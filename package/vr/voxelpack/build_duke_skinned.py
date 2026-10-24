#!/usr/bin/env python3
"""Skinned voxel Duke: one connected voxel body on v7's 49-bone skeleton, used in third and first person.

python3 -I build_duke_skinned.py [fh=2]

Builds (pack folder EDUKE32_VOXEL_PACK, v7 set from EDUKE32_VR_ASSETS/v7-original):
  exports/eduke32/vr_duke_ik.{md3,png,skel,skin,anim,headverts,fphide,handverts_l,handverts_r}
      the full IK body: v7's skeleton (.skel and .anim copied), one surface, frames `bind` and `rest`, a
      "skin 2" of up to 4 bones per vertex with the positions in each bone's frame; the hands are part of the
      body and skinned to the 15 finger bones per side (the pack sets "ik_hands", so the engine poses them
      and draws no separate hand shells), so .handverts_l/_r are empty; .headverts = the head, .fphide = head
      and neck (first person collapses them onto the neck bone, which closes the collar with a cone).
  exports/eduke32/vr_duke.md3/.png        third person: the same mesh posed with v7's 28 frames (v6 MD3
                                          convention, +Y right), tags copied from v7's vr_duke.md3
  exports/eduke32/vr_duke_body.md3/.png   the same mesh and frames with the .fphide head hidden (collapsed
                                          onto the neck bone), as the full body hides it in first person
  metadata/assets/duke.json

The voxel body is assembled by duke_body.py (build pose: T-pose arms, straight legs; see duke_skel.py).
Meshing: voxmesh, ONE closed shell; greedy rectangles never span two bones, and every cell within a joint's
blend zone is its own rectangle, so the mesh has a vertex at every voxel corner where the weights change.
Skinning (blocky but clean): every voxel belongs to exactly one bone; a vertex takes the bones of the solid
cells in a box of half-size R around it (count-weighted, at most 4 bones), so a joint blends linearly over R
voxels on each side and is rigid beyond: R = 2 body voxels at the bend-heavy joints (shoulder, elbow, hip,
knee, neck), 1 elsewhere on the body (spine, ankle), 2 fine cells at the wrist and 1 at the finger joints. The
arms past the shoulder and the hands are fine cells (half the body voxel), so the elbow's blend is 4 fine cells
each side.
"""
import json, os, sys, time
from pathlib import Path
import numpy as np
from scipy import ndimage

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('EDUKE32_VOXEL_PACK', HERE.parent))
ASSETS = Path(os.environ.get('EDUKE32_VR_ASSETS', ROOT.parent))
sys.path.insert(0, str(HERE))
from duke_skel import Skeleton, U  # noqa: E402
import duke_body as DB  # noqa: E402
from voxmesh import mesh_parts, signed_volume, weld_check, save_png  # noqa: E402
from md3io import write_md3  # noqa: E402
from md3np import read as read_md3  # noqa: E402

V7 = ASSETS / 'v7-original' / 'exports' / 'eduke32'
OUT = ROOT / 'exports' / 'eduke32'
MAX_VERTS = 32768     # the engine's IK skin limit
BEND = {frozenset(p) for p in (('clavicle', 'upperarm'), ('chest', 'upperarm'), ('upperarm', 'forearm'),
                               ('pelvis', 'thigh'), ('thigh', 'calf'), ('spine', 'upperarm'),
                               # neck: a softer bend, and a one-voxel strip on the head side of the first-person
                               # cut, so the collapsed head closes the collar with a fan of thin strips
                               ('chest', 'neck'), ('neck', 'head'), ('clavicle', 'neck'), ('chest', 'head'),
                               ('clavicle', 'head'))}
FINGER_R, WRIST_R = 1, 2
# the shoulder blends wider (3 body voxels each side), so a raised or reaching arm does not kink at the deltoid
SHOULDER = {frozenset(p) for p in (('clavicle', 'upperarm'), ('chest', 'upperarm'), ('spine', 'upperarm'))}


def log(*a):
    print('[duke]', *a, flush=True)


def stem(name):
    return name[:-2] if name.endswith(('_l', '_r')) else name


