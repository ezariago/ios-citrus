#!/usr/bin/env python3
"""Inspect/repack Citrus Android boot v2 using a locally backed-up image."""
import argparse
import hashlib
import json
import pathlib
import struct


def align(value, page):
    return (value + page - 1) & ~(page - 1)


def unpack(data):
    if len(data) < 1660 or data[:8] != b'ANDROID!':
        raise ValueError('Not an Android boot image')
    page, version = struct.unpack_from('<II', data, 36)
    if version != 2 or page not in (2048, 4096, 8192, 16384):
        raise ValueError('Only legacy boot header v2 is supported')
    kernel, ramdisk, second = (struct.unpack_from('<I', data, x)[0] for x in (8, 16, 24))
    recovery_size, recovery_offset, header_size, dtb_size = struct.unpack_from('<IQII', data, 1632)
    if header_size != 1660:
        raise ValueError('Unexpected v2 header size')
    sizes = [kernel, ramdisk, second]
    components = {}
    offset = page
    for name, size in zip(('kernel', 'ramdisk', 'second'), sizes):
        if offset + size > len(data):
            raise ValueError(f'Truncated {name}')
        components[name] = data[offset:offset + size]
        offset += align(size, page)
    if recovery_size:
        if recovery_offset != offset:
            raise ValueError('Nonstandard recovery DTBO offset')
        if offset + recovery_size > len(data):
            raise ValueError('Truncated recovery DTBO')
        components['recovery_dtbo'] = data[offset:offset + recovery_size]
        offset += align(recovery_size, page)
    else:
        components['recovery_dtbo'] = b''
    if offset + dtb_size > len(data):
        raise ValueError('Truncated DTB')
    components['dtb'] = data[offset:offset + dtb_size]
    return page, data[:page], components


def repack(template, kernel):
    page, old_header, parts = unpack(template)
    if len(kernel) < 64 or kernel[56:60] != b'ARM\x64':
        raise ValueError('Replacement is not an ARM64 Linux Image')
    if struct.unpack_from('<Q', kernel, 16)[0] != len(kernel):
        raise ValueError('ARM64 Image size must match padded file size')
    parts['kernel'] = kernel
    header = bytearray(old_header)
    struct.pack_into('<I', header, 8, len(kernel))
    offset = page + sum(align(len(parts[x]), page) for x in ('kernel', 'ramdisk', 'second'))
    struct.pack_into('<Q', header, 1636, offset if parts['recovery_dtbo'] else 0)
    # Legacy boot image SHA-1: component bytes followed by their u32 size,
    # including v1 recovery DTBO and v2 DTB, as in AOSP mkbootimg.
    digest = hashlib.sha1()
    for name in ('kernel', 'ramdisk', 'second', 'recovery_dtbo', 'dtb'):
        digest.update(parts[name])
        digest.update(struct.pack('<I', len(parts[name])))
    header[576:608] = digest.digest() + bytes(12)
    output = bytes(header)
    for name in ('kernel', 'ramdisk', 'second', 'recovery_dtbo', 'dtb'):
        output += parts[name] + bytes(align(len(parts[name]), page) - len(parts[name]))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('template', type=pathlib.Path)
    parser.add_argument('--kernel', type=pathlib.Path)
    parser.add_argument('--output', type=pathlib.Path)
    args = parser.parse_args()
    if bool(args.kernel) != bool(args.output):
        parser.error('--kernel and --output must be supplied together')
    template = args.template.read_bytes()
    if args.kernel:
        data = repack(template, args.kernel.read_bytes())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(data)
    else:
        data = template
    page, header, parts = unpack(data)
    print(json.dumps({'header_version': 2, 'page_size': page,
                      'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                      'components': {k: {'bytes': len(v), 'sha256': hashlib.sha256(v).hexdigest()}
                                     for k, v in parts.items()}}, indent=2))


if __name__ == '__main__':
    main()
