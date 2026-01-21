import os
import json
import requests
import uuid
from dotenv import load_dotenv

load_dotenv()

# Configuration
API_KEY = os.getenv("GOVEE_API_KEY")
BASE_URL = "https://openapi.api.govee.com"

# The devices you want to test
DEVICES = {
    "AMBIENT LAMP 1": (os.getenv("ID_AMBIENT_1"), os.getenv("GOVEE_BULB_MODEL")),
    "AMBIENT LAMP 2": (os.getenv("ID_AMBIENT_2"), os.getenv("GOVEE_BULB_MODEL")),
    "STANDING LAMP": (os.getenv("ID_STANDING"), os.getenv("GOVEE_BULB_MODEL")),
    "KITCHEN LIGHT 1": (os.getenv("ID_KITCHEN_1"), os.getenv("GOVEE_BULB_MODEL")),
    "KITCHEN LIGHT 2": (os.getenv("ID_KITCHEN_2"), os.getenv("GOVEE_BULB_MODEL")),
}

def get_detailed_state(name, device_id, sku):
    if not device_id or not sku:
        print(f"[-] Skipping {name}: Missing ID/SKU")
        return

    endpoint = f"{BASE_URL}/router/api/v1/device/state"
    headers = {
        "Content-Type": "application/json",
        "Govee-API-Key": API_KEY,
    }
    payload = {
        "requestId": str(uuid.uuid4()),
        "payload": {"sku": sku, "device": device_id}
    }

    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=10)
        data = response.json()
        
        if data.get("code") != 200:
            print(f"[!] Error {name}: {data.get('msg')}")
            return

        # Extract capabilities from the payload
        caps = data.get("payload", {}).get("capabilities", [])
        
        # We will store what we find to demonstrate how to "Snapshot"
        snapshot = {
            "power": None,
            "brightness": None,
            "color_rgb": None,
            "color_temp": None
        }

        for cap in caps:
            instance = cap.get("instance")
            val = cap.get("state", {}).get("value")
            
            if instance == "powerSwitch":
                snapshot["power"] = "ON" if val == 1 else "OFF"
            elif instance == "brightness":
                snapshot["brightness"] = val
            elif instance == "colorRgb":
                snapshot["color_rgb"] = val
            elif instance == "colorTemperatureK":
                snapshot["color_temp"] = val

        print(f"REPORT FOR: {name}")
        print(f"  > Power:      {snapshot['power']}")
        print(f"  > Brightness: {snapshot['brightness']}%")
        
        # Logic to determine if light is in Kelvin mode or RGB mode
        if snapshot['color_temp'] and snapshot['color_temp'] > 0:
            print(f"  > Mode:       White Balance (Kelvin)")
            print(f"  > Value:      {snapshot['color_temp']}K")
        elif snapshot['color_rgb'] is not None:
            print(f"  > Mode:       Color (RGB)")
            print(f"  > Value:      Decimal: {snapshot['color_rgb']} | Hex: #{snapshot['color_rgb']:06x}")
        else:
            print(f"  > Mode:       Unknown")
        
        print("-" * 30)

    except Exception as e:
        print(f"[X] Failed {name}: {e}")

if __name__ == "__main__":
    if not API_KEY:
        print("MISSING API KEY")
    else:
        print(f"Govee Diagnostic - Checking {len(DEVICES)} devices...\n")
        for name, (d_id, sku) in DEVICES.items():
            get_detailed_state(name, d_id, sku)