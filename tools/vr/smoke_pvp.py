#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Private real native/XR PvP: damage, frag/death, Use respawn and recovery."""
import argparse,json,math,os,re,shutil,subprocess,tempfile
from pathlib import Path
from PIL import Image
import numpy as np
from monado_remote import Remote
from smoke_actions import Observer
from smoke_actions_multiplayer import wait_for_join_barrier,client_player_index
from smoke_aim import orientation
from smoke_hand_shots import room
from smoke_hitscan import rays
from smoke_multiplayer import X11,setup_lab,stop

FIELDS=('player','index','health','dead','frag','deaths','self','ammo','x','y','z','oldx','oldy','oldz','sector','bits','gm','spawns')
def samples(text,player):
    rows=[];row={}
    for key,value in re.findall(r'addlog vrcombat_('+ '|'.join(FIELDS)+r')\b[^=\n]*= (-?\d+)',text):
        if key=='player':row={}
        row[key]=int(value)
        if key=='spawns' and row.get('player')==player:rows.append(row)
    return rows

def latest(observer,player):
    rows=samples(observer.text(),player)
    if not rows:raise RuntimeError('native combat player sample missing')
    return rows[-1]

def spawn_payloads(text):
    return [list(map(int,r)) for r in re.findall(r'Native spawn payload: player=(\d+) pos=(-?\d+),(-?\d+),(-?\d+) old=(-?\d+),(-?\d+),(-?\d+) packet=(-?\d+),(-?\d+),(-?\d+) packetOld=(-?\d+),(-?\d+),(-?\d+)\.',text)]

def scores_stable(rows,killer):
    expected=(1,0,0) if killer else (0,1,0)
    return bool(rows) and all((r['frag'],r['deaths'],r['self'])==expected for r in rows)

