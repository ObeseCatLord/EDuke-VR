# Senior design review disposition — 2026-10-15

Reviewer: Astra (`gpt-6-astra`, `xhigh`), explicitly selected and effective settings verified from that reviewer's local turn metadata. Review verified source before critique. No raw operational telemetry is included here.

| Recommendation | Disposition | Implementation consequence |
|---|---|---|
| Keep native SDL, Polymost, CON, simulation, ENet | Adopted | Add opt-in native OpenXR adapter; retain flat rendering default. |
| Stereo must be one logical game-frame transaction | Adopted | Do not loop `drawframe_do` or `G_DrawRooms`; separate preparation, per-eye transient rendering, finalization first. |
| Preserve per-eye visibility/clipping/depth order | Adopted | Two-pass native rendering is correctness oracle. Center-eye occlusion and a naive geometry union are not production assumptions. |
| Separate input from XR rendering eligibility | Adopted | Future inactive/shouldRender=false frames must still sample/consume input and pump ticks/network. Current diagnostic does not gate the native draw loop. |
| Runtime diagnostic must use actual EDuke GL context | Adopted | Same backend in standalone test and SDL presentation diagnostic. Restore actual GL state so Build's cache remains truthful. |
| Diagnostic alone is not first game-rendering milestone | Adopted | First world milestone requires a loaded Duke room, head motion and native input, followed by portal/sprite proof. Current work is the runtime substep. |
| Try OVR multiview2 on available target first | Adopted | Require extension/function/shader/FBO/pixel proof in actual context. Defer ARB instancing until demonstrated need. |
| Use exact per-eye OpenXR poses/FOV | Adopted | Do not copy RazeXR's combined-FOV/shared-pose submission math. |
| Keep network structs and version initially | Adopted | Local poses/actions map into existing authority; validate mixed clients. No new pose protocol. |
| Full renderer replacement/global GL_ALWAYS→LEQUAL change | Deferred | No evidence requires either. Reopen only after a bounded adapter experiment fails. |

## Load-bearing source evidence

- `source/duke3d/src/game.cpp:6472`: `drawframe_do` combines input, world/UI, frame accounting, presentation and sound. `G_DrawRooms` has CON events at original lines 798/1115/1256, force feedback at 1063, and persistent visibility changes at 1222–1246. Sprite animation also invokes CON. Preserve once-per-logical-pass semantics, including intentional mirrors.
- `source/duke3d/src/game.cpp:6485` and original 7116–7117: input sampling lives in the draw path and tick consumption depends on `g_frameJustDrawn`. Skipping draw without an explicit input contract is a multiplayer regression.
- `source/build/src/polymost.cpp:6867`: opaque room rendering uses `GL_ALWAYS` until restoring `GL_LEQUAL` at 7168. CPU clipping and order are part of correctness; a both-eye polygon union alone is insufficient.
- `source/build/src/glbuild.cpp:82`: viewport calls are cached. External GL calls must restore real state, including on errors, before returning to the engine.
- RazeXR `TBXR_Common.cpp` original 1982/2019–2022: combined FOV and one shared head pose are not the exact per-eye projection submission reference needed here.

## Stereo transaction contract for the next slice

Both eyes share one game state, interpolation ratio and predicted display time. Input preparation, top-level display events, interpolation setup/restore, UI advancement, frame bookkeeping, sound and logical presentation execute once. Each eye gets its own camera, asymmetric projection, sector lookup, visibility/clipping, transient sprite/mask lists, and native ordering. Existing mirrors remain distinct logical camera passes with their original event ordering.

At zero IPD with identical transforms, compare both eyes against native pixels and compare CON event counts/persistent state changes. Then use a portal edge visible to only one eye. Promote one bounded opaque wall/floor draw family to single-pass GPU submission while retaining eye clipping/ownership/order. Single-pass GPU stereo does not require a single CPU visibility traversal.

Reopen architecture if implementation grows into a second visibility engine, duplicates material policy, changes global depth semantics or repeatedly repairs interactions among new layers.

## Foundation correctness review and fixes

A separate bounded Astra/xhigh correctness review inspected the actual new backend, SDL hook, make configuration and dedicated guard. Effective model/effort were again verified for that reviewer. All three actionable findings were adopted:

| Finding | Disposition / verification |
|---|---|
| `xrEndFrame` does not guarantee application GPU work finished before swapchain destruction | Added one-time `glFinish` while the current context is available, before GL/XR resource destruction. Native multi-frame test repeated after change. |
| Toggling USE_OPENXR reused incompatible SDL objects | Default object directory is now `obj-xr` when enabled, `obj` otherwise; explicit make overrides remain supported. Built native → XR → native without cleaning and checked OpenXR linkage. |
| Temporary invalid tracking treated as fatal | Successful view location with missing pose-valid flags now ends an empty frame and returns Idle, allowing recovery. API errors/count mismatch remain errors. Source checked; runtime invalid-tracking/recovery injection still untested. |

Standalone object files and Python bytecode are ignored. The reviewer found no further concrete blocker in the reviewed distinct-layer readback, GL-state restoration or narrow dedicated-server guard; that conclusion does not establish full gameplay VR or multiplayer readiness.

