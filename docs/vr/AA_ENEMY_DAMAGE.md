# Actual AA enemy damage over native multiplayer

The opt-in `--enemy-fixture --enemy-map <owned E1L1.MAP>` mode in
`tools/vr/smoke_aa_multiplayer_gameplay.py` exercises an ordinary AA
NEWTROOPGUARD with the tracked native pistol. It uses the shipped
`package/vr/aa566/eduke32_vr_aa566.con` on both peers. No production engine,
protocol, installed AA script or owned source-map changes are required.

The fixture copies the installed v7 Hollywood map, preserving every existing
byte apart from the sprite count, and appends one ordinary enemy in sector 306.
Its position is checked against the native sector polygon. The appended map
slot is 676 for this installed map. Status is native default 0; hitag/lotag
remain zero. Native AA initialization, health, movement, AI, weapon and damage
code run without assignments from the observer.

An observation module changes only the native level **filename** for slot 0,1
to a unique owned map path, retaining the original title and times. Corresponding
per-map ART is linked read-only under the new basename. This keeps AA's actual
Duke/START flow and campaign indices. `-map` combined with `-v1 -l2` did not
establish the intended fixture entry; its file-existence receipt alone was not
proof of the loaded board.

Read-only `EVENT_PROCESSINPUT` observations inspect the appended actor slot.
The test verifies the initial native tile, position, sector and positive health
on both peers before shooting. Real Monado pose changes aim toward the moving
target using the previous native ray, including Build's 16:1 Z scale. Real
trigger presses fire the existing weapon; no aim ray, packet, health, ammo,
actor motion or hit result is injected.

Acceptance requires authoritative tracked sprite hits, native health loss,
converged death, equal native corpse position/sector/collision, and decreased
matching ammo. The death wait follows the current native state: AA can briefly
show negative overkill before normalizing to zero and clearing collision.
Requiring every peer to receive that transient negative value produced a false
failure, despite the retained logs showing the same final corpse.

AA also has a randomized suffering death (`NEWTROOP.CON:241–344`) that sets
health to zero while retaining collision. `newtsufferingstate` clears collision
only at action count 14 (`1180–1194`), about 84 native updates with action delay
21. Eight wall-clock seconds in the software XR lab can be fewer updates than
that; one strict host run reached only about 73 post-lethal updates. The runner
now observes action ID/count/frame/tics without modifying them and permits a
bounded 30 seconds for the native corpse transition. Zero health alone remains
insufficient for this final gate.

## Evidence and scope

Final private software-XR results and binary hashes are indexed in sibling
`evidence/aa-enemy-damage-validation.json`. The accepted runs use one XR peer
and one native CPU peer, each role in turn, with actual controller selection,
native networking, fresh stereo images, active clean OpenXR core validation,
and owned process cleanup. GPU devices are absent; rendering uses llvmpipe/LVP.

Final XR-host run `work/software-xr-aa-enemy-host-native-death/aa-mp-gameplay-hhevo7ka/result.json`
passes all 20 checks: nine authoritative tracked rays, six target hits, health
60→0, ammo 48→39 on both peers, matching corpse position with blocking/hitscan
collision cleared. Final XR-client run
`work/software-xr-aa-enemy-client-corpse/aa-mp-gameplay-nkeubn9_/result.json`
also passes all 20: eight rays, six target hits, health 60→0 and ammo 48→40.
Both outer labs report child/Monado/Xvfb exit 0, clean validation and teardown.
The final host selected the ordinary death branch; it does not directly prove
the inferred suffering branch in the earlier timeout. That failed evidence is
preserved, and the observer now exposes the missing native action fields.

Earlier fixture attempts remain in ignored `work/` as failed evidence. They
include wrong entry/map routing, an invalid initial map sprite status, missing
actor-event observations, a CON constant-index syntax error, and the transient
overkill oracle and an insufficient wait for AA's suffering animation. Failed
runs are retained separately from acceptance. The worker's initial two runs
also used installed AAGAME.CON rather than the shipped compatibility entry;
their results are excluded from compatibility qualification.

This is one ordinary enemy/pistol encounter in an owned campaign-map fixture.
It does not establish every AA enemy or weapon, campaign progression, late
joining, save synchronization, independent simultaneous VR peers, WAN behavior,
hardware-headset performance or model binding. Native AA startup still reports
`AAGAME.CON:22671` invalid sector 4096 reads; these also occur in the prior
unmodified-map compatibility baseline. Some CPU-side sound decode diagnostics
remain. Clean OpenXR validation does not mean those AA issues are resolved.

AA model integration follows the separately reviewed decision in
`AA_MODEL_DESIGN.md`; assets and floating hands are complete, runtime binding
is still pending.
