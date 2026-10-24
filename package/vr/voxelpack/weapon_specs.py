"""Per-weapon mapping of the Voxel Duke Nukem 3D pickup voxels onto the v6 held-weapon contract.

All boxes are inclusive KVX voxel index ranges (x, y, z; KVX z points DOWN, z = 0 is the top slice).
Axes: `fwd`, `left`, `up` give the KVX axis (signed) that becomes the weapon's true forward / left / up.
The pickup voxels stand upright with the muzzle toward KVX -x and their left side toward KVX +y.

grip      : voxels the trigger hand wraps (palm tags = centroids of its lateral faces, v6 rule)
handlebar : grip is a horizontal side handle held palm-down (Duke 3D HUD style); palm tags on its top
trigger   : trigger blade voxels (index pad target on its front face), optional
muzzle    : region whose front-most slab gives tag_muzzle (default: whole model)
support   : off-hand region (tag_support = its voxel centroid) or 'v6' (v6 point relative to the palm)
scale_axis: MD3 axis whose v6 extent the voxel extent is scaled to (real-world size)
glow      : texel colours that go into the _glow map besides the muzzle flash
"""

STD = dict(fwd='-x', left='+y', up='-z')

SPECS = {
    'pistol': dict(kvx='21_PISTOL', **STD, grip=dict(x=(25, 38), z=(8, 20)), trigger=dict(x=(21, 22), z=(7, 9)),
                   support='v6'),
    'shotgun': dict(kvx='28_SHOTGUN', **STD, grip=dict(x=(76, 86), z=(13, 23)), trigger=dict(x=(70, 72), z=(11, 13)),
                    muzzle=dict(z=(0, 4)), support=dict(x=(28, 37), z=(10, 20))),
    'chaingun': dict(kvx='22_RIPPER', **STD, grip=dict(x=(76, 88), y=(0, 16), z=(3, 11)),
                     support=dict(x=(30, 35), y=(18, 28), z=(15, 20)), glow='fullbright'),
    'rpg': dict(kvx='23_RPG', **STD, grip=dict(x=(28, 30), y=(19, 26), z=(16, 18)), handlebar=True,
                support=dict(x=(20, 36), y=(0, 18), z=(17, 23))),
    'freezer': dict(kvx='24_FREEZE', **STD, grip=dict(x=(31, 35), y=(23, 29), z=(10, 14)), handlebar=True,
                    support=dict(x=(26, 36), y=(0, 22), z=(3, 8))),
    'shrinker': dict(kvx='25_SHRINK', **STD, grip=dict(x=(65, 78), z=(19, 25)), grip_axis=(0.0, 1.0),
                     support=dict(x=(38, 48), z=(12, 17)), glow='green'),
    'expander': dict(kvx='32_EXPANDER', **STD, grip=dict(x=(65, 78), z=(43, 49)), grip_axis=(0.0, 1.0),
                     support=dict(x=(38, 48), z=(36, 41)), glow='orange'),
    'devastator': dict(kvx='29_DEVASTATOR', **STD, grip=dict(x=(48, 52), y=(0, 21), z=(17, 23)),
                       trigger=dict(x=(46, 46), y=(0, 21), z=(17, 20)), muzzle=dict(y=(0, 21)),
                       support=dict(x=(48, 52), y=(28, 49), z=(17, 23)), glow='red'),
    'tripbomb': dict(kvx='2566_TRIPBOMB', **STD, grip=dict(x=(104, 143), z=(4, 44)), support='v6',
                     glow='red'),
    'pipebomb': dict(kvx='26_PIPE', fwd='+z', left='-y', up='+x', scale_axis=2, grip=dict(x=(30, 66)),
                     support='v6', muzzle='v6'),
}

# v6 muzzle-flash visibility (from the v6 flash shells, see README) and collapsed (thrown/placed) frames.
FLASH = {
    'pistol': {'flash': ['fire_01', 'fire_02']},
    'shotgun': {'flash': ['fire_01', 'fire_02', 'fire_03', 'fire_04']},
    'chaingun': {'flash': ['fire_03', 'fire_04', 'fire_06', 'fire_07', 'fire_09', 'fire_10']},
    'rpg': {'flash': ['fire_%02d' % i for i in range(1, 8)]},
    'freezer': {'flash': ['fire_%02d' % i for i in range(1, 6)]},
    'shrinker': {'flash': ['fire_10', 'fire_11', 'fire_12']},
    'expander': {'flash': ['fire_03', 'fire_04', 'fire_05']},
    'devastator': {'flash_l': ['fire_03', 'fire_04'], 'flash_r': ['fire_03', 'fire_04', 'fire_05']},
    'tripbomb': {},
    'pipebomb': {},
}
COLLAPSED = {
    'pipebomb': ['fire_%02d' % i for i in range(12, 20)],
    'tripbomb': ['fire_%02d' % i for i in range(4, 16)],
}
# flash colours per weapon (core, outer) -- Duke palette-ish
FLASH_COLOURS = {
    'freezer': ((235, 250, 255), (120, 190, 255)),
    'shrinker': ((230, 255, 200), (90, 220, 60)),
    'expander': ((255, 230, 180), (240, 90, 40)),
}
