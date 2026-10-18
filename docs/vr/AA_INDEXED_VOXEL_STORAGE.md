# Reuse native voxel geometry for world stereo

Status: bounded implementation privately qualified; final evidence is below. This is an
increment of the full VR port; complete headset/platform/arsenal support remains
open. The previous expanded-geometry checkpoint is in AA_VOXEL_SPS.md.

## Decision and adapter

The complete native AA workload measured 30 voxel draws, 1,901,718 voxel indices
and 24 ART vertices per eye, consistently over three frames. The old per-eye
262,144 expanded-vertex cap rejected the fourth large prop. Raising it to
2,097,152 would fit that scene with about 10% headroom, but retains approximately
87.1 MiB of two-eye expanded voxel payload before replay copies/uploads. These
are measured counts and calculated storage costs, not a GPU performance claim.

The adapter instead borrows each voxel's existing immutable native VBO/IBO during
the synchronous, once-animated MASK collection/replay interval. It preserves the
existing ordered walker, shader/material policy, native transforms and cleanup.
There is no new renderer, resource owner, cross-frame cache, animation system or
network protocol. If native geometry mutation becomes reachable inside this
interval, reject at that concrete boundary rather than inventing a generation
system without evidence.

Geometry identity, buffer names and index count are part of the shared packet
comparison. Different sprite instances may share one multiview submission when
geometry/material match; transforms remain eye-specific. Positive quad counts,
GLsizei limits, native buffer bindings, CPU index bounds and finite positions/UVs
are checked. Earlier admitted packets avoid rescanning the same immutable asset
within this collection. ART/held-model CPU vectors and packet limits remain.

Replay binds native indexed buffers locally and uses a constant eye selector.
Following ART explicitly rebinds the normal streamed VBO and enables its eye
attribute. Entry element-buffer binding, VAO/array state and all four components
of the generic eye attribute are restored, including after submitted-draw faults.
Existing cold-atlas rejection, consume-after-rejection and partial-frame abort
semantics remain authoritative.

## Native reference evidence

The actual-AA opt-in `--mask-oracle` reuses the existing temporary native oracle
target. At world frame59 it copies both current opaque/held-model eye images,
renders native MASK into those copies, collects MASK without writing the real
eyes, and replays the collected stream. Pristine animated sprites, eye membership,
visibility and clock remain shared. Native CON callbacks are not replayed.

A test-only first-resolved-draw snapshot compares native and collection material,
transforms, bindings and relevant GL state. It reports disagreement rather than
normalizing inherited state. Missing/unequal input receipts fail qualification.
The reference and replay must have exactly equal RGB and complete raw depth in
both eyes; collection before/after must be unchanged; MASK must visibly change
both color and depth; actual indexed voxel submission is required. Counter-only
success is insufficient.

First actual-AA run `work/software-xr-aa-indexed-v1` passes the existing 45
checks and new MASK checks. Reference/replay RGB and depth match exactly; visible
color contribution is24,276/24,395 pixels and depth19,201/19,378. Both first draws
are ART with equal inputs. It submits all30voxels and1,901,718indices in paired
multiview draws. World tally: opaque59MV/1fallback, MASK57MV/3fallback, full57MV.
The three MASK fallback frames report native texture/palette mutation. This is
one actual scene/run, not unrestricted AA material or camera coverage.

Four-pillar stress at `work/software-xr-indexed-pressure` exceeds the former cap
and matches native/two-pass/SPS color/depth and callback counts, with zero
collection writes. Prior `work/software-xr-voxel-pressure-baseline` proves the
actual old capacity rejection. Remaining controls/final binary evidence are
recorded below after qualification completes.

## Review dispositions

Astra/xhigh design turn `01a14f0a-c3ef-70c1-b29b-55dbeb72a9f2`:

| Finding | Disposition |
| --- | --- |
| Compare minimal cap adjustment to reuse | Measured complete demand first; reuse deletes expansion without changing native policy |
| Identity/count must be inside compared region | Both captured below texture and before eye transforms |
| Removing cap removes arithmetic bound | Explicit positive/count checks; keep per-collection finite/index validation |
| Switching VBOs adds GL restoration duties | Draw-local bind, following ART rebind, EBO and four-component generic constant restore |
| Native borrowing lifetime | Synchronous interval only; no persistent generation/cache or captured-pointer replay dereference |
| Capacity fixture alone cannot prove different-geometry pairing | Admitted-packet key refusal plus actual unequal-eye image proof; same-material different-mesh image control remains unclaimed |
| Native reference may change inherited state | Compare first resolved complete inputs; exact pixels/depth and no-write snapshots still required |

No physical GPU performance, headset ergonomics or new multiplayer qualification
is claimed by these software-rendered checks. All labs use private CPU
llvmpipe/LVP Monado/Xvfb, without desktop input/focus or installed-game writes.


