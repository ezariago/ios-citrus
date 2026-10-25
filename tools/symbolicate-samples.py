#!/usr/bin/env python3
"""Symbolicate SWEET sampler/crash addresses using a mounted iOS dyld cache.

Only shared-cache PCs/LRs/backtrace addresses are looked up. Main-executable
addresses need that executable's Mach-O symbols/disassembly separately.
"""
import argparse
import concurrent.futures
import pathlib
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=pathlib.Path)
    parser.add_argument('output', type=pathlib.Path)
    parser.add_argument('--dyld-cache', default='/Volumes/iOSRoot/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64')
    args = parser.parse_args()
    slides = {}
    records = []
    keys = set()
    # Console output can concatenate truncated lines; recover each record.
    for line in re.split(r'(?=(?:SMP|CRASH) )', args.log.read_text(errors='replace')):
        line = line.split('\n', 1)[0]
        header = re.match(r'(?:SMP|CRASH) ([^\[]+)\[\d+\].*?slide (0x[0-9a-f]+)', line)
        if header:
            slides[header[1]] = header[2]
        match = re.match(r'(?:SMP|CRASH) (\S+) (?:t\d+ )?(pc .*|bt .*)', line)
        if not match:
            if header or line.startswith('SMP ---'):
                records.append((line, []))
            continue
        slide = slides.get(match[1])
        addresses = re.findall(r'0x[0-9a-f]+', re.sub(r'\b(?:sp|fp|far) 0x[0-9a-f]+', '', match[2]))
        selected = [(slide, a) for a in addresses if slide and 0x180000000 <= int(a, 16) < 0x300000000]
        keys.update(selected)
        records.append((line, selected))

    def lookup(key):
        slide, address = key
        result = subprocess.run(['ipsw', 'dyld', 'a2s', args.dyld_cache, address, '-s', slide], capture_output=True, text=True)
        return key, (result.stdout + result.stderr).strip().replace('\n', ' | ')

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        symbols = dict(pool.map(lookup, sorted(keys)))
    with args.output.open('w') as output:
        for line, selected in records:
            output.write(line + '\n')
            for key in selected:
                output.write('  ' + key[1] + ' ' + symbols[key] + '\n')
    print(f'Wrote {args.output}: {len(records)} records, {len(keys)} unique shared-cache addresses')


if __name__ == '__main__':
    main()
