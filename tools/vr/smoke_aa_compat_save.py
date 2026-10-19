#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Private AA wrapper save/restart/load and new-game qualification.

This never loads an observation module.  It uses the shipped AA compatibility
wrapper as the native main CON, private SDL FIFO or owned hidden-window input,
ordinary F2/F3 save and load menus, and native ``addlogvar`` reads. XR mode runs
inside software_xr_lab.py and reaches real gameplay with Monado controllers.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from smoke_actions import Observer
from smoke_multiplayer import CONFIG, X11, stop
from smoke_native_levels import assert_cpu_binary, assert_gpu_devices_absent, sanitised_env
from monado_remote import Remote


WRAPPER = HERE.parents[1] / 'package' / 'vr' / 'aa566' / 'eduke32_vr_aa566.con'
VARS = ('charsel', 'startmode', 'oldbits', 'pchar', 'cursorx', 'cursory')
VAR_LOG = re.compile(r"Variable '(" + '|'.join(VARS) + r")' has value (-?\d+)")
SAVE_HEADER = b'E32SAVEGAME'
E_SCAN, RETURN_SCAN = 8, 40
F2_SCAN, F3_SCAN, F4_SCAN, F5_SCAN, F12_SCAN = 59, 60, 61, 62, 69


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def reexec_sandbox(args):
    """Re-exec this exact entry point in an isolated, CPU-only namespace."""
    if args._sandboxed:
        return
    bwrap, nice = shutil.which('bwrap'), shutil.which('nice')
    if not bwrap or not nice:
        raise RuntimeError('bubblewrap and nice are required for the CPU-only runner')
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    safe = sanitised_env()
    child_args = [arg for arg in sys.argv[1:] if arg != '--_sandboxed'] + ['--_sandboxed']
    command = [bwrap, '--ro-bind', '/', '/', '--dev', '/dev', '--proc', '/proc',
               '--unshare-pid', '--unshare-net', '--bind', str(work), str(work),
               '--chdir', str(Path.cwd()), '--clearenv']
    for key in ('PATH', 'LANG', 'LC_ALL', 'TZ'):
        if key in safe:
            command += ['--setenv', key, safe[key]]
    command += [nice, '-n', '10', sys.executable, str(Path(__file__).resolve()), *child_args]
    os.execvpe(bwrap, command, safe)


