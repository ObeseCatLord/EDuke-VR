#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read back 60 actual Duke-world XR frames using an already-running runtime.

Linux GLX/Nvidia was tested. Null Monado validates lifecycle and texture pixels,
not headset display/comfort. This does not qualify the final single-pass renderer,
CON compatibility, tracking motion, or multiplayer gameplay.
"""
import argparse
from collections import Counter
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import time

CONFIG = '''[Setup]
ConfigVersion = 348
ForceSetup = 0
NoAutoLoad = 1
[Screen Setup]
ScreenMode = 0
ScreenWidth = 960
ScreenHeight = 600
ScreenBPP = 32
Polymer = 0
[Sound Setup]
FXDevice = -1
MusicDevice = -1
[Controls]
UseMouse = 0
UseJoystick = 0
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--display', default=os.environ.get('DISPLAY'))
    parser.add_argument('--runtime-dir', type=Path)
    parser.add_argument('--timeout', default=30, type=int)
    parser.add_argument('--failure-stage', choices=('opaque', 'masks'))
    args = parser.parse_args()
    binary, grp = args.binary.resolve(), args.grp.resolve()
    if not binary.is_file() or not grp.is_file() or not args.display or not 5 <= args.timeout <= 120:
        parser.error('existing binary/owned GRP, a display and a 5..120 second timeout are required')
    args.work_dir.mkdir(parents=True, exist_ok=True)
    lab = Path(tempfile.mkdtemp(prefix='world-', dir=args.work_dir.resolve()))
    (lab/'eduke32.cfg').write_text(CONFIG)
    (lab/'DUKE3D.GRP').symlink_to(grp)
    prefix = lab/'stereo'
    env = dict(os.environ, DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy',
               EDUKE32_XR='1', EDUKE32_XR_WORLD_OUTPUT=str(prefix))
    env.pop('EDUKE32_XR_DIAGNOSTIC_FRAMES', None)
    env.pop('EDUKE32_XR_TEST_FAIL', None)
    if args.failure_stage:
        env['EDUKE32_XR_TEST_FAIL'] = args.failure_stage
    if args.runtime_dir:
        env['XDG_RUNTIME_DIR'] = str(args.runtime_dir.resolve())
    log_path = lab/'world.log'
    command = [str(binary), '-usecwd', '-nosetup', '-noautoload', '-v1', '-l1', '-s1']
    with log_path.open('w') as log:
        process = subprocess.Popen(command, cwd=lab, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic()+args.timeout
            while time.monotonic() < deadline and process.poll() is None:
                output = log_path.read_text(errors='replace')
                if args.failure_stage and output.count('XR failure test animation:') >= 10:
                    break
                if not args.failure_stage and 'OpenXR world oracle: 60 frames' in output:
                    break
                if ('OpenXR world stopped:' in output and not args.failure_stage) or 'OpenXR world initialization failed:' in output:
                    break
                time.sleep(.1)
            output = log_path.read_text(errors='replace')
            left, right = (lab/'stereo-left.ppm'), (lab/'stereo-right.ppm')
            captured = left.is_file() and right.is_file()
            distinct = captured and left.read_bytes() != right.read_bytes()
            passed = ('OpenXR world oracle: 60 frames' in output and 'E1L1:' in output
                      and distinct and process.poll() is None)
            if args.failure_stage:
                samples = re.findall(r'XR failure test animation: frame=(\d+) input=(\d+) duplicateOwners=(\d+)', output)
                per_frame = Counter(int(frame) for frame, _, _ in samples)
                passed = (process.poll() is None and len(samples) == 10
                          and 'OpenXR world stopped: injected failure' in output
                          and all(int(duplicates) == 0 for _, _, duplicates in samples)
                          and all(count <= (2 if frame == 0 else 1) for frame, count in per_frame.items()))
                result = {'failure_stage': args.failure_stage, 'failure_recovery_counts_passed': passed,
                          'animation_input_samples': len(samples), 'evidence_directory': str(lab)}
            else:
                result = {'world_stereo_60_frames': passed, 'eye_readbacks_distinct': distinct,
                      'world_renderer': 'two-pass oracle', 'headset_visual_test': 'not tested',
                      'multiplayer_gameplay': 'not tested', 'evidence_directory': str(lab)}
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
