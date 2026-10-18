#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual AA held-button edges with two independently controlled native peers.

Run in the CPU-only private sandbox. Both processes load a main CON via -x and
an observation-only module via -mx; the installed mod is never changed.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

from smoke_actions_multiplayer import client_player_index
from smoke_native_levels import assert_cpu_binary, assert_gpu_devices_absent, sanitised_env
from smoke_pistol_reload_native import Run, sha256
from smoke_multiplayer import CONFIG

OPEN_SCAN, RETURN_SCAN, OPEN_BIT = 8, 40, 1 << 29
JUMP_SCAN = 44
FIELDS = ('tick', 'player', 'bits', 'previous', 'charsel', 'startmode', 'cursorx', 'cursory')
PATTERN = re.compile(r'addlog aaedge_(\w+)(?: \(player \d+\))? = (-?\d+)')
OBSERVER = ''.join(f'gamevar aaedge_{f} 0 524289\n' for f in FIELDS) + '''
appendevent EVENT_PROCESSINPUT
 addlog myconnectindex
 add aaedge_tick 1
 getplayer[THISACTOR].index aaedge_player
 getinput[THISACTOR].bits aaedge_bits
 set aaedge_previous oldbits
 set aaedge_charsel charsel
 set aaedge_startmode startmode
 set aaedge_cursorx cursorx
 set aaedge_cursory cursory
''' + ''.join(f' addlog aaedge_{f}\n' for f in FIELDS) + 'endevent\n'


def rows(text, player=None):
    out, row = [], {}
    for key, value in PATTERN.findall(text):
        if key == 'tick':
            row = {}
        if key in FIELDS:
            row[key] = int(value)
        if key == 'cursory' and all(k in row for k in FIELDS):
            if player is None or row['player'] == player:
                out.append(row)
            row = {}
    return out


def sandbox(args):
    if args._sandboxed:
        return
    args.work_dir.mkdir(parents=True, exist_ok=True)
    env = sanitised_env()
    cmd = ['bwrap', '--ro-bind', '/', '/', '--dev', '/dev', '--proc', '/proc',
           '--unshare-pid', '--unshare-net', '--bind', str(args.work_dir), str(args.work_dir),
           '--chdir', str(Path.cwd()), '--clearenv']
    for name in ('PATH', 'LANG', 'LC_ALL', 'TZ'):
        if name in env:
            cmd += ['--setenv', name, env[name]]
    cmd += [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], '--_sandboxed']
    os.execvpe('bwrap', cmd, env)


def states(values, initial):
    result = [initial]
    for row in values:
        if row['charsel'] != result[-1]:
            result.append(row['charsel'])
    return result


