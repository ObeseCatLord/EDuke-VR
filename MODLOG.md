# EDuke32 VR development journal

## 2026-10-15 — reference and baseline

- User goal: full VR port of pinned EDuke32, RazeXR implementation reference, final single-pass stereo, working multiplayer. Current deliverable: investigated plan, Astra senior review, first implementation.
- EDuke32 source: r10669 ec5824db8, exact supplied archive. SHA256 f292e2c69f7f3453dd145d19ce1c114bd7136a8a9cf5b9b6641525fd53fa56c5. Baseline Git commit 72120ae.
- RazeXR reference: caa96be6d80f2ab74fce4b945d54eeda39c3fc20. Its current HEAD omits the Raze engine subtree; b9fb2bf removes it. Preserve history for renderer reference. Android wrapper implements two-layer swapchain/multiview attachments, but does not establish complete single-pass scene rendering.
- Route: incremental native source port, keep EDuke simulation, CON behavior, Polymost/Polymer, assets and ENet. Linux desktop OpenXR/Monado first available validation target; headset/platform preference requested asynchronously.
- Environment: Linux x86_64, SDL2 2.32.72; native make build succeeds; OpenXR loader/headers 1.1.60; Monado v25.1.0-847-g6b41c5b39; NVIDIA GL4.6 supports GL_OVR_multiview2 and ARB_shader_viewport_layer_array. Xvfb's llvmpipe is a different GL driver; use SDL_VIDEODRIVER=x11 explicitly for isolated game automation.
- Knowledge-base queries for EDuke32 and RazeXR returned no field note. um scan misclassified the installed game from an unrelated raze.pk3; source proves Build engine.
- Lab: owned World Tour assets used read-only; disposable -usecwd directories under work/lab; no installed game content modified. No save/profile migration required. Monado uses a private XDG_RUNTIME_DIR in work/runtime, not the user's active service. Xvfb :94 for game input tests.
- Baseline build: make -j8 eduke32, NETCODE defaults 1; succeeds with existing compiler warnings. Native level loads E1L1 from GRP-only -g path. Adding the whole World Tour directory loads loose CON with Linux case-sensitive /maps/E1L1.map mismatch; use GRP-only baseline.
- Native listen-server/client: -server -port 24583 -v1 -l1 -s1 and -connect 127.0.0.1:24583 both enter E1L1 after initial snapshot. Action/convergence/reconnect not yet proven. Dedicated baseline SIGSEGV before join; under investigation.
- Do not skip drawframe_do on shouldRender=false: input sampling lives there and tick input depends on g_frameJustDrawn. Do not loop G_DrawRooms per eye without handling CON events/interpolation/haptics/visibility side effects.
- Single-pass risk: Polymost screen-space domost clipping plus GL_ALWAYS opaque order cannot safely be reused from one eye or naively unioned. Need correctness oracle before optimization.
- Senior reviewer /root/senior_architecture launched explicitly gpt-6-astra/xhigh; effective model and effort verified from its own local turn metadata. No raw session telemetry exported.

## Next

Synthesize senior review into docs/vr/PLAN.md with dispositions and test gates; implement the approved first bounded runtime/render slice. Treat diagnostic success separately from game-world VR and multiplayer completion.

## Implemented and verified

- Added source/vr shared Runtime/standalone runner; strict desktop OVR multiview2, native GLX binding, exact eye projection submission, two-layer swapchain and pre-release pixel validation. Added opt-in diagnostic at SDL presentation, with XR shutdown before context/library teardown.
- Native and XR builds pass. XR objects default to obj-xr; native objects remain obj. Default→XR→default builds tested without cleaning; only XR-linked executable depends on libopenxr_loader.
- Standalone simulated Monado/null-compositor test submitted 12 single-pass frames. Native EDuke-context test submitted 60 with only first-frame readback and Khronos core validation enabled; no validation errors observed. Left/right images contain distinct geometry with ~3.6-pixel horizontal centroid difference in the inspected capture. This is diagnostic geometry, not Duke-world stereo.
- Native dedicated crash reproduced under GDB at RIP=0; retained assembly identifies uninitialized ExtGetTime in CONTROL_GetInput. G_ClearFIFO now skips only device polling for dedicated mode, retaining all state reset. New tools/vr/smoke_dedicated.py proves level entry and 8-second survival; does not claim multiplayer gameplay.
- Native listen/dedicated clients remain on Waiting for server after map load. Source trace identifies a ping barrier and readiness-order cycle: Net_ReceiveNewGame calls map entry before assigning ClientPlayerReady; map entry waits, while snapshots are discarded until ready. This alone does not prove the missing ping response. Do not blanket-bypass synchronization; next work needs exact packet/mode evidence and a join-path ordering fix.
- Xvfb llvmpipe advertises OVR but Monado swapchain multiview FBO is incomplete on that driver/runtime combination. NVIDIA actual EDuke context passes. No production fallback or driver-specific workaround added without diagnosis.
- Final bounded Astra/xhigh correctness review performed; all three findings adopted (GPU completion before swapchain destruction, config-isolated objects, tracking-invalid Idle). Recovery injection and physical headset tests remain open.
- Requested archive and RazeXR clone now live as sibling deliverables under outputs; archive checksum unchanged. No publication performed, no game data committed.

