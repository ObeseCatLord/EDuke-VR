#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Multiplayer client sprite lists stay well formed over a real network.

A desktop client (eduke32-vr-play --desktop) joins a running server (for latency and loss, a
remote one: --server HOST:PORT) and plays for a while: it walks, turns and fires so projectiles,
sparks and debris keep being spawned and deleted on the server. The client checks its sector and
status sprite lists after every applied snapshot (EDUKE32_TEST_SPRITE_LISTS) and logs any broken
link. A broken list can close into a loop, and every walk of it then hangs the game.

Passes when the client stays connected and responsive and no list error was logged.
Run inside tools/vr/software_xr_lab.py --share-net.
"""
import argparse, json, os, re, subprocess, tempfile, time
from pathlib import Path
from smoke_world import CONFIG
from smoke_multiplayer import X11
from smoke_desktop import children_of

LAUNCHER = Path(__file__).resolve().parents[2] / 'package/vr/eduke32-vr-play'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--server', required=True, help='HOST:PORT of a running server')
    parser.add_argument('--display', default=':105')
    parser.add_argument('--seconds', type=int, default=180, help='how long to play')
    parser.add_argument('--break-at', type=int, default=0,
                        help='test the repair: close a sector list into a loop at this snapshot; it must be rebuilt')
    parser.add_argument('--weapons', default='', help='weapon number keys to cycle while playing (give them on the server first)')
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    lab = Path(tempfile.mkdtemp(prefix='mp-sprite-lists-', dir=args.work_dir.resolve()))
    # Synthetic key events cannot carry the Ctrl modifier the default Fire key needs: fire on F.
    (lab / 'eduke32.cfg').write_text(CONFIG + '\n[Comm Setup]\nPlayerName = "Lists"\n')
    (lab / 'settings.cfg').write_text('bind "F" "gamefunc_Fire"\n')
    (lab / 'DUKE3D.GRP').symlink_to(args.grp.resolve())
    env = {k: v for k, v in os.environ.items() if not k.startswith('EDUKE32_XR')}
    env.update(DISPLAY=args.display, SDL_AUDIODRIVER='dummy', XDG_DATA_HOME=str(lab / 'data'),
               XDG_CONFIG_HOME=str(lab / 'config'), EDUKE32_TEST_SPRITE_LISTS='1')
    if args.break_at:
        env['EDUKE32_TEST_BREAK_SPRITE_LIST'] = str(args.break_at)
    command = [str(LAUNCHER), '--desktop', '--no-voxel-build', '--pack', 'original-lowres', '--binary', str(args.binary.resolve()),
               '--', '-usecwd', '-nosetup', '-noautoload', '-nologo', '-connect', args.server]
    result = {'passed': False, 'lab': str(lab), 'server': args.server, 'checks': {}}
    log = lab / 'game.log'
    with log.open('w') as out:
        process = subprocess.Popen(command, cwd=lab, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
    text = lambda: log.read_text(errors='replace')
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and process.poll() is None and 'level synchronization complete' not in text():
            time.sleep(.5)
        if 'level synchronization complete' not in text():
            raise RuntimeError('the client did not join the server')
        time.sleep(3)
        x11 = X11(args.display)
        window, _ = x11.owned_window(next(iter(children_of(process.pid)), process.pid))
        if window is None:
            raise RuntimeError('the game window did not appear')
        # Play: fire bursts while walking and turning, so the server spawns and deletes sprites.
        keys = ['f', 'w', 'f', 'Right', 'f', 's', 'f', 'Left', 'f', 'space']
        for weapon in args.weapons:
            keys += [weapon, 'f', 'f', 'Right', 'f']
        end, step, stalls = time.monotonic() + args.seconds, 0, 0
        last_size = log.stat().st_size
        while time.monotonic() < end and process.poll() is None:
            key = keys[step % len(keys)]
            x11.press(window, key, .6 if key in ('w', 's', 'Right', 'Left') else .3, True)
            step += 1
            time.sleep(.4)
            if step % 25 == 0:
                # Every snapshot check logs a summary each 600 snapshots; a silent log for long means a hang.
                size = log.stat().st_size
                stalls = stalls + 1 if size == last_size else 0
                last_size = size
                if stalls >= 6:
                    break
        lines = text()
        errors = re.findall(r'Sprite lists: [^\n]*rebuilt them[^\n]*', lines)
        summaries = re.findall(r'Sprite lists: (\d+) snapshots checked, (\d+) errors', lines)
        result['list_errors'] = errors[:20]
        result['summaries'] = summaries[-3:]
        result['keys_sent'] = step
        checks = result['checks']
        checks['snapshots checked'] = bool(summaries)
        if args.break_at:
            # Exactly the induced loop is found and repaired, and play goes on afterwards.
            checks['test loop made'] = 'test loop in sector' in lines
            checks['loop repaired once'] = len(errors) == 1 and 'sector' in errors[0]
            checks['checked after the repair'] = any(int(n) > args.break_at for n, _ in summaries)
        else:
            checks['no list errors'] = not errors and all(e == '0' for _, e in summaries)
        checks['game running'] = process.poll() is None
        checks['still connected'] = 'disconnected' not in lines.lower().split('level synchronization complete', 1)[-1]
        checks['log kept moving'] = stalls < 6
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
