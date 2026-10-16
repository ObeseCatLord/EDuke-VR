#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Drive real OpenXR Index actions through a private Monado remote runtime.

All game input observations are native CON EVENT_PROCESSINPUT/player state.
No game action injection, packet mutation, global desktop input, or GRP writes.
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

from monado_remote import Remote
from smoke_world import CONFIG


FIELDS = re.compile(r'addlog vrinput_(\w+)(?: \(player \d+\))? = (-?\d+)')
TRACE = re.compile(r'OpenXR input: sample=(\d+) focus=(\d+) active=(\d+),(\d+) buttons=(\d+),(\d+) funcs=(\d+) axes=(-?\d+),(-?\d+),(-?\d+),(-?\d+) menu=(\d+),(\d+),(\d+),(\d+) gm=(\d+) screen=(-?\d+) aim=(\d+),(\d+) gen=(\d+)')
TRACE_KEYS = ('sample','focus','left_active','right_active','left_buttons','right_buttons','functions',
              'strafe','forward','turn','pitch','advance','back','escape','direction','mode','screen','left_aim','right_aim','generation')


def samples(text):
    result, current = [], {}
    for key, value in FIELDS.findall(text):
        if key == 'tick':
            current = {}
        current[key] = int(value)
        if key == 'ammo' and len(current) == 10:
            result.append(current)
    return result


def traces(text):
    return [dict(zip(TRACE_KEYS, map(int, row))) for row in TRACE.findall(text)]


class Observer:
    def __init__(self, process, path):
        self.process, self.path = process, Path(path)

    def text(self):
        if self.process.poll() is not None:
            raise RuntimeError('owned game exited during controller test')
        value = self.path.read_text(errors='replace')
        if re.search(r'Found \d+ warning\(s\), [1-9]\d* error\(s\)',value):
            raise RuntimeError('native CON compilation failed; inspect owned test log')
        if 'OpenXR world stopped:' in value or 'OpenXR world initialization failed:' in value:
            raise RuntimeError('XR stopped; inspect owned test log')
        return value

    def wait(self, predicate, timeout=12):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            value = self.text()
            if predicate(value):
                return value
            time.sleep(.05)
        raise RuntimeError('controller test observation timeout')

    def pause(self, seconds):
        end = time.monotonic()+seconds
        while time.monotonic() < end:
            self.text()
            time.sleep(min(.05, max(0, end-time.monotonic())))


def exercise(observer, remote, keyboard=None):
    """Return bounded native gameplay/release/menu evidence for a real runtime."""
    observer.wait(lambda s: bool(samples(s)) and any(t['focus'] and t['left_aim'] and t['right_aim'] for t in traces(s)))
    observer.pause(1.6)  # Native finite startup overlay/weapon raise.
    remote.neutral()
    observer.pause(.25)
    stages = {}

    def stage(name, action, seconds=.65):
        offset = len(observer.text())
        action()
        observer.pause(seconds)
        part = observer.text()[offset:]
        stages[name] = {'native': samples(part), 'xr': traces(part)}
        return stages[name]

    before = samples(observer.text())[-1]
    stage('move', lambda: (setattr(remote.packet.left.thumbstick, 'y', .8), remote.send()))
    stage('release_move', remote.neutral, .4)
    after = samples(observer.text())[-1]
    move = stages['move']['native']
    moved = (after['x'],after['y']) != (before['x'],before['y']) and any(s['fvel'] or s['svel'] for s in move)
    ammo_before = after['ammo']

    def fire():
        remote.packet.right.trigger_value=1
        remote.packet.right.trigger_click=True
        remote.send()
    stage('fire',fire,.8)
    stage('release_fire',remote.neutral,.4)
    ammo_after = samples(observer.text())[-1]['ammo']
    fired = any(s['bits'] & 4 for s in stages['fire']['native']) and ammo_after < ammo_before
    released = bool(stages['release_fire']['native']) and all(not (s['bits'] & 4) for s in stages['release_fire']['native'][-2:])

    stage('held_before_disconnect',fire,.3)
    stage('controller_inactive',lambda:(setattr(remote.packet.right,'active',False),remote.send()),.4)
    stage('reconnected_held',lambda:(setattr(remote.packet.right,'active',True),remote.send()),.55)
    stage('reconnected_release',remote.neutral,.35)
    stage('reconnected_repress',fire,.6)
    inactive = bool(stages['controller_inactive']['xr']) and all(t['right_active'] == 0 for t in stages['controller_inactive']['xr'])
    held_blocked = bool(stages['reconnected_held']['xr']) and all(not(t['functions'] & (1<<5)) for t in stages['reconnected_held']['xr'])
    repress = any(s['bits'] & 4 for s in stages['reconnected_repress']['native'])
    remote.neutral();observer.pause(.4)

    stage('menu_open',lambda:(setattr(remote.packet.left,'thumbstick_click',True),remote.send()),.8)
    menu_open = bool(traces(observer.text())[-1]['mode'] & 1)
    stage('menu_held',lambda:None,.85)
    menu_held = bool(traces(observer.text())[-1]['mode'] & 1)
    remote.neutral();observer.pause(.2)
    stage('menu_back',lambda:(setattr(remote.packet.right,'b_click',True),remote.send()),.65)
    menu_closed = not(traces(observer.text())[-1]['mode'] & 1)
    stage('back_held_after_close',lambda:None,.6)
    back_blocked = not(traces(observer.text())[-1]['functions'] & (1<<10))
    remote.neutral();observer.pause(.3)

    native_keyboard = None
    if keyboard:
        offset = len(observer.text())
        keyboard('w',.55)
        observer.pause(.25)
        native_keyboard = any(s['fvel'] or s['svel'] for s in samples(observer.text()[offset:]))

    checks = dict(real_openxr_aim_poses=True, native_movement=moved, native_fire_and_ammo=fired,
                  native_fire_release=released, inactive_controller_neutral=inactive,
                  reconnect_held_suppressed=held_blocked,reconnect_repress_native_fire=repress,
                  menu_open=menu_open,menu_hold_no_repeat=menu_held,menu_back=menu_closed,
                  menu_close_held_button_suppressed=back_blocked)
    if native_keyboard is not None:checks['native_keyboard_coexists']=native_keyboard
    return {'passed': all(checks.values()), 'checks':checks, 'stages':stages,
            'ammo_before':ammo_before,'ammo_after':ammo_after,
            'position_before':[before['x'],before['y']], 'position_after':[after['x'],after['y']]}


