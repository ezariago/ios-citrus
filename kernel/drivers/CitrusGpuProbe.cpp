/* Read-only Citrus GPU/SCM diagnostic, independent of the GPU backport.
 * Keeps the baseline framebuffer, IOSurface and input implementations intact.
 * No firmware authentication, power/clock writes, SMMU setup or GPU commands. */
#include <IOKit/IOLib.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>

extern "C" vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern "C" void citrus_gpu_probe_init(void);

static void query(const char *name, uint64_t fn, uint64_t info, uint64_t argument)
{
    register uint64_t x0 __asm__("x0") = fn;
    register uint64_t x1 __asm__("x1") = info;
    register uint64_t x2 __asm__("x2") = argument;
    register uint64_t x3 __asm__("x3") = 0;
    register uint64_t x4 __asm__("x4") = 0;
    register uint64_t x5 __asm__("x5") = 0;
    register uint64_t x6 __asm__("x6") = 0;
    register uint64_t x7 __asm__("x7") = 0;
    __asm__ volatile("smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3),
        "+r"(x4), "+r"(x5), "+r"(x6), "+r"(x7) : :
        "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory");
    IOLog("CitrusGPU probe2: %s fn=%llx arg=%llx -> %llx/%llx/%llx/%llx x6=%llx\n",
        name, fn, argument, x0, x1, x2, x3, x6);
}

static void probe(__unused void *parameter, __unused wait_result_t result)
{
    IOSleep(15000);
    volatile uint8_t *cc = (volatile uint8_t *)ml_io_map(0x05990000, 0x9000);
    if (!cc) { IOLog("CitrusGPU probe2: GPUCC map failed\n"); return; }
    uint64_t el, affinity;
    __asm__ volatile("mrs %0, CurrentEL" : "=r"(el));
    __asm__ volatile("mrs %0, MPIDR_EL1" : "=r"(affinity));
    IOLog("CitrusGPU probe2: EL=%llu MPIDR=%llx GX=%08x CX=%08x GFX=%08x SMMUCLK=%08x\n",
        el >> 2, affinity, *(volatile uint32_t *)(cc + 0x100c), *(volatile uint32_t *)(cc + 0x1540),
        *(volatile uint32_t *)(cc + 0x1054), *(volatile uint32_t *)(cc + 0x5000));
    query("SMCCC_VERSION", 0x80000000, 0, 0);
    query("PSCI_VERSION", 0x84000000, 0, 0);
    query("INFO64_self", 0x42000601, 1, 0x02000601);
    query("INFO64_PIL7", 0x42000601, 1, 0x02000207);
    query("INFO32_self", 0x02000601, 1, 0x02000601);
    query("INFO32_PIL7", 0x02000601, 1, 0x02000207);
    query("PAS64_GPU13", 0x42000207, 1, 13);
    query("PAS32_GPU13", 0x02000207, 1, 13);
    query("PAS64_MODEM1", 0x42000207, 1, 1);
    IOLog("CitrusGPU probe2: finished queries; baseline display/input retained\n");
}

void citrus_gpu_probe_init(void)
{
    uint32_t on = 0;
    if (!PE_parse_boot_argn("citrusgpuprobe", &on, sizeof(on)) || !on) { return; }
    thread_t thread;
    if (kernel_thread_start(probe, NULL, &thread) == KERN_SUCCESS) { thread_deallocate(thread); }
}
