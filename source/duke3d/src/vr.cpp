// SPDX-License-Identifier: GPL-2.0-only
// Copyright (C) 2026 EDuke32 VR contributors
#ifdef USE_OPENXR
#include "duke3d.h"
#include "sdlayer.h"
#include "voice.h"
#include "vr.h"
#include "vrshoot.h"
#include "network.h"
#include "menus.h"
#include "mdsprite.h"
#include "../../vr/eduke_xr.h"
#include <algorithm>
#include <cfloat>
#include <atomic>
#include <csignal>
#include <ctime>
#include <dlfcn.h>
#include <execinfo.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <array>
#include <cmath>
#include <cstdlib>
#include <vector>

// VR settings (cvars; vr.h).
int32_t vr_models=1, vr_laser=0, vr_fullbody=1, vr_lefttrigger=0, vr_ptt_button=0;

// Engine-private depth-clear latch for Polymost room passes.
extern int32_t yax_polymostclearzbuffer;

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
// Polymost visibility works in a yaw-relative projection and can only see the
// half-space in front of its yaw. A steeply pitched eye whose frustum crosses
// that plane is drawn as two passes of the same physical camera: the front
// pass, and a back pass expressed with yaw+pi, pitch pi-p and roll+pi.
struct EyePass
{
    Camera camera;
    std::vector<tspritetype> sprites;
    std::vector<int16_t> walls;
};
struct Eye
{
    Camera camera; // Front pass, also the eye's model/crosshair camera.
    float left, right, down, up, cover;
    bool split=false;
    float upSin=0.f, upCos=1.f;
    std::array<EyePass,2> passes;
    std::array<uint8_t, sizeof(gotsector)> sectors;
    unsigned passCount() const { return split ? 2 : 1; }
};
// View directions this close to the split plane (in Polymost's focal-length
// units) are left to the other pass; much tighter than the native SCISDIST.
constexpr float SplitViewportClip=1.f/256.f;
// Wall near plane for split passes, in Build units (native SCISDIST is 1).
// Measured: 1 leaves a 1-2px seam, 1/4 and below 1/32 show precision holes.
constexpr float SplitNearClip=1.f/16.f;
static std::array<uint8_t, MAXSPRITESONSCREEN> membership;
static bool animating, generationSaturated;
static uint64_t worldFrames, worldMultiviewFrames, worldOracleFrames;
static uint64_t worldMaskMultiviewFrames, worldMaskOracleFrames, worldFullMultiviewFrames;
static uint64_t worldModelOracleFrames, worldModelMultiviewFrames;
static eduke_xr::Runtime *previousRuntime;
static uint64_t worldGeneration;
static eduke_xr::Runtime *pendingRuntime, *inputRuntime;
static eduke_xr::Runtime::Frame pendingFrame;
static uint64_t pendingGeneration, inputGeneration;
static bool aaWeaponFamily(XRWeaponFamily family)
{
    return family==XRWeaponFamily::AAPistol || family==XRWeaponFamily::AARpg;
}
// HUD-tile model map (EDUKE32_XR_HUD_MODEL_MAP: "hudTile modelTile" lines).
// The weapon tiles a frame draws pick the held model for the next frame; the
// choice sticks through animation tiles until the selected weapon changes.
static std::vector<int32_t> hudModelMap; // indexed by HUD tile, -1 = none
static int32_t hudPredictedModel=-1, hudPredictedWeapon=-1, hudObservedModel=-1;
static bool hudSegmentObserved;
static bool loadHudModelMap()
{
    static bool loaded;
    if (!loaded)
    {
        loaded=true;
        if (auto path=sdlayer_xr_option("EDUKE32_XR_HUD_MODEL_MAP"))
            if (FILE *file=std::fopen(path,"r"))
            {
                hudModelMap.assign(MAXTILES,-1);
                int hud, model;
                while (std::fscanf(file,"%d %d",&hud,&model)==2)
                    if ((unsigned)hud<MAXTILES && (unsigned)model<MAXTILES && hudModelMap[hud]<0) hudModelMap[hud]=model;
                std::fclose(file);
            }
    }
    return !hudModelMap.empty();
}
// Runtime switches (console/settings.cfg): vr_models turns every VR model off (held weapons,
// hands, body, third-person players, 3D weapon wheel) and falls back to native 2D art, like
// RazeXR; vr_laser draws an aiming beam from the muzzle to the aim point.
constexpr int32_t VRLaserTile=30060;
constexpr int32_t VRMoneyTile=30068;   // tipping: wad of bills cut from the GRP's MONEY art
} // namespace


bool G_XRModelsEnabled()
{
    auto const option=sdlayer_xr_option("EDUKE32_XR_MODELS");
    return vr_models && usemodels && option && !Bstrcmp(option,"1");
}

static void G_XRFlatFrame();
void G_XRRegisterCvars()
{
    sdlayer_xr_flatFrameHook=G_XRFlatFrame;
    static osdcvardata_t cvars[] = {
        { "vr_models", "VR 3D models (held weapons, hands, body, other players, weapon wheel); 0 = native 2D sprites", (void *)&vr_models, CVAR_BOOL, 0, 1 },
        { "vr_laser", "VR laser pointer from the weapon to the aim point", (void *)&vr_laser, CVAR_BOOL, 0, 1 },
        { "vr_fullbody", "VR true full body (IK arms/legs; hands attached); 0 = floating hands and foot", (void *)&vr_fullbody, CVAR_BOOL, 0, 1 },
        { "vr_ptt_button", "VR push-to-talk button (voice_mode 1): 0 = left Y / Index left B, 1 = left X / Index left A, 2 = right B", (void *)&vr_ptt_button, CVAR_INT, 0, 2 },
        { "vr_lefttrigger", "VR left trigger: 0 = mighty foot (alt fire on the right stick click), 1 = alt fire (kick on the right stick click)", (void *)&vr_lefttrigger, CVAR_BOOL, 0, 1 },
    };
    for (auto &cv : cvars) OSD_RegisterCvar(&cv, osdcmd_cvar_set);
}

// ---- Model sets for the VR settings menu. The launcher lists the installed sets
// (EDUKE32_XR_MODEL_SETS "name=title;...") and the loaded one; choosing another set records it in
// the launcher's config and, on a restart, relaunches through the launcher with it.
namespace
{
struct ModelSet { std::string name, title; };
std::vector<ModelSet> const &modelSets()
{
    static std::vector<ModelSet> sets=[]() {
        std::vector<ModelSet> list;
        if (char const *env=std::getenv("EDUKE32_XR_MODEL_SETS"))
        {
            std::string const all=env;
            size_t start=0;
            while (start<=all.size())
            {
                size_t const end=std::min(all.find(';',start),all.size());
                std::string const item=all.substr(start,end-start);
                size_t const eq=item.find('=');
                if (eq!=std::string::npos && eq>0) list.push_back({item.substr(0,eq),item.substr(eq+1)});
                start=end+1;
            }
        }
        if (list.empty()) list.push_back({"","3D models"});   // not started by the launcher
        return list;
    }();
    return sets;
}
int pendingModelSet=-1;
}

int G_XRModelSetCount() { return int(modelSets().size()); }
char const *G_XRModelSetTitle(int index)
{
    return unsigned(index)<modelSets().size() ? modelSets()[index].title.c_str() : "";
}
int G_XRLoadedModelSet()
{
    char const *loaded=std::getenv("EDUKE32_XR_MODEL_SET");
    for (size_t i=0;i<modelSets().size();++i)
        if (loaded ? modelSets()[i].name==loaded : modelSets()[i].name.empty()) return int(i);
    return 0;
}
int G_XRChosenModelSet() { return pendingModelSet>=0 ? pendingModelSet : G_XRLoadedModelSet(); }

bool G_XRChooseModelSet(int index)
{
    if (unsigned(index)>=modelSets().size()) return false;
    vr_models=1;
    pendingModelSet=index==G_XRLoadedModelSet() ? -1 : index;
    auto const &name=modelSets()[index].name;
    char const *conf=std::getenv("EDUKE32_XR_LAUNCHER_CONF");
    if (!conf || !*conf || name.empty()) return pendingModelSet>=0;
    // Keep every other line of the launcher config; replace its pack= choice.
    std::string kept;
    if (FILE *in=std::fopen(conf,"r"))
    {
        char line[512];
        while (std::fgets(line,sizeof(line),in))
            if (std::strncmp(line,"pack=",5)) kept+=line;
        std::fclose(in);
    }
    if (!kept.empty() && kept.back()!='\n') kept+='\n';
    kept+="pack="+name+"\n";
    std::string const dir=std::string(conf).substr(0,std::string(conf).rfind('/'));
    if (!dir.empty()) { Bmkdir(dir.substr(0,dir.rfind('/')).c_str(),0700); Bmkdir(dir.c_str(),0700); }
    if (FILE *out=std::fopen(conf,"w")) { std::fputs(kept.c_str(),out); std::fclose(out); }
    else LOG_F(WARNING,"VR model set: cannot write %s.",conf);
    LOG_F(INFO,"VR model set chosen: %s (%s).",name.c_str(),pendingModelSet>=0 ? "restart to load" : "loaded");
    return pendingModelSet>=0;
}

bool G_XRCanRestartForModelSet()
{
    char const *request=std::getenv("EDUKE32_XR_RESTART_REQUEST");
    return pendingModelSet>=0 && request && *request;
}

bool G_XRRequestModelSetRestart()
{
    if (!G_XRCanRestartForModelSet()) return false;
    FILE *out=std::fopen(std::getenv("EDUKE32_XR_RESTART_REQUEST"),"w");
    if (!out) return false;
    std::fprintf(out,"%s\n",modelSets()[pendingModelSet].name.c_str());
    std::fclose(out);
    return true;
}

// Models the VR pack adds to native world sprites (third-person Duke, the 3D pistol pickup) hide
// with vr_models 0; only flags this code set are cleared again.
void G_XRWorldModelToggle(int spriteNum, int picnum)
{
    static std::vector<bool> flagged(MAXSPRITES);
    if ((unsigned)spriteNum>=MAXSPRITES || (picnum!=APLAYER && picnum!=FIRSTGUNSPRITE)) return;
    auto &flags=spriteext[spriteNum].flags;
    if (!vr_models)
    {
        if (!(flags & SPREXT_NOTMD)) { flags|=SPREXT_NOTMD; flagged[spriteNum]=true; }
    }
    else if (flagged[spriteNum]) { flags&=~SPREXT_NOTMD; flagged[spriteNum]=false; }
}

