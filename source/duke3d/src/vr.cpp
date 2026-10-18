// SPDX-License-Identifier: GPL-2.0-only
// Copyright (C) 2026 EDuke32 VR contributors
#ifdef USE_OPENXR
#include "duke3d.h"
#include "sdlayer.h"
#include "vr.h"
#include "vrshoot.h"
#include "network.h"
#include "menus.h"
#include "../../vr/eduke_xr.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <vector>

namespace
{
constexpr float Pi = 3.14159265358979323846f;
// RazeXR's 24 world units/metre; Build horizontal and Z scales are 16 and 256.
constexpr float UnitsPerMetre = 384.f, ZUnitsPerMetre = 6144.f;
struct Camera
{
    vec3_t pos;
    fix16_t angle, horizon;
    int16_t sector;
    float roll;
};
Camera camera()
{
    return {CAMERA(pos), CAMERA(q16ang), CAMERA(q16horiz), CAMERA(sect), gtang};
}
void install(Camera const &c)
{
    CAMERA(pos) = c.pos;
    CAMERA(q16ang) = c.angle;
    CAMERA(q16horiz) = c.horizon;
    CAMERA(sect) = c.sector;
    gtang = c.roll;
}
XrQuaternionf multiply(XrQuaternionf a, XrQuaternionf b)
{
    return {a.w*b.x+a.x*b.w+a.y*b.z-a.z*b.y,
            a.w*b.y-a.x*b.z+a.y*b.w+a.z*b.x,
            a.w*b.z+a.x*b.y-a.y*b.x+a.z*b.w,
            a.w*b.w-a.x*b.x-a.y*b.y-a.z*b.z};
}
XrVector3f rotate(XrQuaternionf q, XrVector3f v)
{
    auto r = multiply(multiply(q, {v.x,v.y,v.z,0}), {-q.x,-q.y,-q.z,q.w});
    return {r.x,r.y,r.z};
}
float dot(XrVector3f a, XrVector3f b) { return a.x*b.x+a.y*b.y+a.z*b.z; }
XrVector3f cross(XrVector3f a, XrVector3f b)
{
    return {a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x};
}
struct Eye
{
    Camera camera;
    float left, right, down, up, cover;
    std::vector<tspritetype> sprites;
    std::vector<int16_t> walls;
    std::array<uint8_t, sizeof(gotsector)> sectors;
};
static std::array<uint8_t, MAXSPRITESONSCREEN> membership;
static bool animating, generationSaturated;
static uint64_t worldFrames, worldMultiviewFrames, worldOracleFrames;
static uint64_t worldMaskMultiviewFrames, worldMaskOracleFrames, worldFullMultiviewFrames;
static eduke_xr::Runtime *previousRuntime;
static uint64_t worldGeneration;
static eduke_xr::Runtime *pendingRuntime, *inputRuntime;
static eduke_xr::Runtime::Frame pendingFrame;
static uint64_t pendingGeneration, inputGeneration;
static bool worldDrawArmed;
static eduke_xr::Runtime *presentationRuntime;
static uint64_t presentationGeneration;
struct WorldReceipt
{
    eduke_xr::Runtime *runtime=nullptr;
    uint64_t generation=0, serial=0;
    bool opaque=false, masks=false;
};
static WorldReceipt worldReceipt;

static void accountWorldFrame(bool opaque, bool masks, bool fixture)
{
    ++worldFrames;
    if (opaque) ++worldMultiviewFrames; else ++worldOracleFrames;
    if (masks) ++worldMaskMultiviewFrames; else ++worldMaskOracleFrames;
    if (opaque && masks) ++worldFullMultiviewFrames;
    if (!fixture && worldFrames==60)
        LOG_F(INFO,"OpenXR world oracle: 60 frames, opaque multiview=%u twoPass=%u; masks multiview=%u twoPass=%u full multiview=%u; one animation transaction per frame.",
              unsigned(worldMultiviewFrames),unsigned(worldOracleFrames),unsigned(worldMaskMultiviewFrames),
              unsigned(worldMaskOracleFrames),unsigned(worldFullMultiviewFrames));
}

static bool overlayEnabled()
{
    auto enabled=std::getenv("EDUKE32_XR_UI");
    return enabled && !Bstrcmp(enabled,"2");
}
static eduke_xr::Runtime *menuRuntime;
static uint64_t menuGeneration, menuOwner;
// Geometry from the same acquired world frame; no separate presentation owner.
static struct { float matrix[2][16]; vec3_t eye[2]; bool valid=false; } crosshairViews;
static eduke_xr::ActionInput rawInput;
static std::array<uint32_t,2> activeInputButtons{}, blockedInputButtons{};
static float aimYawOffset, aimPitchOffset;
static bool aimPoseWasValid, shotLookAllowed=true;
static bool shotReferenceInvalidated;
static bool handShotsRequested()
{
    auto mode=std::getenv("EDUKE32_XR_HAND_SHOTS");
    return mode && !Bstrcmp(mode,"1");
}

// Opt-in while tracked weapon presentation and the full authority matrix develop.
static int aimHand()
{
    auto mode=std::getenv("EDUKE32_XR_AIM");
    if (!mode) return -2;
    if (!Bstrcmp(mode,"head")) return -1;
    if (!Bstrcmp(mode,"left")) return 0;
    return !Bstrcmp(mode,"right") ? 1 : -2;
}

static bool inputValid()
{
    // Native polling may recreate the SDL context after this sample was taken.
    // This callback reads identity only; it never polls or initializes XR.
    return inputRuntime && inputRuntime->generation() == inputGeneration && rawInput.focused;
}

static bool validPose(XrPosef pose)
{
    auto const q=pose.orientation;
    float const length=q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w;
    return std::isfinite(length) && length>.9f && length<1.1f
        && std::isfinite(pose.position.x) && std::isfinite(pose.position.y) && std::isfinite(pose.position.z);
}

static bool aimPoseUsable()
{
    int const hand=aimHand();
    return hand!=-2 && inputValid() && rawInput.headValid && validPose(rawInput.headPose)
        && (hand<0 || (rawInput.hands[hand].aimValid && validPose(rawInput.hands[hand].aimPose)));
}

static XrVector2f inputStick(eduke_xr::HandInput const &hand)
{
    if (!hand.stickActive || !std::isfinite(hand.stick.x) || !std::isfinite(hand.stick.y)) return {};
    float const length=std::hypot(hand.stick.x,hand.stick.y);
    if (length <= .2f) return {};
    float const scale=(std::min(length,1.f)-.2f)/(.8f*length);
    return {hand.stick.x*scale,hand.stick.y*scale};
}

static void publishInput()
{
    using namespace eduke_xr;
    uint32_t down[2]{};
    for (unsigned hand=0;hand<2;++hand)
    {
        uint32_t const active=rawInput.hands[hand].activeButtons;
        uint32_t const held=rawInput.hands[hand].buttons & active;
        blockedInputButtons[hand] |= held & ~activeInputButtons[hand];
        blockedInputButtons[hand] &= held;
        activeInputButtons[hand]=active;
        down[hand]=held & ~blockedInputButtons[hand];
    }
    if (aimHand()!=-2)
    {
        bool const valid=aimPoseUsable() && (!handShotsRequested() || Net_VRShotAvailable());
        // Pose recovery is not a new trigger press. Hold fire until release.
        if (!valid || !aimPoseWasValid)
        {
            blockedInputButtons[1] |= rawInput.hands[1].buttons & (ButtonSelect|ButtonStickClick);
            down[1] &= ~(ButtonSelect|ButtonStickClick);
        }
        aimPoseWasValid=valid;
    }
    auto const move=inputStick(rawInput.hands[0]), turn=inputStick(rawInput.hands[1]);
    ControlInfo analog{};
    analog.dx=std::lround(move.x*32767.f); analog.dz=std::lround(-move.y*32767.f);
    // These are native joystick units, retaining native Strafe/AimWeight/locks.
    analog.dyaw=std::lround(turn.x*16383.f); analog.dpitch=std::lround(-turn.y*16383.f);
    uint64_t buttons=0;
    auto const button=[&](bool pressed, unsigned gamefunc) { if (pressed) buttons |= uint64_t(1)<<gamefunc; };
    button(down[1]&ButtonSelect,gamefunc_Fire); button(down[0]&ButtonSelect,gamefunc_Open);
    button(down[1]&ButtonPrimary,gamefunc_Jump); button(down[1]&ButtonSecondary,gamefunc_Crouch);
    button(down[1]&ButtonStickClick,gamefunc_Quick_Kick);
    button(down[0]&ButtonPrimary,gamefunc_Previous_Weapon); button(down[0]&ButtonSecondary,gamefunc_Next_Weapon);
    button((down[0]|down[1])&ButtonGrip,gamefunc_Run);
    UserInput menu{false,false,false,dir_None};
    menu.b_advance=(down[0]|down[1])&(ButtonSelect|ButtonPrimary);
    menu.b_return=(down[0]|down[1])&ButtonSecondary;
    menu.b_escape=(down[0]|down[1])&ButtonMenu;
    auto const nav=std::hypot(move.x,move.y) > .6f ? move : turn;
    if (std::max(std::fabs(nav.x),std::fabs(nav.y)) > .6f)
        menu.dir=std::fabs(nav.y) >= std::fabs(nav.x) ? (nav.y > 0 ? dir_Up : dir_Down) : (nav.x > 0 ? dir_Right : dir_Left);
    CONTROL_SetExternalInput(&analog,buttons,&menu,inputValid);

    if (auto trace=std::getenv("EDUKE32_XR_TEST_INPUT"))
        if (!Bstrcmp(trace,"1"))
        {
            static std::string previous;
            static uint32_t sample;
            char state[384];
            Bsnprintf(state,sizeof(state),"focus=%u active=%u,%u buttons=%u,%u funcs=%llu axes=%d,%d,%d,%d menu=%u,%u,%u,%d gm=%u screen=%d aim=%u,%u gen=%llu",
                      rawInput.focused,rawInput.hands[0].activeButtons,rawInput.hands[1].activeButtons,down[0],down[1],
                      (unsigned long long)buttons,analog.dx,analog.dz,analog.dyaw,analog.dpitch,
                      menu.b_advance,menu.b_return,menu.b_escape,int(menu.dir),unsigned(g_player[myconnectindex].ps->gm),int(g_currentMenu),
                      rawInput.hands[0].aimValid,rawInput.hands[1].aimValid,(unsigned long long)inputGeneration);
            if (previous != state || sample%60 == 0)
            {
                LOG_F(INFO,"OpenXR input: sample=%u %s",sample,state);
                previous=state;
            }
            ++sample;
        }
}

static XrVector3f origin;
static XrQuaternionf inverseYaw;
static bool recentered, trackingRebase, lastHeadValid;
static XrPosef lastHeadPose;

static void setTrackingReference(XrPosef const &head)
{
    auto const forward=rotate(head.orientation,{0,0,-1});
    float yaw=std::atan2(-forward.x,-forward.z);
    XrVector3f displacement{};
    if (trackingRebase && lastHeadValid)
    {
        // LOCAL can acquire a different origin/yaw in a replacement session.
        // Retain virtual calibration, not stale action validity or a second body.
        auto const previous=rotate(inverseYaw,rotate(lastHeadPose.orientation,{0,0,-1}));
        yaw+=std::atan2(previous.x,-previous.z);
        displacement=rotate(inverseYaw,{lastHeadPose.position.x-origin.x,
                                       lastHeadPose.position.y-origin.y,lastHeadPose.position.z-origin.z});
    }
    inverseYaw={0,-std::sin(yaw*.5f),0,std::cos(yaw*.5f)};
    auto const localDisplacement=rotate({-inverseYaw.x,-inverseYaw.y,-inverseYaw.z,inverseYaw.w},displacement);
    origin={head.position.x-localDisplacement.x,head.position.y-localDisplacement.y,head.position.z-localDisplacement.z};
    recentered=true; trackingRebase=false; lastHeadValid=true; lastHeadPose=head;
}

static float wrapRadians(float angle) { return std::remainder(angle,2.f*Pi); }
static float nativePitch(fix16_t horizon) { return std::atan((fix16_to_float(horizon)-100.f)/128.f); }
static float clampNativePitch(float pitch)
{
    return std::max(nativePitch(F16(HORIZ_MIN)),std::min(pitch,nativePitch(F16(HORIZ_MAX))));
}
static XrQuaternionf pitchRoll(float pitch, float roll)
{
    return multiply({std::sin(pitch*.5f),0,0,std::cos(pitch*.5f)},
                    {0,0,std::sin(roll*.5f),std::cos(roll*.5f)});
}
static bool localAimCamera()
{
    auto const p=g_player[myconnectindex].ps;
    return aimHand()!=-2 && inputRuntime && inputRuntime->generation()==inputGeneration
        && screenpeek==myconnectindex && !ud.recstat && (p->gm & MODE_GAME)
        && p->newowner<0 && ud.camerasprite<0 && !p->over_shoulder_on;
}
static Camera aimBodyCamera(Camera c)
{
    if (localAimCamera())
    {
        c.angle=(c.angle-fix16_from_float(aimYawOffset*1024.f/Pi)) & 0x7FFFFFF;
        c.horizon=fix16_from_float(100.f+128.f*std::tan(nativePitch(c.horizon)-aimPitchOffset));
    }
    return c;
}

bool testFailure(char const *point)
{
    static bool injected;
    char const *requested = std::getenv("EDUKE32_XR_TEST_FAIL");
    if (!injected && requested && !Bstrcmp(requested,point))
    {
        injected=true;
        return true;
    }
    return false;
}


bool makeEye(XrView const &view, Camera const &base, float aspect, Eye &eye)
{
    float const pitch = std::atan((fix16_to_float(base.horizon)-100.f)/128.f);
    XrQuaternionf const bodyPitch {std::sin(pitch*.5f),0,0,std::cos(pitch*.5f)};
    // Native camera rotation is pitch * roll; positive native roll uses +Z in
    // XR's right/up/back coordinates. One rigid transform applies to both the
    // eye position and orientation before conversion to Build's unequal units.
    XrQuaternionf const bodyRoll {0,0,std::sin(base.roll*.5f),std::cos(base.roll*.5f)};
    auto const trackingRotation = multiply(multiply(bodyPitch,bodyRoll),inverseYaw);
    auto const p = rotate(trackingRotation, {view.pose.position.x-origin.x,
                                           view.pose.position.y-origin.y, view.pose.position.z-origin.z});
    float const body = fix16_to_float(base.angle)*Pi/1024.f;
    float const co = std::cos(body), si = std::sin(body);
    eye.camera = base;
    eye.camera.pos.x += std::lround((-p.z*co-p.x*si)*UnitsPerMetre);
    eye.camera.pos.y += std::lround((-p.z*si+p.x*co)*UnitsPerMetre);
    eye.camera.pos.z -= std::lround(p.y*ZUnitsPerMetre);
    updatesectorz(eye.camera.pos.x,eye.camera.pos.y,eye.camera.pos.z,&eye.camera.sector);
    if (eye.camera.sector < 0 || !cansee(base.pos.x,base.pos.y,base.pos.z,base.sector,
        eye.camera.pos.x,eye.camera.pos.y,eye.camera.pos.z,eye.camera.sector))
        return false;  // Camera collision/fade policy is a subsequent gameplay slice.

    auto const q = multiply(trackingRotation,view.pose.orientation);
    auto forward = rotate(q,{0,0,-1});
    float const horizontal = std::hypot(forward.x,forward.z);
    if (horizontal < 1e-4f)
        return false;
    XrVector3f const right {-forward.z/horizontal,0,forward.x/horizontal};
    auto const up = cross(right,forward);
    auto actualRight = rotate(q,{1,0,0});
    eye.camera.angle = fix16_from_float((body+std::atan2(forward.x,-forward.z))*1024.f/Pi);
    eye.camera.horizon = fix16_from_float(100.f+128.f*forward.y/horizontal);
    eye.camera.roll = std::atan2(dot(actualRight,up),dot(actualRight,right));
    eye.left = std::tan(view.fov.angleLeft); eye.right = std::tan(view.fov.angleRight);
    eye.down = std::tan(view.fov.angleDown); eye.up = std::tan(view.fov.angleUp);
    eye.cover = std::max({std::fabs(eye.left),std::fabs(eye.right),
                         std::fabs(eye.down)*aspect,std::fabs(eye.up)*aspect});
    if (!(eye.cover > 0.f && eye.cover < 16.f))
        return false;
    // Native Polymost clips CPU rays to the yaw-forward half-space. Reject an
    // unsupported frame instead of silently clamping tracked head orientation.
    XrVector3f const yawForward {forward.x/horizontal,0,forward.z/horizontal};
    for (float x : {eye.left,eye.right})
        for (float y : {eye.down,eye.up})
            if (dot(rotate(q,{x,y,-1}),yawForward) <= .001f)
                return false;
    return true;
}
void eyeState(Eye const &eye)
{
    install(eye.camera);
    renderSetAspect(std::lround(eye.cover*65536.f),81920);
    polymost_xrProjection(eye.left,eye.right,eye.down,eye.up);
}
} // namespace

