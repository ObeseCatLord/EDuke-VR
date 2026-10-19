#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Immersive pipebomb throw and off-hand detonation (play preset, private software XR).

Selects the pipebomb, holds the right trigger, swings the right controller
(remote linear velocity), releases, and checks that the native pipebomb
spawns from the hand with a speed derived from the swing. A slow release
must not throw. Then the left trigger must detonate the live remote bomb.
"""
import argparse, json, os, re, subprocess, tempfile, time
from pathlib import Path
from monado_remote import Remote
from smoke_world import CONFIG

BOMB = re.compile(r'VR native pipebomb: player=\d+ index=(\d+) origin=(-?\d+),(-?\d+),(-?\d+) sector=-?\d+ clamped=\d '
                  r'angle=(-?\d+) speed=(-?\d+) zvel=(-?\d+)')
SAMPLE = re.compile(r'VR physical throw sample: speedUnits=(\d+) detonate=(\d)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, default=49777)
    parser.add_argument('--timeout', default=500, type=int)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    lab = Path(tempfile.mkdtemp(prefix='throw-', dir=args.work_dir.resolve()))
    (lab / 'eduke32.cfg').write_text(CONFIG)
    (lab / 'DUKE3D.GRP').symlink_to(args.grp.resolve())
    console = lab / 'console-request'
    env = dict(os.environ, DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy',
               EDUKE32_XR='play', EDUKE32_XR_TEST_SHOTS='1', EDUKE32_XR_TEST_HELD='1',
               EDUKE32_XR_CONSOLE_REQUEST=str(console), XDG_DATA_HOME=str(lab / 'data'))
    launcher = Path(__file__).resolve().parents[2] / 'package/vr/eduke32-vr-play'
    command = [str(launcher), '--binary', str(args.binary.resolve()), '--',
               '-usecwd', '-nosetup', '-noautoload', '-nologo', '-v1', '-l1', '-s1']
    log_path = lab / 'game.log'
    text = lambda: log_path.read_text(errors='replace')
    deadline = time.monotonic() + args.timeout
    result = {'passed': False, 'evidence_directory': str(lab)}
    remote = None

    def wait(predicate, what, seconds=60):
        limit = min(deadline, time.monotonic() + seconds)
        while not predicate():
            if process.poll() is not None:
                raise RuntimeError('game exited while waiting for ' + what)
            if time.monotonic() > limit:
                return False
            time.sleep(.05)
        return True

    def run(*lines):
        console.write_text('\n'.join(lines) + '\n')
        wait(lambda: not console.exists(), 'console request')

    with log_path.open('w') as log:
        process = subprocess.Popen(command, cwd=lab, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        try:
            if not wait(lambda: 'OpenXR world oracle: 60 frames' in text(), 'world', 300):
                raise RuntimeError('world did not start')
            remote = Remote(args.remote_port).__enter__()
            time.sleep(8)
            run('xr_weapons'); time.sleep(2)
            run('xr_weapon 5')
            wait(lambda: 'weapon=5 family' in text(), 'pipebomb in hand', 60)
            right = remote.packet.right

            def swing(speed):
                start = len(text())
                right.trigger_value, right.trigger_click = 1.0, True
                right.linear_velocity.x, right.linear_velocity.y, right.linear_velocity.z = 0.0, 0.0, 0.0
                remote.send(); time.sleep(1.0)
                # Forward (OpenXR -Z) and slightly up while still holding, then release.
                right.linear_velocity.y, right.linear_velocity.z = speed * .3, -speed
                remote.send(); time.sleep(.06)
                right.trigger_value, right.trigger_click = 0.0, False
                remote.send(); time.sleep(.06)
                right.linear_velocity.y = right.linear_velocity.z = 0.0
                remote.send()
                wait(lambda: BOMB.search(text()[start:]) is not None, 'pipebomb', 20)
                time.sleep(1.0)
                part = text()[start:]
                return {'bombs': [list(map(int, m)) for m in BOMB.findall(part)],
                        'samples': [list(map(int, m)) for m in SAMPLE.findall(part)]}

            slow = swing(0.3)
            fast = swing(7.0)
            result.update(slow=slow, fast=fast)
            start = len(text())
            left = remote.packet.left
            left.trigger_value, left.trigger_click = 1.0, True; remote.send(); time.sleep(.5)
            left.trigger_value, left.trigger_click = 0.0, False; remote.send()
            detonated = wait(lambda: 'VR off-hand detonation' in text()[start:], 'detonation', 20)
            result['detonation'] = detonated
            speed = fast['bombs'][0][5] if fast['bombs'] else 0
            result['checks'] = {
                'slow_release_does_not_throw': not slow['bombs'],
                'fast_swing_throws_one_bomb': len(fast['bombs']) == 1,
                'throw_speed_from_swing': 150 <= speed <= 500,
                'speed_sample_sent': any(s[0] > 0 for s in fast['samples']),
                'off_hand_detonates': detonated,
                'world_alive': 'OpenXR world stopped' not in text() and process.poll() is None,
            }
            result['passed'] = all(result['checks'].values())
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
