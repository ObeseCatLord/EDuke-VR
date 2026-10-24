#!/usr/bin/env python3
"""Alien Armageddon held models for the voxel pack: exports/eduke32/aa/<family>.md3/.png/_glow.png.

python3 -I build_aa.py [ids=glock,cluster_bomb|all] [aa=PATH]

Every family in v6-original/metadata/aa_inventory.json gets a voxel model on its v6 contract (frame names,
tag names and order, one surface, effect/flash frames, thrown/placed collapse), built from, in order:

  reuse   the stock Duke weapons AA draws with Duke 3D's own art (duke_pistol, duke_defender, duke_ripper,
          duke_rpg, pipebomb, tripmine, shrinker, expander, devastator, freezer, detonator): the pack's
          Voxel Duke model, renamed, when the v6 AA file has exactly the vanilla contract. Holds = the
          voxel weapon's solved hold.
  aavox   AA's own pickup voxel for the family (voxels/AA_voxels/*.kvx in the user's AA install), oriented
          like the Duke pickups (muzzle -x, up -z), scaled to the v6 length (or a set length).
  sprite  the family's side-view pickup tile from the install's ART: a lathe (round items) or the
          silhouette extruded with the v6 model's thickness at each point; colours = the tile's pixels.
  saber   AA's saber hilt voxel plus a blade of voxels in the blade colour of the HUD tiles.
  v6      no AA art to build from: the v6 model voxelised (voxelise.py), coloured from its own texture.

The AA install is read at build time only (untrusted data, parsed, never executed). Without it only the
`reuse` families are built and the others fall back to the shipped originals.
Placement: the grip is found around where v6's hand is; palm tags on its side faces (build_weapons rule);
the model is moved so tag_palm_right sits on v6's. The trigger target is the voxel surface in front of the
grip nearest v6's trigger finger. Holds are re-solved on the new geometry (solve_holds.py aa=all).
"""
import json, os, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('EDUKE32_VOXEL_PACK', HERE.parent))
sys.path.insert(0, str(HERE))
import build_weapons as BW  # noqa: E402
from kvx import read_kvx, fill_solid  # noqa: E402
from kitbash import nearest_index  # noqa: E402
from md3parts import parts as md3_parts  # noqa: E402
import aaart  # noqa: E402

ASSETS = Path(os.environ.get('EDUKE32_VR_ASSETS', ROOT.parent))
V6 = ASSETS / 'v6-original'
OUT = ROOT / 'exports' / 'eduke32' / 'aa'
META = ROOT / 'metadata' / 'assets'
STD = dict(fwd='-x', left='+y', up='-z')
CREDIT_AA = 'Alien Armageddon 5.66 (the user\'s install), PRIVATE'

# family -> how to build it. Optional keys: crop (KVX index boxes to keep), length_m (real length of the
# whole voxel model when v6's length covers only part of it), grip / trigger (KVX index boxes when the
# automatic choice is wrong), lathe ('x' or 'z'), tile (pickup tile), flip (sprite faces right).
FAMILIES = {
    'duke_pistol': dict(kind='reuse', weapon='pistol'),
    'duke_defender': dict(kind='reuse', weapon='shotgun'),
    'duke_ripper': dict(kind='reuse', weapon='chaingun'),
    'duke_rpg': dict(kind='reuse', weapon='rpg'),
    'pipebomb': dict(kind='reuse', weapon='pipebomb'),
    'tripmine': dict(kind='reuse', weapon='tripbomb'),
    'shrinker': dict(kind='reuse', weapon='shrinker'),
    'expander': dict(kind='reuse', weapon='expander'),
    'devastator': dict(kind='reuse', weapon='devastator'),
    'freezer': dict(kind='reuse', weapon='freezer'),
    'detonator': dict(kind='reuse', weapon='detonator'),
    'duke_heavy_pistol': dict(kind='aavox', kvx='10377_Duke_Pistol_Up',
                              features=[('sights', dict(rear=(60, 220, 60), front=(60, 220, 60)))]),
    'shelly_pistol': dict(kind='aavox', kvx='7678_pistolS', features=[('sights', dict())]),
    'shelly_heavy_pistol': dict(kind='aavox', kvx='shellly_gun',
                                features=[('sights', dict(rear=(230, 30, 20), front=(60, 220, 60)))]),
    'glock': dict(kind='aavox', kvx='8176_glock', length_m=0.36,
                  features=[('sights', dict(rear=(235, 235, 235), front=(235, 235, 235)))]),
    'wes_revolver': dict(kind='aavox', kvx='19681_Wes_gun'),
    'mando_wrist': dict(kind='aavox', kvx='mando_glove', crop=[(15, 66), (0, 23), (0, 26)], length_m=0.26,
                        features=[('mando_gauntlet', {})], palm_front=0.05, grip_axis=(0.0, 1.0)),   # worn on the forearm
    'dea_pistol': dict(kind='v6vox', features=[('dea_pistol', {})]),
    'alien_blaster': dict(kind='aavox', kvx='5860_alienpistol', features=[('back_dot', dict(zf=0.2, colour=(250, 220, 40), n=3))]),
    'commgun': dict(kind='aavox', kvx='17494_torpedo', features=[('cap_back', {}), ('top_panel', dict(x=(0.45, 0.75)))]),
    'duke_combat_shotgun': dict(kind='aavox', kvx='8909_Atom_sht', features=[('sights', dict(rear=(90, 250, 60), front=(90, 250, 60)))]),
    'duke_atomic_double': dict(kind='aavox', kvx='18669_DB'),
    'shelly_spas': dict(kind='aavox', kvx='7707_Spas-12'),
    'wes_benelli': dict(kind='aavox', kvx='19689_wes_sg', features=[('ribs', dict(x=(0.05, 0.6)))]),
    'mando_pmp': dict(kind='aavox', kvx='mando_sg'),
    'mando_wstem8': dict(kind='aavox', kvx='mando_secondgun', grip=dict(x=(64, 74), z=(14, 21)),
                         features=[('top_dot', dict(xf=0.55, colour=(250, 140, 30), n=2)), ('top_dot', dict(xf=0.62, colour=(250, 140, 30), n=2))]),
    'dea_shotgun': dict(kind='aavox', kvx='21945_dea_sg'),
    'dea_crossbow': dict(kind='aavox', kvx='22251_deaxbow'),
    'versa_bow': dict(kind='aavox', kvx='8938_bow', scale_axis=2),
    'duke_minigun': dict(kind='aavox', kvx='8958_chaingun_upgrade', features=[('top_panel', dict(x=(0.55, 0.68), colour=(80, 210, 70)))]),
    'shelly_smg': dict(kind='aavox', kvx='7709_M4', features=[('holo_sight', dict(xf=0.45))]),
    'shelly_smg_upgrade': dict(kind='aavox', kvx='8957_dualM4', features=[('holo_sight', dict(xf=0.42))]),
    'wes_uzi': dict(kind='aavox', kvx='19673_uzi'),
    'mando_slugthrower': dict(kind='aavox', kvx='mando_chaingun', features=[('holo_sight', dict(xf=0.5, h=8, L=6))]),
    'dea_laser_minigun': dict(kind='aavox', kvx='dea_chaingun'),
    'executioner': dict(kind='aavox', kvx='15480_executioner', grip=dict(x=(64, 76), z=(20, 31)),
                        features=[('paint', dict(box=[(40, 90), (0, 26), (32, 41)], colour=(230, 130, 30)))]),   # orange drum rim
    'smart_launcher': dict(kind='aavox', kvx='9965_sl', features=[('side_scope', dict(x=(0.6, 0.85), r=4))]),
    'shelly_rpg': dict(kind='aavox', kvx='7714_N64_RPG', features=[
        ('recolour', dict(ramp=[(52, 64, 26), (78, 94, 38), (104, 122, 52), (136, 150, 70)], x=(0.08, 0.92))),
        ('top_dot', dict(xf=0.62, colour=(220, 40, 30), n=2)), ('top_dot', dict(xf=0.66, colour=(50, 80, 220), n=2))]),
    'wes_rpg': dict(kind='aavox', kvx='19696_wes_rl'),
    'mando_rpg': dict(kind='aavox', kvx='mando_rpg'),
    'dea_quad_launcher': dict(kind='aavox', kvx='21987_dea_rpg'),
    'nuke_launcher': dict(kind='aavox', kvx='10357_atomic_launcher', features=[('top_dot', dict(xf=0.7, colour=(240, 210, 30), n=3))]),
    'cluster_bomb': dict(kind='sprite', tile=13004, lathe='z', upright=True, scale_axis=2, length_m=0.2, downsample=2,
                         spikes=True, hud_tiles=(13006, 13007, 13005)),
    'rolly_turret': dict(kind='aavox', kvx='7727_turret', downsample=2),
    'ice_bomb': dict(kind='sprite', tile=19915, lathe='z', downsample=3),
    'thermal_detonator': dict(kind='sprite', tile=20717, lathe='z', downsample=2),
    'doll_bomb': dict(kind='aavox', kvx='doll', downsample=2),
    'spider_mine': dict(kind='aavox', kvx='spidermine'),
    'bmfg': dict(kind='aavox', kvx='13010_bmfg'),
    'wes_scar': dict(kind='aavox', kvx='19899_wescar'),
    'chronolator': dict(kind='sprite', tile=22245, recipe='chronolator', hud_tiles=(22246, 22247)),
    'eviscerator': dict(kind='sprite', tile=22262, width=1.8),
    'plasma_rifle': dict(kind='aavox', kvx='10423_plasma_rifle', features=[('top_panel', dict(x=(0.25, 0.85), colour=(176, 176, 182)))]),
    'double_d': dict(kind='aavox', kvx='7790_grenade_launchers', grip_y=(0, 34)),   # the right-hand launcher
    'annihilator': dict(kind='v6vox', features=[('annihilator', {})], hud_tiles=(21244, 21245, 21246)),
    'railgun': dict(kind='aavox', kvx='5329_railgunstriker', features=[('back_dot', dict(zf=0.1, colour=(40, 70, 200), n=3))]),
    'penetrator': dict(kind='aavox', kvx='8186_sniper'),
    'disintegrator': dict(kind='aavox', kvx='21188_mando_desintegr'),
    'freezer_beam': dict(kind='aavox', kvx='8956_freezer_upgrade'),
    'incinerator': dict(kind='aavox', kvx='7791_Incinerator'),
    'blade_launcher': dict(kind='aavox', kvx='19931_ripsaw'),
    'carbonite_rifle': dict(kind='sprite', tile=20960, flip=True, width=1.5),     # its pickup tile faces right
    'goop_gun': dict(kind='sprite', tile=22276, width=1.6),
    'energy_saber': dict(kind='saber', kvx='10934_vorpal', blade_tiles=(10928, 10929, 10930)),
    'wes_blade': dict(kind='aavox', kvx='19674_daywalker_sword'),
    'dea_claw': dict(kind='v6vox', features=[('dea_claw', {})], hud_tiles=(21921, 21922, 21919)),   # pickup tile = hand + blade
    'duke_chainsaw': dict(kind='aavox', kvx='7641_saw_smart'),
    'circular_saw': dict(kind='aavox', kvx='0036_chainsaw', features=[('stripes', dict(x=(0.45, 0.75), z=(0.3, 0.7)))]),
    'juicer': dict(kind='kit', kvx='17660_spray'),
}


