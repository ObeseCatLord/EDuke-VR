# EDuke32 VR port plan

Status: experimental Linux OpenXR port with bounded ART multiview, native controller input and bounded native weapon/HUD/menu presentation; **not a completed VR port**. Updated 2026-10-18. The requested endpoint remains full VR, single-pass stereo and working multiplayer. This implementation begins the work; it does not redefine completion as a diagnostic or flat screen in a headset.

## Current implementation checkpoint

- Native indexed voxel masks now use the existing ordered eye-owned world packets. Exact native/SPS color and depth pass for zero/stereo/unequal poses, flip and palette/shade, cold/pre-rejection fallback and post-draw cancellation. Actual AA still has0/60 mask multiview frames: three large voxel props plus ART consume209,796 vertices and the next requires69,930, exceeding the262,144 per-eye collection limit. Measure total demand and compare a bounded cap adjustment with native indexed geometry reuse before changing storage. See AA_VOXEL_SPS.md for verified Astra design/code review dispositions and evidence.

- Submitted-frame mounted pistol/holding-hand collision and recovery pass for both aim hands, including same-root world reticle, native/SPS color/depth and actual paired replay. See PISTOL_MOUNT.md. AA truecolor skyboxes now reuse the existing world packets with native per-packet fog. Exact three-pose color/depth and meaningful fault/fallback controls pass; production AA opaque rendering advances to59/60 multiview frames. See AA_SKYBOX_SPS.md for that checkpoint's qualification and reviews; the subsequent voxel increment is above.
- Runtime foundation and actual EDuke-context single-pass diagnostic pass.
- First ordinary Polymost room renders to two exact XR eye layers using a two-pass reference transaction; 60-frame E1L1 captures pass.
- The native world snapshot payload bug is corrected. A native dedicated server plus XR client passes join and replacement/reconnect, with 60 stereo frames/readbacks per join and visible gameplay input changes.
- Independent Astra/xhigh design and code reviews completed; their concrete fixes and tests are recorded in SENIOR_REVIEW.md and VALIDATION.md.
- Strict matched-target zero-IPD/native pixel and callback equivalence passes. A bounded indexed-ART opaque multiview path also matches the two-pass reference with deterministic nonzero IPD, asymmetric FOV and pitch/yaw/roll; unequal coverage and initialization-error recovery pass.
- Native indexed-ART ceiling/floor sky, sky depth-only companions and NPOT shader emulation now pass exact color/depth fixtures. E1L1 uses multiview for 59 of its first 60 opaque frames; one cold texture upload safely retries the reference.
- Indexed ART masks/sprites now share the multiview transport while preserving native transparency and equal-depth group order. Exact RGB/depth, animated ART/alpha cutoff and recovery fixtures pass.
- OpenXR actions now merge into native controls and menus once per logical frame, including the title/demo loop. Real Monado remote actions pass movement/fire/release, controller reactivation, focus and native video-reset checks. Native dedicated server observations confirm controller movement/fire/ammo/release on both original and replacement joins. Native `input_t` and network packets remain unchanged. Tracked aim, haptics, settings and actual headset ergonomics remain required.
- Opt-in opaque cold-menu/console presentation now renders native UI once to its own target and submits a head-relative multiview plane. Actual 60-frame captures, desktop equality, temporary tracking recovery, viewport preservation, console/resize and transition to native stereo gameplay pass. This does not cover transparent HUD or in-game menu effects.
- Native ART weapon/HUD/in-game-menu capture now extends that same target with premultiplied coverage over the existing stereo world (`EDUKE32_XR_UI=2`). Actual eye/color/depth/coverage, full-eye native tint/dim, save-thumbnail cancellation, native callback reference and resize tests pass. This is a provisional 2D weapon plane, not tracked weapon aim or full native UI/material coverage.
- Opt-in tracked orientation now feeds native authoritative aim from right/left controller or actual HMD VIEW pose, with body/view separation and projected native crosshair. Real native-server RPG direction/impact, pose recovery, pole/wrap/body movement and session-recreation proofs pass. Native wire format and shot origin remain unchanged in this slice; it does not complete tracked weapon placement/origins.
- Controller-attached native ART now reuses the existing capture texture in sequential weapon/HUD segments (`EDUKE32_XR_WEAPON=1`). Both eye images pass an independent projection/composition oracle across ten cases, including pose loss, resize and nested weapon-scope presentation. This is a provisional foreground card, not physical hand-origin firing.
- Opt-in ordinary RPG hand origins/full-vector shots now replicate through a negotiated native movement-update tail. Actual native server/client portal, obstruction, vertical projectile, enemy damage, expiry/release and legacy compatibility tests pass. Runtime proof also exposed and corrected native projectile/player binding and sparse-slot inventory replication bugs. This was the RPG-only authority checkpoint; the hitscan expansion follows below in HAND_SHOTS.md.
- Ordinary pistol/shotgun/chaingun/grow now extend the same hand authority at native hitscan helpers, with one private sector/ray context, native events/damage and a bounded full-pitch spread mapping. A fresh verified Astra/xhigh design review caught accurate-probe/autoaim overloading, singular spread math, forced-slope postfire disagreement and custom-projectile presentation eligibility. Initial/rebase actor snapshots now supply complete native fields to eliminate differing bootstrap baselines; later packets remain native deltas. Native readiness handles byte wrap and bounds ping requests. An optional mask3 upgrade distinguishes hitscan support from the original mask1 RPG promise.
- Native dedicated + current flat/XR clients pass pistol damage, kill, converged scores, Use respawn and recovered movement/fire in both roles. The final strengthened harness is now qualified after graphics recovery, including the VR held-trigger gate.
- Dedicated stdin now dispatches native console commands. Native multiplayer map/changelevel handlers reuse active settings and existing reliable messages. Repeated user/built-in/canonical maps, reconnect, empty-host late join, invalid requests and malformed-to-valid recovery pass the GPU-denied CPU matrix. Actual XR map transitions pass native controls, player-sprite ownership and fresh submitted stereo images; held fire is suppressed across reset until release/new press. Native reserved-slot spawning and scratch-list lifetime bugs were fixed at their existing load boundaries.
- Graphics recovery was verified after a reboot and the user's renewed authorization. One private Monado runtime with MEDIUM queue priority passes bounded sequential PvP/controller/crosshair/exact-SPS/map tests without new observed driver faults. This does not establish the earlier fault's cause. Keep one runtime, private windows and stop-on-error checks.
- Next implementation work: remaining projectile/thrown/melee families, remote hand/muzzle presentation, native full-pitch target selection and mod policies, VR host/two independent VR clients/WAN-loss qualification, unrestricted tracked visibility, remaining material/draw families and platforms. The full goal remains active.

