# iOS Citrus bring-up

Target: POCO M3 `citrus`, M2010J19CG, Indonesian region, 4 GB / 64 GB.
Unlocked bootloader, rooted Android 13 AOSP, OrangeFox recovery (version unknown).
User milestones: XNU running → display and iOS UI → touch → GPU and Wi-Fi.

This is an early hardware port. The standalone diagnostic runs on the phone,
hands off from Silver to Gold, and confirms 16K support. A Citrus-adjusted XNU
kernel now builds locally and executes on the phone through scheduler/logging
initialization, then panics. The precise panic is being collected. No iOS root
filesystem or home screen has been installed yet.

## XNU build and first boot

The matching published Topaz artifacts provide both the complete kernel object
archive and generated source/header tree. This permits recompiling selected
sources with the installed Xcode while retaining the original IIG-generated
objects. The logging dependency is rebuilt from Apple libdispatch
`cdb61e93e803d0093635f356753a9a30c09836db`, using Cortex-A53 code generation.
Artifact IDs, commit, ZIP hashes and local provenance are recorded under
`out/upstream-artifacts/artifact-manifest.json`.

Source changes are retained in
`kernel/patches/0001-citrus-diagnostic-console-and-driver-gates.patch`: the early
framebuffer mappings use 0x5c000000 and 2340 rows, and SweetBattery returns
without touching hardware. Rebuild the modified objects and relink with:

```sh
python3 tools/rebuild-kernel.py
python3 tools/mk-citrus-adt.py out/citrus-kernel/citrus.adt
python3 upstream/ios-topaz/tools/mkpayload.py out/citrus-kernel/kernel.development.citrus out/citrus-kernel/citrus.adt out/citrus-kernel/payload.bin --cmdline 'debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 wdt=-1 wdt_test=no_user_checkin sweetbattery=0 sweetcpufreq=0 sweetchg=0 sweethw=0 sweettouch=0'
python3 tools/build-diagnostic.py --template device-dumps/20261025-141423-923416/backups/boot.img --payload out/citrus-kernel/payload.bin
```

The first ADT uses only Gold MPIDR 0x100 and a 1 GiB span at 0x80000000. This
span is in the live RAM bank and has no reservation in the captured /proc/iomem.
UFS, display-service and WLAN driver nodes are omitted. Early console drawing
uses the separate splash reservation. The loader validates payload segments,
range bounds and boot arguments before writes, prepares the boot Gold GIC
redistributor, and jumps to XNU. Synthetic execution verifies copying and the
final entry/arguments; it stubs CPU feature registers and GIC system registers,
so hardware operation is established separately by physical tests.

The kernel scan found zero LSE/RCpc instructions. The initial physical kernel
test shows Firehose initialization, scheduler quantum setup and Mach object
tables, followed by a panic. It is a kernel bring-up result, not a booted iOS
system. No storage driver or user-data modification is part of this test.

## Diagnostic implementation checkpoint

`shim/` now contains an independent, position-independent ARM64 diagnostic
Image. It leaves storage, clocks, voltage, interrupt-controller and DSI
registers alone. It reads candidate MDP source-pipe registers and only draws
if geometry, layout, format and reservation bounds match the supported linear
32-bit surface. It reports entry CPU feature registers, DTB RAM banks and
framebuffer settings, then requests PSCI reset after 60 seconds. Exceptions
have an emergency stack and a nested-exception park path. Reset is best effort;
an unsupported counter access or firmware reset can leave it parked.

Build with the verified backup:

```sh
python3 tools/build-diagnostic.py --template device-dumps/20261025-141423-923416/backups/boot.img
```

Output: `out/citrus-diagnostic/citrus-diagnostic-boot.img`. This is a diagnostic
shim, **not XNU**. It preserves the original ramdisk, DTB and load addresses.
The generated header was checked byte-for-byte against AOSP mkbootimg.
The final ELF has no relocations, and synthetic ARM64 execution at two load
addresses passed framebuffer rendering/bounds and reset-request checks.
An unsupported framebuffer layout was verified to remain untouched. These
checks do not emulate Qualcomm hardware.

LLVM/lld were installed through Homebrew for cross-linking. The synthetic test
uses Unicorn in an isolated environment under `out/test-env`:

```sh
out/test-env/bin/python tools/test-diagnostic.py
```

Actual temporary boot test: transfer succeeded, ABL rejected the boot command
with `unknown command`. Thus no shim code ran on the phone. Normal reboot
returned to Android and ADB reconnected. No flashing was performed. Details
and required XNU changes are in `research/XNU-NEXT.md`.

## Live-device checkpoint (2026-10-25)

Rooted Android connected successfully. Hardware observations are recorded in
`devices/citrus.observed.json`; this is evidence, not a runnable configuration.

- Boot, OrangeFox recovery, and DTBO backed up read-only; each local SHA-256
  matched a separately computed checksum of its source block device. Images
  and checksum manifest are in the ignored local device-dumps directory.
- Boot and recovery both use Android boot header v2 with 4096-byte image pages.
- Live FDT retrieved (543616 bytes) and decoded with `tools/inspect-dtb.py`.
- FocalTech IC `0x8719`, SPI mode 1, up to 6 MHz, SE2 `0x4a88000`, reset GPIO
  103, interrupt GPIO 93, 10 contacts, reported coordinate range 1080×2340.
- Active panel selected by boot arguments: FT8719 Truly v2 video. DRM reports
  1080×2340 at 60 Hz. There is no fb0 sysfs interface on this Android kernel;
  bootloader framebuffer stride and format remain unresolved.
