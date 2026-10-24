#!/usr/bin/env python3
"""Build the held weapons of the voxel pack from the Voxel Duke Nukem 3D pickup KVX files.

python3 -I scripts/build_weapons.py [names=pistol,shotgun|all]

Writes exports/eduke32/vr_<name>.md3/.png/_glow.png and metadata/assets/<name>.json.
Contract (same as ../v6-original): MD3 v15, ONE surface (shader = png name), 64 units/m, +X muzzle,
+Y right, +Z up, positive signed volume, v6 frame names and tag names/order; tags have identity basis and are
the same in every frame. The voxel geometry is static; a blocky muzzle-flash shell is shown in the frames
where the v6 model shows its flash and collapsed to a point inside the barrel otherwise; thrown/placed
frames collapse the whole model to the palm point (as v6 does).
"""
import json, os, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('EDUKE32_VOXEL_PACK', HERE.parent))   # the pack folder being built
sys.path.insert(0, str(HERE))
from kvx import read_kvx  # noqa: E402
from voxmesh import mesh_parts, signed_volume, weld_check, save_png  # noqa: E402
from md3io import write_md3, MD3_SPEC_MAX_VERTS, MD3_SPEC_MAX_TRIS  # noqa: E402
from md3read import read_md3  # noqa: E402
from weapon_specs import SPECS, FLASH, COLLAPSED, FLASH_COLOURS  # noqa: E402

V6 = Path(os.environ.get('EDUKE32_VR_ASSETS', ROOT.parent)) / 'v6-original'
SRC = ROOT / 'source' / 'voxels' / 'weapons'
OUT = ROOT / 'exports' / 'eduke32'
META = ROOT / 'metadata' / 'assets'
AX = {'x': 0, 'y': 1, 'z': 2}
MIRROR = np.diag([1.0, -1.0, 1.0])     # true-handed (fwd, left, up) -> MD3 (fwd, right, up)


def axis_vec(s):
    v = np.zeros(3)
    v[AX[s[1]]] = 1.0 if s[0] == '+' else -1.0
    return v


def box_mask(shape, box):
    m = np.zeros(shape, bool)
    sl = []
    for a in 'xyz':
        lo, hi = box.get(a, (0, shape[AX[a]] - 1))
        sl.append(slice(lo, hi + 1))
    m[tuple(sl)] = True
    return m


def exposed_faces(solid, region):
    """Centres (grid coords) and outward normals (grid axes) of exposed faces of region voxels."""
    P = np.pad(solid, 1)
    out_c, out_n = [], []
    for a in range(3):
        for s in (1, -1):
            nb = np.roll(P, -s, axis=a)[1:-1, 1:-1, 1:-1]
            f = solid & ~nb & region
            idx = np.argwhere(f).astype(float) + 0.5
            idx[:, a] += 0.5 * s
            n = np.zeros((len(idx), 3)); n[:, a] = s
            out_c.append(idx); out_n.append(n)
    return np.concatenate(out_c), np.concatenate(out_n)


def v6_info(name, path=None):
    m = read_md3(path or V6 / 'exports/eduke32' / f'vr_{name}.md3')
    f0 = m['frames'][0]
    tags = {k: np.array(v['origin']) / 64.0 for k, v in m['tags'][0].items()}
    return dict(frames=[f['name'] for f in m['frames']], tags=tags, tag_order=list(m['tags'][0].keys()),
                mins=np.array(f0['mins']) / 64.0, maxs=np.array(f0['maxs']) / 64.0)


def glow_mask(rgb, solid, kind, grid):
    if kind is None:
        return None
    r, g, b = (rgb[..., i].astype(int) for i in range(3))
    if kind == 'fullbright':
        m = grid >= 240
    elif kind == 'green':
        m = (g > 120) & (g > r * 1.25) & (g > b * 1.6)
    elif kind == 'orange':
        m = (r > 170) & (r > g * 1.15) & (b < 110) & (r - b > 110)
    elif kind == 'red':
        m = (r > 140) & (g < 70) & (b < 70)
    else:
        raise ValueError(kind)
    return m & solid


