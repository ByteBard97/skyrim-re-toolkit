# Patch 0004: add a `clang_getCursorDefinition` binding to `Cursor`

**Status: written, applied, verified to compile and not regress anything.
Real, previously-missing libclang capability — but empirically confirmed
NOT to be the fix for the template-specialization problem in patch 0003.**

## What this adds

`playday3008.gcpp.clang.Cursor` had no binding for `clang_getCursorDefinition`
— given a declaration cursor, this libclang call returns the cursor that
actually *defines* it (or a null cursor if there's no definition in the
translation unit). This is a distinct, real libclang API from
`clang_getTypeDeclaration` (already bound, used by `Type.declaration()`),
and the two can legitimately return different cursors for the same
underlying declaration in general.

Added following the exact existing pattern for `Type.declaration()` /
`LibClang.getTypeDeclaration`:

- `LibClang.java`: a new `MethodHandle CLANG_GET_CURSOR_DEFINITION` downcall
  plus a `getCursorDefinition(SegmentAllocator, MemorySegment)` wrapper.
- `Cursor.java`: a new `public Cursor definition()` method.

Full diff: `0004-add-cursor-definition-binding.patch`.

## Why this was added — and what it ruled out

While investigating patch 0003's remaining gap (`Type.declaration()`
correctly resolves to a `CLASS_DECL` cursor for a template specialization,
but visiting its children finds zero fields), the natural next hypothesis
was: maybe `clang_getTypeDeclaration` returns a *declaration-only* cursor
distinct from the *definition* cursor, and only the definition cursor has
real children.

Tested directly against the real `TESForm` header chain (debug tracing,
not guessed): `fieldType.declaration()` and
`fieldType.declaration().definition()` returned **the identical cursor** —
same kind (`CLASS_DECL`), same spelling (`enumeration`). For this specific
case, `clang_getCursorDefinition` is a no-op: `clang_getTypeDeclaration`
was already returning what it considers the definition.

**This rules out the declaration-vs-definition distinction as the cause.**
Combined with patch 0003's own ruled-out list (three parse-mode flags:
`-fdelayed-template-parsing`, `.skipFunctionBodies()`, `.parseIncomplete()`
— none of which changed the outcome either when tested individually), the
real remaining gap is now narrowed to something more specific still
unknown: the cursor is a real, "defined" `CLASS_DECL` by every check
available, yet `clang_visitChildren` on it produces zero children for a
field (`_impl`) that must genuinely exist in clang's AST (proven by the
fact that parsing `TESForm`'s field of this type produces zero
diagnostics — a member of a genuinely incomplete type would be a hard C++
error, not something `.parseIncomplete()` can legally paper over).

## Why keep this patch despite not fixing the problem

Unlike a throwaway debug hack, this is real, generally-useful
infrastructure: a previously-missing libclang binding, implemented
correctly (mirrors the exact working pattern for `Type.declaration()`),
that any future investigation into cursor resolution will likely need
regardless of how the template-specialization issue is eventually solved.
It's also load-bearing evidence — the ruled-out finding above is much more
useful with the binding available for anyone who wants to re-verify it
than as a one-off unrepeatable experiment.

## What's left as the real open question

After patches 0003 and 0004, four specific hypotheses about *why*
`stl::enumeration<...>`'s resolved definition cursor shows zero fields
are now ruled out with real evidence:

1. `-fdelayed-template-parsing` (ruled out: negating it changed nothing)
2. `.skipFunctionBodies()` (ruled out: removing it changed nothing)
3. `.parseIncomplete()` (ruled out: removing it changed nothing)
4. declaration-vs-definition cursor distinction (ruled out: identical cursor either way)

The next investigation step needs to go deeper into libclang/Panama-FFI
specifics rather than trying more Java-level toggles — for example:
comparing `clang_visitChildren`'s actual behavior on a *directly returned*
specialization type's declaration versus a cursor obtained by other means
(e.g. `clang_Cursor_getTemplateArgumentType` style APIs, or checking
whether `CXCursor_ClassDecl` specifically needs
`clang_getSpecializedCursorTemplate` handling that differs from an
ordinary class), or building a minimal C program directly against
libclang's C API (bypassing the Java/Panama layer and this project's
`c-index-test`-based black-box testing entirely) to isolate whether this
is a libclang API behavior or something specific to how this Java binding
layer invokes it.

## How to apply

From `type-importer/vendor/GhidraClangPoweredParse`:

```bash
patch -p1 < ../../patches/0001-fix-redundant-vptr.patch
patch -p1 < ../../patches/0002-fix-forward-decl-overwrite.patch
patch -p1 < ../../patches/0003-inline-template-specialization-fields.patch
patch -p1 < ../../patches/0004-add-cursor-definition-binding.patch
```

All four verified to apply cleanly together (fresh pristine checkout, then
applied in sequence) and build successfully.
