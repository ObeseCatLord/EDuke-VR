# Pinned sources

- [EDuke32 archive](https://dukeworld.com/eduke32/synthesis/latest/eduke32_src_20260807-10669-ec5824db8.tar.xz): r10669, ec5824db8; SHA256 `f292e2c69f7f3453dd145d19ce1c114bd7136a8a9cf5b9b6641525fd53fa56c5`. Imported intact as Git commit `72120ae` before changes.
- [RazeXR](https://github.com/Team-Beef-Studios/RazeXR): `caa96be6d80f2ab74fce4b945d54eeda39c3fc20`; cloned with Git history. Current branch removes its Raze engine integration in `b9fb2bf`; examine the parent of that commit for historical engine reference.

New runtime code follows the OpenXR API and RazeXR's session/two-layer swapchain concepts. Direct source reuse, if introduced, must retain each original file's notices. EDuke32 includes GPLv2 code and the separate Build source license; see package/common/gpl-2.0.txt and package/common/buildlic.txt. Historical Raze files also have individual BSD/LGPL notices. Keep those distinctions when preparing a release. No proprietary GRP, map, texture, CON or audio data belongs in this repository.


Controller integration follows the pinned RazeXR
`Projects/Android/jni/RazeXR/OpenXrInput.cpp` action/subaction/space concepts and
`VrInputDefault.cpp` native-game mapping approach. The new backend checks action
activity/focus and keeps EDuke32 controls/networking authoritative. No Raze game
renderer or input protocol was transplanted.

The test-only native remote-device layout is based on Monado's
`src/xrt/drivers/remote/r_interface.h` (`mndrmt3`, BSL-1.0); no Monado source file
is copied. `smoke_action_lifecycle.py` uses the installed libmonado public API
from `/usr/include/monado/monado.h`. Runtime tests use isolated configuration and
runtime directories. Test profiles reference the user's owned GRP read-only.

Primary API references:
[xrSyncActions](https://registry.khronos.org/OpenXR/specs/1.1/man/html/xrSyncActions.html),
[xrSuggestInteractionProfileBindings](https://registry.khronos.org/OpenXR/specs/1.1/man/html/xrSuggestInteractionProfileBindings.html),
[xrGetActionStateBoolean](https://registry.khronos.org/OpenXR/specs/1.1/man/html/xrGetActionStateBoolean.html).


Tracked-orientation investigation also inspected RazeXR engine history at
`e243dda6690b703146293437a13fcc71c5f3a80a` (parent of the engine-removal commit).
`Projects/Android/jni/Raze/source/games/duke/src/player_d.cpp:1000` temporarily
replaces/restores the player struct in `shoot_d_override` using local controller
position/angle data from `VrInputDefault.cpp`. That mechanism alone does not
replicate authoritative remote aim in EDuke32. The new orientation adapter feeds
native angle updates and existing absolute player-update fields instead; it
copies no Raze renderer or temporary player-struct shot override. Independent
hand-origin authority remains a required next slice, not a permanent omission.
