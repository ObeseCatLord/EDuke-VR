#!/usr/bin/env python3
"""Voxel hands: the generic Duke shells and one pair per Alien Armageddon character.

python3 -I build_hands.py [chars=duke|all|duke,bombshell,...] [wrist=1]

The Alien Armageddon characters are experimental and paused (build_voxel_pack.py --aa-experimental).

Source: v7-original/exports/eduke32/hands/vr_hand_right_shell{,_wrist}.md3/.skin, the single-shell hand
vr.cpp's skinHandShell poses (one surface, frame `bind`, every vertex on <= 2 joints with its position in each
joint's local frame, model units; up to 16384 vertices). Per character:

 1. reshape the smooth v7 shell in its joint frames (same skeleton, so skinning and the holds still work):
    finger width and depth, the back of the hand (the palm side is kept, so a hold's finger contact is
    unchanged), palm width (fingers move in with it), wrist and a smoothly tapered forearm / sleeve, rounded
    fingertips; then offsets along the normals for plates, cuffs and bangles. Duke stays chunky, with the
    forearm taper of Voxel Duke's own forearm gibs; Bombshell is slender (narrower palm and wrist, slimmer
    normal-length fingers); Mando has a bulky glove with a knuckle plate and a blue armour sleeve with soft
    folds; Wes has big gloves and a heavy coat sleeve with a folded cuff and straps; Dea Nova has opera
    gloves, an olive forearm and two bangles.
 2. voxelise that shape in the bind pose (2.5-4.5 mm: the finest that fits the vertex cap; the forearm is
    decided per 2x2x2 block), one closed shell, a rounded knuckle block at each strongly bending joint,
    touching fingers pulled one voxel apart.
 3. rigid per-bone skin: each voxel belongs to one joint (the nearest bind-pose bone segment among the
    joints whose plane it lies past); a vertex's two joints and weight come from the voxels within two voxels
    of it (100 % inside a bone, 75/25 then 50/50 across a joint), and cells in a joint's blend zone mesh as
    single voxels so the bend shows as a short smooth stretch.
 4. colour every voxel by region (glove / skin / nail / knuckle plate / seam / cuff / sleeve / fold / strap /
    bangle) in five clean light bands from the surface normal, glossy highlight streaks on glove leather.
    Duke's skin is the ramp of Voxel Duke's own skin voxels (forearm gibs and the standing Duke, read from
    the mod at build time); the AA characters' colours are constants chosen by looking at their AA HUD hand
    sprites (no sprite pixels are read).
The left hand is the exact mirror of the right (as in v7).

Writes exports/eduke32/hands/vr_hand_<side>_shell.* (Duke; _wrist with wrist=1) and metadata/assets/duke_hands.json;
with AA characters also exports/eduke32/characters/<name>/hands/vr_hand_<side>_shell.* and metadata/characters.json.
"""
import json, os, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('EDUKE32_VOXEL_PACK', HERE.parent))
ASSETS = Path(os.environ.get('EDUKE32_VR_ASSETS', ROOT.parent))
sys.path.insert(0, str(HERE))
from md3np import read  # noqa: E402
from md3io import write_md3  # noqa: E402
from voxmesh import signed_volume, weld_check, save_png  # noqa: E402
from voxelise import umeyama  # noqa: E402
from kitbash import nearest_index  # noqa: E402
from kvx import read_kvx  # noqa: E402

SRC = ASSETS / 'v7-original' / 'exports' / 'eduke32' / 'hands'
EXP = ROOT / 'exports' / 'eduke32'
FINGER = {7: 'index', 8: 'index', 9: 'index', 12: 'middle', 13: 'middle', 14: 'middle',
          17: 'ring', 18: 'ring', 19: 'ring', 22: 'little', 23: 'little', 24: 'little',
          2: 'thumb', 3: 'thumb', 4: 'thumb'}
DISTAL = {4, 9, 14, 19, 24}
PROXIMAL = {7, 12, 17, 22, 3}
KNUCKLE_X = {'index': -0.026 * 1.12, 'middle': -0.007 * 1.12, 'ring': 0.012 * 1.12, 'little': 0.029 * 1.12, 'thumb': 0.0}
U = 64.0                             # model units per metre

