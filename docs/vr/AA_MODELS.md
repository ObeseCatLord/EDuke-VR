# AA standard pistol model binding

This opt-in binding uses the private AA `duke_pistol.md3` and skin through the
existing world model renderer. It covers the unmodified, single Duke pistol;
named positive frames can follow its native counter as described below. The
full AA arsenal attachment, complete firing effects and headset fitting
remain incomplete. Independent tracked floating hands are now implemented; see
[FLOATING_HANDS.md](FLOATING_HANDS.md). Exported art is not runtime qualification.

## Native boundary

Enable `EDUKE32_XR_AA_MODELS=1` alongside the existing models, weapon-card,
right-hand aim and tracked-shot options. Load the shipped AA compatibility CON
entry, installed AA scripts/assets and an ordinary private DEF mapping the
pistol's `rest` frame to pickup tile 21. Do not map its HUD tiles to native HUD
models. The test runner creates this disposable mapping without changing the
installed game or adding proprietary assets to Git.

AA's grpinfo sets only `GAMEFLAG_NOPOLYMER` (1024), omitting `GAMEFLAG_DUKE`.
The explicit AA adapter accepts that identity; the stock qualifier still
requires Duke. Shared ownership, live-player, camera, native weapon-state and
tracked-pose checks remain in force.

The sampler reads native player fields and persistent AA variables before world
rendering. It does not read the late-initialized `hudweap` aliases or execute
the HUD script early. Only Duke/startmode 1, no pistol upgrades or laser mode,
normal unobstructed presentation and settled shade are eligible. Other
characters, upgrades, weapons, switching, special
presentations, nonzero HUD palette and forced widescreen stretching retain ART.
This intentionally qualifies less than every possible AA FIRSTGUN draw.

The existing MD3 loader, tags, transforms, skin cache, world ordering, native
two-eye path and model multiview collector perform the rendering. Native CON
still executes normally. A scoped consumer at the common Polymost rotatesprite
boundary validates actual body and magazine draws: exact native tile, ID,
palette, settled shade, flags, angle, alpha, blend and one instance per role.
Other native artwork and side effects continue.
An exceptional receipt mismatch cancels the already-written XR frame; ordinary
unsupported states choose ART before model emission.

## Native-counter frames

The private `aa-v2-pistol-native` export preserves the original 196-triangle
gun, topology, UVs, 128-square skin and static tags, adding 27 named poses.
The sampler reads `kickback_pic` and `reloading`; it never advances an asset
clock, runs CON early, or changes ammo and reload behavior. Positive model
frames additionally require the exact standard clip/reload/fire/total/hold/flag
parameters. Missing named frames retain ART before emission, so the original
single-frame AA asset remains usable.

| Native counter | Model frame and consumed roles | Preserved native artwork |
|---|---|---|
| 0 | `rest`; body 2524 | Other effects |
| 1–5 | No model emitted | Complete firing sequence, including composite muzzle flashes and native shade fade |
| 6–9, reloading | `reload_06..09`; body 2528 | Other effects |
| 10–19, reloading | `reload_10..19`; magazine 2530 then body 2529 | Other effects |
| 20–24, reloading | `reload_20..24`; body 2529 | Separate hand 2532 |
| 25–26, reloading | `reload_25..26`; body 2529 | Other effects |
| 27 or unsupported state | No model emitted | Native presentation |

AA's HUD increments TotalTime before the fire/reload branch, so its reload
frame boundary is six, while the stock binding retains five. Its magazines use
ID zero and bodies ID one. Required receipt roles are body plus magazine at
10–19, and body otherwise. Draw-time equality includes the frozen native
counter and reload flag. The final footer checks completed roles and ownership;
later native packet polling cannot retroactively change already drawn pixels.

The baked flashes in tiles 2525/2526 include glow overlapping the gun. The
private exterior-flame masks are evidence, not a complete replacement effect.
Actual firing also changes player shade to -48, then -24/-12 while AA's
`hud_shadef` follows at -24/-30/-29 in the observed run. The stable-shade guard
correctly declined those recovery frames. The entire firing sequence 1–5
therefore retains ART in this increment; no duplicate shade-fade implementation
has been added. The separate reload hand is
also native artwork, not yet a spatial floating-hand binding. This is a bounded
animation increment, not seamless full-3D pistol presentation.

## Verification and limits

