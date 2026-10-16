#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Native server freezer/shrinker authority, bounce/effects and XR pixel proof."""
import argparse,json,math,os,re,shutil,subprocess,tempfile
from pathlib import Path
from monado_remote import Remote
from smoke_actions import Observer
from smoke_actions_multiplayer import wait_for_join_barrier
from smoke_aim import orientation,players
from smoke_hand_shots import room,card_evidence
from smoke_hitscan import samples
from smoke_multiplayer import X11,setup_lab,stop

SHOT=re.compile(r'VR native projectile: player=(\d+) tile=(\d+) index=(\d+) origin=(-?\d+),(-?\d+),(-?\d+) sector=(-?\d+) clamped=(\d) angle=(-?\d+) speed=(-?\d+) zvel=(-?\d+) policy=(-?\d+)')
KEYS=('player','tile','index','x','y','z','sector','clamped','angle','speed','zvel','policy')
def shots(text,player):return [dict(zip(KEYS,map(int,r))) for r in SHOT.findall(text) if int(r[0])==player]
def observations(text,player):
 result=[];row={}
 for k,v in re.findall(r'addlog vrproj_(index|tile|player|sector|x|y|z|angle|speed|zvel|policy|hit)\b[^=\n]*= (-?\d+)',text):
  if k=='index':row={}
  row[k]=int(v)
  if k=='hit' and row.get('player')==player:result.append(row)
 return result
