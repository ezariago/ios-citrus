# Citrus power and volume buttons

Status: the existing button driver and HID service match the captured Citrus
wiring, but the current boot disables the driver (`sweetkeys=0`). **No Citrus
button has been tested in XNU.** This investigation does not change or flash
any image.

The Android live device tree in `device-dumps/20261025-141423-923416/` lists
SPMI arbiter core `0x01c40000`, observer `0x03e00000`, configuration
`0x01c0a000`, and PM6125 at SID 0. PON at `0x800` maps power to Linux code
116 and resin to volume-down code 114. Volume-up is active-low PM6125 GPIO5
(code 115), configured as input with pull-up. The captured Android input list
also shows both `qpnp_pon` and `gpio-keys` devices.

The source retained in `out/citrus-gpu-pll0-950/xnu/bsd/dev/sweet_keys.c`
already uses those arbiter addresses, PON PPID `0x008`, GPIO5 PPID `0x0c4`
and status register `0xc410`. It sends PON bit 0 as power, active-low GPIO5
bit 0 as volume-up, and PON bit 1 as volume-down. The inherited HID service
maps these to consumer power, volume increment, and volume decrement. Its
registration and backboardd's open are visible in the existing pll0-950 log;
the key driver logs that it is disabled. The linked kernel contains the driver
and HID diagnostic strings. This wiring match is not a hardware validation of
the observer register protocol, bit polarity, firmware GPIO state, or iOS
behavior on Citrus. The driver's old `gpio4:c110` diagnostic label is stale;
the compiled GPIO5 register is `0xc410`.

The driver scans arbiter APIDs, checks arbiter version and GPIO configuration,
and issues observer read commands; it does not write PMIC configuration. It
polls every 20 ms and suppresses volume-up if the input is not confirmed
configured. Its polling does not share a lock with `sweet_spmi.c`; the current
Citrus `SweetBattery::start()` returns before starting battery polling, so do
not enable battery SPMI polling concurrently without adding serialization.
The driver changes state only after successful reads, but no retry/debounce
beyond the polling interval is present. An unsupported arbiter version prevents
all keys from starting.

For a future boot-only test, replace the existing `sweetkeys=0` token with
`sweetkeys=1`, retain the unchanged 950 MHz kernel and all other baseline
settings, and start one durable log reader before reboot. Verify the version,
APID, and GPIO configuration line before individually pressing and releasing
volume up, volume down, and power; each should produce one `SWEET KEYS` down
and up and corresponding `SWEET HID: key` events with clients, followed by
visible iOS behavior. Avoid a long power+volume combination because the PMIC
has hardware reset timers. `sweetfb_stayon=1` may affect display blanking, so
check lock/wake separately from panel power. Revert to the existing pll0-950
boot image if the experiment is unstable; the root image need not change.
