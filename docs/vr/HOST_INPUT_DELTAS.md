# Native listen-host angular input

The subsequent [AA compatibility entry](AA_COMPAT_ENTRY.md) replaces the lab-only
button-history predeclaration in qualification launches. The original commands
and results below retain their historical diagnostic scope.

AA's character selection and tracked pistol firing now pass with the XR player
either hosting or joining. The listen host previously repeated its last angular
input during catch-up ticks, and ordinary clients repeated or discarded host
increments between native updates. Full AA multiplayer and full VR remain
incomplete; these tests still use the explicit lab-only per-player `oldbits`
predeclaration described in [INPUT_DELTAS.md](INPUT_DELTAS.md).

## Evidence and smallest correction

The failed AA XR-host run started both peers with a pistol and 48 rounds, but
their stationary selector cursors differed: host `(268,35)`, client `(320,0)`.
Six host increments totaling yaw21315235/pitch4224301 became 25 client samples
totaling yaw92366700/pitch16898355. The inventory fix was working; this was a
separate native server-to-client input-lifetime failure.

The existing client-to-server correction provides the behavioral reference:
held controls retain the latest value, angular fields are increments that are
accumulated until a simulation tick consumes them. Three existing boundaries
now apply that behavior to the host path:

1. `Net_SendServerUpdates` preserves native FIFO0-to-FIFO1 staging, then clears
   only FIFO0 angular fields, including when the host is alone. The packet uses
   the just-staged copy so clearing cannot discard its input.
2. `Net_ReceiveServerUpdate` accumulates angular increments into the existing
   host0 pending input, using the established saturating helper. Held fields
   keep their latest-value behavior.
3. `G_DoMoveThings` consumes pending remote angular fields on clients as well
   as servers, after copying the current tick's input. The established paused
   path also consumes these fields.

No packet layout, version, tick rate, renderer, queue, sequence counter or
script-state service was added. NETVERSION6 and native player state updates
remain unchanged. Server input records still carry host0 only; this change
does not introduce a new stream for the other players. The native map FIFO
reset remains the lifecycle boundary.

A replacement ordered input protocol would duplicate native scheduling and
require new epoch/loss policies. Neither this observed replay nor batching
requires that rewrite. The minimal end-to-end proof is actual AA selection
followed by native tracked firing, supplemented by an independent producer
check that cannot pass when both peers repeat the same input.

## Focused Astra disposition

Effective settings for the exact review turn were independently verified:
`gpt-6-astra`, `xhigh`; thread `01a14df9-4893-7e71-b0a7-600485a3e07a`, turn
`01a14df9-48d8-7493-ad65-20037388b362`. This focused design review is separate
from the previously completed broad VR implementation review.

| Finding | Disposition |
| --- | --- |
| Preserve staging before clearing and serialize the preserved copy | Adopted; no callback or mutation intervenes before packet capture. |
| Clear producer input even before any clients join | Adopted before the early return; tested alone and with two receivers. |
| Accumulate received increments and consume remote pending input once | Adopted in the existing FIFO; held movement/buttons remain intact. |
| Matching peer totals can hide sender replay on both peers | Added observation-only draw epochs and real catch-up scheduling; old binary fails and corrected binary passes. |
| Require batching, two receivers and both actual AA VR roles | All pass; results below. |
| Check pause/unpause and map entry separately | Focused lifecycle qualification is recorded with this checkpoint's evidence. |
| Avoid a new protocol or general CON replication layer | Adopted; no new state or wire format. |

## Runtime qualification

`smoke_host_input_deltas_native.py` uses a native CPU listen host and two ordinary
clients, with actual SDL keyboard input through an owned FIFO. Appended CON
observers only record native input and draw epochs. A brief SIGSTOP/SIGCONT of
the owned process creates real scheduling backlog. With Right held, a complete
draw epoch must contain at least three simulation ticks; only its first two may
contain angular input, accounting for native one-tick staging. All later ticks
must be zero. A completed epoch is required, so sliding a partial interval
cannot move the two-tick allowance.

Both baseline and corrected runs record ten ticks in the qualifying epoch,
alone and after joining. The old binary repeats the nonzero angle through the
last tick. The corrected binary records two nonzero ticks followed by eight
zeros in both cases. Matching totals alone would have missed this: the old
binary's host-stop pulse happens to match on both receivers.

Whole pulses require three stationary samples before and after the turn, while
W remains held. One receiver is stopped briefly to accumulate several native
updates; the other remains live. The test requires multiple distinct host sample
ticks during that stopped interval.

| Whole yaw pulse | Host | Receiver 1 | Receiver 2 |
| --- | ---: | ---: | ---: |
| Corrected ordinary scheduling | 1966096 | 1966096 | 1966096 |
| Corrected receiver batching | 37355341 | 37355341 | 37355341 |
| Corrected host catch-up | 39621052 | 39621052 | 39621052 |
| Baseline receiver batching | 37355734 | 40632385 | 37355734 |

