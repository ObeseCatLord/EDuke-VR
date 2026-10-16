# Verification record — 2026-10-15

These results distinguish working code from planned full-port behavior. Private raw logs remain in the local work directory; no session telemetry or proprietary game data is committed.

| Check | Result | Practical limit |
|---|---|---|
| Requested source archive and RazeXR clone | Pass: pinned identities/checksum in PROVENANCE.md | RazeXR current HEAD omits its engine; history retained. |
| Native GNU Make build | Pass | Existing upstream compiler warnings remain. |
| Optional XR full executable build | Pass | Linux SDL2/X11/GLX target only. |
| Native → XR → native without clean | Pass, including default `eduke32` target toggled with USE_OPENXR | XR defaults obj-xr; native defaults obj. Custom shared object-directory overrides must not mix configurations. |
| Linkage check | XR executable links libopenxr_loader; returned native executable does not | This is a build gate, not gameplay proof. |
| Standalone shared-backend diagnostic | Pass: 12 actual submitted frames after final fixes | Monado simulated HMD and null compositor, NVIDIA GL4.6. |
| OpenXR core validation | No validation errors observed during standalone and native-context tests | Validation cannot establish all GPU lifetime/visual correctness. Cleanup explicitly waits for application GL completion. |
| EDuke SDL-context diagnostic | Pass: 60 single-pass frames with first-frame-only readback; session shuts down and game continues | Diagnostic geometry only, not Duke-world stereo. |
| Two-layer pixels | Inspected both actual array layers before release; distinct, non-background images | In the inspected native capture, geometry centroid x≈161.996 vs 158.393, ~3.6 px disparity. Per-eye tint is also intentional. |
| Native rendering after diagnostic | Pass: game-generated screenshot inspected, E1L1 roof, weapon/HUD/sky visible after diagnostic teardown | Does not establish full GL-state coverage across all renderer effects/modes. |
| Dedicated baseline crash | Reproduced native RIP=0; input clock callback never initialized in dedicated mode | Kept fix at map-entry input polling caller. |
| Dedicated regression after fix | Pass: server initializes, E1L1 loads, process remains alive for 8 seconds, then test terminates its own PID | No full multiplayer gameplay claim. |
| Native snapshot stall | Fixed malformed world-update payload: pass the buffer, not the address of its pointer | Packet layouts/versions/readiness ordering unchanged; temporary traces removed. |
| Native listen/dedicated joins | Corrected builds receive world revisions; dedicated reconnect survives; listen client gameplay screenshot responds to a short W input | Fire/damage/respawn/map change and full authoritative convergence remain open. |
| Mixed native dedicated server / XR client | Pass: first join and replacement/reconnect each submit 60 world frames with distinct eye readbacks; gameplay view and W-input image change inspected | Two-pass experimental renderer; no combat/map-transition/full-convergence claim. |
| Injected failure after left opaque / before masks | Both recover to native E1L1; 10 bounded animation-input samples each have no stale duplicate owners; no extra regular-frame animation invocation observed | Startup ordinary-room failure regression, not arbitrary CON equivalence. |
| Rigid-pose/asymmetric projection derivation | 1000 mixed pose cases pass independent numeric reference, max NDC error <4e-16 | Does not qualify native visibility or physical headset optics. |
| Xvfb llvmpipe + current Monado combination | Fails with incomplete multiview FBO despite reported extension | NVIDIA native context passes; no fallback or speculative driver workaround added. |
| Temporary invalid tracking recovery | Source handling corrected to empty-frame/Idle | No injected invalid→valid runtime test yet. |
| XR context recreation/session STOPPING/loss/restart | Cleanup paths inspected; repeated process runs pass | Controlled lifecycle-transition matrix still untested. |
| Actual Duke-world stereo | First ordinary-room two-pass oracle submitted 60 frames; E1L1 roof/masked fence/sprites captured in both eye layers | Single-pass world, full-pitch coverage, tracked-motion tests, weapons/HUD, controllers, YAX/mirrors and CON regression matrix remain open. |
| Physical headset / Windows / Quest | Not tested / bindings not implemented | Simulator cannot prove headset comfort, optics, device input or sustained mobile performance. |

## Exact successful build/test shapes

Run from the repository root. Use the appropriate existing OpenXR runtime environment.

```sh
make -j8 NETCODE=1 eduke32
make -j8 NETCODE=1 USE_OPENXR=1 duke3d_game=eduke32-xr eduke32-xr
make -C source/vr -j2

# Same-target toggle test, no clean:
make -j8 USE_OPENXR=1 eduke32
ldd eduke32
make -j8 USE_OPENXR=0 eduke32
ldd eduke32

XR_ENABLE_API_LAYERS=XR_APILAYER_LUNARG_core_validation \
SDL_VIDEODRIVER=x11 ./source/vr/xr_smoke --frames 12 --timeout 15 --output /path/to/test/stereo

DISPLAY=:94 python tools/vr/smoke_dedicated.py --binary ./eduke32 \
    --grp /path/to/owned/DUKE3D.GRP --work-dir /path/to/test/labs --seconds 8
```

