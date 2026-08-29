# Patch 0031: resolve C++ reference-type (`T&`) fields

**Status: accepted.** Root-caused and fixed via `type-importer/vendor/GhidraClangPoweredParse`'s
`TypePool.resolveComposite`.

## Background

Auditing the coverage sweep's `EMPTY` bucket (resolved classes with `actual<=1`, i.e. reported
as an empty 1-byte placeholder) for the docs-site's "known limitations" writeup surfaced that
this bucket mixes two very different things:

1. Classes that genuinely compile to `sizeof==1` by design — pure enum-namespacing structs
   (`struct ACTOR_AGGRO_RADIUS { enum { kWarn, kWarnAndAttack, kAttack }; };`, real `sizeof==1`
   in C++, since a class with no data members still needs a unique address), RAII guards and
   utility classes with only static/deleted methods. These are correct output, not bugs.
2. Classes with a **known-wrong** size per their own header's `static_assert` — a real gap.

Splitting the AE `EMPTY` bucket (1,046 entries) by whether a `static_assert` exists to check
against found exactly **9** in category 2 — `AttachedScript`, `BGSNumericIDIndex`,
`BSReadLockGuard`, `BSScrapArrayAllocator`, `BSSpinLockGuard`, `BSWriteLockGuard`,
`GFxFunctionHandler::Params`, `GFxResourceLib::ResourceSlot`, `LogEvent`.

## Root cause

Three of the nine (`BSReadLockGuard`, `BSWriteLockGuard`, `BSSpinLockGuard`,
`type-importer/vendor/CommonLibSSE-NG/include/RE/B/BSAtomic.h`) share an identical shape: a
single private reference-type member, e.g.

```cpp
class BSReadLockGuard
{
public:
    BSReadLockGuard() = delete;
    // ...
private:
    BSReadWriteLock& _lock;  // 0
};
static_assert(sizeof(BSReadLockGuard) == 0x8);
```

`SourceParser.parseStruct`'s `FIELD_DECL` case stores `cursor.type().spelling()` verbatim as the
field's type name — for `_lock` this is `"BSReadWriteLock &"` (clang spells a reference with a
trailing `&`, same convention as its `"Foo *"` pointer spelling). `TypePool.resolveComposite`
had a branch to strip a trailing `*` and wrap the resolved base type in a `PointerDataType`, but
**no equivalent branch for a trailing `&`** — so `getType("BSReadWriteLock &")` fell through to
`null`, `ParsedStructure.createDataType` silently skips a field whose type doesn't resolve
(`if (fieldType != null)`), and since `_lock` was each class's *only* field, the struct came out
with zero fields — collapsing to Ghidra's minimum `sizeof==1` for an empty structure.

The same mechanism silently swallows the field for the other 6 confirmed cases too, though their
class bodies aren't identical (a reference-type member is not their *only* content in every case
— not fully traced per-class here, see "Remaining work").

## Fix

Mirror the existing pointer-handling branch in `TypePool.resolveComposite` for a trailing `&`:
a C++ reference has the exact same object-layout representation as a pointer in both the Itanium
and MSVC ABIs (stored as the referent's address, same size), and Ghidra has no reference
`DataType` of its own, so wrapping the resolved base type in `PointerDataType` is the correct
model — identical to what the pointer branch already does.

```java
if (name.endsWith("&")) {
    String baseName = name.substring(0, name.length() - 1).trim();
    DataType baseType = getType(baseName);
    if (baseType != null) {
        return new PointerDataType(baseType, this.dtm);
    }
    return new PointerDataType(this.dtm);
}
```

## Verification

**Isolated reproduction first** (per this project's own established methodology): built a
2-header (`RE/B/BSAtomic.h`) test archive before and after the fix.

- Before: `BSReadLockGuard,1` / `BSWriteLockGuard,1` / `BSSpinLockGuard,1` — all EMPTY,
  `"BSReadWriteLock &"` / `"BSSpinLock &"` confirmed present in `report.csv.unresolved.txt` as
  unfulfilled dependencies (temporary `LOGGER.error` instrumentation, reverted after this
  investigation, confirmed the exact string and confirmed `getType()` was in fact reaching
  `resolveComposite` with it and returning null pre-fix, `true` post-fix).
- After: `BSReadLockGuard,8` / `BSWriteLockGuard,8` / `BSSpinLockGuard,8` — all now match their
  own header's `static_assert(sizeof(...) == 0x8)` exactly. Nothing left unresolved for these
  three names.

**Full 1630-header sweep, all three runtimes** (AE/SE/VR): 0 regressions; `BSReadLockGuard`,
`BSWriteLockGuard`, `BSSpinLockGuard` flip EMPTY → OK on all three (identical set, since
`BSAtomic.h` has no runtime-specific `#ifdef` branching around these classes). No other class
anywhere in any of the three 6266-entry snapshots changed. See the repo's committed sweep run
for the exact before/after OK counts.

## Remaining work (honestly scoped, not chased further this pass)

The other 6 of the 9 confirmed-wrong `EMPTY` entries (`AttachedScript`, `BGSNumericIDIndex`,
`BSScrapArrayAllocator`, `GFxFunctionHandler::Params`, `GFxResourceLib::ResourceSlot`,
`LogEvent`) were **not** individually root-caused this pass — a read of each definition shows
at least two more distinct mechanisms, neither touched by this patch:

- `AttachedScript` (`public BSTPointerAndFlags<BSTSmartPointer<Object>, 1>`, zero own fields)
  and `GFxResourceLib::ResourceSlot` (`public GRefCountBase<ResourceSlot, ...>`, substantial own
  fields) both derive from a template-specialization base with real content — the same *shape*
  patch 0025 fixed for other classes, but these two still fail, so 0025's fix doesn't cover every
  instance of the pattern (untraced why).
- `BGSNumericIDIndex`'s real content (a `stl::enumeration<Flags, std::uint8_t> flags` member) is
  buried three levels deep in a nested anonymous-union-inside-anonymous-struct-inside-anonymous-
  union — a distinct nested-anonymous-type shape, unrelated to references or base classes.
- `LogEvent` has two forward-only declarations elsewhere in the tree
  (`IVirtualMachine.h:35`, `ErrorLogger.h:10`) plus its real definition in `RE/L/LogEvent.h` —
  consistent with (not confirmed as) a first-registration-wins collision where the parser
  registers the empty forward declaration before ever visiting the real one, the same *class* of
  bug patch 0025's `isPolymorphic` fix and this project's various "wrong declaration picked"
  patches have hit before, just not confirmed here.
- `BSScrapArrayAllocator`/`GFxFunctionHandler::Params` not investigated this pass.

None of the above was attempted as a fix — diagnosis only, to leave a precise trail rather than
a vague "different mechanism." Per this project's own "two focused attempts, then defer"
discipline: this pass fixed the one clean, reproducible, shared-root-cause cluster it found; the
remaining 6 split into at least three further investigations, each its own scoped task.

`coverage_report.py` was also changed (see the docs-sync commit) to print `EMPTY, CONFIRMED
WRONG` and `EMPTY, UNVERIFIED` as two distinct sections instead of one undifferentiated `EMPTY`
bucket — so a future sweep makes this same "some of these are real bugs, most are not" fact
checkable at a glance instead of requiring a fresh manual audit each time.
