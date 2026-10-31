#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Co-op name tags and shared keycards: dedicated server, VR player, flat talker.

Run under software_xr_lab.py. The VR player joins first and steps onto a red keycard; the
talker joins afterwards and must hold it too (a late joiner gets the keys already found). The VR
player then steps onto a blue keycard, which the talker must get at once (mp_sharekeys, on by
default). Both players' keys are read on the VR client (keys are synced to clients). The talker's
microphone is a synthetic tone gated on and off; the VR player faces the talker and must build
both of its name tags, "Talker" and "((Talker))" while talking, never one for itself or for the
dedicated server's invisible slot, and captures them for review.
"""
import argparse, json, math, os, re, struct, subprocess, tempfile, time
from pathlib import Path
from monado_remote import Remote
from smoke_actions import Observer
from smoke_aim import orientation
from smoke_multiplayer import X11, setup_lab
from smoke_xr_coop import CON, LEVEL, WHERE, level_map
from stereo_fixture import sprite

ACCESSCARD, RED = 60, 21
ACCESS = re.compile(r'VR where sprite: player=(\d+) .* access=(-?\d+)\.')
TAG = re.compile(r'Name tag: player=(\d+) "([^"]*)"')


RED_AT, BLUE_AT = (900, 5000), (900, 7400)


def card_map():
    """The co-op level fixture with a red and a blue keycard away from the starts."""
    data = bytearray(level_map(True))
    count_at = len(data) - 2 - 44 * (4 + 6)   # sprite count: four starts, six bombs
    count = struct.unpack_from('<h', data, count_at)[0]
    assert count == 10, count
    cards = [sprite(*RED_AT, 0, 0, tile=ACCESSCARD, palette=RED, xrepeat=32, yrepeat=32),
             sprite(*BLUE_AT, 0, 0, tile=ACCESSCARD, palette=0, xrepeat=32, yrepeat=32)]
    return bytes(data[:count_at]) + struct.pack('<h', count + 2) + bytes(data[count_at + 2:]) + b''.join(cards)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, default=49777)
    parser.add_argument('--port', type=int, default=24641)
    parser.add_argument('--timeout', type=int, default=560)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='nametags-', dir=args.work_dir.resolve()))
    labs = {role: setup_lab(root, role, args.grp.resolve(), False) for role in ('server', 'talker', 'xr')}
    for role, lab in labs.items():
        (lab / 'first.map').write_bytes(card_map())
        (lab / 'second.map').write_bytes(level_map(False))
        (lab / 'coop_vr.con').write_text(CON)
        (lab / 'autoexec.cfg').write_text('voice_transmit 1\nvoice_mode 0\n' if role == 'talker' else 'voice_transmit 0\n')
        with (lab / 'eduke32.cfg').open('a') as f:
            f.write('\n[Comm Setup]\nPlayerName = "' + {'server': 'Server', 'talker': 'Talker', 'xr': 'VR'}[role] + '"\n')
    base = {k: v for k, v in os.environ.items() if not k.startswith(('EDUKE32_XR', 'EDUKE32_VOICE'))}
    base.update(DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy')
    native = {k: v for k, v in base.items() if not k.startswith('XR_')}
    talker_env = dict(native, EDUKE32_VOICE_TEST_TONE='440:700:500')
    console, capture = labs['xr'] / 'console-request', labs['xr'] / 'capture-request'
    xr_env = dict(base, EDUKE32_XR='play', EDUKE32_XR_CONSOLE_REQUEST=str(console), EDUKE32_XR_CAPTURE_REQUEST=str(capture),
                  XDG_DATA_HOME=str(labs['xr'] / 'data'))
    launcher = Path(__file__).resolve().parents[2] / 'package/vr/eduke32-vr-play'
    common = ['-usecwd', '-nosetup', '-noautoload', '-nologo', '-ns', '-x', 'coop_vr.con']
    processes, logs = [], []
    deadline = time.monotonic() + args.timeout
    result = {'passed': False, 'evidence_directory': str(root), 'phase': 'setup'}
    checks = result['checks'] = {}

    def launch(role, command, env):
        log = (labs[role] / 'game.log').open('w'); logs.append(log)
        process = subprocess.Popen(command, cwd=labs[role], env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        processes.append(process)
        return process, Observer(process, labs[role] / 'game.log')

    def until(observer, predicate, seconds):
        observer.wait(predicate, timeout=max(1, min(seconds, deadline - time.monotonic())))

    def soft(observer, predicate, seconds):
        try:
            until(observer, predicate, seconds)
            return True
        except RuntimeError:
            return False

    try:
        binary = str(args.binary.resolve())
        server, so = launch('server', [binary, *common, '-nm', '-dedicated', '-port', str(args.port), '-c2', '-v1', '-l1'], native)
        until(so, lambda t: 'Multiplayer server initialized.' in t, 30)
        until(so, lambda t: LEVEL.search(t) is not None, 30)
        so.pause(3)
        x11 = X11(args.display)
        with Remote(args.remote_port) as remote:
            head = remote.packet.head
            result['phase'] = 'XR join'
            xr, co = launch('xr', [str(launcher), '--no-voxel-build', '--pack', 'original-lowres', '--binary', binary, '--',
                                   *common, '-connect', f'127.0.0.1:{args.port}'], xr_env)
            until(co, lambda t: 'Multiplayer client level synchronization complete.' in t, 120)
            until(co, lambda t: 'OpenXR world oracle: 60 frames' in t, 240)
            co.pause(2)

            def keys():
                start = len(co.text())
                console.write_text('xr_where\n')
                until(co, lambda t: len(ACCESS.findall(t[start:])) >= 2 and len(WHERE.findall(t[start:])) >= 2, 60)
                text = co.text()[start:]
                return ({int(m[0]): list(map(int, m)) for m in WHERE.findall(text)},
                        {int(p): int(a) for p, a in ACCESS.findall(text)})

            result['phase'] = 'red key'
            console.write_text(f'xr_goto {RED_AT[0]} {RED_AT[1]} 512\n')
            co.pause(4)
            rows, access = keys()
            me = next(r for r in rows.values() if r[1])
            checks['vr_picked_red_key'] = bool(access.get(me[0], 0) & 2)

            result['phase'] = 'talker join'
            talker, to = launch('talker', [binary, *common, '-nm', '-connect', f'127.0.0.1:{args.port}'], talker_env)
            until(to, lambda t: 'Multiplayer client level synchronization complete.' in t, 60)
            to.pause(3)
            window, _ = x11.owned_window(talker.pid)
            if window:
                x11.press(window, 'Escape', .06, True)
            to.pause(2)
            rows, access = keys()
            talker_row = next(r for i, r in rows.items() if i not in (0, me[0]))
            checks['late_joiner_has_red_key'] = bool(access.get(talker_row[0], 0) & 2)

            result['phase'] = 'blue key'
            console.write_text(f'xr_goto {BLUE_AT[0]} {BLUE_AT[1]} 512\n')
            co.pause(4)
            rows, access = keys()
            result['access'] = access
            result['players'] = {'vr': me[0], 'talker': talker_row[0]}
            checks['vr_picked_blue_key'] = bool(access.get(me[0], 0) & 1)
            checks['talker_got_shared_blue_key'] = bool(access.get(talker_row[0], 0) & 1)

            result['phase'] = 'name tags'
            # Close enough (2 m) to read the tag in the lab's small eye images.
            console.write_text(f'xr_goto {talker_row[7]} {talker_row[8] + 768} 1536\n')
            co.pause(2)
            rows, _ = keys()
            me = rows[me[0]]; talker_row = rows[talker_row[0]]
            facing = math.degrees(math.remainder(math.atan2(talker_row[8] - me[8], talker_row[7] - me[7]) - me[5] * math.pi / 1024, 2 * math.pi))
            head.center.orientation = orientation(facing, 0); remote.send()
            plain, talking = 'Talker', '((Talker))'
            checks['plain_tag_built'] = soft(co, lambda t: any(int(p) == talker_row[0] and l == plain for p, l in TAG.findall(t)), 60)
            checks['talking_tag_built'] = soft(co, lambda t: any(int(p) == talker_row[0] and l == talking for p, l in TAG.findall(t)), 60)
            tags = TAG.findall(co.text())
            checks['no_tag_for_self_or_server'] = not any(int(p) in (0, me[0]) for p, _ in tags)
            result['tags'] = sorted(set(tags))
            for n in range(3):
                capture.write_text(str(labs['xr'] / f'tag{n}') + '\n')
                soft(co, lambda _: not capture.exists(), 30)
                co.pause(.4)
        checks['all_alive'] = all(p.poll() is None for p in processes)
        result['phase'] = 'complete'
        result['passed'] = all(checks.values())
    except RuntimeError as error:
        result['error'] = str(error)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
        for log in logs:
            log.close()
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
