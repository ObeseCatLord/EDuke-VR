#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""CPU-only native MP pistol-reload replication regression.

This starts one dedicated native server and one normal SDL-dummy client for
each requested network protocol binary. Omit --reference-binary for the
current-only gameplay check; supplying it additionally requires the old
stale-flag signature, whose occurrence depends on the native scheduling.  It drives the client's private FIFO
with the ordinary RCTRL fire key.  The CON fixture seeds only the initial
13-round pistol clip and then logs native player state; it neither changes
reload/counter state nor sends or alters packets.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from smoke_actions import Observer
from smoke_actions_multiplayer import client_player_index
from smoke_hand_shots import room
from smoke_multiplayer import CONFIG, stop
from smoke_native_levels import (assert_cpu_binary, assert_gpu_devices_absent,
                                 sanitised_env)


FIRE_SCAN = 228  # SDL_SCANCODE_RCTRL
FIRE_BIT = 4
PISTOL_WEAPON = 1
SYNC = "Multiplayer client level synchronization complete."
ROW_FIELD = re.compile(r"addlog vrrld_(\w+)(?: \(player \d+\))? = (-?\d+)")
ROW_KEYS = ("tick", "player", "counter", "reloading", "ammo", "weapon", "bits")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def reexec_sandbox(args):
    """Enter the existing GPU-denied bwrap setup at niceness 10."""
    if args._sandboxed:
        return
    bwrap = shutil.which("bwrap")
    nice = shutil.which("nice")
    if not bwrap or not nice:
        raise RuntimeError("bubblewrap and nice are required for the CPU-only runner")
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    safe = sanitised_env()
    child_args = [arg for arg in sys.argv[1:] if arg != "--_sandboxed"] + ["--_sandboxed"]
    command = [bwrap, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
               "--unshare-pid", "--unshare-net", "--bind", str(work), str(work), "--chdir", str(Path.cwd()),
               "--clearenv"]
    for key in ("PATH", "LANG", "LC_ALL", "TZ"):
        if key in safe:
            command += ["--setenv", key, safe[key]]
    command += [nice, "-n", "10", sys.executable, str(Path(__file__).resolve()), *child_args]
    os.execvpe(bwrap, command, safe)


def reload_rows(text, player=None):
    values, row = [], {}
    for key, value in ROW_FIELD.findall(text):
        if key == "tick":
            row = {}
        if key in ROW_KEYS:
            row[key] = int(value)
        if key == "bits" and all(name in row for name in ROW_KEYS):
            if player is None or row["player"] == player:
                values.append(row)
    return values


def last_row(text, player):
    values = reload_rows(text, player)
    return values[-1] if values else None


def rest_rows(text, player, count=3):
    values = reload_rows(text, player)
    return (len(values) >= count and all(row["counter"] == 0 and row["ammo"] == 12 and
                                         row["weapon"] == PISTOL_WEAPON
                                         for row in values[-count:]))


def bounded(rows, limit=18):
    return rows[-limit:]


def write_lab(root, role, grp):
    lab = root / role
    lab.mkdir()
    (lab / "DUKE3D.GRP").symlink_to(grp)
    (lab / "eduke32.cfg").write_text(CONFIG.replace("ScreenBPP = 32", "ScreenBPP = 8"))
    with (lab / "eduke32.cfg").open("a") as config:
        config.write(f'\n[Comm Setup]\nPlayerName = "Reload{role.title()}"\n')
    # Both binary pairs use the same deliberate low-FPS client setting.  It
    # makes a snapshot correction visible while retaining stock input/player
    # processing; the server stays at the normal test rate.
    (lab / "autoexec.cfg").write_text("r_maxfps 10\n" if role == "client" else "r_maxfps 30\n")
    for fixture in ("controller_test.con", "aim_test.con", "hand_test.con", "hitscan_test.con",
                    "pistol_reload_test.con"):
        shutil.copyfile(HERE / "fixtures" / fixture, lab / fixture)
    (lab / "reload.map").write_bytes(room())
    return lab


