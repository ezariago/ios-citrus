# Citrus XNU port — active handoff

Updated 2026-10-26 06:52 (Asia/Jakarta). Read this checkpoint first.

## CURRENT STATE — the kernel console is streamed LIVE over USB (new, works), and
## one boot of four reaches and keeps the iOS LOCK SCREEN. The remaining blocker is
## an INTERMITTENT stall (Apple logo / console stops) that is not yet explained.

### 2026-10-26 06:30 Asia/Jakarta — what changed today

**Milestone 2 reached.** The phone boots the HFS root, runs launchd and the
daemons, brings up SpringBoard/backboardd on the MDF, **draws the Apple logo,
then the iOS lock screen, and the clock/UI keep updating for minutes**. User
confirmed stable lock screen at 06:26. This is the first time iOS UI (not just
the boot logo) has been seen on this port.

**Live kernel+userspace console over USB works** (`sweetusb=2`). The kernel
exposes a CDC-ACM function ("Sweet iOS (USB console)"), macOS creates
`/dev/cu.usbmodem00011` about 40 s into the boot, and the kernel streams its
console ring to bulk IN. No root, no host IP config, no network stack.
`tools/usb-log.py` reads it (autodetects the port): the "adb logcat" channel we
wanted. Verified streaming kernel printf and `|SpringBoard|`/`|backboardd|`
stderr from `/dev/null` tees.

### The stall is INTERMITTENT and still unexplained (watchdog theory disproved)

History, measured today with the live USB console (builds usb6..usb9, all with
`sweetwdt=0`, i.e. the in-kernel panic watchdog disabled):

- **usb6** (no periodic heartbeat printed): reached the **iOS lock screen**, UI
  clock updating, still healthy after 6 minutes (user confirmed). Console output
  went quiet at ~60 s, and re-opening the tty later still delivered buffered
  output, so the kernel was alive the whole time.
- **usb7 / usb8** (5 s `SWEET LIVE` heartbeat printed from the USB log thread):
  heartbeats advanced every 5 s to T=147..157 s, then the console stopped and the
  screen stayed on the **Apple logo**.
- **usb9** (heartbeat off by default, everything else identical to usb8): console
  quiet at ~70 s, screen **Apple logo**, no data on re-open.

So (a) the old "whole-kernel freeze at ~150 s" is **not** a watchdog panic —
`sweetwdt=0` boots still stop — and (b) it is **not** deterministic: one boot in
four reached and kept the lock screen. Do not treat any single boot as canonical.

Both good and stalled logs reach the same SpringBoard lock-screen code path
(`SBCoverSheetPrimarySlidingViewController` appears in usb6 and usb9), so the
difference is how far the UI gets and/or whether it keeps presenting, not whether
SpringBoard starts. usb6 ran 531 `exec`s, usb9 279.

Free-page trend seen in the 5 s heartbeat (usb7/usb8): 111632 at boot ->
39658 at T=112 s -> 24611 at T=147 s (~340 pages/s). Worth checking whether the
stalled boots die later in a VM-pressure/compressor path with cpus=1; not proven.

The "UFS wedge holding sweet_ufs_lock" theory remains unproven (it rested on
`ufs_users=1` in a recorder written by a boot that also had the watchdog on).

### USB port status (new, working)

`bsd/dev/sweet_usb.c` is now ported from Topaz/SM7150 to **Citrus = bengal /
SM6115** and device mode works:

- **DWC3** wrapper `ssusb@4e00000`, core regs at `0x04e00000` (size 0xcd00),
  **QSCRATCH at core + 0xf8800**. Correct.
- **GCC is at `0x01400000`, size `0x1f0000`** (DT `/soc/qcom,gcc@1400000`).
  The old Topaz value `0x00100000` is NOT GCC here: reading it wedges the bus
  and killed four boots silently before the first log flush. This cost most of
  the debugging time today.
- USB power domain/clocks are **OFF** after ABL (measured): `usb30_prim` GDSCR
  `0x00222001` (bit31=0), all `usb30-*`/`cfg-noc`/`ahb2phy` CBCRs have bit31 set.
  Bring-up that works (`sweet_usb_power_on`): clear GDSCR bit0 and poll bit31;
  enable `ahb2phy-usb` (0x1d008) and deassert its BCR (0x1d000); enable
  `usb30-master` 0x1a010, `sleep` 0x1a014, `mock-utmi` 0x1a018, `cfg-noc-axi`
  0x1a084, `ahb2phy-usb` 0x1d008, `usb3-clkref` 0x9f000; pulse `usb30` BCR
  (0x1a000). GDSCR comes back `0xf8222000`, all CBCRs on.
