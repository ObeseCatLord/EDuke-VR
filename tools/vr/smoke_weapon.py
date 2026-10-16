#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual controller-attached native ART card and sequential capture proof.

An owned game/window and private Monado remote runtime only. Native callback
counts, actual isolated weapon RGBA, both eye/depth layers, and an independent
CPU ray/plane/linear-sampling oracle qualify the attachment. No shot injection.
"""
import argparse
import ctypes as c
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
from smoke_multiplayer import X11, stop
from smoke_world import CONFIG

FLOAT=r'-?\d+\.\d+'

def rotation(q):
    x,y,z,w=q
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                     [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                     [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])


def quaternion(yaw,pitch,roll):
    y,p,r=map(lambda v:math.radians(v)/2,(yaw,pitch,roll))
    # Yaw-right uses negative OpenXR Y, followed by local X pitch and Z roll.
    a=np.array([0,-math.sin(y),0,math.cos(y)]);b=np.array([math.sin(p),0,0,math.cos(p)])
    def mul(a,b):return np.r_[a[3]*b[:3]+b[3]*a[:3]+np.cross(a[:3],b[:3]),a[3]*b[3]-np.dot(a[:3],b[:3])]
    return mul(mul(a,b),np.array([0,0,math.sin(r),math.cos(r)]))


def warp(before,ui,alpha,view,placement,visible,subpixel_bits=8,half_width=None,half_height=.3):
    """Independent eye rays intersect physical card; sample captured native ART."""
    if not visible:return before.copy()
    h,w=before.shape[:2];th,tw=ui.shape[:2]
    vp,vq,fov=view;position,orientation=placement
    left,right,up,down=np.tan(fov)
    if half_width is None:half_width=half_height*tw/th
    yy,xx=np.mgrid[:h,:w]
    direction=np.stack([left+(right-left)*(xx+.5)/w,up-(up-down)*(yy+.5)/h,-np.ones_like(xx)],axis=-1)
    inverse=rotation(orientation).T
    rays=direction@rotation(vq).T@inverse.T
    origin=(np.asarray(vp)-np.asarray(position))@inverse.T
    with np.errstate(divide='ignore',invalid='ignore'):distance=-origin[2]/rays[:,:,2]
    points=origin+distance[:,:,None]*rays
    u=(points[:,:,0]/half_width+1)*.5;v=(1-points[:,:,1]/half_height)*.5
    # Native raster coverage snaps projected vertices to the actual driver's
    # subpixel grid. Keep this distinct from continuous ray/texture sampling.
    corners=np.array([[-half_width,-half_height,0],[half_width,-half_height,0],[half_width,half_height,0],[-half_width,half_height,0]])
    eye_corners=(corners@rotation(orientation).T+position-vp)@rotation(vq)
    projected=np.c_[(eye_corners[:,0]/-eye_corners[:,2]-left)/(right-left)*w,
                    (up-eye_corners[:,1]/-eye_corners[:,2])/(up-down)*h]
    grid=2**subpixel_bits;projected=np.rint(projected*grid)/grid
    inside=np.zeros((h,w),dtype=bool)
    for tri in ((0,1,2),(0,2,3)):
        edges=[]
        for j,k in zip(tri,tri[1:]+tri[:1]):
            a,b=projected[j],projected[k]
            edges.append((b[0]-a[0])*(yy+.5-a[1])-(b[1]-a[1])*(xx+.5-a[0]))
        inside|=(np.minimum.reduce(edges)>=0)|(np.maximum.reduce(edges)<=0)
    inside&=distance>0
    sx=np.clip(u*tw-.5,0,tw-1);sy=np.clip(v*th-.5,0,th-1)
    sx=np.nan_to_num(sx);sy=np.nan_to_num(sy)
    x0=sx.astype(int);y0=sy.astype(int);x1=np.minimum(x0+1,tw-1);y1=np.minimum(y0+1,th-1)
    fx=(sx-x0)[:,:,None];fy=(sy-y0)[:,:,None]
    rgba=np.dstack([ui,alpha]).astype(float)
    sampled=(rgba[y0,x0]*(1-fx)+rgba[y0,x1]*fx)*(1-fy)+(rgba[y1,x0]*(1-fx)+rgba[y1,x1]*fx)*fy
    out=sampled[:,:,:3]+before*(1-sampled[:,:,3:4]/255)
    return np.where(inside[:,:,None],np.clip(np.rint(out),0,255),before).astype(np.uint8)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('binary','grp','work-dir'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--display',default=':1');p.add_argument('--remote-port',type=int,required=True)
    p.add_argument('--case',choices=('base','moved','rotated','head','left','lost','resize','tint','save','nested'),default='base')
    a=p.parse_args();a.work_dir.mkdir(parents=True,exist_ok=True)
    lab=Path(tempfile.mkdtemp(prefix='weapon-',dir=a.work_dir.resolve()))
    (lab/'eduke32.cfg').write_text(CONFIG);(lab/'DUKE3D.GRP').symlink_to(a.grp.resolve())
    shutil.copyfile(Path(__file__).parent/'fixtures/hud_test.con',lab/'hud_test.con')
    (lab/'tiles099.art').write_bytes(struct.pack('<4i',1,2,30000,30001)+struct.pack('<2h',16,16)+struct.pack('<2h',16,16)+bytes(8)+bytes([255])*256+bytes([196])*256)
    env={k:v for k,v in os.environ.items() if not k.startswith('EDUKE32_XR')}
    mode='left' if a.case=='left' else 'right'
    env.update(DISPLAY=a.display,SDL_VIDEODRIVER='x11',SDL_AUDIODRIVER='dummy',EDUKE32_XR='1',EDUKE32_XR_UI='2',EDUKE32_XR_SINGLE_PASS='1',EDUKE32_XR_AIM=mode,EDUKE32_XR_WEAPON='1',
               EDUKE32_XR_WEAPON_OUTPUT=str(lab/'weapon'),EDUKE32_XR_CROSSHAIR_OUTPUT=str(lab/'crosshair'),EDUKE32_XR_WORLD_OUTPUT=str(lab/'world'),EDUKE32_XR_HUD_OUTPUT=str(lab/'hud'))
    if a.case=='tint':env['EDUKE32_XR_TEST_HUD_TINT']='3'
    if a.case=='save':env['EDUKE32_XR_TEST_HUD_MENU']='2'
    if a.case=='nested':env['EDUKE32_XR_TEST_WEAPON_NESTED']='1'
    command=[str(a.binary.resolve()),'-usecwd','-nosetup','-noautoload','-nologo','-ns','-nm','-v1','-l1','-s1','-x','hud_test.con']
    process=None;result={'passed':False}
    try:
        with Remote(a.remote_port) as remote:
            local_origin=np.array([remote.packet.head.center.position.x,remote.packet.head.center.position.y,remote.packet.head.center.position.z])
            hand=remote.packet.left if mode=='left' else remote.packet.right
            hand.pose.position.x=-.2 if mode=='left' else .2
            hand.pose.position.y=1.25;hand.pose.position.z=-.6
            hand.pose.orientation=Quat(0,0,0,1);remote.send()
            with (lab/'game.log').open('w') as log:
                process=subprocess.Popen(command,cwd=lab,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
                obs=Observer(process,lab/'game.log');obs.wait(lambda t:'OpenXR opaque single-pass:' in t)
                if a.case=='moved':hand.pose.position.x=-.2;hand.pose.position.y+=.1;hand.pose.position.z=-.8
                if a.case=='rotated':hand.pose.orientation=Quat(*quaternion(20,12,15))
                if a.case=='head':
                    remote.packet.head.center.orientation=Quat(*quaternion(-15,6,0))
                    remote.packet.head.center.position.x+=.08;remote.packet.head.center.position.y-=.02;remote.packet.head.center.position.z-=.05
                if a.case=='lost':hand.active=False
                remote.send()
                if a.case=='resize':
                    x=X11(a.display);window,_=x.owned_window(process.pid)
                    if not window:raise RuntimeError('owned window missing')
                    x.x.XResizeWindow.argtypes=[c.c_void_p,c.c_ulong,c.c_uint,c.c_uint]
                    x.x.XResizeWindow(x.display,window,800,600);x.x.XSync(x.display,0)
                text=obs.wait(lambda t:'OpenXR HUD presentation: 60 frames' in t and (lab/'hud-coverage.pgm').is_file(),timeout=25)
                # Captures are written before final submit accounting; require actual submission proof.
                obs.pause(.1);text=obs.text()
                found=re.findall(r'OpenXR weapon card: visible=(\d) pos=('+FLOAT+','+FLOAT+','+FLOAT+r') quat=('+FLOAT+','+FLOAT+','+FLOAT+','+FLOAT+r')',text)
                if not found:raise RuntimeError('no native weapon boundary capture')
                visible,pos,quat=found[-1];visible=bool(int(visible));pos=np.fromstring(pos,sep=',');quat=np.fromstring(quat,sep=',')
                views=[]
                for eye,ep,eq,fov in re.findall(r'OpenXR weapon view: eye=(\d) pos=('+FLOAT+','+FLOAT+','+FLOAT+r') quat=('+FLOAT+','+FLOAT+','+FLOAT+','+FLOAT+r') fov=('+FLOAT+','+FLOAT+','+FLOAT+','+FLOAT+r')',text)[-2:]:
                    views.append((np.fromstring(ep,sep=','),np.fromstring(eq,sep=','),np.fromstring(fov,sep=',')))
                ui=np.array(Image.open(lab/'weapon-ui.ppm'));alpha=np.array(Image.open(lab/'weapon-coverage.pgm'))
                hud_alpha=np.array(Image.open(lab/'hud-coverage.pgm'))
                before=[np.array(Image.open(lab/f'weapon-before-{eye}.ppm')) for eye in ('left','right')]
                after=[np.array(Image.open(lab/f'weapon-{eye}.ppm')) for eye in ('left','right')]
                # Assert actual card placement from the submitted protocol pose,
                # independent of backend/model matrix used for pixel oracle.
                hpos=np.array([hand.pose.position.x,hand.pose.position.y,hand.pose.position.z]);hq=np.array([getattr(hand.pose.orientation,k) for k in ('x','y','z','w')])
                expected_position=hpos-local_origin+rotation(hq)@np.array([-.08,.24,-.15])
                subpixel_bits=int(re.findall(r'OpenXR overlay raster: subpixelBits=(\d+)',text)[-1])
                expected=[warp(before[i],ui,alpha,views[i],(expected_position,hq),visible,subpixel_bits) for i in range(2)]
                errors=[np.abs(after[i].astype(int)-expected[i].astype(int)) for i in range(2)]
                changed=[int(np.any(after[i]!=before[i],axis=2).sum()) for i in range(2)]
                checks={'actual_60_world_HUD_submissions':'OpenXR world oracle: 60 frames' in text,
                        'weapon_capture_has_native_ART':int((alpha==255).sum())>1000,
                        'native_weapon_source_absent_from_final_HUD':not np.any(hud_alpha[alpha>0]) if a.case!='save' else True,
                        'selected_hand_visibility':visible==(a.case!='lost'),
                        'card_pose_matches_actual_remote_source':not visible or (np.max(np.abs(pos-expected_position))<2e-5 and np.max(np.abs(quat-hq))<2e-5),
                        'both_eye_pixels_match_independent_ray_plane_oracle':all(int(e.max())<=2 for e in errors),
                        'weapon_preserves_both_world_depth_layers':all((lab/f'weapon-before-{eye}-depth.bin').read_bytes()==(lab/f'weapon-{eye}-depth.bin').read_bytes() for eye in ('left','right')),
                        'both_eyes_have_visible_weapon_or_no_stale_pose':all(n>1000 for n in changed) if visible else changed==[0,0],
                        'core_validation_active':'Core Validation output type:' in text,
                        'core_validation_no_warning_or_error':not re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)',text)}
                if a.case=='resize':checks['resized_actual_capture_extent']=ui.shape[:2]==(600,800)
                if a.case=='nested':checks['nested_swap_recovers']='weapon test: injected unarmed native presentation' in text
                if a.case=='save':checks['native_save_menu_recovers']='opened native save menu' in text
                if a.case=='tint':
                    # Pick peripheral points outside the head panel and card.
                    final=[np.array(Image.open(lab/f'hud-{eye}.ppm')) for eye in ('left','right')]
                    checks['full_eye_tint_reaches_already_composited_world']=all(np.any(f[:80,:80]!=w[:80,:80]) for f,w in zip(final,after))
                # The spatial crosshair is a separate sequential segment. Its
                # own pixel/depth proof lives in smoke_crosshair; start this HUD
                # composition at that actual completed boundary.
                head=remote.packet.head.center
                head_q=np.array([getattr(head.orientation,k) for k in ('x','y','z','w')])
                head_pos=np.array([head.position.x,head.position.y,head.position.z])-local_origin
                panel_pos=head_pos+rotation(head_q)@np.array([0,0,-1.5])
                final=[np.array(Image.open(lab/f'hud-{eye}.ppm')) for eye in ('left','right')]
                hud=np.array(Image.open(lab/'hud-ui.ppm'))
                final_errors=[]
                for i in range(2):
                    segment=lab/f"crosshair-{('left','right')[i]}.ppm"
                    world=(np.array(Image.open(segment)) if segment.is_file() else after[i]).astype(float)
                    if a.case=='save':world=np.rint(world*(1-168/255))
                    if a.case=='tint':
                        tint=np.array([80,120,200],dtype=float)/255
                        luma=tint@np.array([.2126,.7152,.0722])
                        tint=np.clip((tint*1.3+luma*(1-1.3))*1.4+(.5*(1-1.4)+1.15-1)*(96/255),0,1)
                        world=np.rint(world*(1-96/255)+tint*96)
                    predicted=warp(world.clip(0,255).astype(np.uint8),hud,hud_alpha,views[i],(panel_pos,head_q),True,subpixel_bits,.9,.9*ui.shape[0]/ui.shape[1])
                    final_errors.append(int(np.abs(final[i].astype(int)-predicted.astype(int)).max()))
                checks['final_head_HUD_and_native_tint_match_independent_composition']=max(final_errors)<=2
                counts=dict((k,int(v)) for k,v in re.findall(r'addlog vrhud_(rooms|roomend|weapon|rest)[^=\n]*= (\d+)',text))
                stop(process);process=None
                flat_env=dict(env,EDUKE32_XR='0')
                with (lab/'native.log').open('w') as flat_log:
                    process=subprocess.Popen(command,cwd=lab,env=flat_env,stdin=subprocess.DEVNULL,stdout=flat_log,stderr=subprocess.STDOUT)
                    flat=Observer(process,lab/'native.log')
                    native=flat.wait(lambda t:bool(re.search(r'addlog vrhud_rest[^=\n]*= 60',t)),timeout=15)
                    native_counts=dict((k,int(v)) for k,v in re.findall(r'addlog vrhud_(rooms|roomend|weapon|rest)[^=\n]*= (\d+)',native))
                checks['callbacks_match_actual_native_reference']=counts==native_counts and len(counts)==4
                if a.case=='save':del checks['native_weapon_source_absent_from_final_HUD']
                checks={k:bool(v) for k,v in checks.items()}
                result={'passed':all(checks.values()),'case':a.case,'checks':checks,'native_counts':counts,'flat_reference_counts':native_counts,'eye_max_channel_error':[int(e.max()) for e in errors],
                        'eye_pixels_over_two_bytes':[int((e>2).any(axis=2).sum()) for e in errors], 'changed_pixels':changed,'raster_subpixel_bits':subpixel_bits,'final_composition_max_channel_error':final_errors,
                        'actual_card_position':pos.tolist(),'expected_card_position':expected_position.tolist(),'actual_card_orientation':quat.tolist()}
    except Exception as error:result={'passed':False,'case':a.case,'error':str(error)}
    finally:stop(process)
    result['evidence_directory']=str(lab);(lab/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
