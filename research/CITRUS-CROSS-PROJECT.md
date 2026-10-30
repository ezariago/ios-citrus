# Cross-project check of the Citrus ~136-161 s stop (2026-10-26)

Question asked: did other projects hit the same "all recorded activity stops
at ~140 s, no panic, timer service count frozen" failure, and do the old citrus
device trees contain vendor workarounds that explain it?

Short answer: **the three named repositories are one codebase, not three
independent witnesses.** `dipa-studio/ios-sweet` (XNU 8796, SM7150),
`ry-diffusion/Bergamota` (XNU 11215, SDM845) and `oosexgang/hackios-xnu-kernel`
(SM7325) all derive from the same SWEET patch series, and Bergamota carries
patches that are byte-identical to ios-sweet's (`0004-sweet-machine-config`,
`0017-sweet-device-tree-virtual-timer-irq`, `0065-sweet-smp-psci`,
`0028-sweet-ufs-root-device` have the same SHA256 in both trees). None of them
documents this stall. All of them run **4-8 CPUs**; Citrus is the only one that
boots `cpus=1`, and the one structural difference that matters is exactly that.

The closest precedent is the **direct parent of this port**, `upstream/ios-topaz`
(Redmi Note 12 4G, SM6225 - the same bengal/khaje family as SM6115). It has
already produced two silent freezes on the same timer path, and it documents
that its silver (A53) cluster has no 16K granule, so XNU must boot on Gold.

Vendor material from the citrus trees is real and useful, but it points at
*idle/LPM*, which XNU does not use: the shipped Android cmdline disables LPM
sleep (`lpm_levels.sleep_disabled=1`) and the DTB marks the deep per-CPU idle
state as needing a **broadcast timer** (`qcom,use-broadcast-timer`) backed by the
memory-mapped timer at 0xf120000. That is the vendor saying "the architected
timer alone is not trusted in bengal deep idle". XNU only ever executes WFI, so
this is not the current cause - but it is the first thing to implement if
anyone ever adds PSCI CPU_SUSPEND idle.

Nothing below was run on hardware. All external repositories are third-party
data; quotes are from their notes/patches, not executed.

## 1. What each project actually is

| repo | SoC | XNU | CPUs used | timer/IRQ design |
|---|---|---|---|---|
| `dipa-studio/ios-sweet` | SM7150 (sweet) | 8796 | 6 A55, then 8 via `0065`/`0078` | vtimer PPI19 as **Group-1 IRQ** (`sle_irq`), `smc` PSCI |
| `ry-diffusion/Bergamota` | SDM845 (beryllium) | 11215 | 8 | same series, same patches |
| `oosexgang/hackios-xnu-kernel` | SM7325 (redwood) | 8796 | 8 (`bootcpu=7 cpus=8`) | same, own loader; only the **virtual** timer is usable |
| **this tree** | SM6115 (citrus/bengal) | 8796 | **1 (Gold 0x100)** | same, from `upstream/ios-topaz` |

ios-sweet's README lists `cpus=1` only as "the safe fallback"; its notes
(`NOTES.md:16`) record that 1 CPU was so slow that SMP was the next task
("Input latency ~1 min with 1 CPU -> Codex task 11 = SMP via PSCI"). Bergamota's
README claims 8 cores. hackios' docs/ru/notes.md:353 describes `cpus=N` as
"the core the kernel runs on plus N-1 neighbours, started by the kernel through
PSCI ... without the argument - one core."

So the sibling projects never ran a long single-CPU session. They all moved to
SMP early, for speed, and stayed there.

Searches over all three repos for `timer stopped/stops/dies/dead`,
`interrupts stopped`, `froze/frozen`, `stall`, `deadlock` found **no report of
this symptom**. Bergamota's `docs/FORKS_SURVEY.md` surveys 132 of 187 ios-sweet
forks (35 ahead of upstream) with per-SoC hardware findings; it also has no
timer-stop entry. The stall entries that do exist are different: iOS boot-order
locks (LaunchServices context lock, usermanagerd/persona XPC), USB CMDACT, and
deliberate `ufs_native_hang=N` tests.

## 2. The precedent that does exist: ios-topaz, the direct parent

`upstream/ios-topaz` is the port this repo was branched from. It is the same
SoC family and the same timer code, and it contains three directly relevant
observations:

