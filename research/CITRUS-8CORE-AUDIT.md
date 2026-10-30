# Citrus eight-core feasibility audit (2026-10-27)

Status: investigation and isolated patch trial only. No bootable 4K image has
been built or tested. The active four-Gold boot and root were not modified.

HakiOS revision 88513176b1e96ecf0b764cd62c6f4e6ac71345e3 starts its
secondaries through PSCI and describes the small cores to its scheduler. Its
README says eight, but loader.c excludes the core running the resident loader;
docs/ru/notes.md explicitly says XNU gets at most seven in that configuration.
This is a different CPU family from Citrus. Citrus already has four Gold
cores running through PSCI; Silver A53-class cores require 4K translations.

## Isolated source trial

`python3 tools/build-citrus-gpu.py --output-dir out/citrus-4k-audit
--firmware-dir devices/citrus-gpu-fw --prepare-only` produced a separate copy
of the current GPU source. Applying Topaz patch 0140 with zero fuzz left two
rejected hunks, retained as `.rej` in that copy:

* SweetSurface: our GPU allocation path differs. The 4K patch requests 16K
  alignment for allocations exposed to user tasks, but the path now passes
  `page_size` and has a separate physically contiguous/GPU pool path. Audit
  alignment, size and mapping of *all* paths before substituting SWEET_UPAGE.
* start.s: our Citrus framebuffer diagnostic writes at 0x5c000000 with 2308
  rows, while the patch assumes other Topaz addresses and dimensions. Preserve
  the Citrus bounds and separately audit 4K early mappings. Do not use the
  rejected patch's framebuffer address blindly.

The trial source is incomplete, not a build input. TOPAZ_4K patch 0141 enables
AMP and changes structure layouts. The existing Citrus build tool links most
objects from a prebuilt 16K archive, and cannot safely produce a 4K/AMP kernel
by recompiling its small list of patched files. A completely clean build is
required, including generated assym.s, IIG outputs and all libraries. Topaz's
build-local.sh specifies Xcode 15.4 and KDK 13.5; this host reports Xcode 27.1
and neither of those expected prerequisites was found. Existing artifact
headers/objects are not proof a compatible full toolchain is available.

Security: 0140's cs_validate_page path returns early for TOPAZ_4K because it
cannot validate a 16K hash unit against a single 4K page. Do not silently ship
this behavior; understand and explicitly assess the impact alongside the
existing port's signing enforcement. A successful boot does not prove code
integrity or memory isolation.

## Remaining engineering gates

1. Supply a reproducible clean 4K toolchain; rebase 0140/0141 and relevant 0142
   4K early-console changes against Citrus sources. Audit every change against
   actual Citrus framebuffer and memory reservations. Build from scratch.
2. Audit the Citrus shim and payload for page assumptions. 16K alignment of
   boot data may be conservative, but is not proof of 4K compatibility. Start
   with one Gold core and serial/USB evidence, no root writes.
3. Reconcile 16K user mappings, shared surfaces, GPU buffers, cache maintenance,
   signing, fixed-size register mappings and early kernel page-table layout.
4. Add two-cluster ADT and GIC redistributor setup; boot other Gold cores before
   any Silver, then Silver one at a time. The initial Silver boot CPU is parked
   in WFI after waking Gold, so it cannot simply be treated as PSCI-off. Design
   and test a safe handoff/release or CPU_OFF protocol before requesting it.
5. Verify all eight unique MPIDRs participate, IPI and timers on each, real
   multi-core workloads, GPU/touch/display and sustained behavior. Compare UI
   responsiveness, temperature and power with the existing baseline.

No flash should be attempted with the partial source trial. Known-good images
and the current compositor root remain unchanged.

## Isolated worktree trial, 2026-10-27

