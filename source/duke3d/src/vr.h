// SPDX-License-Identifier: GPL-2.0-only
#pragma once
#include <cstdint>
// Stock weapons other than the calibrated pistol use one generic held MD3 per
// weapon on reserved tile XRHeldModelTileBase+weapon (no world ART exists).
// Flat builds use them too, for weapons held by 3D player models.
constexpr int32_t XRHeldModelTileBase=30020;
#ifdef USE_OPENXR
#include "player.h"
// Called once by each ordinary native display loop, before controls and after
// its intended world draw. Auxiliary room draws never acquire another XR frame.
void G_XRBeginFrame();
void G_XREndFrame();
void G_XRClearInput();
void G_XRResetAim(int playerNum);
bool G_XRBeginWeapon();
void G_XREndWeapon(bool captured);
enum class XRWeaponFamily { Unsupported, StockPistol, AAPistol, AARpg, StockHeld, HudMapped };
struct XRWeaponPresentation
{
    int32_t palette=0, shade=0, counter=0, reloading=0;
    XRWeaponFamily family=XRWeaponFamily::Unsupported;
};
// Stable asset identity, independent of HUD appearance and animation counters.
XRWeaponFamily P_XRWeaponFamily();
// Read-only native presentation sample; never advances weapon/animation state.
bool P_XRWeaponPresentation(XRWeaponPresentation &sample);
// Generic sample for a weapon whose held model was chosen from its HUD tiles.
bool P_XRMappedPresentation(XRWeaponPresentation &sample);
bool G_XRSuppressWeaponTile(int32_t tile, int32_t uniqueID);
void G_XRUpdateShotInput();
void G_XRApplyAim(input_t &input, bool yawAllowed, bool pitchAllowed);
// Tracked aim owns pitch completely (no stick pitch): native centering is moot.
bool G_XRTrackedPitchOwner();
// Build angle of the tracked head for audio listeners (voice chat); `fallback` outside VR.
int G_XRListenerAngle(int fallback);
fix16_t G_XRMovementAngle(fix16_t nativeAngle);
bool G_XRCrosshairPosition(vec2_t &position);
bool G_XRBeginCrosshair();
void G_XREndCrosshair(bool captured, vec2_t position, int32_t scale, int32_t flags, bool eventOnly);
void G_XRArmWorldDraw();
bool G_XRConsumeWorldDraw();
void G_XRBeginMenuPresentation();
void G_XRBeginScreenPresentation();
void G_XRArmMenuPresentation();
void G_XRCancelMenuPresentation();

// Experimental ordinary-room stereo oracle. True means the logical room pass
// was consumed, including failures after animation (never repeat CON effects).
bool G_XRDrawRooms(int32_t smoothRatio);
void G_XRTestAnimationInputs();
void G_XRTestBeginNative();
void G_XRTestCaptureNative();
bool G_XRCanAppendSprite(int32_t limit);
void G_XRInheritSprite(int32_t destination, int32_t parent);
#endif
