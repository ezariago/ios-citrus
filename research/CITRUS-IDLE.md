# Citrus idle-path investigation, 2026-10-26

XNU reaches the iOS lock screen, but normal boots have repeatedly stopped all
recorded timer activity around 136–155 seconds. No panic or normal UFS error
has been recorded. This is a reliability investigation, not a completed port.

## 2026-10-26 20:35: correction — the idle/WFE conclusion was a small-sample artifact

Do **not** treat `wfe_mode=0` as the fix. Repeated controlled boots after the
root was restored and the phone had been running for hours showed the same stop
with every configuration:

| configuration | result |
| --- | --- |
| `nowfe` (`wfe_mode=0`, heavy diagnostics) | stopped at 136/136/149 s on three boots |
| `hbquiet` (`wfe_mode=0`, no trace/sampler/ISR record, heartbeat only) | stopped at 151 s |
| `nowfi` (`wfe_mode=0 wfi=0`, no WFI) | passed 628 s and one run reached 2187 s, then the next two boots stopped at 161/136 s |
| `nousb` (`sweetusb=0`, minimal diagnostics, `wfe_mode=0`) | stopped at the Apple logo |
| restored `ios16-root-keychain.img` (hash verified) + `nowfe` | stopped at 149 s |
| `jtag=1` (bypasses `cpu_idle` entirely) | stopped at 161 s |

The heartbeat always shows the timer ISR itself stopped (`uptime_s` equals the
last live line, `svc_runs` stops), with 18k–32k free 16 KiB pages and 0–7 UFS
users. Battery was 100%, 4.47 V, 31 °C, charging; no panic block was written.
The stall is therefore an intermittent timer/interrupt-path deadlock outside
`cpu_idle`, triggered by the iOS boot workload (the last activity is usually
SpringBoard/securityd/AKS or a completed UFS command). The earlier two/three
long `nowfe` runs were real but are not a reliability rate; the port is
currently failing most boots at ~136–161 s.

Consequences:

- Do not attribute the stop to WFE, WFI, UFS clocks, USB, diagnostics, or root
  freshness without a fresh controlled result; each has now been excluded in at
  least one configuration.
- `wfi_unmask` (unmask IRQs around WFI) was built and **hung before USB init**;
  taking the timer exception inside `cpu_idle` this early is unsafe. It is
  default-off and should not be used as-is.
- A proper diagnosis needs a non-masked observer: a second CPU that monitors
  and dumps the stuck core, JTAG, or instrumentation that persists from an ISR
  that is not the one that died. Flags cannot fix this.

Built images and hashes: `citrus-xnu-boot-nowfi.img` (87072ddc…b4a77c5),
`citrus-xnu-boot-jtag1.img` (3e5c6108…43e739c), `citrus-xnu-boot-unmask.img`
(b6d8fdd2…14f4600, unsafe), `citrus-xnu-boot-hbquiet.img`
(5a09e987…07556568), `citrus-xnu-boot-nousb.img` (179015a6…448d2c5d).
`tools/pull-sweetlog.sh` now also captures `nowfi2`, `hbquiet`, and
`applelogo-stall1`.

## 2026-10-26 18:30: why `wfe_mode=0` works, and a default-safe fix

### The only live WFE on this port

`cpu_idle()` has three optional WFE users, selected by `wfe_mode` bits 0/1/2:
the proximate-timer loop, a masked I/O-recommendation loop, and an unmasked
I/O-recommendation loop.  The two I/O loops run only when
`ml_cluster_wfe_timeout(cluster)` is non-zero.  That value is set by
`ml_update_cluster_wfe_recommendation()`, whose only caller in this tree is the
closed-source Apple performance controller that this port does not have.
`SweetCPU::start()` also leaves `processor_idle`/`idle_timer` NULL.  Therefore
on Citrus the I/O WFE paths are dead and the **only** WFE that can execute is
the proximate-timer loop in `cpu_idle()`.  Clearing bits 1/2 in `wfe_mode` is
harmless but has no effect; bit 0 is the whole story.

### The proximate-timer condition is degenerate here

`cpu_proximate_timer()` is `!SetIdlePop()`.  With
`cpu_idle_latency == 0`, `SetIdlePop()` returns FALSE exactly when
`rtcPop < mach_absolute_time()`, i.e. when the software timer deadline is
**already in the past**.  `cpu_idle_latency` comes from
`ml_processor_info_t.powergate_latency`; `SweetCPU` zero-initializes that
struct and never fills the field (upstream Apple calls
`gPMGR->initCPUIdle()` instead), so it is 0.  The intended Apple case — a timer
due within the next few microseconds — never happens on this port.  The port
only ever takes the shortcut for an already-expired deadline.

