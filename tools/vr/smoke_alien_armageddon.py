#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual installed AA scripts/assets in an owned private software-XR lab.

Run inside software_xr_lab.py. The installed mod remains read-only; config,
settings, texture cache, autosaves and captures belong to the disposable lab.
This checks a real selected map, not complete AA campaign/combat acceptance.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

import numpy as np
from PIL import Image
from monado_remote import Remote
from smoke_actions import Observer, traces
from smoke_multiplayer import CONFIG, X11, stop
from smoke_aim import orientation
from smoke_hitscan import rays
from smoke_crosshair import raster


AA_SELECT_BIT = 1 << 29  # Native Open / AA ifhitspace, mapped to left Select.

AA_FIELDS = ('tick', 'player', 'bits', 'q16avel', 'q16horz', 'cursorx', 'cursory',
             'startmode', 'charsel', 'pchar', 'currentweapon', 'ammo', 'gm',
             'counter', 'reloading', 'weaponpos', 'shoots', 'workslike', 'firedelay', 'shots',
             'volume', 'level')
AA_SAMPLE = re.compile(r'addlog aaobserve_(\w+)(?: \(player \d+\))? = (-?\d+)')
PVP_CAPTURE = re.compile(r'OpenXR PvP frame: submitted=(\d+) captured=1')


def aa_samples(text):
    """Read complete rows from the private, observational AA wrapper."""
    rows, current = [], {}
    for key, value in AA_SAMPLE.findall(text):
        if key == 'tick':
            current = {'tick': int(value)}
        elif current:
            current[key] = int(value)
            if key == 'level' and all(name in current for name in AA_FIELDS):
                rows.append(current)
    return rows


def aa_wrapper(local_only=False, include_game=True):
    """Return AA observations, optionally with the installed AA entry include."""
    fields = '\n'.join(f'gamevar aaobserve_{name} 0 1' for name in AA_FIELDS)
    reads = '''
    addvar aaobserve_tick 1
    getplayer[THISACTOR].index aaobserve_player
    getinput[].bits aaobserve_bits
    getinput[].q16avel aaobserve_q16avel
    getinput[].q16horz aaobserve_q16horz
    setvarvar aaobserve_cursorx cursorx
    setvarvar aaobserve_cursory cursory
    setvarvar aaobserve_startmode startmode
    setvarvar aaobserve_charsel charsel
    setvarvar aaobserve_pchar pchar
    getplayer[THISACTOR].curr_weapon aaobserve_currentweapon
    getplayer[THISACTOR].ammo_amount PISTOL_WEAPON aaobserve_ammo
    getplayer[THISACTOR].gm aaobserve_gm
    getplayer[THISACTOR].kickback_pic aaobserve_counter
    getplayer[THISACTOR].reloading aaobserve_reloading
    getplayer[THISACTOR].weapon_pos aaobserve_weaponpos
    setvarvar aaobserve_shoots WEAPON1_SHOOTS
    setvarvar aaobserve_workslike WEAPON1_WORKSLIKE
    setvarvar aaobserve_firedelay WEAPON1_FIREDELAY
    getuserdef[THISACTOR].volume_number aaobserve_volume
    getuserdef[THISACTOR].level_number aaobserve_level
'''
    logs = ''.join(f'    addlog aaobserve_{name}\n' for name in AA_FIELDS)
    if local_only:
        logs = 'ifvarvare aaobserve_player myconnectindex\n{\n' + logs + '}\n'
    entry = 'include scripts/AAGAME.CON\n\n' if include_game else ''
    return ('// Private read-only AA controller observation wrapper.\n' + entry + fields +
            '\n\nappendevent EVENT_PROCESSINPUT\n' + reads + logs + 'endevent\n'
            'appendevent EVENT_POSTWEAPONSHOOT\n addvar aaobserve_shots 1\nendevent\n')


