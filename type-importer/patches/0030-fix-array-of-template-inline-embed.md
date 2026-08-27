# Patch 0030: fix array-of-template-specialization fields inside recursively inline-embedded types

**Status: real bug, root-caused and fixed with strong evidence. Net effect
is a massive reduction in two classes' MISMATCH deltas (recovering
essentially their entire missing content), but NOT a full fix -- both
classes remain MISMATCH by a small residual gap (216 and 8 bytes) whose
cause is different and out of scope for this pass. Documented honestly
rather than forced further, per this project's "two focused attempts,
then defer" discipline.**

## Task: T1-11 (BACKLOG.md)

Patch 0029 fixed one mechanism behind the 30-entry MISMATCH bucket but
explicitly left two huge outliers uninvestigated: `SkyrimVM` (actual 2208,
expected 0x8978 = 35192, a ~33KB gap) and `VirtualMachine` (actual 5392,
expected 0x9518 = 38168, a ~33KB gap) -- both far larger deltas than
every other MISMATCH class in the bucket (single-digit-to-low-double-digit
bytes).

## Root cause, confirmed empirically

Both real static_asserts (`RE/S/SkyrimVM.h:278`, `RE/V/VirtualMachine.h:243`)
were checked against the actual header content first, not assumed correct:
both are exact, matching this patch's own before/after measurements to the
byte. So the ground truth is right; the parser's `actual` value is what's
wrong.

Both classes have one or more fields of type `BSTStaticFreeList<T, SIZE>`
(`RE/B/BSTFreeList.h`) -- a fixed-capacity free-list template with a
**non-type** template parameter (`SIZE`), whose own real content is a
single field: `BSTFreeListElem<T> elems[SIZE]`. `SkyrimVM` has four such
fields (`renderSafeFunctorPool1`/`2`, `postRenderFunctorPool1`/`2`, each
`BSTStaticFreeList<BSTSmartPointer<SkyrimScript::DelayFunctor>, 512>`,
0x2018 = 8216 bytes each -- 4 x 8216 = 32864, matching almost the entire
32984-byte gap). `VirtualMachine` has one:
`BSTStaticFreeList<FunctionMessage, 1024>` (`funcMsgPool`).

Confirmed via `GCPP_DEBUG_DROPPED` tracing (temporary instrumentation,
reverted) that this is NOT the "field silently dropped because its type
never resolves" failure mode patches 0026/0029 already fixed elsewhere --
every field in `SkyrimVM` resolved to a non-null `DataType` in
`ParsedStructure.createDataType()`. The loss happens one recursion level
deeper: `SkyrimVM`'s own `renderSafeFunctorPool1` field (type
`BSTStaticFreeList<...>`, a template specialization) is correctly routed
through `SourceParser.parseFieldsFromType`'s recursive inline-embedding
mechanism (the same one patches 0025/0029 already extended for base-
content recovery and typedef'd-array fields). But `parseFieldsFromType`'s
own internal field-visiting loop had no handling for a field whose type is
a **C-style array of a template-specialization element**
(`BSTFreeListElem<T> elems[SIZE]`) -- that shape reports `CONSTANT_ARRAY`
via libclang, not `RECORD`/`UNEXPOSED`, so neither of the loop's two
inline-embed checks (raw-type STRUCT_DECL/CLASS_DECL, canonical-type
STRUCT_DECL/CLASS_DECL) ever matched. It fell through to the final
plain-string-typeName fallback, which recorded the field's canonical
array-type spelling as a literal string (e.g.
`"RE::BSTFreeListElem<RE::BSTSmartPointer<...>> [512]"`). That string is
never independently registered as a `ParsedType` (nothing at any scope
ever gets registered under that exact templated array-element spelling),
so `TypePool.getType()` for it returns `null`, and this ONE field --
`elems`, the entirety of `BSTStaticFreeList`'s own real content -- is
silently dropped when `BSTStaticFreeList`'s own inline-embedded
`ParsedStructure` builds its Ghidra `DataType`. The enclosing
`BSTStaticFreeList` sub-structure ends up as just its opaque
base-contributed prefix (24 bytes, `BSTFreeList<T>`'s own vptr+lock+free
pointer, correctly recovered by patch 0029's `opaque_base_prefix`
mechanism) with none of its actual 512- or 1024-element array.

This is **exactly the same shape patch 0016 already fixed once**, at a
different call site: patch 0016's own fix (`SourceParser.parseStruct`'s
top-level `FIELD_DECL` case) peels a `CONSTANT_ARRAY` field type down to
its element type before checking for template-specialization
inline-embedding, so `NiPointer<bhkShape> shapes[2]`-shaped top-level
fields resolve correctly. That peel-and-recurse step was never mirrored
inside `parseFieldsFromType`'s own recursive field-visiting loop -- so an
array-of-template field belonging to a type that is ITSELF only reached
via inline-embedding (one recursion level in) fell through this exact gap.

