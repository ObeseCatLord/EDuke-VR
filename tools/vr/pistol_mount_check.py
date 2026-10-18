#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independent raw-pose/asset check at AA's actual native firing boundary."""
import math
import re
import struct
import numpy as np
from PIL import Image
from smoke_weapon import rotation
from smoke_hitscan import RAY, KEYS
from floating_hands_check import _project

INPUT = re.compile(r'OpenXR pistol mount input: clock=(\d+) counter=(\d+) hand=(\d+) grip=([^ ]+) aim=([^ ]+) origin=([^ ]+) tracking=([^ ]+) yaw=([^ ]+) offset=([^ ]+)\.')


def observer():
    fields=('x','y','z','pyoff','counter')
    source='\n'+''.join(f'gamevar aamount_{key} 0 1\n' for key in fields)
    source+='appendevent EVENT_PREWEAPONSHOOT\n'
    for key,field in zip(fields,('posx','posy','posz','pyoff','kickback_pic')):
        source+=f' getplayer[THISACTOR].{field} aamount_{key}\n addlog aamount_{key}\n'
    return source+'endevent\n'


def tags(model):
    data=model.read_bytes(); count=struct.unpack_from('<i',data,80)[0]; start=struct.unpack_from('<i',data,96)[0]
    return {data[start+i*112:start+i*112+64].split(b'\0')[0].decode():np.array(struct.unpack_from('<3f',data,start+i*112+64))
            for i in range(count)}


def firing(text, model):
    anchors={}; sample=None; rows=[]; points=tags(model)
    for line in text.splitlines():
        found=INPUT.search(line)
        if found:
            clock,counter,hand,grip,aim,origin,tracking,yaw,offset=found.groups()
            values=[np.fromstring(value,sep=',') for value in (grip,aim,origin,tracking,offset)]
            sample=(int(clock),int(counter),int(hand),*values,float(yaw))
        found=re.search(r'addlog aamount_(x|y|z|pyoff|counter)[^=]*= (-?\d+)',line)
        if found:
            key,value=found.groups()
            if key=='x': anchors={}
            anchors[key]=int(value)
        found=RAY.search(line)
        if not found: continue
        if sample is None or len(anchors)!=5:
            rows.append({'sources_complete':False}); continue
        ray=dict(zip(KEYS,map(int,found.groups())))
        clock,counter,hand,grip,aim,origin,tracking,encoded,yaw=sample
        delta=points['tag_muzzle']-points['tag_palm_'+('right' if hand else 'left')]
        muzzle=grip+rotation(aim[:4])@np.array((delta[1],delta[2],-delta[0]))/64
        def convert(point):
            x,y,z=rotation(tracking)@(point-origin)
            return np.array(((-z*math.cos(yaw)-x*math.sin(yaw))*384,
                             (-z*math.sin(yaw)+x*math.cos(yaw))*384,-y*6144))
        expected=convert(muzzle)
        old=convert(aim[4:])
        actual=np.array((ray['x']-anchors['x'],ray['y']-anchors['y'],ray['z']-anchors['z']-anchors['pyoff']))
        displacement=float(np.linalg.norm((expected-old)/np.array((384,384,6144))))
        errors=np.abs(actual-np.rint(expected))
        rows.append({'sources_complete':True,'sample_clock':clock,'sample_counter':counter,'firing_counter':anchors['counter'],
                     'actual_offset':actual.tolist(),'expected_offset':expected.tolist(),'encoded_offset':encoded.tolist(),
                     'old_aim_offset':old.tolist(),
                     'error_build_units':errors.tolist(),'old_aim_distance_metres':displacement,
                     'native_firing_ART_boundary':0<anchors['counter']<6 and 0<counter<6,
                     'unclamped':ray['clamped']==0,
                     'native_ray_uses_independent_calibrated_muzzle':bool(np.max(errors)<=1),
                     'encoded_input_matches_raw_pose':bool(np.max(np.abs(encoded-np.rint(expected)))<=1),
                     'distinguishes_old_aim_point':displacement>.1})
        anchors={}
    checks={'AA_actual_firing_has_calibrated_muzzle_sources':bool(rows) and all(r['sources_complete'] for r in rows)}
    for name in ('native_firing_ART_boundary','unclamped','native_ray_uses_independent_calibrated_muzzle',
                 'encoded_input_matches_raw_pose','distinguishes_old_aim_point'):
        checks['AA_'+name]=bool(rows) and all(r.get(name,False) for r in rows)
    return {'checks':checks,'rays':rows}