namespace
{
static int32_t hudMappedModelTile()
{
    if (!G_XRModelsEnabled() || !loadHudModelMap()) return -1;
    auto const p=g_player[myconnectindex].ps;
    if (!p || p->curr_weapon!=hudPredictedWeapon || hudPredictedModel<0 || md_tilehasmodel(hudPredictedModel,0)<0) return -1;
    return hudPredictedModel;
}
// Native families first; a HUD-mapped model only for otherwise unsupported weapons.
static int weaponModelTile(XRWeaponFamily family);
static XRWeaponFamily effectiveWeaponFamily()
{
    auto const family=P_XRWeaponFamily();
    // A native family without its own model defers to the HUD-mapped model.
    bool const nativeModel=family!=XRWeaponFamily::Unsupported && md_tilehasmodel(weaponModelTile(family),0)>=0;
    return !nativeModel && hudMappedModelTile()>=0 ? XRWeaponFamily::HudMapped : family;
}

static int weaponModelTile(XRWeaponFamily family)
{
    if (family==XRWeaponFamily::HudMapped) return hudMappedModelTile();
    if (family==XRWeaponFamily::StockHeld)
        return XRHeldModelTileBase+g_player[myconnectindex].ps->curr_weapon;
    return family==XRWeaponFamily::AARpg ? RPGSPRITE
        : family==XRWeaponFamily::StockPistol || family==XRWeaponFamily::AAPistol ? FIRSTGUNSPRITE : -1;
}
// The mighty foot (KNEE_WEAPON and quick kicks) as a 3D boot on the VR tile reserved for weapon 0.
constexpr int XRBootModelTile=XRHeldModelTileBase+KNEE_WEAPON;
static bool bootModelAvailable() { return G_XRModelsEnabled() && md_tilehasmodel(XRBootModelTile,0)>=0; }
// While the current weapon is shown in 3D (or is the mighty foot with the 3D boot) the native
// 2D weapon display stays hidden as a whole: Duke's 2D hands, the kick knee, weapon lower/raise
// animations, fist/tip/access-card hands. Only a weapon without any model falls back to its 2D
// sprite (RazeXR style).
static bool heldModelShown; // the held weapon model was drawn in this frame's world pass
static bool nativeWeaponHidden()
{
    if (!G_XRModelsEnabled()) return false;
    auto const p=g_player[myconnectindex].ps;
    if (!p) return false;
    if (p->curr_weapon==KNEE_WEAPON) return bootModelAvailable();
    auto const family=effectiveWeaponFamily();
    if (family==XRWeaponFamily::Unsupported || md_tilehasmodel(weaponModelTile(family),0)<0) return false;
    // Never leave the hand empty: hide the 2D art only when the 3D weapon was drawn, or during the
    // native switch/kick/hand animations (which the 3D hand replaces).
    bool const transient=p->weapon_pos || p->last_weapon>=0 || p->holster_weapon || p->knee_incs || p->quick_kick
        || p->last_quick_kick || p->fist_incs || p->knuckle_incs || p->tipincs || p->access_incs;
    return heldModelShown || transient;
}
static XRWeaponFamily mountedWeaponFamily()
{
    auto const family=effectiveWeaponFamily();
    // Without any held model for this family there is nothing to calibrate
    // from; aim from the controller instead of suppressing fire. A present
    // model with a missing tag still fails closed below in weaponMuzzle.
    if (family==XRWeaponFamily::Unsupported || md_tilehasmodel(weaponModelTile(family),0)<0)
        return XRWeaponFamily::Unsupported;
    auto value=sdlayer_xr_option("EDUKE32_XR_WEAPON_MOUNT");
    if (value && !Bstrcmp(value,"1")) return family;
    // Preserve the legacy opt-in: it must not move an RPG's gameplay muzzle.
    value=sdlayer_xr_option("EDUKE32_XR_PISTOL_MOUNT");
    return value && !Bstrcmp(value,"1") && family!=XRWeaponFamily::AARpg ? family : XRWeaponFamily::Unsupported;
}
static bool worldDrawArmed;
static eduke_xr::Runtime *presentationRuntime;
static uint64_t presentationGeneration;
struct WorldReceipt
{
    eduke_xr::Runtime *runtime=nullptr;
    uint64_t generation=0, serial=0;
    bool opaque=false, masks=false;
    bool models=true, handModels=false;
};
static WorldReceipt worldReceipt;
// Explicit diagnostics only: capture each naturally observed selected native weapon
// counter once, using the same-frame native model oracle. No animation clock.
static std::string modelAnimationCapture, weaponAnimationCapture;
static std::array<bool,16> gripCaptures{};
static int lastGripState=-1;
static unsigned gripDiagnostics;
static struct
{
    eduke_xr::Runtime *runtime=nullptr;
    uint64_t generation=0, serial=0;
    int player=-1;
    XRWeaponPresentation presentation{};
    uint8_t seen=0; // native body=1, optional magazine=2, optional hand=4
    bool mismatch=false;
    bool weaponSegment=false;
    bool hideNative=false; // whole native weapon segment hidden (see nativeWeaponHidden)
} handModelReceipt;

static void accountWorldFrame(bool opaque, bool masks, bool fixture, bool models=true, bool handModels=false)
{
    ++worldFrames;
    if (opaque) ++worldMultiviewFrames; else ++worldOracleFrames;
    if (masks) ++worldMaskMultiviewFrames; else ++worldMaskOracleFrames;
    if (!models) ++worldModelOracleFrames;
    if (models && handModels) ++worldModelMultiviewFrames;
    if (opaque && masks && models) ++worldFullMultiviewFrames;
    if (!fixture && worldFrames==60)
        LOG_F(INFO,"OpenXR world oracle: 60 frames, opaque multiview=%u twoPass=%u; masks multiview=%u twoPass=%u full multiview=%u; hand models twoPass=%u multiview=%u; one animation transaction per frame.",
              unsigned(worldMultiviewFrames),unsigned(worldOracleFrames),unsigned(worldMaskMultiviewFrames),
              unsigned(worldMaskOracleFrames),unsigned(worldFullMultiviewFrames),unsigned(worldModelOracleFrames),unsigned(worldModelMultiviewFrames));
}

static bool overlayEnabled()
{
    auto enabled=sdlayer_xr_option("EDUKE32_XR_UI");
    return enabled && !Bstrcmp(enabled,"2");
}
static eduke_xr::Runtime *menuRuntime;
static uint64_t menuGeneration, menuOwner;
// Geometry from the same acquired world frame; no separate presentation owner.
struct WeaponVisual
{
    bool selected=false, valid=false, clamped=false;
    int player=-1, hand=-1, model=-1;
    XRWeaponFamily family=XRWeaponFamily::Unsupported;
    vec3_t root{}, correction{};
    int16_t sector=-1;
    VRShotInput ray{}; // Render-only direction/bounds; never installed as input.
    XrPosef pose{}; // Resolved muzzle in the acquired frame's LOCAL space.
    XrVector3f basis[3]{};
};
static struct
{
    float matrix[2][16]; vec3_t eye[2]; bool valid=false;
    Camera body{};
    WeaponVisual weapon{};
    std::string diagnosticCrosshairPrefix;
} crosshairViews;
static eduke_xr::ActionInput rawInput;
static std::array<uint32_t,2> activeInputButtons{}, blockedInputButtons{};
static float aimYawOffset, aimPitchOffset;
static bool aimPoseWasValid, shotLookAllowed=true;
static bool shotReferenceInvalidated;
static bool handShotsRequested()
{
    auto mode=sdlayer_xr_option("EDUKE32_XR_HAND_SHOTS");
    return mode && !Bstrcmp(mode,"1");
}

// Comfort options. Snap turn in degrees (0 = smooth native stick turning).
static float snapTurnDegrees()
{
    auto value=sdlayer_xr_option("EDUKE32_XR_SNAP_TURN");
    float const degrees=value ? float(std::atof(value)) : 0.f;
    return degrees>0.f && degrees<=180.f ? degrees : 0.f;
}
static bool stickPitchAllowed()
{
    auto value=sdlayer_xr_option("EDUKE32_XR_STICK_PITCH");
    return !value || Bstrcmp(value,"0");
}
static float pendingSnapTurn; // radians, consumed by the next native tick

// Immersive pipebombs: hold the trigger, swing, release to throw with the
// hand's measured velocity; the off-hand trigger detonates live remote bombs.
static bool physicalThrowEnabled()
{
    auto value=sdlayer_xr_option("EDUKE32_XR_PHYSICAL_THROW");
    return value && !Bstrcmp(value,"1");
}
static struct
{
    bool held=false, pending=false, detonateHeld=false, detonatePending=false;
    XrVector3f velocity{}; // LOCAL metres/second at release
    float speed=0.f;
    struct Sample { double time; XrVector3f velocity; } recent[16]{};
    unsigned next=0;
} xrThrow;

// Opt-in while tracked weapon presentation and the full authority matrix develop.
static int aimHand()
{
    auto mode=sdlayer_xr_option("EDUKE32_XR_AIM");
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

// Weapon and gadget wheels (after Q3VR's controller mode). Hold a wheel's button to open it in
// front of that hand (weapon wheel: weapon hand, right stick click / Index right trackpad touch,
// else hold the turn stick up; gadget wheel: off hand, left stick click / Index left trackpad
// touch), frozen to the hand's direction at that moment. Turning the wrist ~22 degrees moves a
// pointer bead (with a beam from the hand) across the ring; the slot under it lights up; release
// to pick. Weapons switch through the native weapon keys (networked input; pressing again for the
// Expander/Flamethrower toggles), gadgets through the native inventory keys.
struct Wheel
{
    bool gadgets=false;
    bool open=false, hapticPending=false;
    double openedAt=0;
    int hand=1;
    XrVector3f centre{}, forward{}, right{}, up{};
    XrVector3f faceRight{}, faceUp{}, faceBack{}; // display frame: upright, facing the head at opening
    float pointerX=0.f, pointerY=0.f;              // pointer on the ring, radius 1 = slot circle
    int hovered=-1;
    int slots[12]{};
    unsigned count=0;
    int target=-1, lastCurrent=-1;
    double deadline=0, pressUntil=0, waitUntil=0;
};
static Wheel wheel, gadgetWheel{true};

static bool weaponWheelEnabled()
{
    auto const option=sdlayer_xr_option("EDUKE32_XR_WEAPON_WHEEL");
    return option && !Bstrcmp(option,"1");
}

static int wheelCurrentWeapon(DukePlayer_t const *p)
{
    int const weapon=p->curr_weapon;
    return weapon==HANDREMOTE_WEAPON ? HANDBOMB_WEAPON : weapon;
}

static bool wheelSelectable(DukePlayer_t const *p, int weapon)
{
    if ((unsigned)weapon>=MAX_WEAPONS || !(p->gotweapon & (1<<weapon))) return false;
    if (weapon==HANDBOMB_WEAPON) return p->ammo_amount[weapon]>0 || p->hbomb_on;
    return p->ammo_amount[weapon]>0;
}

static int wheelModelTile(DukePlayer_t const *p, int weapon)
{
    if (weapon==HANDBOMB_WEAPON && p->ammo_amount[weapon]<=0 && p->hbomb_on) weapon=HANDREMOTE_WEAPON;
    return weapon==PISTOL_WEAPON ? 21 : XRHeldModelTileBase+weapon;
}

// Usable inventory items (scuba gear and boots work by themselves): item, native key, pickup tile.
static constexpr unsigned GadgetCount=5;
static int gadgetItem(int gadget)
{
    static int const items[GadgetCount]={GET_FIRSTAID,GET_STEROIDS,GET_HOLODUKE,GET_JETPACK,GET_HEATS};
    return items[gadget];
}
static int gadgetKey(int gadget)
{
    static int const keys[GadgetCount]={gamefunc_MedKit,gamefunc_Steroids,gamefunc_Holo_Duke,gamefunc_Jetpack,gamefunc_NightVision};
    return keys[gadget];
}
static int gadgetTile(int gadget)
{
    switch (gadget)
    {
        case 0: return FIRSTAID;
        case 1: return STEROIDS;
        case 2: return HOLODUKE;
        case 3: return JETPACK;
        default: return HEATSENSOR;
    }
}
static bool gadgetSelectable(DukePlayer_t const *p, int gadget) { return p->inv_amount[gadgetItem(gadget)]>0; }

static bool slotSelectable(Wheel const &w, DukePlayer_t const *p, int slot)
{
    return w.gadgets ? gadgetSelectable(p,w.slots[slot]) : wheelSelectable(p,w.slots[slot]);
}

static void wheelFillSlots(Wheel &w)
{
    w.count=0;
    if (w.gadgets)
    {
        for (unsigned gadget=0;gadget<GadgetCount;++gadget) w.slots[w.count++]=int(gadget);
        return;
    }
    static int const order[]={PISTOL_WEAPON,SHOTGUN_WEAPON,CHAINGUN_WEAPON,RPG_WEAPON,HANDBOMB_WEAPON,SHRINKER_WEAPON,
                              GROW_WEAPON,DEVISTATOR_WEAPON,TRIPBOMB_WEAPON,FREEZE_WEAPON,FLAMETHROWER_WEAPON};
    for (int weapon:order)
    {
        if (weapon==GROW_WEAPON && !PLUTOPAK) continue;
        if (weapon==FLAMETHROWER_WEAPON && !WORLDTOUR) continue;
        w.slots[w.count++]=weapon;
    }
}

// The 3D ring needs every slot's model; otherwise the weapons are drawn as 2D pickup sprites on a
// panel at the ring (G_XRDrawWheelPanels). Gadgets always use the panel.
static bool wheelUses3D()
{
    if (!G_XRModelsEnabled()) return false;
    auto const p=g_player[myconnectindex].ps;
    for (unsigned i=0;i<wheel.count;++i)
        if (md_tilehasmodel(wheelModelTile(p,wheel.slots[i]),0)<0) return false;
    return true;
}

static int wheelKey(int weapon)
{
    if (weapon==GROW_WEAPON) weapon=SHRINKER_WEAPON;
    if (weapon==FLAMETHROWER_WEAPON) weapon=FREEZE_WEAPON;
    return gamefunc_Weapon_1+weapon;
}

static bool wheelLog() { return std::getenv("EDUKE32_XR_TEST_WHEEL")!=nullptr; }

// Per input sample: open/close, hover and commit; returns true while the wheel owns the turn stick.
static bool updateWheel(Wheel &w, uint64_t &buttons, uint32_t handDown)
{
    auto const p=g_player[myconnectindex].ps;
    double const now=double(timerGetNanoTicks())/double(timerGetNanoTickRate());
    char const *const name=w.gadgets ? "gadget" : "weapon";
    int const weaponHand=aimHand()>=0 ? aimHand() : 1;
    int const hand=w.gadgets ? 1-weaponHand : weaponHand;
    bool const usable=weaponWheelEnabled() && aimHand()>=0 && inputValid() && p && (p->gm & MODE_GAME) && !(p->gm & MODE_MENU)
        && (unsigned)p->i<MAXSPRITES && sprite[p->i].extra>0 && !p->dead_flag && p->newowner<0 && !ud.recstat
        && rawInput.hands[hand].aimValid && validPose(rawInput.hands[hand].aimPose);
    // Pending pick: press the slot's native key (weapons: release, wait for the change, repeat).
    if (w.target>=0)
    {
        if (w.gadgets)
        {
            if (now<w.pressUntil) buttons|=uint64_t(1)<<gadgetKey(w.target);
            else w.target=-1;
        }
        else
        {
            int const current=p ? wheelCurrentWeapon(p) : -1;
            if (!p || current==w.target || now>w.deadline || !wheelSelectable(p,w.target)) w.target=-1;
            else if (now<w.pressUntil) buttons|=uint64_t(1)<<wheelKey(w.target);
            else if (now>=w.waitUntil || current!=w.lastCurrent)
            {
                w.pressUntil=now+.07; w.waitUntil=w.pressUntil+.35; w.lastCurrent=current;
                buttons|=uint64_t(1)<<wheelKey(w.target);
            }
        }
    }
    bool held;
    if (w.gadgets)
        held=(rawInput.hands[0].activeButtons & eduke_xr::ButtonGadget) && (handDown & eduke_xr::ButtonGadget);
    else
    {
        auto const &stickHand=rawInput.hands[1];
        float const sx=stickHand.stickActive ? stickHand.stick.x : 0.f, sy=stickHand.stickActive ? stickHand.stick.y : 0.f;
        // The dedicated button when this controller binds one, else the stick-up gesture.
        bool const button=stickHand.activeButtons & eduke_xr::ButtonWheel;
        held=button ? bool(handDown & eduke_xr::ButtonWheel) : w.open ? sy>=.35f : (sy>.7f && std::fabs(sx)<.6f);
    }
    if (!usable) { w.open=false; w.hovered=-1; return false; }
    auto const &aim=rawInput.hands[hand].aimPose;
    auto const forward=rotate(aim.orientation,{0,0,-1});
    if (!w.open)
    {
        if (!held) return false;
        wheelFillSlots(w);
        w.open=true; w.openedAt=now; w.hovered=-1; w.hand=hand; w.pointerX=w.pointerY=0.f;
        // Yaw/pitch frame of the hand at opening (no roll), like Q3VR.
        XrVector3f r={-forward.z,0.f,forward.x};
        float const rl=std::sqrt(r.x*r.x+r.z*r.z);
        r=rl>1e-4f ? XrVector3f{r.x/rl,0.f,r.z/rl} : XrVector3f{1,0,0};
        w.forward=forward; w.right=r;
        w.up={r.y*forward.z-r.z*forward.y,r.z*forward.x-r.x*forward.z,r.x*forward.y-r.y*forward.x};
        w.centre=aim.position;
        // Display the ring upright and facing the head (pointing still uses the wrist frame above).
        XrVector3f const head=rawInput.headValid && validPose(rawInput.headPose) ? rawInput.headPose.position
            : XrVector3f{aim.position.x-forward.x,aim.position.y-forward.y,aim.position.z-forward.z};
        XrVector3f const ring={aim.position.x+forward.x*.36f,aim.position.y+forward.y*.36f,aim.position.z+forward.z*.36f};
        XrVector3f back={head.x-ring.x,0.f,head.z-ring.z};
        float const bl=std::sqrt(back.x*back.x+back.z*back.z);
        back=bl>1e-4f ? XrVector3f{back.x/bl,0.f,back.z/bl} : XrVector3f{-forward.x,0.f,-forward.z};
        w.faceBack=back; w.faceUp={0.f,1.f,0.f};
        w.faceRight={back.z,0.f,-back.x};   // up x back
        if (wheelLog())
        {
            char list[64]{}; int at=0;
            for (unsigned i=0;i<w.count;++i) at+=Bsnprintf(list+at,sizeof(list)-at,"%s%d",i?",":"",w.slots[i]);
            LOG_F(INFO,"OpenXR %s wheel: open slots=%u order=%s.",name,w.count,list);
        }
        return !w.gadgets;
    }
    if (!held)
    {
        w.open=false;
        if (w.hovered>=0)
        {
            int const item=w.slots[w.hovered];
            if (w.gadgets) { w.target=item; w.pressUntil=now+.07; }
            else if (item!=wheelCurrentWeapon(p) || (item==SHRINKER_WEAPON && p->curr_weapon==GROW_WEAPON)
                     || (item==FREEZE_WEAPON && p->curr_weapon==FLAMETHROWER_WEAPON))
            {
                w.target=item; w.deadline=now+1.5; w.pressUntil=w.waitUntil=0; w.lastCurrent=-2;
            }
            if (wheelLog()) LOG_F(INFO,"OpenXR %s wheel: commit %s=%d current=%d.",name,w.gadgets ? "gadget" : "weapon",item,p->curr_weapon);
        }
        else if (wheelLog()) LOG_F(INFO,"OpenXR %s wheel: close without selection.",name);
        w.hovered=-1;
        return !w.gadgets;
    }
    // Pointer from the wrist rotation since opening (22.5 degrees reach the slot circle);
    // slots clockwise from the top.
    float const s=std::sin(22.5f*Pi/180.f);
    float x=(forward.x*w.right.x+forward.y*w.right.y+forward.z*w.right.z)/s;
    float y=(forward.x*w.up.x+forward.y*w.up.y+forward.z*w.up.z)/s;
    float const length=std::hypot(x,y);
    if (length>1.15f) { x*=1.15f/length; y*=1.15f/length; }
    w.pointerX=x; w.pointerY=y;
    int hovered=-1;
    if (now-w.openedAt>.1 && length>.55f && w.count)
    {
        float angle=std::atan2(x,y);
        if (angle<0) angle+=2*Pi;
        int const slot=int(std::lround(angle/(2*Pi/w.count)))%int(w.count);
        if (slotSelectable(w,p,slot)) hovered=slot;
    }
    if (hovered!=w.hovered && hovered>=0)
    {
        w.hapticPending=true;
        if (wheelLog()) LOG_F(INFO,"OpenXR %s wheel: hover %s=%d.",name,w.gadgets ? "gadget" : "weapon",w.slots[hovered]);
    }
    w.hovered=hovered;
    return !w.gadgets;
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
        bool const valid=aimPoseUsable();
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
    if (!stickPitchAllowed()) analog.dpitch=0;
    uint64_t wheelButtons=0;
    bool const wheelOwnsStick=updateWheel(wheel,wheelButtons,down[1]);
    updateWheel(gadgetWheel,wheelButtons,down[0]);
    if (wheelOwnsStick) analog.dyaw=analog.dpitch=0;
    if (float const snap=wheelOwnsStick ? 0.f : snapTurnDegrees())
    {
        // One discrete body rotation per stick flick; re-arm near centre.
        static bool armed=true;
        float const x=rawInput.hands[1].stickActive ? rawInput.hands[1].stick.x : 0.f;
        if (armed && std::fabs(x)>.6f)
        {
            pendingSnapTurn+=(x>0.f ? 1.f : -1.f)*snap*Pi/180.f;
            armed=false;
        }
        else if (std::fabs(x)<.3f) armed=true;
        analog.dyaw=0;
    }
    uint64_t buttons=wheelButtons;
    auto const button=[&](bool pressed, unsigned gamefunc) { if (pressed) buttons |= uint64_t(1)<<gamefunc; };
    // Right trigger fires (remote pipebombs: the detonator in the same hand), left trigger is the
    // mighty foot and the right stick click alt fire (vr_lefttrigger 1 swaps them; mods such as
    // Alien Armageddon use alt fire), left grip is use/interact, right grip runs.
    button(down[1]&ButtonSelect,gamefunc_Fire);
    button(down[0]&ButtonSelect,vr_lefttrigger ? gamefunc_Alt_Fire : gamefunc_Quick_Kick);
    button(down[1]&ButtonStickClick,vr_lefttrigger ? gamefunc_Quick_Kick : gamefunc_Alt_Fire);
    button(down[0]&ButtonGrip,gamefunc_Open);
    button(down[1]&ButtonPrimary,gamefunc_Jump);
    // Quick kick also on a right-stick-down flick.
    bool const kickFlick=!stickPitchAllowed() && !wheelOwnsStick && rawInput.hands[1].stickActive
        && rawInput.hands[1].stick.y<-.7f && std::fabs(rawInput.hands[1].stick.x)<.6f;
    button(kickFlick,gamefunc_Quick_Kick);
    // In push-to-talk mode the vr_ptt_button button talks instead of its usual function: left Y
    // (Index: left B, next weapon), left X (Index: left A, previous weapon) or right B (crouch).
    bool const talkMode=Voice_PushToTalkMode();
    unsigned const talkHand=vr_ptt_button==2 ? 1 : 0;
    uint32_t const talkBit=vr_ptt_button==1 ? ButtonPrimary : ButtonSecondary;
    auto const talkFree=[&](unsigned hand, uint32_t bit) { return !(talkMode && hand==talkHand && bit==talkBit); };
    button(talkFree(0,ButtonPrimary) && (down[0]&ButtonPrimary),gamefunc_Previous_Weapon);
    button(talkFree(0,ButtonSecondary) && (down[0]&ButtonSecondary),gamefunc_Next_Weapon);
    {
        // Always run (EDUKE32_XR_ALWAYS_RUN, on in the preset): the right grip walks instead.
        // The native rule combines the Run key with the user's auto-run setting.
        auto const always=sdlayer_xr_option("EDUKE32_XR_ALWAYS_RUN");
        bool const grip=down[1]&ButtonGrip;
        bool const wantRun=always && !Bstrcmp(always,"1") ? !grip : grip;
        button(ud.runkey_mode ? wantRun : (wantRun!=bool(ud.auto_run)),gamefunc_Run);
    }
    button(talkFree(1,ButtonSecondary) && (down[1]&ButtonSecondary),gamefunc_Crouch);
    Voice_SetPushToTalk(talkMode && (down[talkHand]&talkBit));
    if (physicalThrowEnabled() && aimHand()>=0)
    {
        int const hand=aimHand();
        auto const p=g_player[myconnectindex].ps;
        bool const bomb=(unsigned)p->curr_weapon<MAX_WEAPONS && PWEAPON(myconnectindex,p->curr_weapon,WorksLike)==HANDBOMB_WEAPON
            && p->ammo_amount[HANDBOMB_WEAPON]>0;
        double const now=double(timerGetNanoTicks())/double(timerGetNanoTickRate());
        auto const &input=rawInput.hands[hand];
        if (input.gripVelocityValid)
        {
            xrThrow.recent[xrThrow.next++%16]={now,input.gripVelocity};
        }
        bool const trigger=down[hand]&ButtonSelect;
        if (bomb && trigger) xrThrow.held=true;
        else if (bomb && xrThrow.held)
        {
            // Release: use the fastest hand sample of the last 120 ms.
            xrThrow.held=false;
            float best=0.f; XrVector3f velocity{};
            for (auto const &sample:xrThrow.recent)
                if (now-sample.time<=.12)
                {
                    float const speed=std::sqrt(dot(sample.velocity,sample.velocity));
                    if (speed>best) { best=speed; velocity=sample.velocity; }
                }
            if (best>=1.f) { xrThrow.pending=true; xrThrow.velocity=velocity; xrThrow.speed=best; }
        }
        else if (!bomb) xrThrow.held=xrThrow.pending=false;
        if (bomb)
        {
            // The pipebomb fires only through a measured throw.
            buttons&=~(uint64_t(1)<<gamefunc_Fire);
            if (xrThrow.pending) buttons|=uint64_t(1)<<gamefunc_Fire;
        }
    }
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
            Bsnprintf(state,sizeof(state),"focus=%u active=%u,%u buttons=%u,%u funcs=%llu axes=%d,%d,%d,%d menu=%u,%u,%u,%d gm=%u screen=%d aim=%u,%u gen=%llu held=%u,%u",
                      rawInput.focused,rawInput.hands[0].activeButtons,rawInput.hands[1].activeButtons,down[0],down[1],
                      (unsigned long long)buttons,analog.dx,analog.dz,analog.dyaw,analog.dpitch,
                      menu.b_advance,menu.b_return,menu.b_escape,int(menu.dir),unsigned(g_player[myconnectindex].ps->gm),int(g_currentMenu),
                      rawInput.hands[0].aimValid,rawInput.hands[1].aimValid,(unsigned long long)inputGeneration,
                      rawInput.hands[0].buttons&rawInput.hands[0].activeButtons,rawInput.hands[1].buttons&rawInput.hands[1].activeButtons);
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
        // Head-owned pitch keeps the rendered body level from the first frame.
        c.horizon=!stickPitchAllowed() ? F16(100)
            : fix16_from_float(100.f+128.f*std::tan(nativePitch(c.horizon)-aimPitchOffset));
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


// Keep a tracked eye inside the level instead of dropping the frame: clamp
// its height to the sector and pull it back towards the body camera until the
// native sector lookup and line of sight agree.
static bool placeEye(Camera const &base, vec3_t target, Camera &eye)
{
    auto const valid=[&](vec3_t p, int16_t &sector) {
        sector=base.sector;
        updatesector(p.x,p.y,&sector);
        if (sector<0) return false;
        int32_t ceiling, floor;
        getzsofslope(sector,p.x,p.y,&ceiling,&floor);
        int32_t const margin=4<<8;
        if (floor-ceiling<=2*margin) return false;
        p.z=std::max(ceiling+margin,std::min(p.z,floor-margin));
        updatesectorz(p.x,p.y,p.z,&sector);
        if (sector<0 || !cansee(base.pos.x,base.pos.y,base.pos.z,base.sector,p.x,p.y,p.z,sector)) return false;
        eye.pos=p;
        return true;
    };
    int16_t sector;
    if (valid(target,sector)) { eye.sector=sector; return true; }
    float low=0.f, high=1.f;
    bool found=false;
    for (int step=0;step<10;++step)
    {
        float const t=(low+high)*.5f;
        vec3_t const p{base.pos.x+int32_t(std::lround((target.x-base.pos.x)*t)),
                       base.pos.y+int32_t(std::lround((target.y-base.pos.y)*t)),
                       base.pos.z+int32_t(std::lround((target.z-base.pos.z)*t))};
        int16_t candidate;
        if (valid(p,candidate)) { low=t; sector=candidate; found=true; }
        else high=t;
    }
    if (!found)
    {
        eye.pos=base.pos;
        sector=base.sector;
    }
    eye.sector=sector;
    return sector>=0;
}

static fix16_t horizonFromTan(float tangent)
{
    // Native Q16 horizon range; explicit pitch carries the exact angle.
    return fix16_from_float(100.f+128.f*std::max(-200.f,std::min(tangent,200.f)));
}

bool makeEye(XrView const &view, Camera const &base, float aspect, Eye &eye, char const *&rejection)
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
    eye.split = false; eye.upSin=0.f; eye.upCos=1.f;
    vec3_t const target{base.pos.x+int32_t(std::lround((-p.z*co-p.x*si)*UnitsPerMetre)),
                        base.pos.y+int32_t(std::lround((-p.z*si+p.x*co)*UnitsPerMetre)),
                        base.pos.z-int32_t(std::lround(p.y*ZUnitsPerMetre))};
    if (!placeEye(base,target,eye.camera))
    {
        rejection="collision";
        return false;
    }

    auto const q = multiply(trackingRotation,view.pose.orientation);
    auto forward = rotate(q,{0,0,-1});
    float const horizontal = std::hypot(forward.x,forward.z);
    // The pass yaw follows the view direction. Looking straight up or down,
    // the view's own up vector (or its opposite) gives the same heading.
    XrVector3f yawForward{forward.x,0,forward.z};
    if (horizontal < 1e-3f)
    {
        auto const up=rotate(q,{0,1,0});
        float const sign=forward.y<0.f ? 1.f : -1.f;
        yawForward={up.x*sign,0,up.z*sign};
    }
    float const yawLength=std::hypot(yawForward.x,yawForward.z);
    if (!(yawLength > 1e-6f))
    { rejection="vertical"; return false; }
    yawForward={yawForward.x/yawLength,0,yawForward.z/yawLength};
    XrVector3f const right {-yawForward.z,0,yawForward.x};
    float const along=dot(forward,yawForward);
    float const pitchAngle=std::atan2(forward.y,along);
    XrVector3f const pitchForward{yawForward.x*std::cos(pitchAngle),std::sin(pitchAngle),yawForward.z*std::cos(pitchAngle)};
    auto const up = cross(right,pitchForward);
    auto actualRight = rotate(q,{1,0,0});
    eye.camera.angle = fix16_from_float((body+std::atan2(yawForward.x,-yawForward.z))*1024.f/Pi) & 0x7FFFFFF;
    eye.camera.horizon = horizonFromTan(std::tan(pitchAngle));
    eye.camera.roll = std::atan2(dot(actualRight,up),dot(actualRight,right));
    eye.left = std::tan(view.fov.angleLeft); eye.right = std::tan(view.fov.angleRight);
    eye.down = std::tan(view.fov.angleDown); eye.up = std::tan(view.fov.angleUp);
    eye.cover = std::max({std::fabs(eye.left),std::fabs(eye.right),
                         std::fabs(eye.down)*aspect,std::fabs(eye.up)*aspect});
    if (!(eye.cover > 0.f && eye.cover < 16.f))
    { rejection="fov"; return false; }
    // Native Polymost clips CPU rays to the yaw-forward half-space. When any
    // part of the frustum leaves it, add the complementary back pass.
    for (float x : {eye.left,eye.right})
        for (float y : {eye.down,eye.up})
        {
            auto const corner=rotate(q,{x,y,-1});
            if (dot(corner,yawForward) <= .02f*std::sqrt(dot(corner,corner)))
                eye.split=true;
        }
    eye.passes[0].camera=eye.camera;
    if (eye.split)
    {
        eye.upSin=std::sin(pitchAngle); eye.upCos=std::cos(pitchAngle);
        auto &back=eye.passes[1].camera;
        back=eye.camera;
        back.angle=(eye.camera.angle+F16(1024)) & 0x7FFFFFF;
        back.horizon=horizonFromTan(-std::tan(pitchAngle));
        back.roll=wrapRadians(eye.camera.roll+Pi);
    }
    return true;
}
void eyeState(Eye const &eye, unsigned pass=0)
{
    install(pass ? eye.passes[1].camera : eye.camera);
    renderSetAspect(std::lround(eye.cover*65536.f),81920);
    polymost_xrProjection(eye.left,eye.right,eye.down,eye.up);
    if (eye.split)
        polymost_xrViewPitch(eye.upSin,pass ? -eye.upCos : eye.upCos,SplitViewportClip,SplitNearClip);
}

struct WorldModelSample
{
    md3drawcontext_t context{};
    vec3_t root{};
    int16_t sector=-1;
    vec3f_t pivot{};
    XrVector3f basis[3]{}; // Canonical model unit to physical Build X/Y/Z-down.
};

struct HandModelSample : WorldModelSample
{
    XRWeaponPresentation presentation{};
    vec3f_t grip{};
    VRShotInput shot{};
};

struct GripModelSample : WorldModelSample
{
    XrPosef pose{};
    int state=0; // rest, index-ready, trigger-pressed (not MD3 frame indices).
};

struct BodyModelSample : WorldModelSample {};

// Test-only: report why the held weapon model was not drawn (on change).
static void heldReject(char const *where)
{
    static std::string last;
    static std::vector<std::string> seen;
    if (!std::getenv("EDUKE32_XR_TEST_HELD") || last==where) return;
    last=where;
    // Alternating reasons would flood the log: report each reason once per weapon.
    std::string const key=std::string(where)+"/"+std::to_string(g_player[myconnectindex].ps->curr_weapon);
    if (std::find(seen.begin(),seen.end(),key)!=seen.end()) return;
    seen.push_back(key);
    LOG_F(INFO,"OpenXR held model skipped: %s weapon=%d.",where,g_player[myconnectindex].ps->curr_weapon);
}

// Stable palette-zero metadata is shared by native input and local visuals.
// Texture availability, HUD counters and material state never choose a muzzle.
bool weaponMuzzle(XRWeaponFamily family, int hand, int &model, vec3f_t &muzzle, vec3f_t &palm, XrVector3f &position)
{
    if (unsigned(hand)>=2) { heldReject("weaponMuzzle#1"); return false; }
    auto const &input=rawInput.hands[hand];
    model=md_tilehasmodel(weaponModelTile(family),0);
    if (!input.gripValid || !validPose(input.gripPose) || !input.aimValid || !validPose(input.aimPose)
        || !md3_gettagposition(model,"tag_muzzle",&muzzle)) { heldReject("weaponMuzzle#2"); return false; }
    if (!md3_gettagposition(model,hand ? "tag_palm_right" : "tag_palm_left",&palm)
        && ((family!=XRWeaponFamily::StockHeld && family!=XRWeaponFamily::HudMapped)
            || !md3_gettagposition(model,"tag_grip",&palm))) { heldReject("weaponMuzzle#3"); return false; }
    auto const d=rotate(input.aimPose.orientation,{(muzzle.y-palm.y)/64.f,
                                                 (muzzle.z-palm.z)/64.f,-(muzzle.x-palm.x)/64.f});
    position={input.gripPose.position.x+d.x,input.gripPose.position.y+d.y,input.gripPose.position.z+d.z};
    return std::isfinite(position.x) && std::isfinite(position.y) && std::isfinite(position.z);
}

// One current-frame visual, owned by the existing world/HUD presentation.
// This never polls input or writes the native shot stream. Simulation remains
// 30 Hz; local hands and the aiming preview follow acquired XR frame poses.
void prepareWeaponVisual(Camera const &body, eduke_xr::Runtime *runtime)
{
    auto &visual=crosshairViews.weapon;
    visual={}; crosshairViews.body=body;
    visual.family=handShotsRequested() && aimHand()>=0 ? mountedWeaponFamily() : XRWeaponFamily::Unsupported;
    visual.selected=visual.family!=XRWeaponFamily::Unsupported;
    if (!visual.selected) { heldReject("prepareWeaponVisual#1"); return; }
    visual.player=myconnectindex; visual.hand=aimHand();
    if (!overlayEnabled() || !handShotsRequested() || !localAimCamera() || !aimPoseUsable() || !recentered
        || inputRuntime!=runtime || inputGeneration!=runtime->generation() || shotReferenceInvalidated || !shotLookAllowed
        || !G_VRShotValid(myconnectindex)) { heldReject("prepareWeaponVisual#2"); return; }
    vec3f_t muzzle{}, palm{}; XrVector3f position;
    if (!weaponMuzzle(visual.family,visual.hand,visual.model,muzzle,palm,position)) { heldReject("prepareWeaponVisual#3"); return; }
    visual.pose=rawInput.hands[visual.hand].aimPose;
    visual.pose.position=position;
    auto const tracking=multiply(pitchRoll(nativePitch(body.horizon),body.roll),inverseYaw);
    float const yaw=fix16_to_float(body.angle)*Pi/1024.f, co=std::cos(yaw), si=std::sin(yaw);
    auto const toBuild=[&](XrVector3f v) {
        return XrVector3f{(-v.z*co-v.x*si)*UnitsPerMetre,(-v.z*si+v.x*co)*UnitsPerMetre,-v.y*ZUnitsPerMetre};
    };
    auto const delta=toBuild(rotate(tracking,{position.x-origin.x,position.y-origin.y,position.z-origin.z}));
    double const requested[]={double(body.pos.x)+std::round(delta.x),double(body.pos.y)+std::round(delta.y),
                              double(body.pos.z)+std::round(delta.z)};
    auto const p=g_player[myconnectindex].ps;
    double const anchor[]={double(p->pos.x),double(p->pos.y),double(p->pos.z)+p->pyoff};
    auto const orientation=multiply(tracking,visual.pose.orientation);
    XrVector3f const axes[]={{0,0,-1},{1,0,0},{0,1,0}};
    for (unsigned axis=0;axis<3;++axis)
    {
        // The resolver's optional position does not enforce the shot reach
        // limit itself. Validate against the actual native anchor explicitly.
        double const offset=requested[axis]-anchor[axis];
        if (!std::isfinite(requested[axis]) || requested[axis]<INT32_MIN || requested[axis]>INT32_MAX
            || !std::isfinite(offset) || std::fabs(offset)>=32767.) { heldReject("prepareWeaponVisual#4"); return; }
        visual.ray.offset[axis]=int16_t(offset);
        auto const v=toBuild(rotate(orientation,axes[axis]));
        visual.basis[axis]={v.x/64.f,v.y/64.f,v.z/64.f};
    }
    float const forward[]={visual.basis[0].x*64.f/UnitsPerMetre,visual.basis[0].y*64.f/UnitsPerMetre,
                           visual.basis[0].z*64.f/ZUnitsPerMetre};
    for (unsigned axis=0;axis<3;++axis)
        visual.ray.direction[axis]=int16_t(std::lround(std::max(-1.f,std::min(1.f,forward[axis]))*32767.f));
    visual.ray.flags=VRShotEnabled|VRShotValid;
    if (!G_VRValidateShot(visual.ray)) { heldReject("prepareWeaponVisual#5"); return; }
    vec3_t const desired={int32_t(requested[0]),int32_t(requested[1]),int32_t(requested[2])};
    if (!G_VRResolveShot(myconnectindex,visual.root,visual.sector,visual.clamped,&desired)) { heldReject("prepareWeaponVisual#6"); return; }
    int64_t const correction[]={int64_t(visual.root.x)-desired.x,int64_t(visual.root.y)-desired.y,int64_t(visual.root.z)-desired.z};
    for (auto value:correction) if (value<INT32_MIN || value>INT32_MAX) { heldReject("prepareWeaponVisual#7"); return; }
    visual.correction={int32_t(correction[0]),int32_t(correction[1]),int32_t(correction[2])};
    // Include Build rounding when converting the resolved muzzle back to LOCAL,
    // so the native ART card and mesh consume exactly the same visual root.
    float const dx=float(int64_t(visual.root.x)-body.pos.x)/UnitsPerMetre;
    float const dy=float(int64_t(visual.root.y)-body.pos.y)/UnitsPerMetre;
    XrVector3f const relative={-dx*si+dy*co,-float(int64_t(visual.root.z)-body.pos.z)/ZUnitsPerMetre,-dx*co-dy*si};
    auto const local=rotate({-tracking.x,-tracking.y,-tracking.z,tracking.w},relative);
    visual.pose.position={origin.x+local.x,origin.y+local.y,origin.z+local.z};
    visual.valid=true;
}

bool weaponVisualOwned()
{
    auto const &visual=crosshairViews.weapon;
    return crosshairViews.valid && visual.valid && visual.player==myconnectindex && visual.hand==aimHand()
        && visual.family==P_XRWeaponFamily() && visual.model==md_tilehasmodel(weaponModelTile(visual.family),0)
        && inputRuntime==menuRuntime && inputGeneration==menuGeneration && inputValid()
        && aimPoseUsable() && rawInput.hands[visual.hand].gripValid
        && G_VRShotValid(myconnectindex);
}

int gripModelTile(unsigned hand)
{
    auto value=sdlayer_xr_option(hand ? "EDUKE32_XR_HAND_RIGHT_TILE" : "EDUKE32_XR_HAND_LEFT_TILE");
    if (!value || !*value) return -1;
    unsigned tile=0;
    for (;*value;++value)
    {
        if (*value<'0' || *value>'9') return -1;
        unsigned const digit=*value-'0';
        if (tile>(MAXTILES-1-digit)/10u) return -1;
        tile=tile*10+digit;
    }
    return int(tile);
}

bool prepareGripModel(GripModelSample &sample, unsigned hand, Camera const &body, eduke_xr::Runtime *runtime)
{
    int const tile=gripModelTile(hand);
    auto const p=g_player[myconnectindex].ps;
    auto const &input=rawInput.hands[hand];
    if (tile<0 || !G_XRModelsEnabled() || !overlayEnabled() || !recentered || !inputValid()
        || inputRuntime!=runtime || inputGeneration!=runtime->generation()
        || !rawInput.headValid || !validPose(rawInput.headPose) || !input.gripValid || !validPose(input.gripPose)
        || screenpeek!=myconnectindex || ud.recstat || ud.show_help || ud.overhead_on || ud.camerasprite>=0
        || ud.drawweapon!=1 || !(p->gm & MODE_GAME) || (p->gm & MODE_MENU) || p->newowner>=0
        || p->over_shoulder_on || p->dead_flag || unsigned(p->i)>=MAXSPRITES || sprite[p->i].extra<=0
        || unsigned(body.sector)>=unsigned(numsectors)) return false;
#ifdef SPLITSCREEN_MOD_HACKS
    if (g_fakeMultiMode) return false;
#endif
    sample.pose=input.gripPose;
    uint32_t const buttons=input.buttons & input.activeButtons;
    sample.state=(buttons & eduke_xr::ButtonSelect) ? 2 : (buttons & eduke_xr::ButtonGrip) ? 1 : 0;
    // These authored poses name the extended ready index "trigger" and the
    // curled firing index "grip". Bind geometry, not an inferred naming rule.
    char const *const frames[]={"rest","trigger","grip"};
    sample.context.instance=hand+1;
    sample.context.modelid=md_tilehasmodel(tile,0);
    sample.context.skinnum=tile2model[Ptile2tile(tile,0)].skinnum;
    sample.context.shade=min<int32_t>(sprite[p->i].shade,24);
    sample.context.cframe=sample.context.nframe=md3_getframeindex(sample.context.modelid,frames[sample.state]);
    if (sample.context.cframe<0 || !md3_gettagposition(sample.context.modelid,"tag_palm",&sample.pivot)) return false;
    sample.context.modelToEye[0]=sample.context.modelToEye[5]=sample.context.modelToEye[10]=sample.context.modelToEye[15]=1.f;
    if (!md3_preflightcontext(&sample.context)) return false;

    // Use exactly the frozen interpolated body used for the eyes, never the
    // simulation shot sample or the camera left behind by a native callback.
    auto const tracking=multiply(pitchRoll(nativePitch(body.horizon),body.roll),inverseYaw);
    float const yaw=fix16_to_float(body.angle)*Pi/1024.f, co=std::cos(yaw), si=std::sin(yaw);
    auto const toBuild=[&](XrVector3f v) {
        return XrVector3f{(-v.z*co-v.x*si)*UnitsPerMetre,(-v.z*si+v.x*co)*UnitsPerMetre,-v.y*ZUnitsPerMetre};
    };
    auto const delta=toBuild(rotate(tracking,{sample.pose.position.x-origin.x,
                                            sample.pose.position.y-origin.y,sample.pose.position.z-origin.z}));
    double const offsets[]={delta.x,delta.y,delta.z};
    int32_t const anchor[]={body.pos.x,body.pos.y,body.pos.z};
    int32_t *const root[]={&sample.root.x,&sample.root.y,&sample.root.z};
    for (unsigned axis=0;axis<3;++axis)
    {
        double const value=anchor[axis]+std::round(offsets[axis]);
        if (!std::isfinite(value) || value<INT32_MIN || value>INT32_MAX) return false;
        *root[axis]=int32_t(value);
    }
    auto const &visual=crosshairViews.weapon;
    if (visual.selected && visual.hand==int(hand))
    {
        if (!visual.valid || visual.family!=effectiveWeaponFamily()) return false;
        // One collision translation for the gun and its holding hand. Validate
        // the translated palm below; independent clamping would break contact.
        int32_t const correction[]={visual.correction.x,visual.correction.y,visual.correction.z};
        for (unsigned axis=0;axis<3;++axis)
        {
            int64_t const value=int64_t(*root[axis])+correction[axis];
            if (value<INT32_MIN || value>INT32_MAX) return false;
            *root[axis]=int32_t(value);
        }
    }
    sample.sector=body.sector;
    updatesectorz(sample.root.x,sample.root.y,sample.root.z,&sample.sector);
    if (sample.sector<0 || !cansee(body.pos.x,body.pos.y,body.pos.z,body.sector,
        sample.root.x,sample.root.y,sample.root.z,sample.sector)) return false;

    // Canonical MD3 +X fingers, +Y right, +Z dorsal. OpenXR core grip +X
    // points away from the left palm/into the right; -Z is little→index.
    // tag_palm→core grip is approximate across controllers (not grip_surface).
    float const side=hand ? 1.f : -1.f;
    XrVector3f const axes[3]={{0,-1,0},{0,0,-side},{side,0,0}};
    auto const orientation=multiply(tracking,sample.pose.orientation);
    for (unsigned axis=0;axis<3;++axis)
    {
        auto const v=toBuild(rotate(orientation,axes[axis]));
        sample.basis[axis]={v.x/64.f,v.y/64.f,v.z/64.f};
    }
    return true;
}

// Local first-person body (torso/legs, no head or arms) under the tracked
// head. Presentation only: the native player sprite and collision are unchanged.
static int bodyModelTile()
{
    auto value=sdlayer_xr_option("EDUKE32_XR_BODY_TILE");
    int const tile=value ? std::atoi(value) : -1;
    if (tile<=0 || tile>=MAXTILES) return -1;
    // The dedicated torso/legs shell (no head or arms to hide) when the asset pack has it.
    constexpr int BodyShellTile=30066;
    return md_tilehasmodel(BodyShellTile,0)>=0 ? BodyShellTile : tile;
}

bool prepareBodyModel(BodyModelSample &sample, Camera const &body, eduke_xr::Runtime *runtime)
{
    static float bodyYaw, stride;
    static vec3_t lastPos;
    static bool yawValid;
    int const tile=bodyModelTile();
    auto const p=g_player[myconnectindex].ps;
    if (tile<0 || !G_XRModelsEnabled() || !overlayEnabled() || !recentered || !inputValid()
        || inputRuntime!=runtime || inputGeneration!=runtime->generation()
        || !rawInput.headValid || !validPose(rawInput.headPose)
        || screenpeek!=myconnectindex || ud.recstat || ud.overhead_on || ud.camerasprite>=0
        || !(p->gm & MODE_GAME) || (p->gm & MODE_MENU) || p->newowner>=0 || p->over_shoulder_on
        || p->dead_flag || unsigned(p->i)>=MAXSPRITES || sprite[p->i].extra<=0
        || unsigned(body.sector)>=unsigned(numsectors) || md_tilehasmodel(tile,0)<0)
    { yawValid=false; return false; }
    sample.context.instance=3;
    sample.context.modelid=md_tilehasmodel(tile,0);
    sample.context.skinnum=tile2model[Ptile2tile(tile,0)].skinnum;
    sample.context.shade=min<int32_t>(sprite[p->i].shade,24);
    vec3f_t neck{};
    if (!md3_gettagposition(sample.context.modelid,"tag_neck",&neck)) return false;

    // Head yaw relative to the body camera; the torso follows with a 45 degree
    // deadzone, and lines up with the head while moving.
    auto const headForward=rotate(multiply(inverseYaw,rawInput.headPose.orientation),{0,0,-1});
    if (std::hypot(headForward.x,headForward.z)<1e-3f) return false;
    float const headYaw=std::atan2(headForward.x,-headForward.z);
    float const moved=std::hypot(float(p->pos.x-lastPos.x),float(p->pos.y-lastPos.y));
    lastPos=p->pos;
    if (!yawValid) { bodyYaw=headYaw; stride=0.f; yawValid=true; }
    float const lag=wrapRadians(headYaw-bodyYaw), limit=Pi/4.f;
    if (lag>limit) bodyYaw=headYaw-limit; else if (lag<-limit) bodyYaw=headYaw+limit;
    if (moved>1.f) bodyYaw+=wrapRadians(headYaw-bodyYaw)*.2f;

    // Feet on the player's floor, neck kept below the eyes.
    auto const tracking=multiply(pitchRoll(nativePitch(body.horizon),body.roll),inverseYaw);
    float const yaw=fix16_to_float(body.angle)*Pi/1024.f, co=std::cos(yaw), si=std::sin(yaw);
    auto const toBuild=[&](XrVector3f v) {
        return XrVector3f{(-v.z*co-v.x*si)*UnitsPerMetre,(-v.z*si+v.x*co)*UnitsPerMetre,-v.y*ZUnitsPerMetre};
    };
    auto const head=toBuild(rotate(tracking,{rawInput.headPose.position.x-origin.x,
                                           rawInput.headPose.position.y-origin.y,rawInput.headPose.position.z-origin.z}));
    float const facing=yaw+bodyYaw;
    float const fx=std::cos(facing), fy=std::sin(facing);
    float const eyeX=body.pos.x+head.x, eyeY=body.pos.y+head.y, eyeZ=body.pos.z+head.z;
    float const feetZ=float(sprite[p->i].z);
    float const eyeHeight=(feetZ-eyeZ)/ZUnitsPerMetre;
    bool const airborne=!p->on_ground && p->jumping_counter;
    bool const crouched=!airborne && eyeHeight<1.15f;
    float const speed=moved/UnitsPerMetre; // metres this frame
    stride+=moved/(1.4f*UnitsPerMetre);
    stride-=std::floor(stride);
    // Frames of the shared third-person Duke model (4-step cycles), falling
    // back to a dedicated body's 8-step names, then the rest pose.
    int const step=1+int(stride*4.f)%4;
    char name[24];
    int frame=-1;
    auto const tryFrame=[&](char const *format,int index) {
        if (frame>=0) return;
        Bsnprintf(name,sizeof(name),format,index);
        frame=md3_getframeindex(sample.context.modelid,name);
    };
    if (airborne) { tryFrame(p->vel.z>0 ? "fall" : "jump",0); tryFrame("jump",0); }
    else if (crouched) { if (moved>1.f) tryFrame("crouch_walk_%02d",step); tryFrame("crouch",0); }
    else if (moved>1.f)
    {
        if (speed>.08f) tryFrame("run_%02d",step);
        tryFrame("walk_%02d",step);
        tryFrame("walk_%02d",1+int(stride*8.f)%8);
    }
    tryFrame("stand",0);
    tryFrame("rest",0);
    if (frame<0) frame=0;
    // First person never draws Duke's own head or arms (floating hands do).
    sample.context.hiddenSurfaces=0;
    for (char const *hidden:{"head","arm_left","arm_right"})
    {
        int const surface=md3_getsurfaceindex(sample.context.modelid,hidden);
        if (surface>=0 && surface<32) sample.context.hiddenSurfaces|=1u<<surface;
    }
    sample.context.cframe=sample.context.nframe=frame;
    sample.context.modelToEye[0]=sample.context.modelToEye[5]=sample.context.modelToEye[10]=sample.context.modelToEye[15]=1.f;
    if (!md3_preflightcontext(&sample.context)) return false;

    // The neck sits behind and well below the eyes so looking down shows the
    // chest, belt and legs rather than the inside of the shoulders.
    constexpr float NeckBehind=.24f, NeckBelow=.32f;
    float const neckMetres=neck.z/64.f;
    float const sink=std::max(0.f,neckMetres-(eyeHeight-NeckBelow));
    sample.root={int32_t(std::lround(eyeX-fx*NeckBehind*UnitsPerMetre)),int32_t(std::lround(eyeY-fy*NeckBehind*UnitsPerMetre)),
                 int32_t(std::lround(feetZ+sink*ZUnitsPerMetre))};
    sample.pivot={0,0,0};
    sample.sector=body.sector;
    updatesector(sample.root.x,sample.root.y,&sample.sector);
    if (sample.sector<0) sample.sector=body.sector;
    float const scale=UnitsPerMetre/64.f;
    sample.basis[0]={fx*scale,fy*scale,0};
    sample.basis[1]={-fy*scale,fx*scale,0};
    sample.basis[2]={0,0,-ZUnitsPerMetre/64.f};
    return true;
}

// Segmented finger-tracking hands (EDUKE32_XR_HAND_RIG, written by the
// launcher from the asset's hand_poses_flat.json):
//   segment <side> <tile> <joint>            one rigid MD3 per bone segment
//   pose <side> <name> <frame>               frame 0 = controller grip, 1 = weapon model
//     followed by 26 lines "px py pz qx qy qz qw" (metres, XR_EXT_hand_tracking order)
//   hold <weaponModelTile> <poseName>        pose used while holding that model
struct HandRigPose { bool weaponFrame=false; std::array<XrPosef,eduke_xr::HandInput::JointCount> joints{}; };
struct HandRig
{
    struct Segment { int tile, joint; };
    std::array<std::vector<Segment>,2> segments;
    std::array<std::vector<std::pair<std::string,HandRigPose>>,2> poses;
    std::vector<std::pair<int,std::string>> holds;
    // Single-shell hand: one skinned MD3 per side; each vertex follows up to two joints, its
    // position given in each joint's local frame (the segment MD3 frames, model units).
    struct ShellVertex { uint8_t joint[2]; float weight; XrVector3f local[2]; };
    std::array<int,2> shellTile{{-1,-1}};
    std::array<std::vector<ShellVertex>,2> shell;
    // Wrist-cut shells (no forearm) used when the full IK body supplies the arms.
    std::array<int,2> wristShellTile{{-1,-1}};
    std::array<std::vector<ShellVertex>,2> wristShell;
    // Per-character hands (Alien Armageddon pchar 1..7).
    std::array<std::array<int,2>,8> charShellTile{};
    std::array<std::array<std::vector<ShellVertex>,2>,8> charShell;
    // Full IK body (vr_duke_ik): skeleton in model space and a skin of up to four bones per vertex.
    struct IkBone { std::string name; int parent; XrVector3f position; XrQuaternionf rotation; };
    struct IkVertex { uint8_t count; uint8_t bone[4]; float weight[4]; XrVector3f local[4]; };
    struct IkBody
    {
        int tile=-1;
        std::vector<IkBone> bones;
        std::vector<IkVertex> vertices;
        std::vector<uint8_t> hide;   // 1 head, 2 left hand, 4 right hand
        // Eyes relative to the head bone in the bind pose (model units, +X forward, +Z up).
        float eyeForward=.09f*64.f, eyeUp=.06f*64.f;
        int find(char const *name) const
        {
            for (size_t i=0;i<bones.size();++i) if (bones[i].name==name) return int(i);
            return -1;
        }
    } ik;
    HandRigPose const *pose(unsigned side,char const *name) const
    {
        for (auto const &p:poses[side]) if (p.first==name) return &p.second;
        return nullptr;
    }
};
static HandRig const *handRig()
{
    static bool loaded;
    static HandRig rig;
    static bool usable;
    if (loaded) return usable ? &rig : nullptr;
    loaded=true;
    for (auto &tiles:rig.charShellTile) tiles={{-1,-1}};
    auto path=sdlayer_xr_option("EDUKE32_XR_HAND_RIG");
    FILE *file=path ? std::fopen(path,"r") : nullptr;
    if (!file) return nullptr;
    char word[64], name[128];
    while (std::fscanf(file,"%63s",word)==1)
    {
        if (!Bstrcmp(word,"segment"))
        {
            int side,tile,joint;
            if (std::fscanf(file,"%d %d %d",&side,&tile,&joint)==3 && unsigned(side)<2 && unsigned(tile)<MAXTILES
                && unsigned(joint)<eduke_xr::HandInput::JointCount)
                rig.segments[side].push_back({tile,joint});
        }
        else if (!Bstrcmp(word,"pose"))
        {
            int side,frame;
            HandRigPose pose;
            if (std::fscanf(file,"%d %127s %d",&side,name,&frame)!=3 || unsigned(side)>=2) break;
            pose.weaponFrame=frame==1;
            bool good=true;
            for (auto &joint:pose.joints)
                good=good && std::fscanf(file,"%f %f %f %f %f %f %f",&joint.position.x,&joint.position.y,&joint.position.z,
                                         &joint.orientation.x,&joint.orientation.y,&joint.orientation.z,&joint.orientation.w)==7;
            if (!good) break;
            rig.poses[side].emplace_back(name,pose);
        }
        else if (!Bstrcmp(word,"hold"))
        {
            int tile;
            if (std::fscanf(file,"%d %127s",&tile,name)==2) rig.holds.emplace_back(tile,name);
        }
        else if (!Bstrcmp(word,"shell") || !Bstrcmp(word,"shellwrist") || !Bstrcmp(word,"charshell"))
        {
            // shell <side> <tile> <skin file>: "skin 1 <n>" then n lines "j0 w0 x0 y0 z0 j1 x1 y1 z1".
            // charshell <pchar> <side> <tile> <skin file>
            int side,tile,character=0;
            char skinPath[1024];
            if (!Bstrcmp(word,"charshell") && (std::fscanf(file,"%d",&character)!=1 || character<=0 || character>=8)) break;
            if (std::fscanf(file,"%d %d %1023s",&side,&tile,skinPath)!=3 || unsigned(side)>=2 || unsigned(tile)>=MAXTILES) break;
            std::vector<HandRig::ShellVertex> vertices;
            if (FILE *skin=std::fopen(skinPath,"r"))
            {
                int version=0, count=0;
                if (std::fscanf(skin,"skin %d %d",&version,&count)==2 && version==1 && count>0 && count<=4096)
                {
                    vertices.resize(count);
                    for (auto &v:vertices)
                    {
                        int j0,j1;
                        if (std::fscanf(skin,"%d %f %f %f %f %d %f %f %f",&j0,&v.weight,&v.local[0].x,&v.local[0].y,&v.local[0].z,
                                        &j1,&v.local[1].x,&v.local[1].y,&v.local[1].z)!=9
                            || unsigned(j0)>=eduke_xr::HandInput::JointCount || unsigned(j1)>=eduke_xr::HandInput::JointCount
                            || !(v.weight>=0.f && v.weight<=1.f)) { vertices.clear(); break; }
                        v.joint[0]=uint8_t(j0); v.joint[1]=uint8_t(j1);
                    }
                }
                std::fclose(skin);
            }
            if (!vertices.empty())
            {
                if (character) { rig.charShellTile[character][side]=tile; rig.charShell[character][side]=std::move(vertices); }
                else if (!Bstrcmp(word,"shellwrist")) { rig.wristShellTile[side]=tile; rig.wristShell[side]=std::move(vertices); }
                else { rig.shellTile[side]=tile; rig.shell[side]=std::move(vertices); }
            }
            else LOG_F(WARNING,"OpenXR hand rig: unreadable shell skin %s.",skinPath);
        }
        else if (!Bstrcmp(word,"ikbody"))
        {
            // ikbody <tile> <skel> <skin> <headverts> <handverts_l> <handverts_r>
            int tile;
            char paths[5][1024];
            if (std::fscanf(file,"%d %1023s %1023s %1023s %1023s %1023s",&tile,paths[0],paths[1],paths[2],paths[3],paths[4])!=6) break;
            HandRig::IkBody ik;
            bool good=unsigned(tile)<MAXTILES;
            if (FILE *skel=good ? std::fopen(paths[0],"r") : nullptr)
            {
                int version=0, count=0;
                good=std::fscanf(skel,"skel %d %d",&version,&count)==2 && version==1 && count>0 && count<256;
                for (int i=0;good && i<count;++i)
                {
                    char bone[64]; HandRig::IkBone b;
                    good=std::fscanf(skel,"%63s %d %f %f %f %f %f %f %f",bone,&b.parent,&b.position.x,&b.position.y,&b.position.z,
                                     &b.rotation.x,&b.rotation.y,&b.rotation.z,&b.rotation.w)==9 && b.parent<i;
                    b.name=bone; ik.bones.push_back(b);
                }
                std::fclose(skel);
            }
            else good=false;
            if (FILE *skin=good ? std::fopen(paths[1],"r") : nullptr)
            {
                int version=0, count=0;
                good=std::fscanf(skin,"skin %d %d",&version,&count)==2 && version==2 && count>0 && count<=4096;
                if (good) ik.vertices.resize(count);
                for (auto &v:ik.vertices)
                {
                    int k=0;
                    if (!good || std::fscanf(skin,"%d",&k)!=1 || k<1 || k>4) { good=false; break; }
                    v.count=uint8_t(k);
                    for (int j=0;j<k && good;++j)
                    {
                        int bone;
                        good=std::fscanf(skin,"%d %f %f %f %f",&bone,&v.weight[j],&v.local[j].x,&v.local[j].y,&v.local[j].z)==5
                            && unsigned(bone)<ik.bones.size();
                        v.bone[j]=uint8_t(bone);
                    }
                }
                std::fclose(skin);
            }
            else good=false;
            if (good)
            {
                ik.hide.assign(ik.vertices.size(),0);
                for (int list=0;list<3;++list)
                    if (FILE *f=std::fopen(paths[2+list],"r"))
                    {
                        int index;
                        while (std::fscanf(f,"%d",&index)==1)
                            if (unsigned(index)<ik.hide.size()) ik.hide[index]|=uint8_t(1<<list);
                        std::fclose(f);
                    }
                for (char const *name:{"pelvis","spine","chest","neck","head","upperarm_l","forearm_l","hand_l",
                                        "upperarm_r","forearm_r","hand_r","thigh_l","calf_l","foot_l","thigh_r","calf_r","foot_r"})
                    good=good && ik.find(name)>=0;
                // Eyes from the hidden head's bind shape: 2 cm behind the face, 11.5 cm below the crown.
                float front=-FLT_MAX, crown=-FLT_MAX;
                for (size_t i=0;good && i<ik.vertices.size();++i)
                {
                    if (!(ik.hide[i]&1)) continue;
                    auto const &v=ik.vertices[i];
                    XrVector3f bindPos{0,0,0};
                    for (unsigned j=0;j<v.count;++j)
                    {
                        auto const &b=ik.bones[v.bone[j]];
                        auto const r=rotate(b.rotation,v.local[j]);
                        bindPos.x+=v.weight[j]*(b.position.x+r.x); bindPos.z+=v.weight[j]*(b.position.z+r.z);
                    }
                    front=std::max(front,bindPos.x); crown=std::max(crown,bindPos.z);
                }
                if (good && front>-FLT_MAX)
                {
                    auto const &head=ik.bones[ik.find("head")].position;
                    float const forward=front-.02f*64.f-head.x, up=crown-.115f*64.f-head.z;
                    if (forward>0.f && forward<.2f*64.f && up>-.05f*64.f && up<.25f*64.f) ik.eyeForward=forward, ik.eyeUp=up;
                }
            }
            if (good) { ik.tile=tile; rig.ik=std::move(ik); }
            else LOG_F(WARNING,"OpenXR hand rig: unusable IK body %s / %s.",paths[0],paths[1]);
        }
        else break;
    }
    std::fclose(file);
    usable=!rig.segments[0].empty() || !rig.segments[1].empty();
    LOG_F(INFO,"OpenXR hand rig: %zu+%zu segments, %zu+%zu poses, %zu holds, shells %zu+%zu vertices, IK body %zu bones %zu vertices.",
          rig.segments[0].size(),rig.segments[1].size(),rig.poses[0].size(),rig.poses[1].size(),rig.holds.size(),
          rig.shell[0].size(),rig.shell[1].size(),rig.ik.bones.size(),rig.ik.vertices.size());
    return usable ? &rig : nullptr;
}

struct HandSegmentSample : WorldModelSample {};

// Joint transforms of each hand from this frame's prepareHandSegments (Build space): the full
// IK body reaches its arms to the same wrist the floating hand is drawn at.
static struct HandJointCache
{
    bool valid=false;
    std::array<vec3_t,eduke_xr::HandInput::JointCount> roots{};
    std::array<std::array<XrVector3f,3>,eduke_xr::HandInput::JointCount> bases{};
} handJoints[2];
static bool fullBodyFrame;   // the IK body draws the arms this frame (wrist-cut hand shells)
// Alien Armageddon's playable character (gamevar pchar; 0 Duke). Other mods: always Duke.
static int playerCharacter()
{
    static int const missing=INT32_MIN;
    int const value=Gv_GetVarByLabel("pchar",missing,g_player[myconnectindex].ps->i,myconnectindex);
    return value==missing ? 0 : value;
}

// Tracking-space vectors to Build for this frame's body camera (directions keep metres, z up).
struct TrackingToBuild
{
    XrQuaternionf tracking;
    float co, si;
    explicit TrackingToBuild(Camera const &body)
        : tracking(multiply(pitchRoll(nativePitch(body.horizon),body.roll),inverseYaw)),
          co(std::cos(fix16_to_float(body.angle)*Pi/1024.f)), si(std::sin(fix16_to_float(body.angle)*Pi/1024.f)) {}
    XrVector3f offset(XrVector3f v) const   // Build units (z down)
    {
        v=rotate(tracking,v);
        return {(-v.z*co-v.x*si)*UnitsPerMetre,(-v.z*si+v.x*co)*UnitsPerMetre,-v.y*ZUnitsPerMetre};
    }
    XrVector3f direction(XrVector3f v) const   // isotropic, z up
    {
        v=rotate(tracking,v);
        return {-v.z*co-v.x*si,-v.z*si+v.x*co,v.y};
    }
};

using HandRoots=std::array<vec3_t,eduke_xr::HandInput::JointCount>;
using HandBases=std::array<std::array<XrVector3f,3>,eduke_xr::HandInput::JointCount>;
using HandJoints=std::array<XrPosef,eduke_xr::HandInput::JointCount>;

// A hand pose's frame in Build space: a joint at p metres sits at root + axes*p (axes are Build units
// per metre): the controller grip for named poses, the held model (pivot applied) for holds.
struct HandFrame { float root[3]{}; XrVector3f axes[3]{}; };

// What this frame's hands showed, for other players' views (VRBodyPose).
static struct HandWire { uint8_t kind=VRHandNone; float pull=0.f; HandFrame frame; } handWire[2];

// Trigger pull: the index finger curls a little at each joint (pull 0..1). Rotations act in the
// hold's right-handed W frame (W = MD3 +Y, +Z, -X) about each joint's own flexion (+X) axis.
static void curlIndexFinger(HandJoints &joints, float pull)
{
    if (!(pull>0.f)) return;
    auto const toW=[](XrVector3f m) { return XrVector3f{m.y,m.z,-m.x}; };
    auto const toM=[](XrVector3f w) { return XrVector3f{-w.z,w.x,w.y}; };
    // Joint indices in XR_HAND_JOINT order: index proximal 7, intermediate 8, distal 9, tip 10.
    static constexpr unsigned chain[]={7,8,9,10};
    static constexpr float degrees[]={8.f,16.f,12.f};
    for (unsigned link=0;link<3;++link)
    {
        auto const &pivot=joints[chain[link]];
        auto const axis=rotate(pivot.orientation,{1,0,0});
        float const half=-degrees[link]*pull*Pi/360.f, sh=std::sin(half);
        XrQuaternionf const turn={axis.x*sh,axis.y*sh,axis.z*sh,std::cos(half)};
        auto const origin=toW(pivot.position);
        for (unsigned k=link;k<4;++k)
        {
            auto &j=joints[chain[k]];
            if (k>link)
            {
                auto const w=toW(j.position);
                auto const r=rotate(turn,{w.x-origin.x,w.y-origin.y,w.z-origin.z});
                j.position=toM({origin.x+r.x,origin.y+r.y,origin.z+r.z});
            }
            j.orientation=multiply(turn,j.orientation);
        }
    }
}

// Joint roots and axes (Build units per model unit) of a pose placed in its frame. Weapon-frame
// (hold) rotations use the weapon's right-handed aim frame W=(MD3 +Y, MD3 +Z, MD3 -X).
static void placeHandJoints(HandJoints const &joints, bool weaponFrame, HandFrame const &frame, HandRoots &roots, HandBases &bases)
{
    XrVector3f const axes[3]={{1,0,0},{0,1,0},{0,0,1}};
    for (unsigned joint=0;joint<eduke_xr::HandInput::JointCount;++joint)
    {
        auto const &j=joints[joint];
        float const m[3]={j.position.x,j.position.y,j.position.z};
        float pos[3]={frame.root[0],frame.root[1],frame.root[2]};
        for (unsigned k=0;k<3;++k)
        { pos[0]+=frame.axes[k].x*m[k]; pos[1]+=frame.axes[k].y*m[k]; pos[2]+=frame.axes[k].z*m[k]; }
        roots[joint]={int32_t(std::lround(pos[0])),int32_t(std::lround(pos[1])),int32_t(std::lround(pos[2]))};
        for (unsigned axis=0;axis<3;++axis)
        {
            auto const r=rotate(j.orientation,axes[axis]);
            float const c[3]={weaponFrame ? -r.z : r.x,weaponFrame ? r.x : r.y,weaponFrame ? r.y : r.z};
            XrVector3f b{};
            for (unsigned k=0;k<3;++k)
            { b.x+=frame.axes[k].x*c[k]/64.f; b.y+=frame.axes[k].y*c[k]/64.f; b.z+=frame.axes[k].z*c[k]/64.f; }
            bases[joint][axis]=b;
        }
    }
}

// One continuous skinned hand shell, as Build offsets from the wrist.
static bool skinHandShell(HandSegmentSample &sample, std::vector<vec3f_t> &vertices, std::vector<HandRig::ShellVertex> const &skin,
                          int shellTile, HandRoots const &roots, HandBases const &bases, int32_t shade, int instance, int16_t sector)
{
    int const shellModel=shellTile>=0 ? md_tilehasmodel(shellTile,0) : -1;
    if (shellModel<0 || skin.empty()) return false;
    vertices.resize(skin.size());
    vec3_t const anchor=roots[1];   // wrist
    for (size_t i=0;i<skin.size();++i)
    {
        auto const &v=skin[i];
        float acc[3]={0,0,0};
        for (unsigned k=0;k<2;++k)
        {
            float const w=k ? 1.f-v.weight : v.weight;
            if (w<=0.f) continue;
            unsigned const j=v.joint[k];
            auto const &l=v.local[k];
            auto const &b=bases[j];
            acc[0]+=w*(float(roots[j].x-anchor.x)+b[0].x*l.x+b[1].x*l.y+b[2].x*l.z);
            acc[1]+=w*(float(roots[j].y-anchor.y)+b[0].y*l.x+b[1].y*l.y+b[2].y*l.z);
            acc[2]+=w*(float(roots[j].z-anchor.z)+b[0].z*l.x+b[1].z*l.y+b[2].z*l.z);
        }
        vertices[i]={acc[0],acc[1],acc[2]};
    }
    sample.context.instance=instance;
    sample.context.modelid=shellModel;
    sample.context.skinnum=tile2model[Ptile2tile(shellTile,0)].skinnum;
    sample.context.shade=shade;
    sample.context.cframe=sample.context.nframe=0;
    sample.context.modelToEye[0]=sample.context.modelToEye[5]=sample.context.modelToEye[10]=sample.context.modelToEye[15]=1.f;
    sample.context.vertices=vertices.data();
    sample.context.vertexCount=int32_t(vertices.size());
    if (!md3_preflightcontext(&sample.context)) return false;
    // Vertices are already Build offsets from the wrist: identity basis.
    sample.root=anchor;
    sample.pivot={0,0,0};
    sample.basis[0]={1,0,0}; sample.basis[1]={0,1,0}; sample.basis[2]={0,0,1};
    sample.sector=sector;
    updatesector(sample.root.x,sample.root.y,&sample.sector);
    if (sample.sector<0) sample.sector=sector;
    return true;
}

static HandFrame heldModelFrame(WorldModelSample const &model)
{
    HandFrame frame;
    frame.root[0]=float(model.root.x); frame.root[1]=float(model.root.y); frame.root[2]=float(model.root.z);
    float const pivot[3]={model.pivot.x,model.pivot.y,model.pivot.z};
    for (unsigned k=0;k<3;++k)
    {
        frame.root[0]-=model.basis[k].x*pivot[k]; frame.root[1]-=model.basis[k].y*pivot[k]; frame.root[2]-=model.basis[k].z*pivot[k];
        frame.axes[k]={model.basis[k].x*64.f,model.basis[k].y*64.f,model.basis[k].z*64.f};
    }
    return frame;
}

// Pose one hand's segments. Joint sources in priority order: the weapon hold
// pose (fingers wrap the held model's grip), tracked XR_EXT_hand_tracking
// joints, then a controller-button pose in the grip frame.
static unsigned prepareHandSegments(std::vector<HandSegmentSample> &out, unsigned hand, Camera const &body,
                                    eduke_xr::Runtime *runtime, HandModelSample const *heldModel, int heldTile)
{
    auto const *rig=handRig();
    auto const p=g_player[myconnectindex].ps;
    auto const &input=rawInput.hands[hand];
    if (!rig || rig->segments[hand].empty() || !G_XRModelsEnabled() || !overlayEnabled() || !recentered || !inputValid()
        || inputRuntime!=runtime || inputGeneration!=runtime->generation()
        || screenpeek!=myconnectindex || ud.recstat || ud.overhead_on || ud.camerasprite>=0
        || !(p->gm & MODE_GAME) || (p->gm & MODE_MENU) || p->newowner>=0 || p->over_shoulder_on
        || p->dead_flag || unsigned(p->i)>=MAXSPRITES || sprite[p->i].extra<=0
        || unsigned(body.sector)>=unsigned(numsectors)) return 0;

    TrackingToBuild const build(body);
    XrVector3f const axes[3]={{1,0,0},{0,1,0},{0,0,1}};
    // The controller grip as a pose frame (Build root, Build units per metre).
    auto const gripFrame=[&](XrPosef const &g) {
        HandFrame frame;
        auto const d=build.offset({g.position.x-origin.x,g.position.y-origin.y,g.position.z-origin.z});
        frame.root[0]=float(body.pos.x)+d.x; frame.root[1]=float(body.pos.y)+d.y; frame.root[2]=float(body.pos.z)+d.z;
        for (unsigned axis=0;axis<3;++axis) frame.axes[axis]=build.offset(rotate(g.orientation,axes[axis]));
        return frame;
    };
    HandRoots roots;
    HandBases bases;
    auto fromLocal=[&](unsigned joint,XrPosef const &pose) {
        auto const d=build.offset({pose.position.x-origin.x,pose.position.y-origin.y,pose.position.z-origin.z});
        roots[joint]={body.pos.x+int32_t(std::lround(d.x)),body.pos.y+int32_t(std::lround(d.y)),body.pos.z+int32_t(std::lround(d.z))};
        for (unsigned axis=0;axis<3;++axis)
        {
            auto const b=build.offset(rotate(pose.orientation,axes[axis]));
            bases[joint][axis]={b.x/64.f,b.y/64.f,b.z/64.f};
        }
    };
    char const *source=nullptr;
    HandRigPose const *hold=nullptr;
    if (heldModel && heldTile>=0)
        for (auto const &h:rig->holds)
            if (h.first==heldTile) { hold=rig->pose(hand,h.second.c_str()); break; }
    auto &wire=handWire[hand];
    if (hold && hold->weaponFrame)
    {
        // While this hand's trigger is held the index finger curls (eased over ~80 ms; the trigger
        // action is digital).
        static float pull[2];
        static double last[2];
        double const now=double(timerGetNanoTicks())/double(timerGetNanoTickRate());
        float const step=last[hand]>0. ? float(std::min(now-last[hand],.1)/.08) : 1.f;
        last[hand]=now;
        float const target=(input.buttons & input.activeButtons & eduke_xr::ButtonSelect) ? 1.f : 0.f;
        pull[hand]+=std::max(-step,std::min(step,target-pull[hand]));
        auto joints=hold->joints;
        curlIndexFinger(joints,pull[hand]);
        // Weapon model frame (metres) -> model units -> Build through the held model's own transform.
        wire={VRHandHold,pull[hand],heldModelFrame(*heldModel)};
        placeHandJoints(joints,true,wire.frame,roots,bases);
        source="hold";
    }
    else if (input.jointsValid && sdlayer_xr_option("EDUKE32_XR_FINGER_TRACKING") && !Bstrcmp(sdlayer_xr_option("EDUKE32_XR_FINGER_TRACKING"),"1"))
    {
        for (unsigned joint=0;joint<eduke_xr::HandInput::JointCount;++joint) fromLocal(joint,input.joints[joint]);
        // Others see tracked fingers as the relaxed pose on the grip.
        if (input.gripValid && validPose(input.gripPose)) wire={VRHandRelaxed,0.f,gripFrame(input.gripPose)};
        source="tracked";
    }
    else
    {
        if (!input.gripValid || !validPose(input.gripPose)) return 0;
        uint32_t const buttons=input.buttons & input.activeButtons;
        bool const trigger=buttons & eduke_xr::ButtonSelect, grip=buttons & eduke_xr::ButtonGrip;
        char const *name=grip && trigger ? "fist" : grip ? "point" : trigger ? "trigger" : "relaxed";
        auto const *pose=rig->pose(hand,name);
        if (!pose) { pose=rig->pose(hand,"relaxed"); name="relaxed"; }
        if (!pose || pose->weaponFrame) return 0;
        wire={uint8_t(!Bstrcmp(name,"fist") ? VRHandFist : !Bstrcmp(name,"point") ? VRHandPoint
                      : !Bstrcmp(name,"trigger") ? VRHandTrigger : VRHandRelaxed),0.f,gripFrame(input.gripPose)};
        placeHandJoints(pose->joints,false,wire.frame,roots,bases);
        source=name;
    }
    unsigned count=0;
    handJoints[hand].valid=true;
    handJoints[hand].roots=roots;
    handJoints[hand].bases=bases;
    // One continuous skinned shell (one draw) when the rig has it; segments otherwise. With the
    // full IK body the wrist-cut variant (no forearm) meets the body's own forearm.
    bool const wristCut=fullBodyFrame && rig->wristShellTile[hand]>=0 && md_tilehasmodel(rig->wristShellTile[hand],0)>=0;
    int const character=playerCharacter();
    bool const ownHands=character>0 && character<8 && rig->charShellTile[character][hand]>=0
        && md_tilehasmodel(rig->charShellTile[character][hand],0)>=0;
    int const shellTile=ownHands ? rig->charShellTile[character][hand] : wristCut ? rig->wristShellTile[hand] : rig->shellTile[hand];
    {
        static std::vector<vec3f_t> deformed[2];
        auto const &skin=ownHands ? rig->charShell[character][hand] : wristCut ? rig->wristShell[hand] : rig->shell[hand];
        HandSegmentSample sample;
        if (skinHandShell(sample,deformed[hand],skin,shellTile,roots,bases,min<int32_t>(sprite[p->i].shade,24),16+hand*32,body.sector))
        {
            out.push_back(sample);
            if (std::getenv("EDUKE32_XR_TEST_HANDS"))
            {
                static std::string last[2];
                if (last[hand]!=source)
                    LOG_F(INFO,"OpenXR shell hand: hand=%u source=%s vertices=%zu.",hand,source,deformed[hand].size());
                last[hand]=source;
            }
            return 1;
        }
    }
    for (auto const &segment:rig->segments[hand])
    {
        int const modelid=md_tilehasmodel(segment.tile,0);
        if (modelid<0) continue;
        HandSegmentSample sample;
        sample.context.instance=16+hand*32+count;
        sample.context.modelid=modelid;
        sample.context.skinnum=tile2model[Ptile2tile(segment.tile,0)].skinnum;
        sample.context.shade=min<int32_t>(sprite[p->i].shade,24);
        sample.context.cframe=sample.context.nframe=0;
        sample.context.modelToEye[0]=sample.context.modelToEye[5]=sample.context.modelToEye[10]=sample.context.modelToEye[15]=1.f;
        if (!md3_preflightcontext(&sample.context)) continue;
        sample.root=roots[segment.joint];
        sample.pivot={0,0,0};
        for (unsigned axis=0;axis<3;++axis) sample.basis[axis]=bases[segment.joint][axis];
        sample.sector=body.sector;
        updatesector(sample.root.x,sample.root.y,&sample.sector);
        if (sample.sector<0) sample.sector=body.sector;
        out.push_back(sample);
        ++count;
    }
    if (count && std::getenv("EDUKE32_XR_TEST_HANDS"))
    {
        static std::string last[2];
        if (last[hand]!=source)
            LOG_F(INFO,"OpenXR segmented hand: hand=%u source=%s segments=%u.",hand,source,count);
        last[hand]=source;
    }
    return count;
}

// Weapon wheel models: each slot's held-weapon MD3 scaled to a common size on a ring in front of the
// hand (open-time direction), muzzle to the right in a 3/4 view. Hovered: larger, brighter, spinning;
// unavailable: smaller and dark. Same explicit model path as the held weapon and hands.
// Wheel geometry shared by the 3D parts and the 2D icon panel (tracking space, metres).
static XrVector3f wheelCentre(Wheel const &w, float frac)
{
    // Raised above the aim line so the held weapon sits below the ring instead of across it.
    static float const testDistance=[]() { auto v=std::getenv("EDUKE32_XR_TEST_WHEEL_DISTANCE"); return v ? float(std::atof(v)) : .36f; }();
    return {w.centre.x+w.forward.x*testDistance*frac+w.faceUp.x*.18f*frac,
            w.centre.y+w.forward.y*testDistance*frac+w.faceUp.y*.18f*frac,
            w.centre.z+w.forward.z*testDistance*frac+w.faceUp.z*.18f*frac};
}
static float wheelRadius(Wheel const &w, float frac) { return (w.gadgets ? .14f : .17f)*frac; }
static float wheelOpenFraction(Wheel const &w)
{
    double const now=double(timerGetNanoTicks())/double(timerGetNanoTickRate());
    return float(std::min(1.0,(now-w.openedAt)/.1));
}

constexpr int VRWheelBubbleTile=30061, VRWheelBubbleLitTile=30062, VRWheelPointerTile=30063, VRWheelBeamTile=30064;

static unsigned prepareWheel(Wheel const &w, std::vector<HandSegmentSample> &out, Camera const &body, eduke_xr::Runtime *runtime)
{
    auto const p=g_player[myconnectindex].ps;
    if (!w.open || !w.count || !G_XRModelsEnabled() || !overlayEnabled() || !recentered || !inputValid()
        || inputRuntime!=runtime || inputGeneration!=runtime->generation() || unsigned(body.sector)>=unsigned(numsectors))
    {
        if (w.open && wheelLog())
            LOG_F(INFO,"OpenXR wheel: no models usemodels=%d overlay=%d recentered=%d input=%d runtime=%d.",usemodels,
                  overlayEnabled(),recentered,inputValid(),inputRuntime==runtime);
        return 0;
    }
    double const now=double(timerGetNanoTicks())/double(timerGetNanoTickRate());
    float const frac=wheelOpenFraction(w);
    auto const tracking=multiply(pitchRoll(nativePitch(body.horizon),body.roll),inverseYaw);
    float const yaw=fix16_to_float(body.angle)*Pi/1024.f, co=std::cos(yaw), si=std::sin(yaw);
    auto const toBuild=[&](XrVector3f v) {
        return XrVector3f{(-v.z*co-v.x*si)*UnitsPerMetre,(-v.z*si+v.x*co)*UnitsPerMetre,-v.y*ZUnitsPerMetre};
    };
    auto const add=[](XrVector3f a, XrVector3f b, float k) { return XrVector3f{a.x+b.x*k,a.y+b.y*k,a.z+b.z*k}; };
    auto const cross=[](XrVector3f a, XrVector3f b) { return XrVector3f{a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x}; };
    XrVector3f const centre=wheelCentre(w,frac);
    float const radius=wheelRadius(w,frac);
    int const instanceBase=w.gadgets ? 144 : 128;
    unsigned count=0;
    // One MD3 at a tracking-space position with axes (unit vectors) scaled to Build per model unit.
    auto const place=[&](int tile, int instance, int shade, XrVector3f position, XrVector3f const (&axes)[3], float scale,
                         vec3f_t pivot) {
        int const modelid=md_tilehasmodel(tile,0);
        if (modelid<0) return false;
        HandSegmentSample sample;
        sample.context.instance=instance;
        sample.context.modelid=modelid;
        sample.context.skinnum=tile2model[Ptile2tile(tile,0)].skinnum;
        sample.context.shade=shade;
        sample.context.cframe=sample.context.nframe=0;
        sample.context.modelToEye[0]=sample.context.modelToEye[5]=sample.context.modelToEye[10]=sample.context.modelToEye[15]=1.f;
        if (!md3_preflightcontext(&sample.context)) return false;
        auto const d=toBuild(rotate(tracking,{position.x-origin.x,position.y-origin.y,position.z-origin.z}));
        sample.root={body.pos.x+int32_t(std::lround(d.x)),body.pos.y+int32_t(std::lround(d.y)),body.pos.z+int32_t(std::lround(d.z))};
        sample.pivot=pivot;
        for (unsigned axis=0;axis<3;++axis)
        {
            auto const b=toBuild(rotate(tracking,axes[axis]));
            sample.basis[axis]={b.x*scale,b.y*scale,b.z*scale};
        }
        sample.sector=body.sector;
        updatesector(sample.root.x,sample.root.y,&sample.sector);
        if (sample.sector<0) sample.sector=body.sector;
        out.push_back(sample);
        ++count;
        return true;
    };
    XrVector3f const faceAxes[3]={w.faceBack,w.faceRight,w.faceUp};   // bubble disc faces +X
    bool const weaponModels=!w.gadgets && wheelUses3D();
    for (unsigned slot=0;slot<w.count;++slot)
    {
        bool const selectable=slotSelectable(w,p,int(slot)), hovered=int(slot)==w.hovered;
        float const angle=2*Pi*slot/w.count;
        XrVector3f const position=add(add(centre,w.faceRight,radius*std::sin(angle)),w.faceUp,radius*std::cos(angle));
        // Bubble behind the slot: lit and larger when hovered, dark when unavailable.
        float const bubble=(w.gadgets ? .055f : .046f)*(hovered ? 1.2f : 1.f)*frac;
        place(hovered ? VRWheelBubbleLitTile : VRWheelBubbleTile,instanceBase+int(slot),hovered ? -16 : selectable ? 0 : 26,
              add(position,w.faceBack,-.035f),faceAxes,bubble/32.f,{0,0,0});
        if (!weaponModels) continue;
        int const weapon=w.slots[slot];
        int const tile=wheelModelTile(p,weapon);
        int const modelid=md_tilehasmodel(tile,0);
        vec3f_t lo, hi;
        if (modelid<0 || !md3_getframebounds(modelid,0,&lo,&hi)) continue;
        lo={lo.x/64.f,lo.y/64.f,lo.z/64.f}; hi={hi.x/64.f,hi.y/64.f,hi.z/64.f};   // raw vertex units -> model units
        float const size=std::max({hi.x-lo.x,hi.y-lo.y,hi.z-lo.z,1.f});
        static float const testScale=[]() { auto v=std::getenv("EDUKE32_XR_TEST_WHEEL_SCALE"); return v ? float(std::atof(v)) : 1.f; }();
        // Long guns display longer than pistols so they don't shrink to slivers (real length in metres).
        float const length=size/64.f;
        float const shown=std::min(.20f,std::max(.11f,.11f+.11f*(length-.25f)));
        float const metres=shown*(hovered ? 1.25f : selectable ? 1.f : .75f)*frac*testScale;
        // Muzzle to the right, turned 30 degrees away (3/4 view); the hovered weapon spins.
        float const turn=-30.f*Pi/180.f+(hovered ? float(std::fmod(now-w.openedAt,4.0))*Pi*.5f : 0.f);
        XrVector3f const xAxis=add(XrVector3f{w.faceRight.x*std::cos(turn),w.faceRight.y*std::cos(turn),w.faceRight.z*std::cos(turn)},
                                   w.faceBack,-std::sin(turn));
        XrVector3f const zAxis=w.faceUp, yAxis=cross(xAxis,zAxis);
        XrVector3f const axes[3]={xAxis,yAxis,zAxis};
        place(tile,96+int(slot),hovered ? -24 : selectable ? -8 : 24,position,axes,metres/size,
              {(lo.x+hi.x)*.5f,(lo.y+hi.y)*.5f,(lo.z+hi.z)*.5f});
    }
    // Pointer bead on the ring plane and the beam to it from the hand.
    XrVector3f const bead=add(add(add(centre,w.faceRight,radius*w.pointerX),w.faceUp,radius*w.pointerY),w.faceBack,.01f);
    place(VRWheelPointerTile,160+int(w.gadgets),-32,bead,faceAxes,.011f/32.f,{0,0,0});
    auto const &aim=rawInput.hands[w.hand].aimPose;
    if (rawInput.hands[w.hand].aimValid && validPose(aim))
    {
        XrVector3f const d={bead.x-aim.position.x,bead.y-aim.position.y,bead.z-aim.position.z};
        float const length=std::sqrt(dot(d,d));
        if (length>.02f)
        {
            XrVector3f const f={d.x/length,d.y/length,d.z/length};
            XrVector3f side=std::fabs(f.y)<.95f ? cross(f,XrVector3f{0,1,0}) : XrVector3f{1,0,0};
            float const sl=std::sqrt(dot(side,side));
            side={side.x/sl,side.y/sl,side.z/sl};
            XrVector3f const up=cross(side,f);
            XrVector3f const axes[3]={f,side,up};
            // The beam MD3 is 64 units long: stretch X to the distance, keep its thickness.
            int const modelid=md_tilehasmodel(VRWheelBeamTile,0);
            if (modelid>=0 && place(VRWheelBeamTile,162+int(w.gadgets),-32,aim.position,axes,1.f/64.f,{0,0,0}))
            {
                auto &beam=out.back();
                beam.basis[0]={beam.basis[0].x*length,beam.basis[0].y*length,beam.basis[0].z*length};
            }
        }
    }
    if (wheelLog())
    {
        static double lastLog;
        if (now-lastLog>1.0)
        {
            lastLog=now;
            LOG_F(INFO,"OpenXR %s wheel: parts=%u slots=%u pointer=%.2f,%.2f.",w.gadgets ? "gadget" : "weapon",count,w.count,w.pointerX,w.pointerY);
        }
    }
    return count;
}

// Aiming laser (vr_laser): the vr_laser MD3 (1 m along +X) stretched from the shot origin (the held
// model's muzzle, else the resolved hand origin) to where the native aim ray hits.
static bool prepareLaser(HandSegmentSample &sample, Camera const &body, eduke_xr::Runtime *runtime)
{
    auto const p=g_player[myconnectindex].ps;
    int const modelid=md_tilehasmodel(VRLaserTile,0);
    if (!vr_laser || modelid<0 || wheel.open || aimHand()<0 || !handShotsRequested() || !localAimCamera() || !aimPoseUsable()
        || !recentered || !inputValid() || inputRuntime!=runtime || inputGeneration!=runtime->generation()
        || screenpeek!=myconnectindex || ud.recstat || ud.overhead_on || ud.camerasprite>=0
        || !(p->gm & MODE_GAME) || (p->gm & MODE_MENU) || p->newowner>=0 || p->over_shoulder_on || p->dead_flag
        || unsigned(p->i)>=MAXSPRITES || sprite[p->i].extra<=0 || unsigned(body.sector)>=unsigned(numsectors)) return false;
    vec3_t start; int16_t sector; bool clamped=false; vec3_t ray;
    auto const &visual=crosshairViews.weapon;
    if (visual.selected && visual.valid)
    {
        start=visual.root; sector=visual.sector;
        ray={visual.ray.direction[0],visual.ray.direction[1],visual.ray.direction[2]*16};
    }
    else
    {
        if (!G_VRHandShotFeature(myconnectindex) || !G_VRShotValid(myconnectindex)) return false;
        start={p->pos.x,p->pos.y,int32_t(p->pos.z+p->pyoff)}; sector=p->cursectnum;
        if (!G_VRResolveShot(myconnectindex,start,sector,clamped)) return false;
        auto const shot=G_VRGetShotInput(myconnectindex);
        ray={shot.direction[0],shot.direction[1],shot.direction[2]*16};
    }
    if (unsigned(sector)>=unsigned(numsectors)) return false;
    hitdata_t hit{}; hit.sect=-1;
    {
        auto &owner=sprite[p->i]; auto const cstat=owner.cstat;
        owner.cstat &= ~(CSTAT_SPRITE_BLOCK|CSTAT_SPRITE_BLOCK_HITSCAN);
        hitscan(&start,sector,ray.x,ray.y,ray.z,&hit,CLIPMASK1);
        owner.cstat=cstat;
    }
    if (hit.sect<0) return false;
    // Metres between the origin and the hit (Build z is 16x finer).
    XrVector3f const d={float(hit.x-start.x)/UnitsPerMetre,float(hit.y-start.y)/UnitsPerMetre,float(hit.z-start.z)/ZUnitsPerMetre};
    float const length=std::sqrt(dot(d,d));
    if (!(length>.02f)) return false;
    XrVector3f const f={d.x/length,d.y/length,d.z/length};
    XrVector3f side=std::fabs(f.z)<.95f ? XrVector3f{-f.y,f.x,0.f} : XrVector3f{1.f,0.f,0.f};
    float const sl=std::sqrt(dot(side,side));
    side={side.x/sl,side.y/sl,side.z/sl};
    XrVector3f const up={f.y*side.z-f.z*side.y,f.z*side.x-f.x*side.z,f.x*side.y-f.y*side.x};
    auto const build=[](XrVector3f m, float k) { return XrVector3f{m.x*UnitsPerMetre*k,m.y*UnitsPerMetre*k,m.z*ZUnitsPerMetre*k}; };
    sample.context.instance=120;
    sample.context.modelid=modelid;
    sample.context.skinnum=tile2model[Ptile2tile(VRLaserTile,0)].skinnum;
    sample.context.shade=-32;
    sample.context.cframe=sample.context.nframe=0;
    sample.context.modelToEye[0]=sample.context.modelToEye[5]=sample.context.modelToEye[10]=sample.context.modelToEye[15]=1.f;
    if (!md3_preflightcontext(&sample.context)) return false;
    sample.root=start;
    sample.pivot={0,0,0};
    sample.basis[0]=build(f,length/64.f);          // 64 model units = the whole beam
    sample.basis[1]=build(side,1.f/64.f);
    sample.basis[2]=build(up,1.f/64.f);
    sample.sector=sector;
    if (std::getenv("EDUKE32_XR_TEST_HELD"))
    {
        static int logged;
        if (logged++%120==0) LOG_F(INFO,"OpenXR laser: length=%.2fm origin=%s.",length,visual.selected && visual.valid ? "muzzle" : "hand");
    }
    return true;
}

// The mighty foot (quick kick or KNEE_WEAPON): Duke's boot swings out from under the body toward
// where the head looks, the sole facing forward at full extension. Presentation only; the kick
// itself is the native one (aimed with the head direction of the shot sample).
static bool prepareKickBoot(HandSegmentSample &sample, Camera const &body, eduke_xr::Runtime *runtime)
{
    auto const p=g_player[myconnectindex].ps;
    static double started=-1.;
    static int lastCounter=-1;
    if (!bootModelAvailable() || !overlayEnabled() || !recentered || !inputValid() || inputRuntime!=runtime
        || inputGeneration!=runtime->generation() || !rawInput.headValid || !validPose(rawInput.headPose)
        || screenpeek!=myconnectindex || ud.recstat || ud.overhead_on || ud.camerasprite>=0
        || !(p->gm & MODE_GAME) || (p->gm & MODE_MENU) || p->newowner>=0 || p->over_shoulder_on || p->dead_flag
        || unsigned(p->i)>=MAXSPRITES || sprite[p->i].extra<=0 || unsigned(body.sector)>=unsigned(numsectors))
    { lastCounter=-1; return false; }
    int const counter=p->quick_kick>0 ? 14-p->quick_kick
        : p->curr_weapon==KNEE_WEAPON && p->kickback_pic>0 ? std::min<int>(p->kickback_pic,14) : -1;
    double const now=double(timerGetNanoTicks())/double(timerGetNanoTickRate());
    if (counter>=0 && (lastCounter<0 || counter<lastCounter)) started=now-counter/30.;
    lastCounter=counter;
    if (counter<0 || started<0.) return false;
    float const t=float(std::min(1.,(now-started)/(14./30.)));
    float const extend=std::sin(Pi*t);
    if (extend<=.02f) return false;

    auto const tracking=multiply(pitchRoll(nativePitch(body.horizon),body.roll),inverseYaw);
    float const yaw=fix16_to_float(body.angle)*Pi/1024.f, co=std::cos(yaw), si=std::sin(yaw);
    auto const toBuild=[&](XrVector3f v) {
        v=rotate(tracking,v);
        return XrVector3f{(-v.z*co-v.x*si)*UnitsPerMetre,(-v.z*si+v.x*co)*UnitsPerMetre,-v.y*ZUnitsPerMetre};
    };
    // Head yaw and pitch in tracking space; the kick rises with the gaze (15 degrees above it,
    // -10..+50), high enough to be seen in front of you like the native foot.
    auto const look=rotate(rawInput.headPose.orientation,{0,0,-1});
    float const horizontal=std::hypot(look.x,look.z);
    if (horizontal<1e-3f) return false;
    XrVector3f const forward={look.x/horizontal,0.f,look.z/horizontal};
    XrVector3f const side={-forward.z,0.f,forward.x};               // to the right
    float const gaze=std::max(-10.f*Pi/180.f,std::min(50.f*Pi/180.f,std::atan2(look.y,horizontal)+15.f*Pi/180.f));
    // Leg from the hip: hanging (-80 degrees) to the kick elevation and back.
    float const elevation=-80.f*Pi/180.f+(gaze+80.f*Pi/180.f)*extend;
    XrVector3f const leg={forward.x*std::cos(elevation),std::sin(elevation),forward.z*std::cos(elevation)};
    auto const &head=rawInput.headPose.position;
    XrVector3f const hip={head.x+side.x*.10f,head.y-.75f,head.z+side.z*.10f};
    XrVector3f const ankle={hip.x+leg.x*.85f,hip.y+leg.y*.85f,hip.z+leg.z*.85f};
    // Boot axes (model +X toe, +Y left, +Z up the shin): the toe is the leg turned 90 degrees up.
    XrVector3f const toe={forward.x*std::cos(elevation+Pi/2),std::sin(elevation+Pi/2),forward.z*std::cos(elevation+Pi/2)};
    XrVector3f const shin={-leg.x,-leg.y,-leg.z};
    XrVector3f const left=cross(shin,toe);
    int const modelid=md_tilehasmodel(XRBootModelTile,0);
    sample.context.instance=122;
    sample.context.modelid=modelid;
    sample.context.skinnum=tile2model[Ptile2tile(XRBootModelTile,0)].skinnum;
    sample.context.shade=min<int32_t>(sprite[p->i].shade,24);
    sample.context.cframe=sample.context.nframe=0;
    sample.context.modelToEye[0]=sample.context.modelToEye[5]=sample.context.modelToEye[10]=sample.context.modelToEye[15]=1.f;
    if (!md3_preflightcontext(&sample.context)) return false;
    auto const d=toBuild({ankle.x-origin.x,ankle.y-origin.y,ankle.z-origin.z});
    sample.root={body.pos.x+int32_t(std::lround(d.x)),body.pos.y+int32_t(std::lround(d.y)),body.pos.z+int32_t(std::lround(d.z))};
    sample.sector=body.sector;
    sample.pivot={0,0,0};
    XrVector3f const axes[3]={toe,left,shin};
    for (unsigned axis=0;axis<3;++axis)
    {
        auto const b=toBuild(axes[axis]);
        sample.basis[axis]={b.x/64.f,b.y/64.f,b.z/64.f};
    }
    if (std::getenv("EDUKE32_XR_TEST_HELD"))
    {
        static int logged;
        if (logged++%30==0) LOG_F(INFO,"OpenXR kick boot: t=%.2f extend=%.2f counter=%d.",t,extend,counter);
    }
    return true;
}

} // namespace

// Screen rectangle covered by the native 2D sprites of the current overlay segment.
struct SpriteBounds
{
    float x0=FLT_MAX, y0=FLT_MAX, x1=-FLT_MAX, y1=-FLT_MAX;
    bool empty() const { return x1<=x0 || y1<=y0; }
    void add(float ax0,float ay0,float ax1,float ay1) { x0=std::min(x0,ax0); y0=std::min(y0,ay0); x1=std::max(x1,ax1); y1=std::max(y1,ay1); }
    // Overlay texture coordinates (v up) of the rectangle, clamped to the screen.
    void uv(float *rect) const
    {
        rect[0]=std::max(0.f,x0/xdim); rect[2]=std::min(1.f,x1/xdim);
        rect[1]=std::max(0.f,1.f-y1/ydim); rect[3]=std::min(1.f,1.f-y0/ydim);
    }
};
static bool flushHeadPanel()
{
    XrPosef panel=rawInput.headPose;
    auto const offset=rotate(panel.orientation,{0,0,-eduke_xr::PanelDistance});
    panel.position.x+=offset.x; panel.position.y+=offset.y; panel.position.z+=offset.z;
    std::string error;
    if (!menuRuntime->flushMenuOverlay(panel,eduke_xr::PanelHalfWidth,eduke_xr::PanelHalfWidth*float(ydim)/xdim,
                                       rawInput.headValid && validPose(rawInput.headPose),error))
    { G_XRCancelMenuPresentation(); sdlayer_xr_disableWorld(error.c_str()); return false; }
    return true;
}
static XrQuaternionf quatFromAxes(XrVector3f x, XrVector3f y, XrVector3f z)
{
    float const trace=x.x+y.y+z.z;
    XrQuaternionf q;
    if (trace>0.f)
    {
        float const s=std::sqrt(trace+1.f)*2.f;
        q={(y.z-z.y)/s,(z.x-x.z)/s,(x.y-y.x)/s,.25f*s};
    }
    else if (x.x>y.y && x.x>z.z)
    {
        float const s=std::sqrt(1.f+x.x-y.y-z.z)*2.f;
        q={.25f*s,(y.x+x.y)/s,(z.x+x.z)/s,(y.z-z.y)/s};
    }
    else if (y.y>z.z)
    {
        float const s=std::sqrt(1.f+y.y-x.x-z.z)*2.f;
        q={(y.x+x.y)/s,.25f*s,(z.y+y.z)/s,(z.x-x.z)/s};
    }
    else
    {
        float const s=std::sqrt(1.f+z.z-x.x-y.y)*2.f;
        q={(z.x+x.z)/s,(z.y+y.z)/s,.25f*s,(x.y-y.x)/s};
    }
    return q;
}

// True full body (vr_fullbody, on by default when the pack has vr_duke_ik): Duke's skinned body under
// the headset. Facing follows the head with a 45 degree deadzone (and lines up while moving), the
// spine leans and the pelvis drops toward the head (crouching bends the legs), the arms reach the
// tracked wrists by two-bone IK (the articulated hand shells attach there), the legs walk with a
// stride cycle and the right leg performs the mighty foot. The head is hidden in first person and
// shown in mirrors; the body's own hands are always replaced by the hand shells.
static XrQuaternionf ikConj(XrQuaternionf q) { return {-q.x,-q.y,-q.z,q.w}; }
static XrQuaternionf ikNormalize(XrQuaternionf q)
{
    float const l=std::sqrt(q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w);
    return l>1e-8f ? XrQuaternionf{q.x/l,q.y/l,q.z/l,q.w/l} : XrQuaternionf{0,0,0,1};
}
// Shortest rotation taking direction a onto direction b.
static XrQuaternionf ikBetween(XrVector3f a, XrVector3f b)
{
    float const la=std::sqrt(dot(a,a)), lb=std::sqrt(dot(b,b));
    if (!(la>1e-6f) || !(lb>1e-6f)) return {0,0,0,1};
    a={a.x/la,a.y/la,a.z/la}; b={b.x/lb,b.y/lb,b.z/lb};
    float const c=dot(a,b);
    if (c<-.9999f)
    {
        XrVector3f axis=cross(a,{1,0,0});
        if (dot(axis,axis)<1e-6f) axis=cross(a,{0,1,0});
        float const l=std::sqrt(dot(axis,axis));
        return {axis.x/l,axis.y/l,axis.z/l,0.f};
    }
    auto const axis=cross(a,b);
    return ikNormalize({axis.x,axis.y,axis.z,1.f+c});
}
static XrQuaternionf ikSlerpIdentity(XrQuaternionf q, float t)   // rotation by t of q's angle
{
    q=ikNormalize(q);
    if (q.w<0.f) q={-q.x,-q.y,-q.z,-q.w};
    float const angle=2.f*std::acos(std::min(1.f,q.w))*t, s=std::sqrt(std::max(0.f,1.f-q.w*q.w));
    if (s<1e-6f) return {0,0,0,1};
    float const h=std::sin(angle*.5f)/s;
    return {q.x*h,q.y*h,q.z*h,std::cos(angle*.5f)};
}

static std::vector<vec3f_t> ikDeformed[2];   // first person, with head
static vec3f_t const *ikMirrorVertices() { return ikDeformed[1].data(); }

static bool fullBodyAvailable()
{
    auto const *rig=handRig();
    // Duke's body: only while playing Duke (AA's other characters keep floating hands).
    return vr_fullbody && G_XRModelsEnabled() && rig && rig->ik.tile>=0 && md_tilehasmodel(rig->ik.tile,0)>=0
        && playerCharacter()==0;
}

// What the IK body follows: the local headset, or another player's received pose.
struct IkInput
{
    float eye[3]{};                        // Build
    XrVector3f headForward{}, headUp{};    // unit, Build x and y and up
    float angle=0.f;                       // player yaw (radians): the body's facing turns with it
    bool hand[2]{};
    vec3_t wrist[2]{};                     // hand shell wrist joint (Build)
    std::array<XrVector3f,3> wristBasis[2]{};   // its axes, Build units per model unit
    float feetZ=0.f;
    vec3_t pos{};                          // player position, for the stride
    float kick=0.f;                        // mighty foot leg extension 0..1
    int16_t sector=-1;
    int32_t shade=0, instance=4;
};
struct IkState { float bodyYaw=0.f, stride=0.f, standingHeight=0.f; vec3_t lastPos{}; bool yawValid=false; };

// Skins the IK body to the input into buffers (0: as drawn, 1: always with the head, for mirrors).
static bool solveIkBody(HandSegmentSample &sample, IkInput const &in, IkState &state, bool showHead,
                        std::vector<vec3f_t> (&buffers)[2])
{
    auto const *rig=handRig();
    auto const &ik=rig->ik;
    auto const bone=[&](char const *name) { return ik.find(name); };
    int const pelvis=bone("pelvis"), spine=bone("spine"), chest=bone("chest"), neck=bone("neck"), head=bone("head");
    int const upper[2]={bone("upperarm_l"),bone("upperarm_r")}, fore[2]={bone("forearm_l"),bone("forearm_r")},
              handB[2]={bone("hand_l"),bone("hand_r")};
    int const thigh[2]={bone("thigh_l"),bone("thigh_r")}, calf[2]={bone("calf_l"),bone("calf_r")}, foot[2]={bone("foot_l"),bone("foot_r")};
    auto const &bind=ik.bones;
    float &bodyYaw=state.bodyYaw, &stride=state.stride, &standingHeight=state.standingHeight;

    // Facing: head yaw with a 45 degree deadzone; lines up with the head while moving.
    if (std::hypot(in.headForward.x,in.headForward.y)<1e-3f) return false;
    float const headYaw=wrapRadians(std::atan2(in.headForward.y,in.headForward.x)-in.angle);
    float const moved=state.yawValid ? std::hypot(float(in.pos.x-state.lastPos.x),float(in.pos.y-state.lastPos.y)) : 0.f;
    state.lastPos=in.pos;
    if (!state.yawValid) { bodyYaw=headYaw; stride=0.f; state.yawValid=true; }
    float const lag=wrapRadians(headYaw-bodyYaw), limit=Pi/4.f;
    if (lag>limit) bodyYaw=headYaw-limit; else if (lag<-limit) bodyYaw=headYaw+limit;
    if (moved>1.f) bodyYaw+=wrapRadians(headYaw-bodyYaw)*.2f;
    stride+=moved/(1.4f*UnitsPerMetre);
    stride-=std::floor(stride);

    float const facing=in.angle+bodyYaw, fx=std::cos(facing), fy=std::sin(facing);
    // Model +Y is left or right depending on the asset: tell from the shoulders.
    bool const yLeft=bind[upper[0]].position.y>bind[upper[1]].position.y;
    float const yx=yLeft ? fy : -fy, yy=yLeft ? -fx : fx;   // Build direction of model +Y

    // Uniform scale to the player's standing eye height (remembered, slowly relaxing).
    float const *const eye=in.eye;
    float const feetZ=in.feetZ;
    float const eyeHeight=(feetZ-eye[2])/ZUnitsPerMetre;   // metres
    standingHeight=std::max(eyeHeight,standingHeight*.9995f);
    if (!(standingHeight>.5f)) standingHeight=eyeHeight;
    float const bindEye=(bind[head].position.z+ik.eyeUp)/64.f;
    float const scale=std::max(.8f,std::min(1.25f,standingHeight/std::max(.5f,bindEye)));
    float const unitXY=UnitsPerMetre/64.f*scale, unitZ=ZUnitsPerMetre/64.f*scale;

    // Head bone target and orientation in model space (the bind eye offset, measured from the head mesh).
    auto const dirToModel=[&](XrVector3f v) { return XrVector3f{v.x*fx+v.y*fy,v.x*yx+v.y*yy,v.z}; };
    auto const headFwdM=dirToModel(in.headForward);
    auto const headUpM=dirToModel(in.headUp);
    // Root (model origin, between the feet on the floor) under the head bone, by the bind head offset.
    XrVector3f const bindHead=bind[head].position;
    float const headBack=ik.eyeForward, headDown=ik.eyeUp;
    // The body sits a little further back than the skull alone puts it, so looking down shows the
    // chest and feet instead of the inside of the collar.
    float const settle=.04f*64.f;
    // Eye in model axes relative to the root is (bindHead.x + forward offsets...): solve root from the eye.
    XrVector3f const headTargetFromEye={-headFwdM.x*headBack-headUpM.x*headDown,-headFwdM.y*headBack-headUpM.y*headDown,
                                        -headFwdM.z*headBack-headUpM.z*headDown};
    float const rootX=eye[0]-(fx*(bindHead.x+settle-headTargetFromEye.x)+yx*(bindHead.y-headTargetFromEye.y))*unitXY;
    float const rootY=eye[1]-(fy*(bindHead.x+settle-headTargetFromEye.x)+yy*(bindHead.y-headTargetFromEye.y))*unitXY;
    auto const toModel=[&](float const P[3]) {
        float const dx=(P[0]-rootX)/unitXY, dy=(P[1]-rootY)/unitXY;
        return XrVector3f{dx*fx+dy*fy,dx*yx+dy*yy,(feetZ-P[2])/unitZ};
    };
    auto const eyeM=toModel(eye);
    XrVector3f const headTarget={eyeM.x+headTargetFromEye.x-settle,eyeM.y+headTargetFromEye.y,eyeM.z+headTargetFromEye.z};

    // Bind locals.
    size_t const count=bind.size();
    std::vector<XrQuaternionf> localRot(count), worldRot(count);
    std::vector<XrVector3f> localPos(count), worldPos(count);
    std::vector<int8_t> overridden(count,0), placed(count,0);   // rotation / position set explicitly
    for (size_t b=0;b<count;++b)
    {
        int const parent=bind[b].parent;
        if (parent<0) { localRot[b]=bind[b].rotation; localPos[b]=bind[b].position; continue; }
        auto const inv=ikConj(bind[parent].rotation);
        localRot[b]=multiply(inv,bind[b].rotation);
        auto const d=XrVector3f{bind[b].position.x-bind[parent].position.x,bind[b].position.y-bind[parent].position.y,
                                bind[b].position.z-bind[parent].position.z};
        localPos[b]=rotate(inv,d);
    }
    auto const fk=[&](size_t from) {
        for (size_t b=from;b<count;++b)
        {
            int const parent=bind[b].parent;
            if (parent<0) { if (!overridden[b]) worldRot[b]=localRot[b]; if (!placed[b]) worldPos[b]=localPos[b]; continue; }
            if (!overridden[b]) worldRot[b]=multiply(worldRot[parent],localRot[b]);
            if (placed[b]) continue;
            auto const o=rotate(worldRot[parent],localPos[b]);
            worldPos[b]={worldPos[parent].x+o.x,worldPos[parent].y+o.y,worldPos[parent].z+o.z};
        }
    };
    // Pelvis: drops when the head is lower than standing (legs bend), leans toward the head.
    float const drop=std::max(0.f,bindHead.z-headTarget.z);
    worldPos[pelvis]={bind[pelvis].position.x+(headTarget.x-bindHead.x)*.35f,bind[pelvis].position.y+(headTarget.y-bindHead.y)*.35f,
                      bind[pelvis].position.z-drop*.9f};
    worldRot[pelvis]=bind[pelvis].rotation; overridden[pelvis]=placed[pelvis]=1;
    fk(0);
    // Spine and chest bend so the neck heads for the head target.
    {
        auto const s0=worldPos[spine];
        XrVector3f const current={worldPos[neck].x-s0.x,worldPos[neck].y-s0.y,worldPos[neck].z-s0.z};
        XrVector3f const wanted={headTarget.x-s0.x,headTarget.y-s0.y,headTarget.z-s0.z-(bindHead.z-bind[neck].position.z)};
        auto const bend=ikSlerpIdentity(ikBetween(current,wanted),.5f);
        worldRot[spine]=multiply(bend,worldRot[spine]); overridden[spine]=1; fk(size_t(spine)+1);
        worldRot[chest]=multiply(bend,worldRot[chest]); overridden[chest]=1; fk(size_t(chest)+1);
    }
    // Head and neck follow the headset (relative to the model's forward/up).
    {
        // Rotation taking the model's forward/up onto the head's (as coordinates: proper either way).
        auto const target=quatFromAxes(headFwdM,cross(headUpM,headFwdM),headUpM);
        auto const chestDelta=multiply(worldRot[chest],ikConj(bind[chest].rotation));
        auto const relative=multiply(target,ikConj(chestDelta));
        worldRot[neck]=multiply(ikSlerpIdentity(relative,.4f),multiply(chestDelta,bind[neck].rotation)); overridden[neck]=1;
        fk(size_t(neck)+1);
        worldRot[head]=multiply(target,bind[head].rotation); overridden[head]=1;
        fk(size_t(head)+1);
    }
    // Per-bone stretch along the bone (toward its child): arms lengthen to reach the hands.
    std::vector<float> stretch(count,1.f);
    std::vector<XrVector3f> stretchAxis(count,XrVector3f{0,0,0});
    // Two-bone IK: root bone b0 at a, mid bone b1, end bone b2 reaching t with the bend toward pole.
    // With canStretch both bones lengthen equally when t is out of reach (up to MaxArmStretch).
    auto const twoBone=[&](int b0, int b1, int b2, XrVector3f t, XrVector3f pole, bool canStretch) {
        auto const a=worldPos[b0];
        float L1=std::sqrt(dot(localPos[b1],localPos[b1])), L2=std::sqrt(dot(localPos[b2],localPos[b2]));
        XrVector3f d={t.x-a.x,t.y-a.y,t.z-a.z};
        float dist=std::sqrt(dot(d,d));
        if (!(dist>1e-4f) || !(L1>1e-4f) || !(L2>1e-4f)) return;
        float constexpr MaxArmStretch=1.6f;
        float const reach=(L1+L2)*.995f;
        if (canStretch && dist>reach)
        {
            float const k=std::min(MaxArmStretch,dist/reach);
            for (int b:{b0,b1})
            {
                int const child=b==b0 ? b1 : b2;
                float const l=std::sqrt(dot(localPos[child],localPos[child]));
                stretch[b]=k; stretchAxis[b]={localPos[child].x/l,localPos[child].y/l,localPos[child].z/l};
                localPos[child]={localPos[child].x*k,localPos[child].y*k,localPos[child].z*k};
            }
            L1*=k; L2*=k;
            fk(size_t(b0)+1);
        }
        XrVector3f const dir={d.x/dist,d.y/dist,d.z/dist};
        dist=std::max(std::fabs(L1-L2)+1e-3f,std::min(L1+L2-1e-3f,dist));
        float const cosA=std::max(-1.f,std::min(1.f,(L1*L1+dist*dist-L2*L2)/(2.f*L1*dist))), sinA=std::sqrt(1.f-cosA*cosA);
        float const pd=dot(pole,dir);
        XrVector3f perp={pole.x-dir.x*pd,pole.y-dir.y*pd,pole.z-dir.z*pd};
        float const pl=std::sqrt(dot(perp,perp));
        if (pl<1e-5f) perp=std::fabs(dir.z)<.9f ? cross(dir,{0,0,1}) : cross(dir,{1,0,0});
        else perp={perp.x/pl,perp.y/pl,perp.z/pl};
        XrVector3f const elbow={a.x+dir.x*L1*cosA+perp.x*L1*sinA,a.y+dir.y*L1*cosA+perp.y*L1*sinA,a.z+dir.z*L1*cosA+perp.z*L1*sinA};
        XrVector3f const end={a.x+dir.x*dist,a.y+dir.y*dist,a.z+dir.z*dist};
        // Swing each bone from its current direction (parent-carried bind) onto the solved one.
        auto const cur1=rotate(worldRot[b0],localPos[b1]);
        worldRot[b0]=multiply(ikBetween(cur1,{elbow.x-a.x,elbow.y-a.y,elbow.z-a.z}),worldRot[b0]); overridden[b0]=1;
        fk(size_t(b0)+1);
        auto const cur2=rotate(worldRot[b1],localPos[b2]);
        worldRot[b1]=multiply(ikBetween(cur2,{end.x-elbow.x,end.y-elbow.y,end.z-elbow.z}),worldRot[b1]); overridden[b1]=1;
        fk(size_t(b1)+1);
    };
    // Arms to the tracked wrists (the hand shell's wrist joint), hanging when untracked.
    for (unsigned side=0;side<2;++side)
    {
        float const out=bind[upper[side]].position.y>0.f ? 1.f : -1.f;
        XrVector3f target;
        if (in.hand[side])
        {
            auto const &w=in.wrist[side];
            float const P[3]={float(w.x),float(w.y),float(w.z)};
            target=toModel(P);
        }
        else target={worldPos[upper[side]].x+4.f,worldPos[upper[side]].y+out*6.f,worldPos[upper[side]].z-40.f};
        twoBone(upper[side],fore[side],handB[side],target,{-.4f,out*.8f,-1.f},in.hand[side]);
        if (in.hand[side])
        {
            // Hand bone along the wrist joint frame (XR: -Z toward the fingers, +Y back of the hand).
            auto const &bs=in.wristBasis[side];
            auto const axis=[&](XrVector3f b) {
                XrVector3f const m={(b.x*fx+b.y*fy)/unitXY,(b.x*yx+b.y*yy)/unitXY,-b.z/unitZ};
                float const l=std::sqrt(dot(m,m));
                return l>1e-6f ? XrVector3f{m.x/l,m.y/l,m.z/l} : XrVector3f{1,0,0};
            };
            worldRot[handB[side]]=quatFromAxes(axis(bs[0]),axis(bs[1]),axis(bs[2])); overridden[handB[side]]=1;
            fk(size_t(handB[side])+1);
        }
    }
    // Legs: feet planted (stride cycle while moving), right leg kicks for the mighty foot.
    float const kickExtend=in.kick;
    for (unsigned side=0;side<2;++side)
    {
        float const phase=(stride+(side ? .5f : 0.f))*2.f*Pi;
        float const amount=std::min(1.f,moved/4.f);
        XrVector3f target=bind[foot[side]].position;
        target.x+=std::sin(phase)*.18f*64.f*amount;
        target.z+=std::max(0.f,std::cos(phase))*.08f*64.f*amount;
        if (side==1 && kickExtend>0.f)
        {
            float const gaze=std::max(-10.f,std::min(50.f,std::atan2(headFwdM.z,std::hypot(headFwdM.x,headFwdM.y))*180.f/Pi+15.f))*Pi/180.f;
            auto const hip=worldPos[thigh[side]];
            float const reach=(std::sqrt(dot(localPos[calf[side]],localPos[calf[side]]))+std::sqrt(dot(localPos[foot[side]],localPos[foot[side]])))*.95f;
            XrVector3f const kick={hip.x+std::cos(gaze)*reach,hip.y,hip.z+std::sin(gaze)*reach};
            target={target.x+(kick.x-target.x)*kickExtend,target.y+(kick.y-target.y)*kickExtend,target.z+(kick.z-target.z)*kickExtend};
        }
        twoBone(thigh[side],calf[side],foot[side],target,{1.f,0.f,.2f},false);
    }

    // Skin on the CPU (model units, model space): first person without the head, and a copy with
    // the head for mirrors.
    auto &deformed=buffers[0], &withHead=buffers[1];
    deformed.resize(ik.vertices.size()); withHead.resize(ik.vertices.size());
    // Bone rotations as 3x3 matrices once, rather than two quaternion products per vertex weight.
    std::vector<std::array<float,9>> boneMatrix(count);
    for (size_t b=0;b<count;++b)
    {
        auto const q=ikNormalize(worldRot[b]);
        float const xx=q.x*q.x, yy=q.y*q.y, zz=q.z*q.z, xy=q.x*q.y, xz=q.x*q.z, yz=q.y*q.z, wx=q.w*q.x, wy=q.w*q.y, wz=q.w*q.z;
        boneMatrix[b]={1.f-2.f*(yy+zz),2.f*(xy-wz),2.f*(xz+wy),
                       2.f*(xy+wz),1.f-2.f*(xx+zz),2.f*(yz-wx),
                       2.f*(xz-wy),2.f*(yz+wx),1.f-2.f*(xx+yy)};
    }
    for (size_t i=0;i<ik.vertices.size();++i)
    {
        auto const &v=ik.vertices[i];
        uint8_t const hide=ik.hide[i];
        int collapse=-1;
        if (hide&2) collapse=handB[0];
        else if (hide&4) collapse=handB[1];
        if (collapse>=0) { deformed[i]=withHead[i]={worldPos[collapse].x,worldPos[collapse].y,worldPos[collapse].z}; continue; }
        float acc[3]={0,0,0};
        for (unsigned j=0;j<v.count;++j)
        {
            auto const &m=boneMatrix[v.bone[j]];
            XrVector3f l=v.local[j];
            if (stretch[v.bone[j]]!=1.f)
            {
                auto const &axis=stretchAxis[v.bone[j]];
                float const along=dot(l,axis)*(stretch[v.bone[j]]-1.f);
                l={l.x+axis.x*along,l.y+axis.y*along,l.z+axis.z*along};
            }
            auto const &o=worldPos[v.bone[j]];
            acc[0]+=v.weight[j]*(o.x+m[0]*l.x+m[1]*l.y+m[2]*l.z);
            acc[1]+=v.weight[j]*(o.y+m[3]*l.x+m[4]*l.y+m[5]*l.z);
            acc[2]+=v.weight[j]*(o.z+m[6]*l.x+m[7]*l.y+m[8]*l.z);
        }
        withHead[i]={acc[0],acc[1],acc[2]};
        deformed[i]=(hide&1) && !showHead ? vec3f_t{worldPos[neck].x,worldPos[neck].y,worldPos[neck].z} : withHead[i];
    }
    sample.context.instance=in.instance;
    sample.context.modelid=md_tilehasmodel(ik.tile,0);
    sample.context.skinnum=tile2model[Ptile2tile(ik.tile,0)].skinnum;
    sample.context.shade=in.shade;
    sample.context.cframe=sample.context.nframe=0;
    sample.context.modelToEye[0]=sample.context.modelToEye[5]=sample.context.modelToEye[10]=sample.context.modelToEye[15]=1.f;
    sample.context.vertices=deformed.data();
    sample.context.vertexCount=int32_t(deformed.size());
    if (!md3_preflightcontext(&sample.context)) return false;
    sample.root={int32_t(std::lround(rootX)),int32_t(std::lround(rootY)),int32_t(std::lround(feetZ))};
    sample.pivot={0,0,0};
    sample.basis[0]={fx*unitXY,fy*unitXY,0};
    sample.basis[1]={yx*unitXY,yy*unitXY,0};
    sample.basis[2]={0,0,-unitZ};
    sample.sector=in.sector;
    updatesector(sample.root.x,sample.root.y,&sample.sector);
    if (sample.sector<0) sample.sector=in.sector;
    if (std::getenv("EDUKE32_XR_TEST_HANDS") && in.instance==4)
    {
        static int logged;
        if (logged++%120==0)
            LOG_F(INFO,"OpenXR IK body: scale=%.2f eye=%.1f,%.1f drop=%.1f head=%.1f,%.1f,%.1f hands=%d,%d kick=%.2f.",scale,
                  ik.eyeForward,ik.eyeUp,drop,
                  headTarget.x,headTarget.y,headTarget.z,int(in.hand[0]),int(in.hand[1]),kickExtend);
    }
    return true;
}


// The mighty foot's leg extension (0..1) from the local player's kick counters.
static float localKickExtend()
{
    auto const p=g_player[myconnectindex].ps;
    static double kickStart=-1.;
    static int lastCounter=-1;
    int const counter=p->quick_kick>0 ? 14-p->quick_kick
        : p->curr_weapon==KNEE_WEAPON && p->kickback_pic>0 ? std::min<int>(p->kickback_pic,14) : -1;
    double const now=double(timerGetNanoTicks())/double(timerGetNanoTickRate());
    if (counter>=0 && (lastCounter<0 || counter<lastCounter)) kickStart=now-counter/30.;
    lastCounter=counter;
    return counter>=0 && kickStart>=0. ? std::sin(Pi*float(std::min(1.,(now-kickStart)/(14./30.)))) : 0.f;
}

static bool localIkInput(IkInput &in, Camera const &body, eduke_xr::Runtime *runtime)
{
    auto const p=g_player[myconnectindex].ps;
    if (!overlayEnabled() || !recentered || !inputValid() || inputRuntime!=runtime
        || inputGeneration!=runtime->generation() || !rawInput.headValid || !validPose(rawInput.headPose)
        || screenpeek!=myconnectindex || ud.recstat || ud.overhead_on || ud.camerasprite>=0
        || !(p->gm & MODE_GAME) || (p->gm & MODE_MENU) || p->newowner>=0 || p->over_shoulder_on
        || p->dead_flag || unsigned(p->i)>=MAXSPRITES || sprite[p->i].extra<=0 || unsigned(body.sector)>=unsigned(numsectors))
        return false;
    TrackingToBuild const build(body);
    auto const eyeOffset=build.offset({rawInput.headPose.position.x-origin.x,rawInput.headPose.position.y-origin.y,
                                       rawInput.headPose.position.z-origin.z});
    in.eye[0]=body.pos.x+eyeOffset.x; in.eye[1]=body.pos.y+eyeOffset.y; in.eye[2]=body.pos.z+eyeOffset.z;
    in.headForward=build.direction(rotate(rawInput.headPose.orientation,{0,0,-1}));
    in.headUp=build.direction(rotate(rawInput.headPose.orientation,{0,1,0}));
    in.angle=fix16_to_float(body.angle)*Pi/1024.f;
    for (unsigned side=0;side<2;++side)
    {
        in.hand[side]=handJoints[side].valid;
        in.wrist[side]=handJoints[side].roots[1];
        in.wristBasis[side]=handJoints[side].bases[1];
    }
    in.feetZ=float(sprite[p->i].z);
    in.pos=p->pos;
    in.kick=localKickExtend();
    in.sector=body.sector;
    in.shade=min<int32_t>(sprite[p->i].shade,24);
    in.instance=4;
    return true;
}

static bool prepareIkBody(HandSegmentSample &sample, Camera const &body, eduke_xr::Runtime *runtime, bool showHead)
{
    static IkState state;
    IkInput in;
    if (!fullBodyAvailable() || !localIkInput(in,body,runtime)) { state.yawValid=false; return false; }
    return solveIkBody(sample,in,state,showHead,ikDeformed);
}

// ---- Other players' VR bodies. Peers send their raw tracking (head, each hand's grip or weapon
// frame with its finger pose, the held model and frame: VRBodyPose); every client solves their
// IK bodies and hands locally with the same rig as its own.

static int16_t clampShort(float v) { return int16_t(std::max(-32767.f,std::min(32767.f,std::round(v)))); }

static VRBodyFrame encodeFrame(HandFrame const &frame, vec3_t const &ref)
{
    VRBodyFrame wire;
    for (unsigned k=0;k<3;++k) wire.root[k]=clampShort(frame.root[k]-float(k==0 ? ref.x : k==1 ? ref.y : ref.z));
    for (unsigned k=0;k<3;++k)
    {
        wire.axes[k*3]=clampShort(frame.axes[k].x/UnitsPerMetre*VRBodyAxisScale);
        wire.axes[k*3+1]=clampShort(frame.axes[k].y/UnitsPerMetre*VRBodyAxisScale);
        wire.axes[k*3+2]=clampShort(frame.axes[k].z/ZUnitsPerMetre*VRBodyAxisScale);
    }
    return wire;
}

static HandFrame decodeFrame(VRBodyFrame const &wire, float const ref[3])
{
    HandFrame frame;
    for (unsigned k=0;k<3;++k) frame.root[k]=ref[k]+wire.root[k];
    for (unsigned k=0;k<3;++k)
        frame.axes[k]={wire.axes[k*3]*UnitsPerMetre/VRBodyAxisScale,wire.axes[k*3+1]*UnitsPerMetre/VRBodyAxisScale,
                       wire.axes[k*3+2]*ZUnitsPerMetre/VRBodyAxisScale};
    return frame;
}

static void encodeUnit(XrVector3f v, int16_t out[3])
{
    float const l=std::sqrt(dot(v,v));
    if (!(l>1e-6f)) { out[0]=32767; out[1]=out[2]=0; return; }
    out[0]=clampShort(v.x/l*32767.f); out[1]=clampShort(v.y/l*32767.f); out[2]=clampShort(v.z/l*32767.f);
}

// Each world frame in multiplayer: what this player's body shows, for everyone else to solve.
static void publishBodyPose(Camera const &body, eduke_xr::Runtime *runtime, HandModelSample const *held, int heldTile)
{
    if (!g_netServer && !g_netClient) return;
    VRBodyPose pose;
    IkInput in;
    if (localIkInput(in,body,runtime))
    {
        pose.flags|=VRBodyHead;
        pose.eye[0]=clampShort(in.eye[0]-body.pos.x); pose.eye[1]=clampShort(in.eye[1]-body.pos.y);
        pose.eye[2]=clampShort(in.eye[2]-body.pos.z);
        encodeUnit(in.headForward,pose.headForward); encodeUnit(in.headUp,pose.headUp);
        pose.kick=uint8_t(std::lround(std::max(0.f,std::min(1.f,in.kick))*255.f));
        {
            // The body camera removes the head's share of the native angle (head aiming).
            auto const p=g_player[myconnectindex].ps;
            float const native=fix16_to_float(p->q16ang), turn=std::remainder(fix16_to_float(body.angle)-native,2048.f);
            pose.bodyAngle=clampShort(turn*16.f);
        }
        for (unsigned side=0;side<2;++side)
        {
            auto const &wire=handWire[side];
            if (wire.kind==VRHandHold && !held) continue;
            pose.hand[side]=wire.kind;
            pose.pull[side]=uint8_t(std::lround(std::max(0.f,std::min(1.f,wire.pull))*255.f));
            if (wire.kind!=VRHandNone) pose.handFrame[side]=encodeFrame(wire.frame,body.pos);
        }
        if (held && heldTile>=0)
        {
            pose.flags|=VRBodyWeapon;
            pose.weaponTile=int16_t(heldTile);
            pose.weaponFrame=int16_t(held->context.cframe); pose.weaponNextFrame=int16_t(held->context.nframe);
            pose.weaponLerp=uint8_t(std::lround(std::max(0.f,std::min(1.f,held->context.interpol))*255.f));
            pose.weapon=encodeFrame(heldModelFrame(*held),body.pos);
        }
    }
    G_VRPublishBodyPose(pose);
}

static struct RemoteBody { IkState ik; std::vector<vec3f_t> body[2], hands[2]; } remoteBodies[MAXPLAYERS];

// Remote VR players in view: IK body, hand shells and held model from their latest pose, and their
// native player sprite (with its attached weapon) hidden. Players without a fresh pose stay native.
static void prepareRemoteBodies(std::vector<HandSegmentSample> &out, int32_t smoothRatio)
{
    auto const *rig=handRig();
    if ((!g_netServer && !g_netClient) || !fullBodyAvailable()) return;
    char const *const named[]={nullptr,"relaxed","trigger","point","fist"};
    float const sr=float(smoothRatio)/65536.f;
    for (int k=0;k<MAXPLAYERS;++k)
    {
        if (k==myconnectindex) continue;
        auto &remote=remoteBodies[k];
        auto const ps=g_player[k].ps;
        VRBodyPose pose;
        if (!ps || unsigned(ps->i)>=MAXSPRITES || !G_VRGetBodyPose(k,pose,.5) || !(pose.flags & VRBodyHead)
            || ps->dead_flag || sprite[ps->i].extra<=0)
        { remote.ik.yawValid=false; continue; }
        int view=-1;
        for (int j=0;j<spritesortcnt;++j)
            if (tsprite[j].owner==ps->i && tsprite[j].statnum!=TSPR_TEMP) { view=j; break; }
        if (view<0) continue;   // not in view this frame
        auto const &t=tsprite[view];
        float const ref[3]={ps->opos.x+(ps->pos.x-ps->opos.x)*sr,ps->opos.y+(ps->pos.y-ps->opos.y)*sr,
                            ps->opos.z+(ps->pos.z-ps->opos.z)*sr};
        IkInput in;
        for (unsigned k3=0;k3<3;++k3) in.eye[k3]=ref[k3]+pose.eye[k3];
        in.headForward={pose.headForward[0]/32767.f,pose.headForward[1]/32767.f,pose.headForward[2]/32767.f};
        in.headUp={pose.headUp[0]/32767.f,pose.headUp[1]/32767.f,pose.headUp[2]/32767.f};
        fix16_t const turn=((ps->q16ang-ps->oq16ang+F16(1024))&0x7FFFFFF)-F16(1024);
        in.angle=(fix16_to_float(ps->oq16ang)+fix16_to_float(turn)*sr+pose.bodyAngle/16.f)*Pi/1024.f;
        in.feetZ=float(t.z);
        in.pos=ps->pos;
        in.kick=pose.kick/255.f;
        in.sector=t.sectnum;
        in.shade=min<int32_t>(t.shade,24);
        in.instance=1000+k*8;
        size_t const before=out.size();
        bool const weapon=(pose.flags & VRBodyWeapon) && md_tilehasmodel(pose.weaponTile,0)>=0;
        for (unsigned side=0;side<2;++side)
        {
            HandRigPose const *hp=nullptr;
            uint8_t const kind=pose.hand[side];
            if (kind==VRHandHold && weapon)
            {
                for (auto const &h:rig->holds)
                    if (h.first==pose.weaponTile) { hp=rig->pose(side,h.second.c_str()); break; }
                if (hp && !hp->weaponFrame) hp=nullptr;
            }
            else if (kind>=VRHandRelaxed && kind<=VRHandFist)
            {
                hp=rig->pose(side,named[kind]);
                if (!hp) hp=rig->pose(side,"relaxed");
                if (hp && hp->weaponFrame) hp=nullptr;
            }
            if (!hp) continue;
            auto joints=hp->joints;
            if (kind==VRHandHold) curlIndexFinger(joints,pose.pull[side]/255.f);
            HandRoots roots;
            HandBases bases;
            placeHandJoints(joints,hp->weaponFrame,decodeFrame(pose.handFrame[side],ref),roots,bases);
            in.hand[side]=true; in.wrist[side]=roots[1]; in.wristBasis[side]=bases[1];
            bool const wristCut=rig->wristShellTile[side]>=0 && md_tilehasmodel(rig->wristShellTile[side],0)>=0;
            HandSegmentSample sample;
            if (skinHandShell(sample,remote.hands[side],wristCut ? rig->wristShell[side] : rig->shell[side],
                              wristCut ? rig->wristShellTile[side] : rig->shellTile[side],roots,bases,in.shade,
                              in.instance+1+int(side),in.sector))
                out.push_back(sample);
        }
        if (weapon)
        {
            HandSegmentSample sample;
            sample.context.instance=in.instance+3;
            sample.context.modelid=md_tilehasmodel(pose.weaponTile,0);
            sample.context.skinnum=tile2model[Ptile2tile(pose.weaponTile,0)].skinnum;
            sample.context.shade=in.shade;
            sample.context.cframe=pose.weaponFrame; sample.context.nframe=pose.weaponNextFrame;
            sample.context.interpol=pose.weaponLerp/255.f;
            sample.context.modelToEye[0]=sample.context.modelToEye[5]=sample.context.modelToEye[10]=sample.context.modelToEye[15]=1.f;
            if (md3_preflightcontext(&sample.context))
            {
                auto const frame=decodeFrame(pose.weapon,ref);
                sample.root={int32_t(std::lround(frame.root[0])),int32_t(std::lround(frame.root[1])),int32_t(std::lround(frame.root[2]))};
                sample.pivot={0,0,0};
                for (unsigned a=0;a<3;++a) sample.basis[a]={frame.axes[a].x/64.f,frame.axes[a].y/64.f,frame.axes[a].z/64.f};
                sample.sector=in.sector;
                updatesector(sample.root.x,sample.root.y,&sample.sector);
                if (sample.sector<0) sample.sector=in.sector;
                out.push_back(sample);
            }
        }
        HandSegmentSample bodySample;
        if (!solveIkBody(bodySample,in,remote.ik,true,remote.body)) { out.resize(before); continue; }
        out.push_back(bodySample);
        for (int j=0;j<spritesortcnt;++j)
            if (tsprite[j].owner==ps->i) tsprite[j].xrepeat=tsprite[j].yrepeat=0;
        if (std::getenv("EDUKE32_XR_TEST_BODY_POSES"))
        {
            static uint32_t logged[MAXPLAYERS];
            static uint8_t lastKick[MAXPLAYERS];
            bool const kickStarted=pose.kick && !lastKick[k];
            lastKick[k]=pose.kick;
            if (logged[k]++%30==0 || kickStarted)
            {
                // Wrists relative to the eye in the player's own frame (forward, left; Build units), z down.
                float const c=std::cos(in.angle), sn=std::sin(in.angle);
                int w[2][3]{};
                for (unsigned side=0;side<2;++side)
                    if (in.hand[side])
                    {
                        float const dx=in.wrist[side].x-in.eye[0], dy=in.wrist[side].y-in.eye[1];
                        w[side][0]=int(std::lround(dx*c+dy*sn)); w[side][1]=int(std::lround(dx*sn-dy*c));
                        w[side][2]=int(std::lround(in.wrist[side].z-in.eye[2]));
                    }
                LOG_F(INFO,"VR remote body: player=%d sequence=%u hands=%d,%d kinds=%u,%u weapon=%d models=%zu kick=%u "
                      "headyaw=%.1f left=%d,%d,%d right=%d,%d,%d.",
                      k,unsigned(pose.sequence),int(in.hand[0]),int(in.hand[1]),unsigned(pose.hand[0]),unsigned(pose.hand[1]),
                      weapon ? int(pose.weaponTile) : -1,out.size()-before,unsigned(pose.kick),
                      wrapRadians(std::atan2(in.headForward.y,in.headForward.x)-in.angle)*180.f/Pi,
                      w[0][0],w[0][1],w[0][2],w[1][0],w[1][1],w[1][2]);
            }
        }
    }
}

// Tipping ("shake it baby"): Duke's native tip shows a hand holding money on the HUD; in the
// headset the off hand holds a wad of bills (vr_money, made from the game's MONEY art) across
// the palm while the tip plays, and a moment after.
static bool prepareTipWad(HandSegmentSample &sample, Camera const &body)
{
    auto const p=g_player[myconnectindex].ps;
    static double shownUntil;
    double const now=double(timerGetNanoTicks())/double(timerGetNanoTickRate());
    if (p->tipincs>0) shownUntil=now+.6;
    int const modelid=md_tilehasmodel(VRMoneyTile,0);
    if (now>shownUntil || modelid<0 || !G_XRModelsEnabled()) return false;
    unsigned const hand=aimHand()>=0 ? unsigned(1-aimHand()) : 0u;
    if (!handJoints[hand].valid) return false;
    auto const &palm=handJoints[hand].roots[0];
    auto const &b=handJoints[hand].bases[0];   // palm joint axes (Build units per model unit)
    // XR palm frame: -Z toward the fingers, +Y the back of the hand. The wad lies across the palm,
    // 2 cm out from it and 1 cm toward the fingers: MD3 X = palm X, Y = -Z, Z = +Y.
    float const out=-.02f*64.f, toward=-.01f*64.f;
    sample.root={palm.x+int32_t(std::lround(b[1].x*out+b[2].x*toward)),palm.y+int32_t(std::lround(b[1].y*out+b[2].y*toward)),
                 palm.z+int32_t(std::lround(b[1].z*out+b[2].z*toward))};
    sample.pivot={0,0,0};
    sample.basis[0]=b[0];
    sample.basis[1]={-b[2].x,-b[2].y,-b[2].z};
    sample.basis[2]=b[1];
    sample.context.instance=124;
    sample.context.modelid=modelid;
    sample.context.skinnum=tile2model[Ptile2tile(VRMoneyTile,0)].skinnum;
    sample.context.shade=min<int32_t>(sprite[p->i].shade,24);
    sample.context.cframe=sample.context.nframe=0;
    sample.context.modelToEye[0]=sample.context.modelToEye[5]=sample.context.modelToEye[10]=sample.context.modelToEye[15]=1.f;
    if (!md3_preflightcontext(&sample.context)) return false;
    sample.sector=body.sector;
    updatesector(sample.root.x,sample.root.y,&sample.sector);
    if (sample.sector<0) sample.sector=body.sector;
    if (std::getenv("EDUKE32_XR_TEST_HELD"))
    {
        static int logged;
        if (logged++%30==0) LOG_F(INFO,"OpenXR tip wad: hand=%u tipincs=%d.",hand,p->tipincs);
    }
    return true;
}

static SpriteBounds wheelPanelBounds;
static void wheelPanelSprite(float x0,float y0,float x1,float y1) { wheelPanelBounds.add(x0,y0,x1,y1); }

// 2D icons of a wheel on a panel at the ring itself (never on the HUD): the gadget wheel's
// inventory items with their charge, and the weapon wheel's pickup sprites when VR models are off
// or a slot has none. Drawn as its own overlay segment, cropped and placed facing the head.
void G_XRDrawWheelPanels()
{
    auto const p=g_player[myconnectindex].ps;
    for (Wheel *w:{&wheel,&gadgetWheel})
    {
        if (!w->open || !w->count || (!w->gadgets && wheelUses3D())) continue;
        if (!menuRuntime || menuRuntime->generation()!=menuGeneration || !menuRuntime->menuOverlayTargetBound()) return;
        if (!flushHeadPanel()) return;
        float const frac=wheelOpenFraction(*w);
        float const ringUnits=62.f*frac;
        wheelPanelBounds=SpriteBounds{};
        polymost_xrSpriteBounds=wheelPanelSprite;
        for (unsigned slot=0;slot<w->count;++slot)
        {
            int const item=w->slots[slot];
            int tile;
            if (w->gadgets) tile=gadgetTile(item);
            else
            {
                tile=item==GROW_WEAPON ? GROWSPRITEICON : WeaponPickupSprites[item];
                if (item==HANDBOMB_WEAPON && p->ammo_amount[item]<=0 && p->hbomb_on) tile=WeaponPickupSprites[HANDREMOTE_WEAPON];
            }
            if ((unsigned)tile>=MAXTILES) continue;
            bool const selectable=slotSelectable(*w,p,int(slot)), hovered=int(slot)==w->hovered;
            float const angle=2*Pi*slot/w->count;
            float const cx=160.f+ringUnits*std::sin(angle), cy=100.f-ringUnits*std::cos(angle);
            int const scale=int((hovered ? 62000.f : selectable ? 50000.f : 38000.f)*frac);
            // Centre the picture itself: pickup sprites carry ground-anchored tile offsets.
            float const k=scale/65536.f;
            float const ox=picanm[tile].xofs*k, oy=picanm[tile].yofs*k;
            rotatesprite_fs(int(std::lround((cx+ox)*65536.f)),int(std::lround((cy+oy)*65536.f)),scale,0,tile,
                            hovered ? -16 : selectable ? 0 : 28,0,2+8);
            if (w->gadgets && selectable)
            {
                int const amount=p->inv_amount[gadgetItem(item)];
                int const percent=item==0 ? amount : item==1 ? (amount+3)>>2 : item==2 ? (amount+15)/24
                    : item==3 ? (amount+15)>>4 : amount/12;
                char text[8];
                Bsnprintf(text,sizeof(text),"%d%%",percent);
                minitext(int(cx)-int(std::strlen(text))*2,int(cy)+12,text,hovered ? 7 : 0,2+8+16);
            }
        }
        polymost_xrSpriteBounds=nullptr;
        float rect[4]={0,0,1,1};
        bool const visible=!wheelPanelBounds.empty() && rawInput.headValid;
        float halfWidth=.01f, halfHeight=.01f;
        XrPosef pose{}; pose.orientation.w=1;
        if (visible)
        {
            auto &b=wheelPanelBounds;
            b.x0-=2; b.y0-=2; b.x1+=2; b.y1+=2;
            b.uv(rect);
            float const metresPerPixel=wheelRadius(*w,frac)/std::max(1.f,ringUnits*ydim/200.f);
            float const x0=rect[0]*xdim, x1=rect[2]*xdim, y0=(1.f-rect[3])*ydim, y1=(1.f-rect[1])*ydim;
            halfWidth=(x1-x0)*.5f*metresPerPixel; halfHeight=(y1-y0)*.5f*metresPerPixel;
            float const dx=((x0+x1)*.5f-xdim*.5f)*metresPerPixel, dy=-((y0+y1)*.5f-ydim*.5f)*metresPerPixel;
            auto const c=wheelCentre(*w,frac);
            pose.position={c.x+w->faceRight.x*dx+w->faceUp.x*dy+w->faceBack.x*.02f,
                           c.y+w->faceRight.y*dx+w->faceUp.y*dy+w->faceBack.y*.02f,
                           c.z+w->faceRight.z*dx+w->faceUp.z*dy+w->faceBack.z*.02f};
            pose.orientation=quatFromAxes(w->faceRight,w->faceUp,w->faceBack);
        }
        std::string error;
        if (!menuRuntime->flushMenuOverlay(pose,halfWidth,halfHeight,visible,error,nullptr,nullptr,rect))
        { G_XRCancelMenuPresentation(); sdlayer_xr_disableWorld(error.c_str()); return; }
    }
}

namespace
{
// Test-only target ownership, not a renderer/state recorder. Native reference
// emission copies the actual eye into another RGBA8/D24 array layer; frozen
// model or world MASK inputs are compared with replay on the untouched XR target.
struct NativeOracleTarget
{
    GLuint fbo=0, color=0, depth=0;
    GLint read=0, draw=0;
    NativeOracleTarget()
    {
        glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING,&read); glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING,&draw);
        GLint active, array; glGetIntegerv(GL_ACTIVE_TEXTURE,&active); glActiveTexture(GL_TEXTURE0);
        glGetIntegerv(GL_TEXTURE_BINDING_2D_ARRAY,&array);
        glGenFramebuffers(1,&fbo); glGenTextures(1,&color); glGenTextures(1,&depth);
        glBindTexture(GL_TEXTURE_2D_ARRAY,color);
        glTexImage3D(GL_TEXTURE_2D_ARRAY,0,GL_RGBA8,xdim,ydim,2,0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);
        glBindTexture(GL_TEXTURE_2D_ARRAY,depth);
        glTexImage3D(GL_TEXTURE_2D_ARRAY,0,GL_DEPTH24_STENCIL8,xdim,ydim,2,0,GL_DEPTH_STENCIL,GL_UNSIGNED_INT_24_8,nullptr);
        glBindTexture(GL_TEXTURE_2D_ARRAY,array); glActiveTexture(active);
    }
    bool copyEye(unsigned eye,std::string &error)
    {
        GLint source; glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING,&source);
        glBindFramebuffer(GL_READ_FRAMEBUFFER,source); glBindFramebuffer(GL_DRAW_FRAMEBUFFER,fbo);
        glFramebufferTextureLayer(GL_DRAW_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,color,0,eye);
        glFramebufferTextureLayer(GL_DRAW_FRAMEBUFFER,GL_DEPTH_STENCIL_ATTACHMENT,depth,0,eye);
        glDrawBuffer(GL_COLOR_ATTACHMENT0);
        if (glCheckFramebufferStatus(GL_DRAW_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE)
        { error="native reference framebuffer incomplete"; return false; }
        glBlitFramebuffer(0,0,xdim,ydim,0,0,xdim,ydim,GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT|GL_STENCIL_BUFFER_BIT,GL_NEAREST);
        glBindFramebuffer(GL_FRAMEBUFFER,fbo);
        if (glGetError()!=GL_NO_ERROR) { error="native reference target copy failed"; return false; }
        return true;
    }
    ~NativeOracleTarget()
    {
        glBindFramebuffer(GL_READ_FRAMEBUFFER,read); glBindFramebuffer(GL_DRAW_FRAMEBUFFER,draw);
        if (fbo) glDeleteFramebuffers(1,&fbo);
        if (color) glDeleteTextures(1,&color);
        if (depth) glDeleteTextures(1,&depth);
    }
};

