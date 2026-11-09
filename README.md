<p align="center">
  <img src="docs/media/mirror-rpg.gif" alt="Looking at Duke in a mirror, then firing the RPG in VR" width="320">
  <img src="docs/media/coop.gif" alt="Playing co-op in VR with another player" width="320">
</p>

<h1 align="center">EDuke VR</h1>

Duke Nukem 3D in VR, built on [EDuke32](https://www.eduke32.com/). Play the whole game in a VR
headset or on a normal screen, alone or with friends in co-op and DukeMatch.

You need your own copy of Duke Nukem 3D (for example the 20th Anniversary World Tour on Steam). No
game data is included.

**[Download the latest release](../../releases)**

## Features

- Hold and aim weapons with your hands, aim with both hands, throw pipebombs and kick with the
  mighty foot.
- A full Duke body that you and other players can see.
- Co-op and DukeMatch with voice chat. VR and desktop players can play together.
- Weapon and gadget wheels, and a wrist HUD.
- 3D models for Duke, his hands and weapons, including Voxel Duke if you have that mod.
- Snap or smooth turning and room-scale movement.
- Windows, Linux and Steam Frame.

## Installation

1. Download the archive for your system from [Releases](../../releases) and extract it.
2. Put `DUKE3D.GRP` in `data/grp/`, or let the game find your installed copy.
3. Start your VR runtime and run `play.bat vr` on Windows or `./play.sh vr` on Linux. Use
   `desktop` instead of `vr` to play without a headset.

To join a server, run `join.bat HOST` or `./join.sh HOST`. To update, run `./update.sh`, or on
Windows right-click `update.ps1` > **Run with PowerShell**. Your settings, saves and model sets are
kept.

## Co-op

Everyone in a multiplayer game, including the server, needs the same version of EDuke VR. Co-op has
no friendly fire, shared keycards and name tags over other players by default. Turn friendly fire
on with `mp_friendlyfire 1` on the server.

## VR controls

| Input | Action |
| --- | --- |
| Left stick | Move |
| Right stick | Snap or smooth turn; flick down to kick |
| Right trigger | Fire; point and select in menus |
| Left trigger | Kick |
| Left grip | Use (doors, switches, buttons) |
| Right A / B | Jump / crouch (or duck for real) |
| Left X / Y | Previous / next weapon |
| Hold right stick click | Weapon wheel |
| Hold left stick click | Gadget wheel |
| Right grip | Walk |
| Menu button | Menu |

On Index controllers, rest your thumb on a trackpad for the wheels. VR options are under
**Options > VR Setup**. Everything else, including other controllers, multiplayer servers and model
sets, is in [docs/vr/PLAYING.md](docs/vr/PLAYING.md).

## Building from source

See [docs/BUILDING.md](docs/BUILDING.md).

## License

EDuke VR is a modified version of EDuke32 and uses the same licenses: the
[GNU GPL v2](package/common/gpl-2.0.txt), and Ken Silverman's
[BUILD engine license](package/common/buildlic.txt) for `source/build`, which allows non-commercial
use only, so EDuke VR may not be sold. Bundled libraries keep their own licenses, listed in each
release's `licenses/THIRD-PARTY.txt`.

Duke Nukem 3D is a trademark of Gearbox Software. This is a community project, not affiliated with
Gearbox, 3D Realms or Voidpoint.

## Credits

EDuke32 by Richard "TerminX" Gobeille, Evan "Hendricks266" Ramos and the Voidpoint team. The Build
engine by Ken Silverman. Duke Nukem 3D by 3D Realms. JFDuke3D by Jonathon Fowler.