class PrivateRun:
    def __init__(self, args, lab):
        self.args, self.lab = args, lab
        self.process = self.writer = self.log = self.observer = None
        self.x11 = X11(args.display) if args.xr else None
        self.remote = None
        self.command = [str(args.binary), '-usecwd', '-nosetup', '-noautoload', '-nologo', '-ns', '-nm',
                        '-j', str(args.mod_root), '-j', str(WRAPPER.parent),
                        '-g', str(args.mod_root / 'AA.grp'), '-x', WRAPPER.name,
                        '-h', 'duke3d.def', '-v1', '-l2', '-s1']

    def launch(self):
        if self.args.xr:
            env = {k: v for k, v in os.environ.items() if not k.startswith('EDUKE32_XR')}
            env.update(EDUKE32_XR='1', EDUKE32_XR_UI='2', EDUKE32_XR_SINGLE_PASS='1',
                       EDUKE32_XR_AIM='right', EDUKE32_XR_HAND_SHOTS='1', EDUKE32_XR_TEST_SHOTS='1')
            self.remote = Remote(self.args.remote_port)
            self.remote.neutral()
        else:
            fifo = self.lab / 'input.fifo'
            os.mkfifo(fifo, 0o600)
            if fifo.stat().st_mode & 0o077:
                raise RuntimeError('private SDL FIFO is not owner-only')
            self.writer = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
            env = sanitised_env()
            env.update(LD_PRELOAD=str(self.args.input_helper), EDUKE32_TEST_SDL_INPUT=str(fifo))
        self.log = (self.lab / 'game.log').open('w')
        self.process = subprocess.Popen(self.command, cwd=self.lab, env=env, stdin=subprocess.DEVNULL,
                                        stdout=self.log, stderr=subprocess.STDOUT)
        self.observer = Observer(self.process, self.lab / 'game.log')
        self.audit()
        return self.observer

    def audit(self):
        assert_gpu_devices_absent()
        if self.process.poll() is not None:
            raise RuntimeError('private AA process exited unexpectedly')
        maps = Path(f'/proc/{self.process.pid}/maps').read_text(errors='replace').lower()
        fds = []
        for fd in Path(f'/proc/{self.process.pid}/fd').iterdir():
            try:
                fds.append(os.readlink(fd).lower())
            except FileNotFoundError:
                pass
        forbidden = ('libnvidia',) if self.args.xr else ('libnvidia', 'libglx', 'libegl', 'libvulkan')
        if any(name in maps for name in forbidden) or any(
                '/dev/nvidia' in value or '/dev/dri' in value for value in fds):
            raise RuntimeError('private AA process mapped a GPU library or device')

    def tap(self, scan, pause=.18):
        if self.x11:
            keys = {E_SCAN: 'e', RETURN_SCAN: 'Return', F2_SCAN: 'F2', F3_SCAN: 'F3',
                    F4_SCAN: 'F4', F5_SCAN: 'F5', F12_SCAN: 'F12', 81: 'Down', 28: 'y'}
            window, _ = self.x11.owned_window(self.process.pid)
            if not window:
                raise RuntimeError('owned hidden SDL window not found')
            visibility = self.x11.window_visibility(window)
            if not visibility['unmapped'] or visibility['has_desktop_focus']:
                raise RuntimeError('private SDL window acquired desktop visibility or focus')
            self.x11.press(window, keys[scan], pause, external=True)
            time.sleep(pause)
            return
        os.write(self.writer, f'key {scan} 1\n'.encode())
        time.sleep(pause)
        os.write(self.writer, f'key {scan} 0\n'.encode())
        time.sleep(pause)

    def close(self):
        if self.remote:
            self.remote.close()
        if self.process:
            stop(self.process)
        if self.writer is not None:
            os.close(self.writer)
        if self.log:
            self.log.close()
        fifo = self.lab / 'input.fifo'
        if fifo.exists():
            fifo.unlink()


def make_lab(root, xr=False):
    lab = root / 'profile'
    lab.mkdir()
    (lab / 'eduke32.cfg').write_text(CONFIG if xr else CONFIG.replace('ScreenBPP = 32', 'ScreenBPP = 8'))
    (lab / 'settings.cfg').write_text('// Owned AA compatibility save profile.\n')
    (lab / 'autoexec.cfg').write_text(
        'r_maxfps 30\n'
        'unbind E\n'
        'bind E "gamefunc_Open"\n'
        'bind F4 norepeat "' + '; '.join('addlogvar ' + name for name in VARS) + '"\n'
        'bind F5 norepeat "echo AA_SAVE_NEWGAME_DISPATCH; map maps/oldeps/E1L1.MAP"\n')
    return lab


def observations_after(text):
    values = {}
    for name, value in VAR_LOG.findall(text):
        values[name] = int(value)
    return values


def snapshot(run):
    start = len(run.observer.text())
    deadline = time.monotonic() + 12
    # Native level entry can still be loading after its cache-time receipt.
    # Retry only this read-only command until actual gameplay dispatches it.
    while time.monotonic() < deadline:
        run.tap(F4_SCAN)
        values = observations_after(run.observer.text()[start:])
        if set(values) == set(VARS):
            return values
        run.audit()
        time.sleep(.2)
    raise RuntimeError('native addlogvar bindings did not return all AA values')


def wait_ready(run, offset=0):
    deadline, next_return = time.monotonic() + 45, 0
    while time.monotonic() < deadline:
        text = run.observer.text()[offset:]
        run.audit()
        if 'Cache time:' in text:
            return snapshot(run)
        if 'Per-map .art file' in text and time.monotonic() >= next_return:
            run.tap(RETURN_SCAN)
            next_return = time.monotonic() + 1
        time.sleep(.1)
    raise RuntimeError('AA did not reach the private native input barrier')