def pair_r(sk, a, b, fh):
    """Blend half-width (fine cells) of the joint between bones a and b."""
    na, nb = stem(sk.names[a]), stem(sk.names[b])
    hand = {'hand'} | {n for n in (na, nb) if n.startswith(('thumb', 'index', 'middle', 'ring', 'little'))}
    if na in hand and nb in hand:
        return FINGER_R
    if 'hand' in (na, nb):
        return WRIST_R
    pair = frozenset((na, nb))
    return (3 if pair in SHOULDER else 2 if pair in BEND else 1) * fh


def layers(sk, cb, cs, scale, fh):
    """Distance layer (0-based, chessboard cells) of every cell inside some joint's blend zone, else -1: cells
    nearer than R-1 cells to another bone, where R = the joint's blend half-width in these cells (scale fine
    cells each)."""
    present = [int(b) for b in np.unique(cb[cs])]
    dist = {b: ndimage.distance_transform_cdt(~(cs & (cb == b)), metric='chessboard') for b in present}
    lay = np.full(cb.shape, -1, np.int64)
    for own in present:
        m = cs & (cb == own)
        for b in present:
            if b == own:
                continue
            R = pair_r(sk, own, b, fh) // scale
            d = dist[b]
            sel = m & (d <= R - 1)
            lay = np.where(sel & ((lay < 0) | (d < lay)), d, lay)
    return lay


def zone_labels(sk, a, fh):
    """Mesh label per cell: the bone, split into distance layers inside the joints' blend zones, so the mesh has a
    vertex row on every layer border (rectangles still run along the joint) and nowhere else."""
    solid, bone, fine = a['solid'], a['bone'], a['fine']
    lab = np.where(solid, bone.astype(np.int64), -1)
    X, Y, Z = (n // fh for n in solid.shape)
    cb = bone.reshape(X, fh, Y, fh, Z, fh)[:, 0, :, 0, :, 0]
    cf = fine.reshape(X, fh, Y, fh, Z, fh).any((1, 3, 5))
    cs = (cb >= 0) & ~cf
    cl = layers(sk, cb, cs, fh, fh)
    up = np.repeat(np.repeat(np.repeat(cl, fh, 0), fh, 1), fh, 2)
    sel = (up >= 0) & ~fine & solid
    lab[sel] = 1000 + bone[sel] * 16 + up[sel]
    idx = np.argwhere(fine)
    lo, hi = np.maximum(idx.min(0) - 6, 0), np.minimum(idx.max(0) + 7, solid.shape)
    sub = tuple(slice(l, h) for l, h in zip(lo, hi))
    fl = layers(sk, bone[sub], solid[sub], 1, fh)
    sel = (fl >= 0) & fine[sub]
    ls = lab[sub]
    ls[sel] = 2000 + bone[sub][sel] * 16 + fl[sel]
    lab[sub] = ls
    return lab, int((up >= 0).sum() + sel.sum())


def corner_weights(sk, a, corners, fh):
    """Bones and weights of every mesh corner (fine-grid corner index) from the solid cells around it."""
    solid, bone = a['solid'], a['bone']
    B = np.where(solid, bone, -1)
    nb = len(sk.names)
    S = np.array(B.shape)
    idx = np.zeros((len(corners), 4), np.int64)
    w = np.zeros((len(corners), 4))
    Rmax = 3 * fh
    for i, c in enumerate(corners):
        lo, hi = np.maximum(c - Rmax, 0), np.minimum(c + Rmax, S)
        box = B[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]]
        o = c - lo                                        # corner position inside the box
        near = box[max(o[0] - 1, 0):o[0] + 1, max(o[1] - 1, 0):o[1] + 1, max(o[2] - 1, 0):o[2] + 1]
        own = near[near >= 0]
        cnt = np.bincount(box[box >= 0], minlength=nb)
        top = np.argsort(-cnt)[:2]
        if cnt[top[1]] == 0 or len(own) == 0:
            b0 = int(np.bincount(own).argmax()) if len(own) else int(top[0])
            idx[i, 0], w[i, 0] = b0, 1.0
            continue
        # the joint this corner sits on: its own cell's bone and the most common other bone nearby
        b0 = int(np.bincount(own).argmax())
        others = [int(b) for b in np.argsort(-cnt) if cnt[b] > 0 and b != b0]
        R = pair_r(sk, b0, others[0], fh) if others else fh
        sub = box[max(o[0] - R, 0):o[0] + R, max(o[1] - R, 0):o[1] + R, max(o[2] - R, 0):o[2] + R]
        cnt = np.bincount(sub[sub >= 0], minlength=nb).astype(float)
        cnt[cnt < 0.04 * cnt.sum()] = 0
        top = np.argsort(-cnt)[:4]
        ww = cnt[top]
        idx[i], w[i] = top, ww / ww.sum()
    return idx, w


