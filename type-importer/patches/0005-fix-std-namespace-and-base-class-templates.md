# Patch 0005: fix `std::`-qualified builtin resolution and template-specialization base classes

**Status: written, applied, and functionally verified. Together with
patches 0001-0004, this makes `TESForm`, `TESObject`, and `TESBoundObject`
resolve to their exact, byte-correct real layouts, and gets
`TESObjectREFR` to its essentially-complete real layout (one small,
well-understood, pre-existing discrepancy remains — see below).**

## Two fixes, found while finally getting real header resolution working end to end

### Fix 1: `std::`-qualified builtin integer types never resolved

After patches 0001-0004 solved the class-template-specialization field
problem, `TESForm` *still* didn't fully resolve. Debug tracing
(`getUnfulfilledDependencies`) showed exactly why:

```
DEBUG TESForm unfulfilled deps: [std::uint32_t, FormID, std::uint8_t, std::uint32_t]
```

Every plain `std::uint32_t`/`std::uint8_t` field — an extremely common
pattern throughout CommonLibSSE-NG — was stuck as an unresolved
dependency. `TypePool.getType()`'s normalization step
(`normalizeTypeName`) stripped CV qualifiers (`const `, `volatile `, ...)
and elaborated-type prefixes (`struct `, `class `, ...) but never stripped
a leading `std::` namespace qualifier, and Ghidra's `DataTypeParser`
doesn't resolve `"std::uint32_t"` as a name at all — only the bare
`"uint32_t"`.

**Fix:** strip a leading `std::` prefix in `normalizeTypeName`, the same
way CV qualifiers are stripped. Safe unconditionally: CommonLibSSE-NG's
own types live in the `RE::` namespace and are never spelled with a
`std::` prefix, so this can only ever match real standard-library
builtins.

**Impact:** this was the single highest-leverage fix in this whole
investigation — it's not narrow to `TESForm`, it unblocks *any* struct
with a directly-embedded `std::intN_t`/`std::uintN_t` field, which is most
of CommonLibSSE-NG. Resolved-type count jumped from 3746 to 3895 from this
one change alone. `TESForm` immediately came out at **exactly `0x20`
bytes**, matching the header's `static_assert`.

### Fix 2: template specialization used as a base class (not just as a field)

With `std::` fixed, `TESObjectREFR` still didn't resolve.
`getUnfulfilledDependencies` showed the last blocker:

```
DEBUG TESObjectREFR unfulfilled deps: [BSTEventSink<BSAnimationGraphEvent>]
```

`BSTEventSink<T>` is used as a **base class**, not a field — patch 0003's
fix only covered the `FIELD_DECL` code path. Base classes go through a
completely separate mechanism (`C_X_X_BASE_SPECIFIER` handling in
`parseStruct`), which builds `baseClasses` as plain named dependencies
(never marked `isAnonymous`), so `hasType("BSTEventSink<BSAnimationGraphEvent>")`
faced the exact same "no `ParsedType` ever registered for a raw template
spelling" problem as fields did.

**Fix:** extended the same inline-embedding approach to base classes.
`baseInlineTypes` (new list, parallel to `baseClasses`) holds a non-null
inline `ParsedType` whenever a base's type spelling contains `<`, built
via the same `parseFieldsFromType`/`Type.visitFields()` machinery from
patch 0003. Base classes with a template-specialization type are now
embedded the same way anonymous/template-typed fields are (bypassing the
string-keyed dependency system entirely).

