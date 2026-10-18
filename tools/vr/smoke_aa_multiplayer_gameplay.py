#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual AA remote-controller selection against a native dedicated server.

Run inside software_xr_lab.py. Both peers include the owned installation's
unmodified scripts plus observations. No selection/gameplay values are seeded.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
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
ENEMY_FIELDS = ('tick', 'index', 'tile', 'health', 'x', 'y', 'z', 'sector', 'stat',
                'xrepeat', 'yrepeat', 'cstat')
ENEMY_STATE_FIELDS = ('action', 'actioncount', 'actionframe', 'actiontics')
ENEMY_ROW = re.compile(r'addlog aaenemy_(\w+)(?: \(player \d+\))? = (-?\d+)')
ENEMY_TILE = 16898  # NEWTROOPGUARD, defined by the installed AADEFS.CON.
ENEMY_SECTOR = 306
ENEMY_MAP_PATH = 'maps/oldeps/aa_enemy_e1l1.map'
# This is a solid part of E1L1's roof sector, verified from the owned v7 map.
# It remains near the stock pistol's previous wall-ray path without occupying a
# portal boundary or existing sprite position.
ENEMY_POSITION = (-30750, 8500)


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


def enemy_rows(text):
    """Read the native actor slot appended to the owned fixture map."""
    result, row = [], {}
    for name, value in ENEMY_ROW.findall(text):
        if name == 'tick':
            row = {}
        row[name] = int(value)
        if name == 'cstat' and all(key in row for key in ENEMY_FIELDS):
            result.append(row)
    return result


def enemy_wrapper(target_index):
    """Select the owned map copy in the native slot; observe its ordinary actor."""
    declarations = ''.join(f'gamevar aaenemy_{name} 0 1\n' for name in ENEMY_FIELDS + ENEMY_STATE_FIELDS)
    logs = ''.join(f' addlog aaenemy_{name}\n' for name in ENEMY_FIELDS[:-1] + ENEMY_STATE_FIELDS + ('cstat',))
    return (f'definelevelname 0 1 {ENEMY_MAP_PATH} 01:45 00:53 HOLLYWOOD HOLOCAUST\n'
            + declarations + f'''
appendevent EVENT_PROCESSINPUT
  addvar aaenemy_tick 1
  setvar aaenemy_index {target_index}
  getactor[aaenemy_index].picnum aaenemy_tile
  getactor[aaenemy_index].extra aaenemy_health
  getactor[aaenemy_index].x aaenemy_x
  getactor[aaenemy_index].y aaenemy_y
  getactor[aaenemy_index].z aaenemy_z
  getactor[aaenemy_index].sectnum aaenemy_sector
  getactor[aaenemy_index].statnum aaenemy_stat
  getactor[aaenemy_index].xrepeat aaenemy_xrepeat
  getactor[aaenemy_index].yrepeat aaenemy_yrepeat
  getactor[aaenemy_index].htg_t 4 aaenemy_action
  getactor[aaenemy_index].htg_t 2 aaenemy_actioncount
  getactor[aaenemy_index].htg_t 3 aaenemy_actionframe
  getactor[aaenemy_index].lotag aaenemy_actiontics
  getactor[aaenemy_index].cstat aaenemy_cstat
{logs}
endevent
''')


