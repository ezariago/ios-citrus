/* Bounded SWEETXNU payload handoff. Container format is shared with Topaz's
 * tools/mkpayload.py. This stage never accesses storage. */
#include <stdint.h>

extern char _head[], _end[];
extern void line(const char *, uint64_t);

struct segment { uint64_t vmaddr, vmsize, file_offset, file_size; };
struct payload {
    char magic[8];
    uint32_t version, count;
    uint64_t virt_base, entry, adt_offset, adt_size, kernel_end, phys_base, memory_size;
    char cmdline[608];
    struct segment segments[];
};
struct video { uint64_t base, display, stride, width, height, depth; };
struct boot_args {
    uint16_t revision, version;
    uint64_t virt_base, phys_base, memory_size, top;
    struct video video;
    uint32_t machine;
    uint64_t adt;
    uint32_t adt_size;
    char cmdline[608];
    uint64_t flags, actual_memory;
};
_Static_assert(sizeof(struct boot_args) == 736, "XNU boot_args layout");
_Static_assert(__builtin_offsetof(struct payload, segments) == 0x2a8, "Payload layout");

static int matches(const char *a, const char *b)
{
    for (unsigned i = 0; i < 8; ++i) if (a[i] != b[i]) return 0;
    return 1;
}
static int inside(uint64_t value, uint64_t size, uint64_t base, uint64_t length)
{
    return value >= base && value - base <= length && size <= length - (value - base);
}
static void copy(uintptr_t dst, uintptr_t src, uint64_t size)
{
    while (size >= 8 && !(dst & 7) && !(src & 7)) {
        *(volatile uint64_t *)dst = *(const volatile uint64_t *)src;
        dst += 8; src += 8; size -= 8;
    }
    while (size--) *(volatile uint8_t *)dst++ = *(const volatile uint8_t *)src++;
}
static void clear(uintptr_t dst, uint64_t size)
{
    while (size && (dst & 7)) { *(volatile uint8_t *)dst++ = 0; --size; }
    while (size >= 8) { *(volatile uint64_t *)dst = 0; dst += 8; size -= 8; }
    while (size--) *(volatile uint8_t *)dst++ = 0;
}
static uint32_t read32(uintptr_t p) { return *(volatile uint32_t *)p; }
static void write32(uintptr_t p, uint32_t v) { *(volatile uint32_t *)p = v; }

static int prepare_gic(void)
{
    uint64_t sre;
    __asm__ volatile("mrs %0, icc_sre_el1" : "=r"(sre));
    sre |= 1;
    __asm__ volatile("msr icc_sre_el1, %0; isb" : : "r"(sre));
    write32(0x0f200000, read32(0x0f200000) | 0x13);
    for (unsigned i = 0; i < 1000000 && (read32(0x0f200000) >> 31); ++i) {}
    uintptr_t redistributor = 0;
    for (uintptr_t offset = 0; offset < 0x100000; offset += 0x20000) {
        uint64_t typer = *(volatile uint64_t *)(0x0f300008 + offset);
        if ((typer >> 32) == 0x100) { redistributor = 0x0f300000 + offset; break; }
        if (typer & 16) break;
    }
    if (!redistributor) return 0;
    write32(redistributor + 0x14, read32(redistributor + 0x14) & ~2U);
    for (unsigned i = 0; i < 1000000 && (read32(redistributor + 0x14) & 4); ++i) {}
    if (read32(redistributor + 0x14) & 4) return 0;
    write32(redistributor + 0x10080, 0xffffffff);
    for (unsigned i = 0; i < 32; ++i)
        *(volatile uint8_t *)(redistributor + 0x10400 + i) = 0xa0;
    write32(redistributor + 0x10100, (1U << 19) | (1U << 18) | (1U << 1));
    uint64_t ctlr;
    __asm__ volatile("mrs %0, icc_ctlr_el1" : "=r"(ctlr));
    ctlr &= ~2UL;
    __asm__ volatile("msr icc_ctlr_el1, %0; msr icc_pmr_el1, %1;"
                     "msr icc_bpr1_el1, xzr; msr icc_igrpen1_el1, %2; isb"
                     : : "r"(ctlr), "r"(0xf0UL), "r"(1UL) : "memory");
    line("GICR", redistributor);
    return 1;
}

/* Returns zero for a diagnostic-only image; positive/negative after a
 * payload attempt. All validation completes before any kernel memory writes. */
