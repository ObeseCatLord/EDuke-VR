#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prove stock tripmine arming/beam and timer lifecycles in CPU-only MP.

The fixture configures a real weapon and observes native actors; this runner
only sends normal private SDL key input.  It is deliberately separate from
placement/range tests so a lifecycle failure retains its own lab evidence.
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

from smoke_hand_shots import room
from smoke_native_levels import assert_cpu_binary, assert_gpu_devices_absent, sanitised_env
from smoke_pipebomb_native import Run, join, sha256, write_lab

TRIPBOMB, LASERLINE, EXPLOSION2 = 2566, 2567, 1890
TRIPBOMB_WEAPON = 8
FIRE, FORWARD, BACK, LEFT, RIGHT = 228, 26, 22, 4, 7
FIELD = re.compile(r"addlog vrtrip_(\w+)(?: \(player \d+\))? = (-?\d+)")
PLAYER_KEYS = ("tick", "player", "index", "ammo", "weapon", "frame", "health", "x", "y", "z", "angle")
ACTOR_KEYS = ("actor", "tile", "event", "owner", "ownerplayer", "sector", "stat", "xa", "ya", "za", "anglea", "t1", "t3", "t5", "t6", "t7", "hitag", "xrepeat", "yrepeat", "clock")


def rows(text, keys):
    found, row = [], {}
    for key, value in FIELD.findall(text):
        if key not in keys:
            continue
        if key == keys[0]:
            row = {}
        row[key] = int(value)
        if key == keys[-1] and len(row) == len(keys):
            found.append(row)
    return found


def players(text, player=None):
    values = rows(text, PLAYER_KEYS)
    return [row for row in values if player is None or row["player"] == player]


def latest_player(text, player):
    values = players(text, player)
    return values[-1] if values else None


def actors(text, tile=None, event=None, owner=None):
    values = rows(text, ACTOR_KEYS)
    return [row for row in values if (tile is None or row["tile"] == tile)
            and (event is None or row["event"] == event)
            and (owner is None or row["ownerplayer"] == owner)]


def reexec_sandbox(args):
    if args._sandboxed:
        return
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise RuntimeError("bubblewrap is required for the CPU-only runner")
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    child_args = [arg for arg in sys.argv[1:] if arg != "--_sandboxed"] + ["--_sandboxed"]
    safe = sanitised_env()
    command = [bwrap, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
               "--unshare-pid", "--bind", str(work), str(work), "--chdir", str(Path.cwd()), "--clearenv"]
    for key in ("PATH", "LANG", "LC_ALL", "TZ"):
        if key in safe:
            command += ["--setenv", key, safe[key]]
    command += [sys.executable, str(Path(__file__).resolve()), *child_args]
    os.execvpe(bwrap, command, safe)


def configure_lab(root, role, args, mode, lifetime):
    lab = write_lab(root, role, args.grp)
    fixture = (HERE / "fixtures" / "tripmine_lifecycle.con").read_text()
    fixture = fixture.replace("gamevar TRIPBOMB_CONTROL 1 0", f"gamevar TRIPBOMB_CONTROL {mode} 0")
    fixture = fixture.replace("gamevar STICKYBOMB_LIFETIME 18 0", f"gamevar STICKYBOMB_LIFETIME {lifetime} 0")
    (lab / "pipebomb_test.con").write_text(fixture)
    (lab / "pipebomb.map").write_bytes(room(closed=True))
    return lab


def moving(run, scan, seconds):
    run.key("client", scan, True)
    run.observers["server"].pause(seconds)
    run.key("client", scan, False)


def wait_for_player(observer, player, predicate, timeout, message):
    observer.wait(lambda text: (latest_player(text, player) is not None and predicate(latest_player(text, player))),
                  timeout=timeout)
    value = latest_player(observer.text(), player)
    if value is None:
        raise RuntimeError(message)
    return value


