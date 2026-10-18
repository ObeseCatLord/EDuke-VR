# EDuke32 VR work in progress

This repository starts from the exact requested **r10669 ec5824db8** source archive. It now has an optional Linux OpenXR backend, a single-pass stereo **diagnostic**, and an experimental two-pass renderer that submits actual Duke rooms to OpenXR, and a bounded native indexed-ART multiview path for opaque rooms, skies and ordered masks/sprites, with exact color/depth differential fixtures. It is not yet a complete playable VR port: complete single-pass coverage, complete tracked weapon/origin behavior and multiplayer qualification remain open. OpenXR controllers now feed native movement, turning, gameplay buttons and menus, with simulated runtime and native server authority tests.

Read [the implementation plan](docs/vr/PLAN.md), [Astra senior-review dispositions](docs/vr/SENIOR_REVIEW.md), [verification results](docs/vr/VALIDATION.md), and [source provenance](docs/vr/PROVENANCE.md). The pinned RazeXR reference clone is the sibling `../RazeXR` directory. Preserve its Git history: current RazeXR HEAD removed the Raze engine subtree.

The private [chunky model set](docs/vr/MODEL_ASSETS.md) is complete as an art/export
deliverable; animated game attachment and body IK remain open. The qualified
idle pistol now has native MD3 stereo and shared-geometry multiview transport.
A [GPU-denied software OpenXR lab](docs/vr/SOFTWARE_XR.md) now qualifies bounded
actual world multiview rendering without using the hardware GPU.
The private AA arsenal includes 69 handheld entries and both floating hands.
Its [first runtime binding](docs/vr/AA_MODELS.md) draws the idle standard Duke
pistol through native stereo or exact-reference model multiview, with ART
fallback during fire/reload. The [model design](docs/vr/AA_MODEL_DESIGN.md)
preserves native world rendering order; broader bindings remain in progress.
[Actual AA enemy damage tests](docs/vr/AA_ENEMY_DAMAGE.md)
exercise the tracked pistol against native AI across multiplayer peers.

## Build

The existing native prerequisites are required, plus SDL2 development files, OpenXR headers/loader, desktop OpenGL/GLX and X11 development files for the optional XR build. The tested target is Linux x86_64 with `GL_OVR_multiview2`. No dependency installation or game-directory changes are needed on the development machine used here.

```sh
# Unchanged flat build; netcode enabled explicitly.
make -j8 NETCODE=1 eduke32

# Optional XR build, separate objects and executable.
make -j8 NETCODE=1 USE_OPENXR=1 obj=obj-xr duke3d_game=eduke32-xr eduke32-xr

# Standalone runner using the same backend as EDuke32.
make -C source/vr
```

A normal build does not link OpenXR. XR is inactive unless explicitly requested at runtime. The first native binding requires an SDL X11/GLX window; Wayland/EGL and Windows/Quest bindings are not implemented yet. An unsupported actual GL context fails the diagnostic clearly without silently substituting two-pass rendering.

## Runtime diagnostic

Start a supported OpenXR runtime first. For Monado, select its manifest only for this invocation; avoid replacing the user's global runtime configuration. A private `XDG_RUNTIME_DIR` can isolate a simulated service. Monado build options vary: use its installed documentation for simulation and compositor settings.

```sh
# XR_RUNTIME_JSON and XDG_RUNTIME_DIR must identify your running test runtime.
SDL_VIDEODRIVER=x11 ./source/vr/xr_smoke --frames 12 --timeout 15 --output /path/to/test/stereo
```

This creates a hidden SDL compatibility-context window and submits a world-fixed colored quad to two layers with one multiview draw per frame. It uses located eye poses and asymmetric FOVs, checks non-background/different layer readbacks before releasing the image, and writes `stereo-left.ppm` / `stereo-right.ppm`. It returns nonzero on failure or insufficient submitted frames. A null Monado compositor permits lifecycle/pixel-allocation testing; it does not show an image in a headset.

To exercise EDuke32's own GL context, launch from a disposable directory with an existing config (`-nosetup` alone does not suppress the startup window when no config exists):

```sh
SDL_VIDEODRIVER=x11 \
EDUKE32_XR_DIAGNOSTIC_FRAMES=60 \
EDUKE32_XR_DIAGNOSTIC_OUTPUT=/path/to/test/eduke \
/path/to/eduke32-vr/eduke32-xr -usecwd -nosetup -noautoload \
    -g /path/to/owned/DUKE3D.GRP -v1 -l1 -s1
```

