import os
import requests
import json
import uuid
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

API_KEY = os.getenv("GOVEE_API_KEY")
BASE_URL = "https://openapi.api.govee.com"

def get_headers():
    return {
        "Content-Type": "application/json",
        "Govee-API-Key": API_KEY
    }

def list_devices():
    endpoint = "/router/api/v1/user/devices"
    response = requests.get(f"{BASE_URL}{endpoint}", headers=get_headers())
    response.raise_for_status()
    return response.json().get("data", [])

def control_device(device_id, sku, state):
    endpoint = "/router/api/v1/device/control"
    payload = {
        "requestId": str(uuid.uuid4()),
        "payload": {
            "sku": sku,
            "device": device_id,
            "capability": {
                "type": "devices.capabilities.on_off",
                "instance": "powerSwitch",
                "value": state
            }
        }
    }
    response = requests.post(f"{BASE_URL}{endpoint}", headers=get_headers(), json=payload)
    return response.json()

def main():
    if not API_KEY:
        print("Missing API Key in .env")
        return

    try:
        devices = list_devices()
        if not devices:
            print("No devices found.")
            return

        print(f"{'Index':<7} | {'Device Name':<20} | {'SKU':<8} | {'MAC Address':<25} | {'IP Address'}")
        print("-" * 90)

        for i, dev in enumerate(devices):
            index = i
            name = dev.get('deviceName', 'Unknown')
            sku = dev.get('sku', 'N/A')
            # The 'device' field in Govee API is the MAC address
            mac = dev.get('device', 'N/A')
            # IP address might not be available in all API versions/devices
            ip = dev.get('ip', 'N/A') 

            print(f"{index:<7} | {name:<20} | {sku:<8} | {mac:<25} | {ip}")

        choice = input("\nSelect index to toggle (or 'q' to quit): ")
        if choice.lower() == 'q':
            return

        idx = int(choice)
        selected = devices[idx]
        
        action = input("Type 'on' or 'off': ").lower().strip()
        val = 1 if action == "on" else 0
        
        print(f"Sending {action} command to {selected.get('deviceName')}...")
        result = control_device(selected['device'], selected['sku'], val)
        
        if result.get("code") == 200:
            print("Success!")
        else:
            print(f"Failed: {result}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()