bool prepareHandModel(HandModelSample &sample)
{
    auto weapon=sdlayer_xr_option("EDUKE32_XR_WEAPON");
    if (!G_XRModelsEnabled() || !weapon || Bstrcmp(weapon,"1") || !overlayEnabled()
        || !usemodels || aimHand()<0 || !localAimCamera() || !aimPoseUsable() || !handShotsRequested()
        || !G_VRShotValid(myconnectindex))
    {
        char why[96];
        Bsnprintf(why,sizeof(why),"prepareHandModel#1 local=%d pose=%d shots=%d ready=%d enabled=%d",
                  localAimCamera(),aimPoseUsable(),handShotsRequested(),G_VRShotValid(myconnectindex),
                  G_VRShotEnabled(myconnectindex));
        heldReject(why);
        return false;
    }
    if (effectiveWeaponFamily()==XRWeaponFamily::HudMapped ? !P_XRMappedPresentation(sample.presentation)
                                                          : !P_XRWeaponPresentation(sample.presentation)) { heldReject("prepareHandModel#2"); return false; }

    sample.context.palette=sample.presentation.palette;
    sample.context.shade=sample.presentation.shade;

    bool clamped;
    sample.shot=G_VRGetShotInput(myconnectindex);
    auto const &visual=crosshairViews.weapon;
    if (visual.selected)
    {
        if (!visual.valid || visual.hand!=aimHand() || visual.family!=sample.presentation.family) { heldReject("prepareHandModel#3"); return false; }
        sample.shot=visual.ray; sample.root=visual.root; sample.sector=visual.sector;
    }
    else if (!G_VRResolveShot(myconnectindex,sample.root,sample.sector,clamped)) { heldReject("prepareHandModel#4"); return false; }
    // Reuse the current native pickup DEF routing, loader and skin cache.
    // This opt-in contract uses the supplied 64-model-units/metre MD3 assets.
    int const modelTile=weaponModelTile(sample.presentation.family);
    int const tile=Ptile2tile(modelTile,sample.context.palette);
    sample.context.modelid=md_tilehasmodel(modelTile,sample.context.palette);
    sample.context.skinnum=tile2model[tile].skinnum;
    char name[16];
    int const counter=sample.presentation.counter;
    if (counter) Bsprintf(name,sample.presentation.family==XRWeaponFamily::AARpg
        || counter<(sample.presentation.family==XRWeaponFamily::AAPistol ? 6 : 5) ? "fire_%02d" : "reload_%02d",counter);
    else Bstrcpy(name,"rest");
    int frame=md3_getframeindex(sample.context.modelid,name);
    // Counter-keyed stock sets name the whole native cycle fire_NN and may
    // author only key counters: hold the nearest earlier authored frame.
    if (frame<0 && (sample.presentation.family==XRWeaponFamily::StockHeld
                    || sample.presentation.family==XRWeaponFamily::HudMapped
                    || (sample.presentation.family==XRWeaponFamily::StockPistol && md3_gettagposition(sample.context.modelid,"tag_support",&sample.grip))))
    {
        for (int c=counter;c>0 && frame<0;--c)
        {
            Bsprintf(name,"fire_%02d",c);
            frame=md3_getframeindex(sample.context.modelid,name);
        }
        if (frame<0) frame=std::max(0,md3_getframeindex(sample.context.modelid,"rest"));
    }
    if (frame<0 && counter==0 && sample.presentation.family==XRWeaponFamily::StockPistol) frame=0; // Legacy stock idle only.
    if (frame<0) { heldReject("prepareHandModel#5"); return false; } // Positive counters never silently substitute rest.
    sample.context.cframe=sample.context.nframe=frame;
    if (std::getenv("EDUKE32_XR_TEST_HELD"))
    {
        static int lastWeapon=-1, lastFrame=-1;
        int const weapon=g_player[myconnectindex].ps->curr_weapon;
        if (weapon!=lastWeapon || frame!=lastFrame)
            LOG_F(INFO,"OpenXR held model: weapon=%d family=%d model=%d frame=%d counter=%d.",weapon,
                  int(sample.presentation.family),sample.context.modelid,frame,counter);
        lastWeapon=weapon; lastFrame=frame;
    }
    if (!md3_gettagposition(sample.context.modelid,"tag_muzzle",&sample.pivot)
        || (!md3_gettagposition(sample.context.modelid,"tag_grip",&sample.grip)
            && sample.presentation.family!=XRWeaponFamily::StockHeld
            && sample.presentation.family!=XRWeaponFamily::HudMapped)) { heldReject("prepareHandModel#6"); return false; }
    sample.context.modelToEye[0]=sample.context.modelToEye[5]=sample.context.modelToEye[10]=sample.context.modelToEye[15]=1.f;
    if (!md3_preflightcontext(&sample.context))
    {
        static int reportedModel=-2;
        if (std::getenv("EDUKE32_XR_TEST_HELD") && reportedModel!=sample.context.modelid)
            LOG_F(INFO,"OpenXR held model rejected: model=%d frame=%d skin=%d (preflight).",
                  sample.context.modelid,frame,sample.context.skinnum);
        reportedModel=sample.context.modelid;
        { heldReject("prepareHandModel#7"); return false; }
    }
    if (visual.selected)
    {
        if (visual.model!=sample.context.modelid) { heldReject("prepareHandModel#8"); return false; }
        for (unsigned axis=0;axis<3;++axis) sample.basis[axis]=visual.basis[axis];
        return true;
    }

    XrVector3f forward={float(sample.shot.direction[0]),float(sample.shot.direction[1]),-float(sample.shot.direction[2])};
    float length=std::sqrt(dot(forward,forward));
    if (!(length>0.f)) { heldReject("prepareHandModel#9"); return false; }
    forward={forward.x/length,forward.y/length,forward.z/length};
    // Legacy aim-point presentation retains its existing orientation policy.
    auto const p=g_player[myconnectindex].ps;
    float const yaw=fix16_to_float(p->q16ang)*Pi/1024.f-aimYawOffset, co=std::cos(yaw), si=std::sin(yaw);
    auto const tracking=multiply(pitchRoll(nativePitch(p->q16horiz)-aimPitchOffset,gtang),inverseYaw);
    auto const r=rotate(multiply(tracking,rawInput.hands[aimHand()].aimPose.orientation),{1,0,0});
    XrVector3f right={-r.z*co-r.x*si,-r.z*si+r.x*co,r.y};
    float const along=dot(right,forward);
    right={right.x-forward.x*along,right.y-forward.y*along,right.z-forward.z*along};
    length=std::sqrt(dot(right,right));
    if (!(length>1e-4f)) { heldReject("prepareHandModel#10"); return false; }
    right={right.x/length,right.y/length,right.z/length};
    auto const up=cross(forward,right);
    XrVector3f const axes[3]={forward,right,up};
    for (int i=0;i<3;++i)
        sample.basis[i]={axes[i].x*UnitsPerMetre/64.f,axes[i].y*UnitsPerMetre/64.f,-axes[i].z*ZUnitsPerMetre/64.f};
    return true;
}