The native desktop image continues to render. The headset receives the diagnostic geometry, not Duke's world. After the requested number of submitted frames the diagnostic shuts down and native rendering continues. Output is optional; when set, the first submitted frame's two layers are saved. XR errors stop the diagnostic and are logged; they do not make the game a VR application. `EDUKE32_XR_DIAGNOSTIC_FRAMES` must be 1..100000.

Optional validation on an installation that has the Khronos validation layer:

```sh
XR_ENABLE_API_LAYERS=XR_APILAYER_LUNARG_core_validation \
SDL_VIDEODRIVER=x11 ./source/vr/xr_smoke --frames 12 --timeout 15
```

## Experimental Duke-world stereo

```sh
SDL_VIDEODRIVER=x11 EDUKE32_XR=1 \
EDUKE32_XR_WORLD_OUTPUT=/path/to/test/world \
./eduke32-xr -usecwd -nosetup -noautoload -g /path/to/owned/DUKE3D.GRP -v1 -l1 -s1
```

This opts into the first ordinary-room **two-pass reference renderer**. It uses the located eye poses/FOVs, a recentered tracking-to-game transform and RazeXR's world scale. It draws both opaque views before running sprite animation/CON once, then draws each eye's masks using saved wall IDs and per-eye sprite membership. The desktop mirrors the left eye and retains native weapon/HUD drawing. Set `EDUKE32_XR_UI=2` for the experimental native ART weapon/HUD and in-game-menu plane described below.

The optional output prefix captures both actual eye layers on frame 60. The log reports that milestone. XR remains active afterward; errors stop the session and restore native rendering. Unsupported native half-space coverage or camera collision is reported rather than silently clamping the tracked pose. Full pitch, room-scale collision/fade, mirrors/YAX, other camera modes and tracked controller aiming remain required milestones.

A repeatable isolated test, using your already-running runtime:

```sh
python3 tools/vr/smoke_world.py --binary ./eduke32-xr --display :1 \
    --grp /path/to/owned/DUKE3D.GRP --work-dir /path/to/test/labs
python3 tools/vr/check_projection_math.py
# Test both early abort boundaries with native fallback/list-count checks:
python3 tools/vr/smoke_world.py --binary ./eduke32-xr --display :1 \
    --grp /path/to/owned/DUKE3D.GRP --work-dir /path/to/test/labs --failure-stage opaque
# Repeat with --failure-stage masks.
```

The numeric test checks the rigid-pose/native-camera/asymmetric-projection derivation. It does not validate CPU visibility. The world runner requires 60 submitted world frames and distinct actual eye readbacks. The matched llvmpipe/LVP software stack now passes this bounded world test; see [the private lab recipe](docs/vr/SOFTWARE_XR.md). The older mixed software/NVIDIA swapchain configuration failed.

For bounded failure regression only, `EDUKE32_XR_TEST_FAIL=opaque` injects one failure after left opaque collection; `masks` injects after the once-only animation and before masks. Both stop XR. Up to ten native animation input counts/provenance checks are logged to verify that fallback/next-frame rendering receives no stale sprite entries. This flag is for testing, not ordinary gameplay.

## Bounded world single-pass prototype

`EDUKE32_XR_SINGLE_PASS=1` alongside `EDUKE32_XR=1` opts into indexed-ART opaque and mask multiview replay. Both native CPU eye traversals and clipping remain; compatible material heads become one GPU draw for both layers. Eye-owned triangles preserve native ordering and depth semantics. Native flat ceiling/floor skies, their depth-only companion pass and NPOT shader emulation are supported. The same phased transport now captures masked walls and face/wall/floor sprites, native alpha/blend state, transparency order and equal-depth color/depth-only groups. One logical CON animation pass supplies both eyes.

Unsupported materials, models/voxels, alternate renderer paths and texture/palette mutation safely use the native two-pass reference for the affected phase. A failed mask collection has made no eye color/depth writes. Replay failure before its first draw can retry masks; failure after any draw ends empty and disables XR, consuming the already animated logical pass. Opaque geometry is never regenerated after arbitrary CON as mask recovery.

Streaming can still cause reference frames after startup. Coverage counters report opaque, masks and complete multiview frames separately; the world and mixed-client runners can enforce `--minimum-full-multiview-frames`. This remains an incomplete coverage/performance gate, with two CPU traversals and duplicated geometry. It is not a performance claim or complete single-pass renderer.

The deterministic portal fixture includes alternating palette/shade walls and an ordinary sprite mask after opaque replay. It reads only the caller's owned GRP. Synthetic fixture poses finish empty XR frames and never submit projection layers:

```sh
python3 tools/vr/check_stereo_oracle.py --binary ./eduke32-xr --single-pass --display :1 \
    --grp /path/to/owned/DUKE3D.GRP --work-dir /path/to/test/labs
# Nonzero IPD, asymmetric FOV, pitch/yaw/roll against the two-pass reference:
# Repeat with --pose stereo.
# Unequal eye coverage exercises incompatible material/eye-only packets and init failure recovery:
# Repeat with --pose unequal --inject-replay-init-failure.
# Ceiling sky with its native depth-only pass and nonzero panning:
# Repeat with --scene masks-animated for animated ART, transparency and native depth-only sprite groups.
# --mask-failure collect-right or replay-before tests same-frame recovery without another CON pass.
# Repeat with --scene sky --sky-depth 1.
# Floor sky and unequal coverage: --scene sky-floor --pose unequal --sky-depth 1.
# Disable panning/depth explicitly with --sky-panning 0 --sky-depth 0.
```

The default native reference executes its unchanged room/animation/mask path on a matching SRGB8_ALPHA8/depth24 array attachment, allowing strict byte-for-byte comparison. `--native-attachment window` preserves the window-system comparison, which currently differs at 344 of 576,000 pixels in this NVIDIA fixture despite identical matrices/cameras. The matched attachment comparison uses zero tolerance for color and nonconstant raw depth samples. It checks native CON counts at identical zero-IPD views, and two-pass CON counts at the same synthetic pose otherwise. It also requires real replay statistics at the captured frame, preventing a fallback-only run from passing as paired multiview. Sky cases additionally require actual flat-sky/depth-pass draw counts. The world and multiplayer runners accept `--minimum-multiview-frames 59` to require measured opaque replay coverage among their first 60 frames; their JSON reports both multiview and reference counts.

## Dedicated-server regression

A native bug found during baseline testing polled uninitialized CONTROL input during map entry. The fix skips only that local-device poll in dedicated mode and retains the shared FIFO reset. This regression script reads an owned GRP and leaves isolated evidence in a new lab directory:

```sh
DISPLAY=:94 python tools/vr/smoke_dedicated.py \
    --binary ./eduke32 --grp /path/to/owned/DUKE3D.GRP \
    --work-dir /path/to/test/evidence --seconds 8
```

Use a display you own for testing (`:94` was an isolated Xvfb here). This checks dedicated startup/level load/survival only. Multiplayer gameplay is **not** established by that test. A second native fix corrects the world-update packet payload pointer. Listen/dedicated joins and dedicated reconnect now pass startup checks, and a native client reaches rendered gameplay. A native dedicated server with an XR client also passes join/reconnect and 60-frame stereo readbacks per join. Fire/damage/map transitions, authoritative convergence and other mixed-client configurations remain qualification gates; see VALIDATION.md. Native network version2 synchronizes the existing pipebomb hold/remote tuple; all peers must use the current build. The optional hand-shot capability below negotiates a movement-update tail between upgraded peers.

The mixed-client regression uses an already-running runtime and a supported GPU display. It waits for level synchronization, skips the native intro with `-nologo`, dismisses the startup menu after synchronization/fade, then requires eye readbacks and visible input changes on both the initial join and reconnect:

```sh
python3 tools/vr/smoke_multiplayer.py --binary ./eduke32 --client-binary ./eduke32-xr \
    --xr-client --external-display --display :1 --mode dedicated --reconnect --seconds 20 \
    --grp /path/to/owned/DUKE3D.GRP --work-dir /path/to/test/labs
```

The multiplayer runner requires Python Pillow, X11/XTest libraries and ImageMagick `import`; private-display runs also require Xvfb. External-display input/capture targets only a window whose PID matches the spawned client. The caller supplies its runtime manifest/private runtime directory environment.

Do not put proprietary GRP/maps/CON/audio, private configs, or raw session logs in this repository. Existing source licenses are preserved under `package/common`.


## OpenXR controller input

World mode (`EDUKE32_XR=1`) creates one action set with simple-controller, Touch,
Index and Microsoft motion-controller profiles. The Index profile is exercised
through a private Monado remote driver; the other profiles have not been tested
on hardware. Inputs use EDuke32's existing control, menu, CON and network paths.
Keyboard and mouse remain available.

| Control | Native action |
|---|---|
| Left stick | Move / strafe; radial 20% dead zone |
| Right stick | Native smooth turn / look |
| Right stick click | Quick kick (new mapping; headset qualification pending) |
| Right trigger / select | Fire |
| Left trigger / select | Open / use |
| Right primary / secondary face button | Jump / crouch |
| Left primary / secondary face button | Previous / next weapon |
| Either grip | Run |
| Menu action | Open menu (Index: left stick click) |
| Select or primary in menus | Advance |
| Secondary in menus | Back |
| Either stick in menus | Native navigation and repeat |

