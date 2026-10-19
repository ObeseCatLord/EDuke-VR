#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise AA's unmodified standard-Duke RPG through its native UI and fire path.

Run inside ``software_xr_lab.py``.  The supplied AA installation and compatibility
CON are read-only.  The disposable lab receives only configuration, an observation
CON, logs, and optional renderer diagnostics.  The observer grants a few RPG rounds
after native Duke START; it never selects the weapon, advances its counters, or
creates a projectile.  Selection is the owned window's normal weapon key and firing
is a simulated private Monado trigger edge.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile

from PIL import Image
from monado_remote import Remote
from smoke_actions import Observer
from smoke_aim import orientation
from smoke_alien_armageddon import (PVP_CAPTURE, aa_samples, aa_wrapper,
                                    drive_character_selection, post_gameplay_capture)
from smoke_aa_hand_model import (AA_RECEIPT, MODEL_RECEIPT, MODEL_SAMPLE,
                                 image_contribution, native_weapon_card,
                                 wait_for_character_selection)
from smoke_multiplayer import CONFIG, X11, stop


RPG_FIELDS = ('tick', 'player', 'startmode', 'pchar', 'currentweapon', 'ammo', 'counter',
              'reloading', 'weaponpos', 'upgrades', 'nuke', 'firedelay',
              'totaltime', 'workslike', 'shoots', 'flags', 'clip', 'reload', 'holddelay', 'burst', 'shots')
RPG_SAMPLE = re.compile(r'addlog aarpg_(\w+)(?: \(player \d+\))? = (-?\d+)')
RPG_SPAWN = re.compile(r'addlog aarpg_spawn_(\w+)(?: \(player \d+\))? = (-?\d+)')
RPG_IMPACT = re.compile(r'addlog aarpg_impact_(\w+)(?: \(player \d+\))? = (-?\d+)')
MODEL_CALLS = re.compile(
    r'OpenXR hand model single-pass: paired=(\d+) eyeOnly=(\d+) shared=(\d+) sharedVertices=(\d+)\.')
DEFAULT_ASSETS = Path(__file__).resolve().parents[3] / 'duke-vr-assets/aa-rpg-native/exports/eduke32/aa_assets'
MODEL_COUNTERS = tuple(range(1, 4)) + tuple(range(8, 21))
QUALIFIED_MODEL_COUNTERS = tuple(range(1, 4)) + tuple(range(8, 20))


def rows(text, pattern, fields):
    """Parse complete observer rows; partial log fragments never count as evidence."""
    result, current = [], {}
    for name, value in pattern.findall(text):
        if name == fields[0]:
            current = {name: int(value)}
        elif current:
            current[name] = int(value)
            if name == fields[-1] and all(field in current for field in fields):
                result.append(current)
    return result


def rpg_rows(text):
    return rows(text, RPG_SAMPLE, RPG_FIELDS)


def spawn_rows(text):
    return rows(text, RPG_SPAWN, ('tick', 'player', 'index', 'sector', 'x', 'y', 'z', 'angle', 'speed', 'zvel'))


def impact_rows(text):
    return rows(text, RPG_IMPACT, ('tick', 'player', 'x', 'y', 'z', 'kind'))


