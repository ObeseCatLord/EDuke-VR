#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Qualify AA's one supported idle Duke-pistol MD3 in a private software-XR lab.

Run this child under ``software_xr_lab.py``.  It only writes below
``--work-dir``: the installed AA directory, compatibility CON, and exported
MD3/skin remain read-only.  ``model`` proves the idle standard pistol only;
firing and reload frames deliberately retain AA's native ART.  ``missing``
does not install a DEF mapping, while ``missing-frame`` uses a private MD3
copy whose named rest frame cannot resolve; both retain native weapon-card ART.
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
import time

import numpy as np
from PIL import Image
from monado_remote import Remote
from smoke_actions import Observer
from smoke_aim import orientation
from smoke_alien_armageddon import (PVP_CAPTURE, aa_samples, aa_wrapper,
                                    drive_character_selection, post_gameplay_capture)
from smoke_multiplayer import CONFIG, X11, stop


DEFAULT_ASSETS = Path(__file__).resolve().parents[3] / 'duke-vr-assets/aa-v1/exports/eduke32/aa_assets'
DEFAULT_COMPAT = Path(__file__).resolve().parents[2] / 'package/vr/aa566/eduke32_vr_aa566.con'
AA_RECEIPT = re.compile(
    r'OpenXR AA hand model receipt: serial=(\d+) tile=(-?\d+) shade=(-?\d+) '
    r'palette=(-?\d+) roles=(\d+) valid=(\d+)\.')


def model_observer() -> str:
    # One bounded read-only snapshot helps explain an ineligible native state;
    # only the observer's own scratch variables are assigned.
    labels = ('pchar LASERMODE brutalcount PLAYERONTHEBIKE slimpush juice_pos '
              'idleanim slidekick sidekick jumpkick qk_proxy doubletop movecam '
              'thiscam onturret zombieonplayer startmode newhud hud_shadef '
              'hud_palf WEAPON1_TOTALTIME').split()
    return (aa_wrapper(include_game=False) + '''
gamevar aamodel_reported 0 1
gamevar aamodel_upgrades 0 1
appendevent EVENT_PROCESSINPUT
ifvare aamodel_reported 0 ifvare startmode 1 ifvare aaobserve_weaponpos 0
{
 set aamodel_reported 1
 setvarvar aamodel_upgrades dukeupgrades[PISTOL_WEAPON]
 addlog aamodel_upgrades
''' + ''.join(f' addlog {label}\n' for label in labels) + '}\nendevent\n')


def image_contribution(root: Path, prefix: str) -> dict:
    """Read the renderer's own before/after color and depth captures."""
    changed, depth_changed, bounds = [], [], []
    for eye in ('left', 'right'):
        before = np.asarray(Image.open(root / f'{prefix}-before-{eye}.ppm'))
        after = np.asarray(Image.open(root / f'{prefix}-after-{eye}.ppm'))
        delta = np.any(before != after, axis=2)
        before_depth = np.frombuffer((root / f'{prefix}-before-{eye}-depth.bin').read_bytes(), dtype=np.uint32)
        after_depth = np.frombuffer((root / f'{prefix}-after-{eye}-depth.bin').read_bytes(), dtype=np.uint32)
        changed.append(int(delta.sum()))
        depth_changed.append(int(np.count_nonzero(before_depth != after_depth)))
        bounds.append(Image.fromarray(delta).getbbox())
    return {'changed_pixels': changed, 'depth_changed_pixels': depth_changed,
            'bounds': bounds, 'stereo_parallax': bounds[0] != bounds[1],
            'both_eyes_visible': min(changed) > 0 and min(depth_changed) > 0}


def native_weapon_card(root: Path) -> dict:
    """Inspect native weapon-card output without inferring it from a log line."""
    coverage = root / 'weapon-coverage.pgm'
    eyes = [root / f'weapon-{eye}.ppm' for eye in ('left', 'right')]
    if not coverage.is_file() or not all(path.is_file() for path in eyes):
        return {'available': False, 'coverage': False, 'eyes_distinct': False}
    images = [np.asarray(Image.open(path)) for path in eyes]
    return {'available': True, 'coverage': Image.open(coverage).getbbox() is not None,
            'eyes_distinct': not np.array_equal(*images)}


