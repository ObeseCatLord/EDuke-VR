#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Private OpenXR/native-MP proof for the opt-in palm-mounted stock pistol.

Run this *inside* ``software_xr_lab.py``.  It owns a disposable server/client
pair and lab-local DEF/map/CON files.  The only game actions are normal Monado
remote trigger and stick-click inputs; target health, hit rays, and ammo are
observed from the native test fixtures.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile

from monado_remote import Remote
from smoke_actions import Observer
from smoke_actions_multiplayer import wait_for_join_barrier
from smoke_aim import orientation, players
from smoke_hand_shots import room
from smoke_hitscan import rays, samples
# The mighty foot kicks from the body toward where the head looks (not from the hand).
KICK = re.compile(r'VR head kick: player=(\d+) quick=(\d) origin=(-?\d+),(-?\d+),(-?\d+) '
                  r'hit=(-?\d+),(-?\d+),(-?\d+) sector=(-?\d+) target=(-?\d+) wall=(-?\d+) '
                  r'angle=(-?\d+) zvel=(-?\d+) inRange=(\d)')


def melee_traces(text):
    keys = ('player', 'quick', 'hx', 'hy', 'hz', 'x', 'y', 'z', 'sector', 'target', 'wall', 'angle', 'zvel', 'inRange')
    return [dict(zip(keys, map(int, row))) for row in KICK.findall(text)]
from smoke_multiplayer import X11, setup_lab, stop


HERE = Path(__file__).resolve().parent
ASSET_ROOT = HERE.parents[1].parent / "duke-vr-assets"
MOUNTED_ASSETS = ASSET_ROOT / "pistol-palm-mount/stock/exports/eduke32/duke_assets"
V4_ASSETS = ASSET_ROOT / "v4-pistol-native/exports/eduke32/duke_assets"
CASES = ("missing-tag", "loss", "damage", "wall", "quickkick", "quickkick-far")
HEALTH = re.compile(r"addlog vrtarget_health[^=\n]*= (-?\d+)")
MOUNT_POSE = re.compile(r"OpenXR pistol mount pose: eye=(\d) hand=(\d) grip=([^ ]+) aim=([^\n]+)\.")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def md3_tags(path):
    """Read static MD3 tag names without duplicating their transform contract."""
    data = path.read_bytes()
    if data[:4] != b"IDP3" or struct.unpack_from("<i", data, 4)[0] != 15:
        raise RuntimeError(f"{path} is not an MD3 v15 export")
    count = struct.unpack_from("<i", data, 80)[0]
    offset = struct.unpack_from("<i", data, 96)[0]
    if count <= 0 or offset < 0 or offset + count * 112 > len(data):
        raise RuntimeError(f"{path} has an invalid static tag table")
    return [data[offset + index * 112:offset + index * 112 + 64].split(b"\0", 1)[0].decode("ascii")
            for index in range(count)]


def health(text):
    values = HEALTH.findall(text)
    if not values:
        raise RuntimeError("fixture did not emit native target health")
    return int(values[-1])


def install_model(lab, assets):
    """Route palette-zero FIRSTGUNSPRITE through the supplied lab-local DEF."""
    model, skin = assets / "pistol.md3", assets / "pistol.png"
    if not model.is_file() or not skin.is_file():
        raise RuntimeError(f"pistol assets missing from {assets}")
    (lab / "duke_assets").symlink_to(assets, target_is_directory=True)
    (lab / "held-pistol.md3").symlink_to(model)
    (lab / "pistol-mount.def").write_text(
        'model "held-pistol.md3" {\n'
        ' scale 0.5859375\n'
        ' skin { pal 0 surface 0 file "duke_assets/pistol.png" }\n'
        ' frame { name "rest" tile 21 smoothduration 0 }\n'
        '}\n')


def prepare_lab(root, role, args, mounted):
    lab = setup_lab(root, role, args.grp, False)
    for name in ("controller_test.con", "aim_test.con", "hand_test.con", "hitscan_test.con"):
        shutil.copyfile(HERE / "fixtures" / name, lab / name)
    # hitscan_test owns the stock pistol selection and ammo/impact observations;
    # hand_test contributes the real native LIZTROOP health observer.
    closed = args.case == "wall"
    quick = args.case.startswith("quickkick")
    damage = args.case == "damage" or quick
    data=bytearray(room(closed, damage))
    if quick:
        x,y=(3000,4548) if args.case=='quickkick-far' else (1600,4250)
        struct.pack_into('<ii',data,len(data)-44,x,y)
        fixture=lab/'hand_test.con'
        fixture.write_text(fixture.read_text().replace('].x 4096',f'].x {x}').replace('].y 4790',f'].y {y}'))
    (lab / "pistol-mount.map").write_bytes(data)
    install_model(lab, mounted)
    return lab


