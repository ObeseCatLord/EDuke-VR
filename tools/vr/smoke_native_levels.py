#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""CPU-only native multiplayer level-transition smoke test.

This is deliberately a classic-renderer test.  It proves native dedicated
server map changes and SDL dummy input, not VR or single-pass rendering.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import traceback

from PIL import Image, ImageChops

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from smoke_actions import Observer
from smoke_actions_multiplayer import client_player_index
from smoke_hand_shots import room
from smoke_multiplayer import CONFIG, stop


LEVEL_FIELD = re.compile(r"addlog vrlevel_(active|staged|knuckle|weaponpos|player|actor|index|yvel|indexyvel|tile|stat|sectorid|spritesector|sectors|ceiling|floorz|z|sequence|floor|gm|volume|number)\b[^=\n]*= (-?\d+)")
INPUT_FIELD = re.compile(r"addlog vrinput_(tick|player|bits|fvel|svel|x|y|z|weapon|ammo)\b[^=\n]*= (-?\d+)")
SYNC = "Multiplayer client level synchronization complete."
GPU_MAP_NAMES = ("libnvidia", "libGLX", "libEGL", "libvulkan")
MENU_MODE = 1
MODE_GAME = 4


def bounded(value, limit=12):
    return value[-limit:]


def parse_rows(text, pattern, end):
    rows, row = [], {}
    for key, value in pattern.findall(text):
        if key in ("active", "tick"):
            row = {}
        row[key] = int(value)
        if key == end:
            rows.append(row)
    return rows


def levels(text):
    return parse_rows(text, LEVEL_FIELD, "number")


def inputs(text):
    return parse_rows(text, INPUT_FIELD, "ammo")


def level_for(text, player=None):
    rows = levels(text)
    if player is not None:
        rows = [row for row in rows if row.get("player") == player]
    return rows[-1] if rows else None


def input_for(text, player):
    rows = [row for row in inputs(text) if row.get("player") == player]
    return rows[-1] if rows else None


def assert_cpu_binary(binary):
    output = subprocess.run(["readelf", "-Ws", str(binary)], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            check=True).stdout
    dynamic = subprocess.run(["readelf", "-d", str(binary)], text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             check=True).stdout
    # Native teardown references SDL_GL_DeleteContext even in USE_OPENGL=0.
    # Reject creation/rendering references; that null-context cleanup is inert.
    if re.search(r"SDL_GL_(?!DeleteContext\b)\w+|xrCreateInstance", output + dynamic):
        raise RuntimeError("binary has GL creation/rendering or OpenXR instance references")


def assert_gpu_devices_absent():
    if any(Path("/dev").glob("nvidia*")) or Path("/dev/dri").exists():
        raise RuntimeError("GPU device visible in CPU-only test namespace")


def e1l1_floorpic(grp):
    """Read only the owned GRP directory and E1L1's sector-floor field."""
    size = grp.stat().st_size
    with grp.open("rb") as source:
        if source.read(12) != b"KenSilverman":
            raise RuntimeError("owned GRP has an invalid signature")
        count_bytes = source.read(4)
        if len(count_bytes) != 4:
            raise RuntimeError("owned GRP has no directory count")
        count = struct.unpack("<I", count_bytes)[0]
        if count > (size - 16) // 16:
            raise RuntimeError("owned GRP directory exceeds file bounds")
        entries = []
        for _ in range(count):
            entry = source.read(16)
            if len(entry) != 16:
                raise RuntimeError("truncated owned GRP directory")
            raw_name, entry_size = struct.unpack("<12sI", entry)
            entries.append((raw_name.split(b"\0", 1)[0].decode("ascii", "strict"), entry_size))
        offset = 16 + count * 16
        for name, entry_size in entries:
            if offset + entry_size > size:
                raise RuntimeError("owned GRP entry exceeds file bounds")
            if name.upper() == "E1L1.MAP":
                if entry_size < 22 + 24 + 2:
                    raise RuntimeError("owned E1L1 map is too short for its first sector floor")
                source.seek(offset + 22 + 24)
                value = source.read(2)
                if len(value) != 2:
                    raise RuntimeError("owned E1L1 floor field is truncated")
                return struct.unpack("<h", value)[0]
            offset += entry_size
    raise RuntimeError("owned GRP does not contain E1L1.MAP")