def rpg_observer():
    """AA observations plus a bounded post-START RPG inventory grant.

    ``setp`` only grants ownership/ammo once.  Native key selection, shot timing,
    projectile insertion, collision, effects, and event dispatch remain installed AA.
    """
    fields = '\n'.join(f'gamevar aarpg_{field} 0 1' for field in RPG_FIELDS)
    spawn_fields = ('tick', 'player', 'index', 'sector', 'x', 'y', 'z', 'angle', 'speed', 'zvel')
    impact_fields = ('tick', 'player', 'x', 'y', 'z', 'kind')
    spawn_vars = '\n'.join(f'gamevar aarpg_spawn_{field} 0 1' for field in spawn_fields)
    impact_vars = '\n'.join(f'gamevar aarpg_impact_{field} 0 1' for field in impact_fields)
    read = '''
    addvar aarpg_tick 1
    getplayer[THISACTOR].index aarpg_player
    setvarvar aarpg_startmode startmode
    setvarvar aarpg_pchar pchar
    getplayer[THISACTOR].curr_weapon aarpg_currentweapon
    getplayer[THISACTOR].ammo_amount RPG_WEAPON aarpg_ammo
    getplayer[THISACTOR].kickback_pic aarpg_counter
    getplayer[THISACTOR].reloading aarpg_reloading
    getplayer[THISACTOR].weapon_pos aarpg_weaponpos
    setvarvar aarpg_upgrades dukeupgrades[RPG_WEAPON]
    setvarvar aarpg_nuke nukeselect
    setvarvar aarpg_firedelay WEAPON4_FIREDELAY
    setvarvar aarpg_totaltime WEAPON4_TOTALTIME
    set aarpg_workslike WEAPON4_WORKSLIKE
    set aarpg_shoots WEAPON4_SHOOTS
    set aarpg_flags WEAPON4_FLAGS
    set aarpg_clip WEAPON4_CLIP
    set aarpg_reload WEAPON4_RELOAD
    set aarpg_holddelay WEAPON4_HOLDDELAY
    set aarpg_burst WEAPON4_SHOTSPERBURST
'''
    logs = ''.join(f'    addlog aarpg_{field}\n' for field in RPG_FIELDS)
    spawn_logs = ''.join(f'        addlog aarpg_spawn_{field}\n' for field in spawn_fields)
    impact_logs = ''.join(f'            addlog aarpg_impact_{field}\n' for field in impact_fields)
    # aa_wrapper contributes AA's native START/controller rows; no installed
    # script is included a second time because this file is loaded with -mx.
    return (aa_wrapper(include_game=False) + fields + '\n' + spawn_vars + '\n' + impact_vars + '''
gamevar aarpg_given 0 1
gamevar aarpg_spawn_owner 0 1
gamevar aarpg_spawn_kind 0 1
gamevar aarpg_impact_shooterkind 0 1
gamevar aarpg_impact_owner 0 1
gamevar aarpg_impact_projectile 0 1
gamevar aarpg_impact_shooter 0 1

appendevent EVENT_PROCESSINPUT
    // Give one ordinary native RPG only after AA selected standard Duke.
    ifvare aarpg_given 0 ifvare startmode 1 ifvare pchar 0
    {
        setp[].gotweapon RPG_WEAPON YES
        ifl player[].ammo_amount RPG_WEAPON 3 setp[].ammo_amount RPG_WEAPON 3
        set aarpg_given 1
    }
''' + read + logs + '''endevent

appendevent EVENT_POSTWEAPONSHOOT
    ife player[].curr_weapon RPG_WEAPON addvar aarpg_shots 1
endevent

appendevent EVENT_EGS
    ifactor RPG
    {
        addvar aarpg_spawn_tick 1
        getactor[THISACTOR].owner aarpg_spawn_owner
        ifl aarpg_spawn_owner 0 break
        ifge aarpg_spawn_owner MAXSPRITES break
        getactor[aarpg_spawn_owner].picnum aarpg_spawn_kind
        ifn aarpg_spawn_kind APLAYER break
        getactor[aarpg_spawn_owner].yvel aarpg_spawn_player
        setvarvar aarpg_spawn_index THISACTOR
        getactor[THISACTOR].sectnum aarpg_spawn_sector
        getactor[THISACTOR].x aarpg_spawn_x
        getactor[THISACTOR].y aarpg_spawn_y
        getactor[THISACTOR].z aarpg_spawn_z
        getactor[THISACTOR].ang aarpg_spawn_angle
        getactor[THISACTOR].xvel aarpg_spawn_speed
        getactor[THISACTOR].zvel aarpg_spawn_zvel
''' + spawn_logs + '''    }
    ifactor EXPLOSION2
    {
        getactor[THISACTOR].owner aarpg_impact_owner
        ifl aarpg_impact_owner 0 break
        ifge aarpg_impact_owner MAXSPRITES break
        getactor[aarpg_impact_owner].picnum aarpg_impact_projectile
        ifvare aarpg_impact_projectile RPG
        {
            addvar aarpg_impact_tick 1
            getactor[aarpg_impact_owner].owner aarpg_impact_shooter
            ifl aarpg_impact_shooter 0 break
            ifge aarpg_impact_shooter MAXSPRITES break
            getactor[aarpg_impact_shooter].picnum aarpg_impact_shooterkind
            ifn aarpg_impact_shooterkind APLAYER break
            getactor[aarpg_impact_shooter].yvel aarpg_impact_player
            getactor[THISACTOR].x aarpg_impact_x
            getactor[THISACTOR].y aarpg_impact_y
            getactor[THISACTOR].z aarpg_impact_z
            getactor[aarpg_impact_owner].htmovflag aarpg_impact_kind
''' + impact_logs + '''        }
    }
endevent
''')


def native_art_cards(root: Path, counter_seen: bool) -> dict:
    """Use the existing card diagnostic only after observer rows prove a counter."""
    counters = {}
    for counter in range(4, 8):
        prefix = root / f'weapon-counter-{counter:02d}'
        coverage, ui = prefix.with_name(prefix.name + '-coverage.pgm'), prefix.with_name(prefix.name + '-ui.ppm')
        counters[counter] = {'coverage': str(coverage), 'ui': str(ui),
                             'available': coverage.is_file() and ui.is_file(),
                             'nonempty': coverage.is_file() and Image.open(coverage).getbbox() is not None}
    return {'counter_observed': counter_seen, 'flash_counters': counters,
            'nonempty_flash_card': any(card['nonempty'] for card in counters.values())}


def md3_frames(model: Path) -> dict:
    """Read only the MD3 frame table used by the native selector."""
    data = model.read_bytes()
    if len(data) < 96:
        raise RuntimeError('RPG MD3 header is truncated')
    frame_count, frame_offset, surfaces = (struct.unpack_from('<i', data, offset)[0]
                                           for offset in (76, 92, 84))
    if frame_count <= 0 or surfaces <= 0 or frame_offset < 0 or frame_offset + frame_count * 56 > len(data):
        raise RuntimeError('RPG MD3 frame metadata is invalid')
    names = [data[frame_offset + index * 56 + 40:frame_offset + index * 56 + 56]
             .split(b'\0', 1)[0].decode('ascii', 'strict') for index in range(frame_count)]
    return {'data': data, 'frame_count': frame_count, 'frame_offset': frame_offset,
            'surfaces': surfaces, 'names': names}


def write_rpg_def(root: Path, model: Path, skin: Path, missing_skin: bool = False) -> dict:
    """Create a private all-surface RPGSPRITE mapping; installed DEFs stay untouched."""
    metadata = md3_frames(model)
    if 'rest' not in metadata['names']:
        raise RuntimeError('RPG MD3 has no rest frame')
    local_model, local_skin = root / 'duke_rpg.md3', root / 'duke_rpg.png'
    local_model.symlink_to(model)
    if not missing_skin:
        local_skin.symlink_to(skin)
    body = ['include "duke3d.def"', '', 'model "duke_rpg.md3" {', ' scale 1.0']
    body.extend(f' skin {{ pal 0 surface {index} file "duke_rpg.png" }}' for index in range(metadata['surfaces']))
    body.extend((' frame { name "rest" tile 23 smoothduration 0 }', '}', ''))
    definition = root / 'aa-rpg-model.def'
    definition.write_text('\n'.join(body))
    return {'definition': str(definition), 'tile': 23, 'frame': 'rest',
            'surfaces': metadata['surfaces'], 'model': str(model), 'skin': str(skin),
            'frame_names': metadata['names']}


