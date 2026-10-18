#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Real native MP melee with simulated hand poses in a GPU-denied CPU lab."""
import argparse
import json
import os
from pathlib import Path
import re
import struct
import tempfile

from smoke_hand_shots import room
from smoke_melee_native import configure_lab, knees, last, players
from smoke_native_levels import assert_cpu_binary, assert_gpu_devices_absent
from smoke_pipebomb_native import Run, join, sha256
from smoke_tripmine_native import reexec_sandbox

TRACE = re.compile(r'VR native melee: player=(\d+) quick=(\d) hand=(-?\d+),(-?\d+),(-?\d+) '
                   r'hit=(-?\d+),(-?\d+),(-?\d+) sector=(-?\d+) target=(-?\d+) wall=(-?\d+) '
                   r'angle=(-?\d+) clamped=(\d) inRange=(\d)')
CASES = ('selected', 'quick', 'pitched', 'wall', 'far', 'vertical', 'vertical-far',
         'loss', 'quick-loss', 'steroids')


def traces(text):
    keys = ('player', 'quick', 'hx', 'hy', 'hz', 'x', 'y', 'z', 'sector', 'target', 'wall', 'angle', 'clamped', 'inRange')
    return [dict(zip(keys, map(int, row))) for row in TRACE.findall(text)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'input-helper', 'grp', 'work-dir'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--case', choices=CASES, default='selected')
    parser.add_argument('--port', type=int, default=24920)
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--_sandboxed', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    for key in ('binary', 'input_helper', 'grp'):
        setattr(args, key, getattr(args, key).resolve())
    reexec_sandbox(args)
    assert_gpu_devices_absent()
    assert_cpu_binary(args.binary)
    root = Path(tempfile.mkdtemp(prefix='melee-hand-', dir=args.work_dir.resolve()))
    run, phase = Run(args, root), 'setup'
    run.env['EDUKE32_XR_TEST_SHOTS'] = '1'
    result = {'passed': False, 'case': args.case}
    quick = args.case in ('quick', 'quick-loss')
    lost = args.case in ('loss', 'quick-loss')
    scan, weapon = (20, 1) if quick else (228, 0)
    try:
        for role in ('server', 'client'):
            lab = configure_lab(root, role, args, weapon, 1024, 0)
            run.labs[role] = lab
            source = (lab / 'pipebomb_test.con').read_text()
            source = source.replace('gamevar vrmelee_target_y 4120 0',
                                    'gamevar vrmelee_target_y ' + ('4173' if args.case == 'pitched' else '4255') + ' 0')
            if args.case == 'far':
                source = source.replace('gamevar vrmelee_target_x 1600 0', 'gamevar vrmelee_target_x 3000 0')
            if args.case == 'loss':
                source += '\nonevent EVENT_PROCESSINPUT\n setvar WEAPON0_FIREDELAY 18\n setvar WEAPON0_TOTALTIME 30\nendevent\n'
            if args.case == 'steroids':
                # Join initialization can overwrite inventory prepared at the
                # first input tick. Set this controlled native inventory at
                # the shot event, before the original knee damage routine.
                source += '\nonevent EVENT_PREWEAPONSHOOT\n setplayer[THISACTOR].steroids_amount 100\nendevent\n'
            (lab / 'pipebomb_test.con').write_text(source)
            geometry = bytearray(room(args.case == 'wall'))
            if args.case in ('vertical', 'vertical-far'):
                for offset in (26, 66):
                    struct.pack_into('<i', geometry, offset, -16384 if args.case == 'vertical' else -65536)
            (lab / 'pipebomb.map').write_bytes(geometry)
        server = run.launch('server', ['-dedicated', '-c1', '-m', '-port', str(args.port), '-map', 'pipebomb.map'])
        server.wait(lambda text: 'Multiplayer server initialized.' in text, timeout=18)
        phase = 'native client join'
        shooter = join(run)
        client = run.observers['client']
        for observer in (server, client):
            observer.wait(lambda text: last(text, shooter) is not None and last(text, 0) is not None and
                          last(text, shooter)['weapon'] == weapon, timeout=12)
            observer.wait(lambda text: 'features=63' in text, timeout=6)

        def pose(valid=True):
            direction = (32051, 6813, 0)
            if args.case == 'pitched':
                direction = (28377, 0, 16384)
            if args.case in ('vertical', 'vertical-far'):
                direction = (0, 0, -32767)
            values = (3, 192, 77, 1843, *direction) if valid else (1, 0, 0, 0, 0, 0, 0)
            os.write(run.writers['client'], ('pose ' + ' '.join(map(str, values)) + '\n').encode())

        def advance(ticks):
            tick = last(server.text(), shooter)['tick']
            server.wait(lambda text: last(text, shooter)['tick'] >= tick + ticks, timeout=8)

        def fire():
            offset = len(client.text())
            run.key('client', scan, True)
            client.wait(lambda text: any(row['quick'] >= 10 if quick else row['frame'] >= 7
                                         for row in players(text[offset:], shooter)), timeout=6)
            run.key('client', scan, False)
            advance(25)

        pose()
        client.wait(lambda text: 'pose published flags=3' in text, timeout=5)
        advance(10)
        before, target_before = last(server.text(), shooter), last(server.text(), 0)
        server_offset, client_offset = len(server.text()), len(client.text())
        phase = 'native tracked melee input'
        recovery = None
        if lost:
            offset = len(client.text())
            run.key('client', scan, True)
            client.wait(lambda text: any(10 <= row['quick'] <= 14 if quick else 1 <= row['frame'] < 18
                                         for row in players(text[offset:], shooter)), timeout=6)
            pose(False)
            advance(40)
            canceled = {'knees': knees(server.text()[server_offset:], shooter),
                        'target': last(server.text(), 0), 'shooter': last(server.text(), shooter)}
            held_offset = len(server.text())
            pose()
            advance(40)
            held = {'knees': knees(server.text()[server_offset:], shooter), 'target': last(server.text(), 0),
                    'inputs': players(server.text()[held_offset:], shooter)}
            run.key('client', scan, False)
            advance(8)
            server.wait(lambda text: last(text, shooter)['frame'] == last(text, shooter)['quick'] == 0, timeout=6)
            recovery = {'canceled': canceled, 'held': held}
        fire()
        damage_expected = args.case not in ('wall', 'far', 'vertical', 'vertical-far')
        effect_expected = args.case not in ('far', 'vertical-far')
        if damage_expected:
            phase = 'actual native target damage'
            server.wait(lambda text: last(text, 0)['health'] < target_before['health'], timeout=6)
        phase = 'native target/ammo convergence'
        client.wait(lambda text: last(text, 0)['health'] == last(server.text(), 0)['health'] and
                    last(text, shooter)['ammo1'] == last(server.text(), shooter)['ammo1'], timeout=8)
        after, target_after = last(server.text(), shooter), last(server.text(), 0)
        impacts, hand = knees(server.text()[server_offset:], shooter), traces(server.text()[server_offset:])
        checks = {'actual_native_client_and_melee_capability': shooter == 1 and 'features=63' in server.text(),
                  'native_knee_and_pistol_ammo_unchanged': (after['ammo0'], after['ammo1']) == (before['ammo0'], before['ammo1']),
                  'native_target_health_replicates': last(client.text(), 0)['health'] == target_after['health'],
                  'actual_tracked_native_hit_attempt': bool(hand),
                  'native_one_impact_or_range_rejection': len(impacts) == (1 if effect_expected else 0),
                  'native_owner_matches_joining_client': all(r['owner'] == before['index'] for r in impacts),
                  'no_gpu_devices_or_libraries': True}
        checks['native_real_target_damage' if damage_expected else 'native_target_undamaged'] = (
            target_after['health'] < target_before['health'] if damage_expected else target_after['health'] == target_before['health'])
        if hand:
            ray = hand[-1]
            checks['native_quick_or_selected_path'] = ray['quick'] == int(quick)
            checks['native_physical_reach_gate'] = ray['inRange'] == int(effect_expected)
            checks['native_effect_matches_hit'] = all(all(r[k] == ray[k] for k in ('x', 'y', 'z', 'sector', 'angle')) for r in impacts)
            if damage_expected:
                checks['native_hit_is_actual_target_player'] = ray['target'] == target_before['index']
            if args.case in ('vertical', 'vertical-far'):
                checks['native_vertical_ray_preserves_xy'] = ray['x'] == ray['hx'] and ray['y'] == ray['hy'] and ray['z'] < ray['hz']
            elif args.case == 'pitched':
                checks['native_pitched_hit_matches_physical_ray'] = (ray['z'] > ray['hz'] and
                    abs((ray['z']-ray['hz'])*28377-(ray['x']-ray['hx'])*16384*16) < 28377*20)
            else:
                checks['native_horizontal_hit_matches_physical_ray'] = (ray['z'] == ray['hz'] and
                    abs((ray['y']-ray['hy'])*32051-(ray['x']-ray['hx'])*6813) < 32051*2)
            if args.case == 'wall':
                checks['closed_wall_constrains_hand_and_stops_target_damage'] = ray['clamped'] == 1 and ray['hx'] <= 1136 and ray['wall'] == 1
            else:
                checks['native_resolved_hand_crosses_open_portal'] = ray['hx'] == 1216 and ray['hy'] == 4173 and ray['sector'] == 1
        if recovery:
            checks['loss_before_commit_has_no_impact_or_damage'] = not recovery['canceled']['knees'] and recovery['canceled']['target']['health'] == target_before['health']
            checks['native_lost_animation_finishes_without_queued_restarts'] = recovery['canceled']['shooter']['quick'] == recovery['canceled']['shooter']['frame'] == 0
            checks['held_recovery_has_no_impact_or_damage'] = not recovery['held']['knees'] and recovery['held']['target']['health'] == target_before['health']
            mask = (1 << 22) if quick else 4
            checks['held_recovery_suppresses_every_native_action_input'] = bool(recovery['held']['inputs']) and all(not(r['bits'] & mask) for r in recovery['held']['inputs'])
            checks['release_and_new_press_hits_once'] = len(impacts) == 1 and target_after['health'] < target_before['health']
        if args.case == 'steroids':
            # Real player mitigation can change health loss. Require damage
            # beyond the stock unboosted knee's10+7 maximum, not exact RNG.
            checks['native_steroids_damage_bonus_applies'] = any(r['steroids_now'] > 0 for r in players(server.text()[server_offset:], shooter)) and target_before['health'] - target_after['health'] > 17
        screenshot = run.capture('client') if args.capture else None
        run.audit()
        result.update(passed=all(checks.values()), checks=checks, before=before, after=after,
                      target_before=target_before, target_after=target_after, client_target_after=last(client.text(), 0),
                      impacts=impacts, native_client_knees=knees(client.text()[client_offset:], shooter),
                      hand_trace=hand, recovery=recovery, screenshot=screenshot,
                      controlled_steroids_at_PREWEAPONSHOOT=100 if args.case == 'steroids' else None)
    except Exception as error:
        result.update(error=str(error), phase=phase)
    finally:
        run.close()
    result.update(binary_sha256=sha256(args.binary), evidence_directory=str(root),
                  qualification='CPU-native MP and simulated native hand pose; no OpenXR/button/headset/model/SPS proof')
    (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