def exercise_title(observer, remote):
    observer.wait(lambda s:any(t['focus'] and t['mode'] & 1 and t['screen'] == 0 for t in traces(s)))
    observer.pause(1.6)
    remote.neutral(); observer.pause(.3)
    remote.packet.right.a_click=True; remote.send()
    observer.wait(lambda s:traces(s)[-1]['screen'] == 100)
    observer.pause(.8)
    held=traces(observer.text())[-1]['screen'] == 100
    remote.neutral(); observer.pause(.3)
    remote.packet.right.b_click=True; remote.send()
    observer.wait(lambda s:traces(s)[-1]['screen'] == 0)
    observer.pause(.5)
    checks={'title_menu_openxr_actions':True,'advance_enters_episode_menu':True,
            'held_advance_does_not_select_episode':held,'back_returns_to_title_menu':True}
    return {'passed':all(checks.values()),'checks':checks,'trace':traces(observer.text())[-20:]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary',required=True,type=Path)
    parser.add_argument('--grp',required=True,type=Path)
    parser.add_argument('--work-dir',required=True,type=Path)
    parser.add_argument('--display',default=':1')
    parser.add_argument('--remote-port',required=True,type=int)
    parser.add_argument('--title-menu',action='store_true',help='test the independent title/demo frame loop')
    args=parser.parse_args()
    args.work_dir.mkdir(parents=True,exist_ok=True)
    lab=Path(tempfile.mkdtemp(prefix='xr-actions-',dir=args.work_dir.resolve()))
    (lab/'eduke32.cfg').write_text(CONFIG)
    (lab/'DUKE3D.GRP').symlink_to(args.grp.resolve())
    shutil.copyfile(Path(__file__).resolve().parent/'fixtures/controller_test.con',lab/'controller_test.con')
    env=dict(os.environ,DISPLAY=args.display,SDL_VIDEODRIVER='x11',SDL_AUDIODRIVER='dummy',
             EDUKE32_XR='1',EDUKE32_XR_SINGLE_PASS='1',EDUKE32_XR_TEST_INPUT='1')
    for key in ('EDUKE32_XR_TEST_FAIL','EDUKE32_XR_TEST_ZERO_IPD','EDUKE32_XR_TEST_STEREO_POSE',
                'EDUKE32_XR_TEST_NATIVE_TARGET','EDUKE32_XR_DIAGNOSTIC_FRAMES'):
        env.pop(key,None)
    command=[str(args.binary.resolve()),'-usecwd','-nosetup','-noautoload','-nologo','-ns','-nm','-v1','-l1','-s1','-x','controller_test.con']
    if args.title_menu:
        command=[str(args.binary.resolve()),'-usecwd','-nosetup','-noautoload','-nologo','-ns','-nm']
    log_path=lab/'actions.log'
    from smoke_multiplayer import X11, stop
    with log_path.open('w') as log, Remote(args.remote_port) as remote:
        process=subprocess.Popen(command,cwd=lab,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        try:
            observer=Observer(process,log_path)
            x=X11(args.display)
            observer.wait(lambda s:bool(traces(s)) if args.title_menu else bool(samples(s)))
            window,_=x.owned_window(process.pid)
            if not window:raise RuntimeError('owned game window unavailable')
            result=(exercise_title(observer,remote) if args.title_menu else
                    exercise(observer,remote,lambda key,seconds:x.press(window,key,seconds,True)))
        except Exception as error:
            result={'passed':False,'error':str(error)}
        finally:
            stop(process)
    result['evidence_directory']=str(lab)
    (lab/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
