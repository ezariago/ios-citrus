#!/usr/bin/env python3
"""Stage a reviewable GPU userspace bundle; never modify an iOS root image."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT / 'out/citrus-gpu-userland'
    stage = out / 'staging'
    if stage.exists():
        shutil.rmtree(stage)
    files = {
        'citrus/lib/libOSMesa.8.dylib': ROOT / 'out/citrus-mesa/out/libOSMesa.8.dylib',
        'citrus/lib/libcitrus-gl.dylib': ROOT / 'out/citrus-eagl/libcitrus-gl.dylib',
        'citrus/lib/libcitrus-loader.dylib': ROOT / 'out/citrus-eagl/libcitrus-loader.dylib',
        'citrus/bin/citrus-triangle': ROOT / 'out/citrus-eagl/citrus-triangle',
        'citrus/bin/citrus-bbd-wrapper': ROOT / 'out/citrus-eagl/citrus-bbd-wrapper',
        # This is a candidate job, not installed under System/Library/LaunchDaemons.
        'citrus/tests/com.citrus.gpu-triangle.plist': ROOT / 'userland/gpu/com.citrus.gpu-triangle.plist',
    }
    mesa = json.loads((ROOT / 'out/citrus-mesa/manifest.json').read_text())
    eagl = json.loads((ROOT / 'out/citrus-eagl/manifest.json').read_text())
    if hashlib.sha256(files['citrus/lib/libOSMesa.8.dylib'].read_bytes()).hexdigest() != mesa['library_sha256']:
        raise SystemExit('Mesa library differs from build manifest')
    for rel, source in files.items():
        if source.name in eagl['outputs'] and hashlib.sha256(source.read_bytes()).hexdigest() != eagl['outputs'][source.name]:
            raise SystemExit('EAGL artifact differs from build manifest: ' + source.name)
        target = stage / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    manifest = {'hardware_tested': False, 'root_modified': False,
                'compositor_installed': False, 'mesa': mesa, 'eagl': eagl,
                'files': {rel: hashlib.sha256(path.read_bytes()).hexdigest() for rel, path in files.items()}}
    (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (stage / 'READ-ME-FIRST.txt').write_text(
        'UNTESTED CANDIDATE. No GPU acceleration has been demonstrated on Citrus.\n'
        '1. Collect device GPU firmware and pass the GPUCC/PAS probe.\n'
        '2. Build gpu=1 with that firmware; require 16 IB writes and fences.\n'
        '3. Install /citrus only into a backed-up test root, then run citrus-triangle.\n'
        '4. Require Adreno 610, GL readback and shared IOSurface readback to pass.\n'
        '5. Only then consider the preserved-backboardd wrapper and citrusgl=1.\n'
        'The wrapper is staged in /citrus/bin; no system daemon is replaced.\n'
        'Keep a gpu=0 citrusgl=0 fallback boot and the original root/backboardd.\n')
    archive = out / 'citrus-gpu-userland-candidate.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(stage.rglob('*')):
            if path.is_file():
                bundle.write(path, path.relative_to(stage))
    print(str(archive) + '\nsha256 ' + hashlib.sha256(archive.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