int try_xnu(void)
{
    uint64_t image_size = *(const uint64_t *)(_head + 16);
    uint64_t shim_size = (uintptr_t)_end - (uintptr_t)_head;
    if (image_size <= shim_size + 16 || image_size > 0x8000000) return 0;
    uintptr_t container = (uintptr_t)_end;
    if (!matches((const char *)container, "CITRUSPL")) return -1;
    uint64_t length = *(const uint64_t *)(container + 8);
    if (length > image_size - shim_size - 16 || length < sizeof(struct payload)) return -2;
    uintptr_t start = container + 16;
    const struct payload *p = (const struct payload *)start;
    if (!matches(p->magic, "SWEETXNU") || p->version != 1 || !p->count || p->count > 64 ||
        p->count > (length - sizeof(*p)) / sizeof(struct segment)) return -3;
    /* Citrus profiles are limited to the verified low DDR bank that starts at
     * 0x80000000: 1 GiB (original) or 1.75 GiB, which ends at 0xf0000000 just
     * below the first firmware reservation at 0xf3c00000. Nothing from Topaz's
     * nonexistent high DDR bank is accepted. */
    if (p->phys_base != 0x80000000 ||
        (p->memory_size != 0x40000000 && p->memory_size != 0x70000000) ||
        p->virt_base > p->entry || p->virt_base > p->kernel_end ||
        p->kernel_end - p->virt_base > p->memory_size ||
        !inside(p->adt_offset, p->adt_size, 0, length) || !p->adt_size ||
        p->adt_size > 0x100000 || p->cmdline[607] != 0 ||
        !inside(p->entry, 4, p->virt_base, p->kernel_end - p->virt_base)) return -4;
    if (inside(start, length, p->phys_base, p->memory_size) ||
        ((uint64_t)start < p->phys_base && (uint64_t)start + length > p->phys_base)) return -5;
    uint64_t adt = p->phys_base + p->kernel_end - p->virt_base;
    if (adt & 0x3fff) return -6;
    uint64_t args = (adt + p->adt_size + 0x3fff) & ~0x3fffUL;
    uint64_t top = args + 0x4000;
    if (top > p->phys_base + p->memory_size) return -7;
    int entry_in_segment = 0;
    for (unsigned i = 0; i < p->count; ++i) {
        const struct segment *s = &p->segments[i];
        if (s->file_size > s->vmsize ||
            !inside(s->file_offset, s->file_size, 0, length) ||
            !inside(s->vmaddr, s->vmsize, p->virt_base, p->kernel_end - p->virt_base)) return -8;
        if (inside(p->entry, 4, s->vmaddr, s->file_size)) entry_in_segment = 1;
        for (unsigned k = 0; k < i; ++k) {
            const struct segment *t = &p->segments[k];
            if (s->vmsize && t->vmsize && s->vmaddr < t->vmaddr + t->vmsize &&
                t->vmaddr < s->vmaddr + s->vmsize) return -9;
        }
    }
    if (!entry_in_segment) return -10;
    line("XNU SEGMENTS", p->count);
    if (!prepare_gic()) return -11;
    for (unsigned i = 0; i < p->count; ++i) {
        const struct segment *s = &p->segments[i];
        uintptr_t dst = p->phys_base + s->vmaddr - p->virt_base;
        copy(dst, start + s->file_offset, s->file_size);
        clear(dst + s->file_size, s->vmsize - s->file_size);
    }
    copy(adt, start + p->adt_offset, p->adt_size);
    clear(args, 0x4000);
    volatile struct boot_args *ba = (volatile struct boot_args *)args;
    ba->revision = ba->version = 2;
    ba->virt_base = p->virt_base; ba->phys_base = p->phys_base;
    ba->memory_size = ba->actual_memory = p->memory_size;
    ba->top = top;
    ba->video = (struct video){0x5c000000, 1, 4320, 1080, 2340, 32};
    ba->adt = adt - p->phys_base + p->virt_base;
    ba->adt_size = (uint32_t)p->adt_size;
    copy((uintptr_t)ba->cmdline, (uintptr_t)p->cmdline, 608);
    uintptr_t entry = p->phys_base + p->entry - p->virt_base;
    line("XNU BOOTARGS", args);
    line("XNU ENTRY", entry);
    /* Any subsequent firmware/watchdog reset should land in fastboot. */
    write32(0x0c12565c, 0x77665500U);
    __asm__ volatile("dsb sy; ic iallu; dsb sy; isb" ::: "memory");
    ((void (*)(uint64_t))entry)(args);
    return -12;
}
