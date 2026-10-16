# Pinned sources

- [EDuke32 archive](https://dukeworld.com/eduke32/synthesis/latest/eduke32_src_20260807-10669-ec5824db8.tar.xz): r10669, ec5824db8; SHA256 `f292e2c69f7f3453dd145d19ce1c114bd7136a8a9cf5b9b6641525fd53fa56c5`. Imported intact as Git commit `72120ae` before changes.
- [RazeXR](https://github.com/Team-Beef-Studios/RazeXR): `caa96be6d80f2ab74fce4b945d54eeda39c3fc20`; cloned with Git history. Current branch removes its Raze engine integration in `b9fb2bf`; examine the parent of that commit for historical engine reference.

New runtime code follows the OpenXR API and RazeXR's session/two-layer swapchain concepts. Direct source reuse, if introduced, must retain each original file's notices. EDuke32 includes GPLv2 code and the separate Build source license; see package/common/gpl-2.0.txt and package/common/buildlic.txt. Historical Raze files also have individual BSD/LGPL notices. Keep those distinctions when preparing a release. No proprietary GRP, map, texture, CON or audio data belongs in this repository.
