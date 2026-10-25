#!/usr/bin/env python3
"""(Voxel pack copy of v6-original/scripts/poses.py: trigger target and handlebar dorsal axis may come from
the asset record; the left hold of a handlebar keeps the handle axis. Driven by solve_holds.py.)

Solve finger poses (free + per-weapon holds) and write metadata/hand_skeleton.json and
metadata/hand_poses_flat.json.

python3 scripts/poses.py [weapons=pistol,shotgun|all] [aa=1]

Free poses are absolute joint transforms in the controller GRIP frame; hold poses are absolute joint
transforms in the weapon's MD3 model frame (positions in metres: +X forward, +Y right, +Z up) with
orientations in the weapon's right-handed render frame W (Wx = MD3 +Y, Wy = MD3 +Z, Wz = MD3 -X).
Holds are solved for the right hand on the true-handed weapon; the left hold is solved on the
mirrored weapon (its left grip panel becomes a right panel) and mirrored back.
"""
import json, math, sys, os
from pathlib import Path
import numpy as np

ROOT = Path(os.environ.get('EDUKE32_VOXEL_PACK', Path(__file__).resolve().parents[1]))   # the pack folder being built
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hands as H  # noqa: E402
from md3read import read_md3  # noqa: E402

META = ROOT / 'metadata'
A_W = np.array([[0, -1.0, 0], [0, 0, 1.0], [-1.0, 0, 0]]).T   # columns: W axes in author coords
S_Y = np.diag([1.0, -1, 1])


# ------------------------------------------------------------------ free poses (right hand, grip frame)
def controller_obstacle():
    """Virtual controller in the right-hand grip frame: tube along Z at x=-0.022, trigger, top face."""
    tris = []
    n, r, x0, y0 = 10, 0.019, -0.023, 0.002
    z0, z1 = -0.045, 0.065
    ring0 = [(x0 + r * math.cos(2 * math.pi * k / n), y0 + r * math.sin(2 * math.pi * k / n), z0) for k in range(n)]
    ring1 = [(x, y, z1) for x, y, _ in ring0]
    c0, c1 = (x0, y0, z0), (x0, y0, z1)
    for k in range(n):
        k1 = (k + 1) % n
        tris += [(ring0[k], ring0[k1], ring1[k1]), (ring0[k], ring1[k1], ring1[k]), (c0, ring0[k1], ring0[k]), (c1, ring1[k], ring1[k1])]
    tris = list(np.array(tris))
    tris += list(H.box_tris((x0, -0.008, -0.062), (0.044, 0.05, 0.026)))          # head / top face (thumbstick)
    tris += list(H.box_tris((x0 - 0.002, -0.032, -0.040), (0.016, 0.014, 0.026)))   # trigger
    return H.Obstacle(np.array(tris), margin=0.002)


def free_poses():
    root = H.PALM_IN_GRIP
    P = {}
    P['open'] = {}
    rel = {}
    for f, k in (('index', 0.8), ('middle', 1.0), ('ring', 1.15), ('little', 1.3)):
        rel[f'{f}_proximal'] = (14 * k, 0)
        rel[f'{f}_intermediate'] = (24 * k, 0)
        rel[f'{f}_distal'] = (12 * k, 0)
    rel['thumb_metacarpal'] = (8, 0); rel['thumb_proximal'] = (10, 0); rel['thumb_distal'] = (10, 0)
    P['relaxed'] = rel
    fist = H.close_hand({}, root, [], thumb=False)
    fist.update({'thumb_metacarpal': (34, 6), 'thumb_proximal': (30, 0), 'thumb_distal': (35, 0)})
    P['fist'] = fist
    point = H.close_hand({}, root, [], fingers=('middle', 'ring', 'little'), thumb=False)
    point['index_proximal'] = (4, 0); point['index_intermediate'] = (6, 0); point['index_distal'] = (4, 0)
    point.update({'thumb_metacarpal': (30, 6), 'thumb_proximal': (32, 0), 'thumb_distal': (30, 0)})
    P['point'] = point
    ctl = controller_obstacle()
    trig = H.close_hand({}, root, [ctl], thumb=False)
    trig.update({'thumb_metacarpal': (14, 0), 'thumb_proximal': (8, 0), 'thumb_distal': (12, 0)})
    P['trigger'] = trig
    return P


