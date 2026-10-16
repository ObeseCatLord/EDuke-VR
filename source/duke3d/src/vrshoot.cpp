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
}

bool G_VRValidateShot(VRShotInput const &input)
{
    if (input.flags & ~(VRShotEnabled|VRShotValid)) return false;
    if (!(input.flags & VRShotEnabled) && input.flags) return false;
    if (!(input.flags & VRShotValid))
    {
        for (int i=0;i<3;++i) if (input.offset[i] || input.direction[i]) return false;
        return true;
    }
    int64_t const x=input.offset[0], y=input.offset[1], z=input.offset[2];
    // Unequal Build scales, checked without integer truncation or overflow.
    if ((x*x+y*y)*256+z*z > int64_t(MaxReach)*MaxReach*256) return false;
    int64_t length=0;
    for (int i=0;i<3;++i) length+=int64_t(input.direction[i])*input.direction[i];
    return length>=int64_t(32700)*32700 && length<=int64_t(32800)*32800;
}

bool G_VRDecodeShot(uint8_t const *bytes, size_t size, VRShotInput &input)
{
    if (size!=VRShotWireSize || bytes[0]!=1) return false;
    VRShotInput decoded; decoded.flags=bytes[1];
    for (int i=0;i<6;++i)
    {
        uint16_t const word=uint16_t(bytes[2+i*2])|(uint16_t(bytes[3+i*2])<<8);
        int const value=word<32768 ? int(word) : int(word)-65536;
        (i<3 ? decoded.offset[i] : decoded.direction[i-3])=int16_t(value);
    }
    if (!G_VRValidateShot(decoded)) return false;
    input=decoded; return true;
}

void G_VREncodeShot(VRShotInput const &input, uint8_t *bytes)
{
    bytes[0]=1; bytes[1]=input.flags;
    for (int i=0;i<6;++i)
    {
        uint16_t const word=uint16_t(i<3 ? input.offset[i] : input.direction[i-3]);
        bytes[2+i*2]=uint8_t(word); bytes[3+i*2]=uint8_t(word>>8);
    }
}

void G_VRSetShotInput(int player, VRShotInput const &input)
{
    if (unsigned(player)>=MAXPLAYERS || !G_VRValidateShot(input)) return;
    auto &state=shots[player];
    if (!(state.input.flags & VRShotEnabled) || !(input.flags & VRShotValid)
        || uint32_t(uint32_t(totalclock)-state.at)>MaxAge) state.blocked=true;
    state.input=input; state.at=uint32_t(totalclock);
}
VRShotInput G_VRGetShotInput(int player) { return unsigned(player)<MAXPLAYERS ? shots[player].input : VRShotInput{}; }
void G_VRResetShot(int player) { if (unsigned(player)<MAXPLAYERS) shots[player]={}; }
void G_VRResetShots() { for (auto &state:shots) state={}; }
bool G_VRShotEnabled(int player) { return unsigned(player)<MAXPLAYERS && (shots[player].input.flags & VRShotEnabled); }
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
        case SHOTSPARK1__: return works==PISTOL_WEAPON ? VRShotFeatureHitscan : 0;
        case SHOTGUN__: return works==SHOTGUN_WEAPON ? VRShotFeatureHitscan : 0;
        case CHAINGUN__: return works==CHAINGUN_WEAPON ? VRShotFeatureHitscan : 0;
        case GROWSPARK__: return works==GROW_WEAPON ? VRShotFeatureHitscan : 0;
        case RPG__: return works==RPG_WEAPON ? VRShotFeatureRPG : 0;
        case FREEZEBLAST__: return works==FREEZE_WEAPON ? VRShotFeatureFreezeShrink : 0;
        case SHRINKER__: return works==SHRINKER_WEAPON ? VRShotFeatureFreezeShrink : 0;
    }
#endif
    return false;
}
bool G_VRShotReady(int player)
{
    return G_VRShotEnabled(player) && (shots[player].input.flags & VRShotValid)
        && uint32_t(uint32_t(totalclock)-shots[player].at)<=MaxAge;
}
bool G_VRShotCanFire(int player) { return G_VRShotReady(player) && !shots[player].blocked; }
void G_VRFilterShotInput(int player, input_t &input)
{
    if (!G_VRShotEnabled(player)) return;
    auto &state=shots[player];
    bool const held=(input.bits & BIT(SK_FIRE)) || (input.extbits & BIT(EK_ALT_FIRE));
    if (!G_VRShotReady(player)) state.blocked=true;
    if (!held) state.blocked=false;
    if (!G_VRShotReady(player) || state.blocked)
    { input.bits &= ~BIT(SK_FIRE); input.extbits &= ~BIT(EK_ALT_FIRE); }
}

bool G_VRResolveShot(int player, vec3_t &position, int16_t &sect, bool &clamped)
{
    clamped=false;
    if (!G_VRShotReady(player)) return false;
    auto const p=g_player[player].ps;
    if (unsigned(p->i)>=MAXSPRITES || sprite[p->i].extra<=0 || p->newowner>=0 || p->over_shoulder_on || ud.recstat) return false;
    auto const input=shots[player].input;
    int64_t const anchorZ=int64_t(p->pos.z)+p->pyoff;
    if (anchorZ<INT32_MIN || anchorZ>INT32_MAX) return false;
    vec3_t const anchor={p->pos.x,p->pos.y,int32_t(anchorZ)};
    vec3_t const delta={input.offset[0],input.offset[1],input.offset[2]};
    for (int i=0;i<3;++i)
    {
        int64_t const sum=int64_t(i==0 ? anchor.x : i==1 ? anchor.y : anchor.z)+input.offset[i];
        if (sum<INT32_MIN || sum>INT32_MAX) return false;
    }
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
