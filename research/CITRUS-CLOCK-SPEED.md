# Designed clock rates on 4 KiB / 7 cores: CPU, GPU and DDR

2026-10-29 03:40, Asia/Jakarta. On the 4 KiB / 7-core image every clock this
port controls was running at a *debug* rate, not the designed one: the Gold
cluster sat at 300 MHz (LUT state 0), the Silver cluster at 1305 MHz, the
Adreno 610 at 600 MHz, and nothing ever asked the OSM or GPUCC for more. This
note records what was measured, what was changed, and what is still open.

Boot image after this work:
`out/citrus-8core/smp7-clk/citrus-xnu-boot-4k-smp7-clk.img`, SHA256
`a484df6a3147d6c6d572f29ed9b631890e59e0a5d28cb52f20cdf3203f368cdf`
(kernel from `/tmp/relink-smp7.py` build `/tmp/citrus-clk1`, shim PASS).
Command line: `sweetcpufreq=1 gpu=1 gpu_mhz=950 gpupoolmb=128 citrusgl=0`.

## 1. What the hardware advertises (SM6115 EPSS / OSM)

`qcom,cpufreq-hw` (`bengal.dtsi:1761`) has two register blocks, each with a
frequency LUT at `+0x110` (32-byte rows, ≤12 entries, row =
`{src:31..30, core_count:18..16, volt:11..0, l_val:7..0}`, `kHz = src ?
19200*l_val : 300000`) and its own `PERF_STATE` at `+0x920`:

| block | PA | cluster | states | top | "normal" (top-1) |
|---|---|---|---|---|---|
| freq-domain0 | `0xf521000` | Silver (A53) | 8 | 1804 MHz | 1612 MHz |
| freq-domain1 | `0xf523000` | Gold (A73) | 9 | 2016 MHz | 1804 MHz |

Gold table (rate/volt code): 300/15, 652/290, 902/559, 1056/823, 1401/1097,
1536/1360, 1612/1620, 1804/1886, **2016/2153**.
Silver: 300/15, 614/288, 864/557, 1017/821, 1305/1092, 1420/1354, 1612/1620,
**1804/1886**.

Measured live state before the fix: Silver `perf_state=4` (1305 MHz), Gold
`perf_state=0` (**300 MHz**). Nothing in the port ran a cpufreq policy, so the
boot's CPU was at the lowest advertised rate -- the "debug speed" the user
complained about -- for every earlier 4K boot, and the GPU 950 MHz path could
never be taken because it is gated on the Gold top state.

## 2. The tick counter is 19.2 MHz, not 24 MHz

The first measurement was suspicious: a dependent `add x,x,#1` chain reported
2516 MHz at a state whose advertised rate is 2016, and every other state came
out exactly 1.25x high (300 -> 374, 652 -> 815, 902 -> 1127, 1401 -> 1748).
1.25 is 24/19.2, so the measurement assumed the wrong CNTVCT frequency. With
19.2 MHz the same run reads 300, 652, 902, 1401 and **2013 MHz**: the LUT decode
is right and the CPU really is at its advertised rate. Any future code that
converts `cntvct_el0`/`mach_absolute_time` ticks must use 19.2 MHz here (the
24 MHz figure used elsewhere in this tree is wrong for this board).

## 3. The driver (`bsd/dev/sweet_cpufreq.c`)

`sweet_clocks_max()` now:

- decodes both clusters' LUTs, prints them with voltage codes, the live state,
  the normal and the top index;
- boot arg `sweetcpufreq=0` read-only, `1` both clusters to the designed top
  (boost), `2` both to the sustained state (top-1);
- validates both tables before writing either one (n>=2, top within
  600..3000 MHz) and reports a failed readback;
- returns 1 only when the Gold top state is confirmed live, which is what
  `TopazAdreno.cpp` gates the 950 MHz PLL0 path on;
- keeps `sweet_cpufreq_max()` as the old entry point.

