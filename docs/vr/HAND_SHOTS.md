# Experimental native hand-shot authority

Updated 2026-10-16. Opt-in `EDUKE32_XR_HAND_SHOTS=1`, with right/left tracked aim.
Only the ordinary hardcoded RPG selected as WorksLike RPG uses this origin and
full vector. Other weapons/custom projectiles retain their native firing paths.
This is an incremental native adapter, not full weapon or multiplayer completion.

## Authority and wire boundary

The runtime publishes the selected LOCAL aim pose through the existing
tracking calibration and recovered body transform. It quantizes body-relative
position in native Build X/Y/Z units and world direction in physical X/Y/Z-down
axes. The native player position/angle remain authoritative; no absolute second
body or temporary player-struct replacement is maintained.

The native `NETVERSION=1`, `input_t=20`, `playerupdate_t=56`, and
`clientupdate_t=81` are unchanged. Compile-time ABI assertions enforce those
sizes. Upgraded clients send one reliable nine-byte optional capability on
existing CHAN_MISC after authentication/player-index assignment:

| Byte | Value |
|---|---|
| 0 | Packet ID 200, appended explicitly without renumbering native IDs |
| 1–4 | ASCII EDVR |
| 5 | Version 1 |
| 6 | Feature 1: hand-shot tail |
| 7 | Kind 0 request,1 acknowledgement |
| 8 | Native assigned player ID |

Only the authenticated peer's live slot may negotiate; the client accepts an
acknowledgement only from its native server peer. Legacy peers ignore the
unknown MISC packet and retain the base movement update. An upgraded client
waits for the acknowledgement before extending packets. Hand mode suppresses
fire against an unsupported server; it never silently substitutes a body shot.
Ordinary flat clients continue sending native packets even when upgraded.

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

At the RPG start boundary, both client preview and authoritative server trace
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
remain in their original paths. Custom projectile and other weapon families
are not redirected by this adapter.

The ART card uses the client's collision-constrained origin with its provisional
pivot and raw aim orientation; actual GPU fixtures compare it with independently
projected server origins in a static map. Dynamic-world latency reconciliation
is still open. The origin is the aim pose, not a calibrated barrel tip. The card
keeps its existing foreground depth behavior and can intersect the world.
Crosshair direction follows the full vector within its finite head panel; it
is not a world-depth impact marker or a promise about native autoaim/spread.
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
