#!/bin/sh
# Pull the sweetlog ring, the flight-recorder block, the interrupt-context
# stall samples, the SMP observer capture and the panic block from userdata in
# recovery (read-only) and decode them.
# Usage: tools/pull-sweetlog.sh NAME
#   -> out/ios16/logs/NAME-sweetlog.{bin,txt}
#   -> out/ios16/logs/NAME-heartbeat.{bin,txt}
#   -> out/ios16/logs/NAME-stalls.txt
#   -> out/ios16/logs/NAME-observer.txt  (SMP CPU1 capture, when present)
#   -> out/ios16/logs/NAME-panic.txt     (only when a panic was stored)
set -e
name=${1:?name}
out=out/ios16/logs
mkdir -p "$out"
adb devices | grep -q $'\trecovery$' || { echo "need one ADB recovery device" >&2; exit 1; }
bytes=$(adb shell blockdev --getsize64 /dev/block/by-name/userdata | tr -d '\r')
# Layout, from the end of the partition backwards: 4 MiB + 1 block console log,
# 1 heartbeat block, 16 stall-sample blocks, then the SMP observer block
# (sweet_ufs.c: sweet_hb_base-17) and finally the panic block
# (sweet_panic_store: sweet_hb_base-18). The panic offset used to be one block
# too high here, which silently read the (then unused) observer block instead.
skip=$((bytes/4096-1044))
adb exec-out "dd if=/dev/block/by-name/userdata bs=4096 skip=$skip count=1044 2>/dev/null" > "$out/$name-raw.bin"
python3 - "$out/$name-raw.bin" "$out" "$name" <<'PY'
import struct, sys
raw_path, out, name = sys.argv[1], sys.argv[2], sys.argv[3]
raw = open(raw_path, 'rb').read()
assert len(raw) == 1044 * 4096, (len(raw), 'short read')
panic = raw[:4096]
obs = raw[4096:2 * 4096]
stall = raw[2 * 4096:2 * 4096 + 16 * 4096]
hb = raw[18 * 4096:19 * 4096]
log = raw[19 * 4096:]
open(f'{out}/{name}-panic.bin', 'wb').write(panic)
if panic[:9] == b'SWEETPAN1':
    text = panic[10:].split(b'\0')[0].decode('utf-8', 'replace')
    open(f'{out}/{name}-panic.txt', 'w').write(text + '\n')
    print('PANIC BLOCK:', text)
else:
    print('no sweet panic block (boot did not panic through sweet_early_panic)')
open(f'{out}/{name}-sweetlog.bin', 'wb').write(log)
open(f'{out}/{name}-heartbeat.bin', 'wb').write(hb)

# SMP observer capture (osfmk/arm64/cpu.c struct sweet_obs_record): written by
# the CPU1 thread when CPU0's timer counter has not moved for 2 s. Field order
# must match that struct exactly.
if obs[:8] == b'SWEETOBS':
    (seq, uptime_s, stall_s, timer0, timer1, ipi0, ipi_delta,
     ipi_rc, sig0, pend0, active0, enable0, waker0, thr0, stack0,
     obs_cpu, wat_mpidr, tname) = struct.unpack_from('<7QiI6QII64s', obs, 8)
    tname = tname.split(b'\0')[0].decode('utf-8', 'replace')
    lines = [
        f'magic SWEETOBS seq {seq} uptime_s {uptime_s} stall_s {stall_s}',
        f'timer0 (observed CPU) {timer0}   timer1 (observer CPU) {timer1}',
        f'ipi0 {ipi0} ipi_delta {ipi_delta} cpu_signal rc {ipi_rc} sig0 0x{sig0:x}',
        f'GICR pend0 0x{pend0:x} active0 0x{active0:x} '
        f'enable0 0x{enable0:x} waker0 0x{waker0:x}',
        f'active thread 0x{thr0:x} stack 0x{stack0:x} name {tname!r}',
        f'observer cpu {obs_cpu} observed mpidr 0x{wat_mpidr:x}',
    ]
    text = '\n'.join(lines)
    open(f'{out}/{name}-observer.txt', 'w').write(text + '\n')
    print(text)
else:
    print('no SMP observer block (single-CPU boot or CPU0 never stalled)')