The private test service used `SIMULATED_ENABLE=1`, simulated simple left/right controllers and `XRT_COMPOSITOR_NULL=1`, with a task-local XDG_RUNTIME_DIR. Its manifest was selected per process using XR_RUNTIME_JSON; the user's global runtime was not replaced. Game tests use isolated `-usecwd` profiles. Xvfb :94 was owned by this task; successful native OpenXR rendering used NVIDIA on the existing X display, with local mouse/controller disabled for that test.

The native-context run used EDUKE32_XR_DIAGNOSTIC_FRAMES=60 and EDUKE32_XR_DIAGNOSTIC_OUTPUT for its first submitted pair. A screenshot was subsequently requested only from the exact owned SDL game window and inspected. The diagnostic does not replace the desktop backbuffer image with XR geometry.

## Multiplayer diagnosis and correction

The initial “Waiting for server” image was not proof that the ping barrier remained blocked. Bounded packet traces showed the ping exchange and barrier exit succeeding. The actual snapshot bug was `Net_SendWorldUpdate` passing `&tempnetbuf` to `enet_packet_create` although `tempnetbuf` is a buffer pointer. This copied bytes beginning at the pointer variable, producing malformed world-update packets. Clients saw packet type 0 instead of `PACKET_WORLD_UPDATE` (11).

Passing `tempnetbuf` restores the intended serialized data. A causal comparison observed valid type-11 snapshots and advancing client map revisions in listen and dedicated modes. The final build contains only that one-line correction; all provisional join-order changes and diagnostic instrumentation were removed. The native final harness demonstrated a rooftop gameplay view and changed image after Escape plus a short W press, and dedicated client replacement/reconnect survived. This is a useful startup/movement gate, not proof of every multiplayer action.

A subsequent mixed native dedicated-server/XR-client test passed join plus replacement/reconnect. Each client submitted 60 actual world frames and produced distinct eye layers, and its gameplay view/input image changes were inspected. Initial runs timed world frames while the connect startup menu remained open; the final runner uses the native `-nologo` option and waits for explicit level synchronization before timing. Source inspection established that G_DisplayLogo resets ready2send even with -nologo, after which G_PlaybackDemo opens the startup menu. The runner waits for the existing barrier and finite menu fade before dismissing that menu; it does not send Escape during synchronization. Pressing Escape during the network barrier exits the game, so waiting only for an E1L1 load log is insufficient. A single readiness log reports the existing ClientPlayerReady transition; no synchronization was moved.

Remaining matrix: combat/respawn, map transitions, authoritative convergence, multiple peers, VR host/two VR clients, packet loss/latency and XR focus/session changes. Keep the existing protocol and synchronization unless a new failure establishes a need to change them.

## First ordinary-room world result

The reusable XR frame API now drives both diagnostic and game rendering. The world transaction draws two opaque views, animates their stable sprite union once, then restores each eye's masked-wall IDs and pristine animated sprites for two mask passes. Native simulation, top-level events, interpolation and input remain in their original once-per-logical-frame path.

A 960×600-per-eye E1L1 test submitted 60 frames to simulated Monado. Both actual swapchain layers were read before release and inspected; the rooftop, skyline, masked fence and explosion are visible with different eye viewpoints. This is a two-pass reference renderer. World single-pass and the full presentation/input/multiplayer matrix remain required.

After the shared frame API refactor, standalone 12-frame multiview and native 60-frame diagnostic runs were repeated successfully. Native E1L1 weapon/HUD/roof rendering after diagnostic teardown was inspected again. Normal and XR full builds also passed.

## Local visual evidence

Sibling output files (outside the source Git repository to avoid committing game imagery):

- `../../../evidence/eduke-context-multiview.png`: inspected diagnostic left/right pair, not game-world VR.
- `../../../evidence/native-after-xr.png`: native E1L1 screenshot after XR diagnostic teardown.
- `../../../evidence/native-multiplayer-readiness-stall.png`: historical stalled-client image before the payload correction; not the current diagnosis.

- `../../../evidence/first-world-stereo.png`: actual left/right E1L1 world readbacks from the two-pass oracle.

- `../../../evidence/mixed-client-stereo.png`: XR client eye pair after reconnect to the native dedicated server.
- `../../../evidence/mixed-xr-client-gameplay.png`: inspected owned client desktop mirror with native weapon/HUD.

## Final retained checkpoint

Final native/XR full builds, standalone 12-frame multiview/core-validation, world 60-frame and both opaque/masks abort regressions pass. With temporary source traces removed, the final mixed runner passed native dedicated/XR-client initial join and reconnect, with 60 actual world frames and distinct readbacks for each. The corresponding native listen/client run reached gameplay and responded to W input. The final native and XR gameplay images were inspected. The private Monado service and owned game/Xvfb processes were stopped after testing.
