"""Closed triangle mesh (an original v6 model) -> solid voxel grid coloured from its texture in the Duke
Nukem 3D palette, plus the per-vertex motion that carries v6's animation over to the voxel mesh.

voxelise(P, tris, st, tex, glow_tex, s, palette) -> dict(solid, rgb, glow, A, origin, s, stats)
  P metres (MD3 axes), st texture coords (t = 0 top), tex/glow_tex uint8 RGBA arrays (glow may be None).
  * occupancy: each voxel is split into 3x3x3 sub-cells whose centres are tested with an exact ray-parity
    winding count along +Z (outward-wound closed shells); a voxel is solid when >= 1/2 of its sub-cells are
    inside. Thin features (blades, sights, wires) that no voxel half-covers are kept: a voxel that is at least
    15% covered and touches no solid voxel is solid, so parts thinner than a voxel stay one voxel thick;
    one-voxel gaps between solid voxels in a covered region are bridged.
  * colour: every exposed voxel takes the texel at the nearest point of the original surface (dense
    barycentric samples, KD tree), mapped to the nearest palette colour (no dithering); hidden cells take
    the nearest exposed colour. A voxel glows when its texel is lit in the glow map.

motion(rest, frames, k) / apply_motion(...): local similarity transforms (rotation, uniform scale,
translation) fitted per original vertex and frame on its k nearest neighbours (Umeyama); a voxel vertex
follows the transform of the nearest original vertex, so rigid parts move rigidly, collapsed parts
collapse, and coincident vertices stay welded.
"""
import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree
from kvx import fill_solid
from kitbash import nearest_index


def _winding_grid(P, tris, lo, h, shape):
    """Inside test of sub-cell centres lo + (i + 0.5) * h on a grid of `shape` (ray parity along +Z)."""
    nx, ny, nz = shape
    D = np.zeros((nx, ny, nz + 1), np.int32)
    A, B, C = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
    nzs = np.cross(B - A, C - A)[:, 2]
    # a tiny irrational offset keeps ray/edge coincidences away
    off = np.array([0.5 + 1.3e-4, 0.5 + 2.7e-4])
    for a, b, c, nzt in zip(A, B, C, nzs):
        if abs(nzt) < 1e-14:
            continue
        x0, x1 = min(a[0], b[0], c[0]), max(a[0], b[0], c[0])
        y0, y1 = min(a[1], b[1], c[1]), max(a[1], b[1], c[1])
        i0 = max(int(np.ceil((x0 - lo[0]) / h - off[0])), 0)
        i1 = min(int(np.floor((x1 - lo[0]) / h - off[0])), nx - 1)
        j0 = max(int(np.ceil((y0 - lo[1]) / h - off[1])), 0)
        j1 = min(int(np.floor((y1 - lo[1]) / h - off[1])), ny - 1)
        if i0 > i1 or j0 > j1:
            continue
        I, J = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1), indexing='ij')
        px = lo[0] + (I + off[0]) * h
        py = lo[1] + (J + off[1]) * h
        den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        w0 = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / den
        w1 = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / den
        w2 = 1 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        z = w0 * a[2] + w1 * b[2] + w2 * c[2]
        k = np.clip(np.ceil((z - lo[2]) / h - 0.5), 0, nz).astype(int)   # cells with centre below z: 0..k-1
        sgn = 1 if nzt > 0 else -1
        ii, jj, kk = I[inside], J[inside], k[inside]
        np.add.at(D, (ii, jj, np.zeros_like(kk)), sgn)
        np.add.at(D, (ii, jj, kk), -sgn)
    return np.cumsum(D, axis=2)[:, :, :nz] > 0


def surface_samples(P, tris, st, spacing):
    """Dense barycentric samples of every triangle: positions and texture coordinates."""
    A, B, C = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
    L = np.maximum.reduce([np.linalg.norm(B - A, axis=1), np.linalg.norm(C - B, axis=1), np.linalg.norm(A - C, axis=1)])
    ks = np.clip(np.ceil(L / spacing).astype(int), 1, 200)
    pos, uv = [], []
    for k in np.unique(ks):
        sel = np.nonzero(ks == k)[0]
        bw = np.array([(i / k, j / k, 1 - i / k - j / k) for i in range(k + 1) for j in range(k + 1 - i)])
        bw = 0.98 * bw + 0.02 / 3          # stay off the edges (each sample belongs to its own triangle)
        T = tris[sel]
        pos.append(np.einsum('sb,tbc->tsc', bw, np.stack([P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]], 1)).reshape(-1, 3))
        uv.append(np.einsum('sb,tbc->tsc', bw, np.stack([st[T[:, 0]], st[T[:, 1]], st[T[:, 2]]], 1)).reshape(-1, 2))
    return np.concatenate(pos), np.concatenate(uv)