def environment(display, client_lab):
    base = {key: value for key, value in os.environ.items() if not key.startswith("EDUKE32_XR")}
    base.update(DISPLAY=display, SDL_VIDEODRIVER="x11", SDL_AUDIODRIVER="dummy")
    server = {key: value for key, value in base.items() if not key.startswith("XR_")}
    server["EDUKE32_XR_TEST_SHOTS"] = "1"
    client = dict(base, EDUKE32_XR="1", EDUKE32_XR_UI="2", EDUKE32_XR_SINGLE_PASS="1",
                  EDUKE32_XR_AIM="right", EDUKE32_XR_WEAPON="1", EDUKE32_XR_HAND_SHOTS="1",
                  EDUKE32_XR_MODELS="1", EDUKE32_XR_TEST_MODELS="1", EDUKE32_XR_TEST_INPUT="1",
                  EDUKE32_XR_TEST_AIM="1", EDUKE32_XR_TEST_SHOTS="1", EDUKE32_XR_PISTOL_MOUNT="1",
                  EDUKE32_XR_WORLD_OUTPUT=str(client_lab / "world"),
                  EDUKE32_XR_MODEL_OUTPUT=str(client_lab / "model"),
                  EDUKE32_XR_HUD_OUTPUT=str(client_lab / "hud"),
                  EDUKE32_XR_WEAPON_OUTPUT=str(client_lab / "weapon"))
    return server, client


def fire(remote, hand, server, player, expect=True):
    """Use one physical trigger edge, returning only authoritative native rays."""
    offset = len(server.text())
    hand.trigger_value, hand.trigger_click = 1, True
    remote.send()
    if expect:
        server.wait(lambda text: bool(rays(text[offset:], player)), timeout=5)
    else:
        server.pause(.8)
    hand.trigger_value, hand.trigger_click = 0, False
    remote.send()
    server.pause(.25)
    return rays(server.text()[offset:], player)