The separate worktree contains a source-only rebased trial at
`kernel/experiments/citrus-4k-unvalidated.patch`. It incorporates upstream
0140 and 0141 against the current GPU source snapshot. The rejected ordinary
surface allocation hunk was reconciled to request `SWEET_UPAGE` alignment;
the rejected stage-0 framebuffer hunk was omitted because Citrus already has
its own 0x5c000000 / row-2308 address. The patch intentionally retains
upstream's 4K `cs_validate_page` early return. **This is a signing-validation
bypass and must not be shipped without a separate decision and audit.**

The checked-in patch is quarantined, incomplete, and not an image. It is not
wired into any build or packaging tool. `python3 tools/check-citrus-4k-patch.py`
verified all 14 patched files reproduce the isolated trial, with zero fuzz;
that is only a source-reproduction test. Source snapshots are under
`out/citrus-8core/base/xnu` and `out/citrus-8core/source/xnu` in the main checkout.
They are ignored output and can be regenerated from the captured baseline.

Further blockers found during rebase:

* Existing Citrus ADT marks Gold as homogeneous cluster-type 0, but 0141
  enables AMP. `machine_routines.c` recognizes numeric character codes `'P'`
  and `'E'`, not cluster-id alone. A separate validated P/E topology is needed;
  even a one-Gold AMP boot must be checked against scheduler assumptions.
* Several GPU/default-render-target and contiguous allocation paths use
  `round_page_64` or 4K physical masks, outside 0140's surface hunk. On a 4K
  kernel, 16K user mappings need separately verified physical/virtual alignment
  and backing extent. The changed ordinary allocation is not a complete audit.
* The stage-0 store is pre-MMU; the later 4K early console remains disabled by
  0140. Upstream 0142 adds 2 MiB block mappings, but was written for a different
  RAM layout. Do not apply its mappings without proving L1/L2 table ownership,
  framebuffer bounds and bootstrap table capacity on Citrus.
* The initial Silver core remains powered on in the shim's WFI loop. PSCI
  CPU_ON cannot be assumed to reclaim it. A tested release/offline handshake
  is needed before an eight-core claim; do not start the other agent's phone
  while developing it.
* `shim/xnu-loader.c` aligns boot data to 16K. That is likely conservative for
  4K but payload layout and the kernel's expected page tables still require
  verification, not a blind change to 4K.

The worktree preflight `python3 tools/check-citrus-4k-prerequisites.py` reports
the reference Xcode 15.4 absent and no supplied KDK. It identifies headers only
when a KDK path is supplied; it does not verify the KDK version. Xcode 27.1
exists but has not been demonstrated compatible. There was about 1.7 GiB free
when this trial was made; a clean build may need more. Existing archive objects
cannot be reused for 4K/AMP. No hardware access or flash was performed.

## GitHub Actions trial

With the user's authorization, created private temporary repository
`ezariago/citrus-xnu-4k-runner-probe`. Runner probe 40518747327 succeeded on
`macos-14-arm64` (macOS 14.8.9, Xcode 15.4 build 15F31d, iig available,
39 GiB free). The runner did not list an installed KDK. GitHub has announced
macos-14 retirement for 2026-11-02; do not depend on long-term availability.

Run 40519040191 is a clean-source experimental compile attempt using the
pinned Topaz and darwin-xnu-build revisions and strict Citrus patch application.
It uploads only the three source patches, a build script and workflow; device
firmware and root images were not uploaded. Stub firmware arrays deliberately
make any output unsuitable for flashing. 4K signature validation and the
other open safety issues above remain unresolved. The workflow downloads the
KDK via the pinned upstream build script. Check the run before claiming build
success; it was dispatched after the runner probe.

Run 40519040191 failed at compile, after successfully fetching and applying
all three Citrus patches; compile flags contained `-DTOPAZ_4K=1`. The first
reported fatal error was `arm/sweet_idle_stats.h` not found in sweet_ufs.c.
The header was added by the Citrus patch but never added to XNU's exported
header list; local incremental builds added the source include directory and
masked the missing build integration. The remote preparation script now adds it
to `osfmk/arm/Makefile`'s `EXPORT_MD_LIST`. Retry 40520276182 was dispatched;
see its result before claiming the fix fully resolves compilation. No device
firmware was sent and no output is safe to flash.

