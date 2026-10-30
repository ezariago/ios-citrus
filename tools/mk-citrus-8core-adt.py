#!/usr/bin/env python3
"""Generate the experimental eight-core Citrus ADT (Gold P + Silver E).

The real Kryo 260 topology is four Silver Cortex-A53 cores at MPIDR 0x000-0x003
and four Gold Cortex-A73 cores at 0x100-0x103.  The production ADT generator
only publishes the Gold cluster because the 16 KiB kernel cannot run on Silver.
This tool is only for the 4 KiB experiments.

`--boot gold` orders Gold first and omits Silver 0 when `--silver-cores 3`,
matching the shim that parks Silver 0.  `--boot silver` publishes all eight with
Silver 0 as logical CPU 0; it is the target topology once the shim can hand XNU
to the Silver boot core directly.
"""
import argparse
import copy
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'upstream/ios-topaz/tools'))
import adt
import mkadt

mkadt.D22AP_ADT = str(ROOT / 'out/ios16/d22ap.adt')
if Path(mkadt.D22AP_ADT).exists():
    _d22ap_product = mkadt.d22ap_product
    mkadt.d22ap_product = lambda: _d22ap_product(mkadt.D22AP_ADT)
mkadt.PHYS_BASE = 0x80000000
mkadt.MEM_SIZE = 0x70000000
mkadt.FB_H = 2340


def setprop(node, name, value):
    for i, (key, flags, _) in enumerate(node.props):
        if key == name:
            node.props[i] = (key, flags, value)
            return
    node.props.append((name, 0, value))


def all_nodes(root):
    yield root
    for child in root.children:
        yield from all_nodes(child)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--boot', choices=('gold', 'silver'), default='gold')
    parser.add_argument('--silver-cores', type=int, choices=(3, 4), default=3)
    parser.add_argument('--topology', choices=('smp', 'amp'), default='amp',
                        help='smp: one homogeneous cluster (no AMP scheduler); amp: P/E sets')
    parser.add_argument('--ufs', action='store_true')
    parser.add_argument('--display', action='store_true')
    parser.add_argument('--ram-mib', type=int, default=1792)
    args = parser.parse_args()
    if args.boot == 'gold' and args.silver_cores == 4:
        parser.error('the Gold-boot shim parks Silver 0; use --silver-cores 3 or --boot silver')
    if not 256 <= args.ram_mib <= 1792 or args.ram_mib % 16:
        parser.error('--ram-mib must be a multiple of 16 between 256 and 1792')
    if args.output.exists():
        parser.error('output already exists')
    mkadt.MEM_SIZE = args.ram_mib << 20
    tree = mkadt.build(native=True)
    tree.children = [n for n in tree.children if args.ufs or n.name != 'sweet-ufs']
    for n in tree.children:
        if n.name == 'arm-io':
            n.children = [c for c in n.children if c.name != 'wlan' and
                          (args.display or c.name != 'disp0')]
            for c in n.children:
                if c.name == 'disp0':
                    setprop(c, 'canvas-height', struct.pack('<I', 2340))
        elif n.name == 'chosen':
            setprop(n, 'firmware-version', b'citrus-shim\0')
            setprop(n, 'system-firmware-version', b'citrus-shim\0')
            setprop(n, 'mac-address-wifi0', bytes.fromhex('024349545253'))

    cpus = next(n for n in tree.children if n.name == 'cpus')
    gold = cpus.children
    if len(gold) != 4:
        raise SystemExit('mkadt did not produce four Gold CPUs')
    phandles = [struct.unpack('<I', n.prop('AAPL,phandle'))[0] for n in all_nodes(tree)
                if n.prop('AAPL,phandle')]
    next_phandle = max(phandles) + 1

    amp = args.topology == 'amp'
    for core, n in enumerate(gold):
        setprop(n, 'reg', struct.pack('<I', 0x100 | core))
        setprop(n, 'cluster-id', struct.pack('<I', 1 if amp else 0))
        setprop(n, 'cluster-type', struct.pack('<I', ord('P') if amp else 0))
        setprop(n, 'die-cluster-id', struct.pack('<I', 1 if amp else 0))
        setprop(n, 'cluster-core-id', struct.pack('<I', core))
        setprop(n, 'l2-cache-id', struct.pack('<I', 1 if amp else 0))
        setprop(n, 'clock-frequency', struct.pack('<I', 2000000000))

    silver = []
    for core in range(4):
        n = copy.deepcopy(gold[0])
        setprop(n, 'name', f'cpuE{core}'.encode() + b'\0')
        setprop(n, 'AAPL,phandle', struct.pack('<I', next_phandle + core))
        setprop(n, 'reg', struct.pack('<I', core))
        setprop(n, 'cpu-id', struct.pack('<I', core))
        setprop(n, 'cluster-id', struct.pack('<I', 0))
        setprop(n, 'cluster-type', struct.pack('<I', ord('E') if amp else 0))
        setprop(n, 'die-cluster-id', struct.pack('<I', 0))
        setprop(n, 'cluster-core-id', struct.pack('<I', 4 + core if not amp else core))
        setprop(n, 'l2-cache-id', struct.pack('<I', 0))
        setprop(n, 'clock-frequency', struct.pack('<I', 1800000000))
        silver.append(n)

    for core, n in enumerate(gold):
        setprop(n, 'cpu-id', struct.pack('<I', len(silver) + core if args.boot == 'silver' else core))
        setprop(n, 'state', b'running\0' if args.boot == 'gold' and core == 0 else b'stopped\0')
    for core, n in enumerate(silver):
        setprop(n, 'cpu-id', struct.pack('<I', core if args.boot == 'silver' else len(gold) + core - 1))
        setprop(n, 'state', b'running\0' if args.boot == 'silver' and core == 0 else b'stopped\0')

    if args.boot == 'silver':
        cpus.children = silver + gold
    else:
        cpus.children = gold + silver[4 - args.silver_cores:]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(adt.serialize(tree))
    print(f'Wrote {args.output}: boot={args.boot}, topology={args.topology}, '
          f'{len(gold)} Gold + {len(cpus.children) - len(gold)} Silver')


if __name__ == '__main__':
    main()