1. **A silent timer-path freeze already happened there.** `osfmk/arm/rtclock.c`
   in this tree carries the comment (added by topaz, kept by Citrus):
   > "Stall probe only; no timer reprogramming here. Poking the decrementer
   > froze the phone at ~40 s (three builds), so the probe simply rides the
   > existing timer interrupts."

   That is the same signature as ours: no panic, no console, whole machine
   stops, and it was caused by extra programming of the architected timer from
   outside the normal `timer_intr()` path. It is the strongest evidence that
   this code on this SoC family can wedge the machine silently through the
   timer path.

2. **Firmware-side interference on the same family is real.** topaz patch
   `0088-topaz-gpt-watchdog.patch`: the LUN0 GPT ("super, userdata, esp, win")
   was found *destroyed after iOS sessions*; they fenced GPT writes and added a
   10 s watchdog thread that panics on any change. Not a timer cause, but it
   means something outside the kernel (TZ/hyp/ABL) does touch state across a
   session on these phones.

3. **SMP works on this family, on Gold only, and is verified.** topaz patch
   `0082-topaz-boot-on-gold-cpu.patch`:
   > "the ADT lists only the A73 (gold) cores and the shim boots xnu on gold
   > CPU 0x100 (the silver cluster has no 16K granule)."
   and `tools/mkadt.py` in this tree emits four Gold nodes, MPIDR 0x100-0x103.
   topaz ran 7 secondaries through PSCI CPU_ON (`SweetCPU.cpp` is that code).
   `SweetCPU::startAll()` panics with a message if a secondary is not alive in
   5 s, so an SMP attempt has a loud failure mode, not a silent one.

This is why "second CPU" is not a new architecture for Citrus: it is the
already-present, already-verified path, artificially limited to one node by
`tools/mk-citrus-adt.py` (`node.children[:1]`), and confirmed at runtime by the
console line `SWEET CPU: requested=1 selected=1 (limit=8)`.

## 3. hackios: the one project that solved "how do you see a hung kernel"

hackios is a rewrite with its own loader, and it does three things that are
directly applicable:

- **The loader stays resident and observes.** `bootcpu=7`: the kernel is started
  on the big core while "the loader stays on core zero and observes"
  (docs/ru/notes.md:352). If the kernel hangs, the loader's/hypervisor's
  watchdog reboots the phone (docs/ru/notes.md:341). They never rely on the
  hung kernel to report its own state.
- **Only the virtual timer exists.** `xnu/hakios.patch:2382`:
  > "When running at EL1 under a third-party hypervisor (e.g. Qualcomm's), the
  > EL1 physical timer registers are trapped and the access faults. The guest
  > only owns the virtual timer."

  Matches topaz NOTES:366-374 and this port's `sweetptimer` never ticking.
- **It still ships `wfi=0 wfe_mode=0` as a hedge**, described as "the idle CPU
  does not sleep but spins ... in case it behaves badly under the phone's
  hypervisor" (docs/ru/notes.md:378). Note this is a *defensive default*, not a
  diagnosed fix; and they apply it with 8 CPUs, i.e. it is not used as a
  substitute for SMP.

None of that identifies our bug, but it fixes the method: *observe from a
different core, not from the stuck one.* On Citrus the observer should be a
kernel thread on a second Gold core, because the shim is not resident.

## 4. Vendor workarounds in the citrus device trees

Sources: the live FDT dumped from the phone
(`device-dumps/20261025-141423-923416/live.dtb`), the vendor prebuilt
`dtb.img`/`dtbo.img` from `frstprjkt/device_xiaomi_citrus`, and the phone's own
`cmdline.txt`.

