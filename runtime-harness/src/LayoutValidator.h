#pragma once

// LayoutValidator -- cross-checks type layouts against the RUNNING game
// from inside the process, closing the loop with type-importer's static
// coverage data (type-importer/coverage_baseline.json). Full design
// rationale: docs/LAYOUT_VALIDATOR.md.
//
// Unlike the other three inspectors, nothing here is hooked. Two phases:
//
//   1. COMPILE-TIME REPORT (runs at plugin load, inside Install()). Logs
//      sizeof + key offsetof values for ~11 hotspot classes
//      (TESForm/TESObjectREFR/Actor/Character/BaseExtraList/ExtraDataList/
//      TESObjectCELL/NiAVObject/BGSLocation/TESQuest/bhkCharacterState) in a
//      machine-readable "LayoutValidator: LAYOUT class=... sizeof=..."
//      format. The plugin already cannot build if these disagree with the
//      headers' own static_asserts (e.g. static_assert(sizeof(TESForm) ==
//      0x20), TESForm.h:360), so this phase is primarily a build-config
//      fingerprint: it proves the deployed DLL was compiled from the exact
//      vendored CommonLibSSE-NG tree the .gdt archives come from, with the
//      multi-runtime macro configuration (no ENABLE_SKYRIM_AE/SE/VR) that
//      the CMakeLists.txt build uses.
//
//      IMPORTANT multi-runtime caveat baked into the numbers: with no
//      runtime macro defined, every "#ifndef ENABLE_SKYRIM_AE" member
//      block IS compiled in, so the plugin's compiled view of
//      Actor/TESObjectREFR/BaseExtraList/TESObjectCELL is the SE layout
//      (Actor == 0x2B0 with runtime data at 0xE0, TESObjectREFR == 0x98,
//      BaseExtraList == 0x10). On an AE runtime (1.6.629+) the real
//      objects are 8 bytes larger in the runtime-data region and all
//      field access goes through REL::RelocateMemberIfNewer accessors
//      (e.g. Actor::GetActorRuntimeData, Actor.h:710). The logged
//      offsetof values for those classes are therefore SE-view offsets --
//      ground truth for the compiled layout, NOT directly comparable to
//      AE live memory. Unguarded classes (TESForm, TESQuest, BGSLocation,
//      NiAVObject, bhkCharacterState) share one layout across runtimes and
//      their offsets ARE directly comparable to live memory.
//
//   2. LIVE CHECK (runs on kDataLoaded, via a message listener registered
//      by Install()). Resolves published vtables/RTTI through Address
//      Library (RE::VTABLE_TESForm[0], RE::VTABLE_Actor[0],
//      RE::VTABLE_TESObjectREFR[0..3], RE::RTTI_TESForm -- all from the
//      vendored Offsets_VTABLE.h/Offsets_RTTI.h) and logs their resolved
//      addresses against REL::Module::get().base(), then does raw-memory
//      reads of TESForm::formID (0x14) / formType (0x1A) on a live,
//      unguarded-layout instance (the TESNPC for formID 0x00000007, the
//      player base) and compares them against the typed accessors. A
//      mismatch there means the compiled layout disagrees with the real
//      binary -- something no static_assert can ever catch.
//
// Deliberately NOT done here (see docs/LAYOUT_VALIDATOR.md "Limitations"):
// validating member field semantics, vfunc ordering, tail padding, or any
// class with no reachable live instance.

namespace LayoutValidator
{
    // Logs the compile-time layout report and registers the kDataLoaded
    // listener for the live check. Must be called after SKSE::Init()
    // (REL::Relocation resolution and the messaging interface both need
    // it).
    void Install();
}
