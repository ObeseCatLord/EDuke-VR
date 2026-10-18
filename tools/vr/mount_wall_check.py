#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Same-frame wall contact and recovery from real private OpenXR frames."""
import math
from pathlib import Path
import re

import numpy as np
from PIL import Image

from floating_hands_check import STATES, _project
from pistol_mount_check import tags
from smoke_crosshair import raster
from smoke_weapon import rotation


def inspect(root, text, model, side):
    points=tags(model); selected=int(side=='right'); rows=[]
    submitted={int(s) for s in re.findall(r'OpenXR mount submitted: serial=(\d+)\.',text)}
    for block in text.split('OpenXR floating hands:')[1:]:
        header=re.match(r' serial=(\d+) state=(\d+) mask=(\d+) left=\d+ right=\d+ capture=(\d+)\.',block)
        if not header: continue
        serial,state,mask,captured=map(int,header.groups())
        if not captured or state not in (5,6,10): continue
        def numbers(pattern):
            found=re.search(pattern,block)
            if not found: raise RuntimeError(f'wall capture {serial} missing {pattern}')
            return [np.fromstring(s,sep=',') for s in found.groups()]
        body,clamped=numbers(r'OpenXR pistol mount render: serial='+str(serial)+r' hand=\d body=([^ ]+) clamped=(\d+)\.')
        resolved,correction,origin,tracking,yaw,local=numbers(
            r'OpenXR mount collision: serial='+str(serial)+r' root=([^ ]+) correction=([^ ]+) origin=([^ ]+) tracking=([^ ]+) yaw=([^ ]+) local=([^\n]+)\.')
        grip,aim=numbers(r'OpenXR pistol mount pose: eye=0 hand=\d grip=([^ ]+) aim=([^\n]+)\.')
        handroot,pivot,handpose=numbers(r'OpenXR floating hand: serial='+str(serial)+r' hand='+str(selected)+
                                     r' model=\d+ frame=\d+ root=([^ ]+) pivot=([^ ]+) pose=([^\n]+)\.')
        co,si=math.cos(yaw[0]),math.sin(yaw[0])
        to_build=np.array(((0,0,-co),(co,0,-si),(0,-16,0)),float)
        to_build[0,0]=-si
        to_build=384*to_build@rotation(tracking)
        to_local=np.linalg.inv(to_build)
        palm=points['tag_palm_'+side]
        d=points['tag_muzzle']-palm
        raw_muzzle=grip+rotation(aim)@np.array((d[1],d[2],-d[0]))/64
        # Round independently at the Build boundary. The observed correction
        # is the resolver's output; it is not used to define contact itself.
        desired=body[:3]+np.rint(to_build@(raw_muzzle-origin))
        expected_hand=body[:3]+np.rint(to_build@(grip-origin))+correction
        local_delta=to_local@correction
        start_hit=numbers(r'OpenXR world crosshair: start=([^ ]+) hit=([^ ]+) sector=')[0:2]
        hit_sector,hit_wall,hit_sprite=numbers(r'OpenXR world crosshair:.*? sector=(-?\d+) wall=(-?\d+) sprite=(-?\d+) ')
        replay=numbers(r'OpenXR floating replay: serial='+str(serial)+r' instances=(\d+) paired=(\d+) eyeOnly=(\d+) shared=(\d+) vertices=(\d+)\.')
        instances,paired,eye_only,shared,vertices=(int(v[0]) for v in replay)
        hitpoint=numbers(r'OpenXR world crosshair:.*? point=([^\n]+)\.')[0]
        anchor=numbers(r'OpenXR crosshair anchor: pixel=([^\n]+)\.')[0]
        prefix=root/f'hands-state-{state:02d}'
        crossprefix=Path(str(prefix)+'-crosshair')
        ui=np.asarray(Image.open(str(crossprefix)+'-ui.ppm'))
        alpha=np.asarray(Image.open(str(crossprefix)+'-coverage.pgm'))
        contact=[]; corrected_errors=[]; uncorrected_errors=[]; cross_errors=[]; cross_projection=[]
        cross_pixels=[]; depth=[]; contribution=[]
        for eye,name in enumerate(('left','right')):
            weapon=numbers(r'OpenXR hand model matrix: eye='+str(eye)+r' values=([^\n]+)\.')[0].reshape(4,4,order='F')
            hand=numbers(r'OpenXR floating matrix: serial='+str(serial)+r' hand='+str(selected)+r' eye='+str(eye)+r' values=([^\n]+)\.')[0].reshape(4,4,order='F')
            projection=numbers(r'OpenXR floating projection: serial='+str(serial)+r' eye='+str(eye)+r' values=([^\n]+)\.')[0].reshape(4,4,order='F')
            view,fov=numbers(r'OpenXR floating eye: serial='+str(serial)+r' eye='+str(eye)+r' pose=([^ ]+) fov=([^\n]+)\.')
            relative=np.linalg.solve(hand,weapon)@np.r_[palm,1]
            contact.append(float(np.linalg.norm(relative[:3]-pivot)*1000/64))
            for matrix,tag,raw in ((weapon,palm,grip),(weapon,points['tag_muzzle'],raw_muzzle),(hand,pivot,grip)):
                clip=projection@matrix@np.r_[tag,1]
                actual=clip[:2]/clip[3]
                for delta,errors in ((local_delta,corrected_errors),(np.zeros(3),uncorrected_errors)):
                    expected=_project(rotation(view[:4]).T@(raw+delta-view[4:]),fov)
                    errors.append(float(np.max(np.abs(actual-expected))))
            cross=numbers(r'OpenXR crosshair matrix: eye='+str(eye)+r' values=([^\n]+)\.')[0].reshape(4,4,order='F')
            before=np.asarray(Image.open(str(crossprefix)+f'-before-{name}.ppm'))
            after=np.asarray(Image.open(str(crossprefix)+f'-{name}.ppm'))
            depth_before=Path(str(crossprefix)+f'-before-{name}-depth.bin').read_bytes()
            z=np.flipud(np.frombuffer(depth_before,dtype=np.uint32).reshape(before.shape[:2]))/4294967295
            expected,_,_=raster(before,ui,alpha,z,cross)
            cross_errors.append(int(np.max(np.abs(expected.astype(int)-after.astype(int)))))
            cross_pixels.append(int(np.count_nonzero(np.any(before!=after,axis=2))))
            depth.append(depth_before==Path(str(crossprefix)+f'-{name}-depth.bin').read_bytes())
            clip=cross@np.array((2*anchor[0]/ui.shape[1]-1,1-2*anchor[1]/ui.shape[0],0,1))
            hit_local=origin+to_local@(hitpoint-body[:3])
            cross_projection.append(float(np.max(np.abs(clip[:2]/clip[3]-_project(rotation(view[:4]).T@(hit_local-view[4:]),fov)))))
            weapon_before=np.asarray(Image.open(str(prefix)+f'-before-{name}.ppm'))
            weapon_after=np.asarray(Image.open(str(prefix)+f'-instance-0-reference-{name}.ppm'))
            # Native order is gun, left hand, right hand. Measure the holding
            # hand's own contribution, not merely a nonempty combined image.
            preceding=0 if selected==0 else 1
            hand_before=np.asarray(Image.open(str(prefix)+f'-instance-{preceding}-reference-{name}.ppm'))
            hand_after=np.asarray(Image.open(str(prefix)+f'-instance-{selected+1}-reference-{name}.ppm'))
            contribution.append([int(np.count_nonzero(np.any(weapon_before!=weapon_after,axis=2))),
                                 int(np.count_nonzero(np.any(hand_before!=hand_after,axis=2)))])
        exact=lambda a,b:all(Path(str(prefix)+f'-{a}-{eye}{ext}').read_bytes()==Path(str(prefix)+f'-{b}-{eye}{ext}').read_bytes()
                             for eye in ('left','right') for ext in ('.ppm','-depth.bin'))
        rows.append({'serial':serial,'state':state,'submitted':serial in submitted,'clamped':bool(clamped[0]),
                     'mask':mask,'desired':desired.tolist(),'root':resolved.tolist(),'correction':correction.tolist(),
                     'root_source_error':float(np.max(np.abs(resolved-correction-desired))),
                     'hand_shared_translation_error':float(np.max(np.abs(handroot-expected_hand))),
                     'palm_separation_mm':contact,'corrected_projection_errors':corrected_errors,
                     'uncorrected_projection_errors':uncorrected_errors,'crosshair_pixel_errors':cross_errors,
                     'crosshair_projection_errors':cross_projection,'crosshair_pixels':cross_pixels,'crosshair_depth_unchanged':all(depth),
                     'same_frame_reticle_root':bool(np.array_equal(start_hit[0],resolved)),
                     'reticle_hits_blocking_wall':bool(abs(start_hit[1][0]-1550)<=1 and hit_sector[0]==0 and hit_wall[0]==1 and hit_sprite[0]==-1),
                     'model_and_holding_hand_pixels':contribution,'native_stereo_exact':exact('reference','after'),
                     'actual_model_SPS_replay':instances==3 and paired>=instances and eye_only==0 and shared==paired and vertices>0,
                     'collection_zero_writes':exact('before','collected'),
                     'resolved_LOCAL_error_m':float(np.max(np.abs(local-(origin+to_local@(resolved-body[:3])))))})
    by_state={r['state']:r for r in rows}; clamped=by_state.get(6); recovered=by_state.get(10)
    checks={
        'wall_captures_initial_clamp_and_recovery':set(by_state)=={5,6,10},
        'wall_all_captures_submitted':bool(rows) and all(r['submitted'] for r in rows),
        'wall_actual_collision_and_recovery':bool(clamped and recovered) and not by_state[5]['clamped'] and clamped['clamped'] and not recovered['clamped'] and
            np.linalg.norm(clamped['correction'])>32 and recovered['correction']==[0,0,0],
        'wall_raw_pose_reconstructs_requested_muzzle':bool(rows) and all(r['root_source_error']<=1 for r in rows),
        'wall_holding_palm_receives_same_collision_translation':bool(rows) and all(r['hand_shared_translation_error']<=1 for r in rows),
        'wall_contact_stays_within_3mm_both_eyes':bool(rows) and all(max(r['palm_separation_mm'])<=3 for r in rows),
        'wall_corrected_gun_and_palm_projection_matches':bool(rows) and all(max(r['corrected_projection_errors'])<.008 for r in rows),
        # A correction roughly along the sight ray can leave the muzzle's 2D
        # projection almost unchanged. The gun palm and holding palm must each
        # distinguish the missing translation in both eyes.
        'wall_uncorrected_gun_and_palm_negative_control_rejected':bool(clamped) and min(clamped['uncorrected_projection_errors'][i] for i in (0,2,3,5))>.008,
        'wall_gun_and_holding_hand_visible_both_eyes':bool(rows) and all(r['mask']==3 and min(min(v) for v in r['model_and_holding_hand_pixels'])>0 for r in rows),
        'wall_models_match_native_stereo_without_collection_writes':bool(rows) and all(r['native_stereo_exact'] and r['collection_zero_writes'] for r in rows),
        'wall_each_captured_frame_has_shared_model_SPS_replay':bool(rows) and all(r['actual_model_SPS_replay'] for r in rows),
        'wall_reticle_uses_same_resolved_root_and_wall':bool(rows) and all(r['same_frame_reticle_root'] and r['reticle_hits_blocking_wall'] for r in rows),
        'wall_reticle_pixels_and_depth_match_projection':bool(rows) and all(max(r['crosshair_pixel_errors'])<=2 and r['crosshair_depth_unchanged'] and min(r['crosshair_pixels'])>0 for r in rows),
        'wall_reticle_physical_projection_matches':bool(rows) and all(max(r['crosshair_projection_errors'])<.008 for r in rows),
        'wall_resolved_LOCAL_conversion_matches':bool(rows) and all(r['resolved_LOCAL_error_m']<2e-5 for r in rows),
    }
    return {'checks':{name:bool(value) for name,value in checks.items()},'frames':rows}


def exercise(observer, remote, root, model, side):
    selected=getattr(remote.packet,side); initial_z=selected.pose.position.z
    def wait_state(state,start=0):
        def ready(text):
            rows=[tuple(map(int,row)) for row in STATES.findall(text[start:])]
            serial=next((r[0] for r in rows if r[1]==state and r[5]),None)
            return serial is not None and f'OpenXR mount submitted: serial={serial}.' in text and bool(re.search(
                r'OpenXR crosshair capture: world=\d+ serial='+str(serial)+r'\.',text))
        observer.wait(ready,timeout=15)
    try:
        wait_state(5)
        start=len(observer.text());selected.pose.position.z=-1.35
        remote.packet.left.squeeze_value=1;remote.send();wait_state(6,start)
        start=len(observer.text());selected.pose.position.z=initial_z
        remote.packet.right.squeeze_value=1;remote.send();wait_state(10,start)
        return inspect(root,observer.text(),model,side)
    finally:
        selected.pose.position.z=initial_z
        for hand in (remote.packet.left,remote.packet.right):
            hand.squeeze_value=0;hand.trigger_value=0;hand.trigger_click=False
        remote.send()
