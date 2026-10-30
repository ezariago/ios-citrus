/* Citrus diagnostic stage. No storage, clocks, voltage, GIC or DSI writes. */
#include <stdint.h>
#include "font.h"

#define RSR(r) ({ uint64_t v; __asm__ volatile("mrs %0, " #r : "=r"(v)); v; })
#define SPLASH_BASE 0x5c000000UL
#define SPLASH_END  0x5cf00000UL
#define WIDTH 1080
#define HEIGHT 2340
#define FOREGROUND 0xffffffffU

static volatile uint32_t *fb;
static unsigned stride, row;
static uint32_t pipe_format;
static uint32_t background;
extern char gold_entry[];
extern int try_xnu(void);

static uint64_t smc(uint64_t fn, uint64_t a1, uint64_t a2, uint64_t a3)
{
    register uint64_t x0 __asm__("x0") = fn;
    register uint64_t x1 __asm__("x1") = a1;
    register uint64_t x2 __asm__("x2") = a2;
    register uint64_t x3 __asm__("x3") = a3;
    __asm__ volatile("dsb sy; smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3) : :
                     "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11",
                     "x12", "x13", "x14", "x15", "x16", "x17", "memory");
    return x0;
}

static uint32_t read32(uintptr_t p) { return *(volatile uint32_t *)p; }

/* Inspect bootloader scanout. Draw only into an uncompressed 4-byte surface
 * contained entirely within the DT's continuous-splash reservation. */
static int find_display(void)
{
    const uintptr_t bases[] = {0x05e05000, 0x05e25000};
    for (unsigned i = 0; i < 2; ++i) {
        uintptr_t base = bases[i];
        uint32_t size = read32(base), address = read32(base + 0x14);
        uint32_t pitch = read32(base + 0x24) & 0xffff;
        uint32_t format = read32(base + 0x30), opmode = read32(base + 0x38);
        uint32_t unpack = read32(base + 0x34);
        unsigned width = size & 0xffff, height = size >> 16;
        /* Bits 9:10 encode bpp-1. OPMODE bit 0 enables compression.
         * SRC_FORMAT fetch mode bits 30:31 must describe linear memory. */
        if (width != WIDTH || height != HEIGHT || ((format >> 9) & 3) != 3 ||
            (format >> 30) != 0 || (opmode & ((1U << 14) | (1U << 13) | 1)) ||
            (format & 0xff) != 0xff || (format & ((1U << 15) | (1U << 14))) ||
            ((format >> 19) & 3) || ((format >> 23) & 3) ||
            ((format >> 12) & 3) != 3 || !(format & (1U << 17)) ||
            (format & ((1U << 11) | (1U << 22))) || pitch < WIDTH * 4 ||
            pitch > 8192 || pitch % 4 || address % 4 || address < SPLASH_BASE ||
            (uint64_t)address + (uint64_t)pitch * HEIGHT > SPLASH_END)
            continue;
        if (read32(base + 0x08) || read32(base + 0x0c) != size ||
            read32(base + 0x10) || read32(base + 0x170)) continue;
        unsigned seen = 0;
        uint32_t bg = 0;
        for (unsigned byte = 0; byte < 4; ++byte) {
            unsigned component = (unpack >> (8 * byte)) & 0xff;
            if (component > 3 || (seen & (1U << component))) { seen = 0; break; }
            seen |= 1U << component;
            bg |= (component == 3 ? 0xffU : 0x10U) << (8 * byte);
        }
        if (seen != 15) continue;
        fb = (volatile uint32_t *)(uintptr_t)address;
        stride = pitch / 4;
        pipe_format = format;
        background = bg;
        return 1;
    }
    return 0;
}

static void character(unsigned x, unsigned y, char ch)
{
    unsigned index = ch >= 'A' && ch <= 'Z' ? (unsigned)(ch - 'A') :
                     ch >= '0' && ch <= '9' ? (unsigned)(ch - '0' + 26) : 36;
    for (unsigned cy = 0; cy < 7; ++cy)
        for (unsigned cx = 0; cx < 5; ++cx) {
            uint32_t color = (font[index][cy] & (1U << (4 - cx))) ? FOREGROUND : background;
            for (unsigned sy = 0; sy < 3; ++sy)
                for (unsigned sx = 0; sx < 3; ++sx)
                    fb[(y + cy * 3 + sy) * stride + x + cx * 3 + sx] = color;
        }
}

void line(const char *label, uint64_t value)
{
    if (!fb || row >= 65) return;
    unsigned x = 24, y = 24 + row++ * 30;
    while (*label && x < 240) { character(x, y, *label++); x += 18; }
    x = 258;
    for (int i = 15; i >= 0; --i) {
        unsigned digit = (value >> (i * 4)) & 15;
        character(x, y, digit < 10 ? '0' + digit : 'A' + digit - 10);
        x += 18;
    }
    __asm__ volatile("dsb sy" ::: "memory");
}

static uint32_t be32(uintptr_t p) { return __builtin_bswap32(read32(p)); }
static int equal(const char *a, const char *b)
{
    while (*a && *a == *b) { ++a; ++b; }
    return *a == *b;
}

static int memory_name(const char *name)
{
    const char prefix[] = "memory";
    for (unsigned i = 0; i < 6; ++i) if (name[i] != prefix[i]) return 0;
    return name[6] == 0 || name[6] == '@';
}

/* Bounded FDT walk: display RAM banks exactly as ABL supplied them. No
 * allocation or kernel handoff until the usable ranges have been reviewed. */
