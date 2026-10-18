#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual AA remote-controller selection against a native dedicated server.

Run inside software_xr_lab.py. Both peers include the owned installation's
unmodified scripts plus observations. No selection/gameplay values are seeded.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from monado_remote import Remote
from smoke_actions import Observer
from smoke_aim import orientation
from smoke_hitscan import rays
from smoke_alien_armageddon import (aa_samples, aa_wrapper, drive_character_selection,
                                   post_gameplay_capture, PVP_CAPTURE)
from smoke_multiplayer import CONFIG, X11, stop
from smoke_native_levels import assert_cpu_binary, assert_gpu_devices_absent, sanitised_env

SYNC = 'Multiplayer client level synchronization complete.'
POLICY_FIELDS = ('tick', 'player', 'reset_event', 'startguns', 'permanent', 'marathon', 'gametype', 'gotpistol')
POLICY_ROW = re.compile(r'addlog aapolicy_(\w+)(?: \(player \d+\))? = (-?\d+)')


def policy_wrapper():
    declarations = ''.join(f'gamevar aapolicy_{name} 0 524289\n' for name in POLICY_FIELDS)
    reads = '''
 addvar aapolicy_tick 1
 getplayer[THISACTOR].index aapolicy_player
 setvarvar aapolicy_startguns startguns
 setvarvar aapolicy_permanent startguns_perma
 setvarvar aapolicy_marathon marathon
 setvarvar aapolicy_gametype gametype
 getplayer[THISACTOR].gotweapon PISTOL_WEAPON aapolicy_gotpistol
'''
    logs = ''.join(f' addlog aapolicy_{name}\n' for name in POLICY_FIELDS)
    return declarations + ''.join(
        f'appendevent {event}\n setvar aapolicy_reset_event {reset}\n' + reads + logs + 'endevent\n'
        for event, reset in (('EVENT_RESETPLAYER', 1), ('EVENT_PROCESSINPUT', 0)))


def policy_rows(text):
    result, row = [], {}
    for name, value in POLICY_ROW.findall(text):
        if name == 'tick':
            row = {}
        row[name] = int(value)
        if name == 'gotpistol' and all(key in row for key in POLICY_FIELDS):
            result.append(row)
    return result


