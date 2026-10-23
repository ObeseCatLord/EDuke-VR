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
generated DEF. Installed game files are never modified. It always plays the GRP
you pass (an add-on selected in EDuke32's own setup, e.g. Life's a Beach, is not
picked up), skips the setup window (`-- -setup` brings it back) and uses an X11
(XWayland) window, which OpenXR's GL binding needs. Options:
`--left` (left-handed weapon), `--no-models`, `--assets DIR`, `--binary FILE`,
`--glow` (model glow maps: brighter emissive bits, but every VR model is then
drawn once per eye instead of once for both), `--pack NAME` (a model pack folder
beside `v6-original` in `duke-vr-assets`; files it lacks come from
`v6-original`; a pack can ask for unfiltered textures in its `pack.json`);
anything after `--` goes to EDuke32 (e.g. `-- -map E2L1.MAP`). A personal default
pack can be set in `~/.config/eduke32-vr/launcher.conf` (`pack=NAME`); `--release`
refuses packs marked not redistributable. A pack's `pack.json` may also list game data
to autoload (`autoload`, for the games in `games`); its `duke3d.def` is then included,
e.g. a voxel world. Personal packs seen so far: `dnf-private` (Duke, hands, body, foot
and all weapons incl. AA and Caribbean variants) and `voxel-private` (voxel world plus
voxel weapons, foot and player model, base game only; hands and the full body come from
v6). Neither may ever be redistributed.

### Model packs are mods

A VR model pack is an ordinary EDuke32 mod, a folder or a `.zip`:

| file | content |
| --- | --- |
| `vrpack.def` | the models (an EDuke32 DEF) for Duke Nukem 3D and its add-ons |
| `vrpack_aa.def` | the models for Alien Armageddon (optional) |
| `vrpack/pack.txt` | `name=`, `title=`, `filter=` (`nearest` = unfiltered skins), `redistributable=`, `autoload_games=` |
| `vrpack/hand-rig.txt`, `hand-rig-aa.txt` | hand rig, weapon holds, full IK body (names are files in the pack) |
| `vrpack/hud-model-map-aa.txt` | AA HUD tile → held model |
| `vrpack/autoload/*.zip` | game data the pack brings (e.g. a voxel world), loaded with it for the listed games |
| `vr_*.md3`, `.png`, `.skin`, ... | the model files |

Put packs in a `vrpacks/` folder anywhere the game looks for data, e.g. `~/.config/eduke32/vrpacks/`.

The packs are:
- **Original 3D** (`original`, from `duke-vr-assets/v7-original`): the redistributable set.
  - Duke and the vanilla weapons are remodelled to the proportions and designs of the original
    sprites and the Voxel Duke voxels.
  - Single solid shells, low poly, clean painted skins.
- **Original 3D (low-res)** (`original-lowres`): the same models with Quake-style 8-bit,
  low-resolution skins.
- **Personal packs**, never redistributed: Duke Nukem Forever 2001 and Voxel Duke.

- **Options > VR Setup > Models** lists the installed packs (their titles), plus **2D sprites (no models)** (`vr_models 0`), which applies at once.
- Choosing a pack saves it in the game config (`[Setup] VRModelPack`) and loads it on the next start, like any mod. Launched through `eduke32-vr-play`, the game offers to restart right away.
- `-vrpack NAME` picks a pack for one run, and `-vrpack none` loads none.
- A pack added like any other mod (`-g pack.zip`, `-j packdir`, or the `autoload` folder) is used as it is.

`eduke32-vr-play` builds every pack in the sibling `duke-vr-assets` checkout into
`~/.local/share/eduke32-vr/vrpacks/` (symlinked, so it takes a moment) with
`package/vr/build_vr_pack.py`; `build_vr_pack.py ASSETS DIR OUT --zip` makes a shareable zip, and
`make_release.py` ships the original set as `vrpacks/original.zip`. Your `launcher.conf` `pack=`
is only the default until you choose one in the menu; `--pack NAME` overrides for one run.

### What `EDUKE32_XR=play` enables

