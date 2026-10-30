#!/usr/bin/env python3
"""Prepare a quarantined, read-only, one-Gold 4K boot diagnostic.

This creates files only in this checkout's out/ directory and never accesses the
phone. It is an experimental diagnostic: no GPU or touch, signing behavior is
incomplete, and neither 4K boot nor read-only root operation has been verified
on hardware. It must not replace the working boot without a recovery plan.
"""
import hashlib
import json
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

OUT = ROOT / 'out/citrus-8core/gold1-probe'
KERNEL = ROOT / 'out/citrus-8core/ci-run-40531392449/citrus-4k-compile-diagnostics/dxb/fakeroot/System/Library/Kernels/kernel.development.sweet'
EXPECTED_KERNEL = '1492c683fac55578e757446395c48fc345c53dd3ed84ca688cb5e4caae1e3fb8'
TEMPLATE = ROOT / 'device-dumps/20261025-141423-923416/backups/boot.img'
EXPECTED_TEMPLATE = '77c77db8a23ab9cfc92a4e6001a41a1762b78ec9d11a4f34cf535bf747dbe6c1'
PRODUCT = ROOT / 'out/ios16/d22ap.adt'
PYTHON_DEPS = ROOT / 'out/citrus-8core/preflight/python-deps'
CMDLINE = ('debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=ufsroot0 '
           'ufsrw=0 rootrw=0 wdt=-1 wdt_test=no_user_checkin '
           'unentitled_ios_sim_launch=1 launchd_unsecure_cache=1 '
           'sweetkeys=0 sweetbattery=0 sweetcpufreq=0 sweetchg=0 sweethw=0 '
           'sweettouch=0 citrustouchprobe=0 sweetfb_stayon=1 sweetfb_native=1 '
           'sweetwdt=0 sweetpanel=1 sweetirqwr=0 sweetusb=2 sweetusbspin=0 '
           'sweetlog=0 sweetptimer=0 sweetptrecord=0 sweetvrecord=1 sweetufsclk=1 '
           'wfe_mode=0 gpu=0 citrusgpuprobe=0 citrusgl=0')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def main():
    if sha(KERNEL) != EXPECTED_KERNEL or sha(TEMPLATE) != EXPECTED_TEMPLATE:
        raise SystemExit('kernel or boot template does not match its pinned digest')
    if not PRODUCT.is_file() or not PYTHON_DEPS.is_dir():
        raise SystemExit('D22AP ADT or isolated Unicorn dependency is missing')
    if len(CMDLINE.encode()) >= 608:
        raise SystemExit('boot arguments exceed payload limit')
    OUT.mkdir(parents=True, exist_ok=True)
    adt_path, payload = OUT / 'gold1.adt', OUT / 'payload.bin'
    subprocess.run([sys.executable, str(ROOT / 'tools/mk-citrus-adt.py'), str(adt_path),
                    '--cpus', '1', '--ram-mib', '1792', '--ufs', '--display'], check=True)
    tree, consumed = adt.parse(adt_path.read_bytes())
    cpus = next(n for n in tree.children if n.name == 'cpus')
    if consumed != adt_path.stat().st_size or len(cpus.children) != 1 or cpus.children[0].prop('reg') != struct.pack('<I', 0x100):
        raise SystemExit('ADT is not one Gold boot core')
    if not any(n.name == 'product' for n in tree.children) or not any(n.name == 'sweet-ufs' for n in tree.children):
        raise SystemExit('ADT is missing product identity or UFS')
    if mkpayload.adt_dram(adt_path.read_bytes()) != (0x80000000, 0x70000000):
        raise SystemExit('unexpected RAM bounds')
    subprocess.run([sys.executable, str(ROOT / 'upstream/ios-topaz/tools/mkpayload.py'),
                    str(KERNEL), str(adt_path), str(payload), '--cmdline', CMDLINE], check=True)
    raw = payload.read_bytes()
    if raw[:8] != b'SWEETXNU' or raw[0x48:0x2a8].split(b'\0')[0].decode() != CMDLINE:
        raise SystemExit('payload arguments do not match locked diagnostic profile')
    off, size = struct.unpack_from('<QQ', raw, 0x20)
    if raw[off:off + size] != adt_path.read_bytes():
        raise SystemExit('payload ADT mismatch')
    kernel_bytes = bytearray(KERNEL.read_bytes())
    parsed = mkpayload.parse_macho(kernel_bytes)
    if parsed['fixups']:
        raise SystemExit('unexpected kernel chained fixups; investigate before packaging')
    segments = [s for s in parsed['segs'] if s['vmsize']]
    if struct.unpack_from('<I', raw, 12)[0] != len(segments):
        raise SystemExit('kernel segment count mismatch')
    for i, seg in enumerate(segments):
        va, memsize, pos, size = struct.unpack_from('<4Q', raw, 0x2a8 + 32 * i)
        if (va, memsize, size) != (seg['vmaddr'], seg['vmsize'], seg['filesize']) or raw[pos:pos + size] != kernel_bytes[seg['fileoff']:seg['fileoff'] + size]:
            raise SystemExit(f'kernel segment mismatch: {seg["name"]}')
    subprocess.run([sys.executable, str(ROOT / 'tools/build-diagnostic.py'), '--template', str(TEMPLATE), '--payload', str(payload)], check=True)
    env = dict(__import__('os').environ, PYTHONPATH=str(PYTHON_DEPS))
    subprocess.run([sys.executable, str(ROOT / 'tools/test-diagnostic.py'), '--loader'], check=True, env=env)
    generated = ROOT / 'out/citrus-diagnostic/citrus-xnu-boot.img'
    _, _, original_parts = unpack(TEMPLATE.read_bytes())
    _, _, candidate_parts = unpack(generated.read_bytes())
    if any(candidate_parts[k] != v for k, v in original_parts.items() if k != 'kernel'):
        raise SystemExit('non-kernel boot image component changed')
    image = OUT / 'citrus-xnu-boot-4k-gold1-readonly.img'
    shutil.copyfile(generated, image)
    manifest = {
        'status': 'experimental; never hardware-tested; not approved for flashing',
        'kernel_sha256': sha(KERNEL), 'boot_template_sha256': sha(TEMPLATE),
        'image_sha256': sha(image), 'adt_sha256': sha(adt_path), 'payload_sha256': sha(payload),
        'product_adt_sha256': sha(PRODUCT), 'cmdline': CMDLINE,
        'ci_run': 40531392449, 'ci_commit': '7e84cd1c0d6e5e995a54879d5b15b3b75b4bfc57',
        'validated': {'kernel_segments': len(segments), 'boot_template_components_preserved': True,
                      'unicorn_shim_segment_and_bootargs': True, 'hardware': False},
        'limits': ['GPU and touch firmware are empty stubs and disabled',
                   '16K signature units may remain unvalidated',
                   'root read-only configuration untested on 4K hardware',
                   'no XNU execution in emulator', 'Silver cores unavailable'],
    }
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Experimental candidate: {image}\nSHA256: {manifest["image_sha256"]}')
    print('No flash performed. Hardware safety and read-only behavior remain unverified.')


if __name__ == '__main__':
    main()
