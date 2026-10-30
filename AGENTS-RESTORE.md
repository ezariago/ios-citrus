# iOS 16.7.16 full-restore handoff — AGENTS-RESTORE.md

Updated 2026-10-29 20:00 (Asia/Jakarta). **Status: DONE. The rebuilt root
`out/ios16/ios16-root-full.img` (SHA256 `414b3dc6…343d`, 16 GiB) is flashed and
verified on the phone; the user confirmed the full stock app set on the home
screen. Wallpaper is the only known gap (PosterBoard crashes; see FINAL RESULT).**
`AGENTS.md` is untouched (its "next step" is intact); a verbatim snapshot of it
is appended at the bottom of this file as a backup.

## FINAL RESULT (2026-10-29 20:00)

Image: `out/ios16/ios16-root-full.img`, 17,179,869,184 bytes, SHA256
`414b3dc6e84f80e053b23de2af8298e79800aec2b0cfddfa995ce4249b8c343d`; manifest
`out/ios16/ios16-root-full.manifest.json`; boot capture
`out/ios16/logs/fullroot-live.txt`. Flashed with
`tools/stream-image-adb.sh … /dev/block/by-name/userdata` (16 × 1 GiB, all
rc=0); the on-device SHA-256 readback matched exactly. Device serial
`2103d88d0621`, recovery ADB as root.

Contents: 175 bundles in `/Applications` (the 32 staged stock apps moved in,
`staged_system_apps` and `AppPlaceholders` empty), cryptex merges hard-linked
(OS 8, App 11, dyld cache 44), compositor wrapper + real `backboardd` + three
`citrus/lib` dylibs installed and signature-verified, ownership default
`0:0`, `/private/var/mobile` 501:501, `/private/var/Keychains` 64:64. `fsck_hfs
-fn` clean including the multi-linked-file check. Boot reaches SpringBoard and
the compositor (`redwood-gl` frames, presents, touch), no panic.

**Ownership tooling — the trap that cost three rebuilds.** The order that works
on a fresh assembly is: copy sources with `rsync -a` (**no `-H`**), create the
var seeds/keybag/tweaks/app moves/compositor files, then run the catalog
ownership rewrite **while the volume has no hard links**, then (and only then)
create the cryptex/dyld hard links with the volume mounted — new links inherit
the source's `0:0`. Do not run `tools/hfs-chown-inplace.py` on a volume that
already has hard links: even though it writes the correct owner bytes, fsck then
reports `Incorrect number of file hard links` and repairing breaks the link
chains (`Next/Previous ID in a hard link chain is incorrect`).
`tools/hfs-owners.c` (libdmg) is worse here: it kept the tiny test volume clean
but on the assembled 16 GiB image it left the catalog unreadable (`fsck_hfs`
traps with `Trace/BPT trap: 5`, `hdiutil` reports "no mountable file systems"),
consistent with the standing "never run it on a real root" rule. Root
`ios16-root-glscale2.img` (`d93f163a…`) is untouched as the fallback.

**Known gap — wallpaper.** SpringBoard shows the full app set but no wallpaper.
`PosterBoard` crashes at launch (SIGTRAP, then SIGABRT on relaunch) and there is
no poster/wallpaper store in `/private/var/mobile/Library`; the offline restore
never ran Setup Assistant, so nothing seeded one. This is a port/userland issue
separate from the app restore; the old root's `/private/var` contains only
`SBLastRestoreIdentifier`, so there is nothing to copy from it. Also observed
under heavy use: `redwood-gl: more textures with IOSurfaces than there is room
for` (`-texImageIOSurface … not done`) — the wrapper's texture cache runs out,
another compositor-side item, not an image defect.

## 0. What was asked

The user wants a **clean rebuild of the iPhone X (d22ap) iOS 16.7.16 userland**
from the IPSW into the 16 GiB HFSX `userdata` image, so the device contains the
real iOS with **all stock apps**, not the current root that shows only a handful
of apps. Keep the Citrus XNU kernel and the working port; then flash.
This is deliberately not the AGENTS.md performance work.

## 1. Why the current device looks "stripped"

The current root (`out/ios16/ios16-root-glscale2.img`, image SHA256
`d93f163a…7883a0`) is a complete copy of the OS + SystemOS + AppOS dmgs, but it
was assembled **offline**, so it never went through the restore/first-boot app
installation:

- `/Applications` has **143 entries**, but almost all are hidden services
  (`*ViewService.app`, `*UIService.app`, …). Core visible apps such as Maps,
  Music, Calendar, Notes, Mail, Weather, Stocks, Books, Podcasts, Wallet,
  Files, Health, Home, Tips, Translate, Measure, Voice Memos, Contacts,
  FaceTime, Shortcuts, TV, News, Find My, Fitness, Freeform, Calculator,
  Compass, Magnifier, Reminders, Bridge, SequoiaTranslator, MobileStore are
  **not** in `/Applications`.
- Those 32 apps (496 MB) are still sitting in
  `/private/var/staged_system_apps/`.
- There is **no** `/private/var/mobile/Library/MobileInstallation/` database.
- `/System/Library/AppPlaceholders/` still has the 32 matching placeholder
  stubs.

The 10 MB `Cryptex1,AppOS` is **normal** for this build (Safari-support
cryptex only, 4.4 MB mounted); the visible apps come from the OS dmg's staged
directory. Do not "fix" the AppOS size.

## 2. Downloaded sources (all local, verified)

Directory: `out/ios16/restore/` (13 GB).

| file | bytes | digest | checked against |
|---|---|---|---|
| `iphoneX-16.7.16.ipsw` | 6,171,035,648 | sha256 `ece1194f7e233e9109c5790a8d23a4564a10a254e15ec5b09978a343265568fb` | `out/ios16/download.json` |
| `087-86698-044.dmg` (OS) | 4,730,814,044 | sha384 `103b835176572a97ae36bc5ebe4c332c40b921e1f151b844116bbda49959c46c64364d343ceb0c4e9d95a51ba60d0e51` | BuildManifest `OS` |
| `087-86593-047.dmg` (SystemOS) | 2,743,074,816 | sha384 `775e110985ba8fd0dd2ad21d3fd5a896eec8887af219fc0dbc1e55ace791de1d51ecca2477f2e650b24c557cb74a0627` | BuildManifest `Cryptex1,SystemOS` |
| `087-86715-047.dmg` (AppOS) | 10,485,760 | sha384 `853c4f945ea09b1614bedeaffc777aefdf2c5bcb15f1a66986e965207757246c2d3f8712a5a5c491cfc49a5a45e81502` | BuildManifest `Cryptex1,AppOS` |
| `BuildManifest.plist` | 449,774 | sha256 `2d1452103a2f5ad71cb78d94454977fc70632472201980a468c247fba14b10b7` | IPSW member |

Also extracted: `Firmware/087-86698-044.dmg.{mtree,root_hash,trustcache}`,
`Firmware/087-86593-047.dmg.{root_hash,trustcache}`,
`Firmware/087-86715-047.dmg.{root_hash,trustcache}`.

Sanity mounts (read-only) confirmed: OS `/Applications` = 143, OS staged apps =
32, SystemOS = 2.4 GB, AppOS = 4.4 MB. Build identity used: **index 1
(`d22ap`, ApBoardID 0x06)**; the same dmgs serve both d22ap identities.
Host free space after extraction: **23 GiB** (enough for the ~11 GB root plus
the 16 GiB flash read; the five 16 GiB roots under `out/ios16/` are APFS clones
and cost almost nothing).

## 3. Rebuild plan (not started)

### 3.1 Create a fresh 16 GiB HFSX volume — do NOT use `hfsplus grow`

The previous image was made with `hdiutil create 128m` + `out/libdmg-hfsplus`
`hfsplus grow 16GiB`, which produced **`Invalid catalog PEOF`** (see
`out/ios16/fsck-*.log`) and needed the historical catalog-extents reconstruction
/ fileID-8 extents-overflow repair. A direct large create avoids that class of
bug:

```sh
hdiutil create -size 17179869184b -fs 'Case-sensitive Journaled HFS+' \
  -layout NONE -type UDIF -volname iOSRoot out/ios16/restore/root-seed.dmg
hdiutil attach -owners off -nobrowse -mountpoint out/ios16/root-mount \
  out/ios16/restore/root-seed.dmg
```

The phone wants a raw 16 GiB image; after assembly:
`hdiutil convert out/ios16/restore/root-seed.dmg -format UDRW -o <raw>.img`
(or keep the raw device read from the mounted image at flash time). Verify the
final byte size is exactly 17179869184 like the existing roots.

### 3.2 Copy the sources (same layout as `tools/build-ios-root-macos.py`)

- OS dmg → `/`
- SystemOS dmg → `/private/preboot/Cryptexes/OS`
- AppOS dmg → `/private/preboot/Cryptexes/App`
- hard-link every cryptex file to its root-relative path (skip existing paths,
  never follow symlinks out of the image), link
  `Cryptexes/OS/System/Library/Caches/com.apple.dyld/*` into
  `/System/Library/Caches/com.apple.dyld/`
- create `/private/var/keybags/systembag.kb` (mode 0600, `{'KeyBagKeys': b'SWEET'}`)
- run `upstream/ios-topaz/tools/sweet-root-tweaks.py <mount>`; record the
  chown overrides to `out/ios16/root-owners.tsv`
- keep `/private/var/staged_system_apps` for the next step.

Do **not** rerun the whole old builder blindly: it calls `hfs-owners.c`
(libdmg `updateCatalog`), which AGENTS.md §5 says must not be run on a real
root. Use `tools/hfs-chown-inplace.py` instead (never touches the B-tree;
defaults 0:0, `/private/var/mobile` 501:501, then the TSV overrides).

### 3.3 Install the 32 staged system apps (the actual missing piece)

For each `*.app` in `/private/var/staged_system_apps`:

1. `mv` (same volume) to `/Applications/<name>.app`; chown 0:0, mode 0755.
2. remove the matching `/System/Library/AppPlaceholders/<name>.app` stub.
3. leave `/private/var/staged_system_apps` empty.

Expected: on boot `installd`/LaunchServices scans `/Applications` and registers
the system apps, so SpringBoard shows the full icon set. **This is the one
unverified assumption** — if the icons still do not appear, the next levers are
`/usr/libexec/MSUEarlyBootTask` (it is exactly the mover for
`staged_system_apps`; strings show "Found data created by previous ramdisk" and
"Assuming first boot after update") or creating the MobileInstallation database.
Do not flash twice without capturing the first boot's console.

### 3.4 Re-apply the Citrus userland

The working compositor files (from `ios16-root-glscale2.img`) are:

- `/citrus/lib/libOSMesa.8.dylib` sha256 `e0c7ba1d…7894`
- `/citrus/lib/libcitrus-gl.dylib` sha256 `d218d1e1…b50f0`
- `/citrus/lib/libcitrus-loader.dylib` sha256 `2fb666f1…c54f`
- `/usr/libexec/backboardd` (wrapper) sha256 `c87ed2e0…d2df`
- `/usr/libexec/real/backboardd` (original, preserved)

Either run `tools/build-citrus-eagl.py`, `tools/package-citrus-gpu-userland.py`,
then `tools/install-citrus-compositor.py --image <raw> --source-sha256
<new-base-sha256> --apply` (always pass `--image`), or copy those five files in
and fix ownership with `tools/hfs-chown-inplace.py --only-overrides`. The
wrapper only injects GL with `citrusgl=1`; `glscale` stays off.

Also carry over the historical repairs from AGENTS.md §5:
`/private/var/Keychains` → 64:64, the Wi-Fi identity under
`/chosen/mac-address-wifi0`, and a clean `fsck_hfs -fn` before flashing.
Expect the same `Invalid catalog PEOF`/extents checks a fresh build always
needs; do not flash an image that has not passed `fsck_hfs -fn`.

### 3.5 Verify, then flash

- mount read-only: `/Applications` must contain the 32 app bundles, staged dir
  must be empty, `/citrus` and wrapper present.
