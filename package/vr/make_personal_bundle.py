#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Assemble a PERSONAL, ready-to-run EDuke32 VR bundle for testing on another machine you own.

    make_personal_bundle.py OUT --linux-binary eduke32-xr [--linux-amc-binary eduke32-xr-amc] --windows-dir WINDIR [--zip]

PERSONAL USE ONLY. The bundle holds your own game data (GRPs, World Tour files) and the private
Voxel Duke model pack built from your download of that mod: never upload or share it. (The
redistributable release is make_release.py, which carries no game data and no private assets.)

OUT receives:
  linux/      eduke32-vr (the VR-capable build; desktop too), eduke32-vr-amc (the AMC Squad engine
              build, used by play-game.sh when AMCSQUAD.GRP is there) and lib/ with the shared
              libraries they need beyond the system's GL/X11/ALSA/glibc
  windows/    eduke32-vr.exe, eduke32-vr-amc.exe (when built), openxr_loader.dll, libopus-0.dll
  data/       vrpacks/ (original, original-lowres and voxel model sets, ready to use; no Alien
              Armageddon files), local/duke3d/ (generated extras), grp/DUKE3D.GRP (World Tour, the
              same as the multiplayer server), worldtour/ (World Tour episode 5 maps, art, CON,
              music and sound), addons/ (Atomic 1.5 DUKE3D.GRP with Duke It Out in D.C.,
              Duke Caribbean and Nuclear Winter)
  *.sh / *.bat  play (VR or desktop), join the marmot server (VR or desktop), the expansions and
              update (portable: nothing to install)
  README.txt

