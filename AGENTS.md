# Citrus XNU port — active handoff

Updated 2026-10-26 08:20 (Asia/Jakarta). **Read this file top to bottom once; the
first three sections are the whole story.** Everything below "Historical" is old
context kept only for reference.

## 0. Where the project stands (one paragraph)

XNU boots from the 16 GiB HFSX iOS root on UFS, launchd and the daemons run,
backboardd + SpringBoard composite on the MDF, and on a good boot the phone shows
**the real iOS lock screen with a live updating clock** (confirmed 2026-10-26
06:26). The kernel console is now streamed **live over USB** (`/dev/cu.usbmodem*`,
`tools/usb-log.py`), which replaced the old "flash, stall, reset, pull from
recovery" loop. Two things are missing for a usable device: (1) the boot is
**non-deterministic** — only about one boot in eight shows the lock screen, the
rest stop somewhere between the Apple logo and SpringBoard's start, and (2) the
port has no touch / GPU / Wi-Fi yet, so the lock screen cannot be unlocked.

## 1. The current blocker, stated correctly: it is NOT one stall

Previous checkpoints called this "the ~150 s whole-kernel freeze". That framing is
**wrong and wasted a day**. What is actually happening:

The boot fails at a **different point every time**, and the failures look like
**bad or missing I/O results**, not a single deadlock. Measured today (all with
`sweetwdt=0`, i.e. the in-kernel panic watchdog disabled):

| build | config difference | observed outcome |
|---|---|---|
| usb6 | USB console | **reached and kept the iOS lock screen** (clock updating, 6 min) |
| usb7/usb8 | USB console + 5 s heartbeat print | heartbeat to T=147..157 s, then silent, Apple logo |
| usb9 | no heartbeat | silent ~70 s, Apple logo |
| nousb1 | **USB gadget off** | heartbeat to T=136 s then stop, Apple logo |
| slotsample | slot-1 IRQ recorder | heartbeat to T=156 s, `svc_runs` frozen at 31, no stall samples |
| quiet | **no userspace tee, no UFS log** | Apple logo |
| ptimer | 1 Hz physical-timer tick | **kernel alive to 271 s** but userspace died: `shared_region ... vm_shared_region_start_address() failed`, `libignition: failed to lookup preboot`, only 12 KB of log, 107k free pages |

Hysteresis check: a stalled boot left for **9.5 minutes never recovers**.

So:
- it is **not** the `sweetwdt` panic (stalls happen with it off);
- it is **not** USB (a boot with the gadget entirely off stalls);
- it is **not** console spam (a build with the tee and UFS log off stalls);
- it is **not** "just slow / pageout thrashing" (see the 9.5 min above);
- it is **not** one reproducible deadlock — the failure point moves.

## 2. The working hypothesis to act on (highest value next step)

**The UFS driver occasionally returns late, stale, short or wrong completions, so
file reads/writes fail or hang. Userspace then derails in whatever subsystem
touched that I/O next** — hence "shared region can't be mapped", "ignition can't
find preboot", "SpringBoard stops after loading its store-demo plugin", and total
stalls. Stalled boots always leave a thread inside the driver (`ufs_users=1`).

`bsd/dev/sweet_ufs.c` uses exactly **one** UTRL slot, one UCD and one bounce
buffer, and `ufs_scsi()` has four concrete defects:

1. **No response-tag check.** `su.tag` is a byte bumped with `++` and the returned
   UPIU's tag is never compared, so a late completion from an earlier (timed-out)
   command is accepted as the current one.
2. **Timeout does not drain.** On timeout it writes `REG_UTRLCLR` and returns; the
   device may still deliver that response later, into the *next* command. Needs a
   real stop/clear/restart of the ring (stop UTRLRSR, clear doorbell, re-program
   UTRLBA/UTRLBAU, restart) or at minimum draining + tag matching.
3. **No residual/short-transfer check.** Only OCS and response bytes 0/6/7 are
   inspected; a short read is invisible and looks like valid zeros — exactly the
   symptom of an empty/broken dyld shared-cache mapping.
4. **Cache maintenance defaults to the conservative path** (`ufscache=0` → every
   transfer is a full clean+invalidate). Audit read direction against
   `flush_dcache64(pa, len, TRUE)` and `clean_dcache64(...)` in that file.

Suggested order: tag validation + completion drain first (cheap, low risk), then
the residual check, then re-run the same image 3–4 times and count how many boots
reach the lock screen. Fixing this is expected to fix both reliability and boot
time (retries/timeouts vanish).

If that does not explain it, the next instrument already exists: the **1 Hz
physical-timer tick** (`sweetptimer=1`, PPI 18) whose ISR records through UTRL
slot 1 and survives when the virtual-timer path dies.

## 3. What was built and proven today (do not redo)

**Live console over USB — works, this is the big infrastructure win.**
`bsd/dev/sweet_usb.c` is a full DWC3 gadget (ported from Topaz) plus a CDC-ACM
function; the kernel streams its console ring to bulk IN, macOS shows
`/dev/cu.usbmodem00011`, and `tools/usb-log.py` prints it (autodetects the port,
no root, no network config, reports silence instead of hiding it). Citrus facts,
all verified on hardware:

- DWC3 wrapper `ssusb@4e00000`, core regs at **`0x04e00000`** (size 0xcd00),
  **QSCRATCH at core + 0xf8800**.
- **GCC is at `0x01400000`, size `0x1f0000`** (DT `/soc/qcom,gcc@1400000`). The
  old Topaz value `0x00100000` is *not* GCC here; reading it wedges the bus and
  silently killed four boots before their first log flush. This was the single
  most expensive mistake of the day.
- USB is **fully powered down** when XNU starts (measured: `usb30_prim` GDSCR
  `0x00222001`, every USB CBCR has CLK_OFF). Working bring-up
  (`sweet_usb_power_on()`): clear GDSCR bit0 and poll bit31 (comes back
  `0xf8222000`); enable `ahb2phy-usb` 0x1d008 and deassert its BCR 0x1d000;
  enable `usb30-master` 0x1a010, `sleep` 0x1a014, `mock-utmi` 0x1a018,
  `cfg-noc-axi` 0x1a084, `ahb2phy-usb` 0x1d008, `usb3-clkref` 0x9f000; pulse
  `usb30` BCR 0x1a000.
- **QUSB2 PHY is `qusb@1613000`** (the "0x088e2000" in older notes is wrong — that
  was SM7150). Register layout = `phy-qcom-qusb2.c` `msm8996_regs_layout`
  (PLL_STATUS 0x38, TUNE1-4 0x80/84/88/8c, TEST2 0x9c, POWERDOWN 0xb4). The board
  init sequence is in the device tree's `qcom,qusb-phy-init-seq` (value,offset
  pairs) and is applied verbatim; reset via GCC `GCC_QUSB2PHY_PRIM_BCR` 0x1c000.
  PLL locks (status bit 5).
- **HS-only needs the pipe clock from UTMI**: QSCRATCH `GENERAL_CFG` (0x08) |=
  `PIPE_UTMI_CLK_SEL|PIPE3_PHYSTATUS_SW`, clear `PIPE_UTMI_CLK_DIS` (dwc3-qcom's
  `select-utmi-as-pipe-clk`). Without it the DWC3 command engine rejects
  SETEPCONFIG ("ep0 cmd 0x1 timeout").
