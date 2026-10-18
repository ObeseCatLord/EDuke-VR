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
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import time
from PIL import Image, ImageChops
from stereo_fixture import generate, sprite
from smoke_world import CONFIG


COUNTER = re.compile(r'addlog vrfixture_(displayrooms|animatesprites|displayroomsend) = (\d+)')
OPAQUE_SUBMISSION = re.compile(
    r'OpenXR opaque single-pass: frame=12 paired=(\d+) eyeOnly=(\d+) '
    r'pairedVertices=(\d+) eyeOnlyVertices=(\d+) flatSky=(\d+) skyDepth=(\d+) npot=(\d+) '
    r'skybox=(\d+) skyboxPaired=(\d+)')


def skybox_assets_root(root: Path) -> Path:
    """Resolve an owned AA install root or its ``skyboxes`` directory."""
    root = root.resolve()
    assets = root / 'skyboxes' if (root / 'skyboxes').is_dir() else root
    # AA's owned Duke tile-89 set supplies five direction files.  As in its
    # historical tile-89 DEF, the north face also supplies the remaining side.
    faces = ('0089_top.png', '0089_bottom.png', '0089_north.png', '0089_east.png',
             '0089_south.png')
    missing = [assets / 'duke3d' / name for name in faces if not (assets / 'duke3d' / name).is_file()]
    if missing:
        raise ValueError('--skybox-root must contain owned skyboxes/duke3d/0089_{top,bottom,north,east,south}.png')
    return assets


def append_skybox_def(directory: Path, assets: Path, non_sky_rgba=False, include_skybox=True) -> None:
    """Link owned faces into a disposable fixture and define native tile 89.

    No installed AA asset is copied or modified.  The second palette record is
    intentional: Build's ceilingpal/floorpal reaches high-tile lookup even
    though these PNG sky faces stay truecolor (u_usePalette remains disabled).
    """
    link = directory / 'skybox_assets'
    link.symlink_to(assets, target_is_directory=True)
    faces = '''top "skybox_assets/duke3d/0089_top.png" nocompress nodownsize
down "skybox_assets/duke3d/0089_bottom.png" nocompress nodownsize
front "skybox_assets/duke3d/0089_north.png" nocompress nodownsize
right "skybox_assets/duke3d/0089_east.png" nocompress nodownsize
back "skybox_assets/duke3d/0089_south.png" nocompress nodownsize
left "skybox_assets/duke3d/0089_north.png" nocompress nodownsize'''
    definitions = (''.join(f'\nskybox {{\n tile 89 pal {palette}\n{faces}\n}}\n'
                           for palette in (0, 1)) if include_skybox else '')
    if non_sky_rgba:
        # This wall remains an ordinary truecolor replacement.  It must keep
        # the native two-pass route; do not obtain sky admission by disabling
        # the AA artwork that made the original fallback meaningful.
        definitions += ('\ntexture 293 { pal 0 { file "skybox_assets/duke3d/0089_north.png" '
                        'nocompress nodownsize } }\n')
    with (directory / 'stereo_fixture.def').open('a') as defs:
        defs.write(definitions)


def compare_eyes(expected, actual):
    """Return strict RGB and raw-depth parity for a same-pose eye pair."""
    pixels, depth = [], []
    for target_path, image_path in zip(expected, actual):
        target, image = Image.open(target_path).convert('RGB'), Image.open(image_path).convert('RGB')
        if target.size != image.size:
            pixels.append({'size_equal': False, 'exact': False})
            depth.append({'complete': False, 'nontrivial': False, 'exact': False})
            continue
        delta = ImageChops.difference(target, image)
        data = delta.tobytes()
        pixels.append({'size_equal': True, 'exact': delta.getbbox() is None,
                       'changed_pixels': sum(any(data[i:i+3]) for i in range(0, len(data), 3)),
                       'maximum_channel_error': max(data)})
        expected_depth = target_path.with_name(target_path.stem + '-depth.bin')
        image_depth = image_path.with_name(image_path.stem + '-depth.bin')
        complete = (expected_depth.is_file() and image_depth.is_file()
                    and expected_depth.stat().st_size == target.width * target.height * 4
                    and image_depth.stat().st_size == target.width * target.height * 4)
        samples = array.array('I')
        if complete:
            samples.frombytes(image_depth.read_bytes())
        depth.append({'complete': complete, 'nontrivial': complete and min(samples) != max(samples),
                      'exact': complete and expected_depth.read_bytes() == image_depth.read_bytes()})
    exact = (len(pixels) == 2 and all(item['exact'] for item in pixels)
             and len(depth) == 2 and all(item['complete'] and item['nontrivial'] and item['exact'] for item in depth))
    return {'exact': exact, 'pixels': pixels, 'depth': depth}


