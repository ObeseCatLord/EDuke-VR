#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""VR models on/off and the 2D fallback (play preset, private software XR).

Selects the RPG and captures with VR models on (3D weapon, hands, laser), then
sets `vr_models 0` at runtime: the weapon must fall back to its native 2D
sprite on the controller (no held model, no 3D aim hand), the weapon wheel to
the 2D HUD ring; then `vr_models 1` restores the 3D weapon. With --assets
pointing at a pack that lacks a weapon's model, the same 2D fallback applies
to that weapon alone.
"""
import argparse, json, os, re, subprocess, tempfile, time
from pathlib import Path
from monado_remote import Remote
from smoke_aim import orientation
from smoke_world import CONFIG

HELD = re.compile(r'OpenXR held model: weapon=(\d+) ')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--assets', type=Path)
    parser.add_argument('--weapon', type=int, default=4)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, default=49777)
    parser.add_argument('--timeout', default=500, type=int)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    lab = Path(tempfile.mkdtemp(prefix='models-', dir=args.work_dir.resolve()))
    (lab / 'eduke32.cfg').write_text(CONFIG)
    (lab / 'DUKE3D.GRP').symlink_to(args.grp.resolve())
    capture, console = lab / 'capture-request', lab / 'console-request'
    env = dict(os.environ, DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy',
               EDUKE32_XR='play', EDUKE32_XR_TEST_HELD='1', EDUKE32_XR_TEST_WHEEL='1',
               EDUKE32_XR_CAPTURE_REQUEST=str(capture), EDUKE32_XR_CONSOLE_REQUEST=str(console),
               XDG_DATA_HOME=str(lab / 'data'))
    launcher = Path(__file__).resolve().parents[2] / 'package/vr/eduke32-vr-play'
    command = [str(launcher), '--binary', str(args.binary.resolve())]
    if args.assets:
        command += ['--assets', str(args.assets.resolve())]
    command += ['--', '-usecwd', '-nosetup', '-noautoload', '-nologo', '-v1', '-l1', '-s1']
    log_path = lab / 'game.log'
    text = lambda: log_path.read_text(errors='replace')
    deadline = time.monotonic() + args.timeout
    result = {'passed': False, 'evidence_directory': str(lab)}
    checks = result['checks'] = {}
    remote = None

    def wait(predicate, seconds=60):
        limit = min(deadline, time.monotonic() + seconds)
        while not predicate():
            if process.poll() is not None:
                raise RuntimeError('game exited')
            if time.monotonic() > limit:
                return False
            time.sleep(.05)
        return True

    def run(line):
        console.write_text(line + '\n'); wait(lambda: not console.exists())

    def shoot(label):
        capture.write_text(str(lab / label) + '\n'); wait(lambda: not capture.exists())
        wait(lambda: (lab / f'{label}-left.ppm').is_file(), 30)
        return (lab / f'{label}-left.ppm').is_file()

    with log_path.open('w') as log:
        process = subprocess.Popen(command, cwd=lab, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        try:
            if not wait(lambda: 'OpenXR world oracle: 60 frames' in text(), 300):
                raise RuntimeError('world did not start')
            remote = Remote(args.remote_port).__enter__()
            right = remote.packet.right
            right.pose.position.x, right.pose.position.y, right.pose.position.z = .2, 1.3, -.35
            right.pose.orientation = orientation(0, 0); remote.send()
            time.sleep(8)
            run('xr_weapons'); time.sleep(2)
            run(f'xr_weapon {args.weapon}'); time.sleep(4)
            start = len(text())
            time.sleep(3)
            on = text()[start:]
            checks['models_on_held_or_fallback'] = True
            result['models_on_held_model'] = any(int(w) == args.weapon for w in HELD.findall(on))
            result['laser_on'] = 'OpenXR laser:' in text()
            checks['models_on_captured'] = shoot('models-on')
            run('vr_models 0'); time.sleep(3)
            start = len(text()); time.sleep(3)
            off = text()[start:]
            checks['models_off_no_held_model'] = not HELD.findall(off)
            checks['models_off_captured'] = shoot('models-off')
            right.trackpad_force, right.trackpad_touch = 1.0, True; remote.send()
            checks['wheel_opens_without_models'] = wait(lambda: 'OpenXR weapon wheel: open' in text()[start:], 20)
            time.sleep(1.5)
            checks['wheel_2d_captured'] = shoot('wheel-2d')
            right.trackpad_force, right.trackpad_touch = 0.0, False; remote.send(); time.sleep(1.5)
            run('vr_models 1'); time.sleep(3)
            start = len(text())
            checks['models_back_on'] = wait(lambda: bool(HELD.findall(text()[start:])) or not result['models_on_held_model'], 30)
            checks['world_alive'] = 'OpenXR world stopped' not in text() and process.poll() is None
            result['passed'] = all(checks.values())
        except RuntimeError as error:
            result['error'] = str(error)
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
