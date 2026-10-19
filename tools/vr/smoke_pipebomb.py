#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Private actual-XR/native pipebomb authority and native trajectory proof."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile

from PIL import Image, ImageChops
from monado_remote import Remote
from smoke_actions import Observer
from smoke_actions_multiplayer import wait_for_join_barrier, client_player_index
from smoke_aim import orientation
from smoke_hand_shots import room
from smoke_multiplayer import CONFIG, X11, stop
from smoke_pipebomb_native import write_lab, players, bombs, native_bomb, latest_player, explosions, trajectory

TRACE = re.compile(r'VR native pipebomb: player=(\d+) index=(\d+) origin=(-?\d+),(-?\d+),(-?\d+) sector=(-?\d+) clamped=(\d) angle=(-?\d+) speed=(-?\d+) zvel=(-?\d+) rolling=(\d) mode=(-?\d+) fuse=(-?\d+) charge=(\d+)')
KEYS = ('player','index','x','y','z','sector','clamped','angle','xvel','zvel','rolling','mode','fuse','charge')
def throws(text):
    return [dict(zip(KEYS, map(int, row))) for row in TRACE.findall(text)]

def last(text, name):
    values = re.findall(r'addlog vrpipetarget_'+name+r'\b[^=\n]*= (-?\d+)', text)
    return int(values[-1]) if values else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary','client-binary','grp','work-dir'):
        parser.add_argument('--'+name, required=True, type=Path)
    parser.add_argument('--remote-port', type=int, required=True)
    parser.add_argument('--display', default=':1')
    parser.add_argument('--port', type=int, default=24736)
    parser.add_argument('--case', choices=('open','ordering','wall','glancing','steep','vertical','roll','timer','lost','recover-release','reach','high-charge','down-charge'), default='open')
    args = parser.parse_args()
    if os.environ.get('EDUKE32_TEST_PRIVATE_WINDOW') != '1':
        parser.error('private hidden-window mode is required')
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='pipebomb-',dir=args.work_dir.resolve()))
    processes, logs, phase = [], [], 'setup'
    result = {'passed':False}
    try:
        labs={role:write_lab(root, role, args.grp.resolve()) for role in (('server','client','observer') if args.case=='ordering' else ('server','client'))}
        for lab in labs.values():
            (lab/'eduke32.cfg').write_text(CONFIG)
            (lab/'pipebomb.map').write_bytes(room(args.case in ('wall','glancing')))
            # Controlled target: native dedicated player0, initially stationary.
            # No mutation after initialization; damage/owner/score stay native.
            setup = '''\ngamevar vrpipetarget_given 0 1
gamevar vrpipetarget_player 0 0
gamevar vrpipetarget_index 0 0
gamevar vrpipetarget_health 0 0
gamevar vrpipetarget_fragps 0 0
gamevar vrpipetarget_shooter 1 0
gamevar vrpipetarget_frags 0 0
gamevar vrpipetarget_deaths 0 0
gamevar vrpipetarget_shooterindex 0 0
gamevar vrpipetarget_shooterhp 0 0
onevent EVENT_PROCESSINPUT
 ifvare vrpipe_given 1
 ifvare vrpipetarget_given 0
 {
  ifvare vrpipe_player 0
  {
   setplayer[THISACTOR].posx TARGETX
   setplayer[THISACTOR].oposx TARGETX
   setactor[THISACTOR].x TARGETX
   setplayer[THISACTOR].posy TARGETY
   setplayer[THISACTOR].oposy TARGETY
   setactor[THISACTOR].y TARGETY
   setplayer[THISACTOR].cursectnum 1
   changespritesect THISACTOR 1
   setactor[THISACTOR].extra 50
   setplayer[THISACTOR].last_extra 50
  }
  ifvarg vrpipe_player 1
  {
   setplayer[THISACTOR].posx 512
   setplayer[THISACTOR].oposx 512
   setactor[THISACTOR].x 512
   setplayer[THISACTOR].posy 6500
   setplayer[THISACTOR].oposy 6500
   setactor[THISACTOR].y 6500
  }
  CONFIGURE
  setvar vrpipetarget_given 1
 }
 getplayer[vrpipetarget_player].i vrpipetarget_index
 getactor[vrpipetarget_index].extra vrpipetarget_health
 getplayer[vrpipetarget_player].frag_ps vrpipetarget_fragps
 getplayer[vrpipetarget_shooter].frag vrpipetarget_frags
 getplayer[vrpipetarget_player].deaths vrpipetarget_deaths
 getplayer[vrpipetarget_shooter].i vrpipetarget_shooterindex
 getactor[vrpipetarget_shooterindex].extra vrpipetarget_shooterhp
 addlog vrpipetarget_health
 addlog vrpipetarget_fragps
 addlog vrpipetarget_frags
 addlog vrpipetarget_deaths
 addlog vrpipetarget_shooterhp
endevent
'''
            configuration = ''
            if args.case == 'timer':
                configuration='setvar PIPEBOMB_CONTROL 2\n  setvar GRENADE_LIFETIME 120\n  setvar GRENADE_LIFETIME_VAR 0'
            if args.case in ('high-charge','down-charge'):
                configuration='setvar WEAPON5_FIREDELAY 230\n  setvar WEAPON5_HOLDDELAY 240\n  setvar WEAPON5_TOTALTIME 250'
            setup=setup.replace('TARGETX','6000' if args.case=='timer' else '3000').replace('TARGETY','4500' if args.case=='timer' else '2500').replace('CONFIGURE',configuration)
            with (lab/'pipebomb_test.con').open('a') as out:out.write(setup)
        env={k:v for k,v in os.environ.items() if not k.startswith('EDUKE32_XR')}
        env.update(DISPLAY=args.display,SDL_VIDEODRIVER='x11',SDL_AUDIODRIVER='dummy')
        native={k:v for k,v in env.items() if not k.startswith('XR_')}
        native['EDUKE32_XR_TEST_SHOTS']='1'
        xr_env=dict(env,EDUKE32_XR='1',EDUKE32_XR_SINGLE_PASS='1',EDUKE32_XR_UI='2',EDUKE32_XR_AIM='right',EDUKE32_XR_WEAPON='1',EDUKE32_XR_HAND_SHOTS='1',EDUKE32_XR_TEST_INPUT='1',EDUKE32_XR_TEST_SHOTS='1',EDUKE32_XR_TEST_PVP='1',EDUKE32_XR_HUD_OUTPUT=str(labs['client']/'hud'),EDUKE32_XR_WORLD_OUTPUT=str(labs['client']/'world'))
        def launch(role, binary, flags, environment):
            log=(labs[role]/'game.log').open('w');logs.append(log)
            proc=subprocess.Popen([str(binary.resolve()),'-usecwd','-nosetup','-noautoload','-nologo','-ns','-nm',*flags,'-x','pipebomb_test.con'],cwd=labs[role],env=environment,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
            processes.append(proc)
            return proc,Observer(proc,labs[role]/'game.log')
        server,so=launch('server',args.binary,['-dedicated','-c1','-port',str(args.port),'-map','pipebomb.map'],native)
        so.wait(lambda t:'Multiplayer server initialized.' in t,timeout=18)
        x11=X11(args.display)
        with Remote(args.remote_port) as remote:
            hand=remote.packet.right
            hand.pose.position.x=.2;hand.pose.position.y=1.3;hand.pose.position.z=-.5
            if args.case=='glancing':hand.pose.position.x=1.5;hand.pose.position.z=-.40625
            remote.send()
            client,co=launch('client',args.client_binary,['-connect',f'127.0.0.1:{args.port}'],xr_env)
            phase='XR join';player=wait_for_join_barrier(x11,client,labs['client']/'game.log',so)['server_player']
            so.wait(lambda t:latest_player(t,player) is not None and latest_player(t,player)['ammo']==6 and latest_player(t,player)['frame']==0,timeout=10)
            co.pause(1)
            observer=None;oo=None;observer_before=None;ordering_observation=None;marker=root/'delay-player-updates'
            if args.case=='ordering':
                phase='flat observer join'
                observer,oo=launch('observer',args.binary,['-connect',f'127.0.0.1:{args.port}'],dict(native,EDUKE32_TEST_DROP_SERVER_PLAYERS=str(marker)))
                oo.wait(lambda t:'Multiplayer client level synchronization complete.' in t,timeout=20)
                oo.pause(1.5)
                oo.wait(lambda t:client_player_index(t) is not None and latest_player(t,client_player_index(t)) is not None,timeout=8)
                observed=client_player_index(oo.text())
                if observed!=2:raise RuntimeError('ordering observer is not actual native player2')
                window,_=x11.owned_window(observer.pid)
                if window is None:raise RuntimeError('private observer window missing')
                if latest_player(oo.text(),observed)['gm']&1:x11.press(window,'Escape',.06,True)
                so.pause(.3)
                observer_before={'health':last(oo.text(),'shooterhp'),'x':latest_player(oo.text(),player)['x'],'y':latest_player(oo.text(),player)['y']}
                marker.touch()
                oo.wait(lambda t:'Native test: delaying server player snapshots.' in t,timeout=4)
            pitch=35 if args.case=='steep' else 90 if args.case in ('vertical','high-charge') else -80 if args.case=='down-charge' else 8
            hand.pose.orientation=orientation(12,pitch);remote.send()
            if args.case=='roll':
                hand.b_click=True;remote.send()
                so.wait(lambda t:latest_player(t,player)['bits']&2,timeout=4)
            so.pause(.5)
            target_before=last(so.text(),'health')
            co.wait(lambda t:'OpenXR HUD presentation: 60 frames' in t,timeout=20)
            checks={'actual_native_player':player==1,'actual_initial_stereo':(labs['client']/'hud-left.ppm').read_bytes()!=(labs['client']/'hud-right.ppm').read_bytes()}
            def trigger(down):
                hand.trigger_value=1 if down else 0;hand.trigger_click=down;remote.send()
            phase='native held charge';offset=len(so.text());trigger(True)
            fire_delay=230 if args.case in ('high-charge','down-charge') else 6
            so.wait(lambda t:any(r['frame']==fire_delay and r['bits']&4 for r in players(t[offset:],player)),timeout=14)
            so.pause(.3)
            checks['held_native_charge_no_spawn_or_ammo']=not throws(so.text()[offset:]) and all(r['ammo']==6 for r in players(so.text()[offset:],player))
            if args.case in ('lost','recover-release','reach'):
                phase='pending throw cancellation'
                if args.case=='reach':hand.pose.position.x=3.
                else:hand.active=False
                remote.send()
                so.wait(lambda t:latest_player(t,player)['frame']==0 and latest_player(t,player)['ammo']==6,timeout=4)
                hand.active=True;hand.pose.position.x=.2;remote.send()
                if args.case=='recover-release':trigger(False)
                so.pause(.5)
                checks['invalid_charge_canceled_without_ammo_or_spawn']=not throws(so.text()[offset:]) and latest_player(so.text(),player)['ammo']==6
                trigger(False);so.pause(.3);trigger(True)
                so.wait(lambda t:latest_player(t,player)['frame']==6,timeout=5)
            phase='native release';trigger(False)
            so.wait(lambda t:bool(throws(t[offset:])),timeout=6)
            first=throws(so.text()[offset:])[0]
            so.wait(lambda t:latest_player(t,player)['ammo']==5,timeout=5)
            co.wait(lambda t:any(r['index']==first['index'] and r['mode']==first['mode'] for r in bombs(t)),timeout=6)
            co.wait(lambda t:latest_player(t,player)['ammo']==5,timeout=5)
            checks.update(exactly_one_authoritative_throw=len(throws(so.text()[offset:]))==1,one_ammo_consumed=latest_player(so.text(),player)['ammo']==5,owner_is_actual_shooter=any(r['index']==first['index'] and r['ownerplayer']==player for r in bombs(so.text())),actual_live_client_replication=True,representable_native_velocity=-32768<=first['zvel']<=32767 and 0<=first['xvel']<=32767)
            if args.case in ('wall','glancing'):checks['native_origin_constrained_before_wall']=first['clamped']==1 and first['x']<=1136 and first['sector']==0
            else:checks['hand_origin_crosses_portal']=first['x']==1216 and first['y']==2125 and first['sector']==1
            phase='actual native flight';so.wait(lambda t:len(trajectory(bombs(t),first['index']))>=3,timeout=5)
            flight=trajectory(bombs(so.text()),first['index'])
            if args.case in ('open','steep'):
                # Actual actor displacement, correcting native lob and observed
                # gravity increment. The ray's physical slope is independent of
                # the launch helper's stored-field conversion.
                row=flight[0];dx=row['x']-first['x'];dy=row['y']-first['y'];dz=row['z']-first['z']
                gravity_step=row['zvel']-first['zvel']
                corrected_z=(dz-1.5*(-512+gravity_step))/16.
                observed_pitch=math.degrees(math.atan2(-corrected_z,math.hypot(dx,dy)))
                checks['actual_flight_follows_physical_pitch']=abs(observed_pitch-pitch)<2.
            else:observed_pitch=None
            checks['early_native_flight_stays_in_map']=all(r['sector'] in (0,1) and -32768<=r['z']<=0 for r in flight)
            checks['no_client_explosion_before_remote_command']=args.case=='timer' or not explosions(co.text())
            if oo is not None:
                oo.wait(lambda t:len(trajectory(bombs(t),first['index']))>=4,timeout=5)
                observed_flight=trajectory(bombs(oo.text()),first['index'])
                checks['actor_arrives_before_player_state']=latest_player(oo.text(),player)['hbomb']==0 and all(r['mode']==2 for r in observed_flight)
                observer_after={'health':last(oo.text(),'shooterhp'),'x':latest_player(oo.text(),player)['x'],'y':latest_player(oo.text(),player)['y']}
                checks['delayed_observer_no_explosion_or_knockback']=not explosions(oo.text()) and observer_after==observer_before
                ordering_observation={'before':observer_before,'after':observer_after,'bomb_flight':observed_flight,'owner_hbomb_on':latest_player(oo.text(),player)['hbomb'],'explosions_before_command':explosions(oo.text())}
                marker.unlink()
                oo.wait(lambda t:latest_player(t,player)['hbomb']==1,timeout=5)
                checks['authoritative_remote_state_converges_after_delay']=latest_player(oo.text(),player)['hbomb']==1
            if args.case=='roll':
                checks['native_crouch_input']=bool(latest_player(so.text(),player)['bits']&2)
                checks['elevated_native_rolling_tag']=first['rolling']==1 and all(r['yvel']==3 for r in flight)
                so.wait(lambda t:any(r['index']==first['index'] and r['z']>=-768 and r['zvel']==0 for r in bombs(t)),timeout=7)
                checks['elevated_bomb_falls_to_native_floor']=any(r['z']>first['z'] for r in flight) and any(r['index']==first['index'] and r['z']>=-768 and r['zvel']==0 for r in bombs(so.text()))
            if args.case in ('open','ordering','timer'):
                phase='native detonation and damage'
                if args.case in ('open','ordering'):
                    so.wait(lambda t:latest_player(t,player)['weapon']==10 and latest_player(t,player)['frame']==0,timeout=5)
                    trigger(True);so.wait(lambda t:latest_player(t,player)['hbomb']==0,timeout=5);trigger(False)
                so.wait(lambda t:bool(explosions(t)),timeout=10)
                so.wait(lambda t:last(t,'health')<target_before,timeout=5)
                co.wait(lambda t:last(t,'health')<target_before,timeout=5)
                checks['native_target_damage_replicates']=last(so.text(),'health')<target_before and last(co.text(),'health')<target_before
                so.wait(lambda t:last(t,'frags')==1 and last(t,'deaths')==1,timeout=5)
                co.wait(lambda t:last(t,'frags')==1 and last(t,'deaths')==1,timeout=5)
                co.wait(lambda t:bool(explosions(t)),timeout=5)
                checks['native_kill_attributed_and_replicated']=last(so.text(),'frags')==last(co.text(),'frags')==1 and last(so.text(),'deaths')==last(co.text(),'deaths')==1
                checks['native_remote_or_timer_explosion']=bool(explosions(so.text()))
                checks['native_owner_policy']=first['mode']==(1 if args.case=='timer' else 2) and first['fuse']==(120 if args.case=='timer' else 0)
                checks['actual_native_client_explosion']=bool(explosions(co.text()))
                if oo is not None:
                    oo.wait(lambda t:bool(explosions(t)) and last(t,'frags')==1 and last(t,'deaths')==1,timeout=5)
                    checks['delayed_observer_actual_detonation_and_scores']=bool(explosions(oo.text())) and last(oo.text(),'frags')==last(oo.text(),'deaths')==1
                    phase='second native throw and detonation'
                    # Let the native mode3 lifecycle return the first slot to
                    # the allocator; use normal weapon selection/controls.
                    so.pause(1.)
                    window,_=x11.owned_window(client.pid)
                    x11.press(window,'6',.1,True)
                    so.wait(lambda t:latest_player(t,player)['weapon']==5 and latest_player(t,player)['frame']==0,timeout=5)
                    second_offset=len(so.text());client_offset=len(co.text());observer_offset=len(oo.text())
                    trigger(True);so.wait(lambda t:latest_player(t,player)['frame']==6,timeout=5)
                    trigger(False);so.wait(lambda t:bool(throws(t[second_offset:])),timeout=6)
                    second=throws(so.text()[second_offset:])[0]
                    so.wait(lambda t:latest_player(t,player)['ammo']==4,timeout=5)
                    co.wait(lambda t:any(r['index']==second['index'] and r['mode']==2 for r in bombs(t[client_offset:])),timeout=5)
                    oo.wait(lambda t:any(r['index']==second['index'] and r['mode']==2 for r in bombs(t[observer_offset:])),timeout=5)
                    checks['native_bomb_slot_reused']=second['index']==first['index']
                    checks['second_throw_one_ammo_no_early_explosion']=len(throws(so.text()[second_offset:]))==1 and latest_player(so.text(),player)['ammo']==4 and not explosions(co.text()[client_offset:]) and not explosions(oo.text()[observer_offset:])
                    so.wait(lambda t:latest_player(t,player)['weapon']==10 and latest_player(t,player)['frame']==0,timeout=5)
                    trigger(True);so.wait(lambda t:latest_player(t,player)['hbomb']==0,timeout=5);trigger(False)
                    so.wait(lambda t:max(explosions(t) or [0])==2,timeout=5)
                    co.wait(lambda t:max(explosions(t) or [0])==2,timeout=5)
                    oo.wait(lambda t:max(explosions(t) or [0])==2,timeout=5)
                    checks['reused_bomb_actual_client_explosion']=max(explosions(co.text()))==max(explosions(oo.text()))==2
                    ordering_observation['second_throw']=second
            phase='late actual stereo'
            captures=re.compile(r'OpenXR PvP frame: submitted=(\d+) captured=1')
            old=[int(v) for v in captures.findall(co.text())];old=old[-1] if old else 60
            co.wait(lambda t:any(int(v)>old for v in captures.findall(t)),timeout=8)
            serial=int(captures.findall(co.text())[-1]);imgs=[Image.open(labs['client']/f'hud-{serial}-{eye}.ppm').convert('RGB') for eye in ('left','right')]
            checks['fresh_actual_stereo_after_throw']=ImageChops.difference(*imgs).getbbox() is not None
            for eye,img in zip(('left','right'),imgs):img.save(root/f'after-{eye}.png')
            visibility={}
            for role,proc in [('server',server),('xr',client)]+([('observer',observer)] if observer is not None else []):
                window,_=x11.owned_window(proc.pid);visibility[role]=x11.window_visibility(window) if window else None
            checks.update(private_windows=all(v is None or v['unmapped'] and not v['has_desktop_focus'] for v in visibility.values()),core_validation_active='Core Validation output type:' in co.text(),core_validation_clean=not re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)',co.text()))
            result={'passed':all(checks.values()),'case':args.case,'checks':checks,'throw':first,'flight':flight,'observed_pitch':observed_pitch,'ordering_observation':ordering_observation,'target_health':{'before':target_before,'server':last(so.text(),'health'),'client':last(co.text(),'health')},'completed_HUD_frame':serial,'private_windows':visibility}
            trigger(False)
    except Exception as error:
        result={'passed':False,'case':args.case,'phase':phase,'error':str(error)}
    finally:
        for proc in reversed(processes):stop(proc)
        for log in logs:log.close()
    result['evidence_directory']=str(root)
    (root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
