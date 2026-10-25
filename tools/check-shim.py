#!/usr/bin/env python3
"""Compile the pinned Topaz shim to ARM64 ELF objects on macOS; no phone needed."""
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'upstream/ios-topaz/shim'
OUTPUT = ROOT / 'out/shim-objects'
OUTPUT.mkdir(parents=True, exist_ok=True)
for name in ('start.S', 'shim.c', 'console.c', 'mmu.c', 'fdt.c', 'loader.c', 'ufs.c'):
    subprocess.run([
        'clang', '--target=aarch64-none-elf', '-mcpu=cortex-a53', '-O2',
        '-ffreestanding', '-nostdlib', '-fno-pic', '-mgeneral-regs-only',
        '-mstrict-align', '-fno-stack-protector', '-Wall', '-Wextra',
        '-c', str(SOURCE / name), '-o', str(OUTPUT / (pathlib.Path(name).stem + '.o')),
    ], check=True)
    print(f'Compiled {name}')
print('Compilation only: these objects retain Topaz hardware settings and are not a Citrus boot image.')