def finger_obstacles(angles, root, fingers):
    W = H.fk(angles, root)
    tris = []
    for f in fingers:
        for seg in H.finger_chain(f):
            L, w, h = H.seg_dims(seg)
            t = H.box_tris((0, 0, -L / 2), (w, h, L))
            tris += list(t @ W[seg][:3, :3].T + W[seg][:3, 3])
    return H.Obstacle(np.array(tris), margin=0.001)


def thumb_over(angles, root, fingers=('index', 'middle')):
    ob = finger_obstacles(angles, root, fingers)
    ch = ['thumb_metacarpal', 'thumb_proximal', 'thumb_distal']
    return H.close_chain(angles, root, ch, [H.TH_LIMITS[c] for c in ch], [H.TH_WEIGHT[c] for c in ch], [ob], 2.0)


# ------------------------------------------------------------------ weapon holds
def trigger_target(meta):
    if meta.get('trigger_author') is not None:
        return np.array(meta['trigger_author'], float)
    if meta.get('voxel'):
        return None
    """Author-space contact point on the front face of the weapon's `trigger` part, or None.

    The pad of the index finger rests on the trigger blade's front face, a little below its middle.
    """
    try:
        if meta.get('aa'):
            import specs_aa as specs
        else:
            import specs_vanilla as specs
        spec = specs.get(meta['name'])
    except Exception:
        return None
    part = next((q for q in spec['parts'] if q['name'] == 'trigger' and q.get('kind') == 'prism' and q.get('prof')), None)
    if part is None or part.get('axis') not in (None, 'y'):
        return None
    prof = np.array(part['prof'], float)
    zlo, zhi = prof[:, 1].min(), prof[:, 1].max()
    z = zhi - 0.6 * (zhi - zlo)
    xs = []
    for (x0, z0), (x1, z1) in zip(prof, np.roll(prof, -1, 0)):
        if (z0 - z) * (z1 - z) <= 0 and z0 != z1:
            xs.append(x0 + (z - z0) * (x1 - x0) / (z1 - z0))
    if not xs:
        return None
    return np.array([max(xs), float(part.get('y', 0.0)), z])


def reach_trigger(ang, root, tris, target):
    """Index chain that puts its pad on `target` without entering the weapon (trigger blade excepted)."""
    centres = tris.mean(1)
    keep = np.linalg.norm(centres - target, axis=1) > 0.010
    obstacles = [H.Obstacle(tris[keep], margin=0.0015), finger_obstacles(ang, root, ('middle',))]
    L = H.seg_length('index_distal')
    half = H.HEIGHT['index'] * H.K * 0.92 / 2
    back = np.array([-1.0, 0, 0])
    cands = []
    for fp in range(-10, 91, 8):
        for ab in range(-40, 16, 7):
            for fi in range(0, 106, 8):
                for k in (0.25, 0.55, 0.85):
                    a = dict(ang)
                    a['index_proximal'] = (float(fp), float(ab))
                    a['index_intermediate'] = (float(fi), 0.0)
                    a['index_distal'] = (float(fi) * k, 0.0)
                    W = H.fk(a, root)
                    M = W['index_distal']
                    P = M[:3, 3] + M[:3, :3] @ np.array([0, -half, -0.6 * L])
                    volar = -M[:3, 1]
                    cost = float(np.linalg.norm(P - target)) + 0.006 * (1 - float(volar @ back))
                    cands.append((cost, a))
    cands.sort(key=lambda c: c[0])
    # The chunky gloved finger barely fits a real trigger guard: test it against the weapon with a
    # slimmer (75%) section, then take the fewest contacts and the closest pad.
    slim = np.array([0.75, 0.75, 1.0])
    samples = {j: H.seg_samples(j) * slim for j in H.finger_chain('index')}
    best = None
    for cost, a in cands[:400]:
        if cost > 0.012:
            break
        W = H.fk(a, root)
        obs = obstacles + [H.Obstacle(H.palm_proxy_tris(W), margin=0.001)]
        hits = sum(int(o.hits(samples[j] @ W[j][:3, :3].T + W[j][:3, 3]).sum()) for j in samples for o in obs)
        if best is None or (hits, cost) < (best[0], best[1]):
            best = (hits, cost, a)
        if hits == 0:
            break
    if best is None:
        return None, None, None
    return best[2], best[1], best[0]