def flash_part(muzzle, bore, colours, s_unit):
    """Blocky muzzle-flash shell: a 3-D cross of voxels whose back face sits on the muzzle plane."""
    n = 7
    g = np.zeros((n, n, n), bool)
    c = n // 2
    g[0:5, c - 1:c + 2, c - 1:c + 2] = True          # core, pointing forward
    g[1:3, :, c - 1:c + 2] = True                     # side spikes
    g[1:3, c - 1:c + 2, :] = True                     # up/down spikes
    g[5:7, c, c] = True                               # tip
    g[1:3, 1:6, 1:6] |= np.ones((2, 5, 5), bool) & (np.add.outer(np.abs(np.arange(5) - 2), np.abs(np.arange(5) - 2)) <= 2)
    rgb = np.zeros(g.shape + (3,), np.uint8)
    core, outer = colours
    d = np.sqrt(((np.indices(g.shape).transpose(1, 2, 3, 0) - np.array([1.5, c, c])) ** 2).sum(-1))
    rgb[:] = outer
    rgb[d < 2.2] = core
    cell = float(np.clip(bore * 0.3, 0.004, 0.009))     # metres per flash voxel (core ~ bore wide, capped)
    A = np.zeros((3, 4))
    A[0, 0] = A[1, 1] = A[2, 2] = cell * 64
    A[:, 3] = np.array([muzzle[0], muzzle[1] - (c + 0.5) * cell, muzzle[2] - (c + 0.5) * cell]) * 64
    return dict(solid=g, rgb=rgb, glow=g.copy(), A=A)


