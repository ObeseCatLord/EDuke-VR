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
WORLD_TOUR = Path('/home/obesecatlord/Windows/Steam/steamapps/common/Duke Nukem 3D Twentieth Anniversary World Tour')
ADDONS = Path.home() / '.config/eduke32'
LINUX_LIBS = ('libSDL2-2.0.so.0', 'libopenxr_loader.so.1', 'libopus.so.0', 'libvpx.so.12', 'libFLAC.so.14', 'libogg.so.0',
              'libjsoncpp.so.27', 'libatomic.so.1')
PACKS = ('original', 'original-lowres', 'voxel')
AA_FILES = ('hand-rig-aa.txt', 'hud-model-map-aa.txt')

# ---------------------------------------------------------------- scripts (Linux)
SH_COMMON = r'''#!/usr/bin/env bash
# EDuke32 VR personal bundle. VR needs an OpenXR runtime (Monado/Envision, WiVRn or SteamVR).
set -euo pipefail
here=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
data="$here/data"
export LD_LIBRARY_PATH="$here/linux/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
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
        "$here/linux/eduke32-vr" -j "$data" -j "$data/local/duke3d" -mh vr-local.def "${pack[@]}" -nosetup "$@" || status=$?
        [[ -s $restart ]] || return "$status"
        pack=(-vrpack "$(head -n1 "$restart")")   # the VR Setup menu switched model sets
    done
}
'''

def sh_script(body):
    return SH_COMMON + body