# ---- per-character shape (scale factors; lengths in metres) and colour ramps (dark, mid, light).
# Colours: chosen by looking at / measuring AA 5.66's first-person HUD hand sprites (Duke 2564/2565/2571,
# Bombshell 7679/7778/7779, Wes 19456/19459/19461, Mando 20711/20713/20714, Dea Nova 21973/22004), then
# snapped to the Duke Nukem 3D palette. Only these constants are used; the builder never reads AA.
SKIN_DUKE = ((141, 85, 56), (174, 121, 84), (196, 156, 116))
CHARS = {
    'duke': dict(pchar=0, label='Duke Nukem', look='bare, chunky tanned hands and forearms (AA Duke HUD)',
                 shape=dict(), regions=dict(hand=SKIN_DUKE, nail=((180, 140, 104), (204, 170, 132), (222, 190, 150)),
                                            forearm=SKIN_DUKE, cuff=SKIN_DUKE)),
    'bombshell': dict(pchar=1, label='Bombshell (Shelly)',
                      look='slender female hands: narrower palm and wrist, slim normal-length fingers; black leather '
                           'gloves to the wrist with a grey seam on the back and a thin rolled cuff; bare tan forearm, '
                           'smoothly tapered',
                      shape=dict(palm_w=0.87, palm_back=0.82, palm_front=0.95, finger_w=0.84, finger_back=0.82,
                                 finger_front=0.97, thumb_w=0.86, wrist=0.78, forearm=0.88,
                                 bands=[(0.000, 0.016, 0.0)]),
                      regions=dict(hand=((4, 4, 8), (14, 12, 14), (34, 32, 32)), seam=((56, 52, 48), (76, 72, 68), (96, 92, 88)),
                                   cuff=((16, 12, 16), (40, 36, 36), (64, 60, 56)),
                                   forearm=((166, 112, 76), (196, 146, 106), (214, 178, 141)))),
    'wes': dict(pchar=2, label='Wes',
                look='big male hands in rough charcoal gloves; heavy dark coat sleeve with a folded cuff and two straps',
                shape=dict(palm_w=1.06, palm_back=1.10, finger_w=1.06, finger_back=1.10, thumb_w=1.06, wrist=1.25,
                           forearm=1.40, bands=[(0.010, 0.040, 0.006), (0.075, 0.087, 0.003), (0.140, 0.152, 0.003)]),
                regions=dict(hand=((16, 12, 16), (34, 32, 28), (64, 60, 56)), cuff=((24, 20, 20), (44, 40, 36), (68, 62, 56)),
                             forearm=((20, 18, 18), (36, 34, 32), (60, 56, 52)), strap=((52, 44, 36), (76, 66, 54), (100, 88, 72)))),
    'mando': dict(pchar=3, label='Mando',
                  look='armoured soldier: bulky dark charcoal tactical gloves with a raised dark-grey knuckle plate, blue '
                       'armour sleeve moderately wider than the forearm with soft darker-blue folds',
                  shape=dict(palm_w=1.08, palm_back=1.18, finger_w=1.08, finger_back=1.14, thumb_w=1.08, wrist=1.12,
                             forearm=1.18, bands=[(0.000, 0.030, 0.004)],
                             folds=[(0.045, 0.007), (0.095, 0.007), (0.150, 0.007)]),
                  regions=dict(hand=((14, 14, 16), (26, 26, 30), (46, 46, 52)), armour=((34, 36, 42), (48, 50, 58), (64, 66, 74)),
                               plate_edge=((84, 86, 94), (96, 98, 106), (110, 112, 120)),
                               cuff=((24, 32, 64), (36, 46, 90), (64, 84, 150)), forearm=((24, 32, 64), (36, 46, 90), (60, 78, 140)),
                               fold=((16, 20, 44), (22, 28, 58), (32, 42, 84)))),
    'deanova': dict(pchar=4, label='Dea Nova',
                    look='slim alien woman: long black opera gloves over the hand and wrist, lime-olive skin on the forearm, '
                         'two stacked orange bangles',
                    shape=dict(palm_w=0.88, palm_back=0.84, palm_front=0.95, finger_w=0.84, finger_back=0.84, finger_front=0.97,
                               thumb_w=0.87, wrist=0.80, forearm=0.88,
                               bands=[(0.068, 0.078, 0.005), (0.081, 0.091, 0.005)]),
                    regions=dict(hand=((10, 10, 10), (22, 22, 22), (42, 44, 38)), cuff=((10, 10, 10), (22, 22, 22), (42, 44, 38)),
                                 forearm=((72, 85, 44), (118, 148, 70), (153, 194, 97)),
                                 bangle=((165, 80, 0), (214, 117, 48), (230, 150, 72)))),
}
GLOVE_END = dict(duke=None, bombshell=0.016, wes=0.010, mando=0.000, deanova=0.050)   # m past the wrist joint


# ------------------------------------------------------------------ source
def read_skin(path):
    rows = Path(path).read_text().split('\n')
    n = int(rows[0].split()[2])
    v = np.array([[float(x) for x in r.split()] for r in rows[1:1 + n]])
    return dict(j0=v[:, 0].astype(int), w=v[:, 1], l0=v[:, 2:5], j1=v[:, 5].astype(int), l1=v[:, 6:9])


def bind_skeleton(P, skin):
    """Rigid bind transform (R, t) of every joint the skin uses, recovered from its vertices (P = R l + t)."""
    B = {}
    for j in sorted(set(skin['j0']) | set(skin['j1'])):
        L = np.concatenate([skin['l0'][skin['j0'] == j], skin['l1'][skin['j1'] == j]])
        Q = np.concatenate([P[skin['j0'] == j], P[skin['j1'] == j]])
        c, R, t = umeyama(L[None], Q[None])
        B[j] = (R[0], t[0])
    return B


