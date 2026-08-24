# Patch 0002: don't let a forward declaration overwrite a real definition

**Status: written and applied; functionally correct and verified not to
regress anything, but it did NOT turn out to be the cause of the specific
symptom that motivated writing it (see "What this patch does NOT fix"
below — that's a template-instantiation limitation, already documented,
not a new bug).**

## The bug

`TypePool.addParsedType` (`TypePool.java:123-125` originally) is the single
place every parsed struct/union/enum/vtable gets registered:

```java
public void addParsedType(ParsedType type) {
    this.parsedTypes.put(type.getName(), type);
}
```

`SourceParser.parseStruct` is called for **every** `STRUCT_DECL`/`CLASS_DECL`
cursor clang visits — including bare forward declarations (`class Foo;`)
that have zero children, which produce an empty `ParsedStructure` (zero
fields). There is no `isDefinition()` check anywhere in `SourceParser` to
skip these (no such binding exists on the extension's `Cursor` wrapper yet).

Combined, this means: in a translation unit where a class is forward-declared
*again* somewhere after its full definition is visited — a completely
routine C++ pattern, and one CommonLibSSE-NG uses constantly (`class
TESForm;` appears as a forward declaration in dozens of files) — the later,
empty forward-declaration would silently overwrite the real, already-parsed
definition in the map, with no diagnostic.

## The fix

`addParsedType` now keeps whichever `ParsedStructure` has more fields when
both the existing and incoming entries are structures for the same name:

```java
if (existing instanceof ParsedStructure existingStruct
    && type instanceof ParsedStructure incomingStruct
    && incomingStruct.getFields().size() < existingStruct.getFields().size()) {
    return; // keep the richer (already-parsed) definition
}
this.parsedTypes.put(type.getName(), type);
```

No new libclang binding needed — a real definition always has at least as
many fields as any forward declaration of the same class (always zero), so
this heuristic can't misfire in the other direction (a struct never "loses"
fields between two full-definition visits of the same class in one TU).

Full diff: `0002-fix-forward-decl-overwrite.patch` in this directory.

## How this was found, and what it does NOT fix

While building the actual v0.1 `.gdt` for `TESObjectREFR` for the first
time (2026-08-24) with both this fix and `0001-fix-redundant-vptr.patch`
applied, `TESForm` still came out as an empty (`sizeof=1`) struct in the
final archive, despite **zero clang parse errors**. Debug tracing showed
`addParsedType("TESForm")` was actually called correctly, in the right
order (0 fields from a forward declaration, then 8 fields from the real
definition) — so this patch's fix was already doing its job; the map held
the correct 8-field entry going into `resolve()`.