Unavailable or unfocused actions become neutral. A button already held when
it first becomes active, reconnects or regains focus requires release before
it can act. Native input-clearing also suppresses held buttons across menu
transitions. OpenXR focus is independent of desktop window focus.

Aim/grip and HMD VIEW poses are collected at predicted display time. The
opt-in tracked-orientation mode below feeds native authoritative aim; hand-position
firing, visible tracked weapons, haptics and comfort settings remain required.
Shot origin remains native in this orientation checkpoint.
The control map is an initial fixed mapping, pending user settings.

The test tools require an already-running **private** Monado remote-driver
runtime with the native `mndrmt3` protocol. They do not modify global runtime
configuration or installed game content. Supply the runtime environment and an
owned GRP:

```sh
python3 tools/vr/smoke_actions.py --binary ./eduke32-xr --display :1 \
  --grp /path/to/DUKE3D.GRP --work-dir work/actions --remote-port 29427
# Add --title-menu to test the separate title/demo frame loop.
python3 tools/vr/smoke_action_lifecycle.py --binary ./eduke32-xr \
  --helper source/vr/xr_smoke --display :1 --grp /path/to/DUKE3D.GRP \
  --work-dir work/actions --remote-port 29427
python3 tools/vr/smoke_actions_multiplayer.py --binary ./eduke32 \
  --client-binary ./eduke32-xr --display :1 --grp /path/to/DUKE3D.GRP \
  --work-dir work/actions --remote-port 29427 --port 24586 --reconnect
```

The lifecycle tool requires exclusive use of the private runtime. It changes
only the owned clients' Monado focus/IO state and restores that state on exit.
Its native `restartvid` check retains the SDL2 context; actual in-game context
loss/recreation remains an unclosed test gap.


## Experimental headset cold menus

`EDUKE32_XR_UI=1` alongside `EDUKE32_XR=1` enables the first headset UI
checkpoint: opaque startup menus and console on a head-relative plane 1.5 m away.
Native menu content is drawn once into a separate RGBA8 target, then one
multiview draw places it into both existing XR eye layers over black. The
complete native capture is also mirrored to the desktop. Menu resources are
created only when this mode is used.

The logical title-menu owner explicitly arms its final native presentation.
Unarmed nested swaps, auxiliary room draws, mode/extent changes, skipped
presentation and shutdown cancel safely. Temporary invalid head poses cancel a
frame and allow recovery. Controller menu navigation remains native.

```sh
SDL_VIDEODRIVER=x11 EDUKE32_XR=1 EDUKE32_XR_UI=1 \
./eduke32-xr -usecwd -nosetup -noautoload -nologo -g /path/to/DUKE3D.GRP
python3 tools/vr/smoke_menu.py --binary ./eduke32-xr --display :1 \
  --grp /path/to/DUKE3D.GRP --work-dir work/menus \
  --invalid-pose-once --partial-viewport --nested-swap-once
# Add --console --resize for console and capture resizing.
# Add --enter-game to verify transition into actual stereo gameplay.
# Use --quit-native separately to verify normal menu exit/cleanup.
```

Optional `EDUKE32_XR_MENU_OUTPUT=/path/to/prefix` saves actual `-left.ppm`,
`-right.ppm`, `-ui.ppm` and `-desktop.ppm` on the 60th successful menu submission.
The test requires the captured desktop and native UI pixels to match exactly.

This first UI mode covers cold menus only. UI=2 below adds bounded native ART
weapons/HUD, in-game menus and full-eye effects. Broader native/CON compatibility
and real headset comfort remain open. Physical size/distance are provisional.


## Native headset weapons, HUD, and in-game menus

`EDUKE32_XR_UI=2` extends the same cold-menu capture to native ART weapons/HUD,
in-game menus, and console over the stereo world. Native UI runs once, then one
multiview plane composites it into both existing eye layers at a provisional
1.5 m distance. This preserves independent world parallax. These are the native
2D weapon sprites; controller-attached weapon presentation and true hand-origin
shots remain unfinished. Tracked native aim is separately opt-in below.

```sh
SDL_VIDEODRIVER=x11 EDUKE32_XR=1 EDUKE32_XR_SINGLE_PASS=1 EDUKE32_XR_UI=2 \
./eduke32-xr -usecwd -nosetup -noautoload -g /path/to/owned/DUKE3D.GRP -v1 -l1 -s1
```