class Run:
    def __init__(self, args, root, binary, con_file="pistol_reload_test.con"):
        self.args, self.root, self.binary = args, root, binary
        self.con_file = con_file
        self.env = sanitised_env()
        self.labs = {}
        self.processes, self.observers, self.writers, self.logs = {}, {}, {}, []

    def audit(self):
        assert_gpu_devices_absent()
        for role, process in self.processes.items():
            if process.poll() is not None:
                raise RuntimeError(f"{role} exited during CPU-only reload test")
            maps = Path(f"/proc/{process.pid}/maps").read_text(errors="replace").lower()
            fds = []
            for fd in Path(f"/proc/{process.pid}/fd").iterdir():
                try:
                    fds.append(os.readlink(fd).lower())
                except FileNotFoundError:
                    pass
            if any(name in maps for name in ("libnvidia", "libglx", "libegl", "libvulkan")) or any(
                    "/dev/nvidia" in item or "/dev/dri" in item for item in fds):
                raise RuntimeError(f"{role} mapped a GPU library or device")

    def launch(self, role, command):
        lab = self.labs[role]
        env = dict(self.env)
        if role == "client":
            fifo = lab / "input.fifo"
            os.mkfifo(fifo, 0o600)
            if fifo.stat().st_mode & 0o077:
                raise RuntimeError("client input FIFO is not owner-only")
            self.writers[role] = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
            env.update(LD_PRELOAD=str(self.args.input_helper), EDUKE32_TEST_SDL_INPUT=str(fifo))
        log = (lab / "game.log").open("w")
        self.logs.append(log)
        process = subprocess.Popen([str(self.binary), "-usecwd", "-nosetup", "-noautoload", "-nologo",
                                    "-ns", "-nm", *command, "-x", self.con_file],
                                   cwd=lab, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT)
        self.processes[role] = process
        self.observers[role] = Observer(process, lab / "game.log")
        self.audit()
        return self.observers[role]

    def key(self, scan, down):
        os.write(self.writers["client"], f"key {scan} {int(down)}\n".encode())

    def close(self):
        for process in reversed(list(self.processes.values())):
            stop(process)
        for fd in self.writers.values():
            os.close(fd)
        for log in self.logs:
            log.close()