def sanitised_env():
    env = {}
    for key, value in os.environ.items():
        if key in {"DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "LD_PRELOAD"}:
            continue
        if key.startswith(("XR_", "EDUKE32_XR")):
            continue
        env[key] = value
    env.update(SDL_VIDEODRIVER="dummy", SDL_RENDER_DRIVER="software",
               SDL_AUDIODRIVER="dummy", EDUKE32_TEST_PRIVATE_WINDOW="1")
    return env


def reexec_sandbox(args):
    """Enter a GPU-denied namespace before opening any owned game process."""
    if args._sandboxed:
        return
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise RuntimeError("bubblewrap is required for the CPU-only runner")
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).resolve()
    child_args = [arg for arg in sys.argv[1:] if arg != "--_sandboxed"] + ["--_sandboxed"]
    safe = sanitised_env()
    command = [bwrap, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
               "--unshare-pid", "--bind", str(work), str(work), "--chdir", str(Path.cwd()),
               "--clearenv"]
    for key in ("PATH", "LANG", "LC_ALL", "TZ"):
        if key in safe:
            command += ["--setenv", key, safe[key]]
    command += [sys.executable, str(script), *child_args]
    os.execvpe(bwrap, command, safe)


def write_lab(root, role, grp):
    lab = root / role
    lab.mkdir()
    (lab / "DUKE3D.GRP").symlink_to(grp)
    (lab / "eduke32.cfg").write_text(CONFIG.replace("ScreenBPP = 32", "ScreenBPP = 8"))
    names = {"server": "Server", "peer1": "PeerOne", "peer2": "PeerTwo",
             "replacement": "Replace", "newcomer": "Newcomer"}
    with (lab / "eduke32.cfg").open("a") as config:
        config.write(f'\n[Comm Setup]\nPlayerName = "{names[role]}"\n')
    # Exercise the real OSD handlers through native binds. Dummy SDL has no
    # platform text-input service; it still supplies ordinary key events.
    (lab / "autoexec.cfg").write_text('r_maxfps 30\nbind F6 "map second.map"\n'
                                    'bind F7 "changelevel 1 2"\nbind F8 "quit"\n')
    for fixture in ("controller_test.con", "level_test.con"):
        shutil.copyfile(HERE / "fixtures" / fixture, lab / fixture)
    first = room()
    second = bytearray(first)
    struct.pack_into("<h", second, 22 + 24, 183)
    reserved = bytearray(first)
    struct.pack_into("<h", reserved, 22 + 24, 311)
    (lab / "first.map").write_bytes(first)
    (lab / "second.map").write_bytes(second)
    (lab / "reserved.map").write_bytes(reserved)
    (lab / "malformed.map").write_bytes(struct.pack("<I", 1234))
    return lab


