#!/usr/bin/env python3
"""Generate a one-Gold-core ADT for a driver-free Citrus XNU boot."""
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
mkadt.MEM_SIZE = 0x40000000
mkadt.FB_H = 2340
mkadt.SWEET_ECID = 0x4349545255530001
tree = mkadt.build(native=True)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('output', type=pathlib.Path)
parser.add_argument('--ufs', action='store_true', help='Include UFS node; use ufsrw=0 for read-only probe')
parser.add_argument('--display', action='store_true', help='Include native-sized iOS display service')
args = parser.parse_args()
tree.children = [node for node in tree.children if args.ufs or node.name != 'sweet-ufs']
for node in tree.children:
    if node.name == 'cpus':
        node.children = node.children[:1]
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
print(f'Wrote {destination}: one Gold core, 1 GiB at 0x80000000, UFS={args.ufs}, display={args.display}, WLAN=False')
