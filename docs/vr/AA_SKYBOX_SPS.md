# AA truecolor skybox: bounded world SPS increment

Status: **implemented and privately qualified for native shading mode 4**.
Full-world single-pass stereo remains incomplete. The final AA run uses opaque
multiview for 59/60 frames (one cold texture fallback); all 60 mask phases still
use native two-pass rendering because world model/voxel sprites are excluded.

## Implemented behavior and qualification

The implementation follows the reviewed native packet adapter below. It admits
only clamped, opaque truecolor skyboxes with a native replacement record and
the existing shader/material/state guards. It captures native fog start/end/color
into existing packet fields, includes them in existing pairing, and restores
them for classified skybox packets or model packets. Indexed ART never receives
the model/sky fog upload. Native sky geometry, UVs, shaders and traversal remain
the reference; no asset, protocol or gameplay policy changed.

Final XR binary SHA256:
`5c12ba81cb88c2f6be06e3c95b6b249a798bdd614a9071fe43cfcc945de124fb`.
Build: `work/aa-sky-build-xr-v2.log`, existing smmalloc warnings only.
Both final runtime suites used private CPU llvmpipe/LVP Monado/Xvfb namespaces,
clean OpenXR core validation and complete owned-process cleanup. No desktop
input/focus or installed-game changes occurred.

- `work/software-xr-aa-sky-diff-v2/stereo-diff-21wizfjx/result.json`: exact RGB
  and raw depth for native/two-pass/SPS at zero IPD and two-pass/SPS at stereo and
  unequal poses. Actual skybox replay counts: zero 8/8 paired, stereo 19/19
  paired, unequal 33 eye-only. Unequal clipping does not claim paired draws.
- The same captured frame contains ceiling shade8/pal0/visibility32 and floor
  shade24/pal1/visibility16. Independent native visibility controls alter
  110647 ceiling sky pixels (32379 unsaturated) and 496 floor sky pixels
  (37 unsaturated), inside a native replacement-versus-ART mask of 121190 pixels.
- Omitting sky fog upload deliberately changes 110646 sky pixels per eye while
  preserving complete depth. The fault requires valid two-eye captures, visible
  unsaturated color differences inside the native sky mask, unchanged depth,
  and actual frame-12 skybox replay. Missing captures cannot count as success.
- Ordinary RGBA walls and `r_skyzbufferhack=1` retain explicit capture-frame
  fallback with exact two-pass color/depth. Opaque fallback logs now also emit
  at frame12, matching the existing bounded capture diagnostic convention.
- `work/sky-fog-oracle-negative-controls.json`: all seven oracle checks pass,
  including rejecting missing capture/eye/depth, changed depth, no RGB change,
  and changes outside the sky mask.
- `work/software-xr-aa-sky-final/aa-hand-model-wmemxh88/result.json`: all 45 AA
  gameplay/model checks pass, including native shot/ammo/reload, model stereo
  color/depth equivalence and zero collection writes. The world tally is opaque
  59 multiview / 1 two-pass, masks 0 / 60, full multiview 0. Held-model SPS is
  separate (24 observed frames in this run).

The first matrix was a useful failed qualification: all parity passed, but the
floor baseline was fully fog-saturated and invisible in its ART-derived mask,
and fallback logging stopped before frame12. Both fixture/diagnostic issues were
fixed; no renderer workaround or weakened acceptance was used. Main inspected
`work/aa-sky-proof-preview.png` as well as the numerical evidence.

## Code review disposition

Effective reviewer independently verified as Astra/xhigh, turn
`01a14edd-101d-7e43-8193-85ada8a17c58`. Source-only review; no reviewer edits or
runtime launches. No concrete production rendering defect found in this seam.