## Source and behavioral reference

Port the requested EDuke32 r10669 ec5824db8 source. Keep its simulation, CON language/events, asset loaders, renderer behavior, save data, and ENet protocol. RazeXR is the VR implementation reference, pinned at caa96be6d80f2ab74fce4b945d54eeda39c3fc20. See PROVENANCE.md for retrieval/checksum and SENIOR_REVIEW.md for the verified Astra/xhigh review and dispositions.

RazeXR HEAD contains Android/OpenXR integration but removed its Raze engine source in b9fb2bf. Its history remains available. The current wrapper supplies useful two-layer swapchain, session, action and haptic concepts; it is not a complete buildable scene renderer to transplant. Its native binding is Android/EGL/GLES and its optional Meta/Pico extensions are not portable requirements. Historical engine integration has a two-eye rendering/composition loop; current attachment code alone does not prove correct single-pass world rendering. Exact located eye poses/FOV, rather than its combined FOV/shared head pose, are the projection reference.

Initial executable validation target is Linux desktop OpenXR/SDL2/GLX using available Monado and owned Duke content. The eventual platform priority is still open to the user's headset preference. Windows OpenXR/WGL and Quest Android/EGL/GLES are later native binding targets, not a reason to rewrite the engine or add a platform service now. No headset-comfort claim can be made from simulation alone.

