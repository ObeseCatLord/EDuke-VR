#!/usr/bin/env python3
"""Read-back checks of the skinned voxel Duke (build_duke_skinned.py) against the v7 contract.

python3 -I validate_duke.py        (validate.py calls check_all() and merges the result into validation.json)

vr_duke_ik: one MD3 v15 surface, frames [bind, rest], shader = png beside it; .skel = v7's skeleton; "skin 2" with
one row per MD3 vertex (<= 16384), 1..4 influences, valid bones, weights >= 0 summing to 1; skinning the
skeleton's bind pose reproduces the `bind` frame; headverts / fphide / handverts index lists in range (fphide
contains headverts; handverts empty when pack.json sets ik_hands); the engine's eye estimate from the hidden
head is in its accepted range; the bind frame is one closed shell with positive volume.
vr_duke / vr_duke_body: v7's frame names and order, tag names and values; one surface with the IK body's vertex
count; every frame one closed shell (welded by position) with positive volume.
"""
import json, os, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('EDUKE32_VOXEL_PACK', HERE.parent))
ASSETS = Path(os.environ.get('EDUKE32_VR_ASSETS', ROOT.parent))
sys.path.insert(0, str(HERE))
from md3np import read  # noqa: E402
from voxmesh import signed_volume, weld_check  # noqa: E402

MAX_VERTS = 16384


def read_skel(path):
    rows = Path(path).read_text().split('\n')
    n = int(rows[0].split()[2])
    names, par, vals = [], [], []
    for r in rows[1:1 + n]:
        f = r.split()
        names.append(f[0])
        par.append(int(f[1]))
        vals.append([float(x) for x in f[2:9]])
    return names, par, np.array(vals)


def quat_R(q):
    x, y, z, w = q / np.linalg.norm(q)
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def closed(P, tris):
    wc = weld_check(P, tris)
    return wc, wc['odd_edges'] == 0 and wc['unbalanced_directed'] == 0 and wc['components'] == 1


def self_intersections(P, tris, cell=None, which=False):
    """Pairs of triangles that cross each other (an edge of one passes through the other), not counting
    triangles that share a vertex position. P in any unit; spatial hash on triangle bounds."""
    key = np.round(P * 4096).astype(np.int64)
    _, w = np.unique(key, axis=0, return_inverse=True)
    w = w.reshape(-1)
    T = w[tris]
    keep = (T[:, 0] != T[:, 1]) & (T[:, 1] != T[:, 2]) & (T[:, 0] != T[:, 2])
    T, tris = T[keep], tris[keep]
    A, B, C = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
    lo, hi = np.minimum(np.minimum(A, B), C), np.maximum(np.maximum(A, B), C)
    if cell is None:
        cell = float(np.median(np.max(hi - lo, 1))) * 2 + 1e-9
    cells = {}
    for i in range(len(T)):
        a, b = np.floor(lo[i] / cell).astype(int), np.floor(hi[i] / cell).astype(int)
        for x in range(a[0], b[0] + 1):
            for y in range(a[1], b[1] + 1):
                for z in range(a[2], b[2] + 1):
                    cells.setdefault((x, y, z), []).append(i)
    pairs = set()
    for ids in cells.values():
        if len(ids) > 1:
            ids = np.array(ids)
            I, J = np.meshgrid(ids, ids, indexing='ij')
            m = I < J
            pairs.update(zip(I[m].tolist(), J[m].tolist()))
    if not pairs:
        return 0
    pr = np.array(sorted(pairs))
    i, j = pr[:, 0], pr[:, 1]
    share = (T[i][:, :, None] == T[j][:, None, :]).any((1, 2))
    i, j = i[~share], j[~share]
    ov = (lo[i] <= hi[j]).all(1) & (lo[j] <= hi[i]).all(1)
    i, j = i[ov], j[ov]

    def seg_hits(s0, s1, a, b, c):
        e1, e2, d = b - a, c - a, s1 - s0
        h = np.cross(d, e2)
        det = np.einsum('ij,ij->i', e1, h)
        ok = np.abs(det) > 1e-12
        f = np.where(ok, 1.0 / np.where(ok, det, 1), 0)
        s = s0 - a
        u = f * np.einsum('ij,ij->i', s, h)
        q = np.cross(s, e1)
        v = f * np.einsum('ij,ij->i', d, q)
        tt = f * np.einsum('ij,ij->i', e2, q)
        eps = 1e-6
        return ok & (u > eps) & (v > eps) & (u + v < 1 - eps) & (tt > eps) & (tt < 1 - eps)
    hit = np.zeros(len(i), bool)
    for (x, y, z), (o, p) in (((A, B, C), (i, j)), ((A, B, C), (j, i))):
        for k0, k1 in ((0, 1), (1, 2), (2, 0)):
            s0, s1 = P[tris[o, k0]], P[tris[o, k1]]
            hit |= seg_hits(s0, s1, A[p], B[p], C[p])
    if which:
        return np.nonzero(keep)[0][i[hit]], np.nonzero(keep)[0][j[hit]]
    return int(hit.sum())


