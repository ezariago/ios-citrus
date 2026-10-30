#!/usr/bin/env python3
"""Summarize touch_lat=1 timing lines; times are microseconds, not input-to-photon latency."""
import argparse
import re
from pathlib import Path

PATTERNS = {
    'touch': re.compile(r'tl: p (\d+) (\d+) (-?\d+) (-?\d+) at (\d+)'),
    'chip': re.compile(r'tl: c before (\d+) seen (\d+) read (\d+)'),
    'frame': re.compile(r'tl: g (\d+) began (\d+) ended (\d+) (\d+)'),
    'swap': re.compile(r'tl: s (\d+) at (\d+)'),
    'display': re.compile(r'tl: v (\d+) ready (\d+) shown (\d+) done (\d+)'),
    'wait': re.compile(r'tl: f (\S+) (\d+) at (\d+)'),
}

def percentile(values, fraction):
    values = sorted(values)
    return values[round((len(values) - 1) * fraction)] if values else None

def describe(name, samples):
    if samples:
        print(f'{name}: n={len(samples)}, median={percentile(samples, .5)/1000:.2f} ms, '
              f'p95={percentile(samples, .95)/1000:.2f} ms, max={max(samples)/1000:.2f} ms')
    else:
        print(f'{name}: no matching samples')

def analyze(path, last_touch_seconds=None):
    events = {k: [] for k in PATTERNS}
    for line in Path(path).read_text(errors='replace').splitlines():
        for name, pattern in PATTERNS.items():
            m = pattern.search(line)
            if m:
                events[name].append(m.groups())
                break
    if last_touch_seconds is not None and events['touch']:
        end = int(events['touch'][-1][-1])
        start = end - int(last_touch_seconds * 1_000_000)
        time_index = {'touch': 4, 'chip': 2, 'frame': 2, 'swap': 1, 'display': 3, 'wait': 2}
        events = {name: [row for row in rows if start <= int(row[time_index[name]]) <= end] for name, rows in events.items()}
        print(f'Window: {last_touch_seconds:g} seconds ending at the last captured touch')
    print('Counts:', ', '.join(f'{k}={len(v)}' for k, v in events.items()))
    describe('Touch IRQ observation to report read', [int(r[2])-int(r[1]) for r in events['chip'] if int(r[2]) >= int(r[1])])
    describe('Compositor frame duration', [int(r[2])-int(r[1]) for r in events['frame'] if int(r[2]) >= int(r[1])])
    frame_ends = sorted(int(r[2]) for r in events['frame'])
    frame_gaps = [b-a for a,b in zip(frame_ends,frame_ends[1:]) if 0 < b-a <= 500000]
    describe('Compositor frame-completion gaps (excluding pauses over 500 ms)', frame_gaps)
    swaps = {int(r[0]): int(r[1]) for r in events['swap']}
    display = [(int(r[0]), *(int(x) for x in r[1:])) for r in events['display']]
    describe('Swap to surface GPU wait completion', [ready-swaps[i] for i, ready, shown, done in display if i in swaps and ready >= swaps[i]])
    describe('Surface wait completion to present return', [shown-ready for i, ready, shown, done in display if shown >= ready])
    describe('Present return to MDP latch poll end', [done-shown for i, ready, shown, done in display if done >= shown])
    done = sorted(r[3] for r in display)
    gaps = [b-a for a,b in zip(done,done[1:]) if 0 < b-a <= 500000]
    describe('Instrumented direct-latch gaps, incomplete subset (excluding pauses over 500 ms)', gaps)
    if gaps:
        print(f'Instrumented latch gaps over 18 ms: {sum(g > 18000 for g in gaps)}/{len(gaps)}; over 34.5 ms: {sum(g > 34500 for g in gaps)}/{len(gaps)} (not an FPS estimate)')
    print('Display times measure driver completion and latch polling, not physical panel pixels; input-to-photon latency is not measured.')

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('log'); parser.add_argument('--last-touch-seconds', type=float, default=None); args=parser.parse_args(); analyze(args.log, args.last_touch_seconds)
