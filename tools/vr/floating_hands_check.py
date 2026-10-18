#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Private real-runtime checks shared by stock and AA model runners."""
import hashlib
from pathlib import Path
import re
import numpy as np
from PIL import Image
from smoke_weapon import quaternion, rotation
from monado_remote import Quat

STATES = re.compile(r'OpenXR floating hands: serial=(\d+) state=(\d+) mask=(\d+) left=(\d+) right=(\d+) capture=(\d+)\.')


def configure(root, definition, assets, env, same_model=False):
    assets = assets.resolve()
    (root / 'floating-hand-assets').symlink_to(assets, target_is_directory=True)
    inputs = {}
    with definition.open('a') as output:
        for hand, side in enumerate(('left', 'right')):
            if same_model and hand:
                continue # One loaded model object, not two loads of one file.
            source = 'right' if same_model else side
            for suffix in ('md3', 'png'):
                path = assets / f'hand_{source}.{suffix}'
                inputs[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            output.write(f'\nmodel "floating-hand-assets/hand_{source}.md3" {{\n'
                         f' skin {{ pal 0 file "floating-hand-assets/hand_{source}.png" }}\n'
                         f' frame {{ name "rest" tile {30010+hand} smoothduration 0 }}\n}}\n')
    env.update(EDUKE32_XR_HAND_LEFT_TILE='30010', EDUKE32_XR_HAND_RIGHT_TILE='30010' if same_model else '30011',
               EDUKE32_XR_TEST_HANDS='1', EDUKE32_XR_HAND_OUTPUT=str(root / 'hands'))
    return inputs


def _numbers(value):
    return np.fromstring(value, sep=',')


def _project(point, fov):
    left, right, up, down = np.tan(fov)
    x, y, z = point
    return np.array(((2*x/-z-right-left)/(right-left), (2*y/-z-up-down)/(up-down)))


def _raw_pose_projection_error(serial, hand, pivot, pose, eyes, projections, matrices):
    """Project an emitted matrix against a supplied raw grip pose.

    Passing the preceding pose is a deliberate negative control: the matrix
    was submitted for ``serial`` and therefore must not still match it after a
    sufficiently large controller move.
    """
    mapping = np.array(((0,0,1 if hand else -1),(-1,0,0),(0,-1 if hand else 1,0)))
    errors=[]
    for eye in (0,1):
        if (serial,eye) not in eyes or (serial,eye) not in projections or (serial,hand,eye) not in matrices:
            return None
        view,fov=eyes[serial,eye]
        inverse_view=rotation(view[:4]).T
        expected_root=inverse_view@(pose[4:]-view[4:])
        expected_axes=inverse_view@rotation(pose[:4])@mapping
        actual=projections[serial,eye]@matrices[serial,hand,eye]
        actual_points=[];expected_points=[]
        for offset in (np.zeros(3),np.array((3.2,0,0)),np.array((0,3.2,0)),np.array((0,0,3.2))):
            clip=actual@np.r_[pivot+offset,1]
            actual_points.append(clip[:2]/clip[3])
            expected_points.append(_project(expected_root+expected_axes@(offset/64),fov))
        errors.append(float(np.max(np.abs(np.array(actual_points)-expected_points))))
    return max(errors)


def inspect(root, text, require_prior_pose_rejection=False):
    states = [tuple(map(int, row)) for row in STATES.findall(text)]
    eyes = {(int(s), int(e)): (_numbers(p), _numbers(f)) for s,e,p,f in re.findall(
        r'OpenXR floating eye: serial=(\d+) eye=(\d+) pose=([^ ]+) fov=([^\n]+)\.', text)}
    projections = {(int(s),int(e)): _numbers(v).reshape(4,4,order='F') for s,e,v in re.findall(
        r'OpenXR floating projection: serial=(\d+) eye=(\d+) values=([^\n]+)\.', text)}
    matrices = {(int(s),int(h),int(e)): _numbers(v).reshape(4,4,order='F') for s,h,e,v in re.findall(
        r'OpenXR floating matrix: serial=(\d+) hand=(\d+) eye=(\d+) values=([^\n]+)\.', text)}
    hands = {(int(s),int(h)): (int(f),_numbers(p),_numbers(q),int(m)) for s,h,m,f,r,p,q in re.findall(
        r'OpenXR floating hand: serial=(\d+) hand=(\d+) model=(\d+) frame=(\d+) root=([^ ]+) pivot=([^ ]+) pose=([^\n]+)\.', text)}
    replays = {int(s):tuple(map(int,(n,p,e,g,v))) for s,n,p,e,g,v in re.findall(
        r'OpenXR floating replay: serial=(\d+) instances=(\d+) paired=(\d+) eyeOnly=(\d+) shared=(\d+) vertices=(\d+)\.',text)}
    results, errors, axis_errors, frame_matches, raw_poses = {}, [], [], [], []
    for serial,state,mask,left,right,captured in states:
        if not captured: continue
        prefix = root / f'hands-state-{state:02d}'
        prior = 0 if Path(str(prefix)+'-instance-0-reference-left.ppm').exists() else None
        expected_count=bool(prior is not None)+bool(mask&1)+bool(mask&2)
        detail = {'mask': mask, 'model_count': expected_count, 'hands': {}}
        # An empty set has no model collection; require no depth/color writes.
        if expected_count == 0:
            detail['empty_batch_unchanged'] = all(Path(str(prefix)+f'-before-{eye}{ext}').read_bytes() ==
                Path(str(prefix)+f'-after-{eye}{ext}').read_bytes()
                for eye in ('left','right') for ext in ('.ppm','-depth.bin'))
            results[state] = detail
            continue
        detail['native_stereo_exact'] = all(Path(str(prefix)+f'-reference-{eye}{ext}').read_bytes() ==
            Path(str(prefix)+f'-after-{eye}{ext}').read_bytes()
            for eye in ('left','right') for ext in ('.ppm','-depth.bin'))
        detail['zero_collection_writes'] = all(Path(str(prefix)+f'-before-{eye}{ext}').read_bytes() ==
            Path(str(prefix)+f'-collected-{eye}{ext}').read_bytes()
            for eye in ('left','right') for ext in ('.ppm','-depth.bin'))
        replay=replays.get(serial)
        detail['actual_SPS_replay']=bool(replay) and replay[0]==expected_count and replay[1]>=expected_count and replay[2]==0 and replay[3]==replay[1] and replay[4]>0
        for hand in (0,1):
            if not mask & (1<<hand): continue
            frame,pivot,pose,model = hands[serial,hand]
            raw_poses.append((serial,hand,pivot,pose))
            frame_matches.append(frame == (0,2,1)[left if hand==0 else right])
            # Independently apply the authored anatomical axis contract to the
            # actual OpenXR grip relative to the actual OpenXR eye. No emitted
            # world/model basis or calibration state enters expected geometry.
            mapping = np.array(((0,0,1 if hand else -1),(-1,0,0),(0,-1 if hand else 1,0)))
            changed = []
            for eye in (0,1):
                view,fov = eyes[serial,eye]
                inverse_view = rotation(view[:4]).T
                expected_root = inverse_view @ (pose[4:]-view[4:])
                expected_axes = inverse_view @ rotation(pose[:4]) @ mapping
                actual = projections[serial,eye] @ matrices[serial,hand,eye]
                actual_points, expected_points = [], []
                for offset in (np.zeros(3), np.array((3.2,0,0)),np.array((0,3.2,0)),np.array((0,0,3.2))):
                    clip = actual @ np.r_[pivot+offset,1]
                    actual_points.append(clip[:2]/clip[3])
                    expected_points.append(_project(expected_root + expected_axes @ (offset/64),fov))
                errors.append(float(np.max(np.abs(np.array(actual_points)-expected_points))))
                # Subtract projected pivots to reduce common translation
                # error from eye/root Build rounding (~2.6 mm). Depth rounding
                # still leaves a small bounded differential projection error.
                axis_errors.append(float(np.max(np.abs((np.array(actual_points)[1:]-actual_points[0])-
                                                        (np.array(expected_points)[1:]-expected_points[0])))))
                name = ('left','right')[eye]
                before = str(prefix)+(f'-instance-{prior}-reference-{name}.ppm' if prior is not None else f'-before-{name}.ppm')
                after = str(prefix)+f'-instance-{hand+1}-reference-{name}.ppm'
                changed.append(int(np.count_nonzero(np.any(np.asarray(Image.open(before)) != np.asarray(Image.open(after)),axis=2))))
            detail['hands'][hand] = {'changed_pixels': changed, 'visible_both_eyes': min(changed)>0, 'frame': frame, 'model': model}
            prior = hand+1
        results[state] = detail
    prior_by_hand={}; prior_rejections=[]
    for serial,hand,pivot,pose in sorted(raw_poses):
        prior=prior_by_hand.get(hand)
        if prior is not None:
            prior_serial,prior_pose=prior
            moved=np.linalg.norm(pose[4:]-prior_pose[4:])>.03
            turned=np.max(np.abs(rotation(pose[:4])-rotation(prior_pose[:4])))>.04
            if moved or turned:
                current_error=_raw_pose_projection_error(serial,hand,pivot,pose,eyes,projections,matrices)
                prior_error=_raw_pose_projection_error(serial,hand,pivot,prior_pose,eyes,projections,matrices)
                if current_error is not None and prior_error is not None:
                    prior_rejections.append({'serial':serial,'hand':hand,'previous_serial':prior_serial,
                                             'translation_m':float(np.linalg.norm(pose[4:]-prior_pose[4:])),
                                             'current_pose_projection_error':current_error,
                                             'previous_pose_projection_error':prior_error})
        prior_by_hand[hand]=(serial,pose)
    checks = {
        'both_grips_rendered': any(row[2]==3 and row[5] for row in states),
        'all_captured_grip_frames_match_button_geometry': bool(frame_matches) and all(frame_matches),
        'all_grip_native_stereo_exact': bool(results) and all(row.get('native_stereo_exact',row.get('empty_batch_unchanged',False)) for row in results.values()),
        'all_grip_collection_writes_zero': bool(results) and all(row.get('zero_collection_writes',row.get('empty_batch_unchanged',False)) for row in results.values()),
        'each_nonempty_grip_batch_has_actual_SPS_replay': any(row['model_count'] for row in results.values()) and all(row['actual_SPS_replay'] for row in results.values() if row['model_count']),
        'each_present_hand_contributes_both_eyes': any(row['hands'] for row in results.values()) and all(h['visible_both_eyes'] for row in results.values() for h in row['hands'].values()),
        # These are fixed before running: <one cm in the prescribed ~0.5m
        # fixture; axis delta is much stricter, detecting scale/handedness.
        'raw_grip_to_eye_projection_matches': bool(errors) and max(errors)<.008,
        'raw_grip_axis_projection_matches': bool(axis_errors) and max(axis_errors)<.0015,
    }
    if require_prior_pose_rejection:
        checks['raw_grip_prior_pose_rejected_by_absolute_projection']=bool(prior_rejections) and all(
            row['current_pose_projection_error']<.008 and row['previous_pose_projection_error']>.008
            for row in prior_rejections)
    return {'checks':checks, 'states':states, 'captures':results, 'projection_errors':errors,
            'axis_errors':axis_errors, 'prior_pose_rejections':prior_rejections}


def exercise(observer, remote, root, mount_motion=False, selected_hand='right'):
    def state_after(state, start=0, require_capture=False):
        def ready(text):
            rows=[tuple(map(int,row)) for row in STATES.findall(text[start:])]
            match=next((row for row in rows if row[1]==state and (not require_capture or row[5])),None)
            if not match:return False
            serial,_,mask,_,_,captured=match
            if not captured:return True
            if not (root/f'hands-state-{state:02d}-after-right.ppm').is_file():return False
            return mask==0 or bool(re.search(r'OpenXR floating matrix: serial='+str(serial)+r' hand=\d eye=1',text))
        return observer.wait(ready,timeout=12)
    state_after(5, require_capture=True)
    for side in (remote.packet.left,remote.packet.right):
        side.trigger_value=0;side.trigger_click=False;side.squeeze_value=0;side.active=True
    remote.send();observer.pause(.3)
    transitions=[]
    def change(state, callback):
        start=len(observer.text());callback();remote.send();state_after(state,start);transitions.append(state)
    selected=getattr(remote.packet,selected_hand)
    movement=remote.packet.left.thumbstick
    def pose_and_button(state):
        if mount_motion:
            direction=1 if selected_hand=='right' else -1
            selected.pose.position.x=direction*(.18 if state==6 else .06)
            selected.pose.orientation=Quat(*quaternion(12,8,70 if state==6 else -35))
            # Keep native locomotion active while each changed controller pose
            # is captured.  The mount oracle consumes the render-frame body
            # diagnostic, never a guessed tic count.
            movement.y=.65
        setattr(remote.packet.left,'squeeze_value' if state==6 else 'trigger_value',1)
    try:
        change(6,lambda:pose_and_button(6))
        if mount_motion: observer.pause(.15)
        change(7,lambda:pose_and_button(7))
        if mount_motion:
            # Captures 6 and 7 already include simultaneous locomotion. Stop
            # before further image readbacks so a slow CPU lab cannot carry
            # the fixture across the room and turn a loss test into occlusion.
            movement.y=0; remote.send(); observer.pause(.1)
        change(6,lambda:setattr(remote.packet.left,'trigger_value',0))
        change(5,lambda:setattr(remote.packet.left,'squeeze_value',0))
        change(9,lambda:setattr(remote.packet.right,'squeeze_value',1))
        if mount_motion:
            # Keep subsequent button/loss fixtures stationary.
            movement.y=0; remote.send()
        change(5,lambda:setattr(remote.packet.right,'squeeze_value',0))
        if mount_motion:
            # Actual remote poses at ~100 Hz, with no native-tick override.
            # Bounded transform records establish whether the renderer follows
            # more than one acquired pose within an observed unchanged tic.
            direction=1 if selected_hand=='right' else -1
            for step in range(60):
                selected.pose.position.x=direction*(.06+.0015*(step if step<30 else 60-step))
                remote.send(); observer.pause(.01)
        change(4,lambda:setattr(remote.packet.left,'active',False))
        change(5,lambda:setattr(remote.packet.left,'active',True))
        change(1,lambda:setattr(remote.packet.right,'active',False))
        change(0,lambda:setattr(remote.packet.left,'active',False))
        change(1,lambda:setattr(remote.packet.left,'active',True))
        change(5,lambda:setattr(remote.packet.right,'active',True))
        observer.pause(.3)
        result=inspect(root,observer.text(),require_prior_pose_rejection=mount_motion)
    finally:
        # A timeout must never leave the disposable runtime walking or either
        # controller firing when the caller proceeds to another evidence step.
        for side in (remote.packet.left,remote.packet.right):
            side.trigger_value=0;side.trigger_click=False;side.squeeze_value=0;side.active=True
        movement.y=0
        remote.send()
    result['checks']['both_hands_lose_and_recover_independently']=transitions[-6:]==[4,5,1,0,1,5]
    result['transitions']=transitions
    return result
