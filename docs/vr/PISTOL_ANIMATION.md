# Native-counter tracked pistol animation

The stock tracked pistol uses native `kickback_pic` and `reloading` with named
MD3 frames. Counter zero resolves `rest` (legacy frame-zero fallback if absent),
1–4 resolve `fire_01..04`, and 5–26 resolve `reload_05..26`. A missing positive
frame returns to native ART before model emission. Native simulation, input,
ammo, events, firing and reload timing retain ownership; there is no asset clock
or replacement weapon state machine.

Positive frames require the qualified stock clip/reload/fire/total/hold/flag
parameters. Existing custom display, nonlocal/camera/action/palette exclusions
remain. AA's custom display handlers retain its native weapon presentation.
The new `md3_getframeindex` accessor only reads an already loaded MD3 and returns
`-1` for invalid or missing names; it does not mutate DEF mappings or animation.

## Presentation receipt boundary

The frozen presentation selects one explicit MD3 frame for both eyes. Successful
stereo emission issues the existing frame receipt. Each actual native pistol
body, magazine or hand draw must match runtime/generation/serial/player/target
ownership and the frozen native presentation before suppressing its ART pixels.
Body is required once; optional roles are accepted at most once. Wrong tiles,
duplicate roles or a presentation mismatch latch failure. Native shade/palette
and outer display side effects still execute.

Final presentation requires the completed role receipt and valid target/frame
ownership. It does not require continued equality with mutable player state:
`M_DisplayMenus` calls `Net_GetPackets` after weapon drawing even when no menu is
open. A native server correction or a field-only late CON callback cannot
retroactively change already rendered weapon pixels. Moving the native packet
poll, buffering updates, or adding receipt rebasing would change the reference
without necessity. Subsequent frames sample the then-current native state.
Nested rendering/swaps and target loss retain existing cancellation behavior.

Two focused Astra xhigh reviews informed this increment. The first recommended
native counter ownership, role-first validation and legacy/missing-frame rules.
A real multiplayer shot disproved its proposed final-state equality check. The
second review verified the native packet-poll order and explicitly withdrew
that recommendation: draw-time equality plus final ownership is the minimal
correct boundary. Main independently verified both reviewers' exact-turn model
and effort. No new network timeline or generic event policy was introduced.

| Review point | Disposition |
| --- | --- |
| Native counters and pure loaded-MD3 name lookup | Adopted; explicit frames reuse the native emitter. |
| Claimed roles checked before their tile allowlist | Adopted; invalid auxiliaries and duplicates latch rejection. |
| Fresh native presentation equality at final footer | Withdrawn after actual multiplayer evidence; retained at replaced draws, footer checks ownership. |
| Extra packet buffering, receipt rebasing, event policy or animation clock | Omitted; no demonstrated need and native ordering remains the reference. |
| Static muzzle/grip calibration | Bounded to the verified stock pistol; no animated-tag or AA-origin claim. |

## Native multiplayer reload correction

The existing server player snapshot carried `kickback_pic` but omitted
`reloading`. In the pre-change software-XR run the authoritative server completed
its 13→12 clip-boundary reload, while the client reached counter zero with
`reloading=1` still set. The existing snapshot now carries that single byte
alongside the counter and fills/extracts both together. **NETVERSION 5 requires
matching builds.** Existing capability and tracked-pose formats are unchanged;
older-peer compatibility is outside the requested scope.

The isolated classic CPU control also completes the reload on matching new
peers. Its old-protocol control converged in that different schedule, so it is
not presented as reproducing the stale flag. The original failing XR trace and
all current strict authoritative/client reload predicates are retained. The
optional reference mode of `smoke_pistol_reload_native.py` requires an actual
stale signature; current-only mode checks real native gameplay convergence.

## Verification and limits

`smoke_hand_model.py --animation --model-mode sps` fires a real Monado trigger
through native multiplayer with initial pistol ammo 13. It requires actual
server/client shot, positive-ammo clip-boundary reload, counter and reload flag
return to rest, native body/magazine/hand roles, and frame names matching observed
counters. Each naturally observed positive frame is captured once; captures do
not force counters or promise that every native tick is rendered.

The existing scratch-target native oracle compares the same frozen model input
against single-pass emission: exact both-eye color/raw depth, visible model
depth/parallax, and zero target writes during collection. Both vertex-array and
immediate paths are tested. Last-round switching, legacy missing frames,
nonstock timing, custom display fallback and receipt/target failure cases use
actual native presentation paths. Results and original failed attempts are
recorded with hashes in the sibling evidence directory.

The private v4 model supplies only the stock pistol. Its static frame-zero tags
remain valid while firing; reload motion is cosmetic and does not create an
animated gameplay muzzle. Hands/body IK, broader weapon families, independent
headsets/WAN and general world-model/material single-pass coverage remain open.
