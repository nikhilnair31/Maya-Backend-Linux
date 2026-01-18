import os
import requests
from dotenv import load_dotenv

# Replace with your actual key
load_dotenv()
GOVEE_API_KEY = os.getenv("GOVEE_API_KEY")

url = "https://developer-api.govee.com/v1/devices"
headers = {
    "Govee-API-Key": GOVEE_API_KEY
}

response = requests.get(url, headers=headers)

if response.status_code == 200:
    devices = response.json().get("data", {}).get("devices", [])
    print(f"\nFound {len(devices)} device(s):\n")
    for device in devices:
        print(f"Name:  {device['deviceName']}")
        print(f"ID:    {device['device']}")    # This is your DEVICE_ID
        print(f"Model: {device['model']}")     # This is your DEVICE_MODEL
        print("-" * 30)
else:
    print(f"Error: {response.status_code}")
    print(response.text)