#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Private live-XR reference-space event/pose transformation regression.

A test API layer transforms real runtime locations and supplies the matching
standard event. This qualifies application handling, not physical recentering.
"""
import argparse,json,os,re,subprocess,tempfile
from pathlib import Path
from PIL import Image,ImageChops
from monado_remote import Remote
from smoke_actions import Observer
from smoke_actions_multiplayer import wait_for_join_barrier
from smoke_aim import orientation
from smoke_multiplayer import CONFIG,X11,stop
from smoke_pipebomb import throws
from smoke_pipebomb_native import write_lab,latest_player,bombs

CAMERA=re.compile(r'OpenXR aim camera: authorityYaw=(-?\d+\.\d+) bodyYaw=(-?\d+\.\d+) leftYaw=(-?\d+\.\d+) leftPitch=(-?\d+\.\d+) rightYaw=(-?\d+\.\d+) rightPitch=(-?\d+\.\d+)')
EYES=re.compile(r'OpenXR aim eye positions: left=(-?\d+),(-?\d+),(-?\d+) right=(-?\d+),(-?\d+),(-?\d+)')
CHANGE=re.compile(r'OpenXR LOCAL reference changed: at=(\d+) predicted=(\d+) known=([01])')
CAPTURE=re.compile(r'OpenXR PvP frame: submitted=(\d+) captured=1')
def camera(text):return list(map(float,CAMERA.findall(text)[-1]))
def eyes(text):return list(map(int,EYES.findall(text)[-1]))

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('binary','client-binary','grp','work-dir','layer-dir'):p.add_argument('--'+name,type=Path,required=True)
 p.add_argument('--remote-port',type=int,required=True);p.add_argument('--port',type=int,default=24738);p.add_argument('--display',default=':1');p.add_argument('--case',choices=('known','unknown'),required=True);a=p.parse_args()
 if os.environ.get('EDUKE32_TEST_PRIVATE_WINDOW')!='1':p.error('private hidden windows required')
 a.work_dir.mkdir(parents=True,exist_ok=True);root=Path(tempfile.mkdtemp(prefix='reference-',dir=a.work_dir.resolve()))
 logs=[];procs=[];result={'passed':False};phase='setup'
 try:
  labs={role:write_lab(root,role,a.grp.resolve()) for role in ('server','client')}
  for lab in labs.values():(lab/'eduke32.cfg').write_text(CONFIG)
  env={k:v for k,v in os.environ.items() if not k.startswith('EDUKE32_XR')};env.update(DISPLAY=a.display,SDL_VIDEODRIVER='x11',SDL_AUDIODRIVER='dummy')
  native={k:v for k,v in env.items() if not k.startswith('XR_')};native['EDUKE32_XR_TEST_SHOTS']='1'
  marker=root/'reference-change'
  xr=dict(env,XR_API_LAYER_PATH=str(a.layer_dir.resolve())+':/usr/share/openxr/1/api_layers/explicit.d',XR_ENABLE_API_LAYERS='XR_APILAYER_EDUKE32_reference_space_test:XR_APILAYER_LUNARG_core_validation',EDUKE32_TEST_REFERENCE_MARKER=str(marker),EDUKE32_XR='1',EDUKE32_XR_SINGLE_PASS='1',EDUKE32_XR_UI='2',EDUKE32_XR_AIM='right',EDUKE32_XR_WEAPON='1',EDUKE32_XR_HAND_SHOTS='1',EDUKE32_XR_TEST_INPUT='1',EDUKE32_XR_TEST_AIM='1',EDUKE32_XR_TEST_SHOTS='1',EDUKE32_XR_TEST_PVP='1',EDUKE32_XR_HUD_OUTPUT=str(labs['client']/'hud'))
  def launch(role,binary,flags,environ):
   log=(labs[role]/'game.log').open('w');logs.append(log)
   proc=subprocess.Popen([str(binary.resolve()),'-usecwd','-nosetup','-noautoload','-nologo','-ns','-nm',*flags,'-x','pipebomb_test.con'],cwd=labs[role],env=environ,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT);procs.append(proc)
   return proc,Observer(proc,labs[role]/'game.log')
  server,so=launch('server',a.binary,['-dedicated','-c1','-port',str(a.port),'-map','pipebomb.map'],native);so.wait(lambda t:'Multiplayer server initialized.' in t,timeout=18)
  x11=X11(a.display)
  with Remote(a.remote_port) as remote:
   hand=remote.packet.right;hand.pose.position.x=.2;hand.pose.position.y=1.3;hand.pose.position.z=-.5;hand.pose.orientation=orientation(12,8);remote.send()
   client,co=launch('client',a.client_binary,['-connect',f'127.0.0.1:{a.port}'],xr)
   phase='join';player=wait_for_join_barrier(x11,client,labs['client']/'game.log',so)['server_player']
   so.wait(lambda t:latest_player(t,player) is not None and latest_player(t,player)['ammo']==6 and latest_player(t,player)['frame']==0,timeout=10)
   co.wait(lambda t:'OpenXR HUD presentation: 60 frames' in t and bool(EYES.findall(t)),timeout=22);co.pause(.4)
   def trigger(down):hand.trigger_value=int(down);hand.trigger_click=down;remote.send()
   before={'camera':camera(co.text()),'eyes':eyes(co.text()),'native':latest_player(so.text(),player)}
   first=None
   if a.case=='known':
    phase='first authoritative hand throw';off=len(so.text());trigger(True);so.wait(lambda t:latest_player(t,player)['frame']==6,timeout=5);trigger(False)
    so.wait(lambda t:bool(throws(t[off:])),timeout=6);first=throws(so.text()[off:])[0]
    so.wait(lambda t:latest_player(t,player)['ammo']==5 and latest_player(t,player)['frame']==0,timeout=6)
   else:
    phase='charge before unknown transform';trigger(True);so.wait(lambda t:latest_player(t,player)['frame']==6,timeout=5)
   phase='effective reference change';off=len(co.text());server_off=len(so.text())
   marker.write_text(f'{1 if a.case=="known" else 0} .75 0 -.4 .6 300\n')
   co.wait(lambda t:bool(CHANGE.findall(t[off:])),timeout=5);co.pause(.45)
   change=list(map(int,CHANGE.findall(co.text()[off:])[-1]));after={'camera':camera(co.text()),'eyes':eyes(co.text()),'native':latest_player(so.text(),player)}
   checks={'standard_event_applied_at_effective_time':change[0]<=change[1] and change[2]==(a.case=='known'),'live_test_layer_transforms':'reference-space-layer: marker accepted' in co.text(),'native_body_stays_put':(before['native']['x'],before['native']['y'])==(after['native']['x'],after['native']['y']),'eye_positions_stable':max(abs(x-y) for x,y in zip(before['eyes'],after['eyes']))<=2,'eye_angles_stable':max(abs(x-y) for x,y in zip(before['camera'],after['camera']))<.002}
   if a.case=='unknown':
    phase='unknown charge canceled';so.wait(lambda t:latest_player(t,player)['frame']==0 and latest_player(t,player)['ammo']==6,timeout=4);so.pause(.6)
    checks['pending_throw_canceled_without_ammo_or_spawn']=not throws(so.text()[server_off:]) and latest_player(so.text(),player)['ammo']==6
    checks['held_recovery_does_not_fire']=latest_player(so.text(),player)['frame']==0 and not(latest_player(so.text(),player)['bits']&4)
    trigger(False);so.pause(.3)
   else:
    window,_=x11.owned_window(client.pid);x11.press(window,'6',.1,True)
    so.wait(lambda t:latest_player(t,player)['weapon']==5 and latest_player(t,player)['frame']==0,timeout=5)
   phase='post-change fresh throw';off=len(so.text());trigger(True);so.wait(lambda t:latest_player(t,player)['frame']==6,timeout=5);trigger(False)
   so.wait(lambda t:bool(throws(t[off:])),timeout=6);shot=throws(so.text()[off:])[0];ammo=4 if first else 5
   so.wait(lambda t:latest_player(t,player)['ammo']==ammo,timeout=5)
   co.wait(lambda t:any(r['index']==shot['index'] and r['mode']==2 for r in bombs(t)),timeout=6)
   checks.update(exactly_one_fresh_authoritative_throw=len(throws(so.text()[off:]))==1,native_ammo_and_bomb_replicate=latest_player(so.text(),player)['ammo']==ammo,hand_origin_preserved=(shot['x'],shot['y'],shot['sector'])==(1216,2125,1))
   if first:checks['same_physical_hand_same_native_shot']=all(abs(first[k]-shot[k])<=(2 if k in ('x','y','z') else 1) for k in ('x','y','z','sector','angle','xvel','zvel'))
   phase='late actual stereo';serials=list(map(int,CAPTURE.findall(co.text())));old=serials[-1] if serials else 60
   co.wait(lambda t:any(int(v)>old for v in CAPTURE.findall(t)),timeout=8);serial=int(CAPTURE.findall(co.text())[-1]);imgs=[Image.open(labs['client']/f'hud-{serial}-{eye}.ppm').convert('RGB') for eye in ('left','right')]
   checks['fresh_distinct_actual_stereo']=ImageChops.difference(*imgs).getbbox() is not None
   visibility=[]
   for proc in procs:
    window,_=x11.owned_window(proc.pid);visibility.append(x11.window_visibility(window) if window else None)
   checks['private_windows']=all(v is None or v['unmapped'] and not v['has_desktop_focus'] for v in visibility)
   checks['core_validation_clean']='Core Validation output type:' in co.text() and not re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)',co.text())
   result={'passed':all(checks.values()),'case':a.case,'checks':checks,'event':change,'before':before,'after':after,'first_throw':first,'post_change_throw':shot,'completed_HUD_frame':serial,'qualification':'real session with synthetic standard reference event and matching locate-coordinate transform; physical recentering unqualified'}
 except Exception as error:result={'passed':False,'case':a.case,'phase':phase,'error':str(error)}
 finally:
  for proc in reversed(procs):stop(proc)
  for log in logs:log.close()
 result['evidence_directory']=str(root);(root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
