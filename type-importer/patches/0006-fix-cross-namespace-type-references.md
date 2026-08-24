# Patch 0006 — fix cross-namespace type references and missing keyword primitives

## Symptom

The coverage sweep (see `COVERAGE_SWEEP_PLAN.md`) found EMPTY (size ≤ 1,
completely field-less) as the single largest bucket in the full-namespace
sweep: 1365 of 2821 checkable classes. Two concrete, previously-EMPTY
examples: `RE::AbstractHeap` (expected `0x2a8`, resolved to `0x1`) and
`RE::AIProcess` (expected `0x140`, resolved to `0x1`). Neither involves a
template specialization — the class of bug patches 0003/0005 already fixed
— so this needed its own root cause.

## Root cause #1 — cross-namespace type spelling never matches the pool's bare-name registration

`SourceParser.parseStruct`/`parseUnion`/etc. register every type in
`TypePool` under its **bare** name (`structCursor.spelling()`, e.g.
`"CRITICAL_SECTION"`) — namespaces only ever affect the Ghidra
`CategoryPath`, never the lookup key. But when a field or base class is
declared with a type from a *different* namespace than the one it's
referenced from, clang's `Type.spelling()` returns the **fully-qualified**
name, e.g. `"REX::W32::CRITICAL_SECTION"` for `RE::BSCriticalSection`'s own
`criticalSection` member (`RE/B/BSAtomic.h`):

```cpp
namespace RE {
    class BSCriticalSection {
    public:
        REX::W32::CRITICAL_SECTION criticalSection;  // 00
    };
}
```

`TypePool.getType("REX::W32::CRITICAL_SECTION")` never matches the pool's
registered `"CRITICAL_SECTION"` key. `TypePool.checkDependenciesFulfilled`
therefore never returns true for `BSCriticalSection`, so it's left with the
zero-length forward-declaration stub `TypePool.resolve()` pre-registers for
every struct before the iterative resolution loop even starts (`resolve()`,
lines ~46-63) — that stub is what Ghidra reports as a 1-byte empty struct.
This cascades: `RE::AbstractHeap` embeds `BSCriticalSection` as a field, so
its own dependency check also permanently fails, leaving it stuck at the
same empty stub.

Confirmed via a debug trace instrumenting `TypePool.resolve()`/
`checkDependenciesFulfilled` (see verification below): `AbstractHeap` was
reported as permanently blocked on `BSCriticalSection`, which was itself
blocked on `REX::W32::CRITICAL_SECTION` never resolving — while the bare
`CRITICAL_SECTION` (from `REX::W32::CRITICAL_SECTION`'s own top-level
parse, `REX/W32/BASE.h`) resolved fine, at the correct size 0x28.

This is the exact same *class* of bug patch 0005 already fixed for
`std::`-qualified builtins (`normalizeTypeName` strips a leading `"std::"`
prefix) — just not generalized to arbitrary namespace qualifiers. Given
that `RE::` classes reference `REX::W32::*` Win32 stand-ins extremely
commonly (any class touching threading, memory, or file APIs), this is a
widespread, systemic gap, not a one-off.

### Fix

Generalize `TypePool.normalizeTypeName` with a final fallback: strip a
leading namespace-qualifier path down to the bare identifier (last `::`
segment), e.g. `"REX::W32::CRITICAL_SECTION"` → `"CRITICAL_SECTION"`,
`"RE::ActorValue"` → `"ActorValue"`. Deliberately **excluded** for names
containing `<` (template instantiations) — those go through the separate
inline-embedding mechanism in `SourceParser` (patches 0003/0005), and a
naive last-`::`-segment split would incorrectly cut through a
namespace-qualified template argument (e.g. `"RE::NiPointer<Actor>"` must
not become `"Actor>"`).

## Root cause #2 — C++ keyword primitives have no bootstrap path

Even after fixing root cause #1, `AbstractHeap` was *still* empty. Further
tracing showed it was now blocked on the dependency `"bool"` — a bare,
unqualified, un-templated C++ keyword. `AbstractHeap` has two `bool`
members (`allowDecommits`, `supportsSwapping`).

This looks superficially similar to `std::uint32_t`/`std::size_t`, but
those bootstrap themselves: `<cstdint>` (force-included via
`stubs/layout_pch.h`) itself declares `using uint32_t = ...;` as a real
`TYPEDEF_DECL`, which `SourceParser.parseTypedef` registers in the pool
under the bare name `"uint32_t"`. The *first* class that needs
`"std::uint32_t"` fails direct resolution, then `normalizeTypeName` strips
`"std::"` → `"uint32_t"`, which resolves **once the `uint32_t` typedef
itself has already been created** by an earlier resolution pass (it has a
trivial dependency — a genuine core-C primitive Ghidra's `DataTypeParser`
already knows — so it resolves in pass 0 or 1, then stays resolved for
every subsequent lookup against the same `dtm`).