### Why that parks the CPU

The shortcut then calls:

    wfe_to_deadline_or_interrupt(cid, ~0ULL, cdp, false)

which loops issuing `wfe` with IRQs masked, with **no deadline**, waiting for
the timer interrupt to arrive as a WFE wake-up event.  The source itself warns
that ARMv8 permits a PE in WFE with IRQs masked to ignore a pending interrupt
as an event.  The port is single-CPU (`cpus=1`) and there is no other core to
SEV it out.  If the deadline has already been serviced (or its GIC assertion
races the WFE entry), no event is ever posted, and neither the timer ISR nor
any thread can run again: every timer-driven signal stops at once with no
panic, which is exactly the observed 136–155 s stop.

`wfe_mode=0` clears bit 0, so the loop is skipped; `cpu_idle()` falls through
to `Idle_load_context()` and the idle thread re-enables interrupts, letting the
pending/next timer interrupt be taken normally.  This is why the flag is
reliable.  Two secondary questions remain open and are now instrumented:
whether the CPU is asleep in WFE (architected event stream not effective) or
spinning in WFE because the event stream keeps waking it but no interrupt is
ever pending, and why the race only loses once per ~140 s.

### Default-safe kernel fix (built, not yet booted)

The new kernel adds `sweetidle`:

| value | behaviour |
| --- | --- |
| 0 | original Apple loop (control) |
| 1 | wait with WFI, which must wake on a masked pending IRQ |
| 2 | **default**: if `rtcPop` is already past, skip the masked WFE and let the normal idle path retire the interrupt; keep WFE for genuinely future deadlines |

Mode 2 is the exact timer-path behaviour that `wfe_mode=0` produced and that
passed three long runs, but it is now the default and does not disable the
I/O paths or require a boot argument.  `cpu_idle()` also records entry state
(`rtcPop`, `now`, `ISR_EL1`, `CNTV_CTL/TVAL`, `CNTKCTL_EL1`, `DAIF`) and
`SWEET LV` / a new 1 Hz `SWEET IDLE` line publish the counters so a control
stall can show whether the shortcut was taken and whether it ever returned.

Built artifacts (not flashed or hardware-tested at the time of writing):

| image | SHA256 | args |
| --- | --- | --- |
| `citrus-xnu-boot-idlefix.img` | `e146a54a3e64c08e8c3c023f5b189ef9f0a727f1eb97549e6b78bf1e68e9159d` | nowfe set, `wfe_mode` removed, no `sweetidle` (mode 2) |
| `citrus-xnu-boot-idlectl.img` | `f43bcc9f1fe30bcb22a4eef73973a25abd5fa6216248e8aefac656dd9ce8c901` | same + `sweetidle=0` (control) |
| `citrus-xnu-boot-idlefix-wfi.img` | `42eb004d26c4485b7e183ceec6f8abf1a217c6aec492e8e0cb6bbbfb909ae5f0` | same + `sweetidle=1` (WFI) |

Kernel `kernel.development.citrus` SHA256
`52cafafeeeedeaabbf78ce7be09903189650dc9a634b25306cdc7111f276f7a4`.

Expected evidence on the next boots: `SWEET IDLE: mode=2 ... cntkctl=...`,
then 1 Hz `SWEET IDLE ... entries/expired/wfe/wfi/skip lat=0 rec=0x0`.
On the control the last line before the stop should show the shortcut being
taken (`entries > 0`); on the fix `skip` tracks `entries` and `wfe` stays 0.
The decisive follow-up, if needed, is a bounded WFE diagnostic that logs the
stuck entry instead of hanging, and a second CPU/SGI experiment to separate
"asleep in WFE" from "spinning in WFE".

## Controlled results

These three images use the same kernel (`kernel.development.citrus-hcstate7a`),
ADT, and diagnostic arguments. The USB busy probe is off in all three.

| Image | Boot | Idle change | Result |
| --- | --- | --- | --- |
| `noidle` | 43 | `jtag=1` bypasses `cpu_idle()` | Continuous USB through 652 s; heartbeat 651 s; user confirmed lock screen; intentionally reset |
| `idlecontrol` | 44 | Normal idle | USB and heartbeat stopped at 141 s; user confirmed Apple logo |
| `nowfe` | 45 | `wfe_mode=0`; normal WFI retained | Heartbeat 646 s, 129 timer services, 112 diagnostic writes/0 errors; advancing clock confirmed; intentionally reset |
| `nowfe-repeat2` | 46 | Unchanged image, no reflash | Heartbeat611s,122 timer services,103 diagnostic writes/0errors; advancing clock confirmed; intentionally reset. USB was silent throughout |

