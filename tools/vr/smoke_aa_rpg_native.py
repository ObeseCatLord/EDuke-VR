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
import subprocess
import tempfile

from PIL import Image
from monado_remote import Remote
from smoke_actions import Observer
from smoke_aim import orientation
from smoke_alien_armageddon import (PVP_CAPTURE, aa_samples, aa_wrapper,
                                    drive_character_selection, post_gameplay_capture)
from smoke_aa_hand_model import wait_for_character_selection
from smoke_multiplayer import CONFIG, X11, stop


RPG_FIELDS = ('tick', 'player', 'startmode', 'pchar', 'currentweapon', 'ammo', 'counter',
              'reloading', 'weaponpos', 'upgrades', 'nuke', 'firedelay',
              'totaltime', 'workslike', 'shoots', 'flags', 'clip', 'reload', 'holddelay', 'burst', 'shots')
RPG_SAMPLE = re.compile(r'addlog aarpg_(\w+)(?: \(player \d+\))? = (-?\d+)')
RPG_SPAWN = re.compile(r'addlog aarpg_spawn_(\w+)(?: \(player \d+\))? = (-?\d+)')
RPG_IMPACT = re.compile(r'addlog aarpg_impact_(\w+)(?: \(player \d+\))? = (-?\d+)')


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


def select_rpg(process, observer, display, key, timeout):
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
        observer.wait(lambda text: any(row['currentweapon'] == 4
                                      for row in rpg_rows(text[start:])), timeout=timeout)
    finally:
        x11.send_event_key(window, key, False)
    return observer.wait(lambda text: any(row['currentweapon'] == 4 and row['weaponpos'] == 0
                                           for row in rpg_rows(text[start:])), timeout=timeout)