The real cause is one level deeper, in `TypePool.resolve()`'s dependency
gating: a `ParsedStructure` only gets converted into a real Ghidra
`DataType` once `checkDependenciesFulfilled` returns true for *every* field
type name string (`TypePool.java:328-334`, `hasType()` does a literal
lookup by that string). `TESForm`'s 8 real fields include
`inGameFormFlags: stl::enumeration<InGameFormFlag, std::uint16_t>` and
`formType: stl::enumeration<FormType, std::uint8_t>` (confirmed via debug
trace) — raw, uninstantiated template spellings. `GhidraClangPoweredParse`
has **no C++ template instantiation support** (already documented as a
known limitation in `DESIGN.md`'s "Base tooling" section and in this
`patches/` directory's own README context) — it never creates a
`ParsedType`/`DataType` for a template instantiation string like that, so
`hasType(...)` returns false for it forever. `TESForm` therefore never
satisfies `checkDependenciesFulfilled`, `createDataType()` is never called
for it, and the only representation of `TESForm` that ends up in the final
`.gdt` is the empty placeholder registered during `resolve()`'s
forward-declaration pre-pass (`TypePool.java:41-64`) — which happens
*unconditionally* for every struct, real definition or not, and is only
ever replaced when the real type successfully resolves.

**This is not a new, independent bug** — it's a direct, concrete, now
empirically-confirmed manifestation of the already-known "no template
instantiation support" limitation, using our own actual v0.1 target class
as the live reproduction. It's exactly why `DESIGN.md`'s template
flattening table and the force-instantiation preprocessing step
(`scripts/mine_instantiations.py`, `scripts/generate_forced_instantiations.py`)
exist as required v0.1 work, not optional polish: **without force-
instantiating `stl::enumeration<...>` (and every other template type used
as a struct field) ahead of time, any class using one as a field member
will never resolve through this tool, regardless of how correct everything
else is.**

## Next step this points to — one attempt made tonight, didn't work

Wiring `generate_forced_instantiations.py`'s output into the actual
`SourceParser.parseFiles` call was the obvious next step, so one attempt
was made (2026-08-24, same session): appended
`using _f = stl::enumeration<TESForm::InGameFormFlag, std::uint16_t>;`
plus `sizeof(_f)` (and the same for `stl::enumeration<FormType,
std::uint8_t>`) inside `namespace RE { ... }`, *after* the real header
includes in the test's translation unit, and re-ran.

**Result: no change.** Same 3731 resolved types, `TESForm` still empty.
The resolved-type *count* not changing at all is the interesting part — if
the forced instantiation had even partially worked (e.g., registered the
enumeration type but something else still blocked `TESForm`), the count
should have gone up by at least the new `stl::enumeration<...>`
specializations themselves. It didn't move, which suggests the `using` +
`sizeof` trick isn't producing a cursor that `SourceParser`'s
`visitDeclarations`/`visitChildren` traversal ever sees as a child of the
namespace at all — plausible culprits, untested:

- `ArchitectureMapping.TargetEnvironment.WINDOWS` sets
  `-fdelayed-template-parsing` (`ArchitectureMapping.java:114-119`), an
  MSVC-compatibility flag that defers template body parsing/instantiation.
  Combined with `.parseIncomplete()` and `.skipFunctionBodies()` on the
  `TranslationUnit.Builder` (`SourceParser.java:117-118`), the implicit
  specialization triggered by `sizeof` may simply never get materialized
  into a walkable AST node in this parse mode.
- Alternatively, implicit template instantiations may need explicit
  cursor-visitor handling (e.g. checking
  `CursorKind.CLASS_TEMPLATE`/specialization-related kinds, or visiting via
  a different traversal option) that `visitDeclarations`/`parseStruct`
  simply doesn't have — they only handle `STRUCT_DECL`/`CLASS_DECL`, and an
  implicit specialization might report a different kind, or might not be
  enumerated as a syntactic child of the namespace the way an explicit
  declaration is.

**Not chased further tonight** — this needs actual investigation (dumping
the AST via `clang -Xclang -ast-dump` for a minimal repro of `using X =
SomeTemplate<Args>; sizeof(X);` to see whether/how the instantiation shows
up as a cursor, then checking whether `-fdelayed-template-parsing` changes
that) rather than more blind trial-and-error. This is the concrete starting
point for whoever picks this up next, including which two things were
already ruled out (the STL-availability problem and the RTTI/VTABLE-stub
problem — both solved by `stubs/layout_pch.h`) so the search space is
narrower than it looks.

## How this was verified

Same rigor as patch 0001: built the real extension with both patches
applied (JDK 21 + Ghidra 12.1.3, both user-local), ran the standalone
`RealHeaderTest` harness against the actual vendored CommonLibSSE-NG
headers (`RE/T/TESForm.h`, `TESObject.h`, `TESBoundObject.h`,
`TESObjectREFR.h`) with the `layout_pch.h` stub force-included, and
confirmed: zero clang diagnostics, 3731 real data types resolved and
committed to an actual `.gdt` file, and (via debug tracing, since verifying
the *absence* of a symptom needs positive confirmation the code path
actually ran) that `addParsedType` correctly preserves the real 8-field
`TESForm` definition in the pool — the remaining emptiness in the final
archive is the template-instantiation limitation above, not this patch's
concern. Reverted the submodule's working tree to pristine afterward, same
as patch 0001.

## How to apply

From `type-importer/vendor/GhidraClangPoweredParse`:

```bash
patch -p1 < ../../patches/0001-fix-redundant-vptr.patch
patch -p1 < ../../patches/0002-fix-forward-decl-overwrite.patch
```

Both apply cleanly together (touch different files, no conflicts) against
the submodule's current pinned commit.
