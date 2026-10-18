# AA standard Duke RPG: native reference and calibrated asset

The actual AA 5.66 standard Duke RPG now has a passing native firing reference
and a privately authored, counter-addressable MD3 package. The opt-in held-model
adapter now extends the existing pistol path to this family. Native firing,
networking, model loading and renderer ordering remain authoritative. Current
qualification and outstanding acceptance work are recorded below.

## Native behavior established

`tools/vr/smoke_aa_rpg_native.py` loads the installed AA compatibility entry,
uses AA's real controller START selection, grants three ordinary RPG rounds in
a private observer CON, selects RPG through the owned window's native `5` key,
and fires with a simulated Monado trigger edge. It never sets the selected
weapon, advances weapon counters, or inserts a projectile itself.

The final software lab `work/software-xr-aa-rpg-reference-v2` passes all
**19 checks**. Its child result is
`aa-rpg-native-okc608hl/result.json`; the durable summary is sibling
`../evidence/aa-rpg-native-reference.json`.

- Actual standard Duke, slot 4, no upgrades/nuke; FireDelay 4, TotalTime 20,
  WorksLike 4, Shoots 2605, Flags/Clip/Reload/HoldDelay/ShotsPerBurst all zero.
- One trigger edge produces one native POSTWEAPONSHOOT event and one
  player-owned RPG with nonzero speed; ammunition changes 3→2. Native counters
  naturally progress through 1..19 and return to 0. An RPG-owned EXPLOSION2
  impact was also observed; damage and multiplayer are not tested here.
- All four composite firing cards at counters 4, 5, 6, 7 contain actual native
  artwork. The main agent inspected counter 6's flame/gun image. Distinct,
  nonconstant stereo gameplay is captured at submitted frame 120.
- The drawable stays unmapped without desktop focus. GPU devices are denied;
  llvmpipe/LVP render in a private Monado/Xvfb lab. Observed OpenXR validation
  is clean, game remains live until owned cleanup, and all lab children exit 0.

The first attempt `work/software-xr-aa-rpg-reference-v1` failed because an 80 ms
key tap never appeared in slow native input. The final runner holds the owned
key until native selection observes it, then always releases it. That failed
record remains; its cleanup passed and no game/driver crash was observed.
The main agent also fixed the initial runner's truncated fire timeline before
runtime qualification and requires exactly one ammo decrement/owned projectile.

## Minimal diagnostic change

`EDUKE32_XR_TEST_MODEL_WEAPON=4` selects RPG for the existing per-counter native
weapon-card capture. Omission preserves the original pistol diagnostic;
malformed/out-of-range values disable that capture selector. It does not change
native state, frame selection, clocks, or production model eligibility. The
existing bounded counter range 1..26 and once-per-counter capture remain.

XR+NETCODE builds successfully (`work/aa-rpg-reference-build.log`; existing
smmalloc warnings). Tested SHA256:
`4f7516bd683e666e500c46411dfa0e21a098880e21e27b1e623ccaeb17367cb2`.
The earlier fully qualified voxel binary is preserved as
`work/eduke32-xr-before-aa-rpg-reference`. No non-XR source path changed.

## Private art package

Astra created `../duke-vr-assets/aa-rpg-native`, retaining the original chunky
204-triangle geometry, 128×128 texture, UVs, normals and original muzzle/grip/support
tags. It adds measured left/right palm tags and 17 static named samples:
`rest`, `fire_01..03`, `fire_08..20`. These names expose native state; they do
not introduce a second animation clock or new mechanics. All 56 file checksums
were independently verified. Export/master validation passes (MD3 max 0.18812 mm;
actual GLB reimport zero measured positional error).

The real AA dispatch is installed `scripts/weapons_hud.CON:12400..12457`;
`draw_rpg` near 1184 is commented out. It draws body 10228 except composite
flame tiles 10229/10230 at counters 4..7. Those counters require **full native ART
fallback**, not a model body plus a misaligned leftover weapon card. Counter 20
is source-covered but was not observed in the actual native cycle. Native
screen-space recoil is documented; the new asset samples remain static.

Hand-fit previews use current `aa-v3-hands-grip` with idealized aligned aim/grip
orientations. Palm anchors lie on the actual exported grip surfaces; the
inherited 102.54 mm-wide grip is not proof of finger wrap, trigger reach or
hardware fit. Original AA arsenal remains complete offline: 68 physical designs
covering 69 dispatch entries, plus two basic floating hands and no AA bodies.
`../duke-vr-assets/CURRENT_REVISION.md` now correctly indexes the current sets.

## Incremental adapter and Astra design disposition

The adapter uses `XRWeaponFamily` / `XRWeaponPresentation` and the same native
MD3 emitter, before-MASK ordering, current-frame visual and receipt owner.
Standard Duke RPG maps through palette-zero `RPGSPRITE` (23); its sampler reads
persistent native fields and actor-sector floor palette. It admits only the
observed standard settings, no nuke/upgrades, supported actions and counters
0..3 / 8..20. All four baked flame counters remain complete native ART.

`EDUKE32_XR_WEAPON_MOUNT=1` enables canonical palm-to-muzzle calibration for the
qualified pistol and RPG families. The legacy `EDUKE32_XR_PISTOL_MOUNT=1` still
changes only pistol origins. Missing mesh frames/skin retains native ART while
valid mount metadata continues to own firing. Missing selected calibration
keeps shot input enabled-invalid and retains the existing release latch; it
must not silently fall back to a different firing origin. The shared mounted
origin also supplies selected-weapon quick kick, as in the pistol contract.

