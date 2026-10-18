#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""CPU-only native regression for low-FPS P_UpdateAngles view centering.

The test runs an unmodified native game loop in a GPU-denied namespace.  Its
CON fixture supplies the one controlled starting horizon and delays one actual
view-update interval; all observed centering outcomes are produced by the
binary's P_UpdateAngles implementation.
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
from smoke_hand_shots import room
from smoke_multiplayer import CONFIG, stop
from smoke_native_levels import assert_cpu_binary, assert_gpu_devices_absent, sanitised_env


FIELD = re.compile(r"addlog vrcenter_(sample|horizon|return|totalclock)(?: \(player \d+\))? = (-?\d+)")
KEYS = ("sample", "horizon", "return", "totalclock")
FIX16_100 = 100 << 16
FIX16_140 = 140 << 16


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def samples(text):
    result, row = [], {}
    for key, value in FIELD.findall(text):
        if key == "sample":
            row = {}
        row[key] = int(value)
        if key == "totalclock" and all(name in row for name in KEYS):
            result.append(row)
    return result


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
    command = [bwrap, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--unshare-pid",
               "--bind", str(work), str(work), "--chdir", str(Path.cwd()), "--clearenv"]
    for key in ("PATH", "LANG", "LC_ALL", "TZ"):
        if key in safe:
            command += ["--setenv", key, safe[key]]
    command += [sys.executable, str(Path(__file__).resolve()), *child_args]
    os.execvpe(bwrap, command, safe)


def write_lab(root, grp, spin, start_horizon):
    lab = root / "game"
    lab.mkdir()
    (lab / "DUKE3D.GRP").symlink_to(grp)
    (lab / "eduke32.cfg").write_text(CONFIG.replace("ScreenBPP = 32", "ScreenBPP = 8"))
    (lab / "autoexec.cfg").write_text("r_maxfps 30\n")
    fixture = (HERE / "fixtures" / "view_center_test.con").read_text()
    fixture = fixture.replace("15000000", str(spin))
    fixture = fixture.replace("9175040", str(start_horizon << 16))
    (lab / "view_center_test.con").write_text(fixture)
    (lab / "view-center.map").write_bytes(room())
    return lab


