#!/usr/bin/env python3
"""Host-test the actual SMMU scatter diagnostic's mapping and fence checks."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'out/citrus-gpu/xnu/iokit/Kernel/arm/TopazAdreno.cpp').read_text()
a=s.index('static struct kbuf citrus_smmu_page[2];'); b=s.index('/* ---------------------------------------------------------------- start */',a)
prefix=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#define PAGE_SIZE 16384u
#define IOLog(...) ((void)0)
using vm_offset_t=uintptr_t;
struct kbuf { void *md; uint8_t *va; uint64_t pa, iova; };
static uint8_t storage[2][PAGE_SIZE], ib_mem[PAGE_SIZE];
static kbuf selftest_ib{(void*)1,ib_mem,0,0xf0000000};
static bool gpu_identity, fail_map, complete=true, bad_value=false;
static int nalloc, nmaps, unmapped, freed; static uint64_t phys[2], maps[8];
bool kbuf_alloc(kbuf *b, uint64_t) { if (nalloc>=2) return false; b->md=(void*)1;b->va=storage[nalloc];b->pa=phys[nalloc++];return true; }
uint64_t redwood_gpu_address(uint64_t size) { assert(size==2*PAGE_SIZE);return 0x1000000; }
bool redwood_gpu_map(uint64_t va,uint64_t pa,bool) { assert(va==0x1000000ull+nmaps*4096); if(fail_map && nmaps==3) return false; maps[nmaps++]=pa;return true; }
void redwood_gpu_unmap(uint64_t,uint64_t) { unmapped++; } void redwood_gpu_address_free(uint64_t,uint64_t) { freed++; }
void redwood_gpu_mapped() {} void sweet_dcache_clean(vm_offset_t,unsigned) {} void sweet_dcache_flush(vm_offset_t,unsigned) {}
uint32_t pkt7(uint32_t, uint32_t) { return 0x12345678; }
uint32_t redwood_gpu_submit(uint64_t *a,uint32_t *n,int count) {
 assert(*a==selftest_ib.iova && *n==8 && count==1);
 auto ib=(uint32_t*)ib_mem; assert(ib[1]==0x1000000 && ib[5]==0x1004000);
 for (int i=0;i<2;i++) for(int j=0;j<2;j++) if(maps[i*4]==phys[j]) *(uint32_t*)storage[j]=ib[i*4+3];
 if(bad_value) *(uint32_t*)storage[0]=0; return 7;
}
bool redwood_gpu_done(uint32_t) { return complete; } void IOSleep(unsigned) {}
'''
suffix=r'''
void reset() { nalloc=nmaps=unmapped=freed=0;gpu_identity=false;fail_map=false;complete=true;bad_value=false;memset(storage,0,sizeof(storage)); }
int main() {
 reset(); phys[0]=0x88000000;phys[1]=0x88004000;assert(citrus_smmu_scatter_test());assert(maps[0]==phys[1] && maps[4]==phys[0] && nmaps==8);
 reset(); phys[0]=0x88000000;phys[1]=0x89000000;assert(citrus_smmu_scatter_test());assert(maps[0]==phys[0] && maps[4]==phys[1]);
 reset(); fail_map=true;assert(!citrus_smmu_scatter_test());assert(unmapped==1 && freed==1);
 reset(); complete=false;assert(!citrus_smmu_scatter_test());assert(unmapped==0 && freed==0);
 reset(); bad_value=true;assert(!citrus_smmu_scatter_test());
 reset(); gpu_identity=true;assert(!citrus_smmu_scatter_test());assert(nalloc==0);
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d)/'test.cpp';p.write_text(prefix+s[a:b]+suffix);exe=Path(d)/'test'
 subprocess.run(['clang++','-std=c++17','-fsanitize=address,undefined',str(p),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
print('SMMU scatter mapping, noncontiguous ordering, cleanup and fence tests passed')