def run_case(args, case, port):
    mode, lifetime = ((1, 18) if case == "beam" else (2, 20))
    prefix = "tripmine-lifecycle-tracked-" if args.tracked else "tripmine-lifecycle-"
    root = Path(tempfile.mkdtemp(prefix=f"{prefix}{case}-", dir=args.work_dir.resolve()))
    args.port = port
    run, phase = Run(args, root), "setup"
    result = {"passed": False, "case": case, "evidence_directory": str(root)}
    try:
        for role in ("server", "client"):
            run.labs[role] = configure_lab(root, role, args, mode, lifetime)
        if args.tracked:
            # The helper publishes a test pose through this owned FIFO; the
            # engine still performs the negotiated native shot and actor work.
            run.env["EDUKE32_XR_TEST_SHOTS"] = "1"
        phase = "native dedicated server"
        server = run.launch("server", ["-dedicated", "-c1", "-m", "-port", str(port), "-map", "pipebomb.map"])
        server.wait(lambda text: "Multiplayer server initialized." in text, timeout=18)
        phase = "native client join"
        player = join(run)
        client = run.observers["client"]
        wait_for_player(server, player, lambda row: row["weapon"] == TRIPBOMB_WEAPON and row["ammo"] == 6, 12,
                        "client weapon setup was not observed on server")
        wait_for_player(client, player, lambda row: row["weapon"] == TRIPBOMB_WEAPON and row["ammo"] == 6, 12,
                        "client weapon setup was not observed locally")
        tracked = {"enabled": args.tracked}
        if args.tracked:
            phase = "tracked released pose"
            os.write(run.writers["client"], b"pose 3 192 77 1843 32051 6813 0\n")
            client.wait(lambda text: "pose published flags=3" in text, timeout=5)
            pose_tick = latest_player(server.text(), player)["tick"]
            released = wait_for_player(server, player, lambda row: row["tick"] >= pose_tick + 10 and row["frame"] == 0, 5,
                                       "tracked pose did not remain released for ten native ticks")
            tracked.update(pose=(192, 77, 1843, 32051, 6813, 0), pose_tick=pose_tick,
                           released_tick=released["tick"])
        run.audit()
        before = latest_player(server.text(), player)
        actor_offset, client_offset = len(server.text()), len(client.text())
        phase = "native tripmine placement"
        run.press("client", FIRE, .16)
        server.wait(lambda text: (latest_player(text, player) is not None and
                                  latest_player(text, player)["ammo"] == before["ammo"] - 1 and
                                  bool(actors(text[actor_offset:], TRIPBOMB, 170, player))), timeout=8)
        spawned = actors(server.text()[actor_offset:], TRIPBOMB, 170, player)[-1]
        mine_index = spawned["actor"]
        if args.tracked:
            server.wait(lambda text: "VR native tripmine:" in text[actor_offset:], timeout=6)
            tracked["server_trace"] = next(line.strip() for line in server.text()[actor_offset:].splitlines()
                                           if "VR native tripmine:" in line)
            tracked["physical_placement"] = (spawned["xa"], spawned["ya"], spawned["za"])
        client.wait(lambda text: bool([row for row in actors(text[client_offset:], TRIPBOMB, 65, player)
                                       if row["actor"] == mine_index]), timeout=10)
        replicated = [row for row in actors(client.text()[client_offset:], TRIPBOMB, 65, player)
                      if row["actor"] == mine_index][-1]

        if case == "beam":
            phase = "native player leaves arming radius"
            # Sideways movement first carries the real client outside the
            # y=4096 beam before it can arm.  Moving backward first would put
            # the client on the just-created line and test only arm-on-contact.
            moving(run, LEFT, 1.2)
            away = wait_for_player(server, player,
                                   lambda row: (row["x"] - spawned["xa"]) ** 2 + (row["y"] - spawned["ya"]) ** 2 > 768 ** 2,
                                   5, "native movement did not leave mine arming radius")
            phase = "native tripwire arms and creates laserline"
            server.wait(lambda text: any(row["actor"] == mine_index and row["t1"] >= 33
                                         for row in actors(text[actor_offset:], TRIPBOMB, 65, player)), timeout=12)
            server.wait(lambda text: bool(actors(text[actor_offset:], LASERLINE, 65)), timeout=8)
            lasers = actors(server.text()[actor_offset:], LASERLINE, 65)
            # Cross y=4096 using actual SDL movement only after the native
            # actor has produced its stock laserline sprites.
            phase = "native player walks through live beam"
            health_before = latest_player(server.text(), player)["health"]
            health_armed_client = latest_player(client.text(), player)["health"]
            moving(run, RIGHT, 1.8)
            server.wait(lambda text: any(row["actor"] == mine_index and row["t6"] == 3 and row["t3"] > 0
                                         for row in actors(text[actor_offset:], TRIPBOMB, 65, player)), timeout=8)
            server.wait(lambda text: latest_player(text, player) is not None and
                        latest_player(text, player)["health"] < health_before, timeout=8)
            server_after = latest_player(server.text(), player)
            client.wait(lambda text: latest_player(text, player) is not None and
                        latest_player(text, player)["health"] == server_after["health"], timeout=8)
            mine_rows = [row for row in actors(server.text()[actor_offset:], TRIPBOMB, 65, player) if row["actor"] == mine_index]
            checks = {
                "real_client_left_native_768_arming_radius": (away["x"] - spawned["xa"]) ** 2 + (away["y"] - spawned["ya"]) ** 2 > 768 ** 2,
                "native_tripmine_advanced_to_armed_state": any(row["t1"] >= 33 for row in mine_rows),
                "native_LASERLINE_created_before_crossing": bool(lasers),
                "native_beam_crossing_started_stock_detonation": any(row["t6"] == 3 and row["t3"] > 0 for row in mine_rows),
                "native_explosion_damaged_actual_client": server_after["health"] < health_before,
                "native_damage_replicated_to_live_client": latest_player(client.text(), player)["health"] == server_after["health"],
                "no_gpu_devices_or_libraries": True,
            }
            if args.tracked:
                checks.update({
                    "tracked_native_trace": "VR native tripmine:" in tracked["server_trace"],
                    "tracked_pose_released_for_ten_native_ticks": tracked["released_tick"] >= tracked["pose_tick"] + 10,
                    "tracked_mine_uses_physical_hand_placement": tracked["physical_placement"] != (1142, 4096, -8928),
                    "tracked_client_unchanged_while_beam_arms": health_armed_client == health_before,
                })
            result.update(player=player, mine=spawned, replicated_mine=replicated, away_player=away,
                          laserlines=lasers[-12:], health_before=health_before,
                          server_player_after=server_after, client_player_after=latest_player(client.text(), player),
                          tracked=tracked, checks=checks)
        else:
            phase = "native timed fuse countdown"
            # EVENT_GAME observes the stock actor after its first decrement.
            server.wait(lambda text: any(row["actor"] == mine_index and row["t6"] == 1 and row["t7"] in (lifetime, lifetime - 1)
                                         for row in actors(text[actor_offset:], TRIPBOMB, 65, player)), timeout=8)
            armed = [row for row in actors(server.text()[actor_offset:], TRIPBOMB, 65, player)
                     if row["actor"] == mine_index and row["t6"] == 1]
            health_before = latest_player(server.text(), player)["health"]
            health_fusing_client = latest_player(client.text(), player)["health"]
            server.wait(lambda text: any(row["actor"] == mine_index and row["t6"] == 3 and row["t3"] > 0
                                         for row in actors(text[actor_offset:], TRIPBOMB, 65, player)), timeout=8)
            server.wait(lambda text: latest_player(text, player) is not None and
                        latest_player(text, player)["health"] < health_before, timeout=8)
            server_after = latest_player(server.text(), player)
            client.wait(lambda text: latest_player(text, player) is not None and
                        latest_player(text, player)["health"] == server_after["health"], timeout=8)
            mine_rows = [row for row in actors(server.text()[actor_offset:], TRIPBOMB, 65, player) if row["actor"] == mine_index]
            checks = {
                "native_timer_mode_and_nonrandom_fuse": any(row["t6"] == 1 and row["t7"] in (lifetime, lifetime - 1) for row in armed),
                "native_timed_fuse_counts_down": len({row["t7"] for row in armed}) >= 2 and min(row["t7"] for row in armed) < lifetime,
                "native_timer_started_stock_detonation": any(row["t6"] == 3 and row["t3"] > 0 for row in mine_rows),
                "native_timed_explosion_damaged_actual_client": server_after["health"] < health_before,
                "native_timed_damage_replicated_to_live_client": latest_player(client.text(), player)["health"] == server_after["health"],
                "no_gpu_devices_or_libraries": True,
            }
            if args.tracked:
                checks.update({
                    "tracked_native_trace": "VR native tripmine:" in tracked["server_trace"],
                    "tracked_pose_released_for_ten_native_ticks": tracked["released_tick"] >= tracked["pose_tick"] + 10,
                    "tracked_mine_uses_physical_hand_placement": tracked["physical_placement"] != (1142, 4096, -8928),
                    "tracked_client_unchanged_while_fuse_runs": health_fusing_client == health_before,
                })
            result.update(player=player, mine=spawned, replicated_mine=replicated, fuse_samples=armed[-16:],
                          health_before=health_before, server_player_after=server_after,
                          client_player_after=latest_player(client.text(), player), tracked=tracked, checks=checks)
        run.audit()
        result["passed"] = all(result["checks"].values())
    except Exception as error:
        result.update(phase=phase, error=str(error))
    finally:
        run.close()
        (root / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "input-helper", "grp", "work-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--reference-binary", type=Path,
                        help="optional immutable CPU binary for the same stock-lifecycle baseline")
    parser.add_argument("--port", type=int, default=24756)
    parser.add_argument("--case", choices=("beam", "timer", "all"), default="all")
    parser.add_argument("--tracked", action="store_true", help="publish a negotiated simulated hand pose through the SDL helper")
    parser.add_argument("--_sandboxed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.binary, args.input_helper, args.grp = (args.binary.resolve(), args.input_helper.resolve(), args.grp.resolve())
    if args.reference_binary:
        args.reference_binary = args.reference_binary.resolve()
    if args.tracked and args.reference_binary:
        parser.error("--tracked qualifies the current binary only; omit --reference-binary")
    required = (args.binary, args.input_helper, args.grp) + ((args.reference_binary,) if args.reference_binary else ())
    if not all(path.is_file() for path in required):
        parser.error("--binary, --input-helper, --grp, and optional --reference-binary must name existing files")
    reexec_sandbox(args)
    assert_gpu_devices_absent()
    assert_cpu_binary(args.binary)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    cases = ("beam", "timer") if args.case == "all" else (args.case,)
    def execute(binary, port):
        args.binary = binary
        assert_cpu_binary(binary)
        values = [run_case(args, case, port + index) for index, case in enumerate(cases)]
        return {"binary_sha256": sha256(binary), "cases": values, "passed": all(case["passed"] for case in values)}
    current_binary = args.binary
    current = execute(current_binary, args.port)
    reference = execute(args.reference_binary, args.port + 10) if args.reference_binary else None
    result = {"passed": current["passed"] and (reference is None or reference["passed"]), "current": current,
              "reference": reference, "tracked": args.tracked,
              "renderer": "CPU classic with simulated native pose (no OpenXR/GPU proof)" if args.tracked else "CPU classic (no OpenXR, GPU, or desktop-input proof)"}
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
