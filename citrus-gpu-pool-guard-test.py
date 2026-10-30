#!/usr/bin/env python3
"""Host test for experimental kernel pool policy; no phone or image writes."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'out/citrus-8core/ci-run-40531392449/tree/xnu/iokit/Kernel/arm/TopazAdreno.cpp'
PATCH = ROOT / 'citrus-gpu-pool-guard-experiment.patch'

PREAMBLE = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#define GPU_POOL_MAX_BLOCKS 256
struct gpu_pool_block { uint64_t base, size; bool used; unsigned arena; };
static gpu_pool_block gpu_pool_blocks[GPU_POOL_MAX_BLOCKS];
static unsigned gpu_pool_count;
static uint32_t gpu_pool_guard;
static uint8_t *gpu_pool_va, *gpu_pool_va2;
static uint64_t gpu_pool_pa=0x80000000, gpu_pool_pa2=0x84000000;
static void *gpu_pool_lock, *gpu_pool_md=(void *)1;
static bool gpu_pool_reserve(){return true;}
static void IOLockLock(void *){}
static void IOLockUnlock(void *){}
'''
TESTS = r'''
static constexpr uint64_t M=1024ull*1024;
static void init() {
    gpu_pool_count=2;
    gpu_pool_blocks[0]={gpu_pool_pa,64*M,false,0};
    gpu_pool_blocks[1]={gpu_pool_pa2,64*M,false,1};
}
static void validate(){
    assert(gpu_pool_count<=GPU_POOL_MAX_BLOCKS);
    uint64_t totals[2]={0,0}, expected[2]={gpu_pool_pa,gpu_pool_pa2};
    for(unsigned i=0;i<gpu_pool_count;i++){
        auto &b=gpu_pool_blocks[i]; assert(b.arena<2 && b.size && !(b.size&0x3fff));
        assert(b.base==expected[b.arena]); expected[b.arena]+=b.size; totals[b.arena]+=b.size;
        if(i && gpu_pool_blocks[i-1].arena==b.arena) assert(b.base==gpu_pool_blocks[i-1].base+gpu_pool_blocks[i-1].size);
    }
    assert(totals[0]==64*M && totals[1]==64*M);
}
int main(){
    gpu_pool_va=(uint8_t*)malloc(64*M); gpu_pool_va2=(uint8_t*)malloc(64*M);
    assert(gpu_pool_va && gpu_pool_va2);
    for(unsigned mode=0;mode<=1;mode++){
        gpu_pool_guard=mode; init(); void *va=nullptr;
        auto a=gpu_pool_alloc(10*M,&va); assert(a==gpu_pool_pa && va==gpu_pool_va);
        auto b=gpu_pool_alloc(3*M,&va); assert(b && va);
        gpu_pool_give_back(a,10*M); gpu_pool_give_back(b,3*M); validate();
        assert(gpu_pool_count==2 && gpu_pool_blocks[0].size==64*M && gpu_pool_blocks[1].size==64*M);
        uint64_t addresses[120]={}; uint32_t rng=1234567;
        for(unsigned step=0;step<10000;step++){
            rng=rng*1664525u+1013904223u; unsigned slot=rng%120;
            if(addresses[slot]) {gpu_pool_give_back(addresses[slot],0); addresses[slot]=0;}
            else {rng=rng*1664525u+1013904223u; addresses[slot]=gpu_pool_alloc(((rng%48)+1)*0x4000ull,nullptr);}
            validate();
        }
        for(auto addr:addresses) if(addr) gpu_pool_give_back(addr,0);
        validate(); assert(gpu_pool_count==2);
    }
    /* First-fit wastes a 12 MiB hole on a 3 MiB request; guarded best-fit
       uses the 6 MiB hole, preserving the 12 MiB hole for a 10 MiB request. */
    for(unsigned mode=0;mode<=1;mode++) {
        gpu_pool_guard=mode; gpu_pool_count=3;
        gpu_pool_blocks[0]={gpu_pool_pa,12*M,false,0};
        gpu_pool_blocks[1]={gpu_pool_pa+12*M,1*M,true,0};
        gpu_pool_blocks[2]={gpu_pool_pa+13*M,6*M,false,0};
        uint64_t small=gpu_pool_alloc(3*M,nullptr); assert(small==(mode?gpu_pool_pa+13*M:gpu_pool_pa));
        uint64_t big=gpu_pool_alloc(10*M,nullptr); assert(mode ? big==gpu_pool_pa : big==0);
    }
    /* Last 10 MiB block is protected from a small allocation when no other hole fits. */
    gpu_pool_guard=1; gpu_pool_count=1; gpu_pool_blocks[0]={gpu_pool_pa,10*M,false,0};
    assert(gpu_pool_alloc(1*M,nullptr)==0); assert(gpu_pool_alloc(10*M,nullptr)==gpu_pool_pa);
    /* When the metadata table is full even a fitting large hole cannot split. */
    gpu_pool_count=GPU_POOL_MAX_BLOCKS;
    for(unsigned i=0;i<gpu_pool_count;i++) gpu_pool_blocks[i]={gpu_pool_pa+i*0x4000ull,0x4000,true,0};
    gpu_pool_blocks[0]={gpu_pool_pa,20*M,false,0};
    assert(gpu_pool_alloc(1*M,nullptr)==0);
    free(gpu_pool_va); free(gpu_pool_va2);
    puts("PASS: default first-fit, guarded best-fit, reserve, exhaustion, 20k random operations, cross-arena coalescing");
}
'''

def between(text, begin, end):
    start = text.index(begin)
    return text[start:text.index(end, start)]


def main():
    # The working file is already patched: first reverse it in a private copy,
    # then apply the patch to prove both directions and test its real functions.
    with tempfile.TemporaryDirectory(prefix='citrus-pool-test-') as tmp:
        d = Path(tmp)
        target = d / 'iokit/Kernel/arm/TopazAdreno.cpp'
        target.parent.mkdir(parents=True)
        shutil.copyfile(SOURCE, target)
        for reverse in (True, False):
            cmd=['patch', '--batch', '-p1', '-i', str(PATCH)]
            if reverse: cmd.insert(2, '-R')
            subprocess.run(cmd, cwd=d, check=True)
        source=target.read_text()
        selection=between(source, '/* Caller holds gpu_pool_lock.', '/* Snapshot under the allocator lock;')
        release=between(source, 'static void\ngpu_pool_give_back(', 'extern "C" bool topaz_gpu_midmem')
        (d/'test.cpp').write_text(PREAMBLE+selection+release+TESTS)
        subprocess.run(['clang++','-std=c++17','-O1','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
                        '-fsanitize=address,undefined',str(d/'test.cpp'),'-o',str(d/'test')],check=True)
        subprocess.run([str(d/'test')],check=True)

if __name__ == '__main__':
    main()
