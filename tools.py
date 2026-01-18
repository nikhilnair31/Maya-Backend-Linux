import os
import requests
import socket
import json
from ddgs import DDGS
from dotenv import load_dotenv

load_dotenv()

class GoveeController:
    URL = "https://developer-api.govee.com/v1/devices/control"
    API_KEY = os.getenv("GOVEE_API_KEY")
    
    # LAN Settings for Ceiling Light
    CEILING_IP = os.getenv("CEILING_IP")
    UDP_PORT = 4003

    # Centralized Device Configuration
    DEVICES = {
        "AMBIENT LAMP 1": (os.getenv("ID_AMBIENT_1"), os.getenv("GOVEE_BULB_MODEL")),
        "AMBIENT LAMP 2": (os.getenv("ID_AMBIENT_2"), os.getenv("GOVEE_BULB_MODEL")),
        "STANDING LAMP": (os.getenv("ID_STANDING"), os.getenv("GOVEE_BULB_MODEL")),
        "KITCHEN LIGHT 1": (os.getenv("ID_KITCHEN_1"), os.getenv("GOVEE_BULB_MODEL")),
        "KITCHEN LIGHT 2": (os.getenv("ID_KITCHEN_2"), os.getenv("GOVEE_BULB_MODEL")),
        "CEILING LIGHT": (os.getenv("ID_CEILING"), os.getenv("MODEL_CEILING")),
    }

    @staticmethod
    def _control_lan(state: bool) -> bool:
        """Helper to control the Ceiling Light via UDP LAN API"""
        if not GoveeController.CEILING_IP:
            print("[GOVEE] Ceiling IP not set in .env")
            return False
        
        payload = {
            "msg": {
                "cmd": "turn",
                "data": {"value": 1 if state else 0}
            }
        }
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(json.dumps(payload).encode(), (GoveeController.CEILING_IP, GoveeController.UDP_PORT))
            print(f"[GOVEE] LAN Command sent to Ceiling Light: {'ON' if state else 'OFF'}")
            return True
        except Exception as e:
            print(f"[GOVEE LAN ERROR] {e}")
            return False
        finally:
            sock.close()

    @staticmethod
    def set_light(state: bool, target_string: str) -> bool:
        if not GoveeController.API_KEY:
            return False

        # Clean the input string
        raw_target = target_string.strip().upper()
        
        # Handle "ALL" variations (e.g., "ALL LIGHTS", "ALL")
        if "ALL" in raw_target:
            requested_targets = ["ALL"]
        else:
            requested_targets = [t.strip() for t in raw_target.split(",")]
        
        targets_to_act_on = []

        if "ALL" in requested_targets:
            # Control bulbs via Cloud
            cloud_targets = {k: v for k, v in GoveeController.DEVICES.items() if k != "CEILING LIGHT"}
            targets_to_act_on = list(cloud_targets.values())
            # Control Ceiling via LAN
            GoveeController._control_lan(state)
        else:
            for name in requested_targets:
                # Direct check for Ceiling
                if "CEILING" in name:
                    GoveeController._control_lan(state)
                    continue
                
                device_info = GoveeController.DEVICES.get(name)
                if device_info:
                    targets_to_act_on.append(device_info)
                else:
                    # Final attempt: partial match (e.g. "AMBIENT LAMP 1" vs "AMBIENT LAMP 1 LIGHT")
                    found_partial = False
                    for dev_name, info in GoveeController.DEVICES.items():
                        if dev_name in name:
                            targets_to_act_on.append(info)
                            found_partial = True
                            break
                    if not found_partial:
                        print(f"[GOVEE] Device not recognized: {name}")

        if not targets_to_act_on:
            return True # Could be true if only Ceiling was targeted

        # Execute Cloud API calls for bulbs
        success = True
        headers = {
            "Govee-API-Key": GoveeController.API_KEY,
            "Content-Type": "application/json"
        }

        for device_id, model in targets_to_act_on:
            if not device_id or not model:
                continue
            
            payload = {
                "device": device_id,
                "model": model,
                "cmd": {"name": "turn", "value": "on" if state else "off"}
            }
            try:
                resp = requests.put(GoveeController.URL, headers=headers, json=payload, timeout=5)
                if resp.status_code != 200:
                    print(f"[GOVEE CLOUD ERROR] {resp.text}")
                    success = False
            except Exception as e:
                print(f"[GOVEE CLOUD ERROR] {e}")
                success = False
        return success

def web_search(query: str) -> str:
    query = query.strip('"').strip("'")
    print(f"[SEARCH] Querying DuckDuckGo: {query}") # Log the intent
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
        
        if not results:
            print("[SEARCH] No results found.")
            return "No results."

        # Log titles and content previews
        for i, r in enumerate(results):
            content_preview = r['body'][:20].replace('\n', ' ')
            print(f"[SEARCH] Result {i+1}: {r['title']} | Content: {content_preview}...")
        
        formatted_results = "\n".join(
            [f"Source: {r['title']}\nContent: {r['body']}" for r in results]
        )
        return formatted_results

    except Exception as e:
        print(f"[SEARCH ERROR] {str(e)}") # Log the specific error
        return f"Search Error: {str(e)}"