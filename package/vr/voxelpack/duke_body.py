"""One connected voxel Duke in the build pose (see duke_skel.py), assembled from the Voxel Duke Nukem 3D APLAYER
voxels by rigid per-region transforms and re-voxelised into ONE grid, plus v7-shaped hands with finger bones.

build_body(sk, ...) -> coarse body cells + fine hand cells; assemble(r) -> dict(solid, pal, bone, fine) on one fine
grid (h = s / fh metres per cell),
where s = the source voxel size (v7 height / the pain voxel's 84-voxel height = 2.16 cm). The body is coarse
(fh x fh x fh blocks of fine cells, i.e. one block per source voxel); the arms past the shoulder and the hands
are fine.

Regions (all true-handed metres, build pose: arms out along +-Y, legs vertical):
* torso + legs: the pain voxel 1511 (Duke standing straight, no rifle). Its right half (Duke's right, KVX x <=
  21) is used and mirrored onto the left, which removes the left hand Duke holds to his face and keeps the
  tank top, straps, belt and jetpack symmetric. 1511's own right arm (outside the shoulder) is cut away.
  Cell-aligned copy: one target block per source voxel (no resampling).
* head: the standing voxel 1405 (Duke's usual face) above the chin, placed on 1511's head position.
* arms and hands: v7's own arm (upper arm, forearm) and open bind hand (vr_duke_ik.md3 bind frame), carried
  rigidly into the T-pose; the shoulder end at the body voxel size (so the shoulder bends on one grid), the rest
  of the arm from 7 cm past the shoulder joint and the hand at half of it, so the forearm runs into the hand with
  one voxel size. The
  arm is thickened radially about the arm line to Voxel Duke's build, fingers and palm about their bones; each
  cell belongs to the upper arm, forearm, hand or one finger bone (nearest bone segment past its joint plane);
  fingers that touch are pulled one cell apart. Arm and hand are shaded as one surface: Voxel Duke's skin ramp
  (palette 40, 43, 46, 48, 51) in bands of the smoothed voxel shape's normal against one light over the back of
  the hand. Duke's own voxel arms are bent around the rifle in every frame, so they are not reposed.
Every region is sampled by inverse mapping (target cell centre -> source voxel), so there are no holes; the
union is closed (interior filled) and only the largest 6-connected piece is kept.
"""
import math, sys
from pathlib import Path
import numpy as np
from scipy import ndimage

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from kvx import read_kvx, fill_solid  # noqa: E402
from voxmesh import nearest_colour_fill  # noqa: E402
from md3np import read as read_md3  # noqa: E402

# ---------------------------------------------------------------- source constants (Voxel Duke Nukem 3D v1.0)
BODY_TILE, HEAD_TILE = 1511, 1405
BODY_H = 84                     # 1511: head top z = 0 .. soles z = 84
BODY_MID_X = 21                 # 1511 mirror column (cell index): y = 0
BODY_FWD_Y = 17.0               # 1511 KVX y of the hip / spine line (target x = 0)
BODY_ARM_X = 11                 # 1511 cells with x < 11 below the deltoid (z >= 20) are its right arm (cut away)
BODY_DELT_Z = 20
BODY_HEAD_Z = 13                # 1511 cells with z < 13 are its head (replaced)
HEAD_BOX = ((12, 26), (13, 30), (0, 14))    # 1405 head voxels: x, y, z ranges (KVX); excludes the jetpack loop
HEAD_CUT_Z = 13.5               # 1405 voxels above this KVX z are head (chin line + one voxel of neck)
HEAD_REF_Z = 12.5               # the head above this KVX z (no neck) is what is aligned
HEAD_SHIFT = (-1, 0, 1)         # head placed one voxel back and up from 1511's head: face and crown as v7's
SKIN_RAMP = (40, 43, 46, 48, 51)  # Voxel Duke's skin ramp (dark -> light), as the voxel hand shells use
LIGHT_H = np.array([0.25, 1.0, -0.35])   # in the right hand's frame (x little finger, y back, z wrist)
FINGERS = ('thumb', 'index', 'middle', 'ring', 'little')