def check_ik(exp, v7, pack_info):
    res = dict(file='exports/eduke32/vr_duke_ik.md3', errors=[], warnings=[])
    E = res['errors']
    stem = exp / 'vr_duke_ik'
    m = read(stem.with_suffix('.md3'))
    if m['version'] != 15 or m['num_surfaces'] != 1:
        E.append('not a one-surface MD3 v15')
        return res, None
    s = m['surfaces'][0]
    nv = int(s['num_verts'])
    if [f['name'] for f in m['frames']] != ['bind', 'rest']:
        E.append('frames are not [bind, rest]')
    if s['shaders'] != ['vr_duke_ik.png'] or not stem.with_suffix('.png').is_file():
        E.append('png missing or shader name')
    names, par, sv = read_skel(stem.with_suffix('.skel'))
    vn, vp, vv = read_skel(v7 / 'vr_duke_ik.skel')
    if names != vn or par != vp or np.abs(sv - vv).max() > 1e-4:
        E.append("skeleton differs from v7's")
    for b in ('pelvis', 'spine', 'chest', 'neck', 'head', 'upperarm_l', 'forearm_l', 'hand_l', 'upperarm_r', 'forearm_r',
              'hand_r', 'thigh_l', 'calf_l', 'foot_l', 'thigh_r', 'calf_r', 'foot_r'):
        if b not in names:
            E.append(f'bone {b} missing')
    rows = stem.with_suffix('.skin').read_text().split('\n')
    head = rows[0].split()
    n = int(head[2]) if len(head) == 3 and head[:2] == ['skin', '2'] else -1
    if n != nv or n > MAX_VERTS:
        E.append(f'skin count {n} vs {nv} vertices (max {MAX_VERTS})')
        return res, None
    # pose the bind skeleton through the skin, as vr.cpp does
    Rb = np.array([quat_R(v[3:]) for v in sv])
    tb = sv[:, :3]
    pos = np.zeros((n, 3))
    bad = 0
    used = set()
    kmax = 0
    for i, r in enumerate(rows[1:1 + n]):
        f = r.split()
        k = int(f[0])
        kmax = max(kmax, k)
        if not 1 <= k <= 4 or len(f) != 1 + 5 * k:
            bad += 1
            continue
        wsum = 0.0
        for j in range(k):
            b, w = int(f[1 + 5 * j]), float(f[2 + 5 * j])
            if not 0 <= b < len(names) or w < 0:
                bad += 1
                break
            used.add(b)
            loc = np.array([float(x) for x in f[3 + 5 * j:6 + 5 * j]])
            pos[i] += w * (tb[b] + Rb[b] @ loc)
            wsum += w
        if abs(wsum - 1) > 2e-3:
            bad += 1
    if bad:
        E.append(f'{bad} bad skin rows')
    err = float(np.abs(pos - s['xyz'][0]).max())
    if err > 0.05:
        E.append(f'skinned bind pose differs from the bind frame by {err:.3f} units')
    lists = {}
    for ext in ('headverts', 'fphide', 'handverts_l', 'handverts_r'):
        p = stem.with_suffix('.' + ext)
        if not p.is_file():
            E.append(f'{ext} missing')
            continue
        ids = np.array([int(x) for x in p.read_text().split()], int)
        if len(ids) and (ids.min() < 0 or ids.max() >= nv):
            E.append(f'{ext} index out of range')
        lists[ext] = ids
    if 'headverts' in lists and 'fphide' in lists and not set(lists['headverts']) <= set(lists['fphide']):
        E.append('fphide does not contain headverts')
    if pack_info.get('ik_hands') and any(len(lists.get(e, [])) for e in ('handverts_l', 'handverts_r')):
        E.append('ik_hands pack with non-empty handverts')
    # vr.cpp's eye estimate from the hidden head (fphide is what build_vr_def passes as the head list)
    hid = lists.get('fphide', np.zeros(0, int))
    if len(hid):
        hp = tb[names.index('head')]
        fwd = pos[hid, 0].max() - 0.02 * 64 - hp[0]
        up = pos[hid, 2].max() - 0.115 * 64 - hp[2]
        res['eye_m'] = dict(forward=round(float(fwd) / 64, 4), up=round(float(up) / 64, 4))
        if not (0 < fwd < 0.2 * 64 and -0.05 * 64 < up < 0.25 * 64):
            E.append(f'eye estimate out of the engine range: {res["eye_m"]}')
    tris = s['tris'].astype(np.int64)
    P = s['xyz'][0] * 64
    wc, ok = closed(P, tris)
    vol = signed_volume(P, tris)
    if not ok or vol <= 0:
        E.append(f'bind frame not one closed positive shell: {wc}, volume {vol:.1f}')
    res['bind_self_intersecting_pairs'] = si = self_intersections(P, tris)
    if si:
        E.append(f'{si} self-intersecting triangle pairs in the bind frame')
    res.update(verts=nv, tris=int(len(tris)), max_influences=kmax, bones_used=len(used),
               bind_skin_error_units=round(err, 4), weld_bind=wc, signed_volume_m3=round(vol / 64.0 ** 6, 4),
               **{f'{k}_count': int(len(v)) for k, v in lists.items()})
    return res, nv


