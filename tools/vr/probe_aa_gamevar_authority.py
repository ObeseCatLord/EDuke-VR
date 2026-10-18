#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Diagnose AA CON gamevar authority across a native late join.

This private CPU/dummy-SDL probe includes the installed AA script, then adds
only server-side fixture assignments and observations.  It reports whether a
real late client observes the pre-join snapshot and the later server update;
it deliberately does not turn either outcome into a gameplay pass/fail claim.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

from smoke_multiplayer import CONFIG
from smoke_native_levels import assert_cpu_binary, assert_gpu_devices_absent, sanitised_env
from smoke_pistol_reload_native import Run, sha256


SYNC = 'Multiplayer client level synchronization complete.'
FIELDS = ('tick', 'player', 'local', 'phase', 'remote_tick', 'charsel', 'global', 'perplayer', 'nomulti')
ROW = re.compile(r'addlog aaauthority_(\w+)(?: \(player \d+\))? = (-?\d+)')
SERVER_PRE_JOIN = {'charsel': 16, 'global': 101, 'perplayer': 201, 'nomulti': 301}
SERVER_REMOTE_PRE = {'charsel': 16, 'global': 101, 'perplayer': -222, 'nomulti': 301}
CLIENT_PRE = {'charsel': 16, 'global': 101, 'perplayer': -222, 'nomulti': -333}
SERVER_POST = {'charsel': 2, 'global': 102, 'perplayer': 202, 'nomulti': 302}
CLIENT_POST = {'charsel': 2, 'global': 102, 'perplayer': 202, 'nomulti': -333}

# charsel is AA's installed global (AADEFS.CON): this fixture never redefines
# it.  The per-player value is intentionally defaulted on player 1 before the
# server changes that player's slot after real remote input starts.
WRAPPER = '''include scripts/AAGAME.CON
gamevar aauth_s_phase 0 0
gamevar aauth_s_remote_tick 0 0
gamevar aauth_s_global -111 0
gamevar aauth_s_perplayer -222 1
gamevar aauth_s_nomulti -333 524288
''' + ''.join(f'gamevar aaauthority_{name} 0 524288\n' for name in FIELDS) + '''
appendevent EVENT_PROCESSINPUT
 getactor[THISACTOR].yvel aaauthority_player
 setvarvar aaauthority_local myconnectindex
 ifserver
 {
  ife aauth_s_phase 0
  {
   set charsel 16
   set aauth_s_global 101
   set aauth_s_perplayer 201
   set aauth_s_nomulti 301
   set aauth_s_phase 1
  }
  ifvare aaauthority_player 1
  {
   addvar aauth_s_remote_tick 1
   ife aauth_s_phase 1
   ifge aauth_s_remote_tick 300
   {
    set charsel 2
    set aauth_s_global 102
    set aauth_s_perplayer 202
    set aauth_s_nomulti 302
    set aauth_s_phase 2
   }
  }
 }
 addvar aaauthority_tick 1
 setvarvar aaauthority_phase aauth_s_phase
 setvarvar aaauthority_remote_tick aauth_s_remote_tick
 setvarvar aaauthority_charsel charsel
 setvarvar aaauthority_global aauth_s_global
 setvarvar aaauthority_perplayer aauth_s_perplayer
 setvarvar aaauthority_nomulti aauth_s_nomulti
''' + ''.join(f' addlog aaauthority_{name}\n' for name in FIELDS) + 'endevent\n'


def rows(text, player=None):
    parsed, row = [], {}
    for key, value in ROW.findall(text):
        if key == 'tick':
            row = {}
        if key in FIELDS:
            row[key] = int(value)
        if key == 'nomulti' and len(row) == len(FIELDS):
            if player is None or row['player'] == player:
                parsed.append(row)
    return parsed


def latest(text, player):
    values = rows(text, player)
    return values[-1] if values else None


def matches(row, values):
    return row is not None and all(row[name] == value for name, value in values.items())


def sandbox(args):
    if args._sandboxed:
        return
    args.work_dir.mkdir(parents=True, exist_ok=True)
    env = sanitised_env()
    command = ['bwrap', '--ro-bind', '/', '/', '--dev', '/dev', '--proc', '/proc',
               '--unshare-pid', '--unshare-net', '--bind', str(args.work_dir), str(args.work_dir),
               '--chdir', str(Path.cwd()), '--clearenv']
    for name in ('PATH', 'LANG', 'LC_ALL', 'TZ'):
        if name in env:
            command += ['--setenv', name, env[name]]
    command += ['nice', '-n', '10', sys.executable, str(Path(__file__).resolve()),
                *sys.argv[1:], '--_sandboxed']
    os.execvpe('bwrap', command, env)