| Variable | Preset | Meaning |
| --- | --- | --- |
| `EDUKE32_XR_UI` | `2` | HUD, menus and console composited over the stereo world |
| `EDUKE32_XR_SINGLE_PASS` | `1` | multiview world rendering (falls back per frame when needed) |
| `EDUKE32_XR_AIM` | `right` | weapon hand (`left`, `right` or `head`) |
| `EDUKE32_XR_HAND_SHOTS` | `1` | shots leave the tracked hand, replicated in multiplayer |
| `EDUKE32_XR_WEAPON` | `1` | a weapon without a 3D model shows its 2D ART on the hand (never on the HUD) |
| `EDUKE32_XR_MODELS`, `EDUKE32_XR_AA_MODELS` | `1` | held MD3 pistol/RPG when a model is defined |
| `EDUKE32_XR_WEAPON_MOUNT` | `1` | palm-calibrated muzzle from model tags |
| `EDUKE32_XR_HAND_LEFT_TILE` / `_RIGHT_TILE` | `30010` / `30011` | floating hand models |
| `EDUKE32_XR_MOVE` | `head` | stick movement direction: `head`, `hand` (left controller) or `body` |
| `EDUKE32_XR_STICK_PITCH` | `0` | right stick Y does not pitch the world (head tracking owns pitch) |
| `EDUKE32_XR_SNAP_TURN` | unset | degrees per right-stick flick (e.g. `45`); unset = smooth turning |
| `EDUKE32_XR_HAPTICS` | `1` | weapon-hand pulse when firing, both hands when damaged |
| `EDUKE32_XR_RESOLUTION` | `auto` | game/eye render size from OpenXR's recommended per-eye size (`WxH` to force, `window` to keep the config) |
| `EDUKE32_XR_RENDER_SCALE` | unset (1.0) | multiplies the OpenXR size, 0.25–2.0 (e.g. `0.8` for speed, `1.4` to supersample) |
| `EDUKE32_XR_PHYSICAL_THROW` | `1` | pipebombs: hold trigger, swing, release to throw with your hand's real speed/direction; the detonator then comes up in the same hand |
| `EDUKE32_XR_FINGER_TRACKING` | `1` | OpenXR hand tracking drives the hands when available |
| `EDUKE32_XR_PIXELATED` | `1` | unfiltered world ART; model skins nearest up close, mipmapped at a distance |
| `EDUKE32_XR_WEAPON_WHEEL` | `1` | weapon wheel and gadget wheel |
| `EDUKE32_XR_ALWAYS_RUN` | `1` | always run; the right grip walks |
| `EDUKE32_XR_WRIST_HUD` | `1` | status bar as two watches: health/armour on the left wrist, ammo/items on the right |
| `EDUKE32_XR_BODY_TILE` | unset | `1405` shows the third-person Duke model as your first-person body (head/arms hidden) |
| `EDUKE32_XR_RETRY` | `1` | restart a stopped XR session (1, 2, 4, 8, 16 s backoff, 8 attempts); a held-model receipt mismatch drops one frame instead of stopping |

Any variable you export explicitly overrides the preset. `EDUKE32_XR=1` keeps
the old behaviour (everything off unless set), which the test harnesses use.
If a weapon has no held model defined, its shots come straight from the
controller aim pose instead of being suppressed.

## Controls (default)

| Control | Action |
| --- | --- |
| Left stick | move/strafe |
| Right stick | turn (x; smooth or snap); flick down: quick kick |
| Right stick click (Index: rest your thumb on the right trackpad) | hold: weapon wheel |
| Left stick click (Index: rest your thumb on the left trackpad) | hold: gadget wheel |
| Right trigger | fire |
| Left trigger | mighty foot (quick kick); `vr_lefttrigger 1` makes it alt fire instead |
| Left grip | use / interact (doors, switches) |
| Right A / B | jump / crouch |
| Right stick click (Index: trackpad click) | alt fire (mods that have it, e.g. Alien Armageddon); quick kick with `vr_lefttrigger 1` |
| Left X / Y (Index: left A / B) | previous / next weapon; Y is voice push-to-talk when `voice_mode 1` |
| Right grip | walk (you always run; `EDUKE32_XR_ALWAYS_RUN=0` makes the grip run instead) |
| Menu button | menu |

In menus: triggers/A advance, B back, sticks navigate.

Bound profiles: Oculus Touch, Valve Index, HTC Vive (trackpad as stick, right
menu = crouch, right pad click = jump, hold the right pad up for the weapon
wheel, left pad click = gadget wheel), WMR (right stick click = weapon wheel,
left stick click = gadget wheel, right pad click = jump, right menu = crouch),
and the KHR simple controller.

## Body, hands, kicks and pipebombs

- **True full body** (`vr_fullbody 1`, the default when the model pack has it):
  look down and you see Duke's whole body. It stands under the headset, turns
  with you (45 degree deadzone, lines up while you move), leans and crouches with
  your head, its arms reach your tracked hands by IK and its legs walk; the
  mighty foot is its own right leg. Your hands (cut from the same body, fully
  articulated) attach at its wrists. `vr_fullbody 0` switches to floating hands
  and the floating boot. In Alien Armageddon the body is used only while playing
  Duke; the other characters have their own floating hands.
