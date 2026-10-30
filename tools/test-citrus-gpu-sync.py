#!/usr/bin/env python3
"""Run the retained driver's CPU-prep method against independent buffer fences.

Host-only regression for the quarantined perf2 candidate. Its hardware boot
failed visual verification; passing these checks does not validate that boot.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'out/citrus-gpu-performance2/xnu/iokit/Kernel/arm/RedwoodGPU.cpp'

HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
using IOReturn = int;
constexpr int kIOReturnSuccess = 0, kIOReturnBadArgument = 1, kIOReturnBusy = 2;
constexpr unsigned MSM_PREP_NOSYNC = 4;
struct msm_timespec { uint64_t ms; };
struct msm_gem_cpu_prep { uint32_t handle, op; msm_timespec timeout; };
struct gpu_buffer { uint32_t fence; } buffers[2];
struct { uint32_t preps, prepIdle; } gGPUStat;
void *gGPULock;
int lockDepth, waits, expired;
uint32_t waitedFence, completedFence;
uint64_t waitedMs;
bool invalidateBuffer;
void IOLockLock(void *) { assert(lockDepth == 0); ++lockDepth; }
void IOLockUnlock(void *) { assert(lockDepth == 1); --lockDepth; }
uint64_t millisecondsUntil(const msm_timespec *t) { return t->ms; }
bool gpuWait(uint32_t fence, uint64_t ms) {
    assert(lockDepth == 1);
    ++waits; waitedFence = fence; waitedMs = ms;
    if (invalidateBuffer) buffers[0].fence = 0xdead;
    return fence <= completedFence;
}
void waitOver(const msm_timespec *, uint32_t fence) {
    ++expired; assert(fence == waitedFence);
}
// The unrelated latest submission stays busy throughout these tests.
uint32_t redwood_gpu_last() { return 999; }
class RedwoodGPUUserClient {
public:
    gpu_buffer *buffer(uint32_t handle) {
        return handle >= 1 && handle <= 2 ? &buffers[handle - 1] : nullptr;
    }
    IOReturn cpuPrep(msm_gem_cpu_prep *request);
};
/* CPU_PREP */
int main() {
    RedwoodGPUUserClient client;
    msm_gem_cpu_prep request = {1, 0, {100}};
    buffers[0].fence = 0;
    assert(client.cpuPrep(&request) == kIOReturnSuccess);
    assert(waits == 0 && gGPUStat.prepIdle == 1 && lockDepth == 0);

    // A completed buffer must not wait for unrelated submission 999.
    buffers[0].fence = completedFence = 7;
    assert(client.cpuPrep(&request) == kIOReturnSuccess);
    assert(waits == 1 && waitedFence == 7 && waitedMs == 100 && lockDepth == 0);

    // Busy memory remains protected, including nonblocking CPU access.
    buffers[0].fence = 8; request.op = MSM_PREP_NOSYNC;
    assert(client.cpuPrep(&request) == kIOReturnBusy);
    assert(waitedFence == 8 && waitedMs == 0 && expired == 0 && lockDepth == 0);

    // Expired blocking requests report the requested buffer's fence.
    request.op = 0; request.timeout.ms = 0; invalidateBuffer = true;
    assert(client.cpuPrep(&request) == kIOReturnBusy);
    assert(expired == 1 && waitedFence == 8 && lockDepth == 0);
    invalidateBuffer = false;

    // Handle validation must not prepare arbitrary memory.
    request.handle = 0;
    auto before = waits;
    assert(client.cpuPrep(&request) == kIOReturnBadArgument);
    request.handle = 3;
    assert(client.cpuPrep(&request) == kIOReturnBadArgument);
    assert(waits == before && lockDepth == 0);

    // Independent handles have independent dependencies.
    buffers[1].fence = 6; request.handle = 2; request.timeout.ms = 20;
    assert(client.cpuPrep(&request) == kIOReturnSuccess);
    assert(waitedFence == 6 && waitedMs == 20 && lockDepth == 0);
    puts("PASS: idle/completed/busy/expired/invalid/independent buffer CPU prep");
}
'''


def main():
    text = SOURCE.read_text()
    start = text.index('IOReturn\nRedwoodGPUUserClient::cpuPrep(')
    end = text.index('\nIOReturn\n', start + len('IOReturn\n'))
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        source = directory / 'sync.cpp'
        source.write_text(HARNESS.replace('/* CPU_PREP */', text[start:end]))
        binary = directory / 'sync'
        subprocess.run(['xcrun', 'clang++', '-std=c++17', '-fsanitize=address,undefined',
                        str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