void G_XRResetAim(int playerNum)
{
    if (playerNum!=myconnectindex || aimHand()==-2) return;
    aimYawOffset=aimPitchOffset=0;
    aimPoseWasValid=false;
    recentered=trackingRebase=lastHeadValid=false;
}

void G_XRApplyAim(input_t &input, bool yawAllowed, bool pitchAllowed)
{
    if (!localAimCamera()) return;
    shotLookAllowed=yawAllowed && pitchAllowed;
    // Native centering must not reactivate merely because a tracked source is
    // temporarily unavailable. The XR context retains look-mode ownership.
    input.bits|=uint32_t(1)<<SK_AIMMODE;
    input.extbits &= ~(BIT(EK_GAMEPAD_CENTERING)|BIT(EK_GAMEPAD_AIM_ASSIST));
    if (!aimPoseUsable()) return;
    if (!recentered) setTrackingReference(rawInput.headPose);
    auto const p=g_player[myconnectindex].ps;
    // Recover the independent body from native authority, retaining native
    // joystick/mouse turning. Tracking deltas are displacements, not rates.
    float const bodyYaw=fix16_to_float(p->q16ang)*Pi/1024.f-aimYawOffset+fix16_to_float(input.q16avel)*Pi/1024.f;
    float const oldPitch=nativePitch(p->q16horiz);
    float const nativePitchDelta=fix16_to_float(input.q16horz)*Pi/512.f;
    float const bodyPitch=clampNativePitch(oldPitch-aimPitchOffset+(pitchAllowed ? nativePitchDelta : 0.f));
    int const hand=aimHand();
    auto const pose=hand<0 ? rawInput.headPose : rawInput.hands[hand].aimPose;
    auto const q=multiply(multiply(pitchRoll(bodyPitch,gtang),inverseYaw),pose.orientation);
    auto const forward=rotate(q,{0,0,-1});
    float const horizontal=std::hypot(forward.x,forward.z);
    // Yaw is undefined at the pole; retain its last value while native pitch
    // still reaches its supported limit. Never leave a vertical pose stale.
    float const yaw=horizontal<1e-4f ? aimYawOffset : std::atan2(forward.x,-forward.z);
    float const pitch=std::atan2(forward.y,horizontal);
    if (yawAllowed)
    {
        input.q16avel=fix16_sadd(input.q16avel,fix16_from_float(wrapRadians(yaw-aimYawOffset)*1024.f/Pi));
        aimYawOffset=yaw;
    }
    if (pitchAllowed)
    {
        float const target=clampNativePitch(pitch);
        input.q16horz=fix16_from_float((target-oldPitch)*512.f/Pi);
        aimPitchOffset=target-bodyPitch;
    }
    if (std::getenv("EDUKE32_XR_TEST_AIM"))
        LOG_F(INFO,"OpenXR aim: yawOffset=%.6f pitchOffset=%.6f bodyYaw=%.6f bodyPitch=%.6f inputYaw=%d inputPitch=%d hand=%d.",
              aimYawOffset,aimPitchOffset,bodyYaw,bodyPitch,
              input.q16avel,input.q16horz,hand);
}

