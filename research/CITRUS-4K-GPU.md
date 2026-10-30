# 4 KiB / 7-core port: the Adreno 610 came up, the compositor still stalls

Updated 2026-10-29 02:50 (Asia/Jakarta).

This note is the state of the GPU on the `out/citrus-8core` (4 KiB page, 7-core
SM6115) port. The GPU itself is **no longer the blocker**: with the real
firmware compiled in, the kernel powers up the Adreno 610, boots its microcode,
brings the CP up and passes its self-test on 4 KiB pages. What still fails is
the *composition* path: with `citrusgl=1` the screen stops updating after ten to
fifteen frames and the phone sits idle (kernel, vsync timer and all daemons
alive), which the user sees as "boots to the lock screen, then freezes".

## 1. Root cause of "the GPU is not running": a stub firmware file, again

The CI 4K build tree
(`out/citrus-8core/ci-run-40531392449/tree/xnu/iokit/Kernel/arm/TopazAdrenoFw.cpp`)
was a **335-byte stub**:

```c++
extern const uint8_t topaz_fw_zap_mdt[] = {0};
...
extern const size_t topaz_fw_zap_mdt_size = 0;
```

so every 4K boot logged `CitrusGPU: device firmware missing; hardware start
refused` and never touched the GPU. The real 219,623-byte
`TopazAdrenoFw.cpp` (zap MDT 6860 B, zap B02 2096 B, SQE 32304 B) sits in the
source tree and in `out/citrus-gpu/xnu`. This is the exact class of failure as
the FT8719 firmware header (`research/CITRUS-4K-BOOT.md` §3): **an input of the
build was a placeholder, and the driver refused to start rather than crash.**

Fix: copy the real file into the CI tree and compile it into the local relink
(`/tmp/relink-smp7.py`, `compile_cpp_line('TopazAdrenoFw.cpp',
'TopazAdrenoFw.cpo', 'iokit/DEVELOPMENT')`).

### Boot evidence (`out/ios16/logs/4k-smp7-gpu9-live.txt`)

```
CitrusGPU: requested gfx3d 600 MHz (GPLL0/1)
CitrusGPU: requested GPU pool 128 MB
CitrusGPU: reserved 64 MB of contiguous GPU pool at 0x8388c000
CitrusGPU: reserved second 64 MB GPU pool at 0x87a0c000 (total 128 MB)
CitrusGPU: PAS13 query=0; using verified vendor init/auth path
CitrusGPU: power votes MEM=80004221 SNOC=80000001 CX=00222001 CXSTAT=00005ff4 GX=00222001
CitrusGPU: gfx3d 600 MHz (GPLL0/1, cfg=0x501)
TopazGPU: powered: RBBM_STATUS 00000001
TopazGPU: zap: embedded firmware (6860 + 2096 bytes)
TopazGPU: zap: metadata at 0x9031c000
TopazGPU: zap: init_image and mem_setup ok, copying the segment
TopazGPU: smmu: tables
TopazGPU: SMMU TTBR0 0x90320000 SCTLR 0x000000e0 TCR 0x00800020 TCR2 0x00000061 IDR0 0x4c017e04 IDR2 0x00005511 sCR0 0x00210406 (identity)
TopazGPU: cp: SQE 32304 bytes, allocating ring
TopazGPU: cp: SQE at GPU 0x8f0b4000, ring 0x8f0c0000
TopazGPU: CP up (ME_INIT, SET_SECURE_MODE 0), core 600 MHz
CitrusGPU: selftest PASS 16 IB writes and fences
TopazGPU: Adreno 610 ready, RedwoodGPU published
```

So on 4 KiB pages: ZAP boots, the SMMU is identity with the CI's `TCR2` value,
the SQE loads, the ring runs, fences complete (`SWEET GPU ready=1 last=31
done=31` in the heartbeat), and the 16-IB self-test passes. Userspace then
allocates from the pool (`CitrusGPU alloc: request=10485760 result=pool ...`)
and Mesa submits draws — `redwood-gl: frame N` lines appear and every fence
completes.

Nothing in the GPU bring-up is 4K-specific except that the firmware must be
present; the ring/SMMU/fence code is the same source the 16 KiB port uses.

## 2. SOLVED (2026-10-29 05:50): the "stall" was a 90 ms allocation, not a hang

Re-reading the same capture that produced the stall account below with the
per-frame numbers in hand gives the answer: the compositor was not hanging, it
was **spending ~95 % of every frame inside one allocation**.

