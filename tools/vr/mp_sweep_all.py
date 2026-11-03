#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Runs tools/vr/mp_sweep.py over many levels, in chunks of targets, one private lab at a time.

  mp_sweep_all.py --binary eduke32-xr --grp DUKE3D.GRP --work-dir work/sweep [--levels 1,1 1,2 ...] [--chunk 36]

Writes WORK/report.json as it goes (one entry per chunk, with the sweep's issues). A chunk's lab
directory is deleted when it found nothing, and kept as evidence when it did.
"""
import argparse, json, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mp_sweep  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--levels', nargs='*', default=[f'{e},{l}' for e in range(1, 5) for l in range(1, 12)])
    parser.add_argument('--chunk', type=int, default=36)
    args = parser.parse_args()
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    report_path = work / 'report.json'
    report = json.loads(report_path.read_text()) if report_path.is_file() else []
    done = {(r['level'], r['start']) for r in report}
    for level in args.levels:
        episode, number = map(int, level.split(','))
        data = mp_sweep.grp_file(args.grp, f'E{episode}L{number}.MAP')
        if data is None:
            continue
        count = len(mp_sweep.targets(*mp_sweep.read_map(data)))
        for start in range(0, count, args.chunk):
            name = f'E{episode}L{number}'
            if (name, start) in done:
                continue
            run = work / f'{name.lower()}-{start}'
            if run.exists():
                shutil.rmtree(run)
            subprocess.run([sys.executable, str(HERE / 'software_xr_lab.py'), '--deps', str(HERE.parents[1] / 'work/software-xr/deps'),
                            '--work-dir', str(run), '--child-timeout', '590', '--', '/usr/bin/python3', str(HERE / 'mp_sweep.py'),
                            '--binary', str(args.binary.resolve()), '--grp', str(args.grp), '--work-dir', str(run / 'out'),
                            '--level', level, '--start', str(start), '--limit', str(args.chunk), '--timeout', '570'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=700)
            log = run / 'child.log'
            text = log.read_text(errors='replace') if log.is_file() else ''
            try:
                result = json.loads(text[text.index('{\n "level"'):]) if '{\n "level"' in text else {'level': name, 'error': 'no result'}
            except ValueError:
                result = {'level': name, 'error': 'unreadable result'}
            result.setdefault('level', name)
            result['start'] = start
            report.append(result)
            report_path.write_text(json.dumps(report, indent=1))
            if result.get('passed'):
                shutil.rmtree(run, ignore_errors=True)
            print(f"{name}+{start}: used {result.get('used', 0)}/{result.get('targets', '?')} "
                  f"issues {len(result.get('issues', []))} {result.get('error', '')}", flush=True)


if __name__ == '__main__':
    main()
