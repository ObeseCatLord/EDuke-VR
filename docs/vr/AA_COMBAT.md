# AA native pistol and event-drawn crosshair

This increment qualifies the default Duke pistol in the installed Alien
Armageddon 5.66 scripts, plus the corresponding native multiplayer weapon
combination. It does not qualify AA's whole arsenal, campaign, custom multiplayer,
models, or complete single-pass world rendering.

## Demonstrated incompatibilities and minimal changes

AA's `dukeweapons` sets `WEAPON1_SHOOTS=SHOTGUN` while retaining pistol
`WorksLike`. The actual baseline observed `Shoots=2613`, `WorksLike=1`,
`FireDelay=2`, ammo 48→47 and one native `EVENT_POSTWEAPONSHOOT`, but no tracked
hitscan. `G_VRHandShotFeature` rejected this native combination.

Only the `SHOTGUN`/pistol pairing was added to the existing predicate. Exact
current `Shoots` matching and custom-projectile exclusion remain. The same
`A_ShootHardcoded`, `P_PreFireHitscan` and `Proj_DoHitscan` paths supply constrained
hand origin/full direction while native CON events, random spread, firing
counters, ammunition and damage retain ownership. No AA character-name checks,
weapon clock, projectile system or replacement simulation was added.

Matching **NETVERSION6** peers are required. Older version5 peers advertised
Hitscan but did not implement this eligibility combination. Bumping the existing
native version prevents differing authority/prediction semantics without adding
another feature-negotiation layer. Packet layouts, mask127 and pose-tail format
are unchanged from version5.

AA also draws its crosshair inside `EVENT_DISPLAYCROSSHAIR`, then returns -1 to
suppress the stock tile. XR previously began capture after that event and only
for a valid returned tile, leaving AA's pixels on the HUD plane. Capture now
surrounds the existing event and optional stock tile once. A transparent event
produces no visible marker. Native gates, ART, shade, palette, offsets and
callback ordering remain; the desktop mirror receives the native pixels once.

Custom-only crosshair segments use the logical full-screen `(160,100)` anchor
with CON's `(0,0,xdim,ydim)` bounds. Native `dorotspr_handle_bit2` supplies the
actual coordinate transform, including its pixel bias. Authored relative
multipart offsets remain intact. Returned stock tiles retain their original
returnvar/look-angle/viewport/FURY conventions. No anchor is inferred from the
first sprite or coverage bounding box. This is an explicit canonical convention
for independently drawn CON crosshair artwork; arbitrary other custom coordinate
spaces remain unqualified.

The existing shared UI shader/multiview transport projects onto the native
hitscan surface and depth-tests both eyes without writing world depth. The
marker denotes the **central unspread aim ray**. AA's native random spread means
individual bullets can land away from its center; no spread was removed from
the actual AA test.

## Focused senior review disposition

The senior-review workflow used a read-only default Astra agent, independently
verified as `gpt-6-astra/xhigh`, thread
`01a14d95-a1f0-7cd1-9ae3-17abc1442e2f`, turn
`01a14d95-a231-7fb3-9b5b-c4f032c8e110`. This was a focused boundary decision,
not another broad review of the port. The verified brief is private
`work/aa-combat-review-brief.md`.

| Recommendation | Disposition |
|---|---|
| Separate AA's full-screen anchor from stock look/viewport returnvars | Adopted. Explicit CON-only center/bounds; native returned-tile convention preserved. Reduced-viewport/nonzero-look proof added. |
| Fix custom fixture coordinate units and clip bounds | Adopted. `rotatesprite16`, actual `xdim/ydim`, independently checked source-part coverage and anchor. |
| Reuse current cancellation boundaries; avoid a new crosshair state machine | Adopted. Existing runtime generation/bound-target/view validity remains; real nested `startscreen` exercised from the event. No persistent crosshair receipt/replay layer. |
| Extend only the demonstrated pairing and bump existing version | Adopted. Native release/loss gating and matching-peer damage proof included. |
| Capture the same post-selection frame before/after | Adopted. Explicit diagnostic frame120 and serial, actual AA native state, source coverage, both eye images and raw depths. |

`EDUKE32_XR_CROSSHAIR_FRAME` selects a diagnostic world-frame readback (default60)
when `EDUKE32_XR_CROSSHAIR_OUTPUT` is enabled. It does not alter simulation,
render scheduling, native input or crosshair timing.

## Runtime proof

All runtime tests use the existing GPU-denied Bubblewrap lab, private unmapped
Xvfb, CPU llvmpipe GL and matching task-local LVP Vulkan, with one owned Monado
at a time. They do not use desktop focus/global input or alter installed AA.
Observed core validation and process cleanup are required.

`smoke_alien_armageddon.py --play-controller --combat` runs actual installed AA
CON/DEF/ART, selects Duke/START with real OpenXR actions, then moves the physical
hand off the head axis. Its observation wrapper reads native state and counts
native post-shot events; it does not substitute the weapon or force its counters.
The script verifies native fire/ammo/counter/release, hand-origin hitscan, custom
crosshair projection/coverage/parallax/depth, and loss→held recovery→release→fresh
press. A later stereo HUD/world capture shows continued actual AA gameplay.

`smoke_crosshair.py` exercises stock returned-tile behavior, multipart event ART,
actual world-depth occlusion, a reduced viewport plus nonzero look angle,
nested native screen entry, empty cancellation, lost pose and crosshair-off.
The custom cases use a native dedicated server plus XR client with the AA-style
pistol/SHOTGUN combination. Controlled zero spread permits exact authoritative
origin/impact versus reticle comparison. Independent physical eye projection and
source-anchor/relative-part checks supplement the raster oracle.

`smoke_hitscan.py --weapon pistol --pistol-shotgun --case damage` verifies native
CON impact/events and authoritative damage replication for that same combination.
The target health converges from 30 to19 on server and client, with one native
pre/range/autoaim event each. This controlled native fixture is not an actual AA
multiplayer campaign test.

Complete results, baseline failure, original attempts, source/binary hashes,
review provenance and image references are kept in sibling
`evidence/aa-combat-validation.json`. All proprietary images/data stay outside Git.

## Remaining full-port acceptance

Actual AA multiplayer join/combat/map changes and custom modes; remaining AA
weapons/upgrades/characters/scopes/cameras; binding the completed weapon/hand
models; broader material/model/voxel SPS; remote body/hand appearance; unrestricted
view/collision behavior; and physical-headset/platform/performance checks remain.
The observed AA scene still uses native two-pass world fallback. Completed AA
pistol/crosshair proof does not promote those paths or complete the full VR goal.
