#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Qualify AA's optional native Duke-pistol MD3 presentation in software XR.

Run this child under ``software_xr_lab.py``.  It only writes below
``--work-dir``: the installed AA directory, compatibility CON, and exported
MD3/skin remain read-only.  ``model`` proves the idle standard pistol only.
With ``--animation`` and an explicitly supplied private MD3, natural AA
reload counter 6..26 may qualify model frames; firing counter 1..5 and AA's
reload hand remain native ART.  ``missing``
does not install a DEF mapping, while ``missing-frame`` uses a private MD3
copy whose named rest frame cannot resolve; both retain native weapon-card ART.
``duplicate-body`` issues an extra native CON body draw after a valid model
frame and proves cancellation before that mismatched frame can be submitted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
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
MODEL_RECEIPT = re.compile(
    r'OpenXR hand model receipt: serial=(\d+) counter=(\d+) reloading=(\d+) roles=(\d+) valid=(\d+)\.')
MODEL_SAMPLE = re.compile(
    r'OpenXR hand model sample: serial=(\d+) counter=(\d+) reloading=(\d+) frame=(\d+)\.')
MASK_ORACLE_RECEIPT = re.compile(r'OpenXR native mask oracle replay captured: serial=(\d+)\.')
MASK_ORACLE_INPUT = re.compile(
    r'OpenXR native mask oracle input: eye=(\d+) family=(voxel|art) equal=(\d+)\.')
MASK_ORACLE_SUBMISSION = re.compile(
    r'OpenXR masks single-pass: frame=(\d+) .*? voxels=(\d+) voxelsPaired=(\d+) indexedVoxelIndices=(\d+)')
WORLD_MASK_COUNTERS = re.compile(
    r'OpenXR world oracle: 60 frames, opaque multiview=(\d+) twoPass=(\d+); '
    r'masks multiview=(\d+) twoPass=(\d+) full multiview=(\d+);')
AA_RELOAD_FIELDS = ('tick', 'counter', 'reloading', 'ammo', 'thisclip', 'hudshade', 'playershade', 'pistolclip')
AA_RELOAD_SAMPLE = re.compile(r'addlog aareload_(\w+)(?: \(player \d+\))? = (-?\d+)')
AA_BODY_TILES = {2524, 2525, 2526, 2528, 2529, 5122}
AA_AIM_DOWN_BIT = 1 << 4


def aa_reload_samples(text: str) -> list[dict]:
    """Read complete observer-only AA pistol clip rows."""
    rows, current = [], {}
    for key, value in AA_RELOAD_SAMPLE.findall(text):
        if key == 'tick':
            current = {'tick': int(value)}
        elif current:
            current[key] = int(value)
            if key == 'pistolclip' and all(name in current for name in AA_RELOAD_FIELDS):
                rows.append(current)
    return rows


def aa_body_receipts(text: str) -> list[tuple[int, int, int, int, int, int]]:
    """Keep validated AA body receipts, excluding unclaimed magazine draws."""
    return [tuple(map(int, row)) for row in AA_RECEIPT.findall(text) if int(row[1]) in AA_BODY_TILES]


def model_observer() -> str:
    # One bounded read-only snapshot helps explain an ineligible native state;
    # only the observer's own scratch variables are assigned.
    labels = ('pchar LASERMODE brutalcount PLAYERONTHEBIKE slimpush juice_pos '
              'idleanim slidekick sidekick jumpkick qk_proxy doubletop movecam '
              'thiscam onturret zombieonplayer startmode newhud hud_shadef '
              'hud_palf WEAPON1_TOTALTIME').split()
    return (aa_wrapper(include_game=False) +
            ''.join(f'gamevar aareload_{name} 0 1\n' for name in AA_RELOAD_FIELDS) + '''
gamevar aamodel_reported 0 1
gamevar aamodel_upgrades 0 1
appendevent EVENT_PROCESSINPUT
ifvare aamodel_reported 0 ifvare startmode 1 ifvare aaobserve_weaponpos 0
{
 set aamodel_reported 1
 setvarvar aamodel_upgrades dukeupgrades[PISTOL_WEAPON]
 addlog aamodel_upgrades
''' + ''.join(f' addlog {label}\n' for label in labels) + '''}
addvar aareload_tick 1
getplayer[THISACTOR].kickback_pic aareload_counter
getplayer[THISACTOR].reloading aareload_reloading
getplayer[THISACTOR].ammo_amount PISTOL_WEAPON aareload_ammo
setvarvar aareload_thisclip THISCLIP
setvarvar aareload_hudshade hud_shadef
geta[player[].i].shade aareload_playershade
setvarvar aareload_pistolclip PISTOLCLIP
''' + ''.join(f'addlog aareload_{name}\n' for name in AA_RELOAD_FIELDS) + 'endevent\n')


