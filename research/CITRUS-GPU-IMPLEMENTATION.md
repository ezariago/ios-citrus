# Citrus GPU implementation checkpoint — 2026-10-27

## Latest checkpoint: compositor runs; stale-buffer fix (2026-10-27 08:40)

The previous session progressed beyond the triangle without updating these
notes. `gpu-compositor1-live.txt` through `gpu-compositor5-live.txt` are retained.
The latest log proves 4/4 CPUs, the loader's seven EAGL hooks, an FD610 GLES
context in CoreAnimation, GPU submissions and 660+ GL frames. Its boot image is
`gpu-ca5` (`129b49929f3424ec0a70b7d677e894273f16bbfb3061f24b667f55ddaf1193b0`),
full framebuffer backport, `citrusgl=1 sweetfb_noconsole=1`. This supersedes the
old uninstalled/software-only statements further below. It does not establish
correct presentation: the user reports boot-console flashes on display updates.

The copy path skips `s == fSurface` but still calls `flipBack()`. That skip
predates buffered scanout: with a back buffer, the default framebuffer is a
source that must be copied. In compositor5, CA alternates surface 2 (4352-byte
rows, GPU-shared) and surface 1 (4320-byte rows, CPU readback). GL frames 2, 4,
6 and subsequent readbacks coincide with surface-1 swaps. An unfilled back
buffer can still contain the console copied during boot. Text muting cannot
prevent those stale pixels from being flipped onto the display. The quoted
one-core boot text also differs from this four-core boot's actual console.

The fix permits copying the default surface whenever flip buffers exist,
keeping the skip only for direct writes into the same physical framebuffer.
Both baseline and full-GPU sources are fixed; 0002/0003 reproduce exactly.
`tools/test-citrus-framebuffer.py` compiles the actual presentation copy loop
with address/undefined-behavior sanitizers. Alternating default/allocated frames
and a default base with an overlaid layer pass for both trees. Restoring the
old skip makes the alternating-frame pixel assertion fail.

The isolated full-compositor build `out/citrus-gpu-console-fix/` compiles and
links. `gpu-ca6-manifest.json` verifies the entire payload, all 9 Mach-O segments,
four Gold CPU nodes, 1792 MiB and the complete cmdline. New image:
`out/citrus-diagnostic/citrus-xnu-boot-gpu-ca6.img`, SHA256
`b699cac2dfbfb14de6444f7ede0cebcf9b3a830b0b9f70994c4f2f1b5738df75`.
Kernel SHA256 `4a6366e104e471beedfc37b997a66e63f3775bdcdf5e2f7790dba3fceaf30b7e`.

The user switched to fastboot; hash was rechecked, boot-only flash and reboot
succeeded. Reader was started first and detached from the tool session, with
the stale compositor5 reader stopped. Logs: `gpu-compositor6-flash.log`,
`gpu-compositor6-live.txt`, `gpu-compositor6-reader.txt`. The new boot confirms
4/4 CPUs, GPU self-test PASS, FD610 CoreAnimation context, GL frames and
default-surface swaps through the corrected copy path. Capture is live past
T=103 s with no observed GPU fault/kernel panic. Compact evidence:
`gpu-compositor6-result.txt`. **User confirmed the console flash is gone.** The user reports rubber-banding
but explicitly prioritizes performance before frame-order work. Compositor6
shows 23–41 ms warmed GPU frames and roughly 100–230 ms CPU frame readbacks.
The default boot surface has 4320-byte rows and cannot be shared with
Redwood (requires 64-byte rows); every other frame falls back to CPU
readback into that physical framebuffer. Presentation also defaults to
10 Hz. The next candidate changes these two bottlenecks, preserving the
console fix and leaving the queue/ordering design unchanged. No root write was needed; no other partition changed.


## Performance candidate `gpu-perf1` — flashed, observation in progress

User priority: **performance first; rubber-banding/frame order can wait.**
The `gpu-ca6` console-flash fix is visually confirmed and retained.

Changes are limited to the full compositor profile:

- `sweet_surface_create_render_target()` publishes an owned contiguous BGRA
  buffer with 64-byte rows (4352 bytes for 1080 pixels), 64 guard rows for GPU
  tiles, a bounded size (64 MiB maximum), and validated physical/contiguous
  range within the GPU identity map. Memory is zeroed and accounted; failed
  allocation/publication cleans up. The helper uses XNU-owned descriptors,
  not the disabled raw physical GPU pool.
- After the boot console is moved into its shadow, `citrusgl=1` replaces the
  default *render surface* with that buffer. The old physical surface stays
  published/retained and `fPixels` stays mapped to boot memory; console and
  panic paths keep their original geometry. Allocation failure keeps the old
  target. The intended effect is to make both alternating CA targets importable
  by Redwood, eliminating CPU readback into the uncached boot framebuffer.
- With `citrusgl=1`, default copy cadence is now 60 Hz instead of 10 Hz;
  `sweetfb_hz` can still override it. Software profiles retain 10 Hz.
- No changes to presenter queue eligibility, frame ordering, GPU clocks,
  firmware, page size, touch or userland/root image.

Validation: all kernel objects compiled and linked; 0003 applied and reproduced
all seven files exactly. `tools/test-citrus-framebuffer.py` passes with
ASan/UBSan: real presentation loops retain default/layer pixel correctness;
real allocation helper passes row alignment, guard bounds, zeroing, invalid
size, failed/fragmented/out-of-range allocation and publication cleanup cases.
This is not a measured hardware speedup yet.

Image: `out/citrus-diagnostic/citrus-xnu-boot-gpu-perf1.img`, SHA256
`37c832812bd495f4430ba3c7a46092cfc51442ae9733d77cc61a5f66d130d75a`.
Kernel SHA256 `572253213f4919e7fed2c2e92d7c56cb595be565cd8626edc7ef637d581e8360`.
Manifest: `out/citrus-gpu-performance/gpu-perf1-manifest.json` (all nine kernel
segments, 4 Gold nodes and full command line verified). Build:

```sh
python3 tools/build-citrus-gpu.py --output-dir out/citrus-gpu-performance --firmware-dir devices/citrus-gpu-fw
python3 tools/package-citrus-gpu.py --build-dir out/citrus-gpu-performance --name gpu-perf1 --execute --gl 1
```

