# Full-pitch head tracking and eye placement

Updated 2026-10-18.

## Problem

Polymost's CPU visibility projects the world onto a plane perpendicular to the
view *yaw*; it clips everything behind that plane (`SCISDIST`). The XR adapter
used to reject any eye whose frustum crossed the plane and submitted **no
frame**. With a ~100° headset FOV that happened at roughly ±40° head pitch, so
looking at the floor, a ceiling, stairs or pickups froze/blanked the headset.
Eyes leaving the sector (leaning into walls, standing taller than a low
ceiling) were also rejected.

## Implementation

- `makeEye` derives the pass yaw from the view direction (or from the view's up
  vector when looking straight up/down) and checks every real FOV corner
  against the yaw half-space. If any corner is within ~1° of the plane the eye
  is **split** into two passes of the same physical camera:
  - front: yaw `θ`, pitch `p`, roll `r`;
  - back: yaw `θ+π`, pitch `π−p`, roll `r+π`.
  `Yaw(θ+π)·Pitch(π−p)·Roll(r+π) = Yaw(θ)·Pitch(p)·Roll(r)`, so both passes
  render the same image; each covers its own half of the screen.
- `polymost_xrViewPitch` gives Polymost the exact pitch sine/cosine (cosine may
  be negative), a tight viewport-direction clip at the split plane and a
  smaller wall near plane (1/16 unit). Native horizon-derived pitch and
  `SCISDIST=1` are untouched for unsplit and flat rendering.
- The second pass keeps the first pass's depth (`yax_polymostclearzbuffer`).
  Sprites/mask walls are collected per pass, deduplicated for one CON animation
  transaction, and drawn per pass with a 4-bit eye/pass membership.
- Held models and the world crosshair use the front pass camera; they are full
  3D transforms and are not clipped at the yaw plane.
- Split frames use the existing per-eye reference path, not the multiview
  replay (a collection holds one camera rotation per eye). Unsplit frames keep
  single-pass stereo unchanged.
- `placeEye` clamps the tracked eye height into its sector and, if the native
  sector lookup or line of sight from the body camera fails, binary-searches
  back towards the body camera instead of dropping the frame.

## Verification

`tools/vr/smoke_xr_pitch.py` (private software-XR lab) drives the simulated HMD
through level, 35/60/89/90° down, 60/90° up, a 70°-down/40°-yaw/20°-roll pose,
a 2 m forward lean and a 1 m height offset, capturing both eyes and depth via
`EDUKE32_XR_CAPTURE_REQUEST`. All ten poses submit distinct stereo frames; steep
poses report 2+2 passes; no frame rejection or world stop.

Cleared-depth pixels on floor views (seam measure): near plane 1 → ~1,500;
1/16 → 0 for 60/90° down. The rolled diagonal pose keeps ~100 scattered pixels
along the shared edge (rasterization of two independently clipped passes).

Normal E1L1 single-pass coverage is unchanged (opaque 60/60, masks 58/60).

## Remaining

- Split frames are two-pass per eye (up to four room traversals per frame);
  pairing split passes in the multiview replay is future work.
- Residual sparse seam pixels in rolled poses; mirrors/YAX are still excluded
  from the XR world path as before.
- Physical headset comfort/performance not measured.