- `fsck_hfs -fn` clean; raw size 17179869184.
- Flash with recovery + ADB (`fastboot` rejects ≥2 GiB):
  `tools/stream-image-adb.sh IMAGE /dev/block/by-name/userdata` (16 × 1 GiB,
  ~37 s/GiB), then verify the on-device SHA.
- Boot, capture the console (`tools/usb-log.py`), confirm the home-screen app
  count and launch a few apps.

## 4. Standing traps (carried from AGENTS.md)

- Keep `ios16-root-glscale2.img` (`d93f163a…`) as the fallback root; do not
  delete it or any cited log.
- Never mount a 16 GiB root read-write and then whole-image-hash it on this Mac
  (page-cache exhaustion hangs every app). Hash with `F_NOCACHE`
  (`/tmp/sha-nocache.py`) or pass `CITRUS_IMAGE_SHA=…` to skip the script's
  re-hash; the on-device readback still verifies.
- One USB reader only (`pgrep -fl usb-log.py`); a 0-byte capture means a stale
  `/dev/cu.usbmodem*` node — kill, confirm the node mtime changed, restart.
- `sweetufstrace=0` means trace from t=0, not off. `sweetwdt=0`.
- The 32 staged apps are *system* apps: ownership must stay 0:0 and code
  signatures must not be altered; move bundles, do not re-sign.
- Do not modify `AGENTS.md`, `kernel/`, `tools/`, `research/`, `devices/`,
  `upstream/`, `userland/`, the root images in AGENTS.md §5, or cited logs.
- `du` lies on the APFS-cloned 16 GiB roots; measure with `df -k`.

## 5. Where this stopped

Sources complete and verified; rebuild not begun; no mounts left attached
temporarily (`/tmp/osmnt`, `/tmp/sysmnt`, `/tmp/appmnt` are only for the sanity
check and can be detached). Phone: `fastboot devices` → `2103d88d0621
fastboot`; boot image and root on the phone unchanged.

Next action on resume: step 3.1 (create the fresh 16 GiB HFSX), then 3.2–3.5.

---

# Appendix — verbatim snapshot of AGENTS.md (2026-10-29 15:22, 73,060 bytes)

# Citrus XNU port — active handoff

Updated 2026-10-29 06:05 (Asia/Jakarta). This is the only handoff file. Keep it
under ~30 KB: new results go in the top sections, superseded narrative goes to
`research/` and is deleted here. Current readable investigations:
`research/CITRUS-GPU-IMPLEMENTATION.md`, `CITRUS-HAKIOS-PERFORMANCE.md`,
`CITRUS-IDLE.md`, `CITRUS-TOUCH.md`, `CITRUS-CPU-CLOCK.md`,
`CITRUS-CLOCK-SPEED.md` (current clocks), `CITRUS-GPU-CLOCKS.md`,
`CITRUS-BACKLIGHT.md`, `CITRUS-BUTTONS.md`,
`CITRUS-CROSS-PROJECT.md`, `XNU-NEXT.md`.

## 0. FILE & WORKSPACE RULES (read before building anything)

1. **Replace, don't accumulate.** When a build produces a newer artifact, delete
   the artifact it supersedes in the same turn. No `...-v1/-v2/-final` chains,
   no per-boot kernels or payloads left behind.
2. **Keep only:** the current boot image, the named fallbacks in §3, one
   manifest per kept image, and logs cited here or in `research/`. Everything
   else under `out/` is disposable.
3. **Promote by rename.** Build to `out/citrus-gpu-<name>`, package to
   `out/citrus-diagnostic/citrus-xnu-boot-<name>.img`, record its SHA256 here,
   keep `<name>-manifest.json`, then strip the build tree's objects/`citrus.a`
   (regenerate with `tools/build-citrus-gpu.py`). An unflashed candidate that
   is replaced without ever booting should not keep an image at all.
4. **Never delete or modify:** `kernel/`, `tools/`, `research/`, `devices/`,
   `upstream/`, `userland/`, the two root images in §5, or cited logs.
5. **`du` lies here.** The 16 GiB root images are APFS clones of one ~13.6 GiB
   extent set; `du` counts shared blocks per file. Measure real reclamation with
   `df -k` before/after, not `du`. Deleting one clone can free 0 bytes.
6. **Temporary files go to `/tmp`.** If one must live in `out/`, name it after
   the experiment and delete it when the experiment ends.
7. **One durable USB reader only.** `pgrep -fl usb-log.py` first; start with
   `nohup python3 tools/usb-log.py --wait 900 -o out/ios16/logs/<name>-live.txt
   >/tmp/<name>-reader.out 2>&1 &` and record the PID.

## 1. CURRENT STATE (2026-10-29 01:05)

**2026-10-29, surface reuse diagnostic booted:** current phone image
`out/citrus-8core/smp7-reuse/citrus-xnu-boot-4k-smp7-reuse.img`, SHA256
`c8960b9da5eb9e0ac56a08eee25c13f6327aecb4086d4bf81b47da9bb00f3a0d`;
kernel `ea90240914d4947720ad928274912738a0d0d35fa5985a4ff6d6c0e15b2de5f8`.
User says performance similar to cached-scan, slight tearing remains, touch felt
slightly weird. Capture `out/ios16/logs/4k-smp7-reuse-live.txt`; reader stopped.
`cachedscan` (`99b8e8...`), `trylock` (`d55b2d...`), `serial`, `overlap`,
`scanout`, `gpu40` are fallbacks. Fastboot boot unsupported; no userdata flash.

Incremental `citrus-scan-reuse-observation.patch` rechecks each cached scanned
surface's `drawn` fence after latch, just before the next direct present. In 12
windows of 256 direct attempts, 126–128 rechecks per window had **0 changes**.
This is NOT proof of no writes while displayed: `drawn` tracks GPU submissions
that name the surface, not CPU writes; it misses activity before the first
sample and surfaces replaced by the timer, and the read is best-effort. Shim
PASS, hardware booted; no timing or physical FPS claim. Next investigate CPU
writes to the shared cached default surface and MDP latch/scan timing, and test
whether separate protected scanout buffers can retain the throughput gain.

In the 4K CI working tree,
`out/citrus-8core/ci-run-40531392449/tree/xnu/iokit/Kernel/arm/SweetFramebuffer.cpp`,
per-hitch logging is replaced with a 256-frame aggregate for 25–250 ms intervals
(count, queue nonempty, MDP busy, maximum previous GPU wait). The independently
applicable `citrus-frame-hitch-aggregate.patch` was verified forward and reverse
against the gpu40-derived CI source. `/tmp/relink-smp7.py` linked kernel SHA256
`8dc8ac7e44192df5adf02deb37d82ca1b1c7d3ffe4dad86c38b114f59fada85d`;
its aggregate string is present and the old hitch string absent. A `/tmp` payload
using the exact gpu40 ADT and cmdline passed Unicorn shim entry/boot-args testing;
this did **not** execute XNU; the later scanout build above was booted. The
250 ms cutoff filters long idle gaps, not all idle gaps; previous-present data
are correlation, not proof of cause. The user reports smoother motion but no
controlled FPS improvement is established.

**Follow-up: scanout attribution, not physical FPS.** In `showDirect()` the
existing `frameShown()` runs *before* `present()` and before the flush poll;
`showPending()` counts before its pending frame is shown and can replace it.
Thus neither the histogram nor `swaps` by itself proves unique frames reached
the panel. The CI working tree and `citrus-frame-hitch-aggregate.patch` now add
one aggregate per 256 direct attempts: GPU-pool direct scan programming, flush
bit clear, zero observed fence, failed GPU wait, and repeated surface/fence pair.
These are best-effort observations, not a pixel hash or panel-vsync measurement;
the fence is sampled before the wait and can change concurrently. The modified
translation unit compiles and the patch applies forward/reverse. A further
histogram now times intervals *after* the direct-path flush bit becomes clear,
instead of only at `showDirect()` entry. Flush completion is still not proof of
actual panel pixels or unique content. Relinked kernel SHA256
`5d8f03e7d38147f3697741358deb2e666b1ee23dac3d2afb86f7abe31358593d`;
`/tmp/citrus-scanout-diagnostic.img` SHA256
`c1397f9177bb8ed5f07071c41caefcd629fd20446e5cfe56642a2b4357405434` uses the
`gpu40` ADT and command line, passes the Unicorn shim entry/boot-args test and
preserves the template's other boot components. Hardware capture shows three
256-attempt windows each with **256 direct scans and 256 flush clears, zero
failed GPU waits**, and 3/0/1 repeated surface/fence pairs. Direct-only
flush-clear intervals cluster at 25–58 ms, but they exclude other display
updates and do not establish physical frame rate. Traces also contain non-pool
`dp-surf ... 0` interleaved with pool surfaces, contrary to the earlier claim
that every UI present was pool direct. `vsyncFired()` and `showDirect()` can
both call `present()` outside `fLock`; capture actually shows their calls
interleaving (e.g. log lines 3496–3510), but stale scanout has not been proven.
The **booted** follow-up (`citrus-frame-hitch-aggregate.patch`) counts calls
that begin while another `present()` is active: **113, 108, 135 overlaps** per
three windows of 256 direct attempts; observed scan-ID regressions 6/4/5 out
of 463/446/455 samples. These regressions are not proof of displayed order:
field `0x50` semantics are not verified, and `flipFrom()` can take time after
sampling. This confirms a concurrency hazard worth investigating, not its effect
on the panel. Next: design a single ordered commit path that preserves vsync and
surface holds, or instrument actual MMIO commit with a driver-owned sequence;
measure frame pacing and check for regressions before changing default behavior.
Host reset with a writable mounted filesystem is unsafe.

**Booted serialization A/B:** `citrus-present-serialize-experiment.patch`
adds opt-in `fbserial=1`, a separate mutex covering `present()` and associated
hold updates on the timer and direct-present paths. It avoids simultaneous calls
but **does not guarantee FIFO**: the timer can take an older pending record
before acquiring the mutex. It can also block the vsync workloop while GPU
waiting or latch polling, causing dropped pacing; hold-lifetime and visual tests
are mandatory. Default off. Kernel `2509bd8872e323572e8596abd566a2f314087fa6bf25b4660807a54039445459`,
`/tmp/citrus-serial-diagnostic.img` SHA256
`efedf24be680a2313ff3b18679b524c9d198c3ee86a3b4e3a3dbbcaac9d6f0d8`; linked,
shim PASS, non-kernel template components unchanged. On hardware the overlap
counter was 0 in both 256-attempt windows (versus 108–135 before); sampled
field-0x50 regressions were 1 in each, still not proof of display order. User
reports fewer apparent skips but lower apparent FPS, with no visual faults.
This is a diagnostic, not a validated performance fix. Next investigate a
nonblocking ordered commit path and independent physical frame-rate measurement;
retain `overlap` as fallback.

**Booted try-lock A/B:** incremental `citrus-present-trylock-experiment.patch`
on top of serialization adds `fbserial=2`: timer tries the presentation mutex
under `fLock` without waiting; if busy, it leaves pending and retirement holds
unchanged and rearms after notifying vsync. It acquires the mutex before taking
a pending record, avoiding the serial mode's extracted-old-record race. This
is still not FIFO and timer-side `present()` can itself block. Test for hold
lifetime, contention, motion, visual corruption and actual panel rate; counter
`timer present deferrals` reports busy ticks per 256 direct attempts. Kernel
`3ecf00ab3fdeda4664d55672ae3223dff856d37023791fe7c7899a79f16c781a`,
`/tmp/citrus-trylock-diagnostic.img` SHA256
`d55b2d8e664c55cdc20db406e4351d08be80ac956bd85f6281c6667c8bfc1f70`;
linked, patch forward/reverse dry-runs and shim PASS. Hardware test: four
256-direct-attempt windows show 0 overlapping calls and 0 field-0x50 sampled
regressions; busy timer deferrals 157/130/187/173, each including ticks even
when no pending frame existed. User reports much better motion and touch, no
visual problems, but still visibly low FPS. This is not evidence of 60 fps or
proof of correct display ordering; long-duration hold lifetime, power transitions,
and independent physical frame-rate tests remain needed.

