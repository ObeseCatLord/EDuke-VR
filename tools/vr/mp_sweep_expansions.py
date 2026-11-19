#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Runs tools/vr/mp_sweep.py over the official expansions' levels (not the software XR lab: the bots
are flat, so each worker gets its own Xvfb display and server port).

  mp_sweep_expansions.py --binary eduke32-xr --data BUNDLE/data --work-dir work/expsweep \\
      [--only worldtour,caribbean,dc,nwinter] [--levels 1,3] [--workers 2] [--chunk 36]

BUNDLE/data is a personal bundle's data folder: grp/DUKE3D.GRP (World Tour), worldtour/ (episode 5
CON, art, maps), addons/DUKE3D.GRP (Atomic) with vacation.grp, dukedc.grp and nwinter.grp.
Writes WORK/report.json as chunks finish (resumable); a chunk's folder is kept only when it found
something. Every game runs with HOME/XDG folders inside WORK, never the user's own.
"""
import argparse, json, os, shutil, subprocess, sys, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mp_sweep  # noqa: E402


def expansions(data):
    # Episode numbers as the add-on's own CON defines them: Life's a Beach and DC are episode 3 (1 is
    # still L.A. Meltdown), Nuclear Winter episode 2.
    addons = data / 'addons'
    return {
        # The whole World Tour campaign (its own CON and remastered maps), episodes 1-5.
        'worldtour': dict(grp=data / 'grp/DUKE3D.GRP', episodes={1: range(1, 12), 2: range(1, 12), 3: range(1, 12),
                                                                 4: range(1, 12), 5: range(1, 9)},
                          source=data / 'worldtour/maps', map='E{e}L{n}.MAP', link=[f'worldtour={data / "worldtour"}'],
                          args='-j worldtour -j worldtour/maps'),
        'caribbean': dict(grp=addons / 'DUKE3D.GRP', episodes={3: range(1, 8)}, source=addons / 'vacation.grp',
                          map='VACA{n}.MAP', link=[f'vacation.grp={addons / "vacation.grp"}'], args='-grp vacation.grp'),
        'dc': dict(grp=addons / 'DUKE3D.GRP', episodes={3: range(1, 10)}, source=addons / 'dukedc.grp',
                   map='DUKEDC{n}.MAP', link=[f'dukedc.grp={addons / "dukedc.grp"}'], args='-grp dukedc.grp'),
        'nwinter': dict(grp=addons / 'DUKE3D.GRP', episodes={2: range(1, 9)}, source=addons / 'nwinter.grp',
                        map='E2L{n}.MAP', link=[f'nwinter.grp={addons / "nwinter.grp"}'], args='-grp nwinter.grp -x NWINTER.CON'),
    }


def map_data(source, name):
    if source.is_dir():
        found = [f for f in source.iterdir() if f.name.upper() == name.upper()]
        return found[0].read_bytes() if found else None
    return mp_sweep.grp_file(source, name)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--only', default='worldtour,caribbean,dc,nwinter')
    parser.add_argument('--levels', default='', help='only these level numbers, e.g. 1,3')
    parser.add_argument('--chunk', type=int, default=36)
    parser.add_argument('--limit', type=int, default=0, help='at most this many targets per level (smoke test)')
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--display-base', type=int, default=117)
    parser.add_argument('--port-base', type=int, default=24701)
    args = parser.parse_args()
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    home = work / 'home'
    for sub in ('config', 'data', 'cache'):
        (home / sub).mkdir(parents=True, exist_ok=True)
    report_path = work / 'report.json'
    report = json.loads(report_path.read_text()) if report_path.is_file() else []
    done = {(r['expansion'], r['map'], r['start']) for r in report}
    table = expansions(args.data.resolve())
    wanted = {int(n) for n in args.levels.split(',') if n}

    jobs = []
    for name in args.only.split(','):
        e = table[name]
        for episode, levels in e['episodes'].items():
          for n in levels:
            if wanted and n not in wanted:
                continue
            mapname = e['map'].format(e=episode, n=n)
            data = map_data(e['source'], mapname)
            if data is None:
                continue   # (episodes have different lengths)
            count = len(mp_sweep.targets(*mp_sweep.read_map(data)))
            if args.limit:
                count = min(count, args.limit)
            for start in range(0, count, args.chunk):
                if (name, mapname, start) not in done:
                    jobs.append((name, e, episode, n, mapname, start, min(args.chunk, count - start)))
    print(f'{len(jobs)} chunks to run', flush=True)
    lock = threading.Lock()

    def worker(index):
        display = f':{args.display_base + index}'
        xvfb = subprocess.Popen(['Xvfb', display, '-screen', '0', '1280x1024x24', '-nolisten', 'tcp'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        try:
            while True:
                with lock:
                    if not jobs:
                        return
                    name, e, episode, n, mapname, start, limit = jobs.pop(0)
                run = work / f'{name}-{mapname.lower()}-{start}'
                if run.exists():
                    shutil.rmtree(run)
                env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / 'config'),
                           XDG_DATA_HOME=str(home / 'data'), XDG_CACHE_HOME=str(home / 'cache'))
                command = [sys.executable, str(HERE / 'mp_sweep.py'), '--binary', str(args.binary.resolve()),
                           '--grp', str(e['grp']), '--work-dir', str(run), '--level', f'{episode},{n}',
                           '--map-file', mapname, '--map-source', str(e['source']), f'--game-args={e["args"]}',
                           '--display', display, '--port', str(args.port_base + 10 * index),
                           '--start', str(start), '--limit', str(limit), '--timeout', '570',
                           *[f'--link={item}' for item in e['link']]]
                for attempt in range(2):
                    if run.exists():
                        shutil.rmtree(run)
                    try:
                        out = subprocess.run(command, env=env, capture_output=True, text=True, timeout=700).stdout
                    except subprocess.TimeoutExpired:
                        out = ''
                    try:
                        result = json.loads(out[out.index('{\n "level"'):]) if '{\n "level"' in out else {'error': 'no result', 'tail': out[-400:]}
                    except ValueError:
                        result = {'error': 'unreadable result', 'tail': out[-400:]}
                    # A bot frozen in the software GL driver (llvmpipe under load) is retried once; the
                    # first attempt's stack is kept in the report.
                    if 'stopped answering' not in str(result.get('error', '')) or attempt:
                        break
                    first = result
                result['attempts'] = attempt + 1
                if attempt:
                    result['first_attempt_error'] = first.get('error')
                result.update(expansion=name, map=mapname, start=start)
                with lock:
                    report.append(result)
                    report_path.write_text(json.dumps(report, indent=1))
                if result.get('passed'):
                    shutil.rmtree(run, ignore_errors=True)
                print(f"{name} {mapname}+{start}: used {result.get('used', 0)}/{result.get('targets', '?')} "
                      f"issues {len(result.get('issues', []))} {result.get('error', '')}", flush=True)
        finally:
            xvfb.terminate()
            xvfb.wait()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(args.workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == '__main__':
    main()
