/* Opt-in CoreAnimation loader for the 20H392 arm64 cache. Candidate only.
 * Derived from the published Topaz loader's two GLESContext hooks; no process
 * injection, persona changes or crash-handler replacement happens here. */
#include <IOKit/IOKitLib.h>
#include <dlfcn.h>
#include <mach/mach.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/sysctl.h>

extern const void *_dyld_get_shared_cache_range(size_t *length);
static int (*original_supported)(void *);
static void (*original_uniform)(void *, unsigned, size_t, size_t, const float *);
static void (*refused)(unsigned);
static void (*values)(void *, unsigned, unsigned, size_t, size_t, const float *);

static int flag(const char *args, const char *wanted)
{
    size_t length = strlen(wanted);
    for (const char *p = args; *p;) {
        while (*p == ' ') { p++; }
        size_t n = strcspn(p, " ");
        if (n == length && !strncmp(p, wanted, n)) { return 1; }
        p += n;
    }
    return 0;
}

static unsigned function(void *context)
{
    return *(*(uint8_t **)((char *)context + 0x10) + 0x10);
}

static int supported(void *context)
{
    int result = original_supported(context);
    if (!result && refused) { refused(function(context)); }
    return result;
}

static void uniform(void *context, unsigned index, size_t components, size_t count, const float *data)
{
    values(context, function(context), index, components, count, data);
    original_uniform(context, index, components, count, data);
}

__attribute__((constructor))
static void start(void)
{
    char version[64] = "", args[2048] = "";
    size_t size = sizeof(version);
    if (!getprogname() || strcmp(getprogname(), "backboardd") ||
        sysctlbyname("kern.osversion", version, &size, NULL, 0) || strcmp(version, "20H392")) { return; }
    size = sizeof(args) - 1;
    if (sysctlbyname("kern.bootargs", args, &size, NULL, 0) ||
        !flag(args, "citrusgl=1") || flag(args, "gl=0")) { return; }
    io_service_t gpu = IOServiceGetMatchingService(0, IOServiceMatching("RedwoodGPU"));
    if (!gpu) { fprintf(stderr, "CitrusGL: no tested GPU service; software renderer retained\n"); return; }
    IOObjectRelease(gpu);
    size_t length = 0;
    const void *cache = _dyld_get_shared_cache_range(&length);
    if (!cache || length < 0x55b2fa88ull) { return; }
    uintptr_t slide = (uintptr_t)cache - 0x180000000ull;
    uintptr_t *a = (uintptr_t *)(0x1d5b2fa70ull + slide);
    uintptr_t *b = (uintptr_t *)(0x1d5b2fa80ull + slide);
    if (*a != 0x1884b2164ull + slide || *b != 0x1884b21acull + slide) {
        fprintf(stderr, "CitrusGL: GLES vtable differs from 20H392; not loaded\n"); return;
    }
    setenv("GALLIUM_DRIVER", "freedreno", 1);
    if (!dlopen("/System/Library/Frameworks/OpenGLES.framework/OpenGLES", RTLD_NOW | RTLD_GLOBAL)) {
        fprintf(stderr, "CitrusGL: OpenGLES load failed: %s\n", dlerror()); return;
    }
    void *library = dlopen("/citrus/lib/libcitrus-gl.dylib", RTLD_NOW);
    if (!library) { fprintf(stderr, "CitrusGL: library load failed: %s\n", dlerror()); return; }
    refused = dlsym(library, "redwood_gl_function_refused");
    values = dlsym(library, "redwood_gl_function_values");
    if (!refused || !values) { fprintf(stderr, "CitrusGL: missing shader bridge exports\n"); return; }
    vm_address_t page = (vm_address_t)a & ~(vm_address_t)(vm_page_size - 1);
    if (vm_protect(mach_task_self(), page, vm_page_size, FALSE,
                   VM_PROT_READ | VM_PROT_WRITE | VM_PROT_COPY) != KERN_SUCCESS) {
        fprintf(stderr, "CitrusGL: cannot protect private vtable page\n"); return;
    }
    original_supported = (void *)*a;
    original_uniform = (void *)*b;
    __sync_synchronize();
    *a = (uintptr_t)supported;
    *b = (uintptr_t)uniform;
    vm_protect(mach_task_self(), page, vm_page_size, FALSE, VM_PROT_READ);
    fprintf(stderr, "CitrusGL: EAGL loaded; 20H392 GLES shader hooks installed\n");
}
