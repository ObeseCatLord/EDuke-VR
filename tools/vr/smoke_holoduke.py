#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""CPU-only native multiplayer Holoduke player-ownership regression proof.

The fixture grants a joining player a Holoduke once, then observes stock
activation, replication, movement, firing, and recovery.  The runner owns the
server/client processes and their private dummy-SDL FIFO; it never injects
actors, packets, or gameplay state.
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
import time

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from smoke_actions import Observer, samples as input_samples
from smoke_actions_multiplayer import client_player_index
from smoke_hand_shots import room
from smoke_multiplayer import CONFIG, stop
from smoke_native_levels import assert_cpu_binary, assert_gpu_devices_absent, sanitised_env


SYNC = "Multiplayer client level synchronization complete."
PLAYER_FIELD = re.compile(r"addlog vrholo_(\w+)(?: \(player \d+\))? = (-?\d+)")
APLAYER = 1405
STAT_PLAYER = 10


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def bounded(rows, limit=12):
    return rows[-limit:]


def rows(text, prefix, end):
    result, row = [], {}
    for key, value in PLAYER_FIELD.findall(text):
        if not key.startswith(prefix):
            continue
        key = key[len(prefix):]
        if (prefix == "" and key == "player") or (prefix == "actor_" and key == "index"):
            row = {}
        row[key] = int(value)
        if key == end:
            result.append(row)
    return result


def player_rows(text, player=None):
    result = rows(text, "", "gm")
    return [row for row in result if player is None or row.get("player") == player]


def holo_rows(text, player=None):
    result = rows(text, "actor_", "event")
    return [row for row in result if player is None or row.get("yvel") == player]


def latest_player(text, player):
    values = player_rows(text, player)
    return values[-1] if values else None


def real_player(row, player, holo_index=None):
    return (row is not None and row.get("player") == player and
            0 <= row.get("index", -1) < 16384 and row.get("owner", -1) >= 0 and
            row.get("yvel") == player and row.get("tile") == APLAYER and
            row.get("stat") == STAT_PLAYER and row.get("sector", -1) >= 0 and
            -65536 <= row.get("z", -65537) <= 65536 and
            (holo_index is None or row.get("index") != holo_index))


def native_holoduke(row, player):
    return (row.get("owner") == -1 and row.get("yvel") == player and
            row.get("tile") == APLAYER and row.get("stat") == STAT_PLAYER and
            0 <= row.get("index", -1) < 16384 and row.get("sector", -1) >= 0 and
            -65536 <= row.get("z", -65537) <= 65536)


def write_lab(root, role, grp):
    lab = root / role
    lab.mkdir()
    (lab / "DUKE3D.GRP").symlink_to(grp)
    (lab / "eduke32.cfg").write_text(CONFIG.replace("ScreenBPP = 32", "ScreenBPP = 8"))
    with (lab / "eduke32.cfg").open("a") as config:
        config.write(f'\n[Comm Setup]\nPlayerName = "Holo{role.title()}"\n')
    # F6 is an actual game-function binding, supplied through the normal OSD
    # config path rather than an input-bit or packet shortcut.
    (lab / "autoexec.cfg").write_text('r_maxfps 30\nunbind F6\nbind F6 "gamefunc_Holo_Duke"\n')
    for fixture in ("controller_test.con", "holoduke_test.con"):
        shutil.copyfile(HERE / "fixtures" / fixture, lab / fixture)
    (lab / "holoduke.map").write_bytes(room())
    return lab


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
               "--unshare-pid", "--bind", str(work), str(work), "--chdir", str(Path.cwd()),
               "--clearenv"]
    for key in ("PATH", "LANG", "LC_ALL", "TZ"):
        if key in safe:
            command += ["--setenv", key, safe[key]]
    command += [sys.executable, str(Path(__file__).resolve()), *child_args]
    os.execvpe(bwrap, command, safe)


