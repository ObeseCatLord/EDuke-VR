#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Private native SDL minimized/restored events with live XR frame submissions.

Injects SDL events into the owned hidden process. Does not manipulate the real
window manager; that desktop/physical-headset transition remains unqualified.
"""
import argparse,json,os,re,shutil,subprocess,tempfile
from pathlib import Path
from PIL import Image,ImageChops
from monado_remote import Remote
from smoke_actions import Observer,samples
from smoke_multiplayer import CONFIG,X11,stop
from smoke_hand_shots import room


def main():
 p=argparse.ArgumentParser(description=__doc__)
 for key in ('binary','grp','work-dir','event-helper'):p.add_argument('--'+key,type=Path,required=True)
 p.add_argument('--remote-port',type=int,required=True);p.add_argument('--display',default=':1');a=p.parse_args()
 if os.environ.get('EDUKE32_TEST_PRIVATE_WINDOW')!='1':p.error('private hidden window required')
 a.work_dir.mkdir(parents=True,exist_ok=True);lab=Path(tempfile.mkdtemp(prefix='minimized-',dir=a.work_dir.resolve()))
 (lab/'DUKE3D.GRP').symlink_to(a.grp.resolve());(lab/'eduke32.cfg').write_text(CONFIG);(lab/'autoexec.cfg').write_text('r_maxfps 30\n');(lab/'test.map').write_bytes(room())
 shutil.copyfile(Path(__file__).parent/'fixtures/controller_test.con',lab/'controller_test.con')
 fifo=lab/'window-events';os.mkfifo(fifo,0o600);fd=os.open(fifo,os.O_RDWR|os.O_NONBLOCK)
 env={k:v for k,v in os.environ.items() if not k.startswith('EDUKE32_XR')}
 env.update(DISPLAY=a.display,SDL_VIDEODRIVER='x11',SDL_AUDIODRIVER='dummy',LD_PRELOAD=str(a.event_helper.resolve()),EDUKE32_TEST_WINDOW_EVENTS=str(fifo),EDUKE32_XR='1',EDUKE32_XR_SINGLE_PASS='1',EDUKE32_XR_UI='2',EDUKE32_XR_AIM='right',EDUKE32_XR_TEST_INPUT='1',EDUKE32_XR_TEST_PVP='1',EDUKE32_XR_HUD_OUTPUT=str(lab/'hud'))
 proc=None;result={'passed':False};phase='launch'
 receipts=re.compile(r'OpenXR PvP frame: submitted=(\d+) captured=1')
 try:
  with Remote(a.remote_port) as remote,(lab/'game.log').open('w') as log:
   proc=subprocess.Popen([str(a.binary.resolve()),'-usecwd','-nosetup','-noautoload','-nologo','-ns','-nm','-map','test.map','-x','controller_test.con'],cwd=lab,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
   ob=Observer(proc,lab/'game.log');ob.wait(lambda t:'OpenXR HUD presentation: 60 frames' in t and bool(samples(t)),timeout=25)
   before=samples(ob.text())[-1];phase='native minimized event';offset=len(ob.text());os.write(fd,b'm')
   ob.wait(lambda t:'Private SDL window: minimized.' in t[offset:],timeout=5)
   remote.packet.left.thumbstick.y=.65;remote.send()
   ob.wait(lambda t:any(int(v)>=180 for v in receipts.findall(t)),timeout=12)
   minimized=samples(ob.text())[-1];remote.neutral()
   min_serial=int(receipts.findall(ob.text())[-1]);imgs=[Image.open(lab/f'hud-{min_serial}-{eye}.ppm').convert('RGB') for eye in ('left','right')]
   for eye,img in zip(('left','right'),imgs):img.save(lab/f'minimized-{eye}.png')
   phase='native restored event';offset=len(ob.text());os.write(fd,b'r');ob.wait(lambda t:'Private SDL window: restored.' in t[offset:],timeout=5)
   ob.wait(lambda t:any(int(v)>min_serial for v in receipts.findall(t)),timeout=8)
   x11=X11(a.display);window,_=x11.owned_window(proc.pid);visibility=x11.window_visibility(window)
   checks={'actual_minimized_native_dispatch':'Private SDL window: minimized.' in ob.text(),'fresh_XR_projection_while_minimized':min_serial>=180,'native_simulation_and_movement_continue':minimized['tick']>before['tick'] and (minimized['x'],minimized['y'])!=(before['x'],before['y']),'distinct_actual_stereo_while_minimized':ImageChops.difference(*imgs).getbbox() is not None,'projection_after_restore':any(int(v)>min_serial for v in receipts.findall(ob.text())),'private_window':visibility['unmapped'] and not visibility['has_desktop_focus']}
   result={'passed':all(checks.values()),'checks':checks,'before':before,'minimized':minimized,'submitted_while_minimized':min_serial,'qualification':'injected owned SDL window events; no real window-manager or physical-headset transition'}
 except Exception as error:result={'passed':False,'phase':phase,'error':str(error)}
 finally:stop(proc);os.close(fd)
 result['evidence_directory']=str(lab);(lab/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
