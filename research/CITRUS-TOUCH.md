# Citrus FT8719 touchscreen foundation

Status: controller inventory probe built and linked; **not flashed or tested on
hardware**. No touch events, SPI transfers, firmware uploads, resets, or power
changes have been implemented. The boot partition retains the existing nowfe image. At the usage-stop handoff,
the phone is in fastboot and the probe has not been flashed.

## Confirmed wiring and initial source audit

The captured live device tree identifies SPI SE2 at `0x04a88000` (size `0x4000`),
wrapper `0x04ac0000`, chip select 0, maximum 6 MHz, IRQ GPIO93 falling edge,
active-low reset GPIO103, ten contacts, and coordinates 1080×2340. Earlier Android
observations identify the FT8719; the XNU probe has not read its chip ID.

`devices/citrus.touch.json` retains the selected live nodes and register map.
The SPI pinctrl group contains GPIO6/7/71 and CS0 GPIO80, all qup2/mux1. Individual
MOSI/MISO/clock roles still need confirmation. The FocalTech node's own pinctrl
references instead resolve to legacy IRQ80/reset71 groups, conflicting with its
explicit GPIO93/103 properties. Do not apply those legacy groups blindly.

The source's Bengal TLMM tile layout puts GPIO93 in WEST and GPIO103 in SOUTH:
configuration registers are `0x0055d000` and `0x00967000`, respectively; IO is +4.
The existing Topaz reset86/WEST and AVDD36/EAST sequence is unsuitable.

The live supplies resolve to pm6125_l9 (1.8–2.0 V) and the LCD bias LDO/NCP.
These are not a license to reuse Topaz's regulator or GPIO power sequence.

## Read-only kernel probe

Added to `bsd/dev/sweet_touch.c`, selected before legacy touch initialization:

- `citrustouchprobe=0` (default): no new probe access; keep `sweettouch=0`.
- `citrustouchprobe=1`: report GCC votes, SE2 RCG configuration, and five clock
  branch status registers. Never map or access SE2; never write a register.
- `citrustouchprobe=2`: same inventory, then inspect SE2 firmware/status/FIFO
  parameters only if all five branch CLK_OFF bits are clear. This is an explicit
  second diagnostic, not evidence that every possible bus-access fault is ruled
  out. It does not read the FIFO, clear interrupts, or submit SPI commands.
- `citrustouchdelay=N`: delay after the probe thread starts, default120 seconds,
  maximum600. Invalid modes/delays stop without hardware access. Delay is not
  measured from the initial kernel entry.

GCC is verified at `0x01400000`. Source-derived branch offsets are m-AHB
`0x1f004`, s-AHB `0x1f008`, core `0x1f00c`, core2x `0x1f014`, SE2 `0x1f3a4`.
The shared vote register is `0x7900c`, mask `0x13c0`; the probe does not set it.
RCG command/configuration are `0x1f3a8/+4`.

SE firmware revision at +0x68 has protocol in bits15:8; SPI is1, I2C is3.
The next stage must establish SPI firmware before any transfer. The fetched
Xiaomi `focaltech_touch` driver is I2C (`focaltech,fts_ts`), while the live SPI
node is `focaltech,fts`; it does not establish Citrus SPI framing, CRC, dummy
cycles, or firmware-download requirements.

## Built artifact and validation

Second image (2026-10-26 22:2x, current base): `citrus-xnu-boot-touchprobe2.img`
on the smp4 `cpus=2` base with the bounded `directPresent()` kernel, plus
`citrustouchprobe=1 citrustouchdelay=120`. SHA256
`19266aa901842b530e49066fcbc8eaa1e040a2d91bcea7c7cee4aa105ee830ad`,
manifest `out/ios16/logs/touchprobe2-manifest.json`. Not flashed yet. It is
preferred over touchprobe1 (which still uses the old single-CPU `nowfe` profile).

### First live probe result (touchprobe2, 2026-10-26 22:2x)

Booted successfully; at T~150 s the mode-1 probe printed:

```
GCC vote=0x4be0 se2_rcg=0x80000000 cfg=0x100000
clock m-ahb  value=0        halted=0
clock s-ahb  value=0x8      halted=0
clock core   value=0x4220   halted=0
clock core2x value=0x4220   halted=0
clock se2    value=0x80004220 halted=1
SE2 untouched (a required clock is halted); no clock/pin/power writes
```

Interpretation: the QUP0 wrapper and the m/s AHB and core branches are already
running; only `gcc_qupv3_wrap0_s2_clk` is gated. The vendor `gcc-bengal.c`
(commit in `touch-source-manifest.json`) defines that branch as
`halt_reg 0x1f3a4`, `enable_reg 0x7900c`, `enable_mask BIT(12)`,
`halt_check BRANCH_HALT_VOTED`. The live vote `0x4be0` has bit 12 clear, exactly
matching the halt. SE2 was not touched.

The next image, `touchprobe3` (`citrustouchprobe=3`), writes **only** that one
vote bit, polls `0x1f3a4` bit 31 for up to 5 s, and, only if it clears, performs
the mode-2 read-only SE2 inventory (`fw/protocol/sfw/status/hwtx/hwrx`).
No pinmux, reset, regulator, SPI transfer or HID change is included.

### Mode 3 result: SE2 clock opens, SPI firmware confirmed (22:2x)

`touchprobe3` ran and printed:

