#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Desktop (flat, no headset) play smoke test in a private X display.

Starts a level the way a desktop player does (eduke32-vr-play --desktop, or a binary directly),
then plays a little through key events sent to the game's own window (walk, turn, fire, switch
weapon, open and close the menu) and screenshots the window after each step. Passes when every
screenshot shows a picture, the view changes as the player walks and turns, the game is still
running, and no OpenXR session was started.

Run inside tools/vr/software_xr_lab.py (it owns the X display; no desktop input or focus).
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

import numpy as np
from PIL import Image

from smoke_world import CONFIG
from smoke_multiplayer import X11

HERE = Path(__file__).resolve().parent


def children_of(pid):
    out = []
    for stat in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields = stat.read_text().rsplit(')', 1)[1].split()
        except OSError:
            continue
        if int(fields[1]) == pid:
            out.append(int(stat.parent.name))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--pack', default='default', help='launcher --pack; "default": the game\'s own choice')
    parser.add_argument('--direct', action='store_true', help='run the binary itself instead of eduke32-vr-play --desktop')
    parser.add_argument('--level', default='1,2', help='episode,level (default E1L2)')
    parser.add_argument('--args', default='', help='extra EDuke32 arguments')
    args = parser.parse_args()

    args.work_dir.mkdir(parents=True, exist_ok=True)
    lab = Path(tempfile.mkdtemp(prefix='desktop-', dir=args.work_dir.resolve()))
    # Synthetic key events cannot carry the Ctrl modifier the default Fire key needs: fire on F.
    (lab / 'eduke32.cfg').write_text(CONFIG)
    (lab / 'settings.cfg').write_text('bind "F" "gamefunc_Fire"\n')
    (lab / 'DUKE3D.GRP').symlink_to(args.grp.resolve())
    env = {k: v for k, v in os.environ.items() if not k.startswith('EDUKE32_XR')}
    env.update(DISPLAY=args.display, SDL_AUDIODRIVER='dummy', XDG_DATA_HOME=str(lab / 'data'),
               XDG_CONFIG_HOME=str(lab / 'config'), EDUKE32_TEST_FLAT_CAPTURE=str(lab / 'capture-request'))
    episode, level = args.level.split(',')
    game_args = ['-usecwd', '-nosetup', '-noautoload', '-nologo', f'-v{episode}', f'-l{level}', '-s2', *args.args.split()]
    if args.direct:
        command = [str(args.binary.resolve()), *game_args]
    else:
        launcher = HERE.parents[1] / 'package/vr/eduke32-vr-play'
        pack = [] if args.pack == 'default' else ['--pack', args.pack]
        command = [str(launcher), '--desktop', '--no-voxel-build', '--binary', str(args.binary.resolve()), *pack, '--', *game_args]
    result = {'passed': False, 'lab': str(lab), 'command': command, 'shots': {}, 'checks': {}}
    log = lab / 'game.log'
    with log.open('w') as out:
        process = subprocess.Popen(command, cwd=lab, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
    try:
        text = lambda: log.read_text(errors='replace')
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and process.poll() is None and f'E{episode}L{level}' not in text().upper():
            time.sleep(.5)
        time.sleep(4)   # the level's first frames
        game = process.pid if args.direct else next(iter(children_of(process.pid)), process.pid)
        x11 = X11(args.display)
        window, geometry = x11.owned_window(game)
        result['window'] = geometry
        if window is None:
            raise RuntimeError('the game window did not appear')

        def shot(name):
            # The game writes the next frame it shows (test hook; screen grabs of the private display
            # do not see software-OpenGL windows).
            path = lab / f'{name}.ppm'
            (lab / 'capture-request').write_text(str(path))
            limit = time.monotonic() + 30
            while time.monotonic() < limit and not path.is_file():
                time.sleep(.1)
            time.sleep(.2)
            image = np.asarray(Image.open(path).convert('RGB'), float)
            Image.fromarray(image.astype(np.uint8)).save(lab / f'{name}.png')
            result['shots'][name] = {'path': str(lab / f'{name}.png'), 'mean': round(float(image.mean()), 1)}
            return image

        def press(key, seconds):
            x11.press(window, key, seconds, True)
            time.sleep(.6)

        # EDuke32's default keys (W walks, the arrows turn, the number keys pick weapons; F fires here).
        start = shot('start')
        press('w', 1.5)
        walked = shot('walked')
        press('Right', .7)
        turned = shot('turned')
        press('f', .4)
        time.sleep(.8)
        fired = shot('fired')
        press('3', .1)
        time.sleep(1.5)
        switched = shot('switched')
        press('Escape', .1)
        menu = shot('menu')
        press('Escape', .1)
        back = shot('back')
        diff = lambda a, b: round(float(np.abs(a - b).mean()), 2)
        checks = result['checks']
        result['differences'] = {'walk': diff(start, walked), 'turn': diff(walked, turned), 'fire': diff(turned, fired),
                                 'switch': diff(fired, switched), 'menu': diff(back, menu)}
        checks['pictures'] = all(v['mean'] > 8 for v in result['shots'].values())
        checks['walking moves the view'] = diff(start, walked) > 3
        checks['turning moves the view'] = diff(walked, turned) > 3
        checks['menu opens and closes'] = diff(back, menu) > 3
        H, W = turned.shape[:2]
        ammo = lambda image: image[int(H*0.86):, int(W*0.78):]   # the status bar's ammo counter
        changed = lambda a, b: float((np.abs(a - b).sum(-1) > 60).mean())
        result['differences']['ammo counter'] = round(changed(ammo(turned), ammo(fired)), 4)
        checks['firing uses ammo'] = changed(ammo(turned), ammo(fired)) > 0.005
        checks['game running'] = process.poll() is None
        checks['no OpenXR session'] = 'OpenXR' not in text()
        result['pack'] = [line.split('|', 1)[-1].strip() for line in text().splitlines() if 'VR model pack' in line]
        result['passed'] = all(checks.values())
    except Exception as error:
        result['error'] = str(error)
    finally:
        if process.poll() is None:
            for pid in children_of(process.pid):
                try:
                    os.kill(pid, 15)
                except OSError:
                    pass
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