def target(text,name):return int(re.findall(r'addlog vrproj_target_'+name+r'[^=\n]*= (-?\d+)',text)[-1])

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('binary','client-binary','grp','work-dir'):p.add_argument('--'+n,type=Path,required=True)
 p.add_argument('--display',default=':1');p.add_argument('--remote-port',type=int,required=True);p.add_argument('--port',type=int,default=24598)
 p.add_argument('--weapon',choices=('freeze','shrink'),default='freeze')
 p.add_argument('--case',choices=('open','wall','glancing','steep','vertical','effect','unsupported-server','older-client'),default='open')
 a=p.parse_args();a.work_dir.mkdir(parents=True,exist_ok=True);root=Path(tempfile.mkdtemp(prefix='projectile-',dir=a.work_dir.resolve()));server=client=None;logs=[];phase='setup';result={'passed':False}
 try:
  sl=setup_lab(root,'server',a.grp.resolve(),False);cl=setup_lab(root,'client',a.grp.resolve(),False)
  weapon=9 if a.weapon=='freeze' else 6
  for lab in (sl,cl):
   for n in ('controller_test.con','aim_test.con','hand_test.con','hitscan_test.con','projectile_test.con'):shutil.copyfile(Path(__file__).parent/'fixtures'/n,lab/n)
   f=lab/'hitscan_test.con';f.write_text(f.read_text().replace('gamevar vrscan_weapon 1 0',f'gamevar vrscan_weapon {weapon} 0'))
   (lab/'hand.map').write_bytes(room(a.case in ('wall','glancing'),a.case=='effect'))
  env={k:v for k,v in os.environ.items() if not k.startswith('EDUKE32_XR')};env.update(DISPLAY=a.display,SDL_VIDEODRIVER='x11',SDL_AUDIODRIVER='dummy')
  se={k:v for k,v in env.items() if not k.startswith('XR_')};se['EDUKE32_XR_TEST_SHOTS']='1'
  ce=dict(env,EDUKE32_XR='1',EDUKE32_XR_SINGLE_PASS='1',EDUKE32_XR_UI='2',EDUKE32_XR_AIM='right',EDUKE32_XR_WEAPON='1',EDUKE32_XR_HAND_SHOTS='1',EDUKE32_XR_TEST_INPUT='1',EDUKE32_XR_TEST_SHOTS='1',EDUKE32_XR_WORLD_OUTPUT=str(cl/'world'),EDUKE32_XR_HUD_OUTPUT=str(cl/'hud'),EDUKE32_XR_WEAPON_OUTPUT=str(cl/'weapon'))
  log=(sl/'server.log').open('w');logs.append(log)
  server=subprocess.Popen([str(a.binary.resolve()),'-usecwd','-nosetup','-noautoload','-dedicated','-port',str(a.port),'-map','hand.map','-x','projectile_test.con'],cwd=sl,env=se,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
  so=Observer(server,sl/'server.log');so.wait(lambda t:'Multiplayer server initialized.' in t)
  with Remote(a.remote_port) as remote:
   hand=remote.packet.right;hand.pose.position.x=.2;hand.pose.position.y=1.3;hand.pose.position.z=-.5
   if a.case=='glancing':hand.pose.position.x=1.5;hand.pose.position.z=-.40625
   remote.send();log=(cl/'client.log').open('w');logs.append(log)
   client=subprocess.Popen([str(a.client_binary.resolve()),'-usecwd','-nosetup','-noautoload','-nologo','-ns','-nm','-connect',f'127.0.0.1:{a.port}','-x','projectile_test.con'],cwd=cl,env=ce,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
   co=Observer(client,cl/'client.log');phase='join';player=wait_for_join_barrier(X11(a.display),client,cl/'client.log',so)['server_player'];so.wait(lambda t:len(players(t,player))>20)
   yaw=12;pitch=0 if a.case=='effect' else 8
   if a.case=='steep':pitch=75
   if a.case=='vertical':pitch=90
   hand.pose.orientation=orientation(yaw,pitch);remote.packet.head.center.orientation=orientation(-12,4);remote.send();co.pause(.5)
   co.wait(lambda t:'OpenXR world oracle: 60 frames' in t and 'OpenXR HUD presentation: 60 frames' in t,timeout=20)
   checks={'native_join':player>0,'actual_60_stereo_world_HUD_submissions':(cl/'hud-left.ppm').read_bytes()!=(cl/'hud-right.ppm').read_bytes(),'core_validation_active':'Core Validation output type:' in co.text(),'core_validation_clean':not re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)',co.text())}
   ammo=samples(so.text(),'ammo',player)[-1];offset=len(so.text());phase='native fire'
   def fire(wait=True):
    start=len(so.text());remote.packet.right.trigger_value=1;remote.packet.right.trigger_click=True;remote.send()
    if wait:so.wait(lambda t:bool(shots(t[start:],player)),timeout=4)
    else:so.pause(.35)
    remote.packet.right.trigger_value=0;remote.packet.right.trigger_click=False;remote.send();so.pause(.12)
   if a.case=='unsupported-server':
    before=players(so.text(),player)[-1];remote.packet.right.trigger_value=1;remote.packet.right.trigger_click=True;remote.packet.left.thumbstick.y=.7;remote.send();so.pause(1.)
    remote.packet.right.trigger_value=0;remote.packet.right.trigger_click=False;remote.packet.left.thumbstick.y=0;remote.send();so.pause(.2)
    checks.update(older_hitscan_server_does_not_advertise_freeze_shrink='features=3' in co.text() and 'features=7' not in co.text(),unsupported_hand_projectile_does_not_silently_body_fire=not observations(so.text()[offset:],player) and samples(so.text(),'ammo',player)[-1]==ammo,native_movement_continues=players(so.text(),player)[-1]['x']>before['x']+100)
    result={'passed':all(checks.values()),'case':a.case,'weapon':a.weapon,'checks':checks}
   elif a.case=='older-client':
    fire(False);so.wait(lambda t:bool(observations(t[offset:],player)),timeout=4);first=observations(so.text()[offset:],player)[0]
    checks.update(older_client_advertises_only_hitscan='features=3' in so.text() and 'features=7' not in so.text(),unadvertised_feature_does_not_enable_hand_origin=not shots(so.text()[offset:],player) and first['sector']==0 and first['x']<1152,native_body_projectile_consumes_ammo=samples(so.text(),'ammo',player)[-1]<ammo)
    result={'passed':all(checks.values()),'case':a.case,'weapon':a.weapon,'checks':checks,'native_spawn_observation':first}
   else:
    checks['feature_explicitly_negotiated']='features=7' in co.text() and 'features=7' in so.text();fire();first=shots(so.text()[offset:],player)[0]
    speed=644 if a.weapon=='freeze' else 768;bias=-32 if a.weapon=='freeze' else 0
    checks.update(physical_horizontal_speed=abs(first['speed']-round(speed*math.cos(math.radians(pitch))))<=1,physical_vertical_speed_and_native_bias=abs(first['zvel']-(round(-speed*16*math.sin(math.radians(pitch)))+bias))<=1,native_ammo_consumed=samples(so.text(),'ammo',player)[-1]<ammo)
    if a.case in ('wall','glancing'):checks['constrained_before_wall']=first['clamped']==1 and first['x']<=1136 and first['sector']==0
    else:checks['origin_crosses_portal_without_body_offset']=[first[k] for k in ('x','y','z')]==[1216,4173,-8109] and first['sector']==1
    if a.case=='open':
     phase='actual client projectile';co.wait(lambda t:any(r['index']==first['index'] for r in observations(t,player)),timeout=4)
     client_rows=[r for r in observations(co.text(),player) if r['index']==first['index']]
     checks['client_receives_real_projectile']=any(all(r[k]==first[k] for k in ('tile','speed','zvel','angle')) for r in client_rows)
    if a.weapon=='freeze' and a.case in ('open','steep','vertical'):
     phase='native bounce';so.wait(lambda t:any(r['index']==first['index'] and r['policy']<first['policy'] and (r['hit']&49152) in (16384,32768) for r in observations(t[offset:],player)),timeout=5)
     bounce=next(r for r in observations(so.text()[offset:],player) if r['index']==first['index'] and r['policy']<first['policy'] and (r['hit']&49152) in (16384,32768))
     checks['native_bounce_decrements_budget']=bounce['policy']==first['policy']-1
     if a.case in ('steep','vertical'):checks['native_ceiling_bounce_reverses_Z']=bounce['zvel']>0 and (bounce['hit']&49152)==16384
     if a.case=='vertical':checks['vertical_bounce_keeps_axis']=(bounce['x'],bounce['y'])==(first['x'],first['y']) and bounce['speed']==0
    if a.case=='effect':
     phase='native target effect'
     def affected(text):return target(text,'pal')==1 if a.weapon=='freeze' else 0<target(text,'size')<40
     for _ in range(6):
      if affected(so.text()):break
      so.pause(.5)
      if affected(so.text()):break
      fire()
     so.wait(affected,timeout=4);co.wait(affected,timeout=5)
     checks['native_target_effect_server_and_client']=affected(so.text()) and affected(co.text())
     # Allow the received native target state to reach an actual rendered frame.
     co.pause(.25)
     checks['target_effect_persists_through_render']=affected(so.text()) and affected(co.text())
     window,_=X11(a.display).owned_window(client.pid)
     if not window:raise RuntimeError('owned effect window missing')
     subprocess.run(['import','-display',a.display,'-window',str(window),str(root/'effect.png')],check=True,timeout=8)
    card_errors=None
    if a.case not in ('steep','vertical'):
     meta={'x':players(so.text(),player)[-1]['x'],'y':4096,'z':-9952,'pyoff':0};cc,card_errors=card_evidence(cl,meta,[player,first['x'],first['y'],first['z']],hand);checks.update(cc)
    result={'passed':all(checks.values()),'case':a.case,'weapon':a.weapon,'checks':checks,'projectile':first,'native_bounce':bounce if a.weapon=='freeze' and a.case in ('open','steep','vertical') else None,'target_effect':{'server_pal':target(so.text(),'pal'),'client_pal':target(co.text(),'pal'),'server_size':target(so.text(),'size'),'client_size':target(co.text(),'size')} if a.case=='effect' else None,'card_projection_max_channel_error':card_errors}
 except Exception as e:result={'passed':False,'case':a.case,'weapon':a.weapon,'phase':phase,'error':str(e)}
 finally:
  stop(client);stop(server)
  for f in logs:f.close()
 result['evidence_directory']=str(root);(root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