```
CITRUS TOUCH: SE2 vote 0x4be0 -> 0x5be0
CITRUS TOUCH: SE2 running cbcr=0x4220 rcg=0 cfg=0x100000
CITRUS TOUCH: SE2 fw=0x102 protocol=1 sfw=0x102 status=0 hwtx=0x20102864 hwrx=0x20104800
```

So writing only GCC `0x7900c` bit 12 clears the `gcc_qupv3_wrap0_s2_clk`
halt; the QUP0 SE2 runs and its firmware revision reports protocol **1 (SPI)**.
The SE status is 0 (idle), no transaction was issued, and the RX FIFO was not
consumed. Note `rcg` reads 0 after the branch opens even though it read
`0x80000000` before; the SE clearly has a clock (register reads succeed), so the
RCG field is not the gate here.

Next milestone is pinmux + reset/power + a bounded chip-ID read. The mode-3
write is now a prerequisite step for every touch image and must be repeated
after each boot.

### Mode 4 result: pinmux/reset safe, but the first SPI transfer times out

Mode 4 muxed GPIO6/7/71/80 (`pin_cfg=0xc4`: qup2/mux 1, no pull, 8 mA),
pulsed reset GPIO103 (`cfg=0x1a00`, active low 10 ms then high), and issued one
4-byte full-duplex GENI transfer. Two things happened:

- **First boot:** the kernel reset itself around T=126 s, right after the pin
  config print and before any SPI result. No panic line. The likely cause is the
  `SE_CLK_SEL`/`SER_M_CLK` writes that were in that image; they have been
  removed. The reset was not a panic, so the recorder would not have a panic
  block for it.
- **Second boot:** the same image ran the full sequence and stayed alive at the
  lock screen. Result:

```
SPI pins muxed, reset pulsed, pin_cfg 6=0xc4 7=0xc4 71=0xc4 80=0xc4 reset=0x1a00
SPI timeout irq=0x40000080 status=0 rxcount=1 rx=00 00 00 00
```

So pinmux/reset are not inherently fatal. The transfer did not complete:
`0x40000080` is TX-watermark + bit 7, not DONE and not an error bit; the RX FIFO
had one all-zero word. The key clue is that after the branch vote,
`TOUCH_RCG` (0x1f3a8) reads **0** even though it read `0x80000000` before the
vote. Register access still works (AHB), but with ROOT_EN clear the GENI
sequencer has no serial clock, which explains "no DONE" and all-zero RX.

Mode 6 re-asserts `0x1f3a8` bit 31 (ROOT_EN) after enabling the branch, preloads
the TX FIFO before `M_CMD0`, and prints `SER_M_CLK`, `CLK_SEL`, `CLK_CTRL_RO`
(0x60) and status as checkpoints. It is built, not flashed. The FT8719 SPI
chip-ID command is still a hypothesis (`0xA3` + dummy, borrowed from the I2C
register map); a valid DONE with non-zero RX is needed before trusting it.

Image: `out/citrus-diagnostic/citrus-xnu-boot-touchprobe1.img`.
SHA256: `4997dd84b6714ebd75ed76c3a3980ea7522070284df91e41d869c24689719eb7`.
Kernel SHA256: `45fd06599bd4705531f6ddd3f221b20ab50fdcc17d9fcff69b48b097fc5f8973`.

Arguments are the tested nowfe diagnostic profile plus
`citrustouchprobe=1 citrustouchdelay=120`. It retains `wfe_mode=0`, disables the
busy USB probe and physical timer, and keeps `sweettouch=0`.
Exact arguments: `out/ios16/logs/touchprobe1-manifest.json`.

`tools/rebuild-kernel.py` now includes `sweet_touch.o`. All objects compiled and
the kernel linked. Patch0002 includes the new source change and passed a dry run
against the extracted pristine buildtree. This verifies the build, not hardware.

## Next steps

1. Boot mode1 when ready for a diagnostic reboot and capture CITRUS TOUCH lines.
   If a required clock is off, stop before accessing SE2. Design a separate
   bounded clock-enable stage using the confirmed Bengal register definitions.
2. Inspect inherited SE2 firmware in mode2 once access prerequisites are met.
   Establish the actual downstream FT8719 SPI transport and power/reset sequence.
3. Implement bounded polled FIFO SPI and chip-ID reads first, then raw contact
   frames. Verify framing, status, length and CRC before publishing contacts.
4. Connect validated reports to `sweet_hid_touch()`. Existing SweetHID native
   geometry is still1080×2400 and must be corrected/configured for1080×2340
   before touch injection. Do not emit guessed contacts into SpringBoard.

Primary references and unmodified source hashes are in
`research/touch-source-manifest.json`: Xiaomi commit
`02ca1a919564a9b176a79cce09c40977f833e9ac`, especially
[gcc-bengal.c](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/02ca1a919564a9b176a79cce09c40977f833e9ac/drivers/clk/qcom/gcc-bengal.c),
[pinctrl-bengal.c](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/02ca1a919564a9b176a79cce09c40977f833e9ac/drivers/pinctrl/qcom/pinctrl-bengal.c),
and [spi-geni-qcom.c](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/02ca1a919564a9b176a79cce09c40977f833e9ac/drivers/spi/spi-geni-qcom.c).

## 2026-10-26 22:5x — source audit corrects three mode-4 conclusions

