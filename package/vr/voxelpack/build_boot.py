#!/usr/bin/env python3
"""Mighty Foot boot from the Voxel Duke Nukem 3D leg gib voxels/player/1536_BOOT.kvx.

python3 -I scripts/build_boot.py

v6 vr_boot contract: origin at the ankle joint centre, +X toe, +Y LEFT, +Z up (true-handed, NO Y mirror),
64 units/m, one surface `vr_boot` (shader vr_boot.png), one frame `rest`, tags tag_ankle (origin) and tag_toe
(bottom-front of the toe cap), positive signed volume. The gib is cut 0.344 m above the sole (the height of
the v6 boot + jeans), which removes its bloody top; the cut is closed by the mesher.
"""
import json, sys, os
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('EDUKE32_VOXEL_PACK', HERE.parent))   # the pack folder being built
sys.path.insert(0, str(HERE))
from kvx import read_kvx, fill_solid  # noqa: E402
from voxmesh import mesh_parts, signed_volume, weld_check, save_png  # noqa: E402
from md3io import write_md3  # noqa: E402

SRC = ROOT / 'source/voxels/player/1536_BOOT.kvx'
V6_SOLE_LEN, V6_ANKLE_FROM_HEEL, V6_ANKLE_ABOVE_SOLE, V6_TOE_ABOVE_SOLE, V6_TOTAL_H = 0.313, 0.088, 0.11, 0.035, 0.344


def main():
    k = read_kvx(SRC)
    solid, grid = k['solid'].copy(), k['grid']
    rgb = k['palette'][np.clip(grid, 0, 255)]
    X, Y, Z = solid.shape
    zs = np.nonzero(solid.any((0, 1)))[0]
    zbot = zs.max() + 1                                     # sole plane (KVX z grows downward)
    sole = solid[:, :, zbot - 2:zbot].any(2)                # footprint of the two lowest slices
    ys = np.nonzero(sole.any(0))[0]
    sole_len = ys.max() + 1 - ys.min()                      # toe points to KVX +y
    s = V6_SOLE_LEN / sole_len                              # metres per voxel
    keep = int(round(V6_TOTAL_H / s))
    cut = zbot - keep
    solid[:, :, :max(cut, 0)] = False
    solid = fill_solid(solid)
    # straighten the gib's sideways shin lean: shift every slice above the ankle (integer voxels along x)
    # so the leg column stays centred over the ankle
    za = int(round(zbot - V6_ANKLE_ABOVE_SOLE / s))
    def xc(z):
        xs = np.nonzero(solid[:, :, z].any(1))[0]
        return (xs.min() + xs.max() + 1) / 2.0
    ref = xc(za)
    rgb = rgb.copy()
    shifts = {}
    for z in range(max(cut, 0), za):
        if not solid[:, :, z].any():
            continue
        d = int(round(ref - xc(z)))
        if d:
            solid[:, :, z] = np.roll(solid[:, :, z], d, axis=0)
            rgb[:, :, z] = np.roll(rgb[:, :, z], d, axis=0)
            shifts[z] = d
    print('straightened slices', shifts)
    # mapping (true-handed): fwd = +y, left = +x, up = -z
    L = np.array([[0, 1.0, 0], [1.0, 0, 0], [0, 0, -1.0]])
    heel = ys.min()
    xs_shaft = np.nonzero(solid[:, :, zbot - int(round(V6_ANKLE_ABOVE_SOLE / s))].any(1))[0]
    ankle_grid = np.array([(xs_shaft.min() + xs_shaft.max() + 1) / 2.0, heel + V6_ANKLE_FROM_HEEL / s,
                           zbot - V6_ANKLE_ABOVE_SOLE / s])
    t = -(L @ ankle_grid) * s
    A = np.concatenate([L * s * 64, (t * 64)[:, None]], 1)
    m = mesh_parts([dict(solid=solid, rgb=rgb, A=A)])
    pos, tris = m['pos'], m['tris']
    vol = signed_volume(pos, tris)
    assert vol > 0
    P = pos / 64
    # toe tag: front-most point of the toe at 3.5 cm above the sole bottom, centred across the toe
    zt = P[:, 2].min() + V6_TOE_ABOVE_SOLE
    band = P[np.abs(P[:, 2] - zt) < s * 1.01]
    tip = band[:, 0].max()
    front = band[band[:, 0] > tip - s * 0.5]
    toe = np.array([tip, (front[:, 1].min() + front[:, 1].max()) / 2, zt])
    tags = [dict(tag_ankle=(0.0, 0.0, 0.0), tag_toe=tuple(toe * 64))]
    out = ROOT / 'exports/eduke32'
    write_md3(out / 'vr_boot.md3', 'vr_boot', ['rest'], [dict(name='vr_boot', shader='vr_boot.png', tris=tris, st=m['st'],
                                                              pos=[pos], nrm=[m['nrm']])], tags)
    save_png(m['tex'], out / 'vr_boot.png')
    rec = dict(name='boot', stem='vr_boot', source='voxels/player/1536_BOOT.kvx (leg gib; Voxel Duke Nukem 3D by Cheello, PRIVATE)',
               metres_per_voxel=round(float(s), 5), cut_kvx_z=int(cut), bounds_m=[P.min(0).round(4).tolist(), P.max(0).round(4).tolist()],
               tags_m=dict(tag_ankle=[0, 0, 0], tag_toe=toe.round(4).tolist()), verts=len(m['st']), tris=len(tris),
               signed_volume_units3=round(vol, 1), weld=weld_check(pos, tris), atlas=list(m['stats']['atlas']))
    (ROOT / 'metadata/assets/boot.json').write_text(json.dumps(rec, indent=1))
    print(rec)


if __name__ == '__main__':
    main()
