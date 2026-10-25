#!/bin/bash
# Stream a large image into a block device through a rooted adb shell.
#
# Needed because this device's fastboot rejects images >= 2 GiB, and sparse
# chunk offsets are 32-bit, so a 16 GiB volume cannot be flashed with fastboot.
# Boot the installed OrangeFox recovery (fastboot reboot recovery), CANCEL ADB
# Sideload so adbd accepts `adb shell`, then run:
#
#   tools/stream-image-adb.sh out/ios16/ios16-root.img /dev/block/by-name/userdata
#
# Each 1 GiB segment uses dd seek= on both sides, so a failed run can simply be
# repeated. Verify afterwards with:
#   adb shell "dd if=/dev/block/by-name/userdata bs=1048576 count=16384 2>/dev/null | sha256sum"
set -u
set -o pipefail
IMG=${1:?usage: stream-image-adb.sh IMAGE BLOCK_DEVICE}
DEV=${2:?usage: stream-image-adb.sh IMAGE BLOCK_DEVICE}
SEGMENT_MIB=1024
size=$(stat -f %z "$IMG")
segments=$(( (size + SEGMENT_MIB*1024*1024 - 1) / (SEGMENT_MIB*1024*1024) ))
echo "image $IMG size $size bytes, $segments segments of ${SEGMENT_MIB} MiB -> $DEV"
for ((k=0; k<segments; k++)); do
    skip=$(( k * SEGMENT_MIB ))
    start=$(date +%s)
    dd if="$IMG" bs=1048576 skip=$skip count=$SEGMENT_MIB 2>/dev/null |
        adb shell "dd of=$DEV bs=1048576 seek=$skip conv=notrunc 2>/dev/null && sync"
    rc=$?
    echo "segment $k seek=${skip}MiB rc=$rc seconds=$(( $(date +%s) - start ))"
    if [ $rc -ne 0 ]; then echo "segment $k failed; re-run this script to resume"; exit 1; fi
done
echo "stream finished"
adb shell "blockdev --getsize64 $DEV"
