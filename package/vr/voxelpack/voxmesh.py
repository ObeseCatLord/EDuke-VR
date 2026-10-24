"""Voxel grid -> closed blocky mesh with a nearest-filter texture atlas (pure numpy + Pillow).

mesh_parts(parts) where each part is dict(
    solid : bool [X, Y, Z]       occupied cells (interior filled)
    rgb   : uint8 [X, Y, Z, 3]   colour of each cell (only exposed cells are read)
    glow  : bool [X, Y, Z]       optional, emissive cells (written to the glow map)
    label : int [X, Y, Z]        optional, greedy rectangles never span two labels (skinned meshes)
    A     : 3x4 affine           grid corner coordinates (cell (i,j,k) spans [i,i+1]x[j,j+1]x[k,k+1]) -> output units
)
returns dict(pos[nv,3], nrm[nv,3], tris[nt,3], st[nv,2], tex (H,W,4 uint8), glow (H,W,4 uint8),
             part_ranges[(v0, v1)], stats)

Meshing:
  * face culling against the (filled) solid grid, so every exposed cell face is emitted exactly once;
  * greedy merge of coplanar exposed faces into rectangles, IGNORING colour (each rectangle gets its own
    w x h texel patch in the atlas, one texel per cell face, so colours stay exact);
  * T-junction removal: every rectangle corner that lies on another rectangle's edge is inserted into that
    edge, and such rectangles are fanned from a centre vertex, so the shell is watertight when vertices
    are welded by position (MD3 vertices are split per rectangle because each carries its own UVs);
  * winding is CCW-outward in the output frame (flipped automatically when the affine has det < 0).
"""
import numpy as np
from PIL import Image

AXES = {0: (1, 2), 1: (2, 0), 2: (0, 1)}   # (u, v) axes with u x v = +axis


def _greedy(mask):
    """mask: bool [U, V] -> list of (u0, v0, w, h) rectangles covering mask exactly."""
    used = np.zeros_like(mask)
    rects = []
    U, V = mask.shape
    for u, v in np.argwhere(mask):
        if used[u, v]:
            continue
        w = 1
        while u + w < U and mask[u + w, v] and not used[u + w, v]:
            w += 1
        h = 1
        while v + h < V and mask[u:u + w, v + h].all() and not used[u:u + w, v + h].any():
            h += 1
        used[u:u + w, v:v + h] = True
        rects.append((int(u), int(v), w, h))
    return rects


def _slices(solid):
    """Exposed-face slices: (axis, sign, plane, slice index, 2-D face mask [U, V])."""
    X = np.pad(solid, 1)
    for a in range(3):
        for s in (1, -1):
            nb = np.roll(X, -s, axis=a)
            face = (X & ~nb)[1:-1, 1:-1, 1:-1]
            u_ax, v_ax = AXES[a]
            rem = [x for x in range(3) if x != a]
            for i in range(solid.shape[a]):
                sl = np.take(face, i, axis=a)
                if rem != [u_ax, v_ax]:
                    sl = sl.T
                if sl.any():
                    yield a, s, (i + 1 if s > 0 else i), i, sl


def _label_slice(label, a, i):
    """Label grid slice i along axis a in the (u, v) layout of _slices."""
    u_ax, v_ax = AXES[a]
    rem = [x for x in range(3) if x != a]
    sl = np.take(label, i, axis=a)
    return sl.T if rem != [u_ax, v_ax] else sl


def _corner(a, plane, u, v):
    p = [0, 0, 0]
    p[a] = plane
    ua, va = AXES[a]
    p[ua] = u
    p[va] = v
    return tuple(p)


def _pack(sizes, pad, min_w=16):
    """Shelf packing; sizes [(w, h)] in texels -> positions, atlas (W, H)."""
    order = sorted(range(len(sizes)), key=lambda k: (-sizes[k][1], -sizes[k][0]))
    area = sum((w + 2 * pad) * (h + 2 * pad) for w, h in sizes)
    W = min_w
    while W * W < area * 1.2:
        W *= 2
    while W < max(w + 2 * pad for w, h in sizes):
        W *= 2
    while True:
        pos = [None] * len(sizes)
        x = y = shelf = 0
        for k in order:
            w, h = sizes[k][0] + 2 * pad, sizes[k][1] + 2 * pad
            if x + w > W:
                x, y = 0, y + shelf
                shelf = 0
            pos[k] = (x, y)
            x += w
            shelf = max(shelf, h)
        Hh = y + shelf
        H = 16
        while H < Hh:
            H *= 2
        if H <= 2 * W:
            return pos, (W, H)
        W *= 2