Retry 40520276182 failed before compilation: the new header-export script
used an incorrectly escaped newline and its assertion stopped execution. This
was a build-script bug, not evidence about the kernel. The insertion was
corrected and checked against the local Makefile, and run 40520655613 was
dispatched. Its result is pending.

Run 40520655613 succeeded: the clean macOS 14/Xcode 15.4 build applied all
three Citrus patches, exported sweet_idle_stats.h, compiled with
`-DTOPAZ_4K=1`, and linked an arm64 `kernel.development.sweet`. The local
artifact is `out/ci-run-40520655613/dxb/fakeroot/System/Library/Kernels/kernel.development.sweet`,
SHA256 `236b13cc52ca7ad5654c654e3e696eec0d7a80dc83fc540391f93c656c0610e1`.
`nm` shows AMP scheduler symbols; this is not runtime proof of either cluster.
The kernel contains empty firmware placeholders and the quarantined signing
validation bypass; it is not safe to flash. GitHub artifact retention is three
days; the downloaded local copy is retained in this worktree.

## 4K bring-up sequencing and shim test

The first green build had TOPAZ_4K and AMP coupled, but the existing Citrus
ADT describes the Gold cluster as homogeneous. The experimental patch now
separates them: `TOPAZ_4K=1` retains 4K pages with the existing SMP scheduler;
`CITRUS_4K_AMP=1` opts into two-cluster structures and scheduler only when
TOPAZ_4K is set. The mixed-cluster ADT and Silver handoff remain unimplemented,
so do not use that option for a phone boot. The Gold-only build was dispatched
as GitHub run 40522455022; its result must be checked independently.

Separately, the prior green AMP-linked 4K kernel was packaged with a synthetic
one-Gold ADT (no UFS, display, WLAN or product node) solely for host testing.
`tools/build-diagnostic.py` constructed a local test image; the existing shim
was run under Unicorn 2.1.4 with synthetic MMIO and CPU state. It reached the
kernel entry with expected boot arguments, and a strengthened loader test
compared every copied segment, all zero-filled tails and the ADT byte for byte.
The emulator stops at the entry and does not execute XNU or validate actual
ARM translation, GIC/PSCI hardware, scheduler or userspace. The tested kernel
is the previous AMP build, not the pending Gold-only build; neither the payload
nor the generated test image is safe to flash (empty firmware, signature
validation bypass and synthetic ADT). The existing shim retains 16K alignment
for boot data; this host test shows its arithmetic accepts the 4K Mach-O but
cannot establish translation-table correctness on hardware.

Gold-only 4K/SMP run 40522455022 succeeded and linked the ARM64 kernel at
`out/ci-run-40522455022/dxb/fakeroot/System/Library/Kernels/kernel.development.sweet`,
SHA256 `365cca02b8b799e26cd57f1305d618fcc0703de7ae10583c0562d9dcbc256b95`.
Its symbol table contains the SMP scheduler dispatches and no
`sched_amp_dispatch`, consistent with the explicit AMP gate. The local
preprocessor regression `python3 tools/test-citrus-4k-config.py` verifies
baseline 16K, 4K/SMP and explicit 4K/AMP gates.

The Gold-only kernel was then packaged with the same synthetic one-Gold ADT
and tested through the shim emulator; complete segment, zero-tail, ADT and boot
argument comparisons passed, stopping at the entry. This does not execute XNU.
These artifacts retain firmware stubs and the signing-validation bypass; do not
flash them. The generic `out/citrus-diagnostic/citrus-xnu-boot.img` in this
worktree is this unflashable local test, not a replacement for the user's
working boot. No hardware was accessed.

