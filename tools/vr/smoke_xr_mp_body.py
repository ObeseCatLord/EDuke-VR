#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Multiplayer third-person Duke + held weapon, and a networked physical throw.

Private two-client join on a dedicated server (all under software_xr_lab.py):
a flat peer and an XR peer launched through package/vr/eduke32-vr-play (play
preset). The XR player turns its head toward the flat player and captures
both eyes: the flat player must be drawn with the vr_duke model holding the
held pistol model (third-person attachment). Then the XR player picks up
pipebombs placed on its start, selects them with native Next_Weapon, and
throws one with a tracked swing; the server must spawn the native pipebomb.
"""
import argparse, json, math, os, re, struct, subprocess, tempfile, time
from pathlib import Path
from monado_remote import Remote
from smoke_actions import Observer
from smoke_aim import orientation
from smoke_multiplayer import X11, setup_lab
from stereo_fixture import PHEIGHT, sector, sprite
from smoke_hand_shots import wall

HEAVYHBOMB = 26
WHERE = re.compile(r'VR where: player=(\d+) local=(\d) pos=(-?\d+),(-?\d+),(-?\d+) ang=(-?\d+) weapon=(-?\d+) sprite=(-?\d+),(-?\d+),(-?\d+),(-?\d+)\.')
BOMB = re.compile(r'VR native pipebomb: player=(\d+) index=(\d+) origin=(-?\d+),(-?\d+),(-?\d+) sector=-?\d+ clamped=\d '
                  r'angle=(-?\d+) speed=(-?\d+) zvel=(-?\d+)')


def room():
    """Two open sectors; starts 768 units (2 m) apart."""
    a, b = bytearray(sector(0, 4)), bytearray(sector(4, 4))
    for s in (a, b):
        struct.pack_into('<i', s, 4, -32768)
    walls = [wall(0, 0, 1), wall(1152, 0, 2, nextwall=7, nextsector=1), wall(1152, 8192, 3), wall(0, 8192, 0),
             wall(1152, 0, 5), wall(8192, 0, 6), wall(8192, 8192, 7), wall(1152, 8192, 4, nextwall=1, nextsector=0)]
    starts = [sprite(512, 1024 + i*768, 0, 0, tile=1405, angle=0) for i in range(4)]
    # Joining players appear at the map start (1024,4096); bombs wait there.
    bombs = [sprite(1024 + dx, 4096, 0, 0, tile=HEAVYHBOMB, xrepeat=32, yrepeat=32) for dx in (0, 48)]
    sprites = starts + bombs
    return (struct.pack('<iiiihhh', 7, 1024, 4096, -PHEIGHT, 0, 0, 2) + a + b + struct.pack('<h', 8)
            + b''.join(walls) + struct.pack('<h', len(sprites)) + b''.join(sprites))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, default=49777)
    parser.add_argument('--port', type=int, default=24611)
    parser.add_argument('--timeout', type=int, default=500)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='mp-body-', dir=args.work_dir.resolve()))
    labs = {role: setup_lab(root, role, args.grp.resolve(), False) for role in ('server', 'peer1', 'xr')}
    for role, lab in labs.items():
        (lab / 'body.map').write_bytes(room())
        with (lab / 'eduke32.cfg').open('a') as f:
            f.write('\n[Comm Setup]\nPlayerName = "' + {'server': 'Server', 'peer1': 'Flat', 'xr': 'VR'}[role] + '"\n')
    base = {k: v for k, v in os.environ.items() if not k.startswith('EDUKE32_XR')}
    base.update(DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy')
    native = {k: v for k, v in base.items() if not k.startswith('XR_')}
    native.update(EDUKE32_XR_TEST_SHOTS='1')
    capture, console = labs['xr'] / 'capture-request', labs['xr'] / 'console-request'
    xr_env = dict(base, EDUKE32_XR='play', EDUKE32_XR_TEST_SHOTS='1', EDUKE32_XR_TEST_HELD='1', EDUKE32_XR_TEST_INPUT='1',
                  EDUKE32_XR_CAPTURE_REQUEST=str(capture), EDUKE32_XR_CONSOLE_REQUEST=str(console), XDG_DATA_HOME=str(labs['xr'] / 'data'))
    launcher = Path(__file__).resolve().parents[2] / 'package/vr/eduke32-vr-play'
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

    try:
        binary = str(args.binary.resolve())
        server, so = launch('server', [binary, *common, '-dedicated', '-port', str(args.port), '-c1', '-map', 'body.map'], native)
        until(so, lambda t: 'Multiplayer server initialized.' in t, 30)
        so.pause(8)
        x11 = X11(args.display)
        peer1, fo = launch('peer1', [binary, *common, '-connect', f'127.0.0.1:{args.port}'], native)
        until(fo, lambda t: 'Multiplayer client level synchronization complete.' in t, 60)
        fo.pause(2)
        window, _ = x11.owned_window(peer1.pid)
        if window:
            x11.press(window, 'Escape', .06, True)
        with Remote(args.remote_port) as remote:
            right, head = remote.packet.right, remote.packet.head
            right.pose.position.x, right.pose.position.y, right.pose.position.z = .2, 1.3, -.4
            remote.send()
            xr, co = launch('xr', [str(launcher), '--binary', binary, '--', *common, '-connect', f'127.0.0.1:{args.port}'], xr_env)
            until(co, lambda t: 'Multiplayer client level synchronization complete.' in t, 120)
            until(co, lambda t: 'OpenXR world oracle: 60 frames' in t, 240)
            co.pause(2)
            if re.findall(r'screen=(-?\d+)', co.text())[-1:] not in (['0'], []):
                window, _ = x11.owned_window(xr.pid)
                if window:
                    x11.press(window, 'Escape', .06, True)
            co.pause(3)
            # Turn the head toward the flat player (positions from the
            # read-only xr_where report; orientation() yaw is right-positive,
            # like Build angles) and capture.
            # Players share the map start; step the XR player aside with the
            # (networked) move stick first.
            remote.packet.left.thumbstick.x = .8; remote.send(); co.pause(.5)
            remote.packet.left.thumbstick.x = 0.; remote.send(); co.pause(1.5)
            start = len(co.text())
            console.write_text('xr_where\n')
            until(co, lambda t: len(WHERE.findall(t[start:])) >= 2, 60)
            rows = {int(m[0]): list(map(int, m)) for m in WHERE.findall(co.text()[start:])}
            me = next(r for r in rows.values() if r[1])
            flat = rows.get(1) if me[0] != 1 else rows.get(0)
            # Sprite positions are the replicated ones (fields 7..10).
            yaw = math.degrees(math.remainder(math.atan2(flat[8] - me[8], flat[7] - me[7]) - me[5]*math.pi/1024, 2*math.pi))
            result['where'] = {'me': me, 'flat': flat, 'yaw': round(yaw, 1),
                               'distance': round(math.hypot(flat[8] - me[8], flat[7] - me[7]))}
            for label, pitch in (('look', 0), ('look-down20', -20)):
                head.center.orientation = orientation(yaw, pitch); right.pose.orientation = orientation(yaw, pitch); remote.send()
                co.pause(3)
                capture.write_text(str(labs['xr'] / label) + '\n')
                until(co, lambda _: not capture.exists(), 90)
                co.pause(.5)
            result['attach'] = re.findall(r'Held weapon attach: [^\n]*', co.text())[:2]
            result['captured'] = (labs['xr'] / 'look-left.ppm').is_file()
            # Face forward again; select the picked-up pipebombs and throw.
            head.center.orientation = orientation(0, 0); right.pose.orientation = orientation(0, 0); remote.send()
            co.pause(1)
            for _ in range(4):
                if 'weapon=5 family' in co.text():
                    break
                remote.packet.left.b_click = True; remote.send(); co.pause(.4)
                remote.packet.left.b_click = False; remote.send(); co.pause(2.5)
            result['pipebomb_selected'] = 'weapon=5 family' in co.text()
            start_server, start_client = len(so.text()), len(co.text())
            right.trigger_value, right.trigger_click = 1.0, True
            right.linear_velocity.x = right.linear_velocity.y = right.linear_velocity.z = 0.0
            remote.send(); co.pause(1.0)
            right.linear_velocity.y, right.linear_velocity.z = 2.0, -7.0
            remote.send(); time.sleep(.06)
            right.trigger_value, right.trigger_click = 0.0, False
            remote.send(); time.sleep(.06)
            right.linear_velocity.y = right.linear_velocity.z = 0.0
            remote.send()
            try:
                until(so, lambda t: BOMB.search(t[start_server:]) is not None, 30)
            except RuntimeError:
                pass
            so.pause(1)
            result['server_bombs'] = [list(map(int, m)) for m in BOMB.findall(so.text()[start_server:])]
            result['client_samples'] = re.findall(r'VR physical throw sample: [^\n]*', co.text()[start_client:])[:3]
        result['checks'] = {
            'flat_player_model_has_weapon': any('ok=1' in line for line in result['attach']),
            'xr_capture': result['captured'],
            'pipebomb_selected': result['pipebomb_selected'],
            'server_spawned_thrown_bomb': len(result['server_bombs']) == 1 and result['server_bombs'][0][0] == 2,
            'all_alive': all(p.poll() is None for p in processes),
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
