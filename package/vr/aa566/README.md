# AA 5.66 input-history compatibility

`eduke32_vr_aa566.con` corrects AA 5.66's `oldbits` ownership. AA keeps current
input per player, but stores previous input globally. Another player's tick can
then make a held selector button look newly pressed. This entry declares the
history per player before loading the installed AA scripts through native CON
includes. The expected duplicate-definition warning preserves this first
declaration; it is not a compile error.

The package contains no AA game data. It uses your existing AA 5.66 installation
without editing it. It does not change the compiler, selector logic, network
protocol or AA's other input-history variable, `oldextbits`.

## Launch

Use a separate writable profile directory for this development build. Keep the
main CON **basename** shown below: native saves record that name. Supplying an
absolute main-CON path would make the save identity depend on package location.

```sh
mkdir -p /path/to/new-aa-vr-profile
cd /path/to/new-aa-vr-profile

EDUKE32_XR=1 EDUKE32_XR_SINGLE_PASS=1 EDUKE32_XR_UI=2 \
EDUKE32_XR_AIM=right EDUKE32_XR_HAND_SHOTS=1 \
  /path/to/eduke32-vr/eduke32-xr -usecwd -noautoload \
  -j /path/to/alien_armageddon_566 \
  -j /path/to/eduke32-vr/package/vr/aa566 \
  -g /path/to/alien_armageddon_566/AA.grp \
  -x eduke32_vr_aa566.con -h duke3d.def
```

Use the same wrapper, AA content and engine build on every multiplayer peer.
For the qualified Hollywood test, the native host adds
`-server -c2 -v1 -l2 -s1`; the joining peer adds `-connect host:port` instead.
Flat peers use the native executable and omit the XR environment variables.
Native dedicated hosting uses `-dedicated` in place of `-server`.

## Scope

Actual two-player held/released/repressed selection, unrelated input from the
other player, and Duke selection/START/tracked pistol firing with VR hosting
or joining are qualified through this entry. Fresh-wrapper gameplay saves also
pass process restart/load, continued tracked firing and native `map` New Game
reset, without additional CON modules. Exact results and save/profile
qualification are recorded in [the compatibility evidence](../../../docs/vr/AA_COMPAT_ENTRY.md).

Full AA multiplayer is still in development. Shared selection state, general
script-state authority, late-join campaign state, enemy combat, remaining
weapons and model bindings, and complete single-pass stereo need further work.
Importing saves made with the unwrapped AA scripts is unqualified. Keep those
profiles separate; this package provides no save migration.