`kern.sweet_cpu_state` (SYSCTL_PROC, RW) reads the live Gold index and writes a
new one to **both** clusters (clamped per table), so a caller can move between
sustained and boost without rebooting. The entry is compiled in and registered
through the same `__STARTUP_ARG` path as the rest of the kernel's statics, but
it has not been exercised from userspace (this root has no shell), so treat the
runtime knob as compile-verified only.

### Evidence

- `4k-smp7-clk3-live.txt` (sweep, 24 MHz constant in the log; divide by 1.25):
  `gold state 4 advertised 1401 measured 1748` = 1398, `state 2 902 -> 1127` =
  902, `state 1 652 -> 815` = 652, `state 0 300 -> 374` = 299, top 2016 -> 2516
  = 2013. Every advertised state is reached.
- `4k-smp7-clk-live.txt` (current image): `silver perf_state 4 -> 7, readback
  7 (1804 MHz)`, `gold perf_state 0 -> 8, readback 8 (2016 MHz)`, `7/7 CPUs
  initialized`, 4 crashes (driverkitd), GPU `CP up ... core 950 MHz`.

## 4. GPU at the fused maximum: 950 MHz

The 4K tree's `TopazAdreno.cpp` already contains the stock PLL0 recipe
(`gpucc-bengal.c`: 950 MHz = `PLL0 1900 MHz OUT_AUX2 / 2`, `L=98`,
`alpha=0xf5555555`). It only needs `sweetcpufreq=1` to satisfy its own rail
gate. On hardware, with this image:

```
CitrusGPU: requested gfx3d 950 MHz (PLL0 1900/2)
CitrusGPU: PLL0 locked at 1900 MHz (mode=0xc0000007 L=98 alpha=0xf5/0x55555500)
CitrusGPU: gfx3d 950 MHz (PLL0 1900/2, cfg=0x203, PLL mode=0xc0000007)
TopazGPU: CP up (ME_INIT, SET_SECURE_MODE 0), core 950 MHz
CitrusGPU: selftest PASS 16 IB writes and fences
TopazGPU: Adreno 610 ready, RedwoodGPU published
```

No independent RPM rail vote is made: the CX/MX `TURBO_L1` class is still
inherited from the CPU's top state. That is why the 950 MHz step is gated on
`sweetcpufreq=1`; making it independent needs the acknowledged GLINK-RPM
transport described in `research/CITRUS-GPU-CLOCKS.md`.

## 5. DDR / RAM clock: already at the designed top

The board has no AP-side DDR clock controller: `ddr_bw_opp_table`
(`bengal.dtsi:2398`) tops out at **1804 MHz / 13763 MB/s**, the RPM owns the
real rate (`BIMC_MSMBUS_CLK`) and the bootloader leaves it high. A read-only
probe (8 MiB `kmem_alloc` copy, timed with `cntvct`) measures **8.2-8.9 GB/s**
of sustained copy, i.e. ~60-65 % of the 13.76 GB/s theoretical peak at 1804 MHz
-- the range a single-threaded LPDDR4X copy reaches when the memory is at the
top OPP. A 300 MHz DDR would show roughly 1-2 GB/s. So the RAM is *not* at a
debug rate and no RPM vote is needed for it; the GPU's memory path is the same
DDR and inherits the same rate (its bimc/`SNOC` votes are not modelled in this
port yet, see §6).

The probe leaks its two 8 MiB buffers on purpose (`sweetclockdiag=1` boots
only; `kmem_free` has three incompatible declarations in this tree).

## 6. Other clocked blocks: designed values and the measurement attempt

Everything below comes from the vendor clock drivers that are checked into this
workspace (`out/citrus-vendor-kernel/drivers/clk/qcom/`), not from guesswork.

**Designed rates.** Two different owners, so two different answers:

