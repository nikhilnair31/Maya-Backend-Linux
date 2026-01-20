# tools.py

import os
import json
import time
import uuid
import socket
import requests
import subprocess
from ddgs import DDGS
from statistics import mean
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

class PresenceScanner:
    @staticmethod
    def is_user_home():
        PHONE_NAME = os.getenv("PHONE_NAME")
        PHONE_STATIC_IP = os.getenv("PHONE_STATIC_IP")
        print(f"\n[DEBUG] Starting presence check for {PHONE_NAME}...")

        # --- METHOD A: TAILSCALE CHECK ---
        try:
            print(f"[DEBUG] Checking Tailscale status via CLI...")
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                data = json.loads(result.stdout)
                peers = data.get("Peer", {})
                
                for peer_id, info in peers.items():
                    dns_name = info.get("DNSName", "").lower()
                    if PHONE_NAME.lower() in dns_name:
                        online = info.get("Online", False)
                        # Relay 'iad' (Dulles) means you are connecting via a TS DERP server (Away)
                        # An empty relay string OR "direct" usually means a local/p2p connection.
                        relay = info.get("Relay", "")
                        cur_addr = info.get("CurAddr", "")

                        print(f"[DEBUG] Tailscale Match: {dns_name}")
                        print(f"[DEBUG] - Online: {online} | Relay: '{relay}'")
                        print(f"[DEBUG] - CurAddr: {cur_addr}")

                        if online:
                            # 1. Check if the current address is your local subnet
                            if PHONE_STATIC_IP and PHONE_STATIC_IP in cur_addr:
                                print(f"[PRESENCE] Home via Tailscale (Local IP Match)")
                                return True
                            
                            # 2. If online and NO relay is used, it's a direct connection.
                            # Usually, if you are at home, Tailscale identifies a "direct" path.
                            if relay == "":
                                print("[PRESENCE] Home via Tailscale (Direct/No Relay)")
                                return True
                            
                print(f"[DEBUG] Tailscale indicates device is Remote/Relayed.")
        except Exception as e:
            print(f"[DEBUG] Tailscale check error: {e}")

        # --- METHOD B: LOCAL ARPING FALLBACK ---
        # Increased count and timeout because phones sleep their network chips
        print(f"[DEBUG] Falling back to ARPING for {PHONE_STATIC_IP}...")
        try:
            # -c 3: Send 3 packets to wake up the device
            # -w 2: Wait 2 seconds
            arping_cmd = [
                "sudo",
                "arping",
                "-c",
                "3",
                "-w",
                "2",
                PHONE_STATIC_IP,
            ]
            arping_result = subprocess.run(arping_cmd, capture_output=True)

            if arping_result.returncode == 0:
                print(f"[PRESENCE] Home via Local ARPING ({PHONE_STATIC_IP})")
                return True
        except Exception as e:
            print(f"[DEBUG] ARPING command error: {e}")

        print("[PRESENCE] User appears to be AWAY.")
        return False