# Field order must match struct sweet_heartbeat in bsd/dev/sweet_ufs.c exactly:
# the prev_* block sits where it does in the struct, and the interrupt-side
# fields come last. Getting this wrong mislabels every value.
fields = ['boot_id', 'seq', 'uptime_s', 'console_bytes', 'console_seq', 'ufs_ios',
          'flush_runs', 'free_pages', 'wire_pages',
          'prev_boot_id', 'prev_phase', 'prev_uptime_s', 'prev_console_bytes',
          'prev_console_seq', 'prev_ufs_ios', 'prev_flush_runs',
          'svc_runs', 'panel_runs', 'intr_pc', 'ufs_users']
if hb[:8] == b'SWEETHB1':
    version, phase = struct.unpack_from('<II', hb, 8)
    values = struct.unpack_from('<20Q', hb, 16)
    lines = [f'magic {hb[:8]!r} version {version} phase {phase}']
    lines += [f'{k:20} {v}' for k, v in zip(fields, values)]
    if version >= 3:
        irq_fields = ['ptimer_ticks', 'ptimer_pc', 'ptimer_user', 'ptimer_record',
                      'diag_attempts', 'diag_skips', 'diag_success', 'diag_errors',
                      'diag_status', 'ptimer_ctl', 'ptimer_tval', 'ptimer_frq']
        irq_values = struct.unpack_from('<12Q', hb, 16 + 20 * 8)
        lines += [f'{k:20} {hex(v) if k == "ptimer_pc" else v}'
                  for k, v in zip(irq_fields, irq_values)]
    if version >= 4:
        # v4 adds the GCC UFS power-domain/clock snapshot right after the IRQ
        # block: u64 gcc_changes, six u32 GDSCR/CBCR values, u32 gcc_collapses.
        gcc = struct.unpack_from('<Q6II', hb, 16 + 20 * 8 + 12 * 8)
        gcc_fields = ['gcc_changes', 'gcc_gdsc', 'gcc_axi', 'gcc_ahb',
                      'gcc_unipro', 'gcc_noc', 'gcc_clkref', 'gcc_collapses']
        lines += [f'{k:20} {hex(v) if k not in ("gcc_changes", "gcc_collapses") else v}'
                  for k, v in zip(gcc_fields, gcc)]
    if version >= 5:
        # v5 appends the host-controller sample: six u32 (HCE/HCS/IS/
        # UTRLDBR/UTRLRSR and the per-boot sample counter). If hc_seq stops
        # advancing while uptime advances, the 1 Hz thread itself is stuck in
        # a UFS register read; if it keeps advancing, the controller is alive.
        hc = struct.unpack_from('<6I', hb, 16 + 20 * 8 + 12 * 8 + 36)
        hc_fields = ['hc_hce', 'hc_hcs', 'hc_is', 'hc_utrldbr', 'hc_utrlrsr',
                     'hc_seq']
        lines += [f'{k:20} 0x{v:08x}' for k, v in zip(hc_fields, hc)]
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
    console_bytes, ufs_ios, free_pages, ufs_users = struct.unpack_from('<4Q', blk, 72)
    if version >= 2:
        op_age_ms, op_cdb, op_flags = struct.unpack_from('<QII', blk, 104)
    else:
        op_age_ms, op_cdb, op_flags = 0, 0, 0
    pt = struct.unpack_from('<Q', blk, 120)[0] if version >= 3 else 0
    rows.append((seq, slot, uptime_s, stall_s, pc, last_pc, proc,
                 console_bytes, ufs_ios, free_pages, ufs_users,
                 op_age_ms, op_cdb, op_flags, pt))
if rows:
    lines = ['seq slot uptime stall   pc                 last_pc            proc             console_bytes ufs_ios free_pages users  ufs_op']
    for r in sorted(rows):
        (seq, slot, up, st, pc, lpc, proc, cb, io, fp, users,
         op_age, op_cdb, op_flags, pt) = r
        mode = ('user' if op_flags & 4 else 'kernel') if op_flags & 8 else 'stall'
        op = 'idle'
        if op_flags & 2:
            op = f'0x{op_cdb:02x}{"w" if op_flags & 1 else "r"} age={op_age}ms'
        lines.append(f'{seq:3} {slot:4} {up:6} {st:5} 0x{pc:016x} 0x{lpc:016x} {proc:16} '
                     f'{cb:13} {io:7} {fp:9} {users:5}  {op} ptimer={pt} mode={mode}')
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
