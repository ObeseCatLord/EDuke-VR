#!/usr/bin/env python3
"""Re-solve the per-weapon hold poses against the voxel weapons (v6 poses.py approach, 26-joint skeleton).

python3 -I scripts/solve_holds.py [names=...]

Writes metadata/hand_poses_flat.json = v6-original/metadata/hand_poses_flat.json with hold_<weapon> replaced
(both sides) for every weapon built here (detonator / flamethrower holds and the free poses stay v6), and
metadata/hold_stats.json (solver info per side).
"""
import json, sys, os
from pathlib import Path
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('EDUKE32_VOXEL_PACK', HERE.parent))   # the pack folder being built
sys.path.insert(0, str(HERE))
import poses as P  # noqa: E402
import numpy as np  # noqa: E402

_weapon_tris = P.weapon_tris


def cropped_weapon_tris(md3_path, radius=0.20):
    """Weapon triangles near the grip only (the hand never reaches further): the voxel weapons have up to
    7k triangles and the v6 contact tests are O(tris)."""
    tris, tags = _weapon_tris(md3_path)
    palm = tags['tag_palm_right']
    near = np.linalg.norm(tris - palm, axis=2).min(1) < radius
    return tris[near], tags


P.weapon_tris = cropped_weapon_tris

V6META = Path(os.environ.get('EDUKE32_VR_ASSETS', ROOT.parent)) / 'v6-original' / 'metadata'
NAMES = ['pistol', 'shotgun', 'chaingun', 'rpg', 'freezer', 'shrinker', 'expander', 'devastator', 'tripbomb', 'pipebomb']


def job(name):
    meta = json.loads((ROOT / 'metadata' / 'assets' / f'{name}.json').read_text())
    meta['voxel'] = True
    md3 = ROOT / 'exports' / 'eduke32' / f'{meta["stem"]}.md3'
    return name, P.hold_records(md3, meta)


def main():
    args = dict(a.split('=', 1) for a in sys.argv[1:])
    names = NAMES if args.get('names', 'all') == 'all' else args['names'].split(',')
    flat_path = ROOT / 'metadata' / 'hand_poses_flat.json'
    src = flat_path if flat_path.exists() else V6META / 'hand_poses_flat.json'
    flat = json.loads(src.read_text())
    stats_path = ROOT / 'metadata' / 'hold_stats.json'
    stats = json.loads(stats_path.read_text()) if stats_path.exists() else {}
    from multiprocessing import Pool
    with Pool(min(6, len(names))) as pool:
        for name, rec in pool.map(job, names):
            for side in ('left', 'right'):
                flat['poses'][side][f'hold_{name}'] = dict(frame=f'weapon:{name}', joints=rec[side]['joints'])
            stats[name] = {side: dict(solver=rec[side]['solver'], weapon_to_palm=rec[side]['weapon_to_palm'],
                                      angles_deg=rec[side]['angles']) for side in ('left', 'right')}
            print('hold', name, {s: rec[s]['solver'] for s in ('right', 'left')}, flush=True)
    flat_path.write_text(json.dumps(flat, indent=1))
    stats_path.write_text(json.dumps(stats, indent=1))


if __name__ == '__main__':
    main()