- **EP0 max packet must be 64** (HS), not 512. VBUS override still required:
  QSCRATCH `HS_PHY_CTRL` 0x10 |= `UTMI_OTG_VBUS_VALID|SW_SESSVLD_SEL`,
  `SS_PHY_CTRL` 0x30 |= `LANE0_PWR_PRESENT`.
- `ud.lock` must be allocated by hand — it used to come from `ud_if_create()`,
  which the ACM switch removed. Symptom of forgetting: the console streams exactly
  one chunk and stops.
- The old CDC-ECM/UDP path enumerates fine but never delivered datagrams; it is
  gone. Sockets/routes are more fragile than a serial line.

**Diagnostics that now exist** (all in `bsd/dev/sweet_ufs.c` unless noted):

- flight recorder block + 4 MiB console ring at the end of userdata
  (`tools/pull-sweetlog.sh NAME` pulls and decodes: heartbeat v2, stall samples
  v3, console log).
- **interrupt-side stall recorder on UTRL slot 1** with its own UCD and bounce
  buffer (`ufs_diag_write_block()`), so samples are recorded **even while a thread
  holds `sweet_ufs_lock`** — the case the old version could not see.
- **independent 1 Hz tick on the ARM physical timer** (`sweetptimer=1`, PPI 18),
  ISR in `osfmk/arm64/sleh.c`, re-armed in `sweet_ufs.c`; records the interrupted
  PC, uptime, in-flight UFS op and its own tick count.
- `sweet_ufs_op_string()` exposes the in-flight command (opcode, length, age) to
  any healthy thread.

## 4. Traps that cost boots today — read before editing the kernel

- **Never call `PE_parse_boot_argn` from interrupt context.** It killed every boot
  within seconds (panel7..usbprobe2) and looked like a new freeze. Resolve boot
  args once in thread context (`sweet_irq_writes_resolve()` in `sweet_ufs_init`).
- **`mach_absolute_time()` is 24 MHz ticks here, not nanoseconds.** A literal
  `now + 5*1000000000ull` "5 s" period is really ~208 s. Always use
  `nanoseconds_to_absolutetime()` / `absolutetime_to_nanoseconds()`.
- **`sweetwdt=<s>` panics the kernel by design** (`sweet_wdt_thread` in
  `sweet_sample.c` prints then panics). Keep `sweetwdt=0` unless you want a panic.
- Frequent `printf` from the USB log thread is **suspect** (the two builds that
  printed a 5 s heartbeat stalled while the one that did not reached the lock
  screen; the build without heartbeat also stalled, so it is not proven). The
  heartbeat is opt-in: `sweetusbbeat=1`.