`tools/vr/smoke_aa_hand_model.py` runs under `software_xr_lab.py`, using the
installed AA entry plus a read-only observer, native Duke/START controller
selection and real trigger input. Cases are `model` with `native` or `sps`
submission, `missing` without the optional model mapping, and `missing-frame`
with a private metadata-only copy lacking the named `rest` frame. `duplicate-body`
arms one additional native CON rotatesprite call after a valid model frame;
it must reject the duplicate and cancel before submitting that frame. Evidence includes
body receipts, before/after eye color and depth, native ART coverage, actual
ammo/shot events, and owned private-window cleanup. The SPS case additionally
requires identical same-frame native inputs, byte-exact reference color/depth,
zero collection writes and shared geometry submitted once.

`--animation --model /path/to/aa-v2-pistol-native/duke_pistol.md3` additionally
fires a real trigger, observes a partial native clip, waits for the existing
shade fade to settle, and presses AA's actual Reload/Aim_Down binding. No ammo,
counter, clip or shade values are assigned. The accepted software run observes
reload counters 8–26, including early body 2528, magazine/body roles, hand 2532
alongside accepted model bodies, and final body 2529. All 38 checks pass, including
exact both-eye color/depth reference and zero collection writes for every
captured positive model frame. Ammo is 48→47 from firing and stays 47 during
reload; AA's clip refills 11→12 at counter 26 and returns to idle. Fire ART is
actually observed at counters 1–4. Counters 6/7 are not claimed as observed.

`--missing-reload-frame 19` passes 43 checks using a private copy whose only
changes are within that frame's name bytes. Native counter 19 then has visible
ART and no model sample; counters 20–26 resume accepted model rendering and
receipts. All original geometry, textures and installed game files stay intact.
The first attempt missed an 80 ms reload key pulse between software-rendered
frames; a 300 ms owned-window press supplies real native input reliably in the
accepted run. No gameplay fields were injected.

See sibling `evidence/aa-model-validation.json` and
`evidence/aa-pistol-reload-validation.json` for accepted runs and exact binary
hashes. These are software-rendered tests. AA world phases can still
fall back to two-pass rendering independently of a successful model multiview
submission. Existing AA startup invalid-sector diagnostics remain unresolved.

Before broader binding, retain the gates in [AA_MODEL_DESIGN.md](AA_MODEL_DESIGN.md):
AA-specific opaque/translucent occlusion, invalid-pose and mode transitions,
exceptional cancellation, mirror/crosshair/menu effects and multiplayer
presentation. Firing deliberately uses native ART; no new animation clock has
been introduced. Duplicate or omitted magazine fault paths and complete
weapon/mode transitions remain outside the current runtime proof.

The stock animated-pistol regression now passes. The retained earlier failure
(about 0.0133 NDC) came from the test assuming horizontal world right before
controller roll. That assumption loses the native body's pitched tracking
transform. The corrected independent oracle composes logged native eye
yaw/pitch/roll, inverse actual XR view orientation and the prescribed controller
orientation. Expected axes do not use emitted model matrices or basis vectors.
The engine transform and `2e-5` tolerance are unchanged. Real native firing/reload,
25-degree controller roll and asymmetric runtime FOV cases pass, with maximum
axis errors of `8.12e-7`, `8.77e-7` and `2.43e-6` NDC respectively. Earlier failed
evidence remains recorded. Moving-pose temporal coherence is a separate future
test; this corrected static-pose oracle does not establish it.

## Focused code review

Explicit Astra/xhigh, independently verified current-turn metadata: thread
`01a14e50-4e1b-72f0-bd7a-7fb42f45d0fe`, turn
`01a14e50-4e62-7e42-b76e-cda5faf85c05`. Read-only review of this adapter and its
runner, without runtime/build execution. This was not another broad port review.

| Finding | Disposition |
|---|---|
| AA without named `rest` inherited legacy frame-zero substitution | Fixed: retain that compatibility behavior only for stock models; AA requires the named frame. Add a private missing-rest fixture. |
| Existing stock receipt fault injection bypasses the AA consumer | Closed for a duplicate body: an appended native CON draw, armed after valid model gameplay, reports the duplicate inside the owned segment and cancels the frame before submission. The actual draw path is exercised. |
| Keep bounded sampler and existing world renderer | Adopted; no renderer rescheduling, draw replay or independent animation state. |

The native-counter extension received a separate focused Astra/xhigh review:
thread `01a14e64-48dd-7652-9f56-3e772bf15839`, turn
`01a14e64-4919-7cc2-9b73-0c5c42a61a19`, independently verified. It found no
confirmed engine defect and caught a test that could accept absent flash/hand
captures. Separate nonempty observations and same-serial model/body receipts
now make those checks nonvacuous. The review's early/final reload coverage
recommendation is satisfied at 8/9 and 25/26. Main subsequently narrowed the
firing interval to native ART after actual shade-history evidence; no shade
simulation was added to the adapter.