Every full-screen CoreAnimation surface is 1080 x 2340 x 4 = **10 MiB**
(`CitrusGPU alloc: request=10485760`). `RedwoodGPU.cpp` tried the low-memory
`IOBufferMemoryDescriptor::inTaskWithPhysicalMask` path *first*, and for a 10 MiB
physically-contiguous request on this board that call takes **80-110 ms to
fail** (`low_us=91275`) before the reserved pool answers in 3 us (`pool_us=3`).
One or two of those per frame is 100-300 ms -> **3-5 fps**, exactly what the
phone showed. The "frames stop after 15" look was the same cost compounding
until SpringBoard had nothing left to present.

The fix is the `gpupoolfirst` knob that already existed: for requests >= 2 MiB,
ask the pool first and fall back to low memory only on a miss.

| 4 KiB boot, `citrusgl=1` | frame cost |
|---|---|
| without `gpupoolfirst` (`4k-smp7-gpu9-live.txt`, frame 8, 302 calls) | **112,994 us** (102 ms waiting) |
| with `gpupoolfirst=1` (`4k-smp7-gl-poolfirst-live.txt`, frame 23, 269 calls) | **7,782 us** (4.3 ms submitting, 4.3 ms waiting) |
| resting image (`4k-smp7-gpu10-live.txt`, frames 20-22) | 7.9-12.4 ms, allocation 1-2 us |

Frames keep flowing past the old 15-frame point (fences 44 and climbing,
`SURF ... swaps 23`), and no boot since has panicked.

**Still worth fixing, in order:** (a) the surface refill is a CPU path - the
frames that refill a 10 MiB texture from an IOSurface cost 13-183 ms
(`before it for the IOSurfaces`), which is what makes a full-screen content
change hitch once; (b) `handing on` is ~5 ms per frame on 4 KiB against 0.65 ms
on 16 KiB - that is the per-submission cache maintenance, now the largest
remaining per-frame term; (c) 16 KiB pages remain structurally faster.

## 2b. The original stall account (kept for the ruled-out table)

Configuration: `gpu=1 gpu_mhz=600 gpupoolmb=128 citrusgl=1` on the 7-core 4K
kernel with the `ios16-root-onesubmit.img` root (which carries the EAGL
wrapper `libcitrus-gl.dylib`).

- The wrapper logs frames 1-15 and then nothing. Frame cost grows before the
  stop: 6.5 ms, 7.4 ms, 12.6 ms, 28 ms, 39 ms, and frame 7 took **1.18 s**
  (522 ms of it "before it for the IOSurfaces").
- `SWEET FBT` present tracing (`SweetFramebuffer.cpp`, phase lines `enter`,
  `scanned`, `dp-surf`, `dp-drawn`, `dp-scan`, `dp-lock`, `dp-done`) shows
  presents 1-13 completing and then a single present ~35 s later, at t≈120 s.
- The heartbeat counters freeze with the UI:
  `SWEET GPU ready=1 last=N done=N SURF live=18 made=18 freed=0 swaps=13`.
  `last == done` at every sample: **the GPU never stops answering.**
- The process sampler (`sweetsample`, default `SpringBoard,backboardd`) shows
  every thread idle in `mach_msg2_trap`/`CFRunLoop`/`__workq_kernreturn`/
  `__ulock_wait`; symbolicating all sampled PCs against the mounted root's dyld
  cache leaves **no PC inside the wrapper or in backboardd's own code**. The
  system is not deadlocked in a syscall; it simply stops asking for frames.
- Kernel side stays healthy throughout: `7/7 CPUs`, `SWEET INTF1 ~322 frames in
  5 s` (vsync timer alive), `SWEET LV` heartbeat advancing, 4-8 crashes (all
  `driverkitd`), touch probe alive.

### What was ruled out (each tested on hardware, one boot each)

| change | result |
|---|---|
| `gpu_fbpool=0` (surfaces **not** from the GPU pool, `SweetSurface.cpp`) | still stops (21 frames) |
| `sweetpanel=1 sweetfb_noconsole=1 gpu_keep=0` (the 16 KiB production display flags) | still stops (10-11 swaps) |
| `citrusgl=0` with `gpu=1` (GPU up, no userland GL) | still stops (13 swaps) |
| `gpu=0` (no GPU at all) | UI fine (this is `smp7-ent8`, user-confirmed) |
| GPU pool arena split / 10 MiB allocations | all succeeded (`result=pool`), not the trigger |

`citrusgl=1` with `gpu=0` never loads the wrapper (0 `redwood-gl` lines), so it
is not a usable control.