def hashes(args):
    source = Path(__file__).resolve().parents[2] / 'source' / 'duke3d' / 'src'
    paths = (args.binary, args.input_helper, args.mod / 'AA.grp',
             args.mod / 'scripts' / 'AAGAME.CON', Path(__file__).resolve(),
             source / 'gamevars.h', source / 'gamevars.cpp')
    return {str(path): sha256(path) for path in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'input-helper', 'mod', 'work-dir'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--port', type=int, default=25091)
    parser.add_argument('--_sandboxed', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    for name in ('binary', 'input_helper', 'mod', 'work_dir'):
        setattr(args, name, getattr(args, name).resolve())
    if not 1 <= args.port < 65535:
        parser.error('--port must be in 1..65534')
    needed = (args.binary, args.input_helper, args.mod / 'AA.grp', args.mod / 'scripts' / 'AAGAME.CON')
    if not all(path.is_file() for path in needed):
        parser.error('binary, input helper, AA.grp, and scripts/AAGAME.CON must exist')
    sandbox(args)
    assert_gpu_devices_absent()
    assert_cpu_binary(args.binary)
    root = Path(tempfile.mkdtemp(prefix='aa-gamevar-authority-', dir=args.work_dir))
    run = Run(args, root, args.binary, con_file='aa_gamevar_authority.con')
    result = {'diagnosis_complete': False, 'renderer': 'CPU classic SDL dummy (no XR/GPU)',
              'evidence_directory': str(root), 'hashes': hashes(args),
              'fixture_sha256': hashlib.sha256(WRAPPER.encode()).hexdigest(),
              'fixture_values': {'pre_join_server': SERVER_PRE_JOIN, 'remote_pre_server': SERVER_REMOTE_PRE,
                                 'remote_pre_client': CLIENT_PRE, 'post_remote_tick_300_server': SERVER_POST,
                                 'post_remote_tick_300_client': CLIENT_POST},
              'phase': 'setup'}
    try:
        for role in ('server', 'client'):
            lab = root / role
            lab.mkdir()
            run.labs[role] = lab
            (lab / 'eduke32.cfg').write_text(CONFIG.replace('ScreenBPP = 32', 'ScreenBPP = 8'))
            (lab / 'settings.cfg').write_text('// Owned AA gamevar authority probe.\n')
            (lab / 'autoexec.cfg').write_text('r_maxfps 15\n')
            (lab / 'aa_gamevar_authority.con').write_text(WRAPPER)
        common = ['-j', str(args.mod), '-g', str(args.mod / 'AA.grp'), '-h', 'duke3d.def']
        result['phase'] = 'server pre-join fixture'
        server = run.launch('server', common + ['-dedicated', '-port', str(args.port), '-c2', '-v1', '-l2', '-s1'])
        server.wait(lambda text: matches(latest(text, 0), {**SERVER_PRE_JOIN, 'phase': 1}), timeout=25)
        result['pre_join_server'] = latest(server.text(), 0)
        result['phase'] = 'actual AA late client join'
        client = run.launch('client', common + ['-connect', f'127.0.0.1:{args.port}'])
        deadline, next_return = time.monotonic() + 45, 0
        while time.monotonic() < deadline:
            text = client.text()
            run.audit()
            if SYNC in text and rows(text):
                break
            if 'Per-map .art file' in text and time.monotonic() >= next_return:
                run.key(40, True)
                client.pause(.08)
                run.key(40, False)
                next_return = time.monotonic() + 1
            client.pause(.12)
        else:
            raise RuntimeError('actual AA client did not reach native synchronization/input')
        client_index = rows(client.text())[-1]['local']
        if client_index <= 0:
            raise RuntimeError(f'client did not expose a remote native player index: {client_index}')
        server.wait(lambda text: latest(text, client_index) is not None, timeout=12)
        # The 300-tick server delay leaves a real joined-client pre-update
        # sample. No client fixture assignment or packet injection occurs.
        client_pre = latest(client.text(), client_index)
        server.wait(lambda text: matches(latest(text, client_index), {**SERVER_POST, 'phase': 2}), timeout=18)
        client.pause(1)
        run.audit()
        server_rows, client_rows = rows(server.text(), client_index), rows(client.text(), client_index)
        observed_pre = client_pre
        observed_post = latest(client.text(), client_index)
        server_pre = next((row for row in server_rows if matches(row, {**SERVER_REMOTE_PRE, 'phase': 1})), None)
        server_post = next((row for row in server_rows if matches(row, {**SERVER_POST, 'phase': 2})), None)
        pre_replicated = matches(observed_pre, CLIENT_PRE)
        post_replicated = matches(observed_post, CLIENT_POST)
        nomulti_excluded = all(row and row['nomulti'] == -333 for row in (observed_pre, observed_post))
        result.update(phase='complete', server_player_index=client_index, client_player_index=client_index,
                      native_synchronization=SYNC in client.text(),
                      server_remote_pre=server_pre,
                      client_pre=observed_pre, server_remote_post=server_post,
                      client_post=observed_post,
                      charsel_persisted_pre_join=matches(result['pre_join_server'], {**SERVER_PRE_JOIN, 'phase': 1}),
                      diagnosis={'pre_join_snapshot': 'replicated' if pre_replicated else 'diverged',
                                 'post_remote_tick_300': 'replicated' if post_replicated else 'diverged',
                                 'nomulti_control': 'remained_default' if nomulti_excluded else 'changed_or_missing'},
                      diagnosis_complete=bool(server_pre and server_post and observed_pre and observed_post and
                                              SYNC in client.text()))
    except Exception as error:
        result['error'] = str(error)
    finally:
        run.close()
        result['exit_codes'] = {role: process.returncode for role, process in run.processes.items()}
        result['cleanup'] = all(process.poll() is not None for process in run.processes.values())
        for role, lab in run.labs.items():
            log = lab / 'game.log'
            result.setdefault('tail_rows', {})[role] = rows(log.read_text(errors='replace'))[-8:] if log.exists() else []
        (root / 'result.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result['diagnosis_complete'] and result['cleanup'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
