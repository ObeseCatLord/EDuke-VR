#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Qualify the native idle-pistol MD3 adapter through real private XR/MP frames.

Run inside software_xr_lab.py. This never changes installed assets or the user's
runtime. Art-only exports and sequential-eye models do not prove model SPS.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import time

import numpy as np
from PIL import Image
from monado_remote import Quat, Remote
from smoke_actions import Observer
from smoke_actions_multiplayer import wait_for_join_barrier
from smoke_aim import orientation, players
from smoke_hand_shots import room
from smoke_hitscan import rays
from smoke_multiplayer import X11, setup_lab, stop
from smoke_weapon import quaternion, rotation


def pistol_states(text, player):
    rows, row = [], {}
    for key, value in re.findall(r'addlog vrpistol_(player|counter|reloading|ammo|weapon)(?: \(player \d+\))? = (-?\d+)', text):
        if key == 'player': row = {}
        row[key] = int(value)
        if key == 'weapon' and len(row) == 5 and row['player'] == player:
            rows.append(row)
    return rows


def completed_reload(text, player):
    rows = pistol_states(text, player)
    for i, row in enumerate(rows):
        if row['counter'] >= 5 and row['reloading'] == 1 and row['ammo'] == 12:
            return any(s['counter'] == 0 and s['reloading'] == 0 and s['ammo'] == 12
                       and s['weapon'] == 1 for s in rows[i+1:])
    return False


def world_from_eye(yaw, pitch, roll):
    """Map OpenXR eye axes to physical Build-world X/Y/Z-up axes."""
    forward = np.array((math.cos(yaw)*math.cos(pitch), math.sin(yaw)*math.cos(pitch), math.sin(pitch)))
    right = np.array((-math.sin(yaw), math.cos(yaw), 0.))
    up = np.cross(forward, right)
    right = right*math.cos(roll) + up*math.sin(roll)
    up = np.cross(forward, right)
    return np.column_stack((right, up, -forward))


def physical_from_build(point, eye):
    """Convert a Build-world displacement into metres, with Z increasing up."""
    return (np.asarray(point, dtype=float) - np.asarray(eye, dtype=float))*np.array((1/384, 1/384, -1/6144))


