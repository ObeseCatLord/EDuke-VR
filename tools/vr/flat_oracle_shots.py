#!/usr/bin/env python3
"""Run a flat (non-VR) EDuke32-family binary, e.g. stock amcduke32, on the lab display and take its own
F12 screenshots after scripted key presses, for side-by-side comparison with VR captures.

Run inside tools/vr/software_xr_lab.py (it owns the Xvfb). Steps file: JSON list of
{"wait": s} | {"keys": [...]} | {"console": "cmd"} | {"shot": true} (F12). The game plays from a writable folder inside
--work-dir that symlinks every entry of --game-link (real copies of its .cfg files).
"""
import argparse, json, os, shutil, subprocess, time
from pathlib import Path
from smoke_multiplayer import X11
from smoke_world import CONFIG

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', required=True, type=Path)
parser.add_argument('--game-link', required=True, type=Path)
parser.add_argument('--work-dir', required=True, type=Path)
parser.add_argument('--script', required=True, type=Path)
parser.add_argument('--display', default=':105')
parser.add_argument('--args', default='')
parser.add_argument('--env', action='append', default=[], help='KEY=VALUE for the game')
parser.add_argument('--config-name', default='eduke32.cfg', help='config file the binary reads (amcduke32: amcsquad.cfg)')
args = parser.parse_args()
game = args.work_dir / 'game'
game.mkdir(parents=True)
for entry in sorted(args.game_link.resolve().iterdir()):
    if entry.is_file() and entry.suffix.lower() in ('.cfg', '.ini'):
        (game / entry.name).write_bytes(entry.read_bytes())
    elif entry.is_dir() and not entry.is_symlink() and entry.name in ('DATA', 'savegames'):
        shutil.copytree(entry, game / entry.name)   # folders the game writes into
    else:
        (game / entry.name).symlink_to(entry)
(game / args.config_name).write_text(CONFIG)  # no config: the binary would open its setup window
env = dict(os.environ, DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy')
env.pop('WAYLAND_DISPLAY', None)
console = args.work_dir / 'console-request'
env['EDUKE32_XR_CONSOLE_REQUEST'] = str(console)
env.update(kv.split('=', 1) for kv in args.env)
log = (args.work_dir / 'game.log').open('w')
process = subprocess.Popen([str(args.binary.resolve()), '-usecwd', '-nosetup', *args.args.split()], cwd=game, env=env,
                           stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
x11 = X11(args.display)
result = {'shots': []}
try:
    window = None
    for _ in range(600):
        window, _ = x11.owned_window(process.pid)
        if window or process.poll() is not None:
            break
        time.sleep(.1)
    if not window:
        raise RuntimeError('no game window')
    def press(key):
        # The window is recreated when the video mode is set: find it again for every key.
        current, _ = x11.owned_window(process.pid)
        x11.press(current or window, key, .08, True)
    for step in json.loads(args.script.read_text()):
        if 'wait' in step:
            time.sleep(step['wait'])
        for key in step.get('keys', []):
            press(key); time.sleep(.35)
        if 'console' in step:
            console.write_text(step['console'] + '\n')
            for _ in range(300):
                if not console.exists(): break
                time.sleep(.1)
        if step.get('shot'):
            before = set(game.iterdir())
            press('F12'); time.sleep(2)
            result['shots'] += [str(p) for p in set(game.iterdir()) - before]
finally:
    process.terminate()
    try:
        process.wait(10)
    except subprocess.TimeoutExpired:
        process.kill()
print(json.dumps(result, indent=1))
