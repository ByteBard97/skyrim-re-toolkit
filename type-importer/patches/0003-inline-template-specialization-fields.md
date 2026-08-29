# Patch 0003: inline class-template-specialization fields (SOLVED)

**Status: written, applied, and functionally verified end-to-end against
the real CommonLibSSE-NG header chain (2026-08-24). This is a complete
fix, not a partial one — see the update at the bottom; an earlier version
of this patch (same day) was real infrastructure but didn't work, and the
investigation of *why* led directly to the working version below.**

## The problem this addresses

`TESForm` (and any class with a field typed as a class template
specialization, e.g. `stl::enumeration<Flag, uint32_t>`) could never
resolve through `GhidraClangPoweredParse`: `TypePool.checkDependenciesFulfilled`
does a literal string lookup (`hasType(fieldTypeSpelling)`) against the
pool, and no `ParsedType`/`DataType` is ever created for a raw template
instantiation spelling like `"stl::enumeration<InGameFormFlag,
std::uint16_t>"`.

## Root cause, precisely (confirmed with `c-index-test` and a minimal libclang C program)

Two distinct layers of investigation, both done with tools independent of
this Java extension (to separate "libclang problem" from "our binding
layer problem"):

1. **`c-index-test`** (libclang's own cursor-inspection CLI) on a minimal
   repro showed that a class template specialization is *never* exposed
   as a visitable declaration cursor via `clang_visitChildren` — traversal
   only reaches the uninstantiated primary template (`ClassTemplate=...`)
   plus a `TemplateRef` at the use site. Comparing against Clang's
   internal AST (`-ast-dump`, which DOES show a real
   `ClassTemplateSpecializationDecl`) confirmed the specialization
   genuinely exists in the AST — it's just not reachable by top-down
   cursor traversal.

2. **A minimal, from-scratch libclang C program** (not using this
   extension, not using `c-index-test` — direct calls against
   `libclang.so` via `clang-c/Index.h`) pinned this down further against
   the *real* `TESForm::inGameFormFlags` field:
   - `clang_getTypeDeclaration(fieldType)` returns a `CLASS_DECL` cursor.
   - `clang_isCursorDefinition()` on that cursor returns **true**.
   - `clang_Type_getSizeOf(fieldType)` returns **2** (the correct size —
     `std::uint16_t`), proving the type is genuinely, fully instantiated.
   - `clang_visitChildren()` on that same cursor still finds **zero**
     children.
   - `clang_Type_visitFields()` on the field's `Type` — a *different*
     libclang API, which walks `CXXRecordDecl::field_begin()`/
     `field_end()` directly rather than the general declaration-child
     iterator — **finds the field correctly** (`_impl`, a `FieldDecl`).

**Conclusion:** this is a genuine, confirmed libclang-level quirk (or
deliberate design choice) — `clang_visitChildren` simply does not
enumerate members of an implicitly-instantiated class template
specialization, no matter how complete and well-formed the type is.
`clang_Type_visitFields` is the correct API for this case and libclang
ships it for exactly this reason.

## The fix

Two coordinated changes:

1. **`patches/0004-add-libclang-introspection-bindings.patch`** adds a
   `Type.visitFields(FieldVisitor)` method (new native binding:
   `clang_Type_visitFields`), following the exact existing pattern for
   `Cursor.visitChildren`/`clang_visitChildren`.

2. **This patch** (`SourceParser.java` + `ParsedStructure.java`):
   - `SourceParser.parseStruct`'s `FIELD_DECL` case detects when a
     (non-anonymous) field's type is a class template specialization
     (`fieldType.kind() == RECORD || UNEXPOSED`, spelling contains `<`),
     resolves its declaration, and — instead of the broken
     `declCursor.visitChildren(...)` approach — calls a new
     `parseFieldsFromType(Type, CategoryPath)` method that uses
     `type.visitFields(...)` to collect the real fields.
   - The result is inlined via the *same* mechanism already used for
     anonymous struct/union members (`FieldInfo.isAnonymous`/
     `anonymousType`), which conveniently already bypasses the
     string-keyed dependency system entirely
     (`ParsedStructure.getDependencies()` filters out `isAnonymous()`
     fields) — no mangled synthetic name needs to be registered in the
     pool anywhere.
   - `ParsedStructure.createDataType()`'s anonymous-embedding code path
     always used `""` as the field name (correct for a truly anonymous
     member). Fixed to preserve the real field name when one exists,
     since these reused fields DO have one (`inGameFormFlags`, not blank).

   One quirk along the way: **template specialization field types report
   `TypeKind.UNEXPOSED` in libclang's C API, not `TypeKind.RECORD`** — the
   type-kind check has to test for both (confirmed via debug tracing
   against real CommonLibSSE-NG headers).

Full diff: `0003-inline-template-specialization-fields.patch`.

## Investigation history (what was tried and ruled out first)

Getting to the actual fix took four ruled-out hypotheses, each tested
individually against the real header chain, not guessed:

1. Force-instantiation via `using X = Template<Args>; sizeof(X);` at the
   source level — resolved-type count didn't move at all. Ruled out.
2. `-fdelayed-template-parsing` (an MSVC-compat flag this codebase sets)
   — negated it, no change. Ruled out.
3. `.skipFunctionBodies()` on the `TranslationUnit.Builder` — removed it,
   no change. Ruled out.
4. `.parseIncomplete()` — removed it too, no change. Ruled out.
5. Declaration-vs-definition cursor distinction (added
   `clang_getCursorDefinition`, see patch 0004) — confirmed it returns
   the *identical* cursor `clang_getTypeDeclaration` already gives. Ruled
   out.

Only after all five were cleanly eliminated did the minimal from-scratch C
program (bypassing this Java layer, `c-index-test`, and this project's
build entirely) reveal the real answer: `clang_Type_visitFields` vs.
`clang_visitChildren`. The lesson for next time: when a Java/Panama-level
binding produces a surprising result, drop straight to a minimal C
program against the same C API before assuming the binding layer itself
is at fault — it would have saved four rounds of Java-level flag toggling.

## What this does NOT fix

While verifying this fix end-to-end, `TESForm` as a *whole* still doesn't
fully resolve in the real header test — but for a completely different,
unrelated reason discovered in the same verification pass: `FormID`
(`using FormID = std::uint32_t;`, a simple typedef) appears in the
"unresolved dependencies" list, suggesting Ghidra's `DataTypeParser`
and/or this tool's `TypePool.getType()` doesn't resolve namespace-qualified
builtin type spellings like `"std::uint32_t"` correctly in some code path.
This is a **separate, distinct, not-yet-investigated bug** — not chased
further this pass. `TESObjectREFR (RUNTIME_DATA_CONTENT tail sizing, see
DESIGN.md) and BaseFormComponent both resolved fine, isolating the
remaining blocker specifically to typedef/builtin-type-name resolution,
not to anything this patch touches.

## How this was verified

Standalone harness (`VisitFieldsTest`, not committed — throwaway
validation tool) confirmed `Type.visitFields()` finds `TESForm`'s real
`inGameFormFlags` field (`_impl`, type `underlying_type`) directly against
the real vendored headers, independent of the full `SourceParser` pipeline.
Then wired into the real `SourceParser.parseStruct` flow and confirmed
via debug tracing that `parseFieldsFromType(enumeration<InGameFormFlag,
std::uint16_t>) -> 1 fields` fires correctly for every `stl::enumeration<...>`
usage across the real header chain (9 distinct instantiations observed).
Ran the full regression suite (`VptrFixTest`, `RealHeaderTest`) after
removing debug logging — zero clang diagnostics, no regressions, 3746
resolved types (matches the count with all patches applied). Reverted the
submodule's working tree to pristine afterward.

## How to apply

From `type-importer/vendor/GhidraClangPoweredParse`:

```bash
patch -p1 < ../../patches/0001-fix-redundant-vptr.patch
patch -p1 < ../../patches/0002-fix-forward-decl-overwrite.patch
patch -p1 < ../../patches/0003-inline-template-specialization-fields.patch
patch -p1 < ../../patches/0004-add-libclang-introspection-bindings.patch
```

**Patch 0004 must be applied for this patch to compile** (it depends on
`Type.visitFields`). All four verified to apply cleanly together (fresh
pristine checkout, then applied in sequence) and build successfully.
