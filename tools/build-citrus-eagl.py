#!/usr/bin/env python3
"""Build candidate EAGL libraries; never install or inject them into iOS.

The recovered dispatch table targets iOS 16.5 and requires independent 16.7.16
ABI validation. These artifacts are compile candidates, not a working renderer.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT / 'out/citrus-eagl'
    out.mkdir(parents=True, exist_ok=True)
    reference = ROOT / 'userland/gpu/reference'
    gpu = ROOT / 'upstream/ios-topaz/userland/gpu'
    mesa = ROOT / 'out/citrus-mesa/out'
    with (out / 'eagl_gen.h').open('w') as header:
        subprocess.run([sys.executable, str(reference / 'mkeagl.py'),
                        str(reference / 'eagl_slots-ios16.5.txt'), str(mesa / 'gl.xml'),
                        str(mesa / 'exported-gl.txt'), str(gpu / 'eagl.c')], stdout=header, check=True)
    sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
    command = ['xcrun', '--sdk', 'iphoneos', 'clang', '-target', 'arm64-apple-ios16.0',
               '-isysroot', sdk, '-O2', '-I' + str(out), '-I' + str(gpu), '-Wno-deprecated-declarations']
    builds = [
        ('libcitrus-gl.dylib', ['-dynamiclib', '-install_name', '/citrus/lib/libcitrus-gl.dylib',
                              '-framework', 'CoreFoundation', '-framework', 'IOKit', '-framework', 'IOSurface',
                              '-lobjc', str(mesa / 'libOSMesa.8.dylib'), str(gpu / 'eagl.c'), str(gpu / 'gl_osmesa.c')]),
        ('libcitrus-loader.dylib', ['-dynamiclib', '-install_name', '/citrus/lib/libcitrus-loader.dylib',
                                  str(ROOT / 'userland/gpu/citrus-loader.c'),
                                  '-framework', 'CoreFoundation', '-framework', 'IOKit']),
        ('citrus-bbd-wrapper', [str(ROOT / 'userland/gpu/citrus-bbd-wrapper.c')]),
    ]
    triangle = ROOT / 'userland/gpu/citrus-triangle.c'
    if triangle.exists():
        builds.append(('citrus-triangle', [str(triangle), str(gpu / 'gl_osmesa.c'),
                       str(mesa / 'libOSMesa.8.dylib'), '-framework', 'CoreFoundation',
                       '-framework', 'IOKit', '-framework', 'IOSurface']))
    report_path = out / 'dispatch-check.json'
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    slots_sha = hashlib.sha256((reference / 'eagl_slots-ios16.5.txt').read_bytes()).hexdigest()
    offsets_match = report.get('system_build') == '20H392' and report.get('static_offsets_all_match') and report.get('slots_sha256') == slots_sha
    manifest = {'target': 'arm64-apple-ios16.0', 'hardware_tested': False, 'runtime_abi_verified': False,
                'dispatch_offsets_verified_for_20H392': bool(offsets_match), 'outputs': {}}
    for name, args in builds:
        invocation = command + args + ['-o', str(out / name)]
        (out / (name + '.command.json')).write_text(json.dumps(invocation, indent=2) + '\n')
        result = subprocess.run(invocation, capture_output=True, text=True)
        (out / (name + '.log')).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise SystemExit(result.stderr[-5000:])
        # SWEET validates a code signature on exec and dylib load and marks
        # root-filesystem binaries as platform binaries; an ad-hoc signature is
        # the minimum blob that path accepts. Sign after linking so the recorded
        # hash is the installable artifact.
        sign = subprocess.run(['codesign', '--force', '--sign', '-', '--timestamp=none', str(out / name)],
                              capture_output=True, text=True)
        (out / (name + '.codesign.log')).write_text(sign.stdout + sign.stderr)
        if sign.returncode:
            raise SystemExit('codesign failed for ' + name + ': ' + sign.stderr[-2000:])
        manifest['outputs'][name] = hashlib.sha256((out / name).read_bytes()).hexdigest()
        print('Linked and ad-hoc signed ' + str(out / name))
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
