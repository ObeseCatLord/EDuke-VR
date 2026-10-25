#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Multiplayer: a desktop player sees a VR player's networked full body (VRIK).

Private dedicated server, a desktop peer (eduke32-vr-play --desktop with a model set that has
the IK body) and a VR peer (eduke32-vr-play, play preset) on two starts facing each other. The VR
peer raises its hands; the desktop peer must draw the VR player's IK body from the received poses
(its own native player sprite hidden) and captures its flat view for inspection.

Run inside tools/vr/software_xr_lab.py.
"""
import argparse, json, math, os, re, struct, subprocess, tempfile, time
from pathlib import Path
from monado_remote import Remote
from smoke_actions import Observer
from smoke_multiplayer import X11, setup_lab
from stereo_fixture import PHEIGHT, sector, sprite
from smoke_hand_shots import wall
from smoke_desktop import children_of

WHERE = re.compile(r'VR where: player=(\d+) local=(\d) pos=(-?\d+),(-?\d+),(-?\d+) ang=(-?\d+) weapon=(-?\d+) sprite=(-?\d+),(-?\d+),(-?\d+),(-?\d+)\.')

LAUNCHER = Path(__file__).resolve().parents[2] / 'package/vr/eduke32-vr-play'


def room():
    """One open room; two starts 1536 units (4 m) apart facing each other."""
    a = bytearray(sector(0, 4))
    struct.pack_into('<i', a, 4, -32768)
    walls = [wall(0, 0, 1), wall(8192, 0, 2), wall(8192, 8192, 3), wall(0, 8192, 0)]
    starts = [sprite(2048, 4096, 0, 0, tile=1405, angle=0), sprite(3584, 4096, 0, 0, tile=1405, angle=1024)]
    return (struct.pack('<iiiihhh', 7, 2048, 4096, -PHEIGHT, 0, 0, 1) + a + struct.pack('<h', 4)
            + b''.join(walls) + struct.pack('<h', len(starts)) + b''.join(starts))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, default=49777)
    parser.add_argument('--port', type=int, default=24613)
    parser.add_argument('--timeout', type=int, default=520)
    parser.add_argument('--pack', default='original-lowres', help='model set for both players (needs the IK body)')
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='mp-desktop-body-', dir=args.work_dir.resolve()))
    labs = {role: setup_lab(root, role, args.grp.resolve(), False) for role in ('server', 'desktop', 'xr')}
    for role, lab in labs.items():
        (lab / 'body.map').write_bytes(room())
        with (lab / 'eduke32.cfg').open('a') as f:
            f.write('\n[Comm Setup]\nPlayerName = "' + {'server': 'Server', 'desktop': 'Desk', 'xr': 'VR'}[role] + '"\n')
    base = {k: v for k, v in os.environ.items() if not k.startswith('EDUKE32_XR')}
    base.update(DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy')
    native = {k: v for k, v in base.items() if not k.startswith('XR_')}
    flat_capture = labs['desktop'] / 'capture-request'
    desktop_env = dict(native, XDG_DATA_HOME=str(labs['desktop'] / 'data'), XDG_CONFIG_HOME=str(labs['desktop'] / 'config'),
                       EDUKE32_TEST_FLAT_CAPTURE=str(flat_capture), EDUKE32_XR_TEST_BODY_POSES='1')
    console = labs['xr'] / 'console-request'
    xr_env = dict(base, EDUKE32_XR='play', XDG_DATA_HOME=str(labs['xr'] / 'data'), XDG_CONFIG_HOME=str(labs['xr'] / 'config'),
                  EDUKE32_XR_FINGER_TRACKING='0', EDUKE32_XR_CONSOLE_REQUEST=str(console))
    common = ['-usecwd', '-nosetup', '-noautoload', '-nologo', '-ns', '-nm']
    processes, logs = [], []
    deadline = time.monotonic() + args.timeout
    result = {'passed': False, 'evidence_directory': str(root)}

    def launch(role, command, env):
        log = (labs[role] / 'game.log').open('w'); logs.append(log)
        process = subprocess.Popen(command, cwd=labs[role], env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        processes.append(process)
        return process, Observer(process, labs[role] / 'game.log')

    def until(observer, predicate, seconds):
        observer.wait(predicate, timeout=max(1, min(seconds, deadline - time.monotonic())))

    def flat_shot(observer, name):
        path = labs['desktop'] / f'{name}.ppm'
        flat_capture.write_text(str(path))
        until(observer, lambda t: f'Flat capture: {path}' in t, 60)
        return path

    try:
        binary = str(args.binary.resolve())
        server, so = launch('server', [binary, *common, '-dedicated', '-port', str(args.port), '-c1', '-map', 'body.map'], native)
        until(so, lambda t: 'Multiplayer server initialized.' in t, 30)
        so.pause(8)
        x11 = X11(args.display)
        desk, do = launch('desktop', [str(LAUNCHER), '--desktop', '--no-voxel-build', '--pack', args.pack, '--binary', binary,
                                      '--', *common, '-connect', f'127.0.0.1:{args.port}'], desktop_env)
        until(do, lambda t: 'Multiplayer client level synchronization complete.' in t, 120)
        do.pause(2)
        with Remote(args.remote_port) as remote:
            left, right = remote.packet.left, remote.packet.right
            left.pose.position.x, left.pose.position.y, left.pose.position.z = -.3, 1.5, -.3
            right.pose.position.x, right.pose.position.y, right.pose.position.z = .35, 1.7, -.25
            remote.send()
            xr, co = launch('xr', [str(LAUNCHER), '--no-voxel-build', '--pack', args.pack, '--binary', binary,
                                   '--', *common, '-connect', f'127.0.0.1:{args.port}'], xr_env)
            until(co, lambda t: 'Multiplayer client level synchronization complete.' in t, 180)
            until(co, lambda t: 'OpenXR world oracle: 60 frames' in t, 240)
            co.pause(3)
            # Players may share a start: the VR player walks off a few metres first (networked stick).
            remote.packet.left.thumbstick.y = .7; remote.send(); co.pause(1.2)
            remote.packet.left.thumbstick.y = 0.; remote.send(); co.pause(2)
            # Turn the desktop player toward the VR player (positions and angles from the VR peer's
            # read-only xr_where report; the desktop window gets arrow-key events, no desktop focus).
            window, _ = x11.owned_window(next(iter(children_of(desk.pid)), desk.pid))
            turns = []
            for attempt in range(12):
                start = len(co.text())
                console.write_text('xr_where\n')
                until(co, lambda t: len(WHERE.findall(t[start:])) >= 2, 30)
                rows = {int(m[0]): list(map(int, m)) for m in WHERE.findall(co.text()[start:])}
                me = next(r for r in rows.values() if r[1])          # the VR player
                # The dedicated server holds player 0; the desktop peer joined first after it.
                desk_row = min((r for r in rows.values() if not r[1] and r[0] != 0), key=lambda r: r[0])
                bearing = math.atan2(me[8] - desk_row[8], me[7] - desk_row[7])
                error = math.degrees(math.remainder(bearing - desk_row[5]*math.pi/1024, 2*math.pi))
                turns.append(round(error, 1))
                if abs(error) < 6 or window is None:
                    break
                x11.press(window, 'Right' if error > 0 else 'Left', min(.6, abs(error)/180.), True)
                do.pause(.8)
            result['turn_errors_deg'] = turns
            result['distance'] = round(math.hypot(me[8] - desk_row[8], me[7] - desk_row[7]))
            result['players'] = {'vr': me[0], 'desktop': desk_row[0]}
            # The desktop player sees the VR player's body (received poses, drawn in the flat view).
            until(do, lambda t: re.search(r'VR desktop bodies: models=\d+ drawn=[1-9]', t) is not None, 90)
            do.pause(2)
            shot = flat_shot(do, 'desktop-view')
            result['desktop_view'] = str(shot)
            result['remote_body_logs'] = re.findall(r'VR remote body: [^\n]*', do.text())[-2:]
            result['desktop_body_logs'] = re.findall(r'VR desktop bodies: [^\n]*', do.text())[-2:]
        result['checks'] = {
            'desktop draws the VR body': bool(result['desktop_body_logs']),
            'desktop has no OpenXR session': 'OpenXR world' not in do.text(),
            'desktop view captured': Path(result['desktop_view']).is_file(),
            'desktop faces the VR player': abs(result['turn_errors_deg'][-1]) < 10,
            'players apart (body in view)': result['distance'] > 300,
            'all alive': all(p.poll() is None for p in processes),
        }
        result['passed'] = all(result['checks'].values())
    except RuntimeError as error:
        result['error'] = str(error)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
        for log in logs:
            log.close()
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
