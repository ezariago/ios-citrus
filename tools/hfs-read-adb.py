#!/usr/bin/env python3
"""Read HFS catalog/files from recovery without copying the whole root image.

All device commands are reads. Each remote invocation requires a new cache
directory, so blocks from different boots cannot be mixed. --image reads a
local image instead. Only small ordinary data forks (up to eight extents) can
be extracted; this tool never repairs or writes HFS structures.
"""
import argparse
import pathlib
import struct
import subprocess

from _hfslib import HFS, BS, read_records, resolve


class AdbReader:
    CHUNK = 1024 * 1024

    def __init__(self, cache):
        self.cache = cache
        cache.mkdir(parents=True, exist_ok=False)
        self.position = 0
        self.blocks = {}

    def seek(self, offset):
        if not 0 <= offset < 16 * 1024**3:
            raise ValueError('Read outside the 16 GiB root image')
        self.position = offset

    def read(self, size):
        if size < 0 or self.position + size > 16 * 1024**3:
            raise ValueError('Read outside the 16 GiB root image')
        result = bytearray()
        while len(result) < size:
            index, within = divmod(self.position, self.CHUNK)
            if index not in self.blocks:
                command = f'dd if=/dev/block/by-name/userdata bs={self.CHUNK} skip={index} count=1 2>/dev/null'
                block = subprocess.check_output(['adb', 'exec-out', command])
                if len(block) != self.CHUNK:
                    raise RuntimeError(f'Short ADB read for chunk {index}: {len(block)}')
                (self.cache / f'{index:05d}.bin').write_bytes(block)
                self.blocks[index] = block
            take = min(size - len(result), self.CHUNK - within)
            result += self.blocks[index][within:within + take]
            self.position += take
        return bytes(result)


class ReadOnlyHFS(HFS):
    def __init__(self, reader):
        self.f = reader
        vh = self.read(1024, 512)
        if vh[:2] not in (b'H+', b'HX'):
            raise ValueError('Not HFS+/HFSX')
        self.block_size = struct.unpack_from('>I', vh, 40)[0]
        if self.block_size != BS:
            raise ValueError('Unsupported block size')
        self.total_blocks = struct.unpack_from('>I', vh, 44)[0]
        self.file_count, self.folder_count = struct.unpack_from('>II', vh, 32)
        self.catalog = self._fork(vh, 272)
        self.extents = self._fork(vh, 192)
        self.overflow = self._overflow_extents()
        self.segments = self._segments()

    def write(self, *args):
        raise RuntimeError('Read-only HFS reader')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--image', type=pathlib.Path)
    source.add_argument('--adb-cache', type=pathlib.Path)
    parser.add_argument('action', choices=['list', 'extract'])
    parser.add_argument('path')
    parser.add_argument('--output', type=pathlib.Path)
    args = parser.parse_args()
    if args.action == 'extract' and args.output is None:
        parser.error('extract needs --output')
    if args.adb_cache:
        devices = subprocess.check_output(['adb', 'devices'], text=True)
        if sum(line.endswith('\trecovery') for line in devices.splitlines()) != 1:
            raise RuntimeError('Exactly one ADB recovery device is required')
        reader = AdbReader(args.adb_cache)
    else:
        reader = args.image.open('rb')
    hfs = ReadOnlyHFS(reader)
    items, _ = read_records(hfs)
    cnid = resolve(items, args.path)
    if cnid is None:
        raise SystemExit(f'No such HFS path: {args.path}')
    if args.action == 'list':
        by_parent = {}
        for ident, item in items.items():
            if ident != item['parent']:
                by_parent.setdefault(item['parent'], []).append((item['name'], ident, item))
        def walk(parent, prefix):
            for name, ident, item in sorted(by_parent.get(parent, [])):
                path = prefix.rstrip('/') + '/' + name
                print(f"{item['kind']} {item['uid']}:{item['gid']} {path}", flush=True)
                if item['kind'] == 'folder':
                    walk(ident, path)
        walk(cnid, args.path)
    else:
        item = items[cnid]
        if item['kind'] != 'file':
            raise SystemExit('Only ordinary files can be extracted')
        mode = struct.unpack('>H', hfs.read(item['owner_at'] + 10, 2))[0]
        if mode & 0xf000 != 0x8000 or hfs.read(item['owner_at'] + 16, 8) == b'hlnkhfs+':
            raise SystemExit('Symlinks, special files and HFS hard links are unsupported')
        # owner_at = catalog record data + 32; data fork starts at +88.
        fork = hfs._fork(hfs.read(item['owner_at'] + 56, 80), 0)
        if fork['logical'] > 16 * 1024**2 or sum(c for _, c in fork['extents']) < fork['blocks']:
            raise SystemExit('File too large or needs overflow extents; extraction unsupported')
        data = hfs._read_extents(fork['extents'], 0, fork['logical'])
        args.output.write_bytes(data)
        print(f'Extracted {len(data)} bytes to {args.output}')


if __name__ == '__main__':
    main()
