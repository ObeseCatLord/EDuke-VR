#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Cross-build the Windows game (desktop + OpenXR VR, voice chat) with MinGW-w64:
#   package/vr/build_windows.sh DEPS
# DEPS holds include/{opus,openxr}, lib/{libopus.a,libopenxr_loader.a} (an import library made
# from openxr_loader.dll with dlltool), pkgconfig/opus.pc and bin/{openxr_loader.dll,libopus-0.dll}.
# Writes DEPS/out/eduke32-vr.exe beside copies of those two DLLs.
set -euo pipefail
D=$(cd "${1:?usage: build_windows.sh DEPS}" && pwd)
cd "$(dirname "$0")/../.."
PKG_CONFIG_LIBDIR=$D/pkgconfig make -j"$(nproc)" PLATFORM=WINDOWS CROSS=x86_64-w64-mingw32- NETCODE=1 HAVE_FLAC=0 \
    RENDERTYPE=SDL USE_OPENXR=1 OPENXR_CFLAGS="-I$D/include" OPENXR_LIBS="-L$D/lib -lopenxr_loader" \
    obj=obj-winxr duke3d_game=eduke32-xr-win eduke32-xr-win.exe
mkdir -p "$D/out"
cp eduke32-xr-win.exe "$D/out/eduke32-vr.exe"
cp "$D/bin/openxr_loader.dll" "$D/bin/libopus-0.dll" "$D/out/"