## Verified baseline and uncertainties

| Area | Evidence | Consequence |
|---|---|---|
| Native build | Default GNU Make build succeeds, NETCODE defaults to 1 | Preserve desktop build and network-enabled builds; keep XR optional. |
| Native gameplay | GRP-only owned World Tour content loads E1L1 | Use this baseline; loose WT CON/map filenames have a Linux case mismatch. Do not alter installed data. |
| Native LAN | A wire trace found malformed snapshot payloads despite successful ping synchronization; a minimal pointer correction passes native/mixed startup and reconnect checks | Loading logs/ping success do not establish gameplay. Keep movement/combat/map change/reconnect as separate gates. |
| Dedicated mode | Native baseline crashes at null control timer callback during map-entry input flush | Narrowly skip device polling when dedicated; retain all FIFO reset and verify with real clients. |
| Graphics | Actual NVIDIA desktop GL4.6 advertises OVR multiview2; Xvfb uses llvmpipe | Probe each actual context. Do not infer extension support from another display/driver. |
| OpenXR | Private simulated Monado creates HMD/controllers and GL swapchains | Null compositor is lifecycle/allocation evidence, not visible headset/world correctness. |
| Polymost | CPU camera-dependent projected clipping, domost occlusion and GL_ALWAYS opaque ordering | Two projection matrices alone cannot produce correct stereo. |
| Game draw path | Input, CON effects, interpolation, sprite animation, haptics and persistent visibility changes live in draw paths | Define a logical frame transaction before adding eye loops or skipping XR frames. |

## Architecture decision

Choose an incremental native adapter. A small OpenXR backend consumes EDuke's existing SDL-created compatibility GL context, owns XR resources, and tears them down before the context. Rendering and game code retain their existing responsibilities. Desktop mode remains the default. No general rendering thread, new service/protocol, second simulation, new material system, or copied CON VM is planned.

Compared alternatives:

| Approach | Reusable pieces | Demonstrated incompatibility / cost | Decision |
|---|---|---|---|
| Native OpenXR adapter + incremental renderer changes | SDL lifecycle, game/CON/ENet, assets, Polymost | New native XR binding; stereo rendering must address CPU clipping and draw side effects | Chosen, smallest compatibility surface. |
| Drop RazeXR/entire Raze renderer into EDuke | OpenXR concepts only immediately reusable | Current engine absent; different rendering/material architecture, Android assumptions, event/simulation integration would need replacement | Rejected as initial route. |
| Change Polymost projection and broadcast center-eye output | Existing GPU shader path | Source proves eye-dependent occlusion/geometry already removed on CPU | Rejected as a correctness assumption. |
| Replace Polymost with a new world-space renderer | Geometry/data could be reused | No failed bounded adapter experiment yet; duplicates visibility/material/model policy and expands mod compatibility work | Deferred unless evidence requires it. |
| Change opaque depth policy globally | Current geometry | GL_ALWAYS is part of native opaque ordering; global LEQUAL changes may reveal hidden surfaces/sky regressions | Not justified. |

For single-pass GPU stereo, retain independent eye visibility until evidence allows reuse. A single CPU visibility traversal is not an additional requirement. The bounded prototype pairs already-resolved compatible packet heads with eye-specific final vertices and multiview submission; it preserves each eye's ordering. Exact portal, native sky and indexed-mask fixture comparisons pass; remaining material/draw families and unrestricted camera coverage still need qualification. This is an experiment, not a promised production algorithm. If it becomes a full command recorder, a second visibility engine, or repeated material/state repair, stop and reopen the architecture with evidence and deletion opportunities.

## Logical stereo frame contract

