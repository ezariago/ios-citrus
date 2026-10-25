#!/usr/bin/env python3
"""Build the standalone Citrus diagnostic shim and package a temporary boot image."""
import argparse
import pathlib
import shutil
import struct
import subprocess
from bootimage import repack, unpack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', type=pathlib.Path, required=True,
                        help='Verified Citrus boot partition backup')
    parser.add_argument('--payload', type=pathlib.Path, help='SWEETXNU payload for Gold-core handoff')
    args = parser.parse_args()
    root = pathlib.Path(__file__).resolve().parents[1]
    source, output = root / 'shim', root / 'out/citrus-diagnostic'
    output.mkdir(parents=True, exist_ok=True)
    linker = shutil.which('ld.lld') or '/opt/homebrew/opt/lld/bin/ld.lld'
    objects = []
    for name in ('start.S', 'diagnostic.c', 'xnu-loader.c'):
        obj = output / (pathlib.Path(name).stem + '.o')
        subprocess.run(['clang', '--target=aarch64-none-elf', '-mcpu=cortex-a53',
                        '-O2', '-ffreestanding', '-nostdlib', '-fno-pic',
                        '-mgeneral-regs-only', '-mstrict-align', '-fno-stack-protector',
                        '-fno-unwind-tables', '-fno-asynchronous-unwind-tables',
                        '-Wall', '-Wextra', '-Werror', '-c', str(source / name),
                        '-o', str(obj)], check=True)
        objects.append(str(obj))
    common = [linker, '-static', '--build-id=none', '--no-undefined',
              '-T', str(source / 'link.ld'), *objects]
    subprocess.run([*common, '-o', str(output / 'shim.elf')], check=True)
    image = output / 'Image'
    subprocess.run([*common, '--oformat=binary', '-o', str(image)], check=True)
    raw = image.read_bytes()
    image_size = struct.unpack_from('<Q', raw, 16)[0]
    if not len(raw) <= image_size <= 1024 * 1024:
        raise ValueError('Unexpected shim layout')
    raw += bytes(image_size - len(raw))
    if args.payload:
        payload = args.payload.read_bytes()
        if payload[:8] != b'SWEETXNU' or len(payload) > 0x7000000:
            raise ValueError('Invalid or oversized XNU payload')
        raw += b'CITRUSPL' + struct.pack('<Q', len(payload)) + payload
        raw += bytes(-len(raw) & 4095)
        raw = bytearray(raw)
        struct.pack_into('<Q', raw, 16, len(raw))
        raw = bytes(raw)
    image.write_bytes(raw)
    template = args.template.read_bytes()
    boot = repack(template, raw)
    # Round-trip and verify that all non-kernel components were preserved.
    _, _, before = unpack(template)
    _, _, after = unpack(boot)
    for key in before:
        assert after[key] == (raw if key == 'kernel' else before[key]), key
    destination = output / ('citrus-xnu-boot.img' if args.payload else 'citrus-diagnostic-boot.img')
    destination.write_bytes(boot)
    print(f'Built {destination} ({len(boot)} bytes)')
    print(('XNU handoff image.' if args.payload else 'Diagnostic shim only; not XNU.') +
          ' No flashing or reboot was performed.')


if __name__ == '__main__':
    main()
