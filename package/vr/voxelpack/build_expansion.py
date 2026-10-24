#!/usr/bin/env python3
"""Held models that Voxel Duke Nukem 3D has no voxel for, kitbashed from its other voxels.

python3 -I build_expansion.py [names=detonator,flamethrower]

  vr_flamethrower  World Tour Incinerator, matched to its own art (pickup 5134, HUD 5138-5140): the freezer's
                   hull (weapons/24) recoloured red/orange with a pressure gauge on top in place of its crystal,
                   hazard stripes on the rear deck, the shotgun's pistol grip + trigger under the rear
                   (weapons/28), the freezer's side handle for the left hand, the fire effect voxels
                   (effects/2270, 2274) as the flame and a small blocky pilot light.
  vr_detonator     remote detonator: the trip bomb pickup panel (weapons/27, keypad + LED face toward the
                   player) deepened into a hand-held box, a round red push-button cap in the microphone head's
                   reds (props/762) and the microphone stand's pole as the antenna (tip recoloured red).

Same contract and placement rules as build_weapons.py (v6 frames/tags/order, one surface, +X muzzle,
64 units/m, palm tags on the grip voxels' side faces, scale = v6 length along X). The flamethrower flame
(two fire voxels alternating) is shown in the frames where v6 shows its flame and follows v6's flame size per
frame; the pilot light only in `rest`, like v6. The detonator's LED blinks in v6's LED frames.
Each piece used is listed in metadata/assets/<name>.json (`kitbash`).
"""
import json, os, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('EDUKE32_VOXEL_PACK', HERE.parent))
sys.path.insert(0, str(HERE))
import build_weapons as BW  # noqa: E402
from kitbash import Kit, Piece, Shape, load, ramp, nearest_index  # noqa: E402
from md3parts import parts as md3_parts  # noqa: E402
from kvx import fill_solid  # noqa: E402

VOX = ROOT / 'source' / 'voxels'
STD = dict(fwd='-x', left='+y', up='-z')
CREDIT = 'Voxel Duke Nukem 3D by Cheello, PRIVATE'


def duke_palette():
    """The Duke Nukem 3D palette, as carried by the mod's own KVX files."""
    return load(VOX, 'weapons/21_PISTOL')['palette']


def palette_colour(rgb):
    pal = duke_palette()
    return tuple(int(c) for c in pal[int(nearest_index(np.array([rgb], np.uint8), pal)[0])])


def shift_box(box, shift):
    return {a: (box[a][0] + shift[i], box[a][1] + shift[i]) for i, a in enumerate('xyz') if a in box}


