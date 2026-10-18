# Private software OpenXR lab

The current Mesa 26.2.3 llvmpipe GL + matching LVP Vulkan combination runs the
existing Monado/GLX backend and multiview renderer with hardware GPU devices
absent. This supersedes the earlier incomplete-FBO result for a different
software configuration. No production renderer workaround was needed.

`tools/vr/software_xr_lab.py` owns one Xvfb and one Monado service in a private
Bubblewrap PID/network/device namespace. The desktop X sockets are absent;
only a fresh output directory is writable. GL uses llvmpipe; Vulkan is restricted
to the task-local LVP ICD. Descendant process mappings/device descriptors are
audited, CPU threads are bounded, priority is lowered, and owned process groups
are reaped. Never run this concurrently with another task-owned Monado service.

## Dependencies

The qualified host has Mesa `1:26.2.3-1`, LLVM 22.1.8, Xvfb, Bubblewrap, Monado,
the OpenXR loader/core-validation layer, and Python 3. The matching Arch
`vulkan-swrast-1:26.2.3-1-x86_64.pkg.tar.zst` was extracted into
`work/software-xr/deps`; it was **not installed**. Its SHA256 is
`c099e085f778b3183b22a3ab81b7200dd013855c4bcbc7bb5c5189ed045311bf`.
`work/software-xr/package.json` records the official archive URL, version and
verified package hash. The wrapper requires that manifest beside `deps`, the
matching `.PKGINFO`, and exactly one extracted `lvp_icd.json`/library. It is a
local pinned test recipe, not a portable dependency installer.

The namespace runtime path is `/tmp/xr`: longer workspace paths exceeded
Monado's Unix socket limit. An owned PTY is allocated when stdin is not a TTY.
The real HOME value is preserved read-only; config/cache/runtime writes use
private XDG paths. No user's runtime defaults, OS package state or Blender
service are changed.

## Run

Every path-valued argument must be absolute. Use a new empty mode-0700 output
directory each time; previous results are deliberately not overwritten. Child
execution is bounded to 60 seconds. Harnesses must terminate their own games;
the namespace additionally prevents survivors escaping to the host session.

```sh
python3 tools/vr/software_xr_lab.py \
  --deps "$PWD/work/software-xr/deps" \
  --work-dir "$PWD/work/software-xr-lab-new-diagnostic" -- \
  "$PWD/source/vr/xr_smoke" --frames 3 --timeout 10 \
  --output "$PWD/work/software-xr-lab-new-diagnostic/diagnostic"
```

For a game harness, use `/usr/bin/python3` followed by its absolute script path.
The private display is `:105`; remote-controller port defaults to `49777` in
the isolated network namespace. Set test options for the child using
`/usr/bin/env OPTION=value ...` after `--`. The wrapper sets the hidden-window
test flag, enables core validation when available, and inspects nested game
logs as well as the child log. Validation findings fail the result; activation
must be observed if the layer is available. `result.json` records child exit,
CPU Vulkan identity, device denial and cleanup separately.

## Qualified results and limits

- `work/software-xr-lab-final-diagnostic-2`: three actual submitted diagnostic
  multiview frames, one draw per frame, distinct nonbackground eye readbacks,
  core validation without errors/warnings, all owned processes exit0.
  Monado reports a separate destroy-nonexistent-space teardown warning.
- `work/software-xr-lab-world-final`: actual Duke E1L1, 60 submitted stereo world
  frames. Opaque60 multiview; masks59 multiview/1 two-pass; full59 multiview.
  Distinct eye images inspected, core validation clean and all processes reaped.
- `work/software-xr-lab-world-ui`: same actual single-player world with UI2;
  opaque60 multiview, masks58 multiview/2 two-pass, full58 multiview. Clean client
  validation and owned cleanup.
- Initial multiplayer crosshair runs joined and received input but timed out
  after native centering overshot during slow frames. The narrow native fix and
  passing base/occluded real multiplayer reticle tests are recorded in
  [VIEW_CENTERING.md](VIEW_CENTERING.md). Those tests preserve depth, independently
  qualify both-eye projection and match the native authoritative shot ray.
- Sibling `outputs/evidence/software-xr-validation.json` records bounded results
  and hashes; `software-xr-world.png` contains actual world eye readbacks.

The first wrapper attempt without HOME aborted in Monado before startup;
preserving HOME corrected it. An intermediate world harness passed while its
wrapper rejected missing diagnostic-specific layer lifecycle text; the final
wrapper recognizes the engine's actual core-validation activation output.
Both failed records are preserved. Neither failure establishes a game-renderer
defect. This lab qualifies the tested CPU software stack, not hardware GPU,
physical headset, model rendering, complete SPS, comfort or performance.
