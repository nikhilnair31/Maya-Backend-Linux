# main.py

import os
import re
import json
import uuid
import torch
import shutil
import asyncio
import requests
import edge_tts
from pydantic import BaseModel
from dotenv import load_dotenv
from transformers import pipeline
from datetime import datetime, timedelta
from fastapi.responses import FileResponse
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from tools import WeatherManager, WebSearcher, LightsController, PresenceScanner

# Configuration
load_dotenv()
OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT")
MODEL_NAME = os.getenv("MODEL_NAME")
TEMP_DIR = os.getenv("TEMP_DIR")
DEVICE_MAP = {
    "AMBIENT LAMP 2": os.getenv("ID_AMBIENT_2"),
    "STANDING LAMP": os.getenv("ID_STANDING"),
    "AMBIENT LAMP 1": os.getenv("ID_AMBIENT_1"),
    "KITCHEN LIGHT 1": os.getenv("ID_KITCHEN_1"),
    "KITCHEN LIGHT 2": os.getenv("ID_KITCHEN_2"),
    "ALL": "ALL"
}

# Load User Profile
PROFILE_PATH = "user_profile.json"
if os.path.exists(PROFILE_PATH):
    with open(PROFILE_PATH, "r") as f:
        USER_PROFILE = json.load(f)
else:
    # Fallback if file is missing
    USER_PROFILE = {"name": "User", "location": "Unknown", "interests": [], "preferences": ""}

app = FastAPI()
chat_history = []

if os.path.exists(TEMP_DIR):
    shutil.rmtree(TEMP_DIR)
os.makedirs(TEMP_DIR)

pipe = pipeline(
    "automatic-speech-recognition",
    model="openai/whisper-base",
    device="cuda:0",
    torch_dtype=torch.float32,
    chunk_length_s=30,
)

def clean_header_text(text: str) -> str:
    if not text:
        return ""
    # 1. Remove newlines, tabs, and carriage returns
    clean = text.replace("\n", " ").replace("\r", " ").replace("\t", " ").strip()
    
    # 2. Force encoding to ASCII and ignore errors to strip emojis/special chars
    # This is the most reliable way to satisfy h11/uvicorn header requirements
    clean = clean.encode("ascii", "ignore").decode("ascii")
    
    # 3. Use Regex to keep only basic printable characters just in case
    clean = re.sub(r'[^\x20-\x7E]', '', clean)
    
    # 4. Truncate for header safety
    return (clean[:100] + "..") if len(clean) > 100 else clean

