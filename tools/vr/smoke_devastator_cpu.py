#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual native MP Devastator proof in a GPU-denied SDL-dummy namespace.

Tracked cases publish simulated poses through the native setter, not OpenXR.
The original client sends/authenticates its real movement tail; the server
runs real weapon/actor/damage code. This is no graphics/headset qualification.
"""
import argparse,json,os,re,struct,sys,tempfile
from pathlib import Path
from PIL import Image,ImageChops
from smoke_native_levels import assert_cpu_binary,assert_gpu_devices_absent,sanitised_env
from smoke_pipebomb_native import Run,write_lab,join,sha256
from smoke_hand_shots import room

PLAYER=('tick','player','ammo','frame','hold','pending','bits','health','gm','psindex','x','y','z')
SHOT=('index','tile','owner','shooter','sector','px','py','pz','angle','speed','zvel','size','damage','clock','seed','phase')
PAT=re.compile(r'addlog vrw_(\w+)\b[^=\n]*= (-?\d+)')
def rows(text,keys):
 result=[];row={}
 for key,val in PAT.findall(text):
  if key not in keys:continue
  if key==keys[0]:row={}
  row[key]=int(val)
  if key==keys[-1] and len(row)==len(keys):result.append(row)
 return result

def players(text,p):return [r for r in rows(text,PLAYER) if r['player']==p]
def last(text,p):
 values=players(text,p);return values[-1] if values else None

def shots(text,p,phase=1):return [r for r in rows(text,SHOT) if r['shooter']==p and r['phase']==phase]
def count(text,key):
 values=[int(v) for k,v in PAT.findall(text) if k==key];return values[-1] if values else 0

def sandbox(args):
 if args._sandboxed:return
 work=args.work_dir.resolve();work.mkdir(parents=True,exist_ok=True);env=sanitised_env()
 cmd=['bwrap','--ro-bind','/','/','--dev','/dev','--proc','/proc','--unshare-pid','--bind',str(work),str(work),'--chdir',str(Path.cwd()),'--clearenv']
 for key in ('PATH','LANG','LC_ALL','TZ'):
  if key in env:cmd+=['--setenv',key,env[key]]
 cmd += [sys.executable,str(Path(__file__).resolve()),*sys.argv[1:],'--_sandboxed']
 os.execvpe('bwrap',cmd,env)

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('binary','input-helper','grp','work-dir'):p.add_argument('--'+name,type=Path,required=True)
 p.add_argument('--capture',action='store_true');p.add_argument('--reference-result',type=Path);p.add_argument('--port',type=int,default=24741);p.add_argument('--case',choices=('flat','tracked','wall','vertical','loss'),default='tracked');p.add_argument('--_sandboxed',action='store_true',help=argparse.SUPPRESS);a=p.parse_args()
 if a.reference_result and a.case!='flat':p.error('--reference-result applies only to the native flat comparison')
 for key in ('binary','input_helper','grp'):setattr(a,key,getattr(a,key).resolve())
 sandbox(a);assert_gpu_devices_absent();assert_cpu_binary(a.binary)
 root=Path(tempfile.mkdtemp(prefix='devastator-',dir=a.work_dir.resolve()));run=Run(a,root);run.env['EDUKE32_XR_TEST_SHOTS']='1';phase='setup';result={'passed':False}
 try:
  for role in ('server','client'):
   lab=write_lab(root,role,a.grp);run.labs[role]=lab
   fixture=(Path(__file__).parent/'fixtures/hand_weapon_test.con').read_text()
   fixture=fixture.replace('5500','4450' if a.case=='flat' else '5800')
   (lab/'pipebomb_test.con').write_text(fixture)
   geometry=bytearray(room(a.case=='wall'))
   if a.case=='vertical':
    # Keep the actual upward projectile alive through a native world update.
    # The ordinary ceiling is reached before a snapshot can include it.
    for offset in (26,66):struct.pack_into('<i',geometry,offset,-131072)
   (lab/'pipebomb.map').write_bytes(geometry)
   if a.case=='loss':
    with (lab/'pipebomb_test.con').open('a') as f:f.write('\nonevent EVENT_PROCESSINPUT\n setvar WEAPON7_SHOTSPERBURST 4\nendevent\n')
  so=run.launch('server',['-dedicated','-c1','-m','-port',str(a.port),'-map','pipebomb.map']);so.wait(lambda t:'User Map: /pipebomb.map' in t,timeout=18)
  phase='native client join';player=join(run);co=run.observers['client']
  so.wait(lambda t:last(t,player) is not None and last(t,player)['ammo']==40 and last(t,player)['frame']==0,timeout=12)
  co.wait(lambda t:'features=15' in t,timeout=5)
  def pose(flags=3):
   offset=(192,77,1843);direction=(32051,6813,0)
   if a.case=='wall':direction=(-4096,-32510,0) # Near-parallel, away from wall after spawn.
   if a.case=='vertical':direction=(0,0,-32767)
   vals=(flags,*(offset if flags==3 else (0,0,0)),*(direction if flags==3 else (0,0,0)))
   os.write(run.writers['client'],('pose '+' '.join(map(str,vals))+'\n').encode())
  tracked=a.case!='flat'
  if tracked:
   pose();co.wait(lambda t:'pose published flags=3' in t,timeout=5);so.pause(.3)
  native_capture={}
  if a.capture:native_capture['before']=run.capture('client')
  before=last(so.text(),player);target_before=last(so.text(),0)['health'];observations=[]
  burst_size=4 if a.case=='loss' else 2
  def burst():
   client_count=count(co.text(),'post');n=len(shots(so.text(),player));off=len(so.text())
   run.key('client',228,True)
   co.wait(lambda t:count(t,'post')>client_count,timeout=5)
   run.key('client',228,False)
   so.wait(lambda t:len(shots(t,player))>=n+burst_size,timeout=7)
   so.wait(lambda t:last(t,player)['frame']==0 and last(t,player)['pending']==0 and not(last(t,player)['bits']&4),timeout=5)
   so.pause(.3);new=shots(so.text()[off:],player)
   observations.append({'shots':new,'ammo':last(so.text(),player)['ammo'],'player':last(so.text(),player)})
   return new
  phase='first native two-shot burst'
  if a.case=='loss':
   # Cancel during the delayed native burst by invalidating at first local
   # callback; preserve a separately observed source/release recovery phase.
   off=len(so.text());n=count(co.text(),'post');run.key('client',228,True)
   co.wait(lambda t:count(t,'post')>n,timeout=5);pose(1)
   so.pause(.5);invalid={'shots':shots(so.text()[off:],player),'player':last(so.text(),player)}
   pose();so.pause(.5);held={'shots':shots(so.text()[off:],player),'player':last(so.text(),player)}
   run.key('client',228,False);so.pause(.25);first=burst()
  else:
   first=burst();phase='second native alternating burst';second=burst();invalid=held=None
  phase='native live client replication';allshots=shots(so.text(),player)
  co.wait(lambda t:bool(shots(t,player,2)),timeout=8)
  replicated=shots(co.text(),player,2)
  co.wait(lambda t:last(t,player)['ammo']==last(so.text(),player)['ammo'],timeout=5)
  if a.case in ('tracked','flat'):
   phase='actual native wall impact/damage';so.wait(lambda t:count(t,'expl')>0,timeout=8);so.pause(.4)
  checks={'actual_player_and_capability':player==1 and 'features=15' in so.text(),'native_configured_bursts':all(len(b['shots'])==burst_size for b in observations),'native_delayed_cadence':all(all(y['clock']-x['clock']==8 for x,y in zip(b['shots'],b['shots'][1:])) for b in observations),'native_one_ammo_per_projectile':last(so.text(),player)['ammo']==40-len(allshots),'native_half_size_and_quarter_damage':all(s['size']==7 and 20<=s['damage']<=35 for s in allshots),'native_owner_matches_actual_player':all(s['owner']==before['psindex'] for s in allshots),'native_projectile_indices_seen_on_client':all(any(r['index']==s['index'] for r in replicated) for s in allshots),'native_ammo_replicates':last(co.text(),player)['ammo']==last(so.text(),player)['ammo'],'native_body_stays_put':(before['x'],before['y'])==(last(so.text(),player)['x'],last(so.text(),player)['y']),'no_gpu_devices_or_libraries':True}
  if a.case in ('flat','tracked'):
   checks['native_actual_explosion']=count(so.text(),'expl')>0
   checks['native_target_damage']=last(so.text(),0)['health']<target_before
   co.wait(lambda t:last(t,0)['health']==last(so.text(),0)['health'],timeout=5);checks['native_target_damage_replicates']=True
  if len(observations)==2:checks['native_launcher_state_alternates']=observations[0]['player']['hold']!=observations[1]['player']['hold']
  if tracked:
   checks['tracked_native_projectile_path']='VR native projectile:' in so.text()
   if a.case=='wall':checks['final_origin_inside_closed_wall']=all(s['px']<=1136 and s['sector']==0 for s in allshots)
   else:checks['hand_origin_in_resolved_sector']=all(s['sector']==1 and abs(s['px']-1216)<=64 and abs(s['py']-4173)<=64 for s in allshots)
   if a.case=='vertical':checks['vertical_projectiles_use_physical_vector']=all(s['speed']==0 and -10600<s['zvel']<-9900 for s in allshots)
   elif a.case=='tracked':checks['horizontal_physical_heading_with_native_spread']=all(52<=s['angle']<=85 and s['speed']==644 and -255<=s['zvel']<=256 for s in allshots)
   if a.case=='loss':checks['loss_cancels_pending_burst_without_extra_ammo']=invalid['player']['pending']==0 and invalid['player']['frame']==0 and invalid['player']['ammo']==40-len(invalid['shots']);checks['held_recovery_does_not_fire']=len(held['shots'])==len(invalid['shots']) and not(held['player']['bits']&4)
  else:checks['flat_path_has_no_hand_override']='VR native projectile:' not in so.text()
  if a.capture:
   native_capture['after']=run.capture('client')
   images=[Image.open(run.labs['client']/'screenshots'/native_capture[k]).convert('RGB') for k in ('before','after')]
   checks['actual_native_CPU_frames_nonconstant']=all(any(lo!=hi for lo,hi in im.getextrema()) for im in images)
   checks['actual_native_CPU_frame_changes_after_firing']=ImageChops.difference(*images).getbbox() is not None
  comparison=None
  if a.reference_result:
   reference=json.loads(a.reference_result.read_text())
   keys=('tile','owner','shooter','sector','px','py','pz','angle','speed','zvel','size','damage','seed','phase')
   canonical=lambda rows:[{k:r[k] for k in keys} for r in rows]
   equal=reference.get('passed') and reference.get('case')=='flat' and canonical(reference['all_authoritative_shots'])==canonical(allshots)
   checks['native_reference_projectiles_and_random_state_equal']=bool(equal)
   checks['native_reference_burst_ammo_equal']=[b['ammo'] for b in reference['observations']]==[b['ammo'] for b in observations]
   comparison={'reference_binary_sha256':reference['binary_sha256'],'compared_fields':keys,'qualification':'controlled CON seed; allocation indices and inter-session damage magnitudes are not equality assertions'}
  run.audit()
  result={'passed':all(checks.values()),'case':a.case,'checks':checks,'binary_sha256':sha256(a.binary),'qualification':'CPU native weapon, wire, actor and damage only; simulated native pose, no OpenXR/headset/SPS proof','observations':observations,'all_authoritative_shots':allshots,'client_actor_indices':sorted({r['index'] for r in replicated}),'target_health':{'before':target_before,'server':last(so.text(),0)['health'],'client':last(co.text(),0)['health']},'invalid':invalid,'held':held,'native_reference_comparison':comparison,'native_capture':native_capture}
 except Exception as error:result={'passed':False,'case':a.case,'phase':phase,'error':str(error)}
 finally:run.close()
 result['evidence_directory']=str(root);(root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