Fresh explicit Astra/xhigh design review completed this increment: thread
`01a14f3b-b926-71c1-8e25-96ea6a6c5159`, turn
`01a14f3b-b970-7a73-a346-eb936fb8235c`; actual thread and current-turn settings
independently verified. Brief: `work/aa-rpg-design-brief.md`.

| Recommendation | Disposition |
| --- | --- |
| Extend the existing owner/renderer; do not duplicate AA dispatch, animation or networking | Adopted: one small family enum, model-tile mapping, native samplers. |
| Stable calibration must survive the native shot's ART fallback | Adopted; counter-independent family. Actual counter-4 origin proof is required below. |
| Missing frame/skin differs from missing calibration | Adopted: preflight fallback versus enabled-invalid input. |
| RPG palette comes from player sprite sector; normalize 10..25 to 0 | Adopted, with bounds check. No pistol shade-history policy on RPG. |
| Classify RPG tile range OR unique ID 24 before validating exact body and family | Adopted; wrong/duplicate claimed draws invalidate the current receipt. |
| Preserve cancellation and avoid a late post-HUD resample | Adopted; existing ownership/cancellation path retained. |
| Prove actual spawn, supported frame pixels, native flash, family switches and failure recovery | Required acceptance; only completed evidence may be claimed below. |

A subsequent fresh Astra/xhigh **implementation** review spawn hit the session
agent-thread limit. No substitute reviewer was used; that focused code review
remains pending. The earlier checkpoint's reviews do not cover this code.

## Current runtime qualification

Durable evidence: sibling `../evidence/aa-rpg-model-validation.json`. All five
final suites use the same XR binary, GPU-denied llvmpipe/LVP, private Monado/Xvfb,
unmapped drawables without desktop focus, clean observed OpenXR validation and
successful owned-process cleanup. No installed AA files were changed.

| Final actual suite | Checks | Evidence |
| --- | ---: | --- |
| Mounted right RPG | 40 | Native counter 4 commits one actual RPG at independently reconstructed palm/muzzle; 0.612886 m from old aim origin. All supported observed frames render with native/SPS exact RGB/raw depth and zero collection writes. |
| Mounted left, missing frame 8 | 45 | Left palm independently reconstructed; frame 8 falls back to actual ART, later frames recover, same mounted firing origin retained. |
| Legacy pistol option, RPG selected | 40 | Actual shot remains at old aim pose; it does not adopt the RPG mount. Supported model frames and native flame cards still pass. |
| Existing AA pistol | 45 | Native trigger, ammo, firing ART/reload MD3 sequence, calibrated origin and stereo regression. |
| Existing stock pistol, native server/client | 34 | Actual multiplayer ammo/reload, native server ray, mounted world crosshair pixels/depth and model stereo remain functional. |

The origin check joins the last accepted raw input sample, independent MD3 tag
math, read-only native PREWEAPONSHOOT body anchor, authoritative collision-resolved
origin, inserted native projectile and AA EGS observation. Both palms have zero
rounded offset error in the final runs; all RPG shots here are **unclamped**.
At counter 4, native ammo decreases once, POSTWEAPONSHOOT occurs once and one
player-owned tile-2605 projectile is inserted. Actual model counters are 1..3
and 8..19, with nonempty whole-native ART cards and no mesh receipts at 4..7.
Counter 20 remains source/asset-covered only.

Real-log negative controls reject absent input, a moved inserted projectile,
the wrong hand, the old aim-origin expectation for a mounted shot and absent EGS
observations. These parser controls are separate from runtime behavior tests.

XR+NETCODE SHA256:
`293058de2077293344187cfd23aac92daee245806f66f9472cf70ada443fa1d6`.
Non-XR NETCODE also builds; its native server was used in the stock regression:
`a0b71546a7dc417d4d50c939426cf465f2947aaf2f159103c5f3d3d7be8dfea7`.
Logs: `work/aa-rpg-model-build-v3.log`, `work/aa-rpg-flat-build.log` (existing
smmalloc warnings). Test diagnostic `EDUKE32_XR_TEST_WEAPON_MOUNT` observes raw
accepted input for both mounted and old aim modes; it does not change selection.

The first RPG model run failed a test list-versus-tuple comparison of body
receipts. Its separate reanalysis confirms all 15 real receipts; the original
failed result remains unchanged. The first AA pistol regression failed in private
Xvfb setup with an owned `/proc` fd permission error before game/Monado launch;
a fresh-directory retry passed. All failed attempts cleaned up successfully.

## Remaining acceptance

The fresh implementation review remains pending. RPG-specific wall-clamp,
missing-skin, calibration-loss/recovery and wrong/duplicate-draw cancellation
controls are not yet qualified. Neither is switching between both mapped pistol
and RPG models in one continuous session. Existing pistol proofs do not replace
these RPG checks. No RPG multiplayer/damage qualification follows from the stock
pistol regression. Controller-specific fitting, moving-trigger alignment, full
3D muzzle effects and complete AA arsenal runtime bindings remain unfinished.

Preserve the prior [AA renderer ordering decision](AA_MODEL_DESIGN.md) and
[shared mount authority](PISTOL_MOUNT.md). This experimental opt-in increment
adds no duplicate AA state machine, animation clock, protocol or late opaque HUD
renderer.
