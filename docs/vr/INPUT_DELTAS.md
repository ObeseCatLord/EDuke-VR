# Native multiplayer angular input

AA's character cursor exposed a native multiplayer input-lifetime bug. A real
XR client produced eleven distinct nonzero angular increments, but its dedicated
server applied them 47 times. The server retained the latest `input_t` between
packets and treated its angular increments like held movement/buttons. AA adds
these increments to its cursor each actor tick, so server and client reached
different START-button coordinates.

## Smallest correction

The existing input FIFO remains the pending-input store. An authenticated client
update replaces held controls but accumulates yaw/pitch increments. The server
copies the pending input into the existing per-player tick input and then clears
only the pending angular fields. This also consumes motion during pause rather
than releasing a burst on unpause.

The client clears its outgoing angular fields after copying them into the native
packet. Catch-up ticks can send again before another rendered frame supplies
fresh input; clearing at that boundary prevents repeating the last increment.
The current simulation tick's `g_player[].input` remains available to native and
CON consumers. Native absolute player state and tracked shot poses keep their
existing update paths.

Addition widens to `int64_t` and saturates to signed 32-bit bounds. `fix16_sadd`
cannot be used for arbitrary packet fields because its overflow sentinel is also
the valid value `INT32_MIN`. Native map entry already clears every FIFO slot;
player admission/removal now clear angular fields in the existing slots and
consumed input so a reused player index cannot inherit motion.

This changes no packet layout, version, queue, scheduler, tick rate, or gameplay
simulation. Consume-only was rejected because several packets may arrive before
one tick. Cumulative angular totals would add epochs/reset policy and different
wire semantics. A complete ordered input queue would duplicate simulation policy.
Neither is justified by the observed replay failure.

## Focused senior-review disposition

The reviewer was explicitly selected and independently verified for this turn
as `gpt-6-astra` / `xhigh`: thread
`01a14dd1-a96d-7c21-aec9-1243bbff8b08`, turn
`01a14dd1-a9ae-7721-8b3d-8efc65a8e3d4`. This was a focused native-input design
review, separate from the completed broad VR code review.

| Recommendation | Disposition |
| --- | --- |
| Consume and accumulate in the existing FIFO | Adopted; no parallel input store. |
| Cover sender catch-up freshness too | Adopted; clear only after the outgoing packet captures the delta. |
| Use widened saturation, not fixed-point overflow sentinels | Adopted; focused actual-header sanitizer checks cover signed boundaries. |
| Reset reused slots and preserve native map reset | Adopted; admission/removal clear angular fields, existing `G_ClearFIFO` remains authoritative at map entry. |
| Do not promise arbitrary batched CON equivalence | Adopted; actual AA test uses an interior cursor path and a stationary comparison with one-pixel rounding tolerance. |
| Test both peer directions, batching, catch-up and lifecycle | Runtime qualification is recorded with the checkpoint; helper tests alone do not qualify gameplay. |

## Runtime qualification, 2026-10-18

All four native/XR/CPU/CPU-input builds pass. The actual-header helper test passes
ASan/UBSan, including exact `INT32_MIN`, saturation in both directions, successive
packets, zero-angular packets, mixed signs, held fields and consume-once behavior.
The packed 20-byte `input_t` layout is unchanged.

Actual AA XR-client → CPU-server input, with the explicit lab-only per-player
button-history override, now produces 15 nonzero samples on each peer with
identical yaw/pitch sums: `26939893 / 4567864`. Both cursors stop at `(288,30)`;
both confirm Duke and START (`charsel=1`, `startmode=1`, `pchar=0`). Before the
native correction, the same experiment reached START on the client while the
server cursor drifted outside its hitbox. No AA input or gamevar packet was added.

The native World Tour regression passes all 25 checks, including actual
movement/fire/ammo, maps, reconnect and recovery. A separate observational
keyboard fixture suspends only its owned processes briefly to expose packet
batching and client catch-up. Whole angular pulses are measured between stationary
boundaries, rather than counting repeated values or accepting a large peak.