class Run:
    def __init__(self, args, root):
        self.args, self.root = args, root
        self.env = sanitised_env()
        self.processes, self.logs, self.writers, self.observers, self.labs = {}, [], {}, {}, {}
        self.receipt = 0
        self.ownership = []

    def audit(self):
        assert_gpu_devices_absent()
        for role, process in self.processes.items():
            if process.poll() is not None:
                raise RuntimeError(f"{role} exited during CPU-only test")
            maps = Path(f"/proc/{process.pid}/maps").read_text(errors="replace").lower()
            fds = []
            for fd in Path(f"/proc/{process.pid}/fd").iterdir():
                try:
                    fds.append(os.readlink(fd).lower())
                except FileNotFoundError:
                    pass
            if any(name.lower() in maps for name in GPU_MAP_NAMES) or any(
                    "/dev/nvidia" in item or "/dev/dri" in item for item in fds):
                raise RuntimeError(f"{role} mapped a GPU library or device")

    def launch(self, role, command):
        lab = self.labs[role]
        env = dict(self.env)
        if role != "server":
            fifo = lab / "input.fifo"
            os.mkfifo(fifo, 0o600)
            if fifo.stat().st_mode & 0o077:
                raise RuntimeError("client input FIFO is not owner-only")
            self.writers[role] = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
            env.update(LD_PRELOAD=str(self.args.input_helper), EDUKE32_TEST_SDL_INPUT=str(fifo))
        log = (lab / "game.log").open("w")
        self.logs.append(log)
        process = subprocess.Popen([str(self.args.binary), "-usecwd", "-nosetup", "-noautoload",
                                    "-nologo", "-ns", "-nm", *command, "-x", "level_test.con"],
                                   cwd=lab, env=env,
                                   stdin=subprocess.PIPE if role == "server" else subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT)
        self.processes[role] = process
        self.observers[role] = Observer(process, lab / "game.log")
        self.audit()
        return self.observers[role]

    def press(self, role, scan, hold=.10):
        if role not in self.writers:
            raise RuntimeError(f"{role} does not own a dummy SDL input FIFO")
        fd = self.writers[role]
        os.write(fd, f"key {scan} 1\n".encode())
        time.sleep(hold)
        os.write(fd, f"key {scan} 0\n".encode())

    def client_command(self, role, command):
        scan = {"map second.map": 63, "changelevel 1 2": 64, "quit": 65}[command]
        self.press(role, scan)

    def server_command(self, command):
        self.receipt += 1
        receipt = f"native-level-receipt-{self.receipt}"
        observer = self.observers["server"]
        offset = len(observer.text())
        process = self.processes["server"]
        if process.stdin is None:
            raise RuntimeError("dedicated server stdin pipe unavailable")
        process.stdin.write((f"{command}\necho {receipt}\n").encode())
        process.stdin.flush()
        observer.wait(lambda text: receipt in text[offset:], timeout=15)
        return offset, receipt

    def graceful_disconnect(self, role, name):
        process = self.processes[role]
        server = self.observers["server"]
        offset = len(server.text())
        self.client_command(role, "quit")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and process.poll() is None:
            time.sleep(.05)
        if process.poll() is None:
            raise RuntimeError(f"{role} did not exit after native OSD quit")
        server.wait(lambda text: f"{name} disconnected." in text[offset:], timeout=10)
        del self.processes[role]

    def capture(self, role, label):
        lab = self.labs[role]
        before = set((lab / "screenshots").glob("duke*")) if (lab / "screenshots").exists() else set()
        offset = len(self.observers[role].text())
        self.press(role, 69)
        self.observers[role].wait(lambda text: (lab / "screenshots").exists() and
                                  bool(set((lab / "screenshots").glob("duke*")) - before), timeout=5)
        path = next(iter(set((lab / "screenshots").glob("duke*")) - before))
        self.observers[role].wait(lambda text: f"Saved screenshot to {path.relative_to(lab)}" in text[offset:], timeout=5)
        image = Image.open(path).convert("RGB")
        image.load()
        saved = self.root / f"{label}.png"
        image.save(saved)
        extrema = image.getextrema()
        return saved, any(low != high for low, high in extrema)

    def close(self):
        for process in reversed(list(self.processes.values())):
            stop(process)
        for log in self.logs:
            log.close()
        for fd in self.writers.values():
            os.close(fd)


def wait_level(observer, marker, volume, number, player=None, timeout=14):
    def expected(text):
        row = level_for(text, player)
        return (row is not None and row.get("floor") == marker and row.get("volume") == volume and
                row.get("number") == number and row.get("active") == 1 and row.get("staged") == 0 and
                row.get("gm", 0) & MODE_GAME and bound_player(row))
    observer.wait(expected, timeout=timeout)
    return level_for(observer.text(), player)


