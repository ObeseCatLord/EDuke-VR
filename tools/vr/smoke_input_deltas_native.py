#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Native transport regression for accumulated angular input.

Example:
  python3 tools/vr/smoke_input_deltas_native.py \\
    --binary work/eduke32-cpu-input \\
    --baseline-binary work/eduke32-cpu-input-before-input-deltas \\
    --input-helper work/headless_vr_input.so --grp /path/to/owned/DUKE3D.GRP \\
    --work-dir work/native-input-delta-runtime

The runner owns a dedicated server and SDL-dummy client in a GPU-denied
private bubblewrap namespace.  It supplies only normal keyboard events through
the existing owner-only SDL FIFO.  The CON fixture observes native input and
player fields; it neither writes input nor constructs packets.

For an XR listen server, run inside software_xr_lab.py and add
--xr-server-binary /absolute/path/eduke32-xr --display :105 --remote-port 49777.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from smoke_actions import Observer
from smoke_actions_multiplayer import client_player_index
from monado_remote import Remote
from smoke_multiplayer import CONFIG, stop
from smoke_native_levels import assert_cpu_binary, assert_gpu_devices_absent, sanitised_env


SYNC = "Multiplayer client level synchronization complete."
RIGHT_SCAN = 79  # SDL_SCANCODE_RIGHT
FORWARD_SCAN = 26  # SDL_SCANCODE_W
ROW_FIELD = re.compile(r"addlog vrdelta_(\w+)(?: \(player \d+\))? = (-?\d+)")
ROW_KEYS = ("tick", "player", "q16avel", "q16horz", "bits", "fvel", "svel", "extbits", "x", "y", "q16ang")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def bounded(values, limit=18):
    return values[-limit:]


def rows(text, player=None):
    result, row = [], {}
    for key, value in ROW_FIELD.findall(text):
        if key == "tick":
            row = {}
        if key in ROW_KEYS:
            row[key] = int(value)
        if key == "q16ang" and all(name in row for name in ROW_KEYS):
            if player is None or row["player"] == player:
                result.append(row)
    return result


def three_quiet_held(values):
    return any(all(row["q16avel"] == 0 and row["q16horz"] == 0 and row["fvel"] != 0
                   for row in values[index:index + 3])
               for index in range(max(0, len(values) - 2)))


def three_quiet(values):
    return any(all(row["q16avel"] == 0 and row["q16horz"] == 0 for row in values[index:index + 3])
               for index in range(max(0, len(values) - 2)))


def stationary_bounded_pulse(values):
    """Sum a pulse only when three native zero samples bound both ends."""
    active = [i for i, row in enumerate(values) if row["q16avel"] or row["q16horz"]]
    if not active or active[0] < 3 or len(values) - active[-1] <= 3:
        return None
    return {"yaw": sum(row["q16avel"] for row in values),
            "pitch": sum(row["q16horz"] for row in values),
            "samples": len(values), "first_tick": values[active[0]]["tick"],
            "last_tick": values[active[-1]]["tick"]}


def reexec_sandbox(args):
    # software_xr_lab.py already owns the only private network namespace and
    # Monado runtime. Re-entering bwrap here would isolate the listen server.
    if args.xr_server_binary:
        return
    if args._sandboxed:
        return
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise RuntimeError("bubblewrap is required for the CPU-only runner")
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
    command += [sys.executable, str(Path(__file__).resolve()), *child_args]
    os.execvpe(bwrap, command, safe)


def write_lab(root, role, grp, xr_server=False):
    lab = root / role
    lab.mkdir()
    (lab / "DUKE3D.GRP").symlink_to(grp)
    (lab / "eduke32.cfg").write_text(CONFIG if role == "server" and xr_server else
                                     CONFIG.replace("ScreenBPP = 32", "ScreenBPP = 8"))
    with (lab / "eduke32.cfg").open("a") as config:
        config.write(f'\n[Comm Setup]\nPlayerName = "Delta{role.title()}"\n')
    # These are ordinary game-function bindings driven by SDL keyboard events.
    # The XR server uses bounded periodic capture receipts after the input proof.
    rate = 60 if role == "client" else (10 if xr_server else 30)
    (lab / "autoexec.cfg").write_text(
        f"r_maxfps {rate}\nunbind W\nunbind Right\nbind W \"gamefunc_Move_Forward\"\n"
        "bind Right \"gamefunc_Turn_Right\"\n")
    for fixture in ("controller_test.con", "input_delta_test.con"):
        shutil.copyfile(HERE / "fixtures" / fixture, lab / fixture)
    return lab