User switched to fastboot; usage and image hash were rechecked, a durable
reader was started before reboot, and **boot-only flash and reboot succeeded**.
Logs: `gpu-performance1-flash.log`, `gpu-performance1-live.txt`,
`gpu-performance1-reader.txt`. Boot now confirms 4/4 CPUs, self-test PASS, FD610 and cached default
surface 2 shared at `0x89ebc000` (4352-byte rows, 10469376 bytes).
First four logged frames all draw in place with zero pictures copied out;
frames 2/4 previously needed CPU readback. Initial GL processing times
(excluding texture preparation) are 20.5/15.6 ms for frames 2/4; this is an
early sample, not an end-to-end FPS claim or matched-workload benchmark.
Evidence: `gpu-performance1-result.txt` and `gpu-performance1-observation.json`.
71 logged GL frame samples through frame 660 have zero CPU frame readbacks;
touch is active (53 HID events). No GPU fault/kernel panic observed
in this capture. **User confirmed: noticeably faster, but still slow.**
Continue checking
shared default surface and disappearance of alternating `pictures copied out`
from the GL profile. Compare warmed frame times during equivalent gestures
against compositor6, and ask the user about responsiveness. Keep `gpu-ca6`
as the fallback (console fix confirmed, slow but usable). No root write needed.

## Earlier hardware update: RedwoodGPU service published

**`gpu-svc1` booted at 05:24 and published the service.** The chain is the hw2
proof plus `RedwoodGPUStart()`: four Gold cores, CX/GX power-on, zap
`auth_and_reset: 0/0`, identity-mode SMMU, CP up at 300 MHz, **selftest PASS
(16 IB writes and fences)**, then `TopazGPU: Adreno 610 ready, RedwoodGPU
published`. backboardd/SpringBoard continued, created 1080x2340 surfaces and
presented; the console observer stayed healthy and there was no GPU fault,
panic or stall.

This profile is deliberately narrower than the full compositor backport:

- `--baseline-service` in `tools/build-citrus-gpu.py` restores the **baseline
  `SweetFramebuffer.cpp`** (the suspected source of the gpu-probe1 frozen UI:
  presenter thread, vsync lock, published modes) and **baseline
  `sweet_amfi.c`**.
- It keeps the **patched `SweetSurface.cpp/.h`**, because `RedwoodGPU` needs
  the `gpuPool`/`drawn`/state-page surface contract. That surface code alone
  did create and present surfaces without freezing this boot.
- It keeps `citrusgl=0`, so CoreAnimation still uses the software path; only
  the GPU service is exposed.

Image: `out/citrus-diagnostic/citrus-xnu-boot-gpu-svc1.img`, SHA256
`c909a13226d5947c1223705418bec102c3e11f39dac244fd7db3277db7003c86`
(24,018,944 B). Kernel:
`6085e05f9b3c026c0f4ce2e92fb3dc162dea63b76e6d34b547067ae2b132a5ad`. Log:
`out/ios16/logs/gpu-svc1-live.txt`. Build/manifest:
`out/citrus-gpu-baseline-service/` and `gpu-svc1-manifest.json`.

The 30 s `CAMetalContextCreate` wait is visible without the empty
`IOAcceleratorES` publisher: backboardd logs 300+ `IOAcceleratorES -> 0 found`
polls before it proceeds. That is slow but not a freeze, and it is the reason
the compositor patch added the empty accelerator. Do not read it as GPU
failure.

**Still not accelerated:** no user client has connected, no GL context exists,
and no triangle has rendered. The next step is the userspace triangle on a
backed-up test root; the display path must stay baseline until that works.

Rebuild the service-test configuration (20 objects):

```sh
python3 tools/build-citrus-gpu.py --baseline-service --firmware-dir devices/citrus-gpu-fw
python3 tools/package-citrus-gpu.py --build-dir out/citrus-gpu-baseline-service --name gpu-svc1 --execute
```

## Standalone triangle PASSES on hardware (2026-10-27 07:14)

**First GPU-rendered pixels on Citrus.** With the `gpu-svc1` boot and the
triangle test root, Mesa freedreno opened `RedwoodGPU`, created a 64x64 BGRA
IOSurface, submitted command buffers, and both readbacks were correct:

```
exec IOMFB_FDR_Loader
citrus-triangle: start
RedwoodGPU: client IOMFB_FDR_Loader (open 1)
renderer: FD610
RedwoodGPU: surface 2 (64x64 fmt 0x42475241 bpr 256, 32768 bytes) shared at 0xdbe00000
RedwoodGPU: submission 17: 1 command buffers, the first at 0x894f4000, 241 words
RedwoodGPU: submission 18: ...
RedwoodGPU: submission 19: ...
IOSurface center BGRA: 0,0,255,255
PASS: triangle, GL center=255,0,0 corner=0,0,255 error=0
```

One run, one pass, no GPU fault, panic or stall. Full log
`out/ios16/logs/gpu-triangle4-live.txt`; extract
`out/ios16/logs/gpu-triangle4-result.txt`. Image SHA256
`8833e381361a1a9773eafa580a2fc4bc0c8557f2e6c1eeccd5cc691e26653625`
(boot image unchanged at `c909a132…3c86`). Flash log
`out/ios16/logs/gpu-triangle4-flash.log`.

### launchd would not start a new job

The first two attempts did not run the triangle at all:

1. A new entry in the launchd job cache (`/System/Library/xpc/launchd.plist`),
   plus the matching plist in `/System/Library/LaunchDaemons`.
2. Rewriting the existing (disabled) `com.apple.bootpd` slot in the cache, its
   on-disk plist, and `disabled.plist`.

`launchd_cache_loader` did read the edited file — the console shows
`Using unsecure cache: /System/Library/xpc/launchd.plist` thanks to
`launchd_unsecure_cache=1` — and launchd booted normally, but neither job
appeared in the kernel `exec` log and launchd logged no error. The reason is
not established; do not spend more boots editing the cache until it is.

**Working workaround:** borrow a one-shot daemon that launchd already starts on
every boot. `/usr/bin/IOMFB_FDR_Loader` (display FDR calibration) runs at boot
and is not needed by this port; its binary is preserved as
`IOMFB_FDR_Loader.real` and the triangle is installed at its path. Launchd
executes the job, and the triangle opens `/dev/console` itself (launchd
rejects `StandardOutPath=/dev/console` with EACCES). Reproduce with
`tools/install-citrus-gpu-userland.py ... --test-runner iomfb`. This is a
bring-up method, not a production install.

### Root image

`out/ios16/ios16-root-gpu-triangle.img` is an APFS clone of the verified
known-good `ios16-root-keychain.img` (`0ee5bd34…31732`, re-hashed unchanged
after the edit), modified through a noowners mount and then repaired at the HFS
catalog level (`tools/hfs-chown-inplace.py --only-overrides`, 0:0 for only the
added paths). Installed:

| Path | Mode | Owner | Purpose |
|---|---|---|---|
| `/citrus/lib/libOSMesa.8.dylib` | 755 | 0:0 | Mesa freedreno + Redwood DRM bridge |
| `/citrus/bin/citrus-triangle` | 755 | 0:0 | standalone acceptance test |
| `/usr/bin/IOMFB_FDR_Loader` | 755 | 0:0 | triangle, replacing the FDR loader |
| `/usr/bin/IOMFB_FDR_Loader.real` | 755 | 0:0 | preserved original |
| `/System/Library/LaunchDaemons/com.citrus.gpu-triangle.plist` | 644 | 0:0 | unused candidate job |

All binaries are ad-hoc signed (`codesign --verify` checked inside the image);
the flash was verified with an on-device SHA256 of the first 16 GiB of
`userdata` before booting.

### Next GPU gate

CoreAnimation is still software. The remaining work is the compositor:
install the EAGL loader/wrapper, decide how to reintroduce the framebuffer
changes that froze `gpu-probe1` (presenter thread / vsync lock / published
modes / empty `IOAcceleratorES`), and verify lock/unlock, home, transitions and
app content. The standalone triangle is now the known-good reference for the
userspace stack; keep it runnable for regression.

## Hardware update: command execution passed

**`gpu-hw2` has now run on the phone:** CX/GX power-on, device zap
authentication (`0/0`), identity-mode GPU SMMU, SQE/CP initialization, and
**16 known-value IB writes with completion fences at 300 MHz all passed**.
The user confirmed swipe-to-unlock still works. No GPU service is published
and **rendered output / accelerated CoreAnimation remain untested**.

Current running image: `out/citrus-diagnostic/citrus-xnu-boot-gpu-hw2.img`,
SHA256 `26b55f5a7262f9d8e15212879067188d1adda991eed2278ad1317e2becad7eae`.
Kernel: `c5c2cd2f278faf65745fe5aced98e00f67d921922c3530dd04f4d07db2681153`.
Results and firmware hashes: `citrus-gpu-hardware-results.json`. Live log:
`out/ios16/logs/gpu-hw2-live.txt` (single attached reader; leave running).

Important corrections from the physical tests:

- `gpu-probe1`, the full compositor backport with `gpu=0`, booted four cores
  but the user saw a frozen lock-screen clock/unresponsive UI. Kernel timers
  and IPIs continued, and real touch reports reached HID. Do not use that
  image as a fallback. The precise offending backport change is unresolved.
- `gpu-probe2` kept baseline framebuffer/IOSurface/input and successfully
  unlocked. It confirmed SMCCC 1.1, PSCI 1.0, and working 32/64-bit SCM INFO.
  PAS_IS_SUPPORTED returns zero for both GPU13 and modem1 despite the call
  being available. It is **not a reliable gate for the GPU on this firmware**:
  hw2 subsequently authenticated successfully, matching the vendor
  `subsys-pil-tz.c` flow, which does not use that gate. The retained hardware
  driver now treats the query as advisory.
- `gpu-hw1` stopped at MEMNOC halt `0x80004221` before powering the domains;
  swipe still worked. Moving the fabric-clock halt checks **after CX/GX
  power-on** fixed this. Votes are still requested before power-up; the
  checks remain bounded. hw2 reached both domains and all subsequent stages.
- Firmware was read from the phone's vendor partition after a **read-only,
  no-journal-replay** mount in recovery. Each blob matched a separate
  on-device SHA256. No modem/persist/recovery/root partition was written.
  The only persistent on-device changes were the explicitly requested boot
  test flashes. The collector now carries remote exit status in a trailer,
  because this recovery's `adb exec-out` reports host status zero for failed
  remote commands.

Rebuild the isolated, working hardware-test configuration (19 objects):

```sh
python3 tools/build-citrus-gpu.py --baseline-hardware --firmware-dir devices/citrus-gpu-fw
python3 tools/package-citrus-gpu.py --build-dir out/citrus-gpu-baseline-hardware --name gpu-hw-next --execute
```

This mode restores baseline display, IOSurface and AMFI, starts the GPU and
its mandatory self-test, and **omits RedwoodGPU service publication**. It
keeps `citrusgl=0`. Exact sources/commands/manifests for the tested hw2 build
are retained in `out/citrus-gpu-baseline-hardware/`; subsequent rebuilds may
have different hashes as diagnostic text/source retention is updated.

Next: integrate RedwoodGPU with the baseline surface contract in a separate
test, then install only the standalone triangle on a backed-up test root.
Do not re-enable the whole IOSurface/compositor backport until its UI stall
is isolated. No userspace GPU library or wrapper has been installed yet.

The rest of this document is the **initial offline checkpoint**, retained
for build history; its statements that no GPU code has booted are superseded
by the hardware results above.

**GPU acceleration is not working on hardware yet.** No GPU candidate was
flashed or booted, and no firmware authentication, command completion, rendered
triangle or accelerated iOS frame has been observed. This checkpoint records
offline implementation and build results, not completion of README milestone 2.

## Built and verified offline

- Separate linked kernel: `out/citrus-gpu/kernel.development.citrus`, SHA256
  `669f514523f875753b4faf5f5f884a6f5d3a4e0c611a206462b895ed6906a510`.
  All 21 replacement/new objects compiled and the kernel linked successfully.
  The normal build tree and named known-good images were preserved.
- Retained seven-file patch:
  `kernel/patches/0003-citrus-adreno-kernel.patch`, applied **after current
  Citrus 0002**. It includes IOSurface prerequisites, framebuffer integration,
  RedwoodGPU, Adreno hardware code, root-mount helper, and an opt-in dyld policy.
  Its generator applies it with zero fuzz to a temporary baseline copy and
  compares every resulting file byte-for-byte. Base hashes and selected
  upstream file diffs are in `citrus-gpu-source-manifest.json`.
- Probe image: `out/citrus-diagnostic/citrus-xnu-boot-gpu-probe1.img`,
  23,973,888 bytes, SHA256
  `96663f364c20dc614fe6336dffdf997d866a3059f9cd2f28b36ebb1aa9b53d51`.
  In-payload verification: all nine segments equal the linked Mach-O; four
  Gold nodes `0x100..0x103`; `cpus=4`; DRAM `0x80000000 + 0x70000000`;
  full 553-byte command line matches the manifest. Physical timer remains off.
- Mesa 25.0.7 + freedreno + the Redwood DRM bridge:
  `out/citrus-mesa/out/libOSMesa.8.dylib` (14,812,008 bytes), SHA256
  `84d0d3746aa95ce43533348ac6848864c545d673358e3436aff68109e30d92d8`.
  The source archive passed its pinned SHA256. The upstream script's stale
  directory paths were corrected in a local build wrapper. Bison 3.8.2 was
  required; macOS's 2.3 fails on the IR3 parser's `%code` directive. Build
  dependencies live in `out/citrus-mesa/venv`; Homebrew bison is keg-only.