// A weapon that has a 3D model keeps it: when the exact shot-resolved presentation declines a
// frame (muzzle inside a wall, an unvalidated shot sample, an animation counter the adapter does
// not cover, shrunk or tinted HUD states...), the same model sits on the controller's grip/aim
// pose in its rest frame instead of falling back to the 2D sprite. Shots are unaffected (they
// keep their own validated path). Only states where Duke shows no weapon at all draw none.
bool prepareHandModelFallback(HandModelSample &sample, Camera const &body, eduke_xr::Runtime *runtime)
{
    auto const p=g_player[myconnectindex].ps;
    auto const option=sdlayer_xr_option("EDUKE32_XR_WEAPON");
    if (!G_XRModelsEnabled() || !usemodels || !option || Bstrcmp(option,"1") || aimHand()<0 || !overlayEnabled()
        || !recentered || !inputValid() || inputRuntime!=runtime || inputGeneration!=runtime->generation()
        || screenpeek!=myconnectindex || ud.overhead_on || ud.camerasprite>=0 || ud.drawweapon!=1
        || !(p->gm & MODE_GAME) || (p->gm & MODE_MENU) || p->newowner>=0 || p->over_shoulder_on || p->dead_flag
        || unsigned(p->i)>=MAXSPRITES || sprite[p->i].extra<=0 || p->holster_weapon || p->curr_weapon==KNEE_WEAPON
        // Duke puts the weapon away to tip, use an access card or punch a button.
        || p->tipincs || p->access_incs || p->fist_incs || p->knuckle_incs
        || unsigned(body.sector)>=unsigned(numsectors)) return false;
    auto const family=effectiveWeaponFamily();
    if (family==XRWeaponFamily::Unsupported) return false;
    int const modelTile=weaponModelTile(family);
    if (md_tilehasmodel(modelTile,0)<0) return false;
    if (!(family==XRWeaponFamily::HudMapped ? P_XRMappedPresentation(sample.presentation) : P_XRWeaponPresentation(sample.presentation)))
        sample.presentation={0,min<int32_t>(sprite[p->i].shade,24),0,0,family};
    sample.presentation.family=family;
    sample.presentation.counter=0;   // rest frame
    int const hand=aimHand();
    vec3f_t muzzle{}, palm{}; XrVector3f position; int model;
    if (!weaponMuzzle(family,hand,model,muzzle,palm,position) || model<0) return false;
    sample.context.palette=sample.presentation.palette;
    sample.context.shade=sample.presentation.shade;
    sample.context.modelid=md_tilehasmodel(modelTile,sample.context.palette);
    if (sample.context.modelid<0) { sample.context.palette=0; sample.context.modelid=model; }
    sample.context.skinnum=tile2model[Ptile2tile(modelTile,sample.context.palette)].skinnum;
    int const frame=std::max(0,md3_getframeindex(sample.context.modelid,"rest"));
    sample.context.cframe=sample.context.nframe=frame;
    sample.context.interpol=0.f;
    sample.pivot=muzzle;
    if (!md3_gettagposition(sample.context.modelid,"tag_grip",&sample.grip)) sample.grip=palm;
    auto const tracking=multiply(pitchRoll(nativePitch(body.horizon),body.roll),inverseYaw);
    float const yaw=fix16_to_float(body.angle)*Pi/1024.f, co=std::cos(yaw), si=std::sin(yaw);
    auto const toBuild=[&](XrVector3f v) {
        return XrVector3f{(-v.z*co-v.x*si)*UnitsPerMetre,(-v.z*si+v.x*co)*UnitsPerMetre,-v.y*ZUnitsPerMetre};
    };
    auto const delta=toBuild(rotate(tracking,{position.x-origin.x,position.y-origin.y,position.z-origin.z}));
    sample.root={body.pos.x+int32_t(std::lround(delta.x)),body.pos.y+int32_t(std::lround(delta.y)),body.pos.z+int32_t(std::lround(delta.z))};
    auto const orientation=multiply(tracking,rawInput.hands[hand].aimPose.orientation);
    XrVector3f const axes[]={{0,0,-1},{1,0,0},{0,1,0}};
    for (unsigned axis=0;axis<3;++axis)
    {
        auto const v=toBuild(rotate(orientation,axes[axis]));
        sample.basis[axis]={v.x/64.f,v.y/64.f,v.z/64.f};
    }
    sample.sector=body.sector;
    updatesector(sample.root.x,sample.root.y,&sample.sector);
    if (sample.sector<0) sample.sector=body.sector;
    sample.context.modelToEye[0]=sample.context.modelToEye[5]=sample.context.modelToEye[10]=sample.context.modelToEye[15]=1.f;
    if (!md3_preflightcontext(&sample.context)) return false;
    if (std::getenv("EDUKE32_XR_TEST_HELD"))
    {
        static int lastWeapon=-1;
        if (p->curr_weapon!=lastWeapon) LOG_F(INFO,"OpenXR held model fallback: weapon=%d family=%d model=%d.",p->curr_weapon,int(family),sample.context.modelid);
        lastWeapon=p->curr_weapon;
    }
    return true;
}

