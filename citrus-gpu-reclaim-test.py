#!/usr/bin/env python3
"""Exercise the real reclaim method and arena ownership on a host, not the phone."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parent
SRC=ROOT/'out/citrus-8core/ci-run-40531392449/tree/xnu/iokit/Kernel/arm'
PATCH=ROOT/'citrus-gpu-reclaim-experiment.patch'
PRE=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdarg>
static void *gpu_pool_md=(void *)1, *gpu_pool_md2=(void *)2;
static uint64_t gpu_pool_pa=0x10000000, gpu_pool_pa2=0x20000000;
static uint64_t gpu_pool_total=64ull<<20, gpu_pool_size2=64ull<<20;
'''
MIDDLE=r'''
#define GPU_KEPT 48
struct gpu_kept { void *memory; uint64_t address, size, since; };
static bool locked=false; static void *gGPULock;
static uint64_t released[GPU_KEPT]; static unsigned drops, need, allocations;
static void IOLockLock(void *){assert(!locked);locked=true;}
static void IOLockUnlock(void *){assert(locked);locked=false;}
static uint64_t topaz_gpu_pool_alloc(uint64_t, void **va){
 assert(locked); allocations++; if(drops<need)return 0; if(va)*va=(void*)1; return 0xdead0000;
}
static void IOLog(const char *, ... ){}
class RedwoodGPUUserClient {public:
 gpu_kept fKept[GPU_KEPT]={};
 void dropKept(gpu_kept *k){assert(locked && k->memory);released[drops++]=k->address;k->memory=nullptr;}
 uint64_t reclaimPool(uint64_t,void **);
};
'''
TEST=r'''
int main(){
 assert(topaz_gpu_pool_owns(gpu_pool_pa));
 assert(topaz_gpu_pool_owns(gpu_pool_pa+gpu_pool_total-1));
 assert(!topaz_gpu_pool_owns(gpu_pool_pa+gpu_pool_total));
 assert(!topaz_gpu_pool_owns(gpu_pool_pa-1));
 assert(topaz_gpu_pool_owns(gpu_pool_pa2));
 assert(!topaz_gpu_pool_owns(gpu_pool_pa2+gpu_pool_size2));
 gpu_pool_md2=nullptr; assert(!topaz_gpu_pool_owns(gpu_pool_pa2)); gpu_pool_md2=(void*)2;
 RedwoodGPUUserClient c;
 c.fKept[0]={(void*)1,gpu_pool_pa+0x4000,4,30};
 c.fKept[1]={(void*)1,gpu_pool_pa2+0x4000,4,10};
 c.fKept[2]={(void*)1,0x30000000,4,1}; // oldest but outside pool
 c.fKept[3]={(void*)1,gpu_pool_pa+0x8000,4,20};
 drops=allocations=0; need=2; void *va=nullptr;
 assert(c.reclaimPool(100,&va)==0xdead0000 && va==(void*)1);
 assert(drops==2 && allocations==2 && released[0]==gpu_pool_pa2+0x4000 && released[1]==gpu_pool_pa+0x8000);
 assert(c.fKept[0].memory && c.fKept[2].memory && !locked);
 drops=allocations=0; need=9; va=nullptr;
 assert(c.reclaimPool(100,&va)==0 && va==nullptr);
 assert(drops==1 && allocations==1 && released[0]==gpu_pool_pa+0x4000);
 assert(c.fKept[2].memory && !locked);
 drops=allocations=0; assert(c.reclaimPool(100,&va)==0 && drops==0 && allocations==0);
 puts("PASS: arena boundaries, oldest-first, pool-only, stop-on-success, exhausted/empty and lock pairing");
}
'''

def section(s,a,b):
    x=s.index(a); return s[x:s.index(b,x)]

def main():
    with tempfile.TemporaryDirectory(prefix='citrus-reclaim-test-') as tmp:
        d=Path(tmp)
        for name in ('TopazAdreno.cpp','RedwoodGPU.cpp'):
            p=d/'iokit/Kernel/arm'/name; p.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(SRC/name,p)
        for reverse in (True,False):
            cmd=['patch','--batch','-p1','-i',str(PATCH)]
            if reverse:cmd.insert(2,'-R')
            subprocess.run(cmd,cwd=d,check=True)
        a=(d/'iokit/Kernel/arm/TopazAdreno.cpp').read_text()
        b=(d/'iokit/Kernel/arm/RedwoodGPU.cpp').read_text()
        owns=section(a,'extern "C" bool topaz_gpu_pool_owns','/* boot-arg gpu_identity')
        reclaim=section(b,'/* Only the allocating client\'s completed pool-backed cache','/* With the lock held, the GPU done with the buffer: kept')
        (d/'test.cpp').write_text(PRE+owns+MIDDLE+reclaim+TEST)
        subprocess.run(['clang++','-std=c++17','-O1','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(d/'test.cpp'),'-o',str(d/'test')],check=True)
        subprocess.run([str(d/'test')],check=True)

if __name__=='__main__':main()