def build(name, spec=None, k=None, flashes=None, collapsed=None, flash_colours=None, extra=None, source=None,
          v6_path=None, stem=None, sub='', meta_name=None, body_motion=None, scale_m=None):
    """Mesh one weapon. The defaults build the stock voxel weapon `name`; the expansion and AA builders pass
    their own `spec`, voxel grid `k` (a read_kvx-like dict, e.g. a kitbash), flash frames, `extra` shells
    (a callable receiving the placement and returning [dict(part, show=[frames], hide=xyz m, affine={frame:
    (3x3, t m)})]) and a `source` record."""
    spec = spec or SPECS[name]
    v6 = v6_info(name, v6_path)
    k = k or read_kvx(SRC / f"{spec['kvx']}.kvx")
    solid, grid = k['solid'], k['grid']
    rgb = k['palette'][np.clip(grid, 0, 255)]
    # fill colour of hidden interior cells with the nearest stored colour (never shown; keeps patches clean)
    Rt = np.stack([axis_vec(spec['fwd']), axis_vec(spec['left']), axis_vec(spec['up'])])
    assert abs(np.linalg.det(Rt) - 1) < 1e-9, (name, 'mapping must be a proper rotation')
    L = MIRROR @ Rt                                  # grid vector -> MD3 direction (unscaled)
    # scale: voxel extent along the reference MD3 axis = v6 extent
    sa = spec.get('scale_axis', 0)
    pts = np.argwhere(solid).astype(float)
    corners = np.concatenate([pts, pts + 1])
    ext_vox = np.ptp(corners @ L.T, axis=0)
    ext_v6 = v6['maxs'] - v6['mins']
    s = ext_v6[sa] / ext_vox[sa] if scale_m is None else scale_m / ext_vox[sa]   # metres per voxel
    M = L * s                                        # grid coords -> metres (before translation)

    def to_md3(p):
        return np.asarray(p, float) @ M.T

    gmask = box_mask(solid.shape, spec['grip']) & solid
    assert gmask.any(), name
    fc, fn = exposed_faces(solid, gmask)
    fc_m, fn_m = to_md3(fc), fn @ L.T
    gcent = to_md3(np.argwhere(gmask) + 0.5)
    if spec.get('handlebar'):
        top = fn_m[:, 2] > 0.5
        c = fc_m[top].mean(0)
        k_ = np.argmin(np.linalg.norm(fc_m[top][:, :2] - c[:2], axis=1))
        palm_r = np.array([c[0], c[1], fc_m[top][k_, 2]])
        palm_l = palm_r.copy()
        axis_author = np.array([0.0, 1.0, 0.0])      # handle points to the weapon's left (author +Y)
    else:
        pr, pl = [], []
        for sign, store in ((1, pr), (-1, pl)):
            sel = fn_m[:, 1] * sign > 0.7
            c = fc_m[sel].mean(0)
            k_ = np.argmin(np.linalg.norm(fc_m[sel][:, [0, 2]] - c[[0, 2]], axis=1))
            store.append(np.array([c[0], fc_m[sel][k_, 1], c[2]]))
        palm_r, palm_l = pr[0], pl[0]
        # grip axis: principal direction of the grip voxels in the x-z plane, pointing up
        q = gcent[:, [0, 2]] - gcent[:, [0, 2]].mean(0)
        w, V = np.linalg.eigh(q.T @ q)
        d = V[:, np.argmax(w)]
        if d[1] < 0:
            d = -d
        if spec.get('grip_axis') is not None:
            d = np.array(spec['grip_axis'], float)
        axis_author = np.array([d[0], 0.0, d[1]]) / np.linalg.norm(d)
        if name == 'pipebomb' or name == 'tripbomb':
            axis_author = np.array([0.0, 0.0, 1.0])
    # translation: palm_right x,z onto v6 palm_right x,z; grip centre on y = 0
    if spec.get('palm_grid') is not None:         # worn items: the palm is given (grid coords), e.g. ahead of a gauntlet
        palm_r = to_md3(np.asarray(spec['palm_grid'], float))
        palm_l = palm_r.copy()
    ycen = gcent[:, 1].mean() if not spec.get('handlebar') else palm_r[1]
    if spec.get('palm_grid') is not None:
        ycen = palm_r[1]
    t = np.array([v6['tags']['tag_palm_right'][0] - palm_r[0], -ycen, v6['tags']['tag_palm_right'][2] - palm_r[2]])
    palm_r, palm_l = palm_r + t, palm_l + t
    if spec.get('handlebar'):
        palm_r[1] = palm_l[1] = 0.0
    # muzzle: front-most slab of the muzzle region
    mreg = box_mask(solid.shape, spec.get('muzzle', {}) if spec.get('muzzle') != 'v6' else {}) & solid
    mc = to_md3(np.argwhere(mreg) + 0.5) + t
    front = mc[:, 0].max()
    slab = mc[mc[:, 0] > front - 1.5 * s]
    muzzle = np.array([front + 0.5 * s, slab[:, 1].mean(), slab[:, 2].mean()])
    bore = max(np.ptp(slab[:, 1]), np.ptp(slab[:, 2])) + s
    if spec.get('muzzle') == 'v6':
        muzzle = v6['tags']['tag_muzzle'] - v6['tags']['tag_palm_right'] + palm_r
        muzzle[1] = v6['tags']['tag_muzzle'][1]
    # support
    sup = spec.get('support')
    if sup == 'v6':
        support = v6['tags']['tag_support'] - v6['tags']['tag_palm_right'] + palm_r
        support[1] = v6['tags']['tag_support'][1]
    else:
        sreg = box_mask(solid.shape, sup) & solid
        support = to_md3(np.argwhere(sreg) + 0.5).mean(0) + t
    # trigger target (author space: y flipped)
    trig_author = None
    if spec.get('trigger'):
        treg = box_mask(solid.shape, spec['trigger']) & solid
        tc = to_md3(np.argwhere(treg) + 0.5) + t
        zhi, zlo = tc[:, 2].max() + 0.5 * s, tc[:, 2].min() - 0.5 * s
        z = zhi - 0.6 * (zhi - zlo)
        trig_author = [float(tc[:, 0].max() + 0.5 * s), float(-tc[:, 1].mean()), float(z)]

    # ---- mesh
    A = np.concatenate([M * 64, (t * 64)[:, None]], 1)
    glow = glow_mask(rgb, solid, spec.get('glow'), grid)
    if spec.get('glow_mask') is not None:
        glow = spec['glow_mask'] & solid
    parts = [dict(solid=solid, rgb=rgb, glow=glow, A=A)]
    flashes = FLASH.get(name, {}) if flashes is None else flashes
    flash_names = list(flashes)
    flash_pos = {}
    cols = flash_colours or FLASH_COLOURS.get(name, ((255, 250, 210), (255, 150, 30)))
    for fname in flash_names:
        mz = muzzle.copy()
        if name == 'devastator':
            # flash_r at the right pod (in line with the grip), flash_l at the left pod
            other = box_mask(solid.shape, dict(y=(28, 49))) & solid
            oc = to_md3(np.argwhere(other) + 0.5) + t
            of = oc[:, 0].max()
            os_ = oc[oc[:, 0] > of - 1.5 * s]
            if fname == 'flash_l':
                mz = np.array([of + 0.5 * s, os_[:, 1].mean(), os_[:, 2].mean()])
        flash_pos[fname] = mz
        parts.append(flash_part(mz, bore, cols, s))
    extras = extra(dict(muzzle=muzzle, palm_r=palm_r, palm_l=palm_l, support=support, s=s, t=t, M=M, bore=bore)) if extra else []
    parts += [e['part'] for e in extras]
    m = mesh_parts(parts)
    pos, nrm, tris, st = m['pos'], m['nrm'], m['tris'], m['st']
    vol = signed_volume(pos, tris)
    assert vol > 0, (name, vol)
    ranges = m['part_ranges']
    # ---- frames
    frames_pos, frames_nrm = [], []
    for fr in v6['frames']:
        P = pos.copy()
        if body_motion and fr in body_motion:          # v6's whole-body motion in this frame (recoil, swing)
            R_, t_ = body_motion[fr]
            v0, v1 = ranges[0]
            P[v0:v1] = P[v0:v1] @ np.asarray(R_, float).T + np.asarray(t_, float) * 64
        for k_, fname in enumerate(flash_names):
            v0, v1 = ranges[k_ + 1]
            if fr not in flashes[fname]:
                P[v0:v1] = (flash_pos[fname] - np.array([0.012, 0, 0])) * 64     # collapsed inside the barrel
        for k_, e in enumerate(extras):
            v0, v1 = ranges[len(flash_names) + 1 + k_]
            if fr not in e['show']:
                P[v0:v1] = np.asarray(e['hide'], float) * 64
            elif fr in e.get('affine', {}):
                R_, t_ = e['affine'][fr]
                P[v0:v1] = P[v0:v1] @ np.asarray(R_, float).T + np.asarray(t_, float) * 64
        if fr in (COLLAPSED.get(name, []) if collapsed is None else collapsed):
            P[:] = palm_r * 64
        frames_pos.append(P / 64.0)
        frames_nrm.append(nrm)
    tags = {}
    tagv = dict(tag_muzzle=muzzle, tag_palm_left=palm_l, tag_palm_right=palm_r, tag_support=support, tag_grip=palm_r)
    for tn in v6['tag_order']:
        tags[tn] = tuple(float(x) for x in tagv[tn])
    tag_frames = [dict((tn, tuple(np.array(tags[tn]) * 64)) for tn in v6['tag_order']) for _ in v6['frames']]
    stem = stem or f'vr_{name}'
    out_dir = OUT / sub
    out_dir.mkdir(parents=True, exist_ok=True)
    surf = dict(name=stem, shader=f'{stem}.png', tris=tris, st=st,
                pos=[p * 64 for p in frames_pos], nrm=frames_nrm)
    size = write_md3(out_dir / f'{stem}.md3', stem, v6['frames'], [surf], tag_frames)
    save_png(m['tex'], out_dir / f'{stem}.png')
    save_png(m['glow'], out_dir / f'{stem}_glow.png')
    wc = weld_check(pos, tris)
    lo, hi = frames_pos[0].min(0), frames_pos[0].max(0)     # rest frame (flash collapsed)
    rec = dict(name=name, stem=stem, source=source or f"voxels/weapons/{spec['kvx']}.kvx (Voxel Duke Nukem 3D by Cheello, PRIVATE)",
               kvx_size=list(k['size']), kvx_pivot=list(k['pivot']), mapping=dict(fwd=spec['fwd'], left=spec['left'], up=spec['up']),
               metres_per_voxel=round(float(s), 6), scale_axis='xyz'[sa],
               translation_m=[round(float(x), 5) for x in t],
               bounds_m=[[round(float(x), 4) for x in lo], [round(float(x), 4) for x in hi]],
               v6_bounds_m=[[round(float(x), 4) for x in v6['mins']], [round(float(x), 4) for x in v6['maxs']]],
               size_ratio_vs_v6=[round(float(a / b), 3) if b > 1e-6 else None for a, b in zip(hi - lo, ext_v6)],
               tags_m={k_: [round(float(x), 5) for x in v] for k_, v in tags.items()},
               grip_axis_author=[round(float(x), 6) for x in axis_author],
               handlebar=bool(spec.get('handlebar')),
               trigger_author=trig_author, hold={'dorsal': [0.0, 0.0, 1.0]} if spec.get('handlebar') else {},
               frames=v6['frames'], flash={k_: v for k_, v in flashes.items()},
               collapsed=COLLAPSED.get(name, []) if collapsed is None else collapsed,
               verts=int(len(st)), tris=int(len(tris)), atlas=list(m['stats']['atlas']), rects=m['stats']['rects'],
               over_md3_spec_limits=bool(len(st) > MD3_SPEC_MAX_VERTS or len(tris) > MD3_SPEC_MAX_TRIS),
               signed_volume_units3=round(vol, 1), weld=wc, md3_bytes=size)
    META.mkdir(parents=True, exist_ok=True)
    if sub:
        rec['md3'] = f'exports/eduke32/{sub}/{stem}.md3'
    (META / f'{meta_name or name}.json').write_text(json.dumps(rec, indent=1))
    print(name, 'verts', rec['verts'], 'tris', rec['tris'], 'm/vox %.4f' % s, 'ratio', rec['size_ratio_vs_v6'], 'weld', wc,
          'atlas', rec['atlas'], flush=True)
    return rec


def main():
    args = dict(a.split('=', 1) for a in sys.argv[1:])
    names = list(SPECS) if args.get('names', 'all') == 'all' else args['names'].split(',')
    for n in names:
        build(n)


if __name__ == '__main__':
    main()
