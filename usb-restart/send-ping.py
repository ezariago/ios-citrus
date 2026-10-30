#!/usr/bin/env python3
"""Send the receive-only probe's ping to an explicitly named CDC device."""
import argparse
import os
import termios
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('device', help='explicit /dev/cu.usbmodem device')
a = p.parse_args()
if not a.device.startswith('/dev/cu.usbmodem'):
    p.error('expected an explicit /dev/cu.usbmodem device')
fd = os.open(a.device, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
try:
    msg = b'citrus:ping\n'
    n = os.write(fd, msg)
    if n != len(msg):
        raise RuntimeError(f'partial write: {n}/{len(msg)} bytes')
    termios.tcdrain(fd)
finally:
    os.close(fd)
print('Ping written; check the existing USB log for CITRUS USB: ping received.')