**Booted cached-scan experiment:** `citrus-cached-scan-experiment.patch`
applied after the try-lock patches adds `fbscanall=1` (requires `fbserial=2`
and surface holds). For geometry-eligible cached non-pool surfaces it uses the
presenter queue, cleans the CPU cache and scans the held original instead of
copying 10 MiB to a flip buffer. Earlier direct scan without adequate producer
cooperation showed half-drawn frames: **tearing/stale pixels remain a serious
risk**, as do CPU/GPU cache coherency and long-held surface starvation. Only an
A/B test showed a user-perceived substantial speedup, with **slight tearing**
when scrolling very fast; do not claim correctness or promote to default. Heavy
control center still slows down. The existing wait-failure handling remains
unchanged and is not a safety guarantee. Counts include `cached direct scans`.
Kernel SHA256
`27157b2dd585fe1e9df1d2ac19896b5d28d55fa2f44e28f4eb1571f9840ca0f6`,
`/tmp/citrus-cachedscan-diagnostic.img` SHA256
`99b8e821fc8322be0b6295dec5275c19b06a4a3ff38d0f52ce266e9d37a12581`;
compiled/linked, reverse patch dry-run, shim PASS and hardware booted. In many
256-attempt windows, ~128 cached scans, 0 overlaps and 0 failed waits; example
flush-clear interval buckets 0/119/106/12/13/1/3/2. These now include cached
and pool scans, unlike the earlier direct-only histogram, and do not prove panel
FPS. Next investigate whether tearing is caused by in-use reuse, incomplete GPU
fencing, or scanout timing; test lifetime and coherency, not just visual speed.
Keep trylock as fallback and do not alter userdata.

**Separate unbooted refill experiment:** `citrus-gpu-refill-experiment.patch`
is opt-in (`glgpurefill=1`, default off), applied to a `/tmp` copy only. For a
screen-sized, non-inverted mirrored BGRA target it attempts to blit the imported
surface to the target texture on the GPU, holding the IOSurface read lock until
`glFinish`, and falls back to the CPU upload if the FBO/blit fails. A `/tmp` iOS
arm64 dylib linked and ad-hoc signature verified (SHA256
`19c75490021cbc29f4aca48ac7daaf3c342232ad3c2ddc2c5b70cf61a8ae8cb3`).
No GL correctness, cross-process synchronization, runtime or performance testing
has been done; do not install on the phone without those checks. This experiment
needs a root-image decision; no root was modified.


**Historical gpu40 assessment:** 4 KiB / 7 cores with GPU composition; ~50
swap requests/s was measured, but physical unique-frame rate and the cause of
felt stutter remain open as clarified above.
Previous image (fallback) `out/citrus-8core/smp7-gpu40/citrus-xnu-boot-4k-smp7-gpu40.img`, SHA256
`669cf4cfb51dc95e5762ea8725718ef614e042cb513b7c1338a45dded804e4af`, kernel
`0abf7719195e74b3fc0b39dec2ba7143c310a1468f47749156fb2201e16b2577` - it carries the per-hitch
attribution line and no longer runs a 10 MiB pixel census whose result it threw away (capture
`4k-smp7-gpu40-split.txt`). Fallback `smp7-gpu29` (`f82290e748d0...`, kernel `aac49e76...`,
user-confirmed smoother with `gpuagain=16`) and `smp7-gpu20` (`3e0e03924a99...`) stay; `smp7-gpu37`
(the GL-scale experiment) and `smp7-gpu39` are deleted. All of them carry the frame-interval
histogram, the MDP latch probe, GPU fence timing and lock-free surface accounting.
7/7 CPUs, Gold 2016 / Silver 1804, GPU 950 with `CP up`, UFS 200/150/300, `citrusgl=1`, no panic.
**Ranked levers after 2026-10-29:** (1) whole-surface clears - measured, ~2 ms, not it; (2) render
smaller - **both routes closed**: the MDP small mode needs an `IOSurfaceAccelerator` service we do
not have, and the in-wrapper GL scale measured no gain (263-270 vs 205-267 presents/5 s); (3)
present pacing - not a 30 Hz lock, already vsync-paced; (4) SMMU CB0 - parked with a verdict (§6).
What remains is the GPU's own work per frame and the 2-deep presenter queue that turns a late GPU
frame into a blocked `swap()` (§1A item 2b). **The 4K "compositor stall" was one 90 ms allocation
per 10 MiB surface**; `gpupoolfirst=1` fixes it. The GPU-off clock build `smp7-clk` (`de95df37...`)
and `smp7-ent8` (`a00de0c8...`, CPU-300/MHz reference) stay as fallbacks. The 16 KiB GPU line below
is the older, more complete userspace: it is the reference for "what a clean boot looks like" and
the fallback if a 4K experiment fails.

16 KiB reference: `gpu-poolarena1` (4/4 CPUs, PLL0 950, identity SMMU, FD610,
self-test PASS, 8 crashes in 3 minutes, `gpu-poolarena1-live.txt`) with root
`ios16-root-onesubmit.img` (`352688c5...`). **16 KiB lessons that still
matter:** one submission per frame is user-confirmed smoother; the
`gpu_pool_alloc` arena split still fails the volume-slider 10 MiB hold (§2);
`SweetHID.cpp` is missing from 0002's FILES (the 4K relink compiles it
explicitly).

## USB PMIC restart (2026-10-28)

`python3 usb-restart/reboot.py fastboot|recovery --device /dev/cu.usbmodem…`
sends `citrus:reboot:*` to the CDC console; `sweet_usb.c` parses it and runs
the PM6125 PON/IMEM restart reason plus `PSCI SYSTEM_RESET`. Verified on
hardware through a full flash cycle (serial 2103d88d0621 in fastboot, and the
user visually confirmed recovery). Commands work only while the USB poller
runs; resetting with a writable filesystem mounted is unsafe. PMIC-aware image
`out/citrus-8core/gold2-usbpon/…` `14ebd4fb…` (kernel `3fc70396…`). The
`misc` first block is byte-identical to its pre-test backup; no restore needed.
Details in `research/CITRUS-CROSS-PROJECT.md`.

## USB diagnostic evidence (2026-10-28)

Receive ping acknowledged on enumeration (`4k-gold2-usbrx-live.txt`); the
receive-hook console path stays silent after boot, and the IMEM-only and
`bootonce-bootloader` resets both just rebooted (no demonstrated target mode).
The working reset is the PMIC one above. Details in
`research/CITRUS-CROSS-PROJECT.md`; do not repeat those two tests.

## 1A. ALL-CORE / 4 KiB STATUS (2026-10-29)

- **DONE: 4 KiB, 7 cores, lock screen, touch, home gesture.** Current boot
  image `out/citrus-8core/smp7-ent8/citrus-xnu-boot-4k-smp7-ent8.img`, SHA256
  `a00de0c834d471116bcd9a71532492dad5311daf2acb331cd224165937cc2985`, kernel
  from `/tmp/relink-smp7.py`, shim PASS, capture
  `out/ios16/logs/4k-smp7-ent8-live.txt`. `7/7 CPUs initialized, SGI1
  verified`; 4 crashes in three minutes (all `driverkitd`, the 16 KiB
  reference has 8); zero code-signing assertions; ~64 fps presenting.
  **User-confirmed: lock screen with a live clock, touch, and the home
  gesture.** Full account: `research/CITRUS-4K-BOOT.md`.
- **DONE: every clock this port owns is at its designed rate, measured.**
  Gold 300 -> **2016 MHz** (EPSS LUT state 8), Silver 1305 -> **1804 MHz**
  (state 7), GPU 600 -> **950 MHz** (`PLL0 1900 OUT_AUX2/2`, `CP up core
  950 MHz`, `selftest PASS`), DDR at the top OPP (**8.5-9.3 GB/s** measured
  8 MiB copy), and now **UFS**: the bootloader left `ufs_axi` at 120 MHz
  (GPLL0/5) and `ufs_unipro` at 100 MHz (AUX2/3); both are programmed to the
  board's design maxima **200 and 150 MHz** with `ufs_ice` already at **300**
  (divider-only RCG updates, readback confirmed, UFS root mounts read-write
  afterwards). `tools/verify-clocks.py` over the captures is **12 pass / 0 fail
  / 0 missing**. Image `de95df37...`; captures `4k-smp7-ufsrate-live.txt`
  (first programmed boot), `4k-smp7-ufsdefdiag-live.txt` (default-on proof),
  `4k-smp7-ufsfinal-live.txt` (resting build). `sweet_cpufreq.c` now decodes BOTH clusters,
  `sweetcpufreq=1` = designed top (boost), `=2` = sustained (top-1), plus
  `kern.sweet_cpu_state` to switch at runtime. **The tick counter is 19.2 MHz,
  not 24** -- every earlier frequency claim in this file that used 24 is 1.25x
  high. Full account and open items: `research/CITRUS-CLOCK-SPEED.md`.
  **The remaining blocks are classified, and nothing is left to program:**
  **UFS is AP-owned** and now at its design maxima (above); **SNOC/CNOC/BIMC
  are RPM-owned** (`rpmcc *_MSMBUS_CLK`, `bengal-bus.dtsi`) so no AP code can
  set them and the bandwidth probe is their evidence; **PCIE does not exist on
  bengal**. `gcc_bimc_gpu_axi_clk`/`gcc_gpu_snoc_dvm_gfx_clk` are branches off
  that same RPM-driven fabric. Detail: `research/CITRUS-CLOCK-SPEED.md` §6.