The mode-4 image and the built-but-never-flashed mode-6 image were audited
against the vendor sources. Three defects were found; the mode-6 image as built
could not have run at all.

1. **Mode 6 never executed its own path.** The branch-vote block was gated on
   `mode == 3 || mode == 4`; mode 6 skipped the vote, `halted` stayed true, and
   the function exited at "SE2 untouched". Modes 5 and 6 were also gated out of
   the pinmux stage, so mode 5 never muxed anything either. Fixed: modes 3/4/6
   vote, mode 5 runs pinmux/reset without any SE2 write or inventory.

2. **`0x1f3a8` bit 31 is `CMD_ROOT_OFF`, not root enable.** Vendor
   `clk-rcg2.c`: `CMD_ROOT_EN = BIT(1)`, `CMD_ROOT_OFF = BIT(31)`,
   `CMD_UPDATE = BIT(0)`. The pre-vote read `0x80000000` means "RCG off"; the
   post-vote read `0` means "RCG running". Mode 6's planned write of bit 31
   would have *disabled* the serial clock. Fixed: never write bit 31; if
   `ROOT_OFF` survives the vote, set `CMD_ROOT_EN` (bit 1) and poll.

3. **The reset GPIO was driven on the wrong bit.** `pinctrl-bengal.c` sets
   `in_bit = 0`, `out_bit = 1`, `oe_bit = 9`. `citrus_gpio()` wrote the output
   value to bit 0 (the read-only input bit), so GPIO103's output latch was
   never changed and the FT8719 reset was likely held low for the whole probe.
   Fixed: write bit 1, preserve bit 0.

Also found: the single 4-byte `0xA3` transfer is not the FTS SPI protocol. The
matching driver is `drivers/input/touchscreen/FT8719/focaltech_spi.c`
(not the I2C `focaltech_touch/` tree fetched earlier). Each package is sent as
two GENI fragments: the package byte alone, a 30 us gap, then the payload while
CS stays asserted (`FRAGMENTATION` param bit 2). Responses are shifted by the
first byte; `READ_CMD = 0xA0` appends a little-endian CRC16/Kermit over the
payload. The boot ID is: write `0x55` + data `0xAA`, wait 12 ms, read
`0x90 0x00 0x00 0x00` into 2 bytes; FT8719 IDs are `0x8719` (normal/ROM),
`0x87A9` (PB), `0x87B9` (BL).

The reworked mode 6 implements the two-fragment transport, a `0x05` status
poll, and the boot-ID read, with all waits bounded and the engine cancelled on
failure. It also prints `SER_M_CLK`/`CLK_SEL` and the reset IO latch.

Image: `out/citrus-diagnostic/citrus-xnu-boot-touchprobe7.img`
SHA256 `bca348414c556d3c591ffe9380776c305d56d2b8e9156b63ae31b285c6f7e891`,
kernel SHA256 `dceca9e39ff9c61b93d1f852e816c4aa372dfaa46949dfdbb04fd9769d6099c8`,
manifest `out/ios16/logs/touchprobe7-manifest.json`. The old touchprobe6 image is
invalid (defect 1) and must not be used.

### touchprobe8 (mode 6 v2) — reset fixed, but the sequencer still rejects commands

`touchprobe8` booted and ran at T=126 s. The new checkpoints are decisive:

```
CITRUS TOUCH: SE2 cmd len=4 frag=0 irq=0 status=0x41
CITRUS TOUCH: SPI loopback ok=0 rx=00 00 00 00
CITRUS TOUCH: SE2 cmd len=1 frag=1 irq=0x82 status=0
CITRUS TOUCH: FTS status try=0 ok=0 status=0xff irq=0x4000080
```

The 4-byte loopback was ignored (`irq=0`, status still `0x41`); the 1-byte
fragment reported `0x82` = `M_CMD_OVERRUN` (bit 1) + `M_RX_IRQ` (bit 7), never
`M_CMD_DONE` (bit 0). That is the signature of submitting a command while the
primary sequencer is still marked active. The bounded cancel/abort did not
clear it.

Missing piece: the vendor `geni_se_io_init()` always ends with
`GENI_FORCE_DEFAULT_REG (0x20) = FORCE_DEFAULT (bit 0)`. The legacy I2C path in
`sweet_touch.c` already wrote `0x20 = 1`, but the Citrus probe omitted it.
`touchprobe9` adds the full vendor sequence (`GENI_CGC_CTRL 0x28 |= 0x7f`,
`SE_DMA_GENERAL_CFG 0xe30 |= 0xf`, `GENI_OUTPUT_CTRL 0x24 = 0x7f`,
`GENI_FORCE_DEFAULT 0x20 = 1`) plus the FIFO-mode IRQ clears, then re-runs the
loopback and FTS boot-ID protocol.

Image: `out/citrus-diagnostic/citrus-xnu-boot-touchprobe9.img`
SHA256 `81a93c94e892c00dac3199d133b5b7382c4a540c1419df3ab6894a9fad345a4e`.
Log: `out/ios16/logs/touchprobe8-live.txt`.

### touchprobe9 — FORCE_DEFAULT alone is not enough; clock plan is the suspect

