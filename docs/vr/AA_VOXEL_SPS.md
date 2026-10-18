# Native indexed voxel MASK stereo

Status: **bounded adapter implemented and privately qualified**. Full-world SPS
remains incomplete. Actual AA still uses native two-pass masks because its large
voxel props exceed the existing expanded-geometry collection limit. This is a
measured CPU collection boundary, not evidence of a GPU failure.

## Native boundary and implementation

Base `b5ca91f`. An opt-in, bounded diagnostic at the existing post-animation
model/voxel guard identified AA tile913, owner575, palette0, cstat0x11, modern
voxel221, without a native MD3 mapping. The owned `voxels/props.def` maps it to
`voxels/props/0913_maskwall2.kvx`. The native reference visibly renders the pillar.

The adapter retains native visibility/sorting, voxel meshing, palette/shade,
transform/pivot/flip calculation, texture selection and cleanup. It intercepts
only the final native `glDrawElements` while the existing MASK collection is
active. It expands the native index stream in forward order into existing
eye-owned packets, with the native modelview/MVP and cull state. Replay uses the
same shader and ordered mask stream. Each packet restores culling, including
disabling it for subsequent ordinary ART. No renderer, animation clock, protocol,
asset converter or world-state layer was added.

Admission currently requires a warm modern 8-bit indexed voxel, native compatible
material/state, opaque sprite alpha, and valid bounded finite geometry. Legacy,
slab, shadow-hack, floor/slope, translucent, nonindexed and MD3 families retain
native fallback. These are qualification boundaries, not the final product scope.
Native indexed atlas creation does not invoke the ordinary texture-mutation hook,
so a cold atlas must be rejected before entering the voxel path. Native fallback
warms it, and the following frame can collect it. Once collection is active, even
an already-rejected collection consumes later native voxel draws without pixels.

Packet preparation now writes an explicit output packet. Only the ordinary fan
caller sets its pending-transport flag; voxel packets do not masquerade as fans.
No additional sprite identity is needed for this eye-owned geometry path. The
existing complete shared-state comparison controls pairing; transforms remain
eye-specific. Future shared indexed geometry would require asset identity.

## Qualification

Final XR SHA256:
`fb85776012336d255256abebc9931e2003cc260093dbdc9937b5e61151b3d02d`.
XR and non-XR NETCODE builds passed; existing smmalloc warnings only. Logs:
`work/aa-voxel-build-v4.log`, `work/aa-voxel-build-flat.log`.
The new non-XR binary is retained at `work/eduke32-net-voxel`.
No physical headset, GPU performance or new multiplayer claim is made here.

Aggregate evidence is sibling `../evidence/aa-voxel-validation.json` (relative to
the repository root). Runtime artifacts remain local and ignored. All runtimes
used private CPU llvmpipe/LVP Monado/Xvfb namespaces with clean OpenXR validation,
complete owned-process cleanup, and no desktop focus/input or installed edits.

| Case | Required and observed result |
| --- | --- |
| Zero IPD | One paired voxel; exact native/two-pass/SPS RGB and raw depth |
| Stereo | One paired voxel; exact two-pass/SPS RGB/depth; distinct eyes |
| Unequal eye visibility | Two eye-owned voxel draws, zero paired; exact reference |
| X flip | Native winding changes CW to CCW; 23,548 native pixels change; exact SPS |
| Palette1/shade8 | Native resolved shade10; 23,824 native pixels change; exact SPS |
| Reject before voxel | Later actual voxel draw suppressed; exact native fallback |
| Cold atlas | Real atlas eviction; exact frame12 fallback; positive frame13 replay |
| Fault after voxel draw | Actual draw receipt, empty-frame finish, no partial projection/capture, live process |
| Unqualified translucent voxel | Explicit frame12 guard fallback, no mask commit, exact native reference |

Ordinary cases retain translucent ART, depth-only equal-depth groups and disabled
depth writes. Every successful differential case preserves native callback counts
and unchanged collection color/depth snapshots. The normal native voxel-versus-ART
control changes23,640 pixels, proving the asset is visible. The after-draw fault
also matches an independent native transaction counter control; absence of an
image alone is not accepted as success.