- **DONE: the Adreno 610 composes on 4 KiB / 7 cores.** The "stall after 10-15
  frames" was never a hang: every full-screen CoreAnimation surface is 10 MiB,
  `RedwoodGPU.cpp` tried the low-memory allocation first, and for 10 MiB
  physically-contiguous that call **takes 80-110 ms to fail** before the
  reserved pool answers in 3 us — so 1-2 allocations per frame cost 100-300 ms,
  i.e. **3-5 fps**. `gpupoolfirst=1` asks the pool first for >= 2 MiB and falls
  back on a miss: frame cost fell from **112,994 us to 7,782 us** on the same
  workload (302 calls/40 draws), allocations now 1-2 us, frames continue past
  the old 15-frame point with fences climbing. `citrusgl=1` is now the resting
  configuration (`smp7-gpu10` `01599318...`, capture `4k-smp7-gpu10-live.txt`).
  **Where the rest of the frame goes (measured during a real swipe,
  `4k-smp7-gpu11-samples-live.txt`, wrapper summary at 800 frames):** 13.48 ms
  of work a frame - 5.37 ms `glFlush`, 5.49 ms waiting for the GPU, 1.25 ms
  making textures from IOSurfaces, and 7.91 ms of it *outside* GL calls
  (CoreAnimation's own CPU); 479 calls / 93 draws a frame. But only ~23 frames
  arrive a second, i.e. the compositor is idle ~76% of the wall time waiting
  for the next frame: the present/latency chain is costing ~2.7 vsyncs a frame,
  not raw CPU. Kernel side is cheap: 1343 submissions in 5.4 s (10 a frame),
  43 buffers each, 278 us flushing each. **ANSWERED (07:55, the same day, with
  fence timing now in the kernel): the port is GPU-bound, not
  present-bound.** Every submission's fence is stamped at the CP kick and again
  when the fence is seen passed; ~1,400 submissions in 5 s take **8.0 ms of GPU
  time each, 190 of 212 over 4 ms** (~277 submissions/s). The Adreno 610 is
  saturated on ~93 draws + 10 clears over 10 MiB surfaces (~85 us a draw =
  fill/bandwidth bound). Raising the rate now means **cutting GPU work**: (a)
  UBWC/bandwidth compression on the composited surfaces (the kernel already
  reports `HIGHEST_BANK_BIT 14`, `UBWC_SWIZZLE 7`, `MACROTILE_MODE 0`), (b) one
  GPU blit a frame instead of per-layer mirror copies and redundant
  whole-surface clears, (c) fewer submissions a frame (Mesa implicit flushes;
  the wrapper's `glonesubmit` is already 1). Detail:
  `research/CITRUS-4K-GPU.md` §2.
  **What the three levers actually turned out to be (08:05, `glframes=1`):**
  (a) **UBWC is already on**: Mesa 25.0.7's `get_best_layout()` returns UBWC for
  every a6xx resource unless `FD_DBG(NOUBWC)` or the bind flags forbid it, so
  there is nothing to enable there; the 10 MiB IOSurfaces themselves must stay
  **linear** (`PIPE_BIND_SHARED` + display scanout), which is the traffic UBWC
  could not have compressed anyway. (b) **the wrapper already draws in place**
  (`1 in place, 0 copied` - no mirror blit to remove); the cost is
  CoreAnimation **redrawing the whole screen every frame**: the damage box is
  `0,0 1080x2340`, and 1746 of 1911 frames have no scissor at all. 136 draws
  over 2.53 Mpix a frame *is* the 45 ms. (c) submissions are 200-250 a second
  (~10 a frame) at 8-21 ms of queue latency; the multi-second figures in the log
  (2.95 s, 1.39 s) are **observation delay** - the stamp is taken when someone
  polls and finds the fence passed, not when the GPU finished - so only
  busy-window numbers are trustworthy.
  **"It degrades with use" is NOT a leak (measured 08:25, `4k-smp7-gpu14-live.txt`).**
  The heartbeat now prints `WIRED=<KB> big=<n> in <MB>` (lock-free atomics
  beside `sweet_surface_wired`; see §9 for why it cannot walk the table): over a
  minute of real use `SURF live` 19 -> 400 (`made=507 freed=107`) but **WIRED
  plateaus at ~128 MB and `big` stops at 16-18** surfaces, and presents stay
  80-200 per 5 s throughout with no downward trend. What *does* grow is the
  work per frame: 65 -> 83 draws (cumulative) as apps and layers accumulate, and
  an idle lock screen costs only 4 draws a frame (so CA's damage tracking does
  work; a scroll genuinely dirties the screen). The frame budget is therefore
  GPU fill during interaction, not memory. **Sizing it:** ~136 draws at roughly
  1/8 screen each is ~17 full-screen equivalents a frame; an Adreno 610 at
  950 MHz sustains ~1.5-2 Gpix/s of blended fill against a 2.53 Mpix screen, so
  60 fps allows ~10 full-screen equivalents. The port is **2-3x over budget, not
  10x** - one solid 2x win makes 30-45 fps, two make 60. Ranked, with what is
  measured vs assumed:
  1. **~~The ~10 whole-surface clears a frame~~ - MEASURED, SMALL (09:15).**
     `glclears=1` (wrapper) now prints `f N clears: <whole> whole, <boxed>
     boxed, <skipped> skipped, <Mpix> Mpix` per frame. On a real scroll:
     **4.6 whole + 2.5 boxed clears a frame, 4.3 Mpix in total** - about 1.7
     screenfuls, i.e. ~17 MB of writes or **~2 ms of a 40 ms frame**, not the
     12 ms the 10-clear count suggested. Dropping them cannot be the 2x. The
     opt-in skip is still implemented (`gnoclear=1`: a deferred clear is
     dropped when the following draw covers its box with blending off) - and it
     **does not help**: with it on, presents were 150-238 per 5 s (30-48 fps)
     against 205-267 without, i.e. no gain inside the noise, with visual-corruption
     risk. Leave it off. Measured 09:40.
  2. **Render smaller and let the MDP upscale - the scaler DOES work by plain MMIO, the
     reported mode was the bug (11:45).** Two earlier conclusions in this item were wrong and
     are corrected here. (i) The QSEED block is **QSEED4**, not QSEED3-lite: `HW_VERSION`
     (SSPP+0xa00) reads **0x3000** = `QSEED4_SCALER_VERSION`, read back on hardware. (ii) It
     does **not** need the register-DMA engine: `sde_hw_util.c` carries a plain-MMIO
     `sde_hw_setup_scaler3()` beside the reg-DMA one, and its LUT writer returns early when
     `lut_flag == 0` - and the driver's own default scale path sets `lut_flag = 0` with
     **bilinear** filters. So the scaler is: `OP_MODE 0x04` = `enable | BIL<<16 | !DX<<14 |
     alpha_en | alpha-BIL<<29`, `PHASE_STEP 0x10..0x1c` = `(src << 21) / dst`, `PRELOAD 0x20`
     = QSEED4's h4/v2, `SRC_SIZE 0x40/0x44`, `DST_SIZE 0x48`, `PHASE_INIT 0x90..0x9c` = 0, and
     - as the driver does - **`PE_OVERRIDE` stays set** (SSPP `0x38` bit 31) with the pixel
     extension programmed by hand: `0x100/0x110/0x120` = right 2 fetch+repeat, `0x104/0x114/0x124`
     = bottom 2, `0x108/0x118/0x128` = `(src_h+2)<<16 | (src_w+2)`.
     **What actually produced the three broken pictures:** not the scaler. `directPresent()`
     accepted *any* surface at least `fWidth x fHeight` and scanned the **centred crop**
     (`ox = (s->width - fWidth)/2`), while CoreAnimation was still allocating **1080x2340**
     surfaces because `kSweetFBGetDisplaySize` returned `fLogicalW/H`, which the small mode
     had deliberately kept at the panel's size. A `fbdump=1` line (`ystride` 4352 = 1088 px on
     a surface whose pipe SRC_SIZE said 720x1560) proved it: a full-size surface was being
     cropped to 720x1560 and, once the scaler worked, blown back up - hence "mosaic", "top
     half, three shadows" and "stretched diagonally". With the mode reported as the small size
     (`GetDisplaySize` -> 720x1560) CA really does allocate 720-wide surfaces (`ystride` 2880,
     verified) and the scaler is programmed with `step 0x155555` - **but the compositor then
     stops swapping: 12 swaps in a minute, panel black.** So the remaining problem is the
     *mode change*, not the scaler: userspace stops presenting once the size it asked for at
     boot differs from the panel timing it also reads (the mode block 0x40 IDs are constants,
     and nothing notifies it that its mode was accepted). That is the next thing to solve;
     do not re-derive the scaler.
     **WHY userspace stalls at a scaled mode - FOUND (12:30), and it is not our code.**
     `IOSurfaceAccelerator` (in IOSurface.framework, inside `dyld_shared_cache_arm64.25`) does
     `IOServiceMatching("AppleM2ScalerCSCDriver")` and, when nothing matches, prints
     `IOServiceMatchingfailed for: %s` and `Unable to get scaler capabilities` before falling
     back to a software path. That class really exists on this OS: the iPhone X 16.7.16
     kernelcache (`ipsw kernel kexts`) lists **`com.apple.driver.AppleM2ScalerCSCDriver`
     265.0.0**, a full ISPA scaler/CSC driver (`IosaInternalPipeMSR`, `M2ScalerCSCRequest`,
     `IosaColorManagerMSR8`, ...). So iOS implements a scaled display mode by **upscaling the
     frame with the hardware IOSurface accelerator**, and this port has no such service - which
     is exactly the black panel and the 12 swaps a minute: WindowServer asks for the scaler,
     gets nothing, and stops presenting. Our MDP QSEED4 scaler is the equivalent hardware but
     it is invisible to userspace, which wants an IOKit service with IOSurfaceAccelerator's
     user-client API. That is a multi-round driver project, not a register poke - do not retry
     the mode change until it exists.
     **The route that needs no Apple service (in progress, 12:35):** keep the mode at
     1080x2340 and scale *inside the compositor's own GL* - `glscale=N/D` in the wrapper
     (`eagl.c`, committed): the screen-sized surfaces are drawn into a texture N/D of their
     size (`attachImage` re-specifies its storage), every `glViewport`/`glScissor` is mapped
     into that smaller texture (`eagl_scale_rect`, emitted by `mkeagl.py` for slots 0xa80 and
     0x7e0), and the existing mirror blit in `target_to_surface()` copies it up bilinearly.
     Off by default; the same root serves both by adding `glscale=2/3` to the kernel cmdline.
     **Hardware result (12:55 and 13:25, two boots): the scale works, the filter effects do not.**
     With `glscale=2/3` (root `179f3dc3`, boot `smp7-gpu37`) content is correct and full screen and
     presents reach **1581 against the control's 749** in the same session - the port really does
     shade 720x1560 now. Two defects, both user-reported: the **app switcher and the lock-screen
     clock are drawn wrong**, and it **feels slower** despite the extra presents. The first theory -
     that the wrapper's own blur/group passes were scaled a second time - was wrong: those passes
     call Mesa directly, not the intercepted slots, so they were never scaled, and the
     `scale_suspend` guards added for it (root `ios16-root-glscale2.img`, `d93f163a...`) changed
     nothing. The likely real cause is that the *filters* compute their sample geometry from
     `image->width/height` (1080x2340) while the texture they read is now 720x1560, so every
     radius/offset in the blur and group paths is 1.5x out - which is exactly the two effects that
     look wrong. Fixing that means threading `texw/texh` through every filter, and the "feels
     slower" verdict has to be settled by measurement first (frame time 12-15 ms against the
     control's 9-10 ms, i.e. the 4.5 MB read + 10 MB write mirror blit may already eat the gain at
     2/3). **Measured properly (13:55) and CLOSED - it is not a win.** During a real scroll at
     `glscale=2/3`: **263-270 presents per 5 s against the unscaled 205-267**, frame cost 7.5-11 ms
     against 9-10 ms - no gain outside the noise - while the filters stayed broken and the user
     still felt 15-20 fps. The compositor was therefore never shading the frames that were missing:
     it already presents at vsync, and the felt rate is set elsewhere (item 2b). `smp7-gpu37` is
     deleted with this verdict; root `ios16-root-glscale2.img` stays as the phone's root because it
     behaves identically with `glscale` off. **Control fact worth keeping:** an idle SpringBoard simply stops drawing (`swaps` flat, no
     wrapper frames) - do not read that as a hang; ask for a swipe before calling a boot stalled.
     Failed builds deleted; `smp7-gpu29` is back on the phone (presenting, capture
     `4k-smp7-gpu29-restore4.txt`). Captures: `4k-smp7-gpu33-scaler.txt` (scaler programmed,
     black), `4k-smp7-gpu34-pe.txt` (PE extension, cropped picture), `4k-smp7-gpu35-geom.txt`
     (the `ystride 4352` proof), `4k-smp7-gpu36-mode720.txt` (real 720 mode, compositor stalls).
  2b. **The felt 15-20 fps is the presenter waiting for the GPU - ATTRIBUTED (14:05).** The
     presentation chain is neither the console nor a CPU copy: every UI frame takes
     `dp-surf 1080 1 -> dp-drawn -> dp-scan -> dp-done` (direct scanout of the GPU-pool surface,
     `copy-path` count 0), so the GUI is fully migrated off the console frame. What is slow is
     inside `present()`: a new per-hitch line (`SWEET FB: hitch <us>: queue .., MDP busy ..,
     previous present <us> (census <us>, GPU wait <us>) / latch <us>`) shows the presenter spending
     **5-15 ms in `topaz_surface_drawn()`**, waiting for the Adreno to finish the frame, against
     ~0-2 ms of its own work. When that wait exceeds a vsync the 2-deep presenter queue fills and
     `swap()` blocks the compositor (up to its 200 ms deadline) - that is the visible stutter.
     **Fixed on the way:** `present()` ran `sweet_surface_rgb_nz()` (a strided 10 MiB read) on
     GPU-pool surfaces and then discarded the result - now skipped, census 1091-1923 us -> 0.
     Build `smp7-gpu40` (`669cf4cf...`, kernel `0abf7719...`), capture `4k-smp7-gpu40-split.txt`.
     That leaves the port GPU-bound on the app's own draws, which is why halving the fill
     (`glscale`) did not help: the cost is the ~130 submissions a frame and the wait for them.
  3. **Present pacing - ANSWERED (09:25): NOT a 30 Hz lock, and the phone is
     already at ~50 fps.** `frameShown()` in `SweetFramebuffer.cpp` buckets the
     interval between displayed frames in 8.33 ms steps and prints the histogram
     every 256 frames (no per-frame console cost). During a real scroll:
     **buckets 8.3-16.7 ms 102, 16.7-25 ms 138, 25-33 ms 7, 33-41 1, 41-50 0,
     50-58 3, >58 4**, and `swaps` per 5 s reads **248, 205, 257, 255, 251, 256,
     267 = ~50 fps**. Presentation is vsync-paced, not locked at 30, and the
     frame budget is nearly met. The remaining defect is the **hitch tail**
     (25-112 ms frames, a few per 256), which is what "frames skip / arrive out
     of order" feels like. **The latch wait is not the cause**: a second probe
     times the poll for the MDP to latch each frame - `latch max 16.5-17.3 ms`,
     **73-79 of 256 frames over 8 ms, 0 expired** (the 25 ms budget is never
     hit), so the presenter waits at most one vsync and the MDP always latches.
     The frames that miss a vsync are GPU/CPU work, not presentation. Old: from
     the per-frame timestamps, present intervals are vsync-quantised
     (1/2/3 x 16.67 ms buckets) but not locked at 30 Hz, and their **median was
     17.0 ms** - which is an artefact, see the console-cost trap in §9. Treat
     as open. Frames arrive every 25-43 ms,
     which is suspiciously close to 2 vsyncs. A kernel-side histogram of
     inter-present intervals settles whether the compositor is throttled by the
     swap chain rather than by the GPU; if so, triple buffering doubles the rate
     for free.
  4. **GPU memory path**: with SMMU bypass the GPU's accesses are Normal
     non-cacheable (`MAIR0 = 0x44`); only enabling CB0 translation with
     write-back attributes could make them cached/combined. That is the parked
     §6 work, ~2x if it pans out, and coherency-risky.
  5. Cheaper blur/shadow paths in the wrapper (visual change).
