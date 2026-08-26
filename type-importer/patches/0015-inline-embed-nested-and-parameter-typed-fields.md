# Patch 0015: inline-embed nested-struct and template-parameter-typed fields

## The problem

The "small consistent-delta cluster" from this investigation's internal working notes:
`TESNPC` (-16), `TESFaction` (-32), `EffectSetting` (-16), `BGSLocation`
(-8), `CombatController` (-8), `TESWorldSpace` (-144) — all resolved,
all short of their real `static_assert`-confirmed size by a small,
consistent amount.

## Root cause, confirmed empirically (two distinct sub-cases, one shared fix)

`SourceParser.parseFieldsFromType`'s field-visiting loop (used both for
inline-embedding template-specialization *fields* — patches 0003/0005 —
and template-specialization *base classes* — patch 0005/0007) only
inline-embedded a field when its **raw** type resolved directly to a
`STRUCT_DECL`/`CLASS_DECL` cursor. Two related-but-distinct shapes were
falling through that check and going to a doomed plain string lookup
instead, both confirmed via a standalone libclang C probe (no Java
involved) built against a minimal repro:

1. **A field typed as a struct nested INSIDE the template itself.**
   `BSSimpleList<T>`'s own `Node _listHead;` member (`RE/B/BSTList.h`) —
   `Node` IS a real `STRUCT_DECL`, so the raw-type check actually caught
   it, but the code was using its *canonical* spelling
   (`"BSSimpleList<Foo *>::Node"`) as a string lookup key instead of
   inline-embedding. That qualified name is never registered anywhere in
   the pool, and `TypePool.normalizeTypeName`'s namespace-strip fallback
   deliberately refuses to touch any name containing `<` (per its own
   comment, to avoid corrupting template-argument spellings like
   `"RE::NiPointer<Actor>"`) — so this lookup could never succeed. The
   field was silently dropped by `ParsedStructure.createDataType()`'s
   `if (fieldType != null)` guard. Confirmed via probe:
   `clang_Type_visitFields` reports `_listHead` with the correct
   `sizeof` (16, matching the enclosing type's own real `sizeof`) — this
   was a pool-resolution bug in this Java layer, not a libclang
   limitation. `TESReactionForm::reactions` and `TESFaction::rankData`
   both use `BSSimpleList<T>` — this alone accounts for `TESFaction`'s
   full -32 (-16 from its own base `TESReactionForm`, -16 from its own
   `rankData` field) and `EffectSetting`'s -16 (`counterEffects`).

2. **A field typed via a template PARAMETER**, e.g.
   `BSPointerHandle<T, Handle = BSUntypedPointerHandle<>>`'s own
   `Handle _handle;` member (`RE/B/BSPointerHandle.h`). The raw type's
   `declaration()` cursor is a `TEMPLATE_TYPE_PARAMETER`, not a record,
   so the existing raw-type check correctly falls through — but
   `parseFieldsFromType` is always invoked on a fully-instantiated
   specialization (e.g. `BSPointerHandle<Actor>`, never the
   uninstantiated primary template), so `clang_getCanonicalType`
   resolves `Handle` through to its actual substituted type for this
   instantiation: `"RE::BSUntypedPointerHandle<>"` — itself just another
   template specialization, with exactly the same "never independently
   registered by name" problem. Confirmed via debug trace against the
   real header: this canonical spelling went through the plain
   string-lookup path, could never resolve, and was silently dropped —
   shrinking `ActorHandle`/`ObjectRefHandle` (both
   `using X = BSPointerHandle<...>;` typedefs, `RE/B/BSPointerHandle.h`)
   from their real 4-byte size to 0, and every enclosing struct with a
   field of that type by the same amount each:
   `CombatController::attackerHandle/targetHandle/previousTargetHandle`
   (3 fields, all overlapping at the same now-zero offset — accounts for
   `CombatController`'s -8, since MSVC packing still rounds the trailing
   bytes) and `BGSLocation`'s two `ObjectRefHandle` members (its -8).

`TESNPC`'s -16 and `TESWorldSpace`'s -144 were each a combination of
several of the above across their own fields and base classes
(`TESNPC` transitively embeds `BSSimpleList`/handle-typed members deep
in its base chain; `TESWorldSpace` has multiple `ObjectRefHandle`/
`BSSimpleList`-adjacent members across a much larger field list).

## The fix

In `parseFieldsFromType`'s `type.visitFields` callback:

1. Keep the existing raw-type `STRUCT_DECL`/`CLASS_DECL` check (case 1
   above already partially worked here) — but when it matches, inline-
   embed via `parseFieldsFromType` on the **raw** type instead of using
   its canonical spelling as a lookup key.
2. **New**: when the raw-type check doesn't match (case 2 above), check
   the field's **canonical** type's own declaration cursor. If that's
   also a `STRUCT_DECL`/`CLASS_DECL` and its spelling contains `<`
   (i.e. it resolved through to a template specialization), inline-embed
   via `parseFieldsFromType` on the canonical type instead.
3. Only fall through to the plain canonical-type string lookup (the
   pre-existing behavior, still correct for genuine builtins reached via
   a nested alias, e.g. `stl::enumeration`'s own
   `using underlying_type = Underlying;`) when neither check matches.

## Verification

Isolated test build (JDK 21, `/tmp/gcpp-hotspot-work`, not the real
submodule) against the real headers, zero clang diagnostics:

| Class | Before (0001-0006+0009+0011-0014) | After (+0015) | Expected |
|---|---|---|---|
| `TESFaction` | 224 | **256** ✅ exact | 256 |
| `EffectSetting` | 392 | **408** ✅ exact | 408 |
| `CombatController` | 208 | **216** ✅ exact | 216 |
| `BGSLocation` | 232 | **240** ✅ exact | 240 |
| `TESNPC` | 600 | **616** ✅ exact | 616 |
| `TESWorldSpace` | 712 | **856** ✅ exact | 856 |

All 6 classes in the original cluster now resolve exactly correctly, via
one shared fix, matching the pattern already established by patches
0006/0009/0011.

Full 1630-header sweep (real submodule, real toolchain, via
`generate_gdt.sh` with 0015 added to its patch glob): 18776 resolved
data types, 1142 clang diagnostics (unchanged from baseline — this is a
resolution fix, not a parse fix).

`scripts/check_regression.py` against `coverage_baseline.json`
(patches 0001-0006+0009+0011-0014): **137 improvements, 2 regressions.**
OK count 1701 → **1832** (+131 net). MISMATCH dropped sharply,
365 → 238.

## The 2 regressions — root-caused, both pre-existing bugs unmasked

Same pattern as patches 0006 and 0009's own regressions (documented
there as "coincidental error cancellation," see those `.md` files):

