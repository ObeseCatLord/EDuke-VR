// SPDX-License-Identifier: GPL-2.0-only
#include "duke3d.h"
#include "vrshoot.h"
#include <algorithm>
#include <cmath>

namespace
{
struct ShotState { VRShotInput input; uint32_t at=0; bool blocked=true; };
ShotState shots[MAXPLAYERS];
constexpr int MaxReach=768; // 2 metres; native horizontal384/metre, Z6144/metre.
constexpr uint32_t MaxAge=30; // .25s on the existing120Hz native clock.
// A frame hitch delays samples without invalidating tracking; only a long gap
// (pause, reconnect) re-arms the trigger release gate.
constexpr uint32_t ReleaseGapAge=240;
}

bool G_VRValidateShot(VRShotInput const &input)
{
    if (!(input.flags & VRShotEnabled) && input.flags) return false;
    // A throw speed needs a valid hand sample to carry its direction.
    if ((input.flags & VRShotThrowMask) && !(input.flags & VRShotValid)) return false;
    if (!(input.flags & VRShotValid))
    {
        for (int i=0;i<3;++i) if (input.offset[i] || input.direction[i] || input.head[i]) return false;
        return input.use==0;
    }
    auto const unit=[](int16_t const *v) {
        int64_t length=0;
        for (int i=0;i<3;++i) length+=int64_t(v[i])*v[i];
        return length>=int64_t(32700)*32700 && length<=int64_t(32800)*32800;
    };
    // The head direction is optional (all zero: kicks keep the body's angle).
    if ((input.head[0] || input.head[1] || input.head[2]) && !unit(input.head)) return false;
    if (input.use>2048) return false;
    int64_t const x=input.offset[0], y=input.offset[1], z=input.offset[2];
    // Unequal Build scales, checked without integer truncation or overflow.
    if ((x*x+y*y)*256+z*z > int64_t(MaxReach)*MaxReach*256) return false;
    return unit(input.direction);
}

bool G_VRDecodeShot(uint8_t const *bytes, size_t size, VRShotInput &input)
{
    if (size!=VRShotWireSize || bytes[0]!=2) return false;
    VRShotInput decoded; decoded.flags=bytes[1];
    for (int i=0;i<9;++i)
    {
        uint16_t const word=uint16_t(bytes[2+i*2])|(uint16_t(bytes[3+i*2])<<8);
        int const value=word<32768 ? int(word) : int(word)-65536;
        (i<3 ? decoded.offset[i] : i<6 ? decoded.direction[i-3] : decoded.head[i-6])=int16_t(value);
    }
    decoded.use=uint16_t(bytes[20])|(uint16_t(bytes[21])<<8);
    if (!G_VRValidateShot(decoded)) return false;
    input=decoded; return true;
}

void G_VREncodeShot(VRShotInput const &input, uint8_t *bytes)
{
    bytes[0]=2; bytes[1]=input.flags;
    bytes[20]=uint8_t(input.use); bytes[21]=uint8_t(input.use>>8);
    for (int i=0;i<9;++i)
    {
        uint16_t const word=uint16_t(i<3 ? input.offset[i] : i<6 ? input.direction[i-3] : input.head[i-6]);
        bytes[2+i*2]=uint8_t(word); bytes[3+i*2]=uint8_t(word>>8);
    }
}

