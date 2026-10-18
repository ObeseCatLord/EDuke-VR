# Experimental pistol palm / muzzle calibration

This opt-in increment derives the existing authoritative shot point from a
measured handle contact. It does not complete controller fitting, the full
arsenal, physical headset acceptance, or animated reload attachment.

`EDUKE32_XR_PISTOL_MOUNT=1` selects this calibration for a qualified stock or
standard AA Duke pistol. Map the supplied private tagged MD3 to palette-zero
`FIRSTGUNSPRITE` (21) using the native DEF loader. Existing XR, controller aim,
hand-shot and model-presentation options retain their separate meanings. AA
also requires its existing explicit `EDUKE32_XR_AA_MODELS=1` opt-in.

For selected left/right hand, with model coordinates +X forward, +Y right,
+Z up and 64 units/metre:

```
d = tag_muzzle - tag_palm_left_or_right
muzzle_LOCAL = grip.position + aim.rotation * (d.y, d.z, -d.x) / 64
```

The normal native input sample transforms and quantizes that point into the
existing `VRShotInput`. The existing reach bound, wire format, native server
collision resolver, weapon events, spread and firing timers remain in use.
No server-side asset load or additional protocol is introduced. Native firing
continues to consume the accepted simulation sample. Local mounted presentation
uses the current acquired XR frame, as described below; its reticle is an aiming
preview and can differ from the last accepted shot during motion.

Asset identity is independent of fire/reload counters, shade, palette, texture
availability and HUD appearance. It distinguishes unsupported, stock and
standard AA pistol; the conservative AA variant requires Duke, laser off and
zero pistol upgrades. Existing presentation guards remain separate. Thus AA's
firing ART fallback does not move the firing origin. Calibration always reads
palette-zero model metadata and never performs texture/material preflight.
Missing grip/tags or invalid calibration for a supported selected mount yields
an enabled-but-invalid shot and the existing release latch. Unsupported weapon
families retain the previous aim-point behavior.

The shared origin also supplies pistol-selected quick kick. Its impact placement
and reach therefore change with this opt-in; missing calibration suppresses
both fire and quick kick. This is explicit shared-origin behavior, not a claim
that melee is unchanged. Native collision translates the visual gun and its holding hand together,
and the existing two-metre muzzle reach limit includes the barrel extension.

## Private asset contract

The Astra-produced sibling `duke-vr-assets/pistol-palm-mount` contains separate
stock and AA packed masters, MD3/PNG, reproducible scripts, geometry evidence
and exact preservation checks. Two added tags lie on the original handle panels:

| Tag | Native coordinates |
| --- | --- |
| `tag_palm_left` | (-5.684600830, 1.594866037, -6.423392773) |
| `tag_palm_right` | (-5.682834625, 4.187694550, -6.488524914) |

All 27 frame records, surface bytes, legacy tags and skin bytes are unchanged.
Removing the two new tags reconstructs each original MD3 byte-for-byte. Legacy
stock and AA tag bases differ; this positional contract uses tag origins only.

These are authored central side-panel contacts, not measured physical controller
contact points. OpenXR core grip lies within the controller, rather than on a
palm surface. Hand orientation and finger fitting remain separate. Static tags
remain on the rest/fire handle geometry; unchanged reload motion drifts up to
10.025 mm at the left tag and 21.896 mm at the right. The loader exposes the
first frame's tags only. No animated palm-contact claim follows from these tags.

## Earlier authoritative-muzzle design review

Explicit `gpt-6-astra` / `xhigh`, independently verified current turn
`01a14e90-bc74-7662-aac9-f1a464e91afb` (thread
`01a14e90-bc31-7120-98a7-05438ccbe1b9`). Brief retained in ignored
`work/pistol-mount-review-brief.md`. Main disposition:

| Recommendation | Disposition |
| --- | --- |
| Keep calibrated muzzle in the existing native input/shot stream | Adopted; no render-only gameplay offset or new packet. |
| Store same-sample right/roll with shot and ownership | Adopted; generation/player/hand/model/family/shot checks and reset invalidation. |
| Separate family identity from transient presentation | Adopted; tiny native family sampler reused by presentation. |
| Missing calibration fails invalid; unsupported identity retains old behavior | Adopted; canonical palette-zero metadata, no material dependency. |
| Do not synchronize another hand/body simulation merely for this proof | Adopted; current floating hands remain current-render samples. Moving hand/gun separation must be measured and remains unqualified. |
| Explicitly qualify shared-origin quick kick | Adopted as required acceptance; no kick-counter origin switching. |
| Do not claim reload contact from static tags | Adopted; measured asset drift documented above. |

## Focused implementation review