| Finding | Disposition |
| --- | --- |
| Persistent fallback logs cannot satisfy a frame12 assertion | Fixed: retain initial three logs and add the capture-frame log. Actual fallback controls now pass. |
| Missing/depth-only fault captures can falsely prove fog use | Fixed: require complete two-eye sky RGB effects with unchanged nontrivial depth; seven negative checks pass. |
| Second visible fog state unproven | Fixed: invert the floor visibility control so the baseline is unsaturated; both native region gates pass. |

## Next actual world boundary

The final AA log rejects `unsupported model or voxel mask sprite` after its
cold texture mutation. The current diagnostic does not identify the tile or
distinguish MD3 from voxel; do not assume which renderer needs extending.
`polymost_drawsprite` rejects after `tileUpdatePicnum` and before native direct
draw, preserving the no-write collection contract. The next small step is a
bounded resolved-candidate diagnostic at that guard (owner/tile/palette/cstat,
sector, model/frame/skin or voxel identity), followed by a controlled AA run.

For MD3, the native raw-tsprite path already resolves animation, transform,
offsets, fog, skin and tint. Existing held-model geometry/material capture is
reusable, but currently demands an explicit context and separate model-instance
stream. The mask traversal mixes models with ordered sprite/wall fans; wrapping
all masks in the held-model phase would violate that contract. Voxels instead
draw indexed VBOs and have no corresponding geometry capture seam yet. Preserve
native partition/sort/interleave and qualified fallback while choosing the
smallest demonstrated family; no new visibility pass or renderer is justified.

## Pre-implementation blocker and behavioral reference

`work/software-xr-aa-world-diagnostics-v2/aa-hand-model-057viubl/eduke32.log`
records the first 16 opaque rejections as tile89, method0x4, flags0x107:
`PTH_CLAMPED | PTH_HIGHTILE | PTH_SKYBOX | PTH_NOTRANSFIX`. The material is
truecolor, has a native high-tile record, and has no indexed or alpha flag.
Its actual shader state is fog1, palette0, detail0, glow0, colorOnly0,
NPOT0,1,0,1, sampler7. All 60 production opaque and mask frames use native
two-pass rendering. The same run passes 45 bounded AA checks and separately
qualifies held-model SPS; that does not qualify world geometry.

The opt-in `EDUKE32_XR_TEST_OPAQUE_REJECTIONS=1` diagnostic now identifies the
first failing admission predicate, preserving original predicate order and
native fallback. It is bounded to16 records per process. The AA runner exposes
`--opaque-rejection-diagnostics` so the real child receives it.

Native skybox traversal, clipping, UV scaling and fog are the behavioral
reference. The existing world packet stream already receives final native
per-eye geometry and UVs and replays them through the unchanged native fragment
shader. High-tile skybox UV scale is baked into vertices; skyboxes avoid the
ordinary HICR texture matrix. Model shared geometry is not appropriate here:
keep the existing eye-owned world vertex payload and paired multiview draw.

## Minimal adapter and rejected alternatives

The generic packet already has `fogStart`, `fogEnd`, `fogColor`; material
compatibility compares them and the outer replay saves/restores GL fog state.
Before this increment only the model collector/uploader populated/restored them.
Opaque collection captured the fog enable uniform alone. Relaxing the truecolor guard
without fixing that gap would render using incidental final collection state.

The reviewed implementation contract was:

1. Recognize only opaque, color, clamped skybox+hightile packets with a native
   high-tile record, no indexed/alpha flags, palette0/fog1/colorOnly0/detail0/glow0,
   identity texture/modelview, and the existing valid shader/sampler/projection/
   depth/blend/color state. Initially qualify native shading mode4 only.
2. Capture actual native GL fog start/end/color immediately before diverting the
   native draw, using existing packet fields. Require finite values and a finite,
   nonzero end-start difference. **Permit reversed ranges**: native mode4 uses
   them for its no-fog result.
