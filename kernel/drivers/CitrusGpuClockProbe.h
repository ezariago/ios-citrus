/* Read-only Citrus clock prerequisite discovery. No SMD/rail/clock writes.
 * Layout references: MiCode lime-q-oss drivers/soc/qcom/smem.c and
 * drivers/rpmsg/qcom_smd.c. Snapshot only; not a concurrent SMEM transport.
 */
#define CITRUS_CLOCK_SMEM_BASE 0x46000000ull
#define CITRUS_CLOCK_SMEM_SIZE 0x200000u

static bool
citrus_clock_range(uint32_t size, uint32_t at, uint32_t length)
{
    return at <= size && length <= size - at;
}

static uint32_t
citrus_clock_read(const volatile uint8_t *base, uint32_t at)
{
    /* Callers bound the span and require aligned offsets. */
    return *(const volatile uint32_t *)(base + at);
}

static bool
citrus_clock_item(const volatile uint8_t *base, uint32_t size, uint32_t item,
    uint32_t *offset, uint32_t *length)
{
    if (item >= 512 || size < 0x20d0 || citrus_clock_read(base, 0xc0) != 1 ||
        (citrus_clock_read(base, 0x5c) >> 16) != 11) { return false; }
    uint32_t entry = 0xd0 + 16 * item;
    if (citrus_clock_read(base, entry) != 1) { return false; }
    uint32_t at = citrus_clock_read(base, entry + 4);
    uint32_t bytes = citrus_clock_read(base, entry + 8);
    uint32_t aux = citrus_clock_read(base, entry + 12) & ~3u;
    if ((at & 3) || (aux != 0 && aux != CITRUS_CLOCK_SMEM_BASE) ||
        bytes == 0 || !citrus_clock_range(size, at, bytes)) { return false; }
    *offset = at; *length = bytes;
    return true;
}

static bool
citrus_clock_rpm_name(const volatile uint8_t *base, uint32_t at)
{
    static const char name[] = "rpm_requests";
    for (uint32_t i = 0; i < sizeof(name); i++) {
        uint32_t word = citrus_clock_read(base, at + (i & ~3u));
        if (((word >> (8 * (i & 3))) & 255) != (uint8_t)name[i]) { return false; }
    }
    return true;
}

static unsigned
citrus_clock_channels(const volatile uint8_t *base, uint32_t size,
    uint32_t offset, uint32_t length, uint32_t table)
{
    if ((offset & 3) || length < 64 * 32 ||
        !citrus_clock_range(size, offset, length)) { return 0; }
    unsigned found = 0;
    for (uint32_t i = 0; i < 64; i++) {
        uint32_t at = offset + 32 * i;
        uint32_t cid = citrus_clock_read(base, at + 20);
        uint32_t flags = citrus_clock_read(base, at + 24);
        uint32_t refs = citrus_clock_read(base, at + 28);
        if (refs == 0 || cid >= 64 || (flags & 255) != 15 ||
            !citrus_clock_rpm_name(base, at)) { continue; }
        IOLog("CitrusClock: RPM channel table=%u cid=%u flags=%#x refs=%u (snapshot, no writes)\n",
            table, cid, flags, refs);
        found++;
    }
    return found;
}

/* Inspect only existing uncached entries of APPS/RPM or global partitions.
 * Cached entries are deliberately not implemented in this discovery probe.
 */
static unsigned
citrus_clock_partition(const volatile uint8_t *base, uint32_t regionSize,
    uint32_t offset, uint32_t size, uint32_t hosts)
{
    if ((offset & 3) || size < 32 || !citrus_clock_range(regionSize, offset, size) ||
        citrus_clock_read(base, offset) != 0x54525024 ||
        citrus_clock_read(base, offset + 4) != hosts ||
        citrus_clock_read(base, offset + 8) != size) { return 0; }
    uint32_t end = citrus_clock_read(base, offset + 12);
    uint32_t cached = citrus_clock_read(base, offset + 16);
    if ((end & 7) || end < 32 || end > cached || cached > size) { return 0; }
    unsigned found = 0;
    for (uint32_t at = 32; at < end;) {
        if (!citrus_clock_range(end, at, 16)) { return found; }
        uint32_t first = citrus_clock_read(base, offset + at);
        uint32_t bytes = citrus_clock_read(base, offset + at + 4);
        uint32_t padding = citrus_clock_read(base, offset + at + 8);
        uint32_t hdrPad = padding >> 16, dataPad = padding & 65535;
        if ((first & 65535) != 0xa5a5 || (bytes & 7) || (hdrPad & 7) ||
            dataPad > bytes || !citrus_clock_range(end, at + 16, hdrPad) ||
            !citrus_clock_range(end, at + 16 + hdrPad, bytes)) { return found; }
        uint32_t item = first >> 16;
        if (item == 13 || item == 266) {
            found += citrus_clock_channels(base, regionSize, offset + at + 16 + hdrPad,
                bytes - dataPad, item);
        }
        at += 16 + hdrPad + bytes;
    }
    return found;
}

