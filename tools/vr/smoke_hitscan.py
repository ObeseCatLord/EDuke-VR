#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Real native-server hitscan/CON/damage proof driven by OpenXR remote actions."""
import argparse,ctypes,json,math,os,re,shutil,struct,subprocess,tempfile
from pathlib import Path
import numpy as np
from monado_remote import Remote
from smoke_actions import Observer
from smoke_actions_multiplayer import wait_for_join_barrier
from smoke_aim import orientation,players
from smoke_hand_shots import room,card_evidence
from smoke_multiplayer import X11,setup_lab,stop

# This is diagnostic output from the actual final native hitscan, not a mock ray.
RAY=re.compile(r'VR native hitscan: player=(\d+) tile=(\d+) origin=(-?\d+),(-?\d+),(-?\d+) sector=(-?\d+) clamped=(\d) ray=(-?\d+),(-?\d+),(-?\d+) hit=(-?\d+),(-?\d+),(-?\d+) hitsect=(-?\d+) wall=(-?\d+) sprite=(-?\d+)\.')
KEYS=('player','tile','x','y','z','sector','clamped','dx','dy','dz','hitx','hity','hitz','hitsect','wall','sprite')
def rays(text,player):
 result=[dict(zip(KEYS,map(int,v))) for v in RAY.findall(text) if int(v[0])==player]
 spread=re.findall(r'VR hitscan spread: player='+str(player)+r' spread=(-?\d+),(-?\d+) auto=(-?\d+) forced=(\d)',text)
 for row,values in zip(result,spread):row.update(zip(('spreadz','spreada','auto','forced'),map(int,values)))
 return result