- **Root cause of the whole crash loop: no AMFI, so nothing was signed.**
  Without `mpo_vnode_check_signature`, `ubc_cs_blob_add()` never set
  `CS_SIGNED`/`CS_PLATFORM_BINARY`, so every process looked unsigned,
  unentitled and non-platform. Four `ARM64_BOARD_CONFIG_SWEET` fixes:
  `ubc_subr.c` stamps `CS_SIGNED` (+`CS_PLATFORM_BINARY` on the rootfs) on a
  blob that validated; `kern_exec.c` forces
  `CS_SIGNED|CS_VALID|CS_PLATFORM_BINARY` into `imgp->ip_csflags` (exec's mask
  has no platform bit at all); `kern_cs.c`/`kern_proc.c` drop the `CS_SIGNED`
  gate on entitlements and fall back to `ubc_cs_blob_get()` and the signature's
  raw XML/DER blobs; `kern_resource.c` lets platform binaries set low-space io
  policy. Crash count per build on the same root: 1,145 -> 950 -> 845 -> 604 ->
  **4**.
- **Touch had two build-input bugs, not driver bugs.** (a) The CI tree held a
  105-byte stub `bsd/dev/sweet_touch_fw.h` (`len = 0`), so the FT8719 ROM got
  `downloading 0 bytes`; the real 264 KB header with `len = 64336` was next to
  the source but absent from the build. Recompiling `sweet_touch.o` fixed it.
  (b) `SweetHIDTouch::touch()` tested the edge band against the 2436 logical
  height (`y > 2399 - 48`) while the panel reports 2340, so a bottom swipe
  could never set `kIOHIDDigitizerEventFromEdgeTip` and UIKit never armed the
  home gesture. Now `2339 - 48`, and `SweetHID.cpp` must be recompiled into
  `SweetHID.cpo` (the prebuilt member is the old code).
- **Host-driven resets work; the button is no longer needed.** `sweet_usb.c`
  now parses `citrus:reboot:fastboot|recovery` on the already-armed bulk OUT
  endpoint and runs the PM6125 PON/IMEM reason then `PSCI SYSTEM_RESET`
  (`sweetusbcmd` gates it, default on). Verified on hardware, including a full
  build-flash-boot cycle with no physical interaction.
- **Silver 0 remains unavailable.** An 8-node ADT makes `PSCI CPU_ON(0x0)`
  return -4 (ALREADY_ON): secure world owns it. Seven cores (4 Gold + Silver
  1-3) is the true maximum; `SweetCPU.cpp:253` panics on the non-zero rc.