def fire_rpg(observer, remote, timeout):
    """One simulated trigger edge; all passing evidence comes from native AA rows/events."""
    ready = observer.wait(lambda text: rpg_rows(text) and rpg_rows(text)[-1]['currentweapon'] == 4
                          and rpg_rows(text)[-1]['weaponpos'] == 0 and rpg_rows(text)[-1]['counter'] == 0,
                          timeout=timeout)
    before = rpg_rows(ready)[-1]
    start = len(ready)
    hand = remote.packet.right
    hand.pose.position.x, hand.pose.position.y, hand.pose.position.z = .2, 1.3, -.5
    hand.pose.orientation = orientation(10, 4)
    hand.trigger_value, hand.trigger_click = 1, True
    remote.send()
    try:
        observer.wait(lambda text: any(row['counter'] > 0 or row['shots'] > before['shots']
                                                 for row in rpg_rows(text[start:])), timeout=timeout)
    finally:
        hand.trigger_value, hand.trigger_click = 0, False
        remote.send()
    returned = observer.wait(lambda text: rpg_rows(text) and rpg_rows(text)[-1]['counter'] == 0
                             and not (aa_samples(text)[-1]['bits'] & 4), timeout=timeout)
    return {'before': before, 'timeline': rpg_rows(returned[start:]), 'after': rpg_rows(returned)[-1],
            'input': aa_samples(returned[start:]), 'log_offset': start}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'grp', 'mod-root', 'compat-con', 'work-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, required=True)
    parser.add_argument('--timeout', type=int, default=65)
    parser.add_argument('--weapon-key', default='5', help='owned-window native key bound to standard RPG selection')
    args = parser.parse_args()
    if not 10 <= args.timeout <= 180 or len(args.weapon_key) != 1:
        parser.error('--timeout must be 10..180 and --weapon-key must be one keysym character')
    args.binary, args.grp, args.mod_root, args.compat_con, args.work_dir = (
        args.binary.resolve(), args.grp.resolve(), args.mod_root.resolve(), args.compat_con.resolve(), args.work_dir.resolve())
    inputs = (args.binary, args.grp, args.compat_con, args.mod_root / 'AA.grp', args.mod_root / 'duke3d.def',
              args.mod_root / 'scripts/AAGAME.CON')
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
    try:
        (root / 'eduke32.cfg').write_text(CONFIG + '\n[Screen Setup]\nPolymer = 0\n')
        (root / 'settings.cfg').write_text('// Private AA standard-Duke RPG runner.\n')
        (root / 'autoexec.cfg').write_text('r_maxfps 60\n')
        (root / 'aa_rpg_observer.con').write_text(rpg_observer())
        env = {key: value for key, value in os.environ.items() if not key.startswith('EDUKE32_XR')}
        env.update(DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy',
                   EDUKE32_XR='1', EDUKE32_XR_SINGLE_PASS='1', EDUKE32_XR_UI='2',
                   EDUKE32_XR_AIM='right', EDUKE32_XR_WEAPON='1', EDUKE32_XR_HAND_SHOTS='1',
                   EDUKE32_XR_MODELS='0', EDUKE32_XR_TEST_INPUT='1', EDUKE32_XR_TEST_PVP='1',
                   EDUKE32_XR_TEST_MODEL_ANIMATION='1', EDUKE32_XR_TEST_MODEL_WEAPON='4',
                   EDUKE32_XR_WEAPON_OUTPUT=str(root / 'weapon'),
                   EDUKE32_XR_WORLD_OUTPUT=str(root / 'world'), EDUKE32_XR_HUD_OUTPUT=str(root / 'hud'))
        command = [str(args.binary), '-usecwd', '-nosetup', '-noautoload', '-nologo', '-ns', '-nm',
                   '-j', str(args.mod_root), '-j', str(args.compat_con.parent), '-g', str(args.grp),
                   '-x', args.compat_con.name, '-mx', 'aa_rpg_observer.con', '-h', 'duke3d.def', '-v1', '-l2', '-s1']
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
            selected_text = select_rpg(process, observer, args.display, args.weapon_key, min(12, args.timeout))
            selected = [row for row in rpg_rows(selected_text) if row['currentweapon'] == 4 and row['weaponpos'] == 0][-1]
            result['selected'] = selected
            prior_capture = max(map(int, PVP_CAPTURE.findall(observer.text())), default=0)
            result['gameplay_capture'] = post_gameplay_capture(observer, root, prior_capture, timeout=25)
            phase = 'native RPG trigger and projectile'
            result['fire'] = fire_rpg(observer, remote, min(12, args.timeout))
            observer.wait(lambda text: bool(spawn_rows(text[result['fire']['log_offset']:])), timeout=8)
            observer.wait(lambda text: any((root / f'weapon-counter-{counter:02d}-coverage.pgm').is_file()
                                            for counter in range(4, 8)), timeout=8)
            # A normal map may put the impact beyond this bounded observation.
            # Keep it as evidence when it occurs without converting it into a made-up fixture requirement.
            try:
                observer.wait(lambda text: bool(impact_rows(text[result['fire']['log_offset']:])), timeout=4)
            except RuntimeError:
                pass
        text = observer.text()
        native = rpg_rows(text)
        fire = result['fire']
        spawns = spawn_rows(text[fire['log_offset']:])
        impacts = impact_rows(text[fire['log_offset']:])
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
            simulated_trigger_reaches_native_input=any(row['bits'] & 4 for row in fire['input']),
            native_RPG_counter_timeline=any(row['counter'] > 0 for row in fire['timeline']) and
                                        fire['after']['counter'] == 0,
            native_RPG_flash_counter_observed=any(4 <= row['counter'] <= 7 for row in fire['timeline']),
            native_RPG_flash_ART_card_nonempty=result['native_art_card']['nonempty_flash_card'],
            native_RPG_ammo_decrement=fire['after']['ammo'] == fire['before']['ammo'] - 1,
            native_RPG_postweaponshoot=fire['after']['shots'] > fire['before']['shots'],
            native_RPG_single_trigger_shot=fire['after']['shots'] == fire['before']['shots'] + 1,
            native_RPG_projectile_inserted=len(spawns) == 1 and spawns[0]['player'] == selected['player'] and
                spawns[0]['sector'] >= 0 and spawns[0]['speed'] > 0,
            stereo_gameplay=result['gameplay_capture']['eyes_distinct'] and result['gameplay_capture']['eyes_nonconstant'],
            held_weapon_models_disabled='OpenXR hand model:' not in text,
            core_validation_clean=not re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)', text),
            game_remains_running=process.poll() is None)
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