void G_XRUpdateShotInput()
{
    VRShotInput input;
    // A live session with temporarily lost tracking remains fail-closed.
    // Terminal initialization/presentation failure returns to native flat
    // controls, so an invalid hand pose must not suppress keyboard fire there.
    if (handShotsRequested() && videoGetRenderMode()==REND_POLYMOST && sdlayer_xr_worldActive())
    {
        input.flags=VRShotEnabled;
        int const hand=aimHand();
        if (hand>=0 && localAimCamera() && aimPoseUsable() && recentered && shotLookAllowed
            && !shotReferenceInvalidated && !(blockedInputButtons[1]&(eduke_xr::ButtonSelect|eduke_xr::ButtonStickClick)) && Net_VRShotAvailable())
        {
            auto const p=g_player[myconnectindex].ps;
            float const bodyYaw=fix16_to_float(p->q16ang)*Pi/1024.f-aimYawOffset;
            float const co=std::cos(bodyYaw), si=std::sin(bodyYaw);
            auto const tracking=multiply(pitchRoll(nativePitch(p->q16horiz)-aimPitchOffset,gtang),inverseYaw);
            auto const &pose=rawInput.hands[hand].aimPose;
            auto const local=rotate(tracking,{pose.position.x-origin.x,pose.position.y-origin.y,pose.position.z-origin.z});
            auto const forward=rotate(multiply(tracking,pose.orientation),{0,0,-1});
            float const offsets[3]={(-local.z*co-local.x*si)*UnitsPerMetre,(-local.z*si+local.x*co)*UnitsPerMetre,-local.y*ZUnitsPerMetre};
            float const direction[3]={-forward.z*co-forward.x*si,-forward.z*si+forward.x*co,-forward.y};
            bool bounded=true;
            for (int i=0;i<3;++i)
            {
                bounded=bounded && std::isfinite(offsets[i]) && std::fabs(offsets[i])<32767.f;
                if (bounded) input.offset[i]=int16_t(std::lround(offsets[i]));
                input.direction[i]=int16_t(std::lround(std::max(-1.f,std::min(1.f,direction[i]))*32767.f));
            }
            input.flags|=VRShotValid;
            if (!bounded || !G_VRValidateShot(input)) { input={}; input.flags=VRShotEnabled; }
        }
        else if (!Net_VRShotAvailable())
        {
            static bool reported;
            if (!reported) { reported=true; LOG_F(WARNING,"VR hand shots waiting for server capability; firing is suppressed until supported."); }
        }
    }
    G_VRSetShotInput(myconnectindex,input);
    shotReferenceInvalidated=false; // One native sample conveys the unknown reference reset.
}

fix16_t G_XRMovementAngle(fix16_t nativeAngle)
{
    return localAimCamera() ? (nativeAngle-fix16_from_float(aimYawOffset*1024.f/Pi)) & 0x7FFFFFF : nativeAngle;
}

bool G_XRCrosshairPosition(vec2_t &position)
{
    if (!localAimCamera() || !inputRuntime) return true;
    if (!aimPoseUsable() || !recentered) return false;
    auto const logical=camera(), body=aimBodyCamera(logical);
    auto const p=g_player[myconnectindex].ps;
    float const pitch=nativePitch(p->q16horiz+p->q16horizoff);
    auto const ray=[&](Camera const &base, XrQuaternionf view) {
        float const yaw=fix16_to_float(p->q16ang-base.angle)*Pi/1024.f;
        XrVector3f const direction{std::sin(yaw)*std::cos(pitch),std::sin(pitch),-std::cos(yaw)*std::cos(pitch)};
        return rotate({-view.x,-view.y,-view.z,view.w},direction);
    };
    auto const flat=ray(logical,pitchRoll(nativePitch(logical.horizon),logical.roll));
    auto const head=multiply(multiply(pitchRoll(nativePitch(body.horizon),body.roll),inverseYaw),rawInput.headPose.orientation);
    auto tracked=ray(body,head);
    if (handShotsRequested() && G_VRHandShotFeature(myconnectindex))
    {
        if (!G_VRShotReady(myconnectindex)) return false;
        auto const shot=G_VRGetShotInput(myconnectindex);
        float const yaw=fix16_to_float(body.angle)*Pi/1024.f, co=std::cos(yaw), si=std::sin(yaw);
        XrVector3f const direction={(-shot.direction[0]*si+shot.direction[1]*co)/32767.f,-shot.direction[2]/32767.f,
                                   (-shot.direction[0]*co-shot.direction[1]*si)/32767.f};
        tracked=rotate({-head.x,-head.y,-head.z,head.w},direction);
    }
    if (flat.z>=-.001f || tracked.z>=-.001f) return false;
    float const x=-eduke_xr::PanelDistance*tracked.x/tracked.z;
    float const y=-eduke_xr::PanelDistance*tracked.y/tracked.z;
    if (std::fabs(x)>eduke_xr::PanelHalfWidth || std::fabs(y)>eduke_xr::PanelHalfWidth*ydim/xdim) return false;
    float const flatX=-eduke_xr::PanelDistance*flat.x/flat.z, flatY=-eduke_xr::PanelDistance*flat.y/flat.z;
    // Native 320x200 ART coordinates use a 4:3 subregion of a wide window.
    position.x+=fix16_from_float((x-flatX)*float(xdim)/ydim*120.f/eduke_xr::PanelHalfWidth);
    position.y-=fix16_from_float((y-flatY)*float(xdim)/ydim*100.f/eduke_xr::PanelHalfWidth);
    if (worldFrames==59 && std::getenv("EDUKE32_XR_TEST_AIM"))
        LOG_F(INFO,"OpenXR aim crosshair: nativeX=%.6f nativeY=%.6f panelX=%.6f panelY=%.6f.",
              fix16_to_float(position.x),fix16_to_float(position.y),x,y);
    return true;
}

void G_XRClearInput()
{
    VRShotInput shot; if (handShotsRequested()) shot.flags=VRShotEnabled;
    G_VRSetShotInput(myconnectindex,shot);
    for (unsigned hand=0;hand<2;++hand)
        blockedInputButtons[hand] |= rawInput.hands[hand].buttons;
    CONTROL_SetExternalInput(nullptr,0,nullptr);
}

void G_XRArmWorldDraw() { worldDrawArmed=true; }

bool G_XRConsumeWorldDraw()
{
    bool const armed=worldDrawArmed;
    worldDrawArmed=false;
    return armed;
}

void G_XRCancelMenuPresentation()
{
    // A world may have finished before its outer display-end callback. Nested
    // room draws must cancel that retained image too, before native callbacks.
    auto *waiting=presentationRuntime;
    presentationRuntime=nullptr;
    if (waiting && waiting->generation()==presentationGeneration)
    {
        std::string error;
        if (!waiting->finishFrame(false,error)) sdlayer_xr_disableWorld(error.c_str());
    }
    auto *runtime=menuRuntime;
    menuRuntime=nullptr;
    if (!runtime || runtime->generation()!=menuGeneration || !runtime->menuPresentationActive()) return;
    std::string error;
    if (!runtime->cancelMenuPresentation(error,true))
    {
        G_XRClearInput();
        sdlayer_xr_disableWorld(error.c_str());
    }
}