- Locate both views at one predicted display time. Both eye images correspond to the same state and interpolation fraction. Submit exactly those poses/FOVs.
- Once per logical game frame: gather input, dispatch top-level display events, set/restore interpolation, advance UI and persistent display effects, update frame bookkeeping and sound, complete presentation. Existing mirror/other logical-camera passes retain their intentional event ordering.
- Per eye: camera transform/asymmetric projection, room/sector lookup, native visibility/occlusion, transient sprite/mask lists and rendering. Never run `drawframe_do` twice. `G_DrawRooms` also needs refactoring before reuse because it has side effects.
- Preserve script-defined camera/display semantics explicitly. Vanilla proof precedes claims for arbitrary CON mods. Do not silently execute camera-sensitive ANIMATESPRITES effects twice or cache arbitrary script results without defining their semantics.
- Input and network processing continue when XR is unfocused/inactive or shouldRender=false. Current `P_GetInput` and `g_frameJustDrawn` coupling must be deliberately separated before render eligibility can suppress native drawing. Neutralize unavailable controller state to avoid stuck fire/movement.
- Main-thread ownership first. Measure active/inactive `xrWaitFrame` behavior before introducing any scheduling layer. Do not busy-wait for an inactive session, and do not hold packet/snapshot waits behind XR readiness.

## Milestones and acceptance gates

Milestones are ordered to expose architectural failures early. A completed substep is not proof that later gates pass. Estimates below describe scope, not a delivery date; world rendering and multiplayer behavior must set the schedule.

### 0. Reproducible native reference

Build pinned source, preserve pristine import commit, isolate configs/caches/screenshots and read owned assets without changing installation. Confirm native level load. Establish listen-server and dedicated-server behavior before XR; fix demonstrated native blockers narrowly. Add repeatable launch/join/reconnect checks with retained local evidence. Record upstream warnings separately.

Gate: two clients join a native server, map loads, actions converge, disconnect/reconnect works; headless/dedicated failures are identified rather than hidden behind the listen server. This gate remains partly open until the action matrix passes.

### 1a. Runtime / stereo target substep — current implementation

Add optional USE_OPENXR=1 Linux build. Create instance, query extension/graphics requirements, bind existing SDL GLX context, create session and local space, negotiate opaque stereo views and supported color format, allocate two-layer swapchain and private depth/FBO resources. Handle READY/STOPPING/loss/exit, shouldRender, acquisition/wait/release and error cleanup. Require actual-context OVR multiview2 function and shader/FBO proof.

A small diagnostic draws world-fixed geometry with two exact eye transforms in one multiview draw. Validate both actual texture layers before release and optionally save images. The same backend runs in a standalone harness and, explicitly opted in, on the EDuke presentation boundary. Restore all touched GL state on success/error so Build's cached state stays valid. Shut down XR before context teardown. Unsupported contexts fail explicitly; flat rendering remains usable.

Gate: actual EDuke-context single-pass diagnostic, distinct nonempty per-eye pixels, exact view submission, native rendering before/after, successful cleanup/reinitialization, useful unsupported/error reporting. Simulated/null-compositor results must be labeled accurately. No world-VR claim.

### 1b. First game-rendering milestone

Separate the narrow once-per-frame preparation/finalization from view rendering, without duplicating the draw routine. First preserve zero-IPD identical-eye behavior and CON event counts. Add runtime camera transforms, world scale, eye offsets and full yaw/pitch/roll; convert Build's different horizontal/vertical units deliberately. Check eye sector and collision constraints rather than walking camera positions blindly through walls.

Use independent native eye render targets as the correctness oracle. Match asymmetric XR projections; do not approximate a symmetric FOV. Render a real loaded room and sprite, native keyboard/mouse input, and tracked head motion. Keep 2D menus/HUD in a separately defined plane/layer with readable depth, not duplicate game-frame UI advancement.

Gate: side-by-side eye captures and visible compositor show correct depth/parallax at a portal edge; zero-IPD pixels and persistent state/event counts match flat reference. Native gameplay and network input continue during non-rendering XR states.

### 2. Tracked input and gameplay authority

Adapt RazeXR action concepts to OpenXR action sets/profiles: grip/aim poses, trigger/use/jump/crouch/menu/recenter, sticks, handedness, and haptics. Start with available simple controllers and then real target profiles. Preserve native keyboard/mouse fallback and bindings. Add snap/smooth turn, controller/head-oriented movement, seated/standing/recenter and height/scale choices. Validate lost focus and action deactivation.

