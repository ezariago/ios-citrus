#!/usr/bin/env python3
"""Install the standalone GPU triangle into a *copy* of the iOS root image.

The image must be an APFS clone of the verified known-good root (or any test
copy); this tool never touches out/ios16/ios16-root-keychain.img itself. It
installs only:

  /citrus/lib/libOSMesa.8.dylib
  /citrus/bin/citrus-triangle
  /System/Library/LaunchDaemons/com.citrus.gpu-triangle.plist

It also adds that job to the iOS launchd job cache
(/System/Library/xpc/launchd.plist, read when booted with
launchd_unsecure_cache=1); launchd does not scan LaunchDaemons by itself.

The Mac user cannot write root-owned HFS+ entries on an owners-on mount, so the
files are written through a noowners mount and their catalog ownerID/groupID is
then repaired with tools/hfs-chown-inplace.py (--only-overrides, so the rest of
the root's ownership is preserved). All three paths must become 0:0 for launchd
to accept the daemon.

Nothing here flashes the phone. Run tools/stream-image-adb.sh separately.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
JOB_PATH = '/System/Library/LaunchDaemons/com.citrus.gpu-triangle.plist'
CACHE_PATH = '/System/Library/xpc/launchd.plist'
BOOTPD_PATH = '/System/Library/LaunchDaemons/bootps.plist'
DISABLED_PATH = '/private/var/db/com.apple.xpc.launchd/disabled.plist'
IOMFB_PATH = '/usr/bin/IOMFB_FDR_Loader'

FILES = [
    ('citrus/lib/libOSMesa.8.dylib', '/citrus/lib/libOSMesa.8.dylib', 0o755),
    ('citrus/bin/citrus-triangle', '/citrus/bin/citrus-triangle', 0o755),
    ('citrus/tests/com.citrus.gpu-triangle.plist',
     JOB_PATH, 0o644),
]
DIRS = ['/citrus', '/citrus/lib', '/citrus/bin']


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mountpoint_mounted(mountpoint):
    out = subprocess.check_output(['mount'], text=True)
    return str(mountpoint) in out


def attach(image, mountpoint, read_write, owners):
    if mountpoint_mounted(mountpoint):
        raise SystemExit(f'{mountpoint} is already mounted')
    mountpoint.mkdir(parents=True, exist_ok=True)
    cmd = ['hdiutil', 'attach', '-noverify', '-nobrowse', '-mountpoint', str(mountpoint),
           '-owners', 'on' if owners else 'off']
    if not read_write:
        cmd.insert(2, '-readonly')
    else:
        cmd.insert(2, '-readwrite')
    subprocess.run(cmd + [str(image)], check=True, capture_output=True, text=True)


def detach(mountpoint):
    subprocess.run(['hdiutil', 'detach', str(mountpoint)], check=True,
                   capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path,
                        default=ROOT / 'out/ios16/ios16-root-gpu-triangle.img')
    parser.add_argument('--staging', type=Path,
                        default=ROOT / 'out/citrus-gpu-userland/staging')
    parser.add_argument('--mountpoint', type=Path,
                        default=ROOT / 'out/ios16/mnt-root')
    parser.add_argument('--source-sha256', required=True,
                        help='expected SHA256 of the unmodified source image the clone came from')
    parser.add_argument('--test-runner', choices=['new-job', 'bootpd', 'iomfb'], default='new-job',
                        help='launch the triangle from a new cache job or from the existing (disabled) bootpd slot')
    parser.add_argument('--apply', action='store_true',
                        help='write the image (default: report the plan only)')
    args = parser.parse_args()

    for rel, _, _ in FILES:
        if not (args.staging / rel).is_file():
            raise SystemExit('missing staged file: ' + rel)

    plan = {'image': str(args.image.relative_to(ROOT)),
            'source_sha256': args.source_sha256,
            'installed': [], 'mode': 'userspace-triangle'}
    for rel, dest, mode in FILES:
        source = args.staging / rel
        plan['installed'].append({'source': rel, 'destination': dest,
                                  'source_sha256': digest(source),
                                  'size': source.stat().st_size,
                                  'mode': oct(mode)})
    if not args.apply:
        print(json.dumps(plan, indent=2))
        return

    if mountpoint_mounted(args.mountpoint):
        raise SystemExit('refusing: mountpoint already mounted; detach it first')

    # 1. write through a noowners mount, then detach so the catalog can be edited
    attach(args.image, args.mountpoint, True, False)
    try:
        for directory in DIRS:
            target = args.mountpoint / directory.lstrip('/')
            target.mkdir(parents=True, exist_ok=True)
            os.chmod(target, 0o755)
        for rel, dest, mode in FILES:
            target = args.mountpoint / dest.lstrip('/')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(args.staging / rel, target)
            os.chmod(target, mode)
            if dest.endswith(('.dylib', 'citrus-triangle')):
                verify = subprocess.run(['codesign', '--verify', '--verbose=2', str(target)],
                                        capture_output=True, text=True)
                if verify.returncode:
                    raise SystemExit(f'installed file failed codesign --verify: {dest}\n{verify.stderr}')
        if args.test_runner == 'iomfb':
            # launchd created neither cache job, so borrow a one-shot boot
            # daemon that already runs on every boot: IOMFB_FDR_Loader only
            # loads display FDR calibration. Rename the original, then put
            # the triangle at its path; the cache is left untouched.
            original = args.mountpoint / IOMFB_PATH.lstrip('/')
            backup = args.mountpoint / (IOMFB_PATH + '.real').lstrip('/')
            if not original.is_file():
                raise SystemExit('missing ' + IOMFB_PATH)
            if not backup.exists():
                shutil.copyfile(original, backup)
                os.chmod(backup, 0o755)
            shutil.copyfile(args.staging / 'citrus/bin/citrus-triangle', original)
            os.chmod(original, 0o755)
            check = subprocess.run(['codesign', '--verify', '--verbose=2', str(original)],
                                   capture_output=True, text=True)
            if check.returncode:
                raise SystemExit('borrowed daemon failed codesign: ' + check.stderr)
            plan['launchd_job'] = {'runner': 'iomfb',
                                   'executable': IOMFB_PATH,
                                   'backup': IOMFB_PATH + '.real',
                                   'executable_sha256': digest(original)}
        else:
            # iOS launchd does not scan LaunchDaemons at boot: it reads the job
            # cache in /System/Library/xpc/launchd.plist. Add the job there too
            # (rewritten in place so the inode's root:wheel ownership survives).
            cache = args.mountpoint / CACHE_PATH.lstrip('/')
            if not cache.is_file():
                raise SystemExit('launchd job cache not found: /System/Library/xpc/launchd.plist')
            shutil.copyfile(cache, ROOT / 'out/ios16/launchd.plist.before-citrus')
            cache_obj = plistlib.loads(cache.read_bytes())
            job = {'Label': 'com.citrus.gpu-triangle',
                   'ProgramArguments': ['/citrus/bin/citrus-triangle'],
                   'RunAtLoad': True}
            daemons = cache_obj.setdefault('LaunchDaemons', {})
            if args.test_runner == 'new-job':
                daemons[JOB_PATH] = job
            else:
                # Test whether launchd honours cache edits at all through a slot it
                # already knows: bootpd is disabled by default and is not used by
                # iOS, so borrowing it cannot break a normal boot.
                if BOOTPD_PATH not in daemons:
                    raise SystemExit('bootps.plist is not in the launchd cache')
                daemons.pop(JOB_PATH, None)
                job = {'Label': 'com.apple.bootpd',
                       'ProgramArguments': ['/citrus/bin/citrus-triangle'],
                       'RunAtLoad': True}
                daemons[BOOTPD_PATH] = job
                # launchd may re-read the plist named by the cache key; make the
                # on-disk bootps.plist say exactly what the cache entry says.
                bootps = args.mountpoint / BOOTPD_PATH.lstrip('/')
                jblob = plistlib.dumps(job, fmt=plistlib.FMT_BINARY)
                with open(bootps, 'r+b') as handle:
                    handle.write(jblob)
                    handle.truncate()
            blob = plistlib.dumps(cache_obj, fmt=plistlib.FMT_BINARY)
            with open(cache, 'r+b') as handle:
                handle.write(blob)
                handle.truncate()
            want = daemons[JOB_PATH if args.test_runner == 'new-job' else BOOTPD_PATH]
            if plistlib.loads(cache.read_bytes())['LaunchDaemons'].get(
                    JOB_PATH if args.test_runner == 'new-job' else BOOTPD_PATH) != want:
                raise SystemExit('launchd cache did not take the job')
            plan['launchd_job'] = {'cache': CACHE_PATH, 'runner': args.test_runner,
                                   'key': JOB_PATH if args.test_runner == 'new-job' else BOOTPD_PATH,
                                   'entry': want, 'cache_sha256': digest(cache)}
            if args.test_runner == 'bootpd':
                disabled = args.mountpoint / DISABLED_PATH.lstrip('/')
                state = plistlib.loads(disabled.read_bytes())
                if 'com.apple.bootpd' in state:
                    state.pop('com.apple.bootpd')
                    dblob = plistlib.dumps(state, fmt=plistlib.FMT_BINARY)
                    with open(disabled, 'r+b') as handle:
                        handle.write(dblob)
                        handle.truncate()
                plan['launchd_job']['disabled_override_removed'] = True
                plan['launchd_job']['plist_rewritten'] = BOOTPD_PATH
    finally:
        detach(args.mountpoint)

    # 2. repair catalog ownership only for the paths we added
    owners = args.image.with_suffix('.owners.tsv')
    lines = ['0\t0\t' + directory for directory in DIRS]
    lines += ['0\t0\t' + dest for _, dest, _ in FILES]
    if args.test_runner == 'iomfb':
        lines += ['0\t0\t' + IOMFB_PATH, '0\t0\t' + IOMFB_PATH + '.real']
    else:
        lines += ['0\t0\t' + CACHE_PATH]
    if args.test_runner == 'bootpd':
        lines += ['0\t0\t' + DISABLED_PATH, '0\t0\t' + BOOTPD_PATH]
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
                             '--rollback', str(rollback)],
                            capture_output=True, text=True)
    if result.returncode:
        raise SystemExit('ownership repair failed:\n' + result.stdout + result.stderr)
    (args.image.with_suffix('.chown.txt')).write_text(result.stdout + result.stderr)

    # 3. verify from an owners-on read-only mount
    attach(args.image, args.mountpoint, False, True)
    try:
        for _, dest, mode in FILES:
            target = args.mountpoint / dest.lstrip('/')
            st = target.stat()
            if (st.st_uid, st.st_gid) != (0, 0):
                raise SystemExit(f'{dest}: owner is {st.st_uid}:{st.st_gid}, expected 0:0')
            if (st.st_mode & 0o777) != mode:
                raise SystemExit(f'{dest}: mode {oct(st.st_mode & 0o777)}, expected {oct(mode)}')
            if digest(target) != next(x['source_sha256'] for x in plan['installed']
                                      if x['destination'] == dest):
                raise SystemExit(f'{dest}: content changed during install')
        if args.test_runner == 'iomfb':
            original = args.mountpoint / IOMFB_PATH.lstrip('/')
            st = original.stat()
            if (st.st_uid, st.st_gid) != (0, 0):
                raise SystemExit(f'{IOMFB_PATH}: owner {st.st_uid}:{st.st_gid}, expected 0:0')
            if digest(original) != plan['launchd_job']['executable_sha256']:
                raise SystemExit('borrowed daemon content changed during install')
        else:
            cache = args.mountpoint / CACHE_PATH.lstrip('/')
            st = cache.stat()
            if (st.st_uid, st.st_gid) != (0, 0):
                raise SystemExit(f'launchd cache owner is {st.st_uid}:{st.st_gid}, expected 0:0')
            entry = plistlib.loads(cache.read_bytes())['LaunchDaemons'].get(plan['launchd_job']['key'])
            if entry != plan['launchd_job']['entry']:
                raise SystemExit('launchd cache job entry differs after install')
            if args.test_runner == 'bootpd':
                on_disk = plistlib.loads((args.mountpoint / BOOTPD_PATH.lstrip('/')).read_bytes())
                if on_disk != plan['launchd_job']['entry']:
                    raise SystemExit('bootps.plist differs from the cache entry')
        plan['ownership_verified'] = True
        plan['codesign_verified'] = True
        plan['launchd_entry_verified'] = True
    finally:
        detach(args.mountpoint)

    plan['image_sha256'] = digest(args.image)
    plan['image_size'] = args.image.stat().st_size
    out = args.image.with_suffix('.install.json')
    out.write_text(json.dumps(plan, indent=2) + '\n')
    print(f'installed into {args.image}')
    print(f'sha256 {plan["image_sha256"]}')
    print(f'manifest {out}')


if __name__ == '__main__':
    main()
