#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""The Windows release in VR under Wine: play.bat vr, through Proton's wineopenxr, on the lab's Monado.

Run inside tools/vr/software_xr_lab.py (all paths absolute):

  smoke_wine_xr.py --wine GE_PROTON/files --release EDuke-VR --grp DUKE3D.GRP --helper xr_init_registry.exe --work-dir DIR

EDuke-VR is an extracted Windows release archive. A throwaway prefix is made in DIR; the helper
(tools/vr/wine/xr_init_registry.c) does what Proton's steam.exe does for VR games (wineopenxr fills
the registry), then play.bat vr starts the game, which must open an OpenXR session, render world
frames and capture both eyes.

Known limit (GE-Proton 11): wineopenxr forwards D3D11/D3D12/Vulkan sessions only. An OpenGL game's
XrGraphicsBindingOpenGLWin32KHR is dropped, so xrCreateSession fails with
XR_ERROR_GRAPHICS_DEVICE_INVALID after the instance, system and view configuration succeed.
"""
import argparse, json, os, re, shutil, subprocess, time
from pathlib import Path


def winpath(path):
    return 'Z:' + str(path).replace('/', '\\')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--wine', required=True, type=Path, help="a Proton build's files/ folder (bin/wine, lib/wine)")
    parser.add_argument('--release', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--helper', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--timeout', type=int, default=500)
    args = parser.parse_args()
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.timeout
    wine = str(args.wine / 'bin/wine')
    env = dict(os.environ, WINEPREFIX=str(work / 'prefix'), WINEARCH='win64', WINEDEBUG='-all',
               WINEDLLOVERRIDES='mscoree,mshtml=;winemenubuilder.exe=d')
    result = {'passed': False, 'checks': {}}
    log_path = work / 'wine.log'
    log = log_path.open('w')

    def step(name, command, timeout, **kw):
        log.write(f'== {name}: {command}\n'); log.flush()
        run = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout, **kw)
        log.flush()
        return run.returncode

    try:
        result['wineboot'] = step('wineboot', [wine, 'wineboot', '-i'], 300)
        # As Proton does: DXVK's dxgi/d3d11 (wineopenxr imports dxgi).
        system32 = work / 'prefix/drive_c/windows/system32'
        for name in ('dxgi.dll', 'd3d11.dll'):
            shutil.copy2(args.wine / 'lib/wine/dxvk/x86_64-windows' / name, system32 / name)
        env['WINEDLLOVERRIDES'] += ';dxgi,d3d11=n'
        result['init_registry'] = step('init registry', [wine, str(args.helper)], 60)
        query = subprocess.run([wine, 'reg', 'query', r'HKLM\Software\Khronos\OpenXR\1'], env=env,
                               capture_output=True, text=True, timeout=60)
        result['active_runtime'] = query.stdout.strip()[-300:]
        # Proton puts the runtime manifest at C:\openxr (the registry points there).
        target = work / 'prefix/drive_c/openxr'
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.wine / 'share/openxr/wineopenxr64.json', target / 'wineopenxr64.json')
        if 'ActiveRuntime' not in query.stdout:
            step('active runtime', [wine, 'reg', 'add', r'HKLM\Software\Khronos\OpenXR\1', '/v', 'ActiveRuntime',
                                    '/t', 'REG_SZ', '/d', r'C:\openxr\wineopenxr64.json', '/f'], 60)
        release = work / 'EDuke-VR'   # a writable copy (the game writes its config and log beside it)
        if not release.exists():
            shutil.copytree(args.release, release, symlinks=True)
        args.release = release
        grp = args.release / 'data/grp/DUKE3D.GRP'
        if not grp.exists():
            grp.symlink_to(args.grp.resolve())
        request = work / 'capture-request'
        game_env = dict(env, EDUKE32_XR_CAPTURE_REQUEST=winpath(request), XR_LOADER_DEBUG='error')
        game_log = (work / 'game.log').open('w')
        game = subprocess.Popen([wine, 'cmd', '/c', 'play.bat', 'vr'], cwd=args.release, env=game_env,
                                stdout=game_log, stderr=subprocess.STDOUT)

        def logs():
            text = ''
            for path in list(args.release.rglob('eduke32.log')) + list((work / 'prefix/drive_c/users').rglob('eduke32.log')) + [work / 'game.log']:
                try: text += path.read_text(errors='replace')
                except OSError: pass
            return text

        def until(predicate, limit):
            end = min(deadline, time.monotonic() + limit)
            while time.monotonic() < end:
                if predicate(): return True
                if game.poll() is not None: return predicate()
                time.sleep(1)
            return False

        result['checks']['OpenXR world frames'] = until(lambda: 'OpenXR world scale' in logs()
                                                       or 'OpenXR world initialization failed' in logs(), 300) \
            and 'OpenXR world initialization failed' not in logs()
        time.sleep(5)
        stem = work / 'vr'
        request.write_text(winpath(stem) + '\n')
        result['checks']['eyes captured'] = until(lambda: (work / 'vr-left.ppm').is_file() and (work / 'vr-right.ppm').is_file(), 120)
        result['checks']['game still running'] = game.poll() is None
        text = logs()
        result['openxr_lines'] = sorted(set(re.findall(r'OpenXR (?:resolution|runtime|system|session|world|capture request)[^\n]{0,160}', text)))[:12]
        result['errors'] = [l for l in text.splitlines() if re.search(r'(?i)error|failed', l)][:12]
        result['captures'] = sorted(str(p) for p in work.glob('vr-*.ppm'))
    except subprocess.TimeoutExpired as error:
        result['error'] = f'timeout: {error.cmd}'
    finally:
        subprocess.run([str(args.wine / 'bin/wineserver'), '-k'], env=env, timeout=60)
        log.close()
    result['passed'] = bool(result['checks']) and all(result['checks'].values())
    print(json.dumps(result, indent=1))


if __name__ == '__main__':
    main()