`touchprobe9` added the vendor `geni_se_io_init()` including
`GENI_FORCE_DEFAULT`. The 4-byte loopback was still ignored (`irq=0`, status
`0x41`) and the 1-byte fragment still raised `0x82` (`M_CMD_OVERRUN` +
`M_RX_IRQ`). The overrun pattern now reads differently: the first command is
*accepted* and sets `M_GENI_CMD_ACTIVE`, but never completes; the next command
then overruns it. That is a missing serial clock, not a stale command.

The RCG is parked at CXO 19.2 MHz (`CFG 0x100000`, from `clk_rcg2_disable`'s
safe config), but the vendor `get_spi_clk_cfg()` would call
`clk_set_rate(se_clk, 48 MHz)` for the DT's 6 MHz maximum and program
`SE_GENI_CLK_SEL = 5`, `GENI_SER_M_CLK_CFG = div 8 | SER_CLK_EN`. The probe had
never programmed either the RCG rate or `SE_GENI_CLK_SEL`; it only changed the
serial divider.

`touchprobe10` tries two plans in one boot:
- A: keep 19.2 MHz, `CLK_SEL=2`, divider 4 (4.8 MHz);
- B: program the RCG to 48 MHz (`CFG 0x2201`, M=4, N=~21, D=~25,
  force-enable around the update), `CLK_SEL=5`, divider 8 (6 MHz).
Each plan runs the loopback; the FTS status/boot-ID read follows either way.

Image: `out/citrus-diagnostic/citrus-xnu-boot-touchprobe10.img`
SHA256 `499d3f255487d3a92840b496bd5e68b952c9ccbcd96fbbf3447c917c6b27cf35`.

### touchprobe10 + recorder — both clock plans, and the real stall

The live USB console had dropped the decisive block, so the UFS recorder was
pulled (`tools/pull-sweetlog.sh touchprobe10` →
`out/ios16/logs/touchprobe10-sweetlog.txt`). Complete sequence:

```
SE2 pre status=0 irq=0
SE2 reset status=0 irq=0 force=0
SE2 cfg word_len=0x4 pack=0x7f8fe/0x7f8fe clk_sel=0x2 ser_m_clk=0x11->0x41 status=0
SE2 cmd len=4 frag=0 irq=0 status=0x41
SPI loopback ok=0 sel=0x2 mclk=0x41 rx=00 00 00 00
RCG 48M cfg=0x100000->0x2201 updated=1 root_off=0
SE2 cmd len=4 frag=0 irq=0x82 status=0
SPI loopback ok=0 sel=0x5 mclk=0x81 rx=00 00 00 00
SPI loopback failed on both clock plans
```

Conclusions:

- The sequencer was **idle before the probe** (`pre status=0`), so the earlier
  "ABL left a command active" reading was wrong; `0x41` is produced by our own
  command starting and never finishing. `GENI_FORCE_DEFAULT` did clear state
  (`reset status=0`), it just was not the blocker.
- The 48 MHz plan is real: `CFG 0x100000 -> 0x2201`, update completed,
  `ROOT_OFF=0`. Both 19.2 MHz/level 2/div 4 and 48 MHz/level 5/div 8 start the
  command and neither reaches DONE, so the RCG rate/DFS index are not it.
- Inherited `SER_M_CLK` was `0x11` (div 1 = 19.2 MHz serial), far over the
  6 MHz limit; both tested plans are within spec.

The next suspect is the RX flow-control watermark. Vendor `geni_se_init()`
writes `SE_GENI_RX_WATERMARK_REG (0x810) = 0` and
`SE_GENI_RX_RFR_WATERMARK_REG (0x814) = tx_fifo_depth - 2 = 14`. Left at 0, a
full-duplex command can transmit but the RX FIFO refuses the first word, so the
command never completes — exactly the observed `status 0x41` with `irq 0`.
`touchprobe11` adds those two writes, `SE_IRQ_EN=0xc`, and switches to the
vendor submission order (`M_CMD0` first, then fill the TX FIFO with `TX_WM=1`).

Image: `out/citrus-diagnostic/citrus-xnu-boot-touchprobe11.img`
SHA256 `3d45071e5e683690c63f24e67ec4f18d423f64bc9454d17e5257d2230fea3310`.

### touchprobe11 — SPI transport is alive (2026-10-26 23:19)

The RX RFR watermark was the blocker. With `0x810=0`, `0x814=14`,
`SE_IRQ_EN=0xc` and the vendor order (`M_CMD0` then FIFO with `TX_WM=1`):

```
SE2 pre status=0 irq=0
SE2 cfg word_len=0x4 pack=0x7f8fe/0x7f8fe clk_sel=0x2 ser_m_clk=0x11->0x41 status=0
SPI loopback ok=1 sel=0x2 mclk=0x41 rx=a5 5a 3c c3
FTS status try=0 ok=1 status=0x8 irq=0x40000080
FTS boot start ok=1
FTS crc calc=0xb230 read=0x808
FTS boot id ok=0 id=0808 (unexpected)
```

So the GENI sequencer, 4.8 MHz serial clock, 4x8 packing and the FTS
two-fragment framing all work; the FT8719 answers. `status=0x08` has
`(status & 0x81) == 0`, i.e. the vendor's `fw_is_running == false` (boot/ROM
mode), which is the expected state for the boot-ID sequence.

