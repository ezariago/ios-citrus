# 4 KiB / seven-core boot: from crash loop to a usable lock screen

Captured 2026-10-29 01:05 (Asia/Jakarta). This is the reference account behind
§1A/§2A of `AGENTS.md`; `AGENTS.md` keeps only the current state.

## Result

`out/citrus-8core/smp7-ent8/citrus-xnu-boot-4k-smp7-ent8.img`, SHA256
`a00de0c834d471116bcd9a71532492dad5311daf2acb331cd224165937cc2985`, kernel
`/tmp/citrus-ent8/kernel.development.sweet.smp7` (local relink of CI archive
40531392449). Hardware, 7 CPUs (4 Gold + Silver 1-3), 4 KiB pages:

- lock screen up, clock updating, SpringBoard stable, ~64 fps presenting
  (`SWEET INTF1: 322 frames in 5 s`);
- 4 crashes in three minutes, all `driverkitd` (the 16 KiB reference boot has
  8, `gpu-poolarena1-live.txt`);
- touch works (user-confirmed), home gesture works (user-confirmed);
- host-driven reboot to fastboot/recovery works
  (`python3 usb-restart/reboot.py fastboot`).

## The wall: no AMFI, so nothing was ever code-signed

This port builds without an AMFI MAC policy, so `mpo_vnode_check_signature`
has no implementer. `ubc_cs_blob_add()` therefore never set `CS_SIGNED` or
`CS_PLATFORM_BINARY`; `csproc_get_blob()` returned NULL and every process
looked unsigned, unentitled and non-platform. That single defect produced
every userspace symptom:

| symptom | evidence capture |
|---|---|
| `+[SpringBoardUI load]` assertion, 135 of 845 exits | `4k-smp7-iopol1-live.txt` |
| `Assertion failed: (platformBinary), SBStaticInitializer.m:39` | `4k-smp7-ent1-live.txt` |
| SpringBoard/backboardd/lsd/installcoordinationd crash loop | 950-1,145 `CRASH` lines in the ident/iopol captures |
| `proc: table is full` | same captures |

Fixes, all inside `#if defined(ARM64_BOARD_CONFIG_SWEET)`:

1. `bsd/kern/ubc_subr.c`: in `ubc_cs_blob_add()` and in the revalidate path,
   a blob that passed `cs_validate_csblob()` gets `CS_SIGNED`, plus
   `CS_PLATFORM_BINARY` when `vp->v_mount->mnt_flag & MNT_ROOTFS`.
2. `bsd/kern/kern_exec.c`: before `proc_csflags_update(p, imgp->ip_csflags)`,
   force `CS_SIGNED|CS_VALID|CS_PLATFORM_BINARY`. exec's inheritance mask does
   not contain the platform bit at all, which is why SpringBoard still
   asserted after fix 1 (`SWEET CS: usermanagerd ... flags=0x0` before, then
   `0x24000001`).
3. `bsd/kern/kern_cs.c`, `bsd/kern/kern_proc.c`: the entitlement getters drop
   the `CS_SIGNED` gate, and `CS_OPS_{,DER_}ENTITLEMENTS_BLOB` fall back to
   `ubc_cs_blob_get(p_textvp, -1, -1, p_textoff)` and then to the signature's
   own XML/DER blobs. Diagnostic line (keep it while the port is young):
   `SWEET CS: <proc> der=<err> len=<n> flags=<hex>`.
4. `bsd/kern/kern_resource.c`: `iopolicysys_vfs_allow_lowspace_writes()`
   accepts platform binaries (the AMFI entitlement cannot exist here).

Crash counts per build, same root, same 7-core ADT: 1,145 (ident1) → 950
(csigned1, blob flags only) → 845 (iopol1) → 604 (ent1, entitlements
visible; SpringBoardUI assertion gone) → **4** (ent2, platform flags on the
process). The remaining four are `driverkitd`, benign.

## Touch: two independent bugs, both in the build inputs

1. **Zero-length firmware.** `bsd/dev/sweet_touch.c` includes the generated
   `sweet_touch_fw.h`. The CI tree carried a 105-byte stub
   (`citrus_ft8719_fw[] = {0}; len = 0`), so the FT8719 boot ROM was told
   `downloading 0 bytes`, never started its application image, and every
   later read returned `0x80`. The real header (264 KB, `len = 64336`) existed
   next to the source but was never in the build tree. Copying it in and
   recompiling `sweet_touch.o` made `mode9 downloading 64336 bytes` and the
   report loop work.