- **Interrupt-side UFS writes must never use slot 0** (the driver's). Use the
  slot-1 helper. `sweetirqwr=1` deliberately re-enables the old unsafe path; leave
  it 0.
- Panel drawing from the timer interrupt (`sweetpanel=2`) has never actually been
  seen on the panel; do not rely on it as a display channel.
- A dead console stream is **not** proof the kernel is dead (re-open the tty; on
  usb6 buffered output came later). Always ask the user what the screen shows.
- Any new MMIO base must be checked against
  `device-dumps/20261025-141423-923416/live-tree.json` (authoritative for
  bengal/SM6115). Do not trust the older Topaz-derived notes in this file.

## 5. Boot args reference (current best set for userland work)

```
debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=ufsroot0
ufsrw=1 rootrw=1 wdt=-1 wdt_test=no_user_checkin
unentitled_ios_sim_launch=1 launchd_unsecure_cache=1
sweetkeys=0 sweetbattery=0 sweetcpufreq=0 sweetchg=0 sweethw=0 sweettouch=0
sweetscan=mobileactivation
sweetnull=backboardd,SpringBoard,mobileactivation   # or '-' to reduce console load
sweetfb_stayon=1 sweetfb_native=1
sweetwdt=0
sweetpanel=1            # 1 = bookkeeping only, 2 = also draw (unreliable)
sweetirqwr=0            # never use slot 0 from an interrupt
sweetusb=2              # 1 = probe only, 2 = power up + enumerate + live console
sweetusbbeat=0          # 1 = 5 s SWEET LIVE printf (may perturb timing)
sweetptimer=1           # 1 = independent 1 Hz physical-timer tick
sweetlog=0              # 1 = also write the console ring to UFS (slower)
sweetsample=-           # disable the 90 s process sampler
```
Boot-time knobs used for speed: `sweetlog=0`, `sweetsample=-`, USB polling is
10 ms once configured, console chunks 1 KiB.

## 6. Build / flash / test loop

```
# kernel (rebuilds exception.o rtclock.o video_console.o serial_console.o
# sweet_sample.o sweet_ufs.o sweet_usb.o SweetFramebuffer.cpo)
python3 tools/rebuild-kernel.py

# payload + boot image (23.7 MB), then flash
python3 upstream/ios-topaz/tools/mkpayload.py \
    out/citrus-kernel/kernel.development.citrus \
    out/citrus-kernel/citrus-ufsroot-disp-ram1792.adt \
    out/citrus-kernel/payload-<name>.bin --cmdline "<args>"
python3 tools/build-diagnostic.py \
    --template device-dumps/20261025-141423-923416/backups/boot.img \
    --payload out/citrus-kernel/payload-<name>.bin
mv out/citrus-diagnostic/citrus-xnu-boot.img out/citrus-diagnostic/citrus-xnu-boot-<name>.img

# the user resets the phone with Power + Volume Down (nothing is automatic)
fastboot flash boot out/citrus-diagnostic/citrus-xnu-boot-<name>.img
fastboot reboot
python3 tools/usb-log.py -o out/ios16/logs/<name>-live.txt   # live console

# only when the boot must be inspected after a reset:
fastboot reboot recovery && tools/pull-sweetlog.sh <name>
```
`kernels/patches/0002-*.patch` must be regenerated after kernel edits: it is a
`diff -u` of the changed files against `/tmp/origbt/xnu/...` extracted from
`out/upstream-artifacts/xnu-buildtree.zip`. The current file list is: sweet_ufs.c,
sweet_sample.c, sweet_usb.c, osfmk/kern/exception.c, osfmk/arm/rtclock.c,
osfmk/arm64/sleh.c, osfmk/console/video_console.c, osfmk/console/serial_console.c,
pexpert/arm/pe_fiq.c, iokit/Kernel/arm/SweetFramebuffer.cpp.

## 7. Phone state at STOP (2026-10-26 08:20)

Phone is in **OrangeFox recovery** (`adb devices` → `recovery`), boot partition
holds `out/citrus-diagnostic/citrus-xnu-boot-ptimer.img`
(`sweetptimer=1`, `sweetlog=1`, `sweetnull=-`, `sweetusb=1`, `sweetwdt=0`).
Its recorder was already pulled: the kernel was alive at uptime 271 s while
userspace failed in `shared_region`/`ignition` (see the table in section 1).
No image is currently mid-test; the next boot is free to use.

Reference images worth keeping: `citrus-xnu-boot-usb6.img` (the one that reached
the lock screen), `citrus-xnu-boot-ptimer.img` (latest diagnostics), and the
`usb5..usb10` series for the USB port's evolution.

## 8. Next work, in order

1. **Fix `ufs_scsi()`** (section 2): response-tag validation, drain/reset on
   timeout, residual-length check. Rebuild, boot the *same* image 3–4 times, count
   how many reach the lock screen. Expected: reliability goes up and boot gets
   faster. This is the highest-value change in the project right now.
2. If reliability is still poor, use the physical-timer recorder
   (`sweetptimer=1`) plus `tools/pull-sweetlog.sh` to capture the interrupted PC
   and in-flight command at the moment of failure, and check whether the tick ISR
   keeps running (CPU alive with a broken scheduler) or stops (interrupts masked).
3. Then continue the original list: **touch (FT8719 over SPI, QUP SE2
   `0x04a88000`, IRQ 93, reset GPIO 103)** to unlock the lock screen and reach the
   home/setup screen; mobileactivationd SIGTRAP; sandbox container-path patches
   0149/0936 (still not applied); GPU (Adreno 610); Wi-Fi.
4. Boot speed: after the I/O fix, measure boot-to-lock-screen and consider
   trimming daemons/`sweetscan`, and enabling more than one CPU (SMP is unported —
   there is no PSCI CPU start path in the kernel, only the shim's single CPU_ON
   handoff; a second CPU would also give the robust watchdog the port keeps
   needing).

## 9. Evidence produced today (all under out/ios16/logs/)

- `usb-live.txt` — the good boot's live console (usb6, lock screen, 531 execs).
- `usb7-live.txt`, `usb8-live.txt`, `usb9-live.txt`, `usb10-live.txt` — stalled
  boots' live consoles (5 s `SWEET LIVE` heartbeat with `ufsio`, `free`, `op`).
- `nousb1-sweetlog.txt` + `nousb1-heartbeat.txt` — USB-off control (stall at 136 s).
- `slotsample-{sweetlog,heartbeat,stalls}.txt` — slot-1 recorder; no samples
  because the timer interrupt stopped (`svc_runs` froze at 31).
- `ptimer-{sweetlog,heartbeat}.txt` — the alive-to-271 s boot with the
  `shared_region` / `ignition` failures.
- `nousb1-*`, `ptimer-*`, `usbprobe4-*`, `usb1-*` heartbeats document every
  `boot_id` of the day.

### Superseded checkpoint (2026-10-26 00:03 Asia/Jakarta)

Stopped at 89% used / 11% remaining five-hour, 28% used / 72% weekly. Phone was
in OrangeFox recovery; boot partition held
`out/citrus-diagnostic/citrus-xnu-boot-native-long.img` (payload
`payload-ufsroot-native-long.bin`). Root had the verified keychain ownership
fix. Final native-long boot showed only the Apple logo; log had only sample 0
(136923 bytes, flush #58). Symbolication of sample 0 is in
`out/ios16/logs/native-long-symbolicated.txt` (106 records, 238 shared-cache
addresses). SpringBoard t0 in that sample was in
`-[XBApplicationSnapshotManifestImpl _access_validateWithContainerIdentity:]`
-> `NSFileManager removeItemAtPath` -> `removefile`, i.e. it had long left the
old `LSContextInit`/container-XPC wait; containermanagerd was servicing
requests. RAM was hard-whitelisted at 1 GiB in `shim/xnu-loader.c` and
`tools/mk-citrus-adt.py` at that time.

**Next work, in order:**
1. Read final symbolication, especially SpringBoard t0, chronod, timed, DND and
   containermanagerd; compare with earlier samples. Avoid diagnosing permanent
   waits from one sample. Native-long SpringBoard t0 differs from earlier boots;
   chronod is also in a different stack, so startup does progress.
2. Check whether the missing later samples/flushes reflect memory/I/O stalls.
   Current RAM is hard-whitelisted in shim/xnu-loader.c and tools/mk-citrus-adt.py.
   A potential 1.75 GiB interval 0x80000000..0xefffffff stays below the first
   /proc/iomem reservation at 0xf3c00000. Do not naively expose 3 GiB.
3. Once stable, finish home/setup rendering. Native geometry has proven non-empty
   full-screen Apple-logo buffers; original 1125x2436 conversion targets were
   empty. Debug fallback remains; it can select stale content by RGB density.
   Existing "panel nz" probe reads the boot framebuffer fPixels, not necessarily
   the MDP's current flipped buffer, and counts alpha too; don't treat it as a
   real screenshot or proof of visible colour. Actual scanout capture would be
   useful if further rendering diagnosis is needed.
4. Sandbox container-path patches 0149/0936 remain candidates for extension
   support, **not applied**. containermanagerd has now been observed receiving and
   servicing requests (getxattr/lstat), so Mach delivery is not generally broken.

### What this continuation actually fixed / verified

1. **Wi-Fi identity lookup stalled lsd:** latest old cm2 sample was waiting in
   MobileGestalt while generating built-in app install identities, not the earlier
   container query. Disassembly showed fallback waiting for **IONetworkController**
   because Wi-Fi is unported. Added `/chosen/mac-address-wifi0` = six bytes
   **02:43:49:54:52:53** (synthetic locally administered identity) in
   `tools/mk-citrus-adt.py`. This is identity only; no Wi-Fi hardware enabled.
   Subsequent samples prove **lsd finishes seeding** and enters its server runloop.
2. **mobileactivationd migration crash fixed:** enabled existing
   `sweetscan=mobileactivation` and found `Failed to query keychain`, UCRT query
   **-25291**, SQLite cannot open `/Library/Keychains/keychain-2.db`.
   `/Library/Keychains` links to `/private/var/Keychains`; it was root:wheel 0755,
   while securityd runs **_securityd uid/gid 64:64**. Changed just that directory's
   ownership to 64:64. Native migration then succeeds: **zero mobileactivationd
   crashes**, daemon main sampled in CFRunLoop. No activation data-ark seed or
   binary activation patch was applied. Runtime confirms should_hactivate=true.
   Static code explicitly accepts missing UCRT certificate (-25300), unlike -25291.
3. **Display geometry:** after the keychain fix, original logical **1125x2436**
   swaps still referenced all-zero surfaces 3/5 and user saw Apple logo -> black.
   `sweetfb_stayon=1` correctly ignored display-off requests, so this was not
   simply an accepted framebuffer power-off. With **sweetfb_native=1**, dimensions
   are **1080x2340**, surfaces 2/3 actually contain the Apple logo, and normal
   directPresent works without selecting the debug fallback for those frames.
   User saw Apple logo throughout that native test. **Home/setup UI not proven.**
4. **Do not overinterpret samples:** keychain boot's SpringBoard t0 waited in
   `CHSWidgetDescriptorProvider -> CHSChronoServicesConnection descriptors:` ->
   BoardServices sync XPC. Native boot's chronod t0 waits on PlugInKit, pkd waits
   for LS store; SpringBoard t0 has advanced to `FMSharedFileContainer
   groupContainerURLWithIdentifier:` -> container XPC. **containermanagerd is
   actively handling requests**, in getxattr/MCMContainerCacheEntry verify and
   lstat/orphan cleanup. So Mach service delivery works; these samples do NOT
   establish the permanent container-XPC deadlock claimed in the older handoff.
   Later native log prints SBCoverSheet appearance / configuration-update messages.
   Long run is intended to distinguish slow startup from a stable blocker.

### Images / transfer / physical state

- Original offline `out/ios16/ios16-root.img` remains unchanged:
  SHA256 `e4161c8fdbf2e09e6398bcea72bb8b2ee296ee2ffd7016510da32c7efef0bee3`.
  Mounted **read-only** at `/Volumes/iOSRoot`, `/dev/disk4`, owners on, for ipsw.
  OS dmg remains closed. Do not re-stream this old original by mistake.
- Preserved complete phone-generated root **out/ios16/ios16-phone-2314.img**:
  SHA256 `330714ff092ee0c93c43f99d2584ef12678d170d2b437c78bac2e0ec8c8d8c7b`.
  Its `.json` records remotely hashed 256 x 64 MiB chunks; all verified. Kept
  unchanged. Pulled efficiently by cloning original and fetching 44 changed chunks.
- Working / flashed root **out/ios16/ios16-root-keychain.img**:
  SHA256 `0ee5bd34809984e05d88104f4bd5a1e6a78166b6b61c1b1f338ba478f3bb1732`.
  Native HFS replayed pending journal in a mounted working clone, then detached.
  Clean attributes 0x80002100; journal start=end=5220352. 329344 catalog items =
  190308 files + 139036 folders. Applied keychain ownership with --only-overrides.
  Exactly one catalog record changed; byte audit offsets **51645407**, **51645411**,
  both 0 -> 64. Rollback `out/ios16/backup/keychain-owner-2314.rollback`.
- **All 16 segments streamed and FULL on-device SHA matched** the keychain image
  before test boot. Proof: `userdata-stream-keychain.log`, `userdata-verify-keychain.log`.
  Subsequent writable XNU boots naturally change the device root, so don't expect
  it still matches the pre-boot image. Preserve generated state when editing again.
- Current boot is native-long as above. Prior working test boots retained:
  `citrus-xnu-boot-{mac,macscan,keychain,keychain-native}.img`.
- No recovery, bootloader, modem, persist, or partition-map writes. Only boot and
  userdata. Android data already gone by earlier authorization. Never claim iOS
  works just because XNU or the Apple logo works.

### Evidence and new tools

- Logs in `out/ios16/logs/`:
  `cm2-symbolicated{-clean}.txt` (old baseline), `resume-prior-sweetlog.{bin,txt}`,
  `mac-sweetlog.{bin,txt}` / `mac-symbolicated.txt`,
  `macscan-sweetlog.{bin,txt}` / `macscan-symbolicated.txt` (5 samples; migration
  failure strings), `keychain-sweetlog.{bin,txt}` / `keychain-symbolicated.txt`,
  `keychain-native-sweetlog.{bin,txt}` / `keychain-native-symbolicated.txt`.
- `tools/symbolicate-samples.py INPUT OUTPUT` uses ipsw against mounted dyld
  cache, honors each process's slide, recovers concatenated/truncated records,
  skips stack addresses / main-binary addresses. Look up executable offsets with
  LLVM separately. `ipsw dyld a2s ... ADDR -s SLIDE` needs no cache file.
- `ipsw dyld disass ... -q` avoids symbol cache generation; markup needs writable
  `--cache out/ios16/logs/ios16.a2s` (~730 MiB, already created). LLVM `--macho`
  ignores requested address bounds; plain `llvm-objdump -d --start-address=...`
  `--stop-address=...` correctly bounds disassembly. Saved MG and mobileactivation
  disassemblies alongside logs. These are ordinary ipsw/LLVM observations, not REA
  Evidence; REA MCP isn't registered, no configuration changes were made.
- `tools/hfs-read-adb.py --image IMAGE list /path` or `extract /path --output FILE`
  reads raw HFS without mount permissions. Also `--adb-cache NEW_DIR` for direct
  recovery reads (fresh cache per invocation). Read-only; small ordinary files
  only; hardlinks/symlinks/overflow data forks unsupported. Local extraction
  verified byte-identical to mounted com.apple.migration.plist.
- `tools/pull-image-adb.py --clone-base OLD.img --output NEW.img` is verified on
  this phone. Read-only device snapshot: hash all 256 x 64 MiB chunks, APFS clone,
  fetch differences, then recheck every final chunk. Needs recovery + unmounted
  userdata and unused output paths. Keeps failed .partial + manifest. Avoid naive
  full extra copies: host has only ~17 GiB free after snapshot.
- `tools/hfs-chown-inplace.py --only-overrides` preserves everything except TSV
  targets. Use it on **unmounted** working clones, retain rollback. Do NOT run
  global default ownership on generated phone state (would reset container owners).
  `out/ios16/keychain-owners.tsv` targets one directory; `root-owners.tsv` also has
  the new 64:64 override for future complete ownership rebuilds.
- Hardened `tools/stream-image-adb.sh`: pipefail; remote dd `&& sync`, so read/write
  failures cannot be hidden. Mocked source and receiver failures both stop; actual
  16-segment transfer and independent complete device hash passed. Still re-stream
  all 16 segments after image changes, never >2 GiB userdata fastboot writes.
- `adb wait-for-device` hangs when state is recovery. Check `adb devices` or use
  a recovery-specific wait. If sideload, user must cancel it on phone UI.
- Prepared `out/ios16/activation-seed.plist` matching 20H392 / 16.7.16 as fallback;
  **not applied**, no longer needed for the fixed migration error.

### Remaining work / constraints

- First finish long native run, identify any **stable repeated** wait and actual
  screen content. Native geometry fixes the proven empty conversion target issue;
  framebuffer debug probes/fallback remain and should be removed only once actual
  home/setup rendering is verified. No new kernel changes this continuation.
- Sandbox container path support (upstream 0149 + 0936) is still **unimplemented**.
  It may help extension/PlugInKit support, but do not blindly attribute every slow
  XPC request to it. Current sandbox op logs are GLOBAL first-use only, so silence
  for a daemon doesn't mean it receives no operations.
- RAM is now **1.75 GiB** (`--ram-mib 1792` in `tools/mk-citrus-adt.py`, loader
  whitelists 0x40000000 or 0x70000000), physically verified: 111632 free pages at
  boot. It did not change the stall. cpus=1 unchanged. Do NOT expose naive 3 GiB;
  /proc/iomem reserves 0xf3c00000..0xffbfffff and ranges near 0x13b4..0x13ff.
- Touch FT8719 SPI, GPU Adreno 610, Wi-Fi remain unported. Root/macOS permission
  or protected-container flags can block mounted reads; raw read tool avoids it.
- Final usage: **89% used / 11% remaining five-hour; 28% used / 72%
  remaining weekly**. Regularly call get_usage_limits. At about **10% REMAINING**
  in either window, stop work and fully update this file. No background automation.
- User asks if we can see phone: **no live phone screen access**; only user reports
  and logs. Can inspect an attached photo, but do not claim logs are a screenshot.

## Historical handoff below — superseded by the current checkpoint above

#### Earlier symbolication / container waits (2026-10-25 22:45)

`brew install ipsw` works. Mount the image read-only and symbolicate the kernel
sampler's addresses with:

```
ipsw dyld a2s /Volumes/iOSRoot/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64 <addr> -s <slide>
```

`slide` is on the `SMP name[pid] slide 0x... mh 0x...` header line; `ipsw` applies
it itself. This turns the sampler into a usable profiler (no `ipsw dyld a2s`
symbol cache write is needed; the read-only volume is fine).

**SpringBoard is not crashed in the display builds. It is blocked in
LaunchServices, waiting for a reply that never comes:**

- SpringBoard t0: `___ulock_wait` <- `_LSContextInitCommon` <-
  `__LSContextInitWithOptions` <- `LaunchServices::Database::Context::_get` <-
  `-[LSApplicationRecord initWithBundleIdentifier:allowPlaceholder:error:]` <-
  `CCSModuleRepository _queue_filterModuleMetadataByAssociatedBundleAvailability:`
  <- `_BSCollectionFilter` (Control Center filtering modules by app presence).
- SpringBoard t1: `___NSXPCCONNECTION_IS_WAITING_FOR_A_SYNCHRONOUS_REPLY__` <-
  `xpc_connection_send_message_with_reply_sync` <- `_LSContextInitCommon`.
- lsd main thread: `-[_LSInstallProgressService performJournalRecovery]` ->
  `dispatch_sync_f_slow` -> waits for its own queue; the worker running that
  recovery block (lsd t1) is inside
  `-[MIInstalledInfoGatherer _groupContainersDictionary]` ->
  `+[MIContainer groupContainerURLsForBundleIdentifier:persona:error:]` ->
  `container_query_iterate_results_sync` -> `container_xpc_send_sync_message` ->
  sync XPC reply wait.
- containermanagerd is the peer and is **idle** (main thread in `CFRunLoopRun`,
  three workers in ulock wait; no `SWEET Sandbox` ops after startup). The query
  therefore never returns: this sync XPC is the current hard wall.

**Display milestone:** with the debug `present()` fallback (when the swap record
references an empty 1125x2436 surface, present the 1080x2340 surface that has
content) the panel shows the iOS **Apple boot logo** - iOS userspace content is
being composited and displayed. The home screen/Setup still does not draw because
SpringBoard is blocked as above. The fallback is a debug hack in
SweetFramebuffer.cpp (`SWEET FB: fallback frame surface ...`).

Candidate fixes for the container-XPC wall: add the upstream sandbox
container-path hook (0149 plus the 0936 `sweet_sandbox_container_path()` from
CFFIXED_USER_HOME; our Sandbox policy currently returns ENOENT for op 4 and
containermanagerd only logged ops 16/15/7), or investigate why launchd routes
that particular Mach service to a containermanagerd that never sees the message.


#### The big find: the attributes-file extent bug (fixed)

The persistent `hfs_swap_BTNode: invalid forward link (0x69742d74 >= 0x00000c00)`
/ `hfs: node=2950 fileID=8` / `hfs_mark_inconsistent` messages were NOT caused by
streaming. `FileID 8` is the **extended-attributes B-tree**, and it uses
**8192-byte nodes**: 3072 nodes = 6144 4 KiB blocks. The volume-header fork holds
8 extents (4608 blocks); the rest come from the extents-overflow record for
fileID 8, startBlock 4608. That record's 6th extent pointed at block **2909015**,
which is file data of another file (Finnish licence text), instead of the true
**2910039**. With the correct extent the tree is fully coherent: 2926 leaves,
283640 records, index traversal == leaf chain, 121 free nodes (2951..3071).
The true start was found by scanning the image for the 8 KiB node with
`fLink=2945 bLink=2943` (node 2943 in the 5th overflow extent has fLink 2944).
Fix: 4 bytes in extents-overflow leaf node 1 (block 2052), record fileID 8,
extent index 5: 2909015 -> 2910039. Backup of the old node:
out/ios16/backup/extents-node1-prefix-attrsfix.blk.

Validate with a read-only device: `hdiutil attach -readonly -nomount <img>` then
`fsck_hfs -f -n /dev/disk4` (a plain file path fails with "Can't get device block
size"). It now traverses the whole attributes B-tree and reports only count-level
nits (extended attributes 283640 vs 283639, orphaned blocks, dir/free counts).

On the phone this eliminated the corruption messages completely (zero in a
2-minute boot) and lsd, backboardd, installcoordinationd, analyticsd and tccd
stopped crashing. Only mobileactivationd (sig 5, `brk #1` at main+0x1bf3bc,
~8x/min) and, in no-display builds, SpringBoard still crash.

#### Kernel log channel works — the "sweetlog=1 hang" was a filter

`sweetlog=1` was ALSO parsed by `_cnputs` in osfmk/console/serial_console.c as a
word filter for the on-screen console, so the screen only drew lines containing
"1" and looked frozen at "SWEET EARLY 20". The log thread was writing normally all
along. Kernel change: the screen filter boot-arg is now **`sweetlogmask`** (local
buildtree; serial_console.o is now a rebuild target in tools/rebuild-kernel.py).
Boot with `sweetlog=1 ufslogsecs=2`, let it run, then pull from recovery:

```
bytes=$(adb shell blockdev --getsize64 /dev/block/by-name/userdata | tr -d '\r')
skip=$((bytes/4096-1025))
adb exec-out "dd if=/dev/block/by-name/userdata bs=4096 skip=$skip count=1025 2>/dev/null" > log.bin
python3 upstream/ios-topaz/tools/sweet-log.py log.bin log.txt
```

The log area is the last 4 MiB + 4 KiB of userdata (outside the 16 GiB image), so
re-streaming the image does not erase it; each sweetlog boot overwrites it.

#### Display: pipeline proven; the swapped surfaces are empty

- Build the ADT with display:
  `python3 tools/mk-citrus-adt.py out/citrus-kernel/citrus-ufsroot-disp.adt --ufs --display`
- AppleCLCD starts and owns the panel: `SWEET FB: DSI0 ctrl 0x1f7`,
  `MDP VIG0 src 0x5c000000 stride 4320 (boot), direct scanout ready`,
  `AppleCLCD 1080x2340 stride 4320 at 0x5c000000, default surface 1, presented as 1125x2436`.
- backboardd opens it and swaps, and the panel really updates, so the kernel
  display path works. The frame the swap record references (1125x2436 surfaces 3
  and 5) samples as all zero, but 1080x2340 surfaces 2 and 4 contain the Apple
  boot logo (rgb-nz ~1%). The debug fallback in present() shows that logo on the
  panel, proving iOS-composited content can be displayed. The UI does not draw
  because SpringBoard is blocked (see the symbolication section at the top).
- backboardd keeps looking for IOAcceleratorES / AppleM2ScalerCSCDriver; this
  kernel build has no GPU (the published archive predates the Adreno patches).
- Kernel changes in SweetFramebuffer.cpp: empty swaps no longer clear the panel;
  `SWEET FB: present ...`, surface/panel RGB probes and the fallback present are
  debug instrumentation and can be removed once SpringBoard draws.

#### launchd logging rules (learned the hard way)

- **Never point a launchd job's StandardOutPath/StandardErrorPath at
  /dev/console.** Such a job does not launch at all (this is also documented in
  bsd/dev/mem.c). This cost two boot cycles: backboardd never started and
  SpringBoard relaunch-looped every ~30 s because its window server was missing.
- The intended channel is the kernel's `sweetnull` tee (bsd/dev/mem.c): it copies
  what the named processes write to /dev/null to the console as `|name| text`.
  Default `sweetnull=backboardd,SpringBoard`; add names (15-char p_comm forms,
  e.g. `containermanager`) or `sweetnull=-` to disable.
- `OS_ACTIVITY_DT_MODE=YES` / `CFLOG_FORCE_STDERR=1` in a job's
  EnvironmentVariables is harmless but did **not** mirror os_log to stderr on this
  build (only plain stderr appeared). Do not rely on it for os_log.

#### Phone state at STOP

- Phone in OrangeFox recovery (`adb devices` -> recovery, root shell). Sometimes
  adbd comes up in ADB Sideload mode; the user cancels "ADB Sideload" in the UI.
- userdata = full 16-segment stream of out/ios16/ios16-root.img (always verify:
  `adb shell "dd if=/dev/block/by-name/userdata bs=1048576 count=16384 2>/dev/null | sha256sum"`).
- boot = out/citrus-diagnostic/citrus-xnu-boot-cm2.img (kernel with the
  serial-console filter fix, the empty-swap guard, surface/panel probes, the
  debug fallback present, and the sampler set to SpringBoard,lsd,containermanager),
  cmdline sweetlog=1 ufslogsecs=2, display ADT. Disp6/7/8 and native variants are
  kept next to it.
- Local image hashes seen this session (out/ios16/ios16-root.img):
  * 857b5858... old, corrupt attributes extent
  * 4018d05a... attributes extent fixed
  * c6b8d4ef... attributes fix + backboardd/SpringBoard logging (SpringBoard loop)
  * ab794fa5... attributes fix + backboardd stdio logging (SpringBoard loop)
  * e4161c8f... attributes fix + backboardd env-only logging (current image;
    checkpoint clone out/ios16/ios16-root.checkpoint-2250.img)

#### Exact next steps

1. **Break the container-XPC wall** (see the symbolication section): SpringBoard ->
   LaunchServices -> lsd -> `+[MIContainer groupContainerURLsForBundleIdentifier:]`
   -> sync XPC to containermanagerd never returns. Ideas, in order:
   a. Sample `launchd` and the XPC transport: check whether the Mach service the
      query targets is registered (containermanagerd is running and idle).
   b. Add upstream sandbox container-path support (0149 + 0936
      `sweet_sandbox_container_path()` reading CFFIXED_USER_HOME); our Sandbox
      policy still returns ENOENT for op 4.
   c. Try booting with the LS install-progress journal impossible to replay or
      with `sweetsample` on more daemons to see who else blocks on the same XPC.
2. Once SpringBoard draws, remove the debug probes/fallback in SweetFramebuffer.cpp
   and check the home/Setup screen (milestone 2).
3. mobileactivationd SIGTRAP: crash pc is a `brk #1` at main+0x1bf3bc; the code
   around it is an os_crash/assert sequence ("main", line numbers 363/321/310).
   Disassemble `/usr/libexec/mobileactivationd` at VA 0x1001bf3bc (llvm-objdump)
   for the exact site; it may matter for activation/SpringBoard state.
4. Then RAM (1 GiB hard-coded in shim/xnu-loader.c and validated there) and
   cpus=1 (one Gold), which SpringBoard will need.
5. Touch (FT8719, SPI not I2C), GPU (Adreno 610) and Wi-Fi are still unported.


### What was wrong and how it was fixed

The 16 GiB root image could not be attached ("no mountable file systems").
fsck_hfs reported `Invalid catalog PEOF`. Cause: the catalog file's extents
overflow records (extents overflow B-tree, fileID 4) had been rewritten in
little-endian with a wrong continuation key and two bogus extents that actually
belong to another file (they contain Mach-O/strings data). The catalog B-tree
itself was intact.

Reconstruction (read-only forensics, no guessing): the catalog's true layout was
recovered by scanning the whole image for catalog leaf/B-tree nodes, walking the
leaf fLink/bLink chain from the last leaf (node 1 at block 5124), and clustering
`physical_block - node_number` into constant-delta runs. Result — 18 extents,
25600 blocks total, matching the volume header exactly:
5123+2816, 8066+4096, 12418+512, 13186+1024, 14466+1024, 15746+1024,
17026+1280, 18562+1280 (the 8 in the volume header), then
20098+1536, 21890+1280, 23426+1280, 24962+1024, 26242+1280, 27778+4864,
2087439+512, 2087967+256, 2907535+256, 2949132+256.
Validation anchors: node 0 header, node 1 last leaf (fLink 0), node 11055 root
index at height 4, node 25009 first leaf with bLink 0 (block 2088144).

Only ONE 4 KiB node needed repair: extents-overflow leaf node 1 at block 2052.
It now holds three big-endian records (catalog 13056 with 8 extents; catalog
25088 with 2; attributes 4608 with 6) = 76 bytes each, header leafRecords 3.
Nothing else was written: the volume header, catalog B-tree header and catalog
nodes were already correct. Backups in out/ios16/backup/ (extents-node0.blk,
extents-node1.blk, catalog-header.blk, volume-header.bin,
alt-volume-header.bin) plus an APFS clone out/ios16/ios16-root.prefsck.img.

### Image now verified

- Mounts read-only and with `-owners on`.
- 326500 catalog items == 189295 files + 137205 folders (volume header), 25600
  catalog nodes, 25299 leaves; full `find` walk, zero I/O errors.
- The hidden NUL-named `HFS+ Private Data` folder exists (hard-link inodes), so
  counts reconcile exactly (4864 inode files + 42529 hard-link entries).
- Ownership is correct everywhere: root 0:0 (launchd/dyld 0755), /private/var/mobile
  501:501, /private/var/root 0:0 0750, diagnostics+uuidtext 272:272,
  containers/Bundle 33:33, keybags 0:0 0700, bring-up prefs 501:501 0600.
- Known remaining defects (all cosmetic, non-blocking):
  * (SUPERSEDED by "Late image fixes": the dangling hard links and the private
    folder valence were repaired and the sound file was restored from the dmg.)
  * fsck_hfs still reports two count-level errors: "Incorrect number of thread
    records" (orphan thread for the deleted CNID 48938) and "Incorrect number of
    file hard links".
  * fsck_hfs -y CRASHES (SIGTRAP) on this macOS 27 build during its repair
    phase, so these cannot be auto-repaired. `diskutil verifyVolume` works for
    diagnosis; plain `fsck_hfs` needs `-x` to avoid the same trap.
- This image HAS since been booted on the phone: launchd and many daemons run
  from it (see STOPPED HERE). It is no longer an untested artifact.

### New tools and rules

- `tools/hfs-chown-inplace.py` — SAFE offline ownership repair for a large HFSX
  volume. It parses the volume header + extents overflow itself, walks every
  catalog leaf, and rewrites ONLY the 8 bytes of ownerID/groupID inside existing
  records (rollback checkpoint via --rollback; --dry-run supported). It never
  searches/inserts/extends a B-tree, so volumes with a full catalog are safe.
  Rules: default 0:0; /private/var/mobile subtree 501:501; TSV overrides last.
  It is idempotent and asserts item count == fileCount+folderCount.
- `tools/hfs-owners.c` (libdmg-hfsplus based) is UNSAFE on this image: its
  updateCatalog search uses a ':'->'/' key hack while the volume is HFSX
  (keyCompareType 0xBC), and its write path corrupted the extents overflow
  records. Do not run it again on a real root image.
- tools/_hfslib.py is a copy of hfs-chown-inplace.py used for ad-hoc analysis
  scripts (import HFS/read_records).

### Downloads / disk

- The 087-86698-044.dmg OS image was re-downloaded successfully via
  upstream/ios-topaz/tools/remotezip.py: 4,730,814,044 bytes, zip CRC-32 ok
  (log out/ios16/os-redownload.log). Keep it closed unless a rebuild or file
  restore is needed.
- Source mounts are all detached. Keep in mind the OS dmg must stay closed
  unless deliberately rebuilding.

### Flashing route (important — fastboot cannot write >2 GiB here)

`fastboot flash userdata` on this bootloader accepts at most < 2 GiB:
1 MiB, 1 GiB and 1.9 GiB images flash fine; a 2 GiB image fails immediately with
"fastboot: error: Failed reading from userdata". `-S 512M` does not help, and the
sparse chunk `offset` field is 32-bit, so a 16 GiB volume cannot be streamed that
way at all. max-download-size is 804268032 (768 MiB) but the client sparsifies.
Consequence: the only way to place the 16 GiB root image on userdata is a raw
on-device write.

Chosen route (user approved): boot the already-installed OrangeFox recovery and
`dd` from an `adb shell` (root) into the userdata block device in 1 GiB segments.

- `fastboot reboot recovery` works on this device (it sets the BCB); `fastboot
  boot` does NOT (unknown command).
- In OrangeFox, adbd may come up in **sideload** mode (`adb shell` fails with
  "error: closed"). The user must cancel ADB Sideload in the recovery UI; then
  `adb devices` shows `recovery` and `adb shell` is uid=0, context u:r:su:s0.
- userdata is `/dev/block/sda11`, 50,582,138,880 bytes (47.1 GiB). Recovery was
  NOT modified (no recovery write); only boot and userdata are written.
- Root image: 17179869184 bytes. Its sha256 changes every time the image is
  modified; the copy currently on the phone is
  857b58582e90c15d1c836f0f05e0417dd1b5ffaba4872eaaae0d3f65ef77a1da
  (stream log out/ios16/userdata-stream2.log, verify out/ios16/userdata-verify2.log).
  Stream script: tools/stream-image-adb.sh.
- The first 1.9 GiB of userdata was already overwritten by the fastboot size
  probes, so Android's /data (F2FS + Magisk) is gone and Android will not boot.
  That is expected: user does not care about Android data.
- Fallback prepared but not needed yet: out/android-boot/boot-nodata.img is the
  original Android boot image with the userdata line in fstab.qcom commented out
  (`/data` never mounted). Could be flashed to get a root adbd without /data.

### Late image fixes (after the first verification pass)

- The volume header attribute word had to change from 0x80006000 to 0x80002100
  (journaled + kHFSVolumeUnmountedBit). The extra 0x4000 bit made DiskArbitration
  run fsck_hfs on every writable attach, and fsck_hfs crashes (SIGTRAP) on this
  macOS 27, so the image could not be mounted read-write at all. With the clean
  word, `hdiutil attach` mounts it read-write and the kernel manages catalog
  growth. Header backup: out/ios16/backup/volume-header.bin (pre-change).
- Restored the missing sound file from the re-downloaded OS dmg: both
  /System/Library/Audio/UISounds/connect_power.caf and
  /Library/Audio/Tunings/Generic/Haptics/AudioResources/ConnectedToPower.caf are
  now normal files, 163400 bytes, mode 0644, sha256
  0798b94bfb09376c25e516bcad05ad7f9bfe9aae6f9407db9ff131820bca7722 (the dangling
  hard-link records were removed first, with macOS doing the catalog work).
- Fixed the hidden private folder's valence 4865 -> 4864 in place, and set the
  volume header file/folder counts to the actual catalog contents
  (189296 files / 137206 folders; macOS created '.HFS+ Private Directory Data\r'
  while repairing the hard links). Ownership re-verified afterwards with
  tools/hfs-chown-inplace.py (idempotent, 0 items changed).
- Hard-link accounting is now fully consistent by direct analysis: 4864 inode
  files, 42527 hlnk entries, 42527 declared links, no absent inodes, no
  mismatches, no orphan inodes.
- Remaining fsck_hfs (read-only) output: only "Incorrect number of thread
  records" (one orphan thread for now-deleted CNID 48938) and "Incorrect number
  of file hard links". Both are count-level; fsck still crashes at the end of
  its run, so they cannot be auto-repaired. Do not chase them unless the kernel
  complains.

## User instructions and priorities

- Device: POCO M3 citrus, M2010J19CG, Indonesia, 4/64 GB, unlocked bootloader,
  rooted Android 13 Arrow/AOSP, OrangeFox installed. User does not care about
  Android data. Preserve bootloaders, modem, persist, recovery and partition map.
- Milestones: (1) XNU running, (2) display + iOS home/setup screen, (3) touch,
  (4) GPU and Wi-Fi.
- User authorized diagnostic boot flashing and restoration, then said to keep
  working until finished and that Android need not be rebooted between tests.
  Keep the original images available. Never claim iOS works from a kernel boot.
- Latest delegation preference: **only GPT-6 Luna** for subagents. Handle
  demanding work in the main agent. Earlier permission for GPT-6.1 Sol is revoked.
- **Regularly call get_usage_limits. At about 10% REMAINING in either window,
  stop work and update this file fully for another agent.** usedPercent is
  consumed usage, so remaining = 100 - usedPercent. Last check: 76% used / 24%
  remaining five-hour; 12% used / 88% remaining weekly. Check at build checkpoints.
  Do not create a background automation that consumes usage after stopping.

## Achieved on physical phone

1. Rooted ADB works, hardware identified and live DTB collected.
2. boot/recovery/dtbo backed up; local and device SHA-256 matched independently.
3. fastboot boot tested: transfer succeeds, boot command fails `unknown command`.
   Thus test images are flashed to **boot only**. Original restored afterward.
4. Custom ARM64 diagnostic runs and draws on ABL framebuffer.
5. PSCI CPU_ON handoff to Gold MPIDR affinity 0x100 works. Gold reports EL1,
   MIDR 0x51af8002, MPIDR 0x80000100, MMFR0 0x01011122, TGran16=1.
   Silver entry CPU: MIDR 0x51af8014, MPIDR 0x80000000, MMFR0 0x11122, no 16K.
6. XNU boots through scheduler/logging initialization and root selection
   (first panic was the expected missing md0).
7. **iOS userland runs from the HFS root volume on UFS**: HFS mounts as
   `iOSRoot`, XNU execs /sbin/launchd, launchd runs its boot tasks and enters
   ondemand mode, and many daemons spawn (xpcproxy, tccd, locationd, backboardd,
   installcoordinationd, mobileactivationd, logd, analyticsd, ...).
8. **The iOS lock screen renders and stays live** (2026-10-26 06:26, one boot in
   ~8 — the boot is intermittent; see sections 1–2).
9. **The kernel console streams live over USB** (CDC-ACM, `tools/usb-log.py`).
10. Still missing: touch (FT8719 SPI), GPU (Adreno 610), Wi-Fi, and deterministic
    boots. See section 8 for the plan.

## Current physical state

Superseded — see **section 7 "Phone state at STOP"** at the top of this file.
Standing rules that still apply: reset with Power + Volume Down (nothing is
automatic); only boot and userdata are ever written; no recovery/bootloader/modem/
persist/partition-map writes have ever been made.

## Important local artifacts

- `device-dumps/20261025-141423-923416/`: identity, CPU, /proc/iomem, input,
  device logs, live.dtb (543616 bytes), decoded live-tree.json.
- `.../backups/{boot,recovery,dtbo}.img`, manifest.json.
  boot 134217728 bytes SHA256
  `77c77db8a23ab9cfc92a4e6001a41a1762b78ec9d11a4f34cf535bf747dbe6c1`.
  Recovery SHA256 `99068895dccab41b422879ebda54ad9c2d7ccf60eac0e4498f503e2f9fddb03a`.
- `devices/citrus.observed.json`: hardware and transcribed diagnostic evidence.
- `out/citrus-kernel/kernel.development.citrus`: locally rebuilt XNU (~19 MiB).
- `out/citrus-kernel/{citrus.adt,payload.bin,boot-image-manifest.json}`.
- `out/citrus-diagnostic/citrus-xnu-boot.img`: physical test 1, ~23 MiB.
- `out/citrus-diagnostic/citrus-diagnostic-boot.img`: diagnostic-only version.
- Everything under out/, upstream/, device-dumps/ is ignored by root .gitignore.
  The repository is public: https://github.com/ezariago/ios-citrus (branch
  master). Commit only milestone-level changes, not every experiment.

## Hardware confirmed

- CPU Kryo260/A53/A73-class; boot starts Silver and must hand off to Gold.
- GICD 0x0f200000, GICR 0x0f300000, region 0x100000, stride 0x20000.
- CNTFRQ 19200000; virtual timer INTID19 (DT PPI3), physical timer18.
- Display 1080x2340 60 Hz, FT8719 Truly v2 video panel.
  ABL scanout framebuffer **0x5c000000**, stride **4320/0x10e0**, source format
  **0x237ff**. Splash reservation 0x5c000000+0xf00000.
- MDP regs 0x05e00000; VIG0 source 0x05e05000, DMA source0x05e25000.
  SRC_SIZE +0, SRC_XY+8, OUT_SIZE+c, OUT_XY+10, ADDR+14, STRIDE+24,
  FORMAT+30, UNPACK+34, OPMODE+38, MULTIRECT+170.
- Touch FocalTech **FT8719**, SPI mode1, 6 MHz, QUP SE2 0x04a88000,
  CS0, TLMM reset GPIO103, IRQ93, 10 contacts, coords 1080x2340.
  Topaz FT5452 I2C driver is NOT usable as-is.
- GPU Adreno610v1, DT chipid0x06010000, regs0x05900000.
- UFS 0x04804000. Original boot/recovery v2, image pages4096, embedded DTB.
- Live RAM banks: 0x40000000+0x3dd00000, 0xc0000000+0x80000000,
  0x80000000+0x40000000. Some user screen transcriptions have shifted digits;
  use binary DTB and /proc/iomem. First XNU uses 1 GiB at0x80000000 with no
  /proc/iomem reservation in that span. Topaz highmem starts nonexistent RAM.

## Source/build approach (works on this Mac)

- Host Apple Silicon, macOS27.0.1, Xcode27.1. Old Xcode15.4 not installed.
- Homebrew LLVM/lld23.1.4 installed during task; /opt/homebrew/opt/llvm/bin.
- `upstream/ios-topaz`: branch topaz at e4772911e116ab4ab6c4ac1f38e6106fefe8b483.
  Read its AGENTS.md/NOTES.md if editing that checkout. No changes made there.
- Downloaded matching published artifacts from MakrSas/ios-topaz:
  kernel id12263212928, buildtree12262938798, run39419628786,
  commit2665612a9eabb76b294cbc1b014132c6b89d09db.
  Provenance/hashes: out/upstream-artifacts/artifact-manifest.json.
- Artifact `.link/` contains complete ~137 MB object archive, exported/alias
  symbols, linker flags; buildtree provides source + config/generated headers.
  Recompile only changed files, reuse existing IIG objects, avoiding new-IIG ABI.
- Logging library recompiled from Apple libdispatch tag1415.140.2,
  commitcdb61e93e803d0093635f356753a9a30c09836db into
  out/upstream-artifacts/firehose_buffer.o. Compile command JSON saved there.
- `tools/rebuild-kernel.py`: make -n gets correct original per-file compile flags,
  adds source include paths, -fno-lto, targets cortex-a53/arm64, min OS14;
  replaces sweet_early.o/start.o/arm_vm_init.o/SweetBattery.cpo in copied archive,
  relinks with logging object and cc_kext runtime.
- Raw kernel relink MUST OMIT `-rename_segment,__LASTDATA_CONST,__LAST` from
  archived .linkarguments. That extra option is for static kernel collections;
  with current linker it causes illegal text relocations for last constructor.
- Retained patch: kernel/patches/0001-citrus-diagnostic-console-and-driver-gates.patch.
  Applied to out/upstream-artifacts/buildtree/xnu, not upstream checkout.
  Changes old Sweet 0x9c000000 framebuffer refs to0x5c000000, height2400->2340,
  stage marker2368->2308; SweetBattery::start returns false before any hardware.
- `tools/mk-citrus-adt.py`: imports upstream ADT builder, one Gold core,
  no UFS/disp0/WLAN nodes initially. Lacks Apple /product seed (not needed yet).
- Kernel scan found zero LSE/RCpc instructions. TOPAZ_4K remains unset.

Build commands (artifacts already prepared locally):
```
python3 tools/rebuild-kernel.py
python3 tools/mk-citrus-adt.py out/citrus-kernel/citrus.adt
python3 upstream/ios-topaz/tools/mkpayload.py out/citrus-kernel/kernel.development.citrus out/citrus-kernel/citrus.adt out/citrus-kernel/payload.bin --cmdline 'debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 wdt=-1 wdt_test=no_user_checkin sweetbattery=0 sweetcpufreq=0 sweetchg=0 sweethw=0 sweettouch=0'
python3 tools/build-diagnostic.py --template device-dumps/20261025-141423-923416/backups/boot.img --payload out/citrus-kernel/payload.bin
out/test-env/bin/python tools/test-diagnostic.py --loader
```

Shim is own source under shim/: start.S, diagnostic.c, xnu-loader.c, link.ld,
font.h. Gold has separate stack, exceptions have emergency stack/recursion guard.
Loader validates SWEETXNU segments/ADT/ranges, copies into 1GiB bank, initializes
Gold GIC Group1/timers, passes 736-byte XNU boot_args. Synthetic Unicorn test
stubs CPU registers + unsupported GIC sysregs, checks real segment copies/entry.
Build/packager preserves original boot DTB, ramdisk, addresses. Header checked
byte-for-byte against AOSP mkbootimg. Wrapper is CITRUSPL+u64 length after _end.

## Next work

Superseded — see **section 8 "Next work, in order"** at the top of this file.
(The old text here described hunting a single "~150 s freeze", which turned out to
be the wrong model; the failure is intermittent I/O, see section 1.)

## Immediate handoff checklist

1. Read **sections 0–8 at the top** first; they replace every older checkpoint.
   The most important sentence in the file: the boot failure is intermittent and
   looks like bad/missing I/O results, so fix `ufs_scsi()` before anything else.
2. Never fastboot a >2 GiB image at userdata; use tools/stream-image-adb.sh from
   OrangeFox recovery.
3. After ANY change to the local image, re-stream all 16 segments and verify the
   on-device sha256 (partial segments caused misleading HFS corruption).
4. Keep unentitled_ios_sim_launch=1, launchd_unsecure_cache=1 and
   ufsrw=1 rootrw=1 in the cmdline for userland tests.
5. The kernel source of truth for local changes is
   out/upstream-artifacts/buildtree/xnu, and **every edit is captured in
   `kernel/patches/0001-*.patch` + `kernel/patches/0002-*.patch`** (0002 is a
   diff against the pristine `out/upstream-artifacts/xnu-buildtree.zip`).
   Rebuild with `python3 tools/rebuild-kernel.py` (it rebuilds exception.o,
   rtclock.o, video_console.o, serial_console.o, sweet_sample.o, sweet_ufs.o and
   SweetFramebuffer.cpo).
