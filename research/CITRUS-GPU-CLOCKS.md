# Citrus stock GPU clocks and the path beyond 300 MHz

2026-10-27, Asia/Jakarta. **`pll0-950` is running:** GPUCC PLL0 at 1900 MHz with
AUX2 /1 and the GFX3D RCG /2, giving the fused-bin stock maximum 950 MHz. The
previous `gpu-mhz600` boot used only the GPLL0/1 divider. The frozen
`clockprobe1` boot is explained below: its 2 MiB SMEM `ml_io_map` exhausted the
kernel's **8 MiB `io_submap`**, and the touch thread's next 512 KiB map panicked
in `kmem_alloc`. It was a diagnostic bug, not the clock probe's reads.

## pll0-950 (current boot): PLL0 1900 / AUX2 /2

The stock `gpucc-bengal.c` table reaches 950 MHz through
`P_GPU_CC_PLL0_OUT_AUX2 / 2`; it is not another GPLL0 divider. With the Bengal
19.2 MHz reference, 1900/19.2 = `98 + 23/24`, so the alpha PLL uses `L=98` and
a 32-bit alpha of `0xf5555555`. The default PLL register pair stores only the
top 32 alpha bits: `0x0c` gets `0xf5`, `0x08` gets `0x55555500`, matching the
stock `alpha_hi=0x80, alpha=0` encoding for the 1200 MHz default. The other
writes are the stock `config_ctl=0x4001055b`, `test_ctl_u=1`, VCO range 0,
alpha enable, main/aux/aux2 outputs, then bypass/reset/lock/OUTCTRL. AUX2 is
/1 and the GFX3D RCG becomes parent 2 / 2 (`0x1020 = 0x203`).

The driver first parks PLL0 (the gfx3d branch is still off), programs L/alpha,
enables and polls `PLL_LOCK`, verifies the L/alpha readback, then switches the
RCG. It accepts `gpu_mhz=950` only when `sweetcpufreq=1` and
`sweet_cpufreq_max()` confirms the Gold perf state is top (2016 MHz) after the
request; otherwise it uses 600 MHz. That CPU state is the boot's only confirmed
source of the CX/MX `TURBO_L1` class (the GPU OPP for 950 MHz is
`RPMH_REGULATOR_LEVEL_TURBO_L1`). A PLL lock/readback failure falls back to
GPLL0/2 at 300 MHz instead of failing the GPU start. **No independent
GLINK-RPM rail vote was made.**

Hardware evidence (`out/ios16/logs/pll0-950-live.txt`): CPU `perf_state 0 -> 8,
readback 8 (2016 MHz)`; `PLL0 locked at 1900 MHz (mode=0xc0000007 L=98
alpha=0xf5/0x55555500)`; `gfx3d 950 MHz (PLL0 1900/2, cfg=0x203)`; `CP up ...
core 950 MHz`; `selftest PASS 16 IB writes and fences`; FD610 and touch live.
Four CPUs and more than 2300 GL frames, no panic. Matched simple frames
(52 calls/9 draws/32 triangles) went from 5.7-7.7 ms on `gpu-cpu1` to
**1.1-1.2 ms**; a 599-call frame went 16.9 -> 12.0 ms and waits fell from
~5.2 ms to ~0.4-0.7 ms. These are sampled frames, not a controlled FPS test.
The `GPU pool has no 10485760 bytes` and GL 0x505/0x506 messages also appear on
`gpu-cpu1`; they are the pre-existing pool exhaustion.

Image `out/citrus-diagnostic/citrus-xnu-boot-pll0-950.img`, SHA256
`4e3e54fecf8f16a2ce0d44995fbcfcd71a54fcdd19e283c444063b0c7885c638`;
kernel `5df865dd5b296e9f7ce045d987bcf3c9a70c7633571522c82a09f357c9cf916e`.
Host regression `python3 tools/test-citrus-gpu-gfx-clock.py` covers the exact
950 PLL encoding and both failure fallbacks.

## gpu-mhz600 (previous boot)

GPLL0 is 600 MHz on Bengal; the stock GMU entry `F(200 MHz, P_GPLL0_OUT_MAIN, 3)`
fixes that. The GFX3D RCG keeps parent 5 and changes only its divider, so
`0x1020` becomes `0x501` instead of `0x503`. 600 MHz is `VDD_LOW_L1` in
`gpucc-bengal.c`, below the CX level the boot CPU already demands. 745 MHz and
above still need the GPU PLLs and acknowledged RPM rail votes (465 MHz remains
the PLL1/SVS step; 950 MHz is the fused-bin stock maximum but a HIGH_L1 rate).