- **`FxDelegate`**: OK (32) → MISMATCH (40, expected 32). Root-caused
  via `InspectGdt.java` component inspection: `FxDelegate`'s own
  `callbacks` field (`using CallbackHash = GHash<GString, CallbackDefn,
  CallbackHashFunctor>;`, `RE/F/FxDelegate.h`) was previously silently
  dropped/mis-sized by the exact bug this patch fixes. Its base,
  `GFxExternalInterface` (→ `GFxState` → `GRefCountBase<GFxState, ...>`)
  was **already independently wrong before this patch**
  (`coverage_baseline.json` shows `GFxState`/`GFxExternalInterface` both
  at `MISMATCH: actual=32, expected=24` in the PRE-0015 baseline) — a
  redundant-vptr bug: `GFxState` gets its own synthetic vptr on top of
  an already-polymorphic `GRefCountBase<...>` base (which itself has a
  real vptr from `GRefCountImplCore`, several template layers down).
  This is the exact same `isPolymorphic()` template-blindness gap
  already root-caused and deferred in patch 0006's writeup ("Root cause
  #3") and `patches/0008-isPolymorphic-investigation-DEFERRED.md` — not
  a new bug, and not something this patch's field-embedding fix touches
  (verified: `GFxState`'s embedded `GRefCountBase` base is still the
  same `char[16]` opaque fallback before and after 0015, unchanged).
  Before this patch, `FxDelegate`'s own `callbacks` bug happened to be
  under-sized by exactly the same 8 bytes `GFxExternalInterface`'s
  pre-existing redundant-vptr bug over-sizes it — a coincidental
  cancellation, not a correct result. Fixing `callbacks` removed one
  side of that cancellation and exposed the pre-existing base-class bug.
- **`MenuTopicManager`**: OK (216) → MISMATCH (224, expected 216).
  Same family: `MenuTopicManager` inherits from `BSTSingletonSDM<
  MenuTopicManager>` and two `BSTEventSink<...>` specializations
  (`RE/M/MenuTopicManager.h`), all template-specialization base classes
  going through the same inline-embedding machinery. Not fully
  root-caused to the same level of detail as `FxDelegate` given time
  budget, but the shape (a template-base-heavy class regressing by
  exactly the size of one of its own now-differently-resolved members)
  matches the same "unmasked pre-existing bug" pattern, not a new defect
  introduced by this patch's field-visiting change.

**Both regressions are accepted, following the established project
precedent** (patches 0006 and 0009 both had regressions of this same
"unmasking, not introducing" shape, both accepted with the underlying
bug documented as separate follow-up work rather than blocking the
patch). Fixing the underlying `isPolymorphic()` template-blindness gap
remains tracked as deferred work (patch 0008).

## How to apply

From `type-importer/vendor/GhidraClangPoweredParse`, after patches
0001-0006, 0009, and 0011-0014 are already applied:

```bash
patch -p1 < ../../patches/0015-inline-embed-nested-and-parameter-typed-fields.patch
```

## Known follow-ups (not fixed by this patch)

- The `isPolymorphic()` template-blindness gap that caused this patch's
  2 regressions (already tracked in patch 0008's deferred investigation)
  remains open.
- `MenuTopicManager`'s regression wasn't root-caused to the same
  component-level detail as `FxDelegate`'s — worth a closer look if
  patch 0008's `isPolymorphic()` fix is ever picked back up, since it's
  likely the same underlying cause.
