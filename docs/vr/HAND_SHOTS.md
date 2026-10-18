# Experimental native hand-shot authority

Updated 2026-10-17. Opt-in `EDUKE32_XR_HAND_SHOTS=1`, with right/left tracked aim.
Ordinary hardcoded pistol, shotgun, chaingun, grow, RPG, freezer, shrinker and pipebomb use this origin and
full vector when the selected WorksLike family, configured Shoots tile and actual
shot tile agree. Custom-projectile replacements are excluded by the same shared
firing/card/crosshair predicate. Other weapons retain their native firing paths.
This is an incremental native adapter, not full weapon or multiplayer completion.

## Authority and wire boundary

The runtime publishes the selected LOCAL aim pose through the existing
tracking calibration and recovered body transform. It quantizes body-relative
position in native Build X/Y/Z units and world direction in physical X/Y/Z-down
axes. The native player position/angle remain authoritative; no absolute second
body or temporary player-struct replacement is maintained.

The movement layouts `input_t=20`, `playerupdate_t=56`, and `clientupdate_t=81`
retain their sizes, enforced by compile-time assertions. Native `NETVERSION=2`
adds three existing weapon-state bytes to each server player record: `hbomb_on`,
`hbomb_hold_delay`, and `rapid_fire_hold`, beside `kickback_pic`. All peers must
use this version; older-peer compatibility is not required. This repairs an
observed native skipped-commit snapshot failure, rather than creating a second
weapon protocol. Upgraded clients begin with the original reliable nine-byte optional capability on
existing CHAN_MISC after authentication/player-index assignment:

| Byte | Value |
|---|---|
| 0 | Packet ID 200, appended explicitly without renumbering native IDs |
| 1–4 | ASCII EDVR |
| 5 | Version 1 |
| 6 | Feature mask: RPG/tail 1, hitscan 2, freezer/shrinker 4, pipebomb 8; root bit 1 required |
| 7 | Kind 0 request,1 acknowledgement |
| 8 | Native assigned player ID |

Only the authenticated peer's live slot may negotiate; the client accepts an
acknowledgement only from its native server peer. Within the current native
protocol, flat peers retain the base movement update. An upgraded client
waits for the acknowledgement before extending packets. Hand mode suppresses
fire against an unsupported server; it never silently substitutes a body shot.
Ordinary flat clients continue sending native packets even when upgraded.

The existing progressive capability exchange is retained: mask1 then3 then7
then15 on the same reliable channel. Capabilities never downgrade during a
connection. Bit4 promises only freezer/shrinker; bit8 promises only native
handbombs. All current peers use NETVERSION2; the earlier capability scheme
is not a promise of connectivity to pre-version2 binaries. Server firing gates
each family by the authenticated peer's mask. Client input/card availability
uses the selected weapon's required feature; a valid pose alone grants no
additional weapon capability.

Once negotiated, an enabled hand-mode client appends exactly 14 bytes to its
existing PACKET_SLAVE_TO_MASTER on CHAN_MOVE, producing95 bytes. Fire and pose
are in the same ENet update, not separate streams:

| Tail bytes | Value |
|---|---|
| 0 | Version 1 |
| 1 | Flags: Enabled 1, Valid 2; all other bits invalid |
| 2–7 | Three little-endian signed16 native position offsets |
| 8–13 | Three little-endian signed16 physical world direction components, unit32767 |

Valid implies Enabled. Unavailable/disabled samples have zero fields. Reach is
a physical sphere of two metres: horizontal 384 units/metre, Z 6144 units/metre.
Validation uses 64-bit arithmetic and direction norm 32700..32800. Wrong peer,
channel, size, unnegotiated tail, version, flags, reach, norm or embedded player
identity rejects the entire update before any native prefix is applied. A base
update explicitly clears hand mode. No new actor replication format is needed.
This does not add sequencing or anti-cheat guarantees beyond native networking;
loss/reordering and broader malicious-peer behavior remain unqualified.

## Input, collision and projectile behavior

The common native module stores the latest sample per player with existing
`totalclock`. Samples older than 30 native 120Hz ticks expire. Mode entry,
unavailability or expiry blocks fire until an observed release; delayed native
RPG creation also checks readiness. Native CON EVENT_PROCESSINPUT still runs
at its original boundary after the input filter. Explicit CON behavior can
still alter native input; this is not a script sandbox.

At qualified native shot boundaries, both client preview and authoritative server trace
from body eye (`pos + pyoff`) to the requested hand using native hitscan with
owner blocking temporarily disabled and immediately restored. The result backs
away from a first obstruction, resolves the actual sector using updatesectorz,
applies native pushmove radius 16/Z clearance 256, and requires final cansee.
No player position is moved. Dead players, auxiliary/shoulder cameras, recording
and invalid sectors cannot resolve. Spawn/reset/map entry/disconnect clear
samples. Broader demo/save/camera transitions still need runtime qualification.