Pitch is zero in these keyboard cases. AA exercises both axes. The historical
`slow`/`fast` result labels do not establish a frame-rate contrast: native
`r_maxfps 10` is clamped to 30, matching simulation rate. Catch-up proof comes
from the measured no-draw intervals, not that setting.

Actual installed AA5.66, Hollywood Holocaust, passes all 14 current checks in
each VR role. The XR host and CPU client select Duke/START at `(305,29)` and
agree on pistol ammo48→47 after one authoritative tracked wall hit. The XR
client and CPU dedicated server select at `(299,32)` and agree on ammo48→46
after two authoritative tracked wall hits. Fresh submitted stereo frames180
and120 respectively have distinct, nonconstant eyes. OpenXR core validation is
active and clean. Native weapon state and trigger observations are checked;
client script event counts are not asserted equivalent to server execution.

The stock native multiplayer regression passes all 25 checks, including real
movement/fire, level changes, reconnect and recovery. A separate strict CPU
lifecycle run holds Right through native Pause, releases it while paused, then
uses native Pause to resume. Every fresh unpaused host0 sample is angularly zero
on both peers across four distinct ticks. It then turns again on both peers,
releases Right immediately before the real F5 `changelevel 1 2` bind, and checks
every observed new-map host0 sample from ticks1–4 is zero. No pause/map state is
written by the fixture. Separate observation field names prevent display logs
from being misread as duplicate input records. The earlier weaker lifecycle
run is retained but is not the acceptance record.

Native, XR, CPU, CPU-input and NETCODE=0 CPU builds pass. Existing smmalloc
warnings remain. Tests use private CPU or software-XR device/network/PID
namespaces; the software lab uses one owned Xvfb and Monado with llvmpipe/LVP.
GPU devices are absent and owned processes clean up. No desktop, Blender,
Envision or runtime-default changes occur.

The first observer attempt did not induce a no-draw interval and failed closed.
Later producer checks passed on the corrected binary but the next pulse failed
because the log segment included the previous probe's asynchronously released
turn. The runner now waits for fresh quiet input before opening the next pulse.
The final old and corrected binaries use the same strict oracle. These failed
attempts remain available and are not counted as passing tests.

## Reproduction and limits

Exact hashes, bounded results and lifecycle/regression results are stored in
sibling `evidence/host-input-deltas-validation.json`. Principal records:

- `work/host-input-delta-baseline-complete/host-input-delta-a2mdrtt5/result.json`
- `work/host-input-delta-fixed-complete/host-input-delta-l7tl1b0y/result.json`
- `work/software-xr-aa-host-deltas/aa-mp-gameplay-2d477kc9/result.json`
- `work/software-xr-aa-client-host-deltas/aa-mp-gameplay-7zfsupv6/result.json`
- `work/host-input-lifecycle-strict/host-input-lifecycle-8xap9k9q/result.json`
- `work/host-deltas-native-levels/native-levels-s9oxk9i_/result.json`

```sh
python3 tools/vr/smoke_host_input_deltas_native.py \
  --binary work/eduke32-cpu-input --input-helper work/headless_vr_input.so \
  --grp /path/to/owned/DUKE3D.GRP --work-dir work/host-input-test --expect-fixed
# Omit --expect-fixed and supply a preserved old binary for a failing baseline.
python3 tools/vr/smoke_host_input_lifecycle.py \
  --binary work/eduke32-cpu-input --input-helper work/headless_vr_input.so \
  --grp /path/to/owned/DUKE3D.GRP --work-dir work/host-input-lifecycle-test

python3 tools/vr/software_xr_lab.py --deps "$PWD/work/software-xr/deps" \
  --work-dir "$PWD/work/aa-host-input-xr" --child-timeout 150 -- \
  /usr/bin/python3 "$PWD/tools/vr/smoke_aa_multiplayer_gameplay.py" \
  --binary "$PWD/work/eduke32-cpu-input" --client-binary "$PWD/eduke32-xr" \
  --mod-root /path/to/owned/alien_armageddon_566 \
  --work-dir "$PWD/work/aa-host-input-xr" --display :105 --remote-port 49777 \
  --per-player-selector-edge --xr-host \
  --input-helper "$PWD/work/headless_vr_input.so"
# Omit --xr-host and --input-helper for the XR-client direction; use a fresh lab.
```

Unreliable packets can still lose increments. Summing before arbitrary CON
division/clamping is not equivalent to ordered per-tick script execution.
Delayed packets crossing map epochs, general script authority, production AA
button-history compatibility, enemy damage, late joins, campaign progression,
all weapon/model bindings, full SPS and headset qualification remain open.
These actual wall impacts and selection checks do not establish those outcomes.