# ------------------------------------------------------------------ flamethrower (World Tour Incinerator)
def flamethrower_kit():
    """The World Tour Incinerator as its art draws it (pickup 5134, HUD 5138-5140: the freezer's hull in red and
    orange, a pressure gauge on top, a hazard-striped deck, a dark nozzle drum at the front, a rear grip for
    the right hand and the side handle for the left): Voxel Duke's freezer voxel (weapons/24) recoloured from
    its yellow to a red-orange ramp, its crystal dome replaced by a round gauge, hazard stripes on the rear deck
    and the shotgun's pistol grip and trigger (weapons/28) under the rear."""
    global PALETTE_YELLOW, PALETTE_BLACK
    PALETTE_YELLOW, PALETTE_BLACK = palette_colour((235, 190, 20)), palette_colour((24, 22, 20))
    kit = Kit()
    ramp = np.array([(104, 24, 10), (164, 44, 18), (214, 92, 30), (238, 146, 58)], np.uint8)

    def reds(rgb, occ):
        c = rgb.astype(int)
        yellow_ = occ & (c[..., 0] > 110) & (c[..., 1] > 0.55 * c[..., 0]) & (c[..., 2] < 0.6 * c[..., 1])
        lum = c.sum(-1)
        out = rgb.copy()
        q = np.clip(((lum - 200) / 300 * 4).astype(int), 0, 3)       # dark -> light, as the yellow was
        out[yellow_] = ramp[q[yellow_]]
        return out
    hull = Piece(VOX, 'weapons/24_FREEZE')
    hull.recolour(reds, 'the freezer\'s yellow hull -> red / orange ramp by brightness (WT Incinerator colours)')
    dome = np.zeros(hull.shape, bool)
    dome[18:27, :, :6] = True                      # the crystal dome on top of the front
    hull.occ &= ~dome
    hull.log['ops'].append('crystal dome on top (x 18..26, z 0..5) removed for the gauge')
    yellow, black = PALETTE_YELLOW, PALETTE_BLACK

    def stripes(rgb, occ):
        out = rgb.copy()
        X, Y, Z = np.indices(occ.shape)
        top = np.zeros_like(occ)
        zt = np.where(occ.any(2), np.argmax(occ, 2), 99)
        top[X[..., 0], Y[..., 0], np.clip(zt, 0, occ.shape[2] - 1)] = occ.any(2)
        yc = occ.shape[1] / 2
        band = top & (X >= 42) & (X <= 55) & (np.abs(Y - yc) <= 9) & (Z <= 8)     # a band across the deck
        on = ((X + Y) // 3) % 2 == 0                                                 # clean 3-voxel diagonals
        out[band & on] = yellow
        out[band & ~on] = black
        return out
    hull.recolour(stripes, f'hazard stripes on the top deck x 40..58: {yellow} / {black}')
    kit.paste(hull, (0, 0, 0), 'hull')
    # pressure gauge on top of the front: a round dial facing the player (white face, dark rim, red needle)
    n, c = 9, 4
    occ = np.zeros((3, n, n), bool)
    rgb = np.zeros((3, n, n, 3), np.uint8)
    yy, zz = np.meshgrid(np.arange(n), np.arange(n), indexing='ij')
    r = np.hypot(yy - c, zz - c)
    occ[:, r <= 4.3] = True
    rgb[:] = (40, 40, 44)
    rgb[2][r <= 3.2] = (226, 222, 210)
    needle = (np.abs((yy - c) + (zz - c)) <= 0.6) & (r <= 3.0) & (yy >= c)
    rgb[2][needle] = (200, 30, 20)
    rgb[2][(r <= 3.2) & (zz <= 2) & (yy >= 5)] = (60, 170, 60)      # green arc
    # sits flush on the hull top: the dial's lowest row rests on the deck, a short dark collar fills under it
    ho = hull.occ
    zt = min(int(np.nonzero(ho[x, y])[0].min()) for x in range(20, 23) for y in range(11, 20) if ho[x, y].any())
    z0 = zt - n + 2
    kit.paste(Shape(occ, rgb, 'round pressure gauge 9 voxels across: dark rim, white face, green arc, red needle'),
              (20, 11, z0), 'gauge')
    collar = np.zeros((4, 5, 3), bool)
    collar[:] = True
    crgb = np.zeros((4, 5, 3, 3), np.uint8)
    crgb[:] = (40, 40, 44)
    kit.paste(Shape(collar, crgb, 'short dark collar under the gauge'), (19, 13, zt - 1), 'collar', under=True)
    # the shotgun's pistol grip, trigger and guard under the rear (right hand), hull voxels win
    grip = Piece(VOX, 'weapons/28_SHOTGUN', box=[(66, 87), (0, 5), (9, 24)])
    kit.paste(grip, (45, 4, 22), 'grip_piece', under=True)
    kit.marks['grip'] = ([55, 4, 26], [65, 9, 36])            # shotgun grip x 76..86, z 13..23
    kit.marks['trigger'] = ([49, 4, 24], [51, 9, 26])         # shotgun trigger x 70..72, z 11..13
    kit.marks['support'] = ([31, 23, 10], [35, 29, 14])       # the freezer's side handle (left hand)
    kit.marks['wand'] = ([0, 0, 0], [12, 29, 26])             # the nozzle drum
    return kit


def fire_part(rel, s, palette):
    """A fire effect voxel, downsampled 2x, closed then opened (no lone voxels), pointing forward (+X), its
    largest solid piece."""
    p = Piece(VOX, rel).orient((2, 1, 0)).downsample(2, occ_frac=0.3)
    from scipy import ndimage
    occ = fill_solid(ndimage.binary_closing(p.occ, iterations=1) | p.occ)
    occ = ndimage.binary_opening(occ, structure=ndimage.generate_binary_structure(3, 1))   # no 1-voxel spikes
    lab, n = ndimage.label(occ)
    if n > 1:
        sizes = ndimage.sum(occ, lab, range(1, n + 1))
        occ = lab == (1 + int(np.argmax(sizes)))
    _, ind = ndimage.distance_transform_edt(~p.occ, return_indices=True)
    rgb = p.rgb[tuple(ind)]
    return occ, rgb, p.log


def flamethrower_extra(v6):
    """Flame (two fire voxels alternating, following v6's flame per frame) and the pilot light (rest only)."""
    info = md3_parts(BW.V6 / 'exports/eduke32/vr_flamethrower.md3')
    frames = info['frames']
    v6_muzzle = info['tags'][0]['tag_muzzle']
    effects = [sh for i, sh in enumerate(info['shells']) if i != info['body']]
    flame = max(effects, key=lambda sh: sh['shown'].sum())
    pilot = min(effects, key=lambda sh: sh['shown'].sum())
    X = info['X']
    logs = []

    def make(ctx):
        s, muzzle = ctx['s'], ctx['muzzle']
        out = []
        shown = [f for f in range(len(frames)) if flame['shown'][f]]
        for variant, rel in enumerate(('effects/2270_FIRE', 'effects/2274_FIRE')):
            occ, rgb, log = fire_part(rel, s, None)
            logs.append(log)
            n = np.array(occ.shape, float)
            # grid (x = tip .. base, y, z down) -> MD3 metres*64 with the base on the muzzle plane
            A = np.zeros((3, 4))
            A[0, 0] = -s * 64; A[0, 3] = (muzzle[0] + n[0] * s) * 64
            A[1, 1] = s * 64;  A[1, 3] = (muzzle[1] - n[1] * s / 2) * 64
            A[2, 2] = -s * 64; A[2, 3] = (muzzle[2] + n[2] * s / 2) * 64
            lo = np.array([muzzle[0], muzzle[1] - n[1] * s / 2, muzzle[2] - n[2] * s / 2])
            hi = np.array([muzzle[0] + n[0] * s, muzzle[1] + n[1] * s / 2, muzzle[2] + n[2] * s / 2])
            show, aff = [], {}
            for f in shown[variant::2]:
                P = X[f, flame['verts']]
                tlo, thi = P.min(0) - v6_muzzle + muzzle, P.max(0) - v6_muzzle + muzzle
                sc = (thi - tlo) / (hi - lo)
                aff[frames[f]] = (np.diag(sc), tlo - lo * sc)
                show.append(frames[f])
            out.append(dict(part=dict(solid=occ, rgb=rgb, glow=occ.copy(), A=A), show=show, affine=aff,
                            hide=muzzle - np.array([0.012, 0, 0])))
        # pilot light: a tiny blocky flame just under the nozzle tip (v6 shows it at rest only)
        pc = (X[pilot['ref'], pilot['verts']].min(0) + X[pilot['ref'], pilot['verts']].max(0)) / 2 - v6_muzzle
        pf = BW.flash_part(muzzle + np.array([-0.004, 0, pc[2]]), 0.012, ((200, 230, 255), (60, 110, 255)), s)
        out.append(dict(part=pf, show=[frames[f] for f in range(len(frames)) if pilot['shown'][f]], hide=muzzle - np.array([0.012, 0, 0])))
        return out
    return make, logs


# ------------------------------------------------------------------ detonator
def detonator_kit():
    kit = Kit()
    # body: the trip bomb pickup panel (35 long, 5 deep, 12 high; keypad face toward +y) stood up with its
    # face toward the player (kit +x = rear) and deepened by repeating its back plate
    body = Piece(VOX, 'weapons/27_TRIPBOMB').orient((1, 2, 0)).extrude(0, 12, at_low=True)
    kit.paste(body, (0, 0, 0), 'body')
    # push button: a round cap (7 voxels across, domed top) on a dark collar, in the microphone head's reds
    head = Piece(VOX, 'props/762_MIC', box=[(1, 7), (6, 10), (0, 5)])
    reds = ramp(head.rgb, head.occ, lambda c: c[..., 0] > c[..., 1] + 40)
    red = tuple(int(c) for c in reds[len(reds) // 2])
    collar = tuple(int(c) for c in body.rgb[body.occ][0])
    occ = np.zeros((9, 9, 5), bool)
    rgb = np.zeros((9, 9, 5, 3), np.uint8)
    i, j = np.indices((9, 9)) - 4
    r2 = i * i + j * j
    for z, rad, col in ((0, 2.3, reds[-1]), (1, 3.2, reds[len(reds) * 3 // 4]), (2, 3.6, reds[len(reds) // 2]),
                        (3, 3.6, reds[len(reds) // 3]), (4, 4.5, collar)):
        m = r2 <= rad * rad
        occ[:, :, z] = m
        rgb[:, :, z][m] = col
    button = Shape(occ, rgb, 'round push-button cap: radii 2.3/3.2/3.6/3.6 voxels from the top, collar 4.5; '
                   'colours = the red ramp of props/762_MIC (microphone head), collar = the panel back plate')
    kit.paste(button, (4, 1, -5), 'button')
    # antenna: the microphone stand's pole with its clamp at the base, the top two voxels painted red
    pole = Piece(VOX, 'props/762_MIC', box=[(7, 10), (7, 10), (30, 53)]).orient((0, 1, 2), flip=(2,))

    def tip(rgb, occ):
        rgb = rgb.copy()
        rgb[:, :, :2][occ[:, :, :2]] = red
        return rgb
    pole.recolour(tip, f'top two voxels painted {red} (the mic head red)')
    kit.paste(pole, (13, 8, -24), 'antenna')
    kit.marks['grip'] = ([0, 0, 6], [16, 11, 30])
    return kit


def led_mask(k, kit):
    """The trip bomb panel's red LED voxels (glow)."""
    g, pal = k['grid'], k['palette']
    rgb = pal[np.clip(g, 0, 255)].astype(int)
    lo, hi = kit.box('body', k['shift'])['x'], kit.box('body', k['shift'])['z']
    m = (g >= 0) & (rgb[..., 0] > 150) & (rgb[..., 1] < 80) & (rgb[..., 2] < 80)
    keep = np.zeros_like(m)
    keep[:, :, hi[0]:hi[1] + 1] = True
    return m & keep


def detonator_extra(v6, led_centre):
    info = md3_parts(BW.V6 / 'exports/eduke32/vr_detonator.md3')
    frames = info['frames']
    eff = [sh for i, sh in enumerate(info['shells']) if i != info['body']]

    def make(ctx):
        s = ctx['s']
        c = ctx['to_md3'](led_centre)
        n = 3
        g = np.ones((n, n, n), bool)
        rgb = np.zeros((n, n, n, 3), np.uint8); rgb[:] = (255, 40, 30); rgb[1, 1, 1] = (255, 200, 160)
        cell = s * 0.7
        A = np.zeros((3, 4))
        A[0, 0] = A[1, 1] = A[2, 2] = cell * 64
        A[:, 3] = (c - n * cell / 2) * 64
        show = [frames[f] for f in range(len(frames)) if any(sh['shown'][f] for sh in eff)]
        return [dict(part=dict(solid=g, rgb=rgb, glow=g.copy(), A=A), show=show, hide=c)]
    return make


# ------------------------------------------------------------------ build
def build(name):
    palette = duke_palette()
    if name == 'flamethrower':
        kit = flamethrower_kit()
    else:
        kit = detonator_kit()
    k = kit.grid(palette)
    sh = k['shift']
    spec = dict(kvx=None, **STD, grip=kit.box('grip', sh))
    if name == 'flamethrower':
        spec.update(trigger=kit.box('trigger', sh), muzzle=kit.box('wand', sh), support=kit.box('support', sh))
        make, fire_logs = flamethrower_extra(None)
        spec['glow_mask'] = np.zeros(k['solid'].shape, bool)
        extra = make
        flashes = {}
    else:
        spec.update(support='v6', muzzle='v6', grip_axis=(0.0, 1.0))
        led = led_mask(k, kit)
        spec['glow_mask'] = led
        led_centre = np.argwhere(led).mean(0) + 0.5 if led.any() else np.array(k['size']) / 2
        fire_logs = []
        flashes = {}
        maker = detonator_extra(None, led_centre)
        extra = None

    # the placement callback needs the grid -> MD3 map; build_weapons passes M and t
    def extra_cb(ctx):
        ctx = dict(ctx, to_md3=lambda p: np.asarray(p, float) @ ctx['M'].T + ctx['t'])
        return (make if name == 'flamethrower' else maker)(ctx)

    pieces = [dict(p) for p in kit.pieces]
    source = dict(kitbash=pieces, credit=CREDIT)
    rec = BW.build(name, spec=spec, k=k, flashes=flashes, collapsed=[], extra=extra_cb, source=source)
    if fire_logs:
        rec['kitbash_effects'] = fire_logs
        p = BW.META / f'{name}.json'
        p.write_text(json.dumps(rec, indent=1))
    return rec


def main():
    args = dict(a.split('=', 1) for a in sys.argv[1:])
    names = ['detonator', 'flamethrower'] if args.get('names', 'all') == 'all' else args['names'].split(',')
    for n in names:
        build(n)


if __name__ == '__main__':
    main()
