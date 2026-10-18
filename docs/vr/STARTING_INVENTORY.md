# Native co-op starting inventory

The subsequent [host-input correction](HOST_INPUT_DELTAS.md) resolves the
XR-host selector failure retained below and qualifies actual AA tracked pistol
firing in both VR roles. This document preserves the earlier checkpoint.

Command-line co-op hosts now run the existing native player reset before their
first level. Stock players start with a pistol and 48 rounds; CON reset hooks
can change that loadout. A real AA XR client can select Duke, confirm START,
and fire its pistol against the native dedicated server. Full AA multiplayer
remains incomplete, including the opposite XR-host selector direction.

## Cause and implementation

The actual `-server`/`-dedicated -c2 -v1 -l2` route sets `ud.warp_on=1` and calls
`G_NewGame_EnterLevel` directly. In cooperative mode, `G_NewGame` skips its
single-player pistol grant and `P_PrepForNewLevel` preserves inventory. The host
had never initialized that inventory. Later native admission copied player 0's
empty state into the joining player.

An observational wrapper around the installed AA scripts recorded server events
`NEWGAME → RESETPLAYER → ENTERLEVEL`, with weapon/ownership/ammo already zero at
NEWGAME. The native client ran both reset hooks before its own new game and had
48 rounds, then received the host's empty inventory. AA's observed policy was
`startguns=-1`, `startguns_perma=0`, `marathon=0`, `gametype=0`; this was not an
intentional weaponless AA start.

The behavioral reference is `Net_StartNewGame`: it calls `Net_ResetPlayers`
before native game/level entry. This change exposes that existing helper and
calls it only for a network host in the command-line warp branch. Its weapon
reset, inventory reset, CON events and player revision handling remain intact.
Networking-disabled builds use the usual no-op declaration convention.

Changing fresh-join policy, moving resets into every `G_NewGame` or rewriting
co-op inventory preservation would affect already-working paths. No such
incompatibility was demonstrated. The implementation adds no state, protocol,
weapon policy or initialization registry. Native board-file startup already has
its own reset loop; ordinary menu/console new games already use
`Net_StartNewGame`. Normal level exits keep their established preservation path.

## Focused Astra disposition

The current review turn's effective settings were independently verified:
`gpt-6-astra`, `xhigh`; thread `01a14de7-8ebb-7053-ad5e-9cc8d7972773`, turn
`01a14de7-8f11-7432-90ad-da67e86080bf`. This focused initialization review is
separate from the previously completed broad VR implementation review.

| Finding | Disposition |
| --- | --- |
| Proposed MODE_NEWGAME call misses actual command-line startup | Adopted: call in the demonstrated `warp_on==1` branch. |
| Reuse native reset helper and hook order | Adopted; no helper-body or fresh-join changes. |
| Avoid an extra initialization flag or broad reset refactor | Adopted; existing mode/warp transitions delimit startup. |
| Startup/screenshot success alone does not prove weapons | Added ownership, ammo, real firing and reset-order assertions. |
| Test scripted loadouts, level preservation, early join, reconnect and XR host | Results and the separate XR-host failure are recorded below. |
| Check networking enabled and disabled | Both build configurations pass. |

## Verified behavior

`smoke_starting_inventory.py` uses private CPU-only native server/client processes
and ordinary SDL keyboard input. The previous binary fails before joining:
server player 0 has no pistol, ammo or reset events. The corrected binary passes
both stock and scripted-loadout cases. Each records exactly
`RESETWEAPONS → RESETINVENTORY → NEWGAME → RESETPLAYER → ENTERLEVEL`.

- Stock: both peers own the pistol; real RCTRL firing changes ammo 48→46.
- Script hooks: 17 rounds and 37 armor survive startup/join; firing changes
  ammo 17→16 while armor and ownership remain equal.
- `smoke_coop_inventory_transition.py`: a real W press moves the joined player
  into a normal exit sector. Both processes enter the next built-in map in
  MODE_GAME with the same pistol, 16 rounds and 37 armor. Neither player's reset
  hooks run during that transition. Only the bonus UI is skipped by a fixture
  event; the native exit/loading path runs normally.
