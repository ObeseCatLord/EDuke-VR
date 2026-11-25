#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Native 64-bit ARM Linux build (Steam Frame on SteamOS, other arm64 Linux), run ON an arm64 machine:
#   package/vr/build_linux_arm64.sh OUT [WORK]
# Build on an old distribution (e.g. Ubuntu 20.04, glibc 2.31) so the result runs on newer ones.
# Needs gcc/g++, make, cmake 3.16+, curl and the dev packages of SDL2, Opus, libvpx, FLAC, GL and
# X11. The OpenXR loader (1.1 API) is built from the Khronos OpenXR-SDK source into WORK.
# OUT receives eduke32-vr, eduke32-vr-amc (the AMC Squad engine build, AMCSQUAD=1) and lib/ with the libraries it needs beyond the system's SDL2/GL/X11/
# ALSA/glibc: the layout of linux-arm64/ in the release archives and bundles.
set -euo pipefail
OPENXR_VERSION=1.1.60
out=${1:?usage: build_linux_arm64.sh OUT [WORK]}
work=${2:-$HOME/eduke32-vr-arm/deps}
src=$(cd "$(dirname "$0")/../.." && pwd)
[[ $(uname -m) == aarch64 ]] || { echo "build_linux_arm64: run this on an arm64 (aarch64) machine" >&2; exit 1; }
mkdir -p "$work"; work=$(cd "$work" && pwd)

if [[ ! -f $work/prefix/lib/libopenxr_loader.so.$OPENXR_VERSION ]]; then
    curl -fsSL -o "$work/openxr-sdk.tar.gz" "https://github.com/KhronosGroup/OpenXR-SDK/archive/refs/tags/release-$OPENXR_VERSION.tar.gz"
    rm -rf "$work/OpenXR-SDK-release-$OPENXR_VERSION" "$work/build"
    tar -xzf "$work/openxr-sdk.tar.gz" -C "$work"
    cmake -S "$work/OpenXR-SDK-release-$OPENXR_VERSION" -B "$work/build" -DCMAKE_BUILD_TYPE=Release -DDYNAMIC_LOADER=ON \
        -DBUILD_TESTS=OFF -DBUILD_API_LAYERS=OFF -DBUILD_WITH_SYSTEM_JSONCPP=OFF -DBUILD_WITH_WAYLAND_HEADERS=OFF \
        -DBUILD_WITH_XCB_HEADERS=OFF -DCMAKE_INSTALL_PREFIX="$work/prefix"
    make -C "$work/build" -j"$(nproc)" openxr_loader
    make -C "$work/build" install
fi

cd "$src"
PKG_CONFIG_PATH="$work/prefix/lib/pkgconfig" make -j"$(nproc)" NETCODE=1 USE_OPENXR=1 obj=obj-xr duke3d_game=eduke32-xr eduke32-xr
# AMC Squad's engine build (USE_LIBVPX defaults to 1: its 67 IVF cutscenes need libvpx, checked below).
PKG_CONFIG_PATH="$work/prefix/lib/pkgconfig" make -j"$(nproc)" NETCODE=1 USE_OPENXR=1 AMCSQUAD=1 obj=obj-xr-amc duke3d_game=eduke32-xr-amc eduke32-xr-amc

rm -rf "$out"; mkdir -p "$out/lib"
cp eduke32-xr "$out/eduke32-vr"
cp eduke32-xr-amc "$out/eduke32-vr-amc"
cp -L "$work/prefix/lib/libopenxr_loader.so.1" "$out/lib/"
# Codec libraries whose sonames SteamOS and newer distributions do not have (or may not install).
for lib in libopus.so.0 libvpx.so.6 libFLAC.so.8 libogg.so.0; do
    path=$(LD_LIBRARY_PATH="$out/lib" ldd "$out/eduke32-vr" | awk -v l="$lib" '$1==l {print $3}')
    [[ -n $path ]] && cp -L "$path" "$out/lib/$lib"
done
for exe in eduke32-vr eduke32-vr-amc; do
    LD_LIBRARY_PATH="$out/lib" ldd "$out/$exe" | grep -q "not found" && { echo "build_linux_arm64: missing libraries for $exe" >&2; exit 1; }
    LD_LIBRARY_PATH="$out/lib" ldd "$out/$exe" | grep -q "libvpx" || { echo "build_linux_arm64: $exe does not link libvpx (AMC Squad cutscenes)" >&2; exit 1; }
done
echo "built $out: $(ls "$out/lib" | tr '\n' ' ')"
