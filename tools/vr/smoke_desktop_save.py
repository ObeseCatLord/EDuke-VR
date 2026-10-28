#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Desktop (flat) view of a saved game: load it and capture the screen.

Starts the desktop game (eduke32-vr-play --desktop) on the save's level, loads the save through
the console request hook (xr_load, the save's folder added with -j) and writes a picture of the
next frames, e.g. to compare a mirror or voxel view with the headset.

Run inside tools/vr/software_xr_lab.py.
"""
import argparse, json, os, subprocess, tempfile, time
from pathlib import Path
from smoke_world import CONFIG
from smoke_desktop import children_of

LAUNCHER = Path(__file__).resolve().parents[2] / 'package/vr/eduke32-vr-play'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--save', required=True, type=Path)
    parser.add_argument('--level', default='1,2')
    parser.add_argument('--pack', default='voxel')
    parser.add_argument('--display', default=':105')
    parser.add_argument('--env', action='append', default=[], help='extra KEY=VALUE for the game')
    parser.add_argument('--console', default='', help='console commands after loading (";" separated)')
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    lab = Path(tempfile.mkdtemp(prefix='desktop-save-', dir=args.work_dir.resolve()))
    (lab / 'eduke32.cfg').write_text(CONFIG)
    (lab / 'DUKE3D.GRP').symlink_to(args.grp.resolve())
    env = {k: v for k, v in os.environ.items() if not k.startswith('EDUKE32_XR')}
    env.update(DISPLAY=args.display, SDL_AUDIODRIVER='dummy', XDG_DATA_HOME=str(lab / 'data'), XDG_CONFIG_HOME=str(lab / 'config'),
               EDUKE32_TEST_FLAT_CAPTURE=str(lab / 'capture-request'), EDUKE32_XR_CONSOLE_REQUEST=str(lab / 'console-request'))
    env.update(kv.split('=', 1) for kv in args.env)
    episode, level = args.level.split(',')
    command = [str(LAUNCHER), '--desktop', '--no-voxel-build', '--pack', args.pack, '--binary', str(args.binary.resolve()), '--',
               '-usecwd', '-nosetup', '-noautoload', '-nologo', '-j', str(args.save.resolve().parent), f'-v{episode}', f'-l{level}', '-s2']
    log = lab / 'game.log'
    result = {'passed': False, 'lab': str(lab)}
    with log.open('w') as out:
        process = subprocess.Popen(command, cwd=lab, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
    text = lambda: log.read_text(errors='replace')
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and f'E{episode}L{level}' not in text().upper():
            time.sleep(.5)
        time.sleep(4)
        (lab / 'console-request').write_text(f'r_precache 0\nxr_load {args.save.name}\n')
        time.sleep(12)
        if args.console:
            (lab / 'console-request').write_text(args.console.replace(';', '\n') + '\n')
            time.sleep(3)
        shots = []
        for name in ('save', 'save-later'):
            path = lab / f'{name}.ppm'
            (lab / 'capture-request').write_text(str(path))
            limit = time.monotonic() + 30
            while time.monotonic() < limit and not path.is_file():
                time.sleep(.2)
            shots.append(str(path))
            time.sleep(2)
        result['captures'] = shots
        result['passed'] = all(Path(s).is_file() for s in shots)
    finally:
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