def reach_thumb(ang, root, tris, palm, axis, obstacles):
    """Thumb pad on the weapon's off (+Y, left) side, high on the grip and toward its front."""
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    bw = np.array([(i / 3, j / 3, 1 - i / 3 - j / 3) for i in range(4) for j in range(4 - i)])
    V = np.einsum('kb,tbc->tkc', bw, tris)
    N = np.repeat(n[:, None, :], len(bw), 1)
    V, N = V.reshape(-1, 3), N.reshape(-1, 3)
    up = axis / np.linalg.norm(axis)
    rel = V - palm
    along = rel @ up
    # off-side faces, from the upper half of the grip to just above it, ahead of the back strap
    region = (V[:, 1] > 0.004) & (np.abs(N[:, 1]) > 0.6) & (along > 0.0) & (along < 0.075) & (rel[:, 0] > -0.02)
    if region.sum() < 3:
        return None
    pts = V[region]
    L = H.seg_length('thumb_distal')
    half = H.HEIGHT['thumb'] * H.K * 0.92 / 2
    inward, forward = np.array([0, -1.0, 0]), np.array([1.0, 0, 0])
    cands = []
    for tw in range(-60, 61, 30):
        for mf in range(-40, 71, 12):
            for mab in range(-70, 51, 12):
                for pf in range(-10, 71, 16):
                    for df in range(0, 81, 20):
                        a = dict(ang)
                        a['thumb_metacarpal'] = (float(mf), float(mab), float(tw))
                        a['thumb_proximal'] = (float(pf), 0.0)
                        a['thumb_distal'] = (float(df), 0.0)
                        M = H.fk(a, root)['thumb_distal']
                        P = M[:3, 3] + M[:3, :3] @ np.array([0, -half, -0.6 * L])
                        d = float(np.min(np.linalg.norm(pts - P, axis=1)))
                        volar, tip = -M[:3, 1], -M[:3, 2]
                        cost = d + 0.006 * (1 - float(volar @ inward)) + 0.004 * (1 - float(tip @ forward))
                        cands.append((cost, a))
    cands.sort(key=lambda c: c[0])
    slim = np.array([0.8, 0.8, 1.0])
    ch = ['thumb_metacarpal', 'thumb_proximal', 'thumb_distal']
    samples = {j: H.seg_samples(j) * slim for j in ch}
    best = None
    for cost, a in cands[:2500]:
        if cost > 0.035:
            break
        W = H.fk(a, root)
        obs = list(obstacles) + [H.Obstacle(H.palm_proxy_tris(W), margin=0.001)]
        hits = sum(int(o.hits(samples[j] @ W[j][:3, :3].T + W[j][:3, 3]).sum()) for j in ch for o in obs)
        if best is None or (hits, cost) < best[:2]:
            best = (hits, cost, a)
        if hits == 0:
            break
    if best is None or best[0] > 4:
        return None
    return best[2], round(best[1], 4), best[0]


def weapon_tris(md3_path):
    m = read_md3(md3_path)
    s = m['surfaces'][0]
    v = np.array([p[:3] for p in s['frames'][0]]) / 64.0 * np.array([1, -1, 1])   # author space
    t = np.array(s['tris'])[:, ::-1]
    tags = {k: np.array(x['origin']) / 64.0 * np.array([1, -1, 1]) for k, x in m['tags'][0].items()}
    return v[t], tags