Source-over transparency, opaque zero-alpha ART texels, and native full-eye menu
dimming/palette flashes are supported in this bounded path. Fades execute at
their original boundary and affect peripheral world pixels too. The desktop
retains full-size native UI over its left-world mirror. Custom destination-based
blend factors or HUD models cancel the current headset presentation before
native drawing continues; they are not yet qualified. Pre-world CON overlays,
help/other no-world 2D modes, general materials and camera paths still need work.

`EDUKE32_XR_HUD_OUTPUT=/path/to/test/hud` captures UI RGB/coverage and final eye
color/depth on the 60th successful HUD projection. `EDUKE32_XR_WORLD_OUTPUT` also
captures the same frame before composition, allowing exact depth comparison.
Frame statistics credit actual matching projection submissions, including after
cancellation and native window resizing.

```sh
python3 tools/vr/smoke_hud.py --binary ./eduke32-xr --display :1 \
    --grp /path/to/owned/DUKE3D.GRP --work-dir /path/to/test/labs
# Full-eye tint and native corrected/clamped tint: --tint 1, --tint 2, --tint 3.
# Native menu ordering/thumbnail: --native-menu main, --native-menu save.
# Recovery: --resize, or --invalid-pose-once --nested-swap-once.
# Native console path: --console.
# Dedicated server/input runner: add --reconnect --require-hud.
```

The fixture creates its own tiny ART tiles and observes native CON callbacks.
It compares actual eye/depth/coverage readbacks and a separate native flat run.
This is simulated-runtime evidence; real-headset comfort remains untested.


## Experimental authoritative tracked orientation

Add `EDUKE32_XR_AIM=right` to the world/HUD command for orientation from the right
controller's actual aim pose. `left` selects the left aim pose; `head` selects
HMD direction. These select the aim source; the initial button bindings above
remain fixed. Tracking is one-to-one and independent of virtual stick turning.
Movement uses the recovered body heading, so pointing a controller backward does
not reverse forward movement.

Native player angle updates and unchanged packets carry this orientation to the
server. HMD rendering removes the applied aim offset before applying head poses,
so the controller does not rotate the world and head rotation is applied once.
With gameplay HUD mode (`EDUKE32_XR_UI=2`), the native crosshair event runs once
and its ART is projected onto the world at the aiming ray's collision point.
Each eye uses the exact native world projection and existing world depth.
Walls/floors/ceilings receive a surface-aligned marker; other visible geometry
can occlude it. Native crosshair size, color, toggle and script cancellation
remain available. See the world-space aiming section below. Native weapon
autoaim/spread settings remain unchanged; the deterministic fixtures disable
autoaim when comparing the central free-aim ray.

Source loss suppresses firing and requires release before a held trigger can
act after recovery. XR retains native look-mode ownership during pose loss so
legacy gamepad centering cannot tilt the recovered view. New runtime generations
invalidate action samples/buttons while rebasing the existing tracking
calibration to preserve virtual view, room-scale offset and native aim. Native
local-player resets start a fresh calibration.

```sh
SDL_VIDEODRIVER=x11 EDUKE32_XR=1 EDUKE32_XR_SINGLE_PASS=1 \
EDUKE32_XR_UI=2 EDUKE32_XR_AIM=right \
./eduke32-xr -usecwd -nosetup -noautoload -g /path/to/owned/DUKE3D.GRP -v1 -l1 -s1

python3 tools/vr/smoke_aim.py --binary ./eduke32 --client-binary ./eduke32-xr \
  --grp /path/to/owned/DUKE3D.GRP --work-dir work/aim --display :1 \
  --remote-port 29427 --mode right --late-controller --resize
# Also run --mode left and --mode head against your private remote runtime.
```

Actual server RPG spawn angles, velocity and far-wall impact pass; head/controller
independence, projected UI pixels, pole/yaw-wrap behavior, body movement and
nonzero-pose window/session recreation pass in simulated Monado. This remains a
bounded vanilla-Duke orientation step. Native pitch limits remain; true tracked
weapon placement/hand-origin authority, full-pitch visibility, recording/save-load,
other cameras/angle-rewriting CON and physical headset behavior remain open.


## Experimental controller-attached native ART

With `EDUKE32_XR_UI=2` and `EDUKE32_XR_AIM=right` or `left`, add
`EDUKE32_XR_WEAPON=1` to move native weapon ART off the head-relative HUD and
attach it to that controller's aim pose. Native animation, palette and weapon
callbacks run once. Face spit, scuba and following HUD remain head-relative.
The same capture texture is cleared/reused between those sequential segments;
each segment uses one multiview draw for both existing eye layers.