def inventory():
    return json.loads((V6 / 'metadata' / 'aa_inventory.json').read_text())['families']


# ------------------------------------------------------------------ the v6 contract of a family
def contract(fid):
    path = V6 / 'exports/eduke32/aa' / f'{fid}.md3'
    info = md3_parts(path)
    frames = info['frames']
    body = info['shells'][info['body']]
    eff = [sh for i, sh in enumerate(info['shells']) if i != info['body']]
    flash = {}
    for i, sh in enumerate(eff):
        shown = [frames[f] for f in range(len(frames)) if sh['shown'][f]]
        if shown and len(shown) < len(frames):
            flash[f'flash{i}' if i else 'flash'] = shown
    collapsed = [frames[f] for f in range(len(frames)) if not body['shown'][f]]
    # whole-body motion per frame (recoil kick, blade swing, wind-up): similarity fit of the body shell
    from voxelise import umeyama
    X = info['X'][:, body['verts']]
    motion = {}
    for f in range(1, len(frames)):
        if frames[f] in collapsed:
            continue
        c, R, t = umeyama(X[0][None], X[f][None])
        c, R, t = float(c[0]), R[0], t[0]
        err = np.abs(c * X[0] @ R.T + t - X[f]).max()
        if np.abs(c * R - np.eye(3)).max() > 1e-4 or np.abs(t).max() > 1e-4:
            motion[frames[f]] = (c * R, t, float(err))
    lo, hi = X[0].min(0), X[0].max(0)
    return dict(path=path, info=info, frames=frames, flash=flash, collapsed=collapsed, motion=motion,
                body_lo=lo, body_hi=hi, tags=info['tags'][0])


def v6_hold(fid, side='right'):
    flat = json.loads((V6 / 'metadata' / 'hand_poses_flat.json').read_text())
    return flat['poses'][side].get(f'hold_{fid}', {}).get('joints')


def trigger_point(fid):
    """v6's right index fingertip pad (MD3 metres) when that hold has a trigger finger, else None."""
    J = v6_hold(fid)
    if not J:
        return None
    from hands import SHORT
    P = {n: np.array(J[i][:3]) for i, n in enumerate(SHORT)}
    if np.linalg.norm(P['index_tip'] - P['middle_tip']) < 0.03:
        return None
    return (P['index_distal'] + P['index_tip']) / 2


# ------------------------------------------------------------------ automatic grip / trigger boxes
def to_box(idx):
    lo, hi = idx.min(0), idx.max(0)
    return {a: (int(lo[i]), int(hi[i])) for i, a in enumerate('xyz')}


def auto_grip(solid, s, con):
    """KVX index box of the grip. v6's palm, measured from the muzzle end and from the top in metres, gives
    the expected spot; the grip is the part that reaches below the palm there (pistol grip, handle,
    hilt): the run of side-view columns reaching below that height whose nearest column is closest to the
    spot (a run reaching the very back is a shoulder stock and is skipped while another part qualifies),
    3 cm either side of it, from a little above the palm down. Round or flat items without such a part:
    the voxels within 3 cm of the spot."""
    lo, hi = con['body_lo'], con['body_hi']
    palm = con['tags']['tag_palm_right']
    idx = np.argwhere(solid)
    x0, z0, z1 = idx[:, 0].min(), idx[:, 2].min(), idx[:, 2].max()
    ex = x0 + (hi[0] - palm[0]) / s                # KVX x grows toward the back (MD3 -x)
    ez = z0 + (hi[2] - palm[2]) / s                # KVX z grows downward
    side = solid.any(1)
    X = side.shape[0]
    bottom = np.array([np.nonzero(side[x])[0].max() if side[x].any() else -1 for x in range(X)])
    below = bottom > ez + 1
    half = max(2, int(round(0.03 / s)))
    up = max(2, int(round(0.025 / s)))
    # 1) a trigger guard: a closed hole in the lower part of the side view; the grip starts at its back edge
    from scipy import ndimage
    holes = ndimage.binary_fill_holes(side) & ~side
    lab, n = ndimage.label(holes)
    zmid = z0 + 0.35 * (z1 - z0)
    cands = []
    for i in range(1, n + 1):
        h = np.argwhere(lab == i)
        if len(h) < 2 or h[:, 1].mean() < zmid:
            continue
        back = h[:, 0].max()
        c = back + half
        if back + 2 * half >= idx[:, 0].max() - 1:      # a hole in the shoulder stock
            continue
        cands.append((abs(c - ex), back, h[:, 1].min()))
    if cands:
        d, back, top = min(cands)
        if d * s < 0.12:
            sel = (idx[:, 0] > back) & (idx[:, 0] <= back + 2 * half) & (idx[:, 2] >= min(top, ez - up))
            if sel.sum() >= 4:
                return to_box(idx[sel]), idx[sel]
    runs = []
    x = 0
    while x < X:
        if below[x]:
            r0 = x
            while x < X and below[x]:
                x += 1
            runs.append((r0, x - 1))
        else:
            x += 1
    x_end = idx[:, 0].max()
    # a run that ends at the very back is a shoulder stock: never the grip while another part qualifies
    inner = [r for r in runs if r[1] < x_end - 1] or runs
    best = None
    for r0, r1 in inner:
        near = min(max(ex, r0), r1)
        d = abs(near - ex)
        if best is None or d < best[0]:
            best = (d, r0, r1, near)
    if best is not None and best[0] * s < 0.25:
        _, r0, r1, near = best
        c = int(round(near))
        xa, xb = max(r0, c - half), min(r1, c + half)
        sel = (idx[:, 0] >= xa) & (idx[:, 0] <= xb) & (idx[:, 2] >= ez - up)
        if sel.sum() >= 4:
            return to_box(idx[sel]), idx[sel]
    d = np.linalg.norm((idx[:, [0, 2]] - np.array([ex, ez])) * s, axis=1)
    sel = d <= max(0.03, np.sort(d)[min(len(d) - 1, 8)])
    return to_box(idx[sel]), idx[sel]


def placement(solid, s, spec, con):
    """Replicates build_weapons' palm rule to know where the model will sit (for the trigger search)."""
    L = BW.MIRROR @ np.stack([BW.axis_vec(spec['fwd']), BW.axis_vec(spec['left']), BW.axis_vec(spec['up'])])
    gmask = BW.box_mask(solid.shape, spec['grip']) & solid
    fc, fn = BW.exposed_faces(solid, gmask)
    fc_m, fn_m = fc @ (L * s).T, fn @ L.T
    sel = fn_m[:, 1] > 0.7
    c = fc_m[sel].mean(0) if sel.any() else fc_m.mean(0)
    gcent = (np.argwhere(gmask) + 0.5) @ (L * s).T
    t = np.array([con['tags']['tag_palm_right'][0] - c[0], -gcent[:, 1].mean(), con['tags']['tag_palm_right'][2] - c[2]])
    return L * s, t


def auto_trigger(solid, s, spec, con, fid):
    p = trigger_point(fid)
    if p is None:
        return None
    M, t = placement(solid, s, spec, con)
    idx = np.argwhere(solid)
    pts = (idx + 0.5) @ M.T + t
    grip_front = ((np.array([spec['grip']['x'][0], 0, 0]) + 0.5) @ M.T + t)[0]
    d = np.linalg.norm(pts - p, axis=1)
    ok = (pts[:, 0] > grip_front - 0.5 * s) & (d < 0.02)
    if ok.sum() < 1:
        return None
    near = idx[ok][np.argsort(d[ok])[:6]]
    return to_box(near)


# ------------------------------------------------------------------ sources
def aa_kvx(art, name):
    """An AA pickup voxel. Voxels in a pure-magenta palette entry (some AA voxels keep index 245 = magenta, an
    editor marker that never shows as a colour) take the colour of the nearest other voxel."""
    from scipy import ndimage
    p = art.root / 'voxels' / 'AA_voxels' / f'{name}.kvx'
    k = read_kvx(p)
    pal = k['palette'].astype(int)
    bad = np.nonzero((pal[:, 0] > 180) & (pal[:, 1] < 80) & (pal[:, 2] > 180))[0]
    g = k['grid']
    m = np.isin(g, bad)
    if m.any():
        good = (g >= 0) & ~m
        _, ind = ndimage.distance_transform_edt(~good, return_indices=True)
        g = g.copy()
        g[m] = g[tuple(ind)][m]
        k = dict(k, grid=g)
    return k, f'voxels/AA_voxels/{name}.kvx'


def grid_from_rgb(occ, rgb, palette):
    """Composite (occupancy, colours) -> read_kvx-like dict (Duke palette indices, interior filled)."""
    from scipy import ndimage
    solid = fill_solid(occ)
    g = np.full(occ.shape, -1, np.int16)
    g[occ] = nearest_index(rgb[occ], palette[:255])
    _, ind = ndimage.distance_transform_edt(g < 0, return_indices=True)
    g = np.where(solid, g[tuple(ind)], -1).astype(np.int16)
    n = occ.shape
    return dict(grid=g, solid=solid, palette=palette, size=tuple(int(v) for v in n), pivot=tuple(v / 2 for v in n))


