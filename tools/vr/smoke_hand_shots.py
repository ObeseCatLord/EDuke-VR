#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual negotiated native-server hand-origin/full-vector RPG proof.

Uses owned processes/windows and a private Monado remote runtime. A generated
portal map plus read-only native CON observations qualify real projectiles,
sectors and impacts, not injected game shots/packets or only pose telemetry.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
import tempfile
import numpy as np
from PIL import Image
from monado_remote import Remote
from smoke_aim import orientation,players,shots,impacts
from smoke_weapon import rotation,warp,FLOAT
from smoke_actions import Observer
from smoke_actions_multiplayer import wait_for_join_barrier,client_player_index
from smoke_multiplayer import X11,setup_lab,stop
from stereo_fixture import sector,wall,sprite,PHEIGHT

HAND=re.compile(r'addlog vrhand_(player|sector|autoaim|x|y|z|pyoff)(?: \(player \d+\))? = (-?\d+)')
AUTH=re.compile(r'VR authoritative RPG: player=(\d+) origin=(-?\d+),(-?\d+),(-?\d+) sector=(-?\d+) clamped=(\d) angle=(-?\d+) speed=(-?\d+) zvel=(-?\d+)')

def metadata(text,player):
    result=[];row={}
    for key,val in HAND.findall(text):
        if key=='player':row={}
        row[key]=int(val)
        if key=='pyoff' and row['player']==player:result.append(row)
    return result


def room(closed=False,damage=False):
    a=bytearray(sector(0,4));b=bytearray(sector(4,4))
    for s in (a,b):struct.pack_into('<i',s,4,-32768)
    walls=[wall(0,0,1),wall(1152,0,2),wall(1152,8192,3),wall(0,8192,0),
           wall(1152,0,5),wall(8192,0,6),wall(8192,8192,7),wall(1152,8192,4)]
    if not closed:
        walls[1]=wall(1152,0,2,nextwall=7,nextsector=1)
        walls[7]=wall(1152,8192,4,nextwall=1,nextsector=0)
    starts=[sprite(512,1024+i*1536,0,0,tile=1405,angle=0) for i in range(4)]
    if damage:starts.append(sprite(4096,4790,0,1,tile=1680,angle=1024))
    return struct.pack('<iiiihhh',7,1024,4096,-PHEIGHT,0,0,2)+a+b+struct.pack('<h',8)+b''.join(walls)+struct.pack('<h',len(starts))+b''.join(starts)


