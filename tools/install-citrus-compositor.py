#!/usr/bin/env python3
"""Install the candidate CoreAnimation stack into a *copy* of the iOS root.

This is the first compositor test, deliberately narrower than the full backport:
the kernel keeps the baseline framebuffer (the gpu-probe1 freeze source is not
reintroduced) and adds only the RedwoodGPU service and the AMFI dyld policy.

Installed:

  /citrus/lib/libOSMesa.8.dylib
  /citrus/lib/libcitrus-gl.dylib
  /citrus/lib/libcitrus-loader.dylib
  /usr/libexec/real/backboardd      (the original, preserved)
  /usr/libexec/backboardd           (citrus-bbd-wrapper, which execs the real one)

launchd already has a cache job for /usr/libexec/backboardd, so replacing that
binary needs no launchd cache edit. The wrapper only injects the loader when
the kernel command line has citrusgl=1.

The Mac user cannot write root-owned HFS+ entries on an owners-on mount, so the
files go in through a noowners mount and their catalog ownership is repaired
with tools/hfs-chown-inplace.py --only-overrides. Nothing here flashes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

LIBS = [
    ('citrus/lib/libOSMesa.8.dylib', '/citrus/lib/libOSMesa.8.dylib'),
    ('citrus/lib/libcitrus-gl.dylib', '/citrus/lib/libcitrus-gl.dylib'),
    ('citrus/lib/libcitrus-loader.dylib', '/citrus/lib/libcitrus-loader.dylib'),
]
REAL = '/usr/libexec/real/backboardd'
WRAPPER = '/usr/libexec/backboardd'
DIRS = ['/citrus', '/citrus/lib', '/usr/libexec/real']


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mounted(mountpoint):
    return str(mountpoint) in subprocess.check_output(['mount'], text=True)


def attach(image, mountpoint, rw, owners):
    if mounted(mountpoint):
        raise SystemExit(f'{mountpoint} already mounted')
    mountpoint.mkdir(parents=True, exist_ok=True)
    cmd = ['hdiutil', 'attach', '-noverify', '-nobrowse', '-mountpoint', str(mountpoint),
           '-owners', 'on' if owners else 'off']
    cmd.insert(2, '-readwrite' if rw else '-readonly')
    subprocess.run(cmd + [str(image)], check=True, capture_output=True, text=True)


def detach(mountpoint):
    subprocess.run(['hdiutil', 'detach', str(mountpoint)], check=True,
                   capture_output=True, text=True)


def codesign_verify(path):
    result = subprocess.run(['codesign', '--verify', '--verbose=2', str(path)],
                            capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f'codesign --verify failed for {path}\n{result.stderr}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path,
                        default=ROOT / 'out/ios16/ios16-root-gpu-compositor.img')
    parser.add_argument('--staging', type=Path,
                        default=ROOT / 'out/citrus-gpu-userland/staging')
    parser.add_argument('--mountpoint', type=Path,
                        default=ROOT / 'out/ios16/mnt-root')
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()

    for rel, _ in LIBS:
        if not (args.staging / rel).is_file():
            raise SystemExit('missing staged file: ' + rel)
    wrapper_source = args.staging / 'citrus/bin/citrus-bbd-wrapper'
    if not wrapper_source.is_file():
        raise SystemExit('missing staged wrapper')

    plan = {'image': str(args.image.relative_to(ROOT)), 'mode': 'compositor-test',
            'source_sha256': args.source_sha256, 'files': []}
    for rel, dest in LIBS:
        plan['files'].append({'source': rel, 'destination': dest,
                              'sha256': digest(args.staging / rel),
                              'size': (args.staging / rel).stat().st_size})
    plan['files'].append({'source': 'citrus/bin/citrus-bbd-wrapper', 'destination': WRAPPER,
                          'sha256': digest(wrapper_source), 'size': wrapper_source.stat().st_size})
    plan['files'].append({'destination': REAL, 'source': 'original ' + WRAPPER,
                          'preserved': True})
    if not args.apply:
        print(json.dumps(plan, indent=2))
        return

    attach(args.image, args.mountpoint, True, False)
    try:
        for directory in DIRS:
            target = args.mountpoint / directory.lstrip('/')
            target.mkdir(parents=True, exist_ok=True)
            os.chmod(target, 0o755)
        real = args.mountpoint / REAL.lstrip('/')
        original = args.mountpoint / WRAPPER.lstrip('/')
        if not original.is_file():
            raise SystemExit('missing original backboardd at ' + WRAPPER)
        if not real.exists():
            shutil.copyfile(original, real)
            os.chmod(real, 0o755)
            plan['preserved_sha256'] = digest(real)
        for rel, dest in LIBS:
            target = args.mountpoint / dest.lstrip('/')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(args.staging / rel, target)
            os.chmod(target, 0o755)
            if dest.endswith('.dylib'):
                codesign_verify(target)
        shutil.copyfile(wrapper_source, original)
        os.chmod(original, 0o755)
        codesign_verify(original)
    finally:
        detach(args.mountpoint)

    owners = args.image.with_suffix('.owners.tsv')
    lines = ['0\t0\t' + directory for directory in DIRS]
    lines += ['0\t0\t' + dest for _, dest in LIBS]
    lines += ['0\t0\t' + REAL, '0\t0\t' + WRAPPER]
    owners.write_text('\n'.join(lines) + '\n')
    rollback = args.image.with_suffix('.catalog-rollback.bin')
    dry = subprocess.run([sys.executable, str(ROOT / 'tools/hfs-chown-inplace.py'),
                          str(args.image), str(owners), '--only-overrides', '--dry-run'],
                         capture_output=True, text=True)
    if dry.returncode:
        raise SystemExit('ownership dry-run failed:\n' + dry.stdout + dry.stderr)
    (args.image.with_suffix('.chown-dry-run.txt')).write_text(dry.stdout + dry.stderr)
    result = subprocess.run([sys.executable, str(ROOT / 'tools/hfs-chown-inplace.py'),
                             str(args.image), str(owners), '--only-overrides',
                             '--rollback', str(rollback)], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit('ownership repair failed:\n' + result.stdout + result.stderr)
    (args.image.with_suffix('.chown.txt')).write_text(result.stdout + result.stderr)

    attach(args.image, args.mountpoint, False, True)
    try:
        for rel, dest in LIBS:
            target = args.mountpoint / dest.lstrip('/')
            st = target.stat()
            if (st.st_uid, st.st_gid) != (0, 0):
                raise SystemExit(f'{dest}: owner {st.st_uid}:{st.st_gid}, expected 0:0')
            if digest(target) != next(x['sha256'] for x in plan['files'] if x['destination'] == dest):
                raise SystemExit(f'{dest}: content changed during install')
            codesign_verify(target)
        for dest in (REAL, WRAPPER):
            target = args.mountpoint / dest.lstrip('/')
            st = target.stat()
            if (st.st_uid, st.st_gid) != (0, 0) or (st.st_mode & 0o777) != 0o755:
                raise SystemExit(f'{dest}: owner/mode {st.st_uid}:{st.st_gid} {oct(st.st_mode & 0o777)}')
        codesign_verify(args.mountpoint / WRAPPER.lstrip('/'))
        plan['ownership_verified'] = True
        plan['codesign_verified'] = True
    finally:
        detach(args.mountpoint)

    plan['image_sha256'] = digest(args.image)
    plan['image_size'] = args.image.stat().st_size
    out = args.image.with_suffix('.install.json')
    out.write_text(json.dumps(plan, indent=2) + '\n')
    print(f'installed into {args.image}\nsha256 {plan["image_sha256"]}\nmanifest {out}')


if __name__ == '__main__':
    main()
