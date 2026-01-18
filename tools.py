import os
import json
import time
import uuid
import socket
import requests
from ddgs import DDGS
from dotenv import load_dotenv

load_dotenv()

class GoveeController:
    API_KEY = os.getenv("GOVEE_API_KEY")
    BASE_URL = "https://openapi.api.govee.com"
    
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
    def set_light(state: bool, target_string: str) -> bool:
        """
        Sets the light power state for a specific device or ALL devices.
        :param state: True for 'on', False for 'off'
        :param target_string: Key from the DEVICES dictionary or 'ALL'
        :return: Boolean indicating if all operations were successful
        """
        target_upper = target_string.upper()
        
        # Determine which devices to control
        if target_upper == "ALL":
            targets = list(GoveeController.DEVICES.keys())
        elif target_upper in GoveeController.DEVICES:
            targets = [target_upper]
        else:
            print(f"Device '{target_string}' not found.")
            return False

        overall_success = True
        
        for device_key in targets:
            device_id, sku = GoveeController.DEVICES[device_key]
            
            if not device_id or not sku:
                print(f"Skipping {device_key}: Missing ID or SKU in .env")
                overall_success = False
                continue

            success = GoveeController._send_command(device_id, sku, state)
            if not success:
                overall_success = False
            
            # If controlling ALL, a tiny sleep helps avoid rate limit bursts
            if target_upper == "ALL":
                time.sleep(0.1)

        return overall_success

    @staticmethod
    def _send_command(device_id: str, sku: str, state: bool) -> bool:
        """Internal helper to send the POST request."""
        endpoint = f"{GoveeController.BASE_URL}/router/api/v1/device/control"
        headers = {
            "Content-Type": "application/json",
            "Govee-API-Key": GoveeController.API_KEY
        }
        payload = {
            "requestId": str(uuid.uuid4()),
            "payload": {
                "sku": sku,
                "device": device_id,
                "capability": {
                    "type": "devices.capabilities.on_off",
                    "instance": "powerSwitch",
                    "value": 1 if state else 0
                }
            }
        }

        try:
            response = requests.post(endpoint, headers=headers, json=payload, timeout=10)
            data = response.json()
            if data.get("code") == 200:
                return True
            else:
                print(f"API Error for {device_id}: {data.get('message')}")
                return False
        except Exception as e:
            print(f"Request failed for {device_id}: {e}")
            return False

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