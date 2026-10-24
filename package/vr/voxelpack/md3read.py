"""Minimal MD3 (IDP3 v15) reader, no Blender dependency. Vertex xyz are returned in MD3 units (short/64)."""
import struct
from pathlib import Path


def cstr(b):
    return b.split(b'\0')[0].decode('ascii', 'replace')


def read_md3(path):
    d = Path(path).read_bytes()
    ident, ver = d[:4], struct.unpack_from('<i', d, 4)[0]
    name = cstr(d[8:72])
    flags, nf, nt, ns, nskins, ofr, otg, osf, oend = struct.unpack_from('<9i', d, 72)
    frames = []
    for i in range(nf):
        v = struct.unpack_from('<10f', d, ofr + i * 56)
        frames.append(dict(mins=v[0:3], maxs=v[3:6], origin=v[6:9], radius=v[9],
                           name=cstr(d[ofr + i * 56 + 40:ofr + i * 56 + 56])))
    tags = []
    for f in range(nf):
        ft = {}
        for t in range(nt):
            o = otg + (f * nt + t) * 112
            vals = struct.unpack_from('<12f', d, o + 64)
            ft[cstr(d[o:o + 64])] = dict(origin=vals[0:3], axis=vals[3:12])
        tags.append(ft)
    surfaces, o = [], osf
    for s in range(ns):
        sid = d[o:o + 4]
        sname = cstr(d[o + 4:o + 68])
        sflags, snf, nsh, nv, ntri, otri, osh, ost, oxyz, send = struct.unpack_from('<10i', d, o + 68)
        tris = [struct.unpack_from('<3i', d, o + otri + 12 * k) for k in range(ntri)]
        shaders = [cstr(d[o + osh + 68 * k:o + osh + 68 * k + 64]) for k in range(nsh)]
        st = [struct.unpack_from('<2f', d, o + ost + 8 * k) for k in range(nv)]
        fr = []
        for f in range(snf):
            vs = []
            for k in range(nv):
                x, y, z, n = struct.unpack_from('<3hH', d, o + oxyz + (f * nv + k) * 8)
                vs.append((x / 64.0, y / 64.0, z / 64.0, n))
            fr.append(vs)
        surfaces.append(dict(ident=sid, name=sname, frames=fr, tris=tris, st=st, shaders=shaders,
                             num_verts=nv, num_tris=ntri))
        o += send
    return dict(ident=ident, version=ver, name=name, flags=flags, num_frames=nf, num_tags=nt,
                num_surfaces=ns, frames=frames, tags=tags, surfaces=surfaces, size=len(d), ofs_end=oend)


def signed_volume(surf, frame=0):
    """Signed volume (MD3 units^3, positive = CCW-outward like the calibrated stock pistol)."""
    v = surf['frames'][frame]
    tot = 0.0
    for a, b, c in surf['tris']:
        A, B, Cc = (p[:3] for p in (v[a], v[b], v[c]))
        tot += (A[0] * (B[1] * Cc[2] - B[2] * Cc[1]) - A[1] * (B[0] * Cc[2] - B[2] * Cc[0])
                + A[2] * (B[0] * Cc[1] - B[1] * Cc[0])) / 6.0
    return tot
