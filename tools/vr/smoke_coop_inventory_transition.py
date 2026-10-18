#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""CPU-only native co-op exit regression; run with the owned WorldTour GRP."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from smoke_actions_multiplayer import client_player_index
from smoke_hand_shots import room
from smoke_multiplayer import CONFIG
from smoke_native_levels import assert_cpu_binary, assert_gpu_devices_absent, sanitised_env
from smoke_pistol_reload_native import FIRE_BIT, FIRE_SCAN, Run, sha256
from smoke_starting_inventory import INITIAL_EVENTS, events, expected_inventory, inventory, latest, rows


SYNC = "Multiplayer client level synchronization complete."
FORWARD_SCAN = 26  # SDL_SCANCODE_W
MODE_GAME = 4
FIELD = re.compile(r"addlog vrtrans_(\w+)(?: \(player \d+\))? = (-?\d+)")
ROW_KEYS = ("tick", "player", "x", "y", "fvel", "svel", "bits", "gm", "volume", "level")


def reexec_sandbox(args):
    if args._sandboxed:
        return
    bwrap, nice = shutil.which("bwrap"), shutil.which("nice")
    if not bwrap or not nice:
        raise RuntimeError("bubblewrap and nice are required for the CPU-only runner")
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    safe = sanitised_env()
    child_args = [arg for arg in sys.argv[1:] if arg != "--_sandboxed"] + ["--_sandboxed"]
    command = [bwrap, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
               "--unshare-pid", "--unshare-net", "--bind", str(work), str(work), "--chdir", str(Path.cwd()), "--clearenv"]
    for key in ("PATH", "LANG", "LC_ALL", "TZ"):
        if key in safe:
            command += ["--setenv", key, safe[key]]
    command += [nice, "-n", "10", sys.executable, str(Path(__file__).resolve()), *child_args]
    os.execvpe(bwrap, command, safe)


def levels(text, player=None):
    result, row = [], {}
    for key, value in FIELD.findall(text):
        if key == "tick":
            row = {}
        if key in ROW_KEYS:
            row[key] = int(value)
        if key == "level" and all(name in row for name in ROW_KEYS):
            if player is None or row["player"] == player:
                result.append(row)
    return result


def on_second(text, player):
    row = latest(levels(text, player))
    return bool(row) and row["volume"] == 0 and row["level"] == 1 and bool(row["gm"] & MODE_GAME)


def write_lab(root, role, grp):
    lab = root / role
    lab.mkdir()
    (lab / "DUKE3D.GRP").symlink_to(grp)
    (lab / "eduke32.cfg").write_text(CONFIG.replace("ScreenBPP = 32", "ScreenBPP = 8"))
    with (lab / "eduke32.cfg").open("a") as config:
        config.write(f'\n[Comm Setup]\nPlayerName = "CoopTransition{role.title()}"\n')
    (lab / "autoexec.cfg").write_text("r_maxfps 30\n")
    for name in ("starting_inventory_stock_test.con", "starting_inventory_test.con", "coop_inventory_transition_test.con"):
        shutil.copyfile(HERE / "fixtures" / name, lab / name)
    first, second = bytearray(room()), bytearray(room())
    # A_Spawn classifies APLAYER starts from lotag: 1 selects co-op. Keep the
    # helper's initial status; the native spawn path establishes STAT_PLAYER.
    sprite_offset = 22 + 2 * 40 + 2 + 8 * 32 + 2
    for game_map in (first, second):
        for index in range(4):
            offset = sprite_offset + index * 44
            if struct.unpack_from("<h", game_map, offset + 24)[0] != 0:
                raise RuntimeError("generated co-op start left sector 0")
            struct.pack_into("<h", game_map, offset + 38, 1)  # co-op start lotag
    struct.pack_into("<h", first, 22 + 40 + 34, -1)  # sector 1: native EOL exit
    (lab / "first.map").write_bytes(first)
    (lab / "second.map").write_bytes(second)
    return lab


