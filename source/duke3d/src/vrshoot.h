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
    int16_t head[3] {}; // head forward (same axes): the mighty foot kicks where you look
    uint8_t flags=0;
};
constexpr uint8_t VRShotEnabled=1, VRShotValid=2;
// Immersive pipebombs ride spare flag bits of the same 20-byte sample:
// bits 2..5 throw speed (0 = no physical throw, n*0.75 m/s), bit 6 physical
// throwing mode, bit 7 off-hand detonate request.
constexpr uint8_t VRShotThrowShift=2, VRShotThrowMask=0x3c, VRShotPhysical=0x40, VRShotDetonate=0x80;
constexpr float VRShotThrowStep=.75f; // metres/second per speed unit
constexpr size_t VRShotWireSize=20;
constexpr uint8_t VRShotFeatureRPG=1, VRShotFeatureHitscan=2, VRShotFeatureFreezeShrink=4;
constexpr uint8_t VRShotFeatureHandBomb=8, VRShotFeatureTripmine=16;
constexpr uint8_t VRShotFeatureMelee=32;
constexpr uint8_t VRShotFeatureFireball=64;
bool G_VRValidateShot(VRShotInput const &input);
bool G_VRDecodeShot(uint8_t const *bytes, size_t size, VRShotInput &input);
void G_VREncodeShot(VRShotInput const &input, uint8_t *bytes);
void G_VRSetShotInput(int player, VRShotInput const &input);
VRShotInput G_VRGetShotInput(int player);
void G_VRResetShot(int player, bool preserveMode=false);
void G_VRResetShots();
bool G_VRShotEnabled(int player);
// Physical throw speed of this sample as a native pipebomb xvel, or 0.
int G_VRShotThrowVelocity(int player);
bool G_VRShotPhysicalThrow(int player);
bool G_VRShotDetonate(int player);
// Required firing/presentation capability, or zero for an unsupported replacement.
uint8_t G_VRHandShotFeature(int player, int tile=-1);
bool G_VRShotReady(int player);
bool G_VRShotValid(int player);
bool G_VRShotCanFire(int player);
// Native shared keys run before P_ProcessInput's release/readiness filter.
bool G_VRQuickKickBlocked(int player);
// Reuse the existing release-to-rearm latch after a rejected spatial throw.
void G_VRBlockShot(int player);
void G_VRFilterShotInput(int player, input_t &input);
// Revalidated on both client and authoritative server. Never move player state.
// An optional native muzzle point is constrained from the same body anchor.
bool G_VRResolveShot(int player, vec3_t &position, int16_t &sector, bool &clamped, vec3_t const *muzzlePosition=nullptr);

// Tracked body pose that other players need to draw this player's VR body: head, both hands with
// their finger pose and the held 3D weapon. Presentation only (it never changes game state): sent
// unreliably with every client update and relayed by the server to everyone else.
// Offsets are Build units from the sender's view position; frame axes are three columns of Build
// units per metre, divided by (384, 384, 6144) and stored *VRBodyAxisScale.
struct VRBodyFrame { int16_t root[3] {}; int16_t axes[9] {}; };
struct VRBodyPose
{
    uint16_t sequence=0;
    uint8_t flags=0;
    uint8_t hand[2] {};     // VRHand* finger pose source
    uint8_t pull[2] {};     // index finger trigger curl of a hold pose, 0..255
    uint8_t kick=0;         // mighty foot leg extension, 0..255
    int16_t bodyAngle=0;    // the body's facing relative to the player's native angle, Build angle units * 16
    int16_t eye[3] {};      // Build offset of the eye
    int16_t headForward[3] {}, headUp[3] {};   // unit*32767: Build x, y and up (isotropic)
    VRBodyFrame handFrame[2] {};   // grip frame for named poses, weapon frame for a hold
    int16_t weaponTile=-1, weaponFrame=0, weaponNextFrame=0;
    uint8_t weaponLerp=0;
    VRBodyFrame weapon {};  // held model frame (MD3 axes, pivot applied)
};
constexpr uint8_t VRBodyHead=1, VRBodyWeapon=2;
enum : uint8_t { VRHandNone, VRHandRelaxed, VRHandTrigger, VRHandPoint, VRHandFist, VRHandHold, VRHandKinds };
constexpr size_t VRBodyWireSize=108;
constexpr float VRBodyAxisScale=8192.f;
bool G_VRDecodeBodyPose(uint8_t const *bytes, size_t size, VRBodyPose &pose);
void G_VREncodeBodyPose(VRBodyPose const &pose, uint8_t *bytes);
// XR peers publish their pose each frame; the network sends each new one once.
void G_VRPublishBodyPose(VRBodyPose const &pose);
bool G_VRTakeBodyPose(uint8_t *bytes);
// Received poses (newest sequence wins), and the latest one no older than maxAge seconds.
void G_VRStoreBodyPose(int player, VRBodyPose const &pose);
bool G_VRGetBodyPose(int player, VRBodyPose &pose, double maxAge);
void G_VRResetBodyPoses();
