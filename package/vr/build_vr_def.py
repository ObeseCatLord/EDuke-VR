#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Assemble the EDuke32 VR model DEF, hand rig and HUD-tile map.

Usage: build_vr_def.py ASSETS DATA [--aa] [--release]

ASSETS is the duke-vr-assets checkout, DATA the private output directory (the
game's -j search path). Prints the DEF to stdout and writes DATA/hand-rig.txt
and DATA/hud-model-map.txt; reports the chosen sources on stderr.

Sources in priority order:
  v6-original       original, redistributable models (always preferred)
  private fallbacks older packages that contain or derive from commercial
                    game data (Duke Nukem Forever); local use only, never with
                    --release
Tiles: 21 stock pistol, 30020+weapon held weapons, 30010/30011 single-mesh
hands, 30040 first-person body, 30100+family AA held weapons,
30200+side*32+segment finger-tracking hand segments.
"""
import json
import struct
import sys
from pathlib import Path

WEAPONS = {1: 'pistol', 2: 'shotgun', 3: 'chaingun', 4: 'rpg', 5: 'pipebomb', 6: 'shrinker', 7: 'devastator',
           8: 'tripbomb', 9: 'freezer', 10: 'detonator', 11: 'expander', 12: 'flamethrower'}
JOINTS = ['palm', 'wrist', 'thumb_metacarpal', 'thumb_proximal', 'thumb_distal', 'thumb_tip',
          'index_metacarpal', 'index_proximal', 'index_intermediate', 'index_distal', 'index_tip',
          'middle_metacarpal', 'middle_proximal', 'middle_intermediate', 'middle_distal', 'middle_tip',
          'ring_metacarpal', 'ring_proximal', 'ring_intermediate', 'ring_distal', 'ring_tip',
          'little_metacarpal', 'little_proximal', 'little_intermediate', 'little_distal', 'little_tip']


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    aa, release = '--aa' in sys.argv, '--release' in sys.argv
    assets, data = Path(args[0]), Path(args[1])
    v6 = assets / 'v6-original/exports/eduke32'
    out, notes = [], []
    private_used = []

    def link(source, name):
        target = data / name
        if target.is_symlink() or target.exists():
            target.unlink()
        target.symlink_to(source)

    def model(md3, png, tile, name, frame='rest'):
        link(md3, name + '.md3')
        link(png, name + '.png')
        glow = png.with_name(png.stem + '_glow.png')
        if glow.is_file():
            link(glow, name + '_glow.png')
        surfaces = struct.unpack_from('<i', md3.read_bytes(), 84)[0]
        out.append(f'model "{name}.md3" {{\n scale 1.0')
        for surface in range(surfaces):
            out.append(f' skin {{ pal 0 surface {surface} file "{name}.png" }}')
            if glow.is_file():
                out.append(f' glow {{ pal 0 surface {surface} file "{name}_glow.png" }}')
        out.append(f' frame {{ name "{frame}" tile {tile} smoothduration 0 }}\n}}')

    def pick(label, candidates):
        """First existing (md3, png, private) candidate."""
        for md3, png, private in candidates:
            if private and release:
                continue
            if md3.is_file() and png.is_file():
                if private:
                    private_used.append(label)
                notes.append(f'{label}: {md3}')
                return md3, png
        notes.append(f'{label}: none')
        return None

    # Single-mesh hands (controller fallback when no segmented rig).
    for side, tile in (('left', 30010), ('right', 30011)):
        old = assets / 'aa-v3-hands-grip/exports/eduke32/aa_assets'
        chosen = pick(f'hand {side}', [(v6 / f'vr_hand_{side}.md3', v6 / f'vr_hand_{side}.png', False),
                                       (old / f'hand_{side}.md3', old / f'hand_{side}.png', True)])
        if chosen:
            model(*chosen, tile, f'vr_hand_{side}')

    chosen = pick('body', [(v6 / 'vr_body.md3', v6 / 'vr_body.png', False),
                           (assets / 'v5-vanilla/exports/eduke32/vr_body.md3', assets / 'v5-vanilla/exports/eduke32/vr_body.png', True)])
    if chosen:
        model(*chosen, 30040, 'vr_body')

    holds = []
    if aa:
        out.insert(0, 'include "duke3d.def"')
        inventory = assets / 'aa-v1/metadata/arsenal_inventory.json'
        families = json.loads(inventory.read_text())['families'] if inventory.is_file() else []
        hud = []
        for index, family in enumerate(families):
            fid = family['id']
            paths = family.get('paths') or {}
            old_md3, old_png = assets / 'aa-v1' / paths.get('md3', 'missing'), assets / 'aa-v1' / paths.get('png', 'missing')
            chosen = pick(f'aa {fid}', [(v6 / f'aa/{fid}.md3', v6 / f'aa/{fid}.png', False), (old_md3, old_png, True)])
            if not chosen:
                continue
            tile = 30100 + index
            model(*chosen, tile, f'vr_aa_{index}')
            hud += [f'{t} {tile}' for t in family.get('reference_tiles', [])]
            holds.append((tile, f'hold_{fid}'))
        (data / 'hud-model-map.txt').write_text('\n'.join(hud) + '\n')
    else:
        old_pistol = assets / 'pistol-palm-mount/stock/exports/eduke32/duke_assets'
        for index, name in WEAPONS.items():
            v5 = assets / 'v5-vanilla/exports/eduke32'
            candidates = [(v6 / f'vr_{name}.md3', v6 / f'vr_{name}.png', False),
                          (v5 / f'vr_{name}.md3', v5 / f'vr_{name}.png', True)]
            if index == 1:
                candidates.append((old_pistol / 'pistol.md3', old_pistol / 'pistol.png', True))
            chosen = pick(name, candidates)
            if not chosen:
                continue
            tile = 21 if index == 1 else 30020 + index
            model(*chosen, tile, 'vr_pistol' if index == 1 else f'vr_held_{index}')
            holds.append((tile, f'hold_{name}'))

    # Finger-tracking hand rig (original assets only).
    rig_lines = []
    flat = v6.parent.parent / 'metadata/hand_poses_flat.json'
    if flat.is_file():
        rig = json.loads(flat.read_text())
        order = [name.lower().replace('xr_hand_joint_', '').replace('_ext', '') for name in rig.get('joint_order', JOINTS)]
        segments = rig.get('segments', {})
        for side_index, side in enumerate(('left', 'right')):
            for segment_index, (segment, info) in enumerate(sorted(segments.items())):
                md3 = v6 / f'hands/vr_hand_{side}_{segment}.md3'
                png = v6 / f'hands/vr_hand_{side}.png'
                joint = info.get('joint', '').lower().replace('xr_hand_joint_', '').replace('_ext', '')
                if not md3.is_file() or not png.is_file() or joint not in order:
                    continue
                tile = 30200 + side_index * 32 + segment_index
                model(md3, png, tile, f'vr_hand_{side}_{segment}')
                rig_lines.append(f'segment {side_index} {tile} {order.index(joint)}')
            for pose, value in rig.get('poses', {}).get(side, {}).items():
                frame = 1 if str(value.get('frame', 'grip')).startswith('weapon') else 0
                joints = value.get('joints', [])
                if len(joints) != 26:
                    continue
                rig_lines.append(f'pose {side_index} {pose} {frame}')
                rig_lines += [' '.join(f'{x:.6f}' for x in joint) for joint in joints]
        rig_lines += [f'hold {tile} {name}' for tile, name in holds]
    (data / 'hand-rig.txt').write_text('\n'.join(rig_lines) + '\n')

    print('\n'.join(out))
    for note in notes:
        print('eduke32-vr-play:', note, file=sys.stderr)
    if private_used:
        print('eduke32-vr-play: WARNING: using non-redistributable private fallback assets for: '
              + ', '.join(sorted(set(private_used))) + ' (use --release to exclude them).', file=sys.stderr)


if __name__ == '__main__':
    main()