def crosshair_evidence(observer, root):
    """Compare actual AA event pixels with the world-depth projection oracle."""
    text = observer.wait(lambda text: 'OpenXR crosshair capture: world=120 ' in text, timeout=40)
    ui = np.asarray(Image.open(root/'crosshair-ui.ppm'))
    alpha = np.asarray(Image.open(root/'crosshair-coverage.pgm'))
    matrices = {int(eye): np.fromstring(values, sep=',').reshape(4, 4, order='F') for eye, values in
                re.findall(r'OpenXR crosshair matrix: eye=(\d) values=([^\n]+)\.', text)}
    anchor = np.array(list(map(float, re.findall(r'OpenXR crosshair anchor: pixel=([^,]+),([^\n]+)\.', text)[-1])))
    canonical_anchor = [ui.shape[1]/2+1, ui.shape[0]/2+1]
    capture_serial = int(re.findall(r'OpenXR crosshair capture: world=120 serial=(\d+)\.', text)[-1])
    native_state = aa_samples(text)[-1]
    point = np.array([2*anchor[0]/ui.shape[1]-1, 1-2*anchor[1]/ui.shape[0], 0, 1])
    errors, changed, centres, depths, occluded = [], [], [], [], []
    for eye, name in enumerate(('left', 'right')):
        before = np.asarray(Image.open(root/f'crosshair-before-{name}.ppm'))
        after = np.asarray(Image.open(root/f'crosshair-{name}.ppm'))
        raw = (root/f'crosshair-before-{name}-depth.bin').read_bytes()
        depth = np.flipud(np.frombuffer(raw, dtype=np.uint32).reshape(before.shape[:2]))/4294967295
        expected, _, blocked = raster(before, ui, alpha, depth, matrices[eye])
        errors.append(int(np.abs(expected.astype(int)-after.astype(int)).max()))
        changed.append(int(np.count_nonzero(np.any(before != after, axis=2))))
        depths.append(raw == (root/f'crosshair-{name}-depth.bin').read_bytes())
        projected = matrices[eye] @ point
        centres.append((projected[:2]/projected[3]).tolist())
        occluded.append(blocked)
    native_hit = list(map(int, re.findall(r'OpenXR world crosshair: start=(-?\d+),(-?\d+),(-?\d+) '
                                         r'hit=(-?\d+),(-?\d+),(-?\d+)', text)[-1]))
    return {'native_hit': native_hit, 'pixel_max_error': errors, 'changed_pixels': changed,
            'capture_world_frame': 120, 'capture_serial': capture_serial, 'native_state': native_state,
            'anchor_pixels': anchor.tolist(), 'canonical_anchor_pixels': canonical_anchor,
            'depth_preserved': depths, 'centres_ndc': centres, 'occluded_pixels': occluded,
            'coverage_bounds': Image.fromarray(alpha).getbbox(),
            'passed': bool(np.any(alpha)) and max(errors) <= 2 and min(changed) > 0 and all(depths)
            and anchor.tolist() == canonical_anchor and native_state['startmode'] == 1 and native_state['pchar'] == 0
            and abs(centres[0][0]-centres[1][0]) > 1e-4}


def drive_combat(observer, remote, root):
    """Fire AA's actual selected weapon with an off-head physical controller."""
    remote.neutral()
    observer.wait(lambda text: aa_samples(text)[-1]['weaponpos'] == 0, timeout=15)
    hand = remote.packet.right
    hand.pose.position.x = .2
    hand.pose.position.y = 1.3
    hand.pose.position.z = -.5
    hand.pose.orientation = orientation(12, 8)
    remote.send()
    observer.pause(.8)
    crosshair = crosshair_evidence(observer, root)
    before = aa_samples(observer.text())[-1]
    offset = len(observer.text())
    hand.trigger_value = 1
    hand.trigger_click = True
    remote.send()
    fired = observer.wait(lambda text: any(row['shots'] > before['shots'] and row['ammo'] < before['ammo']
                                          for row in aa_samples(text[offset:])), timeout=8)
    held = aa_samples(fired[offset:])
    hand.trigger_value = 0
    hand.trigger_click = False
    remote.send()
    released_at = len(observer.text())
    released = observer.wait(lambda text: any(not (row['bits'] & 4) and row['counter'] == 0
                                             for row in aa_samples(text[released_at:])), timeout=8)
    first_release = aa_samples(released[released_at:])[-1]
    tracked_hits = rays(observer.text()[offset:], 0)
    stages = {}

    def stage(name, active, trigger):
        start = len(observer.text())
        hand.active = active
        hand.trigger_value = int(trigger)
        hand.trigger_click = trigger
        remote.send()
        observed = observer.wait(lambda text: len(aa_samples(text[start:])) >= 4, timeout=8)[start:]
        stages[name] = {'native': aa_samples(observed), 'xr': traces(observed)}

    stage('lost_held', False, True)
    stage('recovered_held', True, True)
    stage('recovered_release', True, False)
    repress_at = len(observer.text())
    hand.trigger_value = 1
    hand.trigger_click = True
    remote.send()
    observer.wait(lambda text: any(row['shots'] > first_release['shots'] for row in aa_samples(text[repress_at:])), timeout=8)
    hand.trigger_value = 0
    hand.trigger_click = False
    remote.send()
    final = observer.wait(lambda text: aa_samples(text)[-1]['counter'] == 0 and
                          not (aa_samples(text)[-1]['bits'] & 4), timeout=8)
    final_row = aa_samples(final)[-1]
    lost = stages['lost_held']
    recovered = stages['recovered_held']
    loss_checks = {
        'actual_controller_inactive': bool(lost['xr']) and any(not row['right_aim'] for row in lost['xr']),
        'held_recovery_does_not_fire': all(row['ammo'] == first_release['ammo'] and
            row['shots'] == first_release['shots'] and not (row['bits'] & 4)
            for stage_rows in (lost, recovered) for row in stage_rows['native']),
        'new_press_after_release_fires': final_row['ammo'] < first_release['ammo']
            and final_row['shots'] > first_release['shots'] and bool(rays(final[repress_at:], 0)),
    }
    return {'before': before, 'held': held, 'released': first_release,
            'tracked_hits': tracked_hits, 'loss_recovery': stages, 'loss_checks': loss_checks,
            'final': final_row,
            'crosshair': crosshair,
            'native_trigger_seen': any(row['bits'] & 4 for row in held)}