def fire_actual_aa_pistol(observer: Observer, remote: Remote) -> dict:
    """Fire one real remote-trigger edge and wait for AA's own ammo/shot rows."""
    local_rows = lambda text: aa_samples(text)
    observer.wait(lambda text: local_rows(text) and local_rows(text)[-1]['weaponpos'] == 0
                  and local_rows(text)[-1]['counter'] == 0, timeout=15)
    remote.neutral()
    hand = remote.packet.right
    hand.pose.position.x, hand.pose.position.y, hand.pose.position.z = .2, 1.3, -.5
    hand.pose.orientation = orientation(12, 8)
    remote.send()
    observer.pause(.5)
    before = local_rows(observer.text())[-1]
    start = len(observer.text())
    hand.trigger_value, hand.trigger_click = 1, True
    remote.send()
    try:
        fired_text = observer.wait(
            lambda text: any(row['shots'] > before['shots'] and row['ammo'] < before['ammo']
                             for row in local_rows(text[start:])), timeout=10)
    finally:
        hand.trigger_value, hand.trigger_click = 0, False
        remote.send()
    observer.wait(lambda text: local_rows(text)[-1]['counter'] == 0
                  and not (local_rows(text)[-1]['bits'] & 4), timeout=10)
    after = local_rows(observer.text())[-1]
    fired_rows = local_rows(fired_text[start:])
    return {'before': before, 'after': after,
            'trigger_seen': any(row['bits'] & 4 for row in fired_rows),
            'checks': {'native_ammo_consumed': after['ammo'] < before['ammo'],
                       'native_shot_event': after['shots'] > before['shots'],
                       'native_trigger_seen': any(row['bits'] & 4 for row in fired_rows)}}


def wait_for_character_selection(observer: Observer, process: subprocess.Popen, display: str, timeout: float) -> None:
    """Dismiss only AA's own opening screens through the owned private window."""
    deadline, next_press = time.monotonic() + timeout, 0.0
    while time.monotonic() < deadline:
        text = observer.text()
        rows = aa_samples(text)
        if rows and rows[-1]['startmode'] < 0:
            return
        if process.poll() is not None:
            raise RuntimeError('owned AA process exited before character selection')
        now = time.monotonic()
        if 'Per-map .art file' in text and now >= next_press:
            window, _ = X11(display).owned_window(process.pid)
            if window:
                X11(display).press(window, 'Return', .08, True)
                next_press = now + 1
        time.sleep(.05)
    raise RuntimeError('AA opening screens did not reach native character selection')


def missing_rest_fixture(root: Path, source: Path) -> dict:
    """Copy an MD3 and change only its static ``rest`` frame-name bytes."""
    original = source.read_bytes()
    if len(original) < 96:
        raise RuntimeError('AA pistol MD3 header is truncated')
    frame_count = struct.unpack_from('<i', original, 76)[0]
    frame_offset = struct.unpack_from('<i', original, 92)[0]
    if frame_count <= 0 or frame_offset < 0 or frame_offset + frame_count * 56 > len(original):
        raise RuntimeError('AA pistol MD3 has invalid frame metadata')
    rest_frames = [index for index in range(frame_count)
                   if original[frame_offset + index * 56 + 40:frame_offset + index * 56 + 56]
                   .split(b'\0', 1)[0] == b'rest']
    if len(rest_frames) != 1:
        raise RuntimeError('AA pistol MD3 must contain exactly one rest frame')
    frame_index = rest_frames[0]
    name_offset = frame_offset + frame_index * 56 + 40
    old_name = original[name_offset:name_offset + 16]
    replacement = b'no_rest\0' + old_name[8:]
    copy = bytearray(original)
    copy[name_offset:name_offset + 16] = replacement
    changed = [index for index, (before, after) in enumerate(zip(original, copy)) if before != after]
    expected = list(range(name_offset, name_offset + 7))
    if changed != expected or any(copy[index] != replacement[index - name_offset] for index in expected):
        raise RuntimeError('missing-frame fixture changed bytes outside the intended MD3 frame name')
    destination = root / 'duke_pistol_missing_rest.md3'
    destination.write_bytes(copy)
    return {'path': str(destination), 'sha256': hashlib.sha256(copy).hexdigest(),
            'source_sha256': hashlib.sha256(original).hexdigest(), 'frame_count': frame_count,
            'frame_index': frame_index,
            'frame_offset': frame_offset, 'name_offset': name_offset,
            'original_name': old_name.split(b'\0', 1)[0].decode('ascii'), 'replacement_name': 'no_rest',
            'changed_offsets': changed, 'only_frame_name_bytes_changed': changed == expected}


