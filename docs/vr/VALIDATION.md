# Verification record — updated 2026-10-16

## Current checkpoint — 2026-10-18

Actual AA native multiplayer early and late joins now pass eight checks each:
the remote player reaches input processing on both peers and the client renders
AA's real character selector. Startup admission retains ENet keepalives while
waiting for native initialization/map state; reserve sprites no longer receive
CON game events. Stock authoritative movement/fire, map changes and reconnect
pass 25 checks, and the software-XR multiplayer custom crosshair passes 16.
Four CPU lifecycle cases pass: prolonged first-map loading, unassigned-peer
disconnect, server-loss recovery to native menu drawing, and quit during wait.
Read [AA_MULTIPLAYER.md](AA_MULTIPLAYER.md) and sibling
`evidence/aa-multiplayer-startup-validation.json`. AA selected-character combat
and script-state replication remain incomplete. NETVERSION6 is unchanged.

AA's actual Duke pistol now uses the native hand-hitscan adapter and AA's own
event-drawn crosshair is projected/depth-tested in both eyes. Real controller
fire/release/tracking-loss recovery, native multiplayer impact/damage for the
same weapon combination, and custom crosshair/viewport/nested-screen regressions
pass. Matching **NETVERSION6** peers are required; the packet layout is unchanged
from version5. See [AA_COMBAT.md](AA_COMBAT.md) and sibling
`evidence/aa-combat-validation.json`. Full AA multiplayer, remaining arsenal/model
bindings and broader SPS remain incomplete.

Stock native-counter tracked pistol animation now passes actual private
software-XR/native multiplayer tests, including authoritative reload-flag
synchronization (matching native NETVERSION5 peers). Exact color/depth model
oracles pass in array and immediate modes; failure, custom/timing/missing-frame
fallback and last-round paths are exercised. Read
[PISTOL_ANIMATION.md](PISTOL_ANIMATION.md). Complete results and original failed
attempts are sibling `evidence/pistol-animation-validation.json`.

AA 5.66's actual installed scripts/assets now reach selected Hollywood world/UI
and controller-operated Duke/START selection with inspected post-selection
stereo gameplay images. Native cache recovery restores replacement-VBO state;
CON startscreen reuses the existing XR UI lifetime. The observed AA scene uses
native two-pass fallback, not accepted full multiview. Apart from the Duke pistol
and native startup increments above, AA weapon integration and multiplayer
campaign behavior remain unqualified. Read
[ALIEN_ARMAGEDDON.md](ALIEN_ARMAGEDDON.md). Private art delivers 69 AA handheld
entries plus both hands; main verified 1,614 manifest files and 71 indexed MD3s.

Historical revision numbers and narrower scope claims below describe their
original checkpoints. The full VR port remains incomplete.


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
| Historical Xvfb llvmpipe + Monado combination | Failed with incomplete multiview FBO despite reported extension | Superseded by matched Mesa26.2.3 GL/LVP CPU proof below; no renderer workaround added. |
| Temporary invalid tracking recovery | Source handling corrected to empty-frame/Idle | No injected invalid→valid runtime test yet. |
| XR context recreation/session STOPPING/loss/restart | Cleanup paths inspected; repeated process runs pass | Controlled lifecycle-transition matrix still untested. |
| Actual Duke-world stereo | First ordinary-room two-pass oracle submitted 60 frames; E1L1 roof/masked fence/sprites captured in both eye layers | Single-pass world, full-pitch coverage, tracked-motion tests, weapons/HUD, controllers, YAX/mirrors and CON regression matrix remain open. |
| Native-fragment multiview shader probe | Pass in actual NVIDIA EDuke GL4.6 context; unchanged GLSL120 fragment links directly with GLSL410 multiview vertex; normal native E1L1 afterward | Link/state proof only; full renderer coverage remains open. |
| Strict zero-IPD differential fixture | Native matched-array reference, two-pass eyes and multiview eyes match all 576,000 pixels exactly; CON counts 14/14/14 | Fixed ordinary portal room, indexed ART, normal sprite mask; not arbitrary CON/mod compatibility. |
| Nonzero IPD/asymmetric FOV/rotated fixture | Both multiview eyes match their two-pass references exactly; 30 paired calls, 342 vertices; eyes distinct | Deterministic synthetic pose, no projection layer submitted; not live tracking/headset proof. |
| Unequal eye coverage / replay init failure | Exact per-eye reference match; 0 paired / 60 eye-only calls, 342 vertices; one injected GL error + partial init cleanup recovers before animation | Demonstrates conservative incompatible-state handling and retry, not draw-call savings for this case. |
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

## 2026-10-16 — initial bounded opaque multiview proof (7044f12)

A generated two-sector portal map uses owned indexed ART, alternating wall palette/shade inputs and an ordinary bottle sprite. A stock-CON wrapper fixes only the rendering camera and counts DISPLAYROOMS / ANIMATESPRITES / DISPLAYROOMSEND. Native and stereo paths each report 14/14/14; sprite animation remains one logical transaction. No owned game data is copied into the fixture source.

The first uncontrolled-camera comparison was invalid because startup interpolation advanced differently. Fixing the normal writable CON camera gamevars removed that difference. The remaining 344 of 576,000 window-versus-array pixel differences persisted with identical camera/projection values, including a native-projection XR experiment. The unchanged native room/animation/mask path rendered to a matching SRGB8_ALPHA8/depth24 array attachment then matched both stereo eyes exactly. The strict harness defaults to that matched attachment; it retains `--native-attachment window` and reports the choice explicitly. No error tolerance was introduced. This isolates render-target dependence; the exact driver-internal rasterization cause was not established.

The new opt-in opaque path captures already-resolved native shader inputs/final vertices, triangle-expands fans, and linearly merges compatible packet heads. Eye ownership clips the other view's triangles while preserving each filtered eye stream's GL_ALWAYS order. Native persistent-buffer offsets/fences, material policy and uniform caches remain owned by native code. Replay has isolated program/VBO resources and restores actual GL state/accounting before native masks. Main integration retries rejected collection in the same ready XR frame before any sprite/CON animation.

| Fixture | Strict pixel reference | Frame-12 replay evidence |
|---|---|---|
| Identical zero-IPD eyes | Matched native reference and two-pass, both exact | 18 paired calls, 0 eye-only, 216 vertices |
| 64 mm IPD, asymmetric FOV, pitch/yaw/roll | Two-pass, both exact and mutually distinct | 30 paired calls, 0 eye-only, 342 vertices |
| Unequal coverage, injected init failure | Two-pass, both exact and mutually distinct; counters unchanged | 0 paired, 60 eye-only, 342 vertices; failed init cleaned and later replay succeeds |

Unequal coverage changes shader-effective visibility, so these packets deliberately do not pair. Two CPU traversals and duplicate eye geometry remain. Masks still use two passes. These figures establish actual multiview submission for the restricted family; they do not establish lower GPU/CPU time or complete single-pass world frames.

Reproduce with the existing runtime environment:

```sh
python3 tools/vr/check_stereo_oracle.py --binary ./eduke32-xr --single-pass --display :1 \
  --grp /path/to/owned/DUKE3D.GRP --work-dir /path/to/test/labs
# Add --pose stereo for the asymmetric fixture.
# Add --pose unequal --inject-replay-init-failure for eye-only and recovery paths.
```

The native-fragment shader proof linked unchanged GLSL120 directly; the generated GLSL410 version wrapper was not needed. Fresh Astra/xhigh correctness review found an initialization-error ownership/partial-object issue, now fixed and fault-injection tested. At that checkpoint, E1L1 with the prototype enabled rejects sky explicitly, uses the existing oracle and submits 60 frames with distinct actual eye images. The mixed native dedicated/XR-client runner repeated initial join and reconnect with the prototype enabled; both retain 60 frames/distinct eyes and the owned gameplay image responds to W input. This exercises the oracle fallback, not paired multiplayer sky rendering.

Native and XR full builds pass, as do the 1000-case projection derivation and Python compilation/diff checks. Image `../../../evidence/bounded-opaque-stereo.png` shows the asymmetric portal fixture. Complete opaque sky/material coverage, mask/sprite multiview, real tracking/full pitch, controllers/headset UI, broad CON features and the full multiplayer action matrix remain open.

## Native flat skies, NPOT and depth validation — 2026-10-16

The opaque adapter now lets native flat-sky panel generation reach the same captured drawpoly fan seam. Native ART panel selection, UVs, panning, shade/palette and the fragment shader remain unchanged. The exact native sky-Z recursion has a scoped depth-only marker; its all-false color mask is captured as a packet kind and restored after replay. Ordinary masked geometry remains excluded from opaque collection.

The first attempt reached a real material restriction: LA sky tile91 uses non-power-of-two height. Native NPOT shader uniforms were (.0078125,1.70667,1,.585938); the packet and unchanged fragment already carry all four. Admission now allows finite valid native NPOT state. No material-resolution or UV calculation was copied.

Depth readback saves/restores actual GL state and reads each layer as raw GL_UNSIGNED_INT samples. The comparator requires complete, nonconstant depth data and exact equality, alongside exact RGB pixels. At zero IPD, native matched-array rendering is the reference. Other poses compare to the same-pose two-pass reference; their callback counts must match that reference, since the camera legitimately differs from native zero pose.

| Scene / controls | Actual multiview calls at frame12 | Pixel / depth result |
|---|---|---|
| Ceiling sky, zero pose, depth and panning on | 30 paired; 9 flat sky, 9 depth-only, 9 NPOT | Both color and nonconstant depth exactly equal native and two-pass; CON14/14/14 |
| Ceiling sky, rotated asymmetric stereo, depth and panning off | 33 paired; 15 flat sky, 0 depth-only, 15 NPOT | Both eyes exactly equal their two-pass color/depth references |
| Floor sky, unequal eye coverage, depth and panning on | 6 paired +76 eye-only; 19 flat sky, 19 depth-only, 19 NPOT | Both eyes exactly equal their two-pass color/depth references |
| Ordinary room zero pose regression | 18 paired; no sky/depth-only/NPOT | Native/two-pass color/depth exactly equal; callback counts match |

Fresh explicitly verified Astra/xhigh correctness review found no actionable issue in the final sky/NPOT/readback diff and inspected the first positive sky result. Main executed the remaining matrix and inspected the actual E1L1 stereo capture. Native/XR full builds and Python/diff checks pass.

