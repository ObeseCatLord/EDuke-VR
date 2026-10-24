#!/usr/bin/env python3
"""Preview sheets of the skinned voxel Duke (CPU, softrender; private output).

python3 -I preview_duke_body.py [out=DIR] [which=walk,bind,joints,fp,frames]

  duke_walk.png          vr_duke walk_02 from 8 angles (re-read from the MD3)
  duke_bind.png          the IK body (vr_duke_ik.md3 `bind` frame) front and side, and the build pose
  duke_joints.png        close-ups of joint bends posed through the .skin file exactly as the engine does it:
                         elbow 100 deg, knee 100 deg, shoulder raised, hip flexed, neck bent, fist
  duke_fp.png            first-person views from the eye looking down at the body (head hidden via .fphide),
                         in v7's stand pose and with the arms reaching forward
  duke_frames.png        all 28 vr_duke frames
"""
import math, os, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('EDUKE32_VOXEL_PACK', HERE.parent))
ASSETS = Path(os.environ.get('EDUKE32_VR_ASSETS', ROOT.parent))
sys.path.insert(0, str(HERE))
from softrender import render, label, grid  # noqa: E402
from md3np import read  # noqa: E402
from duke_skel import Skeleton, fk_pose, rot_axis, U  # noqa: E402

EXP = ROOT / 'exports' / 'eduke32'
V7 = ASSETS / 'v7-original' / 'exports' / 'eduke32'
BG = (70, 74, 84)


def load_skin(path):
    rows = Path(path).read_text().split('\n')
    n = int(rows[0].split()[2])
    idx = np.zeros((n, 4), int)
    w = np.zeros((n, 4))
    L = np.zeros((n, 4, 3))
    for i, r in enumerate(rows[1:1 + n]):
        f = r.split()
        for j in range(int(f[0])):
            b, ww, x, y, z = f[1 + 5 * j:6 + 5 * j]
            idx[i, j], w[i, j], L[i, j] = int(b), float(ww), (float(x), float(y), float(z))
    return idx, w, L / U


def skin_pose(sk_data, M, hide=None, hide_at=None):
    """Engine-style skinning: sum_j w_j (pos_b + R_b local_j); hidden vertices collapse to hide_at."""
    idx, w, L = sk_data
    out = np.zeros((len(idx), 3))
    for j in range(4):
        out += w[:, j:j + 1] * (M[idx[:, j], :3, 3] + np.einsum('nij,nj->ni', M[idx[:, j], :3, :3], L[:, j]))
    if hide is not None:
        out[hide] = hide_at
    return out


def mesh(pos_m_true, md3, tex):
    """softrender expects MD3 (+Y right) units; our points are true-handed metres."""
    s = md3['surfaces'][0]
    return dict(pos=pos_m_true * U * np.array([1, -1, 1]), tris=np.asarray(s['tris'])[:, [0, 2, 1]], st=s['st'], tex=tex)


