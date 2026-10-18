#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual AA native multiplayer join, with private CPU-only rendering/input.

The wrapper includes the user's unmodified AA scripts and only observes state.
This qualifies startup/join, not AA character selection or campaign combat.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

from PIL import Image, ImageChops
from smoke_multiplayer import CONFIG
from smoke_native_levels import assert_cpu_binary, sanitised_env
from smoke_pistol_reload_native import Run, sha256

FIELDS = ('tick', 'player', 'startmode', 'charsel', 'pchar', 'gm', 'weapon',
          'shoots', 'clip', 'ammo', 'x', 'y', 'z', 'live_events', 'reserved_events', 'bits')
ROW = re.compile(r'addlog aamp_(\w+)(?: \(player \d+\))? = (-?\d+)')
SYNC = 'Multiplayer client level synchronization complete.'
WRAPPER = 'include scripts/AAGAME.CON\n' + ''.join(
    f'gamevar aamp_{name} 0 524289\n' for name in FIELDS) + '''gamevar aamp_event_stat 0 524288
appendevent EVENT_GAME
 getactor[THISACTOR].statnum aamp_event_stat
 ifvare aamp_event_stat 1023 addvar aamp_reserved_events 1 else addvar aamp_live_events 1
endevent
appendevent EVENT_PROCESSINPUT
 addvar aamp_tick 1
 getactor[THISACTOR].yvel aamp_player
 setvarvar aamp_startmode startmode
 setvarvar aamp_charsel charsel
 setvarvar aamp_pchar pchar
 getplayer[THISACTOR].gm aamp_gm
 getplayer[THISACTOR].curr_weapon aamp_weapon
 setvarvar aamp_shoots WEAPON1_SHOOTS
 setvarvar aamp_clip WEAPON1_CLIP
 getplayer[THISACTOR].ammo_amount PISTOL_WEAPON aamp_ammo
 getplayer[THISACTOR].posx aamp_x
 getplayer[THISACTOR].posy aamp_y
 getplayer[THISACTOR].posz aamp_z
 getinput[].bits aamp_bits
''' + ''.join(f' addlog aamp_{name}\n' for name in FIELDS) + 'endevent\n'


def rows(text, player=None):
    result, row = [], {}
    for key, value in ROW.findall(text):
        if key == 'tick':
            row = {}
        if key in FIELDS:
            row[key] = int(value)
        if key == 'bits' and len(row) == len(FIELDS):
            if player is None or row['player'] == player:
                result.append(row)
    return result