Actual packet diagnostics show the voxel inherits alpha0.250980407 from its
immediately preceding ART packet. NPOT is0,1,0,1; native drawpoly cleanup resets it.
Nondefault inherited NPOT is not claimed by this fixture. Native alpha/material
values are captured, not normalized. Runtime evidence mutation checks reject
missing suppression, eviction, recovery, wrong-frame/zero-voxel recovery and
missing fallback (eight checks including the two positive baselines).

Main matrix: `work/software-xr-voxel-matrix-v4`, seven ordinary/fault differential
passes plus the after-draw proof. Its original translucency case intentionally
failed qualification: native MASKWALL2 spawn strips that bit, so requested map
bytes did not prove draw-time state. The final fixture sets it with native CON
after spawn in every reference/control path. A first corrected CON used an invalid
literal actor index and failed compilation; the gamevar-index correction passes
in `work/software-xr-voxel-translucent-v5`. Both failed experiments are retained;
the main matrix's child exit1 is not mislabeled as a passed outer run.

The reusable oracle accepts `--voxel-file`, `--voxel-flip`, `--voxel-palette`,
`--voxel-shade`, `--voxel-translucent`, and `--mask-failure before-voxel|voxel-cold`.
Use `tools/vr/software_xr_lab.py` with absolute dependency/work paths as for the
other private renderer fixtures. The local after-draw driver is
`work/voxel-abort-check.py`; it uses the same oracle runner, a frame12 counter
report, and the native control. `work/voxel-matrix.py` records sequential cases.

## Actual AA result and next decision

`work/software-xr-aa-voxel-v4/aa-hand-model-t04wlko2/result.json` passes all45
existing gameplay/model checks, including native firing/ammo/reload, mounted
muzzle and ray, actual MD3 stereo contribution, same-frame native/SPS image and
depth, zero collection writes, and native ART effect boundaries. World tally is
opaque59MV/1fallback, masks0MV/60fallback, fullMV0; held models26MV separately.

The first capacity rejection is tile913, eye0, four prior packets:
209,796 expanded vertices +69,930 requested =279,726 >262,144. Three prior voxel
packets account for209,790 vertices; ordinary ART adds6. The limit is6MiB CPU payload per eye,12MiB combined (24bytes/vertex),
excluding vector overhead.
Replay GPU allocation is per packet/pair rather than a fixed262,144 buffer.

Before another implementation, measure the complete native frame demand. Compare
a small measured bounded cap adjustment with reuse of native indexed VBO/IBO
geometry in the existing ordered packet stream. The latter can avoid repeated
index expansion but needs exact geometry identity for sharing, element-buffer
state restoration and native asset lifetime evidence. Native `voxfree` owns buffer
deletion; do not infer safe cross-frame references. Do not build another renderer
or adopt held-model instance policy merely to remove this limit. Reopen the
design with a verified brief and Astra review before changing the storage model.

## Senior review dispositions

Both effective models/efforts were independently verified as Astra/xhigh:
design turn `01a14eed-1091-7f42-9c0a-9edba8ae7a00`, code turn
`01a14ef5-2302-7831-a7b9-dbefe3d40a56`. Main reviewed subsequent bounded diagnostic
and test-harness changes and performed the actual runtime qualification.

| Recommendation | Disposition |
| --- | --- |
| Preserve native preparation/cleanup and final-draw boundary | Adopted; existing ordered MASK packets and shader only |
| Require warm atlas because voxel upload bypasses mutation hook | Adopted; real eviction/fallback/recovery proof |
| Consume draws even after collection rejection | Adopted; later-voxel suppression receipt plus zero-write snapshots |
| Delete proposed owner+voxel pairing identity | Adopted for eye-owned payloads; identity is unnecessary here |
| Separate packet preparation from fan transport | Adopted explicit output; fan caller alone sets pending |
| Preserve native alpha/NPOT/cull state | Adopted; inherited alpha and flipped winding qualified; nondefault NPOT not claimed |
| Prove voxel-specific unequal-eye submission | Adopted two actual eye-only voxel draws |
| Code review: generic fault reason is insufficient | Fixed; suppression and eviction/recovery markers are mandatory |
| Code review: nondefault voxel palette/shade untested | Added visible palette1/shade8 native control and exact stereo proof |

No production correctness blocker was identified in the reviewed adapter. Reviews
did not certify full AA SPS, full camera/material coverage or physical performance.