| Native transport case | Client yaw sum | Server yaw sum |
| --- | ---: | ---: |
| Corrected CPU server, packet batch | 35716972 | 35716972 |
| Corrected CPU server, client catch-up | 37071503 | 37071503 |
| Previous binary, packet batch | 35717301 | 45546688 |
| Previous binary, client catch-up | 42127376 | 39178994 |
| Corrected XR listen server, packet batch | 35716859 | 35716859 |
| Corrected XR listen server, client catch-up | 38686164 | 38686164 |

Pitch is zero in these keyboard cases; actual AA exercises both axes. Held
forward motion persists after angular release. The XR host's separate player-0
path also observes actual controller movement/fire; its submitted frame120 is
fresh after the client-input test, nonconstant and different between eyes.
Core validation is active and reports no warnings/errors. The private software
lab excludes GPU devices and uses Xvfb/Monado/llvmpipe/LVP; no desktop or hardware
GPU interaction occurs. Owned processes clean up.

The first test-worker burst-peak predicate passed the old binary too and is not
regression evidence. An intermediate pulse reducer stopped at an internal zero
gap; the final reducer requires stationary samples before and after the entire
pulse. These attempts are retained. Final records:

- `work/input-delta-cpu-final/native-input-delta-k2bjgkrd/result.json`
- `work/software-xr-input-listen/native-input-delta-1z63gbuk/result.json`
- `work/input-delta-native-levels/native-levels-dg2gzfnz/result.json`
- `work/software-xr-aa-input-deltas/aa-mp-gameplay-q_rlluv9/result.json`

The full AA runner still fails at weapon initialization, not at selection.
Both players have Knee selected and pistol ammo0. Additional observations in
`work/software-xr-aa-input-policy/aa-mp-gameplay-9xz9ar_o/result.json` rule out
the initial hypothesis of a deliberately weaponless Marathon map: `marathon=0`,
`gametype=0`, `startguns=-1`, `startguns_perma=0`. AA does not remove the native
pistol under that policy. Native fresh join copies player0 and calls only
`P_ResetPlayer`, omitting the inventory/weapon initialization in the established
`P_ResetMultiPlayer` path. Server player0 is already empty, so its initial reset
ordering still needs tracing before fixing the join boundary. Do not seed ammo,
replay a full reset after selection, or treat this diagnostic failure as an AA
gameplay pass.

Dedicated angular pause/unpause, menu return and delayed packets crossing map
entry are not separately qualified here. Existing lifecycle tests and source
reset checks do not establish packet-epoch behavior. Full gamevar authority and
campaign combat remain open.

## Independent AA issues and limits

AA declares `oldbits` globally while its current `bits` and cursor are per-player.
Its player actors overwrite the shared history, so one held Open input can toggle
the character repeatedly. A causal lab wrapper predeclares `oldbits` per-player
**before** including the installed AA script. Native first-definition-wins
behavior makes the installed later declaration produce an expected duplicate
warning. Declaring the override after the include is ineffective. The installed
mod is untouched. This remains an explicit compatibility experiment, not a
silent engine heuristic or compiler change.

A separate server-only authority probe proved that native startup/world
snapshots do not replicate ordinary CON globals or per-player variables. A late
client retained its defaults when the server had already changed AA's `charsel`
and fixture variables, and after later server-only changes. The `NOMULTI`
control also retained its default; that alone does not prove the flag is honored.
`tools/vr/probe_aa_gamevar_authority.py` reports this as a completed diagnosis,
never a successful gameplay test.

Unreliable movement packets can still lose angular increments. Summing opposite
increments before a CON clamp/divide need not equal ordered per-tick execution.
Server-to-client input currently carries player 0 only and retains its existing
semantics. Full AA selection authority, script replication, late-join campaign
state and multiplayer combat remain separate acceptance work. No arbitrary CON
replication, selector clone, or weapon-state replacement is added by this fix.