def card_evidence(lab,meta,authority,hand):
    text=(lab/'client.log').read_text(errors='replace')
    model=re.findall(r'OpenXR weapon card: visible=(\d) pos=('+FLOAT+','+FLOAT+','+FLOAT+r') quat=('+FLOAT+','+FLOAT+','+FLOAT+','+FLOAT+r')',text)[-1]
    views=re.findall(r'OpenXR weapon view: eye=(\d) pos=('+FLOAT+','+FLOAT+','+FLOAT+r') quat=('+FLOAT+','+FLOAT+','+FLOAT+','+FLOAT+r') fov=('+FLOAT+','+FLOAT+','+FLOAT+','+FLOAT+r')',text)[-2:]
    q=np.array([getattr(hand.pose.orientation,k) for k in ('x','y','z','w')])
    # This controlled fixture holds virtual body yaw/pitch at zero. Convert the
    # server's constrained world origin independently back to LOCAL metres.
    origin=np.array([(authority[2]-meta['y'])/384,-(authority[3]-meta['z']-meta['pyoff'])/6144,-(authority[1]-meta['x'])/384])
    expected=origin+rotation(q)@np.array([-.08,.24,-.15])
    actual=np.fromstring(model[1],sep=',')
    ui=np.array(Image.open(lab/'weapon-ui.ppm'));alpha=np.array(Image.open(lab/'weapon-coverage.pgm'))
    bits=int(re.findall(r'OpenXR overlay raster: subpixelBits=(\d+)',text)[-1])
    errors=[]
    for i,(_,vp,vq,fov) in enumerate(views):
        eye=('left','right')[i]
        before=np.array(Image.open(lab/f'weapon-before-{eye}.ppm'));after=np.array(Image.open(lab/f'weapon-{eye}.ppm'))
        predicted=warp(before,ui,alpha,[np.fromstring(v,sep=',') for v in (vp,vq,fov)],(expected,q),True,bits)
        errors.append(int(np.abs(after.astype(int)-predicted.astype(int)).max()))
    return {'actual_card_pose_matches_server_constrained_origin':bool(int(model[0])) and float(np.abs(actual-expected).max())<2e-5,
            'actual_both_eye_card_pixels_match_server_origin_projection':len(errors)==2 and max(errors)<=2,
            'card_preserves_world_depth':all((lab/f'weapon-before-{eye}-depth.bin').read_bytes()==(lab/f'weapon-{eye}-depth.bin').read_bytes() for eye in ('left','right'))},errors


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('binary','client-binary','grp','work-dir'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--display',default=':1');p.add_argument('--remote-port',type=int,required=True)
    p.add_argument('--port',type=int,default=24595)
    p.add_argument('--case',choices=('open','wall','glancing','steep','vertical','left','moved','invalid-reach','timeout','damage','autoaim','legacy-server','legacy-client','unnegotiated'),default='open')
    p.add_argument('--bad-packet',choices=('version','flags','direction','reach','size','channel','identity','capability'))
    a=p.parse_args();a.work_dir.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='hand-shot-',dir=a.work_dir.resolve()))
    server=client=None;client_stopped=False;logs=[];result={'passed':False};phase='startup'
    try:
        sl=setup_lab(root,'server',a.grp.resolve(),False);cl=setup_lab(root,'client',a.grp.resolve(),False)
        for lab in (sl,cl):
            for name in ('hand_test.con','aim_test.con','controller_test.con'):shutil.copyfile(Path(__file__).parent/'fixtures'/name,lab/name)
            if a.case=='autoaim':
                script=lab/'hand_test.con';script.write_text(script.read_text().replace('setplayer[THISACTOR].auto_aim 0','setplayer[THISACTOR].auto_aim 1'))
            (lab/'hand.map').write_bytes(room(a.case in ('wall','glancing'),a.case in ('damage','autoaim')))
        env={k:v for k,v in os.environ.items() if not k.startswith('EDUKE32_XR')}
        env.update(DISPLAY=a.display,SDL_VIDEODRIVER='x11',SDL_AUDIODRIVER='dummy')
        se={k:v for k,v in env.items() if not k.startswith('XR_')}
        se['EDUKE32_XR_TEST_SHOTS']='1'
        ce=dict(env,EDUKE32_XR='1',EDUKE32_XR_SINGLE_PASS='1',EDUKE32_XR_UI='2',EDUKE32_XR_AIM='left' if a.case=='left' else 'right',
                EDUKE32_XR_WEAPON='1',EDUKE32_XR_HAND_SHOTS='1',EDUKE32_XR_TEST_INPUT='1',EDUKE32_XR_TEST_SHOTS='1',
                EDUKE32_XR_WEAPON_OUTPUT=str(cl/'weapon'),EDUKE32_XR_HUD_OUTPUT=str(cl/'hud'),EDUKE32_XR_WORLD_OUTPUT=str(cl/'world'))
        if a.case=='unnegotiated':a.bad_packet='capability'
        if a.bad_packet:ce['EDUKE32_XR_TEST_BAD_SHOT']=a.bad_packet
        log=(sl/'server.log').open('w');logs.append(log)
        server=subprocess.Popen([str(a.binary.resolve()),'-usecwd','-nosetup','-noautoload','-dedicated','-port',str(a.port),'-map','hand.map','-x','hand_test.con'],cwd=sl,env=se,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        so=Observer(server,sl/'server.log');so.wait(lambda t:'Multiplayer server initialized.' in t)
        with Remote(a.remote_port) as remote:
            hand=remote.packet.left if a.case=='left' else remote.packet.right
            hand.pose.position.x=-.2 if a.case=='left' else .2
            hand.pose.position.y=1.3;hand.pose.position.z=-.5
            if a.case=='glancing':hand.pose.position.x=1.5;hand.pose.position.z=-.40625
            remote.send()
            log=(cl/'client.log').open('w');logs.append(log)
            client=subprocess.Popen([str(a.client_binary.resolve()),'-usecwd','-nosetup','-noautoload','-nologo','-ns','-nm','-connect',f'127.0.0.1:{a.port}','-x','hand_test.con'],cwd=cl,env=ce,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
            co=Observer(client,cl/'client.log')
            phase='native join'
            if a.case=='legacy-client':
                co.wait(lambda t:'Multiplayer client level synchronization complete.' in t,timeout=20);co.pause(1.6)
                x=X11(a.display);window,_=x.owned_window(client.pid)
                if client_player_index(co.text()) is None:
                    if not window:raise RuntimeError('owned native window missing')
                    x.press(window,'Escape',.06,True)
                co.wait(lambda t:client_player_index(t) not in (None,0),timeout=10)
                player=client_player_index(co.text())
            else:
                joined=wait_for_join_barrier(X11(a.display),client,cl/'client.log',so);player=joined['server_player']
            so.wait(lambda t:len(players(t,player))>20)
            if a.case not in ('legacy-server','legacy-client','unnegotiated'):co.wait(lambda t:'VR native hand-shot capability: acknowledged' in t)
            if a.case=='legacy-client':
                phase='legacy native client gameplay'
                window,_=x.owned_window(client.pid);before=players(so.text(),player)[-1]
                x.press(window,'w',.65,True);so.pause(.2)
                moved=players(so.text(),player)[-1]
                off=len(so.text());x.press(window,'Control_R',.3,True)
                so.wait(lambda t:bool(shots(t[off:],player)),timeout=5)
                fired=players(so.text(),player)[-1]
                checks={'legacy_native_join':player>0,'legacy_native_updates_move_server_player':moved['x']>before['x']+100,
                        'legacy_native_firing_and_ammo':fired['ammo']<before['ammo'],
                        'legacy_client_has_no_VR_capability':'VR native hand-shot capability: accepted' not in so.text(),
                        'legacy_native_shot_keeps_body_origin':'VR authoritative RPG:' not in so.text()}
                result={'passed':all(checks.values()),'case':a.case,'checks':checks,'native_RPG':shots(so.text()[off:],player)[0]}
            else:
                phase='pose and projection'
                yaw,pitch=12,0 if a.case in ('damage','autoaim') else 8
                if a.case=='steep':pitch=75
                if a.case=='vertical':pitch=90
                hand.pose.orientation=orientation(yaw,pitch)
                remote.packet.head.center.orientation=orientation(-12,4)
                remote.send();co.pause(.5)
                co.wait(lambda t:'OpenXR world oracle: 60 frames' in t and 'OpenXR HUD presentation: 60 frames' in t,timeout=20)
                expected_offset=[round(-hand.pose.position.z*384),round(hand.pose.position.x*384),round((1.6-hand.pose.position.y)*6144)]
                checks={'native_join_assigned_actual_player':player>0,
                        'actual_60_stereo_world_HUD_submissions':all((cl/f'hud-{eye}.ppm').is_file() for eye in ('left','right')) and (cl/'hud-left.ppm').read_bytes()!=(cl/'hud-right.ppm').read_bytes(),
                        'core_validation_active':'Core Validation output type:' in co.text(),
                        'core_validation_no_warning_or_error':not re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)',co.text())}
                if a.case in ('legacy-server','unnegotiated'):
                    phase='legacy server suppression'
                    offset=len(so.text());before=players(so.text(),player)[-1]
                    remote.packet.right.trigger_value=1;remote.packet.right.trigger_click=True;remote.packet.left.thumbstick.y=.7;remote.send();so.pause(1.2)
                    remote.packet.right.trigger_value=0;remote.packet.right.trigger_click=False;remote.packet.left.thumbstick.y=0;remote.send()
                    after=players(so.text(),player)[-1]
                    checks.update(legacy_peer_did_not_ack='capability: acknowledged' not in co.text(),unsupported_hand_mode_does_not_silently_body_fire=not shots(so.text()[offset:],player) and after['ammo']==before['ammo'],native_movement_continues_without_capability=after['x']>before['x']+100)
                    if a.case=='unnegotiated':checks['unnegotiated_actual_extension_rejected']='reason=capability.' in so.text()
                    result={'passed':all(checks.values()),'case':a.case,'checks':checks}
                else:
                    checks['native_server_negotiated_hand_extension']='VR native hand-shot capability: accepted' in so.text()
                    def fire():
                        off=len(so.text());remote.packet.right.trigger_value=1;remote.packet.right.trigger_click=True;remote.send()
                        text=so.wait(lambda t:bool(shots(t[off:],player)),timeout=4)
                        remote.packet.right.trigger_value=0;remote.packet.right.trigger_click=False;remote.send()
                        co.pause(.1);text=so.text()[off:]
                        shot=shots(text,player)[0];meta=metadata(text,player)[0]
                        authority=[list(map(int,v)) for v in AUTH.findall(text) if int(v[0])==player][0]
                        return off,shot,meta,authority
                    if a.bad_packet:
                        expected_reason={'size':'size','channel':'channel','identity':'identity'}.get(a.bad_packet,'payload')
                        checks['malformed_actual_ENet_update_rejected']=f'VR update rejected: player={player} reason={expected_reason}.' in so.text() and f'VR negative update fixture: {a.bad_packet}.' in co.text()
                        checks['malformed_update_did_not_move_native_authority']=all(row['x']!=30000 for row in players(so.text(),player))
                    target_before=None
                    if a.case in ('damage','autoaim'):target_before=int(re.findall(r'addlog vrtarget_health[^=\n]*= (-?\d+)',so.text())[-1])
                    phase='native RPG spawn'
                    off,shot,meta,authority=fire()
                    predicted=[meta['x']+expected_offset[0],meta['y']+expected_offset[1],meta['z']+meta['pyoff']+expected_offset[2]]
                    expected_speed=round(644*math.cos(math.radians(pitch)))
                    expected_zvel=round(-644*16*math.sin(math.radians(pitch)))
                    checks.update(actual_RPG_origin_matches_resolved_server_origin=[shot[k] for k in ('x','y','z')]==authority[1:4],
                                  actual_RPG_sector_matches_resolved_sector=meta['sector']==authority[4],
                                  actual_full_vector_horizontal_speed=abs(shot['speed']-expected_speed)<=1,
                                  actual_full_vector_vertical_speed=abs(shot['zvel']-expected_zvel)<=1,
                                  actual_full_vector_yaw=pitch==90 or abs(shot['angle']-round(yaw*1024/180))<=1)
                    if a.case=='autoaim':
                        del checks['actual_full_vector_vertical_speed']
                        checks['native_autoaim_applies_real_target_correction']=meta['autoaim']==1 and shot['zvel']!=0
                        checks['native_autoaim_velocity_is_normalized']=abs(math.hypot(shot['speed'],shot['zvel']/16)-644)<1
                    else:checks['free_aim_preference_held_at_shot_boundary']=meta['autoaim']==0
                    if a.case in ('wall','glancing'):
                        checks['blocked_hand_is_clamped_before_wall']=authority[5]==1 and authority[1]<=1136 and authority[4]==0
                    else:
                        checks['actual_hand_origin_crosses_open_portal']=authority[4]==1 and authority[1]>1152
                        checks['actual_native_spawn_matches_independent_hand_transform']=max(abs(predicted[i]-shot[k]) for i,k in enumerate(('x','y','z')))<=1
                    phase='native RPG impact'
                    so.wait(lambda t:bool(impacts(t[off:])),timeout=6)
                    impact=impacts(so.text()[off:])[0]
                    hitrow=None
                    if a.case in ('wall','glancing'):checks['actual_RPG_hits_intervening_wall']=impact['x']<1152 and impact['x']>1080
                    elif a.case in ('damage','autoaim'):
                        hitrow={k:int(v) for k,v in re.findall(r'addlog vrhit_(player|kind|sector|ceiling|oldx|oldy|x|y|z)[^=\n]*= (-?\d+)',so.text()[off:])}
                        checks['actual_RPG_collides_with_native_enemy']=(hitrow.get('kind',0)&49152)==49152 and (hitrow.get('kind',0)&16383)==4
                        def killed(text):
                            values=re.findall(r'addlog vrtarget_health[^=\n]*= (-?\d+)',text)
                            return bool(values) and int(values[-1])<=0
                        so.wait(killed,timeout=3);co.wait(killed,timeout=4)
                        checks['native_server_enemy_damage_and_death']=target_before>0 and killed(so.text())
                        checks['client_receives_enemy_damage_and_death']=killed(co.text())
                    elif a.case in ('steep','vertical'):
                        hitfields=re.findall(r'addlog vrhit_(player|kind|sector|ceiling|oldx|oldy|x|y|z)(?: \(player \d+\))? = (-?\d+)',so.text()[off:])
                        hitrow={k:int(v) for k,v in hitfields}
                        checks['native_collision_is_ceiling_not_a_wall']=(hitrow.get('kind',0)&49152)==16384 and shot['zvel']<0
                        checks['actual_RPG_reaches_ceiling_from_hand']=abs(impact['z']+32768)<=abs(shot['zvel'])/2+512 and (a.case!='vertical' or (hitrow['oldx']==shot['x'] and hitrow['oldy']==shot['y']))
                    else:checks['actual_RPG_reaches_far_wall_from_neighbor_sector']=impact['x']>8000
                    card_errors=None
                    if a.case not in ('steep','vertical'):
                        card_checks,card_errors=card_evidence(cl,meta,authority,hand);checks.update(card_checks)
                    replicated=None
                    if a.case in ('open','left','moved','invalid-reach','timeout'):
                        co.wait(lambda t:'addlog vrnet_sector' in t,timeout=4)
                        replicated={k:int(v) for k,v in re.findall(r'addlog vrnet_(angle|speed|zvel|sector)[^=\n]*= (-?\d+)',co.text())}
                        checks['client_world_receives_authoritative_RPG']=all(replicated[k]==shot[{'angle':'angle','speed':'speed','zvel':'zvel'}[k]] for k in ('angle','speed','zvel')) and replicated['sector']==1
                    second=None
                    if a.case=='moved':
                        phase='independent hand translation'
                        so.pause(.65);hand.pose.position.x=-.2;hand.pose.position.y=1.1;hand.pose.position.z=-.8;remote.send();so.pause(.35)
                        _,second,meta2,auth2=fire()
                        predicted2=[meta2['x']+round(.8*384),meta2['y']+round(-.2*384),meta2['z']+meta2['pyoff']+round(.5*6144)]
                        checks['second_actual_shot_follows_independent_hand_translation']=max(abs(predicted2[i]-second[k]) for i,k in enumerate(('x','y','z')))<=1 and second['y']<shot['y']-100 and second['x']>shot['x']+100
                    if a.case=='timeout':
                        phase='owned client packet timeout'
                        so.pause(.65);_,_,_,_=fire();so.pause(.65)
                        remote.packet.right.trigger_value=1;remote.packet.right.trigger_click=True;remote.send()
                        so.wait(lambda t:len(shots(t,player))>=3,timeout=4)
                        os.kill(client.pid,signal.SIGSTOP);client_stopped=True
                        so.pause(.4);offset=len(so.text());ammo=players(so.text(),player)[-1]['ammo'];so.pause(.8)
                        checks['pose_expiry_stops_repeated_native_fire']=not shots(so.text()[offset:],player) and players(so.text(),player)[-1]['ammo']==ammo
                        os.kill(client.pid,signal.SIGCONT);client_stopped=False
                        offset=len(so.text());so.pause(.8)
                        checks['timeout_recovery_held_trigger_requires_release']=not shots(so.text()[offset:],player)
                        remote.packet.right.trigger_value=0;remote.packet.right.trigger_click=False;remote.send();so.pause(.25)
                        _,second,_,_=fire();checks['repress_after_timeout_fires']=True
                    if a.case=='invalid-reach':
                        phase='out of envelope recovery'
                        so.pause(.65);hand.pose.position.z=-3;remote.send();so.pause(.3);offset=len(so.text())
                        remote.packet.right.trigger_value=1;remote.packet.right.trigger_click=True;remote.send();so.pause(.5)
                        hand.pose.position.z=-.5;remote.send();so.pause(.7)
                        checks['invalid_reach_and_held_recovery_do_not_fire']=not shots(so.text()[offset:],player)
                        remote.packet.right.trigger_value=0;remote.packet.right.trigger_click=False;remote.send();so.pause(.25)
                        _,second,_,_=fire();checks['new_press_after_invalid_reach_fires']=True
                    result={'passed':all(checks.values()),'case':a.case,'checks':checks,'actual_RPG':shot,'player_at_spawn':meta,
                            'server_resolved_origin':authority[1:4],'server_resolved_sector':authority[4],'server_clamped':bool(authority[5]),
                            'independent_unclamped_origin':predicted,'actual_impact':impact,'native_collision':hitrow,'second_RPG':second,'replicated_RPG':replicated,'card_projection_max_channel_error':card_errors}
    except Exception as error:result={'passed':False,'phase':phase,'case':a.case,'error':str(error)}
    finally:
        if client_stopped and client and client.poll() is None:os.kill(client.pid,signal.SIGCONT)
        stop(client);stop(server)
        for log in logs:log.close()
    result['evidence_directory']=str(root);(root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
