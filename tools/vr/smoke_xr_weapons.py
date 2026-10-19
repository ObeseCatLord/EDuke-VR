#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Held weapon models for every stock weapon (play preset, private software XR).

Launches E1L1 through package/vr/eduke32-vr-play, gives all weapons through
the console request hook, selects each weapon with its native gamefunc,
waits for the generic held-model path to draw it, captures both final eyes and
fires once to check that the native weapon spends ammo/advances.
"""
import argparse, json, os, re, subprocess, tempfile, time
from pathlib import Path
from monado_remote import Remote
from smoke_world import CONFIG

# (native key gamefunc, expected curr_weapon, label). Keys 7 and 10 toggle.
STEPS = [(3, 2, 'shotgun'), (4, 3, 'chaingun'), (5, 4, 'rpg'), (6, 5, 'pipebomb'),
         (7, 6, 'shrinker'), (7, 11, 'expander'), (8, 7, 'devastator'), (9, 8, 'tripbomb'),
         (10, 9, 'freezer'), (10, 12, 'flamethrower'), (2, 1, 'pistol')]
HELD = re.compile(r'OpenXR held model: weapon=(\d+) family=(\d+) model=(-?\d+) frame=(\d+) counter=(\d+)\.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, default=49777)
    parser.add_argument('--timeout', default=550, type=int)
    parser.add_argument('--assets', type=Path, help='duke-vr-assets directory for the launcher')
    parser.add_argument('--aa-root', type=Path, help='Alien Armageddon install (launcher --aa)')
    parser.add_argument('--map', help='user map instead of E1L1 (e.g. maps/httkb/high_rise.map)')
    parser.add_argument('--switches', type=int, default=16)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    lab = Path(tempfile.mkdtemp(prefix='weapons-', dir=args.work_dir.resolve()))
    (lab / 'eduke32.cfg').write_text(CONFIG)
    (lab / 'DUKE3D.GRP').symlink_to(args.grp.resolve())
    capture, console = lab / 'capture-request', lab / 'console-request'
    env = dict(os.environ, DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy',
               EDUKE32_XR='play', EDUKE32_XR_TEST_HELD='1', EDUKE32_XR_TEST_HAPTICS='1', EDUKE32_XR_TEST_INPUT='1',
               EDUKE32_XR_CAPTURE_REQUEST=str(capture), EDUKE32_XR_CONSOLE_REQUEST=str(console),
               XDG_DATA_HOME=str(lab / 'data'))
    launcher = Path(__file__).resolve().parents[2] / 'package/vr/eduke32-vr-play'
    command = [str(launcher), '--binary', str(args.binary.resolve())]
    if args.assets:
        command += ['--assets', str(args.assets.resolve())]
    if args.aa_root:
        command += ['--aa', str(args.aa_root.resolve())]
    command += ['--', '-usecwd', '-nosetup', '-noautoload', '-nologo']
    command += ['-map', args.map] if args.map else ['-v1', '-l1']
    command += ['-s1']
    log_path = lab / 'game.log'
    text = lambda: log_path.read_text(errors='replace')
    deadline = time.monotonic() + args.timeout
    result = {'passed': False, 'weapons': {}, 'evidence_directory': str(lab)}
    remote = None

    def wait(predicate, what, seconds=60):
        limit = min(deadline, time.monotonic() + seconds)
        while not predicate():
            if process.poll() is not None:
                raise RuntimeError('game exited while waiting for ' + what)
            if time.monotonic() > limit:
                return False
            time.sleep(.1)
        return True

    def run(*lines):
        console.write_text('\n'.join(lines) + '\n')
        wait(lambda: not console.exists(), 'console request')

    with log_path.open('w') as log:
        process = subprocess.Popen(command, cwd=lab, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        try:
            if not wait(lambda: 'OpenXR world oracle: 60 frames' in text(), 'world', 300):
                raise RuntimeError('world did not start')
            remote = Remote(args.remote_port).__enter__()
            time.sleep(.5)
            # god/give weapons share one deferred cheat slot: one per frame.
            time.sleep(8)  # let level-start inventory setup finish first
            run('xr_weapons'); time.sleep(2)
            run('give ammo'); time.sleep(1)
            run('god'); time.sleep(2)
            names = {1: 'pistol', 2: 'shotgun', 3: 'chaingun', 4: 'rpg', 5: 'pipebomb', 6: 'shrinker',
                     7: 'devastator', 8: 'tripbomb', 9: 'freezer', 10: 'detonator', 11: 'expander', 12: 'flamethrower'}
            last = None
            for press in range(args.switches):
                start = len(text())
                # Native Next_Weapon (left controller Y) cycles owned weapons.
                remote.packet.left.b_click = True; remote.send()
                wait(lambda: any(m[0] != last for m in HELD.findall(text()[start:])), 'switch', 25)
                remote.packet.left.b_click = False; remote.send()
                time.sleep(1.0)
                rows = HELD.findall(text()[start:])
                if not rows:
                    continue
                weapon = int(rows[-1][0]); last = rows[-1][0]
                label = names.get(weapon, f'weapon{weapon}') + ('' if int(rows[-1][1]) != 5 else f'-mapped{rows[-1][2]}')
                if label in result['weapons']:
                    if len(result['weapons']) >= 10:
                        break
                    continue
                capture.write_text(str(lab / label) + '\n')
                wait(lambda: not capture.exists(), 'capture', 60)
                time.sleep(.3)
                fire_start = len(text())
                remote.packet.right.trigger_value = 1.0; remote.packet.right.trigger_click = True; remote.send()
                fired = wait(lambda: 'OpenXR haptic' in text()[fire_start:], 'fire', 20)
                remote.packet.right.trigger_value = 0.0; remote.packet.right.trigger_click = False; remote.send()
                frames = sorted({int(m[3]) for m in HELD.findall(text()[fire_start:]) if int(m[0]) == weapon})
                time.sleep(1.0)
                result['weapons'][label] = {
                    'weapon': weapon, 'family': int(rows[-1][1]), 'model': int(rows[-1][2]),
                    'fire_frames_seen': frames, 'captured': (lab / (label + '-left.ppm')).is_file(),
                    'fire_feedback': fired,
                }
            output = text()
            result['world_stopped'] = 'OpenXR world stopped' in output
            result['receipt_drops'] = output.count('receipt mismatch; frame dropped')
            weapons = result['weapons']
            result['checks'] = {
                'at_least_ten_weapons_drawn': len(weapons) >= 10,
                'all_captured': all(w['captured'] for w in weapons.values()),
                'world_alive': not result['world_stopped'] and process.poll() is None,
            }
            result['passed'] = all(result['checks'].values())
        finally:
            if remote:
                remote.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