- **`sweettrustall=1` should now be droppable** (processes carry
  `CS_PLATFORM_BINARY` themselves); the no-trustall test predates the fix and
  has not been repeated. Do not try to suppress the launchd "boot task is not a
  platform binary" panic itself: `panic_kernel()` is `__abortlike`, so returning
  traps (BRK #1) and returning success from `reboot_kernel()` panics
  `initproc exited` — both proven on hardware.
Work is consolidated in this checkout under the isolated namespace
`out/citrus-8core/` (delete that directory to roll back its artifacts; the
added tools and research note are additive). No root image was modified.

- **Build inputs (do not re-derive):** CI run 40531392449 (`7e84cd1c`,
  macos-14/Xcode 15.4, `TOPAZ_4K=1`, no AMP) produced the 4K kernel
  `1492c683…` plus the 133 MB archive, `*.exp`/`*.alias.exp`/`*.linkarguments`
  that `/tmp/relink-smp7.py` reuses for a local relink
  (`tools/relink-citrus-4k-firmware.py` is the older one-shot variant; local ld
  27 emits no `__LINKINFO`/`__CTF` and merges `__LASTDATA_CONST` into `__LAST`,
  so always shim-test before booting). The recorder needs a writable `userdata`
  (`ufsrw=1`); with `sweetlog=0 ufsrw=0` neither the ring nor the heartbeat
  runs. One-Gold and rollback experiments from 2026-10-28 are in
  `research/CITRUS-4K-BOOT.md`.

## 2. NEXT DECISION

1. Composition is on the GPU and fast enough to use (§1A). Next, in order: the
   10 MiB IOSurface refill is still a CPU copy (13-183 ms per full-screen
   change), then the ~5 ms/frame cache maintenance on 4 KiB pages. Both are
   `research/CITRUS-4K-GPU.md` §2.
2. The pool's cold-latency defect is fixed by `gpupoolfirst=1`; what remains is
   the volume-slider 10 MiB *failure* with 12.9 MB free in 4 MB blocks — solve
   it in `gpu_pool_alloc` (refuse small splits below 8 MiB, or reserve the
   10 MiB class), not by raising `gpupoolmb`.

## 2A. 4K PLAN (updated 2026-10-29 04:05)

1. **The phone is healthy on `smp7-clk` `de95df37...`** (§1); no restore
   needed. Use `python3 usb-restart/reboot.py fastboot` then `fastboot flash
   boot ...` for the next experiment.
2. **Then, in order:** (a) make the 10 MiB IOSurface refill a GPU blit instead
   of a CPU copy, and cut the per-submission cache-maintenance cost
   (`research/CITRUS-4K-GPU.md` §2); (b) boot once without `sweettrustall=1`;
   (c) fold touch probe mode 10 into `sweet_touch_init()`; (d) backlight PWM.
3. **Iterate with the host channel, not the button:**
   `python3 usb-restart/reboot.py fastboot` while the USB console is up, then
   `fastboot flash boot ... && fastboot reboot`. Boot to userspace is 40-90 s;
   the touch probe starts 5 s in and needs ~40 s for the 64 KiB firmware.
4. **Silver 0 is not available to the HLOS — proven, not assumed.** Seven
   nodes, `cpus=7`. Do not publish an 8-node ADT.
5. **Do not rebuild what is already fixed:** the identity/entitlement/platform
   stamps, the low-space io policy, the 2340-pixel edge test, the real
   `sweet_touch_fw.h`, the immediate DWC3 bring-up. Each was proven on
   hardware and is described in `research/CITRUS-4K-BOOT.md`.

## 3. MEASURED BASIS (16 KiB B0, 2026-10-27)

3,980 frames: median 10.96 ms/frame, p95 30.34 (29% over 16.7). Texture refills
are per asset, not per frame — deduping them was not justified. All 13 large
allocations came from the pool after 18.9-108.7 ms (median 47.6) of failed
low-memory search, 36 sub-attempts; `gpupoolfirst=1` now removes that search
(§1A). `glFlush` 5.3-7.5 ms/frame, cache maintenance 657 us/submission.

## 4. NAMED IMAGES / QUARANTINE

16 KiB fallbacks in `out/citrus-diagnostic/`: `gpu-poolarena1` `c0056a8f...`
(current 16 KiB boot), `pool2` `aeec7fc4...` (byte-identical), `perf3`
`af7dd145...`, `keys-test` `68e079af...`, `ca6` `b699cac2...`, `pll0-950`
`4e3e54fe...`, `cpu1` `0f709d85...`, `mhz600` `15e99eea...`, `touch-cpu4`
`74598845...`, `touchprobe23` `4bf2cd3b...`, `smp4` `e464cb60...`; manifest
next to each build dir.

**Quarantined — do not flash without a new diagnosis:** `gpu-perf2`, `gpu-perf4`,
`gpu-perf4b`, `gpu-allocprobe`, `gpu-latpool`, `gpu-pool128`, `gpu-smmu1`,
`gpu-smmu39`, `gpu-smmudiag`, `gpu-clockprobe1`, `gpu-direct1`, `gpu-probe1`,
`gpu-backlight1`, `smp5-cpu4`, `citrus-xnu-boot-unmask.img`.

## 5. ROOTS

- **Root on the phone:** `out/ios16/ios16-root-glscale2.img` (`d93f163a...`) - the compositor
  root with the `glscale` wrapper plus the (harmless) filter-pass guards; identical in behaviour
  to `ios16-root-onesubmit.img` while `glscale` is off. `ios16-root-glscale.img` was deleted as
  superseded; rebuild either from the compositor root with the recipe below.
- **Known-good root:** `out/ios16/ios16-root-onesubmit.img`, SHA256
  `352688c583725d7b2090ee7a2b1e8ef68f925c3a96eca5dae4b4afc0431641e6` — the
  compositor root plus the one-submission `libcitrus-gl.dylib`. Rebuild it from
  the compositor root (next bullet) with `tools/build-citrus-eagl.py` +
  `tools/package-citrus-gpu-userland.py` +
  `tools/install-citrus-compositor.py --image <copy> --source-sha256
  0ee5bd34… --apply`, then `tools/flash-citrus-gpu-userdata.sh`.
- Known-good base: `out/ios16/ios16-root-keychain.img` (16 GiB HFSX),
  SHA256 `0ee5bd34809984e05d88104f4bd5a1e6a78166b6b61c1b1f338ba478f3bb1732`.
- Fallback root with compositor, **never modify**:
  `out/ios16/ios16-root-gpu-compositor.img`, install hash
  `e796c1f202ff02f546700395fac3de8b329ece882acecaf23db49adde9eb76fa`.
  It still has the two-submission wrapper, so pair it with a kernel whose
  cmdline has no `glonesubmit=0` only if you want the old behaviour.
- Rebuild the offline root with `tools/build-ios-root-macos.py` (IPSW
  provenance in `out/ios16/download.json`); a triangle root is a copy of the
  keychain image plus `tools/install-citrus-gpu-userland.py --image <copy>
  --test-runner iomfb` (always pass `--image`).
- Repairs already done — do not redo: catalog extents reconstruction, one-node
  extents-overflow fix for fileID 8, keychain ownership `/private/var/Keychains`
  → 64:64, Wi-Fi identity in `/chosen/mac-address-wifi0`.
- Flashing root: fastboot rejects ≥2 GiB. Use recovery + ADB:
  `tools/stream-image-adb.sh IMAGE /dev/block/by-name/userdata` (16 × 1 GiB
  segments), then verify the on-device SHA. Cancel ADB Sideload in OrangeFox if
  `adb shell` is closed. Never run `tools/hfs-owners.c` on a real root; use
  `tools/hfs-chown-inplace.py`.

## 6. SMMU STATUS (parked, not abandoned)

IDR1 `0x20000005`: 4 KiB pages, NUMPAGENDXB 2, five context banks; IDR2
`0x5511` = 36-bit IAS/OAS. Vendor rule `cb_base = base + size/2` gives
CB0=0x8000, GR1=0x1000, confirmed on hardware; `citrus_smmu_layout()` now
validates it (`tools/test-citrus-smmu-layout.py`). CB0 writes land exactly
(SCTLR `0x67`, TTBR0 `0x8efe4000`, TCR `0x00800020`); SCTLR bit 12 and sCR0
bits 4/5 are not writable; only CB0 is trustworthy. **2026-10-29 10:05 - translation is blocked by a fault at enable time, and the
stage-1 tables are NOT the reason.** A software walk of the CP's firmware
address proves the chain is right and the PTEs are in RAM:

```
WALK sqe va=0xf0000000 ttbr0=0x93a64000 l1[3]=0x93a65003 l2[384]=0x93a66003
     l3[0]@0x93a66000=0x8f0cc643   (PA 0x8f0cc000, flags 0x643)  next=0xf0017000
```

(`sqe` 32 KB at 0xf0000000, `ring` at 0xf0009000, `mem` at 0xf0012000; the ring
l3 entry 0x8f0d4643. `table_chunk_used` is fine - `PAGE_SIZE` here is 16 KB, so
4 slots per chunk, and the initialiser of 4 was already correct.)

What actually happens: **CB0 FSR already reads non-zero at the instant SCTLR.M
is set**, before the CP is ever kicked (`SMMU enabled after mapping: SCTLR
00000067 FSR 00000400`). The bootloader leaves the GPU/CP live, so the first
translated access comes from a client that is already running, not from our
submission. Sequence of attempts, each with its own boot:

1. Enable at the end of `smmu_setup()` -> CP faults at `0xf0000000`, ring stuck.
2. Enable only after the CP buffers are mapped (`smmu_enable_now()` style) ->
   **FSR non-zero at enable**, so the fault is not an unmapped-IB ordering bug.
3. `SMR0` widened from mask 1 (SID 0/1 only) to `0x7F` (all 7-bit SIDs) plus an
   attempt to clear `sCR0.USFCFG` -> the fault signature changes (`FAR` becomes
   a 48-bit value), i.e. **stream matching was definitely wrong before**. Note
   `sCR0` bit 10 does not read back cleared.
4. Clean *every* descriptor page (all l2/l3 tables, not just the 8-byte
   entries) before enabling -> unchanged, so it is not descriptor coherency.

**Two traps found, do not trust the old fault report:**
- `smmu_atos()` is useless as written: it polls `CB+0x8F0` for bit 0 with an
  expected value of 0 and prints `PASS` with `par=0` on every address, mapped or
  not. Either fix the register offsets (ATS1PR result is in `CB_PAR`, 0x50) or
  delete it.
- Our `CB_FSR`/`CB_FAR` reads (0x58 / 0x50) can return values that cannot be
  GPU VAs at all (`FAR 0x601310167482`, repeatable but nonsense, 48-bit), so
  the printed FSR/FAR may be from the wrong offsets. Treat "the CP never leaves
  the ring" as the trustworthy symptom and the register dump as suspect.

Reverted to the identity build (`smp7-gpu20` back on the phone, `Adreno 610
ready`, `CP up core 950`); `smp7-gpu26`/`smp7-gpu27` deleted, captures
`4k-smp7-gpu24-walk.txt`, `4k-smp7-gpu26-smr.txt`, `4k-smp7-gpu27-clean.txt`.
The tree now carries those gated edits (SMR0 mask `0x7F` unconditionally, and
enable-after-map plus a full descriptor clean under `!gpu_identity`); **the
resting image predates them**, so a future `gpu_identity=0` build starts from
the state described here, while identity boots are unaffected (SCTLR.M stays 0,
which bypasses translation regardless of stream matching).

**CORRECTION (10:30):** the "fault at enable time" above is an artefact - the
same `FSR 0x400 / FAR 0x6013_10167482` pair reads back on an **identity** boot
with translation disabled (gpu29), where no fault is possible. The register
offsets (FSR 0x58, FAR 0x60/0x64, FSYNR0 0x68) match Linux's arm-smmu, so the
MMU-500 in this SoC simply does not expose usable fault status there; nothing
about the CP's failure can be learned from it.

**VERDICT (10:25): evaluated, parked.** Every avenue that does not require new
machinery is exhausted - the tables, the TLB, the descriptor coherency, the
enable point and the stream mask are all verified or ruled out, and the fault
report itself is untrustworthy on this part. What remains needs either 2 MiB
*block* descriptors (to identity-map the RAM window the ZAP/CP microcode is
already executing from, which is the leading hypothesis: `zap_load()` runs
before `smmu_setup()`, so under bypass the GPU is executing microcode at
IOVA = PA, and translation turns that into an immediate walk fault) or a real
GPU reset path we do not have. That is a multi-round project, not the fast path
to 60 fps, so the lever is parked with the evidence above.

**Next for this lever (if resumed):** find CB0's real FSR/FAR/Fsynr1 offsets from the
MMU-500 spec (Fsynr1 carries the SID of the faulting stream, which names the
client), kill/stop the pre-existing GPU client before enabling translation (a
GPU soft reset, not just a CP halt), and only then map and start. Do not rebuild
the descriptor path - it is verified correct.

## 7. BUILD / FLASH / TEST

```sh
# Kernel + boot image (23.7 MB). The ADT node count must match cpus=.
python3 tools/rebuild-kernel.py
python3 upstream/ios-topaz/tools/mkpayload.py \
    out/citrus-kernel/kernel.development.citrus \
    out/citrus-kernel/citrus-ufsroot-disp-ram1792-cpu4.adt \
    out/citrus-kernel/payload-<name>.bin --cmdline "<args, cpus=4>"
python3 tools/build-diagnostic.py \
    --template device-dumps/20261025-141423-923416/backups/boot.img \
    --payload out/citrus-kernel/payload-<name>.bin
mv out/citrus-diagnostic/citrus-xnu-boot.img \
   out/citrus-diagnostic/citrus-xnu-boot-<name>.img

# Clock goal gate: one row per designed-rate claim, 0 = all satisfied.
# Pass several captures; CPU/GPU evidence and the sweep/DDR probe come from
# different boots. MISSING means the image predates that check, FAIL is real.
python3 tools/verify-clocks.py out/ios16/logs/*.txt

# Flash (user resets with Power+Volume Down; nothing is automatic)
fastboot flash boot out/citrus-diagnostic/citrus-xnu-boot-<name>.img
fastboot reboot
python3 tools/usb-log.py -o out/ios16/logs/<name>-live.txt
fastboot reboot recovery && tools/pull-sweetlog.sh <name>   # recorder pull

# GPU candidate (matches pool2)
python3 tools/build-citrus-gpu.py --output-dir out/citrus-gpu-<name> \
    --firmware-dir devices/citrus-gpu-fw
python3 tools/package-citrus-gpu.py --build-dir out/citrus-gpu-<name> \
    --name <name> --execute --gl 1 --gpu-mhz 950 --cpu-max --keys \
    --extra-arg gpupoolmb=128

# Userland (only with an explicit root decision)
python3 tools/build-citrus-eagl.py
python3 tools/package-citrus-gpu-userland.py
cp out/ios16/ios16-root-gpu-compositor.img out/ios16/ios16-root-<name>.img
python3 tools/install-citrus-compositor.py --image out/ios16/ios16-root-<name>.img \
    --source-sha256 e796c1f202ff02f546700395fac3de8b329ece882acecaf23db49adde9eb76fa --apply
tools/flash-citrus-gpu-userdata.sh <image> <device> <sha256>
```

Patches: `0002-sweet-console-display-stall-instrumentation.patch` (208094 B) is
a `diff -u` against `/tmp/origbt/xnu` (from
`out/upstream-artifacts/xnu-buildtree.zip`). `0003-citrus-adreno-kernel.patch`
(197001 B, sha `8fcd6a1a326b433097efd32aa94f6328e7702de9d9e1868f6955695f1370e49d`, nine files) is reproduced exactly by
`python3 tools/make-citrus-gpu-patch.py`. Regenerate and dry-run verify after
every kernel edit.

## 8. BOOT ARGS

```
debug=0xc serial=3 cpus=4 keepsyms=1 -noprogress rd=ufsroot0
ufsrw=1 rootrw=1 wdt=-1 wdt_test=no_user_checkin
unentitled_ios_sim_launch=1 launchd_unsecure_cache=1
sweetkeys=0 sweetbattery=0 sweetcpufreq=0 sweetchg=0 sweethw=0 sweettouch=0
sweetscan=mobileactivation
sweetnull=-                       # or backboardd,SpringBoard,mobileactivation
sweetfb_stayon=1 sweetfb_native=1
sweetwdt=0                        # nonzero panics by design
sweetpanel=1                      # 2 = draw from ISR (unreliable)
sweetirqwr=0                      # never use slot 0 from an interrupt
sweetusb=2                        # 0 off, 1 probe, 2 full console
sweetptimer=0                     # physical PPI18 never verified
sweetusbspin=0                    # keep the busy probe off
sweetlog=1                        # console ring + heartbeat thread
sweetvrecord=0                    # selects fallback stall probe; DOES NOT disable slot-1 writes
sweetsample=-                     # disable process sampler
sweetufstrace=0                   # 0 means trace from t=0, not "off"!
```

`sweetufstrace=0` starts the trace immediately; omit the argument to disable.
No idle flag is a reliable fix.

## 9. STANDING TRAPS

- Never call `PE_parse_boot_argn` in interrupt context; resolve in thread
  context (`sweet_irq_writes_resolve()` / init paths).
- **`sweet_stall_service()` runs in the timer interrupt, so nothing on that path
  may take a lock.** `IOLockLock` there panics
  `Attempt to take mutex ... with preemption disabled (Glock_mtx.c:194)` before
  userspace starts. The liveness line may only read atomics (that is why
  `redwood_gpu_state()`/`sweet_surface_counts()` are lock-free); a diagnostic
  that needs to walk a table must keep running counters instead.
- `ml_io_map` has an **8 MiB budget for the whole kernel**
  (`IO_MAP_SIZE`, `osfmk/arm/io_map.c`, `KMA_NOFAIL`, permanent maps). A full
  map panics in `kmem_alloc` with `KERN_NO_SPACE` — this killed `clockprobe1`.
  Map small windows, reuse mappings, or use an `IOMemoryDescriptor`.
- **The time base is 19.2 MHz, not 24 MHz.** `mach_absolute_time()`, `cntvct_el0` and
  `cntpct_el0` tick at the board's XO; every frequency derived with a 24 MHz
  constant is 1.25x high (this is how the CPU clock table was misread on
  2026-10-29, see `research/CITRUS-CLOCK-SPEED.md` §2).
- `sweetwdt=<s>` panics by design; keep `sweetwdt=0`.
- Interrupt-side UFS slot 0 writes are unsafe (`sweetirqwr=1` re-enables the old
  path on purpose). The UFS driver is single-slot and polled.
- A dead USB console is not proof of a dead kernel. Reopen the tty, ask what the
  screen shows; the `sweetlog` recorder is authoritative.
- `tools/usb-log.py` can latch a stale `/dev/cu.usbmodem*` node and record
  **0 bytes** while the gadget re-enumerates (seen 22:10, 22:32, 22:57). Check
  `ls -l` the capture after ~60 s; if empty, kill the reader, confirm the node
  mtime changed, then restart it.
- New MMIO bases must be checked against
  `device-dumps/20261025-141423-923416/live-tree.json` (bengal/SM6115). Old
  Topaz addresses (GCC 0x00100000, QUSB2 0x088e2000) are wrong.
- Panel is 1080x2340; iOS logical 1125x2436 targets can be empty.
  `sweetfb_native=1` is the working mode; `sweetpanel=2` has never drawn.
- **Never index surface pixels by `width*height`.** `allocSize` is the length
  (the 312x202 LA08 surface is 2 bpp). Use `sweet_surface_word_limit()`; a stray
  scan faults inside `present()`, which also swallows the panic output.
- **Code-signing flags come from our own stamps, not from AMFI.** There is no
  MAC policy here, so `ubc_subr.c` (blob) and `kern_exec.c` (process) set
  `CS_SIGNED`/`CS_PLATFORM_BINARY` themselves. If a future tree loses those
  edits, the symptoms come back in a fixed order: identity mismatch on boot
  tasks, then the `+[SpringBoardUI load]` assertion, then
  `(platformBinary)` in `SBStaticInitializer`.
- **Generated sources may be stubs in the build tree.** `sweet_touch_fw.h` was
  105 bytes there and 264 KB next to the source, silently producing a
  zero-length firmware download. After touching generated data, grep the build
  tree's copy, not just the source tree's.
- **`SweetHID.cpo` must be recompiled when `SweetHID.cpp` changes.** The
  archive member is prebuilt; the edge test that enables the home gesture only
  changed once it was rebuilt locally.
- ADT nodes and `cpus=` must agree; `cpus=N` alone does nothing (`selected`
  comes from the ADT). Seven homogeneous-SMP cores (4 Gold + Silver 1-3) now
  initialize on 4K. Silver 0/MPIDR 0x0 answers `PSCI CPU_ON` with -4
  (ALREADY_ON, secure world); publishing it in the ADT panics in
  `SweetCPU.cpp:253`. Keep 7 nodes. Do not reintroduce the old "four Gold
  maximum" assumption.
- Keep the physical timer off and one reader only.
- **A console line costs ~17 ms at 115200 baud, so per-frame logging throttles
  the frame rate it is measuring.** `glframes=1`/`glclears=1` print one or two
  ~200-byte lines a frame; the median inter-frame interval then lands exactly on
  17 ms and the numbers are the console's, not the GPU's. Never quote frame
  timing from a `glframes`/`glclears` boot; measure with `SURF ... swaps` per
  5 s (or `touch_lat=1`, which is designed for it).
- **The phone mounts its root read-write, so the on-device volume drifts away
  from any host image.** On 2026-10-29 the journal region of userdata was `0x5a`
  filled and did not match `ios16-root-onesubmit.img`; a block-level diff patch
  would have corrupted the volume. Reflash the whole 16 GiB image
  (`tools/stream-image-adb.sh`, ~37 s per GiB through recovery) instead of
  patching deltas.
- **`INTF1` frames on the heartbeat are the display timer, not presents.** A
  boot can print `~320 frames in 5 s` while the UI draws 3 fps; trust the
  wrapper's `redwood-gl: frame N` lines and `SURF ... swaps` instead.
- **Do not mount a 16 GiB root read-write and then hash it on this Mac.** On
  2026-10-27 that combination (rw attach + whole-image digest, 16 GiB RAM, ~25k
  free pages) made every app hang. Mount **read-only** (`hdiutil attach
  -readonly -noverify -nobrowse -owners off -mountpoint /tmp/mntroot`) only to
  check one file, and hash with `F_NOCACHE` (`/tmp/sha-nocache.py`, prints
  "<sha> <bytes>") rather than `shasum` so the page cache is not filled. Pass
  the result as `CITRUS_IMAGE_SHA=… tools/flash-citrus-gpu-userdata.sh …` to
  skip the script's own 16 GiB re-hash; the on-device readback still verifies.
- **`build-citrus-gpu.py` applies `kernel/patches/0003` to a fresh copy of
  `out/upstream-artifacts/buildtree/xnu`; edits under `out/citrus-gpu/xnu` are
  ignored unless `tools/make-citrus-gpu-patch.py` is run first.** Regenerate the
  patch, then build, and verify the new string/symbol is in the linked kernel
  (`strings ... | grep`) before packaging. A build made before regeneration
  silently runs the old code (this happened once on 2026-10-27: the first
  submitprobe image had no phase line).

## 10. PROVEN INFRASTRUCTURE

- **USB console:** DWC3 `ssusb@4e00000`, core regs `0x04e00000` (size 0xcd00),
  QSCRATCH at core+`0xf8800`; CDC-ACM gives `/dev/cu.usbmodem*`.
- **GCC** `0x01400000` size `0x1f0000` (bengal).
- **UFS:** single UTRL slot/UCD/bounce, polled; GPT `userdata` = `ufsroot0`,
  drive with `rd=ufsroot0`.
- **Display:** AppleCLCD/MDP direct scanout, 1080x2340 stride 4320 at
  `0x5c000000`.
- **Recorder:** console ring + heartbeat + 16 stall slots + panic block at the
  end of userdata; `tools/pull-sweetlog.sh NAME` decodes (panic at `-18`,
  observer at `-17`).
- **Touch (FT8719) works end to end:** crossed data pair (IC MISO GPIO6, MOSI
  GPIO7), ROM firmware downloaded every boot, `0xAE`/`0xCC` carry addr/len in
  the command package, reports read data-phase-only (`0x3F` + 63 bytes).
- **GPU:** Adreno 610 via Mesa freedreno/RedwoodGPU, 950 MHz, identity SMMU,
  FD610; compositor uses the mirror-blit path (direct draw rejected).

## 11. EVIDENCE

- `out/ios16/logs/` — live captures, `*-heartbeat.txt`, `*-stalls.txt`,
  `*-sweetlog.txt`, `*-manifest.json`, `*-reader.json`.
- Boots cited above: `gpu-pool2-b0-live.txt`, `gpu-pool2-restore-live.txt`,
  `gpu-smmudiag-live.txt`, `gpu-performance{1,2,3}-live.txt`,
  `gpu-perf3-reuse-rollback-live.txt`, `gpu-clockprobe1-live.txt`,
  `gpu-triangle4-live.txt`, `touchprobe23-live.txt`, `touch-cpu4-live.txt`,
  `smp2..smp4`, `pll0-950-live.txt`, `gpu-keys-test-live.txt`.
- Per-image evidence lives next to the manifest:
  `out/citrus-gpu-<name>/<name>-manifest.json`.
- `tools/verify-clocks.py <capture>...` is the clock goal's pass/fail gate: one
  row per claim (7/7 CPUs, Silver 7/1804, Gold 8/2016, both normal steps, GPU
  950 + CP 950 + selftest, DDR >= 8 GB/s, the three UFS RCG decodes). As of
  2026-10-29 05:25, over `4k-smp7-clk-live.txt` + `4k-smp7-ufsdefdiag-live.txt`,
  the gate is **12 pass / 0 fail / 0 missing**.

## 12. NEXT WORK, IN ORDER

1. 4K GPU composition works now (§1A); next is the 10 MiB surface refill (CPU
   copy) and the ~5 ms/frame cache maintenance on 4 KiB pages.
2. Clocks: done and measured for every clock the port owns (§1A) — CPU, GPU,
   DDR, UFS. SNOC/CNOC/BIMC are RPM-owned and cannot be programmed from the
   AP; only the GPU bus/rail vote and a sustained/thermal policy remain parked
   with GLINK-RPM (`research/CITRUS-CLOCK-SPEED.md` §6).
3. Re-test 4K boot without `sweettrustall=1`.
4. Fold touch probe mode 10 into `sweet_touch_init()` (`sweettouch=1`).
5. Backlight: `bl_ctrl_pwm` on `pm6125_pwm` is never programmed; inherited
   bootloader duty makes the bottom edge hot.
6. Pool: the volume-slider 10 MiB failure (§2).
7. Touch polish: debounce the phantom "(absent)" ups, drop per-frame printf.
8. Longer term: activation/sandbox, Wi-Fi, RPM/LDO power.

## 13. MAINTENANCE LOG

- **2026-10-29 14:10 - lever 2 closed with numbers; the felt frame rate is the GPU wait in
  `present()`, and the console/scanout hypothesis is ruled out.** A real scroll at `glscale=2/3`
  gave **263-270 presents/5 s against 205-267 unscaled** - no gain - so the GL scale is closed as a
  lever (it also kept the filter defects) and `smp7-gpu37` was deleted. Two diagnostics landed
  instead: per-hitch attribution in `frameShown()` (latency, queue depth, MDP busy, the previous
  present split into census and GPU wait, latch time) and the removal of a strided 10 MiB pixel
  census that ran on every present and whose result was discarded for GPU-pool surfaces. Readings:
  frames reach the panel by **direct scanout of the GPU surface** (`dp-scan`, zero `copy-path`
  frames), and each hitch is `GPU wait 5-15 ms` in `topaz_surface_drawn()` - the Adreno is still
  drawing - against ~0-2 ms of our own work in `present()`. Because the queue is 2 deep, that wait
  becomes a blocked `swap()` in backboardd, which is what the user feels. Image `smp7-gpu40`
  (`669cf4cf...`, kernel `0abf7719...`), capture `4k-smp7-gpu40-split.txt`; `smp7-gpu39` deleted.
  Remaining route to 60 fps: fewer submissions/draws per frame or a shorter GPU tail - not more
  present-path work.

- **2026-10-29 13:35 - `glscale` lever parked: the scale is right, the filters are not.** Second boot
  with the guarded wrapper (root `d93f163a`, `glscale=2/3`) still broke the app switcher and the
  lock-screen clock, so the guard was aimed at the wrong thing: the wrapper's `vblur_level()` /
  `group_flatten()` call Mesa directly, not the intercepted `glViewport` slot, so they were never
  double-scaled. The remaining explanation is that the filter geometry (`image->width/height`) is
  still the full 1080x2340 while the texture is 720x1560, i.e. every blur radius and group offset is
  1.5x out. Threading `texw/texh` through the filter paths plus a measurement of the mirror blit's
  cost is a multi-round piece of work with an uncertain payoff (the user already found 2/3 *slower*
  than unscaled), so the lever is parked with its artifacts kept: boot `smp7-gpu37`
  (`a3cb0a91...`) and root `ios16-root-glscale2.img`. `smp7-gpu38` (the control boot) and
  `ios16-root-glscale.img` were deleted. Phone restored to `smp7-gpu29` + the glscale2 root with
  scaling off: `7/7 CPUs`, `Adreno 610 ready`, presenting, capture `4k-smp7-gpu29-restore5.txt`.

- **2026-10-29 13:05 - lever 2 first hardware result: `glscale=2/3` renders and presents, and the
  group/blur passes had to be exempt.** With `glscale=2/3` the wrapper draws the screen's surfaces into
  720x1560 textures and blits them up: content correct and full screen, **1581 presents against 749**
  for the same session with scaling off. Broken: the app switcher and the lock-screen clock, because
  `vblur_level()` and `group_flatten()` set their own viewports and the new `glscale` hook scaled them
  again - fixed with a `scale_suspend` counter that `eagl_scale_rect()` honours (root
  `ios16-root-glscale2.img`, `d93f163a...`). The user also reported it *feels* slower, so the next step
  is a measurement (frame time 12-15 ms against 9-10 ms unscaled, i.e. the 4.5 MB read + 10 MB write
  blit may be eating the gain at 2/3; 3/4 and 1/2 are a cmdline away). Also learned: an idle
  SpringBoard stops drawing entirely, so a flat `swaps` on an untouched phone is not a hang - always
  ask for a swipe before calling a boot stalled. New root installed, boot `smp7-gpu37` unchanged.

- **2026-10-29 12:40 - lever 2: the scaled-mode blocker has a name (AppleM2ScalerCSCDriver), and the
  wrapper now scales in GL instead.** The stall at 720x1560 is `IOSurfaceAccelerator`: it
  `IOServiceMatching`s `AppleM2ScalerCSCDriver` (a real kext, `com.apple.driver.AppleM2ScalerCSCDriver`
  265.0.0, in the iPhone X 16.7.16 kernelcache - `ipsw kernel kexts`), logs
  `IOServiceMatchingfailed for: %s`, `Unable to get scaler capabilities`, and then WindowServer stops
  presenting. iOS upscales a scaled mode on that hardware accelerator; the port has no such service.
  Meanwhile the same 2.2x is available without userspace cooperation: `glscale=N/D` makes the wrapper
  draw the screen-sized surfaces into a texture N/D of their size and blit it up - `attachImage()`
  re-specifies the texture's storage, `eagl_scale_rect()` (emitted by `mkeagl.py` into slots `0xa80`
  glViewport and `0x7e0` glScissor) maps the boxes, `target_to_surface()` blits bilinearly. New root
  `ios16-root-glscale.img` (`179f3dc3...`), new boot image `smp7-gpu37` (`a3cb0a91...`, kernel
  `8e137ae6...`, + `glscale=2/3`). Also downloaded the iPhone X 16.7.16 IPSW (5.7 GiB, `/tmp`) for
  the kernelcache; `/tmp` was pruned from 21 GB to 4.6 GB on the way (probe images, old build trees,
  the extracted dyld cache).

