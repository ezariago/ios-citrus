#!/usr/bin/env python3
"""Retain staged GPU source changes and verify their exact reproduction.

Baseline is the current Citrus kernel source, after patches 0001/0002.
The generated vendor-firmware translation unit is deliberately excluded.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'out/upstream-artifacts/buildtree/xnu'
STAGE = ROOT / 'out/citrus-gpu/xnu'
PATCH = ROOT / 'kernel/patches/0003-citrus-adreno-kernel.patch'
FILES = ['bsd/dev/topaz_fw.c', 'bsd/dev/sweet_cpufreq.c', 'bsd/dev/sweet_touch.c', 'bsd/kern/sweet_amfi.c'] + ['iokit/Kernel/arm/' + name for name in (
    'SweetFramebuffer.cpp', 'SweetSurface.cpp', 'SweetSurface.h', 'TopazAdreno.cpp', 'RedwoodGPU.cpp')]


def main():
    chunks = []
    for rel in FILES:
        original, modified = BASE / rel, STAGE / rel
        result = subprocess.run(['diff', '-u', '--label', 'a/' + rel, '--label', 'b/' + rel,
                                 str(original) if original.exists() else '/dev/null', str(modified)],
                                capture_output=True, text=True)
        if result.returncode not in (0, 1):
            raise SystemExit(result.stderr)
        chunks.append(result.stdout)
    content = ''.join(chunks)
    with tempfile.TemporaryDirectory() as directory:
        test = Path(directory) / 'xnu'
        shutil.copytree(BASE, test)
        subprocess.run(['patch', '-p1', '--batch', '--fuzz=0'], input=content, text=True, cwd=test,
                       check=True, capture_output=True)
        for rel in FILES:
            if (test / rel).read_bytes() != (STAGE / rel).read_bytes():
                raise SystemExit('reproduction failed: ' + rel)
    PATCH.write_text(content)
    manifest_path = ROOT / 'research/citrus-gpu-source-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['patch_sha256'] = hashlib.sha256(PATCH.read_bytes()).hexdigest()
    manifest['base_files'] = {rel: hashlib.sha256((BASE / rel).read_bytes()).hexdigest()
                              for rel in FILES if (BASE / rel).exists()}
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'{PATCH}: {len(content)} bytes; all {len(FILES)} files reproduced exactly')


if __name__ == '__main__':
    main()
