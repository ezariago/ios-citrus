#!/usr/bin/env python3
"""Exercise the real fence-wait policy with deterministic completion/scheduling.

Host-only: checks timeout, lock and polling bounds, not GPU/cache correctness.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'out/citrus-gpu/xnu/iokit/Kernel/arm/RedwoodGPU.cpp'
HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
constexpr uint64_t NSEC_PER_MSEC = 1000000, NSEC_PER_USEC = 1000;
constexpr unsigned GPU_FAST_POLL_US = 2000, GPU_POLL_STEP_US = 20, GPU_ASK_AGAIN_US = 200;
struct Stats {
    uint32_t waits = 0, fastWaits = 0, blockedWaits = 0;
    uint64_t waiting = 0, sleepCalls = 0, slept = 0;
} gGPUStat;
void *gGPULock;
bool gGPUReported;
uint64_t clockNS, completion, sleepPenalty;
unsigned lockDepth = 1, sleeps, pauses, reports;
uint64_t mach_absolute_time() { return clockNS; }
void nanoseconds_to_absolutetime(uint64_t n, uint64_t *out) { *out = n; }
void IOLockUnlock(void *) { assert(lockDepth == 1); --lockDepth; }
void IOLockLock(void *) { assert(lockDepth == 0); ++lockDepth; }
bool redwood_gpu_done(uint32_t) { assert(lockDepth == 1); return clockNS >= completion; }
void gpu_poll_pause() { assert(lockDepth == 0); ++pauses; clockNS += 1000; }
void delay_for_interval(unsigned interval, uint64_t scale) {
    assert(lockDepth == 0); assert(clockNS >= GPU_FAST_POLL_US * NSEC_PER_USEC);
    ++sleeps; clockNS += interval * scale + sleepPenalty;
}
void redwood_gpu_report(const char *) { ++reports; }
/* WAIT */
void reset(uint64_t readyAt, uint64_t penalty = 0) {
    clockNS = sleeps = pauses = reports = 0;
    completion = readyAt; sleepPenalty = penalty; lockDepth = 1;
    gGPUReported = false; gGPUStat = {};
}
int main() {
    reset(0);
    assert(gpuWait(1, 100));
    assert(clockNS == 0 && pauses == 0 && sleeps == 0 && lockDepth == 1);

    // Nonblocking queries do not become active polls or scheduler waits.
    reset(800000, 15000000);
    assert(!gpuWait(1, 0));
    assert(pauses == 0 && sleeps == 0 && !gGPUReported && lockDepth == 1);

    // A normal short completion avoids the simulated 15 ms wake penalty.
    reset(800000, 15000000);
    assert(gpuWait(1, 100));
    assert(clockNS >= completion && clockNS < 2000000 && sleeps == 0);
    assert(gGPUStat.fastWaits == 1 && gGPUStat.blockedWaits == 0 && lockDepth == 1);

    // Long waits fall back to scheduling, never spin past the 2 ms budget.
    reset(4000000, 15000000);
    assert(gpuWait(1, 100));
    assert(pauses <= 2000 && sleeps == 1 && gGPUStat.sleepCalls == 1);
    assert(gGPUStat.slept == 15200000 && gGPUStat.blockedWaits == 1 && lockDepth == 1);

    // A shorter caller deadline also bounds the polling window.
    reset(3000000);
    assert(!gpuWait(1, 1));
    assert(clockNS == 1000000 && pauses <= 1000 && sleeps == 0 && lockDepth == 1);

    // Existing long-timeout fault reporting still works.
    reset(UINT64_MAX, 100000000);
    assert(!gpuWait(1, 1000));
    assert(gGPUReported && reports == 1 && pauses <= 2000 && sleeps > 0 && lockDepth == 1);
    puts("PASS: completion, nonblocking, fast/blocked waits, deadline, lock and fault bounds");
}
'''


def main():
    text = SOURCE.read_text()
    start = text.index('static bool\ngpuWait(')
    end = text.index('\n/* the display waits', start)
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        source = directory / 'wait.cpp'
        source.write_text(HARNESS.replace('/* WAIT */', text[start:end]))
        binary = directory / 'wait'
        subprocess.run(['xcrun', 'clang++', '-std=c++17', '-fsanitize=address,undefined',
                        str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
