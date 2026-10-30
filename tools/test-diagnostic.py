#!/usr/bin/env python3
"""Execute the ARM64 shim with synthetic MMIO/CPU registers using Unicorn.

This checks relocation, framebuffer bounds and rejection; it does not emulate
Qualcomm hardware or establish that the physical phone will boot.
"""
import pathlib
import re
import struct
import subprocess
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn import arm64_const as registers

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'out/citrus-diagnostic'
IMAGE = (OUT / 'Image').read_bytes()
DTB = (ROOT / 'device-dumps/20261025-141423-923416/live.dtb').read_bytes()
DISASSEMBLY = subprocess.check_output([
    '/opt/homebrew/opt/llvm/bin/llvm-objdump', '-d', str(OUT / 'shim.elf')], text=True)
HOOKS = []
for line in DISASSEMBLY.splitlines():
    m = re.match(r'\s*([0-9a-f]+):\s+[0-9a-f]+\s+(mrs|smc|msr)\s+(.*)', line)
    if m and (m[2] != 'msr' or m[3].startswith('ICC_')):
        HOOKS.append((int(m[1], 16), m[2], m[3]))


def run(base, valid, loader=False):
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.mem_map(base, (len(IMAGE) + 4095) & ~4095)
    cpu.mem_write(base, IMAGE)
    cpu.mem_map(0x47000000, 0x100000)
    cpu.mem_write(0x47000000, DTB)
    cpu.reg_write(registers.UC_ARM64_REG_X0, 0x47000000)
    cpu.mem_map(0x05e00000, 0x30000)
    cpu.mem_map(0x0c125000, 0x1000)
    cpu.mem_map(0x0440b000, 0x1000)
    entered = [False]
    if loader:
        cpu.mem_map(0x80000000, 0x4000000)
        cpu.mem_map(0x0f200000, 0x200000)
        # Synthetic GICv3 redistributor frames for both clusters. typer[63:32]
        # is Aff1:Aff0; the last frame carries GICR_TYPER.Last.
        for index, affinity in enumerate((0, 1, 2, 3, 0x100, 0x101, 0x102, 0x103)):
            typer = (affinity << 32) | (16 if index == 7 else 0)
            cpu.mem_write(0x0f300008 + index * 0x20000, struct.pack('<Q', typer))
        symbols = subprocess.check_output(['/opt/homebrew/opt/llvm/bin/llvm-nm', '-n', str(OUT / 'shim.elf')], text=True)
        boundary = int(next(line.split()[0] for line in symbols.splitlines() if line.endswith(' _end')), 16)
        assert IMAGE[boundary:boundary+8] == b'CITRUSPL'
        payload = boundary + 16
        virt, entry, adt_offset, adt_size, kernel_end, phys, memory_size = struct.unpack_from('<7Q', IMAGE, payload + 16)
        entry_pa = phys + entry - virt
        expected_args = (phys + kernel_end - virt + adt_size + 0x3fff) & ~0x3fff

        def kernel_entry(uc, address, size, unused):
            assert uc.reg_read(registers.UC_ARM64_REG_X0) == expected_args
            boot = bytes(uc.mem_read(expected_args, 736))
            assert struct.unpack_from('<HH', boot) == (2, 2)
            assert struct.unpack_from('<3Q', boot, 8) == (virt, phys, memory_size)
            assert struct.unpack_from('<6Q', boot, 40) == (0x5c000000, 1, 4320, 1080, 2340, 32)
            assert bytes(uc.mem_read(phys + 0x1004000, 4)) == b'\xcf\xfa\xed\xfe'
            entered[0] = True
            uc.emu_stop()

        cpu.hook_add(UC_HOOK_CODE, kernel_entry, begin=entry_pa, end=entry_pa)
    cpu.mem_map(0x5c000000, 0xf00000)
    pitch = 4352
    for offset, value in {
        0: (2340 << 16) | 1080, 0x0c: (2340 << 16) | 1080,
        0x14: 0x5c000000, 0x24: pitch,
        0x30: 0x000237ff if valid else 0x400237ff, 0x34: 0x03020001,
    }.items():
        cpu.mem_write(0x05e05000 + offset, struct.pack('<I', value))
    ticks, reset, gold = [0], [False], [False]

    def system_instruction(uc, address, size, instruction):
        operation, arguments = instruction
        if operation == 'msr':
            # Unicorn has no GIC system-register model. Only the memory-side
            # preparation and handoff structure are covered by this test.
            assert arguments.startswith('ICC_')
            uc.reg_write(registers.UC_ARM64_REG_PC, address + 4)
            return
        if operation == 'smc':
            if uc.reg_read(registers.UC_ARM64_REG_X0) == 0xc4000003:
                assert not gold[0], 'Repeated Gold handoff'
                assert uc.reg_read(registers.UC_ARM64_REG_X1) == 0x100
                entry = uc.reg_read(registers.UC_ARM64_REG_X2)
                context = uc.reg_read(registers.UC_ARM64_REG_X3)
                gold[0] = True
                uc.reg_write(registers.UC_ARM64_REG_X0, context)
                uc.reg_write(registers.UC_ARM64_REG_PC, entry)
                return
            assert uc.reg_read(registers.UC_ARM64_REG_X0) == 0x84000009
            assert cpu.mem_read(0x0c12565c, 4) == struct.pack('<I', 0x77665500)
            reset[0] = True
            uc.emu_stop()
            return
        target, name = arguments.split(', ')
        name = name.strip()
        if name == 'CNTPCT_EL0':
            ticks[0] += 100000
            value = ticks[0]
        elif name == 'CNTFRQ_EL0':
            value = 100
        elif name == 'CurrentEL':
            value = 4
        elif name.startswith('SCTLR'):
            value = 0
        elif name == 'MPIDR_EL1':
            value = 0x80000100 if gold[0] else 0x80000000
        elif name == 'ID_AA64MMFR0_EL1':
            value = 0x111122 if gold[0] else 0x11122
        else:
            value = 0x1234
        uc.reg_write(getattr(registers, 'UC_ARM64_REG_' + target.upper()), value)
        uc.reg_write(registers.UC_ARM64_REG_PC, address + 4)

    for offset, operation, arguments in HOOKS:
        cpu.hook_add(UC_HOOK_CODE, system_instruction, (operation, arguments),
                     begin=base + offset, end=base + offset)

    def guard_mmio_write(uc, access, address, size, value, extra):
        raise AssertionError(f'Unexpected display register write at {address:#x}')

    cpu.hook_add(UC_HOOK_MEM_WRITE, guard_mmio_write,
                 begin=0x05e00000, end=0x05e2ffff)
    try:
        cpu.emu_start(base, base + len(IMAGE), count=80000000)
    except Exception:
        print(f'Emulator stopped at PC={cpu.reg_read(registers.UC_ARM64_REG_PC):#x}')
        raise
    if loader:
        assert entered[0], 'Shim did not reach validated XNU entry'
    else:
        assert reset[0], 'Shim did not reach PSCI reset request'
    assert gold[0], 'Gold handoff did not execute'
    if valid:
        assert cpu.mem_read(0x5c000000, 4) == struct.pack('<I', 0xff101010)
        text = cpu.mem_read(0x5c000000 + 24 * pitch, 30 * pitch)
        assert b'\xff\xff\xff\xff' in text, 'No text rendered'
        assert not any(cpu.mem_read(0x5c000000 + 2340 * pitch, 4096)), 'Write past surface'
        assert not any(cpu.mem_read(0x5c000000 + 1080 * 4, pitch - 1080 * 4)), 'Padding overwritten'
    else:
        assert not any(cpu.mem_read(0x5c000000, 0xf00000)), 'Unsupported display was modified'
    print(f'PASS: relocated at {base:#x}; display {"accepted" if valid else "rejected"}; ' +
          ('XNU entry and boot arguments verified' if loader else 'reset requested'))


if __name__ == '__main__':
    import sys
    if '--loader' in sys.argv:
        run(0x40200000, True, loader=True)
    else:
        run(0x40200000, True)
        run(0x80200000, True)
        run(0x40200000, False)
