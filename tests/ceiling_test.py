import socket
import json
import time

DEVICE_IP = "192.168.1.187"
UDP_PORT = 4003
MULTICAST_IP = "239.255.255.250"
MULTICAST_PORT = 4001 # Discovery port is often different

def send_robust_command(turn_on):
    # 1. The Handshake (Scan)
    scan_msg = {
        "msg": {
            "cmd": "scan",
            "data": {"account_topic": "reserve"}
        }
    }
    
    # 2. The Command
    # Trying the '1' vs 'true' workaround again just in case, but usually stick to what works
    cmd_msg = {
        "msg": {
            "cmd": "turn",
            "data": {"value": 1 if turn_on else 0}
        }
    }

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    try:
        # A. Send a scan packet to the device first (unicast is fine if we know IP)
        print("Sending Wake-up Scan...")
        sock.sendto(json.dumps(scan_msg).encode(), (DEVICE_IP, UDP_PORT))
        time.sleep(0.2) # Give it a tiny moment to process
        
        # B. Send the actual command
        print(f"Sending Command: {'ON' if turn_on else 'OFF'}")
        sock.sendto(json.dumps(cmd_msg).encode(), (DEVICE_IP, UDP_PORT))
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        sock.close()

if __name__ == "__main__":
    send_robust_command(False)