SH_PLAY = sh_script(r'''# ./play.sh [vr|desktop] [extra EDuke32 arguments]   (default: vr)
mode=${1:-vr}; [[ $# -gt 0 ]] && shift
run "$mode" -j "$data/grp" -gamegrp DUKE3D.GRP "$@"
''')
SH_JOIN = sh_script(r'''# Join the marmot (foundry) Duke server in MODE. Same game data as the server: the World Tour GRP.
run "{mode}" -j "$data/grp" -gamegrp DUKE3D.GRP -connect {server} "$@"
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
    mkdir -p "$dest"
    rsync -a --delete --exclude 'data/local/*' "$here/" "$dest/" 2>/dev/null || { rm -rf "$dest"; cp -a "$here" "$dest"; }
    mkdir -p "$dest/data/local"; cp -an "$here/data/local/." "$dest/data/local/" 2>/dev/null || true
fi
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"; mkdir -p "$apps"
entry() {   # file name exec
    printf '[Desktop Entry]\nType=Application\nName=%s\nExec=%s\nTerminal=false\nCategories=Game;\n' "$2" "$3" > "$apps/$1.desktop"
}
entry eduke32-vr "Duke Nukem 3D VR" "$dest/play.sh vr"
entry eduke32-vr-desktop "Duke Nukem 3D (desktop)" "$dest/play.sh desktop"
entry eduke32-vr-marmot "Duke 3D VR - join marmot server" "$dest/join-marmot-vr.sh"
entry eduke32-vr-marmot-desktop "Duke 3D - join marmot server (desktop)" "$dest/join-marmot-desktop.sh"
echo "Installed in $dest (app menu: Duke Nukem 3D VR)."
'''
SH_UPDATE = r'''#!/usr/bin/env bash
# ./update.sh NEW_BUNDLE.tar.gz   installs a newer bundle over this one (settings and saves are kept)
set -euo pipefail
archive=${1:?usage: update.sh eduke32-vr-bundle-*.tar.gz}
here=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
tar -xzf "$archive" -C "$tmp"
new=$(find "$tmp" -maxdepth 2 -name install.sh -printf '%h\n' | head -1)
[[ -n $new ]] || { echo "update: $archive is not an EDuke32 VR bundle" >&2; exit 1; }
"$new/install.sh" "$here"
'''

# ---------------------------------------------------------------- scripts (Windows)
BAT_COMMON = r'''@echo off
setlocal EnableDelayedExpansion
rem EDuke32 VR personal bundle. VR needs an OpenXR runtime (SteamVR, Oculus, WMR, Virtual Desktop...).
set "HERE=%~dp0"
set "DATA=%HERE%data"
set "EXE=%HERE%windows\eduke32-vr.exe"
set "EDUKE32_XR_RESTART_REQUEST=%TEMP%\eduke32-vr-restart.txt"
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
call :run %M% -j "%DATA%\grp" -gamegrp DUKE3D.GRP
''')
BAT_JOIN = bat(r'''rem Join the marmot (foundry) Duke server ({mode}). Same game data as the server: the World Tour GRP.
call :run {mode} -j "%DATA%\grp" -gamegrp DUKE3D.GRP -connect {server}
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
    robocopy $here $Dest /MIR /XD "$here\data\local" /NFL /NDL /NJH /NJS /NP | Out-Null
    robocopy "$here\data\local" "$Dest\data\local" /E /XC /XN /XO /NFL /NDL /NJH /NJS /NP | Out-Null
}
$menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'EDuke32 VR'
New-Item -ItemType Directory -Force $menu | Out-Null
$shell = New-Object -ComObject WScript.Shell
foreach ($s in @(@('Duke Nukem 3D VR','play.bat','vr'), @('Duke Nukem 3D (desktop)','play.bat','desktop'),
                 @('Join marmot server (VR)','join-marmot-vr.bat',''), @('Join marmot server (desktop)','join-marmot-desktop.bat',''))) {
    $l = $shell.CreateShortcut((Join-Path $menu ($s[0] + '.lnk')))
    $l.TargetPath = Join-Path $Dest $s[1]; $l.Arguments = $s[2]; $l.WorkingDirectory = $Dest
    $l.IconLocation = (Join-Path $Dest 'windows\eduke32-vr.exe'); $l.Save()
}
Write-Host "Installed in $Dest (Start menu: EDuke32 VR)."
'''
PS_UPDATE = r'''# Install a newer bundle over this one (settings and saves are kept):
#   powershell -ExecutionPolicy Bypass -File update.ps1 C:\path\eduke32-vr-bundle-....zip
param([Parameter(Mandatory=$true)][string]$Archive)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$tmp = Join-Path $env:TEMP ("eduke32-vr-update-" + [guid]::NewGuid())
Expand-Archive -Path $Archive -DestinationPath $tmp
$new = Get-ChildItem $tmp -Recurse -Filter install.ps1 | Select-Object -First 1
if (-not $new) { throw "$Archive is not an EDuke32 VR bundle" }
& powershell -ExecutionPolicy Bypass -File $new.FullName -Dest $here
Remove-Item -Recurse -Force $tmp
'''

README = '''EDuke32 VR - personal test bundle ({stamp})
PERSONAL USE ONLY: contains your own game data and the private Voxel Duke pack. Do not share.

Linux:   ./install.sh  (optional; adds app-menu entries)   then ./play.sh vr | ./play.sh desktop
         ./join-marmot-vr.sh | ./join-marmot-desktop.sh            (server {server})
         ./play-expansion.sh worldtour|dc|caribbean|nuclearwinter [vr|desktop]
         Needs an OpenXR runtime for VR (Monado/Envision, WiVRn, SteamVR) and a recent glibc
         (built on Arch); SDL2, OpenXR loader, Opus etc. are in linux/lib.
Windows: install.ps1 (optional; Start menu shortcuts: right-click > Run with PowerShell)
         play.bat vr | play.bat desktop, join-marmot-vr.bat, join-marmot-desktop.bat,
         play-expansion.bat worldtour|dc|caribbean|nuclearwinter [vr|desktop]
         VR needs an OpenXR runtime (SteamVR, Oculus, WMR, Virtual Desktop/VDXR...).
Update:  ./update.sh NEW.tar.gz  /  powershell -ExecutionPolicy Bypass -File update.ps1 NEW.zip

Model sets: Voxel Duke (default), original, original-lowres; switch in Options > VR Setup.
Multiplayer joins use the World Tour GRP like the server; voice chat is on in VR (Options > Sound).
Built from commit {commit}.
'''


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
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        sys.exit(f'make_personal_bundle: {out} is not empty')
    data = out / 'data'

    # Builds.
    (out / 'linux/lib').mkdir(parents=True)
    shutil.copy2(args.linux_binary, out / 'linux/eduke32-vr')
    ldd = subprocess.run(['ldd', str(args.linux_binary)], capture_output=True, text=True, check=True).stdout
    for line in ldd.splitlines():
        parts = line.split()
        if parts and parts[0] in LINUX_LIBS and '=>' in parts:
            shutil.copy2(Path(parts[2]).resolve(), out / 'linux/lib' / parts[0])
    (out / 'windows').mkdir()
    for name in ('eduke32-vr.exe', 'openxr_loader.dll', 'libopus-0.dll'):
        shutil.copy2(args.windows_dir / name, out / 'windows' / name)

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
    write(out / 'install.sh', SH_INSTALL, True)
    write(out / 'update.sh', SH_UPDATE, True)
    write(out / 'play.bat', BAT_PLAY, crlf=True)
    write(out / 'play-expansion.bat', BAT_EXPANSION, crlf=True)
    write(out / 'install.ps1', PS_INSTALL, crlf=True)
    write(out / 'update.ps1', PS_UPDATE, crlf=True)
    commit = subprocess.run(['git', '-C', str(REPO), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
    stamp = subprocess.run(['date', '+%Y-%m-%d'], capture_output=True, text=True).stdout.strip()
    write(out / 'README.txt', README.format(stamp=stamp, server=SERVER, commit=commit))

    result = {'out': str(out), 'linux_libs': sorted(p.name for p in (out / 'linux/lib').iterdir()),
              'packs': sorted(p.name for p in (data / 'vrpacks').iterdir()), 'commit': commit}
    if args.zip:
        subprocess.run(['tar', '-czf', f'{out}.tar.gz', '-C', str(out.parent), out.name], check=True)
        subprocess.run(['zip', '-qr', f'{out}.zip', out.name], cwd=out.parent, check=True)
        result['archives'] = [f'{out}.tar.gz', f'{out}.zip']
    print(json.dumps(result, indent=1))


if __name__ == '__main__':
    main()
