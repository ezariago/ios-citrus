#!/usr/bin/env python3
"""Summarize the redwood-gl frame/profile/allocation lines from a boot capture.

These numbers are the wrapper's own GL-thread timings, sampled once every 20
frames after the first 40; they are not an end-to-end FPS measurement.  The
profile lines are cumulative, so the per-200-frame marginal columns are usually
more useful than the cumulative average.

Usage:
  tools/analyze-redwood-frames.py out/ios16/logs/gpu-pool2-live.txt
  tools/analyze-redwood-frames.py --since-byte 628996 out/ios16/logs/gpu-pool2-b0-live.txt
  tools/analyze-redwood-frames.py --json out.json LOG...
"""
import argparse
import json
import re
import statistics
from pathlib import Path

FRAME = re.compile(
    r'redwood-gl: frame (\d+): (\d+) GL calls, (\d+) draws, (\d+) triangles, '
    r'(\d+) clears; (\d+) textures refilled from IOSurfaces \((\d+) KB\); '
    r'(\d+) pictures copied out, (\d+) drawn in place; (\d+) us \((\d+) handing on, '
    r'(\d+) waiting, (\d+) copying out\), (\d+) before it for the IOSurfaces')
PROFILE = re.compile(
    r'profile: (\d+) us a frame in GL calls, (\d+) outside them; frames ended on '
    r'big cores (\d+), little (\d+); most time: (.*)')
PROFILE_CALL = re.compile(r'([A-Za-z0-9_]+) (\d+)')
ALLOC = re.compile(
    r'CitrusGPU alloc: request=(\d+) result=(\w+) low_us=(\d+) pool_us=(\d+) '
    r'free=(\d+) largest=(\d+) blocks=(\d+) attempts=(\d+) failures=(\d+)')
SUBMIT = re.compile(
    r'RedwoodGPU: (\d+) submissions in (\d+) ms: (\d+) command buffers and '
    r'(\d+) buffers named, (\d+) KB out of the cache in (\d+) us a submission')

FRAME_FIELDS = ('frame calls draws tris clears refills kb out inplace total '
                'hand wait copy before').split()
PROFILE_KEYS = ('glFlush', 'glTexImage2D', 'glDrawElements', 'glBindTexture')
COLD = 40


def pct(values, q):
    return values[round((len(values) - 1) * q)] if values else None


def describe(name, values):
    if not values:
        return f'{name:24s} no samples'
    v = sorted(values)
    return (f'{name:24s} n={len(v):3d} min={v[0]/1000:7.2f} med={pct(v, .5)/1000:7.2f} '
            f'p90={pct(v, .9)/1000:7.2f} p95={pct(v, .95)/1000:7.2f} '
            f'max={v[-1]/1000:7.2f} mean={statistics.mean(v)/1000:7.2f} ms')


def read_lines(path, since):
    data = Path(path).read_bytes()
    if since:
        data = data[since:]
    return data.decode('utf-8', 'replace').splitlines()


def analyze(path, since=0):
    frames, profiles, allocs, submits = [], [], [], []
    for line in read_lines(path, since):
        m = FRAME.search(line)
        if m:
            frames.append(dict(zip(FRAME_FIELDS, map(int, m.groups()))))
            continue
        m = PROFILE.search(line)
        if m:
            profiles.append({
                'frame': int(m.group(3)),
                'gl': int(m.group(1)),
                'outside': int(m.group(2)),
                'times': {k: int(v) for k, v in PROFILE_CALL.findall(m.group(5))},
            })
            continue
        m = ALLOC.search(line)
        if m:
            keys = ('request result low_us pool_us free largest blocks '
                    'attempts failures').split()
            row = dict(zip(keys, m.groups()))
            for k in keys:
                if k != 'result':
                    row[k] = int(row[k])
            allocs.append(row)
            continue
        m = SUBMIT.search(line)
        if m:
            n, ms, cbs, named, kb, us = map(int, m.groups())
            submits.append({'submissions': n, 'ms': ms, 'cmd_buffers': cbs,
                            'named': named, 'kb': kb, 'cache_us': us})
    return {'path': str(path), 'since': since, 'frames': frames,
            'profiles': profiles, 'allocs': allocs, 'submits': submits}