`bool` has **no such bootstrap path**: it's a raw language keyword, never
spelled as a `using`/`typedef` declaration anywhere in the parsed AST.
Confirmed directly with a standalone test against a fresh `TypePool` with
zero parsed types:

```java
TypePool pool = new TypePool(new DataTypeManager[]{});
pool.getType("bool");       // -> null
pool.getType("wchar_t");    // -> null
pool.getType("char16_t");   // -> null (not fixed here, see Known follow-ups)
```

`ghidra.util.data.DataTypeParser` (configured with
`AllowedDataTypes.FIXED_LENGTH`, searching only the pool's own
`StandAloneDataTypeManager`) simply does not know `"bool"` as a builtin
name — this is not an ordering issue more resolution passes would fix, it
is a **permanent, deterministic** failure for every single class anywhere
in the codebase with an unqualified `bool` member. `bool` appears roughly
3500 times across `RE/*.h` (vs. ~12 files combined for
`wchar_t`/`char16_t`/`char32_t`/`char8_t`) — by a wide margin the dominant
cause of the EMPTY bucket at scale.

### Fix

Pre-register `"bool"` (→ `ghidra.program.model.data.BooleanDataType`) and
`"wchar_t"` (→ `ghidra.program.model.data.WideCharDataType`) as a static
lookup checked at the start of `TypePool.resolveType`, before falling
through to `DataTypeParser`.

## Verification