void G_VRSetShotInput(int player, VRShotInput const &input)
{
    if (unsigned(player)>=MAXPLAYERS || !G_VRValidateShot(input)) return;
    auto &state=shots[player];
    if (!(state.input.flags & VRShotEnabled) || !(input.flags & VRShotValid)
        || uint32_t(uint32_t(totalclock)-state.at)>ReleaseGapAge) state.blocked=true;
    state.input=input; state.at=uint32_t(totalclock);
}
int G_VRUseAngle(int player, int fallback)
{
    if (unsigned(player)>=MAXPLAYERS) return fallback;
    auto const &state=shots[player];
    if (!(state.input.flags & VRShotValid) || !state.input.use || uint32_t(uint32_t(totalclock)-state.at)>MaxAge) return fallback;
    return (state.input.use-1)&2047;
}
VRShotInput G_VRGetShotInput(int player) { return unsigned(player)<MAXPLAYERS ? shots[player].input : VRShotInput{}; }
void G_VRResetShot(int player, bool preserveMode)
{
    if (unsigned(player)>=MAXPLAYERS) return;
    bool const enabled=preserveMode && (shots[player].input.flags & VRShotEnabled);
    shots[player]={};
    if (enabled)
    {
        // Respawn invalidates the pose, not the held-trigger release gate.
        // A native input already in flight must not escape through flat mode.
        shots[player].input.flags=VRShotEnabled;
        shots[player].blocked=true;
    }
}
void G_VRResetShots() { for (auto &state:shots) state={}; }
bool G_VRShotEnabled(int player) { return unsigned(player)<MAXPLAYERS && (shots[player].input.flags & VRShotEnabled); }
int G_VRShotThrowVelocity(int player)
{
    if (unsigned(player)>=MAXPLAYERS) return 0;
    int const units=(shots[player].input.flags & VRShotThrowMask)>>VRShotThrowShift;
    // Native pipebombs lose 5 xvel per tick (ground and air), so a literal
    // conversion of hand speed only rolls a bomb a metre or two. Map hand speed
    // onto the native throw range instead: a 2 m/s lob ~ a native tap throw
    // (140), a firm 4 m/s throw ~ 8 m, a hard 8 m/s throw ~ 25 m.
    return units ? std::min(600,int(64.f+units*VRShotThrowStep*48.f)) : 0;
}
bool G_VRShotPhysicalThrow(int player) { return unsigned(player)<MAXPLAYERS && (shots[player].input.flags & VRShotPhysical); }
bool G_VRShotDetonate(int player) { return unsigned(player)<MAXPLAYERS && (shots[player].input.flags & VRShotDetonate); }
uint8_t G_VRHandShotFeature(int player, int tile)
{
#ifndef EDUKE32_STANDALONE
    if (unsigned(player)>=MAXPLAYERS || !g_player[player].ps) return false;
    int const weapon=g_player[player].ps->curr_weapon;
    if (unsigned(weapon)>=MAX_WEAPONS) return false;
    int const shoots=PWEAPON(player,weapon,Shoots);
    if (tile<0) tile=shoots;
    if (unsigned(tile)>=MAXTILES || tile!=shoots || A_CheckSpriteTileFlags(tile,SFLAG_PROJECTILE)) return false;
    int const works=PWEAPON(player,weapon,WorksLike);
    switch (tileGetMapping(tile))
    {
        case KNEE__: return works==KNEE_WEAPON ? VRShotFeatureMelee : 0;
        case SHOTSPARK1__: return works==PISTOL_WEAPON ? VRShotFeatureHitscan : 0;
        // Mods may use the native shotgun ray with pistol timing (AA's Duke
        // sidearm). The live Shoots/custom-projectile checks above still own
        // eligibility; native firing, spread, events and damage are unchanged.
        case SHOTGUN__: return (works==SHOTGUN_WEAPON || works==PISTOL_WEAPON) ? VRShotFeatureHitscan : 0;
        case CHAINGUN__: return works==CHAINGUN_WEAPON ? VRShotFeatureHitscan : 0;
        case GROWSPARK__: return works==GROW_WEAPON ? VRShotFeatureHitscan : 0;
        case RPG__: return (works==RPG_WEAPON || works==DEVISTATOR_WEAPON) ? VRShotFeatureRPG : 0;
        case FREEZEBLAST__: return works==FREEZE_WEAPON ? VRShotFeatureFreezeShrink : 0;
        case SHRINKER__: return works==SHRINKER_WEAPON ? VRShotFeatureFreezeShrink : 0;
        case HEAVYHBOMB__: return works==HANDBOMB_WEAPON ? VRShotFeatureHandBomb : 0;
        case HANDHOLDINGLASER__: return works==TRIPBOMB_WEAPON ? VRShotFeatureTripmine : 0;
        case FIREBALL__: return WORLDTOUR && works==FLAMETHROWER_WEAPON ? VRShotFeatureFireball : 0;
    }
#endif
    return false;
}
bool G_VRShotReady(int player)
{
    return G_VRShotEnabled(player) && (shots[player].input.flags & VRShotValid)
        && uint32_t(uint32_t(totalclock)-shots[player].at)<=MaxAge;
}
// Presentation (held model, crosshair) follows the live pose and survives a
// frame hitch; only firing requires a fresh sample.
bool G_VRShotValid(int player)
{
    return G_VRShotEnabled(player) && (shots[player].input.flags & VRShotValid);
}
bool G_VRShotCanFire(int player) { return G_VRShotReady(player) && !shots[player].blocked; }
void G_VRBlockShot(int player) { if (unsigned(player)<MAXPLAYERS) shots[player].blocked=true; }
bool G_VRQuickKickBlocked(int player)
{
    return G_VRShotEnabled(player) && (!G_VRShotCanFire(player));
}
void G_VRFilterShotInput(int player, input_t &input)
{
    if (!G_VRShotEnabled(player)) return;
    auto &state=shots[player];
    bool const held=(input.bits & (BIT(SK_FIRE)|BIT(SK_QUICK_KICK))) || (input.extbits & BIT(EK_ALT_FIRE));
    if (!G_VRShotReady(player)) state.blocked=true;
    if (!held) state.blocked=false;
    if (held && (!G_VRShotReady(player) || state.blocked) && std::getenv("EDUKE32_XR_TEST_SHOTS"))
    {
        static uint32_t lastLog;
        if (uint32_t(uint32_t(totalclock)-lastLog)>=60)
        {
            lastLog=uint32_t(totalclock);
            LOG_F(INFO,"VR fire filtered: player=%d enabled=%d valid=%d age=%u blocked=%d.",player,!!(state.input.flags & VRShotEnabled),
                  !!(state.input.flags & VRShotValid),uint32_t(uint32_t(totalclock)-state.at),state.blocked);
        }
    }
    if (!G_VRShotReady(player) || state.blocked)
    { input.bits &= ~(BIT(SK_FIRE)|BIT(SK_QUICK_KICK)); input.extbits &= ~BIT(EK_ALT_FIRE); }
    if (G_VRQuickKickBlocked(player)) input.bits &= ~BIT(SK_QUICK_KICK);
}

