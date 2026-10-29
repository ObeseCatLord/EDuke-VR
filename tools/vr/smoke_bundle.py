#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run one script of a personal bundle (make_personal_bundle.py) and wait for its game to reach a point.

    smoke_bundle.py --bundle DIR --work-dir DIR --expect REGEX [--expect REGEX ...] -- SCRIPT [ARGS...]

The game runs with a throwaway HOME/XDG folders inside the work dir (the user's own settings are
never touched) and the lab's display/OpenXR runtime. Passes when every --expect pattern appears
in its output before --timeout; then captures one flat frame when possible and stops the game.
Run inside tools/vr/software_xr_lab.py (--share-net for the internet server).
"""
import argparse, json, os, re, signal, subprocess, tempfile, time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--expect', action='append', default=[])
    parser.add_argument('--timeout', type=int, default=240)
    parser.add_argument('--display', default=':105')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    args.work_dir.mkdir(parents=True, exist_ok=True)
    home = Path(tempfile.mkdtemp(prefix='bundle-home-', dir=args.work_dir.resolve()))
    env = {k: v for k, v in os.environ.items() if not k.startswith('EDUKE32')}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'), XDG_DATA_HOME=str(home / '.local/share'),
               DISPLAY=args.display, SDL_AUDIODRIVER='dummy', EDUKE32_TEST_FLAT_CAPTURE=str(home / 'capture-request'))
    log = home / 'game.log'
    result = {'passed': False, 'command': command, 'home': str(home)}
    with log.open('w') as out:
        process = subprocess.Popen([str(args.bundle / command[0]), *command[1:]], cwd=home, env=env, stdin=subprocess.DEVNULL,
                                   stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        deadline = time.monotonic() + args.timeout
        found = {}
        while time.monotonic() < deadline and process.poll() is None and len(found) < len(args.expect):
            text = log.read_text(errors='replace')
            for pattern in args.expect:
                if pattern not in found and re.search(pattern, text):
                    found[pattern] = True
            time.sleep(.5)
        result['found'] = sorted(found)
        result['missing'] = [p for p in args.expect if p not in found]
        result['alive'] = process.poll() is None
        if result['alive'] and not result['missing']:
            time.sleep(3)
            path = home / 'frame.ppm'
            (home / 'capture-request').write_text(str(path))
            limit = time.monotonic() + 30
            while time.monotonic() < limit and not path.is_file():
                time.sleep(.3)
            result['capture'] = str(path) if path.is_file() else None
        result['passed'] = result['alive'] and not result['missing']
        result['tail'] = log.read_text(errors='replace').splitlines()[-6:]
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
    print(json.dumps(result, indent=1))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
