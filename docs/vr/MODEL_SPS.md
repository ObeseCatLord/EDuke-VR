# Native opaque MD3 single-pass transport

Current extension (2026-10-18): the qualified stock pistol also uses native
firing/reload counters, with exact stereo model-oracle tests and matching
NETVERSION5 peers. See [PISTOL_ANIMATION.md](PISTOL_ANIMATION.md); the idle-only
proof below records the earlier bounded checkpoint. AA keeps its custom weapon
presentation until its separate bindings are qualified.

The first tracked idle-pistol model now uses the same bounded multiview packet
transport as indexed ART. This is an incremental native renderer extension;
full weapon/body integration and complete model/material SPS coverage remain
open. Ordinary native world MD3s still use their existing mask fallback until
animation ownership is separately qualified.

## Focused senior design disposition

Review: explicit default **gpt-6-astra / xhigh**. The main independently verified
those effective settings from this exact review turn's metadata. The brief is
retained in ignored `work/model-sps-review-brief.md`. This focused decision did
not repeat the completed broad implementation audit.

| Recommendation | Disposition |
| --- | --- |
| Preserve native rotation, MV, MVP, fog coordinate and raw source-Z arithmetic | Adopted. Existing XR vertex accepts native MV per eye; MVP is captured through GL matrix multiplication and the original projection/mode restored. Native fragment shader remains unchanged. |
| Avoid projection-stack overflow policy | Adopted. Save/load the actual projection around the temporary product; no stack allocation. |
| Keep collection ownership after rejection | Adopted. A native MD3 surface hook intercepts before both immediate and indexed submission, continuing cleanup without framebuffer writes even after rejection. |
| Reject missing skins, empty/incomplete or mismatched surfaces | Adopted. Required skins reject; expected ordered surface counts and matching per-eye material traversal qualify before replay. Triangle indices/finite geometry/capacities are validated. |
| Capture native material state and preserve reversed fog ranges | Adopted. Native shade/tint/sampler, texture matrix, fog start/end/color, cull mode/front-face/enable are captured. A finite nonzero fog range may be negative. |
| Preserve qualified depth/viewport/clamp state | Adapted from observed native setup: `polymost_glinit` enables depth clamping when supported. Collection requires that same native setting, full viewport/scissor and ordinary depth range; replay does not normalize them to generic defaults. |
| Reuse transport, shader and native material policy | Adopted. MODELS adds an explicit opaque LEQUAL branch, not another renderer/loader/shader or weapon animation clock. ART restrictions remain. |
| Establish paired parity before sharing geometry | Adopted. Paired model replay first matched exact native color/depth. Sharing compares ordered XYZ/UV bits and changes only replay staging ownership to -1. Nonidentical streams retain the existing paired payload path. |
| Restore additional state; test later native draws | Adopted. Replay restores fog/cull/texture matrix plus existing program/arrays/samplers/blend/depth/color state. Native mask/HUD execution remains after the pre-mask model. |
| Credit only actually submitted model frames | Adopted. Existing frame receipts carry model presence/coverage; only submitted frames count as model multiview/full multiview. |

## Boundaries

`mdsprite.cpp` still owns loading, surface skins/samplers, local frame sampling,
interpolated CPU vertices, tint and native cleanup. Only its final explicit MD3
surface emission is diverted during MODELS collection. It retains descending
triangle order and each triangle's index order. The hook declaration lives next
to the existing MD3 context API; no native type or include-cycle workaround is
needed. Unsupported alpha/detail/glow/editor/polygon/auxiliary array states
reject before mesh pixels, retaining the two-eye reference.

Packets preserve source coordinates/UV, native modelview, MVP and rotation.
The shader keeps the native operations: rotate source, transform eye position
for fog, transform clip position by MVP, retain source Z for native material
varyings. Texture/fog/culling state participates in material compatibility;
eye transforms do not. Shared geometry is a replay-only optimization after an
ordered bit comparison, with no mesh registry or additional cache.

Both eyes collect the same frozen hand sample before native masks. Rejection
before any replay submission discards the collection and draws the original
native reference once per eye without repeating game simulation/CON animation.
Failure after any replay draw cancels the XR frame. Existing weapon suppression
receipts are issued only after complete reference emission or successful replay.

## Qualification method

The private GPU-denied software lab runs real native multiplayer server/client
sessions, real Monado remote poses, hidden Xvfb windows, matching llvmpipe/LVP and
core validation. No hardware GPU or desktop input is used.

The first separate-session comparison matched color/depth exactly but exposed
last-bit controller basis variation between runs. This was input variation,
not a pixel/depth mismatch. The authoritative oracle now copies the actual
opaque eye layers into an owned RGBA8/D24 array target within the same frame,
renders the unchanged native context there, and compares against replay on the
untouched XR target. The same frozen sample and byte-identical model/projection
matrices are required; no native reference arithmetic or pixel/depth tolerance
is changed. The extra reference target exists only for explicit test captures.
No gameplay callbacks or animation clocks are repeated.

`smoke_hand_model.py --model-mode sps` requires actual submitted model multiview,
shared geometry, identical same-frame native inputs, exact native model color
and depth, zero collection writes, physical muzzle/axes/ray agreement and native
world/HUD receipts. `check_hand_model_stereo.py` adds sequential native controls
and exact pre-model/post-model/post-mask image/depth comparisons. Individual
runs retain binary/artifact hashes and input-path observations.

The model-owned two-surface fixture splits the actual private pistol's 194
triangles into two 97-triangle surfaces, preserving all 266 frames, tags, UVs
and complete native emission order. It provides rejection-after-first-surface
and missing-required-skin cases without changing completed v1/v2/v3 assets.

See sibling `evidence/model-sps-validation.json` for final results and precise
qualification limits. The ordinary model MASKS guard, other material families,
animated weapon presentation, full-body/IK, headset fit and hardware performance
remain outstanding; this increment does not establish the full VR port.

## Observed results — 2026-10-17

All fourteen final private labs passed with GPU devices denied, clean observed
core validation and owned child/Monado/Xvfb cleanup. Native and XR builds link
successfully; existing smmalloc compiler diagnostics remain.

| Cases | Observed result |
| --- | --- |
| Base, roll, actual asymmetric runtime FOV, sector fog, nearer translucent wall | Exact native model color/depth and post-mask world color/depth in both eyes; byte-identical same-frame native transforms and zero collection writes. Actual native MP server shot root/ray matches the physical aiming oracle. |
| Native immediate and vertex-array emission | Both intercepted before mesh writes; shared replay matches the native reference exactly. |
| Two-surface pistol | Two paired/shared draws, 582 shared vertices total, preserving all 194 triangles and native order; exact reference output. Ordinary one-surface case uses one shared draw and 582 vertices. |
| Right-eye rejection, rejection after surface zero, last required skin unavailable, error before replay | Exactly one native model retry in the captured frame, no collection writes, exact final color/depth. Failed collection does not issue a premature receipt. |
| Replay failure after first draw | Terminal XR cancellation; partially drawn serial never submitted and no completed model receipt. |
| Native masks reject after an accepted model | Mask-only native retry preserves exact model and later world output; no second model draw. |
| Existing ART animated masks with unequal eye coverage | Exact RGB/nonconstant depth and callback counts 14/112/14 against the existing two-pass reference; zero mask collection writes. |

The base/asymmetric runs submitted sixty world/HUD frames: opaque 60 multiview,
masks 59 multiview/1 reference, full 59 multiview; 56 frames contained the shared
model and zero contained a sequential-eye model. Startup model absence explains
the smaller model count. Injection cases intentionally reduce full coverage;
these bounded figures are not a performance claim.
