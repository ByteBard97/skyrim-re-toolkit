# type-importer — Design Doc (v0.1)

Status: pre-implementation. Scope is deliberately narrow: prove the pipeline on one
class hierarchy, one game runtime, before generalizing.

## Goal (2-week MVP)

Parse CommonLibSSE-NG headers for the `TESForm → TESObject → TESBoundObject →
TESObjectREFR` hierarchy, targeting **AE 1.6.1170** only, and emit a Ghidra Data Type
Archive (`.gdt`) with correct struct sizes and a usable vtable layout.

Non-goals for v0.1: other class hierarchies, other runtimes, IDA `.til` output, CI
automation. Those come after this slice proves the approach works.

## Base tooling

- **Parser base:** [`playday3008/GhidraClangPoweredParse`](https://github.com/playday3008/GhidraClangPoweredParse),
  vendored as a git submodule at `type-importer/vendor/GhidraClangPoweredParse`.
  It already handles class→struct conversion, vtable function-pointer entries,
  base-class embedding, bitfields, and packed attributes.
  Known gaps we have to patch around: **no C++ template instantiation support**, and
  a **redundant-vptr bug on polymorphic derived classes**.
- **Source of truth:** [`CharmedBaryon/CommonLibSSE-NG`](https://github.com/CharmedBaryon/CommonLibSSE-NG),
  vendored as a git submodule at `type-importer/vendor/CommonLibSSE-NG`.
- **Alternative considered and rejected as primary:** CastXML
  (`aerosoul94/GhidraCastXML.py`) only emits template instantiations that already
  appear in the translation unit — for a codebase saturated with `BSTArray<T>` /
  `REL::Relocation<T>` / `NiPointer<T>` across hundreds of `T`s, that misses most of
  the template surface unless everything is force-instantiated first anyway. Not
  worth using over libclang directly.

## Template flattening

Neither libclang nor CastXML expands templates on their own. Preprocessing step:
force-instantiate the concrete template types actually used in the target hierarchy
before parsing, then flatten known patterns as follows.

Verified against actual CommonLibSSE-NG source (not assumed — read directly from
`vendor/CommonLibSSE-NG/include/RE/B/BSTArray.h` and `include/REL/Relocation.h`):

| Template | Real layout (verified) | Flatten to |
|---|---|---|
| `BSTArray<T>` | Inherits `Allocator` (default `BSTArrayHeapAllocator`) then `BSTArrayBase`. Field order: `void* _data` @ 0x00, `uint32_t _capacity` @ 0x08, `uint32_t _size` @ 0x10 (inherited from `BSTArrayBase`, itself `0x4` bytes). `sizeof(BSTArrayHeapAllocator) == 0x10`, `sizeof(BSTArrayBase) == 0x4`. | Concrete struct per instantiation: `{ T* data; uint32_t capacity; /*pad 4*/ uint32_t size; }`. **Do not assume `{data, size, capacity}` order** — it's `{data, capacity, size}` because of base-class layout order (Allocator first, then BSTArrayBase). |
| `REL::Relocation<T>` | Single member `_impl` of `value_type` — `T` itself unless `T` is a member-pointer or function-pointer type, in which case `std::decay_t<T>`. Pointer/uintptr_t-sized in all practical RE usage. | `T` (or `uintptr_t` if `T` is itself abstract/incomplete in the flattened context). |
| `stl::enumeration<Flag, U>` | Not yet read from source for v0.1 (out of scope — not part of the TESForm slice). Research recommendation carried forward: emit `U` (the underlying integer) plus a companion Ghidra enum datatype. | `U` + enum. **Verify against source before using outside this slice.** |
| `NiPointer<T>` | Not yet read from source for v0.1 (out of scope). Research recommendation carried forward: single pointer-sized field. | `T*`. **Verify against source before using outside this slice.** |
| `BSTSmartPointer<T>` | Not yet read from source for v0.1 (out of scope). | `T*`, or the control-block struct if refcount visibility is needed later. |

Only `BSTArray<T>` and `REL::Relocation<T>` are verified against source so far,
because they're the only two that appear in the v0.1 target hierarchy. Do not import
the other rows into a general-purpose flattening table without re-verifying against
`vendor/CommonLibSSE-NG` first — they were carried over from research and are
unverified.

## MSVC ABI / vtable handling

Ghidra's datatype model cannot represent virtual base classes at all (upstream
maintainers describe it as "currently incompatible with virtual base classes"). Given
that constraint, and that we're targeting MSVC (not Itanium) ABI:

- Flatten multiple inheritance by embedding base-class subobjects directly into the
  derived struct at their real byte offsets. No attempt to model virtual bases.
- One `vftable` pointer field at offset 0 for the primary base; additional vftable
  pointers appear at the start of each secondary base subobject, per MSVC layout
  rules (vptrs at positive offsets, not Itanium-style negative offsets).
- For each class with a vtable, generate a companion `<Class>_vtbl` struct of
  function pointers and wire it as the type of the `vftable` member.

## Target hierarchy for v0.1

`TESForm → TESObject → TESBoundObject → TESObjectREFR`, chosen because it's the most
central, well-documented chain in the engine — a correct import here is immediately
useful to any reverser, and it's a real proof of the pipeline before generalizing.

Ground-truth sizes (from `static_assert` in CommonLibSSE-NG source — these are the
pass/fail bar for the generated `.gdt`):

| Class | `sizeof` (verified via `static_assert` in source) |
|---|---|
| `TESForm` | `0x20` |
| `TESObject` | `0x20` |
| `TESBoundObject` | `0x30` |
| `TESObjectREFR` | `0x98` |

## Target runtime for v0.1

**AE 1.6.1170 only.** Per CommonLibSSE-NG's own wiki warning: "do NOT use a
multi-runtime build because struct/vtable layouts may not match." 1.6.1170 is chosen
over 1.7.99 because it's been stable for ~2.5 years with maximum plugin
compatibility; 1.7.99 changed class layouts and the Address Library format (v2/format
5) and hasn't fully settled in CommonLibSSE-NG yet.

Planned order for future runtimes (not in v0.1 scope): SE 1.5.97 next (the
"downgrade" baseline, still heavily used), then AE 1.7.99 once settled, then VR/GOG.
A separate `.gdt` per runtime — never a unified/multi-runtime archive.

## Validation plan

Three checks, in order of cost:

1. **Static-assert size check (automated, cheap).** The generated Ghidra struct's
   size must exactly match the `static_assert(sizeof(...) == ...)` in the
   CommonLibSSE-NG source for that class. This is the fast, mechanical pass/fail
   gate — run it in CI once CI exists.
2. **Address Library offset cross-check.** For functions already present in
   meh321's Address Library (e.g. well-known vtable slots, Papyrus native
   registrations), verify the generated `.gdt`'s function signature at that vtable
   index matches what's actually at the corresponding address in the AE 1.6.1170
   binary.
