#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Launch an isolated local multiplayer join and retain bounded runtime evidence.

The test owns both game processes and, unless --external-display is supplied,
its Xvfb process. It never writes to the supplied GRP or the caller's normal
EDuke32 configuration.
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

from PIL import Image, ImageChops


CONFIG = """[Setup]
ConfigVersion = 260
ForceSetup = 0
NoAutoLoad = 1
[Screen Setup]
ScreenMode = 0
ScreenWidth = 640
ScreenHeight = 480
ScreenBPP = 32
[Controls]
UseMouse = 0
UseJoystick = 0
"""


def start(command, **kwargs):
    return subprocess.Popen(command, stdin=subprocess.DEVNULL, **kwargs)


def stop(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def setup_lab(root, name, grp, direct_grp):
    lab = root / name
    lab.mkdir()
    (lab / 'eduke32.cfg').write_text(CONFIG)
    if not direct_grp:
        (lab / 'DUKE3D.GRP').symlink_to(grp)
    return lab


class X11:
    def __init__(self, display):
        self.x = c.CDLL('libX11.so.6')
        self.xtst = c.CDLL('libXtst.so.6')
        self.x.XOpenDisplay.argtypes = [c.c_char_p]
        self.x.XOpenDisplay.restype = c.c_void_p
        self.x.XDefaultRootWindow.argtypes = [c.c_void_p]
        self.x.XDefaultRootWindow.restype = c.c_ulong
        self.x.XQueryTree.argtypes = [c.c_void_p, c.c_ulong, c.POINTER(c.c_ulong), c.POINTER(c.c_ulong),
                                      c.POINTER(c.POINTER(c.c_ulong)), c.POINTER(c.c_uint)]
        self.x.XGetGeometry.argtypes = [c.c_void_p, c.c_ulong, c.POINTER(c.c_ulong), c.POINTER(c.c_int),
                                        c.POINTER(c.c_int), c.POINTER(c.c_uint), c.POINTER(c.c_uint),
                                        c.POINTER(c.c_uint), c.POINTER(c.c_uint)]
        self.x.XFree.argtypes = [c.c_void_p]
        self.x.XInternAtom.argtypes = [c.c_void_p, c.c_char_p, c.c_int]
        self.x.XInternAtom.restype = c.c_ulong
        self.x.XGetWindowProperty.argtypes = [c.c_void_p, c.c_ulong, c.c_ulong, c.c_long, c.c_long, c.c_int,
                                               c.c_ulong, c.POINTER(c.c_ulong), c.POINTER(c.c_int),
                                               c.POINTER(c.c_ulong), c.POINTER(c.c_ulong),
                                               c.POINTER(c.POINTER(c.c_ubyte))]
        self.x.XSendEvent.argtypes = [c.c_void_p, c.c_ulong, c.c_int, c.c_long, c.c_void_p]
        self.x.XMapRaised.argtypes = [c.c_void_p, c.c_ulong]
        self.x.XSetInputFocus.argtypes = [c.c_void_p, c.c_ulong, c.c_int, c.c_ulong]
        self.x.XStringToKeysym.argtypes = [c.c_char_p]
        self.x.XStringToKeysym.restype = c.c_ulong
        self.x.XKeysymToKeycode.argtypes = [c.c_void_p, c.c_ulong]
        self.x.XFlush.argtypes = [c.c_void_p]
        self.x.XSync.argtypes = [c.c_void_p, c.c_int]
        error_type = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_void_p)
        self.error_seen = False
        def record_error(_display, _event):
            self.error_seen = True
            return 0
        self.error_handler = error_type(record_error)
        self.x.XSetErrorHandler.argtypes = [error_type]
        self.x.XSetErrorHandler(self.error_handler)
        self.xtst.XTestFakeKeyEvent.argtypes = [c.c_void_p, c.c_uint, c.c_int, c.c_ulong]
        self.display = self.x.XOpenDisplay(display.encode())
        if not self.display:
            raise RuntimeError(f'cannot open X display {display}')

    def children(self, parent):
        root_return, parent_return, children = c.c_ulong(), c.c_ulong(), c.POINTER(c.c_ulong)()
        count = c.c_uint()
        self.x.XQueryTree(self.display, parent, c.byref(root_return), c.byref(parent_return), c.byref(children), c.byref(count))
        result = [int(children[i]) for i in range(count.value)]
        if children:
            self.x.XFree(children)
        return result

    def geometry(self, window):
        origin, x, y, width, height, border, depth = (c.c_ulong(), c.c_int(), c.c_int(), c.c_uint(), c.c_uint(),
                                                       c.c_uint(), c.c_uint())
        self.x.XGetGeometry(self.display, window, c.byref(origin), c.byref(x), c.byref(y), c.byref(width),
                            c.byref(height), c.byref(border), c.byref(depth))
        return int(width.value), int(height.value), int(x.value), int(y.value)

    def owner_pid(self, window):
        actual_type, format_bits = c.c_ulong(), c.c_int()
        item_count, bytes_after = c.c_ulong(), c.c_ulong()
        data = c.POINTER(c.c_ubyte)()
        atom = self.x.XInternAtom(self.display, b'_NET_WM_PID', 1)
        status = self.x.XGetWindowProperty(self.display, window, atom, 0, 1, 0, 6, c.byref(actual_type),
                                           c.byref(format_bits), c.byref(item_count), c.byref(bytes_after), c.byref(data))
        try:
            if status == 0 and data and format_bits.value == 32 and item_count.value:
                return c.cast(data, c.POINTER(c.c_uint32))[0]
        finally:
            if data:
                self.x.XFree(data)
        return None

    def owned_window(self, pid):
        pending = self.children(self.x.XDefaultRootWindow(self.display))
        candidates = []
        while pending:
            window = pending.pop()
            pending.extend(self.children(window))
            width, height, x, y = self.geometry(window)
            if self.owner_pid(window) == pid and width >= 320 and height >= 200:
                candidates.append((window, f'{width}x{height}+{x}+{y}', width * height))
        if not candidates:
            return None, None
        window, geometry, _ = max(candidates, key=lambda item: item[2])
        return window, geometry

    def send_event_key(self, window, key, pressed):
        class Key(c.Structure):
            _fields_ = [('type', c.c_int), ('serial', c.c_ulong), ('send_event', c.c_int), ('display', c.c_void_p),
                        ('window', c.c_ulong), ('root', c.c_ulong), ('subwindow', c.c_ulong), ('time', c.c_ulong),
                        ('x', c.c_int), ('y', c.c_int), ('x_root', c.c_int), ('y_root', c.c_int), ('state', c.c_uint),
                        ('keycode', c.c_uint), ('same_screen', c.c_int)]
        class Event(c.Union):
            _fields_ = [('key', Key), ('padding', c.c_long * 24)]
        code = self.x.XKeysymToKeycode(self.display, self.x.XStringToKeysym(key.encode()))
        event = Event()
        event.key = Key(2 if pressed else 3, 0, 1, self.display, window, self.x.XDefaultRootWindow(self.display),
                        0, 0, 10, 10, 10, 10, 0, code, 1)
        self.x.XSendEvent(self.display, window, 0, 1 if pressed else 2, c.byref(event))
        self.x.XFlush(self.display)

    def press(self, window, key, seconds, external):
        if external:
            self.x.XSync(self.display, 0)
            self.error_seen = False
            self.send_event_key(window, key, True)
            time.sleep(seconds)
            self.send_event_key(window, key, False)
            self.x.XSync(self.display, 0)
            if self.error_seen:
                raise RuntimeError('owned SDL window changed during input; test did not send input to another window')
            return
        code = self.x.XKeysymToKeycode(self.display, self.x.XStringToKeysym(key.encode()))
        self.x.XMapRaised(self.display, window)
        self.x.XSetInputFocus(self.display, window, 1, 0)
        self.xtst.XTestFakeKeyEvent(self.display, code, 1, 0)
        self.x.XFlush(self.display)
        time.sleep(seconds)
        self.xtst.XTestFakeKeyEvent(self.display, code, 0, 0)
        self.x.XFlush(self.display)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--client-binary', type=Path, help='optional client executable for mixed native/XR joins')
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--mode', choices=('listen', 'dedicated'), required=True)
    parser.add_argument('--port', type=int, default=24585)
    parser.add_argument('--seconds', type=int, default=12)
    parser.add_argument('--display', default=':95')
    parser.add_argument('--external-display', action='store_true', help='reuse --display; do not create or stop Xvfb')
    parser.add_argument('--xr-client', action='store_true', help='set EDUKE32_XR=1 and capture 60 client stereo frames')
    parser.add_argument('--direct-grp', action='store_true', help='pass the GRP via -g instead of creating a local symlink')
    parser.add_argument('--input', action='store_true', help='accepted for compatibility; the owned-window input check always runs')
    parser.add_argument('--reconnect', action='store_true', help='replace the client once while retaining the server')
    args = parser.parse_args()

    binary, grp = args.binary.resolve(), args.grp.resolve()
    client_binary = (args.client_binary or binary).resolve()
    if not binary.is_file() or not client_binary.is_file() or not grp.is_file():
        parser.error('server binary, client binary, and owned GRP must exist')
    if not 1 <= args.port <= 65535 or not 5 <= args.seconds <= 60:
        parser.error('port must be 1..65535 and seconds 5..60')
    if not shutil.which('import'):
        parser.error('ImageMagick import is required')
    if not args.external_display and not shutil.which('Xvfb'):
        parser.error('Xvfb is required unless --external-display is used')

    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f'network-ready-{args.mode}-', dir=args.work_dir.resolve()))
    server_lab = setup_lab(root, 'server', grp, args.direct_grp)
    client_lab = setup_lab(root, 'client', grp, args.direct_grp)
    base_env = dict(os.environ, DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy')
    server_env = dict(base_env)
    for key in ('EDUKE32_XR', 'XR_RUNTIME_JSON', 'XR_ENABLE_API_LAYERS', 'EDUKE32_XR_DIAGNOSTIC_FRAMES',
                'EDUKE32_XR_DIAGNOSTIC_OUTPUT'):
        server_env.pop(key, None)
    client_env = dict(base_env)
    if args.xr_client:
        client_env['EDUKE32_XR'] = '1'
        client_env.pop('EDUKE32_XR_DIAGNOSTIC_FRAMES', None)
        client_env['EDUKE32_XR_WORLD_OUTPUT'] = str(client_lab / 'stereo')

    xvfb = server = client = None
    client_log_paths = []
    try:
        if not args.external_display:
            xvfb = start(['Xvfb', args.display, '-screen', '0', '1280x720x24', '-nolisten', 'tcp'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(.4)
            if xvfb.poll() is not None:
                raise RuntimeError(f'Xvfb {args.display} exited early')

        server_args = ['-usecwd', '-nosetup', '-noautoload', '-port', str(args.port), '-v1', '-l1', '-s1']
        if args.mode == 'dedicated':
            server_args.insert(3, '-dedicated')
        else:
            server_args.insert(3, '-server')
        if args.direct_grp:
            server_args.extend(('-g', str(grp)))
        server_log = (server_lab / 'server.log').open('w')
        server = start([str(binary), *server_args], cwd=server_lab, env=server_env,
                       stdout=server_log, stderr=subprocess.STDOUT)
        time.sleep(3)
        x11 = X11(args.display)
        client_log = (client_lab / 'client.log').open('w')
        client_log_paths.append(client_lab / 'client.log')
        client_command = [str(client_binary), '-usecwd', '-nosetup', '-noautoload', '-nologo', '-connect', f'127.0.0.1:{args.port}']
        if args.direct_grp:
            client_command.extend(('-g', str(grp)))
        client = start(client_command,
                       cwd=client_lab, env=client_env, stdout=client_log, stderr=subprocess.STDOUT)

        def enter_game(process, log_path):
            # Skip the native intro with -nologo, then wait for the actual
            # existing level barrier. Never use Escape to bypass a network wait.
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and process.poll() is None:
                if 'Multiplayer client level synchronization complete.' in log_path.read_text(errors='replace'):
                    candidate, _ = x11.owned_window(process.pid)
                    if candidate:
                        # G_DisplayLogo resets ready2send even with -nologo,
                        # then G_PlaybackDemo opens the native startup menu.
                        # Let that finite fade finish before dismissing it.
                        time.sleep(1.5)
                        candidate, _ = x11.owned_window(process.pid)
                        if candidate is None:
                            continue
                        x11.press(candidate, 'Escape', .06, args.external_display)
                        return
                time.sleep(.1)
            raise RuntimeError('client did not reach an owned loaded-level window')

        enter_game(client, client_log_paths[-1])
        deadline = time.monotonic() + (args.seconds if not args.reconnect else max(3, args.seconds // 2))
        while time.monotonic() < deadline and client.poll() is None and server.poll() is None:
            time.sleep(.1)

        reconnect_completed = False
        if args.reconnect and server.poll() is None:
            stop(client)
            client_log.close()
            time.sleep(.5)

            reconnect_lab = setup_lab(root, 'client-reconnect', grp, args.direct_grp)
            client_log = (reconnect_lab / 'client.log').open('w')
            client_log_paths.append(reconnect_lab / 'client.log')
            if args.xr_client:
                client_env['EDUKE32_XR_WORLD_OUTPUT'] = str(reconnect_lab / 'stereo')
            client = start(client_command, cwd=reconnect_lab, env=client_env,
                           stdout=client_log, stderr=subprocess.STDOUT)
            enter_game(client, client_log_paths[-1])
            deadline = time.monotonic() + max(3, args.seconds // 2)
            while time.monotonic() < deadline and client.poll() is None and server.poll() is None:
                time.sleep(.1)
            reconnect_completed = client.poll() is None

        window = None
        geometry = None
        if x11:
            for _ in range(20):
                window, geometry = x11.owned_window(client.pid)
                if window is not None:
                    break
                time.sleep(.1)
        if args.external_display and window is None:
            raise RuntimeError('could not find a sensible window owned by the client process')
        screenshot = root / 'screen.png'
        capture_target = window or 'root'
        subprocess.run(['import', '-display', args.display, '-window', str(capture_target), str(screenshot)],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        input_evidence = {}
        if window:
            before = root / 'client-before-input.png'
            after = root / 'client-after-input.png'
            subprocess.run(['import', '-display', args.display, '-window', str(window), str(before)],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            x11.press(window, 'w', .5, args.external_display)
            time.sleep(.3)
            subprocess.run(['import', '-display', args.display, '-window', str(window), str(after)],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            input_evidence = {'client_pid': client.pid, 'client_window': window, 'client_geometry': geometry,
                              'before_input': str(before), 'after_input': str(after)}
        server_log.close()
        client_log.close()
        server_text = (server_lab / 'server.log').read_text(errors='replace')
        client_text = '\n'.join(path.read_text(errors='replace') for path in client_log_paths)
        changed_pixels = 0
        if input_evidence:
            difference = ImageChops.difference(Image.open(before).convert('RGB'), Image.open(after).convert('RGB'))
            pixels = difference.tobytes()
            changed_pixels = sum(any(pixels[i:i+3]) for i in range(0, len(pixels), 3))
        xr_world_frames = all('OpenXR world oracle: 60 frames' in path.read_text(errors='replace')
                              for path in client_log_paths) if args.xr_client else None
        xr_eye_readbacks = all((path.parent / 'stereo-left.ppm').is_file()
                              and (path.parent / 'stereo-right.ppm').is_file()
                              and (path.parent / 'stereo-left.ppm').read_bytes() != (path.parent / 'stereo-right.ppm').read_bytes()
                              for path in client_log_paths) if args.xr_client else None
        result = {
            'mode': args.mode,
            'server_exit_before_cleanup': server.poll(),
            'client_exit_before_cleanup': client.poll(),
            'server_initialized': 'Multiplayer server initialized.' in server_text,
            'client_backtrace': 'Program received signal' in client_text,
            'reconnect_completed': reconnect_completed,
            'owned_client_window': window is not None,
            'input_changed_pixels': changed_pixels,
            'xr_client': args.xr_client,
            'xr_world_60_frames_per_join': xr_world_frames,
            'xr_distinct_eye_readbacks_per_join': xr_eye_readbacks,
            'screenshot': str(screenshot),
            'evidence_directory': str(root),
        }
        result.update(input_evidence)
        print(json.dumps(result, indent=2))
        passed = (result['server_initialized'] and result['server_exit_before_cleanup'] is None
                  and result['client_exit_before_cleanup'] is None and result['owned_client_window']
                  and result['input_changed_pixels'] > 0 and not result['client_backtrace']
                  and (not args.xr_client or (xr_world_frames and xr_eye_readbacks)))
        return 0 if passed else 1
    finally:
        stop(client)
        stop(server)
        stop(xvfb)


if __name__ == '__main__':
    raise SystemExit(main())
