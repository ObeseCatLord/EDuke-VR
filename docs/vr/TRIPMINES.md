# Native tracked tripmines

The ordinary HANDHOLDINGLASER/TRIPBOMB weapon now uses the constrained tracked
hand ray for both its initial placement check and its later native commit.
This is CPU-native gameplay/multiplayer qualification; current tripmine headset
presentation and model attachments remain unqualified during the GPU hold.

## Adapter and behavioral reference

EDuke32's original P_ProcessWeapon press check, P_FireWeapon ammo/events,
A_ShootHardcoded insertion and TRIPBOMB actor are the reference. The minimal
adapter reuses the existing hand resolver, physical hitscan ray and negotiated
movement tail. There is no new weapon, trap simulation, actor or protocol layer.

The press-time native wall/sector/forcefield/masked-wall/occupied-surface policy
is factored once. Tracked commit repeats it against the current hand hit rather
than trusting the earlier animation-start check. The native flat commit keeps
its original narrower checks and event timing. Difference calculations use
bounded int64 arithmetic so distant hits cannot overflow into legal range.

Native body XY reach stays strictly below290 Build units. Tracked hits also
require physical hand-to-hit distance below290 (Z uses the native16:1 scale),
about0.755metres. A nearly vertical ray can otherwise hit arbitrarily far up a
tall wall while satisfying the original XY-only test. The hand origin still
uses first-obstruction, radius clearance, valid sector and body visibility
checks. Pure ceiling/floor hits cannot become wall placements.

Native owner, insertion size, -20 placement velocity, wall-normal orientation,
arming distance, LASERLINE creation, timer randomness, explosion and damage
remain native. A commit that loses its surface uses the original ammo refund;
lost tracking is refused before ammo. Existing blocked/release handling prevents
a held trigger from firing on recovery. The press ignores a previous shot's
stale CON Z override, as before; the final shot honors an explicit current
shoot-Z override through the shared ray helper.

Optional capability bit16 names this family. The existing reliable request/ack
expands mask15 to31; the9byte capability message,14byte movement tail, native
actor snapshots and NETVERSION3 are unchanged. Current XR input requires the
selected family's acknowledged capability before supplying a valid hand pose.
Custom SFLAG_PROJECTILE replacements and other WorksLike/Shoots combinations
stay outside this adapter.

## Actual placement proof

The test-only SDL-dummy helper publishes poses through G_VRSetShotInput. A real
joining native client negotiates, serializes its own movement update and receives
real server snapshots. Ordinary private SDL Fire starts the native weapon.
Bubblewrap hides GPU devices; process maps and handles are audited. No OpenXR or
GL context, manufactured network packet, fake mine or damage command is used.

`smoke_tripmine_native.py` passes15 native placement/range checks plus4 reference
comparisons against immutable pre-adapter binary
`work/eduke32-cpu-input-before-tripmine` (SHA256
`b12544d653a85acf754745c9c635cf039b6fc53d74a4b19b0c9b5babcff7dc3d`).
The actual flat post-shot mine matches tile/owner/sector/status/XYZ/normal and
native state fields; successful ammo5 and rejected-range ammo6 agree. Clocks and
allocation generations are deliberately not equality assertions.

`smoke_tripmine_hand.py` passes108 checks across ten scenarios:

| Case | Native behavior observed |
|---|---|
| Tracked horizontal | Through-wall requested hand is constrained inside; real mine follows physical ray/height, consumes one ammo, takes wall normal and replicates to live client. Native F12 shows the placed world mine. |
| Pitched | Actual hit Z follows a30degree physical ray with Build Z scale; actor and ammo replicate. |
| Body too far | No actor/ammo despite valid hand input. |
| Vertical | Ceiling hit produces no wall mine or ammo consumption. |
| Steep, tall ceiling | Physically distant wall hit is rejected despite short body XY distance. |
| Forcefield/masked wall | Native surface policy rejects placement. |
| Occupied surface | Second real press cannot place another nearby mine or spend ammo. |
| Tracking loss before commit | No actor/ammo; held recovery remains blocked; release/new press places once. |
| Surface lost before commit | Real POSTWEAPONSHOOT returns-1, original ammo refund holds; held recovery blocked; release/new press places once. |

Evidence: `work/tripmine-native-current.json`,
`work/tripmine-hand-{tracked,pitched,far,vertical,steep,forcefield,masked,occupied,loss,commit-loss}.json`.
The first tracked test expected an exact wall X coordinate; native oblique
hitscan rounded1152 to1151 and the original placement offset produced1141.
That assertion was corrected to the native fixed-point interval; the retained
first lab shows successful placement/replication before this harness correction.

## Native lifecycle proof

`smoke_tripmine_lifecycle.py` drives actual sideways movement out of the native
768-unit arming radius, waits for the existing actor to reach state33 and create
LASERLINE sprites, then walks back through the real beam. The tracked mine at
(1141,4151,-8672) creates its beam at the shifted hand placement; native detonation
reduces the actual client's health100 to18 on both server and client in this run.
The timer case sets native TRIPBOMB_CONTROL=2 (the timer bit, not1), lifetime20,
variance0. Actual native countdown and explosion reduce health100 to3 on both
peers. Damage magnitudes are observations, not general equality expectations.

Tracked beam/timer pass11/10 checks respectively, including capability31,
actual tracked insertion trace, ten released native input ticks, replicated mine,
and unchanged client health at the observed pre-crossing/pre-detonation point.
These point observations are not a loss/reordering or whole-interval timing proof.
Flat current and immutable reference each pass7 beam/6 timer checks with real
movement, native damage and health convergence. No actor/counter is armed or
detonated by the fixture.

Tracked evidence is under `work/tripmine-lifecycle-tracked/`, cases
`tripmine-lifecycle-tracked-beam-0lx__p9l` and
`tripmine-lifecycle-tracked-timer-oheaabfh`. Flat current/reference evidence
is under `work/tripmine-lifecycle/` and the final regression directory recorded
in the durable `outputs/evidence/tripmine-native-validation.json` report.
Current-source Devastator tracked and native pipebomb regressions pass17/14
checks (`work/devastator-tripmine-regression.json`,
`work/pipebomb-tripmine-regression.json`). These are CPU gameplay results.

## Reproduce without GPU

Use the two-symbol CPU input build and helper commands in [DEVASTATOR.md](DEVASTATOR.md).

```sh
python3 tools/vr/smoke_tripmine_native.py \
  --binary work/eduke32-cpu-input --input-helper work/headless_vr_input.so \
  --grp /path/to/owned/DUKE3D.GRP --work-dir work/tripmine-native \
  --reference-result work/tripmine-native-reference/final.json
python3 tools/vr/smoke_tripmine_hand.py \
  --binary work/eduke32-cpu-input --input-helper work/headless_vr_input.so \
  --grp /path/to/owned/DUKE3D.GRP --work-dir work/tripmine-hand \
  --case tracked --capture
python3 tools/vr/smoke_tripmine_lifecycle.py \
  --binary work/eduke32-cpu-input --input-helper work/headless_vr_input.so \
  --grp /path/to/owned/DUKE3D.GRP --work-dir work/tripmine-lifecycle \
  --tracked --case all
```

Native, OpenXR and normal CPU builds pass (`work/build-{native,xr}-tripmine.log`,
`work/build-cpu-tripmine-normal.log`); compiling is not graphics acceptance.
Physical headset, model/grip scale, two independent VR peers, loss/WAN and
actor-slot reuse remain outside these bounded local tests. Full VR/SPS is still
incomplete.
