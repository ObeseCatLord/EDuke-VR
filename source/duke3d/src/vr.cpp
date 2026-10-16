// SPDX-License-Identifier: GPL-2.0-only
// Copyright (C) 2026 EDuke32 VR contributors
#ifdef USE_OPENXR
#include "duke3d.h"
#include "sdlayer.h"
#include "vr.h"
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
static uint64_t worldFrames;
static eduke_xr::Runtime *previousRuntime;
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

// Bounded opt-in evidence for the two injected failure paths. It records input
// provenance before native animation creates intentional parent/child duplicates.
void G_XRTestAnimationInputs()
{
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
    auto *runtime = sdlayer_xr_worldRuntime();
    if (!runtime)
        return false;
    if (runtime != previousRuntime || runtime->submittedFrames() == 0)
    {
        previousRuntime = runtime;
        recentered = false;
        worldFrames = 0;
    }
    eduke_xr::Runtime::Frame frame;
    std::string error;
    auto status = runtime->beginFrame(frame,error);
    if (status == eduke_xr::Runtime::FrameResult::Idle)
        return false;
    if (status != eduke_xr::Runtime::FrameResult::Ready)
    {
        sdlayer_xr_disableWorld(error.empty() ? "session exit requested" : error.c_str());
        return false;
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
    bool animated=false, good=true;
    videoSetViewableArea(0,0,xdim-1,ydim-1);
    for (unsigned i=0;i<2 && good;++i)
    {
        auto &eye=eyes[i];
        good=runtime->bindEye(i,error);
        if (!good) break;
        eyeState(eye);
        glClearColor(0,0,0,1);
        glClear(GL_COLOR_BUFFER_BIT);
        spritesortcnt=0;
        yax_preparedrawrooms();
        renderDrawRoomsQ16(eye.camera.pos.x,eye.camera.pos.y,eye.camera.pos.z,
                          eye.camera.angle,eye.camera.horizon,eye.camera.sector);
        if (spritesortcnt >= maxspritesonscreen || maskwallcnt >= MAXWALLSB)
        {
            error="stereo collection saturated native list capacity";
            good=false; break;
        }
        eye.sprites.assign(tsprite,tsprite+spritesortcnt);
        eye.walls.reserve(maskwallcnt);
        for (int j=0;j<maskwallcnt;++j) eye.walls.push_back(thewall[maskwall[j]]);
        std::copy(std::begin(gotsector),std::end(gotsector),eye.sectors.begin());
        if (i == 0 && testFailure("opaque"))
        {
            error="injected failure after left opaque pass";
            good=false;
        }
    }
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
        for (unsigned i=0;i<2 && good;++i)
        {
            auto const &eye=eyes[i];
            good=runtime->bindEye(i,error);
            if (!good) break;
            videoSetViewableArea(0,0,xdim-1,ydim-1);
            eyeState(eye);
            int const scriptVisibility=g_visibility, scriptParallax=parallaxvisibility;
            g_visibility=frozenVisibility; parallaxvisibility=frozenParallax;
            renderPrepareMasksQ16(eye.camera.pos.x,eye.camera.pos.y,eye.camera.pos.z,
                                 eye.camera.angle,eye.camera.horizon,eye.camera.sector);
            g_visibility=scriptVisibility; parallaxvisibility=scriptParallax;
            spritesortcnt=pristine.size();
            std::copy(pristine.begin(),pristine.end(),tsprite);
            for (int j=0;j<spritesortcnt;++j)
                if (!(membership[j] & (1u<<i))) tsprite[j].xrepeat=tsprite[j].yrepeat=0;
            maskwallcnt=eye.walls.size();
            for (int j=0;j<maskwallcnt;++j) { maskwall[j]=j; thewall[j]=eye.walls[j]; }
            renderDrawMasks();
        }
        if (good && worldFrames == 59)
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
    if (!runtime->finishFrame(good,endError)) { good=false; error += " "+endError; }
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
        if (worldFrames == 60)
            LOG_F(INFO,"OpenXR world oracle: 60 frames, two opaque/mask eye passes and one animation transaction per frame.");
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