static void show_memory(uintptr_t dtb)
{
    if (!dtb || dtb % 4 || be32(dtb) != 0xd00dfeed) { line("BAD DTB", dtb); return; }
    uint32_t total = be32(dtb + 4), offset = be32(dtb + 8);
    uint32_t strings = be32(dtb + 12), names_size = be32(dtb + 32);
    uint32_t structure_size = be32(dtb + 36);
    if (be32(dtb + 20) < 17 || offset % 4 || offset < 40 ||
        total < 40 || total > 0x400000 || offset > total || strings > total ||
        names_size > total - strings || structure_size > total - offset) return;
    uintptr_t p = dtb + offset, end = p + structure_size;
    int depth = 0, memory = 0, address_cells = 0, size_cells = 0;
    while (p + 4 <= end) {
        uint32_t token = be32(p); p += 4;
        if (token == 1) {
            uintptr_t start = p;
            while (p < end && *(volatile char *)p) ++p;
            if (p >= end) return;
            ++depth;
            if (depth == 2) memory = memory_name((const char *)start);
            p = (p + 4) & ~3UL;
        } else if (token == 2) {
            if (depth == 2) memory = 0;
            if (--depth < 0) return;
        } else if (token == 3) {
            if (p + 8 > end) return;
            uint32_t len = be32(p), name = be32(p + 4); p += 8;
            if (len > end - p || name >= names_size) return;
            uintptr_t np = dtb + strings + name, ne = dtb + strings + names_size;
            uintptr_t q = np;
            while (q < ne && *(volatile char *)q) ++q;
            if (q == ne) return;
            if (depth == 1 && len == 4) {
                if (equal((const char *)np, "#address-cells")) address_cells = be32(p);
                if (equal((const char *)np, "#size-cells")) size_cells = be32(p);
            }
            if (memory && depth == 2 && address_cells == 2 && size_cells == 2 &&
                equal((const char *)np, "reg") && len % 16 == 0)
                for (uint32_t i = 0; i < len; i += 16) {
                    line("RAM BASE", ((uint64_t)be32(p+i) << 32) | be32(p+i+4));
                    line("RAM SIZE", ((uint64_t)be32(p+i+8) << 32) | be32(p+i+12));
                }
            p = (p + len + 3) & ~3UL;
        } else if (token == 4) continue;
        else return;
    }
}

static void reset(void)
{
    /* Live Citrus DT: msm-imem@c125000/restart_reason@65c. Request
     * bootloader mode so the host can restore the original boot partition. */
    *(volatile uint32_t *)0x0c12565cUL = 0x77665500U;
    smc(0x84000009, 0, 0, 0);
    /* Firmware on this phone returned without resetting during test 1.
     * Use the DT-confirmed PS_HOLD deassert fallback, as the Qualcomm
     * restart driver does. IMEM retains the requested bootloader reason. */
    *(volatile uint32_t *)0x0440b000UL = 0;
    __asm__ volatile("dsb sy" ::: "memory");
    for (;;) __asm__ volatile("wfe");
}

void shim_main(uintptr_t dtb)
{
    uint64_t frequency = RSR(cntfrq_el0), start = RSR(cntpct_el0);
    if (find_display()) {
        row = 0;
        for (unsigned y = 0; y < HEIGHT; ++y)
            for (unsigned x = 0; x < WIDTH; ++x) fb[y * stride + x] = background;
        line("CITRUS DIAG", 2);
        line("CURRENT EL", RSR(CurrentEL) >> 2);
        line("MIDR", RSR(midr_el1));
        line("MPIDR", RSR(mpidr_el1));
        line("MMFR0", RSR(id_aa64mmfr0_el1));
        line("GRANULE 16K", (RSR(id_aa64mmfr0_el1) >> 20) & 15);
        line("MMFR1", RSR(id_aa64mmfr1_el1));
        line("PFR0", RSR(id_aa64pfr0_el1));
        line("ISAR0", RSR(id_aa64isar0_el1));
        line("CNTFRQ", frequency);
        line("DTB", dtb);
        line("FB BASE", (uintptr_t)fb);
        line("FB STRIDE", stride * 4);
        line("FB FORMAT", pipe_format);
        show_memory(dtb);
    }
#if defined(CITRUS_BOOT_SILVER)
    /*
     * 4 KiB experiment: ABL leaves us on Silver core 0.  A 4 KiB kernel does
     * not need the Gold cluster's 16K granule, so boot XNU here directly and
     * let PSCI bring up all seven remaining cores.  This avoids the parked
     * Silver 0 that limits the Gold-boot path to seven CPUs.
     */
    if ((RSR(mpidr_el1) & 0xffffff) == 0) {
        int result = try_xnu();
        if (result) line("XNU ERROR", (uint64_t)(int64_t)result);
    }
#else
    if ((RSR(mpidr_el1) & 0xffffff) != 0x100) {
        line("GOLD TARGET", 0x100);
        uint64_t result = smc(0xc4000003, 0x100, (uintptr_t)gold_entry, dtb);
        if (result == 0) for (;;) __asm__ volatile("wfi");
        line("CPU ON ERROR", result);
    }
    if ((RSR(mpidr_el1) & 0xffffff) == 0x100 &&
        ((RSR(id_aa64mmfr0_el1) >> 20) & 15) == 1) {
        int result = try_xnu();
        if (result) line("XNU ERROR", (uint64_t)(int64_t)result);
    }
#endif
    line("RESET IN SEC", 60);
    /* Return to the bootloader after an observation window for restoration. */
    while (RSR(cntpct_el0) - start < frequency * 60) __asm__ volatile("yield");
    reset();
}

void shim_exception(uint64_t esr, uint64_t elr, uint64_t far)
{
    line("EXCEPTION", esr);
    line("ELR", elr);
    line("FAR", far);
    uint64_t start = RSR(cntpct_el0), frequency = RSR(cntfrq_el0);
    while (RSR(cntpct_el0) - start < frequency * 30) __asm__ volatile("yield");
    reset();
}