void G_XRBeginMenuPresentation()
{
    char const *enabled=std::getenv("EDUKE32_XR_UI");
    bool const overlay=overlayEnabled() && presentationRuntime;
    if (!enabled || (Bstrcmp(enabled,"1") && Bstrcmp(enabled,"2"))
        || (!overlay && (g_player[myconnectindex].ps->gm & MODE_GAME))
        || videoGetRenderMode()!=REND_POLYMOST) return;
    auto *runtime=overlay ? presentationRuntime : pendingRuntime;
    if (!runtime || runtime->generation()!=(overlay ? presentationGeneration : pendingGeneration)) return;
    std::string error;
    uint64_t owner=0;
    if (auto test=std::getenv("EDUKE32_XR_TEST_MENU_VIEWPORT"))
        if (!Bstrcmp(test,"1")) buildgl_setViewport(13,17,xdim/2,ydim/2);
    if (!runtime->beginMenuPresentation(xdim,ydim,owner,error,overlay))
    {
        G_XREndFrame();
        G_XRClearInput();
        sdlayer_xr_disableWorld(error.c_str());
        return;
    }
    if (overlay) presentationRuntime=nullptr;
    else pendingRuntime=nullptr; // Runtime now owns capture through the armed final swap.
    menuRuntime=runtime; menuGeneration=runtime->generation(); menuOwner=owner;
    static bool injectedNestedSwap;
    if (auto test=std::getenv("EDUKE32_XR_TEST_MENU_NESTED"))
        if (!injectedNestedSwap && !Bstrcmp(test,"1"))
        {
            injectedNestedSwap=true;
            LOG_F(INFO,"OpenXR menu test: injected unarmed native presentation.");
            videoNextPage();
        }
}

bool G_XRBeginWeapon()
{
    auto const enabled=std::getenv("EDUKE32_XR_WEAPON");
    if (!enabled || Bstrcmp(enabled,"1") || aimHand()<0 || !localAimCamera()
        || !menuRuntime || menuRuntime->generation()!=menuGeneration || !menuRuntime->menuOverlayTargetBound()) return false;
    XrPosef panel=rawInput.headPose;
    auto const offset=rotate(panel.orientation,{0,0,-eduke_xr::PanelDistance});
    panel.position.x+=offset.x; panel.position.y+=offset.y; panel.position.z+=offset.z;
    std::string error;
    if (!menuRuntime->flushMenuOverlay(panel,eduke_xr::PanelHalfWidth,eduke_xr::PanelHalfWidth*float(ydim)/xdim,
                                       rawInput.headValid && validPose(rawInput.headPose),error))
    {
        G_XRCancelMenuPresentation(); sdlayer_xr_disableWorld(error.c_str()); return false;
    }
    if (worldFrames==59)
        if (auto prefix=std::getenv("EDUKE32_XR_WEAPON_OUTPUT"))
        {
            std::string before=std::string(prefix)+"-before";
            if (!menuRuntime->captureFrame(before.c_str(),false,error,true))
            { G_XRCancelMenuPresentation(); sdlayer_xr_disableWorld(error.c_str()); return false; }
        }
    return true;
}

void G_XREndWeapon(bool captured)
{
    if (captured)
        if (auto test=std::getenv("EDUKE32_XR_TEST_WEAPON_NESTED"))
        {
            static bool injected;
            if (!injected && !Bstrcmp(test,"1"))
            {
                injected=true;
                LOG_F(INFO,"OpenXR weapon test: injected unarmed native presentation.");
                videoNextPage();
            }
        }
    // Native callbacks may cancel the owner (auxiliary rendering/custom blend).
    if (!captured || !menuRuntime || menuRuntime->generation()!=menuGeneration || !menuRuntime->menuOverlayTargetBound()) return;
    auto const hand=aimHand();
    if (hand<0) return;
    XrPosef pose=rawInput.hands[hand].aimPose;
    bool visible=aimPoseUsable();
    if (handShotsRequested() && G_VRHandShotFeature(myconnectindex))
    {
        vec3_t position; int16_t sector; bool clamped;
        visible=visible && Net_VRShotAvailable() && G_VRResolveShot(myconnectindex,position,sector,clamped);
        if (visible)
        {
            auto const body=aimBodyCamera(camera());
            float const yaw=fix16_to_float(body.angle)*Pi/1024.f, co=std::cos(yaw), si=std::sin(yaw);
            float const dx=float(position.x-body.pos.x)/UnitsPerMetre, dy=float(position.y-body.pos.y)/UnitsPerMetre;
            XrVector3f const relative={-dx*si+dy*co,-float(position.z-body.pos.z)/ZUnitsPerMetre,-dx*co-dy*si};
            auto const tracking=multiply(pitchRoll(nativePitch(body.horizon),body.roll),inverseYaw);
            auto const local=rotate({-tracking.x,-tracking.y,-tracking.z,tracking.w},relative);
            pose.position={origin.x+local.x,origin.y+local.y,origin.z+local.z};
            if (worldFrames==59 && std::getenv("EDUKE32_XR_TEST_SHOTS"))
                LOG_F(INFO,"OpenXR resolved hand: pos=%d,%d,%d sector=%d clamped=%d.",position.x,position.y,position.z,sector,clamped);
        }
    }
    // Native ART is a perspective weapon card. Provisional grip pivot is native
    // (192,180) in its 320x200, 4:3 subregion. Animation/palette/CON remain native.
    auto const offset=rotate(pose.orientation,{-.08f,.24f,-.15f});
    pose.position.x+=offset.x; pose.position.y+=offset.y; pose.position.z+=offset.z;
    char const *prefix=worldFrames==59 ? std::getenv("EDUKE32_XR_WEAPON_OUTPUT") : nullptr;
    if (prefix)
    {
        auto const &p=pose.position; auto const &q=pose.orientation;
        LOG_F(INFO,"OpenXR weapon card: visible=%d pos=%.9f,%.9f,%.9f quat=%.9f,%.9f,%.9f,%.9f.",visible,p.x,p.y,p.z,q.x,q.y,q.z,q.w);
        for (int eye=0;eye<2;++eye)
        {
            auto const &v=pendingFrame.views[eye]; auto const &p=v.pose.position; auto const &q=v.pose.orientation;
            LOG_F(INFO,"OpenXR weapon view: eye=%d pos=%.9f,%.9f,%.9f quat=%.9f,%.9f,%.9f,%.9f fov=%.9f,%.9f,%.9f,%.9f.",
                  eye,p.x,p.y,p.z,q.x,q.y,q.z,q.w,v.fov.angleLeft,v.fov.angleRight,v.fov.angleUp,v.fov.angleDown);
        }
    }
    std::string error;
    if (!menuRuntime->flushMenuOverlay(pose,.3f*float(xdim)/ydim,.3f,visible,error,prefix))
    { G_XRCancelMenuPresentation(); sdlayer_xr_disableWorld(error.c_str()); }
}

bool G_XRBeginCrosshair()
{
    if (!crosshairViews.valid || !menuRuntime || menuRuntime->generation()!=menuGeneration || !menuRuntime->menuOverlayTargetBound()) return false;
    // Flush the preceding HUD at its original depth/order. Only the native
    // crosshair returned by EVENT_DISPLAYCROSSHAIR enters this spatial segment.
    XrPosef panel=rawInput.headPose;
    auto const offset=rotate(panel.orientation,{0,0,-eduke_xr::PanelDistance});
    panel.position.x+=offset.x; panel.position.y+=offset.y; panel.position.z+=offset.z;
    std::string error;
    if (!menuRuntime->flushMenuOverlay(panel,eduke_xr::PanelHalfWidth,eduke_xr::PanelHalfWidth*float(ydim)/xdim,
                                       rawInput.headValid && validPose(rawInput.headPose),error))
    { G_XRCancelMenuPresentation(); sdlayer_xr_disableWorld(error.c_str()); return false; }
    if (worldFrames==59)
        if (auto prefix=std::getenv("EDUKE32_XR_CROSSHAIR_OUTPUT"))
        {
            std::string before=std::string(prefix)+"-before";
            if (!menuRuntime->captureFrame(before.c_str(),false,error,true))
            { G_XRCancelMenuPresentation(); sdlayer_xr_disableWorld(error.c_str()); return false; }
        }
    return true;
}

