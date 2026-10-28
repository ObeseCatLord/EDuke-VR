#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Does the sky stay fixed in the world when the head rotates? (lab captures, no translation)

Compares pairs of smoke_xr_scene captures taken at known head orientations from the same spot.
For a pure rotation every far pixel must move by the homography K R K^-1: the warped reference
must match the target for the sky (depth at the far plane) just as it does for the world. For
each pair the head orientation offset that best explains the sky and the world separately is
searched; a sky that follows the head shows up as an offset (degrees) the world does not have.

  sky_rotation_check.py DIR --fov L,R,D,U --pair REF=yaw,pitch,roll:TARGET=yaw,pitch,roll ...
"""
import argparse, json, math
from pathlib import Path
import numpy as np
from PIL import Image


def rotation(yaw, pitch, roll):
    """Head orientation (degrees): yaw about +y, then pitch about +x, then roll about -z (OpenXR)."""
    a, b, c = map(math.radians, (yaw, pitch, roll))
    ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
    rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
    rz = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
    return ry @ rx @ rz


class Capture:
    def __init__(self, directory, name, tangents):
        self.image = np.asarray(Image.open(directory / f'{name}-left.ppm').convert('RGB'), float)
        depth = np.fromfile(directory / f'{name}-left-depth.bin', np.uint32)   # GL_UNSIGNED_INT, bottom row first
        self.depth = ((depth >> 8) / float(1 << 24)).reshape(self.image.shape[:2])[::-1]
        self.sky = self.depth >= 0.99999
        self.left, self.right, self.down, self.up = tangents
        self.height, self.width = self.image.shape[:2]

    def rays(self, step):
        y, x = np.mgrid[0:self.height:step, 0:self.width:step].astype(float)
        tx = self.left + (x + .5) / self.width * (self.right - self.left)
        ty = self.up - (y + .5) / self.height * (self.up - self.down)
        return x, y, np.stack([tx, ty, -np.ones_like(tx)], -1)

    def pixels(self, rays):
        z = -rays[..., 2]
        ok = z > 1e-6
        tx, ty = rays[..., 0] / np.where(ok, z, 1), rays[..., 1] / np.where(ok, z, 1)
        x = np.round((tx - self.left) / (self.right - self.left) * self.width - .5).astype(int)
        y = np.round((self.up - ty) / (self.up - self.down) * self.height - .5).astype(int)
        ok &= (x >= 0) & (x < self.width) & (y >= 0) & (y < self.height)
        return x.clip(0, self.width - 1), y.clip(0, self.height - 1), ok


def compare(ref, target, ref_pose, target_pose, step=2, search=6.0, resolution=0.25):
    """Best head offset (dyaw, dpitch) of the target for sky and for world pixels, with errors."""
    x, y, rays = target.rays(step)
    sky_t, world_t = target.sky[::step, ::step], ~target.sky[::step, ::step] & (y < target.height * 0.72)
    result = {}
    for kind, mask_t in (('sky', sky_t), ('world', world_t)):
        best = None
        grid = [(dy, dp) for dy in np.arange(-search, search + 1e-6, 1.0) for dp in np.arange(-search, search + 1e-6, 1.0)]
        for stage in range(2):
          if stage == 1 and best is not None:   # refine around the coarse optimum
              grid = [(best[1] + dy, best[2] + dp) for dy in np.arange(-1, 1 + 1e-6, resolution) for dp in np.arange(-1, 1 + 1e-6, resolution)]
          for dyaw, dpitch in grid:
            yaw, pitch, roll = target_pose
            m = rotation(*ref_pose).T @ rotation(yaw + dyaw, pitch + dpitch, roll)
            rx, ry, ok = ref.pixels(rays @ m.T)
            both = mask_t & ok & (ref.sky[ry, rx] if kind == 'sky' else ~ref.sky[ry, rx])
            if both.sum() < 1500:
                continue
            error = float(np.abs(target.image[::step, ::step] - ref.image[ry, rx]).mean(-1)[both].mean())
            if best is None or error < best[0]:
                best = (error, float(dyaw), float(dpitch), int(both.sum()))
        result[kind] = None if best is None else {'error': round(best[0], 2), 'offset_deg': [best[1], best[2]], 'pixels': best[3]}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--fov', default='-40.4,40.0,-40.4,40.0', help='left,right,down,up degrees (EDUKE32_XR_TEST_FOV)')
    parser.add_argument('--pair', action='append', required=True, help='REF=yaw,pitch,roll:TARGET=yaw,pitch,roll')
    parser.add_argument('--tolerance', type=float, default=1.0, help='largest sky offset (degrees) that passes')
    args = parser.parse_args()
    tangents = [math.tan(math.radians(float(v))) for v in args.fov.split(',')]
    captures, report, passed = {}, [], True
    for pair in args.pair:
        (ref_name, ref_pose), (target_name, target_pose) = [(p.split('=')[0], tuple(map(float, p.split('=')[1].split(','))))
                                                            for p in pair.split(':')]
        for name in (ref_name, target_name):
            if name not in captures:
                captures[name] = Capture(args.directory, name, tangents)
        r = compare(captures[ref_name], captures[target_name], ref_pose, target_pose)
        sky = r['sky']
        # A pair with too little sky in both views is not measured (and does not fail).
        ok = sky is None or max(map(abs, sky['offset_deg'])) <= args.tolerance
        passed &= ok
        report.append({'pair': pair, 'sky': sky, 'world': r['world'], 'passed': ok})
    measured = sum(p['sky'] is not None for p in report)
    passed &= measured >= min(3, len(report))
    print(json.dumps({'passed': passed, 'measured_pairs': measured, 'pairs': report}, indent=1))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