def source(variant):
    m = read(SRC / f'vr_hand_right_shell{variant}.md3')
    s = m['surfaces'][0]
    P = s['xyz'][0].astype(float)                 # model units
    skin = read_skin(SRC / f'vr_hand_right_shell{variant}.skin')
    return dict(P=P, tris=s['tris'].astype(np.int64), skin=skin, B=bind_skeleton(P, skin))


# ------------------------------------------------------------------ reshape
def reshape_local(j, l, sh):
    l = l.copy()
    x, y, z = l[:, 0], l[:, 1], l[:, 2]
    if j in FINGER:
        f = FINGER[j]
        w = sh.get('thumb_w' if f == 'thumb' else 'finger_w', 1.0)
        back = sh.get('finger_back', 1.0)
        front = sh.get('finger_front', 1.0)
        x2 = x * w + (sh.get('palm_w', 1.0) - 1.0) * KNUCKLE_X[f] * U
        y2 = np.where(y > 0, y * back, y * front)
        z2 = z
        if j in DISTAL:
            z2 = np.where(z < 0, z * sh.get('tip', 1.0), z)
        return np.stack([x2, y2, z2], 1)
    if j == 1:                                     # wrist joint: palm (z < 0) and forearm (z > 0)
        t = np.clip((z + 0.012 * U) / (0.024 * U), 0, 1)       # 0 in the palm, 1 past the wrist
        pw, fa = sh.get('palm_w', 1.0), sh.get('forearm', 1.0)
        wr = sh.get('wrist', fa)
        u = np.clip(z / (0.12 * U), 0, 1)           # wrist -> forearm: a smooth taper over 12 cm
        girth = wr + (fa - wr) * u * u * (3 - 2 * u)
        sx = pw * (1 - t) + girth * t
        back = sh.get('palm_back', 1.0) * (1 - t) + girth * t
        front = sh.get('palm_front', 1.0) * (1 - t) + girth * t
        x2 = x * sx
        y2 = np.where(y > 0, y * back, y * front)
        return np.stack([x2, y2, z], 1)
    return l


def reshape(src, sh):
    sk, B = src['skin'], src['B']
    out = np.zeros_like(src['P'])
    l0n = np.zeros_like(sk['l0'])
    l1n = np.zeros_like(sk['l1'])
    for j in B:
        a = sk['j0'] == j
        l0n[a] = reshape_local(j, sk['l0'][a], sh)
        b = sk['j1'] == j
        l1n[b] = reshape_local(j, sk['l1'][b], sh)
    # rounded fingertips: the source's tip apex is a cone point 8 mm past its last ring; pull it back to a
    # low dome over the ring (0.4 of the ring radius)
    for j in DISTAL:
        own = (sk['j0'] == j) & (sk['w'] > 0.99)
        L = l0n[own]
        r = np.hypot(L[:, 0], L[:, 1])
        apex = (r < 0.05) & (L[:, 2] < 0)
        ring = ~apex & (L[:, 2] < 0)
        if apex.any() and ring.any():
            zr = L[ring, 2].min()
            rr = np.median(r[ring & (L[:, 2] < zr + 0.05)])
            idx = np.nonzero(own)[0][apex]
            l0n[idx, 2] = zr - 0.4 * rr
            l1n[idx] = l0n[idx] if (sk['j1'][idx] == j).all() else l1n[idx]
    for i in range(len(out)):
        R0, t0 = B[sk['j0'][i]]
        R1, t1 = B[sk['j1'][i]]
        out[i] = sk['w'][i] * (R0 @ l0n[i] + t0) + (1 - sk['w'][i]) * (R1 @ l1n[i] + t1)
    return out


# ------------------------------------------------------------------ regions and colours
def cell_region(src, joints, jw, pts, name):
    """Region label per voxel centre (pts, model units) from the joint that dominates the nearest source
    surface point and the position in that joint's / the wrist's frame."""
    B = src['B']
    reg = CHARS[name]['regions']
    glove_end = GLOVE_END[name]
    bands = CHARS[name]['shape'].get('bands', [])
    R1, t1 = B[1]
    lw = (pts - t1) @ R1 / U                       # wrist frame, metres: z < 0 hand, z > 0 forearm
    jd = np.array(joints)[np.argmax(jw, 1)]
    out = np.empty(len(pts), dtype=object)
    for i in range(len(pts)):
        j = jd[i]
        x, y, z = lw[i]
        if j in FINGER:
            R, t = B[j]
            l = R.T @ (pts[i] - t) / U
            if j in DISTAL and l[1] > 0.002 and l[2] < -0.012 and 'nail' in reg:
                out[i] = 'nail'
            else:
                out[i] = 'hand'
            continue
        if z < 0:
            if name == 'mando' and y > 0.004 and -0.10 < z < -0.07:
                out[i] = 'plate_edge' if z < -0.096 else 'armour'      # knuckle plate, light front edge
            elif name == 'bombshell' and y > 0.004 and abs(x + 0.002) < 0.0035 and -0.085 < z < -0.012:
                out[i] = 'seam'
            else:
                out[i] = 'hand'
            continue
        band = next((k for k, (z0, z1, h) in enumerate(bands) if z0 <= z <= z1), None)
        if name == 'deanova' and band is not None:
            out[i] = 'bangle'
        elif name == 'wes' and band is not None and band > 0:
            out[i] = 'strap'
        elif name == 'mando' and any(abs(z - (zf + 0.006 * np.sin(2 * np.arctan2(x, y) + k))) < w / 2
                                     for k, (zf, w) in enumerate(CHARS[name]['shape'].get('folds', []))):
            out[i] = 'fold'                        # soft wavy folds in the sleeve
        elif glove_end is not None and z <= glove_end:
            out[i] = 'cuff' if (z > glove_end - 0.012 or name == 'bombshell') else 'hand'
        else:
            out[i] = 'forearm'
    return out.astype(str)


