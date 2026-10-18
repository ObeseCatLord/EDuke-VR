#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Write the deterministic v7 Build map used by the native/stereo oracle.

The binary layout is deliberately encoded here from buildtypes.h (40-byte v7
sectors, 32-byte walls, 44-byte sprites) and engine.cpp's saveboard() order.
The map has a portal from the start room into a second room, plus a stationary
BOTTLE1 (Duke tile 954) just off the portal centreline.  It contains no actors,
sector effects or moving geometry. Optional scenes replace the ceiling/floor
with the native LA parallax sky, or add indexed ART masks/translucency.
The animated mask scene includes native DEF animation and alpha-cutoff inputs.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import struct

PHEIGHT = 38 << 8
VERSION = 7
WALL_TILE = 293  # W_TECHWALL1, declared by the stock DEFS.CON.
BOTTLE_TILE = 954  # BOTTLE1, declared by the stock DEFS.CON.
SKY_TILE = 89  # LA, native eight-panel sky configured by G_InitMultiPsky.
MASK_TILE = 285  # MASKWALL1, indexed ART with transparent texels.


def sector(wallptr: int, wallnum: int, sky_ceiling=False, sky_floor=False, *,
           ceiling_shade=None, ceiling_palette=None, floor_shade=None,
           floor_palette=None, visibility=0) -> bytes:
    # sectortypev7, source/build/include/buildtypes.h: 40 bytes.
    return struct.pack(
        "<hhiiHHhhbBBBhhbBBBBBhhh",
        wallptr, wallnum, -16384, 0, int(sky_ceiling), int(sky_floor),
        # shade/palette precede x/y panning.  Preserve the old scenes' 17/9
        # panning bytes exactly; only the new private skybox scene overrides
        # the actual shade/palette fields.
        SKY_TILE if sky_ceiling else WALL_TILE, 0,
        0 if ceiling_shade is None else ceiling_shade,
        0 if ceiling_palette is None else ceiling_palette,
        17 if sky_ceiling else 0, 9 if sky_ceiling else 0,
        SKY_TILE if sky_floor else WALL_TILE, 0,
        0 if floor_shade is None else floor_shade,
        0 if floor_palette is None else floor_palette,
        17 if sky_floor else 0, 9 if sky_floor else 0,
        visibility, 0, 0, 0, -1,
    )


def wall(x: int, y: int, point2: int, nextwall: int = -1, nextsector: int = -1,
         shade: int = 0, palette: int = 0, cstat: int = 0) -> bytes:
    # walltypev7, source/build/include/buildtypes.h: 32 bytes.
    return struct.pack(
        "<iihhhHhhbBBBBBhhh",
        x, y, point2, nextwall, nextsector, cstat, WALL_TILE, MASK_TILE if cstat else 0, shade, palette, 32, 32,
        0, 0, 0, 0, -1,
    )


def sprite(x: int, y: int, z: int, sectnum: int, *, cstat=0, tile=BOTTLE_TILE,
           palette=0, angle=0, xrepeat=24, yrepeat=48) -> bytes:
    # spritetypev7, source/build/include/buildtypes.h: 44 bytes.  statnum=0
    # keeps this ordinary decoration in the world; BOTTLE1 has no enemy AI.
    return struct.pack(
        "<iiiHhbBBBBBbbhhhhhhhhhh",
        x, y, z,                 # position
        cstat, tile, 0,          # cstat, picnum, shade
        palette, 32, 0, xrepeat, yrepeat,  # palette, clipping, blend, scale
        0, 0,                    # offsets
        sectnum, 0, angle, -1,   # sector, status, angle, owner
        0, 0, 0, 0, 0, -1,       # velocity, tags, extra
    )