def persp_render(meshes, eye, target, up=(0, 0, 1), fov=90, size=(640, 480), bg=BG):
    """Perspective variant of softrender.render (true-handed world, metres)."""
    W, H = size
    f = np.asarray(target, float) - eye
    f /= np.linalg.norm(f)
    r = np.cross(f, up)
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    foc = (W / 2) / math.tan(math.radians(fov) / 2)
    img = np.zeros((H, W, 3), float)
    img[:] = bg
    zb = np.full((H, W), np.inf)
    L = np.array([0.4, 0.3, 0.85])
    L /= np.linalg.norm(L)
    for m in meshes:
        P = m['pos'] - eye
        cx, cy, cz = P @ r, P @ u, P @ f
        tex, st = m['tex'], m['st']
        for t in m['tris']:
            a, b, d = t
            if min(cz[a], cz[b], cz[d]) < 0.02:
                continue
            sx = [W / 2 + foc * cx[k] / cz[k] for k in (a, b, d)]
            sy = [H / 2 - foc * cy[k] / cz[k] for k in (a, b, d)]
            x0, x1, x2 = sx
            y0, y1, y2 = sy
            den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(den) < 1e-9:
                continue
            xmin, xmax = int(max(0, math.floor(min(sx)))), int(min(W - 1, math.ceil(max(sx))))
            ymin, ymax = int(max(0, math.floor(min(sy)))), int(min(H - 1, math.ceil(max(sy))))
            if xmin > xmax or ymin > ymax:
                continue
            gx, gy = np.meshgrid(np.arange(xmin, xmax + 1) + 0.5, np.arange(ymin, ymax + 1) + 0.5)
            w0 = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / den
            w1 = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / den
            w2 = 1 - w0 - w1
            inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not inside.any():
                continue
            iz = w0 / cz[a] + w1 / cz[b] + w2 / cz[d]
            z = 1 / iz
            sub = zb[ymin:ymax + 1, xmin:xmax + 1]
            vis = inside & (z < sub)
            if not vis.any():
                continue
            n = np.cross(m['pos'][b] - m['pos'][a], m['pos'][d] - m['pos'][a])
            nl = np.linalg.norm(n)
            if nl < 1e-12:
                continue
            shade = 0.35 + 0.65 * abs(float(n @ L) / nl)
            pa, pb, pd = w0 / cz[a] * z, w1 / cz[b] * z, w2 / cz[d] * z
            uu = pa * st[a][0] + pb * st[b][0] + pd * st[d][0]
            vv = pa * st[a][1] + pb * st[b][1] + pd * st[d][1]
            th, tw = tex.shape[:2]
            cc = tex[np.clip((vv * th).astype(int), 0, th - 1), np.clip((uu * tw).astype(int), 0, tw - 1), :3].astype(float)
            sub[vis] = z[vis]
            img[ymin:ymax + 1, xmin:xmax + 1][vis] = cc[vis] * shade
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def main():
    args = dict(a.split('=', 1) for a in sys.argv[1:])
    out = Path(args.get('out', ROOT / 'previews'))
    out.mkdir(parents=True, exist_ok=True)
    which = set(args.get('which', 'walk,bind,joints,fp,frames').split(','))
    duke = read(EXP / 'vr_duke.md3')
    tex = np.array(Image.open(EXP / 'vr_duke.png').convert('RGBA'))
    ik = read(EXP / 'vr_duke_ik.md3')
    names = [f['name'] for f in duke['frames']]
    sk = Skeleton(V7)
    skin = load_skin(EXP / 'vr_duke_ik.skin')
    fphide = np.array([int(x) for x in (EXP / 'vr_duke_ik.fphide').read_text().split()], int)
    s = duke['surfaces'][0]

    def md3_mesh(fi):
        return [dict(pos=s['xyz'][fi], tris=np.asarray(s['tris']), st=s['st'], tex=tex)]

    if 'walk' in which:
        fi = names.index('walk_02')
        ims = []
        for k, (yaw, nm) in enumerate(((0, 'front'), (45, 'front left'), (90, 'left'), (135, 'back left'), (180, 'back'),
                                       (225, 'back right'), (270, 'right'), (315, 'front right'))):
            im, _ = render(md3_mesh(fi), yaw=yaw, pitch=8, size=(420, 560), upp=0.36, center=(0, 0, 58), bg=BG)
            ims.append(label(im, f'walk_02 {nm}'))
        grid(ims, 4).save(out / 'duke_walk.png')
    if 'frames' in which:
        ims = []
        for fi, fn in enumerate(names):
            im, _ = render(md3_mesh(fi), yaw=30, pitch=10, size=(260, 320), upp=0.5, center=(0, 0, 55), bg=BG)
            ims.append(label(im, fn))
        grid(ims, 7).save(out / 'duke_frames.png')
    if 'bind' in which:
        si = ik['surfaces'][0]
        ims = []
        for fi, fn in ((0, 'bind'), (1, 'rest')):
            for yaw, nm in ((0, 'front'), (90, 'side'), (200, 'back')):
                m = [dict(pos=si['xyz'][fi] * np.array([1, -1, 1]), tris=np.asarray(si['tris'])[:, [0, 2, 1]],
                          st=si['st'], tex=tex)]
                im, _ = render(m, yaw=yaw, pitch=5, size=(520, 560), upp=0.30, center=(0, 0, 58), bg=BG)
                ims.append(label(im, f'vr_duke_ik {fn} {nm}'))
        grid(ims, 3).save(out / 'duke_bind.png')
    if 'joints' in which:
        D = math.radians
        X = np.array([1.0, 0, 0])
        poses = [
            ('elbow 100', {'forearm_l': rot_axis(X, -D(100))}, 'forearm_l', (0, 0), 0.14),
            ('elbow 100 (side)', {'forearm_l': rot_axis(X, -D(100))}, 'forearm_l', (90, 0), 0.14),
            ('knee 100', {'calf_l': rot_axis(X, D(100)), 'thigh_l': rot_axis(X, -D(40))}, 'calf_l', (90, 0), 0.16),
            ('shoulder raised', {'upperarm_l': rot_axis(np.array([0, 1.0, 0]), D(100))}, 'upperarm_l', (0, 0), 0.16),
            ('shoulder forward', {'upperarm_l': rot_axis(X, -D(80))}, 'upperarm_l', (60, 10), 0.16),
            ('hip flexed 80', {'thigh_l': rot_axis(X, -D(80)), 'calf_l': rot_axis(X, D(80))}, 'thigh_l', (90, 0), 0.17),
            ('hip out 40', {'thigh_l': rot_axis(np.array([0, 1.0, 0]), D(40))}, 'thigh_l', (0, 0), 0.17),
            ('neck bent', {'neck': rot_axis(X, -D(25)), 'head': rot_axis(X, -D(25))}, 'neck', (90, 0), 0.10),
            ('neck turned', {'neck': rot_axis(np.array([0, 0, 1.0]), D(35)), 'head': rot_axis(np.array([0, 0, 1.0]), D(30))}, 'head', (20, 10), 0.10),
            ('fist', {f'{f}_{p}_l': rot_axis(X, -D(80 if p == 'proximal' else 90)) for f in ('index', 'middle', 'ring', 'little')
                      for p in ('proximal', 'intermediate', 'distal')} | {'thumb_proximal_l': rot_axis(X, -D(40)),
                                                                          'thumb_distal_l': rot_axis(X, -D(50))}, 'hand_l', (60, 20), 0.06),
            ('fist (back)', {f'{f}_{p}_l': rot_axis(X, -D(80 if p == 'proximal' else 90)) for f in ('index', 'middle', 'ring', 'little')
                             for p in ('proximal', 'intermediate', 'distal')}, 'hand_l', (200, 30), 0.06),
            ('open hand', {}, 'hand_l', (60, 20), 0.06),
        ]
        ims = []
        si = ik['surfaces'][0]
        for nm, deltas, centre, (yaw, pitch), upp in poses:
            M = fk_pose(sk, deltas)
            P = skin_pose(skin, M)
            c = M[sk.bi[centre]][:3, 3] * U * np.array([1, -1, 1])
            if centre in ('forearm_l', 'calf_l'):
                c = c
            m = [mesh(P, ik, tex)]
            im, _ = render(m, yaw=yaw, pitch=pitch, size=(360, 360), upp=upp, center=c, bg=BG)
            ImageDraw.Draw(im).ellipse([177, 177, 183, 183], outline=(255, 0, 0))
            ims.append(label(im, nm))
        grid(ims, 4).save(out / 'duke_joints.png')
    if 'fp' in which:
        ims = []
        neck = sk.bi['neck']
        head = sk.bi['head']
        reach = {'upperarm_l': rot_axis(np.array([1.0, 0, 0]), -math.radians(55)),
                 'upperarm_r': rot_axis(np.array([1.0, 0, 0]), -math.radians(55)),
                 'forearm_l': rot_axis(np.array([1.0, 0, 0]), -math.radians(50)),
                 'forearm_r': rot_axis(np.array([1.0, 0, 0]), -math.radians(50))}
        # the engine's eye: from the hidden head's bind shape, 2 cm behind the face and 11.5 cm under the crown;
        # the body sits 4 cm further back (vr.cpp solveIkBody)
        Pb = skin_pose(skin, sk.bind)[fphide]
        hb = sk.bind[head][:3, 3]
        eye_fwd = min(max(Pb[:, 0].max() - 0.02 - hb[0], 0.0), 0.2)
        eye_up = min(max(Pb[:, 2].max() - 0.115 - hb[2], -0.05), 0.25)
        for pname, M in (('stand', sk.poses['stand']), ('arms forward', fk_pose(sk, reach)), ('walk_02', sk.poses['walk_02'])):
            P = skin_pose(skin, M, fphide, M[neck][:3, 3])
            hp = M[head][:3, 3]
            Rh = M[head][:3, :3]
            eye = hp + Rh @ np.array([0.0, eye_fwd, eye_up]) + np.array([0.04, 0, 0])   # head frame: y forward, z up
            fwd = Rh @ np.array([0, 1.0, 0])
            for pitch in (60, 85):
                tgt = eye + fwd * math.cos(math.radians(pitch)) - np.array([0, 0, math.sin(math.radians(pitch))])
                si = ik['surfaces'][0]
                m = [dict(pos=P, tris=np.asarray(si['tris']), st=si['st'], tex=tex)]
                im = persp_render(m, eye, tgt, fov=95, size=(560, 440))
                ims.append(label(im, f'first person, {pname}, looking {pitch} deg down (eye fwd {eye_fwd:.3f} up {eye_up:.3f})'))
        grid(ims, 2).save(out / 'duke_fp.png')
    print('previews in', out)


if __name__ == '__main__':
    main()
