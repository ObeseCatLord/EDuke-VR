#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Two simulated-VR players in co-op on a real (remote) dedicated server.

Run under software_xr_lab.py --share-net --second-runtime: each client gets its own private Monado
(remote driver ports --remote-port and --remote-port + 1), so the two headsets move independently.
The dedicated server is started separately (e.g. on another machine) and named with --server.
Checks, from both clients:

- both join the co-op game as distinct players;
- each receives the other's VR body pose (head, hands, held weapon) and solves and draws the
  other's IK body, hand shells and weapon locally (native player sprite hidden);
- the other's tracked motion arrives: raising a hand 40 cm raises the remote wrist accordingly,
  turning the head turns the remote head, a mighty foot kick extends the remote leg;
- voice both ways: each talker's synthetic tone is decoded by the other at the right frequency;
- VR shots fire through the server (EDUKE32_XR_TEST_SHOTS log on the server is checked separately);
- eye captures of each player looking at the other for review.
"""
import argparse, json, math, os, re, subprocess, tempfile, time
from pathlib import Path
import numpy as np
from monado_remote import Remote
from smoke_actions import Observer
from smoke_aim import orientation
from smoke_multiplayer import X11, setup_lab

WHERE = re.compile(r'VR where: player=(\d+) local=(\d) pos=(-?\d+),(-?\d+),(-?\d+) ang=(-?\d+) weapon=(-?\d+) '
                   r'sprite=(-?\d+),(-?\d+),(-?\d+),(-?\d+)\.')
RECEIVED = re.compile(r'VR body pose received: player=(\d+) sequence=(\d+) flags=(\d+) hands=(\d+),(\d+) weapon=(-?\d+)\.')
BODY = re.compile(r'VR remote body: player=(\d+) sequence=(\d+) hands=(\d),(\d) kinds=(\d+),(\d+) weapon=(-?\d+) models=(\d+) '
                  r'kick=(\d+) headyaw=(-?[\d.]+) left=(-?\d+),(-?\d+),(-?\d+) right=(-?\d+),(-?\d+),(-?\d+)\.')
TONES = {'a': 440.0, 'b': 660.0}
ZUNITS = 6144


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--server', required=True, help='HOST:PORT of the running dedicated co-op server')
    parser.add_argument('--pack', default='dnf-private')
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, default=49777)
    parser.add_argument('--timeout', type=int, default=580)
    args = parser.parse_args()
    runtime2 = os.environ.get('SOFTWARE_XR_LAB_RUNTIME2')
    if not runtime2:
        raise SystemExit('needs software_xr_lab.py --second-runtime')
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='remote-coop-', dir=args.work_dir.resolve()))
    labs = {role: setup_lab(root, role, args.grp.resolve(), False) for role in ('a', 'b')}
    for role, lab in labs.items():
        (lab / 'autoexec.cfg').write_text('voice_transmit 1\nvoice_mode 0\n')
        with (lab / 'eduke32.cfg').open('a') as f:
            f.write('\n[Comm Setup]\nPlayerName = "VR' + role.upper() + '"\n')
    base = {k: v for k, v in os.environ.items() if not k.startswith(('EDUKE32_XR', 'EDUKE32_VOICE'))}
    base.update(DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy')
    envs, consoles, captures = {}, {}, {}
    for role, lab in labs.items():
        consoles[role], captures[role] = lab / 'console-request', lab / 'capture-request'
        envs[role] = dict(base, EDUKE32_XR='play', EDUKE32_XR_TEST_SHOTS='1', EDUKE32_XR_TEST_HELD='1',
                          EDUKE32_XR_TEST_BODY_POSES='1', EDUKE32_XR_CONSOLE_REQUEST=str(consoles[role]),
                          EDUKE32_XR_CAPTURE_REQUEST=str(captures[role]), XDG_DATA_HOME=str(lab / 'data'),
                          EDUKE32_VOICE_TEST_TONE=f'{TONES[role]:.0f}:700:500', EDUKE32_VOICE_TEST_DUMP=str(lab / 'voice'))
    envs['b'].update(XDG_RUNTIME_DIR=runtime2)
    launcher = Path(__file__).resolve().parents[2] / 'package/vr/eduke32-vr-play'
    common = ['-usecwd', '-nosetup', '-noautoload', '-nologo', '-ns']
    processes, logs = [], []
    deadline = time.monotonic() + args.timeout
    result = {'passed': False, 'evidence_directory': str(root), 'server': args.server, 'phase': 'setup'}
    checks = result['checks'] = {}
    x11 = X11(args.display)

    def launch(role):
        log = (labs[role] / 'game.log').open('w'); logs.append(log)
        command = [str(launcher), '--binary', str(args.binary.resolve()), '--pack', args.pack, '--', *common,
                   '-connect', args.server]
        process = subprocess.Popen(command, cwd=labs[role], env=envs[role], stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT)
        processes.append(process)
        return process, Observer(process, labs[role] / 'game.log')

    def until(observer, predicate, seconds):
        observer.wait(predicate, timeout=max(1, min(seconds, deadline - time.monotonic())))

    def soft(observer, predicate, seconds):
        try:
            until(observer, predicate, seconds)
            return True
        except RuntimeError:
            return False

    def connect(port):
        # The remote driver starts listening a little after Monado's IPC socket appears.
        for _ in range(60):
            try:
                return Remote(port)
            except ConnectionRefusedError:
                time.sleep(.5)
        return Remote(port)

    try:
        with connect(args.remote_port) as ra, connect(args.remote_port + 1) as rb:
            remotes = {'a': ra, 'b': rb}
            for remote in remotes.values():
                p = remote.packet
                p.head.center.position.x, p.head.center.position.y, p.head.center.position.z = 0., 1.65, 0.
                p.right.pose.position.x, p.right.pose.position.y, p.right.pose.position.z = .22, 1.25, -.35
                p.left.pose.position.x, p.left.pose.position.y, p.left.pose.position.z = -.22, 1.05, -.1
                remote.send()
            procs, obs = {}, {}
            for role in ('a', 'b'):
                result['phase'] = f'{role} join'
                procs[role], obs[role] = launch(role)
                until(obs[role], lambda t: 'Multiplayer client level synchronization complete.' in t, 150)
                until(obs[role], lambda t: 'OpenXR world oracle: 60 frames' in t, 300)
                obs[role].pause(2)
                if re.findall(r'screen=(-?\d+)', obs[role].text())[-1:] not in (['0'], []):
                    window, _ = x11.owned_window(procs[role].pid)
                    if window:
                        x11.press(window, 'Escape', .06, True)
            for role in ('a', 'b'):
                obs[role].pause(2)

            def where(role):
                start = len(obs[role].text())
                consoles[role].write_text('xr_where\n')
                until(obs[role], lambda t: len(WHERE.findall(t[start:])) >= 2, 60)
                return {int(m[0]): list(map(int, m)) for m in WHERE.findall(obs[role].text()[start:])}

            result['phase'] = 'positions'
            rows = {role: where(role) for role in ('a', 'b')}
            me = {role: next(r for r in rows[role].values() if r[1]) for role in ('a', 'b')}
            result['players'] = {role: me[role][0] for role in me}
            checks['distinct_players'] = me['a'][0] != me['b'][0] and me['a'][0] > 0 and me['b'][0] > 0
            other = {'a': 'b', 'b': 'a'}

            def face(role):
                mine, theirs = me[role], rows[role][me[other[role]][0]]
                return math.degrees(math.remainder(math.atan2(theirs[8] - mine[8], theirs[7] - mine[7])
                                                   - mine[5] * math.pi / 1024, 2 * math.pi))

            yaw = {role: face(role) for role in ('a', 'b')}
            result['facing_yaw'] = yaw
            for role, remote in remotes.items():
                p = remote.packet
                p.head.center.orientation = orientation(yaw[role], -3)
                p.right.pose.orientation = orientation(yaw[role], 0)
                p.left.pose.orientation = orientation(yaw[role], -30)
                remote.send()

            def bodies(role, start=0):
                return [list(m) for m in BODY.findall(obs[role].text()[start:]) if int(m[0]) == me[other[role]][0]]

            result['phase'] = 'pose relay'
            for role in ('a', 'b'):
                peer = me[other[role]][0]
                checks[f'{role}_receives_pose'] = soft(obs[role], lambda t: any(int(m[0]) == peer for m in RECEIVED.findall(t)), 60)
                checks[f'{role}_draws_remote_ik_body'] = soft(obs[role], lambda t: bool(bodies(role)), 60)
            # Each peer shows its weapon once its own headset has recentered.
            for role in ('a', 'b'):
                soft(obs[role], lambda t: any(int(r[6]) >= 0 for r in bodies(role)), 90)
            last = {role: next((r for r in reversed(bodies(role)) if int(r[6]) >= 0), (bodies(role) or [None])[-1])
                    for role in ('a', 'b')}
            result['remote_body'] = last
            for role in ('a', 'b'):
                row = last[role]
                checks[f'{role}_remote_both_hands_and_weapon'] = bool(row) and row[2:4] == ['1', '1'] and int(row[6]) >= 0
                checks[f'{role}_remote_holds_weapon'] = bool(row) and '5' in row[4:6]

            result['phase'] = 'walk'
            # B walks toward A for a moment (head-relative stick), into the open; A sees B move.
            peer_on_a = me['b'][0]
            mark = len(obs['a'].text())
            rb.packet.left.thumbstick.y = .8; rb.send()
            time.sleep(1.2)
            rb.packet.left.thumbstick.y = 0.; rb.send()
            obs['b'].pause(2)
            rows = {role: where(role) for role in ('a', 'b')}
            moved = math.hypot(rows['b'][peer_on_a][7] - me['b'][7], rows['b'][peer_on_a][8] - me['b'][8])
            result['b_walked_units'] = round(moved)
            seen = rows['a'][peer_on_a]
            result['a_sees_b_at'] = seen[7:9]
            checks['a_sees_b_walk'] = moved > 200 and math.hypot(seen[7] - rows['b'][peer_on_a][7], seen[8] - rows['b'][peer_on_a][8]) < 64
            me = {role: next(r for r in rows[role].values() if r[1]) for role in ('a', 'b')}
            # In VR the native angle follows the head: aim relative to the current head yaw.
            yaw = {role: face(role) + yaw[role] for role in ('a', 'b')}
            result['facing_yaw_after_walk'] = yaw
            for role, remote in remotes.items():
                p = remote.packet
                p.head.center.orientation = orientation(yaw[role], -3)
                p.right.pose.orientation = orientation(yaw[role], 0)
                p.left.pose.orientation = orientation(yaw[role], -30)
                remote.send()
            for role in ('a', 'b'):
                obs[role].pause(2)

            result['phase'] = 'captures facing'
            for role in ('a', 'b'):
                captures[role].write_text(str(labs[role] / 'facing') + '\n')
            for role in ('a', 'b'):
                until(obs[role], lambda _: not captures[role].exists(), 120)

            result['phase'] = 'hand motion sync'
            # A raises its off (left) hand 40 cm; B's view of A's left wrist must rise by about that.
            peer_on_b = me['a'][0]
            before = [r for r in bodies('b') if int(r[0]) == peer_on_b][-1]
            ra.packet.left.pose.position.y += .40; ra.send()
            mark = len(obs['b'].text())
            time.sleep(1.5)
            soft(obs['b'], lambda t: len([r for r in BODY.findall(t[mark:]) if int(r[0]) == peer_on_b]) >= 2, 30)
            after = [list(r) for r in BODY.findall(obs['b'].text()[mark:]) if int(r[0]) == peer_on_b][-1:]
            if after:
                rise = (int(before[12]) - int(after[0][12])) / ZUNITS
                result['remote_left_wrist_rise_m'] = round(rise, 3)
                checks['b_sees_a_hand_raise'] = .30 < rise < .50
            else:
                checks['b_sees_a_hand_raise'] = False
            # B turns its head 60 degrees left; A's view of B's head yaw follows.
            peer_on_a = me['b'][0]
            before_yaw = float([r for r in bodies('a') if int(r[0]) == peer_on_a][-1][9])
            rb.packet.head.center.orientation = orientation(yaw['b'] + 60, -3); rb.send()
            mark = len(obs['a'].text())
            time.sleep(1.5)
            soft(obs['a'], lambda t: len([r for r in BODY.findall(t[mark:]) if int(r[0]) == peer_on_a]) >= 2, 30)
            after = [list(r) for r in BODY.findall(obs['a'].text()[mark:]) if int(r[0]) == peer_on_a][-1:]
            if after:
                turn = math.degrees(math.remainder(math.radians(float(after[0][9]) - before_yaw), 2 * math.pi))
                result['remote_head_turn_deg'] = round(turn, 1)
                checks['a_sees_b_head_turn'] = 50 < turn < 70
            else:
                checks['a_sees_b_head_turn'] = False
            rb.packet.head.center.orientation = orientation(yaw['b'], -3); rb.send()

            result['phase'] = 'captures moved'
            time.sleep(1)
            captures['b'].write_text(str(labs['b'] / 'raised') + '\n')
            until(obs['b'], lambda _: not captures['b'].exists(), 120)

            result['phase'] = 'kick sync'
            # A kicks (left trigger: mighty foot); B sees A's leg extension in the pose stream.
            mark = len(obs['b'].text())
            ra.packet.left.trigger_value, ra.packet.left.trigger_click = 1.0, True; ra.send()
            time.sleep(.3)
            ra.packet.left.trigger_value, ra.packet.left.trigger_click = 0.0, False; ra.send()
            soft(obs['b'], lambda t: any(int(r[0]) == peer_on_b and int(r[8]) > 0 for r in BODY.findall(t[mark:])), 20)
            checks['b_sees_a_kick'] = any(int(r[0]) == peer_on_b and int(r[8]) > 0 for r in BODY.findall(obs['b'].text()[mark:]))
            ra.packet.left.pose.position.y -= .40; ra.send()

            result['phase'] = 'shots'
            for role, remote in remotes.items():
                p = remote.packet
                p.right.trigger_value, p.right.trigger_click = 1.0, True; remote.send()
            time.sleep(.5)
            for role, remote in remotes.items():
                p = remote.packet
                p.right.trigger_value, p.right.trigger_click = 0.0, False; remote.send()
            for role in ('a', 'b'):
                obs[role].pause(1)
            result['shot_time'] = time.time()

            result['phase'] = 'voice'
            for role in ('a', 'b'):
                obs[role].pause(4)
        for role in ('a', 'b'):
            speaker = me[other[role]][0]
            path = labs[role] / f'voice-speaker-{speaker}.s16'
            pcm = np.fromfile(path, dtype='<i2') if path.is_file() else np.zeros(0, dtype='<i2')
            result[f'{role}_decoded_seconds'] = round(len(pcm) / 48000, 2)
            if len(pcm) > 48000:
                chunk = pcm[-48000:].astype(float)
                spectrum = np.abs(np.fft.rfft(chunk * np.hanning(len(chunk))))
                result[f'{role}_dominant_hz'] = float(np.argmax(spectrum[20:]) + 20) * 48000 / len(chunk)
            checks[f'{role}_hears_other_voice'] = (len(pcm) > 48000
                                                   and abs(result.get(f'{role}_dominant_hz', 0) - TONES[other[role]]) < 15)
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
    (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
