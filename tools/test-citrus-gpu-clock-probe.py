#!/usr/bin/env python3
"""Sanitized tests of read-only SMEM clock-prerequisite discovery."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
#include <random>
using vm_offset_t = uintptr_t;
std::vector<uint8_t> memory(0x200000), fuses(0x1000), clocks(0x9000);
volatile uint8_t *gpucc = clocks.data();
vm_offset_t ml_io_map(uint64_t at, uint32_t) {
    return at == 0x01b46000 ? (uintptr_t)fuses.data() : (uintptr_t)memory.data();
}
unsigned reports;
#define IOLog(...) (++reports)
uint32_t rd(volatile uint8_t *base, unsigned at) { return *(volatile uint32_t *)(base + at); }
/* PROBE */
void put(uint32_t at, uint32_t v) { memcpy(memory.data() + at, &v, 4); }
void channel(unsigned at) {
    memcpy(memory.data() + at, "rpm_requests", 13);
    put(at + 20, 3); put(at + 24, 15); put(at + 28, 1);
}
void clear() { std::fill(memory.begin(), memory.end(), 0); }
void global() {
    clear(); put(0x5c, 11u << 16); put(0xc0, 1);
    unsigned entry = 0xd0 + 13 * 16;
    put(entry, 1); put(entry + 4, 0x3000); put(entry + 8, 2048);
    channel(0x3000);
}
void partition() {
    clear(); put(0x5c, 12u << 16); put(0xc0, 1);
    unsigned table = memory.size() - 4096;
    put(table, 0x434f5424); put(table + 4, 1); put(table + 8, 1);
    put(table + 32, 0x10000); put(table + 36, 0x2000); put(table + 44, 6u << 16);
    put(0x10000, 0x54525024); put(0x10004, 6u << 16);
    put(0x10008, 0x2000); put(0x1000c, 32 + 16 + 2048); put(0x10010, 0x2000);
    put(0x10020, (13u << 16) | 0xa5a5); put(0x10024, 2048);
    channel(0x10030);
}
int main() {
    uint32_t offset, length;
    global(); auto before = memory;
    assert(citrus_clock_item(memory.data(), memory.size(), 13, &offset, &length));
    assert(offset == 0x3000 && length == 2048);
    assert(citrus_clock_smem(memory.data(), memory.size()) == 1);
    assert(memory == before);
    put(0x3000 + 24, 1); assert(citrus_clock_smem(memory.data(), memory.size()) == 0);
    global(); put(0x3000 + 20, 64); assert(citrus_clock_smem(memory.data(), memory.size()) == 0);
    global(); put(0x3000 + 28, 0); assert(citrus_clock_smem(memory.data(), memory.size()) == 0);
    global(); memory[0x3000 + 12] = 'X'; assert(citrus_clock_smem(memory.data(), memory.size()) == 0);
    global(); put(0xd0 + 13*16 + 4, 0xfffffff0); assert(citrus_clock_smem(memory.data(), memory.size()) == 0);
    global(); put(0xd0 + 13*16 + 4, 0x3001); assert(citrus_clock_smem(memory.data(), memory.size()) == 0);
    global(); put(0xd0 + 13*16 + 12, 0xdead0000); assert(citrus_clock_smem(memory.data(), memory.size()) == 0);
    global(); put(0xd0 + 13*16 + 8, 2047); assert(citrus_clock_smem(memory.data(), memory.size()) == 0);
    global(); put(0xc0, 0); assert(citrus_clock_smem(memory.data(), memory.size()) == 0);
    assert(!citrus_clock_item(memory.data(), 0x20cf, 13, &offset, &length));
    assert(!citrus_clock_item(memory.data(), memory.size(), 512, &offset, &length));
    partition(); before = memory;
    assert(citrus_clock_smem(memory.data(), memory.size()) == 1 && memory == before);
    put(0x10024, 0xfffffff8); assert(citrus_clock_smem(memory.data(), memory.size()) == 0);
    partition(); put(0x10028, 0xfff80000); assert(citrus_clock_smem(memory.data(), memory.size()) == 0);
    partition(); put(0x10028, 2049); assert(citrus_clock_smem(memory.data(), memory.size()) == 0);
    partition(); put(0x10020, 0); assert(citrus_clock_smem(memory.data(), memory.size()) == 0);
    partition(); put(memory.size()-4096+8, UINT32_MAX); assert(citrus_clock_smem(memory.data(), memory.size()) == 0);
    partition(); put(0x1000c, 0x2008); assert(citrus_clock_smem(memory.data(), memory.size()) == 0);
    partition(); put(memory.size()-4096+44, 2u << 16); assert(citrus_clock_smem(memory.data(), memory.size()) == 0);
    clear(); put(0x5c, 99u << 16); assert(citrus_clock_smem(memory.data(), memory.size()) == 0);
    for (unsigned n = 0; n < 0x20d0; n += 43) assert(citrus_clock_smem(memory.data(), n) == 0);
    // Exercise corrupt sizes/offsets with valid entry canaries under sanitizers.
    std::mt19937 random(42);
    for (unsigned n = 0; n < 5000; n++) {
        partition(); put(0x10024, random()); put(0x10028, random());
        assert(citrus_clock_smem(memory.data(), memory.size()) == 0);
    }
    global(); before = memory; auto clockBefore = clocks, fuseBefore = fuses;
    citrus_gpu_clock_probe();
    assert(memory == before && clocks == clockBefore && fuses == fuseBefore);
    puts("PASS: global/private SMEM, malformed bounds, channel identity, fuzz and no memory writes");
}
'''


def main():
    header = ROOT / 'kernel/drivers/CitrusGpuClockProbe.h'
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / 'probe.cpp'; binary = Path(tmp) / 'probe'
        source.write_text(HARNESS.replace('/* PROBE */', header.read_text()))
        subprocess.run(['xcrun', 'clang++', '-std=c++17', '-O1', '-fsanitize=address,undefined',
                        str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
