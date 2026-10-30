#!/usr/bin/env python3
"""Exercise the real GPU buffer allocation/reuse/lifetime methods with sanitizers.

Host-only regression for quarantined perf4b: validates ownership/fence gates,
not hardware allocation success, performance or device cache coherency.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'out/citrus-gpu-performance4b/xnu/iokit/Kernel/arm/RedwoodGPU.cpp'
HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
using IOReturn = int;
using IOByteCount = uint64_t;
using addr64_t = uint64_t;
using vm_size_t = uint64_t;
constexpr int kIOReturnSuccess = 0, kIOReturnBadArgument = 1, kIOReturnNoMemory = 2;
constexpr unsigned kIOMemoryMapperNone = 0, kIODirectionInOut = 1;
constexpr unsigned kIOMemoryKernelUserShared = 2, kIOMemoryPhysicallyContiguous = 4;
constexpr unsigned kIOMapWriteCombineCache = 8, PAGE_SIZE = 16384;
constexpr uint64_t NSEC_PER_SEC = 1000000000;
/* DEFINES */
void *kernel_task, *gGPULock;
bool gGPUCached;
uint32_t gGPUKeep = 1, completed = 0;
uint64_t now = 1000;
unsigned lockDepth = 0, live = 0, allocations = 0, releases = 0, unmaps = 0;
bool failAllocation = false;
unsigned allocationFailuresRemaining = 0;
struct { uint32_t made, given_again; uint64_t making, reclaimed; uint32_t reclaimPasses; } gGPUStat;
uint64_t mach_absolute_time() { return ++now; }
uint64_t round_page_64(uint64_t n) { return (n + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1ull); }
void nanoseconds_to_absolutetime(uint64_t n, uint64_t *out) { *out = n; }
void IOLockLock(void *) { assert(lockDepth == 0); ++lockDepth; }
void IOLockUnlock(void *) { assert(lockDepth == 1); --lockDepth; }
#define IOLog(...) ((void)0)
struct IOMemoryDescriptor {
    std::vector<uint8_t> bytes;
    unsigned refs = 1;
    explicit IOMemoryDescriptor(uint64_t n) : bytes(n, 0) { ++live; }
    virtual ~IOMemoryDescriptor() { --live; ++releases; }
    void retain() { ++refs; }
    void release() { assert(refs); if (--refs == 0) delete this; }
    addr64_t getPhysicalSegment(uint64_t from, uint64_t *len, unsigned) {
        *len = bytes.size() - from; return 0x90000000 + from;
    }
};
struct IOBufferMemoryDescriptor : IOMemoryDescriptor {
    using IOMemoryDescriptor::IOMemoryDescriptor;
    static IOBufferMemoryDescriptor *inTaskWithPhysicalMask(void *, unsigned, uint64_t n, uint64_t) {
        ++allocations;
        if (allocationFailuresRemaining) { --allocationFailuresRemaining; return nullptr; }
        return failAllocation ? nullptr : new IOBufferMemoryDescriptor(n);
    }
    static IOBufferMemoryDescriptor *inTaskWithOptions(void *, unsigned, uint64_t n, unsigned) {
        return new IOBufferMemoryDescriptor(n);
    }
    void *getBytesNoCopy() { return bytes.data(); }
};
#define OSDynamicCast(T, p) dynamic_cast<T *>(p)
#define OSSafeReleaseNULL(p) do { if (p) { (p)->release(); (p) = nullptr; } } while (0)
struct SweetSurface {
    IOMemoryDescriptor *memory;
    unsigned refs = 1;
    void release() { assert(refs); --refs; }
};
bool redwood_gpu_identity() { return true; }
bool redwood_gpu_ready() { return true; }
bool topaz_gpu_midmem() { return true; }
bool redwood_gpu_done(uint32_t fence) { return fence <= completed; }
bool gpuWait(uint32_t fence, uint64_t) { return redwood_gpu_done(fence); }
void redwood_gpu_unmap(uint64_t, uint64_t) { ++unmaps; }
void redwood_gpu_address_free(uint64_t, uint64_t) {}
uint64_t redwood_gpu_address(uint64_t) { return 0; }
bool redwood_gpu_map(uint64_t, uint64_t, unsigned) { return true; }
void redwood_gpu_mapped() {}
void redwood_gpu_to_memory(void *, uint64_t) {}
uint64_t topaz_gpu_pool_alloc(uint64_t, void **) { return 0; }
IOMemoryDescriptor *topaz_gpu_pool_md(uint64_t, uint64_t) { return nullptr; }
struct msm_gem_new { uint64_t size; uint32_t flags, handle = 0; };
constexpr unsigned MSM_BO_GPU_READONLY = 2;
/* STRUCTS */
class RedwoodGPUUserClient {
public:
    gpu_buffer fBuffers[GPU_BUFFERS] = {};
    uint32_t fNextBuffer = 0, fBufferCount = 0;
    uint64_t fBufferBytes = 0;
    gpu_left fLeft[GPU_LEFT] = {};
    uint32_t fLeftCount = 0;
    gpu_kept fKept[GPU_KEPT] = {};
    uint64_t fKeptBytes = 0;
    gpu_buffer *newBuffer(IOMemoryDescriptor *, uint64_t, uint64_t, uint32_t, uint32_t *);
    void freeBuffer(gpu_buffer *);
    bool keep(IOMemoryDescriptor *, uint8_t *, uint64_t, uint64_t, uint32_t);
    void dropKept(gpu_kept *);
    void reap();
    IOReturn gemNew(msm_gem_new *);
    void give(uint32_t handle) {
        IOLockLock(gGPULock); freeBuffer(&fBuffers[handle - 1]); IOLockUnlock(gGPULock);
    }
    void drain() {
        completed = UINT32_MAX;
        IOLockLock(gGPULock);
        for (auto &b : fBuffers) if (b.memory) freeBuffer(&b);
        reap(); for (auto &k : fKept) dropKept(&k);
        IOLockUnlock(gGPULock);
        assert(fBufferCount == 0 && fBufferBytes == 0 && fKeptBytes == 0 && fLeftCount == 0);
    }
};
/* METHODS */
int main() {
    RedwoodGPUUserClient c, other;
    constexpr uint64_t size = 512u << 10;
    msm_gem_new r = {size, 0};
    assert(c.gemNew(&r) == 0 && live == 1 && gGPUStat.made == 1 && gGPUStat.making > 0);
    auto *memory = c.fBuffers[r.handle - 1].memory;
    memory->bytes[42] = 0xa5;
    c.give(r.handle);
    assert(c.fKeptBytes == size && c.fBufferCount == 0);
    unsigned before = allocations;
    assert(c.gemNew(&r) == 0 && c.fBuffers[r.handle - 1].memory == memory);
    assert(allocations == before && gGPUStat.given_again == 1);
    assert(memory->bytes[42] == 0xa5 && c.fKeptBytes == 0);
    assert(c.fBuffers[r.handle - 1].fence == 0 && !c.fBuffers[r.handle - 1].seen);
    c.give(r.handle);

    // Exact flags and size; another client cannot receive this client's cache.
    msm_gem_new mismatch = {size, 2};
    assert(c.gemNew(&mismatch) == 0 && c.fBuffers[mismatch.handle - 1].memory != memory);
    c.give(mismatch.handle);
    mismatch = {size * 2, 0};
    assert(c.gemNew(&mismatch) == 0 && c.fBuffers[mismatch.handle - 1].memory != memory);
    c.give(mismatch.handle);
    assert(other.gemNew(&r) == 0 && other.fBuffers[r.handle - 1].memory != memory);
    other.drain();

    // A retained buffer must not bypass the active wired-memory limit.
    c.fBufferBytes = GPU_CLIENT_BYTES;
    assert(c.gemNew(&r) == kIOReturnNoMemory && lockDepth == 0);
    c.fBufferBytes = 0;
    gGPUKeep = 2;
    assert(c.gemNew(&r) == 0 && c.fBuffers[r.handle - 1].memory == memory);
    assert(memory->bytes[42] == 0);
    c.give(r.handle);
    gGPUKeep = 1;
    c.drain();
    assert(live == 0);

    // Never recycle a buffer still named by an unfinished GPU submission.
    completed = 3;
    assert(c.gemNew(&r) == 0);
    auto *busyMemory = c.fBuffers[r.handle - 1].memory;
    c.fBuffers[r.handle - 1].fence = 4;
    c.give(r.handle);
    assert(c.fLeftCount == 1 && c.fKeptBytes == 0);
    assert(c.gemNew(&r) == 0 && c.fBuffers[r.handle - 1].memory != busyMemory);
    completed = 4;
    before = allocations;
    msm_gem_new completedRequest = {size, 0};
    assert(c.gemNew(&completedRequest) == 0);
    assert(c.fBuffers[completedRequest.handle - 1].memory == busyMemory);
    assert(c.fLeftCount == 0 && allocations == before);
    c.drain();
    assert(live == 0);

    // Surfaces belong to their surface owner, never to the temporary-buffer cache.
    assert(c.gemNew(&r) == 0);
    SweetSurface surface = {new IOMemoryDescriptor(16)};
    c.fBuffers[r.handle - 1].surface = &surface;
    c.give(r.handle);
    assert(c.fKeptBytes == 0 && surface.refs == 0);
    surface.memory->release();
    assert(live == 0);

    // Cache growth is bounded; oldest entries make room, and expired ones are released.
    for (unsigned n = 0; n < 5; ++n) {
        msm_gem_new big = {8u << 20, n};
        assert(c.gemNew(&big) == 0); c.give(big.handle);
        assert(c.fKeptBytes <= GPU_KEPT_BYTES);
    }
    assert(c.fKeptBytes == GPU_KEPT_BYTES && live == 4);
    now += (GPU_KEPT_SECONDS + 1) * NSEC_PER_SEC;
    assert(c.gemNew(&r) == 0 && live == 1 && c.fKeptBytes == 0);
    c.drain();

    // A failed contiguous allocation releases retained memory and retries once.
    assert(c.gemNew(&r) == 0); c.give(r.handle);
    assert(c.fKeptBytes == size);
    msm_gem_new required = {size * 2, 0};
    allocationFailuresRemaining = 1; before = allocations;
    assert(c.gemNew(&required) == 0 && allocations == before + 2);
    assert(c.fKeptBytes == 0 && gGPUStat.reclaimPasses == 1 && gGPUStat.reclaimed == size);
    c.drain();
    assert(live == 0);

    // Failed retry also releases the cache without publishing a handle.
    assert(c.gemNew(&r) == 0); c.give(r.handle);
    failAllocation = true; before = allocations;
    assert(c.gemNew(&required) == kIOReturnNoMemory && allocations == before + 2);
    assert(live == 0 && c.fKeptBytes == 0 && c.fBufferCount == 0);
    failAllocation = false;

    // Disabled cache releases buffers; allocation failure leaks no handle/descriptor.
    gGPUKeep = 0;
    assert(c.gemNew(&r) == 0); c.give(r.handle);
    assert(live == 0 && c.fKeptBytes == 0);
    failAllocation = true;
    assert(c.gemNew(&r) == kIOReturnNoMemory);
    assert(live == 0 && c.fBufferCount == 0 && lockDepth == 0);
    r.size = 0; assert(c.gemNew(&r) == kIOReturnBadArgument);
    r.size = GPU_BUFFER_MAX + 1ull; assert(c.gemNew(&r) == kIOReturnBadArgument);
    puts("PASS: reuse, isolation, flags/size, budgets, fences, surfaces, eviction, expiry and failures");
}
'''


def program(text):
    defines = text[text.index('#define GPU_BUFFERS '):text.index('static IOLock * gGPULock;')]
    # Only layout declarations are needed from this span.
    structs = text[text.index('struct gpu_buffer {'):text.index('static TUNABLE(uint32_t, gGPUKeep')]
    methods = []
    for signature in ['void\nRedwoodGPUUserClient::freeBuffer(', 'void\nRedwoodGPUUserClient::reap(',
                      'struct gpu_buffer *\nRedwoodGPUUserClient::newBuffer(',
                      'void\nRedwoodGPUUserClient::dropKept(', 'bool\nRedwoodGPUUserClient::keep(',
                      'IOReturn\nRedwoodGPUUserClient::gemNew(']:
        start = text.index(signature)
        end = text.index('\n}\n', start) + 3
        methods.append(text[start:end])
    return HARNESS.replace('/* DEFINES */', defines).replace('/* STRUCTS */', structs).replace('/* METHODS */', '\n'.join(methods))


def main():
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary)
        source = path / 'reuse.cpp'
        source.write_text(program(SOURCE.read_text()))
        binary = path / 'reuse'
        subprocess.run(['xcrun', 'clang++', '-std=c++17', '-fsanitize=address,undefined',
                        str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
