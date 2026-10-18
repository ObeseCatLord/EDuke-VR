# Experimental pistol palm / muzzle calibration

This opt-in increment derives the existing authoritative shot point from a
measured handle contact. It does not complete controller fitting, the full
arsenal, continuous hand contact, or animated reload attachment.

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
No server-side asset load or additional protocol is introduced. A local
presentation record keeps the sampled right vector together with the accepted
shot and its ownership; the model uses that roll and the quantized shot direction.

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
that melee is unchanged. Native collision can displace the gun from the hand,
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

## Focused Astra design review

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

## Validation status

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

**Measured remaining attachment defect:** floating hands still use current
render-frame grip/body while the gun uses the native simulation sample. At rest
the measured tag separation was 1.45 mm. Deliberate 60 mm and 120 mm controller
position steps produced 60.99 mm and 121.39 mm visible separation on the first
captured frames; after settling/body movement it was 1.76 mm. The gun's relative
axes still matched its own saved roll to 1.26e-5, so this is temporal hand/gun
separation, not a tag/roll transform error. These step tests do not estimate
normal hardware motion latency. Coherent hand-and-gun presentation is the next
required implementation decision; this opt-in is not promoted as finished fit.

Also unqualified: isolated grip-only loss/recovery, fresh mounted-crosshair
pixel/depth proof, exact reload-surface contact, controller-specific anatomical
orientation/finger wrapping, physical headset acceptance, and broader arsenal
bindings. Native AA fire still uses ART; static root correctness does not turn
those weapon effects into complete 3D presentation.
