#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Stock World Tour flame weapon through real GPU-denied native multiplayer.

Uses the user's installed WT CON/ART read-only. No replacement weapon defaults,
actor simulation, shot injection, OpenXR or headset qualification is implied.
"""
import argparse
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile

from smoke_devastator_cpu import last, shots, count
from smoke_native_levels import assert_cpu_binary, assert_gpu_devices_absent, sanitised_env
from smoke_pipebomb_native import Run, write_lab, join, sha256
from smoke_hand_shots import room


def sandbox(args):
    if args._sandboxed:
        return
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    env = sanitised_env()
    command = ['bwrap', '--ro-bind', '/', '/', '--dev', '/dev', '--proc', '/proc',
               '--unshare-pid', '--bind', str(work), str(work), '--chdir', str(Path.cwd()), '--clearenv']
    for key in ('PATH', 'LANG', 'LC_ALL', 'TZ'):
        if key in env:
            command += ['--setenv', key, env[key]]
    command += [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], '--_sandboxed']
    os.execvpe('bwrap', command, env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'input-helper', 'grp', 'work-dir'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--case', choices=('flat', 'tracked', 'wall', 'vertical', 'loss', 'underwater', 'cancel'), default='tracked')
    parser.add_argument('--reference-result', type=Path)
    parser.add_argument('--native-reference', action='store_true', help='Flat reference binary predating snapshot diagnostics')
    parser.add_argument('--port', type=int, default=24921)
    parser.add_argument('--_sandboxed', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.reference_result and args.case != 'flat':
        parser.error('--reference-result requires --case flat')
    if args.native_reference and args.case != 'flat':
        parser.error('--native-reference requires --case flat')
    for key in ('binary', 'input_helper', 'grp'):
        setattr(args, key, getattr(args, key).resolve())
    sandbox(args)
    assert_gpu_devices_absent()
    assert_cpu_binary(args.binary)
    root = Path(tempfile.mkdtemp(prefix='flame-', dir=args.work_dir.resolve()))
    run = Run(args, root)
    run.env['EDUKE32_XR_TEST_SHOTS'] = '1'
    phase = 'setup'
    result = {'passed': False}
    try:
        sources = []
        for role in ('server', 'client'):
            lab = write_lab(root, role, args.grp)
            run.labs[role] = lab
            # GRP contains Atomic scripts. WT's loose files are required to
            # establish script version16, native FIREBALL actors and weapon12.
            for source in sorted(args.grp.parent.iterdir()):
                if source.suffix.upper() in ('.CON', '.ART'):
                    (lab/source.name).symlink_to(source)
                    sources.append({'name': source.name, 'sha256': sha256(source)})
            fixture = (Path(__file__).parent/'fixtures/hand_weapon_test.con').read_text()
            fixture = fixture.replace('gamevar vrw_weapon 7 0', 'gamevar vrw_weapon 12 0')
            fixture = re.sub(r'\bRPG\b', 'FIREBALL', fixture)
            fixture = fixture.replace('setactor[THISACTOR].extra 240', 'setactor[THISACTOR].extra 1000')
            fixture = fixture.replace('setplayer[THISACTOR].last_extra 240', 'setplayer[THISACTOR].last_extra 1000')
            fixture = fixture.replace('7600', '4096').replace('5500', '4096' if args.case == 'flat' else '4785')
            fixture += '\nonevent EVENT_PROCESSINPUT\n addlog WEAPON12_SHOOTS\nendevent\n'
            if args.case == 'cancel':
                fixture += '\nonevent EVENT_PREWEAPONSHOOT\n setvar RETURN 1\nendevent\n'
            (lab/'pipebomb_test.con').write_text(fixture)
            geometry = bytearray(room(args.case == 'wall'))
            if args.case == 'vertical':
                for offset in (26, 66):
                    struct.pack_into('<i', geometry, offset, -131072)
            if args.case == 'underwater':
                # Map header22 + sector lotag34; apply to both rooms.
                for offset in (56, 96):
                    struct.pack_into('<h', geometry, offset, 2)
            (lab/'pipebomb.map').write_bytes(geometry)
        so = run.launch('server', ['-dedicated', '-c1', '-m', '-port', str(args.port), '-map', 'pipebomb.map'])
        so.wait(lambda t: 'User Map: /pipebomb.map' in t, timeout=18)
        phase = 'join actual World Tour peers'
        player = join(run)
        co = run.observers['client']
        so.wait(lambda t: last(t, player) is not None and last(t, player)['ammo'] == 40 and last(t, player)['frame'] == 0, timeout=12)
        co.wait(lambda t: 'features=63' in t, timeout=6)
        tracked = args.case != 'flat'
        direction = (32051, 6813, 0) if args.case != 'vertical' else (0, 0, -32767)
        def pose(flags=3):
            values = (flags, *((192, 77, 1843) if flags == 3 else (0, 0, 0)), *(direction if flags == 3 else (0, 0, 0)))
            os.write(run.writers['client'], ('pose '+' '.join(map(str, values))+'\n').encode())
        if tracked:
            pose()
            co.wait(lambda t: 'pose published flags=3' in t, timeout=5)
            so.pause(.3)
        before = last(so.text(), player)
        target_before = last(so.text(), 0)['health']
        observations = []
        def fire():
            prior = count(co.text(), 'post')
            start = len(so.text())
            run.key('client', 228, True)
            if args.case in ('underwater', 'cancel'):
                so.wait(lambda t: last(t, player)['ammo'] < observations[-1]['ammo'] if observations else last(t, player)['ammo'] < before['ammo'], timeout=5)
            else:
                co.wait(lambda t: count(t, 'post') > prior, timeout=5)
            run.key('client', 228, False)
            so.wait(lambda t: last(t, player)['frame'] == 0 and not(last(t, player)['bits'] & 4), timeout=6)
            so.pause(.2)
            observations.append({'shots': shots(so.text()[start:], player), 'ammo': last(so.text(), player)['ammo'], 'player': last(so.text(), player)})
        phase = 'native World Tour firing'
        invalid = held = None
        if args.case == 'loss':
            start = len(so.text())
            pose(1)
            so.pause(.3)
            run.key('client', 228, True)
            so.pause(.5)
            invalid = {'shots': shots(so.text()[start:], player), 'player': last(so.text(), player)}
            pose()
            so.pause(.5)
            held = {'shots': shots(so.text()[start:], player), 'player': last(so.text(), player)}
            run.key('client', 228, False)
            so.pause(.25)
        for _ in range(2):
            fire()
        authoritative = shots(so.text(), player)
        co.wait(lambda t: last(t, player)['ammo'] == last(so.text(), player)['ammo'], timeout=6)
        checks = {
            'actual_native_player': player == 1,
            'stock_World_Tour_FIREBALL_default': ' = 5163' in '\n'.join(re.findall(r'addlog WEAPON12_SHOOTS[^\n]+', so.text())),
            'no_gpu_devices_or_libraries': True,
            'native_ammo_replicates': last(co.text(), player)['ammo'] == last(so.text(), player)['ammo'],
            'native_body_stays_put': (before['x'], before['y']) == (last(so.text(), player)['x'], last(so.text(), player)['y']),
        }
        if args.case in ('underwater', 'cancel'):
            checks['native_consumes_ammo_without_projectile'] = not authoritative and last(so.text(), player)['ammo'] < 40
            checks['native_POST_not_called'] = count(so.text(), 'post') == 0
            checks['native_PRE_semantics'] = (count(so.text(), 'pre') == 0) if args.case == 'underwater' else count(so.text(), 'pre') > 0
        else:
            checks['native_FIREBALL_returned_for_each_fire'] = all(len(o['shots']) == 1 for o in observations)
            checks['native_ammo_per_projectile'] = last(so.text(), player)['ammo'] == 40-len(authoritative)
            checks['native_owner_size_damage'] = bool(authoritative) and all(s['owner'] == before['psindex'] and s['size'] == 40 and 30 <= s['damage'] <= 37 for s in authoritative)
            phase = 'actual projectile replication'
            if args.case == 'wall':
                # Immediate collision may end an actor before any snapshot.
                # Require both real native firing paths, not transient delivery.
                checks['native_client_predicts_wall_shots'] = len(shots(co.text(), player)) == len(authoritative)
            else:
                co.wait(lambda t: bool(shots(t, player, 2)), timeout=6)
                replicated = shots(co.text(), player, 2)
                checks['live_projectile_seen_on_native_client'] = any(r['index'] == s['index'] for r in replicated for s in authoritative)
                if args.native_reference:
                    pass  # Preserved native binary predates snapshot diagnostics.
                else:
                    co.wait(lambda t: 'VR snapshot fireball applied:' in t, timeout=6)
                    received = [tuple(map(int, values)) for values in re.findall(r'VR snapshot fireball applied: index=(\d+) sector=(-?\d+) stat=(\d+) owner=(\d+)', co.text())]
                    checks['authoritative_primary_snapshot_applied'] = any(index == shot['index'] and owner == shot['owner'] and stat == 4 for index, sector, stat, owner in received for shot in authoritative)
            if tracked:
                checks['negotiated_stock_flame_hand_path'] = 'features=127' in so.text() and 'features=127' in co.text() and 'VR native fireball:' in so.text()
                if args.case == 'wall':
                    checks['closed_wall_constrains_hand_origin'] = all(s['sector'] == 0 and s['px'] <= 1136 for s in authoritative)
                else:
                    checks['resolved_hand_origin_without_flat_muzzle_bias'] = all((s['px'], s['py'], s['pz'], s['sector']) == (1216, 4173, before['z']+1843, 1) for s in authoritative)
                if args.case == 'vertical':
                    checks['physical_vertical_velocity'] = all(s['speed'] == 0 and s['zvel'] == -13440 for s in authoritative)
                else:
                    checks['physical_heading_and_speed'] = all(65 <= s['angle'] <= 69 and s['speed'] == 840 and s['zvel'] == 0 for s in authoritative)
                if args.case == 'loss':
                    checks['invalid_source_consumes_no_ammo'] = invalid['player']['ammo'] == 40 and not invalid['shots']
                    checks['held_recovery_requires_release'] = held['player']['ammo'] == 40 and not held['shots']
            else:
                checks['native_flat_path_has_no_hand_override'] = 'VR native fireball:' not in so.text()
            if args.case in ('flat', 'tracked'):
                phase = 'native target damage'
                so.wait(lambda t: last(t, 0)['health'] < target_before, timeout=8)
                co.wait(lambda t: last(t, 0)['health'] == last(so.text(), 0)['health'], timeout=6)
                checks['native_target_damage_replicates'] = True
        comparison = None
        if args.reference_result:
            reference = json.loads(args.reference_result.read_text())
            keys = ('tile', 'owner', 'shooter', 'sector', 'px', 'py', 'pz', 'angle', 'speed', 'zvel', 'size', 'damage', 'seed', 'phase')
            canonical = lambda rows: [{k: row[k] for k in keys} for row in rows]
            checks['native_flat_reference_exact'] = reference['passed'] and canonical(reference['authoritative_shots']) == canonical(authoritative)
            checks['native_flat_reference_ammo_exact'] = [o['ammo'] for o in reference['observations']] == [o['ammo'] for o in observations]
            comparison = {'reference_binary_sha256': reference['binary_sha256'], 'fields': keys}
        run.audit()
        result = {'passed': all(checks.values()), 'case': args.case, 'checks': checks, 'binary_sha256': sha256(args.binary), 'qualification': 'CPU native WT weapon/wire/actor/damage; simulated pose setter, no OpenXR/headset/SPS qualification', 'observations': observations, 'authoritative_shots': authoritative, 'invalid': invalid, 'held': held, 'reference': comparison, 'source_files': sources[:len(sources)//2], 'target_health': {'before': target_before, 'server': last(so.text(), 0)['health'], 'client': last(co.text(), 0)['health']}}
    except Exception as error:
        result = {'passed': False, 'case': args.case, 'phase': phase, 'error': str(error)}
        if 'checks' in locals():
            result['checks'] = checks
        if 'observations' in locals():
            result['observations'] = observations
    finally:
        run.close()
    result['evidence_directory'] = str(root)
    (root/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
