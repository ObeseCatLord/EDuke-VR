#!/usr/bin/env python3
"""CPU preview sheets for the voxel pack (private output: <pack>/previews/).

python3 -I preview.py weapons=detonator,flamethrower [wt=WORLD_TOUR_DIR] [holds=...] [aa=all|id,id] [aaholds=id,id] [hands=all] [contact=1]

  previews/<name>.png        voxel model (re-read from its MD3) next to the v6 original at the same scale,
                             tags marked (muzzle red, palm R green, palm L blue, support yellow), a flash frame
  previews/hold_<name>.png   the model with the pack's skinned hand shells posed from hand_poses_flat.json
  previews/aa/contact_*.png  contact sheets of every AA model next to its v6 original
  previews/aa/<id>.png       one AA model: side, top, first-person view, its HUD frames and pickup tile, v6
  previews/aa/hold_<id>.png  AA holds (the character's own hands when the family belongs to one character)
  previews/hands/<char>.png  each character's hands: back, palm, side, fist and a weapon grip
"""
import json, os, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('EDUKE32_VOXEL_PACK', HERE.parent))
ASSETS = Path(os.environ.get('EDUKE32_VR_ASSETS', ROOT.parent))
sys.path.insert(0, str(HERE))
from softrender import load_md3_mesh, render, label, grid, view_matrix  # noqa: E402
from md3np import read  # noqa: E402

EXP = ROOT / 'exports' / 'eduke32'
PREV = ROOT / 'previews'
TAGC = dict(tag_muzzle=(255, 40, 40), tag_palm_right=(40, 255, 40), tag_palm_left=(60, 120, 255), tag_support=(255, 230, 0))
BG = (46, 52, 64)


def pack_file(rel):
    """pack -> v7-original -> v6-original, like build_vr_def.py."""
    for root in (ROOT, ASSETS / 'v7-original', ASSETS / 'v6-original'):
        p = root / 'exports' / 'eduke32' / rel
        if p.exists():
            return p
    return ROOT / 'exports' / 'eduke32' / rel


def mark(im, m, frame, yaw, pitch, upp, center, size):
    R = view_matrix(yaw, pitch)
    d = ImageDraw.Draw(im)
    for t, c in TAGC.items():
        if t not in m['tags'][frame]:
            continue
        p = np.array(m['tags'][frame][t]['origin']) * np.array([1, -1, 1]) - center
        q = R @ p
        x, y = q[0] / upp + size[0] / 2, -q[1] / upp + size[1] / 2
        d.ellipse([x - 4, y - 4, x + 4, y + 4], outline=c, width=2)


def flash_frame(md3):
    """A frame where the model shows more shells than at rest (flash), else None."""
    from md3parts import parts
    info = parts(md3)
    best = None
    for f in range(1, len(info['frames'])):
        n = sum(1 for i, sh in enumerate(info['shells']) if i != info['body'] and sh['shown'][f])
        if n and (best is None or n > best[0]):
            best = (n, f)
    return None if best is None else best[1]


def weapon_sheet(md3, v6md3, out, title, views=((90, 8), (-90, 8), (205, 30), (-35, -30), (180, 0)), size=(420, 300)):
    ims = []
    mine, mm = load_md3_mesh(md3)
    v6, vm = load_md3_mesh(v6md3)
    allp = np.concatenate([s['pos'] for s in mine] + [s['pos'] for s in v6]) * np.array([1, -1, 1])
    center = (allp.min(0) + allp.max(0)) / 2
    upp = max(np.ptp(allp[:, :2], 0).max() / (size[0] * 0.92), np.ptp(allp[:, 2]) / (size[1] * 0.9))
    for yaw, pitch in views:
        im, _ = render(mine, yaw, pitch, size=size, upp=upp, center=center * np.array([1, -1, 1]))
        mark(im, mm, 0, yaw, pitch, upp, center, size)
        ims.append(label(im, f'voxel {title} yaw{yaw} p{pitch}'))
    fi = flash_frame(md3)
    if fi is not None:
        fm, _ = load_md3_mesh(md3, frame=fi)
        im, _ = render(fm, 60, 15, size=size, upp=upp, center=center * np.array([1, -1, 1]))
        ims.append(label(im, f'voxel {mm["frames"][fi]["name"]} (effect)'))
    else:
        ims.append(label(Image.new('RGB', size, BG), 'no effect frames'))
    for yaw, pitch in views:
        im, _ = render(v6, yaw, pitch, size=size, upp=upp, center=center * np.array([1, -1, 1]))
        mark(im, vm, 0, yaw, pitch, upp, center, size)
        ims.append(label(im, f'v6 {title}'))
    fi6 = flash_frame(v6md3)
    if fi6 is not None:
        fm, _ = load_md3_mesh(v6md3, frame=fi6)
        im, _ = render(fm, 60, 15, size=size, upp=upp, center=center * np.array([1, -1, 1]))
        ims.append(label(im, f'v6 {vm["frames"][fi6]["name"]} (effect)'))
    else:
        ims.append(label(Image.new('RGB', size, BG), 'same scale; muzzle red, palm R green, L blue, support yellow'))
    out.parent.mkdir(parents=True, exist_ok=True)
    grid(ims, 6).save(out)
    print('wrote', out, flush=True)