def sandbox(args):
    if args._sandboxed:
        return
    args.work_dir.mkdir(parents=True, exist_ok=True)
    env = sanitised_env()
    cmd = ['bwrap', '--ro-bind', '/', '/', '--dev', '/dev', '--proc', '/proc',
           '--unshare-pid', '--unshare-net', '--bind', str(args.work_dir), str(args.work_dir),
           '--chdir', str(Path.cwd()), '--clearenv']
    for name in ('PATH', 'LANG', 'LC_ALL', 'TZ'):
        if name in env:
            cmd += ['--setenv', name, env[name]]
    cmd += ['nice', '-n', '10', sys.executable, str(Path(__file__).resolve()),
            *sys.argv[1:], '--_sandboxed']
    os.execvpe('bwrap', cmd, env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--input-helper', type=Path, required=True)
    parser.add_argument('--mod', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=24921)
    parser.add_argument('--join', choices=('early', 'late'), default='early')
    parser.add_argument('--_sandboxed', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    for name in ('binary', 'input_helper', 'mod', 'work_dir'):
        setattr(args, name, getattr(args, name).resolve())
    sandbox(args)
    assert_cpu_binary(args.binary)
    root = Path(tempfile.mkdtemp(prefix='aa-native-join-', dir=args.work_dir))
    run = Run(args, root, args.binary, con_file='aa_native_join.con')
    result = {'passed': False, 'join': args.join, 'binary_sha256': sha256(args.binary),
              'renderer': 'CPU classic (no VR/SPS proof)', 'evidence_directory': str(root),
              'wrapper_sha256': hashlib.sha256(WRAPPER.encode()).hexdigest(),
              'checks': {}, 'states': {}}
    phase = 'setup'
    try:
        for role in ('server', 'client'):
            lab = root / role
            lab.mkdir()
            run.labs[role] = lab
            (lab / 'eduke32.cfg').write_text(CONFIG.replace('ScreenBPP = 32', 'ScreenBPP = 8'))
            (lab / 'settings.cfg').write_text('// Owned AA join test.\n')
            (lab / 'autoexec.cfg').write_text('r_maxfps 15\n')
            (lab / 'aa_native_join.con').write_text(WRAPPER)
        common = ['-j', str(args.mod), '-g', str(args.mod / 'AA.grp'), '-h', 'duke3d.def']
        phase = 'server startup'
        server = run.launch('server', common + ['-dedicated', '-port', str(args.port),
                                               '-c2', '-v1', '-l2', '-s1'])
        server.wait(lambda t: 'Multiplayer server initialized.' in t, timeout=18)
        if args.join == 'late':
            server.wait(lambda t: bool(rows(t, 0)), timeout=25)
        result['server_in_game_at_client_launch'] = bool(rows(server.text(), 0))
        phase = 'actual AA client join'
        client = run.launch('client', common + ['-connect', f'127.0.0.1:{args.port}'])
        # AA's native finite entry screen can await Return. This drives only the
        # owned SDL-dummy client, never the user's desktop or CON game state.
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            text = client.text()
            run.audit()
            if SYNC in text and rows(text, 1):
                break
            if 'Per-map .art file' in text:
                run.key(40, True)
                client.pause(.12)
                run.key(40, False)
            client.pause(.25)
        else:
            raise RuntimeError('actual AA client did not reach native join/input barrier')
        server.wait(lambda t: bool(rows(t, 1)), timeout=10)
        phase = 'native private screenshot'
        run.key(69, True)  # SDL_SCANCODE_F12
        try:
            client.wait(lambda t: 'Saved screenshot to screenshots/' in t and bool(list((run.labs['client'] / 'screenshots').glob('duke*.png'))), timeout=12)
        finally:
            run.key(69, False)
        image_path = sorted((run.labs['client'] / 'screenshots').glob('duke*.png'))[-1]
        with Image.open(image_path) as image:
            image = image.convert('RGB')
            nonconstant = ImageChops.difference(image, Image.new('RGB', image.size, image.getpixel((0, 0)))).getbbox() is not None
            dimensions = list(image.size)
        client.pause(.35)
        run.audit()
        server_text, client_text = server.text(), client.text()
        result['states'] = {'server_player0': rows(server_text, 0)[-2:],
                            'server_player1': rows(server_text, 1)[-2:],
                            'client_player1': rows(client_text, 1)[-2:]}
        checks = {'requested_join_schedule': result['server_in_game_at_client_launch'] == (args.join == 'late'),
                  'native_level_synchronization': SYNC in client_text,
                  'real_remote_player_reaches_both_simulations': bool(rows(server_text, 1) and rows(client_text, 1)),
                  'client_loaded_actual_AA_Hollywood_art': '/maps/oldeps/E1L1_00.art loaded' in client_text,
                  'native_F12_nonconstant': nonconstant and dimensions == [640, 480],
                  'live_CON_events_continue': any(r['live_events'] > 0 for r in rows(server_text)),
                  'network_reserve_slots_excluded_from_CON': all(r['reserved_events'] == 0 for r in rows(server_text) + rows(client_text)),
                  'no_GPU_devices_or_libraries': True}
        result.update(passed=all(checks.values()), checks=checks, screenshot=str(image_path), phase='complete')
    except Exception as error:
        result.update(phase=phase, error=str(error))
    finally:
        run.close()
    for role in run.labs:
        text = (run.labs[role] / 'game.log').read_text(errors='replace')
        result.setdefault('observations', {})[role] = {'sync': SYNC in text, 'rows': rows(text)[-4:]}
    result['exit_codes'] = {role: p.returncode for role, p in run.processes.items()}
    result['cleanup'] = all(p.poll() is not None for p in run.processes.values())
    (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] and result['cleanup'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
