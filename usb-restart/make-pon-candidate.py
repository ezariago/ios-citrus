#!/usr/bin/env python3
"""Generate a PMIC restart-reason experiment from the receive-only overlay."""
from pathlib import Path
import argparse
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('probe', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
s = a.probe.read_text()
anchor = 'static struct citrus_usb_parser citrus_parser;\n'
assert s.count(anchor) == 1
code = r'''
/* PM6125 PON SID 0, PPID 0x008. No reset unless every check succeeds. */
static bool
citrus_pon_read(vm_offset_t obs, uint32_t off, uint8_t reg, uint8_t *value)
{
    *(volatile uint32_t *)(obs + off) = (1u << 27) | ((uint32_t)reg << 4);
    __asm__ volatile("dsb osh" ::: "memory");
    for (unsigned i = 0; i < 1000; i++) {
        uint32_t status = *(volatile uint32_t *)(obs + off + 8);
        if (status & 1u) {
            if (status & 14u) return false;
            *value = (uint8_t)*(volatile uint32_t *)(obs + off + 0x18);
            return true;
        }
        delay(1);
    }
    return false;
}
static bool
citrus_pon_write(vm_offset_t channel, uint8_t reg, uint8_t value)
{
    *(volatile uint32_t *)(channel + 0x10) = value;
    __asm__ volatile("dmb oshst" ::: "memory");
    *(volatile uint32_t *)channel = (uint32_t)reg << 4; /* EXT_WRITEL, one byte */
    __asm__ volatile("dsb osh" ::: "memory");
    for (unsigned i = 0; i < 1000; i++) {
        uint32_t status = *(volatile uint32_t *)(channel + 8);
        if (status & 1u) return !(status & 14u);
        delay(1);
    }
    return false;
}
static void
citrus_pon_reset(enum citrus_usb_command cmd)
{
    vm_offset_t core = ml_io_map(0x01c40000, 0x2000);
    vm_offset_t cfg = ml_io_map(0x01c0a000, 0x1000);
    if (!core || !cfg) { printf("CITRUS RESET: mapping failed\n"); return; }
    uint32_t version = *(volatile uint32_t *)core;
    uint32_t count = *(volatile uint32_t *)(core + 4) & 0x7ffu;
    if (version < 0x50000000 || version >= 0x70000000 || !count || count > 512) {
        printf("CITRUS RESET: unsupported arbiter\n"); return;
    }
    unsigned apid;
    for (apid = 0; apid < count; apid++) {
        uint32_t map = *(volatile uint32_t *)(core + 0x900 + 4 * apid);
        uint32_t owner = *(volatile uint32_t *)(cfg + 0x700 + 4 * apid) & 7;
        if (map && ((map >> 8) & 0xfff) == 0x008 && owner == 0) break;
    }
    if (apid == count) { printf("CITRUS RESET: no apps-owned PON channel\n"); return; }
    uint32_t off = apid * 0x80u;
    vm_offset_t obs = ml_io_map(0x03e00000 + (off & ~0xfffu), 0x1000);
    vm_offset_t wr = ml_io_map(0x01e00000 + apid * 0x10000u, 0x1000);
    if (!obs || !wr) { printf("CITRUS RESET: PON mapping failed\n"); return; }
    off &= 0xfffu;
    uint8_t subtype, before, after;
    if (!citrus_pon_read(obs, off, 0x05, &subtype) ||
        !citrus_pon_read(obs, off, 0x8f, &before)) {
        printf("CITRUS RESET: PON read failed\n"); return;
    }
    unsigned shift;
    if (subtype == 4 || subtype == 5) shift = 1;
    else if (subtype >= 1 && subtype <= 3) shift = 2;
    else { printf("CITRUS RESET: unknown PON subtype %#x\n", subtype); return; }
    uint8_t mask = shift == 1 ? 0xfe : 0xfc;
    uint8_t reason = cmd == CITRUS_FASTBOOT ? 2 : 1;
    uint8_t desired = (before & ~mask) | ((reason << shift) & mask);
    if (!citrus_pon_write(wr, 0x8f, desired) ||
        !citrus_pon_read(obs, off, 0x8f, &after) || after != desired) {
        printf("CITRUS RESET: PON write/readback failed\n"); return;
    }
    vm_offset_t imem = ml_io_map(0x0c125000, 0x1000);
    if (!imem) { printf("CITRUS RESET: IMEM mapping failed\n"); return; }
    *(volatile uint32_t *)(imem + 0x65c) = cmd == CITRUS_FASTBOOT ? 0x77665500u : 0x77665502u;
    __asm__ volatile("dsb sy" ::: "memory");
    register uint64_t x0 __asm__("x0") = 0x84000009;
    register uint64_t x1 __asm__("x1") = 0;
    register uint64_t x2 __asm__("x2") = 0;
    register uint64_t x3 __asm__("x3") = 0;
    __asm__ volatile("smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3) : :
        "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13",
        "x14", "x15", "x16", "x17", "cc", "memory");
    printf("CITRUS RESET: PSCI returned %d\n", (int32_t)x0);
}
'''
s = s.replace(anchor, anchor + code)
old = '''\t\t\telse if (c == CITRUS_FASTBOOT || c == CITRUS_RECOVERY)
\t\t\t\tprintf("CITRUS USB: restart request received, probe only\\n");'''
new = '''\t\t\telse if (c == CITRUS_FASTBOOT || c == CITRUS_RECOVERY) citrus_pon_reset(c);'''
assert s.count(old) == 1
s = s.replace(old, new).replace('/* Probe only: no received command can reset this build. */', '/* Experimental PMIC restart-reason path. */')
a.output.write_text(s)
