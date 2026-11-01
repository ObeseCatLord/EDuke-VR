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
// A flat screen waiting for a button without drawing: show it again and poll the controllers.
void G_XRHoldFlatFrame();
void G_XRResetAim(int playerNum);
bool G_XRBeginWeapon();
void G_XREndWeapon(bool captured);
// The headset world is up with hand-held weapon ART requested: native weapon ART is never drawn on the HUD.
bool G_XRHideHudWeapon();
// Status bar on the wrists (EDUKE32_XR_WRIST_HUD): bracket G_DrawStatusBar; while active the
// status bar uses the mini (alternative) layout so each wrist gets its own half.
bool G_XRBeginWristHud();
void G_XREndWristHud(bool captured);
bool G_XRWristHudActive();
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
// VR 3D models on (vr_models cvar, EDUKE32_XR_MODELS, usemodels); off = native 2D sprites.
bool G_XRModelsEnabled();
// VR settings (cvars) and model sets for the settings menu.
extern int32_t vr_models, vr_laser, vr_fullbody, vr_lefttrigger, vr_ptt_button, vr_twohand, vr_menupointer, vr_ptt_radio, vr_voxeldistance;
extern int32_t vr_foveation, vr_foveation_level;
char const *G_XRFoveationAutoName();   // "Auto (eye-tracked)" on a Steam Frame, else "Auto (off)"
int G_XRModelSetCount();
char const *G_XRModelSetTitle(int index);
int G_XRLoadedModelSet();
int G_XRChosenModelSet();
bool G_XRChooseModelSet(int index);       // records the choice; true if a restart is needed to load it
bool G_XRCanRestartForModelSet();         // a different set is chosen and the launcher can relaunch
bool G_XRRequestModelSetRestart();        // asks the launcher to relaunch with it (then quit the game)
void G_XRRegisterCvars();
void G_XRWorldModelToggle(int spriteNum, int picnum);
void G_XRDrawWheelPanels(); // 2D wheel icons on a panel at the ring (gadgets; weapons without 3D models)
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
void G_XRPrepareDesktopBodies(int32_t smoothRatio);   // desktop play: other players' VR bodies (before the masks)
void G_XRDrawDesktopBodies();                         // ... drawn after them
bool G_XRCanAppendSprite(int32_t limit);
void G_XRInheritSprite(int32_t destination, int32_t parent);
#endif
