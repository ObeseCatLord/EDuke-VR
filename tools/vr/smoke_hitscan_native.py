#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare actual native pistol impacts/events against a pre-change binary.

Both native dedicated/client pairs run without OpenXR or hand input. Uses the
same controlled zero-spread CON fixture and caller-owned GRP read-only.
"""
import argparse,json,os,re,shutil,subprocess,tempfile
from pathlib import Path
from smoke_actions import Observer
from smoke_actions_multiplayer import client_player_index
from smoke_hitscan import samples,spark_hits
from smoke_hand_shots import room
from smoke_multiplayer import X11,setup_lab,stop

def run(binary,grp,root,display,port):
 server=client=None;logs=[]
 try:
  sl=setup_lab(root,'server',grp,False);cl=setup_lab(root,'client',grp,False)
  for lab in (sl,cl):
   for name in ('controller_test.con','aim_test.con','hand_test.con','hitscan_test.con'):shutil.copyfile(Path(__file__).parent/'fixtures'/name,lab/name)
   (lab/'hand.map').write_bytes(room())
   wrapper=lab/'hitscan_test.con';wrapper.write_text(wrapper.read_text()+'\nonevent EVENT_DOFIRE\n ifvarg vrscan_pre 0 setvar RETURN 1\nendevent\n')
  env={k:v for k,v in os.environ.items() if not k.startswith(('EDUKE32_XR','XR_'))};env.update(DISPLAY=display,SDL_VIDEODRIVER='x11',SDL_AUDIODRIVER='dummy')
  for role,lab in (('server',sl),('client',cl)):
   log=(lab/(role+'.log')).open('w');logs.append(log)
   command=[str(binary),'-usecwd','-nosetup','-noautoload','-x','hitscan_test.con']
   if role=='server':command+=['-dedicated','-port',str(port),'-map','hand.map']
   else:command+=['-nologo','-ns','-nm','-connect',f'127.0.0.1:{port}']
   process=subprocess.Popen(command,cwd=lab,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
   if role=='server':
    server=process;so=Observer(server,sl/'server.log');so.wait(lambda t:'Multiplayer server initialized.' in t)
   else:client=process;co=Observer(client,cl/'client.log')
  co.wait(lambda t:'Multiplayer client level synchronization complete.' in t,timeout=20);co.pause(1.6)
  x=X11(display);window,_=x.owned_window(client.pid)
  if not window:raise RuntimeError('owned native client window missing')
  if client_player_index(co.text()) is None:x.press(window,'Escape',.06,True)
  co.wait(lambda t:client_player_index(t) not in (None,0),timeout=10);player=client_player_index(co.text())
  so.wait(lambda t:len(samples(t,'ammo',player))>30)
  before=samples(so.text(),'ammo',player)[-1];offset=len(so.text());x.press(window,'Control_R',.10,True)
  so.wait(lambda t:bool(spark_hits(t[offset:],player)),timeout=4);so.pause(.3)
  hits=spark_hits(so.text()[offset:],player);events={k:len(samples(so.text()[offset:],k,player)) for k in ('pre','range','auto')}
  return {'impacts':hits,'event_counts':events,'ammo_used':before-samples(so.text(),'ammo',player)[-1],'hand_ray_absent':'VR native hitscan:' not in so.text()}
 finally:
  stop(client);stop(server)
  for f in logs:f.close()

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('binary','reference-binary','grp','work-dir'):p.add_argument('--'+n,type=Path,required=True)
 p.add_argument('--display',default=':1');p.add_argument('--port',type=int,default=24597);a=p.parse_args()
 a.work_dir.mkdir(parents=True,exist_ok=True);root=Path(tempfile.mkdtemp(prefix='hitscan-native-',dir=a.work_dir.resolve()))
 try:
  results={}
  for name,binary in (('reference',a.reference_binary),('current',a.binary)):
   sub=root/name;sub.mkdir();results[name]=run(binary.resolve(),a.grp.resolve(),sub,a.display,a.port)
  old,new=results['reference'],results['current']
  checks={'actual_native_impacts_equal':bool(old['impacts']) and old['impacts']==new['impacts'],'native_event_counts_equal':old['event_counts']==new['event_counts'],'native_ammo_equal':old['ammo_used']==new['ammo_used']>0,'no_hand_override':old['hand_ray_absent'] and new['hand_ray_absent']}
  result={'passed':all(checks.values()),'checks':checks,**results}
 except Exception as e:result={'passed':False,'error':str(e)}
 result['evidence_directory']=str(root);(root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
