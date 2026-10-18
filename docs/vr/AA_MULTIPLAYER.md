# AA native multiplayer startup

For the later native angular-input correction and matching Duke/START selection,
read [INPUT_DELTAS.md](INPUT_DELTAS.md). The subsequent starting-inventory fix and
actual tracked multiplayer pistol firing are in
[STARTING_INVENTORY.md](STARTING_INVENTORY.md). This startup section retains the
earlier checkpoint's scope. CON-state replication, reverse-direction AA hosting
and campaign combat remain open.

This checkpoint qualifies Alien Armageddon 5.66 **native startup and joining**.
AA campaign combat, character selection across peers, and script-state
replication remain incomplete. The native packet format stays at NETVERSION6.

## Demonstrated failures and narrow changes

An early real AA client connected before the dedicated server collected spawn
points. The server printed `No player spawn point available` and withheld its
application acknowledgement permanently. A later client reached map loading
while its own AA sounds were still caching. Its CPU-only backtrace was:

```
null callback -> CONTROL_GetInput -> G_ClearFIFO -> G_EnterLevel
              -> Net_StartNewGame -> Net_GetPackets -> cacheAllSounds -> app_main
```

`gameHandleEvents` must continue running during lengthy startup. The fix leaves
ENet transport processing in place and delays application-level game entry:

- One process-initialization latch opens after native `EVENT_INITCOMPLETE`.
  Clients retain incoming application events in ENet's existing queue until then.
- Servers continue consuming transport connect/disconnect events. Native
  ACK/AUTH admission waits for process initialization and the populated initial
  map snapshot, reusing `g_mapStartState` and its existing actor-count field.
  Publishing an empty initial snapshot as a populated one acknowledges connected,
  unassigned peers; normal later connections use the same admission helper.
- Unassigned disconnects leave player counts/player 0 alone. Startup receives
  cannot allocate players before admission. Assigned peers cannot authenticate
  again. A loaded map without room for a player explicitly disconnects the peer.
- The initial-snapshot wait ends on client loss or quit. It does not turn a
  timeout into successful initialization.
- `app_main` resolves the current local player at each use. Its former reference
  lived across `PACKET_PLAYER_INDEX` and reconnects and therefore stayed bound to
  player 0. Other functions' short-lived references are unchanged.
- A client which already entered its server's map skips the local logo/demo
  startup branch. An intermediate real test reached synchronization, then a
  debugger found it in `G_PlaybackDemo` with `ready2send=0`; this additional native
  flow correction was required to reach gameplay input.

This preserves native loading, player allocation, transport, reliable messages,
map snapshots, and ordinary level-change behavior. It adds no packet queue,
replay, handshake registry, transport, or replacement script simulation.
Guarding only `CONTROL_GetInput` would leave all other initialization ordering
wrong. Delaying all server ENet events was rejected because it leaves transport
peers connection-pending, unable to service normal keepalives.

A second demonstrated boundary is generic `EVENT_PREGAME`/`EVENT_GAME` fanout.
It previously visited `STAT_NETALLOC` reserve slots. AA treated each blank tile-0
slot as an actor, logged it, and called `killit`; network deletion returned that
slot to the same reserve. Roughly 7,800 calls repeated each world tick. Fanout
now excludes that status when native networking is active. Actual live CON
actors continue executing. Allocation, deletion, sprite lists and snapshots
retain their existing implementations.

## Focused Astra disposition

The design review was independently verified as `gpt-6-astra`/`xhigh`, thread
`01a14dad-6d69-7b41-9931-1de3fb28c5f7`, turn
`01a14dad-6dac-73a2-b32a-57da66d4363e`. It was a startup-boundary review, separate
from the previously completed broad VR implementation review.

| Recommendation | Disposition |
| --- | --- |
| Preserve server CONNECT dispatch for ENet liveness | Adopted; defer native ACK, using existing unassigned peer identity. |
| Remove persistent player-0 alias | Adopted only in `app_main`; dynamic native index used at every access. |
| Ignore unassigned disconnect for membership | Adopted; includes native disconnect-timeout event. |
| End initial-snapshot wait on loss/quit | Adopted; normal disconnect/menu/exit path retained. |
| Reuse initial snapshot, avoid new readiness state machine | Adapted to populated `maxActorIndex`, so publication follows snapshot copying; one process latch only. |
| Exercise long loading, cancellation, actual controls and reconnect | Runtime results recorded below and in sibling evidence. |

## Runtime evidence

`tools/vr/smoke_aa_multiplayer_native.py` includes the installed, unmodified
`scripts/AAGAME.CON` and appends read-only observations. Early and late joins
both pass eight checks: schedule, native synchronization, player 1 input on
both simulations, actual Hollywood per-map ART, native nonconstant 640×480 F12
capture, continuing live events, zero reserve-slot events, and GPU exclusion.
The captured client shows AA's actual character-selection screen. This is not
selected-character combat proof.

