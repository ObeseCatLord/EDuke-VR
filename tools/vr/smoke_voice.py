#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Voice chat end to end: dedicated co-op server, flat talker, VR listener.

Run under software_xr_lab.py. The talker's microphone is replaced by a
synthetic tone (EDUKE32_VOICE_TEST_TONE, voice activation gates it on and
off); the VR listener dumps the PCM it decodes (EDUKE32_VOICE_TEST_DUMP) and
logs its stereo gains. Checks the server relay, Opus
decode (dominant frequency of the received audio) and that the gains follow
the listener's tracked head: facing the talker is balanced, turning so the
talker is on the left favours the left channel and vice versa.
"""
import argparse, json, math, os, re, subprocess, tempfile, time
from pathlib import Path
import numpy as np
from monado_remote import Remote
from smoke_actions import Observer
from smoke_aim import orientation
from smoke_multiplayer import X11, setup_lab
from smoke_xr_coop import CON, LEVEL, WHERE, level_map

GAINS = re.compile(r'Voice playback: speaker=(\d+) left=(\d+) right=(\d+) ')
TONE = 440.0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--display', default=':105')
    parser.add_argument('--remote-port', type=int, default=49777)
    parser.add_argument('--port', type=int, default=24631)
    parser.add_argument('--timeout', type=int, default=560)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='voice-', dir=args.work_dir.resolve()))
    labs = {role: setup_lab(root, role, args.grp.resolve(), False) for role in ('server', 'talker', 'xr')}
    for role, lab in labs.items():
        (lab / 'first.map').write_bytes(level_map(True))
        (lab / 'second.map').write_bytes(level_map(False))
        (lab / 'coop_vr.con').write_text(CON)
        (lab / 'autoexec.cfg').write_text('voice_transmit 1\nvoice_mode 0\n' if role == 'talker' else 'voice_transmit 0\n')
        with (lab / 'eduke32.cfg').open('a') as f:
            f.write('\n[Comm Setup]\nPlayerName = "' + {'server': 'Server', 'talker': 'Talker', 'xr': 'VR'}[role] + '"\n')
    base = {k: v for k, v in os.environ.items() if not k.startswith(('EDUKE32_XR', 'EDUKE32_VOICE'))}
    base.update(DISPLAY=args.display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy')
    native = {k: v for k, v in base.items() if not k.startswith('XR_')}
    talker_env = dict(native, EDUKE32_VOICE_TEST_TONE=f'{TONE:.0f}:700:500')
    console = labs['xr'] / 'console-request'
    dump = labs['xr'] / 'voice'
    xr_env = dict(base, EDUKE32_XR='play', EDUKE32_XR_CONSOLE_REQUEST=str(console), EDUKE32_VOICE_TEST_DUMP=str(dump),
                  XDG_DATA_HOME=str(labs['xr'] / 'data'))
    launcher = Path(__file__).resolve().parents[2] / 'package/vr/eduke32-vr-play'
    common = ['-usecwd', '-nosetup', '-noautoload', '-nologo', '-ns', '-x', 'coop_vr.con']
    processes, logs = [], []
    deadline = time.monotonic() + args.timeout
    result = {'passed': False, 'evidence_directory': str(root), 'phase': 'setup'}
    checks = result['checks'] = {}

    def launch(role, command, env):
        log = (labs[role] / 'game.log').open('w'); logs.append(log)
        process = subprocess.Popen(command, cwd=labs[role], env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        processes.append(process)
        return process, Observer(process, labs[role] / 'game.log')

    def until(observer, predicate, seconds):
        observer.wait(predicate, timeout=max(1, min(seconds, deadline - time.monotonic())))

    try:
        binary = str(args.binary.resolve())
        server, so = launch('server', [binary, *common, '-nm', '-dedicated', '-port', str(args.port), '-c2', '-v1', '-l1'], native)
        until(so, lambda t: 'Multiplayer server initialized.' in t, 30)
        until(so, lambda t: LEVEL.search(t) is not None, 30)
        so.pause(3)
        x11 = X11(args.display)
        result['phase'] = 'talker join'
        talker, to = launch('talker', [binary, *common, '-nm', '-connect', f'127.0.0.1:{args.port}'], talker_env)
        until(to, lambda t: 'Multiplayer client level synchronization complete.' in t, 60)
        to.pause(2)
        window, _ = x11.owned_window(talker.pid)
        if window:
            x11.press(window, 'Escape', .06, True)
        with Remote(args.remote_port) as remote:
            head = remote.packet.head
            result['phase'] = 'XR join'
            xr, co = launch('xr', [str(launcher), '--binary', binary, '--', *common, '-connect', f'127.0.0.1:{args.port}'], xr_env)
            until(co, lambda t: 'Multiplayer client level synchronization complete.' in t, 120)
            until(co, lambda t: 'OpenXR world oracle: 60 frames' in t, 240)
            co.pause(2)
            result['phase'] = 'positions'
            start = len(co.text())
            console.write_text('xr_where\n')
            until(co, lambda t: len(WHERE.findall(t[start:])) >= 3, 60)
            rows = {int(m[0]): list(map(int, m)) for m in WHERE.findall(co.text()[start:])}
            me = next(r for r in rows.values() if r[1])
            talker_row = next(r for i, r in rows.items() if i not in (0, me[0]))
            speaker = talker_row[0]
            facing = math.degrees(math.remainder(math.atan2(talker_row[8] - me[8], talker_row[7] - me[7]) - me[5] * math.pi / 1024, 2 * math.pi))
            result['talker'] = speaker
            result['phase'] = 'receive'
            until(co, lambda t: any(int(m[0]) == speaker for m in GAINS.findall(t)), 60)
            gains = {}
            for label, yaw in (('facing', facing), ('talker_left', facing + 90), ('talker_right', facing - 90)):
                head.center.orientation = orientation(yaw, 0); remote.send()
                co.pause(1.5)
                offset = len(co.text())
                until(co, lambda t: any(int(m[0]) == speaker for m in GAINS.findall(t[offset:])), 20)
                rows_ = [list(map(int, m)) for m in GAINS.findall(co.text()[offset:]) if int(m[0]) == speaker]
                gains[label] = rows_[-1][1:]
            result['gains'] = gains
            co.pause(2)
        pcm_path = labs['xr'] / f'voice-speaker-{speaker}.s16'
        pcm = np.fromfile(pcm_path, dtype='<i2') if pcm_path.is_file() else np.zeros(0, dtype='<i2')
        result['decoded_seconds'] = round(len(pcm) / 48000, 2)
        loud = pcm[np.abs(pcm.astype(int)) > 1000]
        if len(pcm) > 48000:
            chunk = pcm[-48000:].astype(float)
            spectrum = np.abs(np.fft.rfft(chunk * np.hanning(len(chunk))))
            result['dominant_hz'] = float(np.argmax(spectrum[20:]) + 20) * 48000 / len(chunk)
        checks['decoded_audio'] = len(pcm) > 48000 and len(loud) > 4800
        checks['tone_frequency'] = abs(result.get('dominant_hz', 0) - TONE) < 15
        f, l, r = gains.get('facing', [0, 0]), gains.get('talker_left', [0, 0]), gains.get('talker_right', [0, 0])
        checks['facing_balanced'] = abs(f[0] - f[1]) <= max(3, 0.1 * max(f))
        checks['left_when_talker_left'] = l[0] > l[1]
        checks['right_when_talker_right'] = r[1] > r[0]
        checks['all_alive'] = all(p.poll() is None for p in processes)
        result['phase'] = 'complete'
        result['passed'] = all(checks.values())
    except RuntimeError as error:
        result['error'] = str(error)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
        for log in logs:
            log.close()
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