LIGHT = np.array([0.25, 1.0, -0.35]) / np.linalg.norm([0.25, 1.0, -0.35])   # bind frame: back of hand, toward the tips


GLOSS = dict(bombshell=(104, 100, 100), deanova=(80, 80, 76), wes=(76, 72, 66))   # leather highlights


def colours(regions, cell_idx, normals, name, palette):
    """Clean shading bands, no dither: five steps from each region's ramp (dark, dark-mid, mid, mid-light,
    light) chosen by the baked light (surface normal against a light over the back of the hand and toward
    the tips); glossy glove leather gets a highlight band where the light hits it squarely."""
    reg = CHARS[name]['regions']
    lam = normals @ LIGHT
    band = np.digitize(lam, [-0.45, -0.1, 0.3, 0.65])
    rgb = np.zeros((len(regions), 3), np.uint8)
    for r in set(regions):
        ramp = reg.get(r, reg['hand'])
        if len(ramp) == 5:                         # five explicit band colours (Duke: from Voxel Duke's skin)
            steps = np.array(ramp, np.uint8)
        else:
            d, m_, l_ = (np.array(c, float) for c in ramp)
            steps = np.array([d, (d + m_) / 2, m_, (m_ + l_) / 2, l_]).round().astype(np.uint8)
        sel = regions == r
        rgb[sel] = steps[band[sel]]
        if r == 'hand' and name in GLOSS:
            g = sel & (lam > 0.97)           # only where the leather turns into the light: streaks
            rgb[g] = GLOSS[name]
    return palette[nearest_index(rgb, palette)]


# ------------------------------------------------------------------ normal offsets (plates, cuffs, bangles)
OFFSETS = {   # (region in the wrist frame: z range m, dorsal only, offset m along the normal)
    'bombshell': [((0.000, 0.016), False, 0.0015)],
    'wes': [((0.008, 0.040), False, 0.004)],
    'mando': [((-0.100, -0.068), True, 0.004), ((0.000, 0.030), False, 0.003)],
    'deanova': [((0.066, 0.093), False, 0.004)],
}


def vertex_normals(P, tris):
    n = np.zeros_like(P)
    fn = np.cross(P[tris[:, 1]] - P[tris[:, 0]], P[tris[:, 2]] - P[tris[:, 0]])
    for k in range(3):
        np.add.at(n, tris[:, k], fn)
    return n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12)


def offset(src, P, tris, name):
    R1, t1 = src['B'][1]
    lw = (P - t1) @ R1 / U
    N = vertex_normals(P, tris)
    out = P.copy()
    for (z0, z1), dorsal, h in OFFSETS.get(name, []):
        m = (lw[:, 2] >= z0) & (lw[:, 2] <= z1)
        if dorsal:
            m &= lw[:, 1] > 0.004
        out[m] += N[m] * h * U
    return out


# ------------------------------------------------------------------ voxels
MAX_VERTS = 16384                    # vr.cpp: "skin 1 <n>", n <= 16384
CHILD = {2: 3, 3: 4, 7: 8, 8: 9, 12: 13, 13: 14, 17: 18, 18: 19, 22: 23, 23: 24}
CHAIN = {**{j: 'thumb' for j in (2, 3, 4)}, **{j: f for f, js in (('index', (7, 8, 9)), ('middle', (12, 13, 14)),
                                                                   ('ring', (17, 18, 19)), ('little', (22, 23, 24))) for j in js}}


def bone_segments(src, P):
    """Bind-pose bone of every joint as a segment (model units): joint origin -> child origin; the last bone
    of a finger runs to the fingertip; the wrist's runs from the end of the forearm through the wrist to the
    middle of the knuckles."""
    B, sk = src['B'], src['skin']
    seg = {}
    for j, (R, t) in B.items():
        if j in CHILD:
            seg[j] = [(t, B[CHILD[j]][1])]
        elif j in DISTAL:
            own = (sk['j0'] == j) & (sk['w'] > 0.5)
            L = max(float(-((P[own] - t) @ R[:, 2]).min()), 0.01 * U) if own.any() else 0.02 * U
            seg[j] = [(t, t - R[:, 2] * L)]
    R1, t1 = B[1]
    lw = (P - t1) @ R1
    far = t1 + R1[:, 2] * lw[:, 2].max()
    knuckles = np.mean([B[j][1] for j in (7, 12, 17, 22)], 0)
    seg[1] = [(far, t1), (t1, knuckles)]
    return seg


