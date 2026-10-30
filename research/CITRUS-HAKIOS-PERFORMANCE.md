# HackiOS performance comparison (2026-10-27)

Compared the public `oosexgang/hackios-xnu-kernel` main commit
`88513176b1e96ecf0b764cd62c6f4e6ac71345e3` against the running Citrus source
and `gpu-pool2-live.txt`. HackiOS targets POCO X5 Pro / Snapdragon 778G / Adreno
642L, not Citrus's Adreno 610. Its README establishes GPU Mesa ES and working
Control Center, but does not establish near-native FPS for comparable scenes.

Much of the core method is already in Citrus's Topaz-derived `eagl.c`: Mesa
freedreno, mirrored render-target blit, fence handoff, variable-radius blur and
vibrant group handling. Citrus's display driver also already has a two-entry
presenter queue. HackiOS's documented two-entry queue and mirrored blit have
measured gains on its hardware; the latter was already validated on Citrus
against direct rendering, which was visibly broken. Its newer EAGL file differs
substantially, but wholesale replacement is not evidence of a speedup and risks
losing Citrus-specific behavior.

Potentially useful port: HackiOS records timestamps at input, compositor,
swap, GPU completion and presentation (`touch_lat=1`, `tools/latency.py`,
`tools/frames.py`) and has `glslow`. Citrus's wrapper already recognizes
`touch_lat=1` and `glslow`, but its kernel does not emit all corresponding
stages. Add bounded/rate-controlled per-stage timing and measure a repeated
Control Center gesture, then distinguish rendering, queue and input time.
Its display also has adaptive beat pacing; Citrus already has two queued
frames and an actual MDP scan counter, so pacing is a candidate only after
frame timing, not a drop-in replacement. HackiOS touch-specific Goodix SPI and
rate controls do not directly apply to Citrus's FT8719. Citrus polls IRQ and
waits 2 ms per loop; report transport and actual intervals should be measured
before changing controller timings.

`gpu-pool2` user feedback: stress artifacts gone, much better, but animation,
blur opening and input latency still poor. Last pool sample 73 fallback
attempts, six failures, 19–109 ms sampled low-memory searches and 1–2 us pool
lookup. The earlier `gpu-allocprobe` had 233 attempts/207 failures, but the
workloads and capture durations differ; do not present those as a controlled
performance comparison. Zero wrapper errors through frame 3600 is a cumulative
startup-to-that-point count. The roughly 15.7 ms cumulative frame average is
not a frame interval or FPS. A promising separate allocator experiment is to
try an existing pool block before the expensive low-memory search, preserving
fallback to low memory on pool miss; assess contention with framebuffer
surfaces and compare the same workload. This does not by itself guarantee
blur speed or input latency.

## Timing and allocation candidate `gpu-latpool` (unflashed)

Build `out/citrus-gpu-latpool`, image
`out/citrus-diagnostic/citrus-xnu-boot-gpu-latpool.img`, SHA256
`2eea28ffd4a8eac2dc43b2234c0faae173a385e69a51528154d612bd9e0f01ce`.
It retains two-region pool and enables `gpupoolfirst=1 touch_lat=1`. GEM
allocations of 2 MiB or larger try the pool first, then low contiguous memory;
smaller requests and the default (without this arg) preserve the old order.
Pool-miss counters do not imply final failure: low-memory fallback can succeed.
This may consume pool capacity previously left for scanout; assess stress
artifacts and scanout allocation as well as timings. Pool-first is not yet a
hardware-validated fix. The source-level sanitizer tests cover pool/low
success, fallback and ownership failure; framebuffer and two-region tests pass.

`redwood_tl` writes to the existing live nonblocking log ring. `touch_lat=1`
logs FT8719 poll/read (`tl: c`), injected samples (`tl: p`), existing wrapper
frame timings (`tl: g`), GPU waits (`tl: f`), swap handoff (`tl: s`), and
successful direct-scanout surface-wait/present/latch timings (`tl: v`). A latch
timeout is separately logged; a GPU wait failure does not emit a completed
frame line. Capture can have overwritten/interleaved ring lines under load.
Unlike HackiOS, Citrus uses native SweetHID, not its `/dev/hakios-touch`
userland bridge; `tl: i` is not backported. No screenshot recording or physical
input-to-photon latency exists. `tools/analyze-citrus-latency.py` summarizes
observed stage durations and inter-latch gaps without equating these to
end-to-end input latency. Logging may itself perturb performance; compare with
an instrumentation-off boot before claiming a gain.