DUPLICATE_BODY = '''
// Armed only after the runner observes a successful real AA model frame.
// The native VM issues a second body draw inside the owned weapon segment.
gamevar aamodelfault 0 1
appendevent EVENT_DRAWWEAPON
ifvare aamodelfault 1
{
 guniqhudid PISTOL_WEAPON
 rotatesprite16 10485760 6553600 32768 0 FIRSTGUN 2 0 6146 0 0 xdim ydim
 guniqhudid 0
 set aamodelfault 2
 addlog aamodelfault
}
endevent
'''


def duplicate_body_fault(observer: Observer, process: subprocess.Popen, display: str) -> dict:
    start = len(observer.text())
    x11 = X11(display)
    window, _ = x11.owned_window(process.pid)
    if not window:
        raise RuntimeError('owned AA drawable missing before duplicate-body fault')
    x11.press(window, 'F4', .08, True)
    # Observer deliberately rejects XR shutdown during normal gameplay. This
    # fault alone expects it, so read the owned log directly after arming it.
    deadline = time.monotonic() + 12
    while True:
        if process.poll() is not None:
            raise RuntimeError('owned AA game exited during duplicate-body fault')
        text = observer.path.read_text(errors='replace')[start:]
        if 'OpenXR world stopped:' in text:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError('duplicate-body cancellation timeout')
        time.sleep(.05)
    canceled = [tuple(map(int, row)) for row in re.findall(
        r'OpenXR hand model frame canceled: serial=(\d+) submitted=(\d+)\.', text)]
    mismatch = re.findall(r'OpenXR AA hand model draw mismatch: ([^\n]+)', text)
    return {'canceled': canceled, 'mismatch': mismatch,
            'checks': {
                'native_duplicate_body_event_executed': bool(re.search(r'addlog aamodelfault.* = 2', text)),
                'duplicate_rejected_inside_owned_segment': any('tile=2524 id=1 shade=2 palette=0 flags=6146 angle=0 alpha=0 blend=0 segment=1 roles=1.' in row for row in mismatch),
                'written_frame_canceled_before_submission': len(canceled) == 1 and canceled[0][0] > canceled[0][1],
                'XR_disabled_for_receipt_mismatch': 'held-model/native weapon receipt mismatch' in text,
            }}


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


def _mask_capture(root: Path, prefix: str, stage: str, eye: str) -> dict:
    """Read one engine-owned MASK capture without treating absent files as data."""
    color_path = root / f'{prefix}-{stage}-{eye}.ppm'
    depth_path = root / f'{prefix}-{stage}-{eye}-depth.bin'
    record = {'color_path': str(color_path), 'depth_path': str(depth_path), 'available': False}
    if not color_path.is_file() or not depth_path.is_file():
        return record
    try:
        image = np.asarray(Image.open(color_path).convert('RGB'))
        depth = depth_path.read_bytes()
    except OSError:
        return record
    complete_depth = len(depth) == image.shape[0] * image.shape[1] * 4
    record.update(image=image, depth=depth, size=[int(image.shape[1]), int(image.shape[0])],
                  available=True, complete_depth=complete_depth)
    return record


def _mask_pair(expected: dict, actual: dict) -> dict:
    """Compare complete RGB/depth captures and retain failure distinctions."""
    available = expected['available'] and actual['available']
    dimensions = available and expected['image'].shape == actual['image'].shape
    depth_complete = available and expected['complete_depth'] and actual['complete_depth']
    rgb_exact = dimensions and bool(np.array_equal(expected['image'], actual['image']))
    depth_exact = depth_complete and expected['depth'] == actual['depth']
    return {'available': available, 'dimensions_equal': dimensions,
            'rgb_exact': rgb_exact, 'raw_depth_exact': depth_exact,
            'complete_exact': dimensions and depth_complete and rgb_exact and depth_exact}


