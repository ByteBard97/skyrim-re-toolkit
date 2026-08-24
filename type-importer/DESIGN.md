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
| `BSTArray<T>` | Inherits `Allocator` (default `BSTArrayHeapAllocator`) then `BSTArrayBase`. Field order: `void* _data` @ 0x00, `uint32_t _capacity` @ 0x08 (`BSTArray.h:140-141`), `uint32_t _size` @ 0x10 (`BSTArray.h:47`, from `BSTArrayBase`, itself `0x4` bytes, `BSTArray.h:49`). `sizeof(BSTArrayHeapAllocator) == 0x10` (`BSTArray.h:143`). | `{ T* data; uint32_t capacity; /*pad 4*/ uint32_t size; }`, total `0x18`. **Order is `{data, capacity, size}`, not `{data, size, capacity}`** — base-class layout order (Allocator first, then BSTArrayBase) determines this, not declaration order in any one class. |
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

**This number (`0xA0`) is a strong derived hypothesis, not a header
`static_assert`.** It should still go through the Address Library / RTTI
cross-check in the validation plan before being treated as ground truth in a
shipped `.gdt`.

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

Unchanged from v0.1: generated `.gdt` files are treated as GPL-3.0 (inherited from
CommonLibSSE-NG), attributed to the source commit hash. `type-importer/` tooling
itself is MIT.

## Toolchain note (Linux-native validation)

Confirmed no system `clang` binary, only `libclang-14` shared libs (Ubuntu jammy).
No passwordless `sudo` available in this environment, so system package
installation isn't an option — using user-local prebuilt LLVM releases instead
(no root required): `clang+llvm-18.1.8-x86_64-linux-gnu-ubuntu-18.04` first
(failed to run — linked against `libtinfo.so.5`, which doesn't exist on this
system and isn't ABI-compatible with the `libtinfo.so.6` that is installed), now
retrying with `LLVM-19.1.0-Linux-X64.tar.xz` (a more recent, more portable
build). Both installed under `~/.local/tools/`, not the system.

**Not yet confirmed:** whether `-fms-extensions -fms-compatibility` (or
`clang-cl --target=x86_64-pc-windows-msvc`) on Linux actually reproduces MSVC's
real record layout for these headers, vs. just parsing without error. This is the
single most load-bearing unverified assumption in the whole Linux-native pipeline
— see progress log / open questions.

## Open questions / not yet resolved

- Does Linux clang (`-fms-extensions -fms-compatibility` or `clang-cl` with an
  MSVC target triple) actually produce MSVC-ABI-correct record layouts for these
  headers? Unverified — in progress.
- `GhidraClangPoweredParse`'s redundant-vptr bug: no workaround found yet (not in
  its issue tracker as of this pass — needs another look once we can actually
  build and run it).
- CommonLibSSE-NG's CMake build macros for selecting the AE 1.6.1170 target
  specifically (vs. some other AE point release) — not yet identified. Needed
  before compiling anything for real, since headers are multi-runtime by
  default and dispatch on macros like `ENABLE_SKYRIM_AE`.
- No CI trigger mechanism defined yet — out of scope until `symbol-archive`
  exists.
- Exact force-instantiation script implementation (recursive template-argument
  mining → explicit instantiation TU or `using`-alias TU → record-layout dump)
  not yet written.
