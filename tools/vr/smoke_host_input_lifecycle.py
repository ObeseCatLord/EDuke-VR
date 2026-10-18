#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Private CPU-native listen-host pause and map-reset input regression.

The listen host is the sole SDL FIFO owner.  Its ordinary network receiver
observes host player zero over the real native connection.  The fixture only
logs native input, pause, and level state; it never injects game state.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from smoke_actions_multiplayer import client_player_index
from smoke_input_deltas_native import RIGHT_SCAN, Run, bounded, sha256, write_lab
from smoke_native_levels import assert_cpu_binary, assert_gpu_devices_absent, sanitised_env


SYNC = "Multiplayer client level synchronization complete."
PAUSE_SCAN = 72  # SDL_SCANCODE_PAUSE
CHANGELEVEL_SCAN = 62  # SDL_SCANCODE_F5
INPUT_FIELD = re.compile(r"addlog vrhostlife_(tick|draw|q16avel|q16horz|q16ang|pause|volume|level)\b[^=\n]*= (-?\d+)")
DISPLAY_FIELD = re.compile(r"addlog vrhostlife_display(?:_(pause|volume|level))?\b[^=\n]*= (-?\d+)")
INPUT_KEYS = ("tick", "draw", "q16avel", "q16horz", "q16ang", "pause", "volume", "level")
DISPLAY_KEYS = ("display", "pause", "volume", "level")


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


def parsed_rows(text, pattern, keys, terminal, start):
    result, row = [], {}
    for key, value in pattern.findall(text):
        key = key or "display"
        if key == start:
            row = {}
        row[key] = int(value)
        if key == terminal and all(name in row for name in keys):
            result.append(row)
            row = {}
    return result


def inputs(text):
    return parsed_rows(text, INPUT_FIELD, INPUT_KEYS, "level", "tick")


def displays(text):
    return parsed_rows(text, DISPLAY_FIELD, DISPLAY_KEYS, "level", "display")


def zero_angles(rows):
    return bool(rows) and all(row["q16avel"] == 0 and row["q16horz"] == 0 for row in rows)


def three_distinct_ticks(rows):
    return len({row["tick"] for row in rows}) >= 3


def three_active_ticks(rows):
    return len({row["tick"] for row in rows if row["q16avel"] != 0 or row["q16horz"] != 0}) >= 3


def wait_for(observer, offset, predicate, description, timeout=14):
    observer.wait(lambda text: predicate(text[offset:]), timeout=timeout)
    text = observer.text()[offset:]
    if not predicate(text):
        raise RuntimeError(description + ": observation disappeared")
    return text


def wait_input(observer, offset, predicate, description, timeout=14):
    return inputs(wait_for(observer, offset, lambda text: predicate(inputs(text)), description, timeout))


def native_press(run, scan, hold=.12):
    run.key(scan, True)
    time.sleep(hold)
    run.key(scan, False)


def level_rows(text, volume, level):
    return [row for row in inputs(text) if row["volume"] == volume and row["level"] == level]


def unpaused_rows(text):
    return [row for row in inputs(text) if row["pause"] == 0]


def paused_display(text):
    return any(row["pause"] != 0 for row in displays(text))


def unpaused_display(text):
    return any(row["pause"] == 0 for row in displays(text))


