#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Native co-op with a VR player: two clients on a dedicated co-op server.

Run under software_xr_lab.py. A dedicated `-c2` (Cooperative Play) server
runs a two-level episode (`definelevelname` first.map/second.map, co-op
starts with lotag 1, sector 1 of the first map is a native end-of-level
exit). A flat client and an XR client (package/vr/eduke32-vr-play, play
preset) join. Checks, all through native game paths:

- both clients join and play as distinct co-op players at co-op starts;
- the XR player sees its teammate drawn as vr_duke holding his weapon;
- a VR hand shot (pistol) is resolved natively by the server;
- a VR swing throw spawns the native pipebomb on the server;
- walking (head-relative stick) through the exit takes the whole co-op
  game to level 2, with the XR session and held weapon still running and a
  second VR shot resolved on the new level.
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
WHERE = re.compile(r'VR where: player=(\d+) local=(\d) pos=(-?\d+),(-?\d+),(-?\d+) ang=(-?\d+) weapon=(-?\d+) '
                   r'sprite=(-?\d+),(-?\d+),(-?\d+),(-?\d+)\.')
BOMB = re.compile(r'VR native pipebomb: player=(\d+) ')
HITSCAN = re.compile(r'VR native hitscan: player=(\d+) ')
LEVEL = re.compile(r'addlog vrcoop_level(?: \(player \d+\))? = (-?\d+)')
CON = """// Private co-op VR observation: two-level episode, level entry log.
include GAME.CON
definelevelname 0 0 first.map 00:00 00:00 Co-op VR First
definelevelname 0 1 second.map 00:00 00:00 Co-op VR Second
gamevar vrcoop_level 0 0
appendevent EVENT_ENTERLEVEL
    getuserdef[THISACTOR].level_number vrcoop_level
    addlog vrcoop_level
endevent
"""