def _earclip(n_loop, collinear, on_seg):
    """Triangulate a convex loop 0..n-1 (some points collinear on edges) without a centre vertex and
    without zero-area triangles. collinear(i, j, k) -> bool on loop indices."""
    idx = list(range(n_loop))
    tris = []
    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        m = len(idx)
        for t in range(m):
            p, c, q = idx[(t - 1) % m], idx[t], idx[(t + 1) % m]
            if not collinear(p, c, q) and not any(on_seg(p, r, q) for r in idx if r not in (p, c, q)):
                tris.append((p, c, q))
                idx.pop(t)
                break
        else:
            break
    if len(idx) == 3 and not collinear(*idx):
        tris.append(tuple(idx))
    return tris


def mesh_parts(parts, pad=1, min_atlas_w=16):
    from scipy import ndimage
    # 1) slices -> connected components (one texture patch each) -> greedy rectangles
    comps = []      # dict(part, a, s, plane, i, u0, v0, w, h, rects)
    corners = [set() for _ in parts]
    for pi, P in enumerate(parts):
        for a, s, plane, i, sl in _slices(P['solid']):
            lab, n = ndimage.label(sl)
            for ci, bb in enumerate(ndimage.find_objects(lab)):
                m = lab[bb] == ci + 1
                cu0, cv0 = bb[0].start, bb[1].start
                if P.get('label') is None:
                    rects = [(cu0 + u0, cv0 + v0, w, h) for (u0, v0, w, h) in _greedy(m)]
                else:
                    # rectangles never span two labels (e.g. two bones of a skinned hand), so the mesh has
                    # vertices on every label border
                    L2 = _label_slice(P['label'], a, i)[bb]
                    rects = [(cu0 + u0, cv0 + v0, w, h) for lv in np.unique(L2[m])
                             for (u0, v0, w, h) in _greedy(m & (L2 == lv))]
                comps.append(dict(part=pi, a=a, s=s, plane=plane, i=i, u0=cu0, v0=cv0, w=m.shape[0], h=m.shape[1],
                                  mask=m, rects=rects))
                for (u0, v0, w, h) in rects:
                    for (u, v) in ((u0, v0), (u0 + w, v0), (u0 + w, v0 + h), (u0, v0 + h)):
                        corners[pi].add(_corner(a, plane, u, v))
    comps.sort(key=lambda c: c['part'])
    tf = [P.get('tex_f', 1) for P in parts]
    pos_atlas, (AW, AH) = _pack([(c['w'] * tf[c['part']], c['h'] * tf[c['part']]) for c in comps], pad,
                                min_w=min_atlas_w)
    tex = np.zeros((AH, AW, 4), np.uint8)
    glow = np.zeros((AH, AW, 4), np.uint8)
    glow[..., 3] = 255
    V, N, ST, T = [], [], [], []
    part_ranges = [[None, None] for _ in parts]
    tri_ranges = [[None, None] for _ in parts]
    for k, C in enumerate(comps):
        pi, a, s, plane, i = C['part'], C['a'], C['s'], C['plane'], C['i']
        P = parts[pi]
        if part_ranges[pi][0] is None:
            part_ranges[pi][0] = len(V)
            tri_ranges[pi][0] = len(T)
        f = tf[pi]
        A = np.asarray(P['A'], float)
        L = A[:, :3]
        flip = np.linalg.det(L) < 0
        ua, va = AXES[a]
        u0, v0, w, h = C['u0'], C['v0'], C['w'], C['h']
        if f == 1:
            idx = [slice(None)] * 3
            idx[a] = i
            idx[ua] = slice(u0, u0 + w)
            idx[va] = slice(v0, v0 + h)
            sub = P['rgb'][tuple(idx)]
            gsub = P['glow'][tuple(idx)] if P.get('glow') is not None else None
            rem = [x for x in range(3) if x != a]
            if rem != [ua, va]:
                sub = np.transpose(sub, (1, 0, 2))
                if gsub is not None:
                    gsub = gsub.T
            # cells of the bbox outside the component: copy the nearest component cell (no stray colours)
            if not C['mask'].all():
                _, (iu, iv) = ndimage.distance_transform_edt(~C['mask'], return_indices=True)
                sub = sub[iu, iv]
                if gsub is not None:
                    gsub = gsub[iu, iv]
        else:
            # coarse geometry, fine texture: f x f texels per coarse face, sampled from the projected
            # fine-voxel colours seen through that face
            proj = P['proj'][(a, s)]
            j = (i + 1) * f - 1 if s > 0 else i * f
            idx = [slice(None)] * 3
            idx[a] = j
            idx[ua] = slice(u0 * f, (u0 + w) * f)
            idx[va] = slice(v0 * f, (v0 + h) * f)
            sub = proj[tuple(idx)]
            rem = [x for x in range(3) if x != a]
            if rem != [ua, va]:
                sub = np.transpose(sub, (1, 0, 2))
            gsub = None
        w_t, h_t = w * f, h * f
        px, py = pos_atlas[k]
        patch = np.pad(np.transpose(sub, (1, 0, 2)), ((pad, pad), (pad, pad), (0, 0)), mode='edge')
        tex[py:py + h_t + 2 * pad, px:px + w_t + 2 * pad, :3] = patch
        tex[py:py + h_t + 2 * pad, px:px + w_t + 2 * pad, 3] = 255
        if gsub is not None and gsub.any():
            gp = np.pad(gsub.T, ((pad, pad), (pad, pad)), mode='edge')
            gl = glow[py:py + h_t + 2 * pad, px:px + w_t + 2 * pad]
            gl[..., :3] = np.where(gp[..., None], patch, gl[..., :3])
        nrm = np.zeros(3)
        nrm[a] = s
        n_out = L @ nrm
        n_out /= np.linalg.norm(n_out)
        vid = {}

        def vert(uv):
            key = uv
            if key not in vid:
                p = np.array(_corner(a, plane, uv[0], uv[1]), float)
                V.append(A[:, :3] @ p + A[:, 3])
                N.append(n_out)
                ST.append(((px + pad + (uv[0] - u0) * f) / AW, (py + pad + (uv[1] - v0) * f) / AH))
                vid[key] = len(V) - 1
            return vid[key]

        rev = (s < 0) != flip
        for (ru0, rv0, rw, rh) in C['rects']:
            loop = []
            cs = [(ru0, rv0), (ru0 + rw, rv0), (ru0 + rw, rv0 + rh), (ru0, rv0 + rh)]
            for e in range(4):
                (ua0, va0), (ub0, vb0) = cs[e], cs[(e + 1) % 4]
                loop.append((ua0, va0))
                du, dv = int(np.sign(ub0 - ua0)), int(np.sign(vb0 - va0))
                n = max(abs(ub0 - ua0), abs(vb0 - va0))
                for t in range(1, n):
                    q = (ua0 + du * t, va0 + dv * t)
                    if _corner(a, plane, *q) in corners[pi]:
                        loop.append(q)

            def col(x, y, z, lp=loop):
                (x0, y0), (x1, y1), (x2, y2) = lp[x], lp[y], lp[z]
                return (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0) == 0
            def onseg(x, r, z, lp=loop):
                (x0, y0), (x1, y1), (x2, y2) = lp[x], lp[r], lp[z]
                if (x2 - x0) * (y1 - y0) - (y2 - y0) * (x1 - x0) != 0:
                    return False
                return min(x0, x2) <= x1 <= max(x0, x2) and min(y0, y2) <= y1 <= max(y0, y2)
            ids = [vert(q) for q in loop]
            tri_l = _earclip(len(loop), col, onseg)
            assert len(tri_l) == len(loop) - 2, (loop, tri_l)
            for (x, y, z) in tri_l:
                t3 = (ids[x], ids[y], ids[z])
                T.append((t3[0], t3[2], t3[1]) if rev else t3)
        part_ranges[pi][1] = len(V)
        tri_ranges[pi][1] = len(T)
    return dict(pos=np.array(V), nrm=np.array(N), tris=np.array(T, np.int64), st=np.array(ST), tex=tex, glow=glow,
                part_ranges=[tuple(r) for r in part_ranges], tri_ranges=[tuple(r) for r in tri_ranges],
                stats=dict(components=len(comps), rects=sum(len(c['rects']) for c in comps), atlas=(AW, AH)))