def mask_oracle_evidence(root: Path, prefix: str, text: str) -> dict:
    """Evaluate an engine-produced whole-MASK same-frame replay receipt.

    This is deliberately a pure reader so focused tests can prove that missing
    captures, collection writes, and omitted input receipts fail independently.
    """
    captures = {stage: {eye: _mask_capture(root, prefix, stage, eye)
                        for eye in ('left', 'right')}
                for stage in ('reference', 'mask-before', 'mask-after', 'replayed')}
    replay = {eye: _mask_pair(captures['reference'][eye], captures['replayed'][eye])
              for eye in ('left', 'right')}
    collection = {eye: _mask_pair(captures['mask-before'][eye], captures['mask-after'][eye])
                  for eye in ('left', 'right')}
    contribution = {}
    for eye in ('left', 'right'):
        before, after = captures['mask-before'][eye], captures['replayed'][eye]
        valid = (before['available'] and after['available'] and before['complete_depth'] and
                 after['complete_depth'] and before['image'].shape == after['image'].shape)
        if valid:
            color_delta = np.any(before['image'] != after['image'], axis=2)
            before_depth = np.frombuffer(before['depth'], dtype=np.uint32)
            after_depth = np.frombuffer(after['depth'], dtype=np.uint32)
            depth_delta = before_depth != after_depth
            contribution[eye] = {'available': True, 'color_changed_pixels': int(color_delta.sum()),
                                 'depth_changed_pixels': int(depth_delta.sum()),
                                 'visible': bool(color_delta.any() and depth_delta.any())}
        else:
            contribution[eye] = {'available': False, 'color_changed_pixels': 0,
                                 'depth_changed_pixels': 0, 'visible': False}
    receipts = [int(value) for value in MASK_ORACLE_RECEIPT.findall(text)]
    first_inputs = {}
    input_receipts = MASK_ORACLE_INPUT.findall(text)
    for eye, family, equal in input_receipts:
        first_inputs.setdefault(int(eye), {'family': family, 'equal': int(equal)})
    submissions = [{'frame': int(frame), 'voxels': int(voxels), 'voxels_paired': int(paired),
                    'indexed_voxel_indices': int(indices)}
                   for frame, voxels, paired, indices in MASK_ORACLE_SUBMISSION.findall(text)]
    counters = [tuple(map(int, values)) for values in WORLD_MASK_COUNTERS.findall(text)]
    last_counter = counters[-1] if counters else None
    return {
        'prefix': str(root / prefix),
        'reference_replay': replay,
        'collection': collection,
        'contribution': contribution,
        'receipt_serials': receipts,
        'first_inputs': first_inputs,
        'mask_submissions': submissions,
        'world_counters': ({'opaque_multiview': last_counter[0], 'opaque_two_pass': last_counter[1],
                            'masks_multiview': last_counter[2], 'masks_two_pass': last_counter[3],
                            'full_multiview': last_counter[4]} if last_counter else None),
        'checks': {
            'SPS_MASK_reference_replay_complete_exact': all(item['complete_exact'] for item in replay.values()),
            'SPS_MASK_collection_color_depth_unchanged': all(item['complete_exact'] for item in collection.values()),
            'SPS_MASK_visible_color_depth_contribution_both_eyes': all(item['visible'] for item in contribution.values()),
            'SPS_MASK_single_positive_replay_receipt': len(receipts) == 1 and receipts[0] > 0,
            'SPS_MASK_first_inputs_equal_for_both_eyes': len(input_receipts) == 2 and set(first_inputs) == {0, 1} and
                all(item['family'] in ('voxel', 'art') and item['equal'] == 1 for item in first_inputs.values()),
            'SPS_MASK_indexed_voxel_submission_at_capture': bool(submissions) and
                submissions[-1]['frame'] == 59 and
                submissions[-1]['voxels'] > 0 and submissions[-1]['voxels_paired'] > 0 and
                submissions[-1]['indexed_voxel_indices'] > 0,
        },
    }


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


