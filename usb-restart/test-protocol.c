#include <assert.h>
#include <string.h>
#include "protocol.h"
static enum citrus_usb_command feed(struct citrus_usb_parser *p, const char *s) {
    enum citrus_usb_command result = CITRUS_NONE;
    for (; *s; ++s) { enum citrus_usb_command x = citrus_usb_feed(p, (uint8_t)*s); if (x) result = x; }
    return result;
}
int main(void) {
    struct citrus_usb_parser p = {0};
    assert(feed(&p, "citrus:pi") == CITRUS_NONE);
    assert(feed(&p, "ng\n") == CITRUS_PING);
    assert(feed(&p, "citrus:reboot:fastboot\n") == CITRUS_FASTBOOT);
    assert(feed(&p, "citrus:reboot:recovery\n") == CITRUS_RECOVERY);
    assert(feed(&p, "citrus:reboot:fastbootX\n") == CITRUS_NONE);
    for (int i = 0; i < 100; ++i) assert(citrus_usb_feed(&p, 'x') == CITRUS_NONE);
    assert(feed(&p, "citrus:ping\n") == CITRUS_NONE);
    assert(feed(&p, "citrus:ping\n") == CITRUS_PING);
    return 0;
}
