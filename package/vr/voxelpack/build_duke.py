#!/usr/bin/env python3
"""Third-person Duke (vr_duke) and first-person body (vr_duke_body) from the Voxel Duke Nukem 3D APLAYER voxels.

python3 -I scripts/build_duke.py [f_duke=3] [f_body=2]

* Frames: the 28 v6 frame names. Each frame shows the voxel of the APLAYER action tile that the stock GAME.CON
  uses for it (front-facing rotation = the single 3-D voxel); frames without a voxel reuse the closest one
  (see FRAME_TILE). Every distinct voxel is its own surface `duke_<tile>` (all surfaces share vr_duke.png);
  in the frames where a surface is not shown, all its vertices collapse to one point inside the shown body
  (the torso centre), so only one surface has area in any frame.
* The rifle Duke carries in the voxels is cut out (the engine draws the real held weapon at tag_weapon_right).
* Geometry is meshed at 1/f of the voxel resolution (block solid when >= 3/8 full) with the texture kept at
  the full voxel resolution (f x f texels per block face); f = 1 keeps every voxel (very large file).
* Scale: the standing voxel (1405) is 117 units (1.831 m) tall, like v6's Duke. Axes: +X forward (Duke faces
  KVX +y), +Y right, +Z up, origin on the floor; per frame the neck is put at v6's neck x,y (upright
  frames) or the voxel's own pivot (swim/die/dead), feet on the floor (swim: v6 neck height).
* Tags per frame: tag_neck (identity) and tag_weapon_right (right fist centre; rows = forward/right/up of the
  rifle Duke holds in that voxel, or v6's orientation in frames without a rifle).
* vr_duke_body: same frames/tags/surface layout, torso + legs only (head above the neck, skin = arms and
  hands, and the rifle removed; largest connected piece kept); skin vr_duke_body.png.
"""
import json, sys, os
from pathlib import Path
import numpy as np
from scipy import ndimage
HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('EDUKE32_VOXEL_PACK', HERE.parent))   # the pack folder being built
sys.path.insert(0, str(HERE))
from kvx import read_kvx, fill_solid  # noqa: E402
from voxmesh import mesh_parts, coarse_part, nearest_colour_fill, signed_volume, weld_check, save_png  # noqa: E402
from md3io import write_md3  # noqa: E402
from md3read import read_md3  # noqa: E402
from duke_seg import gun_mask, gun_axis, isin, HAIR, SKIN, RED  # noqa: E402

V6 = Path(os.environ.get('EDUKE32_VR_ASSETS', ROOT.parent)) / 'v6-original'
SRC = ROOT / 'source/voxels/player'
OUT = ROOT / 'exports/eduke32'

# v6 frame -> APLAYER voxel tile (stock GAME.CON actions: PSTAND 0, PWALK/PRUN 20 x4, PJUMPING 50 x4,
# PFALLING 65 (no voxel -> last jump voxel 1465), PDUCKING/PCRAWLING 86 x3, PFLINTCHING/PTHROWNBACK 106 x5,
# lying dead 1516, PSWIMMING 375 x4).
FRAME_TILE = {
    'stand': 1405, 'walk_01': 1425, 'walk_02': 1430, 'walk_03': 1435, 'walk_04': 1440,
    'run_01': 1425, 'run_02': 1430, 'run_03': 1435, 'run_04': 1440, 'shoot': 1405,
    'crouch': 1491, 'crouch_walk_01': 1496, 'crouch_walk_02': 1501, 'crouch_walk_03': 1496, 'crouch_walk_04': 1491,
    'jump': 1455, 'fall': 1465, 'swim_01': 1780, 'swim_02': 1785, 'swim_03': 1790, 'swim_04': 1795,
    'pain': 1511, 'die_01': 1511, 'die_02': 1512, 'die_03': 1513, 'die_04': 1514, 'die_05': 1515, 'dead': 1516,
}
LYING = {1516}
SWIM = {1780, 1785, 1790, 1795}
DIE = {1512, 1513, 1514, 1515, 1516}
MIRROR = np.diag([1.0, -1.0, 1.0])
# KVX -> true-handed (fwd, left, up): Duke faces +y, his left is +x, KVX z is down
L = np.array([[0, 1.0, 0], [1.0, 0, 0], [0, 0, -1.0]])
LM = MIRROR @ L                                     # KVX -> MD3 (fwd, right, up)


def largest_component(m):
    lab, n = ndimage.label(m, structure=np.ones((3, 3, 3)))
    if n <= 1:
        return m
    sizes = ndimage.sum(m, lab, range(1, n + 1))
    return lab == (int(np.argmax(sizes)) + 1)


