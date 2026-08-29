# Patch 0016 -- inline-embed array-of-template-specialization fields

## Root cause

A C-style array field whose **element type** is a class template
specialization (e.g. `bhkCharacterController`'s `NiPointer<bhkShape>
shapes[2];`, `TESQuest`'s `BSTArray<TESTopic*> topics[6];` and
`BSTHashMap<BGSDialogueBranch*, BSTArray<TESTopic*>*>
branchedDialogue[2];`) reports its own libclang `TypeKind` as
`CONSTANT_ARRAY`, not `RECORD`/`UNEXPOSED`. Patch 0015's inline-embed
check in `SourceParser.parseStruct`'s `FIELD_DECL` case only inspects
the field's own raw/canonical type kind, so it never fired for these
array fields. The field fell through to a plain string-keyed dependency
(e.g. `"NiPointer<bhkShape>[2]"`), and no `ParsedType` is ever
registered under that name anywhere in the pool -- template
specializations are only ever inline-embedded, never registered by
name -- so `TypePool.checkDependenciesFulfilled` reported it permanently
unfulfilled and the whole enclosing struct never reached
`createDataType()`.

This produced a genuinely confusing symptom during investigation: debug
tracing showed `bhkCharacterController` and `TESQuest` being parsed
correctly (63 fields/bases and 29 fields/bases respectively) and
successfully registered in `TypePool` -- i.e. the bug was NOT in parsing
or registration (contrary to this pass's initial assumption while
investigating the Havok cluster and, in an earlier pass, `TESQuest`
independently). It was strictly downstream, in dependency resolution:
`resolve()`'s fixed-point loop never called `createDataType()` for
either class because `checkDependenciesFulfilled` never returned true.

**This is one shared root cause for both the Havok cluster
(`bhkCharacterController`) and `TESQuest`** -- not two separate bugs, as
this pass's own earlier investigation notes had assumed while they
were being looked at independently.

## Fix

- `ParsedStructure.FieldInfo` gained a new `arrayCount` field (default 0
  via a compatibility 6-arg constructor overload -- all pre-existing call
  sites are unaffected).
- `SourceParser.parseStruct`'s `FIELD_DECL` case: before checking
  whether a field's type is an inline-embeddable template specialization,
  peel off a `CONSTANT_ARRAY` wrapper (recording its element count) and
  apply the existing check to the *element* type instead.
- `ParsedStructure.createDataType`: when `arrayCount > 0`, wrap the
  inline-embedded element `DataType` in a Ghidra `ArrayDataType` before
  adding it to the struct.

## Verification

Full 1630-header sweep via the committed `generate_gdt.sh` pipeline
(JDK 25, final FFM, `LIBCLANG_DISABLE_CRASH_RECOVERY=1`):

- `check_regression.py`: **0 regressions**, 38 improvements.
- `TESQuest`: EMPTY (size=1) → **OK, exact** (616/616 = 0x268).
- `bhkCharacterController`: EMPTY (size=1) → MISMATCH (616/816). Still
  short, but a huge improvement (previously not a single field
  resolved; now every field the parser attempts DOES resolve -- the
  remaining gap is a separate, unrelated bug, see below).
- Other improvements from the same array-of-template-element pattern
  appearing across the codebase (as expected -- this is a common
  pattern): `BSGeometry`, `BSTriShape`, `BSDynamicTriShape`,
  `BSInstanceTriShape`, `BSMultiIndexTriShape`,
  `BSMultiStreamInstanceTriShape`, `BGSSaveLoadGame`,
  `ImageSpaceModifierData` (+ nested `Bloom`/`HDR`), `MapCamera`,
  `PlayerCamera`, `TESImageSpaceModifier` (+ nested), `TESWaterForm`,
  `UI3DSceneManager`, `UIRenderManager`, `AIPerkData`,
  `BGSConstructFormsInAllFilesMap`, `BGSFootstepSet`,
  `BGSMusicPaletteTrack`, `BGSSaveLoadQueuedSubBufferMap`,
  `BSBloodSplatterShaderProperty`, `BSLightingShaderMaterialLandscape`,
  `ControlMap::InputContext`, `ScreenSplatter`, `RaceSexMenu::
  RUNTIME_DATA`, `MapMenu::RUNTIME_DATA2`, and others (full list in the
  regression-check improvements report).

`hkpCharacterProxy` (-56 MISMATCH, part of the original Havok cluster)
is **unaffected by this patch** -- its gap has a different, unrelated
cause not yet investigated.

## New, separate, deferred finding: `hkQuadReal`/`__m128` SSE intrinsic type resolves EMPTY

`bhkCharacterController`'s remaining 200-byte gap (616 actual vs. 816
expected) is caused by a *different* bug, unmasked now that the rest of
the struct resolves: every `hkVector4` field (there are 9: `forwardVec`,
`outVelocity`, `initialVelocity`, `velocityMod`, `direction`,
`rotCenter`, `pushDelta`, `fakeSupportStart`, `up`, `supportNorm`)
resolves at `len=0` (confirmed via `InspectGdt.java`). `RE::hkVector4`
(`RE/H/hkVector4.h`) is a genuinely real, non-template class with one
real member, `hkQuadReal quad;`, where `hkQuadReal` is `using
hkQuadReal = __m128;` (`RE/H/hkSseMathTypes.h`) -- a compiler-builtin SSE
vector type, not a struct/class our parser or Ghidra's `DataTypeParser`
knows how to resolve. `hkVector4` itself resolves EMPTY (size=1) in the
full-sweep CSV, confirming `__m128` fails to resolve as a dependency the
same way an unregistered template specialization does, but for a
completely different reason (a compiler intrinsic type, not a template).

This is out of scope for patch 0016 (unrelated root cause: intrinsic
vector types vs. template specializations) and was not investigated
further given time budget -- left as a documented, separate follow-up.
A fix would likely need `TypePool` to special-case `__m128`/`__m256`/
similar SSE/AVX intrinsic type names as built-in fixed-size opaque types
(Ghidra has no native concept of them), similar to how other
compiler-builtin types are already handled elsewhere in the pipeline.
This likely affects other Havok classes beyond `bhkCharacterController`
that also embed `hkVector4`/`hkQuadReal` members directly.
