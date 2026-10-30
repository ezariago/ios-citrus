# Citrus GPU (Adreno 610) — backport analysis, evidence and estimate

**Superseded implementation details:** see `CITRUS-GPU-IMPLEMENTATION.md`.
The candidate now links and Mesa/EAGL builds; the missing generator/table were
found in the local HakiOS reference checkout. The earlier "zero rejects" claim
below was too broad: the active Citrus source needs `SWEET_UPAGE`/rounding
adaptation and lacks the AMFI prerequisite expected by 0902. The implementation
uses a checked consolidated patch, not blind application of the whole series.
Most importantly, the inherited raw GPU pool overlaps Citrus kernel RAM and
the Khaje Zonda PLL recipe differs from Bengal. Neither may be used unchanged.
There is still **no hardware GPU execution or accelerated UI result**.

Written 2026-10-27 01:21 (Asia/Jakarta). Status of this document: **analysis and
verified portability test, nothing flashed, nothing changed in the live tree.**
Answers the question: *"Would it take long to implement / backport the GPU driver
and GPU acceleration from `upstream/ios-topaz` to Citrus?"*

Short answer: **no — the kernel half is nearly copy-paste; the userspace
Mesa/EAGL half and the boot-cycle debugging are the work.**
Estimate: **8–12 focused working days if it goes well, 3–4 weeks realistic,
6+ weeks if zap/PAS auth or GPU power fights back.**

---

## 1. What "GPU support" in ios-topaz actually is

Topaz (Redmi Note 12 4G, SM6225 "khaje", Adreno 610) does **not** have an Apple
driver and does **not** use Metal. It does this:

```
CoreAnimation (QuartzCore)  ->  EAGLContext (iOS's EAGL API)
        |                            replaced by libtopaz-gl (eagl.c)
        v
Mesa freedreno (gallium)    ->  libdrm stand-in (redwood-drm)
        |                            IOConnect calls
        v
RedwoodGPU user client (kernel, msm/DRM-like interface)
        v
TopazAdreno.cpp (hardware: power, zap, SMMU, CP/SQE, IB submit, fences)
        v
Adreno 610
```