def missing_frame_fixture(root: Path, model: Path, counter: int) -> dict:
    """Make a private MD3 copy with exactly one eligible native frame name removed."""
    metadata = md3_frames(model)
    target = f'fire_{counter:02d}'
    matches = [index for index, name in enumerate(metadata['names']) if name == target]
    if len(matches) != 1:
        raise RuntimeError(f'RPG MD3 must contain exactly one {target} frame')
    offset = metadata['frame_offset'] + matches[0] * 56 + 40
    original = metadata['data']
    changed = bytearray(original)
    replacement = f'missing_{counter:02d}'.encode('ascii') + b'\0'
    changed[offset:offset + 16] = replacement.ljust(16, b'\0')
    destination = root / f'duke_rpg_missing_{counter:02d}.md3'
    destination.write_bytes(changed)
    offsets = [index for index, (before, after) in enumerate(zip(original, changed)) if before != after]
    return {'path': str(destination), 'counter': counter, 'frame_index': matches[0],
            'original_name': target, 'replacement_name': replacement[:-1].decode('ascii'),
            'source_sha256': hashlib.sha256(original).hexdigest(),
            'sha256': hashlib.sha256(changed).hexdigest(), 'changed_offsets': offsets,
            'only_chosen_frame_name_bytes_changed': all(offset <= index < offset + 16 for index in offsets),
            'payload_unchanged': original[:offset] == changed[:offset] and original[offset + 16:] == changed[offset + 16:]}


def capture_oracle(root: Path, prefix: str) -> dict:
    """Evaluate one accepted hand-model capture without advancing any game state."""
    files = {stage: {eye: [root / f'{prefix}-{stage}-{eye}{suffix}' for suffix in ('.ppm', '-depth.bin')]
                     for eye in ('left', 'right')}
             for stage in ('before', 'collected', 'reference', 'after')}
    complete = all(path.is_file() for stages in files.values() for paths in stages.values() for path in paths)
    collection_exact = complete and all(files['before'][eye][index].read_bytes() == files['collected'][eye][index].read_bytes()
                                        for eye in ('left', 'right') for index in range(2))
    replay_exact = complete and all(files['reference'][eye][index].read_bytes() == files['after'][eye][index].read_bytes()
                                    for eye in ('left', 'right') for index in range(2))
    contribution = image_contribution(root, prefix) if complete else {
        'both_eyes_visible': False, 'stereo_parallax': False, 'changed_pixels': [], 'depth_changed_pixels': []}
    return {'prefix': str(root / prefix), 'complete': complete,
            'collection_color_depth_unchanged': collection_exact,
            'native_replay_color_depth_exact': replay_exact,
            'contribution': contribution,
            'passed': complete and collection_exact and replay_exact and contribution['both_eyes_visible'] and
                      contribution['stereo_parallax']}


def model_animation_evidence(root: Path, text: str, names: list[str]) -> dict:
    """Bind each naturally emitted positive counter to its named frame and capture oracle."""
    samples = [tuple(map(int, row)) for row in MODEL_SAMPLE.findall(text)]
    receipts = [tuple(map(int, row)) for row in MODEL_RECEIPT.findall(text)]
    body_receipts = [tuple(map(int, row)) for row in AA_RECEIPT.findall(text) if int(row[1]) == 10228]
    receipt_by_serial = {serial: (counter, reloading, roles, valid) for serial, counter, reloading, roles, valid in receipts}
    body_by_serial = {serial: tuple(row) for serial, *row in body_receipts}
    entries = {}
    for serial, counter, reloading, frame in samples:
        if counter <= 0 or counter in entries:
            continue
        expected = f'fire_{counter:02d}'
        oracle = capture_oracle(root, f'model-counter-{counter:02d}')
        receipt = receipt_by_serial.get(serial)
        body = body_by_serial.get(serial)
        entries[counter] = {'serial': serial, 'reloading': reloading, 'frame_index': frame,
                            'frame_name': names[frame] if 0 <= frame < len(names) else None,
                            'expected_frame_name': expected, 'oracle': oracle,
                            'valid_model_receipt': receipt is not None and receipt[0] == counter and receipt[2:] == (1, 1),
                            'valid_native_RPG_body_receipt': body is not None and body[0] == 10228 and body[2] == 0 and
                                body[3:] == (1, 1)}
    native_art = {}
    for counter in range(4, 8):
        coverage = root / f'weapon-counter-{counter:02d}-coverage.pgm'
        native_art[counter] = coverage.is_file() and Image.open(coverage).getbbox() is not None
    return {'samples': samples, 'receipts': receipts, 'body_receipts': body_receipts,
            'counter_entries': entries, 'native_art_4_to_7': native_art}


def select_native_weapon(process, observer, display, key, timeout, weapon=4):
    """Hold the owned key until native selection observes it, then release."""
    observer.wait(lambda text: rpg_rows(text) and rpg_rows(text)[-1]['weaponpos'] == 0,
                  timeout=timeout)
    x11 = X11(display)
    window, _ = x11.owned_window(process.pid)
    if not window:
        raise RuntimeError('owned AA drawable missing before native RPG selection')
    start = len(observer.text())
    x11.send_event_key(window, key, True)
    try:
        observer.wait(lambda text: any(row['currentweapon'] == weapon
                                      for row in rpg_rows(text[start:])), timeout=timeout)
    finally:
        x11.send_event_key(window, key, False)
    return observer.wait(lambda text: any(row['currentweapon'] == weapon and row['weaponpos'] == 0
                                           for row in rpg_rows(text[start:])), timeout=timeout)


