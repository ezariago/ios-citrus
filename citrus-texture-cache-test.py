#!/usr/bin/env python3
"""Host-only regression test for the uninstalled texture-cache experiment.

Extracts the real image helpers after applying the patch to a temporary copy.
Stubbed CoreFoundation/GL operations do not validate iOS reentrancy or rendering.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'upstream/ios-topaz/userland/gpu/eagl.c'
PATCH = ROOT / 'citrus-texture-cache-experiment.patch'

PREAMBLE = r'''
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
typedef unsigned GLuint;
typedef void *IOSurfaceRef;
struct image { GLuint texture, mirror; bool sub_ok; IOSurfaceRef surface; };
struct eagl { struct image *images[32]; unsigned image_count; };
static int refs, fail_next, deletes;
static void *test_calloc(size_t n, size_t s) {
    if (fail_next) { fail_next = 0; return NULL; }
    return calloc(n, s);
}
#define calloc test_calloc
static void *CFRetain(void *p) { assert(p); refs++; return p; }
static void CFRelease(void *p) { assert(p); refs--; }
static void glDeleteTextures(int n, GLuint *p) { assert(n == 1 && *p); deletes++; }
static void say(const char *s) { (void)s; }
'''
TEST = r'''
int main(void) {
    struct eagl e = {0};
    void *s = (void *)(uintptr_t)1;
    for (unsigned i = 1; i <= 256; i++) assert(image_new(&e, i, s));
    assert(e.image_count == 256 && refs == 256);
    struct image *stable = image_of(&e, 100);
    fail_next = 1;
    assert(!image_new(&e, 257, s));
    assert(e.image_count == 256 && image_of(&e, 100) == stable);
    for (unsigned i = 257; i <= 8192; i++) {
        assert(image_new(&e, i, s));
        if (i % 256 == 0) assert(image_of(&e, 100) == stable);
    }
    assert(refs == 8192);
    assert(!image_new(&e, 8193, s));
    image_of(&e, 100)->mirror = 10;
    assert(image_new(&e, 100, s));
    assert(refs == 8192 && deletes == 1 && e.image_count == 8192);
    image_of(&e, 100)->mirror = 11;
    image_forget(&e, 100);
    assert(!image_of(&e, 100) && refs == 8191 && deletes == 2);
    assert(image_of(&e, 8192)); /* moved slot is still findable */
    image_forget(&e, 8192);
    assert(refs == 8190 && !image_of(&e, 8192));
    assert(image_new(&e, 8193, s)); /* reuse a freed slot at the limit */
    for (unsigned i = 0; i < e.image_count; i++) CFRelease(image_at(&e, i)->surface);
    for (unsigned i = 0; i < IMAGE_BLOCKS; i++) free(e.images[i]);
    assert(refs == 0);
    puts("PASS: cache growth, OOM, cap, replace, delete, slot reuse, retain balance");
}
'''


def portion(text, begin, end):
    start = text.index(begin)
    return text[start:text.index(end, start)]


def main():
    with tempfile.TemporaryDirectory(prefix='citrus-texture-test-') as tmp:
        directory = Path(tmp)
        shutil.copyfile(SOURCE, directory / 'eagl.c')
        subprocess.run(['patch', '--batch', '-p1', '-i', str(PATCH)], cwd=directory, check=True)
        source = (directory / 'eagl.c').read_text()
        pieces = [
            portion(source, '#define IMAGE_BLOCK_SIZE', '/*\n * glscale='),
            portion(source, 'static struct image *\nimage_new(', '/* A viewport'),
            portion(source, 'static void\nimage_forget(', "/* Apple's OpenGL"),
        ]
        (directory / 'test.c').write_text(PREAMBLE + ''.join(pieces) + TEST)
        subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-O1', str(directory / 'test.c'),
                        '-o', str(directory / 'test')], check=True)
        subprocess.run([str(directory / 'test')], check=True)
        subprocess.run(['patch', '--batch', '--dry-run', '-R', '-p1', '-i', str(PATCH)],
                       cwd=directory, check=True)


if __name__ == '__main__':
    main()
