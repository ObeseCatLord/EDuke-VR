# SPDX-License-Identifier: GPL-2.0-only
"""A wad of bills for VR tipping, made at launch from the game's own MONEY art.

The user's GRP supplies tile 1233 (the flying bill) and the palette; nothing is shipped. The
skewed sprite is mapped flat by its four corners onto the bill face, the wad's sides get stacked
paper edges in the bill's own colours, and a one-surface MD3 (64 units per metre) is written.
"""
import struct
from pathlib import Path

MONEY_TILE = 1233
BILL = (0.156, 0.066, 0.012)   # metres: length, width, wad thickness


def _grp_files(path):
    data = Path(path).read_bytes()
    if data[:12] != b'KenSilverman':
        return {}
    count = struct.unpack('<i', data[12:16])[0]
    offset, files = 16 + count*16, {}
    for i in range(count):
        entry = data[16+i*16:32+i*16]
        name = entry[:12].split(b'\0')[0].decode('ascii', 'replace').upper()
        size = struct.unpack('<i', entry[12:16])[0]
        files[name] = data[offset:offset+size]
        offset += size
    return files


def _tile(files, tile):
    palette = files.get('PALETTE.DAT', b'')[:768]
    if len(palette) < 768:
        return None
    for name in sorted(k for k in files if k.startswith('TILES') and k.endswith('.ART')):
        art = files[name]
        _, _, start, end = struct.unpack('<4i', art[:16])
        if not start <= tile <= end:
            continue
        count = end - start + 1
        xs = struct.unpack(f'<{count}h', art[16:16+2*count])
        ys = struct.unpack(f'<{count}h', art[16+2*count:16+4*count])
        offset = 16 + 8*count + sum(xs[t]*ys[t] for t in range(tile-start))
        w, h = xs[tile-start], ys[tile-start]
        pixels = art[offset:offset+w*h]
        rgba = [(0, 0, 0, 0)]*(w*h)
        for x in range(w):
            for y in range(h):
                c = pixels[x*h+y]
                if c != 255:
                    rgba[y*w+x] = (palette[c*3]*4, palette[c*3+1]*4, palette[c*3+2]*4, 255)
        return w, h, rgba
    return None


def _texture(w, h, rgba, out):
    import numpy as np
    from PIL import Image
    image = np.array(rgba, dtype=np.uint8).reshape(h, w, 4)
    ys, xs = np.nonzero(image[:, :, 3])
    points = np.stack([xs, ys], 1).astype(float) + 0.5
    centre = points.mean(0)
    # The bill's long axis (principal direction) and its normal.
    _, vectors = np.linalg.eigh(np.cov((points - centre).T))
    along, across = vectors[:, 1], vectors[:, 0]
    if along[0] < 0:
        along = -along
    if across[1] < 0:
        across = -across
    a = (points - centre) @ along
    c = (points - centre) @ across
    # Straighten: for each slice along the bill, sample between its own near and far edges.
    W, H = 128, 54
    lo_a, hi_a = a.min(), a.max()
    face = np.zeros((H, W, 4), dtype=np.uint8)
    for u in range(W):
        t = lo_a + (u + 0.5)/W*(hi_a - lo_a)
        near = np.abs(a - t) < 1.0
        if not near.any():
            continue
        c0, c1 = c[near].min(), c[near].max()
        for v in range(H):
            q = centre + along*t + across*(c0 + (v + 0.5)/H*(c1 - c0))
            x, y = int(q[0]), int(q[1])
            if 0 <= x < w and 0 <= y < h:
                face[v, u] = image[y, x]
    seen = face[face[:, :, 3] > 0]
    mean = tuple(int(k) for k in seen[:, :3].mean(0)) + (255,)
    face[face[:, :, 3] == 0] = mean
    atlas = Image.new('RGBA', (128, 64), mean)
    atlas.paste(Image.fromarray(face, 'RGBA'), (0, 0))
    # Stacked paper edges: light sheets with darker gaps, in the bill's colours.
    light = tuple(min(255, int(k*1.25)) for k in mean[:3]) + (255,)
    dark = tuple(int(k*0.6) for k in mean[:3]) + (255,)
    for y in range(54, 64):
        for x in range(128):
            atlas.putpixel((x, y), dark if y % 2 else light)
    atlas.save(out)


def _md3(out):
    L, W, T = (v*64 for v in BILL)   # model units
    x0, x1, y0, y1, z0, z1 = -L/2, L/2, -W/2, W/2, -T/2, T/2
    face_v, edge_v = (0.0, 54/64), (54/64, 1.0)
    quads = [   # corners counter-clockwise seen from outside, with (u0, u1, v0, v1)
        (((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)), face_v),
        (((x0, y1, z0), (x1, y1, z0), (x1, y0, z0), (x0, y0, z0)), face_v),
        (((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)), edge_v),
        (((x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)), edge_v),
        (((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)), edge_v),
        (((x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)), edge_v),
    ]
    verts, uvs, tris = [], [], []
    for corners, (va, vb) in quads:
        base = len(verts)
        verts += corners
        uvs += [(0.0, vb), (1.0, vb), (1.0, va), (0.0, va)]
        tris += [(base, base+1, base+2), (base, base+2, base+3)]
    name = b'vr_money'.ljust(64, b'\0')
    shader = b'vr_money.png'.ljust(64, b'\0') + struct.pack('<i', 0)
    surf_header = 108
    ofs_tri = surf_header + 68
    ofs_st = ofs_tri + 12*len(tris)
    ofs_xyz = ofs_st + 8*len(uvs)
    ofs_end = ofs_xyz + 8*len(verts)
    surface = struct.pack('<4s64siiiiiiiiii', b'IDP3', b'money'.ljust(64, b'\0'), 0, 1, 1, len(verts), len(tris),
                          ofs_tri, surf_header, ofs_st, ofs_xyz, ofs_end)
    surface += shader
    surface += b''.join(struct.pack('<3i', *t) for t in tris)
    surface += b''.join(struct.pack('<2f', *uv) for uv in uvs)
    surface += b''.join(struct.pack('<3hH', *(int(round(c*64)) for c in v), 0) for v in verts)
    lo = [min(v[k] for v in verts) for k in range(3)]
    hi = [max(v[k] for v in verts) for k in range(3)]
    frame = struct.pack('<3f3f3ff16s', *lo, *hi, 0, 0, 0, max(L, W, T), b'rest'.ljust(16, b'\0'))
    ofs_frames = 108
    ofs_surfaces = ofs_frames + len(frame)
    header = struct.pack('<4si64siiiiiiiii', b'IDP3', 15, name, 0, 1, 0, 1, 0, ofs_frames, ofs_frames + len(frame),
                         ofs_surfaces, ofs_surfaces + len(surface))
    Path(out).write_bytes(header + frame + surface)


def build(grps, data):
    """Writes vr_money.md3/.png into data from the first GRP with the MONEY tile; True on success."""
    for grp in grps:
        try:
            tile = _tile(_grp_files(grp), MONEY_TILE)
        except OSError:
            tile = None
        if tile:
            _texture(*tile, Path(data)/'vr_money.png')
            _md3(Path(data)/'vr_money.md3')
            return True
    return False
