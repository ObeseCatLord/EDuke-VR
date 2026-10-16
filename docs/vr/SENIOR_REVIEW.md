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
