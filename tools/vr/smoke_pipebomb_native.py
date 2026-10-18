#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""CPU-only native dedicated-server pipebomb reference test.

The runner owns a tiny map and two local native processes.  It drives only the
client's private SDL FIFO and records bounded native CON observations, leaving
stock player/actor pipebomb creation, replication, physics, and detonation in
charge.
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

from smoke_actions import Observer
from smoke_actions_multiplayer import client_player_index
from smoke_hand_shots import room
from smoke_multiplayer import CONFIG, stop
from smoke_native_levels import (assert_cpu_binary, assert_gpu_devices_absent,
                                 sanitised_env)


PLAYER_FIELD = re.compile(r"addlog vrpipe_(\w+)(?: \(player \d+\))? = (-?\d+)")
SYNC = "Multiplayer client level synchronization complete."
MODE_GAME = 4
FIRE_BIT = 4
FIRE_DELAY = 6
REMOTE_WEAPON = 10
HANDBOMB_WEAPON = 5
HEAVYHBOMB = 26


def reexec_sandbox(args):
    """Enter the GPU-denied namespace while preserving this runner's argv."""
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


def bounded(rows, limit=12):
    return rows[-limit:]


def rows(text, prefix, end):
    result, row = [], {}
    for key, value in PLAYER_FIELD.findall(text):
        if prefix == "" and (key.startswith("bomb_") or key in ("explosions", "totalclock")):
            continue
        if not key.startswith(prefix):
            continue
        key = key[len(prefix):]
        if (prefix == "" and key == "tick") or (prefix == "bomb_" and key == "index"):
            row = {}
        row[key] = int(value)
        if key == end:
            result.append(row)
    return result


def players(text, player=None):
    result = rows(text, "", "hbomb")
    return [row for row in result if player is None or row.get("player") == player]


def bombs(text):
    return rows(text, "bomb_", "event")


def explosions(text):
    return [int(value) for key, value in PLAYER_FIELD.findall(text) if key == "explosions"]


def latest_player(text, player):
    values = players(text, player)
    return values[-1] if values else None


def native_bomb(values, player, event=None):
    return [row for row in values if row.get("tile") == HEAVYHBOMB and
            row.get("ownerplayer") == player and (event is None or row.get("event") == event)]


def trajectory(values, index):
    """Bound early authoritative/native-client EVENT_GAME trajectory samples."""
    sample = [row for row in values if row.get("index") == index and row.get("event") == 65]
    return sample[:12]


def native_clock_progresses(samples):
    clocks = [sample.get("totalclock") for sample in samples]
    return len(clocks) >= 2 and all(clock is not None for clock in clocks) and all(
        later > earlier for earlier, later in zip(clocks, clocks[1:]))


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_lab(root, role, grp):
    lab = root / role
    lab.mkdir()
    (lab / "DUKE3D.GRP").symlink_to(grp)
    (lab / "eduke32.cfg").write_text(CONFIG.replace("ScreenBPP = 32", "ScreenBPP = 8"))
    with (lab / "eduke32.cfg").open("a") as config:
        config.write(f'\n[Comm Setup]\nPlayerName = "Pipe{role.title()}"\n')
    (lab / "autoexec.cfg").write_text("r_maxfps 30\n")
    for fixture in ("controller_test.con", "pipebomb_test.con"):
        shutil.copyfile(HERE / "fixtures" / fixture, lab / fixture)
    (lab / "pipebomb.map").write_bytes(room())
    return lab


