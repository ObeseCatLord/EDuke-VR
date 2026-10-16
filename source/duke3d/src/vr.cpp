// SPDX-License-Identifier: GPL-2.0-only
// Copyright (C) 2026 EDuke32 VR contributors
#ifdef USE_OPENXR
#include "duke3d.h"
#include "sdlayer.h"
#include "vr.h"
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
static eduke_xr::Runtime *menuRuntime;
static uint64_t menuGeneration, menuOwner;
static eduke_xr::ActionInput rawInput;
static std::array<uint32_t,2> activeInputButtons{}, blockedInputButtons{};

static bool inputValid()
{
    // Native polling may recreate the SDL context after this sample was taken.
    // This callback reads identity only; it never polls or initializes XR.
    return inputRuntime && inputRuntime->generation() == inputGeneration && rawInput.focused;
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
    auto const move=inputStick(rawInput.hands[0]), turn=inputStick(rawInput.hands[1]);
    ControlInfo analog{};
    analog.dx=std::lround(move.x*32767.f); analog.dz=std::lround(-move.y*32767.f);
    // These are native joystick units, retaining native Strafe/AimWeight/locks.
    analog.dyaw=std::lround(turn.x*16383.f); analog.dpitch=std::lround(-turn.y*16383.f);
    uint64_t buttons=0;
    auto const button=[&](bool pressed, unsigned gamefunc) { if (pressed) buttons |= uint64_t(1)<<gamefunc; };
    button(down[1]&ButtonSelect,gamefunc_Fire); button(down[0]&ButtonSelect,gamefunc_Open);
    button(down[1]&ButtonPrimary,gamefunc_Jump); button(down[1]&ButtonSecondary,gamefunc_Crouch);
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
static bool recentered;

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

void G_XRClearInput()
{
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
    if (!enabled || Bstrcmp(enabled,"1") || (g_player[myconnectindex].ps->gm & MODE_GAME)
        || videoGetRenderMode()!=REND_POLYMOST) return;
    auto *runtime=pendingRuntime;
    if (!runtime || runtime->generation()!=pendingGeneration) return;
    std::string error;
    uint64_t owner=0;
    if (auto test=std::getenv("EDUKE32_XR_TEST_MENU_VIEWPORT"))
        if (!Bstrcmp(test,"1")) buildgl_setViewport(13,17,xdim/2,ydim/2);
    if (!runtime->beginMenuPresentation(xdim,ydim,owner,error))
    {
        G_XREndFrame();
        G_XRClearInput();
        sdlayer_xr_disableWorld(error.c_str());
        return;
    }
    pendingRuntime=nullptr; // Runtime now owns capture through the armed final swap.
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

void G_XRArmMenuPresentation()
{
    if (!menuRuntime || menuRuntime->generation()!=menuGeneration) return;
    if (videoGetRenderMode()!=REND_POLYMOST || !menuRuntime->armMenuPresentation(menuOwner,xdim,ydim))
        G_XRCancelMenuPresentation();
}

void G_XREndFrame()
{
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
    { activeInputButtons={}; blockedInputButtons={}; }
    inputRuntime=runtime; inputGeneration=pendingGeneration; rawInput=sample;
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
    // The complete VR port still requires those paths and the weapon/HUD/input.
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
        recentered=false; worldFrames=0;
        worldMultiviewFrames=worldOracleFrames=0;
        worldMaskMultiviewFrames=worldMaskOracleFrames=worldFullMultiviewFrames=0;
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
            if (!makeEye(frame.views[i],logical,float(frame.width)/frame.height,eyes[i]))
            {
                static bool warned;
                if (!warned)
                    LOG_F(WARNING,"XR oracle frame outside native camera coverage/collision domain; full-pitch/room-scale support remains pending.");
                warned = true;
                runtime->finishFrame(false,error);
                return false;
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
                good=runtime->captureFrame(prefix,false,error);
        }
        if (good) good=runtime->mirrorEye(0,error);
    }
    install(logical);
    polymost_xrProjectionReset();
    videoSetViewableArea(oldStart.x,oldStart.y,oldEnd.x,oldEnd.y);
    renderSetAspect(oldRange,oldAspect);
    std::string endError;
    if (!runtime->finishFrame(good && !fixtureTest,endError)) { good=false; error += " "+endError; }
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
        ++worldFrames;
        if (usedMultiview) ++worldMultiviewFrames;
        else ++worldOracleFrames;
        if (usedMaskMultiview) ++worldMaskMultiviewFrames;
        else ++worldMaskOracleFrames;
        if (usedMultiview && usedMaskMultiview) ++worldFullMultiviewFrames;
        if (!fixtureTest && worldFrames == 60)
            LOG_F(INFO,"OpenXR world oracle: 60 frames, opaque multiview=%u twoPass=%u; masks multiview=%u twoPass=%u full multiview=%u; one animation transaction per frame.",
                  unsigned(worldMultiviewFrames),unsigned(worldOracleFrames),unsigned(worldMaskMultiviewFrames),
                  unsigned(worldMaskOracleFrames),unsigned(worldFullMultiviewFrames));
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
