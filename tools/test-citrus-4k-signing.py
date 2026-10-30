#!/usr/bin/env python3
"""Exercise the actual 4K signing-unit guard with address/undefined sanitizers."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'out/citrus-8core/source/xnu/bsd/kern/ubc_subr.c'


def main():
    text = SOURCE.read_text()
    start = text.index('static boolean_t\ncitrus_cs_hash_fits_range(')
    end = text.index('\n#endif', start)
    helper = text[start:end]
    guard = text.index('if (!citrus_cs_hash_fits_range(blobs, page_offset, PAGE_SIZE))')
    assert guard < text.index('subrange_validated = cs_validate_hash(', guard)
    range_start = text.index('boolean_t\ncs_validate_range(')
    range_guard = text.index('if (!citrus_cs_hash_fits_range(blobs, page_offset + offset_in_range,', range_start)
    assert range_guard < text.index('subrange_validated = cs_validate_hash(', range_start)
    harness = r'''
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>
typedef uint64_t memory_object_offset_t;
typedef int boolean_t;
typedef uint64_t vm_size_t;
#define FALSE 0
#define TRUE 1
#define PAGE_SHIFT 12
struct cs_blob {
    struct cs_blob *csb_next;
    uint64_t csb_base_offset;
    off_t csb_start_offset, csb_end_offset;
    uintptr_t csb_mem_kaddr;
    void *csb_cd;
    unsigned csb_hash_pageshift;
};
''' + helper + r'''
int main(void) {
    struct cs_blob small = {0, 0, 0, 0x8000, 1, (void *)1, 12};
    struct cs_blob large = {&small, 0, 0x4000, 0x8000, 1, (void *)1, 14};
    assert(citrus_cs_hash_fits_range(0, 0, 4096));
    assert(citrus_cs_hash_fits_range(&large, 0x3000, 4096));
    for (uint64_t p = 0x4000; p < 0x8000; p += 0x1000)
        assert(!citrus_cs_hash_fits_range(&large, p, 4096));
    assert(citrus_cs_hash_fits_range(&large, 0x4000, 16384));
    assert(!citrus_cs_hash_fits_range(&large, 0x5000, 16384));
    assert(citrus_cs_hash_fits_range(&large, 0x8000, 4096));
    large.csb_mem_kaddr = 0;
    assert(citrus_cs_hash_fits_range(&large, 0x5000, 4096));
    large.csb_mem_kaddr = 1; large.csb_cd = 0;
    assert(citrus_cs_hash_fits_range(&large, 0x5000, 4096));
    large.csb_cd = (void *)1; large.csb_base_offset = 0x10000;
    assert(!citrus_cs_hash_fits_range(&large, 0x15000, 4096));
    large.csb_hash_pageshift = 32;
    assert(!citrus_cs_hash_fits_range(&large, 0x14000, 65536));
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='citrus-cs-') as tmp:
        c = Path(tmp) / 'test.c'
        exe = Path(tmp) / 'test'
        c.write_text(harness)
        subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', str(c), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print('PASS: 4K hash-unit selection guard (ASan/UBSan); full XNU policy not tested')


if __name__ == '__main__':
    main()