- Android identifies GPU as `Adreno610v1`; DT chip ID `0x06010000`.
- Live RAM banks: `0x40000000 + 0x3dd00000`, `0xc0000000 + 0x80000000`,
  `0x80000000 + 0x40000000` (DT order). Reserved-memory regions must be excluded.
  In particular, Topaz's assumed upper bank at `0x140000000` is not present.
- GIC, splash reservation, and UFS bases match the source-level candidates.

No reboot, flash, partition modification or fastboot boot test was performed.
The collector's binary FDT command quoting was corrected against the real
device. One initial framebuffer query failed because fb0 does not exist;
the DRM query supplies display mode information instead.

## Offline work completed (2026-10-25)

- Cloned `MakrSas/ios-topaz`, branch `topaz`, commit
  `e4772911e116ab4ab6c4ac1f38e6106fefe8b483` into `upstream/ios-topaz`.
- Saved selected Xiaomi `lime-q-oss` device-tree sources and a Citrus recovery
  BoardConfig under `research/sources`. Exact URLs and SHA-256 hashes are in
  `research/source-manifest.json`. These are incomplete source excerpts, not a
  compilable device tree. Preserve each source file's original license.
- Compiled all seven Topaz shim translation units to AArch64 ELF objects using
  this Mac's Apple clang. This verifies compiler compatibility only; it does
  not establish hardware correctness, linkability, or successful boot.
- Added a read-only rooted Android inventory tool for when the phone is charged.

## Findings and constraints

1. Xiaomi explicitly lists POCO M3 under `lime-q-oss` in its kernel repository
   README. This is the initial hardware reference, rather than assuming every
   Topaz setting also applies to Citrus.
2. The Citrus recovery BoardConfig specifies boot header v2, a 4096-byte image
   page size, and an included DTB. Topaz's shim builder emits v4. Our packager
   must be adapted after inspecting a known-working Citrus boot/recovery image.
   The boot-image page size is unrelated to XNU's virtual-memory page size.
3. Xiaomi's Bengal base tree has CPU MPIDRs `0..3` and `0x100..0x103`, PSCI
   using SMC, splash reservation at `0x5c000000` (size `0xf00000`), and UFS
   registers at `0x4804000`. These are promising source-level similarities;
   the live DTB must confirm active overrides and RAM reservations.
4. The published IDP/QRD includes multiple touch possibilities, including
   FocalTech and Novatek SPI on SE2 (`0x4a88000`). It also has I2C alternatives.
   This does not identify this particular phone's controller. Topaz's FT5452
   I2C driver must not be enabled based only on the shared brand.
5. Topaz's console assumes 1080×2400 and a tightly packed 32-bit framebuffer.
   Citrus needs its own dimensions, stride, format, and confirmed splash base.
   Start by retaining the bootloader's display setup, before programming MDP/DSI.
6. Do not reuse Topaz's fixed DDR bank sizes. They must be derived from the
   phone's live memory map with all reserved ranges excluded.
7. Begin with one Gold core and the 16K-page path as a candidate baseline.
   CPU feature registers must confirm granule support. The newer Topaz 4K/AMP
   patches exist, but their presence is not proof they work on Citrus.
8. GPU and Wi-Fi require separate clock, power, firmware, SMMU and transport
   checks after basic boot. Do not copy Topaz's GPU performance settings.

## Host check

Observed: Apple Silicon arm64, macOS 27.0.1, Xcode 27.1 selected,
ADB/Fastboot 37.0.1, approximately 12 GiB free at inspection.
No phone attached. GNU AArch64 GCC, `ld.lld`, and `llvm-objcopy` were not found
in the checked PATH/default Homebrew LLVM location.

The Topaz local XNU script explicitly selects Xcode 15.4 and a 13.5 KDK.
Its comments warn that newer `iig` output does not match xnu-8796's IORPC ABI.
No full kernel build or large SDK/userland download was attempted. Arrange more
disk space and the compatible toolchain, or a suitable build runner, first.
The small shim can already be compiled with the installed clang:

```sh
python3 tools/check-shim.py
```

## Once the phone is available

Boot Android, enable USB debugging, authorize this Mac, then run:

```sh
python3 tools/collect-device.py
```

Root access must be granted to ADB shell. The tool reads selected properties,
CPU/memory information, input devices, framebuffer properties, bus listings,
partition names, kernel logs and the live DTB. It never reboots or flashes.
It has not yet been validated against the physical phone; failures are recorded
in `results.json`. Device dumps are excluded from git and may contain identifiers.

The hardware collection has now been validated on this phone, with DRM replacing
the unavailable fb0 interface and the FDT command corrected for binary output.
Boot, recovery and DTBO backups were completed and independently verified.
The fastboot boot command was tested and rejected by ABL with `unknown command`.
An explicitly authorized boot-partition diagnostic test is in progress; the
user confirmed diagnostic text on the physical display. This establishes shim
execution and bootloader framebuffer access, not XNU boot. Restoration status
is tracked in `out/citrus-diagnostic/flash-test-state.json`.

## References

- https://github.com/MakrSas/ios-topaz/tree/topaz
- https://github.com/oosexgang/hackios-xnu-kernel/blob/main/docs/PORTING.md
- https://github.com/MiCode/Xiaomi_Kernel_OpenSource/tree/lime-q-oss
- https://github.com/geoanto555/android_device_poco-xiaomi_citrus/blob/android-10/BoardConfig.mk