def run_case(args, root):
    # Reuse the input-delta Run: its role called client is this test's actual
    # listen host and therefore is the only process supplied an owned FIFO.
    run = Run(args, root, args.binary)
    result = {"passed": False, "phase": "setup"}
    try:
        host_lab = write_lab(root, "host", args.grp)
        receiver_lab = write_lab(root, "receiver", args.grp)
        fixture = HERE / "fixtures" / "host_input_lifecycle.con"
        for lab in (host_lab, receiver_lab):
            shutil.copyfile(fixture, lab / fixture.name)
            with (lab / "input_delta_test.con").open("a") as target:
                target.write("\ninclude host_input_lifecycle.con\n")
        # F5 goes through the game\'s ordinary OSD changelevel handler.  The
        # host owns this bind and no test path writes pause/map userdefs.
        (host_lab / "autoexec.cfg").write_text(
            'r_maxfps 30\nunbind Right\nbind Right "gamefunc_Turn_Right"\n'
            'bind F5 "changelevel 1 2"\n')
        run.labs = {"client": host_lab, "receiver": receiver_lab}

        result["phase"] = "CPU listen host"
        host = run.launch("client", ["-server", "-c3", "-m", "-v1", "-l1", "-port", str(args.port)])
        host.wait(lambda text: "Multiplayer server initialized." in text, timeout=18)
        result["phase"] = "ordinary receiver joins"
        receiver = run.launch("receiver", ["-connect", f"127.0.0.1:{args.port}"])
        receiver.wait(lambda text: SYNC in text, timeout=25)
        receiver.wait(lambda text: client_player_index(text) == 1, timeout=14)
        receiver_index = client_player_index(receiver.text())
        if receiver_index != 1:
            raise RuntimeError(f"ordinary receiver native index is {receiver_index}, expected 1")
        for observer, role in ((host, "host"), (receiver, "receiver")):
            wait_input(observer, 0, lambda values: three_distinct_ticks(level_rows_from(values, 0, 0)),
                       role + " did not expose three initial host0 native samples")
        run.audit()

        result["phase"] = "real Pause while host right is held"
        start = {"host": len(host.text()), "receiver": len(receiver.text())}
        run.key(RIGHT_SCAN, True)
        for observer, role in ((host, "host"), (receiver, "receiver")):
            wait_input(observer, start[role], three_active_ticks,
                       role + " did not observe three held-host Right ticks")
        pause_offsets = {"host": len(host.text()), "receiver": len(receiver.text())}
        native_press(run, PAUSE_SCAN)
        for observer, role in ((host, "host"), (receiver, "receiver")):
            wait_for(observer, pause_offsets[role], paused_display,
                     role + " did not observe native pause_on through EVENT_DISPLAYREST")
        # The release is deliberately delivered during native pause, after its
        # boundary has been observed.  There is no setuserdef/gameflag path.
        run.key(RIGHT_SCAN, False)
        for observer, role in ((host, "host"), (receiver, "receiver")):
            wait_for(observer, pause_offsets[role], paused_display,
                     role + " lost its observed paused display boundary")
        unpause_offsets = {"host": len(host.text()), "receiver": len(receiver.text())}
        native_press(run, PAUSE_SCAN)
        post_pause = {}
        for observer, role in ((host, "host"), (receiver, "receiver")):
            wait_for(observer, unpause_offsets[role], unpaused_display,
                     role + " did not observe native unpause through EVENT_DISPLAYREST")
            post_pause[role] = wait_for(
                observer, unpause_offsets[role],
                lambda text: (three_distinct_ticks(unpaused_rows(text)) and
                              zero_angles(unpaused_rows(text))),
                role + " replayed angular host0 input after native unpause")

        result["phase"] = "F5 native changelevel resets released host input"
        turn_offsets = {"host": len(host.text()), "receiver": len(receiver.text())}
        run.key(RIGHT_SCAN, True)
        for observer, role in ((host, "host"), (receiver, "receiver")):
            wait_input(observer, turn_offsets[role], three_active_ticks,
                       role + " did not observe three fresh host Right ticks before F5")
        map_offsets = {"host": len(host.text()), "receiver": len(receiver.text())}
        # Keep the release and real F5 adjacent in the FIFO sequence: this is
        # the lifecycle edge under test, rather than a timed idle period.
        run.key(RIGHT_SCAN, False)
        native_press(run, CHANGELEVEL_SCAN)
        new_map = {}
        for observer, role in ((host, "host"), (receiver, "receiver")):
            segment = wait_for(
                observer, map_offsets[role],
                lambda text: three_distinct_ticks(level_rows(text, 0, 1)),
                role + " did not expose three host0 samples in native level 0,1", timeout=24)
            rows = level_rows(segment, 0, 1)
            if not zero_angles(rows):
                raise RuntimeError(role + " observed nonzero host0 angular input after native level 0,1 began")
            new_map[role] = bounded(rows)
        run.audit()
        checks = {
            "actual_listen_host_owns_real_sdl_fifo": True,
            "ordinary_receiver_has_unique_native_index_1": receiver_index == 1,
            "host_and_receiver_observe_held_host_turn_before_pause": all(
                three_active_ticks(inputs((host if role == "host" else receiver).text()[start[role]:]))
                for role in ("host", "receiver")),
            "real_pause_and_unpause_boundaries_observed_in_displayrest": all(
                paused_display((host if role == "host" else receiver).text()[pause_offsets[role]:]) and
                unpaused_display((host if role == "host" else receiver).text()[unpause_offsets[role]:])
                for role in ("host", "receiver")),
            "fresh_post_unpause_host0_angular_input_zero_on_host_and_receiver": all(
                three_distinct_ticks(unpaused_rows(post_pause[role])) and zero_angles(unpaused_rows(post_pause[role]))
                for role in ("host", "receiver")),
            "host_and_receiver_observe_fresh_host_turn_immediately_before_F5": all(
                three_active_ticks(inputs((host if role == "host" else receiver).text()[turn_offsets[role]:]))
                for role in ("host", "receiver")),
            "both_observe_native_level_0_1_and_all_observed_host0_angles_zero": all(zero_angles(new_map[role]) for role in ("host", "receiver")),
            "no_gpu_libraries_or_devices": True,
        }
        result.update(passed=all(checks.values()), phase="complete", checks=checks,
                      receiver_index=receiver_index,
                      post_unpause={role: bounded(unpaused_rows(values)) for role, values in post_pause.items()},
                      post_unpause_first={role: unpaused_rows(values)[0] for role, values in post_pause.items()},
                      new_map_host0_rows=new_map)
    except Exception as error:
        result.update(error=str(error))
        for role in ("client", "receiver"):
            if role in run.labs:
                log = run.labs[role] / "game.log"
                if log.exists():
                    result[role + "_input_rows"] = bounded(inputs(log.read_text(errors="replace")))
                    result[role + "_display_rows"] = bounded(displays(log.read_text(errors="replace")))
    finally:
        run.close()
        result["cleanup"] = all(process.poll() is not None for process in run.processes.values())
        (root / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def level_rows_from(values, volume, level):
    return [row for row in values if row["volume"] == volume and row["level"] == level]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "input-helper", "grp", "work-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--port", type=int, default=24821)
    parser.add_argument("--_sandboxed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.port < 65535:
        parser.error("--port must be in 1..65534")
    args.binary, args.input_helper, args.grp = (args.binary.resolve(), args.input_helper.resolve(), args.grp.resolve())
    if not all(path.is_file() for path in (args.binary, args.input_helper, args.grp)):
        parser.error("--binary, --input-helper, and --grp must name existing files")
    args.xr_server_binary = None  # Required by the reused CPU Run audit.
    reexec_sandbox(args)
    assert_gpu_devices_absent()
    assert_cpu_binary(args.binary)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="host-input-lifecycle-", dir=args.work_dir.resolve()))
    result = run_case(args, root)
    result.update(evidence_root=str(root), binary_sha256=sha256(args.binary),
                  qualification=("Private CPU-only bwrap listen host and ordinary receiver; real SDL Pause/F5 "
                                 "events only, with observation-only CON input/pause/level rows."))
    (root / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
