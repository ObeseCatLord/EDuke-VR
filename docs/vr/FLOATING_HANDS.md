# Tracked floating hands

Basic left and right hands now use actual OpenXR grip poses through the native
opaque MD3 renderer. They work independently of the selected weapon and its
model eligibility, including AA 5.66. Each hand is opt-in through a native DEF
tile binding. They do not alter gameplay, multiplayer packets, native CON,
weapon timing, or the projected aiming crosshair.

This does **not** complete weapon attachment. Experimental pistol palm/muzzle
calibration is described in [PISTOL_MOUNT.md](PISTOL_MOUNT.md); it measures a
remaining temporal gap between current hands and the sampled gun. Native weapon ART
can include additional hands, especially AA reload hand 2532; it remains visible
until its own replacement is qualified. These are independent floating hands,
not a full-body or hand-tracking/IK implementation.

## Native binding and asset contract

Use the private Astra-authored `aa-v3-hands-grip` package. Each hand has 208
triangles, a 64×64 opaque skin, four named frames, and a static `tag_palm`.
The packed Blender masters, MD3 exports, authored calibration, reproducible
scripts and preservation reports are in that package. The original AA weapon
package remains `aa-v1` (68 designs covering 69 entries); no extra character bodies
were created.

Map the left/right MD3 and skin through ordinary DEF `model`, `skin`, and `frame`
blocks to two unused tiles chosen for the content being loaded. Then set:

```
EDUKE32_XR_HAND_LEFT_TILE=<left native DEF tile>
EDUKE32_XR_HAND_RIGHT_TILE=<right native DEF tile>
```

Keep the existing XR world/overlay setup (`EDUKE32_XR=1`,
`EDUKE32_XR_UI=2`, native Polymost models enabled). `EDUKE32_XR_SINGLE_PASS=1`
requests the existing stereo collector. The hands do not require
`EDUKE32_XR_MODELS`, weapon replacement, hand-shot negotiation, or a valid aim
pose. Omitting one tile gives one hand. Missing/invalid/out-of-range bindings,
missing model/frame/tag, or unsupported native materials omit only that hand
before rendering. No global tile numbers are reserved by this feature.

For example, the private runners use tiles 30010/30011 in their disposable
fixtures. Those are test bindings, not a guarantee that those tiles are unused
in arbitrary mods. Native loader/cache ownership and DEF material selection
remain unchanged.

Canonical MD3 coordinates are 64 units/metre, +X fingers-forward, +Y right, +Z
dorsal. `tag_palm` is approximately (5.12,0,-0.96). The authored model-to-grip
rotations are proper rotations, with columns:

| Hand | Model +X | Model +Y | Model +Z |
|---|---|---|---|
| Left | grip (0,-1,0) | grip (0,0,1) | grip (-1,0,0) |
| Right | grip (0,-1,0) | grip (0,0,-1) | grip (1,0,0) |

Core controller grip is centered within the controller; it is not guaranteed
to be the physical palm surface. Mapping the authored palm tag to it is an
approximate controller fit. The newer `grip_surface` action is not requested.
See the [OpenXR standard pose definitions](https://registry.khronos.org/OpenXR/specs/1.1/html/xrspec.html)
and the private package's `CALIBRATION.md`.

The frames are selected directly from current active buttons, without another
animation clock. Trigger press selects `grip` (curled index); otherwise squeeze
selects `trigger` (extended ready index); otherwise `rest`. The names alone are
misleading, so this mapping follows the authored geometry. It is a button-driven
pose approximation, not tracked finger articulation.

## Rendering and ownership

Preparation uses the same frozen interpolated body camera as the two eyes,
current focused input and runtime generation, shared tracking origin and
recenter rotation. It requires a valid head and current grip for that hand,
normal local live first-person gameplay, and native weapon visibility. Menus,
help/map views, recording, remote cameras, shoulder view and death hide hands.
Weapon switching, firing and reload do not introduce separate hand policies.

World roots are finite/integer-bounded, sector-resolved, and visible from the
body camera. Native depth and later translucent masks provide occlusion. This
is not mesh-volume collision: fingers can penetrate a nearby surface, and a
root across a solid boundary is omitted rather than clamped.

A fixed, frozen list of at most three instances contains the qualified weapon
and either hand. One native per-eye loop, before masks, feeds one model stereo
collection/replay. Every explicit draw has a stable instance ID and its own
complete ordered surface set. The collector verifies instance/model/surface
identity and order across eyes, including two instances sharing one native
model object. Aggregate capacities and material checks remain unchanged.

Collection rejection before replay uses the same frozen native batch. Failure
after partial native emission or submitted replay cancels the acquired XR
frame. Only the existing accepted weapon model acquires the existing native
weapon receipt. Hands never suppress or claim ownership of HUD ART.

## Review and qualification

The design review and bounded code review both used explicit, independently
verified Astra/xhigh. Their useful corrections and dispositions:

| Recommendation | Disposition |
|---|---|
| Existing collector is singleton; add explicit instance boundaries and identity | Adopted, retaining the existing emitter/collector/replay. |
| Use the frozen visual body, not simulation shot state | Adopted. No new gameplay pose or protocol. |
| Keep independent additive hands; avoid another AA unarmed policy | Adopted. Weapon fit/duplicate native ART remain explicit limitations. |
| Bind authored finger geometry rather than frame names | Adopted. Press curls the index. |
| Core grip is not a hardware-independent palm-surface pose | Adopted in code comments, metadata and this contract. |
| Same-file loads do not prove one native model object instanced twice | Fixed. The corrected fixture maps both hands to one tile and asserts equal native model IDs. |
| Native image equality alone cannot establish successful SPS for every state | Fixed. Every captured nonempty state now requires serial-associated paired/shared replay counts. |

`smoke_hand_model.py --floating-hands /path/to/calibrated/aa_assets --model-mode sps`
adds both hands to the existing real native multiplayer pistol fixture.
`smoke_aa_hand_model.py` accepts the same option with its ordinary SPS model
case, preserving native Duke/START and actual firing. Both use
`floating_hands_check.py` for current-button poses and independent tracking
loss/recovery. Expected projections use raw OpenXR grip relative to actual
view poses/FOV, independently of emitted model/world bases. Separate per-instance
native captures require both hands to contribute pixels in both eyes.

Final accepted run details and hashes are recorded in sibling
`evidence/floating-hands-validation.json`. All runtime tests use the existing
private GPU-denied Xvfb/Monado lab with llvmpipe/LVP and owned-process cleanup.
No desktop input, hardware GPU, installed game, live Blender or runtime defaults
are changed. Software proof does not establish physical controller fitting or
headset performance.

Still unqualified: complete menu/map/death/camera/reference-space-generation
transitions for this new visual family; moving/turning/interpolated-body stress;
solid-wall mesh penetration; invalid asset/material matrix; arbitrary native
model surface counts with multiple instances; full AA character/weapon/body
attachment and all arsenal effects. Existing world SPS fallbacks remain
independent of successful explicit-model SPS.
