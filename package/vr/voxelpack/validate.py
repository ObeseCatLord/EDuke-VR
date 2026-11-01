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



# vr_duke / vr_duke_body are stored with +Y to the right (build_duke_skinned.py) and the engine draws
# these sprite models mirrored back, keeping their triangle order: they are outward-facing as drawn,
# so their volume is measured as drawn (in file coordinates it is negative by design).
ENGINE_MIRRORED = ('vr_duke', 'vr_duke_body')


def engine_mirror(stem):
    return np.array([1.0, -1.0, 1.0]) if Path(stem).name in ENGINE_MIRRORED else np.ones(3)

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
        if s['shaders'] != [f'{Path(stem).name}.png']:
            E.append(f"shader {s['shaders']}")
        nv += s['num_verts']; nt += s['num_tris']
        if s['num_verts'] > 4096 or s['num_tris'] > 8192:
            W.append(f"surface {s['name']}: {s['num_verts']} verts / {s['num_tris']} tris exceed the Quake 3 MD3 spec "
                     f"limits (EDuke32 loads it: uint16 indices)")
        # the frame where this surface is fully shown = the frame with the largest extent
        ext = [np.ptp(s['xyz'][fi], 0).max() for fi in range(len(fn))]
        fi = int(np.argmax(ext))
        P = s['xyz'][fi] * 64
        vol = signed_volume(P * engine_mirror(stem), s['tris'].astype(np.int64))
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


def check_hand(md3):
    """A skinned hand shell as vr.cpp loads it: one surface, frame `bind`, shader = png beside it, a .skin with
    one valid entry per vertex (<= 16384, joints < 26, weight 0..1), closed and outward when welded."""
    m = read(md3)
    res = dict(file=str(md3.relative_to(ROOT)), bytes=m['size'], errors=[], warnings=[])
    E = res['errors']
    if m['version'] != 15 or m['num_surfaces'] != 1:
        E.append('not a one-surface MD3 v15')
        return res
    s = m['surfaces'][0]
    if [f['name'] for f in m['frames']] != ['bind']:
        E.append('frames are not [bind]')
    if s['shaders'] != [f'{md3.stem}.png'] or not md3.with_suffix('.png').is_file():
        E.append('png missing or shader name')
    skin = md3.with_suffix('.skin')
    if not skin.is_file():
        E.append('skin missing')
        return res
    rows = skin.read_text().split('\n')
    head = rows[0].split()
    n = int(head[2]) if len(head) == 3 and head[:2] == ['skin', '1'] else -1
    if n != s['num_verts'] or n > 16384:
        E.append(f'skin count {n} vs {s["num_verts"]} vertices (max 16384)')
    else:
        v = np.array([[float(x) for x in r.split()] for r in rows[1:1 + n]])
        if v.shape != (n, 9) or (v[:, [0, 5]] < 0).any() or (v[:, [0, 5]] >= 26).any() or (v[:, 1] < 0).any() or (v[:, 1] > 1).any():
            E.append('bad skin rows')
    P = s['xyz'][0] * 64
    vol = signed_volume(P, s['tris'].astype(np.int64))
    wc = weld_check(P, s['tris'].astype(np.int64))
    if wc['odd_edges'] or wc['unbalanced_directed'] or wc['components'] != 1:
        E.append(f'not one closed shell: {wc}')
    if vol <= 0:
        E.append('non-positive signed volume')
    res.update(verts=int(s['num_verts']), tris=int(s['num_tris']), weld=wc, signed_volume_units3=round(vol, 1))
    return res


def main():
    stems = ['vr_pistol', 'vr_shotgun', 'vr_chaingun', 'vr_rpg', 'vr_pipebomb', 'vr_shrinker', 'vr_devastator',
             'vr_tripbomb', 'vr_freezer', 'vr_expander', 'vr_boot', 'vr_duke', 'vr_duke_body', 'vr_detonator', 'vr_flamethrower']
    out = {}
    for st in stems:
        if (EXP / f'{st}.md3').is_file():
            out[st] = check(st)
            r = out[st]
            print(st, 'frames', r['frames'], 'surf', r['surfaces'], 'verts', r['verts'], 'tris', r['tris'],
                  'ratio', r['size_ratio_vs_v6'], 'ERR' if r['errors'] else 'ok', r['errors'][:2], len(r['warnings']), 'warnings')
    # Alien Armageddon held models (build_aa.py): v6's AA contract
    for md3 in sorted((EXP / 'aa').glob('*.md3')):
        st = f'aa/{md3.stem}'
        if not (V6 / 'exports/eduke32' / f'{st}.md3').is_file():
            out[st] = dict(file=f'exports/eduke32/{st}.md3', errors=['no v6 counterpart'], warnings=[])
            continue
        out[st] = r = check(st)
        if r['errors']:
            print(st, 'ERR', r['errors'][:3])
    print('aa models', sum(1 for k in out if k.startswith('aa/')), 'errors', sum(1 for k in out if k.startswith('aa/') and out[k]['errors']))
    # skinned hand shells (build_hands.py): the generic hands and every character's
    shells = sorted((EXP / 'hands').glob('vr_hand_*_shell*.md3')) + sorted((EXP / 'characters').glob('*/hands/vr_hand_*_shell.md3'))
    for md3 in shells:
        key = md3.relative_to(EXP).with_suffix('').as_posix()
        out[key] = r = check_hand(md3)
        print(key, 'verts', r.get('verts'), 'ERR' if r['errors'] else 'ok', r['errors'][:3])
    chars = ROOT / 'metadata/characters.json'
    if chars.is_file():
        info = json.loads(chars.read_text())
        bad = [f'{n}: {k} {e}' for n, c in info.items() for k, f in c.get('files', {}).items() for e, rel in f.items()
               if not (ROOT / rel).is_file()]
        out['characters.json'] = dict(file='metadata/characters.json', characters=sorted(info),
                                      pchar={n: c.get('pchar') for n, c in info.items()}, errors=bad, warnings=[])
    import validate_duke                          # the skinned voxel Duke against v7's IK contract
    out.update(validate_duke.check_all(ROOT))
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