def join(run, role, expected_index):
    observer = run.launch(role, ["-connect", f"127.0.0.1:{run.args.port}"])
    observer.wait(lambda text: SYNC in text, timeout=25)
    observer.pause(1.5)
    observer.wait(lambda text: "addlog vrlevel_mode" in text, timeout=10)
    mode_values = re.findall(r"addlog vrlevel_mode\b[^=\n]*= (-?\d+)", observer.text())
    if not mode_values:
        raise RuntimeError(f"{role} did not expose vrlevel_mode")
    dismissed = bool(int(mode_values[-1]) & MENU_MODE)
    if dismissed:
        run.press(role, 41)  # SDL_SCANCODE_ESCAPE
    observer.wait(lambda text: client_player_index(text) is not None, timeout=12)
    actual = client_player_index(observer.text())
    if actual != expected_index:
        raise RuntimeError(f"{role} native myconnectindex {actual}, expected {expected_index}")
    run.observers["server"].wait(lambda text: input_for(text, actual) is not None, timeout=12)
    return {"index": actual, "menu_dismissed": dismissed}


def state(run, players):
    ids = sorted(set(players.values()))
    def owned(text):
        rows = [level_for(text, player) for player in ids]
        return all(bound_player(row) for row in rows) and len({row["index"] for row in rows}) == len(ids)
    snapshots = {}
    for role in players:
        observer = run.observers[role]
        observer.wait(owned, timeout=10)
        sequences = {player: level_for(observer.text(), player)["sequence"] for player in ids}
        # Observe multiple later native input/snapshot cycles, rather than just
        # the collection result before the first authoritative snapshot.
        observer.wait(lambda text: all(level_for(text, player)["sequence"] >= sequence + 12
                                       for player, sequence in sequences.items()), timeout=5)
        if not owned(observer.text()):
            raise RuntimeError(f"{role} player sprite ownership/world bounds changed after synchronization")
        snapshots[role] = [level_for(observer.text(), player) for player in ids]
    run.ownership.append(snapshots)
    return {role: level_for(run.observers[role].text(), player) for role, player in players.items()}


def all_state(rows, marker, volume, number):
    return all(row is not None and row.get("floor") == marker and row.get("volume") == volume and
               row.get("number") == number and row.get("active") == 1 and row.get("staged") == 0
               and row.get("gm", 0) & MODE_GAME
               for row in rows.values())


def bound_player(row):
    return (row is not None and row.get("actor") == row.get("index") and
            0 <= row.get("index", -1) < 16384 and
            row.get("yvel") == row.get("player") == row.get("indexyvel") and
            row.get("tile") == 1405 and row.get("stat") == 10 and
            0 <= row.get("sectorid", -1) < row.get("sectors", 0) and
            0 <= row.get("spritesector", -1) < row.get("sectors", 0) and
            row.get("ceiling", 0) <= row.get("z", 1) <= row.get("floorz", 0))


def in_fixture(row):
    return row is not None and 0 <= row["x"] <= 8192 and 0 <= row["y"] <= 8192 and -32768 <= row["z"] <= 0


