# Alien Armageddon 5.66 integration

The installed AA content is an additional required target. It remains outside
this repository; tests read the installation without changing its scripts,
assets, configuration, cache, or saves. The test owns a separate working directory.

The explicit [AA 5.66 compatibility entry](AA_COMPAT_ENTRY.md) now supplies the
per-player button-history correction through native `-x`/`-j`. Use that entry
for the qualified selection and tracked-pistol paths; the original launch below
is the unwrapped reference. Full AA campaign/multiplayer support remains open.

## Native entry and presentation

AA supplies `AA.grp`, `alien_armageddon.grpinfo`, `scripts/AAGAME.CON`, and
`duke3d.def`. Its classic episode selector is level zero; Hollywood Holocaust
is level one, selected by the human-facing `-v1 -l2` arguments. A direct launch
uses `-j <AA-root> -g <AA-root>/AA.grp -x scripts/AAGAME.CON -h duke3d.def`.

Keep AA's native custom display, weapon, projectile, camera, character, upgrade,
and multiplayer logic. Its display handlers intentionally fail the stock
tracked-pistol model qualification. A stock-pistol model must not suppress AA
weapon ART merely because the selected native slot is the pistol slot.

Two native compatibility boundaries were encountered:

* A truncated texture-cache index invokes `texcache_invalidate`, which rebuilds
  the draw VBO through `polymost_glreset`. The reset must restore native vertex
  pointers/program state after replacing that VBO, just as initial GL setup
  already does. Array pointers retain the buffer object bound when set; creating
  and unbinding a replacement buffer does not update them. The observed failure
  was a native load-screen draw before OpenXR initialization, reproduced inside
  the CPU software renderer. It is not evidence of a hardware GPU failure.
* AA invokes CON `startscreen` during native level entry. `Screen_Play` already
  owns event polling, pacing, `EVENT_SCREEN`, input clearing, and the final swap.
  It now uses the existing XR frame/UI ownership around that same native draw.
  A narrow screen entry permits a flat presentation during `MODE_GAME`; ordinary
  menu/HUD gates remain unchanged. Input clearing retains the existing held-button
  release gate. There is no second screen loop, renderer, runtime, or script clock.

## Current runtime evidence

`tools/vr/smoke_alien_armageddon.py` runs the actual installed CON/DEF/ART in
`tools/vr/software_xr_lab.py`: private unmapped Xvfb, one owned Monado service,
llvmpipe GL and matching LVP Vulkan, hardware GPU devices denied.

The first completed selected-map run recovered a deliberately reused incomplete
owned cache, passed the former load-screen crash, dismissed the native opening
screens with window-targeted Return events, and submitted 60 world/HUD frames
with distinct nonconstant eye layers and clean observed OpenXR core validation.
Inspection shows the actual Hollywood world behind AA's character-selection
panel. This establishes selected-map/UI presentation, **not completed character
selection, combat, or multiplayer compatibility**.

The controller follow-up used actual OpenXR left Select (native Open), right
stick native cursor deltas, observed press/release edges, and AA's literal
Duke/START hit boxes. The native state changed to Duke-only `startmode=1`,
`charsel=1`, `pchar=0`, volume 0/level 1. A fresh periodic HUD/world capture at
submission 120 was inspected: the character panel is gone and the native AA
pistol/status display is visible in Hollywood. Both a clean-cache control and the deliberately incomplete-cache recovery
completed this controller path. Opening-screen and gameplay eye images are nonconstant/distinct, validation is clean, and the private window is
unmapped with no desktop focus. The original failed right-Fire/timed-pulse and
pixel-center steering attempts remain preserved; the passing route uses AA's
native Open interaction and full documented activation rectangles.

That scene used 60 native reference room/mask passes and zero accepted complete
multiview world frames. AA's unsupported opaque state and model/voxel mask
families retain the existing two-pass fallback. Do not describe this result as
full AA single-pass coverage.

## Native Duke pistol combat and projected crosshair

The next increment qualifies actual AA Duke pistol fire/ammo/counters, tracked
hand origin, native event-drawn crosshair in world space, and held-trigger loss
recovery. The corresponding native multiplayer weapon fixture also verifies
authoritative impact/damage. Matching NETVERSION6 peers are required. See
[AA_COMBAT.md](AA_COMBAT.md) for the two demonstrated compatibility boundaries,
focused Astra review, native-coordinate conventions and complete test scope.
Actual AA campaign multiplayer and the remaining arsenal are still unqualified.

## Native multiplayer startup

Actual AA early and late native joins now reach the real Hollywood character
selector and remote-player input on both simulations. Startup admission and
client dispatch wait for existing native initialization boundaries, and generic
CON game events exclude the native reserve-sprite pool. Read
[AA_MULTIPLAYER.md](AA_MULTIPLAYER.md) for the demonstrated failures, focused
Astra disposition and tests. Both peers still have default unselected AA state;
this does not establish cross-peer character choice or campaign combat.

## Assets and remaining acceptance

The Astra asset subagent completed 69 AA handheld dispatch entries (68 physical
designs, with shared Shrinker/Expander chassis) and both floating hands in the
private sibling `duke-vr-assets/aa-v1`. Main verified all 1,614 manifest files
and all 71 indexed MD3/frame-name/tag contracts; see [MODEL_ASSETS.md](MODEL_ASSETS.md).
New character body models are not required. Geometry/export validation and visual source matching
are separate acceptance gates; family counts alone do not establish completion.
Bindings must follow actual AA character/upgrade dispatch and the native
`weaponcount`, `LASERFIRE`, `saberpos`, `spinframe`, and other action channels.
Unbound semantic clips must not acquire invented engine animation clocks.

Still required: remaining controller-operated menus and AA weapon-family
combat/aim/crosshair checks, custom weapon origins and animation bindings,
scripted cameras/bikes/cutscenes, selected-character native AA multiplayer
combat/late join/map transitions, broader single-pass material/model/voxel coverage, and physical
headset testing. Native multiplayer is reused; old-peer compatibility is not a
requirement.
