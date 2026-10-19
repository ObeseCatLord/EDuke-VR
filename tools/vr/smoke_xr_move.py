#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Comfort locomotion check in the private software-XR lab (play preset).

Turns the simulated head, pushes the left stick forward and measures the
player's native displacement direction; then flicks the right stick for a
snap turn. Single player E1L1 through package/vr/eduke32-vr-play.
"""
import argparse, json, math, os, re, subprocess, tempfile, time
from pathlib import Path
from monado_remote import Remote
from smoke_world import CONFIG
from smoke_xr_pitch import orientation

MOVE = re.compile(r'OpenXR move: native=([-\d.]+) move=([-\d.]+) pos=(-?\d+),(-?\d+),(-?\d+)\.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, default=49777)
    parser.add_argument('--timeout', default=400, type=int)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    lab = Path(tempfile.mkdtemp(prefix='move-', dir=args.work_dir.resolve()))
    (lab / 'eduke32.cfg').write_text(CONFIG)
    (lab / 'DUKE3D.GRP').symlink_to(args.grp.resolve())
    env = dict(os.environ, DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy',
               EDUKE32_XR='play', EDUKE32_XR_TEST_MOVE='1', EDUKE32_XR_SNAP_TURN='45',
               XDG_DATA_HOME=str(lab / 'data'))
    launcher = Path(__file__).resolve().parents[2] / 'package/vr/eduke32-vr-play'
    command = [str(launcher), '--binary', str(args.binary.resolve()), '--',
               '-usecwd', '-nosetup', '-noautoload', '-nologo', '-v1', '-l1', '-s1']
    log_path = lab / 'game.log'
    text = lambda: log_path.read_text(errors='replace')
    samples = lambda start=0: [tuple(map(float, m)) for m in MOVE.findall(text()[start:])]
    result = {'passed': False, 'evidence_directory': str(lab)}
    deadline = time.monotonic() + args.timeout
    remote = None
    with log_path.open('w') as log:
        process = subprocess.Popen(command, cwd=lab, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        try:
            while 'OpenXR world oracle: 60 frames' not in text():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('world did not start')
                time.sleep(.2)
            remote = Remote(args.remote_port).__enter__()
            time.sleep(1)

            def ticks(count, start=None):
                # Wait for game ticks (logged every 2), robust to host load.
                start = len(text()) if start is None else start
                while len(samples(start)) < count:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('game ticks stalled')
                    time.sleep(.1)
                return start

            def walk(head_yaw):
                remote.packet.head.center.orientation = orientation(head_yaw, 0, 0)
                remote.send(); ticks(8)
                start = len(text())
                remote.packet.left.thumbstick.y = 1.0; remote.send(); ticks(20, start)
                remote.packet.left.thumbstick.y = 0.0; remote.send(); ticks(30, start)
                rows = samples(start)
                (n0, m0, x0, y0, _), (n1, m1, x1, y1, _) = rows[0], rows[-1]
                # First displacement step: later steps may slide along walls.
                step = next(((b[2] - a[2], b[3] - a[3]) for a, b in zip(rows, rows[1:])
                             if math.hypot(b[2] - a[2], b[3] - a[3]) > 20), (x1 - x0, y1 - y0))
                heading = math.degrees(math.atan2(step[1], step[0]))  # Build angle: 0=east, +y south
                build = (m1 * 360 / 2048) % 360
                error = (heading - build + 180) % 360 - 180
                return {'head_yaw': head_yaw, 'native_angle': n1, 'move_angle': m1,
                        'distance': math.hypot(x1 - x0, y1 - y0), 'heading_deg': heading,
                        'move_angle_deg': build, 'heading_error_deg': error}

            straight = walk(0)
            turned = walk(90)   # OpenXR +yaw turns the head left
            start = len(text())
            before = samples()[-1][0]
            remote.packet.right.thumbstick.x = 1.0; remote.send(); ticks(5, start)
            remote.packet.right.thumbstick.x = 0.0; remote.send(); ticks(15, start)
            after = samples(start)[-1][0]
            snap = ((after - before) * 360 / 2048 + 180) % 360 - 180
            result.update(straight=straight, turned=turned, snap_turn_deg=snap)
            delta = (turned['move_angle_deg'] - straight['move_angle_deg'] + 180) % 360 - 180
            result['move_rotation_with_head_deg'] = delta
            result['checks'] = {
                'walks_forward': straight['distance'] > 200 and abs(straight['heading_error_deg']) < 10,
                'turned_walk_follows_move_angle': turned['distance'] > 200 and abs(turned['heading_error_deg']) < 10,
                'move_angle_follows_head_90': abs(abs(delta) - 90) < 5,
                'snap_turn_45': abs(abs(snap) - 45) < 3,
                'world_alive': 'OpenXR world stopped' not in text() and process.poll() is None,
            }
            result['passed'] = all(result['checks'].values())
        finally:
            if remote:
                remote.close()
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
