#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Every sky stays fixed in the world while the head turns, looks up and down, and rolls.

For each spot (a sector under a parallax sky: tools/vr/sky_spots.json lists one per sky tile used
by the official maps) the player is put there (xr_goto test hook) in a private software XR lab
with the Bigscreen Beyond's field of view and the sky panels replaced by a bright random block
pattern (EDUKE32_XR_TEST_SKY_PATTERN: same tile sizes and layout), captures are taken at known head orientations, and
sky_rotation_check.py tests that the sky moves exactly with the view rotation, like the world.

  sky_rotation_suite.py --grp DUKE3D.GRP [--extra-dir WORLDTOUR_DIR] --work-dir DIR [--tiles 89,84]

Runs the labs one after another (one software XR lab at a time).
"""
import argparse, json, os, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FOV = '-40.4,40.0,-40.4,40.0'
POSES = {'y0': (0, 0, 0), 'p10': (0, 10, 0), 'a': (0, 25, 0), 'b': (15, 25, 0), 'r': (0, 25, 10),
         'p45': (0, 45, 0), 'p60': (0, 60, 0), 'p75': (0, 75, 0), 'p88': (0, 88, 0),
         'p60y15': (15, 60, 0), 'p60r10': (0, 60, 10)}
PAIRS = [('y0', 'p10'), ('a', 'b'), ('a', 'r'), ('a', 'p45'), ('p45', 'p60'), ('p60', 'p75'), ('p75', 'p88'),
         ('p60', 'p60y15'), ('p60', 'p60r10')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--binary', type=Path, default=ROOT / 'eduke32-xr')
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--spots', type=Path, default=HERE / 'sky_spots.json')
    parser.add_argument('--extra-dir', type=Path, help='World Tour folder (E5 maps and art)')
    parser.add_argument('--tiles', default='', help='only these sky tiles (comma separated)')
    parser.add_argument('--deps', type=Path, default=ROOT / 'work/software-xr/deps')
    parser.add_argument('--keep-passing', action='store_true', help='keep the captures of skies that pass (large)')
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    spots = json.loads(args.spots.read_text())
    if args.tiles:
        wanted = {int(t) for t in args.tiles.split(',')}
        spots = [s for s in spots if s['tile'] in wanted]
    summary = []
    for spot in spots:
        name = f"sky{spot['tile']}-{spot['map'].split('.')[0].lower()}"
        work = args.work_dir / f'{name}-{int(time.time())}'
        script = [{'pose': {'head': [0, 1.6, 0, 0, 0, 0]}}, {'wait': 2},
                  {'console': f"xr_goto {spot['x']} {spot['y']} {spot.get('ang', 0)}"}, {'wait': 3}]
        for pose, (yaw, pitch, roll) in POSES.items():
            script += [{'pose': {'head': [0, 1.6, 0, yaw, pitch, roll]}}, {'wait': 1.5}, {'capture': pose}]
        work.mkdir(parents=True)
        (work / 'scene.json').write_text(json.dumps(script))
        level = spot['map'].upper().removesuffix('.MAP')
        episode, number = level[1:].split('L')
        game_args = '-m'   # monsters off: a death (dead view camera) would spoil the pure head rotations
        if episode == '5':
            if not args.extra_dir:
                summary.append({'spot': spot, 'skipped': 'E5 needs --extra-dir (World Tour folder)'}); continue
            game_args += f' -j {args.extra_dir} -j {args.extra_dir}/maps'
        extra = [f'--args={game_args}']
        lab = [sys.executable, str(HERE / 'software_xr_lab.py'), '--deps', str(args.deps), '--work-dir', str(work / 'lab'),
               '--child-timeout', '600', '--', sys.executable, str(HERE / 'smoke_xr_scene.py'), '--binary', str(args.binary.resolve()),
               '--grp', str(args.grp.resolve()), '--work-dir', str(work / 'lab' / 'out'), '--level', f'{episode},{number}',
               '--script', str(work / 'scene.json'), '--env', f'EDUKE32_XR_TEST_FOV={FOV}', '--env', 'EDUKE32_XR_RESOLUTION=800x800',
               # Bright random blocks in every sky panel (same tile sizes and layout): dark and plain
               # skies become measurable.
               '--env', 'EDUKE32_XR_TEST_SKY_PATTERN=1',
               *extra]
        subprocess.run(lab, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        captures = list((work / 'lab' / 'out').glob('*/y0-left.ppm'))   # the lab writes only inside its own work dir
        if not captures:
            summary.append({'spot': spot, 'error': 'no captures', 'work': str(work)}); print(json.dumps(summary[-1])); continue
        directory = captures[0].parent
        goto = [l for l in (directory / 'game.log').read_text(errors='replace').splitlines() if 'VR goto' in l]
        pairs = []
        for ref, target in PAIRS:
            pairs += ['--pair', f"{ref}={','.join(map(str, POSES[ref]))}:{target}={','.join(map(str, POSES[target]))}"]
        check = subprocess.run([sys.executable, str(HERE / 'sky_rotation_check.py'), str(directory), '--fov', FOV, *pairs],
                               capture_output=True, text=True)
        try:
            result = json.loads(check.stdout)
        except json.JSONDecodeError:
            result = {'passed': False, 'error': check.stderr[-400:]}
        result.update(spot=spot, goto=goto[-1:], captures=str(directory))
        if result.get('passed') and not args.keep_passing:
            shutil.rmtree(work, ignore_errors=True); result['captures'] = None
        summary.append(result)
        print(json.dumps({'tile': spot['tile'], 'map': spot['map'], 'passed': result.get('passed'),
                          'sky_offsets': [p['sky'] and p['sky']['offset_deg'] for p in result.get('pairs', [])]}), flush=True)
    (args.work_dir / 'summary.json').write_text(json.dumps(summary, indent=1))
    measured = [s for s in summary if 'pairs' in s]
    print(f"{sum(s['passed'] for s in measured)}/{len(measured)} skies pass; summary in {args.work_dir / 'summary.json'}")
    return 0 if measured and all(s['passed'] for s in measured) else 1


if __name__ == '__main__':
    raise SystemExit(main())
