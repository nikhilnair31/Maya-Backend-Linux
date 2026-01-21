# tools.py

import os
import json
import time
import uuid
import socket
import requests
import subprocess
import platform
import logging
import shutil
from ddgs import DDGS
from statistics import mean
from datetime import datetime, timezone
from dotenv import load_dotenv

# Try to import scapy for Layer 2 discovery
try:
    from scapy.all import arping
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False

load_dotenv()

class PresenceScanner:
    @staticmethod
    def is_user_home():
        """
        Main entry point for checking user presence using ARP, ICMP, and Tailscale.
        """
        WIFI_IP = os.getenv("PHONE_STATIC_IP")
        TS_IP = os.getenv("PHONE_TAILSCALE_IP") or os.getenv("PHONE_NAME")
        INTERFACE = os.getenv("NETWORK_INTERFACE") # e.g., 'eth0' or 'wlan0'
        
        # 1. Try ARP Scan (Layer 2 - Most reliable for local)
        if SCAPY_AVAILABLE and WIFI_IP:
            try:
                # Use specified interface if available to avoid Scapy routing issues
                ans, _ = arping(WIFI_IP, iface=INTERFACE, timeout=1, verbose=0) if INTERFACE \
                    else arping(WIFI_IP, timeout=1, verbose=0)
                if len(ans) > 0:
                    print(f"[PRESENCE] Home via ARP ({WIFI_IP})")
                    return True
            except Exception as e:
                print(f"[DEBUG] ARP Error: {e}")

        # 2. Try Standard Ping (Layer 3)
        if WIFI_IP:
            is_windows = platform.system().lower() == "windows"
            param = "-n" if is_windows else "-c"
            timeout_param = "-w" if is_windows else "-W"
            timeout_val = "1000" if is_windows else "1"
            
            # Wake up the radio first
            subprocess.run(["ping", param, "1", timeout_param, timeout_val, WIFI_IP], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Actual check
            cmd = ["ping", param, "1", timeout_param, timeout_val, WIFI_IP]
            if subprocess.run(cmd, stdout=subprocess.DEVNULL).returncode == 0:
                print(f"[PRESENCE] Home via ICMP Ping ({WIFI_IP})")
                return True

        # 3. Try Tailscale Ping (The 'Sleep-breaker')
        if TS_IP and shutil.which("tailscale"):
            # tailscale ping is excellent for waking up mobile devices
            ts_cmd = ["tailscale", "ping", "-c", "1", "--timeout", "2s", TS_IP]
            try:
                ts_result = subprocess.run(ts_cmd, capture_output=True, text=True)
                if ts_result.returncode == 0 and "pong" in ts_result.stdout.lower():
                    # Check if it's a direct connection to confirm 'Home' status
                    # If you want to be home even via DERP (Relay), remove 'via DERP' check
                    if "via DERP" not in ts_result.stdout:
                        print(f"[PRESENCE] Home via Tailscale Direct ({TS_IP})")
                        return True
                    else:
                        print(f"[DEBUG] User reachable via Tailscale Relay (Away)")
            except Exception as e:
                print(f"[DEBUG] Tailscale Ping Error: {e}")

        print("[PRESENCE] User appears to be AWAY.")
        return False

class LightsController:
    API_KEY = os.getenv("GOVEE_API_KEY")
    BASE_URL = "https://openapi.api.govee.com"
    STATE_FILE = "lights_snapshot.json"

    DEVICES = {
        "AMBIENT LAMP 1": (os.getenv("ID_AMBIENT_1"), os.getenv("GOVEE_BULB_MODEL")),
        "AMBIENT LAMP 2": (os.getenv("ID_AMBIENT_2"), os.getenv("GOVEE_BULB_MODEL")),
        "STANDING LAMP": (os.getenv("ID_STANDING"), os.getenv("GOVEE_BULB_MODEL")),
        "KITCHEN LIGHT 1": (os.getenv("ID_KITCHEN_1"), os.getenv("GOVEE_BULB_MODEL")),
        "KITCHEN LIGHT 2": (os.getenv("ID_KITCHEN_2"), os.getenv("GOVEE_BULB_MODEL")),
        "CEILING LIGHT": (os.getenv("ID_CEILING"), os.getenv("MODEL_CEILING")),
    }
    
    @staticmethod
    def get_device_state(device_key: str):
        """Fetches current state of a device from Govee API."""
        device_id, sku = LightsController.DEVICES.get(device_key, (None, None))
        
        if not device_id:
            print(f"Device key '{device_key}' not found in configuration.")
            return None

        print(f"Fetching state for {device_key} ({device_id})...")
        
        endpoint = f"{LightsController.BASE_URL}/router/api/v1/device/state"
        headers = {
            "Content-Type": "application/json",
            "Govee-API-Key": LightsController.API_KEY,
        }
        payload = {
            "requestId": str(uuid.uuid4()),
            "payload": {"sku": sku, "device": device_id},
        }

        try:
            response = requests.post(endpoint, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            resp_data = response.json()

            if resp_data.get("code") != 200:
                print(
                    f"Govee API error for {device_key}: {resp_data.get('message', 'Unknown Error')}"
                )
                return None

            caps = resp_data.get("payload", {}).get("capabilities", [])
            state = {
                "brightness": 50,
                "color_temp": 2700,
                "color_rgb": None,
            }

            for cap in caps:
                inst = cap.get("instance")
                val = cap.get("state", {}).get("value")
                if inst == "brightness":
                    state["brightness"] = val
                elif inst == "colorTemperatureK":
                    state["color_temp"] = val
                elif inst == "colorRgb":
                    state["color_rgb"] = val

            print(f"Successfully retrieved state for {device_key}: {state}")
            return state

        except requests.exceptions.RequestException as e:
            print(f"Network error fetching state for {device_key}: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error fetching state for {device_key}: {e}")
            return None

    @staticmethod
    def save_all_states():
        """Snapshots all lights to a JSON file."""
        snapshot = {}
        for name in LightsController.DEVICES:
            state = LightsController.get_device_state(name)
            if state: snapshot[name] = state
        with open(LightsController.STATE_FILE, "w") as f:
            json.dump(snapshot, f)
        return True

    @staticmethod
    def restore_all_states():
        """Restores lights from the JSON file."""
        if not os.path.exists(LightsController.STATE_FILE): return False
        with open(LightsController.STATE_FILE, "r") as f:
            snapshot = json.load(f)
        
        for name, state in snapshot.items():
            # Restore Power
            LightsController.set_light(state["power"] == 1, name)
            if state["power"] == 1:
                # Restore Brightness
                LightsController.set_light(True, name, brightness=state["brightness"])
                # Restore Color (Kelvin takes priority if present)
                if state.get("color_temp"):
                    LightsController.set_light(True, name, color_temp=state["color_temp"])
            time.sleep(0.2)
        return True

    @staticmethod
    def set_light(state: bool, target_string: str, brightness: int = None, color_temp: int = None) -> bool:
        target_upper = target_string.upper()
        targets = [target_upper] if target_upper in LightsController.DEVICES else (list(LightsController.DEVICES.keys()) if target_upper == "ALL" else [])
        
        overall_success = True
        for device_key in targets:
            device_id, sku = LightsController.DEVICES[device_key]
            # Power
            success = LightsController._send_command(device_id, sku, "powerSwitch", 1 if state else 0, "devices.capabilities.on_off")
            # Brightness
            if success and state and brightness is not None:
                success = LightsController._send_command(device_id, sku, "brightness", max(1, min(100, brightness)), "devices.capabilities.range")
            # Temp
            if success and state and color_temp is not None:
                success = LightsController._send_command(device_id, sku, "colorTemperatureK", color_temp, "devices.capabilities.color_setting")
            if not success: overall_success = False
        return overall_success

    @staticmethod
    def _send_command(device_id, sku, instance, value, cap_type):
        endpoint = f"{LightsController.BASE_URL}/router/api/v1/device/control"
        payload = {"requestId": str(uuid.uuid4()), "payload": {"sku": sku, "device": device_id, "capability": {"type": cap_type, "instance": instance, "value": value}}}
        try:
            res = requests.post(endpoint, headers={"Govee-API-Key": LightsController.API_KEY}, json=payload, timeout=10)
            return res.json().get("code") == 200
        except: return False

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