Everything the scripts need is prebuilt here: the target machine needs no Python or compiler.
"""
import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SERVER = 'incidentalstoat.xyz:26555'
GITHUB_REPO = 'ObeseCatLord/EDuke-VR'   # releases the updaters download (see make_github_release.py)
WORLD_TOUR = Path('/home/obesecatlord/Windows/Steam/steamapps/common/Duke Nukem 3D Twentieth Anniversary World Tour')
ADDONS = Path.home() / '.config/eduke32'
# Bundled beside the game (the system's own SDL2, GL, X11 and ALSA are used). Build the binary with
# PORTABLE_GLIBC=1 LTO=0: with these libraries it then needs glibc 2.38 and GCC 13's libstdc++.
LINUX_LIBS = ('libopenxr_loader.so.1', 'libopus.so.0', 'libvpx.so.12', 'libFLAC.so.14', 'libogg.so.0',
              'libjsoncpp.so.27', 'libatomic.so.1')
WINDOWS_FILES = ('eduke32-vr.exe', 'openxr_loader.dll', 'libopus-0.dll')
WINDOWS_OPTIONAL_FILES = ('eduke32-vr-amc.exe',)   # AMC Squad's own engine build
PACKS = ('original', 'original-lowres', 'voxel')
AA_FILES = ('hand-rig-aa.txt', 'hud-model-map-aa.txt')

# ---------------------------------------------------------------- scripts (Linux)
SH_COMMON = r'''#!/usr/bin/env bash
# EDuke32 VR personal bundle. VR needs an OpenXR runtime (Monado/Envision, WiVRn or SteamVR).
set -euo pipefail
here=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
data="$here/data"
# @JOIN_DEFAULT@
exe=eduke32-vr   # play-game.sh may switch to eduke32-vr-amc; an exported "exe" must not leak in
# x86_64 PCs use linux/, 64-bit ARM (Steam Frame, other arm64 Linux) linux-arm64/.
case $(uname -m) in aarch64|arm64) bin="$here/linux-arm64" ;; *) bin="$here/linux" ;; esac
[[ -x $bin/eduke32-vr ]] || { echo "EDuke VR: no build for $(uname -m) here ($bin)" >&2; exit 1; }
export LD_LIBRARY_PATH="$bin/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
# The bundled GRP when there is one; otherwise EDuke32 finds an installed copy (Steam, GOG...).
grp=(); [[ -f $data/grp/DUKE3D.GRP ]] && grp=(-j "$data/grp" -gamegrp DUKE3D.GRP)
# Voxel Duke (Duke's 3D full body, hands and weapons): built once on this machine from your copy of
# Voxel Duke Nukem 3D, voxel_duke3d.zip, put next to play.sh, in data/ or in ~/Downloads. A release
# carries the builder (voxelbuilder/); EDUKE32_VR_VOXEL_BUILD=0 skips it.
voxel_build() {
    local builder="$here/voxelbuilder/package/vr/build_voxel_pack.py" packs="$data/vrpacks" zip="" c want have="" stamp
    [[ -f $builder && ${EDUKE32_VR_VOXEL_BUILD:-1} != 0 && ! -d $packs/voxel ]] || return 0
    for c in "$here/voxel_duke3d.zip" "$data/voxel_duke3d.zip" "$HOME/Downloads/voxel_duke3d.zip"; do
        [[ -f $c ]] && { zip=$c; break; }
    done
    [[ -n $zip ]] || return 0
    command -v python3 >/dev/null \
        || { echo "EDuke VR: install Python 3 with numpy, scipy and Pillow to build Voxel Duke from $zip" >&2; return 0; }
    want=$(python3 "$builder" --version) || return 0
    # Missing modules are not a failed build: it runs once they are installed.
    python3 -c 'import numpy, scipy, PIL' 2>/dev/null \
        || { echo "EDuke VR: to build Voxel Duke from $zip, install numpy, scipy and Pillow for Python 3 (pip install numpy scipy pillow)" >&2; return 0; }
    [[ -f $packs/voxel.built ]] && have=$(cat "$packs/voxel.built")
    [[ $have == "$want" && -f $packs/voxel.zip ]] && return 0
    stamp="$want $(stat -c %s "$zip")"
    [[ -f $packs/voxel.failed && $(cat "$packs/voxel.failed") == "$stamp" ]] && return 0
    mkdir -p "$packs"
    echo "EDuke VR: building Voxel Duke from $zip (once, about half an hour)..." >&2
    command -v notify-send >/dev/null && notify-send "EDuke VR" "Building Voxel Duke (once, about half an hour); the game starts after." || true
    if python3 "$builder" "$zip" --assets "$here/voxelbuilder/duke-vr-assets" --out "$packs" --zip >&2; then
        echo "$want" > "$packs/voxel.built"; rm -f "$packs/voxel.failed"
    else
        echo "$stamp" > "$packs/voxel.failed"
        echo "EDuke VR: the Voxel Duke build failed (above); playing without it. It is tried again when the zip or the builder changes." >&2
    fi
}
run() {   # run MODE(vr|desktop) [game arguments...]
    local mode=$1; shift
    # Another EDuke32 game (play-game.sh) uses its own art: no Duke model sets or Duke mods.
    [[ -n ${other_game:-} ]] || voxel_build
    if [[ $mode == vr ]]; then
        export EDUKE32_XR="${EDUKE32_XR:-play}" SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-x11}"
        export __GL_SYNC_TO_VBLANK=0 __GL_THREADED_OPTIMIZATIONS=0 mesa_glthread=false
    else
        unset EDUKE32_XR
    fi
    restart=$(mktemp -t eduke32-vr-restart.XXXXXX)   # global: the EXIT trap runs after run() returned
    trap 'rm -f "$restart"' EXIT
    export EDUKE32_XR_RESTART_REQUEST="$restart"
    local pack=() mods=() local_data=() status
    # Personal bundles carry data/local/duke3d (the money wad cut from your GRP); releases do not.
    [[ -f $data/local/duke3d/vr-local.def ]] && local_data=(-j "$data/local/duke3d" -mh vr-local.def)
    # Hit Feedback mod (extra blood and sparks on hits): EDUKE32_VR_HITFEEDBACK=0 leaves it out.
    [[ ${EDUKE32_VR_HITFEEDBACK:-1} != 0 && -f $data/mods/hitfeedback/hitfeedback.con ]] \
        && mods=(-j "$data/mods/hitfeedback" -mx hitfeedback.con)
    [[ -n ${other_game:-} ]] && { mods=(); local_data=(); pack=(-vrpack none); }
    while :; do
        : > "$restart"; status=0
        "$bin/$exe" -j "$data" "${local_data[@]}" "${mods[@]}" "${pack[@]}" -nosetup "$@" || status=$?
        [[ -s $restart ]] || return "$status"
        pack=(-vrpack "$(head -n1 "$restart")")   # the VR Setup menu switched model sets
    done
}
'''

def copy_games(dest):
    """VR profiles of the other EDuke32 games play-game supports (package/vr/games/NAME/)."""
    for game in sorted((HERE / 'games').iterdir()):
        if game.is_dir():
            shutil.copytree(game, dest / game.name)


def copy_mods(dest):
    """The gameplay mods shipped with the game (package/vr/mods/NAME/), loaded by play/join."""
    for mod in sorted((HERE / 'mods').iterdir()):
        if mod.is_dir():
            shutil.copytree(mod, dest / mod.name)


def sh_script(body):
    return SH_COMMON + body

SH_PLAY = sh_script(r'''# ./play.sh [vr|desktop] [extra EDuke32 arguments]   (default: vr)
mode=${1:-vr}; [[ $# -gt 0 ]] && shift
run "$mode" "${grp[@]}" "$@"
''')
SH_GAME = sh_script(r'''# ./play-game.sh GAME_FOLDER [vr|desktop]   another EDuke32 game you own, from its install folder:
#   Ion Fury (fury.grp), Demon Throne (WGR2.grp), AMC Squad (AMCSQUAD.GRP) or A.W.O.L. (awol.grp). Its own HUD, menus and
#   art; VR weapon and gadget wheels from data/games/. AMC Squad runs on its own engine build
#   (linux/eduke32-vr-amc) from its folder, where it keeps savegames and progress: use a writable copy.
dir=${1:?usage: play-game.sh GAME_FOLDER [vr|desktop]}; mode=${2:-vr}; shift $(( $# >= 2 ? 2 : 1 ))
dir=$(cd "$dir" && pwd)
found=""
for name in fury.grp WGR2.grp AMCSQUAD.GRP awol.grp; do
    found=$(find "$dir" -maxdepth 1 -iname "$name" -print -quit)
    [[ -n $found ]] && break
done
case "$(basename "${found:-none}" | tr '[:upper:]' '[:lower:]')" in
    fury.grp) game=(-j "$dir" -j "$data/games/fury") ;;
    wgr2.grp) game=(-j "$dir" -j "$dir/WGR2" -j "$data/games/demonthrone") ;;   # its scripts include from WGR2/
    awol.grp) game=(-j "$dir" -j "$data/games/awol") ;;
    amcsquad.grp)
        [[ -x $bin/eduke32-vr-amc ]] || { echo "play-game: this bundle has no AMC Squad engine build ($bin/eduke32-vr-amc)" >&2; exit 1; }
        exe=eduke32-vr-amc; game=(-j "$dir" -j "$data/games/amc"); [[ -f $data/games/amc/amc_vr_fixes.con ]] && game+=(-mx amc_vr_fixes.con); cd "$dir" ;;
    *) echo "play-game: no supported game in $dir (Ion Fury: fury.grp, Demon Throne: WGR2.grp, AMC Squad: AMCSQUAD.GRP, A.W.O.L.: awol.grp)" >&2; exit 2 ;;
esac
other_game=1
run "$mode" "${game[@]}" -gamegrp "$(basename "$found")" "$@"
''')
SH_JOIN_ANY = sh_script(r'''# ./join.sh HOST[:PORT] [vr|desktop]   join a multiplayer server (default port 23513)
server=${1:?usage: join.sh HOST[:PORT] [vr|desktop]}; mode=${2:-vr}; shift $(( $# >= 2 ? 2 : 1 ))
run "$mode" "${grp[@]}" -connect "$server" "$@"
''')
SH_JOIN = sh_script(r'''# Join the marmot (foundry) Duke server in MODE. Same game data as the server: the World Tour GRP.
run "{mode}" "${grp[@]}" -connect {server} "$@"
''')
SH_EXPANSION = sh_script(r'''# ./play-expansion.sh NAME [vr|desktop]   NAME: worldtour (episode 5), dc, caribbean, nuclearwinter
name=${1:?worldtour, dc, caribbean or nuclearwinter}; mode=${2:-vr}; shift $(( $# >= 2 ? 2 : 1 ))
case $name in
    worldtour)     run "$mode" -j "$data/grp" -j "$data/worldtour" -j "$data/worldtour/maps" -gamegrp DUKE3D.GRP -v5 -l1 "$@" ;;
    dc)            run "$mode" -j "$data/addons" -gamegrp DUKE3D.GRP -grp dukedc.grp "$@" ;;
    caribbean)     run "$mode" -j "$data/addons" -gamegrp DUKE3D.GRP -grp vacation.grp "$@" ;;
    nuclearwinter) run "$mode" -j "$data/addons" -gamegrp DUKE3D.GRP -grp nwinter.grp -x NWINTER.CON "$@" ;;
    *) echo "play-expansion: unknown expansion $name" >&2; exit 2 ;;
esac
''')
SH_UPDATE = r'''#!/usr/bin/env bash
# ./update.sh              update to the latest Linux release on GitHub (github.com/@REPO@):
#                          a vX.Y.Z release for every platform, or (older) tags vX.Y.Z-linux on
#                          x86_64 and vX.Y.Z-linux-arm64 on 64-bit ARM (Steam Frame)
# ./update.sh FILE.tar.gz  update from a downloaded release (or personal bundle) archive
# ./update.sh --force      reinstall the latest release even when it is the installed version
# Only files the release carries are replaced: game data, the Voxel Duke pack, extras, settings and
# saved games stay.
{   # (braces: bash reads the whole script before running it, as the update replaces this file)
set -euo pipefail
here=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
repo=@REPO@
current=$(cat "$here/VERSION" 2>/dev/null || echo none)
case $(uname -m) in
    aarch64|arm64) suffix=-linux-arm64 file=-linux-arm64.tar.gz dir=linux-arm64 ;;
    *)             suffix=-linux file=-linux-x86_64.tar.gz dir=linux ;;
esac
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
if [[ $# -gt 0 && $1 != --force ]]; then
    archive=$1
else
    # Releases come newest first. Take the first release for this machine: a tag ending in $suffix (or a
    # plain vX.Y.Z release for every platform), not a
    # pre-release, with this machine's archive. Each release lists tag_name, then prerelease, then its
    # assets' download URLs, so one pass over those fields in order finds it.
    api=$(curl -fsSL -H 'Accept: application/vnd.github+json' "https://api.github.com/repos/$repo/releases?per_page=100") \
        || { echo "update: cannot reach GitHub (github.com/$repo)" >&2; exit 1; }
    url= tag= release= pre=
    while IFS= read -r field; do
        value=${field#*:}; value=${value#"${value%%[![:space:]]*}"}; value=${value//\"/}
        case $field in
            '"tag_name"'*) release=$value pre= ;;
            '"prerelease"'*) pre=$value ;;
            '"browser_download_url"'*)
                if [[ ($release == *"$suffix" || $release =~ ^v[0-9.]+$) && $pre == false && $value == *"$file" ]]; then
                    url=$value tag=${release%"$suffix"}; break
                fi ;;
        esac
    done < <(grep -oE '"(tag_name|prerelease|browser_download_url)": *("[^"]*"|true|false)' <<<"$api")
    [[ -n $url ]] || { echo "update: no ${suffix#-} release found on github.com/$repo" >&2; exit 1; }
    if [[ $tag == "$current" && ${1:-} != --force ]]; then echo "EDuke VR is up to date ($tag)."; exit 0; fi
    echo "Updating EDuke VR $current -> $tag"
    archive="$tmp/release.tar.gz"
    curl -fL --progress-bar -o "$archive" "$url"
fi
mkdir "$tmp/x"
tar -xzf "$archive" -C "$tmp/x"
new=$(find "$tmp/x" -maxdepth 2 -name play.sh -printf '%h\n' -quit)
[[ -n $new && -x $new/$dir/eduke32-vr ]] || { echo "update: $archive is not an EDuke VR archive for $(uname -m)" >&2; exit 1; }
# Each file is copied in beside its old copy and renamed over it: a running game's executable and
# libraries are replaced too (they stay valid for the running game). VERSION is written last, so an
# update that fails part way is retried in full next time.
(cd "$new" && find . -type d -print0) | while IFS= read -r -d '' d; do mkdir -p "$here/$d"; done
while IFS= read -r -d '' f; do
    [[ $f == ./VERSION ]] && continue
    cp -a "$new/$f" "$here/$f.update-new" && mv -f "$here/$f.update-new" "$here/$f" \
        || { rm -f "$here/$f.update-new"; echo "update: could not replace $f" >&2; exit 1; }
done < <(cd "$new" && find . \( -type f -o -type l \) -print0)
rm -f "$here/install.sh" "$here/install.ps1"   # older versions had an installer; the game is portable
cp -a "$new/VERSION" "$here/VERSION"
echo "EDuke VR is now $(cat "$here/VERSION" 2>/dev/null || echo updated)."
exit 0
}
'''

# ---------------------------------------------------------------- scripts (Windows)
BAT_COMMON = r'''@echo off
rem Paths are set before delayed expansion is on (a "!" in the folder name would be eaten) and used
rem as !VAR! after (values expanded that way are not parsed again).
setlocal DisableDelayedExpansion
rem EDuke32 VR personal bundle. VR needs an OpenXR runtime (SteamVR, Oculus, WMR, Virtual Desktop...).
set "HERE=%~dp0"
set "DATA=%~dp0data"
set "EXE=%~dp0windows\eduke32-vr.exe"
rem @JOIN_DEFAULT@
rem One request file per game started (two games on one PC must not share it).
set "EDUKE32_XR_RESTART_REQUEST=%TEMP%\eduke32-vr-restart-%RANDOM%%RANDOM%.txt"
setlocal EnableDelayedExpansion
rem The bundled GRP when there is one; otherwise EDuke32 finds an installed copy (Steam, GOG...).
set GRP=
if exist "!DATA!\grp\DUKE3D.GRP" set GRP=-j "!DATA!\grp" -gamegrp DUKE3D.GRP
'''
BAT_RUN = r'''
rem :run MODE args...  (MODE vr or desktop). Paths go in XARGS, not through CALL (it drops a "!").
:run
set "MODE=%~1"
shift
set "ARGS="
:collect
if "%~1"=="" goto collected
set "ARGS=!ARGS! "%~1""
shift
goto collect
:collected
if not defined OTHERGAME call :voxel
if /i "%MODE%"=="vr" (set "EDUKE32_XR=play") else (set "EDUKE32_XR=")
rem Hit Feedback mod (extra blood and sparks on hits): set EDUKE32_VR_HITFEEDBACK=0 to leave it out.
set "MODS="
if not "%EDUKE32_VR_HITFEEDBACK%"=="0" if exist "!DATA!\mods\hitfeedback\hitfeedback.con" set MODS=-j "!DATA!\mods\hitfeedback" -mx hitfeedback.con
rem Personal bundles carry data\local\duke3d (the money wad cut from your GRP); releases do not.
set "LOCALDATA="
if exist "!DATA!\local\duke3d\vr-local.def" set LOCALDATA=-j "!DATA!\local\duke3d" -mh vr-local.def
set "PACK="
rem Another EDuke32 game (play-game.bat) uses its own art: no Duke model sets or Duke mods.
if defined OTHERGAME (
    set "MODS="
    set "LOCALDATA="
    set "PACK=-vrpack none"
)
:again
type nul > "!EDUKE32_XR_RESTART_REQUEST!"
"!EXE!" -j "!DATA!" !LOCALDATA! !MODS! !PACK! -nosetup !XARGS! !ARGS!
for %%F in ("!EDUKE32_XR_RESTART_REQUEST!") do if %%~zF GTR 0 (
    set /p NEXT=<"!EDUKE32_XR_RESTART_REQUEST!"
    set "PACK=-vrpack !NEXT!"
    goto again
)
del "!EDUKE32_XR_RESTART_REQUEST!" 2>nul
exit /b

rem Voxel Duke (Duke's 3D full body, hands and weapons): built once on this machine from your copy of
rem Voxel Duke Nukem 3D, voxel_duke3d.zip, put next to play.bat, in data\ or in Downloads. Needs Python 3
rem with numpy, scipy and Pillow. A release carries the builder (voxelbuilder\); EDUKE32_VR_VOXEL_BUILD=0 skips it.
:voxel
set "VB=!HERE!voxelbuilder\package\vr\build_voxel_pack.py"
set "VP=!DATA!\vrpacks"
if not exist "!VB!" exit /b 0
if "%EDUKE32_VR_VOXEL_BUILD%"=="0" exit /b 0
if exist "!VP!\voxel\" exit /b 0
set "VZ="
for %%Z in ("!HERE!voxel_duke3d.zip" "!DATA!\voxel_duke3d.zip" "!USERPROFILE!\Downloads\voxel_duke3d.zip") do if not defined VZ if exist "%%~Z" set "VZ=%%~Z"
if not defined VZ exit /b 0
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
    echo EDuke VR: install Python 3 with numpy, scipy and Pillow to build Voxel Duke from !VZ!
    exit /b 0
)
rem Missing modules are not a failed build: it runs once they are installed.
!PY! -c "import numpy, scipy, PIL" >nul 2>nul
if errorlevel 1 (
    echo EDuke VR: to build Voxel Duke from !VZ!, install numpy, scipy and Pillow for Python 3: pip install numpy scipy pillow
    exit /b 0
)
set "WANT="
for /f "delims=" %%V in ('!PY! "!VB!" --version 2^>nul') do set "WANT=%%V"
if not defined WANT exit /b 0
set "HAVE="
if exist "!VP!\voxel.built" set /p HAVE=<"!VP!\voxel.built"
if "!HAVE!"=="!WANT!" if exist "!VP!\voxel.zip" exit /b 0
for %%Z in ("!VZ!") do set "STAMP=!WANT! %%~zZ"
set "FAILED="
if exist "!VP!\voxel.failed" set /p FAILED=<"!VP!\voxel.failed"
if "!FAILED!"=="!STAMP!" exit /b 0
if not exist "!VP!" mkdir "!VP!"
echo EDuke VR: building Voxel Duke from !VZ!, once, about half an hour...
!PY! "!VB!" "!VZ!" --assets "!HERE!voxelbuilder\duke-vr-assets" --out "!VP!" --zip
if errorlevel 1 goto voxelfailed
>"!VP!\voxel.built" echo !WANT!
if exist "!VP!\voxel.failed" del "!VP!\voxel.failed"
exit /b 0
:voxelfailed
>"!VP!\voxel.failed" echo !STAMP!
echo EDuke VR: the Voxel Duke build failed, see above; playing without it. It is tried again when the zip or the builder changes.
exit /b 0
'''

def bat(body):
    return BAT_COMMON + body + '\nexit /b\n' + BAT_RUN

BAT_PLAY = bat(r'''rem play.bat [vr|desktop] [extra EDuke32 arguments]   (default vr)
set "M=%~1"
if "%M%"=="" set "M=vr"
shift
set "REST="
:rest
if "%~1"=="" goto restdone
set REST=!REST! "%~1"
shift
goto rest
:restdone
set "XARGS=!GRP!"
call :run %M% !REST!
''')
BAT_GAME = bat(r'''rem play-game.bat GAME_FOLDER [vr|desktop]   another EDuke32 game you own, from its install folder:
rem   Ion Fury (fury.grp), Demon Throne (WGR2.grp), AMC Squad (AMCSQUAD.GRP) or A.W.O.L. (awol.grp). Its own HUD, menus and art;
rem   VR weapon and gadget wheels from data\games\. AMC Squad runs on its own engine build
rem   (windows\eduke32-vr-amc.exe) from its folder, where it keeps savegames and progress: use a writable copy.
set "G=%~1"
set "M=%~2"
if "%M%"=="" set "M=vr"
if "!G!"=="" (echo usage: play-game.bat GAME_FOLDER [vr^|desktop] & exit /b 2)
for %%i in ("!G!") do set "G=%%~fi"
set "XARGS="
if exist "!G!\fury.grp" set XARGS=-j "!G!" -j "!DATA!\games\fury" -gamegrp fury.grp
if exist "!G!\WGR2.grp" set XARGS=-j "!G!" -j "!G!\WGR2" -j "!DATA!\games\demonthrone" -gamegrp WGR2.grp
if exist "!G!\awol.grp" set XARGS=-j "!G!" -j "!DATA!\games\awol" -gamegrp awol.grp
if exist "!G!\AMCSQUAD.GRP" (
    if not exist "!HERE!windows\eduke32-vr-amc.exe" (echo play-game: this bundle has no AMC Squad engine build ^(windows\eduke32-vr-amc.exe^) & exit /b 1)
    set XARGS=-j "!G!" -j "!DATA!\games\amc" -gamegrp AMCSQUAD.GRP
    if exist "!DATA!\games\amc\amc_vr_fixes.con" set XARGS=!XARGS! -mx amc_vr_fixes.con
    set "EXE=!HERE!windows\eduke32-vr-amc.exe"
    cd /d "!G!"
)
if not defined XARGS (echo play-game: no supported game in !G! ^(Ion Fury: fury.grp, Demon Throne: WGR2.grp, AMC Squad: AMCSQUAD.GRP, A.W.O.L.: awol.grp^) & exit /b 2)
set "OTHERGAME=1"
call :run %M%
''')
BAT_JOIN_ANY = bat(r'''rem join.bat HOST[:PORT] [vr|desktop]   join a multiplayer server (default port 23513)
set "S=%~1"
set "M=%~2"
if "%S%"=="" (echo usage: join.bat HOST[:PORT] [vr^|desktop] & exit /b 2)
if "%M%"=="" set "M=vr"
set "XARGS=!GRP! -connect %S%"
call :run %M%
''')
BAT_JOIN = bat(r'''rem Join the marmot (foundry) Duke server ({mode}). Same game data as the server: the World Tour GRP.
set "XARGS=!GRP! -connect {server}"
call :run {mode}
''')
BAT_EXPANSION = bat(r'''rem play-expansion.bat NAME [vr|desktop]   NAME: worldtour (episode 5), dc, caribbean, nuclearwinter
set "N=%~1"
set "M=%~2"
if "%M%"=="" set "M=vr"
set "XARGS="
if /i "%N%"=="worldtour" set XARGS=-j "!DATA!\grp" -j "!DATA!\worldtour" -j "!DATA!\worldtour\maps" -gamegrp DUKE3D.GRP -v5 -l1
if /i "%N%"=="dc" set XARGS=-j "!DATA!\addons" -gamegrp DUKE3D.GRP -grp dukedc.grp
if /i "%N%"=="caribbean" set XARGS=-j "!DATA!\addons" -gamegrp DUKE3D.GRP -grp vacation.grp
if /i "%N%"=="nuclearwinter" set XARGS=-j "!DATA!\addons" -gamegrp DUKE3D.GRP -grp nwinter.grp -x NWINTER.CON
if not defined XARGS (echo play-expansion: unknown expansion %N% & exit /b 2)
call :run %M%
''')
PS_UPDATE = r'''# update.ps1              update to the latest Windows release on GitHub (github.com/@REPO@,
#                         a vX.Y.Z release for every platform, or (older) a vX.Y.Z-windows one)
# update.ps1 FILE.zip     update from a downloaded release (or personal bundle) archive
# update.ps1 -Force       reinstall the latest release even when it is the installed version
# Run:  powershell -ExecutionPolicy Bypass -File update.ps1
# Only files the release carries are replaced: game data, the Voxel Duke pack, extras, settings and
# saved games stay.
param([string]$Archive = '', [switch]$Force)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = '@REPO@'
$current = if (Test-Path "$here\VERSION") { (Get-Content "$here\VERSION" -Raw).Trim() } else { 'none' }
$tmp = Join-Path $env:TEMP ('eduke-vr-update-' + [guid]::NewGuid())
New-Item -ItemType Directory $tmp | Out-Null
try {
    if (-not $Archive) {
        $headers = @{ 'User-Agent' = 'EDuke-VR-updater'; 'Accept' = 'application/vnd.github+json' }
        # Releases come newest first; take the first one with the Windows download.
        $releases = Invoke-RestMethod -UseBasicParsing -Headers $headers "https://api.github.com/repos/$repo/releases?per_page=100"
        $asset = $null; $tag = $null
        # Windows releases (a tag ending in -windows, or a plain vX.Y.Z one for every platform), not
        # pre-releases, with the Windows archive.
        foreach ($r in $releases) {
            if ($r.draft -or $r.prerelease -or ($r.tag_name -notlike '*-windows' -and $r.tag_name -notmatch '^v[0-9.]+$')) { continue }
            $a = $r.assets | Where-Object { $_.name -like '*-windows-x64.zip' } | Select-Object -First 1
            if ($a) { $asset = $a; $tag = $r.tag_name -replace '-windows$', ''; break }
        }
        if (-not $asset) { throw 'No Windows release found.' }
        if ($tag -eq $current -and -not $Force) { Write-Host "EDuke VR is up to date ($current)."; return }
        Write-Host "Updating EDuke VR $current -> $tag"
        $Archive = Join-Path $tmp 'release.zip'
        Invoke-WebRequest -UseBasicParsing -Headers @{ 'User-Agent' = 'EDuke-VR-updater' } $asset.browser_download_url -OutFile $Archive
    }
    Expand-Archive -Path $Archive -DestinationPath "$tmp\x"
    $new = Get-ChildItem "$tmp\x" -Recurse -Filter play.bat | Select-Object -First 1
    if (-not $new -or -not (Test-Path (Join-Path $new.DirectoryName 'windows\eduke32-vr.exe'))) { throw "$Archive is not an EDuke VR archive" }
    # VERSION last, so an update that fails part way is retried in full next time.
    robocopy $new.DirectoryName $here /E /IS /IT /XF VERSION /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Copying the update failed (robocopy exit $LASTEXITCODE). Close EDuke VR and run the update again." }
    # Older versions had an installer; the game is portable.
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $here 'install.ps1'), (Join-Path $here 'install.sh')
    Copy-Item -Force (Join-Path $new.DirectoryName 'VERSION') (Join-Path $here 'VERSION')
    Write-Host ('EDuke VR is now ' + (Get-Content "$here\VERSION" -Raw).Trim() + '.')
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
'''

README = '''EDuke32 VR - personal test bundle ({stamp})
PERSONAL USE ONLY: contains your own game data and the private Voxel Duke pack. Do not share.

Linux:   ./play.sh vr | ./play.sh desktop   (portable: run from this folder, nothing to install)
         ./join-marmot-vr.sh | ./join-marmot-desktop.sh            (server {server})
         ./play-expansion.sh worldtour|dc|caribbean|nuclearwinter [vr|desktop]
         Needs an OpenXR runtime for VR (Monado/Envision, WiVRn, SteamVR) and a recent glibc
         (2.38+: Ubuntu 24.04, Debian 13, Fedora 39, Arch...) and SDL2 (installed with Steam);
         the OpenXR loader, Opus etc. are in linux/lib. 64-bit ARM (Steam Frame on SteamOS):
         the same scripts use linux-arm64/ when it is in the bundle.
Windows: play.bat vr | play.bat desktop, join-marmot-vr.bat, join-marmot-desktop.bat,
         play-expansion.bat worldtour|dc|caribbean|nuclearwinter [vr|desktop]
         VR needs an OpenXR runtime (SteamVR, Oculus, WMR, Virtual Desktop/VDXR...).
Update:  ./update.sh  /  powershell -ExecutionPolicy Bypass -File update.ps1
         (downloads the latest release from github.com/@REPO@ and lays it over this
         bundle: your game data, the Voxel Duke pack, settings and saves stay)

Model sets: Voxel Duke (default), original, original-lowres; switch in Options > VR Setup.
Multiplayer joins use the World Tour GRP like the server; voice chat is on in VR (Options > Sound).
Version {version}, built from commit {commit}.
'''


def copy_linux_build(binary, dest, amc_binary=None):
    """The game as linux/eduke32-vr (and the AMC Squad engine build as eduke32-vr-amc, when given) plus
    lib/ with the shared libraries it needs beyond the system's SDL2/GL/X11/ALSA/glibc."""
    (dest / 'lib').mkdir(parents=True)
    shutil.copy2(binary, dest / 'eduke32-vr')
    if amc_binary:
        shutil.copy2(amc_binary, dest / 'eduke32-vr-amc')
        # Same libraries as the normal build (libvpx for its 67 IVF cutscenes): check it links them too.
        amc_ldd = subprocess.run(['ldd', str(amc_binary)], capture_output=True, text=True, check=True).stdout
        for lib in ('libvpx.so.12', 'libopenxr_loader.so.1'):
            if lib not in amc_ldd:
                raise SystemExit(f'copy_linux_build: {amc_binary} does not link {lib}')
    ldd = subprocess.run(['ldd', str(binary)], capture_output=True, text=True, check=True).stdout
    copied = set()
    for line in ldd.splitlines():
        parts = line.split()
        if parts and parts[0] in LINUX_LIBS and '=>' in parts:
            shutil.copy2(Path(parts[2]).resolve(), dest / 'lib' / parts[0])
            copied.add(parts[0])
    # A library whose soname changed on the build host (an update to libvpx...) was silently left
    # out, and the THIRD-PARTY list names these sonames.
    missing = sorted(set(LINUX_LIBS) - copied)
    if missing:
        raise SystemExit(f'copy_linux_build: {binary} does not link {", ".join(missing)} (soname changed?); '
                         'update LINUX_LIBS and the THIRD-PARTY list')


