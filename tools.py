# tools.py

import os
import json
import time
import uuid
import socket
import requests
import subprocess
from ddgs import DDGS
from dotenv import load_dotenv

load_dotenv()

class PresenceScanner:
    @staticmethod
    def is_user_home():
        PHONE_NAME = os.getenv("PHONE_NAME")
        print(f"\n[DEBUG] Starting presence check for {PHONE_NAME}...")

        # --- METHOD A: TAILSCALE CHECK ---
        try:
            print(f"[DEBUG] Checking Tailscale status via CLI...")
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True, text=True, timeout=5
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                peers = data.get("Peer", {})
                found_in_ts = False

                for peer_id, info in peers.items():
                    dns_name = info.get("DNSName", "").lower()
                    if PHONE_NAME.lower() in dns_name:
                        found_in_ts = True
                        online = info.get("Online", False)
                        relay = info.get("Relay", "")
                        cur_addr = info.get("CurAddr", "N/A")
                        
                        print(f"[DEBUG] Tailscale Match: {dns_name}")
                        print(f"[DEBUG] - Online: {online}")
                        print(f"[DEBUG] - Relay: '{relay}' (Empty means direct/local)")
                        print(f"[DEBUG] - CurAddr: {cur_addr}")

                        # If online and NOT relayed, user is home
                        if online:
                            # If the current address is a local one, it's an immediate 'Home'
                            if "192.168.1." in cur_addr:
                                print(f"[PRESENCE] Home via Tailscale Local IP ({cur_addr})")
                                return True
                        elif online and relay == "":
                            print("[PRESENCE] Home via Tailscale (Direct)")
                            return True
                        elif online and relay != "":
                            print("[DEBUG] Device is Online but Relayed (Away)")
                
                if not found_in_ts:
                    print(f"[DEBUG] Device '{PHONE_NAME}' not found in Tailscale peer list.")
            else:
                print(f"[DEBUG] Tailscale CLI returned error code: {result.returncode}")
        except Exception as e:
            print(f"[DEBUG] Tailscale check error: {e}")

        # --- METHOD B: LOCAL ARPING FALLBACK ---
        PHONE_STATIC_IP = os.getenv("PHONE_STATIC_IP")
        print(f"[DEBUG] Falling back to ARPING for {PHONE_STATIC_IP}...")
        try:
            # -c 1 = 1 packet, -w 1 = 1 second timeout
            # We use the 'arping' command which is better at waking up sleeping mobile devices
            arping_cmd = ["sudo", "arping", "-c", "1", "-w", "1", PHONE_STATIC_IP]
            arping_result = subprocess.run(arping_cmd, capture_output=True)
            
            if arping_result.returncode == 0:
                print(f"[PRESENCE] Home via Local ARPING ({PHONE_STATIC_IP})")
                return True
            else:
                print(f"[DEBUG] ARPING to {PHONE_STATIC_IP} failed.")
        except Exception as e:
            print(f"[DEBUG] ARPING command error: {e}")

        print("[PRESENCE] User appears to be AWAY.")
        return False

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

class WebSearcher:
    """Handles web searching via DuckDuckGo."""
    
    @staticmethod
    def search(query: str, max_results: int = 3) -> str:
        """
        Performs a text search and returns a formatted string of results.
        """
        query = query.strip('"').strip("'")
        print(f"[SEARCH] Querying DuckDuckGo: {query}")
        
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            
            if not results:
                print("[SEARCH] No results found.")
                return "No results found for this query."

            # Log results for debugging
            for i, r in enumerate(results):
                content_preview = r['body'][:30].replace('\n', ' ')
                print(f"[SEARCH] Result {i+1}: {r['title']} | {content_preview}...")
            
            # Format results for the LLM context
            formatted_results = "\n".join(
                [f"Source: {r['title']}\nContent: {r['body']}" for r in results]
            )
            return formatted_results

        except Exception as e:
            print(f"[SEARCH ERROR] {str(e)}")
            return f"Search Error: {str(e)}"
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