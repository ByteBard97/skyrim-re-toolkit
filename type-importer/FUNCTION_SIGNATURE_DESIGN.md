# Function Signature / Symbol Application -- Design

Status: phases 1-3 implemented and verified end-to-end (2026-08-29) against a
user-supplied SkyrimSE.exe AE 1.6.1170. Closes the gap defined in
`FUNCTION_SIGNATURE_PROBLEM.md`. Remaining: phase 4 (vtable walk) and docs.

## What changed since the problem statement

A working reference run now exists. A local checkout of alandtse's
BethesdaGhidraScripts fork (commit `702c932`; pipeline code offered as MIT
via its `NOTICE.md` -- see Constraints) with local fixes (pinned externs,
winsdk clang target for Linux, CommonLib-before-fallback pass ordering,
py3.12-safe deps; checkout deliberately untracked here) was set up against a
user-supplied `SkyrimSE.exe` AE 1.6.1170 and passes its own verification
suite:

- 32,275 named functions (26,138 scoped `Class::Method`) created at real
  addresses from `RELOCATION_ID`/`REL::ID` symbols + vtable walks +
  rename-DB/PDB fallbacks
- 11,457 function signatures applied (925 CommonLib + vtable slots + 5,891
  fallback), 0 failures
- 39,291 structs/classes with real layouts in the program's DTM (incl.
  ~19k internal Bethesda structs merged from SkyrimSE.pdb type info)
- Spot checks: `Actor` 696 B / 94 fields, `TESObjectREFR` 160 B / 22,
  `PlayerCharacter` 3048 B / 282; `AbsorbEffect::ModifyOnStart @ 0x1405ab340`
  with a typed signature

This proves the technical approach in the problem statement works on a real
binary. It also pinned down the exact machinery needed, its failure modes, and
what we must NOT copy (see Constraints).

## Constraints (binding)

1. **Licensing.** doodlum/BethesdaGhidraScripts (the original) has NO license
   (all rights reserved, verified via GitHub API 2026-08-29). alandtse's
   extended fork dual-grants its pipeline code (`run.py`, `scripts/`,
   `tools/`) as MIT via its `NOTICE.md` (copyright BethesdaGhidraScripts
   contributors; the fork's top-level GPL-3.0 is aggregate-only, via
   CommonLibSF, which we do not use). Caveat: since the original repo is
   unlicensed, the fork's MIT offer cannot cleanly cover doodlum-derived
   portions, so we treat the whole chain as not-vendorable until upstream
   resolves it. The components below are original implementations written
   against the stricter doodlum constraint and thus satisfy both readings.
2. **Ground rules.** No DRM-circumvention tooling shipped or automated by this
   repo; no PDBs. The toolkit takes the user's exe as given (unpacking their
   own legally purchased game locally is the user's step, documented but not
   performed or distributed by us). Note: a stock `SkyrimSE.exe` is
   SteamStub-wrapped (entry point in `.bind`); symbol application only makes
   sense against an unpacked exe. The reference run unpacked locally via
   Steamless-under-Wine -- that step stays out of the toolkit.
