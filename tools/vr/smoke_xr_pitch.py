#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Full-pitch / room-scale XR world capture through a private remote runtime.

Starts E1L1 in single player, drives the simulated HMD through a list of head
orientations/positions and captures both submitted eye images for each one.
Checks that every pose still submits stereo frames (no dropped/empty frames)
and that steep poses use the split front/back Polymost passes.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from monado_remote import Remote, Quat
from smoke_world import CONFIG

# name, yaw, pitch, roll (degrees), head offset (metres, x/y/z)
POSES = [
    ('level', 0, 0, 0, (0, 0, 0)),
    ('down35', 0, -35, 0, (0, 0, 0)),
    ('down60', 0, -60, 0, (0, 0, 0)),
    ('down89', 0, -89, 0, (0, 0, 0)),
    ('down90', 0, -90, 0, (0, 0, 0)),
    ('up60', 0, 60, 0, (0, 0, 0)),
    ('up90', 0, 90, 0, (0, 0, 0)),
    ('down70-yaw40-roll20', 40, -70, 20, (0, 0, 0)),
    ('lean-forward-2m', 0, 0, 0, (0, 0, -2.0)),
    ('tall-1m', 0, 0, 0, (0, 1.0, 0)),
]


def orientation(yaw, pitch=0, roll=0):
    # Y (yaw) * X (pitch, positive looks up) * Z (roll), OpenXR axes.
    def q(axis, angle):
        s = math.sin(math.radians(angle) / 2)
        return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(math.radians(angle) / 2))

    def mul(a, b):
        ax, ay, az, aw = a
        bx, by, bz, bw = b
        return (aw*bx+ax*bw+ay*bz-az*by, aw*by-ax*bz+ay*bw+az*bx,
                aw*bz+ax*by-ay*bx+az*bw, aw*bw-ax*bx-ay*by-az*bz)
    r = mul(mul(q((0, 1, 0), yaw), q((1, 0, 0), pitch)), q((0, 0, 1), roll))
    return Quat(*r)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, default=49777)
    parser.add_argument('--timeout', default=150, type=int)
    parser.add_argument('--level', default='1')
    parser.add_argument('--single-pass', action='store_true')
    parser.add_argument('--aa-root', type=Path, help='Alien Armageddon install; uses its GRP/CON/DEF')
    parser.add_argument('--map', help='user map to load instead of an episode level')
    parser.add_argument('--poses', help='comma-separated subset of pose names')
    parser.add_argument('--play', action='store_true', help='launch through package/vr/eduke32-vr-play')
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    lab = Path(tempfile.mkdtemp(prefix='pitch-', dir=args.work_dir.resolve()))
    (lab / 'eduke32.cfg').write_text(CONFIG)
    (lab / 'DUKE3D.GRP').symlink_to(args.grp.resolve())
    request = lab / 'capture-request'
    env = dict(os.environ, DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy',
               EDUKE32_XR='1', EDUKE32_XR_CAPTURE_REQUEST=str(request), EDUKE32_XR_TEST_PITCH='1')
    if args.single_pass:
        env['EDUKE32_XR_SINGLE_PASS'] = '1'
    for key in list(env):
        if key.startswith('EDUKE32_XR_TEST_') and key != 'EDUKE32_XR_TEST_PITCH':
            env.pop(key)
    log_path = lab / 'game.log'
    command = [str(args.binary.resolve()), '-usecwd', '-nosetup', '-noautoload']
    if args.play:
        env['EDUKE32_XR'] = 'play'
        env['XDG_DATA_HOME'] = str(lab / 'data')
        launcher = Path(__file__).resolve().parents[2] / 'package/vr/eduke32-vr-play'
        command = [str(launcher), '--binary', str(args.binary.resolve())]
        if args.aa_root:
            command += ['--aa', str(args.aa_root.resolve())]
        command += ['--', '-usecwd', '-nosetup', '-noautoload', '-nologo']
    elif args.aa_root:
        aa = args.aa_root.resolve()
        command += ['-nologo', '-j', str(aa), '-g', str(aa / 'AA.grp'), '-x', 'scripts/AAGAME.CON', '-h', 'duke3d.def']
    command += ['-map', args.map] if args.map else ['-v1', '-l' + args.level]
    command += ['-s1']
    poses = [p for p in POSES if not args.poses or p[0] in args.poses.split(',')]
    result = {'passed': False, 'poses': {}, 'evidence_directory': str(lab)}
    deadline = time.monotonic() + args.timeout
    remote = None
    with log_path.open('w') as log:
        process = subprocess.Popen(command, cwd=lab, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT)
        text = lambda: log_path.read_text(errors='replace')
        try:
            while 'OpenXR world oracle: 60 frames' not in text():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('world did not reach 60 frames')
                time.sleep(.2)
            # The remote driver accepts connections once the session is running.
            remote = Remote(args.remote_port).__enter__()
            time.sleep(.5)
            base = remote.packet.head.center.position
            base = (base.x, base.y, base.z)
            for name, yaw, pitch, roll, offset in poses:
                head = remote.packet.head.center
                head.orientation = orientation(yaw, pitch, roll)
                head.position.x, head.position.y, head.position.z = (b + o for b, o in zip(base, offset))
                remote.send()
                time.sleep(1.0)
                before = len(text())
                submitted_before = len(re.findall('OpenXR capture request', text()))
                request.write_text(str(lab / name) + '\n')
                while request.exists():
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('capture request not served: ' + name)
                    time.sleep(.1)
                time.sleep(.5)
                tail = text()[before:]
                match = re.search(r'OpenXR capture request: serial=(\d+) prefix=\S+ passes=(\d),(\d) .* ok=(\d)', tail)
                left, right = lab / (name + '-left.ppm'), lab / (name + '-right.ppm')
                final = f'final presentation prefix={lab / name}.' in tail
                result['poses'][name] = {
                    'captured': (final or (bool(match) and match.group(4) == '1')) and left.is_file() and right.is_file(),
                    'passes': [int(match.group(2)), int(match.group(3))] if match else None,
                    'distinct_eyes': left.is_file() and right.is_file() and left.read_bytes() != right.read_bytes(),
                }
            output = text()
            result['world_stopped'] = 'OpenXR world stopped' in output
            result['rejected_frames_warning'] = 'outside native camera coverage' in output
            poses = result['poses']
            result['checks'] = {
                'all_poses_captured': all(p['captured'] for p in poses.values()),
                # Final-presentation captures (UI overlay) do not report passes.
                'level_unsplit': poses['level']['passes'] in ([1, 1], None) if 'level' in poses else True,
                'steep_poses_split': all(poses[n]['passes'] in ([2, 2], None)
                                         for n in ('down60', 'down89', 'down90', 'up60', 'up90') if n in poses),
                'no_world_stop': not result['world_stopped'],
                'no_rejected_frames': not result['rejected_frames_warning'],
                'game_alive': process.poll() is None,
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
                    process.kill()
                    process.wait()
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
