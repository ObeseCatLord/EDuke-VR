#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run one OpenXR application or harness in a disposable, CPU-only Monado lab.

Every filesystem argument, including CHILD_COMMAND and any path-valued child
arguments, must be absolute.  ``--work-dir`` is the only host directory made
writable by Bubblewrap; use a new ignored ``work/software-xr-lab-*`` directory.

Example (run from a private PTY):
  tools/vr/software_xr_lab.py --deps "$PWD/work/software-xr/deps" \\
    --work-dir "$PWD/work/software-xr-lab-smoke" -- \\
    "$PWD/source/vr/xr_smoke" --frames 3 --timeout 10 \\
    --output "$PWD/work/software-xr-lab-smoke/diagnostic"
"""

import argparse
import json
import os
import pty
import re
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterable


EXPECTED_SHA256 = "c099e085f778b3183b22a3ab81b7200dd013855c4bcbc7bb5c5189ed045311bf"
EXPECTED_VERSION = "1:26.2.3-1"
DISPLAY = ":105"
XDG_RUNTIME = Path("/tmp/xr")  # Monado IPC paths reject longer runtime roots.


class LabError(RuntimeError):
    pass


@dataclass
class OwnedProcess:
    name: str
    process: subprocess.Popen[object]
    log: IO[str]


def absolute_path(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise LabError(f"{label} must be an absolute path: {value!r}")
    return path.resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deps", required=True, help="absolute extracted vulkan-swrast dependency directory")
    parser.add_argument("--work-dir", required=True, help="absolute, owned lab output directory")
    parser.add_argument("--remote-port", type=int, default=49777)
    parser.add_argument("--_in-lab", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("child", nargs=argparse.REMAINDER, metavar="CHILD_COMMAND")
    args = parser.parse_args()
    if not args.child or args.child[0] != "--":
        parser.error("a child command is required after --")
    args.child = args.child[1:]
    if not args.child:
        parser.error("a child command is required after --")
    if not 1 <= args.remote_port <= 65535:
        parser.error("--remote-port must be in 1..65535")
    return args


def verify_dependencies(deps: Path) -> Path:
    manifest = deps.parent / "package.json"
    try:
        package = json.loads(manifest.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise LabError(f"cannot read dependency manifest {manifest}: {exc}") from exc
    if package.get("sha256") != EXPECTED_SHA256 or package.get("version") != EXPECTED_VERSION:
        raise LabError("dependency manifest is not the verified vulkan-swrast 1:26.2.3-1 package")
    pkginfo = deps / ".PKGINFO"
    if not pkginfo.is_file() or f"pkgver = {EXPECTED_VERSION}" not in pkginfo.read_text(errors="replace"):
        raise LabError("extracted dependency version does not match its verified manifest")
    icds = list((deps / "usr/share/vulkan/icd.d").glob("*lvp*.json"))
    library = deps / "usr/lib/libvulkan_lvp.so"
    if len(icds) != 1 or not library.is_file():
        raise LabError("expected exactly one extracted LVP ICD and libvulkan_lvp.so")
    try:
        icd = json.loads(icds[0].read_text())
    except json.JSONDecodeError as exc:
        raise LabError(f"invalid LVP ICD file: {exc}") from exc
    if icd.get("ICD", {}).get("library_path") != "libvulkan_lvp.so":
        raise LabError("LVP ICD does not name the pinned software library")
    return icds[0]


def reexec_sandbox(args: argparse.Namespace, script: Path) -> None:
    work_dir = absolute_path(args.work_dir, "--work-dir")
    deps = absolute_path(args.deps, "--deps")
    command = absolute_path(args.child[0], "CHILD_COMMAND")
    if not deps.is_dir() or not command.is_file():
        raise LabError("--deps must exist and CHILD_COMMAND must name an existing regular file")
    work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not work_dir.is_dir():
        raise LabError("--work-dir is not a directory")
    if any(work_dir.iterdir()):
        raise LabError("--work-dir must be empty; preserve prior results and use a new directory")
    if work_dir.stat().st_uid != os.getuid() or work_dir.stat().st_mode & 0o077:
        raise LabError("--work-dir must be owned by this user with mode 0700")
    # The re-exec keeps all repository inputs read-only from the initial bind.
    command_line = [
        "bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
        "--unshare-pid", "--unshare-net", "--die-with-parent",
        "--bind", str(work_dir), str(work_dir), "--tmpfs", "/tmp", "--tmpfs", "/run/user",
        "--chdir", str(work_dir), "--clearenv",
    ]
    for name in ("PATH", "LANG", "LC_ALL", "HOME"):
        if name in os.environ:
            command_line.extend(("--setenv", name, os.environ[name]))
    command_line.extend((sys.executable, str(script), "--_in-lab", "--deps", str(deps),
                         "--work-dir", str(work_dir), "--remote-port", str(args.remote_port), "--", str(command)))
    command_line.extend(args.child[1:])
    os.execvp("bwrap", command_line)


def descendants(roots: Iterable[int]) -> set[int]:
    parent_of: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            # Field two is parenthesized comm and may contain spaces; rsplit is safe here.
            fields = (entry / "stat").read_text().rsplit(") ", 1)[1].split()
            parent_of[int(entry.name)] = int(fields[1])
        except (FileNotFoundError, IndexError, ValueError):
            continue
    found = set(roots)
    changed = True
    while changed:
        changed = False
        for pid, parent in parent_of.items():
            if parent in found and pid not in found:
                found.add(pid)
                changed = True
    return found


def audit_processes(processes: list[OwnedProcess]) -> None:
    if Path("/dev/dri").exists() or any(Path("/dev").glob("nvidia*")):
        raise LabError("GPU device nodes are visible inside the private namespace")
    roots = [item.process.pid for item in processes if item.process.poll() is None]
    forbidden = ("libnvidia", "libvulkan_intel", "libvulkan_radeon", "libvulkan_nouveau",
                 "libvulkan_amd", "libvulkan_dzn", "libanv", "libradv")
    for pid in descendants(roots):
        proc = Path("/proc") / str(pid)
        try:
            maps = (proc / "maps").read_text(errors="replace").lower()
        except FileNotFoundError:
            continue
        if any(token in maps for token in forbidden):
            raise LabError(f"pid {pid} mapped a hardware GPU driver")
        try:
            fds = list((proc / "fd").iterdir())
        except FileNotFoundError:
            continue
        for fd in fds:
            try:
                target = os.readlink(fd)
            except FileNotFoundError:
                continue
            if "/dev/dri" in target or "/dev/nvidia" in target:
                raise LabError(f"pid {pid} opened a hardware GPU device: {target}")


def wait_for(process: OwnedProcess, predicate, timeout: float, processes: list[OwnedProcess], label: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.process.poll() is not None:
            raise LabError(f"{label} exited before readiness (code {process.process.returncode})")
        if predicate():
            return
        audit_processes(processes)
        time.sleep(0.1)
    raise LabError(f"{label} readiness timed out; it was not restarted")


def close_owned(processes: list[OwnedProcess], pty_fds: list[int]) -> bool:
    for owned in reversed(processes):
        if owned.process.poll() is None:
            try:
                os.killpg(owned.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 4
    for owned in reversed(processes):
        if owned.process.poll() is None:
            try:
                owned.process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(owned.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    owned.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
        owned.log.close()
    for fd in pty_fds:
        os.close(fd)
    return all(owned.process.poll() is not None for owned in processes)


def find_validation_lines(text: str) -> list[str]:
    # VALID_DEBUG lifecycle messages prove the layer ran; they are not warnings.
    return [line for line in text.splitlines()
            if re.search(r"VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)", line, re.I)]


def run_lab(args: argparse.Namespace) -> int:
    work_dir = absolute_path(args.work_dir, "--work-dir")
    deps = absolute_path(args.deps, "--deps")
    child = [str(absolute_path(args.child[0], "CHILD_COMMAND")), *args.child[1:]]
    result_path = work_dir / "result.json"
    result: dict[str, object] = {
        "exit": "failed", "code": None, "gpu_denied": False, "cleanup": False,
        "source": child, "remote_port": args.remote_port, "work_dir": str(work_dir),
        "core_validation": {"available": False, "requested": False, "clean": None, "findings": []},
    }
    processes: list[OwnedProcess] = []
    pty_fds: list[int] = []
    stage = "dependency verification"
    child_code: int | None = None
    try:
        icd = verify_dependencies(deps)
        if Path("/dev/dri").exists() or any(Path("/dev").glob("nvidia*")):
            raise LabError("GPU devices are visible before any process starts")
        result["gpu_denied"] = True
        runtime = XDG_RUNTIME
        config = work_dir / "config"
        cache = work_dir / "cache"
        for directory in (runtime, config, cache, config / "monado"):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        (config / "monado/config_v0.json").write_text(json.dumps({
            "active": "remote", "remote": {"version": 0, "port": args.remote_port, "view_count": 2},
        }) + "\n")
        layer = Path("/usr/share/openxr/1/api_layers/explicit.d/XrApiLayer_core_validation.json")
        layer_available = layer.is_file()
        result["core_validation"] = {"available": layer_available, "requested": layer_available,
                                     "clean": None, "findings": []}
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "DISPLAY": DISPLAY,
            "WAYLAND_DISPLAY": "software-xr-lab-no-wayland", "XDG_SESSION_TYPE": "x11",
            "SDL_VIDEODRIVER": "x11", "SDL_AUDIODRIVER": "dummy", "XDG_RUNTIME_DIR": str(runtime),
            "XDG_CONFIG_HOME": str(config), "XDG_CACHE_HOME": str(cache),
            "LIBGL_ALWAYS_SOFTWARE": "1", "GALLIUM_DRIVER": "llvmpipe", "__GLX_VENDOR_LIBRARY_NAME": "mesa",
            "__EGL_VENDOR_LIBRARY_FILENAMES": "/usr/share/glvnd/egl_vendor.d/50_mesa.json",
            "VK_ICD_FILENAMES": str(icd), "VK_DRIVER_FILES": str(icd), "VK_LOADER_LAYERS_DISABLE": "~implicit~",
            "LD_LIBRARY_PATH": str(deps / "usr/lib"), "XRT_COMPOSITOR_NULL": "1", "SIMULATED_ENABLE": "1",
            "XR_RUNTIME_JSON": "/usr/share/openxr/1/openxr_monado.json", "LP_NUM_THREADS": "4",
            "OMP_NUM_THREADS": "4", "MESA_SHADER_CACHE_DISABLE": "true",
            "EDUKE32_TEST_PRIVATE_WINDOW": "1",
        }
        # Monado requires HOME to exist. Preserve its real value; XDG paths
        # redirect runtime writes and the host home remains read-only.
        if "HOME" in os.environ:
            env["HOME"] = os.environ["HOME"]
        if layer_available:
            env.update({"XR_API_LAYER_PATH": str(layer.parent), "XR_ENABLE_API_LAYERS": "XR_APILAYER_LUNARG_core_validation"})

        def launch(name: str, command: list[str], stdin: object = None) -> OwnedProcess:
            log = (work_dir / f"{name}.log").open("w", encoding="utf-8")
            owned = OwnedProcess(name, subprocess.Popen(["nice", "-n", "10", *command], cwd=work_dir,
                                 stdin=stdin, stdout=log, stderr=subprocess.STDOUT, env=env,
                                 start_new_session=True), log)
            processes.append(owned)
            return owned

        stage = "private Xvfb"
        Path("/tmp/.X11-unix").mkdir(mode=0o1777, exist_ok=True)
        xvfb = launch("xvfb", ["Xvfb", DISPLAY, "-screen", "0", "640x480x24", "-nolisten", "tcp", "-ac"])
        wait_for(xvfb, lambda: Path("/tmp/.X11-unix/X105").exists(), 8, processes, "Xvfb")

        stage = "private Monado"
        monado_stdin: object
        if sys.stdin.isatty():
            monado_stdin = sys.stdin
        else:
            master, slave = pty.openpty()
            pty_fds.extend((master, slave))
            monado_stdin = slave
        monado = launch("monado", ["monado-service"], monado_stdin)
        wait_for(monado, lambda: any(stat.S_ISSOCK(path.stat().st_mode) for path in runtime.iterdir()), 15,
                 processes, "Monado")

        stage = "child diagnostic"
        smoke = launch("child", child)
        deadline = time.monotonic() + 60
        while smoke.process.poll() is None and time.monotonic() < deadline:
            audit_processes(processes)
            time.sleep(0.1)
        if smoke.process.poll() is None:
            raise LabError("child timed out after 60 seconds; it was not restarted")
        child_code = smoke.process.returncode
        audit_processes(processes)
        # Harnesses write game logs in child directories. A fresh work directory
        # prevents old validation output from being mistaken for this run.
        child_logs = [(path, path.read_text(errors="replace")) for path in work_dir.rglob("*.log")
                      if path not in (work_dir / "monado.log", work_dir / "xvfb.log")]
        findings = [f"{path.relative_to(work_dir)}: {line}" for path, contents in child_logs
                    for line in find_validation_lines(contents)]
        layer_observed = any("VUID-CoreValidation-Initialize" in contents
                             or "Core Validation output type:" in contents for _, contents in child_logs)
        result["main_log_warnings"] = findings
        result["core_validation"] = {"available": layer_available, "requested": layer_available,
                                     "observed": layer_observed,
                                     "clean": (not findings and layer_observed) if layer_available else None,
                                     "findings": findings}
        monado_log = (work_dir / "monado.log").read_text(errors="replace")
        lvp_cpu_device = "name: llvmpipe" in monado_log and "deviceType: VK_PHYSICAL_DEVICE_TYPE_CPU" in monado_log
        result["lvp_cpu_device"] = lvp_cpu_device
        result["monado_teardown_nonexistent_space_warning"] = "destroy non-existent space" in monado_log
        result["gpu_denied"] = True
        result["code"] = child_code
        result["exit"] = ("passed" if child_code == 0 and lvp_cpu_device and not findings
                          and (not layer_available or layer_observed) else "failed")
    except Exception as exc:  # Result files are the diagnostic artifact for failures too.
        result.update({"stage": stage, "error": str(exc), "code": child_code})
    finally:
        result["cleanup"] = close_owned(processes, pty_fds)
        if (work_dir / "monado.log").is_file():
            result["monado_teardown_nonexistent_space_warning"] = "destroy non-existent space" in (
                work_dir / "monado.log").read_text(errors="replace")
        result["process_codes"] = {owned.name: owned.process.returncode for owned in processes}
        result["qualification"] = ("private PID/network/device namespace; Xvfb and Monado are owned; "
                                    "Mesa llvmpipe plus the verified extracted LVP ICD only")
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["exit"] == "passed" and result["cleanup"] and result["gpu_denied"] else (child_code or 1)


def main() -> int:
    args = parse_args()
    script = Path(__file__).resolve()
    if not args._in_lab:
        reexec_sandbox(args, script)
        raise AssertionError("unreachable")
    return run_lab(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LabError as exc:
        print(f"software_xr_lab: {exc}", file=sys.stderr)
        raise SystemExit(2)