**A necessary companion change to `parseFieldsFromType` itself:** classes
like `BSTEventSink<T>` are pure vtable interfaces with **no explicit data
fields** — `clang_Type_visitFields` correctly finds zero members (the
compiler-generated vptr isn't a real `FieldDecl`). Left as-is, this would
produce a zero-size inline struct, silently shrinking the enclosing class
by the base's real size. Fixed by padding: when `visitFields` finds
nothing, add one opaque field sized from `clang_Type_getSizeOf` (already
proven accurate for fully-instantiated specializations — confirmed
earlier with `stl::enumeration<...>`) — `char[N]` rather than
`undefined1[N]`, since Ghidra's `DataTypeParser` recognizes `char` but not
`undefined1` as a parseable type name (confirmed empirically: the
`undefined1[8]` spelling silently failed to resolve, `char[8]` worked).
This correctly accounts for the missing vtable-pointer bytes without
attempting to model the vtable's actual contents.

**A related, smaller fix bundled in the same investigation:**
`parseFieldsFromType` now uses `fieldCursor.type().canonicalType().spelling()`
instead of the raw spelling. Template members are commonly typed via a
nested alias — `stl::enumeration`'s own `_impl` field is declared as
`underlying_type` (`using underlying_type = Underlying;`), which is never
independently registered as a resolvable type anywhere. `canonicalType()`
(`clang_getCanonicalType`, already bound in this codebase) resolves
through the alias to the real type (e.g. `"unsigned short"`), which
Ghidra's parser can find. Without this, `inGameFormFlags`/`formType`
showed the right *offset* but `length=0` — this fix gave them their
correct sizes (2 and 1 bytes respectively).

Full diff: `0005-fix-std-namespace-and-base-class-templates.patch`.

## Result: real, verified layouts

With all five patches applied, parsing the real
`TESForm`/`TESObject`/`TESBoundObject`/`TESObjectREFR` chain and
committing to a real `.gdt` gives:

| Class | Ghidra-committed size | Matches known-correct value? |
|---|---|---|
| `TESForm` | `0x20`, full field-by-field layout matches DESIGN.md's independently clang-cl-verified dump exactly | ✅ Exact match, including `stl::enumeration` field sizes/offsets |
| `TESObject` | `0x20` | ✅ Matches `static_assert` |
| `TESBoundObject` | `0x30` | ✅ Matches `static_assert` |
| `TESObjectREFR` | `0x70` (112) | ⚠️ See below — 8 bytes short of the `0x78` clang-cl gave, for an already-understood reason unrelated to this session's fixes |

### The one remaining, pre-existing, well-understood discrepancy

`TESObjectREFR`'s base/member layout now matches DESIGN.md's
independently-derived offsets *exactly* — `TESForm@0x00`,
`BSHandleRefObject@0x20`, `BSTEventSink@0x30` (now correctly 8 bytes via
this patch's padding fix), `IAnimationGraphManagerHolder@0x38`,
`data(OBJ_REFR)@0x40`, `parentCell@0x60`, `loadedData@0x68`,
`extraList@0x70`. The only gap is `extraList` itself, which the real
clang-cl compile (documented in DESIGN.md's TESObjectREFR field-map
section) contributes `8` trailing bytes to (`112 → 120` total) even
though `RE::ExtraDataList`/`RE::BaseExtraList` are themselves empty
classes under `ENABLE_SKYRIM_AE` — an artifact of C++ struct-alignment
padding rules for a trailing empty member that this tool doesn't
currently replicate (Ghidra computes `0x70`, ending exactly where
`extraList`'s own zero-length contribution leaves it, rather than the
`0x78` a real compiler pads out to). This is not a new bug from this patch's
work — it's the same "invisible relocated member" pattern already
extensively documented in `DESIGN.md`'s TESObjectREFR field-map section
(the true game object size is larger than any of these numbers, due to
runtime-relocated fields CommonLibSSE-NG doesn't declare as real compiled
members at all). Not chased further this session — flagged precisely so
it isn't mistaken for a new mystery.

## How this was verified

Same rigor as prior patches: rebuilt with JDK 21 + Ghidra 12.1.3
(user-local), applied all five patches to a fresh pristine submodule
checkout (zero fuzz, zero rejects), ran both `VptrFixTest` and
`RealHeaderTest` — zero clang diagnostics, no regressions, resolved-type
count increased from 3746 → 3908 across these two fixes. Printed and
manually cross-checked the full field-by-field layout of all four target
classes against both the headers' own `static_assert`s and this session's
earlier independent `clang-cl` verification. Reverted the submodule's
working tree to pristine afterward.

## How to apply

From `type-importer/vendor/GhidraClangPoweredParse`:

```bash
patch -p1 < ../../patches/0001-fix-redundant-vptr.patch
patch -p1 < ../../patches/0002-fix-forward-decl-overwrite.patch
patch -p1 < ../../patches/0003-inline-template-specialization-fields.patch
patch -p1 < ../../patches/0004-add-libclang-introspection-bindings.patch
patch -p1 < ../../patches/0005-fix-std-namespace-and-base-class-templates.patch
```

All five verified to apply cleanly together, in this order, against a
fresh pristine submodule checkout, and build successfully.