- EAGL, loader, backboardd wrapper and standalone triangle all link as
  **arm64 / iOS minimum 16.0**. Outputs and hashes are in
  `out/citrus-eagl/manifest.json`. They use `/citrus/lib` install names.
- The missing EAGL generator and dispatch table were found in the existing
  HakiOS reference checkout, commit
  `88513176b1e96ecf0b764cd62c6f4e6ac71345e3`. MIT-licensed copies and
  provenance are retained under `userland/gpu/reference/`. The source table
  targets 16.5, so it was independently checked against the mounted **16.7.16 /
  20H392** cache: **457 function names matched, zero mismatches or unknowns**.
  This is a static offset check, not complete ABI/runtime verification.
  Evidence: `out/citrus-eagl/dispatch-check.json`, including byte-range hashes.
- Seven host tests pass: valid firmware import/probe stubs, truncated program
  headers, reservation overflow, payload-size mismatch, invalid SQE, a real
  ARM64 dispatch wrapper and unrecognized code. No test emulates Qualcomm GPU
  hardware.
- Reviewable userspace ZIP:
  `out/citrus-gpu-userland/citrus-gpu-userland-candidate.zip`. This stages
  libraries, triangle, wrapper and candidate launch job under `/citrus`.
  **It does not replace backboardd or install a launch daemon.**

## Citrus-specific changes and limits

`tools/audit-citrus-gpu.py` checks every mapped GPU/GPUCC/SMMU/GCC window and
the zap reservation against the captured live device tree. Retained result:
`devices/citrus.gpu.json`. GPU is `0x05900000`, GPUCC `0x05990000`, SMMU
`0x059a0000`, GCC `0x01400000`, chip `0x06010000`, PAS 13, zap reservation
**`0x55a15000 + 0x2000`**. The GPU maps only the `0x40000` subwindow used by
the driver, within the captured `0x90000` resource.

The inherited Topaz pool at **`0x90000000..0xd0000000` overlaps Citrus's
managed kernel RAM**. Its allocator/descriptor/fallback interfaces now refuse
allocations. Kernel buffers come only from bounded XNU-owned contiguous
descriptors; allocation failure aborts bring-up. Redwood identity mappings
also reject buffers outside `0x80000000..0xf0000000`. A buffer is limited to
64 MiB, a client's active set to 256 MiB, its retained cache to 32 MiB, and
the early screen-surface reserve to four 12 MiB buffers. The first execution
profile disables retained buffers with `gpu_keep=0`. These limits are
conservative starting points, not measured compositor requirements.

Bengal's GPU PLL is the default alpha PLL type, whereas the inherited Topaz
code programmed Khaje's Zonda registers. That PLL path was removed. Bring-up
is restricted to **GPLL0 / 2 = 300 MHz**, without a voltage vote or overclock.
Mandatory branch/RCG failures now stop startup. The captured highest-bank bit
14 is used in the DRM parameter and RB/TPL1/SP/UCHE setup. Resource/clock
references: [Xiaomi Bengal GPUCC source](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/lime-q-oss/drivers/clk/qcom/gpucc-bengal.c),
[Linux A6xx UBWC setup](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/msm/adreno/a6xx_gpu.c).
The 300 MHz path and all power sequencing remain untested on Citrus.

CPU pages remain **16K**. Optional GPU SMMU stage-1 tables have their own 4K
granule; no 4K-CPU or Silver-core patch was applied. GPU defaults off.

`citrusgpuprobe=1` takes priority over `gpu=1`: it reads GPUCC status and
queries `PIL_IS_SUPPORTED` for PAS 13, then returns. No GPU clock, power,
firmware-authentication, SMMU or CP write occurs in that branch. The SMC route
and even this probe still need their first physical boot.

`gpu=1` requires supplied firmware, queries PAS support, powers up,
authenticates zap, initializes SMMU/CP, then executes **16 actual indirect
command buffers**. Each writes a distinct known word with `CP_MEM_WRITE`,
completes a fence, and has a 250 ms host-thread wait bound. Only a complete
self-test publishes RedwoodGPU. A failure logs the ring/SMMU state and stops
the CP; buffers are retained after timeout so an in-flight GPU cannot write
freed memory. This failure handling has not been exercised on hardware.

The compositor path is separately gated by **`citrusgl=1`**, default off.
The dyld policy changes its name to `AMFI` only under that flag and allows
DYLD policy flags only for backboardd. The candidate wrapper requires the
preserved real daemon. Its loader checks process name, OS build `20H392`,
explicit flag, GPU service and the expected runtime GLES vtable pointers
before loading EAGL and installing shader hooks. No persona or unrelated
daemon patches were added. Static matching cannot prove that CoreAnimation
will accept this integration.

## Rebuild

Run from the project root; these commands do not access the phone:

```sh
python3 tools/build-citrus-gpu.py
python3 tools/audit-citrus-gpu.py
python3 tools/package-citrus-gpu.py
python3 tools/build-citrus-mesa.py
python3 tools/check-citrus-eagl.py /Volumes/iOSRoot/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64
python3 tools/build-citrus-eagl.py
python3 tools/package-citrus-gpu-userland.py
python3 tools/test-citrus-gpu.py
```

The cache path is the existing **read-only** iOSRoot mount. Rebuilding Mesa
requires Xcode's iPhoneOS SDK and `/opt/homebrew/opt/bison/bin/bison` 3.8+.
Manifests contain input/output hashes and kernel compile commands/logs are
retained next to each object. Probe-only builds generate zero-sized firmware
arrays, never another phone's firmware. To edit the staged kernel, regenerate
and verify 0003 with `python3 tools/make-citrus-gpu-patch.py` before rebuilding;
the builder recreates the stage from the baseline and retained patch.

## Hardware blocker and next physical steps

During this run **ADB and fastboot had no devices and there was no USB CDC
port**. No phone reset, flash, root-image modification, on-device write or
background automation occurred. This does not establish the phone's screen
or kernel state. Inspection of the independently verified local recovery
backup found touch firmware but none of the three GPU firmware files.

1. Connect an Android/recovery shell with access to vendor firmware. Read-only
   collection, separate device/host SHA256 checks, local provenance:

   ```sh
   python3 tools/collect-citrus-gpu-fw.py
   # Add --su if the Android shell needs root. Existing output is not replaced.
   ```

   The tool checks standard vendor firmware directories and saves to the
   ignored `devices/citrus-gpu-fw/`. It never mounts or writes the phone.
   Do not restore the iOS root or write recovery/modem/persist to obtain these.

