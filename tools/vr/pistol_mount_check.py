#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independent raw-pose/asset check at AA's actual native firing boundary."""
import math
import re
import struct
import numpy as np
from smoke_weapon import rotation
from smoke_hitscan import RAY, KEYS

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
    """Measure same-frame gun/hand separation; do not impose a fake fit limit."""
    palm=tags(model)['tag_palm_right']; rows=[]
    mapping=np.array(((0,0,1),(-1,0,0),(0,-1,0)))
    canonical=np.array(((0,1,0),(0,0,1),(-1,0,0)))
    for block in text.split('OpenXR floating hands:')[1:]:
        header=re.match(r' serial=(\d+) state=(\d+) mask=(\d+) left=\d+ right=\d+ capture=(\d+)\.',block)
        if not header: continue
        serial,state,mask,captured=map(int,header.groups())
        if not captured or not mask&2: continue
        pose=re.search(r'OpenXR pistol mount pose: eye=0 hand=1 grip=([^ ]+) aim=([^\n]+)\.',block)
        hand=re.search(r'OpenXR floating hand: serial='+str(serial)+r' hand=1 model=\d+ frame=\d+ root=[^ ]+ pivot=([^ ]+) pose=([^\n]+)\.',block)
        if not pose or not hand: continue
        sampled,aim=(np.fromstring(value,sep=',') for value in pose.groups())
        pivot,current=(np.fromstring(value,sep=',') for value in hand.groups())
        expected=(rotation(current[:4])@mapping).T@rotation(aim)@canonical
        distances=[]; axis_errors=[]
        for eye in (0,1):
            weapon=re.search(r'OpenXR hand model matrix: eye='+str(eye)+r' values=([^\n]+)\.',block)
            grip=re.search(r'OpenXR floating matrix: serial='+str(serial)+r' hand=1 eye='+str(eye)+r' values=([^\n]+)\.',block)
            if not weapon or not grip: continue
            w=np.fromstring(weapon[1],sep=',').reshape(4,4,order='F')
            h=np.fromstring(grip[1],sep=',').reshape(4,4,order='F')
            relative=np.linalg.solve(h,w)
            contact=(relative@np.array([*palm,1]))[:3]
            distances.append(float(np.linalg.norm(contact-pivot)*1000/64))
            axis_errors.append(float(np.max(np.abs(relative[:3,:3]-expected))))
        rows.append({'serial':serial,'state':state,'sampled_aim':aim.tolist(),
                     'visible_palm_separation_mm':distances,'relative_axis_errors':axis_errors,
                     'sampled_to_current_grip_mm':float(np.linalg.norm(sampled-current[4:])*1000)})
    changing=[r for r in rows if r['state'] in (6,7)]
    return {'checks':{'mount_motion_measured_multiple_frames':len(rows)>=3,
                      'mount_roll_changed_in_both_sampled_poses':len(changing)==2 and
                        not np.allclose(changing[0]['sampled_aim'],changing[1]['sampled_aim']),
                      'mounted_basis_uses_its_sampled_roll':bool(changing) and all(len(r['relative_axis_errors'])==2 and
                        max(r['relative_axis_errors'])<.0015 for r in changing)},
            'frames':rows,'maximum_visible_palm_separation_mm':max((max(r['visible_palm_separation_mm']) for r in rows if r['visible_palm_separation_mm']),default=None)}