def contacts(text, model):
    """Independently reconstruct the selected current-frame palm/gun contact."""
    points=tags(model); rows=[]
    canonical=np.array(((0,1,0),(0,0,1),(-1,0,0)))
    for block in text.split('OpenXR floating hands:')[1:]:
        header=re.match(r' serial=(\d+) state=(\d+) mask=(\d+) left=\d+ right=\d+ capture=(\d+)\.',block)
        if not header: continue
        serial,state,mask,captured=map(int,header.groups())
        if not captured: continue
        pose=re.search(r'OpenXR pistol mount pose: eye=0 hand=(\d+) grip=([^ ]+) aim=([^\n]+)\.',block)
        render=re.search(r'OpenXR pistol mount render: serial='+str(serial)+
                         r' hand=(\d+) body=([-\d]+),([-\d]+),([-\d]+),([-\d]+),([-\d]+),([-\d]+) clamped=(\d+)\.',block)
        if not pose or not render: continue
        selected,grip,aim=pose.groups(); selected=int(selected)
        render_hand,*body,clamped=render.groups()
        if int(render_hand)!=selected: continue
        if not mask&(1<<selected): continue
        hand=re.search(r'OpenXR floating hand: serial='+str(serial)+r' hand='+str(selected)+
                       r' model=\d+ frame=\d+ root=[^ ]+ pivot=([^ ]+) pose=([^\n]+)\.',block)
        if not hand: continue
        grip,aim,pivot,current=(np.fromstring(value,sep=',') for value in (grip,aim,*hand.groups()))
        mapping=np.array(((0,0,1 if selected else -1),(-1,0,0),(0,-1 if selected else 1,0)))
        # The floating-hand pose is the current raw grip pose.  The mount log
        # supplies its current grip position and aim orientation in the
        # longstanding compact format.
        expected=(rotation(current[:4])@mapping).T@rotation(aim)@canonical
        distances=[]; axis_errors=[]
        for eye in (0,1):
            weapon=re.search(r'OpenXR hand model matrix: eye='+str(eye)+r' values=([^\n]+)\.',block)
            floating=re.search(r'OpenXR floating matrix: serial='+str(serial)+r' hand='+str(selected)+r' eye='+str(eye)+r' values=([^\n]+)\.',block)
            if not weapon or not floating: continue
            w=np.fromstring(weapon[1],sep=',').reshape(4,4,order='F')
            h=np.fromstring(floating[1],sep=',').reshape(4,4,order='F')
            relative=np.linalg.solve(h,w)
            contact=(relative@np.array([*points['tag_palm_'+('right' if selected else 'left')],1]))[:3]
            distances.append(float(np.linalg.norm(contact-pivot)*1000/64))
            axis_errors.append(float(np.max(np.abs(relative[:3,:3]-expected))))
        rows.append({'serial':serial,'state':state,'hand':selected,'current_grip':grip.tolist(),
                     'current_aim':aim.tolist(),'render_body':list(map(int,body)),'clamped':bool(int(clamped)),
                     'visible_palm_separation_mm':distances,'relative_axis_errors':axis_errors,
                     'current_grip_to_floating_grip_mm':float(np.linalg.norm(grip-current[4:])*1000)})
    changing=[r for r in rows if r['state'] in (6,7)]
    motion_rows=[r for r in rows if r['state'] in (6,7,9)]
    unclamped=[r for r in rows if not r['clamped']]
    body_changed=any(sum(abs(r['render_body'][i]-motion_rows[0]['render_body'][i]) for i in (0,1))>20
                     for r in motion_rows[1:]) if motion_rows else False
    result={'checks':{
                'mount_motion_measured_multiple_frames':len(rows)>=3,
                'mount_motion_has_unclamped_current_frame_samples':bool(unclamped),
                'mount_motion_fixture_is_unclamped':bool(rows) and len(unclamped)==len(rows),
                'mounted_palm_separation_within_3mm_unclamped':bool(unclamped) and all(
                    len(r['visible_palm_separation_mm'])==2 and max(r['visible_palm_separation_mm'])<=3 for r in unclamped),
                'mount_roll_changed_in_current_raw_aim':len(changing)>=2 and
                    not np.allclose(changing[0]['current_aim'],changing[-1]['current_aim']),
                'mounted_basis_uses_current_raw_grip_and_aim':bool(unclamped) and all(
                    len(r['relative_axis_errors'])==2 and max(r['relative_axis_errors'])<.0015 and
                    r['current_grip_to_floating_grip_mm']<.01
                    for r in unclamped),
                'mounted_motion_render_body_changed_while_captured':body_changed,
            },
            'frames':rows,
            'maximum_visible_palm_separation_mm':max((max(r['visible_palm_separation_mm']) for r in unclamped if r['visible_palm_separation_mm']),default=None)}
    result['stream']=stream(text,model)
    result['checks'].update(result['stream']['checks'])
    return result


