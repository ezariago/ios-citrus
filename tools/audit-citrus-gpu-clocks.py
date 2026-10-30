#!/usr/bin/env python3
"""Record stock clock/voltage prerequisites from captured DT and pinned kernel.

Read-only host analysis; does not change clocks, voltages or boot images.
"""
import hashlib
import json
import re
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'out/citrus-vendor-kernel'
CAPTURE = ROOT / 'device-dumps/20261025-141423-923416/live-tree.json'


def main():
    tree = json.loads(CAPTURE.read_text())
    gpu = tree['/soc/qcom,kgsl-3d0@5900000']
    clock = tree['/soc/qcom,gpucc@5990000']
    def resolve(handle):
        nodes = [(p, v) for p, v in tree.items() if v.get('phandle') == [handle]]
        if len(nodes) != 1:
            raise ValueError('nonunique phandle ' + handle)
        return nodes[0]
    bins = []
    prefix = '/soc/qcom,kgsl-3d0@5900000/qcom,gpu-pwrlevel-bins/'
    for path, node in tree.items():
        if not path.startswith(prefix) or 'qcom,speed-bin' not in node:
            continue
        levels = []
        for p, v in tree.items():
            if p.startswith(path + '/') and 'qcom,gpu-freq' in v:
                hz = int(v['qcom,gpu-freq'][0], 0)
                if hz:
                    levels.append({'mhz': hz // 1000000,
                                   'bus_index': int(v['qcom,bus-freq'][0], 0)})
        bins.append({'speed_bin': int(node['qcom,speed-bin'][0], 0), 'levels': levels})
    common = sorted(set.intersection(*[{v['mhz'] for v in b['levels']} for b in bins]))
    supplies = {}
    for key in ['vdd_cx-supply', 'vdd_mx-supply']:
        path, node = resolve(clock[key][0]); resource = tree[path.rsplit('/', 1)[0]]
        supplies[key] = {'node': path, 'regulator': node['regulator-name'][0],
                         'resource_type': resource['qcom,resource-name'][0],
                         'resource_id': int(resource['qcom,resource-id'][0], 0),
                         'uses_voltage_level': 'qcom,use-voltage-level' in node}
    opps = []
    for path, node in tree.items():
        if path.startswith('/soc/gpu-opp-table/opp-'):
            words = [int(x, 0) for x in node['opp-hz']]
            opps.append({'mhz': ((words[0] << 32) | words[1]) // 1000000,
                         'encoded_regulator_level': int(node['opp-microvolt'][0], 0)})
    sources = ['drivers/clk/qcom/gpucc-bengal.c', 'drivers/clk/qcom/clk-alpha-pll.c', 'drivers/clk/clk.c',
               'drivers/clk/qcom/vdd-level-bengal.h', 'drivers/clk/qcom/clk-regmap.c',
               'drivers/regulator/rpm-smd-regulator.c', 'drivers/rpmsg/rpm-smd.c',
               'drivers/rpmsg/qcom_smd.c', 'drivers/rpmsg/qcom_glink_rpm.c',
               'drivers/rpmsg/qcom_glink_native.c', 'drivers/gpu/msm/adreno.c', 'drivers/soc/qcom/smem.c',
               'drivers/soc/qcom/msm_bus/msm_bus_rpm_smd.c']
    live = ROOT / 'out/ios16/logs/gpu-clockprobe1-live.txt'
    match = re.search(r'CitrusClock: fuse speed_bin=(\d+) gaming_bin=(\d+)',
                      live.read_text(errors='replace')) if live.exists() else None
    fused_bin = int(match[1]) if match else None
    matching_bin = next((b for b in bins if b['speed_bin'] == fused_bin), None)
    result = {'capture': str(CAPTURE.relative_to(ROOT)),
              'capture_sha256': hashlib.sha256(CAPTURE.read_bytes()).hexdigest(),
              'stock_kernel_commit': subprocess.check_output(['git', '-C', str(VENDOR), 'rev-parse', 'HEAD'], text=True).strip(),
              'stock_source_sha256': {p: hashlib.sha256((VENDOR / p).read_bytes()).hexdigest() for p in sources},
              'current_driver_mhz': 300, 'common_stock_mhz_across_dt_bins': common,
              'actual_fuse_bin_known': match is not None, 'observed_speed_bin': fused_bin,
              'observed_gaming_bin': int(match[2]) if match else None,
              'fused_bin_max_stock_mhz': max(v['mhz'] for v in matching_bin['levels']) if matching_bin else None,
              'speed_bins': bins,
              'opps': sorted(opps, key=lambda v: v['mhz']), 'clock_supplies': supplies,
              'voltage_transport': 'RPM-SMD frontend, rpm_requests RPMsg over GLINK-RPM; not traditional SMEM-SMD or inherited RPMh',
              'rpm_message_ram': tree['/soc/memory@045f0000'],
              'rpm_glink': tree['/soc/rpm-glink'],
              'apcs_mailbox': tree['/soc/mailbox@0f111000'],
              'rpm_wire_format': 'stock driver defaults to v0 when the DT RPM node has no reg property',
              'stock_levels_are_not_microvolts': True,
              'clock_parent': 'Bengal default alpha PLLs; PLL1 AUX /2 for 320/465, PLL0 AUX2 /2 for 600+',
              'higher_clock_implemented': False, 'higher_clock_applied': False, 'probe_boot_only': match is not None}
    destination = ROOT / 'research/citrus-gpu-clock-audit.json'
    destination.write_text(json.dumps(result, indent=2) + '\n')
    print(destination)
    print('Common stock rates (MHz):', common)
    print('Clock supplies:', json.dumps(supplies))


if __name__ == '__main__':
    main()
