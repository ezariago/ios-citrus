#!/usr/bin/env python3
"""Compile the real GPU/touch firmware objects locally and relink a 4K XNU kernel.

The CI build tree and archive contain empty firmware placeholders.  This tool
compiles only the firmware-containing translation units against the generated
4K headers, replaces those two archive members, and relinks with the local
toolchain.  Firmware bytes never leave this checkout.
"""
import argparse, glob, hashlib, json, os, re, shutil, struct, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIREHOSE = Path('/Users/ezariago/Projects/ios-citrus-copy/out/upstream-artifacts/firehose_buffer.o')


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def run(cmd, cwd, log):
    r = subprocess.run([str(x) for x in cmd], cwd=cwd, capture_output=True, text=True)
    log.write_text(log.read_text() + '$ ' + ' '.join(map(str, cmd)) + '\n' + r.stdout + r.stderr + '\n')
    if r.returncode:
        raise SystemExit(f'command failed ({r.returncode}); see {log}')
    return r


def macho_segments(data):
    if struct.unpack_from('<I', data, 0)[0] != 0xfeedfacf:
        raise SystemExit('not a 64-bit Mach-O')
    ncmds = struct.unpack_from('<I', data, 16)[0]
    off, segs = 32, []
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<II', data, off)
        if cmd == 0x19:
            name = data[off + 8:off + 24].split(b'\0')[0].decode()
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from('<4Q', data, off + 24)
            segs.append((name, vmaddr, vmsize, fileoff, filesize))
        off += size
    return segs


def symbol_addresses(nm_output):
    syms = {}
    for line in nm_output.splitlines():
        m = re.search(r'^([0-9a-f]+) .*? (_[A-Za-z0-9_.]+)$', line.strip())
        if m:
            syms[m.group(2)] = int(m.group(1), 16)
    return syms


