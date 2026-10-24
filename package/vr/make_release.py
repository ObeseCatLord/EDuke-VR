#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Assemble a redistributable EDuke32 VR tree (nothing is uploaded).

Usage: make_release.py OUT [--binary eduke32-xr] [--assets DUKE_VR_ASSETS]

OUT receives:
  eduke32-vr/            launcher, DEF and pack builders (and build_voxel_pack.py, which makes
                         the Voxel Duke pack from the player's own copy of that mod), AA
                         compatibility CON, docs,
                         GPL text, the binary (when given or built), a source
                         archive of the current commit (GPL source) and
                         vrpacks/original.zip and original-lowres.zip, the
                         original model set (and its low-res skins) as
                         ready-to-use mods
  duke-vr-assets/v7-original/, v6-original/
                         only the original models, skins, hand rig and
                         metadata the builders read (v6 supplies the parts v7
                         has not remade yet), plus README/manifest/pack.json

Only the original sets are copied. The release_excludes (private reference
tiles and renders, comparison sheets) are enforced, and the DEF builder is run
with --release against the assembled tree to prove it needs nothing else.
Game data (GRP/ART) is never included.
"""
import argparse
import fnmatch
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ASSET_METADATA = ('hand_poses_flat.json', 'aa_inventory.json', 'animation_mapping.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('out', type=Path)
    parser.add_argument('--binary', type=Path, default=REPO / 'eduke32-xr')
    parser.add_argument('--assets', type=Path, default=REPO.parent / 'duke-vr-assets')
    parser.add_argument('--no-source', action='store_true', help='skip the git source archive')
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        sys.exit(f'make_release: {out} is not empty')
    game = out / 'eduke32-vr'
    excludes = ['references/', 'previews/', 'masters/', 'work/']

    def excluded(rel):
        return any(rel.startswith(pattern) if pattern.endswith('/') else fnmatch.fnmatch(rel, pattern)
                   for pattern in excludes)

    # Engine side.
    (game / 'package/vr').mkdir(parents=True)
    for name in ('eduke32-vr-play', 'build_vr_def.py', 'build_vr_pack.py', 'build_voxel_pack.py', 'money_wad.py'):
        shutil.copy2(REPO / 'package/vr' / name, game / 'package/vr' / name)
    # Code only: the Voxel Duke pack is built on the player's machine from their own download.
    shutil.copytree(REPO / 'package/vr/voxelpack', game / 'package/vr/voxelpack', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(REPO / 'package/vr/aa566', game / 'package/vr/aa566')
    (game / 'docs/vr').mkdir(parents=True)
    for doc in ('PLAYING.md', 'FULL_PITCH.md'):
        if (REPO / 'docs/vr' / doc).is_file():
            shutil.copy2(REPO / 'docs/vr' / doc, game / 'docs/vr' / doc)
    shutil.copy2(REPO / 'README-VR.md', game / 'README-VR.md')
    shutil.copy2(REPO / 'package/common/gpl-2.0.txt', game / 'gpl-2.0.txt')
    if args.binary.is_file():
        shutil.copy2(args.binary, game / 'eduke32-xr')
    if not args.no_source:
        subprocess.run(['git', '-C', str(REPO), 'archive', '--format=tar.gz', '--prefix=eduke32-vr-source/',
                        '-o', str(game / 'eduke32-vr-source.tar.gz'), 'HEAD'], check=True)

    # Original assets only.
    copied = []
    for set_name in ('v7-original', 'v7-original-lowres', 'v6-original'):
        src, dst = args.assets.resolve() / set_name, out / 'duke-vr-assets' / set_name
        if not src.is_dir():
            continue
        if (src / 'manifest.json').is_file():
            excludes_set = excludes + json.loads((src / 'manifest.json').read_text()).get('release_excludes', [])
        else:
            excludes_set = excludes
        for path in sorted((src / 'exports/eduke32').rglob('*')):
            rel = path.relative_to(src).as_posix()
            if path.is_file() and path.suffix in ('.md3', '.png', '.skin', '.skel', '.anim', '.headverts', '.fphide',
                                                  '.handverts_l', '.handverts_r') \
                    and not any(rel.startswith(e) if e.endswith('/') else fnmatch.fnmatch(rel, e) for e in excludes_set):
                target = dst / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                copied.append(f'{set_name}/{rel}')
        (dst / 'metadata').mkdir(parents=True, exist_ok=True)
        for name in ASSET_METADATA:
            if (src / 'metadata' / name).is_file():
                shutil.copy2(src / 'metadata' / name, dst / 'metadata' / name)
                copied.append(f'{set_name}/metadata/{name}')
        for name in ('README.md', 'manifest.json', 'pack.json'):
            if (src / name).is_file():
                shutil.copy2(src / name, dst / name)

    leaked = [f'{d.name}/{p.relative_to(d).as_posix()}' for d in (out / 'duke-vr-assets').iterdir()
              for p in d.rglob('*') if p.is_file() and excluded(p.relative_to(d).as_posix())]
    if leaked:
        sys.exit('make_release: excluded files in release: ' + ', '.join(leaked))

    # The assembled tree alone must satisfy the release DEF build.
    for aa in ([], ['--aa']):
        with tempfile.TemporaryDirectory() as data:
            run = subprocess.run([sys.executable, str(game / 'package/vr/build_vr_def.py'), str(out / 'duke-vr-assets'),
                                  data, '--release', *aa], capture_output=True, text=True, check=True)
            if 'WARNING' in run.stderr or ': none' in run.stderr:
                sys.exit('make_release: release DEF build incomplete:\n' + run.stderr)
    # The original set as a ready-to-use mod (drop into any "vrpacks" folder, or -g it).
    for set_name in ('v7-original', 'v7-original-lowres'):
        if (out / 'duke-vr-assets' / set_name / 'pack.json').is_file():
            subprocess.run([sys.executable, str(game / 'package/vr/build_vr_pack.py'), str(out / 'duke-vr-assets'), set_name,
                            str(game / 'vrpacks'), '--release', '--zip'], check=True, capture_output=True, text=True)
    print(json.dumps({'out': str(out), 'asset_files': len(copied), 'packs': sorted(p.name for p in (game / 'vrpacks').glob('*.zip')),
                      'binary': (game / 'eduke32-xr').is_file(),
                      'source_archive': (game / 'eduke32-vr-source.tar.gz').is_file()}, indent=1))


if __name__ == '__main__':
    main()
