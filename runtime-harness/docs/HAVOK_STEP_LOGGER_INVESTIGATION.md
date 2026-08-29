# HavokStepLogger: known non-working, investigation notes

**Status: known non-working.** This is a documented negative result, not an
in-progress feature. It builds, loads, and installs cleanly, but has never
logged a single line against live gameplay.

## What it does (attempted)

Hooks `bhkCharacterState::Update` across all six concrete character-state
vtables (OnGround/Jumping/InAir/Climbing/Flying/Swimming -- none override the
base's `Update`, so all six need the hook) to log collision/ragdoll state.
The vfunc index was verified by hand-walking the full inheritance chain
(`hkBaseObject`→`hkReferencedObject`→`hkpCharacterState`→`bhkCharacterState`→
the six concrete classes).

Not yet actor-attributed even if it did fire: the hook's signature carries
no direct pointer back to the owning `Actor` or `bhkCharacterController`, so
log lines would be keyed by the `hkpCharacterContext` instance address
rather than a form ID.

## What was tested

Deployed and installed cleanly against a live Skyrim AE 1.6.1170 process
(SKSE64 2.2.6), but produced **zero log lines across 70+ minutes of real
gameplay** (Helgen intro through open-world Whiterun, including
combat-adjacent NPC activity) -- long enough to rule out timing as the
explanation. `PlayerCharacter` was checked and ruled out as a
separate-hierarchy explanation too: its header has no character-controller
references at all, and `AIProcess::GetCharController()`'s actual
implementation returns a plain `bhkCharacterController*` with no
player/NPC branching. The vfunc index (6) was verified by hand-walking the
full inheritance chain (`hkBaseObject`→`hkReferencedObject`→
`hkpCharacterState`→`bhkCharacterState`→the six concrete classes), so an
indexing bug is unlikely.

## Likely root cause

Checked real prior art: [ersh1/Precision](https://github.com/ersh1/Precision)
(GPL-3.0, the standard SKSE-community reference for Havok hooking) has zero
references to `bhkCharacterState`/`hkpCharacterState` anywhere in its
~2,200-line hooking code -- it hooks `RE::bhkWorld`'s physics-step function
directly via a mid-function Xbyak trampoline instead of vtable-hooking the
state machine. The standard community reference doesn't use this project's
vtable-hook approach, which is the most likely reason it's silent -- plausibly
the physics step no longer calls through these vtables on this engine
version, or a different object holds the live state.

## Scoped follow-on (not attempted)

Rebuild Precision-style: hook `bhkWorld`'s physics-step function via an
Xbyak mid-function trampoline instead of vtable hooking. Needs Xbyak enabled
in the build (currently `OFF`), a vcpkg dependency, and re-verified offsets --
a real feature task, not a quick fix.

## Build status

Compiled behind the `RTK_ENABLE_HAVOK_STEP_LOGGER` CMake option, **off by
default** -- it does not ship in the default build alongside the three
working inspectors. See `runtime-harness/CMakeLists.txt`.
