# Patch 0028: T1-8 -- root-cause the ~10 nested-type UNRESOLVED classes left after patch 0026

**Status: accepted, one real submodule fix + two script fixes, all
verified via full 1630-header sweeps on AE/SE/VR: 0 regressions, 5
improvements per runtime.** This is patch 0028's own submodule `.patch`
(the one real parser bug found); two other bugs found during this same
investigation live in this repo's own `tools/GenerateGdt.java` and
`scripts/mine_static_asserts.py` and don't need a submodule patch,
following the precedent set by patches 0026/0027.

## Task

BACKLOG.md's T1-8: patch 0026 closed the `BSString`-shaped typedef-of-
template-specialization family (27 -> 17/18 `UNRESOLVED`) but only
*categorized* the remaining bucket in one paragraph -- it never
root-caused individual members the way patch 0027 did for the
`RUNTIME_DATA2` collision (itself one member of this same bucket, closed
separately). This patch investigates every remaining member for real.

## Regenerating the bucket (don't trust the old list)

A fresh full-1630-header AE sweep against the current baseline (patch
0027's state, `9942adb`) reproduced `2,092 OK` exactly, confirming the
sweep is reproducible, then showed the current real `UNRESOLVED` bucket
is **16** classes, not the ~17-18 patch 0026 described (numbers move):
`RUNTIME_DATA2` is gone (closed by 0027, as expected); everything else
0026 named is still present, unchanged.

## Root cause 1 (real parser bug, fixed): `parseUnion` never recurses into nested type declarations

`SourceParser.parseStruct`'s child-visitor has explicit cases for nested
`STRUCT_DECL`/`CLASS_DECL`/`UNION_DECL`/`ENUM_DECL`/`TYPEDEF_DECL`
children, recursively registering each as its own standalone type.
`SourceParser.parseUnion`'s child-visitor had **no such cases at all** --
it only ever looked at `FIELD_DECL`. Any named type declared directly
inside a union body (not further nested inside a struct within that
union) was therefore silently never visited, let alone registered,
regardless of whether the union itself was inside a template.

Confirmed with a real, non-template example:
`RE::BGSRefAlias::GenericFillData::Padding` (`RE/B/BGSRefAlias.h`) --
`BGSRefAlias` is an ordinary class (not a template), `GenericFillData` is
a `union` field inside it, and `Padding` is a `struct` declared directly
inside that union, with its own `static_assert(sizeof(Padding) == 0x18)`.
`BGSRefAlias` (a real, concrete class, visited via `parseStruct` from the
top-level declaration walk) correctly recurses into its nested
`GenericFillData` union via the existing `case UNION_DECL ->
parseUnion(...)`, but `parseUnion` then had nothing to do with a nested
`STRUCT_DECL` child, so `Padding` was dropped on the floor.

**Fix**: mirror `parseStruct`'s nested-declaration cases into
`parseUnion`'s child-visitor (`STRUCT_DECL`/`CLASS_DECL` ->
`parseStruct`, `UNION_DECL` -> `parseUnion` recursively, `ENUM_DECL` ->
`parseEnum`, `TYPEDEF_DECL`/`TYPE_ALIAS_DECL` -> `parseTypedef`), passing
the same `category` `parseStruct` already threads through for its own
nested types.

**Effect, verified via full sweep**: fixes not just `Padding` itself but
its two containing types, which had been quietly wrong because of the
gap -- `BGSRefAlias::GenericFillData` (the union) was `EMPTY` (its
largest member, `Padding`, was invisible so the union's real size was
never contributed), and `BGSRefAlias` itself (the outer class) was
`MISMATCH` (same missing-content chain, one level further out). All
three now resolve `OK`.

## Root cause 2 (real report-writer bug, fixed): `writeCoverageReport`'s type filter excludes Enum

`tools/GenerateGdt.java`'s CSV coverage-report writer (used by
`coverage_report.py`, the mechanism this whole bucket is measured
through) only included `Composite` (struct/union) and `TypeDef` instances
-- the exact same shape of bug patch 0026 fixed for `TypeDef`, this time
for `ghidra.program.model.data.Enum`. A real, resolved, correctly-sized
`EnumDataType` (e.g. a nested `enum class Type` inside a non-template
struct) was committed to the DTM successfully but never appeared in
either the CSV or `unresolved.txt` -- invisible to `coverage_report.py`,
misread as `UNRESOLVED` even though the parser had it right all along.
(The newer `--report-json` writer, added for T1-3, already handled
`Enum` correctly -- this CSV writer had simply fallen out of sync with
it.)

Confirmed with two real examples:
- `RE::BSScript::ByteCode::Argument::Type` (`RE/U/UnlinkedTypes.h`) -- a
  nested `enum class Type : std::uint32_t` inside the non-template
  `Argument` struct, with its own `static_assert(sizeof(Type) == 0x4)`.
  Never appeared under any name in the CSV at all -- purely invisible,
  not misnamed.
- `RE::INPUT_DEVICES::INPUT_DEVICE` (`RE/I/InputDevices.h`) -- a plain
  `enum INPUT_DEVICE` nested inside the non-template `INPUT_DEVICES`
  struct. This one is a more interesting case: a namespace-scope
  `using INPUT_DEVICE = INPUT_DEVICES::INPUT_DEVICE;` alias right below
  it DOES get independently registered (as a `TypedefDataType`, which the
  filter already included), so `INPUT_DEVICE` (bare, no `::`) showed up
  in the CSV with the *correct* size (4) the whole time -- but ground
  truth mines the qualified name from where the `static_assert` is
  actually written (`INPUT_DEVICES::INPUT_DEVICE`), and
  `coverage_report.py` does exact-string-key comparison, so the correct
  data existed under the "wrong" key and never matched.