The boot-ID reply was `08 08` with a CRC mismatch. Cause found in the vendor
defines: `_FT8719 = 0x8719080D` has `FLAG_IDC_BIT` (bit 11) set, so
`FTS_CHIP_IDC` is true, `is_incell` is true, and the driver uses
`FTS_CMD_READ_ID_LEN_INCELL = 1` (just `0x90`), not the four-byte
`FTS_CMD_READ_ID_LEN = 4` command. The four-byte command misaligned the reply.

`touchprobe12` reads with the one-byte incell command and prints the raw
five-byte data package on CRC failure.

Image: `out/citrus-diagnostic/citrus-xnu-boot-touchprobe12.img`
SHA256 `0559455e21d84cc9e9b307c5544f7f36f13a5ea6a8f921c4b2a28736ed12df07`.

### touchprobe12/13 — the chip answers, but only with its status byte

The recorder (`touchprobe13-sweetlog.txt`) shows both identity paths return the
same constant:

```
SPI loopback ok=1 sel=0x2 mclk=0x41 rx=a5 5a 3c c3
FTS status try=0 ok=1 status=0x8 irq=0x40000080
FTS crc calc=0x83cf read=0x808 raw=08 08 08 08 00 00 00 00
FTS normal id ok=0/0/0/0 id=0800 fw=00 vendor=00
FTS boot start ok=1
FTS crc calc=0xb230 read=0x808 raw=08 08 08 08 08 00 00 00
FTS boot id ok=0 id=0808 (unexpected)
```

So the GENI path is proven (loopback exact, transfers complete, status package
returns a byte), but every register/data read returns `0x08` — the same value
as the status package. That is the FTS "not ready" behaviour: the chip drives
its status byte instead of data, and the CRC never matches. The incell
command-length fix (touchprobe12) was necessary but not sufficient.

`touchprobe14` sweeps `CPHA` 0/1 against serial dividers 4 and 16
(4.8 MHz / 1.2 MHz), four status polls each, printing the resulting status. If
one combination reports `(status & 0x81) == 0x01` or `0x00`, that is the
transport mode to use for the identity and report reads. If all four stay at
`0x08`, the next suspects are chip power (`touch_vddio`, lab/ibb), reset
polarity/timing, or the QUP2 MOSI/MISO signal assignment — not the GENI.

Image: `out/citrus-diagnostic/citrus-xnu-boot-touchprobe14.img`
SHA256 `fd0cbc59b5cd76623a8919f1ac3ea1fac5783639b584d9cc24049e3d854dc5d7`.

### touchprobe14 — mode/clock sweep all return 0x08

```
status sweep cpha=0 mclk=0x41  ok=1 status=0x8
status sweep cpha=0 mclk=0x101 ok=1 status=0x8
status sweep cpha=1 mclk=0x41  ok=1 status=0x8
status sweep cpha=1 mclk=0x101 ok=1 status=0x8
FTS status try=0 ok=1 status=0x8 irq=0x40000080
FTS normal id ok=0/0/0/0 id=0800 fw=00 vendor=00
FTS boot id ok=0 id=0808 (unexpected)
```

SPI mode and clock are not the problem: CPHA 0/1 at 4.8 and 1.2 MHz all give
the same byte, and every data read still returns `0x08` with a CRC mismatch.
The chip is answering, but only with its status byte; it never becomes ready.

Remaining hypotheses, in order:
1. **Touch I/O rail.** `touch_vddio-supply` is one of the `qcom,rpm-smd`
   `pm6125_l*` LDOs, not an RPMh resource; XNU has no RPM (APPS→RPM) driver, so
   the probe never enables it. If the rail is off, the FT8719's I/O buffers are
   unpowered and MISO floats (a fixed 0x08 is plausible). Check the rail with a
   meter, or add an RPM/SPMI enable.
2. **Boot-ROM mode.** If the FT8719 has no internal firmware and expects a
   download on every boot, it stays in ROM mode until `fts_fwupgrade()` uploads
   the image. The vendor probe reads the boot ID and then uploads firmware; the
   `0x08` status would then be "boot ROM busy/waiting". The firmware file is in
   the vendor tree; this is a larger implementation.
3. **QUP2 MOSI/MISO assignment.** The pinctrl group names the pins but not the
   signal roles. If MOSI/MISO are swapped, the chip sees no valid command while
   MISO still carries something. This can be tested by checking the chip's IRQ
   line after reset (a powered, booted chip usually releases INT high) or with a
   scope.

Image: `out/citrus-diagnostic/citrus-xnu-boot-touchprobe14.img`
SHA256 `fd0cbc59b5cd76623a8919f1ac3ea1fac5783639b584d9cc24049e3d854dc5d7`.

## 2026-10-27 — Why 0x08: the FT8719 is in boot ROM; power and wiring are not the problem

### The "hot bottom of the screen" observation, decoded

The phone's lower edge gets hot in fastboot and on the "POCO" splash *before*
MIUI, and it does the same under this port. That is the display subsystem
running in the bootloader's power state, not a touch fault:

- the panel backlight is `qcom,mdss-dsi-bl-pmic-control-type = "bl_ctrl_pwm"`
  with `pwms = <&pm6125_pwm>`
  (`/soc/qcom,mdss_mdp/qcom,mdss_dsi_ft8719_truly_v2_video` in the live DTB).
  Nothing in this port programs the PMIC PWM, so the ABL duty cycle survives,
  exactly like in fastboot/splash, and the bottom edge (backlight LED bar plus
  the chip-on-glass DDIC) dissipates the same power.
