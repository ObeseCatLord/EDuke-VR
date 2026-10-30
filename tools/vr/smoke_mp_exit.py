#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Two VR players change level through the real exit: E1L1's nuke button.

Run under software_xr_lab.py --share-net --second-runtime. Starts its own dedicated co-op server
(E1L1, no monsters) and two simulated-VR clients (player A on the first runtime, B on the second).
A is placed at the nuke button, shoots the glass in front of it (right hand) and presses use (left
grip, aimed by the left hand). Every machine
then ends the level on its own, as in real play, a little apart in time. Checks, after all three
reach E1L2:

- the server and both clients are on E1L2, and both clients keep receiving world updates there
  (a "Net stats world: applied=N" line after the change with N > 0);
- no client logged "player killed by cursectnum == -1" (players placed outside the new map) or
  "Tried to draw wall ... twice" (geometry corrupted by a mismatched world update);
- each client sees both players inside the new map, alive, and the two clients agree on where
  the other player is;
- eye captures of each player on E1L2 for review.
"""
import argparse, json, math, os, re, subprocess, tempfile, time
from pathlib import Path
from monado_remote import Remote
from smoke_actions import Observer
from smoke_aim import orientation
from smoke_multiplayer import setup_lab

WHERE = re.compile(r'VR where: player=(\d+) local=(\d) pos=(-?\d+),(-?\d+),(-?\d+) ang=(-?\d+) weapon=(-?\d+) '
                   r'sprite=(-?\d+),(-?\d+),(-?\d+),(-?\d+)\.')
SPRITE = re.compile(r'VR where sprite: player=(\d+) index=(\d+) picnum=(\d+) cstat=(\d+) xrepeat=(\d+) extra=(-?\d+) dead=(\d+)')
APPLIED = re.compile(r'Net stats world: applied=(\d+)')
# E1L1 (World Tour maps/E1L1.MAP): nuke button sprite 404 at (22016, 60928), facing west, floor -54272.
# The button sits in a shallow alcove behind GLASS: as in play, A shoots the glass, then presses.
BUTTON_STAND = (21700, 60928, 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path, help='VR client (eduke32-xr)')
    parser.add_argument('--server-binary', required=True, type=Path, help='dedicated server (eduke32-net)')
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--port', type=int, default=24871)
    parser.add_argument('--pack', default='original-lowres')
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, default=49777)
    parser.add_argument('--timeout', type=int, default=580)
    args = parser.parse_args()
    runtime2 = os.environ.get('SOFTWARE_XR_LAB_RUNTIME2')
    if not runtime2:
        raise SystemExit('needs software_xr_lab.py --second-runtime')
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='mp-exit-', dir=args.work_dir.resolve()))
    deadline = time.monotonic() + args.timeout
    result = {'passed': False, 'evidence_directory': str(root), 'phase': 'setup'}
    checks = result['checks'] = {}
    processes, files = [], []

    server_dir = setup_lab(root, 'server', args.grp.resolve(), False)
    server_log = server_dir / 'server.log'
    out = server_log.open('w'); files.append(out)
    server = subprocess.Popen([str(args.server_binary.resolve()), '-usecwd', '-nosetup', '-noautoload', '-nologo', '-dedicated',
                               '-port', str(args.port), '-c2', '-v1', '-l1', '-s2', '-m'], cwd=server_dir,
                              env=dict(os.environ, EDUKE32_XR_TEST_USE='1'), stdin=subprocess.PIPE, stdout=out, stderr=subprocess.STDOUT, text=True)
    processes.append(server)
    server_obs = Observer(server, server_log)

    labs = {role: setup_lab(root, role, args.grp.resolve(), False) for role in ('a', 'b')}
    base = {k: v for k, v in os.environ.items() if not k.startswith(('EDUKE32_XR', 'EDUKE32_VOICE'))}
    base.update(DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy')
    envs, consoles, captures = {}, {}, {}
    for role, lab in labs.items():
        with (lab / 'eduke32.cfg').open('a') as f:
            f.write('\n[Comm Setup]\nPlayerName = "VR' + role.upper() + '"\n')
        consoles[role], captures[role] = lab / 'console-request', lab / 'capture-request'
        envs[role] = dict(base, EDUKE32_XR='play', EDUKE32_XR_FINGER_TRACKING='0', EDUKE32_XR_TEST_USE='1', EDUKE32_XR_TEST_SHOTS='1',
                          EDUKE32_XR_CONSOLE_REQUEST=str(consoles[role]), EDUKE32_XR_CAPTURE_REQUEST=str(captures[role]),
                          XDG_DATA_HOME=str(lab / 'data'))
    envs['b'].update(XDG_RUNTIME_DIR=runtime2)
    launcher = Path(__file__).resolve().parents[2] / 'package/vr/eduke32-vr-play'

    def launch(role):
        log = (labs[role] / 'game.log').open('w'); files.append(log)
        command = [str(launcher), '--no-voxel-build', '--binary', str(args.binary.resolve()), '--pack', args.pack, '--',
                   '-usecwd', '-nosetup', '-noautoload', '-nologo', '-connect', f'127.0.0.1:{args.port}']
        process = subprocess.Popen(command, cwd=labs[role], env=envs[role], stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT)
        processes.append(process)
        return Observer(process, labs[role] / 'game.log')

    def until(observer, predicate, seconds):
        observer.wait(predicate, timeout=max(1, min(seconds, deadline - time.monotonic())))

    def soft(observer, predicate, seconds):
        try:
            until(observer, predicate, seconds)
            return True
        except RuntimeError:
            return False

    def connect(port):
        for _ in range(60):
            try:
                return Remote(port)
            except ConnectionRefusedError:
                time.sleep(.5)
        return Remote(port)

    def where(obs, role):
        start = len(obs[role].text())
        consoles[role].write_text('xr_where\n')
        until(obs[role], lambda t: len(SPRITE.findall(t[start:])) >= 3, 60)
        text = obs[role].text()[start:]
        return ({int(m[0]): [int(v) for v in m] for m in WHERE.findall(text)},
                {int(m[0]): [int(v) for v in m] for m in SPRITE.findall(text)})

    try:
        until(server_obs, lambda t: 'E1L1' in t, 60)
        with connect(args.remote_port) as ra, connect(args.remote_port + 1) as rb:
            remotes = {'a': ra, 'b': rb}
            for remote in remotes.values():
                p = remote.packet
                p.head.center.position.x, p.head.center.position.y, p.head.center.position.z = 0., 1.65, 0.
                p.head.center.orientation = orientation(0, 0)
                p.right.pose.position.x, p.right.pose.position.y, p.right.pose.position.z = .22, 1.25, -.35
                p.left.pose.position.x, p.left.pose.position.y, p.left.pose.position.z = -.18, 1.35, -.35
                p.left.pose.orientation = orientation(0, 0)
                remote.send()
            obs = {}
            for role in ('a', 'b'):
                result['phase'] = f'{role} join'
                obs[role] = launch(role)
                until(obs[role], lambda t: 'Multiplayer client level synchronization complete.' in t, 150)
                until(obs[role], lambda t: 'OpenXR world oracle: 60 frames' in t, 300)
            for role in ('a', 'b'):
                obs[role].pause(3)

            result['phase'] = 'press the nuke button'
            mark = {role: len(obs[role].text()) for role in ('a', 'b')}
            consoles['a'].write_text('xr_goto %d %d %d\n' % BUTTON_STAND)
            obs['a'].pause(3)
            ra.packet.right.pose.position.x, ra.packet.right.pose.position.y = .05, 1.5
            ra.packet.right.pose.orientation = orientation(0, 0); ra.send()
            obs['a'].pause(1.5)
            for _ in range(3):   # break the glass
                ra.packet.right.trigger_value = 1.0; ra.send(); obs['a'].pause(.25)
                ra.packet.right.trigger_value = 0.0; ra.send(); obs['a'].pause(.6)
            obs['a'].pause(2)
            ra.packet.left.squeeze_value = 1.0; ra.send()
            obs['a'].pause(.6)
            ra.packet.left.squeeze_value = 0.0; ra.send()
            checks['a_used_the_button'] = soft(obs['a'], lambda t: re.search(r'VR use: .*picnum=142', t[mark['a']:]) is not None, 30)

            result['phase'] = 'level change'
            # Every machine ends the level on its own; bonus screens wait for a button.
            for role in ('a', 'b'):
                for _ in range(40):
                    if 'E1L2' in obs[role].text()[mark[role]:] or time.monotonic() > deadline:
                        break
                    remotes[role].packet.right.a_click = True; remotes[role].send()
                    time.sleep(.3)
                    remotes[role].packet.right.a_click = False; remotes[role].send()
                    time.sleep(2.7)
            checks['server_on_e1l2'] = soft(server_obs, lambda t: 'E1L2' in t, 60)
            for role in ('a', 'b'):
                checks[f'{role}_on_e1l2'] = soft(obs[role], lambda t: 'E1L2' in t[mark[role]:], 90)
            changed = {role: obs[role].text().find('E1L2', mark[role]) for role in ('a', 'b')}

            result['phase'] = 'settle on E1L2'
            # The client waits for the server after loading (readiness pings); then a full minute of
            # play so it logs network statistics from the new map (the line logged at the change
            # itself describes the old map).
            for role in ('a', 'b'):
                checks[f'{role}_ready_on_e1l2'] = soft(obs[role], lambda t: 'readiness wait: complete' in t[changed[role]:], 120)
            for role in ('a', 'b'):
                soft(obs[role], lambda t: len(APPLIED.findall(t[changed[role]:])) >= 2, 100)
            rows = {role: where(obs, role) for role in ('a', 'b')}
            result['where'] = {role: {'players': rows[role][0], 'sprites': rows[role][1]} for role in rows}
            for role in ('a', 'b'):
                text = obs[role].text()[max(changed[role], 0):]
                applied = [int(n) for n in APPLIED.findall(text)][1:]   # [0]: the old map's, logged at the change
                result[f'{role}_world_updates_applied'] = applied
                checks[f'{role}_world_updates_after_change'] = any(n > 0 for n in applied)
                checks[f'{role}_no_players_outside_map'] = 'cursectnum == -1' not in text
                checks[f'{role}_no_corrupted_geometry'] = 'twice in a frame' not in text
                players, sprites = rows[role]
                humans = [p for p in players if p > 0]
                checks[f'{role}_sees_both_players_alive'] = len(humans) >= 2 and all(
                    p in sprites and sprites[p][5] > 0 and sprites[p][6] == 0 for p in humans)
            pa, pb = rows['a'][0], rows['b'][0]
            agree = [math.hypot(pa[p][2] - pb[p][2], pa[p][3] - pb[p][3]) for p in pa if p > 0 and p in pb]
            result['client_disagreement_units'] = [round(d) for d in agree]
            checks['clients_agree_on_positions'] = bool(agree) and max(agree) < 256

            result['phase'] = 'captures'
            for role in ('a', 'b'):
                captures[role].write_text(str(labs[role] / 'e1l2') + '\n')
            for role in ('a', 'b'):
                soft(obs[role], lambda _: not captures[role].exists(), 120)
            result['captures'] = {role: str(labs[role] / 'e1l2') for role in ('a', 'b')}
            result['phase'] = 'done'
    except Exception as error:   # report how far it got
        result['error'] = f'{type(error).__name__}: {error}'
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        for f in files:
            f.close()
    result['passed'] = result['phase'] == 'done' and bool(checks) and all(checks.values())
    print(json.dumps(result, indent=1))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