def drive_character_selection(observer, remote, stages=None, before_start=None):
    """Use only remote-controller axes and trigger presses to enter AA play.

    Cursor direction is calibrated from the installed script's own native input
    rows.  No AA variable or input packet is changed by the wrapper.
    """
    remote.neutral()
    initial_text = observer.wait(lambda text: len(aa_samples(text)) >= 6, timeout=8)
    initial = aa_samples(initial_text)[-1]
    if initial['startmode'] >= 0:
        raise RuntimeError('AA character-select state was not observed before controller input')
    if stages is None:
        stages = {}
    stages['initial'] = initial

    def select_press():
        remote.packet.left.trigger_value = 1
        remote.packet.left.trigger_click = True
        remote.send()

    def hold_until(label, activate, observed, released, timeout=8):
        """Hold a physical remote control until a new native row proves it.

        Cold AA asset loading can delay the first XR frame for seconds.  Never
        turn a time-based remote pulse into a guessed in-game input: release
        only after the appended AA observation sees the required edge, then
        require a subsequent native release row.
        """
        before = len(aa_samples(observer.text()))
        activate()
        held_text = observer.wait(lambda text: observed(aa_samples(text)[before:]), timeout=timeout)
        held_rows = aa_samples(held_text)[before:]
        remote.neutral()
        released_at = len(aa_samples(observer.text()))
        released_text = observer.wait(lambda text: released(aa_samples(text)[released_at:]), timeout=timeout)
        return held_rows, aa_samples(released_text)[released_at:]

    def select_edge(requirement):
        held, released = hold_until(
            'left trigger / native Open', select_press,
            lambda rows: any((row['bits'] & AA_SELECT_BIT) and requirement(row) for row in rows),
            lambda rows: any(not (row['bits'] & AA_SELECT_BIT) for row in rows))
        return [row for row in held if (row['bits'] & AA_SELECT_BIT) and requirement(row)][-1], released[-1]

    # AA accepts native Open through ifhitspace in startmodecode.  The centered native cursor begins in
    # Duke's inclusive hit box, so selection needs no synthetic cursor move.
    selected, select_release = select_edge(lambda row: bool(row['charsel'] & 1))
    if selected['startmode'] >= 0:
        raise RuntimeError('Duke bit was not observed while AA character selection remained active')
    stages['duke_select'] = selected
    stages['duke_release'] = select_release

    def axis_edge(axis_name, value, coordinate):
        before = aa_samples(observer.text())[-1]

        def send_axis():
            setattr(remote.packet.right.thumbstick, axis_name, value)
            remote.send()

        field = 'q16avel' if axis_name == 'x' else 'q16horz'
        held, released = hold_until(
            f'right-stick {axis_name}', send_axis,
            lambda rows: any(row[field] and row[coordinate] != before[coordinate] for row in rows),
            lambda rows: any(not row[field] for row in rows))
        return [row for row in held if row[field] and row[coordinate] != before[coordinate]][-1], released[-1]

    def calibrate(axis_name, coordinate):
        start = aa_samples(observer.text())[-1]
        changed, _ = axis_edge(axis_name, .8, coordinate)
        delta = changed[coordinate] - start[coordinate]
        if not delta:
            raise RuntimeError(f'native AA cursor did not respond to right-stick {axis_name}')
        return delta, changed

    rates, cursor = {}, aa_samples(observer.text())[-1]
    rates['x'], cursor = calibrate('x', 'cursorx')
    rates['y'], cursor = calibrate('y', 'cursory')

    def steer(axis_name, coordinate, target, rate, low, high):
        nonlocal cursor
        field = 'q16avel' if axis_name == 'x' else 'q16horz'
        for attempt in range(10):
            cursor = aa_samples(observer.text())[-1]
            error = target - cursor[coordinate]
            if low <= cursor[coordinate] <= high:
                return
            sign = 1 if error * rate > 0 else -1
            def send_axis():
                setattr(remote.packet.right.thumbstick, axis_name, sign*(.8 if attempt == 0 else .4))
                remote.send()
            held, released = hold_until(
                f'steer {coordinate}', send_axis,
                lambda rows: any(row[field] and low <= row[coordinate] <= high for row in rows),
                lambda rows: any(not row[field] for row in rows), timeout=12)
            cursor = released[-1]
        raise RuntimeError(f'native AA {coordinate} did not reach the START hit box')

    # START is inclusive x=265..316, y=21..54 in the installed startmodecode.
    steer('x', 'cursorx', 290, rates['x'], 265, 316)
    steer('y', 'cursory', 36, rates['y'], 21, 54)
    cursor = aa_samples(observer.text())[-1]
    if not 265 <= cursor['cursorx'] <= 316 or not 21 <= cursor['cursory'] <= 54:
        raise RuntimeError('native AA cursor did not enter the installed START hit box')
    stages['start_cursor'] = cursor
    if before_start is not None:
        before_start()

    captures_before_start = [int(value) for value in PVP_CAPTURE.findall(observer.text())]
    start_press, start_release = select_edge(
        lambda row: row['startmode'] == 1 and row['pchar'] == 0 and (row['charsel'] & 1))
    gameplay_text = observer.wait(
        lambda text: any(row['startmode'] == 1 and row['pchar'] == 0 and
                         (row['charsel'] & 1) and row['volume'] == 0 and row['level'] == 1
                         for row in aa_samples(text)), timeout=8)
    gameplay = [row for row in aa_samples(gameplay_text)
                if row['startmode'] == 1 and row['pchar'] == 0 and (row['charsel'] & 1)
                and row['volume'] == 0 and row['level'] == 1][-1]
    stages['start_press'] = start_press
    stages['start_release'] = start_release
    stages['gameplay'] = gameplay
    return {'stages': stages,
            'axis_rates': rates,
            'axis_observed': bool(selected['bits'] & AA_SELECT_BIT) and any(
                row['q16avel'] or row['q16horz'] for row in aa_samples(observer.text())),
            'periodic_capture_before_start': max(captures_before_start, default=0)}


