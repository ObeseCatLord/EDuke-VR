# Building EDuke VR

## Linux

Install the development packages for SDL2, the OpenXR loader, Opus, libvpx, FLAC and OpenGL, then:

```bash
make -j$(nproc) NETCODE=1 USE_OPENXR=1 obj=obj-xr duke3d_game=eduke32-xr eduke32-xr
```

That one binary plays in VR and on the desktop. Add `PORTABLE_GLIBC=1 LTO=0` for a release binary
that also runs on older distributions.

The dedicated server is a separate build:

```bash
make NETCODE=1 duke3d_game=eduke32-net eduke32-net
```

Run it with `eduke32-net -dedicated -port PORT -c2`.

## 64-bit ARM Linux (e.g. the Steam Frame)

On an arm64 machine, `package/vr/build_linux_arm64.sh OUT`. It builds the OpenXR loader from source
too.

## Windows

Cross-build with MinGW-w64: `package/vr/build_windows.sh DEPS`. The script lists the OpenXR loader
and Opus it expects.

## Releases and development

- `package/vr/make_github_release.py` makes the release archives.
- `package/vr/eduke32-vr-play` is the Linux launcher used during development.
- The VR code is mostly in `source/duke3d/src/vr.cpp`, `source/vr/` and
  `source/build/src/polymost.cpp`.
- [README-VR.md](../README-VR.md) and [docs/vr/](vr/) hold the design notes, and `tools/vr/` the
  test tools, including a GPU-free software OpenXR lab.
- Model sets are mods; how to make and build them is in [docs/vr/PLAYING.md](vr/PLAYING.md#model-packs-are-mods).
