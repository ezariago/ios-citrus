#!/usr/bin/env python3
"""Execute a compiled kernel reset vector under Unicorn with synthetic CPU records.

This tests the actual reset-vector instructions and full Aff1:Aff0 lookup; it
stops before the CPU reset handler and does not model caches, PSCI or GIC.
"""
import argparse
from pathlib import Path
import re
import struct
import subprocess
import sys

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm64_const as reg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'upstream/ios-topaz/tools'))
import mkpayload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path)
    args = parser.parse_args()
    kernel = args.kernel.read_bytes()
    macho = mkpayload.parse_macho(kernel)
    assert not macho['fixups'], 'test expects a kernel without chained fixups'
    symbols = subprocess.check_output(['xcrun', 'nm', '-n', str(args.kernel)], text=True)
    names = {}
    wanted = {'_reset_vector', '_ResetHandlerData', '_start_cpu'}
    for line in symbols.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] in wanted:
            names[parts[2]] = int(parts[0], 16)
    assert names.keys() >= wanted
    dump = subprocess.check_output([
        '/opt/homebrew/opt/llvm/bin/llvm-objdump', '-d',
        f"--start-address={names['_reset_vector']:#x}",
        f"--stop-address={names['_reset_vector'] + 0x88:#x}", str(args.kernel)], text=True)
    def offset(pattern):
        hits = re.findall(pattern, dump)
        assert len(hits) == 1, (pattern, hits)
        return int(hits[0], 0)
    entries_off = offset(r'ldr\s+x1, \[x19, #(0x[0-9a-f]+|\d+)\]')
    phys_off = offset(r'ldr\s+w2, \[x21, #(0x[0-9a-f]+|\d+)\]')
    handler_off = offset(r'ldr\s+x0, \[x21, #(0x[0-9a-f]+|\d+)\]')
    assert re.search(r'and\s+x0, x15, #0xffff', dump), 'reset vector does not compare full Aff1:Aff0'
    sysreg = []
    for line in dump.splitlines():
        match = re.match(r'^([0-9a-f]+):\s+[0-9a-f]+\s+(mrs|msr)\s+(.+)$', line.strip())
        if match:
            sysreg.append((int(match[1], 16), match[2], match[3]))
    assert any(op == 'mrs' and 'MPIDR_EL1' in arg for _, op, arg in sysreg)
    virtbase = macho['segs'][0]['vmaddr'] & ~(0x2000000 - 1)
    physbase = 0x80000000
    def phys(address):
        result = physbase + address - virtbase
        assert physbase <= result < physbase + 0x3800000
        return result
    entries, records = 0x83800000, 0x83900000
    cpus = [0x100, 0x101, 0x102, 0x103, 1, 2, 3]
    for wanted_mpidr in [0x101, 0x001, 0x102, 0x003, 0x007]:
        uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        uc.mem_map(physbase, 0x4000000)
        for segment in macho['segs']:
            if segment['vmsize'] and segment['filesize']:
                uc.mem_write(phys(segment['vmaddr']), kernel[segment['fileoff']:segment['fileoff'] + segment['filesize']])
        uc.mem_write(phys(names['_ResetHandlerData']) + entries_off, struct.pack('<Q', entries))
        for index, mpidr in enumerate(cpus):
            record = records + index * 0x1000
            uc.mem_write(entries + index * 16, struct.pack('<Q', record))
            uc.mem_write(record + phys_off, struct.pack('<I', mpidr))
            uc.mem_write(record + handler_off, struct.pack('<Q', phys(names['_start_cpu'])))
        reached = []
        def handle_sysreg(machine, addr, size, details):
            op, arg = details
            if op == 'mrs':
                assert 'MPIDR_EL1' in arg
                machine.reg_write(reg.UC_ARM64_REG_X15, wanted_mpidr | 0x80000000)
            machine.reg_write(reg.UC_ARM64_REG_PC, addr + 4)
        for address, op, arg in sysreg:
            uc.hook_add(UC_HOOK_CODE, handle_sysreg, (op, arg), begin=phys(address), end=phys(address))
        def reached_handler(machine, address, size, _):
            reached.append(machine.reg_read(reg.UC_ARM64_REG_X21))
            machine.emu_stop()
        handler = phys(names['_start_cpu'])
        uc.hook_add(UC_HOOK_CODE, reached_handler, begin=handler, end=handler)
        uc.emu_start(phys(names['_reset_vector']), physbase + 0x4000000, count=300)
        if wanted_mpidr in cpus:
            assert reached == [records + cpus.index(wanted_mpidr) * 0x1000], (wanted_mpidr, reached)
        else:
            assert not reached, f'unknown MPIDR {wanted_mpidr:#x} reached a handler'
    print('PASS: compiled reset vector distinguishes 0x001/0x101 and rejects an unknown MPIDR')
    print('Emulation stops at the reset handler; PSCI, caches, GIC and XNU startup are not tested')


if __name__ == '__main__':
    main()