def build_map(scene="room") -> bytes:
    if scene not in ("room", "sky", "sky-floor", "skybox", "skybox-ceiling-fog-control",
                     "skybox-floor-fog-control", "masks", "masks-animated"):
        raise ValueError("unknown fixture scene")
    # A six-wall first room with a portal only in its middle east-wall span.
    # Wall 2 and wall 6 are exact reversed twins, required by Build portals.
    # Alternating native palette/shade inputs exercise state changes before
    # the ordinary bottle mask returns to palette/shade zero after replay.
    walls = [
        wall(0, 0, 1), wall(4096, 0, 2, shade=10, palette=1),
        wall(4096, 1536, 3, 6, 1, cstat=(16 | (128 if scene == "masks-animated" else 0)) if scene.startswith("masks") else 0),
        wall(4096, 2560, 4), wall(4096, 4096, 5, shade=10, palette=1), wall(0, 4096, 0),
        wall(4096, 2560, 7, 2, 0, cstat=(16 | (128 if scene == "masks-animated" else 0)) if scene.startswith("masks") else 0), wall(4096, 1536, 8),
        wall(8192, 0, 9, shade=10, palette=1), wall(8192, 4096, 6),
    ]
    # The bottle is deliberately near the portal edge: it is visible from the
    # centred native start and gives an eye-membership test a stable boundary.
    sprites = [sprite(4700, 1700, 0, 1)]
    if scene.startswith("masks"):
        # cstat bits are the native buildtypes.h enums: translucent=2,
        # wall alignment=16, floor alignment=32, inverse translucent=512.
        # Identical-position floor sprites exercise the native equal-depth
        # color/depth-only group. All are ordinary, stationary decorations.
        sprites += [
            sprite(2300, 1700, 0, 0),
            sprite(3000, 2020, -1500, 0, cstat=2, palette=1),
            sprite(3100, 2100, -1500, 0, cstat=2 | 512),
            sprite(3500, 2400, -2048, 0, cstat=16, tile=MASK_TILE, angle=512, xrepeat=32, yrepeat=32),
            sprite(2800, 2100, -4096, 0, cstat=32, tile=MASK_TILE, xrepeat=32, yrepeat=32),
            sprite(2800, 2100, -4096, 0, cstat=32, tile=MASK_TILE, palette=1, xrepeat=32, yrepeat=32),
            sprite(3400, 1900, -3072, 0, cstat=32 | 2, tile=MASK_TILE, xrepeat=32, yrepeat=32),
        ]
    if scene.startswith("skybox"):
        # The two regions deliberately share tile 89 but have different native
        # ceiling/floor palette, shade and visibility inputs.  The portal puts
        # the remote floor and local ceiling in one camera view.  Controls vary
        # only visibility, so their native pixel deltas demonstrate fog input
        # ownership without treating the mode-4 sky blend as a distance ramp.
        ceiling_visibility = 32 if scene != "skybox-ceiling-fog-control" else 160
        # Shade 24 / visibility 96 clamps to fully black native mode-4 fog.
        # Keep visibility 16 in the baseline so the remote floor contributes
        # visible sky pixels alongside the ceiling before the control hides it.
        floor_visibility = 16 if scene != "skybox-floor-fog-control" else 96
        sectors = (
            sector(0, 6, True, False, ceiling_shade=8, ceiling_palette=0,
                   visibility=ceiling_visibility),
            sector(6, 4, False, True, floor_shade=24, floor_palette=1,
                   visibility=floor_visibility),
        )
    else:
        sectors = (
            sector(0, 6, scene == "sky", scene == "sky-floor"),
            sector(6, 4, scene == "sky", scene == "sky-floor"),
        )
    header = struct.pack("<iiiihh", VERSION, 1024, 2048, -PHEIGHT, 0, 0)
    return b"".join((
        header, struct.pack("<h", 2),
        *sectors,
        struct.pack("<h", len(walls)), *walls,
        struct.pack("<h", len(sprites)), *sprites,
    ))


def _assert_sector_layout() -> None:
    """Keep the v7 byte layout honest without relying on a renderer run."""
    # Exact byte equivalence with the pre-skybox packer for every old form.
    def legacy(wallptr, wallnum, sky_ceiling=False, sky_floor=False):
        return struct.pack(
            "<hhiiHHhhbBBBhhbBBBBBhhh",
            wallptr, wallnum, -16384, 0, int(sky_ceiling), int(sky_floor),
            SKY_TILE if sky_ceiling else WALL_TILE, 0, 0, 0, 17 if sky_ceiling else 0, 9 if sky_ceiling else 0,
            SKY_TILE if sky_floor else WALL_TILE, 0, 0, 0, 17 if sky_floor else 0, 9 if sky_floor else 0,
            0, 0, 0, 0, -1)
    for ceiling, floor in ((False, False), (True, False), (False, True), (True, True)):
        assert sector(6, 4, ceiling, floor) == legacy(6, 4, ceiling, floor)

    # struct unpack indexes are the actual v7 sector field order, not byte
    # guesses: ceiling shade/palette 8/9, floor shade/palette 14/15.
    first = struct.unpack_from("<hhiiHHhhbBBBhhbBBBBBhhh", build_map("skybox"), 22)
    second = struct.unpack_from("<hhiiHHhhbBBBhhbBBBBBhhh", build_map("skybox"), 62)
    assert (first[6], first[8], first[9], first[10], first[11], first[18]) == (SKY_TILE, 8, 0, 17, 9, 32)
    assert (second[12], second[14], second[15], second[16], second[17], second[18]) == (SKY_TILE, 24, 1, 17, 9, 16)


_assert_sector_layout()


def generate(directory: Path, scene="room") -> Path:
    """Generate ``stereo_fixture.map`` in *directory* and return its path.

    This is intentionally a small public API for the native/XR comparison
    harness. It has no dependency on a local GRP: the caller supplies the
    owned GRP and ``fixtures/stereo_test.con`` at launch time.
    """
    data = build_map(scene)
    count = 8 if scene.startswith("masks") else 1
    if len(data) != 20 + 2 + 2 * 40 + 2 + 10 * 32 + 2 + count * 44:
        raise AssertionError("v7 fixture size no longer matches source layouts")
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "stereo_fixture.map"
    output.write_bytes(data)
    # Consecutive native animation bases deliberately mutate picnum again in
    # an equal-depth group's second (depth-only) pass. Clock=1 selects +1.
    (directory / "stereo_fixture.def").write_text(
        "animtilerange 285 286 0 2\nanimtilerange 286 287 0 2\n"
        "alphahackrange 285 287 0.25\n" if scene == "masks-animated" else "// native ART defaults\n")
    (directory / "stereo_map.con").write_text(f"define VRFIXTURE_SPRITES {count}\n")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="output .map path")
    parser.add_argument("--scene", choices=("room", "sky", "sky-floor", "skybox",
                                               "skybox-ceiling-fog-control", "skybox-floor-fog-control",
                                               "masks", "masks-animated"), default="room")
    args = parser.parse_args()
    output = generate(args.output.parent, args.scene)
    if output != args.output:
        output.replace(args.output)
    print(f"wrote {args.output} ({args.output.stat().st_size} bytes, v7, 2 sectors, 10 walls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