def texel(tex, uv):
    h, w = tex.shape[:2]
    iu = np.clip((np.mod(uv[:, 0], 1.0) * w).astype(int), 0, w - 1)
    iv = np.clip((np.mod(uv[:, 1], 1.0) * h).astype(int), 0, h - 1)
    return tex[iv, iu]


def exposed(solid):
    P = np.pad(solid, 1)
    e = np.zeros_like(solid)
    for a in range(3):
        for sft in (1, -1):
            e |= solid & ~np.roll(P, sft, axis=a)[1:-1, 1:-1, 1:-1]
    return e


def voxelise(P, tris, st, tex, glow_tex, s, palette, sub=3):
    P = np.asarray(P, float)
    lo = P.min(0) - s
    n = np.ceil((P.max(0) + s - lo) / s).astype(int)
    h = s / sub
    inside = _winding_grid(P, tris, lo, h, tuple(n * sub))
    frac = inside.reshape(n[0], sub, n[1], sub, n[2], sub).mean((1, 3, 5))
    solid = frac >= 0.5
    near = ndimage.binary_dilation(solid, structure=ndimage.generate_binary_structure(3, 1))
    thin = (frac >= 0.15) & ~near
    solid |= thin
    for a in range(3):          # bridge one-voxel gaps inside covered regions
        lo_n = np.roll(solid, 1, axis=a)
        hi_n = np.roll(solid, -1, axis=a)
        solid |= (frac >= 0.3) & lo_n & hi_n
    solid = fill_solid(solid)
    # colour
    sp, suv = surface_samples(P, tris, st, s / 3)
    tree = cKDTree(sp)
    ex = exposed(solid)
    idx = np.argwhere(ex)
    centres = lo + (idx + 0.5) * s
    _, nearest = tree.query(centres)
    col = texel(tex, suv[nearest])[:, :3]
    pidx = nearest_index(col, palette[:255])
    rgb = np.zeros(solid.shape + (3,), np.uint8)
    rgb[tuple(idx.T)] = palette[pidx]
    glow = np.zeros(solid.shape, bool)
    if glow_tex is not None:
        g = texel(glow_tex, suv[nearest])[:, :3]
        glow[tuple(idx.T)] = g.max(1) > 40
    _, ind = ndimage.distance_transform_edt(~ex, return_indices=True)
    rgb = np.where(solid[..., None], rgb[tuple(ind)], 0).astype(np.uint8)
    A = np.zeros((3, 4))
    A[0, 0] = A[1, 1] = A[2, 2] = s * 64
    A[:, 3] = lo * 64
    return dict(solid=solid, rgb=rgb, glow=glow, A=A, origin=lo, s=s,
                stats=dict(grid=[int(v) for v in n], voxels=int(solid.sum()), thin_rescued=int(thin.sum()),
                           metres_per_voxel=round(float(s), 6)))


# ------------------------------------------------------------------ motion transfer
def umeyama(src, dst):
    """Batched similarity fit dst ~ c R src + t; src, dst [..., k, 3] -> c [...], R [..., 3, 3], t [..., 3]."""
    ms, md = src.mean(-2, keepdims=True), dst.mean(-2, keepdims=True)
    S, Dd = src - ms, dst - md
    var = (S ** 2).sum((-1, -2)) / src.shape[-2]
    cov = np.einsum('...ki,...kj->...ij', Dd, S) / src.shape[-2]
    U, sig, Vt = np.linalg.svd(cov)
    d = np.sign(np.linalg.det(U @ Vt))
    E = np.ones(sig.shape)
    E[..., 2] = d
    R = U @ (E[..., None] * Vt)
    c = (sig * E).sum(-1) / np.maximum(var, 1e-18)
    t = md[..., 0, :] - c[..., None] * np.einsum('...ij,...j->...i', R, ms[..., 0, :])
    return c, R, t


def motion(rest, frames, k=12):
    """rest [nv, 3], frames [nf, nv, 3] -> per frame and vertex (c, R, t) from the k-neighbourhood fits."""
    rest = np.asarray(rest, float)
    tree = cKDTree(rest)
    k = min(k, len(rest))
    _, nb = tree.query(rest, k=k)
    src = rest[nb]
    out = []
    for F in frames:
        out.append(umeyama(src, np.asarray(F, float)[nb]))
    return tree, out


def apply_motion(tree, fits, pts):
    """Voxel vertices pts [n, 3] (metres) -> [nf, n, 3] following their nearest original vertex."""
    _, j = tree.query(pts)
    res = []
    for c, R, t in fits:
        res.append(c[j, None] * np.einsum('nij,nj->ni', R[j], pts) + t[j])
    return np.array(res)