def fire_selected_weapon(server, client, tracked, remote, player):
    """Use the actual AA weapon and normal VR pose/input packets on both peers."""
    local_rows = lambda observer: [row for row in aa_samples(observer.text()) if row['player'] == player]
    tracked.wait(lambda text: local_rows(tracked)[-1]['weaponpos'] == 0 and
                 local_rows(tracked)[-1]['counter'] == 0, timeout=12)
    remote.neutral()
    hand = remote.packet.right
    hand.pose.position.x, hand.pose.position.y, hand.pose.position.z = .2, 1.3, -.5
    hand.pose.orientation = orientation(12, 8)
    remote.send()
    tracked.pause(.6)
    before = {'server': local_rows(server)[-1], 'client': local_rows(client)[-1]}
    offsets = {'server': len(server.text()), 'client': len(client.text())}
    hand.trigger_value, hand.trigger_click = 1, True
    remote.send()
    try:
        server.wait(lambda text: any(row['player'] == player and row['shots'] > before['server']['shots']
                                    and row['ammo'] < before['server']['ammo']
                                    for row in aa_samples(text[offsets['server']:])), timeout=10)
    finally:
        hand.trigger_value, hand.trigger_click = 0, False
        remote.send()
    server.wait(lambda text: local_rows(server)[-1]['counter'] == 0 and
                not (local_rows(server)[-1]['bits'] & 4), timeout=8)
    after_server = local_rows(server)[-1]
    client.wait(lambda text: local_rows(client)[-1]['ammo'] == after_server['ammo'] and
                local_rows(client)[-1]['counter'] == 0 and not (local_rows(client)[-1]['bits'] & 4), timeout=8)
    after_client = local_rows(client)[-1]
    impacts = rays(server.text()[offsets['server']:], player)
    return {'before': before, 'after': {'server': after_server, 'client': after_client},
            'authoritative_tracked_hits': impacts,
            'checks': {'actual_AA_native_weapon_fired': after_server['shots'] > before['server']['shots'],
                       'native_ammo_decreased_and_converged': 0 <= after_server['ammo'] < before['server']['ammo']
                           and after_client['ammo'] == after_server['ammo'],
                       'authoritative_hand_hitscan': bool(impacts),
                       'actual_tracked_player_trigger_seen': any(row['player'] == player and row['bits'] & 4
                           for row in aa_samples(tracked.text()[offsets['server' if tracked is server else 'client']:]))}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'client-binary', 'mod-root', 'work-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, required=True)
    parser.add_argument('--port', type=int, default=24942)
    parser.add_argument('--client-fps', type=int, default=5)
    parser.add_argument('--xr-host', action='store_true',
                        help='Use --client-binary as the XR listen server and --binary as its CPU client')
    parser.add_argument('--input-helper', type=Path,
                        help='Owned SDL-dummy keyboard helper required for the --xr-host CPU client')
    parser.add_argument('--per-player-selector-edge', action='store_true',
                        help='Causal lab experiment: predeclare AA oldbits as per-player on both peers')
    args = parser.parse_args()
    if args.xr_host and (not args.input_helper or not args.input_helper.is_file()):
        parser.error('--xr-host requires --input-helper')
    if args.input_helper:
        args.input_helper = args.input_helper.resolve()
    for name in ('binary', 'client_binary', 'mod_root', 'work_dir'):
        setattr(args, name, getattr(args, name).resolve())
    assert_gpu_devices_absent()
    assert_cpu_binary(args.binary)
    xr_role = 'server' if args.xr_host else 'client'
    root = Path(tempfile.mkdtemp(prefix='aa-mp-gameplay-', dir=args.work_dir))
    processes, observers, logs, labs = {}, {}, [], {}
    input_fd = None
    result = {'passed': False, 'checks': {}, 'stages': {}, 'evidence_directory': str(root),
              'qualification': 'Actual AA selection, tracked firing and native ammo authority; not full campaign or SPS acceptance.',
              'xr_role': xr_role}
    result['selector_edge_experiment'] = args.per_player_selector_edge
    result['selector_edge_definition_order'] = 'before installed script; native first definition wins'
    phase = 'setup'
    try:
        for role in ('server', 'client'):
            lab = root / role
            lab.mkdir()
            labs[role] = lab
            config = CONFIG if role == xr_role else CONFIG.replace('ScreenBPP = 32', 'ScreenBPP = 8')
            (lab / 'eduke32.cfg').write_text(config)
            (lab / 'settings.cfg').write_text('// Private AA multiplayer observation.\n')
            (lab / 'autoexec.cfg').write_text('r_maxfps ' + (str(args.client_fps) if role == xr_role else '30') + '\n')
            wrapper = aa_wrapper(local_only=role == xr_role)
            if args.per_player_selector_edge:
                wrapper = 'gamevar oldbits 0 GAMEVAR_PERPLAYER\n' + wrapper
            (lab / 'aa_mp_observer.con').write_text(wrapper + policy_wrapper())
        common = ['-usecwd', '-nosetup', '-noautoload', '-nologo', '-ns', '-nm',
                  '-j', str(args.mod_root), '-g', str(args.mod_root / 'AA.grp'),
                  '-x', 'aa_mp_observer.con', '-h', 'duke3d.def']
        server_env = sanitised_env()
        server_env['EDUKE32_XR_TEST_SHOTS'] = '1'
        client_env = {k: v for k, v in os.environ.items() if not k.startswith('EDUKE32_XR')}
        client_env.update(DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy',
                          EDUKE32_XR='1', EDUKE32_XR_SINGLE_PASS='1', EDUKE32_XR_UI='2',
                          EDUKE32_XR_AIM='right', EDUKE32_XR_WEAPON='1', EDUKE32_XR_HAND_SHOTS='1',
                          EDUKE32_XR_TEST_INPUT='1', EDUKE32_XR_TEST_SHOTS='1', EDUKE32_XR_TEST_PVP='1',
                          EDUKE32_XR_WORLD_OUTPUT=str(labs[xr_role] / 'world'),
                          EDUKE32_XR_HUD_OUTPUT=str(labs[xr_role] / 'hud'))
        if args.xr_host:
            server_env, client_env = client_env, server_env
            fifo = labs['client'] / 'input.fifo'
            os.mkfifo(fifo, 0o600)
            input_fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
            client_env.update(LD_PRELOAD=str(args.input_helper), EDUKE32_TEST_SDL_INPUT=str(fifo))

        def launch(role, binary, options, env):
            log = (labs[role] / 'game.log').open('w')
            logs.append(log)
            process = subprocess.Popen([str(binary), *common, *options], cwd=labs[role], env=env,
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            processes[role] = process
            observers[role] = Observer(process, labs[role] / 'game.log')
            return observers[role]

        def wait_ready(observer, role, predicate, timeout):
            deadline, next_press = time.monotonic() + timeout, 0
            while time.monotonic() < deadline:
                text = observer.text()
                if predicate(text):
                    return
                if processes[role].poll() is not None:
                    raise RuntimeError(f'owned AA {role} exited before readiness')
                now = time.monotonic()
                if 'Per-map .art file' in text and now >= next_press:
                    if role == xr_role:
                        x11 = X11(args.display)
                        window, _ = x11.owned_window(processes[role].pid)
                        if window:
                            x11.press(window, 'Return', .08, True)
                    elif role == 'client' and input_fd is not None:
                        os.write(input_fd, b'key 40 1\n')
                        observer.pause(.12)
                        os.write(input_fd, b'key 40 0\n')
                    next_press = now + 1
                time.sleep(.05)
            raise RuntimeError(f'actual AA {role} readiness timed out')

        phase = 'native server entry'
        server = launch('server', args.client_binary if args.xr_host else args.binary,
                        ['-server' if args.xr_host else '-dedicated', '-port', str(args.port), '-c2', '-v1', '-l2', '-s1'], server_env)
        wait_ready(server, 'server', lambda text: bool(aa_samples(text)), 45)
        with Remote(args.remote_port) as remote:
            remote.neutral()
            phase = 'real AA client join'
            client = launch('client', args.binary if args.xr_host else args.client_binary,
                            ['-connect', f'127.0.0.1:{args.port}'], client_env)
            wait_ready(client, 'client', lambda text: SYNC in text and bool(aa_samples(text)), 45)
            tracked = observers[xr_role]
            index = 0 if args.xr_host else aa_samples(client.text())[-1]['player']
            result['tracked_index'] = index
            selected_rows = lambda observer: [row for row in aa_samples(observer.text()) if row['player'] == index]
            client.wait(lambda text: bool(selected_rows(client)), timeout=8)
            result['initial_inventory'] = {role: selected_rows(observer)[-1]
                                           for role, observer in observers.items()}
            result['checks']['initial_native_pistol_and_ammo_on_both_peers'] = all(
                row['currentweapon'] == 1 and row['ammo'] == 48 for row in result['initial_inventory'].values())
            result['stages']['before_selection'] = {'server': aa_samples(server.text())[-6:],
                                                    'client': aa_samples(client.text())[-3:]}
            phase = 'actual controller Duke and START selection'
            result['controller_stages'] = {}

            def check_stationary_cursor():
                # AA clamps each actor tick and divides horizontal input by 3.
                # Use this interior path, allowing one pixel of rounding; do
                # not claim arbitrary lossy/batched CON execution equivalence.
                remote.neutral()
                tracked.pause(1)
                sr, cr = selected_rows(server)[-1], selected_rows(client)[-1]
                result['stages']['stationary_cursor'] = {'server': sr, 'client': cr}
                result['checks']['stationary_cursor_converged'] = all(
                    abs(sr[key] - cr[key]) <= 1 for key in ('cursorx', 'cursory'))
                if not result['checks']['stationary_cursor_converged']:
                    raise RuntimeError('stationary AA cursor disagrees before START')

            selection = drive_character_selection(tracked, remote, result['controller_stages'], check_stationary_cursor)
            result['controller'] = selection
            remote.neutral()
            tracked.pause(1)
            selected = lambda row: row['startmode'] == 1 and row['charsel'] == 1 and row['pchar'] == 0
            server_rows = aa_samples(server.text())
            client_rows = selected_rows(client)
            authoritative = [row for row in server_rows if row['player'] == index]
            result['stages']['after_selection'] = {'server': server_rows[-12:], 'client': client_rows[-6:]}
            checks = result['checks']
            checks.update(native_tracked_index=index == (0 if args.xr_host else 1), native_join=SYNC in client.text(),
                          native_input_reaches_server=any(row['q16avel'] or row['q16horz'] for row in authoritative),
                          server_selected_same_character=bool(authoritative) and selected(authoritative[-1]),
                          client_selected_character=selected(client_rows[-1]))
            if not checks['server_selected_same_character']:
                raise RuntimeError('AA client confirmed selection but authoritative server state disagrees')
            phase = 'selected weapon state and fresh stereo image'
            server.wait(lambda text: any(row['player'] == index and row['ammo'] > 0 for row in aa_samples(text)), timeout=8)
            client.wait(lambda text: selected_rows(client)[-1]['ammo'] > 0, timeout=8)
            capture = post_gameplay_capture(tracked, labs[xr_role],
                max(map(int, PVP_CAPTURE.findall(tracked.text())), default=0), timeout=25)
            result['capture'] = capture
            sr = [row for row in aa_samples(server.text()) if row['player'] == index][-1]
            cr = selected_rows(client)[-1]
            result['weapon_state'] = {'server': sr, 'client': cr}
            checks.update(native_weapon_state_agrees=all(sr[k] == cr[k] for k in ('currentweapon', 'ammo', 'shoots', 'workslike', 'firedelay')),
                          fresh_stereo_gameplay=capture['eyes_distinct'] and capture['eyes_nonconstant'],
                          core_validation_clean=not re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)', tracked.text()))
            phase = 'actual AA tracked fire and native ammo authority'
            result['fire'] = fire_selected_weapon(server, client, tracked, remote, index)
            checks.update(result['fire']['checks'])
            phase = 'complete'
            result['passed'] = all(checks.values())
    except Exception as error:
        result['error'] = str(error)
    finally:
        result['phase'] = phase
        result['final_rows'] = {role: aa_samples(observer.text())[-16:] for role, observer in observers.items()}
        result['policy'] = {role: {'resets': [row for row in policy_rows(observer.text()) if row['reset_event']],
                                 'final': policy_rows(observer.text())[-8:]}
                            for role, observer in observers.items()}
        for process in reversed(list(processes.values())):
            stop(process)
        if input_fd is not None:
            os.close(input_fd)
        for log in logs:
            log.close()
    result['cleanup'] = all(process.poll() is not None for process in processes.values())
    result['sha256'] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in (args.binary, args.client_binary, Path(__file__), args.mod_root / 'scripts/AAGAME.CON')}
    (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
