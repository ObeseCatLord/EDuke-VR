# Playing EDuke32 VR

Experimental Linux/OpenXR build. Single-player and native multiplayer use the
same binary; a dedicated server needs no XR runtime.

## Build

```sh
make -j8 NETCODE=1 USE_OPENXR=1 obj=obj-xr duke3d_game=eduke32-xr eduke32-xr
```

## Launch

Start your OpenXR runtime (Monado/WiVRn/SteamVR), then:

```sh
package/vr/eduke32-vr-play --grp /path/to/DUKE3D.GRP
package/vr/eduke32-vr-play --aa /path/to/alien_armageddon_566
```

The launcher sets `EDUKE32_XR=play`, links the held-weapon/hand models from the
sibling `duke-vr-assets` checkout into `~/.local/share/eduke32-vr/` and passes a
generated DEF. Installed game files are never modified. Options:
`--left` (left-handed weapon), `--no-models`, `--assets DIR`, `--binary FILE`;
anything after `--` goes to EDuke32 (e.g. `-- -map E2L1.MAP`).

### What `EDUKE32_XR=play` enables

| Variable | Preset | Meaning |
| --- | --- | --- |
| `EDUKE32_XR_UI` | `2` | HUD, menus and console composited over the stereo world |
| `EDUKE32_XR_SINGLE_PASS` | `1` | multiview world rendering (falls back per frame when needed) |
| `EDUKE32_XR_AIM` | `right` | weapon hand (`left`, `right` or `head`) |
| `EDUKE32_XR_HAND_SHOTS` | `1` | shots leave the tracked hand, replicated in multiplayer |
| `EDUKE32_XR_WEAPON` | `1` | 2D weapon ART follows the controller |
| `EDUKE32_XR_MODELS`, `EDUKE32_XR_AA_MODELS` | `1` | held MD3 pistol/RPG when a model is defined |
| `EDUKE32_XR_WEAPON_MOUNT` | `1` | palm-calibrated muzzle from model tags |
| `EDUKE32_XR_HAND_LEFT_TILE` / `_RIGHT_TILE` | `30010` / `30011` | floating hand models |
| `EDUKE32_XR_MOVE` | `head` | stick movement direction: `head`, `hand` (left controller) or `body` |
| `EDUKE32_XR_STICK_PITCH` | `0` | right stick Y does not pitch the world (head tracking owns pitch) |
| `EDUKE32_XR_SNAP_TURN` | unset | degrees per right-stick flick (e.g. `45`); unset = smooth turning |
| `EDUKE32_XR_HAPTICS` | `1` | weapon-hand pulse when firing, both hands when damaged |
| `EDUKE32_XR_RESOLUTION` | `auto` | game/eye render size from OpenXR's recommended per-eye size (`WxH` to force, `window` to keep the config) |
| `EDUKE32_XR_RENDER_SCALE` | unset (1.0) | multiplies the OpenXR size, 0.25–2.0 (e.g. `0.8` for speed, `1.4` to supersample) |
| `EDUKE32_XR_RETRY` | `1` | restart a stopped XR session (1, 2, 4, 8, 16 s backoff, 8 attempts); a held-model receipt mismatch drops one frame instead of stopping |

Any variable you export explicitly overrides the preset. `EDUKE32_XR=1` keeps
the old behaviour (everything off unless set), which the test harnesses use.
If a weapon has no held model defined, its shots come straight from the
controller aim pose instead of being suppressed.

## Controls (default)

| Control | Action |
| --- | --- |
| Left stick | move/strafe |
| Right stick | turn (x; smooth or snap) |
| Right trigger | fire |
| Left trigger | open/use |
| Right A / B | jump / crouch |
| Right stick click | quick kick |
| Left X / Y | previous / next weapon |
| Either grip | run |
| Menu button | menu |

In menus: triggers/A advance, B back, sticks navigate.

Bound profiles: Oculus Touch, Valve Index, HTC Vive (trackpad as stick, right
menu = crouch, right pad click = jump), WMR, and the KHR simple controller.

## Known limits

- The desktop window mirrors the left eye at the eye resolution; a window
  manager may clamp it to the monitor, which does not affect the headset.
- Mirrors render per eye from the front pass camera (not in the back half of a
  steep-pitch split view); frames with a visible mirror use the per-eye path.
- Steep head pitch and room-over-room maps render through the per-eye path
  instead of multiview (see FULL_PITCH.md).
- Weapons without a mapped held model (and tinted HUD palettes) use the
  controller-attached 2D ART card.
- No headset comfort/performance qualification yet.

## Performance notes

- While an OpenXR session runs, `xrWaitFrame` paces the game: the native
  `r_maxfps` limiter, desktop vsync and `r_glfinish` are bypassed so the game
  can run at the headset's refresh rate.
- Ordinary frames render both eyes with one multiview submission. Steep-pitch,
  room-over-room and mirror frames use the per-eye path (about 2x draw calls).
- The flat desktop mirror pass is skipped in XR; mirrors are drawn per eye.
- Lower `EDUKE32_XR_RENDER_SCALE` first if the headset drops frames.

## Held weapon models

Every stock weapon can be held as a 3D model. The pistol keeps its calibrated
family on its pickup tile (21); the others use reserved tiles `30020 + weapon
index` (2 shotgun … 12 flamethrower), so world pickups keep their sprites. The
launcher maps the reference-built `duke-vr-assets/v5-vanilla` set when present,
falling back to the older v3 set. Models need `tag_muzzle` and
`tag_palm_left`/`tag_palm_right` (or `tag_grip`); frames are chosen from the
native weapon counter as `fire_NN`, holding the nearest earlier authored frame,
else `rest`. An optional `<skin>_glow.png` becomes a DEF glow map (muzzle
flash), drawn by the explicit held-model path (multiview collection falls back
to per-eye for that model). While a held model is shown the native 2D
weapon/hand ART for that weapon is suppressed; tinted HUD palettes (underwater,
night vision) fall back to the 2D card. The v5 set is built from the Duke
Nukem Forever (2001) meshes adjusted toward the Duke 3D handheld sprites (see
`duke-vr-assets/v5-vanilla/README.md`). Verified with
`tools/vr/smoke_xr_weapons.py`: 10 weapons drawn in hand, counter-keyed fire
frames advancing, firing feedback.

Mods / Alien Armageddon: `EDUKE32_XR_HUD_MODEL_MAP` (lines `hudTile modelTile`)
selects a held model from the HUD weapon tiles a frame draws; the choice holds
through animation tiles until the selected weapon changes (one-frame latency on
switches). The launcher builds this map for AA from the aa-v1 arsenal metadata
(69 families on tiles 30100+).

Tracked pitch note: with `EDUKE32_XR_STICK_PITCH=0` native view centering
(hard landings, auto-centering) is cancelled instead of locking tracked aim;
previously it could disable VR shots and held models indefinitely.