static unsigned
citrus_clock_smem(const volatile uint8_t *base, uint32_t size)
{
    if (size < 0x20d0) { return 0; }
    uint32_t version = citrus_clock_read(base, 0x5c) >> 16;
    IOLog("CitrusClock: SMEM version=%u initialized=%u; existing-item snapshot only\n",
        version, citrus_clock_read(base, 0xc0));
    if (version != 11 && version != 12) { return 0; }
    unsigned found = 0;
    for (uint32_t i = 0; i < 2; i++) {
        uint32_t item = i == 0 ? 13 : 266, offset, length;
        if (citrus_clock_item(base, size, item, &offset, &length)) {
            found += citrus_clock_channels(base, size, offset, length, item);
        }
    }
    uint32_t table = size - 4096;
    if ((table & 3) || citrus_clock_read(base, table) != 0x434f5424 ||
        citrus_clock_read(base, table + 4) != 1) { return found; }
    uint32_t count = citrus_clock_read(base, table + 8);
    if (count > (4096 - 32) / 48) { return found; }
    for (uint32_t i = 0; i < count; i++) {
        uint32_t entry = table + 32 + 48 * i;
        uint32_t offset = citrus_clock_read(base, entry);
        uint32_t length = citrus_clock_read(base, entry + 4);
        uint32_t hosts = citrus_clock_read(base, entry + 12);
        uint32_t a = hosts & 65535, b = hosts >> 16;
        if (!((a == 0 && b == 6) || (a == 6 && b == 0) ||
              (a == 0xfffe && b == 0xfffe))) { continue; }
        IOLog("CitrusClock: SMEM partition hosts=%u:%u offset=%#x size=%#x\n", a, b, offset, length);
        found += citrus_clock_partition(base, size, offset, length, hosts);
    }
    return found;
}

static void
citrus_gpu_clock_probe(void)
{
    /* Captured live DT: qfprom@1b40000, speed_bin@6006 bits=<5 8>,
     * gaming_bin@602d bits=<5 1>; SMEM reserved region 46000000 + 200000. */
    const volatile uint8_t *fuses = (const volatile uint8_t *)ml_io_map(0x01b46000, 0x1000);
    if (fuses != NULL) {
        uint32_t speed = (citrus_clock_read(fuses, 4) >> 21) & 255;
        uint32_t gaming = (citrus_clock_read(fuses, 0x2c) >> 13) & 1;
        IOLog("CitrusClock: fuse speed_bin=%u gaming_bin=%u (read only)\n", speed, gaming);
    }
    IOLog("CitrusClock: GFX cmd=%#x cfg=%#x PLL0 mode=%#x L=%#x PLL1 mode=%#x L=%#x; current policy 300 MHz\n",
        rd(gpucc, 0x101c), rd(gpucc, 0x1020), rd(gpucc, 0), rd(gpucc, 4), rd(gpucc, 0x100), rd(gpucc, 0x104));
    const volatile uint8_t *smem = (const volatile uint8_t *)ml_io_map(CITRUS_CLOCK_SMEM_BASE, CITRUS_CLOCK_SMEM_SIZE);
    if (smem == NULL) { IOLog("CitrusClock: SMEM map failed; no voltage request attempted\n"); return; }
    unsigned found = citrus_clock_smem(smem, CITRUS_CLOCK_SMEM_SIZE);
    IOLog("CitrusClock: discovery found %u RPM channel entries; no SMD/voltage/clock writes\n", found);
}