def _solve_hold_once(tris, palm, axis, hold_cfg, trigger=None):
    """Right hand on a true-handed weapon whose RIGHT grip panel (author -Y) carries `palm`."""
    a = np.asarray(axis, float); a = a / np.linalg.norm(a)
    yH = np.array(hold_cfg.get('dorsal', [0, -1.0, 0]), float)
    yH = yH - np.dot(yH, a) * a; yH /= np.linalg.norm(yH)
    xH = -a
    zH = np.cross(xH, yH)
    R = np.stack([xH, yH, zH], 1)
    tilt = hold_cfg.get('roll_deg', 0.0)
    if tilt:
        R = R @ H.rot('z', tilt)
    # Level the wrist: with the knuckle line along a raked grip the whole hand tilts down toward the
    # muzzle. Turn the hand within the grip panel (about its dorsal axis) until the wrist runs back
    # at `wrist_pitch_deg` (default 5 deg down), as in a natural high grip.
    if abs(a[2]) > 0.5 and hold_cfg.get('wrist_pitch_deg', -5.0) is not None:
        target = math.radians(hold_cfg.get('wrist_pitch_deg', -5.0))
        best_t = min(range(-45, 46), key=lambda t: abs(math.asin(float(np.clip((R @ H.rot('y', t))[2, 2], -1, 1))) - target))
        R = R @ H.rot('y', best_t)
    # forward distance from the palm tag to the grip front, measured in a band around the palm
    bw = np.array([(i / 4, j / 4, 1 - i / 4 - j / 4) for i in range(5) for j in range(5 - i)])
    V = np.einsum('kb,tbc->tkc', bw, tris).reshape(-1, 3)      # dense surface samples
    rel = V - palm
    along = rel @ a
    side = rel @ R[:, 1]
    band = (along > -0.03) & (along < 0.02) & (side < 0.004) & (side > -0.08)
    fwd = -R[:, 2]
    front = float((rel[band] @ fwd).max()) if band.any() else 0.02
    kn = -H.BIND['middle_proximal'][2, 3]          # knuckle distance ahead of the palm joint
    d_pj = front + hold_cfg.get('knuckle_gap', 0.006) - kn
    d_pj = float(np.clip(d_pj, -0.03, 0.025))
    up = hold_cfg.get('slide_up', 0.0)
    pj = palm + R[:, 1] * (H.PALM_HALF_T + 0.0015) + fwd * d_pj + a * up
    obs = [H.Obstacle(tris, margin=0.0015)]
    # Wrap: the back strap sits in the palm, so the palm turns round the grip's back-right corner and
    # faces forward-left; this is what lets the thumb reach the far side. Rotate the placement about
    # the grip centreline, then settle the palm against the grip along its back-of-hand axis.
    wrap = hold_cfg.get('wrap_deg', 35.0 if abs(a[2]) > 0.5 else 0.0)
    if wrap:
        centre = palm - R[:, 1] * float(np.clip(-(rel[band] @ R[:, 1]).min() if band.any() else 0.018, 0.01, 0.03))
        c_, s_ = math.cos(math.radians(-wrap)), math.sin(math.radians(-wrap))
        k = a  # Rodrigues rotation about the grip axis
        K_ = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
        Rw = np.eye(3) + s_ * K_ + (1 - c_) * (K_ @ K_)
        R = Rw @ R
        pj = centre + Rw @ (pj - centre)
        palm_obs = lambda p_: H.Obstacle(H.palm_proxy_tris(H.fk({}, H.T(R, p_))), margin=0.0)
        weapon = H.Obstacle(tris, margin=0.002)
        def touching(p_):
            P_ = H.palm_proxy_tris(H.fk({}, H.T(R, p_))).reshape(-1, 3)
            return weapon.hits(P_).any() or palm_obs(p_).hits(tris.reshape(-1, 3)).any()
        for _ in range(15):            # push out of the grip
            if not touching(pj):
                break
            pj = pj + R[:, 1] * 0.002
        for _ in range(6):             # or settle onto it
            if touching(pj - R[:, 1] * 0.002):
                break
            pj = pj - R[:, 1] * 0.002
    root = H.T(R, pj)
    info = {}
    if trigger is not None:
        # Trigger weapons: middle/ring/little wrap the grip, the index finger rests on the trigger.
        # Slide the hand along the grip (smallest shift first) until the trigger is reachable.
        # Rank (contacts, |slide|, pad distance); a few grazing contacts of the chunky finger with the
        # guard/body are accepted rather than falling back to a wrap with no trigger finger.
        best = None
        for slide in (0.0, 0.008, -0.008, 0.016, -0.016, 0.024, -0.024):
            r_ = H.T(R, pj + a * slide)
            base = H.close_hand({}, r_, obs, fingers=('middle', 'ring', 'little'), thumb=False)
            got, cost, hits = reach_trigger(base, r_, tris, trigger)
            if got is not None and (best is None or (hits, abs(slide), cost) < best[:3]):
                best = (hits, abs(slide), cost, got, r_, slide)
            if best is not None and best[0] == 0:
                break
        reached = None
        if best is not None and best[0] <= 8:
            hits, _, cost, reached, root, slide = best
            info.update(trigger_cost_m=round(cost, 4), trigger_slide_m=slide, trigger_contacts=hits)
        if reached is not None:
            ang = reached
        else:
            ang = H.close_hand({}, root, obs, thumb=False)
            info['trigger_cost_m'] = None
    else:
        ang = H.close_hand({}, root, obs, thumb=False)
    # thumb: rest the pad on the off side of the frame/grip, high and toward the front, facing the
    # weapon and pointing forward; fall back to wrapping when that region is missing.
    fobs = finger_obstacles(ang, root, ('index', 'middle', 'ring', 'little'))
    got = reach_thumb(ang, root, tris, palm, a, obs + [fobs])
    if got is not None:
        ang, info['thumb_cost_m'], info['thumb_contacts'] = got
    else:
        best = None
        ch = ['thumb_metacarpal', 'thumb_proximal', 'thumb_distal']
        cands = hold_cfg.get('thumb_starts') or [(f, ab) for f in (-20.0, 0.0, 15.0) for ab in (-35.0, -15.0, 0.0)]
        for fl, ab in cands:
            a0 = dict(ang)
            a0['thumb_metacarpal'] = (fl, ab)
            r = H.close_chain(a0, root, ch, [H.TH_LIMITS[c] for c in ch], [H.TH_WEIGHT[c] for c in ch], obs + [fobs], 2.0)
            W = H.fk(r, root)
            P = np.array([W['thumb_tip'][:3, 3], W['thumb_distal'][:3, 3]])
            if any(o.hits(P).any() for o in obs):
                continue
            depth = float(-(W['thumb_tip'][:3, 3] - root[:3, 3]) @ R[:, 1])
            if best is None or depth > best[0]:
                best = (depth, r)
        if best:
            ang = best[1]
    return ang, root, dict(front=front, palm_joint_forward=d_pj, **info)


