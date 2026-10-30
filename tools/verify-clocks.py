#!/usr/bin/env python3
"""Check a Citrus XNU boot capture against the designed-clock checklist.

Every claim the clock goal makes is a line in the console capture. This script
is the objective's pass/fail gate: point it at a live capture, it prints one row
per claim and exits non-zero if a claim that the image should satisfy is absent
or wrong.

    python3 tools/verify-clocks.py out/ios16/logs/4k-smp7-clk-live.txt

Tri-state, because captures come from different images:

    PASS     the evidence line is present and matches the expected value
    MISSING  the image in that capture predates the check (e.g. the read-only
             UFS report added 2026-10-29 04:15) -- not a failure
    FAIL     the line is present but the value is wrong

Notes that matter when reading the numbers:
  * the tick counter is 19.2 MHz, not 24; a capture from a build that used the
    old constant reports every frequency 1.25x high (see the DDR probe).
  * pass several captures to merge them: the CPU/GPU evidence and the
    diagnostic sweep/DDR probe usually come from different boots.
  * the DDR probe counts read+write bytes, so its ceiling is ~2x the peak.
"""

import argparse
import re
import sys

# (name, regex, group, predicate, predicate_text)
CHECKS = [
    (
        "CPUs online (7 = 4 Gold + Silver 1-3)",
        r"SWEET CPU: (\d+)/7 CPUs initialized",
        1,
        lambda v: int(v) == 7,
        "== 7",
    ),
    (
        "Silver cluster at its top OPP",
        r"silver perf_state \d+ -> (\d+), readback (\d+) \(1804 MHz\)",
        2,
        lambda v: int(v) == 7,
        "== 7 (1804 MHz)",
    ),
    (
        "Gold cluster at its top OPP (turbo)",
        r"gold perf_state \d+ -> (\d+), readback (\d+) \(2016 MHz\)",
        2,
        lambda v: int(v) == 8,
        "== 8 (2016 MHz)",
    ),
    (
        "Gold normal (sustained) step present in the LUT",
        r"gold 300\.\.2016 MHz in 9 states.*normal=(\d+)",
        1,
        lambda v: int(v) == 7,
        "normal == 7 (1804 MHz)",
    ),
    (
        "Silver normal step present in the LUT",
        r"silver 300\.\.1804 MHz in 8 states.*normal=(\d+)",
        1,
        lambda v: int(v) == 6,
        "normal == 6 (1612 MHz)",
    ),
    (
        "GPU gfx3d programmed to 950 MHz",
        r"gfx3d (\d+) MHz \(PLL0 1900/2",
        1,
        lambda v: int(v) == 950,
        "== 950",
    ),
    (
        "GPU CP running at 950 MHz",
        r"CP up .*core (\d+) MHz",
        1,
        lambda v: int(v) == 950,
        "== 950",
    ),
    (
        "GPU self-test passed",
        r"selftest PASS",
        0,
        lambda v: True,
        "present",
    ),
    (
        "DDR copy bandwidth (probe counts read+write)",
        r"ddr copy probe (\d+) MB/s",
        1,
        lambda v: int(v) >= 8000,
        ">= 8000 MB/s",
    ),
]

# Per-branch designed maxima, from the UFS node's freq-table-hz in bengal.dtsi.
UFS_WANT = {"ufs_axi": 200, "ufs_ice": 300, "ufs_unipro": 150}
UFS_RE = re.compile(
    r"SWEET CLOCK: (ufs_axi|ufs_ice|ufs_unipro) src=(\d+) div=(\d+) -> (\d+) MHz \(want (\d+)"
)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "captures",
        nargs="+",
        help="console capture(s) to check; several are merged (evidence for one "
        "image is often spread over more than one boot)",
    )
    ap.add_argument(
        "--quiet-missing",
        action="store_true",
        help="exit 0 even when checks are MISSING (image predates them)",
    )
    args = ap.parse_args(argv)

    text = ""
    for path in args.captures:
        try:
            with open(path, "r", errors="replace") as f:
                text += f.read() + "\n"
        except OSError as exc:
            print(f"cannot read {path}: {exc}")
            return 2

    rows = []
    failures = missing = passes = 0
    for name, pattern, group, pred, text_expect in CHECKS:
        rx = re.compile(pattern)
        values = [m.group(group) for m in rx.finditer(text)]
        if not values:
            rows.append(("MISSING", name, "+ " + text_expect))
            missing += 1
            continue
        good = [v for v in values if pred(v)]
        if good:
            rows.append(("PASS", name, ", ".join(dict.fromkeys(good))))
            passes += 1
        else:
            shown = ", ".join(dict.fromkeys(values))
            rows.append(("FAIL", name, f"{shown} (expected {text_expect})"))
            failures += 1

    # UFS branches: one row each, decoded rate against the design maximum.
    seen = {}
    for m in UFS_RE.finditer(text):
        seen[m.group(1)] = m
    for branch, want in UFS_WANT.items():
        m = seen.get(branch)
        label = f"{branch} RCG at designed {want} MHz (read-only decode)"
        if m is None:
            rows.append(("MISSING", label, "+ = " + str(want)))
            missing += 1
            continue
        got = int(m.group(4))
        src, div = m.group(2), m.group(3)
        detail = f"{got} MHz (src={src} div={div})"
        if got == want:
            rows.append(("PASS", label, detail))
            passes += 1
        else:
            rows.append(("FAIL", label, detail + f", expected {want}"))
            failures += 1

    width = max(len(r[1]) for r in rows)
    print("capturing: " + ", ".join(args.captures))
    for status, name, detail in rows:
        print(f"  {status:7s} {name:<{width}}  {detail}")
    print(
        f"\n{passes} pass, {failures} fail, {missing} missing "
        f"({len(rows)} checks)"
    )

    if failures:
        return 1
    if missing and not args.quiet_missing:
        print(
            "missing checks are from an image that predates them; "
            "use --quiet-missing to accept that"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