class LightsController:
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
    def set_light(
        state: bool, target_string: str, brightness: int = None
    ) -> bool:
        """
        Sets the light power state or brightness for a device or ALL devices.
        :param state: True for 'on', False for 'off'
        :param target_string: Key from the DEVICES dictionary or 'ALL'
        :param brightness: Optional integer 1-100
        :return: Boolean indicating if all operations were successful
        """
        target_upper = target_string.upper()

        if target_upper == "ALL":
            targets = list(LightsController.DEVICES.keys())
        elif target_upper in LightsController.DEVICES:
            targets = [target_upper]
        else:
            print(f"Device '{target_string}' not found.")
            return False

        overall_success = True

        for device_key in targets:
            device_id, sku = LightsController.DEVICES[device_key]

            if not device_id or not sku:
                print(f"Skipping {device_key}: Missing ID or SKU in .env")
                overall_success = False
                continue

            # Send Power Command
            success = LightsController._send_command(
                device_id,
                sku,
                "powerSwitch",
                1 if state else 0,
                "devices.capabilities.on_off",
            )

            # Send Brightness Command if state is True and brightness is provided
            if success and state and brightness is not None:
                # Ensure brightness is within 1-100 range
                val = max(1, min(100, brightness))
                success = LightsController._send_command(
                    device_id,
                    sku,
                    "brightness",
                    val,
                    "devices.capabilities.range",
                )

            if not success:
                overall_success = False

            if target_upper == "ALL":
                time.sleep(0.2)  # Slightly longer sleep for multiple commands

        return overall_success

    @staticmethod
    def _send_command(
        device_id: str,
        sku: str,
        instance: str,
        value: any,
        cap_type: str,
    ) -> bool:
        """Internal helper to send the POST request to Govee."""
        endpoint = f"{LightsController.BASE_URL}/router/api/v1/device/control"
        headers = {
            "Content-Type": "application/json",
            "Govee-API-Key": LightsController.API_KEY,
        }
        payload = {
            "requestId": str(uuid.uuid4()),
            "payload": {
                "sku": sku,
                "device": device_id,
                "capability": {
                    "type": cap_type,
                    "instance": instance,
                    "value": value,
                },
            },
        }

        try:
            response = requests.post(
                endpoint, headers=headers, json=payload, timeout=10
            )
            data = response.json()
            if data.get("code") == 200:
                return True
            else:
                print(f"API Error for {device_id} ({instance}): {data.get('message')}")
                return False
        except Exception as e:
            print(f"Request failed for {device_id}: {e}")
            return False

class WebSearcher:
    @staticmethod
    def search(query: str, max_results: int = 3) -> str:
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

class WeatherManager:
    API_KEY = os.getenv("WEATHER_API_KEY")
    LOCATION = os.getenv("WEATHER_LOCATION")

    @staticmethod
    def get_summary(date_str: str = None) -> str:
        """
        Fetches weather. 
        :param date_str: Format 'YYYY-MM-DD'. If None, fetches current forecast.
        """
        # Determine if we use forecast or history endpoint
        # Default to forecast for today/tomorrow
        mode = "forecast"
        if date_str:
            print(f"[DEBUG] Fetching weather for {WeatherManager.LOCATION} on {date_str}")
            # If the date is in the past, you'd use "history.json" (requires paid plan usually)
            # For simplicity with free tier, we use forecast.json and 'days' or 'dt'
        else:
            print(f"[DEBUG] Fetching current weather for {WeatherManager.LOCATION}")

        if not WeatherManager.API_KEY:
            return "Weather Error: Missing API Key"
            
        try:
            # WeatherAPI uses 'dt' parameter for specific dates
            dt_param = f"&dt={date_str}" if date_str else ""
            url = (
                f"https://api.weatherapi.com/v1/forecast.json"
                f"?key={WeatherManager.API_KEY}"
                f"&q={WeatherManager.LOCATION}"
                f"&days=3{dt_param}&aqi=no&alerts=no"
            )
            
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            data = resp.json()

            # Navigate to the specific day requested (or index 0 for today)
            # WeatherAPI returns the requested 'dt' in the forecastday list
            fc_day = data["forecast"]["forecastday"][0]
            day_data = fc_day["day"]
            ast = fc_day["astro"]
            
            cond = day_data["condition"]["text"]
            high_c = int(day_data["maxtemp_c"])
            low_c  = int(day_data["mintemp_c"])
            avg_temp = int(day_data["avgtemp_c"])
            rain_chance = day_data.get("daily_chance_of_rain", 0)
            sunset_time = ast.get("sunset")

            date_label = date_str if date_str else "Today"
            
            summary = (
                f"Location: {WeatherManager.LOCATION} | Date: {date_label} | "
                f"Conditions: {cond} | Avg: {avg_temp}°C (H:{high_c} L:{low_c}) | "
                f"Rain: {rain_chance}% | Sunset: {sunset_time}"
            )
            print(f"[DEBUG] Weather Result: {summary}")
            return summary
            
        except Exception as e:
            print(f"[WEATHER ERROR] {e}")
            return f"Weather unavailable for {date_str if date_str else 'today'}."