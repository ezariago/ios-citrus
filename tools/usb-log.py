#!/usr/bin/env python3
"""Live kernel+userspace console from the phone over its USB serial port.

The XNU port exposes a CDC-ACM function ("Sweet iOS (USB console)"), so macOS
creates /dev/cu.usbmodemXXXX as soon as the kernel brings the DWC3 up (~40 s
into a boot). No root, no network configuration: this just opens the port and
prints whatever the kernel streams.

The USB console thread in the kernel keeps the byte it is sending pending until
the host reads it, so if this process dies the console "goes silent" while the
kernel keeps running. That is exactly what happened to the smp4 boot at T=408 s:
the log stopped, the kernel did not. This tool therefore reconnects and reopens
the port instead of exiting on a read error or a long silence, and it keeps the
in-flight chunk gap explicit.

Usage:
  tools/usb-log.py                 # auto-detect the port, print live
  tools/usb-log.py -o FILE         # also append raw bytes to FILE
  tools/usb-log.py -d /dev/cu.usbmodem00011
  tools/usb-log.py --reopen-after 30
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


def open_dev(dev, wait_s):
    deadline = time.time() + wait_s
    while True:
        if dev and os.path.exists(dev):
            try:
                return dev, os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                pass
        if time.time() >= deadline:
            return None, None
        time.sleep(1)
        dev = find_port() or dev


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('-o', '--output', help='append raw bytes to this file')
    ap.add_argument('-d', '--device', help='serial device (default: autodetect)')
    ap.add_argument('--wait', type=int, default=0,
                    help='wait up to N seconds for the port to appear')
    ap.add_argument('--reopen-after', type=int, default=30,
                    help='reopen the port after N seconds without data (0 disables)')
    ap.add_argument('--no-reconnect', action='store_true',
                    help='exit on the first read error instead of reconnecting')
    args = ap.parse_args()

    dev = args.device or find_port()
    if not dev:
        dev, fd = open_dev(dev, args.wait)
        if not fd:
            sys.exit('no /dev/cu.usbmodem* found (is the phone booted with sweetusb=2?)')
    else:
        try:
            fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            sys.exit(f'cannot open {dev}: {exc}')

    out = open(args.output, 'ab', buffering=0) if args.output else None
    total = 0
    gaps = 0
    reconnect = not args.no_reconnect
    last = time.time()
    silent_note = False
    print(f'[{time.strftime("%H:%M:%S")}] reading {dev}', file=sys.stderr, flush=True)

    while True:
        reopen = False
        try:
            while True:
                r, _, _ = select.select([fd], [], [], 0.5)
                now = time.time()
                if not r:
                    if total and not silent_note and now - last > 5:
                        print(f'\n[{time.strftime("%H:%M:%S")}] ... silent for '
                              f'{now - last:.0f}s (kernel or USB console stopped printing)',
                              file=sys.stderr, flush=True)
                        silent_note = True
                    if (reconnect and args.reopen_after and
                            now - last > args.reopen_after):
                        print(f'\n[{time.strftime("%H:%M:%S")}] no data for '
                              f'{now - last:.0f}s: closing and reopening the port '
                              f'to pick up the kernel ring backlog', file=sys.stderr, flush=True)
                        reopen = True
                        break
                    continue
                try:
                    data = os.read(fd, 65536)
                except BlockingIOError:
                    continue
                except OSError as exc:
                    print(f'\n[read error: {exc}]', file=sys.stderr, flush=True)
                    reopen = reconnect
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
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

        if not reopen:
            break
        gaps += 1
        time.sleep(1)
        dev = find_port() or args.device
        if not dev:
            print('[waiting for the USB console to come back]', file=sys.stderr, flush=True)
            dev, fd = open_dev(dev, 600)
            if not fd:
                break
        else:
            try:
                fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
            except OSError as exc:
                print(f'[reopen failed: {exc}]', file=sys.stderr, flush=True)
                break
        print(f'[{time.strftime("%H:%M:%S")}] reopened {dev} after {gaps} gap(s); '
              f'data between the last read and this reopen may be missing',
              file=sys.stderr, flush=True)
        last = time.time()

    if out:
        out.close()
    print(f'\n[{total} bytes, {gaps} reopen(s)]', file=sys.stderr)


if __name__ == '__main__':
    main()
