# Patch 0011: record-qualified type registration (kills the name-collision defect family)

## The defect family

TypePool registered every struct/union under its **bare** cursor spelling
(`structCursor.spelling()`), and patch 0006's normalization stripped
references down to bare identifiers to match. But nested-type names in
CommonLibSSE-NG collide massively: 25 distinct classes declare an
unrelated nested `struct Data`, plus dozens more collisions on
`Type`/`Value`/`Flag`/`Flags`-style names. All of them shared one
registration key, and `addParsedType`'s keep-more-fields heuristic (plus
registration order) silently picked one winner for every reference in
the program.

Confirmed consequences before this patch:

- `BGSSoundOutput` regressed 64->72 under patch 0009 purely because 0009
  shifted registration order and a different `Data` won (the one known
  regression in 0009's acceptance).
- Five classes (`BGSDirectionalAmbientLightingColors`, `BGSLightingTemplate`,
  `Directional`, `INTERIOR_DATA`, `hkpConstraintInstance`) resolved
  *differently on GitHub's CI runner than on the dev machine* -- same code,
  different filesystem enumeration order, different collision winners.
- Patch 0007's blocker: `anon_tmpl_` synthetics keyed by hash of
  canonical-vs-sugared spellings of the same instantiation.
- An unknown number of classes were "OK" by coincidence: e.g.
  `BSScript::Variable` measured a correct-looking 16 only because a
  *different, simpler* union had won the bare `Value` key and happened to
  also be 8 bytes -- the real `Variable::Value` never composed at all.

## The fix (four coordinated pieces)

1. **Registration** (`SourceParser.recordQualifiedName`): structs/unions
   register under their record-parent-qualified name
   (`BGSSoundOutput::Data`), walking `semanticParent()` chains of
   class/struct/union/class-template cursors. Namespaces stay excluded
   (they map to CategoryPath), matching clang's own printing.
2. **References** (`SourceParser.fieldTypeSpelling`): a nested type is
   spelled BARE at local reference sites (confirmed empirically:
   `BGSSoundOutput`'s own `Data data;` field spells as `Data`, canonical
   `RE::BGSSoundOutput::Data`). Field, base-class, and typedef-underlying
   references whose declaration is nested in a record now use the
   canonical (fully-qualified) spelling. Templates/anonymous spellings
   are left untouched (separate inline-embedding mechanism).
3. **Resolution** (`TypePool.getType` progressive qualifier peeling): a
   `::`-qualified reference tries successively shorter suffixes, longest
   (most qualified) first, before the legacy bare-name fallback -- so
   `RE::BGSSoundOutput::Data` finds `BGSSoundOutput::Data`, while
   plain-namespace cases (`REX::W32::CRITICAL_SECTION` -> bare
   `CRITICAL_SECTION`) keep working exactly as under 0006. Plus an
   exact-name DTM lookup fallback in `resolveType`, because Ghidra's
   `DataTypeParser` tokenizer cannot find types whose name contains `::`.
4. **Ground truth** (`scripts/mine_static_asserts.py`): a brace-depth
   record-scope tracker qualifies bare `static_assert(sizeof(Data) == N)`
   asserts written inside a class body the same way
   (`BGSSoundOutput::Data`), so the coverage sweep compares qualified to
   qualified. Bonus: ~125 nested classes whose asserts were previously
   EXCLUDED as ambiguous collisions gained usable ground truth, and the
   old miner's silent conflation of two different `MegaBlockPage` classes
   is now split correctly.

## Bugs unmasked and fixed along the way

Qualified registration removed the accidental collision-winners, exposing
two real, previously-masked composition bugs (both fixed in this patch):

- **Unions never got template-member inline-embedding** (patch 0003/0005
  only wired it into struct fields): `BSScript::Variable::Value`'s
  `BSTSmartPointer<Array>` member left the union permanently
  unresolvable. Mirrored parseStruct's branch into parseUnion; the fix
  cascades through the Papyrus VM structs (`Variable` 16, `Stack`,
  `StackFrame` all correct again on their own merits).
- **Nested base classes**: a base that is itself a nested record
  (`BSISoundOutputModel::BSIAttenuationCharacteristics`) is spelled bare
  at the inheritance site; qualifying base references fixed
  `BGSSoundOutput::DynamicAttenuationCharacteristics` to its true 0x18 --
  a class the old pipeline NEVER measured correctly (it was MISMATCH 16
  in every earlier baseline).

## Verification (full 1630-header sweep, JDK 25 + JIT)

- **OK count: 1523 -> 1667** (MISMATCH 393->376, EMPTY 792->958 -- the
  EMPTY rise is bare forward-declaration "ghost" entries now visible as
  their own 1-byte placeholders instead of being silently overwritten by
  colliding real definitions; the real definitions live correctly under
  their qualified names).
- Ground truth grew 2024 -> 2149 tracked classes (+125 previously-excluded
  ambiguous nested names).
- Status-equivalence check against the pre-0011 baseline (suffix-mapping
  each old bare key to its qualified successor, preferring the qualified
  twin over a 1-byte ghost): **48 better, 3 worse, 21 unmappable** (bare
  keys that split into multiple qualified twins, each now measured on its
  own merits).
- The 3 worse, documented as known deltas: `GFxLoadStates` (152->160) and
  `GFxStream` (624->632), both Scaleform internals whose old "OK" was two
  masking errors cancelling (their embedded `GString`/`GStringDH` used to
  be a broken 1-byte placeholder); and `RUNTIME_DATA2` (a bare
  macro-generated name with multiple qualified twins, no longer trackable
  as one entry).
- Hotspot list: `TESRace` (1208), `TESObjectWEAP` (544), `TESObjectARMO`
  (552), `SpellItem` (232), `AlchemyItem` (360), `EnchantmentItem` (192),
  `TESObjectBOOK` (312), `NiAVObject`/`NiNode`/`NiCamera` (272/296/392),
  `MagicItem` (144), `IngredientItem` (320) all byte-accurate.
- `TypePool.checkDependenciesFulfilled` gained an env-gated debug aid:
  `GCPP_DEBUG_DEPS=<substring>` prints which dependency blocks a type.

## How to apply

Applied by `generate_gdt.sh` after 0009 (and 0010 on JDK 22+; no file
overlap, order-independent with 0010). Manually:

```bash
patch -p1 < ../../patches/0011-qualify-nested-record-registration.patch
```