With the prototype enabled, real E1L1 first60frames measured 59 opaque multiview +1 reference frame. Requiring60/60 correctly failed; the 59minimum test passed. Mixed native dedicated-server/XR-client initial join/reconnect each still render60actualworldframes with distinct eye readbacks and visible movement input. One run measured58/60 on initial join and59/60 on reconnect, failing its explicit59minimum; a diagnostic repeat measured59/60 on each and passed. Bounded fallback logs identify texture/palette mutation and also record a later frame79 mutation during gameplay. Coverage is therefore variable when assets stream; full steady/performance/multiplayer qualification is not closed by these startup checks. Masks still use two passes in all these tests.

Reproduce the added cases with the existing runtime environment:

```sh
python3 tools/vr/check_stereo_oracle.py --binary ./eduke32-xr --single-pass --scene sky \
  --sky-depth 1 --display :1 --grp /path/to/owned/DUKE3D.GRP --work-dir /path/to/test/labs
# --pose stereo --sky-depth 0 --sky-panning 0 exercises rotated sky with those native switches off.
# --scene sky-floor --pose unequal --sky-depth 1 exercises floor and eye-only packets.
```

World and mixed runners now report opaque multiview/reference frame counts independently of successful stereo submission; `--minimum-multiview-frames` can enforce a chosen threshold without concealing reference frames. `../../../evidence/sky-world-stereo.png` shows actual E1L1 eye layers with opaque multiview plus native per-eye masks. The synthetic differential fixtures still submit no projection layer.

## Native indexed ART masks/sprites in multiview — 2026-10-16

The MASK phase reuses the opaque packet transport/program/VBO and native fragment shader. Native partition/sort/interleave still determines each eye's packet stream. It captures actual native cutoff/blend factors and depth/color-write variants, retaining equal-depth sprite color/depth-only passes. Direct Polymost2/model/voxel branches reject before their draw entry even after earlier rejection. Failed preflight now skips traversal before editor diagnostic paths. Texture uploads can complete but reject collection. No second geometry/material/sort implementation was added.

A fresh Astra/xhigh senior design review established the explicit submission boundary and projection-capture ordering. A fresh correctness review caught redundant cache invalidation overwriting restored samplers; deleting that reset fixed it. Another verified Astra/xhigh follow-up found no issue in the final preflight skip and animated fixture. See SENIOR_REVIEW.md for dispositions and remaining test gaps.

The richer generated fixture has eight stationary sprites, a masked portal, face/wall/floor orientations, translucent overlaps and an equal-depth group. `masks-animated` adds a translucent portal, native DEF animation bases 285→286→287 across the group's two passes, and alpha cutoff .25. An explicit fixture-only input fixes `totalclocklock=1` for native and XR mask rendering; simulation time is untouched. It does not establish a production clock-drift bug or change the native renderer ABI.

| Final case | Mask replay at frame12 | Exact result |
|---|---|---|
| Animated masks, zero IPD | 11 paired, 132 vertices; 3 translucent, 2 depth-only, 5 depth-write-off calls | Both RGB images and raw nonconstant depth match native and two-pass; CON14/112/14 |
| Animated masks, asymmetric stereo with pitch/yaw/roll | Same call counts; eye images distinct | Both RGB/depth match same-pose two-pass; callback counts match |
| Animated masks, unequal eye coverage | 22 eye-only calls, 132 vertices; 6 translucent, 4 depth-only, 10 depth-write-off | Both RGB/depth match two-pass; distinct eye images and matching callbacks |
| Late right-eye collection rejection plus queued GL error | No MASK replay at captured frame; native masks retry | Exact native/two-pass RGB/depth and CON counts; no leaked GL error |
| Replay error before first mask draw | No MASK replay at captured frame; native masks retry | Exact native/two-pass RGB/depth and CON counts |
| Sky with depth companion regression | 30 opaque paired calls including 9 sky/9 sky-depth/9 NPOT; one paired bottle-mask call | Native/two-pass RGB/depth and CON counts exact |

For every final differential case, readbacks immediately before and after collection prove **zero changes to both eyes' RGB/depth before replay or fallback**. These observations include the injected late rejection; they do not substitute for real model/voxel, unsupported-material or capacity-triggered fixtures. Post-first-draw injected replay failure takes the other branch: XR stops after ending an empty frame, the logical animated pass is consumed, and ten bounded animation-input samples retain correct counts/provenance. No opaque retry after CON occurs.

Real E1L1 final first60frames measured opaque59/reference1, masks58/reference2, with **58 complete opaque+mask multiview world frames** and distinct layer readbacks. Native dedicated-server/XR-client initial join and replacement/reconnect each measured opaque59/reference1 and masks59/reference1, with **59 complete multiview world frames per join**. Both joins rendered60 world frames with distinct eye images; owned W input changed188,585 desktop pixels and its weapon/HUD/world screenshot was visually inspected. This is startup/reconnect/input evidence, not combat/map-change/authority convergence or headset presentation qualification. The eye layers still contain world geometry; the desktop weapon/HUD screenshot is not a claim that those appear in the headset.

Texture/palette mutation still causes reference phases, including during streaming. Two CPU traversals and duplicate vertices remain; no GPU/CPU timing benefit is claimed. Native/XR full builds, Python compilation and diff checks pass. Existing allocator compiler warnings persist in the baseline code. Full-pitch/collision/real tracking, controllers, headset weapon/HUD/menu presentation, other camera/material families and full multiplayer/platform matrices remain required.

Reproduce with private runtime environment and owned GRP:

```sh
python3 tools/vr/check_stereo_oracle.py --binary ./eduke32-xr --single-pass \
  --scene masks-animated --display :1 --grp /path/to/owned/DUKE3D.GRP --work-dir /path/to/labs
# Add --pose stereo or --pose unequal.
# Add --mask-failure collect-right or --mask-failure replay-before.
EDUKE32_XR_SINGLE_PASS=1 python3 tools/vr/smoke_world.py --binary ./eduke32-xr \
  --failure-stage mask-replay-after --display :1 --grp /path/to/owned/DUKE3D.GRP --work-dir /path/to/labs
```

World and mixed runners additionally accept `--minimum-full-multiview-frames`; this is a separate gate from successful stereo submission and opaque-only coverage. Evidence: `../../../evidence/mask-world-stereo.png`, `../../../evidence/mask-multiplayer-gameplay.png` and compact `../../../evidence/mask-validation.json`.

## OpenXR actions through native controls — 2026-10-16

One physical action set now samples Boolean actions, sticks and valid grip/aim
poses at the located frame's predicted time. Both ordinary game and title/demo
loops own one sample. CONTROL merges the mapped snapshot before its existing
button/analog processing; native input_t, CON, ENet and authority are unchanged.
The dedicated executable is the flat build without an OpenXR dependency.

Actual tests use the installed Monado remote driver, an exclusive private
runtime/config directory, Index device inputs and the NVIDIA GLX context. The
remote helper sends actual Monado device state; it never substitutes game
input or network packets. Owned profiles reference the GRP read-only. XSendEvent
is restricted to the exact owned SDL window; desktop focus is not changed.

| Test | Observed result |
|---|---|
| Single-player actions | 12 checks pass: valid real OpenXR aim poses, native movement, fire/ammo/release, controller inactivation, held reconnect suppression/repress, menu open/hold/back, held-button clearing on close, keyboard coexistence. Position (-31243,7160)→(-30718,9229); pistol ammo48→44. |
| Title/demo-loop menu | Four checks pass: focused actions in the startup loop, primary advances to episode menu100, holding does not choose an episode, secondary returns to main menu0. |
| Tracking/action availability | Real libmonado POSES block invalidates tracked poses while native firing continues. INPUTS block neutralizes actions; unblocking a held trigger requires release/repress. |
| Real XR focus transition | A second owned hidden OpenXR application becomes primary. First game loses action focus, emits neutral controls and continues native ticks. Returning primary focus suppresses the held trigger until release/repress. |
| Native video reset | `restartvid` executes through the owned window's OSD. SDL2 retains its GL context/session, held input continues, and release/repress works. This is not context-recreation evidence. |
| Native dedicated + XR client | Both original join (assigned slot1) and replacement join (assigned slot2) pass authoritative server position/input/fire/ammo/release checks. Each spends pistol ammo48→43. First position(-31243,7160)→(-33260,8536); replacement→(-32389,9875). |
| Stereo regression | Animated-mask asymmetric stereo remains exact in both RGB and complete, nonconstant raw depth against the two-pass reference; once-only CON counts remain equal; mask collection changes no eye color/depth pixels. |
| Real world frame ownership regression | E1L1 submits60 actual world frames with distinct eye readbacks: opaque59 multiview/1 reference; masks and complete world57 multiview/3 reference. Streaming fallback remains visible. |
| Runtime validation | Rebuilt shared standalone backend submits12 multiview frames with Khronos core validation enabled; no validation warning/error reported. |
| Builds | Native and optional XR full builds pass. Flat binary does not link OpenXR; XR binary links its loader. Python compilation and diff checks pass. Existing smmalloc warnings remain. |

The replacement test terminates the first owned process and reconnects a new
client; the old ENet peer can remain until its native timeout, so the new client
may receive a different slot. The harness reads the actual native read-only
`myconnectindex` log and matches that exact player on the server. Initial harness
runs failed because they assumed slot1 and then waited for client CON input while
the startup menu was still open. The corrected barrier waits for native network
synchronization, finishes the finite menu fade, dismisses that menu, then waits
for the assigned native index and corresponding server observations. No game
protocol or connection behavior was changed to make the test pass.

Retained bounded evidence is `../../../evidence/controller-validation.json`.
The individual test labs/logs remain local under work/. Pose validity is not yet
tracked gameplay aim. Haptics, tracked weapon/shot alignment, user bindings,
headset UI, real hardware ergonomics, captured-input context recreation,
explicit shouldRender=false observation and the full multiplayer action matrix
remain open. Null compositor tests do not establish headset comfort or visuals.

## Opaque cold-menu headset presentation — 2026-10-16

`EDUKE32_XR_UI=1` opts into native startup-menu/console capture on an opaque
head-relative plane, using the existing acquired projection array. One native
UI draw and one multiview plane draw serve both eyes. World submission remains
on its previous path; this checkpoint does not qualify transparent HUD or
in-game menu/fade handling.

