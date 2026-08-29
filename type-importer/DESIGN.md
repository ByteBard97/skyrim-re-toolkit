# type-importer — Design Doc (v0.2)

Status: pre-implementation, source-verified. v0.1 had two load-bearing wrong
assumptions (see "Corrections from v0.1" below) that were caught by reading actual
CommonLibSSE-NG source instead of trusting research-report heuristics. Everything
in this doc is now either (a) read directly from
`vendor/CommonLibSSE-NG/include/...` with a file:line citation, or (b) explicitly
marked unverified.

## Corrections from v0.1

1. **`TESObjectREFR` does NOT inherit from `TESBoundObject`.** v0.1 assumed a linear
   chain `TESForm → TESObject → TESBoundObject → TESObjectREFR`. That's wrong —
   `TESBoundObject` is unrelated to `TESObjectREFR` in the inheritance graph.
   `TESObjectREFR` uses **multiple inheritance** from four unrelated bases (see
   below). This was carried uncritically from the web research, which never opened
   the header.
2. **`sizeof(TESObjectREFR) == 0x98` is SE-only, not AE.** The header's own
   `static_assert` for this is wrapped in `#ifndef ENABLE_SKYRIM_AE`
   (`TESObjectREFR.h:510-511`). For AE 1.6.1170 (our actual target), the true size
   is **`0xA0`**, derived (not asserted) from two independent pieces of evidence —
   see "TESObjectREFR field map" below. Building the MVP against `0x98` would have
   produced a `.gdt` that silently fails the very check meant to validate it.

Both corrections came from actually reading the header rather than trusting a
size number quoted in a research summary. Lesson applied going forward: **treat
every unverified number as a hypothesis, and prefer deriving a number from two
independent sources over trusting one static_assert that might be version-gated.**

## Goal (2-week MVP) — unchanged in spirit, scope corrected

Parse CommonLibSSE-NG headers for `TESObjectREFR` and its real base classes,
targeting **AE 1.6.1170** only, and emit a Ghidra Data Type Archive (`.gdt`) with
correct struct sizes and a usable multi-vtable layout.

Non-goals for v0.1: other classes, other runtimes, IDA `.til` output, CI
automation.

## Base tooling