void worldModelMatrix(WorldModelSample &sample, Eye const &eye)
{
    float toEye[16]; polymost_xrRelativeWorldToEye(toEye);
    float local[16]={};
    for (int column=0;column<3;++column)
    {
        local[column*4]=sample.basis[column].x;
        local[column*4+1]=sample.basis[column].y;
        local[column*4+2]=sample.basis[column].z;
    }
    local[12]=float(int64_t(sample.root.x)-eye.camera.pos.x);
    local[13]=float(int64_t(sample.root.y)-eye.camera.pos.y);
    local[14]=float(int64_t(sample.root.z)-eye.camera.pos.z);
    float const pivot[3]={sample.pivot.x,sample.pivot.y,sample.pivot.z};
    for (int column=0;column<3;++column)
        for (int row=0;row<3;++row) local[12+row]-=local[column*4+row]*pivot[column];
    local[15]=1.f;
    for (int column=0;column<4;++column)
        for (int row=0;row<4;++row)
        {
            sample.context.modelToEye[column*4+row]=0;
            for (int k=0;k<4;++k) sample.context.modelToEye[column*4+row]+=toEye[k*4+row]*local[column*4+k];
        }
}
} // namespace

static bool weaponReceiptOwned()
{
    return handModelReceipt.runtime && handModelReceipt.runtime==menuRuntime && menuRuntime
        && handModelReceipt.generation==menuGeneration && menuRuntime->generation()==menuGeneration
        && handModelReceipt.serial==pendingFrame.serial && handModelReceipt.player==screenpeek
        && menuRuntime->menuOverlayTargetBound();
}