def analyse(tile):
    k = read_kvx(SRC / f'{tile}_DUKE.kvx')
    g = k['grid']
    stored = g >= 0
    gun = gun_mask(g)
    gun_info = None
    if gun.sum() >= 60:
        c, d = gun_axis(g, gun)
        skin = isin(g, SKIN)
        near = skin & ndimage.binary_dilation(gun, np.ones((3, 3, 3)), iterations=2)
        Pn = np.argwhere(near).astype(float) + 0.5
        if len(Pn) >= 5:
            t = (Pn - c) @ d
            rear = Pn[t <= np.median(t)]          # the rear (trigger) hand
            fist = rear.mean(0)
        else:
            fist = c
        gun_info = dict(centre=c, dir=d, fist=fist)
    gun_region = gun.copy()
    if gun.any():
        # the gun's unstored core: interior cells of the filled voxel next to the removed shell
        core = k['solid'] & ~stored
        grow = gun.copy()
        for _ in range(4):
            grow = ndimage.binary_dilation(grow, np.ones((3, 3, 3))) & (core | gun)
        gun_region = grow | fill_solid(gun)
    solid = largest_component(k['solid'] & ~gun_region)
    keep = solid
    gf = nearest_colour_fill(np.where(gun_region, -1, g), solid)     # colour for every solid cell
    g = gf
    hair = isin(g, HAIR) & keep
    red = isin(g, RED) & keep
    H = np.argwhere(hair).mean(0) + 0.5
    T = np.argwhere(red).mean(0) + 0.5
    return dict(k=k, grid=g, keep=keep, gun=gun, gun_info=gun_info, H=H, T=T)


