#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual private native firing after terminal OpenXR initialization/draw failure."""
import argparse,json,os,re,subprocess,tempfile
from pathlib import Path
from smoke_actions import Observer
from smoke_actions_multiplayer import client_player_index
from smoke_multiplayer import CONFIG,X11,stop
from smoke_pipebomb_native import write_lab,players,bombs,latest_player


class FallbackObserver(Observer):
 def text(self):
  if self.process.poll() is not None:raise RuntimeError("owned fallback game exited")
  value=self.path.read_text(errors="replace")
  if re.search(r"Found \d+ warning\(s\), [1-9]\d* error\(s\)",value):raise RuntimeError("native CON compilation failed")
  return value


def main():
 p=argparse.ArgumentParser(description=__doc__)
 for key in ('binary','client-binary','grp','work-dir'):p.add_argument('--'+key,type=Path,required=True)
 p.add_argument('--case',choices=('init','world'),required=True);p.add_argument('--display',default=':1');p.add_argument('--port',type=int,default=24739)
 a=p.parse_args()
 if os.environ.get('EDUKE32_TEST_PRIVATE_WINDOW')!='1':p.error('private hidden windows required')
 a.work_dir.mkdir(parents=True,exist_ok=True);root=Path(tempfile.mkdtemp(prefix='fallback-',dir=a.work_dir.resolve()))
 processes=[];logs=[];phase='setup';result={'passed':False}
 try:
  labs={role:write_lab(root,role,a.grp.resolve()) for role in ('server','client')}
  for lab in labs.values():(lab/'eduke32.cfg').write_text(CONFIG)
  target='''
gamevar vrfallback_given 0 1
gamevar vrfallback_target 0 0
gamevar vrfallback_index 0 0
gamevar vrfallback_health 0 0
onevent EVENT_PROCESSINPUT
 ifvare vrpipe_given 1
 ifvare vrfallback_given 0
 {
  ifvare vrpipe_player 0
  {
   setplayer[THISACTOR].posx 3000
   setplayer[THISACTOR].oposx 3000
   setactor[THISACTOR].x 3000
   setplayer[THISACTOR].posy 2200
   setplayer[THISACTOR].oposy 2200
   setactor[THISACTOR].y 2200
   setplayer[THISACTOR].cursectnum 1
   changespritesect THISACTOR 1
  }
  setvar vrfallback_given 1
 }
 getplayer[vrfallback_target].i vrfallback_index
 getactor[vrfallback_index].extra vrfallback_health
 addlog vrfallback_health
endevent
'''
  for lab in labs.values():
   with (lab/'pipebomb_test.con').open('a') as f:f.write(target)
  env={k:v for k,v in os.environ.items() if not k.startswith('EDUKE32_XR')}
  env.update(DISPLAY=a.display,SDL_VIDEODRIVER='x11',SDL_AUDIODRIVER='dummy')
  native={k:v for k,v in env.items() if not k.startswith('XR_')}
  xr=dict(env,EDUKE32_XR='1',EDUKE32_XR_AIM='right',EDUKE32_XR_HAND_SHOTS='1',EDUKE32_XR_SINGLE_PASS='1',EDUKE32_XR_UI='2',EDUKE32_XR_TEST_SHOTS='1')
  if a.case=='init':xr['XR_RUNTIME_JSON']=str(root/'absent-runtime.json')
  else:xr['EDUKE32_XR_TEST_FAIL']='opaque'
  def launch(role,binary,flags,e):
   log=(labs[role]/'game.log').open('w');logs.append(log)
   proc=subprocess.Popen([str(binary.resolve()),'-usecwd','-nosetup','-noautoload','-nologo','-ns','-nm',*flags,'-x','pipebomb_test.con'],cwd=labs[role],env=e,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT);processes.append(proc)
   return proc,FallbackObserver(proc,labs[role]/'game.log')
  server,so=launch('server',a.binary,['-dedicated','-c1','-m','-port',str(a.port),'-map','pipebomb.map'],native)
  so.wait(lambda t:'Multiplayer server initialized.' in t,timeout=18)
  client,co=launch('client',a.client_binary,['-connect',f'127.0.0.1:{a.port}'],xr)
  phase='native join';co.wait(lambda t:'Multiplayer client level synchronization complete.' in t,timeout=25);co.pause(1.5)
  co.wait(lambda t:client_player_index(t) is not None and latest_player(t,client_player_index(t)) is not None,timeout=8)
  player=client_player_index(co.text());x11=X11(a.display);window,_=x11.owned_window(client.pid)
  if window is None:raise RuntimeError('owned private SDL window unavailable')
  if latest_player(co.text(),player)['gm']&1:x11.press(window,'Escape',.06,True)
  phase='terminal XR failure'
  failure='OpenXR world initialization failed:' if a.case=='init' else 'OpenXR world stopped:'
  co.wait(lambda t:failure in t,timeout=12)
  def health(text):
   values=re.findall(r'addlog vrfallback_health\b[^=\n]*= (-?\d+)',text)
   return int(values[-1]) if values else None
  before=health(so.text())
  so.wait(lambda t:latest_player(t,player) is not None and latest_player(t,player)['frame']==0,timeout=5)
  offset=len(so.text());phase='native keyboard hold after fallback'
  x11.send_event_key(window,'Control_R',True)
  so.wait(lambda t:any(r['frame']==6 and r['bits']&4 for r in players(t[offset:],player)),timeout=6)
  co.pause(.25);x11.send_event_key(window,'Control_R',False)
  phase='native body throw after fallback'
  so.wait(lambda t:any(r['event']==71 and r['ownerplayer']==player for r in bombs(t[offset:])),timeout=6)
  so.wait(lambda t:latest_player(t,player)['ammo']==5,timeout=5)
  co.wait(lambda t:latest_player(t,player)['ammo']==5,timeout=5)
  spawned=[r for r in bombs(so.text()[offset:]) if r['event']==71 and r['ownerplayer']==player]
  phase='native remote detonation after fallback'
  so.wait(lambda t:latest_player(t,player)['weapon']==10 and latest_player(t,player)['frame']==0,timeout=5)
  x11.send_event_key(window,'Control_R',True)
  so.wait(lambda t:latest_player(t,player)['hbomb']==0,timeout=5)
  x11.send_event_key(window,'Control_R',False)
  so.wait(lambda t:health(t)<before,timeout=6)
  co.wait(lambda t:health(t)<before,timeout=6)
  checks={'actual_terminal_XR_failure':failure in co.text(),'native_keyboard_fire_reaches_host':any(r['frame']==6 and r['bits']&4 for r in players(so.text()[offset:],player)),'one_authoritative_native_body_bomb':len(spawned)==1 and spawned[0]['x']==1280 and spawned[0]['y']==2048,'one_ammo_consumed_and_replicated':latest_player(so.text(),player)['ammo']==latest_player(co.text(),player)['ammo']==5,'no_stale_tracked_throw':'VR native pipebomb:' not in so.text()[offset:],'client_alive_after_fallback':client.poll() is None,'private_window':x11.window_visibility(window)['unmapped'] and not x11.window_visibility(window)['has_desktop_focus']}
  checks['native_damage_replicates_after_fallback']=health(so.text())<before and health(co.text())<before
  result={'passed':all(checks.values()),'case':a.case,'checks':checks,'body_bomb':spawned[0]}
 except Exception as error:result={'passed':False,'case':a.case,'phase':phase,'error':str(error)}
 finally:
  for proc in reversed(processes):stop(proc)
  for log in logs:log.close()
 result['evidence_directory']=str(root);(root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
