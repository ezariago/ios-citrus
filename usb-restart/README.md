# Citrus USB restart

The 4 KiB two-Gold `gold2-usbpon` diagnostic accepts newline-terminated CDC
commands `citrus:ping`, `citrus:reboot:fastboot`, and `citrus:reboot:recovery`.
To send one request to the only connected modem:

```
python3 usb-restart/reboot.py fastboot
python3 usb-restart/reboot.py recovery
```

Add `--device /dev/cu.usbmodem00011` if necessary. The host write alone does
not prove the phone acted: confirm the mode with `fastboot devices` or `adb
 devices`. Fastboot was verified by USB enumeration and recovery by the user seeing the
recovery screen; both commands were sent at modem enumeration. The currently
installed recovery does not expose ADB reliably. `send-fastboot-on-enumeration.py`
and `send-recovery-on-enumeration.py` start before boot and send once as soon
as the modem appears. Keep one durable console reader, not multiple readers.

The handler checks application ownership of the PM6125 PON channel and its
subtype, writes the appropriate masked PMIC restart reason, verifies it, sets
the IMEM reason, and requests PSCI SYSTEM_RESET. The image uses the read-only
4K root profile. This immediate reset does not flush a writable filesystem.
Commands are unauthenticated: any host with access to the USB serial device
can invoke them. A stalled USB poller cannot service a command; enumeration
alone does not prove it is still running. Retain physical recovery as fallback.

`make-probe.py` and `make-pon-candidate.py` generate overlays outside protected
source trees. `protocol.h` has the bounded byte-stream parser; compile and test
it with `clang -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined
usb-restart/test-protocol.c -o /tmp/citrus-usb-protocol-test` and run that
binary. Build scripts and evidence paths are recorded in AGENTS.md. The local
relink caveats for the 4K diagnostic still apply.