def reload_actual_aa_pistol(observer: Observer, process: subprocess.Popen, display: str) -> dict:
    """Press AA's installed Reload/Aim_Down binding after a real partial clip."""
    # Native shot lighting fades through AA's existing shade history. Wait for
    # the supported steady presentation, without assigning either shade value.
    observer.wait(lambda text: bool(aa_reload_samples(text)) and
                  aa_reload_samples(text)[-1]['counter'] == 0 and
                  aa_reload_samples(text)[-1]['hudshade'] == min(aa_reload_samples(text)[-1]['playershade'], 24),
                  timeout=12)
    before = aa_samples(observer.text())[-1]
    before_clip_rows = aa_reload_samples(observer.text())
    if not before_clip_rows:
        raise RuntimeError('AA pistol clip observer did not produce a complete row before reload')
    before_clip = before_clip_rows[-1]
    if before['ammo'] <= 0 or not 0 < before_clip['thisclip'] < before_clip['pistolclip']:
        raise RuntimeError('AA reload requested without a live partial pistol clip')
    window, _ = X11(display).owned_window(process.pid)
    if not window:
        raise RuntimeError('owned AA drawable missing before native reload input')
    start = len(observer.text())
    # AA's settings bind End to gamefunc_RELOAD_WEAPON.  AAPLAYER names that
    # input at index 18 and receives it through EVENT_AIMDOWN; no CON state is
    # injected here.
    # A short press can begin and end between two software-rendered frames.
    # Hold through a native input poll; AA itself rejects repeats while reloading.
    X11(display).press(window, 'End', .3, True)
    entered_text = observer.wait(
        lambda text: any(row['reloading'] == 1 and row['counter'] >= 6
                         for row in aa_reload_samples(text[start:])), timeout=12)
    returned_text = observer.wait(
        lambda text: any(row['counter'] == 0 and row['reloading'] == 0
                         and row['thisclip'] == row['pistolclip'] and row['ammo'] == before['ammo']
                         for row in aa_reload_samples(text[start:])), timeout=15)
    rows = aa_reload_samples(returned_text[start:])
    input_rows = aa_samples(returned_text[start:])
    return {'before': before, 'before_clip': before_clip, 'rows': rows,
            'entered': aa_reload_samples(entered_text[start:]), 'after': rows[-1],
            'checks': {
                'native_Aim_Down_reload_bit_seen': any(row['bits'] & AA_AIM_DOWN_BIT for row in input_rows),
                'native_partial_clip_before_reload': 0 < before_clip['thisclip'] < before_clip['pistolclip'],
                'native_reload_enters': any(row['reloading'] == 1 and row['counter'] >= 6 for row in rows),
                'native_clip_refills_at_counter_26': any(row['counter'] == 26 and
                    row['thisclip'] == row['pistolclip'] for row in rows),
                'native_reload_returns_to_rest_with_total_ammo_unchanged': rows[-1]['counter'] == 0 and
                    rows[-1]['reloading'] == 0 and rows[-1]['thisclip'] == rows[-1]['pistolclip'] and
                    rows[-1]['ammo'] == before['ammo'],
            }}


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


def animation_frames(model: Path) -> dict:
    """Validate the external AA MD3's authored native-counter frame names."""
    data = model.read_bytes()
    if len(data) < 96:
        raise RuntimeError('AA animation MD3 header is truncated')
    count = struct.unpack_from('<i', data, 76)[0]
    offset = struct.unpack_from('<i', data, 92)[0]
    if count <= 0 or offset < 0 or offset + count * 56 > len(data):
        raise RuntimeError('AA animation MD3 has invalid frame metadata')
    names = [data[offset + index * 56 + 40:offset + index * 56 + 56]
             .split(b'\0', 1)[0].decode('ascii', errors='strict') for index in range(count)]
    required = ['rest'] + [f'reload_{counter:02d}' for counter in range(6, 27)]
    missing = [name for name in required if name not in names]
    if missing:
        raise RuntimeError('AA animation MD3 is missing required frame names: ' + ', '.join(missing))
    return {'frame_count': count, 'frame_offset': offset, 'names': names,
            'required_names': required, 'all_required_names_present': not missing}


def missing_reload_fixture(root: Path, source: Path, counter: int) -> dict:
    """Rename only one private reload-frame name; preserve every MD3 payload byte."""
    metadata = animation_frames(source)
    original = source.read_bytes()
    target = f'reload_{counter:02d}'.encode()
    indices = [index for index, name in enumerate(metadata['names']) if name.encode() == target]
    if len(indices) != 1:
        raise RuntimeError(f'AA animation MD3 must contain exactly one {target.decode()} frame')
    index = indices[0]
    name_offset = metadata['frame_offset'] + index * 56 + 40
    old_name = original[name_offset:name_offset + 16]
    replacement = f'no_reload{counter:02d}'.encode() + b'\0' + old_name[12:]
    copy = bytearray(original)
    copy[name_offset:name_offset + 16] = replacement
    changed = [offset for offset, (before, after) in enumerate(zip(original, copy)) if before != after]
    destination = root / f'duke_pistol_missing_reload_{counter:02d}.md3'
    destination.write_bytes(copy)
    return {'path': str(destination), 'counter': counter, 'frame_index': index,
            'frame_offset': metadata['frame_offset'], 'name_offset': name_offset,
            'original_name': target.decode(), 'replacement_name': replacement.split(b'\0', 1)[0].decode(),
            'changed_offsets': changed, 'source_sha256': hashlib.sha256(original).hexdigest(),
            'sha256': hashlib.sha256(copy).hexdigest(),
            'only_chosen_frame_name_bytes_changed': all(name_offset <= offset < name_offset + 16 for offset in changed),
            'payload_unchanged': original[:name_offset] == copy[:name_offset] and
                                 original[name_offset + 16:] == copy[name_offset + 16:]}


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