def save_header(path):
    content = path.read_bytes()[:328]
    return {'path': str(path), 'sha256': sha256(path), 'size': path.stat().st_size,
            'e32savegame_magic': content.startswith(SAVE_HEADER),
            'wrapper_name_present': WRAPPER.name.encode() in content}


def save_with_native_menu(run, lab):
    before = set(lab.glob('save*.esv'))
    offset = len(run.observer.text())
    run.tap(F2_SCAN)
    time.sleep(.35)
    run.tap(RETURN_SCAN)
    screenshot(run, lab)
    run.tap(RETURN_SCAN)
    try:
        run.observer.wait(lambda text: bool(set(lab.glob('save*.esv')) - before) and 'Saved: ' in text[offset:], timeout=15)
    except RuntimeError as error:
        raise RuntimeError('native F2 save UI gave no post-selection save receipt') from error
    created = sorted(set(lab.glob('save*.esv')) - before)
    if len(created) != 1:
        raise RuntimeError('native save UI did not create exactly one private save')
    return created[0]


def load_with_native_menu(run):
    start = len(run.observer.text())
    run.tap(F3_SCAN)
    time.sleep(.35)
    screenshot(run, run.lab)
    # Fresh restart creates a newer automatic entry. The immediately preceding
    # user save is the next row; restoration is verified from native state.
    run.tap(81)  # SDL_SCANCODE_DOWN
    run.tap(RETURN_SCAN)
    run.tap(28)  # SDL_SCANCODE_Y: ordinary Load Game confirmation
    # Loading does not emit a universal success string. A subsequent native
    # read observes the restored saved values; loading diagnostics are retained
    # separately and never inferred merely from the script-name header.
    time.sleep(1.0)
    return start, snapshot(run)


def start_gameplay(run):
    """Drive native AA cursor with real Monado controls, observing named vars."""
    remote = run.remote
    current = snapshot(run)
    if current['charsel'] != 1 or current['startmode'] != -1:
        raise RuntimeError('Duke must be selected before native START navigation')
    for axis, field, low, high in [('x', 'cursorx', 265, 316), ('y', 'cursory', 21, 54)]:
        origin = current[field]
        setattr(remote.packet.right.thumbstick, axis, .4)
        remote.send()
        try:
            for _ in range(8):
                changed = snapshot(run)
                if changed[field] != origin:
                    break
            else:
                raise RuntimeError('native cursor did not respond to controller ' + axis)
        finally:
            remote.neutral()
        direction = 1 if changed[field] > origin else -1
        current = snapshot(run)
        for _ in range(20):
            if low <= current[field] <= high:
                break
            value = .4 * direction * (1 if current[field] < low else -1)
            setattr(remote.packet.right.thumbstick, axis, value)
            remote.send()
            try:
                snapshot(run)
            finally:
                remote.neutral()
            current = snapshot(run)
        else:
            raise RuntimeError('native cursor did not settle in START ' + axis)
    cursor = current
    remote.packet.left.squeeze_value = 1   # left grip: native Open (use/interact)
    remote.send()
    try:
        for _ in range(12):
            current = snapshot(run)
            if current['startmode'] == 1 and current['pchar'] == 0:
                break
        else:
            raise RuntimeError('controller START did not enter actual Duke gameplay')
    finally:
        remote.neutral()
    return {'start_cursor': cursor, 'gameplay': snapshot(run)}


def fire_in_gameplay(run):
    """Require a fresh native tracked hit, then release the physical trigger."""
    from smoke_hitscan import rays
    offset = len(run.observer.text())
    run.remote.packet.right.trigger_value = 1
    run.remote.packet.right.trigger_click = True
    run.remote.send()
    try:
        run.observer.wait(lambda text: bool(rays(text[offset:], 0)), timeout=12)
    finally:
        run.remote.neutral()
    time.sleep(.5)
    return rays(run.observer.text()[offset:], 0)


