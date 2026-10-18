#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bounded CPU-native pipebomb slot-reuse probe.

This is deliberately a two-round experiment.  It drives the normal native
throw and hand-remote paths and records the server and client sprite indices.
It neither selects an allocator slot nor creates actor effects.  A completed
run therefore has one of two useful outcomes: it proves same-slot reuse, or
it records that this particular bounded run did not reuse the first slot.
Different slots leave reuse unqualified; they do not prove it impossible.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from smoke_native_levels import assert_cpu_binary, assert_gpu_devices_absent, sanitised_env
from smoke_pipebomb_native import (FIRE_BIT, FIRE_DELAY, HANDBOMB_WEAPON, HEAVYHBOMB,
                                   MODE_GAME, REMOTE_WEAPON, Run, bombs, explosions,
                                   join, latest_player, native_bomb, players, sha256, write_lab)


ROUNDS = 2
COOLDOWN_SECONDS = 1.5


def reexec_sandbox(args):
    """Use the same GPU-denied, SDL-dummy private-FIFO route as the native test."""
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


def settled_bomb(text, player, offset, event=None, index=None):
    """Return the native stationary remote bomb observed after a release."""
    candidates = native_bomb(bombs(text[offset:]), player, event)
    return next((row for row in reversed(candidates)
                 if row.get("tile") == HEAVYHBOMB and row.get("xvel") == 0 and
                 row.get("mode") == 2 and (index is None or row.get("index") == index)), None)


def explosion_count(text):
    values = explosions(text)
    return values[-1] if values else 0


