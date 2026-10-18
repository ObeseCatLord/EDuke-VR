# AA model integration: native world pass and actual-draw validation

Design checkpoint, 2026-10-18. Asset production is complete; runtime binding is
not. Private `../duke-vr-assets/aa-v1` contains 69 handheld dispatch entries
(68 physical designs) and two floating hands, without additional character
bodies. Models have 36–620 triangles; each hand has 208. Weapons use 128×128
textures and hands 64×64. See that package's `NATIVE_BINDING.md` for the exact
frame/tag contract and animation limitations. Proprietary assets stay outside
this repository; all further modeling remains Astra-owned.

## Decision

Preserve the existing explicit MD3 world emitter, controller transform, native
loader/skin cache, multiview collector, and two-pass fallback. Begin with an
explicitly enabled, narrowly qualified AA standard-pistol presentation sample.
Validate that sample against the actual native body draw in the same owned
weapon segment. Unsupported modes retain the native ART presentation before any
model is emitted. This is a vertical proof, not a completed arsenal selector.

Do not add a late opaque model draw from `rotatesprite`. Native translucent
masks blend after the current world-held model pass with depth writes disabled
(`engine.cpp`, `DrawMaskedSprites`, `glDepthMask(GL_FALSE)`). A later opaque
weapon passes the underlying opaque depth test and overwrites a foreground
translucent surface. Replaying masks over the completed eye would blend them
twice. Fixing that requires a materially different rendering schedule, not a
small HUD-to-world adapter.

The current stock-pistol qualifier must remain intact. AA owns
`EVENT_DISPLAYWEAPON` and `EVENT_DRAWWEAPON`, uses different unique IDs, and
draws through CON `rotatesprite`, bypassing the stock C++ suppression hook.
The narrow AA qualifier therefore needs its own selection rules and a consumer
at the common native draw boundary, while reusing the existing frame receipt.

## Focused senior review and disposition

Reviewer: explicit `gpt-6-astra`, `xhigh`; independently verified exact-turn
metadata. Thread `01a14e32-331f-7082-8bac-36d30e2920d4`, turn
`01a14e32-336a-7f02-b809-05c1066831b2`. Read-only, no runtime tests. Main
spot-checked the mask depth-write transition, HUD-variable aliases, current
suppression location and AA shade-fading source. This was a focused architecture
review, not another broad VR code review.

| Recommendation | Disposition |
|---|---|
| Reject late opaque HUD model emission | Adopted: demonstrated translucent-compositing error; no renderer rescheduling in this slice. |
| Keep the existing world MD3/SPS boundary | Adopted: reuse native transforms, emission, preflight, fallback and mirror. |
| Avoid reading HUD aliases before display | Adopted: `currentweapon`, `weaponcount`, `gs` alias `hudweap`, initialized after the world pass. Read current player fields and verified persistent AA variables. |
| Account for AA shade fading | Adopted: qualify a proven stable subset first, validate actual shade; never call script draw states early to advance the fade. |
| Validate at common native draw boundary | Adopted: owned segment, exact tile/unique-ID/palette/shade/flags and multiplicity; retain auxiliary effects. |
| No new tracked DEF flag for the first proof | Adopted: ordinary frame/skin loading suffices; tile alone cannot identify repeated reload phases or dual instances. |
| Treat mismatch cancellation as exceptional | Adopted: ordinary unsupported modes/switches must choose ART before emission, without shutting down XR. |
| Reopen if sampler duplicates substantial AA flow | Adopted: bounded eligibility is allowed; a second arsenal/HUD state machine is not. |

## Proof required before wider binding

Actual AA Duke/START, idle and shot; exactly one body replacement, native
callbacks/effects/ammo/reload preserved. Distinct perspective eyes with opaque
and translucent occluders in front of and behind the model, plus native
two-pass versus multiview image/depth comparisons. Missing model/frame/skin,
invalid pose, unsupported modes and ordinary switching retain ART. Injected
failure after an eye write cancels the frame. Check desktop weapon content,
crosshair, menus, tint and subsequent frames.

The delivered generic `response_*` poses are not an authorized independent
animation clock. The first static geometry proof must not be described as full
AA reload choreography. Four other asset families have documented literal
native-counter mappings; the remaining mappings and hand fitting still require
implementation and runtime evidence.

## Verified inputs for the first sampler (not implemented)

Terra's follow-up was source investigation only, not a review. The standard
single Duke pistol uses native `kickback_pic==0`, slot 1/WorksLike pistol,
`pchar==0`, `LASERMODE==0`, and clear Duke pistol upgrade bits 1, 4 and 8.
`dukeupgrades` is a 12-element gamearray; its array ID must be resolved by label
and bounds checked rather than assumed. `Gv_GetVarByLabel` reads per-player
persistent variables; `Gv_GetArrayValue` reads the resolved array element.

`old_weapon_setup` derives the base shade from `gs`, which native display will
set to `min(player-sprite shade,24)`, and reads the player's `hudpal`. AA's
per-player `hud_shadef`/`hud_palf` retain fade history. Even at a stable shade,
FIRSTGUN adds 2 immediately before drawing. Stable body shade is therefore the
native base plus 2, not the unadjusted native sprite shade. Do not execute the
draw state early to obtain this value.

The qualifier must first exclude native ownership/camera/death/weapon-lowering
conditions and AA's suppressed HUD, selector, brutal attack, camera, bike,
turret, slim-push and juicer presentations. The last two branches and callback
stability still need bounded qualification. Reject ordinary unsupported states
before model emission. Do not generalize these initial pistol conditions into
an engine-owned copy of AA's complete arsenal dispatcher.
