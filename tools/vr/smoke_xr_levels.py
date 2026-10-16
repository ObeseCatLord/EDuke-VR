#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Private real XR map transitions, native authority and late stereo receipts.

Use one existing private Monado remote runtime. Does not create a compositor,
focus windows, synthesize packets, or change installed game files.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from PIL import Image, ImageChops
from monado_remote import Remote
from smoke_actions import Observer
from smoke_actions_multiplayer import exercise_server, wait_for_join_barrier
from smoke_multiplayer import CONFIG, X11, stop
from smoke_native_levels import (bound_player, e1l1_floorpic, input_for, inputs,
                                  level_for, wait_level, write_lab)

SYNC = 'Multiplayer client level synchronization complete.'
CAPTURE = re.compile(r'OpenXR PvP frame: submitted=(\d+) captured=1\.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'client-binary', 'grp', 'work-dir'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--remote-port', required=True, type=int)
    parser.add_argument('--port', type=int, default=24730)
    parser.add_argument('--display', default=':1')
    args = parser.parse_args()
    if os.environ.get('EDUKE32_TEST_PRIVATE_WINDOW') != '1':
        parser.error('EDUKE32_TEST_PRIVATE_WINDOW=1 is required')
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='xr-levels-', dir=args.work_dir.resolve()))
    processes, handles = [], []
    result, phase = {'passed': False}, 'setup'
    try:
        labs = {role: write_lab(root, role, args.grp.resolve()) for role in ('server', 'peer1')}
        for lab in labs.values():
            (lab / 'eduke32.cfg').write_text(CONFIG)
            (lab / 'autoexec.cfg').write_text('r_maxfps 30\n')
        base = {k: v for k, v in os.environ.items() if not k.startswith('EDUKE32_XR')}
        base.update(DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy')
        native = {k: v for k, v in base.items() if not k.startswith('XR_')}
        xr_env = dict(base, EDUKE32_XR='1', EDUKE32_XR_SINGLE_PASS='1', EDUKE32_XR_UI='2',
                      EDUKE32_XR_AIM='right', EDUKE32_XR_WEAPON='1', EDUKE32_XR_HAND_SHOTS='1',
                      EDUKE32_XR_TEST_INPUT='1', EDUKE32_XR_TEST_PVP='1',
                      EDUKE32_XR_HUD_OUTPUT=str(labs['peer1'] / 'hud'),
                      EDUKE32_XR_WORLD_OUTPUT=str(labs['peer1'] / 'world'))

        def launch(role, binary, flags, env):
            log = (labs[role] / 'game.log').open('w')
            handles.append(log)
            process = subprocess.Popen([str(binary.resolve()), '-usecwd', '-nosetup', '-noautoload',
                                        '-nologo', '-ns', '-nm', *flags, '-x', 'level_test.con'],
                                       cwd=labs[role], env=env, stdout=log, stderr=subprocess.STDOUT,
                                       stdin=subprocess.PIPE if role == 'server' else subprocess.DEVNULL)
            processes.append(process)
            return process, Observer(process, labs[role] / 'game.log')

        server, so = launch('server', args.binary,
                            ['-dedicated', '-c1', '-m', '-port', str(args.port), '-map', 'first.map'], native)
        so.wait(lambda text: 'Multiplayer server initialized.' in text, timeout=18)
        wait_level(so, 293, 0, 7, 0)
        x11 = X11(args.display)
        with Remote(args.remote_port) as remote:
            remote.neutral()
            client, co = launch('peer1', args.client_binary, ['-connect', f'127.0.0.1:{args.port}'], xr_env)
            phase = 'XR native join'
            index = wait_for_join_barrier(x11, client, labs['peer1'] / 'game.log', so)['server_player']
            if index != 1:
                raise RuntimeError('XR client was not actual native player1')
            co.wait(lambda text: 'OpenXR HUD presentation: 60 frames;' in text, timeout=18)
            stages, images, receipt = [], [], 0

            def command(value):
                nonlocal receipt
                receipt += 1
                token = f'xr-level-receipt-{receipt}'
                offset = len(so.text())
                server.stdin.write(f'{value}\necho {token}\n'.encode())
                server.stdin.flush()
                so.wait(lambda text: token in text[offset:], timeout=15)

            def capture():
                # Receipt is emitted only after actual acquired-frame completion.
                previous = [int(n) for n in CAPTURE.findall(co.text())]
                previous = previous[-1] if previous else 60
                co.wait(lambda text: any(int(n) > previous for n in CAPTURE.findall(text)), timeout=8)
                serial = int(CAPTURE.findall(co.text())[-1])
                paths = [labs['peer1'] / f'hud-{serial}-{eye}.ppm' for eye in ('left', 'right')]
                pixels = [Image.open(path).convert('RGB') for path in paths]
                if any(len(set(image.getdata())) < 2 for image in pixels) or ImageChops.difference(*pixels).getbbox() is None:
                    raise RuntimeError('actual late eye captures are empty/identical')
                saved = []
                for eye, image in zip(('left', 'right'), pixels):
                    path = root / f'stage-{len(stages)}-{eye}.png'
                    image.save(path)
                    saved.append(str(path))
                images.append(pixels[0].copy())
                return {'completed_HUD_frame': serial, 'eyes': saved}

            targets = [('initial', None, 293, 7), ('second-held-fire', 'map second.map', 183, 7),
                       ('builtin', 'changelevel 1 1', e1l1_floorpic(args.grp), 0),
                       ('small-return', 'map first.map', 293, 7)]
            for name, request, marker, level in targets:
                phase = name
                held = name == 'second-held-fire'
                if held:
                    remote.packet.right.trigger_value = 1
                    remote.packet.right.trigger_click = True
                    remote.send()
                    so.wait(lambda text: input_for(text, index)['bits'] & 4, timeout=5)
                else:
                    remote.neutral()
                if request:
                    count = co.text().count(SYNC)
                    server_offset = len(so.text())
                    command(request)
                    load = re.search(r'User Map:|E1L\d+:', so.text()[server_offset:])
                    if load is None:
                        raise RuntimeError('fresh native server map-load receipt missing')
                    server_offset += load.end()
                    co.wait(lambda text: text.count(SYNC) > count, timeout=20)
                for observer in (so, co):
                    wait_level(observer, marker, 0, level, index, timeout=15)
                    observer.wait(lambda text: all(bound_player(level_for(text, player)) for player in (0, index)), timeout=10)
                offset = len(so.text())
                so.pause(.5)
                held_samples = [row for row in inputs(so.text()[server_offset if held else offset:]) if row['player'] == index]
                suppressed = not held or (bool(held_samples) and all(not (row['bits'] & 4) for row in held_samples) and
                                          all(row['ammo'] == 48 for row in held_samples))
                remote.neutral()
                so.wait(lambda text: level_for(text, index)['knuckle'] == 0 and
                                    level_for(text, index)['weaponpos'] == 0, timeout=8)
                controls = exercise_server(so, remote, index)
                co.wait(lambda text: input_for(text, index)['ammo'] == input_for(so.text(), index)['ammo'] and
                                    abs(input_for(text, index)['x'] - input_for(so.text(), index)['x']) < 256 and
                                    abs(input_for(text, index)['y'] - input_for(so.text(), index)['y']) < 256, timeout=8)
                ownership = {role: [level_for(observer.text(), player) for player in (0, index)]
                             for role, observer in (('server', so), ('xr', co))}
                owned = all(all(bound_player(row) for row in rows) and len({row['index'] for row in rows}) == 2
                            for rows in ownership.values())
                stereo = capture()
                stages.append({'name': name, 'held_fire_suppressed': suppressed, 'controls': controls,
                               'ownership': ownership, 'stereo': stereo, 'passed': suppressed and controls['passed'] and owned})
                if not stages[-1]['passed']:
                    raise RuntimeError('native ownership/input check failed')
            visibility = {}
            for role, process in (('server', server), ('xr', client)):
                window, _ = x11.owned_window(process.pid)
                visibility[role] = x11.window_visibility(window) if window else None
            checks = {'all_native_map_controls_and_ownership': all(stage['passed'] for stage in stages),
                      'actual_late_stereo_changes_between_each_map': all(ImageChops.difference(a, b).getbbox() is not None for a, b in zip(images, images[1:])),
                      'core_validation_active': 'Core Validation output type:' in co.text(),
                      'core_validation_clean': not re.search(r'VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)', co.text()),
                      'private_unmapped_without_focus': all(v is None or v['unmapped'] and not v['has_desktop_focus'] for v in visibility.values())}
            result = {'passed': all(checks.values()), 'checks': checks, 'stages': stages, 'private_windows': visibility}
            remote.neutral()
    except Exception as error:
        result = {'passed': False, 'phase': phase, 'error': str(error)}
    finally:
        for process in reversed(processes):
            stop(process)
        for handle in handles:
            handle.close()
    result['evidence_directory'] = str(root)
    (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