| Case | Actual result |
|---|---|
| Cold menu |60 actual successful submissions, nonconstant and distinct eye layers, native UI/desktop captures exactly equal. Both menu callbacks report60/60, matching the native flat reference fixture. |
| Temporary invalid head pose |One successful real location query is deliberately marked invalid. That frame cancels; the session recovers to60 actual submissions without XR shutdown. |
| Non-full capture-entry viewport |The test sets native cached/actual viewport to13,17,half-size. Native UI changes it to full; final actual viewport remains full and desktop pixels exactly equal the native UI capture. |
| Nested native swap |One real videoNextPage is injected before the owner arms final presentation. It cancels/mirrors/ends empty; later owners reach60 submissions, with exact desktop/UI equality and no double menu callbacks. |
| Console and resize |Owned window changes960x600→800x600; console appears in actual eye captures. Capture is800x600, both eye images remain nonconstant/distinct and desktop/native UI pixels match exactly. |
| Menu→game |Native keyboard menu selections enter E1L1. World then submits60 frames with distinct eye readbacks: opaque59, mask/full57 multiview; the remaining frames use the existing reference. |
| Rendering regression |Animated-mask asymmetric stereo still matches two-pass RGB and complete nonconstant depth exactly. Native/oracle callback counts14/112/14 remain equal; capture writes no eye pixels before replay. |
| Multiplayer regression |Flat dedicated server + XR client, original and replacement joins, each pass server-authoritative movement/position/fire/ammo/release. |
| Native quit |Quit through the owned menu exits0; the XR instance is destroyed without core-validation warnings/errors. The input helper allows expected window destruction only when the process exits cleanly. |
| Builds/API validation |Native/XR builds and Python/diff checks pass. Cold-menu, faults, resize and game transition report no core-validation warning/error. UI-disabled standalone submits12 validated multiview frames. |

`tools/vr/smoke_menu.py` retains bounded checks and actual UI/desktop/eye readbacks.
Flags `--invalid-pose-once --partial-viewport --nested-swap-once` exercise the
specific recovery/cache cases; `--console --resize` exercises cold console
resizing; `--enter-game` exercises native level entry. The fixture itself only
observes native menu callback counts. A native flat run with the same wrapper
reports60/60. No simulation state, packets or global desktop input are injected.

Opaque UI alpha is intentionally ignored. Standard source-over coverage, custom
blends, full-eye tint/dimming, pre-world script overlays, depth/model HUD,
in-game menus/save captures, actual minimize/render-mode/context recreation,
world rendering across window resizing and real headset optics/comfort still
need qualification. Captured XR layers are runtime texture evidence under a
null compositor, not a real-headset visual test.

Visual QA caught an initially weak console assertion: the harness recorded key
delivery before startup/resize input clearing had settled. The corrected runner
waits for stable menu input, requires positive `osdRows` at the captured frame,
and the final eye image was inspected. It reports36 visible console rows with
an800x600 capture and exact desktop/UI equality. A first native-quit check also
mistook expected window destruction between key down/up for failure; the runner
now accepts that only after verifying clean exit0, never retargeting another
window or sending global input.


## Native ART headset weapon/HUD overlay — 2026-10-16

`EDUKE32_XR_UI=2` implements the previously reviewed transparent target A on the
same reusable capture and acquired projection array. Native ART weapon/HUD,
in-game menus and console draw once, then one head-relative multiview plane
composites them over distinct eye worlds. The desktop uses a flat GPU composite
over its left-world mirror. No UI callbacks are replayed.

| Case | Actual result |
|---|---|
| Ordinary E1L1 |60 actual HUD/world projections; native pistol/health/ammo visible over distinct stereo worlds. Final first60: opaque59, mask/full57 multiview; texture-loading frames retain the reference path. |
| Coverage |Generated local ART with opaque index255, masked index255 and overlapping 2/3 and 1/3 translucent rectangles passes actual RGBA8 coverage readback. Measured alpha includes0,85,170,198,255. Zero-coverage RGB remains zero. |
| Depth and peripheral world |Both entire raw world-depth layers are byte-identical before/after HUD composition. Peripheral world RGB is unchanged exactly without an effect. |
| Full-eye tint |Actual native fullscreen tint reaches peripheral world pixels. Default correction matches independent encoded-value blend arithmetic exactly; nondefault and over-range corrected/clamped cases differ by at most one RGB byte. UI tint arithmetic also stays within one byte while preserving coverage. World differential tolerance remains zero. |
| Native callback reference |Separate flat runs match rooms/room-end61/61, weapon/rest60/60. The fixture normalizes only the timed cosmetic spawn knuckle animation so weapon callback eligibility does not depend on frame rate. |
| In-game menus |Actual native in-game menu ordering/full-eye168-alpha black dim passes. Native save menu invokes its extra room/readback, cancels capture before auxiliary entry, then recovers to60 world/HUD submissions. Counts62/62/60/60 match flat; the actual auxiliary read uses native read/draw framebuffer0 and contains nonconstant world pixels. The opaque save panel intentionally covers the transparency fixture. |
| Console |Owned-window console activation is visible at the captured frame (`osdRows` positive), with actual UI coverage and stereo layers. This tests the native font/background submission path too. |
| Tracking/nested swap |One invalid VIEW pose and one real unarmed nested videoNextPage cancel without crediting an unsubmitted world. The session subsequently reaches60 projections, with native callback counts unchanged. A non-full cached capture-entry viewport is also injected and the final native viewport sentinel passes. |
| Resize |Owned native window960x600→800x600 commits before the existing XR runtime recreates at the next ordinary frame boundary. New generation reaches60 world/HUD submissions with matching world/UI extent; depth remains unchanged. |
| Existing renderer/UI regression |Animated-mask asymmetric stereo still matches native two-pass RGB and nonconstant depth exactly, with equal CON counts14/112/14. Cold-menu/console resize retains exact native-UI/desktop equality. |
| Multiplayer |Native dedicated server plus XR client, original and replacement joins, each pass authoritative movement/position, fire/ammo and stable release. Each now also requires60 world/HUD projections and distinct final eye captures. No protocol change. |
| Builds and validation |Native, OpenXR and standalone builds pass. Flat executable does not link OpenXR. Python syntax/diff checks pass. Core layer is active with no validation warning/error in HUD faults, save, tint, resize, console, both network clients and standalone12-frame submission. |

`tools/vr/smoke_hud.py` runs these scenarios against an already-running private
runtime. Flags are `--tint 1/2/3`, `--native-menu main/save`, `--console`,
`--resize`, and `--invalid-pose-once --nested-swap-once`. Use
`EDUKE32_XR_TEST_MENU_VIEWPORT=1` with the last case for the cache sentinel.
`smoke_actions_multiplayer.py --reconnect --require-hud` adds actual presentation
and eye-readback gates to the existing server observations. All input targets
only owned processes/windows; game assets are read-only links in isolated labs.

Two failed experiments are retained locally: the initial nondefault tint test
assumed ordinary brightness/contrast offsets instead of native alpha-scaled
matrix translation; the stronger over-range test then caught a real missing
pre-premultiplication clamp, which was fixed. The first60-submission network
extension also exposed a fixed .55-second release-observation window containing
an in-flight fire sample followed by two released samples. The runner now waits
at most3 seconds for **three consecutive authoritative released samples**; it
does not relax release correctness or inject packets.

Bounded retained results are `../../../evidence/hud-validation.json`; actual
ordinary headset layer readbacks are shown in `../../../evidence/hud-stereo.png`.
Null-compositor simulation proves texture/submission behavior, not actual headset
optics, comfort or performance. No fresh independent implementation review was
available for this slice; it follows the preceding verified Astra target-A
design and main source/GPU verification. Tracked aim/3D weapon alignment,
haptics/settings, full pitch/room-scale/camera families, general materials and
HUD models/custom blends, pre-world CON drawing/help, real context loss/platform
ports and full multiplayer combat/host/map-change coverage remain open.

## Authoritative tracked orientation — 2026-10-16

`EDUKE32_XR_AIM=right|left|head` opts into orientation adapted at native
`P_GetInput` before `P_UpdateAngles`. Existing native angles, input records,
packets and weapon simulation remain authoritative. Two applied offsets recover
body direction for locomotion and the HMD camera. There is no temporary local
shot override or new pose protocol. Independent physical hand origins remain
required future work.

| Case | Actual result |
|---|---|
| Native dedicated server + right aim |24 checks pass in the final run. A tracked12° yaw/8° pitch produces server deltas12.000002°/8.000000°; holding the pose does not accumulate rotation. |
| Left and head sources |Both source modes pass native authority, actual RPG/impact, stereo camera, crosshair and core-validation checks. Left selects the pose source; the provisional physical fire binding remains the right trigger. |
| Actual native RPG |Server spawns angle68, zvel-1458 from its native player authority. Actual far-wall explosion is(8175,5626,-26316). Independently predicted impact differs by15.76 horizontal and606.64 vertical Build units, within one native discrete movement step plus wall clearance. Autoaim is disabled only in this controlled fixture. |
| Independent HMD |Controller stays12°right/8°up while HMD turns18°left/6°up and translates(.08,-.02,-.05)m. Native server aim is unchanged. Actual left/right camera yaw is-.314159rad and pitch.104720rad, so head orientation is applied once. Head-aim mode also passes the no-double-rotation check. |
| Direction marker |Native authoritative angle/horizon projects onto the shared head-relative panel at(.856192,.084329)m, matching an independent basis calculation. Actual UI pixels contain the crosshair at the predicted position. This is a direction marker, not a world-depth hit indicator. |
| Tracking availability |Selected hand can be inactive before the first world frame and join later without calibrating from an eye quaternion. Loss/recovery while the trigger is held produces no extra shot; release/repress fires again. Native look ownership remains active during unavailable poses, preventing legacy centering from tilting the recovered body. |
| Runtime generation replacement |Actual640x480→800x600 native resize recreates XR at the existing frame boundary. Native aim, both eye angles and nonzero translated eye positions remain unchanged: left(1039,4115,-9829), right(1047,4138,-9829). Replacement reaches another60 world/HUD submissions. This is session replacement in a retained GL context, not real context destruction/loss. |
| Native limits and body controls |Vertical controller pose reaches native horizon299 without stale pitch/undefined yaw.179°→-179° follows the shortest2° displacement. Forward motion remains along body heading when the hand points backward. Sustained native stick look keeps the virtual body within native pitch limits. |
| Rendering/UI regressions |Animated-mask asymmetric stereo retains exact native two-pass RGB and complete nonconstant depth; callback counts14/112/14 match. HUD console/depth/coverage and cold-menu console/resize checks pass. |
| Existing multiplayer/actions |Original and replacement native joins still pass movement, firing/ammo, stable release,60 world/HUD submissions and distinct eyes. Prior focus/IO/held-action lifecycle suite passes all12 checks with tracked aim unset. Its restartvid case retains the GL context. |
| Builds/API validation |Native, XR and standalone builds pass; native executable has no OpenXR dependency. Python syntax/diff checks pass. All three tracked-source tests and the standalone12-frame run have core validation active with no warning/error. |

