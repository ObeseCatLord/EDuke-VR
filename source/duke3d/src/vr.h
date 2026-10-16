// SPDX-License-Identifier: GPL-2.0-only
#pragma once
#include <cstdint>
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
void G_XRUpdateShotInput();
void G_XRApplyAim(input_t &input, bool yawAllowed, bool pitchAllowed);
fix16_t G_XRMovementAngle(fix16_t nativeAngle);
bool G_XRCrosshairPosition(vec2_t &position);
bool G_XRBeginCrosshair();
void G_XREndCrosshair(bool captured, vec2_t position, int32_t scale, int32_t flags);
void G_XRArmWorldDraw();
bool G_XRConsumeWorldDraw();
void G_XRBeginMenuPresentation();
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