STUCK_FLEX = 15.0       # a wrapping finger whose knuckle bends less than this sticks out past the grip
TUCKED = {'proximal': 75.0, 'intermediate': 95.0, 'distal': 60.0}


def stuck_fingers(ang, trigger=None):
    """Fingers that found nothing to wrap (straight or bent back), the trigger finger aside."""
    return [f for f in ('index', 'middle', 'ring', 'little')
            if not (trigger is not None and f == 'index') and ang.get(f'{f}_proximal', (0.0,))[0] < STUCK_FLEX]


def solve_hold(tris, palm, axis, hold_cfg, trigger=None):
    """Try a few palm wraps (most natural first); keep the first that seats both the trigger finger and
    the thumb, else the best by (trigger seated, thumb seated, contacts). A short grip can leave fingers
    with nothing to wrap (they would stick out straight): then the best wrap is also tried slid along
    the grip (at most three more solves), and any finger still left over is tucked into a curl."""
    wraps = [hold_cfg['wrap_deg']] if 'wrap_deg' in hold_cfg else [35.0, 20.0, 0.0]
    base_up = hold_cfg.get('slide_up', 0.0)

    def attempt(wrap, up):
        ang, root, info = _solve_hold_once(tris, palm, axis, dict(hold_cfg, wrap_deg=wrap, slide_up=base_up + up), trigger)
        info['wrap_deg'] = wrap
        trig_ok = trigger is None or info.get('trigger_cost_m') is not None
        thumb_ok = 'thumb_cost_m' in info
        score = (len(stuck_fingers(ang, trigger)), not trig_ok, not thumb_ok, abs(up),
                 info.get('trigger_contacts', 0) + info.get('thumb_contacts', 0))
        return (score, ang, root, info, up, wrap)

    best = None
    for wrap in wraps:
        r = attempt(wrap, 0.0)
        if best is None or r[0][1:] < best[0][1:] or (r[0][1:] == best[0][1:] and r[0] < best[0]):
            best = r
        if not r[0][1] and not r[0][2]:
            break
    if best[0][0]:
        for up in (-0.012, -0.024, 0.012):
            r = attempt(best[5], up)
            if r[0][0] < best[0][0] and r[0][1:3] <= best[0][1:3]:
                best = r
            if not best[0][0]:
                break
    ang, root, info, up = dict(best[1]), best[2], best[3], best[4]
    if up:
        info['slide_up_m'] = up
    left = stuck_fingers(ang, trigger)
    for f in left:
        for seg, flex in TUCKED.items():
            j = f'{f}_{seg}'
            v = list(ang.get(j, (0.0, 0.0, 0.0)))
            ang[j] = tuple([flex] + v[1:])
    if left:
        info['tucked'] = left
    return ang, root, info


