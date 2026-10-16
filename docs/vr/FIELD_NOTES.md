---
game: Duke Nukem 3D / EDuke32
status: in-progress
date: 2026-10-15
agents: [Codex]
---
# EDuke32 native OpenXR foundation: field notes

## Setup

EDuke32 r10669 ec5824db8 from the user-specified archive; RazeXR caa96be6d80f2ab74fce4b945d54eeda39c3fc20. Linux x86_64, SDL2 2.32.72, OpenXR loader 1.1.60, Monado v25.1.0-847-g6b41c5b39, NVIDIA GL4.6. See PROVENANCE.md and VALIDATION.md. No relevant knowledge-base entry was found before work.

## Route and actual engine behavior

Use a native OpenXR adapter, preserving Build/EDuke simulation, CON and ENet. RazeXR HEAD removed the Raze engine subtree in b9fb2bf; its Android wrapper remains. Two-layer FBO creation is reusable as a concept, but not proof of a working single-pass game renderer.

Polymost does CPU screen-space occlusion/clipping and uses GL_ALWAYS for opaque rooms. A center-eye projection broadcast to two layers can omit visible geometry. Retain independent eye visibility as the correctness reference. GPU single-pass does not imply one CPU traversal.

The top-level game draw function also gathers input and advances persistent/script state. G_DrawRooms and sprite animation invoke CON callbacks. Do not call those twice without an explicit frame contract; do not skip them for shouldRender=false without separating input/consumption.

## Verification

Shared native backend submitted 12 diagnostic frames standalone and 60 in EDuke's existing GL context, with distinct per-eye array-layer readbacks. Khronos core validation reported no errors. Native E1L1 rendering was visually checked after teardown. The diagnostic remains a substep. The subsequent ordinary-room two-pass oracle submitted 60 actual E1L1 world frames and both eye images were inspected. A native dedicated server/XR client also passed join/reconnect with 60 world frames and distinct layers per join. Native dedicated startup passes after one narrow input-poll guard; the snapshot stall was corrected separately without changing readiness order or packet layout.

## Gotchas

1. Force SDL_VIDEODRIVER=x11 when using a private Xvfb; DISPLAY alone does not prevent SDL selecting inherited Wayland.
2. A clean lab without config can open GTK setup even with -nosetup. Seed an isolated config first.
3. World Tour loose CON/map filenames can fail Linux case matching. GRP-only original-script baseline works without modifying the installation.
4. Dedicated mode skips CONTROL_Startup, but G_ClearFIFO polled CONTROL_GetInput and dereferenced its null timer. Skip only that device poll for dedicated mode; retain FIFO resets.
5. Actual-context extension probing, FBO completeness and per-layer pixels are separate gates. Xvfb llvmpipe reports multiview but its current Monado FBO failed; NVIDIA passes.
6. xrEndFrame is not an application GPU-completion wait for swapchain destruction. Explicitly finish owned GL work at teardown.
7. Native/XR compile defines need distinct object trees. Merely adding a link library does not rebuild SDL hooks when a make option changes.
8. Temporary invalid poses are not fatal API failures: end an empty frame and keep polling.

9. A successful ping barrier can leave a stale “Waiting” image. Trace actual packet types/revisions before changing synchronization. Net_SendWorldUpdate passed &tempnetbuf when tempnetbuf was a pointer; passing tempnetbuf fixes corrupted snapshots. Remove causal trace scaffolding afterward.
10. Polymost masked walls reconstruct geometry from ordered logical wall IDs. Two opaque views → one stable union animation → two resumed masks avoids discarded visibility prepasses and a full transient-engine snapshot. Preserve per-eye sprite membership through generated children and restore canonical animated slots before each eye, because drawing changes picnum.
11. Native Polymost does not reset spritesortcnt before ordinary collection. Clear shared counts when aborting an XR transaction before native fallback or the next frame, or stale inputs duplicate sprite callbacks. Both injected abort points now pass bounded provenance/count regressions.
12. Apply one rigid tracking rotation to both eye position and orientation. Native pitch * roll corresponds to XR pitch * positive-Z roll; horizontal/Z Build scales are 384/6144 units per metre, derived from historical RazeXR's 24 world units/metre and 16/256 map scales.
13. Camera-only preparation must not clear depth/color. The native resizeglcheck debug wireframe path does, so mask/logical-camera reconstruction explicitly suppresses that clear.
14. The native connect startup path can show its menu after level synchronization. -nologo skips animation, but G_DisplayLogo still clears ready2send and G_PlaybackDemo opens the startup menu. Automated gameplay tests wait for the barrier and finite menu fade before dismissing it; Escape during Net_WaitForServer exits the game.

## Open work

Zero-IPD/native callback/pixel equivalence, portal eye-only membership, real tracked-motion/full-pitch proof, tracked gameplay input, single-pass world families, full presentation coverage and complete multiplayer action/convergence qualification. No raw session telemetry, proprietary assets or external publication accompanies this local field note.