bool G_VRResolveShot(int player, vec3_t &position, int16_t &sect, bool &clamped, vec3_t const *muzzlePosition)
{
    clamped=false;
    // Firing callers gate on G_VRShotCanFire (fresh sample); the held-weapon
    // presentation resolves its muzzle every frame and only needs validity.
    if (!G_VRShotValid(player)) return false;
    auto const p=g_player[player].ps;
    if (unsigned(p->i)>=MAXSPRITES || sprite[p->i].extra<=0 || p->newowner>=0 || p->over_shoulder_on || ud.recstat) return false;
    auto const input=shots[player].input;
    int64_t const anchorZ=int64_t(p->pos.z)+p->pyoff;
    if (anchorZ<INT32_MIN || anchorZ>INT32_MAX) return false;
    vec3_t const anchor={p->pos.x,p->pos.y,int32_t(anchorZ)};
    int64_t const requested[3]={muzzlePosition ? int64_t(muzzlePosition->x)-anchor.x : input.offset[0],
                                muzzlePosition ? int64_t(muzzlePosition->y)-anchor.y : input.offset[1],
                                muzzlePosition ? int64_t(muzzlePosition->z)-anchor.z : input.offset[2]};
    for (int i=0;i<3;++i)
    {
        int64_t const sum=int64_t(i==0 ? anchor.x : i==1 ? anchor.y : anchor.z)+requested[i];
        if (requested[i]<INT32_MIN || requested[i]>INT32_MAX || sum<INT32_MIN || sum>INT32_MAX) return false;
    }
    vec3_t const delta={int32_t(requested[0]),int32_t(requested[1]),int32_t(requested[2])};
    position={anchor.x+delta.x,anchor.y+delta.y,anchor.z+delta.z};
    int16_t const bodySector=p->cursectnum;
    if (unsigned(bodySector)>=unsigned(numsectors)) return false;
    sect=bodySector;
    // A point-sized body-to-hand ray cannot skip a blocking wall/actor or
    // ceiling/floor. Keep the projectile16-unit radius inside the first hit.
    double const length=std::sqrt(double(delta.x)*delta.x+double(delta.y)*delta.y+double(delta.z)*delta.z/256.);
    if (length>0.)
    {
        auto &owner=sprite[p->i]; auto const cstat=owner.cstat;
        owner.cstat &= ~(CSTAT_SPRITE_BLOCK|CSTAT_SPRITE_BLOCK_HITSCAN);
        hitdata_t hit; hitscan(&anchor,bodySector,delta.x,delta.y,delta.z,&hit,CLIPMASK1);
        owner.cstat=cstat;
        if (hit.sect>=0)
        {
            double const distance=std::sqrt((double(hit.x)-anchor.x)*(double(hit.x)-anchor.x)+(double(hit.y)-anchor.y)*(double(hit.y)-anchor.y)
                                           +(double(hit.z)-anchor.z)*(double(hit.z)-anchor.z)/256.);
            if (distance<length+32.)
            {
                double const amount=std::max(0.,std::min(length,distance-32.))/length;
                position={anchor.x+int32_t(std::lround(delta.x*amount)),anchor.y+int32_t(std::lround(delta.y*amount)),
                          anchor.z+int32_t(std::lround(delta.z*amount))};
                clamped=true;
            }
        }
    }
    updatesectorz(position.x,position.y,position.z,&sect);
    if (sect<0) return false;
    auto const before=position;
    // Native radius clearance also handles glancing approaches, where backing
    // along the ray alone can leave a projectile centre too close to a wall.
    if (pushmove(&position,&sect,16,256,256,CLIPMASK1)<0 || sect<0) return false;
    clamped=clamped || position.x!=before.x || position.y!=before.y || position.z!=before.z;
    return cansee(anchor.x,anchor.y,anchor.z,bodySector,position.x,position.y,position.z,sect);
}

