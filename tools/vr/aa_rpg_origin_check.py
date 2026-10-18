#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independent native-origin oracle for AA's standard-Duke RPG shot.

The runner supplies only native log text and the private RPG MD3.  This module
does not manufacture a projectile, alter controller input, or choose a shot:
it joins the accepted input sample, PREWEAPONSHOOT anchor, engine RPG traces,
and AA's EVENT_EGS observation for the one native insertion.
"""
import math
import re
import struct

import numpy as np

from pistol_mount_check import tags
from smoke_weapon import rotation


INPUT = re.compile(
    r"OpenXR weapon mount input: clock=(\d+) counter=(\d+) hand=(\d+) "
    r"grip=([^ ]+) aim=([^ ]+) origin=([^ ]+) tracking=([^ ]+) "
    r"yaw=([^ ]+) offset=([^ ]+)\.")
AUTHORITY = re.compile(
    r"VR authoritative RPG: player=(\d+) origin=(-?\d+),(-?\d+),(-?\d+) "
    r"sector=(-?\d+) clamped=(\d+) angle=(-?\d+) speed=(-?\d+) zvel=(-?\d+)\.")
# Current engine text is ``native projectile``.  Accept the explicit RPG name
# too, so the parser remains tied to the same field contract if that label is
# clarified without changing the diagnostic payload.
NATIVE = re.compile(
    r"VR native (?:projectile|RPG): player=(\d+) tile=(\d+) index=(\d+) "
    r"origin=(-?\d+),(-?\d+),(-?\d+) sector=(-?\d+) clamped=(\d+) "
    r"angle=(-?\d+) speed=(-?\d+) zvel=(-?\d+) policy=(-?\d+)\.")
AAMOUNT = re.compile(r"addlog aamount_(x|y|z|pyoff|counter)(?: \(player \d+\))? = (-?\d+)")
EGS = re.compile(r"addlog aarpg_spawn_(\w+)(?: \(player \d+\))? = (-?\d+)")

_ANCHOR_FIELDS = ("x", "y", "z", "pyoff", "counter")
_EGS_FIELDS = ("tick", "player", "index", "sector", "x", "y", "z", "angle", "speed", "zvel")
RPG_TILE = 2605


def _numbers(value, size):
    """Parse one compact comma-separated diagnostic field strictly."""
    try:
        result = np.fromstring(value, sep=",")
    except ValueError:
        return None
    return result if result.size == size and np.isfinite(result).all() else None


def _input(match):
    clock, counter, hand, grip, aim, origin, tracking, yaw, offset = match.groups()
    values = (_numbers(grip, 3), _numbers(aim, 7), _numbers(origin, 3),
              _numbers(tracking, 4), _numbers(offset, 3))
    if any(value is None for value in values):
        return None
    return {"clock": int(clock), "counter": int(counter), "hand": int(hand),
            "grip": values[0], "aim": values[1], "origin": values[2],
            "tracking": values[3], "yaw": float(yaw), "offset": values[4]}


def _authority(match):
    player, x, y, z, sector, clamped, angle, speed, zvel = map(int, match.groups())
    return {"player": player, "x": x, "y": y, "z": z, "sector": sector,
            "clamped": clamped, "angle": angle, "speed": speed, "zvel": zvel}


def _native(match):
    player, tile, index, x, y, z, sector, clamped, angle, speed, zvel, policy = map(int, match.groups())
    return {"player": player, "tile": tile, "index": index, "x": x, "y": y, "z": z,
            "sector": sector, "clamped": clamped, "angle": angle, "speed": speed,
            "zvel": zvel, "policy": policy}


def _complete_row(text, pattern, fields):
    """Yield ordered complete addlog rows; partial writes are not evidence."""
    row = {}
    for field, value in pattern.findall(text):
        if field == fields[0]:
            row = {field: int(value)}
        elif row:
            row[field] = int(value)
        if row and field == fields[-1] and all(key in row for key in fields):
            yield row
            row = {}


def _expected_offsets(sample, points):
    """Recreate vr.cpp's tag swizzle, tracking transform, and Build units."""
    hand = sample["hand"]
    side = "right" if hand else "left"
    palm_key = "tag_palm_" + side
    if hand not in (0, 1) or "tag_muzzle" not in points or palm_key not in points:
        return None
    delta = points["tag_muzzle"] - points[palm_key]
    muzzle = sample["grip"] + rotation(sample["aim"][:4]) @ np.array((delta[1], delta[2], -delta[0])) / 64

    def convert(point):
        x, y, z = rotation(sample["tracking"]) @ (point - sample["origin"])
        co, si = math.cos(sample["yaw"]), math.sin(sample["yaw"])
        return np.array(((-z * co - x * si) * 384, (-z * si + x * co) * 384, -y * 6144))

    return {"palm_tag": palm_key, "mounted": convert(muzzle), "legacy": convert(sample["aim"][4:])}