Boot evidence: 4/4 CPUs, `gfx3d 600 MHz (GPLL0/1, cfg=0x501)`, 16-IB/fence
self-test PASS, FD610 and touch mode10 live; no GL error/fault/panic. If the
self-test ever fails at 600 the driver reverts to GPLL0/2, re-tests and keeps
running at 300. **No consistent speed win is measured yet:** matched-draw
medians (perf3 → 600) are 19.6 → 22.6 ms at 23 draws, 35.2 → 26.9 at 40,
27.6 → 28.5 at 46 and 47.1 → 38.2 at 128; the ~15 ms waits are intermittent in
both logs. The clock is not proven to be the frame-time limiter, and 60 fps is
not implied. Host check: `python3 tools/test-citrus-gpu-gfx-clock.py`.

## Why clockprobe1 froze: io_submap exhaustion

The recorder pulled from recovery contains
`panic: kmem_alloc(..., 524288, 0x100021): failed with 3 @vm_kern.c:178`
(3 = `KERN_NO_SPACE`). `ml_io_map` allocates permanently from `io_submap`,
which is only `IO_MAP_SIZE = 8 MiB` (`osfmk/arm/io_map.c`) and uses
`KMA_NOFAIL`, so a full map panics. The probe's
`ml_io_map(0x46000000, 0x200000)` used 2 MiB; at T=126 the touch thread's first
`ml_io_map(0x01400000, 0x80000)` (512 KiB) failed and panicked. The USB capture
stopped at T=126, but the stall sampler continued to T=141 with console bytes
still growing — the console path died, not the kernel. The probe's fuse/GPUCC
reads and the clock code are not implicated. Any future large probe must use an
`IOMemoryDescriptor` mapping or small windows, or raise `IO_MAP_SIZE` knowingly.

## Result

The phone reports `speed_bin=200 gaming_bin=0`. `adreno_read_speed_bin()` reads
the nvmem cell and `adreno_of_get_pwrlevels()` selects the exact matching bin.
In the captured DT, bin 200 contains **320, 465, 600, 745, 820, 900, 950 MHz**.
Thus 950 MHz is a listed stock maximum for this fuse bin, not an overclock.
This does not mean sustained 950 MHz has been validated under XNU.

Probe also reports GFX CMD=0, CFG=0x503 (GPLL0 / 2), PLL0/1 MODE=0 L=0.
That agrees with the current direct-GPLL0 300 MHz recipe; the dedicated GPU
PLLs have not been configured by this port.

The earlier assumption that RPM voltage requests should use traditional
SMEM-SMD was incomplete. The `rpm-smd` frontend is bound to the RPMsg channel
`rpm_requests`, but this board's backend is **GLINK-RPM**, with a separate
message-RAM TOC/FIFO, not the traditional SMEM channel allocation table.
The probe found SMEM version 12 and no RPM channel in the supported uncached
SMEM tables. That is not evidence that RPM is unavailable. No SMEM/RPM writes
were made. Future transport code must use the actual GLINK backend below.

## Source used

Sparse stock kernel checkout: `out/citrus-vendor-kernel`, Xiaomi branch
`lime-q-oss`, pinned commit `02ca1a919564a9b176a79cce09c40977f833e9ac`.
The source is available locally for subsequent work, not just web snippets.
`tools/audit-citrus-gpu-clocks.py` records file hashes, the DT capture hash,
phandle resolution, all bins, OPP levels and the observed fuse result in
`research/citrus-gpu-clock-audit.json`.

Relevant source paths in that checkout:

- `drivers/gpu/msm/adreno.c`: fuse read and exact bin matching.
- `drivers/clk/qcom/gpucc-bengal.c`: default alpha PLLs, parents, frequency table,
  CX/MX voltage classes and GPU domains/branches.
- `drivers/clk/qcom/clk-alpha-pll.c`: default PLL register layout, rate programming,
  enable/lock/dynamic-update sequence. The inherited Khaje Zonda layout differs.
- `drivers/clk/clk.c`: regulator voting before a prepared clock's rate increase.
- `drivers/clk/qcom/vdd-level-bengal.h`: VDD class to encoded-level mapping.
- `drivers/regulator/rpm-smd-regulator.c`: level votes use the `vlvl` key;
  floor levels use `vfl`; they are not literal microvolts.
