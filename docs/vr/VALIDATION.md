# Verification record — updated 2026-10-16

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
