#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Alien Armageddon held weapon models through AA's real start flow.

Launches AA 5.66 through package/vr/eduke32-vr-play --aa (play preset), drives
AA's own character selection with a private Monado remote controller (the
same driver as smoke_alien_armageddon.py), gives the arsenal through the
console request hook, cycles weapons with the native Next_Weapon gamefunc and
captures every held weapon that reaches the HUD-mapped model path. The
installed AA directory is read-only; only an observer CON is added with -mx.
"""
import argparse, json, os, re, subprocess, tempfile, time
from pathlib import Path
from monado_remote import Remote
from smoke_actions import Observer
from smoke_alien_armageddon import aa_samples, aa_wrapper, drive_character_selection
from smoke_multiplayer import CONFIG

HELD = re.compile(r'OpenXR held model: weapon=(\d+) family=(\d+) model=(-?\d+) frame=(\d+) counter=(\d+)\.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--aa-root', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, default=49777)
    parser.add_argument('--timeout', default=580, type=int)
    parser.add_argument('--switches', type=int, default=24)
    parser.add_argument('--pack', default='original', help='model pack (launcher --pack)')
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    lab = Path(tempfile.mkdtemp(prefix='aa-weapons-', dir=args.work_dir.resolve()))
    (lab / 'eduke32.cfg').write_text(CONFIG + '\n[Screen Setup]\nPolymer = 0\n')
    (lab / 'settings.cfg').write_text('// Private test preferences.\n')
    (lab / 'aa_controller_observer.con').write_text(aa_wrapper(include_game=False))
    capture, console = lab / 'capture-request', lab / 'console-request'
    env = {k: v for k, v in os.environ.items() if not k.startswith('EDUKE32_XR')}
    # The selector driver steers AA's cursor with the right stick; the play
    # preset otherwise leaves pitch to tracking (pointing also moves it).
    env.update(DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy',
               EDUKE32_XR='play', EDUKE32_XR_STICK_PITCH='1', EDUKE32_XR_PHYSICAL_THROW='0',
               EDUKE32_XR_TEST_HELD='1', EDUKE32_XR_TEST_HAPTICS='1', EDUKE32_XR_TEST_INPUT='1',
               EDUKE32_XR_TEST_SHOTS='1', EDUKE32_XR_TEST_PVP='1',
               EDUKE32_XR_CAPTURE_REQUEST=str(capture), EDUKE32_XR_CONSOLE_REQUEST=str(console),
               XDG_DATA_HOME=str(lab / 'data'))
    launcher = Path(__file__).resolve().parents[2] / 'package/vr/eduke32-vr-play'
    command = [str(launcher), '--binary', str(args.binary.resolve()), '--aa', str(args.aa_root.resolve()), '--pack', args.pack, '--',
               '-usecwd', '-nosetup', '-noautoload', '-nologo', '-ns', '-nm',
               '-mx', 'aa_controller_observer.con', '-v1', '-l2', '-s1']
    log_path = lab / 'game.log'
    deadline = time.monotonic() + args.timeout
    result = {'passed': False, 'weapons': {}, 'evidence_directory': str(lab)}

    with log_path.open('w') as log:
        process = subprocess.Popen(command, cwd=lab, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        observer = Observer(process, log_path)

        def wait(predicate, seconds):
            try:
                observer.wait(lambda text: predicate(text), timeout=max(1, min(seconds, deadline - time.monotonic())))
                return True
            except RuntimeError as error:
                if 'observation timeout' in str(error):
                    return False
                raise

        def run(*lines):
            console.write_text('\n'.join(lines) + '\n')
            wait(lambda _: not console.exists(), 60)

        try:
            with Remote(args.remote_port) as remote:
                # Arrive at AA's character selection; advance AA's opening
                # screens the way a player would, with the controller A button
                # (native menu advance).
                next_press, presses = 0, 0
                while True:
                    text = observer.text()
                    rows = aa_samples(text)
                    if rows and rows[-1]['startmode'] < 0:
                        break
                    now = time.monotonic()
                    if now > deadline:
                        raise RuntimeError('AA character selection not reached')
                    if 'Per-map .art file' in text and now >= next_press:
                        remote.packet.right.a_click = True; remote.send(); time.sleep(.3)
                        remote.packet.right.a_click = False; remote.send()
                        presses += 1; next_press = now + 3
                    time.sleep(.1)
                result['intro_controller_presses'] = presses
                result['selection'] = drive_character_selection(observer, remote)['stages']['gameplay']
                observer.pause(6)
                run('xr_weapons'); observer.pause(2)
                run('god'); observer.pause(2)
                last, seen = None, set()
                for press in range(args.switches):
                    if time.monotonic() > deadline - 30:
                        break
                    start = len(observer.text())
                    remote.packet.left.b_click = True; remote.send()
                    wait(lambda text: any(m[0] != last for m in HELD.findall(text[start:])), 25)
                    remote.packet.left.b_click = False; remote.send()
                    observer.pause(1.0)
                    rows = HELD.findall(observer.text()[start:])
                    if not rows:
                        continue
                    weapon, family, model = map(int, rows[-1][:3]); last = rows[-1][0]
                    label = f'w{weapon}-f{family}-m{model}'
                    if label in seen:
                        if len(seen) >= 12:
                            break
                        continue
                    seen.add(label)
                    capture.write_text(str(lab / label) + '\n')
                    wait(lambda _: not capture.exists(), 60)
                    observer.pause(.3)
                    fire_start = len(observer.text())
                    remote.packet.right.trigger_value = 1.0; remote.packet.right.trigger_click = True; remote.send()
                    fired = wait(lambda text: 'OpenXR haptic' in text[fire_start:], 20)
                    remote.packet.right.trigger_value = 0.0; remote.packet.right.trigger_click = False; remote.send()
                    frames = sorted({int(m[3]) for m in HELD.findall(observer.text()[fire_start:]) if int(m[0]) == weapon})
                    observer.pause(1.0)
                    result['weapons'][label] = {'weapon': weapon, 'family': family, 'model': model,
                                                'fire_frames_seen': frames, 'fire_feedback': fired,
                                                'captured': (lab / (label + '-left.ppm')).is_file()}
            text = observer.text()
            weapons = result['weapons']
            result['checks'] = {
                'mapped_weapons_drawn': sum(1 for w in weapons.values() if w['family'] == 5) >= 4,
                'all_captured': bool(weapons) and all(w['captured'] for w in weapons.values()),
                'some_fire_feedback': any(w['fire_feedback'] for w in weapons.values()),
                'world_alive': 'OpenXR world stopped' not in text and process.poll() is None,
            }
            result['passed'] = all(result['checks'].values())
        except RuntimeError as error:
            result['error'] = str(error)
        finally:
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