def add_spikes(occ, col):
    """Spikes radiating from the top end of an upright lathed item (cluster bomb, HUD 13006/13007): two rings
    of eight, staggered, rising outward, and one on top; dark metal with light tips."""
    W, Y_, H = occ.shape
    zs = np.nonzero(occ.any((0, 1)))[0]
    z0 = int(zs.min())
    pad = 4
    occ = np.pad(occ, ((pad, pad), (pad, pad), (pad, 0)))
    col = np.pad(col, ((pad, pad), (pad, pad), (pad, 0), (0, 0)))
    cx, cy_ = (W - 1) / 2 + pad, (Y_ - 1) / 2 + pad
    R = float(np.max(np.hypot(*(np.argwhere(occ[:, :, z0 + pad + 3])[:, :2] - [cx, cy_]).T))) if occ[:, :, z0 + pad + 3].any() else W / 2
    dark, tip = (66, 66, 70), (140, 140, 146)
    for ring, zz in enumerate((z0 + 2, z0 + 5)):
        for k in range(8):
            a = 2 * np.pi * (k + 0.5 * ring) / 8
            for t in range(int(R) - 1, int(R) + 4):
                x = int(round(cx + t * np.cos(a)))
                y = int(round(cy_ + t * np.sin(a)))
                z = zz + pad - max(0, t - int(R)) // 2
                occ[x, y, z] = True
                col[x, y, z] = tip if t >= int(R) + 2 else dark
    for t in range(4):
        occ[int(cx), int(cy_), z0 + pad - 1 - t] = True
        col[int(cx), int(cy_), z0 + pad - 1 - t] = tip if t >= 2 else dark
    return occ, col


def sprite_model(art, fam, con, palette):
    """Pickup tile -> voxels (KVX convention: x = tile column with the muzzle at 0, z = tile row, y = depth)."""
    t = art.tile(fam['tile'])
    m = t != 255
    rows, cols = np.nonzero(m)
    t = t[rows.min():rows.max() + 1, cols.min():cols.max() + 1]
    m = t != 255
    if fam.get('flip'):
        t, m = t[:, ::-1], m[:, ::-1]
    if fam.get('recipe'):                          # room around the silhouette for raised features
        t = np.pad(t, 8, constant_values=255)
        m = t != 255
    if fam.get('upright'):                          # long axis vertical, the tile's right end up
        t, m = np.rot90(t, 1), np.rot90(m, 1)
    rgb = art.palette[t]
    H, W = t.shape

    def nearest_opaque(z, x, axis_rows=True):
        if axis_rows:
            zs = np.nonzero(m[:, x])[0]
            return rgb[zs[np.argmin(np.abs(zs - z))], x]
        xs = np.nonzero(m[z])[0]
        return rgb[z, xs[np.argmin(np.abs(xs - x))]]
    if fam.get('lathe') == 'x':                    # round about the long (x) axis: each column a disc
        R = int(np.ceil(H / 2))
        occ = np.zeros((W, 2 * R + 1, H), bool)
        col = np.zeros((W, 2 * R + 1, H, 3), np.uint8)
        for x in range(W):
            zs = np.nonzero(m[:, x])[0]
            if not len(zs):
                continue
            zc, r = (zs.min() + zs.max()) / 2, (zs.max() - zs.min() + 1) / 2
            for z in range(H):
                for y in range(2 * R + 1):
                    if (y - R) ** 2 + (z - zc) ** 2 <= r * r:
                        occ[x, y, z] = True
                        col[x, y, z] = nearest_opaque(z, x)
        return occ, col
    if fam.get('lathe') == 'z':                    # round about the vertical axis: each row a disc
        R = int(np.ceil(W / 2))
        occ = np.zeros((W, 2 * R + 1, H), bool)
        col = np.zeros((W, 2 * R + 1, H, 3), np.uint8)
        for z in range(H):
            xs = np.nonzero(m[z])[0]
            if not len(xs):
                continue
            xc, r = (xs.min() + xs.max()) / 2, (xs.max() - xs.min() + 1) / 2
            for x in range(W):
                for y in range(2 * R + 1):
                    if (x - xc) ** 2 + (y - R) ** 2 <= r * r:
                        occ[x, y, z] = True
                        col[x, y, z] = nearest_opaque(z, int(round(xc + (x - xc) * 0.9)), axis_rows=False)
        return occ, col
    # extrusion: the silhouette, as thick at each point as the v6 model is there (its y extent)
    from voxelise import _winding_grid
    info = con['info']
    body = info['shells'][info['body']]
    P = info['X'][0]
    T = info['tris'][body['tris']]
    lo, hi = con['body_lo'], con['body_hi']
    s = (hi[0] - lo[0]) / W
    ny = int(np.ceil((hi[1] - lo[1]) / s)) + 2
    inside = _winding_grid(P, T, np.array([lo[0], lo[1] - s, lo[2]]), s, (W, ny, H))   # MD3 x up, z up
    thick = inside.sum(1)                          # [W (md3 x), H (md3 z)]
    cen = np.where(thick > 0, (inside * np.arange(ny)[None, :, None]).sum(1) / np.maximum(thick, 1), ny / 2)
    thick = thick[::-1, ::-1]                      # -> tile columns (muzzle first), rows (top first)
    from scipy import ndimage
    _, ind = ndimage.distance_transform_edt(thick == 0, return_indices=True)
    thick = np.maximum(thick[tuple(ind)] * fam.get('width', 1.0), 2)   # width: chunkier than v6 where the HUD is
    pad = 14                                       # room for features standing out of the body (ribs)
    Y = int(thick.max()) + 2 + 2 * pad
    occ = np.zeros((W, Y, H), bool)
    col = np.zeros((W, Y, H, 3), np.uint8)
    for x in range(W):
        z = 0
        while z < H:                               # every vertical run of the column gets a rounded section
            if not m[z, x]:
                z += 1
                continue
            z0 = z
            while z < H and m[z, x]:
                z += 1
            z1 = z - 1
            hw = float(np.median(thick[x, z0:z1 + 1])) / 2
            zc, half = (z0 + z1) / 2, (z1 - z0 + 1) / 2
            for zz in range(z0, z1 + 1):
                t = min(1.0, abs(zz - zc) / max(half, 0.5))
                h = max(1, int(round(2 * hw * (1 - t ** 3) ** (1 / 3))))     # superellipse: round top/bottom
                y0 = (Y - h) // 2
                occ[x, y0:y0 + h, zz] = True
                col[x, y0:y0 + h, zz] = rgb[zz, x]
    fam['_features'] = ['side silhouette extruded with a rounded (superellipse) section, v6 thickness per column'
                        + (f" x {fam['width']} (chunkier, as the HUD frames show)" if fam.get('width') else '')]
    recipe = RECIPES.get(fam.get('recipe'))
    if recipe:
        occ, col, feats = recipe(occ, col, m, rgb, art, fam)
        fam['_features'] += feats
    return occ, col


def hud_colours(art, tiles):
    """Typical colours of a family's HUD tiles by kind (median of the matching pixels): the colours the
    feature recipes paint with."""
    c = np.concatenate([art.palette[t[t != 255]].astype(int) for t in (art.tile(n) for n in tiles) if t is not None])
    sat = c.max(1) - c.min(1)
    kinds = dict(orange=(c[:, 0] > 150) & (c[:, 1] > 60) & (c[:, 2] < 90) & (c[:, 0] > c[:, 1] + 40),
                 light_blue=(c[:, 2] > 170) & (c[:, 2] > c[:, 0] + 40),
                 blue=(c[:, 2] > 90) & (c[:, 2] > c[:, 0] + 40) & (c[:, 2] <= 170),
                 dark=(c.max(1) < 70) & (sat < 30),
                 grey=(c.max(1) >= 70) & (c.max(1) < 170) & (sat < 30))
    out = {}
    for k, msk in kinds.items():
        if msk.sum() < 10:
            continue
        cc = c[msk]
        lum = cc.sum(1)
        out[k] = [tuple(int(v) for v in np.median(cc[lum <= np.percentile(lum, q)], 0)) for q in (25, 60, 100)]
    return out