Map inputs into existing `input_t`; preserve authoritative aim/origin/collision. The reticle/weapon must show the direction the server actually fires. Freely tracked hand-origin hitscan or physical melee is not achieved by a visual gun pose; specify and replicate any such gameplay change before presenting it as authoritative. Keep roomscale view offset bounded by collision; decide translation vs body movement from user-observable tests.

Gate: correct controls and haptics, no stuck inputs after focus/session loss, weapon direction agrees with hit results on both server and remote clients. Comfort defaults need real headset validation.

### 3. Single-pass world rendering

Prove one bounded opaque wall/floor draw family against the two-pass oracle. Native multiview target uses two-layer color/depth, a view-indexed shader, and one GPU submission path for both eyes. Preserve palette/shade/fog, per-eye clipping/ownership, native depth/order and shader variants. Record actual draw calls and GPU/CPU time; do not describe repeated eye renders or copying one image to two layers as single-pass stereo.

Then extend masked walls, sprites, models, voxels, translucent geometry and material/detail/glow variants. Assess existing Polymost1 versus optional Polymost2 seams from actual proof; do not enable Polymost2 globally merely because it has explicit uniforms. Keep the correctness oracle available for differential capture while the optimized path develops.

Gate: both eyes match the oracle at occluding portal edges and near geometry, no one-eye holes, exact layer indexing. Captures establish single-pass GPU behavior and honest CPU visibility cost. Report fallback modes explicitly. Final completion requires the selected production world path to satisfy single-pass, not only the diagnostic.

Mask-phase implementation constraint: reuse the same typed transport/program and native per-eye partition/sort/interleave. Capture the native alpha/blend/depth/color state instead of adding a new sorter or material policy. Collection after CON animation must produce no committed mask pixels before qualification; direct model/voxel/alternate paths need explicit reject-and-skip coverage or isolated targets. After partial mask replay failure, consume the logical frame and submit empty as current post-animation failure handling does. Do not regenerate opaque geometry after CON as a generic recovery: scripts may have changed the world since its reference opaque pass. This boundary has now passed a fresh Astra design review and implementation/follow-up reviews; dispositions and validation are recorded separately. Future direct draw families must prove the same no-write/recovery contract before joining it.

### 4. Full engine/game presentation coverage

Mirrors and their event ordering; YAX room-over-room; water/warps/viewscreens; sky/parallax; all sprite orientations, clipping and transparency; models/voxels/HRP where supported; weapons, crosshair, HUD/inventory, map, menus, console, loading/cutscenes, palette fades, screenshots/save thumbnails, death/camera effects and aspect changes. Decide unsupported renderer configurations from evidence, not silent renderer replacement. Polymer is preserved for flat mode; VR Polymer support requires a separate compatibility proof before promising parity.

Gate: a recorded matrix for every logical camera/draw family and regression maps, plus game progression through representative episodes. Unknown/unsupported mod features are listed precisely.

### 5. Multiplayer qualification — carried through every milestone

Keep NETCODE=1 and reuse EDuke32's built-in ENet server, input simulation and snapshot authority. No new connection layer. Test current-build flat/flat, dedicated/VR, VR host/flat and two VR clients. Dedicated server must run without an XR runtime. User clarification on 2026-10-16: older-peer compatibility is not required; historical peer testing is optional evidence, not a release gate. Existing packet sizes/capability exchange remain where already implemented, but future work need not preserve old-build interoperability. Cosmetic remote head/hand poses need bounded update rate/payload and must not silently change gameplay origin/aim.

Matrix: join/initial snapshot, spawn/movement/jump/crouch/use, weapon switch/fire/damage/frag, chat, death/respawn, level vote/change, late join, reconnect, password rejection; multiple peers, loss/latency, XR focus/STOPPING/loss while connected. Verify authoritative position/aim/action convergence, tick progress and protocol acceptance, not just UDP counters. Keep save/load/demo compatibility tests where the native mode supports them.

