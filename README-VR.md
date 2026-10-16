# EDuke32 VR work in progress

This repository starts from the exact requested **r10669 ec5824db8** source archive. It now has an optional Linux OpenXR backend and a single-pass stereo **diagnostic**, integrated with EDuke32's SDL/OpenGL context. It is not yet a playable VR port: game-world stereo, headset/controller gameplay and full multiplayer qualification remain open.

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

## Dedicated-server regression

A native bug found during baseline testing polled uninitialized CONTROL input during map entry. The fix skips only that local-device poll in dedicated mode and retains the shared FIFO reset. This regression script reads an owned GRP and leaves isolated evidence in a new lab directory:

```sh
DISPLAY=:94 python tools/vr/smoke_dedicated.py \
    --binary ./eduke32 --grp /path/to/owned/DUKE3D.GRP \
    --work-dir /path/to/test/evidence --seconds 8
```

Use a display you own for testing (`:94` was an isolated Xvfb here). This checks dedicated startup/level load/survival only. Multiplayer gameplay is **not** established by that test. Current native client tests still show a persistent “Waiting for server” readiness barrier; see VALIDATION.md. No network packet layouts or versions have been changed.

Do not put proprietary GRP/maps/CON/audio, private configs, or raw session logs in this repository. Existing source licenses are preserved under `package/common`.