def amc_binary_or_none(path):
    if path and path.is_file():
        return path
    print(f'make_personal_bundle: {path} not found, AMC Squad will not run from this bundle', file=sys.stderr)
    return None


def copy_windows_build(windir, dest):
    dest.mkdir(parents=True)
    for name in WINDOWS_FILES:
        shutil.copy2(windir / name, dest / name)
    for name in WINDOWS_OPTIONAL_FILES:
        if (windir / name).is_file():
            shutil.copy2(windir / name, dest / name)
        else:
            print(f'copy_windows_build: {windir / name} not found, AMC Squad will not run from this bundle', file=sys.stderr)


def copy_pack(src, dst):
    """A model set as real files (the local packs are symlink farms), without Alien Armageddon files."""
    for path in sorted(src.rglob('*')):
        rel = path.relative_to(src)
        if path.name.startswith('vr_aa_') or path.name in AA_FILES or path.is_dir():
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path.resolve(), target)


# Personal bundles offer their server in Join Server (until the player has joined one); releases
# leave the marker as a comment.
JOIN_DEFAULT = {'sh': 'export EDUKE32_VR_JOIN_DEFAULT="${EDUKE32_VR_JOIN_DEFAULT:-' + SERVER + '}"   # Join Server\'s server until another is joined',
                'bat': 'if not defined EDUKE32_VR_JOIN_DEFAULT set "EDUKE32_VR_JOIN_DEFAULT=' + SERVER + '"'}