2. First test the packaged `gpu-probe1` image. Follow the standing manual
   reset loop: recheck usage; start a single durable `tools/usb-log.py` reader
   **before** reset; user resets into fastboot; reverify the image hash; flash
   **boot only**; reboot and capture. Require the four-core line, responsive
   software UI/touch and `CitrusGPU: probe ...` / PAS result. Do not treat a
   silent tty as proof of a kernel crash. Keep the known-good image available.

3. After a successful probe and real firmware capture:

   ```sh
   python3 tools/build-citrus-gpu.py --firmware-dir devices/citrus-gpu-fw
   python3 tools/package-citrus-gpu.py --execute
   ```

   The firmware importer rejects bad ELF headers, unexpected segment layout,
   payload-size mismatches and content exceeding the 8 KiB zap reservation.
   `--execute` refuses to package the no-firmware build. This profile keeps
   `citrusgl=0`, so compositor integration is not mixed into CP bring-up.
   Require `CitrusGPU: selftest PASS 16 IB writes and fences` before proceeding.

4. Install the staged `/citrus` tree only into a backed-up test root. Run the
   standalone triangle first, optionally via the candidate launch job. It
   waits up to 30 seconds for the tested GPU service, forces freedreno,
   requires an Adreno 610 renderer, imports a real IOSurface, draws a red
   triangle over blue, and checks both GL and CPU IOSurface pixels. A software
   renderer or unshared texture fails. A 45-second process alarm bounds this
   test. Capture its result rather than inferring success from a library load.

5. Only after repeated triangle success: preserve the original backboardd at
   `/usr/libexec/real/backboardd`, install the candidate wrapper, and build a
   compositor profile with `citrusgl=1`. Keep `gpu=0 citrusgl=0 gl=0` as the
   software fallback. Verify lock/unlock, home, transitions, app content,
   multi-touch gestures, repeated cycles and sustained memory/frame timing.
   No automatic root installer was run or supplied for this untested step.

The remaining README completion criteria are intentionally still unchecked.

### Performance1 user result and remaining cost

The user confirms **noticeably faster, but still pretty slow**. Keep perf1 as
the current improved boot; rubber-banding is accepted for now. At 600 GL frames
the cumulative EAGL profile reports 70.4 ms/frame, including 25.3 ms preparing
textures from IOSurfaces, 20.2 ms handing commands on, 8.6 ms waiting and only
~5 us copying rendered output. This includes cold shader/asset work and is not
end-to-end FPS or an equivalent-workload comparison. Warm complex sampled
frames remain around 35–45 ms. The next performance investigation should target
texture upload/import and GPU submission/wait overhead, retaining the successful
cached default render target. No frame-ordering change was made. No root write.

## Second performance pass: CPU preparation dependencies

Latest user feedback: rubber-banding is no longer noticeable; continue the
performance work. The current improved baseline remains `gpu-perf1`.

`RedwoodGPUUserClient::externalMethod(kMsmGemCpuPrep)` waited for the global
last GPU fence and ignored the requested buffer's handle. This can make an
upload into idle/new texture memory wait for unrelated rendering. The new
`cpuPrep()` validates the handle and snapshots the buffer's own fence while
holding `gGPULock`, then uses that snapshot even if `gpuWait` releases the lock.
Never-submitted buffers (fence 0) return immediately. Every submit continues to
record the fence in every buffer it names, including read-only use, so this is
a conservative dependency check. Busy and expired requests retain their prior
return semantics; invalid handles now fail validation. Cache maintenance and
GPU/display completion checks are retained.

The host regression compiles the actual method with ASan/UBSan and checks idle,
completed, busy, expired, invalid and independent handles. It also mutates the
buffer during a mocked lock-dropping wait to check snapshot use. Added short
CPU-prep counters and actual identity-map allocation timing (the old identity
path incremented `made` without incrementing `making`). No root/userland write
is needed for this pass. Build: `out/citrus-gpu-performance2/`.

Second-pass build/link and packaging passed. `gpu-perf2` was **flashed to boot and rebooted** after the user switched
to fastboot. Usage and hash were rechecked, and a single durable reader was
started before reboot. Logs: `gpu-performance2-live.txt`,
`gpu-performance2-flash.log`, `gpu-performance2-reader.txt`. Boot/render
observation is pending. Image SHA256:
`3cc07d101e60640b3b041b14bd2b31c55a7b2034ae82d98110cb48fbe99e5976`.
Kernel SHA256: `90a40c031746bc0a18d517d6defb72bdcba206291d91e975236aa8ac907e7b15`.
Manifest: `out/citrus-gpu-performance2/gpu-perf2-manifest.json` (all nine
segments/four Gold nodes/full cmdline verified). Restoring the global-fence
choice in the host test fails its idle-buffer assertion. Reproduce:

```sh
python3 tools/test-citrus-gpu-sync.py
python3 tools/build-citrus-gpu.py --output-dir out/citrus-gpu-performance2 --firmware-dir devices/citrus-gpu-fw
python3 tools/package-citrus-gpu.py --build-dir out/citrus-gpu-performance2 --name gpu-perf2 --execute --gl 1
```

Next hardware gate: compare responsiveness during the same gestures and inspect
`CitrusGPU: CPU prep` counters plus real allocation timings; keep no-readback
in-place rendering, four cores, touch and healthy observer/GPU state. Do not
claim a measured speedup from the host regression alone.

### perf2 failed visual verification; rollback required

The user reports **the screen does not refresh**. The kernel remains alive:
4/4 cores, GPU self-test PASS, FD610, initial 10 GL frames, then no further GL
frame logs despite touch events, healthy observer timers/IPIs and INTF scan
counters. No explicit GPU fault or kernel panic appears. Immediately after
frame 10, the log says `display off ignored (sweetfb_stayon)` and falls back
to surface 2. The first CPU-prep counter was zero; the dependency change is
not proven causal. No speedup can be claimed. Capture evidence:
`gpu-performance2-result.txt`. The user was asked to return to fastboot to
restore the unchanged, confirmed `gpu-perf1` image.

The canonical RedwoodGPU.cpp has been restored from the perf1 source and 0003
regenerated. The rejected perf2 source, binary, manifest and capture remain in
their separate output directories. `test-citrus-gpu-sync.py` now explicitly
uses the quarantined candidate, whose passing host tests did not establish
hardware correctness. Do not repeat this boot without diagnosing the display
sleep/fallback/renderer state first. No root or other partition was written.

