#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build the "Voxel Duke" VR model pack from your own copy of Voxel Duke Nukem 3D.

Usage: build_voxel_pack.py VOXEL_DUKE3D_ZIP [--assets DUKE_VR_ASSETS] [--out VRPACKS] [--zip] [--any-version]

The EDuke32 VR release ships no voxel content. Voxel Duke Nukem 3D v1.0 by Daniel Peterson ("Cheello")
is a separate download; give this script its zip (voxel_duke3d.zip) and it makes, on your machine:

  DUKE_VR_ASSETS/voxel-duke/   the pack's source folder: the held weapons (pistol, shotgun, ripper,
                               RPG, pipe bomb, shrinker, expander, devastator, trip bomb, freezer),
                               the Mighty Foot boot, the third-person Duke and the first-person body,
                               all meshed from the mod's voxels, with hand poses solved for every
                               weapon. The mod's zip is copied in too, so the game world is voxels as well.
  VRPACKS/voxel.zip (--zip)    the pack as a mod, or VRPACKS/voxel/ (default; links into the folder).

Duke is one skinned voxel body on v7's skeleton with his own hands (vr_duke_ik, vr_duke, vr_duke_body;
pack.json "ik_hands"). Anything the voxels do not cover (hands, detonator, flamethrower, laser,
wheel) falls back to the shipped original set. The launcher (eduke32-vr-play) lists the pack by
itself once the folder exists; pick it in VR Setup > Models or with --pack voxel.

Needs Python 3 with numpy, scipy and Pillow; CPU only; about 20 minutes, most of it solving the hand poses. The result is built from
third-party art: it is for your own use and is never redistributable (its pack.json says so, and
build_vr_pack.py --release refuses it).

DUKE_VR_ASSETS defaults to the duke-vr-assets folder next to this release (it must hold v6-original);
VRPACKS defaults to ~/.local/share/eduke32-vr/vrpacks.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE / 'voxelpack'
# Voxel Duke Nukem 3D v1.0 (the release the weapon mapping in voxelpack/weapon_specs.py was made for).
KNOWN_SHA256 = '935a9079c4f3a3c3a2a869e066c5366b0201a856cc6041644f644d22918178aa'
STEPS = [('meshing the weapons', 'build_weapons.py'), ('meshing the boot', 'build_boot.py'),
         ('building the skinned voxel Duke (third person, first-person and full IK body)', 'build_duke_skinned.py'), ('solving the hand poses', 'solve_holds.py'),
         ('checking the result', 'validate.py')]
NEEDED = ['voxels/weapons/21_PISTOL.kvx', 'voxels/player/1536_BOOT.kvx']


