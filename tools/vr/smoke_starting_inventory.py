#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""CPU-only native co-op starting-inventory regression.

This uses the real RESETINVENTORY/RESETWEAPONS hooks and an ordinary client
RCTRL key through the private SDL FIFO.  It never fabricates packets or edits
the owned GRP.  Reproduce with:
  python3 tools/vr/smoke_starting_inventory.py --binary work/eduke32-cpu-input \\
    --input-helper work/headless_vr_input.so --grp '/home/obesecatlord/Windows/Steam/steamapps/common/Duke Nukem 3D Twentieth Anniversary World Tour/DUKE3D.GRP' \\
    --work-dir work/native-starting-inventory
"""
import argparse
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

from smoke_pistol_reload_native import FIRE_BIT, FIRE_SCAN, Run, sha256
from smoke_actions_multiplayer import client_player_index
from smoke_multiplayer import CONFIG
from smoke_native_levels import assert_cpu_binary, assert_gpu_devices_absent


SYNC = "Multiplayer client level synchronization complete."
FIELD = re.compile(r"addlog vrinv_(\w+)(?: \(player \d+\))? = (-?\d+)")
ROW_KEYS = ("tick", "player", "weapon", "owned", "ammo", "shield", "bits")
EVENT_NAMES = {1: "RESETINVENTORY", 2: "RESETWEAPONS", 3: "RESETPLAYER",
               4: "NEWGAME", 5: "ENTERLEVEL"}
INITIAL_EVENTS = ("RESETWEAPONS", "RESETINVENTORY", "NEWGAME", "RESETPLAYER", "ENTERLEVEL")


def reexec_sandbox(args):
    """Enter the established private CPU bubblewrap lab for this runner."""
    if args._sandboxed:
        return
    bwrap, nice = shutil.which("bwrap"), shutil.which("nice")
    if not bwrap or not nice:
        raise RuntimeError("bubblewrap and nice are required for the CPU-only runner")
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    from smoke_native_levels import sanitised_env
    safe = sanitised_env()
    child_args = [arg for arg in sys.argv[1:] if arg != "--_sandboxed"] + ["--_sandboxed"]
    command = [bwrap, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
               "--unshare-pid", "--unshare-net", "--bind", str(work), str(work),
               "--chdir", str(Path.cwd()), "--clearenv"]
    for key in ("PATH", "LANG", "LC_ALL", "TZ"):
        if key in safe:
            command += ["--setenv", key, safe[key]]
    command += [nice, "-n", "10", sys.executable, str(Path(__file__).resolve()), *child_args]
    os.execvpe(bwrap, command, safe)


def rows(text, player=None):
    result, row = [], {}
    for key, value in FIELD.findall(text):
        if key == "tick":
            row = {}
        if key in ROW_KEYS:
            row[key] = int(value)
        if key == "bits" and all(name in row for name in ROW_KEYS):
            if player is None or row["player"] == player:
                result.append(row)
    return result


def events(text, player=0):
    result, code = [], None
    for key, value in FIELD.findall(text):
        if key == "event_code":
            code = int(value)
        elif key == "event_player" and code is not None:
            if int(value) == player:
                result.append(EVENT_NAMES.get(code, f"UNKNOWN({code})"))
            code = None
    return result


def initial_order_ok(sequence):
    try:
        return tuple(sequence[:sequence.index("ENTERLEVEL") + 1]) == INITIAL_EVENTS
    except ValueError:
        return False


def write_lab(root, role, grp):
    lab = root / role
    lab.mkdir()
    (lab / "DUKE3D.GRP").symlink_to(grp)
    (lab / "eduke32.cfg").write_text(CONFIG.replace("ScreenBPP = 32", "ScreenBPP = 8"))
    with (lab / "eduke32.cfg").open("a") as config:
        config.write(f'\n[Comm Setup]\nPlayerName = "Inventory{role.title()}"\n')
    (lab / "autoexec.cfg").write_text("r_maxfps 30\n")
    for fixture in ("starting_inventory_stock_test.con", "starting_inventory_test.con"):
        shutil.copyfile(HERE / "fixtures" / fixture, lab / fixture)
    return lab


def latest(values):
    return values[-1] if values else None


def inventory(row):
    return tuple(row[name] for name in ("weapon", "owned", "ammo", "shield"))


def expected_inventory(row, ammo, shield):
    return bool(row) and row["weapon"] == 1 and row["owned"] == 1 and row["ammo"] == ammo and (shield is None or row["shield"] == shield)


def run_case(args, root, label, fixture, expected_ammo, expected_shield, port):
    case_root = root / label
    case_root.mkdir()
    run = Run(args, case_root, args.binary, fixture)
    result = {"case": label, "fixture": fixture, "expected": {"weapon": 1, "owned": 1, "ammo": expected_ammo,
              "shield": expected_shield}, "passed": False, "phase": "setup"}
    try:
        for role in ("server", "client"):
            run.labs[role] = write_lab(case_root, role, args.grp)
        result["phase"] = "initial dedicated server"
        server = run.launch("server", ["-dedicated", "-c2", "-v1", "-l1", "-port", str(port)])
        server.wait(lambda text: "Multiplayer server initialized." in text, timeout=18)
        server.pause(2.0)
        initial_text = server.text()
        initial_rows = rows(initial_text, 0)
        initial = latest(initial_rows)
        timeline = events(initial_text, 0)
        initial_checks = {
            "initial_events_are_exact_reviewed_order": initial_order_ok(timeline),
            "server0_owns_pistol_with_stock_or_hook_policy": expected_inventory(initial, expected_ammo, expected_shield),
            "server0_shield_is_hook_policy": expected_shield is None or bool(initial) and initial["shield"] == expected_shield,
        }
        result.update(initial_server0=initial, server0_rows=initial_rows[-12:], server0_event_order=timeline,
                      initial_checks=initial_checks)
        if not all(initial_checks.values()):
            result.update(phase="initial server inventory diagnostic", error="initial server did not run the native reset policy")
            return result

        result["phase"] = "native client join"
        client = run.launch("client", ["-connect", f"127.0.0.1:{port}"])
        client.wait(lambda text: SYNC in text, timeout=25)
        client.wait(lambda text: client_player_index(text) is not None, timeout=14)
        player = client_player_index(client.text())
        if player is None or player <= 0:
            raise RuntimeError("client did not expose a non-server native player index")
        result["client_player"] = player
        result["phase"] = "replicated initial inventory"
        server.wait(lambda text: expected_inventory(latest(rows(text, player)), expected_ammo, expected_shield),
                    timeout=14)
        client.wait(lambda text: expected_inventory(latest(rows(text, player)), expected_ammo, expected_shield),
                    timeout=14)
        server_before, client_before = latest(rows(server.text(), player)), latest(rows(client.text(), player))
        matching_initial = inventory(server_before) == inventory(client_before)
        if not matching_initial:
            raise RuntimeError("server and joining client disagree on the initial native inventory")

        result["phase"] = "ordinary native RCTRL fire"
        server_offset, client_offset = len(server.text()), len(client.text())
        run.key(FIRE_SCAN, True)
        try:
            server.wait(lambda text: any(row["bits"] & FIRE_BIT and row["ammo"] < expected_ammo
                                         for row in rows(text[server_offset:], player)), timeout=10)
        finally:
            run.key(FIRE_SCAN, False)
        server.wait(lambda text: bool(latest(rows(text, player))) and latest(rows(text, player))["ammo"] < expected_ammo and not (latest(rows(text, player))["bits"] & FIRE_BIT), timeout=12)
        client.wait(lambda text: bool(latest(rows(text, player))) and latest(rows(text, player))["ammo"] < expected_ammo and not (latest(rows(text, player))["bits"] & FIRE_BIT), timeout=12)
        server.wait(lambda text: inventory(latest(rows(text, player))) == inventory(latest(rows(client.text(), player))), timeout=12)
        server_after, client_after = latest(rows(server.text(), player)), latest(rows(client.text(), player))
        checks = {
            "initial_server0_policy": all(initial_checks.values()),
            "joining_client_matches_server_before_fire": matching_initial,
            "RCTRL_reaches_authoritative_native_input": any(row["bits"] & FIRE_BIT for row in rows(server.text()[server_offset:], player)),
            "server_ammo_decreases_after_RCTRL": server_after["ammo"] < expected_ammo,
            "client_ammo_decreases_and_matches_server": client_after["ammo"] == server_after["ammo"] < expected_ammo,
            "both_peers_retain_pistol_ownership_after_fire": server_after["owned"] == client_after["owned"] == 1,
            "weapon_ownership_ammo_and_shield_stay_equal_after_fire": inventory(server_after) == inventory(client_after),
        }
        result.update(phase="complete", checks=checks, server_before=server_before, client_before=client_before,
                      server_after=server_after, client_after=client_after,
                      server_rows=rows(server.text(), player)[-12:], client_rows=rows(client.text(), player)[-12:],
                      passed=all(checks.values()))
    except Exception as error:
        result.update(error=str(error))
    finally:
        run.close()
        result["cleanup"] = all(process.poll() is not None for process in run.processes.values())
        (case_root / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "input-helper", "grp", "work-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--port", type=int, default=24778)
    parser.add_argument("--_sandboxed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.port < 65534:
        parser.error("--port must be in 1..65533")
    for name in ("binary", "input_helper", "grp"):
        setattr(args, name, getattr(args, name).resolve())
    if not all(path.is_file() for path in (args.binary, args.input_helper, args.grp)):
        parser.error("--binary, --input-helper, and --grp must name existing files")
    reexec_sandbox(args)
    assert_gpu_devices_absent()
    assert_cpu_binary(args.binary)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="native-starting-inventory-", dir=args.work_dir.resolve()))
    result = {"passed": False, "root": str(root), "renderer": "CPU classic SDL dummy (no XR/GPU)",
              "binary_sha256": sha256(args.binary), "input_helper_sha256": sha256(args.input_helper),
              "grp_sha256": sha256(args.grp)}
    try:
        stock = run_case(args, root, "stock", "starting_inventory_stock_test.con", 48, None, args.port)
        hooks = run_case(args, root, "reset_hooks", "starting_inventory_test.con", 17, 37, args.port + 1) if stock["passed"] else None
        result.update(stock=stock, reset_hooks=hooks,
                      passed=bool(stock["passed"]) and bool(hooks and hooks["passed"]))
    finally:
        (root / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