def _map_layout(data):
    """Return the v7 map sections without interpreting or rewriting them."""
    if len(data) < 22 or struct.unpack_from('<i', data)[0] != 7:
        raise RuntimeError('AA enemy fixture requires a v7 Build map')
    start_x, start_y, start_z, start_ang, start_sector = struct.unpack_from('<iiihh', data, 4)
    sectors = struct.unpack_from('<h', data, 20)[0]
    if sectors <= ENEMY_SECTOR:
        raise RuntimeError(f'map has no requested enemy sector {ENEMY_SECTOR}')
    sector_offset = 22
    walls_offset = sector_offset + sectors * 40
    if walls_offset + 2 > len(data):
        raise RuntimeError('truncated sector table in AA source map')
    walls = struct.unpack_from('<h', data, walls_offset)[0]
    if walls < 1:
        raise RuntimeError('invalid wall count in AA source map')
    sprite_count_offset = walls_offset + 2 + walls * 32
    if sprite_count_offset + 2 > len(data):
        raise RuntimeError('truncated wall table in AA source map')
    sprites = struct.unpack_from('<h', data, sprite_count_offset)[0]
    sprite_offset = sprite_count_offset + 2
    sprite_end = sprite_offset + sprites * 44
    if sprites < 0 or sprite_end > len(data):
        raise RuntimeError('truncated sprite table in AA source map')
    floor = struct.unpack_from('<i', data, sector_offset + ENEMY_SECTOR * 40 + 8)[0]
    return {'start': (start_x, start_y, start_z, start_ang, start_sector), 'sectors': sectors,
            'walls': walls, 'sprite_count': sprites, 'sprite_count_offset': sprite_count_offset,
            'sprite_offset': sprite_offset, 'sprite_end': sprite_end, 'floor': floor}


def _inside_sector(data, layout, sector, x, y):
    """Use the map's exact sector polygon before writing a placement."""
    sector_offset = 22 + sector * 40
    wallptr, wallnum = struct.unpack_from('<hh', data, sector_offset)
    inside = False
    for wall_index in range(wallptr, wallptr + wallnum):
        offset = 22 + layout['sectors'] * 40 + 2 + wall_index * 32
        ax, ay, point2 = struct.unpack_from('<iih', data, offset)
        bx, by = struct.unpack_from('<ii', data, 22 + layout['sectors'] * 40 + 2 + point2 * 32)
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return inside


def write_enemy_fixture(source, output):
    """Copy one owned AA map and append a single ordinary native enemy sprite.

    Existing map bytes (including a possible trailing extension) are preserved
    exactly. The observer reads this appended map slot from player input events,
    avoiding any dependency on the enemy's own event-dispatch flags.
    """
    data = source.read_bytes()
    layout = _map_layout(data)
    if not _inside_sector(data, layout, ENEMY_SECTOR, *ENEMY_POSITION):
        raise RuntimeError('chosen AA enemy position is outside its declared sector')
    enemy = struct.pack(
        '<iiiHhbBBBBBbbhhhhhhhhhh',
        *ENEMY_POSITION, layout['floor'], 257, ENEMY_TILE, 0, 0, 40, 0, 24, 22,
        0, 0, ENEMY_SECTOR, 0, 1536, -1, 0, 0, 0, 0, 0, -1,
    )
    amended = bytearray(data[:layout['sprite_end']] + enemy + data[layout['sprite_end']:])
    struct.pack_into('<h', amended, layout['sprite_count_offset'], layout['sprite_count'] + 1)
    if (bytes(amended[:layout['sprite_count_offset']]) != data[:layout['sprite_count_offset']] or
            bytes(amended[layout['sprite_count_offset'] + 2:layout['sprite_end']]) !=
            data[layout['sprite_count_offset'] + 2:layout['sprite_end']] or
            bytes(amended[layout['sprite_end'] + 44:]) != data[layout['sprite_end']:]):
        raise AssertionError('AA fixture changed native map data outside its sprite count/addition')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(amended)
    # Per-map ART follows the map basename. Keep the actual AA textures while
    # giving this fixture a unique native VFS path; installed files stay read-only.
    art_files = []
    for art in sorted(source.parent.glob(source.stem + '_*.art')):
        destination = output.with_name(output.stem + art.name[len(source.stem):])
        destination.symlink_to(art.resolve())
        art_files.append({'path': str(destination), 'source': str(art),
                          'sha256': hashlib.sha256(art.read_bytes()).hexdigest()})
    return {'source': str(source), 'source_sha256': hashlib.sha256(data).hexdigest(),
            'fixture_sha256': hashlib.sha256(amended).hexdigest(), 'target_index': layout['sprite_count'],
            'target_tile': ENEMY_TILE, 'position': [*ENEMY_POSITION, layout['floor']],
            'sector': ENEMY_SECTOR, 'source_start': list(layout['start']),
            'source_sprite_count': layout['sprite_count'], 'trailing_bytes_preserved': len(data) - layout['sprite_end'],
            'native_level_slot': [0, 1], 'per_map_art': art_files}


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


