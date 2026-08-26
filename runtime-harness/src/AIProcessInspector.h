#pragma once

// AIProcessInspector -- hooks Actor::Update via its vtable to observe
// package-evaluation state live, for the AI scheduler inspector described
// in README.md.
//
// Hooking Actor::Update (not Actor::EvaluatePackage) is a deliberate
// choice: EvaluatePackage is a plain (non-virtual) member function
// resolved only through an Address Library RELOCATION_ID
// (see vendor/CommonLibSSE-NG/src/RE/A/Actor.cpp:249-254), and
// SKSE::Trampoline::write_branch/write_call patch an existing rel32
// call/jmp *site* -- they don't relocate a function's own prologue, so
// they can't safely detour EvaluatePackage's entry point without a
// disassembled call-site offset this repo doesn't have. Actor::Update is
// virtual (Actor.h:371, vfunc index 0xAD) and Actor's vtable is already
// published as RE::VTABLE_Actor in the vendored headers
// (Offsets_VTABLE.h), so it hooks cleanly via REL::Relocation::write_vfunc
// with no extra offsets to source.
//
// Hooked on BOTH RE::VTABLE_Actor and RE::VTABLE_Character: live NPCs
// are RE::Character instances, which carry their own vtable array
// distinct from RE::Actor's even though Character.h doesn't override
// Update -- patching only VTABLE_Actor would silently never fire for any
// real NPC. RE::PlayerCharacter has yet another vtable and is not
// covered; this inspector is NPC-only by design.

namespace AIProcessInspector
{
    // Installs the Actor::Update vfunc hook. Must be called after
    // SKSE::Init() (write_vfunc needs the module base REL::Relocation
    // resolves against).
    void Install();
}