3. **RTTI cross-check.** Independently run
   [`astrelsky/Ghidra-Cpp-Class-Analyzer`](https://github.com/astrelsky/Ghidra-Cpp-Class-Analyzer)
   against the target binary and compare its recovered class hierarchy (names,
   inheritance shape) against what we imported. They should agree on shape even
   where our version has richer field typing.

No single automated validator script exists yet for all three — that's follow-up
work once the v0.1 slice produces real output to check.

## Licensing note (carries through to symbol-archive later)

CommonLibSSE-NG is GPL-3.0-or-later with Modding and Linking Exceptions. A generated
`.gdt` is derived data from GPL-licensed headers, not a linked executable — but the
conservative position (and the one this project takes) is to treat generated `.gdt`
files as GPL-3.0 and attribute them to the specific CommonLibSSE-NG commit hash they
were generated from. This applies to `symbol-archive/`, not `type-importer/` itself
(the importer tooling/code here is MIT, per the root README).

## Open questions / not yet resolved

- No CI trigger mechanism defined yet (planned: scheduled poll of
  CommonLibSSE-NG's latest release tag via GitHub API, plus manual
  `workflow_dispatch`) — out of scope until symbol-archive exists.
- `stl::enumeration`, `NiPointer`, `BSTSmartPointer` flattening rows above are
  unverified against source — re-check before using them outside the TESForm slice.
- Exact preprocessing mechanism for forcing template instantiation (explicit
  instantiation TU vs. some other trick) is not yet designed.
