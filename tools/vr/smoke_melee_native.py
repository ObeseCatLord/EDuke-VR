#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""CPU-only native selected-kick and quick-kick multiplayer reference.

This owns two classic SDL-dummy processes and feeds their normal private SDL
FIFO.  The fixture observes stock KNEE actors and player state only; it does
not fabricate a kick, damage, counter, or network message.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from smoke_actions_multiplayer import client_player_index
from smoke_hand_shots import room
from smoke_native_levels import assert_cpu_binary, assert_gpu_devices_absent, sanitised_env
from smoke_pipebomb_native import Run, join, sha256, write_lab


SYNC = "Multiplayer client level synchronization complete."
FIRE_SCAN = 228  # SDL_SCANCODE_RCTRL
QUICK_KICK_SCAN = 20  # SDL_SCANCODE_Q
KNEE = 2521
KNEE_WEAPON = 0
PISTOL_WEAPON = 1
FIRE_DELAY = 7
QUICK_KICK_FRAME = 8
PLAYER_KEYS = ("tick", "player", "index", "weapon", "frame", "quick", "lastquick", "bits",
               "health", "ammo0", "ammo1", "x", "y_now", "z", "angle", "steroids_now")
KNEE_KEYS = ("index", "owner", "ownerplayer", "sector", "x", "y", "z", "angle", "extra", "totalclock", "event")
FIELD = re.compile(r"addlog vrmelee_(\w+)(?: \(player \d+\))? = (-?\d+)")


def rows(text, keys):
    values, row = [], {}
    for key, value in FIELD.findall(text):
        if key not in keys:
            continue
        if key == keys[0]:
            row = {}
        row[key] = int(value)
        if key == keys[-1] and len(row) == len(keys):
            values.append(row)
    return values


def players(text, player=None):
    values = rows(text, PLAYER_KEYS)
    return [row for row in values if player is None or row["player"] == player]


def knees(text, ownerplayer=None):
    values, row = [], {}
    for key, value in FIELD.findall(text):
        if not key.startswith("knee_"):
            continue
        key = key[len("knee_"):]
        if key == KNEE_KEYS[0]:
            row = {}
        if key in KNEE_KEYS:
            row[key] = int(value)
        if key == KNEE_KEYS[-1] and len(row) == len(KNEE_KEYS):
            values.append(row)
    return [row for row in values if ownerplayer is None or row["ownerplayer"] == ownerplayer]


def last(text, player):
    values = players(text, player)
    return values[-1] if values else None


def reexec_sandbox(args):
    if args._sandboxed:
        return
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise RuntimeError("bubblewrap is required for the CPU-only runner")
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    safe = sanitised_env()
    child_args = [arg for arg in sys.argv[1:] if arg != "--_sandboxed"] + ["--_sandboxed"]
    command = [bwrap, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--unshare-pid",
               "--bind", str(work), str(work), "--chdir", str(Path.cwd()), "--clearenv"]
    for key in ("PATH", "LANG", "LC_ALL", "TZ"):
        if key in safe:
            command += ["--setenv", key, safe[key]]
    command += [sys.executable, str(Path(__file__).resolve()), *child_args]
    os.execvpe(bwrap, command, safe)


def configure_lab(root, role, args, selected_weapon, shooter_x, steroids):
    lab = write_lab(root, role, args.grp)
    fixture = (HERE / "fixtures" / "melee_test.con").read_text()
    fixture = fixture.replace("gamevar vrmelee_selected_weapon 0 0", f"gamevar vrmelee_selected_weapon {selected_weapon} 0")
    fixture = fixture.replace("gamevar vrmelee_shooter_x 1024 0", f"gamevar vrmelee_shooter_x {shooter_x} 0")
    fixture = fixture.replace("gamevar vrmelee_steroids 0 0", f"gamevar vrmelee_steroids {steroids} 0")
    (lab / "pipebomb_test.con").write_text(fixture)
    (lab / "pipebomb.map").write_bytes(room())
    # This binding exists only in the owned lab. Q is the normal local input
    # route for gamefunc_Quick_Kick, not a console/scripted damage command.
    with (lab / "autoexec.cfg").open("a") as script:
        script.write('bind "Q" "gamefunc_Quick_Kick"\n')
    return lab


