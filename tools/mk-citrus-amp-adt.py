#!/usr/bin/env python3
"""Make a quarantined P/E ADT from an existing four-Gold Citrus ADT.

Silver 0 stays out: the current shim parks that CPU in WFI while Gold boots.
This file is for offline topology testing only, not packaging or flashing.
It must only be paired with an explicitly AMP-enabled 4K kernel after the
PSCI, GIC, scheduler and Silver-core startup paths have been validated.
"""
import argparse
import copy
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'upstream/ios-topaz/tools'))
import adt


def u32(value):
    return struct.pack('<I', value)


def setprop(node, name, value):
    matches = [i for i, (key, _, _) in enumerate(node.props) if key == name]
    if len(matches) != 1:
        raise ValueError(f'{node.name}: expected exactly one {name}')
    i = matches[0]
    key, flags, _ = node.props[i]
    node.props[i] = (key, flags, value)


def all_nodes(root):
    yield root
    for child in root.children:
        yield from all_nodes(child)


def convert(data, silver_count):
    if not 0 <= silver_count <= 3:
        raise ValueError('silver_count must be 0..3; Silver 0 is parked by the shim')
    root, end = adt.parse(data)
    if end != len(data):
        raise ValueError('trailing data after ADT')
    cpu_nodes = [n for n in root.children if n.name == 'cpus']
    if len(cpu_nodes) != 1:
        raise ValueError('expected one /cpus node')
    cpus = cpu_nodes[0]
    if len(cpus.children) != 4 or [n.prop('reg') for n in cpus.children] != [u32(x) for x in range(0x100, 0x104)]:
        raise ValueError('input must contain exactly Gold CPUs 0x100..0x103 in order')
    for i, n in enumerate(cpus.children):
        if n.prop('cpu-id') != u32(i) or n.prop('cluster-type') != u32(0):
            raise ValueError('input is not the expected homogeneous Citrus topology')
    phandles = []
    for n in all_nodes(root):
        for name, _, value in n.props:
            if name == 'AAPL,phandle':
                if len(value) != 4:
                    raise ValueError('invalid phandle')
                phandles.append(struct.unpack('<I', value)[0])
    if len(phandles) != len(set(phandles)) or not phandles:
        raise ValueError('missing or duplicate phandles')
    next_handle = max(phandles) + 1
    if next_handle + silver_count > 0x100000000:
        raise ValueError('phandle space exhausted')
    for n in cpus.children:
        setprop(n, 'cluster-type', u32(ord('P')))
    for core in range(1, silver_count + 1):
        n = copy.deepcopy(cpus.children[0])
        updates = {
            'name': f'cpu{3 + core}'.encode() + b'\0',
            'AAPL,phandle': u32(next_handle + core - 1),
            'reg': u32(core),
            'cpu-id': u32(3 + core),
            'cluster-id': u32(1),
            'cluster-type': u32(ord('E')),
            'die-cluster-id': u32(1),
            'cluster-core-id': u32(core),
            'l2-cache-id': u32(1),
            'state': b'stopped\0',
        }
        for key, value in updates.items():
            setprop(n, key, value)
        cpus.children.append(n)
    return adt.serialize(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--silver-cores', type=int, required=True, choices=range(4))
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error('input and output must be different')
    if args.output.exists():
        parser.error('output already exists')
    converted = convert(args.input.read_bytes(), args.silver_cores)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as f:
        f.write(converted)
    print(f'Wrote experimental ADT: 4 Gold P cores, {args.silver_cores} Silver E cores; Silver 0 excluded')
    print('Offline testing only; no image was packaged or flashed')


if __name__ == '__main__':
    main()