This is a perspective ART card with a provisional native(192,180) grip pivot,
physical scale and foreground-depth policy. It is not a solid gun model or
collision-constrained physical muzzle. The card tracks translation, yaw, pitch
and roll; unavailable poses hide it without stale pixels. The desktop retains
native flat placement. `head` aim and an unset weapon flag retain the preceding
head-panel presentation.

```sh
EDUKE32_XR=1 EDUKE32_XR_SINGLE_PASS=1 EDUKE32_XR_UI=2 \
EDUKE32_XR_AIM=right EDUKE32_XR_WEAPON=1 SDL_VIDEODRIVER=x11 \
./eduke32-xr -usecwd -nosetup -noautoload -g /path/to/owned/DUKE3D.GRP -v1 -l1 -s1

python3 tools/vr/smoke_weapon.py --binary ./eduke32-xr \
  --grp /path/to/owned/DUKE3D.GRP --work-dir work/weapon \
  --display :1 --remote-port 29427 --case rotated
```

The runner also accepts `base`, `moved`, `head`, `left`, `lost`, `resize`, `tint`,
`save` and `nested`. It compares actual eye pixels against an independent
ray/plane/linear-sampling oracle, final HUD/tint composition, unchanged world
depth and native callback counts. All ten cases pass under private simulated
Monado; this does not establish real-headset comfort or performance.

Without the hand-shot flag below, shots retain the native player origin and
native pitch limits. World occlusion, per-weapon pivots/two-hand behavior, other
weapon/face-action families and physical-headset ergonomics remain required.

## Experimental authoritative hand-origin weapons

`EDUKE32_XR_HAND_SHOTS=1` with `EDUKE32_XR_AIM=right` or `left` enables
independent hand-origin/full-vector firing for ordinary hardcoded pistol,
shotgun, chaingun, grow, RPG, freezer and shrinker weapons.
The existing native server creates projectiles, applies damage and replicates
actors. Other weapons and custom projectile replacements retain native origins. This flag
is optional and requires the corresponding server capability. RPG-only hand
servers retain RPG support; unsupported hand hitscan is suppressed while native
movement continues. Optional feature upgrades separately qualify hitscan and
freezer/shrinker, so hitscan-capable older servers retain that support.

```sh
EDUKE32_XR=1 EDUKE32_XR_SINGLE_PASS=1 EDUKE32_XR_UI=2 \
EDUKE32_XR_AIM=right EDUKE32_XR_WEAPON=1 EDUKE32_XR_HAND_SHOTS=1 \
SDL_VIDEODRIVER=x11 ./eduke32-xr -usecwd -nosetup -noautoload \
  -g /path/to/owned/DUKE3D.GRP -v1 -l1 -s1

python3 tools/vr/smoke_hand_shots.py --binary ./eduke32 \
  --client-binary ./eduke32-xr --grp /path/to/owned/DUKE3D.GRP \
  --work-dir work/hand-shots --display :1 --remote-port 29427 --case wall
```

The negotiated 14-byte tail travels with the existing native movement/fire
update. Both sides constrain its body-relative position to two metres, trace
body-to-hand obstruction and resolve the actual origin sector. The eligible weapon card uses
the locally constrained origin; static fixtures compare it with server authority.
Samples expire after 250ms on the native clock; invalidity/expiry requires a
trigger release before recovery can fire. No player body is temporarily moved.

Tracked hitscan keeps native shot events, random sampling, damage, switches and
decals. A finite local spread cone supports vertical shots; it is an explicit
physical interpretation of native ranges at pitched rays. An accurate free-aim
pistol hit still suppresses spread without replacing its hand ray. CON forced
slopes retain precedence, including postfire ceiling/floor classification.

Tracked RPG/freezer velocity uses physical 3D speed 644 and shrinker uses 768,
so steep shots have less horizontal speed than native body firing. Freezer keeps
its native post-spawn vertical bias of -32, bounce count and freeze effects;
shrinker keeps native shrink effects. Tracked network shrinkers spawn on the
server and reach clients through native actor replication. Pure vertical
projectile ceiling/floor impacts skip the arbitrary yaw-based horizontal
backoff; vertical RPG explosions also keep the impact X/Y. Other native impact
offsets remain. Native autoaim selection/events remain;
its velocity is normalized in this mode, while explicit CON z-velocity overrides
retain native precedence. Vertical projectiles work, but full-pitch **world
rendering** remains incomplete. This is an aim-pose origin with provisional ART
placement, not a calibrated 3D barrel. Dynamic-world prediction, loss/reordering,
all weapon families and full multiplayer combat/respawn/map-change coverage
remain open. See [the protocol and invariants](docs/vr/HAND_SHOTS.md) and
[validation](docs/vr/VALIDATION.md).

