#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Native tracked tripmine placement via real MP input in a GPU-denied lab.

The pose provider calls the existing native setter on the joining client.
Weapon timing, ammo, placement, collision and live actor replication are real.
No OpenXR, headset rendering, model or SPS coverage is claimed here.
"""
import argparse
import json
import os
from pathlib import Path
import re
import struct
import tempfile

from smoke_native_levels import assert_cpu_binary, assert_gpu_devices_absent
from smoke_pipebomb_native import Run, join, sha256
from smoke_tripmine_native import (configure_lab, latest_player, native_mines,
                                   post_returns, reexec_sandbox)

TRACE = re.compile(r'VR native tripmine: player=(\d+) index=(\d+) hand=(-?\d+),(-?\d+),(-?\d+) '
                   r'hit=(-?\d+),(-?\d+),(-?\d+) wall=(-?\d+) sector=(-?\d+) clamped=(\d) mode=(\d) fuse=(-?\d+)')
CASES = ('tracked', 'pitched', 'far', 'vertical', 'steep', 'forcefield', 'masked',
         'occupied', 'loss', 'commit-loss')


def traces(text):
    keys = ('player', 'index', 'hx', 'hy', 'hz', 'x', 'y', 'z', 'wall', 'sector', 'clamped', 'mode', 'fuse')
    return [dict(zip(keys, map(int, values))) for values in TRACE.findall(text)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'input-helper', 'grp', 'work-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--case', choices=CASES, default='tracked')
    parser.add_argument('--port', type=int, default=24820)
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--_sandboxed', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    for key in ('binary', 'input_helper', 'grp'):
        setattr(args, key, getattr(args, key).resolve())
    reexec_sandbox(args)
    assert_gpu_devices_absent()
    assert_cpu_binary(args.binary)
    root = Path(tempfile.mkdtemp(prefix='tripmine-hand-', dir=args.work_dir.resolve()))
    run = Run(args, root)
    run.env['EDUKE32_XR_TEST_SHOTS'] = '1'
    phase = 'setup'
    result = {'passed': False, 'case': args.case}
    try:
        for role in ('server', 'client'):
            lab = configure_lab(root, role, args, 512 if args.case == 'far' else 1024)
            run.labs[role] = lab
            if args.capture and role == 'client':
                with (lab / 'autoexec.cfg').open('a') as config:
                    config.write('r_drawweapon 0\n')  # Leave the placed world mine visible for F12.
            geometry = bytearray((lab / 'pipebomb.map').read_bytes())
            if args.case == 'steep':
                for offset in (26, 66):
                    struct.pack_into('<i', geometry, offset, -131072)
            if args.case == 'forcefield':
                struct.pack_into('<h', geometry, 104 + 32 + 18, 230)  # wall[1].overpicnum BIGFORCE
            if args.case == 'masked':
                struct.pack_into('<H', geometry, 104 + 32 + 14, 16)  # wall[1].cstat MASKED
            (lab / 'pipebomb.map').write_bytes(geometry)
            if args.case in ('loss', 'commit-loss'):
                # CON's ordinary weapon settings widen the native press/commit
                # interval so the runner can change tracking before FireDelay.
                with (lab / 'pipebomb_test.con').open('a') as source:
                    source.write('\nonevent EVENT_PROCESSINPUT\n setvar WEAPON8_FIREDELAY 18\n'
                                 ' setvar WEAPON8_TOTALTIME 30\nendevent\n')
        server = run.launch('server', ['-dedicated', '-c1', '-m', '-port', str(args.port), '-map', 'pipebomb.map'])
        server.wait(lambda text: 'Multiplayer server initialized.' in text, timeout=18)
        phase = 'native client join'
        player = join(run)
        client = run.observers['client']
        for observer in (server, client):
            observer.wait(lambda text: latest_player(text, player) is not None and
                          latest_player(text, player)['ammo'] == 6, timeout=12)
            observer.wait(lambda text: 'features=31' in text, timeout=6)

        def pose(valid=True, vertical=False):
            offset, direction = (192, 77, 1843), (32051, 6813, 0)
            if args.case in ('pitched', 'steep'):
                offset = (0, 77, 1843)
                direction = (28377, 0, -16384) if args.case == 'pitched' else (4096, 0, -32510)
            if args.case == 'vertical' or vertical:
                direction = (0, 0, -32767)
            values = (3, *offset, *direction) if valid else (1, 0, 0, 0, 0, 0, 0)
            os.write(run.writers['client'], ('pose ' + ' '.join(map(str, values)) + '\n').encode())

        def advance(ticks=20):
            tick = latest_player(server.text(), player)['tick']
            server.wait(lambda text: latest_player(text, player)['tick'] >= tick + ticks, timeout=6)

        def released():
            run.key('client', 228, False)
            advance(8)
            server.wait(lambda text: latest_player(text, player)['frame'] == 0, timeout=6)

        def fire():
            run.press('client', 228, .16)
            advance(20)

        pose()
        client.wait(lambda text: 'pose published flags=3' in text, timeout=5)
        advance(10)  # Real released input clears the existing readiness latch.
        before = latest_player(server.text(), player)
        server_offset, client_offset = len(server.text()), len(client.text())
        phase = 'native tracked placement'
        recovery = None
        if args.case in ('loss', 'commit-loss'):
            run.key('client', 228, True)
            client.wait(lambda text: 1 <= latest_player(text, player)['frame'] < 18, timeout=5)
            pose(valid=args.case != 'loss', vertical=args.case == 'commit-loss')
            advance(40)
            canceled = latest_player(server.text(), player)
            canceled_mines = native_mines(server.text()[server_offset:], player, 170)
            canceled_returns = post_returns(server.text()[server_offset:])
            pose()
            advance(40)  # Still holding: a recovered pose cannot create a shot.
            held = latest_player(server.text(), player)
            held_mines = native_mines(server.text()[server_offset:], player, 170)
            released()
            recovery = {'canceled': canceled, 'held': held,
                        'canceled_post_mines': canceled_mines, 'held_post_mines': held_mines,
                        'canceled_post_returns': canceled_returns}
            fire()
        else:
            fire()

        positive = args.case in ('tracked', 'pitched', 'occupied', 'loss', 'commit-loss')
        placed = native_mines(server.text()[server_offset:], player, 170)
        phase = 'native client observation'
        replicated = []
        if positive:
            server.wait(lambda text: bool(native_mines(text[server_offset:], player, 170)), timeout=6)
            placed = native_mines(server.text()[server_offset:], player, 170)
            index = placed[0]['index']
            client.wait(lambda text: any(row['index'] == index for row in
                        native_mines(text[client_offset:], player, 65)), timeout=8)
            replicated = [row for row in native_mines(client.text()[client_offset:], player, 65)
                          if row['index'] == index]
            if args.case == 'occupied':
                released()
                fire()
        client.wait(lambda text: latest_player(text, player)['ammo'] ==
                    latest_player(server.text(), player)['ammo'], timeout=6)
        after, client_after = latest_player(server.text(), player), latest_player(client.text(), player)
        placed = native_mines(server.text()[server_offset:], player, 170)
        hand = traces(server.text()[server_offset:])
        checks = {'native_join_and_tripmine_capability': player == 1 and 'features=31' in server.text(),
                  'native_client_ammo_matches_server': after['ammo'] == client_after['ammo'],
                  'native_server_simulated_input_after_fire': after['tick'] >= before['tick'] + 20,
                  'no_gpu_devices_or_libraries': True}
        if positive:
            checks.update(native_one_placement_and_one_ammo=len(placed) == len(hand) == 1 and after['ammo'] == 5,
                          native_owner_sector_and_normal=placed[0]['ownerplayer'] == player and
                          placed[0]['sector'] == 0 and placed[0]['angle'] == placed[0]['t5'] == 1024,
                          tracked_adapter_ran=bool(hand),
                          native_real_client_mine_replication=bool(replicated),
                          native_mine_position_replicates=any(all(abs(row[k] - placed[0][k]) <= 16
                                                                 for k in ('x', 'y', 'z')) for row in replicated))
            if hand:
                ray = hand[0]
                checks['hand_origin_inside_wall'] = ray['hx'] <= 1136 and ray['sector'] == 0
                # Build hitscan rounds oblique intersection coordinates toward
                # the wall interior; A_SetSprite then applies native -20 xvel
                # along the shoot angle before the mine takes its wall normal.
                checks['native_surface_hit_and_placement_offset'] = (
                    1151 <= ray['x'] <= 1152 and 9 <= ray['x'] - placed[0]['x'] <= 11)
                if args.case == 'pitched':
                    checks['physical_pitched_hit_matches_native_ray'] = (ray['z'] < ray['hz'] and
                        abs((ray['z'] - ray['hz']) * 28377 - (ray['x'] - ray['hx']) * -16384 * 16) < 28377 * 20)
                else:
                    checks['physical_heading_and_height_match_native_ray'] = (ray['z'] == ray['hz'] and
                        abs((ray['y'] - ray['hy']) * 32051 - (ray['x'] - ray['hx']) * 6813) < 32051 * 2 and
                        placed[0]['y'] != 4096 and placed[0]['z'] != -8928)
                    checks['through_wall_hand_origin_was_constrained'] = ray['clamped'] == 1
            if recovery:
                checks['loss_or_rejected_commit_keeps_ammo_without_actor'] = (
                    recovery['canceled']['ammo'] == 6 and not recovery['canceled_post_mines'])
                checks['held_recovery_keeps_ammo_without_actor'] = (
                    recovery['held']['ammo'] == 6 and not recovery['held_post_mines'])
                checks['release_and_new_press_places_once'] = len(placed) == 1 and after['ammo'] == 5
                if args.case == 'commit-loss':
                    checks['native_commit_ran_and_refunded_rejected_hit'] = -1 in recovery['canceled_post_returns']
            if args.case == 'occupied':
                checks['native_occupied_surface_rejects_second_press'] = len(placed) == 1 and after['ammo'] == 5
        else:
            checks.update(rejected_placement_keeps_ammo=after['ammo'] == before['ammo'] == 6,
                          rejected_placement_has_no_native_mine=not native_mines(server.text()[server_offset:], player)
                          and not native_mines(client.text()[client_offset:], player),
                          rejected_placement_has_no_hand_commit=not hand)
        screenshot = run.capture('client') if args.capture else None
        if screenshot:
            checks['native_F12_capture_written'] = (run.labs['client'] / 'screenshots' / screenshot).is_file()
        run.audit()
        result.update(passed=all(checks.values()), checks=checks, before=before, after=after,
                      client_after=client_after, placed=placed, replicated=replicated[-2:], hand_trace=hand,
                      recovery=recovery, screenshot=screenshot)
    except Exception as error:
        result.update(error=str(error), phase=phase)
    finally:
        run.close()
    result.update(binary_sha256=sha256(args.binary), evidence_directory=str(root),
                  qualification='CPU native MP with simulated native pose; no OpenXR/headset/model/SPS proof')
    (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
