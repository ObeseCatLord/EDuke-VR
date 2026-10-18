#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""CPU-only stock tripmine reference in a GPU-denied native MP lab.

The fixture only prepares native player state and records engine callbacks.
This runner sends the ordinary RCTRL input through the private SDL FIFO; stock
weapon firing, HANDHOLDINGLASER placement, actor logic, replication and F12
capture remain in the game executable.
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
TRIPBOMB = 2566
TRIPBOMB_WEAPON = 8
FIRE_SCAN = 228  # SDL_SCANCODE_RCTRL
PLAYER_FIELD = re.compile(r"addlog vrtrip_(\w+)(?: \(player \d+\))? = (-?\d+)")


def rows(text, prefix, start, end):
    result, row = [], {}
    for key, value in PLAYER_FIELD.findall(text):
        if prefix == "" and (key.startswith("mine_") or key.startswith("post_")):
            continue
        if not key.startswith(prefix):
            continue
        key = key[len(prefix):]
        if key == start:
            row = {}
        row[key] = int(value)
        if key == end:
            result.append(row)
    return result


def players(text, player=None):
    result = rows(text, "", "tick", "angle")
    return [row for row in result if player is None or row.get("player") == player]


def mines(text):
    return rows(text, "mine_", "index", "event")


def latest_player(text, player):
    values = players(text, player)
    return values[-1] if values else None


def native_mines(text, player=None, event=None):
    result = [row for row in mines(text) if row.get("tile") == TRIPBOMB]
    if player is not None:
        result = [row for row in result if row.get("ownerplayer") == player]
    if event is not None:
        result = [row for row in result if row.get("event") == event]
    return result


def post_returns(text):
    return [int(value) for key, value in PLAYER_FIELD.findall(text) if key == "post_return"]


def close_enough(server, client):
    exact = ("owner", "ownerplayer", "sector", "stat", "angle", "t0", "t5", "t6", "t7", "hitag")
    return (all(server.get(key) == client.get(key) for key in exact) and
            all(abs(server.get(key, 0) - client.get(key, 0)) <= 16 for key in ("x", "y", "z")))


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
    command += [sys.executable, str(Path(sys.argv[0]).resolve()), *child_args]
    os.execvpe(bwrap, command, safe)


def configure_lab(root, role, args, shooter_x):
    lab = write_lab(root, role, args.grp)
    fixture = (HERE / "fixtures" / "tripmine_test.con").read_text()
    fixture = fixture.replace("gamevar vrtrip_controlled_x 1024 0",
                              f"gamevar vrtrip_controlled_x {shooter_x} 0")
    (lab / "pipebomb_test.con").write_text(fixture)
    (lab / "pipebomb.map").write_bytes(room(closed=True))
    return lab


