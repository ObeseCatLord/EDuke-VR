#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""CPU-only native startup/admission lifecycle regression.

Each case uses a normal native dedicated server and at most one native client.
The first-map delay is a CON ``startscreen`` whose Screen_Play loop continues
calling gameHandleEvents; it is not an engine sleep or packet injection.  The
small ENet peer only proves transport disconnect before admission.
"""
import argparse
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
from smoke_native_levels import assert_cpu_binary, assert_gpu_devices_absent, sanitised_env
from smoke_pistol_reload_native import Run, sha256

SYNC = "Multiplayer client level synchronization complete."
DELAY_STARTED = re.compile(r"addlog vrsu_delay_started\b[^=]*= 1")
DELAY_COMPLETE = re.compile(r"addlog vrsu_delay_complete\b")
PLAYER = re.compile(r"addlog vrsu_player\b[^=]*= (-?\d+)")


def reexec_sandbox(args):
    """This script owns its own bwrap re-exec; no other runner is imported."""
    if args._sandboxed:
        return
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    safe = sanitised_env()
    child_args = [item for item in sys.argv[1:] if item != "--_sandboxed"] + ["--_sandboxed"]
    command = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
               "--unshare-pid", "--unshare-net", "--bind", str(work), str(work),
               "--chdir", str(Path.cwd()), "--clearenv"]
    for key in ("PATH", "LANG", "LC_ALL", "TZ"):
        if key in safe:
            command += ["--setenv", key, safe[key]]
    command += ["nice", "-n", "10", sys.executable, str(Path(__file__).resolve()), *child_args]
    os.execvpe("bwrap", command, safe)


def wait_log(observer, predicate, timeout, label):
    try:
        return observer.wait(predicate, timeout=timeout)
    except Exception as error:
        raise RuntimeError(f"{label}: {error}") from error


def wait_process(process, timeout, label):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return process.returncode
        time.sleep(.05)
    raise RuntimeError(f"{label}: process remained alive for {timeout}s")


def log_text(lab):
    return (lab / "game.log").read_text(errors="replace")


def make_lab(root, role, grp):
    lab = root / role
    lab.mkdir()
    (lab / "DUKE3D.GRP").symlink_to(grp)
    (lab / "eduke32.cfg").write_text(CONFIG.replace("ScreenBPP = 32", "ScreenBPP = 8"))
    with (lab / "eduke32.cfg").open("a") as output:
        output.write(f'\n[Comm Setup]\nPlayerName = "Startup{role.title()}"\n')
    (lab / "autoexec.cfg").write_text("r_maxfps 30\n")
    shutil.copyfile(HERE / "fixtures" / "startup_delay_test.con", lab / "startup_delay_test.con")
    (lab / "startup.map").write_bytes(room())
    return lab


class LifecycleRun(Run):
    """Reuse the established CPU audit/cleanup runner, adding a private quit FIFO."""
    def __init__(self, args, root):
        super().__init__(args, root, args.binary, con_file="startup_delay_test.con")
        self.quit_writers = {}

    def launch(self, role, command):
        lab = self.labs[role]
        env = dict(self.env)
        if role == "client":
            input_fifo, quit_fifo = lab / "input.fifo", lab / "startup-events.fifo"
            for fifo in (input_fifo, quit_fifo):
                os.mkfifo(fifo, 0o600)
                status = fifo.stat()
                if status.st_uid != os.geteuid() or status.st_mode & 0o077:
                    raise RuntimeError("client event FIFO is not owner-only")
            self.writers[role] = os.open(input_fifo, os.O_RDWR | os.O_NONBLOCK)
            self.quit_writers[role] = os.open(quit_fifo, os.O_RDWR | os.O_NONBLOCK)
            env.update(LD_PRELOAD=f"{self.args.startup_helper}:{self.args.input_helper}",
                       EDUKE32_TEST_SDL_INPUT=str(input_fifo),
                       EDUKE32_TEST_STARTUP_EVENTS=str(quit_fifo),
                       EDUKE32_TEST_PRIVATE_STARTUP="1")
        log = (lab / "game.log").open("w")
        self.logs.append(log)
        process = subprocess.Popen([str(self.binary), "-usecwd", "-nosetup", "-noautoload", "-nologo",
                                    "-ns", "-nm", *command, "-x", self.con_file], cwd=lab, env=env,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        self.processes[role] = process
        self.observers[role] = Observer(process, lab / "game.log")
        self.audit()
        return self.observers[role]

    def quit_client(self):
        os.write(self.quit_writers["client"], b"quit\n")

    def close(self):
        super().close()
        for descriptor in self.quit_writers.values():
            os.close(descriptor)


def start_server(args, root, port):
    root.mkdir()
    run = LifecycleRun(args, root)
    for role in ("server", "client"):
        run.labs[role] = make_lab(root, role, args.grp)
    server = run.launch("server", ["-dedicated", "-c1", "-m", "-port", str(port), "-map", "startup.map"])
    wait_log(server, lambda text: "Multiplayer server initialized." in text, 18, "dedicated startup")
    wait_log(server, lambda text: bool(DELAY_STARTED.search(text)), 12, "first-map Screen_Play delay")
    return run, server


def assert_join(server, client):
    wait_log(client, lambda text: SYNC in text, 18, "native client synchronization")
    wait_log(client, lambda text: client_player_index(text) is not None, 12, "native client index")
    index = client_player_index(client.text())
    if index is None or index <= 0:
        raise RuntimeError(f"native client index invalid: {index}")
    wait_log(server, lambda text: index in [int(item) for item in PLAYER.findall(text)], 12,
             "authoritative remote player observation")
    return index


def case_early_join(args, root, port):
    result = {"name": "early_native_join_while_first_map_is_held", "passed": False}
    run = None
    try:
        run, server = start_server(args, root, port)
        delay_at = time.monotonic()
        client = run.launch("client", ["-connect", f"127.0.0.1:{port}"])
        wait_log(server, lambda text: "A new client connected" in text, 8, "early transport connect")
        if SYNC in client.text():
            raise RuntimeError("client synchronized before the controlled first-map delay completed")
        wait_log(server, lambda text: bool(DELAY_COMPLETE.search(text)), 48, "35s first-map delay")
        held_seconds = time.monotonic() - delay_at
        if held_seconds < 35:
            raise RuntimeError(f"first map was held only {held_seconds:.2f}s")
        index = assert_join(server, client)
        run.audit()
        result.update(passed=True, held_seconds=round(held_seconds, 2), remote_index=index,
                      server_players=PLAYER.findall(server.text())[-8:],
                      client_index_samples=client_player_index(client.text()))
    except Exception as error:
        result["error"] = str(error)
    finally:
        if run:
            run.close()
            result["cleanup"] = all(process.poll() is not None for process in run.processes.values())
    return result


def case_unassigned_disconnect(args, root, port, peer):
    result = {"name": "unassigned_transport_disconnect_then_native_join", "passed": False}
    run = peer_process = None
    try:
        run, server = start_server(args, root, port)
        peer_log = root / "transport-peer.log"
        with peer_log.open("w") as output:
            peer_process = subprocess.Popen([str(peer), str(port)], stdin=subprocess.DEVNULL,
                                            stdout=output, stderr=subprocess.STDOUT)
        if wait_process(peer_process, 9, "transport peer") != 0:
            raise RuntimeError("transport-only peer did not complete its connect/disconnect")
        peer_text = peer_log.read_text(errors="replace")
        if "transport-connected" not in peer_text or "transport-disconnected-before-admission" not in peer_text:
            raise RuntimeError("transport-only peer lacked connect/disconnect evidence")
        if DELAY_COMPLETE.search(server.text()):
            raise RuntimeError("transport peer did not run during first-map admission hold")
        if " disconnected." in server.text():
            raise RuntimeError("unassigned transport peer mutated an assigned native player")
        client = run.launch("client", ["-connect", f"127.0.0.1:{port}"])
        wait_log(server, lambda text: bool(DELAY_COMPLETE.search(text)), 48, "first-map delay after transport disconnect")
        index = assert_join(server, client)
        if index != 1:
            raise RuntimeError(f"unassigned transport peer consumed native player index {index}")
        server_players = [int(item) for item in PLAYER.findall(server.text())]
        if 0 not in server_players or index not in server_players:
            raise RuntimeError("normal join did not retain player 0 and add its remote player")
        run.audit()
        result.update(passed=True, remote_index=index, server_players=server_players[-10:],
                      transport_log=str(peer_log))
    except Exception as error:
        result["error"] = str(error)
    finally:
        if peer_process and peer_process.poll() is None:
            stop(peer_process)
        if run:
            run.close()
            result["cleanup"] = all(process.poll() is not None for process in run.processes.values())
    return result


def case_server_loss(args, root, port):
    result = {"name": "server_loss_during_initial_snapshot_wait", "passed": False}
    run = None
    try:
        run, server = start_server(args, root, port)
        client = run.launch("client", ["-connect", f"127.0.0.1:{port}"])
        wait_log(server, lambda text: "A new client connected" in text, 8, "client connected before server loss")
        wait_log(client, lambda text: "Waiting for initial snapshot..." in text, 12,
                 "client initial-snapshot wait")
        if SYNC in client.text():
            raise RuntimeError("client reached a snapshot before deliberate server loss")
        client_offset = len(client.text())
        stop(run.processes["server"])
        wait_process(run.processes["server"], 1, "server loss")
        deadline = time.monotonic() + 42
        while time.monotonic() < deadline:
            text = log_text(run.labs["client"])
            if "Disconnected." in text or client.process.poll() is not None:
                break
            time.sleep(.1)
        else:
            raise RuntimeError("client remained in initial snapshot wait after server loss")
        text = log_text(run.labs["client"])
        if client.process.poll() is None and "Disconnected." not in text:
            raise RuntimeError("client neither exited nor returned through native disconnect handling")
        wait_log(client, lambda value: "addlog vrsu_menu_event" in value[client_offset:], 12,
                 "post-disconnect native menu draw")
        result.update(passed=True, client_exit=client.process.poll(), disconnect_logged=True,
                      initial_snapshot_wait_logged=True, post_disconnect_menu_draw=True,
                      synchronized_before_loss=False)
    except Exception as error:
        result["error"] = str(error)
    finally:
        if run:
            run.close()
            result["cleanup"] = all(process.poll() is not None for process in run.processes.values())
    return result


def case_quit_wait(args, root, port):
    result = {"name": "owned_sdl_quit_during_initial_snapshot_wait", "passed": False}
    run = None
    try:
        run, server = start_server(args, root, port)
        client = run.launch("client", ["-connect", f"127.0.0.1:{port}"])
        wait_log(server, lambda text: "A new client connected" in text, 8, "client connected before owned quit")
        wait_log(client, lambda text: "Waiting for initial snapshot..." in text, 12,
                 "client initial-snapshot wait")
        if SYNC in client.text():
            raise RuntimeError("client reached a snapshot before owned quit")
        run.quit_client()
        exit_code = wait_process(client.process, 12, "SDL_QUIT during initial snapshot wait")
        text = log_text(run.labs["client"])
        if exit_code != 0 or "sdl_dummy_startup: injected SDL_QUIT" not in text:
            raise RuntimeError("private SDL quit helper did not report its owned event")
        result.update(passed=True, client_exit=exit_code, helper_quit_logged=True,
                      initial_snapshot_wait_logged=True)
    except Exception as error:
        result["error"] = str(error)
    finally:
        if run:
            run.close()
            result["cleanup"] = all(process.poll() is not None for process in run.processes.values())
    return result


def build_helpers(args, root):
    startup = root / "sdl_dummy_startup.so"
    peer = root / "startup_peer"
    commands = [
        ["c++", "-std=c++17", "-fPIC", "-shared", "-Wall", "-Wextra", "-Werror",
         str(HERE / "sdl_dummy_startup.cpp"), "-o", str(startup), "-I/usr/include/SDL2", "-lSDL2", "-ldl"],
        ["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(HERE.parent.parent / "source" / "build" / "include"),
         str(HERE / "startup_peer.cpp"), "-o", str(peer)],
    ]
    for command in commands:
        # The sandbox mounts only this work root writable; keep compiler scratch
        # files there as well rather than relying on the read-only host /tmp.
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                       env=dict(os.environ, TMPDIR=str(root)))
    args.startup_helper = startup
    return peer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "input-helper", "grp", "work-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--port", type=int, default=24984)
    parser.add_argument("--_sandboxed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    for name in ("binary", "input_helper", "grp", "work_dir"):
        setattr(args, name, getattr(args, name).resolve())
    if not 1 <= args.port < 65531:
        parser.error("--port must be in 1..65530")
    if not all(path.is_file() for path in (args.binary, args.input_helper, args.grp)):
        parser.error("--binary, --input-helper, and --grp must name existing files")
    reexec_sandbox(args)
    assert_gpu_devices_absent()
    assert_cpu_binary(args.binary)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="native-startup-lifecycle-", dir=args.work_dir))
    result = {"passed": False, "renderer": "CPU classic SDL dummy (no GPU/X11/desktop)",
              "evidence_directory": str(root), "binary_sha256": sha256(args.binary),
              "input_helper_sha256": sha256(args.input_helper), "cases": []}
    try:
        peer = build_helpers(args, root)
        result["startup_helper_sha256"] = sha256(args.startup_helper)
        result["cases"] = [case_early_join(args, root / "early", args.port),
                           case_unassigned_disconnect(args, root / "unassigned", args.port + 1, peer),
                           case_server_loss(args, root / "server-loss", args.port + 2),
                           case_quit_wait(args, root / "quit", args.port + 3)]
        result["passed"] = all(case.get("passed") and case.get("cleanup") for case in result["cases"])
    except Exception as error:
        result["error"] = str(error)
    finally:
        (root / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