References for the synchronization/tracking constraints: [xrDestroySwapchain](https://registry.khronos.org/OpenXR/specs/1.1/man/html/xrDestroySwapchain.html), [Khronos hello_xr reference](https://github.com/KhronosGroup/OpenXR-SDK-Source/blob/main/src/tests/hello_xr/openxr_program.cpp).

## Ordinary-room stereo design review (second implementation slice)

A fresh Astra/xhigh reviewer inspected the room/masks and sprite-animation source; effective settings were verified from that reviewer's own turn metadata. The recommendation simplified the proposed renderer transaction rather than adding a renderer layer.

| Recommendation | Disposition |
|---|---|
| Replace two discarded visibility prepasses plus two real renders with two actual opaque draws, one animation transaction, then two resumed mask draws | Adopted. Opaque geometry remains before CON animation for both eyes, matching native ordering. |
| Restore ordered logical masked-wall IDs, not an opaque-engine snapshot | Adopted. Native Polymost reconstructs mask geometry from wall IDs; no copy of domost/occlusion state. |
| Preserve per-eye sprite membership through animation and generated children | Adopted. Stable canonical slots, explicit parent membership at weapon/chat/shadow appends, pristine animated list restored before each eye. |
| Treat projection correctness separately from full-pitch visibility coverage | Adopted. Exact asymmetric crop is installed in native projection setup. Unsupported yaw-forward coverage is logged and rejected by this experimental oracle, with full-pitch support still required. |
| Keep YAX, mirrors and arbitrary-CON equivalence as explicit follow-up proofs | Adopted. The first result demonstrates ordinary E1L1 room pixels only; it is not full presentation coverage. |
| Detect both collection and generated-list capacity loss | Adopted. Collection/union capacity is checked; the three native append capacity checks now report saturation to the transaction. |

The first integrated result submitted 60 actual Duke-world frames to simulated Monado, with distinct left/right rooftop images. The implementation is a **two-pass reference**, not the final single-pass world renderer. An independent Astra/xhigh correctness review of the implemented transaction and shared frame API also completed; effective settings were verified again.


## Implemented world transaction correctness review

| Finding | Disposition |
|---|---|
| Aborted opaque/union passes leave sprites that native fallback appends to; aborted post-animation passes contaminate the next frame | Adopted. Clear sprite and masked-wall counts on every touched transaction exit. Added one-time opaque/masks fault injection and bounded input-provenance/count evidence. |
| Position and orientation used different body-pitch/roll transforms | Adopted. One `(bodyPitch * bodyRoll) * inverseYaw` rigid rotation applies to both, then Build's unequal horizontal/Z units. Native positive roll maps to XR +Z. |
| CON animation and display-end observers inherit right-eye camera/aspect | Adopted. Restore native viewport/aspect and common renderer camera before animation and after frame completion, preserving script-visible state changes. |
| Camera-only mask preparation clears buffers in wireframe/point modes | Adopted. Pass an explicit no-clear setting through factored camera setup. Ordinary native opaque setup retains its debug clear. |

The reviewer verified all but the pending list-cleanup patch directly during its review; the main agent then applied the accepted cleanup and passed both final opaque/masks failure regressions, each with ten bounded animation-input samples and native recovery. The independent numerical projection check covers 1000 mixed pose/asymmetric-FOV cases with maximum NDC error below 4e-16. This derivation check does not replace real visibility, callback, portal or headset tests. Strict matched-target zero-IPD pixel/event equivalence now passes in the deterministic ordinary-room fixture. Portal eye-only sprite membership and arbitrary CON callback semantics remain open acceptance gates.

## Single-pass collection boundary review — 2026-10-16

A fresh Astra/xhigh senior review verified the final vertex/material submission path. Effective model and effort were checked from that reviewer's exact turn metadata. The demonstrated incompatibility is eye-specific CPU clipping followed by order-dependent GL_ALWAYS drawing; a shader-only center-view broadcast cannot preserve the reference.

| Recommendation | Disposition |
|---|---|
| Capture final vertices and already-resolved typed shader/material inputs instead of extracting all native material preparation | Adopted for the bounded prototype. Native resolution/setters/cleanup remain authoritative; no second material resolver. |
| Isolate replay in a separate program/location table and leave native uniform mirrors/hidden caches intact | Adopted. Shader compatibility is the first executable check. A reusable replay VBO may transport vertices; native stream offsets/fences stay owned by their existing code. |
| Capture native projection at construction and rotation at accepted emission, before drawrooms resets it | Implemented in collection: projection at construction and rotation at emission. Saving rotation after the room render would lose pitch/roll. |
| Merge only compatible packet heads; filtering by eye must reproduce every original packet/triangle in order | Adopted. No global sort or depth-policy change. Pairing saves submission calls; it does not prove shared CPU traversal, shared geometry work, or improved GPU time. |
| Probe existing GLSL120 fragment policy with the multiview vertex variant before collection | Implemented as an opt-in actual-context compile/link probe; runtime result recorded in VALIDATION.md after testing. Any required version wrapper uses the same fragment body. |
| Retry unsupported candidate collection with the two-pass opaque oracle inside the same ready frame, before animation | Implemented in integration. Rejected candidates rerun opaque traversals before animation in the same ready frame; no callback replay after animation begins. |
| Limit this to three implementation slices and reopen if it requires general GL interception, traversal snapshots, state serialization or material-policy duplication | Adopted: shader/state handoff, collection/replay, then transaction integration/differential fixtures. |

The first promoted family is ordinary indexed ART opaque geometry with shade-table rendering and supported sampler/texture state. Sky, recursive passes, mutable textures, models, masks and unsupported material branches remain explicit exclusions until individually qualified. Complete single-pass world rendering remains the requested endpoint; a paired opaque batch alone does not close it.

## Bounded opaque implementation correctness review

A separate fresh reviewer explicitly selected `gpt-6-astra` at `xhigh`; its exact turn metadata was checked before relying on the result. It verified stream ordering/right-eye transform handling, qualification, native cache restoration and the pre-animation retry boundary. One actionable finding was adopted:

| Finding | Disposition |
|---|---|
| Replay initialization errors escape the owned GL-error interval; a program can be cached before successful VBO creation | Fixed. Initialize inside the owned interval, drain errors before retry, delete partial objects, and publish program/VBO together. An injected invalid-target GL error plus simulated VBO failure exercises cleanup; the same frame falls back and later frames replay successfully, with exact pixels and unchanged CON counts. |

Main integration checks additionally required explicit texture-client unit zero, separate matrix-array locations, program/cache truth restoration without native uniform setters, and qualification of actual program/depth/blend/alpha/color-write/modelview/texture state. These were implemented before final fixture tests. The reviewer did not run tests or fully review the subsequently added asymmetric fixture; runtime evidence and final integration checks remain the main agent's responsibility. Main integration then removed the duplicated right-only draw body: paired and either-eye packets now share one upload/draw helper, with the unequal-coverage fixture exercising both unpaired branches.

Results: zero-IPD uses 18 paired calls/216 vertices; nonzero symmetric-coverage stereo uses 30 paired calls/342 vertices. Unequal coverage deliberately leaves all 60 calls unpaired because shader-effective visibility differs. All three cases preserve exact reference pixels and CON counts. This qualifies the restricted adapter; it does not establish complete world single-pass, shared geometry work, lower frame time, or full CON/mod compatibility.

## Native sky extension correctness review — 2026-10-16

A fresh read-only reviewer explicitly used `gpt-6-astra` / `xhigh`; its own current-turn settings were verified before relying on its result. It inspected the final sky, NPOT, depth-capture and fixture changes and found no actionable correctness issue. Main integration separately checked native/XR builds and runtime results.

| Investigated decision / recommendation | Disposition and evidence |
|---|---|
| Reuse native flat-sky panel/UV/material generation at the existing drawpoly seam | Adopted. Removed only the explicit sky rejection; native panel selection, panning and projection remain authoritative. |
| Admit the existing sky-Z depth pass without admitting arbitrary masked geometry | Adopted. A scoped marker at the exact native `DAMETH_MASK` recursion qualifies all-false color writes; normal masks and alpha/blend cases retain their restrictions. Packet kind participates in pairing; replay restores incoming color mask. |
| Real LA sky ART needs nonidentity NPOT uniforms | Adapted from the earlier restriction. Runtime showed tile91 using native NPOT values (.0078125,1.70667,1,.585938). The packet and unchanged fragment already carry the native calculation; admit finite valid native values, without copying material policy. |
| Color-only equality does not establish depth correctness | Adopted. Compare complete nonconstant GL_UNSIGNED_INT depth readbacks for both actual layers as well as exact color. Native and two-pass references match the sky fixtures exactly. |

The reviewer verified the first positive ceiling-sky/depth/panning result JSON (30 paired calls, including nine flat-sky, nine depth-only and nine NPOT calls). Main then passed rotated sky with panning/depth disabled, unequal-coverage floor sky with depth enabled, and the ordinary-room regression. These are bounded feature proofs; masks remain per-eye and full VR presentation/gameplay qualification remains open.

## Indexed ART mask phase design checkpoint — 2026-10-16

Fresh `gpt-6-astra` / `xhigh` design review, with effective settings verified for this turn. The reviewer inspected the actual native mask traversal and collector before critique. Main spot-checked replay error returns, projection capture timing, native equal-depth groups, and direct sprite bypasses.

| Recommendation | Disposition / implementation |
|---|---|
| Distinguish rejection/pre-draw failure from partially committed mask pixels | Adopted. Sticky replay-submitted bit is set immediately before `glDrawArrays`. Pre-draw rejection can restore pristine native mask inputs; an error after submission ends empty, disables XR and consumes the animated logical pass. |
| Begin collection before camera preparation | Adopted. Shared mask helper begins before `renderPrepareMasksQ16`, which captures the current eye projection. |
| Keep one phased collector and existing native sort | Adopted. Generic public API, same packet vectors/program/VBO/native fragment, no new sorter or material resolver. |
| Require zero eye color/depth writes during mask collection | Adopted. Active MASK guards stop Polymost2, models and modern/legacy voxels before direct entry, even after rejection. Native fan transport stays intercepted. Editor/polygon modes reject. Texture mutations remain allowed to complete but reject the candidate. |
| Validate both blend equations and restore actual incoming state | Adopted. RGB/alpha equations and factors checked separately; replay preserves alpha test, separate blend state, depth and color writes and reconciles Build accounting. Packet variation remains limited to actual native inputs. |
| Restore pristine sprite lists between complete native traversals, not between equal-depth subpasses | Adopted. The common helper installs post-CON sprites and original wall IDs per eye and retry; native tile animation and two-pass sprite group behavior remain intact. |
| Add scratch framebuffer or general GL recorder | Rejected for this bounded phase. Inspected ordinary paths can suppress target writes directly; scratch targets do not solve texture mutation or native CPU animation side effects. Reopen if a new reachable draw path cannot be isolated. |
| Fault and equivalence proofs must establish actual mask replay | Adopted. Harness now requires frame-12 mask replay counts, exact RGB/depth and CON counts; snapshots compare color/depth immediately before/after capture. Separate late-right collection, pre-draw replay and post-draw replay faults exercise recovery boundaries. |

No additional user preference or approval was required for these correctness choices. Full headset presentation, controllers, arbitrary CON/mod compatibility and multiplayer qualification remain separate incomplete gates.


### Mask implementation and follow-up reviews

Fresh Astra/xhigh correctness review caught a redundant exit `buildgl_resetStateAccounting()` after raw sampler restoration: the helper actively unbinds samplers. Adopted the smaller fix—delete the exit reset, because replay entry already invalidates accounting and subsequent operations use raw GL. The reviewer verified this call graph and found no remaining actionable issue in that slice.

A further explicitly selected/verified Astra/xhigh follow-up checked the final bool-returning begin/preflight skip and animated ART fixture. Failed MASK begin now skips traversal before editor diagnostic paths; direct guards still protect later rejection in a traversal. Consecutive DEF animation bases exercise 285→286→287 within the native equal-depth group, with a nonzero cutoff and deterministic test-only `totalclocklock`. No simulation timer or engine C ABI change was introduced. The reviewer found no actionable issue in these scoped changes.

A proposed production clock-freeze API was deferred: source investigation found no actual timer/event pumping in these traversals, so repeated camera preparation alone did not establish animation-clock drift. Model/voxel, unsupported-material and capacity-triggered no-write fixtures remain gaps; source guards and an injected late rejection are not equivalent runtime coverage of those assets.


## Controller actions and native input integration — 2026-10-16

Fresh controller design and implementation reviewers explicitly used
`gpt-6-astra` / `xhigh`; effective settings were verified for each review turn.
Terra separately investigated the native input seam and implemented the bounded
runtime action backend. Main owns mapping, integration and runtime conclusions.

| Recommendation / finding | Disposition |
|---|---|
| Title/menu and demo playback have their own loop | Adopted. Both ordinary game and non-profiling demo owners acquire/sync once before native input. Auxiliary room draws cannot acquire frames. |
| Snap-turn through mouse input inherits MouseBias and Strafe behavior | Adopted the smaller first slice: native joystick smooth yaw/pitch. A dedicated snap angular seam remains future work. |
| SDL event handling can invalidate a captured runtime/session | Adopted. Runtime generation increments on shutdown; captured frame/input identity is checked without a lazy getter or XR call from CONTROL. |
| Poll even when world rendering is ineligible | Adopted. Predicted time is published after wait, including Idle returns; focused actions are queried regardless of frame rendering. Real blocked-view-tracking test retains native firing. |
| Desktop app focus must not suppress headset input | Adopted. Runtime/action focus is authoritative; native keyboard/device gates stay native. |
| Do not duplicate native menu repeat or cleared-until-release state | Adopted. One raw semantic snapshot enters existing CONTROL filtering. Physical action activation only adds release-before-use protection on source activation. |
| A demo early RECHECK exit could leave an unclaimed frame open | Fixed after review: close the unconsumed frame immediately after background/rooms, before UI/menu callbacks and the early exit. |
| External activity did not update LastSeenInput | Fixed after review. Actual analog/button/menu activity selects native Joystick input semantics, including native aim-assist behavior. A neutral connected controller does not select it. |
| Profile allowlist and scalar-to-Boolean conversion | Follow core OpenXR action binding rules, with runtime conversion; no duplicated trigger threshold/hysteresis. Only Index has runtime-device proof here. |

The implementation review found no remaining blocking source issue in its
reviewed slice. Main fixed the two integration gaps above and ran the actual
controller/title/lifecycle/native-server tests. Context recreation with captured
input and explicit `shouldRender=false` input proof remain narrower gaps; native
SDL2 `restartvid` reuses its existing GL context and must not be labeled recreation.
Haptics, tracked weapon aim/origin, headset UI and full multiplayer qualification
were outside this bounded slice and remain required for the requested full port.

## Headset presentation architecture — 2026-10-16

A fresh explicit `gpt-6-astra` / `xhigh` review verified the actual source before
critique; current effective metadata was independently checked. Main separately
traced the save-thumbnail, menu dimming and native final-swap call sites. The
review changed the first implementation boundary and supplied concrete ordering
and cancellation requirements.

| Recommendation | Disposition |
|---|---|
| Keep the existing projection-array world; avoid copying composed desktop world into both eyes | Adopted. Target is one native UI capture and one GPU plane into the existing array. A compositor quad would retain the capture/effect problems and add a resource/color boundary. |
| Prove opaque cold-menu presentation before transparent HUD | Adopted as first checkpoint, under EDUKE32_XR_UI=1. This stages the full UI adapter; world/weapon/HUD completion is still required. |
| A swap does not identify the logical owner's final presentation | Adopted. The owner explicitly arms immediately before its intended videoNextPage; unarmed nested swaps cancel/mirror/end empty. No lazy XR initialization from a swap. |
| Generation alone does not catch mode/extent changes with a retained SDL context | Adopted. Capture extent is checked at arming; resize/minimize/video-mode/renderer changes cancel before native operations. Next owner begin also drains skipped presentation. |
| Auxiliary save/premap room draws can contaminate UI capture | Adopted. Cancellation covers whole G_DrawRooms entry, before background/CON/readback. Main also found an existing frame-permission gap: only intended world owners may arm a draw, and permission is consumed at entry so nested draws cannot steal it. |
| Native full-eye tint cannot become a rectangular finite-panel effect | Adopted for the later HUD stage. Adapt the named full-eye effect at its original boundary: tint world, transform premultiplied UI RGB with coverage preserved, then compose. Do not reorder menu dimming relative to menu text. Cold no-world menu proof does not close this gate. |
| Source-over alpha needs separate coverage; arbitrary custom blends do not fit the same rule | Adopted. Initial opaque capture ignores stored alpha; future transparent capture is bounded to verified conventional blending/opaque writes. Unsupported destination-dependent factors need explicit handling, not an invented material resolver. |
| Compare native reference callback counts, not an absolute global one | Adopted. Native thumbnails and duplicate native background draws remain intentional; no callbacks are rerun merely to recover pre-world UI pixels. |

A scratch actual-GPU GLX probe confirms the conventional alpha issue and one
raw-RGBA8 route: native red alpha.5 stores RGBA127,0,0,63 on transparent clear;
separate alpha ONE stores127,0,0,127. Two overlays captured and then composed over
blue exactly match direct native RGB95,64,96, with no GL error. This is not a
native shader/compositor/headset proof. Panel distance1.5m remains provisional.

### Cold-menu implementation review and fixes

A fresh explicitly selected Astra/xhigh implementation review, with effective
settings verified, found three conditional issues. All were adopted:

- Successful `xrLocateSpace` with missing validity now cancels/mirrors/ends empty;
  it does not disable XR. Actual submitted-frame deltas drive the SDL counter.
- Menu VIEW space, shaders and geometry now initialize lazily on first capture;
  UI-disabled world/diagnostic initialization has no menu-resource dependency.
- Capture preserves native UI's final viewport/cache and mirrors to the full
  native extent. Begin no longer changes the viewport; target restoration keeps
  only framebuffer/buffer fields instead of an entire persistent GL snapshot.

Removed unused blend-function/equation and stencil-function/operation state from
this opaque adapter; kept the masks/enables/clear/sampler/renderbuffer state it
actually changes. Same-size captures reuse their texture/depth allocation.

A further fresh Astra follow-up could not start because of the agent-thread
limit. No substitute reviewer was used. Main verified the fixes directly and
ran injected invalid-pose, non-full cached viewport, unarmed nested native swap,
desktop pixel equality, console/resize, native-game transition and regression
checks. Real minimize/render-mode transitions, actual context recreation,
in-game save rendering and broader mod/native presentation remain separate gaps.


### Transparent HUD implementation of the reviewed target A

The target-A design above is now implemented experimentally with UI=2, using
its same capture/resource/owner boundary. No extra scene target, swapchain,
command recorder, protocol, rendering thread or simulation was introduced.

| Reviewed recommendation | Implementation/disposition |
|---|---|
| Extend the existing projection-array owner through final native presentation | Adopted. Successful world rendering retains the acquired frame; outer game/demo owners begin UI capture after rooms return, then arm the intended final swap. A retained world is also canceled before auxiliary room entry. |
| Preserve actual submission identity | Adapted. A runtime frame serial and last successful submitted serial qualify one pending statistics receipt. Canceled images cannot count as submitted world frames. Runtime lifecycle state remains authoritative. |
| Factor conventional source-over coverage; preserve opaque writes | Adopted. Capture-target-aware separate alpha blending, native opaque clears, and transient native-shader coverage preserve GREATER alpha discard before opaque coverage one. Unsupported custom factors/model HUD cancel before entry. |
| Adapt full-eye effects at their original native boundary | Adopted. Shared unchanged native correction GLSL tints both world eyes; native captured UI uses premultiplied corrected tint and destination coverage without changing coverage. Native dim-before-menu and final palette-tint ordering remain. |
| Preserve native desktop output without executing UI twice | Adopted. One flat GPU composite puts captured UI over the left-world desktop base; partial capture cancellation uses the same composite. |
| Reconcile same-context extent changes | Adopted. Existing runtime shuts down/reinitializes only at the ordinary frame boundary after the native extent commits; subsequent owner/input generation checks use that new runtime identity. |

Main source/GPU verification caught a real corrected-color edge case: native
normalized-target clamping must occur before tint premultiplication. The test
also corrected its own initial assumption about native brightness/contrast
translation: native matrices scale those offsets by source alpha. Actual
nondefault and over-range correction tests now stay within one RGB byte of
independent blend arithmetic; unchanged-world fixtures still use zero tolerance.

A fresh model-selected Astra follow-up could not start because retained agent
threads exhausted capacity. The supported app messaging route also rejects
model-selected input to these subagents. No substitute or unverified resumed
review was used. This slice has the preceding verified Astra design review and
main source/GPU verification, not a fresh independent implementation review.


## Authoritative tracked orientation — main verification, 2026-10-16

A fresh explicitly selected Astra/xhigh design review was requested against a
verified brief. Creation again failed at the retained agent-thread limit. No
unverified resumed/substitute review was used. The preceding Astra architecture
review requires native authority, correct camera/shot agreement and a narrow
adapter; main source/GPU/native-server verification supplies this bounded slice.
This is not claimed as a fresh independent implementation review.

| Decision | Main disposition and evidence |
|---|---|
| Copy RazeXR temporary local shot override | Rejected for this authority boundary. Historical `shoot_d_override` restores local player state; EDuke's server fires remote RPGs from native replicated player angles. Existing `playerupdate_t` already carries the needed orientation. |
| New pose protocol or parallel player/controller simulation now | Deferred until independent hand origins. Orientation uses native `P_GetInput` → `P_UpdateAngles` and existing packets. Two applied angular offsets recover an independent body from native authority, rather than duplicating absolute body/player state. |
| Drive the camera directly from authoritative controller aim | Rejected. Remove applied offsets from the ordinary camera base, then use actual HMD eye poses. Both actual eye-camera inputs and GPU crosshair pixels are verified; head mode is tested against double rotation. |
| Use an eye quaternion as HMD calibration | Rejected for tracked authority because eyes can be canted. Reuse the actual VIEW space/pose before hand acquisition; no second space or XR lifecycle. |
| Treat a missing pose as loss of native look ownership | Rejected after runtime evidence: this re-enabled centering and shifted body pitch during recovery. Look ownership follows the live XR context; unavailable poses gate aim/fire updates, while native ticks/control flow continue. |
| Clear calibration/angular offsets on every runtime generation | Adapted. New action samples/buttons invalidate normally. A last valid HMD pose rebases existing origin/yaw calibration when LOCAL is recreated, preserving virtual view/body aim without another body or lifecycle state. Actual nonzero-pose resize/session replacement passes. Native player reset deliberately starts a fresh calibration. |
| Leave the native head-center crosshair for controller aim | Rejected. Preserve its event/script offset and add tracked-versus-native projection correction using actual authoritative angle/horizon, sharing existing panel dimensions. The finite panel and native auto-aim/spread remain explicit limits. |

The estimate remained bounded: existing native frame/input/render boundaries,
one shared VIEW resource, one calibration sample and two angular offsets; no
new service, renderer, actor simulation or wire format. Direct verification also
covers native pitch clamp at a vertical controller pose, shortest yaw wrap and
body locomotion with the controller pointing backward. Full tracked weapons,
hand-origin authority, full-pitch rendering and broad mod/demo/camera behavior
remain required, not substituted by this orientation checkpoint.


## Controller-attached native ART — main verification, 2026-10-16

A verified source brief compared reusing the sequential capture with a separate
weapon target and a renderer/asset replacement. A fresh explicitly selected
Astra/xhigh request failed at the retained agent-thread limit. No unverified
resumed/substitute reviewer was used. This slice follows the existing verified
Astra target-A ownership/coverage guidance and main source/GPU verification;
there is no fresh independent implementation review.

| Decision | Main disposition |
|---|---|
| Add a second weapon texture/FBO/lifecycle | Rejected as unnecessary. Existing texture is flushed, mirrored, cleared and reused sequentially under the same owner/acquired frame. |
| Duplicate weapon rendering for each eye or for the desktop | Rejected. Native weapon/event path runs once; one multiview card draw serves both eyes, and the native flat capture is mirrored once. Actual callback counts match separate native runs. |
| Capture face effects with the hand weapon | Narrowed. End before `P_DisplaySpit`; scuba and later HUD remain on the head panel. Other native weapon/action families still need explicit placement qualification. |
| Move native player state to align a visual weapon | Rejected. The card uses actual LOCAL aim pose; existing native angles/shot authority remain unchanged. Independent hand-origin authority is a separate explicit native movement-update/sector/collision design. |
| Keep full-eye tint on a panel | Rejected by preceding Astra guidance. Already-composited weapon pixels are part of the world when native tint/dimming occurs; later captured HUD preserves its own coverage/order. Independent final-image arithmetic passes. |
| Add another owner token or presentation queue | Unnecessary. Existing cancellation/arming handles nested weapon-scope videoNextPage and native save auxiliary rendering; both recover without callback duplication. |

Independent CPU ray/plane/sample and final HUD/tint oracles cover actual texture
layers, not counters alone. Native runtime eye/card poses are logged at nine
decimal places; triangle coverage uses the queried driver subpixel grid.
The initial ideal-edge/rounded-pose oracle disagreed at one boundary pixel in a
head-motion case; correct raster coverage resolved it without relaxing RGB
limits. Foreground depth, native pitch limits, per-weapon pivots and unchanged
body shot origin remain explicit prototype limits.


## Hand-origin RPG authority — main verification, 2026-10-16

A verified brief compared a negotiated movement tail with a global version
rewrite, separate pose stream and temporary Raze-style player replacement.
Fresh explicitly selected Astra/xhigh creation again failed at the retained
agent-thread limit. No substitute model or unverified resumed review was used.
This change follows preceding verified Astra native-authority/incremental
architecture requirements plus main source/GPU/native-server verification;
a fresh independent implementation review remains outstanding.

| Decision | Main disposition and actual evidence |
|---|---|
| Replace networking or introduce another player simulation | Rejected. Same ENet peer, native input/fire prefix and actor replication; only an optional acknowledged14-byte tail. |
| Send pose independently of fire | Rejected. Same movement packet carries both; malformed tails reject before applying any prefix. Seven actual malformed ENet cases plus missing capability pass. |
| Reuse body sector for a physical hand across a portal | Rejected. Common native trace/updatesectorz/pushmove/cansee resolves the start sector; actual RPG starts in neighbor sector1 while body remains on the other side. Closed/glancing fixtures constrain the origin. |
| Permit stale held fire after loss | Rejected. Native-clock expiry and release gate qualify actual stopped-client timeout/recovery, not only local pose validity. |
| Add a second autoaim/damage implementation | Rejected. Native events/target choice/ownership/damage retained. Opt-in RPG velocity normalization is explicit; actual enemy collision/death and separate autoaim preference pass. |
| Treat successful server spawn as client replication proof | Rejected after failure. Actual client EVENT_GAME found no live RPG; native cached player0 index misclassified incoming projectile8192. Bind actual snapshot APLAYER/STAT_PLAYER identity, retain native player prediction copy, and repair same-stat sector links. Live client RPG fields now agree. |
| Treat contiguous player records as arbitrary-slot proof | Rejected after failure. Real slot1 disconnect left sparse0,2 updates; server ammo36/client44 exposed ordinal indexing. Receiver now uses the validated record player ID; both server and actual slot2 client report36. |
| Generalize all weapons before one complete proof | Rejected. RPG-only opt-in end-to-end slice first. Other native weapon families and multiplayer combat/respawn/map/loss gates remain required. |

No renderer, protocol service, actor packet or absolute body state was added.
The estimate grew only at two demonstrated native replication defects; narrow
repairs stayed in their existing functions. Before broadening weapons, obtain a
fresh Astra review when capacity permits and challenge whether each adaptation
can reuse existing native helpers without duplicating weapon policy.


## Native hitscan authority design — verified Astra/xhigh, 2026-10-16

Fresh review agent hitscan_authority_design ran explicitly selected gpt-6-astra
at xhigh; main independently verified that exact turn's effective session
metadata before relying on it. The reviewer read source and the verified brief,
made no edits and ran no GPU tests. Main owns implementation and runtime proof.

| Recommendation | Disposition |
|---|---|
| Separate GetAutoAimAng correction from accurate-probe success | Adopted. Select physical/native corrected base immediately after the former. The later probe only suppresses spread. A steep free-aim actor-hit test exercises the distinction. |
| Keep a local resolved-sector/effective-ray contract | Adopted. Only a private two-field context crosses native prefire/final hitscan; no new player state, networking or damage implementation. |
| Reject tangent singularities and arbitrary pole-threshold hybrids | Adopted. Bounded F*cos(a)+R*sin(a)+cross(F,R)*b, with retained yaw at the pole; native sample/event boundaries remain. Physical pitched spread is explicit. |
| Forced slopes and native postfire must agree | Adopted. Encode the override last; derive postfire vertical sign and impact yaw from that exact ray. Opposite-hand-direction forced floor/ceiling cases qualify it. |
| Match presentation to actual supported/default projectile | Adopted. Shared family/Shoots/actual-tile/custom-exclusion predicate is used by firing, card origin and crosshair. |
| Verify grow separately and strengthen geometry/behavior fixtures | Adopted in tests; remaining overlapping-XY/YAX, broad native switch/material/mod and dynamic-world coverage remain explicit gates rather than inferred from the horizontal portal. |

A separate explicitly selected Astra/xhigh implementation-review creation hit
the retained thread limit. No substitute or unverified resumed review was used.
The subsequent initial-snapshot repair was reopened independently: both duplicate
sprites were visible/self-owned, disproving a visibility/owner heuristic. The
native codec can send every actor field at initial/rebase revisions, preserving
existing readers and subsequent deltas; main chose that narrow repair over a
new identity packet or guessed sprite index. It requires runtime before/after
and compatibility proof and is not covered by the earlier design review.

Main runtime investigation additionally found a native readiness failure outside
the reviewed hitscan design. The byte-sized pingcnt was compared with its saved
entry value using greater-than. A maximum-counter fixture with real replies
stayed inside Net_WaitForServer/G_EnterLevel, confirmed by an owned debugger;
observed responses continued wrapping below255. The narrow repair compares for
change and rate-limits reliable requests to the existing simulation tick. No new
handshake/counter protocol or timing service is introduced. This repair likewise
has main runtime verification, not a separate fresh Astra implementation review.


Final main compatibility review caught a capability-version boundary: the
previous hand server's feature1 promises RPG only. Treating that acknowledgement
as support for new hitscan would display a hand origin while an old server fires
from the body. Adopted an optional mask3 upgrade after the original mask1
request/ack, with per-peer server weapon gating and selected-weapon client
availability. Original peers retain the original exchange. Actual pinned
RPG-only server tests require hand RPG success plus hitscan suppression/movement;
new peers require explicit hitscan acknowledgement. This is a bounded extension
of the existing capability field, not a separate protocol/service. It is main
verification, outside the fresh Astra design review.

## Freezer/shrinker extension — main verification, fresh review unavailable

A verified scratch brief compared the existing projectile boundary adapter with
a generic weapon layer, temporary body replacement and new per-projectile VR
flags. Fresh explicitly selected Astra/xhigh creation hit the retained thread
limit. No substitute review ran. Main kept the existing native resolver,
velocity boundary, damage/bounce/effect logic and actor replication. A shared
velocity helper replaces the RPG's literal code and handles freezer/shrinker;
tracked shrinker network creation uses native server authority. Actual native
client projectile, freeze/shrink state, bounce and regressions qualify this
bounded slice. The narrow zero-xvel backoff repair removes a reproduced sideways
vertical impact, without a new projectile state machine. It does not redesign
all native impact policy. User subsequently removed older-peer compatibility as
a requirement; additional work should focus on current-build behavior.

## World-space crosshair — main design/verification

User requested a projected world-space reticle. The verified scratch brief
compared the existing sequential native-ART capture with injecting an actor,
moving CON callbacks into room rendering, or adding a renderer/swapchain. Main
kept the existing event order and capture/lifecycle, extending only its draw
boundary with two native clip matrices and depth testing. Independent work could
not start at retained agent capacity; earlier explicitly selected Astra follow-up
requests hit the same limit. No fresh review or substitute-model review ran.

| Decision | Main disposition/evidence |
|---|---|
| Reuse HUD projection depth | Rejected. Native Polymost's depth differs from the backend HUD near/far convention. Export actual prepared native projection/rotation plus relative Build mapping. Independent physical projection and real world-depth occlusion pass. |
| Add a fake actor or move the crosshair event into room rendering | Rejected. One native event and original desktop ART segment remain; existing multiview capture is reused without another actor/owner/texture. |
| Keep a camera-facing marker on every contact | Adapted after runtime failure. It intersected its own wall. Native wall/sector plane alignment removes that clipping; actor contacts retain billboard presentation. |
| Place by the centre of the full capture texture | Rejected after source/runtime inspection. Reuse native viewport/320x200 scaling to find the actual ART anchor. The independently projected world point matches the marker anchor in both eyes. |
| Trust a green counter/uploaded matrix | Rejected. Real server shot, independent physical projection, CPU depth/pixel oracle, actual occlusion and native callback references qualify15 cases plus9 regressions. |
| Keep visible test windows | Rejected at user's request. Explicit hidden drawable mode and native startup suppression; actual X11 unmapped/focus checks pass for all15 final reticle fixtures. |

The central ray is a preview, not another implementation of native autoaim,
weapon spread/CON fire events or ballistic simulation. Those callbacks are not
replayed for the reticle. User no longer requires older-peer interoperability.


## Native PvP checkpoint — verified Astra/xhigh read-only review

A fresh reviewer ran with explicit `gpt-6-astra` / `xhigh`; parent independently
verified those effective settings in this review turn's metadata. Scope was the
small native spawn writer, existing receiver/reset references, late submission
receipt, private fixture and before/after local JSON. No GPU work, services,
builds or edits were delegated. The reviewer accepted the one-offset packet
correction and its unchanged27-byte/native-receiver contract.

| Recommendation | Disposition |
|---|---|
| Historical score maxima can hide1→0 regression after convergence | Adopted. Retain maxima, then require every observed sample after the established kill checkpoint to preserve expected frag/death/self values on all peers. A CPU regression test rejects the false positive; retained complete pre-fault logs also pass this stronger interpretation. |
| Fixed48-round post-reset oracle can reject native pickups | Adopted. Require no actual victim rays, no observed Fire bits and no ammo consumption during the held interval; allow native pickup increases. CPU cases accept48→96 and reject consumption, Fire input, shots or empty observations. |
| Pre-fix recovered-controls claim exceeds its JSON | Adopted. Before-fix record proves recovered movement, not post-respawn fire. The two corrected records do include resumed fire/ammo convergence. |
| Distinct stereo pairs alone can be frozen images | Adapted. Require actual image changes between death and recovery as well as submission receipts. Saved XR-victim frames were visually inspected for native death/zero-health versus recovered100-health HUD. This is bounded fixture evidence, not general renderer correctness. |
| Defer unqualified dual-runtime branch and remove obsolete fallback assertion | Adopted. Both removed from the checked-in harness; experimental copies remain only in ignored local work. No second runtime is needed for this mixed-client checkpoint. |

The final harness revisions have CPU observation tests and syntax checks, but
remain pending a healthy-driver runtime rerun. Earlier passing mixed-client
records are explicitly historical fixtures, not execution of the later changes.
NVIDIA Xid51/154 caused the graphics-test hold; root cause remains unknown.
This review does not close independent two-VR, VR host/maps/loss, or the full
port/SPS/multiplayer goal.
