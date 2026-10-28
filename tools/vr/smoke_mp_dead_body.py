#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Multiplayer: how a VR player's body looks to others when that player dies.

Private dedicated server, a desktop peer and a VR peer (both with the model set under test). The
VR player walks off, the desktop player turns to face it, then the VR player dies (the server's net_kill). The
desktop peer captures its flat view at intervals while the corpse settles and logs that player's
sprite (picnum, z against the floor) each time, so a body sinking into or bouncing through the
ground shows in both the pictures and the numbers.

Run inside tools/vr/software_xr_lab.py.
"""
import argparse, json, math, os, re, tempfile, time
from pathlib import Path
from monado_remote import Remote
from smoke_multiplayer import X11, setup_lab
from smoke_mp_desktop_body import LAUNCHER, WHERE, room
from smoke_desktop import children_of
from smoke_actions import Observer
import subprocess

SPRITE = re.compile(r'VR where sprite: player=(\d+) index=(-?\d+) picnum=(-?\d+) cstat=(-?\d+) xrepeat=(-?\d+) extra=(-?\d+) dead=(\d+) floorz=(-?\d+)\.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, default=49777)
    parser.add_argument('--port', type=int, default=24617)
    parser.add_argument('--timeout', type=int, default=540)
    parser.add_argument('--pack', default='voxel')
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='mp-dead-body-', dir=args.work_dir.resolve()))
    labs = {role: setup_lab(root, role, args.grp.resolve(), False) for role in ('server', 'desktop', 'xr')}
    for role, lab in labs.items():
        (lab / 'body.map').write_bytes(room())
        # Synthetic key events cannot carry the Ctrl modifier the default Fire key needs: fire on F.
        (lab / 'settings.cfg').write_text('bind "F" "gamefunc_Fire"\n')
        with (lab / 'eduke32.cfg').open('a') as f:
            f.write('\n[Comm Setup]\nPlayerName = "' + {'server': 'Server', 'desktop': 'Desk', 'xr': 'VR'}[role] + '"\n')
    base = {k: v for k, v in os.environ.items() if not k.startswith('EDUKE32_XR')}
    base.update(DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy')
    native = {k: v for k, v in base.items() if not k.startswith('XR_')}
    flat_capture, desk_console = labs['desktop'] / 'capture-request', labs['desktop'] / 'console-request'
    desktop_env = dict(native, XDG_DATA_HOME=str(labs['desktop'] / 'data'), XDG_CONFIG_HOME=str(labs['desktop'] / 'config'),
                       EDUKE32_TEST_FLAT_CAPTURE=str(flat_capture), EDUKE32_XR_CONSOLE_REQUEST=str(desk_console),
                       EDUKE32_XR_TEST_DEAD='1')
    console = labs['xr'] / 'console-request'
    xr_env = dict(base, EDUKE32_XR='play', XDG_DATA_HOME=str(labs['xr'] / 'data'), XDG_CONFIG_HOME=str(labs['xr'] / 'config'),
                  EDUKE32_XR_FINGER_TRACKING='0', EDUKE32_XR_CONSOLE_REQUEST=str(console))
    common = ['-usecwd', '-nosetup', '-noautoload', '-nologo', '-ns', '-nm']
    processes, logs = [], []
    deadline = time.monotonic() + args.timeout
    result = {'passed': False, 'evidence_directory': str(root), 'samples': []}

    def launch(role, command, env):
        log = (labs[role] / 'game.log').open('w'); logs.append(log)
        # The dedicated server reads console commands (net_kill) from stdin.
        process = subprocess.Popen(command, cwd=labs[role], env=env, stdin=subprocess.PIPE if role == 'server' else subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT)
        processes.append(process)
        return process, Observer(process, labs[role] / 'game.log')

    def until(observer, predicate, seconds):
        observer.wait(predicate, timeout=max(1, min(seconds, deadline - time.monotonic())))

    def where(observer, request):
        start = len(observer.text())
        request.write_text('xr_where\n')
        until(observer, lambda t: len(SPRITE.findall(t[start:])) >= 2, 30)
        text = observer.text()[start:]
        return {int(m[0]): list(map(int, m)) for m in WHERE.findall(text)}, {int(m[0]): list(map(int, m)) for m in SPRITE.findall(text)}

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
            xr, co = launch('xr', [str(LAUNCHER), '--no-voxel-build', '--pack', args.pack, '--binary', binary,
                                   '--', *common, '-connect', f'127.0.0.1:{args.port}'], xr_env)
            until(co, lambda t: 'Multiplayer client level synchronization complete.' in t, 180)
            until(co, lambda t: 'OpenXR world oracle: 60 frames' in t, 240)
            co.pause(3)
            remote.packet.left.thumbstick.y = .7; remote.send(); co.pause(.45)   # about 1.5 m
            remote.packet.left.thumbstick.y = 0.; remote.send(); co.pause(2)
            window, _ = x11.owned_window(next(iter(children_of(desk.pid)), desk.pid))
            for attempt in range(12):
                rows, _ = where(co, console)
                me = next(r for r in rows.values() if r[1])
                desk_row = min((r for r in rows.values() if not r[1] and r[0] != 0), key=lambda r: r[0])
                bearing = math.atan2(me[8] - desk_row[8], me[7] - desk_row[7])
                error = math.degrees(math.remainder(bearing - desk_row[5]*math.pi/1024, 2*math.pi))
                if abs(error) < 6 or window is None:
                    break
                x11.press(window, 'Right' if error > 0 else 'Left', min(.6, abs(error)/180.), True)
                do.pause(.8)
            vr_player = me[0]
            # Alive, then shot dead by the desktop player (a weapon kill: thrown back, a body and,
            # after the respawn, a corpse left behind).
            server.stdin.write(b'net_giveall\n'); server.stdin.flush()
            do.pause(1.)
            x11.press(window, '3', .1, True)    # shotgun
            do.pause(1.5)

            def sample(label):
                path = labs['desktop'] / f'{label}.ppm'
                flat_capture.write_text(str(path))
                until(do, lambda t: f'Flat capture: {path}' in t, 60)
                rows, sprites = where(do, desk_console)
                row = sprites.get(vr_player)
                where_row = rows.get(vr_player, [None]*11)
                result['samples'].append({'label': label, 'capture': str(path), 'z': where_row[9], 'ang': where_row[10],
                                          'sprite': row and dict(zip(('player', 'index', 'picnum', 'cstat', 'xrepeat', 'extra', 'dead', 'floorz'), row))})
                return row

            sample('alive')
            shots = 0
            for shots in range(1, 16):
                x11.press(window, 'f', .15, True)
                do.pause(1.)
                _, sprites = where(do, desk_console)
                row = sprites.get(vr_player)
                if row and (row[5] <= 0 or row[6]):
                    break
            result['shots'] = shots
            started = time.monotonic()
            for at in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0):
                while time.monotonic() - started < at:
                    time.sleep(.05)
                sample(f'dead-{at}')
            # Respawn (Open is the left grip in VR): the corpse stays behind as DUKELYINGDEAD.
            remote.packet.left.squeeze_value = 1.; remote.packet.left.squeeze_force = 1.; remote.send(); co.pause(.6)
            remote.packet.left.squeeze_value = 0.; remote.packet.left.squeeze_force = 0.; remote.send()
            for label, wait in (('respawned-1', 1.), ('respawned-2', 1.), ('respawned-4', 2.), ('respawned-6', 2.)):
                do.pause(wait)
                path = labs['desktop'] / f'{label}.ppm'
                flat_capture.write_text(str(path))
                until(do, lambda t: f'Flat capture: {path}' in t, 60)
                start = len(do.text())
                desk_console.write_text('xr_where\n')
                until(do, lambda t: 'VR where sprite' in t[start:], 30)
                do.pause(.3)
                corpses = re.findall(r'VR where corpse: [^\n]*', do.text()[start:])
                result['samples'].append({'label': label, 'capture': str(path), 'corpses': corpses})
        result['passed'] = all(s.get('sprite') or s.get('corpses') is not None for s in result['samples'])
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