# ------------------------------------------------------------------ skinned hand shells
def qmat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def read_skin(path):
    rows = Path(path).read_text().split('\n')
    n = int(rows[0].split()[2])
    v = np.array([[float(x) for x in r.split()] for r in rows[1:1 + n]])
    return dict(j0=v[:, 0].astype(int), w=v[:, 1], l0=v[:, 2:5], j1=v[:, 5].astype(int), l1=v[:, 6:9])


W2MD3 = np.array([[0, 0, -1.0], [1.0, 0, 0], [0, 1.0, 0]])     # W (x, y, z) -> MD3 (-z, x, y)


def skin_pose(skin, joints):
    """Vertices (MD3 units) of a shell posed by hold joints (MD3-frame positions, W-frame quaternions), the
    same blend vr.cpp's skinHandShell does."""
    J = np.array(joints, float)
    R = np.array([W2MD3 @ qmat(j[3:]) for j in J])
    p = J[:, :3] * 64
    a = np.einsum('nij,nj->ni', R[skin['j0']], skin['l0']) + p[skin['j0']]
    b = np.einsum('nij,nj->ni', R[skin['j1']], skin['l1']) + p[skin['j1']]
    return skin['w'][:, None] * a + (1 - skin['w'][:, None]) * b


def hand_mesh(side, joints, stem=None):
    """Posed shell mesh dict for softrender (stem: path stem of md3/png/skin; default the pack's hand)."""
    if stem is None:
        stem = pack_file(f'hands/vr_hand_{side}_shell.md3').with_suffix('')
    stem = Path(stem)
    ms, m = load_md3_mesh(stem.with_suffix('.md3'), tex_path=str(stem.with_suffix('.png')))
    skin = read_skin(stem.with_suffix('.skin'))
    return [dict(ms[0], pos=skin_pose(skin, joints))]


def hold_sheet(md3, flat, pose, out, title, stems=None, size=(420, 320)):
    weapon, _ = load_md3_mesh(md3)
    ims = []
    for side in ('right', 'left'):
        joints = flat['poses'][side][pose]['joints']
        hm = hand_mesh(side, joints, (stems or {}).get(side))
        allm = weapon + hm
        palm = np.array(joints[0][:3]) * 64
        for yaw, pitch, whole in ((-90 if side == 'right' else 90, 10, True), (-60 if side == 'right' else 60, 25, False),
                                  (200, 35, False), (-150 if side == 'right' else 150, -35, False)):
            if whole:
                im, _ = render(allm, yaw, pitch, size=size)
            else:
                im, _ = render(allm, yaw, pitch, size=size, upp=0.30 / size[0] * 64, center=palm)
            ims.append(label(im, f'{title} {side} yaw{yaw} p{pitch}' + ('' if whole else ' (close)')))
    out.parent.mkdir(parents=True, exist_ok=True)
    grid(ims, 4).save(out)
    print('wrote', out, flush=True)