### Current hypothesis

The GPU-pool / `gpu_low` surface path changes what the display scans
(`SweetSurface::sweet_scanout_eligible()` returns false when `gpu=1`, so the
cached scanout slots are never used and `directPresent()` takes the copy path or
the GPU-pool `scanFrom()` path). Combined with the diagnostic fallback in
`AppleCLCD::present()` — which treats a GPU-pool surface as unreadable
(16 KiB-user-page write-combined memory) and can flip a *different*, stale
surface — the compositor ends up in a state where CoreAnimation stops
committing. `SURF live=18 made=18 freed=0` shows nothing is ever released, but
the count also stops growing, so a plain retain leak is not proven.

The next step is visibility **inside the wrapper**, not more kernel tracing:
its `say()` already writes to fd 2 and lands on the kernel console (4,569
`redwood-gl:` lines in the 16 KiB capture), so the wrapper should log the entry
and exit of `frame_end()`, `glFinish` and the surface ioctls. That needs the
dylib rebuilt and the root re-flashed over ADB (`tools/build-citrus-eagl.py`,
`tools/package-citrus-gpu-userland.py`,
`tools/install-citrus-compositor.py`, `tools/flash-citrus-gpu-userdata.sh`).

## 3. Instrumentation added (kept; it is cheap and boot-arg free)

- `SWEET GPU ready= last= done= SURF live= made= freed= swaps=` on the existing
  heartbeat line (`sweet_ufs.c`, `TopazAdreno.cpp:redwood_gpu_state()`,
  `SweetSurface.cpp:sweet_surface_counts()`), so a stalled compositor can be
  told apart from a stalled GPU without a console attached.
- `SWEET FBT <us> <phase>` present-phase trace for the first 400 phases
  (`SweetFramebuffer.cpp:sweet_fb_trace()`), enabled by including the file in
  the relink.
- `AppleCLCD::present()` no longer flips a foreign surface when the referenced
  one is a GPU-pool surface (write-combined: emptiness cannot be read back).

## 4. Build / flash recipe for the GPU candidate

```sh
# 1. real firmware into the CI tree (once)
cp out/citrus-gpu/xnu/iokit/Kernel/arm/TopazAdrenoFw.cpp \
   out/citrus-8core/ci-run-40531392449/tree/xnu/iokit/Kernel/arm/

# 2. local relink (compiles: serial_console, sweet_ufs, sweet_usb, sweet_touch,
#    SweetHID, SweetFramebuffer, SweetSurface, TopazAdrenoFw, TopazAdreno, and
#    the six code-signing TUs)
python3 /tmp/relink-smp7.py            # -> /tmp/citrus-gpuN/kernel...

# 3. boot image: 7-node ADT + cpus=7, gpu=1 citrusgl=1
python3 upstream/ios-topaz/tools/mkpayload.py <kernel> \
    out/citrus-8core/smp7-first/smp7.adt /tmp/p/payload.bin --cmdline "<...>"
python3 tools/build-diagnostic.py \
    --template device-dumps/20261025-141423-923416/backups/boot.img \
    --payload /tmp/p/payload.bin
PYTHONPATH=out/citrus-8core/preflight/python-deps \
    python3 tools/test-diagnostic.py --loader out/citrus-diagnostic/citrus-xnu-boot.img
python3 usb-restart/reboot.py fastboot    # no buttons needed
fastboot flash boot <img> && fastboot reboot
```

Candidate kept: `out/citrus-8core/smp7-gpu9/citrus-xnu-boot-4k-smp7-gpu9.img`,
SHA256 `7d25ec892dc64ca9f24b60d1c1135ec914c4f05921066605c00e097eb0078d1f`
(GPU up, present trace on, compositor stalls). The working phone image stays
`smp7-ent8` (`a00de0c8...`), GPU off.

## 5. Traps learned here

- `strings <kernel> | grep 'device firmware'` after every relink: a stub
  firmware file silently produces a kernel that refuses to start the GPU.
- The CI build tree and the source tree drift: `TopazAdrenoFw.cpp`,
  `sweet_touch_fw.h` and `SweetFramebuffer.cpp` all differed. Always compile
  the file you edited into the relink, from the tree you edited.
- A C++ TU included in the relink needs `extern "C"` on functions an `extern
  "C"` caller references; otherwise the symbol is mangled and the link fails
  with `_redwood_gpu_state` undefined.
- `sweet_ufs.c` in the relink comes from the **CI tree**, not
  `out/citrus-8core/source/xnu`: changes there must be copied before relinking.
