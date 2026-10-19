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
- Residual sparse seam pixels in rolled poses.
- Physical headset comfort/performance not measured.

## Room-over-room (YAX) maps

`G_XRDrawRooms` used to return false for any map with YAX bunches, so the XR
frame was never submitted (many AA 5.66 maps, e.g. all of HTTKB/Attrition,
are v9 YAX maps). The opaque phase now calls the native `yax_drawrooms` after
each eye/pass room traversal, exactly as `G_DrawRooms` does: other levels are
drawn with their own native sprite animation and masks per view, and the base
level keeps the single shared animation transaction and per-eye mask pass.
`yax_drawrooms` only clears depth when `yax_polymostclearzbuffer` is set, so a
split back pass keeps its front pass's depth. YAX frames use the per-eye
reference path (no multiview collection).

Consequence: on YAX maps the per-level `G_DoSpriteAnimations` runs once per
view (natively it already runs once per level per frame). Verified on AA
`maps/httkb/high_rise.map`: level/60° down/90° down/60° up all submit distinct
stereo frames with the expected split passes.

## Mirrors

Native Polymost draws a mirror before the room, marking its region in the
stencil buffer. The eye depth arrays are now `GL_DEPTH24_STENCIL8`
(multiview and per-eye attachments use `GL_DEPTH_STENCIL_ATTACHMENT`).
`drawEyeMirror` repeats `G_HandleMirror`'s mirror choice and draw order with
each eye's front-pass camera (prepare, room, per-view sprite animation, masks,
complete). Script `EVENT_DISPLAYROOMS`/`EVENT_RESETGOTPICS` stay with the native
once-per-frame call. Because `G_ClearGotMirror` clears the native gotpic bit
before the XR pass, the XR pass remembers whether its own previous frame drew a
mirror. Verified with `tools/vr/mirror_fixture.py`: both eyes show the
reflection, matching a native flat capture (`tools/vr/native_capture.py`).
