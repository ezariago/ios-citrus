#!/usr/bin/env python3
"""Exercise the driver's real SMMU layout validation.

The vendor arm-smmu driver places context banks at half the mapped register
window (cb_base = base + resource_size(res) / 2); IDR1 only supplies the
register page size used for the GR1 page and the context-bank stride.
"""
from pathlib import Path
import subprocess, tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'out/citrus-gpu/xnu/iokit/Kernel/arm/TopazAdreno.cpp').read_text()
a=s.index('static bool\ncitrus_smmu_layout(');b=s.index('static uint32_t\nsmmu_cb_stride(',a)
test='''
#include <cassert>
#include <cstdint>
'''+s[a:b]+'''
int main() {
 uint32_t p=0,c=0;
 /* 4 KB register pages, 64 KiB window: CB0 at 0x8000, GR1 at 0x1000. */
 assert(citrus_smmu_layout(0x4c010e04u,0x10000,&p,&c) && p==0x1000 && c==0x8000);
 assert(citrus_smmu_layout(0x4c017e04u,0x10000,&p,&c) && p==0x1000 && c==0x8000);
 /* 64 KB register pages need a 128 KiB window. */
 assert(citrus_smmu_layout(0x80010e04u,0x20000,&p,&c) && p==0x10000 && c==0x10000);
 assert(!citrus_smmu_layout(0x80010e04u,0x10000,&p,&c));
 /* Degenerate windows fail closed. */
 assert(!citrus_smmu_layout(0,0x10001,&p,&c));
 assert(!citrus_smmu_layout(0,0x1000,&p,&c));
 assert(!citrus_smmu_layout(0,0x1008,&p,&c));
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d)/'test.cpp'; p.write_text(test); exe=Path(d)/'test'
 subprocess.run(['clang++','-std=c++17','-fsanitize=address,undefined',str(p),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
print('SMMU layout bounds and IDR1 page-size decoding passed')