## 2026-10-15 — first actual room stereo and snapshot correction

- Corrected the earlier multiplayer diagnosis: the ping barrier does release. A causal wire trace found Net_SendWorldUpdate passed the address of a buffer pointer to ENet instead of the buffer. The one-line correction restores valid world-update packets and advancing revisions. All provisional readiness changes and temporary wire traces were removed. Listen/dedicated startup and dedicated reconnect pass; native client roof/gameplay input captures were inspected. Broader gameplay/convergence remains open.
- A fresh verified Astra/xhigh senior design review deleted two proposed visibility prepasses and avoided an opaque-engine snapshot. Implemented two native opaque renders, one stable sprite-union animation transaction, two masks renders reconstructed from ordered logical wall IDs. Per-eye sprite membership propagates to generated weapons/chat/shadows, and pristine animated slots are restored before each eye.
- Shared Runtime frame lifecycle now supports diagnostic, per-eye world rendering, layer readback and desktop mirroring. SDL retains context/session ownership. No alternate renderer, protocol or simulation was added.
- First actual 960x600-per-eye E1L1 world capture submitted 60 frames on simulated Monado/NVIDIA. Skyline/roof/masked fence/explosion appear in both layers with stereo separation. This is the two-pass correctness reference; final world single-pass remains required.
- Independent Astra/xhigh correctness review caught rigid-pose position/orientation disagreement, right-eye camera/aspect leakage to CON, camera preparation's debug clears, and stale transient sprites on failure. Adopted fixes and added bounded failure injection. Numeric mixed-pose/asymmetric projection check passes 1000 cases.
- Native/XR builds pass. Shared standalone 12-frame and native-context 60-frame multiview diagnostics still pass, and native post-diagnostic weapon/HUD/world image was inspected.
- Mixed native dedicated-server/XR-client join and replacement/reconnect now each submit 60 world frames and distinct eye readbacks. Initial harness timing began while the startup menu was open; it now skips the intro with native -nologo and waits for the existing ClientPlayerReady transition before timing. An explicit synchronization log supports that test without changing order. Movement image changes inspected; combat/map/convergence and broaderclientmatrix remain open.

- Final uninstrumented world 60-frame, both abort-boundary regressions and standalone 12-frame multiview/core-validation tests pass. All temporary frame/session traces removed. Final sources committed as 7060173 (world) and 589bf62 (snapshot/harness baseline); final harness startup timing refinement follows.
- Final harness uses -nologo, waits for level synchronization and lets the finite startup-menu fade finish before Escape. Final uninstrumented mixed join/reconnect and native listen gameplay tests pass; both XR joins retain 60-frame eye captures. Private Monado and owned games/Xvfb stopped.

## 2026-10-16 — restricted opaque world single-pass

- Fresh Astra/xhigh senior design review narrowed collection to typed already-resolved native inputs/final vertices, independent eye clipping/order and isolated replay state. Preserved native material resolution, GL_ALWAYS, persistent streaming and CON ownership; no renderer/protocol replacement.
- Verified actual EDuke-context native GLSL120 fragment linkage with OVRmultiview2 GLSL410 vertex. Added opt-in bounded indexed-ART opaque collection/replay and same-frame two-pass retry before animation; masks remain per eye.
- Added source-generated portal map and stock-CON counter wrapper, matched-target native capture and strict differential harness. Zero-IPD/native and asymmetric-IPD/two-pass comparisons pass exactly, with CON14/14/14. Unequal coverage preserves incompatible visibility values and uses eye-only packets with exact images.
- Fresh verified Astra/xhigh implementation review found replay-init error leakage/partial object publication. Adopted atomic initialization/owned error cleanup and tested one queued GL error + VBO failure; fallback and later replay pass without duplicate callbacks.
- Single-pass remains restricted: 18 paired calls for zero pose, 30 for rotated/asymmetric equal coverage; unequal coverage has 60 eye-only calls and no draw savings. Two CPU traversals/duplicate geometry remain; no performance claim.
- E1L1 sky explicitly falls back. Native dedicated/XR client join and reconnect still each produce 60 stereo frames/distinct layers with visible movement input. Combat/maps/convergence remain open. Native/XR builds pass. Full port goal active.