## 4K signature and surface work

The experimental patch now narrows the unconditional `cs_validate_page()`
early return. It follows `cs_validate_hash` blob selection order and leaves
a 4K VM page unvalidated if its selected signature hash unit is larger than
PAGE_SIZE; 4K hash units proceed through the original validation path. This
avoids sending a 4K mapping to a 16K hash operation. Unvalidated does not
necessarily mean execution is rejected: fault and signing policy decides.
This does not validate 16K signatures, assess cs_validate_range, or establish
enforcement. The guard was exercised with ASan/UBSan using
`tools/test-citrus-4k-signing.py`; full XNU behavior remains unverified.

The 4K SweetSurface paths now request 16K physical alignment for scanout and
default render targets and round default and GPU-fallback extents to the 16K
user-page size. Wrapped ranges reject arithmetic overflow. The GPU pool's
16K mask and 16K block rounding were checked in source; that does not prove
mapping correctness or coherence. Surface runtime tests remain necessary.
Patch reproduction and the local signing and configuration tests passed.
Run 40524060453 compiles these changes with firmware stubs; result pending.
No phone access occurred.

Run 40524060453 (commit 15b2690) completed successfully with the first
signature and surface changes. It remains a stub-firmware, unflashable build.

Further source inspection found `vm_page_validate_cs_mapped_chunk()` can call
`cs_validate_range()` with less data than a signature hash unit. The earlier
page-only guard did not protect that caller: `cs_validate_hash()` expects an
aligned full hash unit and may panic or read beyond a partial range. The
experimental patch now shares a guard between page and range validation. It
follows existing first-matching-blob selection, checks alignment and available
length, and rejects shifts incompatible with the 32-bit size calculation.
Unsupported cases are left unvalidated; fault policy still decides access. A
full aligned 16K range can follow the existing hash path, but one 4K page
covered by such a unit remains unvalidated. This is not a complete signing
implementation or proof of policy enforcement.

`tools/test-citrus-4k-signing.py` compiles the exact guard under ASan/UBSan and
checks 4K and 16K windows, partial/misaligned input, blob order, absent metadata
and oversized shifts. Both callers are checked to guard before hashing. The
source-reproduction and config checks pass. The next CI build uses commit
2807f42; runtime behavior remains unverified.

## Offline mixed-cluster topology

Run 40525879879 succeeded for commit 2807f42, the 4K/SMP trial with both
signature-range guards; successful compilation does not establish signing
policy or runtime memory safety.

`tools/mk-citrus-amp-adt.py` converts a verified-format, four-Gold Citrus ADT
to an explicitly experimental four-P plus zero-to-three-E tree. It requires
Gold MPIDRs 0x100..0x103 first and emits Silver MPIDRs 1..3 in order. It
omits Silver 0 because the shim keeps it powered on in WFI. Its inputs cannot
be overwritten and an existing output is rejected. Phandles remain unique.
The clock-frequency properties are inherited placeholders, not measured
Silver frequency or evidence of DVFS. `tools/test-citrus-amp-adt.py` round-trips
all four permitted sizes, validates affinities, labels, logical IDs, states,
cluster-core IDs and unique handles, models the `HAS_CLUSTER`-unset topology
grouping in the current XNU source, and rejects an invalid Gold input and the
unsupported fourth Silver core. It does not execute XNU's topology parser or
prove PSCI, redistributor, timer, scheduler or coherency behavior. The output is
not integrated into image packaging or suitable for flashing.

The original four-core SMP ADT generation remains unchanged. A separate GitHub
compile will opt into `CITRUS_4K_AMP=1`; it uses stub firmware, has no device
ADT, and cannot prove mixed-cluster runtime behavior. Existing open signing
and surface mapping concerns still apply.

## AMP compiled reset-vector test

