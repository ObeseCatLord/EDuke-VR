#!/usr/bin/env python3
"""Read back every export and compare with its v6-original counterpart -> metadata/validation.json.

python3 -I scripts/validate.py

Checks per MD3: IDP3 v15, frame names/order == v6, tag names/order == v6, surface count (weapons/boot: 1),
shader == png next to it, vertex/triangle counts (flagged above the Quake 3 MD3 spec 4096/8192; EDuke32 itself
has no such cap), positive signed volume per surface (shown frames), watertight when welded by position,
rest-frame bounds vs v6, tags inside/near the geometry. Also checks hand_poses_flat.json structure.
"""
import json, sys, os
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('EDUKE32_VOXEL_PACK', HERE.parent))   # the pack folder being built
sys.path.insert(0, str(HERE))
from md3np import read  # noqa: E402
from voxmesh import signed_volume, weld_check  # noqa: E402

V6 = Path(os.environ.get('EDUKE32_VR_ASSETS', ROOT.parent)) / 'v6-original'
EXP = ROOT / 'exports/eduke32'


def check(stem):
    m = read(EXP / f'{stem}.md3')
    v = read(V6 / 'exports/eduke32' / f'{stem}.md3')
    res = dict(file=f'exports/eduke32/{stem}.md3', bytes=m['size'], errors=[], warnings=[])
    E, W = res['errors'], res['warnings']
    if m['version'] != 15:
        E.append('version')
    fn = [f['name'] for f in m['frames']]
    vfn = [f['name'] for f in v['frames']]
    if fn != vfn:
        E.append(f'frames differ: {fn} vs {vfn}')
    tn = list(m['tags'][0].keys())
    vtn = list(v['tags'][0].keys())
    if tn != vtn:
        E.append(f'tags differ: {tn} vs {vtn}')
    res.update(frames=len(fn), tags=tn, surfaces=m['num_surfaces'], v6_surfaces=v['num_surfaces'])
    if stem not in ('vr_duke', 'vr_duke_body') and m['num_surfaces'] != 1:
        E.append('more than one surface')
    png = EXP / f'{stem}.png'
    if not png.is_file():
        E.append('png missing')
    vol_ok = True
    nv = nt = 0
    wt = []
    for s in m['surfaces']:
        if s['shaders'] != [f'{stem}.png']:
            E.append(f"shader {s['shaders']}")
        nv += s['num_verts']; nt += s['num_tris']
        if s['num_verts'] > 4096 or s['num_tris'] > 8192:
            W.append(f"surface {s['name']}: {s['num_verts']} verts / {s['num_tris']} tris exceed the Quake 3 MD3 spec "
                     f"limits (EDuke32 loads it: uint16 indices)")
        # the frame where this surface is fully shown = the frame with the largest extent
        ext = [np.ptp(s['xyz'][fi], 0).max() for fi in range(len(fn))]
        fi = int(np.argmax(ext))
        P = s['xyz'][fi] * 64
        vol = signed_volume(P, s['tris'].astype(np.int64))
        if vol <= 0:
            vol_ok = False
        wc = weld_check(P, s['tris'].astype(np.int64))
        wt.append(dict(surface=s['name'], verts=s['num_verts'], tris=s['num_tris'], frame=fn[fi],
                       signed_volume_units3=round(vol, 1), **wc))
        if wc['odd_edges'] or wc['unbalanced_directed']:
            E.append(f"{s['name']} not watertight")
    if not vol_ok:
        E.append('non-positive signed volume')
    res.update(verts=nv, tris=nt, shells=wt)
    lo = np.min([s['xyz'][0].min(0) for s in m['surfaces'] if np.ptp(s['xyz'][0], 0).max() > 0.01], 0)
    hi = np.max([s['xyz'][0].max(0) for s in m['surfaces'] if np.ptp(s['xyz'][0], 0).max() > 0.01], 0)
    vlo = np.min([s['xyz'][0].min(0) for s in v['surfaces']], 0)
    vhi = np.max([s['xyz'][0].max(0) for s in v['surfaces']], 0)
    res['rest_bounds_m'] = [(lo / 64).round(4).tolist(), (hi / 64).round(4).tolist()]
    res['v6_rest_bounds_m'] = [(vlo / 64).round(4).tolist(), (vhi / 64).round(4).tolist()]
    res['size_ratio_vs_v6'] = ((hi - lo) / np.maximum(vhi - vlo, 1e-6)).round(3).tolist()
    # tags: distance of each tag (frame 0) to the nearest vertex of the shown geometry
    allp = np.concatenate([s['xyz'][0] for s in m['surfaces']])
    td = {}
    for t, val in m['tags'][0].items():
        o = np.array(val['origin']) / 64.0
        td[t] = dict(pos_m=(o).round(4).tolist(), nearest_vertex_m=round(float(np.linalg.norm(allp / 64 - o, axis=1).min()), 4))
    res['tags_frame0'] = td
    return res


def main():
    stems = ['vr_pistol', 'vr_shotgun', 'vr_chaingun', 'vr_rpg', 'vr_pipebomb', 'vr_shrinker', 'vr_devastator',
             'vr_tripbomb', 'vr_freezer', 'vr_expander', 'vr_boot', 'vr_duke', 'vr_duke_body']
    out = {}
    for st in stems:
        if (EXP / f'{st}.md3').is_file():
            out[st] = check(st)
            r = out[st]
            print(st, 'frames', r['frames'], 'surf', r['surfaces'], 'verts', r['verts'], 'tris', r['tris'],
                  'ratio', r['size_ratio_vs_v6'], 'ERR' if r['errors'] else 'ok', r['errors'][:2], len(r['warnings']), 'warnings')
    # hand poses
    flat = json.loads((ROOT / 'metadata/hand_poses_flat.json').read_text())
    v6f = json.loads((V6 / 'metadata/hand_poses_flat.json').read_text())
    hp = dict(same_keys=sorted(flat) == sorted(v6f), same_joint_order=flat['joint_order'] == v6f['joint_order'],
              same_segments=flat['segments'] == v6f['segments'],
              same_pose_names={s: sorted(flat['poses'][s]) == sorted(v6f['poses'][s]) for s in ('left', 'right')},
              joints_ok=all(len(p['joints']) == 26 and all(len(j) == 7 for j in p['joints'])
                            for s in ('left', 'right') for p in flat['poses'][s].values()),
              replaced=[n for n in flat['poses']['right'] if flat['poses']['right'][n] != v6f['poses']['right'].get(n)])
    out['hand_poses_flat'] = hp
    print('hand_poses_flat', hp)
    (ROOT / 'metadata/validation.json').write_text(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