def tile_image(art, t, size):
    a = art.rgba(t) if art is not None else None
    T = Image.new('RGB', size, BG)
    if a is None:
        return label(T, f'tile {t}: none')
    I = Image.fromarray(a)
    sc = min(size[0] * 0.95 / I.width, (size[1] - 20) * 0.95 / I.height, 4)
    I = I.resize((max(1, int(I.width * sc)), max(1, int(I.height * sc))), Image.NEAREST)
    T.paste(I, ((size[0] - I.width) // 2, 16 + (size[1] - 16 - I.height) // 2), I)
    return label(T, f'AA tile {t}')


def hud_sheet(md3, v6md3, out, title, art=None, hud=(), pickup=None, notes='', size=(400, 300)):
    """Row 1: the voxel model from the left side, from the top, from the player's first-person angle (behind
    and above the right hand, like the HUD frames) next to two HUD frames. Row 2: v6 side, an effect frame,
    the pickup tile, a third HUD frame and the notes (top features added)."""
    mine, mm = load_md3_mesh(md3)
    v6, vm = load_md3_mesh(v6md3)
    allp = np.concatenate([q['pos'] for q in mine]) * np.array([1, -1, 1])
    center = (allp.min(0) + allp.max(0)) / 2
    upp = max(np.ptp(allp[:, :2], 0).max() / (size[0] * 0.92), np.ptp(allp[:, 2]) / (size[1] * 0.9))
    c3 = center * np.array([1, -1, 1])
    ims = []
    for yaw, pitch, lab in ((90, 5, 'side'), (0, 89, 'top (muzzle up)')):
        im, _ = render(mine, yaw, pitch, size=size, upp=upp, center=c3)
        mark(im, mm, 0, yaw, pitch, upp, center, size)
        ims.append(label(im, f'voxel {title}: {lab}'))
    # HUD framing: from behind-right and a little above, the rear two thirds filling the tile (as the frames
    # crop the weapon at the screen edge)
    ext = np.ptp(allp, 0)
    fp = c3 + np.array([-0.15 * ext[0], 0.0, 0.0])
    im, _ = render(mine, 205, 20, size=size, upp=upp * 0.7, center=fp)
    ims.append(label(im, f'voxel {title}: first person'))
    hud = list(hud)
    for t in hud[:2]:
        ims.append(tile_image(art, t, size))
    while len(ims) < 5:
        ims.append(label(Image.new('RGB', size, BG), ''))
    im, _ = render(v6, 90, 5, size=size, upp=upp, center=c3)
    ims.append(label(im, f'v6 {title}: side'))
    fi = flash_frame(md3)
    if fi is not None:
        fm, _ = load_md3_mesh(md3, frame=fi)
        im, _ = render(fm, 60, 15, size=size, upp=upp, center=c3)
        ims.append(label(im, f'voxel {mm["frames"][fi]["name"]} (effect)'))
    else:
        ims.append(label(Image.new('RGB', size, BG), 'no effect frames'))
    ims.append(tile_image(art, pickup, size) if pickup else label(Image.new('RGB', size, BG), 'no pickup tile'))
    ims.append(tile_image(art, hud[2], size) if len(hud) > 2 else label(Image.new('RGB', size, BG), ''))
    note = Image.new('RGB', size, BG)
    d = ImageDraw.Draw(note)
    for i in range(0, min(len(notes), 56 * 22), 56):
        d.text((6, 6 + 12 * (i // 56)), notes[i:i + 56], fill=(230, 230, 230))
    ims.append(note)
    out.parent.mkdir(parents=True, exist_ok=True)
    grid(ims, 5).save(out)
    print('wrote', out, flush=True)


def aa_sheet(fid, art, size=(400, 300)):
    inv = {f['id']: f for f in json.loads((ASSETS / 'v6-original/metadata/aa_inventory.json').read_text())['families']}
    rec = json.loads((ROOT / 'metadata/assets' / f'aa_{fid}.json').read_text()) if (ROOT / 'metadata/assets' / f'aa_{fid}.json').is_file() else {}
    ref = inv[fid]['reference_tiles']
    hud = rec.get('hud_tiles') or [ref[0], ref[0] + 1, ref[0] + 2]
    src = rec.get('source') if isinstance(rec.get('source'), dict) else {}
    notes = f"kind: {rec.get('kind')}  source: {src.get('aa_voxel') or src.get('aa_tile') or rec.get('reuses') or rec.get('source')}  " \
            f"top features: {'; '.join(rec.get('top_features', [])) or 'none added'}"
    hud_sheet(EXP / 'aa' / f'{fid}.md3', ASSETS / 'v6-original/exports/eduke32/aa' / f'{fid}.md3', PREV / 'aa' / f'{fid}.png',
              fid, art, hud, rec.get('pickup_tile'), notes, size)


def skin_pose_grip(skin, joints):
    """Shell vertices posed by a free (grip-frame) pose; the grip frame is drawn as the model frame."""
    J = np.array(joints, float)
    R = np.array([qmat(j[3:]) for j in J])
    p = J[:, :3] * 64
    a = np.einsum('nij,nj->ni', R[skin['j0']], skin['l0']) + p[skin['j0']]
    b = np.einsum('nij,nj->ni', R[skin['j1']], skin['l1']) + p[skin['j1']]
    g = skin['w'][:, None] * a + (1 - skin['w'][:, None]) * b
    return np.stack([-g[:, 2], g[:, 0], g[:, 1]], 1)       # grip (-Z along the grip) -> view frame


def hands_sheet(name, chars, flat, art=None, hold=None, size=(300, 300)):
    """One character: right hand bind pose (back, palm, thumb side, little-finger side), relaxed and fist
    poses, both hands on a weapon hold, next to the character's AA HUD hand tiles."""
    info = chars[name]
    ims = []
    stems = {side: ROOT / info['files'][side]['md3'][:-4] for side in ('left', 'right')}
    ms, m = load_md3_mesh(stems['right'].with_suffix('.md3'), tex_path=str(stems['right'].with_suffix('.png')))
    pos = ms[0]['pos']
    # bind: palm frame (x little finger, y back of hand, z wrist); view frame (x fwd = -z, y = x, z = y)
    bind = [dict(ms[0], pos=np.stack([-pos[:, 2], pos[:, 0], pos[:, 1]], 1))]
    for yaw, pitch, lab in ((0, 89, 'back'), (0, -89, 'palm'), (90, 0, 'thumb side'), (-90, 0, 'little side')):
        im, _ = render(bind, yaw, pitch, size=size)
        ims.append(label(im, f'{name} right {lab}'))
    skin = read_skin(stems['right'].with_suffix('.skin'))
    for pose in ('relaxed', 'fist'):
        P = skin_pose_grip(skin, flat['poses']['right'][pose]['joints'])
        im, _ = render([dict(ms[0], pos=P)], 150, 25, size=size)
        ims.append(label(im, f'{name} right {pose}'))
    if hold:
        md3, pose = hold
        weapon, _ = load_md3_mesh(md3)
        for side, yaw in (('right', -60), ('left', 60)):
            joints = flat['poses'][side][pose]['joints']
            hm = hand_mesh(side, joints, stems[side])
            palm = np.array(joints[0][:3]) * 64
            im, _ = render(weapon + hm, yaw, 25, size=size, upp=0.30 / size[0] * 64, center=palm)
            ims.append(label(im, f'{pose} {side}'))
    if art is not None:
        for t in info.get('reference_tiles', []):
            a = art.rgba(t)
            if a is None:
                continue
            I = Image.fromarray(a)
            sc = min(size[0] * 0.95 / I.width, (size[1] - 20) * 0.95 / I.height, 3)
            I = I.resize((max(1, int(I.width * sc)), max(1, int(I.height * sc))), Image.NEAREST)
            T = Image.new('RGB', size, BG)
            T.paste(I, ((size[0] - I.width) // 2, 16 + (size[1] - 16 - I.height) // 2), I)
            ims.append(label(T, f'AA HUD tile {t}'))
    if name == 'duke':                             # Voxel Duke's own forearm gib for comparison
        from kvx import read_kvx
        f = ROOT / 'source/voxels/player/1528_ARM.kvx'
        if f.is_file():
            k = read_kvx(f)
            g, pal = k['grid'], k['palette']
            for ax, lab in ((1, 'side'), (0, 'front')):
                occ = g >= 0
                first = np.argmax(occ, axis=ax)
                idx = np.take_along_axis(g, np.expand_dims(first, ax), ax).squeeze(ax)
                img = np.where(occ.any(ax)[..., None], pal[np.clip(idx, 0, 255)], np.array(BG)).astype(np.uint8)
                I = Image.fromarray(np.transpose(img, (1, 0, 2)))
                sc = max(1, int((size[1] - 20) / I.height))
                I = I.resize((I.width * sc, I.height * sc), Image.NEAREST)
                T = Image.new('RGB', size, BG)
                T.paste(I, ((size[0] - I.width) // 2, 16))
                ims.append(label(T, f'Voxel Duke 1528_ARM gib ({lab})'))
    out = PREV / 'hands' / f'{name}.png'
    out.parent.mkdir(parents=True, exist_ok=True)
    grid(ims, 6).save(out)
    print('wrote', out, flush=True)


def contact_sheets(per=24, size=(260, 170)):
    """previews/aa/contact_<n>.png: every AA model (voxel, left) next to its v6 original (right), side view,
    same scale per pair."""
    v6dir = ASSETS / 'v6-original/exports/eduke32/aa'
    ids = sorted(p.stem for p in (EXP / 'aa').glob('*.md3'))
    for n0 in range(0, len(ids), per):
        ims = []
        for fid in ids[n0:n0 + per]:
            mine, _ = load_md3_mesh(EXP / 'aa' / f'{fid}.md3')
            v6, _ = load_md3_mesh(v6dir / f'{fid}.md3')
            allp = np.concatenate([q['pos'] for q in mine] + [q['pos'] for q in v6]) * np.array([1, -1, 1])
            c = (allp.min(0) + allp.max(0)) / 2 * np.array([1, -1, 1])
            upp = max(np.ptp(allp[:, :2], 0).max() / (size[0] * 0.92), np.ptp(allp[:, 2]) / (size[1] * 0.85))
            a_, _ = render(mine, 90, 8, size=size, upp=upp, center=c)
            b_, _ = render(v6, 90, 8, size=size, upp=upp, center=c)
            ims += [label(a_, f'{fid} (voxel)'), label(b_, 'v6')]
        out = PREV / 'aa' / f'contact_{n0 // per + 1}.png'
        out.parent.mkdir(parents=True, exist_ok=True)
        grid(ims, 6).save(out)
        print('wrote', out, flush=True)


def wt_tiles(root, tiles):
    """Reference tiles from a Duke Nukem 3D World Tour install (preview only; the builder never reads it): the
    palette from DUKE3D.GRP, the tiles from the loose TILESnnn.ART files. Read as data only."""
    import struct
    root = Path(root)
    d = (root / 'DUKE3D.GRP').read_bytes()
    n = struct.unpack_from('<i', d, 12)[0]
    off = 16 + 16 * n
    pal = None
    for i in range(n):
        name = d[16 + 16 * i:28 + 16 * i].split(b'\0')[0].decode('ascii', 'replace').upper()
        size = struct.unpack_from('<i', d, 28 + 16 * i)[0]
        if name == 'PALETTE.DAT':
            pal = np.clip(np.frombuffer(d, np.uint8, 768, off).reshape(256, 3).astype(int) * 255 // 63, 0, 255).astype(np.uint8)
        off += size
    out = {}
    for f in sorted(root.glob('TILES*.ART')):
        b = f.read_bytes()
        ver, _, start, end = struct.unpack_from('<4i', b, 0)
        cnt = end - start + 1
        sx = np.frombuffer(b, '<i2', cnt, 16)
        sy = np.frombuffer(b, '<i2', cnt, 16 + 2 * cnt)
        o = 16 + 8 * cnt
        for i in range(cnt):
            sz = int(sx[i]) * int(sy[i])
            if start + i in tiles and sz > 0 and pal is not None:
                t = np.frombuffer(b, np.uint8, sz, o).reshape(sx[i], sy[i]).T
                rgba = np.zeros(t.shape + (4,), np.uint8)
                rgba[..., :3] = pal[t]
                rgba[..., 3] = np.where(t == 255, 0, 255)
                out[start + i] = rgba
            o += max(sz, 0)
    return out


def add_reference_row(path, refs, size=(420, 300)):
    """Append a row of reference tiles to a preview sheet."""
    im = Image.open(path)
    tiles = []
    for t, a in refs.items():
        I = Image.fromarray(a)
        sc = min(size[0] * 0.95 / I.width, (size[1] - 20) * 0.95 / I.height, 4)
        I = I.resize((max(1, int(I.width * sc)), max(1, int(I.height * sc))), Image.NEAREST)
        T = Image.new('RGB', size, BG)
        T.paste(I, ((size[0] - I.width) // 2, 16 + (size[1] - 16 - I.height) // 2), I)
        tiles.append(label(T, f'World Tour tile {t} (reference)'))
    if not tiles:
        return
    row = grid(tiles, len(tiles))
    out = Image.new('RGB', (max(im.width, row.width), im.height + row.height), (20, 20, 20))
    out.paste(im, (0, 0))
    out.paste(row, (0, im.height))
    out.save(path)


def main():
    args = dict(a.split('=', 1) for a in sys.argv[1:])
    flat = json.loads((ROOT / 'metadata' / 'hand_poses_flat.json').read_text())
    v6 = ASSETS / 'v6-original' / 'exports' / 'eduke32'
    for n in [x for x in args.get('weapons', '').split(',') if x]:
        weapon_sheet(EXP / f'vr_{n}.md3', v6 / f'vr_{n}.md3', PREV / f'{n}.png', n)
        if n == 'flamethrower' and args.get('wt'):          # wt=PATH: World Tour install (reference only)
            add_reference_row(PREV / f'{n}.png', wt_tiles(args['wt'], (5134, 5138, 5139, 5140)))
    for n in [x for x in args.get('holds', '').split(',') if x]:
        hold_sheet(EXP / f'vr_{n}.md3', flat, f'hold_{n}', PREV / f'hold_{n}.png', f'hold_{n}')
    if args.get('aa'):
        import aaart
        install = aaart.find_install(args.get('aa_install') or os.environ.get('EDUKE32_AA_INSTALL'))
        art = aaart.Art(install) if install else None
        ids = sorted(p.stem for p in (EXP / 'aa').glob('*.md3')) if args['aa'] == 'all' else args['aa'].split(',')
        for fid in ids:
            aa_sheet(fid, art)
    if args.get('hands'):
        import aaart
        install = aaart.find_install(args.get('aa_install') or os.environ.get('EDUKE32_AA_INSTALL'))
        art = aaart.Art(install) if install else None
        cj = ROOT / 'metadata' / 'characters.json'
        chars = json.loads(cj.read_text()) if cj.is_file() else \
            dict(duke=json.loads((ROOT / 'metadata' / 'assets' / 'duke_hands.json').read_text()))
        refs = dict(duke=[2564, 2571, 2529], bombshell=[7778, 7679, 7685], wes=[19456, 19461, 19697],
                    mando=[20711, 20714, 20713], deanova=[22004, 21973, 21920])
        holds = dict(duke=('vr_pistol.md3', 'hold_pistol'), bombshell=('aa/shelly_pistol.md3', 'hold_shelly_pistol'),
                     wes=('aa/wes_revolver.md3', 'hold_wes_revolver'), mando=('aa/mando_pmp.md3', 'hold_mando_pmp'),
                     deanova=('aa/dea_shotgun.md3', 'hold_dea_shotgun'))
        for n in (list(chars) if args['hands'] == 'all' else args['hands'].split(',')):
            h = holds.get(n)
            if h and not (EXP / h[0]).is_file():
                h = ('vr_pistol.md3', 'hold_pistol')
            hands_sheet(n, {k: dict(v, reference_tiles=refs.get(k, [])) for k, v in chars.items()}, flat, art,
                        (EXP / h[0], h[1]) if h else None)
    if args.get('contact'):
        contact_sheets()
    aaholds = [x for x in args.get('aaholds', '').split(',') if x]
    if aaholds == ['all']:
        aaholds = sorted(p.stem for p in (EXP / 'aa').glob('*.md3'))
    inv = {f['id']: f for f in json.loads((ASSETS / 'v6-original/metadata/aa_inventory.json').read_text())['families']}
    who = dict(Shelly='bombshell', Wes='wes', Mando='mando', Dea='deanova')
    for fid in aaholds:
        chars = inv.get(fid, {}).get('characters', [])
        stems = None
        if len(chars) == 1 and chars[0] in who:     # a single character's weapon: show her/his own hands
            d = EXP / 'characters' / who[chars[0]] / 'hands'
            if (d / 'vr_hand_right_shell.md3').is_file():
                stems = {side: d / f'vr_hand_{side}_shell' for side in ('left', 'right')}
        hold_sheet(EXP / 'aa' / f'{fid}.md3', flat, f'hold_{fid}', PREV / 'aa' / f'hold_{fid}.png',
                   f'hold_{fid}' + (f' ({who[chars[0]]})' if stems else ''), stems=stems)


if __name__ == '__main__':
    main()
