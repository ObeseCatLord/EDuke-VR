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
from smoke_weapon import quaternion


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('binary','client-binary','grp','model-root','work-dir'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--display',default=':105')
    p.add_argument('--remote-port',type=int,default=49777)
    p.add_argument('--port',type=int,default=24610)
    p.add_argument('--case',choices=('base','roll','translucent','missing-skin','custom','second-eye-failure'),default='base')
    a=p.parse_args()
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
            data=bytearray(room())
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
        (cl/'hand-model.def').write_text('model "duke_assets/pistol.md3" {\n'
            ' scale 0.5859375\n'
            f' skin {{ pal 0 surface 0 file "duke_assets/{skin}" }}\n'
            ' frame { name "rest" tile 21 smoothduration 0 }\n}\n')
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
        if a.case=='second-eye-failure':ce['EDUKE32_XR_TEST_FAIL']='model-eye-1'
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
            if a.case=='second-eye-failure':
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    text=(cl/'client.log').read_text(errors='replace')
                    if 'injected held-model failure before second eye' in text:break
                    if client.poll() is not None:raise RuntimeError('owned game exited before injected failure')
                    time.sleep(.05)
                canceled=re.findall(r'OpenXR hand model frame canceled: serial=(\d+) submitted=(\d+)\.',text)
                checks={'second_eye_failure_cancels_XR':'injected held-model failure before second eye' in text,
                        'partially_drawn_frame_never_submitted':bool(canceled) and int(canceled[-1][0])>int(canceled[-1][1]),
                        'no_completed_model_frame_receipt':'OpenXR hand model:' not in text,
                        'no_sixty_frame_model_submission':'OpenXR world oracle: 60 frames' not in text}
                details={}
            else:
                co.wait(lambda t:'OpenXR world oracle: 60 frames' in t and 'OpenXR HUD presentation: 60 frames' in t,timeout=25)
                text=co.text()
                fallback=a.case in ('missing-skin','custom')
                checks={'sixty_world_and_HUD_submissions':'OpenXR world oracle: 60 frames' in text,
                    'core_validation_active':'Core Validation output type:' in text,
                    'core_validation_clean':not re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)',text)}
                counts=re.findall(r'full multiview=(\d+); hand models twoPass=(\d+)',text)
                checks['model_frames_reported_as_two_pass']=bool(counts) and (int(counts[-1][1])==0 if fallback else int(counts[-1][1])>0 and sum(map(int,counts[-1]))<=60)
                details={}
                if fallback:
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
                    forward=np.array(list(map(int,rows[0][5:])),dtype=float)*np.array([1,1,-1])
                    forward/=np.linalg.norm(forward)
                    right=np.array([-forward[1],forward[0],0]);right/=np.linalg.norm(right)
                    up=np.cross(forward,right)
                    right=right*math.cos(math.radians(roll))+up*math.sin(math.radians(roll))
                    up=np.cross(forward,right)
                    physical_axes=(forward,right,up)
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
                        # muzzle, including native unequal XY/Z scale.
                        root_position=np.array(list(map(int,rows[index][2:5])))
                        rel=(root_position-eyes[index])/np.array([384,384,6144])
                        yaw,pitch=angles[index*2:index*2+2]
                        front=rel[0]*math.cos(yaw)+rel[1]*math.sin(yaw)
                        horizontal=-rel[0]*math.sin(yaw)+rel[1]*math.cos(yaw);up=-rel[2]
                        forward=front*math.cos(pitch)+up*math.sin(pitch)
                        vertical=up*math.cos(pitch)-front*math.sin(pitch)
                        fov=np.tan(np.fromstring(re.findall(r'OpenXR weapon view: eye='+str(index)+r'.*? fov=([^\n]+)\.',text)[-1],sep=','))
                        left,right_t,top,bottom=fov
                        expected=np.array([(2*horizontal/forward-right_t-left)/(right_t-left),(2*vertical/forward-top-bottom)/(top-bottom)])
                        actual=projections[index]@matrices[index]@np.array([*tags['tag_muzzle'],1])
                        projection_errors.append(float(np.abs(actual[:2]/actual[3]-expected).max()))
                        # Three five-centimetre offsets independently qualify
                        # orientation, tracked roll and scale, beyond the pivot.
                        for axis,physical in enumerate(physical_axes):
                            point=root_position+physical*np.array([384,384,-6144])*.05
                            rel=(point-eyes[index])/np.array([384,384,6144])
                            front=rel[0]*math.cos(yaw)+rel[1]*math.sin(yaw)
                            horizontal=-rel[0]*math.sin(yaw)+rel[1]*math.cos(yaw);vertical=-rel[2]
                            distance=front*math.cos(pitch)+vertical*math.sin(pitch)
                            height=vertical*math.cos(pitch)-front*math.sin(pitch)
                            expected=np.array([(2*horizontal/distance-right_t-left)/(right_t-left),(2*height/distance-top-bottom)/(top-bottom)])
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
                    # Native firing temporarily returns to ART, then requalifies idle.
                    co.pause(.7)
                    checks['native_fire_does_not_cancel_XR']='receipt mismatch' not in co.text() and 'held-model emission failed' not in co.text()
                    details.update(changed_pixels=changed,depth_changed_pixels=depth_changed,bounds=bounds,native_shot=shot,native_ray_normalized_max_error=direction_error,muzzle_projection_NDC_max_error=projection_errors,axis_projection_NDC_max_error=axis_errors,model_pixels_covered_by_translucency=translucent_changed)
            if os.environ.get('EDUKE32_TEST_PRIVATE_WINDOW')=='1':
                x11=X11(a.display);window,_=x11.owned_window(client.pid)
                if not window:raise RuntimeError('owned XR drawable missing')
                state=x11.window_visibility(window)
                checks.update(private_drawable_unmapped=state['unmapped'],no_desktop_focus=not state['has_desktop_focus'])
            result={'passed':all(checks.values()),'case':a.case,'checks':checks,**details}
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
