#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Multiplayer interaction sweep: bots use every switch, scanner, security screen and door of a level.

Run inside tools/vr/software_xr_lab.py (it provides the X display). A dedicated co-op server runs the
level (monsters off) with two flat players: the actor walks up to each interactive thing found in the
map and presses Use (test_use), the other only watches. After each use the server and both players
write their world state (net_state) twice, a moment apart, and the sweep reports what does not
agree or should not happen:

  desync-player   the actor's position on the server and in its own game differ
  moved           the actor ended up far from where it stood to use the thing (a teleport)
  camera-stuck    a security screen left the actor in camera view, or not back where it stood
  desync-sector   a sector's floor or ceiling differs between the server and a player (both samples)
  desync-switch   a switch wall's picture differs (on/off) between the server and a player
  desync-sprite   a lasting sprite (crane, door part, effector...) is elsewhere on a player's game
  crane-off-rail  a crane left the line between its rest place and its pole (server or a player)
  crane-stuck     a crane that took the actor did not get back to its rest place
  actor-died      the actor was dead after using the thing (it is respawned and the sweep goes on)
  level-ended     the thing ended the level (an exit): the rest of the chunk is not run

Progression things are tested their own way: cranes (stand under the pole and ride it there and
back), lifts and elevators (Use from inside), teleporters and touch plates (step in).

