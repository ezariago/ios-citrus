#!/usr/bin/env python3
"""Live kernel+userspace console from the phone over its USB serial port.

The XNU port exposes a CDC-ACM function ("Sweet iOS (USB console)"), so macOS
creates /dev/cu.usbmodemXXXX as soon as the kernel brings the DWC3 up (~40 s
into a boot). No root, no network configuration: this just opens the port and
prints whatever the kernel streams.

Usage:
  tools/usb-log.py                 # auto-detect the port, print live
  tools/usb-log.py -o FILE         # also append raw bytes to FILE
  tools/usb-log.py -d /dev/cu.usbmodem00011
"""
import argparse
import glob
import os
import select
import sys
import time


def find_port():
    for pat in ('/dev/cu.usbmodem*', '/dev/tty.usbmodem*'):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[0]
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('-o', '--output', help='append raw bytes to this file')
    ap.add_argument('-d', '--device', help='serial device (default: autodetect)')
    ap.add_argument('--wait', type=int, default=0,
                    help='wait up to N seconds for the port to appear')
    args = ap.parse_args()

    dev = args.device or find_port()
    deadline = time.time() + args.wait
    while not dev and time.time() < deadline:
        time.sleep(1)
        dev = find_port()
    if not dev:
        sys.exit('no /dev/cu.usbmodem* found (is the phone booted with sweetusb=2?)')
    print(f'[{time.strftime("%H:%M:%S")}] reading {dev}', file=sys.stderr, flush=True)

    fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
    out = open(args.output, 'ab', buffering=0) if args.output else None
    total = 0
    last = time.time()
    silent_note = False
    try:
        while True:
            r, _, _ = select.select([fd], [], [], 0.5)
            if not r:
                if total and not silent_note and time.time() - last > 5:
                    print(f'\n[{time.strftime("%H:%M:%S")}] ... silent for '
                          f'{time.time() - last:.0f}s (kernel stopped printing)',
                          file=sys.stderr, flush=True)
                    silent_note = True
                continue
            try:
                data = os.read(fd, 65536)
            except BlockingIOError:
                continue
            except OSError as exc:
                print(f'\n[read error: {exc}]', file=sys.stderr)
                break
            if not data:
                continue
            total += len(data)
            last = time.time()
            silent_note = False
            if out:
                out.write(data)
            sys.stdout.write(data.decode('utf-8', 'replace'))
            sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        if out:
            out.close()
        print(f'\n[{total} bytes]', file=sys.stderr)


if __name__ == '__main__':
    main()