def check_frames(exp, v7, stem, nv):
    res = dict(file=f'exports/eduke32/{stem}.md3', errors=[], warnings=[])
    E = res['errors']
    m = read(exp / f'{stem}.md3')
    ref = read(v7 / f'{stem}.md3')
    fn = [f['name'] for f in m['frames']]
    if fn != [f['name'] for f in ref['frames']]:
        E.append("frames differ from v7's")
    if list(m['tags'][0]) != list(ref['tags'][0]):
        E.append("tag names differ from v7's")
    else:
        d = max(float(np.abs(np.array(a[t]['origin']) - np.array(b[t]['origin'])).max()) + float(
            np.abs(np.array(a[t]['axis']) - np.array(b[t]['axis'])).max()) for a, b in zip(m['tags'], ref['tags']) for t in a)
        res['tag_max_diff_vs_v7'] = round(d, 5)
        if d > 1e-3:
            E.append(f"tags differ from v7's by {d}")
    if m['num_surfaces'] != 1:
        E.append('not one surface')
        return res
    s = m['surfaces'][0]
    if nv is not None and s['num_verts'] != nv:
        E.append(f"{s['num_verts']} vertices vs the IK body's {nv}")
    if s['shaders'] != [f'{stem}.png'] or not (exp / f'{stem}.png').is_file():
        E.append('png missing or shader name')
    tris = s['tris'].astype(np.int64)
    bad = []
    for fi, name in enumerate(fn):
        P = s['xyz'][fi] * 64
        wc, ok = closed(P, tris)
        vol = signed_volume(P, tris)
        if not ok or vol <= 0:
            bad.append(f'{name}: {wc} volume {vol:.1f}')
    if bad:
        E.append('frames not one closed positive shell: ' + '; '.join(bad[:4]))
    res.update(frames=len(fn), verts=int(s['num_verts']), tris=int(len(tris)), closed_frames=len(fn) - len(bad))
    return res


def check_all(root=ROOT, assets=ASSETS):
    exp = Path(root) / 'exports' / 'eduke32'
    v7 = Path(assets) / 'v7-original' / 'exports' / 'eduke32'
    if not (exp / 'vr_duke_ik.md3').is_file():
        return {}
    pj = Path(root) / 'pack.json'
    info = json.loads(pj.read_text()) if pj.is_file() else {}
    out = {}
    out['vr_duke_ik'], nv = check_ik(exp, v7, info)
    for stem in ('vr_duke', 'vr_duke_body'):
        out[f'{stem} (v7 contract)'] = check_frames(exp, v7, stem, nv)
    for k, r in out.items():
        print(k, {x: r[x] for x in ('verts', 'tris', 'max_influences', 'eye_m', 'closed_frames') if x in r},
              'ERR' if r['errors'] else 'ok', r['errors'][:3])
    return out


if __name__ == '__main__':
    print(json.dumps(check_all(), indent=1)[:4000])
