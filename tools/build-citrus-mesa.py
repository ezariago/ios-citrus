#!/usr/bin/env python3
"""Build the pinned Topaz Mesa/Redwood bridge for arm64 iOS in out/citrus-mesa.

Correct the upstream script's stale directory layout without editing upstream.
Does not install libraries on the phone or alter any root image.
"""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'out/citrus-mesa'
UPSTREAM = ROOT / 'upstream/ios-topaz/userland/mesa'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    venv = OUT / 'venv'
    if not (venv / 'bin/python3').exists():
        subprocess.run(['python3', '-m', 'venv', str(venv)], check=True)
    subprocess.run([str(venv / 'bin/python3'), '-m', 'pip', 'install',
                    'meson==1.7.2', 'ninja==1.11.1.4', 'mako==1.3.10',
                    'PyYAML==6.0.2', 'packaging==25.0'], check=True)
    script = (UPSTREAM / 'mk-mesa-mac.sh').read_text()
    script = script.replace('set -e', 'set -euo pipefail', 1)
    script = script.replace('ROOT=$(cd "$(dirname "$0")" && pwd)', 'ROOT=' + str(UPSTREAM))
    script = script.replace('B=$ROOT/build-mesa', 'B=' + str(OUT))
    script = script.replace('"$ROOT"/mesa/', '"$ROOT"/')
    script = script.replace('"$ROOT/mesa/redwood-drm"', '"$ROOT/redwood-drm"')
    script = script.replace('ninja -C $BUILD > ninja.log',
                            'meson setup --reconfigure --clearcache $BUILD mesa-$VERSION > meson-reconfigure.log\nninja -C $BUILD > ninja.log')
    # Use a separate prefix so the candidate cannot replace the running stack.
    script = script.replace('/topaz', '/citrus')
    generated = OUT / 'build.sh'
    generated.write_text(script)
    sources = [UPSTREAM / 'mk-mesa-mac.sh', *sorted(UPSTREAM.glob('*.patch')),
               *sorted((UPSTREAM / 'redwood-drm').glob('*'))]
    manifest = {'target': 'arm64-apple-ios16.0', 'mesa': '25.0.7',
                'hardware_tested': False,
                'inputs': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    subprocess.run(['bash', str(generated)], cwd=OUT, check=True)
    library = OUT / 'out/libOSMesa.8.dylib'
    # SWEET's AMFI path validates signatures on dylib load; ad-hoc is sufficient
    # on a root-filesystem binary and keeps the install self-contained.
    subprocess.run(['codesign', '--force', '--sign', '-', '--timestamp=none', str(library)], check=True)
    manifest['library_sha256'] = hashlib.sha256(library.read_bytes()).hexdigest()
    manifest['library_signed'] = 'adhoc'
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
