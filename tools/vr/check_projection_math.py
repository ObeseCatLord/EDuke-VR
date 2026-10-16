#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independent numeric check of the XR -> native Polymost projection boundary.

This verifies the coordinate/euler/crop derivation against rigid-pose projection;
it is not a runtime test of native visibility, sprite membership, or GL state.
"""
import math
import random


def mul(a, b):
    x, y, z, w = a
    X, Y, Z, W = b
    return (w*X+x*W+y*Z-z*Y, w*Y-x*Z+y*W+z*X,
            w*Z+x*Y-y*X+z*W, w*W-x*X-y*Y-z*Z)


def conjugate(q):
    return (-q[0], -q[1], -q[2], q[3])


def rotate(q, v):
    return mul(mul(q, (*v, 0)), conjugate(q))[:3]


def axis(index, angle):
    q = [0., 0., 0., math.cos(angle/2)]
    q[index] = math.sin(angle/2)
    return tuple(q)


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def cross(a, b):
    x, y, z = a
    X, Y, Z = b
    return y*Z-z*Y, z*X-x*Z, x*Y-y*X


def main():
    rng = random.Random(10669)
    max_error = 0.
    for _ in range(1000):
        # Native pitch*roll plus a yawed/translated HMD and initial recenter yaw.
        base = mul(axis(0, rng.uniform(-.4, .4)), axis(2, rng.uniform(-.3, .3)))
        tracking = mul(base, axis(1, -.23))
        head = mul(axis(1, rng.uniform(-1., 1.)), mul(axis(0, .12), axis(2, -.17)))
        q = mul(tracking, head)
        eye = rotate(tracking, (.032, .08, -.16))
        forward, actual_right = rotate(q, (0, 0, -1)), rotate(q, (1, 0, 0))
        horizontal = math.hypot(forward[0], forward[2])
        right = (-forward[2]/horizontal, 0, forward[0]/horizontal)
        up = cross(right, forward)
        yaw, pitch = math.atan2(forward[0], -forward[2]), math.atan2(forward[1], horizontal)
        roll = math.atan2(dot(actual_right, up), dot(actual_right, right))
        # Deliberately unequal asymmetric FOVs and a noncentral visible landmark.
        l, r, d, u = -.7, 1.1, -.6, .9
        cover = max(abs(l), abs(r), abs(d)*1.6, abs(u)*1.6)
        local = (rng.uniform(-.3, .5), rng.uniform(-.2, .4), -rng.uniform(1., 4.))
        world_delta = rotate(q, local)
        world = tuple(a+b for a, b in zip(eye, world_delta))
        # Independent rigid inverse view, standard OpenXR signed-tangent crop.
        rigid = rotate(conjugate(q), tuple(a-b for a, b in zip(world, eye)))
        expected = ((2*rigid[0]/-rigid[2]-(r+l))/(r-l),
                    (2*rigid[1]/-rigid[2]-(u+d))/(u-d))
        # Native yaw -> unequal VRC pitch -> tilt matrices from Polymost, then
        # exact crop matrix. Build's 384/6144 unit conversion is ratio sixteen.
        bx, by, bz = -world_delta[2]*384, world_delta[0]*384, -world_delta[1]*6144
        co, si = math.cos(yaw), math.sin(yaw)
        x = (-bx*si+by*co)/384/cover
        y = -bz/6144/cover
        z = (bx*co+by*si)/384
        cp, sp = math.cos(pitch), math.sin(pitch)
        y, z = cp*y-sp/cover*z, sp*cover*y+cp*z
        cr, sr = math.cos(roll), math.sin(roll)
        x, y = cr*x+sr*y, -sr*x+cr*y
        actual = ((2*cover*x/z-(r+l))/(r-l), (2*cover*y/z-(u+d))/(u-d))
        max_error = max(max_error, *(abs(a-b) for a, b in zip(actual, expected)))
    assert max_error < 1e-10, max_error
    print(f'1000 mixed-pose asymmetric-projection cases passed; max NDC error {max_error:.3g}')


if __name__ == '__main__':
    main()
