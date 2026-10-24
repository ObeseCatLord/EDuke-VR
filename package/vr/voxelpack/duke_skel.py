"""v7's 49-bone Duke skeleton for the skinned voxel body (pure numpy).

The skeleton, the 28 animation poses and the frame/tag contract are read from the shipped v7 set
(EDUKE32_VR_ASSETS/v7-original/exports/eduke32/vr_duke_ik.{skel,anim}, vr_duke.md3); nothing is copied.

Frames: true-handed model space (+X forward, +Y LEFT, +Z up), metres. MD3 files store 64 units per metre; the
third-person vr_duke / vr_duke_body use the v6 convention (+Y RIGHT: y mirrored, winding reversed).

Build pose: the pose the voxel body is assembled and meshed in. It is v7's bind pose with the arms raised to a
T-pose (each upper arm, forearm, hand and finger chain turned rigidly about the shoulder so the arm points
straight out along +-Y) and straight vertical legs (thigh and calf turned about the hip; the foot keeps its
bind orientation), so every limb lies along a grid axis and its voxels stay box-aligned when it moves. The
skin's local vertex positions are taken in the build-pose bone frames; in the bind pose (the .skel) the arms
therefore come down to v7's A-pose and the legs spread 6 degrees, exactly as the engine poses them.
"""
import math
from pathlib import Path
import numpy as np

U = 64.0


def quat_to_R(q):
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w)
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def rot_axis(axis, ang):
    k = np.asarray(axis, float) / np.linalg.norm(axis)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * K @ K


def rot_between(a, b):
    a = np.asarray(a, float) / np.linalg.norm(a)
    b = np.asarray(b, float) / np.linalg.norm(b)
    c = np.cross(a, b)
    s = np.linalg.norm(c)
    if s < 1e-12:
        if np.dot(a, b) > 0:
            return np.eye(3)
        return rot_axis(np.cross(a, [1, 0, 0]) if abs(a[0]) < 0.9 else np.cross(a, [0, 1, 0]), math.pi)
    return rot_axis(c, math.atan2(s, np.dot(a, b)))


def T4(R, p):
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = p
    return M


class Skeleton:
    def __init__(self, v7_exports):
        v7 = Path(v7_exports)
        rows = (v7 / 'vr_duke_ik.skel').read_text().split('\n')
        head = rows[0].split()
        assert head[:2] == ['skel', '1'], head
        n = int(head[2])
        self.names, self.parent, M = [], [], []
        for r in rows[1:1 + n]:
            f = r.split()
            self.names.append(f[0])
            self.parent.append(int(f[1]))
            p = np.array([float(v) for v in f[2:5]]) / U
            M.append(T4(quat_to_R([float(v) for v in f[5:9]]), p))
        self.bind = np.array(M)
        self.bi = {b: i for i, b in enumerate(self.names)}
        self.skel_text = (v7 / 'vr_duke_ik.skel').read_text()
        self.poses = self._read_anim(v7 / 'vr_duke_ik.anim')
        self.build = self._build_pose()

    def _read_anim(self, path):
        rows = path.read_text().split('\n')
        h = rows[0].split()
        assert h[:2] == ['anim', '1'] and int(h[2]) == len(self.names), h
        poses, i = {}, 1
        for _ in range(int(h[3])):
            name = rows[i].split()[1]
            M = []
            for r in rows[i + 1:i + 1 + len(self.names)]:
                f = [float(v) for v in r.split()]
                M.append(T4(quat_to_R(f[3:7]), np.array(f[:3]) / U))
            poses[name] = np.array(M)
            i += 1 + len(self.names)
        return poses

    def subtree(self, root):
        out = [self.bi[root]]
        for i, p in enumerate(self.parent):
            if p in out:
                out.append(i)
        return out

    def _build_pose(self):
        G = self.bind.copy()
        self.arm_rot = {}
        for s, out in (('l', 1.0), ('r', -1.0)):
            ua, fa = self.bi[f'upperarm_{s}'], self.bi[f'forearm_{s}']
            sh = self.bind[ua][:3, 3]
            R = rot_between(self.bind[fa][:3, 3] - sh, [0, out, 0])
            self.arm_rot[s] = (R, sh)
            for b in self.subtree(f'upperarm_{s}'):
                G[b][:3, :3] = R @ self.bind[b][:3, :3]
                G[b][:3, 3] = sh + R @ (self.bind[b][:3, 3] - sh)
            th, ca = self.bi[f'thigh_{s}'], self.bi[f'calf_{s}']
            hip = self.bind[th][:3, 3]
            R = rot_between(self.bind[ca][:3, 3] - hip, [0, 0, -1])
            for b in self.subtree(f'thigh_{s}'):
                if self.names[b].startswith('foot'):
                    G[b][:3, 3] = hip + R @ (self.bind[b][:3, 3] - hip)
                else:
                    G[b][:3, :3] = R @ self.bind[b][:3, :3]
                    G[b][:3, 3] = hip + R @ (self.bind[b][:3, 3] - hip)
        return G

    def pos(self, name, pose=None):
        P = self.build if pose is None else pose
        return P[self.bi[name]][:3, 3].copy()


def fk_pose(sk, deltas, base=None):
    """World matrices after rotating bones in their own (parent-relative) frames: deltas = {bone: R (3x3) applied
    in the bone's local frame}, starting from `base` (default: the bind pose)."""
    base = sk.bind if base is None else base
    loc = []
    for i, p in enumerate(sk.parent):
        loc.append(base[i] if p < 0 else np.linalg.inv(base[p]) @ base[i])
    out = [None] * len(sk.names)
    for i, p in enumerate(sk.parent):
        L = loc[i].copy()
        if sk.names[i] in deltas:
            L[:3, :3] = L[:3, :3] @ deltas[sk.names[i]]
        out[i] = L if p < 0 else out[p] @ L
    return np.array(out)