def stream(text, model):
    """Actual submitted right-eye transforms across unchanged native tics."""
    points=tags(model); rows=[]
    submitted={int(v) for v in re.findall(r'OpenXR mount submitted: serial=(\d+)\.',text)}
    pivots={int(h):np.fromstring(p,sep=',') for h,p in re.findall(
        r'OpenXR floating hand: serial=\d+ hand=(\d+) model=\d+ frame=\d+ root=[^ ]+ pivot=([^ ]+)',text)}
    for block in text.split('OpenXR mount stream:')[1:]:
        head=re.match(r' serial=(\d+) tick=(\d+) hand=(\d+) clamped=(\d+) grip=([^ ]+) aim=([^\n]+)\.',block)
        if not head: continue
        serial,tick,hand,clamped=map(int,head.groups()[:4])
        if serial not in submitted: continue
        grip,aim=(np.fromstring(v,sep=',') for v in head.groups()[4:])
        view=re.search(r'OpenXR mount stream view: pose=([^ ]+) fov=([^\n]+)\.',block)
        matrices={name:np.fromstring(value,sep=',').reshape(4,4,order='F') for name,value in re.findall(
            r'OpenXR mount stream (weapon|hand|projection): values=([^\n]+)\.',block)}
        if not view or len(matrices)!=3 or hand not in pivots: continue
        pose,fov=(np.fromstring(v,sep=',') for v in view.groups())
        palm=points['tag_palm_'+('right' if hand else 'left')]
        d=points['tag_muzzle']-palm
        muzzle=grip[4:]+rotation(aim)@np.array((d[1],d[2],-d[0]))/64
        errors=[]
        for name,tag,point in (('weapon',palm,grip[4:]),('weapon',points['tag_muzzle'],muzzle),('hand',pivots[hand],grip[4:])):
            clip=matrices['projection']@matrices[name]@np.r_[tag,1]
            expected=_project(rotation(pose[:4]).T@(point-pose[4:]),fov)
            errors.append(float(np.max(np.abs(clip[:2]/clip[3]-expected))))
        prior_errors=[]
        if rows and rows[-1]['hand']==hand:
            old=np.array(rows[-1]['raw_grip'])
            prior_expected=_project(rotation(pose[:4]).T@(old[4:]-pose[4:]),fov)
            for name,tag in (('hand',pivots[hand]),('weapon',palm)):
                clip=matrices['projection']@matrices[name]@np.r_[tag,1]
                prior_errors.append(float(np.max(np.abs(clip[:2]/clip[3]-prior_expected))))
        rows.append({'serial':serial,'native_tick':tick,'hand':hand,'clamped':bool(clamped),
                     'raw_grip':grip.tolist(),'projection_error':max(errors),'previous_pose_errors':prior_errors})
    pairs=[]
    for before,after in zip(rows,rows[1:]):
        if before['native_tick']==after['native_tick'] and before['hand']==after['hand']:
            delta=float(np.linalg.norm(np.array(before['raw_grip'][4:])-after['raw_grip'][4:]))
            if delta>.001:
                pairs.append({'serials':[before['serial'],after['serial']], 'native_tick':after['native_tick'],
                              'raw_move_m':delta,'projection_errors':[before['projection_error'],after['projection_error']],
                              'previous_pose_errors':after['previous_pose_errors']})
    distinguishing=[p for p in pairs if len(p['previous_pose_errors'])==2 and min(p['previous_pose_errors'])>.008]
    return {'subtick_qualification':{'passed':bool(distinguishing) and all(max(p['projection_errors'])<.008 for p in distinguishing),
                                      'required_for_full_acceptance':True},
            'checks':{'all_streamed_unclamped_matrices_match_current_pose':bool(rows) and all(
                          not r['clamped'] and r['projection_error']<.008 for r in rows)},
            'frame_count':len(rows),'maximum_projection_error':max((r['projection_error'] for r in rows),default=None),
            'unchanged_tick_pairs':pairs}


