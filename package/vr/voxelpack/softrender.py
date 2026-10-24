"""Tiny CPU rasteriser (numpy + Pillow) for MD3 previews: orthographic, z-buffer, nearest texture lookup,
two-sided Lambert + ambient. No GPU, no Blender.

Meshes are given in MD3 coordinates (units, +X forward, +Y right, +Z up). They are drawn true-handed
(the model's right side appears on the viewer's right when looking at its back), i.e. Y is negated
before projection, exactly how the engine shows them.
"""
import math
import numpy as np
from PIL import Image, ImageDraw


_CACHE = {}


def load_md3_mesh(path, frame=0, tex_path=None):
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from md3np import read
    key = str(path)
    if key not in _CACHE:
        _CACHE[key] = read(path)
    m = _CACHE[key]
    out = []
    for s in m['surfaces']:
        pos = s['xyz'][frame]
        tp = tex_path or os.path.join(os.path.dirname(str(path)), s['shaders'][0] if s['shaders'] else '')
        tk = ('tex', tp)
        if tk not in _CACHE:
            _CACHE[tk] = np.array(Image.open(tp).convert('RGBA')) if os.path.isfile(tp) else None
        out.append(dict(pos=pos, tris=np.asarray(s['tris'], np.int64), st=np.asarray(s['st'], float), tex=_CACHE[tk]))
    return out, m


def view_matrix(yaw_deg, pitch_deg):
    """Camera looking at the origin from direction (yaw about +Z, pitch up); returns rows (right, up, fwd)
    in true-handed world coords (x fwd, y LEFT, z up)."""
    y, p = math.radians(yaw_deg), math.radians(pitch_deg)
    eye = np.array([math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p)])  # from origin to eye
    fwd = -eye
    up0 = np.array([0, 0, 1.0]) if abs(eye[2]) < 0.99 else np.array([1.0, 0, 0])
    right = np.cross(fwd, up0); right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    return np.stack([right, up, fwd])


def render(meshes, yaw=0, pitch=0, size=(512, 384), upp=None, center=None, bg=(46, 52, 64), light=(0.4, 0.3, 0.85)):
    """meshes: list of dict(pos, tris, st, tex or color). upp = model units per pixel (auto if None)."""
    W, H = size
    R = view_matrix(yaw, pitch)
    allp = []
    for m in meshes:
        p = m['pos'] * np.array([1, -1, 1])
        allp.append(p)
    P = np.concatenate(allp)
    if center is None:
        center = (P.min(0) + P.max(0)) / 2 * np.array([1, 1, 1])
    else:
        center = np.asarray(center, float) * np.array([1, -1, 1])
    cam = [(p - center) @ R.T for p in allp]
    if upp is None:
        C = np.concatenate(cam)
        ext = max((C[:, 0].max() - C[:, 0].min()) / (W * 0.9), (C[:, 1].max() - C[:, 1].min()) / (H * 0.9), 1e-6)
        upp = ext
    img = np.zeros((H, W, 3), float)
    img[:] = bg
    zb = np.full((H, W), np.inf)
    L = np.array(light, float); L /= np.linalg.norm(L)
    Lc = L  # light in camera coords (right, up, toward-viewer = -fwd)
    for m, c in zip(meshes, cam):
        sx = c[:, 0] / upp + W / 2
        sy = -c[:, 1] / upp + H / 2
        sz = c[:, 2]
        tex = m.get('tex')
        st = m.get('st')
        col = np.array(m.get('color', (200, 200, 200)), float)
        for t in m['tris']:
            a, b, d = t
            x0, y0, x1, y1, x2, y2 = sx[a], sy[a], sx[b], sy[b], sx[d], sy[d]
            den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(den) < 1e-9:
                continue
            xmin, xmax = int(max(0, math.floor(min(x0, x1, x2)))), int(min(W - 1, math.ceil(max(x0, x1, x2))))
            ymin, ymax = int(max(0, math.floor(min(y0, y1, y2)))), int(min(H - 1, math.ceil(max(y0, y1, y2))))
            if xmin > xmax or ymin > ymax:
                continue
            gx, gy = np.meshgrid(np.arange(xmin, xmax + 1) + 0.5, np.arange(ymin, ymax + 1) + 0.5)
            w0 = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / den
            w1 = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / den
            w2 = 1 - w0 - w1
            inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not inside.any():
                continue
            z = w0 * sz[a] + w1 * sz[b] + w2 * sz[d]
            sub = zb[ymin:ymax + 1, xmin:xmax + 1]
            vis = inside & (z < sub)
            if not vis.any():
                continue
            n = np.cross(c[b] - c[a], c[d] - c[a])
            nl = np.linalg.norm(n)
            if nl < 1e-12:
                continue
            n /= nl
            shade = 0.35 + 0.65 * abs(float(n[0] * Lc[0] + n[1] * Lc[1] - n[2] * Lc[2]))
            if tex is not None and st is not None:
                u = w0 * st[a][0] + w1 * st[b][0] + w2 * st[d][0]
                v = w0 * st[a][1] + w1 * st[b][1] + w2 * st[d][1]
                th, tw = tex.shape[:2]
                iu = np.clip((u * tw).astype(int), 0, tw - 1)
                iv = np.clip((v * th).astype(int), 0, th - 1)
                cc = tex[iv, iu, :3].astype(float)
            else:
                cc = np.broadcast_to(col, gx.shape + (3,))
            sub[vis] = z[vis]
            img[ymin:ymax + 1, xmin:xmax + 1][vis] = cc[vis] * shade
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)), upp


def label(im, text, color=(255, 255, 255)):
    d = ImageDraw.Draw(im)
    d.text((5, 4), text, fill=(0, 0, 0))
    d.text((4, 3), text, fill=color)
    return im


def grid(images, cols):
    w = max(i.width for i in images); h = max(i.height for i in images)
    rows = (len(images) + cols - 1) // cols
    S = Image.new('RGB', (cols * w, rows * h), (20, 20, 20))
    for k, im in enumerate(images):
        S.paste(im, ((k % cols) * w, (k // cols) * h))
    return S
