#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual OpenXR HUD coverage, full-eye tint, depth, and native callback proof.

Requires an already-running private Monado runtime and an owned GRP. Uses only
its own process/window. This qualifies native ART UI, not tracked 3D weapons.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import time
import numpy as np
from PIL import Image
from smoke_multiplayer import X11, stop
from smoke_world import CONFIG


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('binary','grp','work-dir'): p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--display',default=':1')
    p.add_argument('--tint',choices=('0','1','2','3'),default='0')
    p.add_argument('--native-menu',choices=('none','main','save'),default='none')
    p.add_argument('--resize',action='store_true')
    p.add_argument('--console',action='store_true')
    p.add_argument('--invalid-pose-once',action='store_true')
    p.add_argument('--nested-swap-once',action='store_true')
    a=p.parse_args(); a.work_dir.mkdir(parents=True,exist_ok=True)
    lab=Path(tempfile.mkdtemp(prefix='hud-',dir=a.work_dir.resolve()))
    (lab/'eduke32.cfg').write_text(CONFIG)
    (lab/'DUKE3D.GRP').symlink_to(a.grp.resolve())
    shutil.copyfile(Path(__file__).parent/'fixtures/hud_test.con',lab/'hud_test.con')
    # Local test pixels only; no owned game assets are copied into this fixture.
    (lab/'tiles099.art').write_bytes(struct.pack('<4i',1,2,30000,30001)+struct.pack('<2h',16,16)
                                   +struct.pack('<2h',16,16)+bytes(8)+bytes([255])*256+bytes([196])*256)
    env=dict(os.environ,DISPLAY=a.display,SDL_VIDEODRIVER='x11',SDL_AUDIODRIVER='dummy',EDUKE32_XR='1',
             EDUKE32_XR_UI='2',EDUKE32_XR_SINGLE_PASS='1',EDUKE32_XR_WORLD_OUTPUT=str(lab/'world'),
             EDUKE32_XR_HUD_OUTPUT=str(lab/'hud'))
    for key in ('EDUKE32_XR_TEST_ZERO_IPD','EDUKE32_XR_TEST_STEREO_POSE','EDUKE32_XR_TEST_FAIL',
                'EDUKE32_XR_TEST_MENU_POSE','EDUKE32_XR_TEST_MENU_NESTED','EDUKE32_XR_TEST_HUD_TINT','EDUKE32_XR_TEST_HUD_MENU'):
        env.pop(key,None)
    if a.tint!='0': env['EDUKE32_XR_TEST_HUD_TINT']=a.tint
    if a.native_menu!='none': env['EDUKE32_XR_TEST_HUD_MENU']='2' if a.native_menu=='save' else '1'
    if a.native_menu=='save': env['EDUKE32_XR_TEST_AUX_OUTPUT']=str(lab/'auxiliary.ppm')
    if a.invalid_pose_once: env['EDUKE32_XR_TEST_MENU_POSE']='1'
    if a.nested_swap_once: env['EDUKE32_XR_TEST_MENU_NESTED']='1'
    result={'passed':False}
    with (lab/'hud.log').open('w') as log:
        process=subprocess.Popen([str(a.binary.resolve()),'-usecwd','-nosetup','-noautoload','-nologo','-ns','-nm',
                                  '-v1','-l1','-s1','-x','hud_test.con'],cwd=lab,env=env,
                                 stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        try:
            x=X11(a.display); resized=False; console_open=False; session_seen=None
            end=time.monotonic()+30
            while time.monotonic()<end:
                text=(lab/'hud.log').read_text(errors='replace')
                if process.poll() is not None: raise RuntimeError('owned game exited')
                if session_seen is None and 'OpenXR experimental Polymost world session started' in text: session_seen=time.monotonic()
                if a.console and not console_open and session_seen is not None and time.monotonic()-session_seen>1.2:
                    window,_=x.owned_window(process.pid)
                    if window: x.press(window,'quoteleft',.06,True); console_open=True
                if a.resize and not resized and 'OpenXR masks single-pass: frame=4' in text:
                    window,_=x.owned_window(process.pid)
                    if window:
                        import ctypes as c
                        x.x.XResizeWindow.argtypes=[c.c_void_p,c.c_ulong,c.c_uint,c.c_uint]
                        x.x.XResizeWindow(x.display,window,800,600); x.x.XSync(x.display,0); resized=True
                if 'OpenXR world stopped:' in text: raise RuntimeError('XR stopped; inspect owned HUD log')
                if 'OpenXR world oracle: 60 frames' in text and (lab/'hud-coverage.pgm').is_file(): break
                time.sleep(.05)
            else: raise RuntimeError('HUD projection/capture timeout')
            alpha=np.array(Image.open(lab/'hud-coverage.pgm'))
            ui=np.array(Image.open(lab/'hud-ui.ppm'))
            before=[np.array(Image.open(lab/f'world-{eye}.ppm')) for eye in ('left','right')]
            after=[np.array(Image.open(lab/f'hud-{eye}.ppm')) for eye in ('left','right')]
            checks={'actual_60_HUD_projections':'OpenXR HUD presentation: 60 frames' in text,
                    'stereo_worlds_and_final_images_distinct':not np.array_equal(before[0],before[1]) and not np.array_equal(after[0],after[1]),
                    'zero_coverage_survives':int((alpha==0).sum())>alpha.size//2,
                    'opaque_zero_alpha_ART_has_coverage_one':int((alpha[:200,:400]==255).sum())>2000,
                    'two_thirds_source_coverage':int((alpha==170).sum())>1000,
                    'one_third_source_coverage':int((alpha==85).sum())>1000,
                    'overlap_source_over_coverage':int(((alpha==198)|(alpha==199)).sum())>100,
                    'UI_does_not_write_world_depth':all((lab/f'world-{eye}-depth.bin').read_bytes()==(lab/f'hud-{eye}-depth.bin').read_bytes() for eye in ('left','right'))}
            counts=dict((key,int(val)) for key,val in re.findall(r'addlog vrhud_(rooms|roomend|weapon|rest)[^=\n]*= (\d+)',text))
            # Compare against an actual flat reference; startup intentionally
            # renders an extra room before its first DISPLAYREST callback.
            flat_env=dict(env,EDUKE32_XR='0')
            if a.native_menu=='save': flat_env['EDUKE32_XR_TEST_AUX_OUTPUT']=str(lab/'native-auxiliary.ppm')
            for key in ('EDUKE32_XR_TEST_MENU_NESTED','EDUKE32_XR_TEST_MENU_POSE'):
                flat_env.pop(key,None)
            with (lab/'native.log').open('w') as flat_log:
                flat=subprocess.Popen([str(a.binary.resolve()),'-usecwd','-nosetup','-noautoload','-nologo','-ns','-nm',
                                       '-v1','-l1','-s1','-x','hud_test.con'],cwd=lab,env=flat_env,
                                      stdin=subprocess.DEVNULL,stdout=flat_log,stderr=subprocess.STDOUT)
                try:
                    deadline=time.monotonic()+15
                    while time.monotonic()<deadline:
                        native=(lab/'native.log').read_text(errors='replace')
                        if re.search(r'addlog vrhud_rest[^=\n]*= 60',native): break
                        if flat.poll() is not None: raise RuntimeError('flat reference exited')
                        time.sleep(.05)
                    else: raise RuntimeError('flat callback reference timeout')
                    native_counts=dict((key,int(val)) for key,val in re.findall(r'addlog vrhud_(rooms|roomend|weapon|rest)[^=\n]*= (\d+)',native))
                finally: stop(flat)
            checks['native_callback_counts_match']=len(counts)==4 and counts==native_counts and counts['weapon']==60
            if a.native_menu=='save' or a.console:
                # The large opaque native save panel covers the transparency
                # rectangles. Their coverage algebra is tested in other cases.
                for key in ('zero_coverage_survives','opaque_zero_alpha_ART_has_coverage_one',
                            'two_thirds_source_coverage','one_third_source_coverage','overlap_source_over_coverage'):
                    checks.pop(key)
            if a.console:
                checks['console_visible_in_captured_frame']=console_open and bool(re.search(r'osdRows=[1-9]\d*;',text))
                checks['console_capture_has_coverage']=int((alpha>0).sum())>alpha.size//3
            if a.native_menu=='save':
                checks['save_panel_has_opaque_and_transparent_coverage']=int((alpha==255).sum())>alpha.size*.75 and int((alpha==0).sum())>alpha.size*.05
                checks['auxiliary_native_readback_target_restored']='auxiliary readback test: readFbo=0 drawFbo=0' in text
                auxiliary=np.array(Image.open(lab/'auxiliary.ppm'))
                native_auxiliary=np.array(Image.open(lab/'native-auxiliary.ppm'))
                checks['actual_auxiliary_readbacks_nonconstant']=all(int(image.max())>int(image.min()) for image in (auxiliary,native_auxiliary))
                checks['native_extra_room_callback_retained']=counts['rooms']==counts['roomend']==62
            # The panel is well inside these peripheral strips. Full-eye effects
            # must touch them too. Reference applies native encoded-value blend.
            border=np.zeros(alpha.shape,dtype=bool); border[:30]=True; border[-30:]=True; border[:,:30]=True; border[:,-30:]=True
            tint=np.array([80,120,200],dtype=float)/255
            if a.tint in ('2','3'):
                brightness,contrast,saturation=(.9,1.1,.8) if a.tint=='2' else (1.15,1.4,1.3)
                luma=tint@np.array([.2126,.7152,.0722])
                # Native correction matrices translate by the input alpha.
                tint=np.clip((tint*saturation+luma*(1-saturation))*contrast
                             +(.5*(1-contrast)+brightness-1)*(96/255),0,1)
            errors=[]
            for old,new in zip(before,after):
                expected=old.astype(float)
                if a.native_menu!='none': expected=np.rint(expected*(1-168/255))
                if a.tint!='0': expected=np.rint(expected*(1-96/255)+tint*96)
                expected=expected.clip(0,255).astype(np.uint8)
                errors.append(int(np.abs(new[border].astype(int)-expected[border].astype(int)).max()))
            checks['periphery_native_tint' if a.tint!='0' else 'periphery_world_unchanged']=max(errors)<=(1 if a.tint!='0' or a.native_menu!='none' else 0)
            if a.tint!='0':
                old_ui=np.array(Image.open(lab/'hud-untinted-ui.ppm')).astype(float)
                expected=np.rint(old_ui*(1-96/255)+tint*96*(alpha[:,:,None]/255)).clip(0,255).astype(np.uint8)
                ui_error=int(np.abs(ui.astype(int)-expected.astype(int)).max())
                checks['tint_UI_premultiplied_coverage_preserved']=ui_error<=1
            if a.native_menu!='none': checks['native_menu_exercised']='opened native '+('save' if a.native_menu=='save' else 'in-game')+' menu.' in text
            if a.resize: checks['resized_world_and_UI_extent']=resized and alpha.shape==(600,800) and 'OpenXR world extent changed at native frame boundary: 800x600.' in text
            # An opaque index-255 rectangle is visible in coverage, while an
            # identical masked tile to its right leaves no rectangle of coverage.
            checks['no_RGB_in_zero_coverage']=bool((ui[alpha==0]==0).all())
            if 'XR_APILAYER_LUNARG_core_validation' in env.get('XR_ENABLE_API_LAYERS',''):
                checks['core_validation_active']='Core Validation output type:' in text
                checks['core_validation_no_warning_or_error']=not bool(re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)',text))
            if a.invalid_pose_once: checks['pose_loss_recovers']='injected temporary invalidity' in text
            if a.nested_swap_once: checks['nested_unarmed_swap_recovers']='injected unarmed native presentation' in text
            result={'passed':all(checks.values()),'checks':checks,'callback_counts':counts,'native_reference_counts':native_counts,
                    'periphery_max_channel_error':errors,'tint':a.tint,'native_menu':a.native_menu,
                    'UI_tint_max_channel_error':ui_error if a.tint!='0' else None,
                    'coverage_values':{str(v):int((alpha==v).sum()) for v in (0,85,170,198,199,255)}}
        except Exception as error: result={'passed':False,'error':str(error)}
        finally: stop(process)
    result['evidence_directory']=str(lab)
    (lab/'result.json').write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps(result,indent=2))
    return 0 if result['passed'] else 1

if __name__=='__main__': raise SystemExit(main())