- `drivers/rpmsg/rpm-smd.c`: actual vendor RPM frontend, v0/v1 formats, request IDs
  and ACK handling. The captured `qcom,rpm-smd` node has no `reg`, so its stock
  probe defaults to RPM v0 messages. `drivers/soc/qcom/smd-rpm.c` is a separate
  driver and must not be mistaken for this frontend.
- `drivers/rpmsg/qcom_glink_rpm.c` and `qcom_glink_native.c`: actual RPM transport,
  GLINK protocol, version/channel negotiation and intentless transfer support.
- `drivers/soc/qcom/msm_bus/msm_bus_rpm_smd.c`: bus-bandwidth requests.

## Concrete stock dependencies

| GPU rate | Clock source | GPU/CX level | PLL/MX class requirement |
|---|---|---|---|
| 320 MHz | PLL1 AUX, 640 MHz / 2 | LOW_SVS = 64 | MIN_SVS = 48 for PLL1 <= 1 GHz |
| 465 MHz | PLL1 AUX, 930 MHz / 2 | SVS = 128 | MIN_SVS = 48 for PLL1 <= 1 GHz |
| 600 MHz | PLL0 AUX2, 1200 MHz / 2 | SVS_L1 = 192 | NOM = 256 for PLL0 > 1 GHz |
| 950 MHz | PLL0 AUX2, 1900 MHz / 2 | TURBO_L1 = 416 | NOM = 256 for PLL0 > 1 GHz |

The numbers are encoded regulator levels. They are not mV or microvolts.
Other clocks/consumers can impose higher aggregate requirements; do not lower
an existing shared-rail requirement based on this table alone.

Captured GPUCC supplies resolve to:

- CX: PM6125 S3 level regulator, RPM resource **`rwcx`, id 0**.
- MX: PM6125 S5 level regulator, RPM resource **`rwmx`, id 0**.

Captured backend:

- `/soc/rpm-glink`: `qcom,glink-rpm`, GIC SPI 194, mailbox channel 0.
- `/soc/memory@045f0000`: `qcom,rpm-msg-ram`, **0x045f0000 + 0x7000**.
- `/soc/mailbox@0f111000`: `qcom,bengal-apcs-hmss-global`, **0x0f111000 + 0x1000**.
- GLINK-RPM TOC: last 256 bytes of message RAM, magic **0x67727430** (`grt0`).
  Entries identify TX `ap2r` (0x61703272) and RX `r2ap` (0x72326170), with
  offsets/sizes, then tail/head words and FIFO data. Bounds, pointer alignment,
  protocol ownership and negotiated channels must be validated before writing.

## Why 60 fps is not guaranteed by a clock change

60 fps requires a new displayed frame every 16.67 ms; a real 15 fps workload
would need about a fourfold reduction from 66.67 ms. Increasing 300 to 600 MHz
doubles core frequency, not CPU work, cache maintenance, shader compilation,
texture upload or presentation throughput. The perf3 logs include warmed
frames with 30-55 ms of elapsed work and occasional much faster simple frames.
Their sampled/cumulative GL profiles are not end-to-end FPS measurements.

The current `redwood_gpu_worked()` is a **stub returning zero**. Its log text
`GPU worked 0 us` is not measured GPU utilization and cannot justify a clock
bottleneck claim. Separate GPU work from queue/CPU/driver latency in a fixed
warmed workload; keep Control Center/volume as a correctness comparison.

## Next implementation gate

PLL0/950 is now booted, but without an independent rail vote it depends on the
Gold top state's CX/MX level. The next gate is still bounded GLINK-RPM
transport using the actual vendor source: validate TOC/FIFOs, negotiate the
link and `rpm_requests` channel, encode RPM v0 resource votes and match ACK
IDs/errors/timeouts. Preserve voltage requirements of other consumers. After
acknowledged rail support, make 950 MHz independent of the CPU state and add
thermal/bus management for sustained operation; PLL1 and **465 MHz** remain a
separate lower-rate step. Compare the same warmed workload at 300/600/950;
60 fps is still not implied by a clock increase alone.

A high-frequency PLL0 boot image and voltage-control implementation now exist;
the latter is only the CPU-state dependency, not a GLINK-RPM vote. No new
root/userland install is required for this kernel work.
