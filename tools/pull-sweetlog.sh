#!/bin/sh
# Pull the sweetlog ring, the flight-recorder block and the interrupt-context
# stall samples from userdata in recovery (read-only) and decode them.
# Usage: tools/pull-sweetlog.sh NAME
#   -> out/ios16/logs/NAME-sweetlog.{bin,txt}
#   -> out/ios16/logs/NAME-heartbeat.{bin,txt}
#   -> out/ios16/logs/NAME-stalls.txt
set -e
name=${1:?name}
out=out/ios16/logs
mkdir -p "$out"
adb devices | grep -q $'\trecovery$' || { echo "need one ADB recovery device" >&2; exit 1; }
bytes=$(adb shell blockdev --getsize64 /dev/block/by-name/userdata | tr -d '\r')
# Layout, from the end of the partition backwards: 4 MiB + 1 block console log,
# 1 heartbeat block, then 16 stall-sample blocks.
skip=$((bytes/4096-1042))
adb exec-out "dd if=/dev/block/by-name/userdata bs=4096 skip=$skip count=1042 2>/dev/null" > "$out/$name-raw.bin"
python3 - "$out/$name-raw.bin" "$out" "$name" <<'PY'
import struct, sys
raw_path, out, name = sys.argv[1], sys.argv[2], sys.argv[3]
raw = open(raw_path, 'rb').read()
assert len(raw) == 1042 * 4096, (len(raw), 'short read')
stall = raw[:16 * 4096]
hb = raw[16 * 4096:17 * 4096]
log = raw[17 * 4096:]
open(f'{out}/{name}-sweetlog.bin', 'wb').write(log)
open(f'{out}/{name}-heartbeat.bin', 'wb').write(hb)

fields = ['boot_id', 'seq', 'uptime_s', 'console_bytes', 'console_seq', 'ufs_ios',
          'flush_runs', 'free_pages', 'wire_pages',
          'prev_boot_id', 'prev_phase', 'prev_uptime_s', 'prev_console_bytes',
          'prev_console_seq', 'prev_ufs_ios', 'prev_flush_runs']
if hb[:8] == b'SWEETHB1':
    version, phase = struct.unpack_from('<II', hb, 8)
    values = struct.unpack_from('<16Q', hb, 16)
    lines = [f'magic {hb[:8]!r} version {version} phase {phase}']
    lines += [f'{k:20} {v}' for k, v in zip(fields, values)]
    text = '\n'.join(lines)
    open(f'{out}/{name}-heartbeat.txt', 'w').write(text + '\n')
    print(text)
else:
    print('no flight-recorder block (this boot predates it or the read was short)')

# Stall samples: 8 byte magic, u32 version, u32 slot, then 9 u64 fields.
rows = []
for i in range(16):
    blk = stall[i * 4096:(i + 1) * 4096]
    if blk[:8] != b'SWEETSTL':
        continue
    version, slot = struct.unpack_from('<II', blk, 8)
    seq, uptime_s, stall_s, pc, last_pc = struct.unpack_from('<5Q', blk, 16)
    proc = blk[56:72].split(b'\0')[0].decode('utf-8', 'replace')
    console_bytes, ufs_ios, free_pages = struct.unpack_from('<3Q', blk, 72)
    rows.append((seq, slot, uptime_s, stall_s, pc, last_pc, proc,
                 console_bytes, ufs_ios, free_pages))
if rows:
    lines = ['seq slot uptime stall   pc                 last_pc            proc             console_bytes ufs_ios free_pages']
    for r in sorted(rows):
        seq, slot, up, st, pc, lpc, proc, cb, io, fp = r
        lines.append(f'{seq:3} {slot:4} {up:6} {st:5} 0x{pc:016x} 0x{lpc:016x} {proc:16} '
                     f'{cb:13} {io:7} {fp}')
    text = '\n'.join(lines)
    open(f'{out}/{name}-stalls.txt', 'w').write(text + '\n')
    print(text)
else:
    print('no interrupt-context stall samples')
PY
python3 upstream/ios-topaz/tools/sweet-log.py "$out/$name-sweetlog.bin" "$out/$name-sweetlog.txt"
python3 - "$out/$name-sweetlog.bin" <<'PY'
import struct, sys
d = open(sys.argv[1], 'rb').read(32)
if d[:8] == b'SWEETLOG':
    print('sweetlog total', struct.unpack_from('<Q', d, 16)[0],
          'seq', struct.unpack_from('<Q', d, 24)[0])
PY
