"""Fast numpy MD3 reader (same result layout as md3read.read_md3 but surfaces carry numpy arrays:
xyz[nf, nv, 3] in MD3 units (short/64), nrm16[nf, nv], tris[nt, 3], st[nv, 2])."""
import struct
from pathlib import Path
import numpy as np


def cstr(b):
    return b.split(b'\0')[0].decode('ascii', 'replace')


def read(path):
    d = Path(path).read_bytes()
    assert d[:4] == b'IDP3'
    ver = struct.unpack_from('<i', d, 4)[0]
    flags, nf, nt, ns, nskins, ofr, otg, osf, oend = struct.unpack_from('<9i', d, 72)
    frames = []
    for i in range(nf):
        v = struct.unpack_from('<10f', d, ofr + i * 56)
        frames.append(dict(mins=v[0:3], maxs=v[3:6], origin=v[6:9], radius=v[9], name=cstr(d[ofr + i * 56 + 40:ofr + i * 56 + 56])))
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
        sname = cstr(d[o + 4:o + 68])
        sflags, snf, nsh, nv, ntri, otri, osh, ost, oxyz, send = struct.unpack_from('<10i', d, o + 68)
        tris = np.frombuffer(d, '<i4', ntri * 3, o + otri).reshape(ntri, 3)
        shaders = [cstr(d[o + osh + 68 * k:o + osh + 68 * k + 64]) for k in range(nsh)]
        st = np.frombuffer(d, '<f4', nv * 2, o + ost).reshape(nv, 2)
        raw = np.frombuffer(d, '<i2', snf * nv * 4, o + oxyz).reshape(snf, nv, 4)
        surfaces.append(dict(name=sname, tris=tris, st=st, shaders=shaders, xyz=raw[..., :3].astype(float) / 64.0,
                             nrm16=raw[..., 3].view('<u2'), num_verts=nv, num_tris=ntri, num_frames=snf))
        o += send
    return dict(version=ver, flags=flags, num_frames=nf, num_tags=nt, num_surfaces=ns, frames=frames, tags=tags,
                surfaces=surfaces, size=len(d), ofs_end=oend)
