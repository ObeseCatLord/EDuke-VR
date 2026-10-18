# View centering after a slow frame

The private software multiplayer crosshair test exposed an existing native
view-centering instability. It joined successfully and received controller
input, but submitted only one XR world frame before the native camera coverage
guard rejected subsequent views. Single-player world/UI tests passed in the
same runtime, so this was not a generic UI or software multiview failure.

The exact eye rejection was the yaw-forward half-space, caused by large body
pitch swings before the harness changed either tracked pose. Native CON and
bounded angle traces showed the horizon crossing level repeatedly while XR
pitch input remained zero. `P_UpdateAngles` scales its existing centering delta
by elapsed view time. A slow frame makes the correction exceed the remaining
distance to level, and the next frame amplifies the error in the other
direction. When the native centering counter expires, the camera can remain
near its pitch limit. The original pose/collision/FOV guard was correct to
reject that unsupported view.

## Incremental correction

The native centering update now clamps its result to the interval between the
previous horizon and level 100. Its existing near-level completion resets the
counter. Ordinary updates that stay within this interval are unchanged;
delayed updates converge instead of crossing. Native counters, movement locks,
angle events, simulation/network ownership and XR calibration remain reusable
and unchanged. No independent pitch state, new camera controller or broader
renderer acceptance was introduced.

`EDUKE32_XR_TEST_AIM` additionally enables bounded native before/after angle
receipts and the first eye rejection reason. These are test diagnostics, not
new aiming policy. An initial temporary trace passed the ClockTicks class
directly through printf varargs and shifted its displayed fields; the final
trace explicitly casts it. Use the final trace or native CON observations for
field-level evidence.

## Actual proof

`tools/vr/smoke_view_center_cpu.py` runs the real classic CPU game in a GPU-denied
namespace. A CON fixture sets one initial horizon and native centering counter,
then delays the next real view update with one post-event busy loop. Subsequent
horizons come only from `P_UpdateAngles`. Observer timing and native clock
ticks corroborate the delayed interval. It compares a preserved pre-fix binary
with the corrected executable, including a normal-rate convergence case.

Final `work/view-center-qualification-{high,low,normal}.json` cases pass. With
the delayed interval, baseline 140 crossed to 81.91 and baseline 60 crossed to 120.85;
the corrected binary reached 100 and reset the native counter in both cases.
Both normal-rate traces converged monotonically to 100. Standalone corrected
mode also checks convergence when no reference executable is supplied.

```sh
python3 tools/vr/smoke_view_center_cpu.py \
  --binary "$PWD/work/eduke32-cpu-input" \
  --reference-binary "$PWD/work/eduke32-cpu-input-before-melee" \
  --grp /absolute/path/to/owned/DUKE3D.GRP --work-dir "$PWD/work"
# Repeat with --start-horizon 60, then separately with --normal.
```

Actual software OpenXR multiplayer results after the correction:

- `work/software-xr-lab-crosshair-centered`: all 13 checks pass, including actual
  world/HUD 60-frame receipts, independently projected both-eye pixels,
  parallax, unchanged world depth and exact reticle ray/server-shot equality.
  Maximum color error 1/255; independent projection error below 6e-7 NDC.
- `work/software-xr-lab-crosshair-occluded`: all 13 checks pass. Native world
  depth blocks all 24 covered reticle pixels in each eye; image changes 0 pixels,
  with unchanged depth and exact server-ray agreement.

Both use actual revision 4 native peers, real remote-runtime poses and native
shots. The hardware GPU is absent, windows remain private/unmapped, client core
validation is clean and owned runtime processes are reaped. Earlier failed
crosshair runs remain preserved; no evidence is relabeled as passing. This
qualifies the bounded camera/aiming cases, not unrestricted head pitch,
room-scale collision, models, physical headset or full SPS coverage.