void G_XREndCrosshair(bool captured, vec2_t position, int32_t scale, int32_t flags)
{
    if (!captured || !crosshairViews.valid || !menuRuntime || menuRuntime->generation()!=menuGeneration || !menuRuntime->menuOverlayTargetBound()) return;
    auto const p=g_player[myconnectindex].ps;
    auto const body=aimBodyCamera(camera());
    bool visible=screenpeek==myconnectindex && !ud.recstat && p->newowner<0 && !p->over_shoulder_on
        && !(p->gm & MODE_MENU) && rawInput.headValid && validPose(rawInput.headPose)
        && (aimHand()==-2 || aimPoseUsable())
        && unsigned(p->i)<MAXSPRITES && sprite[p->i].extra>0;
    int64_t const anchorZ=int64_t(p->pos.z)+p->pyoff;
    visible=visible && anchorZ>=INT32_MIN && anchorZ<=INT32_MAX;
    vec3_t start={p->pos.x,p->pos.y,int32_t(std::max<int64_t>(INT32_MIN,std::min<int64_t>(INT32_MAX,anchorZ)))};
    int16_t sector=p->cursectnum; bool clamped=false;
    float const pitch=nativePitch(p->q16horiz+p->q16horizoff), angle=fix16_to_float(p->q16ang)*Pi/1024.f;
    vec3_t ray={int32_t(std::lround(std::cos(angle)*std::cos(pitch)*32767.f)),
                int32_t(std::lround(std::sin(angle)*std::cos(pitch)*32767.f)),int32_t(std::lround(-std::sin(pitch)*32767.f))*16};
    if (handShotsRequested() && G_VRHandShotFeature(myconnectindex))
    {
        visible=visible && aimPoseUsable() && Net_VRShotAvailable() && G_VRResolveShot(myconnectindex,start,sector,clamped);
        auto const shot=G_VRGetShotInput(myconnectindex);
        ray={shot.direction[0],shot.direction[1],shot.direction[2]*16};
    }
    hitdata_t hit{}; hit.sect=-1;
    if (visible && unsigned(sector)<unsigned(numsectors))
    {
        auto &owner=sprite[p->i]; auto const cstat=owner.cstat;
        owner.cstat &= ~(CSTAT_SPRITE_BLOCK|CSTAT_SPRITE_BLOCK_HITSCAN);
        hitscan(&start,sector,ray.x,ray.y,ray.z,&hit,CLIPMASK1);
        owner.cstat=cstat;
    }
    visible=visible && hit.sect>=0;
    float matrices[2][16]={};
    XrPosef unused{}; unused.orientation.w=1;
    if (visible)
    {
        // Pull four native XY-equivalent units toward the ray origin to avoid
        // z fighting at the actual surface. The centre is shared by both eyes.
        float const dx=float(hit.x)-start.x, dy=float(hit.y)-start.y, dz=float(hit.z)-start.z;
        float const distance=std::sqrt(dx*dx+dy*dy+dz*dz/256.f);
        float const back=distance>4.f ? 4.f/distance : 0.f;
        XrVector3f const point={hit.x-dx*back,hit.y-dy*back,hit.z-dz*back};
        auto const tracking=multiply(pitchRoll(nativePitch(body.horizon),body.roll),inverseYaw);
        float const yaw=fix16_to_float(body.angle)*Pi/1024.f, co=std::cos(yaw), si=std::sin(yaw);
        auto const toBuild=[&](XrVector3f v) {
            v=rotate(tracking,v);
            return XrVector3f{(-v.z*co-v.x*si)*UnitsPerMetre,(-v.z*si+v.x*co)*UnitsPerMetre,-v.y*ZUnitsPerMetre};
        };
        auto const head=toBuild({rawInput.headPose.position.x-origin.x,rawInput.headPose.position.y-origin.y,rawInput.headPose.position.z-origin.z});
        float const hx=point.x-body.pos.x-head.x, hy=point.y-body.pos.y-head.y, hz=(point.z-body.pos.z-head.z)/16.f;
        float const halfHeight=.6f*std::sqrt(hx*hx+hy*hy+hz*hz)/UnitsPerMetre;
        auto right=toBuild(rotate(rawInput.headPose.orientation,{1,0,0}));
        auto up=toBuild(rotate(rawInput.headPose.orientation,{0,1,0}));
        // Project onto the hit wall/sector plane. A head-facing billboard can
        // otherwise bury half its ART behind the very surface it marks.
        XrVector3f normal{};
        if (hit.wall>=0)
        {
            auto const &a=wall[hit.wall], &b=wall[a.point2];
            normal={float(b.y)-a.y,float(a.x)-b.x,0};
        }
        else if (hit.sprite<0)
        {
            bool const ceiling=std::abs(int64_t(hit.z)-getceilzofslope(hit.sect,hit.x,hit.y))
                              <std::abs(int64_t(hit.z)-getflorzofslope(hit.sect,hit.x,hit.y));
            auto const slope=ceiling ? getceilzofslope : getflorzofslope;
            int const z=slope(hit.sect,hit.x,hit.y);
            normal={-(slope(hit.sect,hit.x+256,hit.y)-z)/4096.f,
                    -(slope(hit.sect,hit.x,hit.y+256)-z)/4096.f,1};
        }
        float const normalLength=std::sqrt(dot(normal,normal));
        if (normalLength>0)
        {
            normal={normal.x/normalLength,normal.y/normalLength,normal.z/normalLength};
            if (normal.x*ray.x+normal.y*ray.y+normal.z*ray.z/16.f>0)
                normal={-normal.x,-normal.y,-normal.z};
            XrVector3f r={right.x/UnitsPerMetre,right.y/UnitsPerMetre,right.z/ZUnitsPerMetre};
            float const along=dot(r,normal);
            r={r.x-normal.x*along,r.y-normal.y*along,r.z-normal.z*along};
            float const length=std::sqrt(dot(r,r));
            if (length>1e-5f)
            {
                r={r.x/length,r.y/length,r.z/length}; auto const u=cross(normal,r);
                right={r.x*UnitsPerMetre,r.y*UnitsPerMetre,r.z*ZUnitsPerMetre};
                up={u.x*UnitsPerMetre,u.y*UnitsPerMetre,u.z*ZUnitsPerMetre};
            }
        }
        right={right.x*halfHeight*float(xdim)/ydim,right.y*halfHeight*float(xdim)/ydim,right.z*halfHeight*float(xdim)/ydim};
        up={up.x*halfHeight,up.y*halfHeight,up.z*halfHeight};
        auto const anchor=polymost_xrRotateSpriteAnchor(position,scale,flags);
        float const ax=2.f*anchor.x/xdim-1.f, ay=1.f-2.f*anchor.y/ydim;
        for (int eye=0;eye<2;++eye)
        {
            auto const &m=crosshairViews.matrix[eye]; auto const e=crosshairViews.eye[eye];
            float const columns[4][4]={{right.x,right.y,right.z,0},{up.x,up.y,up.z,0},{0,0,0,0},
                                      {point.x-e.x-right.x*ax-up.x*ay,point.y-e.y-right.y*ax-up.y*ay,point.z-e.z-right.z*ax-up.z*ay,1}};
            for (int column=0;column<4;++column)
                for (int row=0;row<4;++row)
                    for (int k=0;k<4;++k) matrices[eye][column*4+row]+=m[k*4+row]*columns[column][k];
        }
        if (worldFrames==59 && std::getenv("EDUKE32_XR_CROSSHAIR_OUTPUT"))
        {
            LOG_F(INFO,"OpenXR world crosshair: start=%d,%d,%d hit=%d,%d,%d sector=%d wall=%d sprite=%d point=%.6f,%.6f,%.6f.",
                  start.x,start.y,start.z,hit.x,hit.y,hit.z,hit.sect,hit.wall,hit.sprite,point.x,point.y,point.z);
            LOG_F(INFO,"OpenXR crosshair anchor: pixel=%.6f,%.6f.",anchor.x,anchor.y);
            for (int eye=0;eye<2;++eye)
                LOG_F(INFO,"OpenXR crosshair matrix: eye=%d values=%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g.",eye,
                      matrices[eye][0],matrices[eye][1],matrices[eye][2],matrices[eye][3],matrices[eye][4],matrices[eye][5],matrices[eye][6],matrices[eye][7],
                      matrices[eye][8],matrices[eye][9],matrices[eye][10],matrices[eye][11],matrices[eye][12],matrices[eye][13],matrices[eye][14],matrices[eye][15]);
        }
    }
    char const *prefix=worldFrames==59 ? std::getenv("EDUKE32_XR_CROSSHAIR_OUTPUT") : nullptr;
    std::string error;
    if (!menuRuntime->flushMenuOverlay(unused,1,1,visible,error,prefix,&matrices[0][0]))
    { G_XRCancelMenuPresentation(); sdlayer_xr_disableWorld(error.c_str()); }
}

void G_XRArmMenuPresentation()
{
    if (auto test=std::getenv("EDUKE32_XR_TEST_HUD_MENU"))
    {
        static unsigned testFrames;
        if (++testFrames==10 && (!Bstrcmp(test,"1") || !Bstrcmp(test,"2")))
        {
            Menu_Open(myconnectindex);
            Menu_Change(!Bstrcmp(test,"2") ? MENU_SAVE : MENU_MAIN_INGAME);
            LOG_F(INFO,"OpenXR HUD test: opened native %s menu.",!Bstrcmp(test,"2") ? "save" : "in-game");
        }
    }
    if (auto test=std::getenv("EDUKE32_XR_TEST_HUD_TINT"))
        if (!Bstrcmp(test,"1") || !Bstrcmp(test,"2") || !Bstrcmp(test,"3"))
        {
            if (worldFrames==59 && sdlayer_xr_overlayTargetBound())
                if (auto prefix=std::getenv("EDUKE32_XR_HUD_OUTPUT"))
                {
                    std::string error, path=std::string(prefix)+"-untinted-ui.ppm";
                    if (!eduke_xr::captureFramebuffer(path.c_str(),xdim,ydim,error))
                        LOG_F(ERROR,"XR HUD test capture: %s",error.c_str());
                }
            vec4f_t const correction = !Bstrcmp(test,"3") ? vec4f_t{1.15f,1.4f,1.3f,0.f}
                : !Bstrcmp(test,"2") ? vec4f_t{.9f,1.1f,.8f,0.f} : vec4f_t{1.f,1.f,1.f,0.f};
            polymost_setColorCorrection(correction);
            fullscreen_tint_gl(80,120,200,96);
        }
    if (!menuRuntime || menuRuntime->generation()!=menuGeneration) return;
    if (videoGetRenderMode()!=REND_POLYMOST || !menuRuntime->armMenuPresentation(menuOwner,xdim,ydim))
        G_XRCancelMenuPresentation();
}

void G_XREndFrame()
{
    if (presentationRuntime) G_XRCancelMenuPresentation();
    auto *runtime=pendingRuntime;
    pendingRuntime=nullptr;
    if (!runtime || runtime->generation() != pendingGeneration) return;
    std::string error;
    if (!runtime->finishFrame(false,error))
    {
        G_XRClearInput();
        sdlayer_xr_disableWorld(error.c_str());
    }
}

