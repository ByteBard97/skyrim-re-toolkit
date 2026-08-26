# Patch 0026: fix `GenerateGdt.java`'s coverage-report writer silently dropping resolved `Typedef` entries

**Note on numbering**: unlike patches 0001-0025, this one does not touch
the vendored `GhidraClangPoweredParse` submodule at all -- no `.patch`
file accompanies this doc. The bug and the fix are entirely in
`type-importer/tools/GenerateGdt.java`, part of this repo. It's numbered
into the same sequence for traceability (it was found investigating
T1-6, the same session as patch 0025) and because it changes
`coverage_baseline*.json` the same way a submodule patch would.

## Task: T1-6 (BACKLOG.md), investigate the 27 `UNRESOLVED` classes

`BSString` -- a load-bearing type used everywhere in CommonLibSSE-NG --
was one of 27 classes the coverage sweep reported as `UNRESOLVED`
("expected but absent from the resolved set", the worst status in
`check_regression.py`'s ranking). Total resolution failure on something
that fundamental was the obvious high-value lead in T1-6's list.

## Root cause: NOT a parser bug -- the parser already resolves these correctly

Before writing any fix, traced `BSString`'s actual behavior with
temporary `LOGGER.error` instrumentation (not committed) in
`SourceParser.parseTypedef` and `TypePool.resolve()`:

- `BSString` is `using BSString = BSStringT<char,
  static_cast<std::uint32_t>(-1), DynamicMemoryManagementPol>;`
  (`RE/B/BSString.h`) -- a typedef of a class-template specialization.
- `SourceParser.parseTypedef` already has a dedicated path for exactly
  this shape (added by an earlier patch in the 0011-0018/0021-0025
  range, referencing "patches/0008-fix-typedef-of-template-
  specialization.md" in its own comment): when the underlying type's
  spelling contains `<`, it routes through `parseFieldsFromType`
  (the same inline-embed mechanism fields/bases use) and constructs the
  `ParsedTypedef` via its `inlineType` constructor, whose
  `getDependencies()` returns `List.of()` -- no name-keyed dependency to
  ever get stuck on.
- Confirmed via instrumentation at both small-header scale (3 headers)
  and full 1630-header scale: `present=true`,
  `stillOutstanding=false` after the resolution loop,
  `inDtmAlready=true` -- `BSString` **is** fully resolved into the
  in-memory `StandAloneDataTypeManager` every time, and
  `GenerateGdt.main`'s commit loop reports `0 failed` committing it (and
  everything else) into the real `FileDataTypeManager` / `.gdt` output.

The actual bug is in `GenerateGdt.writeCoverageReport` (the
`--report-csv` writer `coverage_report.py` reads): its filter kept only
`t instanceof Composite` (struct/union) entries from the committed type
list. A `using`-alias to a template specialization commits as a
`TypedefDataType` **wrapping** a Composite, but the `Typedef` itself is
not a `Composite` -- so `BSString` (and every other typedef-of-template-
specialization) was silently excluded from both the CSV and the
`unresolved.txt` companion file. `coverage_report.py`'s UNRESOLVED
bucket is defined as "expected but absent from the resolved set" --
absent from the *report*, not absent from the *actual resolved data*.
This was a pure measurement gap: the parser has had the real fix since
some point in the 0011-0025 range; nothing about `BSString`'s resolution
itself needed changing.

(`GenerateGdt.writeJsonReport`, the separate `--report-json` emitter
T1-3 built, already walks Composite/Enum/**TypeDef** correctly -- this
gap only ever affected the older CSV path.)

## Fix

`writeCoverageReport`'s filter: `t instanceof Composite` ->
`t instanceof Composite || t instanceof TypeDef`. `TypeDef.getLength()`
returns the underlying type's length, which is exactly what
`coverage_report.py` needs to compare against a `static_assert`.

## Verification

Full 1630-header sweeps on all three runtimes (AE, SE, VR), patch set
0001-0025 (submodule, unchanged) + this fix (tools/GenerateGdt.java
only), via `scripts/generate_gdt.sh`-equivalent manual build +
`scripts/coverage_report.py` + `scripts/check_regression.py` against
each runtime's previously-committed baseline:

- **AE**: 0 regressions, 10 improvements. UNRESOLVED 27 -> 17, OK 2082 -> 2091.
- **SE**: 0 regressions, 10 improvements (identical class list). UNRESOLVED 27 -> 17.
- **VR**: 0 regressions, 10 improvements (identical class list, one extra UNRESOLVED unrelated to this fix). UNRESOLVED 27 -> 18.

Improvements (all three runtimes): `ActorHandlePtr`, `AnimHandler`,
`AnimResponse`, `BSString`, `GPointD`, `GPointF`, `GRectD`, `GRectF`,
`hkQuadReal` (all UNRESOLVED -> OK), plus `SkyObject` (UNRESOLVED ->
MISMATCH -- a rank improvement per `check_regression.py`'s ordering,
though not yet fully correct; a nested-alias case, not investigated
further here).

`coverage_baseline.json`, `coverage_baseline_se.json`,
`coverage_baseline_vr.json` all updated -- also now much larger, since
the fix surfaces thousands of previously-invisible `TypeDef`-backed
`NO_GROUND_TRUTH`/`EMPTY` entries that were always resolved but never
reported (baseline entry count 2814-ish -> 4869/4870); this is expected
visibility growth, not noise -- `check_regression.py` confirms 0
regressions on every previously-tracked entry.

## Remaining T1-6 scope (not addressed by this fix)

Of the original 27 `UNRESOLVED`:
- **9-10 fixed by this patch** (the typedef-of-template-specialization
  family: `BSString`, `GPointD/F`, `GRectD/F`, `hkQuadReal`,
  `ActorHandlePtr`, `AnimHandler`, `AnimResponse`, plus `SkyObject`
  moving to MISMATCH).
- **`IHandlerFunctor`, `BSTObjectDictionary`** -- expected to stay
  UNRESOLVED by design (base class templates never independently
  registered as standalone types in the inline-embed architecture; see
  BACKLOG.md's T1-6 entry).
- **10 nested-type entries** (`Argument::Type`,
  `AutoRegisterFactory::AutoRegisterFactory`,
  `BGSNamedPackageData::Data`, `BGSRefAlias::GenericFillData::Padding`,
  `GHashNode::NodeAltHashF`, `GHashNode::NodeHashF`,
  `GHashNode::NodeRef`, `GHashSetBase::TableType`,
  `GHashSetBase::const_iterator`, `INPUT_DEVICES::INPUT_DEVICE`) --
  not investigated this pass; a different shape (qualified/nested
  member types) from the typedef-of-template-specialization pattern
  this fix addresses.
- **4 policy-class entries with commented-out static_asserts**
  (`HandlerCreationMissPolicy`, `NoInitializationPolicy`,
  `ResponseDefinitionMissPolicy`, `PreloadResponsesInitializationPolicy`)
  -- pure-vtable base-class templates, likely by-design-UNRESOLVED like
  `IHandlerFunctor`/`BSTObjectDictionary` above; not confirmed.
- **`RUNTIME_DATA2`** -- confirmed a genuine name collision: THREE
  unrelated classes (`Console`, `MapMenu`, `NiCamera`) each declare their
  own nested `RUNTIME_DATA2` struct with different sizes (no assert,
  0x138, and 0x38 respectively); `mine_static_asserts.py` picks one
  arbitrarily as "the" expected size for the flat name. A real, separate
  bug in the ground-truth miner (or in how nested-type names are
  recorded), not something this fix's mechanism touches. Left for a
  future pass.

These remaining ~17 are a smaller, more varied set than the original 27
and don't share one root cause the way the typedef-of-template-
specialization family did -- a good stopping point for this session
rather than forcing a single narrative across unrelated shapes.