def run_pair(args, label, binary, port, root):
    pair_root = root / label
    pair_root.mkdir()
    run = Run(args, pair_root, binary)
    phase = "setup"
    result = {"label": label, "binary": str(binary), "binary_sha256": sha256(binary),
              "passed": False, "phase": phase, "checks": {}}
    player = None
    try:
        for role in ("server", "client"):
            run.labs[role] = write_lab(pair_root, role, args.grp)
        phase = "native dedicated server"
        server = run.launch("server", ["-dedicated", "-c1", "-m", "-port", str(port),
                                       "-map", "reload.map"])
        server.wait(lambda text: "Multiplayer server initialized." in text, timeout=18)
        phase = "native client join"
        client = run.launch("client", ["-connect", f"127.0.0.1:{port}"])
        client.wait(lambda text: SYNC in text, timeout=25)
        client.pause(1.6)
        client.wait(lambda text: client_player_index(text) is not None, timeout=12)
        player = client_player_index(client.text())
        if player is None or player <= 0:
            raise RuntimeError("client did not expose a real native player index")
        phase = "native pistol seed"
        server.wait(lambda text: (last_row(text, player) is not None and
                                  last_row(text, player)["ammo"] == 13 and
                                  last_row(text, player)["weapon"] == PISTOL_WEAPON and
                                  last_row(text, player)["counter"] == 0), timeout=14)
        client.wait(lambda text: (last_row(text, player) is not None and
                                  last_row(text, player)["ammo"] == 13 and
                                  last_row(text, player)["weapon"] == PISTOL_WEAPON), timeout=14)
        run.audit()
        server_offset, client_offset = len(server.text()), len(client.text())
        phase = "actual RCTRL native fire"
        run.key(FIRE_SCAN, True)
        try:
            server.wait(lambda text: any(row["ammo"] == 12 and row["counter"] > 0 and
                                         row["bits"] & FIRE_BIT
                                         for row in reload_rows(text[server_offset:], player)), timeout=8)
        finally:
            run.key(FIRE_SCAN, False)
        phase = "native clip reload and rest"
        server.wait(lambda text: any(row["ammo"] == 12 and row["counter"] >= 5 and
                                     row["reloading"] == 1
                                     for row in reload_rows(text[server_offset:], player)), timeout=10)
        server.wait(lambda text: rest_rows(text[server_offset:], player), timeout=12)
        client.wait(lambda text: any(row["ammo"] == 12 and row["counter"] >= 5 and
                                     row["reloading"] == 1
                                     for row in reload_rows(text[client_offset:], player)), timeout=12)
        client.wait(lambda text: rest_rows(text[client_offset:], player), timeout=12)
        run.audit()
        server_rows = reload_rows(server.text(), player)
        client_rows = reload_rows(client.text(), player)
        server_after, client_after = server_rows[-1], client_rows[-1]
        fired = any(row["ammo"] == 12 and row["counter"] > 0 and row["bits"] & FIRE_BIT
                    for row in reload_rows(server.text()[server_offset:], player))
        reloaded = any(row["ammo"] == 12 and row["counter"] >= 5 and row["reloading"] == 1
                       for row in reload_rows(server.text()[server_offset:], player))
        checks = {
            "actual_native_client_player_index": player > 0,
            "RCTRL_reaches_authoritative_native_fire": fired,
            "authoritative_native_clip_reload_observed": reloaded,
            "authoritative_rest_has_ammo12_counter0_reload0":
                server_after["ammo"] == 12 and server_after["counter"] == 0 and
                server_after["reloading"] == 0 and server_after["weapon"] == PISTOL_WEAPON,
            "client_counter_and_ammo_correct_to_authority":
                client_after["ammo"] == 12 and client_after["counter"] == 0 and
                client_after["weapon"] == PISTOL_WEAPON,
        }
        if label == "net4_before_reload_flag":
            checks["expected_client_reloading_flag_stuck"] = client_after["reloading"] == 1
            result["expected_regression_observed"] = all(checks.values())
            # The pre-fix binary is evidence, never a passing product result.
            result["passed"] = False
        else:
            checks["client_reloading_flag_clears_after_authoritative_rest"] = client_after["reloading"] == 0
            result["passed"] = all(checks.values())
        result.update(phase="complete", checks=checks, player=player,
                      server_rows=bounded(server_rows), client_rows=bounded(client_rows),
                      server_after=server_after, client_after=client_after)
    except Exception as error:
        result.update(error=str(error), phase=phase)
        for role in ("server", "client"):
            if role in run.labs:
                text = (run.labs[role] / "game.log").read_text(errors="replace") if (run.labs[role] / "game.log").exists() else ""
                result[f"{role}_rows"] = bounded(reload_rows(text, player))
    finally:
        run.close()
        result["cleanup"] = all(process.poll() is not None for process in run.processes.values())
        (pair_root / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def source_evidence():
    network = HERE.parent.parent / "source" / "duke3d" / "src" / "network.cpp"
    header = HERE.parent.parent / "source" / "duke3d" / "src" / "network.h"
    fixture = HERE / "fixtures" / "pistol_reload_test.con"
    header_text = header.read_text(errors="replace")
    return {
        "network_cpp": {"path": str(network), "sha256": sha256(network)},
        "network_h": {"path": str(header), "sha256": sha256(header),
                      "NETVERSION": re.search(r"#define\s+NETVERSION\s+(\d+)", header_text).group(1)},
        "fixture": {"path": str(fixture), "sha256": sha256(fixture)},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "input-helper", "grp", "work-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--reference-binary", type=Path, help="Also require the timing-dependent preserved stale-flag reproduction")
    parser.add_argument("--port", type=int, default=24758)
    parser.add_argument("--_sandboxed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.port < 65535:
        parser.error("--port must be in 1..65534")
    args.binary = args.binary.resolve()
    if args.reference_binary: args.reference_binary = args.reference_binary.resolve()
    args.input_helper = args.input_helper.resolve()
    args.grp = args.grp.resolve()
    inputs = [args.binary, args.input_helper, args.grp]+([args.reference_binary] if args.reference_binary else [])
    if not all(path.is_file() for path in inputs):
        parser.error("--binary, --reference-binary, --input-helper, and --grp must name existing files")
    reexec_sandbox(args)
    assert_gpu_devices_absent()
    assert_cpu_binary(args.binary)
    if args.reference_binary: assert_cpu_binary(args.reference_binary)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="pistol-reload-native-", dir=args.work_dir.resolve()))
    result = {"passed": False, "root": str(root), "renderer": "CPU classic SDL dummy (no XR/GPU)",
              "source": source_evidence(), "input_helper_sha256": sha256(args.input_helper),
              "grp_sha256": sha256(args.grp)}
    try:
        baseline = run_pair(args, "net4_before_reload_flag", args.reference_binary, args.port, root) if args.reference_binary else None
        current = run_pair(args, "net5_with_reload_flag", args.binary, args.port + 1, root)
        # Passing requires both a reproduced pre-fix stale flag and a fixed
        # current client.  An inconclusive baseline is deliberately not hidden.
        result.update(baseline=baseline, current=current,
                      passed=(baseline is None or bool(baseline.get("expected_regression_observed")))
                          and bool(current.get("passed")) and bool(current.get("cleanup")),
                      current_only=baseline is None)
    except Exception as error:
        result["error"] = str(error)
    finally:
        (root / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
