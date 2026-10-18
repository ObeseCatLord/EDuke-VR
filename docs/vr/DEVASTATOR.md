# Native tracked Devastator

The ordinary Devastator now uses the existing RPG hand-origin/vector adapter
and feature1. The14byte movement tail and native packet layouts are unchanged.
Native network revision3 rejects prior builds whose feature1 did not include
Devastator; older-peer compatibility is not required.
Qualification here is CPU-native gameplay and multiplayer; headset presentation
and Devastator's model/muzzle attachment integration remain open.

## Incremental design

The behavioral reference is EDuke32's P_FireWeapon/delayed-burst code,
A_ShootHardcoded RPG branch, and original RPG actor. The pinned RazeXR historical
engine `e243dda6690b703146293437a13fcc71c5f3a80a`,
`Projects/Android/jni/Raze/source/games/duke/src/player_d.cpp:shootrpg`, retains
the same native reduced damage/size, random spread and alternating muzzle policy.

Adding Devastator to the existing selected-weapon/RPG-tile predicate reuses
native events, ammo, owner, delay, movement, damage and actor replication.
A new pose protocol or rocket simulation has no demonstrated incompatibility
to solve. No such layer was added. Custom SFLAG_PROJECTILE replacements stay
outside this hardcoded adapter.

A simple eligibility change exposed two concrete failures:

- A closed-wall resolved origin was safe, then the native post-insert barrel
  shift moved its centre to x1150, only2units from the wall at1152. Native radius
  clearance is16. The original negative is `work/devastator-wall-initial.json`.
- A four-shot CON-configured delayed burst lost tracking after one real rocket.
  Native A_Shoot rejected later actors but the burst still consumed4ammo.
  `work/devastator-loss-initial.json` records ammo36 with one actual projectile.

The existing resolver now accepts a native muzzle point, with the
same overflow, first obstruction, pushmove, sector and visibility checks. Tracked
Devastator barrels apply their original offsets to the already-constrained
hand root, then constrain that final point before insertion; flat paths
retain the original post-insert calculation and event timing. Native damage,
random draws and half-size still run in their original order. The post-EGS
WorksLike check remains at its original boundary, including script mutation.
The default hand-point path preserves the resolver used by other supported families.

Lost hand readiness now stops the existing native delayed-burst counter before
its ammo decrement. P_FireWeapon also refuses unready tracked shots before ammo
or another burst is queued. This reuses the existing enabled/valid/release
latch; it adds no grenade/weapon state machine or replicated latch. Flat and
unsupported custom paths keep native behavior.

## Actual proof

The CPU helper publishes simulated poses through **G_VRSetShotInput**, using
only two exported symbols in a separate test executable. The ordinary native
client negotiates its capabilities, serializes its own movement update and hand
tail, and receives real native server snapshots. Fire comes from native SDL
key events. There is no fake projectile, packet emulation, damage shortcut or
GL/OpenXR context. Bubblewrap hides GPU devices; process maps/handles are audited.

`smoke_devastator_cpu.py` uses the caller's read-only GRP and an owned CON/map
fixture. It observes POSTWEAPONSHOOT results, actual actor updates, real native
explosions, player ammo/health and native callbacks. A shared scripted seed at
PREWEAPONSHOOT makes projectile fields and subsequent RNG state comparable
without depending on process startup time; it is not a general ambient-RNG proof.

| Case | Result |
|---|---|
| Native flat reference/current | Four actual projectile records match in position, sector, angle, velocity, owner, size, damage and post-shot RNG state; burst ammo and8clock-unit delayed cadence agree. Both actual sessions cause replicated target damage. |
| Tracked horizontal |19checks pass: constrained hand/alternating barrel positions, native two-shot cadence/ammo/half-size/damage, native client actors, actual explosions and replicated target health reduction; real nonconstant native F12 frames change after firing. |
| Closed wall |13checks pass for a near-parallel inward trajectory: final centres stay inside radius clearance, actual client actor indices and native ammo converge. |
| Vertical |14checks pass, zero horizontal speed and native Z velocity near-10304 plus original random spread; actual native client actors observed. A tall ceiling keeps the projectile alive through snapshots. |
| Tracking loss |14checks pass with four-shot configured burst: one rocket/ammo39, pending counter canceled, held recovery cannot fire; release/new press yields the four-shot native burst and final ammo35. |
| Native pipebomb regression |14checks pass on the current normal CPU build: native hold/release/ammo/owner/fuse/trajectory/client replication/remote detonation/F12. |

Source/result paths: `work/devastator-flat-reference.json`,
`work/devastator-{flat,tracked,wall,vertical,loss}-net3.json` (final source),
`work/devastator-native-comparison.json` (earlier matching flat comparison),
`work/pipebomb-devastator-regression.json`. Per-run result JSONs and logs remain
in their referenced ignored evidence directories.

Retained failed fixtures matter: after the source correction, the original
almost-tangent wall and low-ceiling vertical runs could finish native projectile
lifetimes before a world snapshot. Their corrected server muzzle/physics were
observed, but live-client-actor gates timed out (`...wall-final.json`,
`...vertical-final.json`). The final scenarios deliberately retain real flight
long enough to observe it. They do **not** prove that every very short-lived
projectile/effect reaches every native client. The client-index check is exactly
that: receipt of those indices, not a generation/lifetime identity guarantee
when the allocator reuses one. Arbitrary loss/WAN and transient effect delivery
remain open native multiplayer qualification.

## Reproduce without GPU

Build the normal CPU prerequisite plus a separately named input-test executable:

```sh
make -j4 USE_OPENGL=0 POLYMER=0 obj=work/obj-cpu \
  LDFLAGS='-Wl,--export-dynamic-symbol=_Z16G_VRSetShotInputiRK11VRShotInput -Wl,--export-dynamic-symbol=myconnectindex' \
  duke3d_game=work/eduke32-cpu-input work/eduke32-cpu-input
c++ -fPIC -shared -Wall -Wextra -Werror tools/vr/sdl_dummy_vr_input.cpp \
  -o work/headless_vr_input.so $(pkg-config --cflags --libs sdl2) -ldl
python3 tools/vr/smoke_devastator_cpu.py \
  --binary work/eduke32-cpu-input --input-helper work/headless_vr_input.so \
  --grp /path/to/owned/DUKE3D.GRP --work-dir work/devastator-cpu --case tracked
```

Cases: flat, tracked, wall, vertical, loss. `--reference-result` with flat compares
a saved passing native reference. Export only the required symbols: exporting
all unused CPU functions retains SDL_GL_GetDrawableSize, which the existing
strict CPU-binary gate rejects. The normal game executable needs no exports or
helper. Native, XR and normal CPU builds compile (`work/build-*-devastator-net3.log`); no GPU test was launched for
this change during the current GPU hold.

Final-source revision3 cases pass77checks across the five scenarios. The flat
case includes the exact pre-slice projectile/RNG and burst-ammo comparison. The
tracked case additionally captures native CPU frames before/after firing.
`work/devastator-protocol3-rejection.json` passes the real older-client rejection
check: a revision2 native executable cannot enter revision3 gameplay. No auth
packet was manufactured. All current native layouts are otherwise unchanged.