def report(res):
    frames = res['frames']
    print(f"\n== {res['path']}"
          + (f" (from byte {res['since']})" if res['since'] else ''))
    if not frames:
        print('no redwood-gl frame lines')
        return
    cold = [f for f in frames if f['frame'] < COLD]
    warm = [f for f in frames if f['frame'] >= COLD]
    print(f"frames: {len(frames)} samples, frame {frames[0]['frame']}..{frames[-1]['frame']}; "
          f"cold(<{COLD})={len(cold)} warm={len(warm)}")
    for label, rows in (('cold', cold), ('warm', warm)):
        print(f'-- {label}')
        for key in ('total', 'hand', 'wait', 'copy', 'before'):
            print(describe(key, [f[key] for f in rows]))
    if warm:
        heavy = [f['total'] for f in warm]
        print(f"warm over 16.7 ms (60 Hz budget): {sum(v > 16700 for v in heavy)}/{len(heavy)}; "
              f"over 33.3 ms: {sum(v > 33300 for v in heavy)}/{len(heavy)}")
        refills = [f for f in warm if f['refills']]
        print(f"warm refill samples: {len(refills)}/{len(warm)}, "
              f"{sum(f['kb'] for f in refills)} KB total, "
              f"max {max((f['kb'] for f in refills), default=0)} KB in a sample")
        print(f"warm copied out: {sum(f['out'] for f in warm)} pictures; "
              f"drawn in place: {sum(f['inplace'] for f in warm)}")

    if res['allocs']:
        print('-- allocations')
        low = [a['low_us'] for a in res['allocs']]
        print(f"{len(res['allocs'])} requests, results="
              f"{sorted({a['result'] for a in res['allocs']})}, "
              f"low_us min={min(low)} med={int(pct(sorted(low), .5))} max={max(low)}, "
              f"pool_us max={max(a['pool_us'] for a in res['allocs'])}, "
              f"sub-attempt failures={sum(a['failures'] for a in res['allocs'])}")
    if res['submits']:
        print('-- submissions')
        rates = [s['submissions'] / (s['ms'] / 1000) for s in res['submits']]
        cache = [s['cache_us'] for s in res['submits']]
        print(f"{len(res['submits'])} windows; submissions/s med={pct(sorted(rates), .5):.0f} "
              f"max={max(rates):.0f}; cache maintenance med={pct(sorted(cache), .5)} us/sub "
              f"max={max(cache)} us/sub")

    if res['profiles']:
        print('-- profile marginal per frame (cumulative deltas)')
        print(f"{'block':>13} {'gl/f':>7} {'out/f':>7} "
              + ' '.join(f'{k:>13}' for k in PROFILE_KEYS))
        prev = None
        for p in res['profiles']:
            if prev:
                n = p['frame'] - prev['frame']
                if n > 0:
                    cells = []
                    for k in PROFILE_KEYS:
                        delta = p['times'].get(k, 0) - prev['times'].get(k, 0)
                        cells.append(f'{delta / n / 1000:13.2f}')
                    print(f"{prev['frame']:5d}->{p['frame']:<5d} "
                          f"{p['gl']/1000:7.2f} {p['outside']/1000:7.2f} "
                          + ' '.join(cells))
            prev = p


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('logs', nargs='+')
    ap.add_argument('--since-byte', type=int, default=0,
                    help='ignore everything before this byte offset (for a workload marker)')
    ap.add_argument('--json', help='write the parsed data here')
    args = ap.parse_args()
    results = [analyze(p, args.since_byte) for p in args.logs]
    for res in results:
        report(res)
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=1))


if __name__ == '__main__':
    main()