class Run:
    def __init__(self, args, root):
        self.args, self.root = args, root
        self.env = sanitised_env()
        self.processes, self.observers, self.labs, self.writers, self.logs = {}, {}, {}, {}, []

    def audit(self):
        assert_gpu_devices_absent()
        for role, process in self.processes.items():
            if process.poll() is not None:
                raise RuntimeError(f"{role} exited during CPU-only pipebomb test")
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
        process = subprocess.Popen([str(self.args.binary), "-usecwd", "-nosetup", "-noautoload",
                                    "-nologo", "-ns", "-nm", *command, "-x", "pipebomb_test.con"],
                                   cwd=lab, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT)
        self.processes[role] = process
        self.observers[role] = Observer(process, lab / "game.log")
        self.audit()
        return self.observers[role]

    def key(self, role, scan, down):
        if role not in self.writers:
            raise RuntimeError(f"{role} does not own a private SDL FIFO")
        os.write(self.writers[role], f"key {scan} {int(down)}\n".encode())

    def press(self, role, scan, seconds=.12):
        self.key(role, scan, True)
        time.sleep(seconds)
        self.key(role, scan, False)

    def capture(self, role):
        lab = self.labs[role]
        directory = lab / "screenshots"
        before = set(directory.glob("duke*")) if directory.exists() else set()
        offset = len(self.observers[role].text())
        self.press(role, 69)  # SDL_SCANCODE_F12
        self.observers[role].wait(lambda text: directory.exists() and bool(set(directory.glob("duke*")) - before) and
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


def join(run):
    client = run.launch("client", ["-connect", f"127.0.0.1:{run.args.port}"])
    client.wait(lambda text: SYNC in text, timeout=25)
    client.pause(1.6)
    client.wait(lambda text: client_player_index(text) is not None, timeout=12)
    player = client_player_index(client.text())
    if player is None or player <= 0:
        raise RuntimeError("client did not expose a real native player index")
    return player


def close_enough(server, client):
    keys = ("owner", "ownerplayer", "yvel", "sector", "angle", "mode", "fuse")
    return (all(server.get(key) == client.get(key) for key in keys) and
            all(abs(server.get(key, 0) - client.get(key, 0)) <= 128 for key in ("x", "y", "z")) and
            abs(server.get("xvel", 0) - client.get("xvel", 0)) <= 5 and
            abs(server.get("zvel", 0) - client.get("zvel", 0)) <= 64)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "input-helper", "grp", "work-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--port", type=int, default=24735)
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
    root = Path(tempfile.mkdtemp(prefix="pipebomb-native-", dir=args.work_dir.resolve()))
    run = Run(args, root)
    phase = "setup"
    result = {"passed": False, "renderer": "CPU classic (no VR/SPS proof)",
              "binary_sha256": sha256(args.binary), "checks": {}}
    try:
        for role in ("server", "client"):
            run.labs[role] = write_lab(root, role, args.grp)
        phase = "native dedicated server"
        server = run.launch("server", ["-dedicated", "-c1", "-m", "-port", str(args.port), "-map", "pipebomb.map"])
        server.wait(lambda text: "Multiplayer server initialized." in text, timeout=18)
        phase = "native client join"
        player = join(run)
        server.wait(lambda text: (latest_player(text, player) is not None and
                                  latest_player(text, player).get("weapon") == HANDBOMB_WEAPON and
                                  latest_player(text, player).get("ammo") == 6 and
                                  latest_player(text, player).get("gm", 0) & MODE_GAME), timeout=12)
        run.observers["client"].wait(lambda text: latest_player(text, player) is not None and
                                     latest_player(text, player).get("weapon") == HANDBOMB_WEAPON, timeout=12)
        run.audit()
        baseline = latest_player(server.text(), player)
        ammo_before = baseline["ammo"]

        phase = "native handbomb hold at fire delay"
        hold_offset = len(server.text())
        run.key("client", 228, True)  # SDL_SCANCODE_RCTRL
        server.wait(lambda text: any(row.get("bits", 0) & FIRE_BIT and row.get("frame") == FIRE_DELAY
                                     for row in players(text[hold_offset:], player)), timeout=6)
        server.pause(.35)
        held = players(server.text()[hold_offset:], player)
        held_bombs = native_bomb(bombs(server.text()[hold_offset:]), player)
        held_after = latest_player(server.text(), player)

        phase = "native release creates remote pipebomb"
        release_offset = len(server.text())
        client_release_offset = len(run.observers["client"].text())
        run.key("client", 228, False)
        server.wait(lambda text: (latest_player(text, player) is not None and
                                  latest_player(text, player).get("ammo") == ammo_before - 1 and
                                  latest_player(text, player).get("hbomb") == 1 and
                                  latest_player(text, player).get("weapon") == REMOTE_WEAPON and
                                  bool(native_bomb(bombs(text[release_offset:]), player, 71))), timeout=8)
        server.wait(lambda text: any(row.get("xvel") == 0 and row.get("mode") == 2
                                     for row in native_bomb(bombs(text[release_offset:]), player)), timeout=8)
        server_bombs = native_bomb(bombs(server.text()[release_offset:]), player)
        spawned = {row["index"] for row in server_bombs if row.get("event") == 71}
        authoritative = next(row for row in reversed(server_bombs)
                             if row.get("index") in spawned and row.get("xvel") == 0 and row.get("mode") == 2)

        phase = "native client pipebomb replication"
        client = run.observers["client"]
        client.wait(lambda text: bool(native_bomb(bombs(text[client_release_offset:]), player, 65)), timeout=10)
        client.wait(lambda text: any(row.get("xvel") == 0 and row.get("mode") == 2
                                     for row in native_bomb(bombs(text[client_release_offset:]), player, 65)), timeout=10)
        replicated = next(row for row in reversed(native_bomb(bombs(client.text()[client_release_offset:]), player, 65))
                          if row.get("xvel") == 0 and row.get("mode") == 2)

        phase = "native handremote detonation"
        explosion_before = explosions(server.text())[-1] if explosions(server.text()) else 0
        detonate_offset = len(server.text())
        run.press("client", 228, .28)
        server.wait(lambda text: latest_player(text, player) is not None and
                    latest_player(text, player).get("hbomb") == 0, timeout=6)
        server.wait(lambda text: (explosions(text) and explosions(text)[-1] == explosion_before + 1), timeout=8)
        client.wait(lambda text: latest_player(text, player) is not None and
                    latest_player(text, player).get("hbomb") == 0 and
                    latest_player(text, player).get("ammo") == ammo_before - 1, timeout=8)
        server_after = latest_player(server.text(), player)
        client_after = latest_player(client.text(), player)
        phase = "native F12 capture after close receipt"
        screenshot = run.capture("client")
        run.audit()

        checks = {
            "actual_native_player_index": player > 0,
            "held_RCTRL_reaches_native_fire_delay": any(row.get("bits", 0) & FIRE_BIT and row.get("frame") == FIRE_DELAY for row in held),
            "no_throw_or_ammo_loss_while_held": not held_bombs and held_after["ammo"] == ammo_before,
            "release_creates_exactly_one_native_HEAVYHBOMB": len(spawned) == 1,
            "release_consumes_exactly_one_handbomb": server_after["ammo"] == ammo_before - 1,
            "native_pipebomb_owner_mode_and_fuse": (authoritative.get("ownerplayer") == player and
                                                      authoritative.get("mode") == 2 and authoritative.get("fuse") == 0),
            "actual_live_client_pipebomb_replication": (replicated.get("tile") == HEAVYHBOMB and
                                                         replicated.get("ownerplayer") == player and replicated.get("mode") == 2),
            "server_client_pipebomb_convergence": close_enough(authoritative, replicated),
            "native_totalclock_progresses_on_server_trajectory": native_clock_progresses(
                trajectory(server_bombs, authoritative["index"])),
            "native_totalclock_progresses_on_client_trajectory": native_clock_progresses(
                trajectory(native_bomb(bombs(client.text()[client_release_offset:]), player), replicated["index"])),
            "actual_handremote_press_clears_hbomb_on": server_after.get("hbomb") == client_after.get("hbomb") == 0,
            "actual_native_pipebomb_explosion": explosions(server.text())[-1] == explosion_before + 1,
            "client_state_converges_after_detonation": (server_after.get("ammo") == client_after.get("ammo") == ammo_before - 1 and
                                                         server_after.get("weapon") == client_after.get("weapon")),
            "native_F12_capture_after_close_receipt": bool(screenshot),
        }
        result.update(passed=all(checks.values()), checks=checks, player=player,
                      fire_delay=FIRE_DELAY, ammo_before=ammo_before,
                      authoritative_bomb=authoritative, replicated_bomb=replicated,
                      server_bomb_trajectory=trajectory(server_bombs, authoritative["index"]),
                      client_bomb_trajectory=trajectory(native_bomb(bombs(client.text()[client_release_offset:]), player),
                                                        replicated["index"]),
                      server_player_after=server_after, client_player_after=client_after,
                      explosion_count=explosions(server.text())[-1], screenshot=screenshot)
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