The ordinary RPG's native two-dimensional side muzzle displacement is omitted
only for hand mode. Free aim normalizes physical 3D velocity to 644:
`xvel = round(644 * horizontal / norm)` and
`zvel = round(644 * 16 * directionZ / norm)`, including vertical directions.
This intentionally differs from native constant-horizontal-speed firing.
Native autoaim selection and events remain, and its chosen velocity is likewise
normalized; explicit CON z-velocity override retains precedence and native
horizontal speed. Native ownership, ammo, damage, impact and actor replication
remain in their original paths. The same native velocity boundary handles freezer at644 and shrinker at768.
Freezer retains its post-spawn zvel-=32, half-size and native bounce budget;
shrinker retains SHRINKSPARK insertion and native shrink damage/effect logic.
Only tracked multiplayer shrinker prediction is suppressed; the native server
spawns and replicates the real actor. Classic body/actor/custom paths retain
their prior firing policy. Custom projectile and remaining weapon families
are not redirected by this adapter.

A demonstrated pure vertical impact bug shifted RPG X/Y along an arbitrary
retained yaw even with xvel0. Native ceiling/floor backoff now requires nonzero
xvel, as does the RPG explosion's additional horizontal shift. This removes
sideways jumps for pure vertical shots without per-projectile VR state.
It does not generalize all native pitched impact offsets to a new 3D policy.

The ART card uses the client's collision-constrained origin with its provisional
pivot and raw aim orientation; actual GPU fixtures compare it with independently
projected server origins in a static map. Dynamic-world latency reconciliation
is still open. The origin is the aim pose, not a calibrated barrel tip. The card
keeps its existing foreground depth behavior and can intersect the world.
With gameplay HUD mode the crosshair now traces from that constrained origin
along the physical aim ray and projects its native ART into world space using
the actual native eye matrices/depth. It represents central free aim before
native autoaim/spread/CON shot overrides or projectile arcs/bounces.
Full-pitch projectile flight does not establish full-pitch world rendering.

## Reproducible proof

`tools/vr/smoke_hand_shots.py` uses a generated two-sector map, the caller's owned
GRP and read-only native CON observations. A native dedicated server creates
real RPGs; the XR client uses actual Monado remote actions. Cases: open, wall,
glancing, steep, vertical, left, moved, invalid-reach, timeout, damage, autoaim,
legacy-server, legacy-client and unnegotiated. Supply the pre-extension native
binary for the applicable legacy role; the helper cannot infer compatibility
from version text. `--bad-packet version|flags|direction|reach|size|channel|identity`
injects one actual malformed ENet update with a sentinel position, requires
server rejection/no sentinel movement, then proves ordinary valid RPG behavior.
The test-only environment flags are absent in ordinary play.

`smoke_actions_multiplayer.py --reconnect --inventory-sync` additionally joins
two actual XR peers, disconnects slot 1 through native input and verifies slot 2
inventory after a native server-side CON mutation in the sparse 0,2 update.
Private-runtime primary selection uses owned libmonado clients, never desktop
focus. Final results, retained failed hypotheses and limitations are recorded in
VALIDATION.md and the bounded sibling evidence JSON.


## Native full-vector hitscan

One optional local sector/ray context passes through P_PreFireHitscan and
Proj_DoHitscan for qualified hardcoded bullet/grow shots. It resolves the hand
once and omits the body-only ZOFFSET6 subtraction. The accurate probe and final
native hitscan use the same resolved sector/ray; owner cstat is restored exactly.
Custom, actor and knee calls retain the original no-context path.

Immediately after native GetAutoAimAng, only its actual target return permits
native corrected yaw/zvel to replace the physical hand base. A later accurate
free-aim actor hit controls spread suppression only. Native GETAUTOAIMANGLE,
GETSHOTRANGE and per-pellet weapon events remain ordered and native conditional
random draws remain unchanged.

The two native sampled offsets produce a bounded physical local cone:
`V = F*cos(a) + R*sin(a) + cross(F,R)*b`, where F is normalized physical forward,
R horizontal right, a the sampled angle in native angle units and b the sampled
z offset/4096. Retained native yaw defines R at the exact pole. Normalize V and
encode physical X/Y at16384 and physical Z at262144 in Build ray units. This
preserves the ideal horizontal azimuth/slope relation and stays finite at large
CON ranges and vertical pitch. Pitched-ray spread is an intentional physical
interpretation; exact native integer equivalence is not claimed.

Explicit CON zshoot overrides that cone with the native absolute slope and
sampled native yaw. The effective ray supplies final impact yaw and vertical
sign to existing native postfire code, so ceiling/floor damage policy agrees
with forced flight. Water tracers begin from the resolved origin sector. Native
shotspark/grow impact, damage, switch, decal and sound paths are reused.