def ready(run, observer, player, require_join):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        text = observer.text()
        run.audit()
        if rows(text, player) and (not require_join or 'Multiplayer client level synchronization complete.' in text):
            return
        if 'Per-map .art file' in text:
            run.key(RETURN_SCAN, True)
            time.sleep(.12)
            run.key(RETURN_SCAN, False)
        time.sleep(.15)
    raise RuntimeError('AA peer did not reach native selector/input')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'input-helper', 'mod', 'work-dir'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--compat-con', type=Path)
    parser.add_argument('--port', type=int, default=24962)
    parser.add_argument('--_sandboxed', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    for name in ('binary', 'input_helper', 'mod', 'work_dir', 'compat_con'):
        if getattr(args, name) is not None:
            setattr(args, name, getattr(args, name).resolve())
    main_con = args.compat_con or args.mod/'scripts/AAGAME.CON'
    for path in (args.binary, args.input_helper, main_con, args.mod/'AA.grp'):
        if not path.is_file():
            parser.error('missing input: '+str(path))
    sandbox(args)
    assert_cpu_binary(args.binary)
    assert_gpu_devices_absent()
    root = Path(tempfile.mkdtemp(prefix='aa-button-edges-', dir=args.work_dir))
    runs, observers = {}, {}
    result = dict(passed=False, phase='startup', main_con=str(main_con), main_con_sha256=sha256(main_con),
                  binary_sha256=sha256(args.binary), evidence_directory=str(root), stages={})
    try:
        for role in ('host', 'receiver'):
            lab = root/role
            lab.mkdir()
            (lab/'eduke32.cfg').write_text(CONFIG.replace('ScreenBPP = 32', 'ScreenBPP = 8'))
            (lab/'settings.cfg').write_text('// Private AA edge qualification.\n')
            (lab/'autoexec.cfg').write_text('r_maxfps 30\nunbind E\nbind E "gamefunc_Open"\nbind Space "gamefunc_Jump"\n')
            (lab/'aa_button_observer.con').write_text(OBSERVER)
            run = Run(args, root, args.binary, con_file=main_con.name)
            # One reused Run per process gives each peer its own owner-only FIFO.
            run.labs['client'] = lab
            runs[role] = run
            common = ['-j', str(args.mod), '-j', str(main_con.parent), '-g', str(args.mod/'AA.grp'),
                      '-h', 'duke3d.def', '-mx', 'aa_button_observer.con']
            options = ['-server', '-c2', '-v1', '-l2', '-s1', '-port', str(args.port)] if role == 'host' else [
                '-connect', f'127.0.0.1:{args.port}']
            observer = run.launch('client', common+options)
            observers[role] = observer
            ready(run, observer, 0 if role == 'host' else 1, role == 'receiver')
        if client_player_index(observers['receiver'].text()) != 1:
            raise RuntimeError('receiver must be native player1')
        for observer in observers.values():
            observer.wait(lambda t: all(rows(t, p) for p in (0, 1)), timeout=10)
            if any(rows(observer.text(), p)[-1]['charsel'] != 0 for p in (0, 1)):
                raise RuntimeError('initial native selection is not empty')
        result['phase'] = 'independent held Open edges'

        def stage(name, change, initial, expected, held_players):
            offsets = {role: len(obs.text()) for role, obs in observers.items()}
            change()
            measured = {}
            for role, obs in observers.items():
                def enough(text):
                    return all(len({r['tick'] for r in rows(text[offsets[role]:], p)
                                    if bool(r['bits'] & OPEN_BIT) == (p in held_players)}) >= 12
                               for p in (0, 1))
                obs.wait(enough, timeout=12)
                values = rows(obs.text()[offsets[role]:])
                sequence = states(values, initial)
                held_words = {p: sorted({r['bits'] for r in values
                                        if r['player'] == p and r['bits'] & OPEN_BIT}) for p in held_players}
                measured[role] = dict(transitions=sequence, tail=values[-8:],
                                      held_input_words=held_words,
                                      held_words_constant=all(len(words) == 1 for words in held_words.values()),
                                      expected_transition=sequence == ([initial] if initial == expected else [initial, expected]),
                                      duke_cursor=all(145 <= r['cursorx'] <= 185 and 60 <= r['cursory'] <= 160 for r in values))
            result['stages'][name] = measured

        stage('host_press_held_receiver_idle', lambda: runs['host'].key(OPEN_SCAN, True), 0, 1, {0})
        stage('receiver_jump_host_open_held', lambda: runs['receiver'].key(JUMP_SCAN, True), 1, 1, {0})
        stage('receiver_jump_release_host_open_held', lambda: runs['receiver'].key(JUMP_SCAN, False), 1, 1, {0})
        stage('host_release', lambda: runs['host'].key(OPEN_SCAN, False), 1, 1, set())
        stage('host_repress', lambda: runs['host'].key(OPEN_SCAN, True), 1, 0, {0})
        stage('host_release_again', lambda: runs['host'].key(OPEN_SCAN, False), 0, 0, set())
        stage('receiver_press_held_host_idle', lambda: runs['receiver'].key(OPEN_SCAN, True), 0, 1, {1})
        stage('host_jump_receiver_open_held', lambda: runs['host'].key(JUMP_SCAN, True), 1, 1, {1})
        stage('host_jump_release_receiver_open_held', lambda: runs['host'].key(JUMP_SCAN, False), 1, 1, {1})
        stage('receiver_release', lambda: runs['receiver'].key(OPEN_SCAN, False), 1, 1, set())
        stage('receiver_repress', lambda: runs['receiver'].key(OPEN_SCAN, True), 1, 0, {1})
        stage('receiver_release_again', lambda: runs['receiver'].key(OPEN_SCAN, False), 0, 0, set())
        checks = {name: all(v['expected_transition'] and v['duke_cursor'] and v['held_words_constant'] for v in data.values())
                  for name, data in result['stages'].items()}
        for run in runs.values():
            run.audit()
        checks['private_cpu_only_two_owned_input_fifos'] = True
        result.update(passed=all(checks.values()), checks=checks, phase='complete')
    except Exception as error:
        result['error'] = str(error)
        result['final_rows'] = {role: rows(obs.text())[-8:] for role, obs in observers.items()}
    finally:
        for run in runs.values():
            run.close()
        result['cleanup'] = all(p.poll() is not None for run in runs.values() for p in run.processes.values())
        (root/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