Run 40527583747 succeeded on commit 166443e. Its kernel was built with
`TOPAZ_4K=1` and `CITRUS_4K_AMP=1`; the linked binary contains
`sched_amp_dispatch`. Downloaded kernel:
`out/ci-run-40527583747/dxb/fakeroot/System/Library/Kernels/kernel.development.sweet`,
SHA256 `986e4febb7ea4a02520f73a396ccb5ea6d7ab0c05fad2548fdea8b8ed1dd570d`.
It has empty firmware stubs and remains unsuitable for flashing.

`tools/test-citrus-reset-affinity.py` loads that actual Mach-O kernel and runs
its compiled `reset_vector` under Unicorn using synthetic CPU records. It
confirms selection of the correct records for Silver 0x001 and Gold 0x101,
Gold 0x102 and Silver 0x003, and confirms unknown 0x007 does not reach the
reset handler. The test stops at `start_cpu` and does not model the PSCI call,
cache visibility, GIC redistributor setup, timers, MMU initialization, XNU
scheduler or real hardware. The source startup path explicitly cleans reset
structures/page tables to PoC, compares full Aff1:Aff0, initializes a per-core
GIC redistributor and waits for a self-SGI, but these do not prove the Silver
cluster works. Silver 0 remains parked; no safe release/offline handshake has
been implemented.

A disassembly search for common ARMv8.1 LSE/RCpc mnemonics in the kernel's
`__text` section returned no matches. This is a limited static check, not a
proof that every executable section or every unsupported instruction was
covered. A data constant in `__hib_text` disassembles to an apparent LSE
instruction, illustrating why indiscriminately scanning all executable-marked
sections yields false positives. No phone access or flash was performed.

## One-Gold, read-only 4K diagnostic package

`tools/package-citrus-4k-probe.py` now packages the successful 4K/SMP CI
kernel from run 40525879879 (SHA256
`f81a51e8c757e4564ea1f4ba4a47a836f2dd97df015014c9a9f12b8c8a1c3b60`)
with a one-Gold ADT, the locally copied D22AP identity, and a fixed boot
profile. The package explicitly uses `gpu=0 citrusgpuprobe=0 citrusgl=0`,
`sweettouch=0 citrustouchprobe=0 sweetkeys=0`, `ufsrw=0 rootrw=0`,
`sweetlog=0 sweetirqwr=0`, and `sweetusb=2` for live console. GPU and touch
firmware are zero-length placeholders; input and GPU are unavailable. The
existing UFS driver explicitly blocks writes unless ufsrw is nonzero, and
rootrw=0 does not remove MNT_RDONLY. Persistent sweetlog is disabled; the
in-memory USB console ring is still present. This is source-level evidence,
not proof the hardware/root stays unchanged under an untested kernel.

Image `out/citrus-8core/gold1-probe/citrus-xnu-boot-4k-gold1-readonly.img`,
SHA256 `d187aa577ca87c813bfa29b5302906098b174953872992975aa93c44cd288372`;
manifest `out/citrus-8core/gold1-probe/manifest.json`. The packager pins kernel
and backup boot template hashes, verifies CPU/ADT/RAM/cmdline and all kernel
segments, checks non-kernel boot components, and runs the Unicorn shim test
through the kernel entry. Kernel execution, 4K translation, signing policy,
UFS, read-only behavior, and the actual screen/USB are not hardware-tested.
A 4K page covered by a 16K signature remains unvalidated. Expect a diagnostic
rather than a usable system, and do not replace gpu-pool2 without a separately
prepared and hash-verified rollback and coordination with the other agent.
No phone access or flashing was performed.

For a usable build with real input/GPU firmware, firmware must stay local. A
new CI build is being prepared to return the generated 4K build headers and
source tree (firmware placeholders only), in addition to its archive and
kernel. This is intended to permit local replacement of firmware-containing
objects and relinking; compatibility of local Xcode 27 with those generated
4K headers and object ABI still requires actual compile/link tests. No device
firmware or root image is uploaded.

