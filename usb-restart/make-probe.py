#!/usr/bin/env python3
"""Make a receive-only sweet_usb.c overlay. Never changes the source tree."""
from pathlib import Path
import argparse
p = argparse.ArgumentParser()
p.add_argument('source', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
s = a.source.read_text()
header = (Path(__file__).parent / 'protocol.h').read_text()
anchor = 'static void\nud_rx_done(void)\n{'
assert s.count(anchor) == 1
insert = '''\nstatic struct citrus_usb_parser citrus_parser;\n'''
s = s.replace(anchor, header + insert + anchor)
anchor = '\tud_sync(UD_RX, UD_FRAME_MAX);\n'
assert s.count(anchor) == 1
probe = '''\t/* Probe only: no received command can reset this build. */
\tif (len <= UD_FRAME_MAX) {
\t\tfor (uint32_t i = 0; i < len; i++) {
\t\t\tenum citrus_usb_command c = citrus_usb_feed(&citrus_parser, ((const uint8_t *)(ud.dma + UD_RX))[i]);
\t\t\tif (c == CITRUS_PING) printf("CITRUS USB: ping received\\n");
\t\t\telse if (c == CITRUS_FASTBOOT || c == CITRUS_RECOVERY)
\t\t\t\tprintf("CITRUS USB: restart request received, probe only\\n");
\t\t}
\t}
'''
s = s.replace(anchor, anchor + probe)
a.output.write_text(s)
