#!/usr/bin/env python3
"""Package a 4 KiB-page Citrus diagnostic with an explicit ADT and cmdline.

This is the guarded path for the SMP/AMP experiments: it pins the kernel and
ADT digests, checks that the ADT CPU count matches cpus= in the boot arguments,
repackages only the kernel component of the verified boot template, and runs
the Unicorn shim segment/boot-argument test before writing a candidate image.
It never flashes or reboots the phone.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'upstream/ios-topaz/tools'))
import adt
import mkpayload
from bootimage import unpack

TEMPLATE = ROOT / 'device-dumps/20261025-141423-923416/backups/boot.img'
EXPECTED_TEMPLATE = '77c77db8a23ab9cfc92a4e6001a41a1762b78ec9d11a4f34cf535bf747dbe6c1'
PRODUCT = ROOT / 'out/ios16/d22ap.adt'
PYTHON_DEPS = ROOT / 'out/citrus-8core/preflight/python-deps'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def cpu_nodes(adt_path):
    tree, consumed = adt.parse(adt_path.read_bytes())
    if consumed != adt_path.stat().st_size:
        raise SystemExit('trailing bytes after ADT')
    cpus = next((n for n in tree.children if n.name == 'cpus'), None)
    if cpus is None or not cpus.children:
        raise SystemExit('ADT has no /cpus children')
    return tree, cpus.children


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--kernel-sha256', required=True)
    parser.add_argument('--adt', type=Path, required=True)
    parser.add_argument('--adt-sha256', required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--cmdline', required=True)
    parser.add_argument('--out-dir', type=Path, default=ROOT / 'out/citrus-8core')
    parser.add_argument('--allow-boot-cpu', default='0x100',
                        help='expected boot MPIDR of logical CPU 0 (default 0x100)')
    args = parser.parse_args()

    if sha(args.kernel) != args.kernel_sha256:
        raise SystemExit('kernel digest does not match --kernel-sha256')
    if sha(args.adt) != args.adt_sha256:
        raise SystemExit('ADT digest does not match --adt-sha256')
    if sha(TEMPLATE) != EXPECTED_TEMPLATE:
        raise SystemExit('boot template digest mismatch')
    if not PRODUCT.is_file() or not PYTHON_DEPS.is_dir():
        raise SystemExit('D22AP ADT or isolated Unicorn dependency is missing')
    if len(args.cmdline.encode()) >= 608:
        raise SystemExit('boot arguments exceed the 608-byte payload field')

    tree, cpus = cpu_nodes(args.adt)
    if len(cpus) > 8:
        raise SystemExit('ADT has more than eight CPUs')
    boot_reg = struct.unpack('<I', cpus[0].prop('reg'))[0]
    if boot_reg != int(args.allow_boot_cpu, 0):
        raise SystemExit(f'logical CPU0 is MPIDR {boot_reg:#x}, expected {args.allow_boot_cpu}')
    requested = [word.split('=', 1)[1] for word in args.cmdline.split() if word.startswith('cpus=')]
    if len(requested) != 1 or int(requested[0]) != len(cpus):
        raise SystemExit(f'cmdline cpus= must equal the ADT CPU count ({len(cpus)})')
    if mkpayload.adt_dram(args.adt.read_bytes()) != (0x80000000, 0x70000000):
        raise SystemExit('unexpected ADT RAM bounds')
    if not any(n.name == 'product' for n in tree.children) or not any(n.name == 'sweet-ufs' for n in tree.children):
        raise SystemExit('ADT is missing product identity or UFS')

    out = args.out_dir.resolve() / args.name
    out.mkdir(parents=True, exist_ok=True)
    adt_path, payload = out / f'{args.name}.adt', out / 'payload.bin'
    shutil.copyfile(args.adt, adt_path)
    subprocess.run([sys.executable, str(ROOT / 'upstream/ios-topaz/tools/mkpayload.py'),
                    str(args.kernel), str(adt_path), str(payload),
                    '--cmdline', args.cmdline], check=True)
    raw = payload.read_bytes()
    if raw[:8] != b'SWEETXNU' or raw[0x48:0x2a8].split(b'\0')[0].decode() != args.cmdline:
        raise SystemExit('payload header or args mismatch')
    off, size = struct.unpack_from('<QQ', raw, 0x20)
    if raw[off:off + size] != adt_path.read_bytes():
        raise SystemExit('payload ADT mismatch')
    parsed = mkpayload.parse_macho(bytearray(args.kernel.read_bytes()))
    if parsed['fixups']:
        raise SystemExit('unexpected kernel chained fixups')
    segments = [s for s in parsed['segs'] if s['vmsize']]
    if struct.unpack_from('<I', raw, 12)[0] != len(segments):
        raise SystemExit('kernel segment count mismatch')
    for i, seg in enumerate(segments):
        va, memsize, pos, fsize = struct.unpack_from('<4Q', raw, 0x2a8 + 32 * i)
        if (va, memsize, fsize) != (seg['vmaddr'], seg['vmsize'], seg['filesize']):
            raise SystemExit(f'kernel segment header mismatch: {seg["name"]}')

    subprocess.run([sys.executable, str(ROOT / 'tools/build-diagnostic.py'),
                    '--template', str(TEMPLATE), '--payload', str(payload)], check=True)
    env = dict(os.environ, PYTHONPATH=str(PYTHON_DEPS))
    subprocess.run([sys.executable, str(ROOT / 'tools/test-diagnostic.py'), '--loader'],
                   check=True, env=env)
    generated = ROOT / 'out/citrus-diagnostic/citrus-xnu-boot.img'
    _, _, original = unpack(TEMPLATE.read_bytes())
    _, _, candidate = unpack(generated.read_bytes())
    if any(candidate[k] != v for k, v in original.items() if k != 'kernel'):
        raise SystemExit('non-kernel boot image component changed')
    image = out / f'citrus-xnu-boot-4k-{args.name}.img'
    shutil.copyfile(generated, image)
    manifest = {
        'status': 'experimental 4 KiB diagnostic; hardware-tested only after flash',
        'name': args.name,
        'kernel': str(args.kernel), 'kernel_sha256': sha(args.kernel),
        'adt': str(args.adt), 'adt_sha256': sha(args.adt),
        'boot_template_sha256': sha(TEMPLATE),
        'image_sha256': sha(image), 'image_bytes': image.stat().st_size,
        'payload_sha256': sha(payload),
        'cmdline': args.cmdline,
        'cpus': len(cpus),
        'cpu_mpidrs': [struct.unpack('<I', n.prop('reg'))[0] for n in cpus],
        'validated': {
            'kernel_segments': len(segments),
            'boot_template_components_preserved': True,
            'unicorn_shim_segment_and_bootargs': True,
            'hardware': False,
        },
        'limits': [
            'no XNU execution in the emulator',
            '4 KiB page tables, signing and GIC/PSCI are unverified until boot',
            'GPU/touch firmware may be placeholders depending on the kernel input',
        ],
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'image': str(image), 'sha256': manifest['image_sha256'],
                      'cpus': manifest['cpus'],
                      'cpu_mpidrs': [hex(x) for x in manifest['cpu_mpidrs']]}, indent=2))


if __name__ == '__main__':
    main()
