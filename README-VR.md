# EDuke32 VR work in progress

This repository starts from the exact requested **r10669 ec5824db8** source archive. It now has an optional Linux OpenXR backend, a single-pass stereo **diagnostic**, and an experimental two-pass renderer that submits actual Duke rooms to OpenXR, and a bounded native indexed-ART multiview path for opaque rooms, skies and ordered masks/sprites, with exact color/depth differential fixtures. It is not yet a complete playable VR port: complete single-pass coverage, tracked aiming, tracked weapon presentation and complete multiplayer qualification remain open. OpenXR controllers now feed native movement, turning, gameplay buttons and menus, with simulated runtime and native server authority tests.

Read [the implementation plan](docs/vr/PLAN.md), [Astra senior-review dispositions](docs/vr/SENIOR_REVIEW.md), [verification results](docs/vr/VALIDATION.md), and [source provenance](docs/vr/PROVENANCE.md). The pinned RazeXR reference clone is the sibling `../RazeXR` directory. Preserve its Git history: current RazeXR HEAD removed the Raze engine subtree.

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

The numeric test checks the rigid-pose/native-camera/asymmetric-projection derivation. It does not validate CPU visibility. The world runner requires 60 submitted world frames and distinct actual eye readbacks. Use a real supported GL context; Xvfb's llvmpipe did not work with this Monado/NVIDIA swapchain combination.

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

Use a display you own for testing (`:94` was an isolated Xvfb here). This checks dedicated startup/level load/survival only. Multiplayer gameplay is **not** established by that test. A second native fix corrects the world-update packet payload pointer. Listen/dedicated joins and dedicated reconnect now pass startup checks, and a native client reaches rendered gameplay. A native dedicated server with an XR client also passes join/reconnect and 60-frame stereo readbacks per join. Fire/damage/map transitions, authoritative convergence and other mixed-client configurations remain qualification gates; see VALIDATION.md. No network packet layouts or versions have been changed.

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

Aim/grip poses are collected at the predicted display time, but tracked aiming,
hand-position firing, visible tracked weapons, haptics and comfort settings are
still required. Current aim and shot origin remain the native player values.
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
2D weapon sprites; controller-tracked weapon models and authoritative tracked
shot direction remain unfinished.

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