void G_XRBeginFrame()
{
    crosshairViews.valid=false;
    // Credit only the exact completed projection, never a rendered image that
    // was later canceled by a nested native draw, resize, or early swap.
    if (worldReceipt.runtime && worldReceipt.runtime->generation()==worldReceipt.generation
        && worldReceipt.runtime->lastSubmittedSerial()==worldReceipt.serial)
        accountWorldFrame(worldReceipt.opaque,worldReceipt.masks,false);
    worldReceipt={};
    // Only the ordinary game/demo frame owners may acquire/synchronize input.
    G_XRCancelMenuPresentation();
    G_XREndFrame();
    worldDrawArmed=false;
    auto const neutral=[] {
        rawInput={}; inputRuntime=nullptr;
        activeInputButtons={}; blockedInputButtons={};
        CONTROL_SetExternalInput(nullptr,0,nullptr);
    };
    if (g_networkMode == NET_DEDICATED_SERVER || videoGetRenderMode() != REND_POLYMOST)
    { neutral(); return; }
    auto *runtime=sdlayer_xr_worldRuntime();
    if (!runtime) { neutral(); return; }
    std::string error;
    auto const status=runtime->beginFrame(pendingFrame,error);
    if (status == eduke_xr::Runtime::FrameResult::Error || status == eduke_xr::Runtime::FrameResult::Exit)
    {
        std::string ignored;
        runtime->finishFrame(false,ignored);
        neutral();
        sdlayer_xr_disableWorld(error.empty() ? "session exit requested" : error.c_str());
        return;
    }
    pendingGeneration=runtime->generation();
    if (status == eduke_xr::Runtime::FrameResult::Ready) pendingRuntime=runtime;
    eduke_xr::ActionInput sample;
    if (!runtime->readInput(sample,pendingFrame.predictedDisplayTime,error))
    {
        G_XREndFrame(); neutral(); sdlayer_xr_disableWorld(error.c_str()); return;
    }
    if (inputRuntime != runtime || inputGeneration != pendingGeneration)
    {
        activeInputButtons={}; blockedInputButtons={};
        if (aimHand()!=-2)
        {
            trackingRebase=trackingRebase || (recentered && lastHeadValid);
            if (!trackingRebase) aimYawOffset=aimPitchOffset=0;
            aimPoseWasValid=false; recentered=false;
        }
    }
    else for (auto const &change:pendingFrame.referenceChanges)
    {
        if (change.poseValid && validPose(change.poseInPreviousSpace))
        {
            // new->previous is supplied by OpenXR. Move the existing tracking
            // reference into the new coordinates; native world pose is stable.
            auto const &pose=change.poseInPreviousSpace;
            XrQuaternionf const inverse={-pose.orientation.x,-pose.orientation.y,-pose.orientation.z,pose.orientation.w};
            auto const point=[&](XrVector3f p) {
                return rotate(inverse,{p.x-pose.position.x,p.y-pose.position.y,p.z-pose.position.z});
            };
            if (recentered)
            {
                origin=point(origin);
                inverseYaw=multiply(inverseYaw,pose.orientation);
            }
            if (lastHeadValid)
            {
                lastHeadPose.position=point(lastHeadPose.position);
                lastHeadPose.orientation=multiply(inverse,lastHeadPose.orientation);
            }
        }
        else
        {
            // An unknown transform cannot carry old calibration into a new
            // coordinate frame. Reuse recovery and the existing release gate.
            trackingRebase=trackingRebase || (recentered && lastHeadValid);
            recentered=false; aimPoseWasValid=false;
            shotReferenceInvalidated=true;
            blockedInputButtons[1]|=sample.hands[1].buttons&(eduke_xr::ButtonSelect|eduke_xr::ButtonStickClick);
            G_VRBlockShot(myconnectindex);
        }
        if (std::getenv("EDUKE32_XR_TEST_INPUT"))
            LOG_F(INFO,"OpenXR LOCAL reference changed: at=%lld predicted=%lld known=%d.",
                  (long long)change.changeTime,(long long)pendingFrame.predictedDisplayTime,int(change.poseValid));
    }
    inputRuntime=runtime; inputGeneration=pendingGeneration; rawInput=sample;
    if (rawInput.headValid && validPose(rawInput.headPose))
    {
        if (trackingRebase) setTrackingReference(rawInput.headPose);
        if (recentered) { lastHeadPose=rawInput.headPose; lastHeadValid=true; }
    }
    publishInput();
}

static bool testArtClock()
{
    char const *value=std::getenv("EDUKE32_XR_TEST_ART_CLOCK");
    return value && !Bstrcmp(value,"1") && std::getenv("EDUKE32_XR_TEST_CAPTURE");
}

// Opt-in input provenance for failure tests, before intentional native children.
void G_XRTestAnimationInputs()
{
    // Fixture input only: animated ART must see the same deterministic tick
    // in the native reference and each synthetic XR traversal. totalclock
    // and the simulation are untouched.
    if (testArtClock()) totalclocklock=1;
    static bool const enabled = std::getenv("EDUKE32_XR_TEST_FAIL") != nullptr;
    static unsigned samples;
    if (!enabled || samples++ >= 10)
        return;
    std::vector<uint8_t> seen(MAXSPRITES,0);
    unsigned duplicates=0;
    for (int i=0;i<spritesortcnt;++i)
        if ((unsigned)tsprite[i].owner < seen.size() && seen[tsprite[i].owner]++)
            ++duplicates;
    LOG_F(INFO,"XR failure test animation: frame=%u input=%d duplicateOwners=%u",
          unsigned(g_frameCounter),spritesortcnt,duplicates);
}

// A matched attachment isolates renderer differences from window-system versus
// texture-target rasterization. This fixture still executes the native room,
// animation and mask path below without the stereo transaction or XR runtime.
static GLuint nativeTestFbo, nativeTestColor, nativeTestDepth;
static GLint nativeTestDrawFbo, nativeTestReadFbo;
void G_XRTestBeginNative()
{
    if (nativeTestFbo || !std::getenv("EDUKE32_XR_TEST_NATIVE_TARGET") || !std::getenv("EDUKE32_XR_TEST_CAPTURE")
        || g_frameCounter != 12 || videoGetRenderMode() != REND_POLYMOST)
        return;
    glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING,&nativeTestDrawFbo);
    glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING,&nativeTestReadFbo);
    GLint texture;
    glGetIntegerv(GL_TEXTURE_BINDING_2D_ARRAY,&texture);
    glGenFramebuffers(1,&nativeTestFbo);
    glGenTextures(1,&nativeTestColor);
    glGenTextures(1,&nativeTestDepth);
    glBindTexture(GL_TEXTURE_2D_ARRAY,nativeTestColor);
    glTexImage3D(GL_TEXTURE_2D_ARRAY,0,GL_SRGB8_ALPHA8,xdim,ydim,2,0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);
    glBindTexture(GL_TEXTURE_2D_ARRAY,nativeTestDepth);
    glTexImage3D(GL_TEXTURE_2D_ARRAY,0,GL_DEPTH_COMPONENT24,xdim,ydim,2,0,GL_DEPTH_COMPONENT,GL_UNSIGNED_INT,nullptr);
    glBindTexture(GL_TEXTURE_2D_ARRAY,texture);
    glBindFramebuffer(GL_FRAMEBUFFER,nativeTestFbo);
    glFramebufferTextureLayer(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,nativeTestColor,0,0);
    glFramebufferTextureLayer(GL_FRAMEBUFFER,GL_DEPTH_ATTACHMENT,nativeTestDepth,0,0);
    glDrawBuffer(GL_COLOR_ATTACHMENT0);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
        LOG_F(ERROR,"XR native reference attachment incomplete.");
    glClearColor(0,0,0,1);
    glClear(GL_COLOR_BUFFER_BIT);
}

void G_XRTestCaptureNative()
{
    static bool captured;
    char const *prefix=std::getenv("EDUKE32_XR_TEST_CAPTURE");
    if (captured || !prefix || g_frameCounter != 12 || videoGetRenderMode() != REND_POLYMOST)
        return;
    captured=true;
    std::string error;
    std::string path=std::string(prefix)+"-native.ppm";
    std::string depthPath=std::string(prefix)+"-native-depth.bin";
    if (!eduke_xr::captureFramebuffer(path.c_str(),xdim,ydim,error)
        || !eduke_xr::captureFramebufferDepth(depthPath.c_str(),xdim,ydim,error))
        LOG_F(ERROR,"XR native reference capture failed: %s",error.c_str());
    else
        LOG_F(INFO,"XR native reference captured at logical frame 12 (%s attachment).",nativeTestFbo ? "matched texture" : "window");
    if (nativeTestFbo)
    {
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER,nativeTestDrawFbo);
        glBindFramebuffer(GL_READ_FRAMEBUFFER,nativeTestReadFbo);
        glDeleteFramebuffers(1,&nativeTestFbo);
        glDeleteTextures(1,&nativeTestColor);
        glDeleteTextures(1,&nativeTestDepth);
        nativeTestFbo=nativeTestColor=nativeTestDepth=0;
    }
}

bool G_XRCanAppendSprite(int32_t limit)
{
    bool const fits = spritesortcnt < limit;
    if (animating && !fits)
        generationSaturated = true;
    return fits;
}

void G_XRInheritSprite(int32_t destination, int32_t parent)
{
    if (animating && (unsigned)destination < membership.size() && (unsigned)parent < membership.size())
        membership[destination] = membership[parent];
}