- **Mirrors** show your VR body (head included) with your hands and weapon,
  instead of the native player sprite; no black frame around mirrors.
- **Hands**: one continuous skinned mesh per hand, deformed on the CPU from the
  tracked joints or the weapon's hold pose; the older 16-part segmented hands are
  only a fallback. Close to your face they are no longer sliced open (near plane
  16x closer).
- **Other players and third person**: Duke players use the third-person Duke
  model; characters without a model (e.g. Alien Armageddon's Bombshell) keep
  their sprites, in multiplayer and in mirrors.
- **Old first-person body**: `EDUKE32_XR_BODY_TILE=1405` (only without the full
  body) shows the torso/legs model under you.
- **Mighty Foot**: kicks (selected foot or quick kick) leave your body and go
  where you **look**, not where your hand points, and Duke's 3D boot (with a
  jeans cuff) swings out in front of you. No 2D foot or hand ever appears on
  the HUD: while a weapon has a 3D model, the native 2D weapon display
  (including Duke's 2D hands, the kick knee and the lower/raise animation when
  switching) stays hidden.
- **Pipebombs**: hold the trigger, swing and let go; the bomb flies with your
  swing (a firm 4 m/s throw reaches about 8 m, a hard one 20+ m). In remote
  mode Duke's detonator then comes up in the same hand: pull the right trigger
  to set the bombs off, and the next bomb returns.
- **Tipping** ("shake it baby"): use on a dancer and your off hand holds a wad
  of bills, made at launch from the game's own MONEY art in your GRP.

## Sky, sprites and flat screens

- The sky stays put: it no longer drifts with your head when you look up/down.
- Enemies and other sprites are upright cards that face your head, the same for
  both eyes, instead of turning with each eye's view (`EDUKE32_XR_FACE_BILLBOARD=0`
  restores the old screen-aligned sprites).
- Intermission/bonus screens, loading screens, logos and cutscenes, and the
  menus, appear on a virtual screen fixed in the world in front of you (it
  re-centres when you look well away); controller buttons advance them.

## Wrist HUD

The status bar is drawn as two watches (`EDUKE32_XR_WRIST_HUD`, on in the
preset): turn your **left** wrist toward you to read health and armour, your
**right** wrist for ammo and the selected item. They hide while a wheel is open.
Game messages, voice status and menus stay on the panel in front of you.

## Aiming, 3D models and the 2D fallback

- **Projected crosshair**: Duke's own crosshair is placed on whatever surface
  the weapon hand's aim ray hits (`crosshair`, `crosshairscale` as usual).
- **Laser pointer** (`vr_laser 1`, default off): a thin glowing beam from the
  weapon's muzzle (or the hand when the weapon has no 3D model) to the aim
  point.
- **`vr_models`** (default 1): `vr_models 0` turns every VR model off at
  runtime: held weapons, hands, first-person body, other players' 3D Duke and
  the 3D pistol pickup. Everything falls back to the native 2D art like
  RazeXR: the weapon's HUD sprite (with Duke's 2D hand), cropped to the sprite
  itself, is held in your hand and the weapon wheel becomes a ring of pickup
  sprites in front of you. `eduke32-vr-play --no-models` starts without
  loading any VR models.
- A weapon that has no 3D model in the asset pack (e.g. a mod's custom gun)
  gets the same 2D sprite on the controller on its own, and that hand's 3D
  model hides so there are never two hands. Verified with
  `tools/vr/smoke_xr_models_toggle.py` (also with `--assets` lacking a model).

## Weapon wheel and gadget wheel

Like Q3VR's controller selector. Hold the right stick click (Valve Index: just
rest your thumb on the right trackpad; HTC Vive wands: hold the right pad up): a
ring of your weapons (their 3D models, each in its own bubble) opens in front of
and above your weapon hand, facing you, and the held weapon hides. A blue beam
runs from your hand to a pointer bead on the ring; turn your wrist about 20
degrees toward a weapon to move the bead onto it: its bubble lights up yellow
and grows, the weapon spins and the controller pulses. Let go to switch.
Weapons you don't have or have no ammo for sit in dark bubbles and can't be
picked. Shrinker/Expander and Freezer/Flamethrower each have their own slot; the
switch goes through the normal weapon keys, so it works in multiplayer. Turning
is paused while the weapon wheel is open.

