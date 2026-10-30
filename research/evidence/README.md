# Cited hardware captures (archive)

`cited-captures-2026-10-29.tar.xz` holds the captures that `AGENTS.md`,
`AGENTS-RESTORE.md` and `research/*.md` cite by name - the raw console/USB
evidence behind the 2026-10-25..29 findings (shim, 4 KiB/7-core boot, GPU
composition, pool fragmentation, presentation serialization).

- archive SHA256: `61629fcfe14d53199586a018614086a1c824430fc41d4b9db5bf481086365877`
- members: 101
- extracted: 75.5 MB

Extract into the log directory the documents expect:

```sh
mkdir -p out/ios16/logs
tar -xJf research/evidence/cited-captures-2026-10-29.tar.xz -C out/ios16/logs
```

Captures that no document cites (listener duplicates, superseded probe
runs) were not kept. Sizes are the original file sizes.

| capture | bytes |
|---|---|
| `4k-gold2-usbrx-live.txt` | 49451 |
| `4k-smp7-clk-live.txt` | 771916 |
| `4k-smp7-clk3-live.txt` | 311007 |
| `4k-smp7-ent1-live.txt` | 523467 |
| `4k-smp7-ent8-live.txt` | 953777 |
| `4k-smp7-gl-poolfirst-live.txt` | 240457 |
| `4k-smp7-gpu10-live.txt` | 245459 |
| `4k-smp7-gpu11-samples-live.txt` | 438113 |
| `4k-smp7-gpu12-live.txt` | 342457 |
| `4k-smp7-gpu13-live.txt` | 736909 |
| `4k-smp7-gpu14-live.txt` | 492989 |
| `4k-smp7-gpu16-clears.txt` | 409792 |
| `4k-smp7-gpu17-intervals.txt` | 364490 |
| `4k-smp7-gpu20-latch.txt` | 296739 |
| `4k-smp7-gpu21-smmu.txt` | 289504 |
| `4k-smp7-gpu24-walk.txt` | 269505 |
| `4k-smp7-gpu26-smr.txt` | 271613 |
| `4k-smp7-gpu27-clean.txt` | 266891 |
| `4k-smp7-gpu29-restore4.txt` | 1447338 |
| `4k-smp7-gpu29-restore5.txt` | 277244 |
| `4k-smp7-gpu30-vigdump.txt` | 305201 |
| `4k-smp7-gpu31-fb720.txt` | 515541 |
| `4k-smp7-gpu32-fb720pe.txt` | 617682 |
| `4k-smp7-gpu33-scaler.txt` | 332226 |
| `4k-smp7-gpu34-pe.txt` | 3742660 |
| `4k-smp7-gpu35-geom.txt` | 321631 |
| `4k-smp7-gpu36-mode720.txt` | 308686 |
| `4k-smp7-gpu40-split.txt` | 526502 |
| `4k-smp7-gpu9-live.txt` | 258849 |
| `4k-smp7-iopol1-live.txt` | 1267211 |
| `4k-smp7-poolguard-live.txt` | 746563 |
| `4k-smp7-reuse-live.txt` | 629696 |
| `4k-smp7-ufsclk-live.txt` | 284538 |
| `4k-smp7-ufsdefdiag-live.txt` | 260287 |
| `4k-smp7-ufsfinal-live.txt` | 262358 |
| `4k-smp7-ufsrate-live.txt` | 264307 |
| `backlight-probe1-live.txt` | 306742 |
| `fullroot-live.txt` | 4051803 |
| `fullroot-touchprofile-sweetlog.txt` | 715911 |
| `gpu-allocprobe-flash.log` | 259 |
| `gpu-clockprobe1-live.txt` | 167298 |
| `gpu-compositor1-live.txt` | 403415 |
| `gpu-compositor5-live.txt` | 592775 |
| `gpu-compositor6-flash.log` | 345 |
| `gpu-compositor6-live.txt` | 311084 |
| `gpu-compositor6-reader.txt` | 311125 |
| `gpu-compositor6-result.txt` | 549 |
| `gpu-hw2-live.txt` | 414150 |
| `gpu-keys-test-live.txt` | 507303 |
| `gpu-latpool-live.txt` | 30888185 |
| `gpu-onesubmit-live.txt` | 5217195 |
| `gpu-perf1-rollback-flash.log` | 360 |
| `gpu-perf1-rollback-live.txt` | 340616 |
| `gpu-perf3-reuse-rollback-live.txt` | 540683 |
| `gpu-perf3-reuse-rollback-reader.json` | 121 |
| `gpu-performance1-flash.log` | 345 |
| `gpu-performance1-live.txt` | 393106 |
| `gpu-performance1-observation.json` | 8713 |
| `gpu-performance1-reader.txt` | 393147 |
| `gpu-performance1-result.txt` | 21428 |
| `gpu-performance2-flash.log` | 345 |
| `gpu-performance2-live.txt` | 262922 |
| `gpu-performance2-reader.txt` | 262963 |
| `gpu-performance2-result.txt` | 5498 |
| `gpu-performance3-flash.log` | 345 |
| `gpu-performance3-live.txt` | 400450 |
| `gpu-performance3-observation.json` | 8335 |
| `gpu-performance3-reader.txt` | 400491 |
| `gpu-performance3-result.txt` | 20398 |
| `gpu-performance4-flash.log` | 430 |
| `gpu-performance4-live.txt` | 423548 |
| `gpu-performance4-reader.json` | 113 |
| `gpu-performance4b-reader.json` | 114 |
| `gpu-pool2-b0-live.txt` | 1321426 |
| `gpu-pool2-live.txt` | 706072 |
| `gpu-pool2-restore-flash.log` | 259 |
| `gpu-pool2-restore-live.txt` | 360976 |
| `gpu-poolarena1-live.txt` | 1063048 |
| `gpu-smmu1-live.txt` | 254128 |
| `gpu-smmu39-flash.log` | 259 |
| `gpu-smmu39-live.txt` | 613960 |
| `gpu-smmudiag-live.txt` | 418054 |
| `gpu-svc1-live.txt` | 277173 |
| `gpu-triangle4-flash.log` | 1305 |
| `gpu-triangle4-live.txt` | 227877 |
| `gpu-triangle4-result.txt` | 3277 |
| `pll0-950-flash.log` | 268 |
| `pll0-950-live.txt` | 841775 |
| `resprobe1-live.txt` | 361917 |
| `timer-idle-trials.json` | 8403 |
| `touch-cpu4-live.txt` | 477071 |
| `touchprobe1-manifest.json` | 901 |
| `touchprobe10-sweetlog.txt` | 215830 |
| `touchprobe13-sweetlog.txt` | 260972 |
| `touchprobe15-manifest.json` | 1404 |
| `touchprobe2-manifest.json` | 1140 |
| `touchprobe20-live.txt` | 263441 |
| `touchprobe23-live.txt` | 525496 |
| `touchprobe7-manifest.json` | 1256 |
| `touchprobe8-live.txt` | 140861 |
| `ufsclk-live.txt` | 120617 |
