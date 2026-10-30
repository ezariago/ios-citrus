#!/usr/bin/env python3
"""Send one fastboot request to the experimental reset kernel on enumeration."""
import glob
import os
import sys
import termios
import time
if glob.glob('/dev/cu.usbmodem*'):
    sys.exit('Modem already present; start while the phone is in recovery or fastboot.')
deadline = time.monotonic() + 180
while time.monotonic() < deadline:
    ports = sorted(glob.glob('/dev/cu.usbmodem*'))
    if ports:
        fd = os.open(ports[0], os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            cmd = b'citrus:reboot:fastboot\n'
            count = os.write(fd, cmd)
            if count != len(cmd): raise RuntimeError(f'partial write {count}/{len(cmd)}')
            termios.tcdrain(fd)
        finally:
            os.close(fd)
        print('Fastboot request written to', ports[0], flush=True)
        sys.exit(0)
    time.sleep(0.05)
sys.exit('No modem appeared within 180 seconds.')