Gate: actual mixed-client gameplay with evidence; no input starvation or double simulation from XR frame rate; no permanent snapshot waits introduced by XR lifecycle.

### 6. Platform and release validation

Add WGL binding for Windows PC OpenXR and/or Android EGL/GLES binding for Quest according to headset priority. Reuse runtime semantics; isolate only demonstrated native-binding differences. Reassess mobile GL extension, render target formats, depth, precision, performance, loader/activity lifecycle and controller profiles. Android is not a flag on the Linux GLX implementation.

Gate: target headset visual/comfort/performance tests, real multiplayer with two devices, install/package instructions, retained licenses/credits and source provenance; no proprietary game data. Record frame-time distribution, reprojection/motion behavior and recommended settings. A simulator cannot close headset optics/controller ergonomics/comfort or sustained mobile performance.

## Verification ladder and stopping rules

1. Native build and level, then unchanged desktop rendering with XR disabled.
2. Native listen/dedicated joins and authoritative actions before blaming XR.
3. Shared diagnostic: standalone and actual EDuke context, array-layer pixel readback, native rendering after cleanup.
4. Real compositor screenshots/recording; null compositor only for lifecycle/pixel-allocation tests.
5. Stereo room oracle including zero-IPD/event-count proof, then full projection/position tests.
6. Single-pass differential portal maps, then complete draw-family matrix and mixed-client actions.
7. Real hardware on each supported platform before release claims.

A build, a green counter or a diagnostic triangle is not game-world VR proof. If a failure repeats three times, retain evidence and change the experiment. If the adapter grows into adjacent-system replacements, duplicate state/policy, or repeated cross-layer fixes, reopen the design and seek simplification before expanding. No completion claim until the user's full VR, single-pass and multiplayer behavior gates pass.

### Next presentation checkpoint (senior-reviewed)

Use the existing projection array and native UI, beginning with opaque cold
menus/console under an opt-in flag. Capture native content once, arm only the
logical owner's final swap, draw one head-relative multiview plane, mirror the
native capture and end that same acquired frame. Cancel before auxiliary room
draws, mode/extent changes, nested swaps, skipped presentation or shutdown.
Current world submission remains unchanged during this first checkpoint.

Then extend to native weapon/HUD over the stereo world. That extension requires
source-over coverage alpha, full-eye tint/dimming at its original order, save
thumbnail isolation, distinct-right-world and depth preservation, and native
callback reference comparisons. A finite panel alone cannot reproduce a full-eye
damage flash. Custom destination-dependent UI blending and pre-world script
overlays remain explicit compatibility decisions. Do not grow a general command
recorder, material resolver or second XR lifecycle to hide those gaps.

## Controller weapon / hand-origin authority follow-through

The controller attachment slice reuses native `P_DisplayWeapon` and one UI
texture sequentially: preceding UI → head panel, weapon ART → selected aim pose,
then following HUD → head panel. It adds no swapchain, renderer or player
simulation. The native animation/event/palette path remains the source. Face
spit and scuba stay head-relative. This is an opt-in perspective ART card with a
provisional grip pivot and foreground-depth policy, not a solid gun model or a
physical muzzle. Full pitch, per-weapon pivots/two-hand behavior and collision
remain required.

The initial authority proof is now implemented for the ordinary hardcoded RPG.
A globally versioned movement rewrite was compared with a negotiated extension:
the latter preserves the existing 81-byte client prefix, native input_t and ENet
simulation, while carrying a bounded 14-byte hand origin/direction sample in the
same update as fire. A separate pose stream was rejected because it could pair
fire with another sample. A reliable optional capability on existing CHAN_MISC
keeps non-capable peers on the base update. See HAND_SHOTS.md for exact format.

The common native module validates two-metre reach and direction, expires samples
on the existing clock, gates recovery until release, traces the body-to-hand path,
resolves sectors across portals and applies native radius clearance. Server and
local card preview share that constraint; neither moves the body. The initial
vertical proof is actual server RPG spawn/flight/impact and native client actor
replication, plus native enemy damage/death, rather than pose counters alone.
The card's actual two-eye pixels match an independent projection of the static
server-constrained origin. Full-pitch projectile direction bypasses the native
horizon cap only for this opt-in RPG; the world renderer's full-pitch gate stays
open.

