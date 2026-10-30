#!/usr/bin/env python3
"""Exercise the real GFX3D/PLL0 clock encoders with a fake GPUCC register block.

Host-only: checks the 300/600 MHz GPLL0 divider fields, the 950 MHz PLL0
1900 MHz multiplier/alpha encoding, parent selection, rejection of unsupported
rates, PLL-lock failure and RCG update-poll failure. It does not measure a
clock, voltage or GPU operation.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'out/citrus-gpu/xnu/iokit/Kernel/arm/TopazAdreno.cpp'
HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>

#define RCG_UPDATE (1u << 0)
#define SRC_GPLL0  5
#define SRC_PLL0_AUX2 2

#define PLL0_MODE       0x00
#define PLL0_L          0x04
#define PLL0_ALPHA      0x08
#define PLL0_ALPHA_HI   0x0c
#define PLL0_USER_CTL   0x10
#define PLL0_CONFIG_CTL 0x18
#define PLL0_TEST_CTL_U 0x20
#define PLL_BYPASSNL    (1u << 1)
#define PLL_RESET_N     (1u << 2)
#define PLL_UPDATE_BYPASS (1u << 23)
#define PLL_ALPHA_EN    (1u << 24)
#define PLL_ACTIVE      (1u << 30)
#define PLL_LOCK        (1u << 31)

static uint32_t regs[0x4000 / 4];
static volatile uint8_t *gpucc = (volatile uint8_t *)regs;
static unsigned writes, polls;
static bool pollFails, pllLockFails, rcgUpdateFails;

void wr(volatile uint8_t *b, uint32_t o, uint32_t v)
{
    ++writes;
    *(volatile uint32_t *)(b + o) = v;
}

uint32_t rd(volatile uint8_t *b, uint32_t o)
{
    return *(volatile uint32_t *)(b + o);
}

void rmw(volatile uint8_t *b, uint32_t o, uint32_t clear, uint32_t set)
{
    wr(b, o, (rd(b, o) & ~clear) | set);
}

void IODelay(unsigned) {}

bool poll(volatile uint8_t *b, uint32_t o, uint32_t mask, uint32_t value, unsigned)
{
    ++polls;
    if (pollFails) { return false; }
    uint32_t *reg = (uint32_t *)((uint8_t *)regs + o);
    if (o == PLL0_MODE && mask == PLL_LOCK) {
        if (pllLockFails) { return false; }
        *reg |= PLL_LOCK;
        return (*reg & mask) == value;
    }
    if (rcgUpdateFails) { return false; }
    /* The RCG latches the update and clears CMD_UPDATE; model that here. */
    *reg &= ~mask;
    return (*reg & mask) == value;
}

void IOLog(const char *, ...) {}

/* CLOCK */
static uint32_t cfg(void) { return rd(gpucc, 0x1020); }

static void reset(void)
{
    memset(regs, 0, sizeof(regs));
    writes = polls = 0;
    pollFails = pllLockFails = rcgUpdateFails = false;
}

int main()
{
    // The 300 MHz bring-up rate is GPLL0 / 2: parent 5 and divider field 3.
    reset();
    assert(gfx_set_mhz(300));
    assert(cfg() == ((SRC_GPLL0 << 8) | 3));
    assert((rd(gpucc, 0x101c) & RCG_UPDATE) == 0);
    assert(polls == 1 && writes == 2);

    // 600 MHz is the same parent at / 1: divider field 1.
    reset();
    assert(gfx_set_mhz(600));
    assert(cfg() == ((SRC_GPLL0 << 8) | 1));

    // A round trip back to the bring-up rate restores the exact field.
    reset();
    assert(gfx_set_mhz(600) && gfx_set_mhz(300));
    assert(cfg() == ((SRC_GPLL0 << 8) | 3));

    // 950 MHz needs PLL0 at 1900 MHz; 1900/19.2 = 98 + 23/24.
    reset();
    assert(gfx_set_mhz(950));
    assert(cfg() == ((SRC_PLL0_AUX2 << 8) | 3));
    assert(rd(gpucc, PLL0_L) == 98);
    assert(rd(gpucc, PLL0_ALPHA_HI) == 0xf5);
    assert(rd(gpucc, PLL0_ALPHA) == 0x55555500);
    assert(rd(gpucc, PLL0_CONFIG_CTL) == 0x4001055b);
    assert(rd(gpucc, PLL0_TEST_CTL_U) == 1);
    assert((rd(gpucc, PLL0_USER_CTL) & ((1u << 24) | 0x7u)) == ((1u << 24) | 0x7u));
    assert((rd(gpucc, PLL0_MODE) & PLL_LOCK) == PLL_LOCK);
    assert(polls == 2);                 // PLL lock, then RCG update

    // Returning to 300 MHz must move the RCG back to GPLL0, not leave it on AUX2.
    assert(gfx_set_mhz(300));
    assert(cfg() == ((SRC_GPLL0 << 8) | 3));

    // Unsupported rates are rejected before any register write.
    reset();
    assert(!gfx_set_mhz(745));
    assert(!gfx_set_mhz(0));
    assert(writes == 0 && polls == 0 && cfg() == 0);

    // A PLL that never locks fails before the RCG is touched.
    reset();
    pllLockFails = true;
    assert(!gfx_set_mhz(950));
    assert(cfg() == 0);

    // An RCG update failure after a locked PLL also surfaces as failure.
    reset();
    rcgUpdateFails = true;
    assert(!gfx_set_mhz(950));
    assert(cfg() == ((SRC_PLL0_AUX2 << 8) | 3));
    rcgUpdateFails = false;
    assert(gfx_set_mhz(300));
    assert(cfg() == ((SRC_GPLL0 << 8) | 3));

    // A failed GPLL0 update still surfaces and keeps the encoded field visible.
    reset();
    pollFails = true;
    assert(!gfx_set_mhz(600));
    assert(cfg() == ((SRC_GPLL0 << 8) | 1));

    puts("PASS: 300/600 GPLL0, 950 PLL0 encoding, parent, failures");
}
'''


def main():
    text = SOURCE.read_text()
    start = text.index('static bool\nrcg_set(')
    end = text.index('\nstatic bool\ngdsc_on(', start)
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        source = directory / 'gfx_clock.cpp'
        source.write_text(HARNESS.replace('/* CLOCK */', text[start:end]))
        binary = directory / 'gfx_clock'
        subprocess.run(['xcrun', 'clang++', '-std=c++17', '-Wall', '-Wextra',
                        '-fsanitize=address,undefined', str(source), '-o', str(binary)],
                       check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
