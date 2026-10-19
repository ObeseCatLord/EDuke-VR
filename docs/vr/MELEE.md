# Native tracked kick and quick-kick

> **Superseded (2026-10-19):** the mighty foot is no longer a hand-tracked melee ray. Selected
> kicks and quick kicks leave the body like the native kick and go where the **head** looks (the
> shot sample now carries the head direction), with a 3D boot shown swinging out. The hand-melee
> validation below (`smoke_melee_hand.py`, removed) documents the earlier design only.


The native selected KNEE weapon and quick-kick counter now use the constrained
physical hand ray. Native windup, damage, steroid bonus, smoke, switches,
ownership, ammo and actor simulation remain in EDuke32. This is a hand-aimed
native kick adapter; foot tracking and full-body IK remain integration work.

## Reference and adapter

EDuke32 P_ProcessWeapon/P_FireWeapon drive selected kicks. P_HandleSharedKeys
starts quick_kick=14; P_DoCounters calls A_Shoot(KNEE) at8, independently of the
selected weapon. A_ShootHardcoded/Proj_HandleKnee handle contact and effects.
The pinned RazeXR historical engine e243dda6690b703146293437a13fcc71c5f3a80a
dispatch.cpp selects shoot_d_override, whose controller-derived origin/aim
also reaches shootknee. Its temporary player-struct mutation is not copied.

The local tripmine hitscan helper is renamed P_HandWeaponHitscan and reused for
melee: existing readiness, constrained hand origin/sector, physical vector,
owner cstat restoration and explicit CON Z override. Selected melee requires
the native KNEE/Shoots/WorksLike match. The native quick counter at8 explicitly
permits the ordinary KNEE while another weapon is selected. Custom projectile
replacement still uses its original path. NPC, blood-splat and flat kick paths
keep their native logic.

Tracked contact follows the physical ray without the flat body's6<<8 Z and15
angle offsets. That keeps nominal aiming reticle and physical hit line aligned.
Native1024 Manhattan reach from the resolved origin extends to physical Z:
`(abs(dx)+abs(dy))*16+abs(dz)<1024*16`. A vertical ceiling contact therefore has
finite reach. This uses int64 differences and does not move player state.

Right stick click maps to native Quick_Kick. Pose/focus/reference recovery
blocks that raw button along with Fire, and keeps the pose invalid until the
blocked source is released. The existing native readiness/release latch now
includes Fire, alternate Fire and Quick_Kick as one held group. There is no new
replicated counter, gesture state or damage protocol. Current controller-button
behavior is compiled but not yet exercised through OpenXR during the GPU hold.

## Observed failures and fixes

The first quick-loss run showed post-filter input bits0 and no damage while
tracking was invalid, but native quick counters kept restarting. On release and
new press two actual impacts damaged the target. P_HandleSharedKeys runs before
P_ProcessInput's filter, so it had already consumed raw Quick_Kick each tick.
G_VRQuickKickBlocked now gates that earlier handler using the same capability
and readiness state. It does not run the mutating release filter a second time
on already-filtered input. The original failed case is
`work/melee-hand-quick-loss-initial.json`.

A mixed-build native probe also demonstrated an incompatible older server:
it never acknowledged melee capability, yet raw quick input made a body-aimed
KNEE at(1599,4122,-7392), angle15, and real target health100→86. The new client
had a valid pistol hand pose; the old quick handler did not know how to refuse
it. `work/melee-oldserver-probe.json` records that actual session. The existing
NETVERSION guard advances3→4 to require matching builds, consistent with the
user's lack of an older-peer compatibility requirement. No packet fields are
added: feature32 upgrades mask31→63, capability messages remain9bytes and the
pose movement tail14bytes. A new compatibility layer is unnecessary.

The initial steroids test prepared inventory before native join initialization
finished and the joining player's inventory was overwritten. That was fixture
setup, not evidence of a melee damage defect. The final steroid test sets100
controlled native inventory in PREWEAPONSHOOT, then observes the original bonus
in actual target damage. It never assigns damage or creates a kick actor.

## Actual CPU multiplayer proof

`smoke_melee_native.py` drives real RCTRL and private Q bindings in a dedicated
server/client session. The immutable pre-adapter CPU input executable is
`work/eduke32-cpu-input-before-melee`, SHA256
`a8ac0af1a51d2a31a8564cec054dfb44ff1eda2d7af7b7b5ae81c9dccd514f6a`.
Selected kick reaches frame7; quick-kick reaches counter8 while pistol stays
selected. Real KNEE callbacks, target damage convergence, unchanged ammo and
too-far rejection are observed. Current flat results compare original impact
position/sector/angle/owner/initial EGS strength and ammo against that reference.
EGS strength is measured before native random damage/bonus; this is not an
ambient-RNG equivalence assertion. Transient client actor callbacks alone are
not required to establish damage replication.

`smoke_melee_hand.py` uses simulated poses through the existing native setter.
The real client negotiates, serializes its own input/pose and receives native
server snapshots; input is ordinary SDL in an owned FIFO. Bubblewrap hides GPU
devices and process maps/handles are audited. No fake packets, hit actors,
damage commands, OpenXR or GL context are involved.

The ten cases cover selected/quick actual target damage, pitched contact,
closed-wall clamping/contact without behind-wall damage, out-of-reach target,
near/far vertical ceilings, selected/quick tracking loss and held recovery,
and native steroids bonus. The quick-loss case now reaches zero counters
without queued restarts, suppresses every held native Quick_Kick sample, and
allows one impact only after release/new press. Real F12 shows the native scene.

Result paths, build hashes and protocol rejection are recorded with the final
checkpoint in `outputs/evidence/melee-native-validation.json`. The baseline
CPU input build/helper commands are in [DEVASTATOR.md](DEVASTATOR.md).

```sh
python3 tools/vr/smoke_melee_hand.py \
  --binary work/eduke32-cpu-input --input-helper work/headless_vr_input.so \
  --grp /path/to/owned/DUKE3D.GRP --work-dir work/melee-hand \
  --case quick-loss
```

Native/OpenXR/CPU compilation and these CPU gameplay tests do not establish
headset input, model/foot attachment, complete SPS, WAN/loss, arbitrary mods or
physical comfort/performance. Full VR remains incomplete.