def screenshot(run, lab):
    before = set((lab / 'screenshots').glob('duke*.png')) if (lab / 'screenshots').exists() else set()
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        run.tap(F12_SCAN)
        created = set((lab / 'screenshots').glob('duke*.png')) - before
        if created and 'Saved screenshot to screenshots/' in run.observer.text():
            return str(sorted(created)[0])
        run.audit()
        time.sleep(.3)
    raise RuntimeError('native screenshot key did not create its owned image')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'mod-root', 'work-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--input-helper', type=Path)
    parser.add_argument('--xr', action='store_true', help='run inside the existing private software XR lab')
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int)
    parser.add_argument('--_sandboxed', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    for name in ('binary', 'mod_root', 'work_dir'):
        setattr(args, name, getattr(args, name).resolve())
    if args.input_helper:
        args.input_helper = args.input_helper.resolve()
    if args.xr:
        if not args.remote_port or os.environ.get('EDUKE32_TEST_PRIVATE_WINDOW') != '1' or os.environ.get('LIBGL_ALWAYS_SOFTWARE') != '1':
            parser.error('--xr requires the existing private software XR lab and --remote-port')
    elif not args.input_helper or not args.input_helper.is_file():
        parser.error('CPU mode requires --input-helper')
    for path in (args.binary, args.mod_root / 'AA.grp', args.mod_root / 'duke3d.def', WRAPPER):
        if not path.is_file():
            parser.error('missing required input: ' + str(path))
    if not args.xr:
        reexec_sandbox(args)
        assert_cpu_binary(args.binary)
    assert_gpu_devices_absent()
    root = Path(tempfile.mkdtemp(prefix='aa-compat-save-', dir=args.work_dir))
    lab = make_lab(root, args.xr)
    result = {'passed': False, 'phase': 'setup', 'evidence_directory': str(root),
              'command': None, 'no_mx_observer': True, 'xr': args.xr,
              'wrapper': {'path': str(WRAPPER), 'sha256': sha256(WRAPPER)},
              'binary_sha256': sha256(args.binary), 'checks': {}, 'states': {}}
    first = second = None
    try:
        result['phase'] = 'fresh private profile and AA selector'
        first = PrivateRun(args, lab)
        first.launch()
        result['command'] = first.command
        if '-mx' in first.command or first.command[first.command.index('-x') + 1] != WRAPPER.name:
            raise RuntimeError('compatibility launch did not use the stable native -x wrapper basename')
        initial = wait_ready(first)
        result['states']['fresh_initial'] = initial
        if initial['charsel'] != 0 or initial['startmode'] != -1:
            raise RuntimeError('fresh private AA selector did not expose its unselected native state')

        result['phase'] = 'ordinary Duke Open press/release edges'
        first.tap(E_SCAN)
        selected = snapshot(first)
        first.tap(E_SCAN)
        deselected = snapshot(first)
        first.tap(E_SCAN)
        saved_state = snapshot(first)
        result['states'].update(selected=selected, deselected=deselected, saved_state=saved_state)
        if not (selected['charsel'] == 1 and deselected['charsel'] == 0 and saved_state['charsel'] == 1):
            raise RuntimeError('ordinary E Open press/release did not toggle the native Duke character bit')
        if args.xr:
            result['phase'] = 'controller START and actual tracked gameplay'
            result['controller'] = start_gameplay(first)
            result['first_hits'] = fire_in_gameplay(first)
            result['gameplay_screenshot'] = screenshot(first, lab)
            saved_state = snapshot(first)
            result['states']['saved_state'] = saved_state

        result['phase'] = 'native F2 private save UI'
        saved_path = save_with_native_menu(first, lab)
        result['save'] = save_header(saved_path)
        result['screenshot'] = screenshot(first, lab)
        first.audit()
        first.close()
        (lab / 'game.log').rename(lab / 'first-game.log')
        result['logs'] = {'first': str(lab / 'first-game.log')}
        first = None

        result['phase'] = 'fresh process then native F3 load UI'
        second = PrivateRun(args, lab)
        second.launch()
        restarted_initial = wait_ready(second)
        result['states']['restart_initial'] = restarted_initial
        load_offset, restored = load_with_native_menu(second)
        result['states']['restored'] = restored
        post_load = second.observer.text()[load_offset:]
        result['load_diagnostics'] = {'incompatible_savegame': 'Incompatible savegame.' in post_load,
                                      'missing_saved_label': "couldn't find savegame label" in post_load,
                                      'log_offset': load_offset}
        if restored != saved_state:
            raise RuntimeError('native F3 load did not restore the saved AA gamevar state')
        if result['load_diagnostics']['incompatible_savegame'] or result['load_diagnostics']['missing_saved_label']:
            raise RuntimeError('native F3 load reported a save compatibility or label restoration failure')

        result['phase'] = 'restored-state input then second native new game'
        if args.xr:
            result['restored_hits'] = fire_in_gameplay(second)
            result['restored_gameplay_screenshot'] = screenshot(second, lab)
        else:
            second.tap(E_SCAN)
        continued = snapshot(second)
        change_offset = len(second.observer.text())
        for _ in range(8):
            second.tap(F5_SCAN, pause=.3)
            if 'AA_SAVE_NEWGAME_DISPATCH' in second.observer.text()[change_offset:]:
                break
        else:
            raise RuntimeError('native F5 binding did not dispatch the requested second new game')
        reset = wait_ready(second, change_offset)
        if 'E1L2: HOLLYWOOD HOLOCAUST' not in second.observer.text()[change_offset:]:
            raise RuntimeError('second new game did not load the requested AA map')
        second.tap(E_SCAN)
        reset_input = snapshot(second)
        second.audit()
        result['states']['continued_input'] = continued
        result['states']['second_new_game'] = reset
        result['states']['second_new_game_input'] = reset_input
        result['checks'] = {
            'fresh_profile_selector_is_unselected': initial['charsel'] == 0 and initial['startmode'] == -1,
            'ordinary_E_press_release_toggles_Duke_selection': selected['charsel'] == 1 and deselected['charsel'] == 0,
            'native_F2_save_UI_created_private_E32_save': result['save']['e32savegame_magic'],
            'save_uses_stable_shipped_wrapper_name': result['save']['wrapper_name_present'],
            'restart_native_F3_restores_exact_observed_state': restored == saved_state,
            'load_has_no_incompatible_or_missing_label_diagnostic': not (
                result['load_diagnostics']['incompatible_savegame'] or result['load_diagnostics']['missing_saved_label']),
            'restored_state_accepts_new_native_input': bool(result.get('restored_hits')) if args.xr else continued['charsel'] == 0,
            'native_map_command_starts_second_new_game': True,
            'second_new_game_resets_selector_and_accepts_Open': reset == initial and reset_input['charsel'] == 1,
            'private_GPU_device_denied_process': True,
            'no_mx_observation_module': '-mx' not in result['command'],
        }
        result['passed'] = all(result['checks'].values())
        result['phase'] = 'complete'
    except Exception as error:
        result['error'] = str(error)
        active = second or first
        if active and active.process and active.process.poll() is None:
            try:
                result['failure_screenshot'] = screenshot(active, lab)
            except Exception as capture_error:
                result['capture_error'] = str(capture_error)
    finally:
        for run in (second, first):
            if run:
                run.close()
        result['cleanup'] = all(run is None or run.process is None or run.process.poll() is not None
                                for run in (first, second))
        for label, run in (('first', first), ('second', second)):
            if run and (run.lab / 'game.log').exists():
                result.setdefault('logs', {})[label] = str(run.lab / 'game.log')
        (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] and result['cleanup'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
