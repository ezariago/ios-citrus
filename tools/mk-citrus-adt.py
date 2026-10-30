#!/usr/bin/env python3
"""Generate a Citrus ADT: 1-4 Gold cores, optional UFS and display nodes."""
import pathlib
import struct
import sys
import argparse

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'upstream/ios-topaz/tools'))
import mkadt
import adt

# Use the real D22AP device tree decompressed into out/ios16 for /product
# identity (product type/device class/UI). mkadt binds its default path at
# definition time, so override the function itself.
mkadt.D22AP_ADT = str(ROOT / 'out/ios16/d22ap.adt')
if pathlib.Path(mkadt.D22AP_ADT).exists():
    _d22ap_product = mkadt.d22ap_product
    mkadt.d22ap_product = lambda: _d22ap_product(mkadt.D22AP_ADT)

mkadt.PHYS_BASE = 0x80000000
mkadt.FB_H = 2340
mkadt.SWEET_ECID = 0x4349545255530001
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('output', type=pathlib.Path)
parser.add_argument('--ufs', action='store_true', help='Include UFS node; use ufsrw=0 for read-only probe')
parser.add_argument('--display', action='store_true', help='Include native-sized iOS display service')
parser.add_argument('--ram-mib', type=int, default=1024,
                    help='Kernel-managed RAM from 0x80000000 (1024 default; 1792 verified '
                         'free below the 0xf3c00000 reservation, ending at 0xf0000000). '
                         'Not a tuning knob: shim/xnu-loader.c whitelists 1024/1792, and 4 GiB '
                         'is impossible — RAM from 0x80000000 is 3 GiB (ends at 0x140000000).')
parser.add_argument('--cpus', type=int, default=1,
                    help='Number of Gold (A73) CPU nodes to publish, 1-4. ml_parse_cpu_topology '
                         'selects this many only if the cmdline also says cpus=N; the remaining '
                         'cores are started by PSCI (SweetCPU.cpp). SMP is NOT hardware-tested '
                         'on citrus: 1 is the only proven value.')
args = parser.parse_args()
# 0x80000000..0xf3c00000 is System RAM with no reservation; stay below it.
if not 256 <= args.ram_mib <= 1792 or args.ram_mib % 16:
    parser.error('--ram-mib must be a multiple of 16 between 256 and 1792')
if not 1 <= args.cpus <= 4:
    parser.error('--cpus must be 1-4: mkadt.py emits only the four Gold A73 nodes '
                 '(MPIDR 0x100-0x103) on the phone path')
mkadt.MEM_SIZE = args.ram_mib << 20
tree = mkadt.build(native=True)
tree.children = [node for node in tree.children if args.ufs or node.name != 'sweet-ufs']
for node in tree.children:
    if node.name == 'cpus':
        node.children = node.children[:args.cpus]
        cpu = node.children[0]
        cpu.props = [(name, flags, struct.pack('<I', 2000000000) if name == 'clock-frequency' else value)
                     for name, flags, value in cpu.props]
    elif node.name == 'arm-io':
        node.children = [child for child in node.children if child.name != 'wlan' and
                         (args.display or child.name != 'disp0')]
        for child in node.children:
            if child.name == 'disp0':
                child.props = [(name, flags, struct.pack('<I', 2340) if name == 'canvas-height' else value)
                               for name, flags, value in child.props]
    elif node.name == 'chosen':
        node.props = [(name, flags, b'citrus-shim\0' if name in
                       ('firmware-version', 'system-firmware-version') else value)
                      for name, flags, value in node.props]
        # MobileGestalt tries this before waiting for an IONetworkController.
        # Without Wi-Fi, that wait stalls lsd's built-in app identity generation
        # and therefore SpringBoard's LaunchServices database access. This is a
        # synthetic, locally administered identity, not a working network device.
        node.props.append(('mac-address-wifi0', 0, bytes.fromhex('024349545253')))
destination = args.output
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_bytes(adt.serialize(tree))
print(f'Wrote {destination}: {args.cpus} Gold core(s), {args.ram_mib} MiB at 0x80000000, '
      f'UFS={args.ufs}, display={args.display}, WLAN=False')