def post_gameplay_capture(observer, root, prior, timeout):
    """Return an existing periodic HUD/world capture issued after AA entry."""
    text = observer.wait(lambda value: any(int(serial) > prior for serial in PVP_CAPTURE.findall(value)), timeout=timeout)
    serial = max(int(value) for value in PVP_CAPTURE.findall(text) if int(value) > prior)
    paths = [root/f'hud-{serial}-{eye}.ppm' for eye in ('left', 'right')]
    if not all(path.is_file() for path in paths):
        raise RuntimeError('post-gameplay OpenXR HUD capture receipt had no eye images')
    images = [np.asarray(Image.open(path)) for path in paths]
    return {'submitted_frame': serial, 'paths': [str(path) for path in paths],
            'eyes_distinct': not np.array_equal(*images),
            'eyes_nonconstant': all(int(image.max()) > int(image.min()) for image in images)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'mod-root', 'work-dir'):
        p.add_argument('--'+name, required=True, type=Path)
    p.add_argument('--display', default=':105')
    p.add_argument('--episode', type=int, default=1)
    p.add_argument('--level', type=int, default=2)
    p.add_argument('--timeout', type=int, default=55)
    p.add_argument('--advance-intro', action='store_true',
        help='Advance actual AA opening screens with Return sent only to the owned private window')
    p.add_argument('--play-controller', action='store_true',
        help='Use a private Monado remote controller to select Duke and START in AA\'s native character UI')
    p.add_argument('--combat', action='store_true', help='Fire the actual AA Duke weapon after controller entry')
    p.add_argument('--remote-port', type=int,
        help='Loopback mndrmt3 port for --play-controller; the runtime must already be running')
    p.add_argument('--texture-cache-seed', type=Path, help='Reuse an owned prior lab cache without changing installed content')
    p.add_argument('--compat-con', type=Path,
        help='Read-only production AA main CON loaded with native -x')
    a = p.parse_args()
    if a.play_controller and not a.remote_port:
        p.error('--play-controller requires --remote-port')
    if a.combat and not a.play_controller:
        p.error('--combat requires --play-controller')
    if a.play_controller and (a.episode, a.level) != (1, 2):
        p.error('--play-controller is the fixed Hollywood (episode 1, level 2) proof')
    binary, mod = a.binary.resolve(), a.mod_root.resolve()
    if a.compat_con:
        a.compat_con = a.compat_con.resolve()
        if not a.compat_con.is_file():
            p.error('missing --compat-con: '+str(a.compat_con))
    entry = mod/'scripts/AAGAME.CON'
    for path in (binary, entry, mod/'AA.grp', mod/'duke3d.def'):
        if not path.is_file():
            p.error('missing required installed input: '+str(path))
    root = Path(tempfile.mkdtemp(prefix='aa-', dir=a.work_dir.resolve()))
    (root/'eduke32.cfg').write_text(CONFIG+'\n[Screen Setup]\nPolymer = 0\n')
    (root/'settings.cfg').write_text('// Private test preferences; installed profile is not used.\n')
    # Slow the disposable lab enough to observe expensive cold-start input
    # edges; the driver still waits on native observations, never this rate.
    (root/'autoexec.cfg').write_text('r_maxfps '+('5' if a.play_controller else '30')+'\n')
    if a.texture_cache_seed:
        for name in ('texturecache', 'texturecache.index'):
            source = a.texture_cache_seed.resolve()/name
            if source.is_file():
                shutil.copyfile(source, root/name)
    env = {k: v for k, v in os.environ.items() if not k.startswith('EDUKE32_XR')}
    env.update(DISPLAY=a.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy',
        EDUKE32_XR='1', EDUKE32_XR_SINGLE_PASS='1', EDUKE32_XR_UI='2',
        EDUKE32_XR_AIM='right', EDUKE32_XR_WEAPON='1', EDUKE32_XR_HAND_SHOTS='1',
        EDUKE32_XR_MODELS='1', EDUKE32_XR_TEST_MODELS='1',
        EDUKE32_XR_MENU_OUTPUT=str(root/'intro'),
        EDUKE32_XR_WORLD_OUTPUT=str(root/'world'), EDUKE32_XR_HUD_OUTPUT=str(root/'hud'),
        EDUKE32_XR_WEAPON_OUTPUT=str(root/'weapon'))
    if a.play_controller:
        env['EDUKE32_XR_TEST_INPUT'] = '1'
        env['EDUKE32_XR_TEST_PVP'] = '1'
        (root/'aa_controller_observer.con').write_text(aa_wrapper(include_game=not bool(a.compat_con)))
    if a.combat:
        env['EDUKE32_XR_TEST_SHOTS'] = '1'
        env['EDUKE32_XR_CROSSHAIR_OUTPUT'] = str(root/'crosshair')
        env['EDUKE32_XR_CROSSHAIR_FRAME'] = '120'
    main_con = a.compat_con.name if a.compat_con else (
        'aa_controller_observer.con' if a.play_controller else 'scripts/AAGAME.CON')
    observer_con = 'aa_controller_observer.con' if a.compat_con and a.play_controller else None
    command = [str(binary), '-usecwd', '-nosetup', '-noautoload', '-nologo', '-ns', '-nm',
        '-j', str(mod)]
    if a.compat_con:
        command.extend(('-j', str(a.compat_con.parent)))
    command.extend(('-g', str(mod/'AA.grp'), '-x', main_con))
    if observer_con:
        command.extend(('-mx', observer_con))
    command.extend(('-h', 'duke3d.def', '-v'+str(a.episode), '-l'+str(a.level), '-s1'))
    process = None
    result = {'passed': False,
              'con_launch': {'main_cli': ['-x', main_con],
                             'observer_cli': ['-mx', observer_con] if observer_con else []}}
    if a.compat_con:
        result['compat_con'] = {'path': str(a.compat_con),
                                'sha256': hashlib.sha256(a.compat_con.read_bytes()).hexdigest()}
    try:
        with (root/'game.log').open('w') as log:
            process = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT)
            observer = Observer(process, root/'game.log')
            controller = None
            deadline, next_press, intro_presses = time.monotonic()+a.timeout, 0, 0
            if a.play_controller:
                with Remote(a.remote_port) as remote:
                    # Preserve --advance-intro when the caller asks for it:
                    # arrive at AA's own character-selection state before any
                    # controller press is interpreted as a game choice.
                    while a.advance_intro:
                        opening = observer.text()
                        rows = aa_samples(opening)
                        if rows and rows[-1]['startmode'] < 0:
                            break
                        now = time.monotonic()
                        if now >= deadline:
                            raise RuntimeError('AA opening-screen advance timeout before controller selection')
                        if 'Per-map .art file' in opening and not next_press:
                            next_press = now+(13 if a.play_controller else 3)
                        if 'Per-map .art file' in opening and 'OpenXR opaque ' not in opening \
                                and now >= next_press and intro_presses < 24:
                            x11 = X11(a.display)
                            window, _ = x11.owned_window(process.pid)
                            if window:
                                x11.press(window, 'Return', .08, True)
                                intro_presses += 1
                                next_press = now+1
                        time.sleep(.05)
                    controller = drive_character_selection(observer, remote)
                    capture_after = controller['periodic_capture_before_start']
                    if a.combat:
                        controller['combat'] = drive_combat(observer, remote, root)
                        capture_after = max(map(int, PVP_CAPTURE.findall(observer.text())), default=0)
                        controller['periodic_capture_before_combat_end'] = capture_after
                    controller['post_gameplay_capture'] = post_gameplay_capture(
                        observer, root, capture_after,
                        max(1, min(30, deadline-time.monotonic())))
            while True:
                text = observer.text()
                if 'OpenXR world oracle: 60 frames' in text and 'OpenXR HUD presentation: 60 frames' in text:
                    break
                now = time.monotonic()
                if now >= deadline:
                    raise RuntimeError('AA selected-map observation timeout')
                if a.advance_intro and 'Per-map .art file' in text and not next_press:
                    next_press = now+(13 if a.play_controller else 3)
                if a.advance_intro and 'Per-map .art file' in text and 'OpenXR opaque ' not in text \
                        and now >= next_press and intro_presses < 24:
                    x11 = X11(a.display)
                    window, _ = x11.owned_window(process.pid)
                    if window:
                        x11.press(window, 'Return', .08, True)
                        intro_presses += 1
                        next_press = now+1
                time.sleep(.05)
            counts = re.findall(r'OpenXR world oracle: 60 frames, opaque multiview=(\d+) twoPass=(\d+); masks multiview=(\d+) twoPass=(\d+) full multiview=(\d+)', text)
            checks = {'actual_AA_scripts_compiled': ('Compiling: scripts/AAGAME.CON' in text or 'Including: scripts/AAGAME.CON' in text) and not re.search(r'error:|Found \d+ error', text),
                'actual_sixty_world_HUD_submissions': bool(counts),
                'core_validation_active': 'Core Validation output type:' in text,
                'core_validation_clean': not re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)', text),
                'AA_custom_weapon_not_replaced_by_stock_model': 'OpenXR hand model:' not in text,
                'game_remains_running': process.poll() is None}
            images = [np.asarray(Image.open(root/('world-'+eye+'.ppm'))) for eye in ('left', 'right')]
            initial_world_capture = {
                'eyes_distinct': not np.array_equal(*images),
                'eyes_nonconstant': all(int(im.max()) > int(im.min()) for im in images),
            }
            checks['actual_world_eye_layers_distinct'] = initial_world_capture['eyes_distinct']
            checks['actual_world_images_nonconstant'] = initial_world_capture['eyes_nonconstant']
            if a.advance_intro:
                checks['native_opening_screen_presented_in_XR'] = 'OpenXR menu presentation: 60 frames' in text
                checks['native_opening_screen_capture_nonconstant'] = all(
                    any(low < high for low, high in Image.open(root/('intro-'+eye+'.ppm')).getextrema())
                        for eye in ('left', 'right'))
            if a.play_controller:
                final_rows = aa_samples(text)
                game_rows = [row for row in final_rows if row['startmode'] == 1 and row['pchar'] == 0
                             and (row['charsel'] & 1) and row['volume'] == 0 and row['level'] == 1]
                axis_rows = [row for row in final_rows if row['q16avel'] or row['q16horz']]
                checks.update(
                    controller_wrapper_compiled=('Compiling: aa_controller_observer.con' in text or
                                                 bool(observer_con and 'Including: aa_controller_observer.con' in text)),
                    controller_native_axis_to_cursor=bool(axis_rows) and any(
                        row['cursorx'] != controller['stages']['initial']['cursorx'] or
                        row['cursory'] != controller['stages']['initial']['cursory'] for row in axis_rows),
                    controller_open_selected_duke=bool(controller['stages']['duke_select']['bits'] & AA_SELECT_BIT)
                        and bool(controller['stages']['duke_select']['charsel'] & 1),
                    controller_start_entered_hollywood=bool(game_rows)
                        and controller['post_gameplay_capture']['submitted_frame']
                            > controller['periodic_capture_before_start'],
                    controller_gameplay_weapon_ammo_observed=bool(game_rows)
                        and all(name in game_rows[-1] for name in ('currentweapon', 'ammo', 'gm')),
                    controller_post_gameplay_HUD_eyes_distinct=controller['post_gameplay_capture']['eyes_distinct'],
                    controller_post_gameplay_HUD_nonconstant=controller['post_gameplay_capture']['eyes_nonconstant'])
            if os.environ.get('EDUKE32_TEST_PRIVATE_WINDOW') == '1':
                x11 = X11(a.display)
                window, _ = x11.owned_window(process.pid)
                if not window:
                    raise RuntimeError('owned AA private drawable missing')
                state = x11.window_visibility(window)
                checks.update(private_drawable_unmapped=state['unmapped'], no_desktop_focus=not state['has_desktop_focus'])
            if a.combat:
                combat = controller['combat']
                checks.update(actual_AA_pistol_is_native_shotgun_hitscan=combat['before']['shoots'] == 2613
                              and combat['before']['workslike'] == 1,
                              native_AA_ammo_and_shot_event=combat['released']['ammo'] < combat['before']['ammo']
                              and combat['released']['shots'] > combat['before']['shots'],
                              actual_controller_fire_and_release=combat['native_trigger_seen']
                              and not (combat['released']['bits'] & 4),
                              actual_AA_tracked_native_hitscan=bool(combat['tracked_hits']),
                              actual_AA_event_crosshair_projected_with_world_depth=combat['crosshair']['passed'],
                              reticle_origin_matches_actual_AA_shot=bool(combat['tracked_hits']) and
                              combat['crosshair']['native_hit'][:3] == [combat['tracked_hits'][0][key] for key in ('x', 'y', 'z')])
                checks.update(combat['loss_checks'])
            result = {'passed': all(checks.values()), 'checks': checks, 'episode': a.episode, 'level': a.level,
                'multiview_accounting': list(map(int, counts[-1])) if counts else None,
                'native_intro_keypresses': intro_presses,
                'initial_world_capture': initial_world_capture,
                'controller_observation': controller,
                'post_gameplay_capture': controller.get('post_gameplay_capture') if controller else None,
                'con_launch': {'main_cli': ['-x', main_con],
                               'observer_cli': ['-mx', observer_con] if observer_con else []},
                'qualification': 'Actual AA entry, with optional Duke-pistol tracked combat/crosshair proof; full arsenal/campaign/AA multiplayer and general SPS remain unqualified.'}
            if a.compat_con:
                result['compat_con'] = {'path': str(a.compat_con),
                                        'sha256': hashlib.sha256(a.compat_con.read_bytes()).hexdigest()}
    except Exception as error:
        result = {'passed': False, 'episode': a.episode, 'level': a.level, 'error': str(error),
                  'con_launch': {'main_cli': ['-x', main_con],
                                 'observer_cli': ['-mx', observer_con] if observer_con else []}}
        if a.compat_con:
            result['compat_con'] = {'path': str(a.compat_con),
                                    'sha256': hashlib.sha256(a.compat_con.read_bytes()).hexdigest()}
    finally:
        stop(process)
    result.update(evidence_directory=str(root), cleanup=process is None or process.poll() is not None,
        sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (binary, entry, mod/'duke3d.def', mod/'AA.grp')})
    (root/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