- **2026-10-29 11:45 - lever 2: the MDP scaler was never the problem; the reported mode was.**
  The QSEED block reads `HW_VERSION 0x3000` on hardware, i.e. **QSEED4**, and `sde_hw_util.c`
  has a **plain-MMIO** `sde_hw_setup_scaler3()` that needs no register-DMA and no LUT (the
  driver's own default path uses `lut_flag = 0`, bilinear). Implemented in
  `SweetFramebuffer.cpp::programScaler()`: op mode `0xa0034401`, phase step
  `(src<<21)/dst` = `0x155555` for 720x1560 -> 1080x2340, preload h4/v2, sizes, init phase 0,
  plus the driver's pixel-extension registers (`0x100..0x128`) with `PE_OVERRIDE` left set.
  The three broken pictures came from somewhere else: `directPresent()` scans the **centred
  720x1560 crop** of whatever surface it is handed, and CoreAnimation was still allocating
  **1080x2340** surfaces because `GetDisplaySize` returned the *panel* size. A `fbdump`
  readback (`ystride 4352` = 1088 px against a 720x1560 SRC_SIZE) proved the crop. Reporting
  the mode as the small size works (`ystride 2880`, step `0x155555`, scaler registers read
  back exactly as written) but then the compositor stops presenting - **12 swaps a minute,
  black panel** - so the open problem is the mode change, not the scaler. Four boots
  (`gpu33`..`gpu36`), all deleted; `smp7-gpu29` restored and presenting
  (`4k-smp7-gpu29-restore4.txt`). Captures `4k-smp7-gpu33-scaler.txt`,
  `4k-smp7-gpu34-pe.txt`, `4k-smp7-gpu35-geom.txt`, `4k-smp7-gpu36-mode720.txt`.

- **2026-10-29 11:05 - lever 2 started: small-mode plumbing lands, MDP scaling does not work yet.** `fbw=`/`fbh=` shrink the framebuffer (and every compositor surface) while the logical size stays 1080x2340 points; `scanFrom()` writes `SSPP_SRC_SIZE`/`SSPP_OUT_SIZE`. A 720x1560 build boots fully (`rendering 720x1560`, `Adreno 610 ready`, presenting) but the panel shows a mosaic - top half only, three shadow copies - so the pipe fetches with no working scaler. `fbdump=1` read the pipe's registers back: SRC_SIZE/OUT_SIZE at 0x00/0x0c, SRC0_ADDR 0x14, YSTRIDE0 0x24, SRC_OP_MODE 0x38 = **PE_OVERRIDE set**, QSEED3-lite at SSPP+0xa00. Clearing PE_OVERRIDE does not help (same mosaic), which points at the QSEED3LITE path being reg-DMA + LUT (`reg_dmav1_setup_vig_qseed3` in msm's `sde_hw_sspp.c`) - a multi-round bring-up, not a register poke. Recommended next: keep the small mode and do the upscale as one **GPU blit** into a 1080x2340 scanout surface, reusing the wrapper's existing copy path, since the GPU is what is fill-bound. Two boots (`gpu31`, `gpu32`), both deleted; `smp7-gpu29` restored and presenting. Captures `4k-smp7-gpu30-vigdump.txt`, `4k-smp7-gpu31-fb720.txt`, `4k-smp7-gpu32-fb720pe.txt`.