Two demonstrated native incompatibilities required narrow fixes: stale cached
player sprite indices misclassified an incoming RPG as player data, and server
inventory records were applied by ordinal rather than actual player ID when a
slot disconnected. Actual client actors and a real sparse0,2 peer fixture prove
the corrections. No actor packet, renderer, service or second player simulation
was added. Fresh independent Astra follow-up remains unavailable at retained
thread capacity; preceding verified senior architecture guidance and main
source/GPU/server checks are recorded, without claiming a new review.

The next hitscan proof now uses the same resolver at native bullet/grow helpers.
The finite local spread cone preserves native event/random sampling boundaries
and explicitly interprets pitched ranges physically; direct actor accuracy is
not confused with an autoaim correction. Native damage/impact policies remain.
An initial actor delta against different bootstrap arrays was demonstrated to
retain duplicate player identities; complete field encoding at the existing
initial/rebase packet boundary removes that mismatch without another protocol.
Then extend remaining projectiles/thrown weapons/tripmines/melee, PvP damage/frag and
respawn, map change/late join, save/demo/camera transitions and packet loss. Do
not turn an RPG-specific adapter into a second generic weapon policy engine.
Reopen the design if native helpers require duplicated simulation or temporary
absolute body replacement. Physical muzzle calibration, per-weapon/two-hand
placement, dynamic collision reconciliation and real hardware remain separate
qualification gates.


## Freezer/shrinker authority and current scope

Ordinary freezer and shrinker now reuse the RPG's physical velocity helper and
common constrained hand resolver. Native freeze bounce/target logic and native
shrink effects remain authoritative, with server-created tracked shrinkers
replicated through existing actors. No generic projectile engine or parallel
multiplayer implementation was introduced. Pure vertical native projectile
impacts no longer back away in X/Y using an arbitrary yaw; the RPG explosion
retains that axis too. Other pitched impact offsets remain native.

User clarified that EDuke32's existing multiplayer is the foundation and older
peers are not required. Focus further qualification on current-build combat,
frag/respawn, map changes/late joins, loss and independent VR peers. Retain
existing bounded protocol work without spending further milestones on legacy
compatibility. Tracked pipebombs and the native Devastator adapter now exist;
Devastator graphics/headset qualification remains pending. The tracked native
tripmine adapter is now implemented with CPU placement/replication/recovery proof
(TRIPMINES.md). Native selected/quick melee now has CPU multiplayer/recovery
proof too (MELEE.md). The stock World Tour flame adapter now has CPU multiplayer
and private software-XR controller proof (FLAMETHROWER.md); complete
headset/model integration and full SPS remain required.


## World-space crosshair follow-through

User explicitly requested a proper projected world-space aiming crosshair.
The native crosshair event/ART now occupies one sequential captured segment at
its original display boundary. Its world point comes from native hitscan using
the existing constrained hand origin, or native body aim where applicable. The
existing multiview segment draw accepts the two actual native camera clip
matrices and LEQUAL world-depth testing, with writes off. Reusing this boundary
avoids a fake actor, moved CON callbacks, another capture texture, renderer or
frame owner. Exact native relative-coordinate projection is exported after each
mask camera setup; large absolute world coordinates are subtracted first.

Initial camera-facing ART clipped into its own hit wall. The narrow correction
aligns wall/sector contacts to the hit surface and reuses native 320x200 scaling
for the precise ART anchor. Point/depth/pixel and actual authoritative-shot
checks qualify the geometry, rather than trusting uploaded matrices alone.
The reticle previews free aim before weapon-specific correction/spread/arcs.
Remaining full-pitch visibility, custom-material/camera and dynamic-world
qualification still apply; the full VR/multiplayer goal remains active.


