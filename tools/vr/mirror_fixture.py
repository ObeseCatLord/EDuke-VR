#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Write a v7 Build map: one room whose east wall holds a Duke mirror.

Sector 0 (8192x8192) has a one-way wall with overpicnum MIRROR (560) leading
to a small dummy sector 1, which is how Duke maps declare mirrors
(premap.cpp G_SetupSpecialWalls). The player starts facing the mirror; a
bottle stands beside the start so the reflection has a distinct object.
"""
import argparse
import struct
from pathlib import Path

from stereo_fixture import sector, sprite, PHEIGHT

MIRROR, WALL = 560, 293


def wall(x, y, point2, nextwall=-1, nextsector=-1, cstat=0, overpicnum=0, shade=0):
    return struct.pack('<iihhhHhhbBBBBBhhh', x, y, point2, nextwall, nextsector, cstat,
                       WALL, overpicnum, shade, 0, 32, 32, 0, 0, 0, 0, -1)


def build(start_x=2048, angle=0) -> bytes:
    walls = [wall(0, 0, 1, shade=8), wall(8192, 0, 2),
             wall(8192, 3072, 3, 9, 1, cstat=32, overpicnum=MIRROR),
             wall(8192, 5120, 4), wall(8192, 8192, 5, shade=8), wall(0, 8192, 0, shade=16),
             wall(8192, 3072, 7), wall(8704, 3072, 8), wall(8704, 5120, 9),
             wall(8192, 5120, 6, 2, 0)]
    sectors = sector(0, 6) + sector(6, 4)
    sprites = [sprite(start_x, 4096, 0, 0, tile=1405, angle=angle),
               sprite(4096, 3400, 0, 0, xrepeat=48, yrepeat=96)]
    header = struct.pack('<iiiihhh', 7, start_x, 4096, -PHEIGHT, angle, 0, 2)
    return (header + sectors + struct.pack('<h', len(walls)) + b''.join(walls)
            + struct.pack('<h', len(sprites)) + b''.join(sprites))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--start-x', type=int, default=2048, help='player x (mirror plane is x=8192)')
    parser.add_argument('--angle', type=int, default=0, help='start angle (0 faces the mirror)')
    args = parser.parse_args()
    args.output.write_bytes(build(args.start_x, args.angle))