`tools/vr/smoke_aim.py --mode right --late-controller --resize` is the strongest
combined scenario; `--mode left` and `--mode head` select the other sources.
The runner uses a generated local room with four native multiplayer spawn
points, a CON observation fixture and actual Monado remote poses/actions. It
observes native server logs and real texture readbacks; it does not inject game
packets, override shots or write owned game assets. The existing join helper now
dismisses a startup menu only when native state actually reports one.

Early fixture attempts omitted multiplayer spawn points, unconditionally opened
a menu with Escape, or captured before the independent HMD sweep. Those harness
errors were corrected without changing native connection/simulation policy.
Runtime testing also found and fixed real pose-recovery centering, pole-pitch
and calibration-loss cases; native pitch limits now also constrain recovered
virtual body pitch. Failed runs remain local rather than being counted as proof.

Bounded results are `../../../evidence/tracked-aim-validation.json`; actual final
eye layers are shown in `../../../evidence/tracked-aim-stereo.png`. A fresh
explicitly selected Astra/xhigh review could not start at the retained
agent-thread limit. No substitute or unverified resumed review was used; this
slice has main source/runtime verification and preceding Astra architecture
guidance, not a fresh independent implementation review.

The native2D weapon remains on the head-relative HUD. True controller-attached
weapons and authoritative hand-origin/collision/replication, full pitch,
demo/record/save-load/CON-angle rewrites and other cameras remain unqualified.
The full VR-host/native-client/two-VR combat, damage/frag/respawn/map-change and
loss matrix remains open. Null-compositor captures do not qualify physical
headset optics, comfort or performance.

## Controller-attached native ART card — 2026-10-16

`EDUKE32_XR_WEAPON=1` with UI=2 and right/left tracked aim separates native
weapon ART from the head HUD using the same capture texture. Preceding UI,
weapon and subsequent HUD are sequential segments under the existing owner.
Each segment uses one multiview draw; native callbacks are not replayed. End of
weapon capture precedes face spit/scuba. No shot or packet behavior changes.

| Case | Actual result |
|---|---|
| Base, translated, yaw/pitch/roll and independent HMD |Actual card pose matches the selected remote source plus the provisional grip pivot. Both complete eye RGB layers match independent CPU ray/plane/linear-texture sampling within one byte. HMD can turn15°left/6°up and translate while the physical hand remains fixed. |
| Left hand |The left aim pose drives placement, with actual complete eye RGB matching the independent projection within one byte. This does not yet switch the provisional right-trigger fire binding. |
| Selected pose loss |Actual native weapon ART is still captured and callbacks run normally; both eye images have exactly zero changed pixels at the weapon boundary. Final HUD contains no stale weapon. |
| Resize |Native960x600→800x600 commits through the existing XR recreation boundary. Actual isolated weapon layers match within one/two bytes; complete final HUD composition matches within one byte. Both full world depth layers remain unchanged. |
| Tint |Already-placed weapon becomes part of the world at the native full-eye corrected/clamped tint boundary. Independent final head-HUD plus world/tint arithmetic matches both complete eye layers within two bytes. |
| Native save menu |Actual auxiliary room/capture cancels the owner and recovers. Complete final menu/dim/HUD composition matches within one byte. Native/XR counts62/62/60/60 agree, including the intentional extra native room. |
| Weapon-scope nested swap |A real unarmed `videoNextPage` is injected after native weapon drawing, before card composition. It cancels the active weapon/UI capture, mirrors native pixels and later reaches60 actual world/HUD submissions. Callback counts61/61/60/60 match native, with no duplicate weapon event. |
| Capture separation/depth |In all ten cases, actual isolated capture contains opaque native weapon ART. Its pixels are absent from the later HUD capture wherever the opaque save panel is not intentionally covering them. Both complete raw world-depth arrays are byte-identical before/after card composition. |
| Native references |Every scenario compares observed rooms/room-end/weapon/rest counts with a separate actual native flat run; all match. Final eye composition independently includes the later head-relative HUD. |
| Multiplayer with attached weapon |Native dedicated server plus tracked XR client passes all24 orientation/RPG trajectory, held recovery, late-controller, body control, actual stereo/crosshair and nonzero-pose session-recreation checks with attached weapon enabled. Actual server RPG angle68/zvel-1458 reaches(8175,5626,-26316). Its origin remains native body authority. |
| Rendering/UI regression |Animated-mask asymmetric stereo retains exact two-pass RGB/depth and callback counts. Existing UI=2 console/coverage/depth test and cold-menu console/resize test pass with attachment unset. |
| Builds/API validation |Native, optional XR and standalone builds pass; flat executable has no OpenXR loader link. Python/diff checks pass. Core validation is active without warnings/errors across all ten card cases, tracked multiplayer and the standalone12-frame multiview run. |

`tools/vr/smoke_weapon.py` accepts the cases `base`, `moved`, `rotated`, `head`,
`left`, `lost`, `resize`, `tint`, `save` and `nested`. The independent oracle uses
actual eye FOV/poses, the test's submitted remote hand pose, native captured
premultiplied RGBA and the queried raster subpixel grid (8 bits on this driver).
It tests complete images with a two-byte bound for cross-implementation
interpolation/rounding; renderer differential fixtures still use exact equality.
Nine decimal places in pose diagnostics avoid amplifying rounded input at card
edges. No game packets/shots, native angles or installed assets are injected.

Initial harness failures assumed a particular frame's cold-upload fallback,
looked for a validation debug line not enabled in game logging, used a broad HUD
coverage count that included the status bar, and attempted to serialize NumPy
booleans. Corrected checks use observed multiview readiness, actual validation
output, isolated weapon-source coverage and plain booleans. A continuous-edge
oracle using rounded poses also disagreed at one boundary pixel during head
motion; actual subpixel coverage and higher pose precision resolved it without
relaxing RGB limits. Failed experiments remain local under work/.

Bounded results are `../../../evidence/tracked-weapon-validation.json`; actual
final eye layers are `../../../evidence/tracked-weapon-stereo.png`. Visual QA
inspected the pistol independently of the head HUD in both eyes. A fresh
Astra/xhigh design request failed at the retained-thread limit; this slice has
main source/GPU verification and preceding Astra guidance, not a fresh
independent review.

This remains a foreground perspective ART card. World occlusion, solid gun
models, weapon-specific/two-hand/foot/face-action placement, full-pitch shot
agreement, physical muzzle/collision and authoritative hand-origin replication
are unfinished. Native body-origin firing is explicit temporary behavior.
Real headset optics/ergonomics/performance and the full multiplayer combat,
VR-host/two-VR, damage/frag/respawn/map-change/loss matrix remain open.


## Native hand-origin/full-vector RPG authority — 2026-10-16

`EDUKE32_XR_HAND_SHOTS=1` now enables the ordinary hardcoded RPG's independent
hand position/full physical direction, including native-server multiplayer.
This is an optional acknowledged movement tail, not a second pose service or
player simulation. Protocol/invariants and exact scope are in HAND_SHOTS.md.

The final native and XR builds pass, and only the latter links OpenXR. Fourteen
actual native-server/client cases and seven malformed-ENet cases pass under
private simulated Monado remote devices. Applicable XR cases require60 actual
world/HUD submissions, distinct eye layers, active core validation and no core
warnings/errors. The pre-extension flat binary at5749396 is used as the actual
legacy peer; changing only a reported version would not prove compatibility.

| Proof | Actual result |
|---|---|
| Open portal | Body XY1024,4096; server RPG origin1216,4173,-8109 in neighboring sector1. Angle69, xvel638, zvel-1434; native far-wall impact8175,5672,-24242. Independent physical-hand transform matches; live client RPG fields also match. |
| Blocked and glancing hand | Closed wall constrains origin1125,4149,-8672 in sector0; native RPG hits that wall. Glancing case ends at1136,4656,-8162 with native radius clearance, not behind the wall. |
| Steep and vertical |75° gives xvel167/zvel-9953;90° gives xvel0/zvel-10304. Native ceiling-collision kind is observed in sector1. Vertical pre-impact htbpos XY remains1216,4173. Native collision advances discretely and native Proj_GetOffset backs impact XY112 units; neither is rewritten to fit an ideal ray. |
| Left hand and translation | Actual selected left source passes. A second real RPG follows independently moved hand coordinates rather than body translation. |
| Reach and packet timeout | A3m pose cannot fire; held recovery cannot fire until release/repress. Pausing only the owned client lets native-clock expiry stop repeated server fire/ammo use; resumed held input remains blocked, then a new press fires. |
| Native damage/autoaim | Actual RPG collides with native target actor4; server native enemy health goes from positive to nonpositive and client receives death. Separate autoaim0/1 cases hold that preference at the shot boundary; native autoaim produces zvel-87 versus free-aim0, with normalized physical speed. No replacement damage code. |
| Pixel agreement | Actual card pose and both complete eye RGB arrays match independent projection of static server-constrained origins, within one byte in open/blocked cases (allowed maximum2). Both complete raw world-depth layers remain byte-identical. Glancing card is outside visible coverage, so its zero-error result alone is not a visible-card proof. |
| Legacy peers | Pre-extension native client moves/fires with native body origin and ammo. Pre-extension server receives base updates, never acknowledges the new capability; opt-in unsupported hand fire is suppressed and native movement continues. |
| Unnegotiated/malformed | One real unnegotiated95-byte update is rejected. Seven real bad updates exercise version, flags, direction, reach, size, channel and player identity. Each sentinel-position update is rejected before native prefix application; subsequent valid hand RPG origin/impact/client actor and eye checks pass. |
| Sparse inventory | Two actual XR peers join slots1 and2; slot1 disconnects via native F10 binding, leaving0,2. A native server CON ammo mutation reports36, and the actual slot2 client's ammo reports36. Movement/fire/release and60 stereo frames pass for both tested joins. |

