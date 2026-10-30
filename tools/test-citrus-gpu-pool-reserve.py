#!/usr/bin/env python3
"""Run the real pool-reserve code against a fake contiguous allocator."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
src = (root / 'out/citrus-gpu/xnu/iokit/Kernel/arm/TopazAdreno.cpp').read_text()
part = src[src.index('#define GPU_POOL_MAX_BLOCKS'):src.index('static void pool_give_back(')]
prefix = r'''
#include <cassert>
#include <cstdint>
#include <cstdarg>
#include <vector>
#include <cstring>
using vm_size_t = uint64_t; using IOByteCount = uint64_t; using addr64_t = uint64_t;
struct IOLock {};
IOLock lock;
IOLock *IOLockAlloc() { return &lock; }
void IOLockLock(IOLock *) {} void IOLockUnlock(IOLock *) {}
void IOLog(const char *, ...) {}
const int kernel_task=0, kIODirectionInOut=1, kIOMemoryKernelUserShared=2,
 kIOMemoryPhysicallyContiguous=4, kIOMapWriteCombineCache=8, kIOMemoryMapperNone=0;
std::vector<uint64_t> requests; uint64_t max_success; unsigned made;
struct IOMemoryDescriptor {};
struct IOBufferMemoryDescriptor : IOMemoryDescriptor {
 IOBufferMemoryDescriptor(uint64_t n, uint64_t p, uint8_t *m) : length(n), pa(p), memory(m) {}
 uint64_t length, pa; uint8_t *memory;
 static IOBufferMemoryDescriptor *inTaskWithPhysicalMask(int,int,vm_size_t size,uint64_t) {
  requests.push_back(size); return size <= max_success ? new IOBufferMemoryDescriptor(size, 0x88000000ull + (made++ * (64ull << 20)), new uint8_t[size]) : nullptr;
 }
 addr64_t getPhysicalSegment(int, IOByteCount *len, int) { *len=length; return pa; }
 void *getBytesNoCopy() { return memory; }
 void release() { delete[] memory; delete this; }
};
IOMemoryDescriptor *last_parent; uint64_t last_offset;
struct IOSubMemoryDescriptor { static IOMemoryDescriptor *withSubRange(IOMemoryDescriptor *p, uint64_t o, uint64_t, int) { last_parent=p; last_offset=o; return p; } };
#define OSSafeReleaseNULL(p) do { if (p) { (p)->release(); (p)=nullptr; } } while (0)
'''
suffix = r'''
void reset(uint32_t requested, uint64_t max) {
 if (gpu_pool_md) gpu_pool_md->release(); if (gpu_pool_md2) gpu_pool_md2->release();
 gpu_pool_md=nullptr; gpu_pool_md2=nullptr; gpu_pool_lock=nullptr; gpu_pool_tried=false; gpu_pool_count=0;
 gpu_pool_requested_mb=requested; requests.clear(); max_success=max; made=0;
}
int main() {
 const uint64_t M=1ull<<20; void *va=nullptr;
 reset(64,64*M); assert(gpu_pool_reserve()); assert(gpu_pool_total==64*M); assert(requests.size()==1);
 reset(128,64*M); assert(gpu_pool_reserve()); assert(gpu_pool_total==64*M && gpu_pool_size2==64*M); assert(requests.size()==2);
 uint64_t a=gpu_pool_alloc(64*M,&va), b=gpu_pool_alloc(64*M,&va);
 assert(a==0x88000000 && b==0x8c000000 && va==gpu_pool_va2);
 assert(topaz_gpu_pool_md(a+0x4000,0x4000)==gpu_pool_md && last_offset==0x4000);
 assert(topaz_gpu_pool_md(b+0x8000,0x4000)==gpu_pool_md2 && last_offset==0x8000);
 assert(topaz_gpu_pool_md(b+64*M-0x4000,0x8000)==nullptr);
 gpu_pool_give_back(a,64*M); gpu_pool_give_back(b,64*M);
 assert(gpu_pool_count==2 && gpu_pool_blocks[0].arena!=gpu_pool_blocks[1].arena);
 assert(gpu_pool_alloc(80*M,&va)==0); // adjacent arenas must never merge
 reset(128,16*M); assert(gpu_pool_reserve()); assert(gpu_pool_total==16*M && gpu_pool_size2==16*M); assert(requests.size()==6);
 reset(128,0); assert(!gpu_pool_reserve()); assert(requests.size()==3); assert(!gpu_pool_reserve()); assert(requests.size()==3);
 reset(64,0);
}
'''
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / 'test.cpp'; p.write_text(prefix + part + suffix)
    exe = Path(d) / 'test'
    subprocess.run(['clang++','-std=c++17','-fsanitize=address,undefined',str(p),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('GPU pool reserve, fallback, allocation and arena isolation cases passed')