def native_round(run, player, ordinal, expected_ammo):
    """Execute exactly one normal hold/release/remote cycle; no retry path exists."""
    server = run.observers["server"]
    client = run.observers["client"]
    server.wait(lambda text: latest_player(text, player) is not None and
                latest_player(text, player).get("weapon") == HANDBOMB_WEAPON and
                latest_player(text, player).get("ammo") == expected_ammo, timeout=10)

    hold_offset = len(server.text())
    run.key("client", 228, True)  # SDL_SCANCODE_RCTRL, the native fire binding.
    server.wait(lambda text: any(row.get("bits", 0) & FIRE_BIT and row.get("frame") == FIRE_DELAY
                                 for row in players(text[hold_offset:], player)),
                timeout=6)

    server_offset = len(server.text())
    client_offset = len(client.text())
    run.key("client", 228, False)
    server.wait(lambda text: bool(native_bomb(bombs(text[server_offset:]), player, 71)) and
                latest_player(text, player).get("ammo") == expected_ammo - 1 and
                latest_player(text, player).get("hbomb") == 1 and
                latest_player(text, player).get("weapon") == REMOTE_WEAPON, timeout=10)
    spawned = native_bomb(bombs(server.text()[server_offset:]), player, 71)
    server_index = spawned[-1]["index"]
    server.wait(lambda text: settled_bomb(text, player, server_offset, index=server_index) is not None,
                timeout=10)
    client.wait(lambda text: settled_bomb(text, player, client_offset, 65) is not None, timeout=12)
    server_bomb = settled_bomb(server.text(), player, server_offset, index=server_index)
    client_bomb = settled_bomb(client.text(), player, client_offset, 65)
    if server_bomb is None or client_bomb is None:
        raise RuntimeError(f"round {ordinal}: native pipebomb did not settle on both peers")

    server_explosions = explosion_count(server.text())
    client_explosions = explosion_count(client.text())
    run.press("client", 228, .28)
    server.wait(lambda text: latest_player(text, player) is not None and
                latest_player(text, player).get("hbomb") == 0 and
                explosion_count(text) == server_explosions + 1, timeout=10)
    client.wait(lambda text: explosion_count(text) == client_explosions + 1, timeout=12)
    server.wait(lambda text: latest_player(text, player) is not None and
                latest_player(text, player).get("weapon") == HANDBOMB_WEAPON and
                latest_player(text, player).get("ammo") == expected_ammo - 1, timeout=10)

    # This is release time for the ordinary actor lifecycle, not an allocation retry.
    server.pause(COOLDOWN_SECONDS)
    run.audit()
    return {
        "round": ordinal,
        "server_bomb_index": server_bomb["index"],
        "client_bomb_index": client_bomb["index"],
        "server_bomb": server_bomb,
        "client_bomb": client_bomb,
        "server_explosions_before": server_explosions,
        "server_explosions_after": explosion_count(server.text()),
        "client_explosions_before": client_explosions,
        "client_explosions_after": explosion_count(client.text()),
        "cooldown_seconds": COOLDOWN_SECONDS,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "input-helper", "grp", "work-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--port", type=int, default=24739)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--_sandboxed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be in 1..65535")
    args.binary, args.input_helper, args.grp = (
        args.binary.resolve(), args.input_helper.resolve(), args.grp.resolve())
    if not args.binary.is_file() or not args.input_helper.is_file() or not args.grp.is_file():
        parser.error("--binary, --input-helper, and --grp must name existing files")
    if args.expected_sha256 and sha256(args.binary) != args.expected_sha256:
        parser.error("--binary does not match --expected-sha256")
    reexec_sandbox(args)
    assert_gpu_devices_absent()
    assert_cpu_binary(args.binary)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="pipebomb-reuse-", dir=args.work_dir.resolve()))
    run = Run(args, root)
    phase = "setup"
    result = {"passed": False, "round_limit": ROUNDS,
              "binary_sha256": sha256(args.binary), "renderer": "CPU classic (no VR/SPS proof)",
              "checks": {}}
    try:
        for role in ("server", "client"):
            run.labs[role] = write_lab(root, role, args.grp)
        phase = "native dedicated server"
        server = run.launch("server", ["-dedicated", "-c1", "-m", "-port", str(args.port),
                                        "-map", "pipebomb.map"])
        server.wait(lambda text: "Multiplayer server initialized." in text, timeout=18)
        # The current CPU build can accept a client just before its user map
        # has collected spawn points; wait for the native map-ready log first.
        server.wait(lambda text: "User Map: /pipebomb.map" in text, timeout=8)
        phase = "native client join"
        player = join(run)
        server.wait(lambda text: latest_player(text, player) is not None and
                    latest_player(text, player).get("weapon") == HANDBOMB_WEAPON and
                    latest_player(text, player).get("ammo") == 6 and
                    latest_player(text, player).get("gm", 0) & MODE_GAME, timeout=12)
        run.audit()

        phase = "two fixed native pipebomb rounds"
        rounds = [native_round(run, player, ordinal, 7 - ordinal) for ordinal in range(1, ROUNDS + 1)]
        server_indices = [entry["server_bomb_index"] for entry in rounds]
        client_indices = [entry["client_bomb_index"] for entry in rounds]
        server_events = all(entry["server_explosions_after"] == entry["server_explosions_before"] + 1
                            for entry in rounds)
        client_events = all(entry["client_explosions_after"] == entry["client_explosions_before"] + 1
                            for entry in rounds)
        same_server_slot = len(set(server_indices)) == 1
        same_client_slot = len(set(client_indices)) == 1
        observable = len(rounds) == ROUNDS and server_events and client_events
        result.update(
            passed=observable and same_server_slot and same_client_slot and server_indices==client_indices,
            experiment_completed=observable,
            player=player,
            rounds=rounds,
            server_bomb_indices=server_indices,
            client_bomb_indices=client_indices,
            outcome="same_slot_reuse_proved" if same_server_slot and same_client_slot else
                    "same_slot_reuse_not_observed",
            checks={
                "exactly_two_bounded_native_rounds": len(rounds) == ROUNDS,
                "two_server_native_EXPLOSION2_events": server_events,
                "two_client_native_EXPLOSION2_events": client_events,
                "same_server_HEAVYHBOMB_sprite_index_reused": same_server_slot,
                "same_client_HEAVYHBOMB_sprite_index_reused": same_client_slot,
                "server_client_indices_match": server_indices == client_indices,
            })
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
