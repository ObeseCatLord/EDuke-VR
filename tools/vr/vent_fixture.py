#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Write a v7 Build map with a vent: a room (floor 0) whose east wall has a 512-wide duct opening
24 units up (floor -6144) and 32 units tall, running 16 units deep east. For crouch-jump checks.
"""
import argparse, struct
from pathlib import Path
from stereo_fixture import sector, sprite, PHEIGHT
from mirror_fixture import wall


def zsector(wallptr, wallnum, ceiling, floor):
    data = bytearray(sector(wallptr, wallnum))
    struct.pack_into('<ii', data, 4, ceiling, floor)
    return bytes(data)


def build() -> bytes:
    walls = [wall(0, 0, 1), wall(4096, 0, 2), wall(4096, 1792, 3, 9, 1), wall(4096, 2304, 4),
             wall(4096, 4096, 5), wall(0, 4096, 0),
             wall(4096, 1792, 7), wall(8192, 1792, 8), wall(8192, 2304, 9), wall(4096, 2304, 6, 2, 0)]
    sectors = zsector(0, 6, -16384, 0) + zsector(6, 4, -14336, -6144)
    sprites = [sprite(2048, 2048, 0, 0, tile=1405, angle=0)]
    header = struct.pack('<iiiihhh', 7, 2048, 2048, -PHEIGHT, 0, 0, 2)
    return (header + sectors + struct.pack('<h', len(walls)) + b''.join(walls)
            + struct.pack('<h', len(sprites)) + b''.join(sprites))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.parse_args().output.write_bytes(build())