Actual runtime failures drove two narrow native fixes. A cached player0 sprite
index8192 misclassified incoming server RPG8192 as player data, so server spawn
success initially hid missing client projectiles. Authoritative snapshot role
and player ID now restore the binding, retain native player prediction copying
only for actual players, and update same-stat sector links. Live client
EVENT_GAME observations prove the replicated RPG. Separately, the real sparse
fixture failed with server ammo36/client44 because inventory fields used record
ordinal; receiver fields now use the validated record player ID. Contiguous
slots had passed and were insufficient evidence for this bug.

Fixture corrections are retained in scratch evidence: CON actor indexing needs
a gamevar, EVENT_GAME excludes deleted/unlinked RPG scratch slots, initial
EVENT_EGS precedes native projectile target assignment, native fire defaults to
right Control, and native client-info restores autoaim after spawn. Tests now
observe actual compilation errors promptly, hold the requested autoaim setting
through native input, and wait for the first complete server sample after the
inventory mutation marker rather than a potentially stale pre-mutation sample.
No baseline CON/damage/impact policy was changed to make tests pass.

Post-change regressions: animated-mask multiview versus two-pass reference has
zero changed RGB pixels and exact nonconstant raw depth in both eyes; callback
counts14/112/14 match. HUD/console has60 actual projections, unchanged world
depth and native callbacks61/61/60/60. Cold-menu/console resize reaches800x600
with60 submissions and exact desktop/native UI equality. Prior non-hand tracked
aim passes all24 native-server orientation/impact/recovery/body/resize checks.
Shared standalone submits12 core-validated frames with one multiview draw each.
Python compilation, native/XR builds and diff checks pass. Existing baseline
allocator compiler warnings persist. The private runtime was stopped afterward.

Bounded results: `../../../evidence/hand-shot-validation.json`; visually inspected
actual final left/right layers: `../../../evidence/hand-shot-stereo.png`. The
image labels distinguish an open portal and blocked wall, and call the ART card
provisional. No raw operational logs/private configs or proprietary data files
are exported. The source commit is pinned in the evidence after integration.

Fresh explicitly selected Astra/xhigh follow-up could not start at retained
agent-thread capacity. This has prior verified senior architecture guidance and
main source/GPU/server checks, not a fresh independent implementation review.
Other weapons/custom projectiles, full-pitch world rendering, full single-pass
coverage, dynamic collision reconciliation, packet loss/reordering, PvP
frag/respawn/map changes, save/demo/camera behavior, haptics/settings and physical
headset/Windows/Quest qualification remain required. The full-port goal is active.


## Native full-vector hitscan and multiplayer readiness — 2026-10-16

The optional hand path now covers ordinary hardcoded pistol, shotgun, chaingun,
grow and RPG when the selected family/configured Shoots/actual tile agree.
One shared feature mapping also excludes custom projectile replacements from
hand-origin presentation. The hitscan adapter has one private resolved-sector/
ray context inside existing native helpers; input, CON, random sampling, impact,
damage and actor replication remain native. HAND_SHOTS.md records the physical
spread interpretation and protocol invariants.

A fresh explicitly selected Astra/xhigh senior design review verified source;
main checked its exact effective turn metadata before adopting it. It caught
accurate-probe success being distinct from autoaim correction, singular spread
math, forced-slope/postfire disagreement and presentation eligibility. A fresh
implementation-review request hit retained thread capacity; main verification
covers implementation and subsequent native fixes, without claiming another
independent review.

Twenty-two final hitscan cases pass under actual native dedicated server plus
simulated Monado XR client. Each requires actual60 world/HUD submissions,
distinct eye layers, active core validation, no core warning/error and explicit
hitscan feature acknowledgement on both peers. Native CON events and actual
impact sprites, ammo and damage are observed; shots are driven by real OpenXR
remote trigger actions. The controlled fixture equips weapons and sets spread
ranges, retaining owned GAME.CON firing/damage. It never injects a substitute
projectile, hit result, target health or growth state.

| Proof | Actual result |
|---|---|
| Portal origin | Pistol starts1216,4173,-8109 in neighboring sector1; actual ray15870,3373,-36481 hits8191,5655,-24145 on far wall5. Native CON shotspark has that impact. |
| Blocked/glancing | Common resolver constrains before the wall in sector0; blocked pistol starts1125,4149,-8672 and hits1151,4154,-8734. Native wall-hit rounding can end one Build unit inside the plane. Native decals are created. |
| Steep direct actor accuracy |75° free-aim pistol hits native actor4 at1549,4244,-28497; native target health decreases on server and client. The probe suppresses spread while preserving the full physical ray, rather than reconstructing clamped body pitch. |
| Native autoaim | Actual target4 correction changes the effective ray; native server/client health decreases in the final fixture. Native target/event selection remains; full-pitch target-selection policy is not newly qualified. |
| Vertical/spread | Straight-up pistol and seven-pellet shotgun hit the ceiling. Nonzero vertical shotgun dispersion has two independent horizontal axes and matches an independent analytic pole contract. Horizontal dispersion matches independent azimuth/slope arithmetic. Zero, one and INT_MAX ranges are finite and retain per-pellet native events. |
| Forced CON slope | An upward hand forced down by zshoot8192 hits floorZ0; a downward hand forced up by zshoot-8192 hits ceilingZ-32768. Native postfire sign follows the same effective ray. |
| Shootable switch | A real native far-wall DIPSWITCH changes162→163 on server and client after the hand-directed hit. This does not qualify every native switch/material interaction. |
| Damage/grow | Pistol, shotgun and chaingun produce actual native enemy hits/damage and client health updates. Grow uses repeated native trigger presses until native health exhaustion starts expansion; both peers report size larger than initial40. Actual owned client screenshots before/after show the enlarged enemy. Peer samples are at different ticks, not exact instantaneous size convergence. |
| Card pixels/depth | Applicable horizontal scenes compare both complete eye layers with an independent ray/plane/texture oracle using the static server-constrained origin, within two RGB bytes. Complete world-depth layers remain byte-identical. Card pivot/depth policy remain provisional. |
| Native helper reference | Actual pre-change03e6344 and current native dedicated/client pistol pairs, without XR/hand mode, hit8192,4096,-9952; prefire/range/autoaim events are1/1/1 and ammo use1 in both. A native DOFIRE fixture limits each run to one real shot. |

Two native networking defects required explicit investigation and narrow repairs:

- Different local bootstrap actors make server/client initial actor baselines
  unequal. Initial deltas retained two visible/self-owned APLAYER identities3
  and8193 for player1, alternating its binding every snapshot. Initial/rebase
  packets now explicitly encode all native actor fields, including zero, with
  the existing codec; later packets remain native deltas. Final hitscan cases
  require no binding oscillation. There is no new identity stream or actor
  format. Startup/rebase traffic increases and WAN/loss costs remain unqualified.
- Native pingcnt is one byte, but Net_WaitForServer compared it with its entry
  value using greater-than. The maximum-counter fixture stayed in that native
  wait despite real responses repeatedly wrapping below255; an owned debugger
  confirmed Net_WaitForServer/G_EnterLevel on the stack. The repair detects any
  counter change and sends at most one request per native simulation tick. The
  same maximum-counter test now reaches actual60-frame stereo gameplay and a
  real hit; every injected maximum-counter wait observes a smaller wrapped
  value, with request counts within one immediate request plus one per four
  elapsed native clock ticks. No synthetic readiness acknowledgement is supplied. This is bounded
  proof of that failure, not a claim that all possible startup stalls are solved.

Main final compatibility review also found that original capability1 promises
RPG/tail support only. Aware clients now optionally upgrade to mask3 after the
original mask1 request/ack. Server per-peer firing and client selected-weapon
availability use the same feature mapping. Actual pinned03e6344 RPG-only server
accepts hand RPGs while the new client's unsupported pistol fire is suppressed,
with native movement and60 stereo frames retained. An actual pre-upgrade
prototype client advertising only1 sends valid hand data to the new server;
server pistol impact still matches the independent native body ray, proving a
valid tail alone does not grant hitscan authority. New peers require mask3.
Older peers keep the original exchange; this does not qualify every historical
XR revision or repair an old peer's own readiness-counter bug.

Fourteen regression/compatibility groups pass: maximum-counter recovery, native
helper reference, RPG open/wall/vertical/timeout, pre-extension native server and
client, true sparse0,2 inventory/controller joins, exact animated-mask stereo,
and the four capability cases. Both sparse joins retain actual60 stereo/HUD
frames, native movement/fire/release and server/client inventory agreement.
Animated-mask RGB has zero changed pixels, raw nonconstant depth is exact in
both eyes, and native/two-pass/multiview callback counts match. Native and XR
builds, Python compilation and diff checks pass; only XR links OpenXR. Existing
baseline allocator warnings persist. The private Monado service is stopped
after tests.

Bounded evidence: `../../../evidence/hitscan-validation.json`; inspected actual
XR layers: `../../../evidence/hitscan-stereo.png`; actual owned client growth
comparison: `../../../evidence/hitscan-native-growth.png`. Raw debugger/session
logs, private configs and proprietary data files are not exported. Failed
fixture assumptions (initial event ordering, ideal wall coordinate, one-shot
grow and transient negative-health equality) are recorded as test corrections,
not engine behavior changes.

Remaining: other projectile/thrown/tripmine/melee families, remote tracked
muzzle presentation, dynamic collision reconciliation, overlapping-XY/YAX and
underwater tracer qualification, broader CON/switch/material policies, full-pitch
world rendering, full single-pass coverage, PvP frag/respawn, map/late-join/loss,
save/demo/camera behavior, comfort/haptics and hardware/platform qualification.
The full port remains active and unfinished.

## Freezer/shrinker native authority — 2026-10-16