def run_case(args, name, selected_weapon, shooter_x, input_scan, steroids, port):
    root = Path(tempfile.mkdtemp(prefix=f"melee-native-{name}-", dir=args.work_dir.resolve()))
    args.port = port
    run = Run(args, root)
    phase = "setup"
    result = {"passed": False, "case": name, "root": str(root), "selected_weapon": selected_weapon,
              "shooter_x": shooter_x, "steroids": steroids}
    try:
        for role in ("server", "client"):
            run.labs[role] = configure_lab(root, role, args, selected_weapon, shooter_x, steroids)
        phase = "native dedicated server"
        server = run.launch("server", ["-dedicated", "-c1", "-m", "-port", str(port), "-map", "pipebomb.map"])
        server.wait(lambda text: "Multiplayer server initialized." in text, timeout=18)
        phase = "native client join"
        shooter = join(run)
        client = run.observers["client"]
        server.wait(lambda text: last(text, shooter) is not None and last(text, 0) is not None and
                    last(text, shooter)["weapon"] == selected_weapon and last(text, shooter)["frame"] == 0, timeout=12)
        client.wait(lambda text: last(text, shooter) is not None and last(text, 0) is not None and
                    last(text, shooter)["weapon"] == selected_weapon, timeout=12)
        run.audit()
        shooter_before, target_before = last(server.text(), shooter), last(server.text(), 0)
        server_offset, client_offset = len(server.text()), len(client.text())
        phase = "normal local selected kick" if input_scan == FIRE_SCAN else "normal local quick kick"
        run.key("client", input_scan, True)
        if input_scan == FIRE_SCAN:
            server.wait(lambda text: any(row["frame"] == FIRE_DELAY and row["bits"] & 4
                                         for row in players(text[server_offset:], shooter)), timeout=6)
        else:
            server.wait(lambda text: any(row["quick"] > QUICK_KICK_FRAME for row in players(text[server_offset:], shooter)), timeout=6)
        run.key("client", input_scan, False)
        if input_scan == QUICK_KICK_SCAN:
            server.wait(lambda text: any(row["quick"] == QUICK_KICK_FRAME for row in players(text[server_offset:], shooter)), timeout=6)
        if shooter_x == 1024:
            server.wait(lambda text: bool(knees(text[server_offset:], shooter)), timeout=6)
            client.wait(lambda text: last(text, 0) is not None and last(text, 0)["health"] < target_before["health"], timeout=8)
        else:
            server.wait(lambda text: last(text, shooter) is not None and last(text, shooter)["tick"] >= shooter_before["tick"] + 18,
                        timeout=6)
        run.audit()
        authoritative = knees(server.text()[server_offset:], shooter)
        client_knees = knees(client.text()[client_offset:], shooter)
        windup = [row for row in players(server.text()[server_offset:], shooter)
                  if row["frame"] or row["quick"]]
        shooter_after, server_target_after, client_target_after = last(server.text(), shooter), last(server.text(), 0), last(client.text(), 0)
        hit = shooter_x == 1024
        checks = {
            "actual_native_client_player": shooter > 0,
            "selected_knee_native_windup_reaches_fire_delay": input_scan != FIRE_SCAN or any(
                row["frame"] == FIRE_DELAY and row["bits"] & 4 for row in windup),
            "quick_kick_starts_while_pistol_selected": input_scan != QUICK_KICK_SCAN or (
                shooter_before["weapon"] == PISTOL_WEAPON and any(row["quick"] > QUICK_KICK_FRAME for row in windup)),
            "quick_kick_native_counter_reaches_eight": input_scan != QUICK_KICK_SCAN or any(
                row["quick"] == QUICK_KICK_FRAME for row in windup),
            "within_native_manhattan_knee_range": (not hit) or bool(authoritative),
            "too_far_has_no_native_knee_actor": hit or not authoritative,
            "native_EGS_KNEE_owner_portal_sector_and_angle": (not hit) or all(
                row["ownerplayer"] == shooter and row["sector"] == 1 and row["angle"] == 15 for row in authoritative),
            "native_knee_body_origin_and_initial_EGS_strength": (not hit) or all(
                row["z"] == shooter_before["z"] + 2560 and row["extra"] == 10 for row in authoritative),
            "within_range_actual_server_target_damage": (not hit) or server_target_after["health"] < target_before["health"],
            "within_range_actual_client_target_damage_converges": (not hit) or client_target_after["health"] == server_target_after["health"] < target_before["health"],
            "too_far_target_remains_undamaged_and_converged": hit or (
                server_target_after["health"] == client_target_after["health"] == target_before["health"]),
            "knee_and_pistol_ammo_unchanged": (shooter_after["ammo0"] == shooter_before["ammo0"] and
                                                 shooter_after["ammo1"] == shooter_before["ammo1"]),
            "quick_kick_uses_KNEE_not_selected_pistol": input_scan != QUICK_KICK_SCAN or (not hit) or bool(authoritative),
            "no_gpu_devices_or_libraries": True,
        }
        result.update(passed=all(checks.values()), checks=checks, shooter=shooter, shooter_before=shooter_before,
                      shooter_after=shooter_after, target_before=target_before, server_target_after=server_target_after,
                      client_target_after=client_target_after, authoritative_knees=authoritative[-12:],
                      client_knees=client_knees[-12:], server_windup=windup[-16:],
                      target_manhattan_xy=abs(1600 - shooter_x) + abs(4120 - 4096))
    except Exception as error:
        result.update(error=str(error), phase=phase)
    finally:
        run.close()
        (root / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "input-helper", "grp", "work-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--reference-result", type=Path,
                        help="compare native impact fields/ammo against a saved pre-adapter reference")
    parser.add_argument("--port", type=int, default=24751)
    parser.add_argument("--_sandboxed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.port <= 65532:
        parser.error("--port must be in 1..65532")
    args.binary, args.input_helper, args.grp = (args.binary.resolve(), args.input_helper.resolve(), args.grp.resolve())
    if args.reference_result:
        args.reference_result = args.reference_result.resolve()
    if not args.binary.is_file() or not args.input_helper.is_file() or not args.grp.is_file():
        parser.error("--binary, --input-helper, and --grp must name existing files")
    reexec_sandbox(args)
    assert_gpu_devices_absent()
    assert_cpu_binary(args.binary)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    selected = run_case(args, "selected", KNEE_WEAPON, 1024, FIRE_SCAN, 0, args.port)
    too_far = run_case(args, "too-far", KNEE_WEAPON, 512, FIRE_SCAN, 0, args.port + 1)
    quick = run_case(args, "quick", PISTOL_WEAPON, 1024, QUICK_KICK_SCAN, 0, args.port + 2)
    result = {"passed": all(case.get("passed", False) for case in (selected, too_far, quick)),
              "renderer": "CPU classic (no VR/SPS proof)", "binary_sha256": sha256(args.binary),
              "selected": selected, "too_far": too_far, "quick": quick}
    if args.reference_result:
        reference = json.loads(args.reference_result.read_text())
        fields = ("owner", "ownerplayer", "sector", "x", "y", "z", "angle", "extra", "event")
        canonical = lambda rows: [{key: row.get(key) for key in fields} for row in rows]
        checks = {"passing_native_reference": bool(reference.get("passed"))}
        for name in ("selected", "too_far", "quick"):
            prior, current = reference.get(name, {}), result[name]
            checks[name + "_native_impact_fields_equal"] = canonical(prior.get("authoritative_knees", [])) == canonical(current.get("authoritative_knees", []))
            checks[name + "_native_ammo_equal"] = all(prior.get("shooter_after", {}).get(key) == current.get("shooter_after", {}).get(key) for key in ("ammo0", "ammo1"))
        result["native_reference_comparison"] = {"checks": checks, "compared_fields": fields,
            "reference_binary_sha256": reference.get("binary_sha256"),
            "qualification": "impact and ammo only; allocation indices, clocks and ambient RNG/damage magnitudes are not equality assertions"}
        result["passed"] = result["passed"] and all(checks.values())
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