def fire_rpg(observer, remote, timeout, aim_hand="right"):
    """One simulated trigger edge; all passing evidence comes from native AA rows/events."""
    ready = observer.wait(lambda text: rpg_rows(text) and rpg_rows(text)[-1]['currentweapon'] == 4
                          and rpg_rows(text)[-1]['weaponpos'] == 0 and rpg_rows(text)[-1]['counter'] == 0,
                          timeout=timeout)
    before = rpg_rows(ready)[-1]
    start = len(ready)
    hand = getattr(remote.packet, aim_hand)
    hand.pose.position.x, hand.pose.position.y, hand.pose.position.z = .2, 1.3, -.5
    hand.pose.orientation = orientation(10, 4)
    remote.send()
    # Observe several native input samples at the chosen stationary pose before firing.
    settle = len(observer.text())
    observer.wait(lambda text: len(rpg_rows(text[settle:])) >= 4, timeout=timeout)
    remote.packet.right.trigger_value, remote.packet.right.trigger_click = 1, True
    remote.send()
    try:
        observer.wait(lambda text: any(row['counter'] > 0 or row['shots'] > before['shots']
                                                 for row in rpg_rows(text[start:])), timeout=timeout)
    finally:
        remote.packet.right.trigger_value, remote.packet.right.trigger_click = 0, False
        remote.send()
    returned = observer.wait(lambda text: rpg_rows(text) and rpg_rows(text)[-1]['counter'] == 0
                             and not (aa_samples(text)[-1]['bits'] & 4), timeout=timeout)
    return {'before': before, 'timeline': rpg_rows(returned[start:]), 'after': rpg_rows(returned)[-1],
            'input': aa_samples(returned[start:]), 'log_offset': start}


FAMILY_CAPTURE = re.compile(r'OpenXR hand model family capture: serial=(\d+) family=(\d+) index=(\d+)\.')


def wait_idle_model(observer, root, family=3, switching=False, after=0):
    """Wait for the actual family draw receipt and, for switches, completed submission."""
    tile = {2: 2524, 3: 10228}[family]
    accepted = {}
    def ready(text):
        receipts = [tuple(map(int, row)) for row in AA_RECEIPT.findall(text[after:])
                    if int(row[1]) == tile and int(row[4]) == 1 and int(row[5]) == 1]
        completed = {int(row[0]) for row in MODEL_RECEIPT.findall(text) if int(row[1]) == 0 and int(row[4]) == 1}
        captures = {int(serial): int(index) for serial, candidate, index in FAMILY_CAPTURE.findall(text[after:])
                    if int(candidate) == family}
        for receipt in receipts:
            serial = receipt[0]
            if switching and (serial not in captures or serial not in completed or
                               f'OpenXR mount submitted: serial={serial}.' not in text):
                continue
            suffix = f'-family-{captures[serial]:02d}' if switching else ''
            prefix = 'model' + suffix
            files = [root / f'{prefix}-{stage}-{eye}{ext}'
                     for stage in ('before', 'collected', 'reference', 'after')
                     for eye in ('left', 'right') for ext in ('.ppm', '-depth.bin')]
            if all(path.is_file() for path in files):
                accepted.update(receipt=receipt, prefix=prefix, suffix=suffix)
                return True
        return False
    text = observer.wait(ready, timeout=25)
    row = accepted['receipt']
    sample = None
    if switching:
        block = text.split(f'OpenXR hand model family capture: serial={row[0]} ', 1)[1]
        sample = re.search(r'OpenXR hand model: eye=0 model=(\d+) ', block)
    return {'receipt': dict(zip(('serial', 'tile', 'shade', 'palette', 'roles', 'valid'), row)),
            'oracle': capture_oracle(root, accepted['prefix']),
            'native_weapon_card': native_weapon_card(root, 'weapon' + accepted['suffix']),
            'model_id': int(sample[1]) if sample else None}


def append_pistol_binding(root, model, skin):
    metadata = md3_frames(model)
    (root / 'switch_pistol.md3').symlink_to(model)
    (root / 'switch_pistol.png').symlink_to(skin)
    body = ['model "switch_pistol.md3" {', ' scale 1.0']
    body.extend(f' skin {{ pal 0 surface {surface} file "switch_pistol.png" }}' for surface in range(metadata['surfaces']))
    body.extend((' frame { name "rest" tile 21 smoothduration 0 }', '}', ''))
    with (root / 'aa-rpg-model.def').open('a') as output:
        output.write('\n'.join(body))


