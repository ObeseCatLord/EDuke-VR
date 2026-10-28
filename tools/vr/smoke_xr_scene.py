#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Scripted VR scene for visual checks (play preset, private software XR).

Run under software_xr_lab.py. Starts E1L1 (or --map) with the play preset and runs a JSON
step list against the Monado remote (a Valve Index pair), capturing both eyes where asked:

  [{"pose": {"right": [x, y, z, yaw, pitch, roll], "left": [...], "head": [...]}},
   {"buttons": {"right": {"trackpad_touch": 1}, "left": {"trigger_value": 1.0}}},
   {"console": "xr_weapons"}, {"wait": 2}, {"until": "regex", "timeout": 20},
   {"capture": "name"}]

Poses are metres in the LOCAL space (y up, -z forward) and degrees. Buttons are Hand fields of
monado_remote (a_click, b_click, thumbstick_click, trackpad_touch, trackpad_force, trigger_value,
squeeze_value, thumbstick=[x, y] ...); they stay set until changed. Prints a JSON result with
the capture paths; captures are <work>/<name>-left.ppm / -right.ppm.
"""
import argparse, json, math, os, re, subprocess, tempfile, time
from pathlib import Path
from monado_remote import Remote, Quat, Vec2
from smoke_world import CONFIG
from smoke_multiplayer import X11


def quat(yaw=0.0, pitch=0.0, roll=0.0):
    """Yaw about +Y (positive turns left), then pitch about +X (positive up), then roll about -Z."""
    y, p, r = (math.radians(a) / 2 for a in (yaw, pitch, roll))
    qy = (0.0, math.sin(y), 0.0, math.cos(y))
    qp = (math.sin(p), 0.0, 0.0, math.cos(p))
    qr = (0.0, 0.0, math.sin(r), math.cos(r))

    def mul(a, b):
        ax, ay, az, aw = a; bx, by, bz, bw = b
        return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)
    x, yy, z, w = mul(mul(qy, qp), qr)
    return Quat(x, yy, z, w)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--script', required=True, type=Path)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, default=49777)
    parser.add_argument('--timeout', default=560, type=int)
    parser.add_argument('--map', default='', help='user map instead of E1L1')
    parser.add_argument('--level', default='1,1', help='episode,level when no --map is given (default E1L1)')
    parser.add_argument('--env', action='append', default=[], help='extra KEY=VALUE for the game')
    parser.add_argument('--args', default='', help='extra EDuke32 arguments (space separated)')
    parser.add_argument('--pack', default='original-lowres', help='model pack (launcher --pack); "default": the game\'s own choice')
    args = parser.parse_args()
    steps = json.loads(args.script.read_text())
    args.work_dir.mkdir(parents=True, exist_ok=True)
    lab = Path(tempfile.mkdtemp(prefix='scene-', dir=args.work_dir.resolve()))
    (lab / 'eduke32.cfg').write_text(CONFIG)
    (lab / 'DUKE3D.GRP').symlink_to(args.grp.resolve())
    capture, console = lab / 'capture-request', lab / 'console-request'
    env = dict(os.environ, DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy',
               EDUKE32_XR='play', EDUKE32_XR_TEST_HELD='1',
               EDUKE32_XR_CAPTURE_REQUEST=str(capture), EDUKE32_XR_CONSOLE_REQUEST=str(console),
               XDG_DATA_HOME=str(lab / 'data'))
    env.update(kv.split('=', 1) for kv in args.env)
    launcher = Path(__file__).resolve().parents[2] / 'package/vr/eduke32-vr-play'
    if args.map and Path(args.map).is_file():
        # EDuke32 resolves user maps against its search path: copy into the lab directory.
        (lab / Path(args.map).name).write_bytes(Path(args.map).read_bytes())
        args.map = Path(args.map).name
    level = ['-map', args.map] if args.map else ['-v' + args.level.split(',')[0], '-l' + args.level.split(',')[1]]
    pack = [] if args.pack == 'default' else ['--pack', args.pack]
    command = [str(launcher), '--no-voxel-build', '--binary', str(args.binary.resolve()), *pack, '--',
               '-usecwd', '-noautoload', '-nologo', *level, '-s1', *args.args.split()]
    log_path = lab / 'game.log'
    text = lambda: log_path.read_text(errors='replace')
    deadline = time.monotonic() + args.timeout
    result = {'passed': False, 'captures': [], 'evidence_directory': str(lab)}
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

    x11 = X11(args.display)

    def game_window():
        # The launcher runs the game as a child (it relaunches it to switch model sets).
        pids, found = {process.pid}, True
        while found:
            found = False
            for entry in Path('/proc').iterdir():
                try:
                    if entry.name.isdigit() and int(entry.name) not in pids and \
                            int((entry / 'stat').read_text().rsplit(') ', 1)[1].split()[1]) in pids:
                        pids.add(int(entry.name)); found = True
                except (OSError, ValueError, IndexError):
                    pass
        for pid in pids:
            window, _ = x11.owned_window(pid)
            if window:
                return window
        return None

    with log_path.open('w') as log:
        process = subprocess.Popen(command, cwd=lab, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        try:
            if not wait(lambda: 'OpenXR world oracle: 60 frames' in text(), 300):
                raise RuntimeError('world did not start')
            remote = Remote(args.remote_port).__enter__()
            packet = remote.packet
            for side in ('left', 'right'):
                hand = getattr(packet, side)
                hand.pose.position.x, hand.pose.position.y, hand.pose.position.z = (-.2 if side == 'left' else .2), 1.3, -.35
                hand.pose.orientation = quat()
            remote.send()
            time.sleep(4)
            console_mark = None
            for step in steps:
                if 'pose' in step:
                    for name, value in step['pose'].items():
                        target = packet.head.center if name == 'head' else getattr(packet, name).pose
                        target.position.x, target.position.y, target.position.z = value[:3]
                        target.orientation = quat(*value[3:6])
                    remote.send()
                if 'buttons' in step:
                    for side, fields in step['buttons'].items():
                        hand = getattr(packet, side)
                        for field, value in fields.items():
                            if field in ('thumbstick', 'trackpad'):
                                setattr(hand, field, Vec2(*value))
                            elif field in ('linear_velocity', 'angular_velocity'):
                                vector = getattr(hand, field)
                                vector.x, vector.y, vector.z = value
                            else:
                                setattr(hand, field, type(getattr(hand, field))(value))
                    remote.send()
                if 'keys' in step:
                    # A following 'until' also sees what the keys logged at once.
                    console_mark = len(text())
                    # Keyboard input to the game's own window (menus), never the desktop.
                    window = game_window()
                    if not window:
                        raise RuntimeError('no game window for key input')
                    for key in step['keys']:
                        try:
                            x11.press(window, key, .08, True)
                        except RuntimeError:
                            # The window went away under the key (e.g. the game quit to relaunch).
                            break
                        time.sleep(.35)
                if 'console' in step:
                    # A following 'until' also sees what the command logged at once.
                    console_mark = len(text())
                    console.write_text(step['console'] + '\n'); wait(lambda: not console.exists(), 30)
                if 'wait' in step:
                    end = time.monotonic() + step['wait']
                    while time.monotonic() < end:
                        if process.poll() is not None:
                            raise RuntimeError('game exited')
                        remote.send(); time.sleep(.05)
                if 'until' in step:
                    start = 0 if step.get('from_start') else min(len(text()), console_mark if console_mark is not None else len(text()))
                    console_mark = None
                    ok = wait(lambda: re.search(step['until'], text()[start:]) is not None, step.get('timeout', 20))
                    result.setdefault('until', []).append({step['until']: ok})
                if 'capture' in step:
                    stem = lab / step['capture']
                    capture.write_text(str(stem) + '\n'); wait(lambda: not capture.exists(), 60)
                    # Both eyes written completely (sizes stop changing).
                    eyes = [Path(f'{stem}-{e}.ppm') for e in ('left', 'right')]
                    sizes = None
                    for _ in range(100):
                        now = [e.stat().st_size if e.is_file() else -1 for e in eyes]
                        if now == sizes and min(now) > 0:
                            break
                        sizes = now; time.sleep(.2)
                    result['captures'].append(str(stem) + '-left.ppm')
            result['alive'] = process.poll() is None and 'OpenXR world stopped' not in text()
            result['passed'] = result['alive'] and all(v for u in result.get('until', []) for v in u.values())
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
