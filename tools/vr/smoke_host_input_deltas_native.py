#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""CPU-native host-input angular pulse regression.

Default mode records a baseline diagnostic and always exits nonzero.  Re-run a
corrected binary with --expect-fixed to require the measured host/client sums.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import re
import signal
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from smoke_actions_multiplayer import client_player_index
from smoke_input_deltas_native import (FORWARD_SCAN, RIGHT_SCAN, Run, bounded, rows,
                                       sha256, stationary_bounded_pulse,
                                       three_quiet_held, write_lab)
from smoke_native_levels import assert_cpu_binary, assert_gpu_devices_absent, sanitised_env


SYNC = "Multiplayer client level synchronization complete."
OBSERVER_FIELD = re.compile(r"addlog vrhostobs_(\w+)(?: \(player \d+\))? = (-?\d+)")
DRAW_FIELD = re.compile(r"addlog vrhostdraw_epoch(?: \(player \d+\))? = (-?\d+)")
OBSERVER_KEYS = ("tick", "draw", "q16avel", "q16horz", "q16ang")


def reexec_sandbox(args):
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
               "--unshare-pid", "--unshare-net", "--bind", str(work), str(work),
               "--chdir", str(Path.cwd()), "--clearenv"]
    for key in ("PATH", "LANG", "LC_ALL", "TZ"):
        if key in safe:
            command += ["--setenv", key, safe[key]]
    command += [sys.executable, str(Path(__file__).resolve()), *child_args]
    os.execvpe(bwrap, command, safe)


def wait_rows(observer, player, offset, predicate, description, timeout=12):
    observer.wait(lambda text: predicate(rows(text[offset:], player)), timeout=timeout)
    values = rows(observer.text()[offset:], player)
    if not predicate(values):
        raise RuntimeError(description)
    return values


def bounded_pulse(values, label):
    pulse = stationary_bounded_pulse(values)
    if not pulse:
        raise RuntimeError(f"{label} lacks three quiet native samples around a host0 pulse")
    return pulse


def producer_rows(text):
    result, row = [], {}
    for key, value in OBSERVER_FIELD.findall(text):
        if key == "tick":
            row = {}
        if key in OBSERVER_KEYS:
            row[key] = int(value)
        if key == "q16ang" and all(name in row for name in OBSERVER_KEYS):
            result.append(row)
    return result


def display_epochs(text):
    return [int(value) for value in DRAW_FIELD.findall(text)]


def producer_interval(values):
    """Observe an entire draw epoch; never slide the two-tick allowance."""
    start = 0
    while start < len(values):
        draw = values[start]["draw"]
        end = start
        while end < len(values) and values[end]["draw"] == draw:
            end += 1
        group = values[start:end]
        active = lambda row: row["q16avel"] or row["q16horz"]
        if end < len(values) and len(group) >= 3 and any(active(row) for row in group[:2]):
            return {'rows': group, 'consumed_once': all(not active(row) for row in group[2:])}
        start = end
    return None


def producer_proof(host, run):
    """Exercise local sender early-return before any receiver is connected."""
    offset, deadline = len(host.text()), time.monotonic() + 14
    run.key(RIGHT_SCAN, True)
    try:
        wait_rows(host, 0, offset, lambda values: any(row['q16avel'] for row in values),
                  'host-alone turn did not become active')
        # A stopped owned process accumulates real wall-clock time. On resume,
        # native scheduling must expose catch-up ticks without another draw.
        os.kill(run.processes['client'].pid, signal.SIGSTOP)
        try:
            time.sleep(.30)
        finally:
            os.kill(run.processes['client'].pid, signal.SIGCONT)
        while time.monotonic() < deadline:
            text = host.text()[offset:]
            epochs, values = display_epochs(text), producer_rows(text)
            interval = producer_interval(values)
            if epochs and interval is not None:
                return {"display_epochs": bounded(epochs, 8), "no_draw_interval": interval['rows'],
                        'consumed_once': interval['consumed_once']}
            time.sleep(.05)
        groups, start = [], 0
        values = producer_rows(host.text()[offset:])
        while start < len(values):
            end = start + 1
            while end < len(values) and values[end]["draw"] == values[start]["draw"]:
                end += 1
            groups.append(end - start)
            start = end
        raise RuntimeError("host-alone DISPLAYREST/no-draw producer interval unavailable: "
                           f"display_epochs={len(display_epochs(host.text()[offset:]))}, "
                           f"host_ticks={len(values)}, longest_epoch_ticks={max(groups, default=0)}")
    finally:
        run.key(RIGHT_SCAN, False)