- The useful part: the panel is on in the port (lock screen visible), and the
  live DTB makes the touch I/O rail **the same 1.8 V regulator as the panel
  I/O rail**: `/soc/dsi-display-primary vddio-supply = <&pm6125_l9>` and
  `/soc/spi@4a88000/focaltech@0 touch_vddio-supply = <&pm6125_l9>`. The panel
  bias comes from `touch_lab-supply` = `qpnp-lcdb ldo` and `touch_ibb-supply` =
  `qpnp-lcdb ncp`, i.e. the display bias rails. So `pm6125_l9`, LAB and IBB are
  all live whenever the panel is, including under XNU.

That **eliminates hypothesis (a) from the previous section** (touch I/O rail
off because XNU has no RPM driver): the rail is shared with a display that
works, so it is powered. It also matches the heat: the pre-OS panel state is
inherited, not re-initialised.

`l9` is a `qcom,rpm-smd-regulator` (`qcom,set = <3>`,
`regulator-min/max-microvolt` 1.8-2.0 V) with no `regulator-always-on`; it is
enabled by its consumers (display and touch). ABL enables it for the splash and
nothing turns it off, so it stays on across the handoff.

### The pinmux confusion is real but harmless

The live DTB has two contradictory pinctrl sets:

| group | pins | function |
|---|---|---|
| `qupv3_se2_spi_active` | gpio6, gpio7, gpio71 | qup2 |
| `qupv3_se2_spi_cs0_active` | gpio80 | qup2 |
| `pmx_ts_active` → `ts_int_active` | **gpio80** | gpio, pull-up |
| `pmx_ts_active` → `ts_reset_active` | **gpio71** | gpio, pull-up |
| `focaltech,irq-gpio` | **93** (flags 2) | - |
| `focaltech,reset-gpio` | **103** (flags 1) | - |

The `pmx_ts_*` groups are stale (they collide with SPI CLK and CS0); the
vendor driver ignores them in practice because `gpio_request()` +
`gpio_direction_output()` on 103 and the IRQ request on 93 program those pads
through gpiolib, and the SPI runtime resume re-applies its own pinctrl before
each transfer. Our probe muxes 6/7/71/80 itself, so it is correct.

### The actual blocker: no firmware download

The matching driver is `drivers/input/touchscreen/FT8719/` (commit
`02ca1a919564a9b176a79cce09c40977f833e9ac`), not the earlier I2C tree:

- `focaltech_config.h`: `FTS_AUTO_UPGRADE_EN 1`, `FTS_CHIP_IDC` true for
  `_FT8719 = 0x8719080D`, `FTS_POWER_SOURCE_CUST_EN 0`.
- `focaltech_flash.c`: `FTS_FW_REQUEST_SUPPORT 1`, prefix
  `focaltech_ts_fw` + module name `""` → `focaltech_ts_fw.bin`.
  `fts_fwupg_init()` is called at the end of probe and **queues
  `fts_fwupg_work`**, which calls `fts_fw_download()` unconditionally; there is
  no version comparison and no "already running" shortcut.
- Reset/handshake detail: `fts_enter_into_boot()` = hardware reset (1 ms low) + 8 ms,
  write `0x55`, 8 ms, read `0x90` – repeated 30 x 3 times. The probe-time
  `fts_read_bootid()` variant writes `0x55`+`0xAA` first. Both are accepted by
  the ROM.
- `fts_dpram_write_pe()`: `0xAE` command package, then one data package of
  `addr[2:0] + len[1:0] + payload`; `spi_pe=1` for 0x8719, so no separate
  `SET_PRAM_ADDR` command. `drwr_support=0`, so only PRAM is written, and
  `half_length=0`, `app2_offset=64K`.
- `fts_pram_start()`: command `0x08`, then the IC runs the application and all
  reads switch to the "fw running" framing (two length bytes + CRC).
- Every package is preceded by `fts_wait_idle()`, a `0x05` status package.
  Boot mode is idle at `(status & 0x81) == 0x00`, application mode at
  `== 0x01`. Our `0x08` satisfies the boot test, so it is a *boot ROM idle*
  status, and every read returning `0x08` is the ROM answering with its status
  instead of data. The mode-6 comment "after reset the FT8719 runs its factory
  firmware" was wrong: after reset it is in ROM mode and has no application.

Independent proof that this device needs the download: the OrangeFox "juice"
(POCO M3 / citrus) recovery ramdisk ships
`recovery/root/vendor/firmware/focaltech_ts_fw.bin` (131072 bytes, sha256
`8d80bd91df7500be90484ed05b78ebaa28f2f6c71434a3109d7c357fd45b5b87`). The
recovery kernel is the vendor kernel; it only needs that file because the
driver requests it through `request_firmware()` at probe.

The Android input dump confirms the controller and bus we target:
`fts_ts` on `/devices/platform/soc/4a88000.spi/spi_master/spi1/spi1.0`
(`device-dumps/20261025-141423-923416/inputs.txt`). The `novatek@1` node also
exists in the DTB but is not the bound driver.

Firmware header: `code_len` at 0x100 = 0xFB50 (64336) with one's complement
0x04AF at 0x102, so 64336 bytes are written to PRAM from offset 0.
`drwr_support = 0` means the `const_len` (0xD502) DRAM block is not used.

### Implementation: probe mode 7

