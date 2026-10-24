"""Hand skeleton, forward kinematics and grasp solver (pure numpy; importable from Blender too).

Conventions
- Joint frames follow XR_EXT_hand_tracking: -Z toward the fingertip (child joint), +Y dorsal,
  +X = Y x Z (right hand: toward the little finger; left hand: toward the thumb).
- Everything is authored for the RIGHT hand; the left hand is the exact mirror (positions x -> -x in
  the mirrored frame, local frames R -> S R S with S = diag(-1,1,1)).
- Bind ("open") skeleton is expressed in the palm-joint frame H (palm joint at the origin).
- Grip frame (OpenXR core grip pose, metres): +X to the user's right for both hands, -Z along the
  grip from the little finger to the thumb, +Y = Z x X.  The palm SURFACE centroid sits at the grip
  origin (same point the engine puts at a weapon's tag_palm_<side>).
"""
import math
import numpy as np

JOINTS = ['XR_HAND_JOINT_PALM_EXT', 'XR_HAND_JOINT_WRIST_EXT',
          'XR_HAND_JOINT_THUMB_METACARPAL_EXT', 'XR_HAND_JOINT_THUMB_PROXIMAL_EXT', 'XR_HAND_JOINT_THUMB_DISTAL_EXT', 'XR_HAND_JOINT_THUMB_TIP_EXT']
for _f in ('INDEX', 'MIDDLE', 'RING', 'LITTLE'):
    JOINTS += [f'XR_HAND_JOINT_{_f}_{b}_EXT' for b in ('METACARPAL', 'PROXIMAL', 'INTERMEDIATE', 'DISTAL', 'TIP')]
SHORT = [j.replace('XR_HAND_JOINT_', '').replace('_EXT', '').lower() for j in JOINTS]
JI = {s: i for i, s in enumerate(SHORT)}
FINGERS = ['index', 'middle', 'ring', 'little']
K = 1.12   # gloved, slightly oversized Duke hand

# --- bind skeleton (right hand, metres, palm frame H) -----------------------------------------
_KN = {'index': (-0.026, 0.000, -0.031), 'middle': (-0.007, 0.002, -0.035), 'ring': (0.012, 0.001, -0.032),
       'little': (0.029, -0.003, -0.025)}
_MC = {'index': (-0.013, 0.0, 0.031), 'middle': (-0.003, 0.0, 0.032), 'ring': (0.007, 0.0, 0.031), 'little': (0.016, -0.001, 0.029)}
_LEN = {'index': (0.040, 0.024, 0.020), 'middle': (0.044, 0.028, 0.021), 'ring': (0.041, 0.027, 0.020), 'little': (0.032, 0.020, 0.018)}
_SPREAD = {'index': -5.0, 'middle': 0.0, 'ring': 5.0, 'little': 11.0}      # degrees, toward +X
_THUMB_BASE = (-0.019, -0.009, 0.031)
_THUMB_LEN = (0.043, 0.033, 0.027)
_THUMB_DIR = (-0.62, -0.30, -0.72)
_THUMB_UP = (-0.55, 0.80, 0.0)          # dorsal hint for the thumb (nail faces up-and-out)
WIDTH = {'index': 0.0232, 'middle': 0.0243, 'ring': 0.0227, 'little': 0.0205, 'thumb': 0.026}
HEIGHT = {'index': 0.0211, 'middle': 0.0216, 'ring': 0.0205, 'little': 0.0184, 'thumb': 0.0227}
PALM_W, PALM_T = 0.092, 0.042         # palm width at the knuckles, thickness (gloved, muscular)
PALM_HALF_T = PALM_T * K / 2


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def frame(z_back, up):
    """Rotation whose -Z points along -z_back... built from the bone direction d (toward child)."""
    d = unit(z_back)            # direction toward the child joint
    z = -d
    y = unit(np.asarray(up, float) - np.dot(up, z) * z)
    x = np.cross(y, z)
    return np.stack([x, y, z], 1)