def write_private_def(root: Path, model: Path, skin: Path, frame_name: str = 'rest') -> dict:
    """Route AA's existing pickup tile 21 through a disposable MD3 definition."""
    surfaces = struct.unpack_from('<i', model.read_bytes(), 84)[0]
    if surfaces <= 0:
        raise RuntimeError('AA pistol MD3 has no surfaces')
    local_model, local_skin = root / 'duke_pistol.md3', root / 'duke_pistol.png'
    local_model.symlink_to(model)
    local_skin.symlink_to(skin)
    body = ['include "duke3d.def"', '', 'model "duke_pistol.md3" {', ' scale 0.5859375']
    body.extend(f' skin {{ pal 0 surface {index} file "duke_pistol.png" }}' for index in range(surfaces))
    body.extend((f' frame {{ name "{frame_name}" tile 21 smoothduration 0 }}', '}', ''))
    (root / 'aa-hand-model.def').write_text('\n'.join(body))
    return {'tile': 21, 'frame': frame_name, 'surfaces': surfaces, 'model': str(model), 'skin': str(skin)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=('model', 'missing', 'missing-frame'), default='model')
    parser.add_argument('--model-mode', choices=('native', 'sps'), default='native')
    for name in ('binary', 'mod-root', 'work-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--model', type=Path, default=DEFAULT_ASSETS / 'duke_pistol.md3')
    parser.add_argument('--skin', type=Path, default=DEFAULT_ASSETS / 'duke_pistol.png')
    parser.add_argument('--compat-con', type=Path, default=DEFAULT_COMPAT)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, required=True)
    parser.add_argument('--timeout', type=int, default=65)
    args = parser.parse_args()
    args.binary, args.mod_root, args.work_dir = (args.binary.resolve(), args.mod_root.resolve(), args.work_dir.resolve())
    args.compat_con = args.compat_con.resolve()
    args.model, args.skin = args.model.resolve(), args.skin.resolve()
    for path in (args.binary, args.compat_con, args.mod_root / 'AA.grp', args.mod_root / 'duke3d.def',
                 args.mod_root / 'scripts/AAGAME.CON'):
        if not path.is_file():
            parser.error('missing required read-only input: ' + str(path))
    if args.case in ('model', 'missing-frame'):
        for path in (args.model, args.skin):
            if not path.is_file():
                parser.error('missing required private AA asset: ' + str(path))
    args.work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='aa-hand-model-', dir=args.work_dir))
    process = None
    log = None
    phase = 'setup'
    result = {'passed': False, 'case': args.case, 'model_mode': args.model_mode,
              'evidence_directory': str(root), 'checks': {},
              'qualification': 'One idle standard Duke pistol only. Positive fire/reload counters retain native AA ART; the rest of AA arsenal and campaign remain unqualified.'}
    try:
        (root / 'eduke32.cfg').write_text(CONFIG + '\n[Screen Setup]\nPolymer = 0\n')
        (root / 'settings.cfg').write_text('// Private AA hand-model smoke preferences.\n')
        (root / 'autoexec.cfg').write_text('r_maxfps 5\n')
        (root / 'aa_hand_model_observer.con').write_text(model_observer())
        if args.case == 'missing-frame':
            result['missing_frame_fixture'] = missing_rest_fixture(root, args.model)
            result['model_mapping'] = write_private_def(
                root, Path(result['missing_frame_fixture']['path']), args.skin, 'no_rest')
        else:
            result['model_mapping'] = write_private_def(root, args.model, args.skin) if args.case == 'model' else None
        env = {key: value for key, value in os.environ.items() if not key.startswith('EDUKE32_XR')}
        env.update(DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy',
                   EDUKE32_XR='1', EDUKE32_XR_SINGLE_PASS='1', EDUKE32_XR_UI='2',
                   EDUKE32_XR_AIM='right', EDUKE32_XR_WEAPON='1', EDUKE32_XR_HAND_SHOTS='1',
                   EDUKE32_XR_MODELS='1', EDUKE32_XR_AA_MODELS='1', EDUKE32_XR_TEST_MODELS='1',
                   EDUKE32_XR_TEST_MODEL_ANIMATION='1', EDUKE32_XR_TEST_INPUT='1',
                   EDUKE32_XR_TEST_SHOTS='1', EDUKE32_XR_TEST_PVP='1',
                   EDUKE32_XR_MODEL_OUTPUT=str(root / 'model'),
                   EDUKE32_XR_WEAPON_OUTPUT=str(root / 'weapon'),
                   EDUKE32_XR_WORLD_OUTPUT=str(root / 'world'), EDUKE32_XR_HUD_OUTPUT=str(root / 'hud'))
        if args.model_mode == 'native':
            env['EDUKE32_XR_TEST_MODELS_TWO_PASS'] = '1'
        definition = 'aa-hand-model.def' if args.case in ('model', 'missing-frame') else 'duke3d.def'
        command = [str(args.binary), '-usecwd', '-nosetup', '-noautoload', '-nologo', '-ns', '-nm',
                   '-j', str(args.mod_root), '-j', str(args.compat_con.parent), '-g', str(args.mod_root / 'AA.grp'),
                   '-x', args.compat_con.name, '-mx', 'aa_hand_model_observer.con', '-h', definition,
                   '-v1', '-l2', '-s1']
        log = (root / 'game.log').open('w', encoding='utf-8')
        process = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT)
        observer = Observer(process, root / 'game.log')
        phase = 'native AA opening and controller selection'
        wait_for_character_selection(observer, process, args.display, min(45, args.timeout))
        with Remote(args.remote_port) as remote:
            controller = drive_character_selection(observer, remote)
            result['controller'] = controller
            selection_log_end = len(observer.text())
            observer.wait(lambda text: aa_samples(text) and aa_samples(text)[-1]['currentweapon'] == 1
                          and aa_samples(text)[-1]['ammo'] > 0 and aa_samples(text)[-1]['counter'] == 0,
                          timeout=12)
            prior_capture = max(map(int, PVP_CAPTURE.findall(observer.text())), default=0)
            phase = 'idle AA model/native card evidence'
            if args.case == 'model':
                required = [root / f'model-{suffix}-{eye}{extension}'
                            for suffix in ('before', 'after') for eye in ('left', 'right')
                            for extension in ('.ppm', '-depth.bin')]
                # The first eligible native weapon frame can be committed as
                # START transitions to gameplay.  Its receipt/captures are
                # still AA's real body draw, so do not discard that evidence
                # merely because controller selection returned a few lines
                # later.
                text = observer.wait(lambda value: AA_RECEIPT.search(value) and
                                     all(path.is_file() for path in required), timeout=25)
                receipt = [tuple(map(int, row)) for row in AA_RECEIPT.findall(text)][-1]
                result['receipt_evidence'] = {
                    'scope': 'whole log; first native START frame is accepted',
                    'observed_before_selection_return': bool(AA_RECEIPT.search(text[:selection_log_end])),
                    'capture_prefix': str(root / 'model'),
                }
                result['receipt'] = {'serial': receipt[0], 'tile': receipt[1], 'shade': receipt[2],
                                     'palette': receipt[3], 'roles': receipt[4], 'valid': receipt[5]}
                result['model_images'] = image_contribution(root, 'model')
            else:
                observer.pause(2)
            result['gameplay_capture'] = post_gameplay_capture(observer, root, prior_capture, timeout=25)
            result['weapon_card'] = native_weapon_card(root)
            phase = 'actual AA pistol fire'
            result['fire'] = fire_actual_aa_pistol(observer, remote)
        text = observer.text()
        rows = aa_samples(text)
        idle = [row for row in rows if row['startmode'] == 1 and row['pchar'] == 0 and row['currentweapon'] == 1]
        checks = result['checks']
        checks.update(actual_AA_compat_main_compiled=('Compiling: ' + args.compat_con.name in text or
                                                      'Including: ' + args.compat_con.name in text),
                      observer_compiled=('Compiling: aa_hand_model_observer.con' in text or
                                         'Including: aa_hand_model_observer.con' in text),
                      native_Duke_START_gameplay=bool(idle),
                      real_stereo_gameplay=result['gameplay_capture']['eyes_distinct'] and
                                           result['gameplay_capture']['eyes_nonconstant'],
                      native_weapon_card_observed=result['weapon_card']['available'],
                      no_XR_cancellation='OpenXR AA hand model frame canceled:' not in text and
                                         'OpenXR hand model frame canceled:' not in text,
                      core_validation_clean=not re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)', text),
                      game_remains_running=process.poll() is None)
        checks.update(result['fire']['checks'])
        positive_cards = [path for path in root.glob('weapon-counter-*-coverage.pgm')
                          if Image.open(path).getbbox() is not None]
        checks['positive_AA_counter_retains_native_ART'] = bool(positive_cards)
        if args.case == 'model':
            receipts = [tuple(map(int, row)) for row in AA_RECEIPT.findall(text)]
            receipt = result['receipt']
            contribution = result['model_images']
            matrices = re.findall(r'OpenXR hand model matrix: eye=(\d) values=([^\n]+)\.', text)
            projections = re.findall(r'OpenXR hand model projection: eye=(\d) values=([^\n]+)\.', text)
            submissions = [tuple(map(int, row)) for row in re.findall(
                r'hand models twoPass=(\d+) multiview=(\d+)', text)]
            checks.update(AA_idle_receipt_matches_native_CON_draw=(receipt['tile'] == 2524 and
                                                                    receipt['palette'] == 0 and
                                                                    receipt['roles'] == 1 and receipt['valid'] == 1),
                          native_body_callback_once_per_model_receipt=bool(receipts) and
                              len({row[0] for row in receipts}) == len(receipts) and
                              all(row[4:] == (1, 1) for row in receipts),
                          real_MD3_color_and_depth_contribution_both_eyes=contribution['both_eyes_visible'],
                          real_MD3_stereo_parallax=contribution['stereo_parallax'],
                          native_model_matrices_and_projections_for_both_eyes=
                              [int(row[0]) for row in matrices[-2:]] == [0, 1] and
                              [int(row[0]) for row in projections[-2:]] == [0, 1],
                          native_ART_body_suppressed=result['weapon_card']['available'] and
                                                     not result['weapon_card']['coverage'],
                          model_submission_mode=(any(two_pass > 0 and multiview == 0 for two_pass, multiview in submissions)
                                                 if args.model_mode == 'native' else
                                                 ('OpenXR hand model single-pass:' in text)))
            if args.model_mode == 'sps':
                collected = [root / f'model-collected-{eye}{suffix}' for eye in ('left', 'right')
                             for suffix in ('.ppm', '-depth.bin')]
                before = [root / f'model-before-{eye}{suffix}' for eye in ('left', 'right')
                          for suffix in ('.ppm', '-depth.bin')]
                reference = [root / f'model-reference-{eye}{suffix}' for eye in ('left', 'right')
                             for suffix in ('.ppm', '-depth.bin')]
                after = [root / f'model-after-{eye}{suffix}' for eye in ('left', 'right')
                         for suffix in ('.ppm', '-depth.bin')]
                calls = [tuple(map(int, row)) for row in re.findall(
                    r'OpenXR hand model single-pass: paired=(\d+) eyeOnly=(\d+) shared=(\d+) sharedVertices=(\d+)\.', text)]
                collection_clean = all(path.is_file() for path in before + collected) and all(
                    before[index].read_bytes() == collected[index].read_bytes() for index in range(len(before)))
                reference_exact = all(path.is_file() for path in reference + after) and all(
                    reference[index].read_bytes() == after[index].read_bytes() for index in range(len(reference)))
                shared = calls[-1] if calls else None
                result['sps_oracle'] = {
                    'native_inputs_identical': 'OpenXR hand model oracle inputs: identical=1.' in text,
                    'reference_color_depth_exact': reference_exact,
                    'collection_color_depth_unchanged': collection_clean,
                    'shared_geometry': {'paired': shared[0], 'eye_only': shared[1],
                                        'shared': shared[2], 'vertices': shared[3]} if shared else None,
                }
                checks.update(SPS_same_frame_native_oracle_inputs_identical=result['sps_oracle']['native_inputs_identical'],
                              SPS_same_frame_native_reference_color_depth_exact=reference_exact,
                              SPS_collection_did_not_write_color_or_depth=collection_clean,
                              SPS_shared_model_geometry_submitted_once=bool(shared) and shared[0] > 0 and
                                  shared[1] == 0 and shared[0] == shared[2] and shared[3] > 0)
        else:
            checks.update(no_MD3_receipt=not AA_RECEIPT.search(text),
                          no_MD3_capture=not (root / 'model-after-left.ppm').exists(),
                          native_ART_body_visible=result['weapon_card']['available'] and result['weapon_card']['coverage'])
            if args.case == 'missing-frame':
                checks['missing_rest_fixture_only_changed_frame_name'] = \
                    result['missing_frame_fixture']['only_frame_name_bytes_changed']
        if os.environ.get('EDUKE32_TEST_PRIVATE_WINDOW') == '1':
            window, _ = X11(args.display).owned_window(process.pid)
            if not window:
                raise RuntimeError('owned AA private drawable missing')
            state = X11(args.display).window_visibility(window)
            checks.update(private_drawable_unmapped=state['unmapped'], no_desktop_focus=not state['has_desktop_focus'])
        result['native_rows'] = idle[-8:]
        result['passed'] = all(checks.values())
    except Exception as error:
        result['error'] = str(error)
    finally:
        result['phase'] = phase
        if process is not None:
            stop(process)
        if log is not None:
            log.close()
    result['cleanup'] = process is None or process.poll() is not None
    inputs = [args.binary, args.compat_con, args.mod_root / 'AA.grp', args.mod_root / 'duke3d.def',
              args.mod_root / 'scripts/AAGAME.CON']
    if args.case in ('model', 'missing-frame'):
        inputs.extend((args.model, args.skin))
    result['sha256'] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