To fit the payload command line, omitted explicit `sweetptrecord=0` and
`sweetvrecord=0` (both zero-initialized globals), and `sweetusbspinstart=90`
(only used when `sweetusbspin=1`; this profile sets it to zero). Root unchanged;
`gpu-pool2` image remains the user-confirmed fallback. Boot candidate after
fastboot handoff, confirm two pool reservations, CPU/GPU init and lines `tl:`,
then repeat swipe, typing and Control Center gestures and inspect capture with
`python3 tools/analyze-citrus-latency.py out/ios16/logs/gpu-latpool-live.txt`.

### `gpu-latpool` workload

User reports substantially more tasks before artifacts, but poor FPS and input
lag persist. Recent 120 seconds ending at the last touch: 1,599 logged touch
samples; compositor completion-gap median 21.95 ms, p95 30.31 ms (gaps over
500 ms omitted); per-frame compositor duration median 9.37 ms, p95 23.90 ms.
These are aggregate capture windows, not a controlled FPS benchmark. The
instrumented direct-latch `tl: v` events cover only about half of swaps; their
33 ms median gap is an incomplete subset and must NOT be interpreted as panel
FPS. FT8719 IRQ-observation-to-report-read median 2.21 ms, p95 3.47 ms; this
does not measure end-to-end input latency. Timing logs may perturb behavior.

After the workload the sampled pool counts reached 115 attempts/33 pool misses;
those misses can still have succeeded in low-memory fallback. GL 0x505/0x506
occurred in the capture, including immediately after repeated 224-page (3.5
MiB at 16 KiB pages) contiguous-memory search failures and zone GC. This is
consistent with allocation pressure as one possible contributor to artifacts,
but the sampled pool log does not identify the exact failing request or prove
causality. Pool-first removed the expensive search for pool hits but did not
solve capacity/fragmentation, and should not be declared a verified full fix.
Capture remains `out/ios16/logs/gpu-latpool-live.txt`; analysis supports
`--last-touch-seconds 120`. No root change. Timing lines remain active on this
boot and can affect performance.

## `gpu-smmu1`: first translation-mode boot

User authorized the investigation. A boot-only `gpu_identity=0` diagnostic,
with `citrusgl=0`, ran a guarded scatter-write self-test after GPU startup.
The test maps two separately allocated physical pages into adjacent GPU virtual
pages, forcing noncontiguous physical order; actual GPU writes and fence are
required before the service is published. Host ASan/UBSan test covers mapping,
cleanup, wrong data and timeout. Image SHA256
`dd2aeec9d279787556613ecc195a5c33dd1e9f94be8ebd6d982cf3e54409d755`,
manifest `out/citrus-gpu-smmu1/gpu-smmu1-manifest.json`, capture
`out/ios16/logs/gpu-smmu1-live.txt`. Four CPUs and PLL0 succeeded, but the CP
never fetched its SQE: ring rptr 0/wptr 9 and SMMU FSR 0x402, FAR
0xf0000000, FSYNR0 0x00040040. GPU start aborted before either normal IB self-test
or the scatter test; root unchanged. Thus translation is NOT validated. This
is a context translation fault, not proof of its underlying cause. HackiOS's
39-bit TCR versus Citrus's 32-bit TCR is one hypothesis; follow-up opt-in test
records the local software table walk on failure. Userland stays software until
the low-level test passes. The `gpu-pool2` boot remains the user-confirmed
fallback. See ARM's SMMUv2 architecture manual
https://documentation-service.arm.com/static/5f900d34f86e16515cdc08fb and
HackiOS `xnu/files/bsd/dev/hakios.adreno.c` for comparison, not a claim the
hardware configurations are identical.

Follow-up `gpu-smmu39` built, not flashed: only translation-mode TCR T0SZ
changes from 32 to 25 (39-bit VA), selected by `citrussmmu39=1`; the same
4 KiB three-level tables still cover our below-4-GiB virtual addresses. This
mirrors HackiOS's VA width but does not copy its other context configuration.
On command-processor ring failure it logs the SQE IOVA and software L1/L2/L3
entries, providing evidence about the page tables. Same guarded scatter test
and software compositor as smmu1. Host scatter diagnostic test and kernel
build passed; page-table change has not been hardware validated. Image SHA256
`20051ab6b88efafdae7962bd75ad1b441216215e68c4bc10bc9616dd2329e766`,
manifest `out/citrus-gpu-smmu39/gpu-smmu39-manifest.json`. Await fastboot;
`gpu-pool2` fallback retained. Previous test remains on phone, no root write.