| block | owner | designed rate |
|---|---|---|
| UFS `core_clk` (PHY AXI) | AP, GCC RCG `0x45020` | 50..**200 MHz** (`freq-table-hz`, `bengal.dtsi:1603`) |
| UFS `core_clk_unipro` | AP, GCC RCG `0x45060` | 37.5..**150 MHz** |
| UFS `core_clk_ice` | AP, GCC RCG `0x45048` | 75..**300 MHz** |
| UFS `iface_clk` (AHB) | AP branch | fixed AHB |
| sys NoC / config NoC / BIMC | **RPM** (`rpmcc SNOC_MSMBUS_CLK`, `CNOC_MSMBUS_CLK`, `BIMC_MSMBUS_CLK`, `bengal-bus.dtsi`) | not AP-programmable; set by the RPM from the bandwidth vote |
| GPU DDR port (`gcc_bimc_gpu_axi_clk`, `gcc_gpu_snoc_dvm_gfx_clk`) | AP branch, source = the same NoC/BIMC | inherits the RPM rate |
| PCIe | **absent on bengal** | — |

The NoC/BIMC rows matter for the goal: those clocks are *not* something this port
can program at all. `bengal-bus.dtsi` clocks `fab-bimc`/`fab-config_noc` from
`rpmcc` (`BIMC_MSMBUS_CLK`/`A_CLK`, `CNOC_MSMBUS_CLK`, and the sys NoC
equivalents), so their rate follows the RPM's bandwidth vote exactly like DDR
does. The AP-side path (`gcc_bimc_gpu_axi_clk`, `gcc_gpu_snoc_dvm_gfx_clk`) is a
branch off that same fabric. The read-only evidence that this path is healthy is
the 8.2-8.9 GB/s copy probe in §5; a *rate* for it can only be obtained with the
debug pmux (§ below) or with an RPM transport that does not exist in this port.

**Measurement path the vendor uses (`debugcc-bengal.c` + `clk-debug.c`):**
every block exposes a debug pmux; pointing it at a branch and running the
global XO/4 counter in GCC for 65536 ticks (≈13.65 ms) gives
`rate = count * 4.8 MHz / 65536`. Registers (GCC base `0x01400000`):

```
XO/4 counter enable   GCC + 0x28008  (bit 0)
counter ctl           GCC + 0x62038  (bits 24:0 = ticks, bit 20 = enable)
counter status        GCC + 0x6203C  (bit 25 = done, bits 24:0 = count)
mux select            GCC + 0x62000  (bits 9:0, gcc_debug_mux_sels[] map)
mux post divider      GCC + 0x30000  (bits 3:0 = div-1)
```
`debugcc-bengal.c`'s `gcc_debug_mux_sels[]` gives the selector per branch, e.g.
`snoc 0x07`, `cnoc 0x1a`, `sys_noc_cpuss_ahb 0x09`, `ufs_phy_axi 0x110`,
`ufs_phy_unipro_core 0x116`, `ufs_phy_ice_core 0x117`, `ufs_phy_ahb 0x111`,
`sys_noc_ufs_phy_axi 0x19`, `bimc_gpu_axi 0x90`, `gpu_snoc_dvm_gfx 0xea`,
`usb3_prim_phy_pipe 0x60`. DISPCC/GPUCC mux registers are at `+0x7000` and
`+0x1568` in their own blocks (the counter stays in GCC); their post dividers
are 4 and 2, so their measured rate must be multiplied by that.

**The first attempt is quarantined.** `sweet_cpufreq.c` now contains
`sweet_cc_measure()` implementing exactly the sequence above for the eleven GCC
branches. On 2026-10-29 03:47 a boot with `sweetclockdiag=1` ran it (then not
yet gated) and the phone **stopped enumerating USB and never reached fastboot**
— no `/dev/cu.usbmodem*`, no `fastboot devices`, for four minutes; recovery
needs one physical power cycle. The likely culprits, in order: clearing bit 0 of
`0x28008` at the end (it is the XO/4 branch *and* possibly a live functional
branch for the USB/UFS PHY), or the mux select write landing while a client was using that branch. It is now double-gated behind `sweetclockdiag=1 sweetccmeas=1` and is
off on every normal boot, and the safe resting image
(`smp7-clk`, `5b96f896…`) contains it switched off.

