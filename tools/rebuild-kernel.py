#!/usr/bin/env python3
"""Recompile Citrus changes against the matching published Topaz object archive.

Prerequisites are the downloaded/extracted artifacts under out/upstream-artifacts
and the logging dependency compiled there. This avoids regenerating IIG output
with an incompatible Xcode version. It never accesses the phone.
"""
import json
import pathlib
import shlex
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
ART = ROOT / 'out/upstream-artifacts'
TREE = ART / 'buildtree'
OUT = ROOT / 'out/citrus-kernel'
SOURCE = TREE / 'xnu'


def compile_object(component, target):
    work = TREE / 'build/xnu.obj/DEVELOPMENT_ARM64_SWEET' / component / 'DEVELOPMENT'
    command = ['make', '-n', '-o', 'assym.s', '-o', '.CFLAGS', '-o', '.SFLAGS', target,
               'SRCROOT=' + str(SOURCE), 'SOURCE_DIR=' + str(SOURCE),
               'SOURCE=' + str(SOURCE / component) + '/',
               'OBJROOT=' + str(TREE / 'build/xnu.obj'),
               'CURRENT_ARCH_CONFIG=ARM64', 'CURRENT_ARCH=arm64',
               'CURRENT_MACHINE_CONFIG=SWEET', 'CURRENT_KERNEL_CONFIG=DEVELOPMENT',
               'FAKEROOT_DIR=' + str(TREE / 'fakeroot'), 'ARCH_CONFIGS=ARM64',
               'MACHINE_CONFIGS=SWEET', 'KERNEL_CONFIGS=DEVELOPMENT']
    result = subprocess.run(command, cwd=work, capture_output=True, text=True)
    (OUT / (target + '.make.log')).write_text(result.stdout + result.stderr)
    commands = [line for line in result.stdout.splitlines()
                if ('/clang ' in line or '/clang++ ' in line) and ' -c ' in line
                and 'replacecontents' not in line]
    if result.returncode or not commands:
        raise RuntimeError(f'Cannot obtain compile command for {target}; see make log')
    command = shlex.split(commands[-1])
    command = ['-mmacosx-version-min=14.0' if x.startswith('-mmacosx-version-min=') else x
               for x in command]
    command += ['-fno-lto', '-Wno-error', '-w']
    for part in ['osfmk', 'bsd', 'libkern', 'pexpert', 'iokit', 'libsa', 'osfmk/libsa']:
        command += ['-I' + str(SOURCE / part)]
    command += ['-o', str(OUT / target)]
    (OUT / (target + '.command.json')).write_text(json.dumps(command, indent=2) + '\n')
    result = subprocess.run(command, cwd=work, capture_output=True, text=True)
    (OUT / (target + '.compile.log')).write_text(result.stdout + result.stderr)
    if result.returncode:
        print('\n'.join(x for x in result.stderr.splitlines() if 'error:' in x))
        raise RuntimeError(f'Compilation failed for {target}; see compile log')
    print(f'Compiled {target}', flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # The touch probe embeds the vendor FT8719 boot image; regenerate it from
    # devices/citrus-ft8719-fw.bin so a stale header can never be linked.
    subprocess.run(['python3', str(ROOT / 'tools/embed-touch-fw.py')], check=True)
    targets = [('pexpert', 'pe_fiq.o'),
               ('osfmk', 'sweet_early.o'), ('osfmk', 'start.o'),
               ('osfmk', 'arm_vm_init.o'), ('iokit', 'SweetBattery.cpo'),
               ('osfmk', 'serial_console.o'), ('iokit', 'SweetFramebuffer.cpo'),
               ('osfmk', 'exception.o'), ('osfmk', 'rtclock.o'), ('osfmk', 'video_console.o'), ('bsd', 'sweet_sample.o'),
               ('osfmk', 'cpu.o'),
               ('bsd', 'sweet_ufs.o'), ('bsd', 'sweet_usb.o'), ('bsd', 'sweet_touch.o')]
    for component, target in targets:
        compile_object(component, target)
    link = ART / 'xnu-kernel/kernel.development.sweet.link'
    archive = OUT / 'citrus.a'
    shutil.copyfile(link / 'kernel.development.sweet.a', archive)
    subprocess.run(['/opt/homebrew/opt/llvm/bin/llvm-ar', 'r', str(archive),
                    *[str(OUT / target) for _, target in targets]], check=True)
    args = shlex.split((link / 'kernel.development.sweet.linkarguments').read_text())
    # The final rename is for static kernel collections, not this raw kernel.
    args = [x for x in args if not x.startswith('-L/Users/runner/') and x not in
            ['-lfirehose_kernel', '-lcc_kext', '-Wl,-rename_segment,__LASTDATA_CONST,__LAST']]
    runtime = subprocess.check_output(['xcrun', 'clang', '--print-file-name=libclang_rt.cc_kext.a'], text=True).strip()
    args += [runtime, str(ART / 'firehose_buffer.o'), '-Wl,-force_load,' + str(archive),
             '-Wl,-exported_symbols_list,' + str(link / 'kernel.development.sweet.exp'),
             '-Wl,-alias_list,' + str(link / 'kernel.development.sweet.alias.exp'),
             '-o', str(OUT / 'kernel.development.citrus')]
    result = subprocess.run(['xcrun', 'clang', *args], capture_output=True, text=True)
    (OUT / 'link.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        print(result.stderr[-3000:])
        raise RuntimeError('Kernel link failed')
    print(f'Linked {OUT / "kernel.development.citrus"}')


if __name__ == '__main__':
    main()
