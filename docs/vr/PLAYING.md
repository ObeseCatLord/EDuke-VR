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
| `EDUKE32_XR_PHYSICAL_THROW` | `1` | pipebombs: hold trigger, swing, release to throw with your hand's real speed/direction; off-hand trigger detonates live remote bombs |
| `EDUKE32_XR_FINGER_TRACKING` | `1` | OpenXR hand tracking drives the segmented hands when available |
| `EDUKE32_XR_PIXELATED` | `1` | force nearest (unfiltered) textures |
| `EDUKE32_XR_BODY_TILE` | `1405` | first-person body = the third-person Duke model (head/arms hidden) |
| `EDUKE32_XR_RETRY` | `1` | restart a stopped XR session (1, 2, 4, 8, 16 s backoff, 8 attempts); a held-model receipt mismatch drops one frame instead of stopping |

Any variable you export explicitly overrides the preset. `EDUKE32_XR=1` keeps
the old behaviour (everything off unless set), which the test harnesses use.
If a weapon has no held model defined, its shots come straight from the
controller aim pose instead of being suppressed.

## Controls (default)

| Control | Action |
| --- | --- |
| Left stick | move/strafe |
| Right stick | turn (x; smooth or snap); hold up: weapon wheel |
| Right trigger | fire |
| Left trigger | open/use |
| Right A / B | jump / crouch |
| Right stick click | quick kick |
| Left X / Y | previous / next weapon |
| Either grip | run |
| Menu button | menu |
| Left stick click | voice push-to-talk (when `voice_mode 1`) |

In menus: triggers/A advance, B back, sticks navigate.

Bound profiles: Oculus Touch, Valve Index, HTC Vive (trackpad as stick, right
menu = crouch, right pad click = jump), WMR, and the KHR simple controller.

## Weapon wheel

Hold the right stick up: a ring of your weapons (their 3D models) opens in
front of and above your weapon hand, facing you, and the held weapon hides.
Turn your wrist about 20 degrees toward a weapon to highlight it (it grows,
brightens and spins; the controller pulses), then let go of the stick to
switch. Weapons you don't have or have no ammo for are dark and can't be
picked. Shrinker/Expander and Freezer/Flamethrower each have their own slot;
the switch goes through the normal weapon keys, so it works in multiplayer.
Turning is paused while the wheel is open. `EDUKE32_XR_WEAPON_WHEEL=0`
disables it. Verified with `tools/vr/smoke_xr_wheel.py`.

## Voice chat (multiplayer)

Built in when libopus is available. In VR your microphone transmits by voice
activation as soon as you join a game (`voice_transmit 2`, the default, means
on in VR, off on desktop); the HUD shows `MIC READY` / `MIC LIVE` and
`> name` for whoever is talking. Other players' voices come from where they
are: louder and panned when near, fading to a centred "radio" level beyond
`voice_spatial_distance` (about 24 m), following your head in VR.

| Command / cvar | Default | |
| --- | --- | --- |
| `voice_transmit` | 2 | 0 off, 1 on, 2 auto (VR on, desktop off) |
| `voice_mode` | 0 | 0 voice activation, 1 push-to-talk (VR: left stick click; desktop: `voice_ptt_key` scancode) |
| `voice_vad_sensitivity` | 55 | 0-100 |
| `voice_input_gain` / `voice_volume` | 1 / 1 | |
| `voice_radio_volume` | 0.45 | distant talkers |
| `voice_device` | "" | recording device (`voice_devices` lists them) |
| `voice_enable`, `voice_hud` | 1 | |
| `voice_loopback` | 0 | hear yourself (mic test) |
| `voice_mute <name\|slot>`, `voice_status`, `voice_restart` | | |