2. **Edge geometry.** `SweetHIDTouch::touch()` tested the edge band against
   the 1125x2436 logical height (`y > 2399 - 48`), but the FT8719 reports
   1080x2340, so a bottom swipe could never set
   `kIOHIDDigitizerEventFromEdgeTip`; UIKit derives `UITouch`'s edge type
   from that bit and therefore never armed the home gesture. The test now uses
   `2339 - 48`, and the log shows `SWEET HID: touch 0 down at 407,2334 edge`.

A patched `SweetHID.cpp` must be compiled into `SweetHID.cpo` and put in the
archive; the prebuilt member is the old code. Both the 4K tree and the 16K
GPU tree now hold the fixed source.

## Host command channel (no more button resets)

The 4K USB gadget is CDC-ACM with the bulk OUT endpoint already armed, but
`ud_rx_done()` dropped every packet because the port had no parser; the only
implementation ever built lived in a throwaway PMIC overlay. `bsd/dev/sweet_usb.c`
now carries `ud_cmd_feed()` (a 64-byte line buffer) plus `ud_pmic_restart()`:
PM6125 PON arbiter check (SID0, apps-owned APID), masked restart reason at
`0x88f` with readback, IMEM reason at `0x0c125650`, then
`PSCI SYSTEM_RESET`. Commands: `citrus:reboot:fastboot`,
`citrus:reboot:recovery`; gated by `sweetusbcmd` (default on). Verified twice
on hardware, including a full flash cycle; physical reset is no longer needed
for a normal iteration.

## Kernel provenance

`/tmp/relink-smp7.py` compiles the patched translation units with the exact
CI clang lines from
`out/citrus-8core/ci-run-40531392449/citrus-4k-compile-diagnostics/build.log`,
`ar r`s them into a copy of the CI archive, and relinks with the CI
`*.linkarguments`, `*.exp`, the local `libclang_rt.cc_kext.a` and
`firehose_buffer.o`. Objects: `serial_console.o`, `sweet_ufs.o`,
`sweet_usb.o`, `sweet_touch.o`, `SweetHID.cpo`, `SweetFramebuffer.cpo`
(copied in, its source needs the real FB header set), `kern_cs.o`,
`kern_proc.o`, `kern_resource.o`, `ubc_subr.o`, `kern_exec.o`. Local-ld
caveats stay: no `__LINKINFO`/`__CTF`, `__LASTDATA_CONST` merged into
`__LAST`; always run the shim test
(`PYTHONPATH=out/citrus-8core/preflight/python-deps python3
tools/test-diagnostic.py --loader <img>`) before flashing.

## Boot arguments of the working image

`debug=0xc serial=3 cpus=7 keepsyms=1 -noprogress rd=ufsroot0 ufsrw=1
rootrw=0 wdt=-1 wdt_test=no_user_checkin unentitled_ios_sim_launch=1
launchd_unsecure_cache=1 sweettrustall=1 sweetkeys=0 sweetbattery=0
sweetcpufreq=0 sweetchg=0 sweethw=0 sweettouch=0 citrustouchprobe=10
citrustouchdelay=5 sweetfb_stayon=1 sweetfb_native=1 sweetfb_directcons=1
sweetwdt=0 sweetpanel=0 sweetirqwr=0 sweetusb=2 sweetusbspin=0 sweetusbcmd=1
sweetlog=1 sweetptimer=0 sweetptrecord=0 sweetvrecord=0 sweetufsclk=1
wfe_mode=0 gpu=0 citrusgpuprobe=0 citrusgl=0`

`sweettouch=0` is deliberate: on 4K the `sweettouch` driver is the SE2/I2C
path, which needs ABL-loaded firmware. The working bring-up is the probe
harness in mode 10 (bit-bang ROM download, then reports and HID), so keep
`citrustouchprobe=10 citrustouchdelay=5`.

## Open items

- `sweettrustall=1` is still on the command line. Processes now carry
  `CS_PLATFORM_BINARY` themselves, so the flag should be droppable; the earlier
  no-trustall test predates the fix. Not yet re-tested.
- Mode 10 is a probe harness, not a driver: fold it into
  `sweet_touch_init()` as the default path when `sweettouch=1` is set.
- GPU/compositor on 4K (`out/citrus-8core/firmware-relink`) is untouched since
  the userspace wall fell; it has never been booted with a working SpringBoard.
