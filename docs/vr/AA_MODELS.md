# AA standard pistol model: first runtime binding

This opt-in binding uses the private AA `duke_pistol.md3` and skin through the
existing world model renderer. It currently covers the idle, unmodified, single
Duke pistol. The full AA arsenal, floating hands, native firing/reload model
animation, and headset fitting remain incomplete. Exported art is not runtime
qualification.

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
zero firing/reload counters, normal unobstructed presentation and settled shade
are eligible. Other characters, upgrades, weapons, switching, special
presentations, nonzero HUD palette and forced widescreen stretching retain ART.
This intentionally qualifies less than every possible AA FIRSTGUN draw.

The existing MD3 loader, tags, transforms, skin cache, world ordering, native
two-eye path and model multiview collector perform the rendering. Native CON
still executes normally. A scoped consumer at the common Polymost rotatesprite
boundary validates the actual FIRSTGUN body draw: tile 2524, pistol ID, palette,
settled native shade plus two, flags, angle, alpha, blend and one body instance.
Only that body draw is consumed. Other native artwork and side effects continue.
An exceptional receipt mismatch cancels the already-written XR frame; ordinary
unsupported states choose ART before model emission.

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

See sibling `evidence/aa-model-validation.json` for accepted runs and exact
binary hashes. These are software-rendered tests. AA world phases can still
fall back to two-pass rendering independently of a successful model multiview
submission. Existing AA startup invalid-sector diagnostics remain unresolved.

Before broader binding, retain the gates in [AA_MODEL_DESIGN.md](AA_MODEL_DESIGN.md):
AA-specific opaque/translucent occlusion, invalid-pose and mode transitions,
exceptional cancellation, mirror/crosshair/menu effects, native animation and
multiplayer presentation. Current firing/reload frames deliberately use native
ART; no new animation clock has been introduced.

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
