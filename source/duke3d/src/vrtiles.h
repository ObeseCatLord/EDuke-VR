// SPDX-License-Identifier: GPL-2.0-only
#pragma once
#include <cstdint>
#ifdef AMC_BUILD
# include "build.h"
#endif

// Tiles reserved for the VR layer (held weapon models, hands, body, laser, wheel, rings, tips,
// name tags). They are "logical" tile numbers 30000..30540 in the VR model packs and rig files.
// AMC Squad's own art uses that range, so the AMC build moves the whole block up by
// XR_TILE_OFFSET: 30000..30540 -> 50400..50940 (below MAXUSERTILES, 51200-256 = 50944).
// Model pack DEF files must be generated with the same offset (build_vr_def.py); the rig/profile
// text files keep the logical numbers and are shifted when read (XRTileFromFile).
#ifdef AMC_BUILD
constexpr int32_t XR_TILE_OFFSET = 20400;
#else
constexpr int32_t XR_TILE_OFFSET = 0;
#endif
constexpr int32_t XRTileLogicalFirst = 30000, XRTileLogicalLast = 30540;
constexpr int32_t XRTileFirst = XRTileLogicalFirst + XR_TILE_OFFSET, XRTileLast = XRTileLogicalLast + XR_TILE_OFFSET;
static_assert(XRTileLast < 51200 - 256 || XR_TILE_OFFSET == 0, "VR tiles must stay below MAXUSERTILES");

// A logical VR tile number (30000..30540) as the engine sees it.
constexpr int32_t XRTile(int32_t logical) { return logical + XR_TILE_OFFSET; }
// A tile number read from a pack/rig text file: VR tiles are shifted, stock tiles are unchanged.
constexpr int32_t XRTileFromFile(int32_t tile)
{
    return tile >= XRTileLogicalFirst && tile <= XRTileLogicalLast ? tile + XR_TILE_OFFSET : tile;
}
#ifdef AMC_BUILD
static_assert(XRTileFirst == ENGINE_RESERVED_TILE_FIRST, "build.h ENGINE_RESERVED_TILE_FIRST must match the VR tile block");
#endif
constexpr bool XRIsReservedTile(int32_t tile) { return tile >= XRTileFirst && tile <= XRTileLast; }
