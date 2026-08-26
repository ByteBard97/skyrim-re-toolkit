# Patch 0022: `isPolymorphic()` extracts template arguments from partially-dependent types

Fixes the "nested template-parameter references" wall patch 0021 documented
as deferred, and turns out to be the single largest fix in the coverage-sweep
series so far: **88 classes** fixed per runtime (vs. patch 0021's own 10-11),
including 0008's original running examples, `FxDelegateHandler` and `IMenu`.

## What 0021/0008/0007 thought this needed

Patch 0021's writeup ("What's still deferred: nested template-parameter
references") describes the wall like this:

```
template <class T, std::uint32_t STAT>
class GRefCountBase : public GRefCountBaseStatImpl<GRefCountImpl, STAT> { ... };
```

Walking `GRefCountBase`'s primary template body finds one base, spelled
`GRefCountBaseStatImpl<GRefCountImpl, STAT>`. That spelling isn't equal to
any single parameter name in `paramNames`, so 0021's bare-name substitution
never fires, and `STAT` stays unresolved one level down. 0021 concluded this
needs "textual/structural substitution into a template-id (rewriting `STAT`
to `2` inside `GRefCountBaseStatImpl<GRefCountImpl, STAT>` to get a genuine
instantiation to look up or re-derive)" — a "comparably-sized follow-on
investigation", the same conclusion patch 0007 reached for the analogous
`hkArray<T> : public hkArrayBase<T>` field-embedding case.

**This turned out to be wrong.** No textual substitution is needed at all.

## The actual root cause: an unnecessary gate, not a missing mechanism

`clang_Type_getNumTemplateArguments`/`clang_Type_getTemplateArgumentAsType`
operate on a `Type`'s own `TemplateSpecializationType` structure directly —
they read the argument list right off `type` itself, independent of whether
`type.declaration()` happens to resolve to a genuine
`ClassTemplateSpecializationDecl`. 0021's code gated the whole extraction
behind `isSpecialization` (exactly that declaration check), which is
**false** for a partially-dependent type like
`GRefCountBaseStatImpl<GRefCountImpl, STAT>` — one argument (`GRefCountImpl`)
is concrete, the other (`STAT`) is still a symbolic reference to an enclosing
template's own parameter, and that's enough to make `isSpecialization` return
false, even though the concrete argument is sitting right there.

Confirmed via `GCPP_DEBUG_POLY=GRefCount` with temporary extra tracing
(`rawNumArgs`, `canonicalNumArgs`, `rawArg0` printed directly, bypassing
the `isSpecialization` gate) before committing to the fix: for
`GRefCountBaseStatImpl<GRefCountImpl, STAT>`,
`type.declaration()` resolves to the bare `CLASS_TEMPLATE` (not a
specialization, so `isSpecialization=false`), yet
`type.canonicalType().numTemplateArguments()` still correctly reports `2`
and `.templateArgumentType(0)` still correctly resolves to `GRefCountImpl`
— entirely independent of `STAT` (argument 1) being unresolved. This is
precisely the "nested parameter inside a template-id" case 0021/0008/0007
all separately hit and assumed required structural substitution: it doesn't.
The base's own spelling (`GRefCountBaseStatImpl<GRefCountImpl, STAT>`) was
never the thing being substituted — the fix substitutes the **next level
down**'s bare parameter reference (`Base` inside `GRefCountBaseStatImpl`'s
own primary body) using argument data read directly off *this* type, gate
removed.

## The fix

Removed the `isSpecialization` conditional entirely from the
template-argument-extraction block in `isPolymorphic(Type)`. Old code:

```java
Type canonicalForArgs = isSpecialization ? type.canonicalType() : null;
int numArgs = isSpecialization ? canonicalForArgs.numTemplateArguments() : 0;
...
if (isSpecialization && baseSpelling != null) {
    int paramIndex = paramNames.indexOf(baseSpelling);
    if (paramIndex >= 0 && paramIndex < numArgs) {
        Type substituted = canonicalForArgs.templateArgumentType(paramIndex);
        ...
```

New code always attempts extraction, unconditionally:

```java
Type argsSource = type.canonicalType();
int numArgs = argsSource.numTemplateArguments();
...
if (baseSpelling != null) {
    int paramIndex = paramNames.indexOf(baseSpelling);
    if (paramIndex >= 0 && paramIndex < numArgs) {
        Type substituted = argsSource.templateArgumentType(paramIndex);
        ...
```

A plain, non-template type simply reports `numArgs=0` either way — a safe
no-op for the substitution loop, so this isn't gated behind any new
condition, it just always runs. `canonicalType()` is kept (not the raw
`type`) for the same reason 0006/0007 established: `clang_Type_getNumTemplateArguments`
only reports explicitly-specified arguments on the raw/sugared type, not ones
resolved from a parameter's own default — `canonicalType()` reports the full,
positionally-correct list including defaults, and the same `GCPP_DEBUG_POLY`
trace confirmed it also correctly reports `numArgs=2`/`arg[0]=GRefCountImpl`
for the partially-dependent case, so this doesn't reintroduce the gating bug
being removed.

The debug instrumentation added to confirm the hypothesis (extra
`rawNumArgs`/`canonicalNumArgs`/`rawArg0` prints via a try/catch) was removed
once confirmed; the pre-existing `debugThis`-gated `[POLY]` trace lines from
patch 0021 are left in place, unchanged.

## Blast radius: 88 classes fixed per runtime, 2 pre-existing bugs unmasked

Full 1630-header sweep, all three runtimes, against the committed
`coverage_baseline*.json` files (updated by this patch):

- **AE**: 88 improvements, 2 regressions, 0 newly-seen.
- **SE**: 88 improvements (identical set), 2 regressions (same two classes), 0 newly-seen.
- **VR**: 88 improvements (identical set), 2 regressions (same two classes), 0 newly-seen.

