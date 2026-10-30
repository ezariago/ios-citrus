#!/usr/bin/env python3
"""Check SWEET page-size and AMP preprocessor gates in the staged 4K source."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / 'out/citrus-8core/source/xnu/pexpert/pexpert/arm64/SWEET.h'


def macros(flags):
    result = subprocess.run(['clang', '-x', 'c', '-E', '-dM', *flags, str(HEADER)],
                            check=True, capture_output=True, text=True)
    return {line.split()[1] for line in result.stdout.splitlines() if line.startswith('#define ')}


def main():
    for flags, is_16k, is_amp in [
        ([], True, False),
        (['-DTOPAZ_4K=1'], False, False),
        (['-DTOPAZ_4K=1', '-DCITRUS_4K_AMP=1'], False, True),
        (['-DCITRUS_4K_AMP=1'], True, False),
    ]:
        defined = macros(flags)
        assert ('__ARM_16K_PG__' in defined) == is_16k, flags
        assert ('__ARM_AMP__' in defined) == is_amp, flags
    print('PASS: 16K baseline, 4K SMP and explicit 4K AMP gates')


if __name__ == '__main__':
    main()
