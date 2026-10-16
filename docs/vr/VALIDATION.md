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
| Native listen host + client; dedicated host + client | Both reach map load, but client visibly remains at “Waiting for server” | **Fail/open multiplayer readiness gate.** A loaded-map log is insufficient proof of a playable join. |
| Xvfb llvmpipe + current Monado combination | Fails with incomplete multiview FBO despite reported extension | NVIDIA native context passes; no fallback or speculative driver workaround added. |
| Temporary invalid tracking recovery | Source handling corrected to empty-frame/Idle | No injected invalid→valid runtime test yet. |
| XR context recreation/session STOPPING/loss/restart | Cleanup paths inspected; repeated process runs pass | Controlled lifecycle-transition matrix still untested. |
| Actual Duke-world VR / controller gameplay | Not implemented yet | Next milestones in PLAN.md. |
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

## Multiplayer issue to resolve next

The persistent wait is `Net_WaitForServer`'s ping-reply barrier (`network.cpp`, original lines 4671–4710), not evidence that the first world snapshot succeeded. Server replies are gated on its local player's MODE_GAME; client progress requires parsing a ping reply. Separately, `Net_ReceiveNewGame` enters the level before setting ClientPlayerReady/sending PLAYER_READY. Level entry initializes map history then waits, while world updates are discarded until ready. That ordering needs a narrow join-path correction, but it does not by itself prove the missing ping's cause.

Next experiment: retain exact ping-sent/received/replied and server-mode evidence, then defer the nested join barrier until map history and readiness exist. Verify listen and dedicated joins, actual movement/fire/respawn/map transition/reconnect and authoritative convergence. Do not bypass all synchronization or introduce a replacement network protocol.

## Local visual evidence

Sibling output files (outside the source Git repository to avoid committing game imagery):

- `../../../evidence/eduke-context-multiview.png`: inspected diagnostic left/right pair, not game-world VR.
- `../../../evidence/native-after-xr.png`: native E1L1 screenshot after XR diagnostic teardown.
- `../../../evidence/native-multiplayer-readiness-stall.png`: unresolved native multiplayer barrier.
