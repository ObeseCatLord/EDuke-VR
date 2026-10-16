#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise controller input across private Monado focus/IO and native video resets.

Requires an exclusively owned private Monado service. Its libmonado operations
are restricted to IDs discovered from the two processes launched by this test.
Never changes desktop focus or the user's runtime configuration.
"""
import argparse
import ctypes as c
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from monado_remote import Remote
from smoke_actions import Observer, samples, traces
from smoke_multiplayer import X11, stop
from smoke_world import CONFIG


class Admin:
    def __init__(self):
        self.lib=c.CDLL('libmonado.so')
        self.root=c.c_void_p()
        signatures={
            'create':[c.POINTER(c.c_void_p)], 'destroy':[c.POINTER(c.c_void_p)],
            'update_client_list':[c.c_void_p],
            'get_number_clients':[c.c_void_p,c.POINTER(c.c_uint32)],
            'get_client_id_at_index':[c.c_void_p,c.c_uint32,c.POINTER(c.c_uint32)],
            'get_client_name':[c.c_void_p,c.c_uint32,c.POINTER(c.c_char_p)],
            'get_client_state':[c.c_void_p,c.c_uint32,c.POINTER(c.c_uint32)],
            'set_client_primary':[c.c_void_p,c.c_uint32],
            'set_client_io_blocks':[c.c_void_p,c.c_uint32,c.c_uint32]}
        for name,arguments in signatures.items():
            getattr(self.lib,'mnd_root_'+name).argtypes=arguments
        self.allowed=set()
        self.call('create',c.byref(self.root))
        self.baseline=self.clients()
        if len(self.baseline)!=1 or next(iter(self.baseline.values()))['name']!='libmonado':
            self.close()
            raise RuntimeError('private runtime must contain no existing XR clients')

    def call(self,name,*args):
        result=getattr(self.lib,'mnd_root_'+name)(*args)
        if result < 0:raise RuntimeError('libmonado '+name+' failed: '+str(result))

    def clients(self):
        self.call('update_client_list',self.root)
        count=c.c_uint32();self.call('get_number_clients',self.root,c.byref(count))
        result={}
        for index in range(count.value):
            ident=c.c_uint32();name=c.c_char_p();flags=c.c_uint32()
            self.call('get_client_id_at_index',self.root,index,c.byref(ident))
            self.call('get_client_name',self.root,ident,c.byref(name))
            self.call('get_client_state',self.root,ident,c.byref(flags))
            result[ident.value]={'name':name.value.decode(),'flags':flags.value}
        return result

    def discover(self,before):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            clients=self.clients();added=set(clients)-set(before)
            if len(added)==1:
                ident=added.pop()
                if clients[ident]['name'] != 'EDuke32 VR':raise RuntimeError('unexpected client in private runtime')
                self.allowed.add(ident);return ident
            if len(added)>1:raise RuntimeError('unexpected simultaneous clients in private runtime')
            time.sleep(.05)
        raise RuntimeError('owned XR client did not register')

    def change(self,operation,ident,*args):
        if ident not in self.allowed:raise RuntimeError('refusing unowned runtime client operation')
        self.call(operation,self.root,ident,*args)

    def close(self):
        self.lib.mnd_root_destroy(c.byref(self.root))


def exercise(observer,remote,admin,game_id,helper_path,env,lab,x,process):
    observer.wait(lambda s:bool(samples(s)) and any(t['focus'] and t['left_aim'] for t in traces(s)))
    observer.pause(1.6);remote.neutral();observer.pause(.3)
    checks={};stages={}
    def record(name,action,seconds=.6):
        offset=len(observer.text());action();observer.pause(seconds)
        text=observer.text()[offset:]
        stages[name]={'native':samples(text),'xr':traces(text)}
        return stages[name]
    def fire():
        remote.packet.right.trigger_value=1;remote.packet.right.trigger_click=True;remote.send()
    record('fire',fire)
    # IO blocks apply through Monado's real device plumbing. POSES invalidates
    # view tracking; buttons must still advance native gameplay on the Idle path.
    p=record('poses_blocked',lambda:admin.change('set_client_io_blocks',game_id,1),.9)
    checks['native_fire_with_invalid_view_tracking']=any(s['bits']&4 for s in p['native'])
    checks['runtime_pose_block_observed']=any(not t['right_aim'] for t in p['xr'])
    record('poses_restored',lambda:admin.change('set_client_io_blocks',game_id,0),.4)
    p=record('inputs_blocked',lambda:admin.change('set_client_io_blocks',game_id,4),.7)
    checks['blocked_actions_neutral']=bool(p['xr']) and all(t['right_active']==0 and not t['functions'] for t in p['xr'])
    p=record('inputs_restored_held',lambda:admin.change('set_client_io_blocks',game_id,0),.7)
    checks['unblocked_held_action_suppressed']=bool(p['xr']) and all(not(t['functions']&(1<<5)) for t in p['xr'])
    record('inputs_release',remote.neutral,.3)
    p=record('inputs_repress',fire,.6)
    checks['unblocked_repress_native_fire']=any(s['bits']&4 for s in p['native'])
    helper=None
    try:
        before=admin.clients()
        helper_log=(lab/'focus-helper.log').open('w')
        helper=subprocess.Popen([str(helper_path),'--frames','1000000','--timeout','45'],env=env,
                                stdin=subprocess.DEVNULL,stdout=helper_log,stderr=subprocess.STDOUT)
        helper_id=admin.discover(before)
        # set_client_focused is an unimplemented success stub in this Monado;
        # change the primary application and assert actual action focus instead.
        p=record('other_primary',lambda:admin.change('set_client_primary',helper_id),1.1)
        checks['real_focus_loss_neutral']=any(not t['focus'] and not t['functions'] for t in p['xr'])
        checks['native_ticks_continue_unfocused']=len(p['native'])>=2
        p=record('focus_restored_held',lambda:admin.change('set_client_primary',game_id),1.0)
        checks['focus_regain_held_suppressed']=any(t['focus'] for t in p['xr']) and all(not(t['functions']&(1<<5)) for t in p['xr'])
        record('focus_release',remote.neutral,.3)
        p=record('focus_repress',fire,.6)
        checks['focus_regain_repress_native_fire']=any(s['bits']&4 for s in p['native'])
    finally:
        if game_id in admin.clients():admin.change('set_client_primary',game_id)
        stop(helper)
        if helper is not None:helper_log.close()
    old_generation=traces(observer.text())[-1]['generation']
    window,_=x.owned_window(process.pid)
    def key(name):x.press(window,name,.04,True)
    # Command executes in the native frame after XR preparation. Windowed mode
    # avoids modifying the display mode or desktop focus on the shared display.
    key('quoteleft');observer.pause(.35)
    for char in 'restartvid':key('space' if char==' ' else char)
    key('Return')
    observer.wait(lambda s:'>restartvid' in s,10)
    observer.pause(.4)
    window,_=x.owned_window(process.pid)
    if not window:raise RuntimeError('owned window missing after video reset')
    x.press(window,'quoteleft',.04,True)
    p=record('video_reset_held',lambda:None,.7)
    current=traces(observer.text())[-1]
    checks['native_video_reset_keeps_existing_context']=current['generation']==old_generation
    checks['video_reset_retains_live_held_action']=bool(current['functions']&(1<<5))
    record('video_reset_release',remote.neutral,.3)
    p=record('video_reset_repress',fire,.7)
    checks['video_reset_repress_native_fire']=any(s['bits']&4 for s in p['native'])
    return {'passed':all(checks.values()),'checks':checks,'stages':stages}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('binary','helper','grp','work-dir'):parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--display',default=':1')
    parser.add_argument('--remote-port',required=True,type=int)
    args=parser.parse_args()
    args.work_dir.mkdir(parents=True,exist_ok=True)
    lab=Path(tempfile.mkdtemp(prefix='xr-action-lifecycle-',dir=args.work_dir.resolve()))
    (lab/'eduke32.cfg').write_text(CONFIG)
    (lab/'DUKE3D.GRP').symlink_to(args.grp.resolve())
    shutil.copyfile(Path(__file__).resolve().parent/'fixtures/controller_test.con',lab/'controller_test.con')
    env=dict(os.environ,DISPLAY=args.display,SDL_VIDEODRIVER='x11',SDL_AUDIODRIVER='dummy',
             EDUKE32_XR='1',EDUKE32_XR_SINGLE_PASS='1',EDUKE32_XR_TEST_INPUT='1')
    for key in ('EDUKE32_XR_TEST_FAIL','EDUKE32_XR_TEST_ZERO_IPD','EDUKE32_XR_TEST_STEREO_POSE',
                'EDUKE32_XR_TEST_NATIVE_TARGET','EDUKE32_XR_DIAGNOSTIC_FRAMES'):env.pop(key,None)
    admin=Admin();process=None
    try:
        with (lab/'actions.log').open('w') as log,Remote(args.remote_port) as remote:
            process=subprocess.Popen([str(args.binary.resolve()),'-usecwd','-nosetup','-noautoload','-nologo','-ns','-nm',
                                      '-v1','-l1','-s1','-x','controller_test.con'],cwd=lab,env=env,
                                     stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
            try:
                game_id=admin.discover(admin.baseline)
                result=exercise(Observer(process,lab/'actions.log'),remote,admin,game_id,args.helper.resolve(),env,lab,X11(args.display),process)
            except Exception as error:result={'passed':False,'error':str(error)}
            finally:
                for ident in list(admin.allowed):
                    if ident in admin.clients():admin.change('set_client_io_blocks',ident,0)
                stop(process)
    finally:admin.close()
    result['evidence_directory']=str(lab)
    (lab/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
