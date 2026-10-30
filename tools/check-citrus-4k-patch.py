#!/usr/bin/env python3
"""Check that the quarantined 4K source patch reproduces the staged trial.

This is a source-integrity check only; it does not validate the kernel, build
an image, or establish that the patch is safe to run.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'kernel/experiments/citrus-4k-unvalidated.patch'
BASE = ROOT / 'out/citrus-8core/base/xnu'
TRIAL = ROOT / 'out/citrus-8core/source/xnu'


def main():
    names = [line[6:] for line in PATCH.read_text().splitlines() if line.startswith('--- a/')]
    if not names or len(names) != len(set(names)):
        raise SystemExit('patch has no files or contains duplicates')
    with tempfile.TemporaryDirectory(prefix='citrus-4k-check-') as tmp:
        staged = Path(tmp)
        for name in names:
            dest = staged / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(BASE / name, dest)
        result = subprocess.run(['patch', '-p1', '--batch', '--fuzz=0', '-i', str(PATCH)],
                                cwd=staged, capture_output=True, text=True)
        if result.returncode:
            raise SystemExit(result.stdout + result.stderr)
        for name in names:
            if (staged / name).read_bytes() != (TRIAL / name).read_bytes():
                raise SystemExit(f'patch does not reproduce {name}')
    print(f'PASS: {len(names)} patched files reproduce the staged trial; not a boot validation')


if __name__ == '__main__':
    main()