namespace
{
struct BodyPoseState { VRBodyPose pose; double at=-1.; bool valid=false; };
BodyPoseState bodyPoses[MAXPLAYERS];
VRBodyPose publishedPose;
bool posePending;
uint16_t poseSequence;
double poseNow() { return double(timerGetNanoTicks())/double(timerGetNanoTickRate()); }

// Field order on the wire after the version byte (all little endian).
template <typename Visit> void visitBodyPose(VRBodyPose &p, Visit &&visit)
{
    visit.u16(p.sequence); visit.u8(p.flags);
    for (auto &v:p.hand) visit.u8(v);
    for (auto &v:p.pull) visit.u8(v);
    visit.u8(p.kick);
    visit.s16(p.bodyAngle);
    for (auto &v:p.eye) visit.s16(v);
    for (auto &v:p.headForward) visit.s16(v);
    for (auto &v:p.headUp) visit.s16(v);
    auto frame=[&](VRBodyFrame &f) { for (auto &v:f.root) visit.s16(v); for (auto &v:f.axes) visit.s16(v); };
    frame(p.handFrame[0]); frame(p.handFrame[1]);
    visit.s16(p.weaponTile); visit.s16(p.weaponFrame); visit.s16(p.weaponNextFrame); visit.u8(p.weaponLerp);
    frame(p.weapon);
}
struct PoseWriter
{
    uint8_t *at;
    void u8(uint8_t v) { *at++=v; }
    void u16(uint16_t v) { *at++=uint8_t(v); *at++=uint8_t(v>>8); }
    void s16(int16_t v) { u16(uint16_t(v)); }
};
struct PoseReader
{
    uint8_t const *at;
    void u8(uint8_t &v) { v=*at++; }
    void u16(uint16_t &v) { v=uint16_t(at[0]|(at[1]<<8)); at+=2; }
    void s16(int16_t &v) { uint16_t w; u16(w); v=int16_t(w); }
};
bool unitVector(int16_t const *v)
{
    int64_t const length=int64_t(v[0])*v[0]+int64_t(v[1])*v[1]+int64_t(v[2])*v[2];
    return length>=int64_t(31000)*31000 && length<=int64_t(34000)*34000;
}
}

bool G_VRDecodeBodyPose(uint8_t const *bytes, size_t size, VRBodyPose &pose)
{
    if (size!=VRBodyWireSize || bytes[0]!=1) return false;
    VRBodyPose decoded;
    visitBodyPose(decoded,PoseReader{bytes+1});
    if (decoded.flags & ~(VRBodyHead|VRBodyWeapon)) return false;
    if (decoded.hand[0]>=VRHandKinds || decoded.hand[1]>=VRHandKinds) return false;
    if ((decoded.flags & VRBodyHead) && (!unitVector(decoded.headForward) || !unitVector(decoded.headUp))) return false;
    if ((decoded.flags & VRBodyWeapon) && (decoded.weaponTile<0 || decoded.weaponTile>=MAXTILES
        || decoded.weaponFrame<0 || decoded.weaponNextFrame<0)) return false;
    pose=decoded; return true;
}

void G_VREncodeBodyPose(VRBodyPose const &pose, uint8_t *bytes)
{
    bytes[0]=1;
    auto copy=pose;
    visitBodyPose(copy,PoseWriter{bytes+1});
}

void G_VRPublishBodyPose(VRBodyPose const &pose)
{
    publishedPose=pose; publishedPose.sequence=++poseSequence; posePending=true;
}

bool G_VRTakeBodyPose(uint8_t *bytes)
{
    if (!posePending) return false;
    posePending=false;
    G_VREncodeBodyPose(publishedPose,bytes);
    return true;
}

void G_VRStoreBodyPose(int player, VRBodyPose const &pose)
{
    if (unsigned(player)>=MAXPLAYERS) return;
    auto &state=bodyPoses[player];
    double const now=poseNow();
    // Unsequenced packets: drop older ones, unless the stream restarted (a second of silence).
    if (state.valid && now-state.at<1. && int16_t(uint16_t(pose.sequence-state.pose.sequence))<=0) return;
    state.pose=pose; state.at=now; state.valid=true;
}

bool G_VRGetBodyPose(int player, VRBodyPose &pose, double maxAge)
{
    if (unsigned(player)>=MAXPLAYERS || !bodyPoses[player].valid || poseNow()-bodyPoses[player].at>maxAge) return false;
    pose=bodyPoses[player].pose;
    return true;
}

void G_VRResetBodyPoses() { for (auto &state:bodyPoses) state={}; posePending=false; }
