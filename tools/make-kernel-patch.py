#!/usr/bin/env python3
"""Regenerate kernel/patches/0002-*.patch from the working build tree.

The working tree is out/upstream-artifacts/buildtree/xnu; the pristine baseline
is /tmp/origbt/xnu (extracted from out/upstream-artifacts/xnu-buildtree.zip by
the earlier sessions).  The generated bsd/dev/sweet_touch_fw.h is deliberately
excluded: tools/rebuild-kernel.py regenerates it from devices/citrus-ft8719-fw.bin.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TREE = ROOT / 'out/upstream-artifacts/buildtree/xnu'
ORIG = pathlib.Path('/tmp/origbt/xnu')
PATCH = ROOT / 'kernel/patches/0002-sweet-console-display-stall-instrumentation.patch'

# Order of the existing patch; keep it stable so the diff stays reviewable.
FILES = [
    'bsd/dev/sweet_ufs.c',
    'bsd/dev/sweet_sample.c',
    'bsd/dev/sweet_usb.c',
    'bsd/dev/sweet_touch.c',
    'osfmk/kern/exception.c',
    'osfmk/arm/rtclock.c',
    'osfmk/arm64/sleh.c',
    'osfmk/console/video_console.c',
    'osfmk/console/serial_console.c',
    'pexpert/arm/pe_fiq.c',
    'iokit/Kernel/arm/SweetFramebuffer.cpp',
    'osfmk/arm64/sweet_early.c',
    'osfmk/arm64/cpu.c',
    'osfmk/arm/sweet_idle_stats.h',
]


def main():
    if not ORIG.is_dir():
        raise SystemExit(f'pristine tree missing: {ORIG}')
    out = []
    for rel in FILES:
        new = TREE / rel
        old = ORIG / rel
        if not new.exists():
            raise SystemExit(f'working file missing: {new}')
        if old.exists():
            args = ['diff', '-u', '--label', f'a/{rel}', '--label', f'b/{rel}',
                    str(old), str(new)]
        else:
            args = ['diff', '-u', '--label', 'a/' + rel, '--label', 'b/' + rel,
                    '/dev/null', str(new)]
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode not in (0, 1):
            raise SystemExit(f'diff failed for {rel}: {r.stderr}')
        if r.stdout:
            out.append(r.stdout)
    text = ''.join(out)
    PATCH.write_text(text)
    print(f'wrote {PATCH} ({len(text)} bytes, {len(out)} files)')

    # Dry-run: apply to a scratch copy of the pristine tree and compare.
    import shutil, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        dst = pathlib.Path(tmp) / 'xnu'
        shutil.copytree(ORIG, dst)
        r = subprocess.run(['patch', '-p1', '-s', '-i', str(PATCH)],
                           cwd=dst, capture_output=True, text=True)
        if r.returncode:
            print(r.stdout + r.stderr, file=sys.stderr)
            raise SystemExit('patch dry run failed')
        bad = []
        for rel in FILES:
            a = (dst / rel).read_bytes()
            b = (TREE / rel).read_bytes()
            if a != b:
                bad.append(rel)
        if bad:
            raise SystemExit('patch does not reproduce: ' + ', '.join(bad))
    print('dry run: patch applies cleanly and reproduces every file')


if __name__ == '__main__':
    main()