def mesh_body(sk, a, pal, G):
    fh = G.fh
    lab, nz = zone_labels(sk, a, fh)
    rgb = pal[np.clip(a['pal'], 0, 255)]
    A = np.zeros((3, 4))
    A[0, 0] = A[1, 1] = A[2, 2] = G.h
    A[:, 3] = G.origin
    t = time.time()
    m = mesh_parts([dict(solid=a['solid'], rgb=rgb, A=A, label=lab)], min_atlas_w=512)
    log(f'mesh: {len(m["pos"])} verts, {len(m["tris"])} tris, atlas {m["stats"]["atlas"]}, zone cells {nz} '
        f'({time.time() - t:.1f} s)')
    m['corners'] = np.round((m['pos'] - G.origin) / G.h).astype(np.int64)
    return m


def hidden_sets(sk, a, corners):
    """Corners whose adjacent solid cells are all head (headverts) / all head or neck (fphide)."""
    B = np.where(a['solid'], a['bone'], -1)
    head, neck = sk.bi['head'], sk.bi['neck']
    hv, fp = np.zeros(len(corners), bool), np.zeros(len(corners), bool)
    for i, c in enumerate(corners):
        n = B[c[0] - 1:c[0] + 1, c[1] - 1:c[1] + 1, c[2] - 1:c[2] + 1]
        n = n[n >= 0]
        hv[i] = len(n) > 0 and (n == head).all()
        fp[i] = len(n) > 0 and np.isin(n, (head, neck)).all()
    return hv, fp


def pose_points(P, N, idx, w, rest, pose):
    """LBS of points and normals."""
    D = np.einsum('bij,bjk->bik', pose, np.linalg.inv(rest))
    Ph = np.c_[P, np.ones(len(P))]
    out = np.zeros((len(P), 3))
    nrm = np.zeros((len(P), 3))
    for k in range(idx.shape[1]):
        Dk = D[idx[:, k]]
        out += w[:, k:k + 1] * np.einsum('nij,nj->ni', Dk, Ph)[:, :3]
        nrm += w[:, k:k + 1] * np.einsum('nij,nj->ni', Dk[:, :3, :3], N)
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    return out, nrm