Initial/rebase actor snapshots now encode every native actor field, including
zero, in the existing codec. Server/client bootstrap sprites differ; a delta
against different initial arrays otherwise retains ghost player actors and
alternates player binding. Subsequent native actor packets remain ordinary
deltas. No layout/version/identity stream is added; old native readers already
understand these field-change bits. Actual compatibility remains a runtime gate.

`smoke_hitscan.py` observes real native hitscan results, native CON impact
sprites/events/ammo, target health/grow state and actual two-eye card pixels.
`smoke_hitscan_native.py` compares an actual native dedicated/client pistol run
with a pre-change binary, with hand mode/OpenXR absent. The horizontal portal
fixture does not qualify overlapping-XY/YAX sector transitions. Full-pitch
world rendering, native full-pitch autoaim selection and broad CON/mod weapon
families remain open.

The native readiness wait also now detects any change in its byte-sized ping
counter, including wrap, rather than requiring a greater value. At the maximum
byte value the old condition could never finish. It sends one immediate request
then at most one per native simulation tick, retaining event/network pumping.
Test-only EDUKE32_XR_TEST_READY_WRAP=1 starts the owned client's wait at its
actual counter maximum; real native replies must still lead to gameplay, stereo
submission and a real hitscan. This is not a simulated readiness acknowledgement.
The older-peer smoke is bounded compatibility evidence; it cannot repair an old
peer executable's own readiness-counter bug.

Grow's native CON effect begins only after grow damage exhausts target health.
The growth test therefore uses repeated actual trigger presses, leaving native
health/action/scale untouched. Dead-state replication compares the native final
dead state rather than requiring the client to capture a short-lived negative
health value between snapshots.


`tools/vr/smoke_projectiles.py --weapon freeze|shrink` exercises native server
projectile replication, closed/glancing origins, steep/vertical velocity, freezer
bounce budgets and native target effects. `--case unsupported-server` requires
an actual pre-feature4 server; `--case older-client` requires an actual mask3
client. Those pinned binaries establish capability boundaries with real peers.
All test maps/scripts are generated wrappers around the caller's owned data;
no game assets or proprietary CON files are included.


## Native tracked pipebombs and snapshot coherence

Pipebombs use their existing direct insertion in `P_ProcessWeapon`, retaining
native charge/ammo, remote or timed fuse, owner, random draws, bounce, pickup,
damage and attribution. They do not acquire weapon callbacks absent from that
path. A pending tracked charge cancels immediately on lost readiness/rearm;
commit resolves collision before ammo changes. Cancellation preserves earlier
bombs' `hbomb_on`. Geometry failure sets the existing release latch.

Native pipebomb movement advances horizontal position by approximately xvel/2,
but vertical position by approximately 1.5*zvel through A_Fall and A_MoveSprite.
The physical directional Z conversion is therefore **16/3**, with native throw
bias -512 (or zero for rolling) retained separately. Coupled finite bounds
respect signed storage and native fall limits. Elevated crouch-roll retains
yvel3 and falls through the normal actor path without the body-only Z offset.

A real pre-fix client skipped commit frame 11, received ammo5 while keeping
hbomb_on0, exploded a live mode2 bomb early and propagated knockback back to
the server. The native server player snapshot now carries the coherent tuple
above. Independent actor/player channels still have no cross-channel ordering,
so clients cannot initiate the player-owned HEAVYHBOMB remote-command transition
from that player byte. They accept authoritative mode3 via existing actor
snapshots and execute native effects; damage/timer/bounce/pickup logic remains.

`smoke_pipebomb_native.py` compares real CPU-native multiplayer flight against
the preserved unmodified firing reference. `smoke_pipebomb.py` drives real XR
actions and native server simulation. Qualified cases include open/oblique,
steep/vertical, wall/glancing, elevated crouch-roll, timed fuse/kill attribution,
tracking loss/recovery, reach failure and high-charge bounds. Its ordering case
delays actual observer player snapshots while live bomb actors arrive, then
requires no early damage/knockback and actual later native explosions/scores.
The second-throw extension currently observes a different allocator slot and
**does not establish same-slot reuse**; host-only geometry rejection remains
unqualified. See VALIDATION.md for exact evidence and limits.

Terminal XR disable clears hand authority so native keyboard fire works. A live
session with temporary tracking loss stays fail-closed. Effective LOCAL reference
changes update existing tracking calibration at the predicted locate timestamp;
unknown transforms reuse recovery and the release gate, including one invalid
native pose sample to cancel an already charged throw. No extra body or protocol
state machine is introduced.

Native respawn now clears the tracked pose while retaining enabled-invalid
mode and its existing blocked latch for a previously tracked player. Clearing
mode entirely allowed an in-flight native Use+Fire input through the first
post-respawn filter; the strengthened PvP harness caught that input even though
weapon raising prevented a shot in the observed run. Join/disconnect/global
map reset still clear the whole sample. No new replicated latch is added.