def expected_projection(world_eye, eye, point, fov):
    """Project a physical world point through the native logged eye basis."""
    horizontal, vertical, back = world_eye.T @ physical_from_build(point, eye)
    distance = -back
    left, right, top, bottom = np.tan(fov)
    return np.array(((2*horizontal/distance-right-left)/(right-left),
                     (2*vertical/distance-top-bottom)/(top-bottom)))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('binary','client-binary','grp','model-root','work-dir'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--display',default=':105')
    p.add_argument('--remote-port',type=int,default=49777)
    p.add_argument('--port',type=int,default=24610)
    p.add_argument('--model-mode',choices=('native','sps'),default='native',help='retain the native two-eye reference or require model multiview')
    p.add_argument('--vertex-mode',choices=('arrays','immediate'),default='arrays')
    p.add_argument('--model-file',type=Path,help='private native multi-surface fixture, retaining pistol geometry/tags')
    p.add_argument('--fault',choices=('collect-right','surface-1','skin-last','replay-before','replay-after','mask-retry'))
    p.add_argument('--case',choices=('base','roll','fog','asymmetric','translucent','missing-skin','custom','second-eye-failure'),default='base')
    p.add_argument('--animation',action='store_true',help='Actual native MP shot/clip reload and per-counter stereo model oracles')
    p.add_argument('--late-field',action='store_true',help='Native DISPLAYEND field mutation after completed weapon pixels')
    p.add_argument('--last-shot',action='store_true',help='Native final pistol round and automatic weapon switch')
    p.add_argument('--receipt-fault',choices=('invalid-aux','duplicate','nested-swap'),help='Reject a completed model with a native weapon receipt/ownership fault')
    p.add_argument('--animation-fallback',choices=('missing-frames','nonstock'),help='Prove native animated ART when a model frame or stock timing is unavailable')
    a=p.parse_args()
    if a.animation_fallback and not a.animation:p.error('--animation-fallback requires --animation')
    if a.receipt_fault and (a.animation or a.fault):p.error('--receipt-fault is a separate cancellation case')
    if a.late_field and not a.animation:p.error('--late-field requires --animation')
    if a.last_shot and a.animation:p.error('--last-shot and --animation are separate native cases')
    if a.animation and (a.case!='base' or a.fault or a.model_mode!='sps'):
        p.error('--animation requires the base SPS case without a collection fault')
    a.work_dir.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='hand-model-',dir=a.work_dir.resolve()))
    server=client=None;logs=[];phase='setup';result={'passed':False}
    try:
        sl=setup_lab(root,'server',a.grp.resolve(),False)
        cl=setup_lab(root,'client',a.grp.resolve(),False)
        for lab in (sl,cl):
            for name in ('controller_test.con','aim_test.con','hand_test.con','hitscan_test.con'):
                shutil.copyfile(Path(__file__).parent/'fixtures'/name,lab/name)
            if a.case=='custom':
                with (lab/'hitscan_test.con').open('a') as f:
                    f.write('\nonevent EVENT_DISPLAYWEAPON\n setvar RETURN 0\nendevent\n')
            if a.animation or a.last_shot:
                fixture=lab/'hitscan_test.con'
                script=fixture.read_text().replace('.ammo_amount vrscan_weapon 80','.ammo_amount vrscan_weapon '+('1' if a.last_shot else '13'))
                script+='\n'+''.join(f'gamevar vrpistol_{key} 0 1\n' for key in ('player','counter','reloading','ammo','weapon'))
                script+='onevent EVENT_PROCESSINPUT\n    getactor[THISACTOR].yvel vrpistol_player\n'
                for field,key in (('kickback_pic','counter'),('reloading','reloading'),('ammo_amount PISTOL_WEAPON','ammo'),('curr_weapon','weapon')):
                    script+=f'    getplayer[THISACTOR].{field} vrpistol_{key}\n'
                script+=''.join(f'    addlog vrpistol_{key}\n' for key in ('player','counter','reloading','ammo','weapon'))+'endevent\n'
                if a.animation_fallback=='nonstock':
                    script+='onevent EVENT_PROCESSINPUT\n setvar WEAPON1_FIREDELAY 3\nendevent\n'
                if a.late_field:
                    script+='gamevar vrpistol_late 0 524289\ngamevar vrpistol_latecounter 0 524289\n'
                    script+='onevent EVENT_DISPLAYEND\n addvar vrpistol_latecounter 1\n'
                    script+=' ifvare vrpistol_latecounter 60\n'
                    script+=' { setactor[THISACTOR].shade 1 setvar vrpistol_late 1 addlog vrpistol_late }\nendevent\n'
                fixture.write_text(script)
                with (lab/'autoexec.cfg').open('a') as f:f.write('r_maxfps 120\n')
            data=bytearray(room())
            if a.case=='fog':
                # The constrained hand crosses into sector1 while the player
                # remains in sector0. Exercise the native model-sector fog
                # boundary instead of inheriting an opaque room's final wall.
                data[64+32]=128
                data[64+29]=1
            if a.case=='translucent':
                # An actual native translucent portal wall in front of the
                # entire held model, without a native hitscan-block flag.
                for index in (1,2,4,7):struct.pack_into('<i',data,104+index*32,1100)
                for index in (1,7):
                    struct.pack_into('<H',data,104+index*32+14,16|128)
                    struct.pack_into('<h',data,104+index*32+18,30001)
                (lab/'tiles099.art').write_bytes(struct.pack('<4i',1,1,30001,30001)+struct.pack('<hh',16,16)+bytes(4)+bytes([196])*256)
            (lab/'hand.map').write_bytes(data)
        (cl/'duke_assets').symlink_to(a.model_root.resolve()/'duke_assets',target_is_directory=True)
        skin='missing.png' if a.case=='missing-skin' else 'pistol.png'
        model_file=a.model_file.resolve() if a.model_file else a.model_root.resolve()/'duke_assets/pistol.md3'
        (cl/'held-pistol.md3').symlink_to(model_file)
        surfaces=struct.unpack_from('<i',model_file.read_bytes(),84)[0]
        (cl/'hand-model.def').write_text('model "held-pistol.md3" {\n'
            ' scale 0.5859375\n'+''.join(f' skin {{ pal 0 surface {index} file "duke_assets/{skin}" }}\n' for index in range(surfaces))+
            ' frame { name "rest" tile 21 smoothduration 0 }\n}\n')
        if a.vertex_mode=='immediate':
            with (cl/'autoexec.cfg').open('a') as f:f.write('r_vertexarrays 0\n')
        env={k:v for k,v in os.environ.items() if not k.startswith('EDUKE32_XR')}
        env.update(DISPLAY=a.display,SDL_VIDEODRIVER='x11',SDL_AUDIODRIVER='dummy')
        se={k:v for k,v in env.items() if not k.startswith('XR_')}
        se['EDUKE32_XR_TEST_SHOTS']='1'
        ce=dict(env,EDUKE32_XR='1',EDUKE32_XR_UI='2',EDUKE32_XR_SINGLE_PASS='1',
            EDUKE32_XR_AIM='right',EDUKE32_XR_WEAPON='1',EDUKE32_XR_HAND_SHOTS='1',
            EDUKE32_XR_MODELS='1',EDUKE32_XR_TEST_MODELS='1',EDUKE32_XR_TEST_INPUT='1',
            EDUKE32_XR_TEST_AIM='1',EDUKE32_XR_TEST_SHOTS='1',
            EDUKE32_XR_MODEL_OUTPUT=str(cl/'model'),EDUKE32_XR_WORLD_OUTPUT=str(cl/'world'),
            EDUKE32_XR_HUD_OUTPUT=str(cl/'hud'),EDUKE32_XR_WEAPON_OUTPUT=str(cl/'weapon'),
            EDUKE32_XR_CROSSHAIR_OUTPUT=str(cl/'crosshair'))
        if a.animation:ce['EDUKE32_XR_TEST_MODEL_ANIMATION']='1'
        if a.model_mode=='native':ce['EDUKE32_XR_TEST_MODELS_TWO_PASS']='1'
        if a.fault:ce['EDUKE32_XR_TEST_FAIL']='model-'+a.fault
        if a.fault=='mask-retry':
            ce.update(EDUKE32_XR_TEST_FAIL='mask-collect-right',EDUKE32_XR_TEST_MASK_WITH_MODEL='1')
        if a.case=='second-eye-failure':ce['EDUKE32_XR_TEST_FAIL']='model-eye-1'
        if a.receipt_fault=='nested-swap':ce['EDUKE32_XR_TEST_WEAPON_NESTED']='2'
        elif a.receipt_fault:ce['EDUKE32_XR_TEST_RECEIPT']=a.receipt_fault
        log=(sl/'server.log').open('w');logs.append(log)
        server=subprocess.Popen([str(a.binary.resolve()),'-usecwd','-nosetup','-noautoload',
            '-dedicated','-port',str(a.port),'-map','hand.map','-x','hitscan_test.con'],
            cwd=sl,env=se,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        so=Observer(server,sl/'server.log')
        so.wait(lambda t:'Multiplayer server initialized.' in t)
        with Remote(a.remote_port) as remote:
            hand=remote.packet.right
            hand.pose.position.x=.12;hand.pose.position.y=1.5;hand.pose.position.z=-.65
            roll=25 if a.case=='roll' else 0
            hand.pose.orientation=Quat(*quaternion(12,8,roll))
            remote.packet.head.center.orientation=orientation(-12,4)
            if a.case=='asymmetric':
                # Monado r_head_data views are relative to head.center.
                # These are real runtime-supplied located views, not client
                # substitution of synthetic projection-layer poses.
                remote.packet.head.per_view_data_valid=True
                for index,view in enumerate(remote.packet.head.views):
                    view.pose.orientation=Quat(0,0,0,1)
                    view.pose.position.x=.032 if index else -.032
                    view.pose.position.y=view.pose.position.z=0
                    view.fov.angle_left=-.68 if index else -.75
                    view.fov.angle_right=.65 if index else .8
                    view.fov.angle_up=.6 if index else .7
                    view.fov.angle_down=-.62 if index else -.72
            remote.send()
            log=(cl/'client.log').open('w');logs.append(log)
            client=subprocess.Popen([str(a.client_binary.resolve()),'-usecwd','-nosetup','-noautoload',
                '-nologo','-ns','-nm','-connect',f'127.0.0.1:{a.port}','-x','hitscan_test.con',
                '-h','hand-model.def'],cwd=cl,env=ce,stdin=subprocess.DEVNULL,
                stdout=log,stderr=subprocess.STDOUT)
            co=Observer(client,cl/'client.log');phase='native join'
            player=wait_for_join_barrier(X11(a.display),client,cl/'client.log',so)['server_player']
            so.wait(lambda t:len(players(t,player))>20)
            phase='actual model frames'
            if a.case=='second-eye-failure' or a.fault=='replay-after' or a.receipt_fault:
                expected_failure='held-model/native weapon receipt mismatch' if a.receipt_fault else 'model replay failed after submission' if a.fault else 'injected held-model failure before second eye'
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    text=(cl/'client.log').read_text(errors='replace')
                    if expected_failure in text:break
                    if client.poll() is not None:raise RuntimeError('owned game exited before injected failure')
                    time.sleep(.05)
                canceled=re.findall(r'OpenXR hand model frame canceled: serial=(\d+) submitted=(\d+)\.',text)
                checks={'injected_model_failure_cancels_XR':expected_failure in text,
                        'partially_drawn_frame_never_submitted':bool(canceled) and int(canceled[-1][0])>int(canceled[-1][1]),
                        'expected_emission_before_failure':('OpenXR hand model:' in text) if a.receipt_fault else ('OpenXR hand model:' not in text),
                        'no_sixty_frame_model_submission':'OpenXR world oracle: 60 frames' not in text,
                        'native_game_remains_running':client.poll() is None}
                details={}
            else:
                co.wait(lambda t:'OpenXR world oracle: 60 frames' in t and 'OpenXR HUD presentation: 60 frames' in t,timeout=25)
                text=co.text()
                fallback=a.case in ('missing-skin','custom')
                checks={'sixty_world_and_HUD_submissions':'OpenXR world oracle: 60 frames' in text,
                    'core_validation_active':'Core Validation output type:' in text,
                    'core_validation_clean':not re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)',text)}
                checks['requested_native_vertex_path_observed']=f'OpenXR MD3 emission path: arrays={int(a.vertex_mode=="arrays")}.' in text
                if a.case=='asymmetric':
                    observed=[np.fromstring(re.findall(r'OpenXR weapon view: eye='+str(i)+r'.*? fov=([^\n]+)\.',text)[-1],sep=',') for i in (0,1)]
                    checks['runtime_asymmetric_FOVs_observed']=max(float(np.abs(v-np.array(expected)).max()) for v,expected in zip(observed,[[-.75,.8,.7,-.72],[-.68,.65,.6,-.62]]))<1e-6
                counts=re.findall(r'full multiview=(\d+); hand models twoPass=(\d+)',text)
                mv=re.findall(r'hand models twoPass=\d+ multiview=(\d+)',text)
                checks['expected_model_submission_mode']=bool(counts) and (int(counts[-1][1])==0 if fallback or a.model_mode=='sps' else int(counts[-1][1])>0 and sum(map(int,counts[-1]))<=60)
                if a.model_mode=='sps' and not fallback:
                    checks['actual_model_multiview_frames']=bool(mv) and int(mv[-1])>0
                    if a.fault and a.fault!='mask-retry':
                        checks['rejected_model_uses_one_native_retry']=int(counts[-1][1])==1 and ('injected model-'+a.fault in text or a.fault=='skin-last' and 'missing required model skin' in text)
                        checks['expected_model_submission_mode']=True
                    if a.fault=='mask-retry':checks['mask_retry_after_model_observed']='injected mask-collect-right' in text
                    if not a.fault:
                        calls=re.findall(r'OpenXR hand model single-pass: paired=(\d+) eyeOnly=(\d+) shared=(\d+) sharedVertices=(\d+)\.',text)
                        checks['shared_model_geometry_submitted_once']=bool(calls) and int(calls[-1][0])>0 and int(calls[-1][1])==0 and calls[-1][0]==calls[-1][2] and int(calls[-1][3])>0
                details={}
                if fallback:
                    checks.pop('requested_native_vertex_path_observed')
                    checks['unsupported_case_retains_native_ART']='OpenXR hand model:' not in text and not (cl/'model-after-left.ppm').exists() and Image.open(cl/'weapon-coverage.pgm').getbbox() is not None
                else:
                    rows=re.findall(r'OpenXR hand model: eye=(\d) model=(\d+) root=(-?\d+),(-?\d+),(-?\d+) direction=(-?\d+),(-?\d+),(-?\d+)\.',text)
                    checks['exactly_two_eye_emissions']=len(rows)==2 and [int(r[0]) for r in rows]==[0,1]
                    checks['native_pistol_ART_pixels_suppressed']=Image.open(cl/'weapon-coverage.pgm').getbbox() is None
                    changed=[];depth_changed=[];bounds=[];translucent_changed=[];projection_errors=[];axis_errors=[]
                    matrices={int(i):np.fromstring(m,sep=',').reshape(4,4,order='F') for i,m in re.findall(r'OpenXR hand model matrix: eye=(\d) values=([^\n]+)\.',text)}
                    projections={int(i):np.fromstring(m,sep=',').reshape(4,4,order='F') for i,m in re.findall(r'OpenXR hand model projection: eye=(\d) values=([^\n]+)\.',text)}
                    # Read the actual MD3 static tag, rather than a duplicated
                    # copy of its authored position or the adapter's basis.
                    model=(a.model_root/'duke_assets/pistol.md3').read_bytes()
                    ntags=struct.unpack_from('<i',model,80)[0];offset=struct.unpack_from('<i',model,96)[0]
                    tags={model[offset+i*112:offset+i*112+64].split(b'\0')[0].decode():struct.unpack_from('<3f',model,offset+i*112+64) for i in range(ntags)}
                    eyes=np.array(list(map(int,re.findall(r'OpenXR aim eye positions: left=(-?\d+),(-?\d+),(-?\d+) right=(-?\d+),(-?\d+),(-?\d+)',text)[-1]))).reshape(2,3)
                    angles=list(map(float,re.findall(r'leftYaw=([-+\d.eE]+) leftPitch=([-+\d.eE]+) rightYaw=([-+\d.eE]+) rightPitch=([-+\d.eE]+)\.',text)[-1]))
                    eye_rolls=list(map(float,re.findall(r'OpenXR aim eye roll: left=([-+\d.eE]+) right=([-+\d.eE]+)\.',text)[-1]))
                    view_rows=re.findall(r'OpenXR weapon view: eye=(\d) pos=[^\n]*? quat=([^ ]+) fov=([^\n]+)\.',text)
                    views={int(index):(np.fromstring(quat,sep=','),np.fromstring(fov,sep=','))
                           for index,quat,fov in view_rows}
                    for eye in ('left','right'):
                        index=('left','right').index(eye)
                        before=np.array(Image.open(cl/f'model-before-{eye}.ppm'))
                        after=np.array(Image.open(cl/f'model-after-{eye}.ppm'))
                        delta=np.any(before!=after,axis=2)
                        changed.append(int(delta.sum()));bounds.append(Image.fromarray(delta).getbbox())
                        raw_before=np.frombuffer((cl/f'model-before-{eye}-depth.bin').read_bytes(),dtype=np.uint32)
                        raw_after=np.frombuffer((cl/f'model-after-{eye}-depth.bin').read_bytes(),dtype=np.uint32)
                        depth_changed.append(int(np.count_nonzero(raw_before!=raw_after)))
                        checks[f'{eye}_model_depth_is_native_nearer_surface']=bool(np.all(raw_after<=raw_before))
                        # Independent physical projection of the constrained
                        # muzzle.  Reconstruct this from logged native eye
                        # yaw/pitch/roll and the actual runtime view pose;
                        # emitted model axes and matrices remain actual-side
                        # evidence only.
                        root_position=np.array(list(map(int,rows[index][2:5])))
                        yaw,pitch=angles[index*2:index*2+2]
                        eye_world=world_from_eye(yaw,pitch,eye_rolls[index])
                        view_quaternion,fov=views[index]
                        world_tracking=eye_world@rotation(view_quaternion).T
                        expected_hand=world_tracking@rotation(quaternion(12,8,roll))
                        physical_axes=(-expected_hand[:,2],expected_hand[:,0],expected_hand[:,1])
                        expected=expected_projection(eye_world,eyes[index],root_position,fov)
                        actual=projections[index]@matrices[index]@np.array([*tags['tag_muzzle'],1])
                        projection_errors.append(float(np.abs(actual[:2]/actual[3]-expected).max()))
                        # Three five-centimetre offsets independently qualify
                        # orientation, tracked roll and scale, beyond the pivot.
                        for axis,physical in enumerate(physical_axes):
                            point=root_position+physical*np.array([384,384,-6144])*.05
                            expected=expected_projection(eye_world,eyes[index],point,fov)
                            vertex=np.array([*tags['tag_muzzle'],1]);vertex[axis]+=3.2
                            actual=projections[index]@matrices[index]@vertex
                            axis_errors.append(float(np.abs(actual[:2]/actual[3]-expected).max()))
                        if a.case=='translucent':
                            composed=np.array(Image.open(cl/f'world-{eye}.ppm'))
                            translucent_changed.append(int(np.count_nonzero(delta&np.any(composed!=after,axis=2))))
                            checks[f'{eye}_translucent_wall_preserves_model_depth']=(cl/f'world-{eye}-depth.bin').read_bytes()==(cl/f'model-after-{eye}-depth.bin').read_bytes()
                    checks['visible_model_and_depth_both_eyes']=min(changed)>0 and min(depth_changed)>0
                    checks['stereo_model_has_parallax']=bounds[0]!=bounds[1]
                    checks['muzzle_matches_independent_physical_stereo_projection']=max(projection_errors)<2e-5
                    checks['physical_model_axes_scale_and_roll_match']=max(axis_errors)<2e-5
                    if a.model_mode=='sps':
                        checks['same_frame_native_inputs_identical']='OpenXR hand model oracle inputs: identical=1.' in text
                        checks['same_frame_native_model_color_depth_exact']=all(
                            (cl/f'model-reference-{eye}{suffix}').read_bytes()==(cl/f'model-after-{eye}{suffix}').read_bytes()
                            for eye in ('left','right') for suffix in ('.ppm','-depth.bin'))
                        checks['model_collection_writes_zero_color_depth']=all(
                            (cl/f'model-before-{eye}{suffix}').read_bytes()==(cl/f'model-collected-{eye}{suffix}').read_bytes()
                            for eye in ('left','right') for suffix in ('.ppm','-depth.bin'))
                    if a.case=='translucent':checks['near_translucent_wall_composes_over_model_both_eyes']=all(t>c*.9 for t,c in zip(translucent_changed,changed))
                    # Actual server simulation must fire from the same root/ray.
                    phase='native server shot';offset=len(so.text())
                    remote.packet.right.trigger_value=1;remote.packet.right.trigger_click=True;remote.send()
                    so.wait(lambda t:bool(rays(t[offset:],player)),timeout=4)
                    remote.packet.right.trigger_value=0;remote.packet.right.trigger_click=False;remote.send()
                    shot=rays(so.text()[offset:],player)[0]
                    sampled=list(map(int,rows[0][2:]))
                    # The wire vector is physical Q15 XYZ; native hitscan uses
                    # its historic XY magnitude and sixteen Z units per XY.
                    model_direction=np.array(sampled[3:],dtype=float)
                    native_direction=np.array([shot['dx'],shot['dy'],shot['dz']/16.])
                    model_direction/=np.linalg.norm(model_direction)
                    native_direction/=np.linalg.norm(native_direction)
                    direction_error=float(np.abs(model_direction-native_direction).max())
                    checks['model_uses_actual_native_server_root_and_ray']=sampled[:3]==[shot[k] for k in ('x','y','z')] and direction_error<1e-4
                    if a.animation:
                        phase='actual native clip-boundary reload'
                        co.wait(lambda t:completed_reload(t,player),timeout=8)
                        so.wait(lambda t:completed_reload(t,player),timeout=8)
                        animated=co.text()
                        receipts=[tuple(map(int,r)) for r in re.findall(r'OpenXR hand model receipt: serial=(\d+) counter=(\d+) reloading=(\d+) roles=(\d+) valid=(\d+)\.',animated)]
                        samples=[tuple(map(int,r)) for r in re.findall(r'OpenXR hand model sample: serial=(\d+) counter=(\d+) reloading=(\d+) frame=(\d+)\.',animated)]
                        frames_offset=struct.unpack_from('<i',model,92)[0]
                        names=[model[frames_offset+i*56+40:frames_offset+i*56+56].split(b'\0')[0].decode()
                               for i in range(struct.unpack_from('<i',model,76)[0])]
                        checks['actual_native_server_and_client_positive_ammo_reload']=completed_reload(animated,player) and completed_reload(so.text(),player)
                        checks['native_reload_model_roles_observed']=all(any(r[3]==role and r[4] for r in receipts) for role in (1,3,5))
                        checks['native_firing_counter_model_observed']=any(0<c<5 for _,c,_,_ in samples)
                        checks['captured_model_frames_match_native_counter_names']=all(names[f]==('rest' if c==0 else ('fire_' if c<5 else 'reload_')+f'{c:02d}') for _,c,_,f in samples)
                        counter_checks={}
                        for serial,counter,reloading,frame_index in samples:
                            if counter==0:continue
                            prefix=cl/f'model-counter-{counter:02d}'
                            equal=all(Path(str(prefix)+f'-reference-{eye}'+suffix).read_bytes()==Path(str(prefix)+f'-after-{eye}'+suffix).read_bytes()
                                      for eye in ('left','right') for suffix in ('.ppm','-depth.bin'))
                            clean=all(Path(str(prefix)+f'-before-{eye}'+suffix).read_bytes()==Path(str(prefix)+f'-collected-{eye}'+suffix).read_bytes()
                                      for eye in ('left','right') for suffix in ('.ppm','-depth.bin'))
                            visible=all(Image.open(Path(str(prefix)+f'-after-{eye}.ppm')).tobytes()!=Image.open(Path(str(prefix)+f'-before-{eye}.ppm')).tobytes()
                                        for eye in ('left','right'))
                            art=Image.open(cl/f'weapon-counter-{counter:02d}-coverage.pgm').getbbox() is None
                            receipt=any(r[:3]==(serial,counter,reloading) and r[4] for r in receipts)
                            counter_checks[counter]={'native_color_depth_exact':equal,'zero_collection_writes':clean,
                                'visible_both_eyes':visible,'ART_suppressed':art,'valid_native_receipt':receipt}
                        if a.late_field:
                            checks['native_displayend_field_write_once']=len(re.findall(r'addlog vrpistol_late \(player '+str(player)+r'\) = 1',animated))==1
                        checks['animated_counter_stereo_oracles_pass']=bool(counter_checks) and all(all(c.values()) for c in counter_checks.values())
                        if a.animation_fallback:
                            checks.pop('native_reload_model_roles_observed')
                            checks.pop('native_firing_counter_model_observed')
                            checks.pop('animated_counter_stereo_oracles_pass')
                            art_files=list(cl.glob('weapon-counter-*-coverage.pgm'))
                            counters=[int(path.name.split('-')[2]) for path in art_files]
                            checks['positive_native_counters_do_not_emit_ineligible_model']=not any(c>0 for _,c,_,_ in samples) and not receipts
                            checks['actual_firing_and_reload_ART_captured']=any(0<c<5 for c in counters) and any(c>=6 for c in counters)
                            checks['all_captured_fallback_ART_has_native_pixels']=bool(art_files) and all(Image.open(path).getbbox() is not None for path in art_files)
                            details['fallback_native_ART_counters']=sorted(counters)
                        details.update(native_pistol_receipts=receipts,animated_counter_checks=counter_checks,
                            server_pistol_states=pistol_states(so.text(),player),client_pistol_states=pistol_states(animated,player))
                    else:
                        co.pause(.7)
                    if a.last_shot:
                        so.wait(lambda t:any(r['ammo']==0 and r['weapon']!=1 for r in pistol_states(t,player)),timeout=4)
                        co.wait(lambda t:any(r['ammo']==0 and r['weapon']!=1 for r in pistol_states(t,player)),timeout=4)
                        checks['native_zero_ammo_weapon_switch_on_both_peers']=True
                    checks['native_fire_does_not_cancel_XR']='receipt mismatch' not in co.text() and 'held-model emission failed' not in co.text()
                    details.update(changed_pixels=changed,depth_changed_pixels=depth_changed,bounds=bounds,native_shot=shot,native_ray_normalized_max_error=direction_error,muzzle_projection_NDC_max_error=projection_errors,axis_projection_NDC_max_error=axis_errors,model_pixels_covered_by_translucency=translucent_changed)
            if os.environ.get('EDUKE32_TEST_PRIVATE_WINDOW')=='1':
                x11=X11(a.display);window,_=x11.owned_window(client.pid)
                if not window:raise RuntimeError('owned XR drawable missing')
                state=x11.window_visibility(window)
                checks.update(private_drawable_unmapped=state['unmapped'],no_desktop_focus=not state['has_desktop_focus'])
            result={'passed':all(checks.values()),'case':a.case,'model_mode':a.model_mode,'vertex_mode':a.vertex_mode,'fault':a.fault,'receipt_fault':a.receipt_fault,'checks':checks,**details}
    except Exception as exc:
        result={'passed':False,'case':a.case,'phase':phase,'error':str(exc)}
    finally:
        stop(client);stop(server)
        for log in logs:log.close()
    result['evidence_directory']=str(root)
    result['sha256']={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in
        (a.binary.resolve(),a.client_binary.resolve(),a.model_root.resolve()/'duke_assets/pistol.md3',a.model_root.resolve()/'duke_assets/pistol.png')}
    (root/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
