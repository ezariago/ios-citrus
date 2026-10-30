#!/usr/bin/env python3
"""Read and independently hash GPU firmware from a connected Citrus Android/recovery.

No reboot, mount, partition write or on-device temporary file. Use --su only
when the connected Android shell requires root to read /vendor/firmware.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('a610_zap.mdt', 'a610_zap.b02', 'a630_sqe.fw')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial')
    parser.add_argument('--su', action='store_true')
    parser.add_argument('--directory', help='Override the standard vendor/firmware search directories')
    parser.add_argument('--output', type=Path, default=ROOT / 'devices/citrus-gpu-fw')
    args = parser.parse_args()
    adb = ['adb'] + (['-s', args.serial] if args.serial else [])

    def read(command):
        # Some recovery exec services return host status 0 even when the remote
        # command fails. Carry its status in a trailer outside the binary data.
        script = command + '; citrus_status=$?; printf "\\nCITRUS_EXIT:%d\\n" "$citrus_status"'
        invocation = ['su', '-c', shlex.quote(script)] if args.su else ['sh', '-c', shlex.quote(script)]
        output = subprocess.check_output(adb + ['exec-out', ' '.join(invocation)], timeout=30)
        data, marker, status = output.rpartition(b'\nCITRUS_EXIT:')
        if not marker or not status.strip().isdigit():
            raise RuntimeError('recovery did not return a valid remote-command status')
        if int(status.strip()):
            raise subprocess.CalledProcessError(int(status.strip()), command, output=data)
        return data

    # Fail before creating a result directory when no device is connected.
    state = subprocess.check_output(adb + ['get-state'], text=True, timeout=10).strip()
    if state not in ('device', 'recovery'):
        raise SystemExit('ADB is not in a shell-capable state')
    blobs, records = {}, {}
    identity = read('getprop').decode(errors='replace')
    directories = [args.directory] if args.directory else [
        '/vendor/firmware', '/vendor/firmware_mnt/image', '/vendor/etc/firmware', '/odm/firmware', '/firmware/image']
    for name in NAMES:
        remote = None
        for directory in directories:
            candidate = directory.rstrip('/') + '/' + name
            try:
                read('test -r ' + shlex.quote(candidate))
                remote = candidate
                break
            except subprocess.CalledProcessError:
                continue
        if remote is None:
            raise SystemExit(name + ': not found in the firmware directories; no files saved')
        data = read('cat ' + shlex.quote(remote))
        checksum = read('sha256sum ' + shlex.quote(remote)).decode().split()[0]
        local = hashlib.sha256(data).hexdigest()
        if checksum != local or not data:
            raise SystemExit(f'{name}: device/host hashes differ or file is empty')
        blobs[name] = data
        records[name] = {'remote': remote, 'sha256': local, 'bytes': len(data)}
    # Never silently replace an earlier firmware capture.
    args.output.mkdir(parents=True, exist_ok=False)
    for name, data in blobs.items():
        (args.output / name).write_bytes(data)
    (args.output / 'identity.txt').write_text(identity)
    manifest = {'captured_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'adb_serial': args.serial, 'independently_verified': True,
                'method': 'adb exec-out cat, separate on-device sha256sum', 'files': records}
    (args.output / 'provenance.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Verified device firmware in ' + str(args.output))


if __name__ == '__main__':
    main()