def _angle_delta(target, actual):
    """Return the shortest degree adjustment from a logged Build ray."""
    return (target - actual + 180) % 360 - 180


def fire_enemy_until_dead(server, client, tracked, remote, player, fixture_index, evidence):
    """Fire tracked AA pistol shots, steering from native target/ray observations.

    The aim loop does not seed enemy health, movement, weapons, inputs, or
    packets.  It only changes the real Monado controller pose between normal
    trigger presses after reading the target's native actor state.
    """
    player_rows = lambda observer: [row for row in aa_samples(observer.text()) if row['player'] == player]
    target_rows = lambda observer: enemy_rows(observer.text())
    tracked.wait(lambda text: player_rows(tracked)[-1]['weaponpos'] == 0 and
                 player_rows(tracked)[-1]['counter'] == 0, timeout=12)
    server.wait(lambda text: bool(target_rows(server)) and target_rows(server)[-1]['health'] > 0, timeout=12)
    client.wait(lambda text: bool(target_rows(client)) and target_rows(client)[-1]['health'] > 0, timeout=12)
    before = {'server': target_rows(server)[-1], 'client': target_rows(client)[-1],
              'ammo': {'server': player_rows(server)[-1], 'client': player_rows(client)[-1]}}
    if before['server']['index'] != fixture_index:
        raise RuntimeError(f'fixture observer selected sprite {before["server"]["index"]}, expected {fixture_index}')
    for role in ('server', 'client'):
        target = before[role]
        if (target['tile'] != ENEMY_TILE or target['sector'] != ENEMY_SECTOR or
                (target['x'], target['y']) != ENEMY_POSITION or target['health'] <= 0):
            raise RuntimeError(f'{role} did not observe the live map-authored NEWTROOPGUARD at the fixture position')
    remote.neutral()
    hand = remote.packet.right
    hand.pose.position.x, hand.pose.position.y, hand.pose.position.z = .2, 1.3, -.5
    yaw, pitch = 12.0, -10.0
    hand.pose.orientation = orientation(yaw, pitch)
    remote.send()
    tracked.pause(.4)
    attempts, all_rays, target_hits = [], [], []
    evidence.update(stage='tracked firing', before=before, attempts=attempts, authoritative_tracked_hits=all_rays)
    for attempt in range(12):
        target = target_rows(server)[-1]
        # The first pose follows the known AA stock-start ray.  Thereafter use
        # the real prior ray's origin/vector to correct both axes toward the
        # actor's observed body centre while the native AI is free to move.
        prior = all_rays[-1] if all_rays else None
        if prior:
            desired_yaw = math.degrees(math.atan2(target['y'] - prior['y'], target['x'] - prior['x']))
            actual_yaw = math.degrees(math.atan2(prior['dy'], prior['dx']))
            yaw += _angle_delta(desired_yaw, actual_yaw)
            horizontal = math.hypot(target['x'] - prior['x'], target['y'] - prior['y'])
            if horizontal:
                body_z = target['z'] - max(1024, target['yrepeat'] * 192)
                # Native Build Z coordinates/vectors have sixteen times the
                # scale of horizontal coordinates. Controller angles do not.
                desired_pitch = -math.degrees(math.atan2((body_z - prior['z']) / 16, horizontal))
                actual_pitch = math.degrees(math.atan2(-prior['dz'] / 16, math.hypot(prior['dx'], prior['dy'])))
                pitch = max(-80.0, min(80.0, pitch + desired_pitch - actual_pitch))
        hand.pose.orientation = orientation(yaw, pitch)
        remote.send()
        offsets = {'server': len(server.text()), 'client': len(client.text()), 'tracked': len(tracked.text())}
        ammunition = player_rows(server)[-1]['ammo']
        hand.trigger_value, hand.trigger_click = 1, True
        remote.send()
        try:
            server.wait(lambda text: any(row['player'] == player and row['shots'] > before['ammo']['server']['shots'] + attempt
                                        and row['ammo'] < ammunition
                                        for row in aa_samples(text[offsets['server']:])), timeout=8)
        finally:
            hand.trigger_value, hand.trigger_click = 0, False
            remote.send()
        server.wait(lambda text: player_rows(server)[-1]['counter'] == 0 and
                    not (player_rows(server)[-1]['bits'] & 4), timeout=8)
        observed = rays(server.text()[offsets['server']:], player)
        all_rays.extend(observed)
        hit = [ray for ray in observed if ray['sprite'] == fixture_index]
        target_hits.extend(hit)
        latest = target_rows(server)[-1]
        attempts.append({'number': attempt + 1, 'pose_degrees': {'yaw': yaw, 'pitch': pitch},
                         'target_before': target, 'target_after': latest, 'rays': observed,
                         'fixture_hits': hit})
        if hit and latest['health'] <= 0:
            break
        if player_rows(server)[-1]['ammo'] <= 0:
            break
        tracked.pause(.15)
    evidence['stage'] = 'native health loss and death transition'
    server.wait(lambda text: target_rows(server)[-1]['health'] <= 0, timeout=6)
    def corpse_converged(_text):
        authority, replica = target_rows(server)[-1], target_rows(client)[-1]
        # AA may briefly report negative overkill before its native death
        # state normalizes health to zero and clears collision. Do not freeze
        # that transient value as a value every client must receive.
        return (authority['health'] <= 0 and not (authority['cstat'] & 257)
                and all(authority[key] == replica[key]
                        for key in ('tile', 'health', 'x', 'y', 'z', 'sector', 'cstat')))
    evidence['stage'] = 'native corpse collision and position convergence'
    try:
        # Native AA suffering deliberately keeps collision until actioncount14,
        # roughly 84 simulation updates. The CPU XR lab can run below real time.
        client.wait(corpse_converged, timeout=30)
    finally:
        evidence['latest'] = {role: target_rows(observer)[-1]
                              for role, observer in (('server', server), ('client', client))}
    server_after = target_rows(server)[-1]
    client_after = target_rows(client)[-1]
    server_ammo, client_ammo = player_rows(server)[-1], player_rows(client)[-1]
    return {'stage': 'complete', 'before': before, 'after': {'server': server_after, 'client': client_after,
                                         'ammo': {'server': server_ammo, 'client': client_ammo}},
            'attempts': attempts, 'authoritative_tracked_hits': all_rays,
            'checks': {'fixture_target_observed_on_native_server': bool(target_rows(server)),
                       'fixture_target_observed_on_native_client': bool(target_rows(client)),
                       'fixture_target_initial_identity_matches_map': all(
                           before[role]['tile'] == ENEMY_TILE and before[role]['sector'] == ENEMY_SECTOR and
                           (before[role]['x'], before[role]['y']) == ENEMY_POSITION
                           for role in ('server', 'client')),
                       'authoritative_hand_hits_fixture_sprite': bool(target_hits),
                       'native_enemy_health_lost': server_after['health'] < before['server']['health'],
                       'native_enemy_death_converged': server_after['health'] <= 0 and
                           client_after['health'] == server_after['health'],
                       'native_corpse_collision_and_position_converged': not (server_after['cstat'] & 257) and
                           all(server_after[key] == client_after[key]
                               for key in ('tile', 'x', 'y', 'z', 'sector', 'cstat')),
                       'native_ammo_decreased_and_converged': 0 <= server_ammo['ammo'] < before['ammo']['server']['ammo'] and
                           client_ammo['ammo'] == server_ammo['ammo'],
                       'actual_AA_native_weapon_fired': server_ammo['shots'] > before['ammo']['server']['shots'],
                       'actual_tracked_player_trigger_seen': any(row['player'] == player and row['bits'] & 4
                           for row in aa_samples(tracked.text()[offsets['tracked']:]))}}


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
    parser.add_argument('--compat-con', type=Path,
                        help='Read-only production AA main CON loaded with native -x on both peers')
    parser.add_argument('--enemy-fixture', action='store_true',
                        help='copy an owned E1L1 v7 map into each lab and append one observed native NEWTROOPGUARD')
    parser.add_argument('--enemy-map', type=Path,
                        help='owned E1L1 map source required by --enemy-fixture')
    args = parser.parse_args()
    if args.xr_host and (not args.input_helper or not args.input_helper.is_file()):
        parser.error('--xr-host requires --input-helper')
    if args.input_helper:
        args.input_helper = args.input_helper.resolve()
    for name in ('binary', 'client_binary', 'mod_root', 'work_dir'):
        setattr(args, name, getattr(args, name).resolve())
    if args.compat_con:
        args.compat_con = args.compat_con.resolve()
        if not args.compat_con.is_file():
            parser.error('missing --compat-con: '+str(args.compat_con))
    if args.compat_con and args.per_player_selector_edge:
        parser.error('--compat-con cannot be combined with --per-player-selector-edge')
    if args.enemy_fixture:
        if not args.compat_con:
            parser.error('--enemy-fixture requires --compat-con so installed AA actor scripts remain the gameplay source')
        if not args.enemy_map:
            parser.error('--enemy-fixture requires --enemy-map')
        args.enemy_map = args.enemy_map.resolve()
        if not args.enemy_map.is_file():
            parser.error('missing --enemy-map: ' + str(args.enemy_map))
    assert_gpu_devices_absent()
    assert_cpu_binary(args.binary)
    xr_role = 'server' if args.xr_host else 'client'
    root = Path(tempfile.mkdtemp(prefix='aa-mp-gameplay-', dir=args.work_dir))
    processes, observers, logs, labs = {}, {}, [], {}
    input_fd = None
    result = {'passed': False, 'checks': {}, 'stages': {}, 'evidence_directory': str(root),
              'qualification': 'Actual AA selection, tracked firing and native ammo authority; not full campaign or SPS acceptance.',
              'xr_role': xr_role}
    main_con = args.compat_con.name if args.compat_con else 'aa_mp_observer.con'
    observer_con = 'aa_mp_observer.con' if args.compat_con else None
    result['con_launch'] = {'main_cli': ['-x', main_con],
                            'observer_cli': ['-mx', observer_con] if observer_con else []}
    if args.compat_con:
        result['compat_con'] = {'path': str(args.compat_con),
                                 'sha256': hashlib.sha256(args.compat_con.read_bytes()).hexdigest()}
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
            wrapper = aa_wrapper(local_only=role == xr_role, include_game=not bool(args.compat_con))
            if args.per_player_selector_edge:
                wrapper = 'gamevar oldbits 0 GAMEVAR_PERPLAYER\n' + wrapper
            if args.enemy_fixture:
                # E1L1.MAP also exists under the installed -j directory.
                # Use an otherwise-unreferenced basename so the native VFS
                # cannot silently select that unmodified loose copy.
                destination = lab / ENEMY_MAP_PATH
                fixture = write_enemy_fixture(args.enemy_map, destination)
                result.setdefault('enemy_fixture', {'map': fixture, 'copies': {}})['copies'][role] = {
                    'path': str(destination), 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}
                wrapper += enemy_wrapper(fixture['target_index'])
            (lab / 'aa_mp_observer.con').write_text(wrapper + policy_wrapper())
        common = ['-usecwd', '-nosetup', '-noautoload', '-nologo', '-ns', '-nm',
                  '-j', str(args.mod_root)]
        if args.compat_con:
            common.extend(('-j', str(args.compat_con.parent)))
        common.extend(('-g', str(args.mod_root / 'AA.grp'), '-x', main_con))
        if observer_con:
            common.extend(('-mx', observer_con))
        common.extend(('-h', 'duke3d.def'))
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
            # AA's installed directory is needed for its original scripts and
            # assets; the lab directory supplies the uniquely named map copy.
            fixture_search = ['-j', str(labs[role])] if args.enemy_fixture else []
            process = subprocess.Popen([str(binary), *common, *fixture_search, *options], cwd=labs[role], env=env,
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
            if args.enemy_fixture:
                result['fire'] = {}
                result['fire'] = fire_enemy_until_dead(
                    server, client, tracked, remote, index, result['enemy_fixture']['map']['target_index'], result['fire'])
            else:
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
