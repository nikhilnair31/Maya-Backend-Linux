import socket
import json

def find_govee_ip():
    # Govee standard discovery broadcast address and port
    BROADCAST_IP = "239.255.255.250"
    PORT = 4001
    
    # The "scan" message from the documentation you provided
    search_msg = {
        "msg": {
            "cmd": "scan",
            "data": {"account_topic": "reserve"}
        }
    }

    # Setup the UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5.0) # Wait 5 seconds for a response
    
    try:
        print("Searching for your H60A1 on the local network...")
        sock.sendto(json.dumps(search_msg).encode(), (BROADCAST_IP, PORT))
        
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                response = json.loads(data.decode())
                # Check if this is the H60A1
                if response["msg"]["data"]["sku"] == "H60A1":
                    print(f"\nSUCCESS! Found your Ceiling Light:")
                    print(f"IP Address: {response['msg']['data']['ip']}")
                    print(f"Device ID:  {response['msg']['data']['device']}")
                    return response['msg']['data']['ip']
            except socket.timeout:
                print("\nNo devices responded. Check if LAN Control is ON in the app.")
                break
    finally:
        sock.close()

if __name__ == "__main__":
    find_govee_ip()