static bool weaponReceiptMatches()
{
    XRWeaponPresentation fresh;
    auto const &saved=handModelReceipt.presentation;
    return weaponReceiptOwned() && P_XRWeaponPresentation(fresh) && fresh.family==saved.family
        && fresh.palette==saved.palette && fresh.shade==saved.shade
        && fresh.counter==saved.counter && fresh.reloading==saved.reloading;
}

static bool suppressWeaponTile(int32_t tile, int32_t uniqueID);
bool G_XRSuppressWeaponTile(int32_t tile, int32_t uniqueID)
{
    // Receipts first (they validate the held model), then the blanket rule.
    bool const handled=suppressWeaponTile(tile,uniqueID);
    return handled || (handModelReceipt.weaponSegment && handModelReceipt.hideNative);
}
static bool suppressWeaponTile(int32_t tile, int32_t uniqueID)
{
    // The weapon wheel hides the held weapon (3D model and native weapon ART) while it is open.
    if (wheel.open && handModelReceipt.weaponSegment) return true;
    // A generic held model replaces the whole native weapon display segment,
    // including its hands; native animation and CON state still run.
    if (handModelReceipt.presentation.family==XRWeaponFamily::StockHeld)
    {
        if (!handModelReceipt.runtime || !handModelReceipt.weaponSegment) return false;
        if (!weaponReceiptOwned()) { handModelReceipt.mismatch=true; return false; }
        handModelReceipt.seen|=1;
        return true;
    }
    if (handModelReceipt.presentation.family!=XRWeaponFamily::StockPistol) return false;
    int const role=uniqueID==W_PISTOL ? 1 : uniqueID==W_PISTOL_CLIP ? 2 : uniqueID==W_PISTOL_HAND ? 4 : 0;
    if (!handModelReceipt.runtime || !role) return false;
    // Classify claimed roles first: a wrong auxiliary tile must latch failure,
    // even when the body draw has already consumed its part of the receipt.
    bool const validTile=role==1 ? (tile==FIRSTGUN || tile==FIRSTGUN+1 || tile==FIRSTGUN+2
                                         || tile==FIRSTGUN+4 || tile==FIRSTGUN+5 || tile==FIRSTGUNRELOADWIDE)
                                 : tile==FIRSTGUN+(role==2 ? 6 : 8);
    if (!validTile || (handModelReceipt.seen&role) || !weaponReceiptMatches())
    { handModelReceipt.mismatch=true; return false; }
    handModelReceipt.seen|=role;
    return true;
}

static bool consumeAAWeaponTile(int32_t tile,int32_t uniqueID,int32_t shade,int32_t palette,
                                int32_t flags,int32_t angle,int32_t alpha,int32_t blend);
// Every rotatesprite during the native weapon display segment: remember the
// mapped HUD tile, and hide the segment while its HUD-mapped model is shown.
static bool weaponSegmentTileReceipt(int32_t tile,int32_t uniqueID,int32_t shade,int32_t palette,
                                     int32_t flags,int32_t angle,int32_t alpha,int32_t blend);
static bool weaponSegmentTile(int32_t tile,int32_t uniqueID,int32_t shade,int32_t palette,
                              int32_t flags,int32_t angle,int32_t alpha,int32_t blend)
{
    bool const handled=weaponSegmentTileReceipt(tile,uniqueID,shade,palette,flags,angle,alpha,blend);
    return handled || (handModelReceipt.weaponSegment && handModelReceipt.hideNative);
}
static bool weaponSegmentTileReceipt(int32_t tile,int32_t uniqueID,int32_t shade,int32_t palette,
                                     int32_t flags,int32_t angle,int32_t alpha,int32_t blend)
{
    auto &receipt=handModelReceipt;
    if (wheel.open && receipt.weaponSegment) return true;   // weapon wheel open: no held weapon
    if (aaWeaponFamily(receipt.presentation.family) && receipt.runtime)
        return consumeAAWeaponTile(tile,uniqueID,shade,palette,flags,angle,alpha,blend);
    if (receipt.weaponSegment && std::getenv("EDUKE32_XR_TEST_HELD"))
    {
        static std::vector<int32_t> reported;
        if (reported.size()<64 && std::find(reported.begin(),reported.end(),tile)==reported.end())
        {
            reported.push_back(tile);
            LOG_F(INFO,"OpenXR HUD tile: tile=%d segment=%d mapped=%d weapon=%d.",tile,int(receipt.weaponSegment),
                  (unsigned)tile<hudModelMap.size() ? hudModelMap[tile] : -1,g_player[myconnectindex].ps->curr_weapon);
        }
    }
    if (!receipt.weaponSegment) return false;
    hudSegmentObserved=true;
    if ((unsigned)tile<hudModelMap.size() && hudModelMap[tile]>=0 && hudObservedModel<0)
        hudObservedModel=hudModelMap[tile];
    if (receipt.presentation.family==XRWeaponFamily::HudMapped && receipt.runtime && weaponReceiptOwned())
    {
        receipt.seen|=1;
        return true;
    }
    return false;
}

static bool consumeAAWeaponTile(int32_t tile,int32_t uniqueID,int32_t shade,int32_t palette,
                                int32_t flags,int32_t angle,int32_t alpha,int32_t blend)
{
    auto &receipt=handModelReceipt;
    auto const &saved=receipt.presentation;
    if (!receipt.runtime || !aaWeaponFamily(saved.family)) return false;
    bool const rpg=saved.family==XRWeaponFamily::AARpg;
    // Classify claimed roles before validation, including a wrong tile carrying
    // the RPG's unique ID after its valid body already consumed the receipt.
    int const role=rpg ? ((tile>=10228 && tile<=10230) || uniqueID==24 ? 1 : 0)
        : tile==FIRSTGUN+6 ? 2 :
          (tile==FIRSTGUN || tile==FIRSTGUN+1 || tile==FIRSTGUN+2 || tile==FIRSTGUN+4
           || tile==FIRSTGUN+5 || tile==FIRSTGUNRELOADWIDE) ? 1 : 0;
    if (!role) return false;
    XRWeaponPresentation fresh;
    int const counter=saved.counter;
    int const bodyTile=rpg ? 10228 : FIRSTGUN+(counter<6 ? 0 : counter<10 ? 4 : 5);
    bool const validRole=role==1 ? tile==bodyTile && uniqueID==(rpg ? 24 : PISTOL_WEAPON)
        : counter>=10 && counter<20 && uniqueID==0;
    int const expectedFlags=rpg ? (2|4096) : (2|2048|4096|(counter>=6 ? 512 : 0));
    bool const valid=receipt.weaponSegment && weaponReceiptOwned() && !(receipt.seen&role)
        && validRole && palette==saved.palette && shade==saved.shade
        && flags==expectedFlags && !angle && !alpha && !blend
        && P_XRWeaponPresentation(fresh) && fresh.family==saved.family
        && fresh.palette==saved.palette && fresh.shade==saved.shade
        && fresh.counter==saved.counter && fresh.reloading==saved.reloading;
    if (!valid)
    {
        receipt.mismatch=true;
        if (std::getenv("EDUKE32_XR_TEST_MODELS"))
            LOG_F(INFO,"OpenXR AA hand model draw mismatch: tile=%d id=%d shade=%d palette=%d flags=%d angle=%d alpha=%d blend=%d segment=%d roles=%u.",
                  tile,uniqueID,shade,palette,flags,angle,alpha,blend,receipt.weaponSegment,unsigned(receipt.seen));
        return false;
    }
    receipt.seen|=role;
    if (std::getenv("EDUKE32_XR_TEST_MODELS"))
    {
        static unsigned reported;
        if (reported++<3 || !modelAnimationCapture.empty())
            LOG_F(INFO,"OpenXR AA hand model receipt: serial=%llu tile=%d shade=%d palette=%d roles=%u valid=1.",
                  (unsigned long long)receipt.serial,tile,shade,palette,unsigned(receipt.seen));
    }
    return true;
}

static bool weaponReceiptComplete()
{
    auto const &saved=handModelReceipt.presentation;
    if (saved.family==XRWeaponFamily::StockHeld || saved.family==XRWeaponFamily::HudMapped)
        return true; // Some counters draw no ART at all.
    unsigned const required=saved.family==XRWeaponFamily::AAPistol && saved.counter>=10 && saved.counter<20 ? 3 : 1;
    return (handModelReceipt.seen&required)==required;
}

void G_XRResetAim(int playerNum)
{
    if (playerNum==myconnectindex) crosshairViews.weapon.valid=false;
    if (playerNum!=myconnectindex || aimHand()==-2) return;
    aimYawOffset=aimPitchOffset=0;
    aimPoseWasValid=false;
    recentered=trackingRebase=lastHeadValid=false;
}

bool G_XRTrackedPitchOwner() { return localAimCamera() && !stickPitchAllowed(); }

int G_XRListenerAngle(int fallback)
{
    // The native body angle follows the aim source; recover the head's yaw in
    // the same frame G_XRApplyAim uses (body reference = q16ang - aim offset).
    if (!localAimCamera() || !recentered || !inputValid() || !rawInput.headValid || !validPose(rawInput.headPose)) return fallback;
    auto const p=g_player[myconnectindex].ps;
    auto const forward=rotate(multiply(inverseYaw,rawInput.headPose.orientation),{0,0,-1});
    if (std::hypot(forward.x,forward.z)<1e-4f) return fallback;
    float const yaw=fix16_to_float(p->q16ang)*Pi/1024.f-aimYawOffset+std::atan2(forward.x,-forward.z);
    return int(std::lround(yaw*1024.f/Pi))&2047;
}

void G_XRApplyAim(input_t &input, bool yawAllowed, bool pitchAllowed)
{
    if (!localAimCamera()) return;
    shotLookAllowed=yawAllowed && pitchAllowed;
    // Native centering must not reactivate merely because a tracked source is
    // temporarily unavailable. The XR context retains look-mode ownership.
    input.bits|=uint32_t(1)<<SK_AIMMODE;
    input.extbits &= ~(BIT(EK_GAMEPAD_CENTERING)|BIT(EK_GAMEPAD_AIM_ASSIST));
    if (pendingSnapTurn!=0.f && yawAllowed)
        input.q16avel=fix16_sadd(input.q16avel,fix16_from_float(pendingSnapTurn*1024.f/Pi));
    pendingSnapTurn=0.f;
    if (!aimPoseUsable()) return;
    if (!recentered) setTrackingReference(rawInput.headPose);
    auto const p=g_player[myconnectindex].ps;
    // Recover the independent body from native authority, retaining native
    // joystick/mouse turning. Tracking deltas are displacements, not rates.
    float const bodyYaw=fix16_to_float(p->q16ang)*Pi/1024.f-aimYawOffset+fix16_to_float(input.q16avel)*Pi/1024.f;
    float const oldPitch=nativePitch(p->q16horiz);
    float const nativePitchDelta=fix16_to_float(input.q16horz)*Pi/512.f;
    // Without stick pitch the head owns pitch entirely: keep the body level,
    // so a native horizon excursion before tracking starts cannot tilt the
    // world permanently.
    float const bodyPitch=stickPitchAllowed()
        ? clampNativePitch(oldPitch-aimPitchOffset+(pitchAllowed ? nativePitchDelta : 0.f)) : 0.f;
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
    crosshairViews.weapon.valid=false;
    // A live session with temporarily lost tracking remains fail-closed.
    // Terminal initialization/presentation failure returns to native flat
    // controls, so an invalid hand pose must not suppress keyboard fire there.
    if (handShotsRequested() && videoGetRenderMode()==REND_POLYMOST && sdlayer_xr_worldActive())
    {
        input.flags=VRShotEnabled;
        int const hand=aimHand();
        if (hand>=0 && localAimCamera() && aimPoseUsable() && recentered && shotLookAllowed
            && !shotReferenceInvalidated && !(blockedInputButtons[1]&(eduke_xr::ButtonSelect|eduke_xr::ButtonStickClick)))
        {
            auto const p=g_player[myconnectindex].ps;
            float const bodyYaw=fix16_to_float(p->q16ang)*Pi/1024.f-aimYawOffset;
            float const co=std::cos(bodyYaw), si=std::sin(bodyYaw);
            auto const tracking=multiply(pitchRoll(nativePitch(p->q16horiz)-aimPitchOffset,gtang),inverseYaw);
            auto const &pose=rawInput.hands[hand].aimPose;
            XrVector3f position=pose.position;
            auto const family=mountedWeaponFamily();
            int model=-1;
            bool calibrated=true;
            if (family!=XRWeaponFamily::Unsupported)
            {
                vec3f_t muzzle{}, palm{};
                calibrated=weaponMuzzle(family,hand,model,muzzle,palm,position);
            }
            auto const local=rotate(tracking,{position.x-origin.x,position.y-origin.y,position.z-origin.z});
            auto const forward=rotate(multiply(tracking,pose.orientation),{0,0,-1});
            auto const look=rotate(multiply(tracking,rawInput.headPose.orientation),{0,0,-1});
            float const head[3]={-look.z*co-look.x*si,-look.z*si+look.x*co,-look.y};
            float const offsets[3]={(-local.z*co-local.x*si)*UnitsPerMetre,(-local.z*si+local.x*co)*UnitsPerMetre,-local.y*ZUnitsPerMetre};
            float const direction[3]={-forward.z*co-forward.x*si,-forward.z*si+forward.x*co,-forward.y};
            bool bounded=calibrated;
            for (int i=0;i<3;++i)
            {
                bounded=bounded && std::isfinite(offsets[i]) && std::fabs(offsets[i])<32767.f;
                if (bounded) input.offset[i]=int16_t(std::lround(offsets[i]));
                input.direction[i]=int16_t(std::lround(std::max(-1.f,std::min(1.f,direction[i]))*32767.f));
                input.head[i]=int16_t(std::lround(std::max(-1.f,std::min(1.f,head[i]))*32767.f));
            }
            input.flags|=VRShotValid;
            if (xrThrow.pending && physicalThrowEnabled())
            {
                // Throw direction and speed come from the hand's motion, not its aim.
                auto const v=rotate(tracking,xrThrow.velocity);
                float const d[3]={-v.z*co-v.x*si,-v.z*si+v.x*co,-v.y};
                float const length=std::sqrt(d[0]*d[0]+d[1]*d[1]+d[2]*d[2]);
                if (length>1e-3f)
                {
                    for (int i=0;i<3;++i) input.direction[i]=int16_t(std::lround(d[i]/length*32767.f));
                    int const units=std::max(1,std::min(15,int(std::lround(xrThrow.speed/VRShotThrowStep))));
                    input.flags|=uint8_t(units<<VRShotThrowShift);
                }
                xrThrow.pending=false;
            }
            if (!bounded || !G_VRValidateShot(input))
            {
                char why[96];
                Bsnprintf(why,sizeof(why),"shotInput calibrated=%d bounded=%d family=%d",calibrated,bounded,int(family));
                heldReject(why);
                input={}; input.flags=VRShotEnabled;
            }
            else
            {
                bool const weaponDiagnostic=std::getenv("EDUKE32_XR_TEST_WEAPON_MOUNT")!=nullptr;
                if ((weaponDiagnostic || (family!=XRWeaponFamily::Unsupported
                    && std::getenv("EDUKE32_XR_TEST_PISTOL_MOUNT"))) && p->kickback_pic>0 && p->kickback_pic<=26)
                {
                    static unsigned samples;
                    if (samples++<128)
                    {
                        auto const &g=rawInput.hands[hand].gripPose.position;
                        auto const &q=pose.orientation; auto const &a=pose.position;
                        LOG_F(INFO,"OpenXR %s mount input: clock=%u counter=%d hand=%d grip=%.9g,%.9g,%.9g aim=%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g origin=%.9g,%.9g,%.9g tracking=%.9g,%.9g,%.9g,%.9g yaw=%.9g offset=%d,%d,%d.",
                              weaponDiagnostic ? "weapon" : "pistol",unsigned(totalclock),p->kickback_pic,hand,g.x,g.y,g.z,q.x,q.y,q.z,q.w,a.x,a.y,a.z,
                              origin.x,origin.y,origin.z,tracking.x,tracking.y,tracking.z,tracking.w,bodyYaw,
                              input.offset[0],input.offset[1],input.offset[2]);
                    }
                }
            }
        }
        else if (std::getenv("EDUKE32_XR_TEST_HELD"))
        {
            char why[128];
            Bsnprintf(why,sizeof(why),"shotInput hand=%d local=%d pose=%d recentered=%d look=%d invalidated=%d blocked=%u",
                      hand,localAimCamera(),aimPoseUsable(),recentered,shotLookAllowed,shotReferenceInvalidated,
                      blockedInputButtons[1]);
            heldReject(why);
        }
    }
    if ((input.flags & VRShotEnabled) && physicalThrowEnabled())
    {
        input.flags|=VRShotPhysical;
        if (xrThrow.detonatePending) { input.flags|=VRShotDetonate; xrThrow.detonatePending=false; }
    }
    if (std::getenv("EDUKE32_XR_TEST_SHOTS") && (input.flags & (VRShotThrowMask|VRShotDetonate)))
        LOG_F(INFO,"VR physical throw sample: speedUnits=%d detonate=%d direction=%d,%d,%d.",(input.flags&VRShotThrowMask)>>VRShotThrowShift,
              int(!!(input.flags&VRShotDetonate)),input.direction[0],input.direction[1],input.direction[2]);
    G_VRSetShotInput(myconnectindex,input);
    shotReferenceInvalidated=false; // One native sample conveys the unknown reference reset.
}

// Yaw of a tracked pose relative to the recentered body reference, radians.
static bool trackedYaw(XrPosef const &pose, float &yaw)
{
    if (!validPose(pose) || !recentered) return false;
    auto const forward=rotate(multiply(inverseYaw,pose.orientation),{0,0,-1});
    if (std::hypot(forward.x,forward.z)<1e-3f) return false;
    yaw=std::atan2(forward.x,-forward.z);
    return true;
}

