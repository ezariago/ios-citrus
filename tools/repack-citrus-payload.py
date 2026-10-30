#!/usr/bin/env python3
"""Rebuild a SWEETXNU payload from an existing Citrus image with a new ADT.

The kernel segment bytes, entry point and physical layout are preserved exactly;
only the ADT and boot arguments are replaced.  This is for hardware experiments
where the kernel under test has already been linked (and may contain local UFS,
USB or firmware changes that are not reproducible from the checked-in CI tree).

Input may be a full boot image or the bare shim `Image`.  The output is a
payload suitable for `tools/build-diagnostic.py --payload`.
"""
import argparse
import hashlib
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'upstream/ios-topaz/tools'))
import mkpayload
from bootimage import unpack

HEADER = 0x2a8


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bare_image(data):
    if data[:4] == b'\x1f\x8b\x08\x00':
        return data
    # Android boot image: use the verified parser, which returns the kernel.
    try:
        _, _, parts = unpack(data)
        return parts['kernel']
    except Exception:
        return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='boot image or bare shim Image')
    parser.add_argument('--adt', type=Path, required=True)
    parser.add_argument('--cmdline', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    image = bare_image(args.source.read_bytes())
    marker = b'CITRUSPL'
    hits = [i for i in range(len(image)) if image.startswith(marker, i)]
    if len(hits) != 1:
        raise SystemExit(f'expected exactly one CITRUSPL marker, found {len(hits)}')
    container = hits[0]
    length, = struct.unpack_from('<Q', image, container + 8)
    start = container + 16
    payload = image[start:start + length]
    if len(payload) != length or payload[:8] != b'SWEETXNU':
        raise SystemExit('truncated or invalid payload')
    version, nsegs = struct.unpack_from('<II', payload, 8)
    if version != 1 or not 0 < nsegs <= 64:
        raise SystemExit('unsupported payload header')
    virt, entry, old_adt_off, old_adt_size, kernel_end, phys, mem = struct.unpack_from('<7Q', payload, 0x10)
    old_cmdline = payload[0x48:0x48 + 608].split(b'\0')[0]
    if len(args.cmdline.encode()) >= 608:
        raise SystemExit('cmdline too long')
    segments = []
    for i in range(nsegs):
        vmaddr, vmsize, off, size = struct.unpack_from('<4Q', payload, HEADER + 32 * i)
        if off + size > len(payload):
            raise SystemExit(f'segment {i} outside payload')
        segments.append((vmaddr, vmsize, payload[off:off + size]))
    adt_blob = args.adt.read_bytes()
    if mkpayload.adt_dram(adt_blob) != (phys, mem):
        raise SystemExit('new ADT RAM bounds differ from the payload kernel layout')

    out = bytearray(HEADER + 32 * len(segments))
    table = []
    for vmaddr, vmsize, data in segments:
        off = len(out)
        out += data
        out += b'\0' * (-len(out) & 0xf)
        table.append((vmaddr, vmsize, off, len(data)))
    adt_off = len(out)
    out += adt_blob
    out += b'\0' * (-len(out) & 0xf)
    struct.pack_into('<8sII', out, 0, b'SWEETXNU', 1, len(segments))
    struct.pack_into('<7Q', out, 0x10, virt, entry, adt_off, len(adt_blob), kernel_end, phys, mem)
    cl = args.cmdline.encode()
    out[0x48:0x48 + len(cl)] = cl
    for i, row in enumerate(table):
        struct.pack_into('<4Q', out, HEADER + 32 * i, *row)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(out)
    print(f'source={args.source} sha256={sha(args.source)}')
    print(f'payload={args.output} sha256={sha(args.output)} bytes={len(out)}')
    print(f'segments={len(segments)} entry={entry:#x} virt={virt:#x} '
          f'phys={phys:#x} mem={mem:#x}')
    print(f'old_cmdline={old_cmdline.decode()}')
    print(f'new_cmdline={args.cmdline}')


if __name__ == '__main__':
    main()