## 2026-10-28: latest CI run, hardware boot, and local firmware relink

The artifacts are consolidated in the main checkout under `out/citrus-8core/`
so the existing boot/root images are untouched; deleting that directory rolls
back the generated 4K output. The tools are the additive, uniquely named
`tools/*citrus-4k*`, `tools/*citrus-amp*` and
`tools/relink-citrus-4k-firmware.py`.

Run 40531392449 (commit `7e84cd1c0d6e5e995a54879d5b15b3b75b4bfc57`, macos-14,
Xcode 15.4) succeeded for `TOPAZ_4K=1` Gold-only, no AMP. Kernel SHA256
`1492c683fac55578e757446395c48fc345c53dd3ed84ca688cb5e4caae1e3fb8`. Unlike
earlier uploads, its diagnostics artifact includes the complete 133 MB
`kernel.development.sweet.a` and the `.exp`/`.alias.exp`/`.linkarguments`, so a
local relink no longer needs a second CI run.

`tools/package-citrus-4k-probe.py` was pointed at that run and rebuilt the
one-Gold read-only image, SHA256
`d9c03de33618f1c3fd9979c6a677bab393cc402d7b6384fa49cdc4b74317373b`; the
Unicorn shim segment/boot-arg test passed before flashing. On hardware the
screen showed:

```
OSLog stream configured: stream: 8192 bytes, cache: 2112 bytes
OSLog stream verification: 0
standard timeslicing quantum is 10000 us
standard background quantum is 2500us
```

then stopped. No CDC-ACM `/dev/cu.usbmodem*`, ADB or fastboot appeared within
about 2.5 minutes. This is the first hardware evidence that the 4K kernel
reaches XNU OSLog and scheduler initialization. It is not proof of root, USB,
interrupts or userspace. The user reset with Power+Volume Down; the
`gpu-poolarena1` rollback (`c0056a8f...`) was flashed in fastboot and the user
confirmed a normal boot. The root image was not modified.

The boot had `sweetlog=0 ufsrw=0`, so `sweet_log_start()` skipped both the
console ring and the 1 Hz heartbeat; the screen tail is the only trace. The
next diagnostic (approved, not yet run) uses `ufsrw=1 rootrw=0 sweetlog=1` so
the recorder writes its reserved 4 MiB + 4 KiB tail of `userdata` while HFS
stays read-only, then pulls with `tools/pull-sweetlog.sh`. If that recorder
never starts, the UFS/root handoff is the blocker and the next build needs
earlier screen/USB instrumentation; Gold SMP and Silver remain off the table
until one-Gold produces a console or recorder trace.

Local firmware relink is reproducible. `tools/relink-citrus-4k-firmware.py`
compiles `TopazAdrenoFw.cpp` and `sweet_touch.c` against the CI-generated 4K
headers with local Xcode 27, replaces the two stub members in the CI archive,
and links with local `libclang_rt.cc_kext.a`, `firehose_buffer.o` and
`-Wl,-read_only_relocs,suppress`. The resulting kernel is
`out/citrus-8core/firmware-relink/kernel.development.sweet.fw`, SHA256
`9b1123f1bdfa8396e40bafc1042d838520b6a93cb8ba9c1ed0399e6dee3a7cbc`. The tool
parses the linked Mach-O and verifies each blob (local `ar`/ld ordering makes
the link hash vary between rebuilds; use the manifest's per-run hash): zap MDT 6860 B
`6577effd...`, zap B02 2096 B `84c65799...`, SQE 32304 B `a0e1b583...`, FT8719
64336 B `46fdd7c9...`. Caveat: local ld 27 omits `__LINKINFO`/`__CTF` and
merges `__LASTDATA_CONST` into `__LAST`, unlike CI's ld 15.4; this kernel is
not shim-tested or booted, and remains diagnostic-only.
