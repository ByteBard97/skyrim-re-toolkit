#pragma once

// HavokStepLogger -- hooks bhkCharacterState::Update via vtable to
// observe character-controller physics-state transitions live (the
// second of the three planned inspectors -- see README.md).
//
// Hook point: bhkCharacterState::Update (RE/B/bhkCharacterState.h,
// vfunc index 6, inherited from RE::hkpCharacterState::Update). Neither
// RE::hkpCharacterState nor RE::bhkCharacterState is ever instantiated
// directly -- both are abstract (hkpCharacterState::GetType and
// bhkCharacterState::Unk_08 remain pure virtual) -- so, exactly like
// AIProcessInspector's Actor/Character vtable split, there is no single
// vtable to hook. The six concrete Bethesda state subclasses
// (RE::bhkCharacterStateOnGround/Jumping/InAir/Climbing/Flying/Swimming)
// each carry their own vtable (Offsets_VTABLE.h) and none of them
// override Update, so all six are hooked at the same index.
//
// Known limitation: this hook's signature (hkpCharacterContext&,
// hkpCharacterInput&, hkpCharacterOutput&) carries no direct pointer to
// the owning RE::Actor or RE::bhkCharacterController. Correlating a step
// back to a specific actor would need either an unlabeled/"unkNNN" field
// in RE::bhkCharacterController -- which this project's ground rules
// forbid guessing at -- or is left for a rewrite of the underlying
// libclang parser plumbing to add member names before Address Library
// cross-checking. RE::hkpCharacterContext IS a byval member of
// RE::bhkCharacterController at a documented offset (0x1E0), so the
// owning controller is a valid pointer-arithmetic recovery, but nothing
// beyond that is attempted here. This inspector therefore logs
// state-transition data keyed by the hkpCharacterContext instance
// address, not by actor -- still real, changing per-physics-step data,
// just not yet actor-attributed.

namespace HavokStepLogger
{
    // Installs the bhkCharacterState::Update hook on all six concrete
    // character-state vtables. Must be called after SKSE::Init() (each
    // write_vfunc needs the module base REL::Relocation resolves
    // against).
    void Install();
}