def run_case(args, root):
    run = Run(args, root, args.binary, "coop_inventory_transition_test.con")
    result = {"passed": False, "expected_inventory": {"weapon": 1, "owned": 1, "ammo": 17, "shield": 37}, "phase": "setup"}
    try:
        for role in ("server", "client"):
            run.labs[role] = write_lab(root, role, args.grp)
        result["phase"] = "initial native server"
        server = run.launch("server", ["-dedicated", "-c2", "-v1", "-l1", "-port", str(args.port)])
        server.wait(lambda text: "Multiplayer server initialized." in text, timeout=18)
        server.pause(2)
        initial_events = events(server.text(), 0)
        if tuple(initial_events[:initial_events.index("ENTERLEVEL") + 1]) != INITIAL_EVENTS:
            raise RuntimeError(f"unexpected initial player0 events: {initial_events}")

        result["phase"] = "native client join"
        client = run.launch("client", ["-connect", f"127.0.0.1:{args.port}"])
        client.wait(lambda text: SYNC in text, timeout=25)
        client.wait(lambda text: client_player_index(text) not in (None, 0), timeout=14)
        player = client_player_index(client.text())
        result["client_player"] = player
        result["phase"] = "hook-policy inventory replication"
        server.wait(lambda text: expected_inventory(latest(rows(text, player)), 17, 37), timeout=14)
        client.wait(lambda text: expected_inventory(latest(rows(text, player)), 17, 37), timeout=14)
        server_before, client_before = latest(rows(server.text(), player)), latest(rows(client.text(), player))
        if inventory(server_before) != inventory(client_before):
            raise RuntimeError("server and client initial inventory differ")

        result["phase"] = "ordinary RCTRL fire"
        fire_offset = len(server.text())
        run.key(FIRE_SCAN, True)
        try:
            server.wait(lambda text: any(row["bits"] & FIRE_BIT and row["ammo"] < 17 for row in rows(text[fire_offset:], player)), timeout=10)
        finally:
            run.key(FIRE_SCAN, False)
        server.wait(lambda text: bool(latest(rows(text, player))) and latest(rows(text, player))["ammo"] < 17 and not (latest(rows(text, player))["bits"] & FIRE_BIT), timeout=12)
        client.wait(lambda text: bool(latest(rows(text, player))) and latest(rows(text, player))["ammo"] < 17 and not (latest(rows(text, player))["bits"] & FIRE_BIT), timeout=12)
        server.wait(lambda text: inventory(latest(rows(text, player))) == inventory(latest(rows(client.text(), player))), timeout=12)
        pre_server, pre_client = latest(rows(server.text(), player)), latest(rows(client.text(), player))
        if inventory(pre_server) != inventory(pre_client):
            raise RuntimeError("post-fire inventory did not settle identically")

        result["phase"] = "ordinary W native exit"
        server_transition_offset, client_transition_offset = len(server.text()), len(client.text())
        start = latest(levels(server.text(), player))
        run.key(FORWARD_SCAN, True)
        try:
            server.wait(lambda text: on_second(text, player), timeout=12)
        finally:
            run.key(FORWARD_SCAN, False)
        client.wait(lambda text: on_second(text, player), timeout=14)
        server.wait(lambda text: inventory(latest(rows(text, player))) == inventory(latest(rows(client.text(), player))), timeout=12)
        post_server, post_client = latest(rows(server.text(), player)), latest(rows(client.text(), player))
        transition_server = server.text()[server_transition_offset:]
        transition_client = client.text()[client_transition_offset:]
        moved = any((row["x"], row["y"]) != (start["x"], start["y"]) and row["fvel"] for row in levels(transition_server, player))
        reset_events = {role: {p: [event for event in events(text, p) if event in ("RESETWEAPONS", "RESETINVENTORY")]
                         for p in (0, player)} for role, text in (("server", transition_server), ("client", transition_client))}
        checks = {
            "W_moves_client_through_the_only_exit": moved,
            "server_and_client_reach_second_level_mode_game": on_second(server.text(), player) and on_second(client.text(), player),
            "post_fire_inventory_is_exactly_preserved": inventory(post_server) == inventory(pre_server) == inventory(pre_client) == inventory(post_client),
            "no_native_reset_hooks_during_transition": not any(values for peers in reset_events.values() for values in peers.values()),
        }
        result.update(phase="complete", checks=checks, pre_fire=server_before, post_fire=pre_server,
                      post_transition_server=post_server, post_transition_client=post_client,
                      transition_reset_events=reset_events, passed=all(checks.values()))
        run.audit()
    except Exception as error:
        result.update(error=str(error))
    finally:
        run.close()
        result["cleanup"] = all(process.poll() is not None for process in run.processes.values())
        (root / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "input-helper", "grp", "work-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--port", type=int, default=24788)
    parser.add_argument("--_sandboxed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.port < 65535:
        parser.error("--port must be in 1..65534")
    for name in ("binary", "input_helper", "grp"):
        setattr(args, name, getattr(args, name).resolve())
    if not all(path.is_file() for path in (args.binary, args.input_helper, args.grp)):
        parser.error("--binary, --input-helper, and --grp must name existing files")
    reexec_sandbox(args)
    assert_gpu_devices_absent()
    assert_cpu_binary(args.binary)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="native-coop-inventory-", dir=args.work_dir.resolve()))
    result = {"passed": False, "root": str(root), "renderer": "CPU classic SDL dummy (no XR/GPU)",
              "binary_sha256": sha256(args.binary), "grp_sha256": sha256(args.grp)}
    try:
        result["transition"] = run_case(args, root)
        result["passed"] = bool(result["transition"]["passed"]) and bool(result["transition"]["cleanup"])
    finally:
        (root / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
