"""Numpy MD3 (IDP3 v15) writer for the voxel pack (same layout as v6 md3write.py, vectorised, multi-surface).

write_md3(path, name, frame_names, surfaces, tags)
  surfaces: list of dict(name, shader, tris[nt,3] (CCW-outward in MD3 coords), st[nv,2] (t=0 top),
                         pos[nf][nv,3] MD3 units, nrm[nf][nv,3])
  tags: list over frames of {tag: (x,y,z)} or {tag: ((x,y,z), axis9)}; tag order = dict order of frame 0.
The MD3 spec (Quake 3) caps a surface at 4096 vertices / 8192 triangles; EDuke32's loader has no such cap
(uint16 indices), so the hard limit here is 65535 and the caller reports anything above the spec limit.
"""
import math, struct
import numpy as np

MD3_SPEC_MAX_VERTS, MD3_SPEC_MAX_TRIS = 4096, 8192


def _str(s, n):
    b = s.encode('ascii')
    assert len(b) < n, (s, n)
    return b + bytes(n - len(b))


def normals16(n):
    n = np.asarray(n, float)
    L = np.linalg.norm(n, axis=1, keepdims=True)
    L[L == 0] = 1
    n = n / L
    lat = np.arctan2(n[:, 1], n[:, 0])
    lng = np.arccos(np.clip(n[:, 2], -1, 1))
    a = (np.round(lat * 255 / (2 * math.pi)).astype(np.int64) & 255) << 8
    b = np.round(lng * 255 / (2 * math.pi)).astype(np.int64) & 255
    return (a | b).astype(np.uint16)


def write_md3(path, name, frame_names, surfaces, tags):
    nf = len(frame_names)
    tag_names = list(tags[0].keys()) if tags else []
    fb = b''
    tb = b''
    for fi, fname in enumerate(frame_names):
        pts = np.concatenate([np.asarray(s['pos'][fi], float) for s in surfaces])
        lo, hi = pts.min(0), pts.max(0)
        c = (lo + hi) / 2
        rad = float(np.linalg.norm(pts - c, axis=1).max())
        fb += struct.pack('<10f', *lo, *hi, *c, rad) + _str(fname, 16)
        for t in tag_names:
            v = tags[fi][t]
            if len(v) == 2 and hasattr(v[0], '__len__'):
                o, ax = v
            else:
                o, ax = v, (1, 0, 0, 0, 1, 0, 0, 0, 1)
            tb += _str(t, 64) + struct.pack('<12f', *[float(x) for x in o], *[float(x) for x in ax])
    sb = b''
    for s in surfaces:
        st = np.asarray(s['st'], np.float32)
        tris = np.asarray(s['tris'], np.int32)
        nv, nt = len(st), len(tris)
        assert 0 < nv <= 65535 and nt <= 65535, (s['name'], nv, nt)
        assert tris.min() >= 0 and tris.max() < nv
        xyz = np.zeros((nf, nv, 4), np.int16)
        for fi in range(nf):
            q = np.round(np.asarray(s['pos'][fi], float) * 64)
            assert np.all(np.abs(q) <= 32767), (s['name'], fi)
            xyz[fi, :, :3] = q.astype(np.int16)
            xyz[fi, :, 3] = normals16(s['nrm'][fi]).view(np.int16)
        otri = 108; osh = otri + nt * 12; ost = osh + 68; oxyz = ost + nv * 8; send = oxyz + nf * nv * 8
        sb += (b'IDP3' + _str(s['name'], 64) + struct.pack('<10i', 0, nf, 1, nv, nt, otri, osh, ost, oxyz, send)
               + tris.astype('<i4').tobytes() + _str(s['shader'], 64) + struct.pack('<i', 0)
               + st.astype('<f4').tobytes() + xyz.astype('<i2').tobytes())
    ofr = 108; otg = ofr + 56 * nf; osf = otg + 112 * nf * len(tag_names); end = osf + len(sb)
    hdr = b'IDP3' + struct.pack('<i', 15) + _str(name, 64) + struct.pack('<9i', 0, nf, len(tag_names), len(surfaces), 0,
                                                                         ofr, otg, osf, end)
    data = hdr + fb + tb + sb
    assert len(data) == end
    with open(path, 'wb') as f:
        f.write(data)
    return end
