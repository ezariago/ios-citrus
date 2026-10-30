#!/usr/bin/env python3
"""Generate an experimental, fastboot-only reset overlay from the RX probe."""
from pathlib import Path
import argparse
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('probe', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
s = a.probe.read_text()
anchor = 'static struct citrus_usb_parser citrus_parser;\n'
assert s.count(anchor) == 1
reset = r'''
/* Runs in the USB event thread. The active 4K profile has a read-only root.
 * Citrus bootloader handling of this IMEM reason is not yet verified. */
static void
citrus_reset_to_bootloader(void)
{
    vm_offset_t imem = ml_io_map(0x0c125000, 0x1000);
    *(volatile uint32_t *)(imem + 0x65c) = 0x77665500;
    __asm__ volatile("dsb sy" ::: "memory");
    register uint64_t x0 __asm__("x0") = 0x84000009;
    register uint64_t x1 __asm__("x1") = 0;
    register uint64_t x2 __asm__("x2") = 0;
    register uint64_t x3 __asm__("x3") = 0;
    __asm__ volatile("smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3) : :
        "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13",
        "x14", "x15", "x16", "x17", "cc", "memory");
    printf("CITRUS USB: PSCI reset returned %d\n", (int32_t)x0);
}
'''
s = s.replace(anchor, anchor + reset)
old = '''\t\t\telse if (c == CITRUS_FASTBOOT || c == CITRUS_RECOVERY)
\t\t\t\tprintf("CITRUS USB: restart request received, probe only\\n");'''
new = '''\t\t\telse if (c == CITRUS_FASTBOOT) citrus_reset_to_bootloader();
\t\t\telse if (c == CITRUS_RECOVERY)
\t\t\t\tprintf("CITRUS USB: recovery restart not implemented\\n");'''
assert s.count(old) == 1
s = s.replace(old, new).replace('/* Probe only: no received command can reset this build. */', '/* Experimental fastboot reset; recovery remains disabled. */')
a.output.write_text(s)