`bsd/dev/sweet_touch.c` mode 7 (`citrustouchprobe=7`) now:

1. muxes 6/7/71/80 (qup2), GPIO93 input pull-up, GPIO103 reset,
2. runs `GENI_FORCE_DEFAULT` + the proven FIFO/watermark/clock setup,
3. prints the pre-handshake `0x05` status and the INT level,
4. runs the vendor `fts_enter_into_boot()` loop (30 x 3, reset each round,
   `0x55`, 8 ms, `0x90`) and prints each round's id,
5. only if the id is `0x87 0x19/0xA9/0xB9`: writes the embedded 64336-byte
   application to PRAM in 48-byte packets (each with the `0xAE` + addr/len
   framing and a status poll before both packages), 1237 packets bounded,
6. `0x08` start, `fts_wait_idle` in application mode, reads `0xA3` and `0xA6`
   with the application framing and CRC.

The image embeds `devices/citrus-ft8719-fw.bin` through
`tools/embed-touch-fw.py` (generates `bsd/dev/sweet_touch_fw.h`, regenerated by
`tools/rebuild-kernel.py`; deliberately not part of patch 0002).

Image `out/citrus-diagnostic/citrus-xnu-boot-touchprobe15.img`, sha256
`074d4f3750f7b0343ee091722c5680f5de6acbc2bee64d170c4a4087902a5d94`,
kernel `27b13edf6f7e17b2c685dd44644524c86b1f5b554c491d67264b69b22699ccdd`,
manifest `out/ios16/logs/touchprobe15-manifest.json`.

What each outcome means:

- `boot ROM id=8719` then `application idle status=0x1` and `app chip=0x87`:
  the IC is running the application; the next work is the report register
  reads (0xA3/0xA6 already prove app framing) and `sweet_hid_touch()`.
- `boot ROM id=8719` but the application never becomes idle: the ECC upload
  is incomplete (the vendor checks ECC with `0xCC/0xCD` before starting);
  implement `fts_pram_write_ecc`'s check and the `0xCC` sequence.
- `enter-boot try=0..29 id=0808` (or 0xEEEE): the ROM never accepts the
  handshake, so the remaining suspect is the SPI wiring/CS rather than power
  or firmware. Compare with a logic capture on GPIO6/7/71/80 at reset.

### Mode 7 result (2026-10-27 00:0x) — the predicted wiring branch

`touchprobe15` booted and ran mode 7. All 30 `fts_enter_into_boot()` rounds
returned `id=eeee` (`ok=0`), each `0x90` read returned `08 08 08 08` with
`crc=0xb230/0x808`, and the probe stopped with:

```
mode7 boot ROM never returned an FT8719 id; no download
mode7 status=0x8 (neither mode idle)
```

So the outcome is the last branch above: **the ROM never accepts the
handshake**, and no firmware was downloaded. Power is not the differentiator
(the panel shares `pm6125_l9` and is visibly on), and the firmware path is not
reachable until the chip answers. The next discriminator is the SPI wiring/CS:
either the QUP2 pin roles (MOSI/MISO/CLK) are not what the GENI expects, or CS
is not reaching the IC.

Recommended next image: a **bit-banged** read of `0x90`/`0xA3` on GPIO6/7/71/80
after the same reset, with the pins switched to plain GPIO. If bit-banging gets
a real `0x87xx` ID, the problem is the GENI/pin role mapping, not the chip;
if it also returns `0x08`, the chip is not receiving commands at all (CS/MOSI
wiring or reset). This is cheaper and more decisive than a scope if no logic
analyzer is available.

## 2026-10-27 00:40 — the IC answers: pin roles, real boot ID, and firmware download

**Result: the FT8719 is alive, powered and in boot ROM. Its boot ID is `0x8719`
with a valid CRC. The old `0x08` was the GENI RX looking at the wrong pad.**

### Pin roles are crossed relative to the old assumption

`touchprobe17` put GPIO6/7/71/80/93 into plain-input mode and read each one with
no pull, pull-down and pull-up, out of reset and with reset held:

```
out-of-reset    gpio6 none=0 down=0 up=0 DRIVEN   <- the IC drives it
                gpio7 none=0 down=0 up=1
                gpio71 none=0 down=0 up=1
                gpio80 none=0 down=0 up=1
                gpio93 none=1 down=1 up=1 DRIVEN  <- board pull / INT
held-in-reset   gpio6 none=1 down=0 up=1           <- IC stops driving it
```

So GPIO6 is the IC's **MISO**, GPIO7 is its **MOSI**. The DT only lists the
`qup2` group (pins 6, 7, 71, CS0 80); it does not state roles, and the earlier
"GPIO6 = MOSI, GPIO7 = MISO" assumption was wrong.

Bit-banging with the discovered roles (CLK 71, CS 80, ~300 kHz, mode 0) gives:

```
mode8 bit-bang roles mosi=7 miso=6
mode8 status c0 bb: 00 00
mode8 start55 bb: 00 00 ef
mode8 dataAA bb: 00 ef
mode8 read90 bb: 00 ef ef
mode8 read90d bb: 00 87 19 3c bc
```

`87 19` is the FT8719 boot ID (`_FT8719 = 0x8719080D`) and `3c bc` is the
little-endian CRC16/Kermit `0xbc3c` over `87 19` — verified with the vendor's
`crckermit()`. That is a complete, valid boot-ID read.

