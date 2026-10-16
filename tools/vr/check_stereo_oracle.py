#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare native, two-pass and bounded multiview world pixels/CON counts.

Requires an existing supported desktop GLX display and running OpenXR runtime.
Generated test geometry is original; all art/scripts come from the supplied GRP.
Synthetic fixtures end empty XR frames, never submit synthetic headset views.
"""
import argparse
import array
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from PIL import Image, ImageChops
from stereo_fixture import generate
from smoke_world import CONFIG


COUNTER = re.compile(r'addlog vrfixture_(displayrooms|animatesprites|displayroomsend) = (\d+)')


def run(binary, grp, directory, fixture_con, display, zero_ipd, timeout, native_attachment, single_pass=False, pose="zero", inject_init=False, scene="room", sky_depth=0, sky_panning=1, mask_failure=None):
    directory.mkdir()
    generate(directory, scene)
    shutil.copyfile(fixture_con, directory/'stereo_test.con')
    (directory/'DUKE3D.GRP').symlink_to(grp)
    (directory/'eduke32.cfg').write_text(CONFIG)
    (directory/'autoexec.cfg').write_text(f'r_size 0\nr_projectionhack 0\nr_yshearing 0\nr_flatsky 1\nr_skyzbufferhack {sky_depth}\nr_parallaxskypanning {sky_panning}\n')
    prefix = directory/'world'
    env = dict(os.environ, DISPLAY=display, SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy',
               EDUKE32_XR_TEST_CAPTURE=str(prefix))
    for key in ('EDUKE32_XR', 'EDUKE32_XR_TEST_ZERO_IPD', 'EDUKE32_XR_WORLD_OUTPUT',
                'EDUKE32_XR_DIAGNOSTIC_FRAMES', 'EDUKE32_XR_TEST_FAIL', 'EDUKE32_XR_SINGLE_PASS',
                'EDUKE32_XR_TEST_NATIVE_TARGET', 'EDUKE32_XR_TEST_STEREO_POSE',
                'EDUKE32_XR_TEST_MASK_ARMED', 'EDUKE32_XR_TEST_MASK_SNAPSHOT', 'EDUKE32_XR_TEST_ART_CLOCK'):
        env.pop(key, None)
    if scene == 'masks-animated':
        env['EDUKE32_XR_TEST_ART_CLOCK'] = '1'
    if zero_ipd:
        env['EDUKE32_XR'] = '1'
        env['EDUKE32_XR_TEST_ZERO_IPD' if pose == 'zero' else 'EDUKE32_XR_TEST_STEREO_POSE'] = '2' if pose == 'unequal' else '1'
        if single_pass:
            env['EDUKE32_XR_SINGLE_PASS'] = '1'
            env['EDUKE32_XR_TEST_MASK_SNAPSHOT'] = '1'
            if mask_failure:
                env['EDUKE32_XR_TEST_FAIL'] = 'mask-'+mask_failure
            if inject_init:
                env['EDUKE32_XR_TEST_FAIL'] = 'replay-init'
    elif native_attachment == 'array':
        env['EDUKE32_XR_TEST_NATIVE_TARGET'] = '1'
    command = [str(binary), '-usecwd', '-nosetup', '-noautoload', '-nologo', '-ns', '-nm',
               '-map', 'stereo_fixture.map', '-x', 'stereo_test.con', '-h', 'stereo_fixture.def']
    log_path = directory/'test.log'
    with log_path.open('w') as log:
        process = subprocess.Popen(command, cwd=directory, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic()+timeout
            while time.monotonic() < deadline and process.poll() is None:
                output = log_path.read_text(errors='replace')
                capture = ('XR zero-IPD eyes captured' if pose == 'zero' else 'XR stereo-fixture eyes captured') if zero_ipd else 'XR native reference captured'
                if capture in output and len(COUNTER.findall(output)) >= 3:
                    break
                if 'OpenXR world stopped:' in output or 'OpenXR world initialization failed:' in output:
                    break
                time.sleep(.05)
            output = log_path.read_text(errors='replace')
            counts = {name: int(value) for name, value in COUNTER.findall(output)}
            files = [directory/('world'+suffix+'.ppm') for suffix in
                     (('-left', '-right') if zero_ipd else ('-native',))]
            good = process.poll() is None and len(counts) == 3 and all(p.is_file() for p in files)
            if not zero_ipd and native_attachment == 'array':
                good = good and '(matched texture attachment)' in output
            submissions = re.findall(r'OpenXR opaque single-pass: frame=12 paired=(\d+) eyeOnly=(\d+) pairedVertices=(\d+) eyeOnlyVertices=(\d+) flatSky=(\d+) skyDepth=(\d+) npot=(\d+)', output)
            submission = dict(zip(('paired_calls', 'eye_only_calls', 'paired_vertices', 'eye_only_vertices', 'flat_sky_calls', 'sky_depth_calls', 'npot_calls'),
                                  map(int, submissions[-1]))) if submissions else None
            masks = re.findall(r'OpenXR masks single-pass: frame=12 paired=(\d+) eyeOnly=(\d+) pairedVertices=(\d+) eyeOnlyVertices=(\d+) masks=(\d+) translucent=(\d+) depthOnly=(\d+) depthWriteOff=(\d+)', output)
            mask_submission = dict(zip(('paired_calls', 'eye_only_calls', 'paired_vertices', 'eye_only_vertices',
                                        'mask_calls', 'translucent_calls', 'depth_only_calls', 'depth_write_off_calls'),
                                       map(int, masks[-1]))) if masks else None
            snapshots = [(directory/f'world-mask-{stage}-{eye}{suffix}')
                         for stage in ('before', 'after') for eye in ('left', 'right')
                         for suffix in ('.ppm', '-depth.bin')]
            untouched = (all(p.is_file() for p in snapshots)
                         and all(a.read_bytes() == b.read_bytes() for a, b in zip(snapshots[:4], snapshots[4:])))
            fault_observed = bool(mask_failure and re.search(
                r'OpenXR masks candidate uses two-pass oracle: .*injected.*mask-'+re.escape(mask_failure)+r'.*\(frame=12\)', output))
            return {'captured': good, 'masks_at_capture': mask_submission,
                    'mask_collection_untouched': untouched if single_pass else None, 'mask_fault_observed': fault_observed,
                    'counts': counts, 'single_pass_at_capture': submission,
                    'init_failure_recovered': 'injected opaque replay initialization' in output and submission is not None,
                    'exit_before_cleanup': process.poll()}, files
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--grp', required=True, type=Path)
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--display', default=os.environ.get('DISPLAY'))
    parser.add_argument('--timeout', default=25, type=int)
    parser.add_argument('--native-attachment', choices=('array', 'window'), default='array',
                        help='match XR texture attachment for exact differential pixels (default: array)')
    parser.add_argument('--single-pass', action='store_true', help='also compare bounded opaque multiview against native and two-pass')
    parser.add_argument('--pose', choices=('zero', 'stereo', 'unequal'), default='zero',
                        help='identical eyes, or deterministic nonzero IPD, pitch/yaw/roll and asymmetric FOV')
    parser.add_argument('--inject-replay-init-failure', action='store_true')
    parser.add_argument('--mask-failure', choices=('collect-right', 'replay-before'))
    parser.add_argument('--scene', choices=('room', 'sky', 'sky-floor', 'masks', 'masks-animated'), default='room')
    parser.add_argument('--sky-depth', choices=(0, 1), type=int, default=0, help='native sky depth-only companion pass')
    parser.add_argument('--sky-panning', choices=(0, 1), type=int, default=1)
    args = parser.parse_args()
    if args.mask_failure and (not args.single_pass or args.inject_replay_init_failure):
        parser.error('--mask-failure requires --single-pass and cannot combine with opaque init failure')
    if args.inject_replay_init_failure and not args.single_pass:
        parser.error('--inject-replay-init-failure requires --single-pass')
    binary, grp = args.binary.resolve(), args.grp.resolve()
    if not binary.is_file() or not grp.is_file() or not args.display:
        parser.error('existing XR-enabled binary, owned GRP and display are required')
    args.work_dir.mkdir(parents=True, exist_ok=True)
    lab = Path(tempfile.mkdtemp(prefix='stereo-diff-', dir=args.work_dir.resolve()))
    fixture_con = Path(__file__).resolve().parent/'fixtures/stereo_test.con'
    native, reference = run(binary, grp, lab/'native', fixture_con, args.display, False, args.timeout, args.native_attachment, pose=args.pose, scene=args.scene, sky_depth=args.sky_depth, sky_panning=args.sky_panning)
    oracle, oracle_eyes = run(binary, grp, lab/'oracle', fixture_con, args.display, True, args.timeout, args.native_attachment, pose=args.pose, scene=args.scene, sky_depth=args.sky_depth, sky_panning=args.sky_panning)
    if args.single_pass:
        stereo, eyes = run(binary, grp, lab/'single-pass', fixture_con, args.display, True, args.timeout, args.native_attachment, True, args.pose, args.inject_replay_init_failure, args.scene, args.sky_depth, args.sky_panning, args.mask_failure)
    else:
        stereo, eyes = oracle, oracle_eyes
    pixel_results = []
    if native['captured'] and oracle['captured'] and stereo['captured']:
        for index, path in enumerate(eyes):
            target = Image.open(reference[0] if args.pose == 'zero' else oracle_eyes[index]).convert('RGB')
            image = Image.open(path).convert('RGB')
            if image.size != target.size:
                pixel_results.append({'size_equal': False, 'exact': False})
                continue
            delta = ImageChops.difference(target, image)
            data = delta.tobytes()
            pixel_results.append({'size_equal': True, 'exact': delta.getbbox() is None,
                                  'changed_pixels': sum(any(data[i:i+3]) for i in range(0,len(data),3)),
                                  'maximum_channel_error': max(data)})
    depth_results = []
    if native['captured'] and oracle['captured'] and stereo['captured']:
        for index, path in enumerate(eyes):
            target = reference[0] if args.pose == 'zero' else oracle_eyes[index]
            depth = path.with_name(path.stem+'-depth.bin')
            target_depth = target.with_name(target.stem+'-depth.bin')
            oracle_depth = oracle_eyes[index].with_name(oracle_eyes[index].stem+'-depth.bin')
            expected = Image.open(path).width * Image.open(path).height * 4
            complete = all(p.is_file() and p.stat().st_size == expected for p in (depth, target_depth, oracle_depth))
            samples = array.array('I')
            if complete:
                samples.frombytes(depth.read_bytes())
            depth_results.append({'complete': complete, 'nontrivial': complete and min(samples) != max(samples),
                                  'exact_reference': complete and depth.read_bytes() == target_depth.read_bytes(),
                                  'exact_two_pass': complete and depth.read_bytes() == oracle_depth.read_bytes()})
    depth_good = len(depth_results) == 2 and all(d['exact_reference'] and d['exact_two_pass'] and d['nontrivial'] for d in depth_results)
    counts_equal = stereo['counts'] == oracle['counts'] and bool(oracle['counts'])
    if args.pose == 'zero':
        counts_equal = counts_equal and native['counts'] == stereo['counts']
    oracle_equal = oracle['captured'] and stereo['captured'] and all(
        a.read_bytes() == b.read_bytes() for a, b in zip(oracle_eyes, eyes))
    submission = stereo['single_pass_at_capture']
    promoted = not args.single_pass or bool(submission and submission['eye_only_calls' if args.pose == 'unequal' else 'paired_calls'] > 0)
    distinct = stereo['captured'] and eyes[0].read_bytes() != eyes[1].read_bytes()
    pose_good = args.pose == 'zero' or distinct
    sky_good = (not args.single_pass or args.scene not in ('sky', 'sky-floor') or bool(submission
                and submission['flat_sky_calls'] > 0 and (not args.sky_depth or submission['sky_depth_calls'] > 0)))
    masks = stereo['masks_at_capture']
    masks_good = (not args.single_pass or bool(masks and masks['paired_calls'] + masks['eye_only_calls'] > 0))
    if args.single_pass and args.scene.startswith('masks'):
        masks_good = bool(masks and masks['translucent_calls'] > 0 and masks['depth_only_calls'] > 0
                          and masks['depth_write_off_calls'] > 0)
    if args.mask_failure:
        masks_good = stereo['mask_fault_observed'] and masks is None
    untouched = not args.single_pass or stereo['mask_collection_untouched']
    recovered = not args.inject_replay_init_failure or stereo['init_failure_recovered']
    passed = (masks_good and untouched and sky_good and depth_good and recovered and pose_good and native['captured'] and stereo['captured'] and counts_equal and oracle_equal and promoted
              and len(pixel_results) == 2 and all(p['exact'] for p in pixel_results))
    result = {'stereo_differential_passed': passed,
              'zero_ipd_native_equivalence': passed if args.pose == 'zero' else None,
              'pose': args.pose, 'scene': args.scene, 'sky_depth': args.sky_depth, 'sky_panning': args.sky_panning, 'depth': depth_results, 'eyes_distinct': distinct, 'native': native, 'stereo': stereo,
              'counts_equal': counts_equal, 'eye_pixels': pixel_results,
              'native_attachment': args.native_attachment, 'pixel_reference': 'native' if args.pose == 'zero' else 'two-pass', 'oracle': oracle,
              'two_pass_pixels_equal': oracle_equal, 'single_pass_requested': args.single_pass,
              'replayed_at_capture': promoted if args.single_pass else None,
              'init_failure_injected': args.inject_replay_init_failure,
              'mask_failure_injected': args.mask_failure,
              'art_animation_test_clock': 1 if args.scene == 'masks-animated' else None,
              'mask_replayed_at_capture': bool(masks),
              'mask_collection_zero_color_depth_writes': untouched,
              'projection_submission': 'none: synthetic offscreen fixture', 'evidence_directory': str(lab)}
    (lab/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
