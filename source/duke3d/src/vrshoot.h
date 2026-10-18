// SPDX-License-Identifier: GPL-2.0-only
#pragma once
#include <cstddef>
#include <cstdint>
#include "player.h"

// Optional native movement-update extension, independent of OpenXR/graphics.
// Direction uses physical world X/Y/Z-down axes; offset uses native Build units.
struct VRShotInput
{
    int16_t offset[3] {}, direction[3] {};
    uint8_t flags=0;
};
constexpr uint8_t VRShotEnabled=1, VRShotValid=2;
constexpr size_t VRShotWireSize=14;
constexpr uint8_t VRShotFeatureRPG=1, VRShotFeatureHitscan=2, VRShotFeatureFreezeShrink=4;
constexpr uint8_t VRShotFeatureHandBomb=8;
bool G_VRValidateShot(VRShotInput const &input);
bool G_VRDecodeShot(uint8_t const *bytes, size_t size, VRShotInput &input);
void G_VREncodeShot(VRShotInput const &input, uint8_t *bytes);
void G_VRSetShotInput(int player, VRShotInput const &input);
VRShotInput G_VRGetShotInput(int player);
void G_VRResetShot(int player, bool preserveMode=false);
void G_VRResetShots();
bool G_VRShotEnabled(int player);
// Required firing/presentation capability, or zero for an unsupported replacement.
uint8_t G_VRHandShotFeature(int player, int tile=-1);
bool G_VRShotReady(int player);
bool G_VRShotCanFire(int player);
// Reuse the existing release-to-rearm latch after a rejected spatial throw.
void G_VRBlockShot(int player);
void G_VRFilterShotInput(int player, input_t &input);
// Revalidated on both client and authoritative server. Never move player state.
// An optional native muzzle point is constrained from the same body anchor.
bool G_VRResolveShot(int player, vec3_t &position, int16_t &sector, bool &clamped, vec3_t const *muzzlePosition=nullptr);