- **2026-10-29 10:30 - cache maintenance halved; ~50 fps confirmed on a real scroll; SMMU stream-match trap.** `GPU_PUSH_AGAIN_MS` (4 ms) meant the compositor re-cleaned every surface on nearly every submission: **1876 us a submission for 4381 KB**, ten times a frame. `gpuagain=16` (one frame) cuts it to **915 us** on the same set with no visual corruption over a real scroll, and the user reports it feels smoother. Measured during that scroll: presents **199/453/703/956/1145 per 5 s = 50-51 fps**, frame buckets `0 79 152 15 5 2 1 2`, latch `max 16.8-27 ms, 0 expired`. So the port is a solid ~50 fps and the residual is GPU fill plus a hitch tail, not CPU. Default is 16 ms in code now. **Trap found:** applying the wildcard `SMR0` mask on *every* boot (a round-4 experiment) stops the CP on identity boots (`ring stuck rptr 0 wptr 9`, `CP_HW_FAULT 00`, no `Adreno 610 ready`); it is now gated to `!gpu_identity`. Also: `CB0 FSR` reads `0x400` with `FAR 0x601310167482` **even in bypass mode**, which proves that register pair cannot be trusted at all - round 4's "fault at enable time" was this artefact, not a real fault. Image `smp7-gpu29` (`f82290e748d0...`, kernel `aac49e76...`); `smp7-gpu28` deleted.

- **2026-10-29 10:25 - lever 4 parked with a verdict; the remaining 60 fps gap is the hitch tail.** The stage-1 tables are verified correct by a software walk, so the blocker is the fault raised the instant `SCTLR.M` is set, from a client the GPU left running (`zap_load()` executes microcode under bypass *before* `smmu_setup()`), and `CB_FAR` returns impossible values so the faulting SID cannot be named with the registers we can trust. Fixing it needs either level-2 block descriptors to identity-map the RAM the microcode runs from, or a GPU reset path - both multi-round work, so the lever is parked. Also noted: `sweet_atos()` is broken (always `PASS`), and `SweetFramebuffer.cpp` has **no scaler support at all** (no QSEED/SCALER register writes anywhere), so lever 2 means a from-scratch QSEED3 bring-up on the display pipe, not a configuration change.

- **2026-10-29 10:05 - SMMU lever 4: tables verified correct; the fault is at enable time from a client the bootloader left running.** A software walk reproduces CB0's exact walk (`l1[3] -> l2[384] -> l3[0] = 0x8f0cc643`, PA 0x8f0cc000), so the stage-1 tables are right, cleaned and flushed; yet `CB0 FSR` is already non-zero the instant `SCTLR.M` goes to 1, before our CP kick, and the CP never leaves the ring. Widening `SMR0` from mask 1 to mask `0x7F` changes the fault signature (stream matching was wrong: the GPU's SID is not 0), and cleaning every descriptor page changes nothing. Two diagnostics are untrustworthy: `smmu_atos()` always prints PASS with `par=0` (wrong poll register), and our CB_FSR/CB_FAR offsets return 48-bit nonsense, so use `Fsynr1` for the faulting SID and a GPU soft reset before enabling. Reverted to `smp7-gpu20`; captures `4k-smp7-gpu24-walk.txt`, `4k-smp7-gpu26-smr.txt`, `4k-smp7-gpu27-clean.txt`.

- **2026-10-29 09:45 — SMMU translation: the walker works, the first GPU-VA fetch does not.** Built a `gpumair` boot arg (MAIR0 attr0; 0x44 = Normal non-cacheable, 0xFF = write-back) and booted `gpu_identity=0 gpumair=0x44`. The SMMU programs cleanly (`TTBR0 0x93d30000 SCTLR 0x67 TCR 0x00800020 MAIR0 44`) and the GPU then faults once, `CB0 FSR 0x402 FAR 0xf0000000`, and never reaches `Adreno 610 ready`; presents stay at 5. `0xf0000000` is `VA_KERNEL`, the base of our own GPU-VA allocator, so this is a **translation fault on our IOVA, i.e. stage-1 walking works** and the bug is the mapping/TLB visibility of the first submission, not the hardware. Reverted to the identity build; the image `smp7-gpu21` is deleted and `smp7-gpu20` is back on the phone. Capture `4k-smp7-gpu21-smmu.txt`.

- **2026-10-29 09:40 — the latch wait is clean; skipping clears gains nothing; resting build back at ~50 fps.** A probe around the MDP latch poll in `showDirect()` reports `latch max 16.5-17.3 ms, 73-79 of 256 frames over 8 ms, 0 expired`: presentation always completes within one vsync, so the presenter is not serialising the compositor. The clear-skip path (`gnoclear=1`) was then tried on hardware: presents **150-238 per 5 s** versus **205-267** without it - no improvement inside the run-to-run noise, so it stays off (and it carries a visual-corruption risk). Resting image `smp7-gpu20` (`3e0e03924a99...`, kernel `4eeeac6b`, `frameShown()` + latch probe in), captures `4k-smp7-gpu20-latch.txt`, `4k-smp7-gpu17-intervals.txt`. The 60 fps target now needs **~17% less work a frame**; the clears (2 ms) and the latch are both excluded as causes.

- **2026-10-29 09:25 — the phone is at ~50 fps; the gap to 60 is a hitch tail, not throughput.** `AppleCLCD::frameShown()` (in the display path, printed every 256 frames) shows the interval distribution during a real scroll: **102 intervals of 8.3-16.7 ms and 138 of 16.7-25 ms**, i.e. most frames meet vsync, with 7 at 25-33 ms and 8 outliers up to 112 ms. `swaps` per 5 s is **205-267 (41-53 fps)**. So presentation is vsync-paced, neither a 30 Hz lock nor the 16-40 fps the earlier `swaps` windows implied, and the "2-3x over budget" estimate was inflated by console-throttled measurements. What remains is the **hitch tail** - a handful of 25-112 ms frames per 256 - which is exactly the "frames skip / out of order" the user reports. Image `smp7-gpu17` (`f7be732af926...`), capture `4k-smp7-gpu17-intervals.txt`.

- **2026-10-29 09:15 — clears measured: ~2 ms, not the lever; and per-frame logging costs 17 ms a line.** A new wrapper census (`glclears=1`) shows 4.6 whole + 2.5 boxed clears a frame totalling **4.3 Mpix** (~1.7 screens, ~2 ms), so clears cannot explain the frame time - the draws can. The bigger discovery is a measurement trap: a 200-byte console line takes **~17 ms at 115200 baud**, which is exactly the median inter-frame interval seen with `glframes=1`/`glclears=1`, so every frame-timing number taken with per-frame logging enabled is throttled by the console, not by the GPU. Root reflashed because the on-device volume no longer matched `ios16-root-onesubmit.img` (journal region rewritten, `0x5a` fill; the phone mounts root read-write, so a stale image cannot be block-patched - always stream the whole image). Image `smp7-gpu16` (`5d6086e309e4...`), root `ios16-root-clears.img` (`c779e0bf...`), capture `4k-smp7-gpu16-clears.txt`.

- **2026-10-27 and earlier (`2026-10-28 20:45` back):** moved verbatim to `research/CITRUS-MAINTENANCE-ARCHIVE.md` to keep this file under its size budget. The findings that still matter are in §1A, §6 and §9.