The source reads `jtag` only in `cpu_machine_idle_init()`, where a nonzero value
sets `idle_enable=FALSE`. The normal-idle control differs from `noidle` only by
removing this argument. Writable iOS state naturally changes between boots, so
repeat trials are still needed.

In `osfmk/arm64/cpu.c`, `cpu_idle()` can enter
`wfe_to_deadline_or_interrupt(..., false)` while interrupts remain masked. Its
proximate-timer case has no finite deadline. The source explicitly notes that an
ARMv8 processor may ignore a masked pending interrupt as a WFE event. The
`wfe_mode=0` argument disables the optional idle WFE loops while leaving the WFI
path enabled. These observations support an idle-path hypothesis; they do not
establish the precise failed instruction or event-stream state.

## Probe limitations and USB changes

The initial `sweetusbspin=1` probe ran at kernel priority 81 and prevented
userland startup on the single CPU. Boot 39 stayed alive for 2246 seconds but
never launched SpringBoard. This is a starvation control, not a successful boot.

Later probes started at 90 or 130 seconds. Priority 4 received too little CPU
time; a timeshare probe still produced sparse ALIVE lines and lost USB service.
No trial showed ALIVE continuing after the last virtual timer tick. Absence of
ALIVE cannot distinguish a halted CPU, a descheduled probe, and a failed USB
channel. `delay()` can sleep or use WFE, so the latest probe uses counter reads
and YIELD instead. Spin mode also has one thread own both USB events and TX.

USB silence can precede the kernel stop: boot 40 stopped streaming at 107 s but
its heartbeat reached 151 s; boot 41 stopped streaming at 53 s but its heartbeat
reached 136 s. Always compare the recovery recorder with the live log.

USB TRBs now occupy separate 64-byte cache lines. Previously EP0 OUT/IN and bulk
RX/TX shared one line, so cache maintenance for a CPU-written descriptor could
write stale state over a neighboring descriptor updated by DMA. This safety
change is retained in both sides of the idle comparison. USB reset handling is
still incomplete and has not been established as the kernel-stop cause.

`CNTV_CTL_EL0` decoding is ENABLE bit 0, IMASK bit 1, ISTATUS bit 2. A healthy
pre-stop sample cannot reveal the timer state at a later stop.

## Artifacts and reproduction

Ignored local evidence is under `out/ios16/logs/`: each trial has a live log,
image manifest, and recovery recorder when pulled. `timer-idle-trials.json`
records outcomes; `*-record-provenance.json` compares raw stall slots with the
previous pull to exclude unchanged records. Stall records contain no boot ID.

The kernel source of truth remains `out/upstream-artifacts/buildtree/xnu`.
Changes are retained in `kernel/patches/0002-sweet-console-display-stall-instrumentation.patch`.
The modified objects compiled and linked, and the regenerated patch passed a
dry run against `/tmp/origbt/xnu`.

The working diagnostic configuration was `wfe_mode=0 sweetusbspin=0`, which
passed two unchanged ten-minute lock-screen trials. The new `sweetidle` default
(mode 2) is intended to replace that argument; see the section at the top.
Keep the physical-timer diagnostic off. No trial yet establishes a long-term
reliability rate or power behavior. The exact WFE/event-stream failure
mechanism (sleep vs livelock) and USB reset recovery remain open.

The exact first successful WFE-disabled diagnostic arguments are retained in
`kernel/citrus-idle-workaround.bootargs`. They retain the heavy recorder, process
sampling, and UFS trace used for comparison; this is not a quiet daily-use
profile. Rebuild the existing kernel and an ADT with UFS/display and 1792 MiB,
then pass the file contents as the `--cmdline` value to `mkpayload.py`. The
resulting test requires the already-installed HFSX root on the phone.

After the second recorder pull, the same image was rebooted again and left at a
user-confirmed lock screen. Its live timer evidence passed 186 s; this final
resume is not counted as a third ten-minute trial. The live capture later reached939s. After the user reported fastboot, recovery
pull `nowfe-resume-*` identified boot47 with heartbeat936s,187 timer services
and161 diagnostic writes/0errors. This does not establish a spontaneous halt.
The phone is now in fastboot for the unflashed touch probe; no capture or AI
automation remains active.