def run_pulse(name, host, receivers, run, pause_role=None):
    """Drive a complete host0 turn pulse while W stays physically held."""
    # The preceding producer probe releases a still-held turn asynchronously.
    # Drain that release before opening this pulse's independently bounded log.
    quiet = lambda values: len(values) >= 3 and all(
        not row['q16avel'] and not row['q16horz'] for row in values[-3:])
    for observer in (host, *receivers.values()):
        wait_rows(observer, 0, len(observer.text()), quiet, name + ': previous turn did not settle')
    run.key(FORWARD_SCAN, True) if name == "slow" else None
    host_offset = len(host.text())
    receiver_offsets = {role: len(observer.text()) for role, observer in receivers.items()}
    # Put three held-forward, zero-angular samples into this segment before
    # turning; stationary_bounded_pulse intentionally rejects a peak-only cut.
    wait_rows(host, 0, host_offset, three_quiet_held, f"{name}: host lacks a quiet held-forward boundary")
    for role, observer in receivers.items():
        wait_rows(observer, 0, receiver_offsets[role], three_quiet_held,
                  f"{name}: {role} lacks a quiet held-forward boundary")
    run.key(RIGHT_SCAN, True)
    wait_rows(host, 0, host_offset, lambda values: any(row["q16avel"] > 0 for row in values),
              f"{name}: host did not produce input deltas")
    paused_host = []
    if pause_role:
        process = run.processes[pause_role]
        paused_host_offset = len(host.text())
        os.kill(process.pid, signal.SIGSTOP)
        try:
            time.sleep(.30)
            paused_host = rows(host.text()[paused_host_offset:], 0)
        finally:
            os.kill(process.pid, signal.SIGCONT)
        if pause_role == "receiver1" and len({row["tick"] for row in paused_host if row["q16avel"] > 0}) < 2:
            raise RuntimeError("receiver pause did not measure two host angular increments")
    for role, observer in receivers.items():
        wait_rows(observer, 0, receiver_offsets[role], lambda values: any(row["q16avel"] > 0 for row in values),
                  f"{name}: {role} did not observe host0 deltas")
    release_host_offset = len(host.text())
    release_receiver_offsets = {role: len(observer.text()) for role, observer in receivers.items()}
    run.key(RIGHT_SCAN, False)
    wait_rows(host, 0, release_host_offset, three_quiet_held,
                             f"{name}: host replayed turn after release")
    for role, observer in receivers.items():
        wait_rows(observer, 0, release_receiver_offsets[role], three_quiet_held,
                  f"{name}: {role} replayed turn after release")
    host.pause(.35)
    for observer in receivers.values():
        observer.pause(.35)
    host_values = rows(host.text()[host_offset:], 0)
    host_pulse = bounded_pulse(host_values, name + " host")
    receiver_values = {role: rows(observer.text()[receiver_offsets[role]:], 0) for role, observer in receivers.items()}
    receiver_pulses = {role: bounded_pulse(values, name + " " + role) for role, values in receiver_values.items()}
    sums_equal = {role: (host_pulse["yaw"], host_pulse["pitch"]) == (pulse["yaw"], pulse["pitch"])
                  for role, pulse in receiver_pulses.items()}
    return {"host_pulse": host_pulse, "receiver_pulses": receiver_pulses, "sums_equal": sums_equal,
            "host_rows": bounded(host_values), "receiver_rows": {role: bounded(values) for role, values in receiver_values.items()},
            "paused_host_rows": bounded(paused_host)}


