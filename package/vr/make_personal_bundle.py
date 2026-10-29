#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Assemble a PERSONAL, ready-to-run EDuke32 VR bundle for testing on another machine you own.

    make_personal_bundle.py OUT --linux-binary eduke32-xr --windows-dir WINDIR [--zip]

PERSONAL USE ONLY. The bundle holds your own game data (GRPs, World Tour files) and the private
Voxel Duke model pack built from your download of that mod: never upload or share it. (The
redistributable release is make_release.py, which carries no game data and no private assets.)

OUT receives:
  linux/      eduke32-vr (the VR-capable build; desktop too) and lib/ with the shared libraries
              it needs beyond the system's GL/X11/ALSA/glibc
  windows/    eduke32-vr.exe, openxr_loader.dll, libopus-0.dll
  data/       vrpacks/ (original, original-lowres and voxel model sets, ready to use; no Alien
              Armageddon files), local/duke3d/ (generated extras), grp/DUKE3D.GRP (World Tour, the
              same as the multiplayer server), worldtour/ (World Tour episode 5 maps, art, CON,
              music and sound), addons/ (Atomic 1.5 DUKE3D.GRP with Duke It Out in D.C.,
              Duke Caribbean and Nuclear Winter)
  *.sh / *.bat  play (VR or desktop), join the marmot server (VR or desktop), the expansions,
              install and update
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
PACKS = ('original', 'original-lowres', 'voxel')
AA_FILES = ('hand-rig-aa.txt', 'hud-model-map-aa.txt')

# ---------------------------------------------------------------- scripts (Linux)
SH_COMMON = r'''#!/usr/bin/env bash
# EDuke32 VR personal bundle. VR needs an OpenXR runtime (Monado/Envision, WiVRn or SteamVR).
set -euo pipefail
here=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
data="$here/data"
# x86_64 PCs use linux/, 64-bit ARM (Steam Frame, other arm64 Linux) linux-arm64/.
case $(uname -m) in aarch64|arm64) bin="$here/linux-arm64" ;; *) bin="$here/linux" ;; esac
[[ -x $bin/eduke32-vr ]] || { echo "EDuke VR: no build for $(uname -m) here ($bin)" >&2; exit 1; }
export LD_LIBRARY_PATH="$bin/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
# The bundled GRP when there is one; otherwise EDuke32 finds an installed copy (Steam, GOG...).
grp=(); [[ -f $data/grp/DUKE3D.GRP ]] && grp=(-j "$data/grp" -gamegrp DUKE3D.GRP)
run() {   # run MODE(vr|desktop) [game arguments...]
    local mode=$1; shift
    if [[ $mode == vr ]]; then
        export EDUKE32_XR="${EDUKE32_XR:-play}" SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-x11}"
        export __GL_SYNC_TO_VBLANK=0 __GL_THREADED_OPTIMIZATIONS=0 mesa_glthread=false
    else
        unset EDUKE32_XR
    fi
    local restart; restart=$(mktemp -t eduke32-vr-restart.XXXXXX)
    trap 'rm -f "$restart"' EXIT
    export EDUKE32_XR_RESTART_REQUEST="$restart"
    local pack=() status
    while :; do
        : > "$restart"; status=0
        "$bin/eduke32-vr" -j "$data" -j "$data/local/duke3d" -mh vr-local.def "${pack[@]}" -nosetup "$@" || status=$?
        [[ -s $restart ]] || return "$status"
        pack=(-vrpack "$(head -n1 "$restart")")   # the VR Setup menu switched model sets
    done
}
'''

def sh_script(body):
    return SH_COMMON + body