def samples(text,kind,player):return list(map(int,re.findall(r'addlog vrscan_'+kind+r' \(player '+str(player)+r'\) = (-?\d+)',text)))
def spark_hits(text,player):
 rows=[];current={}
 for k,v in re.findall(r'addlog vrscan_(shooter|sector|x|y|z)[^=\n]*= (-?\d+)',text):
  if k=='shooter':current={}
  current[k]=int(v)
  if k=='z' and current.get('shooter')==player:rows.append(current)
 return rows

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('binary','client-binary','grp','work-dir'):p.add_argument('--'+n,type=Path,required=True)
 p.add_argument('--ready-wrap',action='store_true',help='exercise native readiness counter wrap with actual server replies')
 p.add_argument('--diagnose-join',action='store_true',help='allow an owned child debugger to capture a stalled native join stack')
 p.add_argument('--display',default=':1');p.add_argument('--remote-port',type=int,required=True)
 p.add_argument('--port',type=int,default=24596)
 p.add_argument('--weapon',choices=('pistol','shotgun','chaingun','grow'),default='pistol')
 p.add_argument('--pistol-shotgun',action='store_true',help='use the AA native SHOTGUN firing tile with pistol timing/WorksLike')
 p.add_argument('--case',choices=('open','wall','glancing','steep','vertical','damage','autoaim','spread','range-one','large-range','force','force-down','steep-target','switch','spread-level'),default='open')
 a=p.parse_args()
 if a.pistol_shotgun and a.weapon!='pistol':p.error('--pistol-shotgun requires --weapon pistol')
 if a.case in ('force','force-down') and a.weapon!='pistol':p.error('forced-slope fixture uses the pistol')
 if a.case in ('spread','spread-level','range-one','large-range') and a.weapon!='shotgun':p.error('spread fixtures require the shotgun pellet burst')
 a.work_dir.mkdir(parents=True,exist_ok=True)
 root=Path(tempfile.mkdtemp(prefix='hitscan-',dir=a.work_dir.resolve()));server=client=None;logs=[];phase='setup';result={'passed':False}
 try:
  sl=setup_lab(root,'server',a.grp.resolve(),False);cl=setup_lab(root,'client',a.grp.resolve(),False)
  weapon={'pistol':1,'shotgun':2,'chaingun':3,'grow':11}[a.weapon]
  for lab in (sl,cl):
   for n in ('controller_test.con','aim_test.con','hand_test.con','hitscan_test.con'):shutil.copyfile(Path(__file__).parent/'fixtures'/n,lab/n)
   f=lab/'hitscan_test.con';s=f.read_text().replace('gamevar vrscan_weapon 1 0',f'gamevar vrscan_weapon {weapon} 0')
   if a.pistol_shotgun:s+='\ngamevar WEAPON1_SHOOTS SHOTGUN GAMEVAR_PERPLAYER\n'
   if a.case in ('spread','spread-level','large-range'):s=s.replace('setvar ANGRANGE 0','setvar ANGRANGE 32').replace('setvar ZRANGE 0','setvar ZRANGE 256')
   if a.case=='large-range':s=s.replace('setvar ANGRANGE 32','setvar ANGRANGE 2147483647').replace('setvar ZRANGE 256','setvar ZRANGE 2147483647')
   if a.case=='range-one':s=s.replace('setvar ANGRANGE 0','setvar ANGRANGE 1').replace('setvar ZRANGE 0','setvar ZRANGE 1')
   if a.case in ('force','force-down'):s+='\nonevent EVENT_PREWEAPONSHOOT\n zshoot -8192 SHOTSPARK1\n setvar RETURN 1\nendevent\n'
   if a.case=='force-down':s=s.replace('zshoot -8192 SHOTSPARK1','zshoot 8192 SHOTSPARK1')
   f.write_text(s)
   if a.case=='steep-target':
    f=lab/'hand_test.con';f.write_text(f.read_text().replace('setactor[THISACTOR].x 4096','setactor[THISACTOR].x 1550').replace('setactor[THISACTOR].y 4790','setactor[THISACTOR].y 4244\n        setactor[THISACTOR].z -24576'))
   if a.case=='autoaim':
    f=lab/'hand_test.con';f.write_text(f.read_text().replace('setplayer[THISACTOR].auto_aim 0','setplayer[THISACTOR].auto_aim 1'))
   data=bytearray(room(a.case in ('wall','glancing'),a.case in ('damage','autoaim','steep-target')))
   if a.case=='switch':
    struct.pack_into('<h',data,104+5*32+16,162)
    struct.pack_into('<h',data,104+5*32+26,101)
   if a.case=='steep-target':struct.pack_into('<iii',data,len(data)-44,1550,4244,-24576)
   (lab/'hand.map').write_bytes(data)
  env={k:v for k,v in os.environ.items() if not k.startswith('EDUKE32_XR')};env.update(DISPLAY=a.display,SDL_VIDEODRIVER='x11',SDL_AUDIODRIVER='dummy')
  se={k:v for k,v in env.items() if not k.startswith('XR_')};se['EDUKE32_XR_TEST_SHOTS']='1'
  ce=dict(env,EDUKE32_XR='1',EDUKE32_XR_SINGLE_PASS='1',EDUKE32_XR_UI='2',EDUKE32_XR_AIM='right',EDUKE32_XR_WEAPON='1',EDUKE32_XR_HAND_SHOTS='1',EDUKE32_XR_TEST_INPUT='1',EDUKE32_XR_TEST_SHOTS='1',EDUKE32_XR_WORLD_OUTPUT=str(cl/'world'),EDUKE32_XR_HUD_OUTPUT=str(cl/'hud'),EDUKE32_XR_WEAPON_OUTPUT=str(cl/'weapon'))
  if a.ready_wrap:ce['EDUKE32_XR_TEST_READY_WRAP']='1'
  log=(sl/'server.log').open('w');logs.append(log)
  server=subprocess.Popen([str(a.binary.resolve()),'-usecwd','-nosetup','-noautoload','-dedicated','-port',str(a.port),'-map','hand.map','-x','hitscan_test.con'],cwd=sl,env=se,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
  so=Observer(server,sl/'server.log');so.wait(lambda t:'Multiplayer server initialized.' in t)
  with Remote(a.remote_port) as remote:
   hand=remote.packet.right;hand.pose.position.x=.2;hand.pose.position.y=1.3;hand.pose.position.z=-.5
   if a.case=='glancing':hand.pose.position.x=1.5;hand.pose.position.z=-.40625
   remote.send();log=(cl/'client.log').open('w');logs.append(log)
   def permit_parent_debugger():
    ctypes.CDLL(None).prctl(0x59616d61,os.getppid(),0,0,0) # PR_SET_PTRACER: this parent and its owned descendants only
   client=subprocess.Popen([str(a.client_binary.resolve()),'-usecwd','-nosetup','-noautoload','-nologo','-ns','-nm','-connect',f'127.0.0.1:{a.port}','-x','hitscan_test.con'],cwd=cl,env=ce,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,preexec_fn=permit_parent_debugger if a.diagnose_join else None)
   co=Observer(client,cl/'client.log');phase='join'
   player=wait_for_join_barrier(X11(a.display),client,cl/'client.log',so)['server_player'];so.wait(lambda t:len(players(t,player))>20)
   yaw=12;pitch=0 if a.case in ('damage','autoaim','spread-level') else 8
   if a.case in ('steep','steep-target'):pitch=75
   if a.case=='force':pitch=-75
   if a.case in ('vertical','spread','force-down'):pitch=90
   hand.pose.orientation=orientation(yaw,pitch);remote.packet.head.center.orientation=orientation(-12,4);remote.send();co.pause(.5)
   co.wait(lambda t:'OpenXR world oracle: 60 frames' in t and 'OpenXR HUD presentation: 60 frames' in t,timeout=20)
   initial_ammo=samples(so.text(),'ammo',player)[-1]
   before_health=None
   initial_size=int(re.findall(r'addlog vrscan_target_xrepeat[^=\n]*= (-?\d+)',so.text())[-1])
   if a.case in ('damage','autoaim','steep-target'):before_health=int(re.findall(r'addlog vrtarget_health[^=\n]*= (-?\d+)',so.text())[-1])
   if a.weapon=='grow' and a.case=='damage':
    window,_=X11(a.display).owned_window(client.pid)
    if not window:raise RuntimeError('owned pre-growth window missing')
    subprocess.run(['import','-display',a.display,'-window',str(window),str(root/'pre-grow.png')],check=True,timeout=8)
   phase='native shot';offset=len(so.text());remote.packet.right.trigger_value=1;remote.packet.right.trigger_click=True;remote.send()
   so.wait(lambda t:bool(rays(t[offset:],player)),timeout=4)
   remote.packet.right.trigger_value=0;remote.packet.right.trigger_click=False;remote.send();so.pause(.3)
   observed=rays(so.text()[offset:],player);first=observed[0]
   if a.case in ('damage','autoaim','steep-target') and a.weapon!='grow':
    phase='server native damage'
    # Pistol damage is intentionally native: observe a health decrease rather
    # than editing the enemy's health to force a kill in one shot.
    so.wait(lambda t:int(re.findall(r'addlog vrtarget_health[^=\n]*= (-?\d+)',t)[-1])<before_health,timeout=3)
    health=int(re.findall(r'addlog vrtarget_health[^=\n]*= (-?\d+)',so.text())[-1])
    phase='client native damage'
    co.wait(lambda t:int(re.findall(r'addlog vrtarget_health[^=\n]*= (-?\d+)',t)[-1])<=max(health,0),timeout=4)
   if a.weapon=='grow' and a.case=='damage':
    phase='native grow threshold'
    def grown(text):return int(re.findall(r'addlog vrscan_target_xrepeat[^=\n]*= (-?\d+)',text)[-1])>initial_size
    # Native CON starts expansion only after damage exhausts target health.
    # Use additional real trigger presses; never change health/action/scale.
    for _ in range(5):
     if grown(so.text()):break
     so.pause(.35);next_offset=len(so.text())
     remote.packet.right.trigger_value=1;remote.packet.right.trigger_click=True;remote.send()
     so.wait(lambda t:bool(rays(t[next_offset:],player)),timeout=3)
     remote.packet.right.trigger_value=0;remote.packet.right.trigger_click=False;remote.send();so.pause(.3)
    so.wait(grown,timeout=3);co.wait(grown,timeout=4)
    observed=rays(so.text()[offset:],player)
    co.pause(.12);window,_=X11(a.display).owned_window(client.pid)
    if not window:raise RuntimeError('owned post-growth window missing')
    subprocess.run(['import','-display',a.display,'-window',str(window),str(root/'post-grow.png')],check=True,timeout=8)
   checks={'native_join':player>0,'actual_60_stereo_world_HUD_submissions':(cl/'hud-left.ppm').read_bytes()!=(cl/'hud-right.ppm').read_bytes(),'core_validation_active':'Core Validation output type:' in co.text(),'core_validation_clean':not re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)',co.text()),'native_ammo_consumed':samples(so.text(),'ammo',player)[-1]<initial_ammo,'native_player_binding_does_not_oscillate':len(re.findall(r'VR snapshot player binding restored: player='+str(player)+r' ',co.text()))<=1}
   if a.ready_wrap:
    waits=re.findall(r'readiness wait: begin baseline=(\d+)\.[\s\S]*?readiness wait: complete observed=(-?\d+) requests=(\d+) ticks=(\d+)',co.text())
    checks['actual_wrapped_native_readiness_replies_reach_gameplay']=bool(waits) and all(int(base) in (127,255) and int(observed)<int(base) for base,observed,_,_ in waits)
    checks['native_readiness_request_rate_bounded']=bool(waits) and all(0<int(requests)<=int(ticks)//4+1 for _,_,requests,ticks in waits)
   if a.case in ('wall','glancing'):checks['native_ray_starts_before_blocking_wall']=first['clamped']==1 and first['x']<=1136 and first['sector']==0 and abs(first['hitx']-1152)<=1
   else:checks['native_ray_starts_in_neighbor_sector']=first['sector']==1 and first['x']==1216 and first['y']==4173
   direction=np.array([math.cos(math.radians(pitch))*math.cos(math.radians(yaw)),math.cos(math.radians(pitch))*math.sin(math.radians(yaw)),-math.sin(math.radians(pitch))])
   actual=np.array([first['dx'],first['dy'],first['dz']/16.]);actual/=np.linalg.norm(actual)
   if a.case not in ('autoaim','spread','spread-level','large-range','force','force-down'):checks['native_full_direction_matches_independent_physical_hand']=float(np.linalg.norm(actual-direction))<.003
   if a.case in ('steep','vertical','spread'):checks['actual_ceiling_hit']=all(r['wall']==r['sprite']==-1 and r['hitz']==-32768 for r in observed)
   elif a.case not in ('damage','autoaim','steep-target','wall','glancing','large-range','force','force-down'):checks['actual_far_wall_hit']=first['wall']==5 and abs(first['hitx']-8192)<=1
   if a.case=='switch':
    so.wait(lambda t:'addlog vrscan_switch = 163' in t,timeout=3);co.wait(lambda t:'addlog vrscan_switch = 163' in t,timeout=4)
    checks['native_shootable_switch_toggles_server_and_client']=True
   if a.case in ('open','wall','glancing') and a.weapon!='grow':checks['native_wall_decal_created']='addlog vrscan_decal = 1' in so.text()[offset:]
   if a.weapon=='grow' and a.case=='damage':checks['native_grow_effect_server_and_client']=first['sprite']==4 and grown(so.text()) and grown(co.text())
   hits=spark_hits(so.text()[offset:],player);checks['native_CON_impact_sprite_matches_actual_hit']=len(hits)==len(observed) and all([s[k] for k in ('x','y','z')]==[r[k] for k in ('hitx','hity','hitz')] and s['sector']==r['hitsect'] for s,r in zip(hits,observed))
   events={k:samples(so.text()[offset:],k,player) for k in ('pre','range','auto')}
   checks['native_events_once_per_pellet']=all(len(events[k])==len(observed) for k in events)
   if a.weapon=='shotgun':checks['native_shotgun_seven_pellets']=len(observed)==7
   if a.case in ('damage','autoaim','steep-target') and a.weapon!='grow':
    after=int(re.findall(r'addlog vrtarget_health[^=\n]*= (-?\d+)',so.text())[-1]);client_after=int(re.findall(r'addlog vrtarget_health[^=\n]*= (-?\d+)',co.text())[-1])
    checks['actual_native_target_hit']=any(r['sprite']==4 for r in observed)
    checks['native_server_damage_replicates']=after<before_health and client_after<=max(after,0)
   if a.case=='autoaim':checks['native_autoaim_selects_real_actor']=first['auto']==4 and first['dz']!=0
   if a.case in ('force','force-down'):
    slope=-8192/256 if a.case=='force' else 8192/256
    checks['explicit_CON_zshoot_slope_wins']=first['forced']==1 and abs(first['dz']/math.hypot(first['dx'],first['dy'])-slope)<.001
    checks['opposite_forced_slope_hits_correct_plane']=first['wall']==first['sprite']==-1 and first['hitz']==(-32768 if slope<0 else 0)
   if a.case=='range-one':checks['range_one_consumes_native_zero_spread_samples']=all(r['spreadz']==r['spreada']==0 for r in observed)
   if a.case=='large-range':checks['large_CON_ranges_remain_finite_and_hit_geometry']=all(r['hitsect']>=0 and max(abs(r[k]) for k in ('dx','dy','dz'))<=262144 for r in observed)
   if a.case=='spread-level':
    def level_spread(row):
     x,y,z=row['dx'],row['dy'],row['dz']/16.
     azimuth=math.atan2(y,x)-math.radians(yaw)-row['spreada']*math.pi/1024
     azimuth=math.atan2(math.sin(azimuth),math.cos(azimuth))
     return abs(azimuth)<.0001 and abs(z/math.hypot(x,y)-row['spreadz']/4096)<.0001
    checks['horizontal_native_azimuth_and_slope_contract']=all(level_spread(row) for row in observed)
   if a.case=='spread':
    def pole_spread(row):
     actual=np.array([row['dx'],row['dy'],row['dz']/16.]);actual/=np.linalg.norm(actual)
     a=row['spreada']*math.pi/1024;expected=np.array([row['spreadz']/4096,math.sin(a),-math.cos(a)]);expected/=np.linalg.norm(expected)
     return float(np.linalg.norm(actual-expected))<.0001
    checks['vertical_spread_matches_independent_pole_contract']=all(pole_spread(row) for row in observed)
    checks['nonzero_vertical_spread_is_two_dimensional']=bool(np.linalg.matrix_rank(np.array([[r['dx'],r['dy']] for r in observed]))==2)
    checks['native_ranges_produce_nonzero_offsets']=len({(r['spreadz'],r['spreada']) for r in observed})>1
   card_errors=None
   if a.case not in ('steep','steep-target','vertical','spread','large-range','force','force-down'):
    meta={'x':players(so.text(),player)[-1]['x'],'y':4096,'z':-9952,'pyoff':0}
    card,card_errors=card_evidence(cl,meta,[player,first['x'],first['y'],first['z']],hand);checks.update(card)
   result={'passed':all(checks.values()),'weapon':a.weapon,'case':a.case,'checks':checks,'rays':observed,'native_event_counts':{k:len(v) for k,v in events.items()},'ammo_before':initial_ammo,'ammo_after':samples(so.text(),'ammo',player)[-1],'card_projection_max_channel_error':card_errors,'readiness_waits':([list(map(int,w)) for w in waits] if a.ready_wrap else None),'grown_repeat':({'server':int(re.findall(r'addlog vrscan_target_xrepeat[^=\n]*= (-?\d+)',so.text())[-1]),'client':int(re.findall(r'addlog vrscan_target_xrepeat[^=\n]*= (-?\d+)',co.text())[-1]),'before':initial_size} if a.weapon=='grow' and a.case=='damage' else None),'target_health':({'before':before_health,'server':int(re.findall(r'addlog vrtarget_health[^=\n]*= (-?\d+)',so.text())[-1]),'client':int(re.findall(r'addlog vrtarget_health[^=\n]*= (-?\d+)',co.text())[-1])} if before_health is not None else None)}
 except Exception as e:
  result={'passed':False,'weapon':a.weapon,'case':a.case,'phase':phase,'error':str(e)}
  if a.diagnose_join and client and client.poll() is None:
   try:
    with (root/'join-stack.txt').open('w') as trace:
     subprocess.run(['gdb','--batch','--nx','--pid',str(client.pid),'-ex','set pagination off','-ex','thread apply all bt 16','-ex','detach'],stdout=trace,stderr=subprocess.STDOUT,timeout=15)
   except Exception as diagnostic:result['diagnostic_error']=str(diagnostic)
 finally:
  stop(client);stop(server)
  for log in logs:log.close()
 result['pistol_shotgun']=a.pistol_shotgun;result['evidence_directory']=str(root);(root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
