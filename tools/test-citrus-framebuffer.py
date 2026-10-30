#!/usr/bin/env python3
"""Exercise the real presentation copy loop on host memory, without a phone.

This checks pixel contents across alternating default/allocated surfaces and
partial layers. It does not emulate GPU fences, cache maintenance or scanout.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REL = 'iokit/Kernel/arm/SweetFramebuffer.cpp'

HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
struct Memory { uint64_t getLength() { return 48; } } memory;
struct SweetSurface {
    uint32_t width = 4, height = 3, pixelFormat = 0, bytesPerRow = 16;
    uint32_t bytesPerElement = 4, elementWidth = 1, elementHeight = 1, offset = 0;
    Memory *memory = &::memory;
    uint32_t pixels[12] = {};
    uintptr_t kernelAddress() { return (uintptr_t)pixels; }
    void release() {}
} surfaces[2];
SweetSurface *fSurface = &surfaces[0];
SweetSurface *sweet_surface_copy(uint32_t id) {
    return id >= 1 && id <= 2 ? &surfaces[id - 1] : nullptr;
}
template<class T> void release(T *&s) { if (s) s->release(); s = nullptr; }
#define OSSafeReleaseNULL(s) release(s)
#define IOLog(...) ((void)0)
bool topaz_surface_drawn(SweetSurface *, uint64_t) { return true; }
constexpr uint32_t SWEET_FB_LAYERS = 4;
uint32_t sweet_fb_swaps_logged;
uint32_t buffers[2][12], front;
void *fFlip[2] = {buffers[0], buffers[1]};
int32_t fOffX = 0, fOffY = 0;
uint32_t fWidth = 4, fHeight = 3, fRowBytes = 16;
void flipBack() { front ^= 1; }
uint32_t get32(const uint8_t *p, uint32_t off) {
    uint32_t v; memcpy(&v, p + off, 4); return v;
}
void put32(uint8_t *p, uint32_t off, uint32_t v) { memcpy(p + off, &v, 4); }
void present(const uint8_t *rec) {
    uint32_t mask = get32(rec, 0x104);
    uint8_t *dst = (uint8_t *)buffers[front ^ 1];
    /* COPY_LOOP */
}
int main() {
    for (auto &buffer : buffers) for (auto &p : buffer) p = 0x00badbad;
    // CoreAnimation swaps between default surface 1 and allocated surface 2.
    for (uint32_t frame = 1; frame <= 8; ++frame) {
        uint32_t id = frame % 2 + 1;
        for (auto &p : surfaces[id - 1].pixels) p = 0xff000000 | frame;
        uint8_t rec[0x46c] = {};
        put32(rec, 0x104, 1); put32(rec, 0x54, id);
        put32(rec, 0xcc, 4); put32(rec, 0xd0, 3);
        present(rec);
        for (auto p : buffers[front]) assert(p == (0xff000000 | frame));
    }
    // The default surface also works as the base of a multi-layer frame.
    for (auto &p : surfaces[0].pixels) p = 0xff123456;
    for (auto &p : surfaces[1].pixels) p = 0xffabcdef;
    uint8_t rec[0x46c] = {};
    put32(rec, 0x104, 3); put32(rec, 0x54, 1); put32(rec, 0x58, 2);
    put32(rec, 0xcc, 4); put32(rec, 0xd0, 3);
    put32(rec, 0xd4, 1); put32(rec, 0xd8, 1);
    put32(rec, 0xdc, 2); put32(rec, 0xe0, 1);
    present(rec);
    for (uint32_t i = 0; i < 12; ++i)
        assert(buffers[front][i] == (i == 5 || i == 6 ? 0xffabcdef : 0xff123456));
    puts("PASS: alternating default/allocated frames and layered default frame");
}
'''

ALLOCATION_HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <vector>
using IOByteCount = uint64_t;
using SInt64 = int64_t;
constexpr uint32_t SWEET_SURFACE_MAX_DIM = 16384;
constexpr unsigned kIODirectionInOut = 1, kIOMemoryKernelUserShared = 2;
constexpr unsigned kIOMemoryPhysicallyContiguous = 4, kIOMemoryMapperNone = 0;
constexpr unsigned kIOMapDefaultCache = 0;
void *kernel_task;
int mode, live;
uint64_t sweet_surface_wired;
uint64_t round_page_64(uint64_t n) { return (n + 16383) & ~16383ull; }
int64_t OSAddAtomic64(int64_t n, volatile int64_t *v) { return *v += n; }
struct IOBufferMemoryDescriptor {
    std::vector<uint8_t> pixels;
    explicit IOBufferMemoryDescriptor(uint64_t size) : pixels(size, 0xcd) { ++live; }
    static IOBufferMemoryDescriptor *inTaskWithPhysicalMask(void *, unsigned, uint64_t size, uint64_t) {
        return mode == 1 ? nullptr : new IOBufferMemoryDescriptor(size);
    }
    uint64_t getPhysicalSegment(unsigned, uint64_t *length, unsigned) {
        *length = pixels.size() - (mode == 2 ? 1 : 0);
        return mode == 3 ? 0xefffc000ull : 0x90000000ull;
    }
    void *getBytesNoCopy() { return pixels.data(); }
    void release() { --live; delete this; }
};
struct SweetSurface {
    uint32_t width, height, bytesPerRow, bytesPerElement, elementWidth, elementHeight;
    uint32_t pixelFormat, allocSize, mapCache;
    uint64_t scanoutPhys;
    IOBufferMemoryDescriptor *memory = nullptr;
    void release() {
        if (memory) { sweet_surface_wired -= allocSize; memory->release(); }
        delete this;
    }
};
SweetSurface *sweet_surface_alloc() { return new SweetSurface; }
bool sweet_surface_publish(SweetSurface *) { return mode != 4; }
template<class T> void release(T *&s) { if (s) s->release(); s = nullptr; }
#define OSSafeReleaseNULL(s) release(s)
/* ALLOCATE */
int main() {
    auto *s = sweet_surface_create_render_target(1080, 2340, 0x42475241);
    assert(s && s->bytesPerRow == 4352);
    assert(s->allocSize >= uint64_t(s->bytesPerRow) * (s->height + 64));
    assert((s->allocSize & 16383) == 0);
    assert(s->scanoutPhys == 0x90000000 && sweet_surface_wired == s->allocSize);
    for (auto p : s->memory->pixels) assert(p == 0);
    s->release();
    assert(live == 0 && sweet_surface_wired == 0);
    for (mode = 1; mode <= 4; ++mode) {
        assert(sweet_surface_create_render_target(1080, 2340, 0x42475241) == nullptr);
        assert(live == 0 && sweet_surface_wired == 0);
    }
    mode = 0;
    assert(sweet_surface_create_render_target(0, 2340, 0) == nullptr);
    assert(sweet_surface_create_render_target(0xffffffff, 2340, 0) == nullptr);
    assert(sweet_surface_create_render_target(16384, 16384, 0) == nullptr);
    assert(live == 0 && sweet_surface_wired == 0);
    puts("PASS: cached target layout, zeroing, guard, bounds and failure cleanup");
}
'''


def check_allocation(directory):
    text = (ROOT / 'out/citrus-gpu/xnu/iokit/Kernel/arm/SweetSurface.cpp').read_text()
    start = text.index('SweetSurface *\nsweet_surface_create_render_target(')
    end = text.index('\nmach_port_name_t\n', start)
    source = directory / 'allocate.cpp'
    source.write_text(ALLOCATION_HARNESS.replace('/* ALLOCATE */', text[start:end]))
    binary = directory / 'allocate'
    subprocess.run(['xcrun', 'clang++', '-std=c++17', '-fsanitize=address,undefined',
                    str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)


def check(source, directory, name):
    text = source.read_text()
    start = text.index('\tfor (uint32_t layer = 0; layer < SWEET_FB_LAYERS; layer++) {',
                       text.index('AppleCLCD::present('))
    end = text.index('\n}\n', start)
    program = directory / (name + '.cpp')
    program.write_text(HARNESS.replace('/* COPY_LOOP */', text[start:end]))
    binary = directory / name
    subprocess.run(['xcrun', 'clang++', '-std=c++17', '-fsanitize=address,undefined',
                    str(program), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)


def main():
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        for name, tree in [('baseline', 'out/upstream-artifacts/buildtree/xnu'),
                           ('gpu', 'out/citrus-gpu/xnu')]:
            print(name + ':', flush=True)
            check(ROOT / tree / REL, directory, name)
        check_allocation(directory)


if __name__ == '__main__':
    main()