def main():
    args = dict(x.split('=', 1) for x in sys.argv[1:])
    fh = int(args.get('fh', 2))
    OUT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'metadata/assets').mkdir(parents=True, exist_ok=True)
    if not (V7 / 'vr_duke_ik.skel').is_file():
        raise SystemExit(f'build_duke_skinned: {V7} (the original v7 set) is needed for the skeleton and frames')
    sk = Skeleton(V7)
    r = DB.build_body(sk, ROOT, V7, fh=fh, log=log)
    a = DB.assemble(r, log=log)
    G = r['G']
    m = mesh_body(sk, a, r['pal'], G)
    nv = len(m['pos'])
    if nv > MAX_VERTS:
        raise SystemExit(f'build_duke_skinned: {nv} vertices > {MAX_VERTS}')
    P, T, ST, N = m['pos'], m['tris'], m['st'], m['nrm']
    vol = signed_volume(P, T)
    weld = weld_check(P * U, T)
    log('volume m3', round(vol, 4), 'weld', weld)
    assert vol > 0 and weld['odd_edges'] == 0 and weld['unbalanced_directed'] == 0 and weld['components'] == 1, weld
    t = time.time()
    idx, w = corner_weights(sk, a, m['corners'], fh)
    log(f'weights ({time.time() - t:.1f} s): max influences {int((w > 0).sum(1).max())}, '
        f'blended verts {int((w[:, 1] > 0).sum())}')
    hv, fp = hidden_sets(sk, a, m['corners'])
    rest = sk.build
    # ---------------- vr_duke_ik
    stem_ik = 'vr_duke_ik'
    frames = []
    for fn, M in (('bind', sk.bind), ('rest', sk.poses['rest'])):
        Pd, Nd = pose_points(P, N, idx, w, rest, M)
        frames.append((fn, Pd * U, Nd))
    write_md3(OUT / f'{stem_ik}.md3', stem_ik, [f[0] for f in frames],
              [dict(name='duke', shader=f'{stem_ik}.png', tris=T, st=ST, pos=[f[1] for f in frames],
                    nrm=[f[2] for f in frames])], [])
    save_png(m['tex'], OUT / f'{stem_ik}.png')
    (OUT / f'{stem_ik}.skel').write_text(sk.skel_text)
    (OUT / f'{stem_ik}.anim').write_text((V7 / 'vr_duke_ik.anim').read_text())
    Binv = np.linalg.inv(rest)
    lines = [f'skin 2 {nv}']
    for i in range(nv):
        parts = []
        for k in range(4):
            if w[i, k] <= 0:
                continue
            b = int(idx[i, k])
            loc = (Binv[b][:3, :3] @ P[i] + Binv[b][:3, 3]) * U
            parts.append(f'{b} {w[i, k]:.6f} {loc[0]:.5f} {loc[1]:.5f} {loc[2]:.5f}')
        lines.append(f'{len(parts)} ' + ' '.join(parts))
    (OUT / f'{stem_ik}.skin').write_text('\n'.join(lines) + '\n')
    (OUT / f'{stem_ik}.headverts').write_text(''.join(f'{i}\n' for i in np.nonzero(hv)[0]))
    (OUT / f'{stem_ik}.fphide').write_text(''.join(f'{i}\n' for i in np.nonzero(fp)[0]))
    # the hands are part of the body (ik_hands): nothing is hidden for separate hand shells
    (OUT / f'{stem_ik}.handverts_l').write_text('')
    (OUT / f'{stem_ik}.handverts_r').write_text('')
    # ---------------- vr_duke / vr_duke_body: v7's 28 frames, v6 MD3 convention (+Y right)
    v7m = read_md3(V7 / 'vr_duke.md3')
    names = [f['name'] for f in v7m['frames']]
    tags = [{t: (tuple(v['origin']), tuple(v['axis'])) for t, v in ft.items()} for ft in v7m['tags']]
    Sy = np.array([1.0, -1.0, 1.0])
    TM = T[:, [0, 2, 1]]
    neck = sk.bi['neck']
    rec_frames = {}
    for stem_out, surf, hide in (('vr_duke', 'duke', None), ('vr_duke_body', 'body', fp)):
        fpos, fnrm = [], []
        for fn in names:
            Pd, Nd = pose_points(P, N, idx, w, rest, sk.poses[fn])
            if hide is not None:
                Pd[hide] = sk.poses[fn][neck][:3, 3]
            fpos.append(Pd * U * Sy)
            fnrm.append(Nd * Sy)
            if hide is None:
                rec_frames[fn] = dict(min_z=round(float(Pd[:, 2].min()), 4))
        size = write_md3(OUT / f'{stem_out}.md3', stem_out, names,
                         [dict(name=surf, shader=f'{stem_out}.png', tris=TM, st=ST, pos=fpos, nrm=fnrm)], tags)
        save_png(m['tex'], OUT / f'{stem_out}.png')
        log(stem_out, 'bytes', size)
    rec = dict(name='duke_skinned',
               source='voxels/player/1511_DUKE.kvx (torso, legs), 1405_DUKE.kvx (head) of Voxel Duke Nukem 3D by '
                      'Cheello (PRIVATE); arms and hands voxelised from v7\'s bind body, Voxel Duke skin ramp',
               voxel_m=round(G.s, 5), hand_voxel_m=round(G.h, 5), fine_factor=fh,
               verts=nv, tris=int(len(T)), atlas=list(m['stats']['atlas']), signed_volume_m3=round(vol, 5), weld=weld,
               max_influences=int((w > 0).sum(1).max()), headverts=int(hv.sum()), fphide=int(fp.sum()),
               bones_used=sorted({sk.names[int(b)] for b in np.unique(idx[w > 0])}),
               hand_bind='v7 bind: open flat hand, every finger bone along its own -Z (XR joint frames, +Y = back of '
                         'the hand), index/little slightly splayed; the hand bone = XR wrist joint frame',
               frames=rec_frames)
    (ROOT / 'metadata/assets/duke.json').write_text(json.dumps(rec, indent=1))
    log(json.dumps({k: v for k, v in rec.items() if k not in ('frames', 'bones_used')}))


if __name__ == '__main__':
    main()