def signed_volume(pos, tris):
    A, B, C = pos[tris[:, 0]], pos[tris[:, 1]], pos[tris[:, 2]]
    return float(np.einsum('ij,ij->i', A, np.cross(B, C)).sum() / 6.0)


def weld_check(pos, tris, q=1.0 / 64):
    """Weld by quantised position; return (boundary_edges, nonmanifold_edges, components)."""
    key = np.round(pos / q).astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    t = inv[tris]
    t = t[(t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])]
    e = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]])
    und = np.sort(e, 1)
    uk, cnt = np.unique(und, axis=0, return_counts=True)
    # directed edge balance: every directed edge should be matched by its reverse
    from collections import Counter
    dc = Counter(map(tuple, e))
    unbalanced = sum(1 for (x, y), c in dc.items() if dc.get((y, x), 0) != c)
    # components (union-find over triangles' vertices)
    par = np.arange(inv.max() + 1)

    def f(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    for a_, b_, c_ in t:
        ra, rb, rc = f(a_), f(b_), f(c_)
        par[rb] = ra
        par[f(rc)] = ra
    roots = {f(x) for x in np.unique(t)}
    return dict(edges=int(len(uk)), odd_edges=int((cnt % 2 == 1).sum()), nonmanifold_edges=int((cnt > 2).sum()),
                unbalanced_directed=int(unbalanced), components=len(roots))


def save_png(arr, path):
    Image.fromarray(arr, 'RGBA').save(path)


def coarse_part(grid, palette, solid, f, A, occ_frac=0.375):
    """Geometry at 1/f resolution (block solid when >= occ_frac of its fine cells are solid), texture at full
    resolution (f x f texels per block face = colour of the first solid fine cell seen through the face).
    grid: palette index of every solid fine cell (interior filled with the nearest surface colour),
    solid: fine occupancy (filled). A maps COARSE grid corners -> output. Returns a mesh_parts part."""
    from kvx import fill_solid
    pads = [(0, (-n) % f) for n in grid.shape]
    S = np.pad(solid, pads)
    G = np.pad(np.where(solid, grid, 0), pads)
    X, Y, Z = (n // f for n in S.shape)
    occ = S.reshape(X, f, Y, f, Z, f).mean((1, 3, 5)) >= occ_frac
    occ = fill_solid(occ)
    rgbf = palette[np.clip(G, 0, 255)]
    proj = {}
    for a in range(3):
        n = S.shape[a]
        shape = [1, 1, 1]; shape[a] = n
        ar = np.arange(n).reshape(shape)
        last_le = np.maximum.accumulate(np.where(S, ar, -1), axis=a)
        first_ge = np.flip(np.minimum.accumulate(np.flip(np.where(S, ar, n), a), axis=a), a)
        for s, ind in ((1, last_le), (-1, first_ge)):
            other = first_ge if s > 0 else last_le
            ind = np.where((ind < 0) | (ind >= n), other, ind)
            ind = np.clip(ind, 0, n - 1)
            proj[(a, s)] = np.take_along_axis(rgbf, np.expand_dims(ind, -1).repeat(3, -1), axis=a)
    return dict(solid=occ, rgb=None, A=A, tex_f=f, proj=proj)


def nearest_colour_fill(grid, solid):
    """Palette index for every solid cell: stored colour, or the nearest stored cell's colour inside."""
    from scipy import ndimage
    stored = grid >= 0
    _, ind = ndimage.distance_transform_edt(~stored, return_indices=True)
    filled = grid[tuple(ind)]
    return np.where(solid, filled, -1)