def run_case(args, shooter_x, capture, port):
    root = Path(tempfile.mkdtemp(prefix="tripmine-native-", dir=args.work_dir.resolve()))
    # smoke_pipebomb_native.join deliberately reads args.port.  Keep each
    # bounded sequential case connected to its own dedicated server.
    args.port = port
    run = Run(args, root)
    phase = "setup"
    result = {"passed": False, "shooter_x": shooter_x, "root": str(root)}
    try:
        for role in ("server", "client"):
            run.labs[role] = configure_lab(root, role, args, shooter_x)
        phase = "native dedicated server"
        server = run.launch("server", ["-dedicated", "-c1", "-m", "-port", str(port), "-map", "pipebomb.map"])
        server.wait(lambda text: "Multiplayer server initialized." in text, timeout=18)
        phase = "native client join"
        player = join(run)
        client = run.observers["client"]
        server.wait(lambda text: (latest_player(text, player) is not None and
                                  latest_player(text, player).get("weapon_now") == TRIPBOMB_WEAPON and
                                  latest_player(text, player).get("ammo") == 6), timeout=12)
        client.wait(lambda text: (latest_player(text, player) is not None and
                                  latest_player(text, player).get("weapon_now") == TRIPBOMB_WEAPON and
                                  latest_player(text, player).get("ammo") == 6), timeout=12)
        run.audit()
        before = latest_player(server.text(), player)
        server_offset, client_offset = len(server.text()), len(client.text())
        phase = "native tripmine fire"
        run.press("client", FIRE_SCAN, .16)
        if shooter_x == 1024:
            server.wait(lambda text: (latest_player(text, player) is not None and
                                      latest_player(text, player).get("ammo") == before["ammo"] - 1 and
                                      bool(native_mines(text[server_offset:], player, 170))), timeout=8)
            server_mines = native_mines(server.text()[server_offset:], player)
            spawned = {row["index"] for row in server_mines if row.get("event") == 170}
            postweapon_mine = next(row for row in reversed(server_mines) if row.get("event") == 170)
            server_event_game_mine = next(row for row in reversed(server_mines) if row.get("event") == 65)
            phase = "native client tripmine replication"
            client.wait(lambda text: bool(native_mines(text[client_offset:], player, 65)), timeout=10)
            replicated = next(row for row in reversed(native_mines(client.text()[client_offset:], player, 65))
                              if row.get("index") == postweapon_mine["index"])
            screenshot = None
            if capture:
                phase = "native F12 after replicated mine"
                screenshot = run.capture("client")
            run.audit()
            after_server, after_client = latest_player(server.text(), player), latest_player(client.text(), player)
            checks = {
                "native_weapon8_consumes_one_ammo": after_server["ammo"] == before["ammo"] - 1,
                "native_POSTWEAPONSHOOT_returns_one_TRIPBOMB": (len(spawned) == 1 and postweapon_mine.get("tile") == TRIPBOMB and
                                                                   postweapon_mine["index"] in post_returns(server.text()[server_offset:])),
                "native_owner_and_sector": postweapon_mine.get("ownerplayer") == player and postweapon_mine.get("sector") == 0,
                "native_wall_normal_angle": postweapon_mine.get("angle") == 1024 and postweapon_mine.get("t5") == 1024,
                "native_tripwire_state": postweapon_mine.get("t6") == 0 and postweapon_mine.get("t7") == 0 and postweapon_mine.get("hitag") == postweapon_mine.get("index"),
                "native_live_client_EVENT_GAME_tripmine": replicated.get("tile") == TRIPBOMB and replicated.get("ownerplayer") == player,
                "server_client_tripmine_convergence": close_enough(server_event_game_mine, replicated),
                "native_totalclock_advances": len({row.get("totalclock") for row in native_mines(server.text()[server_offset:], player, 65)}) >= 2,
                "native_ammo_and_weapon_replicate": after_client.get("ammo") == after_server.get("ammo") and after_client.get("weapon_now") == TRIPBOMB_WEAPON,
                "native_F12_after_replicated_mine": bool(screenshot),
                "no_gpu_devices_or_libraries": True,
            }
            result.update(passed=all(checks.values()), checks=checks, player=player, ammo_before=before["ammo"],
                          postweapon_mine=postweapon_mine, server_event_game_mine=server_event_game_mine,
                          replicated_mine=replicated,
                          server_player_after=after_server, client_player_after=after_client, screenshot=screenshot)
        else:
            server.wait(lambda text: latest_player(text, player) is not None and
                        latest_player(text, player).get("tick", 0) >= before["tick"] + 12 and
                        latest_player(text, player).get("frame") == 0, timeout=7)
            run.audit()
            after_server, after_client = latest_player(server.text(), player), latest_player(client.text(), player)
            appeared = native_mines(server.text()[server_offset:], player) or native_mines(client.text()[client_offset:], player)
            checks = {
                "too_far_native_placement_keeps_ammo": after_server["ammo"] == before["ammo"] == 6,
                "too_far_native_placement_has_no_tripmine_actor": not appeared,
                "too_far_client_ammo_converges": after_client.get("ammo") == after_server.get("ammo"),
                "no_gpu_devices_or_libraries": True,
            }
            result.update(passed=all(checks.values()), checks=checks, player=player, ammo_before=before["ammo"],
                          server_player_after=after_server, client_player_after=after_client,
                          observed_mines=appeared)
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
                        help="compare flat placement fields against a saved passing native reference")
    parser.add_argument("--port", type=int, default=24747)
    parser.add_argument("--_sandboxed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.port <= 65534:
        parser.error("--port must be in 1..65534")
    args.binary, args.input_helper, args.grp = (args.binary.resolve(), args.input_helper.resolve(), args.grp.resolve())
    if args.reference_result:
        args.reference_result = args.reference_result.resolve()
    if not args.binary.is_file() or not args.input_helper.is_file() or not args.grp.is_file():
        parser.error("--binary, --input-helper, and --grp must name existing files")
    reexec_sandbox(args)
    assert_gpu_devices_absent()
    assert_cpu_binary(args.binary)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    valid = run_case(args, shooter_x=1024, capture=True, port=args.port)
    too_far = run_case(args, shooter_x=512, capture=False, port=args.port + 1)
    result = {
        "passed": valid.get("passed", False) and too_far.get("passed", False),
        "renderer": "CPU classic (no VR/SPS proof)",
        "binary_sha256": sha256(args.binary),
        "valid": valid,
        "too_far": too_far,
    }
    if args.reference_result:
        reference = json.loads(args.reference_result.read_text())
        fields = ("tile", "owner", "ownerplayer", "sector", "stat", "x", "y", "z", "angle",
                  "t0", "t1", "t2", "t5", "t6", "t7")
        expected = reference.get("valid", {}).get("postweapon_mine", {})
        observed = valid.get("postweapon_mine", {})
        checks = {
            "passing_native_reference": bool(reference.get("passed")),
            "native_flat_mine_fields_equal": all(key in expected and key in observed and
                                                  expected[key] == observed[key] for key in fields),
            "native_flat_ammo_equal": reference.get("valid", {}).get("server_player_after", {}).get("ammo")
                                      == valid.get("server_player_after", {}).get("ammo") == 5,
            "native_range_rejection_equal": reference.get("too_far", {}).get("server_player_after", {}).get("ammo")
                                            == too_far.get("server_player_after", {}).get("ammo") == 6,
        }
        result["native_reference_comparison"] = {
            "checks": checks, "compared_fields": fields,
            "reference_binary_sha256": reference.get("binary_sha256"),
            "qualification": "placement fields/ammo only; clocks and allocation generations are not compared",
        }
        result["passed"] = result["passed"] and all(checks.values())
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