def _row(sample, anchor, authority, native, egs, points, mounted, expected_hand):
    result = {"sources_complete": False, "mounted": mounted, "expected_hand": expected_hand}
    if sample is None or anchor is None or authority is None or native is None or egs is None:
        return result
    offsets = _expected_offsets(sample, points)
    if offsets is None:
        return result
    expected = offsets["mounted"] if mounted else offsets["legacy"]
    other = offsets["legacy"] if mounted else offsets["mounted"]
    anchor_position = np.array((anchor["x"], anchor["y"], anchor["z"] + anchor["pyoff"]), dtype=float)
    encoded = sample["offset"]
    expected_insert = anchor_position + encoded
    actual_insert = np.array((native["x"], native["y"], native["z"]), dtype=float)
    mode_gap = float(np.linalg.norm((offsets["mounted"] - offsets["legacy"]) / np.array((384, 384, 6144))))
    authority_native_equal = (authority["player"] == native["player"] and
                              all(authority[key] == native[key] for key in ("x", "y", "z", "sector", "clamped")))
    egs_native_equal = (egs["player"] == native["player"] and egs["index"] == native["index"] and
                        all(egs[key] == native[key] for key in ("x", "y", "z", "sector")))
    result.update(
        sources_complete=True,
        sample_clock=sample["clock"], sample_counter=sample["counter"], firing_counter=anchor["counter"],
        hand=sample["hand"], palm_tag=offsets["palm_tag"], encoded_offset=encoded.tolist(),
        expected_offset=expected.tolist(), other_mode_offset=other.tolist(),
        encoded_error_build_units=np.abs(encoded - np.rint(expected)).tolist(),
        mounted_legacy_gap_metres=mode_gap, anchor=anchor_position.tolist(),
        expected_unclamped_insertion=expected_insert.tolist(), native_origin=actual_insert.tolist(),
        native_clamped=bool(native["clamped"]), native_tile=native["tile"], native_index=native["index"],
        authoritative_matches_native=authority_native_equal, egs_matches_native=egs_native_equal,
        accepted_hand=sample["hand"] == expected_hand and offsets["palm_tag"] ==
                      "tag_palm_" + ("right" if expected_hand else "left"),
        native_counter_four=anchor["counter"] == 4 and sample["counter"] in (3, 4),
        encoded_offset_matches_selected_mode=bool(np.max(np.abs(encoded - np.rint(expected))) <= 1),
        modes_are_physically_distinct=mode_gap > .1,
        native_standard_RPG=native["tile"] == RPG_TILE,
        unclamped_native_origin_matches_anchor_plus_offset=(native["clamped"] == 0 and
            bool(np.array_equal(actual_insert, expected_insert))),
        clamped_native_insertion_reported=(native["clamped"] != 0 and authority_native_equal and egs_native_equal),
    )
    return result


def firing(text, model, mounted: bool, expected_hand: int):
    """Return non-vacuous native-origin evidence for one RPG firing log.

    ``mounted`` selects the expected tagged palm muzzle.  ``False`` selects the
    legacy aim-pose origin; the reported mode gap still proves the two origins
    are materially different without asserting wall-resolver internals.
    """
    try:
        points = tags(model)
    except (OSError, ValueError, struct.error) as error:  # pragma: no cover - defensive boundary
        return {"checks": {"RPG_model_tags_readable": False}, "rows": [], "error": str(error)}
    required = {"tag_muzzle", "tag_palm_left", "tag_palm_right"}
    if not required.issubset(points):
        return {"checks": {"RPG_model_has_both_palm_tags": False}, "rows": [],
                "error": "RPG model lacks required muzzle/palm tags"}

    # Addlog records are emitted one field at a time. Pre-parse complete rows
    # by their final field, then consume them in source order below.
    anchors = list(_complete_row(text, AAMOUNT, _ANCHOR_FIELDS))
    egs_rows = list(_complete_row(text, EGS, _EGS_FIELDS))
    anchor_iter = iter(anchors)
    egs_iter = iter(egs_rows)
    next_anchor = next(anchor_iter, None)
    next_egs = next(egs_iter, None)
    latest_anchor = latest_egs = latest_input = latest_authority = None
    rows = []

    # Preserve line ordering so the last accepted sample before the projectile
    # trace, rather than an arbitrary later idle sample, is the source of truth.
    for line in text.splitlines():
        found = INPUT.search(line)
        if found:
            latest_input = _input(found)
        found = AAMOUNT.search(line)
        if found and found.group(1) == _ANCHOR_FIELDS[-1] and next_anchor is not None:
            latest_anchor, next_anchor = next_anchor, next(anchor_iter, None)
        found = EGS.search(line)
        if found and found.group(1) == _EGS_FIELDS[-1] and next_egs is not None:
            latest_egs, next_egs = next_egs, next(egs_iter, None)
        found = AUTHORITY.search(line)
        if found:
            latest_authority = _authority(found)
        found = NATIVE.search(line)
        if found:
            native = _native(found)
            if native["tile"] == RPG_TILE:
                rows.append(_row(latest_input, latest_anchor, latest_authority, native,
                                 latest_egs, points, mounted, expected_hand))

    required_checks = {
        "RPG_model_has_both_palm_tags": required.issubset(points),
        "RPG_native_trace_present": bool(rows),
        "RPG_complete_native_origin_sources": bool(rows) and all(row["sources_complete"] for row in rows),
    }
    row_checks = ("accepted_hand", "native_counter_four", "encoded_offset_matches_selected_mode",
                  "modes_are_physically_distinct", "native_standard_RPG",
                  "authoritative_matches_native", "egs_matches_native")
    for name in row_checks:
        required_checks["RPG_" + name] = bool(rows) and all(row.get(name, False) for row in rows)
    required_checks["RPG_unclamped_origin_or_clamped_exact_insertion_chain"] = bool(rows) and all(
        row.get("unclamped_native_origin_matches_anchor_plus_offset", False)
        or row.get("clamped_native_insertion_reported", False) for row in rows)
    return {"checks": required_checks, "rows": rows}
