# EDuke32 VR work in progress

This repository starts from the exact requested **r10669 ec5824db8** source archive. It now has an optional Linux OpenXR backend, a single-pass stereo **diagnostic**, and an experimental two-pass renderer that submits actual Duke rooms to OpenXR, and a bounded opaque-world multiview path with exact differential fixtures. It is not yet a complete playable VR port: single-pass world rendering, full presentation coverage, headset/controller gameplay and multiplayer qualification remain open.

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

This opts into the first ordinary-room **two-pass reference renderer**. It uses the located eye poses/FOVs, a recentered tracking-to-game transform and RazeXR's world scale. It draws both opaque views before running sprite animation/CON once, then draws each eye's masks using saved wall IDs and per-eye sprite membership. The desktop mirrors the left eye and retains native weapon/HUD drawing. Weapons/HUD are not yet in the headset.

The optional output prefix captures both actual eye layers on frame 60. The log reports that milestone. XR remains active afterward; errors stop the session and restore native rendering. Unsupported native half-space coverage or camera collision is reported rather than silently clamping the tracked pose. Full pitch, room-scale collision/fade, mirrors/YAX, other camera modes and controller input remain required milestones.

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

## Bounded opaque single-pass prototype

`EDUKE32_XR_SINGLE_PASS=1` alongside `EDUKE32_XR=1` opts into ordinary indexed-ART opaque multiview replay. Both native CPU eye traversals and clipping remain; compatible material heads become one GPU draw for both layers. Eye-owned triangles preserve each eye's native order and GL_ALWAYS depth semantics. Native fragment shading remains the sole material policy. Masks still use two native passes. Unsupported sky, hires/detail/glow, recursion, mutable textures, NPOT transforms and unknown state retry the two-pass opaque reference within the same XR frame, before animation. E1L1's sky currently requires that fallback. This prototype is not complete single-pass world rendering or a performance claim.

The deterministic portal fixture includes alternating palette/shade walls and an ordinary sprite mask after opaque replay. It reads only the caller's owned GRP. Synthetic fixture poses finish empty XR frames and never submit projection layers:

```sh
python3 tools/vr/check_stereo_oracle.py --binary ./eduke32-xr --single-pass --display :1 \
    --grp /path/to/owned/DUKE3D.GRP --work-dir /path/to/test/labs
# Nonzero IPD, asymmetric FOV, pitch/yaw/roll against the two-pass reference:
# Repeat with --pose stereo.
# Unequal eye coverage exercises incompatible material/eye-only packets and init failure recovery:
# Repeat with --pose unequal --inject-replay-init-failure.
```

The default native reference executes its unchanged room/animation/mask path on a matching SRGB8_ALPHA8/depth24 array attachment, allowing strict byte-for-byte comparison. `--native-attachment window` preserves the window-system comparison, which currently differs at 344 of 576,000 pixels in this NVIDIA fixture despite identical matrices/cameras. The matched attachment comparison uses zero tolerance and checks CON counts. It also requires real replay statistics at the captured frame, preventing a fallback-only run from passing as paired multiview.

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