bool G_XRDrawRooms(int32_t smoothRatio)
{
    // Initial renderer oracle deliberately excludes multi-view sector effects.
    // Further camera/draw families and tracked weapon origins remain required.
    if (videoGetRenderMode() != REND_POLYMOST || g_screenCapture
#ifdef YAX_ENABLE
        || numyaxbunches
#endif
        )
        return false;
    auto *runtime=pendingRuntime;
    if (!runtime || runtime->generation() != pendingGeneration) return false;
    pendingRuntime=nullptr; // Transfer this acquired frame; auxiliary draws cannot take another.
    auto frame=pendingFrame;
    std::string error;
    if (runtime != previousRuntime || worldGeneration != runtime->generation())
    {
        previousRuntime=runtime; worldGeneration=runtime->generation();
        if (aimHand()==-2) recentered=false;
        worldFrames=0;
        worldMultiviewFrames=worldOracleFrames=0;
        worldMaskMultiviewFrames=worldMaskOracleFrames=worldFullMultiviewFrames=0;
    }
    if (!recentered && aimHand()!=-2)
    {
        // A hand may connect after the first world frame. Never initialize
        // tracked authority from a possibly canted eye in that interval.
        if (!rawInput.headValid || !validPose(rawInput.headPose))
        {
            if (!runtime->finishFrame(false,error)) sdlayer_xr_disableWorld(error.c_str());
            return false;
        }
        setTrackingReference(rawInput.headPose);
    }
    if (!recentered)
    {
        auto const &a=frame.views[0].pose.position, &b=frame.views[1].pose.position;
        origin = {(a.x+b.x)*.5f,(a.y+b.y)*.5f,(a.z+b.z)*.5f};
        auto f = rotate(frame.views[0].pose.orientation,{0,0,-1});
        float const yaw = std::atan2(-f.x,-f.z);
        inverseYaw = {0,-std::sin(yaw*.5f),0,std::cos(yaw*.5f)};
        recentered = true;
    }
    Camera logical = camera();
    Camera const body=aimBodyCamera(logical);
    std::array<Eye,2> eyes;
    char const *zeroValue=std::getenv("EDUKE32_XR_TEST_ZERO_IPD");
    bool const zeroTest=zeroValue && !Bstrcmp(zeroValue,"1");
    char const *stereoValue=std::getenv("EDUKE32_XR_TEST_STEREO_POSE");
    bool const unequalTest=stereoValue && !Bstrcmp(stereoValue,"2");
    bool const stereoTest=stereoValue && (!Bstrcmp(stereoValue,"1") || unequalTest);
    bool const fixtureTest=zeroTest || stereoTest;
    if (stereoTest)
    {
        origin={0,1.6f,0};
        inverseYaw={0,0,0,1};
        XrQuaternionf const yaw{0,std::sin(.035f),0,std::cos(.035f)};
        XrQuaternionf const pitch{std::sin(.025f),0,0,std::cos(.025f)};
        XrQuaternionf const roll{0,0,std::sin(-.015f),std::cos(-.015f)};
        for (unsigned i=0;i<2;++i)
        {
            frame.views[i].pose.position={i ? .032f : -.032f,1.6f,0};
            frame.views[i].pose.orientation=multiply(multiply(yaw,pitch),roll);
            frame.views[i].fov={i ? -.8f : -.75f,i ? .75f : .8f,.7f,-.72f};
            if (unequalTest && i == 1)
                frame.views[i].fov={-.68f,.65f,.6f,-.62f};
        }
    }
    if (zeroTest)
    {
        // Offscreen differential fixture only. No projection layer is submitted
        // for these synthetic poses/FOVs, so runtime-located eyes stay truthful.
        if (windowxy1.x || windowxy1.y || windowxy2.x != xdim-1 || windowxy2.y != ydim-1 || yxaspect != 81920)
        {
            runtime->finishFrame(false,error);
            sdlayer_xr_disableWorld("zero-IPD fixture requires full viewport and square Build pixel aspect");
            return false;
        }
        for (auto &eye : eyes)
        {
            eye.camera=logical;
            eye.cover=float(viewingrange)/65536.f;
            eye.left=-eye.cover; eye.right=eye.cover;
            eye.down=-eye.cover/(float(xdim)/ydim); eye.up=-eye.down;
        }
    }
    else
        for (unsigned i=0;i<2;++i)
            if (!makeEye(frame.views[i],body,float(frame.width)/frame.height,eyes[i]))
            {
                static bool warned;
                if (!warned)
                    LOG_F(WARNING,"XR oracle frame outside native camera coverage/collision domain; full-pitch/room-scale support remains pending.");
                warned = true;
                runtime->finishFrame(false,error);
                return false;
            }
    if (!fixtureTest && std::getenv("EDUKE32_XR_TEST_AIM")
        && (worldFrames==59 || std::getenv("EDUKE32_TEST_REFERENCE_MARKER")))
    {
        LOG_F(INFO,"OpenXR aim camera: authorityYaw=%.6f bodyYaw=%.6f leftYaw=%.6f leftPitch=%.6f rightYaw=%.6f rightPitch=%.6f.",
              fix16_to_float(logical.angle)*Pi/1024.f,fix16_to_float(body.angle)*Pi/1024.f,
              fix16_to_float(eyes[0].camera.angle)*Pi/1024.f,nativePitch(eyes[0].camera.horizon),
              fix16_to_float(eyes[1].camera.angle)*Pi/1024.f,nativePitch(eyes[1].camera.horizon));
        auto const &left=eyes[0].camera.pos, &right=eyes[1].camera.pos;
        LOG_F(INFO,"OpenXR aim eye positions: left=%d,%d,%d right=%d,%d,%d.",left.x,left.y,left.z,right.x,right.y,right.z);
    }
    vec2_t const oldStart=windowxy1, oldEnd=windowxy2;
    int const oldRange=viewingrange, oldAspect=yxaspect;
    int const frozenVisibility=g_visibility, frozenParallax=parallaxvisibility;
    bool animated=false, good=true, usedMultiview=false, usedMaskMultiview=false;
    videoSetViewableArea(0,0,xdim-1,ydim-1);
    auto const drawOpaque = [&](bool collect) {
        for (unsigned i=0;i<2 && good;++i)
        {
            auto &eye=eyes[i];
            eye.sprites.clear();
            eye.walls.clear();
            good=runtime->bindEye(i,error);
            if (!good) return false;
            eyeState(eye);
            glClearColor(0,0,0,1);
            glClear(GL_COLOR_BUFFER_BIT);
            spritesortcnt=0;
            if (collect) polymost_xrBeginCollection(POLYMOST_XR_OPAQUE,i);
            yax_preparedrawrooms();
            renderDrawRoomsQ16(eye.camera.pos.x,eye.camera.pos.y,eye.camera.pos.z,
                              eye.camera.angle,eye.camera.horizon,eye.camera.sector);
            if (collect && polymost_xrEndCollection(i) != POLYMOST_XR_COLLECT_OK)
                return false;
            if (spritesortcnt >= maxspritesonscreen || maskwallcnt >= MAXWALLSB)
            {
                error="stereo collection saturated native list capacity";
                good=false; return false;
            }
            eye.sprites.assign(tsprite,tsprite+spritesortcnt);
            eye.walls.reserve(maskwallcnt);
            for (int j=0;j<maskwallcnt;++j) eye.walls.push_back(thewall[maskwall[j]]);
            std::copy(std::begin(gotsector),std::end(gotsector),eye.sectors.begin());
            if (i == 0 && testFailure("opaque"))
            {
                error="injected failure after left opaque pass";
                good=false; return false;
            }
        }
        return good;
    };
    char const *singleValue=std::getenv("EDUKE32_XR_SINGLE_PASS");
    bool const singlePass=singleValue && !Bstrcmp(singleValue,"1");
    if (singlePass)
    {
        bool committed=drawOpaque(true);
        if (committed)
        {
            good=runtime->bindMultiview(error);
            if (good)
            {
                // Collection can execute unsupported native draw families on
                // the individual eye targets. Commit only the accepted replay.
                glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
                committed=polymost_xrReplayCollection() == POLYMOST_XR_COLLECT_OK;
                if (committed)
                {
                    usedMultiview=true;
                    static bool reported;
                    if (!reported || g_frameCounter == 12)
                    {
                        auto const stats=polymost_xrCollectionStats();
                        LOG_F(INFO,"OpenXR opaque single-pass: frame=%u paired=%u eyeOnly=%u pairedVertices=%u eyeOnlyVertices=%u flatSky=%u skyDepth=%u npot=%u",
                              unsigned(g_frameCounter),stats.pairedCalls,stats.eyeOnlyCalls,stats.pairedVertices,stats.eyeOnlyVertices,
                              stats.flatSkyCalls,stats.skyDepthCalls,stats.npotCalls);
                        reported=true;
                    }
                }
            }
            else committed=false;
        }
        if (!committed && good)
        {
            static unsigned reported;
            if (reported < 3)
            {
                LOG_F(INFO,"OpenXR opaque candidate uses two-pass oracle: %s (frame=%u)",
                      polymost_xrCollectionReason(),unsigned(g_frameCounter));
                ++reported;
            }
            polymost_xrDiscardCollection();
            // Retry before animation in the same located/acquired XR frame.
            // No CON callback or simulation/input tick is repeated here.
            drawOpaque(false);
        }
        polymost_xrDiscardCollection();
    }
    else drawOpaque(false);
    if (good)
    {
        std::vector<int> byOwner(MAXSPRITES,-1);
        spritesortcnt=0;
        membership.fill(0);
        for (unsigned i=0;i<2 && good;++i)
            for (auto const &sprite : eyes[i].sprites)
            {
                int slot=(unsigned)sprite.owner < byOwner.size() ? byOwner[sprite.owner] : -1;
                if (slot >= 0 && Bmemcmp(&tsprite[slot],&sprite,sizeof(sprite)))
                {
                    error="ordinary-room stereo collected conflicting instances of one sprite";
                    good=false; break;
                }
                if (slot < 0)
                {
                    if (spritesortcnt >= maxspritesonscreen)
                    {
                        error="stereo sprite union exceeds native list capacity";
                        good=false; break;
                    }
                    slot=spritesortcnt++;
                    tsprite[slot]=sprite;
                    if ((unsigned)sprite.owner < byOwner.size()) byOwner[sprite.owner]=slot;
                }
                membership[slot] |= 1u<<i;
            }
    }
    if (good)
    {
        install(logical);
        // CON reads the common logical camera and the native aspect values.
        // Camera preparation changes no pixels and preserves both eye depths.
        polymost_xrProjectionReset();
        videoSetViewableArea(oldStart.x,oldStart.y,oldEnd.x,oldEnd.y);
        renderSetAspect(oldRange,oldAspect);
        renderPrepareMasksQ16(logical.pos.x,logical.pos.y,logical.pos.z,
                             logical.angle,logical.horizon,logical.sector);
        for (size_t i=0;i<sizeof(gotsector);++i) gotsector[i]=eyes[0].sectors[i]|eyes[1].sectors[i];
        generationSaturated=false;
        animating=true;
        G_DoSpriteAnimations(logical.pos.x,logical.pos.y,logical.pos.z,fix16_to_int(logical.angle),smoothRatio);
        animating=false;
        animated=true;
        logical=camera(); // Preserve any CON changes to the common logical camera.
        if (generationSaturated)
        {
            good=false;
            error="stereo generated-sprite list saturated native capacity";
        }
        if (testFailure("masks"))
        {
            good=false;
            error="injected failure after animation, before first masks";
        }
        std::vector<tspritetype> pristine(tsprite,tsprite+spritesortcnt);
        auto const drawMasks = [&](bool collect) {
            bool accepted=true;
            for (unsigned i=0;i<2 && good;++i)
            {
                auto const &eye=eyes[i];
                good=runtime->bindEye(i,error);
                if (!good) return false;
                videoSetViewableArea(0,0,xdim-1,ydim-1);
                eyeState(eye);
                // Begin before camera preparation, which captures this eye's
                // projection. Native sorting/animation of tiles stays intact.
                if (collect && !polymost_xrBeginCollection(POLYMOST_XR_MASKS,i))
                    return false; // Preflight rejection must skip editor/direct paths.
                int const scriptVisibility=g_visibility, scriptParallax=parallaxvisibility;
                g_visibility=frozenVisibility; parallaxvisibility=frozenParallax;
                renderPrepareMasksQ16(eye.camera.pos.x,eye.camera.pos.y,eye.camera.pos.z,
                                     eye.camera.angle,eye.camera.horizon,eye.camera.sector);
                g_visibility=scriptVisibility; parallaxvisibility=scriptParallax;
                polymost_xrRelativeWorldToClip(crosshairViews.matrix[i]);
                crosshairViews.eye[i]=eye.camera.pos;
                if (testArtClock()) totalclocklock=1;
                spritesortcnt=pristine.size();
                std::copy(pristine.begin(),pristine.end(),tsprite);
                for (int j=0;j<spritesortcnt;++j)
                    if (!(membership[j] & (1u<<i))) tsprite[j].xrepeat=tsprite[j].yrepeat=0;
                maskwallcnt=eye.walls.size();
                for (int j=0;j<maskwallcnt;++j) { maskwall[j]=j; thewall[j]=eye.walls[j]; }
                renderDrawMasks();
                // Remaining draws in a rejected traversal stay suppressed.
                // A rejected begin for the next eye skips that traversal.
                if (collect && polymost_xrEndCollection(i) != POLYMOST_XR_COLLECT_OK)
                    accepted=false;
            }
            return good && accepted;
        };
        if (singlePass && good)
        {
            char const *failure=std::getenv("EDUKE32_XR_TEST_FAIL");
            bool const maskFault=failure && !Bstrncmp(failure,"mask-",5);
            if (maskFault)
                SDL_setenv("EDUKE32_XR_TEST_MASK_ARMED",(!fixtureTest || g_frameCounter == 12) ? "1" : "0",1);
            auto const captureCollection = [&](char const *suffix) {
                auto const prefix=std::getenv("EDUKE32_XR_TEST_CAPTURE");
                return !prefix || runtime->captureFrame((std::string(prefix)+suffix).c_str(),false,error,true);
            };
            bool const snapshot=fixtureTest && g_frameCounter == 12 && std::getenv("EDUKE32_XR_TEST_MASK_SNAPSHOT");
            if (snapshot) good=captureCollection("-mask-before");
            bool committed=good && drawMasks(true);
            // Read both layers before fallback/replay can hide a capture leak.
            if (snapshot && good) good=captureCollection("-mask-after");
            if (committed && good)
            {
                good=runtime->bindMultiview(error);
                if (good)
                {
                    committed=polymost_xrReplayCollection() == POLYMOST_XR_COLLECT_OK;
                    if (committed)
                    {
                        usedMaskMultiview=true;
                        static bool reported;
                        if (!reported || g_frameCounter == 12)
                        {
                            auto const stats=polymost_xrCollectionStats();
                            LOG_F(INFO,"OpenXR masks single-pass: frame=%u paired=%u eyeOnly=%u pairedVertices=%u eyeOnlyVertices=%u masks=%u translucent=%u depthOnly=%u depthWriteOff=%u",
                                  unsigned(g_frameCounter),stats.pairedCalls,stats.eyeOnlyCalls,stats.pairedVertices,stats.eyeOnlyVertices,
                                  stats.maskCalls,stats.translucentCalls,stats.depthOnlyCalls,stats.depthWriteOffCalls);
                            reported=true;
                        }
                    }
                    else if (polymost_xrReplaySubmitted())
                    {
                        error=std::string("mask replay failed after draw submission: ")+polymost_xrCollectionReason();
                        good=false;
                    }
                }
            }
            if (!committed && good)
            {
                static unsigned reported;
                if (reported < 3 || (fixtureTest && g_frameCounter == 12))
                {
                    LOG_F(INFO,"OpenXR masks candidate uses two-pass oracle: %s (frame=%u)",
                          polymost_xrCollectionReason(),unsigned(g_frameCounter));
                    ++reported;
                }
                polymost_xrDiscardCollection();
                // Opaque pixels and once-animated pristine sprites are still
                // authoritative. Never regenerate rooms after arbitrary CON.
                drawMasks(false);
            }
            polymost_xrDiscardCollection();
        }
        else if (good) drawMasks(false);
        if (good && fixtureTest && g_frameCounter == 12)
        {
            if (auto prefix=std::getenv("EDUKE32_XR_TEST_CAPTURE"))
            {
                good=runtime->captureFrame(prefix,false,error,true);
                if (good)
                    LOG_F(INFO,"XR %s eyes captured at logical frame 12 (offscreen, no projection submission).",zeroTest ? "zero-IPD" : "stereo-fixture");
            }
        }
        if (good && !fixtureTest && worldFrames == 59)
        {
            if (auto prefix=std::getenv("EDUKE32_XR_WORLD_OUTPUT"))
                good=runtime->captureFrame(prefix,false,error,overlayEnabled());
        }
        if (good) good=runtime->mirrorEye(0,error);
    }
    install(logical);
    polymost_xrProjectionReset();
    videoSetViewableArea(oldStart.x,oldStart.y,oldEnd.x,oldEnd.y);
    renderSetAspect(oldRange,oldAspect);
    std::string endError;
    bool const deferPresentation=good && !fixtureTest && overlayEnabled();
    crosshairViews.valid=deferPresentation;
    if (!deferPresentation && !runtime->finishFrame(good && !fixtureTest,endError)) { good=false; error += " "+endError; }
    if (deferPresentation)
    {
        presentationRuntime=runtime; presentationGeneration=runtime->generation();
        worldReceipt={runtime,runtime->generation(),frame.serial,usedMultiview,usedMaskMultiview};
    }
    // Display-end callbacks must not observe the right eye's renderer globals.
    // Preserve script visibility mutations while rebuilding native derived fog.
    int const scriptVisibility=g_visibility, scriptParallax=parallaxvisibility;
    g_visibility=frozenVisibility; parallaxvisibility=frozenParallax;
    renderPrepareMasksQ16(logical.pos.x,logical.pos.y,logical.pos.z,
                         logical.angle,logical.horizon,logical.sector);
    g_visibility=scriptVisibility; parallaxvisibility=scriptParallax;
    if (!good)
        sdlayer_xr_disableWorld(error.c_str());
    else
    {
        if (!deferPresentation) accountWorldFrame(usedMultiview,usedMaskMultiview,fixtureTest);
    }
    // Native Polymost appends to these arrays rather than resetting the sprite
    // count. Also clear on an aborted pass before fallback/next-frame rendering.
    spritesortcnt=0;
    maskwallcnt=0;
    // Before animation a native fallback is safe. After it, the logical pass
    // must be consumed even on failure so CON/persistent state cannot run twice.
    return good || animated;
}
#endif