def src_path(root, tile):
    return Path(root) / 'source/voxels/player' / f'{tile}_DUKE.kvx'


# ---------------------------------------------------------------- helpers
def seg_dist(P, a, b):
    d = b - a
    t = np.clip(((P - a) @ d) / max(float(d @ d), 1e-12), 0, 1)
    return np.linalg.norm(P - (a + t[:, None] * d), axis=1), t


def inside_mesh(Q, P, T):
    """Ray parity (+X with a small tilt) of points Q against triangles (P, T)."""
    d = np.array([1.0, 0.0123, 0.0071])
    d /= np.linalg.norm(d)
    A, B, C = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    cnt = np.zeros(len(Q), np.int64)
    e1, e2 = B - A, C - A
    h = np.cross(d, e2)
    a = np.einsum('ij,ij->i', e1, h)
    ok = np.abs(a) > 1e-14
    for i in np.nonzero(ok)[0]:
        f = 1.0 / a[i]
        s = Q - A[i]
        u = f * (s @ h[i])
        m = (u >= 0) & (u <= 1)
        if not m.any():
            continue
        q = np.cross(s[m], e1[i])
        v = f * (q @ d)
        t = f * (q @ e2[i])
        hit = (v >= 0) & (u[m] + v <= 1) & (t > 0)
        cnt[np.nonzero(m)[0][hit]] += 1
    return cnt % 2 == 1


def hand_segments(sk, side, P):
    """Bone segments (metres, bind) of the hand and finger bones; distal bones run to the fingertip."""
    B = sk.bind
    segs = {}
    for f in FINGERS:
        names = ['thumb_metacarpal', 'thumb_proximal', 'thumb_distal'] if f == 'thumb' else \
            [f'{f}_proximal', f'{f}_intermediate', f'{f}_distal']
        for k, nm in enumerate(names):
            b = sk.bi[f'{nm}_{side}']
            a = B[b][:3, 3]
            if k < 2:
                e = B[sk.bi[f'{names[k + 1]}_{side}']][:3, 3]
            else:
                # tip: farthest v7 hand vertex along the bone's -Z within the finger's radius
                z = -B[b][:3, 2]
                rel = P - a
                along = rel @ z
                rad = np.linalg.norm(rel - np.outer(along, z), axis=1)
                sel = (rad < 0.012) & (along > 0)
                L = float(along[sel].max()) if sel.any() else 0.02
                e = a + z * L
            segs[b] = (a, e)
    hb = sk.bi[f'hand_{side}']
    wrist = B[hb][:3, 3]
    knuckles = np.mean([B[sk.bi[f'{f}_proximal_{side}']][:3, 3] for f in ('index', 'middle', 'ring', 'little')], 0)
    segs[hb] = (wrist, knuckles)
    return segs


CHAIN_ORDER = {'thumb': 0, 'index': 1, 'middle': 2, 'ring': 3, 'little': 4}


def finger_chain(sk, b):
    n = sk.names[b]
    for f in FINGERS:
        if n.startswith(f + '_'):
            return CHAIN_ORDER[f]
    return -1


# ---------------------------------------------------------------- v7 arms and hands
ARM_U0 = -0.04        # the voxelised v7 arm starts 4 cm inside the shoulder joint plane (inward: Duke's own shoulder)
ARM_FINE_U = 0.07     # body voxels up to here (the shoulder bends on one grid), fine cells from here to the fingertips
# v7's arm and hand thickened to Voxel Duke's build (the bone positions stay v7's): radial factor about the arm
# line for the upper arm, the forearm at the elbow and at the wrist; about each finger bone; the palm's thickness
ARM_FAT = (1.2, 1.15, 1.08)
FINGER_FAT, THUMB_FAT, PALM_FAT = 1.35, 1.3, 1.25
ARM_R = 0.13          # the arm lies within 13 cm of its line
BAND = (-0.45, -0.1, 0.3, 0.65)
SHADE_SIGMA = 1.5     # fine cells: smoothing of the voxel shape whose normal shades the arm and hand