def run_case(args, root):
    # Reuse input-delta Run: its role named "client" is this test's host so
    # it alone receives the owned keyboard FIFO; receivers use ordinary SDL.
    run = Run(args, root, args.binary)
    result = {"passed": False, "phase": "setup"}
    try:
        host_lab = write_lab(root, "host", args.grp)
        receiver_labs = {role: write_lab(root, role, args.grp) for role in ("receiver1", "receiver2")}
        for lab in (host_lab, *receiver_labs.values()):
            shutil.copyfile(HERE / "fixtures" / "host_input_delta_observer.con", lab / "host_input_delta_observer.con")
            with (lab / "input_delta_test.con").open("a") as fixture:
                fixture.write("\ninclude host_input_delta_observer.con\n")
        # Native r_maxfps clamps this legacy requested value to 30. The labels
        # "slow"/"fast" do not prove a rate contrast; measured draw epochs and
        # owned-process suspension establish the catch-up/batching conditions.
        (host_lab / "autoexec.cfg").write_text('r_maxfps 10\nunbind W\nunbind Right\nbind W "gamefunc_Move_Forward"\nbind Right "gamefunc_Turn_Right"\n')
        run.labs = {"client": host_lab, **receiver_labs}
        result["phase"] = "CPU listen server"
        # -c3 is native Deathmatch (No Spawn), selected to avoid co-op spawn
        # placement in this input-only topology; it is not a player-count flag.
        host = run.launch("client", ["-server", "-c3", "-v1", "-l1", "-port", str(args.port)])
        host.wait(lambda text: "Multiplayer server initialized." in text, timeout=18)
        result["phase"] = "host-alone producer drain"
        result["host_alone_producer"] = producer_proof(host, run)
        result["phase"] = "ordinary client joins"
        receivers, players = {}, {}
        for role in ("receiver1", "receiver2"):
            observer = run.launch(role, ["-connect", f"127.0.0.1:{args.port}"])
            observer.wait(lambda text: SYNC in text, timeout=25)
            observer.wait(lambda text: client_player_index(text) not in (None, 0), timeout=14)
            receivers[role], players[role] = observer, client_player_index(observer.text())
        if len(set(players.values())) != 2:
            raise RuntimeError(f"joining clients do not have unique native player indices: {players}")
        host.wait(lambda text: bool(rows(text, 0)), timeout=12)
        for observer in receivers.values():
            observer.wait(lambda text: bool(rows(text, 0)), timeout=12)
        run.audit()
        result["client_players"] = players
        result["joined_producer"] = producer_proof(host, run)
        result["phase"] = "bounded host0 angular pulses"
        slow = run_pulse("slow", host, receivers, run)
        batch = run_pulse("receiver_stop", host, receivers, run, "receiver1")
        catchup = run_pulse("host_stop", host, receivers, run, "client")
        run.key(FORWARD_SCAN, False)
        checks = {
            "host_alone_displayrest_and_three_tick_no_draw_drain": result["host_alone_producer"]["consumed_once"],
            "host_with_two_clients_three_tick_no_draw_drain": result["joined_producer"]["consumed_once"],
            "two_unique_native_joining_player_indices": all(player > 0 for player in players.values()),
            "slow_host_fast_clients_whole_pulse_sums_equal": all(slow["sums_equal"].values()),
            "receiver_stop_batch_whole_pulse_sums_equal": all(batch["sums_equal"].values()),
            "host_stop_catchup_whole_pulse_sums_equal": all(catchup["sums_equal"].values()),
        }
        result.update(phase="complete", checks=checks, slow=slow, receiver_stop_batch=batch,
                      host_stop_catchup=catchup, passed=all(checks.values()))
        run.audit()
    except Exception as error:
        result.update(error=str(error))
        for role in ("client", "receiver1", "receiver2"):
            if role in run.labs:
                log = run.labs[role] / "game.log"
                if log.exists():
                    text = log.read_text(errors="replace")
                    result[role + "_host0_rows"] = bounded(rows(text, 0))
                    if role == "client":
                        result["host_alone_observer_rows"] = bounded(producer_rows(text))
                        result["host_display_epochs"] = bounded(display_epochs(text), 12)
    finally:
        run.close()
        result["cleanup"] = all(process.poll() is not None for process in run.processes.values())
        (root / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "input-helper", "grp", "work-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--port", type=int, default=24801)
    parser.add_argument("--expect-fixed", action="store_true")
    parser.add_argument("--_sandboxed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.port < 65535:
        parser.error("--port must be in 1..65534")
    args.binary, args.input_helper, args.grp = args.binary.resolve(), args.input_helper.resolve(), args.grp.resolve()
    if not all(path.is_file() for path in (args.binary, args.input_helper, args.grp)):
        parser.error("--binary, --input-helper, and --grp must name existing files")
    args.xr_server_binary = None  # Required by the reused CPU Run audit.
    reexec_sandbox(args)
    assert_gpu_devices_absent()
    assert_cpu_binary(args.binary)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="host-input-delta-", dir=args.work_dir.resolve()))
    diagnostic = run_case(args, root)
    result = {"passed": bool(args.expect_fixed and diagnostic["passed"]), "baseline_diagnostic": not args.expect_fixed,
              "diagnostic": diagnostic, "root": str(root), "binary_sha256": sha256(args.binary),
              "qualification": "Actual CPU listen-server host keyboard input and native EVENT_PROCESSINPUT rows; the host-alone producer proof requires a DISPLAYREST epoch and three no-draw ticks while Right remains held; no packet, pose, or input_t injection."}
    (root / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