Frames are drawn into **IOSurfaces** (the kernel's `SweetSurface`), and the
existing framebuffer path still copies the surface to the panel each vsync
("today the CPU copies every frame out" — topaz README). So no new display
driver is needed: Citrus's SweetFramebuffer already does exactly that copy.

### Kernel-side inventory (lines are from the patched tree, not the patch headers)

| File | Lines | Role |
|---|---|---|
| `iokit/Kernel/arm/TopazAdreno.cpp` | 1229 | hardware: GCC/GPUCC branches, CX/GX GDSCs, gfx3d from GPLL0, zap shader via TrustZone PAS 13, GPU SMMU stage-1 (4 KB granule, 4 GB VA, one CB), CP start (SQE µcode, ME_INIT, SET_SECURE_MODE 0), IB submission, polled fences |
| `iokit/Kernel/arm/RedwoodGPU.cpp` | 1334 | `IOService`/`IOUserClient` speaking Linux `msm` DRM ioctls (from HackiOS `vcvkk/darwin-redwood`, reused with permission, APSL 2.0/MIT) |
| `iokit/Kernel/arm/TopazAdrenoFw.cpp` | 2606 | the three firmware blobs as C arrays (patch 0905; 0901 reads them from `/usr/share/firmware/topaz/` instead) |
| `bsd/dev/topaz_fw.c` | 78 | `topaz_fw_read()` from the root filesystem |
| `bsd/kern/topaz_sandbox_container.c` | — | sandbox container path from `CFFIXED_USER_HOME` (patch 0936) |
| edits | — | `SweetSurface.cpp/.h` (GPU-visible surface memory, `drawn`/seed, guard rows), `SweetFramebuffer.cpp` (calls `topaz_adreno_init()` at line 341, presenter/vsync), `kern_exec.c` (`topaz_inject=`), `kern_memorystatus.c` (no jetsam for backboardd), `sweet_amfi.c` (dyld may honour `DYLD_INSERT_LIBRARIES`), `bsd/conf/files`, `iokit/conf/files.arm64` |

Boot args used by that stack: `gpu=1` (start driver + publish service),
`gpu_mhz=320|465|600|785|820|980|1025|1100|1260` (stock OPPs, opt-in),
`topaz_inject=NAME[,NAME]` (kernel-side dyld injection), `gl=0` (never load the
GL library), `bbdenv=1` (backboardd wrapper reads `/topaz/backboardd.env`),
plus the usual `sweetfb_*`.

### Userspace inventory (all present in this repo)

| File | Lines | Role |
|---|---|---|
| `userland/gpu/eagl.c` | 3765 | iOS EAGLContext implementation behind CoreAnimation; the `gl*` entry table comes from a **generated** `eagl_gen.h` |
| `userland/gpu/inject.c` | 881 | `libredwood.dylib`: vtable replacement in backboardd, CA renderer selection, container-manager persona answer |
| `userland/gpu/topaz_inject.c` | 250 | `libtopaz-inject.dylib`: loads the GL library when the GPU service exists; hardcoded iOS 16.7.16 shared-cache addresses |
| `userland/gpu/gl_osmesa.c` | 115 | OSMesa entry points |
| `userland/gpu/bbd_wrap.c` | 47 | `/usr/libexec/backboardd` wrapper that sets `DYLD_INSERT_LIBRARIES` and execs `/usr/libexec/real/backboardd` |
| `userland/mesa/*` | — | Mesa 25.0.7 patches (freedreno + softpipe), `mk-mesa-mac.sh` (full cross-build for `arm64-apple-ios16.0`, verified present and complete) |
| `userland/mesa/redwood-drm/` | 302 | libdrm stand-in that turns DRM ioctls into IOConnect calls on RedwoodGPU |

**Not in the repo** (must be reconstructed): `userland/build.sh`, `mkjobs.py`,
`mkeagl.py`, `src/eagl_slots.txt`, and therefore `eagl_gen.h`. `eagl.c`
includes `eagl_gen.h` at lines 151 and 3423, and the header comment says the
table is "made by mkeagl.py: each entry counts the call and passes it on".
Everything else about the userspace stack is source-available.

---

## 2. Why it maps onto Citrus (measured, not assumed)

Citrus is a **POCO M3 (M2010J19CG), `bengal` / SM6115, 4 GB/64 GB, 1080x2340,
iOS 16.7.16 (20H392) iPhone10,3 userland**. Topaz is SM6225 "khaje". Both are
the same Qualcomm family, the same **Adreno 610**, and the driver was written
from a *bengal* recipe (`GMEM_SIZE 0x21000 /* 128K + 4K (bengal), TopazGpuW */`).

| Item | topaz constant | Citrus device tree (`live-tree.json`) |
|---|---|---|
| GPU registers | `0x05900000` + `0x40000` | `qcom,kgsl-3d0@5900000`, size `0x90000` |
| GPUCC | `0x05990000` + `0x9000` | `qcom,gpucc@5990000`, size `0x9000` |
| GPU SMMU | `0x059A0000` | `kgsl-smmu@0x59a0000` / `kgsl-iommu@59a0000` |
| GCC (GPLL0 etc.) | `0x01400000` | `0x01400000` (bengal) |
| chip id | A610 `0x6010000` | `qcom,chipid 0x6010000` |
| zap firmware | `a610_zap` | `qcom,kgsl-hyp` → `a610_zap` |
| PAS id | 13 | (same PIL/TZ mechanism) |
| SQE µcode | `a630_sqe.fw` | (not in DTB; A6xx standard file name) |
| zap region | `0x55B15000`, `0x2000` | `reserved-memory/gpu_region@55A15000`, `0x2000` |
| interrupt | SPI, polled anyway | `SPI 0xb1 (177)`, **driver polls fences, no GIC work needed** |
| OPP table | up to ~980 MHz | `gpu-opp-table` 320…980 MHz, `initial-pwrlevel 6` |

Two further coincidences that matter a lot:

1. **Same iOS build.** Citrus's root is iOS **16.7.16 / 20H392 / iPhone10,3**,
   the exact build topaz's `topaz_inject.c` hardcodes (`VT_GLES_CONTEXT
   0x1d5b2f6e8`, `FN_FUNCTION_SUPPORTED 0x1884b2164`, …). Those addresses
   transfer verbatim; nothing has to be re-derived from the dyld cache for the
   CoreAnimation renderer selection.
2. **Both phones are Xiaomi.** The zap shader is signed and authenticated by
   the SoC's fused OEM key; same OEM + same A610 makes it plausible that topaz's
   signed zap works here, but Citrus's own `/vendor/firmware/a610_zap.mdt`,
   `.b02` and `a630_sqe.fw` must still be pulled (adb root, 5 minutes) — do not
   rely on the coincidence.

RAM difference: Citrus publishes **1792 MiB** (`tools/mk-citrus-adt.py` caps
`--ram-mib` at 1792, `MEM_SIZE` at `0x80000000`). **The cap is not arbitrary and
cannot go to 4 GiB** (verified 2026-10-27 against `memory.txt`, the live DTB and
`shim/xnu-loader.c`):

- The phone's 4 GB is two banks, not one 4 GiB window: the low bank is
  `0x40000000 + 0x3dd00000` (989 MiB, owned by ABL/firmware — Android kernel
  code, modem, ADSP, and `cont_splash` at `0x5c000000`), and the OS bank is
  `0x80000000 .. 0x140000000` = exactly **3 GiB**. `0x140000000` *is* the 4 GiB
  line, so `--ram-mib 4096` from `0x80000000` would end at `0x180000000` —
  1 GiB past the end of RAM.
- Even inside that 3 GiB, ABL carves out `0xf3c00000 .. 0xffbfffff` (192 MiB)
  plus ~16 MiB at `0x13b400000`+, so the largest **contiguous** range is
  1852 MiB (`0x80000000..0xf3c00000`; 1840 with the 16 MiB alignment rule), then
  a separate 952 MiB window at `0xffc00000..0x13b400000`. Total usable below
  4 GiB is 2804 MiB (2.74 GiB) — the figure §5.3 quotes — but it is split.
- 1792 MiB ends at `0xf0000000`, 60 MiB below that first carveout. The size is
  also whitelisted in the shim: `shim/xnu-loader.c` accepts only
  `0x40000000`/`0x70000000`, and `mkpayload.py` takes `/chosen` `dram-size`
  verbatim. Raising it is a shim + ADT + payload edit and a boot, not an ADT
  flag.
- XNU's boot path is one range (`arm_vm_init(memory_size, args)`, one physmap):
  reaching 2.74 GiB needs multi-range memory support in `arm_vm_init`/pmap, i.e.
  a kernel change. Claiming the 192 MiB carveout would give a **single 2992 MiB
  range** (1852 + 192 + 952, stopping 4 MiB below the `0x13b400000` carveout) —
  not 3072: the 76 MiB above 4 GiB are separate reservations and are not needed.

**Probe result (2026-10-27 01:41): the 192 MiB window is NOT empty.** Booted
`citrus-xnu-boot-resprobe.img` (`42738a05…96d05`, same kernel + a read-only
`sweetresprobe=60` sampler in `bsd/dev/sweet_ufs.c`) and took 16 samples every
12 MiB (`out/ios16/logs/resprobe1-live.txt`): all 16 points **readable** (no XPU
fault, so the AP is allowed to read it) and **11 non-zero** —

```
0xf3e40000  ndop(.   Cur2ent     0xf3f00000  ing pageq....I:I
0xf4380000  anoc-sno               0xf4680000  PQR.PUVCPYZ{\mn/
0xf3cc0000  ...*.zF>.V.j.N..       0xf4200000  ....>.cM^z....Q.
```

i.e. stale-or-live kernel-log fragments plus high-entropy words; five points
are zero. So the heuristic "empty window → claimable" failed: something wrote
there, and the content alone cannot tell stale Android RAM from a live buffer.
Do **not** claim it without identifying the owner. Two cheap discriminators
remain: boot twice and diff the same 16 samples (identical → no boot-time
writer), and read `xbl`/`abl` in recovery and search for the address in their
memory map. Until then the only *verified-free* gain is multi-range (2804 MiB).

Consequence for the GPU: topaz's constraint is *"GPU-visible memory below
4 GiB"*, and 1792 MiB already satisfies that — the gap is **amount**, not
addressability. GPU-visible pool comes from the published 1.75 GiB, so size the
GPU pool conservatively and only do the multi-range work if bring-up shows
jetsam/memory pressure. Topaz had 4 GiB published and its own "GPU memory from
below 4 GiB" patches.

---

## 3. What I verified on 2026-10-27 (reproducible)

All tests were done on **throwaway copies** (`/tmp/xnu-pre`, `/tmp/xnu-gpu`) of
`out/upstream-artifacts/buildtree/xnu`. Nothing in the workspace was modified
except this document.

### 3.1 Patch application: 100% clean, in the right order

```sh
cp -a out/upstream-artifacts/buildtree/xnu /tmp/xnu-pre
cd /tmp/xnu-pre
# IOSurface prerequisites first (0131-0139; 0140 = 4K pages, NOT applicable here)
for p in upstream/ios-topaz/xnu/patches/01{31..39}-*.patch; do patch -p1 -f < "$p"; done
# then the whole GPU series
for p in upstream/ios-topaz/xnu/patches/09[0-4]*.patch; do patch -p1 -f < "$p"; done
```

Result: **zero rejects, zero fuzz** for every patch. (Applied without the
prerequisites, 9 patches leave rejects — all in `SweetSurface.cpp/.h` and
`sweet_amfi.c`, because the tree already carries a different revision of that
code. With 0131–0139 first, that disappears: the rejects were the missing
prerequisite, not a conflict.)

`0140-topaz-4k-pages` does **not** apply and must be skipped — XNU here is
16K-page (`__ARM_16K_PG__`), and the Silver cluster has no 16K granule anyway.
`0141`/`0143` (AMP clusters, panel sleep) and `0147`/`0148` (AMFI name, charger)
also apply and are optional; `0149` is the sandbox container hook.

### 3.2 Compilation: clean with the stock Citrus flags

Using the stored compile commands in `out/citrus-kernel/*.command.json`
(`-std=gnu++1z -fapple-kext -flto …`, same flags `tools/rebuild-kernel.py`
uses), with cwd = the matching `build/xnu.obj/…/DEVELOPMENT` directory (needed
for `-include meta_features.h`):

| Source | Result |
|---|---|
| `iokit/Kernel/arm/TopazAdreno.cpp` | **rc=0, 0 errors** |
| `iokit/Kernel/arm/RedwoodGPU.cpp` | **rc=0, 0 errors** |
| `iokit/Kernel/arm/TopazAdrenoFw.cpp` | **rc=0, 0 errors** |
| `iokit/Kernel/arm/SweetSurface.cpp` | **rc=0, 0 errors** |
| `iokit/Kernel/arm/SweetFramebuffer.cpp` | **rc=0, 0 errors** |
| `bsd/dev/topaz_fw.c` | **rc=0, 0 errors** |
| `bsd/kern/topaz_sandbox_container.c` | **rc=0, 0 errors** |

So the kernel side is not "port the driver": it is *apply the series, add the
new objects to the build script, supply firmware, and boot it*.

### 3.3 Not verified

- **Link**: the Citrus build is a partial relink against the fixed topaz object
  archive (`kernel.development.sweet.a` from
  `out/upstream-artifacts/xnu-kernel/`). `tools/rebuild-kernel.py` compiles a
  hardcoded 17-object list; the GPU adds ~6 more targets. That should link the
  same way `SweetFramebuffer.cpo` does (built-in `OSObject` subclass), but it has
  not been tried.
- Anything on hardware: no boot, no GPU power-on, no PAS query, no IB submit.
- Whether the zap authenticates, whether the CX/GX GDSCs come up, and the
  actual achievable clock without an RPM/GX voltage vote.

---

## 4. What is missing / must be produced

| # | Item | Effort | Notes |
|---|---|---|---|
| 1 | Pull `a610_zap.mdt`, `a610_zap.b02`, `a630_sqe.fw` from the phone's `/vendor/firmware` | 5 min | adb root; then either install under `/usr/share/firmware/citrus/` or embed with a 20-line generator like `TopazAdrenoFw.cpp` (preferred: no rootfs write) |
| 2 | Change the zap region constant `0x55B15000` → **`0x55A15000`** (Citrus' reserved `gpu_region`) | 1 line | verify against `memory.txt` (`55a17000-…` is System RAM, so 55a15000 is carved out) |
| 3 | Add `TopazAdreno.cpo`, `RedwoodGPU.cpo`, `TopazAdrenoFw.cpo`, `topaz_fw.o`, `topaz_sandbox_container.o` to `tools/rebuild-kernel.py` | ~10 lines | `-I` list already includes `iokit`, `bsd`, … |
| 4 | Reconstruct `userland/build.sh`, `mkjobs.py`, `mkeagl.py` + `eagl_slots.txt` → `eagl_gen.h` | 1–3 days | the only real gap; the EAGL table can be generated from iOS 16.7.16's OpenGLES export list (same build as topaz), or realised with a `dlsym` thunk table |
| 5 | Install `/citrus/lib` + wrapped `backboardd` into the root image; patch launchd plists (`tools/patch-launchd-plist.py` exists) | ½ day | root-image writes were painful before; consider a separate small image + a boot-arg-gated wrapper so a normal boot stays untouched |
| 6 | Mesa build for `arm64-apple-ios16.0` | 2–4 h machine time | `mk-mesa-mac.sh` is complete (Mesa 25.0.7, verified sha) |
| 7 | Memory: raise `--ram-mib` beyond 1792 and/or size the GPU pool | ½ day + boots | 1.75 GiB is tight for CoreAnimation on the GPU |

---

## 5. Risks, ranked (with the cheap probe for each)

1. **Zap shader authentication through TrustZone.** `TopazAdreno` issues raw
   `smc #0` from EL1 (same as `TopazModem.cpp`, which is already in this tree's
   source). Citrus's shim is its own (`shim/diagnostic.c`), not topaz's, so the
   EL1→EL3 SCM path is unproven here.
   *Probe:* one boot that only calls `PIL_IS_SUPPORTED` (PAS 13) and reads
   GPUCC/GDSC status — no GPU memory, no display change, purely read-only.
2. **CX/GX power.** No RPM/RPMH vote: the driver flips GDSCs and assumes the CX
   corner is up as ABL left it. If `gdsc_on()` never sees `PWR_ON`, this becomes
   an RPMH job (`bsd/dev/sweet_rpmh.c` exists but is thin).
3. **Memory pressure.** 1.75 GiB published, GPU pool + Mesa + CoreAnimation.
   Mitigations: trim the pool, guard rows; raising the cap means the multi-range
   work in §2 (2.74 GiB exists, but split by the `0xf3c00000` carveout — see the
   RAM note above), not a bigger `--ram-mib`.
4. **Userspace injection chain.** `eagl_gen.h` reconstruction plus the
   sandbox/`CFFIXED_USER_HOME`, jetsam and AMFI pieces. Same iOS build as topaz
   is the big win here; this is where most *time* goes, not most *risk*.
5. **The old ~140 s stall.** Root-caused (surface scan overread in `present()`)
   and mitigated by SMP; the current known-good boot is 4-core. A new driver plus
   GL load is a fresh chance to resurface something in that area.
6. **Performance expectation.** Topaz gets 25–35 fps with 8 cores and 4 GB.
   Citrus runs 4× A73 and 1.75 GiB, so expect lower; the display path still
   CPU-copies each frame until the "direct frames/presenter" work (0945) lands.

---

## 6. Plan and estimate

| Phase | Work | Effort | Boots |
|---|---|---|---|
| 0 | Pull firmware, set zap region, add objects to the build script, build a **read-only probe** (`gpu=1` that stops after power + PAS query) | ½–1 day | 1–3 |
| 1 | Kernel driver up: zap auth, SMMU, CP start, one IB that writes a known value and fences; dump via console | 1–2 days | 5–10 |
| 2 | RedwoodGPU + Mesa: build Mesa, `redwood_drm` client, a standalone GL test (triangle → IOSurface → readback) before CoreAnimation | 2–3 days | 3–6 |
| 3 | Userspace runtime: reconstruct `eagl_gen.h`/build scripts, install `/citrus/lib`, wrapper `backboardd`, sandbox/jetsam | 3–6 days | 5–10 |
| 4 | CoreAnimation on GLES: renderer selection, surfaces shared with the GPU, presentation | 2–5 days | 10–20 |
| 5 | Polish: direct scanout, frame pacing, 60 Hz, GPU clock/voltage | optional | — |

Totals:

- **Optimistic** (kernel probe and zap work first try, Mesa builds, no new stall):
  **8–12 focused working days**, ~25–40 boots.
- **Realistic:** **3–4 weeks** calendar at this project's pace (hardware cycles
  are the bottleneck, not code), ~40–60 boots.
- **If zap auth or CX power fails:** +1–2 weeks (RPMH/PAS work), possibly more.

For comparison, touch bring-up cost far more (two wiring/framing bugs, ~20 probe
boots, several days) and the stall investigation cost more still.

---

## 7. Reproduce / resume

```sh
# 1. scratch tree with prerequisites + GPU series
cp -a out/upstream-artifacts/buildtree/xnu /tmp/xnu-pre && cd /tmp/xnu-pre
for p in /ABS/upstream/ios-topaz/xnu/patches/01{31..39}-*.patch; do patch -p1 -f < "$p"; done
for p in /ABS/upstream/ios-topaz/xnu/patches/09[0-4]*.patch;   do patch -p1 -f < "$p"; done

# 2. compile one GPU object with the stock flags (see §3.2)
#    take out/citrus-kernel/SweetFramebuffer.cpo.command.json, replace the
#    source with /tmp/xnu-pre/iokit/Kernel/arm/TopazAdreno.cpp, keep cwd =
#    out/upstream-artifacts/buildtree/build/xnu.obj/DEVELOPMENT_ARM64_SWEET/iokit/DEVELOPMENT

# 3. when ready: add the objects to tools/rebuild-kernel.py, pull firmware,
#    build a probe image (read-only) before any GPU memory or display change
```

Open questions to check before phase 1:

- Does EL1 `smc #0` reach EL3 from Citrus's shim (probe: `PIL_IS_SUPPORTED`)?
- Are Citrus's `a610_zap.*` byte-identical to topaz's embedded ones?
- What do `GPUCC 0x100c / 0x1540` (GX/CX GDSC status) read at boot, and is the
  GPU already powered by ABL?
- Is `qcom,kgsl-3d0` `initial-pwrlevel 6` (320 MHz) actually what ABL leaves?
- Zero-page/RAM headroom: how much of the 1.75 GiB is free after SpringBoard?

---

## 8. Sources (local)

- `upstream/ios-topaz/README.md` §Roadmap 3 (GPU in progress, what works/what's next)
- `upstream/ios-topaz/xnu/patches/0901-topaz-0108-Adreno-610-GPU-TopazGpuW-recipe-behind-da.patch`
  (driver + client + `topaz_fw.c`), `0905` (embedded firmware), `0922` (OPPs),
  `0933`/`0945` (presentation), `0936` (sandbox container), `0947` (exec injection)
- `upstream/ios-topaz/xnu/patches/0131`–`0139` (IOSurface prerequisites, incl.
  empty `IOAcceleratorES`)
- `upstream/ios-topaz/userland/gpu/*.c`, `userland/mesa/*`
- `device-dumps/20261025-141423-923416/live-tree.json` (GPU/GPUCC/SMMU/OPP nodes),
  `memory.txt` (RAM banks, `gpu_region` carve-out), `identity.txt` (`bengal`, POCO M3)
- `out/upstream-artifacts/artifact-manifest.json` (which topaz build the tree and
  object archive come from: `MakrSas/ios-topaz`, run 39419628786,
  `head_sha 2665612a…`)
- this tree: `tools/rebuild-kernel.py`, `tools/mk-citrus-adt.py`,
  `shim/diagnostic.c`, `AGENTS.md` §7 item 7 ("GPU (Adreno 610), Wi-Fi: unported")
