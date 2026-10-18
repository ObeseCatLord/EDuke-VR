# Private chunky model set

## AA weapons and floating hands (2026-10-18)

The Astra asset subagent completed sibling `duke-vr-assets/aa-v1`: 69 AA
weapon/equipment dispatch entries representing 68 physical designs, plus both
floating hands. Shrinker/Expander intentionally share the native AA chassis.
There are 71 editable Blender masters, MD3/PNG sets and embedded GLBs, with
source comparisons and all-side CPU previews. No new AA character bodies were
requested or created.

Entries use 36–620 triangles; hands use 208 each. Weapons have 128² atlases and
hands 64². Authored atlases have at most 64 colors; unchanged Ripper, tripmine
and freezer donor pixels retain 295/293/295 colors. Newly authored closed
components retain deliberate overlaps, while seven reused models disclose
original detail boundaries. Hidden surfaces and metre scale are inferred.

Main integration verified all 1,614 manifest hashes (manifest SHA-256
`3f7471e8bbff04616d95060e9aa73af04d2afb5144abdbf931ea20faf7c1ccbc`), all 71
indexed MD3s and 467 frame names, triangle counts, and the canonical static tag
basis (maximum float error 4.38e-8). Visual inspection prompted correction of
repeated generic pistol/energy shapes before final acceptance. These are chunky
sprite-guided interpretations, not recovered source meshes.

Use private `aa-v1/metadata/asset_index.json` and `aa-v1/NATIVE_BINDING.md` for
paths, character/upgrade dispatch, coordinate conversions, tags and action
ownership. Four literal native-counter mappings are evidenced; other cosmetic
samples remain unbound. Static muzzle tags can be central emitter/contact
references and do not prove gameplay origins. Runtime selection, hand fitting,
remaining timing, effects/scopes and reload-hand choreography remain integration
work. The files stay outside Git and the installed game remains unchanged.

## Stock native pistol action package

Sibling `duke-vr-assets/v4-pistol-native` supplies the stock pistol's 27 native
counter frames: rest, fire 1–4 and reload 5–26. Its 196 triangles include two
necessary magazine closure triangles; its 128² PNG and rest calibration remain
unchanged. The engine resolves frame names and uses the existing native MD3
path. See [PISTOL_ANIMATION.md](PISTOL_ANIMATION.md) for actual runtime proof and
scope; this does not promote AA weapons automatically.

## Earlier stock package history

The user's requested full art revision was completed by the Astra asset agent
in sibling `outputs/duke-vr-assets/v2`. Original Duke3D/World Tour ART sprites
guide silhouettes, proportions and colors. Editable sources derive from the
user's installed **DNF2001 October 26 build**, with incompatible weapon shapes
replaced by documented authored approximations. These private files remain
outside this repository.

The fourteen entries comprise Duke plus pistol, shotgun, chaingun, RPG,
pipebomb, detonator, shrinker, expander, Devastator, tripmine, freezer, kick and
World Tour flamethrower. Duke has 678 triangles, 43 bones, 24 retained clips and a
256² diffuse atlas. Equipment uses 44–236 triangles and 128² atlases, flat normals
and nearest filtering. Every entry has a packed `.blend`, embedded GLB, MD3v15
and PNG export. The complete gallery and individual original-sprite comparisons
are under `v2/previews`.

All 28 exported binaries passed structural checks and 19 rest/animated geometry
roundtrips passed unchanged tolerances. Maximum errors were 0.0017 mm GLB and
0.2030 mm MD3. The parent independently checked all 281 manifest file hashes and
inspected the gallery and comparison sheet. All 98 recorded v1 files remain
unchanged. These checks establish the delivered art/export set, not native
gameplay or headset behavior.

## Runtime contract and remaining work

### Completed v3 action package

The latest private art deliverable is sibling `duke-vr-assets/v3`. The Astra
asset agent completed nine authored cosmetic actions across the eight formerly
rest-only reconstructions, including independent Devastator left/right clips.
All fourteen textures and six inherited model/master sets remain byte-identical;
all eight updated MD3s retain exact frame-zero geometry, normals, topology, UVs
and tags. There are 55 named action/pose clips in the full package.

The main agent independently verified all 430 final manifest hashes and
inspected the three new action/sprite comparison sheets. Offline evidence has
142 GLB position comparisons and 115 integer-frame MD3 comparisons; 27
fractional samples are GLB-only, so MD3 interpolation is not qualified. Maximum
measured errors are 0 mm GLB and 0.2022 mm MD3. Structural checks cover all 28
exported models. Detailed production/ownership evidence is the private
`v3/COMPLETION_REPORT.md`; previews include `action_overview.gif` and
`action_comparison_1.png` through `_3.png`.

All new clips follow explicit native counter-to-frame metadata; 30 fps is the
interchange preview cadence. Existing native weapon counters, effects, ammo,
projectiles and damage retain gameplay ownership. Pipebomb remains a rigid pose
whose throw/release motion belongs to the controller/native game. The source
install is DNF2001 October 26; sprite-guided reconstructions and authored action
approximations are documented rather than described as recovered original 3D.

Use v3 for further integration, preserving v1/v2. Pistol is byte-identical to
the qualified v2 model; current native tracked-idle proof is recorded in
[MODEL_HAND_DESIGN.md](MODEL_HAND_DESIGN.md). The following rest-only counts
describe v2 history; v3 supersedes them. Engine animation/body/SPS acceptance
remains separate from the completed art scope.

GLB uses metres, +Y up, +Z forward and retains Duke's skeleton. MD3 uses 64 model
units/metre, +Z up, +X forward and bakes animation into vertex frames. Each model
provides grip/muzzle/support tags; Duke additionally provides body attachments.
Devastator has separate barrel tags. Per-model metadata records exact frame
ranges and source clips. Tags are initial fitting references, not yet qualified
controller/muzzle transforms.

Eight reconstructions are rest-only: chaingun, RPG, shrinker, expander, Devastator,
tripmine, freezer, flamethrower. Retained clips: Duke 24, pistol 12, shotgun 3,
detonator 4, pipebomb 1, kick 2. Runtime recoil/firing/attachment policy must follow
native weapon counters; do not create a second weapon simulation around these
clips. Further art modifications remain delegated to the asset agent.

Native `mdsprite.cpp` already loads/renders MD3 and DEF already associates model
frames/skins with tiles. The delivered pickup/player DEFs are untested drafts;
first qualify loading, scale, orientation, native animation and per-eye depth
through those existing boundaries. Current unsupported model draws fall back
to the two-pass reference, so ART-only multiview evidence does not prove model
SPS. Preserve that working reference while extending supported draw families.

The engine has no GLB skeletal loader. Baked MD3 frames cannot establish
tracked-body skeletal IK. Full-body integration therefore still needs an
explicit incremental design, controller/head fit, occlusion/visibility and
multiplayer presentation qualification. No full-body tracking, animated muzzle
alignment, native model scale or model stereo acceptance is claimed yet.