```sh
python3 tools/vr/smoke_hitscan.py --binary ./eduke32 --client-binary ./eduke32-xr \
  --grp /path/to/owned/DUKE3D.GRP --work-dir work/hitscan \
  --display :1 --remote-port 29427 --weapon shotgun --case spread
```


## World-space aiming crosshair

Gameplay HUD mode (`EDUKE32_XR_UI=2`) draws the crosshair at the native hitscan
collision of the aiming ray. With supported hand-origin weapons it uses the
same constrained hand position and physical direction as firing. Body-origin
mode uses native player aim. The marker has real stereo parallax, uses existing
world depth with depth writes disabled, and is aligned to hit walls or sector
planes. A small pullback avoids surface z fighting. Its angular scale follows
the native crosshair size setting; the normal crosshair color/toggle and
`EVENT_DISPLAYCROSSHAIR` artwork/cancellation apply. For a bright marker, the
native console command `crosshaircolor 255 255 255` selects white. Losing the selected hand
hides its marker. The desktop retains its native crosshair draw position.

The trace previews central free aim before weapon spread, autoaim, CON shoot
overrides and ballistic/bounce behavior. Dynamic server reconciliation and
broader custom projectile/model/mirror/YAX behavior remain qualification work.
The existing partial head-pitch world-rendering limit also applies.

```sh
EDUKE32_TEST_PRIVATE_WINDOW=1 python3 tools/vr/smoke_crosshair.py --binary ./eduke32 \
  --client-binary ./eduke32-xr --grp /path/to/owned/DUKE3D.GRP \
  --work-dir work/crosshair --display :1 --remote-port 29427 --case occluded
```

The runner checks real server shot agreement, independent physical projection,
actual two-eye pixels against a depth-tested CPU oracle, unchanged native world
depth and native crosshair event counts. It also exercises head translation,
near-wall/sector contacts, target actors, handed aim, tracking loss and native
visibility/size/color controls.

For non-interrupting simulator tests, set `EDUKE32_TEST_PRIVATE_WINDOW=1` on
both game processes (the Python runners inherit it). The native startup log
window is suppressed and SDL creates an unmapped GPU drawable, with fullscreen,
mouse capture and desktop gamma changes disabled. Test input uses owned-window
XSendEvent or the private Monado actions; the helper refuses focus-changing
input in this mode. Use framebuffer eye captures instead of desktop screenshots.
The crosshair runner verifies actual X11 unmapped/focus state as part of the
proof. Normal game launches omit this test-only flag.


## Native PvP and level transitions

The native dedicated server with current flat/XR clients has passed real pistol
kill, native frag/death convergence, Use respawn and recovered controls in both
victim roles. The XR victim also passes held-fire suppression through respawn
until release/new press. A native spawn-packet copy offset is corrected without
a new protocol or simulation. See [validation](docs/vr/VALIDATION.md) for the
precise scope and actual pre-fault eye images.

After the reported driver fault, GPU work stopped. The user later authorized
GPU testing again. A new boot, no recovery action and a clean bounded graphics
probe established recovery before one private runtime was resumed. Both final
PvP roles, controller reconnect/inventory, world-crosshair occlusion and exact
animated-mask single-pass color/depth checks now pass on that recovered driver.
The cause of the earlier fault remains unknown. Hidden windows still share GPU
resources; tests use one runtime, sequential cases and driver checks.

Native `map` and `changelevel` now work from a dedicated server's stdin and
reuse EDuke32's existing level loader and reliable multiplayer messages. Active
settings survive transitions; clients cannot change the server's map. Two native
sprite-lifetime bugs are corrected: reserved network slots are excluded from map
actor spawning, and old client temporary-sprite indices are cleared at map load.
Repeated native and actual XR transitions pass controls, sprite ownership,
late stereo frames and held-trigger reset checks. This is bounded local testing;
the full VR/SPS/multiplayer port remains incomplete.

CPU-only reproduction requires a classic build and `bubblewrap`. Its private
namespace has no GPU devices; SDL dummy input reaches native controls through a
test-only FIFO helper. The test also captures native software framebuffers.