def native_sky_mask(replacement: Path, art_control: Path):
    """Identify sky pixels from an otherwise identical native ART control."""
    with Image.open(replacement).convert('RGB') as sky, Image.open(art_control).convert('RGB') as art:
        if sky.size != art.size:
            return None
        delta = ImageChops.difference(sky, art).tobytes()
    return bytes(any(delta[offset:offset+3]) for offset in range(0, len(delta), 3))


def native_fog_delta(reference: Path, control: Path, sky_mask):
    """Measure native visibility-only changes inside the sky-only pixel mask."""
    before, after = Image.open(reference).convert('RGB'), Image.open(control).convert('RGB')
    if before.size != after.size or sky_mask is None or len(sky_mask) != before.width * before.height:
        return {'size_equal': False, 'sky_pixels': 0, 'changed_pixels': 0, 'visible_unsaturated_pixels': 0, 'proved': False}
    source, changed = before.tobytes(), ImageChops.difference(before, after).tobytes()
    sky_pixels = changed_pixels = visible_unsaturated = 0
    for pixel, offset in enumerate(range(0, len(changed), 3)):
        if not sky_mask[pixel]:
            continue
        sky_pixels += 1
        if any(changed[offset:offset+3]):
            changed_pixels += 1
            # Require a contribution that is visible without merely detecting
            # clipped black/white pixels at the sky seam.
            if all(2 < channel < 253 for channel in source[offset:offset+3]):
                visible_unsaturated += 1
    return {'size_equal': True, 'sky_pixels': sky_pixels, 'changed_pixels': changed_pixels,
            'visible_unsaturated_pixels': visible_unsaturated,
            'proved': sky_pixels > 25 and changed_pixels > 25 and visible_unsaturated > 25}


def skybox_fog_fault_evidence(captured, comparison, expected, actual, sky_mask):
    """Accept the fault only as a visible sky-color error with unchanged depth.

    Missing captures, depth-only errors and RGB changes outside the independently
    identified native sky region are failed experiments, not proof of fog use.
    The fault case uses zero IPD, so the native sky mask applies to both eyes.
    """
    complete = bool(captured and len(expected) == 2 and len(actual) == 2
                    and len(comparison['pixels']) == 2 and len(comparison['depth']) == 2
                    and all(item['size_equal'] for item in comparison['pixels'])
                    and all(item['complete'] and item['nontrivial'] and item['exact']
                            for item in comparison['depth']))
    effects = ([native_fog_delta(reference, fault, sky_mask)
                for reference, fault in zip(expected, actual)] if complete else [])
    return {'captured': captured, 'complete_unchanged_depth': complete,
            'sky_color_effects': effects,
            'proved': complete and len(effects) == 2 and all(item['proved'] for item in effects)}