Native and XR builds pass. Twelve current-build cases pass: each weapon's open,
closed-wall, glancing, steep, vertical and target-effect fixture. Every case
requires actual native join, 60 stereo world/HUD submissions and clean active
OpenXR core validation. Open cases require live client projectile fields matching
the server. Native speed644/768 is normalized physically, with freezer's native
-32 post-spawn Z bias retained. Portal origins resolve to1216,4173,-8109 in
sector1; blocked origins remain before the wall in sector0. Both-eye ART card
projection differs by at most1 channel value and leaves world depth unchanged.

Native freezer bounces decrement the bounce budget, reverse Z at the ceiling,
and a pure vertical bounce keeps X/Y1216,4173 and horizontal speed0. Actual enemy
freeze palette1 and shrink size below40 occur on server/client; snapshots are
captured after received state has reached rendered frames. Four historical
mask3 peer cases also passed before the user clarified that older-peer
compatibility is not required. These are optional evidence, not further gates.

Seven current-build regressions pass: RPG open/wall/vertical/expiry recovery,
steep-target hitscan, two sparse-slot joins with controller/inventory agreement,
and exact animated-mask single-pass color/depth/callback oracle. The retained
vertical RPG before-result shifted X1216→1104 at ceiling contact. The corrected
projectile and explosion both retain X/Y1216,4173 at the actual radius-damage
boundary. Other pitched native impact offsets are unchanged.

Bounded results/images are in sibling evidence/freeze-shrink-validation.json,
freeze-native-effect.png and shrink-native-effect.png. No raw operational logs
or owned game assets are included. Python syntax/diff checks pass; native build
retains existing compiler warnings. Fresh independent review was unavailable at
the retained thread limit; this is main source/runtime verification. Full-pitch
world coverage, remaining weapons and full current-build multiplayer combat,
respawn, map/late-join/loss and remote hand presentation remain unqualified.

## Projected world-space crosshair and private tests — 2026-10-16

Fifteen real native-server/XR-client crosshair cases pass under private simulated
Monado: base, constrained wall, independent head translation, occlusion, off,
lost hand, event cancellation, left aim, ceiling, floor, size100, green color,
real enemy actor, sloped ceiling and sloped floor. Actual native server firing
agrees with the crosshair's client-world origin and collision point in each
positive case. This is the central free-aim ray before autoaim/spread/CON shot
overrides and projectile arcs/bounces; dynamic reconciliation remains open.

Both eyes match an independent physical world-point projection within
6.6e-7 NDC. A separate CPU raster/linear-sampling/depth-test reference differs
from actual GPU output by at most1 channel value. Eye depth is byte-identical
before/after the marker. An opaque decoration that deliberately permits native
hitscan through it occludes all24 reticle coverage pixels in each eye; a
reference without depth testing would draw them. A moved head retains the same
server hit while changing eye projections. Native crosshair events execute once
per eligible native display frame, or zero when disabled. Native size100 and
actual green UI pixels prove size/color settings survive the spatial segment.

Wall/sector surfaces use native collision geometry/slopes to align the marker.
The first billboard version clipped into its own contact wall; the surface
alignment fixes that demonstrated issue. Native 320x200 scaling supplies the ART
anchor, so its physical aim point is independent of viewport/draw offsets.
The same existing menu multiview shader draws the segment once for both eyes,
with exact native projection/depth and LEQUAL; there is no new actor, renderer,
shader program, texture, frame owner or network stream.

Nine private regression groups pass: six native-ART weapon cases (rotated,
tint, lost, resize, save, nested), controller/native aim authority, HUD with
actual native callback reference, and the exact animated-mask stereo oracle.
Right/left/head body-aim tests also passed before isolation was requested.
The weapon composition oracle now starts its final-HUD check at the completed
spatial-crosshair boundary; its preceding weapon ray/plane oracle remains
independent. The stereo oracle retains exact RGB/raw depth and callback counts.
Native and XR builds, Python syntax and diff checks pass; the native executable
has no OpenXR dependency. Existing compiler warnings remain.

All15 final crosshair fixtures explicitly verify an unmapped XR drawable,
no mapped server window and no desktop focus on the test window. A first
isolation trial exposed the server's separate GTK startup log window; skipping
that path fixes it. The explicit test-only flag also disables fullscreen,
mouse capture and desktop gamma changes. Error dialogs stay in the test log;
an actual fixture compile error exercised that path. Subsequent captures come
from the acquired eye framebuffers, with no mapped desktop window needed.

Bounded numeric evidence and actual eye images are in sibling
`evidence/world-crosshair-validation.json` and `world-crosshair-stereo.png`.
Fresh independent review could not run at retained agent capacity; this is main
source/runtime verification. Full-pitch world visibility, broad custom camera,
model/material/CON behavior and current-build multiplayer combat/respawn/map/
loss qualification remain required for the full port.


## Native PvP death/respawn checkpoint — 2026-10-16

Two real current clients join the native dedicated DukeMatch server: a flat
client and an XR client with constrained hand shots. Both role assignments
passed before the GPU driver fault at09:05:21 local. These are bounded pistol
combat proofs; two independent VR players, VR hosting, map transitions and
loss/latency remain open. Older-peer compatibility is not required.

| Case | Actual result before driver fault |
|---|---|
| XR kills flat | Native pistol hits the actual victim sprite, reduces health100→0, and replicates native death. Killer frag1, victim deaths1, no self-frag on server and both clients. |
| Flat kills XR | Same native health/score/death convergence; XR keeps submitting actual distinct stereo layers while dead. |
| Native Use respawn | Both victim roles use actual native Open/Use and GAME.CON resetplayer. Server EVENT_RESETPLAYER increases once, health100/dead0 and scores converge; movement and firing resume with replicated ammo. No injected damage/health/reset/scores or post-respawn teleport. |
| XR held trigger through death/reset | Held fire produces no server hand ray, native fire bit or ammo consumption after respawn. Releasing and pressing again fires normally. |
| Late actual stereo evidence | XR-shooter death/respawn frames180/240; XR-victim180/300. These are acquired projection layers read through the existing completed HUD presentation, with distinct eye images and clean active core validation. |
| Private capture/input | Both clients remain unmapped with no desktop focus; dedicated server has no mapped game window. Native owned F12 captures and final GPU eye images are nonconstant. No map/raise/focus/global input. |
| Native spawn payload | Before: all three actual sends decoded old-position as(0,0,0), although native opos was nonzero. After: initial player1/player2 and victim respawn payloads match pos/opos. Existing packet size27 and receiver layout are retained. |
| Scores | Retained complete samples show maximum killer frag1 and victim death1 on every peer. No reproduced double-counting; no score-policy replacement was made. |

The original sender copied both vectors at offset2, overwriting position and
leaving the existing old-position field at14 unset. The correction writes the
second vector at byteOffset+sizeof(vec3_t). Before-fix gameplay recovered in the
observed native movement path, so the evidence proves an invalid payload, not a
permanent visible desync in that run. Its JSON does not prove post-respawn firing.

A fresh verified Astra/xhigh read-only review accepted the packet fix and caught
two harness issues. Score stability now rejects later regressions; held-fire
checks allow native ammo pickups. Two CPU regression tests pass. Final death
and recovery images must also differ, rejecting a frozen stereo pair. The
unqualified dual-runtime option and removed-fallback assertion were deleted.
See SENIOR_REVIEW.md for dispositions.

Native and XR source builds pass after restoring the unchanged renderer; native
linkage remains free of OpenXR. Final test-only harness changes (peer1 naming,
native gm startup barrier, stronger movement/score/held-fire
assertions and full-run core scan) require a healthy-driver rerun. Earlier
passing results must not be presented as execution of those later changes.

### Historical driver fault and testing hold (lifted below)

Kernel evidence shows NVIDIA Xid51 BAD_TSG, then Xid154 PF FLR and repeated
NV_ERR_RESET_REQUIRED. Cause is unresolved. A second private Monado failed
vkCreateDevice, and a later native client crashed writing through a null
persistent streaming map. A byte-identical unstripped relink identifies
polymost_bufferVert→polymost_drawpoly→G_DoLoadScreen at that native crash.
A trial mutable fallback was built, but its subsequent runtime attempts timed
out on the faulted driver; it was removed from production source and retained
only as an unqualified local patch. Those failures cannot qualify networking or
normal renderer behavior. No GPU reset or desktop/session changes were made.

At that checkpoint all owned game/Monado processes stopped and GPU tests were
held pending recovery. A hidden window still shares the user's GPU. The later
recovery/authorization and one-runtime qualification are recorded below; tests
still stop at the first kernel/graphics error. Independent two-VR qualification should use
separate recovered machines/runtimes rather than repeating the failing local
dual-service experiment.

Bounded records and actual pre-fault images: `../../../evidence/pvp-validation.json`
and `../../../evidence/pvp-xr-victim-death-stereo.png` /
`../../../evidence/pvp-xr-victim-respawn-stereo.png`. The full VR/SPS/multiplayer
goal remains active.

## Native map transitions and graphics recovery — 2026-10-16

This supersedes the graphics hold above. After the user's renewed permission,
a new boot, GPU Recovery Action=None and absence of new kernel faults were
verified before creating one private Monado runtime. Its actual Vulkan queue
priority is MEDIUM under no-new-privileges. A 12-frame hidden multiview probe
passed before game testing. These observations establish recovery for this
bounded run, not the cause of the earlier Xid51/154 fault.

Final strengthened PvP tests pass for both XR-shooter and XR-victim roles.
The recovered run also passes controller reconnect/sparse inventory, projected
crosshair occlusion (independent world-point/eye/depth oracle), and animated ART
mask single-pass differential checks: both eyes have zero changed pixels and
exact depth against the two-pass reference, with equal native callback counts.
Synthetic differential views remain offscreen; actual gameplay tests separately
submit located stereo views. Private window checks and core validation pass;
no new observed kernel GPU errors occurred between sequential cases.

### Native level changes

The existing dedicated stdin reader was called only from the non-dedicated
branch. Initial stdin experiments therefore did not dispatch a map command and
do not prove a map desync. After moving that existing call, a trailing native
echo receipt proved actual dispatch while the original multiplayer map stub
still did nothing. The final map/changelevel adapter uses native active settings,
startup and existing reliable USER_MAP/NEW_GAME messages. It sends the final
canonical filename, including empty, only after successful native startup.

