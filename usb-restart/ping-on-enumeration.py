#!/usr/bin/env python3
"""Wait for a fresh modem node and send one receive-probe ping."""
import glob
import os
import subprocess
import time
import sys
if glob.glob('/dev/cu.usbmodem*'):
    sys.exit('Modem already present; start this while the phone is in recovery or fastboot.')
end = time.monotonic() + 180
while time.monotonic() < end:
    ports = sorted(glob.glob('/dev/cu.usbmodem*'))
    if ports:
        print('Found', ports[0], flush=True)
        subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), 'send-ping.py'), ports[0]], check=True)
        sys.exit(0)
    time.sleep(0.05)
sys.exit('No modem appeared within 180 seconds.')
