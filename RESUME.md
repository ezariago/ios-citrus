# Resume here — project paused 2026-10-30

The working copy was archived on 2026-10-30 because the project is being put
down for a while. `AGENTS.md` is the detailed handoff (current state, traps,
image hashes, next work); this page is the short "where was I" index and an
honest list of what does **not** live in this repository.

## Where the port stands

XNU boots **iOS 16.7.16 (20H392, iPhone10,3 userland)** on a POCO M3 `citrus`
from a 16 GiB HFSX root on UFS, with:

- 4 KiB kernel pages and **7 CPUs** (4 Gold + Silver 1–3; Silver 0 is owned by
  the secure world and cannot be started);
- the Adreno 610 composing the UI through Mesa freedreno + RedwoodGPU
  (`citrusgl=1`), direct scanout of GPU-pool surfaces;
- FT8719 touch with firmware download, lock screen, unlock, home gesture;
- CPU/GPU/DDR/UFS clocks programmed to their design rates (measured);
- presentation at vsync, **~50 fps** in a real scroll, with a hitch tail
  (25–112 ms frames) and memory-pressure/blur slowdowns still open.

The phone last ran the **seed** boot
`out/citrus-8core/smp7-seed/…` (image `a323b745…`, kernel `3a397fc9…`,
`fbserial=2 fbscanall=1`) on the **full restored root** (`414b3dc6…`). The
pool-guard A/B (`92efea88…`) was not an improvement and is not the resting
image. See `AGENTS.md` §1, §1A, §5 for the exact configuration.

If the phone is still in the state it was left in, **it boots by itself** — the
root and boot image live on the device, not in this repo.

## What this repository contains

| Path | Contents |
|---|---|
| `AGENTS.md` | Active handoff: state, decisions, traps, build/flash commands |
| `AGENTS-RESTORE.md` | Full-root restore and known wallpaper gap |
| `RESUME.md` | This page |
| `README.md` | Project overview and milestone roadmap |
| `kernel/patches/` | The XNU patches (`0001` gates, `0002` display/stall, `0003` Adreno) |
| `kernel/drivers/`, `kernel/experiments/` | Standalone driver probe sources and the unvalidated 4K patch |
| `shim/` | Diagnostic payload (entry, boot-image packing, framebuffer probe) |
| `tools/` | Build, package, flash, pull, verify, audit and test scripts |
| `devices/` | Device JSON, FT8719 firmware blob, GPU firmware + provenance |
| `usb-restart/` | USB-host-driven fastboot/recovery reset |
| `userland/` | iOS userland sources for the GL wrapper / Mesa glue |
| `research/` | Per-topic investigations, source excerpts, manifests |
| `research/artifacts/` | Hashes/provenance of every image and root that existed locally |
| `research/evidence/` | `.tar.xz` of the 101 hardware captures cited by the docs |
| `citrus-*.patch`, `citrus-*-test.py` | Isolated experiment patches + host harnesses |

Every experiment patch applies to the XNU tree used by
`tools/build-citrus-gpu.py`; the host harnesses run without a phone (the reclaim
test also needs the CI build tree, see below).

## What is NOT in this repository

These were local-only, are large or derived, and were **not** pushed. A fresh
clone can rebuild them, but not instantly:

| Missing local artifact | Size | How to get it back |
|---|---|---|
| `out/ios16/ios16-root-*.img` (16 GiB HFSX roots) | 12–14 GiB each | Re-download the IPSW (URL/SHA-256 in `research/artifacts/download.json`), then `tools/build-ios-root-macos.py` + `tools/install-citrus-gpu-userland.py`; `AGENTS-RESTORE.md` has the full procedure. Or keep using the root already on the phone. |
| `out/ios16/` IPSW downloads, mounts, backups | ~53 GiB | Same IPSW; `out/ios16/download.json`. |
| `out/upstream-artifacts/` (XNU build tree, CI artifacts, relink inputs) | ~418 MiB | GitHub Actions artifacts `12263212928` / `12262938798` of `MakrSas/ios-topaz` run `39419628786` (head `2665612a`), or re-run `.github/workflows/xnu.yml`; provenance in `research/artifacts/upstream-artifact-manifest.json`. Artifacts may have expired. |
| `device-dumps/` (stock boot/recovery/dtbo backups, live FDT) | 275 MiB | Re-dump the partitions from the phone in recovery (`tools/collect-device.py`); `device-dumps/…/backups/boot.img` is the boot-image template used by `tools/build-diagnostic.py`. |
| `upstream/ios-topaz/` | 4.7 MiB | `git clone https://github.com/MakrSas/ios-topaz.git upstream/ios-topaz && git -C upstream/ios-topaz checkout e4772911e116ab4ab6c4ac1f38e6106fefe8b483` |
| `out/` build trees, boot images, manifests | ~2 GiB | Rebuild with `tools/build-citrus-gpu.py` / `tools/rebuild-kernel.py`; the kept manifests in `research/artifacts/` record every hash. |
| Uncited captures under `out/ios16/logs/` | ~850 MiB | Deliberately dropped (listener duplicates, superseded probes). Cited ones are in `research/evidence/`. |

The device itself is the durable copy of the working root and boot image. The
on-device root has been mounted read-write and may have drifted from the host
image; that is expected (`AGENTS.md` §9).

## First steps on resume

1. Clone this repo. `git clone git@github.com:ezariago/ios-citrus.git`.
2. Recreate ignored prerequisites:
   `upstream/ios-topaz` at `e477291…` (command above) and, if you need to build
   a boot image, a stock `boot.img` in `device-dumps/`.
3. Read `AGENTS.md` top to bottom — §0 (file rules), §1/§1A (state), §9
   (traps) and §12 (next work) are the parts that cost time to rediscover.
4. Recreate the XNU build tree (CI artifact or workflow) before expecting
   `tools/build-citrus-gpu.py` / `tools/rebuild-kernel.py` to run.
5. If the phone still has the port installed, power it on before changing
   anything; use `python3 usb-restart/reboot.py fastboot` for host-driven
   resets. Do not mount the 16 GiB root read-write on the Mac (§9).

## Where the work stopped (2026-10-29/30)

- GPU composition works but the **remaining gap is GPU work per frame and a
  hitch tail**, not presentation pacing (§1A items 2–3). Two levers are
  measured and closed: clears (~2 ms), MDP/GL scaling (no gain, filters wrong).
- **Pool fragmentation** still fails a 10 MiB request with enough free bytes
  in smaller blocks; the guard experiment did not help.
- New, **host-tested only, never booted**:
  - `citrus-gpu-reclaim-experiment.patch` — opt-in `gpureclaim=1`, drops the
    oldest *completed* pool-backed `fKept` buffers on a pool miss.
  - `citrus-texture-cache-experiment.patch` — bounded growing texture cache.
  No image was built for either; both need review and an A/B on hardware.
- Parked with evidence: SMMU CB0 translation (§6), activation/sandbox, Wi-Fi,
  RPM/LDO power, backlight PWM.