Repeated transitions exposed two real ownership bugs. Reserved STAT_NETALLOC
slots retained previous-map tile data and entered both generic map-spawn passes;
an old E1L1 player slot579 could become player1 in a four-sprite test map, later
becoming a shot spark with yvel2595 while the player fell outside the world.
Those slots are now excluded at the spawn boundary. The client scratch list
also retained old-map indices; resetting its bookkeeping immediately after the
new board loads prevents the next snapshot from deleting unrelated new actors.
No serialization, generation protocol or transition state machine was added.

The CPU runner uses a USE_OPENGL=0 classic build, dummy SDL, private PID/proc/dev
namespace and owner-only SDL-event FIFOs. No NVIDIA/DRI devices, GPU libraries
or handles are visible. The sole SDL_GL_DeleteContext teardown symbol is inert
with its native null context; GL context creation and OpenXR instance references
are rejected. Native binds invoke the real client OSD handlers; native W/fire
inputs and native F12 software images establish behavior. Screenshot readers
wait for the native completion receipt emitted after file closure, avoiding
partially written PNGs.

| Gate | Result and limit |
|---|---|
| Dedicated server plus two native clients | Real assigned indices; active monster setting1 retained while staged menu setting0 differs. |
| Repeated user/built-in transitions | first→second→E1L1→filename-canonical E1L1→first→reserved built-in→first→canonical reserved map→first. Native fresh loads, floor markers and gameplay observed. |
| Ownership and world state | Every connected player checked on every observer for distinct valid APLAYER/STAT_PLAYER indices, matching yvel and valid sectors/Z; repeated after at least12 further native input ticks. |
| Controls | Both client roles move/fire; server input/positions/ammo and peer positions/ammo converge within256 horizontal Build units, with Z constrained to fixture geometry. Controls repeat after return, reserved map, replacement and malformed recovery. |
| Client authority / invalid requests | Both client map commands warn without changing maps. Missing map, zero/negative/overflow/suffix/arity/out-of-range level requests rejected. |
| Reconnect / empty host | Native quit/disconnect frees a slot; replacement controls current map. Host alone selects another map and the next joiner receives it. |
| Failed map | Malformed version rejected without instructing client reload; native startup has already reset server state and returns to menu. A subsequent valid request reloads both peers and resumes controls. No rollback promise. |
| CPU screenshots | Nonconstant native F12 framebuffers differ across maps. |
| Actual XR transitions | Initial small map→second→E1L1→small map: real native controls/ownership plus changing, distinct late stereo eye images at completed HUD frames180/300/420/540 in the first run. Held trigger is neutralized through reset until release/new press. |

Fresh Astra/xhigh source/design review was explicitly selected and effective
turn metadata independently verified. It accepted the narrow corrections and
required stronger persistent ownership, peer movement, world bounds and
malformed-to-valid gates; these were implemented. Temporary native collection
logging was removed. Native, XR and CPU builds pass. Existing upstream allocator
compiler warnings remain separate from these changes.

Bounded records and actual image files are in the sibling
`../../../evidence/native-levels-validation.json` and
`../../../evidence/recovered-gpu-validation.json`. These tests do not qualify
VR hosting, two independent VR clients, loss/WAN behavior, unrestricted mods,
all weapons/materials/cameras, other platforms or physical-headset comfort.
The full VR/SPS/multiplayer goal remains active.

## 2026-10-17 tracked pipebomb and single implementation review

One requested broad read-only **Astra/xhigh** review inspected snapshot5c62400
plus the pending pipebomb diff. Exact-turn model/effort was independently verified.
Its four findings and narrow adopted fixes are recorded in
[CODE_REVIEW_20261017.md](CODE_REVIEW_20261017.md). No additional broad review
was run. This is a qualified checkpoint, not full-port acceptance.

| Test | Actual evidence and limit |
|---|---|
| Holoduke native negative/positive | `work/holoduke-proof-s7iqvvqf/result.json` reproduces client binding to actual holo8192/owner-1. Corrected `work/holoduke-proof-3pvglrhh/result.json` passes13checks: real player3 stays bound through later snapshots, native movement/fire and actual F12 image. The first owner>=0 attempt was vacuous on unsigned wire data and failed; valid owner-index discrimination fixes it. |
| Terminal XR fallback | `work/xr-fallback-init.json` and `work/xr-fallback-world.json` each pass8checks. Real initialization failure / post-start opaque-render failure, then native keyboard throw, replicated ammo, remote explosion and target damage. Temporary live tracking loss remains fail-closed. Pending charge at terminal shutdown is not separately qualified. |
| Minimized mirror | `work/xr-minimized.json` passes6checks. Injected native SDL minimized/restored events into the owned hidden process; controller movement and actual distinct stereo submissions continue at frame180 and after restore. This is not an actual window-manager or physical-headset transition. |
| Known LOCAL reference change | `work/xr-reference-known.json` passes12checks. A live API layer supplies delayed standard event and matching real locate-pose basis transform (.75,0,-.4m / .6rad). Applied at changeTime; native body/eye poses stay unchanged; two authoritative physical hand throws have exactly matching origin/angle/velocity; new distinct stereo frame180 and clean core validation. |
| Unknown LOCAL reference change | `work/xr-reference-unknown.json` passes13checks. Same live coordinate change with poseValid0 during native charge: cancel frame/hold, ammo6, no bomb; held recovery stays blocked; release/new press yields exactly one hand throw/ammo5 and native client bomb. Eye/body continuity and actual later stereo pass. Physical runtime recentering remains unqualified. |
| CPU-native pipebomb reference | `work/pipebomb-native-reference/pipebomb-native-aw2irjvl/result.json`, `work/pipebomb-current-cpu.json`, `work/pipebomb-snapshot-cpu.json`:14checks each. Observed12-row native server/client early trajectory matches preserved pre-adapter binary; real remote detonation/damage still run. |
| Actual XR pipebomb matrix | `work/pipebomb-{open,timer,steep,wall,glancing,vertical,roll,lost,recover-release,reach,high-charge,down-charge}.json` pass. Real server insertion/one ammo, owner, client actor/trajectory, physical8° versus measured8.025° oblique flight, steep and storage bounds, elevated native roll-to-floor, timed/remote native kills/scores and late distinct stereo. |
| Cross-channel ordering | `work/pipebomb-ordering.json` passes the original delayed-observer proof. Actual player packets suppressed while several native mode2 actor updates arrive; no premature client explosion/health/knockback, then real native explosion and scores after intentional remote command. |
| Second throw coverage gap | `work/pipebomb-ordering-reuse.json` fails only the actual same-index assertion: native bomb8192 then8155. Both throws/ammo and actual client/observer explosions pass. Different indices are not reuse proof; do not call that extension green. Host-only geometry cancellation and arbitrary loss/WAN remain open. |

The native pipebomb failure was independently reproduced before its repair:
`work/pipebomb-xr/pipebomb-jrto93c5/result.json`. The client skipped commit frame11,
kept hbomb_on0, exploded a live host mode2 bomb and applied knockback that later
reached the host. Native server snapshots now carry hbomb_on/hold/rapid state
beside kickback, requiring **NETVERSION2 on every peer**. Only the client's
player-owned HEAVYHBOMB remote-command transition is gated; authoritative actor
mode3 still invokes native explosion logic. Native damage/timer/pickup is retained.

The reference test API layer is isolated under `tools/vr/`; it is not part of the
production runtime or a new game protocol. Build its shared object with C++17
and substitute the absolute library path in `reference_space_layer.json.in`.
Set `XR_API_LAYER_PATH` to that manifest directory plus the installed explicit
layer directory; the runner enables both test and core-validation layers. Its
marker supplies one delayed transform. Actual Monado projections are restored
to the underlying runtime coordinates at xrEndFrame. The initial runner parsing
failure remains in its lab; it does not establish a production defect.

Native/XR builds pass. Earlier private batches showed Recovery Action=None
and no new observed faults at their checks. A later kernel check found new
Xid69/32 at19:57:56, naming another game process; Recovery Action remained None.
This does not establish the cause. Main stopped its private Monado and all GPU
tests immediately on discovering them. No desktop focus/input or runtime
configuration was changed. Asset conversion/rendering
ran separately through software Blender and did not use this GPU queue.

The fresh CPU map matrix (`work/cpu-levels-review.json`) passes25checks and
XR-shooter PvP (`work/pvp-review-shooter.json`) passes24checks on the review-fix
build. XR-victim attempts retained two harness failures: next-frame wait8s too
short under a slow run, then a fixed60ms F12 tap missed between rendered frames.
The harness now allows a bounded25s next-capture wait and holds F12 only in its
owned hidden window until native completion, releasing it in finally.

The next full XR-victim run (`work/pvp-review-victim-input.json`) reached all
late stereo/respawn/control/score checks but failed held-fire input suppression:
one first post-reset server sample retained Fire, without ammo consumption or
a shot. The native reset previously cleared Enabled before filtering an
in-flight Use+Fire input. It now preserves Enabled-invalid and the existing
blocked latch only at P_ResetPlayer; broader join/disconnect/map reset semantics
remain unchanged. Final-source runtime proof is pending.

A separate bounded two-round CPU reuse probe observed8192 then8162 on both
peers with two actual native explosions (`work/pipebomb-reuse-u3bply9n/result.json`).
The worker initially labelled experiment completion as passed and overclaimed
infeasibility. Main corrected the harness: same-slot reuse is a required passing
condition and different slots are only an uncovered case, not impossibility
proof. Historical result is retained; **it does not qualify same-slot reuse**.

Final reset-source builds pass for native, XR and CPU.
`work/pvp-review-victim-final.json` passes all24checks, including **every** live
held interval input without Fire, no shots/ammo consumption, native Use respawn,
recovered movement/fire/ammo/scores and distinct changing real eye frames180/300.
The previous one-sample Fire negative is retained in the input result. This
closes the observed reset race; all-device loss/WAN is still unqualified.
CPU final SHA256:15f89b10d99d521b845db6d02ca7d4928dcae997d278a89d51ba3459b4b9f003.
The CPU25check map matrix and XR-shooter24check run precede only this final
respawn-mode preservation; flat reset remains identical. Reference/fallback/
minimize tests precede it too; their rendering/calibration source is unchanged.