The **gadget wheel** works the same on the off hand (left stick click; Index:
rest your thumb on the left trackpad): portable medkit, steroids, HoloDuke,
jetpack and night vision goggles with their charge; picking one uses or toggles
it through the normal inventory keys. Scuba gear and boots work by themselves.

`EDUKE32_XR_WEAPON_WHEEL=0` disables both. Without VR models the weapon wheel
shows the pickup sprites, on the ring in front of you rather than on the HUD.
Verified with `tools/vr/smoke_xr_wheel.py` and `tools/vr/scenes/wheels.json`.

## Voice chat (multiplayer)

Built in when libopus is available. In VR your microphone transmits by voice
activation as soon as you join a game (`voice_transmit 2`, the default, means
on in VR, off on desktop); the HUD shows `MIC READY` / `MIC LIVE` and
`> name` for whoever is talking. Other players' voices come from where they
are: louder and panned when near, fading to a centred "radio" level beyond
`voice_spatial_distance` (about 24 m), following your head in VR.

Everything below is in **Options > Sound Setup > Voice Chat Setup** (also linked from VR Setup):
- voice chat on/off and microphone off/on/auto;
- **Input device**: system default or any recording device, switched immediately;
- **Transmit**: voice activation or push-to-talk.
- **Push-to-talk key**: opens Key Configuration on the new **Push To Talk** action (default `V`; it is also assignable to mouse and controller buttons).
- **VR push-to-talk button**: left Y / Index left B (instead of next weapon), left X / Index left A (instead of previous weapon), or right B (instead of crouch).
- activation sensitivity, microphone and voice volumes, distant talkers;
- **Hear myself** (mic test) and the talker HUD.

A live microphone level meter at the bottom shows whether your voice opens the gate (or push-to-talk is held). It works outside a game too.

| Command / cvar | Default | |
| --- | --- | --- |
| `voice_transmit` | 2 | 0 off, 1 on, 2 auto (VR on, desktop off) |
| `voice_mode` | 0 | 0 voice activation, 1 push-to-talk (the Push_To_Talk binding; VR: `vr_ptt_button`) |
| `vr_ptt_button` | 0 | VR talk button: 0 left Y (Index left B), 1 left X (Index left A), 2 right B |
| `voice_vad_sensitivity` | 55 | 0-100 |
| `voice_input_gain` / `voice_volume` | 1 / 1 | |
| `voice_radio_volume` | 0.45 | distant talkers |
| `voice_device` | "" | recording device (`voice_devices` lists them) |
| `voice_enable`, `voice_hud` | 1 | |
| `voice_loopback` | 0 | hear yourself (mic test) |
| `voice_mute <name\|slot>`, `voice_status`, `voice_restart` | | |

Opus 24 kbps (~3 kB/s per talker) on its own unreliable channel, relayed by
the server to every other client. Opus is BSD-licensed (system library). Verified with
`tools/vr/smoke_voice.py` (test tone, relay, 440 Hz decode, head-tracked pan).

## VR bodies in multiplayer

Each VR player sends its raw tracking about 30 times a second (about 3 kB/s):
- head pose;
- each hand's grip or weapon frame and finger pose (relaxed, trigger, point, fist or the weapon's hold, with the trigger curl);
- the held 3D model and its animation frame;
- the mighty foot leg extension.

This is presentation only. It rides its own unreliable channel and the server relays it like voice.

Every client solves the other players' full IK bodies locally, using the same rig as its own body:
- arms reach the tracked wrists (stretching when needed);
- the head follows the headset;
- legs step and kick;
- hand shells grip the weapon each player is holding.

Players without a fresh pose (flat players, the dead, a stalled connection) keep the native Duke sprite. Remote bodies need a pack with the IK body (the DNF pack). Other packs show the native sprite.

On a dedicated server, the server's own player 0 is not in the game: it is invisible, never blocks, never takes shots and is never targeted.

Verified across a real network with `tools/vr/smoke_xr_remote_coop.py`. That test uses two independent simulated headsets (`software_xr_lab.py --share-net --second-runtime`) against a dedicated aarch64 server on another machine.

## Multiplayer compatibility

Only identical, current builds play together. The network protocol (NETVERSION 9) always carries the VR shot sample (hand ray and head direction) in every input update; flat clients send it inactive. It also has voice and VR body pose channels. There is no negotiation and no support for older clients or servers, which are refused at connect.

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
In remote-detonation mode the detonator replaces the bomb in the throwing hand
(native flow); its trigger detonates. Verified with
`tools/vr/smoke_xr_throw.py`.