`gpu-smmu39` booted with TCR 0x00800019 (39-bit), but still faulted at
0xf0000000 with FSR 0x402 and FSYNR0 0x40040. CPU-side software table walk:
root 0x8f324000, L1[3]=0x8f325003, L2[384]=0x8f326003,
L3[0]=0x8a4c8643. Those values look populated; they do not prove what the
SMMU saw. No CP self-test or scatter test ran. Four CPUs and PLL0 passed;
software compositor and unchanged root. `gpu-smmu39-live.txt` and
`gpu-smmu39-flash.log` hold the evidence. T0SZ alone did not fix this.

The next guarded hypothesis checks SMMU IDR1 page size / register-page count
against the 64 KiB DT register window, and only if the layout is consistent
uses the derived context-bank-0 and GR1 offsets. The previous code hard-codes
0x8000 and 0x1000; HackiOS derives its layout from IDR1. S1CBNDX=4 in the
syndrome may be relevant but does not by itself prove an incorrect offset.
Keep context readout and self-test before attempting compositing. Source-level
ASan/UBSan tests cover IDR1 layout bounds and scatter test logic.

## `gpu-smmudiag`: layout question answered, CP-side output lost in transport

Built and booted a guarded diagnostic (`citrussmmudiag=1 citrussmmureset=1`,
`gpu_identity=0`, 32-bit TCR, software compositor, `citrussmmutest=1`) on the
unchanged root: image `out/citrus-diagnostic/citrus-xnu-boot-gpu-smmudiag.img`,
SHA256 `d3bb3075f6bca4d56650aee055ef63d3ee88a90f484e1b4a416c39c8a5af5980`,
manifest `out/citrus-gpu-smmudiag/gpu-smmudiag-manifest.json`, capture
`out/ios16/logs/gpu-smmudiag-live.txt`.

Hardware-reported registers: IDR0 `4c017e04`, IDR1 `20000005` (4 KiB register
pages, NUMPAGENDXB 2, **five** context banks, zero stage-2-only), IDR2
`00005511` (36-bit IAS / 36-bit OAS), sACR `0000001c` (no CACHE_LOCK),
sCR0 `00210406`, GFSR 0. The vendor rule `cb_base = base + resource_size/2`
gives CB0 `0x8000`, GR1 `0x1000`, and the driver's validator accepted it; the
earlier "derive CB0 from IDR1.NUMPAGENDXB" hypothesis is therefore **refuted**
and the relocation path was replaced by a validator for the vendor rule
(`tools/test-citrus-smmu-layout.py` updated, ASan/UBSan pass). The 64 KiB
window equals 2 x 8 x 4 KiB, matching `IMPL_DEF0=0x2000` / `IMPL_DEF1=0x6000`
in the vendor macros.

The opt-in reset cleared/set ACR to `0000011c` and wrote sCR0 `00211c36`; the
readback was `00211c06`, i.e. sCR0 bits 4/5 are not writable here. SCTLR bit
12 (S1_ASIDPNE) is also not writable (wrote `0x1067`, read `0x67`). CB0 then
read back exactly as programmed: SCTLR `0x67`, TTBR0 `0x8efe4000`, TCR
`0x00800020`, TCR2 `0x61`. So the failure is not a silent CB0 register write.
CB1-CB4 registers read implausible values and CB5-CB7 are outside the five
reported banks; only CB0 is trustworthy. At rest, CB0 FSR read `0x400` with a
stale-looking FAR/FSYNR0, so the earlier FSR/FAR interpretation needs a fresh
read after a controlled fault.

**The decisive part of this boot was not captured.** The USB CDC console
spliced and dropped bytes exactly across the verbose setup dump: the ATOS
self-translation result, the `cp: SQE` / `CP up` lines and any ring fault dump
are absent while the rest of the boot continued normally. A reader reopen (to
replay the kernel ring backlog) instead lost `/dev/cu.usbmodem*`. The 4 MiB
kernel log ring was not overflowed, so this is a transport loss, not a kernel
drop. Next diagnostic must print at most a few short lines; the UFS recorder
(`tools/pull-sweetlog.sh`) is the reliable way to recover the full console if
the transport loses it again.

