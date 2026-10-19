#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Capture native flat Polymost frame 12 of a map (no XR) as a visual reference."""
import argparse, os, subprocess, tempfile, time
from pathlib import Path
from smoke_world import CONFIG

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', required=True, type=Path)
parser.add_argument('--grp', required=True, type=Path)
parser.add_argument('--map', required=True, type=Path)
parser.add_argument('--work-dir', required=True, type=Path)
parser.add_argument('--display', default=':105')
args = parser.parse_args()
args.work_dir.mkdir(parents=True, exist_ok=True)
lab = Path(tempfile.mkdtemp(prefix='native-', dir=args.work_dir.resolve()))
(lab / 'eduke32.cfg').write_text(CONFIG)
(lab / 'DUKE3D.GRP').symlink_to(args.grp.resolve())
(lab / args.map.name).write_bytes(args.map.read_bytes())
env = {k: v for k, v in os.environ.items() if not k.startswith('EDUKE32_XR')}
env.update(DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy',
           EDUKE32_XR_TEST_CAPTURE=str(lab / 'flat'))
log = lab / 'game.log'
with log.open('w') as out:
    p = subprocess.Popen([str(args.binary.resolve()), '-usecwd', '-nosetup', '-noautoload', '-map', args.map.name, '-s1'],
                         cwd=lab, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline and 'XR native reference captured' not in log.read_text(errors='replace'):
        if p.poll() is not None:
            break
        time.sleep(.2)
    p.terminate()
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()
print(lab / 'flat-native.ppm', (lab / 'flat-native.ppm').is_file())