def rot(axis, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    if axis == 'x':
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if axis == 'y':
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def T(R=None, p=None):
    M = np.eye(4)
    if R is not None:
        M[:3, :3] = R
    if p is not None:
        M[:3, 3] = p
    return M


PARENT = {'palm': None, 'wrist': 'palm', 'thumb_metacarpal': 'palm', 'thumb_proximal': 'thumb_metacarpal',
          'thumb_distal': 'thumb_proximal', 'thumb_tip': 'thumb_distal'}
for _f in FINGERS:
    PARENT.update({f'{_f}_metacarpal': 'palm', f'{_f}_proximal': f'{_f}_metacarpal', f'{_f}_intermediate': f'{_f}_proximal',
                   f'{_f}_distal': f'{_f}_intermediate', f'{_f}_tip': f'{_f}_distal'})


def bind_skeleton():
    """{joint: 4x4} world (= palm frame H) transforms of the open hand, scaled by K."""
    B = {'palm': T()}
    B['wrist'] = T(np.eye(3), np.array([0, 0, 0.049]) * K)
    for f in FINGERS:
        kn, mc = np.array(_KN[f]) * K, np.array(_MC[f]) * K
        B[f'{f}_metacarpal'] = T(frame(kn - mc, (0, 1, 0)), mc)
        d = rot('y', -_SPREAD[f]) @ np.array([0, 0, -1.0])
        R = frame(d, (0, 1, 0))
        p = kn
        names = [f'{f}_proximal', f'{f}_intermediate', f'{f}_distal', f'{f}_tip']
        for n, L in zip(names, list(_LEN[f]) + [None]):
            B[n] = T(R, p)
            if L is not None:
                p = p + d * L * K
    d = unit(_THUMB_DIR)
    R = frame(d, _THUMB_UP)
    p = np.array(_THUMB_BASE) * K
    for n, L in zip(['thumb_metacarpal', 'thumb_proximal', 'thumb_distal', 'thumb_tip'], list(_THUMB_LEN) + [None]):
        B[n] = T(R, p)
        if L is not None:
            p = p + d * L * K
    return B


BIND = bind_skeleton()
LOCAL = {j: (np.linalg.inv(BIND[PARENT[j]]) @ BIND[j]) if PARENT[j] else BIND[j] for j in SHORT}

SEGMENTS = {'palm': 'wrist', 'thumb_metacarpal': 'thumb_metacarpal', 'thumb_proximal': 'thumb_proximal',
            'thumb_distal': 'thumb_distal'}
for _f in FINGERS:
    SEGMENTS.update({f'{_f}_proximal': f'{_f}_proximal', f'{_f}_intermediate': f'{_f}_intermediate', f'{_f}_distal': f'{_f}_distal'})
CHILD = {'thumb_metacarpal': 'thumb_proximal', 'thumb_proximal': 'thumb_distal', 'thumb_distal': 'thumb_tip'}
for _f in FINGERS:
    CHILD.update({f'{_f}_proximal': f'{_f}_intermediate', f'{_f}_intermediate': f'{_f}_distal', f'{_f}_distal': f'{_f}_tip'})


def seg_length(seg):
    if seg == 'palm':
        return float(np.linalg.norm(BIND['middle_proximal'][:3, 3] - BIND['wrist'][:3, 3]))
    return float(np.linalg.norm(BIND[CHILD[seg]][:3, 3] - BIND[seg][:3, 3]))


def seg_dims(seg):
    f = seg.split('_')[0]
    L = seg_length(seg)
    if seg == 'palm':
        return L, PALM_W * K, PALM_T * K
    w, h = WIDTH[f] * K, HEIGHT[f] * K
    if seg.endswith('distal'):
        w, h = w * 0.94, h * 0.92
    if seg == 'thumb_metacarpal':
        w, h = w * 1.25, h * 1.2
    return L, w, h


# --- forward kinematics ---------------------------------------------------------------------
def fk(angles, root=None):
    """angles: {joint: (flex_deg, abduct_deg[, twist_deg])} local rotations (flex about local X toward the
    palm = negative rotation, abduction about local Y toward +X, twist about local Z).  Returns world
    transforms {joint: 4x4} with the palm joint at `root` (4x4, default identity)."""
    W = {}
    root = np.eye(4) if root is None else root
    for j in SHORT:
        p = PARENT[j]
        base = root @ LOCAL[j] if p is None else W[p] @ LOCAL[j]
        a = angles.get(j)
        if a:
            fl, ab = a[0], a[1] if len(a) > 1 else 0.0
            tw = a[2] if len(a) > 2 else 0.0
            R = rot('y', -ab) @ rot('x', -fl) @ rot('z', tw)
            base = base @ T(R)
        W[j] = base
    return W


def quat(R):
    m = R
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w, x, y, z = 0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        w, x, y, z = (m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        w, x, y, z = (m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        w, x, y, z = (m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s
    q = np.array([x, y, z, w])
    q = q / np.linalg.norm(q)
    return q if q[3] >= 0 else -q


def quat_to_R(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


S_X = np.diag([-1.0, 1, 1])


def mirror_x(M):
    """Right-hand joint transform in a frame -> left-hand transform mirrored across that frame's X=0."""
    out = np.eye(4)
    out[:3, :3] = S_X @ M[:3, :3] @ S_X
    out[:3, 3] = S_X @ M[:3, 3]
    return out


# --- grip-frame placement ---------------------------------------------------------------------
# right hand: palm frame axes in the grip frame: X_H (little) = +Z_g, Y_H (dorsal) = +X_g, Z_H (wrist) = +Y_g
R_PALM_GRIP = np.stack([[0, 0, 1.0], [1.0, 0, 0], [0, 1.0, 0]], 1)
PALM_IN_GRIP = T(R_PALM_GRIP, np.array([PALM_HALF_T + 0.002, -0.004, 0.0]))


# --- segment collision samples (joint-local) --------------------------------------------------
def seg_samples(seg, density=1.0):
    L, w, h = seg_dims(seg)
    pts = []
    zs = np.linspace(-0.3 * L, -L, 4)
    for z in zs:
        for x in (-0.38 * w, 0.0, 0.38 * w):
            pts.append((x, -0.5 * h, z))           # palmar face
        pts.append((-0.5 * w, -0.2 * h, z))
        pts.append((0.5 * w, -0.2 * h, z))
    if seg.endswith('distal'):
        for x in (-0.3 * w, 0.3 * w):
            pts.append((x, -0.1 * h, -L - 0.004))   # fingertip pad
        pts.append((0, 0.2 * h, -L - 0.002))
    return np.array(pts)


# --- geometry queries -------------------------------------------------------------------------
def point_tri_dist(P, A, B, C):
    """P (n,3); A,B,C (m,3) -> (n,m) distances (vectorised Ericson closest point)."""
    P = P[:, None, :]
    A, B, C = A[None], B[None], C[None]
    ab, ac, ap = B - A, C - A, P - A
    d1 = (ab * ap).sum(-1); d2 = (ac * ap).sum(-1)
    bp = P - B; d3 = (ab * bp).sum(-1); d4 = (ac * bp).sum(-1)
    cp = P - C; d5 = (ab * cp).sum(-1); d6 = (ac * cp).sum(-1)
    va = d3 * d6 - d5 * d4; vb = d5 * d2 - d1 * d6; vc = d1 * d4 - d3 * d2
    den = va + vb + vc
    den = np.where(np.abs(den) < 1e-18, 1e-18, den)
    v = vb / den; w = vc / den
    Q = A + ab * v[..., None] + ac * w[..., None]
    # edges
    def seg(Pp, X, Y):
        d = Y - X
        t = np.clip(((Pp - X) * d).sum(-1) / np.maximum((d * d).sum(-1), 1e-18), 0, 1)
        return X + d * t[..., None]
    inside = (va >= 0) & (vb >= 0) & (vc >= 0)
    q1, q2, q3 = seg(P, A, B), seg(P, B, C), seg(P, C, A)
    dist_in = np.linalg.norm(P - Q, axis=-1)
    de = np.minimum(np.minimum(np.linalg.norm(P - q1, axis=-1), np.linalg.norm(P - q2, axis=-1)), np.linalg.norm(P - q3, axis=-1))
    return np.where(inside, np.minimum(dist_in, de), de)


def winding(P, A, B, C):
    """Generalised winding number of points P w.r.t. the closed triangle soup (sum over closed parts)."""
    a = A[None] - P[:, None]; b = B[None] - P[:, None]; c = C[None] - P[:, None]
    la, lb, lc = (np.linalg.norm(x, axis=-1) for x in (a, b, c))
    det = (a * np.cross(b, c)).sum(-1)
    den = la * lb * lc + (a * b).sum(-1) * lc + (b * c).sum(-1) * la + (c * a).sum(-1) * lb
    return (2 * np.arctan2(det, den)).sum(-1) / (4 * math.pi)


class Obstacle:
    def __init__(self, tris, margin=0.0015):
        tris = np.asarray(tris, float)
        ar = np.linalg.norm(np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1)
        tris = tris[ar > 1e-10]
        self.A, self.B, self.C = tris[:, 0], tris[:, 1], tris[:, 2]
        self.lo = tris.reshape(-1, 3).min(0) - 0.05
        self.hi = tris.reshape(-1, 3).max(0) + 0.05
        self.margin = margin

    def hits(self, P):
        P = np.asarray(P, float)
        near = np.all((P > self.lo) & (P < self.hi), axis=1)
        out = np.zeros(len(P), bool)
        if not near.any():
            return out
        Q = P[near]
        d = point_tri_dist(Q, self.A, self.B, self.C).min(1)
        wn = winding(Q, self.A, self.B, self.C)
        out[near] = (d < self.margin) | (wn > 0.5)
        return out


def box_tris(c, s, R=np.eye(3)):
    c = np.asarray(c, float); s = np.asarray(s, float) / 2
    v = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]) * s
    v = v @ R.T + c
    F = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    return np.array([[v[a], v[b], v[cc]] for a, b, cc in F])


def palm_proxy_tris(W):
    """Palm collision proxy in world space (shortened palmar-front edge so fingers can fold)."""
    Wr = W['palm']
    L = float(np.linalg.norm(BIND['wrist'][:3, 3]))
    kn = -0.020 * K
    c = np.array([0.003, 0.004 * K, (L + kn) / 2 + 0.004])
    s = np.array([PALM_W * K * 0.92, PALM_T * K * 0.82, (L - kn) - 0.01])
    t = box_tris(c, s)
    return t @ Wr[:3, :3].T + Wr[:3, 3]


# --- grasp closing ------------------------------------------------------------------------------
LIMITS = {'proximal': 92.0, 'intermediate': 108.0, 'distal': 78.0}
WEIGHT = {'proximal': 1.0, 'intermediate': 1.25, 'distal': 0.85}
TH_LIMITS = {'thumb_metacarpal': 40.0, 'thumb_proximal': 60.0, 'thumb_distal': 75.0}
TH_WEIGHT = {'thumb_metacarpal': 0.6, 'thumb_proximal': 1.0, 'thumb_distal': 1.0}


def close_chain(angles, root, chain, limits, weights, obstacles, step=2.0, start=None, self_palm=True):
    """Coupled closing of one finger chain until each link touches an obstacle (see module doc)."""
    a = {j: list(angles.get(j, (0.0, 0.0))) + [0.0] * (3 - len(angles.get(j, (0.0, 0.0)))) for j in chain}
    if start:
        for j, v in start.items():
            a[j][0] = v
    active = [True] * len(chain)
    samples = {j: seg_samples(j) for j in chain}
    def collide(ang):
        full = dict(angles); full.update({j: tuple(v) for j, v in ang.items()})
        W = fk(full, root)
        obs = list(obstacles)
        if self_palm:
            obs.append(Obstacle(palm_proxy_tris(W), margin=0.001))
        res = []
        for j in chain:
            P = samples[j] @ W[j][:3, :3].T + W[j][:3, 3]
            res.append(any(o.hits(P).any() for o in obs))
        return res
    ignore = set()
    collide_raw = collide
    def collide_f(ang):
        r = collide_raw(ang)
        return [h and (i not in ignore) for i, h in enumerate(r)]
    h0 = collide(a)
    ext = 0
    while any(h0) and ext < 5:
        ext += 1
        a[chain[0]][0] -= 8.0
        h0 = collide(a)
    if any(h0):
        ignore = set(i for i, h in enumerate(h0) if h)
    collide = collide_f
    for _ in range(80):
        if not any(active):
            break
        trial = {j: list(v) for j, v in a.items()}
        for i, j in enumerate(chain):
            if active[i]:
                trial[j][0] = min(trial[j][0] + step * weights[i], limits[i])
                if trial[j][0] >= limits[i]:
                    active[i] = False
        hit = collide(trial)
        if any(hit):
            first = hit.index(True)
            for i in range(first + 1):
                active[i] = False
            # keep the increments of joints distal to the first hit only if they are themselves free
            for i, j in enumerate(chain):
                if i <= first:
                    trial[j][0] = a[j][0]
            if any(collide(trial)):
                continue
        a = trial
    out = dict(angles)
    out.update({j: tuple(v) for j, v in a.items()})
    return out


def finger_chain(f):
    return [f'{f}_proximal', f'{f}_intermediate', f'{f}_distal']


def close_hand(angles, root, obstacles, fingers=('index', 'middle', 'ring', 'little'), thumb=True, step=2.0):
    for f in fingers:
        ch = finger_chain(f)
        angles = close_chain(angles, root, ch, [LIMITS[c.split('_')[1]] for c in ch],
                             [WEIGHT[c.split('_')[1]] for c in ch], obstacles, step)
    if thumb:
        ch = ['thumb_metacarpal', 'thumb_proximal', 'thumb_distal']
        angles = close_chain(angles, root, ch, [TH_LIMITS[c] for c in ch], [TH_WEIGHT[c] for c in ch], obstacles, step)
    return angles


def world_joints(angles, root):
    W = fk(angles, root)
    return [W[s] for s in SHORT]


def pose_record(W_list):
    out = []
    for M in W_list:
        q = quat(M[:3, :3])
        out.append([round(float(v), 6) for v in list(M[:3, 3]) + list(q)])
    return out


# --- segment geometry (joint-local, right hand) as blib part specs ----------------------------------
GLOVE, SKIN = 'glove', 'skin'


def segment_parts(seg):
    """Part specs (blib.make_part) for one rigid segment in its proximal joint's frame (-Z to the tip)."""
    L, w, h = seg_dims(seg)
    f = seg.split('_')[0]
    parts = []
    if seg == 'palm':
        Wi = np.linalg.inv(BIND['wrist'])
        def loc(p):
            return list((Wi @ np.append(p, 1.0))[:3])
        kn = {g: BIND[f'{g}_proximal'][:3, 3] for g in FINGERS}
        ht = PALM_T * K / 2
        # Rounded, tapered palm: elliptical sections from the knuckle line to the wrist (wider at the
        # knuckles, domed on the back, flatter on the palm side), plus the thenar pad by the thumb.
        pts = []
        for z, hw, top, bot in ((-0.033, 0.047, 0.80, 0.70), (-0.020, 0.050, 0.98, 0.92), (0.000, 0.050, 1.06, 1.04),
                                (0.022, 0.046, 1.02, 1.04), (0.040, 0.040, 0.92, 0.94), (0.050, 0.035, 0.84, 0.86)):
            for k in range(14):
                t = 2 * math.pi * k / 14
                cx, cy = math.cos(t), math.sin(t)
                ry = top if cy > 0 else bot
                # superellipse: fuller sides than an ellipse, still no hard box corners
                sx = math.copysign(abs(cx) ** 0.7, cx)
                sy = math.copysign(abs(cy) ** 0.85, cy)
                pts.append(np.array([hw * K * sx, ht * ry * sy, z * K]))
        for x, y, z in ((-0.036, -1.25, 0.010), (-0.030, -1.32, 0.026), (-0.041, -1.10, 0.030), (-0.024, -1.20, 0.040),
                        (0.034, -1.12, 0.032), (0.038, -1.05, 0.016)):
            pts.append(np.array([x * K, ht * y, z * K]))
        front = back = mid = []
        mid = pts
        parts.append(dict(name='palm', mat=GLOVE, kind='hull', pts=[loc(p) for p in front + back + mid],
                          decals=[dict(type='rect', box=[(-0.05, 0.0, -0.06), (0.05, 0.03, -0.035)], normal='y', mat='leather')]))
        # knuckles: one rounded bump per finger on the back of the glove, over each MCP joint
        for g, r in (('index', 0.0108), ('middle', 0.0112), ('ring', 0.0104), ('little', 0.0092)):
            c = kn[g] + np.array([0.0, ht * 0.62, 0.003 * K])
            parts.append(dict(name=f'knuckle_{g}', mat='leather', kind='sphere', c=loc(c), r=r * K, seg=(8, 5),
                              scale3=(1.0, 0.72, 1.05)))
        # wrist cuff (behind the wrist joint, +Z)
        parts.append(dict(name='cuff', mat='leather', kind='lathe', p0=(0, 0, -0.004), p1=(0, 0, 0.034 * K), n=12,
                          prof=[(0.0, 0.98), (0.15, 1.06), (0.85, 1.06), (1.0, 0.96)], scale2=(ht * 1.1, 0.037 * K),
                          decals=[dict(type='rect', box=[(-0.06, -0.06, 0.012), (0.06, 0.06, 0.022)], normal='x,-x,y,-y', mat='red')]))
        # Duke's bare, muscular forearm behind the cuff, so the hand doesn't end in a cut-off stump
        parts.append(dict(name='forearm', mat=SKIN, kind='lathe', p0=(0, 0, 0.030 * K), p1=(0, 0, 0.200), n=12,
                          prof=[(0.0, 0.96), (0.25, 1.10), (0.55, 1.16), (0.85, 1.08), (1.0, 0.98)],
                          scale2=(ht * 1.08, 0.036 * K)))
        return parts
    mat = GLOVE if (seg.endswith('proximal') or seg == 'thumb_metacarpal') else SKIN
    back = 0.30 * h
    # Rounded, slightly tapered phalanges with domed ends; a joint ball at the proximal end fills the
    # bend so flexed fingers read as knuckles instead of gaps between blocks.
    if seg.endswith('distal'):
        tip = 0.30 * h
        prof = [(0.0, 0.62), (0.10, 0.90), (0.55, 0.95), (0.80, 0.84), (0.93, 0.60), (1.0, 0.28)]
        decals = [dict(type='rect', box=[(-w * 0.34, h * 0.18, -L - 0.01), (w * 0.34, h, -L * 0.45)], normal='y', mat='nail')]
    else:
        tip = 0.22 * h
        prof = [(0.0, 0.60), (0.10, 0.90), (0.25, 1.0), (0.75, 0.95), (0.92, 0.86), (1.0, 0.62)]
        decals = []
        if mat == GLOVE and seg != 'thumb_metacarpal':
            decals = [dict(type='rect', box=[(-w, -h, -L * 0.98), (w, h, -L * 0.82)], mat='leather')]  # glove hem
    if seg == 'thumb_metacarpal':
        back = 0.25 * h
        prof = [(0.0, 0.70), (0.2, 1.0), (0.8, 0.92), (1.0, 0.70)]
    parts.append(dict(name=seg, mat=mat, kind='lathe', p0=(0, 0, back), p1=(0, 0, -L - tip), n=10, prof=prof,
                      scale2=(h / 2, w / 2), decals=decals))
    if seg.endswith('intermediate') or seg.endswith('distal') or seg == 'thumb_proximal' or seg == 'thumb_distal':
        r = 0.5 * min(w, h) * 0.98
        parts.append(dict(name=seg + '_joint', mat=mat, kind='sphere', c=(0.0, 0.03 * h, 0.0), r=r, seg=(8, 5),
                          scale3=(w / (2 * r) * 0.96, h / (2 * r) * 0.96, 1.0)))
    return parts
