#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prove remote OpenXR controller input reaches its dedicated-server player.

The native server and XR client each load the test-only controller CON wrapper.
The wrapper observes normal EVENT_PROCESSINPUT state; this runner does not alter
game packets or inject gameplay actions.  A caller provides an already-running
private Monado remote runtime through its normal client environment.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from monado_remote import Remote
from smoke_actions import Observer, samples
from smoke_multiplayer import X11, setup_lab, stop


WRAPPER = Path(__file__).resolve().parent / 'fixtures' / 'controller_test.con'
MYCONNECTINDEX = re.compile(r'addlog myconnectindex\b[^=\n]*= (-?\d+)')


def player_samples(text, player):
    """Return complete fixture samples for one authoritative server player."""
    return [sample for sample in samples(text) if sample.get('player') == player]


def client_player_index(text):
    """Read the joining client's native index emitted by the CON wrapper."""
    matches = MYCONNECTINDEX.findall(text)
    return int(matches[-1]) if matches else None


def bounded(values, limit=10):
    """Keep JSON evidence useful without copying an unbounded server log."""
    return values[-limit:]


def copy_wrapper(lab):
    shutil.copyfile(WRAPPER, lab / WRAPPER.name)


def runtime_env(display, server=False):
    env = dict(os.environ, DISPLAY=display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy')
    if server:
        # A native dedicated server must not receive the caller's XR runtime.
        for key in tuple(env):
            if key.startswith('XR_') or key.startswith('EDUKE32_XR'):
                env.pop(key)
        return env
    # Preserve the caller's XR_RUNTIME_JSON/layer setup only for this client.
    env.update(EDUKE32_XR='1', EDUKE32_XR_TEST_INPUT='1')
    for key in ('EDUKE32_XR_TEST_FAIL', 'EDUKE32_XR_TEST_ZERO_IPD',
                'EDUKE32_XR_TEST_STEREO_POSE', 'EDUKE32_XR_TEST_NATIVE_TARGET',
                'EDUKE32_XR_DIAGNOSTIC_FRAMES'):
        env.pop(key, None)
    return env


def wait_for_server(observer):
    observer.wait(lambda text: 'Multiplayer server initialized.' in text, timeout=15)


def wait_for_join_barrier(x11, process, client_log, server_observer):
    """Wait for real network synchronization before the finite menu dismissal."""
    deadline = time.monotonic() + 25
    synchronized_at = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('XR client exited before multiplayer synchronization')
        client_text = client_log.read_text(errors='replace')
        server_observer.text()
        if 'Multiplayer client level synchronization complete.' in client_text:
            synchronized_at = time.monotonic()
            break
        time.sleep(.05)
    if synchronized_at is None:
        raise RuntimeError('join barrier unavailable: client synchronization missing')

    # G_DisplayLogo/menu setup leaves ready2send reset even under -nologo.
    # This finite fade is deliberately complete before sending Escape.
    while time.monotonic() < synchronized_at + 1.5:
        server_observer.text()
        if process.poll() is not None:
            raise RuntimeError('XR client exited during post-synchronization fade')
        time.sleep(.05)
    window, geometry = x11.owned_window(process.pid)
    if window is None:
        raise RuntimeError('no owned XR client window after synchronization barrier')
    x11.press(window, 'Escape', .06, True)
    deadline = time.monotonic() + 12
    assigned_player = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('XR client exited before native myconnectindex observation')
        assigned_player = client_player_index(client_log.read_text(errors='replace'))
        if assigned_player is not None and player_samples(server_observer.text(), assigned_player):
            break
        time.sleep(.05)
    if assigned_player is None or not player_samples(server_observer.text(), assigned_player):
        raise RuntimeError('post-menu native myconnectindex or matching server samples missing')
    return {'synchronized': True, 'fade_seconds': 1.5,
            'owned_client_window': window, 'client_geometry': geometry,
            'server_player': assigned_player,
            'server_player_samples_at_barrier': len(player_samples(server_observer.text(), assigned_player))}


def exercise_server(observer, remote, player):
    """Perform physical-runtime actions and inspect only server EVENT_PROCESSINPUT."""
    observer.wait(lambda text: bool(player_samples(text, player)), timeout=10)
    remote.neutral()
    observer.pause(.25)
    stages = {}

    def stage(name, action, seconds):
        offset = len(observer.text())
        action()
        observer.pause(seconds)
        stage_samples = player_samples(observer.text()[offset:], player)
        stages[name] = bounded(stage_samples)
        return stage_samples

    baseline = player_samples(observer.text(), player)[-1]

    def move():
        remote.packet.left.thumbstick.y = .8
        remote.send()

    move_samples = stage('move', move, .80)
    stage('release_move', remote.neutral, .55)
    after_move = player_samples(observer.text(), player)[-1]

    def fire():
        remote.packet.right.trigger_value = 1
        remote.packet.right.trigger_click = True
        remote.send()

    ammo_before = after_move['ammo']
    fire_samples = stage('fire', fire, .80)
    release_fire_samples = stage('release_fire', remote.neutral, .55)
    after_fire = player_samples(observer.text(), player)[-1]
    remote.neutral()

    moved = ((baseline['x'], baseline['y']) != (after_move['x'], after_move['y'])
             and any(sample['fvel'] or sample['svel'] for sample in move_samples))
    fired = (any(sample['bits'] & 4 for sample in fire_samples)
             and after_fire['ammo'] < ammo_before)
    last_release = release_fire_samples[-3:]
    released = bool(last_release) and all(not (sample['bits'] & 4) for sample in last_release)
    checks = {
        'server_assigned_player_observed': bool(player_samples(observer.text(), player)),
        'server_authoritative_movement': moved,
        'server_authoritative_fire_and_ammo': fired,
        'server_authoritative_fire_release': released,
    }
    return {
        'passed': all(checks.values()),
        'server_player': player,
        'checks': checks,
        'position_before': [baseline['x'], baseline['y']],
        'position_after_move': [after_move['x'], after_move['y']],
        'ammo_before_fire': ammo_before,
        'ammo_after_fire': after_fire['ammo'],
        'server_samples': stages,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path, help='native dedicated-server executable')
    parser.add_argument('--client-binary', required=True, type=Path, help='XR client executable')
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--display', default=':1')
    parser.add_argument('--port', type=int, default=24586)
    parser.add_argument('--remote-port', required=True, type=int)
    parser.add_argument('--reconnect', action='store_true', help='replace the XR client and repeat the proof')
    args = parser.parse_args()

    binary, client_binary, grp = (args.binary.resolve(), args.client_binary.resolve(), args.grp.resolve())
    if not binary.is_file() or not client_binary.is_file() or not grp.is_file() or not WRAPPER.is_file():
        parser.error('server binary, XR client binary, GRP, and controller wrapper must exist')
    if not 1 <= args.port <= 65535 or not 1 <= args.remote_port <= 65535:
        parser.error('port and remote-port must be in 1..65535')
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='xr-authoritative-input-', dir=args.work_dir.resolve()))
    server = None
    client = None
    server_log = None
    client_log = None
    result = {'passed': False, 'joins': [], 'evidence_directory': str(root)}
    try:
        server_lab = setup_lab(root, 'server', grp, False)
        copy_wrapper(server_lab)
        server_log_path = server_lab / 'server.log'
        server_log = server_log_path.open('w')
        server_command = [str(binary), '-usecwd', '-nosetup', '-noautoload', '-dedicated',
                          '-port', str(args.port), '-v1', '-l1', '-s1', '-x', WRAPPER.name]
        server = subprocess.Popen(server_command, cwd=server_lab, env=runtime_env(args.display, server=True),
                                  stdin=subprocess.DEVNULL, stdout=server_log, stderr=subprocess.STDOUT)
        server_observer = Observer(server, server_log_path)
        wait_for_server(server_observer)
        x11 = X11(args.display)

        with Remote(args.remote_port) as remote:
            for join_number in range(1, 2 + int(args.reconnect)):
                client_lab = setup_lab(root, f'client-{join_number}', grp, False)
                copy_wrapper(client_lab)
                client_log_path = client_lab / 'client.log'
                client_log = client_log_path.open('w')
                client_command = [str(client_binary), '-usecwd', '-nosetup', '-noautoload', '-nologo',
                                  '-ns', '-nm', '-connect', f'127.0.0.1:{args.port}', '-x', WRAPPER.name]
                client = subprocess.Popen(client_command, cwd=client_lab, env=runtime_env(args.display),
                                          stdin=subprocess.DEVNULL, stdout=client_log, stderr=subprocess.STDOUT)
                try:
                    join = {'join': join_number}
                    join['barrier'] = wait_for_join_barrier(x11, client, client_log_path, server_observer)
                    join['server_player'] = join['barrier']['server_player']
                    join['server_authority'] = exercise_server(server_observer, remote, join['server_player'])
                    join['client_exit_before_cleanup'] = client.poll()
                    join['passed'] = join['server_authority']['passed'] and join['client_exit_before_cleanup'] is None
                except Exception as error:
                    join = {'join': join_number, 'passed': False, 'error': str(error),
                            'client_exit_before_cleanup': client.poll()}
                finally:
                    remote.neutral()
                    stop(client)
                    client = None
                    client_log.close()
                    client_log = None
                result['joins'].append(join)
                if not join['passed']:
                    break
                if join_number < 1 + int(args.reconnect):
                    time.sleep(.5)

        result['server_initialized'] = 'Multiplayer server initialized.' in server_log_path.read_text(errors='replace')
        result['server_exit_before_cleanup'] = server.poll()
        result['reconnect_requested'] = args.reconnect
        result['reconnect_completed'] = (not args.reconnect or len(result['joins']) == 2)
        result['passed'] = (result['server_initialized'] and result['server_exit_before_cleanup'] is None
                            and len(result['joins']) == 1 + int(args.reconnect)
                            and all(join['passed'] for join in result['joins']))
    except Exception as error:
        result['error'] = str(error)
        result['server_exit_before_cleanup'] = server.poll() if server else None
    finally:
        if client_log:
            client_log.close()
        stop(client)
        if server_log:
            server_log.close()
        stop(server)
    (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
