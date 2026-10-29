# EDuke VR

Duke Nukem 3D in virtual reality, based on [EDuke32](https://www.eduke32.com/) (r10669). It plays
in an OpenXR headset or on a normal desktop, alone or in multiplayer, from the same build.

- Stereo rendering of the original Build engine levels, skies, sprites, voxels, models and mirrors.
- Tracked hands: weapons are held and aimed with the controller. There is two-handed aiming,
  physical pipebomb throwing, a wrist HUD, and weapon and gadget wheels with ammo rings.
- A full body: an IK Duke body with legs and the mighty foot, which other players see in
  multiplayer.
- 3D model sets for the hands, held weapons and Duke (original, original-lowres). The Voxel Duke
  set can be built from your own copy of that mod.
- Client/server multiplayer (co-op and DukeMatch) with tracked bodies and voice chat; VR and
  desktop players can mix.
- Snap or smooth turning, room-scale head movement kept out of walls, crouching by ducking, and
  use/open where your left hand points.

You need your own copy of Duke Nukem 3D (`DUKE3D.GRP`, e.g. from the 20th Anniversary World Tour on
Steam). No game data is included.

## Download and play

Get the archive for your system from [Releases](../../releases). Each platform has its own
releases, tagged `vX.Y.Z-windows`, `vX.Y.Z-linux` and `vX.Y.Z-linux-arm64`:

- **Windows** (`EDuke-VR-*-windows-x64.zip`): run `play.bat vr` or `play.bat desktop`, or
  `install.ps1` for Start menu entries. VR needs an OpenXR runtime (SteamVR, Meta/Oculus, WMR,
  Virtual Desktop).
- **Linux** (`EDuke-VR-*-linux-x86_64.tar.gz`): run `./play.sh vr` or `./play.sh desktop`, or
  `./install.sh` for menu entries. It needs glibc 2.38+ (Ubuntu 24.04, Debian 13, Fedora 39,
  Arch...), SDL2, and for VR an OpenXR runtime (SteamVR, Monado/Envision, WiVRn).
- **Linux on 64-bit ARM, e.g. the Steam Frame on SteamOS** (`EDuke-VR-*-linux-arm64.tar.gz`): the
  same scripts. It needs glibc 2.31+, SDL2, and for VR an OpenXR runtime that supports OpenGL. On
  SteamOS, add `play.sh` as a non-Steam game.

Put `DUKE3D.GRP` in `data/grp/`, or let EDuke32 find an installed copy. Join a server with
`join.sh` / `join.bat HOST[:PORT]`. To update, run `./update.sh` or
`powershell -ExecutionPolicy Bypass -File update.ps1`: it fetches the latest release for your
system and keeps your
game data, model sets, settings and saves. In VR, options are under **Options > VR Setup**.
[docs/vr/PLAYING.md](docs/vr/PLAYING.md) has more.

## Building

Linux (VR + desktop): needs SDL2, OpenXR loader, Opus, libvpx, FLAC and GL development packages.

```bash
make -j$(nproc) NETCODE=1 USE_OPENXR=1 obj=obj-xr duke3d_game=eduke32-xr eduke32-xr
```

Add `PORTABLE_GLIBC=1 LTO=0` for a release binary that runs on older distributions. The dedicated
server is `make NETCODE=1 duke3d_game=eduke32-net eduke32-net`, run with
`eduke32-net -dedicated -port PORT -c2`.

64-bit ARM Linux: `package/vr/build_linux_arm64.sh OUT` on an arm64 machine (it builds the OpenXR
loader from source too). Windows: cross-build with MinGW-w64 via `package/vr/build_windows.sh DEPS` (see the script for
the OpenXR loader and Opus it expects). `package/vr/eduke32-vr-play` is the Linux launcher used
during development. Release archives come from `package/vr/make_github_release.py`. The VR
code is mostly in `source/duke3d/src/vr.cpp`, `source/vr/` and `source/build/src/polymost.cpp`.
[README-VR.md](README-VR.md) and [docs/vr/](docs/vr/) hold the design notes and test tools
(`tools/vr/`, including a GPU-free software OpenXR lab).

## License

EDuke VR is a modified version of EDuke32 and is distributed under the same terms:

- **GNU GPL version 2** for EDuke32 and this port ([package/common/gpl-2.0.txt](package/common/gpl-2.0.txt)).
- **BUILD engine license** by Ken Silverman for the Build engine source under `source/build`
  ([package/common/buildlic.txt](package/common/buildlic.txt)). It allows non-commercial use
  only, so EDuke VR may not be sold.
- Other bundled code (SDL, libvpx, OpenXR loader, Opus...) keeps its own license. The release
  archives list them in `licenses/THIRD-PARTY.txt`.

Duke Nukem 3D is a trademark of Gearbox Software. This project is not affiliated with Gearbox,
3D Realms or Voidpoint.

## Credits

EDuke32 by Richard "TerminX" Gobeille, Evan "Hendricks266" Ramos and the Voidpoint team. The
Build engine by Ken Silverman. Duke Nukem 3D by 3D Realms. JFDuke3D by Jonathon Fowler.
[RazeXR](https://github.com/Team-Beef-Studios/RazeXR) served as a reference for the VR design.
