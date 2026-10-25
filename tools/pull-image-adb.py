#!/usr/bin/env python3
"""Snapshot the phone's 16 GiB HFS root using an APFS clone and changed chunks.

Requires OrangeFox root ADB with userdata unmounted. The device is only read.
Every 64 MiB chunk is SHA-256 checked, including chunks reused from the clone.
A fresh output is required; failed partial outputs are retained for diagnosis.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
import pathlib
import subprocess

SIZE = 16 * 1024**3
CHUNK = 64 * 1024**2
COUNT = SIZE // CHUNK


def local_hashes(path):
    result = []
    with path.open('rb') as source:
        for _ in range(COUNT):
            block = source.read(CHUNK)
            if len(block) != CHUNK:
                raise RuntimeError('Short local source')
            result.append(hashlib.sha256(block).hexdigest())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clone-base', required=True, type=pathlib.Path)
    parser.add_argument('--output', required=True, type=pathlib.Path)
    args = parser.parse_args()
    base, output = args.clone_base.resolve(), args.output.resolve()
    partial = output.with_name(output.name + '.partial')
    manifest = output.with_name(output.name + '.json')
    if base.stat().st_size != SIZE or any(p.exists() for p in (output, partial, manifest)):
        raise RuntimeError('Need a 16 GiB base and unused output/partial/manifest paths')
    devices = subprocess.check_output(['adb', 'devices'], text=True)
    if sum(line.endswith('\trecovery') for line in devices.splitlines()) != 1:
        raise RuntimeError('Exactly one recovery device is required')
    device = subprocess.check_output(['adb', 'shell', 'readlink -f /dev/block/by-name/userdata'], text=True).strip()
    mounts = subprocess.check_output(['adb', 'shell', 'cat /proc/mounts'], text=True)
    if any(line.split()[0] in (device, '/dev/block/by-name/userdata') for line in mounts.splitlines()):
        raise RuntimeError('userdata must be unmounted')
    script = f'''i=0
while [ "$i" -lt {COUNT} ]; do
  printf '%s ' "$i"
  dd if=/dev/block/by-name/userdata bs={CHUNK} skip="$i" count=1 2>/dev/null | sha256sum
  i=$((i+1))
done'''
    print('Hashing all device chunks and the local clone base...', flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(local_hashes, base)
        remote = subprocess.check_output(['adb', 'shell', script], text=True)
        expected = {}
        for line in remote.splitlines():
            fields = line.split()
            if len(fields) != 3 or len(fields[1]) != 64:
                raise RuntimeError(f'Unexpected device hash output: {line!r}')
            index = int(fields[0])
            if index in expected:
                raise RuntimeError('Duplicate device chunk index')
            expected[index] = fields[1]
        if set(expected) != set(range(COUNT)):
            raise RuntimeError('Incomplete device chunk hashes')
        existing = future.result()
    changed = [i for i in range(COUNT) if existing[i] != expected[i]]
    manifest.write_text(json.dumps({'complete': False, 'base': str(base), 'device': device,
                                    'chunk_size': CHUNK, 'hashes': expected, 'changed': changed}, indent=2) + '\n')
    print(f'{len(changed)}/{COUNT} chunks differ; cloning base with APFS copy-on-write.', flush=True)
    subprocess.run(['cp', '-c', str(base), str(partial)], check=True)
    with partial.open('r+b') as target:
        for number, index in enumerate(changed, 1):
            command = f'dd if=/dev/block/by-name/userdata bs={CHUNK} skip={index} count=1 2>/dev/null'
            block = subprocess.check_output(['adb', 'exec-out', command])
            if len(block) != CHUNK or hashlib.sha256(block).hexdigest() != expected[index]:
                raise RuntimeError(f'Chunk {index} changed or was read incorrectly; partial retained')
            target.seek(index * CHUNK)
            target.write(block)
            print(f'Copied changed chunk {number}/{len(changed)} (index {index})', flush=True)
        target.flush()
        os.fsync(target.fileno())
    digest = hashlib.sha256()
    with partial.open('rb') as target:
        for index in range(COUNT):
            block = target.read(CHUNK)
            if len(block) != CHUNK or hashlib.sha256(block).hexdigest() != expected[index]:
                raise RuntimeError(f'Final snapshot chunk {index} failed verification')
            digest.update(block)
    partial.rename(output)
    report = json.loads(manifest.read_text())
    report.update(complete=True, sha256=digest.hexdigest(), output=str(output))
    manifest.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Verified all {COUNT} chunks: {digest.hexdigest()}  {output}', flush=True)


if __name__ == '__main__':
    main()