def remove_file(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print(f"Error deleting temp file {path}: {e}")

@app.post("/process")
async def process_input(
    background_tasks: BackgroundTasks,
    text_input: str = Form(None),
    audio_file: UploadFile = File(None),
    return_audio: bool = Form(False),
):
    print(f"\n-----STARTED PROCESSING INPUT-----")
    global chat_history
    prompt = ""

    # 0. Input Handling
    if audio_file:
        audio_path = f"{TEMP_DIR}/{uuid.uuid4()}_{audio_file.filename}"
        with open(audio_path, "wb") as buffer:
            buffer.write(await audio_file.read())
        try:
            outputs = pipe(audio_path, batch_size=24, generate_kwargs={"language": "english"})
            prompt = outputs["text"]
            print(f"[STT] User said: {prompt}")
        finally:
            remove_file(audio_path)
    elif text_input:
        prompt = text_input
    else:
        raise HTTPException(status_code=400, detail="No input")
    
    # 1. GATHER ALL CONTEXT (Always happens)
    is_home = PresenceScanner.is_user_home()
    
    # Date/Weather Context Extraction
    date_extraction_prompt = (
        f"Current Date: {datetime.now().strftime('%Y-%m-%d')}\n"
        f"User said: '{prompt}'\n"
        f"If the user is asking about weather for a specific time, output YYYY-MM-DD. Otherwise 'TODAY'."
    )
    try:
        extracted_date = requests.post(OLLAMA_ENDPOINT, json={
            "model": MODEL_NAME, "prompt": date_extraction_prompt, "stream": False, "options": {"temperature": 0}
        }).json().get("response", "").strip()
    except:
        extracted_date = "TODAY"
    
    target_date = None if "TODAY" in extracted_date.upper() else extracted_date
    weather_info = WeatherManager.get_summary(target_date)

    # Build a comprehensive System Identity
    profile_parts = [f"{k.capitalize()}: {v}" for k, v in USER_PROFILE.items() if v]
    profile_summary = " | ".join(profile_parts)
    presence_str = "User is currently at home." if is_home else "User is currently away."
    
    system_identity = (
        f"You are Maya, a helpful smart home AI.\n"
        f"User Profile: {profile_summary}\n"
        f"User Presence: {presence_str}\n"
        f"Weather/Environment: {weather_info}\n"
        f"Current Time: {datetime.now().strftime('%H:%M')}\n"
        f"Style: {USER_PROFILE.get('preferences', 'Concise and friendly')}\n"
    )

    # Update Chat History
    chat_history.append(f"User: {prompt}")
    chat_history = chat_history[-6:]
    history_context = "\n".join(chat_history)

    # 2. CATEGORIZATION ROUTER
    cat_prompt = (
        f"Recent Conversation:\n{history_context}\n\n"
        f"Analyze the new input: '{prompt}'\n"
        f"Categories: [LIGHT_COMMAND, GENERAL_QUESTION, CONVERSATIONAL]\n"
        f"Rules:\n"
        f"- LIGHT_COMMAND: Use ONLY if the user is giving a direct order or expressing a current need for change (e.g., 'turn on', 'make it brighter', 'too dark'). If the user is describing a state or using a metaphor (e.g., 'the lights are dim', 'my eyes are tired'), do NOT use this.\n"
        f"- GENERAL_QUESTION: Factual/world data.\n"
        f"- CONVERSATIONAL: Greetings, statements about feelings, or casual chat.\n"
        f"Note: If the user asks for your name or who you are, it is ALWAYS CONVERSATIONAL.\n"
        f"Respond with only the category name."
    )
    try:
        cat_resp = requests.post(
            OLLAMA_ENDPOINT,
            json={
                "model": MODEL_NAME, 
                "prompt": cat_prompt, 
                "stream": False, 
                "options": {"temperature": 0}
            },
        ).json().get("response", "").strip().upper()
    except Exception:
        cat_resp = "CONVERSATIONAL"
    
    # 3. EXECUTION BRANCHES
    context = ""
    if "LIGHT_COMMAND" in cat_resp:
        # Optimal Router Prompt for Qwen 2.5 3B
        devices_list = ", ".join(LightsController.DEVICES.keys())

        decision_prompt = f"""<|im_start|>system
            You are a smart home lighting controller.
            
            # Goals:
            - Identify the ACTION (ON or OFF).
            - Identify the TARGET ({devices_list} or ALL).
            - Identify BRIGHTNESS (0-100) if a number is mentioned.

            # Rules:
            1. If the user mentions a number (e.g., "100", "set to 50", "20%"), include it as "brightness": <number>.
            2. If no number is mentioned, do NOT include the brightness key.
            3. "action": "OFF" is only for turning completely off. 
            4. "action": "ON" is for turning on OR changing brightness.
            5. Return ONLY valid JSON.

            # Examples:
            User: "All lights 100" -> {{"action": "ON", "target": "ALL", "brightness": 100}}
            User: "kitchen off" -> {{"action": "OFF", "target": "KITCHEN LIGHT 1"}}
            User: "dim ambient lamp to 5" -> {{"action": "ON", "target": "AMBIENT LAMP 1", "brightness": 5}}
            <|im_end|>
            <|im_start|>user
            {prompt}
            <|im_end|>
            <|im_start|>assistant
        """
        print(f"[DEBUG] Input Prompt: {decision_prompt}")
        
        try:
            resp = requests.post(
                OLLAMA_ENDPOINT,
                json={
                    "model": MODEL_NAME, 
                    "prompt": decision_prompt, 
                    "stream": False, 
                    "options": {"temperature": 0, "stop": ["<|im_end|>", "</tool_call>"]}
                },
            ).json()
            
            decision_resp = resp.get("response", "").strip()
            print(f"[DEBUG] Raw Router Output: {decision_resp}")
        
            # --- ADD THIS CHECK ---
            if "NO_ACTION" in decision_resp or "{" not in decision_resp:
                print("[DEBUG] False positive light command detected. Diverting to conversational.")
                cat_resp = "CONVERSATIONAL" # Force it into the chat branch instead
            else:
                try:
                    # 1. Strip Markdown and XML tags
                    json_clean = decision_resp.replace("<tool_call>", "").replace("</tool_call>", "")
                    json_clean = json_clean.replace("```json", "").replace("```", "").strip()
                    
                    tool_data = json.loads(json_clean)
                    
                    # 2. Flexible parameter extraction
                    # This handles both {"parameters": {"action": "ON"}} AND {"action": "ON"}
                    if "parameters" in tool_data:
                        params = tool_data["parameters"]
                    else:
                        params = tool_data
                        
                    action_str = params.get("action", "OFF").upper()
                    target = params.get("target", "ALL").upper()
                    brightness_val = params.get("brightness") # May be None

                    action_bool = (action_str == "ON")
                    
                    # Pass brightness to the controller
                    success = LightsController.set_light(action_bool, target, brightness=brightness_val)
                    
                    if success:
                        if brightness_val:
                            context = f"SUCCESS: {target} set to {brightness_val}% brightness"
                        else:
                            context = f"SUCCESS: {target} turned {action_str}"
                    else:
                        context = "FAILED: I couldn't reach the lights."
                    
                except Exception as e:
                    print(f"[ERROR] Parsing failed: {e}")
                    context = "I couldn't process that light command."
                    # Don't switch to CONVERSATIONAL here, let it finish with the error context
            
        except Exception as e:
            print(f"[WARN] Routing/Parsing Error: {e}")
            context = "API Call failed"
    elif "GENERAL_QUESTION" in cat_resp:
        rewrite_prompt = (
            f"User Profile Summary: {profile_summary}.\n"
            f"Conversation History:\n{history_context}\n\n"
            f"User's new question: {prompt}\n"
            f"Rewrite this question into a standalone search engine query "
            f"that captures the full context (who 'she', 'it', or 'they' refers to). "
            f"Respond with only the search query."
        )
        try:
            search_query_resp = requests.post(
                OLLAMA_ENDPOINT,
                json={
                    "model": MODEL_NAME, 
                    "prompt": rewrite_prompt, 
                    "stream": False, 
                    "options": {"temperature": 0}
                },
            ).json().get("response", "").strip().replace('"', '')
        except Exception:
            search_query_resp = prompt # Fallback to original

        print(f"[ACTION] Searching for expanded query: {search_query_resp}")
        
        search_results = WebSearcher.search(search_query_resp)
        context = f"Search Results: {search_results}"
    else:
        # DEFAULT / CONVERSATIONAL branch
        print(f"[ACTION] Handling as general chat")
        context = "No external tools needed. Respond naturally."
    
    # 4. Final Humanized Response
    try:
        is_search = "Search Results:" in context
        is_light = "SUCCESS:" in context

        # 2. Define Persona using the dynamic summary
        system_rules = (
            f"Role: You are Maya, a smart home assistant."
            f"User Profile Summary: {profile_summary}."
            f"Weather Outside: {weather_info}."
            f"Persona Style: {USER_PROFILE.get('preferences', 'Concise')}."
            f"Instruction: Address the user as {USER_PROFILE.get('nickname', 'User')}."
        )
        
        if is_light:
            final_prompt = (
                f"{system_rules}\n"
                f"Context: {context}\n"
                f"Task: Give a very short confirmation of the light action. "
                f"Max 5 words. Use your specific persona/style."
            )
        elif is_search:
            final_prompt = (
                f"{system_rules}\n"
                f"Search Data: {context}\n"
                f"User Asked: {prompt}\n"
                f"Task: Summarize the news naturally. Under 25 words."
            )
        else:
            final_prompt = (
                f"{system_rules}\n"
                f"User said: {prompt}\n"
                f"Task: Reply briefly. One short sentence only. You are Maya."
            )
        print(f"[DEBUG] final_prompt: {final_prompt}")

        response = requests.post(
            OLLAMA_ENDPOINT,
            json={
                "model": MODEL_NAME,
                "prompt": final_prompt,
                "stream": False,
                "options": {
                    "stop": ["\n", "<|"], 
                    "temperature": 0.8, # Higher temperature prevents empty/stuck responses
                    "num_predict": 50    # Limit output length at the model level
                },
            },
        )
        print(f"[DEBUG] response: {response}")
        
        llm_text = response.json().get("response", "").strip().replace('"', '')
        print(f"[DEBUG] llm_text: {llm_text}")
        llm_text = re.sub(r"<\|.*?\|>", "", llm_text).strip()
        print(f"[DEBUG] llm_text: {llm_text}")

        # Emergency Fallback for empty strings
        if not llm_text:
            if is_light: llm_text = "Lights updated."
            else: llm_text = "I'm on it."

        print(f"[FINAL] Maya: {llm_text}")
    except Exception as e:
        print(f"Error in final response: {e}")
        llm_text = "Handled."

    # 5. Audio Return
    if return_audio:
        output_path = f"{TEMP_DIR}/out_{uuid.uuid4()}.mp3"
        communicate = edge_tts.Communicate(llm_text, "en-US-GuyNeural", rate="+25%")
        await communicate.save(output_path)
        background_tasks.add_task(remove_file, output_path)
        return FileResponse(output_path, media_type="audio/mpeg", headers={"X-LLM-Response": clean_header_text(llm_text)})

    return {"response": llm_text, "transcription": prompt}