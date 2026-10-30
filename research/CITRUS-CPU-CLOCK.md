> **Superseded by `research/CITRUS-CLOCK-SPEED.md` (2026-10-29).** This note was
> the first pass: it only programmed the Gold cluster, and any frequency it
> measured with a 24 MHz tick constant is 1.25x too high (the board's time base
> is 19.2 MHz). The current driver handles both clusters; read the newer note.

# Citrus CPU clock: the Gold cluster was running at 300 MHz

2026-10-27 12:50, Asia/Jakarta. Found while investigating UI smoothness after
`gpu-mhz600`.

## Result

`SWEET CPUFREQ: gold LUT 300..2016 MHz in 9 states, perf_state=0 (300 MHz)`
then `perf_state 0 -> 8, readback 8 (2016 MHz)`.

The four Gold cores that XNU runs on were at **300 MHz**, the lowest LUT state,
for every previous boot of this port. Raising them to state 8 (2016 MHz) cut
simple-frame GL time from ~16–30 ms to **0.6–1.0 ms** (`handing on` ~250 us vs
~8–10 ms). The earlier "GPU is slow" profile was largely a 300 MHz CPU.

## Why it was never raised

- `bsd/dev/sweet_cpufreq.c` existed but was only called from
  `SweetBattery::start()`, which begins with `return false;` ("no PMIC, I2C or
  frequency programming"). The call was dead code.
- The baseline cmdline also carried `sweetcpufreq=0`.

## Hardware interface

Bengal `qcom,cpufreq-hw` (`arch/arm64/boot/dts/vendor/qcom/bengal.dtsi`):

- freq-domain0 (Silver A53, Linux CPU0-3): `0xf521000`
- freq-domain1 (Gold, Linux CPU4-7 = the cores XNU boots): `0xf523000`
- LUT at `+0x110`, 32-byte rows, at most 12 entries; PERF_STATE at `+0x920`
- entry decode (msm-4.19 `qcom-cpufreq-hw.c`): `src = (v >> 30) & 3`,
  `lval = v & 0xff`, `kHz = src ? 19200 * lval : 300000`

The Gold LUT decode is `300, 576, 768, 1017, 1209, 1401, 1612, 1804, 2016`
MHz (9 states). State 8 is the top.

## Implementation (this candidate)

- `sweet_cpufreq.c` now always logs the LUT range and live perf state
  (read-only), and writes only with `sweetcpufreq=1`.
- The write is guarded: refuse unless the decoded top is 600–3000 MHz and the
  table has >= 2 entries. Readback is logged. The function returns 1 only when
  `sweetcpufreq=1` and the top state is confirmed live (already selected or
  read back after the write); 0 is a read-only report and -1 is a failed
  table/readback. The GPU 950 MHz path uses that 1 as its rail gate.
- `TopazAdreno.cpp` calls `sweet_cpufreq_max()` from `topaz_adreno_init()`,
  because SweetBattery never reaches its old call.
- `tools/package-citrus-gpu.py --cpu-max` replaces `sweetcpufreq=0` with `=1`;
  `--gpu-mhz 950` refuses to package without it.
- The object is rebuilt by `build-citrus-gpu.py` (added to its rebuild list) and
  `make-citrus-gpu-patch.py` now carries `bsd/dev/sweet_cpufreq.c` (8 files).

Image `out/citrus-diagnostic/citrus-xnu-boot-pll0-950.img`, SHA256
`4e3e54fecf8f16a2ce0d44995fbcfcd71a54fcdd19e283c444063b0c7885c638`;
kernel `5df865dd5b296e9f7ce045d987bcf3c9a70c7633571522c82a09f357c9cf916e`;
capture `out/ios16/logs/pll0-950-live.txt`, flash log `pll0-950-flash.log`.
The CPU-only image `gpu-cpu1` remains
`0f709d853adb953bbe73bb6fdb8f5072d2e80162e08e630d0b7e3992c84fdc99`.

## Caveats

- No DVFS: the cluster stays at 2016 MHz for the whole boot. Expect more heat
  and battery drain until an XNU cpufreq policy exists.
- 2016 MHz is the top advertised LUT state, not an overclock.
- The OSM applies its own rail level for the requested state; no RPM vote was
  needed or made.

## Next

- The CPU is at 2016 MHz for the whole boot; the GPU 950 MHz path now relies on
  that state for CX/MX TURBO_L1 rather than an independent RPM vote. The next
  clock work is acknowledged GLINK-RPM rail support (making 950 MHz independent
  of the CPU state) and sustained-operation/thermal policy.
- Re-measure a warmed UI workload before attributing remaining cost to the GPU.
  The current matched-frame samples are in `CITRUS-GPU-CLOCKS.md`.