Astra/xhigh code review turn `01a14f14-b05f-75a3-b7e8-58d0932ba407` found no
production blocker. Effective model/effort were verified independently from
minimal local metadata. Two harness false-pass routes were fixed: restoration
must have an explicit frame12 success/fault receipt, and AA's indexed submission
must be from the selected frame59, with exactly two matching input receipts.
The final matrix exercises the rebuilt sentinel with the matching harness.

The lean geometry control copies an admitted real packet, requires an exact
copy to match, independently changes geometry identity, VBO, IBO and index count
and requires each to refuse pairing, then confirms differing per-eye transforms
remain compatible. This proves six comparison properties without adding another
buffer owner. Together with actual unequal-eye RGB/depth parity it supports key
refusal and eye-owned rendering. **It does not prove an end-to-end same-material,
different-mesh image result.** That coverage limit is retained explicitly.

## Final qualification

- `work/software-xr-indexed-matrix-v5/matrix.json`: all 11 cases pass. The six
  admitted cases require exact RGB/raw depth, native callback equality, zero
  collection writes and the explicit frame12 state/key controls. Cold atlas,
  rejection before voxel, invalid captured buffer reference and translucent
  voxel retain exact native fallback. The after-draw fault passes ten checks,
  including restored nonzero EBO/full attribute constant, actual indexed draw,
  canceled projection/empty finish and once-only native transaction counts.
- `work/software-xr-indexed-hidden-v6/result-hidden.json`: independently hiding
  pillars1/2/3 changes56,220 /63,044 /23,848 native pixels; pillar0 in the pressure
  matrix changes23,628. Each prop is visibly contributing. These native-only
  controls exit0 and clean up, but the outer XR lab intentionally cannot observe
  an OpenXR validation client and labels that outer run failed. No XR validation
  claim is made for a flat-native-only child.
- `work/indexed-oracle-negative-controls.json`:11 positive/negative checks pass,
  including omitted frame59 submission, absent/duplicate inputs, missing/wrong
  restoration receipt, wrong frame/fault and missing/failed geometry keys.

Failed attempts remain recorded: v4 matrix had a main-agent Python variable
name error and an outer child-diagnostic ESRCH; cleanup succeeded. Hidden-v5
used the wrong native capture filename and stopped before a game launch. The
corrected runs above supersede them. The v2 matrix was exploratory before the
stricter sentinel checks. No failed outer run is relabeled as successful.


Final actual AA evidence:
`work/software-xr-aa-indexed-final/aa-hand-model-8p1i4vyv/result.json` passes all
**52 checks** (the existing 45 plus seven MASK/counter checks). Both eyes have
exact native/replay RGB and raw depth, unchanged collection snapshots, equal
first inputs and actual indexed submission of 30 voxels. Color contribution is
24,589 / 24,755 pixels; depth contribution is 19,231 / 19,398. Final world tally:
**opaque 59 MV / 1 fallback, MASK 58 MV / 2 fallbacks, full world 58 MV / 60**.
The final scene's two native fallbacks are texture/palette mutation. Differences
from the exploratory run's 57/60 reflect its live native timing; both retain
same-frame image comparison instead of comparing different gameplay moments.

Both final XR labs (matrix and actual AA) have clean observed OpenXR validation,
child/game/Monado/Xvfb exits0 and complete cleanup. No desktop focus/input, installed
game/asset changes or GPU access were used. The native-only control lab limitation
above remains correctly recorded.

XR SHA256 `b4d6cc4f42dd6b7ff77c1387533eeaed55e031bb7cf042fa953dc94b326cc5c7`;
non-XR NETCODE binary `work/eduke32-net-indexed-voxel`, SHA256
`877291fd05469fe149bc68825f3abeec068e54a7a25e8cbfa2fa35804b7c447b`.
Build logs `work/aa-indexed-voxel-build-v4.log` and
`work/aa-indexed-voxel-build-flat.log` contain only existing smmalloc warnings.
The qualified binaries embed precommit `f06dfd9-dirty`; do not rebuild merely for
metadata and imply that another hash was tested. Aggregate local evidence:
`../evidence/aa-indexed-voxel-validation.json` relative to repository root.

## AA model request

A fresh verified Astra check found the offline package complete: 69 weapon/
equipment dispatch entries, 68 physical designs and two basic floating hands.
No AA character body was added. Weapons use 128×128 textures, hands64×64, with
editable Blender masters, MD3/PNG and GLB exports. All indexed paths/source hashes
and existing geometry/texture validators pass. See sibling
`../duke-vr-assets/aa-completion-check/COMPLETION_REPORT.md` for coverage and exact
limits. The full runtime arsenal still needs selectors, hand/controller fitting,
effects and native animation/counter integration. Do not confuse completed art
with completed in-game integration or regenerate the finished package.