def run_binary(args, binary, label):
    root = Path(tempfile.mkdtemp(prefix=f"view-center-{label}-", dir=args.work_dir.resolve()))
    lab = write_lab(root, args.grp, args.spin, args.start_horizon)
    log_path = lab / "game.log"
    env = sanitised_env()
    process = None
    result = {"label": label, "binary_sha256": sha256(binary), "passed": False}
    try:
        log = log_path.open("w")
        process = subprocess.Popen([str(binary), "-usecwd", "-nosetup", "-noautoload", "-nologo", "-ns", "-nm",
                                    "-map", "view-center.map", "-x", "view_center_test.con"], cwd=lab, env=env,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        observer = Observer(process, log_path)
        observed_at = []
        seen = 0
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            assert_gpu_devices_absent()
            rows = samples(observer.text())
            if len(rows) > seen:
                observed_at.extend(time.monotonic() for _ in rows[seen:])
                seen = len(rows)
            if len(rows) >= args.samples:
                break
            time.sleep(.01)
        rows = samples(observer.text())
        if len(rows) < args.samples:
            raise RuntimeError(f"only observed {len(rows)} native angle samples")
        interval = observed_at[1] - observed_at[0] if len(observed_at) >= 2 else 0
        delayed = rows[1]
        start = rows[0]
        # The baseline must cross level after a delayed update; the corrected
        # binary must converge. Native clock ticks corroborate observer timing.
        result.update(samples=rows[:12], observed_log_gap_seconds=interval,
                      starting_horizon=start["horizon"], delayed_horizon=delayed["horizon"],
                      delayed_return_to_center=delayed["return"],
                      actual_totalclock_delta=delayed["totalclock"] - start["totalclock"],
                      minimum_log_gap_observed=interval >= args.min_interval,
                      minimum_native_clock_gap_observed=(delayed["totalclock"] - start["totalclock"]
                                                         >= max(1, int(args.min_interval * 120))),
                      setup_is_exactly_controlled_horizon=start["horizon"] == (args.start_horizon << 16))
        result["passed"] = (result["minimum_log_gap_observed"] and result["minimum_native_clock_gap_observed"]
                            and result["setup_is_exactly_controlled_horizon"])
    except Exception as error:
        result["error"] = str(error)
    finally:
        if process is not None:
            stop(process)
        if 'log' in locals():
            log.close()
        (root / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def converges_without_crossing(rows, start_horizon):
    values = [row["horizon"] for row in rows]
    if not values or values[-1] != FIX16_100:
        return False
    if start_horizon > 100:
        return all(FIX16_100 <= later <= earlier for earlier, later in zip(values, values[1:]))
    return all(FIX16_100 >= later >= earlier for earlier, later in zip(values, values[1:]))


def comparison_checks(corrected, baseline, start_horizon, normal):
    initial_above = start_horizon > 100
    checks = {
        "both_runs_reached_controlled_native_setup": corrected.get("passed", False) and baseline.get("passed", False),
        "corrected_trace_converges_without_crossing": converges_without_crossing(corrected.get("samples", []), start_horizon),
    }
    if normal:
        checks["baseline_normal_trace_remains_on_starting_side"] = (
            converges_without_crossing(baseline.get("samples", []), start_horizon))
    else:
        baseline_horizon = baseline.get("delayed_horizon", FIX16_100)
        checks["baseline_expected_negative_crosses_past_level"] = (
            baseline_horizon < FIX16_100 if initial_above else baseline_horizon > FIX16_100)
        checks["corrected_delayed_update_converges_to_level"] = corrected.get("delayed_horizon") == FIX16_100
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path, help="corrected CPU binary")
    parser.add_argument("--reference-binary", type=Path, help="baseline CPU binary expected to fail centering")
    parser.add_argument("--grp", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--input-helper", type=Path, help="accepted for shared CPU-runner CLI compatibility; unused")
    parser.add_argument("--spin", type=int, help="default: 1 normal, otherwise 15000000")
    parser.add_argument("--start-horizon", type=int, default=140,
                        help="controlled integer horizon, on either side of level 100")
    parser.add_argument("--samples", type=int,
                        help="native POSTUPDATEANGLES samples to retain (default: 12 normal, otherwise 4)")
    parser.add_argument("--normal", action="store_true", help="validate a normal-rate, non-delayed trace")
    parser.add_argument("--min-interval", type=float, help="default: .015 normal, otherwise .05 seconds")
    parser.add_argument("--timeout", type=float, default=18)
    parser.add_argument("--_sandboxed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.spin is None:
        args.spin = 1 if args.normal else 15000000
    if args.min_interval is None:
        args.min_interval = .015 if args.normal else .05
    if args.samples is None:
        args.samples = 12 if args.normal else 4
    if args.spin <= 0 or args.timeout <= 0 or args.min_interval <= 0 or args.samples < 2:
        parser.error("--spin, --timeout, --min-interval must be positive and --samples must be at least two")
    if not 1 <= args.start_horizon <= 199 or args.start_horizon == 100:
        parser.error("--start-horizon must be 1..199 and not level 100")
    args.binary, args.grp = args.binary.resolve(), args.grp.resolve()
    if args.reference_binary:
        args.reference_binary = args.reference_binary.resolve()
    if args.input_helper:
        args.input_helper = args.input_helper.resolve()
    for path in (args.binary, args.grp, args.reference_binary, args.input_helper):
        if path is not None and not path.is_file():
            parser.error(f"missing required file: {path}")
    reexec_sandbox(args)
    assert_gpu_devices_absent()
    assert_cpu_binary(args.binary)
    if args.reference_binary:
        assert_cpu_binary(args.reference_binary)
    args.work_dir.mkdir(parents=True, exist_ok=True)

    corrected = run_binary(args, args.binary, "corrected")
    checks = {"controlled_native_setup_and_interval": corrected["passed"],
              "corrected_trace_converges_without_crossing": converges_without_crossing(
                  corrected.get("samples", []), args.start_horizon)}
    if not args.normal:
        checks["corrected_delayed_update_converges_to_level"] = corrected.get("delayed_horizon") == FIX16_100
    result = {"passed": all(checks.values()), "checks": checks,
              "renderer": "CPU classic (no VR/SPS proof)", "corrected": corrected}
    if args.reference_binary:
        baseline = run_binary(args, args.reference_binary, "baseline")
        checks = comparison_checks(corrected, baseline, args.start_horizon, args.normal)
        result.update(baseline=baseline, checks=checks, passed=all(checks.values()))
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
