#!/usr/bin/env python3
"""Resolve kernel virtual addresses against the local XNU build.

The Citrus kernel is linked at its final virtual addresses (no KASLR slide),
so an address captured by the stall sampler or a panic maps directly.

Usage: tools/symbolicate-kernel.py ADDR [ADDR ...]
       tools/symbolicate-kernel.py --file out/ios16/logs/x-stalls.txt
"""
import argparse
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
KERNEL = ROOT / 'out/citrus-kernel/kernel.development.citrus'
ADDR2LINE = pathlib.Path('/opt/homebrew/opt/llvm/bin/llvm-addr2line')


def symbolicate(addresses):
    if not ADDR2LINE.exists():
        raise SystemExit(f'missing {ADDR2LINE}')
    if not KERNEL.exists():
        raise SystemExit(f'missing {KERNEL}')
    command = [str(ADDR2LINE), '-e', str(KERNEL), '-f', '-C', *addresses]
    out = subprocess.check_output(command, text=True).splitlines()
    for i, address in enumerate(addresses):
        function = out[2 * i] if 2 * i < len(out) else '??'
        location = out[2 * i + 1] if 2 * i + 1 < len(out) else '??'
        print(f'{address:>20}  {function}  ({location})')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('addresses', nargs='*')
    parser.add_argument('--file', type=pathlib.Path,
                        help='read every 0x... token from this file')
    args = parser.parse_args()
    addrs = list(args.addresses)
    if args.file:
        addrs += re.findall(r'0x[0-9a-fA-F]{6,16}', args.file.read_text())
    if not addrs:
        parser.error('no addresses')
    symbolicate(addrs)


if __name__ == '__main__':
    main()
