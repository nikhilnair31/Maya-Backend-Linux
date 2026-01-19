import os
import sys
import time
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from tools import PresenceScanner
except ImportError:
    print("Error: Could not find tools/PresenceScanner. Check your folder structure.")
    sys.exit(1)

if __name__ == "__main__":
    print("Starting Tailscale Presence Monitor...")
    while True:
        try:
            PresenceScanner.is_user_home()
        except Exception as e:
            print(f"Error in monitor loop: {e}")
        time.sleep(5)