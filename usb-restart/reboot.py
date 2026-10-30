#!/usr/bin/env python3
"""Request fastboot or recovery from the PMIC-aware Citrus USB kernel."""
import argparse
import glob
import os
import sys
import termios
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('mode', choices=('fastboot', 'recovery'))
p.add_argument('--device', help='explicit /dev/cu.usbmodem device')
a = p.parse_args()
ports = [a.device] if a.device else sorted(glob.glob('/dev/cu.usbmodem*'))
if len(ports) != 1 or not ports[0].startswith('/dev/cu.usbmodem'):
    sys.exit('Select exactly one /dev/cu.usbmodem device using --device.')
fd = os.open(ports[0], os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
try:
    data = ('citrus:reboot:' + a.mode + '\n').encode('ascii')
    n = os.write(fd, data)
    if n != len(data): raise RuntimeError(f'partial write: {n}/{len(data)}')
    termios.tcdrain(fd)
finally:
    os.close(fd)
print(f'Request written to {ports[0]}; verify the target USB mode separately.')
