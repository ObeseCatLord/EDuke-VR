#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build the public EDuke VR release archives for GitHub (nothing is uploaded).

    make_github_release.py OUT --version vX.Y.Z --windows-dir WINDIR [--linux-binary BIN] [--release DIR]

OUT receives
  EDuke-VR-<version>-linux-x86_64.tar.gz   EDuke-VR/ with linux/ (game + libraries), play/join/
                                           install/update .sh
  EDuke-VR-<version>-windows-x64.zip       EDuke-VR/ with windows/ (game + DLLs), play/join .bat,
                                           install/update .ps1
both with data/vrpacks/ (the original and original-lowres model sets, without the Alien
Armageddon files), licenses/, README.txt and VERSION (read by update.sh/ps1).

No game data and no private model sets. The model sets come from make_release.py (run here unless
--release names its output), which copies only the original sets and enforces their release
excludes. The money wad (cut from the player's GRP) is not included. The archives have the
personal bundle's layout, so update.sh/ps1 in either lays a release over an install and keeps
everything else (GRPs, expansions, Voxel Duke, settings, saves).

The Linux binary should be built portable: make NETCODE=1 USE_OPENXR=1 PORTABLE_GLIBC=1 LTO=0
(it then needs glibc 2.38 and GCC 13's libstdc++ with the bundled libraries).
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import make_personal_bundle as mpb  # noqa: E402  (shared scripts and copy helpers)

PUBLIC_PACKS = ('original', 'original-lowres')
# Third-party license texts on the build host (Arch Linux packages), by bundled component.
LINUX_LICENSES = {
    'OpenXR-loader-Apache-2.0.txt': '/usr/share/licenses/spdx/Apache-2.0.txt',
    'opus-COPYING.txt': '/usr/share/licenses/opus/COPYING',
    'libvpx-LICENSE.txt': '/usr/share/licenses/libvpx/LICENSE',
    'flac-COPYING.Xiph.txt': '/usr/share/licenses/flac/COPYING.Xiph',
    'libogg-COPYING.txt': '/usr/share/licenses/libogg/COPYING',
    'jsoncpp-LICENSE.txt': '/usr/share/licenses/jsoncpp/LICENSE',
    'libatomic-GPL-3.0.txt': '/usr/share/licenses/spdx/GPL-3.0-or-later.txt',
    'libatomic-RUNTIME.LIBRARY.EXCEPTION.txt': '/usr/share/licenses/libatomic/RUNTIME.LIBRARY.EXCEPTION',
}
WINDOWS_LICENSES = {
    'OpenXR-loader-Apache-2.0.txt': '/usr/share/licenses/spdx/Apache-2.0.txt',
    'opus-COPYING.txt': '/usr/share/licenses/opus/COPYING',
    'SDL2-zlib-LICENSE.txt': '/usr/share/licenses/sdl2-compat/LICENSE.txt',
    'libvpx-LICENSE.txt': '/usr/share/licenses/libvpx/LICENSE',
}

README = '''EDuke VR {version}
Duke Nukem 3D in VR (OpenXR) and on the desktop, based on EDuke32.
https://github.com/@REPO@

You need your own copy of Duke Nukem 3D. Put its DUKE3D.GRP in data/grp/, or have the game
installed (Steam: 20th Anniversary World Tour or Megaton; GOG), where EDuke32 finds it itself.

{platform}
Update:  {update}
         Downloads the latest release from GitHub and lays it over this folder. Files the release
         does not carry stay: your game data, other model sets, settings and saved games.

In VR: Options > VR Setup (model set, snap turn, hand used for weapons, voice chat...).
Model sets: original and original-lowres. The Voxel Duke set can be built from your copy of that
mod with package/vr/build_voxel_pack.py from the source code.
Multiplayer: all players need the same version (the server too) and the same game data.

Licenses: EDuke32 and EDuke VR are under the GNU GPL version 2 (licenses/gpl-2.0.txt). The Build
engine source is under Ken Silverman's BUILD license (licenses/buildlic.txt: non-commercial use).
The bundled third-party libraries keep their own licenses (licenses/THIRD-PARTY.txt). Duke Nukem 3D
is a trademark of Gearbox Software; no game data is included. Source code: the repository above,
tag {version} (GitHub's "Source code" downloads of this release).
'''
LINUX_TEXT = '''Linux:   ./play.sh vr | ./play.sh desktop        ./join.sh HOST[:PORT] [vr|desktop]
         ./install.sh copies this folder to ~/.local/share/eduke32-vr-bundle and adds menu entries.
         Needs glibc 2.38+ (Ubuntu 24.04, Debian 13, Fedora 39, Arch...), SDL2 (installed with
         Steam) and, for VR, an OpenXR runtime (SteamVR, Monado/Envision, WiVRn).'''
WINDOWS_TEXT = '''Windows: play.bat vr | play.bat desktop          join.bat HOST[:PORT] [vr|desktop]
         install.ps1 (right-click > Run with PowerShell) copies this folder to
         %LOCALAPPDATA%\\EDuke32-VR and adds Start menu entries.
         VR needs an OpenXR runtime (SteamVR, Oculus/Meta, WMR, Virtual Desktop/VDXR).'''
THIRD_PARTY = '''Third-party components bundled with EDuke VR {version}

EDuke VR (this port) and EDuke32: GNU GPL v2 (gpl-2.0.txt); Build engine: BUILD license
(buildlic.txt). EDuke32 also contains code under other free licenses (see its source tree).

{items}
'''
LINUX_ITEMS = '''linux/lib/libopenxr_loader.so.1   Khronos OpenXR loader, Apache License 2.0 (OpenXR-loader-Apache-2.0.txt)
linux/lib/libopus.so.0            Opus, BSD 3-clause (opus-COPYING.txt)
linux/lib/libvpx.so.12            libvpx, BSD 3-clause (libvpx-LICENSE.txt)
linux/lib/libFLAC.so.14           FLAC, BSD 3-clause (flac-COPYING.Xiph.txt)
linux/lib/libogg.so.0             libogg, BSD 3-clause (libogg-COPYING.txt)
linux/lib/libjsoncpp.so.27        JsonCpp, MIT (jsoncpp-LICENSE.txt)
linux/lib/libatomic.so.1          GCC libatomic, GPL v3 with the GCC Runtime Library Exception
                                  (libatomic-GPL-3.0.txt, libatomic-RUNTIME.LIBRARY.EXCEPTION.txt)'''
WINDOWS_ITEMS = '''windows/openxr_loader.dll         Khronos OpenXR loader, Apache License 2.0 (OpenXR-loader-Apache-2.0.txt)
windows/libopus-0.dll             Opus, BSD 3-clause (opus-COPYING.txt)
windows/eduke32-vr.exe            statically links SDL2 (zlib license, SDL2-zlib-LICENSE.txt) and
                                  libvpx (BSD 3-clause, libvpx-LICENSE.txt)'''


def licenses(dest, table, items, version):
    dest.mkdir(parents=True)
    shutil.copy2(REPO / 'package/common/gpl-2.0.txt', dest / 'gpl-2.0.txt')
    shutil.copy2(REPO / 'package/common/buildlic.txt', dest / 'buildlic.txt')
    for name, source in table.items():
        shutil.copy2(source, dest / name)
    (dest / 'THIRD-PARTY.txt').write_text(THIRD_PARTY.format(version=version, items=items))


def tree(root, version, platform, binary, windir, packs):
    """One platform's EDuke-VR/ folder."""
    out = root / 'EDuke-VR'
    data = out / 'data'
    for pack in PUBLIC_PACKS:
        mpb.copy_pack(packs / pack, data / 'vrpacks' / pack)
    (data / 'grp').mkdir(parents=True)
    (data / 'grp/PUT DUKE3D.GRP HERE.txt').write_text('Optional: put your DUKE3D.GRP here (else an installed copy is found).\n')
    mpb.write(out / 'VERSION', version + '\n')
    if platform == 'linux':
        mpb.copy_linux_build(binary, out / 'linux')
        mpb.write(out / 'play.sh', mpb.SH_PLAY, True)
        mpb.write(out / 'join.sh', mpb.SH_JOIN_ANY, True)
        mpb.write(out / 'install.sh', mpb.SH_INSTALL, True)
        mpb.write(out / 'update.sh', mpb.SH_UPDATE, True)
        licenses(out / 'licenses', LINUX_LICENSES, LINUX_ITEMS, version)
        text, update = LINUX_TEXT, './update.sh'
    else:
        mpb.copy_windows_build(windir, out / 'windows')
        mpb.write(out / 'play.bat', mpb.BAT_PLAY, crlf=True)
        mpb.write(out / 'join.bat', mpb.BAT_JOIN_ANY, crlf=True)
        mpb.write(out / 'install.ps1', mpb.PS_INSTALL, crlf=True)
        mpb.write(out / 'update.ps1', mpb.PS_UPDATE, crlf=True)
        licenses(out / 'licenses', WINDOWS_LICENSES, WINDOWS_ITEMS, version)
        text, update = WINDOWS_TEXT, 'powershell -ExecutionPolicy Bypass -File update.ps1'
    mpb.write(out / 'README.txt', README.format(version=version, platform=text, update=update),
              crlf=platform == 'windows')
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('out', type=Path)
    parser.add_argument('--version', required=True, help='release tag, e.g. v0.1.0')
    parser.add_argument('--linux-binary', type=Path, default=REPO / 'eduke32-xr-portable')
    parser.add_argument('--windows-dir', type=Path, required=True, help='eduke32-vr.exe, openxr_loader.dll, libopus-0.dll')
    parser.add_argument('--release', type=Path, help='an existing make_release.py output (else one is made)')
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        sys.exit(f'make_github_release: {out} is not empty')
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out) as scratch:
        scratch = Path(scratch)
        release = args.release
        if release is None:
            release = scratch / 'release'
            subprocess.run([sys.executable, str(HERE / 'make_release.py'), str(release), '--no-source',
                            '--binary', str(args.linux_binary)], check=True, stdout=subprocess.DEVNULL)
        packs = scratch / 'packs'
        for pack in PUBLIC_PACKS:
            with zipfile.ZipFile(release / 'eduke32-vr/vrpacks' / f'{pack}.zip') as z:
                z.extractall(packs / pack)
        name = f'EDuke-VR-{args.version}'
        lin = tree(scratch / 'linux', args.version, 'linux', args.linux_binary, None, packs)
        subprocess.run(['tar', '-czf', str(out / f'{name}-linux-x86_64.tar.gz'), '-C', str(lin.parent), lin.name], check=True)
        win = tree(scratch / 'windows', args.version, 'windows', None, args.windows_dir, packs)
        subprocess.run(['zip', '-qr', str(out / f'{name}-windows-x64.zip'), win.name], cwd=win.parent, check=True)
    archives = sorted(str(p) for p in out.iterdir())
    print(json.dumps({'version': args.version, 'archives': archives}, indent=1))


if __name__ == '__main__':
    main()
