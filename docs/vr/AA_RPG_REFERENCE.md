# AA standard Duke RPG: native reference and calibrated asset

The actual AA 5.66 standard Duke RPG now has a passing native firing reference
and a privately authored, counter-addressable MD3 package. **Its held mesh is
not integrated yet.** Current runtime replacement still supports the previously
qualified pistol families. No new RPG firing, networking, renderer or model
selection policy was introduced here.

## Native behavior established

`tools/vr/smoke_aa_rpg_native.py` loads the installed AA compatibility entry,
uses AA's real controller START selection, grants three ordinary RPG rounds in
a private observer CON, selects RPG through the owned window's native `5` key,
and fires with a simulated Monado trigger edge. It never sets the selected
weapon, advances weapon counters, or inserts a projectile itself.

The final software lab `work/software-xr-aa-rpg-reference-v2` passes all
**19 checks**. Its child result is
`aa-rpg-native-okc608hl/result.json`; the durable summary is sibling
`../evidence/aa-rpg-native-reference.json`.

- Actual standard Duke, slot 4, no upgrades/nuke; FireDelay 4, TotalTime 20,
  WorksLike 4, Shoots 2605, Flags/Clip/Reload/HoldDelay/ShotsPerBurst all zero.
- One trigger edge produces one native POSTWEAPONSHOOT event and one
  player-owned RPG with nonzero speed; ammunition changes 3→2. Native counters
  naturally progress through 1..19 and return to 0. An RPG-owned EXPLOSION2
  impact was also observed; damage and multiplayer are not tested here.
- All four composite firing cards at counters 4, 5, 6, 7 contain actual native
  artwork. The main agent inspected counter 6's flame/gun image. Distinct,
  nonconstant stereo gameplay is captured at submitted frame 120.
- The drawable stays unmapped without desktop focus. GPU devices are denied;
  llvmpipe/LVP render in a private Monado/Xvfb lab. Observed OpenXR validation
  is clean, game remains live until owned cleanup, and all lab children exit 0.

The first attempt `work/software-xr-aa-rpg-reference-v1` failed because an 80 ms
key tap never appeared in slow native input. The final runner holds the owned
key until native selection observes it, then always releases it. That failed
record remains; its cleanup passed and no game/driver crash was observed.
The main agent also fixed the initial runner's truncated fire timeline before
runtime qualification and requires exactly one ammo decrement/owned projectile.

## Minimal diagnostic change

`EDUKE32_XR_TEST_MODEL_WEAPON=4` selects RPG for the existing per-counter native
weapon-card capture. Omission preserves the original pistol diagnostic;
malformed/out-of-range values disable that capture selector. It does not change
native state, frame selection, clocks, or production model eligibility. The
existing bounded counter range 1..26 and once-per-counter capture remain.

XR+NETCODE builds successfully (`work/aa-rpg-reference-build.log`; existing
smmalloc warnings). Tested SHA256:
`4f7516bd683e666e500c46411dfa0e21a098880e21e27b1e623ccaeb17367cb2`.
The earlier fully qualified voxel binary is preserved as
`work/eduke32-xr-before-aa-rpg-reference`. No non-XR source path changed.

## Private art package

Astra created `../duke-vr-assets/aa-rpg-native`, retaining the original chunky
204-triangle geometry, 128×128 texture, UVs, normals and original muzzle/grip/support
tags. It adds measured left/right palm tags and 17 static named samples:
`rest`, `fire_01..03`, `fire_08..20`. These names expose native state; they do
not introduce a second animation clock or new mechanics. All 56 file checksums
were independently verified. Export/master validation passes (MD3 max 0.18812 mm;
actual GLB reimport zero measured positional error).

The real AA dispatch is installed `scripts/weapons_hud.CON:12400..12457`;
`draw_rpg` near 1184 is commented out. It draws body 10228 except composite
flame tiles 10229/10230 at counters 4..7. Those counters require **full native ART
fallback**, not a model body plus a misaligned leftover weapon card. Counter 20
is source-covered but was not observed in the actual native cycle. Native
screen-space recoil is documented; the new asset samples remain static.

Hand-fit previews use current `aa-v3-hands-grip` with idealized aligned aim/grip
orientations. Palm anchors lie on the actual exported grip surfaces; the
inherited 102.54 mm-wide grip is not proof of finger wrap, trigger reach or
hardware fit. Original AA arsenal remains complete offline: 68 physical designs
covering 69 dispatch entries, plus two basic floating hands and no AA bodies.
`../duke-vr-assets/CURRENT_REVISION.md` now correctly indexes the current sets.

## Next decision — not approved

`work/aa-rpg-design-brief.md` proposes extending the existing before-MASK world
MD3 sample/receipt/mount to this one family, with stable identity separate from
appearance, canonical palette-zero tags and exact actual-draw validation.
The fresh explicit Astra/xhigh review spawn hit the session agent-thread limit;
**no design review occurred and the generalized adapter was not implemented**.
Do not treat the proposal as approval. Obtain a fresh explicitly selected Astra
review when available, verify its effective settings, then integrate and prove
native/SPS image-depth equivalence, supported mesh states, unchanged composite
fallback, missing-asset/pose behavior and pistol regressions. Preserve the prior
[AA renderer ordering decision](AA_MODEL_DESIGN.md) and
[shared mount authority](PISTOL_MOUNT.md). No 69-way duplicate AA dispatcher,
late opaque HUD emission, new network protocol or invented recoil is justified.