def hold_records(md3_path, meta):
    tris, tags = weapon_tris(md3_path)
    axis = np.array(meta['grip_axis_author'])
    cfg = meta.get('hold') or {}
    trigger = trigger_target(meta)
    out = {}
    for side in ('right', 'left'):
        if side == 'right':
            T_, palm, ax = tris, tags['tag_palm_right'], axis
        else:   # mirror the weapon, solve with the right hand, mirror back
            T_ = tris * np.array([1, -1, 1])
            T_ = T_[:, ::-1]
            palm = tags['tag_palm_left'] * np.array([1, -1, 1])
            ax = axis if cfg.get('dorsal') else axis * np.array([1, -1, 1])
        trig = None if trigger is None else (trigger if side == 'right' else trigger * np.array([1, -1, 1]))
        ang, root, info = solve_hold(T_, palm, ax, cfg, trig)
        W = H.fk(ang, root)
        joints = []
        for j in H.SHORT:
            M = W[j]
            Rm, p = M[:3, :3], M[:3, 3]
            if side == 'left':
                Rm = S_Y @ Rm @ H.S_X
                p = S_Y @ p
            Rw = A_W.T @ Rm                 # orientation in W
            p_md3 = p * np.array([1, -1, 1])
            joints.append([round(float(x), 6) for x in list(p_md3) + list(H.quat(Rw))])
        pj = joints[0]
        out[side] = dict(angles={k: [round(float(x), 3) for x in v] for k, v in ang.items()}, joints=joints,
                         weapon_to_palm=dict(position_md3_m=pj[:3], orientation_W_xyzw=pj[3:]), solver=info)
    return out


# ------------------------------------------------------------------ output
def local_quats(angles):
    out = {}
    for j, a in angles.items():
        fl, ab = a[0], a[1] if len(a) > 1 else 0.0
        tw = a[2] if len(a) > 2 else 0.0
        out[j] = [round(float(x), 6) for x in H.quat(H.rot('y', -ab) @ H.rot('x', -fl) @ H.rot('z', tw))]
    return out


def grip_joints(angles, side):
    W = H.fk(angles, H.PALM_IN_GRIP)
    rec = []
    for j in H.SHORT:
        M = W[j] if side == 'right' else H.mirror_x(W[j])
        rec.append([round(float(x), 6) for x in list(M[:3, 3]) + list(H.quat(M[:3, :3]))])
    return rec


def _hold_job(md3, meta):
    rec = hold_records(Path(md3), meta)
    rec['md3'] = str(Path(md3).relative_to(ROOT))
    return rec