All games run under bubblewrap with a private network/PID namespace, no GPU
devices, SDL dummy/software rendering, private config/output directories and
owner-only input FIFOs. Screenshots come from native F12, not desktop capture.
No installed AA files, user desktop, Blender or Envision runtime are modified.

Preserved work records:

- `software-cpu-aa-mp-baseline`: early connection rejected before spawn collection.
- `software-cpu-aa-mp-latejoin` and `software-cpu-aa-mp-backtrace`: late-load crash and native stack.
- `aa-join-early.json` and `software-cpu-aa-mp-after-sync-gdb`: intermediate post-sync demo-flow failure.
- `aa-join-early-flow.json`: gameplay reached; runner initially looked for F12 in the wrong directory. Native screenshot was present under `screenshots/`; corrected runner observes its native completion log.
- `aa-join-early-final.json`, `aa-join-late-final.json`: final AA startup proof.

The stock native multiplayer regression passes 25 checks, including authoritative
movement/fire/ammo convergence, map changes, reserved-slot maps, malformed-map
recovery, client replacement/reconnect and real F12 images. A private software-XR
multiplayer custom-crosshair regression passes all 16 checks: actual tracked
shot origin/impact matches the world reticle, both-eye raster error is at most
one channel value, and world depth is unchanged. This controlled weapon fixture
is not actual AA campaign multiplayer.

The first XR rerun exposed an omitted term in the independent projection oracle.
Composing body pitch with tracked head yaw produces eye roll; the check used only
yaw/pitch. A bounded diagnostic reports existing native eye roll, and the oracle
now uses it. It still derives projection independently of the uploaded matrix,
with the original 2e-5 tolerance. Final maximum error is below 2.7e-7 NDC; the
renderer was unchanged. The original failure is preserved in
`software-xr-aa-startup-crosshair`, followed by the passing
`software-xr-aa-startup-crosshair-roll`.

Exact binary hashes and lifecycle results are in sibling
`evidence/aa-multiplayer-startup-validation.json` and the handoff.

The four CPU startup lifecycle cases also pass. A real native client stays
connected through a 35.98-second first-map `Screen_Play` delay and joins as
player1. A transport-only peer disconnects before admission; player0 remains
and the next real client still receives index1. Losing the server during the
initial-snapshot wait reaches native menu drawing after the disconnect. An
owned SDL_QUIT during that wait exits with code0. These cases use normal ENet
service and event pumping, not synthetic gameplay packets or engine sleeps.
The post-disconnect menu handles SDL_QUIT as Escape; an earlier assertion that
it must exit was rejected as a test-policy error. Actual menu drawing establishes
wait recovery, and the runner then stops only its owned process.

## Reproduction

From the repository root, using the existing CPU-only executable and private
SDL input helper:

```sh
python3 tools/vr/smoke_aa_multiplayer_native.py \
  --binary work/eduke32-cpu-input --input-helper work/headless_vr_input.so \
  --mod /path/to/owned/alien_armageddon_566 \
  --work-dir "$PWD/work/software-cpu-aa-join" --join early
# Repeat with --join late.

python3 tools/vr/smoke_startup_lifecycle.py \
  --binary work/eduke32-cpu-input --input-helper work/headless_vr_input.so \
  --grp /path/to/owned/DUKE3D.GRP \
  --work-dir "$PWD/work/software-cpu-startup-lifecycle"
```

These runners enter their own GPU-denied private namespace. The lifecycle runner
compiles its two small test helpers into its writable output directory; it does
not rebuild or modify the engine. Retain the generated result JSON and logs.

## Remaining AA multiplayer decision

Current native networking synchronizes fixed player state and world
walls/sectors/actors. It has no gamevar payload or `Gv_*` replication calls.
`GAMEVAR_NOMULTI` is declared but has no packet consumer. Native savegame gamevar
serialization is separate and is not transmitted by ENet.

AA's `startmode` and `charsel` are global NORESET variables; `pchar` is per-player.
Weapon script values are also not transferred. AA's character selection chooses
local player/AI companions; its CTF/DM/Survive labels do not establish a working
network game mode. At the startup-only checkpoint, both remained at `startmode=-1`,
`charsel=0`, pistol ammo0. Agreement of defaults is not replication evidence.

The later diagnostic in [INPUT_DELTAS.md](INPUT_DELTAS.md) now proves that a
server-only AA state change is absent across both join and later snapshots;
native input and selector side effects are traced separately. Before adding
replication, compare a narrow AA script adapter with extending the existing
native snapshot codec. Identify which values are authoritative gameplay versus
local menu/HUD state. Do not globally replicate every CON variable or invent a
second AA weapon/menu state machine. A completed acceptance test must include
actual selected characters, authoritative movement/fire/damage, late join,
map transitions and reconnect, followed by the existing private software-XR
controller/crosshair proof. None of these unfinished AA campaign behaviors is
claimed by the startup tests.