Rollback: fastboot was detected, usage and the original `gpu-perf1` image SHA256
were checked, and boot-only flash/reboot succeeded. New single durable capture:
`gpu-perf1-rollback-live.txt`; flash log `gpu-perf1-rollback-flash.log`.
The canonical regenerated GPU patch hash equals perf1's original build manifest.
Visual recovery still needs confirmation. Perf2 is quarantined as a failed
visual gate, not established as the cause: display-sleep/fallback happened
immediately after its last GL frame, and observed CPU-prep calls were zero.

### Recovery confirmed; bounded polling candidate next

The user confirms the unchanged perf1 boot refreshes and responds to touch
again. Keep perf2 quarantined; causality remains unproven. Performance work
continues from perf1's exact driver behavior, including its old CPU-prep path.

The next candidate changes only fence waiting: active, preemptible 20 us poll
intervals for up to 2 ms, with `gGPULock` released during intervals; afterward
fall back to the original 200 us blocking delay. Zero-timeout queries do not
poll, shorter caller deadlines cap the active window, and long-timeout error
reporting is retained. It adds short counts for polled/blocked completions and
measured sleep durations. The 14–16 ms GL wait intervals suggest a scheduling
component, but counters must establish that; do not claim it is proven yet.
`test-citrus-gpu-wait.py` compiles the actual function under ASan/UBSan against
a deterministic completion clock and scheduling penalty; all completion,
timeout, lock and polling-bound cases pass. Build is separate under
`out/citrus-gpu-performance3/`. No perf2 CPU-prep change, root write or userland
change is included.

Bounded-polling candidate `gpu-perf3` compiled, linked and packaged, then was
**flashed to boot and rebooted** after the user switched to fastboot. Usage
and hash were checked, and one durable capture reader was started before
reboot. Logs: `gpu-performance3-live.txt`, `gpu-performance3-flash.log`,
`gpu-performance3-reader.txt`. **Hardware result:** four cores, self-test PASS, FD610, cached default target,
GL frames drawn in place with no sampled CPU frame readbacks, touch events
and healthy observer; no observed GPU fault/kernel panic. **User confirms
the screen refreshes and feels faster than the working perf1.**
Retain perf3 as current baseline, perf1 as fallback and quarantine perf2.
Evidence: `gpu-performance3-result.txt`, `gpu-performance3-observation.json`.
Counters show polled and blocked completions; actual requested-200-us
sleeps are roughly 300–600 us. Thus the gain is confirmed subjectively, but the
14–16 ms GL wait interval is not proven to be scheduler overshoot, and
there is no controlled FPS claim. Texture upload/allocation remains a
large cold-start cost to target from this new working baseline. Image SHA256:
`af7dd145bd40c35959156c54a5fd9a824befcd3fcdbb96fcd5d1376f6b6ad16b`.
Kernel SHA256: `0dafdc0943392c49bdfe0289a61a7efe3ff370e8bdab892e4b53b0cb950faeed`.
Manifest: `out/citrus-gpu-performance3/gpu-perf3-manifest.json`; all nine kernel
segments, four Gold nodes and full command line verified. Current phone now boots perf3; the restored, user-confirmed perf1 image remains
the fallback. Reproduce:

```sh
python3 tools/test-citrus-gpu-wait.py
python3 tools/build-citrus-gpu.py --output-dir out/citrus-gpu-performance3 --firmware-dir devices/citrus-gpu-fw
python3 tools/package-citrus-gpu.py --build-dir out/citrus-gpu-performance3 --name gpu-perf3 --execute --gl 1
```

## Performance candidate gpu-perf4: bounded temporary-buffer reuse

Continued from the hardware-confirmed perf3. Only RedwoodGPU.cpp changes among
the seven staged kernel files. gpuWait and CPU-prep behavior are unchanged;
perf2 remains quarantined. No root/userland, GPU clock or frame-order changes.

The package profile had explicitly disabled the inherited same-client buffer
cache (`gpu_keep=0`). Candidate perf4 uses `gpu_keep=1`: completed owned buffers
of matching size/flags may be retained up to 32 MiB (48 slots, 60 s expiry,
256 KiB minimum, 8 MiB maximum entry). Contents remain from the same client,
matching the existing Mesa/driver reuse contract. IOSurfaces are excluded.
This should avoid some repeated contiguous allocations; no speedup is claimed
until hardware observation/user feedback. Cold, unique uploads still allocate.

Hardened reuse to obey the same 256 MiB active-set limit as fresh allocation;
reap completed deferred buffers before lookup, using a post-reap timestamp to
avoid unsigned age underflow; diagnostic `gpu_keep=2` clears while the handle
is locked. Added missing allocation duration accounting in both identity paths;
prior `0 us` values were unmeasured. `tools/package-citrus-gpu.py` now accepts
`--keep-buffers 0|1|2`, with the existing default remaining 0.

Validation: `python3 tools/test-citrus-gpu-reuse.py` compiles the real allocation,
keep, drop, free and reap methods with ASan/UBSan. Exact reuse, client isolation,
flags/size mismatch, active/cache budgets, unfinished/completed fences, surface
exclusion, eviction/expiry, disabled mode and allocation failure pass. Deliberate
budget-bypass, unfinished-reuse and flags-mismatch mutants fail their assertions.
Existing framebuffer/allocation and gpuWait sanitizer regressions and seven
GPU checks pass. Patch 0003 reproduces all seven files exactly. Full kernel
compile/link passed (`out/citrus-gpu-performance4-build.log`).

Reproduce:

```sh
python3 tools/build-citrus-gpu.py --output-dir out/citrus-gpu-performance4 --firmware-dir devices/citrus-gpu-fw
python3 tools/package-citrus-gpu.py --build-dir out/citrus-gpu-performance4 --name gpu-perf4 --execute --gl 1 --keep-buffers 1
```

Image: `out/citrus-diagnostic/citrus-xnu-boot-gpu-perf4.img`, SHA256 `91e296092a4e25a086144605c492eddc82a4f6dfe7ff1e71de0aad7a5444ffef`.
Kernel SHA256 `0f574a07b3572d4114e46464536580c3bbe7ca03d962f91e5b9118b92ccb715a`.
Manifest `out/citrus-gpu-performance4/gpu-perf4-manifest.json` verifies all nine
kernel segments, four Gold ADT nodes and full command line.

The phone was already in fastboot. Reverified candidate/perf3 fallback hashes,
checked one target, checked existing reader processes, started one durable reader
before reboot, and successfully flashed only boot then rebooted. Flash log
`out/ios16/logs/gpu-performance4-flash.log`; capture `gpu-performance4-live.txt`;
reader PID in `gpu-performance4-reader.json`. Awaiting boot evidence and visual
feedback; perf3 is the named fallback. No automation created.