def recipe_chronolator(occ, col, m, rgb, art, fam):
    """The barrel housing as the HUD shows it from above/behind: an open blue cage (rails on the top edges and
    cross bars, side panels with the side view's windows cut through) round a row of dark round cells, and
    square orange frames standing proud of it, open underneath, where the side view has its orange bands."""
    hud = hud_colours(art, fam['hud_tiles'])
    orange, lblue, blue, dark = hud['orange'], hud['light_blue'], hud['blue'], hud['dark']
    grey = hud.get('grey', dark)
    W, Y, H = occ.shape
    pal = rgb.astype(int)
    is_orange = (pal[..., 0] > 150) & (pal[..., 2] < 90) & (pal[..., 0] > pal[..., 1] + 40) & m
    is_blue = (pal[..., 2] > pal[..., 0] + 20) & m
    # housing: the blue band at the top of the side view, from the muzzle back to where the blue ends
    rows = [z for z in range(H) if is_blue[z].sum() > 0.25 * W]
    z0, z1 = min(rows), max(rows)
    from scipy import ndimage
    # the longest run of mostly-blue columns (the front part; the thin orange bands across it are bridged)
    frac = ndimage.maximum_filter1d(is_blue[z0:z1 + 1].mean(0), 7)
    best, x = (0, 0, -1), 0
    while x < W:
        if frac[x] > 0.3:
            r0 = x
            while x < W and frac[x] > 0.3:
                x += 1
            best = max(best, (x - r0, r0, x - 1))
        else:
            x += 1
    _, x0, x1 = best
    hh = (z1 - z0 + 1) / 2
    hw = int(round(hh * 1.35))                     # boxy: the HUD cage is wider than the side view is tall
    cy = Y // 2
    occ[x0:x1 + 1, :, z0:z1 + 1] = False
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            for y in range(cy - hw, cy + hw + 1):
                side = abs(y - cy) >= hw - 1
                top = z <= z0 + 1
                bottom = z >= z1 - 1
                rail = top and side
                bar = top and (x - x0) % 9 in (0, 1)
                panel = side and not top and m[z, x] and pal[z, x].max() >= 50       # side windows stay open
                floor = bottom
                if rail or bar:
                    occ[x, y, z], col[x, y, z] = True, lblue[2] if rail else lblue[1]
                elif panel or floor:
                    occ[x, y, z], col[x, y, z] = True, blue[1] if panel else blue[0]
        # dark round cells inside, an axle between them
        k = (x - x0) % 7
        r = hw - 1.2 if k in (1, 2, 3, 4, 5) else 1.2         # big drums, an axle between them
        zc = (z0 + z1) / 2 + 0.5
        for z in range(z0, z1 + 1):
            for y in range(cy - hw, cy + hw + 1):
                d2 = (y - cy) ** 2 + (z - zc) ** 2
                if d2 <= r * r:
                    occ[x, y, z] = True
                    rim = d2 > (r - 1.5) ** 2
                    col[x, y, z] = (grey[2] if z < zc else grey[1]) if rim and k in (1, 5) else \
                        (grey[1] if z < zc - r * 0.5 else dark[1])
    # orange frames: one per orange band crossing the housing in the side view
    top_orange = is_orange[z0:z0 + 2, x0:x1 - 2].any(0)   # the bands reach the housing's top edge
    frames, x = [], 0
    while x < len(top_orange):
        if top_orange[x]:
            r0 = x
            while x < len(top_orange) and top_orange[x]:
                x += 1
            frames.append(x0 + (r0 + x - 1) // 2)
        else:
            x += 1
    t = max(3, int(round(hw * 0.6)))              # chunky square rings: about a third of the cage width thick
    for c in frames:
        for x in range(c - 2, c + 2):
            for z in range(z0 - t, z1 + 3):
                for y in range(cy - hw - t, cy + hw + t + 1):
                    dy, dz = abs(y - cy) - hw, z0 - z           # > 0: outside the cage side / above its top
                    if (dy > 0 or dz > 0) and 0 <= y < Y and z >= 0:
                        occ[x, y, z] = True
                        edge = max(dy, dz) >= t or x == c - 2       # outer rim / front face: bevel light
                        inner = max(dy, dz) <= 1
                        col[x, y, z] = orange[2] if edge else orange[0] if inner else orange[1]
    feats = [f'barrel housing x {x0}-{x1}: square open cage ({2 * hw + 1} wide), light-blue rails on the top edges and '
             'cross bars every 9 voxels, blue side panels with the side view\'s windows cut through',
             'big dark drums (r = housing - 1) filling the cage, grey rims and lit tops, axle between',
             f'{len(frames)} chunky orange square rings at x {frames}, 4 thick, {t} proud on top and sides, '
             'bevel shading (light rim and front face, dark inner edge), open underneath',
             'colours: median orange / light blue / blue / dark / grey of HUD tiles ' + ', '.join(map(str, fam['hud_tiles']))]
    return occ, col, feats


RECIPES = {'chronolator': recipe_chronolator}


def saber_model(art, fam, palette):
    """AA's saber hilt voxel with a glowing flame blade as HUD 10928-10930 show it: at the base about the hilt's
    width (1.2x), tapering steadily to 60 % and then to a point over the front 18 %, a flattened oval section, a pale-yellow core and orange edges
    (the 90th / 30th percentile by brightness of the HUD blade pixels); the blade is fullbright (glow map)."""
    k, src = aa_kvx(art, fam['kvx'])
    occ = k['grid'] >= 0
    rgb = k['palette'][np.clip(k['grid'], 0, 255)]
    px = []
    for tnum in fam['blade_tiles']:
        t = art.tile(tnum)
        if t is not None:
            c = art.palette[t[t != 255]].astype(int)
            warm = c[(c[:, 0] > 150) & (c[:, 0] > c[:, 2] + 40)]
            if len(warm):
                px.append(warm)
    c = np.concatenate(px) if px else np.array([[250, 200, 90]])
    lum = c.sum(1)
    edge = tuple(int(v) for v in np.median(c[lum <= np.percentile(lum, 30)], 0))
    core = tuple(int(v) for v in np.median(c[lum >= np.percentile(lum, 90)], 0))
    X, Yn, Z = occ.shape
    yz = np.argwhere(occ.any(0))
    hilt_w = float(min(np.ptp(yz[:, 0]), np.ptp(yz[:, 1])) + 1)
    n = int(round(X * 2.6))                        # blade in front of the hilt (muzzle side = -x)
    cy = (yz[:, 0].min() + yz[:, 0].max()) / 2
    cz = (yz[:, 1].min() + yz[:, 1].max()) / 2
    bocc = np.zeros((n + X, Yn, Z), bool)
    brgb = np.zeros((n + X, Yn, Z, 3), np.uint8)
    bocc[n:], brgb[n:] = occ, rgb
    blade = np.zeros_like(bocc)
    half = 0.6 * hilt_w                            # 1.2 x the hilt width at the base
    for x in range(n):
        u = (x + 1) / n                            # 0 at the tip, 1 at the hilt
        h = half * (0.6 + 0.4 * u) * min(1.0, u / 0.18)   # steady taper, pointed over the front 18 %
        for y in range(Yn):
            for z in range(Z):
                dy, dz = abs(y - cy), abs(z - cz)
                if (dz / max(h, 0.5)) ** 2 + (dy / max(0.7 * h, 0.5)) ** 2 <= 1.0 + 1e-6:   # flattened oval section
                    bocc[x, y, z] = blade[x, y, z] = True
                    brgb[x, y, z] = core if dz <= 0.5 * h else edge
    return bocc, brgb, src, dict(blade_edge_rgb=edge, blade_core_rgb=core, blade_tiles=list(fam['blade_tiles']),
                                 width_vs_hilt=1.2), blade


# ------------------------------------------------------------------ reuse (exact stock contract)
def rename_md3(src, dst, name):
    d = bytearray(Path(src).read_bytes())
    def put(off, text, n=64):
        b = text.encode('ascii')
        d[off:off + n] = b + bytes(n - len(b))
    put(8, name)
    osf = int.from_bytes(d[100:104], 'little', signed=True)
    put(osf + 4, name)
    osh = int.from_bytes(d[osf + 92:osf + 96], "little", signed=True)   # ofs_shaders
    put(osf + osh, f'{name}.png')
    Path(dst).write_bytes(bytes(d))


def same_contract(fid, weapon):
    a = md3_parts(V6 / 'exports/eduke32/aa' / f'{fid}.md3')
    b = md3_parts(V6 / 'exports/eduke32' / f'vr_{weapon}.md3')
    if a['frames'] != b['frames'] or a['tag_order'] != b['tag_order']:
        return False
    if any(not np.allclose(a['tags'][0][k], b['tags'][0][k], atol=1e-4) for k in a['tag_order']):
        return False
    fa = sorted(tuple(sh['shown']) for i, sh in enumerate(a['shells']) if i != a['body'])
    fb = sorted(tuple(sh['shown']) for i, sh in enumerate(b['shells']) if i != b['body'])
    return fa == fb


def hud_tiles(fid, fam):
    if fam.get('hud_tiles'):
        return list(fam['hud_tiles'])
    ref = next(f for f in inventory() if f['id'] == fid)['reference_tiles']
    return [ref[0], ref[0] + 1, ref[0] + 2]


def pickup_tile(art, fam):
    if fam.get('tile'):
        return fam['tile']
    if art is not None and fam.get('kvx'):
        for t, p in sorted(art.voxels().items()):
            if p.stem == fam['kvx']:
                return t
    return None


# ------------------------------------------------------------------ top-detail features (voxel edits in code)
def _pi(pal, rgb):
    return int(nearest_index(np.array([rgb], np.uint8), pal[:255])[0])   # 255: Build's transparent slot


def _top_profile(g):
    occ = g >= 0
    X = g.shape[0]
    top = np.array([np.nonzero(occ[x].any(0))[0].min() if occ[x].any() else 10 ** 6 for x in range(X)])
    return occ, top


def feat_sights(g, pal, rear=None, front=None, post=None, gap=2):
    """Rear sight (two posts with coloured dots facing the player) at the back of the top line and a front
    post (dot) at the muzzle end, standing above the slide like the HUD frames show."""
    occ, top = _top_profile(g)
    zt = int(top.min())
    line = np.nonzero(top <= zt + 1)[0]
    xf, xr = int(line.min()), int(line.max())
    ys = np.nonzero(occ[xr, :, top[xr]])[0]
    y0, y1 = int(ys.min()), int(ys.max())
    pc = _pi(pal, post) if post else int(g[xr, (y0 + y1) // 2, top[xr]])
    z = int(top[xr])
    if z < 2:
        return g, 'sights skipped (no room above)'
    for y in (y0, y1):
        g[xr - 2:xr, y, z - 2:z] = pc
        if rear:
            g[xr - 1, y, z - 2] = _pi(pal, rear)
    yc = (y0 + y1) // 2
    zf = int(top[xf])
    g[xf + 1:xf + 3, yc, zf - 2:zf] = pc
    if front:
        g[xf + 1, yc, zf - 2] = _pi(pal, front)
    return g, f'rear sight posts at x {xr - 2}-{xr - 1} (dots {rear}), front post at x {xf + 1} (dot {front})'


def feat_box(g, pal, box, colour):
    sl = tuple(slice(a, b + 1) for a, b in box)
    g[sl] = _pi(pal, colour)
    return g, f'box {box} {colour}'


def feat_paint(g, pal, box, colour, src=None):
    """Recolour the existing voxels in a box (optionally only those near colour src)."""
    sl = tuple(slice(a, b + 1) for a, b in box)
    sub = g[sl]
    m = sub >= 0
    if src is not None:
        c = pal[np.clip(sub, 0, 255)].astype(int)
        m &= np.abs(c - np.array(src)).sum(-1) < 90
    sub[m] = _pi(pal, colour)
    return g, f'paint {box} -> {colour}'


def feat_cyl(g, pal, x, yc, zc, r, colour, end=None):
    """Cylinder along x (scope tube, barrel), an optional end colour (lens)."""
    X, Y, Z = g.shape
    yy, zz = np.meshgrid(np.arange(Y), np.arange(Z), indexing='ij')
    disc = (yy - yc) ** 2 + (zz - zc) ** 2 <= r * r
    for xi in range(x[0], x[1] + 1):
        g[xi][disc] = _pi(pal, colour)
    if end:
        inner = (yy - yc) ** 2 + (zz - zc) ** 2 <= (r - 1) ** 2
        g[x[1]][inner] = _pi(pal, end)
    return g, f'cylinder x {x} r {r} at (y {yc}, z {zc}) {colour}'


def _bbox(g):
    idx = np.argwhere(g >= 0)
    return idx.min(0), idx.max(0)


def feat_top_dot(g, pal, xf, colour, n=2, dy=0, h=1):
    """A small raised block (n x n, h high) on the top surface at fraction xf of the length from the muzzle
    (LEDs, lights, lenses on top)."""
    lo, hi = _bbox(g)
    x = int(round(lo[0] + xf * (hi[0] - lo[0])))
    occ = g >= 0
    cols = np.nonzero(occ[x].any(1))[0]
    y = int(round((cols.min() + cols.max()) / 2)) + dy
    z = int(np.nonzero(occ[x, y])[0].min()) if occ[x, y].any() else int(lo[2])
    g[x:x + n, y - n // 2:y - n // 2 + n, z - h:z] = _pi(pal, colour)
    return g, f'raised {n}x{n} {colour} block on top at {xf:.2f} of the length'


def feat_back_dot(g, pal, zf, colour, n=2, dy=0):
    """Coloured voxels on the rear face (what the player looks at): lights, crescents."""
    lo, hi = _bbox(g)
    z = int(round(lo[2] + zf * (hi[2] - lo[2])))
    occ = g >= 0
    xs = np.nonzero(occ[:, :, z].any(1))[0]
    x = int(xs.max())
    ys = np.nonzero(occ[x, :, z])[0]
    y = int(round((ys.min() + ys.max()) / 2)) + dy
    g[x - 1:x + 1, y - n // 2:y - n // 2 + n, z - n // 2:z - n // 2 + n] = _pi(pal, colour)
    return g, f'{colour} lights on the rear face at {zf:.2f} of the height'


def feat_stripes(g, pal, x, z, a=(235, 190, 20), b=(24, 22, 20), w=2):
    """Diagonal hazard stripes painted on the existing surface voxels inside a box given as fractions of the
    model's length (x, from the muzzle) and height (z, from the top)."""
    lo, hi = _bbox(g)
    xs = [int(round(lo[0] + f * (hi[0] - lo[0]))) for f in x]
    zs = [int(round(lo[2] + f * (hi[2] - lo[2]))) for f in z]
    sub = g[xs[0]:xs[1] + 1, :, zs[0]:zs[1] + 1]
    X, Y, Z = np.indices(sub.shape)
    on = ((X + Z) // w) % 2 == 0
    m = sub >= 0
    sub[m & on] = _pi(pal, a)
    sub[m & ~on] = _pi(pal, b)
    return g, f'hazard stripes {a}/{b} over x {x}, z {z} (fractions)'


def feat_holo_sight(g, pal, xf, colour=(70, 72, 78), glass=(110, 150, 170), h=6, L=5):
    """A holographic / reflex sight on top (as the HUD frames show): a box frame (two side posts and a roof,
    a tinted glass voxel layer at its rear) standing on the top line at fraction xf of the length."""
    lo, hi = _bbox(g)
    x = int(round(lo[0] + xf * (hi[0] - lo[0])))
    occ = g >= 0
    zt = int(np.nonzero(occ[x].any(0))[0].min())
    ys = np.nonzero(occ[x, :, zt])[0]
    yc = int(round((ys.min() + ys.max()) / 2))
    hw = max(2, (int(ys.max() - ys.min()) + 3) // 2)
    c, gl = _pi(pal, colour), _pi(pal, glass)
    z0, z1 = zt - h, zt - 1
    if z0 < 0:
        return g, 'holo sight skipped (no room above)'
    g[x:x + L, yc - hw:yc + hw + 1, z1] = c                      # base
    g[x:x + L, yc - hw, z0:z1 + 1] = c                         # posts
    g[x:x + L, yc + hw, z0:z1 + 1] = c
    g[x:x + L, yc - hw:yc + hw + 1, z0] = c                    # roof
    g[x + L - 1, yc - hw + 1:yc + hw, z0 + 1:z1] = gl          # glass at the rear
    return g, f'reflex/holographic sight frame on top at {xf:.2f} of the length ({2 * hw + 1} wide, {h} high)'


def feat_mando_gauntlet(g, pal):
    """Mando's wrist blaster as HUD 20647-20650 show it, on the cut-off sleeve of AA's glove voxel (KVX: x grows
    toward the back / the player, -y is the outer (right) side, z down):
    - shroud: a big wedge plate 3 voxels thick, the gauntlet's width plus one voxel each side, over the top from
      40 % of the length (from the back) to the front, rising steadily to 40 % of the gauntlet's height above
      the top at the front edge and overhanging the front by 18 % of the length; the front edge is cut at an
      angle (outer corner further forward and higher), never a spike; light upper surface, mid-blue sides, a
      highlight on its upper edge, darker underside; closed on the inner side, open on the outer side;
    - mechanism: a dark cavity under the raised part on the outer side, a 6-voxel red lens (bright centre) set
      back in it facing out, grey and orange bits;
    - the open rear (where the forearm goes in) capped by a dark inner wall three voxels in;
    - plate ridges round the body and a round disc on the inner side, two blues with light edges."""
    from scipy import ndimage
    occ = g >= 0
    lo, hi = _bbox(g)
    x0, x1 = int(lo[0]), int(hi[0])
    L, H = x1 - x0 + 1, int(hi[2] - lo[2]) + 1
    ylo, yhi = int(lo[1]) - 1, int(hi[1]) + 1
    blue_l, blue_m, blue_d = _pi(pal, (74, 96, 200)), _pi(pal, (48, 64, 152)), _pi(pal, (26, 34, 92))
    edge = _pi(pal, (136, 156, 240))
    seam = _pi(pal, (22, 30, 80))
    dark, red, red_c = _pi(pal, (24, 24, 28)), _pi(pal, (205, 28, 18)), _pi(pal, (255, 150, 120))
    grey, orange = _pi(pal, (150, 150, 156)), _pi(pal, (200, 120, 50))
    top_at = {}
    for x in range(x0, x1 + 1):
        if occ[x].any():
            top_at[x] = int(np.nonzero(occ[x].any(0))[0].min())
    xb = x0 + int(0.6 * L)                          # back edge of the plate (40 % of the length from the back)
    ov = int(round(0.18 * L))                       # overhang past the front
    rise_max = 0.4 * H
    plate = {}                                      # (x, y) -> z of the plate's upper surface
    for y in range(ylo, yhi + 1):
        o = (yhi - y) / (yhi - ylo)                 # 0 inner, 1 outer
        xf = x0 - int(round(ov * (0.4 + 0.6 * o)))  # angled front edge: outer corner further forward
        for x in range(xf, xb + 1):
            t = (xb - x) / (xb - (x0 - ov))         # 0 at the back edge, 1 at the farthest front
            base = top_at.get(max(x, x0), top_at[x0])
            z = base - 1 - int(round(rise_max * t + 4 * o * t))     # rises to the front, outer corner higher
            plate[(x, y)] = z
    for (x, y), z in plate.items():
        g[x, y, z] = blue_l
        g[x, y, z + 1] = blue_m
        g[x, y, z + 2] = blue_d                     # darker underside
    for (x, y), z in plate.items():                 # highlight on the upper edge, mid-blue rim
        if any((x + dx, y + dy) not in plate for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
            g[x, y, z] = edge
    # the inner side is closed by a wall from the plate down to the gauntlet (a hood hinged there)
    for x in range(x0 - 2, xb + 1):
        for y in (yhi, yhi - 1):
            if (x, y) in plate:
                zt = top_at.get(max(x, x0), top_at[x0])
                g[x, y, plate[(x, y)] + 3:zt + 1] = blue_m
    # mechanism in the gap on the outer side: dark cavity set back two voxels, lens and parts on its face
    xa, xz = x0, x0 + int(0.3 * L)
    yface = ylo + 3
    for x in range(xa, xz + 1):
        for y in range(yface, int((ylo + yhi) / 2) + 1):
            if (x, y) in plate:
                zt = top_at.get(x, top_at[x0])
                if zt - (plate[(x, y)] + 3) >= 1:
                    g[x, y, plate[(x, y)] + 3:zt] = dark
    xc = (xa + xz) // 2
    zc = (plate.get((xc, yface), top_at[xc] - 6) + 3 + top_at[xc]) // 2 + 1
    for dx in range(-3, 4):
        for dz in range(-3, 4):
            r2 = dx * dx + dz * dz
            if r2 <= 9:
                g[xc + dx, yface - 2:yface, zc + dz] = red_c if r2 <= 1 else red     # stands out 2 voxels
    for dz in range(-1, 2):
        g[xc + 5, yface - 1, zc + dz] = grey
        g[xc - 5, yface - 1, zc + dz] = orange
    g[xc + 6, yface - 1, zc - 1:zc + 2] = grey
    # the open rear capped by a dark inner wall three voxels in
    outline = ndimage.binary_fill_holes(occ[x1 - 3:x1 + 1].any(0))
    wall = outline & ~occ[x1 - 3]
    g[x1 - 3][wall] = dark
    # plate ridges round the body behind the shroud, and the disc on the inner side
    for xr in (xb + 4, xb + 10, xb + 16):
        if xr >= x1 - 4:
            continue
        for y, z in np.argwhere(occ[xr]):
            for dy, dz in ((-1, 0), (1, 0), (0, -1)):
                if not occ[xr, y + dy, z + dz] and g[xr, y + dy, z + dz] < 0:
                    g[xr, y + dy, z + dz] = edge if dz < 0 else blue_l
        g[xr + 1][occ[xr + 1]] = seam
    xd, zd = x0 + int(0.45 * L), int(round((lo[2] + hi[2]) / 2)) + 2
    for x in range(xd - 5, xd + 6):
        for z in range(zd - 5, zd + 6):
            r = np.hypot(x - xd, z - zd)
            ys_ = np.nonzero(occ[x, :, z])[0]
            if not len(ys_) or r > 4.4:
                continue
            y = int(ys_.max())
            if r >= 3.0:
                g[x, y, z] = seam
            elif r < 1.6:
                g[x, y + 1, z] = edge
    return g, (f'wedge shroud plate (3 thick, gauntlet width + 1 each side) from 40 % of the length to the front, '
               f'rising to 40 % of the height at the front, overhanging {ov} voxels, front edge cut at an angle '
               '(outer corner forward and higher); light top, highlight edge, darker underside; closed on the '
               'inner side; dark mechanism cavity on the outer side with a 7-voxel red lens (bright centre), grey '
               'and orange parts; rear opening capped by a dark inner wall; plate ridges; disc on the inner side; '
               'the glove\'s fist and wrist cut off')


def _ramp_recolour(g, pal, mask, ramp):
    """Recolour the masked voxels with a ramp (dark -> light) by their current brightness rank."""
    idx = np.argwhere(mask)
    if not len(idx):
        return g
    lum = pal[np.clip(g[mask], 0, 255)].astype(int).sum(1)
    q = np.argsort(np.argsort(lum)) / max(len(lum) - 1, 1)
    steps = [_pi(pal, c) for c in ramp]
    g[tuple(idx.T)] = np.array(steps)[np.minimum((q * len(steps)).astype(int), len(steps) - 1)]
    return g


def _surface(g):
    occ = g >= 0
    P = np.pad(occ, 1)
    ex = np.zeros_like(occ)
    for a in range(3):
        for sft in (1, -1):
            ex |= occ & ~np.roll(P, sft, axis=a)[1:-1, 1:-1, 1:-1]
    return ex


def feat_dea_pistol(g, pal):
    """Dea's corrosive pistol as HUD 21970-21974 show it: grey metal, serrations along the top of the barrel,
    a glowing green cell in a window on the left side, a round double drum at the back with a dark strap,
    a blue hose loop by the muzzle; dark grip."""
    occ = g >= 0
    lo, hi = _bbox(g)
    L = hi[0] - lo[0]
    zb = lo[2] + int(0.45 * (hi[2] - lo[2]))      # body above, grip below
    body = occ.copy()
    body[:, :, zb + 1:] = False
    g = _ramp_recolour(g, pal, body, [(84, 86, 92), (122, 124, 130), (160, 162, 168), (200, 202, 206)])
    grip = occ & ~body
    g = _ramp_recolour(g, pal, grip, [(28, 28, 30), (44, 44, 48), (62, 62, 66)])
    surf = _surface(g)
    top = {x: int(np.nonzero(occ[x].any(0))[0].min()) for x in range(lo[0], hi[0] + 1) if occ[x].any()}
    dark = _pi(pal, (48, 48, 52))
    for x in range(lo[0] + 1, lo[0] + int(0.4 * L)):
        if (x - lo[0]) % 2 == 0 and x in top:
            row = g[x, :, top[x]]
            row[surf[x, :, top[x]]] = dark
    # green cell window on the left (+y) side
    x0, x1 = lo[0] + int(0.3 * L), lo[0] + int(0.6 * L)
    z0, z1 = lo[2] + 3, zb - 2
    gr, grl = _pi(pal, (120, 210, 50)), _pi(pal, (210, 250, 130))
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            ys = np.nonzero(occ[x, :, z])[0]
            if len(ys):
                g[x, ys.max(), z] = grl if (z - z0) == (z1 - z0) // 2 else gr
    # round double drum at the back: two cylinders along x side by side, a dark strap round them
    yc = (lo[1] + hi[1]) / 2
    zc = lo[2] + 0.55 * (zb - lo[2])
    r = 0.38 * (zb - lo[2]) + 1
    grey, strap = _pi(pal, (150, 152, 158)), _pi(pal, (56, 56, 60))
    xr0, xr1 = hi[0] - int(0.18 * L), hi[0]
    for x in range(xr0, xr1 + 1):
        for y in range(int(lo[1]) - 3, int(hi[1]) + 4):
            for z in range(int(lo[2]), zb + 1):
                for dy in (-0.45 * r, 0.45 * r):
                    if (y - yc - dy) ** 2 + (z - zc) ** 2 <= r * r:
                        g[x, y, z] = strap if x in (xr0 + 2, xr0 + 3) else grey
    # blue hose loop on the left side by the muzzle
    blue = _pi(pal, (40, 64, 176))
    xh = lo[0] + int(0.12 * L)
    ys = np.nonzero(occ[xh, :, zb - 1])[0]
    yh = int(ys.max()) + 1 if len(ys) else int(hi[1]) + 1
    for t in range(9):
        a = np.pi * t / 8
        g[xh + int(round(3 * np.cos(a))), yh, int(round(zb - 2 + 3 * np.sin(a)))] = blue
    return g, ('grey metal ramp on the body, dark grip; serrations (every 2nd voxel dark) on the front 40 % of the '
               'top; glowing green cell window on the left side (30-60 % of the length); round double drum at the '
               'back (two cylinders, dark strap); blue hose loop on the left by the muzzle')


def feat_annihilator(g, pal):
    """The Annihilator as HUD 21244-21246 show it: orange-yellow body, a dark grey housing on the rear top
    (v6's carry handle replaced), a red panel on top, white tips at the muzzle, dark vents and three silver
    ports on the right side, an orange drum low on the left front."""
    occ = g >= 0
    lo, hi = _bbox(g)
    L = hi[0] - lo[0]
    rows = np.nonzero(occ.any((0, 1)))[0]
    zt = int(np.nonzero(occ.sum((0, 1)) > 0.5 * occ.sum((0, 1)).max())[0].min())    # top of the main body
    g[:, :, :zt][occ[:, :, :zt]] = -1                 # v6's handle off
    occ = g >= 0
    g = _ramp_recolour(g, pal, occ, [(178, 88, 20), (222, 136, 36), (238, 172, 60), (246, 206, 110)])
    yc = int(round((lo[1] + hi[1]) / 2))
    hw = int((hi[1] - lo[1]) // 2)
    housing, edge = _pi(pal, (72, 72, 78)), _pi(pal, (128, 128, 134))
    xa = lo[0] + int(0.55 * L)
    g[xa:hi[0], yc - hw + 1:yc + hw, zt - 5:zt] = housing
    g[xa:hi[0], yc - hw + 1:yc + hw, zt - 5] = edge
    g[xa + 3:xa + 9, yc - 2:yc + 3, zt - 8:zt - 5] = housing                      # raised box on it
    red = _pi(pal, (210, 50, 20))
    g[lo[0] + int(0.3 * L):xa - 1, yc - hw + 2:yc + hw - 1, zt] = red
    white = _pi(pal, (238, 238, 232))
    for dy, dz in ((-3, 1), (0, -1), (3, 1)):
        g[lo[0] - 3:lo[0] + 1, yc + dy - 1:yc + dy + 2, zt + 2 + dz:zt + 5 + dz] = white
    vent, port, port_c = _pi(pal, (46, 36, 30)), _pi(pal, (200, 200, 206)), _pi(pal, (40, 40, 44))
    ylo = int(lo[1])
    for x in range(lo[0] + int(0.15 * L), lo[0] + int(0.28 * L)):
        if x % 2 == 0:
            g[x, ylo, zt + 2:zt + 6][g[x, ylo, zt + 2:zt + 6] >= 0] = vent
    for k_ in range(3):
        xc, zc = lo[0] + int((0.4 + 0.07 * k_) * L), zt + 9
        for x in range(xc - 2, xc + 3):
            for z in range(zc - 2, zc + 3):
                d = np.hypot(x - xc, z - zc)
                if d <= 2.4:
                    g[x, ylo - 1, z] = port if d > 1.2 else port_c
    drum = _pi(pal, (230, 120, 30))
    for x in range(lo[0], lo[0] + int(0.2 * L)):
        for y in range(yc, int(hi[1]) + 5):
            for z in range(zt + 6, int(hi[2]) + 2):
                if (y - (hi[1] + 1)) ** 2 + (z - (zt + 11)) ** 2 <= 16:
                    g[x, y, z] = drum
    return g, ('orange-yellow ramp on the body; v6 carry handle replaced by a dark grey housing on the rear top '
               'with a light top edge and a raised box; red panel on top; three white tips at the muzzle; dark '
               'vents and three silver ports on the right side; orange drum low on the left front')


def feat_dea_claw(g, pal):
    """Dea's energy claw as HUD 21919-21926 show it: a jagged blue crystal blade (light/dark blue, white
    glints) on a black claw mount with an orange band, worn on the hand (the hand itself is not modelled)."""
    occ = g >= 0
    lo, hi = _bbox(g)
    L = hi[0] - lo[0]
    xm = lo[0] + int(0.7 * L)                    # blade in front, mount behind
    blade = occ.copy()
    blade[xm:] = False
    g = _ramp_recolour(g, pal, blade, [(36, 60, 150), (70, 112, 210), (120, 170, 240), (200, 228, 255)])
    for x in range(lo[0], xm, 5):                 # jagged crystal edges
        col = np.nonzero(occ[x].any(0))[0]
        if len(col):
            g[x, :, col.min()][g[x, :, col.min()] >= 0] = -1
    mount = occ.copy()
    mount[:xm] = False
    g = _ramp_recolour(g, pal, mount, [(18, 18, 20), (30, 30, 34), (48, 48, 54)])
    g[xm:xm + 2][g[xm:xm + 2] >= 0] = _pi(pal, (214, 117, 48))
    zt = int(np.nonzero(occ[xm:].any((0, 1)))[0].min())
    g[xm + 2:hi[0] - 1, int(lo[1]):int(hi[1]) + 1, zt - 1] = _pi(pal, (64, 64, 70))
    return g, ('blade: crystal-blue ramp with white glints, a notch every 5 voxels on the top edge (jagged); mount: '
               'black, an orange band at the blade root, a dark grey plate on top')


def feat_cap_back(g, pal, colour=(70, 70, 74), depth=2):
    """Close an open back end (a hollow tube seen from the player) with a plate filling its outline."""
    from scipy import ndimage
    occ = g >= 0
    lo, hi = _bbox(g)
    xb = int(hi[0])
    outline = ndimage.binary_fill_holes(occ[xb - depth - 2:xb + 1].any(0))
    for x in range(xb - depth + 1, xb + 1):
        m = outline & ~occ[x]
        g[x][m] = _pi(pal, colour)
    return g, f'open back end capped ({depth} voxels, {colour})'


def feat_ribs(g, pal, x=(0.0, 0.6), colour=(150, 150, 156), every=2):
    """Serrations / a ventilated rib along the top: every `every`-th column of the top surface in the given
    length fractions (from the muzzle) lighter."""
    occ = g >= 0
    lo, hi = _bbox(g)
    x0, x1 = int(lo[0] + x[0] * (hi[0] - lo[0])), int(lo[0] + x[1] * (hi[0] - lo[0]))
    surf = _surface(g)
    c = _pi(pal, colour)
    for xi in range(x0, x1 + 1, every):
        if occ[xi].any():
            zt = int(np.nonzero(occ[xi].any(0))[0].min())
            row = g[xi, :, zt]
            row[surf[xi, :, zt]] = c
    return g, f'top rib serrations every {every} voxels over {x} of the length ({colour})'


def feat_top_panel(g, pal, x=(0.4, 0.7), colour=(90, 200, 60)):
    """Paint the top surface over a length range (screens, displays, lit panels)."""
    occ = g >= 0
    lo, hi = _bbox(g)
    x0, x1 = int(lo[0] + x[0] * (hi[0] - lo[0])), int(lo[0] + x[1] * (hi[0] - lo[0]))
    surf = _surface(g)
    c = _pi(pal, colour)
    yc = (lo[1] + hi[1]) / 2
    hw = (hi[1] - lo[1]) * 0.3
    for xi in range(x0, x1 + 1):
        if occ[xi].any():
            zt = int(np.nonzero(occ[xi].any(0))[0].min())
            for y in range(int(yc - hw), int(yc + hw) + 1):
                if surf[xi, y, zt]:
                    g[xi, y, zt] = c
    return g, f'top panel {colour} over {x} of the length'


def feat_side_scope(g, pal, x=(0.55, 0.8), r=3, side=1, colour=(60, 62, 66), lens=(110, 40, 30)):
    """A scope tube along the top edge on one side (side=+1: left), a coloured lens on its rear end facing the
    player (the HUD frames' big round lens)."""
    occ = g >= 0
    lo, hi = _bbox(g)
    x0, x1 = int(lo[0] + x[0] * (hi[0] - lo[0])), int(lo[0] + x[1] * (hi[0] - lo[0]))
    zt = int(np.nonzero(occ[x0:x1 + 1].any((0, 1)))[0].min())
    ys = np.nonzero(occ[x0:x1 + 1, :, zt:zt + 2 * r].any((0, 2)))[0]     # the body's width there
    yc = (ys.max() + r - 1) if side > 0 else (ys.min() - r + 1)
    zc = zt + r - 1
    X, Y, Z = g.shape
    yy, zz = np.meshgrid(np.arange(Y), np.arange(Z), indexing='ij')
    d2 = (yy - yc) ** 2 + (zz - zc) ** 2
    for xi in range(x0, x1 + 1):
        g[xi][d2 <= r * r] = _pi(pal, colour)
    g[x1][d2 <= (r - 1) ** 2] = _pi(pal, lens)
    return g, f'scope tube r {r} on the {"left" if side > 0 else "right"} top edge over {x}, lens {lens} at the rear'


def feat_recolour(g, pal, ramp, x=(0.0, 1.0), dark_only=True):
    """Recolour (by brightness rank) the voxels in a length range, optionally only the dark ones (a black body
    the HUD shows green, etc.)."""
    lo, hi = _bbox(g)
    x0, x1 = int(lo[0] + x[0] * (hi[0] - lo[0])), int(lo[0] + x[1] * (hi[0] - lo[0]))
    m = np.zeros(g.shape, bool)
    m[x0:x1 + 1] = g[x0:x1 + 1] >= 0
    if dark_only:
        c = pal[np.clip(g, 0, 255)].astype(int)
        m &= c.max(-1) < 90
    return _ramp_recolour(g, pal, m, ramp), f'{"dark " if dark_only else ""}voxels over {x} recoloured to {ramp}'


FEATURES = dict(side_scope=feat_side_scope, recolour=feat_recolour, cap_back=feat_cap_back, ribs=feat_ribs, top_panel=feat_top_panel, dea_pistol=feat_dea_pistol, annihilator=feat_annihilator, dea_claw=feat_dea_claw,
                mando_gauntlet=feat_mando_gauntlet, holo_sight=feat_holo_sight, sights=feat_sights, box=feat_box, paint=feat_paint, cyl=feat_cyl, top_dot=feat_top_dot,
                back_dot=feat_back_dot, stripes=feat_stripes)


FEATURE_PAD = 10


def apply_features(k, feats, art, fam):
    g = k['grid'].copy()
    pad = FEATURE_PAD                              # room above / around for raised parts
    g = np.pad(g, pad, constant_values=-1)
    notes = []
    for name, kw in feats:
        kw = dict(kw)
        for key in ('box', 'x'):
            if key in kw and name in ('box', 'paint', 'cyl'):
                v = kw[key]
                kw[key] = [(a + pad, b + pad) for a, b in v] if key == 'box' else (v[0] + pad, v[1] + pad)
        for key in ('yc', 'zc'):
            if key in kw and name == 'cyl':
                kw[key] = kw[key] + pad
        g, note = FEATURES[name](g, k['palette'], **kw)
        notes.append(note)
    occ = g >= 0
    solid = fill_solid(occ)
    from scipy import ndimage
    _, ind = ndimage.distance_transform_edt(~occ, return_indices=True)
    g = np.where(solid, g[tuple(ind)], -1).astype(np.int16)
    return dict(k, grid=g, solid=solid, size=g.shape), notes


def kit_juicer(art):
    """The juicer as HUD 17656-17659 show it: AA's spray-can pickup voxel (17660) laid along the top of a pistol
    body (Shelly's pistol voxel 7678) with its domed cap toward the player, a silver tube along the body ending
    in a brown cap under it, as the HUD frames show from behind."""
    from kitbash import Kit, Piece, Shape
    root = art.root / 'voxels' / 'AA_voxels'
    kit = Kit()
    body = Piece(root, '7678_pistolS')
    kit.paste(body, (0, 0, 0), 'body')
    can = Piece(root, '17660_spray').orient((2, 1, 0), flip=(0,))        # cap (top of the can) to the back
    X, Y, Z = can.shape
    kit.paste(can, (80 - X, 6 - Y // 2, -Z + 2), 'canister')
    occ = np.zeros((44, 9, 9), bool)
    rgb = np.zeros((44, 9, 9, 3), np.uint8)
    yy, zz = np.meshgrid(np.arange(9), np.arange(9), indexing='ij')
    disc = (yy - 4) ** 2 + (zz - 4) ** 2 <= 16
    occ[:, disc] = True
    rgb[:, disc] = (176, 176, 184)
    rgb[:6, disc & ((yy - 4) ** 2 + (zz - 4) ** 2 >= 9)] = (60, 90, 180)        # blue band near its front
    rgb[-2:, disc] = (120, 76, 44)                                              # brown cap toward the player
    kit.paste(Shape(occ, rgb, 'silver tube, blue band, brown cap'), (38, 6 - 4, 2), 'tube')
    return kit, ['AA spray-can voxel (17660) laid on top of the pistol body (7678) as the canister, its domed cap '
                 'to the back', 'silver tube along the body with a blue band and a brown end cap below the canister']


KITS = dict(juicer=kit_juicer)


def build_reuse(fid, fam):
    import shutil
    w = fam['weapon']
    src = ROOT / 'exports/eduke32' / f'vr_{w}.md3'
    if not src.is_file() or not same_contract(fid, w):
        return None
    OUT.mkdir(parents=True, exist_ok=True)
    rename_md3(src, OUT / f'{fid}.md3', fid)
    for ext in ('.png', '_glow.png'):
        if (src.with_name(f'vr_{w}{ext}')).is_file():
            shutil.copyfile(src.with_name(f'vr_{w}{ext}'), OUT / f'{fid}{ext}')
    rec = dict(name=fid, stem=fid, kind='reuse', md3=f'exports/eduke32/aa/{fid}.md3', reuses=f'exports/eduke32/vr_{w}.md3',
               hud_tiles=hud_tiles(fid, fam),
               hold_alias=f'hold_{w}', note='v6 AA file has the vanilla contract (frames, tags, effect frames)')
    (META / f'aa_{fid}.json').write_text(json.dumps(rec, indent=1))
    print(fid, 'reuse', w, flush=True)
    return rec


# ------------------------------------------------------------------ build one family
def build(fid, art, palette):
    fam = FAMILIES[fid]
    if fam['kind'] == 'reuse':
        return build_reuse(fid, fam)
    if art is None:                                # everything but the stock-weapon families needs the AA install
        return None
    con = contract(fid)
    spec = dict(kvx=None, **STD, support='v6')
    extra_rec = {}
    if fam['kind'] == 'aavox':
        k, src = aa_kvx(art, fam['kvx'])
        if fam.get('crop'):
            sl = tuple(slice(a, b + 1) for a, b in fam['crop'])
            g = k['grid'][sl]
            k = dict(k, grid=g, solid=fill_solid(g >= 0), size=g.shape)
        if fam.get('downsample'):                   # very fine voxels for a small item: 2x2x2 blocks
            from kitbash import Shape
            occ = k['grid'] >= 0
            sh = Shape(occ, k['palette'][np.clip(k['grid'], 0, 255)], 'aa voxel').downsample(fam['downsample'], occ_frac=0.4)
            k = grid_from_rgb(sh.occ, sh.rgb, palette)
        source = dict(aa_voxel=src, credit=CREDIT_AA)
        if fam.get('features'):
            k, notes = apply_features(k, fam['features'], art, fam)
            fam['_features'] = notes
    elif fam['kind'] == 'sprite':
        occ, rgb = sprite_model(art, fam, con, palette)
        if fam.get('lathe'):
            fam['_features'] = [f"side tile lathed round its {'vertical' if fam['lathe'] == 'z' else 'long'} axis"] + \
                (['16 spikes in two rings round the top end and one on top (HUD 13006/13007)'] if fam.get('spikes') else [])
        if fam.get('downsample'):
            from kitbash import Shape
            sh = Shape(occ, rgb, 'sprite voxels').downsample(fam['downsample'], occ_frac=0.4)
            occ, rgb = sh.occ, sh.rgb
        if fam.get('spikes'):
            occ, rgb = add_spikes(occ, rgb)
        k = grid_from_rgb(occ, rgb, palette)
        source = dict(aa_tile=fam['tile'], method=f"lathe {fam['lathe']}" if fam.get('lathe') else 'extruded side view',
                      credit=CREDIT_AA)
    elif fam['kind'] == 'v6vox':
        k = v6_grid(con, palette)
        source = dict(v6=f'v6-original/exports/eduke32/aa/{fid}.md3 (voxelised as the starting volume)',
                      hud_tiles=fam.get('hud_tiles'), credit=CREDIT_AA)
        if fam.get('features'):
            k, notes = apply_features(k, fam['features'], art, fam)
            fam['_features'] = ['v6 shape voxelised (no side view of it in AA)'] + notes
    elif fam['kind'] == 'kit':
        kit, notes = KITS[fid](art)
        k = kit.grid(palette)
        source = dict(kitbash=[dict(p_) for p_ in kit.pieces], credit=CREDIT_AA)
        fam['_features'] = notes
    elif fam['kind'] == 'saber':
        occ, rgb, src, extra_rec, blade = saber_model(art, fam, palette)
        k = grid_from_rgb(occ, rgb, palette)
        spec['glow_mask'] = blade                   # the blade is fullbright
        fam['_features'] = ['flame blade: 1.2x the hilt width at the base, tapering to 60 % then to a point, oval section, '
                            f"pale-yellow core {extra_rec['blade_core_rgb']} and orange edges {extra_rec['blade_edge_rgb']} "
                            'from the HUD blade pixels; fullbright (glow map)']
        source = dict(aa_voxel=src, blade=extra_rec, credit=CREDIT_AA)
    else:
        return build_v6(fid, con, palette)
    solid = k['solid']
    # scale as build_weapons will: v6 body length along X (or the family's own length)
    idx = np.argwhere(solid)
    sa = fam.get('scale_axis', 0)                  # MD3 axis the length applies to (0 x, 2 z)
    n_a = np.ptp(idx[:, sa]) + 1
    v6i = BW.v6_info(fid, con['path'])
    s = (fam.get('length_m') or (v6i['maxs'][sa] - v6i['mins'][sa])) / n_a
    spec['scale_axis'] = sa
    if fam.get('palm_front'):                      # worn: the hand sits palm_front metres ahead of the front, centred
        lo_, hi_ = idx.min(0), idx.max(0)
        front = idx[idx[:, 0] <= lo_[0] + 2]
        spec['palm_grid'] = (lo_[0] - fam['palm_front'] / s, (lo_[1] + hi_[1] + 1) / 2, front[:, 2].mean() + 0.5)
        spec['grip'] = {'x': (int(lo_[0]), int(lo_[0]) + 3)}
    elif fam.get('grip'):                          # given in the voxel file's indices
        sh_ = FEATURE_PAD if fam.get('features') else 0
        spec['grip'] = {a: (v[0] + sh_, v[1] + sh_) for a, v in fam['grip'].items()}
    else:
        sg = solid
        if fam.get('grip_y'):                      # twin weapons: look for the grip on one of them only
            sg = solid.copy()
            ylo, yhi = fam['grip_y']
            sg[:, :ylo] = False
            sg[:, yhi + 1:] = False
        spec['grip'], _ = auto_grip(sg, s, con)
        if fam.get('grip_y'):
            spec['grip']['y'] = tuple(fam['grip_y'])
    tb = fam.get('trigger') or auto_trigger(solid, s, spec, con, fid)
    if tb:
        spec['trigger'] = tb
    if fam.get('grip_axis'):
        spec['grip_axis'] = fam['grip_axis']
    flashes = {}
    if con['flash']:
        # one blocky flash shell at the muzzle, shown in the frames where v6 shows its first effect
        flashes = {'flash': next(iter(con['flash'].values()))}
    motion = {f: (A, t) for f, (A, t, err) in con['motion'].items()}
    rec = BW.build(fid, spec=spec, k=k, flashes=flashes, collapsed=con['collapsed'], source=source,
                   v6_path=con['path'], stem=fid, sub='aa', meta_name=f'aa_{fid}', body_motion=motion,
                   scale_m=fam.get('length_m'))
    rec.update(kind=fam['kind'], solve_hold=True, hold=dict(rec.get('hold') or {}, name=fid),
               motion_frames=sorted(con['motion']), effect_frames=con['flash'],
               hud_tiles=hud_tiles(fid, fam), pickup_tile=pickup_tile(art, fam), top_features=fam.get('_features', []))
    (META / f'aa_{fid}.json').write_text(json.dumps(rec, indent=1))
    return rec


def v6_grid(con, palette):
    """The v6 body voxelised (voxelise.py, its own texture colours) as a read_kvx-like grid in the KVX
    convention build_weapons expects (muzzle toward -x, left +y, z down: every MD3 axis flipped)."""
    from PIL import Image
    from voxelise import voxelise
    info = con['info']
    body = info['shells'][info['body']]
    P = info['X'][0]
    T = info['tris'][body['tris']]
    tex = np.array(Image.open(con['path'].with_suffix('.png')).convert('RGBA'))
    Lx = con['body_hi'][0] - con['body_lo'][0]
    n = np.interp(Lx, [0.05, 0.3, 0.8, 1.1], [20, 40, 84, 92])
    s = float(np.clip(Lx / n, 0.003, 0.013))
    vb = voxelise(P, T, info['st'], tex, None, s, palette)
    occ = vb['solid'][::-1, ::-1, ::-1]
    rgb = vb['rgb'][::-1, ::-1, ::-1]
    return grid_from_rgb(np.ascontiguousarray(occ), np.ascontiguousarray(rgb), palette)


def build_v6(fid, con, palette):
    """Voxelise the v6 model itself (no AA art to build from), keeping its tags exactly."""
    from PIL import Image
    from voxelise import voxelise
    from voxmesh import mesh_parts, signed_volume, weld_check, save_png
    from md3io import write_md3
    info = con['info']
    body = info['shells'][info['body']]
    P = info['X'][0]
    T = info['tris'][body['tris']]
    tex = np.array(Image.open(con['path'].with_suffix('.png')).convert('RGBA'))
    gp = con['path'].with_name(con['path'].stem + '_glow.png')
    glow = np.array(Image.open(gp).convert('RGBA')) if gp.is_file() else None
    Lx = con['body_hi'][0] - con['body_lo'][0]
    n = np.interp(Lx, [0.05, 0.3, 0.8, 1.1], [20, 40, 84, 92])
    s = float(np.clip(Lx / n, 0.003, 0.013))
    vb = voxelise(P, T, info['st'], tex, glow, s, palette)
    parts = [dict(solid=vb['solid'], rgb=vb['rgb'], glow=vb['glow'], A=vb['A'])]
    frames = con['frames']
    m = mesh_parts(parts)
    pos = m['pos']
    nv = len(pos)
    tags = [{k_: tuple(info['tags'][f][k_] * 64) for k_ in info['tag_order']} for f in range(len(frames))]
    frames_pos = []
    for f, fr in enumerate(frames):
        Q = pos.copy()
        if fr in con['collapsed']:
            Q[:] = con['info']['shells'][con['info']['body']]['centre'][f] * 64
        elif fr in con['motion']:
            A, t, _ = con['motion'][fr]
            Q = Q @ A.T + t * 64
        frames_pos.append(Q)
    # flash: a blocky shell at v6 tag_muzzle, in v6's first effect's frames
    if con['flash']:
        fl = BW.flash_part(con['tags']['tag_muzzle'], 0.03, ((255, 250, 210), (255, 150, 30)), s)
        m = mesh_parts(parts + [fl])
        pos = m['pos']
        v0, v1 = m['part_ranges'][1]
        shown = next(iter(con['flash'].values()))
        frames_pos = []
        for f, fr in enumerate(frames):
            Q = pos.copy()
            b0, b1 = m['part_ranges'][0]
            if fr in con['collapsed']:
                Q[b0:b1] = con['info']['shells'][con['info']['body']]['centre'][f] * 64
            elif fr in con['motion']:
                A, t, _ = con['motion'][fr]
                Q[b0:b1] = Q[b0:b1] @ A.T + t * 64
            if fr not in shown:
                Q[v0:v1] = (con['tags']['tag_muzzle'] - np.array([0.012, 0, 0])) * 64
            frames_pos.append(Q)
    OUT.mkdir(parents=True, exist_ok=True)
    surf = dict(name=fid, shader=f'{fid}.png', tris=m['tris'], st=m['st'], pos=frames_pos, nrm=[m['nrm']] * len(frames))
    size = write_md3(OUT / f'{fid}.md3', fid, frames, [surf], tags)
    save_png(m['tex'], OUT / f'{fid}.png')
    save_png(m['glow'], OUT / f'{fid}_glow.png')
    rec = dict(name=fid, stem=fid, kind='v6', md3=f'exports/eduke32/aa/{fid}.md3',
               source='v6-original/exports/eduke32/aa (voxelised; no AA side-view art for this family)',
               voxelise=vb['stats'], verts=int(len(m['st'])), tris=int(len(m['tris'])), md3_bytes=size,
               signed_volume_units3=round(signed_volume(m['pos'], m['tris']), 1), weld=weld_check(m['pos'], m['tris']),
               solve_hold=False, hold=dict(name=fid), note='hold: v6 hold_<id> (shape follows v6 within a voxel)')
    (META / f'aa_{fid}.json').write_text(json.dumps(rec, indent=1))
    print(fid, 'v6 voxelised', rec['verts'], 'verts', vb['stats'], flush=True)
    return rec


def main():
    args = dict(a.split('=', 1) for a in sys.argv[1:])
    install = aaart.find_install(args.get('aa') or os.environ.get('EDUKE32_AA_INSTALL'))
    art = aaart.Art(install) if install else None
    if art is None:
        print('build_aa: no Alien Armageddon install found; only the stock-weapon families are built', flush=True)
    palette = read_kvx(ROOT / 'source/voxels/weapons/21_PISTOL.kvx')['palette']
    META.mkdir(parents=True, exist_ok=True)
    ids = [f['id'] for f in inventory()] if args.get('ids', 'all') == 'all' else args['ids'].split(',')
    done = {}
    for fid in ids:
        if fid not in FAMILIES:
            print('build_aa: no recipe for', fid, flush=True)
            continue
        rec = build(fid, art, palette)
        if rec:
            done[fid] = rec.get('kind', FAMILIES[fid]['kind'])
    (ROOT / 'metadata' / 'aa_models.json').write_text(json.dumps(dict(install=str(install) if install else None,
                                                                     families=done), indent=1))


if __name__ == '__main__':
    main()
