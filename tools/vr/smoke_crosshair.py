#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Real native-server aiming ray and two-eye depth-tested world crosshair proof."""
import argparse,json,math,os,re,shutil,struct,subprocess,tempfile
from pathlib import Path
import numpy as np
from PIL import Image
from monado_remote import Remote
from smoke_actions import Observer
from smoke_actions_multiplayer import wait_for_join_barrier
from smoke_aim import orientation,players
from smoke_hand_shots import room
from smoke_hitscan import rays
from smoke_multiplayer import X11,setup_lab,stop
from smoke_weapon import rotation
from stereo_fixture import sprite

NUMBER=r'[-+\d.eE]+'

def raster(before,ui,alpha,depth,m):
    """Invert the projected quad at pixel centres; sample native premultiplied ART.

    Native depth comes from the actual preceding world, never a made-up plane.
    Returns both depth-tested and unoccluded references to prove real occlusion.
    """
    h,w=before.shape[:2];th,tw=alpha.shape
    yy,xx=np.mgrid[:h,:w];x=2*(xx+.5)/w-1;y=1-2*(yy+.5)/h
    a=m[0,0]-x*m[3,0];b=m[0,1]-x*m[3,1];c=x*m[3,3]-m[0,3]
    d=m[1,0]-y*m[3,0];e=m[1,1]-y*m[3,1];f=y*m[3,3]-m[1,3]
    with np.errstate(divide='ignore',invalid='ignore'):
        u=(c*e-b*f)/(a*e-b*d);v=(a*f-c*d)/(a*e-b*d)
        cw=m[3,0]*u+m[3,1]*v+m[3,3]
        z=(m[2,0]*u+m[2,1]*v+m[2,3])/cw*.5+.5
    inside=(abs(u)<=1)&(abs(v)<=1)&(cw>0)&(z>=0)&(z<=1)
    sx=np.nan_to_num(np.clip((u+1)*.5*tw-.5,0,tw-1));sy=np.nan_to_num(np.clip((1-v)*.5*th-.5,0,th-1))
    x0=sx.astype(int);y0=sy.astype(int);x1=np.minimum(x0+1,tw-1);y1=np.minimum(y0+1,th-1)
    fx=(sx-x0)[:,:,None];fy=(sy-y0)[:,:,None];rgba=np.dstack([ui,alpha]).astype(float)
    sample=(rgba[y0,x0]*(1-fx)+rgba[y0,x1]*fx)*(1-fy)+(rgba[y1,x0]*(1-fx)+rgba[y1,x1]*fx)*fy
    blended=np.clip(np.rint(sample[:,:,:3]+before*(1-sample[:,:,3:4]/255)),0,255).astype(np.uint8)
    clear=np.where(inside[:,:,None],blended,before)
    # D24 readback expands to uint32; permit one storage quantization unit.
    passed=inside&(z<=depth+1/16777215)
    return np.where(passed[:,:,None],blended,before),clear,int(np.count_nonzero(inside&(sample[:,:,3]>1)&~passed))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('binary','client-binary','grp','work-dir'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--display',default=':1');p.add_argument('--remote-port',type=int,required=True);p.add_argument('--port',type=int,default=24599)
    p.add_argument('--case',choices=('base','wall','head-moved','occluded','off','lost','cancelled','custom','custom-occluded','custom-viewport','custom-nested','left','ceiling','floor','large','color','target','ceiling-slope','floor-slope'),default='base')
    p.add_argument('--pistol-shotgun',action='store_true',help='make only pistol WEAPON1_SHOOTS use SHOTGUN; retain its native WorksLike')
    a=p.parse_args();a.work_dir.mkdir(parents=True,exist_ok=True);root=Path(tempfile.mkdtemp(prefix='crosshair-',dir=a.work_dir.resolve()));server=client=None;logs=[];phase='setup';result={'passed':False}
    try:
        sl=setup_lab(root,'server',a.grp.resolve(),False);cl=setup_lab(root,'client',a.grp.resolve(),False)
        for lab in (sl,cl):
            for n in ('controller_test.con','aim_test.con','hand_test.con','hitscan_test.con'):shutil.copyfile(Path(__file__).parent/'fixtures'/n,lab/n)
            con=(lab/'hitscan_test.con').read_text()+'''\ngamevar vrch_frames 0 0\ngamevar vrch_calls 0 0\ngamevar vrch_scale 0 0\nonevent EVENT_DISPLAYCROSSHAIR\n addvar vrch_calls 1\nendevent\nonevent EVENT_DISPLAYREST\n addvar vrch_frames 1\n addlog vrch_frames\n addlog vrch_calls\n getuserdef[THISACTOR].crosshairscale vrch_scale\n addlog vrch_scale\nendevent\n'''
            if a.pistol_shotgun:
                con+="""
// Match AA's projectile override without changing pistol WorksLike.
gamevar WEAPON1_SHOOTS SHOTGUN GAMEVAR_PERPLAYER
gamevar vrch_shoots 0 0
gamevar vrch_workslike 0 0
onevent EVENT_PROCESSINPUT
 setvarvar vrch_shoots WEAPON1_SHOOTS
 setvarvar vrch_workslike WEAPON1_WORKSLIKE
 addlog vrch_shoots
 addlog vrch_workslike
endevent
"""
            if a.case=='cancelled':con+='\nonevent EVENT_DISPLAYCROSSHAIR\n setvar RETURN -1\nendevent\n'
            if a.case in ('custom','custom-occluded','custom-viewport','custom-nested'):
                # The event owns these ART pixels and deliberately suppresses
                # the built-in tile.  The two differently transformed parts
                # make an empty/returned-tile capture unable to pass.
                con+='''
onevent EVENT_DISPLAYCROSSHAIR
 rotatesprite16 10485760 6553600 65536 0 CROSSHAIR 0 0 3 0 0 xdim ydim
 rotatesprite16 11010048 6553600 32768 256 CROSSHAIR 0 0 3 0 0 xdim ydim
 setvar RETURN -1
endevent
'''
            if a.case=='custom-viewport':
                con+='''
gamevar vrch_look_ang 0 0
gamevar vrch_screen_size 0 0
onevent EVENT_PROCESSINPUT
 setplayer[THISACTOR].look_ang 32
 getplayer[THISACTOR].look_ang vrch_look_ang
 getuserdef[THISACTOR].screen_size vrch_screen_size
 addlog vrch_look_ang
 addlog vrch_screen_size
endevent
'''
            if a.case=='custom-nested':
                con+='''
gamevar vrch_nested 0 0
gamevar vrch_nested_at 0 0
gamevar vrch_screen_calls 0 0
onevent EVENT_DISPLAYCROSSHAIR
 ifvare vrch_frames 10
 ifvare vrch_nested 0
 {
  setvar vrch_nested 1
  setvarvar vrch_nested_at vrch_frames
  startscreen
 }
endevent
onevent EVENT_SCREEN
 addvar vrch_screen_calls 1
 setvar RETURN 1
endevent
onevent EVENT_DISPLAYREST
 addlog vrch_nested
 addlog vrch_nested_at
 addlog vrch_screen_calls
endevent
// EVENT_SCREEN's return is nested in this callback. Restore the outer
// event-only result after that one native screen frame has completed.
onevent EVENT_DISPLAYCROSSHAIR
 setvar RETURN -1
endevent
'''
            (lab/'crosshair_test.con').write_text(con)
            data=bytearray(room(a.case=='wall',a.case=='target'))
            if a.case in ('ceiling-slope','floor-slope'):
                # sector1, native sloped plane along its first wall.
                offset=64+ (12 if a.case=='ceiling-slope' else 14)
                struct.pack_into('<H',data,offset,2)
                struct.pack_into('<h',data,64+(18 if a.case=='ceiling-slope' else 26),512)
            if a.case in ('occluded','custom-occluded'):
                # Opaque decoration blocks the view/depth, but deliberately has
                # no native hitscan-block bit. It must occlude a marker behind it.
                struct.pack_into('<h',data,104+8*32,5)
                data+=sprite(3500,4600,-14000,1,tile=30001,cstat=128,xrepeat=128,yrepeat=128)
                (lab/'tiles099.art').write_bytes(struct.pack('<4i',1,1,30001,30001)+struct.pack('<hh',16,16)+bytes(4)+bytes([196])*256)
            (lab/'hand.map').write_bytes(data)
            if a.case in ('large','color','custom-viewport'):
                setting='crosshairscale 100\n' if a.case=='large' else 'crosshaircolor 0 255 0\n' if a.case=='color' else 'r_size 12\n'
                with (lab/'autoexec.cfg').open('a') as f:f.write(setting)
            if a.case=='off':
                with (lab/'autoexec.cfg').open('a') as f:f.write('crosshair 0\n')
        env={k:v for k,v in os.environ.items() if not k.startswith('EDUKE32_XR')};env.update(DISPLAY=a.display,SDL_VIDEODRIVER='x11',SDL_AUDIODRIVER='dummy')
        se={k:v for k,v in env.items() if not k.startswith('XR_')};se['EDUKE32_XR_TEST_SHOTS']='1'
        ce=dict(env,EDUKE32_XR='1',EDUKE32_XR_SINGLE_PASS='1',EDUKE32_XR_UI='2',EDUKE32_XR_AIM='left' if a.case=='left' else 'right',EDUKE32_XR_WEAPON='1',EDUKE32_XR_HAND_SHOTS='1',EDUKE32_XR_TEST_SHOTS='1',EDUKE32_XR_TEST_INPUT='1',EDUKE32_XR_TEST_AIM='1',EDUKE32_XR_CROSSHAIR_OUTPUT=str(cl/'crosshair'),EDUKE32_XR_WORLD_OUTPUT=str(cl/'world'),EDUKE32_XR_HUD_OUTPUT=str(cl/'hud'),EDUKE32_XR_WEAPON_OUTPUT=str(cl/'weapon'))
        log=(sl/'server.log').open('w');logs.append(log)
        server=subprocess.Popen([str(a.binary.resolve()),'-usecwd','-nosetup','-noautoload','-dedicated','-port',str(a.port),'-map','hand.map','-x','crosshair_test.con'],cwd=sl,env=se,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        so=Observer(server,sl/'server.log');so.wait(lambda t:'Multiplayer server initialized.' in t)
        with Remote(a.remote_port) as remote:
            hand=remote.packet.left if a.case=='left' else remote.packet.right
            hand.pose.position.x=-.2 if a.case=='left' else .2;hand.pose.position.y=1.3;hand.pose.position.z=-.5;remote.send()
            log=(cl/'client.log').open('w');logs.append(log)
            client=subprocess.Popen([str(a.client_binary.resolve()),'-usecwd','-nosetup','-noautoload','-nologo','-ns','-nm','-connect',f'127.0.0.1:{a.port}','-x','crosshair_test.con'],cwd=cl,env=ce,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
            co=Observer(client,cl/'client.log');phase='join';player=wait_for_join_barrier(X11(a.display),client,cl/'client.log',so)['server_player'];so.wait(lambda t:len(players(t,player))>20)
            hand.pose.orientation=orientation(12,45 if a.case.startswith('ceiling') else -45 if a.case.startswith('floor') else 0 if a.case=='target' else 8);remote.packet.head.center.orientation=orientation(-12,25 if a.case.startswith('ceiling') else -25 if a.case.startswith('floor') else 4)
            if a.case=='head-moved':remote.packet.head.center.position.x+=.07
            if a.case=='lost':hand.active=False
            remote.send();co.pause(.5)
            co.wait(lambda t:'OpenXR world oracle: 60 frames' in t and 'OpenXR HUD presentation: 60 frames' in t,timeout=20);co.pause(.05)
            text=co.text();counts=[tuple(map(int,r)) for r in re.findall(r'addlog vrch_frames = (\d+).*?addlog vrch_calls = (\d+)',text,re.S)]
            checks={'actual_60_stereo_world_HUD_frames':(cl/'hud-left.ppm').read_bytes()!=(cl/'hud-right.ppm').read_bytes(),'core_validation_active':'Core Validation output type:' in text,'core_validation_clean':not re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)',text),'native_crosshair_event_once':len(counts)>60 and all(c==(0 if a.case=='off' else f) for f,c in counts)}
            extra={}
            if a.pistol_shotgun:
                server_shoots=list(map(int,re.findall(r'addlog vrch_shoots[^=\n]*= (-?\d+)',so.text())))
                server_workslike=list(map(int,re.findall(r'addlog vrch_workslike[^=\n]*= (-?\d+)',so.text())))
                checks['pistol_slot_SHOTGUN_override_keeps_WorksLike1']=bool(server_shoots and server_workslike) and server_shoots[-1]==2613 and server_workslike[-1]==1
                extra['server_pistol_slot_weapon_data']={'shoots':(server_shoots[-1] if server_shoots else None),'workslike':(server_workslike[-1] if server_workslike else None)}
            if a.case=='large':checks['native_crosshair_size_setting_applied']=int(re.findall(r'addlog vrch_scale = (\d+)',text)[-1])==100
            if a.case=='custom-viewport':
                viewport_look=list(map(int,re.findall(r'addlog vrch_look_ang[^=\n]*= (-?\d+)',text)))
                viewport_size=list(map(int,re.findall(r'addlog vrch_screen_size[^=\n]*= (-?\d+)',text)))
                checks['custom_viewport_has_native_nonzero_look_and_reduced_screen']=bool(viewport_look and viewport_size) and viewport_look[-1]==32 and viewport_size[-1]==12
                extra['custom_viewport_native_state']={'look_ang':(viewport_look[-1] if viewport_look else None),'screen_size':(viewport_size[-1] if viewport_size else None)}
            if a.case=='custom-nested':
                nested=list(map(int,re.findall(r'addlog vrch_nested(?: \(player \d+\))? = (-?\d+)',text)))
                screen_calls=list(map(int,re.findall(r'addlog vrch_screen_calls[^=\n]*= (-?\d+)',text)))
                captures=[tuple(map(int,row)) for row in re.findall(r'OpenXR crosshair capture: world=(\d+) serial=(\d+)\.',text)]
                nested_at=list(map(int,re.findall(r'addlog vrch_nested_at = (\d+)',text)))
                checks['custom_nested_startscreen_runs_once']=bool(nested and screen_calls and nested_at) and nested[-1]==1 and screen_calls[-1]==1 and nested_at[-1]==10
                checks['custom_nested_continues_to_fresh_world_frame_60']=any(world==60 and serial>0 for world,serial in captures)
                extra['custom_nested_captures']=captures
            if os.environ.get('EDUKE32_TEST_PRIVATE_WINDOW')=='1':
                x11=X11(a.display);window,_=x11.owned_window(client.pid)
                if not window:raise RuntimeError('private drawable missing')
                state=x11.window_visibility(window);server_window,_=x11.owned_window(server.pid)
                checks.update(private_XR_drawable_unmapped=state['unmapped'],test_window_does_not_have_desktop_focus=not state['has_desktop_focus'],server_has_no_mapped_window=not server_window or x11.window_visibility(server_window)['unmapped'])
            if a.case=='off':
                checks['native_off_hides_spatial_marker']=not (cl/'crosshair-ui.ppm').exists() and 'OpenXR world crosshair:' not in text
            elif a.case=='cancelled':
                # A callback that returns -1 still owns a real, empty XR
                # segment. Require its capture evidence rather than treating
                # missing output files as cancellation proof.
                coverage=cl/'crosshair-coverage.pgm'
                cancelled_coverage_empty=coverage.exists() and not np.any(np.array(Image.open(coverage)))
                cancelled_changed=[]
                cancelled_frames_present=True
                for name in ('left','right'):
                    before_path=cl/f'crosshair-before-{name}.ppm';after_path=cl/f'crosshair-{name}.ppm'
                    if before_path.exists() and after_path.exists():
                        before=np.array(Image.open(before_path));after=np.array(Image.open(after_path))
                        cancelled_changed.append(int(np.count_nonzero(np.any(before!=after,axis=2))))
                    else:cancelled_frames_present=False
                checks['native_event_cancellation_hides_spatial_marker']=cancelled_coverage_empty and cancelled_frames_present and len(cancelled_changed)==2 and max(cancelled_changed)==0
                extra.update(cancelled_coverage_pixels=(int(np.count_nonzero(np.array(Image.open(coverage)))) if coverage.exists() else None),cancelled_changed_pixels=cancelled_changed)
            else:
                phase='pixel/depth oracle';ui=np.array(Image.open(cl/'crosshair-ui.ppm'));alpha=np.array(Image.open(cl/'crosshair-coverage.pgm'))
                if a.case=='color':checks['native_crosshair_color_preserved']=bool(np.any(alpha>0)) and int(ui[:,:,1].max())>200 and int(ui[:,:,0].max())<10 and int(ui[:,:,2].max())<10
                extra['native_coverage_bounds']=Image.open(cl/'crosshair-coverage.pgm').getbbox()
                depth_ok=[];errors=[];changed=[];occluded=[];centres=[];projection_errors=[];anchors=[]
                matrices={int(i):np.fromstring(m,sep=',').reshape(4,4,order='F') for i,m in re.findall(r'OpenXR crosshair matrix: eye=(\d) values=([^\n]+)\.',text)}
                for eye,name in enumerate(('left','right')):
                    before=np.array(Image.open(cl/f'crosshair-before-{name}.ppm'));after=np.array(Image.open(cl/f'crosshair-{name}.ppm'))
                    raw=(cl/f'crosshair-before-{name}-depth.bin').read_bytes();depth=np.flipud(np.frombuffer(raw,dtype=np.uint32).reshape(before.shape[:2]))/4294967295
                    depth_ok.append(raw==(cl/f'crosshair-{name}-depth.bin').read_bytes());changed.append(int(np.count_nonzero(np.any(before!=after,axis=2))))
                    if a.case=='lost':expected=before;blocked=0
                    else:
                        expected,clear,blocked=raster(before,ui,alpha,depth,matrices[eye])
                        anchor=np.array(list(map(float,re.findall(r'OpenXR crosshair anchor: pixel=('+NUMBER+'),('+NUMBER+r')\.',text)[-1])))
                        anchors.append(anchor)
                        c=matrices[eye]@np.array([2*anchor[0]/ui.shape[1]-1,1-2*anchor[1]/ui.shape[0],0,1]);centre=c[:2]/c[3];centres.append(centre.tolist())
                        # Independent physical eye projection of the world point;
                        # do not trust the matrix uploaded by the implementation.
                        point=np.array(list(map(float,re.findall(r'point=('+NUMBER+'),('+NUMBER+'),('+NUMBER+r')\.',text)[-1])))
                        eyes=np.array(list(map(int,re.findall(r'OpenXR aim eye positions: left=(-?\d+),(-?\d+),(-?\d+) right=(-?\d+),(-?\d+),(-?\d+)',text)[-1]))).reshape(2,3)
                        angle_pitch=list(map(float,re.findall(r'leftYaw=('+NUMBER+') leftPitch=('+NUMBER+') rightYaw=('+NUMBER+') rightPitch=('+NUMBER+r')\.',text)[-1]))
                        yaw,pitch=angle_pitch[eye*2:eye*2+2];rel=(point-eyes[eye])/np.array([384,384,6144]);front=rel[0]*math.cos(yaw)+rel[1]*math.sin(yaw);right=-rel[0]*math.sin(yaw)+rel[1]*math.cos(yaw);up=-rel[2]
                        forward=front*math.cos(pitch)+up*math.sin(pitch);vertical=up*math.cos(pitch)-front*math.sin(pitch)
                        fov=np.tan(np.fromstring(re.findall(r'OpenXR weapon view: eye='+str(eye)+r'.*? fov=([^\n]+)\.',text)[-1],sep=','));left,right_t,top,bottom=fov
                        physical=np.array([(2*right/forward-right_t-left)/(right_t-left),(2*vertical/forward-top-bottom)/(top-bottom)])
                        projection_errors.append(float(np.abs(physical-centre).max()))
                        extra.setdefault('unoccluded_reference_changed_pixels',[]).append(int(np.count_nonzero(np.any(clear!=before,axis=2))))
                    errors.append(int(np.abs(expected.astype(int)-after.astype(int)).max()));occluded.append(blocked)
                checks.update(exact_world_depth_preserved=all(depth_ok),both_eye_pixels_match_depth_tested_projection=max(errors)<=2)
                if a.case.startswith('custom'):
                    # Event-only ART is authored in native 320x200 units but
                    # must use the physical full-screen centre. This expected
                    # point comes from the native screen dimensions, not the
                    # uploaded world matrix.
                    expected_anchor=np.array([ui.shape[1]/2+1,ui.shape[0]/2+1])
                    part_centres=(expected_anchor,np.array([expected_anchor[0]+8*ui.shape[1]/320,expected_anchor[1]]))
                    def covered(point):
                        x,y=np.rint(point).astype(int);radius=12
                        return int(np.count_nonzero(alpha[max(0,y-radius):min(alpha.shape[0],y+radius+1),max(0,x-radius):min(alpha.shape[1],x+radius+1)]))
                    part_coverage=[covered(point) for point in part_centres]
                    checks['custom_event_anchor_is_fullscreen_logical_centre']=len(anchors)==2 and max(float(np.abs(anchor-expected_anchor).max()) for anchor in anchors)<1e-4
                    checks['custom_event_multipart_source_coverage_present']=all(part_coverage)
                    extra.update(custom_expected_anchor=expected_anchor.tolist(),custom_part_centres=[point.tolist() for point in part_centres],custom_part_coverage=part_coverage)
                if a.case=='lost':checks['invalid_hand_hides_reticle_without_stale_pixels']=changed==[0,0] and not matrices
                else:
                    checks['independent_physical_projection_matches_world_point']=max(projection_errors)<2e-5
                    checks['independent_eye_projection_has_parallax']=abs(centres[0][0]-centres[1][0])>1e-4
                    if a.case in ('occluded','custom-occluded'):checks['actual_world_depth_occludes_reticle']=min(occluded)>0 and max(changed)==0 and min(extra['unoccluded_reference_changed_pixels'])>0
                    else:checks['actual_spatial_marker_visible_both_eyes']=min(changed)>0
                    phase='actual native shot';offset=len(so.text());remote.packet.right.trigger_value=1;remote.packet.right.trigger_click=True;remote.send();so.wait(lambda t:bool(rays(t[offset:],player)),timeout=4);remote.packet.right.trigger_value=0;remote.packet.right.trigger_click=False;remote.send()
                    shot=rays(so.text()[offset:],player)[0];hit=list(map(int,re.findall(r'OpenXR world crosshair: start=(-?\d+),(-?\d+),(-?\d+) hit=(-?\d+),(-?\d+),(-?\d+)',text)[-1]));checks['reticle_ray_matches_actual_server_origin_and_impact']=hit==[shot[k] for k in ('x','y','z','hitx','hity','hitz')]
                    extra['native_shot']=shot;extra['crosshair_hit']=hit
                extra.update(pixel_max_error=errors,changed_pixels=changed,depth_occluded_coverage_pixels=occluded,eye_centres_NDC=centres,physical_projection_NDC_max_error=projection_errors)
            window,_=X11(a.display).owned_window(client.pid)
            if window and os.environ.get('EDUKE32_TEST_PRIVATE_WINDOW')!='1':subprocess.run(['import','-display',a.display,'-window',str(window),str(root/'desktop.png')],check=True,timeout=8)
            result={'passed':all(checks.values()),'case':a.case,'checks':checks,**extra}
    except Exception as e:result={'passed':False,'case':a.case,'phase':phase,'error':str(e)}
    finally:
        stop(client);stop(server)
        for f in logs:f.close()
    result['evidence_directory']=str(root);(root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
