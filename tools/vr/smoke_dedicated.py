#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Regression: dedicated E1L1 entry must not poll uninitialized CONTROL.

This tests startup/survival, not multiplayer gameplay. Uses a new disposable
-usecwd directory and reads the supplied owned GRP without modifying it.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

CONFIG = """[Setup]
ConfigVersion = 260
ForceSetup = 0
NoAutoLoad = 1
[Screen Setup]
ScreenMode = 0
ScreenWidth = 640
ScreenHeight = 480
ScreenBPP = 32
[Controls]
UseMouse = 0
UseJoystick = 0
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--port', default=24584, type=int)
    parser.add_argument('--seconds', default=8, type=int)
    args = parser.parse_args()
    binary, grp = args.binary.resolve(), args.grp.resolve()
    if not binary.is_file() or not grp.is_file():
        parser.error('binary and owned GRP must exist')
    if not 1 <= args.port <= 65535 or not 3 <= args.seconds <= 60:
        parser.error('port must be 1..65535 and seconds 3..60')
    args.work_dir.mkdir(parents=True, exist_ok=True)
    lab = Path(tempfile.mkdtemp(prefix='dedicated-', dir=args.work_dir.resolve()))
    (lab / 'eduke32.cfg').write_text(CONFIG)
    # Select this as main GRP, without loading unrelated loose World Tour CONs.
    (lab / 'DUKE3D.GRP').symlink_to(grp)
    env = dict(os.environ, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy')
    env.pop('EDUKE32_XR_DIAGNOSTIC_FRAMES', None)
    command = [str(binary), '-usecwd', '-nosetup', '-noautoload', '-dedicated',
               '-port', str(args.port), '-v1', '-l1', '-s1']
    log_path = lab / 'startup.log'
    with log_path.open('w') as log:
        process = subprocess.Popen(command, cwd=lab, env=env,
                                   stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline and process.poll() is None:
                time.sleep(0.1)
            alive = process.poll() is None
            output = log_path.read_text(errors='replace')
            passed = alive and 'Multiplayer server initialized.' in output and 'E1L1:' in output
            result = {'dedicated_startup_survived': passed,
                      'server_initialized': 'Multiplayer server initialized.' in output,
                      'level_loaded': 'E1L1:' in output, 'exit_before_cleanup': process.poll(),
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
