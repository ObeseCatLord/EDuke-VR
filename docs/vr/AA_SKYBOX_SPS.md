# AA truecolor skybox: next bounded world SPS increment

Status: investigated and reviewed; **skybox admission is not implemented yet**.
Full-world single-pass stereo remains incomplete. The existing fallback keeps
native AA rendering available while the unsupported families are qualified.

## Actual blocker and behavioral reference

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
Only the model collector/uploader currently populates/restores them. Opaque
collection captures the fog enable uniform alone. Relaxing the truecolor guard
without fixing that gap would render using incidental final collection state.

The next implementation should:

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
