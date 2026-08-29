# Patch 0004: add `clang_getCursorDefinition` and `clang_Type_visitFields` bindings

**Status: written, applied, verified. Two libclang bindings, previously
missing from `playday3008.gcpp.clang`. One (`Type.visitFields`) is the
actual fix wired into patch 0003. The other (`Cursor.definition`) was
added mid-investigation to test a hypothesis that turned out to be wrong
-- kept anyway as real, correctly-implemented, generally useful
infrastructure.**

## `Type.visitFields` -- the actual fix

Adds a binding for `clang_Type_visitFields`, following the exact existing
pattern for `Cursor.visitChildren`/`clang_visitChildren` (same upcall-stub
approach, same ThreadLocal visitor-bridge pattern, just a different
callback signature -- `CXFieldVisitor` takes a single cursor and returns
`CXVisitorResult`, vs. `CXCursorVisitor`'s cursor+parent pair and
`CXChildVisitResult`).

This is the API that actually solves the class-template-specialization
problem described in `patches/0003-inline-template-specialization-fields.md`:
`clang_visitChildren` never enumerates the members of an
implicitly-instantiated template specialization, no matter how complete
the type is (confirmed: `clang_isCursorDefinition` true, correct
`clang_Type_getSizeOf`) -- but `clang_Type_visitFields` (which walks
`CXXRecordDecl::field_begin()`/`field_end()` directly) does.

## `Cursor.definition` -- added mid-investigation, kept as infrastructure

Adds a binding for `clang_getCursorDefinition` -- given a declaration
cursor, returns the cursor that actually defines it (or a null cursor if
there's no definition in the translation unit).

**Why it was added:** while patch 0003 was still broken (before finding
`clang_Type_visitFields`), the natural hypothesis was that
`clang_getTypeDeclaration` might return a declaration-only cursor distinct
from the definition cursor for a template specialization, and only the
definition cursor would have real children.

**What testing it found:** for the real `TESForm::inGameFormFlags` case,
`fieldType.declaration()` and `fieldType.declaration().definition()`
returned the **identical** cursor -- same kind, same spelling. This ruled
out the declaration-vs-definition distinction as the cause (it was the
4th of 5 hypotheses ruled out before finding the real answer -- see patch
0003's "Investigation history" section for the full list).

**Why keep it despite not being the fix:** it's real, generally-useful,
correctly-implemented libclang capability that any future cursor-resolution
work will likely need, implemented by mirroring the exact working pattern
for `Type.declaration()`/`clang_getTypeDeclaration`. Removing it would
just mean re-adding it the next time someone needs to check a
declaration/definition distinction -- better to keep working, tested
infrastructure than throw it away because it answered "no" to the
question it was built to test.

Full diff: `0004-add-libclang-introspection-bindings.patch` (touches
`LibClang.java`, `Cursor.java`, and `Type.java`).

## How this was verified

Both bindings compile cleanly standalone (before patches 0001-0003 are
applied) and together with the full patch stack. `Type.visitFields` was
verified two ways: (1) a minimal libclang C program, completely outside
this Java layer, using `clang-c/Index.h` directly against `libclang.so`
-- confirmed `clang_Type_visitFields` finds the field where
`clang_visitChildren` does not; (2) a standalone Java harness
(`VisitFieldsTest`, not committed) exercising the actual
`Type.visitFields()` Java method against the real vendored headers,
confirming the same result through this binding layer. `Cursor.definition`
was verified via debug tracing showing it returns the same cursor as
`Type.declaration()` in the case it was built to test.

## How to apply

From `type-importer/vendor/GhidraClangPoweredParse`:

```bash
patch -p1 < ../../patches/0001-fix-redundant-vptr.patch
patch -p1 < ../../patches/0002-fix-forward-decl-overwrite.patch
patch -p1 < ../../patches/0003-inline-template-specialization-fields.patch
patch -p1 < ../../patches/0004-add-libclang-introspection-bindings.patch
```

This patch can also be applied standalone (it only adds new methods,
doesn't modify any call sites) but patch 0003 depends on it
(`Type.visitFields`) to compile. All four verified to apply cleanly
together against a fresh pristine submodule checkout and build
successfully.
