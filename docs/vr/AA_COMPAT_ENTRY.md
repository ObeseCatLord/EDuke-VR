# AA 5.66 native compatibility entry

The shipped `package/vr/aa566/eduke32_vr_aa566.con` makes the demonstrated AA
button-history correction available through the normal native launch path.
It contains two CON statements: declare `oldbits` as per-player, then include
the user's installed `scripts/AAGAME.CON`. Both multiplayer peers use it.
The installed mod remains unchanged and no proprietary content is copied.

## Native boundary and assumptions

AA5.66 declares `bits` per-player and `oldbits` global in `AADEFS.CON:3517–3518`.
All 20 `oldbits` references are in that declaration and `AAPLAYER.CON`; its
consumers track edges for selection, vendors, slime escape, bonus dismissal,
double jump, weapon transitions and lookup. Each consumer runs with a player
context. History is updated in the selector and player actor. Sharing that
history allows another player's tick to erase a held press's previous value.

Native `Gv_NewVar` ignores a later duplicate non-system declaration before
changing its flags. The expected duplicate warning is retained. Main CON
parsing precedes native `-mx` modules, so an appended predeclaration would be too
late. Tests now select the actual shipped main through `-x` and append
observation-only modules through `-mx`; the experimental flag is not used in
these qualification runs. Both test options are mutually exclusive.

This is the smallest adapter to the existing content/compiler architecture.
Hardcoded engine detection would affect arbitrary mods. Copying and patching
AA scripts would create a maintained fork. A launcher or compatibility service
would duplicate native search paths and script selection. None is needed.
The wrapper does not synchronize gamevars, replace AA menus/weapons, change
the protocol, or convert the separate untraced `oldextbits` variable.

Native saves include the main script filename. Launch with the stable basename
`-x eduke32_vr_aa566.con` and locate it through `-j <package-directory>`.
Evidence records the resolved file path and hash separately. Ordinary disk
gamevars load by label; internal snapshot ordering is not evidence of ordinary
save incompatibility. Neither header-name comparison nor flag mismatch handling
proves old-save migration safe. Existing unwrapped saves remain unqualified.

## Focused senior disposition

The exact current review turn was independently verified as `gpt-6-astra` /
`xhigh`: thread `01a14e09-ae2f-7b22-ae41-6215124d19fa`, turn
`01a14e09-ae6e-7b43-80d6-d103666468f8`. This was a narrow entry/content decision,
separate from the completed broad VR implementation review.

| Finding | Disposition |
| --- | --- |
| A successful quick click cannot prove held-button stability | Added real two-input CPU test, constant held words, alternating press/repress and unrelated other-player input; unwrapped baseline fails. |
| Use native two-statement wrapper; avoid compiler/protocol machinery | Adopted with explicit `-x` selection and unchanged installed content. |
| Absolute main paths make save identity installation-dependent | Adapted to basename plus native search path in both runners and launch documentation. |
| Test fresh-profile disk save/restart/load without observation modules | Passed in actual VR gameplay, including a tracked shot after loading; native New Game reset also passed. |
| Distinguish ordinary disk saves from internal snapshots | Adopted; no inferred old-save rejection or migration claim. |
| Record hashes of included declaration/consumer scripts | Evidence includes AADEFS.CON, AAPLAYER.CON and AAGAME.CON, wrapper and binaries. |
| Leave oldextbits and general AA state authority separate | Adopted; no broader compatibility claim. |

## Verification

`smoke_aa_button_edges.py` runs a native listen host and client with independent,
owner-only SDL keyboard FIFOs inside one private CPU/device/network/PID sandbox.
No selector values are assigned by the observer. Each phase observes at least
12 actual input ticks for each player on each process. Tests keep the selected
player's complete held input word constant, including while the other player
presses/releases Jump. Players select separately because AA shares `charsel`.
Each Open press must cause exactly one transition; holding and releasing cause
none; repress causes exactly one more. Both players repeat this sequence.

Unwrapped AA repeatedly toggles selection while Open remains held. The shipped
wrapper preserves exactly one transition on each press on both simulations.
The same current engine binary is used for both runs. This is an actual AA
script behavior comparison, not a copied edge-detection implementation.

Actual XR-host and XR-client tests load the shipped entry with native `-x` plus
an observation module with `-mx`, without the lab predeclaration flag. Both
qualify Duke/START, matching native pistol state/ammo, real tracked wall impacts
and fresh distinct/nonconstant stereo gameplay. Core validation is active and
clean in the private software renderer. These wall impacts do not establish
enemy damage or full multiplayer script authority.

The single-player opening/selection/combat and uninstrumented fresh-save
results are recorded in sibling `evidence/aa-compat-entry-validation.json`.
The save runner loads no `-mx` module and declares no observation gamevars.
It queries existing AA variables with native `addlogvar`, drives START with
real Monado controllers, fires a tracked pistol shot, saves through F2,
restarts the executable, loads through F3/confirmation, and fires again.
The saved `charsel=1`, `startmode=1`, `pchar=0` and cursor/history values restore
exactly. Inspected native HUD captures show ammo 47 before saving and 46 after
the restored shot. These are ordinary fresh-wrapper saves; old saves and
cross-build migration remain unqualified.

The initial reset test used console `changelevel`. That command routes through
the native warp cheat during gameplay, so it must not be described as proof of
the New Game boundary. The CPU selector case accepted it, while active AA XR
gameplay did not restart despite a confirmed command dispatch. The final test
instead invokes native `map maps/oldeps/E1L1.MAP`, which sets
`MODE_RESTART|MODE_NEWGAME` and reaches the existing `G_NewGame` boundary.
Both CPU and XR runs report a fresh native `E1L2: HOLLYWOOD HOLOCAUST` load,
restore all six observed variables to fresh values, and accept a new Open
selection. This qualifies native `map` New Game entry for the same AA Hollywood
file (AA labels the result as its episode map); it does not qualify
AA's full custom episode-picker/menu flow. Both final save runners pass all
eleven checks. Failed harness attempts remain separately identified in evidence.

All runtime tests use private CPU or one sequential Xvfb/Monado llvmpipe/LVP lab
with GPU devices absent. The user's desktop, installed game and existing saves
are untouched.

## Reproduction

See the [package launch instructions](../../package/vr/aa566/README.md).

```sh
python3 tools/vr/smoke_aa_button_edges.py \
  --binary work/eduke32-cpu-input --input-helper work/headless_vr_input.so \
  --mod /path/to/alien_armageddon_566 --work-dir work/aa-edges \
  --compat-con package/vr/aa566/eduke32_vr_aa566.con
# Omit --compat-con for the failing unwrapped control.
```

The software-XR gameplay runners accept `--compat-con` with this same file.
Use the existing private software lab and separate work directories as in
[HOST_INPUT_DELTAS.md](HOST_INPUT_DELTAS.md), replacing
`--per-player-selector-edge` with the explicit compatibility file.

The uninstrumented gameplay save round trip uses the same private lab:

```sh
python3 tools/vr/software_xr_lab.py --deps "$PWD/work/software-xr/deps" \
  --work-dir "$PWD/work/aa-save" --child-timeout 240 -- \
  /usr/bin/python3 "$PWD/tools/vr/smoke_aa_compat_save.py" \
  --binary "$PWD/eduke32-xr" --mod-root /path/to/alien_armageddon_566 \
  --work-dir "$PWD/work/aa-save" --xr --display :105 --remote-port 49777
```