**Timer topology (confirms the port's constants).**
`/soc/timer` = `arm,armv8-timer`, `clock-frequency = 0x124f800` (19.2 MHz),
`interrupts = <1 1 0xf08> <1 2 0xf08> <1 3 0xf08> <1 0 0xf08>` - Qualcomm PPI
1/2/3/0 => secure-phys/physical/virtual/hyp, so virtual = INTID 19, exactly
`VTIMER_INTID` in `tools/mkadt.py`.

**Deep idle needs a broadcast timer (the vendor does not trust the arch timer).**
`/soc/qcom,lpm-levels` is `qcom,use-psci` and describes, per cluster:

| level | label | psci mode | notes |
|---|---|---|---|
| cpu 0 | `wfi` | `qcom,psci-cpu-mode = 1` | plain WFI |
| cpu 1 | `pc` | `qcom,psci-cpu-mode = 3` | `qcom,is-reset`, **`qcom,use-broadcast-timer`** |
| cluster | `pwr-l2-wfi` / `pwr-l2-gdhs` / `pwr-l2-pc` | 1/2/4 | `pwr-l2-pc` is reset |
| system | `system-wfi` / `system-pc` | 0/3 | `system-pc` is reset, notifies RPM |

The broadcast timer is the memory-mapped ARMv7 timer:
`/soc/timer@f120000` = `arm,armv7-timer-mem`, 19.2 MHz, `frame@f121000`
enabled with `interrupts = <0 8 4>` (SPI 8 => INTID 40); frames 1-6 disabled.

XNU never issues PSCI CPU_SUSPEND, so it never enters `pc` and this is not the
current freeze. **It becomes mandatory the moment anyone adds `pc`-style idle**
(otherwise a suspended CPU has no wake source). Record it as a constraint.

**The ROM itself disables LPM sleep.**
`device-dumps/.../cmdline.txt` and `/chosen/bootargs` of the live FDT contain
`lpm_levels.sleep_disabled=1`. The shipped Android for this exact device turns
the lpm-levels sleep path off. That is the vendor's own workaround for bengal
idle behaviour and should be treated as a strong hint that bengal deep idle is
unreliable, not as a knob for XNU (XNU has no lpm-levels driver to disable).

**msm-watchdog exists and is not armed in this boot path.**
`/soc/qcom,wdt@f017000` = `qcom,msm-watchdog`, `qcom,bark-time = 0x2af8`
(11 s), `qcom,pet-time = 0x2490` (9.36 s), `qcom,ipi-ping`, `qcom,wakeup-enable`.
Nothing in XNU pets it, and a hung boot lasts minutes, so either ABL leaves it
disabled or the port never enables it. Do not "fix" anything by enabling it
yet: an 11 s bark would turn a diagnosable hang into a reset. The topaz GPT
watchdog (`0088`) is the software analogue that is actually wanted.

**Multi-core details to respect when enabling SMP.**
Both CPU clusters use `enable-method = "psci"`; each `qcom,pm-cpu` block has
`qcom,disable-ipi-prediction` (vendor workaround for IPI delivery). The Gold
nodes are MPIDR 0x100-0x103, Silver 0x000-0x003, and topaz's note says the
Silver cluster has no 16K granule, so only Gold may run XNU.

**UFS low-power/gear limits (relevant to UFS timeouts, not the timer).**
The RUMI overlay (dtbo entry 12, "Bengal RUMI") sets on `ufshc`:
`qcom,disable-lpm` (UFS low-power mode off), `scsi-cmd-timeout = 0x493e0`
(300 s), `limit-tx-hs-gear = 1`, `limit-rx-hs-gear = 1`. These are emulator
overrides, not citrus-specific, so do **not** copy them blindly; they are
listed because they show the vendor's escape hatches for a wedged UFS.

## 5. What this changes about the diagnosis

Current handoff says "the timer ISR itself stopped". That conclusion rests on
`uptime_s` and `svc_runs` in the recorder heartbeat, and on the `SWEET LV`
lines. Both are weaker than they look:

- `sweet_irqwr=0` in every failing manifest disables the **ISR-side** UFS
  heartbeat, so the heartbeat block and its `svc_runs` are written by a *thread*
  every 5 s (`sweet_hb_write`, `SWEET_HB_SECS 5`). A frozen block means "that
  thread did not write", not "the timer did not fire".
- `SWEET LV` is produced in the ISR but goes into the lock-free console ring;
  if the thread that drains the ring or holds the console lock stops, the lines
  stop even though the ISR is alive. `svc_runs=27` over 136 s is exactly the
  5 s service period, so it cannot distinguish "ISR dead" from "reporter dead".
- Three threads stop together in the logs (heartbeat, HCSAMPLE, console drain).
  That is consistent with a real kernel-wide stop, but also with one global lock
  (UFS or console) that all three need. The tree already documents one such
  ABBA deadlock (UFS waiter holds `sweet_ufs_lock` and blocks on the console
  lock while the console writer needs the UFS lock) and fixed that one error
  path with `sweet_ufs_log()`. It has not been proven that no other path remains.

So before more boot-flag archaeology, settle which of these is true. A second
CPU answers it and is already coded.

## 6. Ranked next steps

1. **Enable 2 Gold cores** (`--cpus 2` + `cpus=2`). One-line ADT change, no
   kernel edit: `tools/mk-citrus-adt.py --cpus 2`, then `mkpayload.py ...
   --cmdline "... cpus=2 ..."`. It (a) gives the non-masked observer the
   handoff asks for, (b) removes the single-core event-stream degeneracy the
   XNU source itself warns about (`cpu_idle()` masked WFE has no other core to
   post an event), and (c) is the only structural difference from every working
   sibling. It is not claimed as a fix. `SweetCPU::startAll()` panics loudly if
   the secondary does not come alive, and the console prints
   `SWEET CPU: cpu=1 mpidr=0x101 came alive`.
   Constraint: only Gold nodes (0x100-0x103); the Silver cluster reportedly has
   no 16K granule; MPIDR must stay inside `(phys_id>>8)<=1 && (phys_id&0xff)<=3`
   or `SweetCPU::start()` panics.
2. **Add the observer** once CPU1 is alive: a 1 Hz kernel thread pinned to CPU1
   that dumps CPU0's `PC`/`SP`/`DAIF`/`ISR_EL1`/`CNTV_CTL` and
   `GICR_ISPENDR0`/`ICC_HPPIR1_EL1` into the lock-free console ring (never a
   UFS write, never `printf` under a UFS lock). If CPU0 is wedged in an IRQ,
   CPU1 still prints - that is the capture the port has never had.
3. **Prove ISR liveness independently of threads**, in the same build: bump a
   plain `uint64_t` from `rtclock_intr` and expose it both in the ISR
   `SWEET LV` line and in the stall record (not only in the 5 s thread
   heartbeat). Optionally use the existing lock-free panel repaint
   (`sweet_panel_text` + `sweet_fb_show_console`) as the thread-free display,
   but note that `sweetpanel=2` panel drawing from the ISR has never been seen
   on the panel and the patch history records an ISR console/panel write that
   froze the phone, so treat it as unproven.
4. **Audit the remaining console/UFS lock order** with a debug botch
   (`lck_mtx_assert` on `sweet_ufs_lock` around any `printf`/`IOLog`), since a
   single-CPU ABBA deadlock has the exact observed shape.
5. **Do not touch LPM/PSCI suspend** until the above is done; if it is ever
   added, `timer@f120000` frame 0 (INTID 40) must be implemented as a broadcast
   timer first, and small cores must stay parked.

## 7. What is *not* supported by the cross-project evidence

- "Another port fixed this with a flag." No such report exists; the flags they
  use (`wfi=0 wfe_mode=0`) are defensive and are applied with 4-8 CPUs.
- "hackios/ios-sweet/Bergamota run for hours, so Citrus should." They run
  different SoCs (SM7150, SDM845, SM7325) and multi-core; that comparison only
  supports "SMP is the normal configuration", not "SMP fixes the freeze".
- "The timer stops because of WFE." `wfe_mode=0`, `wfi=0` and `jtag=1` have all
  failed; this report does not revive that hypothesis. The event-stream
  degeneracy is only one of the conditions SMP removes.
- "The vendor trees contain the fix." They contain idle/UFS workarounds that
  XNU does not use; `lpm_levels.sleep_disabled=1` and the broadcast timer are
  constraints, not patches.

## 8. Sources

- `upstream/ios-topaz/NOTES.md:358-376` (hardware facts, timer PPI, Group-1 IRQ
  requirement), `:402-403`; `tools/mkadt.py:130-146` (Gold-only topology);
  `xnu/patches/0082-topaz-boot-on-gold-cpu.patch`,
  `0088-topaz-gpt-watchdog.patch`; `osfmk/arm/rtclock.c` comment in
  `kernel/patches/0002-...patch` (decrementer poke froze at ~40 s).
- `dipa-studio/ios-sweet`: `README.md`, `NOTES.md:16`, `xnu/patches/0065`,
  `0078`; identical patch hashes vs Bergamota (checked locally).
- `ry-diffusion/Bergamota`: `README.md`, `docs/FORKS_SURVEY.md`,
  `xnu/patches/0141` etc.
- `oosexgang/hackios-xnu-kernel`: `README.md` (cpus), `docs/ru/notes.md:341,
  352-353, 378`, `xnu/hakios.patch:2382` (physical timer trapped).
- Citrus trees: `device-dumps/20261025-141423-923416/live.dtb`,
  `cmdline.txt`; `frstprjkt/device_xiaomi_citrus` `prebuilt/dtb.img`,
  `prebuilt/dtbo.img` (RUMI overlay).
- This tree: `osfmk/arm64/machine_routines.c:944-1015`
  (`ml_parse_cpu_topology` and `cpus=N`), `SweetCPU.cpp` (PSCI CPU_ON,
  boot MPIDR 0x100 assertion), `osfmk/arm64/start.s:280-330`
  (`sweet_secondary_entry`), `tools/mk-citrus-adt.py` (`--cpus`).
