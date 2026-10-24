"""KVX (Build engine / SLAB6 voxel) reader, pure numpy.

Run anything that reads the untrusted source with `python3 -I`.

read_kvx(path) -> dict(
    grid   : int16 array [xsiz, ysiz, zsiz]; palette index of each stored (surface) voxel, -1 = not stored
    solid  : bool array, stored voxels plus the hollow interior filled in (flood fill from outside)
    pivot  : (px, py, pz) in voxel units (KVX 8.8 fixed point / 256); z is measured downward from the top
    palette: uint8 [256, 3] (KVX 6-bit palette scaled to 8 bit)
    size   : (xsiz, ysiz, zsiz))

KVX axes: x and y are horizontal, z points DOWN (z = 0 is the top slice). Only the first mip level is read.
"""
import struct
import numpy as np


def read_kvx(path):
    d = open(path, 'rb').read()
    numbytes, xs, ys, zs, px, py, pz = struct.unpack_from('<7i', d, 0)
    assert 0 < xs <= 1024 and 0 < ys <= 1024 and 0 < zs <= 255, (xs, ys, zs)
    base = 28
    xoff = np.frombuffer(d, '<i4', xs + 1, base)
    xyoff = np.frombuffer(d, '<u2', xs * (ys + 1), base + (xs + 1) * 4).reshape(xs, ys + 1)
    grid = np.full((xs, ys, zs), -1, np.int16)
    vis = np.zeros((xs, ys, zs), np.uint8)
    for x in range(xs):
        for y in range(ys):
            o = base + int(xoff[x]) + int(xyoff[x, y])
            e = base + int(xoff[x]) + int(xyoff[x, y + 1])
            while o < e:
                ztop, zleng, cull = d[o], d[o + 1], d[o + 2]
                cols = np.frombuffer(d, np.uint8, zleng, o + 3)
                z1 = min(zs, ztop + zleng)
                grid[x, y, ztop:z1] = cols[:z1 - ztop]
                vis[x, y, ztop:z1] = cull
                o += 3 + zleng
    pal = np.frombuffer(d[-768:], np.uint8).reshape(256, 3).astype(np.int32)
    pal = np.clip(pal * 255 // 63, 0, 255).astype(np.uint8)
    return dict(grid=grid, vis=vis, solid=fill_solid(grid >= 0), pivot=(px / 256.0, py / 256.0, pz / 256.0),
                palette=pal, size=(xs, ys, zs), numbytes=numbytes)


def fill_solid(stored):
    """Stored voxels + every empty cell not reachable from outside (6-connected flood fill)."""
    pad = np.pad(stored, 1)
    outside = np.zeros_like(pad)
    outside[0, :, :] = outside[-1, :, :] = True
    outside[:, 0, :] = outside[:, -1, :] = True
    outside[:, :, 0] = outside[:, :, -1] = True
    outside &= ~pad
    empty = ~pad
    while True:
        grow = outside.copy()
        grow[1:] |= outside[:-1]; grow[:-1] |= outside[1:]
        grow[:, 1:] |= outside[:, :-1]; grow[:, :-1] |= outside[:, 1:]
        grow[:, :, 1:] |= outside[:, :, :-1]; grow[:, :, :-1] |= outside[:, :, 1:]
        grow &= empty
        if grow.sum() == outside.sum():
            break
        outside = grow
    return ~outside[1:-1, 1:-1, 1:-1]