**Fix**: add `|| t instanceof ghidra.program.model.data.Enum` to the CSV
writer's filter, matching the JSON writer.

## Root cause 3 (real ground-truth-mining bug, fixed, currently zero-count-impact): `mine_static_asserts.py` double-qualifies a self-referential `static_assert`

`AutoRegisterFactory::AutoRegisterFactory` was ground-truth-mined as a
self-referential double name. Real cause: `AutoRegisterFactory.h` writes
`static_assert(sizeof(AutoRegisterFactory) == 0x8);` **inside the class's
own body**, referring to itself via C++'s injected-class-name rule (valid,
common style) rather than to a nested member. `mine_static_asserts.py`'s
`qualify()` unconditionally prefixes any bare name found inside a record
scope with that scope's full path, so it produced
`AutoRegisterFactory::AutoRegisterFactory` instead of the correct
`AutoRegisterFactory`.

Checked for broader impact before fixing: only **one** entry in the
entire 2,149-key AE ground-truth map matches this self-referential
shape (verified by comparing each qualified key's last two `::`-
separated segments), so this isn't a hidden multi-class bug --
`AutoRegisterFactory` (`template <class Parent, class Manager> class
AutoRegisterFactory : public Parent`) is also a template class never
independently registered by the top-level declaration walker regardless
(same mechanism as Root cause 4 below), so this fix's *count* impact is
zero: `AutoRegisterFactory` stays `UNRESOLVED` either way, just under
its real, correct, single-qualified name instead of a nonsensical
doubled one. Fixed anyway as a genuine correctness bug in the
ground-truth miner, in case a future header adds a second instance of
this pattern on a class the parser *can* resolve.

**Fix**: in `qualify()`, when the name being qualified equals the
current innermost `record_stack` frame's own name, return the stack's
existing qualified path unchanged rather than appending the name again.

## Root cause 4 (confirmed by-design, no fix): template-nested members are never independently registered

The remaining 13 (`AutoRegisterFactory`, `BGSNamedPackageData::Data`,
`BSTObjectDictionary`, `GHashNode::NodeAltHashF`, `GHashNode::NodeHashF`,
`GHashNode::NodeRef`, `GHashSetBase::TableType`,
`GHashSetBase::const_iterator`, `HandlerCreationMissPolicy`,
`IHandlerFunctor`, `NoInitializationPolicy`,
`PreloadResponsesInitializationPolicy`, `ResponseDefinitionMissPolicy`)
all share one confirmed mechanism, matching what patch 0026 already
documented for `IHandlerFunctor`/`BSTObjectDictionary`: each is a nested
member of an **uninstantiated class template** (`GHashNode<C,U,Hash>`,
`GHashSetBase<...>`, `BGSNamedPackageData<Parent>`, `AutoRegisterFactory
<Parent,Manager>`, and the four `*Policy` classes, all real templates
per their own headers).

Confirmed structurally, not just by pattern-matching: `SourceParser`'s
top-level declaration walker (`visitDeclarations`) only has switch cases
for `STRUCT_DECL`/`CLASS_DECL` (concrete, non-template records) --
libclang emits a template class definition as a different cursor kind
entirely, which this walker has no case for and silently skips via its
`default` branch. `parseStruct`/`parseUnion` (which DO recurse into
nested declarations, including as of this patch) are only ever reached
for a template's *nested members* if something first calls them on the
outer template -- which never happens, because the outer template cursor
is never dispatched to `parseStruct` in the first place. A concrete
instantiation of one of these templates used as a field elsewhere (e.g.
`hkInplaceArray<T,N>` embedding, patch 0025's mechanism) is handled by
an entirely separate code path (`parseFieldsFromType`, the
inline-embed-by-value mechanism) that inlines the instantiation's
*contents* directly into the containing struct -- it does not
independently register the instantiation's own nested member types
under a standalone name. So these 13 are unresolvable under the current
inline-embed architecture by design, not a bug -- reaching them would
require either instantiating and registering templates independently
(a much larger architectural change) or special-casing each one, neither
of which fits this patch's scope. Left as documented, honest
`UNRESOLVED` entries.

## Verification

Full 1630-header sweeps, all three runtimes (AE/SE/VR), against the
patch-0027 baseline (`9942adb`):

- **0 regressions, 5 improvements, identical set on every runtime**:
  `Argument::Type` (UNRESOLVED -> OK), `INPUT_DEVICES::INPUT_DEVICE`
  (UNRESOLVED -> OK), `BGSRefAlias::GenericFillData::Padding`
  (UNRESOLVED -> OK), `BGSRefAlias::GenericFillData` (EMPTY -> OK),
  `BGSRefAlias` (MISMATCH -> OK).
- OK counts: AE 2,092 -> 2,097; SE 2,110 -> 2,115; VR 2,111 -> 2,116.
- UNRESOLVED bucket: 16 -> 13 on all three runtimes (all
  runtime-independent -- these are structural/naming bugs, not
  macro-guard-dependent ones).
- `coverage_baseline*.json` updated on all three; each now also carries
  many more `NO_GROUND_TRUTH` entries than before (Enum types are now
  visible in the CSV broadly, not just the two named above) -- expected,
  same non-regression side effect patch 0026 documented for `TypeDef`.

## How to apply

From `type-importer/vendor/GhidraClangPoweredParse`, after patches
0001-0027 (skipping 0007/0008/0020, which are superseded/deferred) are
already applied:

```bash
patch -p1 < ../../patches/0028-fix-parseunion-nested-types.patch
```

The `GenerateGdt.java` and `mine_static_asserts.py` fixes are plain edits
to this repo's own files, not submodule patches -- already committed
alongside this doc.
