#!/usr/bin/env python3
"""Decode a flattened device tree to JSON without external dependencies."""
import argparse
import json
import pathlib
import struct


def decode(data):
    if len(data) < 40:
        raise ValueError('Truncated FDT header')
    magic, total, off, strings, _, version, _, _, strsize, size = struct.unpack_from('>10I', data)
    if magic != 0xd00dfeed or version < 17 or total > len(data):
        raise ValueError('Invalid or unsupported FDT header')
    end = off + size
    if end > total or strings + strsize > total:
        raise ValueError('FDT blocks exceed total size')
    names = data[strings:strings + strsize]
    nodes, stack = {}, []

    def read32():
        nonlocal off
        if off + 4 > end:
            raise ValueError('Truncated FDT structure')
        value = struct.unpack_from('>I', data, off)[0]
        off += 4
        return value

    while off < end:
        token = read32()
        if token == 1:
            stop = data.find(b'\0', off, end)
            if stop < 0:
                raise ValueError('Unterminated node name')
            stack.append(data[off:stop].decode())
            off = (stop + 4) & ~3
            nodes['/' + '/'.join(stack[1:])] = {}
        elif token == 2:
            if not stack:
                raise ValueError('Unbalanced FDT node')
            stack.pop()
        elif token == 3:
            length, index = read32(), read32()
            stop = names.find(b'\0', index)
            if not stack or stop < 0 or off + length > end:
                raise ValueError('Invalid FDT property')
            name = names[index:stop].decode()
            raw = data[off:off + length]
            off = (off + length + 3) & ~3
            if not raw:
                value = True
            elif raw.endswith(b'\0') and all(raw[:-1].split(b'\0')) and all(c in (0, 9, 10, 13) or 32 <= c < 127 for c in raw):
                value = raw[:-1].decode().split('\0')
            elif length % 4 == 0:
                value = [hex(x[0]) for x in struct.iter_unpack('>I', raw)]
            else:
                value = {'hex': raw.hex()}
            nodes['/' + '/'.join(stack[1:])][name] = value
        elif token == 4:
            continue
        elif token == 9:
            if stack:
                raise ValueError('Unclosed FDT nodes')
            return nodes
        else:
            raise ValueError(f'Unknown FDT token {token}')
    raise ValueError('Missing FDT end token')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dtb', type=pathlib.Path)
    args = parser.parse_args()
    print(json.dumps(decode(args.dtb.read_bytes()), indent=2))
