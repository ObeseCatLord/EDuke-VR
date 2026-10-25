#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Assemble the EDuke32 VR model DEF, hand rig and HUD-tile map.

Usage: build_vr_def.py ASSETS DATA [--aa] [--release] [--glow] [--pack=NAME]
       build_vr_def.py ASSETS --list-packs [--release]

ASSETS is the duke-vr-assets checkout, DATA the private output directory (the
game's -j search path). Prints the DEF to stdout and writes DATA/hand-rig.txt
and DATA/hud-model-map.txt; reports the chosen sources on stderr.

Sources in priority order:
  v6-original       original, redistributable models (always preferred)
  private fallbacks older packages that contain or derive from commercial
                    game data (Duke Nukem Forever); local use only, never with
                    --release
Tiles: 21 stock pistol, 30020+weapon held weapons, 30010/30011 single-mesh
hands, 30020 mighty foot boot, 30060 aiming laser, 30061-30064 wheel parts, 30066 first-person body (torso/legs), 30067 full IK body, 30266+side wrist-cut hands, 30270+pchar*2+side character hands, APLAYER (1405+) Duke for both third and first person (torso/legs),
30100+family AA held weapons,
30200+side*32+segment finger-tracking hand segments, 30264+side single-shell hands.
"""
import json
import struct
import sys
from pathlib import Path

BASE, LEGACY = 'v7-original', 'v6-original'   # the original set, and the older one it replaces part by part

WEAPONS = {1: 'pistol', 2: 'shotgun', 3: 'chaingun', 4: 'rpg', 5: 'pipebomb', 6: 'shrinker', 7: 'devastator',
           8: 'tripbomb', 9: 'freezer', 10: 'detonator', 11: 'expander', 12: 'flamethrower'}
JOINTS = ['palm', 'wrist', 'thumb_metacarpal', 'thumb_proximal', 'thumb_distal', 'thumb_tip',
          'index_metacarpal', 'index_proximal', 'index_intermediate', 'index_distal', 'index_tip',
          'middle_metacarpal', 'middle_proximal', 'middle_intermediate', 'middle_distal', 'middle_tip',
          'ring_metacarpal', 'ring_proximal', 'ring_intermediate', 'ring_distal', 'ring_tip',
          'little_metacarpal', 'little_proximal', 'little_intermediate', 'little_distal', 'little_tip']


def list_packs(assets, release):
    """Installed model sets as NAME=TITLE=DIRECTORY lines: every directory with a pack.json and
    exports/eduke32 (private ones left out with --release, and any a listed pack "supersedes");
    the defaults first (the built Voxel Duke, then the low-res and full original sets)."""
    packs = []
    for root in sorted(p for p in assets.iterdir() if not p.name.startswith('.')   # builders' staging folders
                       and (p / 'exports/eduke32').is_dir() and (p / 'pack.json').is_file()):
        info = json.loads((root / 'pack.json').read_text())
        if release and info.get('redistributable') is False:
            continue
        packs.append((info.get('name', root.name), root, info))
    superseded = {name for _, _, info in packs for name in info.get('supersedes', [])}
    rank = {'voxel': 0, 'original-lowres': 1, 'original': 2}
    for name, root, info in sorted(packs, key=lambda p: (rank.get(p[0], 3), p[1].name)):
        if name in superseded or root.name in superseded:
            continue
        title = (info.get('title') or root.name).replace(';', ',').replace('=', '-')
        print(f"{name}={title}={root.name}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    aa, release = '--aa' in sys.argv, '--release' in sys.argv
    if '--list-packs' in sys.argv:
        return list_packs(Path(args[0]), release)
    # Glow maps make the headset draw every VR model once per eye instead of once for both
    # (multiview); the parts that must glow (laser, wheel pointer and beam) are drawn fullbright.
    glow_maps = '--glow' in sys.argv
    assets, data = Path(args[0]), Path(args[1])
    # --pack NAME: a model pack beside v6-original (e.g. a private one); any file it lacks comes
    # from v6-original, so a pack may replace only some models.
    pack_name = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--pack=')), BASE)
    pack_root = assets / pack_name
    if pack_name not in (BASE, LEGACY) and not pack_root.is_dir():
        sys.exit(f'build_vr_def: no model pack {pack_root}')
    pack_info = json.loads((pack_root / 'pack.json').read_text()) if (pack_root / 'pack.json').is_file() else {}
    if release and pack_info.get('redistributable') is False:
        sys.exit(f'build_vr_def: pack {pack_name} is not redistributable')

    class PackDir(type(Path())):
        """exports/eduke32 of the chosen pack, falling back file by file to v7-original, then to the
        legacy v6-original for parts not remade yet."""
        def __truediv__(self, rel):
            for root in (pack_root, assets / BASE, assets / LEGACY):
                chosen = root / 'exports/eduke32' / rel
                if chosen.exists():
                    return chosen
            return chosen

    v6 = PackDir(pack_root / 'exports/eduke32')
    out, notes = [], []
    if pack_name not in (BASE, LEGACY):
        notes.append(f'model pack: {pack_name}' + (' (PRIVATE, not redistributable)' if pack_info.get('redistributable') is False else ''))
    # Pack-wide texture filter (e.g. "nearest": no filtering at all) for the launcher.
    (data / 'pack-filter.txt').write_text(pack_info.get('texture_filter', '') + '\n')
    # Extra game data the pack wants loaded (e.g. a voxel world mod), only for the games it lists.
    games = pack_info.get('games', ['duke3d', 'aa566'])
    autoload = [str((pack_root / rel).resolve()) for rel in pack_info.get('autoload', [])
                if (pack_root / rel).is_file() and ('aa566' if aa else 'duke3d') in games]
    (data / 'pack-autoload.txt').write_text(''.join(path + '\n' for path in autoload))
    if autoload:
        notes.append('pack autoload: ' + ', '.join(Path(a).name for a in autoload))
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
        if not glow_maps:
            glow = Path('/nonexistent')
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

    # Aiming laser beam (vr_laser), drawn by the engine from the muzzle to the aim point.
    if (v6 / 'vr_laser.md3').is_file() and (v6 / 'vr_laser.png').is_file():
        model(v6 / 'vr_laser.md3', v6 / 'vr_laser.png', 30060, 'vr_laser')
        notes.append(f'laser: {v6 / "vr_laser.md3"}')

    # Weapon/gadget wheel parts (Q3VR-style selector): slot bubble, hovered bubble, pointer, beam.
    for tile, name in ((30061, 'vr_wheel_bubble'), (30062, 'vr_wheel_bubble_lit'), (30063, 'vr_wheel_pointer'),
                       (30064, 'vr_wheel_beam')):
        if (v6 / f'{name}.md3').is_file() and (v6 / f'{name}.png').is_file():
            model(v6 / f'{name}.md3', v6 / f'{name}.png', tile, name)

    # Mighty Foot boot (vr_boot) on the held-weapon tile of weapon 0 (KNEE_WEAPON), drawn by the
    # engine during kicks.
    if (v6 / 'vr_boot.md3').is_file() and (v6 / 'vr_boot.png').is_file():
        model(v6 / 'vr_boot.md3', v6 / 'vr_boot.png', 30020, 'vr_boot')
        notes.append(f'boot: {v6 / "vr_boot.md3"}')

    # Third-person Duke for other players: native APLAYER (1405) action tiles,
    # from the stock GAME.CON actions (start, frames, 5 view angles each).
    duke_md3, duke_png = v6 / 'vr_duke.md3', v6 / 'vr_duke.png'
    # Duke-character players only: other characters (e.g. Alien Armageddon's Bombshell) use their own
    # player tiles and keep their native sprites in multiplayer and mirrors.
    if duke_md3.is_file() and duke_png.is_file():
        actions = [  # (first tile offset, frame names) — later entries win on shared art
            (0, ['stand']), (40, ['stand', 'stand']), (20, ['walk_01', 'walk_02', 'walk_03', 'walk_04']),
            (45, ['walk_04', 'walk_03', 'walk_02', 'walk_01']), (50, ['jump'] * 4), (15, ['jump']), (65, ['fall']),
            (86, ['crouch', 'crouch_walk_01', 'crouch_walk_02']), (375, ['swim_01', 'swim_02', 'swim_03', 'swim_04']),
            (395, ['swim_01', 'swim_02'])]
        tiles = {}
        for start, names in actions:
            for frame, name in enumerate(names):
                for angle in range(5):
                    tiles[1405 + start + frame * 5 + angle] = name
        for frame, name in enumerate(['die_01', 'die_02', 'die_03', 'die_04', 'die_05']):
            tiles[1405 + 106 + frame] = name
        tiles[1405 + 113] = 'dead'
        link(duke_md3, 'vr_duke.md3')
        link(duke_png, 'vr_duke.png')
        frames = set()
        data_md3 = duke_md3.read_bytes()
        count, offset = struct.unpack_from('<i', data_md3, 76)[0], struct.unpack_from('<i', data_md3, 92)[0]
        for index in range(count):
            frames.add(data_md3[offset + index * 56 + 40:offset + index * 56 + 56].split(b'\0')[0].decode())
        surfaces = struct.unpack_from('<i', data_md3, 84)[0]
        # Polymost draws a model unit as 0.16*xrepeat xy and 2.56*yrepeat z
        # Build units times the DEF scale. With Duke's 42x36 repeat and scale
        # 1.0 the 117-unit (64/m) model stands 1.76 m with its eyes ~5 cm
        # above the native eye height (PHEIGHT); xy is ~12% wider, matching
        # the original sprite's aspect.
        out.append('model "vr_duke.md3" {\n scale 1.0')
        for surface in range(surfaces):
            out.append(f' skin {{ pal 0 surface {surface} file "vr_duke.png" }}')
        for tile, name in sorted(tiles.items()):
            # Multi-surface players hide parts by collapsing them: no blending between frames.
            out.append(f' frame {{ name "{name if name in frames else "stand"}" tile {tile} smoothduration {0 if surfaces > 1 else 0.1} }}')
        out.append('}')
        notes.append(f'player model: {duke_md3} ({len(tiles)} tiles)')
        # First-person body: Duke's torso and legs as their own single shell (same frames).
        body_md3 = v6 / 'vr_duke_body.md3'
        body_png = v6 / 'vr_duke_body.png'
        if not body_png.is_file():
            body_png = duke_png
        if body_md3.is_file():
            model(body_md3, body_png, 30066, 'vr_duke_body', frame='stand')

    holds = []
    if autoload and not aa:
        # The world data a pack autoloads (e.g. voxels and map hacks) comes with its own duke3d.def.
        out.insert(0, 'include "duke3d.def"')
    if aa:
        out.insert(0, 'include "duke3d.def"')
        # Family ids and AA HUD tile numbers; v6 ships its own copy.
        inventory = pack_root / 'metadata/aa_inventory.json'
        if not inventory.is_file():
            inventory = assets / 'v6-original/metadata/aa_inventory.json'
        if not inventory.is_file():
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
    flat = next((root / 'metadata/hand_poses_flat.json' for root in (pack_root, assets / BASE, assets / LEGACY)
                 if (root / 'metadata/hand_poses_flat.json').is_file()), assets / LEGACY / 'metadata/hand_poses_flat.json')
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
            # Single-shell hand (one skinned mesh, drawn instead of the segments when present).
            shell = {ext: v6 / f'hands/vr_hand_{side}_shell{ext}' for ext in ('.md3', '.png', '.skin')}
            if all(path.is_file() for path in shell.values()):
                tile = 30264 + side_index
                model(shell['.md3'], shell['.png'], tile, f'vr_hand_{side}_shell', frame='bind')
                link(shell['.skin'], f'vr_hand_{side}_shell.skin')
                rig_lines.append(f'shell {side_index} {tile} vr_hand_{side}_shell.skin')
            wrist = {ext: v6 / f'hands/vr_hand_{side}_shell_wrist{ext}' for ext in ('.md3', '.png', '.skin')}
            # A pack whose own shell is cut from its body at the wrist (and has no separate wrist
            # cut) uses that shell for the full body, never another pack's wrist cut.
            own = pack_root / 'exports/eduke32/hands'
            if (own / f'vr_hand_{side}_shell.md3').is_file() and not (own / f'vr_hand_{side}_shell_wrist.md3').is_file():
                wrist = shell
            if all(path.is_file() for path in wrist.values()):
                tile = 30266 + side_index
                model(wrist['.md3'], wrist['.png'], tile, f'vr_hand_{side}_shell_wrist', frame='bind')
                link(wrist['.skin'], f'vr_hand_{side}_shell_wrist.skin')
                rig_lines.append(f'shellwrist {side_index} {tile} vr_hand_{side}_shell_wrist.skin')
        # True full body (IK skeleton + skin + head/hand vertex lists).
        ik = {ext: v6 / f'vr_duke_ik{ext}' for ext in ('.md3', '.png', '.skel', '.skin', '.headverts', '.handverts_l', '.handverts_r')}
        # First person hides .fphide (head and neck, closed by inner caps) when the pack has it.
        if (v6 / 'vr_duke_ik.fphide').is_file():
            ik['.headverts'] = v6 / 'vr_duke_ik.fphide'
        if all(path.is_file() for path in ik.values()):
            model(ik['.md3'], ik['.png'], 30067, 'vr_duke_ik', frame='bind')
            for ext in ('.skel', '.skin', '.headverts', '.handverts_l', '.handverts_r'):
                link(ik[ext], 'vr_duke_ik' + ext)
            rig_lines.append('ikbody 30067 ' + ' '.join('vr_duke_ik' + ext
                                                        for ext in ('.skel', '.skin', '.headverts', '.handverts_l', '.handverts_r')))
            notes.append(f'full body: {ik[".md3"]}')
            # A pack whose own body includes the hands (pack.json "ik_hands"): the engine poses its
            # finger bones and draws no separate hand shells with it.
            if pack_info.get('ik_hands') and (pack_root / 'exports/eduke32/vr_duke_ik.md3').is_file():
                rig_lines.append('ikhands')
                notes.append('full body: own hands')
        # Per-character hands (Alien Armageddon's pchar 1..4) from the pack's characters.json.
        chars = pack_root / 'metadata/characters.json'
        if aa and chars.is_file():
            for name, info in json.loads(chars.read_text()).items():
                pchar = int(info.get('pchar', 0))
                if not 0 < pchar < 8:
                    continue
                for side_index, side in enumerate(('left', 'right')):
                    stem = pack_root / 'exports/eduke32/characters' / name / 'hands' / f'vr_hand_{side}_shell'
                    files = {ext: stem.with_name(stem.name + ext) for ext in ('.md3', '.png', '.skin')}
                    if not all(path.is_file() for path in files.values()):
                        continue
                    tile = 30270 + pchar * 2 + side_index
                    label = f'vr_hand_{side}_{name}'
                    model(files['.md3'], files['.png'], tile, label, frame='bind')
                    link(files['.skin'], label + '.skin')
                    rig_lines.append(f'charshell {pchar} {side_index} {tile} {label}.skin')
                notes.append(f'character hands: {name} (pchar {pchar})')
        rig_lines += [f'hold {tile} {name}' for tile, name in holds]
        # Two-handed aiming: the off hand's support grip on the same model, when the pack solved one.
        posed = rig.get('poses', {})
        rig_lines += [f'support {tile} support_{name[5:]}' for tile, name in holds
                      if all(f'support_{name[5:]}' in posed.get(side, {}) for side in ('left', 'right'))]
    (data / 'hand-rig.txt').write_text('\n'.join(rig_lines) + '\n')

    # Tipping: a wad of bills made from the game's own MONEY art in the user's GRP (--grp=PATH).
    grps = [a.split('=', 1)[1] for a in sys.argv if a.startswith('--grp=')]
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import money_wad
    if grps and money_wad.build(grps, data):
        out.append('model "vr_money.md3" {\n scale 1.0\n skin { pal 0 surface 0 file "vr_money.png" }\n'
                   ' frame { name "rest" tile 30068 smoothduration 0 }\n}')
        notes.append('money wad: MONEY art from ' + Path(grps[0]).name)

    print('\n'.join(out))
    for note in notes:
        print('eduke32-vr-play:', note, file=sys.stderr)
    if private_used:
        print('eduke32-vr-play: WARNING: using non-redistributable private fallback assets for: '
              + ', '.join(sorted(set(private_used))) + ' (use --release to exclude them).', file=sys.stderr)


if __name__ == '__main__':
    main()
