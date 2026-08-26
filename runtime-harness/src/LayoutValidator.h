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
//      multi-runtime macro configuration the CMakeLists.txt build uses.
//
//      IMPORTANT, corrected after the first real Windows compile: this
//      build's CMakeLists.txt (type-importer/vendor/CommonLibSSE-NG's
//      ENABLE_SKYRIM_SE/AE/VR options) defaults all THREE macros ON
//      simultaneously (dynamic runtime dispatch), not none of them as
//      originally assumed here. That lands every guarded class in the
//      headers' "#else" branch, which is a DIFFERENT, narrower view than
//      either the SE-only or AE-only layout: e.g. Actor compiles to
//      sizeof 0x78 (not 0x2B0), TESObjectREFR to 0x78 (not 0x98),
//      BaseExtraList to 0x1 with data/presence inaccessible via offsetof
//      (accessor-only), TESObjectCELL to 0x50, NiAVObject with no named
//      userData member. These are ground truth for THIS compiled plugin,
//      not for any single real runtime's live memory -- they cannot be
//      diffed against type-importer/coverage_baseline.json (parsed in
//      AE mode) without accounting for the mismatch. Unguarded classes
//      (TESForm, TESQuest, BGSLocation, NiAVObject's parent/local/world/
//      worldBound, bhkCharacterState) share one layout across all three
//      macro states and their offsets ARE directly comparable to live
//      memory and to the baseline.
//
//   2. LIVE CHECK (runs on kDataLoaded -- main.cpp's single messaging
//      listener calls OnDataLoaded() directly. Observed in-game: a second
//      RegisterListener() call from this file returned true but its
//      callback never fired, while main.cpp's own registration did --
//      so every inspector needing kDataLoaded routes through main.cpp's
//      one registration instead of registering its own). Resolves published
//      vtables/RTTI through Address
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
    // Logs the compile-time layout report. Must be called after
    // SKSE::Init() (REL::Relocation resolution needs it).
    void Install();

    // Runs the live-instance check (Address Library resolution +
    // raw-vs-accessor field reads). Call from main.cpp's kDataLoaded
    // handler -- see the file header comment for why this isn't a
    // self-registered listener.
    void OnDataLoaded();
}