SH_PLAY = sh_script(r'''# ./play.sh [vr|desktop] [extra EDuke32 arguments]   (default: vr)
mode=${1:-vr}; [[ $# -gt 0 ]] && shift
run "$mode" "${grp[@]}" "$@"
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
SH_INSTALL = r'''#!/usr/bin/env bash
# Install (or update to) this bundle: copies it to ~/.local/share/eduke32-vr-bundle and adds app-menu
# entries. Settings and saved games live in ~/.config/eduke32 and are kept.
set -euo pipefail
here=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
dest="${1:-$HOME/.local/share/eduke32-vr-bundle}"
if [[ $(readlink -f "$here") != $(readlink -f "$dest" 2>/dev/null || echo none) ]]; then
    # Lay the files over any earlier install: nothing there is deleted (game data, model sets).
    mkdir -p "$dest"
    cp -a "$here/." "$dest/"
fi
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"; mkdir -p "$apps"
entry() {   # file name exec
    printf '[Desktop Entry]\nType=Application\nName=%s\nExec=%s\nTerminal=false\nCategories=Game;\n' "$2" "$3" > "$apps/$1.desktop"
}
entry eduke32-vr "Duke Nukem 3D VR" "$dest/play.sh vr"
entry eduke32-vr-desktop "Duke Nukem 3D (desktop)" "$dest/play.sh desktop"
if [[ -x $dest/join-marmot-vr.sh ]]; then
    entry eduke32-vr-marmot "Duke 3D VR - join marmot server" "$dest/join-marmot-vr.sh"
    entry eduke32-vr-marmot-desktop "Duke 3D - join marmot server (desktop)" "$dest/join-marmot-desktop.sh"
fi
echo "Installed in $dest (app menu: Duke Nukem 3D VR)."
'''
SH_UPDATE = r'''#!/usr/bin/env bash
# ./update.sh              update to the latest Linux release on GitHub (github.com/@REPO@):
#                          tags vX.Y.Z-linux on x86_64, vX.Y.Z-linux-arm64 on 64-bit ARM (Steam
#                          Frame); Windows has its own vX.Y.Z-windows releases
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
    # Releases come newest first. Take the first release for this machine: a tag ending in $suffix, not a
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
                if [[ $release == *"$suffix" && $pre == false && $value == *"$file" ]]; then
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
new=$(find "$tmp/x" -maxdepth 2 -name play.sh -printf '%h\n' | head -n1)
[[ -n $new && -x $new/$dir/eduke32-vr ]] || { echo "update: $archive is not an EDuke VR archive for $(uname -m)" >&2; exit 1; }
cp -a "$new/." "$here/"
echo "EDuke VR is now $(cat "$here/VERSION" 2>/dev/null || echo updated)."
exit 0
}
'''

# ---------------------------------------------------------------- scripts (Windows)
BAT_COMMON = r'''@echo off
setlocal EnableDelayedExpansion
rem EDuke32 VR personal bundle. VR needs an OpenXR runtime (SteamVR, Oculus, WMR, Virtual Desktop...).
set "HERE=%~dp0"
set "DATA=%HERE%data"
set "EXE=%HERE%windows\eduke32-vr.exe"
set "EDUKE32_XR_RESTART_REQUEST=%TEMP%\eduke32-vr-restart.txt"
rem The bundled GRP when there is one; otherwise EDuke32 finds an installed copy (Steam, GOG...).
set GRP=
if exist "%DATA%\grp\DUKE3D.GRP" set GRP=-j "%DATA%\grp" -gamegrp DUKE3D.GRP
'''
BAT_RUN = r'''
rem :run MODE args...  (MODE vr or desktop)
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
if /i "%MODE%"=="vr" (set "EDUKE32_XR=play") else (set "EDUKE32_XR=")
set "PACK="
:again
type nul > "%EDUKE32_XR_RESTART_REQUEST%"
"%EXE%" -j "%DATA%" -j "%DATA%\local\duke3d" -mh vr-local.def !PACK! -nosetup !ARGS!
for %%F in ("%EDUKE32_XR_RESTART_REQUEST%") do if %%~zF GTR 0 (
    set /p NEXT=<"%EDUKE32_XR_RESTART_REQUEST%"
    set "PACK=-vrpack !NEXT!"
    goto again
)
exit /b
'''

def bat(body):
    return BAT_COMMON + body + '\nexit /b\n' + BAT_RUN

BAT_PLAY = bat(r'''rem play.bat [vr|desktop]   (default vr)
set "M=%~1"
if "%M%"=="" set "M=vr"
call :run %M% %GRP%
''')
BAT_JOIN_ANY = bat(r'''rem join.bat HOST[:PORT] [vr|desktop]   join a multiplayer server (default port 23513)
set "S=%~1"
set "M=%~2"
if "%S%"=="" (echo usage: join.bat HOST[:PORT] [vr^|desktop] & exit /b 2)
if "%M%"=="" set "M=vr"
call :run %M% %GRP% -connect %S%
''')
BAT_JOIN = bat(r'''rem Join the marmot (foundry) Duke server ({mode}). Same game data as the server: the World Tour GRP.
call :run {mode} %GRP% -connect {server}
''')
BAT_EXPANSION = bat(r'''rem play-expansion.bat NAME [vr|desktop]   NAME: worldtour (episode 5), dc, caribbean, nuclearwinter
set "N=%~1"
set "M=%~2"
if "%M%"=="" set "M=vr"
if /i "%N%"=="worldtour" call :run %M% -j "%DATA%\grp" -j "%DATA%\worldtour" -j "%DATA%\worldtour\maps" -gamegrp DUKE3D.GRP -v5 -l1
if /i "%N%"=="dc" call :run %M% -j "%DATA%\addons" -gamegrp DUKE3D.GRP -grp dukedc.grp
if /i "%N%"=="caribbean" call :run %M% -j "%DATA%\addons" -gamegrp DUKE3D.GRP -grp vacation.grp
if /i "%N%"=="nuclearwinter" call :run %M% -j "%DATA%\addons" -gamegrp DUKE3D.GRP -grp nwinter.grp -x NWINTER.CON
''')
PS_INSTALL = r'''# Install (or update to) this bundle: copies it to %LOCALAPPDATA%\EDuke32-VR and adds Start menu
# shortcuts. Run:  powershell -ExecutionPolicy Bypass -File install.ps1
param([string]$Dest = "$env:LOCALAPPDATA\EDuke32-VR")
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if ((Resolve-Path $here).Path -ne $Dest) {
    New-Item -ItemType Directory -Force $Dest | Out-Null
    # Lay the files over any earlier install: nothing there is deleted (game data, model sets).
    robocopy $here $Dest /E /IS /IT /NFL /NDL /NJH /NJS /NP | Out-Null
}
$menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'EDuke32 VR'
New-Item -ItemType Directory -Force $menu | Out-Null
$shell = New-Object -ComObject WScript.Shell
$links = @(@('Duke Nukem 3D VR','play.bat','vr'), @('Duke Nukem 3D (desktop)','play.bat','desktop'))
if (Test-Path (Join-Path $Dest 'join-marmot-vr.bat')) {
    $links += ,@('Join marmot server (VR)','join-marmot-vr.bat','')
    $links += ,@('Join marmot server (desktop)','join-marmot-desktop.bat','')
}
foreach ($s in $links) {
    $l = $shell.CreateShortcut((Join-Path $menu ($s[0] + '.lnk')))
    $l.TargetPath = Join-Path $Dest $s[1]; $l.Arguments = $s[2]; $l.WorkingDirectory = $Dest
    $l.IconLocation = (Join-Path $Dest 'windows\eduke32-vr.exe'); $l.Save()
}
Write-Host "Installed in $Dest (Start menu: EDuke32 VR)."
'''
PS_UPDATE = r'''# update.ps1              update to the latest Windows release on GitHub (github.com/@REPO@,
#                         tags vX.Y.Z-windows; Linux has its own vX.Y.Z-linux releases)
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
        # Only Windows releases: a tag ending in -windows, not a pre-release, with the Windows archive.
        foreach ($r in $releases) {
            if ($r.draft -or $r.prerelease -or $r.tag_name -notlike '*-windows') { continue }
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
    robocopy $new.DirectoryName $here /E /IS /IT /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Copying the update failed (robocopy exit $LASTEXITCODE)." }
    Write-Host ('EDuke VR is now ' + (Get-Content "$here\VERSION" -Raw).Trim() + '.')
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
'''

README = '''EDuke32 VR - personal test bundle ({stamp})
PERSONAL USE ONLY: contains your own game data and the private Voxel Duke pack. Do not share.

Linux:   ./install.sh  (optional; adds app-menu entries)   then ./play.sh vr | ./play.sh desktop
         ./join-marmot-vr.sh | ./join-marmot-desktop.sh            (server {server})
         ./play-expansion.sh worldtour|dc|caribbean|nuclearwinter [vr|desktop]
         Needs an OpenXR runtime for VR (Monado/Envision, WiVRn, SteamVR) and a recent glibc
         (2.38+: Ubuntu 24.04, Debian 13, Fedora 39, Arch...) and SDL2 (installed with Steam);
         the OpenXR loader, Opus etc. are in linux/lib. 64-bit ARM (Steam Frame on SteamOS):
         the same scripts use linux-arm64/ when it is in the bundle.
Windows: install.ps1 (optional; Start menu shortcuts: right-click > Run with PowerShell)
         play.bat vr | play.bat desktop, join-marmot-vr.bat, join-marmot-desktop.bat,
         play-expansion.bat worldtour|dc|caribbean|nuclearwinter [vr|desktop]
         VR needs an OpenXR runtime (SteamVR, Oculus, WMR, Virtual Desktop/VDXR...).
Update:  ./update.sh  /  powershell -ExecutionPolicy Bypass -File update.ps1
         (downloads the latest release from github.com/@REPO@ and lays it over this
         bundle: your game data, the Voxel Duke pack, settings and saves stay)

Model sets: Voxel Duke (default), original, original-lowres; switch in Options > VR Setup.
Multiplayer joins use the World Tour GRP like the server; voice chat is on in VR (Options > Sound).
Version {version}, built from commit {commit}.
'''


def copy_linux_build(binary, dest):
    """The game as linux/eduke32-vr plus lib/ with the shared libraries it needs beyond the system's
    SDL2/GL/X11/ALSA/glibc."""
    (dest / 'lib').mkdir(parents=True)
    shutil.copy2(binary, dest / 'eduke32-vr')
    ldd = subprocess.run(['ldd', str(binary)], capture_output=True, text=True, check=True).stdout
    for line in ldd.splitlines():
        parts = line.split()
        if parts and parts[0] in LINUX_LIBS and '=>' in parts:
            shutil.copy2(Path(parts[2]).resolve(), dest / 'lib' / parts[0])


def copy_windows_build(windir, dest):
    dest.mkdir(parents=True)
    for name in WINDOWS_FILES:
        shutil.copy2(windir / name, dest / name)


def copy_pack(src, dst):
    """A model set as real files (the local packs are symlink farms), without Alien Armageddon files."""
    for path in sorted(src.rglob('*')):
        rel = path.relative_to(src)
        if path.name.startswith('vr_aa_') or path.name in AA_FILES or path.is_dir():
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path.resolve(), target)


def write(path, text, executable=False, crlf=False):
    text = text.replace('@REPO@', GITHUB_REPO)
    path.write_text(text.replace('\n', '\r\n') if crlf else text, newline='')
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('out', type=Path)
    parser.add_argument('--linux-binary', type=Path, default=REPO / 'eduke32-xr')
    parser.add_argument('--windows-dir', type=Path, required=True, help='eduke32-vr.exe, openxr_loader.dll, libopus-0.dll')
    parser.add_argument('--packs', type=Path, default=Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'eduke32-vr/vrpacks')
    parser.add_argument('--world-tour', type=Path, default=WORLD_TOUR)
    parser.add_argument('--addons', type=Path, default=ADDONS, help='folder with the Atomic DUKE3D.GRP and dukedc/vacation/nwinter.grp')
    parser.add_argument('--zip', action='store_true', help='also write OUT.tar.gz (Linux) and OUT.zip (Windows)')
    parser.add_argument('--linux-arm64-dir', type=Path, help='prebuilt 64-bit ARM build: eduke32-vr and lib/ (package/vr/build_linux_arm64.sh)')
    parser.add_argument('--version', required=True, help='the GitHub release this bundle matches (VERSION, for update.sh/ps1)')
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        sys.exit(f'make_personal_bundle: {out} is not empty')
    data = out / 'data'

    # Builds.
    copy_linux_build(args.linux_binary, out / 'linux')
    if args.linux_arm64_dir:
        shutil.copytree(args.linux_arm64_dir, out / 'linux-arm64', symlinks=False)
    copy_windows_build(args.windows_dir, out / 'windows')

    # Model sets and generated extras.
    for pack in PACKS:
        copy_pack(args.packs / pack, data / 'vrpacks' / pack)
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
    (data / 'addons').mkdir()
    for name in ('DUKE3D.GRP', 'dukedc.grp', 'vacation.grp', 'nwinter.grp'):
        shutil.copy2(args.addons / name, data / 'addons' / name)

    # Scripts.
    write(out / 'play.sh', SH_PLAY, True)
    write(out / 'play-expansion.sh', SH_EXPANSION, True)
    for mode in ('vr', 'desktop'):
        write(out / f'join-marmot-{mode}.sh', SH_JOIN.replace('{mode}', mode).replace('{server}', SERVER), True)
        write(out / f'join-marmot-{mode}.bat', BAT_JOIN.replace('{mode}', mode).replace('{server}', SERVER), crlf=True)
    write(out / 'join.sh', SH_JOIN_ANY, True)
    write(out / 'join.bat', BAT_JOIN_ANY, crlf=True)
    write(out / 'VERSION', args.version + '\n')
    write(out / 'install.sh', SH_INSTALL, True)
    write(out / 'update.sh', SH_UPDATE, True)
    write(out / 'play.bat', BAT_PLAY, crlf=True)
    write(out / 'play-expansion.bat', BAT_EXPANSION, crlf=True)
    write(out / 'install.ps1', PS_INSTALL, crlf=True)
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
