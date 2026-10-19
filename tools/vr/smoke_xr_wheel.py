#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""VR weapon wheel (play preset, private software XR).

Gives all weapons, then for each target: holds the right stick up to open the
wheel, turns the weapon hand toward the target slot (wrist rotation, slots
clockwise from the top), captures both eyes, releases the stick and checks
that the native weapon switched (including the Expander/Flamethrower toggles).
"""
import argparse, json, math, os, re, subprocess, tempfile, time
from pathlib import Path
from monado_remote import Remote
from smoke_aim import orientation
from smoke_world import CONFIG

HELD = re.compile(r'OpenXR held model: weapon=(\d+) ')
# Stock World Tour order (PLUTOPAK and WORLDTOUR): 11 slots.
SLOTS = [1, 2, 3, 4, 5, 6, 11, 7, 8, 9, 12]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, default=49777)
    parser.add_argument('--timeout', default=560, type=int)
    parser.add_argument('--targets', default='4,11,12,1')
    parser.add_argument('--env', action='append', default=[], help='extra KEY=VALUE for the game (debug)')
    parser.add_argument('--scale', help='EDUKE32_XR_TEST_WHEEL_SCALE (debug: enlarge wheel models)')
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    lab = Path(tempfile.mkdtemp(prefix='wheel-', dir=args.work_dir.resolve()))
    (lab / 'eduke32.cfg').write_text(CONFIG)
    (lab / 'DUKE3D.GRP').symlink_to(args.grp.resolve())
    capture, console = lab / 'capture-request', lab / 'console-request'
    env = dict(os.environ, DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy',
               EDUKE32_XR='play', EDUKE32_XR_TEST_HELD='1', EDUKE32_XR_TEST_WHEEL='1',
               EDUKE32_XR_CAPTURE_REQUEST=str(capture), EDUKE32_XR_CONSOLE_REQUEST=str(console),
               XDG_DATA_HOME=str(lab / 'data'))
    env.update(kv.split('=', 1) for kv in args.env)
    if args.scale:
        env['EDUKE32_XR_TEST_WHEEL_SCALE'] = args.scale
    launcher = Path(__file__).resolve().parents[2] / 'package/vr/eduke32-vr-play'
    command = [str(launcher), '--binary', str(args.binary.resolve()), '--',
               '-usecwd', '-nosetup', '-noautoload', '-nologo', '-v1', '-l1', '-s1']
    log_path = lab / 'game.log'
    text = lambda: log_path.read_text(errors='replace')
    deadline = time.monotonic() + args.timeout
    result = {'passed': False, 'targets': {}, 'evidence_directory': str(lab)}
    remote = None

    def wait(predicate, seconds=60):
        limit = min(deadline, time.monotonic() + seconds)
        while not predicate():
            if process.poll() is not None:
                raise RuntimeError('game exited')
            if time.monotonic() > limit:
                return False
            time.sleep(.05)
        return True

    with log_path.open('w') as log:
        process = subprocess.Popen(command, cwd=lab, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        try:
            if not wait(lambda: 'OpenXR world oracle: 60 frames' in text(), 300):
                raise RuntimeError('world did not start')
            remote = Remote(args.remote_port).__enter__()
            right = remote.packet.right
            right.pose.position.x, right.pose.position.y, right.pose.position.z = .2, 1.3, -.35
            right.pose.orientation = orientation(0, 0); remote.send()
            time.sleep(8)
            console.write_text('xr_weapons\n'); wait(lambda: not console.exists())
            time.sleep(2)
            for target in map(int, args.targets.split(',')):
                start = len(text())
                right.pose.orientation = orientation(0, 0)
                right.thumbstick.x, right.thumbstick.y = 0.0, 1.0; remote.send()
                opened = wait(lambda: 'OpenXR weapon wheel: open' in text()[start:], 20)
                order = re.findall(r'OpenXR weapon wheel: open slots=\d+ order=([\d,]+)\.', text()[start:])
                slots = list(map(int, order[-1].split(','))) if order else SLOTS
                result.setdefault('slots', slots)
                if target not in slots:
                    right.thumbstick.y = 0.0; remote.send(); time.sleep(1)
                    result['targets'][target] = dict(skipped_not_in_game=True)
                    continue
                angle = 2 * math.pi * slots.index(target) / len(slots)
                time.sleep(.6)
                right.pose.orientation = orientation(24 * math.sin(angle), 24 * math.cos(angle)); remote.send()
                hovered = wait(lambda: f'OpenXR weapon wheel: hover weapon={target}.' in text()[start:], 20)
                time.sleep(.5)
                capture.write_text(str(lab / f'wheel-{target}') + '\n'); wait(lambda: not capture.exists())
                right.thumbstick.y = 0.0; remote.send()
                right.pose.orientation = orientation(0, 0); remote.send()
                committed = wait(lambda: 'OpenXR weapon wheel: commit' in text()[start:], 20)
                switched = wait(lambda: any(int(w) == target for w in HELD.findall(text()[start:])), 20)
                time.sleep(1.5)
                result['targets'][target] = dict(opened=opened, hovered=hovered, committed=committed, switched=switched,
                                                 captured=(lab / f'wheel-{target}-left.ppm').is_file())
            result['checks'] = {f'weapon_{t}': all(v.values()) for t, v in result['targets'].items() if 'skipped_not_in_game' not in v}
            result['checks']['world_alive'] = 'OpenXR world stopped' not in text() and process.poll() is None
            result['passed'] = all(result['checks'].values())
        except RuntimeError as error:
            result['error'] = str(error)
        finally:
            if remote:
                remote.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