## CPU-native Devastator continuation

[DEVASTATOR.md](DEVASTATOR.md) records the incremental adapter, actual native
negative cases (unsafe post-insert barrel offset and lost-burst ammo), the five
passing final scenarios, unchanged flat projectile/random-state comparison,
CPU pipebomb regression, and limits for very short-lived native actors. All
activity in this slice uses a GPU-denied CPU process namespace. Native/XR/CPU
builds compile; current Devastator graphics/model/headset behavior is unverified.
The earlier GPU hold remains in force; no Monado/GPU application was started.

Final native revision3 builds pass, with final-source CPU cases
`work/devastator-{flat,tracked,wall,vertical,loss}-net3.json`:77checks total,
including native F12 frames before/after firing in the tracked case.
`work/devastator-protocol3-rejection.json` additionally proves that the existing
authentication version guard rejects a real prior revision2 executable before
gameplay. Revision3 changes the feature1 promise to include Devastator; it adds
no packet fields. Older-peer compatibility is not required.

## CPU-native tracked tripmine continuation

[TRIPMINES.md](TRIPMINES.md) records the native press/commit adapter, unchanged
flat reference, actual hand-ray/closed-wall/steep-range behavior, native surface
and occupancy rejection, tracking loss and rejected-commit ammo refund/release
proof. Ten tracked placement cases pass108 checks. Flat placement/range passes15
checks and4 explicit pre-adapter comparisons. Native lifecycle tests pass on
tracked placements (21checks total), and flat current/reference each pass13.
Real beam crossing and timer expiry cause native damage and converged client
health. Current CPU Devastator17check and pipebomb14check regressions pass.

The native capability mask expands15 to31 with family bit16; wire layouts and
NETVERSION3 remain unchanged. Native, OpenXR and normal/special CPU builds pass.
All gameplay tests use the GPU-denied SDL-dummy/private FIFO environment;
actual native F12 shows the placed mine. GPU hold remains in force. This does
not qualify tripmine headset/model presentation, WAN/reordering, full-body
integration or complete SPS. Bounded results and binary hashes are saved in
sibling `outputs/evidence/tripmine-native-validation.json`.

## CPU-native melee and quick-kick continuation

[MELEE.md](MELEE.md) records native reference, minimal hand-ray adapter and
actual negative cases. `work/melee-hand-net4-{selected,quick,pitched,wall,far,vertical,vertical-far,loss,quick-loss,steroids}.json`
all pass on final revision4 source: native target damage/health convergence,
ammo, collision/physical reach, existing counters and recovery are observed.
The last steroids assertion observes a real bonus beyond unboosted knee damage;
it does not require a particular random damage draw or mitigation amount.
Native flat selected/quick/range cases pass and match pre-adapter impact/ammo
fields (`work/melee-native-net4.json`). EGS strength precedes random/bonus damage.

Retained quick-loss negative repeatedly queued counters before the input
filter, then caused two impacts on recovery. The shared-key handler now uses
the same readiness gate before starting quick-kick. No counter/protocol layer
is added. Actual mixed revision3 probe showed an old server firing a body kick
without feature32; NETVERSION4 now rejects that mix using native authentication
(`work/melee-protocol4-rejection.json`). Same capability/pose layouts, mask63.

Native/OpenXR/CPU/input builds pass (`work/build-*-melee-net4.log`). Devastator
loss and tripmine rejected-commit regressions pass on the same gameplay source
before only the final native version constant advanced3→4. Their evidence is
`work/devastator-melee-regression.json`, `work/tripmine-melee-regression.json`.
All tests are GPU-denied CPU/private input; actual OpenXR stick-click and current
model/headset behavior remain unqualified. Durable bounded results and hashes
are in sibling `outputs/evidence/melee-native-validation.json`.

## Private software OpenXR and completed art revision

[SOFTWARE_XR.md](SOFTWARE_XR.md) records the new GPU-denied private runtime lab.
Actual three-frame diagnostic multiview and60-frame Duke E1L1 rendering pass
using matching Mesa26.2.3 llvmpipe/LVP, with distinct eye readbacks and clean
client core validation. The final world run reports opaque60multiview,
masks59multiview/1two-pass and full59multiview. All owned processes were reaped;
hardware GPU devices were absent. A separate diagnostic-only Monado teardown
warning remains recorded. No OS driver installation, desktop input or runtime
default change occurred. This supersedes the earlier software-FBO limitation
for the tested configuration; full SPS/headset/model acceptance remains open.

[MODEL_ASSETS.md](MODEL_ASSETS.md) records the completed private fourteen-entry
Astra art revision: Duke678tri/256², weapons44–236tri/128²,28 structural models,
19 roundtrip samples,281 independently verified manifest hashes. Original v1
files are preserved. Eight weapons have rest-only geometry; controller fit,
runtime animation/body IK and model stereo rendering remain integration work.

The initial software multiplayer reticle timeout exposed native centering
overshoot after slow frames. [VIEW_CENTERING.md](VIEW_CENTERING.md) records the
narrow convergence correction and native reference proof. Final base and
occluded crosshair cases each pass13 checks using actual native revision4 peers,
real runtime poses and shots,60 world/HUD receipts and independent eye/depth
oracles. The visible marker matches both-eye projection within1 color unit;
world depth blocks all24 covered pixels per eye in the occluded case. Both
reticle rays exactly match the server's shot origin and impact. No renderer
coverage relaxation, new camera state or hardware GPU use was needed.

## Native tracked idle MD3 pistol

[MODEL_HAND_DESIGN.md](MODEL_HAND_DESIGN.md) records the focused Astra/xhigh
review and its adopted pre-mask native-renderer boundary. Base and nearer
translucent-wall cases render sixty actual world/HUD frames with native model
color/depth in both eyes and empty idle ART coverage. All 8,106/7,903 model
pixels receive the nearer translucent composition while retaining exact depth.
Independent muzzle projection error is below 7e-7 NDC; actual server shot origin
matches exactly and normalized native physical ray error is below 1.2e-5.
A separate 25-degree roll case qualifies three 5 cm basis offsets/scale below 3e-7 NDC.
Missing-skin/custom-weapon-handler cases retain native ART. Injected second-eye
failure ends an empty frame: failed serial exceeds last submitted serial and
there is no completed model receipt. Hardware GPU devices remain denied,
private drawables unmapped, client core validation clean and owned processes
reaped. The forced-shutdown case retains Monado's separate known
destroy-nonexistent-space teardown warning. A separate nonzero native world-model
fixture retains exact two-pass/candidate color/depth and callback counts 14/14/14; the model masks correctly
use sequential-eye fallback, with zero collection writes. Model SPS is not
claimed by that earlier increment. Durable results/hashes are sibling `evidence/hand-model-validation.json`.

## Opaque tracked MD3 shared-geometry SPS — 2026-10-17

The subsequent increment qualifies actual model multiview through the existing
native MD3 emission and ART transport. Fourteen final private software labs pass:
base, tracked roll, actual runtime asymmetric FOVs, fog, nearer translucent wall,
immediate mode, two surfaces, four pre-draw rejection/error cases, later-mask
retry, post-draw cancellation and existing unequal-coverage animated ART masks.
All wrappers verify hardware GPU denial, matching llvmpipe/LVP, observed clean
core validation and owned process cleanup. Native and XR builds pass.

The actual multiplayer native/SPS sessions compare both eyes' color and raw
depth exactly before/after the model and after masks. A same-frame native draw
on copied array targets additionally requires byte-identical frozen transform
inputs and zero color/depth tolerance. Collection leaves both actual eye layers
unchanged. One-surface replay shares 582 vertices once; the mechanical two-surface
fixture splits them into two shared draws. Post-submission failure cancels the
serial; earlier rejection retries native emission once. See MODEL_SPS.md for
review dispositions, actual counters and qualification limits. Durable results,
binary/source hashes and prior failed attempt locations are sibling
`evidence/model-sps-validation.json`. Full animated weapons/body integration,
world MD3 animation ownership, general model/material SPS and hardware/headset
performance remain open.


## Native stock World Tour flame adapter — 2026-10-17

Seven actual GPU-denied CPU server/client cases pass: native flat reference,
tracked, closed wall, vertical, loss/release, underwater and PRE cancellation.
Default weapon12 emits FIREBALL without a fixture Shoots override. Native flat
spawn fields, controlled damage/random state and ammo exactly match the saved
pre-adapter binary. Native and tracked target health converges1000→926 on both
peers. Invalid/held recovery does not fire or consume ammo; underwater/cancel
retain native ammo/event semantics. Vertical physical velocity is0/-13440;
resolved origins cross the portal or stay safely before the closed wall. Actual
primary snapshots apply on native clients; immediate wall hits are explicitly
excluded from transient snapshot guarantees.

Four final private software-XR labs pass: actual controller flame open/wall/
vertical and freezer open regression. Each submits sixty actual world/HUD
frames with core validation clean, GPU devices denied, matching llvmpipe/LVP,
unmapped private drawables/no focus, and owned Monado/Xvfb/child cleanup. Open
flame: origin(1216,4173,-8109), sector1, yaw69, xvel832/zvel-1870 at8-degree
physical pitch. Wall clamps to(1125,4149,-8672), sector0. Straight up is
xvel0/zvel-13440. Applied primary snapshot and native gravity are observed.
Native weapon card pose matches the independently resolved physical origin;
open/wall/flame/freezer pixel maxima are1 in both eyes and world depth is exact.
The actual captured native WT weapon/world image was inspected.

Initial flame/freezer runs failed only a card-boundary comparison (right maxima
12/64). Saved-artifact CPU analysis proved the independent oracle omitted
homogeneous triangle clipping before viewport/subpixel snapping. Corrected
clipping and top-left fill retain the original tolerance2 and independent
continuous-ray UV/sampling. Both original captures now compare at1/1, followed
by the four passing fresh runs; no renderer or pixel tolerance changed.

All native/XR/CPU/input builds pass; existing smmalloc compiler diagnostics
remain. Python compilation and whitespace checks pass. Read FLAMETHROWER.md;
durable run results, original failed attempts, source/binary hashes and oracle
recheck are sibling `evidence/flamethrower-validation.json`. No physical headset,
3D flame-weapon animation, general SPS/materials, WAN or full-port completion
is established by these bounded checks.