def read_symbol(kernel, segs, addr, size):
    for _, vmaddr, vmsize, fileoff, filesize in segs:
        if vmaddr <= addr and addr + size <= vmaddr + min(vmsize, filesize):
            pos = fileoff + addr - vmaddr
            return kernel[pos:pos + size]
    raise SystemExit(f'symbol at {addr:#x} is not backed by a file range')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree', required=True, type=Path, help='extracted citrus-4k-buildtree (contains xnu/ and build/xnu.obj)')
    ap.add_argument('--link-dir', required=True, type=Path, help='downloaded kernel.development.sweet.link directory')
    ap.add_argument('--firmware-dir', type=Path, default=ROOT / 'devices/citrus-gpu-fw')
    ap.add_argument('--touch-firmware', type=Path, default=ROOT / 'devices/citrus-ft8719-fw.bin')
    ap.add_argument('--firehose-object', type=Path, default=DEFAULT_FIREHOSE)
    ap.add_argument('--output-dir', type=Path, default=ROOT / 'out/citrus-8core/firmware-relink')
    args = ap.parse_args()
    tree, link, out = args.tree.resolve(), args.link_dir.resolve(), args.output_dir.resolve()
    obj = out / 'obj'
    src = out / 'src'
    for d in (obj, src / 'iokit/Kernel/arm', src / 'bsd/dev', out / 'link'):
        d.mkdir(parents=True, exist_ok=True)
    log = out / 'relink.log'
    log.write_text('')

    # Reuse the exact generator that embeds firmware for the 16K build.
    import importlib.util
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    bcg = load('bcg', ROOT / 'tools/build-citrus-gpu.py')
    etf = load('etf', ROOT / 'tools/embed-touch-fw.py')
    fw_records = bcg.firmware(args.firmware_dir.resolve(), src)
    touch_header = etf.build(args.touch_firmware.resolve())
    (src / 'bsd/dev/sweet_touch_fw.h').write_text(touch_header)
    touch_len = int(re.search(r'citrus_ft8719_fw_len = (\d+)u', touch_header).group(1))

    flags = (tree / 'build/xnu.obj/DEVELOPMENT_ARM64_SWEET/.CFLAGS').read_text().replace('\x00', '').split()
    clang = subprocess.run(['xcrun', '-f', 'clang'], capture_output=True, text=True, check=True).stdout.strip()
    flags[0] = clang
    cflags = []
    for f in flags:
        f = f.replace('/Users/runner/work/citrus-xnu-4k-runner-probe/citrus-xnu-4k-runner-probe/dxb', str(tree))
        if f.startswith('/Applications/Xcode_15.4.app'):
            continue
        cflags.append(f)
    work = tree / 'build/xnu.obj/DEVELOPMENT_ARM64_SWEET'
    shutil.copyfile(tree / 'xnu/bsd/dev/sweet_touch.c', src / 'bsd/dev/sweet_touch.c')
    jobs = [
        (src / 'iokit/Kernel/arm/TopazAdrenoFw.cpp', obj / 'TopazAdrenoFw.cpo', work / 'iokit/DEVELOPMENT'),
        (src / 'bsd/dev/sweet_touch.c', obj / 'sweet_touch.o', work / 'bsd/DEVELOPMENT'),
    ]
    for source, target, cwd in jobs:
        run([clang, *cflags, '-c', source, '-o', target], cwd, log)

    archive = out / 'link/kernel.development.sweet.a'
    shutil.copyfile(link / 'kernel.development.sweet.a', archive)
    run(['ar', 'r', archive, obj / 'TopazAdrenoFw.cpo', obj / 'sweet_touch.o'], out / 'link', log)
    for name in ('kernel.development.sweet.exp', 'kernel.development.sweet.alias.exp',
                 'kernel.development.sweet.linkarguments'):
        shutil.copyfile(link / name, out / 'link' / name)

    args_list = (out / 'link/kernel.development.sweet.linkarguments').read_text().replace('\x00', '').split()
    link_args = [a for a in args_list if not (a.startswith('-L/Users/runner') or a in ('-lfirehose_kernel', '-lcc_kext'))]
    cc_kext = sorted(glob.glob('/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib/clang/*/lib/darwin/libclang_rt.cc_kext.a'))[-1]
    kernel = out / 'kernel.development.sweet.fw'
    run([clang, *link_args, cc_kext, args.firehose_object.resolve(),
         '-Wl,-force_load,' + str(archive),
         '-Wl,-exported_symbols_list,' + str(out / 'link/kernel.development.sweet.exp'),
         '-Wl,-alias_list,' + str(out / 'link/kernel.development.sweet.alias.exp'),
         '-Wl,-read_only_relocs,suppress', '-o', kernel], out / 'link', log)

    data = bytearray(kernel.read_bytes())
    # ld assigns a random LC_UUID; pin it from the inputs so reruns are reproducible.
    digest_input = (sha(obj / 'TopazAdrenoFw.cpo') + sha(obj / 'sweet_touch.o') +
                     ''.join(sorted(r['sha256'] for r in fw_records.values())) +
                     hashlib.sha256(args.touch_firmware.read_bytes()[:touch_len]).hexdigest())
    digest = hashlib.sha256(digest_input.encode()).digest()
    ncmds = struct.unpack_from('<I', data, 16)[0]
    off = 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<II', data, off)
        if cmd == 0x1b:
            data[off + 8:off + 24] = digest[:16]
            break
        off += size
    kernel.write_bytes(data)
    data = bytes(data)
    segs = macho_segments(data)
    syms = symbol_addresses(subprocess.run(['nm', '-m', str(kernel)], capture_output=True, text=True, check=True).stdout)
    checks = {}
    for key, rec in fw_records.items():
        sym = '_topaz_fw_' + {'a610_zap.mdt': 'zap_mdt', 'a610_zap.b02': 'zap_b02', 'a630_sqe.fw': 'sqe_fw'}[key]
        size = struct.unpack('<Q', read_symbol(data, segs, syms[sym + '_size'], 8))[0]
        blob = read_symbol(data, segs, syms[sym], size)
        checks[sym] = {'size': size, 'sha256': hashlib.sha256(blob).hexdigest(),
                       'expected': rec['sha256'], 'ok': size == rec['bytes'] and hashlib.sha256(blob).hexdigest() == rec['sha256']}
    tsize = touch_len  # the static length is constant-folded, only the blob has a symbol
    tblob = read_symbol(data, segs, syms['_citrus_ft8719_fw'], tsize)
    checks['citrus_ft8719_fw'] = {'size': tsize, 'sha256': hashlib.sha256(tblob).hexdigest(),
                                  'expected': hashlib.sha256(args.touch_firmware.read_bytes()[:touch_len]).hexdigest(),
                                  'ok': tsize == touch_len}
    if not all(c['ok'] for c in checks.values()):
        raise SystemExit('firmware verification failed: ' + json.dumps(checks, indent=2))
    manifest = {
        'kernel': str(kernel), 'kernel_sha256': sha(kernel), 'kernel_bytes': len(data),
        'ci_tree': str(tree), 'archive_sha256': sha(archive),
        'firmware': fw_records, 'touch_firmware': {'bytes': touch_len, 'sha256': sha(args.touch_firmware)},
        'objects': {'TopazAdrenoFw.cpo': sha(obj / 'TopazAdrenoFw.cpo'), 'sweet_touch.o': sha(obj / 'sweet_touch.o')},
        'checks': checks, 'segments': [s[0] for s in segs],
        'limits': ['linked with local Xcode 27 ld, not the CI Xcode 15.4 ld',
                   'local ld warns/merges __LASTDATA_CONST and omits __CTF; shim-test before boot',
                   'no hardware test of this firmware-containing kernel'],
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'kernel': str(kernel), 'sha256': manifest['kernel_sha256'], 'checks': checks}, indent=2))


if __name__ == '__main__':
    main()