Unresolved question: whether the SMMU's own walker (CB_ATS1PR) can translate
`0xf0000000` with these tables. Registers still not read back: CBAR, CBA2R,
S1_MAIR0. Next guarded candidate should: print IDR1/ACR/sCR0 plus CBAR/CBA2R/
TCR/TTBR0/MAIR compactly; use the vendor's 36-bit IAS field (T0SZ 28, since
IDR2.IAS=1) rather than 32/39; run ATOS on the SQE and ring IOVAs before the
CP kick; on fault print one line with GFSR/CB0 FSR/FAR/FSYNR0 and the FSR of
the five real banks. `gpu-pool2` has been restored and verified meanwhile.

## Restored `gpu-pool2` after the SMMU experiments

Boot-only flash of the unchanged image
`out/citrus-diagnostic/citrus-xnu-boot-gpu-pool2.img` (SHA256
`aeec7fc4b9bd92cd3afcdaabd29026a3a66f3ef475fb1bd83b6896d7175b9d19`) after the
diagnostic boot. Capture `out/ios16/logs/gpu-pool2-restore-live.txt`, flash log
`gpu-pool2-restore-flash.log`: four CPUs requested/selected, two 64 MB pools
(`0x83890000`, `0x87890000`), SMMU identity, CP up at 950 MHz, GPU self-test
PASS, FD610 CoreAnimation context and RedwoodGPU published. Root unchanged.
This is the current boot and the confirmed performance fallback.

## Root experiment A: one GL submission per frame (2026-10-27 23:30)

First root-side (userland) performance change on the compositor stack.
`eagl.c` used to flush CoreAnimation's draws in `my_glFlush()` and then, in
`frame_end()`, blit the frame into its IOSurface and flush again (plus a fence
whose `glClientWaitSync(...,0)` never waits for the GPU — freedreno's
`fence_flush()` returns immediately on a zero timeout, so the 4.3 ms "waiting"
bucket was the second submit, not a GPU wait). The blit now goes into the
frame's own batch and one `glFlush()` at the end of `frame_end()` sends draws
and blit together. `glonesubmit=0` restores the old order for A/B.

Root image `out/ios16/ios16-root-onesubmit.img` (`352688c5…`, streamed through
recovery/ADB, on-device SHA verified) is the compositor root with the new
`/citrus/lib/libcitrus-gl.dylib` (`af3e822c…`); kernel unchanged
(`gpu-poolarena1`). Control boot image `citrus-xnu-boot-gpu-poolarena1-oldsubmit.img`
(`b846989c…`, same root, two submissions; `sweetusbspinstart=90` omitted to fit
the 607-byte cmdline). Capture `out/ios16/logs/gpu-onesubmit-live.txt`, both
legs, one reader.

Same 60 s sequence in both legs (home-page swipes, Settings scrolling, Control
Center slider drags), frames binned by CoreAnimation draw count (`tl: g`):

| draws/frame | one submission | two submissions |
|---|---:|---:|
| 1-40 | 5.55 ms | 5.99 ms |
| 40-70 | 9.74 ms | 11.04 ms |
| 70-100 | 12.91 ms | 13.79 ms |
| 100-130 | 13.31 ms | 13.58 ms |
| 130-170 | 16.02 ms | 15.38 ms (n=82) |
| 170-260 | 24.70 ms | 24.20 ms |

So 2-12% shorter frames, and the user reported the phone "notably smoother".
But the kernel's own submission counter barely moved (177-187 submissions/s in
both legs, ~4 per drawn frame): Mesa submits on its own for texture uploads and
batch limits, so the wrapper's extra flush was a small part. The ~4 ms
full-frame blit is real GPU work in either order, and the ~10 ms/frame outside
GL calls is CoreAnimation's own software work.

Interpretation: submission ordering is now as cheap as it can be, but it is not
where the remaining frame time is. Do not expect another userland win from
rearranging flushes.

Incidental defect found by the user during this test: holding the volume
slider in Control Center and leaving it makes the old artifact plus a stall.
It is a pool failure, not a wrapper one —
`CitrusGPU alloc: request=10485760 result=failed low_us=30340 free=12894208
largest=4194304 blocks=29`, followed by GL 0x505/0x506. The large arena had
been reduced to 4 MB blocks, so a 10 MiB request could not fit even with
12.9 MB free. The arena split from the poolarena1 build therefore covers the
Control Center case but not the volume HUD's allocation pattern (see AGENTS §2
for the next step).
