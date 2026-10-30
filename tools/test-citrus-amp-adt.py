#!/usr/bin/env python3
"""Round-trip and reject malformed offline Citrus AMP device trees."""
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'upstream/ios-topaz/tools'))
import adt

spec = importlib.util.spec_from_file_location('citrus_amp', ROOT / 'tools/mk-citrus-amp-adt.py')
amp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(amp)


def val(node, key):
    return struct.unpack('<I', node.prop(key))[0]


def main():
    with tempfile.TemporaryDirectory(prefix='citrus-amp-adt-') as tmp:
        source = Path(tmp) / 'gold.adt'
        subprocess.run([sys.executable, str(ROOT / 'tools/mk-citrus-adt.py'), str(source),
                        '--cpus', '4', '--ram-mib', '1792'], check=True, capture_output=True)
        baseline = source.read_bytes()
        for count in range(4):
            converted = amp.convert(baseline, count)
            root, end = adt.parse(converted)
            assert end == len(converted)
            cpus = next(n for n in root.children if n.name == 'cpus').children
            assert [val(n, 'reg') for n in cpus] == list(range(0x100, 0x104)) + list(range(1, count + 1))
            assert [val(n, 'cluster-type') for n in cpus] == [ord('P')] * 4 + [ord('E')] * count
            assert [val(n, 'cluster-id') for n in cpus] == [0] * 4 + [1] * count
            assert [val(n, 'cpu-id') for n in cpus] == list(range(4 + count))
            assert [val(n, 'cluster-core-id') for n in cpus] == list(range(4)) + list(range(1, count + 1))
            handles = [val(n, 'AAPL,phandle') for n in amp.all_nodes(root) if n.prop('AAPL,phandle')]
            assert len(handles) == len(set(handles))
            assert [n.prop('state') for n in cpus] == [b'running\0'] + [b'stopped\0'] * (3 + count)
            # With HAS_CLUSTER unset, XNU groups by (cluster_type == P):
            # the first cluster encountered becomes logical 0, the other logical 1.
            seen = {}
            logical = [seen.setdefault(int(val(n, 'cluster-type') == ord('P')), len(seen)) for n in cpus]
            assert logical == [0] * 4 + [1] * count
        try:
            amp.convert(baseline, 4)
            raise AssertionError('parked Silver 0 was not rejected')
        except ValueError:
            pass
        root, _ = adt.parse(baseline)
        cpus = next(n for n in root.children if n.name == 'cpus')
        cpus.children[1].props = [(k, f, amp.u32(0x100) if k == 'reg' else v) for k, f, v in cpus.children[1].props]
        try:
            amp.convert(adt.serialize(root), 3)
            raise AssertionError('duplicate MPIDR was not rejected')
        except ValueError:
            pass
    print('PASS: offline 4P+0..3E ADT round trips, parked CPU exclusion and malformed input')


if __name__ == '__main__':
    main()
