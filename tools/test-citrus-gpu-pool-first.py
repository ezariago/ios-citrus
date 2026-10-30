#!/usr/bin/env python3
"""Test the real identity allocation branch and pool/low-memory ownership."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
s = (root / 'out/citrus-gpu/xnu/iokit/Kernel/arm/RedwoodGPU.cpp').read_text()
a = s.index('\tif (redwood_gpu_identity()) {', s.index('RedwoodGPUUserClient::gemNew('))
b = s.index('\n\tmemory = IOBufferMemoryDescriptor::inTaskWithOptions', a)
branch = s[a:b]
prefix = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
using vm_size_t=uint64_t; using IOReturn=int;
const int kIOReturnSuccess=0,kIOReturnNoMemory=1,kIODirectionInOut=1,kIOMemoryKernelUserShared=2,kIOMemoryPhysicallyContiguous=4,kIOMapWriteCombineCache=8;
void *kernel_task, *gGPULock;
uint32_t gPoolFirst; bool poolAvailable,lowAvailable,newAvailable; int poolCalls,lowCalls,freeCalls,releases,depth; uint64_t now=1;
uint8_t bytes[2 << 20]; struct IOMemoryDescriptor { void release() { releases++; } };
struct IOBufferMemoryDescriptor : IOMemoryDescriptor {
 static IOBufferMemoryDescriptor *inTaskWithPhysicalMask(void*,int,uint64_t,uint64_t) { ++lowCalls; static IOBufferMemoryDescriptor low; return lowAvailable ? &low : nullptr; }
 void *getBytesNoCopy() { return bytes; }
};
struct gpu_buffer { IOMemoryDescriptor *memory; uint8_t *kernel; } buffer;
struct msm_gem_new { uint64_t size; uint32_t flags,handle; };
struct { int made; } gGPUStat;
void IOLockLock(void*) { assert(depth==0); depth++; } void IOLockUnlock(void*) { assert(depth==1); depth--; }
bool redwood_gpu_identity() { return true; } bool topaz_gpu_midmem() { return true; }
uint64_t mach_absolute_time() { return now++; }
void absolutetime_to_nanoseconds(uint64_t n, uint64_t *p) { *p=n; }
uint64_t topaz_gpu_pool_alloc(uint64_t, void **v) { poolCalls++; if (!poolAvailable) return 0; *v=bytes; return 0x10000; }
IOMemoryDescriptor *topaz_gpu_pool_md(uint64_t,uint64_t) { static IOMemoryDescriptor p; return &p; }
void redwood_gpu_address_free(uint64_t p,uint64_t) { assert(p==0x10000); freeCalls++; }
bool citrus_gpu_pool_sample(uint64_t,bool,uint64_t*,uint64_t*,unsigned*,uint64_t*,uint64_t*) { return false; }
#define IOLog(...) ((void)0)
#define bzero(p,n) memset(p,0,n)
#define OSSafeReleaseNULL(p) do { if (p) { (p)->release(); (p)=nullptr; } } while(0)
gpu_buffer *newBuffer(IOMemoryDescriptor*,int,uint64_t,uint32_t,uint32_t*) { return newAvailable ? &buffer : nullptr; }
IOReturn run(msm_gem_new *request) { uint64_t size=request->size; gpu_buffer *b;
'''
suffix = r'''
 return 99; }
void reset(bool first,bool pool,bool low,bool slot) { gPoolFirst=first;poolAvailable=pool;lowAvailable=low;newAvailable=slot;poolCalls=lowCalls=freeCalls=releases=depth=0; }
int main() { msm_gem_new r{2 << 20,0,0};
 reset(true,true,true,true); assert(run(&r)==0 && poolCalls==1 && lowCalls==0 && buffer.kernel==bytes);
 reset(true,false,true,true); assert(run(&r)==0 && poolCalls==1 && lowCalls==1 && freeCalls==0);
 reset(true,false,false,true); assert(run(&r)==1 && poolCalls==1 && lowCalls==1);
 reset(true,true,true,false); assert(run(&r)==1 && poolCalls==1 && lowCalls==0 && freeCalls==1 && releases==1 && depth==0);
 reset(false,true,true,true); assert(run(&r)==0 && lowCalls==1 && poolCalls==0);
 reset(false,true,false,true); assert(run(&r)==0 && lowCalls==1 && poolCalls==1);
 reset(false,false,false,true); assert(run(&r)==1 && lowCalls==1 && poolCalls==1);
 reset(true,false,true,false); assert(run(&r)==1 && lowCalls==1 && releases==1 && freeCalls==0 && depth==0);
 r.size=16384; reset(true,true,true,true); assert(run(&r)==0 && lowCalls==1 && poolCalls==0);
}
'''
with tempfile.TemporaryDirectory() as d:
    src=Path(d)/'test.cpp'; src.write_text(prefix+branch+suffix); exe=Path(d)/'test'
    subprocess.run(['clang++','-std=c++17','-fsanitize=address,undefined',str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('Pool-first and low-first allocation, fallback and ownership tests passed')