class Run:
    def __init__(self, args, root, binary):
        self.args, self.root, self.binary = args, root, binary
        self.env = sanitised_env()
        self.labs, self.processes, self.observers, self.writers, self.logs = {}, {}, {}, {}, []

    def audit(self):
        assert_gpu_devices_absent()
        for role, process in self.processes.items():
            if process.poll() is not None:
                raise RuntimeError(f"{role} exited during CPU-only input-delta test")
            maps = Path(f"/proc/{process.pid}/maps").read_text(errors="replace").lower()
            fds = []
            for fd in Path(f"/proc/{process.pid}/fd").iterdir():
                try:
                    fds.append(os.readlink(fd).lower())
                except FileNotFoundError:
                    pass
            forbidden = ("libnvidia",) if role == "server" and self.args.xr_server_binary else (
                "libnvidia", "libglx", "libegl", "libvulkan")
            if any(name in maps for name in forbidden) or any(
                    "/dev/nvidia" in item or "/dev/dri" in item for item in fds):
                raise RuntimeError(f"{role} mapped a GPU library or device")

    def launch(self, role, command):
        lab, env = self.labs[role], dict(self.env)
        if role == "client":
            fifo = lab / "input.fifo"
            os.mkfifo(fifo, 0o600)
            if fifo.stat().st_mode & 0o077:
                raise RuntimeError("client input FIFO is not owner-only")
            self.writers[role] = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
            env.update(LD_PRELOAD=str(self.args.input_helper), EDUKE32_TEST_SDL_INPUT=str(fifo))
        elif self.args.xr_server_binary:
            # Preserve the enclosing software-XR lab's runtime, layer, and
            # software-renderer environment. This process is the only XR user.
            env = dict(os.environ)
            env.update(DISPLAY=self.args.display, SDL_VIDEODRIVER="x11", SDL_AUDIODRIVER="dummy",
                       EDUKE32_XR="1", EDUKE32_XR_UI="2", EDUKE32_XR_SINGLE_PASS="1",
                       EDUKE32_XR_WORLD_OUTPUT=str(lab / "xr-world"),
                       EDUKE32_XR_HUD_OUTPUT=str(lab / "xr-hud"), EDUKE32_XR_TEST_PVP="1",
                       EDUKE32_TEST_PRIVATE_WINDOW="1")
        log = (lab / "game.log").open("w")
        self.logs.append(log)
        executable = self.args.xr_server_binary if role == "server" and self.args.xr_server_binary else self.binary
        process = subprocess.Popen([str(executable), "-usecwd", "-nosetup", "-noautoload", "-nologo",
                                    "-ns", "-nm", *command, "-x", "input_delta_test.con"], cwd=lab, env=env,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        self.processes[role] = process
        self.observers[role] = Observer(process, lab / "game.log")
        self.audit()
        return self.observers[role]

    def key(self, scan, down):
        os.write(self.writers["client"], f"key {scan} {int(down)}\n".encode())

    def close(self):
        for process in reversed(list(self.processes.values())):
            if process.poll() is None:
                stop(process)
        for fd in self.writers.values():
            os.close(fd)
        for log in self.logs:
            log.close()


def wait_rows(observer, player, offset, predicate, description, timeout=10):
    def found(text):
        return predicate(rows(text[offset:], player))
    observer.wait(found, timeout=timeout)
    values = rows(observer.text()[offset:], player)
    if not predicate(values):
        raise RuntimeError(f"{description}: observation disappeared")
    return values


def run_pair(args, label, binary, port, root, require_accumulation):
    pair_root = root / label
    pair_root.mkdir()
    run = Run(args, pair_root, binary)
    result = {"label": label, "binary": str(binary), "binary_sha256": sha256(binary),
              "server_binary_sha256": sha256(args.xr_server_binary or binary), "passed": False,
              "checks": {}, "evidence_root": str(pair_root)}
    phase, player = "setup", None
    try:
        for role in ("server", "client"):
            run.labs[role] = write_lab(pair_root, role, args.grp, bool(args.xr_server_binary))
        phase = "XR listen server" if args.xr_server_binary else "native dedicated server"
        # Use the owned GRP's ordinary first level. Some owned shareware GRPs
        # deliberately reject user maps, while this transport proof needs no
        # custom geometry.
        server_mode = "-server" if args.xr_server_binary else "-dedicated"
        server = run.launch("server", [server_mode, "-c1", "-m", "-port", str(port), "-v1", "-l1"])
        server.wait(lambda text: "Multiplayer server initialized." in text, timeout=18)
        remote = Remote(args.remote_port) if args.xr_server_binary else None
        if remote:
            remote.neutral()
        phase = "native SDL client join"
        client = run.launch("client", ["-connect", f"127.0.0.1:{port}"])
        client.wait(lambda text: SYNC in text, timeout=25)
        client.pause(1.5)
        client.wait(lambda text: client_player_index(text) is not None, timeout=12)
        player = client_player_index(client.text())
        if player is None or player <= 0:
            raise RuntimeError("client did not expose a native joining player index")
        server.wait(lambda text: bool(rows(text, player)), timeout=12)
        run.audit()
        host_xr = None
        if remote:
            # Optional corroboration for the listen server's own player zero.
            # Keep this diagnostic: the remote runtime's menu/start state is
            # independent of the remote client's transport pulse proof.
            host_offset = len(server.text())
            remote.packet.left.thumbstick.y = .8
            remote.send()
            server.pause(.55)
            remote.neutral()
            server.pause(.15)
            host_values = rows(server.text()[host_offset:], 0)
            host_xr = {"movement_seen": any(row["fvel"] or row["svel"] for row in host_values),
                       "fire_seen": False, "rows": bounded(host_values)}
            host_offset = len(server.text())
            remote.packet.right.trigger_value = 1
            remote.packet.right.trigger_click = True
            remote.send()
            server.pause(.45)
            remote.neutral()
            host_values = rows(server.text()[host_offset:], 0)
            host_xr["fire_seen"] = any(row["bits"] & 4 for row in host_values)
            host_xr["fire_rows"] = bounded(host_values)

        phase = "slow keyboard turn consumed while forward remains held"
        slow_server_offset = len(server.text())
        run.key(FORWARD_SCAN, True)
        run.key(RIGHT_SCAN, True)
        slow_turn = wait_rows(server, player, slow_server_offset,
                              lambda values: any(row["q16avel"] > 0 and row["fvel"] != 0 for row in values),
                              "slow native turn did not reach server")
        release_offset = len(server.text())
        run.key(RIGHT_SCAN, False)
        slow_release = wait_rows(server, player, release_offset, three_quiet_held,
                                 "released angular input replayed while forward stayed held")

        phase = "server pause batches measured client increments"
        pulse_client_offset, pulse_server_offset = len(client.text()), len(server.text())
        wait_rows(client, player, pulse_client_offset, three_quiet, "client did not reach an angularly stationary boundary")
        wait_rows(server, player, pulse_server_offset, three_quiet, "server did not reach an angularly stationary boundary")
        client_offset, server_offset = pulse_client_offset, pulse_server_offset
        run.key(RIGHT_SCAN, True)
        wait_rows(client, player, client_offset, lambda values: any(row["q16avel"] > 0 for row in values),
                  "client did not produce a native angular sample")
        stopped = False
        try:
            os.kill(run.processes["server"].pid, signal.SIGSTOP)
            stopped = True
            time.sleep(.35)
            paused_client = rows(client.text()[client_offset:], player)
        finally:
            if stopped:
                os.kill(run.processes["server"].pid, signal.SIGCONT)
        paused_positive = [row["q16avel"] for row in paused_client if row["q16avel"] > 0]
        if len(paused_positive) < 2:
            raise RuntimeError("server pause did not measure two client angular increments")
        burst_rows = wait_rows(server, player, server_offset,
                               lambda values: any(row["q16avel"] > 0 for row in values),
                               "server did not expose angular input after resuming")
        run.key(RIGHT_SCAN, False)
        burst_release_offset = len(server.text())
        burst_release = wait_rows(server, player, burst_release_offset, three_quiet_held,
                                  "batched angular input replayed after release")
        # Wait for samples after the release on both peers, rather than an
        # earlier zero gap already present in the pulse's log segment.
        wait_rows(client, player, len(client.text()), three_quiet,
                  "client did not stop angular input after release")
        client.pause(.4)
        server.pause(.4)
        burst_client_pulse = stationary_bounded_pulse(rows(client.text()[pulse_client_offset:], player))
        burst_server_pulse = stationary_bounded_pulse(rows(server.text()[pulse_server_offset:], player))
        if not burst_client_pulse or not burst_server_pulse:
            raise RuntimeError("could not bound complete native client/server angular pulse segments")

        phase = "client pause catch-up consumes angular input once"
        catchup_server_offset, catchup_client_offset = len(server.text()), len(client.text())
        wait_rows(client, player, catchup_client_offset, three_quiet, "client not quiet before catch-up")
        wait_rows(server, player, catchup_server_offset, three_quiet, "server not quiet before catch-up")
        run.key(RIGHT_SCAN, True)
        wait_rows(server, player, catchup_server_offset, lambda values: any(row["q16avel"] > 0 for row in values),
                  "pre-pause client turn did not reach server")
        stopped = False
        try:
            os.kill(run.processes["client"].pid, signal.SIGSTOP)
            stopped = True
            time.sleep(.30)
        finally:
            if stopped:
                os.kill(run.processes["client"].pid, signal.SIGCONT)
        wait_rows(client, player, catchup_client_offset, lambda values: any(row["q16avel"] > 0 for row in values),
                  "client did not resume native angular input after catch-up")
        wait_rows(server, player, catchup_server_offset, lambda values: any(row["q16avel"] > 0 for row in values),
                  "server did not observe resumed native angular input")
        catchup_release_offset = len(server.text())
        run.key(RIGHT_SCAN, False)
        catchup_release = wait_rows(server, player, catchup_release_offset, three_quiet_held,
                                    "client catch-up replayed angular input after release")
        wait_rows(client, player, len(client.text()), three_quiet, "client not quiet after catch-up")
        client.pause(.4)
        server.pause(.4)
        catchup_client_pulse = stationary_bounded_pulse(rows(client.text()[catchup_client_offset:], player))
        catchup_server_pulse = stationary_bounded_pulse(rows(server.text()[catchup_server_offset:], player))
        if not catchup_client_pulse or not catchup_server_pulse:
            raise RuntimeError("could not bound complete native catch-up pulse segments")
        run.key(FORWARD_SCAN, False)
        xr_capture = None
        if args.xr_server_binary:
            captured = re.compile(r'OpenXR PvP frame: submitted=(\d+) captured=1')
            capture_offset = len(server.text())
            server.wait(lambda text: bool(captured.search(text[capture_offset:])), timeout=30)
            serial = int(captured.findall(server.text()[capture_offset:])[-1])
            left, right = [run.labs["server"] / f"xr-hud-{serial}-{eye}.ppm" for eye in ("left", "right")]
            xr_capture = {"left": left.name, "right": right.name, "submitted_frame": serial,
                          "fresh_after_input": True,
                          "eyes_distinct": left.read_bytes() != right.read_bytes()}

        run.audit()

        burst_server_positive = [row["q16avel"] for row in burst_rows if row["q16avel"] > 0]
        diagnostics = {
            "batch_measured_two_client_increments": len(paused_positive) >= 2,
            "batch_delta_exceeds_each_paused_client_increment": bool(burst_server_positive) and
                max(burst_server_positive) > max(paused_positive),
            "batch_release_stops_angular_replay": three_quiet_held(burst_release),
            "client_stop_continue_resumes_native_turn": True,
            "client_catchup_release_stops_angular_replay": three_quiet_held(catchup_release),
        }
        checks = {
            "actual_native_join_index": player > 0,
            "slow_turn_reaches_authoritative_server": any(row["q16avel"] > 0 for row in slow_turn),
            "angular_release_preserves_held_forward": three_quiet_held(slow_release),
            "stationary_bounded_client_server_pulse_sums_equal":
                (burst_client_pulse["yaw"], burst_client_pulse["pitch"]) ==
                (burst_server_pulse["yaw"], burst_server_pulse["pitch"]),
            "stationary_bounded_catchup_sums_equal":
                (catchup_client_pulse["yaw"], catchup_client_pulse["pitch"]) ==
                (catchup_server_pulse["yaw"], catchup_server_pulse["pitch"]),
        }
        if xr_capture:
            checks["fresh_xr_server_two_eye_output_after_client_input"] = (
                xr_capture["fresh_after_input"] and xr_capture["eyes_distinct"])
        result.update(phase="complete", player=player, checks=checks, diagnostics=diagnostics,
                      slow_turn=bounded(slow_turn), slow_release=bounded(slow_release),
                      paused_client=bounded(paused_client), burst_server=bounded(burst_rows),
                      burst_release=bounded(burst_release), catchup_release=bounded(catchup_release),
                      burst_client_pulse=burst_client_pulse, burst_server_pulse=burst_server_pulse,
                      catchup_client_pulse=catchup_client_pulse, catchup_server_pulse=catchup_server_pulse,
                      xr_capture=xr_capture, xr_host_diagnostic=host_xr)
        result["passed"] = all(checks.values()) if require_accumulation else False
    except Exception as error:
        result.update(phase=phase, error=str(error), player=player)
        for role in ("server", "client"):
            if role in run.labs:
                log = run.labs[role] / "game.log"
                if log.exists():
                    result[role + "_rows"] = bounded(rows(log.read_text(errors="replace"), player))
    finally:
        if 'remote' in locals() and remote:
            try:
                remote.close()
            except OSError as error:
                result['cleanup_error'] = str(error)
                result['passed'] = False
        run.close()
        result["cleanup"] = all(process.poll() is not None for process in run.processes.values())
        (pair_root / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "input-helper", "grp", "work-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--baseline-binary", type=Path)
    parser.add_argument("--xr-server-binary", type=Path,
                        help="listen-server executable; requires an enclosing software_xr_lab.py runtime")
    parser.add_argument("--display", default=":105", help="existing software-XR lab display")
    parser.add_argument("--remote-port", type=int, default=49777, help="existing software-XR lab Monado remote port")
    parser.add_argument("--port", type=int, default=24791)
    parser.add_argument("--_sandboxed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be in 1..65535")
    if not 1 <= args.remote_port <= 65535:
        parser.error("--remote-port must be in 1..65535")
    args.binary, args.input_helper, args.grp = (args.binary.resolve(), args.input_helper.resolve(), args.grp.resolve())
    if args.baseline_binary:
        args.baseline_binary = args.baseline_binary.resolve()
    if args.xr_server_binary:
        args.xr_server_binary = args.xr_server_binary.resolve()
        if not args.display or not os.environ.get("XR_RUNTIME_JSON"):
            parser.error("--xr-server-binary requires an existing software_xr_lab.py XR_RUNTIME_JSON environment")
        if args.baseline_binary:
            parser.error("--baseline-binary compares CPU pairs; do not combine it with --xr-server-binary")
    if args.baseline_binary and args.port == 65535:
        parser.error("--baseline-binary needs an additional port below 65536")
    required = (args.binary, args.input_helper, args.grp)
    if (not all(path.is_file() for path in required) or
            (args.baseline_binary and not args.baseline_binary.is_file()) or
            (args.xr_server_binary and not args.xr_server_binary.is_file())):
        parser.error("--binary, --input-helper, --grp, and optional binary paths must be existing files")
    reexec_sandbox(args)
    assert_gpu_devices_absent()
    assert_cpu_binary(args.binary)
    if args.baseline_binary:
        assert_cpu_binary(args.baseline_binary)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="native-input-delta-", dir=args.work_dir.resolve()))
    current = run_pair(args, "current", args.binary, args.port, root, True)
    result = {"passed": current["passed"], "current": current,
              "qualification": ("Actual CPU client input into an XR listen server." if args.xr_server_binary else
                                "Actual CPU-only native SDL keyboard and transport observation; no packet/input injection and no gameplay/XR proof."),
              "evidence_root": str(root)}
    if args.baseline_binary:
        # Baseline evidence remains diagnostic: it is never counted as a product pass.
        baseline = run_pair(args, "baseline", args.baseline_binary, args.port + 1, root, False)
        result["baseline"] = baseline
        result["baseline_contrast"] = {
            "baseline_pulse_sums_equal": baseline.get("checks", {}).get("stationary_bounded_client_server_pulse_sums_equal"),
            "baseline_catchup_sums_equal": baseline.get("checks", {}).get("stationary_bounded_catchup_sums_equal"),
            "current_pulse_sums_equal": current.get("checks", {}).get("stationary_bounded_client_server_pulse_sums_equal"),
            "current_catchup_sums_equal": current.get("checks", {}).get("stationary_bounded_catchup_sums_equal"),
            "baseline_burst_accumulated": baseline.get("diagnostics", {}).get(
                "batch_delta_exceeds_each_paused_client_increment"),
            "current_burst_accumulated": current.get("diagnostics", {}).get(
                "batch_delta_exceeds_each_paused_client_increment"),
            "baseline_is_diagnostic_only": True,
            "batch_and_catchup_predicates_are_diagnostic_when_equal": True,
        }
    (root / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
