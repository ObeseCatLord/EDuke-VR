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

Shared native backend submitted 12 diagnostic frames standalone and 60 in EDuke's existing GL context, with distinct per-eye array-layer readbacks. Khronos core validation reported no errors. Native E1L1 rendering was visually checked after teardown. This proves a diagnostic substep, not game-world VR. Native dedicated startup now passes after one narrow input-poll guard; native multiplayer still stalls at its readiness barrier.

## Gotchas

1. Force SDL_VIDEODRIVER=x11 when using a private Xvfb; DISPLAY alone does not prevent SDL selecting inherited Wayland.
2. A clean lab without config can open GTK setup even with -nosetup. Seed an isolated config first.
3. World Tour loose CON/map filenames can fail Linux case matching. GRP-only original-script baseline works without modifying the installation.
4. Dedicated mode skips CONTROL_Startup, but G_ClearFIFO polled CONTROL_GetInput and dereferenced its null timer. Skip only that device poll for dedicated mode; retain FIFO resets.
5. Actual-context extension probing, FBO completeness and per-layer pixels are separate gates. Xvfb llvmpipe reports multiview but its current Monado FBO failed; NVIDIA passes.
6. xrEndFrame is not an application GPU-completion wait for swapchain destruction. Explicitly finish owned GL work at teardown.
7. Native/XR compile defines need distinct object trees. Merely adding a link library does not rebuild SDL hooks when a make option changes.
8. Temporary invalid poses are not fatal API failures: end an empty frame and keep polling.

## Open work

Stereo-safe game transaction, real-room two-eye oracle, tracked gameplay input, single-pass world families, full presentation coverage and multiplayer readiness/action qualification. No raw session telemetry, proprietary assets or external publication accompanies this local field note.