fix16_t G_XRMovementAngle(fix16_t nativeAngle)
{
    if (!localAimCamera()) return nativeAngle;
    float offset=-aimYawOffset; // body yaw
    // Stick movement follows the head (default in play mode) or the left
    // controller, like RazeXR; "body" keeps the recentered body direction.
    auto const mode=sdlayer_xr_option("EDUKE32_XR_MOVE");
    float yaw;
    if (mode && !Bstrcmp(mode,"head") && inputValid() && rawInput.headValid && trackedYaw(rawInput.headPose,yaw))
        offset+=yaw;
    else if (mode && !Bstrcmp(mode,"hand") && inputValid() && rawInput.hands[0].aimValid && trackedYaw(rawInput.hands[0].aimPose,yaw))
        offset+=yaw;
    fix16_t const angle=(nativeAngle+fix16_from_float(offset*1024.f/Pi)) & 0x7FFFFFF;
    if (std::getenv("EDUKE32_XR_TEST_MOVE"))
    {
        static unsigned ticks;
        auto const p=g_player[myconnectindex].ps;
        if (ticks++%2==0)
            LOG_F(INFO,"OpenXR move: native=%.3f move=%.3f pos=%d,%d,%d.",fix16_to_float(nativeAngle),
                  fix16_to_float(angle),p->pos.x,p->pos.y,p->pos.z);
    }
    return angle;
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
        if (!G_VRShotValid(myconnectindex)) return false;
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
    crosshairViews.weapon.valid=false;
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
    crosshairViews.valid=false;
    polymost_xrWeaponTileConsumer=nullptr;
    handModelReceipt={};
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

static void beginMenuPresentation(bool nativeScreen)
{
    char const *enabled=sdlayer_xr_option("EDUKE32_XR_UI");
    bool const overlay=!nativeScreen && overlayEnabled() && presentationRuntime;
    if (!enabled || (Bstrcmp(enabled,"1") && Bstrcmp(enabled,"2"))
        || (!nativeScreen && !overlay && (g_player[myconnectindex].ps->gm & MODE_GAME))
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

void G_XRBeginMenuPresentation() { beginMenuPresentation(false); }
// CON startscreen owns a flat screen even during MODE_GAME/level entry.
// Reuse the acquired frame and native UI target without arming a world draw.
void G_XRBeginScreenPresentation() { beginMenuPresentation(true); }

static SpriteBounds weaponCardBounds;
static void weaponCardSprite(float x0,float y0,float x1,float y1) { weaponCardBounds.add(x0,y0,x1,y1); }

bool G_XRBeginWeapon()
{
    auto const enabled=sdlayer_xr_option("EDUKE32_XR_WEAPON");
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
    if (auto prefix=!weaponAnimationCapture.empty() ? weaponAnimationCapture.c_str()
                    : worldFrames==59 ? std::getenv("EDUKE32_XR_WEAPON_OUTPUT") : nullptr)
        {
            std::string before=std::string(prefix)+"-before";
            if (!menuRuntime->captureFrame(before.c_str(),false,error,true))
            { G_XRCancelMenuPresentation(); sdlayer_xr_disableWorld(error.c_str()); return false; }
        }
    handModelReceipt.weaponSegment=true;
    handModelReceipt.hideNative=nativeWeaponHidden();
    weaponCardBounds=SpriteBounds{};
    polymost_xrSpriteBounds=weaponCardSprite;
    if (std::getenv("EDUKE32_XR_TEST_HELD"))
    {
        static int reported=-1;
        int const state=loadHudModelMap() ? int(hudModelMap.size()) : 0;
        if (reported!=state) LOG_F(INFO,"OpenXR weapon segment: hud map tiles=%d.",state);
        reported=state;
    }
    if (loadHudModelMap())
    {
        hudObservedModel=-1; hudSegmentObserved=false;
        polymost_xrWeaponTileConsumer=weaponSegmentTile;
    }
    return true;
}

bool G_XRHideHudWeapon()
{
    auto const enabled=sdlayer_xr_option("EDUKE32_XR_WEAPON");
    return enabled && !Bstrcmp(enabled,"1") && sdlayer_xr_worldActive();
}

void G_XREndWeapon(bool captured)
{
    handModelReceipt.weaponSegment=false;
    polymost_xrSpriteBounds=nullptr;
    if (!hudModelMap.empty() && hudSegmentObserved)
    {
        // A newly seen mapped tile (or a weapon change) updates the prediction.
        int const weapon=g_player[myconnectindex].ps->curr_weapon;
        if (hudObservedModel>=0) { hudPredictedModel=hudObservedModel; hudPredictedWeapon=weapon; }
        else if (weapon!=hudPredictedWeapon) hudPredictedModel=-1;
        hudSegmentObserved=false;
    }
    if (captured)
        if (auto test=std::getenv("EDUKE32_XR_TEST_WEAPON_NESTED"))
        {
            static bool injected;
            if (!injected && (!Bstrcmp(test,"1") || (!Bstrcmp(test,"2") && worldFrames==59)))
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
    if (crosshairViews.weapon.selected)
    {
        visible=visible && weaponVisualOwned();
        if (visible) pose=crosshairViews.weapon.pose;
    }
    else if (handShotsRequested() && G_VRHandShotFeature(myconnectindex))
    {
        vec3_t position; int16_t sector; bool clamped;
        visible=visible && G_VRResolveShot(myconnectindex,position,sector,clamped);
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
    // RazeXR-style 2D fallback: only the drawn native sprites (cropped to their bounds) form a
    // card held in the hand, its bottom edge at the controller and facing back along the aim;
    // at 0.6 m per screen height, as large as the native weapon reads on a flat screen.
    float rect[4]={0,0,1,1};
    visible=visible && !weaponCardBounds.empty();
    float halfWidth=.01f, halfHeight=.01f;
    if (visible)
    {
        weaponCardBounds.uv(rect);
        float const metresPerPixel=.6f/ydim;
        halfWidth=std::max(.01f,(rect[2]-rect[0])*xdim*metresPerPixel*.5f);
        halfHeight=std::max(.01f,(rect[3]-rect[1])*ydim*metresPerPixel*.5f);
        // The sprite's horizontal centre sits over the hand; ART is drawn right of centre
        // for a right-handed weapon, so this also keeps a left-handed card in its own hand.
        auto const offset=rotate(pose.orientation,{0.f,halfHeight-.03f,-.04f});
        pose.position.x+=offset.x; pose.position.y+=offset.y; pose.position.z+=offset.z;
    }
    char const *prefix=!weaponAnimationCapture.empty() ? weaponAnimationCapture.c_str()
        : worldFrames==59 ? std::getenv("EDUKE32_XR_WEAPON_OUTPUT") : nullptr;
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
    if (!menuRuntime->flushMenuOverlay(pose,halfWidth,halfHeight,visible,error,prefix,nullptr,rect))
    { G_XRCancelMenuPresentation(); sdlayer_xr_disableWorld(error.c_str()); }
}

// Wrist HUD: the native mini status bar is drawn as one overlay segment and split by screen
// half; the left half (health, armour) becomes a watch face on the left wrist, the right half
// (ammo, inventory) one on the right wrist. Quotes, voice and menus stay on the head panel.
static bool wristHudRequested()
{
    auto const value=sdlayer_xr_option("EDUKE32_XR_WRIST_HUD");
    return value && !Bstrcmp(value,"1");
}
static SpriteBounds wristBounds[2];
static bool wristSegment;
static void wristSprite(float x0,float y0,float x1,float y1)
{
    wristBounds[(x0+x1)*.5f<xdim*.5f ? 0 : 1].add(x0,y0,x1,y1);
}
bool G_XRWristHudActive() { return wristSegment; }

bool G_XRBeginWristHud()
{
    auto const p=g_player[myconnectindex].ps;
    if (!wristHudRequested() || !menuRuntime || menuRuntime->generation()!=menuGeneration || !menuRuntime->menuOverlayTargetBound()
        || !inputValid() || screenpeek!=myconnectindex || ud.overhead_on || !(p->gm & MODE_GAME))
    {
        static bool reported;
        if (!reported && std::getenv("EDUKE32_XR_TEST_HELD") && wristHudRequested())
            LOG_F(INFO,"OpenXR wrist HUD skipped: runtime=%d bound=%d input=%d.",menuRuntime!=nullptr,
                  menuRuntime && menuRuntime->menuOverlayTargetBound(),int(inputValid()));
        reported=true;
        return false;
    }
    if (!flushHeadPanel()) return false;   // HUD drawn so far stays on the head panel
    wristBounds[0]=wristBounds[1]=SpriteBounds{};
    polymost_xrSpriteBounds=wristSprite;
    wristSegment=true;
    return true;
}

void G_XREndWristHud(bool captured)
{
    polymost_xrSpriteBounds=nullptr;
    wristSegment=false;
    if (!captured || !menuRuntime || menuRuntime->generation()!=menuGeneration || !menuRuntime->menuOverlayTargetBound()) return;
    // Same scale on both wrists: the wider half spans 13 cm.
    float const widest=std::max({wristBounds[0].empty() ? 0.f : wristBounds[0].x1-wristBounds[0].x0,
                                 wristBounds[1].empty() ? 0.f : wristBounds[1].x1-wristBounds[1].x0,1.f});
    float const metresPerPixel=std::min(.10f/widest,.3f/ydim);
    if (std::getenv("EDUKE32_XR_TEST_HELD"))
    {
        static int logged;
        if (logged++%300==0)
            LOG_F(INFO,"OpenXR wrist HUD: left=%.0f,%.0f-%.0f,%.0f right=%.0f,%.0f-%.0f,%.0f hands=%d,%d.",
                  wristBounds[0].x0,wristBounds[0].y0,wristBounds[0].x1,wristBounds[0].y1,
                  wristBounds[1].x0,wristBounds[1].y0,wristBounds[1].x1,wristBounds[1].y1,
                  int(rawInput.hands[0].aimValid),int(rawInput.hands[1].aimValid));
    }
    std::string error;
    for (unsigned hand=0;hand<2;++hand)
    {
        auto const &input=rawInput.hands[hand];
        float rect[4]={0,0,1,1};
        bool visible=!wristBounds[hand].empty() && input.aimValid && validPose(input.aimPose)
            && rawInput.headValid && !wheel.open && !gadgetWheel.open;
        float halfWidth=.01f, halfHeight=.01f;
        XrPosef pose=input.aimPose;
        if (visible)
        {
            wristBounds[hand].uv(rect);
            halfWidth=(rect[2]-rect[0])*xdim*metresPerPixel*.5f;
            halfHeight=(rect[3]-rect[1])*ydim*metresPerPixel*.5f;
            // On top of the wrist behind the controller, read like a watch with the arm across the
            // chest: text along the forearm (left to right as seen), its top edge away from you,
            // the face tilted 35 degrees toward the eyes. Panel axes in the aim frame:
            // left X=-Z Y=-X, right X=+Z Y=+X, normal +Y.
            auto const offset=rotate(pose.orientation,{0.f,.035f,.11f});
            pose.position.x+=offset.x; pose.position.y+=offset.y; pose.position.z+=offset.z;
            XrQuaternionf const face=hand==0 ? XrQuaternionf{-.5f,.5f,.5f,.5f} : XrQuaternionf{-.5f,-.5f,-.5f,.5f};
            float const half=Pi*35.f/360.f;
            pose.orientation=multiply(multiply(pose.orientation,face),XrQuaternionf{std::sin(half),0,0,std::cos(half)});
        }
        if (!menuRuntime->flushMenuOverlay(pose,halfWidth,halfHeight,visible,error,nullptr,nullptr,rect,hand==0))
        { G_XRCancelMenuPresentation(); sdlayer_xr_disableWorld(error.c_str()); return; }
    }
}

static char const *crosshairCapturePrefix()
{
    // Explicit diagnostic frame selection lets native mod entry finish before
    // readback. It never changes simulation or crosshair presentation timing.
    auto const requested=std::getenv("EDUKE32_XR_CROSSHAIR_FRAME");
    if (!crosshairViews.diagnosticCrosshairPrefix.empty()) return crosshairViews.diagnosticCrosshairPrefix.c_str();
    return worldFrames+1==(requested ? std::strtoull(requested,nullptr,10) : 60)
        ? std::getenv("EDUKE32_XR_CROSSHAIR_OUTPUT") : nullptr;
}

bool G_XRBeginCrosshair()
{
    if (!crosshairViews.valid || !menuRuntime || menuRuntime->generation()!=menuGeneration || !menuRuntime->menuOverlayTargetBound()) return false;
    // Flush the preceding HUD at its original depth/order. Only the native
    // crosshair event and its optional returned tile enter this spatial segment.
    XrPosef panel=rawInput.headPose;
    auto const offset=rotate(panel.orientation,{0,0,-eduke_xr::PanelDistance});
    panel.position.x+=offset.x; panel.position.y+=offset.y; panel.position.z+=offset.z;
    std::string error;
    if (!menuRuntime->flushMenuOverlay(panel,eduke_xr::PanelHalfWidth,eduke_xr::PanelHalfWidth*float(ydim)/xdim,
                                       rawInput.headValid && validPose(rawInput.headPose),error))
    { G_XRCancelMenuPresentation(); sdlayer_xr_disableWorld(error.c_str()); return false; }
    if (auto prefix=crosshairCapturePrefix())
        {
            std::string before=std::string(prefix)+"-before";
            if (!menuRuntime->captureFrame(before.c_str(),false,error,true))
            { G_XRCancelMenuPresentation(); sdlayer_xr_disableWorld(error.c_str()); return false; }
        }
    return true;
}

void G_XREndCrosshair(bool captured, vec2_t position, int32_t scale, int32_t flags, bool eventOnly)
{
    if (!captured || !crosshairViews.valid || !menuRuntime || menuRuntime->generation()!=menuGeneration || !menuRuntime->menuOverlayTargetBound()) return;
    auto const p=g_player[myconnectindex].ps;
    auto const body=crosshairViews.weapon.selected ? crosshairViews.body : aimBodyCamera(camera());
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
    if (crosshairViews.weapon.selected)
    {
        auto const &visual=crosshairViews.weapon;
        visible=visible && weaponVisualOwned();
        start=visual.root; sector=visual.sector; clamped=visual.clamped;
        ray={visual.ray.direction[0],visual.ray.direction[1],visual.ray.direction[2]*16};
    }
    else if (handShotsRequested() && G_VRHandShotFeature(myconnectindex))
    {
        visible=visible && aimPoseUsable() && G_VRResolveShot(myconnectindex,start,sector,clamped);
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
        // CON-only reticles use the logical full-screen centre with native
        // rotatesprite bounds (0,0,xdim,ydim). Their authored relative offsets
        // stay intact. Stock returned tiles retain look/returnvar/viewport and
        // FURY conventions; those do not describe independently drawn CON ART.
        auto const anchor=eventOnly
            ? polymost_xrRotateSpriteAnchor({160<<16,100<<16},65536,RS_AUTO,{xdim,ydim})
            : polymost_xrRotateSpriteAnchor(position,scale,flags,{windowxy1.x+windowxy2.x,windowxy1.y+windowxy2.y});
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
        if (crosshairCapturePrefix())
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
    char const *prefix=crosshairCapturePrefix();
    std::string error;
    if (!menuRuntime->flushMenuOverlay(unused,1,1,visible,error,prefix,&matrices[0][0]))
    { G_XRCancelMenuPresentation(); sdlayer_xr_disableWorld(error.c_str()); }
    else if (prefix)
        LOG_F(INFO,"OpenXR crosshair capture: world=%llu serial=%llu.",
              (unsigned long long)(worldFrames+1),(unsigned long long)pendingFrame.serial);
}

void G_XRArmMenuPresentation()
{
    if (handModelReceipt.runtime && worldFrames==59)
        if (auto test=std::getenv("EDUKE32_XR_TEST_RECEIPT"))
        {
            if (!Bstrcmp(test,"invalid-aux")) G_XRSuppressWeaponTile(FIRSTGUN+7,W_PISTOL_CLIP);
            else if (!Bstrcmp(test,"duplicate")) G_XRSuppressWeaponTile(FIRSTGUN,W_PISTOL);
        }
    if (handModelReceipt.runtime && !modelAnimationCapture.empty())
        LOG_F(INFO,"OpenXR hand model receipt: serial=%llu counter=%d reloading=%d roles=%u valid=%d.",
              (unsigned long long)handModelReceipt.serial,handModelReceipt.presentation.counter,
              handModelReceipt.presentation.reloading,unsigned(handModelReceipt.seen),
              weaponReceiptComplete() && !handModelReceipt.mismatch && weaponReceiptOwned());
    // Native menus poll authoritative packets after the weapon pixels, even
    // when no menu is open. Late field changes belong to subsequent draws;
    // the completed image requires its receipt and target ownership to survive.
    if (handModelReceipt.runtime && (!weaponReceiptComplete() || handModelReceipt.mismatch || !weaponReceiptOwned()))
    {
        if (std::getenv("EDUKE32_XR_TEST_MODELS"))
            LOG_F(INFO,"OpenXR hand model frame canceled: serial=%llu submitted=%llu.",
                  (unsigned long long)handModelReceipt.serial,
                  (unsigned long long)handModelReceipt.runtime->lastSubmittedSerial());
        if (std::getenv("EDUKE32_XR_TEST_MODEL_ANIMATION"))
        {
            XRWeaponPresentation fresh;
            auto const &saved=handModelReceipt.presentation;
            bool const qualified=P_XRWeaponPresentation(fresh) && fresh.family==saved.family;
            LOG_F(INFO,"OpenXR hand model rejected: qualified=%d saved=%d,%d,%d,%d fresh=%d,%d,%d,%d bound=%d roles=%u mismatch=%d serial=%llu,%llu.",
                  qualified,saved.palette,saved.shade,saved.counter,saved.reloading,
                  fresh.palette,fresh.shade,fresh.counter,fresh.reloading,
                  menuRuntime && menuRuntime->menuOverlayTargetBound(),unsigned(handModelReceipt.seen),handModelReceipt.mismatch,
                  (unsigned long long)handModelReceipt.serial,(unsigned long long)pendingFrame.serial);
        }
        // The submitted image would disagree with native weapon state: drop
        // this one frame. Test runs (EDUKE32_XR=1) keep the strict stop.
        G_XRCancelMenuPresentation();
        auto const retry=sdlayer_xr_option("EDUKE32_XR_RETRY");
        if (retry && !Bstrcmp(retry,"1"))
        {
            static unsigned dropped;
            if (dropped++<4) LOG_F(WARNING,"OpenXR held-model receipt mismatch; frame dropped.");
            return;
        }
        sdlayer_xr_disableWorld("held-model/native weapon receipt mismatch");
        return;
    }
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

// Controller feedback from native player state, sampled once per display
// frame: a pulse in the weapon hand when ammo is spent or a melee/zero-ammo
// weapon starts its native firing counter, and in both hands on damage.
static void updateHaptics(eduke_xr::Runtime *runtime)
{
    static int lastWeapon=-1, lastAmmo=-1, lastHealth=-1, lastCounter=0;
    auto const option=sdlayer_xr_option("EDUKE32_XR_HAPTICS");
    auto const p=g_player[myconnectindex].ps;
    if (!option || Bstrcmp(option,"1") || !runtime || !inputValid() || !(p->gm & MODE_GAME) || ud.recstat
        || (unsigned)p->i>=MAXSPRITES || (unsigned)p->curr_weapon>=MAX_WEAPONS)
    {
        lastWeapon=lastAmmo=lastHealth=-1; lastCounter=0;
        return;
    }
    int const weapon=p->curr_weapon, ammo=p->ammo_amount[weapon], health=sprite[p->i].extra;
    unsigned const hand=aimHand()==0 ? 0 : 1;
    if (wheel.hapticPending)
    {
        wheel.hapticPending=false;
        runtime->vibrate(hand,.6f,.05f);
    }
    if (gadgetWheel.hapticPending)
    {
        gadgetWheel.hapticPending=false;
        runtime->vibrate(1-hand,.6f,.05f);
    }
    bool const spent=weapon==lastWeapon && ammo<lastAmmo;
    bool const swing=weapon==KNEE_WEAPON && lastWeapon==KNEE_WEAPON && lastCounter==0 && p->kickback_pic>0;
    if (spent || swing)
    {
        bool const applied=runtime->vibrate(hand,weapon==RPG_WEAPON || weapon==DEVISTATOR_WEAPON ? 1.f : .6f,
                                            weapon==CHAINGUN_WEAPON ? .03f : .07f);
        if (std::getenv("EDUKE32_XR_TEST_HAPTICS"))
            LOG_F(INFO,"OpenXR haptic: fire hand=%u weapon=%d ammo=%d applied=%d.",hand,weapon,ammo,int(applied));
    }
    if (lastHealth>=0 && health<lastHealth && health>=0)
    {
        float const strength=std::min(1.f,.3f+float(lastHealth-health)/40.f);
        runtime->vibrate(0,strength,.12f);
        runtime->vibrate(1,strength,.12f);
    }
    lastWeapon=weapon; lastAmmo=ammo; lastHealth=health; lastCounter=p->kickback_pic;
}

// Test-only CPU profiler (EDUKE32_XR_PROFILE=1): samples the main thread's call stack every 1 ms
// of its own CPU time; the console request "xr_profile <path>" writes inclusive/self counts per
// function (symbols via dladdr; build with -rdynamic or symbolize addresses offline).
namespace xrprofile
{
constexpr unsigned Depth=24, Capacity=1<<16;
static void *samples[Capacity][Depth];
static uint8_t depths[Capacity];
static std::atomic<unsigned> count{0};
static void onSample(int, siginfo_t *, void *)
{
    unsigned const at=count.fetch_add(1);
    if (at<Capacity) depths[at]=uint8_t(backtrace(samples[at],Depth));
}
static void start()
{
    static bool started;
    if (started || !std::getenv("EDUKE32_XR_PROFILE")) return;
    started=true;
    struct sigaction action{};
    action.sa_sigaction=onSample; action.sa_flags=SA_SIGINFO|SA_RESTART;
    sigaction(SIGPROF,&action,nullptr);
    void *warm[4]; backtrace(warm,4);   // load the unwinder before the first signal
    sigevent event{};
    event.sigev_notify=SIGEV_THREAD_ID; event._sigev_un._tid=int(syscall(SYS_gettid)); event.sigev_signo=SIGPROF;
    timer_t timer;
    if (timer_create(CLOCK_THREAD_CPUTIME_ID,&event,&timer)) return;
    itimerspec spec{}; spec.it_interval.tv_nsec=spec.it_value.tv_nsec=1000000;
    timer_settime(timer,0,&spec,nullptr);
    LOG_F(INFO,"OpenXR profiler: sampling the main thread every 1 ms of CPU.");
}
static void dump(char const *path)
{
    // One stack per line, innermost first: library symbol, else module+offset (symbolize the
    // game's own frames offline, e.g. tools/vr/profile_report.py with addr2line).
    unsigned const n=std::min<unsigned>(count.load(),Capacity);
    FILE *f=std::fopen(path,"w");
    if (!f) return;
    for (unsigned i=0;i<n;++i)
    {
        for (unsigned d=1;d<depths[i];++d)   // frame 0 is the signal handler
        {
            Dl_info info{};
            if (dladdr(samples[i][d],&info) && info.dli_sname) std::fprintf(f,"%s ",info.dli_sname);
            else std::fprintf(f,"%s+%#lx ",info.dli_fname ? info.dli_fname : "?",
                              (unsigned long)((char *)samples[i][d]-(char *)info.dli_fbase));
        }
        std::fputc('\n',f);
    }
    std::fclose(f);
    count=0;
}
}

// Test hook: run native console commands written into the request file
// (one per line), then remove it. Used by harnesses to give/switch weapons.
static void runConsoleRequest()
{
    xrprofile::start();
    auto const request=std::getenv("EDUKE32_XR_CONSOLE_REQUEST");
    if (!request) return;
    FILE *file=std::fopen(request,"r");
    if (!file) return;
    std::vector<std::string> commands;
    char line[512];
    while (std::fgets(line,sizeof(line),file))
    {
        line[strcspn(line,"\r\n")]=0;
        if (line[0]) commands.emplace_back(line);
    }
    std::fclose(file);
    std::remove(request);
    for (auto const &command:commands)
    {
        LOG_F(INFO,"OpenXR console request: %s",command.c_str());
        if (command=="xr_weapons")
        {
            // Deterministic test inventory (the deferred native cheat slot
            // is shared with other console cheats).
            auto const p=g_player[myconnectindex].ps;
            for (int weapon=PISTOL_WEAPON;weapon<MAX_WEAPONS;++weapon)
            {
                p->gotweapon|=1<<weapon;
                P_AddAmmo(p,weapon,p->max_ammo_amount[weapon]);
            }
            continue;
        }
        if (!command.compare(0,11,"xr_profile "))
        {
            xrprofile::dump(command.c_str()+11);
            continue;
        }
        if (!command.compare(0,9,"xr_spawn "))
        {
            // Test hook: an actor (tile number) in front of the player, facing them; an optional
            // second number is the distance in Build units (default 2048, ~5 m).
            auto const p=g_player[myconnectindex].ps;
            char *rest=nullptr;
            int const tile=int(std::strtol(command.c_str()+9,&rest,10));
            int const distance=rest && *rest ? std::max(64,std::min(16384,std::atoi(rest))) : 2048;
            if ((unsigned)p->i<MAXSPRITES && (unsigned)tile<MAXTILES)
            {
                int const spawned=A_Spawn(p->i,tile);
                if (spawned>=0)
                {
                    int const ang=fix16_to_int(p->q16ang);
                    auto &spr=sprite[spawned];
                    spr.x=p->pos.x+mulscale14(sintable[(ang+512)&2047],distance);
                    spr.y=p->pos.y+mulscale14(sintable[ang&2047],distance);
                    spr.ang=(ang+1024)&2047;
                    if (!spr.xrepeat || !spr.yrepeat) spr.xrepeat=spr.yrepeat=40;   // map actors carry their size
                    changespritesect(spawned,p->cursectnum);
                    spr.z=sector[p->cursectnum].floorz;
                    LOG_F(INFO,"OpenXR test spawn: tile=%d sprite=%d.",tile,spawned);
                }
            }
            continue;
        }
        if (command=="xr_kill")
        {
            // Test hook: the local player dies (as from damage).
            auto const p=g_player[myconnectindex].ps;
            if ((unsigned)p->i<MAXSPRITES) { sprite[p->i].extra=0; p->dead_flag=0; }
            continue;
        }
        if (command=="xr_endlevel")
        {
            // Test hook: finish the level like the exit switch (intermission follows).
            for (int TRAVERSE_CONNECT(i)) g_player[i].ps->gm=MODE_EOL;
            continue;
        }
        if (command=="xr_items")
        {
            // Test hook: a full inventory (native maxima).
            auto const p=g_player[myconnectindex].ps;
            p->inv_amount[GET_FIRSTAID]=100; p->inv_amount[GET_STEROIDS]=400; p->inv_amount[GET_HOLODUKE]=2400;
            p->inv_amount[GET_JETPACK]=1600; p->inv_amount[GET_HEATS]=1200; p->inv_amount[GET_SCUBA]=6400;
            p->inv_amount[GET_BOOTS]=200;
            continue;
        }
        if (!command.compare(0,10,"xr_select "))
        {
            // Test hook: switch the local player's weapon directly.
            int const weapon=std::atoi(command.c_str()+10);
            if (unsigned(weapon)<MAX_WEAPONS) P_AddWeapon(g_player[myconnectindex].ps,weapon,1);
            continue;
        }
        if (command=="xr_where")
        {
            // Read-only position report for multiplayer harnesses.
            for (int TRAVERSE_CONNECT(i))
            {
                auto const q=g_player[i].ps;
                if ((unsigned)q->i>=MAXSPRITES) continue;
                auto const &body=sprite[q->i];
                LOG_F(INFO,"VR where: player=%d local=%d pos=%d,%d,%d ang=%d weapon=%d sprite=%d,%d,%d,%d.",i,int(i==myconnectindex),
                      q->pos.x,q->pos.y,q->pos.z,fix16_to_int(q->q16ang),q->curr_weapon,body.x,body.y,body.z,body.ang);
            }
            continue;
        }
        int weapon;
        if (std::sscanf(command.c_str(),"xr_weapon %d",&weapon)==1 && (unsigned)weapon<MAX_WEAPONS)
        {
            auto const p=g_player[myconnectindex].ps;
            if (p->gotweapon & (1<<weapon)) P_AddWeapon(p,weapon,1);
            continue;
        }
        OSD_Dispatch(command.c_str());
    }
}

// Load every VR model skin once per level, while the level loads, instead of the first time a
// weapon, the wheel or a hand pose shows it (a visible hitch in the headset).
static void precacheVRModels()
{
    static int precachedLevel=-1;
    auto const p=g_player[myconnectindex].ps;
    if (!sdlayer_xr_worldActive() || !G_XRModelsEnabled() || !p || !(p->gm & MODE_GAME)) return;
    int const level=ud.volume_number*MAXLEVELS+ud.level_number;
    if (level==precachedLevel) return;
    precachedLevel=level;
    double const start=double(timerGetNanoTicks())/double(timerGetNanoTickRate());
    unsigned count=0;
    auto const precache=[&](int tile) { if (md_tilehasmodel(tile,0)>=0) { polymost_precache(tile,0,1); ++count; } };
    precache(21);
    for (int tile=XRHeldModelTileBase-10;tile<XRHeldModelTileBase+300 && tile<MAXTILES;++tile) precache(tile);
    LOG_F(INFO,"OpenXR precached %u VR models in %.0f ms.",count,(double(timerGetNanoTicks())/double(timerGetNanoTickRate())-start)*1000.);
}

// Opt-in CPU phase timing (EDUKE32_XR_TEST_TIMING=1): averages every 120 frames.
static struct
{
    double opaque=0, animate=0, models=0, masks=0, total=0;
    unsigned frames=0;
} xrTiming;
static double xrNowMs() { return double(timerGetNanoTicks())*1000.0/double(timerGetNanoTickRate()); }

// EDUKE32_XR_PERF=1: one line every ~2 s with where the frame time goes (CPU per phase, time
// blocked in xrWaitFrame, overlay flushes, GPU time from timer queries).
static void logPerf(eduke_xr::Runtime *runtime)
{
    static bool const enabled=std::getenv("EDUKE32_XR_PERF")!=nullptr;
    if (!enabled || !runtime) return;
    runtime->enablePerf(true);
    static double windowStart=-1., lastFrame=-1., frameSum=0., frameMax=0.;
    static unsigned frameCount=0;
    double const now=xrNowMs();
    if (lastFrame>=0.) { double const dt=now-lastFrame; frameSum+=dt; frameMax=std::max(frameMax,dt); ++frameCount; }
    lastFrame=now;
    if (windowStart<0.) windowStart=now;
    if (now-windowStart<2000.) return;
    auto const p=runtime->takePerf();
    double const n=std::max(1u,frameCount), world=std::max(1u,xrTiming.frames);
    double const gpu=p.gpuFrames ? p.gpuMs/p.gpuFrames : -1.;
    LOG_F(INFO,"OpenXR perf: fps=%.1f frame=%.2f (max %.2f) ms; wait=%.2f render-cpu=%.2f [world=%.2f: opaque=%.2f anim=%.2f models=%.2f masks=%.2f; flushes=%.2f x%.1f] gpu=%.2f ms.",
          frameCount*1000./(now-windowStart),frameSum/n,frameMax,p.waitMs/std::max(1u,p.frames),p.renderMs/std::max(1u,p.frames),
          xrTiming.total/world,xrTiming.opaque/world,xrTiming.animate/world,xrTiming.models/world,xrTiming.masks/world,
          p.flushMs/std::max(1u,p.frames),double(p.flushes)/std::max(1u,p.frames),gpu);
    xrTiming={};
    windowStart=now; frameSum=frameMax=0.; frameCount=0;
}

void G_XRBeginFrame()
{
    runConsoleRequest();
    precacheVRModels();
    crosshairViews={};
    modelAnimationCapture.clear(); weaponAnimationCapture.clear();
    // Credit only the exact completed projection, never a rendered image that
    // was later canceled by a nested native draw, resize, or early swap.
    if (worldReceipt.runtime && worldReceipt.runtime->generation()==worldReceipt.generation
        && worldReceipt.runtime->lastSubmittedSerial()==worldReceipt.serial)
    {
        if (worldFrames<512 && (std::getenv("EDUKE32_XR_TEST_MODEL_SWITCH")
            || (worldFrames>=60 && std::getenv("EDUKE32_XR_TEST_MOUNT_STREAM"))))
            LOG_F(INFO,"OpenXR mount submitted: serial=%llu.",(unsigned long long)worldReceipt.serial);
        accountWorldFrame(worldReceipt.opaque,worldReceipt.masks,false,worldReceipt.models,worldReceipt.handModels);
    }
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
    logPerf(runtime);
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
        crosshairViews.weapon.valid=false;
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
        crosshairViews.weapon.valid=false;
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
    updateHaptics(runtime);
}

// Flat screens drawn outside the game's display loop (intermission/bonus screens, logos,
// cutscenes, loading) never reach the headset on their own. After two swaps without an XR
// submission, show each swapped frame on the world-locked virtual screen (and keep controller
// input flowing so "press any button" works).
static void G_XRFlatFrame()
{
    auto *runtime=sdlayer_xr_worldRuntime();
    if (!runtime || g_networkMode==NET_DEDICATED_SERVER || videoGetRenderMode()!=REND_POLYMOST) return;
    // Synthetic stereo fixtures end their XR frames empty on purpose.
    static bool const fixture=std::getenv("EDUKE32_XR_TEST_ZERO_IPD") || std::getenv("EDUKE32_XR_TEST_STEREO_POSE");
    if (fixture) return;
    static uint64_t lastSerial;
    static unsigned idleSwaps;
    uint64_t const serial=runtime->lastSubmittedSerial();
    if (serial!=lastSerial) { lastSerial=serial; idleSwaps=0; return; }
    if (++idleSwaps<2 || runtime->menuPresentationActive()) return;
    G_XRBeginFrame();
    auto *ready=pendingRuntime;
    pendingRuntime=nullptr;
    if (!ready || ready->generation()!=pendingGeneration) return;
    // Test hook shared with the world path: capture this frame to the requested prefix.
    std::string requested;
    if (char const *request=std::getenv("EDUKE32_XR_CAPTURE_REQUEST"))
        if (FILE *file=std::fopen(request,"r"))
        {
            char prefix[1024]={};
            if (std::fgets(prefix,sizeof(prefix),file)) requested=prefix;
            std::fclose(file); std::remove(request);
            requested.erase(requested.find_last_not_of("\r\n")+1);
            if (!requested.empty()) LOG_F(INFO,"OpenXR capture request: flat screen prefix=%s.",requested.c_str());
        }
    std::string error;
    if (!ready->presentNativeFrame(xdim,ydim,error,requested.empty() ? nullptr : requested.c_str()))
    {
        static bool reported;
        if (!reported) LOG_F(WARNING,"OpenXR flat screen: %s",error.c_str());
        reported=true;
    }
    else if (std::getenv("EDUKE32_XR_TEST_HELD"))
    {
        static unsigned shown;
        if (shown++%90==0) LOG_F(INFO,"OpenXR flat screen: presented %u frames.",shown);
    }
    lastSerial=ready->lastSubmittedSerial();
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

// A mirror was drawn by the previous XR frame (native gotpic is cleared by
// G_ClearGotMirror before our pass, after the flat G_HandleMirror used it).
static bool mirrorSeen;

// G_HandleMirror's mirror choice and draw order from one eye's camera, into
// that eye's target (stencil marks the mirror region). Script DISPLAYROOMS /
// RESETGOTPICS events stay with the native once-per-frame call.
// Last frame's VR models (body, hands, held weapon, ...), drawn reflected inside mirrors: you see your
// own full body in a mirror. One frame old, which a reflection never shows.
static std::vector<WorldModelSample> mirrorModels;
static bool mirrorHasBody;

static void drawMirrorModels(Eye const &eye, int mirrorWall)
{
    // Only with the full body: otherwise the native third-person Duke stays in the reflection and
    // floating hands next to it would be doubles.
    if (mirrorModels.empty() || !mirrorHasBody) return;
    auto const &a=wall[mirrorWall], &b=wall[a.point2];
    float dx=float(b.x-a.x), dy=float(b.y-a.y);
    float const l=std::sqrt(dx*dx+dy*dy);
    if (!(l>0.f)) return;
    dx/=l; dy/=l;
    float const nx=-dy, ny=dx;   // unit normal of the mirror line
    // Real-eye camera for the model matrices (the mirror pass left the reflected camera installed).
    eyeState(eye);
    renderPrepareMasksQ16(eye.camera.pos.x,eye.camera.pos.y,eye.camera.pos.z,eye.camera.angle,eye.camera.horizon,eye.camera.sector);
    for (auto model:mirrorModels)
    {
        float const d=(float(model.root.x-a.x)*nx+float(model.root.y-a.y)*ny)*2.f;
        model.root.x=int32_t(std::lround(model.root.x-d*nx));
        model.root.y=int32_t(std::lround(model.root.y-d*ny));
        for (auto &v:model.basis)
        {
            float const k=(v.x*nx+v.y*ny)*2.f;
            v.x-=k*nx; v.y-=k*ny;
        }
        worldModelMatrix(model,eye);
        bool drawn=false;
        if (polymost_xrBeginModelDraw(model.context.shade,model.context.palette,model.sector))
        {
            drawn=polymost_md3drawcontext(&model.context)!=0;
            polymost_xrEndModelDraw();
        }
        if (std::getenv("EDUKE32_XR_TEST_HANDS"))
        {
            static int logged;
            if (logged++<12) LOG_F(INFO,"OpenXR mirror model: instance=%d drawn=%d root=%d,%d,%d eye=%.3f,%.3f,%.3f.",model.context.instance,int(drawn),
                                   model.root.x,model.root.y,model.root.z,model.context.modelToEye[12],model.context.modelToEye[13],model.context.modelToEye[14]);
        }
    }
}

static void drawEyeMirror(Camera const &cam, int32_t smoothRatio, Eye const *eye=nullptr)
{
    if (std::getenv("EDUKE32_XR_TEST_HANDS"))
    {
        static int logged;
        if (logged++<4) LOG_F(INFO,"OpenXR mirror pass: seen=%d count=%d models=%zu eye=%d.",int(mirrorSeen),g_mirrorCount,mirrorModels.size(),eye!=nullptr);
    }
    if (!mirrorSeen || g_mirrorCount<=0) return;
    int best=-1;
    int32_t distance=INT32_MAX;
    for (int k=g_mirrorCount-1;k>=0;--k)
    {
        if (!wallvisible(cam.pos.x,cam.pos.y,g_mirrorWall[k])) continue;
        int32_t const d=klabs(wall[g_mirrorWall[k]].x-cam.pos.x)+klabs(wall[g_mirrorWall[k]].y-cam.pos.y);
        if (d<distance) { distance=d; best=k; }
    }
    if (best<0 || wall[g_mirrorWall[best]].overpicnum!=MIRROR) return;
    int32_t tposx, tposy;
    fix16_t tang;
    renderPrepareMirror(cam.pos.x,cam.pos.y,cam.pos.z,cam.angle,cam.horizon,g_mirrorWall[best],&tposx,&tposy,&tang);
    int32_t const visibility=g_visibility;
    g_visibility=(visibility>>1)+(visibility>>2);
    spritesortcnt=0;
    yax_preparedrawrooms();
    int32_t const didmirror=renderDrawRoomsQ16(tposx,tposy,cam.pos.z,tang,cam.horizon,g_mirrorSector[best]+MAXSECTORS);
    if (numyaxbunches) yax_drawrooms(G_DoSpriteAnimations,g_mirrorSector[best],didmirror,smoothRatio);
    display_mirror=1;
    G_DoSpriteAnimations(tposx,tposy,cam.pos.z,fix16_to_int(tang),smoothRatio);
    display_mirror=0;
    // Your VR body replaces your own native player sprite in the reflection.
    // (Removed from the list: drawmasks does not look at CSTAT_SPRITE_INVISIBLE.)
    if (eye && mirrorHasBody)
        for (int k=spritesortcnt-1;k>=0;--k)
            if (tsprite[k].owner==g_player[myconnectindex].ps->i) tsprite[k]=tsprite[--spritesortcnt];
    renderDrawMasks();
    if (eye) drawMirrorModels(*eye,g_mirrorWall[best]);
    renderCompleteMirror();
    g_visibility=visibility;
    spritesortcnt=0;
    maskwallcnt=0;
}


bool G_XRDrawRooms(int32_t smoothRatio)
{
    double const timingStart=xrNowMs();
    double timingMark=timingStart;
    static bool const timing=std::getenv("EDUKE32_XR_TEST_TIMING")!=nullptr || std::getenv("EDUKE32_XR_PERF")!=nullptr;
    auto const lap=[&](double &slot) { if (!timing) return; double const now=xrNowMs(); slot+=now-timingMark; timingMark=now; };
    // Initial renderer oracle deliberately excludes multi-view sector effects.
    // Further camera/draw families and tracked weapon origins remain required.
    if (videoGetRenderMode() != REND_POLYMOST || g_screenCapture)
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
        worldModelOracleFrames=worldModelMultiviewFrames=0;
        gripCaptures.fill(false); lastGripState=-1; gripDiagnostics=0;
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
    prepareWeaponVisual(body,runtime);
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
        {
            char const *rejection=nullptr;
            if (!makeEye(frame.views[i],body,float(frame.width)/frame.height,eyes[i],rejection))
            {
                static bool warned;
                if (!warned)
                {
                    LOG_F(WARNING,"XR oracle frame outside native camera coverage/collision domain; full-pitch/room-scale support remains pending.");
                    if (std::getenv("EDUKE32_XR_TEST_AIM"))
                        LOG_F(INFO,"OpenXR rejected eye: eye=%u reason=%s bodyPitch=%.6f pos=%d,%d,%d sector=%d fov=%.6f,%.6f,%.6f,%.6f.",
                              i,rejection ? rejection : "unknown",nativePitch(body.horizon),
                              eyes[i].camera.pos.x,eyes[i].camera.pos.y,eyes[i].camera.pos.z,eyes[i].camera.sector,
                              frame.views[i].fov.angleLeft,frame.views[i].fov.angleRight,
                              frame.views[i].fov.angleUp,frame.views[i].fov.angleDown);
                }
                warned = true;
                runtime->finishFrame(false,error);
                return false;
            }
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
        LOG_F(INFO,"OpenXR aim eye roll: left=%.9f right=%.9f.",eyes[0].camera.roll,eyes[1].camera.roll);
    }
    // Face sprites become head-facing cards for this stereo frame (see polymost_drawsprite).
    struct BillboardScope
    {
        BillboardScope(vec3_t a, vec3_t b)
        {
            auto const option=sdlayer_xr_option("EDUKE32_XR_FACE_BILLBOARD");
            polymost_xrBillboard={(a.x+b.x)/2,(a.y+b.y)/2,!option || Bstrcmp(option,"0")};
        }
        ~BillboardScope() { polymost_xrBillboard.active=false; }
    } const billboards(eyes[0].camera.pos,eyes[1].camera.pos);
    vec2_t const oldStart=windowxy1, oldEnd=windowxy2;
    int const oldRange=viewingrange, oldAspect=yxaspect;
    int const frozenVisibility=g_visibility, frozenParallax=parallaxvisibility;
    bool animated=false, good=true, usedMultiview=false, usedMaskMultiview=false, usedHandModel=false, usedModelMultiview=false, attemptedHandModel=false;
    videoSetViewableArea(0,0,xdim-1,ydim-1);
    auto const drawOpaque = [&](bool collect) {
        for (unsigned i=0;i<2 && good;++i)
        {
            auto &eye=eyes[i];
            good=runtime->bindEye(i,error);
            if (!good) return false;
            eye.sectors.fill(0);
            for (unsigned pass=0;pass<eye.passCount();++pass)
            {
                auto &view=eye.passes[pass];
                view.sprites.clear();
                view.walls.clear();
                eyeState(eye,pass);
                if (!pass)
                {
                    glClearColor(0,0,0,1);
                    glClear(GL_COLOR_BUFFER_BIT);
                    // Mirrors use the front pass camera only.
                    if (!collect) drawEyeMirror(view.camera,smoothRatio,&eye);
                }
                spritesortcnt=0;
                if (collect) polymost_xrBeginCollection(POLYMOST_XR_OPAQUE,i);
                yax_preparedrawrooms();
                // The back pass covers a disjoint screen region of the same eye.
                yax_polymostclearzbuffer=!pass;
                renderDrawRoomsQ16(view.camera.pos.x,view.camera.pos.y,view.camera.pos.z,
                                  view.camera.angle,view.camera.horizon,view.camera.sector);
                // Room-over-room levels are drawn natively per view, each
                // with its own masks and sprite animation exactly as the flat
                // renderer does; the base level keeps one shared transaction.
                if (numyaxbunches)
                    yax_drawrooms(G_DoSpriteAnimations,view.camera.sector,0,smoothRatio);
                yax_polymostclearzbuffer=1;
                if (collect && polymost_xrEndCollection(i) != POLYMOST_XR_COLLECT_OK)
                    return false;
                if (spritesortcnt >= maxspritesonscreen || maskwallcnt >= MAXWALLSB)
                {
                    error="stereo collection saturated native list capacity";
                    good=false; return false;
                }
                view.sprites.assign(tsprite,tsprite+spritesortcnt);
                view.walls.reserve(maskwallcnt);
                for (int j=0;j<maskwallcnt;++j) view.walls.push_back(thewall[maskwall[j]]);
                for (size_t j=0;j<sizeof(gotsector);++j) eye.sectors[j]|=gotsector[j];
            }
            if (i == 0 && testFailure("opaque"))
            {
                error="injected failure after left opaque pass";
                good=false; return false;
            }
        }
        return good;
    };
    char const *singleValue=sdlayer_xr_option("EDUKE32_XR_SINGLE_PASS");
    // Split full-pitch eyes carry two camera rotations per eye; their replay
    // uses the per-eye reference path until multiview can pair split passes.
    bool const singlePass=singleValue && !Bstrcmp(singleValue,"1") && !eyes[0].split && !eyes[1].split && !numyaxbunches
        && !mirrorSeen;
    if (eyes[0].split || eyes[1].split)
    {
        static unsigned splitFrames;
        if (!splitFrames++ || std::getenv("EDUKE32_XR_TEST_PITCH"))
            LOG_F(INFO,"OpenXR full-pitch split frame: serial=%llu passes=%u,%u pitch=%.1f bodyPitch=%.1f fov=%.2f,%.2f,%.2f,%.2f.",
                  (unsigned long long)frame.serial,eyes[0].passCount(),eyes[1].passCount(),
                  std::atan2(eyes[0].upSin,eyes[0].upCos)*180.f/Pi,nativePitch(body.horizon)*180.f/Pi,
                  frame.views[0].fov.angleLeft,frame.views[0].fov.angleRight,frame.views[0].fov.angleUp,frame.views[0].fov.angleDown);
    }
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
                        LOG_F(INFO,"OpenXR opaque single-pass: frame=%u paired=%u eyeOnly=%u pairedVertices=%u eyeOnlyVertices=%u flatSky=%u skyDepth=%u npot=%u skybox=%u skyboxPaired=%u",
                              unsigned(g_frameCounter),stats.pairedCalls,stats.eyeOnlyCalls,stats.pairedVertices,stats.eyeOnlyVertices,
                              stats.flatSkyCalls,stats.skyDepthCalls,stats.npotCalls,stats.skyboxCalls,stats.skyboxPairedCalls);
                        reported=true;
                    }
                }
            }
            else committed=false;
        }
        if (!committed && good)
        {
            static unsigned reported;
            if (reported < 3 || g_frameCounter == 12)
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
    mirrorSeen=bitmap_test(gotpic,MIRROR);
    lap(xrTiming.opaque);
    if (good)
    {
        std::vector<int> byOwner(MAXSPRITES,-1);
        spritesortcnt=0;
        membership.fill(0);
        for (unsigned i=0;i<2 && good;++i)
            for (unsigned pass=0;pass<eyes[i].passCount() && good;++pass)
            for (auto const &sprite : eyes[i].passes[pass].sprites)
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
                membership[slot] |= 1u<<(i*2+pass);
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
        lap(xrTiming.animate);
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
        // Remote VR bodies replace their native sprites in every eye pass.
        std::vector<HandSegmentSample> remoteSamples;
        remoteSamples.reserve(4*MAXPLAYERS);
        if (good && !fixtureTest) prepareRemoteBodies(remoteSamples,smoothRatio);
        std::vector<tspritetype> pristine(tsprite,tsprite+spritesortcnt);
        // Capture actual native fallback ART too when an optional model lacks
        // a named frame. This diagnostic observes counters without changing them.
        auto const observedPlayer=g_player[myconnectindex].ps;
        int const observedCounter=observedPlayer->kickback_pic;
        // Observe another native weapon without changing its counters or draw
        // path. Keep the original pistol diagnostic as the default.
        static int const captureWeapon=[]() {
            auto const value=std::getenv("EDUKE32_XR_TEST_MODEL_WEAPON");
            if (!value) return int(PISTOL_WEAPON);
            char *end;
            long const weapon=std::strtol(value,&end,10);
            return end!=value && !*end && weapon>=0 && weapon<MAX_WEAPONS ? int(weapon) : -1;
        }();
        static bool capturedCounters[27]{};
        if (worldFrames>=60 && observedCounter>0 && observedCounter<27
            && observedPlayer->curr_weapon==captureWeapon
            && std::getenv("EDUKE32_XR_TEST_MODEL_ANIMATION")
            && !capturedCounters[observedCounter])
        {
            char suffix[32]; Bsnprintf(suffix,sizeof(suffix),"-counter-%02d",observedCounter);
            if (auto prefix=std::getenv("EDUKE32_XR_MODEL_OUTPUT"))
                modelAnimationCapture=std::string(prefix)+suffix;
            if (auto prefix=std::getenv("EDUKE32_XR_WEAPON_OUTPUT"))
                weaponAnimationCapture=std::string(prefix)+suffix;
            capturedCounters[observedCounter]=true;
        }
        HandModelSample handModel;
        GripModelSample grips[2];
        BodyModelSample bodyModel;
        constexpr unsigned MaxWorldModels=72;
        std::vector<HandSegmentSample> segments;
        segments.reserve(MaxWorldModels);
        WorldModelSample *models[MaxWorldModels]{};
        unsigned modelCount=0, gripMask=0;
        bool const exactWeapon=good && !fixtureTest && !wheel.open && prepareHandModel(handModel);
        bool const weaponModel=exactWeapon || (good && !fixtureTest && !wheel.open && prepareHandModelFallback(handModel,body,runtime));
        heldModelShown=weaponModel;
        if (weaponModel) models[modelCount++]=&handModel;
        // RazeXR-style fallback: a weapon without a 3D model shows its native 2D sprite (which
        // carries Duke's own hand) on the controller, so that hand's 3D model stays hidden.
        auto const cardOption=sdlayer_xr_option("EDUKE32_XR_WEAPON");
        bool const cardHand=!weaponModel && !wheel.open && cardOption && !Bstrcmp(cardOption,"1")
            && g_player[myconnectindex].ps->curr_weapon!=KNEE_WEAPON && !nativeWeaponHidden();
        // True full body this frame: the IK body draws arms/legs; hands attach as wrist-cut shells.
        fullBodyFrame=good && !fixtureTest && fullBodyAvailable();
        handJoints[0].valid=handJoints[1].valid=false;
        handWire[0]=handWire[1]=HandWire{};
        HandModelSample detonator;
        unsigned detonatorHand=2;
        for (unsigned hand=0;hand<2 && good && !fixtureTest;++hand)
        {
            if (cardHand && int(hand)==aimHand()) continue;
            bool const holding=weaponModel && int(hand)==aimHand();
            HandModelSample const *held=holding ? &handModel : hand==detonatorHand ? &detonator : nullptr;
            int const heldTile=holding ? weaponModelTile(handModel.presentation.family)
                : hand==detonatorHand ? XRHeldModelTileBase+HANDREMOTE_WEAPON : -1;
            size_t const before=segments.size();
            if (prepareHandSegments(segments,hand,body,runtime,held,heldTile))
                continue; // Segmented hand replaces the single-mesh floating hand.
            segments.resize(before);
            if (prepareGripModel(grips[hand],hand,body,runtime))
            { models[modelCount++]=&grips[hand]; gripMask|=1u<<hand; }
        }
        if (good && !fixtureTest) { prepareWheel(wheel,segments,body,runtime); prepareWheel(gadgetWheel,segments,body,runtime); }
        HandSegmentSample tipWad;
        if (good && !fixtureTest && prepareTipWad(tipWad,body)) segments.push_back(tipWad);
        HandSegmentSample laser, boot;
        if (good && !fixtureTest && prepareLaser(laser,body,runtime)) segments.push_back(laser);
        if (good && !fixtureTest && !fullBodyFrame && prepareKickBoot(boot,body,runtime)) segments.push_back(boot);
        for (auto &segment:segments)
            if (modelCount<MaxWorldModels-1) models[modelCount++]=&segment;
        HandSegmentSample ikBody;
        if (fullBodyFrame && prepareIkBody(ikBody,body,runtime,false)) models[modelCount++]=&ikBody;
        else if (good && !fixtureTest && prepareBodyModel(bodyModel,body,runtime)) models[modelCount++]=&bodyModel;
        if (good && !fixtureTest)
            publishBodyPose(body,runtime,weaponModel ? &handModel : nullptr,weaponModel ? weaponModelTile(handModel.presentation.family) : -1);
        for (auto &sample:remoteSamples)
            if (modelCount<MaxWorldModels-1) models[modelCount++]=&sample;
        int const gripState=((gripMask&1) ? grips[0].state+1 : 0)+4*((gripMask&2) ? grips[1].state+1 : 0);
        std::string gripPrefix;
        bool gripLog=false;
        if (good && worldFrames>=60 && std::getenv("EDUKE32_XR_TEST_HANDS") && gripDiagnostics<32
            && gripState!=lastGripState)
        {
            gripLog=true;
            lastGripState=gripState; ++gripDiagnostics;
            if (auto prefix=std::getenv("EDUKE32_XR_HAND_OUTPUT"))
                if (!gripCaptures[gripState])
                {
                    char suffix[24]; Bsnprintf(suffix,sizeof(suffix),"-state-%02d",gripState);
                    gripPrefix=std::string(prefix)+suffix;
                    gripCaptures[gripState]=true;
                }
        }
        if (gripLog && !modelCount && gripPrefix.empty())
            LOG_F(INFO,"OpenXR floating hands: serial=%llu state=%d mask=%u left=%d right=%d capture=0.",
                  (unsigned long long)frame.serial,gripState,gripMask,grips[0].state,grips[1].state);
        if (good && (modelCount || !gripPrefix.empty()))
        {
            attemptedHandModel=modelCount!=0;
            // AA enters gameplay after its own controller selector, so the
            // ordinary frame60 diagnostic can precede the first eligible model.
            // Capture the first actual accepted AA model, without advancing it.
            // An explicit switch diagnostic also captures at most eight
            // accepted family changes; it never advances native weapon state.
            static bool capturedAAModel;
            static XRWeaponFamily capturedAAFamily=XRWeaponFamily::Unsupported;
            static unsigned familyCaptures;
            bool const captureFamily=std::getenv("EDUKE32_XR_TEST_MODEL_SWITCH")!=nullptr;
            bool const familyChanged=captureFamily && familyCaptures<8
                && handModel.presentation.family!=capturedAAFamily;
            if (weaponModel && aaWeaponFamily(handModel.presentation.family) && (!capturedAAModel || familyChanged)
                && std::getenv("EDUKE32_XR_TEST_MODELS"))
                if (auto prefix=std::getenv("EDUKE32_XR_MODEL_OUTPUT"))
                {
                    char suffix[32]={};
                    if (captureFamily)
                    {
                        Bsnprintf(suffix,sizeof(suffix),"-family-%02u",familyCaptures);
                        LOG_F(INFO,"OpenXR hand model family capture: serial=%llu family=%u index=%u.",
                              (unsigned long long)frame.serial,unsigned(handModel.presentation.family),familyCaptures);
                        ++familyCaptures;
                    }
                    modelAnimationCapture=std::string(prefix)+suffix;
                    if (auto weaponPrefix=std::getenv("EDUKE32_XR_WEAPON_OUTPUT"))
                        weaponAnimationCapture=std::string(weaponPrefix)+suffix;
                    capturedAAModel=true;
                    capturedAAFamily=handModel.presentation.family;
                }
            // Preserve the existing per-weapon diagnostic when both select
            // the same frame. Observe this grip state again on a later frame.
            if (!gripPrefix.empty() && !modelAnimationCapture.empty())
            {
                gripPrefix.clear(); gripCaptures[gripState]=false; lastGripState=-1;
            }
            char const *modelPrefix=!gripPrefix.empty() ? gripPrefix.c_str()
                : !modelAnimationCapture.empty() ? modelAnimationCapture.c_str()
                : worldFrames==59 ? std::getenv("EDUKE32_XR_MODEL_OUTPUT") : nullptr;
            bool const modelCapture=modelPrefix!=nullptr;
            bool const gripCapture=!gripPrefix.empty();
            if (gripCapture && std::getenv("EDUKE32_XR_TEST_MOUNT_WALL"))
                crosshairViews.diagnosticCrosshairPrefix=gripPrefix+"-crosshair";
            static unsigned mountStreamSamples;
            bool const mountStream=worldFrames>=60 && mountStreamSamples<240 && weaponModel
                && crosshairViews.weapon.valid && (gripMask & (1u<<crosshairViews.weapon.hand))
                && std::getenv("EDUKE32_XR_TEST_MOUNT_STREAM");
            if (gripLog)
                LOG_F(INFO,"OpenXR floating hands: serial=%llu state=%d mask=%u left=%d right=%d capture=%d.",
                      (unsigned long long)frame.serial,gripState,gripMask,grips[0].state,grips[1].state,gripCapture);
            if (modelCapture && weaponModel && std::getenv("EDUKE32_XR_TEST_MODEL_ANIMATION"))
                LOG_F(INFO,"OpenXR hand model sample: serial=%llu counter=%d reloading=%d frame=%d.",
                      (unsigned long long)frame.serial,handModel.presentation.counter,
                      handModel.presentation.reloading,handModel.context.cframe);
            auto const captureModels = [&](char const *suffix) {
                auto const prefix=modelPrefix;
                return !prefix
                    || runtime->captureFrame((std::string(prefix)+suffix).c_str(),false,error,true);
            };
            float modelMatrices[2][MaxWorldModels][16]{}, modelProjections[2][16]{};
            float oracleMatrices[2][MaxWorldModels][16]{}, oracleProjections[2][16]{};
            bool oracleSamples[2]{}, oracleCompared[2]{};
            auto const drawHandModel = [&](bool collect,NativeOracleTarget *oracle=nullptr) {
                bool accepted=true;
                for (unsigned i=0;i<2 && good;++i)
                {
                    good=runtime->bindEye(i,error);
                    if (!good) break;
                    if (oracle && !oracle->copyEye(i,error)) { good=false; break; }
                    videoSetViewableArea(0,0,xdim-1,ydim-1);
                    eyeState(eyes[i]);
                    if (collect && !polymost_xrBeginCollection(POLYMOST_XR_MODELS,i)) return false;
                    int const scriptVisibility=g_visibility, scriptParallax=parallaxvisibility;
                    g_visibility=frozenVisibility; parallaxvisibility=frozenParallax;
                    renderPrepareMasksQ16(eyes[i].camera.pos.x,eyes[i].camera.pos.y,eyes[i].camera.pos.z,
                                         eyes[i].camera.angle,eyes[i].camera.horizon,eyes[i].camera.sector);
                    g_visibility=scriptVisibility; parallaxvisibility=scriptParallax;
                    if (i==1 && testFailure("model-eye-1"))
                    { good=false; error="injected held-model failure before second eye"; break; }
                    for (unsigned index=0;index<modelCount && good;++index)
                    {
                        auto &model=*models[index];
                        worldModelMatrix(model,eyes[i]);
                        if (modelCapture || mountStream)
                        {
                            float projection[16]; glGetFloatv(GL_PROJECTION_MATRIX,projection);
                            if (oracle)
                            {
                                Bmemcpy(oracleMatrices[i][index],model.context.modelToEye,sizeof(projection));
                                Bmemcpy(oracleProjections[i],projection,sizeof(projection)); oracleSamples[i]=true;
                            }
                            else if (oracleSamples[i])
                            {
                                if (Bmemcmp(oracleMatrices[i][index],model.context.modelToEye,sizeof(projection))
                                    || Bmemcmp(oracleProjections[i],projection,sizeof(projection)))
                                { good=false; error="native model oracle transform changed"; break; }
                                oracleCompared[i]=true;
                            }
                            Bmemcpy(modelMatrices[i][index],model.context.modelToEye,sizeof(projection));
                            Bmemcpy(modelProjections[i],projection,sizeof(projection));
                        }
                        good=polymost_xrBeginModelDraw(model.context.shade,model.context.palette,model.sector);
                        if (good)
                        {
                            good=polymost_md3drawcontext(&model.context)!=0;
                            polymost_xrEndModelDraw();
                        }
                        if (!good) error="native held-model emission failed";
                        if (good && oracle && gripCapture)
                        {
                            auto const prefix=std::string(modelPrefix)+"-instance-"+std::to_string(model.context.instance)
                                +"-reference-"+(i ? "right" : "left");
                            good=eduke_xr::captureFramebuffer((prefix+".ppm").c_str(),xdim,ydim,error)
                                && eduke_xr::captureFramebufferDepth((prefix+"-depth.bin").c_str(),xdim,ydim,error);
                        }
                    }
                    if (good && oracle)
                    {
                        auto const prefix=std::string(modelPrefix)+"-reference-"+(i ? "right" : "left");
                        good=eduke_xr::captureFramebuffer((prefix+".ppm").c_str(),xdim,ydim,error)
                            && eduke_xr::captureFramebufferDepth((prefix+"-depth.bin").c_str(),xdim,ydim,error);
                    }
                    if (collect && polymost_xrEndCollection(i)!=POLYMOST_XR_COLLECT_OK) accepted=false;

                }
                return good && accepted;
            };
            good=captureModels("-before");
            auto const forceReference=std::getenv("EDUKE32_XR_TEST_MODELS_TWO_PASS");
            if (good && modelCount && singlePass && !(forceReference && !Bstrcmp(forceReference,"1")))
            {
                if (modelCapture)
                {
                    NativeOracleTarget oracle;
                    drawHandModel(false,&oracle);
                }
                if (std::getenv("EDUKE32_XR_TEST_FAIL"))
                    SDL_setenv("EDUKE32_XR_TEST_MODELS_ARMED",worldFrames==59 ? "1" : "0",1);
                bool committed=drawHandModel(true);
                if (good) good=captureModels("-collected");
                if (committed && good)
                {
                    good=runtime->bindMultiview(error);
                    if (good)
                    {
                        committed=polymost_xrReplayCollection()==POLYMOST_XR_COLLECT_OK;
                        if (committed)
                        {
                            usedModelMultiview=true;
                            if (modelCapture && (gripCapture || std::getenv("EDUKE32_XR_TEST_MODELS")))
                            {
                                auto const stats=polymost_xrCollectionStats();
                                LOG_F(INFO,"OpenXR hand model single-pass: paired=%u eyeOnly=%u shared=%u sharedVertices=%u.",
                                      stats.pairedCalls,stats.eyeOnlyCalls,stats.sharedModelCalls,stats.sharedModelVertices);
                                if (gripCapture)
                                    LOG_F(INFO,"OpenXR floating replay: serial=%llu instances=%u paired=%u eyeOnly=%u shared=%u vertices=%u.",
                                          (unsigned long long)frame.serial,modelCount,stats.pairedCalls,stats.eyeOnlyCalls,
                                          stats.sharedModelCalls,stats.sharedModelVertices);
                            }
                        }
                        else if (polymost_xrReplaySubmitted())
                        { good=false; error=std::string("model replay failed after submission: ")+polymost_xrCollectionReason(); }
                    }
                }
                if (!committed && good)
                {
                    static unsigned reported;
                    if (reported<3 || worldFrames==59)
                    { LOG_F(INFO,"OpenXR hand model uses two-pass oracle: %s.",polymost_xrCollectionReason()); ++reported; }
                    polymost_xrDiscardCollection();
                    drawHandModel(false);
                }
                polymost_xrDiscardCollection();
            }
            else if (good) drawHandModel(false);
            if (good) good=captureModels("-after");
            if (good)
            {
                usedHandModel=modelCount!=0;
                if (exactWeapon)
                {
                    handModelReceipt={runtime,runtime->generation(),frame.serial,myconnectindex,handModel.presentation,0,false};
                    if (aaWeaponFamily(handModel.presentation.family)) polymost_xrWeaponTileConsumer=consumeAAWeaponTile;
                }
                if (oracleCompared[0] && oracleCompared[1]) LOG_F(INFO,"OpenXR hand model oracle inputs: identical=1.");
                if (mountStream)
                {
                    ++mountStreamSamples;
                    int const hand=crosshairViews.weapon.hand;
                    auto const &g=rawInput.hands[hand].gripPose; auto const &a=rawInput.hands[hand].aimPose.orientation;
                    auto const &v=frame.views[1]; auto const &q=v.pose.orientation; auto const &p=v.pose.position;
                    LOG_F(INFO,"OpenXR mount stream: serial=%llu tick=%u hand=%d clamped=%d grip=%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g aim=%.9g,%.9g,%.9g,%.9g.",
                          (unsigned long long)frame.serial,g_moveThingsCount,hand,crosshairViews.weapon.clamped,
                          g.orientation.x,g.orientation.y,g.orientation.z,g.orientation.w,g.position.x,g.position.y,g.position.z,a.x,a.y,a.z,a.w);
                    LOG_F(INFO,"OpenXR mount stream view: pose=%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g fov=%.9g,%.9g,%.9g,%.9g.",
                          q.x,q.y,q.z,q.w,p.x,p.y,p.z,v.fov.angleLeft,v.fov.angleRight,v.fov.angleUp,v.fov.angleDown);
                    float const *values[]={handModel.context.modelToEye,grips[hand].context.modelToEye,modelProjections[1]};
                    char const *names[]={"weapon","hand","projection"};
                    for (unsigned n=0;n<3;++n)
                    {
                        auto const m=values[n];
                        LOG_F(INFO,"OpenXR mount stream %s: values=%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g.",names[n],
                              m[0],m[1],m[2],m[3],m[4],m[5],m[6],m[7],m[8],m[9],m[10],m[11],m[12],m[13],m[14],m[15]);
                    }
                }
                if (modelCapture && weaponModel && std::getenv("EDUKE32_XR_TEST_MODELS"))
                    for (unsigned i=0;i<2;++i)
                    {
                        LOG_F(INFO,"OpenXR hand model: eye=%u model=%d root=%d,%d,%d direction=%d,%d,%d.",i,
                              handModel.context.modelid,handModel.root.x,handModel.root.y,handModel.root.z,
                              handModel.shot.direction[0],handModel.shot.direction[1],handModel.shot.direction[2]);
                        if (crosshairViews.weapon.selected)
                        {
                            auto const &visual=crosshairViews.weapon;
                            auto const &p=rawInput.hands[visual.hand].gripPose.position;
                            auto const &q=rawInput.hands[visual.hand].aimPose.orientation;
                            LOG_F(INFO,"OpenXR pistol mount pose: eye=%u hand=%d grip=%.9g,%.9g,%.9g aim=%.9g,%.9g,%.9g,%.9g.",
                                  i,visual.hand,p.x,p.y,p.z,q.x,q.y,q.z,q.w);
                            if (i==0)
                            {
                                LOG_F(INFO,"OpenXR pistol mount render: serial=%llu hand=%d body=%d,%d,%d,%d,%d,%d clamped=%d.",
                                      (unsigned long long)frame.serial,visual.hand,body.pos.x,body.pos.y,body.pos.z,
                                      body.angle,body.horizon,body.sector,visual.clamped);
                                if (std::getenv("EDUKE32_XR_TEST_MOUNT_WALL"))
                                {
                                    auto const tracking=multiply(pitchRoll(nativePitch(body.horizon),body.roll),inverseYaw);
                                    LOG_F(INFO,"OpenXR mount collision: serial=%llu root=%d,%d,%d correction=%d,%d,%d origin=%.9g,%.9g,%.9g tracking=%.9g,%.9g,%.9g,%.9g yaw=%.9g local=%.9g,%.9g,%.9g.",
                                          (unsigned long long)frame.serial,visual.root.x,visual.root.y,visual.root.z,
                                          visual.correction.x,visual.correction.y,visual.correction.z,origin.x,origin.y,origin.z,
                                          tracking.x,tracking.y,tracking.z,tracking.w,fix16_to_float(body.angle)*Pi/1024.f,
                                          visual.pose.position.x,visual.pose.position.y,visual.pose.position.z);
                                }
                            }
                        }
                        float const *a=modelMatrices[i][0];
                        LOG_F(INFO,"OpenXR hand model matrix: eye=%u values=%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g.",i,
                              a[0],a[1],a[2],a[3],a[4],a[5],a[6],a[7],a[8],a[9],a[10],a[11],a[12],a[13],a[14],a[15]);
                        a=modelProjections[i];
                        LOG_F(INFO,"OpenXR hand model projection: eye=%u values=%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g.",i,
                              a[0],a[1],a[2],a[3],a[4],a[5],a[6],a[7],a[8],a[9],a[10],a[11],a[12],a[13],a[14],a[15]);
                    }
                if (gripCapture)
                {
                    for (unsigned i=0;i<2;++i)
                    {
                        auto const &p=frame.views[i].pose; auto const &f=frame.views[i].fov;
                        LOG_F(INFO,"OpenXR floating eye: serial=%llu eye=%u pose=%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g fov=%.9g,%.9g,%.9g,%.9g.",
                              (unsigned long long)frame.serial,i,p.orientation.x,p.orientation.y,p.orientation.z,p.orientation.w,
                              p.position.x,p.position.y,p.position.z,f.angleLeft,f.angleRight,f.angleUp,f.angleDown);
                        float const *a=modelProjections[i];
                        LOG_F(INFO,"OpenXR floating projection: serial=%llu eye=%u values=%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g.",
                              (unsigned long long)frame.serial,i,a[0],a[1],a[2],a[3],a[4],a[5],a[6],a[7],a[8],a[9],a[10],a[11],a[12],a[13],a[14],a[15]);
                    }
                    for (unsigned index=0;index<modelCount;++index)
                    {
                        int const hand=models[index]->context.instance-1;
                        if (hand<0 || hand>1) continue;
                        auto const &g=grips[hand]; auto const &p=g.pose;
                        LOG_F(INFO,"OpenXR floating hand: serial=%llu hand=%d model=%d frame=%d root=%d,%d,%d pivot=%.9g,%.9g,%.9g pose=%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g.",
                              (unsigned long long)frame.serial,hand,g.context.modelid,g.context.cframe,g.root.x,g.root.y,g.root.z,g.pivot.x,g.pivot.y,g.pivot.z,
                              p.orientation.x,p.orientation.y,p.orientation.z,p.orientation.w,p.position.x,p.position.y,p.position.z);
                        for (unsigned i=0;i<2;++i)
                        {
                            float const *a=modelMatrices[i][index];
                            LOG_F(INFO,"OpenXR floating matrix: serial=%llu hand=%d eye=%u values=%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g.",
                                  (unsigned long long)frame.serial,hand,i,a[0],a[1],a[2],a[3],a[4],a[5],a[6],a[7],a[8],a[9],a[10],a[11],a[12],a[13],a[14],a[15]);
                        }
                    }
                }
            }
        }
        // Keep this frame's models for next frame's mirrors (the body with its head shown).
        mirrorModels.clear(); mirrorHasBody=false;
        for (unsigned index=0;index<modelCount;++index)
        {
            mirrorModels.push_back(*models[index]);
            if (models[index]==&ikBody)
            {
                mirrorModels.back().context.vertices=ikMirrorVertices();
                mirrorHasBody=true;
            }
            else if (models[index]==&bodyModel)
            {
                mirrorModels.back().context.hiddenSurfaces=0;
                mirrorHasBody=true;
            }
        }
        lap(xrTiming.models);
        auto const maskPrefix=std::getenv("EDUKE32_XR_TEST_MASK_ORACLE");
        bool const maskCapture=maskPrefix && maskPrefix[0] && singlePass && !fixtureTest && worldFrames==59;
        auto const drawMasks = [&](bool collect,NativeOracleTarget *oracle=nullptr) {
            bool accepted=true;
            for (unsigned i=0;i<2 && good;++i)
            {
                auto const &eye=eyes[i];
                good=runtime->bindEye(i,error);
                if (!good) return false;
                if (oracle && !oracle->copyEye(i,error)) { good=false; return false; }
                for (unsigned pass=0;pass<eye.passCount() && good;++pass)
                {
                auto const &view=eye.passes[pass];
                videoSetViewableArea(0,0,xdim-1,ydim-1);
                eyeState(eye,pass);
                // Begin before camera preparation, which captures this eye's
                // projection. Native sorting/animation of tiles stays intact.
                if (collect && !polymost_xrBeginCollection(POLYMOST_XR_MASKS,i))
                    return false; // Preflight rejection must skip editor/direct paths.
                int const scriptVisibility=g_visibility, scriptParallax=parallaxvisibility;
                g_visibility=frozenVisibility; parallaxvisibility=frozenParallax;
                renderPrepareMasksQ16(view.camera.pos.x,view.camera.pos.y,view.camera.pos.z,
                                     view.camera.angle,view.camera.horizon,view.camera.sector);
                g_visibility=scriptVisibility; parallaxvisibility=scriptParallax;
                if (!pass)
                {
                    polymost_xrRelativeWorldToClip(crosshairViews.matrix[i]);
                    crosshairViews.eye[i]=eye.camera.pos;
                }
                if (testArtClock()) totalclocklock=1;
                spritesortcnt=pristine.size();
                std::copy(pristine.begin(),pristine.end(),tsprite);
                for (int j=0;j<spritesortcnt;++j)
                    if (!(membership[j] & (1u<<(i*2+pass)))) tsprite[j].xrepeat=tsprite[j].yrepeat=0;
                maskwallcnt=view.walls.size();
                for (int j=0;j<maskwallcnt;++j) { maskwall[j]=j; thewall[j]=view.walls[j]; }
                if (maskCapture) polymost_xrObserveMaskInput(i,oracle!=nullptr);
                if (!collect) polymost_xrMeasureNativeMasks(i,g_frameCounter);
                renderDrawMasks();
                if (maskCapture) polymost_xrObserveMaskInput(-1,false);
                if (!collect) polymost_xrMeasureNativeMasks(-1,g_frameCounter);
                if (oracle && good)
                {
                    auto const prefix=std::string(maskPrefix)+"-reference-"+(i ? "right" : "left");
                    good=eduke_xr::captureFramebuffer((prefix+".ppm").c_str(),xdim,ydim,error)
                        && eduke_xr::captureFramebufferDepth((prefix+"-depth.bin").c_str(),xdim,ydim,error);
                }
                // Remaining draws in a rejected traversal stay suppressed.
                // A rejected begin for the next eye skips that traversal.
                if (collect && polymost_xrEndCollection(i) != POLYMOST_XR_COLLECT_OK)
                    accepted=false;
                }
            }
            return good && accepted;
        };
        if (singlePass && good)
        {
            char const *failure=std::getenv("EDUKE32_XR_TEST_FAIL");
            bool const maskFault=failure && !Bstrncmp(failure,"mask-",5);
            if (fixtureTest) SDL_setenv("EDUKE32_XR_TEST_MASK_PROBE_ARMED",g_frameCounter==12 ? "1" : "0",1);
            if (maskFault)
                SDL_setenv("EDUKE32_XR_TEST_MASK_ARMED",
                           (std::getenv("EDUKE32_XR_TEST_MASK_WITH_MODEL") ? usedHandModel && worldFrames==59
                            : (!fixtureTest || g_frameCounter == 12)) ? "1" : "0",1);
            auto const captureCollection = [&](char const *suffix) {
                auto const prefix=maskCapture ? maskPrefix : std::getenv("EDUKE32_XR_TEST_CAPTURE");
                return !prefix || runtime->captureFrame((std::string(prefix)+suffix).c_str(),false,error,true);
            };
            bool const snapshot=maskCapture || (fixtureTest && g_frameCounter == 12 && std::getenv("EDUKE32_XR_TEST_MASK_SNAPSHOT"));
            if (snapshot) good=captureCollection("-mask-before");
            if (maskCapture && good)
            {
                NativeOracleTarget oracle;
                drawMasks(false,&oracle);
            }
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
                        if (!reported || g_frameCounter == 12 || maskCapture
                            || (fixtureTest && g_frameCounter == 13 && testFailure("mask-voxel-cold")))
                        {
                            auto const stats=polymost_xrCollectionStats();
                            LOG_F(INFO,"OpenXR masks single-pass: frame=%u paired=%u eyeOnly=%u pairedVertices=%u eyeOnlyVertices=%u masks=%u translucent=%u depthOnly=%u depthWriteOff=%u voxels=%u voxelsPaired=%u indexedVoxelIndices=%llu",
                                  unsigned(g_frameCounter),stats.pairedCalls,stats.eyeOnlyCalls,stats.pairedVertices,stats.eyeOnlyVertices,
                                  stats.maskCalls,stats.translucentCalls,stats.depthOnlyCalls,stats.depthWriteOffCalls,
                                  stats.voxelCalls,stats.voxelPairedCalls,(unsigned long long)stats.voxelIndexedIndices);
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
            if (maskCapture && good && committed)
            {
                good=captureCollection("-replayed");
                if (good) LOG_F(INFO,"OpenXR native mask oracle replay captured: serial=%llu.",(unsigned long long)frame.serial);
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
        lap(xrTiming.masks);
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
        // Test hook: a harness writes an output prefix into the request file;
        // the next world frame captures both eyes there and removes the file.
        // With UI overlays the final composited frame is captured at
        // presentation instead (sdlayer_xr_presentMenu).
        if (good && !fixtureTest && !overlayEnabled())
            if (auto request=std::getenv("EDUKE32_XR_CAPTURE_REQUEST"))
                if (FILE *file=std::fopen(request,"r"))
                {
                    char prefix[1024]={};
                    bool const named=std::fgets(prefix,sizeof(prefix),file)!=nullptr;
                    std::fclose(file);
                    std::remove(request);
                    prefix[strcspn(prefix,"\r\n")]=0;
                    if (named && prefix[0])
                    {
                        good=runtime->captureFrame(prefix,false,error,true);
                        LOG_F(INFO,"OpenXR capture request: serial=%llu prefix=%s passes=%u,%u roll=%.4f,%.4f horizon=%.3f,%.3f ok=%d.",
                              (unsigned long long)frame.serial,prefix,eyes[0].passCount(),eyes[1].passCount(),
                              eyes[0].camera.roll,eyes[1].camera.roll,fix16_to_float(eyes[0].camera.horizon),
                              fix16_to_float(eyes[1].camera.horizon),int(good));
                    }
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
    bool const frameFinished=deferPresentation || runtime->finishFrame(good && !fixtureTest,endError);
    if (!frameFinished) { good=false; error += " "+endError; }
    if (!good && fixtureTest && testFailure("mask-voxel-replay-after"))
        LOG_F(INFO,"OpenXR voxel fault frame canceled: serial=%llu submitted=%llu emptyFinished=%d.",
              (unsigned long long)frame.serial,(unsigned long long)runtime->lastSubmittedSerial(),int(frameFinished));
    if (deferPresentation)
    {
        presentationRuntime=runtime; presentationGeneration=runtime->generation();
        worldReceipt={runtime,runtime->generation(),frame.serial,usedMultiview,usedMaskMultiview,!usedHandModel || usedModelMultiview,usedHandModel};
    }
    // Display-end callbacks must not observe the right eye's renderer globals.
    // Preserve script visibility mutations while rebuilding native derived fog.
    int const scriptVisibility=g_visibility, scriptParallax=parallaxvisibility;
    g_visibility=frozenVisibility; parallaxvisibility=frozenParallax;
    renderPrepareMasksQ16(logical.pos.x,logical.pos.y,logical.pos.z,
                         logical.angle,logical.horizon,logical.sector);
    g_visibility=scriptVisibility; parallaxvisibility=scriptParallax;
    if (!good)
    {
        polymost_xrWeaponTileConsumer=nullptr;
        handModelReceipt={};
        if (attemptedHandModel && std::getenv("EDUKE32_XR_TEST_MODELS"))
            LOG_F(INFO,"OpenXR hand model frame canceled: serial=%llu submitted=%llu.",
                  (unsigned long long)frame.serial,(unsigned long long)runtime->lastSubmittedSerial());
        sdlayer_xr_disableWorld(error.c_str());
    }
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
    if (timing)
    {
        xrTiming.total+=xrNowMs()-timingStart;
        if (++xrTiming.frames==120 && std::getenv("EDUKE32_XR_TEST_TIMING"))
        {
            double const n=xrTiming.frames;
            LOG_F(INFO,"OpenXR CPU ms/frame: opaque=%.2f animate=%.2f models=%.2f masks=%.2f world total=%.2f.",
                  xrTiming.opaque/n,xrTiming.animate/n,xrTiming.models/n,xrTiming.masks/n,xrTiming.total/n);
            xrTiming={};
        }
    }
    return good || animated;
}
#endif