def seg_dist(pts, a, b):
    d = b - a
    t = np.clip(((pts - a) @ d) / max(d @ d, 1e-12), 0, 1)
    return np.linalg.norm(pts - (a + t[:, None] * d), axis=1)


def assign_bones(src, segs, pts, s_u):
    """Each voxel centre -> one joint: the nearest bone segment among the joints whose plane it lies past
    (joint frame z <= half a voxel; the wrist always qualifies)."""
    B = src['B']
    joints = sorted(segs)
    D = np.full((len(pts), len(joints)), np.inf)
    for k, j in enumerate(joints):
        d = np.min([seg_dist(pts, a, b) for a, b in segs[j]], axis=0)
        if j != 1:
            R, t = B[j]
            past = ((pts - t) @ R[:, 2]) <= 0.5 * s_u
            d = np.where(past, d, np.inf)
        D[:, k] = d
    return np.array(joints)[np.argmin(D, 1)]


def separate_fingers(solid, label):
    """Voxels of two different fingers (or thumb) that touch are pulled apart (the later finger gives way),
    so every finger is its own closed segment chain and no face goes missing when they move apart."""
    order = {'thumb': 0, 'index': 1, 'middle': 2, 'ring': 3, 'little': 4}
    chain = np.vectorize(lambda j: order.get(CHAIN.get(int(j)), -1))(label)
    for _ in range(4):
        drop = np.zeros_like(solid)
        for ax in range(3):
            for sh_ in (1, -1):
                nb = np.roll(chain, sh_, axis=ax)
                ns = np.roll(solid, sh_, axis=ax)
                drop |= solid & ns & (chain >= 0) & (nb >= 0) & (nb != chain) & (chain > nb)
        if not drop.any():
            break
        solid &= ~drop
    return solid


def corner_weights(solid, label, corners):
    """Joint weights of each mesh corner (grid index) from the voxels within two voxels of it (a 4x4x4 block):
    the two most common joints share in proportion, so a joint border blends over two voxel rows each side
    (50/50 on the border, then 75/25, then 100 %) instead of one seam row."""
    X, Y, Z = solid.shape
    out = []
    for c in corners:
        i0, j0, k0 = c[0] - 2, c[1] - 2, c[2] - 2
        sl = (slice(max(i0, 0), max(c[0] + 2, 0)), slice(max(j0, 0), max(c[1] + 2, 0)), slice(max(k0, 0), max(c[2] + 2, 0)))
        js = label[sl][solid[sl]]
        u, n = np.unique(js, return_counts=True)
        o = np.argsort(-n)
        if len(u) == 1:
            out.append((int(u[0]), 1.0, int(u[0])))
            continue
        a, b = o[0], o[1]
        w = n[a] / (n[a] + n[b])
        w = 0.5 if w < 0.625 else 0.75 if w < 0.875 else 1.0
        out.append((int(u[a]), w, int(u[b])))
    return out


def knuckle_balls(src, P, solid, label, lo, s_u):
    """A rounded block of voxels at each strongly bending joint (finger MCP, thumb CMC and MCP), as thick as
    the finger there, split by the joint plane like the rest: the bend then shows a knuckle, not a sheet."""
    B, sk = src['B'], src['skin']
    idx = np.indices(solid.shape).transpose(1, 2, 3, 0)
    for j in (7, 12, 17, 22, 2, 3):
        R, t = B[j]
        own = (sk['j0'] == j) & (sk['w'] > 0.5)
        if not own.any():
            continue
        L = (P[own] - t) @ R
        r = float(np.median(np.hypot(L[:, 0], L[:, 1]))) * 0.95
        c = (t - lo) / s_u - 0.5
        ball = ((idx - c) ** 2).sum(-1) <= (r / s_u) ** 2
        new = ball & ~solid
        if new.any():
            pts = lo + (np.argwhere(new) + 0.5) * s_u
            past = ((pts - t) @ R[:, 2]) <= 0.5 * s_u
            parent = {2: 1, 3: 2}.get(j, 1)
            label[tuple(np.argwhere(new).T)] = np.where(past, j, parent)
            solid |= new
    return solid, label