### perf4 hardware observation and amended reclaim candidate

Perf4 boot confirms 4/4 cores, self-test PASS, FD610, cached target, in-place
rendering and touch. Cache hits are real (counters logged), but failed 10 MiB
contiguous allocations caused GL errors 0x505 and 0x506; 21 cumulative errors
by frame 600. This candidate has **not** passed GL allocation verification.
No comparative speedup claim is valid. Retained memory can increase contiguous
fragmentation, but failures also appear while the most recent logged retained
total is below 1 MiB; do not claim the cache is proven causal. See the live
capture and `gpu-performance4-{result.txt,observation.json}`.

Amended source releases this client's retained cache when a contiguous fresh
allocation fails, then retries once. Only completed own buffers are dropped;
busy deferred buffers remain protected. Counters report bytes/reclaim passes.
The host ASan/UBSan regression now exercises allocation failure, cache release
and successful retry. 0003 regenerated. Full build in progress separately at
`out/citrus-gpu-performance4b/`. No new flash yet; perf4 still on phone, with
perf3 unchanged as fallback.

Perf4 user feedback: Control Center refreshes with the same pre-existing visual
glitches; performance about the same as perf3. No gain established.

Perf4b full build/link and packaging passed. Image `out/citrus-diagnostic/citrus-xnu-boot-gpu-perf4b.img`, SHA256 `21c51b9175868561dc196952b3e73a4dd059016053a537905810d735403be7a7`;
kernel SHA256 `5a236ca55f0da7a5d66feb9b4119bbe9d51819779aefb6be0307379a9813a2f4`. Manifest
`out/citrus-gpu-performance4b/gpu-perf4b-manifest.json` verifies all nine
segments/four Gold nodes/full cmdline. Missing-retry mutant fails the new
regression. Rebuild/package commands are the perf4 commands with build dir
`out/citrus-gpu-performance4b` and name `gpu-perf4b`, keeping `--keep-buffers 1`.
Not flashed; user asked to return to fastboot or choose perf3 restoration.

User returned to fastboot; perf4b boot-only flash and reboot succeeded. Candidate
and perf3 hashes reverified. Stopped the perf4 reader and started one durable
perf4b reader before reboot. Logs `gpu-performance4b-{flash.log,live.txt}` and
reader metadata `gpu-performance4b-reader.json`. Awaiting boot evidence.

Perf4b initial boot evidence: 4/4 CPUs, self-test PASS, FD610, cached default
render target and in-place rendering; touch firmware 0x0B running. First ten
sampled GL frames show zero picture readbacks and no logged GL error/fault/panic.
No pressure-reclaim pass observed yet; this is not a workload verification.
User asked to repeat Control Center/Search, response pending. Durable capture
remains live; no automation. Perf3 remains confirmed fallback. Evidence extract
and observation: `out/ios16/logs/gpu-performance4b-{result.txt,observation.json}`.

### perf4b failed allocation verification; restored perf3

Under UI use perf4b still failed 10 MiB contiguous GPU-buffer allocations and
logged GL 0x505/0x506 after cache reclamation. One counter sample reports 2880
KiB reclaimed over two passes. This rules out retained-cache pressure as a
sufficient explanation, not all effects of allocation layout. User says the
performance is about the same; the pre-existing issue affects perf3 and all
earlier builds and is reproducible by changing volume via Control Center.
Use that fixed gesture for the next baseline comparison. Do not equate the
pre-existing visual/performance issue with candidate allocation errors without
matching perf3 evidence.

Both perf4/4b are quarantined. Canonical staged RedwoodGPU.cpp was restored
byte-for-byte from perf3 and 0003 regenerated/reproduced (159846 bytes).
The retained reuse regression now explicitly targets perf4b's quarantined
source, not the canonical driver. Packaging's optional --keep-buffers remains
available with default 0. No root/userland changes or clock/queue/pacing work.

User returned to fastboot. Reverified unchanged perf3 image SHA256
`af7dd145bd40c35959156c54a5fd9a824befcd3fcdbb96fcd5d1376f6b6ad16b`, one target,
stopped perf4b reader, started one durable reader, then successfully flashed
boot and rebooted. Logs `out/ios16/logs/gpu-perf3-reuse-rollback-{flash.log,live.txt}`;
reader metadata `gpu-perf3-reuse-rollback-reader.json`. Awaiting startup and
volume-slider reproduction. No automation.

Rollback startup verified: 4/4 CPUs, self-test PASS, FD610 and in-place GL frames
through the first ten samples, no initial GL allocation error/fault/panic.
Volume-slider workload and user verification pending; durable reader live.
Evidence `out/ios16/logs/gpu-perf3-reuse-rollback-{result.txt,observation.json}`.

### Final user correction: perf3 is better; reuse candidates are regressions

After testing the restored baseline the user explicitly corrected the earlier
report: the volume-slider issue **did not arise in perf3**, and performance is
**noticeably better** on perf3. This supersedes the claim that every earlier
build had that issue. Keep perf3 running; quarantine both perf4 and perf4b.
The rollback capture passes at least 600 GL frames with zero logged GL errors,
while the reuse candidates had allocation failures and GL 0x505/0x506.
This is evidence against promoting reuse; the exact fragmentation mechanism
remains unproven. Do not treat after-the-fact cache reclamation as sufficient.
All seven canonical staged files match perf3 exactly, 0003 reproduces them,
and the perf3 gpuWait regression still passes. Named perf3 boot image unchanged.
No root/userland changes. One durable rollback reader remains live; no automation.
Final extract and structured observation are retained in
`out/ios16/logs/gpu-perf3-reuse-rollback-{result.txt,observation.json}`.

Final rollback snapshot: sampled frame 1120, 90 HID events, zero logged GL
errors/CPU picture readbacks, no GPU fault/panic observed. It **also logged
10 GPU buffer allocation failures** without GL errors, so allocation-failure
lines alone are not sufficient to explain or distinguish the visible issue.
Do not overstate that diagnosis; retain both the user comparison and GL-error
comparison. The structured observation includes the baseline failures.

## Clock investigation and clockprobe1

See `CITRUS-GPU-CLOCKS.md` for pinned stock source, fuse-bin result, actual
GLINK-RPM backend and next gate. Clockprobe1 boot-only flashed successfully;
speed bin 200 selects a stock 950 MHz maximum, but current rate is still
300 MHz. Four cores/self-test/FD610/in-place GL verified. No voltage changes.
Live capture and evidence: `out/ios16/logs/gpu-clockprobe1-*`.