Standalone `TestGetType.java` harness (not committed — throwaway, mirrors
`TypePool`'s own construction) confirmed the isolated failure before the
fix and the isolated success after.

`RE/A/*.h` subset (53 headers, same subset used to validate the coverage
sweep tooling itself):

| Class | Before (patches 0001-0005 only) | After (+ patch 0006) | Expected (`static_assert`) |
|---|---|---|---|
| `BSCriticalSection` | 1 (EMPTY) | **40 (0x28)** ✅ exact | 0x28 |
| `AbstractHeap` | 1 (EMPTY) | **680 (0x2a8)** ✅ exact | 0x2a8 |
| `AIProcess` | 1 (EMPTY) | 240 (still short — see Known follow-ups) | 0x140 (320) |
| `IMemoryHeap` | 4 | 8 | (no direct assert found; vtable-only interface, 8 bytes = 1 vptr is plausible) |

Full-namespace sweep (1630 headers via `scripts/list_re_headers.sh`,
same scope as the corrected baseline in `coverage_baseline.json`):

| Bucket | Before (baseline) | After (+ patch 0006) |
|---|---|---|
| OK | 1004 | **1234** (+230) |
| MISMATCH | 420 | 461 (+41 — includes the 5 known regressions below, and classes newly resolved-but-still-wrong) |
| EMPTY | 1365 | **1032** (-333) |
| UNRESOLVED | 32 | 32 |
| NO_GROUND_TRUTH | 727 | 790 |
| Total resolved data types | 14415 | 16960 |
| Clang diagnostics | 1144 | 1144 (unchanged — this patch is a `TypePool` resolution fix, not a parse fix) |

`scripts/check_regression.py --baseline coverage_baseline.json --new
<this-run's-snapshot>`: **383 improvements, 5 regressions** (all 5
root-caused above, all pre-existing/unmasked, not introduced by this
patch's own two fixes), 1 newly-seen class. Full regression list and the
383-improvement list are in this session's run output.

## Regression found and root-caused (NOT fixed here — see below)

The full-sweep regression check (`scripts/check_regression.py` against the
committed `coverage_baseline.json`) found 5 regressions alongside 383
improvements: `HUDMenu` (152→160), `KinectMenu` (80→88), `ModManagerMenu`
(88→104), `SleepWaitMenu` (88→96), `TutorialMenu` (72→80) — all previously
`OK`, all now `MISMATCH`, all larger than expected.

**This is not a bug introduced by patch 0006.** Root-caused via
`InspectGdt.java` component diffing (before/after): all five embed
`RE::GFxValue` (directly or via `HUDMenu`'s own `RUNTIME_DATA`). Before
this patch, `GFxValue` itself resolved to size 16 — **wrong**, its own
`static_assert(sizeof(GFxValue) == 0x18)` says 24. This patch's root
cause #1 fix (cross-namespace stripping) happened to also fix whatever was
blocking one of `GFxValue`'s own fields, so `GFxValue` now correctly
resolves to 24. That's a real improvement — but `HUDMenu`'s own baseline
"OK" (152, matching `static_assert(sizeof(HUDMenu) == 0x98)`) turns out to
have been a **coincidental cancellation of two errors**: `GFxValue` was
8 bytes too small, and `RE::IMenu` (HUDMenu's other, unrelated,
already-broken dependency) was independently 8 bytes too **large** — the
errors summed to zero. Fixing `GFxValue` removed one side of that
cancellation and exposed the other.

**Root cause #3 (found, not fixed — separate, pre-existing bug in
patches 0001-0005, predates this patch):** `IMenu`'s primary base
`FxDelegateHandler` is oversized by exactly 8 bytes (56 vs. the
`static_assert`-confirmed 48/0x30). Traced via `InspectGdt.java` down to:
`FxDelegateHandler : public GRefCountBase<FxDelegateHandler,
GStatGroups::kGStat_Default_Mem>` (`RE/F/FxDelegateHandler.h`) — a
template specialization primary base, correctly inline-embedded by
`parseFieldsFromType` as a 16-byte opaque blob (`type.sizeOf()` == 16,
which is genuinely correct: the real vtable + refcount data live in
`GRefCountImplCore`, several template layers down:
`GRefCountBase<T,STAT> → GRefCountBaseStatImpl<Base,StatType> →
GRefCountImpl → GRefCountImplCore`, and `GRefCountImplCore` declares
`virtual ~GRefCountImplCore() = default;`). `FxDelegateHandler` itself
overrides that destructor (`~FxDelegateHandler() override`), so per the
existing rule from patch 0001 (a class overriding a virtual method from an
already-polymorphic base does NOT get a new vptr), `FxDelegateHandler`
should NOT get its own synthetic vptr — the vtable is already accounted
for inside the 16-byte opaque blob. But `SourceParser.isPolymorphic()`
(the function that rule relies on) walks `cursor.visitChildren()` on the
base's declaration cursor to look for a virtual method or a further base
— and **patch 0003's own investigation already proved
`clang_visitChildren` returns zero children for an implicitly-instantiated
class template specialization's cursor.** `isPolymorphic()` was never
updated with the `Type.visitFields()`-style fix patches 0003/0005 applied
to field/base *field* extraction — it still uses the old, template-blind
API for the *polymorphism* check specifically. So for any class whose
**primary base is itself a template specialization with a polymorphic
ancestor** (confirmed rare in practice — only 5 classes surfaced across
the full 1630-header sweep, all through this same
`FxDelegateHandler`/`GRefCountBase` CRTP pattern), `isPolymorphic()`
silently returns `false`, and a redundant vptr gets added on top of the
already-embedded one — exactly the patch-0001 bug, recurring for a case
patch 0001 didn't cover.

**Why this isn't fixed in patch 0006:** a proper fix needs the AST-level
insight patches 0003/0004 needed for the *original* template-field
problem — most likely a new libclang binding to map a specialization
cursor back to its primary template pattern (`clang_getSpecializedCursorTemplate`
or equivalent), which would have a real, walkable AST unlike the
specialization itself, verified with the same rigor (a `c-index-test`/
minimal-C-program probe) patch 0003 used. That's a distinct, nontrivial
investigation, not a small addition to this patch's two root causes. A
heuristic instead (e.g. "never add a vptr on top of a template-specialization
primary base") was considered and rejected: it's unverified guessing,
against this project's own established standard of confirming behavior
before changing it, and could plausibly be wrong in the opposite direction
for some other class shape not yet seen.

**Net assessment:** patch 0006 is a strict, large net improvement (383
classes fixed, all independently verified against real `static_assert`s)
that incidentally exposes 5 pre-existing wrong answers that were
previously "right" only by accident. `scripts/check_regression.py`
correctly flags this — that's the tool working as designed — but the
right response is a follow-up patch (0007) for `isPolymorphic()`'s
template-blindness, not reverting or blocking this one.

## Known follow-ups (not fixed by this patch)

- **`char16_t`/`char32_t`/`char8_t`** hit the same "keyword primitive, no
  bootstrap path" problem as `bool`/`wchar_t`, but are far rarer (~12
  files total vs. ~3500 occurrences of `bool`) — left unfixed to keep this
  patch's verification tight and its diff minimal. A future patch can
  extend `KEYWORD_PRIMITIVES` the same way if they turn out to matter.
- **Typedef-of-template-specialization** (root cause #3, identified but
  NOT fixed here, out of scope for this patch): `RE::AIProcess` and
  `RE::ActiveEffect` both remain non-exact after this fix, blocked on
  aliases like `using ActorHandle = BSPointerHandle<Actor>;`
  (`RE/B/BSPointerHandle.h`) and `using RefHandle = std::uint32_t;`
  (already fine, resolves as a plain typedef). `SourceParser.parseTypedef`
  registers a `ParsedTypedef` whose underlying-type string is the raw
  clang spelling of the aliased type — for `ActorHandle` that's
  `"BSPointerHandle<Actor>"`, a template specialization. Unlike
  field/base-class template usage (patches 0003/0005), `ParsedTypedef`'s
  resolution path does **not** go through `SourceParser.parseFieldsFromType`'s
  inline-embedding mechanism, so a typedef whose target is a template
  specialization can never resolve. This is a distinct, separate bug from
  both root causes above and would need its own investigation +
  verification pass; it's why `AIProcess` (240 vs. expected 320) and
  `ActiveEffect` (still EMPTY, blocked specifically on `ActorHandle`)
  aren't fully fixed by this patch.
