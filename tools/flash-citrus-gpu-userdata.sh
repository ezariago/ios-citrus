#!/bin/bash
# Flash the prepared triangle root into userdata through recovery/ADB.
#
# Refuses to start unless the host image hash and the attached ADB device match
# the expected test target. Writes 16 x 1 GiB segments (fastboot rejects a
# 16 GiB image), then reads the block device back and compares SHA256.
#
# Preconditions: phone in OrangeFox recovery, ADB Sideload cancelled so
# `adb shell` answers. This script does not reboot the phone.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
IMG=${1:-"$ROOT/out/ios16/ios16-root-gpu-triangle.img"}
DEV=${2:-/dev/block/by-name/userdata}
EXPECT=${3:-8833e381361a1a9773eafa580a2fc4bc0c8557f2e6c1eeccd5cc691e26653625}

[ -f "$IMG" ] || { echo "no image: $IMG" >&2; exit 1; }
# CITRUS_IMAGE_SHA: a hash taken already (the image has not changed since), for
# when hashing 16 GiB again would crowd the machine out.
HOST=${CITRUS_IMAGE_SHA:-$(shasum -a 256 "$IMG" | cut -d' ' -f1)}
if [ "$HOST" != "$EXPECT" ]; then
    echo "image hash mismatch: $HOST != $EXPECT" >&2
    exit 1
fi
echo "image $IMG sha256 $HOST"

adb get-state >/dev/null 2>&1 || { echo "adb has no device; boot recovery first" >&2; exit 1; }
SIZE=$(adb shell "blockdev --getsize64 $DEV" | tr -d '\r')
# userdata is the whole ~47 GiB partition; the HFSX root is its first 16 GiB.
if [ "$SIZE" -lt 17179869184 ]; then
    echo "$DEV is $SIZE bytes, smaller than the 16 GiB root volume" >&2
    exit 1
fi
echo "$DEV is $SIZE bytes; writing the first 16 GiB (this takes tens of minutes)"

"$ROOT/tools/stream-image-adb.sh" "$IMG" "$DEV"

echo "reading back $DEV for SHA256 (also tens of minutes)"
REMOTE=$(adb shell "dd if=$DEV bs=1048576 count=16384 2>/dev/null | sha256sum" | tr -d '\r' | cut -d' ' -f1)
if [ "$REMOTE" != "$EXPECT" ]; then
    echo "ON-DEVICE SHA MISMATCH: $REMOTE != $EXPECT" >&2
    exit 1
fi
echo "ON-DEVICE SHA OK $REMOTE"
echo "now reboot the phone; the gpu-svc1 boot image stays installed"