def main():
    args = dict(a.split('=', 1) for a in sys.argv[1:])
    free = free_poses()
    flat_path = META / 'hand_poses_flat.json'
    skel_path = META / 'hand_skeleton.json'
    old_flat = json.loads(flat_path.read_text()) if flat_path.exists() else {}
    old_skel = json.loads(skel_path.read_text()) if skel_path.exists() else {}
    holds = dict((old_skel.get('holds') or {}))
    names = []
    assets = META / 'assets'
    if args.get('weapons'):
        if args['weapons'] == 'all':
            names = sorted(p.stem for p in assets.glob('*.json') if 'grip_axis_author' in json.loads(p.read_text()))
        else:
            names = args['weapons'].split(',')
    jobs = []
    for n in names:
        mp = assets / f'{n}.json'
        if not mp.exists():
            mp = assets / f'vr_{n}.json'
        meta = json.loads(mp.read_text())
        md3 = ROOT / 'exports' / 'eduke32' / ('aa/' if meta.get('aa') else '') / f'{meta["stem"]}.md3'
        jobs.append((meta['name'], str(md3), meta))
    from multiprocessing import Pool
    with Pool(int(args.get('jobs', 6))) as pool:
        for key, rec in zip([j[0] for j in jobs], pool.starmap(_hold_job, [(j[1], j[2]) for j in jobs])):
            holds[key] = rec
            print('hold', key, {s_: holds[key][s_]['solver'] for s_ in ('right', 'left')}, flush=True)
    conventions = {
        'units': 'metres',
        'joint_order': 'XR_HAND_JOINT_PALM_EXT .. XR_HAND_JOINT_LITTLE_TIP_EXT (26, XR_EXT_hand_tracking order)',
        'joint_frame': 'XR_EXT_hand_tracking: -Z toward the fingertip/child joint, +Y dorsal (back of the hand), +X = Y x Z',
        'quaternion': '[qx, qy, qz, qw], unit, qw >= 0',
        'grip_frame': ('OpenXR core grip pose: +X to the user\'s right for BOTH hands (away from the left palm, into the right '
                       'palm), -Z along the grip from the little finger toward the thumb, +Y = Z x X. The palm surface centroid '
                       'is at the grip origin (the same point the engine puts at a weapon\'s tag_palm_<side>).'),
        'weapon_frame_positions': 'hold poses: positions in the weapon MD3 model frame in metres (+X forward, +Y right, +Z up; MD3 units / 64)',
        'weapon_frame_orientations': ('hold poses: orientations in the weapon\'s right-handed render frame W with Wx = MD3 +Y, '
                                      'Wy = MD3 +Z, Wz = MD3 -X (the (y, z, -x) mapping vr.cpp uses for held weapons). To get a '
                                      'joint axis as MD3 components: r = rotate(q, axis); c = (-r.z, r.x, r.y).'),
        'segments': ('hands/vr_hand_<side>_<segment>.md3 vertices are stored directly in the proximal joint\'s local frame '
                     '(metres*64, no mirroring, positive signed volume); draw each at its joint transform.'),
        'left_hand': 'exact mirror of the right hand (grip frame: x -> -x, R -> S R S with S = diag(-1,1,1))',
        'local_rotations': ('poses[*].local: per-joint rotation relative to that joint\'s bind (open-hand) local transform, '
                            'R = Ry(-abduct) Rx(-flex) Rz(twist) applied in the joint frame (flex > 0 curls toward the palm); '
                            'world_j = world_parent * bind_local_j * R_j, parent hierarchy in "parents".'),
    }
    seg_info = {s: dict(joint=H.JOINTS[H.JI[j]], length_m=round(H.seg_length(s), 5),
                        width_m=round(H.seg_dims(s)[1], 5), thickness_m=round(H.seg_dims(s)[2], 5))
                for s, j in H.SEGMENTS.items()}
    skel = dict(conventions=conventions, joint_order=H.JOINTS, parents={H.JOINTS[H.JI[j]]: (H.JOINTS[H.JI[p]] if p else None)
                                                                        for j, p in H.PARENT.items()},
                scale_vs_reference_hand=H.K, segments=seg_info, sides={}, holds=holds)
    flat = dict(conventions=conventions, joint_order=H.JOINTS,
                segments={s: dict(joint=v['joint'], length_m=v['length_m']) for s, v in seg_info.items()}, poses={})
    for side in ('left', 'right'):
        rest = grip_joints({}, side)
        bind_local = {}
        for j in H.SHORT:
            M = H.LOCAL[j] if side == 'right' else H.mirror_x(H.LOCAL[j])
            bind_local[H.JOINTS[H.JI[j]]] = [round(float(x), 6) for x in list(M[:3, 3]) + list(H.quat(M[:3, :3]))]
        sp = {}
        fp = {}
        for name, ang in free.items():
            lq = local_quats(ang)
            sp[name] = dict(frame='grip', angles_deg={H.JOINTS[H.JI[k]]: [round(float(x), 2) for x in v] for k, v in ang.items()},
                            local_quaternions={H.JOINTS[H.JI[k]]: (q if side == 'right' else [q[0], -q[1], -q[2], q[3]]) for k, q in lq.items()},
                            joints=grip_joints(ang, side))
            fp[name] = dict(frame='grip', joints=sp[name]['joints'])
        for wname, rec in holds.items():
            r = rec[side]
            ang = r['angles']
            lq = local_quats(ang)
            sp[f'hold_{wname}'] = dict(frame=f'weapon:{wname}', weapon_md3=rec['md3'],
                                       angles_deg={H.JOINTS[H.JI[k]]: v for k, v in ang.items()},
                                       local_quaternions={H.JOINTS[H.JI[k]]: (q if side == 'right' else [q[0], -q[1], -q[2], q[3]]) for k, q in lq.items()},
                                       weapon_to_palm=r['weapon_to_palm'], joints=r['joints'])
            fp[f'hold_{wname}'] = dict(frame=f'weapon:{wname}', joints=r['joints'])
        skel['sides'][side] = dict(rest_joints_grip=rest, bind_local=bind_local, poses=sp)
        flat['poses'][side] = fp
    skel_path.write_text(json.dumps(skel, indent=1))
    flat_path.write_text(json.dumps(flat, indent=1))
    print('poses', list(flat['poses']['right']))


if __name__ == '__main__':
    main()