class Run:
    def __init__(self, args, root):
        self.args, self.root, self.env = args, root, sanitised_env()
        self.processes, self.observers, self.labs, self.writers, self.logs = {}, {}, {}, {}, []
        self.receipt = 0

    def audit(self):
        assert_gpu_devices_absent()
        for role, process in self.processes.items():
            if process.poll() is not None:
                raise RuntimeError(f"{role} exited during CPU-only Holoduke test")
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
        lab, env = self.labs[role], dict(self.env)
        stdin = subprocess.PIPE if role == "server" else subprocess.DEVNULL
        if role == "client":
            fifo = lab / "input.fifo"
            os.mkfifo(fifo, 0o600)
            if fifo.stat().st_mode & 0o077:
                raise RuntimeError("client input FIFO is not owner-only")
            self.writers[role] = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
            env.update(LD_PRELOAD=str(self.args.input_helper), EDUKE32_TEST_SDL_INPUT=str(fifo))
        log = (lab / "game.log").open("w")
        self.logs.append(log)
        process = subprocess.Popen([str(self.args.binary), "-usecwd", "-nosetup", "-noautoload",
                                    "-nologo", "-ns", "-nm", *command, "-x", "holoduke_test.con"],
                                   cwd=lab, env=env, stdin=stdin, stdout=log, stderr=subprocess.STDOUT)
        self.processes[role] = process
        self.observers[role] = Observer(process, lab / "game.log")
        self.audit()
        return self.observers[role]

    def key(self, scan, down):
        os.write(self.writers["client"], f"key {scan} {int(down)}\n".encode())

    def press(self, scan, seconds=.12):
        self.key(scan, True)
        time.sleep(seconds)
        self.key(scan, False)

    def server_receipt(self):
        self.receipt += 1
        receipt = f"holoduke-proof-receipt-{self.receipt}"
        server, process = self.observers["server"], self.processes["server"]
        offset = len(server.text())
        if process.stdin is None:
            raise RuntimeError("dedicated server stdin pipe unavailable")
        process.stdin.write((f"echo {receipt}\n").encode())
        process.stdin.flush()
        server.wait(lambda text: receipt in text[offset:], timeout=8)
        return receipt

    def capture(self):
        lab, observer = self.labs["client"], self.observers["client"]
        directory = lab / "screenshots"
        before = set(directory.glob("duke*")) if directory.exists() else set()
        offset = len(observer.text())
        self.press(69)  # SDL_SCANCODE_F12
        observer.wait(lambda text: directory.exists() and bool(set(directory.glob("duke*")) - before) and
                      "Saved screenshot to" in text[offset:], timeout=6)
        created = next(iter(set(directory.glob("duke*")) - before))
        if created.stat().st_size == 0:
            raise RuntimeError("native F12 produced an empty screenshot")
        return created.name

    def close(self):
        for process in reversed(list(self.processes.values())):
            stop(process)
        for fd in self.writers.values():
            os.close(fd)
        for log in self.logs:
            log.close()