def crosshair(root, text, shot):
    """Mounted static reticle: real native ray, physical eyes, pixels and depth."""
    from smoke_crosshair import raster, NUMBER
    from smoke_hand_model import world_from_eye, expected_projection
    matrices={int(i):np.fromstring(m,sep=',').reshape(4,4,order='F') for i,m in re.findall(
        r'OpenXR crosshair matrix: eye=(\d) values=([^\n]+)\.',text)}
    hit=list(map(int,re.findall(r'OpenXR world crosshair: start=(-?\d+),(-?\d+),(-?\d+) hit=(-?\d+),(-?\d+),(-?\d+)',text)[-1]))
    point=np.array(list(map(float,re.findall(r'point=('+NUMBER+'),('+NUMBER+'),('+NUMBER+r')\.',text)[-1])))
    anchor=np.array(list(map(float,re.findall(r'OpenXR crosshair anchor: pixel=('+NUMBER+'),('+NUMBER+r')\.',text)[-1])))
    eyes=np.array(list(map(int,re.findall(r'OpenXR aim eye positions: left=(-?\d+),(-?\d+),(-?\d+) right=(-?\d+),(-?\d+),(-?\d+)',text)[-1]))).reshape(2,3)
    angles=list(map(float,re.findall(r'leftYaw=('+NUMBER+') leftPitch=('+NUMBER+') rightYaw=('+NUMBER+') rightPitch=('+NUMBER+r')\.',text)[-1]))
    rolls=list(map(float,re.findall(r'OpenXR aim eye roll: left=('+NUMBER+') right=('+NUMBER+r')\.',text)[-1]))
    ui=np.asarray(Image.open(root/'crosshair-ui.ppm')); alpha=np.asarray(Image.open(root/'crosshair-coverage.pgm'))
    errors=[];projection=[];changed=[];depths=[]
    for eye,name in enumerate(('left','right')):
        before=np.asarray(Image.open(root/f'crosshair-before-{name}.ppm'))
        after=np.asarray(Image.open(root/f'crosshair-{name}.ppm'))
        raw=(root/f'crosshair-before-{name}-depth.bin').read_bytes()
        depth=np.flipud(np.frombuffer(raw,dtype=np.uint32).reshape(before.shape[:2]))/4294967295
        expected,_,_=raster(before,ui,alpha,depth,matrices[eye])
        errors.append(int(np.max(np.abs(expected.astype(int)-after.astype(int)))))
        changed.append(int(np.count_nonzero(np.any(before!=after,axis=2))))
        depths.append(raw==(root/f'crosshair-{name}-depth.bin').read_bytes())
        clip=matrices[eye]@np.array((2*anchor[0]/ui.shape[1]-1,1-2*anchor[1]/ui.shape[0],0,1))
        fov=np.fromstring(re.findall(r'OpenXR weapon view: eye='+str(eye)+r'.*? fov=([^\n]+)\.',text)[-1],sep=',')
        physical=expected_projection(world_from_eye(*angles[eye*2:eye*2+2],rolls[eye]),eyes[eye],point,fov)
        projection.append(float(np.max(np.abs(clip[:2]/clip[3]-physical))))
    return {'checks':{
        'mounted_static_reticle_matches_native_server_origin_and_hit':hit==[shot[k] for k in ('x','y','z','hitx','hity','hitz')],
        'mounted_crosshair_pixels_match_depth_tested_projection':max(errors)<=2,
        'mounted_crosshair_preserves_world_depth':all(depths),
        'mounted_crosshair_visible_both_eyes':min(changed)>0,
        'mounted_crosshair_physical_projection_matches':max(projection)<2e-5},
        'pixel_errors':errors,'projection_errors':projection,'changed_pixels':changed,'hit':hit}