Clockprobe1 health caveat: USB capture went quiet at T=126 before touch firmware
completion. Reader remains alive and reopened repeatedly with no new bytes.
No panic was captured; do not infer the whole kernel died from silence alone.
User asked about screen/touch, then asked to return to fastboot for unchanged
perf3 rollback. Still awaiting that handoff. Source probe and image quarantined;
canonical TopazAdreno.cpp restored from perf3, 0003 again 159846 bytes and all
seven files reproduce exactly. Fuse/bin and actual GLINK-RPM source findings
remain valid; do not reflash this diagnostic without diagnosing its health.

## 2026-10-27: follow-up on root-side blit and allocation failures

The `gpu-boxes` workload rules out the proposed dirty-rectangle optimization for
these interactions: 2,281 frame lines, 2,278 with scissor disabled and three
with it enabled at the full 1080x2340 size. This is the frame-level scissor
observation, not a proof about every individual draw. The handoff's stop
condition is met, so no dirty-blit implementation or root image was made.

A separate candidate for investigation is allocation pressure. The same log
shows a 64 MiB contiguous GPU pool reserved at boot and 104 messages reporting
failure to allocate 10,485,760 bytes. Near frame 2466, repeated contiguous
allocation searches scan 111,722 pages and invoke zone GC before the pool
failure; frame 2467 follows at 346.576 s after frame 2466 at 345.828 s. This
association does not establish that allocation caused the frame interval:
frame timestamps include scheduling and workload. In `RedwoodGPUUserClient::gemNew`'s
allocation path, the driver first requests contiguous low memory, then falls
back to the reserved pool; the failure message alone does not distinguish pool
fragmentation from insufficient free space. The log does not contain pool
occupancy or largest-free-block data. A useful next step is boot-only,
rate-limited instrumentation of request size, free bytes, largest free block,
and allocation duration, followed by the same interaction workload. Do not
increase the pool or alter allocation lifetime until that evidence distinguishes
capacity, fragmentation and transient contiguous-memory failures. Preserve the
confirmed button-enabled boot and compositor root as fallbacks.

### Allocation diagnostic candidate

Built and flashed boot-only `gpu-allocprobe` with the pll0-950 settings and
`sweetkeys=1`. Image SHA256
`1e9cf81e10ae2351577bea4e2da7ee75920e89fa8a0a5a0f285d10398919a6ad`;
manifest `out/citrus-gpu-allocprobe/gpu-allocprobe-manifest.json`, flash log
`out/ios16/logs/gpu-allocprobe-flash.log`, build log
`out/citrus-gpu-allocprobe-build.log`. Patch 0003 reproduces all eight staged
files. The diagnostic samples pool fallback attempts at most once per five
seconds, reporting request size, result, low-memory and pool allocation time,
post-attempt free bytes, largest free block, block count and cumulative pool
attempt/failure counts. Snapshot and counters use the pool lock; logging occurs
outside it. Allocation behavior is unchanged. Pool attempts that occur between
samples contribute to cumulative counts but their individual durations and sizes
are not retained. The old per-failure pool message is replaced by the sampled
line. The first detached reader exited before enumeration; a replacement reader
was started immediately after reboot and waits for USB. Root unchanged. Hardware
and workload verification pending.

Workload result: user completed swipe, scroll and typing. Capture has at least
207 touch events; the last sampled cumulative count was 233 pool attempts and
207 failures. Sampled failed low-memory searches took 17,995–106,803 us;
pool lookup itself took 1–2 us. At one sampled 10 MiB failure only 2,113,536
bytes were free: capacity was insufficient. At another, 12,599,296 bytes were
free but the largest block was 9,437,184 bytes: fragmentation prevented that
10 MiB allocation despite enough aggregate free space. These are snapshots
after the attempt. The log also contains GL 0x505/0x506 errors, seen in earlier
baselines; the capture does not independently establish each error's cause.
The sampled timings establish expensive failed low-memory searches, not their
full end-to-end impact or that a pool-size increase would be safe. No panic was
seen in the inspected capture; visual and responsiveness feedback is pending.

### 128 MiB pool candidate (unflashed)

User clarified the artifact report followed a substantially heavier stress test
than the earlier baseline and declined rollback; the cause is unresolved.
Candidate `gpu-pool128` adds an opt-in `gpupoolmb=128`, retains the normal 64
MiB default and falls back to 64, 32, then 16 MiB if reservation fails. Buffer
lifetime and allocation order are unchanged; allocation sampling is retained.
This addresses measured capacity pressure, but may still fragment and reserves
64 MiB more kernel RAM when successful. Build and link succeeded. The host
`tools/test-citrus-gpu-pool-reserve.py` executes the real reservation function
under ASan/UBSan for requested-size success, each fallback and total failure.
Image `out/citrus-diagnostic/citrus-xnu-boot-gpu-pool128.img` SHA256
`8442a301e40b2ac0962af4f4f4a42fc7081f9acf91d4a1172792662fc6b26605`;
manifest `out/citrus-gpu-pool128/gpu-pool128-manifest.json`; no flash yet.
The command-line limit required omitting `sweetptrecord=0`, whose static
variable is zero-initialized; all other allocation-diagnostic settings remain.
On boot confirm actual reserved size and stress similarly, compare attempt and
failure counters, GL errors and user-visible behavior. A 64 MiB fallback does
not test the intended capacity change. Current root remains unchanged.

`gpu-pool128` booted but its single 128 MiB reservation fell back to 64 MiB;
4/4 CPUs, PLL0, self-test and FD610 passed. It cannot test increased capacity.
A revised unflashed `gpu-pool2` requests a second independently allocated
region (64, then 32, then 16 MiB) when `gpupoolmb=128`; allocations cannot
span or merge across regions, and sub-descriptors reference the correct owning
region. The default remains one region. The host ASan/UBSan test exercises
allocation, return, region isolation, sub-descriptor offsets and fallback.
Build and link passed; image SHA256
`aeec7fc4b9bd92cd3afcdaabd29026a3a66f3ef475fb1bd83b6896d7175b9d19`;
manifest `out/citrus-gpu-pool2/gpu-pool2-manifest.json`. This is unverified on
hardware. Confirm second reservation size before stress testing; it adds wired
RAM and cannot satisfy a single request larger than any individual region.

`gpu-pool2` was flashed and booted. It reserved two 64 MiB regions at
0x836d0000 and 0x87810000. Four CPUs, PLL0, GPU self-test and FD610 were
confirmed. The first sampled 10 MiB fallback succeeded, with 113,262,592 bytes
free and a 67,108,864-byte largest block after allocation. Workload and visual
verification remain pending. Capture `out/ios16/logs/gpu-pool2-live.txt`.
