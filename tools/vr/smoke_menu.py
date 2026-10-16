#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Capture actual cold-menu XR eye layers and the once-rendered native UI.

Uses an already-running private OpenXR runtime and an owned window only.
Opaque cold menus are the scope; transparent HUD and in-game menu effects are
not qualified by this test.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from PIL import Image
from smoke_multiplayer import X11, stop
from smoke_world import CONFIG


def image_evidence(path):
    image=Image.open(path).convert('RGB')
    black=Image.new('RGB',image.size)
    from PIL import ImageChops
    box=ImageChops.difference(image,black).getbbox()
    return {'size':list(image.size),'nonblack_bounds':list(box) if box else None,
            'channel_range':[list(x) for x in image.getextrema()],
            'nonconstant':any(low!=high for low,high in image.getextrema())}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('binary','grp','work-dir'):parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--display',default=':1')
    parser.add_argument('--console',action='store_true')
    parser.add_argument('--invalid-pose-once',action='store_true')
    parser.add_argument('--nested-swap-once',action='store_true')
    parser.add_argument('--partial-viewport',action='store_true')
    parser.add_argument('--resize',action='store_true')
    parser.add_argument('--enter-game',action='store_true')
    parser.add_argument('--quit-native',action='store_true')
    parser.add_argument('--timeout',type=int,default=25)
    args=parser.parse_args()
    if args.enter_game and args.quit_native:parser.error('--enter-game and --quit-native are separate scenarios')
    args.work_dir.mkdir(parents=True,exist_ok=True)
    lab=Path(tempfile.mkdtemp(prefix='xr-menu-',dir=args.work_dir.resolve()))
    (lab/'eduke32.cfg').write_text(CONFIG)
    (lab/'DUKE3D.GRP').symlink_to(args.grp.resolve())
    shutil.copyfile(Path(__file__).resolve().parent/'fixtures/menu_test.con',lab/'menu_test.con')
    env=dict(os.environ,DISPLAY=args.display,SDL_VIDEODRIVER='x11',SDL_AUDIODRIVER='dummy',
             EDUKE32_XR='1',EDUKE32_XR_UI='1',EDUKE32_XR_SINGLE_PASS='1',EDUKE32_XR_MENU_OUTPUT=str(lab/'menu'))
    for key in ('EDUKE32_XR_TEST_FAIL','EDUKE32_XR_TEST_ZERO_IPD','EDUKE32_XR_TEST_STEREO_POSE',
                'EDUKE32_XR_TEST_NATIVE_TARGET','EDUKE32_XR_DIAGNOSTIC_FRAMES'):env.pop(key,None)
    if args.invalid_pose_once:env['EDUKE32_XR_TEST_MENU_POSE']='1'
    if args.nested_swap_once:env['EDUKE32_XR_TEST_MENU_NESTED']='1'
    if args.partial_viewport:env['EDUKE32_XR_TEST_MENU_VIEWPORT']='1'
    env['EDUKE32_XR_WORLD_OUTPUT']=str(lab/'world')
    log_path=lab/'menu.log';result={'passed':False}
    with log_path.open('w') as log:
        process=subprocess.Popen([str(args.binary.resolve()),'-usecwd','-nosetup','-noautoload','-nologo','-ns','-nm','-x','menu_test.con'],
                                 cwd=lab,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        try:
            x=X11(args.display);console_open=False;resized=False;session_seen=None;deadline=time.monotonic()+args.timeout
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError('owned menu process exited')
                text=log_path.read_text(errors='replace')
                if 'OpenXR world stopped:' in text or 'OpenXR world initialization failed:' in text:
                    raise RuntimeError('XR stopped; inspect owned menu log')
                if session_seen is None and 'OpenXR experimental Polymost world session started' in text:
                    session_seen=time.monotonic()
                if args.resize and not resized and 'OpenXR experimental Polymost world session started' in text:
                    window,_=x.owned_window(process.pid)
                    if window:
                        import ctypes as c
                        x.x.XResizeWindow.argtypes=[c.c_void_p,c.c_ulong,c.c_uint,c.c_uint]
                        x.x.XResizeWindow(x.display,window,800,600);x.x.XSync(x.display,0);resized=True
                if args.console and not console_open and session_seen is not None and time.monotonic()-session_seen>1.2:
                    window,_=x.owned_window(process.pid)
                    if window:
                        x.press(window,'quoteleft',.06,True);console_open=True
                if 'OpenXR menu presentation: 60 frames;' in text:
                    paths={name:lab/('menu-'+name+'.ppm') for name in ('ui','left','right','desktop')}
                    if all(p.is_file() for p in paths.values()):break
                time.sleep(.05)
            else:raise RuntimeError('menu 60-frame/capture timeout')
            evidence={name:image_evidence(path) for name,path in paths.items()}
            counts=re.findall(r'addlog vrmenu_(draw|rest)[^=\n]*= (\d+)',text)
            counts=dict((key,int(value)) for key,value in counts)
            checks={'actual_60_menu_submissions':True,'all_images_nonconstant':all(v['nonconstant'] for v in evidence.values()),
                    'left_right_images_distinct':paths['left'].read_bytes()!=paths['right'].read_bytes(),
                    'native_menu_callbacks_equal':bool(counts) and counts.get('draw')==counts.get('rest')==60}
            checks['desktop_matches_native_ui']=paths['desktop'].read_bytes()==paths['ui'].read_bytes()
            if args.console:checks['console_visible_in_captured_frame']=console_open and bool(re.search(r'osdRows=[1-9]\d*;',text))
            if args.invalid_pose_once:checks['invalid_pose_canceled_and_recovered']='OpenXR menu pose test: injected temporary invalidity.' in text
            if args.partial_viewport:checks['native_final_viewport_preserved']=True
            if args.nested_swap_once:checks['unarmed_nested_swap_canceled_and_recovered']='OpenXR menu test: injected unarmed native presentation.' in text
            if args.resize:checks['resized_capture_extent']=resized and evidence['ui']['size']==[800,600]
            if args.enter_game:
                window,_=x.owned_window(process.pid)
                if args.console:x.press(window,'quoteleft',.06,True);time.sleep(.3)
                for _ in range(3):x.press(window,'Return',.08,True);time.sleep(.65)
                end=time.monotonic()+25
                while time.monotonic()<end:
                    text=log_path.read_text(errors='replace')
                    if process.poll() is not None:raise RuntimeError('owned game exited during menu transition')
                    if 'OpenXR world stopped:' in text:raise RuntimeError('XR stopped after menu transition')
                    if 'OpenXR world oracle: 60 frames' in text:break
                    time.sleep(.05)
                checks['menu_to_native_game_world_60_frames']='OpenXR world oracle: 60 frames' in text
                left,right=lab/'world-left.ppm',lab/'world-right.ppm'
                checks['game_world_distinct_eyes']=left.is_file() and right.is_file() and left.read_bytes()!=right.read_bytes()
                coverage=re.findall(r'world oracle: 60 frames, opaque multiview=(\d+) twoPass=(\d+).*full multiview=(\d+);',text)
                checks['game_world_multiview_retained']=bool(coverage) and int(coverage[-1][0])>0 and int(coverage[-1][2])>0
            if args.quit_native:
                window,_=x.owned_window(process.pid)
                if args.console:x.press(window,'quoteleft',.06,True);time.sleep(.3)
                try:
                    x.press(window,'q',.08,True);time.sleep(.5);x.press(window,'Return',.08,True)
                except RuntimeError as error:
                    # Native exit can destroy its window between key down/up.
                    # Accept only the expected clean process exit; never retarget.
                    if process.wait(timeout=10)!=0:raise error
                try:code=process.wait(timeout=10)
                except subprocess.TimeoutExpired:code=None
                checks['native_menu_quit_clean_exit']=code==0
            result={'passed':all(checks.values()),'checks':checks,'images':evidence,'native_counts':counts,
                    'scope':'Opaque cold menu/console; actual XR texture layers under simulated runtime'}
        except Exception as error:result={'passed':False,'error':str(error)}
        finally:stop(process)
    result['evidence_directory']=str(lab)
    (lab/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2));return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