def main():
    args = dict(a.split('=', 1) for a in sys.argv[1:])
    fs = dict(duke=int(args.get('f_duke', 3)), body=int(args.get('f_body', 2)))
    v6m = read_md3(V6 / 'exports/eduke32/vr_duke.md3')
    frames = [fr['name'] for fr in v6m['frames']]
    assert set(frames) == set(FRAME_TILE), set(frames) ^ set(FRAME_TILE)
    v6tags = [{n: (np.array(t['origin']) / 64.0, np.array(t['axis'])) for n, t in ft.items()} for ft in v6m['tags']]
    tiles = sorted(set(FRAME_TILE.values()))
    info = {t: analyse(t) for t in tiles}
    # scale: standing voxel height = v6 height
    st = info[1405]['keep']
    zs = np.nonzero(st.any((0, 1)))[0]
    v6h = v6m['frames'][0]['maxs'][2] / 64.0 - v6m['frames'][0]['mins'][2] / 64.0
    s = v6h / (zs.max() + 1 - zs.min())
    # neck: along torso-centre -> hair-centre line; calibrated so that the standing neck is 0.36 m under the
    # head top (v6: 1.831 m tall, neck 1.471 m)
    I = info[1405]
    ztop = zs.min()
    neck_z_vox = ztop + (v6h - v6tags[0]['tag_neck'][0][2]) / s
    alpha = (I['T'][2] - neck_z_vox) / (I['T'][2] - I['H'][2])
    for t in tiles:
        J = info[t]
        J['neck_grid'] = J['T'] + alpha * (J['H'] - J['T'])
    # per tile placement (translation in metres, MD3 coords = LM @ grid * s + tr)
    first_frame = {}
    for fr in frames:
        first_frame.setdefault(FRAME_TILE[fr], fr)
    for t in tiles:
        J = info[t]
        fr = first_frame[t]
        v6neck = v6tags[frames.index(fr)]['tag_neck'][0]
        P = np.argwhere(J['keep']).astype(float)
        md3 = (np.concatenate([P, P + 1]) @ LM.T) * s
        neck = LM @ J['neck_grid'] * s
        if t in SWIM or t in DIE:
            piv = np.array(J['k']['pivot'])
            pv = LM @ piv * s
            tx, ty = -pv[0], -pv[1]
        else:
            tx, ty = v6neck[0] - neck[0], v6neck[1] - neck[1]
        tz = (v6neck[2] - neck[2]) if t in SWIM else -md3[:, 2].min()
        J['tr'] = np.array([tx, ty, tz])
        J['neck_md3'] = neck + J['tr']
        J['torso_md3'] = LM @ J['T'] * s + J['tr']
    # tags per frame
    tag_frames = []
    for fi, fr in enumerate(frames):
        J = info[FRAME_TILE[fr]]
        neck = J['neck_md3']
        if J['gun_info'] is not None:
            fist = LM @ J['gun_info']['fist'] * s + J['tr']
            fwd = LM @ J['gun_info']['dir']
            fwd /= np.linalg.norm(fwd)
            right = np.array([0, 1.0, 0]) - fwd[1] * fwd
            right /= np.linalg.norm(right)
            up = np.cross(fwd, right)
            axis = tuple(fwd) + tuple(right) + tuple(up)
        else:
            # no rifle: the right fist = the right-arm skin voxels farthest from the torso centre
            v6w = v6tags[fi]['tag_weapon_right']
            g = J['grid']
            sk = np.argwhere(isin(g, SKIN) & J['keep']).astype(float) + 0.5
            ax = J['H'] - J['T']; ax /= np.linalg.norm(ax)
            side = sk[:, 0] < J['T'][0] - 2                      # Duke's right = KVX -x
            below = (sk - J['neck_grid']) @ ax < -2
            cand = sk[side & below]
            if len(cand) < 10:
                cand = sk[side]
            dist = np.linalg.norm(cand - J['T'], axis=1)
            far = cand[np.argsort(dist)[-30:]]
            fist = LM @ far.mean(0) * s + J['tr']
            axis = tuple(v6w[1])
        tag_frames.append({'tag_neck': (tuple(neck * 64), (1, 0, 0, 0, 1, 0, 0, 0, 1)),
                           'tag_weapon_right': (tuple(fist * 64), axis)})
    report = {}
    upright = [t for t in tiles if t not in SWIM and t not in DIE and t != 1511]
    for variant in ('duke', 'body'):
        f = fs[variant]
        vtiles = tiles if variant == 'duke' else upright
        ftile = dict(FRAME_TILE) if variant == 'duke' else {fr: (t if t in upright else 1405) for fr, t in FRAME_TILE.items()}
        parts = []
        for t in vtiles:
            J = info[t]
            keep = J['keep']
            if variant == 'body':
                g = J['grid']
                # head: everything beyond the neck along the torso->head axis; arms/hands: skin
                ax = J['H'] - J['T']; ax /= np.linalg.norm(ax)
                P = np.indices(keep.shape).transpose(1, 2, 3, 0) + 0.5
                beyond = ((P - J['neck_grid']) @ ax) > 0
                keep = keep & ~beyond & ~isin(g, SKIN) & ~isin(g, HAIR)
                # arms: above the belt keep only the torso's width (tank top x extent + 1 voxel)
                red = np.argwhere(isin(g, RED) & J['keep']).astype(float) + 0.5
                x_lo, x_hi = np.percentile(red[:, 0], 3) - 1, np.percentile(red[:, 0], 97) + 1
                belt = ((P - J['T']) @ ax) > -0.8 * float((J['neck_grid'] - J['T']) @ ax)
                lateral = (P[..., 0] < x_lo) | (P[..., 0] > x_hi)
                keep = keep & ~(belt & lateral)
                keep = largest_component(fill_solid(keep))
            A = np.concatenate([LM * s * 64 * f, (J['tr'] * 64)[:, None]], 1)
            if f == 1:
                parts.append(dict(solid=keep, rgb=J['k']['palette'][np.clip(J['grid'], 0, 255)], A=A))
            else:
                parts.append(coarse_part(J['grid'], J['k']['palette'], keep, f, A))
        m = mesh_parts(parts, min_atlas_w=512)
        surfaces = []
        stem = 'vr_duke' if variant == 'duke' else 'vr_duke_body'
        per = {}
        for pi, t in enumerate(vtiles):
            v0, v1 = m['part_ranges'][pi]
            t0, t1 = m['tri_ranges'][pi]
            pos = m['pos'][v0:v1]
            tris = m['tris'][t0:t1] - v0
            vol = signed_volume(pos, tris)
            assert vol > 0, (variant, t, vol)
            fpos = []
            for fr in frames:
                if ftile[fr] == t:
                    fpos.append(pos)
                else:
                    c = info[ftile[fr]]['torso_md3'] * 64
                    fpos.append(np.repeat(c[None], len(pos), 0))
            surfaces.append(dict(name=f'duke_{t}' if variant == 'duke' else f'body_{t}', shader=f'{stem}.png',
                                 tris=tris, st=m['st'][v0:v1], pos=fpos, nrm=[m['nrm'][v0:v1]] * len(frames)))
            P = pos / 64
            per[t] = dict(verts=int(v1 - v0), tris=int(t1 - t0), bounds_m=[P.min(0).round(3).tolist(), P.max(0).round(3).tolist()],
                          signed_volume=round(vol, 1), weld=weld_check(pos, tris))
        size = write_md3(OUT / f'{stem}.md3', stem, frames, surfaces, tag_frames)
        save_png(m['tex'], OUT / f'{stem}.png')
        report[variant] = dict(block_factor=f, metres_per_block=round(float(s * f), 5), frame_tile=ftile, md3_bytes=size, atlas=list(m['stats']['atlas']), surfaces=per,
                               total_verts=int(sum(p['verts'] for p in per.values())))
        print(variant, 'bytes', size, 'atlas', m['stats']['atlas'], 'verts', report[variant]['total_verts'], flush=True)
    rec = dict(name='duke', source='voxels/player/<tile>_DUKE.kvx (Voxel Duke Nukem 3D by Cheello, PRIVATE)',
               block_factor=fs, metres_per_voxel=round(float(s), 5),
               frame_tile=FRAME_TILE, neck_alpha=round(float(alpha), 4),
               rifle_removed_voxels={t: int(info[t]['gun'].sum()) for t in tiles},
               tags_m={fr: {n: [round(float(x) / 64, 4) for x in v[0]] for n, v in tf.items()} for fr, tf in zip(frames, tag_frames)},
               report=report)
    (ROOT / 'metadata/assets/duke.json').write_text(json.dumps(rec, indent=1))


if __name__ == '__main__':
    main()
