#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Assemble a redistributable EDuke32 VR tree (nothing is uploaded).

Usage: make_release.py OUT [--binary eduke32-xr] [--assets DUKE_VR_ASSETS]

OUT receives:
  eduke32-vr/            launcher, DEF builder, AA compatibility CON, docs,
                         GPL text, the binary (when given or built) and a
                         source archive of the current commit (GPL source)
  duke-vr-assets/v6-original/
                         only the original models, skins, hand rig and
                         metadata the launcher reads, plus README/manifest

Only v6-original assets are copied. The manifest's release_excludes (private
reference tiles, comparison sheets) are enforced, and the DEF builder is run
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
    game, v6_src = out / 'eduke32-vr', args.assets.resolve() / 'v6-original'
    v6 = out / 'duke-vr-assets/v6-original'
    manifest = json.loads((v6_src / 'manifest.json').read_text())
    excludes = manifest.get('release_excludes', [])

    def excluded(rel):
        return any(rel.startswith(pattern) if pattern.endswith('/') else fnmatch.fnmatch(rel, pattern)
                   for pattern in excludes)

    # Engine side.
    (game / 'package/vr').mkdir(parents=True)
    for name in ('eduke32-vr-play', 'build_vr_def.py'):
        shutil.copy2(REPO / 'package/vr' / name, game / 'package/vr' / name)
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
    for path in sorted((v6_src / 'exports/eduke32').rglob('*')):
        rel = path.relative_to(v6_src).as_posix()
        if path.is_file() and path.suffix in ('.md3', '.png') and not excluded(rel):
            target = v6 / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied.append(rel)
    (v6 / 'metadata').mkdir(parents=True, exist_ok=True)
    for name in ASSET_METADATA:
        if (v6_src / 'metadata' / name).is_file():
            shutil.copy2(v6_src / 'metadata' / name, v6 / 'metadata' / name)
            copied.append('metadata/' + name)
    for name in ('README.md', 'manifest.json'):
        shutil.copy2(v6_src / name, v6 / name)

    leaked = [p.relative_to(v6).as_posix() for p in v6.rglob('*') if p.is_file() and excluded(p.relative_to(v6).as_posix())]
    if leaked:
        sys.exit('make_release: excluded files in release: ' + ', '.join(leaked))

    # The assembled tree alone must satisfy the release DEF build.
    for aa in ([], ['--aa']):
        with tempfile.TemporaryDirectory() as data:
            run = subprocess.run([sys.executable, str(game / 'package/vr/build_vr_def.py'), str(out / 'duke-vr-assets'),
                                  data, '--release', *aa], capture_output=True, text=True, check=True)
            if 'WARNING' in run.stderr or ': none' in run.stderr:
                sys.exit('make_release: release DEF build incomplete:\n' + run.stderr)
    print(json.dumps({'out': str(out), 'asset_files': len(copied),
                      'binary': (game / 'eduke32-xr').is_file(),
                      'source_archive': (game / 'eduke32-vr-source.tar.gz').is_file()}, indent=1))


if __name__ == '__main__':
    main()
