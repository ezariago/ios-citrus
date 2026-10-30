#!/usr/bin/env python3
"""Package the linked GPU kernel using the verified four-core/touch profile.

Default: read-only GPUCC/PAS query, no GPU power, authentication or execution.
--execute: full GPU bring-up with firmware and a mandatory IB/fence self-test.
This tool never flashes the phone.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'upstream/ios-topaz/tools'))
import adt as apple_dt
import mkpayload


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--clock-probe', action='store_true', help='read-only fuse/SMEM discovery, leaves GPU at 300 MHz')
    parser.add_argument('--gpu-mhz', choices=['300', '600', '950'], default='300',
                        help='GFX3D rate: 300 (GPLL0/2), 600 (GPLL0/1) or 950 (PLL0 1900/2; needs --cpu-max)')
    parser.add_argument('--cpu-max', action='store_true',
                        help='sweetcpufreq=1: raise the Gold cluster to its top LUT state')
    parser.add_argument('--keys', action='store_true',
                        help='enable the existing hardware key driver (sweetkeys=1)')
    parser.add_argument('--keep-buffers', choices=['0', '1', '2'], default='0',
                        help='bounded same-client buffer reuse: 0 off, 1 reuse, 2 clear on reuse')
    parser.add_argument('--build-dir', type=Path, default=ROOT / 'out/citrus-gpu')
    parser.add_argument('--name', help='Named test image, e.g. gpu-probe2')
    parser.add_argument('--gl', choices=['0', '1'], help='override citrusgl (default: compositor profile)')
    parser.add_argument('--glblit', choices=['0', '1'], default='1',
                        help='1 (default): CoreAnimation frames are GPU-blitted from a library texture into the '
                             'IOSurface; 0: draw straight into the IOSurface (glblit=0, wrapper boot arg)')
    parser.add_argument('--extra-arg', action='append', default=[], metavar='ARG',
                        help='append a boot argument; may be repeated')
    parser.add_argument('--omit-arg', action='append', default=[], metavar='ARG',
                        help='remove an exact baseline boot argument; may be repeated')
    args = parser.parse_args()
    if args.gpu_mhz == '950' and not args.cpu_max:
        parser.error('--gpu-mhz 950 requires --cpu-max: 950 MHz relies on the '
                     'Gold top state for its CX/MX TURBO_L1 rail class')
    out = args.build_dir.resolve()
    build = json.loads((out / 'manifest.json').read_text())
    kernel = out / 'kernel.development.citrus'
    if digest(kernel) != build['kernel_sha256']:
        raise SystemExit('kernel differs from build manifest')
    if args.execute and any(not x['bytes'] for x in build['firmware'].values()):
        raise SystemExit('device firmware absent: build with --firmware-dir first')
    baseline = json.loads((ROOT / 'out/ios16/logs/touch-cpu4-manifest.json').read_text())
    adt = ROOT / baseline['adt']
    if digest(adt) != baseline['adt_sha256']:
        raise SystemExit('four-core ADT differs from verified touch baseline')
    cmdline = baseline['cmdline']
    for arg in args.omit_arg:
        parts = cmdline.split()
        if parts.count(arg) != 1:
            parser.error('--omit-arg must match exactly one baseline argument')
        parts.remove(arg)
        cmdline = ' '.join(parts)
    if 'cpus=4' not in cmdline.split() or 'sweetptimer=0' not in cmdline.split():
        raise SystemExit('unexpected CPU/timer baseline')
    gl = args.gl if args.gl is not None else ('1' if build.get('baseline_compositor') else '0')
    probe_arg = '' if args.clock_probe else ' citrusgpuprobe=0'
    cmdline += (f' gpu=1{probe_arg} gpu_mhz={args.gpu_mhz} gpu_keep={args.keep_buffers} citrusgl={gl}'
                if args.execute else ' gpu=0 citrusgpuprobe=1 citrusgl=0')
    if args.clock_probe:
        if not args.execute:
            parser.error('--clock-probe requires --execute')
        if args.gpu_mhz != '300':
            parser.error('--clock-probe must keep gpu_mhz=300')
        probe_source = out / 'xnu/iokit/Kernel/arm/TopazAdreno.cpp'
        if not probe_source.exists() or 'citrus_gpu_clock_probe();' not in probe_source.read_text():
            raise SystemExit('build does not include the opt-in clock probe')
        cmdline += ' citrusgpuclockprobe=1'
    if args.cpu_max:
        if ' sweetcpufreq=0' not in cmdline:
            parser.error('baseline cmdline has no sweetcpufreq=0 to replace')
        cmdline = cmdline.replace(' sweetcpufreq=0', ' sweetcpufreq=1', 1)
    if args.keys:
        if cmdline.split().count('sweetkeys=0') != 1:
            parser.error('baseline must contain exactly one sweetkeys=0')
        cmdline = cmdline.replace(' sweetkeys=0', ' sweetkeys=1', 1)
    if gl == '1':
        # A framebuffer console drawn over the GPU frames makes animations
        # flash the log; keep the console on USB only.
        cmdline += ' sweetfb_noconsole=1'
        if args.glblit == '0':
            # eagl.c (installed /citrus/lib/libcitrus-gl.dylib) reads this: draw
            # into the IOSurface itself instead of blitting a library texture
            # into it at the end of every frame. Every gpu=1 screen surface now
            # has 64 guard rows, which the old artifact report predates.
            cmdline += ' glblit=0'
    for arg in args.extra_arg:
        if not arg or any(c.isspace() or c == '\0' for c in arg):
            parser.error('--extra-arg must be a single nonempty boot argument')
        cmdline += ' ' + arg
    if len(cmdline.encode()) >= 0x260:
        raise SystemExit('command line exceeds the 607-byte payload limit')
    name = args.name or ('gpu-execute1' if args.execute else 'gpu-probe1')
    if not re.fullmatch('[a-z0-9-]+', name):
        raise SystemExit('invalid image name')
    payload = out / ('payload-' + name + '.bin')
    subprocess.run([sys.executable, str(ROOT / 'upstream/ios-topaz/tools/mkpayload.py'),
                    str(kernel), str(adt), str(payload), '--cmdline', cmdline], check=True)
    raw = payload.read_bytes()
    if raw[:8] != b'SWEETXNU' or raw[0x48:0x2a8].split(b'\0')[0].decode() != cmdline:
        raise SystemExit('payload header/command line mismatch')
    offset, size = struct.unpack_from('<QQ', raw, 0x20)
    tree, _ = apple_dt.parse(raw[offset:offset + size])
    cpus = next(node for node in tree.children if node.name == 'cpus')
    registers = [struct.unpack('<I', node.prop('reg'))[0] for node in cpus.children]
    if registers != [0x100, 0x101, 0x102, 0x103]:
        raise SystemExit('payload does not contain the four Gold CPU nodes')
    if mkpayload.adt_dram(raw[offset:offset + size]) != (0x80000000, 0x70000000):
        raise SystemExit('payload RAM does not match the verified 1792 MiB range')
    macho = bytearray(kernel.read_bytes())
    parsed = mkpayload.parse_macho(macho)
    mkpayload.apply_chained_fixups(macho, parsed)
    segments = [segment for segment in parsed['segs'] if segment['vmsize']]
    for index, segment in enumerate(segments):
        va, virtual_size, position, length = struct.unpack_from('<QQQQ', raw, 0x2a8 + index * 32)
        if (va, virtual_size, length) != (segment['vmaddr'], segment['vmsize'], segment['filesize']) or \
           raw[position:position + length] != macho[segment['fileoff']:segment['fileoff'] + length]:
            raise SystemExit('payload kernel segment mismatch: ' + segment['name'])
    subprocess.run([sys.executable, str(ROOT / 'tools/build-diagnostic.py'),
                    '--template', str(ROOT / 'device-dumps/20261025-141423-923416/backups/boot.img'),
                    '--payload', str(payload)], check=True)
    image = ROOT / 'out/citrus-diagnostic' / ('citrus-xnu-boot-' + name + '.img')
    shutil.copyfile(ROOT / 'out/citrus-diagnostic/citrus-xnu-boot.img', image)
    manifest = {'image': str(image.relative_to(ROOT)), 'sha256': digest(image),
                'size': image.stat().st_size, 'kernel_sha256': digest(kernel),
                'adt': str(adt.relative_to(ROOT)), 'adt_sha256': digest(adt),
                'cmdline': cmdline, 'payload_sha256': digest(payload),
                'gpu_build': build, 'hardware_tested': False,
                'payload_verified': {'gold_mpidrs': [hex(x) for x in registers],
                                     'kernel_segments_byte_identical': len(segments), 'full_command_line': True},
                'mode': 'execution-selftest' if args.execute else 'gpucc-read-and-pas-query'}
    (out / (name + '-manifest.json')).write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'{image}\nsha256 {manifest["sha256"]}')


if __name__ == '__main__':
    main()
