#!/usr/bin/env python3
"""Check recovered EAGL dispatch offsets against an offline arm64 dyld cache.

Reads cache files directly, without extracting or modifying the iOS volume.
This checks static dispatch offsets, not prototypes, Objective-C hooks or runtime.
Layout reference: Apple's dyld include/mach-o/dyld_cache_format.h.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import struct

ROOT = Path(__file__).resolve().parents[1]


class Cache:
    def __init__(self, path):
        self.path = path
        self.maps = []
        self.reads = {}
        for file in sorted(path.parent.glob(path.name + '*')):
            if file.suffix == '.symbols':
                continue
            with file.open('rb') as stream:
                header = stream.read(512)
                if not header.startswith(b'dyld_'):
                    continue
                offset, count = struct.unpack_from('<II', header, 16)
                if count > 64 or offset + count * 32 > file.stat().st_size:
                    raise ValueError('invalid cache mappings: ' + str(file))
                stream.seek(offset)
                for _ in range(count):
                    va, size, position, _, _ = struct.unpack('<QQQII', stream.read(32))
                    self.maps.append((va, va + size, position, file))
        self.header = path.open('rb').read(512)
        if b'arm64' not in self.header[:16] or b'arm64e' in self.header[:16]:
            raise ValueError('requires the non-arm64e cache used by iPhone10,3')

    def read(self, va, size):
        for start, end, offset, file in self.maps:
            if start <= va and va + size <= end:
                with file.open('rb') as stream:
                    position = offset + va - start
                    stream.seek(position)
                    data = stream.read(size)
                if len(data) != size:
                    raise ValueError('short cache read')
                self.reads[(str(file), position, size)] = hashlib.sha256(data).hexdigest()
                return data
        raise ValueError('unmapped cache VA ' + hex(va))

    def image(self, suffix):
        offset, count = struct.unpack_from('<II', self.header, 448)
        if not count or count > 100000:
            raise ValueError('unsupported cache image table')
        with self.path.open('rb') as stream:
            stream.seek(offset)
            records = stream.read(count * 32)
            for i in range(count):
                va, _, _, pathoff, _ = struct.unpack_from('<QQQII', records, i * 32)
                stream.seek(pathoff)
                name = stream.read(1024).split(b'\0')[0].decode()
                if name.endswith(suffix):
                    return va, name
        raise ValueError('image not found: ' + suffix)


def uleb(data, at):
    value = shift = 0
    while shift < 64:
        byte = data[at]
        at += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, at
        shift += 7
    raise ValueError('invalid ULEB')


def exports(cache, base):
    header = cache.read(base, 32)
    if struct.unpack_from('<I', header)[0] != 0xfeedfacf:
        raise ValueError('not a 64-bit Mach-O image')
    count, size = struct.unpack_from('<II', header, 16)
    commands = cache.read(base + 32, size)
    at = 0
    export_offset = export_size = 0
    link_va = link_offset = None
    for _ in range(count):
        kind, length = struct.unpack_from('<II', commands, at)
        if length < 8 or at + length > size:
            raise ValueError('invalid load command')
        if kind == 0x19 and commands[at + 8:at + 24].split(b'\0')[0] == b'__LINKEDIT':
            link_va, _, link_offset = struct.unpack_from('<QQQ', commands, at + 24)
        if kind == 0x80000022:
            export_offset, export_size = struct.unpack_from('<II', commands, at + 40)
        if kind == 0x80000033:
            export_offset, export_size = struct.unpack_from('<II', commands, at + 8)
        at += length
    if link_va is None or not export_size:
        raise ValueError('no export trie')
    trie = cache.read(link_va + export_offset - link_offset, export_size)
    result = {}

    def walk(node, name, seen):
        if node in seen or len(seen) > 1024:
            raise ValueError('cyclic or excessive export trie')
        terminal, cursor = uleb(trie, node)
        child = cursor + terminal
        if terminal:
            flags, value_at = uleb(trie, cursor)
            if not flags & 8:  # re-export
                address, _ = uleb(trie, value_at)
                result[name] = base + address
        cursor = child + 1
        for _ in range(trie[child]):
            end = trie.index(0, cursor)
            edge = trie[cursor:end].decode()
            next_node, cursor = uleb(trie, end + 1)
            walk(next_node, name + edge, seen | {node})
    walk(0, '', set())
    return result


def dispatch_slot(cache, symbols, name):
    address = symbols.get('_' + name)
    if not address:
        return None, 'not exported'
    end = min((x for x in symbols.values() if x > address), default=address + 512)
    data = cache.read(address, min(end - address, 512))
    loads, contexts = {}, []
    for i in range(0, len(data) - 3, 4):
        word = struct.unpack_from('<I', data, i)[0]
        if word & 0xffc00000 == 0xf9400000:  # LDR Xt, [Xn, #imm12*8]
            target, parent, offset = word & 31, (word >> 5) & 31, ((word >> 10) & 4095) * 8
            loads[target] = (parent, offset)
            if offset == 0x20:
                contexts.append((i, parent, target))
        if word & 0xfffffc1f in (0xd61f0000, 0xd63f0000):  # BR/BLR Xn
            target = loads.get((word >> 5) & 31)
            # The public GL wrapper's dispatch area starts with context at +0x20.
            # EAGL's macro table starts with that context at offset 0.
            if target and target[1] > 0x20 and any(c[1] == target[0] for c in contexts):
                return target[1] - 0x20, hex(address)
            return None, 'unrecognized indirect branch'
    return None, 'no recognized dispatch'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cache', type=Path)
    parser.add_argument('--slots', type=Path, default=ROOT / 'userland/gpu/reference/eagl_slots-ios16.5.txt')
    parser.add_argument('--output', type=Path, default=ROOT / 'out/citrus-eagl/dispatch-check.json')
    args = parser.parse_args()
    cache = Cache(args.cache.resolve())
    base, image = cache.image('/OpenGLES.framework/OpenGLES')
    symbols = exports(cache, base)
    records, counts = [], {}
    for line in args.slots.read_text().splitlines():
        parts = line.split('#')[0].split()
        if not parts:
            continue
        expected = int(parts[0], 16)
        for name in parts[2:]:
            actual, detail = dispatch_slot(cache, symbols, name)
            status = 'match' if actual == expected else 'mismatch' if actual is not None else 'unknown'
            counts[status] = counts.get(status, 0) + 1
            records.append({'name': name, 'expected': hex(expected), 'actual': hex(actual) if actual is not None else None,
                            'status': status, 'detail': detail})
    report = {'method': 'offline Python cache parsing and ARM64 wrapper decoding (not REA Evidence)',
              'cache': str(cache.path), 'cache_uuid': cache.header[88:104].hex(),
              'image': image, 'base': hex(base), 'runtime_abi_verified': False,
              'slots_sha256': hashlib.sha256(args.slots.read_bytes()).hexdigest(),
              'static_offsets_all_match': counts.get('match', 0) == len(records) and bool(records),
              'limitations': ['Checks conventional LDR/BR dispatch offsets; does not establish function prototypes, '
                              'Objective-C hook behavior, CoreAnimation compatibility or hardware rendering.'],
              'counts': counts, 'records': records,
              'byte_ranges': [{'file': f, 'offset': off, 'size': size, 'sha256': digest}
                              for (f, off, size), digest in cache.reads.items()]}
    version = cache.path.parents[2] / 'CoreServices/SystemVersion.plist'
    if version.exists():
        system = plistlib.loads(version.read_bytes())
        report['system_build'] = system.get('ProductBuildVersion')
        report['system_version'] = system.get('ProductVersion')
        report['system_version_plist_sha256'] = hashlib.sha256(version.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(counts), '->', args.output)
    if not report['static_offsets_all_match']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
