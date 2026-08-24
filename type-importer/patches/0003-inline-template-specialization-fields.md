# Patch 0003: inline class-template-specialization fields (partial fix)

**Status: written, applied, verified not to regress anything (build succeeds,
both prior test harnesses still pass, resolved-type count goes up slightly).
Does NOT fully solve the underlying problem — see "What's still missing"
below. Real, tested infrastructure that a future fix will need regardless.**

## The problem this addresses

Documented in `patches/0002-fix-forward-decl-overwrite.md`: `TESForm` (and
any other class with a field typed as a class template specialization, e.g.
`stl::enumeration<Flag, uint32_t>`) can never resolve through
`GhidraClangPoweredParse`, because `TypePool.checkDependenciesFulfilled`
does a literal string lookup (`hasType(fieldTypeSpelling)`) against the pool,
and no `ParsedType`/`DataType` is ever created for a raw template
instantiation spelling like `"stl::enumeration<InGameFormFlag,
std::uint16_t>"`.

## Root cause, precisely (not guessed — confirmed with `c-index-test`)

Built a minimal repro and inspected it two ways:

1. `clang -Xclang -ast-dump` (Clang's internal AST, not libclang's cursor
   model): shows a real `ClassTemplateSpecializationDecl` node for
   `enumeration<Flag, unsigned short>` when the type is used in a `using`
   alias plus `sizeof()`.
2. `c-index-test -test-load-source all` (libclang's actual cursor-tree
   view, the same API `GhidraClangPoweredParse` uses): for the SAME code,
   traversal only ever surfaces `ClassTemplate=enumeration (Definition)`
   (the uninstantiated primary template) and, at the use site,
   `TemplateRef=enumeration` (a reference, not a declaration). **There is
   no cursor anywhere in the traversal for the specialization itself.**
   Confirmed again with a struct field (`struct Holder { enumeration<Flag,
   unsigned short> field1; };`) — libclang shows `FieldDecl=field1` and,
   inside it, only a `TemplateRef` to the primary template. No
   `StructDecl`/`ClassDecl` for the specialization appears as a child of
   anything, no matter how it's used.

**Conclusion: no amount of top-down cursor traversal (`visitDeclarations`'s
approach) or source-level force-instantiation trickery (tried in patch
0002's writeup, confirmed not to move the needle) can make
`SourceParser`'s existing `case STRUCT_DECL, CLASS_DECL ->` traversal ever
see a template specialization as a declaration to parse.** This isn't a
tuning problem, it's an architectural mismatch between how the tool
discovers types (structural traversal) and where template specializations
actually live in libclang's model (only reachable by resolving a `Type`,
never by walking declarations).

## The fix (partial)

`SourceParser.parseStruct`'s `FIELD_DECL` case already has an existing
mechanism for exactly this shape of problem: anonymous struct/union
members are resolved via `Type.declaration()` (`clang_getTypeDeclaration`)
rather than traversal, and inlined directly into the parent via
`FieldInfo.isAnonymous`/`anonymousType` — which conveniently already
bypasses the string-keyed dependency system entirely
(`ParsedStructure.getDependencies()` filters out `isAnonymous()` fields).

This patch extends that exact mechanism to non-anonymous fields whose type
is a class template specialization:

```java
Type fieldType = cursor.type().unwrap();
if ((fieldType.kind() == TypeKind.RECORD || fieldType.kind() == TypeKind.UNEXPOSED)
    && fieldType.spelling().contains("<")) {
    Cursor declCursor = fieldType.declaration();
    CursorKind declKind = declCursor.kind();
    if (declKind == CursorKind.STRUCT_DECL || declKind == CursorKind.CLASS_DECL) {
        anonType = parseAnonymousStruct(pool, declCursor, category);
        inlineEmbed = true;
    }
}
```

One quirk discovered along the way (confirmed via debug tracing, not
assumed): **template specialization types report `TypeKind.UNEXPOSED` in
libclang's C API, not `TypeKind.RECORD`** — the check above has to test
for both.

Also fixed a small side issue in `ParsedStructure.createDataType()`: the
existing anonymous-embedding code path always used `""` as the field name
(correct for a truly anonymous member, which has none), but this reused
path needs to preserve the real field name (`inGameFormFlags`, not blank)
since these fields DO have one.

Full diff: `0003-inline-template-specialization-fields.patch`.

## What's still missing — this does NOT fully fix `TESForm`

Debug tracing after applying this patch showed real, precise progress:
`Type.declaration()` **does** successfully resolve to a `CLASS_DECL` cursor
for the specialization (e.g. `spelling=enumeration`) — confirming the
premise of this fix is correct, `clang_getTypeDeclaration` reaches nodes
that `clang_visitChildren` traversal cannot. But calling
`.visitChildren()` on that resolved cursor finds **zero fields** — not
just for `stl::enumeration`, but for essentially every templated type
checked this way across the whole CommonLibSSE-NG parse (`vector`,
`optional`, `array`, `atomic`, `BSTArray`, `NiPointer`, `shared_ptr`, all
showed "0 fields" in the trace).

