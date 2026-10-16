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
from smoke_action_lifecycle import Admin
from smoke_actions import Observer, samples, traces
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
    context_deadline=time.monotonic()+10
    current=traces(client_log.read_text(errors='replace'))
    while not current and time.monotonic()<context_deadline:
        if process.poll() is not None: raise RuntimeError('XR client exited before native input context')
        server_observer.text()
        time.sleep(.05)
        current=traces(client_log.read_text(errors='replace'))
    if not current: raise RuntimeError('native XR input context unavailable at join barrier')
    # User maps can enter gameplay directly; Escape would open a menu there.
    # Dismiss only a menu actually observed in the native input context.
    menu_dismissed=bool(current[-1]['mode'] & 1)
    if menu_dismissed: x11.press(window, 'Escape', .06, True)
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
    return {'synchronized': True, 'fade_seconds': 1.5,'observed_menu_dismissed':menu_dismissed,
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
    release_offset=len(observer.text())
    stage('release_fire', remote.neutral, .55)
    def stable_release(text):
        recent=player_samples(text[release_offset:],player)[-3:]
        return len(recent)==3 and all(not (sample['bits'] & 4) for sample in recent)
    # Observe actual server acknowledgement; the native transport can still
    # deliver an in-flight firing input inside a fixed half-second window.
    observer.wait(stable_release,timeout=3)
    release_fire_samples=player_samples(observer.text()[release_offset:],player)
    stages['release_fire']=bounded(release_fire_samples)
    after_fire = player_samples(observer.text(), player)[-1]
    remote.neutral()

    moved = ((baseline['x'], baseline['y']) != (after_move['x'], after_move['y'])
             and any(sample['fvel'] or sample['svel'] for sample in move_samples))
    fired = (any(sample['bits'] & 4 for sample in fire_samples)
             and after_fire['ammo'] < ammo_before)
    last_release = release_fire_samples[-3:]
    released = len(last_release)==3 and all(not (sample['bits'] & 4) for sample in last_release)
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
    parser.add_argument('--require-hud', action='store_true', help='require 60 actual native HUD/world projections and distinct final eye captures per join')
    parser.add_argument('--inventory-sync',action='store_true',help='require a server-only native inventory change to reach each actual client player ID')
    args = parser.parse_args()

    script='inventory_test.con' if args.inventory_sync else WRAPPER.name
    binary, client_binary, grp = (args.binary.resolve(), args.client_binary.resolve(), args.grp.resolve())
    if not binary.is_file() or not client_binary.is_file() or not grp.is_file() or not WRAPPER.is_file():
        parser.error('server binary, XR client binary, GRP, and controller wrapper must exist')
    if not 1 <= args.port <= 65535 or not 1 <= args.remote_port <= 65535:
        parser.error('port and remote-port must be in 1..65535')
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='xr-authoritative-input-', dir=args.work_dir.resolve()))
    server = None
    client = None
    retained_client = None
    admin = None
    server_log = None
    client_log = None
    result = {'passed': False, 'joins': [], 'evidence_directory': str(root)}
    try:
        server_lab = setup_lab(root, 'server', grp, False)
        copy_wrapper(server_lab)
        if args.inventory_sync:shutil.copyfile(WRAPPER.parent/'inventory_test.con',server_lab/script)
        server_log_path = server_lab / 'server.log'
        server_log = server_log_path.open('w')
        server_command = [str(binary), '-usecwd', '-nosetup', '-noautoload', '-dedicated',
                          '-port', str(args.port), '-v1', '-l1', '-s1', '-x', script]
        server = subprocess.Popen(server_command, cwd=server_lab, env=runtime_env(args.display, server=True),
                                  stdin=subprocess.DEVNULL, stdout=server_log, stderr=subprocess.STDOUT)
        server_observer = Observer(server, server_log_path)
        wait_for_server(server_observer)
        x11 = X11(args.display)

        if args.inventory_sync and args.reconnect:admin=Admin()
        with Remote(args.remote_port) as remote:
            for join_number in range(1, 2 + int(args.reconnect)):
                client_lab = setup_lab(root, f'client-{join_number}', grp, False)
                copy_wrapper(client_lab)
                if args.inventory_sync:shutil.copyfile(WRAPPER.parent/'inventory_test.con',client_lab/script)
                if admin:(client_lab/'settings.cfg').write_text('bind \"F10\" \"disconnect\"\n')
                client_log_path = client_lab / 'client.log'
                client_log = client_log_path.open('w')
                client_command = [str(client_binary), '-usecwd', '-nosetup', '-noautoload', '-nologo',
                                  '-ns', '-nm', '-connect', f'127.0.0.1:{args.port}', '-x', script]
                client_env=runtime_env(args.display)
                if args.require_hud:
                    client_env.update(EDUKE32_XR_UI='2',EDUKE32_XR_SINGLE_PASS='1',EDUKE32_XR_HUD_OUTPUT=str(client_lab/'hud'))
                known=admin.clients() if admin else None
                client = subprocess.Popen(client_command, cwd=client_lab, env=client_env,
                                          stdin=subprocess.DEVNULL, stdout=client_log, stderr=subprocess.STDOUT)
                try:
                    if admin:
                        client_id=admin.discover(known)
                        admin.change('set_client_primary',client_id)
                    join = {'join': join_number}
                    join['barrier'] = wait_for_join_barrier(x11, client, client_log_path, server_observer)
                    join['server_player'] = join['barrier']['server_player']
                    if retained_client:
                        # Establish a real sparse connection set: join the second
                        # owned client, then disconnect the first through its
                        # native command binding. No synthetic server state.
                        window,_=x11.owned_window(retained_client.pid)
                        if not window:raise RuntimeError('retained owned client window missing')
                        offset=len(server_observer.text())
                        x11.press(window,'F10',.06,True)
                        server_observer.wait(lambda text:' disconnected.' in text[offset:],timeout=8)
                        join['sparse_player_after_native_disconnect']=join['server_player']>1
                        if not join['sparse_player_after_native_disconnect']:raise RuntimeError('sparse player fixture unavailable')
                        stop(retained_client);retained_client=None

                    join['server_authority'] = exercise_server(server_observer, remote, join['server_player'])
                    if args.inventory_sync:
                        player=join['server_player']
                        changed=re.compile(r'addlog vrinventory_done \(player '+str(player)+r'\) = 1')
                        server_observer.wait(lambda text:bool(changed.search(text)),timeout=6)
                        marker=changed.search(server_observer.text()).end()
                        server_observer.wait(lambda text:bool(player_samples(text[marker:],player)),timeout=3)
                        expected=player_samples(server_observer.text()[marker:],player)[-1]['ammo']
                        observer=Observer(client,client_log_path)
                        observer.wait(lambda text:bool(player_samples(text,player)) and player_samples(text,player)[-1]['ammo']==expected,timeout=5)
                        join['inventory_sync']={'passed':True,'player':player,'authoritative_ammo':expected,
                                                'client_ammo':player_samples(observer.text(),player)[-1]['ammo']}
                    if args.require_hud:
                        observer=Observer(client,client_log_path)
                        observer.wait(lambda text: 'OpenXR HUD presentation: 60 frames;' in text
                                      and 'OpenXR world oracle: 60 frames,' in text,timeout=15)
                        text=observer.text()
                        left,right=client_lab/'hud-left.ppm',client_lab/'hud-right.ppm'
                        join['presentation']={'HUD_and_world_60_submissions':True,
                            'distinct_final_eye_captures':left.is_file() and right.is_file() and left.read_bytes()!=right.read_bytes(),
                            'runtime_not_stopped':'OpenXR world stopped:' not in text,
                            'core_validation_no_warning_or_error':not bool(re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)',text))}
                    join['client_exit_before_cleanup'] = client.poll()
                    join['passed'] = (join['server_authority']['passed'] and join['client_exit_before_cleanup'] is None
                                      and (not args.require_hud or all(join['presentation'].values()))
                                      and (not args.inventory_sync or join['inventory_sync']['passed']))
                except Exception as error:
                    join = {'join': join_number, 'passed': False, 'error': str(error),
                            'client_exit_before_cleanup': client.poll()}
                finally:
                    remote.neutral()
                    if admin and join_number==1 and join.get('passed'):
                        retained_client=client
                    else:stop(client)
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
        stop(retained_client)
        if admin:admin.close()
        if server_log:
            server_log.close()
        stop(server)
    (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