def extract(archive, target):
    """Extract the mod's files (data only; nothing in it is ever run). Refuses unsafe member paths."""
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            name = info.filename.replace('\\', '/')
            parts = [p for p in name.split('/') if p not in ('', '.')]
            if not parts or name.startswith('/') or '..' in parts or ':' in parts[0]:
                raise SystemExit(f'build_voxel_pack: unsafe path in {archive.name}: {info.filename!r}')
            dest = target.joinpath(*parts)
            if info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(dest, 'wb') as out:
                shutil.copyfileobj(src, out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('zip', type=Path, help='voxel_duke3d.zip (Voxel Duke Nukem 3D v1.0)')
    parser.add_argument('--assets', type=Path, default=HERE.parents[2] / 'duke-vr-assets')
    parser.add_argument('--out', type=Path, default=Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'eduke32-vr/vrpacks')
    parser.add_argument('--folder', default='voxel-duke', help='pack folder name inside the assets folder')
    parser.add_argument('--zip-pack', '--zip', dest='as_zip', action='store_true', help='write VRPACKS/voxel.zip instead of a linked folder')
    parser.add_argument('--any-version', action='store_true', help='try a zip other than v1.0 (the weapon mapping may not fit it)')
    args = parser.parse_args()

    for module in ('numpy', 'scipy', 'PIL'):
        try:
            __import__(module)
        except ImportError:
            raise SystemExit(f'build_voxel_pack: Python module {module!r} is missing (install numpy, scipy and Pillow)')
    archive = args.zip.resolve()
    if not archive.is_file():
        raise SystemExit(f'build_voxel_pack: {archive} not found')
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != KNOWN_SHA256 and not args.any_version:
        raise SystemExit(f'build_voxel_pack: {archive.name} is not Voxel Duke Nukem 3D v1.0 (sha256 {digest});\n'
                         'pass --any-version to try it anyway')
    assets = args.assets.resolve()
    if not (assets / 'v6-original/metadata/hand_poses_flat.json').is_file() or not (assets / 'v6-original/exports/eduke32/vr_pistol.md3').is_file():
        raise SystemExit(f'build_voxel_pack: {assets} does not hold the original model set (v6-original); use --assets')

    pack = assets / args.folder
    stage = assets / f'.{args.folder}.build'
    if stage.exists():
        shutil.rmtree(stage)
    (stage / 'source').mkdir(parents=True)
    print(f'build_voxel_pack: extracting {archive.name}', flush=True)
    extract(archive, stage / 'source')
    missing = [n for n in NEEDED if not (stage / 'source' / n).is_file()]
    if missing:
        shutil.rmtree(stage)
        raise SystemExit(f'build_voxel_pack: {archive.name} lacks {", ".join(missing)}; is it Voxel Duke Nukem 3D?')
    shutil.copy2(archive, stage / 'source/voxel_duke3d.zip')
    for sub in ('exports/eduke32', 'metadata/assets'):
        (stage / sub).mkdir(parents=True, exist_ok=True)
    (stage / 'pack.json').write_text(json.dumps({
        'name': 'voxel', 'title': 'Voxel Duke', 'texture_filter': 'nearest', 'redistributable': False,
        'source': f'Voxel Duke Nukem 3D by Daniel Peterson ("Cheello"), {archive.name} (sha256 {digest}); built by build_voxel_pack.py',
        'autoload': ['source/voxel_duke3d.zip'], 'games': ['duke3d'], 'ik_hands': True,
    }, indent=1) + '\n')
    (stage / 'README.txt').write_text(
        'Voxel Duke model pack for EDuke32 VR, built on this machine by build_voxel_pack.py from your copy of\n'
        'Voxel Duke Nukem 3D by Daniel Peterson ("Cheello"). Third-party art: personal use only, never redistribute.\n')

    env = dict(os.environ, EDUKE32_VOXEL_PACK=str(stage), EDUKE32_VR_ASSETS=str(assets), PYTHONDONTWRITEBYTECODE='1')
    for label, script in STEPS:
        print(f'build_voxel_pack: {label}', flush=True)
        run = subprocess.run([sys.executable, '-I', str(SCRIPTS / script)], cwd=stage, env=env, capture_output=True, text=True)
        if run.returncode:
            raise SystemExit(f'build_voxel_pack: {script} failed:\n{run.stdout[-3000:]}{run.stderr[-3000:]}')
    report = json.loads((stage / 'metadata/validation.json').read_text())
    hands = report.pop('hand_poses_flat', {})
    problems = {stem: r['errors'] for stem, r in report.items() if r.get('errors')}
    if len(report) < 13:
        problems['models'] = f'only {len(report)} of 13 models were built'
    if not (hands.get('same_joint_order') and hands.get('same_segments') and hands.get('joints_ok')):
        problems['hand poses'] = hands
    if problems:
        raise SystemExit('build_voxel_pack: validation found problems:\n' + json.dumps(problems, indent=1)[:3000])

    old = assets / f'.{args.folder}.old'
    if old.exists():
        shutil.rmtree(old)
    if pack.exists():
        pack.rename(old)
    stage.rename(pack)
    if old.exists():
        shutil.rmtree(old)
    built = subprocess.run([sys.executable, str(HERE / 'build_vr_pack.py'), str(assets), args.folder, str(args.out),
                            *(['--zip'] if args.as_zip else [])], capture_output=True, text=True)
    if built.returncode:
        raise SystemExit(f'build_voxel_pack: build_vr_pack.py failed:\n{built.stderr}')
    models = sorted(p.name for p in (pack / 'exports/eduke32').glob('*.md3'))
    print(f'build_voxel_pack: {len(models)} models in {pack}; pack: {built.stdout.strip()}')
    print('build_voxel_pack: choose "Voxel Duke" in VR Setup > Models (or eduke32-vr-play --pack voxel). '
          'Personal use only: never share the built pack.')


if __name__ == '__main__':
    main()
