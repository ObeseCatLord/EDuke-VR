#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Write the deterministic v7 Build map used by the native/stereo oracle.

The binary layout is deliberately encoded here from buildtypes.h (40-byte v7
sectors, 32-byte walls, 44-byte sprites) and engine.cpp's saveboard() order.
The map has a portal from the start room into a second room, plus a stationary
BOTTLE1 (Duke tile 954) just off the portal centreline.  It contains no actors,
sector effects or moving geometry. Optional scenes replace the ceiling/floor
with the native LA parallax sky.
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


def sector(wallptr: int, wallnum: int, sky_ceiling=False, sky_floor=False) -> bytes:
    # sectortypev7, source/build/include/buildtypes.h: 40 bytes.
    return struct.pack(
        "<hhiiHHhhbBBBhhbBBBBBhhh",
        wallptr, wallnum, -16384, 0, int(sky_ceiling), int(sky_floor),
        SKY_TILE if sky_ceiling else WALL_TILE, 0, 0, 0, 17 if sky_ceiling else 0, 9 if sky_ceiling else 0,
        SKY_TILE if sky_floor else WALL_TILE, 0, 0, 0, 17 if sky_floor else 0, 9 if sky_floor else 0, 0, 0, 0, 0, -1,
    )


def wall(x: int, y: int, point2: int, nextwall: int = -1, nextsector: int = -1,
         shade: int = 0, palette: int = 0) -> bytes:
    # walltypev7, source/build/include/buildtypes.h: 32 bytes.
    return struct.pack(
        "<iihhhHhhbBBBBBhhh",
        x, y, point2, nextwall, nextsector, 0, WALL_TILE, 0, shade, palette, 32, 32,
        0, 0, 0, 0, -1,
    )


def sprite(x: int, y: int, z: int, sectnum: int) -> bytes:
    # spritetypev7, source/build/include/buildtypes.h: 44 bytes.  statnum=0
    # keeps this ordinary decoration in the world; BOTTLE1 has no enemy AI.
    return struct.pack(
        "<iiiHhbBBBBBbbhhhhhhhhhh",
        x, y, z,                 # position
        0, BOTTLE_TILE, 0,       # cstat, picnum, shade
        0, 32, 0, 24, 48,        # palette, clipping, blend, scale
        0, 0,                    # offsets
        sectnum, 0, 0, -1,       # sector, status, angle, owner
        0, 0, 0, 0, 0, -1,       # velocity, tags, extra
    )


def build_map(scene="room") -> bytes:
    if scene not in ("room", "sky", "sky-floor"):
        raise ValueError("unknown fixture scene")
    # A six-wall first room with a portal only in its middle east-wall span.
    # Wall 2 and wall 6 are exact reversed twins, required by Build portals.
    # Alternating native palette/shade inputs exercise state changes before
    # the ordinary bottle mask returns to palette/shade zero after replay.
    walls = [
        wall(0, 0, 1), wall(4096, 0, 2, shade=10, palette=1), wall(4096, 1536, 3, 6, 1),
        wall(4096, 2560, 4), wall(4096, 4096, 5, shade=10, palette=1), wall(0, 4096, 0),
        wall(4096, 2560, 7, 2, 0), wall(4096, 1536, 8),
        wall(8192, 0, 9, shade=10, palette=1), wall(8192, 4096, 6),
    ]
    # The bottle is deliberately near the portal edge: it is visible from the
    # centred native start and gives an eye-membership test a stable boundary.
    sprites = [sprite(4700, 1700, 0, 1)]
    header = struct.pack("<iiiihh", VERSION, 1024, 2048, -PHEIGHT, 0, 0)
    return b"".join((
        header, struct.pack("<h", 2),
        sector(0, 6, scene == "sky", scene == "sky-floor"),
        sector(6, 4, scene == "sky", scene == "sky-floor"),
        struct.pack("<h", len(walls)), *walls,
        struct.pack("<h", len(sprites)), *sprites,
    ))


def generate(directory: Path, scene="room") -> Path:
    """Generate ``stereo_fixture.map`` in *directory* and return its path.

    This is intentionally a small public API for the native/XR comparison
    harness. It has no dependency on a local GRP: the caller supplies the
    owned GRP and ``fixtures/stereo_test.con`` at launch time.
    """
    data = build_map(scene)
    if len(data) != 20 + 2 + 2 * 40 + 2 + 10 * 32 + 2 + 44:
        raise AssertionError("v7 fixture size no longer matches source layouts")
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "stereo_fixture.map"
    output.write_bytes(data)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="output .map path")
    parser.add_argument("--scene", choices=("room", "sky", "sky-floor"), default="room")
    args = parser.parse_args()
    output = generate(args.output.parent, args.scene)
    if output != args.output:
        output.replace(args.output)
    print(f"wrote {args.output} ({args.output.stat().st_size} bytes, v7, 2 sectors, 10 walls, 1 sprite)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
