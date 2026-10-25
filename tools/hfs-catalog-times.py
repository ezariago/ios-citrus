#!/usr/bin/env python3
"""Report the newest catalog timestamps of an HFSX root, read-only.

Answers "how long did the last iOS boot keep writing to the filesystem?" from
the persistent on-device root instead of the (small, flaky) console log ring.

Reads via --image or directly over recovery ADB (--adb-cache NEW_DIR, fresh
cache per invocation). Never writes HFS structures.
"""
import argparse
import datetime
import importlib.util
import pathlib
import struct
import subprocess
import sys

from _hfslib import BS, LEAF_NODE, FILE_RECORD, FOLDER_RECORD, HFS

# tools/hfs-read-adb.py is not importable by name (hyphen): load it by path.
_reader_path = pathlib.Path(__file__).with_name('hfs-read-adb.py')
_spec = importlib.util.spec_from_file_location('sweet_hfs_read_adb', _reader_path)
_hfs_read = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_hfs_read)
AdbReader = _hfs_read.AdbReader
ReadOnlyHFS = _hfs_read.ReadOnlyHFS

HFS_EPOCH = 2082844800  # 1904-01-01 -> 1970-01-01


def hfs_date(value):
    if value == 0:
        return None
    return datetime.datetime.fromtimestamp(value - HFS_EPOCH, datetime.timezone.utc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--image', type=pathlib.Path)
    source.add_argument('--adb-cache', type=pathlib.Path)
    parser.add_argument('--top', type=int, default=25)
    parser.add_argument('--since', type=str, default=None,
                        help='ISO time; also list every entry newer than this')
    args = parser.parse_args()

    if args.adb_cache:
        devices = subprocess.check_output(['adb', 'devices'], text=True)
        if sum(line.endswith('\trecovery') for line in devices.splitlines()) != 1:
            raise RuntimeError('Exactly one ADB recovery device is required')
        reader = AdbReader(args.adb_cache)
    else:
        reader = args.image.open('rb')

    hfs = ReadOnlyHFS(reader)
    header = hfs.catalog_header()
    if header['nodeSize'] != BS:
        raise SystemExit('unexpected catalog node size')

    items = {}
    for node in range(header['totalNodes']):
        raw = hfs.read(hfs.node_offset(node), BS)
        f_link, b_link, kind, height, count = struct.unpack('>IIBBH', raw[0:12])
        if kind != LEAF_NODE or height != 1:
            continue
        offsets = [struct.unpack('>H', raw[BS - 2 * (i + 1):BS - 2 * i])[0]
                   for i in range(count + 1)]
        for i in range(count):
            record = raw[offsets[i]:offsets[i + 1]]
            key_length = struct.unpack('>H', record[0:2])[0]
            parent = struct.unpack('>I', record[2:6])[0]
            name_length = struct.unpack('>H', record[6:8])[0]
            name = record[8:8 + 2 * name_length].decode('utf-16-be', 'surrogatepass')
            data = 2 + key_length
            record_type = struct.unpack('>H', record[data:data + 2])[0]
            if record_type not in (FOLDER_RECORD, FILE_RECORD):
                continue
            cnid = struct.unpack('>I', record[data + 8:data + 12])[0]
            created, modified, attrs = struct.unpack('>III', record[data + 12:data + 24])
            items[cnid] = {
                'parent': parent, 'name': name, 'cnid': cnid,
                'kind': 'folder' if record_type == FOLDER_RECORD else 'file',
                'created': created, 'modified': modified, 'attrs': attrs,
            }

    def path_of(cnid):
        parts = []
        seen = 0
        while cnid and cnid in items and seen < 64:
            item = items[cnid]
            parts.append(item['name'])
            cnid = item['parent']
            seen += 1
        return '/' + '/'.join(reversed(parts))

    newest = sorted(items.values(), key=lambda it: max(it['created'], it['modified'],
                                                       it['attrs']), reverse=True)
    print(f'{len(items)} catalog entries, {header["totalNodes"]} nodes')
    for item in newest[:args.top]:
        when = hfs_date(max(item['created'], item['modified'], item['attrs']))
        print(f'{when}  {item["kind"]:6} c {hfs_date(item["created"])} '
              f'm {hfs_date(item["modified"])} a {hfs_date(item["attrs"])}  '
              f'{path_of(item["cnid"])}')

    if args.since:
        since = datetime.datetime.fromisoformat(args.since)
        if since.tzinfo is None:
            since = since.replace(tzinfo=datetime.timezone.utc)
        cutoff = int(since.timestamp()) + HFS_EPOCH
        newer = [it for it in items.values()
                 if max(it['created'], it['modified'], it['attrs']) > cutoff]
        print(f'\n{len(newer)} entries newer than {since.isoformat()}')
        for item in sorted(newer, key=lambda it: max(it['created'], it['modified'],
                                                     it['attrs'])):
            when = hfs_date(max(item['created'], item['modified'], item['attrs']))
            print(f'{when}  {item["kind"]:6}  {path_of(item["cnid"])}')


if __name__ == '__main__':
    sys.exit(main())