3. Restore those fields for models or the explicitly classified skybox family.
   Do not upload zero-initialized fog fields for ordinary indexed ART packets.
   Reuse existing pairing and outer state restoration. No new shader or uniform
   is needed; the native fragment directly calculates its linear fog expression.
   An additional GL_FOG_MODE policy would be redundant for this shader.
4. Give skyboxes a distinct packet classification and count paired skybox draws
   separately from total skybox draws. Existing generic paired-wall counters and
   flat-sky counters cannot prove the intended sky submission.

Estimated production footprint: one family predicate, one existing-field capture
and upload seam, small replay accounting; no new renderer, visibility system,
protocol, persistent state, or animation clock. Reopen the decision if this
turns into a generic command recorder or a second sky traversal.

A separate sky renderer/cubemap would duplicate native working behavior. Generic
RGBA admission would prematurely include alpha, ordinary HICR texture matrices,
detail/glow and unqualified fog policies. Disabling AA artwork would change the
reference. These alternatives are rejected for this increment.

## Smallest end-to-end acceptance

Extend the existing `check_stereo_oracle.py` and generated private map/DEF fixture,
referencing owned AA sky textures read-only. No installed assets are modified.

- Put the same texture in two simultaneously visible native sky regions with
  distinct native fog inputs, for example ceiling plus floor. Use ceilingpal/
  floorpal, shade and visibility; sky fog does not use sector.fogpal.
- Prove both regions have visible unsaturated fog contributions through native
  control captures. Mode4 produces endpoints around1e37 and essentially constant
  blends, so a distance gradient is the wrong oracle. Separate runs with
  different final states do not prove per-packet ownership.
- Require exact zero-IPD native/two-pass/SPS color+depth, then nonzero and unequal
  pose two-pass/SPS equality. Include a visible horizon/seam for texture and eye
  transform coverage.
- Deliberately omit per-packet fog upload in a bounded test-only fault and require
  this same-frame fixture to fail. The test must detect the demonstrated bug.
- Require positive paired skybox draws for zero/stereo cases. Unequal clipping
  may legitimately produce eye-only packets; require real visible skybox replay
  and exact pixels there rather than claiming every sky polygon pairs.
- Preserve explicit native fallback for ordinary non-sky RGBA replacement and
  `r_skyzbufferhack=1`: the latter recursively submits a masked companion outside
  this color-only admission. Do not silently disable those native paths.
- Rerun production AA unchanged after fixture qualification. Collection stops at
  the first rejection, so tile89 evidence does not identify all later materials.
  Masks, world model/voxel sprites and full production image parity remain their
  own gates. Do not call the full port complete from an opaque increment.

## Astra senior-review disposition

Brief: ignored `work/AA_SKY_SPS_REVIEW.md`. Effective model/effort independently
verified: Astra/xhigh, turn `01a14ed3-031d-7b62-9cf8-4df4c8493ae5`.
Source inspection only; no design-review runtime or edits.

| Recommendation | Disposition |
| --- | --- |
| Reuse native packet adapter; reject separate sky renderer | Adopted. Existing geometry, shader and fog fields suffice for the bounded family. |
| Fog proof must contain different visible states in one frame | Adopted. Replaces the draft's incorrect gradient assumption; requires final-state substitution failure. |
| Generic paired calls do not prove paired skybox submission | Adopted. Add family-specific paired and total replay counters. |
| Capture actual fog fields and upload only for classified family/models | Adopted. Do not introduce singular zero ranges for indexed ART. |
| Reversed fog range is native and valid | Adopted. Validate finite/nonzero difference, not positive ordering. |
| GL_FOG_MODE gate is redundant with unchanged fragment shader | Adopted. Keep shading4 as qualification scope, without invented mode policy. |
| Native sky-depth recursion must remain explicit fallback | Adopted. Add regression alongside ordinary high-tile control. |

The earlier investigator's fog0 proposal contradicted the observed fog1 state.
Main caught it before implementation; the corrected trace and review above
govern the next increment. No human taste or permission decision is pending.