def held_fire_suppressed(rows,shots):
    # Native pickups may increase ammo after reset. A shot, fire input or any
    # observed consumption during the held interval is still a failure.
    return bool(rows) and not shots and all(not (r['bits']&4) for r in rows) and all(b['ammo']>=a['ammo'] for a,b in zip(rows,rows[1:]))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('binary','client-binary','grp','work-dir'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--display',default=':1');p.add_argument('--remote-port',type=int,required=True);p.add_argument('--port',type=int,default=24600)
    p.add_argument('--case',choices=('xr-shooter','xr-victim'),default='xr-shooter')
    a=p.parse_args()
    if os.environ.get('EDUKE32_TEST_PRIVATE_WINDOW')!='1':p.error('private testing requires EDUKE32_TEST_PRIVATE_WINDOW=1')
    a.work_dir.mkdir(parents=True,exist_ok=True);root=Path(tempfile.mkdtemp(prefix='pvp-',dir=a.work_dir.resolve()));server=peer1=xr=None;logs=[];phase='setup';result={'passed':False}
    victim=1 if a.case=='xr-shooter' else 2;killer=3-victim;victim_vr=victim==2
    try:
        labs={role:setup_lab(root,role,a.grp.resolve(),False) for role in ('server','peer1','xr')}
        for role,lab in labs.items():
            for n in ('controller_test.con','pvp_test.con'):shutil.copyfile(Path(__file__).parent/'fixtures'/n,lab/n)
            f=lab/'pvp_test.con';f.write_text(f.read_text().replace('gamevar vrcombat_victim 1 0',f'gamevar vrcombat_victim {victim} 0'))
            (lab/'hand.map').write_bytes(room())
            with (lab/'eduke32.cfg').open('a') as f:f.write('\n[Comm Setup]\nPlayerName = "'+{'server':'Server','peer1':'FlatTest','xr':'VRPeer2'}[role]+'"\n')
        env={k:v for k,v in os.environ.items() if not k.startswith('EDUKE32_XR')};env.update(DISPLAY=a.display,SDL_VIDEODRIVER='x11',SDL_AUDIODRIVER='dummy')
        native={k:v for k,v in env.items() if not k.startswith('XR_')};native.update(EDUKE32_XR_TEST_SHOTS='1',EDUKE32_XR_TEST_PVP='1')
        ce=dict(env,EDUKE32_XR='1',EDUKE32_XR_SINGLE_PASS='1',EDUKE32_XR_UI='2',EDUKE32_XR_AIM='right',EDUKE32_XR_WEAPON='1',EDUKE32_XR_HAND_SHOTS='1',EDUKE32_XR_TEST_INPUT='1',EDUKE32_XR_TEST_SHOTS='1',EDUKE32_XR_TEST_PVP='1',EDUKE32_XR_WORLD_OUTPUT=str(labs['xr']/'world'),EDUKE32_XR_HUD_OUTPUT=str(labs['xr']/'hud'))
        def launch(role,binary,args,environment):
            f=(labs[role]/'game.log').open('w');logs.append(f)
            proc=subprocess.Popen([str(binary.resolve()),'-usecwd','-nosetup','-noautoload','-nologo','-ns','-nm',*args,'-x','pvp_test.con'],cwd=labs[role],env=environment,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT)
            return proc,Observer(proc,labs[role]/'game.log')
        server,so=launch('server',a.binary,['-dedicated','-port',str(a.port),'-c1','-map','hand.map'],native);so.wait(lambda t:'Multiplayer server initialized.' in t)
        # The ENet socket is opened before game initialization. Observe actual
        # native gameplay ticks instead of connecting into the startup sequence.
        so.wait(lambda t:len(samples(t,0))>10 and all(r['gm']&4 for r in samples(t,0)[-3:]),timeout=15)
        x11=X11(a.display)
        peer1,fo=launch('peer1',a.binary,['-connect',f'127.0.0.1:{a.port}'],native)
        phase='peer1 join';fo.wait(lambda t:'Multiplayer client level synchronization complete.' in t,timeout=20);fo.pause(1.5)
        fo.wait(lambda t:'addlog vrcombat_mode' in t)
        peer1_window,_=x11.owned_window(peer1.pid)
        if not peer1_window:raise RuntimeError('owned private peer1 window unavailable')
        mode=int(re.findall(r'addlog vrcombat_mode[^=\n]*= (\d+)',fo.text())[-1])
        if mode&1:x11.press(peer1_window,'Escape',.06,True)
        so.wait(lambda t:len(samples(t,1))>10);fo.wait(lambda t:client_player_index(t)==1)
        with Remote(a.remote_port) as remote:
            hand=remote.packet.right;hand.pose.position.x=.2;hand.pose.position.y=1.3;hand.pose.position.z=-.5;remote.send()
            xr,co=launch('xr',a.client_binary,['-connect',f'127.0.0.1:{a.port}'],ce)
            phase='XR join';player=wait_for_join_barrier(x11,xr,labs['xr']/'game.log',so)['server_player']
            if player!=2:raise RuntimeError('controlled second peer was not actual player2')
            yaw=math.degrees(math.atan2(-77,4096-1216)) if killer==2 else 90
            hand.pose.orientation=orientation(yaw,0);remote.packet.head.center.orientation=orientation(0,0);remote.send()
            co.wait(lambda t:'OpenXR world oracle: 60 frames' in t and 'OpenXR HUD presentation: 60 frames' in t,timeout=20);so.pause(.25)
            def isolation():
                states={}
                for name,process in (('peer1',peer1),('XR',xr),('server',server)):
                    window,_=x11.owned_window(process.pid)
                    states[name]=None if window is None else x11.window_visibility(window)
                return all(v is None or v['unmapped'] and not v['has_desktop_focus'] for v in states.values()),states
            private,states=isolation()
            initial={role:{str(i):latest(o,i) for i in (1,2)} for role,o in (('server',so),('peer1',fo),('xr',co))}
            checks={'two_real_client_indices':player==2 and client_player_index(fo.text())==1,'private_unmapped_no_focus':private,'real_60_stereo_world_HUD_frames':(labs['xr']/'hud-left.ppm').read_bytes()!=(labs['xr']/'hud-right.ppm').read_bytes(),'core_validation_active':'Core Validation output type:' in co.text(),'core_validation_clean':not re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)',co.text()),'native_initial_health':all(initial[role][str(victim)]['health']==100 for role in initial)}
            def control(player,kind,held):
                target=remote if player==2 else None
                if target is None:
                    x11.send_event_key(peer1_window,{'fire':'Control_R','use':'e','move':'w'}[kind],held)
                elif kind=='move':target.packet.left.thumbstick.y=.7 if held else 0;target.send()
                else:
                    h=target.packet.right if kind=='fire' else target.packet.left
                    h.trigger_value=1 if held else 0;h.trigger_click=held;target.send()
            screenshots={}
            def screenshot(name,process,observer,lab):
                before=set(lab.glob('screenshots/duke[0-9][0-9][0-9][0-9].*'));window,_=x11.owned_window(process.pid)
                if not window:raise RuntimeError('private screenshot window missing')
                offset=len(observer.text())
                # Hold the owned-window native key until it is consumed.
                # A fixed 60ms tap can begin/end between slow rendered frames.
                x11.send_event_key(window,'F12',True)
                try:
                    observer.wait(lambda t:bool(set(lab.glob('screenshots/duke[0-9][0-9][0-9][0-9].*'))-before),timeout=8)
                    path=next(iter(set(lab.glob('screenshots/duke[0-9][0-9][0-9][0-9].*'))-before))
                    # Receipt follows fclose, not just file creation.
                    observer.wait(lambda t:f'Saved screenshot to {path.relative_to(lab)}' in t[offset:],timeout=8)
                finally:
                    x11.send_event_key(window,'F12',False)
                im=Image.open(path);im.load();im.save(root/(name+'.png'))
                screenshots[name]=bool(np.asarray(im).max()>np.asarray(im).min())
            phase='native player damage';offset=len(so.text());first_health=latest(so,victim)['health']
            control(killer,'fire',True)
            so.wait(lambda t:bool(samples(t[offset:],victim)) and samples(t[offset:],victim)[-1]['health']<first_health,timeout=6)
            damaged={role:latest(o,victim) for role,o in (('server',so),('peer1',fo),('xr',co))}
            phase='native death and frag';so.wait(lambda t:latest(so,victim)['health']==0 and latest(so,victim)['dead']!=0,timeout=18)
            control(killer,'fire',False)
            for observer in (fo,co):observer.wait(lambda t:samples(t,victim)[-1]['health']==0 and samples(t,victim)[-1]['dead']!=0,timeout=5)
            so.pause(.3)
            killed={role:{str(i):latest(o,i) for i in (1,2)} for role,o in (('server',so),('peer1',fo),('xr',co))}
            score_offsets={role:len(o.text()) for role,o in (('server',so),('peer1',fo),('xr',co))}
            checks.update(native_actual_target_damaged=damaged['server']['health']<100,native_death_replicates=all(killed[role][str(victim)]['health']==0 and killed[role][str(victim)]['dead'] for role in killed),killer_frag_and_victim_death_converge=all(killed[role][str(killer)]['frag']==1 and killed[role][str(victim)]['deaths']==1 for role in killed),no_self_frag=all(killed[role][str(killer)]['self']==killed[role][str(victim)]['self']==0 for role in killed))
            if killer==2:
                actual=rays(so.text()[offset:],killer);checks['native_hand_hits_actual_victim_sprite']=bool(actual) and actual[0]['sprite']==killed['server'][str(victim)]['index']
            def late_stereo(label):
                previous=list(map(int,re.findall(r'OpenXR PvP frame: submitted=(\d+) captured=1',co.text())))
                count=previous[-1] if previous else 60
                co.wait(lambda t:any(int(v)>count for v in re.findall(r'OpenXR PvP frame: submitted=(\d+) captured=1',t)),timeout=25)
                serial=int(re.findall(r'OpenXR PvP frame: submitted=(\d+) captured=1',co.text())[-1])
                paths=[labs['xr']/f'hud-{serial}-{eye}.ppm' for eye in ('left','right')]
                images=[Image.open(p) for p in paths]
                for im in images:im.load()
                stereo=Image.new('RGB',(images[0].width*2,images[0].height));stereo.paste(images[0],(0,0));stereo.paste(images[1],(images[0].width,0));stereo.save(root/(label+'-stereo.png'))
                return {'completed_HUD_frame':serial,'distinct_eyes':paths[0].read_bytes()!=paths[1].read_bytes()}
            phase='late actual XR death projection';death_stereo=late_stereo('death')
            phase='private native death screenshots';screenshot('peer1-death',peer1,fo,labs['peer1']);screenshot('xr-death',xr,co,labs['xr'])
            if victim_vr:
                control(victim,'fire',True);so.pause(.2)
            phase='native Use respawn';spawn_offset=len(so.text());before_spawn=latest(so,victim)['spawns']
            control(victim,'use',True)
            so.wait(lambda t:latest(so,victim)['health']>0 and latest(so,victim)['dead']==0 and latest(so,victim)['spawns']>before_spawn,timeout=6)
            control(victim,'use',False)
            for observer in (fo,co):observer.wait(lambda t:samples(t,victim)[-1]['health']>0 and samples(t,victim)[-1]['dead']==0,timeout=5)
            so.pause(.3);respawned={role:{str(i):latest(o,i) for i in (1,2)} for role,o in (('server',so),('peer1',fo),('xr',co))}
            checks.update(native_Use_respawns_actual_player=respawned['server'][str(victim)]['spawns']==before_spawn+1,respawn_health_and_scores_converge=all(respawned[r][str(victim)]['health']==100 and respawned[r][str(victim)]['dead']==0 and respawned[r][str(victim)]['deaths']==1 and respawned[r][str(killer)]['frag']==1 for r in respawned))
            if victim_vr:
                so.pause(1.2)
                live=[r for r in samples(so.text()[spawn_offset:],victim) if r['spawns']>before_spawn and r['dead']==0]
                checks['held_fire_does_not_restart_on_VR_respawn']=held_fire_suppressed(live,rays(so.text()[spawn_offset:],victim))
                control(victim,'fire',False);so.pause(.25)
            phase='post respawn native movement';start=latest(so,victim);other_start=latest(so,killer)
            control(victim,'move',True)
            so.pause(.6)
            control(victim,'move',False)
            so.pause(.2);moved=latest(so,victim)
            checks['respawned_client_controls_real_body']=math.hypot(moved['x']-start['x'],moved['y']-start['y'])>80
            other_end=latest(so,killer)
            checks['movement_isolated_to_selected_player']=(other_start['x'],other_start['y'])==(other_end['x'],other_end['y'])
            phase='post respawn native fire';ammo=latest(so,victim)['ammo'];post_fire_offset=len(so.text())
            control(victim,'fire',True)
            so.wait(lambda t:latest(so,victim)['ammo']<ammo,timeout=5)
            control(victim,'fire',False)
            so.pause(.2)
            checks['respawned_player_can_fire_again']=latest(so,victim)['ammo']<ammo and (not victim_vr or bool(rays(so.text()[post_fire_offset:],victim)))
            for observer in (fo,co):observer.wait(lambda t:samples(t,victim)[-1]['ammo']==latest(so,victim)['ammo'],timeout=4)
            checks['post_respawn_ammo_replicates']=True
            payloads=spawn_payloads(so.text());checks['actual_native_spawn_payload_complete']=bool(payloads) and all(v[1:7]==v[7:13] for v in payloads)
            checks['native_respawn_packet_was_sent']=any(v[0]==victim for v in spawn_payloads(so.text()[spawn_offset:]))
            phase='late actual XR respawn projection';respawn_stereo=late_stereo('respawn');checks['late_actual_stereo_death_and_respawn_frames']=death_stereo['distinct_eyes'] and respawn_stereo['distinct_eyes'] and respawn_stereo['completed_HUD_frame']>death_stereo['completed_HUD_frame']
            checks['actual_stereo_changes_between_death_and_recovery']=not np.array_equal(np.asarray(Image.open(root/'death-stereo.png')),np.asarray(Image.open(root/'respawn-stereo.png')))
            phase='private native respawn screenshots';screenshot('peer1-respawn',peer1,fo,labs['peer1']);screenshot('xr-respawn',xr,co,labs['xr']);checks['native_private_framebuffer_captures_nonconstant']=all(screenshots.values());checks['private_after_respawn']=isolation()[0]
            counts={role:{str(i):{'max_frag':max(r['frag'] for r in samples(o.text(),i)),'max_deaths':max(r['deaths'] for r in samples(o.text(),i))} for i in (1,2)} for role,o in (('server',so),('peer1',fo),('xr',co))}
            checks['native_scores_stable_through_respawn']=all(v[str(killer)]=={'max_frag':1,'max_deaths':0} and v[str(victim)]=={'max_frag':0,'max_deaths':1} for v in counts.values()) and all(scores_stable(samples(o.text()[score_offsets[role]:],i),i==killer) for role,o in (('server',so),('peer1',fo),('xr',co)) for i in (1,2))
            checks['core_validation_clean']=not re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)',co.text())
            result={'passed':all(checks.values()),'case':a.case,'peer1_mode':'flat','checks':checks,'initial':initial,'first_damage':damaged,'killed':killed,'respawned':respawned,'post_respawn_movement':{'before':start,'after':moved},'spawn_payloads':payloads,'late_actual_stereo':{'death':death_stereo,'respawn':respawn_stereo},'native_score_maxima':counts,'private_window_states':states,'private_screenshots':screenshots}
    except Exception as e:result={'passed':False,'case':a.case,'phase':phase,'error':str(e)}
    finally:
        stop(xr);stop(peer1);stop(server)
        for f in logs:f.close()
    result['evidence_directory']=str(root);(root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