def run(binary, grp, directory, fixture_con, display, zero_ipd, timeout, native_attachment, single_pass=False, pose="zero", inject_init=False, scene="room", sky_depth=0, sky_panning=1, mask_failure=None, model_root=None, model_name="pistol", model_scale=1.0, models_enabled=True, model_skin=True, skybox_root=None, non_sky_rgba=False, skybox_fog_fault=False, include_skybox_def=True):
    directory.mkdir()
    generate(directory, scene)
    shutil.copyfile(fixture_con, directory/'stereo_test.con')
    if skybox_root:
        append_skybox_def(directory, skybox_root, non_sky_rgba, include_skybox_def)
    (directory/'DUKE3D.GRP').symlink_to(grp)
    (directory/'eduke32.cfg').write_text(CONFIG)
    (directory/'autoexec.cfg').write_text(f'r_size 0\nr_projectionhack 0\nr_yshearing 0\nr_flatsky 1\nr_skyzbufferhack {sky_depth}\nr_parallaxskypanning {sky_panning}\n')
    if model_root:
        # Keep the actual mesh clearly in view rather than accepting equality
        # when a tiny pickup is hidden at the distant portal's floor edge.
        map_path = directory/'stereo_fixture.map'
        data = map_path.read_bytes()
        map_path.write_bytes(data[:-44] + sprite(2300,2048,-8192,0,tile=954,angle=512,xrepeat=64,yrepeat=64))
        (directory/'duke_assets').symlink_to(model_root/'duke_assets', target_is_directory=True)
        model = (model_root/'duke_assets'/f'{model_name}.md3').read_bytes()
        if len(model) < 108 or model[:8] != b'IDP3\x0f\0\0\0':
            raise ValueError('model fixture requires a native MD3 v15 export')
        surfaces = struct.unpack_from('<i', model, 84)[0]
        if not 1 <= surfaces <= 32:
            raise ValueError('model fixture surface count is outside its bounded range')
        with (directory/'stereo_fixture.def').open('a') as defs:
            defs.write(f'\nmodel "duke_assets/{model_name}.md3"\n{{\n scale {model_scale}\n')
            if model_skin:
                for surface in range(surfaces):
                    defs.write(f' skin {{ pal 0 surface {surface} file "duke_assets/{model_name}.png" }}\n')
            defs.write(' frame { name "rest" tile 954 }\n}\n')
        with (directory/'autoexec.cfg').open('a') as cfg:
            cfg.write(f'r_models {int(models_enabled)}\n')
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
            if skybox_fog_fault:
                env['EDUKE32_XR_TEST_FAIL'] = 'skybox-fog-upload'
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
            submissions = OPAQUE_SUBMISSION.findall(output)
            submission = dict(zip(('paired_calls', 'eye_only_calls', 'paired_vertices', 'eye_only_vertices', 'flat_sky_calls', 'sky_depth_calls', 'npot_calls', 'skybox_calls', 'skybox_paired_calls'),
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
            model_fallback = bool(re.search(r'OpenXR masks candidate uses two-pass oracle: .*model.*\(frame=12\)', output))
            opaque_fallback = bool(re.search(r'OpenXR opaque candidate uses two-pass oracle: .*\(frame=12\)', output))
            return {'captured': good, 'masks_at_capture': mask_submission,
                    'native_model_fallback_at_capture': model_fallback,
                    'mask_collection_untouched': untouched if single_pass else None, 'mask_fault_observed': fault_observed,
                    'counts': counts, 'single_pass_at_capture': submission,
                    'opaque_fallback_at_capture': opaque_fallback,
                    'skybox_fog_fault_observed': 'XR skybox fog upload intentionally skipped.' in output,
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
    parser.add_argument('--scene', choices=('room', 'sky', 'sky-floor', 'skybox',
                                             'skybox-ceiling-fog-control', 'skybox-floor-fog-control',
                                             'masks', 'masks-animated'), default='room')
    parser.add_argument('--sky-depth', choices=(0, 1), type=int, default=0, help='native sky depth-only companion pass')
    parser.add_argument('--sky-panning', choices=(0, 1), type=int, default=1)
    parser.add_argument('--skybox-root', type=Path,
                        help='owned AA install root (or its skyboxes directory); runs the tile-89 native skybox fog matrix')
    parser.add_argument('--model-root', type=Path, help='private export root containing duke_assets/*.md3 and PNG; never copied into the repository')
    parser.add_argument('--model-name', default='pistol', choices=('duke','pistol','shotgun','chaingun','rpg','pipebomb','detonator','shrinker','expander','devastator','tripmine','freezer','kick','flamethrower'))
    parser.add_argument('--model-scale', type=float, default=.5859375, help='native DEF scale for 64-repeat fixture and 64 model units/metre')
    args = parser.parse_args()
    if args.mask_failure and (not args.single_pass or args.inject_replay_init_failure):
        parser.error('--mask-failure requires --single-pass and cannot combine with opaque init failure')
    if args.inject_replay_init_failure and not args.single_pass:
        parser.error('--inject-replay-init-failure requires --single-pass')
    if args.skybox_root:
        if args.scene != 'room' or args.mask_failure or args.inject_replay_init_failure or args.model_root:
            parser.error('--skybox-root owns its skybox scenes and cannot combine with scene, model, or unrelated fault options')
        args.skybox_root = skybox_assets_root(args.skybox_root)
        args.scene, args.pose, args.sky_depth, args.sky_panning, args.single_pass = 'skybox', 'zero', 0, 1, True
    binary, grp = args.binary.resolve(), args.grp.resolve()
    if not math.isfinite(args.model_scale) or not 0 < args.model_scale <= 1000:
        parser.error('--model-scale must be finite and in 0..1000')
    model_options = {}
    if args.model_root:
        args.model_root = args.model_root.resolve()
        if args.scene != 'room' or args.mask_failure:
            parser.error('model proof requires the ordinary room without injected mask failures')
        if any(not (args.model_root/'duke_assets'/f'{args.model_name}.{ext}').is_file() for ext in ('md3','png')):
            parser.error('model root must contain the requested MD3 and PNG')
        model_options = dict(model_root=args.model_root, model_name=args.model_name, model_scale=args.model_scale)
    fixture_options = dict(model_options)
    if args.skybox_root:
        fixture_options['skybox_root'] = args.skybox_root
    if not binary.is_file() or not grp.is_file() or not args.display:
        parser.error('existing XR-enabled binary, owned GRP and display are required')
    args.work_dir.mkdir(parents=True, exist_ok=True)
    lab = Path(tempfile.mkdtemp(prefix='stereo-diff-', dir=args.work_dir.resolve()))
    fixture_con = Path(__file__).resolve().parent/'fixtures/stereo_test.con'
    native, reference = run(binary, grp, lab/'native', fixture_con, args.display, False, args.timeout, args.native_attachment, pose=args.pose, scene=args.scene, sky_depth=args.sky_depth, sky_panning=args.sky_panning, **fixture_options)
    oracle, oracle_eyes = run(binary, grp, lab/'oracle', fixture_con, args.display, True, args.timeout, args.native_attachment, pose=args.pose, scene=args.scene, sky_depth=args.sky_depth, sky_panning=args.sky_panning, **fixture_options)
    if args.single_pass:
        stereo, eyes = run(binary, grp, lab/'single-pass', fixture_con, args.display, True, args.timeout, args.native_attachment, True, args.pose, args.inject_replay_init_failure, args.scene, args.sky_depth, args.sky_panning, args.mask_failure, **fixture_options)
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
    model_reference = None
    if args.model_root:
        control, control_files = run(binary, grp, lab/'native-art-control', fixture_con, args.display, False,
                                     args.timeout, args.native_attachment, pose=args.pose, models_enabled=False, **fixture_options)
        changed = control['captured'] and native['captured'] and ImageChops.difference(
            Image.open(reference[0]).convert('RGB'), Image.open(control_files[0]).convert('RGB')).getbbox() is not None
        empty, empty_files = run(binary, grp, lab/'native-no-skin-control', fixture_con, args.display, False,
                                 args.timeout, args.native_attachment, pose=args.pose, model_skin=False, **fixture_options)
        footprint = None
        if empty['captured'] and native['captured']:
            footprint = ImageChops.difference(Image.open(reference[0]).convert('RGB'),Image.open(empty_files[0]).convert('RGB'))
        footprint_bytes = footprint.tobytes() if footprint else b''
        footprint_pixels = sum(any(footprint_bytes[i:i+3]) for i in range(0,len(footprint_bytes),3))
        model_reference = {'asset': args.model_name, 'DEF_scale': args.model_scale,
                           'native_ART_control_captured': control['captured'], 'native_model_changes_ART_pixels': bool(changed),
                           'native_no_skin_control_captured': empty['captured'],
                           'textured_model_visible_pixels': footprint_pixels,
                           'textured_model_pixel_bounds': footprint.getbbox() if footprint else None,
                           'model_draw_is_sequential_eye_fallback': stereo['native_model_fallback_at_capture'] if args.single_pass else None}
        if args.single_pass:
            masks_good = stereo['native_model_fallback_at_capture'] and masks is None
    if args.single_pass and args.scene.startswith('masks'):
        masks_good = bool(masks and masks['translucent_calls'] > 0 and masks['depth_only_calls'] > 0
                          and masks['depth_write_off_calls'] > 0)
    if args.mask_failure:
        masks_good = stereo['mask_fault_observed'] and masks is None
    untouched = not args.single_pass or stereo['mask_collection_untouched']
    recovered = not args.inject_replay_init_failure or stereo['init_failure_recovered']
    passed = (masks_good and untouched and sky_good and depth_good and recovered and pose_good and native['captured'] and stereo['captured'] and counts_equal and oracle_equal and promoted
              and (model_reference is None or model_reference['native_model_changes_ART_pixels']
                   and model_reference['native_no_skin_control_captured'] and model_reference['textured_model_visible_pixels'] > 25)
              and len(pixel_results) == 2 and all(p['exact'] for p in pixel_results))
    skybox_matrix = None
    if args.skybox_root:
        def fixture_run(name, *, zero_ipd, pose='zero', single_pass=False, scene='skybox',
                        sky_depth=0, non_sky_rgba=False, skybox_fog_fault=False,
                        include_skybox_def=True):
            return run(binary, grp, lab/name, fixture_con, args.display, zero_ipd, args.timeout,
                       args.native_attachment, single_pass=single_pass, pose=pose, scene=scene,
                       sky_depth=sky_depth, sky_panning=1, skybox_root=args.skybox_root,
                       non_sky_rgba=non_sky_rgba, skybox_fog_fault=skybox_fog_fault,
                       include_skybox_def=include_skybox_def)

        def parity(expected_run, expected_files, actual_run, actual_files):
            if not expected_run['captured'] or not actual_run['captured']:
                return {'exact': False, 'pixels': [], 'depth': []}
            return compare_eyes(expected_files, actual_files)

        def has_skybox_submission(candidate, *, paired):
            submission = candidate['single_pass_at_capture']
            return bool(submission and submission['skybox_calls'] > 0
                        and (not paired or submission['skybox_paired_calls'] > 0))

        # Baseline zero-IPD has already run through native, two-pass and SPS.
        zero_parity = parity(oracle, oracle_eyes, stereo, eyes)
        stereo_oracle, stereo_oracle_eyes = fixture_run('skybox-stereo-oracle', zero_ipd=True, pose='stereo')
        stereo_sps, stereo_sps_eyes = fixture_run('skybox-stereo-sps', zero_ipd=True, pose='stereo', single_pass=True)
        stereo_parity = parity(stereo_oracle, stereo_oracle_eyes, stereo_sps, stereo_sps_eyes)
        unequal_oracle, unequal_oracle_eyes = fixture_run('skybox-unequal-oracle', zero_ipd=True, pose='unequal')
        unequal_sps, unequal_sps_eyes = fixture_run('skybox-unequal-sps', zero_ipd=True, pose='unequal', single_pass=True)
        unequal_parity = parity(unequal_oracle, unequal_oracle_eyes, unequal_sps, unequal_sps_eyes)

        # Build a sky-only mask from an otherwise identical native ART control.
        # It excludes wall pixels before judging the sector-visibility controls.
        art_control, art_files = fixture_run('skybox-art-native', zero_ipd=False,
                                             include_skybox_def=False)
        sky_mask = (native_sky_mask(reference[0], art_files[0])
                    if native['captured'] and art_control['captured'] else None)
        # These native-only controls each alter one sector's visibility while
        # retaining its texture, shade and palette.  The mask above means a
        # delta proves fog contribution in that sky region, not on its walls.
        ceiling_control, ceiling_files = fixture_run('skybox-ceiling-native', zero_ipd=False,
                                                     scene='skybox-ceiling-fog-control')
        floor_control, floor_files = fixture_run('skybox-floor-native', zero_ipd=False,
                                                 scene='skybox-floor-fog-control')
        ceiling_fog = (native_fog_delta(reference[0], ceiling_files[0], sky_mask)
                       if native['captured'] and ceiling_control['captured'] else
                       {'proved': False, 'sky_pixels': 0, 'changed_pixels': 0, 'visible_unsaturated_pixels': 0})
        floor_fog = (native_fog_delta(reference[0], floor_files[0], sky_mask)
                     if native['captured'] and floor_control['captured'] else
                     {'proved': False, 'sky_pixels': 0, 'changed_pixels': 0, 'visible_unsaturated_pixels': 0})

        # A fixture-only fault omits the sky packet fog upload after collection.
        # It must replay sky geometry and fail exact same-frame parity rather
        # than escaping through a native fallback.
        fog_fault, fog_fault_eyes = fixture_run('skybox-fog-upload-fault', zero_ipd=True,
                                                 single_pass=True, skybox_fog_fault=True)
        fog_fault_parity = parity(oracle, oracle_eyes, fog_fault, fog_fault_eyes)
        fog_fault_evidence = skybox_fog_fault_evidence(
            fog_fault['captured'], fog_fault_parity, oracle_eyes, fog_fault_eyes, sky_mask)

        # Two explicit fallback controls keep the ordinary RGBA and recursive
        # sky-depth paths native.  Their exact two-pass pixels/depth prove the
        # fallback is an intentional compatibility boundary, not asset removal.
        rgba_oracle, rgba_oracle_eyes = fixture_run('ordinary-rgba-oracle', zero_ipd=True,
                                                     scene='room', non_sky_rgba=True)
        rgba_sps, rgba_sps_eyes = fixture_run('ordinary-rgba-sps', zero_ipd=True,
                                               single_pass=True, scene='room', non_sky_rgba=True)
        rgba_parity = parity(rgba_oracle, rgba_oracle_eyes, rgba_sps, rgba_sps_eyes)
        depth_oracle, depth_oracle_eyes = fixture_run('skybox-depth-oracle', zero_ipd=True, sky_depth=1)
        depth_sps, depth_sps_eyes = fixture_run('skybox-depth-sps', zero_ipd=True, single_pass=True, sky_depth=1)
        depth_parity = parity(depth_oracle, depth_oracle_eyes, depth_sps, depth_sps_eyes)

        skybox_matrix = {
            'native_two_pass_sps_zero': zero_parity,
            'two_pass_sps_stereo': stereo_parity,
            'two_pass_sps_unequal': unequal_parity,
            'native_ceiling_visibility_control': ceiling_fog,
            'native_floor_visibility_control': floor_fog,
            'native_sky_pixels_from_art_control': sum(sky_mask) if sky_mask is not None else 0,
            'skybox_fog_upload_fault': {
                'observed': fog_fault['skybox_fog_fault_observed'],
                'replayed_skybox': has_skybox_submission(fog_fault, paired=True),
                'exact_parity': fog_fault_parity['exact'],
                'pixels': fog_fault_parity['pixels'],
                **fog_fault_evidence,
            },
            'ordinary_truecolor_rgba_fallback': {
                'native_fallback': rgba_sps['opaque_fallback_at_capture'],
                'exact_two_pass_parity': rgba_parity['exact'],
            },
            'skyzbufferhack_fallback': {
                'native_fallback': depth_sps['opaque_fallback_at_capture'],
                'exact_two_pass_parity': depth_parity['exact'],
            },
            'submissions': {
                'zero': stereo['single_pass_at_capture'],
                'stereo': stereo_sps['single_pass_at_capture'],
                'unequal': unequal_sps['single_pass_at_capture'],
            },
        }
        matrix_passed = (zero_parity['exact'] and has_skybox_submission(stereo, paired=True)
                         and stereo_parity['exact'] and has_skybox_submission(stereo_sps, paired=True)
                         and unequal_parity['exact'] and has_skybox_submission(unequal_sps, paired=False)
                         and ceiling_fog['proved'] and floor_fog['proved']
                         and fog_fault['skybox_fog_fault_observed']
                         and has_skybox_submission(fog_fault, paired=True) and fog_fault_evidence['proved']
                         and rgba_sps['opaque_fallback_at_capture'] and rgba_parity['exact']
                         and depth_sps['opaque_fallback_at_capture'] and depth_parity['exact'])
        skybox_matrix['passed'] = matrix_passed
        passed = passed and matrix_passed
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
    if skybox_matrix is not None:
        result['skybox_fog_matrix'] = skybox_matrix
    if model_reference is not None:
        result['private_model_reference'] = model_reference
    (lab/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