- **QUSB2 PHY is `qusb@1613000`** (NOT 0x088e2000 — that was a wrong note from
  Topaz). Register layout = `phy-qcom-qusb2.c` `msm8996_regs_layout`
  (PLL_STATUS 0x38, TUNE1-4 0x80/84/88/8c, TEST2 0x9c, POWERDOWN 0xb4).
  The board's own init sequence is in the DT property
  `qcom,qusb-phy-init-seq` (value,offset pairs) and is applied verbatim;
  reset is GCC `GCC_QUSB2PHY_PRIM_BCR` 0x1c000. PLL locks (status bit5).
- **HS-only needs the pipe clock from UTMI**: write QSCRATCH `GENERAL_CFG`
  (0x08) with `PIPE_UTMI_CLK_SEL|PIPE3_PHYSTATUS_SW`, clear `PIPE_UTMI_CLK_DIS`
  (the equivalent of dwc3-qcom's `select-utmi-as-pipe-clk`). Without it the
  DWC3 command engine rejects SETEPCONFIG ("ep0 cmd 0x1 timeout").
- EP0 max packet must be **64** (HS), not 512.  VBUS override is still needed:
  QSCRATCH `HS_PHY_CTRL` 0x10 |= `UTMI_OTG_VBUS_VALID|SW_SESSVLD_SEL`,
  `SS_PHY_CTRL` 0x30 |= `LANE0_PWR_PRESENT`.
- The gadget body (EP0 state machine, bulk endpoints, TRBs) is Topaz code that
  ported unchanged.

**Console channel implementation:** descriptors are CDC-ACM (2 interfaces, bulk
0x81 IN / 0x01 OUT, int 0x82); `ud_log_thread` reads `sweet_log_copy()` straight
from the console ring and pushes 6 KiB chunks to the bulk IN endpoint. There is
**no ifnet/socket/UDP path any more** (the old ECM+UDP code enumerates fine but
never delivered datagrams; sockets/routes are more fragile than a serial line).
`ud.lock` must still be allocated by hand — it used to come from
`ud_if_create()`.

**Stability caveat:** the console stream itself sometimes dies (bulk IN transfer
left pending, e.g. if the host closes the tty). Re-opening `/dev/cu.usbmodem*`
recovers the buffered console on some boots (usb6) but not on others (usb9); a
dead channel is therefore NOT proof that the kernel is dead — always ask the user
what the screen shows. The periodic `SWEET LIVE` heartbeat is now **opt-in**
(`sweetusbbeat=1`) because it is still unclear whether frequent printf from that
thread contributed to the stalls.

**Timebase trap:** `mach_absolute_time()` is 24 MHz ticks here, not nanoseconds.
A `now + 5*1000000000ull` "5 s" period is really ~208 s. Always use
`nanoseconds_to_absolutetime()`. This bug is fixed in the log thread's
heartbeat but was the reason only one `SWEET LIVE` line ever appeared.

### Boot arguments that matter now

`sweetusb=2` (power up DWC3 + PHY, enumerate, stream the console),
`sweetusb=1` (probe GCC/clock state only, no writes),
`sweetwdt=0` (do NOT enable the 150 s stall watchdog while debugging a boot —
it panics),
`sweetpanel=1` = probe bookkeeping only, `sweetpanel=2` = also draw on the
console frame from the timer interrupt (drawing from IRQ is still suspect: every
build that drew died within seconds of the first draw),
`sweetirqwr=0` = keep the interrupt-side UFS heartbeat writes off.

**Never call `PE_parse_boot_argn` from interrupt context.** Resolve boot args
once in thread context (`sweet_irq_writes_resolve()` in `sweet_ufs_init`) and
have the IRQ path read the resolved value. Doing otherwise killed every boot
within seconds (panel7 through usbprobe2), which was misread as a new freeze.

### Phone state at STOP (2026-10-26 06:50)

Phone is ON, running `out/citrus-diagnostic/citrus-xnu-boot-usb9.img` (~06:44:53),
screen static on the Apple logo. Reset with Power + Volume Down for the next test.
usb6 (below) is the build that reached the lock screen; keep it as the reference.

Earlier, 06:30: phone **alive**, running `out/citrus-diagnostic/citrus-xnu-boot-usb6.img`
(`sweetusb=2 sweetwdt=0 sweetpanel=1 sweetirqwr=0`, payload
`payload-ufsroot-usb6.bin`), booted 06:22:16, showing the iOS lock screen.
Note usb6 predates the timebase fix; the next build (usb7) has a true 5 s
`SWEET LIVE` heartbeat and should be used to measure long-run stability.
`/dev/cu.usbmodem00011` is live; `tools/usb-log.py -o FILE` captures it.

### Next work, in order

1. **Characterise the intermittent stall** (this is the blocker; the watchdog
   theory is dead, see above). Ideas, cheapest first:
   a. Re-boot the *same* image several times and count how often it stalls. If it
      is ~1-in-4, look for a race rather than a fixed blocker.
   b. Boot `out/citrus-diagnostic/citrus-xnu-boot-usb6.img` again (the build that
      reached the lock screen) and compare its console with a stalled boot's.
   c. Use `sweetsample=SpringBoard,backboardd,launchd` (prints thread PCs every
      90 s from a kernel thread) on a stalled boot — the sample dump names the
      blocking stack. Note the sampler's output never appeared in the logs so far
      because the console is already silent by then; `sweetirqwr=1` +
      `tools/pull-sweetlog.sh` from recovery is the fallback.
   d. Consider the VM angle: free pages fell to ~24k (96 MB) by T=147 s at
      ~340 pages/s with cpus=1. A stalled boot's last heartbeat vs a good boot's
      is the cheapest discriminator.
2. **Watch stability with the opt-in heartbeat** (`sweetusbbeat=1`, real 5 s
   period now) once the stall is understood, not before: it may itself perturb
   timing.
3. **Lock screen → home screen**: it is stable but not unlockable; touch
   (FT8719 over SPI) is still unported, and the lock screen may be waiting for a
   passcode/press. Consider whether `sweetfb_stayon=1` + a synthetic HID event
   (SweetHID touch/buttons already open) can dismiss the lock screen for a test.
4. Then the original list: setup/home rendering, mobileactivationd SIGTRAP,
   sandbox container-path patches 0149/0936 (still not applied), touch, GPU
   (Adreno 610), Wi-Fi.

### Rules and traps learned today

- Before calling a boot "frozen", check that `sweetwdt` is 0 — the in-kernel
  watchdog panics by design.
- Any new MMIO base must be cross-checked against
  `device-dumps/20261025-141423-923416/live-tree.json` (authoritative for this
  SoC: bengal/SM6115). The GCC address was the single most expensive mistake.
- Flashing: `fastboot flash boot <img>` then `fastboot reboot`; the boot images
  are ~23.7 MB. To pull the UFS recorder you must still go through
  `fastboot reboot recovery` + `tools/pull-sweetlog.sh NAME`, but **most
  debugging no longer needs it** thanks to the USB console.
- Tests are reset with Power + Volume Down by the user (no automated reset).
- Use `tools/usb-log.py` (not a raw `cat`) so silence is reported as
  "kernel stopped printing" rather than being missed.

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
7. **iOS userland now runs from the HFS root volume on UFS**: HFS mounts as
   `iOSRoot`, XNU execs /sbin/launchd, launchd runs its boot tasks and enters
   ondemand mode, and many daemons spawn (xpcproxy, tccd, locationd, backboardd,
   installcoordinationd, mobileactivationd, logd, analyticsd, ...). Most of them
   then crash; that is the current frontier. See STOPPED HERE.

## Current physical state

- Phone is ON, running `citrus-xnu-boot-panel5.img` (boot partition), userdata
  still holds the 16 GiB HFSX root image (written by earlier boots; no re-stream
  since). It will be frozen at the usual stall. See **STOPPED HERE** at the top.
- Reset via PSCI_SYSTEM_RESET does not return automatically; after a panic or a
  completed boot the user has to hold Power + Volume Down to reach fastboot.
  Do not assume the phone re-enumerates on USB by itself.
- Before the XNU jump the shim writes the bootloader reason to IMEM 0x0c12565c so
  a watchdog reset should request fastboot. That is RAM/MMIO, not a partition
  write.
- No recovery, bootloader, modem, persist or partition-map writes have ever been
  made in this project.

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

1. Pull the recorder from the currently running panel5 boot and follow the
   decision tree in **Next work, in order** at the top: find the ~150 s freeze
   (UFS wedge vs kernel spin) before anything else.
2. Build a live console channel (USB DWC3 at 0x04e00000 / QUSB2 PHY) — the single
   highest-value infrastructure item; see item 2 at the top.
3. Then home/setup rendering (milestone 2), mobileactivationd SIGTRAP, sandbox
   container-path patches, touch (FT8719 SPI), GPU (Adreno 610), Wi-Fi.

## Immediate handoff checklist

1. Read **STOPPED HERE** first: it has the phone state, the attributes-extent fix,
   the working `sweetlog=1` method, the display findings and the launchd logging
   experiment.
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