def animation_oracles(root: Path, samples: list[tuple[int, int, int, int]], names: list[str],
                      receipts: list[tuple[int, int, int, int, int]]) -> dict:
    """Read only captures made for naturally observed accepted model frames."""
    receipt_by_serial = {serial: (counter, reloading, roles, valid)
                         for serial, counter, reloading, roles, valid in receipts}
    counters, accepted = {}, []
    for serial, counter, reloading, frame in samples:
        if counter in counters:
            continue
        if frame < 0 or frame >= len(names):
            counters[counter] = {'frame_index_in_model': False}
            continue
        prefix = root / f'model-counter-{counter:02d}'
        model_files = [Path(str(prefix) + f'-{stage}-{eye}{suffix}')
                       for stage in ('before', 'collected', 'reference', 'after')
                       for eye in ('left', 'right') for suffix in ('.ppm', '-depth.bin')]
        required_name = 'fire_%02d' % counter if 1 <= counter <= 5 else \
            'reload_%02d' % counter if counter >= 6 else 'rest'
        receipt = receipt_by_serial.get(serial)
        expected_roles = 3 if 10 <= counter <= 19 else 1
        if not all(path.is_file() for path in model_files):
            counters[counter] = {'frame_index_in_model': True, 'captures_available': False}
            continue
        equal = all((root / f'model-counter-{counter:02d}-reference-{eye}{suffix}').read_bytes() ==
                    (root / f'model-counter-{counter:02d}-after-{eye}{suffix}').read_bytes()
                    for eye in ('left', 'right') for suffix in ('.ppm', '-depth.bin'))
        clean = all((root / f'model-counter-{counter:02d}-before-{eye}{suffix}').read_bytes() ==
                    (root / f'model-counter-{counter:02d}-collected-{eye}{suffix}').read_bytes()
                    for eye in ('left', 'right') for suffix in ('.ppm', '-depth.bin'))
        visible = all(not np.array_equal(np.asarray(Image.open(root / f'model-counter-{counter:02d}-before-{eye}.ppm')),
                                         np.asarray(Image.open(root / f'model-counter-{counter:02d}-after-{eye}.ppm')))
                      for eye in ('left', 'right'))
        counters[counter] = {
            'frame_index_in_model': True, 'captures_available': True,
            'native_counter_frame_name': names[frame] == required_name,
            'native_color_depth_reference_exact': equal,
            'collection_color_depth_unchanged': clean,
            'visible_both_eyes': visible,
            'valid_native_receipt': receipt is not None and receipt[0] == counter and receipt[1] == reloading
                and receipt[3] == 1,
            'native_receipt_roles_match': receipt is not None and receipt[2] == expected_roles,
            'receipt_roles': receipt[2] if receipt else None,
        }
        accepted.append((serial, counter, reloading, frame))
    return {'counter_checks': counters, 'accepted_samples': accepted}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=('model', 'missing', 'missing-frame', 'duplicate-body'), default='model')
    parser.add_argument('--model-mode', choices=('native', 'sps'))
    parser.add_argument('--palm-mount', action='store_true', help='Enable the tagged standard-pistol muzzle calibration')
    parser.add_argument('--opaque-rejection-diagnostics', action='store_true', help='Record bounded production world collection rejection predicates')
    parser.add_argument('--mask-rejection-diagnostics', action='store_true', help='Record bounded AA MASK model or voxel rejection mappings')
    parser.add_argument('--mask-oracle', action='store_true',
                        help='Require same-frame native whole-MASK collection/replay parity in SPS mode')
    parser.add_argument('--animation', action='store_true',
                        help='qualify native AA firing ART and reload model frames from an explicit private MD3')
    parser.add_argument('--floating-hands', type=Path, help='Private calibrated hand MD3/PNG directory')
    parser.add_argument('--missing-reload-frame', type=int, choices=range(6, 26),
                        help='remove one private reload frame (6..25), requiring model recovery at a later reload counter')
    for name in ('binary', 'mod-root', 'work-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--model', type=Path, default=DEFAULT_ASSETS / 'duke_pistol.md3')
    parser.add_argument('--skin', type=Path, default=DEFAULT_ASSETS / 'duke_pistol.png')
    parser.add_argument('--compat-con', type=Path, default=DEFAULT_COMPAT)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, required=True)
    parser.add_argument('--timeout', type=int, default=65)
    args = parser.parse_args()
    if args.floating_hands and (args.case != 'model' or args.animation or args.model_mode != 'sps'):
        parser.error('--floating-hands requires --case model --model-mode sps without animation')
    explicit_model = any(value == '--model' or value.startswith('--model=') for value in sys.argv[1:])
    if args.animation and args.case != 'model':
        parser.error('--animation requires --case model')
    if args.animation and not explicit_model:
        parser.error('--animation requires an explicit external --model')
    if args.animation and args.model_mode == 'native':
        parser.error('--animation requires SPS model qualification')
    if args.missing_reload_frame is not None and not args.animation:
        parser.error('--missing-reload-frame requires --animation')
    args.model_mode = args.model_mode or ('sps' if args.animation else 'native')
    if args.mask_oracle and args.model_mode != 'sps':
        parser.error('--mask-oracle requires --model-mode sps')
    model_case = args.case in ('model', 'duplicate-body')
    args.binary, args.mod_root, args.work_dir = (args.binary.resolve(), args.mod_root.resolve(), args.work_dir.resolve())
    args.compat_con = args.compat_con.resolve()
    args.model, args.skin = args.model.resolve(), args.skin.resolve()
    for path in (args.binary, args.compat_con, args.mod_root / 'AA.grp', args.mod_root / 'duke3d.def',
                 args.mod_root / 'scripts/AAGAME.CON'):
        if not path.is_file():
            parser.error('missing required read-only input: ' + str(path))
    if model_case or args.case == 'missing-frame':
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
              'qualification': ('Native standard Duke pistol rest/reload model frames; firing remains native ART.'
                                if args.animation else
                                'One idle standard Duke pistol only. Positive fire/reload counters retain native AA ART; the rest of AA arsenal and campaign remain unqualified.')}
    try:
        (root / 'eduke32.cfg').write_text(CONFIG + '\n[Screen Setup]\nPolymer = 0\n')
        (root / 'settings.cfg').write_text('// Private AA hand-model smoke preferences.\n')
        fault = args.case == 'duplicate-body'
        (root / 'autoexec.cfg').write_text(
            f'r_maxfps {60 if args.animation else 5}\n' +
            ('bind End "gamefunc_RELOAD_WEAPON"\n' if args.animation else '') +
            ('bind F4 norepeat "setvar aamodelfault 1"\n' if fault else ''))
        from pistol_mount_check import observer as mount_observer
        (root / 'aa_hand_model_observer.con').write_text(model_observer() + (DUPLICATE_BODY if fault else '')
                                                       + (mount_observer() if args.palm_mount else ''))
        if args.case == 'missing-frame':
            result['missing_frame_fixture'] = missing_rest_fixture(root, args.model)
            result['model_mapping'] = write_private_def(
                root, Path(result['missing_frame_fixture']['path']), args.skin, 'no_rest')
        elif args.animation:
            result['animation_model'] = animation_frames(args.model)
            mapped_model = args.model
            if args.missing_reload_frame is not None:
                result['missing_reload_fixture'] = missing_reload_fixture(root, args.model, args.missing_reload_frame)
                mapped_model = Path(result['missing_reload_fixture']['path'])
            result['model_mapping'] = write_private_def(root, mapped_model, args.skin)
        else:
            result['model_mapping'] = write_private_def(root, args.model, args.skin) if model_case else None
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
        if args.opaque_rejection_diagnostics:
            env['EDUKE32_XR_TEST_OPAQUE_REJECTIONS'] = '1'
        if args.mask_rejection_diagnostics:
            env['EDUKE32_XR_TEST_MASK_REJECTIONS'] = '1'
        if args.mask_oracle:
            result['mask_oracle'] = {'prefix': str(root / 'mask-oracle')}
            env['EDUKE32_XR_TEST_MASK_ORACLE'] = str(root / 'mask-oracle')
        if args.palm_mount:
            env['EDUKE32_XR_PISTOL_MOUNT'] = '1'
            env['EDUKE32_XR_TEST_PISTOL_MOUNT'] = '1'
        definition = 'aa-hand-model.def' if model_case or args.case == 'missing-frame' else 'duke3d.def'
        if args.floating_hands:
            from floating_hands_check import configure
            result['hand_assets'] = configure(root, root / definition, args.floating_hands, env)
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
            if model_case:
                required = [root / f'model-{suffix}-{eye}{extension}'
                            for suffix in ('before', 'after') for eye in ('left', 'right')
                            for extension in ('.ppm', '-depth.bin')]
                # The first eligible native weapon frame can be committed as
                # START transitions to gameplay.  Its receipt/captures are
                # still AA's real body draw, so do not discard that evidence
                # merely because controller selection returned a few lines
                # later.
                text = observer.wait(lambda value: aa_body_receipts(value) and
                                     all(path.is_file() for path in required), timeout=25)
                receipt = aa_body_receipts(text)[-1]
                result['receipt_evidence'] = {
                    'scope': 'whole log; first native START frame is accepted',
                    'observed_before_selection_return': bool(aa_body_receipts(text[:selection_log_end])),
                    'capture_prefix': str(root / 'model'),
                }
                result['receipt'] = {'serial': receipt[0], 'tile': receipt[1], 'shade': receipt[2],
                                     'palette': receipt[3], 'roles': receipt[4], 'valid': receipt[5]}
                result['model_images'] = image_contribution(root, 'model')
            else:
                observer.pause(2)
            result['gameplay_capture'] = post_gameplay_capture(observer, root, prior_capture, timeout=25)
            result['weapon_card'] = native_weapon_card(root)
            if fault:
                phase = 'actual native AA duplicate-body draw'
                result['fault'] = duplicate_body_fault(observer, process, args.display)
            else:
                phase = 'actual AA pistol fire'
                result['fire'] = fire_actual_aa_pistol(observer, remote)
                if args.animation:
                    phase = 'actual native AA Reload/Aim_Down'
                    result['reload'] = reload_actual_aa_pistol(observer, process, args.display)
                if args.floating_hands:
                    from floating_hands_check import exercise
                    phase = 'actual AA floating grip models'
                    result['floating_hands'] = exercise(observer, remote, root)
            if args.mask_oracle:
                phase = 'same-frame native whole-MASK replay oracle'
                observer.wait(lambda value: bool(MASK_ORACLE_RECEIPT.findall(value)), timeout=25)
        text = observer.path.read_text(errors='replace') if fault else observer.text()
        if args.mask_oracle:
            result['mask_oracle'] = mask_oracle_evidence(root, 'mask-oracle', text)
        rows = aa_samples(text)
        idle = [row for row in rows if row['startmode'] == 1 and row['pchar'] == 0 and row['currentweapon'] == 1]
        checks = result['checks']
        if args.floating_hands:
            checks.update(result['floating_hands']['checks'])
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
        if fault:
            del checks['no_XR_cancellation']
            checks.update(result['fault']['checks'])
        else:
            checks.update(result['fire']['checks'])
            if args.animation:
                checks.update(result['reload']['checks'])
            else:
                positive_cards = [path for path in root.glob('weapon-counter-*-coverage.pgm')
                                  if Image.open(path).getbbox() is not None]
                checks['positive_AA_counter_retains_native_ART'] = bool(positive_cards)
        if model_case:
            if args.palm_mount:
                checks['sampled_palm_mount_observed'] = 'OpenXR pistol mount pose:' in text
                from pistol_mount_check import firing
                result['palm_mount_firing']=firing(text,args.model)
                checks.update(result['palm_mount_firing']['checks'])
            receipts = aa_body_receipts(text)
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
                              all(row[5] == 1 for row in receipts),
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
            if args.animation:
                samples = [tuple(map(int, row)) for row in MODEL_SAMPLE.findall(text) if int(row[1]) > 0]
                receipts = [tuple(map(int, row)) for row in MODEL_RECEIPT.findall(text)]
                animation = animation_oracles(root, samples, result['animation_model']['names'], receipts)
                result['animation'] = animation
                counter_checks = animation['counter_checks']
                body_receipt_serials = {row[0] for row in aa_body_receipts(text) if row[5] == 1}
                reloading = [row for row in animation['accepted_samples']
                             if 6 <= row[1] <= 26 and row[2] == 1]
                magazine = [row for row in reloading if 10 <= row[1] <= 19 and
                            counter_checks[row[1]].get('receipt_roles') == 3]
                # These files are emitted only when the engine naturally sees
                # the native counter. A passing animation run must capture the
                # flash and the later reload hand; neither is inferred from an
                # absent capture or an all-ART fallback.
                native_art = {}
                for path in root.glob('weapon-counter-*-coverage.pgm'):
                    counter = int(path.name.split('-')[2])
                    if 1 <= counter <= 5 or 20 <= counter <= 24 or counter == args.missing_reload_frame:
                        native_art[counter] = Image.open(path).getbbox() is not None
                result['native_ART_captures'] = native_art
                flash_art = [counter for counter in (1, 2) if native_art.get(counter)]
                recovery_art = [counter for counter in range(3, 6) if native_art.get(counter)]
                hand_art = [counter for serial, counter, _, _ in animation['accepted_samples']
                            if 20 <= counter <= 24 and native_art.get(counter) and serial in body_receipt_serials
                            and counter_checks[counter].get('valid_native_receipt')]
                result['native_ART_qualification'] = {
                    'flash_counters': flash_art,
                    'fire_recovery_counters': recovery_art,
                    'reload_hand_counters_with_model_and_body_receipt': hand_art,
                    'valid_body_receipt_serials': sorted(body_receipt_serials),
                }
                checks.update(
                    animation_MD3_declares_all_native_frame_names=result['animation_model']['all_required_names_present'],
                    native_firing_retains_ART_and_has_no_model=bool(recovery_art) and
                        not any(1 <= row[1] <= 5 for row in samples),
                    observed_native_reloading_model_counter_6_to_26=bool(reloading),
                    observed_native_early_reload_body_2528=any(7 <= row[1] <= 9 for row in reloading),
                    observed_native_final_reload_body_2529=any(25 <= row[1] <= 26 for row in reloading),
                    observed_native_reload_magazine_roles_1_and_2=bool(magazine),
                    naturally_observed_model_frames_pass_SPS_color_depth_oracles=bool(counter_checks) and
                        all(all(value for key, value in check.items() if key not in ('receipt_roles',))
                            for check in counter_checks.values()),
                    observed_native_flash_ART_counter_1_or_2=bool(flash_art),
                    observed_native_reload_hand_ART_counter_20_to_24_with_model_body_receipt=bool(hand_art),
                )
                if args.missing_reload_frame is not None:
                    missing = args.missing_reload_frame
                    later = [row for row in reloading if row[1] > missing and
                             counter_checks[row[1]].get('valid_native_receipt')]
                    checks.update(
                        missing_reload_fixture_mutates_only_name=result['missing_reload_fixture']['only_chosen_frame_name_bytes_changed'] and
                            result['missing_reload_fixture']['payload_unchanged'],
                        native_missing_reload_counter_observed=any(row['counter'] == missing and row['reloading'] == 1
                            for row in result['reload']['rows']),
                        missing_reload_counter_retains_native_ART=bool(native_art.get(missing)),
                        missing_reload_counter_emits_no_model_sample=not any(row[1] == missing for row in samples),
                        later_reload_model_frames_and_receipts_survive=bool(later),
                    )
        else:
            checks.update(no_MD3_receipt=not AA_RECEIPT.search(text),
                          no_MD3_capture=not (root / 'model-after-left.ppm').exists(),
                          native_ART_body_visible=result['weapon_card']['available'] and result['weapon_card']['coverage'])
            if args.case == 'missing-frame':
                checks['missing_rest_fixture_only_changed_frame_name'] = \
                    result['missing_frame_fixture']['only_frame_name_bytes_changed']
        if args.mask_oracle:
            mask = result['mask_oracle']
            checks.update(mask['checks'])
            if mask['world_counters'] is not None:
                checks['SPS_MASK_warm_world_and_MASK_multiview'] = (
                    mask['world_counters']['masks_multiview'] > 0 and
                    mask['world_counters']['full_multiview'] > 0)
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
    if model_case or args.case == 'missing-frame':
        inputs.extend((args.model, args.skin))
    result['sha256'] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