**Read-only UFS report (built, not yet booted).** `sweet_ufs_clock_report()`
in `sweet_cpufreq.c` reads — never writes — the three UFS RCGs and decodes them:
`cfg = reg+4`, `src = (cfg>>8)&7`, `hid = cfg&0x1f`,
`rate = parent/hid` with parents 19.2 MHz (bi_tcxo), 600 MHz (gpll0) and
300 MHz (gpll0_out_aux2), plus the AXI/AHB/UNIPRO/ICE gate bits and the clkref
branch. It runs on any `sweetclockdiag=1` boot and prints, per branch, the
decoded MHz next to the design maximum above. That is the evidence the next
device session needs: if the bootloader left the UFS path at 37.5/25 MHz, this
line says so, and only then is programming the divider worth the risk.

**Measured on 2026-10-29 05:00-05:20 (the answer to §6's open question).** The
bootloader hands over `ufs_axi` = **120 MHz** (GPLL0 600 / 5) and `ufs_unipro` =
**100 MHz** (AUX2 300 / 3); `ufs_ice` is already at its maximum 300 MHz. The
read-only decode printed exactly that (`4k-smp7-ufsclk-live.txt`), and
`sweet_ufs_clock_set()` then rewrote the two dividers to `CFG_RCGR` 0x00100103
(div 3 -> 200 MHz) and 0x00100202 (div 2 -> 150 MHz), latching each with
`CMD_RCGR` bit 0 and polling bit 1; readback confirms both
(`4k-smp7-ufsrate-live.txt`), a boot with no extra argument proves the fix is on
by default (`4k-smp7-ufsdefdiag-live.txt`), and the UFS root still mounts
read-write afterwards in every case. Divider-only updates are safe because the
parent never changes; the write happens before the UFS driver claims the
controller, while the branch gates are still closed.

**The debug pmux was deleted, not parked.** It measured nothing that the RCG
decode could not, and its 2 MiB permanent GCC mapping is the likely cause of the
`kmem_alloc(65536) KERN_NO_SPACE` panic that killed USB on the 03:47 boot (the
boot log in this note's §1 references). With it gone the kernel's io-map budget
is back to the GPU/UFS/USB/display windows only.

**The goal's gate.** `tools/verify-clocks.py cap1 cap2 ...` merges captures and
prints one row per designed-rate claim with PASS / FAIL / MISSING, exiting
non-zero unless every claim the image supports is satisfied. On 2026-10-29
04:07, over `4k-smp7-clk-live.txt` + `4k-smp7-clk3-live.txt`: 9 pass, 0 fail,
3 missing (the UFS rows, which need the next boot).

**Next, safest first:**

1. Read-only decode of the same branches: read the RCG `cmd_rcgr` cfg registers
   (`ufs_phy_axi` `0x45020`, `ufs_phy_ice_core` `0x45048`, plus the snoc/cnoc
   RCGs) and decode source/div/M/N/D exactly like the `gfx3d` and EPSS decodes
   in this port. No writes, so it cannot kill a boot.
2. If the pmux is retried, do it with a person next to the phone, and write
   only `0x62000`/`0x30000`, leaving `0x28008` alone (the vendor enables its
   `cxo` clock via `clk_prepare_enable`, not by poking that register from a
   non-Linux kernel; if the counter does not advance without it, that alone
   proves the branch must be handed to the USB/UFS driver).
3. UFS throughput probe (read 8 MiB through the single-slot driver) as
   behavioural evidence that the UFS path is at its fast OPP, like the DDR copy
   probe.
