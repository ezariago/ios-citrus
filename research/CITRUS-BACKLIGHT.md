# Citrus backlight investigation

2026-10-27. No device writes, kernel changes, or flashes were made in this investigation.

The captured live DT (`device-dumps/20261025-141423-923416/live-tree.json`) identifies the selected FT8719 Truly v2 panel's backlight as `bl_ctrl_pwm`, referencing phandle `0x23f`: `/soc/qcom,spmi@1c40000/qcom,pm6125@1/qcom,pwms@b300`. This is SPMI SID 1, peripheral `0xb3`, one LPG channel, period 100 µs; the panel's logical brightness range is 1–4095. The panel node also names TLMM GPIO 99 as `platform-bklight-en-gpio`. The physical LPG duty counter is not necessarily 12-bit just because the panel API is 12-bit.

The currently built `SweetFramebuffer.cpp` contains the inherited Topaz `AppleARMBacklight` service, enabled only by `sweetbl=1`, and translates nits to DSI DCS `0x51`. That path was designed for Topaz and is not an implementation of Citrus's PMIC PWM. The inherited display on/off commands are also not sufficient evidence that the Citrus backlight or full panel sleep/wake sequence works. Do not enable the inherited service as a brightness fix. Its original opt-in rationale warns that CoreBrightness may enable digital dimming; behavior with the GPU compositor is not yet measured.

The matching Android vendor kernel is available as git commit `02ca1a919564a9b176a79cce09c40977f833e9ac` in `out/citrus-vendor-kernel`. Its `drivers/pwm/pwm-qti-lpg.c` describes the channel registers: subtype `+0x05`, size/clock `+0x41`, predivider/exponent `+0x42`, duty low/high `+0x44/+0x45`, enable `+0x46`, and value sync `+0x47`. It supports 6- and 9-bit counters and determines the proper encoding using subtype and requested period; it writes the high duty bit, low byte, then sync. A port must respect the actual subtype and retain unrelated bits with masked writes. The stock `drivers/spmi/spmi-pmic-arb.c` chooses different channel mappings and offsets by hardware version, discovers the PPID-to-APID mapping, and checks write ownership. SID 1 peripheral b3 corresponds to PPID `0x1b3`; the APID and owner are runtime values, not the SPMI SID or fixed offsets.

Next, capture the arbiter version and the mapping/ownership for PPID `0x1b3`, and read LPG subtype and configuration without writing them. The DT maps arbiter core at `0x01c40000`, channel window at `0x01e00000`, observer at `0x03e00000`, and configuration at `0x01c0a000`; use the vendor driver's version-specific map and bounds, and avoid exhausting the XNU 8 MiB `io_submap` by mapping individual pages rather than the full channel window. A successful read and confirmed APPS ownership are prerequisites for a bounded, timeout-checked write implementation. Then port the vendor period/duty calculation, connect asynchronous `AppleARMBacklight` updates to it, and provide an opt-in boot argument and a known-good rollback. Validate minimum, midpoint and maximum slider settings, display off/on, touch, GPU rendering and heat on hardware before calling brightness functional. Never assume a software property update means the physical PWM changed.

## Hardware probe and first candidate (2026-10-27)

`backlight-probe1` read the v5 arbiter: PPID 0x1b3 maps to APID 141,
owner 0 (APPS). PM6125 register values: type 0x13, subtype 0x0b,
size/clock 0x07, predivider 0x02, duty high/low 0x00/0xff, enable 0x80.
Log: `out/ios16/logs/backlight-probe1-live.txt`. Based on the vendor driver,
this is 9-bit PWM and enable bit 2 selects the PWM value source; the inherited
value has that bit clear.

An opt-in `citrusbl=1` candidate in the staged GPU framebuffer validates the
channel, subtype, clock and ownership; it uses bounded SPMI transactions and
readback, connects the inherited backlight service to PWM duty, and offers
`citrusblrestore=1` to restore the inherited source selection. It compiled and
booted as `backlight1`, SHA256
`bfd632ea34d9004f588209a3898a453939c2e885a265d1b610da8b1ccd9568d5`.
`AppleARMBacklight` was published and matched by backboardd, but **no
brightness property callback or PWM write was logged** during attempted slider
use. The user reported severe performance regression. A digital-dimming
interaction is plausible from prior evidence but not established by this boot;
sampled complex frames took 0.11–0.91 s and are not a controlled comparison.
The candidate is quarantined; do not present it as working or reflash without
new diagnosis. `backlight-restore1` was packaged but not needed: the candidate
logged no duty writes, and its PMIC source selection remained unchanged.

The confirmed button image was restored (flash log and capture
`backlight1-rollback-{flash.log,live.txt}`); four CPUs and GPU self-test passed.
The user confirmed the rollback refreshes and feels like the prior boot. Next investigate why CoreBrightness finds
the service but sends no level request, and why publishing it degrades the UI;
only then retest the PWM writer. Root image was never modified.
