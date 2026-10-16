#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Real Monado tracked orientation -> native server angles -> RPG and impact.

Uses native packets/weapon simulation, a local controlled map/CON fixture, and
an already-running private remote runtime. No game data writes or shot injection.
"""
import argparse
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
from monado_remote import Remote, Quat
from smoke_actions import Observer
from smoke_actions_multiplayer import wait_for_join_barrier
from smoke_multiplayer import X11, setup_lab, stop
from stereo_fixture import sector, wall, sprite, PHEIGHT

FIELDS=re.compile(r'addlog (vraim|vrshot|vrimpact)_(\w+)(?: \(player \d+\))? = (-?\d+)')


def records(text, prefix, start, end):
    result=[]; current={}
    for kind,key,value in FIELDS.findall(text):
        if kind!=prefix: continue
        if key==start: current={}
        current[key]=int(value)
        if key==end: result.append(current); current={}
    return result


def players(text,player): return [v for v in records(text,'vraim','tick','ammo') if v['player']==player]
def shots(text,player): return [v for v in records(text,'vrshot','player','native_offset') if v['player']==player]
def impacts(text): return records(text,'vrimpact','x','z')


def orientation(yaw,pitch=0):
    y,p=math.radians(yaw)/2,math.radians(pitch)/2
    return Quat(math.sin(p)*math.cos(y),-math.cos(p)*math.sin(y),math.sin(p)*math.sin(y),math.cos(p)*math.cos(y))


def room():
    sec=bytearray(sector(0,4));struct.pack_into('<i',sec,4,-32768)
    walls=[wall(0,0,1),wall(8192,0,2,shade=12),wall(8192,8192,3),wall(0,8192,0,shade=12)]
    starts=[sprite(1024,1024+i*1536,0,0,tile=1405,angle=0) for i in range(4)]
    return struct.pack('<iiiihhh',7,1024,4096,-PHEIGHT,0,0,1)+sec+struct.pack('<h',4)+b''.join(walls)+struct.pack('<h',len(starts))+b''.join(starts)


def angle(sample): return (sample['angle']/65536)*math.pi/1024
def pitch(sample): return math.atan((sample['horizon']/65536-100)/128)
def difference(a,b): return math.remainder(a-b,2*math.pi)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('binary','client-binary','grp','work-dir'): p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--display',default=':1');p.add_argument('--remote-port',type=int,required=True)
    p.add_argument('--port',type=int,default=24594);p.add_argument('--mode',choices=('right','left','head'),default='right')
    p.add_argument('--late-controller',action='store_true')
    p.add_argument('--resize',action='store_true')
    a=p.parse_args()
    if a.late_controller and a.mode=='head': p.error('--late-controller requires a hand aim mode')
    a.work_dir.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='tracked-aim-',dir=a.work_dir.resolve()))
    server=client=None; logs=[]; result={'passed':False}; phase='startup'
    try:
        sl=setup_lab(root,'server',a.grp.resolve(),False);cl=setup_lab(root,'client',a.grp.resolve(),False)
        for lab in (sl,cl):
            for name in ('aim_test.con','controller_test.con'): shutil.copyfile(Path(__file__).parent/'fixtures'/name,lab/name)
            (lab/'aim.map').write_bytes(room())
        common=dict(os.environ,DISPLAY=a.display,SDL_VIDEODRIVER='x11',SDL_AUDIODRIVER='dummy')
        se={k:v for k,v in common.items() if not k.startswith(('XR_','EDUKE32_XR'))}
        ce=dict(common,EDUKE32_XR='1',EDUKE32_XR_UI='2',EDUKE32_XR_SINGLE_PASS='1',EDUKE32_XR_AIM=a.mode,
                EDUKE32_XR_TEST_AIM='1',EDUKE32_XR_CROSSHAIR_OUTPUT=str(cl/'aim-crosshair'),EDUKE32_XR_TEST_INPUT='1',EDUKE32_XR_HUD_OUTPUT=str(cl/'aim'),EDUKE32_XR_WORLD_OUTPUT=str(cl/'world'))
        for key in ('EDUKE32_XR_TEST_ZERO_IPD','EDUKE32_XR_TEST_STEREO_POSE','EDUKE32_XR_TEST_FAIL','EDUKE32_XR_TEST_HUD_MENU','EDUKE32_XR_TEST_HUD_TINT'):
            ce.pop(key,None)
        slog=(sl/'server.log').open('w');logs.append(slog)
        server=subprocess.Popen([str(a.binary.resolve()),'-usecwd','-nosetup','-noautoload','-dedicated','-port',str(a.port),'-map','aim.map','-x','aim_test.con'],cwd=sl,env=se,stdin=subprocess.DEVNULL,stdout=slog,stderr=subprocess.STDOUT)
        so=Observer(server,sl/'server.log');so.wait(lambda t:'Multiplayer server initialized.' in t)
        with Remote(a.remote_port) as remote:
            if a.late_controller:
                (remote.packet.left if a.mode=='left' else remote.packet.right).active=False;remote.send()
            clog=(cl/'client.log').open('w');logs.append(clog)
            client=subprocess.Popen([str(a.client_binary.resolve()),'-usecwd','-nosetup','-noautoload','-nologo','-ns','-nm','-connect',f'127.0.0.1:{a.port}','-x','aim_test.con'],cwd=cl,env=ce,stdin=subprocess.DEVNULL,stdout=clog,stderr=subprocess.STDOUT)
            co=Observer(client,cl/'client.log')
            phase='join barrier'
            barrier=wait_for_join_barrier(X11(a.display),client,cl/'client.log',so);player=barrier['server_player']
            so.wait(lambda t:len(players(t,player))>=20);co.pause(.2)
            phase='tracking samples'
            before=players(so.text(),player)[-1]
            hand=remote.packet.left if a.mode=='left' else remote.packet.right
            if a.late_controller: hand.active=True;remote.send()
            def set_pose(yaw,pit,head_yaw=0,head_pitch=0):
                hand.pose.orientation=orientation(yaw,pit)
                remote.packet.head.center.orientation=orientation(head_yaw,head_pitch);remote.send()
            target=(12,8)
            if a.mode=='head':
                set_pose(0,0,*target)
            else:set_pose(*target)
            so.pause(.65);steady=players(so.text(),player)[-1]
            # The HMD now moves independently of the held controller.
            if a.mode!='head':
                if a.resize:
                    remote.packet.head.center.position.x+=.08
                    remote.packet.head.center.position.y-=.02
                    remote.packet.head.center.position.z-=.05
                set_pose(*target,head_yaw=-18,head_pitch=6)
            so.pause(.65);head=players(so.text(),player)[-1]
            last=players(so.text(),player)[-6:]
            expected_yaw=angle(before)+math.radians(target[0])
            expected_pitch=pitch(before)+math.radians(target[1])
            checks={'native_server_orientation_matches_tracking':abs(difference(angle(steady),expected_yaw))<.002 and abs(pitch(steady)-expected_pitch)<.002,
                    'held_pose_does_not_accumulate':max(angle(v) for v in last)-min(angle(v) for v in last)<.002}
            if a.mode!='head':checks['independent_HMD_does_not_turn_authoritative_aim']=abs(difference(angle(head),angle(steady)))<.002 and abs(pitch(head)-pitch(steady))<.002
            phase='RPG shot'
            offset=len(so.text());remote.packet.right.trigger_value=1;remote.packet.right.trigger_click=True;remote.send()
            so.wait(lambda t:bool(shots(t[offset:],player)),timeout=4)
            remote.packet.right.trigger_value=0;remote.packet.right.trigger_click=False;remote.send()
            phase='RPG impact'
            so.wait(lambda t:bool(impacts(t[offset:])),timeout=5)
            actual=shots(so.text()[offset:],player)[0];hit=impacts(so.text()[offset:])[0]
            checks['native_RPG_spawn_matches_server_angle']=actual['angle']==((actual['native_angle']>>16)&2047)
            checks['native_RPG_spawn_matches_server_pitch']=actual['zvel']==((100*65536-actual['native_horizon']-actual['native_offset'])>>16)*81
            checks['actual_server_RPG_reaches_target_wall']=hit['x']>8000
            shot_angle=actual['angle']*math.pi/1024
            distance=hit['x']-actual['x']
            ticks=distance/(math.cos(shot_angle)*actual['speed'])
            predicted_y=actual['y']+distance*math.tan(shot_angle)
            predicted_z=actual['z']+ticks*actual['zvel']
            trajectory_error=[abs(hit['y']-predicted_y),abs(hit['z']-predicted_z)]
            # Native collision advances in discrete steps. Permit one step and
            # its wall clearance, while rejecting a wrong heading/pitch path.
            checks['actual_impact_matches_authoritative_trajectory']=trajectory_error[0]<abs(math.sin(shot_angle)*actual['speed'])+32 and trajectory_error[1]<abs(actual['zvel'])+256
            # An inactive/recovered source while trigger held cannot fire again.
            so.pause(.9);fault_offset=len(so.text())
            hand.active=False;remote.packet.right.trigger_value=1;remote.packet.right.trigger_click=True;remote.send();so.pause(.35)
            hand.active=True;remote.send();so.pause(.9)
            fault_samples=players(so.text()[fault_offset:],player)
            checks['source_reactivation_requires_trigger_release']=not shots(so.text()[fault_offset:],player) and bool(fault_samples) and all(not(v['bits']&4) for v in fault_samples[-5:])
            remote.packet.right.trigger_value=0;remote.packet.right.trigger_click=False;remote.send();so.pause(.2)
            offset=len(so.text());remote.packet.right.trigger_value=1;remote.packet.right.trigger_click=True;remote.send()
            so.wait(lambda t:bool(shots(t[offset:],player)),timeout=4)
            remote.packet.right.trigger_value=0;remote.packet.right.trigger_click=False;remote.send()
            checks['new_press_after_release_fires']=True
            phase='60 stereo submissions'
            co.wait(lambda t:'OpenXR world oracle: 60 frames' in t and 'OpenXR HUD presentation: 60 frames' in t,timeout=15)
            left,right=cl/'aim-left.ppm',cl/'aim-right.ppm'
            checks['actual_60_stereo_world_HUD_submissions']=left.is_file() and right.is_file() and left.read_bytes()!=right.read_bytes()
            text=co.text()
            camera=re.findall(r'OpenXR aim camera: authorityYaw=(-?\d+\.\d+) bodyYaw=(-?\d+\.\d+) leftYaw=(-?\d+\.\d+) leftPitch=(-?\d+\.\d+) rightYaw=(-?\d+\.\d+) rightPitch=(-?\d+\.\d+)',text)
            head_yaw,head_pitch=target if a.mode=='head' else (-18,6)
            actual_camera=list(map(float,camera[-1])) if camera else []
            position_pattern=r'OpenXR aim eye positions: left=(-?\d+),(-?\d+),(-?\d+) right=(-?\d+),(-?\d+),(-?\d+)'
            positions=re.findall(position_pattern,text)
            actual_positions=list(map(int,positions[-1])) if positions else []
            checks['actual_eye_cameras_follow_HMD_once']=len(actual_camera)==6 and all(abs(difference(actual_camera[i],math.radians(v)))<.002 for i,v in ((2,head_yaw),(3,head_pitch),(4,head_yaw),(5,head_pitch)))
            # The former head-panel marker is now a native world-space segment.
            from smoke_crosshair import raster
            prefix=cl/'aim-crosshair'
            actual_marker=list(map(int,re.findall(r'OpenXR world crosshair: start=(-?\d+),(-?\d+),(-?\d+) hit=(-?\d+),(-?\d+),(-?\d+)',text)[-1]))
            ray=(np.array(actual_marker[3:])-actual_marker[:3])/np.array([1,1,16]);ray=ray/np.linalg.norm(ray)
            ay,ap=angle(head),pitch(head)
            direction=np.array([math.cos(ay)*math.cos(ap),math.sin(ay)*math.cos(ap),-math.sin(ap)])
            checks['world_crosshair_trace_follows_native_authority']=float(np.abs(ray-direction).max())<.001
            matrices={int(i):np.fromstring(m,sep=',').reshape(4,4,order='F') for i,m in re.findall(r'OpenXR crosshair matrix: eye=(\d) values=([^\n]+)\.',text)}
            ui=np.array(Image.open(str(prefix)+'-ui.ppm'));alpha=np.array(Image.open(str(prefix)+'-coverage.pgm'));errors=[]
            for eye,name in enumerate(('left','right')):
                before_eye=np.array(Image.open(str(prefix)+f'-before-{name}.ppm'));after_eye=np.array(Image.open(str(prefix)+f'-{name}.ppm'))
                depth=np.flipud(np.fromfile(str(prefix)+f'-before-{name}-depth.bin',dtype=np.uint32).reshape(before_eye.shape[:2]))/4294967295
                expected,_,_=raster(before_eye,ui,alpha,depth,matrices[eye]);errors.append(int(np.abs(expected.astype(int)-after_eye.astype(int)).max()))
            checks['both_eye_world_crosshair_pixels_match_projection']=max(errors)<=2
            if 'XR_APILAYER_LUNARG_core_validation' in ce.get('XR_ENABLE_API_LAYERS',''):
                checks['core_validation_active']='Core Validation output type:' in co.text()
            checks['core_validation_no_warning_or_error']=not bool(re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)',co.text()))
            if a.resize:
                # Capture evidence before the second generation overwrites its
                # 60th-frame files; the actual UI pixel check above uses these.
                for image in cl.glob('aim-*.ppm'): shutil.copyfile(image,image.with_name('initial-'+image.name))
                previous=players(so.text(),player)[-1]
                x=X11(a.display);window,_=x.owned_window(client.pid)
                if not window: raise RuntimeError('owned window missing before resize')
                import ctypes as c
                x.x.XResizeWindow.argtypes=[c.c_void_p,c.c_ulong,c.c_uint,c.c_uint]
                x.x.XResizeWindow(x.display,window,800,600);x.x.XSync(x.display,0)
                co.wait(lambda t:t.count('OpenXR HUD presentation: 60 frames')>=2 and t.count('OpenXR world oracle: 60 frames')>=2,timeout=15)
                restored=players(so.text(),player)[-1]
                checks['session_recreation_preserves_authoritative_aim']=abs(difference(angle(previous),angle(restored)))<.002 and abs(pitch(previous)-pitch(restored))<.002
                new_camera=re.findall(r'OpenXR aim camera: authorityYaw=(-?\d+\.\d+) bodyYaw=(-?\d+\.\d+) leftYaw=(-?\d+\.\d+) leftPitch=(-?\d+\.\d+) rightYaw=(-?\d+\.\d+) rightPitch=(-?\d+\.\d+)',co.text())
                new_camera=list(map(float,new_camera[-1])) if new_camera else []
                checks['session_recreation_preserves_eye_direction']=len(new_camera)==6 and max(abs(difference(x,y)) for x,y in zip(new_camera,actual_camera))<.002
                checks['resized_actual_eye_extent']=Image.open(cl/'aim-left.ppm').size==(800,600)
                positions=re.findall(position_pattern,co.text())
                new_positions=list(map(int,positions[-1])) if positions else []
                checks['session_recreation_preserves_nonzero_head_offset']=len(actual_positions)==6 and new_positions==actual_positions and max(abs((actual_positions[i]+actual_positions[i+3])*.5-head[k]) for i,k in ((0,'x'),(1,'y')))>16
            # An exactly vertical source has undefined yaw but must still
            # update native pitch to its limit, without introducing NaN/drift.
            if a.mode!='head':
                set_pose(12,90,head_yaw=-18,head_pitch=6);so.pause(.5)
                pole=players(so.text(),player)[-1]
                checks['vertical_pose_reaches_native_pitch_limit']=abs(pole['horizon']-299*65536)<64 and abs(difference(angle(pole),angle(head)))<.002
                set_pose(179,0,head_yaw=-18,head_pitch=6);so.pause(.3)
                wrap_before=players(so.text(),player)[-1]
                set_pose(-179,0,head_yaw=-18,head_pitch=6);so.pause(.3)
                wrap_after=players(so.text(),player)[-1]
                checks['yaw_wrap_uses_shortest_displacement']=abs(difference(angle(wrap_after),angle(wrap_before))-math.radians(2))<.002
                start=players(so.text(),player)[-1]
                remote.packet.left.thumbstick.y=.8;remote.send();so.pause(.5)
                remote.packet.left.thumbstick.y=0;remote.send();so.pause(.2)
                moved=players(so.text(),player)[-1]
                dx,dy=moved['x']-start['x'],moved['y']-start['y']
                checks['native_locomotion_uses_body_not_backward_hand_heading']=dx>100 and abs(dy)<dx*.05
                offset=len(co.text())
                remote.packet.right.thumbstick.y=1;remote.send();co.pause(1.2)
                body_values=re.findall(r'bodyPitch=(-?\d+\.\d+)',co.text()[offset:])
                limit=math.atan((299-100)/128)
                checks['virtual_body_pitch_retains_native_limit']=bool(body_values) and max(map(float,body_values))<=limit+.002 and float(body_values[-1])>=limit-.002
                remote.packet.right.thumbstick.y=0;remote.send()
            if a.late_controller: checks['late_controller_uses_existing_head_reference']=checks['native_server_orientation_matches_tracking'] and checks['actual_eye_cameras_follow_HMD_once']
            result={'passed':all(checks.values()),'checks':checks,'mode':a.mode,'server_player':player,
                    'native_samples':{'before':before,'controller':steady,'after_HMD_motion':head},'actual_RPG':actual,'actual_impact':hit,'impact_trajectory_error_build_units':trajectory_error,'actual_eye_camera_radians':actual_camera,'actual_eye_positions_build':actual_positions,'actual_marker':actual_marker,'crosshair_pixel_max_error':errors,
                    'expected_delta_degrees':list(target),'observed_delta_degrees':[math.degrees(difference(angle(steady),angle(before))),math.degrees(pitch(steady)-pitch(before))]}
    except Exception as error:result={'passed':False,'phase':phase,'error':str(error)}
    finally:
        stop(client);stop(server)
        for log in logs: log.close()
    result['evidence_directory']=str(root); (root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
