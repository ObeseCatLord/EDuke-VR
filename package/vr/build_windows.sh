#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Cross-build the Windows game (desktop + OpenXR VR, voice chat) with MinGW-w64:
#   package/vr/build_windows.sh DEPS
# DEPS holds include/{opus,openxr}, lib/{libopus.a,libopenxr_loader.a} (an import library made
# from openxr_loader.dll with dlltool), pkgconfig/opus.pc and bin/{openxr_loader.dll,libopus-0.dll}.
# Writes DEPS/out/eduke32-vr.exe beside copies of those two DLLs, and eduke32-vr-amc.exe: the engine
# build for AMC Squad (AMCSQUAD=1, 16-bit tile numbers), which play-game.bat picks for AMCSQUAD.GRP.
# Both link libvpx (USE_LIBVPX defaults to 1; the AMC game plays 67 IVF cutscenes through it).
# LTO=0: with link-time optimisation the MinGW (GCC 16) build corrupts memory during startup
# (search-path and console symbol tables) and crashes before the menu on Windows.
set -euo pipefail
D=$(cd "${1:?usage: build_windows.sh DEPS}" && pwd)
cd "$(dirname "$0")/../.."
build() {   # build OBJDIR GAME [extra make arguments]: eduke32-vr and the AMC Squad engine build, same settings
    local obj=$1 game=$2; shift 2
    PKG_CONFIG_LIBDIR=$D/pkgconfig make -j"$(nproc)" PLATFORM=WINDOWS CROSS=x86_64-w64-mingw32- NETCODE=1 HAVE_FLAC=0 \
        RENDERTYPE=SDL USE_OPENXR=1 USE_LIBVPX=1 OPENXR_CFLAGS="-I$D/include" OPENXR_LIBS="-L$D/lib -lopenxr_loader" LTO=0 \
        "$@" obj="$obj" duke3d_game="$game" "$game.exe"
}
build obj-winxr-nolto eduke32-xr-win
build obj-winxr-amc-nolto eduke32-xr-amc-win AMCSQUAD=1
mkdir -p "$D/out"
cp eduke32-xr-win.exe "$D/out/eduke32-vr.exe"
cp eduke32-xr-amc-win.exe "$D/out/eduke32-vr-amc.exe"
cp "$D/bin/openxr_loader.dll" "$D/bin/libopus-0.dll" "$D/out/"
