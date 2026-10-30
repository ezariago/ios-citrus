#!/usr/bin/env python3
"""Read-only preflight for a clean Citrus 4K/AMP kernel build.

This deliberately does not build, flash, or assert that Xcode versions other
than upstream's are incompatible. The published 16K archive cannot be reused
for a 4K/AMP kernel, even when a subset of sources compiles successfully.
"""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xcode', type=Path, default=Path('/Applications/Xcode_15.4.app'))
    parser.add_argument('--kdk', type=Path, help='KDK 13.5 root or unpacked KDK.pkg/Payload')
    args = parser.parse_args()
    xcodebuild = args.xcode / 'Contents/Developer/usr/bin/xcodebuild'
    version = None
    if xcodebuild.is_file():
        result = subprocess.run([str(xcodebuild), '-version'], capture_output=True, text=True)
        version = result.stdout.strip() if result.returncode == 0 else None
    headers = ('System/Library/Frameworks/Kernel.framework/Headers',
               'Library/Developer/KDKs/KDK_13.5.kdk/System/Library/Frameworks/Kernel.framework/Headers')
    kdk_found = bool(args.kdk and any((args.kdk / p).is_dir() for p in headers))
    report = {
        'reference_xcode': '15.4',
        'xcode_path': str(args.xcode),
        'xcode_version': version,
        'reference_xcode_found': bool(version and version.splitlines()[0] == 'Xcode 15.4'),
        'kdk_path': str(args.kdk) if args.kdk else None,
        'kdk_kernel_headers_found': kdk_found,
        'kdk_version_verified': False,
        'clean_4k_build_required': True,
        'existing_16k_archive_suitable': False,
        'hardware_ready': False,
        'remaining': ['verify KDK version and build dependencies',
                      'rebase 4K patches and audit signature validation',
                      'rebuild all objects and generated assembly offsets',
                      'audit 4K early mapping and user/GPU surface alignment',
                      'implement and test Silver CPU handoff and topology'],
    }
    print(json.dumps(report, indent=2))
    return 0 if report['reference_xcode_found'] and kdk_found else 1


if __name__ == '__main__':
    raise SystemExit(main())
