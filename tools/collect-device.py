#!/usr/bin/env python3
"""Read-only Android inventory. Never reboots, flashes, or writes device storage."""
import argparse
import datetime
import json
import pathlib
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', help='Select a particular ADB device')
    args = parser.parse_args()
    adb = ['adb'] + (['-s', args.serial] if args.serial else [])
    subprocess.run(adb + ['get-state'], check=True, capture_output=True, timeout=10)
    root = pathlib.Path(__file__).resolve().parents[1]
    output = root / 'device-dumps' / datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output.mkdir(parents=True, mode=0o700)
    commands = {
        'identity': 'for p in ro.product.device ro.product.model ro.board.platform ro.boot.hardware ro.build.version.release ro.build.display.id ro.boot.bootloader ro.boot.slot_suffix; do echo "$p=$(getprop "$p")"; done',
        'cpu': 'cat /proc/cpuinfo; cat /proc/meminfo',
        'memory': 'cat /proc/iomem',
        'cmdline': 'cat /proc/cmdline',
        'inputs': 'cat /proc/bus/input/devices',
        'partitions': 'ls -l /dev/block/by-name; cat /proc/partitions',
        'framebuffer': 'for f in /sys/class/graphics/fb0/virtual_size /sys/class/graphics/fb0/stride /sys/class/graphics/fb0/bits_per_pixel /sys/class/graphics/fb0/name /sys/class/graphics/fb0/modes; do echo "$f"; cat "$f"; done',
        'buses': 'ls -l /sys/bus/spi/devices /sys/bus/i2c/devices',
        'drm-display': 'cat /proc/fb; cat /sys/class/drm/card0-DSI-1/modes',
        'touch-controller': 'cat /sys/bus/spi/devices/spi1.0/fts_driver_info',
        'gpu-model': 'cat /sys/class/kgsl/kgsl-3d0/gpu_model; cat /sys/class/kgsl/kgsl-3d0/devfreq/available_frequencies',
        'kernel-log': 'dmesg',
    }
    results = {}
    for name, command in commands.items():
        try:
            result = subprocess.run(adb + ['shell', 'su', '-c', "'" + command.replace("'", "'\\''") + "'"],
                                    capture_output=True, timeout=30)
            (output / (name + '.txt')).write_bytes(result.stdout)
            (output / (name + '.stderr.txt')).write_bytes(result.stderr)
            results[name] = {'returncode': result.returncode}
        except subprocess.TimeoutExpired:
            results[name] = {'error': 'Timed out; other collection steps continued'}
    try:
        result = subprocess.run(adb + ['exec-out', 'su', '-c', 'cat /sys/firmware/fdt'],
                                capture_output=True, timeout=30)
        valid = result.returncode == 0 and result.stdout[:4] == b'\xd0\x0d\xfe\xed'
        if valid:
            (output / 'live.dtb').write_bytes(result.stdout)
        results['live-dtb'] = {'returncode': result.returncode, 'valid_magic': valid,
                               'stderr': result.stderr.decode(errors='replace')}
    except subprocess.TimeoutExpired:
        results['live-dtb'] = {'error': 'Timed out'}
    (output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(f'Saved inventory to {output}')
    print('Device logs can contain identifiers. Review before sharing. No partition images were copied.')


if __name__ == '__main__':
    main()
