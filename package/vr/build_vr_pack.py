#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build an EDuke32 VR model pack as an ordinary mod folder or zip.

Usage: build_vr_pack.py ASSETS PACKDIR OUT [--release] [--glow] [--zip]

ASSETS is the duke-vr-assets checkout and PACKDIR one of its pack directories (one with a pack.json,
e.g. v7-original). The pack is written to OUT/<name>/, or to OUT/<name>.zip with --zip. Without --zip
the files are symlinks into ASSETS (quick to rebuild; for local use); the zip holds real copies (for
sharing; with --release it refuses non-redistributable packs).

Layout, like any mod:
  vrpack.def                 the models (EDuke32 DEF), Duke Nukem 3D and its add-ons
  vrpack_aa.def              the models for Alien Armageddon (when the assets have its arsenal)
  vrpack/pack.txt            name=, title=, filter=, redistributable=, autoload_games=
  vrpack/hand-rig.txt        VR hand rig, holds and full body (hand-rig-aa.txt for AA)
  vrpack/hud-model-map-aa.txt
  vrpack/autoload/*.zip      game data the pack brings (e.g. a voxel world), loaded with it
  vr_*.md3/.png/...          model files referenced by the above

The game loads a pack from a "vrpacks/" folder on its search path ([Setup] VRModelPack in the config
or -vrpack NAME), or any pack given like another mod (-g PACK.zip, -j PACKDIR).
"""
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPECIAL = {'hand-rig.txt', 'hud-model-map.txt', 'pack-filter.txt', 'pack-autoload.txt'}


def run_builder(assets, data, packdir, aa, flags):
    data.mkdir(parents=True)
    command = [sys.executable, str(HERE / 'build_vr_def.py'), str(assets), str(data), f'--pack={packdir}', *flags]
    if aa:
        command.append('--aa')
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f'build_vr_pack: {packdir}{" (aa)" if aa else ""}: {result.stderr.strip()}')
    return result.stdout, result.stderr


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) != 3:
        raise SystemExit(__doc__)
    assets, packdir, out = Path(args[0]).resolve(), args[1], Path(args[2])
    release, as_zip = '--release' in sys.argv, '--zip' in sys.argv
    flags = [f for f in ('--release', '--glow') if f in sys.argv]
    info = json.loads((assets / packdir / 'pack.json').read_text())
    name = info.get('name', packdir)
    if release and info.get('redistributable') is False:
        raise SystemExit(f'build_vr_pack: {packdir} is not redistributable')
    out.mkdir(parents=True, exist_ok=True)
    stage = out / f'.{name}.build'
    if stage.exists():
        shutil.rmtree(stage)
    pack = stage / 'pack'
    (pack / 'vrpack').mkdir(parents=True)

    files = {}   # pack file name -> real source path
    notes = []
    variants = [('vrpack.def', 'hand-rig.txt', False)]
    if (assets / 'aa-v1/metadata/arsenal_inventory.json').is_file() or (assets / 'v6-original/metadata/aa_inventory.json').is_file():
        variants.append(('vrpack_aa.def', 'hand-rig-aa.txt', True))
    autoload, texture_filter = [], ''
    for def_name, rig_name, aa in variants:
        data = stage / ('aa' if aa else 'duke3d')
        text, log = run_builder(assets, data, packdir, aa, flags)
        notes += [line for line in log.splitlines() if 'WARNING' in line]
        (pack / def_name).write_text(f'// EDuke32 VR model pack "{name}" ({"Alien Armageddon" if aa else "Duke Nukem 3D"}); '
                                     'built by build_vr_pack.py\n' + text)
        for entry in sorted(data.iterdir()):
            if entry.name in SPECIAL or not entry.is_symlink():
                continue
            files.setdefault(entry.name, entry.resolve())
        if (data / 'hand-rig.txt').is_file():
            (pack / 'vrpack' / rig_name).write_text((data / 'hand-rig.txt').read_text())
        if aa and (data / 'hud-model-map.txt').is_file():
            (pack / 'vrpack' / 'hud-model-map-aa.txt').write_text((data / 'hud-model-map.txt').read_text())
        if not aa:
            texture_filter = (data / 'pack-filter.txt').read_text().strip() if (data / 'pack-filter.txt').is_file() else ''
            if (data / 'pack-autoload.txt').is_file():
                autoload = [Path(line) for line in (data / 'pack-autoload.txt').read_text().splitlines() if line]
    for path in autoload:
        files[f'vrpack/autoload/{path.name}'] = path
    games = info.get('games', ['duke3d', 'aa566'])
    (pack / 'vrpack' / 'pack.txt').write_text(
        f'name={name}\ntitle={info.get("title", name)}\nfilter={texture_filter}\n'
        f'redistributable={0 if info.get("redistributable") is False else 1}\n'
        + (f'autoload_games={",".join(games)}\n' if autoload else ''))

    if as_zip:
        target = out / f'{name}.zip'
        tmp = out / f'.{name}.zip.part'
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(pack.rglob('*')):
                if path.is_file():
                    archive.write(path, path.relative_to(pack).as_posix())
            for rel, source in sorted(files.items()):
                archive.write(source, rel)
        tmp.replace(target)
    else:
        for rel, source in files.items():
            (pack / rel).parent.mkdir(parents=True, exist_ok=True)
            (pack / rel).symlink_to(source)
        target = out / name
        old = out / f'.{name}.old'
        if old.exists():
            shutil.rmtree(old)
        if target.exists():
            target.rename(old)
        pack.rename(target)
        if old.exists():
            shutil.rmtree(old)
    shutil.rmtree(stage)
    print(target)
    for note in notes:
        print(note, file=sys.stderr)


if __name__ == '__main__':
    main()