All three runtimes hit the exact same 88 improvements and the exact same 2
regressions — no runtime-specific divergence. Improvements include
`FxDelegateHandler` and `IMenu` (0008's own original examples, both now
`OK`), the entire menu hierarchy (`AlchemyMenu`, `BarterMenu`, `BookMenu`,
`ContainerMenu`, `CraftingMenu`, `DialogueMenu`, `FavoritesMenu`, and ~20
more `*Menu` classes), and most of the `GFx*`/`GAS*` Scaleform UI layer
(`GFxMovie`, `GFxMovieView`, `GFxSprite`, `GFxTranslator`,
`GASGlobalContext`, `GASStringManager`, and dozens more) — all of which
route through the same `GRefCountBase<T, STAT>` -> `GRefCountBaseStatImpl<GRefCountImpl, STAT>`
private-inheritance chain this fix unblocks. `ArmorRatingVisitor`,
`BaseExtraList`, `ExtraDataList`, and `BGSPackageDataBool` (0021's own
accepted regression) are all unchanged, confirming no interaction with
unrelated prior patches.

## The two regressions: both pre-existing bugs unmasked, not caused by this patch

### `GFxMovieRoot`: `OK (actual=11248) -> MISMATCH (actual=11240)`

`GFxMovieRoot : public GFxMovieView, public GFxActionPriority`. Before this
patch, `GFxMovieView` (a base of `GFxMovieRoot`) itself measured `0x20` (32
bytes) embedded — **wrong**, since `GFxMovieView`'s own
`static_assert(sizeof(GFxMovieView) == 0x18)` says it should be exactly `0x18`
(24). After this patch, the same embedded `GFxMovieView` correctly measures
`0x18` — byte-exact against its own static_assert. `GFxMovieRoot`'s reported
total dropping from 11248 to 11240 is this same 8-byte correction propagating
up one level; the previous 11248 was two errors cancelling (an oversized
`GFxMovieView` masking an independent 8-byte shortfall elsewhere in
`GFxMovieRoot`'s own layout), not a genuinely correct total. Same pattern as
0021's `BGSPackageDataBool` and the 0006/0009/0011/0015 precedent.

### `GFxLoaderImpl`: `OK (actual=120) -> MISMATCH (actual=112)`

`GFxLoaderImpl`'s own header (`RE/G/GFxLoaderImpl.h`) inherits from three
bases with its own inline offset comments:

```cpp
class GFxLoaderImpl :
    public GRefCountBase<GFxLoaderImpl, GStatGroups::kGStat_Default_Mem>,  // 00
    public GFxStateBag,                                                    // 10
    public GFxLogBase<GFxLoaderImpl>                                       // 20
{
public:
    ~GFxLoaderImpl() override;  // 00
    GFxStateBagImpl* stateBagImpl;  // 28
    ...
};
static_assert(sizeof(GFxLoaderImpl) == 0x78);
```

The header's own annotated offsets place `GFxStateBag` at `0x10` and the next
base, `GFxLogBase<GFxLoaderImpl>`, at `0x20` — a 16-byte span. But
`GFxStateBag`'s own `static_assert(sizeof(GFxStateBag) == 0x8)` says it's
only 8 bytes, and `GFxLogBase<void*>`'s own `static_assert(sizeof(GFxLogBase<void*>) == 0x8)`
confirms the same for the third base. There is a genuine, pre-existing 8-byte
gap between `GFxStateBag` and `GFxLogBase` in the real MSVC layout (secondary
polymorphic base alignment, unrelated to this patch) that this pipeline has
never modeled — this fix doesn't touch base-offset/padding computation at
all, only the yes/no `isPolymorphic()` decision. Before this patch,
`GFxLoaderImpl` got a spurious 8-byte vptr from the old blindness to
`GRefCountBase`'s chain, which happened to supply exactly the 8 bytes the
unmodeled `GFxStateBag`/`GFxLogBase` gap needed — another case of two errors
cancelling into a coincidentally-correct total. Confirmed the redundant vptr
correctly disappears after this fix (verified via direct `.gdt` component
inspection) and that `GRefCountBase`'s own embedded size is unchanged
(`0x10` both before and after) — the regression is entirely attributable to
this separate, pre-existing, unrelated base-offset gap, not to anything this
patch changed.

Both regressions were verified identically on all three runtimes (AE/SE/VR),
ruling out a runtime-specific edge case.

## Verification

Full 1630-header sweep, all three runtimes (`ENABLE_SKYRIM_AE`,
`ENABLE_SKYRIM_SE`, `ENABLE_SKYRIM_VR`), against
`coverage_baseline{,_se,_vr}.json` via `check_regression.py`: 2 regressions
(both above, precedented/accepted as pre-existing-bug unmasking), 88
improvements per runtime, 0 other changes. `coverage_baseline*.json` updated
to lock in the 88 improvements and the two accepted regressions.

## Correction to patch 0008's own writeup

`patches/0008-isPolymorphic-investigation-DEFERRED.md` (and 0021's own
writeup) describe the nested-parameter wall as needing "textual/structural
substitution into a template-id" — a real follow-on investigation. It
wasn't: it was a one-line gating bug (`isSpecialization` guarding argument
extraction that works fine without it). Filed here so the next reader
doesn't re-derive the same "this needs bigger machinery" conclusion 0007,
0008, and 0021 each independently reached.

## How to apply

From `type-importer/vendor/GhidraClangPoweredParse`, after patches
0001-0006, 0009, 0011-0018, 0021 (and 0010 on JDK 22+) are already applied:

```bash
patch -p1 < ../../patches/0022-fix-ispolymorphic-partial-dependent-args.patch
```