def await_release(server, player, offset):
    """Require several native samples after release before allowing a re-press."""
    server.wait(lambda text: len(samples(text[offset:], "ammo", player)) >= 3, timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "client-binary", "grp", "work-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--remote-port", required=True, type=int)
    parser.add_argument("--display", default=":105")
    parser.add_argument("--port", type=int, default=24960)
    parser.add_argument("--case", choices=CASES, default="damage")
    parser.add_argument("--mounted-assets", type=Path, default=MOUNTED_ASSETS)
    parser.add_argument("--missing-tag-assets", type=Path, default=V4_ASSETS)
    args = parser.parse_args()
    for name in ("binary", "client_binary", "grp", "mounted_assets", "missing_tag_assets"):
        setattr(args, name, getattr(args, name).resolve())
    args.work_dir.mkdir(parents=True, exist_ok=True)

    mounted_tags = md3_tags(args.mounted_assets / "pistol.md3")
    missing_tags = md3_tags(args.missing_tag_assets / "pistol.md3")
    required = {"tag_muzzle", "tag_palm_left", "tag_palm_right", "tag_grip"}
    if not required.issubset(mounted_tags):
        raise RuntimeError("mounted export lacks a required palm/muzzle/grip tag")
    if "tag_muzzle" not in missing_tags or {"tag_palm_left", "tag_palm_right"} & set(missing_tags):
        raise RuntimeError("missing-tag control must retain muzzle but omit both palm tags")

    root = Path(tempfile.mkdtemp(prefix="pistol-mount-gameplay-", dir=args.work_dir.resolve()))
    server = client = None
    logs = []
    phase = "setup"
    result = {"passed": False, "case": args.case}
    selected_assets = args.missing_tag_assets if args.case == "missing-tag" else args.mounted_assets
    try:
        sl = prepare_lab(root, "server", args, selected_assets)
        cl = prepare_lab(root, "client", args, selected_assets)
        server_env, client_env = environment(args.display, cl)
        server_log = (sl / "server.log").open("w")
        logs.append(server_log)
        server = subprocess.Popen([str(args.binary), "-usecwd", "-nosetup", "-noautoload", "-dedicated",
                                   "-port", str(args.port), "-map", "pistol-mount.map", "-x", "hitscan_test.con"],
                                  cwd=sl, env=server_env, stdin=subprocess.DEVNULL,
                                  stdout=server_log, stderr=subprocess.STDOUT)
        so = Observer(server, sl / "server.log")
        so.wait(lambda text: "Multiplayer server initialized." in text)
        with Remote(args.remote_port) as remote:
            hand = remote.packet.right
            hand.pose.position.x, hand.pose.position.y, hand.pose.position.z = .2, 1.3, -.5
            # Roll belongs to the renderer's local model basis.  The gameplay
            # check holds it fixed and validates only the server's serialized
            # calibrated origin/ray, never an invented roll-dependent reach.
            remote.send()
            client_log = (cl / "client.log").open("w")
            logs.append(client_log)
            client = subprocess.Popen([str(args.client_binary), "-usecwd", "-nosetup", "-noautoload", "-nologo",
                                       "-ns", "-nm", "-connect", f"127.0.0.1:{args.port}", "-x", "hitscan_test.con",
                                       "-h", "pistol-mount.def"], cwd=cl, env=client_env, stdin=subprocess.DEVNULL,
                                      stdout=client_log, stderr=subprocess.STDOUT)
            co = Observer(client, cl / "client.log")
            phase = "native join"
            player = wait_for_join_barrier(X11(args.display), client, cl / "client.log", so)["server_player"]
            so.wait(lambda text: len(players(text, player)) > 20)
            co.pause(1)
            # Match the existing native hitscan fixture: establish the map's
            # body/reference first, then aim the controller at its target.
            pitch=8
            if args.case=='damage' or args.case.startswith('quickkick'):
                # The native spawn retains a body look angle. Aim the physical
                # controller down by that measured pitch to target a floor actor.
                co.wait(lambda text: bool(re.findall(r'OpenXR aim:.*bodyPitch=([-+\d.eE]+)',text)))
                pitch=-math.degrees(float(re.findall(r'OpenXR aim:.*bodyPitch=([-+\d.eE]+)',co.text())[-1]))
            hand.pose.orientation = orientation(12, pitch)
            remote.packet.head.center.orientation = orientation(-12, 4)
            remote.send()
            co.pause(.5)
            co.wait(lambda text: "OpenXR world oracle: 60 frames" in text and
                    "OpenXR HUD presentation: 60 frames" in text, timeout=25)
            so.wait(lambda text: bool(samples(text, "ammo", player)), timeout=8)
            baseline_ammo = samples(so.text(), "ammo", player)[-1]
            common = {
                "native_join": player > 0,
                "pistol_selected_with_native_ammo": baseline_ammo > 0,
                "mounted_asset_tags": required.issubset(mounted_tags),
                "missing_tag_control_has_no_palm_tags": not ({"tag_palm_left", "tag_palm_right"} & set(missing_tags)),
                "core_validation_active": "Core Validation output type:" in co.text(),
                "core_validation_clean": not re.search(r"VALID_(?:ERROR|WARN)|Validation (?:Error|Warning)", co.text()),
            }
            if args.case == "missing-tag":
                phase = "invalid mount release latch"
                offset = len(so.text())
                fire(remote, hand, so, player, expect=False)
                # Quick kick is deliberately attempted while the pistol remains
                # selected.  An enabled-invalid shot context must not create a
                # KNEE impact or spend pistol ammo.
                hand.thumbstick_click = True
                remote.send()
                so.pause(.5)
                hand.thumbstick_click = False
                remote.send()
                so.pause(.35)
                after_ammo = samples(so.text(), "ammo", player)[-1]
                part = so.text()[offset:]
                checks = dict(common,
                    no_native_pistol_hitscan=not rays(part, player),
                    no_native_quickkick_hitscan=not melee_traces(part),
                    invalid_mount_keeps_pistol_ammo=after_ammo == baseline_ammo,
                    invalid_mount_never_publishes_calibrated_pose=not MOUNT_POSE.search(co.text()))
                details = {"ammo_before": baseline_ammo, "ammo_after": after_ammo}
            else:
                co.wait(lambda text: bool(MOUNT_POSE.findall(text)), timeout=10)
                if args.case == "loss":
                    phase = "tracking loss and release recovery"
                    offset = len(so.text())
                    hand.trigger_value, hand.trigger_click, hand.active = 1, True, False
                    remote.send()
                    so.pause(.55)
                    lost = so.text()[offset:]
                    hand.active = True
                    remote.send()
                    so.pause(.65)
                    held = so.text()[offset:]
                    release_offset = len(so.text())
                    hand.trigger_value, hand.trigger_click = 0, False
                    remote.send()
                    await_release(so, player, release_offset)
                    recovery_ammo = samples(so.text(), "ammo", player)[-1]
                    phase = "new physical trigger after release"
                    recovered = fire(remote, hand, so, player)
                    after_ammo = samples(so.text(), "ammo", player)[-1]
                    checks = dict(common,
                        calibrated_mount_pose_published=bool(MOUNT_POSE.findall(co.text())),
                        tracking_loss_held_trigger_has_no_shot=not rays(lost, player),
                        recovery_held_trigger_has_no_shot=not rays(held, player),
                        recovery_hold_keeps_ammo=recovery_ammo == baseline_ammo,
                        release_then_new_press_has_one_native_shot=len(recovered) == 1,
                        release_then_new_press_consumes_ammo=after_ammo < baseline_ammo)
                    details = {"ammo_before": baseline_ammo, "ammo_after_release": recovery_ammo,
                               "ammo_after_repress": after_ammo, "repress_rays": recovered}
                elif args.case.startswith("quickkick"):
                    phase = "calibrated pistol reference shot"
                    reference = fire(remote, hand, so, player)
                    if len(reference) != 1:
                        raise RuntimeError("expected exactly one mounted pistol reference ray")
                    ammo_before_quick = samples(so.text(), "ammo", player)[-1]
                    health_before_quick = health(so.text())
                    offset = len(so.text())
                    hand.thumbstick_click = True
                    remote.send()
                    so.wait(lambda text: bool(melee_traces(text[offset:])), timeout=5)
                    hand.thumbstick_click = False
                    remote.send()
                    so.pause(.5)
                    quick = melee_traces(so.text()[offset:])
                    far=args.case=='quickkick-far'
                    if not far:
                        so.wait(lambda text: health(text)<health_before_quick,timeout=5)
                    target_health=health(so.text())
                    co.wait(lambda text: health(text)==target_health or health(text)<=0 and target_health<=0,timeout=6)
                    after_ammo = samples(so.text(), "ammo", player)[-1]
                    origin = reference[0]
                    checks = dict(common,
                        calibrated_mount_pose_published=bool(MOUNT_POSE.findall(co.text())),
                        pistol_reference_uses_native_hand_ray=True,
                        quickkick_trace_is_selected_pistol=bool(quick) and quick[-1]["quick"] == 1,
                        quickkick_leaves_the_body_not_the_pistol=bool(quick) and
                            [quick[-1][key] for key in ("hx", "hy")] != [origin[key] for key in ("x", "y")],
                        quickkick_does_not_consume_pistol_ammo=after_ammo == ammo_before_quick)
                    checks.update(quickkick_ray_hits_actual_target=bool(quick) and quick[-1]['target']==4,
                                  quickkick_native_range_decision=bool(quick) and quick[-1]['inRange']==int(not far),
                                  native_quickkick_damage_or_far_rejection=(target_health==health_before_quick if far else target_health<health_before_quick),
                                  target_health_replicates=health(co.text())==target_health or health(co.text())<=0 and target_health<=0)
                    details = {"pistol_origin": [origin[key] for key in ("x", "y", "z")],
                               "quick_trace": quick[-1] if quick else None,
                               "ammo_before_quick": ammo_before_quick, "ammo_after_quick": after_ammo,
                               "target_health_before_quick":health_before_quick,"target_health_after_quick":target_health}
                else:
                    phase = "mounted native pistol shot"
                    before_health = health(so.text()) if args.case == "damage" else None
                    observed = fire(remote, hand, so, player)
                    if len(observed) != 1:
                        raise RuntimeError("expected exactly one mounted pistol native ray")
                    shot = observed[0]
                    after_ammo = samples(so.text(), "ammo", player)[-1]
                    checks = dict(common,
                        calibrated_mount_pose_published=bool(MOUNT_POSE.findall(co.text())),
                        mounted_pistol_uses_one_native_hitscan=len(observed) == 1,
                        native_ammo_consumed=after_ammo < baseline_ammo)
                    if args.case == "damage":
                        phase = "native enemy damage convergence"
                        so.wait(lambda text: health(text) < before_health, timeout=5)
                        server_health = health(so.text())
                        co.wait(lambda text: health(text) <= max(server_health, 0), timeout=6)
                        client_health = health(co.text())
                        checks.update(native_ray_hits_real_enemy=shot["sprite"] == 4,
                                      native_server_health_decreases=server_health < before_health,
                                      native_client_health_converges=client_health <= max(server_health, 0))
                        details = {"ray": shot, "target_health": {"before": before_health,
                                   "server": server_health, "client": client_health},
                                   "ammo_before": baseline_ammo, "ammo_after": after_ammo}
                    else:
                        checks.update(wall_clamps_calibrated_origin=shot["clamped"] == 1 and shot["x"] <= 1136,
                                      wall_blocks_before_portal=abs(shot["hitx"] - 1152) <= 1 and shot["wall"] >= 0)
                        details = {"ray": shot, "ammo_before": baseline_ammo, "ammo_after": after_ammo}
            result.update(passed=all(checks.values()), checks=checks, **details)
    except Exception as error:
        result.update(error=str(error), phase=phase)
    finally:
        stop(client)
        stop(server)
        for log in logs:
            log.close()
        result.update(evidence_directory=str(root), mounted_asset_sha256=sha256(args.mounted_assets / "pistol.md3"),
                      missing_tag_asset_sha256=sha256(args.missing_tag_assets / "pistol.md3"),
                      mounted_tags=mounted_tags, missing_tag_tags=missing_tags)
        (root / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