Level-ending things (nuke buttons, end-of-level sectors) are left out. Prints a JSON report.
"""
import argparse, json, math, os, re, struct, subprocess, tempfile, time
from pathlib import Path
from smoke_world import CONFIG

SWITCHES = {162, 164, 168, 140, 1111, 712, 134, 862, 860, 864, 1122, 132, 136, 138, 130, 170, 146, 166, 1142}
SWITCH_TILES = SWITCHES | {t + 1 for t in SWITCHES} | {147, 148, 149}
ACCESS = {130, 131, 170, 171}
VIEWSCREENS = {502, 499}
NUKEBUTTON = {142, 143, 144, 145}
DOOR_LOTAGS = {9, 20, 21, 22, 23, 25, 26, 29}   # doors used with Use from outside
LIFT_LOTAGS = {15, 16, 17, 18, 19}               # elevators and platforms used with Use from inside
CRANE, CRANEPOLE, TOUCHPLATE, SECTOREFFECTOR = 1222, 1221, 3, 1
SE_TELEPORT = 7
# Effectors that move their sector all the time (rotating sectors, subways, pistons, waves): sampled
# at slightly different moments on the server and the players, they never compare.
CONTINUOUS_SE = {0, 6, 14, 25, 29}
CAMERA_TOLERANCE = 256


def grp_file(grp, name):
    d = grp.read_bytes()
    n = struct.unpack_from('<I', d, 12)[0]
    off = 16 + 16 * n
    for i in range(n):
        entry = d[16 + 16 * i:28 + 16 * i].rstrip(b'\0').decode().upper()
        size = struct.unpack_from('<I', d, 28 + 16 * i)[0]
        if entry == name.upper():
            return d[off:off + size]
        off += size
    return None


def read_map(data):
    p = 22
    ns = struct.unpack_from('<H', data, 20)[0]
    sectors = []
    for i in range(ns):
        wallptr, wallnum = struct.unpack_from('<hh', data, p + 40 * i)
        ceilingz, floorz = struct.unpack_from('<ii', data, p + 40 * i + 4)
        lotag, hitag = struct.unpack_from('<hh', data, p + 40 * i + 34)
        sectors.append(dict(wallptr=wallptr, wallnum=wallnum, floorz=floorz, ceilingz=ceilingz, lotag=lotag, hitag=hitag))
    p += 40 * ns
    nw = struct.unpack_from('<H', data, p)[0]; p += 2
    walls = []
    for i in range(nw):
        x, y, point2, nextwall, nextsector, cstat, picnum, overpicnum = struct.unpack_from('<iihhhhhh', data, p + 32 * i)
        lotag, hitag = struct.unpack_from('<hh', data, p + 32 * i + 26)
        walls.append(dict(x=x, y=y, point2=point2, nextwall=nextwall, nextsector=nextsector, picnum=picnum, overpicnum=overpicnum,
                          lotag=lotag, hitag=hitag))
    p += 32 * nw
    nsp = struct.unpack_from('<H', data, p)[0]; p += 2
    sprites = []
    for i in range(nsp):
        x, y, z, cstat, picnum = struct.unpack_from('<iiihh', data, p + 44 * i)
        sectnum, statnum, ang = struct.unpack_from('<hhh', data, p + 44 * i + 24)
        lotag, hitag = struct.unpack_from('<hh', data, p + 44 * i + 38)
        sprites.append(dict(x=x, y=y, z=z, cstat=cstat, picnum=picnum, sectnum=sectnum, ang=ang, lotag=lotag, hitag=hitag))
    for s, sec in enumerate(sectors):
        for w in range(sec['wallptr'], sec['wallptr'] + sec['wallnum']):
            walls[w]['sector'] = s
    return sectors, walls, sprites


def inside(sectors, walls, s, x, y):
    sec = sectors[s]
    crossings = 0
    for w in range(sec['wallptr'], sec['wallptr'] + sec['wallnum']):
        a, b = walls[w], walls[walls[w]['point2']]
        if (a['y'] > y) != (b['y'] > y) and x < a['x'] + (y - a['y']) * (b['x'] - a['x']) / (b['y'] - a['y']):
            crossings += 1
    return crossings % 2 == 1


def find_sector(sectors, walls, x, y):
    return next((s for s in range(len(sectors)) if inside(sectors, walls, s, x, y)), -1)


def build_angle(dx, dy):
    return int(round(math.atan2(dy, dx) * 1024 / math.pi)) & 2047


def wall_spot(sectors, walls, w, sector, distance=192):
    """A place in front of wall w (inside `sector`) facing it."""
    a, b = walls[w], walls[walls[w]['point2']]
    mx, my = (a['x'] + b['x']) / 2, (a['y'] + b['y']) / 2
    dx, dy = b['x'] - a['x'], b['y'] - a['y']
    length = math.hypot(dx, dy) or 1
    for nx, ny in ((-dy / length, dx / length), (dy / length, -dx / length)):
        x, y = mx + nx * distance, my + ny * distance
        if inside(sectors, walls, sector, x, y):
            return int(x), int(y), build_angle(mx - x, my - y)
    return None


def interior(sectors, walls, s):
    """A point inside sector s: its vertex centroid, else just inside its first wall."""
    sec = sectors[s]
    pts = [(walls[w]['x'], walls[w]['y']) for w in range(sec['wallptr'], sec['wallptr'] + sec['wallnum'])]
    x, y = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    if inside(sectors, walls, s, x, y):
        return int(x), int(y)
    for w in range(sec['wallptr'], sec['wallptr'] + sec['wallnum']):
        spot = wall_spot(sectors, walls, w, s, 96)
        if spot:
            return spot[0], spot[1]
    return None


def targets(sectors, walls, sprites):
    found = []
    end_sectors = {s for s, sec in enumerate(sectors) if sec['lotag'] in (-1, 65535)}
    for w, wall in enumerate(walls):
        tile = wall['overpicnum'] if wall['overpicnum'] in SWITCH_TILES else wall['picnum']
        if tile in SWITCH_TILES and wall['lotag'] and 'sector' in wall:
            spot = wall_spot(sectors, walls, w, wall['sector'])
            if spot:
                found.append(dict(kind='access' if tile in ACCESS else 'switch-wall', id=w, tile=tile, spot=spot))
    for i, spr in enumerate(sprites):
        if spr['picnum'] in NUKEBUTTON:
            continue
        kind = ('viewscreen' if spr['picnum'] in VIEWSCREENS else 'access' if spr['picnum'] in ACCESS
                else 'switch-sprite' if spr['picnum'] in SWITCH_TILES and spr['lotag'] else None)
        if not kind or not (0 <= spr['sectnum'] < len(sectors)):
            continue
        for sign in (1, -1):
            a = spr['ang'] * math.pi / 1024
            x, y = spr['x'] + sign * 224 * math.cos(a), spr['y'] + sign * 224 * math.sin(a)
            s = find_sector(sectors, walls, x, y)
            if s >= 0 and s not in end_sectors:
                found.append(dict(kind=kind, id=i, tile=spr['picnum'], spot=(int(x), int(y), build_angle(spr['x'] - x, spr['y'] - y))))
                break
    for s, sec in enumerate(sectors):
        if (sec['lotag'] & 0x7fff) in LIFT_LOTAGS and s not in end_sectors:
            spot = interior(sectors, walls, s)
            if spot:
                found.append(dict(kind='lift', id=s, tile=sec['lotag'], spot=(*spot, 0)))
    for i, spr in enumerate(sprites):
        if not (0 <= spr['sectnum'] < len(sectors)) or spr['sectnum'] in end_sectors:
            continue
        if spr['picnum'] == CRANE:
            pole = next((p for p in sprites if p['picnum'] == CRANEPOLE and p['hitag'] == spr['hitag']), None)
            if pole:
                found.append(dict(kind='crane', id=i, tile=CRANE, spot=(pole['x'], pole['y'], 0),
                                  rail=((spr['x'], spr['y']), (pole['x'], pole['y']))))
        elif spr['picnum'] == TOUCHPLATE:
            spot = interior(sectors, walls, spr['sectnum'])
            if spot:
                found.append(dict(kind='touchplate', id=i, tile=TOUCHPLATE, spot=(*spot, 0)))
        elif spr['picnum'] == SECTOREFFECTOR and spr['lotag'] == SE_TELEPORT and sectors[spr['sectnum']]['lotag'] not in (1, 2):
            # (SE 7 in above/under water sectors links the water layers: not a teleporter)
            found.append(dict(kind='teleport', id=i, tile=SE_TELEPORT, spot=(spr['x'], spr['y'], 0)))
    for s, sec in enumerate(sectors):
        if (sec['lotag'] & 0x7fff) in DOOR_LOTAGS:
            # From the far side of the door's first two-sided wall, facing it.
            for w in range(sec['wallptr'], sec['wallptr'] + sec['wallnum']):
                other = walls[w]['nextsector']
                if other >= 0 and other not in end_sectors and (sectors[other]['lotag'] & 0x7fff) not in DOOR_LOTAGS:
                    back = walls[w]['nextwall']
                    spot = wall_spot(sectors, walls, back, other, 256) if back >= 0 else None
                    if spot:
                        found.append(dict(kind='door', id=s, tile=sec['lotag'], spot=spot))
                        break
    return found


def parse_state(path):
    state = dict(players={}, sectors={}, walls={}, sprites={}, local=-1, map='')
    for line in path.read_text().splitlines():
        f = line.split()
        if not f:
            continue
        if f[0] == 'map':
            state['map'] = f[1].upper()
        elif f[0] == 'local':
            state['local'] = int(f[1])
        elif f[0] == 'player':
            state['players'][int(f[1])] = dict(pos=(int(f[3]), int(f[4]), int(f[5])), newowner=int(f[11]), crane=int(f[13]),
                                               extra=int(f[15]), dead=int(f[17]))
        elif f[0] == 'sector':
            state['sectors'][int(f[1])] = (int(f[2]), int(f[3]))
        elif f[0] == 'wall':
            state['walls'][int(f[1])] = (int(f[2]), int(f[3]))
        elif f[0] == 'sprite':
            state['sprites'][int(f[1])] = tuple(map(int, f[2:]))
    return state


def compare(server, client, who, moving=frozenset()):
    issues = []
    for s, (fz, cz) in server['sectors'].items():
        if s in moving:
            continue
        other = client['sectors'].get(s)
        if other and (abs(other[0] - fz) > 512 or abs(other[1] - cz) > 512):
            issues.append(('desync-sector', who, s, (fz, cz), other))
    for w, pics in server['walls'].items():
        other = client['walls'].get(w)
        # Switches only (animated walls such as force fields are sampled at different moments).
        if other and other != pics and (set(pics) | set(other)) & SWITCH_TILES:
            issues.append(('desync-switch', who, w, pics, other))
    for i, spr in server['sprites'].items():
        other = client['sprites'].get(i)
        if other and other[0] == spr[0] and other[1] == spr[1] and (abs(other[2] - spr[2]) > 768 or abs(other[3] - spr[3]) > 768):
            issues.append(('desync-sprite', who, i, spr[:5], other[:5]))
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--level', default='1,1', help='episode,level')
    parser.add_argument('--display', default=':105')
    parser.add_argument('--port', type=int, default=24691)
    parser.add_argument('--settle', type=float, default=3.5, help='seconds after a use before sampling')
    parser.add_argument('--only', default='', help='only these kinds (comma separated, e.g. crane,lift)')
    parser.add_argument('--start', type=int, default=0, help='skip the first targets (chunked runs)')
    parser.add_argument('--limit', type=int, default=0, help='at most this many targets (0: all)')
    parser.add_argument('--timeout', type=int, default=560)
    parser.add_argument('--server-wrap', default='', help='command the server runs under (e.g. a debugger)')
    parser.add_argument('--server-binary', type=Path, help='another binary for the server (e.g. a debug build)')
    parser.add_argument('--client-env', action='append', default=[], help='KEY=VALUE for the players\' games')
    parser.add_argument('--client-wrap', default='', help='command the players run under (e.g. gdb); a player that stops '
                        'answering is interrupted (SIGINT) so a debugger shows where')
    args = parser.parse_args()
    episode, level = map(int, args.level.split(','))
    deadline = time.monotonic() + args.timeout
    data = grp_file(args.grp, f'E{episode}L{level}.MAP')
    if data is None:
        print(json.dumps({'passed': False, 'error': f'no E{episode}L{level}.MAP in the GRP'}))
        return 1
    sectors, walls, sprites = read_map(data)
    teleporters = frozenset(spr['sectnum'] for spr in sprites if spr['picnum'] == SECTOREFFECTOR and spr['lotag'] == SE_TELEPORT)
    moving = frozenset(spr['sectnum'] for spr in sprites if spr['picnum'] == SECTOREFFECTOR and spr['lotag'] in CONTINUOUS_SE)
    every = [t for t in targets(sectors, walls, sprites) if not args.only or t['kind'] in args.only.split(',')]
    todo = every[args.start:args.start + args.limit] if args.limit else every[args.start:]
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f'sweep-e{episode}l{level}-', dir=args.work_dir.resolve()))
    env = {k: v for k, v in os.environ.items() if not k.startswith(('EDUKE32_XR', 'XR_'))}
    env.update(DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy')
    result = {'level': f'E{episode}L{level}', 'targets': len(todo), 'of': len(every), 'start': args.start, 'used': 0, 'issues': [], 'baseline': [],
              'evidence_directory': str(root)}
    processes = []

    def lab(name):
        d = root / name; d.mkdir()
        # Small windows: three software-rendered games share the lab's X server.
        config = CONFIG.replace('ScreenWidth = 960', 'ScreenWidth = 320').replace('ScreenHeight = 600', 'ScreenHeight = 200')
        (d / 'eduke32.cfg').write_text(config + f'\n[Comm Setup]\nPlayerName = "{name}"\n')
        (d / 'DUKE3D.GRP').symlink_to(args.grp.resolve())
        return d

    def log_text(d):
        return (d / 'game.log').read_text(errors='replace')

    def wait(predicate, seconds):
        limit = min(deadline, time.monotonic() + seconds)
        while not predicate():
            if any(p.poll() is not None for p in processes):
                raise RuntimeError('a game exited')
            if time.monotonic() > limit:
                return False
            time.sleep(.1)
        return True

    try:
        binary = str(args.binary.resolve())
        common = ['-usecwd', '-nosetup', '-noautoload', '-nologo', '-ns', '-nm']
        host = lab('server')
        # --server-wrap, e.g. "gdb -batch -ex run -ex bt --args": the server under a debugger.
        server_env = dict(env, **dict(kv.split('=', 1) for kv in args.client_env))
        server = subprocess.Popen([*args.server_wrap.split(), str(args.server_binary.resolve()) if args.server_binary else binary,
                                   *common, '-dedicated', '-port', str(args.port), '-c2', f'-v{episode}', f'-l{level}', '-m'],
                                  cwd=host, env=server_env, stdin=subprocess.PIPE, stdout=(host / 'game.log').open('w'), stderr=subprocess.STDOUT)
        processes.append(server)
        if not wait(lambda: 'Multiplayer server initialized.' in log_text(host), 60):
            raise RuntimeError('server did not start')
        time.sleep(2)
        bots = {}
        for name in ('actor', 'watcher'):
            d = lab(name)
            request = d / 'console-request'
            p = subprocess.Popen([*args.client_wrap.split(), binary, *common, '-connect', f'127.0.0.1:{args.port}'], cwd=d,
                                 env=dict(env, EDUKE32_XR_CONSOLE_REQUEST=str(request), EDUKE32_TEST_STALL='1', **dict(kv.split('=', 1) for kv in args.client_env)), stdin=subprocess.DEVNULL,
                                 stdout=(d / 'game.log').open('w'), stderr=subprocess.STDOUT)
            processes.append(p)
            if not wait(lambda: 'Multiplayer client level synchronization complete.' in log_text(d), 120):
                raise RuntimeError(f'{name} did not join')
            bots[name] = (d, request, p)
            time.sleep(2)

        def console(name, command):
            d, request, _ = bots[name]
            request.write_text(command + '\n')
            return wait(lambda: not request.exists(), 30)

        def server_command(command):
            server.stdin.write((command + '\n').encode()); server.stdin.flush()

        def states(tag):
            files = {'server': host / f'{tag}.state'}
            server_command(f'net_state {tag}.state')   # relative to its directory: its console reads short lines
            for name in bots:
                files[name] = bots[name][0] / f'{tag}.state'
                console(name, f'net_state {files[name]}')
            wait(lambda: all(f.is_file() and f.stat().st_size for f in files.values()), 20)
            time.sleep(.3)
            silent = [k for k, f in files.items() if not f.is_file()]
            if silent:
                # A game that stopped answering: it prints its stack (SIGUSR1, EDUKE32_TEST_STALL), and
                # is interrupted (under a debugger this shows where).
                for k in silent:
                    if k in bots:
                        pid = bots[k][2].pid
                        try:
                            os.kill(pid, 10)
                        except OSError:
                            pass
                        time.sleep(1)
                        for entry in Path('/proc').iterdir():
                            try:
                                if entry.name.isdigit() and int((entry / 'stat').read_text().rsplit(') ', 1)[1].split()[1]) == pid:
                                    os.kill(int(entry.name), 2)
                            except (OSError, ValueError, IndexError):
                                pass
                time.sleep(5)
                raise RuntimeError(f'{",".join(silent)} stopped answering at {tag}')
            return {k: parse_state(f) for k, f in files.items()}

        before = states('baseline')
        for name in bots:
            result['baseline'] += [list(map(str, i)) for i in compare(before['server'], before[name], name, moving)][:20]
        me = None
        for n, target in enumerate(todo):
            if time.monotonic() > deadline - 30:
                result['stopped_early'] = n
                break
            x, y, ang = target['spot']
            kind = target['kind']
            console('actor', f'xr_goto {x} {y} {ang}')
            time.sleep(1.0)
            issues = []
            if kind == 'crane':
                # Stand under the pole: the crane comes, lifts the actor, carries them to its rest
                # place and lets go. It must stay on its rail everywhere, and come back.
                (hx, hy), (px, py) = target['rail']
                length = math.hypot(px - hx, py - hy) or 1

                def off_rail(sx, sy):
                    t = max(0, min(1, ((sx - hx) * (px - hx) + (sy - hy) * (py - hy)) / length ** 2))
                    return math.hypot(sx - (hx + t * (px - hx)), sy - (hy + t * (py - hy)))
                worst, back = 0, False
                for k in range(10):
                    time.sleep(4)
                    sample = states(f't{n}r{k}')
                    for who, st in sample.items():
                        crane = st['sprites'].get(target['id'])
                        if crane:
                            d = off_rail(crane[2], crane[3])
                            worst = max(worst, d)
                            if d > 128:
                                issues.append(('crane-off-rail', who, target['id'], (crane[2], crane[3]), int(d)))
                    srv = sample['server']['sprites'].get(target['id'])
                    if k >= 4 and srv and math.hypot(srv[2] - hx, srv[3] - hy) < 256:
                        back = True
                        break
                if not back:
                    issues.append(('crane-stuck', 'server', target['id'], (hx, hy), srv[2:4] if srv else None))
                result['used'] += 1
                if issues:
                    result['issues'].append({'target': target, 'issues': [list(map(str, i)) for i in issues][:30]})
                continue
            if kind not in ('teleport', 'touchplate'):
                console('actor', 'test_use')
            time.sleep(args.settle + (3 if kind == 'lift' else 0))
            first = states(f't{n}a')
            time.sleep(1.5)
            second = states(f't{n}b')
            result['used'] += 1
            if me is None:
                me = first['actor']['local']
            maps = {st['map'] for st in (first['server'], second['server'])}
            if not any(f'E{episode}L{level}.MAP' in m for m in maps):
                result['issues'].append({'target': target, 'issues': [['level-ended', 'server', str(sorted(maps))]]})
                result['stopped_early'] = n
                break
            server_me, own_me = second['server']['players'].get(me), second['actor']['players'].get(me)
            if own_me and (own_me['dead'] or own_me['extra'] <= 0):
                issues.append(('actor-died', 'actor', me, (x, y), own_me['pos']))
                result['issues'].append({'target': target, 'issues': [list(map(str, i)) for i in issues]})
                console('actor', 'test_use')   # respawn
                time.sleep(3)
                continue
            if server_me and own_me:
                if own_me['newowner'] < 0 and math.dist(server_me['pos'][:2], own_me['pos'][:2]) > 512:
                    issues.append(('desync-player', 'actor', me, server_me['pos'], own_me['pos']))
                if math.dist(own_me['pos'][:2], (x, y)) > 1536 and own_me['newowner'] < 0 and kind not in ('door', 'teleport', 'lift') \
                        and find_sector(sectors, walls, x, y) not in teleporters:
                    issues.append(('moved', 'actor', me, (x, y), own_me['pos']))
                if own_me['newowner'] >= 0 or target['kind'] == 'viewscreen':
                    # A camera: leave it, and the actor must be back where it stood.
                    console('actor', 'test_use')
                    time.sleep(1.5)
                    after = states(f't{n}c')
                    back = after['actor']['players'].get(me)
                    srv = after['server']['players'].get(me)
                    if back and (back['newowner'] >= 0 or math.dist(back['pos'][:2], (x, y)) > CAMERA_TOLERANCE * 4):
                        issues.append(('camera-stuck', 'actor', me, (x, y), back['pos'], back['newowner']))
                    if back and srv and math.dist(back['pos'][:2], srv['pos'][:2]) > 512:
                        issues.append(('desync-player', 'actor-after-camera', me, srv['pos'], back['pos']))
            for name in bots:
                # Only what stays wrong: the server's value held still between the two samples and the
                # player's still differs (a lift or door still moving is sampled at different moments).
                a = {tuple(map(str, i[:3])) for i in compare(first['server'], first[name], name, moving)}
                for issue in compare(second['server'], second[name], name, moving):
                    kind, _, key = issue[0], issue[1], issue[2]
                    table = {'desync-sector': 'sectors', 'desync-switch': 'walls', 'desync-sprite': 'sprites'}[kind]
                    steady = first['server'][table].get(key) == second['server'][table].get(key)
                    if tuple(map(str, issue[:3])) in a and steady:
                        issues.append(issue)
            if issues:
                result['issues'].append({'target': target, 'issues': [list(map(str, i)) for i in issues][:30]})
        result['passed'] = not result['issues']
    except RuntimeError as error:
        result['error'] = str(error)
    finally:
        for p in reversed(processes):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill(); p.wait()
    print(json.dumps(result, indent=1))
    return 0 if result.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