3. **Project conventions.** Ghidra-side code is Java headless postScripts in
   the `demo/ghidra_scripts/` style (not doodlum's generated-Jython style).
   Python glue is stdlib-only.

## Architecture

Four components. Two already exist; one is a trivial extension; one is new.

```
CommonLibSSE-NG headers ─┬─(A) libclang parse (EXISTS)──> FunctionDefinition
                         │                                DataTypes in .gdt
                         └─(B) ID correlation (NEW)─────> name ↔ REL::ID map
meh321 Address Library ────(C) .bin parse (EXISTS,──────> ID → RVA
   .bin (user-supplied)      extend to emit RVAs)
                                   │
                                   ▼
                        symbols.json (name, RVA, ID,
                        signature type-ref, provenance)
                                   │
user's exe ──analyzeHeadless──> (D) ApplySymbols.java (NEW)
              + ApplyGdt.java      createFunction / createLabel at RVA,
                                   apply FunctionDefinition from program DTM,
                                   plate comment with RELOCATION_ID + source
```

### (A) Signature extraction -- EXISTS, no work

The patched `SourceParser.java` already walks `FUNCTION_DECL`,
`C_X_X_METHOD`, constructors, destructors and emits
`FunctionDefinitionDataType`s into the `.gdt` (`parseMethodAsFunction` adds
the explicit `this` param). Verified present in current archives
(`GenerateGdt.java:241-244`). Nothing to build; the applier (D) looks these
up by name in the program DTM after `ApplyGdt.java` runs.

### (B) Name ↔ REL::ID correlation -- NEW, small

The one genuinely missing piece. Given a CommonLib function we know its
declared signature (A) but not which `REL::VariantID(se, ae, vr)` ID belongs
to it, because that binding lives in the function's inline body
(`return REL::VariantID(...).address()(...)` or a static
`REL::Relocation<...> func{...}` at namespace scope) -- and our parser runs
with `skipFunctionBodies()`.

Design: a standalone Python script
(`type-importer/scripts/mine_function_ids.py`) that scans `RE/**/*.h` source
with a brace-tracking context walker (namespace/class/method scope) and
regexes for `RELOCATION_ID(se, ae)` / `REL::ID(x)` / `REL::VariantID(...)`
plus `REL::Relocation<sig> name{id}` declarations, emitting
`{qualified_name, se_id, ae_id, kind}`. Same technique as the reference
implementation, reimplemented (constraint 1). Prefer source-scan over enabling
function bodies in libclang: bodies would slow the main parse and pull in
body-dependent types we deliberately skip.

Also mine `Offsets.h`, `Offsets_RTTI.h`, `Offsets_NiRTTI.h`,
`Offsets_VTABLE.h` for label symbols (RTTI_/VTABLE_ entries) -- these feed
vtable-anchored function naming in (D).

### (C) ID → RVA resolution -- trivial extension

`scripts/check_address_library_ids.py` already parses the meh321
delta-encoded `.bin` format and builds the full `{id: offset}` dict; it just
only uses it for membership tests. Add an emit mode. The user supplies the
`.bin` matching their exe version (per-version offsets shift between AE point
releases; a 1.6.1170 database is present in the local reference checkout).
PE version detection: trivial `VS_FIXEDFILEINFO` read (~40 lines, stdlib).

### (D) Ghidra-side application -- NEW, the deliverable

`demo/ghidra_scripts/ApplySymbols.java`, run as a postScript after
`ApplyGdt.java` in the existing `analyze_skyrim.sh` multi-pass harness.
Input: `symbols.json` from (B)+(C). Behavior, in one transaction:

1. For each symbol: `createLabel(addr, name, USER_DEFINED)`; for functions,
   `DisassembleCommand` + `createFunction`, `setName`.
2. Signature application: look up the `FunctionDefinition` by name in the
   program DTM (placed there by ApplyGdt), apply via
   `ApplyFunctionSignatureCmd`. No C-text parsing -- the .gdt types are the
   single source of truth, unlike the reference pipeline which rebuilds
   signatures from its own descriptors.
3. Plate comment: `RELOCATION_ID(se, ae)` + provenance (which source file
   provided the name).
4. Vtable pass: for each `VTABLE_X` label, walk the pointer table in memory,
   create+name target functions `Class::Method` from the vtable structs we
   already emit, and apply slot signatures. This is what scales coverage from
   ~1k REL::ID'd functions to the reference run's ~18k named.

### Verification

Implemented and verified (2026-08-29), SkyrimSE.exe AE 1.6.1170,
`versionlib-1-6-1170-0.bin`, 4-header test .gdt:

- `mine_function_ids.py`: 15,203 symbols mined+resolved (639 funcs, 14,564
  labels); 1,349 dropped (no AE address, mostly SE-only IDs)
- `ApplySymbols.java`: 14,610 labels created, 577 functions created/named,
  103 signatures applied from .gdt FunctionDefinitions, **0 failures**;
  idempotent on rerun
- Decompiled ground truth at `CombatMagicCaster::CheckTargetValid @
  0x14081e610`: typed signature `bool (CombatController*, Actor*, ...)` with
  a `REL::ID(45348)` plate comment -- the exact gap the problem statement
  demonstrated (`FUN_1401e1270(longlong*, undefined8)`)

Classification pitfalls fixed during verification: `REL::Relocation<T**>
singleton{}` inside inline `GetSingleton()` thunks is a DATA address (name
the variable, not the thunk); `constexpr REL::VariantID X(...)` is a
declaration form distinct from call syntax; VTABLE entries are
`std::array<REL::VariantID, N>` (first element = primary vtable); Offsets.h
mixes function and data IDs, so ApplySymbols demotes `func` symbols to
labels when the resolved address is not in an executable block.

### Verification (planned, next steps)

- Ground-truth spot checks in the postScript (reference-run values, AE
  1.6.1170): `AbsorbEffect::ModifyOnStart @ 0x5ab340`, named functions
  >= 12,000, signatures applied with zero failures.
- ID-level: (B) output cross-checked against the address library for 100%
  resolution, extending the existing `ADDRESS_LIBRARY_VALIDATION.md` result.
- Regression: committed `symbols_baseline.json` + `check_regression.py`-style
  gate, matching the type-coverage harness pattern.
- Demo: before/after `DumpDecomp.java` screenshots at a known function,
  extending `demo/README.md`.

## Phasing

1. ~~(C) emit mode + PE version detect~~ -- done (`mine_function_ids.py
   --addrlib`; PE version detect still open, version is user-specified for now).
2. ~~(B) header miner, Skyrim AE~~ -- done (include/ + src/, 15,203 symbols).
   SE/VR legs still open.
3. ~~(D) applier, symbols-only~~ -- done (`ApplySymbols.java`), verified
   end-to-end. This closes the problem statement.
4. Vtable walk pass -- the coverage multiplier (~18k named functions in the
   reference run vs ~600 from symbols alone).
5. Docs: demo walkthrough update + README "What changes on screen" refresh.

## Explicit non-goals

- No Steamless/DRM handling, no PDB consumption, no IDA imports.
- No Fallout 4 leg in v1 (no local exe, no CommonLibF4 vendored).
- Not vendoring or copying BethesdaGhidraScripts code (constraint 1); the
  local fork checkout stays untracked reference material.