## 2026-10-16 — native sky / NPOT opaque multiview

- Read-only native-source investigation located flat-sky admission and the exact native sky-Z recursion. Reused all native panel/UV/material logic. Added scoped packet classification and color-mask preservation for the depth-only companion; ordinary masked geometry stays outside opaque qualification.
- Real LA sky tile91 has non-power-of-two height. Existing packet/native fragment already carry the four NPOT values, so the adapter now admits valid native NPOT state instead of adding shader/material logic.
- Added ceiling/floor sky variants with nonzero panning, explicit depth/panning cvars, exact raw per-layer depth capture and complete/nonconstant depth checks. Zero ceiling/depth/panning, rotated ceiling with depth/panning disabled, unequal floor/depth, and ordinary room regressions pass exact color/depth comparisons; callback counts match their appropriate native/two-pass references.
- Fresh explicitly verified Astra/xhigh correctness review found no actionable issue in the final bounded diff. Native and XR builds pass. Real E1L1 emits opaque multiview on 59/60 startup frames; one texture-mutation frame uses reference rendering before animation. Kept measured coverage visible rather than treating all 60 as paired.
- Native dedicated/XR client joins and reconnect retain 60 stereo frames with new opaque coverage reporting. Initial strict 59 minimum run measured 58/2 then 59/1 and failed; repeat measured 59/1 both and passed. Asset mutation also occurs later in gameplay; no all-frames/performance claim. Kept the failed threshold evidence and variable coverage explicit.
- Investigated the next ordinary mask phase in native engine sorting/drawpoly. Plan reuses the same collector with captured native alpha/blend/depth/color states. Preserve post-animation semantics: no new sort, no callback repeats, no opaque regeneration after CON on generic recovery. Fresh design review required before implementation.

## 2026-10-16 — native ordered mask/sprite multiview

- Fresh verified Astra/xhigh senior review approved one phased collector and native sort, adding explicit pre-draw/post-draw recovery and begin-before-camera preparation. MASK retains native alpha/blend/depth/color state, equal-depth groups and per-eye ordering; models/voxels/alternate direct paths reject before entry.
- Added same-frame native mask recovery from pristine once-animated sprites and wall IDs. No opaque rerender after CON. Partial mask replay errors consume the animated frame and stop XR. Collection snapshots prove no eye RGB/depth writes before commit.
- Exact native/two-pass RGB and depth fixtures pass for animated indexed ART masks, cutoff .25, translucent masked wall and sprites, equal-depth color/depth passes, asymmetric stereo and unequal coverage. CON counts14/112/14 stay identical. Late-right rejection, queued GLerror, pre-draw and post-first-draw replay faults pass their distinct recovery tests.
- Fresh Astra correctness review caught a redundant exit accounting reset unbinding restored samplers; deleted it. Separate verified Astra follow-up approved the final preflight skip and animated fixture. A speculative general animation-clock API was deferred for lack of a demonstrated drift path.
- Actual E1L1 final first60frames: opaque59, masks58, complete world multiview58. Mixed native dedicated/XR initial join and reconnect each render60frames with59complete multiview frames and distinct eye layers; owned movement input visibly changes gameplay. Streaming/reference phases remain and broader multiplayer/headset/controller gates are still open.
- Native/XR full builds and Python/diff checks pass. No protocol or simulation change in this slice. Full VR goal remains active.

## 2026-10-16 — OpenXR controller actions into native gameplay

- One OpenXR action set with simple/Touch/Index/WMR profile suggestions, physical action activity, predicted-time grip/aim spaces and lifecycle cleanup. Index remote-device simulation supplies actual runtime actions; other profiles remain untested on hardware.
- Native control/menu snapshot merges preserve existing button clearing, repeat, analog settings, CON and unchanged network input_t. Frame acquisition/input now happens once in both game and title/demo loops; auxiliary room draws cannot acquire another frame. Session generation checks prevent stale input/frame use after shutdown.
- Fresh verified Astra/xhigh design review rejected mouse-driven snap turning, caught the separate title/demo owner and required runtime focus rather than desktop focus. Smooth turn uses native joystick units. Implementation review prompted earlier demo frame closure and LastSeenInput activity marking.
- Real simulated-controller gameplay, title menus, action deactivation/reconnect, private runtime focus/IO transitions and native video reset pass. Native dedicated server independently observes movement/fire/ammo/release for initial and replacement XR clients using their actual assigned slots.
- Native/XR builds, exact animated-mask stereo color/depth/CON regression and 12-frame core-validated standalone multiview pass. Actual headset UI/tracked aiming/haptics/full render and multiplayer matrices remain required. Full VR goal stays active.
