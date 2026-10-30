#!/usr/bin/env python3
"""Check GPU MMIO windows and firmware reservation against the captured live DT.

No MMIO or phone access. This establishes resource provenance, not power-on.
"""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def main():
    capture = ROOT / 'device-dumps/20261025-141423-923416/live-tree.json'
    tree = json.loads(capture.read_text())
    source = (ROOT / 'out/citrus-gpu/xnu/iokit/Kernel/arm/TopazAdreno.cpp').read_text()
    constants = {name: int(value, 16) for name, value in
                 re.findall(r'^#define\s+(\w+)\s+(0x[0-9a-fA-F]+)', source, re.M)}
    nodes = {}
    checks = []
    for label, fragment in [('GPU', '/qcom,kgsl-3d0@5900000'),
                            ('GPUCC', '/qcom,gpucc@5990000'),
                            ('SMMU', '/kgsl-smmu@0x59a0000'),
                            ('GCC', '/qcom,gcc@1400000')]:
        matches = [(key, value) for key, value in tree.items() if key.endswith(fragment)]
        if len(matches) != 1:
            raise SystemExit('missing or ambiguous DT node ' + fragment)
        path, node = matches[0]
        values = [int(v, 16) for v in node['reg']]
        start, size = values[:2]
        base, mapped = constants[label + '_BASE'], constants[label + '_SIZE']
        if not (start <= base and base + mapped <= start + size):
            raise SystemExit(f'{label} mapping does not fit captured DT resource')
        checks.append({'resource': label, 'node': path, 'dt_base': hex(start), 'dt_size': hex(size),
                       'driver_base': hex(base), 'driver_size': hex(mapped)})
        nodes[path] = node
    zap_path = '/reserved-memory/gpu_region@55A15000'
    zap = tree[zap_path]
    cells = [int(v, 16) for v in zap['reg']]
    zap_base, zap_size = cells[0] << 32 | cells[1], cells[2] << 32 | cells[3]
    if constants['ZAP_REGION'] != zap_base or constants['ZAP_REGION_SIZE'] != zap_size:
        raise SystemExit('zap firmware region differs from the DT reservation')
    if not zap.get('no-map'):
        raise SystemExit('zap region lacks no-map')
    nodes[zap_path] = zap
    hyp_path = '/soc/qcom,kgsl-hyp'
    nodes[hyp_path] = tree[hyp_path]
    if int(tree[hyp_path]['qcom,pas-id'][0], 16) != 13:
        raise SystemExit('unexpected GPU PAS ID')
    if 'GPU_POOL_BASE' in constants:
        raise SystemExit('unsafe fixed physical GPU pool reintroduced')
    chip = int(tree['/soc/qcom,kgsl-3d0@5900000']['qcom,chipid'][0], 16)
    if chip != 0x06010000:
        raise SystemExit('unexpected chip ID')
    report = {'hardware_tested': False, 'capture': str(capture.relative_to(ROOT)),
              'capture_sha256': hashlib.sha256(capture.read_bytes()).hexdigest(),
              'chip_id': hex(chip), 'zap_base': hex(zap_base), 'zap_size': hex(zap_size),
              'managed_ram': ['0x80000000', '0xf0000000'], 'cpu_page_size': 16384,
              'clock_policy': 'GPLL0 / 2, 300 MHz bring-up; no PLL or RPM voltage programming',
              'static_checks': checks, 'nodes': nodes}
    destination = ROOT / 'devices/citrus.gpu.json'
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print('GPU/GPUCC/SMMU/GCC windows and zap reservation match captured DT -> ' + str(destination))


if __name__ == '__main__':
    main()