def level_map(exit_sector):
    """Two sectors; four co-op starts (lotag 1) 768 units apart; bombs on them."""
    a, b = bytearray(sector(0, 4)), bytearray(sector(4, 4))
    for s in (a, b):
        struct.pack_into('<i', s, 4, -32768)
    if exit_sector:
        struct.pack_into('<h', b, 34, -1)  # native end-of-level sector
    walls = [wall(0, 0, 1), wall(1152, 0, 2, nextwall=7, nextsector=1), wall(1152, 8192, 3), wall(0, 8192, 0),
             wall(1152, 0, 5), wall(8192, 0, 6), wall(8192, 8192, 7), wall(1152, 8192, 4, nextwall=1, nextsector=0)]
    starts = []
    for i in range(4):
        start = bytearray(sprite(512, 1024 + i*768, 0, 0, tile=1405, angle=0))
        struct.pack_into('<h', start, 38, 1)  # co-op start
        starts.append(bytes(start))
    bombs = [sprite(512 + dx, 1024 + i*768, 0, 0, tile=HEAVYHBOMB, xrepeat=32, yrepeat=32) for i in range(1, 4) for dx in (48, 96)]
    sprites = starts + bombs
    return (struct.pack('<iiiihhh', 7, 512, 1024, -PHEIGHT, 0, 0, 2) + a + b + struct.pack('<h', 8)
            + b''.join(walls) + struct.pack('<h', len(sprites)) + b''.join(sprites))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, default=49777)
    parser.add_argument('--port', type=int, default=24621)
    parser.add_argument('--timeout', type=int, default=560)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='coop-', dir=args.work_dir.resolve()))
    labs = {role: setup_lab(root, role, args.grp.resolve(), False) for role in ('server', 'flat', 'xr')}
    for role, lab in labs.items():
        (lab / 'first.map').write_bytes(level_map(True))
        (lab / 'second.map').write_bytes(level_map(False))
        (lab / 'coop_vr.con').write_text(CON)
        with (lab / 'eduke32.cfg').open('a') as f:
            f.write('\n[Comm Setup]\nPlayerName = "' + {'server': 'Server', 'flat': 'Flat', 'xr': 'VR'}[role] + '"\n')
    base = {k: v for k, v in os.environ.items() if not k.startswith('EDUKE32_XR')}
    base.update(DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy')
    native = {k: v for k, v in base.items() if not k.startswith('XR_')}
    native.update(EDUKE32_XR_TEST_SHOTS='1')
    capture, console = labs['xr'] / 'capture-request', labs['xr'] / 'console-request'
    xr_env = dict(base, EDUKE32_XR='play', EDUKE32_XR_TEST_SHOTS='1', EDUKE32_XR_TEST_HELD='1', EDUKE32_XR_TEST_INPUT='1',
                  EDUKE32_XR_CAPTURE_REQUEST=str(capture), EDUKE32_XR_CONSOLE_REQUEST=str(console),
                  XDG_DATA_HOME=str(labs['xr'] / 'data'))
    launcher = Path(__file__).resolve().parents[2] / 'package/vr/eduke32-vr-play'
    common = ['-usecwd', '-nosetup', '-noautoload', '-nologo', '-ns', '-nm', '-x', 'coop_vr.con']
    processes, logs = [], []
    deadline = time.monotonic() + args.timeout
    result = {'passed': False, 'evidence_directory': str(root), 'phase': 'setup'}
    checks = result['checks'] = {}

    def launch(role, command, env):
        log = (labs[role] / 'game.log').open('w'); logs.append(log)
        process = subprocess.Popen(command, cwd=labs[role], env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        processes.append(process)
        return process, Observer(process, labs[role] / 'game.log')

    def until(observer, predicate, seconds):
        observer.wait(predicate, timeout=max(1, min(seconds, deadline - time.monotonic())))

    try:
        binary = str(args.binary.resolve())
        server, so = launch('server', [binary, *common, '-dedicated', '-port', str(args.port), '-c2', '-v1', '-l1'], native)
        until(so, lambda t: 'Multiplayer server initialized.' in t, 30)
        until(so, lambda t: LEVEL.search(t) is not None, 30)
        checks['server_cooperative_play'] = 'Cooperative Play' in so.text()
        so.pause(4)
        x11 = X11(args.display)
        result['phase'] = 'flat join'
        flat, fo = launch('flat', [binary, *common, '-connect', f'127.0.0.1:{args.port}'], native)
        until(fo, lambda t: 'Multiplayer client level synchronization complete.' in t, 60)
        fo.pause(2)
        window, _ = x11.owned_window(flat.pid)
        if window:
            x11.press(window, 'Escape', .06, True)
        with Remote(args.remote_port) as remote:
            right, left, head = remote.packet.right, remote.packet.left, remote.packet.head
            right.pose.position.x, right.pose.position.y, right.pose.position.z = .2, 1.3, -.4
            remote.send()
            result['phase'] = 'XR join'
            xr, co = launch('xr', [str(launcher), '--no-voxel-build', '--pack', 'original-lowres', '--binary', binary, '--', *common, '-connect', f'127.0.0.1:{args.port}'], xr_env)
            until(co, lambda t: 'Multiplayer client level synchronization complete.' in t, 120)
            until(co, lambda t: 'OpenXR world oracle: 60 frames' in t, 240)
            co.pause(2)
            if re.findall(r'screen=(-?\d+)', co.text())[-1:] not in (['0'], []):
                window, _ = x11.owned_window(xr.pid)
                if window:
                    x11.press(window, 'Escape', .06, True)
            co.pause(4)

            def where():
                start = len(co.text())
                console.write_text('xr_where\n')
                until(co, lambda t: len(WHERE.findall(t[start:])) >= 3, 60)
                return {int(m[0]): list(map(int, m)) for m in WHERE.findall(co.text()[start:])}

            result['phase'] = 'co-op starts'
            rows = where()
            me = next(r for r in rows.values() if r[1])
            result['players'] = rows
            checks['distinct_coop_players'] = len(rows) >= 3 and me[0] == 2
            # Native co-op uses the collected start order (not start index),
            # exactly as at a level start; joiners must not share a start.
            starts = {(512, 1024 + i*768) for i in range(4)}
            spots = [(rows[i][7], rows[i][8]) for i in sorted(rows)]
            checks['players_at_distinct_coop_starts'] = set(spots) <= starts and len(set(spots)) == len(spots)

            result['phase'] = 'teammate view'
            mate = rows[1]
            yaw = math.degrees(math.remainder(math.atan2(mate[8] - me[8], mate[7] - me[7]) - me[5]*math.pi/1024, 2*math.pi))
            head.center.orientation = orientation(yaw, -5); right.pose.orientation = orientation(yaw, -5); remote.send()
            co.pause(3)
            capture.write_text(str(labs['xr'] / 'teammate') + '\n')
            until(co, lambda _: not capture.exists(), 90)
            checks['teammate_model_holds_weapon'] = 'ok=1' in ''.join(re.findall(r'Held weapon attach: [^\n]*', co.text()))
            checks['teammate_captured'] = (labs['xr'] / 'teammate-left.ppm').is_file()

            def shoot(label):
                head.center.orientation = orientation(0, 0); right.pose.orientation = orientation(0, 0); remote.send()
                co.pause(1)
                start = len(so.text())
                right.trigger_value, right.trigger_click = 1.0, True; remote.send()
                try:
                    until(so, lambda t: any(int(p) == me[0] for p in HITSCAN.findall(t[start:])), 25)
                except RuntimeError:
                    pass
                right.trigger_value, right.trigger_click = 0.0, False; remote.send()
                co.pause(1)
                checks[label] = any(int(p) == me[0] for p in HITSCAN.findall(so.text()[start:]))

            result['phase'] = 'pipebomb throw'
            for _ in range(4):
                if 'weapon=5 family' in co.text():
                    break
                left.b_click = True; remote.send(); co.pause(.4)
                left.b_click = False; remote.send(); co.pause(2.5)
            start = len(so.text())
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
                until(so, lambda t: any(int(p) == me[0] for p in BOMB.findall(t[start:])), 30)
            except RuntimeError:
                pass
            checks['server_spawns_vr_thrown_pipebomb'] = any(int(p) == me[0] for p in BOMB.findall(so.text()[start:]))
            # Back to the pistol (Previous_Weapon) for the hand shots.
            for _ in range(4):
                if re.findall(r'held model: weapon=(\d+)', co.text())[-1:] == ['1']:
                    break
                left.a_click = True; remote.send(); co.pause(.4)
                left.a_click = False; remote.send(); co.pause(2.5)
            result['phase'] = 'VR pistol shot'
            shoot('server_resolves_vr_pistol_shot')

            result['phase'] = 'co-op level exit'
            levels_before = len(LEVEL.findall(so.text()))
            xr_levels_before = len(LEVEL.findall(co.text()))
            left.thumbstick.y = .9; remote.send()
            try:
                until(so, lambda t: len(LEVEL.findall(t)) > levels_before, 60)
            finally:
                left.thumbstick.y = 0.; remote.send()
            until(co, lambda t: len(LEVEL.findall(t)) > xr_levels_before, 60)
            until(fo, lambda t: LEVEL.findall(t)[-1:] == ['1'], 60)
            checks['coop_game_reaches_level_2'] = (LEVEL.findall(so.text())[-1:] == ['1'] and LEVEL.findall(co.text())[-1:] == ['1'])
            offset = len(co.text())
            until(co, lambda t: 'OpenXR held model: weapon=' in t[offset:] or 'OpenXR input: sample=' in t[offset:], 60)
            co.pause(5)
            checks['xr_session_survives_transition'] = 'OpenXR world stopped' not in co.text() and xr.poll() is None
            rows = where()
            checks['coop_players_respawn_on_level_2'] = len(rows) >= 3
            result['phase'] = 'VR shot on level 2'
            shoot('server_resolves_vr_shot_on_level_2')
            capture.write_text(str(labs['xr'] / 'level2') + '\n')
            until(co, lambda _: not capture.exists(), 90)
            until(co, lambda _: (labs['xr'] / 'level2-left.ppm').is_file(), 30)
        checks['all_alive'] = all(p.poll() is None for p in processes)
        result['phase'] = 'complete'
        result['passed'] = all(checks.values())
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
