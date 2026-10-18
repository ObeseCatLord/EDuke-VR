#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Private asset and native-CON fault controls for the AA RPG adapter."""
import hashlib
from pathlib import Path
import re
import struct
import time

from smoke_actions import traces
from smoke_aim import orientation
from smoke_multiplayer import X11


def remove_palm_tag(root: Path, model: Path, side: str) -> dict:
    """Rename only the selected calibration tag, in every private MD3 frame."""
    if side not in ('left', 'right'):
        raise ValueError('invalid palm side')
    original = model.read_bytes()
    if original[:4] != b'IDP3' or len(original) < 108:
        raise ValueError('invalid MD3 header')
    frames, count = struct.unpack_from('<2i', original, 76)
    start = struct.unpack_from('<i', original, 96)[0]
    if frames <= 0 or count <= 0 or start < 108 or start + frames * count * 112 > len(original):
        raise ValueError('invalid MD3 tag table')
    target = ('tag_palm_' + side).encode()
    changed = bytearray(original)
    ranges = []
    for frame in range(frames):
        matches = [start + (frame * count + tag) * 112 for tag in range(count)
                   if original[start + (frame * count + tag) * 112: start + (frame * count + tag) * 112 + 64]
                   .split(b'\0', 1)[0] == target]
        if len(matches) != 1:
            raise ValueError('expected exactly one selected palm tag per frame')
        offset = matches[0]
        changed[offset:offset + 64] = ('absent_palm_' + side).encode().ljust(64, b'\0')
        ranges.append((offset, offset + 64))
    differences = [i for i, (a, b) in enumerate(zip(original, changed)) if a != b]
    only_names = bool(differences) and all(any(lo <= i < hi for lo, hi in ranges) for i in differences)
    if not only_names:
        raise RuntimeError('private fixture changed bytes outside selected tag names')
    path = root / ('rpg_missing_' + side + '_palm.md3')
    path.write_bytes(changed)
    return {'path': str(path), 'side': side, 'frames': frames, 'renamed_tag_records': len(ranges),
            'only_selected_tag_names_changed': only_names, 'changed_bytes': len(differences),
            'source_sha256': hashlib.sha256(original).hexdigest(),
            'sha256': hashlib.sha256(changed).hexdigest()}


def draw_fault_con(kind: str) -> str:
    tile = {'duplicate-body': 10228, 'wrong-tile': 2524}[kind]
    return f'''
// Test-only extra draw, armed after an accepted native RPG body.
gamevar aarpg_fault 0 1
appendevent EVENT_DRAWWEAPON
ifvare aarpg_fault 1 ife player[].curr_weapon RPG_WEAPON
{{
 guniqhudid 24
 rotatesprite16 10485760 6553600 32768 0 {tile} 0 0 4096 0 0 xdim ydim
 guniqhudid 0
 set aarpg_fault 2
 addlog aarpg_fault
}}
endevent
'''


def exercise_draw_fault(observer, process, display: str, kind: str) -> dict:
    """Require a real extra CON draw to cancel its already-written XR frame."""
    tile = {'duplicate-body': 10228, 'wrong-tile': 2524}[kind]
    start = len(observer.text())
    x11 = X11(display)
    window, _ = x11.owned_window(process.pid)
    if not window:
        raise RuntimeError('owned AA drawable missing before draw fault')
    deadline = time.monotonic() + 15
    x11.send_event_key(window, 'F4', True)
    try:
        while True:
            if process.poll() is not None:
                raise RuntimeError('owned game exited during draw fault')
            # Only this expected-cancellation path bypasses Observer's XR-stop rejection.
            text = observer.path.read_text(errors='replace')
            part = text[start:]
            if 'OpenXR world stopped:' in part:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('native draw fault/cancellation observation timeout')
            time.sleep(.05)
    finally:
        x11.send_event_key(window, 'F4', False)
    canceled = [tuple(map(int, row)) for row in re.findall(
        r'OpenXR hand model frame canceled: serial=(\d+) submitted=(\d+)\.', part)]
    mismatches = re.findall(r'OpenXR AA hand model draw mismatch: ([^\n]+)', part)
    expected = f'tile={tile} id=24 shade=0 palette=0 flags=4098 angle=0 alpha=0 blend=0 segment=1 roles=1.'
    return {'kind': kind, 'canceled': canceled, 'mismatches': mismatches, 'text': text,
            'checks': {'native_extra_CON_draw_executed': bool(re.search(r'addlog aarpg_fault[^=]*= 2', part)),
                       'extra_claimed_RPG_draw_rejected_after_valid_body': expected in mismatches,
                       'fault_written_frame_canceled_before_submission': len(canceled) == 1 and canceled[0][0] > canceled[0][1],
                       'fault_XR_shutdown_has_receipt_reason': 'held-model/native weapon receipt mismatch' in part}}


def blocked_fire(observer, remote, native_rows, side: str) -> dict:
    """Attempt real trigger input with valid aim and absent selected calibration."""
    before = native_rows(observer.text())[-1]
    hand = getattr(remote.packet, side)
    hand.pose.position.x, hand.pose.position.y, hand.pose.position.z = .2, 1.3, -.5
    hand.pose.orientation = orientation(10, 4)
    remote.send()
    settle = len(observer.text())
    observer.wait(lambda text: len(native_rows(text[settle:])) >= 4)
    start = len(observer.text())
    remote.packet.right.trigger_value, remote.packet.right.trigger_click = 1, True
    remote.send()
    try:
        held = observer.wait(lambda text: len(native_rows(text[start:])) >= 8)
        part = held[start:]
    finally:
        remote.packet.right.trigger_value, remote.packet.right.trigger_click = 0, False
        remote.send()
    release = len(observer.text())
    released = observer.wait(lambda text: len(native_rows(text[release:])) >= 4)
    after = native_rows(released)[-1]
    observed = native_rows(part)
    xr = traces(part)
    return {'before': before, 'after': after, 'held_native_rows': observed, 'held_XR_rows': xr,
            'checks': {'invalid_calibration_received_real_trigger_with_valid_aim': any(
                row['right_buttons'] & 1 and row[side + '_aim'] for row in xr),
                'invalid_calibration_observed_native_ticks': len(observed) >= 8,
                'invalid_calibration_spends_no_ammo': after['ammo'] == before['ammo'] and all(
                    row['ammo'] == before['ammo'] for row in observed),
                'invalid_calibration_has_no_counter_or_shot': before['counter'] == 0 and after['counter'] == 0
                    and after['shots'] == before['shots'] and all(row['counter'] == 0 and row['shots'] == before['shots'] for row in observed),
                'invalid_calibration_has_no_native_RPG_insertion': 'VR authoritative RPG:' not in released[start:]
                    and 'VR native projectile:' not in released[start:] and 'addlog aarpg_spawn_' not in released[start:]}}