def lr(sk, b, side):
    """Bone index of the same bone on the other side."""
    n = sk.names[b]
    return sk.bi[n[:-2] + '_' + side] if n.endswith(('_l', '_r')) else b


def v7_arm(sk, v7_exports, G, cidx, C, log):
    """Left arm (coarse at the shoulder, fine from ARM_FINE_U on) and hand (fine) from v7's bind mesh, carried to
    the T-pose; then mirrored. The forearm, wrist and hand share one voxel size, and the whole arm one shading."""
    m = read_md3(Path(v7_exports) / 'vr_duke_ik.md3')
    s0 = m['surfaces'][0]
    P = s0['xyz'][0] / 64.0
    T = np.asarray(s0['tris'], np.int64)
    key = np.round(P * 4096).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    P = P[first]
    T = inv.reshape(-1)[T]
    T = T[(T[:, 0] != T[:, 1]) & (T[:, 1] != T[:, 2]) & (T[:, 0] != T[:, 2])]
    T = T[(P[T][:, :, 1] > 0.15).all(1)]                 # the left arm side (rays never leave y > 0.15)
    R, sh = sk.arm_rot['l']
    Hb = sk.bind[sk.bi['hand_l']]
    wrist_u = float((Hb[:3, 3] - sh) @ (R.T @ np.array([0, 1.0, 0])))
    s, h = G.s, G.h
    seam_y = sh[1] + ARM_FINE_U
    seam_y = G.corigin[1] + math.ceil((seam_y - G.corigin[1]) / s) * s     # a coarse cell boundary
    to_bind = lambda Q: (Q - sh) @ R + sh                # R^T (q - sh) + sh, row vectors
    L_up = float(np.linalg.norm(sk.pos('forearm_l') - sk.pos('upperarm_l')))
    arm_fat = lambda uu: np.interp(uu, [L_up - 0.03, L_up + 0.03, wrist_u], [ARM_FAT[0], ARM_FAT[1], ARM_FAT[2]])
    Sx = np.array([-1.0, 1, 1])                          # left hand frame -> right-hand convention
    # one light for arm and hand: LIGHT_H (right-hand frame) carried to the left hand's build-pose frame
    Lb = R @ Hb[:3, :3] @ (LIGHT_H * Sx)
    Lb /= np.linalg.norm(Lb)
    # ---- coarse: the upper arm from inside the shoulder to the seam (the shoulder's blend stays on one grid)
    uc = C[:, 1] - sh[1]
    radc = np.hypot(C[:, 0] - sh[0], C[:, 2] - sh[2])
    cand = (C[:, 1] > 0) & (uc >= ARM_U0) & (radc < ARM_R) & (C[:, 1] < seam_y)
    Qt = C[cand].copy()
    fat = arm_fat(uc[cand])
    Qt[:, [0, 2]] = sh[[0, 2]] + (Qt[:, [0, 2]] - sh[[0, 2]]) / fat[:, None]
    ci = cidx[cand][inside_mesh(to_bind(Qt), P, T)]
    cbone = np.full(len(ci), sk.bi['upperarm_l'], np.int16)
    # ---- fine cells: the rest of the upper arm, forearm, wrist and hand
    hb = sk.build[sk.bi['hand_l']][:3, 3]
    lo = np.array([min(hb[0], sh[0]) - 0.16, sh[1] + ARM_U0 - h, min(hb[2], sh[2]) - 0.16])
    hi = np.array([max(hb[0], sh[0]) + 0.16, hb[1] + 0.27, max(hb[2], sh[2]) + 0.16])
    box = [(max(0, int(math.floor((lo[a] - G.origin[a]) / h))), min(G.shape[a], int(math.ceil((hi[a] - G.origin[a]) / h))))
           for a in range(3)]
    fidx, F = G.fcentres(box)
    u = F[:, 1] - sh[1]
    rad = np.hypot(F[:, 0] - sh[0], F[:, 2] - sh[2])
    F_ok = (F[:, 1] > seam_y) & ((u > wrist_u - 0.02) | (rad < ARM_R))
    # room under the arm for it to come down to the bind A-pose (no arm cell where the torso is)
    F_ok &= ~((u < ARMPIT_ARM_U) & (F[:, 2] < sh[2] - ARMPIT_ARM_DZ))
    fidx, F, u = fidx[F_ok], F[F_ok], u[F_ok]
    Fb = to_bind(F)
    segs = hand_segments(sk, 'l', P)
    hand_b, fore_b, upper_b = sk.bi['hand_l'], sk.bi['forearm_l'], sk.bi['upperarm_l']
    Hi = np.linalg.inv(Hb)
    hl = Fb @ Hi[:3, :3].T + Hi[:3, 3]                  # hand-bone local (z toward the elbow)
    bones = sorted(segs)
    D = np.full((len(Fb), len(bones)), np.inf)
    for k, b in enumerate(bones):
        a, e = segs[b]
        d, _ = seg_dist(Fb, a, e)
        if b != hand_b:
            past = ((Fb - a) @ -sk.bind[b][:3, 2]) >= -0.5 * h
            d = np.where(past, d, np.inf)
        D[:, k] = d
    fbone = np.array(bones)[np.argmin(D, 1)]
    arm = hl[:, 2] > 0
    fbone = np.where(arm, np.where(u < L_up, upper_b, fore_b), fbone).astype(np.int16)
    # thicken: shrink each cell's offset from its bone before asking whether v7's arm/hand contains it
    Qb = Fb.copy()
    for b in np.unique(fbone):
        sel = fbone == b
        if b in (fore_b, upper_b):
            k = arm_fat(u[sel])
            Qt = F[sel].copy()
            Qt[:, [0, 2]] = sh[[0, 2]] + (Qt[:, [0, 2]] - sh[[0, 2]]) / k[:, None]
            Qb[sel] = to_bind(Qt)
        elif b == hand_b:
            l = hl[sel].copy()
            l[:, 1] /= PALM_FAT
            Qb[sel] = l @ Hb[:3, :3].T + Hb[:3, 3]
        else:
            a, e = segs[b]
            d = (e - a) / np.linalg.norm(e - a)
            rel = Fb[sel] - a
            along = rel @ d
            k = THUMB_FAT if sk.names[b].startswith('thumb') else FINGER_FAT
            Qb[sel] = a + np.outer(along, d) + (rel - np.outer(along, d)) / k
    ins = inside_mesh(Qb, P, T)
    fidx, F, Fb, fbone = fidx[ins], F[ins], Qb[ins], fbone[ins]
    # fingers of different chains that touch: the later chain gives way (so every finger is its own shell)
    sol = np.zeros(G.shape, bool)
    lab = np.full(G.shape, -1, np.int16)
    sol[tuple(fidx.T)] = True
    lab[tuple(fidx.T)] = fbone
    chain_of = np.array([finger_chain(sk, b) for b in range(len(sk.names))] + [-1])
    sub = tuple(slice(a, b) for a, b in box)
    ssol, slab = sol[sub], lab[sub]
    for _ in range(4):
        ch = np.where(ssol, chain_of[slab], -1)
        drop = np.zeros_like(ssol)
        for ax in range(3):
            for sh_ in (1, -1):
                nb = np.roll(ch, sh_, axis=ax)
                drop |= ssol & (ch >= 0) & (nb >= 0) & (nb != ch) & (ch > nb)
        if not drop.any():
            break
        ssol &= ~drop
    keep = ssol[tuple((fidx - [b[0] for b in box]).T)]
    fidx, F, Fb, fbone = fidx[keep], F[keep], Fb[keep], fbone[keep]
    # shading: the normal of the voxel shape itself (smoothed occupancy of the coarse and fine arm cells), so
    # arm, wrist and hand shade as one surface; Voxel Duke's skin ramp in clean bands
    occ = ssol.astype(np.float32)
    b0 = np.array([b[0] for b in box])
    kids = (ci[:, None, :] * G.fh + np.indices((G.fh,) * 3).reshape(3, -1).T[None]).reshape(-1, 3) - b0
    kids = kids[((kids >= 0) & (kids < occ.shape)).all(1)]
    occ[tuple(kids.T)] = 1
    g = [ndimage.gaussian_filter(occ, SHADE_SIGMA, order=[int(a == ax) for a in range(3)]) for ax in range(3)]

    def bands(local):
        local = np.clip(local, 0, np.array(occ.shape) - 1)
        n = -np.stack([gg[tuple(local.T)] for gg in g], 1)
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        return np.digitize(n @ Lb, BAND)
    band = bands(fidx - b0)
    cpal = np.array(SKIN_RAMP, np.int16)[bands(ci * G.fh + G.fh // 2 - b0)]
    # nails: the back of the distal phalanges, one ramp step lighter
    nail = np.zeros(len(Fb), bool)
    for f in ('index', 'middle', 'ring', 'little', 'thumb'):
        b = sk.bi[f'{f}_distal_l']
        sel = fbone == b
        if sel.any():
            Bi = np.linalg.inv(sk.bind[b])
            l = Fb[sel] @ Bi[:3, :3].T + Bi[:3, 3]
            nail[np.nonzero(sel)[0][(l[:, 1] > 0.002) & (l[:, 2] < -0.012)]] = True
    band = np.where(nail, np.minimum(band + 1, 4), band)
    fpal = np.array(SKIN_RAMP, np.int16)[band]
    log(f'v7 arm and hand: {len(ci)} coarse and {len(fidx)} fine cells per side (fine from y {seam_y:.3f}, '
        f'wrist {sh[1] + wrist_u:.3f}), bones ' +
        ', '.join(f'{sk.names[b]}:{int((fbone == b).sum())}' for b in np.unique(fbone)))

    # ---- mirror to the right
    def mir_c(ix):
        o = ix.copy()
        o[:, 1] = G.cshape[1] - 1 - o[:, 1]
        return o

    def mir_f(ix):
        o = ix.copy()
        o[:, 1] = G.shape[1] - 1 - o[:, 1]
        return o
    rb = lambda bb: np.array([lr(sk, int(b), 'r') for b in bb], np.int16)
    cidx_all = np.concatenate([ci, mir_c(ci)])
    return dict(cidx=tuple(cidx_all.T), cpal=np.concatenate([cpal, cpal]), cbone=np.concatenate([cbone, rb(cbone)]),
                hand=dict(fidx=np.concatenate([fidx, mir_f(fidx)]), pal=np.concatenate([fpal, fpal]),
                          bone=np.concatenate([fbone, rb(fbone)])),
                seam_y=seam_y)


# ---------------------------------------------------------------- the grid
class Grid:
    """Fine grid: cell (i, j, k) centre = origin + (i + 0.5, j + 0.5, k + 0.5) * h; coarse block = fh^3 cells."""

    def __init__(self, s, fh, lo, hi):
        self.s, self.fh, self.h = s, fh, s / fh
        # coarse cell centres: x = (n + 0.5) s, y = j s (symmetric, y = 0 is a cell centre), z = (m + 0.5) s
        nx0, nx1 = math.floor(lo[0] / s), math.ceil(hi[0] / s)
        ny = math.ceil(hi[1] / s + 0.5)
        nz1 = math.ceil(hi[2] / s)
        self.corigin = np.array([nx0 * s, -(ny + 0.5) * s, 0.0])
        self.cshape = (nx1 - nx0, 2 * ny + 1, nz1)
        self.origin = self.corigin
        self.shape = tuple(n * fh for n in self.cshape)

    def ccentres(self):
        idx = np.indices(self.cshape).reshape(3, -1).T
        return idx, self.corigin + (idx + 0.5) * self.s

    def fcentres(self, box=None):
        if box is None:
            box = [(0, n) for n in self.shape]
        idx = np.stack(np.meshgrid(*[np.arange(a, b) for a, b in box], indexing='ij'), -1).reshape(-1, 3)
        return idx, self.origin + (idx + 0.5) * self.h

    def up(self, a):
        f = self.fh
        return np.repeat(np.repeat(np.repeat(a, f, 0), f, 1), f, 2)


def build_body(sk, pack_root, v7_exports, fh=2, log=print):
    root = Path(pack_root)
    kb = read_kvx(src_path(root, BODY_TILE))
    kh = read_kvx(src_path(root, HEAD_TILE))
    pal = kb['palette']
    assert np.array_equal(pal, kh['palette'])
    height = float(read_md3(Path(v7_exports) / 'vr_duke_ik.md3')['frames'][0]['maxs'][2]) / 64.0
    s = height / BODY_H
    G = Grid(s, fh, (-0.50, -1.15, 0.0), (0.42, 1.15, height + 0.05))
    log(f'voxel {s * 1000:.2f} mm, fine {G.h * 1000:.2f} mm, coarse {G.cshape}, fine {G.shape}')
    cidx, C = G.ccentres()
    cpal = np.full(G.cshape, -1, np.int16)
    cbone = np.full(G.cshape, -1, np.int16)
    creg = np.zeros(G.cshape, np.int8)          # 1 body, 2 head, 3 arm

    # ---- torso + legs: 1511 right half, mirrored
    gb = nearest_colour_fill(kb['grid'], kb['solid'])
    xs = BODY_MID_X - np.abs(np.round(C[:, 1] / s)).astype(int)
    ys = np.floor(C[:, 0] / s + BODY_FWD_Y).astype(int)
    zs = np.floor(BODY_H - C[:, 2] / s).astype(int)
    ok = (xs >= 0) & (ys >= 0) & (ys < kb['size'][1]) & (zs >= 0) & (zs < kb['size'][2])
    ok[ok] = kb['solid'][xs[ok], ys[ok], zs[ok]]
    ok &= (zs >= BODY_HEAD_Z) & ~((xs < BODY_ARM_X) & (zs >= BODY_DELT_Z))
    ci = tuple(cidx[ok].T)
    cpal[ci] = gb[xs[ok], ys[ok], zs[ok]]
    creg[ci] = 1

    # ---- head: 1405 above the chin, its centroid on 1511's head centroid
    gh = nearest_colour_fill(kh['grid'], kh['solid'])
    (x0, x1), (y0, y1), (z0, z1) = HEAD_BOX
    hm = np.zeros(kh['solid'].shape, bool)
    hm[x0:x1, y0:y1, z0:z1] = True
    zz = np.arange(kh['size'][2])[None, None, :] + 0.5
    hm &= kh['solid']
    hc = np.argwhere(hm & (zz < HEAD_REF_Z)).mean(0) + 0.5         # alignment: the head above the chin
    hm &= zz < HEAD_CUT_Z
    bm = kb['solid'].copy()
    bm[:, :, BODY_HEAD_Z - 1:] = False
    bm[:BODY_MID_X - 6] = False
    bm[BODY_MID_X + 9:] = False
    bc = np.argwhere(bm).mean(0) + 0.5
    # target of the 1405 head centroid: 1511's head centroid, laterally centred (y = 0)
    tgt = np.array([(bc[1] - BODY_FWD_Y + HEAD_SHIFT[0]) * s, 0.0, (BODY_H - bc[2] + HEAD_SHIFT[2]) * s])
    hx = np.floor(C[:, 1] / s + hc[0]).astype(int)
    hy = np.floor((C[:, 0] - tgt[0]) / s + hc[1]).astype(int)
    hz = np.floor(hc[2] - (C[:, 2] - tgt[2]) / s).astype(int)
    ok = (hx >= 0) & (hx < kh['size'][0]) & (hy >= 0) & (hy < kh['size'][1]) & (hz >= 0) & (hz < kh['size'][2])
    ok[ok] = hm[hx[ok], hy[ok], hz[ok]]
    ci = tuple(cidx[ok].T)
    cpal[ci] = gh[hx[ok], hy[ok], hz[ok]]
    creg[ci] = 2
    log(f'head centroid 1405 {hc.round(2)} -> 1511 {bc.round(2)}')

    # ---- arms + hands: v7's own arm and open bind hand, voxelised (left side, mirrored to the right)
    arm = v7_arm(sk, v7_exports, G, cidx, C, log)
    ci = arm['cidx']
    cpal[ci] = arm['cpal']
    creg[ci] = 3
    cbone[ci] = arm['cbone']
    label_trunk(sk, C, cidx, creg, cbone)
    # armpits: room under each arm for the arm coming down to the bind A-pose (no torso cell where it swings)
    sh = sk.pos('upperarm_l')
    y, z = np.abs(C[:, 1]), C[:, 2]
    pit = (y >= ARMPIT_Y) & (z >= ARMPIT_Z[0]) & (z <= ARMPIT_Z[1])
    tor = (creg[tuple(cidx.T)] == 1) & pit
    under = (creg[tuple(cidx.T)] == 3) & (y - sh[1] < ARMPIT_ARM_U) & (z < sh[2] - ARMPIT_ARM_DZ)
    for sel in (tor, under):
        ci = tuple(cidx[sel].T)
        cpal[ci], cbone[ci], creg[ci] = -1, -1, 0
    log(f'armpits: {int(tor.sum())} torso and {int(under.sum())} arm voxels cleared')
    cs, cpal, cbone, creg, nfix = manifold_fix(cpal >= 0, cpal, cbone, creg)
    log(f'manifold repair: {nfix} body voxels added')
    return dict(G=G, s=s, cpal=cpal, cbone=cbone, creg=creg, pal=pal, hand=arm['hand'])


# trunk bone borders (build pose, metres; v7's own weight borders)
NECK_Z, NECK_R = 1.46, 0.125         # neck: above the collar, within 12.5 cm of the spine line (hidden in first person)
CHEST_Z, SPINE_Z = 1.225, 1.045      # chest above, spine between, pelvis below
CLAV_Y, CLAV_Z = 0.15, 1.36          # shoulder tops (traps) follow the clavicles
DELT_Y = 0.25                        # Duke's own deltoid caps (outside the shoulder joints) follow the upper arms
PACK_X = -0.13                       # the jetpack (behind the back) is rigid with the chest
HIP_Z = 0.886                        # thighs below the hip joints
ARMPIT_Y, ARMPIT_Z = 0.20, (1.22, 1.35)   # torso cells cleared under the arms (|y| >=, z range)
ARMPIT_ARM_U, ARMPIT_ARM_DZ = 0.10, 0.05  # arm cells cleared: within 10 cm of the shoulder, 5 cm under its line


def label_trunk(sk, C, cidx, creg, cbone):
    sel = (creg[tuple(cidx.T)] == 1) | (creg[tuple(cidx.T)] == 2)
    Q = C[sel]
    x, y, z = Q[:, 0], Q[:, 1], Q[:, 2]
    side = np.where(y > 0, 'l', 'r')
    b = np.full(len(Q), sk.bi['pelvis'])
    b[z >= SPINE_Z] = sk.bi['spine']
    b[z >= CHEST_Z] = sk.bi['chest']
    b[(x < PACK_X) & (z > 0.95)] = sk.bi['chest']
    clav = (z >= CLAV_Z) & (np.abs(y) >= CLAV_Y)
    b[clav] = [sk.bi[f'clavicle_{s}'] for s in side[clav]]
    delt = (z >= CLAV_Z - 0.06) & (np.abs(y) >= DELT_Y)
    b[delt] = [sk.bi[f'upperarm_{s}'] for s in side[delt]]
    neck = (z >= NECK_Z) & (np.hypot(x - sk.pos('neck')[0], y) < NECK_R)
    b[neck] = sk.bi['neck']
    b[creg[tuple(cidx[sel].T)] == 2] = sk.bi['head']
    knee = sk.pos('calf_l')[2]
    ankle = sk.pos('foot_l')[2] + 0.02
    leg = (z < HIP_Z) & (np.abs(y) > 1e-6)              # the middle column stays pelvis (crotch)
    for name, cond in (('thigh', leg), ('calf', leg & (z < knee)), ('foot', leg & (z < ankle))):
        b[cond] = [sk.bi[f'{name}_{s}'] for s in side[cond]]
    cbone[tuple(cidx[sel].T)] = b


def assemble(r, log=print):
    """Fine grid: coarse blocks upsampled, the fine hand cells set; interior filled, largest piece kept."""
    G = r['G']
    pal = G.up(r['cpal'])
    bone = G.up(r['cbone'])
    hd = r['hand']
    fi = tuple(hd['fidx'].T)
    pal[fi] = hd['pal']
    bone[fi] = hd['bone']
    fine = np.zeros(G.shape, bool)
    fine[fi] = True
    solid = pal >= 0
    lab, n = ndimage.label(solid)
    if n > 1:
        sizes = ndimage.sum(solid, lab, range(1, n + 1))
        log(f'pieces: {n} (sizes {sorted(sizes.astype(int).tolist())[-6:]}); keeping the largest')
        solid = lab == 1 + int(np.argmax(sizes))
    filled = fill_solid(solid)
    holes = filled & ~solid
    if holes.any():
        _, ind = ndimage.distance_transform_edt(~solid, return_indices=True)
        pal = np.where(holes, pal[tuple(ind)], pal)
        bone = np.where(holes, bone[tuple(ind)], bone)
    solid = filled
    solid, pal, bone, nfix = manifold_fix(solid, pal, bone)
    if nfix:
        log(f'manifold repair: {nfix} fine cells added')
    pal = np.where(solid, pal, -1)
    bone = np.where(solid, bone, -1)
    return dict(solid=solid, pal=pal, bone=bone, fine=fine & solid)


def manifold_fix(solid, *labels, max_iter=8):
    """Fill one empty cell of every 2x2 (edge-only) or 2x2x2 (corner-only) diagonal contact, so the voxel shell is a
    2-manifold (no edge shared by four faces, no pinched vertex); filled cells copy their nearest neighbour's labels."""
    solid = solid.copy()
    labels = [l.copy() for l in labels]
    total = 0
    for _ in range(max_iter):
        add = np.zeros_like(solid)
        for a, b in ((0, 1), (0, 2), (1, 2)):
            def sl(da, db):
                s = [slice(None)] * 3
                s[a] = slice(da, solid.shape[a] - 1 + da)
                s[b] = slice(db, solid.shape[b] - 1 + db)
                return tuple(s)
            c00, c11, c10, c01 = solid[sl(0, 0)], solid[sl(1, 1)], solid[sl(1, 0)], solid[sl(0, 1)]
            add[sl(1, 0)] |= c00 & c11 & ~c10 & ~c01
            add[sl(0, 0)] |= c10 & c01 & ~c00 & ~c11
        X, Y, Z = solid.shape
        cube = [[[solid[i:X - 1 + i, j:Y - 1 + j, k:Z - 1 + k] for k in (0, 1)] for j in (0, 1)] for i in (0, 1)]
        n = sum(cube[i][j][k].astype(np.int8) for i in (0, 1) for j in (0, 1) for k in (0, 1))
        for (i, j, k) in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)):
            diag = cube[i][j][k] & cube[1 - i][1 - j][1 - k] & (n == 2)
            add[slice(1 - i, X - i), slice(j, Y - 1 + j), slice(k, Z - 1 + k)] |= diag
        add &= ~solid
        if not add.any():
            break
        total += int(add.sum())
        _, ind = ndimage.distance_transform_edt(~solid, return_indices=True)
        for l in labels:
            l[add] = l[tuple(ind)][add]
        solid |= add
    return (solid, *labels, total)
