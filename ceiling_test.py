import socket
import json
import time

# The IP we just found
DEVICE_IP = "192.168.1.187"
UDP_PORT = 4003

def send_command(value):
    msg = {
        "msg": {
            "cmd": "turn",
            "data": {"value": value}
        }
    }
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(json.dumps(msg).encode(), (DEVICE_IP, UDP_PORT))
        print(f"Sent command: {'ON' if value == 1 else 'OFF'}")
    finally:
        sock.close()

if __name__ == "__main__":
    print("Testing Ceiling Light...")
    send_command(1)  # Turn ON
    time.sleep(2)
    send_command(0)  # Turn OFF