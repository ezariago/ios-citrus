#!/usr/bin/env python3
"""Assemble a local HFSX iOS root using native mounts; never touches the phone.

Sources must already be mounted read-only at out/ios16/{os,system,app}-mount.
The destination is a new sparse-grown HFSX image; mounted paths are checked
before copying and only this task's destination is detached.
"""
import json
import os
import pathlib
import plistlib
import runpy
import subprocess
import sys
import argparse

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORK = ROOT / 'out/ios16'
IMAGE = WORK / 'ios16-root.img'
MOUNT = WORK / 'root-mount'
STATE = WORK / 'root-build-state.json'
HFS = ROOT / 'out/libdmg-hfsplus/build/hfs/hfsplus'
OWNERS = {}


def stage(name):
    STATE.write_text(json.dumps({'stage': name, 'image': str(IMAGE), 'mount': str(MOUNT)}, indent=2) + '\n')
    print(name, flush=True)


def run(command, log=None):
    if log:
        with (WORK / log).open('w') as output:
            subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, check=True)
    else:
        subprocess.run(command, check=True)


def mkdir(path, mode=0o755, uid=0, gid=0):
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(mode)
    OWNERS['/' + str(path.relative_to(MOUNT))] = (uid, gid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', action='store_true', help='Resume this tool\'s existing destination copy')
    args = parser.parse_args()
    for name in ('os', 'system', 'app'):
        source = WORK / (name + '-mount')
        if not source.is_mount():
            raise RuntimeError(f'Source not mounted: {source}')
    resuming = args.resume and IMAGE.exists() and MOUNT.is_mount() and STATE.exists()
    if (IMAGE.exists() or MOUNT.is_mount()) and not resuming:
        raise RuntimeError('Root image or destination mount already exists; inspect state before resuming')
    if not resuming:
        stage('creating-sparse-hfsx')
        seed = WORK / 'root-seed.dmg'
        run(['hdiutil', 'create', '-size', '128m', '-fs', 'Case-sensitive Journaled HFS+',
             '-layout', 'NONE', '-type', 'UDIF', '-volname', 'iOSRoot', str(seed)])
        seed.rename(IMAGE)
        run([str(HFS), str(IMAGE), 'grow', str(16 * 1024**3)])
        MOUNT.mkdir(exist_ok=True)
        run(['hdiutil', 'attach', '-owners', 'off', '-nobrowse', '-mountpoint', str(MOUNT), str(IMAGE)])
    if not MOUNT.is_mount():
        raise RuntimeError('Destination mount did not appear')
    stage('copying-os')
    # Apple's empty, mode-000 root marker cannot be opened by an unprivileged
    # rsync. Recreate the verified zero-byte file with its original mode.
    marker = WORK / 'os-mount/.file'
    if marker.stat().st_size != 0:
        raise RuntimeError('Unexpected nonempty .file marker')
    excludes = ['--exclude=.fseventsd', '--exclude=.Spotlight-V100', '--exclude=.Trashes', '--exclude=/.file']
    run(['rsync', '-aH', '--no-owner', '--no-group', *excludes,
         str(WORK / 'os-mount') + '/', str(MOUNT) + '/'], 'copy-os.log')
    marker = MOUNT / '.file'
    marker.touch(exist_ok=True)
    marker.chmod(0)
    for name, destination in [('system', 'OS'), ('app', 'App')]:
        stage('copying-' + name)
        target = MOUNT / 'private/preboot/Cryptexes' / destination
        mkdir(target)
        run(['rsync', '-aH', '--no-owner', '--no-group', *excludes,
             str(WORK / (name + '-mount')) + '/', str(target) + '/'], 'copy-' + name + '.log')
    stage('linking-cryptex-files')
    cache = MOUNT / 'System/Library/Caches/com.apple.dyld'
    mkdir(cache)
    cryptex_cache = MOUNT / 'private/preboot/Cryptexes/OS/System/Library/Caches/com.apple.dyld'
    for source in cryptex_cache.iterdir():
        target = cache / source.name
        if not os.path.lexists(target):
            os.link(source, target)
    for component in ('OS', 'App'):
        base = MOUNT / 'private/preboot/Cryptexes' / component
        for directory, dirs, files in os.walk(base, followlinks=False):
            links = [name for name in dirs if (pathlib.Path(directory) / name).is_symlink()]
            for name in files + links:
                source = pathlib.Path(directory) / name
                relative = source.relative_to(base)
                if str(relative).startswith('System/Library/Caches/com.apple.dyld/'):
                    continue
                target = MOUNT / relative
                if os.path.lexists(target):
                    continue
                if not target.parent.resolve().is_relative_to(MOUNT.resolve()):
                    raise RuntimeError(f'Cryptex target escapes image through a symlink: {relative}')
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_symlink():
                    os.symlink(os.readlink(source), target)
                else:
                    os.link(source, target)
    stage('preparing-var')
    db = MOUNT / 'private/var/db'
    for relative, mode in [('diagnostics', 0o751), ('uuidtext', 0o755), ('diagnostics/timesync', 0o755)]:
        folder = db / relative
        mkdir(folder, mode, 272, 272)
        marker = folder / '.migrated'
        marker.touch()
        marker.chmod(0o644)
        OWNERS['/' + str(marker.relative_to(MOUNT))] = (272, 272)
    keybags = MOUNT / 'private/var/keybags'
    mkdir(keybags, 0o700)
    keybag = keybags / 'systembag.kb'
    keybag.write_bytes(plistlib.dumps({'KeyBagKeys': b'SWEET'}))
    keybag.chmod(0o600)
    stage('applying-bringup-preferences')
    original_chown, original_argv = os.chown, sys.argv

    def record_chown(path, uid, gid, **kwargs):
        path = pathlib.Path(path).absolute()
        relative = '/' + str(path.relative_to(MOUNT))
        if not relative.startswith('/private/var/'):
            uid, gid = 0, 0
        OWNERS[relative] = (uid, gid)

    try:
        os.chown = record_chown
        sys.argv = ['sweet-root-tweaks.py', str(MOUNT)]
        runpy.run_path(str(ROOT / 'upstream/ios-topaz/tools/sweet-root-tweaks.py'), run_name='__main__')
    finally:
        os.chown, sys.argv = original_chown, original_argv
    overrides = WORK / 'root-owners.tsv'
    overrides.write_text(''.join(f'{uid}\t{gid}\t{path}\n' for path, (uid, gid) in sorted(OWNERS.items())))
    stage('unmounting-for-ownership-repair')
    run(['hdiutil', 'detach', str(MOUNT)])
    if MOUNT.is_mount():
        raise RuntimeError('Refusing offline mutation while image remains mounted')
    stage('repairing-offline-ownership')
    helper = ROOT / 'out/hfs-owners'
    library = ROOT / 'out/libdmg-hfsplus'
    run(['clang', '-O2', '-I' + str(library / 'includes'), str(ROOT / 'tools/hfs-owners.c'),
         str(library / 'build/hfs/libhfs.a'), str(library / 'build/common/libcommon.a'),
         '-lz', '-o', str(helper)])
    run([str(helper), str(IMAGE), str(overrides)])
    stage('assembled-needs-readonly-verification')


if __name__ == '__main__':
    main()