## The fix

Mirror patch 0016's array-peel pattern inside `parseFieldsFromType`'s
field-visiting loop: before either inline-embed check (raw or canonical),
peel a `CONSTANT_ARRAY` field type down to its element type and capture
the element count. If the peeled element type inline-embeds (either
check), pass the captured `arrayCount` through the existing 7-arg
`FieldInfo` constructor (already supported by
`ParsedStructure.createDataType()` since patch 0016 -- just never fed a
nonzero value from this call site) so `createDataType()` wraps the
recovered inline-embedded element type in an `ArrayDataType` at the
correct multiplicity, exactly as the top-level case already does. The
final plain-string fallback deliberately keeps using the *original*
(unpeeled) field type's canonical spelling, not the peeled one -- an array
of a plain (non-template) element type was already handled correctly via
`TypePool`'s own `ARRAY_SUFFIX` regex on the full `"Type [N]"` spelling,
and peeling there would only lose the bracket that regex depends on.

## Verification

Isolated reproduction first (2-header parse of just `RE/S/SkyrimVM.h` +
`RE/V/VirtualMachine.h`), before any full sweep:

| Class | Before | After | Expected |
|---|---|---|---|
| `SkyrimVM` | 2208 | **34976** | 35192 |
| `VirtualMachine` | 5392 | **38160** | 38168 |

Full 1630-header sweeps on all three runtimes (AE/SE/VR), patch set
0001-0029 + this patch: **0 regressions, 0 status-flip improvements**
(`check_regression.py`, which tracks OK/MISMATCH/EMPTY/UNRESOLVED/
NO_GROUND_TRUTH *status* transitions -- both classes stay `MISMATCH`
before and after, since neither closes its full residual gap) -- but the
underlying `actual` values for both classes moved dramatically closer to
correct in every runtime, identically: `SkyrimVM` 2208->34976/35192,
`VirtualMachine` 5392->38160/38168, same numbers on AE, SE, and VR (both
classes are runtime-invariant in this respect -- no `#if
ENABLE_SKYRIM_*` branching touches these particular fields). No other
class in any of the three 6266-entry snapshots changed at all -- this fix
is precisely scoped to the array-of-template-in-recursive-embed shape,
with no observed side effects elsewhere in the sweep.

`coverage_baseline{,_se,_vr}.json` updated to reflect the new `actual`
values for `SkyrimVM`/`VirtualMachine` (still `MISMATCH`, now for a much
smaller and better-understood reason).

## Residual gap, not investigated this pass

`SkyrimVM` remains short by 216 bytes (34976 vs 35192); `VirtualMachine`
by 8 bytes (38160 vs 38168). Both are far smaller and structurally
different from the ~33KB gap this patch closed, and neither was
investigated -- two focused attempts on the *array* mechanism (this
patch's own two rounds of construction, verified via the isolated
reproduction before the full sweep) is this pass's honest limit, per this
project's "two focused attempts, then defer" rule. Candidate leads for a
future pass, unverified: `VirtualMachine`'s 8-byte gap is a single
pointer/field's worth, plausibly one more field of the same recursive
inline-embed class hitting an unrelated edge case (its `funcMsgPool` is
the only `BSTStaticFreeList` field, already fixed by this patch, so the
gap is elsewhere in the class); `SkyrimVM`'s 216-byte gap is a more
unusual size (216 = 0xD8, not obviously one field) and wasn't traced at
all.

## How to apply

From `type-importer/vendor/GhidraClangPoweredParse`, after patches
0001-0029 are already applied:

```bash
patch -p1 < ../../patches/0030-fix-array-of-template-inline-embed.patch
```