Opus 24 kbps (~3 kB/s per talker) on its own unreliable channel; the server
relays only between clients that announced voice support, so older clients
are unaffected. Opus is BSD-licensed (system library). Verified with
`tools/vr/smoke_voice.py` (test tone, relay, 440 Hz decode, head-tracked pan).

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
launcher maps `duke-vr-assets/v6-original`: original, redistributable models
built from primitives in a chunky Duke 3D style with palette-quantised,
unfiltered skins (Duke Nukem Forever was used only as visual reference). Older
private packages are used only if v6 is missing and never with `--release`.
Models need `tag_muzzle` and `tag_palm_left`/`tag_palm_right` (or `tag_grip`);
frames are chosen from the native weapon counter as `fire_NN`, holding the
nearest earlier authored frame, else `rest`. An optional `<skin>_glow.png`
becomes a DEF glow map (muzzle flash), drawn by the explicit held-model path
(multiview collection falls back to per-eye for that model). While a held
model is shown the native 2D weapon/hand ART for that weapon is suppressed;
tinted HUD palettes (underwater, night vision) fall back to the 2D card.
Verified with `tools/vr/smoke_xr_weapons.py`: every weapon drawn in hand,
counter-keyed fire frames advancing, native shots and haptics for each.

Hands: 16 segments per hand follow OpenXR hand-tracking joints when available
(`EDUKE32_XR_FINGER_TRACKING=1`), otherwise button poses (fist, point,
trigger, relaxed); with a weapon they take that weapon's solved `hold_*` pose.

Mods / Alien Armageddon: `EDUKE32_XR_HUD_MODEL_MAP` (lines `hudTile modelTile`)
selects a held model from the HUD weapon tiles a frame draws; the choice holds
through animation tiles until the selected weapon changes (one-frame latency on
switches). The launcher builds this map for AA from v6's
`metadata/aa_inventory.json` (69 families on tiles 30100+). Verified through
AA's real start flow with `tools/vr/smoke_xr_aa_weapons.py`: the controller A
button advances AA's opening screens, and AA's character-select cursor follows
the weapon hand's pointing (tracked yaw/pitch feed the native look input) or
the right stick.

Other players (and you, in mirrors) are drawn with the `vr_duke` model on the
native APLAYER action tiles and hold their current weapon: its held model is
placed with `tag_grip` on the model's animated `tag_weapon_right` instead of
the classic pickup icon over the head. This also works in flat (non-XR)
builds that load the same DEF. The first-person body is the same model with
the head and arms hidden. VR assets are authored with MD3 +Y to the model's
right, so the native sprite path draws tagged player models x-flipped.

World models in XR: native sprite models (third-person players, HRP props)
are placed in camera-relative Build units and mapped with the world pass's
own rotation in XR views; previously any head pitch sheared them. Verified in
multiplayer with `tools/vr/smoke_xr_mp_body.py` (dedicated server, flat peer,
XR peer: the flat player is drawn holding his weapon at level and -20 deg
pitch, and the XR player's swing throw spawns the pipebomb on the server).

Trigger gating: a frame hitch no longer re-arms the trigger release gate
(only invalid tracking or a gap over 2 s do), and held models stay visible on
slow frames; firing itself still needs a fresh tracked sample.

## Redistributing

`package/vr/make_release.py OUT` assembles a redistributable tree: launcher,
DEF builder, AA compatibility CON, docs, GPL text, the binary and a source
archive of the current commit, plus only the v6-original models, skins, hand
rig and metadata. The asset manifest's `release_excludes` (private reference
tiles and comparison sheets) are enforced, and the DEF builder must succeed
with `--release` on the assembled tree. No game data is included; players
supply their own DUKE3D.GRP or AA install. Nothing is uploaded.

Tracked pitch note: with `EDUKE32_XR_STICK_PITCH=0` native view centering
(hard landings, auto-centering) is cancelled instead of locking tracked aim;
previously it could disable VR shots and held models indefinitely.

## Immersive pipebombs

With the pipebomb selected, hold the weapon-hand trigger, swing and let go:
the bomb leaves your hand with the controller's measured velocity (peak of the
last 120 ms; releases under 1 m/s don't throw). The native pipebomb actor,
bounce, fuse, damage and multiplayer replication are unchanged: the swing
speed (0.75 m/s steps up to ~11 m/s) and direction travel in spare bits of
the existing hand-shot sample, and the host releases the bomb on that tick.
In remote-detonation mode the next bomb stays in your hand; while bombs are
live the off-hand trigger detonates them (instead of Open/Use). Verified with
`tools/vr/smoke_xr_throw.py`.