def control_and_converge(run, actor_role, actor_player, observer_roles, phase):
    server = run.observers["server"]
    # Native spawn has a real knuckle/weapon-raise animation. Observe its end
    # rather than injecting readiness or treating an early ignored shot as loss.
    server.wait(lambda text: level_for(text, actor_player) is not None and
                level_for(text, actor_player).get("knuckle") == 0 and
                level_for(text, actor_player).get("weaponpos") == 0 and
                bound_player(level_for(text, actor_player)), timeout=8)
    start = input_for(server.text(), actor_player)
    if start is None:
        raise RuntimeError("missing server native input sample for peer1")
    offset = len(server.text())
    run.press(actor_role, 26, .55)  # SDL_SCANCODE_W
    server.wait(lambda text: any((row.get("x"), row.get("y")) != (start["x"], start["y"])
                                 and (row.get("fvel") or row.get("svel"))
                                 for row in inputs(text[offset:]) if row.get("player") == actor_player), timeout=6)
    moved = input_for(server.text(), actor_player)
    ammo_before = moved["ammo"]
    offset = len(server.text())
    run.press(actor_role, 228, .16)  # SDL_SCANCODE_RCTRL / native fire
    server.wait(lambda text: any(row.get("ammo", ammo_before) < ammo_before for row in inputs(text[offset:])
                                 if row.get("player") == actor_player), timeout=6)
    authoritative = input_for(server.text(), actor_player)
    peers = {}
    for role in observer_roles:
        observer = run.observers[role]
        observer.wait(lambda text: (input_for(text, actor_player) is not None and
                                    input_for(text, actor_player)["ammo"] == authoritative["ammo"] and
                                    bound_player(level_for(text, actor_player)) and
                                    abs(input_for(text, actor_player)["x"] - input_for(server.text(), actor_player)["x"]) < 256 and
                                    abs(input_for(text, actor_player)["y"] - input_for(server.text(), actor_player)["y"]) < 256), timeout=6)
        peers[role] = input_for(observer.text(), actor_player)
    if phase != "builtin-e1l1" and not all(in_fixture(row) for row in [authoritative, *peers.values()]):
        raise RuntimeError("native player left the fixture world after map transition")
    return {"phase": phase, "moved": {"before": bounded([start]), "after": bounded([moved])},
            "fire": {"server": authoritative, "peers": peers}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "input-helper", "grp", "work-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--port", type=int, default=24722)
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
    e1l1_marker = e1l1_floorpic(args.grp)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="native-levels-", dir=args.work_dir.resolve()))
    run, phase, result = Run(args, root), "setup", {"passed": False, "renderer": "CPU classic (no VR/SPS proof)"}
    try:
        for role in ("server", "peer1", "peer2", "replacement", "newcomer"):
            run.labs[role] = write_lab(root, role, args.grp)
        phase = "native dedicated server"
        server = run.launch("server", ["-dedicated", "-c1", "-m", "-port", str(args.port), "-map", "first.map"])
        server.wait(lambda text: "Multiplayer server initialized." in text, timeout=18)
        wait_level(server, 293, 0, 7, 0)
        players = {"server": 0}
        for index, role in enumerate(("peer1", "peer2"), 1):
            phase = f"{role} native join"
            joined = join(run, role, index)
            players[role] = joined["index"]
            wait_level(run.observers[role], 293, 0, 7, joined["index"])
        run.audit()
        initial = state(run, players)

        phase = "reject invalid server commands"
        invalid_offset, _ = run.server_command("map missing-level.map")
        server.wait(lambda text: "map: file missing-level.map not found." in text[invalid_offset:], timeout=5)
        invalid_numbers = ("0 1", "-1 1", "1junk 1", "2147483648 1",
                           "999999999999999999999999999999 1", "1 0", "1 -1", "1 3junk", "1", "1 65", "8 1")
        invalid_sync = {role: run.observers[role].text().count(SYNC) for role in ("peer1", "peer2")}
        for numbers in invalid_numbers:
            range_offset, _ = run.server_command("changelevel " + numbers)
            server.wait(lambda text: "changelevel <" in text[range_offset:], timeout=5)
        server.pause(.5)
        rejected = state(run, players)
        invalid_no_reload = all(run.observers[role].text().count(SYNC) == count for role, count in invalid_sync.items())

        phase = "native server map second.map"
        sync_offsets = {role: run.observers[role].text().count(SYNC) for role in ("peer1", "peer2")}
        run.server_command("map second.map")
        for role in ("peer1", "peer2"):
            run.observers[role].wait(lambda text, n=sync_offsets[role]: text.count(SYNC) > n, timeout=20)
            wait_level(run.observers[role], 183, 0, 7, players[role], timeout=15)
        wait_level(server, 183, 0, 7, 0, timeout=15)
        second = state(run, players)
        before_path, before_nonconstant = run.capture("peer1", "second-before")
        post_second = control_and_converge(run, "peer1", players["peer1"], ("peer1", "peer2"), "second-map")
        post_second_peer2 = control_and_converge(run, "peer2", players["peer2"], ("peer1", "peer2"), "second-map-peer2")

        phase = "native server changelevel 1 1"
        sync_offsets = {role: run.observers[role].text().count(SYNC) for role in ("peer1", "peer2")}
        run.server_command("changelevel 1 1")
        for role in ("peer1", "peer2"):
            run.observers[role].wait(lambda text, n=sync_offsets[role]: text.count(SYNC) > n, timeout=20)
            wait_level(run.observers[role], e1l1_marker, 0, 0, players[role], timeout=15)
        wait_level(server, e1l1_marker, 0, 0, 0, timeout=15)
        builtin = state(run, players)
        post_builtin = control_and_converge(run, "peer1", players["peer1"], ("peer1", "peer2"), "builtin-e1l1")

        phase = "builtin filename canonicalization"
        sync_offsets = {role: run.observers[role].text().count(SYNC) for role in ("peer1", "peer2")}
        label = "E1L1: HOLLYWOOD HOLOCAUST"
        label_offsets = {role: run.observers[role].text().count(label) for role in ("peer1", "peer2")}
        run.server_command("map e1l1.map")
        for role in ("peer1", "peer2"):
            run.observers[role].wait(lambda text, n=sync_offsets[role]: text.count(SYNC) > n, timeout=20)
            run.observers[role].wait(lambda text, n=label_offsets[role]: text.count(label) > n, timeout=15)
            wait_level(run.observers[role], e1l1_marker, 0, 0, players[role], timeout=15)
        wait_level(server, e1l1_marker, 0, 0, 0, timeout=15)
        builtin_by_name = state(run, players)

        phase = "native server map first.map"
        sync_offsets = {role: run.observers[role].text().count(SYNC) for role in ("peer1", "peer2")}
        run.server_command("map first.map")
        for role in ("peer1", "peer2"):
            run.observers[role].wait(lambda text, n=sync_offsets[role]: text.count(SYNC) > n, timeout=20)
            wait_level(run.observers[role], 293, 0, 7, players[role], timeout=15)
        wait_level(server, 293, 0, 7, 0, timeout=15)
        first_again = state(run, players)
        after_path, after_nonconstant = run.capture("peer1", "first-after")
        images_differ = ImageChops.difference(Image.open(before_path).convert("RGB"),
                                              Image.open(after_path).convert("RGB")).getbbox() is not None
        post_first = control_and_converge(run, "peer1", players["peer1"], ("peer1", "peer2"), "first-map-return")

        phase = "native reserved builtin level"
        label = "E1L8: CPU Reserved Slot"
        sync_offsets = {role: run.observers[role].text().count(SYNC) for role in ("peer1", "peer2")}
        label_offsets = {role: run.observers[role].text().count(label) for role in ("peer1", "peer2")}
        run.server_command("changelevel 1 8")
        for role in ("peer1", "peer2"):
            run.observers[role].wait(lambda text, n=sync_offsets[role]: text.count(SYNC) > n, timeout=20)
            run.observers[role].wait(lambda text, n=label_offsets[role]: text.count(label) > n, timeout=15)
            wait_level(run.observers[role], 311, 0, 7, players[role], timeout=15)
        wait_level(server, 311, 0, 7, 0, timeout=15)
        reserved_builtin = state(run, players)
        reserved_builtin_loads = all(run.observers[role].text().count(label) > label_offsets[role]
                                     for role in ("peer1", "peer2"))

        phase = "return from reserved builtin level"
        sync_offsets = {role: run.observers[role].text().count(SYNC) for role in ("peer1", "peer2")}
        run.server_command("map first.map")
        for role in ("peer1", "peer2"):
            run.observers[role].wait(lambda text, n=sync_offsets[role]: text.count(SYNC) > n, timeout=20)
            wait_level(run.observers[role], 293, 0, 7, players[role], timeout=15)
        wait_level(server, 293, 0, 7, 0, timeout=15)
        first_after_reserved_builtin = state(run, players)

        phase = "native reserved user-map canonicalization"
        sync_offsets = {role: run.observers[role].text().count(SYNC) for role in ("peer1", "peer2")}
        label_offsets = {role: run.observers[role].text().count(label) for role in ("peer1", "peer2")}
        run.server_command("map reserved.map")
        for role in ("peer1", "peer2"):
            run.observers[role].wait(lambda text, n=sync_offsets[role]: text.count(SYNC) > n, timeout=20)
            run.observers[role].wait(lambda text, n=label_offsets[role]: text.count(label) > n, timeout=15)
            wait_level(run.observers[role], 311, 0, 7, players[role], timeout=15)
        wait_level(server, 311, 0, 7, 0, timeout=15)
        reserved_user_map = state(run, players)
        reserved_user_loads = all(run.observers[role].text().count(label) > label_offsets[role]
                                  for role in ("peer1", "peer2"))
        reserved_control = control_and_converge(run, "peer2", players["peer2"], ("peer1", "peer2"), "reserved-user-map")

        phase = "return from reserved user map"
        sync_offsets = {role: run.observers[role].text().count(SYNC) for role in ("peer1", "peer2")}
        run.server_command("map first.map")
        for role in ("peer1", "peer2"):
            run.observers[role].wait(lambda text, n=sync_offsets[role]: text.count(SYNC) > n, timeout=20)
            wait_level(run.observers[role], 293, 0, 7, players[role], timeout=15)
        wait_level(server, 293, 0, 7, 0, timeout=15)
        first_final = state(run, players)

        phase = "client OSD server-only map commands"
        client_before = state(run, players)
        client_sync_before = {role: run.observers[role].text().count(SYNC) for role in ("peer1", "peer2")}
        client_offset = len(run.observers["peer1"].text())
        run.client_command("peer1", "map second.map")
        run.observers["peer1"].wait(lambda text: "Only the server can change multiplayer levels." in text[client_offset:], timeout=6)
        second_warning_end = len(run.observers["peer1"].text())
        run.client_command("peer1", "changelevel 1 2")
        run.observers["peer1"].wait(lambda text: "Only the server can change multiplayer levels." in text[second_warning_end:], timeout=6)
        run.observers["peer1"].pause(.5)
        client_after = state(run, players)
        client_no_reload = all(run.observers[role].text().count(SYNC) == count for role, count in client_sync_before.items())

        phase = "replacement peer native rejoin"
        run.graceful_disconnect("peer2", "PeerTwo")
        replacement = join(run, "replacement", players["peer2"])
        players["replacement"] = replacement["index"]
        wait_level(run.observers["replacement"], 293, 0, 7, replacement["index"], timeout=15)
        run.observers["server"].wait(lambda text: input_for(text, replacement["index"]) is not None, timeout=10)
        replacement_control = control_and_converge(run, "replacement", replacement["index"],
                                                    ("replacement",), "replacement-rejoin")

        phase = "server alone selected user map"
        run.graceful_disconnect("peer1", "PeerOne")
        run.graceful_disconnect("replacement", "Replace")
        run.server_command("map second.map")
        wait_level(server, 183, 0, 7, 0, timeout=15)
        lone = join(run, "newcomer", 1)
        wait_level(run.observers["newcomer"], 183, 0, 7, lone["index"], timeout=15)
        lone_state = state(run, {"server": 0, "newcomer": lone["index"]})
        run.audit()

        phase = "malformed user map isolated rejection"
        sync_before = run.observers["newcomer"].text().count(SYNC)
        loads_before = len(re.findall(r"E1L\d+:", run.observers["newcomer"].text()))
        malformed_offset, _ = run.server_command("map malformed.map")
        server.wait(lambda text: "Server could not start requested level; clients were not instructed to reload." in text[malformed_offset:], timeout=15)
        server.pause(.6)
        malformed_no_client_reload = (run.observers["newcomer"].text().count(SYNC) == sync_before and
                                       len(re.findall(r"E1L\d+:", run.observers["newcomer"].text())) == loads_before)

        phase = "valid native recovery after malformed map"
        run.server_command("map first.map")
        run.observers["newcomer"].wait(lambda text: text.count(SYNC) > sync_before, timeout=20)
        wait_level(run.observers["newcomer"], 293, 0, 7, lone["index"], timeout=15)
        wait_level(server, 293, 0, 7, 0, timeout=15)
        recovered_state = state(run, {"server": 0, "newcomer": lone["index"]})
        recovered_control = control_and_converge(run, "newcomer", lone["index"], ("newcomer",), "malformed-recovery")
        observed_states = [initial, rejected, second, builtin, builtin_by_name, first_again,
                           reserved_builtin, first_after_reserved_builtin, reserved_user_map, first_final,
                           client_before, client_after, lone_state, recovered_state]

        checks = {
            "actual_dedicated_stdin_receipts": run.receipt >= 6,
            "initial_native_indices_and_marker": all_state(initial, 293, 0, 7),
            "missing_map_and_out_of_range_rejected_without_transition": all_state(rejected, 293, 0, 7),
            "strict_numeric_rejections_no_client_reload": len(invalid_numbers) == 11 and invalid_no_reload,
            "native_server_second_user_map_all_peers": all_state(second, 183, 0, 7),
            "peer_movement_fire_ammo_converges_after_second_map": bool(post_second["fire"]["server"]),
            "second_client_movement_fire_converges_after_map": bool(post_second_peer2["fire"]["server"]),
            "native_changelevel_e1l1_all_peers": all_state(builtin, e1l1_marker, 0, 0),
            "native_builtin_filename_canonicalizes_e1l1_all_peers": all_state(builtin_by_name, e1l1_marker, 0, 0),
            "peer_movement_fire_ammo_converges_after_builtin": bool(post_builtin["fire"]["server"]),
            "native_server_returns_to_first_user_map": all_state(first_again, 293, 0, 7),
            "peer_movement_fire_ammo_converges_after_first_return": bool(post_first["fire"]["server"]),
            "reserved_builtin_e1l8_has_fresh_native_loads_and_marker": reserved_builtin_loads and all_state(reserved_builtin, 311, 0, 7),
            "return_from_reserved_builtin": all_state(first_after_reserved_builtin, 293, 0, 7),
            "reserved_user_map_canonicalizes_to_e1l8_and_marker": reserved_user_loads and all_state(reserved_user_map, 311, 0, 7),
            "reserved_user_map_second_client_controls": bool(reserved_control["fire"]["server"]),
            "return_from_reserved_user_map": all_state(first_final, 293, 0, 7),
            "F12_cpu_captures_nonconstant_and_transition_differs": before_nonconstant and after_nonconstant and images_differ,
            "client_map_and_changelevel_warn_server_only_and_keep_map": client_no_reload and all_state(client_before, 293, 0, 7) and all_state(client_after, 293, 0, 7),
            "replacement_peer_rejoins_current_map_with_native_index_and_control": replacement["index"] == players["peer2"] and bool(replacement_control["fire"]["server"]),
            "server_alone_user_map_reaches_new_joiner": lone["index"] == 1 and all_state(lone_state, 183, 0, 7),
            "malformed_user_map_reports_server_rejection_without_client_reload": malformed_no_client_reload,
            "valid_map_and_controls_recover_after_malformed": all_state(recovered_state, 293, 0, 7) and bool(recovered_control["fire"]["server"]),
            "actual_player_sprite_roles_match_native_indices_at_checkpoints": all(bound_player(row) for stage in observed_states for row in stage.values()),
            "no_gpu_libraries_or_devices": True,
        }
        result = {"passed": all(checks.values()), "checks": checks, "states": {
            "initial": initial, "rejected": rejected, "second": second, "builtin": builtin, "builtin_by_name": builtin_by_name,
            "first_again": first_again, "client_before": client_before, "client_after": client_after,
            "reserved_builtin": reserved_builtin, "first_after_reserved_builtin": first_after_reserved_builtin,
            "reserved_user_map": reserved_user_map, "first_final": first_final, "e1l1_floorpic": e1l1_marker},
            "controls": {"second": post_second, "builtin": post_builtin, "first_return": post_first,
                         "second_peer2": post_second_peer2, "reserved": reserved_control,
                         "replacement": replacement_control, "malformed_recovery": recovered_control},
            "all_player_ownership_after_later_snapshots": run.ownership,
            "screenshots": {"before": str(before_path), "after": str(after_path)}}
    except Exception as error:
        result = {"passed": False, "phase": phase, "error": str(error),
                  "renderer": "CPU classic (no VR/SPS proof)",
                  "error_sites": [{"file":Path(frame.filename).name,"line":frame.lineno,"function":frame.name} for frame in traceback.extract_tb(error.__traceback__)[-3:]]}
    finally:
        run.close()
    result["evidence_directory"] = str(root)
    (root / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