def later_player_rows(observer, player, offset):
    observer.wait(lambda text: len(player_rows(text[offset:], player)) >= 4, timeout=8)
    return bounded(player_rows(observer.text()[offset:], player))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "input-helper", "grp", "work-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--port", type=int, default=24749)
    parser.add_argument("--_sandboxed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be in 1..65535")
    args.binary, args.input_helper, args.grp = (args.binary.resolve(), args.input_helper.resolve(), args.grp.resolve())
    if not args.binary.is_file() or not args.input_helper.is_file() or not args.grp.is_file():
        parser.error("--binary, --input-helper, and --grp must name existing files")
    reexec_sandbox(args)
    assert_gpu_devices_absent()
    assert_cpu_binary(args.binary)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="holoduke-proof-", dir=args.work_dir.resolve()))
    run, phase = Run(args, root), "setup"
    result = {"passed": False, "renderer": "CPU classic (no VR/SPS proof)",
              "binary_sha256": sha256(args.binary), "evidence_root": str(root), "checks": {}}
    try:
        for role in ("server", "client"):
            run.labs[role] = write_lab(root, role, args.grp)
        phase = "native dedicated server"
        server = run.launch("server", ["-dedicated", "-c1", "-m", "-port", str(args.port), "-map", "holoduke.map"])
        server.wait(lambda text: "Multiplayer server initialized." in text, timeout=18)
        phase = "native client join"
        client = run.launch("client", ["-connect", f"127.0.0.1:{args.port}"])
        client.wait(lambda text: SYNC in text, timeout=25)
        client.pause(1.6)
        client.wait(lambda text: client_player_index(text) is not None, timeout=12)
        player = client_player_index(client.text())
        if player is None or player <= 0:
            raise RuntimeError("client did not expose a distinct native player index")
        server.wait(lambda text: real_player(latest_player(text, player), player), timeout=12)
        client.wait(lambda text: real_player(latest_player(text, player), player), timeout=12)
        baseline_server, baseline_client = latest_player(server.text(), player), latest_player(client.text(), player)
        result.update(player=player, baseline={"server": baseline_server, "client": baseline_client})
        if baseline_server.get("amount") != 2400:
            raise RuntimeError("fixture did not grant the joining player one native Holoduke inventory")
        run.audit()

        phase = "native F6 Holoduke activation"
        server_offset, client_offset = len(server.text()), len(client.text())
        run.press(63)  # SDL_SCANCODE_F6, bound in autoexec to gamefunc_Holo_Duke.
        server.wait(lambda text: any(native_holoduke(row, player) for row in holo_rows(text[server_offset:], player)), timeout=8)
        client.wait(lambda text: any(native_holoduke(row, player) for row in holo_rows(text[client_offset:], player)), timeout=10)
        server_holo = next(row for row in reversed(holo_rows(server.text()[server_offset:], player)) if native_holoduke(row, player))
        client_holo = next(row for row in reversed(holo_rows(client.text()[client_offset:], player)) if native_holoduke(row, player))
        result["holoduke"] = {"server": server_holo, "client": client_holo}
        if server_holo["index"] != client_holo["index"]:
            raise RuntimeError("native client Holoduke index did not match server snapshot")
        holo_index = server_holo["index"]

        phase = "later authoritative snapshots with Holoduke active"
        active_server = later_player_rows(server, player, server_offset)
        active_client = later_player_rows(client, player, client_offset)
        result["active_snapshots"] = {"server": active_server, "client": active_client}
        if not all(real_player(row, player, holo_index) for row in active_server[-4:]):
            raise RuntimeError("server real player binding was lost after native Holoduke snapshot")
        if not all(real_player(row, player, holo_index) for row in active_client[-4:]):
            raise RuntimeError("client real player binding was lost after native Holoduke snapshot")

        phase = "native movement and fire after Holoduke"
        before = latest_player(server.text(), player)
        move_offset = len(server.text())
        run.press(26, .55)  # SDL_SCANCODE_W
        server.wait(lambda text: any((row.get("x"), row.get("y")) != (before["x"], before["y"])
                                     for row in player_rows(text[move_offset:], player)), timeout=6)
        moved = latest_player(server.text(), player)
        ammo_before = [row for row in input_samples(server.text()) if row.get("player") == player][-1]["ammo"]
        fire_offset = len(server.text())
        run.press(228, .16)  # SDL_SCANCODE_RCTRL / native Fire binding
        server.wait(lambda text: any(row.get("player") == player and row.get("ammo", ammo_before) < ammo_before
                                     for row in input_samples(text[fire_offset:])), timeout=7)
        fired = [row for row in input_samples(server.text()) if row.get("player") == player][-1]
        result["after_active_controls"] = {"before": before, "moved": moved, "ammo_before": ammo_before, "fired": fired}

        phase = "native F6 Holoduke recovery"
        recovery_offset = len(server.text())
        run.press(63)
        server.wait(lambda text: latest_player(text, player) is not None and
                    latest_player(text, player).get("holoon") == -1, timeout=8)
        client.wait(lambda text: latest_player(text, player) is not None and
                    latest_player(text, player).get("holoon") == -1, timeout=10)
        recovery_server = later_player_rows(server, player, recovery_offset)
        recovery_client = later_player_rows(client, player, recovery_offset)
        result["recovery_snapshots"] = {"server": recovery_server, "client": recovery_client}
        if not all(real_player(row, player, holo_index) for row in recovery_server[-4:]):
            raise RuntimeError("server real player binding was lost after native Holoduke recovery")
        if not all(real_player(row, player, holo_index) for row in recovery_client[-4:]):
            raise RuntimeError("client real player binding was lost after native Holoduke recovery")

        phase = "saved receipt then native F12"
        receipt = run.server_receipt()
        screenshot = run.capture()
        run.audit()
        checks = {
            "distinct_connected_native_client_player": player > 0,
            "one_time_native_holoduke_inventory_grant": baseline_server.get("amount") == 2400,
            "actual_native_holoduke_server_actor": native_holoduke(server_holo, player),
            "actual_native_holoduke_client_actor": native_holoduke(client_holo, player),
            "server_client_holoduke_snapshot_index_matches": server_holo["index"] == client_holo["index"],
            "server_real_player_survives_later_snapshots": all(real_player(row, player, holo_index) for row in active_server[-4:]),
            "client_real_player_survives_later_snapshots": all(real_player(row, player, holo_index) for row in active_client[-4:]),
            "native_movement_after_holoduke": (moved["x"], moved["y"]) != (before["x"], before["y"]),
            "native_fire_after_holoduke": fired["ammo"] < ammo_before,
            "server_real_player_recovers_after_holoduke_off": all(real_player(row, player, holo_index) for row in recovery_server[-4:]),
            "client_real_player_recovers_after_holoduke_off": all(real_player(row, player, holo_index) for row in recovery_client[-4:]),
            "saved_server_receipt_before_native_F12": bool(receipt),
            "native_F12_capture_after_receipt": bool(screenshot),
        }
        result.update(passed=all(checks.values()), checks=checks, receipt=receipt, screenshot=screenshot)
    except Exception as error:
        result.update(error=str(error), phase=phase)
    finally:
        run.close()
        (root / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
