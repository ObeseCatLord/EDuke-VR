# Native World Tour tracked flamethrower

The stock World Tour weapon12 fires `FIREBALL` (tile5163). Its native primary
and five trail children remain FIREBALL actors; `FLAMETHROWERFLAME` is also a
separate native attack and damage attribution, not the stock player's emitted
tile. This increment adapts the stock player weapon, without replacing its
`Shoots` default or implementing a separate flame simulation.

## Native boundary and architecture

Compared with a replacement projectile/particle system, the smallest adapter
is the existing `A_ShootHardcoded` FIREBALL branch. Native loading, weapon
counter/reset, ammo, PRE/POST events, insertion, damage random draw, owner/yvel,
repeat40, collision, gravity, tracer children, lava and damage attribution all
remain reusable. No incompatibility requires replacing those components.

The demonstrated missing boundary was its body-relative muzzle and horizon
velocity. For a supported tracked player, the existing constrained hand resolver
supplies position/sector and the existing physical projectile helper supplies
yaw and normalized XY/Z velocity. Native flat offsets apply only to the original
path. `A_GetShootZvel` remains after the conversion, preserving explicit native
Z-velocity overrides. World/NPC attacks and unsupported replacements retain
their native paths. The separate FLAMETHROWERFLAME attack is not promoted here.

The native movement uses trig-scaled XY and direct Build Z. Thus a stationary
horizontal shot has xvel840/zvel0; a vertical upward shot has xvel0/zvel-13440.
Native first-tick owner-motion coupling, half step and subsequent +200 gravity
remain. Trail actor behavior is unchanged, including its existing angle/owner
initialization; no cosmetic correction is mixed into this adapter.

Feature64 extends the existing staged capability mask63 to127. Both peers
qualify it before hand firing/presentation. The nine-byte capability message,
fourteen-byte movement tail, native network revision4 and native actor snapshots
retain their layout. Rebuild matching peers; older-peer compatibility is not an
acceptance requirement. Existing readiness/release gates own tracking loss,
including delayed native firing before ammo/events. No extra pose or weapon
state machine is added.

## Qualification

`tools/vr/smoke_flame_cpu.py` loads the user's read-only loose World Tour
CON/ART files in private labs; the GRP alone contains Atomic scripts and cannot
establish this test. It equips the actual default weapon without overriding its
Shoots/timing, drives real dedicated server/client input, and observes native
POST shot fields, live actors, applied authoritative snapshots and target health.
The GPU-denied SDL-dummy namespace audits both native processes for GPU device
or library access. Simulated poses use the native setter, not OpenXR.

Seven cases pass: flat reference, tracked, closed wall, vertical, tracking loss,
underwater and PRE-event cancellation. Flat spawn fields, controlled random
state and ammo match the saved pre-adapter executable exactly. Flat and tracked
target health converge1000→926 on server/client. Tracked primary origin is
(1216,4173,-8109), sector1, while its body remains in sector0; the closed wall
constrains it to sector0/x1125. Vertical fire returns xvel0/zvel-13440. Invalid
tracking and held recovery consume no ammo; release/new press resumes native
shots. Underwater consumes ammo before its original early return without
PRE/POST/projectiles; PRE cancellation retains native ammo/PRE and no POST.
Immediate wall hits can die before a snapshot, so that case proves both native
firing paths and authoritative clearance, not guaranteed transient delivery.

The saved first reference invocation accidentally entered the reused Devastator
runner; it is excluded. A corrected entry point produced the actual WT baseline.
An early tracked target fixture lay outside the physical ray and timed out;
the target was moved onto the independently calculated ray, with no gameplay
change. Earlier records remain preserved.

The first actual software-XR run passed all gameplay/presentation checks except
one card-edge oracle pixel (right maximum12). A freezer regression exposed the
same missing oracle operation (right maximum64). CPU artifact investigation
proved native homogeneous clipping occurs before viewport/subpixel snapping;
the oracle previously snapped the un-clipped offscreen corners. It now clips
triangles first and applies top-left coverage, retaining independent eye-ray
sampling and the original two-channel-value limit. Both preserved captures
then have maximum error1 in each eye. This changes the test, not the renderer;
no boundary epsilon or pixel tolerance relaxation was introduced.

OpenXR/controller/graphics qualification and final results are recorded in
VALIDATION.md and sibling `evidence/flamethrower-validation.json`. These bounded
tests do not establish physical headset feel, complete weapon models/body IK,
arbitrary CON/projectile overrides, general SPS or WAN compatibility.

## Reproduce the CPU proof

Use the separately linked CPU-input executable and private SDL helper documented
in DEVASTATOR.md, then run:

```sh
python3 tools/vr/smoke_flame_cpu.py \
  --binary work/eduke32-cpu-input --input-helper work/headless_vr_input.so \
  --grp '/path/to/World Tour/DUKE3D.GRP' --work-dir work --case tracked
```

The preserved native baseline can be rerun with `--case flat --native-reference`
against `work/eduke32-cpu-input-before-flame`. Feed its result to the current
binary with `--reference-result /absolute/path/to/result.json` for exact native
spawn/random/ammo comparison. All generated labs are owned outputs; installed
game files remain untouched and outside Git.
