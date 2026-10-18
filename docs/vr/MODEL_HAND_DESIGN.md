# Native tracked MD3 increment

This is an opt-in **idle pistol** vertical proof, not completed weapon/body
integration or model single-pass stereo. Private art remains in sibling
`duke-vr-assets`; no proprietary meshes/textures are committed here.

## Focused Astra design review

The separate focused review used explicit `gpt-6-astra` / `xhigh`; its own review
turn's effective settings were verified. It did not repeat the requested broad
implementation review. The brief is retained in ignored
`work/model-hand-review-brief.md`.

| Recommendation | Disposition |
| --- | --- |
| Insert before native masks; late depth testing overwrites nearer translucent glass | Adopted. Both model eyes emit after opaque rooms/once-only animation and before mask collection or retries. |
| Reuse native MD3 loading, materials and triangle emission | Adopted. An explicit sampled context branches before actor-owner lookup; no additional mesh loader, shader, actor or animation clock. |
| Keep shared animation/owner timing intact | Adopted. Context frame pair/interpolation are local; world callers retain `updateanimation`. First proof samples frame zero. |
| Use native eye space/projection and identity shader rotation | Adopted. Polymost owns preparation and rotation restoration. Build's unequal XY/Z scale is applied once. |
| Use constrained shot origin and stored direction together | Adopted. Canonical muzzle position maps to that origin; tracked right is orthogonalized around authoritative forward to retain roll. |
| Predict only a narrow vanilla weapon; preserve native side effects | Adopted. Conservative player/weapon/event eligibility; a frame receipt suppresses only the matching idle pistol tile. Native helpers and weapon branch still execute. |
| Reject unsupported materials before pixels, cancel after partial failure | Adopted. All surfaces/skins and affine transforms preflight; second-eye failure ends an empty XR frame. Receipt mismatch cancels presentation. |
| Build SPS on the qualified native emission | Deferred until its two-eye reference is established. Frames containing sequential-eye hand models are excluded from full-multiview counts. |
| Prove transparent composition and native gameplay alignment | Actual private software-XR multiplayer fixtures described below; remaining promotion cases remain explicit. |

The load-bearing correction was composition order. `renderDrawMasks` defers
translucent surfaces with depth writes disabled, so drawing an opaque model
after the masks cannot reconstruct the correct blended image. Insertion before
that phase removes the need for an unrelated UI-to-native-model state bridge.

## Runtime boundary

Enable `EDUKE32_XR_MODELS=1` with existing `EDUKE32_XR_UI=2`,
`EDUKE32_XR_WEAPON=1` and tracked hand-shot settings. The supplied private MD3
pistol must be mapped through native DEF to pickup tile `21`, with an opaque
base skin and static `tag_muzzle`/`tag_grip`. The explicit instance contract is
64 model units/metre, +X forward, +Y right, +Z up; it does not infer arbitrary
third-party model conventions from DEF scale.

Only a live, normal-size local Duke with a stable raised vanilla idle pistol,
supported native hitscan behavior, palette zero and valid negotiated tracking
qualifies. Relevant custom room-end/rest/weapon presentation events, cameras,
menus/help/map, another player view, recording, competing kick/fist/access/tip,
switching, firing and reload retain native ART. Missing/alpha/detail/glow
materials likewise retain ART. There is no second gameplay animation state.

The native adapter validates model/frame/skin/appearance and a finite invertible
affine matrix. It samples canonical decoded MD3 coordinates through a local
frame pair. Existing loader, skin cache, buffers and surface triangle emission
remain authoritative. Ordinary native model callers keep their owner state,
frame sampling, scale and material behavior.

The hand root is the already-constrained native gameplay shot origin. Static
muzzle-first placement proves aiming alignment; it does **not** finish grip
calibration. The authored grip is roughly 27 cm behind that muzzle. Headset
comfort, controller grip alignment and animated attachment behavior remain
unqualified. Native loading retains only the first tag set, so no animated-tag
support is implied.

## Actual bounded qualification

`tools/vr/smoke_hand_model.py` runs real native revision4 server/client gameplay
and Monado remote poses inside `software_xr_lab.py`. The lab denies hardware GPU
devices, uses matching llvmpipe/LVP, hidden private Xvfb drawables, core validation
and exact owned-process cleanup. No desktop focus/input or installed content
changes occur.

- Base: sixty world/HUD submissions; native idle ART coverage is empty while
  model color/depth changes occur in both eyes. Independent physical muzzle
  projection error is below `7e-7` NDC. Actual server hitscan root agrees exactly,
  and normalized physical direction differs by less than `1.2e-5` (native
  hitscan uses historical XY magnitude and sixteen Z units per XY).
- Near translucent native portal: all 8,106 left / 7,903 right visible model
  pixels are subsequently covered by glass, retaining exact model depth. This
  exercises the ordering problem identified by the reviewer.
- Missing skin and custom `DISPLAYWEAPON` handler: native ART remains visible,
  no model capture/emission and no model frames counted.
- Failure before the second model eye passes: the partially drawn serial is
  never submitted, and terminal XR cancellation clears the frame receipt.
  A separate 25-degree tracked-roll case independently qualifies the muzzle
  and all three five-centimetre basis offsets, below `3e-7` NDC error.
  Firing uses native server events/shot and returns to ART;
  this does not qualify a fully animated 3D pistol.

Native world-model fixture `check_stereo_oracle.py --model-root ...` includes
ART and no-skin controls to establish visible textured loading. Its model mask
phase uses the existing reference fallback. Nonzero stereo, exact color/depth
comparison and no writes during collection are distinct from model SPS.

Results, source/binary hashes and exact run directories are recorded in sibling
`evidence/hand-model-validation.json`. Early failed attempts remain in `work`;
their errors are not silently counted as passing evidence. Six hand cases pass
71 checks. Client core validation is clean throughout; the forced-shutdown case
retains Monado's separate known destroy-nonexistent-space teardown warning.

Still required before broad promotion: asymmetric-FOV hand cases,
wall/ceiling clipping, tracking loss/recovery and resolver clamping, mask retry
with a hand model, comprehensive native transitions/callback accounting,
simultaneous world/hand animation ownership, animated weapon families,
full-body presentation/IK and model/material single-pass stereo. Physical
headset/controller fit and performance remain separate acceptance work.