- Existing native multiplayer regression: all 25 checks pass, including normal
  console level changes, actual movement/fire, map recovery and reconnect.
- Actual AA early joining: all eight startup/input/render checks pass.
- Actual AA XR client / CPU dedicated server: all 14 current checks pass. Real
  controller selection agrees, both peers start with 48 rounds, two tracked
  native hits reach a wall, and both peers settle at 46 rounds. Submitted frame
  120 has distinct, nonconstant eyes; OpenXR core validation is active and clean.

AA selection still explicitly uses the lab-only per-player `oldbits`
predeclaration described in [INPUT_DELTAS.md](INPUT_DELTAS.md). Installed AA files
remain unchanged. These wall impacts and ammo checks do not establish enemy
damage, all weapons, script authority, campaign progression or full SPS.

The reverse AA direction exposes an additional failure: the XR listen host and
CPU client both correctly start with pistol ammo48, but their selector cursors
diverge before START. Host player0 consumes six nonzero samples totaling
yaw21315235/pitch4224301; the client observes 25 samples totaling
yaw92366700/pitch16898355. Their stationary cursors are `(268,35)` and `(320,0)`.
This is evidence for investigating the existing server-to-client input path,
not proof of a particular fix. That path was outside the earlier client-input
delta correction. The saved reverse-direction run is an overall failure.

All tests run under private CPU/software-XR namespaces without GPU devices.
The software lab uses one owned Xvfb/Monado with llvmpipe/LVP. All owned processes
exit. Native, XR, CPU, CPU-input and NETCODE=0 CPU builds pass; existing smmalloc
compiler warnings remain. No desktop, Blender or Envision changes occur.

## Evidence and reproduction

Exact hashes, bounded results, failed attempts and lab cleanup are stored in
sibling `evidence/starting-inventory-validation.json`. Principal results:

- `work/native-starting-inventory-final/native-starting-inventory-svi0_kf_/result.json`
- `work/native-coop-inventory-coop-starts/native-coop-inventory-1u1sgr2l/result.json`
- `work/inventory-native-levels/native-levels-n0h332f2/result.json`
- `work/aa-inventory-early/aa-native-join-utm88h5x/result.json`
- `work/software-xr-aa-inventory-final/aa-mp-gameplay-9obdmxh2/result.json`
- `work/software-xr-aa-inventory-host-input/aa-mp-gameplay-75szjd41/result.json` (failure)

Preserved harness failures include duplicate observer logs from chained CON
events, invalid CON return syntax, deathmatch-only generated spawn markers, and
a CPU AA entry screen requiring Return. The final fixtures use appended policy
hooks, `RETURN`, native co-op start lotag1, and owned FIFO input. No production
rule or acceptance tolerance was changed to accommodate these failures.

From the repository root:

```sh
python3 tools/vr/smoke_starting_inventory.py \
  --binary work/eduke32-cpu-input --input-helper work/headless_vr_input.so \
  --grp /path/to/owned/DUKE3D.GRP --work-dir work/inventory-test
python3 tools/vr/smoke_coop_inventory_transition.py \
  --binary work/eduke32-cpu-input --input-helper work/headless_vr_input.so \
  --grp /path/to/owned/DUKE3D.GRP --work-dir work/inventory-exit-test

python3 tools/vr/software_xr_lab.py --deps "$PWD/work/software-xr/deps" \
  --work-dir "$PWD/work/aa-inventory-xr" --child-timeout 150 -- \
  /usr/bin/python3 "$PWD/tools/vr/smoke_aa_multiplayer_gameplay.py" \
  --binary "$PWD/work/eduke32-cpu-input" --client-binary "$PWD/eduke32-xr" \
  --mod-root /path/to/owned/alien_armageddon_566 \
  --work-dir "$PWD/work/aa-inventory-xr" --display :105 --remote-port 49777 \
  --per-player-selector-edge
# Add --xr-host --input-helper "$PWD/work/headless_vr_input.so" to reproduce
# the separate reverse-direction selector failure, using a fresh work directory.
```