def voxel_hand(src, P, tris, name, palette, s_mm):
    from voxelise import _winding_grid
    from voxmesh import mesh_parts
    from scipy import ndimage
    from scipy.spatial import cKDTree
    s_u = s_mm / 1000 * U
    lo = P.min(0) - 2 * s_u
    n = np.ceil((P.max(0) + 2 * s_u - lo) / s_u).astype(int)
    sub = 3
    inside = _winding_grid(P, tris, lo, s_u / sub, tuple(n * sub))
    n0 = n.copy()
    frac = inside.reshape(n[0], sub, n[1], sub, n[2], sub).mean((1, 3, 5))
    solid = frac >= 0.5
    # the forearm (2 cm past the wrist and on) is decided per 2x2x2 block: half the steps, so the vertex
    # budget goes to the fingers; still one grid and one closed shell
    pads = [(0, (-v) % 2) for v in n]
    fr = np.pad(frac, pads)
    X, Y, Z = (v // 2 for v in fr.shape)
    cf = fr.reshape(X, 2, Y, 2, Z, 2).mean((1, 3, 5)) >= 0.5
    up = np.repeat(np.repeat(np.repeat(cf, 2, 0), 2, 1), 2, 2)[:n0[0], :n0[1], :n0[2]]
    R1, t1 = src['B'][1]
    cz = ((lo + (np.indices(tuple(n0)).transpose(1, 2, 3, 0) + 0.5) * s_u - t1) @ R1)[..., 2] / U
    zb = np.pad(cz, pads, mode='edge').reshape(X, 2, Y, 2, Z, 2).min((1, 3, 5))
    far = np.repeat(np.repeat(np.repeat(zb > 0.02, 2, 0), 2, 1), 2, 2)[:n0[0], :n0[1], :n0[2]]
    solid = np.where(far, up, solid)
    cells = np.argwhere(solid)
    centres = lo + (cells + 0.5) * s_u
    segs = bone_segments(src, P)
    label = np.zeros(solid.shape, np.int32)
    label[tuple(cells.T)] = assign_bones(src, segs, centres, s_u)
    solid, label = knuckle_balls(src, P, solid, label, lo, s_u)
    solid = separate_fingers(solid, label)
    lab, k = ndimage.label(solid)
    if k > 1:
        sizes = ndimage.sum(solid, lab, range(1, k + 1))
        solid = lab == 1 + int(np.argmax(sizes))
    from kvx import fill_solid
    solid = fill_solid(solid)
    cells = np.argwhere(solid)
    centres = lo + (cells + 0.5) * s_u
    # colour: region and light band of the nearest point of the smooth reshaped shell
    sk = src['skin']
    joints = sorted(src['B'])
    jidx = {j: i for i, j in enumerate(joints)}
    W = np.zeros((len(P), len(joints)))
    for i in range(len(P)):
        W[i, jidx[sk['j0'][i]]] += sk['w'][i]
        W[i, jidx[sk['j1'][i]]] += 1 - sk['w'][i]
    N = vertex_normals(P, tris)
    kk = 4
    bw = np.array([(i / kk, j / kk, 1 - i / kk - j / kk) for i in range(kk + 1) for j in range(kk + 1 - i)])
    sp = np.einsum('sb,tbc->tsc', bw, P[tris]).reshape(-1, 3)
    sn = np.einsum('sb,tbc->tsc', bw, N[tris]).reshape(-1, 3)
    sn /= np.linalg.norm(sn, axis=1, keepdims=True) + 1e-12
    sw = np.einsum('sb,tbj->tsj', bw, W[tris]).reshape(-1, len(joints))
    _, nc = cKDTree(sp).query(centres)
    regions = cell_region(src, joints, sw[nc], centres, name)
    rgb = np.zeros(solid.shape + (3,), np.uint8)
    rgb[tuple(cells.T)] = colours(regions, cells, sn[nc], name, palette)
    A3 = np.zeros((3, 4))
    A3[0, 0] = A3[1, 1] = A3[2, 2] = s_u
    A3[:, 3] = lo
    # cells in a joint's blend zone (another bone within two voxels) get a label of their own: 1-voxel
    # rectangles there, so the soft weights bend the surface smoothly instead of shearing long rectangles
    from scipy import ndimage
    mesh_label = np.where(solid, label, -1)
    zone = np.zeros(solid.shape, bool)
    for j in np.unique(label[solid]):
        own = solid & (label == j)
        zone |= own & ndimage.binary_dilation(solid & (label != j), iterations=2)
    zc = np.argwhere(zone)
    mesh_label[tuple(zc.T)] = 1000 + np.arange(len(zc))
    m = mesh_parts([dict(solid=solid, rgb=rgb, A=A3, label=mesh_label)])
    if len(m['pos']) > MAX_VERTS:
        return None, len(m['pos'])
    corners = np.round((m['pos'] - lo) / s_u).astype(int)
    cw = corner_weights(solid, label, corners)
    B = src['B']
    rows = []
    for i, (ja, wa, jb) in enumerate(cw):
        Ra, ta = B[ja]
        Rb, tb = B[jb]
        rows.append((ja, wa, Ra.T @ (m['pos'][i] - ta), jb, Rb.T @ (m['pos'][i] - tb)))
    info = dict(voxel_mm=s_mm, voxels=int(solid.sum()), regions=sorted(set(regions.tolist())),
                bones={int(j): int((label[solid] == j).sum()) for j in np.unique(label[solid])})
    return dict(P=m['pos'], tris=m['tris'], st=m['st'], rows=rows, tex=m['tex'], tinfo=info), len(m['pos'])


# ------------------------------------------------------------------ build
def weld_groups(P):
    """Index of the first vertex at each vertex's position (UV seams duplicate vertices)."""
    key = np.round(P * 64).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return first[inv.reshape(-1)]


def build_side(src, name, palette, st=None):
    sh = CHARS[name]['shape']
    g = weld_groups(src['P'])
    P = reshape(src, sh)[g]                        # seam duplicates move together (stays closed)
    tw = g[src['tris']]                            # welded triangles
    P = offset(src, P, tw, name)[g]
    for s_mm in (2.5, 2.75, 3.0, 3.25, 3.5, 3.75, 4.0, 4.5):
        res, nv = voxel_hand(src, P, tw, name, palette, s_mm)
        if res:
            return res
    raise SystemExit(f'build_hands: {name} does not fit {MAX_VERTS} vertices')


def write_side(res, side, stem):
    pos, tris = res['P'].copy(), res['tris'].copy()
    mir = np.array([1.0, 1.0, 1.0])
    if side == 'left':                             # exact mirror of the right hand (as in v7)
        mir = np.array([-1.0, 1.0, 1.0])
        pos, tris = pos * mir, tris[:, ::-1]
    nrm = vertex_normals(pos, tris)
    stem.parent.mkdir(parents=True, exist_ok=True)
    name = stem.name
    surf = dict(name=name, shader=f'{name}.png', tris=tris, st=res['st'], pos=[pos], nrm=[nrm])
    size = write_md3(stem.with_suffix('.md3'), name, ['bind'], [surf], [])
    save_png(res['tex'], stem.with_suffix('.png'))
    lines = [f'skin 1 {len(res["rows"])}']
    for ja, wa, la, jb, lb in res['rows']:
        la, lb = la * mir, lb * mir
        lines.append(f'{ja} {wa:.6f} {la[0]:.6f} {la[1]:.6f} {la[2]:.6f} {jb} {lb[0]:.6f} {lb[1]:.6f} {lb[2]:.6f}')
    stem.with_suffix('.skin').write_text('\n'.join(lines) + '\n')
    return dict(verts=int(len(pos)), tris=int(len(tris)), md3_bytes=size,
                signed_volume_units3=round(signed_volume(pos, tris), 2), weld=weld_check(pos, tris))


VOXEL_SKIN = ['player/1528_ARM', 'player/1530_ARM', 'player/1532_ARM', 'player/1534_ARM', 'player/1405_DUKE']


def duke_voxel_look(palette):
    """Duke's skin and forearm as Cheello voxelled them: the skin voxels of the forearm gibs (player/1528-1534
    ARM, Duke's severed forearm gripping his rifle) and of the standing Duke voxel (1405): their palette
    indices (the Duke palette's skin ramp; blood, stump, rifle and cloth excluded by colour), weighted by use,
    give the five band colours (10/30/50/70/90 % of the voxels by brightness); the gibs' forearm gives the
    taper (wrist / elbow thickness) and slenderness (elbow thickness / forearm length)."""
    from kvx import read_kvx
    vox = ROOT / 'source' / 'voxels'
    counts = {}
    shape = []
    used = []
    for rel in VOXEL_SKIN:
        f = vox / f'{rel}.kvx'
        if not f.is_file():
            continue
        k = read_kvx(f)
        g = k['grid']
        c = k['palette'][np.clip(g, 0, 255)].astype(int)
        skin = (g >= 0) & (c[..., 0] > c[..., 2] + 35) & (c[..., 1] > 0.45 * c[..., 0]) & (c[..., 0] > 60) & \
            (c[..., 1] > c[..., 2] + 10) & (c[..., 2] > 0.25 * c[..., 0]) & (c[..., 1] < 0.8 * c[..., 0])   # no hair/olive
        blood = (g >= 0) & (c[..., 0] > 120) & (c[..., 1] < 0.35 * c[..., 0])
        used.append(f'voxels/{rel}.kvx')
        for i, n in zip(*np.unique(g[skin], return_counts=True)):
            counts[int(i)] = counts.get(int(i), 0) + int(n)
        if 'ARM' in rel:                           # forearm: stump (bottom) -> wrist (thinnest) along the arm
            P = np.argwhere(skin).astype(float)
            m = P.mean(0)
            ax = np.linalg.svd(P - m)[2][0]
            t = (P - m) @ ax
            tb = (np.argwhere(blood).astype(float) - m) @ ax
            if len(tb) and tb.mean() > 0:
                t = -t                             # t grows from the bloody stump (elbow) to the hand
            r = np.linalg.norm((P - m) - np.outer(t, ax), axis=1)
            bins = np.linspace(t.min(), t.max(), 9)
            prof = [2 * np.percentile(r[(t >= a) & (t < b)], 90) if ((t >= a) & (t < b)).sum() > 3 else np.nan
                    for a, b in zip(bins[:-1], bins[1:])]
            elbow = np.nanmean(prof[:2])
            wrist = np.nanmin(prof[2:5])
            shape.append((elbow, wrist, 0.5 * (t.max() - t.min())))      # forearm: the arm's lower half
    if not counts:
        return None
    idx = np.array(sorted(counts, key=lambda i: palette[i].astype(int).sum()))
    w = np.array([counts[i] for i in idx], float)
    cum = np.cumsum(w) / w.sum()
    bands = [int(idx[np.searchsorted(cum, q)]) for q in (0.1, 0.3, 0.5, 0.7, 0.9)]
    out = dict(sources=used, skin_indices={int(i): counts[int(i)] for i in idx}, band_indices=bands,
               bands=[tuple(int(v) for v in palette[i]) for i in bands])
    if shape:
        e, wr, L = (float(np.mean([s_[i] for s_ in shape])) for i in range(3))
        out.update(taper=round(wr / e, 3), slenderness=round(e / L, 3))
    return out


def duke_forearm_factors(src, look):
    """Scale factors (wrist, forearm) that give the v7 forearm the gibs' taper and slenderness."""
    R1, t1 = src['B'][1]
    L = (src['P'] - t1) @ R1 / U
    fz = L[:, 2]
    length = fz.max()
    def thick(z0, z1):
        sel = (fz >= z0) & (fz <= z1)
        return 2 * np.percentile(np.hypot(L[sel, 0], L[sel, 1]), 90)
    t_far, t_wrist = thick(length * 0.75, length), thick(0.0, 0.03)
    forearm = np.clip(look['slenderness'] * length / t_far, 0.8, 1.3)
    wrist = np.clip(forearm * look['taper'] * t_far / t_wrist, 0.8, 1.3)
    return round(float(wrist), 3), round(float(forearm), 3)


def build_char(name, palette, wrist=False):
    variants = ['', '_wrist'] if name == 'duke' and wrist else ['']
    look = duke_voxel_look(palette) if name == 'duke' else None
    if look:
        CHARS['duke']['regions'] = dict(hand=look['bands'], forearm=look['bands'], cuff=look['bands'],
                                        nail=look['bands'][1:] + [look['bands'][-1]])
        if 'taper' in look:
            wr, fa = duke_forearm_factors(source(''), look)
            CHARS['duke']['shape'] = dict(wrist=wr, forearm=fa)
            look.update(wrist=wr, forearm=fa)
    rec = dict(pchar=CHARS[name]['pchar'], label=CHARS[name]['label'], look=CHARS[name]['look'],
               shape=CHARS[name]['shape'], offsets=OFFSETS.get(name, []),
               colours={k: [list(c) for c in v] for k, v in CHARS[name]['regions'].items()},
               source='v7-original/exports/eduke32/hands/vr_hand_right_shell (shape, skin joints)')
    if look:
        rec['voxel_duke'] = look                 # which Voxel Duke voxels and palette indices were used
    out_dir = EXP / 'hands' if name == 'duke' else EXP / 'characters' / name / 'hands'
    rel = out_dir.relative_to(ROOT).as_posix()
    rec['hands'] = f'{rel}/vr_hand_{{side}}_shell'
    rec['files'] = {}
    for variant in variants:
        src = source(variant)
        res = build_side(src, name, palette)
        for side in ('left', 'right'):
            stem = out_dir / f'vr_hand_{side}_shell{variant}'
            info = write_side(res, side, stem)
            key = side + variant
            rec['files'][key] = {ext: f'{rel}/{stem.name}.{ext}' for ext in ('md3', 'png', 'skin')}
            rec.setdefault('meshes', {})[key] = dict(info, voxels=res['tinfo'])
        print(name, variant or '(full)', rec['meshes']['right' + variant], flush=True)
    return rec


def main():
    """chars=duke (default): Duke's floating voxel hands only, record in metadata/assets/duke_hands.json.
    chars=all|names: also the Alien Armageddon characters (experimental, paused), written with Duke to
    metadata/characters.json. wrist=1: also Duke's wrist-cut variant (not needed when the pack's full body has
    its own hands)."""
    args = dict(a.split('=', 1) for a in sys.argv[1:])
    names = ['duke'] if args.get('chars', 'duke') == 'duke' else \
        (list(CHARS) if args['chars'] == 'all' else args['chars'].split(','))
    palette = read_kvx(ROOT / 'source/voxels/weapons/21_PISTOL.kvx')['palette']
    data = {n: build_char(n, palette, wrist=args.get('wrist') == '1') for n in names}
    (ROOT / 'metadata' / 'assets').mkdir(parents=True, exist_ok=True)
    (ROOT / 'metadata' / 'assets' / 'duke_hands.json').write_text(json.dumps(data['duke'], indent=1))
    if any(n != 'duke' for n in names):
        path = ROOT / 'metadata' / 'characters.json'
        path.write_text(json.dumps({k: data[k] for k in CHARS if k in data}, indent=1))


if __name__ == '__main__':
    main()