```sh
make -j4 USE_OPENGL=0 POLYMER=0 obj=work/obj-cpu \
  duke3d_game=work/eduke32-cpu work/eduke32-cpu
cc -shared -fPIC $(sdl2-config --cflags) tools/vr/sdl_dummy_input.c \
  -o work/headless_input.so -ldl $(sdl2-config --libs)
python3 tools/vr/smoke_native_levels.py --binary work/eduke32-cpu \
  --input-helper work/headless_input.so --grp /path/to/owned/DUKE3D.GRP \
  --work-dir work/cpu-levels

# Existing private Monado runtime/validation environment required.
EDUKE32_TEST_PRIVATE_WINDOW=1 python3 tools/vr/smoke_xr_levels.py \
  --binary ./eduke32 --client-binary ./eduke32-xr \
  --grp /path/to/owned/DUKE3D.GRP --work-dir work/xr-levels \
  --display :1 --remote-port 29427
```

Use `duke3d_game=eduke32-xr` to name the executable. Changing `APPBASENAME`
also changes the native configuration filename and can bypass the fixture's
bounded video settings. See [validation](docs/vr/VALIDATION.md) for evidence and
remaining limits.


## Implementation review and pipebomb checkpoint (2026-10-17)

The requested single Astra/xhigh code review found four defects. All four have
narrow fixes and bounded regressions; see [the disposition table](docs/vr/CODE_REVIEW_20261017.md).
Holoduke no longer wins player binding; terminal XR fallback restores native
firing; effective LOCAL-space changes preserve calibration or safely rearm;
minimizing the mirror permits active headset projections. Physical runtime
recenter/minimize behavior remains unqualified.

Tracked pipebombs now retain native charge, remote/timer physics, damage and
multiplayer ownership. A demonstrated skipped-commit/early-client-explosion
bug required three native weapon-state bytes in server snapshots and network
version2. Rebuild every peer together. Details and remaining coverage limits
are in [HAND_SHOTS.md](docs/vr/HAND_SHOTS.md).

The private sibling Duke/weapon asset package has a completed chunky `v2` set:
Duke plus all thirteen equipment entries, including World Tour's flame weapon,
with original sprite silhouettes/proportions and small diffuse atlases. Astra
completed the latest `v3` package with action clips for all eight formerly static
reconstructions, preserving v1/v2. All 430 manifest hashes were independently
verified. See [MODEL_ASSETS.md](docs/vr/MODEL_ASSETS.md).

The stock World Tour flamethrower now uses the constrained hand origin and
physical aim through its existing native FIREBALL path. Native damage, gravity,
trail actors, ammo and script events remain intact. Seven CPU multiplayer cases
and three private software-XR controller cases pass, alongside a freezer
regression. Feature64 extends the existing capability mask to127 without new
packet fields; rebuild matching peers. Physical headset and 3D flame-weapon
presentation remain open. See [FLAMETHROWER.md](docs/vr/FLAMETHROWER.md).

An opt-in native MD3 adapter now renders a qualified **idle pistol** from the
constrained aiming ray, with stereo depth and correct ordering behind nearer
translucency. Enable `EDUKE32_XR_MODELS=1` alongside the existing tracked
weapon/UI settings and the supplied private native DEF binding. Firing, reload,
custom presentation and unsupported models retain native ART. This first
muzzle-alignment proof does not finish controller grip fit, animated weapons,
full-body integration or complete model/material SPS. With the existing
`EDUKE32_XR_SINGLE_PASS=1` opt-in, this opaque idle pistol now submits shared
geometry through the existing multiview transport, with exact native color/depth
qualification. Unsupported state uses the native two-eye reference and is
excluded from full-multiview counts. See [the native boundary](docs/vr/MODEL_HAND_DESIGN.md)
and [model SPS qualification](docs/vr/MODEL_SPS.md).


The native tracked **Devastator** now reuses the RPG path, retaining native
barrel alternation/spread, reduced damage/size and delayed bursts. CPU-native
multiplayer tests cover hand vectors, final muzzle clearance, vertical flight,
tracking-loss cancellation, native actors and replicated damage; the flat
projectile/random-state reference matches. See [DEVASTATOR.md](docs/vr/DEVASTATOR.md).
Native network revision3 requires matching builds for the expanded RPG
capability; no packet fields are added. Devastator graphics/headset/model attachment is
not yet qualified; GPU testing remains on hold after the recorded driver errors.

Native tracked tripmine and melee/quick-kick adapters now have CPU gameplay and
multiplayer proof; see [TRIPMINES.md](docs/vr/TRIPMINES.md) and
[MELEE.md](docs/vr/MELEE.md). Current network revision is **4**; rebuild all peers
together. An actual prior server could apply a body-aimed quick-kick without
melee capability, so the existing native version guard rejects that mix.
The same9byte capability exchange and14byte hand tail remain. Actual headset
input/presentation, completed body/model integration and full SPS remain open.