- **Parser base:** [`playday3008/GhidraClangPoweredParse`](https://github.com/playday3008/GhidraClangPoweredParse),
  vendored as a git submodule at `type-importer/vendor/GhidraClangPoweredParse`.
  Handles class→struct conversion, vtable function-pointer entries, base-class
  embedding, bitfields, packed attributes.
  Known gaps: **no C++ template instantiation support**, and a **redundant-vptr bug
  on polymorphic derived classes**. Neither gap has a documented workaround upstream
  (confirmed: the report that flagged this bug gave no fix, and our own read of the
  repo hasn't located one yet either — see "Open questions").
- **Source of truth:** [`CharmedBaryon/CommonLibSSE-NG`](https://github.com/CharmedBaryon/CommonLibSSE-NG),
  vendored as a git submodule.
- **CastXML rejected as primary** (only emits template instantiations already
  present in the translation unit — not viable given hundreds of concrete `T`s
  across the codebase; see "Force-instantiation targets" below for how many).

## Template flattening (all rows now source-verified)

| Template | Real layout (verified, with citation) | Flatten to |
|---|---|---|
| `BSTArray<T>` | Inherits `Allocator` (default `BSTArrayHeapAllocator`) then `BSTArrayBase`. Field order: `void* _data` @ 0x00, `uint32_t _capacity` @ 0x08 (`BSTArray.h:140-141`), `uint32_t _size` @ 0x10 (`BSTArray.h:47`, from `BSTArrayBase`, itself `0x4` bytes, `BSTArray.h:49`). `sizeof(BSTArrayHeapAllocator) == 0x10` (`BSTArray.h:143`). **Double-verified (2026-08-24):** force-instantiated `RE::BSTArray<RE::TESForm*>` for real via `scripts/generate_forced_instantiations.py` + `clang-cl -fdump-record-layouts-complete`, not just read from source — dump shows exactly `_data@0x00, _capacity@0x08, _size@0x10`, `sizeof=24 (0x18)`, matching this row exactly. | `{ T* data; uint32_t capacity; /*pad 4*/ uint32_t size; }`, total `0x18`. **Order is `{data, capacity, size}`, not `{data, size, capacity}`** — base-class layout order (Allocator first, then BSTArrayBase) determines this, not declaration order in any one class. |
| `REL::Relocation<T>` | Single member `_impl` of `value_type` (`Relocation.h:203+`) — `T` itself unless `T` is a member-pointer or function type, then `std::decay_t<T>`. | `T` (pointer/uintptr_t-sized in all struct-member usage we found — see instantiation list, most `Relocation<func_t>` usage is actually free-standing, not a struct member). |
| `NiPointer<T>` | Single member `element_type* _ptr` @ offset 0 (`NiSmartPointer.h:191`). Commented-out `static_assert(sizeof(NiPointer<void*>) == 0x8)` at `NiSmartPointer.h:193` confirms pointer-sized. Intrusive refcounting via the pointee's own `IncRefCount`/`DecRefCount` — no separate control block. | `T*`. |
| `BSTSmartPointer<T>` | Single member `element_type* _ptr` @ offset 0 (`BSTSmartPointer.h:227`). Same intrusive-refcount pattern as `NiPointer` (pointee's own `IncRef`/`DecRef` via a `reference_manager` policy template param) — no control-block struct. | `T*`. Contradicts the earlier research's "concrete layout per instantiation" guess — it's just a bare pointer, identical shape to `NiPointer<T>`. |
| `stl::enumeration<Flag, U>` | Single member `_impl` of `underlying_type` (`= U`) (`SKSE/Impl/PCH.h:221-269`, field at the class's only data member). | `U` directly. A companion Ghidra enum for `Flag`'s values is a nice-to-have, not structurally required — the struct-layout-relevant fact is just "it's `sizeof(U)` bytes." |

All five rows are now verified. Note two of the original research's claims were
wrong: `BSTSmartPointer` is not a richer structure than `NiPointer` (both are bare
pointers), and `stl::enumeration` actually lives in `SKSE::stl` inside
`SKSE/Impl/PCH.h` in this codebase, not in a dedicated `RE/S/stl/enumeration.h` file
as guessed.

## MSVC ABI / vtable handling

Ghidra's datatype model cannot represent virtual base classes. Checked directly:
**zero occurrences of `virtual public` or `: virtual` anywhere under
`include/RE/`** (grepped the whole namespace). So this codebase never uses virtual
inheritance — the "Ghidra can't model virtual bases" limitation is a non-issue for
everything we're targeting. Multiple inheritance (non-virtual) is common, though,
and matters a lot — see below.

- Flatten multiple inheritance by embedding base-class subobjects at their real
  byte offsets. No virtual-base handling needed (confirmed above).
- One `vftable` pointer per polymorphic base subobject, at the start of that
  subobject, per MSVC layout rules (positive offsets, not Itanium negative
  offsets).
- Per-class-with-vtable, generate a companion `<Class>_vtbl` function-pointer
  struct.
- **This is not a hypothetical edge case** — our actual v0.1 target,
  `TESObjectREFR`, has **three separate vtables** in one object (see field map
  below). Multi-vtable flattening is a first-week concern, not a stretch goal.

## TESObjectREFR field map (source-verified, `TESObjectREFR.h`)

Real inheritance (`TESObjectREFR.h:108-113`):

```cpp
class TESObjectREFR :
    public TESForm,                              // 0x00
    public BSHandleRefObject,                    // 0x20
    public BSTEventSink<BSAnimationGraphEvent>,  // 0x30
    public IAnimationGraphManagerHolder          // 0x38
```

Verified base sizes:

| Base | Offset | Size | Vtable? | Citation |
|---|---|---|---|---|
| `TESForm` | 0x00 | 0x20 | yes (primary) | prior verification, unchanged |
| `BSHandleRefObject` | 0x20 | 0x10 | yes — inherits `NiRefObject` (`virtual ~NiRefObject()`, `NiRefObject.h:13`) | `BSHandleRefObject.h:25` |
| `BSTEventSink<BSAnimationGraphEvent>` | 0x30 | 0x8 (vptr only, inferred from the 0x38−0x30 gap to the next base) | yes | offset arithmetic from `TESObjectREFR.h:108-113` comments |
| `IAnimationGraphManagerHolder` | 0x38 | 0x8 (vptr only — pure interface, no data members) | yes | `IAnimationGraphManagerHolder.h:52` (`static_assert(sizeof(...) == 0x8)`) |

So **three of the four bases are polymorphic** — this class needs three vftable
pointers correctly placed at 0x00, 0x20, and 0x38 (0x30's vtable pointer *is* the
base of that subobject too, at 0x30).

Own members start at 0x40 (`TESObjectREFR.h:494-498`):

| Offset | Field | Type | Size |
|---|---|---|---|
| 0x40 | `data` | `OBJ_REFR` (`TESObjectREFR.h:71-81`, verified `static_assert(sizeof(OBJ_REFR) == 0x20)`) | 0x20 |
| 0x60 | `parentCell` | `TESObjectCELL*` | 0x8 |
| 0x68 | `loadedData` | `LOADED_REF_DATA*` | 0x8 |
| 0x70 | `extraList` | `ExtraDataList` | (not fully sized this pass — see gap analysis below) |

### The runtime-relocated tail, and how we got 0xA0 for AE

Past `extraList`, the header does **not** declare the remaining fields as normal
struct members for AE builds. It only does so `#ifndef ENABLE_SKYRIM_AE`
(`TESObjectREFR.h:500-502`), where it inlines `RUNTIME_DATA_CONTENT` — a macro
expanding to `unk88 (u64) + refScale (u16) + modelState (i8) + preDestroyed (bool) +
pad94 (u32)` = `0x10` bytes (`TESObjectREFR.h:474-479`).

For **AE builds these are not compiled struct members at all** — they're read via
`REL::RelocateMemberIfNewer<REFERENCE_RUNTIME_DATA>(SKSE::RUNTIME_SSE_1_6_629, this,
0x88, 0x90)` (`TESObjectREFR.h:484-491`): raw pointer arithmetic on `this`, picking
offset `0x88` for pre-1.6.629 runtimes and `0x90` for 1.6.629+ (which includes every
AE version, including our 1.6.1170 target). This is CommonLibSSE-NG's pattern for
fields whose offset moved across versions: don't declare them as a compile-time
member at all, compute the address at runtime instead. **Consequence: the
library's own `sizeof(TESObjectREFR)` under an AE compile is smaller than the
game's real object size** — the compiler doesn't need to know about memory past
the last declared member.

For our purposes (telling Ghidra the true size of the real game object), the
number that matters is `0x90 + 0x10 = 0xA0`, not whatever the C++ compiler
computes for CommonLibSSE-NG's own (intentionally partial) struct.

**Independent cross-check, found separately in `Actor.h`:** `Actor`'s inheritance
list is version-gated too (`Actor.h:123-135`). The non-AE branch lists secondary
bases with dual offset comments — `MagicTarget, // 098, 0A0` — meaning even within
non-AE SE, `TESObjectREFR`'s effective size is `0x98` before the 1.6.629 hotfix and
`0xA0` after it (matching the `0x88`→`0x90` relocation switch exactly). And for AE,
`Actor`'s inheritance collapses to `public TESObjectREFR` alone
(`Actor.h:130-131`) — everything that used to be a separate base
(`MagicTarget`, `ActorValueOwner`, `ActorState`, two `BSTEventSink<...>`,
`IPostAnimationChannelUpdateFunctor`) got folded elsewhere for AE. This
independently confirms **`0xA0`** as the AE `TESObjectREFR` size, agreeing with
the relocation-offset math above from a completely different part of the codebase.

**Superseded by real-compiler evidence, and revised further (2026-08-24).**
Got a real header-based, `clang-cl -fdump-record-layouts-complete` compile of
the actual `TESObjectREFR` (via the stub PCH described in the toolchain note
below) working. It reproduces every hand-derived offset above exactly —
`TESForm@0x00`, `BSHandleRefObject@0x20`, `BSTEventSink@0x30`,
`IAnimationGraphManagerHolder@0x38`, own members starting `@0x40`,
`OBJ_REFR data@0x40`, `parentCell@0x60`, `loadedData@0x68`,
`extraList@0x70` — but reports **`sizeof(TESObjectREFR) == 0x78`** (120),
not `0xA0`.

The reason isn't a bug in the reasoning above — it's a **second instance of
the exact same "invisible relocated member" pattern**, this time inside
`extraList`'s own type. `RE::BaseExtraList` (`RE/E/ExtraDataList.h:18-46`)
declares its `data`/`presence` pointer members **only**
`#ifndef ENABLE_SKYRIM_AE` (`ExtraDataList.h:39-42`, with the header's own
comment confirming it: `"~BaseExtraList(); // 00, virtual on AE 1.6.629 and
later"`). Under `ENABLE_SKYRIM_AE=1`, `BaseExtraList` compiles to a
genuinely **empty class** (verified: clang's dump shows it as `(empty)`,
`sizeof=1`) — its two pointers are accessed via the same
`REL::RelocateMember`-style runtime-offset trick as `TESObjectREFR`'s own
tail, not as compiled struct members. `ExtraDataList` (which wraps a single
`BaseExtraList _extraData` member) inherits that emptiness.

**Consequence:** the `0x78` clang reports for `TESObjectREFR` is
CommonLibSSE-NG's own AE-compiled size with **two separate blocks of
invisible relocated data** excluded — `BaseExtraList`'s own two pointers
*and* `TESObjectREFR`'s own `RUNTIME_DATA_CONTENT` tail. The true game
object size is larger than either `0x78` (what clang reports) or the
earlier `0xA0` hypothesis (which only accounted for one of the two
invisible blocks). **Neither number should be trusted as the real object
size without binary-level ground truth** (Address Library cross-check or
direct disassembly) — this is now a confirmed instance of a recurring
CommonLibSSE-NG pattern, not a one-off, so expect it in other classes with
"AE moved this field" history too, and don't assume clang's `sizeof` under
`ENABLE_SKYRIM_AE` is the true object size for any class that has ever had
a runtime-relocated member.

**What this changes for the `.gdt` output:** a generated Ghidra struct
based on naively parsing these headers under `ENABLE_SKYRIM_AE` will be
undersized wherever this pattern occurs. The type-importer needs to detect
uses of the relocation-accessor pattern (`REL::RelocateMember[IfNewer]`
called from an inline accessor with no backing declared member) and either
(a) append the accessed-but-undeclared trailing bytes to the emitted
struct's size, or (b) flag the class as "layout incomplete, needs manual
tail sizing" rather than silently emitting a too-small struct. Not yet
designed — tracked in open questions.

## Multiple inheritance / virtual bases — codebase-wide check

- Grepped all of `include/RE/` for `virtual public` and `: virtual`: **zero
  matches.** No virtual inheritance anywhere in this codebase's public headers.
- `NiAVObject : public NiObjectNET` — single inheritance (`NiAVObject.h:49`).
- `Actor`'s AE inheritance is single (`public TESObjectREFR` only); its non-AE
  (SE) inheritance is 7-way multiple inheritance including two different
  `BSTEventSink<T>` instantiations on the *same* class (`Actor.h:123-135`) — a
  case worth remembering for when SE 1.5.97 becomes the next target, since two
  polymorphic bases of "the same template, different `T`" need two independently
  named `_vtbl` types on the same class.

## Force-instantiation targets (mined from `include/RE/`, top results)

Method: `grep -rhoP 'TemplateName<\K[^>]+(?=>)' RE/ | sort | uniq -c | sort -rn`.

- `BSTArray<T>`: `void*` (76), `TESForm*` (12), `ActorHandle` (12), nested
  `NiPointer<NiAVObject>` (8), `TESQuest*` (7), `ObjectRefHandle` (7),
  `std::uint32_t` (6), nested `NiPointer<BSTempEffect>` (6), `BSNavmeshInfo*` (5).
- `NiPointer<T>`: `NiNode` (92), `NiAVObject` (48), `TESObjectREFR` (47),
  `NiSourceTexture` (46), `NiFloatInterpolator` (23), `NiTexture` (18),
  `BSTriShape` (18), `Actor` (14), `BSLight` (11).
- `BSTSmartPointer<T>`: `Object` (46), `ObjectTypeInfo` (34),
  `BShkbAnimationGraph` (21), `BSAnimationGraphManager` (15), `BipedAnim` (14).
- `stl::enumeration<T,U>`: `Flag, std::uint32_t` (31), `Flag, std::uint8_t` (29),
  `Flags, std::uint32_t` (12), `Type, std::uint8_t` (9).
- `REL::Relocation<T>`: `func_t` (102 — overwhelmingly function-pointer
  relocations, not struct-member data relocations), scattered pointer types
  otherwise.

**Confirmed:** nested template instantiation is real and must be handled
(`BSTArray<NiPointer<NiAVObject>>` appears 8 times) — the force-instantiation
script needs to recurse into template arguments, not just top-level matches.

## Target runtime for v0.1

**AE 1.6.1170 only**, per CommonLibSSE-NG's own wiki warning against multi-runtime
builds. Planned order after v0.1 proves out: SE 1.5.97, then AE 1.7.99, then
VR/GOG — a separate `.gdt` per runtime, never unified.

## Validation plan

1. **Static-assert size check** — but now known to be version-gated in some
   headers (see corrections above). Before trusting any `static_assert` as the
   AE ground truth, check whether it's wrapped in `#ifndef ENABLE_SKYRIM_AE` /
   `#ifdef ENABLE_SKYRIM_AE` first. A size check against the wrong branch's
   assert is worse than no check — it gives false confidence.
2. **Address Library offset cross-check** against the real AE 1.6.1170 binary.
3. **RTTI cross-check** via `astrelsky/Ghidra-Cpp-Class-Analyzer`.

No automated validator script yet — deferred until the pipeline produces real
output.

## Licensing note

Generated `.gdt` files are derived from CommonLibSSE-NG's headers, which are
MIT-licensed (CharmedBaryon/CommonLibSSE-NG — check the vendored `LICENSE` file,
not folklore: some *other* CommonLib forks are GPL-3.0, this one is not).
Archives are attributed to the source commit hash and keep the MIT attribution.
`type-importer/` tooling itself is MIT. The vendored `GhidraClangPoweredParse`
extension is Apache-2.0; the patches applied to it remain Apache-2.0-compatible.

## Toolchain note (Linux-native validation)

Distro-packaged libclang is typically too old (e.g. Ubuntu jammy ships
`libclang-14`, which MSVC's STL headers reject). A user-local prebuilt LLVM
release works without root. Note that older release tarballs can have their own
portability problems: `clang+llvm-18.1.8-x86_64-linux-gnu-ubuntu-18.04` links
against `libtinfo.so.5`, absent on current distros and not ABI-compatible with
the installed `libtinfo.so.6`. `LLVM-19.1.0-Linux-X64.tar.xz` (the newer, more
portable build) works out of the box — install under `~/.local/tools/` or
similar, no system packages needed.

**CONFIRMED (2026-08-24):** `clang-cl` from `LLVM-19.1.0-Linux-X64` (user-local
install under `~/.local/tools/`, defaults its target to
`x86_64-pc-windows-msvc` — no extra flags needed) correctly reproduces MSVC
record layout rules on Linux. Verified with a synthetic reproduction of the real
`TESObjectREFR` multiple-inheritance shape (`TESForm` + `BSHandleRefObject` +
two vtable-only interfaces + trailing own-data members) via
`clang-cl -Xclang -fdump-record-layouts -fsyntax-only`. Output placed every base
subobject and every own-member at exactly the offsets hand-derived from the
header in the field map above: `0x00`, `0x20`, `0x30`, `0x38`, `0x40`. This is
strong evidence the whole Linux-native libclang pipeline is viable — record
layout, not just parsing, matches MSVC.

Two notes for reproducing this: (1) `LLVM-19.1.0-Linux-X64.tar.xz` was needed,
not `clang+llvm-18.1.8-...-ubuntu-18.04.tar.xz` — the 18.04-targeted build links
against `libtinfo.so.5`, which isn't present or ABI-compatible with this
system's `libtinfo.so.6`, and there's no passwordless `sudo` to install it
system-wide. (2) `clang-cl` cannot find `<cstdint>` etc. without a real Windows
SDK/MSVC STL on disk — the synthetic test avoided the STL entirely (used
`unsigned int` etc. instead of `std::uint32_t`). Compiling *real*
CommonLibSSE-NG headers will hit this for real and need either a vendored
Windows SDK header set, or `-nostdinc++`/stub headers for the small slice of
STL surface actually used in class layouts (`<cstdint>`, `<utility>` for
`std::pair`, etc.) — not yet solved, see open questions.

## Open questions / not yet resolved

- ~~Does Linux clang produce MSVC-ABI-correct record layouts?~~ **Resolved: yes**,
  confirmed via `clang-cl` synthetic test, see toolchain note above.
- ~~Real CommonLibSSE-NG headers pull in real STL... Not yet solved~~
  **Resolved.** `stubs/layout_pch.h` (real STL includes + minimal stand-ins
  for `REL::Relocation`, `stl::enumeration`, etc.) plus `xwin`-acquired
  Windows SDK/CRT headers solves this for `clang-cl` layout verification.
  Confirmed real CommonLibSSE-NG headers (`TESForm.h` through
  `TESObjectREFR.h`) compile with **zero errors** through this stub.
- **MAJOR MILESTONE (2026-08-24): produced a real `.gdt` file from actual
  CommonLibSSE-NG headers using the actual (patched) `GhidraClangPoweredParse`
  extension** — not just a clang-cl layout dump. Installed JDK 21 + Ghidra
  12.1.3 (both user-local), applied the patches in `patches/`, and ran
  `SourceParser.parseFiles` directly (via a standalone harness, same
  technique as the patch verification tests) against `TESForm.h`,
  `TESObject.h`, `TESBoundObject.h`, `TESObjectREFR.h`, force-including
  `stubs/layout_pch.h`. Result: **zero clang diagnostics**, ~3746 real data
  types resolved and committed to an actual `.gdt` file via
  `FileDataTypeManager.createFileArchive` (the same API path the real
  Ghidra UI plugin uses).
- ~~Class template specialization fields (e.g. `stl::enumeration<...>`)
  can never resolve~~ **SOLVED (2026-08-24).** Root-caused precisely with
  two independent tools outside this Java layer: `c-index-test` (libclang's
  own cursor-inspection CLI) showed a template specialization is never
  exposed as a visitable declaration cursor via `clang_visitChildren`
  — only the uninstantiated primary template plus a `TemplateRef` at the
  use site — even though Clang's internal AST (`-ast-dump`) shows the real
  `ClassTemplateSpecializationDecl` node exists. A minimal, from-scratch
  libclang C program confirmed this further against the real
  `TESForm::inGameFormFlags` field: `clang_getTypeDeclaration` resolves a
  `CLASS_DECL` cursor, `clang_isCursorDefinition` on it returns true,
  `clang_Type_getSizeOf` gives the correct size (2 bytes) — the type is
  genuinely, fully instantiated — yet `clang_visitChildren` on that same
  cursor still finds zero children. **The fix:** `clang_Type_visitFields`
  (a different libclang API that walks `CXXRecordDecl::field_begin()`/
  `field_end()` directly) finds the field correctly in the exact same
  case. Added as a new `Type.visitFields()` binding
  (`patches/0004-add-libclang-introspection-bindings.patch`) and wired
  into `SourceParser`'s field-handling logic
  (`patches/0003-inline-template-specialization-fields.patch`, superseding
  an earlier version of that patch which used the broken
  `declaration().visitChildren()` approach and didn't work). Verified: a
  debug trace across the real header chain shows `parseFieldsFromType`
  correctly resolving real fields for all 9 distinct `stl::enumeration<...>`
  instantiations encountered.

  Getting to this took five ruled-out hypotheses first, each tested
  individually against the real headers (not guessed) — source-level
  force-instantiation, `-fdelayed-template-parsing`, `.skipFunctionBodies()`,
  `.parseIncomplete()`, and the declaration-vs-definition cursor
  distinction. See `patches/0003-inline-template-specialization-fields.md`'s
  "Investigation history" for the full list and the lesson learned: when a
  Java/Panama binding produces a surprising result, drop to a minimal C
  program against the same C API before assuming the binding layer is at
  fault.

  **Follow-up, same session — also solved (patch 0005):** the `FormID`
  blocker turned out to be much bigger than `FormID` alone — `TypePool`
  never stripped a leading `std::` namespace qualifier when normalizing
  type names, so **every plain `std::uint32_t`/`std::uint8_t` field
  anywhere in the codebase** (an extremely common pattern) was stuck
  unresolved. Fixed by stripping `std::` in `normalizeTypeName`, safe
  unconditionally since this codebase's own types never carry that
  prefix. This was the single highest-leverage fix of the whole
  investigation: resolved-type count jumped from 3746 to 3895 from this
  one change, and **`TESForm` immediately came out at exactly `0x20`
  bytes**, matching its `static_assert` field-for-field (see
  `patches/0005-fix-std-namespace-and-base-class-templates.md`).

  A second, related gap surfaced immediately after: `TESObjectREFR` still
  didn't resolve, blocked on `BSTEventSink<BSAnimationGraphEvent>` — the
  *same* template-specialization problem patch 0003 solved for fields,
  but this time as a **base class**, which goes through an entirely
  separate code path. Extended the same `Type.visitFields()`-based
  inlining to base classes, plus a padding fix for vtable-only template
  bases (which have zero explicit fields but a real, non-zero
  `clang_Type_getSizeOf`) and a canonical-type fix for template members
  typed via a nested alias (`stl::enumeration`'s own `underlying_type`).
  **Result: `TESObject` and `TESBoundObject` also now match their
  `static_assert`s exactly, and `TESObjectREFR`'s full multi-base layout
  matches this doc's independently clang-cl-verified offsets exactly**
  (`TESForm@0x00`, `BSHandleRefObject@0x20`, `BSTEventSink@0x30`,
  `IAnimationGraphManagerHolder@0x38`, `data@0x40`, `parentCell@0x60`,
  `loadedData@0x68`, `extraList@0x70`) — with one small, already-
  understood discrepancy remaining (`0x70` vs. the real compiler's
  `0x78`, a C++ struct-alignment padding artifact for `extraList`'s
  trailing empty-class contribution, not a new bug — see patch 0005's
  writeup for the precise explanation, which ties directly back to the
  "invisible relocated member" pattern already documented above).
- Third-party tool bugs found and fixed in `GhidraClangPoweredParse`
  during bring-up, beyond the redundant-vptr one below: **forward-declaration
  overwrite** — `TypePool.addParsedType` let a later, empty forward
  declaration of an already-fully-parsed class silently clobber the real
  definition with no diagnostic (extremely common pattern; CommonLibSSE-NG
  forward-declares classes like `TESForm` in dozens of files). Fixed in
  `patches/0002-fix-forward-decl-overwrite.patch`, verified not to regress
  anything, though it turned out not to be the cause of the `TESForm`
  emptiness above (that's the template-instantiation issue) — it's a real,
  separate, correctly-fixed bug in its own right.
- ~~`GhidraClangPoweredParse`'s redundant-vptr bug: no workaround found~~
  **Root-caused (2026-08-24)**, read directly from source
  (`src/main/java/playday3008/gcpp/processing/SourceParser.java:308-369`):
  - `parseStruct` collects `baseClasses` (from `C_X_X_BASE_SPECIFIER` cursors,
    `:308-317`) and `virtualMethods` (any virtual method or destructor
    declared/overridden *directly on this class*, `:320-336`) as two separate
    lists, with **no relationship tracked between them**.
  - At `:351-369`, the final field list is built as: `if virtualMethods is
    non-empty, add a brand-new synthetic "vptr" field` (`:354-359`) — **always**,
    regardless of whether any of `baseClasses` is itself polymorphic — followed
    by the embedded base-class fields (`:362-365`, which for an already-
    polymorphic base already contains that base's own vptr as its first
    member).
  - **Consequence:** any derived class that overrides even one virtual method
    from a polymorphic base gets *two* vptr fields where MSVC has one — the
    spurious new one from `:354-359`, plus the correct inherited one already
    embedded inside the base-class field. This shifts every subsequent field
    by 8 bytes and produces a wrong total size. This isn't an edge case: it
    fires on essentially every override in an inheritance chain, including our
    exact target (`TESObjectREFR` overrides base virtuals from `TESForm`).
  - **Fixed and functionally verified (2026-08-24).** Installed JDK 21
    (Temurin) and Ghidra 12.1.3 locally (both user-local, no sudo on this
    box), built the extension for real, wrote a standalone Java harness
    that calls `SourceParser.parseFiles` directly against a synthetic
    reproduction of `TESObjectREFR`'s exact shape (primary polymorphic
    base with an overridden virtual, plus a secondary polymorphic base),
    and did a clean A/B: unpatched code produces the spurious extra
    `vptr` field exactly as predicted; patched code produces zero. See
    `patches/0001-fix-redundant-vptr.md` for the full fix, diff, and
    verification writeup. Patch lives at
    `patches/0001-fix-redundant-vptr.patch` — applied and tested against
    the vendored submodule's working tree, then reverted to keep the
    submodule pristine, per this repo's own convention of not committing
    into `vendor/`.
- ~~CommonLibSSE-NG's CMake build macros for selecting the AE 1.6.1170 target~~
  **Resolved (2026-08-24).** `CMakeLists.txt:4-6` defines three independent
  options, **all `ON` by default**: `ENABLE_SKYRIM_SE`, `ENABLE_SKYRIM_AE`,
  `ENABLE_SKYRIM_VR`. The project's own default CMake configure is therefore
  a **multi-runtime build** — exactly what the wiki warns against for a
  reversing target. A true single-runtime AE-only configure needs all three
  passed explicitly:
  `cmake -DENABLE_SKYRIM_SE=OFF -DENABLE_SKYRIM_AE=ON -DENABLE_SKYRIM_VR=OFF ...`
  (our clang-cl layout tests already did the raw-preprocessor equivalent
  correctly, by defining only `ENABLE_SKYRIM_AE=1` and nothing else — worth
  calling out explicitly since it wasn't a deliberate choice at the time,
  just happened to be right).

  **Bigger finding: "AE" is a family, not one point release.** There is no
  separate compile-time macro for 1.6.1170 vs. 1.6.640 vs. other AE point
  releases. Within `ENABLE_SKYRIM_AE`, CommonLibSSE-NG targets the *whole*
  AE family with one compiled binary, and handles the handful of fields
  that moved between AE point releases (like `TESObjectREFR`'s runtime-data
  tail) via runtime dispatch — `REL::RelocateMemberIfNewer<T>(SKSE::
  RUNTIME_SSE_1_6_629, this, seOffset, aeOffset)` picks an offset by
  comparing the *actually running game's detected version* against a
  threshold (here, 1.6.629) at runtime, not by a compile-time macro per
  point release. So "target AE 1.6.1170" isn't really a CommonLibSSE-NG
  compile-time decision — it's a decision about **which Address Library
  version and which real game binary you validate the generated `.gdt`
  against**, not which macros you pass. This changes how to think about
  "one `.gdt` per runtime": the `.gdt` for "AE" is genuinely valid across
  the AE point-release range CommonLibSSE-NG supports, *provided* the
  version-gated fields (few, but real — flagged wherever
  `RelocateMember[IfNewer]` appears) are handled correctly, which requires
  knowing which real address to bake in for the specific binary being
  analyzed.
- No CI trigger mechanism defined yet — out of scope until `symbol-archive`
  exists.
- Exact force-instantiation script implementation (recursive template-argument
  mining → explicit instantiation TU or `using`-alias TU → record-layout dump)
  not yet written.