def exercise_family_switches(observer, process, display, remote, root, pistol_model, rpg_model, initial):
    """Select each native weapon normally and prove real draws and native shots."""
    from smoke_aa_hand_model import fire_actual_aa_pistol
    from pistol_mount_check import firing as pistol_firing
    from aa_rpg_origin_check import firing as rpg_firing
    stages = []
    for weapon, key, family in ((1, '2', 2), (4, '5', 3)):
        start = len(observer.text())
        selected = select_native_weapon(process, observer, display, key, 12, weapon)
        transitions = rpg_rows(selected[start:])
        idle = wait_idle_model(observer, root, family, True, start)
        firing_start = len(observer.text())
        if weapon == 1:
            shot = fire_actual_aa_pistol(observer, remote)
            native = observer.text()[firing_start:]
            origin = pistol_firing(native.replace('OpenXR weapon mount input:', 'OpenXR pistol mount input:'), pistol_model)
            shot_checks = shot['checks']
        else:
            shot = fire_rpg(observer, remote, 12)
            native = observer.text()[firing_start:]
            origin = rpg_firing(native, rpg_model, True, 1)
            shot_checks = {'one_RPG_ammo_spent_after_return': shot['after']['ammo'] == shot['before']['ammo'] - 1,
                           'one_native_RPG_after_return': len(spawn_rows(native)) == 1 and
                               shot['after']['shots'] == shot['before']['shots'] + 1}
        stages.append({'weapon': weapon, 'transition_rows': transitions, 'idle_model': idle,
                       'fire': shot, 'origin': origin, 'shot_checks': shot_checks})
    ids = [initial['model_id']] + [stage['idle_model']['model_id'] for stage in stages]
    return {'stages': stages, 'model_ids': ids, 'checks': {
        'switches_preserve_distinct_native_model_bindings': None not in ids and ids[0] == ids[2] and ids[0] != ids[1],
        'switches_observe_native_raise_lower_and_ready': all(stage['transition_rows'] and
            any(row['weaponpos'] != 0 for row in stage['transition_rows']) and
            stage['transition_rows'][-1]['currentweapon'] == stage['weapon'] and
            stage['transition_rows'][-1]['weaponpos'] == 0 for stage in stages),
        'switches_have_submitted_native_stereo_models': all(stage['idle_model']['oracle']['passed'] for stage in stages),
        'switches_suppress_only_accepted_native_body': all(stage['idle_model']['native_weapon_card']['available'] and
            not stage['idle_model']['native_weapon_card']['coverage'] for stage in stages),
        'switches_native_firing_and_calibrated_origins': all(all(stage['shot_checks'].values()) and
            all(stage['origin']['checks'].values()) for stage in stages),
        'switches_keep_XR_active_without_receipt_mismatch': 'hand model draw mismatch:' not in observer.text(),
    }}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'grp', 'mod-root', 'compat-con', 'work-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, required=True)
    parser.add_argument('--timeout', type=int, default=65)
    parser.add_argument('--weapon-key', default='5', help='owned-window native key bound to standard RPG selection')
    parser.add_argument('--model', type=Path, help='private standard-Duke RPG MD3; enables held-model qualification '
                        f'(calibrated source: {DEFAULT_ASSETS / "duke_rpg.md3"})')
    parser.add_argument('--skin', type=Path, help='private standard-Duke RPG PNG; required with --model '
                        f'(calibrated source: {DEFAULT_ASSETS / "duke_rpg.png"})')
    mounts = parser.add_mutually_exclusive_group()
    mounts.add_argument('--mount', action='store_true', help='enable the engine\'s optional held-weapon mount')
    mounts.add_argument('--legacy-mount', action='store_true', help='legacy pistol flag must leave RPG at its aim point')
    parser.add_argument('--aim-hand', choices=('left', 'right'), default='right')
    parser.add_argument('--switch-pistol-model', type=Path)
    parser.add_argument('--switch-pistol-skin', type=Path)
    parser.add_argument('--tracking-recovery', action='store_true', help='lose selected left tracking while right trigger stays active')
    parser.add_argument('--asset-fault', choices=('missing-skin', 'missing-palm'))
    parser.add_argument('--draw-fault', choices=('duplicate-body', 'wrong-tile'))
    parser.add_argument('--missing-frame', type=int,
                        help='private model fixture: remove one fire_NN MD3 frame and require native ART recovery')
    args = parser.parse_args()
    if not 10 <= args.timeout <= 180 or len(args.weapon_key) != 1:
        parser.error('--timeout must be 10..180 and --weapon-key must be one keysym character')
    if bool(args.model) != bool(args.skin):
        parser.error('--model and --skin must be supplied together')
    if (args.mount or args.legacy_mount) and not args.model:
        parser.error('--mount requires --model and --skin')
    if args.missing_frame is not None and not args.model:
        parser.error('--missing-frame requires --model and --skin')
    if args.missing_frame is not None and args.missing_frame not in MODEL_COUNTERS[:-1]:
        parser.error('--missing-frame must name one available fire counter with a later recovery frame')
    if (args.asset_fault or args.draw_fault) and not args.mount:
        parser.error('--asset-fault and --draw-fault require --mount with model/skin')
    if sum((bool(args.asset_fault), bool(args.draw_fault), args.missing_frame is not None)) > 1:
        parser.error('asset/draw/missing-frame controls are separate cases')
    if bool(args.switch_pistol_model) != bool(args.switch_pistol_skin):
        parser.error('switch pistol model and skin are required together')
    if args.switch_pistol_model and (not args.mount or args.aim_hand != 'right' or args.asset_fault or args.draw_fault or args.missing_frame is not None):
        parser.error('switch proof requires a normal right-hand mounted RPG case')
    if args.switch_pistol_model:
        args.switch_pistol_model = args.switch_pistol_model.resolve()
        args.switch_pistol_skin = args.switch_pistol_skin.resolve()
    if args.tracking_recovery and (not args.mount or args.aim_hand != 'left' or args.asset_fault or args.draw_fault or args.missing_frame is not None or args.switch_pistol_model):
        parser.error('tracking recovery requires a normal mounted left-hand case with separate right trigger')
    args.binary, args.grp, args.mod_root, args.compat_con, args.work_dir = (
        args.binary.resolve(), args.grp.resolve(), args.mod_root.resolve(), args.compat_con.resolve(), args.work_dir.resolve())
    if args.model:
        args.model, args.skin = args.model.resolve(), args.skin.resolve()
        if not args.model.is_file() or not args.skin.is_file():
            parser.error('--model and --skin must name existing private files')
    inputs = (args.binary, args.grp, args.compat_con, args.mod_root / 'AA.grp', args.mod_root / 'duke3d.def',
              args.mod_root / 'scripts/AAGAME.CON')
    if args.model:
        inputs += (args.model, args.skin)
    if args.switch_pistol_model:
        inputs += (args.switch_pistol_model, args.switch_pistol_skin)
    for path in inputs:
        if not path.is_file():
            parser.error('missing required read-only input: ' + str(path))
    args.work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='aa-rpg-native-', dir=args.work_dir))
    process = None
    log = None
    phase = 'setup'
    result = {'passed': False, 'checks': {}, 'evidence_directory': str(root),
              'native_reference': {'weapon': 'RPG_WEAPON', 'currentweapon': 4, 'body_id': 24,
                                   'body_tiles': [10228, 10229, 10230], 'pchar': 0,
                                   'upgrades': 0, 'nuke': 0, 'fire_delay': 4, 'total_time': 20,
                                   'native_body_flags_before_later_engine_processing': 4098}}
    model_case = args.model is not None
    model_expected = model_case and not args.asset_fault
    blocked = args.asset_fault == 'missing-palm'
    fault_text = None
    result.update(asset_fault=args.asset_fault, draw_fault=args.draw_fault)
    try:
        (root / 'eduke32.cfg').write_text(CONFIG + '\n[Screen Setup]\nPolymer = 0\n')
        (root / 'settings.cfg').write_text('// Private AA standard-Duke RPG runner.\n')
        (root / 'autoexec.cfg').write_text('r_maxfps 60\n' +
            ('bind F4 norepeat "setvar aarpg_fault 1"\n' if args.draw_fault else ''))
        from pistol_mount_check import observer as mount_observer
        from aa_rpg_faults import remove_palm_tag, draw_fault_con, exercise_draw_fault, blocked_fire, tracking_recovery
        (root / 'aa_rpg_observer.con').write_text(rpg_observer() + (mount_observer() if model_case else '')
            + (draw_fault_con(args.draw_fault) if args.draw_fault else ''))
        definition = 'duke3d.def'
        if model_case:
            mapped_model = args.model
            if args.missing_frame is not None:
                result['missing_frame_fixture'] = missing_frame_fixture(root, args.model, args.missing_frame)
                mapped_model = Path(result['missing_frame_fixture']['path'])
            if blocked:
                result['missing_palm_fixture'] = remove_palm_tag(root, args.model, args.aim_hand)
                mapped_model = Path(result['missing_palm_fixture']['path'])
            result['model_mapping'] = write_rpg_def(root, mapped_model, args.skin, args.asset_fault == 'missing-skin')
            result['model_mapping'].update(mount_requested=args.mount, legacy_mount_requested=args.legacy_mount, aim_hand=args.aim_hand)
            if args.switch_pistol_model:
                append_pistol_binding(root, args.switch_pistol_model, args.switch_pistol_skin)
            definition = 'aa-rpg-model.def'
        env = {key: value for key, value in os.environ.items() if not key.startswith('EDUKE32_XR')}
        env.update(DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy',
                   EDUKE32_XR='1', EDUKE32_XR_SINGLE_PASS='1', EDUKE32_XR_UI='2',
                   EDUKE32_XR_AIM=args.aim_hand, EDUKE32_XR_WEAPON='1', EDUKE32_XR_HAND_SHOTS='1',
                   EDUKE32_XR_MODELS='1' if model_case else '0', EDUKE32_XR_TEST_INPUT='1', EDUKE32_XR_TEST_PVP='1',
                   EDUKE32_XR_TEST_MODEL_ANIMATION='1', EDUKE32_XR_TEST_MODEL_WEAPON='4',
                   EDUKE32_XR_WEAPON_OUTPUT=str(root / 'weapon'),
                   EDUKE32_XR_WORLD_OUTPUT=str(root / 'world'), EDUKE32_XR_HUD_OUTPUT=str(root / 'hud'))
        if model_case:
            env.update(EDUKE32_XR_AA_MODELS='1', EDUKE32_XR_TEST_MODELS='1',
                       EDUKE32_XR_MODEL_OUTPUT=str(root / 'model'),
                       EDUKE32_XR_TEST_WEAPON_MOUNT='1', EDUKE32_XR_TEST_SHOTS='1')
            if args.switch_pistol_model:
                env['EDUKE32_XR_TEST_MODEL_SWITCH'] = '1'
            if args.mount:
                env['EDUKE32_XR_WEAPON_MOUNT'] = '1'
            elif args.legacy_mount:
                env['EDUKE32_XR_PISTOL_MOUNT'] = '1'
        command = [str(args.binary), '-usecwd', '-nosetup', '-noautoload', '-nologo', '-ns', '-nm',
                   '-j', str(args.mod_root), '-j', str(args.compat_con.parent), '-g', str(args.grp),
                   '-x', args.compat_con.name, '-mx', 'aa_rpg_observer.con', '-h', definition, '-v1', '-l2', '-s1']
        log = (root / 'game.log').open('w', encoding='utf-8')
        process = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT)
        observer = Observer(process, root / 'game.log')
        phase = 'native AA character selection'
        wait_for_character_selection(observer, process, args.display, min(45, args.timeout))
        with Remote(args.remote_port) as remote:
            result['controller'] = drive_character_selection(observer, remote)
            phase = 'native Duke RPG inventory initialization'
            observer.wait(lambda text: any(row['startmode'] == 1 and row['pchar'] == 0 and row['ammo'] >= 3
                                            for row in rpg_rows(text)), timeout=12)
            phase = 'owned native RPG key selection'
            selected_text = select_native_weapon(process, observer, args.display, args.weapon_key, min(12, args.timeout))
            selected = [row for row in rpg_rows(selected_text) if row['currentweapon'] == 4 and row['weaponpos'] == 0][-1]
            result['selected'] = selected
            if model_expected:
                phase = 'accepted native RPG idle model receipt'
                result['idle_model'] = wait_idle_model(observer, root, switching=bool(args.switch_pistol_model))
            prior_capture = max(map(int, PVP_CAPTURE.findall(observer.text())), default=0)
            result['gameplay_capture'] = post_gameplay_capture(observer, root, prior_capture, timeout=25)
            if args.tracking_recovery:
                phase = 'selected tracking loss and held-trigger recovery'
                result['tracking_recovery'] = tracking_recovery(observer, remote, rpg_rows)
            if blocked:
                phase = 'native RPG firing suppressed by missing calibration'
                result['blocked_fire'] = blocked_fire(observer, remote, rpg_rows, args.aim_hand)
            else:
                phase = 'native RPG trigger and projectile'
                result['fire'] = fire_rpg(observer, remote, min(12, args.timeout), args.aim_hand)
                observer.wait(lambda text: bool(spawn_rows(text[result['fire']['log_offset']:])), timeout=8)
                observer.wait(lambda text: any((root / f'weapon-counter-{counter:02d}-coverage.pgm').is_file()
                                                for counter in range(4, 8)), timeout=8)
                if model_expected:
                    expected = set(QUALIFIED_MODEL_COUNTERS)
                    if args.missing_frame is not None:
                        expected.discard(args.missing_frame)
                        expected.add(next(counter for counter in MODEL_COUNTERS if counter > args.missing_frame))
                    observer.wait(lambda text: all((root / f'model-counter-{counter:02d}-after-left.ppm').is_file()
                                                    for counter in expected), timeout=20)
                # A normal map may put the impact beyond this bounded observation.
                # Keep it as evidence when it occurs without converting it into a made-up fixture requirement.
                try:
                    observer.wait(lambda text: bool(impact_rows(text[result['fire']['log_offset']:])), timeout=4)
                except RuntimeError:
                    pass
            if not blocked:
                result['fire']['log_end'] = len(observer.text())
            if args.switch_pistol_model:
                phase = 'ordinary native pistol and RPG switches'
                result['switches'] = exercise_family_switches(observer, process, args.display, remote, root,
                    args.switch_pistol_model, args.model, result['idle_model'])
            if args.draw_fault:
                phase = 'actual native RPG draw mismatch cancellation'
                result['draw_fault_result'] = exercise_draw_fault(observer, process, args.display, args.draw_fault)
                fault_text = result['draw_fault_result'].pop('text')
        text = fault_text if fault_text is not None else observer.text()
        native = rpg_rows(text)
        if not blocked:
            fire = result['fire']
            spawns = spawn_rows(text[fire['log_offset']:fire['log_end']])
            impacts = impact_rows(text[fire['log_offset']:fire['log_end']])
            result['counter_timeline'] = fire['timeline']
            result['projectiles'] = spawns
            result['optional_native_impacts'] = impacts
            result['native_art_card'] = native_art_cards(root, any(row['counter'] > 0 for row in fire['timeline']))
        checks = result['checks']
        checks.update(
            actual_AA_compat_main_compiled=('Compiling: ' + args.compat_con.name in text or
                                             'Including: ' + args.compat_con.name in text),
            observer_compiled=('Compiling: aa_rpg_observer.con' in text or 'Including: aa_rpg_observer.con' in text),
            native_Duke_START=bool(native) and any(row['startmode'] == 1 and row['pchar'] == 0 for row in native),
            native_standard_Duke_RPG_selected=(selected['currentweapon'] == 4 and selected['pchar'] == 0 and
                                                selected['upgrades'] == 0 and selected['nuke'] == 0),
            native_standard_RPG_timing=(selected['firedelay'], selected['totaltime']) == (4, 20),
            stereo_gameplay=result['gameplay_capture']['eyes_distinct'] and result['gameplay_capture']['eyes_nonconstant'],
            core_validation_clean=not re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)', text),
            game_remains_running=process.poll() is None)
        if blocked:
            checks.update(result['blocked_fire']['checks'])
            checks['private_fixture_only_renames_selected_palm'] = result['missing_palm_fixture']['only_selected_tag_names_changed']
        else:
            checks.update(
                simulated_trigger_reaches_native_input=any(row['bits'] & 4 for row in fire['input']),
                native_RPG_counter_timeline=any(row['counter'] > 0 for row in fire['timeline']) and
                                            fire['after']['counter'] == 0,
                native_RPG_flash_counter_observed=any(4 <= row['counter'] <= 7 for row in fire['timeline']),
                native_RPG_flash_ART_card_nonempty=result['native_art_card']['nonempty_flash_card'],
                native_RPG_ammo_decrement=fire['after']['ammo'] == fire['before']['ammo'] - 1,
                native_RPG_postweaponshoot=fire['after']['shots'] > fire['before']['shots'],
                native_RPG_single_trigger_shot=fire['after']['shots'] == fire['before']['shots'] + 1,
                native_RPG_projectile_inserted=len(spawns) == 1 and spawns[0]['player'] == selected['player'] and
                    spawns[0]['sector'] >= 0 and spawns[0]['speed'] > 0
            )
        if args.tracking_recovery:
            checks.update(result['tracking_recovery']['checks'])
            checks['recovery_repress_fires_exactly_once_from_unchanged_inventory'] = (
                fire['before']['ammo'] == result['tracking_recovery']['baseline']['ammo'] and
                fire['after']['ammo'] == fire['before']['ammo'] - 1 and len(spawns) == 1 and
                fire['after']['shots'] == fire['before']['shots'] + 1)
        if args.switch_pistol_model:
            checks.update(result['switches']['checks'])
        if args.draw_fault:
            checks.update(result['draw_fault_result']['checks'])
        if model_case and not blocked:
            from aa_rpg_origin_check import firing as origin_firing
            result['native_origin'] = origin_firing(text, args.model, args.mount, int(args.aim_hand == 'right'))
            checks.update(result['native_origin']['checks'])
        if model_expected:
            animation = model_animation_evidence(root, text, result['model_mapping']['frame_names'])
            result['model_animation'] = animation
            expected = set(QUALIFIED_MODEL_COUNTERS)
            if args.missing_frame is not None:
                expected.discard(args.missing_frame)
            entries = animation['counter_entries']
            calls = [tuple(map(int, row)) for row in MODEL_CALLS.findall(text)]
            shared = calls[-1] if calls else None
            positive = [entries[counter] for counter in sorted(expected) if counter in entries]
            idle = result['idle_model']
            checks.update(
                private_RPG_DEF_maps_all_surfaces_and_rest=(result['model_mapping']['tile'] == 23 and
                    result['model_mapping']['frame'] == 'rest' and result['model_mapping']['surfaces'] > 0),
                RPG_asset_declares_required_native_frames=all(f'fire_{counter:02d}' in result['model_mapping']['frame_names']
                    for counter in expected),
                actual_RPG_idle_receipt_is_native_body=(idle['receipt']['tile'] == 10228 and
                    idle['receipt']['palette'] == 0 and idle['receipt']['roles'] == 1 and idle['receipt']['valid'] == 1),
                idle_model_both_eye_color_depth_parallax=idle['oracle']['passed'],
                idle_same_frame_native_SPS_RGB_raw_depth_exact=idle['oracle']['native_replay_color_depth_exact'],
                idle_collection_has_zero_color_depth_writes=idle['oracle']['collection_color_depth_unchanged'],
                idle_paired_shared_submission=bool(shared) and shared[0] > 0 and shared[1] == 0 and
                    shared[0] == shared[2] and shared[3] > 0,
                native_RPG_body_ART_empty_at_accepted_idle=(idle['native_weapon_card']['available'] and
                    not idle['native_weapon_card']['coverage']),
                natural_RPG_model_samples_cover_early_and_late_frames=len(positive) == len(expected) and
                    all(entry['frame_name'] == entry['expected_frame_name'] and entry['oracle']['passed'] and
                        entry['valid_model_receipt'] and entry['valid_native_RPG_body_receipt'] for entry in positive),
                native_RPG_4_to_7_remain_full_nonempty_ART=all(animation['native_art_4_to_7'].values()),
                native_RPG_4_to_7_have_no_model_receipt_or_sample=(not any(4 <= row[1] <= 7 for row in animation['samples']) and
                    not any(4 <= row[1] <= 7 for row in animation['receipts'])),
            )
            if args.missing_frame is not None:
                missing = args.missing_frame
                later = [entry for counter, entry in entries.items() if counter > missing]
                checks.update(
                    missing_frame_fixture_changes_only_frame_name=result['missing_frame_fixture']['only_chosen_frame_name_bytes_changed'] and
                        result['missing_frame_fixture']['payload_unchanged'],
                    missing_native_counter_observed=any(row['counter'] == missing for row in fire['timeline']),
                    missing_counter_keeps_native_ART=animation['native_art_4_to_7'].get(missing, False) or
                        ((root / f'weapon-counter-{missing:02d}-coverage.pgm').is_file() and
                         Image.open(root / f'weapon-counter-{missing:02d}-coverage.pgm').getbbox() is not None),
                    missing_counter_has_no_model_receipt_or_sample=(not any(row[1] == missing for row in animation['samples']) and
                        not any(row[1] == missing for row in animation['receipts'])),
                    later_native_model_recovery=bool(later) and all(entry['oracle']['passed'] and
                        entry['valid_model_receipt'] and entry['valid_native_RPG_body_receipt'] for entry in later),
                )
        elif args.asset_fault:
            checks.update(asset_fault_has_no_mesh_sample=not MODEL_SAMPLE.search(text),
                          asset_fault_has_no_consumed_body_receipt=not AA_RECEIPT.search(text))
            if not blocked:
                cards = {counter: (root / f'weapon-counter-{counter:02d}-coverage.pgm') for counter in range(1,20)}
                checks['missing_skin_keeps_native_ART_all_observed_counters'] = all(
                    path.is_file() and Image.open(path).getbbox() is not None for path in cards.values())
                checks['missing_skin_DEF_target_is_absent'] = not (root / 'duke_rpg.png').exists()
        else:
            checks['held_weapon_models_disabled'] = 'OpenXR hand model:' not in text
        if os.environ.get('EDUKE32_TEST_PRIVATE_WINDOW') == '1':
            window, _ = X11(args.display).owned_window(process.pid)
            if not window:
                raise RuntimeError('owned AA private drawable missing')
            visibility = X11(args.display).window_visibility(window)
            checks.update(private_drawable_unmapped=visibility['unmapped'],
                          no_desktop_focus=not visibility['has_desktop_focus'])
        result['passed'] = all(checks.values())
        phase = 'complete'
    except Exception as error:
        result['error'] = str(error)
    finally:
        if process is not None:
            stop(process)
        if log is not None:
            log.close()
    result['phase'] = phase
    result['cleanup'] = process is None or process.poll() is not None
    result['compat_con'] = {'path': str(args.compat_con), 'sha256': hashlib.sha256(args.compat_con.read_bytes()).hexdigest()}
    result['sha256'] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