The GENI path on the same pins still returns `08 08 08 08 08` for the same
packages, and its status reads are `00 00`; this is now understood as GENI
sampling a pad the IC does not drive (or not reaching the IC at all). The
vendor's `qup2` function index is confirmed correct (`PINGROUP` puts `gpio` at
funcs[0] and `qup2` at funcs[1]`, so mux 1 is right), the tile bases are
0x500000/0x900000/0xd00000, and the loopback only proves the SE internals.
Do not spend more boots on GENI until bit-bang has produced a working
touchscreen; then revisit the QUP pin/demux configuration.

### The boot protocol works; the application start does not (yet)

`mode 9` (`touchprobe18`) repeated the vendor path entirely over bit-bang:

```
mode9 start mosi=7 miso=6 cs=80 clk=71 irq93=0x1
mode9 boot status=0
mode9 boot id=8719
mode9 downloading 64336 bytes
mode9 fw 61440/64336
mode9 pram done; starting app
mode9 app idle=0 status=0
mode9 read a3: never idle
```

So 64336 bytes (the `code_len` from the firmware header) were written to PRAM
in 1341 bounded 48-byte `0xAE` packets, and `0x08` was sent, but the IC still
reports boot-mode status `0x00` and never answers application reads. Two
candidates remain: (1) the write did not land correctly (bit-bang timing or
packet granularity), or (2) the ROM refuses to start because its internal ECC
over the written image does not match.

`touchprobe19` (mode 9 v2) adds the vendor's own check before deciding:
`fts_ecc_cal_host()` (16-bit-word CRC, poly 0x8408 over the 64336 bytes) versus
`fts_ecc_cal_tp()` (`0xCC` + addr + len, poll `0xCE` until `eccok_val == 0`,
read `0xCD` two bytes), then a 20 ms settle, `0x08`, and raw status/`0xA3`
reads at +10/50/250 ms with no idle gate, so a started-but-quiet application
is visible.

Image `out/citrus-diagnostic/citrus-xnu-boot-touchprobe19.img`, sha256
`d98d1dbe90b3621acd4db43607a832ac5ca069c69e4a0bfc0df3438e27f994cc`.

### Notes for the next step

- If `ecc ... match=1` and the app still does not start, the start command or
  a missing `0xCE`/`0xCD` commit step is the problem, not the image.
- If `match=0`, the bit-bang write is corrupt: move to the vendor's packet size
  (4092 or 32752 bytes, `FTS_FLASH_PACKET_LENGTH_SPI(_LOW)`) with a static
  buffer, since 48-byte packets are not what the vendor uses.
- For touch reports the bit-bang transport is fast enough (10 contacts at
  ~100 Hz is a few hundred bytes/s at 300 kHz); a GENI fix can wait.

## 2026-10-27 01:00 — the application runs; the last two bugs

1. **Board-level data-pair crossover.** Pull tests find the IC's MISO on
   GPIO6; bit-bang (MOSI 7, MISO 6, CLK 71, CS 80) returns `87 19` + CRC.
2. **ROM command package length.** `focaltech_spi.c`'s `fts_write()` special
   cases `0xAE` (and `0x85`/`0xF2`) to `cmdlen = 6` and `0xCC` to `cmdlen = 7`
   while `fw_is_running == false`. `fts_cmdpkg_wirte()` then puts the address
   and length **in the command package**; only the payload follows in the data
   package. Modes 7/9 v1 sent `C0 01 AE` and put addr/len in the data phase,
   so every ROM write asked for address 0 length 0. That is why the PRAM
   image never landed and the `0x08` start left the IC in boot mode.

With both fixed, `touchprobe20` (mode 9) reports:

```
mode9 boot id=8719
mode9 pram done
mode9 ecc host=0x7d03 tp=0x7d03 ok=1 match=1
mode9 pre-start status=00 00
mode9 starting app
mode9 start+10ms status=01 01
mode9 chip a3 (app) raw: 01 87 30 ff
mode9 app idle=1 status=0x9
mode9 app chip ok=1 id=0x87
mode9 app fw ok=1 ver=0xb
mode9 done irq93=0x1
```

The FT8719 is running firmware 0x0B, status 0x01 (application idle), INT
released, and the vendor ECC agrees with the host ECC over all 64336 PRAM
bytes. Log: `out/ios16/logs/touchprobe20-live.txt`.

Mode 10 adds the report path (vendor `fts_read_touchdata()`): a data-phase-only
transfer (`0x3F` + `FTS_TOUCH_DATA_LEN + 2` dummy bytes, no command package),
`rep[0]` = report header `0x9x`, `rep[1] & 0x0f` = point count, and 6-byte
points at `rep[2 + 6i]` = `X_H/event`, `rep[3 + 6i]` = `X_L`,
`rep[4 + 6i]` = `Y_H/id`, `rep[5 + 6i]` = `Y_L`, `rep[6]` pressure,
`rep[7]` area (our `rep[k]` is the vendor's `buf[k+1]`). Contacts are published
with `sweet_hid_touch()` in panel pixels; SweetHID clamps to 1080x2400 and maps
to the presented display.

Image `out/citrus-diagnostic/citrus-xnu-boot-touchprobe21.img`, sha256
`fcb5f37524a3c53c90ecd69c47ed42791ca0087fd12b8c1e80f0065e4993a8f8`.