JOIN_DEFAULT_ON = False   # set by main() for a personal bundle


def write(path, text, executable=False, crlf=False):
    text = text.replace('@REPO@', GITHUB_REPO)
    if JOIN_DEFAULT_ON:
        text = text.replace('# @JOIN_DEFAULT@', JOIN_DEFAULT['sh']).replace('rem @JOIN_DEFAULT@', JOIN_DEFAULT['bat'])
    path.write_text(text.replace('\n', '\r\n') if crlf else text, newline='')
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('out', type=Path)
    parser.add_argument('--linux-binary', type=Path, default=REPO / 'eduke32-xr')
    parser.add_argument('--linux-amc-binary', type=Path, default=REPO / 'eduke32-xr-amc', help='the AMC Squad engine build (skipped, with a warning, when missing)')
    parser.add_argument('--windows-dir', type=Path, required=True, help='eduke32-vr.exe, openxr_loader.dll, libopus-0.dll')
    parser.add_argument('--packs', type=Path, default=Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'eduke32-vr/vrpacks')
    parser.add_argument('--world-tour', type=Path, default=WORLD_TOUR)
    parser.add_argument('--addons', type=Path, default=ADDONS, help='folder with the Atomic DUKE3D.GRP and dukedc/vacation/nwinter.grp')
    parser.add_argument('--zip', action='store_true', help='also write OUT.tar.gz (Linux) and OUT.zip (Windows)')
    parser.add_argument('--linux-arm64-dir', type=Path, help='prebuilt 64-bit ARM build: eduke32-vr and lib/ (package/vr/build_linux_arm64.sh)')
    parser.add_argument('--version', required=True, help='the GitHub release this bundle matches (VERSION, for update.sh/ps1)')
    args = parser.parse_args()
    global JOIN_DEFAULT_ON
    JOIN_DEFAULT_ON = True
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        sys.exit(f'make_personal_bundle: {out} is not empty')
    data = out / 'data'

    # Builds.
    amc = amc_binary_or_none(args.linux_amc_binary)
    copy_linux_build(args.linux_binary, out / 'linux', amc)
    if args.linux_arm64_dir:
        shutil.copytree(args.linux_arm64_dir, out / 'linux-arm64', symlinks=False)
    copy_windows_build(args.windows_dir, out / 'windows')

    # Model sets, mods and generated extras.
    for pack in PACKS:
        copy_pack(args.packs / pack, data / 'vrpacks' / pack)
    copy_mods(data / 'mods')
    copy_games(data / 'games')
    local = data / 'local/duke3d'
    local.mkdir(parents=True)
    sys.path.insert(0, str(HERE))
    import money_wad
    text = '// Generated by make_personal_bundle.py: local extras (not a model pack).\n'
    if money_wad.build([str(args.world_tour / 'DUKE3D.GRP')], local):
        text += ('model "vr_money.md3" {\n scale 1.0\n skin { pal 0 surface 0 file "vr_money.png" }\n'
                 ' frame { name "rest" tile 30068 smoothduration 0 }\n}\n')
    (local / 'vr-local.def').write_text(text)

    # Game data: World Tour (base game, multiplayer, episode 5) and the Atomic add-ons.
    (data / 'grp').mkdir()
    shutil.copy2(args.world_tour / 'DUKE3D.GRP', data / 'grp/DUKE3D.GRP')
    wt = data / 'worldtour'
    wt.mkdir()
    for item in sorted(args.world_tour.iterdir()):
        if item.suffix.upper() in ('.ART', '.CON', '.RTS') or item.name in ('maps', 'music', 'sound'):
            (shutil.copytree if item.is_dir() else shutil.copy2)(item, wt / item.name)
    # World Tour's CON names its maps maps/E1L1.map, but episodes 1-4 ship as E1L1.MAP: Windows does
    # not mind the case, Linux could not load them (only episode 5, named .map, played).
    for item in sorted((wt / 'maps').iterdir()):
        if item.suffix == '.MAP':
            item.rename(item.with_suffix('.map'))
    (data / 'addons').mkdir()
    for name in ('DUKE3D.GRP', 'dukedc.grp', 'vacation.grp', 'nwinter.grp'):
        shutil.copy2(args.addons / name, data / 'addons' / name)

    # Scripts.
    write(out / 'play.sh', SH_PLAY, True)
    write(out / 'play-expansion.sh', SH_EXPANSION, True)
    write(out / 'play-game.sh', SH_GAME, True)
    write(out / 'play-game.bat', BAT_GAME, crlf=True)
    for mode in ('vr', 'desktop'):
        write(out / f'join-marmot-{mode}.sh', SH_JOIN.replace('{mode}', mode).replace('{server}', SERVER), True)
        write(out / f'join-marmot-{mode}.bat', BAT_JOIN.replace('{mode}', mode).replace('{server}', SERVER), crlf=True)
    write(out / 'join.sh', SH_JOIN_ANY, True)
    write(out / 'join.bat', BAT_JOIN_ANY, crlf=True)
    write(out / 'VERSION', args.version + '\n')
    write(out / 'update.sh', SH_UPDATE, True)
    write(out / 'play.bat', BAT_PLAY, crlf=True)
    write(out / 'play-expansion.bat', BAT_EXPANSION, crlf=True)
    write(out / 'update.ps1', PS_UPDATE, crlf=True)
    commit = subprocess.run(['git', '-C', str(REPO), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
    stamp = subprocess.run(['date', '+%Y-%m-%d'], capture_output=True, text=True).stdout.strip()
    write(out / 'README.txt', README.format(stamp=stamp, server=SERVER, commit=commit, version=args.version))

    result = {'out': str(out), 'linux_libs': sorted(p.name for p in (out / 'linux/lib').iterdir()),
              'packs': sorted(p.name for p in (data / 'vrpacks').iterdir()), 'commit': commit}
    if args.zip:
        subprocess.run(['tar', '-czf', f'{out}.tar.gz', '-C', str(out.parent), out.name], check=True)
        subprocess.run(['zip', '-qr', f'{out}.zip', out.name], cwd=out.parent, check=True)
        result['archives'] = [f'{out}.tar.gz', f'{out}.zip']
    print(json.dumps(result, indent=1))


if __name__ == '__main__':
    main()
