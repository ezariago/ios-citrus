/* Bounded CDC byte-stream parser; no I/O, allocation, or reset side effects. */
#ifndef CITRUS_USB_RESTART_PROTOCOL_H
#define CITRUS_USB_RESTART_PROTOCOL_H
#include <stddef.h>
#include <stdint.h>

enum citrus_usb_command { CITRUS_NONE, CITRUS_PING, CITRUS_FASTBOOT, CITRUS_RECOVERY };
struct citrus_usb_parser { unsigned used; unsigned discard; char line[64]; };
static enum citrus_usb_command
citrus_usb_feed(struct citrus_usb_parser *p, uint8_t c)
{
    static const char ping[] = "citrus:ping";
    static const char fastboot[] = "citrus:reboot:fastboot";
    static const char recovery[] = "citrus:reboot:recovery";
    const char *expected[] = { ping, fastboot, recovery };
    if (c != '\n') {
        if (!p->discard && p->used < sizeof(p->line)) p->line[p->used++] = (char)c;
        else p->discard = 1;
        return CITRUS_NONE;
    }
    enum citrus_usb_command result = CITRUS_NONE;
    if (!p->discard) {
        for (unsigned i = 0; i < 3; ++i) {
            unsigned j = 0;
            while (j < p->used && expected[i][j] && p->line[j] == expected[i][j]) ++j;
            if (j == p->used && expected[i][j] == '\0') { result = (enum citrus_usb_command)(i + 1); break; }
        }
    }
    p->used = p->discard = 0;
    return result;
}
#endif