Astra/xhigh turn `01a14e9b-8a05-7213-8f3a-b8dffbe413f4`, independently verified
from its current turn metadata, found no confirmed production correctness
defect in the scoped implementation. It identified three test gaps:

| Finding | Disposition |
| --- | --- |
| Quick-kick trace is emitted before range/damage processing | Fixed with a reachable real enemy, replicated damage and a too-far target control. Preserve the same-origin comparison. |
| AA idle mount presence does not prove the firing ART boundary keeps that origin | Added raw source-pose/tag reconstruction and a read-only native pre-shot body anchor, compared with the actual native ray. Require a measurable difference from the old aim point. |
| Whole-hand loss cannot prove grip-only loss while aim/trigger remain valid | Explicit remaining limitation. The current Monado remote control toggles the whole controller. Do not relabel that run as grip-only coverage. |

The main also repaired the gameplay runner's missing model-output diagnostic
configuration before qualifying it. Motion/contact measurement was outside
the review's code scope and is separately described with its actual evidence.

## Earlier authoritative-muzzle validation

Bounded acceptance is recorded in sibling `evidence/pistol-mount-validation.json`.
All runs use GPU-denied private CPU Monado/Xvfb, clean core validation and owned
process cleanup. Each row below is a separate actual runtime suite:

| Case | Checks | Actual evidence |
| --- | ---: | --- |
| Tagged asset, mounting disabled | 27 | Original stock MP fire/reload and exact native/SPS color/depth remain intact. |
| Mounted right, 25-degree roll, floating hands | 33 | Independent raw LOCAL grip/tag palm and muzzle projection; actual server origin/ray; stereo and hand loss/recovery. |
| Mounted left, native animation | 29 | Left rest contact plus native MP fire/reload model frames and server origin. |
| Missing palm tags | 10 | No pistol ray or quick-kick trace, no ammo consumed. |
| Wall | 11 | Actual native resolver clamps muzzle and hits the blocking wall. |
| Whole-controller loss | 12 | Loss and held recovery suppress fire; release/repress produces one real shot. Not grip-only proof. |
| Enemy damage | 12 | Real native target health converges 30→22 on server and client. |
| Selected-pistol quick kick | 15 | Shared calibrated origin, real enemy health 21→6 on both peers, pistol ammo unchanged by kick. |
| Too-far quick kick | 15 | Native ray hits distant target, native range check rejects damage, target stays 25 on both peers. |
| AA native firing/reload with independent origin | 45 | Input counter1/native firing counter2 uses reconstructed muzzle exactly after integer quantization, 0.26993m from old aim point. Ammo48→47 and native reload/model SPS remain functional. |
| Controller roll/position steps and body movement | 37 | Sampled weapon roll remains coherent; actual gun/hand separation is measured, not declared acceptable. |

The six combat suites and left/right static suites used the first mount binary;
the final AA-origin and motion suites used the subsequent binary adding only a
bounded test diagnostic. The manifest records both hashes rather than claiming
every run used one build. The earlier AA model-only mount pass is superseded by
the independent origin suite above. Parser negative controls reject both a
missing calibration sample and an actual ray moved back to the old aim origin.

**Prior attachment defect (6dfef7d):** floating hands used current
render-frame grip/body while the gun used the native simulation sample. At rest
the measured tag separation was 1.45 mm. Deliberate 60 mm and 120 mm controller
position steps produced 60.99 mm and 121.39 mm visible separation on the first
captured frames; after settling/body movement it was 1.76 mm. The gun's relative
axes still matched its own saved roll to 1.26e-5, so this is temporal hand/gun
separation, not a tag/roll transform error. These step tests do not estimate
normal hardware motion latency. This evidence led to the current-frame presentation change below; the opt-in
is still not promoted as finished controller fit.

Other remaining qualifications are described below, including isolated
grip-only loss/recovery, exact reload-surface contact, controller-specific anatomical
orientation/finger wrapping, physical headset acceptance, and broader arsenal
bindings. Native AA fire still uses ART; static root correctness does not turn
those weapon effects into complete 3D presentation.


## Current-frame mounted presentation

The mounted pistol now uses current raw grip/aim poses and the same frozen
interpolated body as the eyes. A stateless calibration calculation supplies both
the existing native input path and this visual path. The visual request passes
finite, integer and two-metre reach validation before the existing
`G_VRResolveShot(..., muzzlePosition)` collision path; it does not call
`G_VRSetShotInput`, poll XR again, change native clocks or add network state.

The existing world/HUD frame data carries the resolved visual origin, direction,
orientation and collision translation. The mesh, native weapon ART and projected
reticle consume it. The selected floating hand stays on its current raw grip and
receives the same translation correction. Its corrected palm must pass the
existing sector/visibility checks; it is never independently clamped. The other
hand retains ordinary live grip presentation. Mesh counter/material eligibility
is separate from this spatial policy, including AA firing's ART fallback.
Missing current supported calibration hides its mounted presentation until valid;
unsupported weapon families retain ordinary floating-hand behavior.

