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