User testing constraint (2026-10-16): all further local game tests in this task
must use `EDUKE32_TEST_PRIVATE_WINDOW=1` plus the private null-compositor Monado
runtime. SDL drawables stay unmapped; native startup dialogs/log windows,
fullscreen changes, mouse capture and desktop gamma changes are suppressed in
this explicit test mode. Use owned-window XSendEvent and framebuffer captures;
never map/raise/focus a game window or send global desktop input. Current
crosshair fixtures verify real unmapped/focus state as well as gameplay.
Older-peer compatibility remains outside the required scope.


The 2026-10-17 implementation checkpoint adds tracked native pipebombs, coherent
native weapon snapshots (network version2), and fixes the four findings from
the user's single broad Astra code review. See CODE_REVIEW_20261017.md and
VALIDATION.md. Private Duke/weapon assets are exported and structurally checked;
full-body/controller/native-model integration remains pending, as do complete
SPS coverage, remaining weapons, unrestricted view/collision behavior, physical
headsets and independent VR peers/WAN. No model or packet scaffold qualifies
those user-observable milestones by itself.

The next CPU-native slice qualifies Devastator's existing RPG actor and burst
policy, including demonstrated final-barrel clearance and lost-source ammo
corrections. No new pose protocol, actor simulation or weapon state machine.
Details, baseline comparison and explicit transient-snapshot limits are in
DEVASTATOR.md. The subsequent native tripmine press/commit adapter and CPU
multiplayer proof are recorded in TRIPMINES.md. Melee now reuses the native
counter/hitscan/damage path, with an observed early shared-key readiness defect
corrected and actual revision4 matching-peer proof (MELEE.md). Continue with
World Tour flames and model integration (the stock flame adapter is now
qualified in FLAMETHROWER.md; animated model integration remains open);
GPU/headset acceptance is still required before declaring the full port done.

The user requested a further complete model pass: Quake-like chunky geometry,
lower-resolution diffuse textures and proportions/silhouettes grounded in the
original 2D sprites. Astra owns the entire separate private asset `v2` set,
including World Tour flamethrower. The original exported set is preserved.
The v2 export set is complete and verified; a separate Astra-owned v3 completes
cosmetic action clips for reconstructed weapons while keeping v2 stable.
The v3 art package is now complete, with 430 independently verified manifest
hashes. Neither asset production pass establishes IK or complete runtime presentation.

The first native tracked-model boundary is now implemented and qualified for
vanilla idle pistol frame zero. A focused Astra/xhigh design review moved its
opaque draw before native masks to preserve nearer translucent glass. Reuse the
native MD3 loader/materials/triangle emission with a local sampled instance;
world owners and animation remain native. A serial/generation/player receipt
suppresses only the matching idle ART tile after both eyes succeed. Actual
private software-XR multiplayer proves visible depth, physical muzzle/axes/
scale/roll projection, native server ray alignment, transparent composition,
unsupported-case ART fallback and partial-frame cancellation. See
MODEL_HAND_DESIGN.md. The subsequent MODEL_SPS.md increment reuses the same
native surface boundary and existing transport for the opaque idle pistol.
Shared geometry passes exact native color/depth comparisons with real private
software XR multiplayer, asymmetric FOV, roll, fog, immediate/array paths,
two surfaces, collection/replay rejection and later-mask retry. Model fallback
remains excluded from full-multiview accounting. Animated weapons, grip fitting,
body/IK and complete model/material SPS remain open.


The stock World Tour weapon12 FIREBALL path now reuses the native hand resolver
and physical projectile velocity helper, preserving native weapon/actor policy.
Seven CPU native MP cases and actual private software-XR open/wall/vertical
controller cases pass; freezer rendering/authority regression passes. The native
reference matches flat spawn/random/ammo fields exactly. An observed card-edge
oracle defect was corrected by clipping before viewport/subpixel snapping,
without changing renderer output or tolerance. See FLAMETHROWER.md and bounded
evidence. Next work remains animated weapon presentation/controller fit, deliberate
body/IK/remote presentation, broader model/material SPS and complete headset,
platform, multiplayer and world-feature acceptance.