This removes the persistent native-to-render `PistolMountSample` cache. Reset,
tracking-reference, input-clear and frame cancellation invalidate the visual data
through existing ownership boundaries. No additional attachment lifecycle exists.

**Changed contract:** local reticle/muzzle preview follows current visual aim;
actual firing, impacts, damage and packets remain on the accepted 30 Hz native
sample. Static equality is tested. Exact moving-trigger correspondence and the
visual-versus-accepted difference during fire remain unqualified. Static tag
contact still does not prove animated reload surface or anatomical finger fit.

### Astra design disposition

Astra/xhigh current turn `01a14eae-a533-71b1-8eaa-eeb7770116e4`, independently
verified. Main brief: ignored `work/MOVING_MOUNT_REVIEW.md`.

| Recommendation | Disposition |
| --- | --- |
| Prefer current-frame visuals over delaying the hand to the 30 Hz sample | Adopted; absolute current-pose projection is required alongside contact. |
| Reuse optional-muzzle collision resolver and explicitly bound reach | Adopted; no second resolver or gameplay stream. |
| One acquired-frame spatial policy for mesh, ART and reticle | Adopted; existing frame-owned geometry extended, native snapshot cache deleted. |
| Translate gun/holding hand together, revalidate corrected palm | Adopted; no independent hand clamp or saved correction. |
| Preserve native accepted-shot authority and revise the preview contract | Adopted; exact equality is claimed only for the stationary proof. |
| Require current-pose negative controls, both hands, simultaneous movement | Adopted; prior-pose substitution fails independent absolute projection. |
| Prove multiple moving XR frames within one unchanged native tick | Still open; explicit `subtick_qualification.passed=false`, required for full acceptance. |

The system Monado null compositor is hardcoded to 20 Hz
(`/usr/src/debug/monado-multilib-git/monado/src/xrt/compositor/null/null_compositor.c:617`).
The supported immediate-wait debug pacing experiment still produced no qualifying
within-tick pair. Its temporary lab option was removed. No native time override
or weakened cadence threshold was introduced. `--require-subtick` makes this
additional gate fail explicitly; ordinary motion suites report its unqualified
status separately from their bounded geometry checks.

### Current validation

Final evidence is in sibling `evidence/moving-pistol-validation.json`. Both hands
are checked against actual acquired raw poses and actual submitted matrices, with
native/SPS color and depth comparison. Controller translation/roll occurs while
native locomotion moves the body hundreds of Build units. Right maximum palm
separation is 1.764 mm; left is 1.862 mm (3 mm tolerance). Previous-pose controls
produce projection errors above 0.10 NDC while current-pose errors stay below
0.004 NDC. Static mounted crosshair pixels match the independently depth-tested
projection within one channel value, preserve world depth exactly, and match the
real native server origin/impact.

Remaining gates: within-tick moving-frame cadence, moving-trigger authority and
visual divergence, mounted wall-contact/recovery geometry, isolated grip-only
loss, reset/generation/family transitions, AA ART-to-mesh moving continuity,
reload/anatomical/controller fit, broader arsenal, hardware performance/headset.
These are completion gates, not claims inferred from passing static tests.


### Current implementation review

Astra/xhigh turn `01a14ebd-66f9-7071-9e88-173caab5a810`, independently verified.
The reviewer found one concrete flag regression, verified its fix, and reported
no remaining concrete implementation defect in scope. Main dispositions:

| Finding | Disposition |
| --- | --- |
| Mount option alone could hide ART/reticle when hand shots were disabled | Fixed: select this spatial policy only with hand shots enabled and actual hand aim. Added real-runtime disabled-hand-shots regression with floating hands. |
| Tiny same-tic movements could pass while a prior pose was stale | Strengthened: qualification requires both gun and hand prior-pose projections to fail on that same-tic pair. Cadence remains unqualified in the 20 Hz lab. |
| Render stream rows preceded final mask/HUD submission | Fixed: only rows whose serial matches existing next-frame `lastSubmittedSerial`/`worldReceipt` accounting enter the submitted-transform oracle. No second owner or lifecycle. |
| Native wall tests do not prove clamped visual hand/gun contact | Retained as an explicit next gate; no claim that native wall damage tests qualify the visual correction. |

The final stream checks require actual submission receipts. Removing all receipt
lines must make the submitted current-pose check fail; this is separately recorded
as a parser negative control. A first motion fixture incorrectly accepted tiny
angle rounding as body motion; it was repaired to require more than 20 horizontal
Build units during captured movement, with an above-dead-zone stick input.