The most likely explanation (untested, the actual next investigation
step): `ArchitectureMapping.TargetEnvironment.WINDOWS` sets
`-fdelayed-template-parsing`, and `SourceParser.parseFiles` also sets
`.parseIncomplete()` and `.skipFunctionBodies()`. Together, these may mean
the template class's *body* is never actually instantiated/parsed at all —
`Type.declaration()` can resolve to the specialization's outward shell
(enough to get a cursor with the right name and kind), but nothing in this
parse actually forces the body to materialize, since an incomplete-type-
tolerant field declaration doesn't count as a "use" the way a real
`sizeof()` or member access would. A prior attempt this session to force
that via an explicit `using X = Template<Args>; sizeof(X);` at the end of
the same translation unit did not change the resolved-type count at all,
suggesting either that trick doesn't actually force *this* code path's
specific specialization to materialize, or the forced instantiation and
the field's own usage don't end up sharing the same canonical AST node in
a way that helps.

**Update, same session: all three parse-mode flags ruled out empirically,
real cause narrowed further.** Tested each of the three candidates named
above individually against the real `TESObjectREFR` header chain:

- `-fno-delayed-template-parsing` appended to the clang args (a real,
  recognized flag — verified it doesn't error) — **no change**, `TESForm`
  still `size=0x1`.
- Removed `.skipFunctionBodies()` from the `TranslationUnit.Builder` call
  — **no change**.
- Removed `.parseIncomplete()` too (both flags gone at once) — **no
  change**. (Resolved-type count crept up slightly across these tests —
  3744 → 3746 → 3751 — consistent with a few unrelated types elsewhere
  benefiting, not with this specific problem being touched at all.)

All three hypotheses from the original writeup are now ruled out, not just
suspected. Reasoning about *why* points at a different, more specific gap:
clang's normal semantic checking would treat a struct member whose type is
genuinely incomplete as a hard compile error (you cannot have a plain
by-value member of an incomplete class type — this isn't something
`.parseIncomplete()`/`-fdelayed-template-parsing` can legally paper over,
those are about tolerating *unrelated* incomplete types, not malformed
member declarations). Since parsing `TESForm` produced **zero diagnostics**
end to end, clang must have instantiated `stl::enumeration<InGameFormFlag,
std::uint16_t>` for real, correctly, as an ordinary part of checking that
field declaration. The specialization's body demonstrably exists,
complete, somewhere in clang's AST for this translation unit.

**So the most likely remaining gap is in the extension's `Cursor` wrapper
itself, not in any compiler flag:** `Type.declaration()`
(`clang_getTypeDeclaration`) may be returning a *declaration* cursor for
the specialization rather than its *definition* cursor — libclang
distinguishes these for exactly this kind of case, and only the
definition cursor has real, visitable children. The fix would be calling
`clang_getCursorDefinition()` on the result (given a declaration, returns
the cursor that actually defines it, or a null cursor if none exists in
this TU) before running `parseAnonymousStruct` on it. **This binding does
not exist yet** in `playday3008.gcpp.clang.Cursor` — adding it means a new
native Panama FFI declaration alongside the existing ones (see how
`isVirtualMethod()`/`isPureVirtualMethod()` etc. are bound in `Cursor.java`
for the pattern to follow), which is a native-binding-level change, not a
plain Java logic edit. That's genuinely the next concrete step, and it's
now scoped precisely enough that it should be a small, mechanical addition
rather than more exploratory debugging.

## How this was verified

Same rigor as patches 0001/0002: rebuilt the real extension (JDK 21 +
Ghidra 12.1.3, both user-local) with all three patches applied together,
confirmed clean `patch -p1` application in sequence against a fresh
pristine checkout of the submodule, reran both existing standalone test
harnesses (`VptrFixTest`, `RealHeaderTest`) to confirm no regression —
`VptrFixTest` still shows zero spurious vptr fields, `RealHeaderTest`
still parses with zero clang diagnostics and now resolves 3744 types
(up from 3730-3731 without this patch, consistent with a handful of
template-typed fields elsewhere in the hierarchy successfully picking up
an empty-but-present inline type instead of blocking their whole
containing struct). Reverted the submodule's working tree to pristine
afterward.

## How to apply

From `type-importer/vendor/GhidraClangPoweredParse`:

```bash
patch -p1 < ../../patches/0001-fix-redundant-vptr.patch
patch -p1 < ../../patches/0002-fix-forward-decl-overwrite.patch
patch -p1 < ../../patches/0003-inline-template-specialization-fields.patch
```

All three apply cleanly together (verified via a fresh pristine checkout,
then applying all three in sequence) against the submodule's current
pinned commit.
