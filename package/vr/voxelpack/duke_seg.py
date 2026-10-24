"""Segmentation helpers for the APLAYER (Duke) voxels: gun, head (hair), hands, torso.

Duke faces KVX +y, his left is KVX +x, KVX z points down. Palette indices are the Duke 3D palette.
"""
import numpy as np
from scipy import ndimage

GREY = set(range(2, 32))            # Duke 3D grey ramp (0/1 = near black used by boots/shadows excluded)
RED = set(range(128, 136))          # tank top
SKIN = set(range(36, 56))           # skin / tan ramp
HAIR = set(range(144, 160))         # yellow ramp (flat-top hair)
BLUE = set(range(80, 96))           # jeans


def isin(grid, s):
    return np.isin(grid, np.array(sorted(s)))


def gun_mask(grid, radius=3.6, back=40):
    """Voxels of the gun Duke carries: the metal voxels clearly in front of the tank top seed a long axis;
    every non-skin/cloth/hair voxel within `radius` of that axis (up to `back` voxels behind the seed) that is
    connected to the seed is the gun."""
    stored = grid >= 0
    red = isin(grid, RED)
    hair = isin(grid, HAIR)
    metal = isin(grid, GREY | {0, 1} | set(range(160, 176)))
    body = isin(grid, SKIN | RED | HAIR | BLUE)
    if red.sum() < 20:
        return np.zeros_like(stored)
    ry = np.argwhere(red)[:, 1]
    y_f = np.percentile(ry, 97)
    zs = np.nonzero(stored.any((0, 1)))[0]
    z_knee = zs.min() + 0.62 * (zs.max() - zs.min())
    zz = np.arange(grid.shape[2])[None, None, :]
    yy = np.arange(grid.shape[1])[None, :, None]
    near_hair = ndimage.binary_dilation(hair, np.ones((3, 3, 3)), iterations=4)
    seeds = metal & ~near_hair & (zz < z_knee) & (yy > y_f + 2)
    lab, n = ndimage.label(seeds, structure=np.ones((3, 3, 3)))
    if n == 0:
        return np.zeros_like(stored)
    sizes = ndimage.sum(seeds, lab, range(1, n + 1))
    big = int(np.argmax(sizes)) + 1
    if sizes[big - 1] < 30:
        return np.zeros_like(stored)
    S = np.argwhere(lab == big).astype(float)
    c = S.mean(0)
    w, V = np.linalg.eigh(np.cov((S - c).T))
    d = V[:, -1]
    if d[1] < 0:
        d = -d
    tS = (S - c) @ d
    P = np.argwhere(stored & ~body).astype(float)
    for it in range(3):
        rel = P - c
        t = rel @ d
        dist = np.linalg.norm(rel - np.outer(t, d), axis=1)
        sel = (dist <= radius) & (t >= tS.min() - back) & (t <= tS.max() + 2)
        m = np.zeros_like(stored)
        m[tuple(P[sel].astype(int).T)] = True
        m |= (lab == big)
        lab2, n2 = ndimage.label(m, structure=np.ones((3, 3, 3)))
        m = lab2 == lab2[tuple(S[0].astype(int))]
        # refit the axis on everything selected so far (the seed may be only the muzzle end)
        Q = np.argwhere(m).astype(float)
        c = Q.mean(0)
        w, V = np.linalg.eigh(np.cov((Q - c).T))
        d = V[:, -1]
        if d[1] < 0:
            d = -d
        tS = (S - c) @ d
    # the magazine / grip hanging under the gun: non-body voxels just below the gun, within its length
    G = np.argwhere(m).astype(float)
    tg = (G - c) @ d
    near = ndimage.binary_dilation(m, np.ones((3, 3, 3)), iterations=4) & stored & ~body & ~m
    Q = np.argwhere(near).astype(float)
    if len(Q):
        tq = (Q - c) @ d
        relq = Q - c - np.outer(tq, d)
        below = relq[:, 2] > 0.5            # KVX z down
        ok = below & (tq >= tg.min()) & (tq <= tg.max())
        m2 = m.copy()
        m2[tuple(Q[ok].astype(int).T)] = True
        lab3, _ = ndimage.label(m2, structure=np.ones((3, 3, 3)))
        m = lab3 == lab3[tuple(S[0].astype(int))]
    return m


def gun_axis(grid, m):
    """(centre, unit direction toward the muzzle) of a gun mask, in grid coordinates (cell centres)."""
    P = np.argwhere(m).astype(float) + 0.5
    c = P.mean(0)
    w, V = np.linalg.eigh(np.cov((P - c).T))
    d = V[:, -1]
    if d[1] < 0:
        d = -d
    return c, d
