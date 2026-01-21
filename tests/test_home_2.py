import time
import subprocess
import platform
import logging
import shutil

try:
    from scapy.all import arping
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PresenceScanner")

class PresenceScanner:
    def __init__(self, wifi_ip, interface=None, tailscale_ip=None, use_arp=True):
        """
        :param wifi_ip: The static local IP (e.g. 192.168.1.50)
        :param interface: The physical network interface (e.g., 'eth0', 'wlan0')
        :param tailscale_ip: The Tailscale IP or Hostname.
        :param use_arp: If True, attempts Layer 2 detection.
        """
        self.wifi_ip = wifi_ip
        self.tailscale_ip = tailscale_ip
        self.interface = interface  # Store the specific interface
        self.use_arp = use_arp and SCAPY_AVAILABLE
        self.is_windows = platform.system().lower() == "windows"

        if use_arp and not SCAPY_AVAILABLE:
            logger.warning("ARP requested but 'scapy' missing. Falling back to Ping.")

    def _ping(self, target_ip):
        if not target_ip: return False
        param = '-n' if self.is_windows else '-c'
        timeout_param = '-w' if self.is_windows else '-W'
        timeout_val = '1000' if self.is_windows else '1'
        command = ['ping', param, '1', timeout_param, timeout_val, target_ip]
        try:
            subprocess.check_output(command, stderr=subprocess.STDOUT)
            return True
        except subprocess.CalledProcessError:
            return False

    def _tailscale_ping(self):
        if not self.tailscale_ip or not shutil.which("tailscale"):
            return False
        
        # We explicitly ping via tailscale cli
        command = ['tailscale', 'ping', '-c', '1', '--timeout', '2s', self.tailscale_ip]
        try:
            subprocess.check_call(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except subprocess.CalledProcessError:
            return False

    def _arp_check(self):
        if not self.use_arp: return False
        try:
            # CRITICAL FIX: Pass the 'iface' argument
            # verbose=0 is silent, timeout=1 is fast
            if self.interface:
                ans, _ = arping(self.wifi_ip, iface=self.interface, timeout=1, verbose=0)
            else:
                ans, _ = arping(self.wifi_ip, timeout=1, verbose=0)
            
            return len(ans) > 0
        except Exception as e:
            logger.error(f"ARP scan error: {e}")
            return False

    def scan(self):
        # 1. ARP (Local)
        if self._arp_check():
            logger.info(f"ARP found {self.wifi_ip}")
            return True
        
        # 2. Ping (Local)
        if self._ping(self.wifi_ip):
            logger.info(f"Ping found {self.wifi_ip}")
            return True
            
        # 3. Tailscale (Remote/Sleep)
        if self.tailscale_ip and self._tailscale_ping():
            logger.info(f"Tailscale found {self.tailscale_ip}")
            return True

        return False

# CONFIGURATION
PHONE_WIFI_IP = "192.168.1.228"
PHONE_TAILSCALE_IP = "100.121.58.117"

# CHANGE THIS to your actual interface name found via 'ip a' or 'ifconfig'
# Common names: 'eth0', 'eno1', 'enp3s0', 'wlan0'
NETWORK_INTERFACE = "wlp0s20f3" 

scanner = PresenceScanner(
    wifi_ip=PHONE_WIFI_IP, 
    tailscale_ip=PHONE_TAILSCALE_IP,
    interface=NETWORK_INTERFACE, 
    use_arp=True 
)

if __name__ == "__main__":
    logger.info(f"Scanning for phone on {NETWORK_INTERFACE}...")
    while True:
        if scanner.scan():
            print("Action: Phone is HERE.")
        else:
            print("Action: Phone is AWAY.")
        time.sleep(10)