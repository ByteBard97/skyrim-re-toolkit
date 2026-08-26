# TIL Export — Design Doc (v0.1)

Status: pre-implementation, web-research-verified only. **No IDA anything has
been run or even seen on this project** — no IDA install, no SDK, no `idapro`
wheel, no `tilib`, no `idaclang` on the dev machine or the Windows build box
(verified 2026-08-26 by checking both). Every claim below about an IDA API or
tool is sourced from Hex-Rays documentation or public code, cited inline, and
should be treated as a hypothesis until the first with-IDA run confirms it.
That distinction is called out per-claim wherever it matters.

This doc is the IDA-side sibling of `DESIGN.md`'s Ghidra `.gdt` pipeline. It
is written so that someone with an IDA 9.x license can execute it without
asking us questions — everything gated on IDA access is isolated in clearly
marked steps, and everything testable without IDA has a concrete test plan.

## Goal

Emit an IDA Type Library (`.til`) containing the same CommonLibSSE-NG type
information the existing pipeline already emits as a Ghidra `.gdt` — same
classes, same field offsets, same sizes, same multi-vtable flattening — so IDA
users analyzing `SkyrimSE.exe` get what Ghidra users already get.

Success metric, same as the `.gdt` side: the ~2,064 classes currently `OK`
(byte-accurate against the headers' own `static_assert`s, per
`coverage_baseline.json` as of 2026-08-26) must come out byte-identical in
the `.til`, and no class may silently change size or offset in translation.

## Non-goals

- **No function prototypes / symbol application.** The `.gdt` pipeline emits
  type information only; Address Library ID → function-prototype mapping is
  `symbol-archive`'s problem. A `.til` *can* carry symbols (`tilib`'s dump
  format shows a SYMBOLS section), but v0.1 carries TYPES only.
- **Not a unified multi-runtime `.til`.** Same rule as `.gdt`: one archive per
  runtime (AE first, then SE 1.5.97, then VR), never merged. See `DESIGN.md`
  "Target runtime".
- **No re-implementation of the C++ parse.** We already have a patched,
  verified libclang pipeline with ~24 patches of hard-won fixes (template
  inlining, redundant-vptr, forward-decl clobbering, empty-base optimization,
  tail-padding for runtime-relocated members). Any route that throws that away
  and re-parses the raw headers with a different C++ frontend inherits none of
  it — see Route D below for why that makes it a comparison tool, not a
  primary route.
- **No CI automation yet** — same status as the `.gdt` side.

## What the pipeline already has (intermediate data inventory)

Everything a `.til` emitter needs is already computed, in-process, by
`tools/GenerateGdt.java`. Concretely, after `SourceParser.parseFiles` +
`TypePool.resolve()` and the commit into a `FileDataTypeManager`
(`GenerateGdt.java:105-167`):

- **Fully-resolved Ghidra `DataType` objects** for every class: `Structure`s
  with component names, types, **explicit byte offsets**, and lengths. The
  committed archive is the ground truth, not the pre-commit list — Ghidra
  finalizes struct lengths at commit time, and measuring pre-commit was found
  to silently misreport sizes (see `GenerateGdt.java:172-184`).
- **Flattened multiple inheritance**: base subobjects embedded as ordinary
  fields at their real MSVC offsets (e.g. `TESObjectREFR`: `TESForm`@0x00,
  `BSHandleRefObject`@0x20, `BSTEventSink<...>`@0x30,
  `IAnimationGraphManagerHolder`@0x38 — `DESIGN.md`).
- **Vtables as companion structs**: one `<Class>_vtbl` function-pointer struct
  per polymorphic subobject, with the vptr as an ordinary first field. This is
  exactly the shape IDA itself uses for C++ classes — IDAClang's own output
  for a polymorphic class is `struct __cppobj C { C_vtbl *__vftable /*VFT*/; }`
  plus a separate `C_vtbl` struct (Hex-Rays IDAClang tutorial,
  <https://docs.hex-rays.com/ida-9.2/user-guide/types/type-libraries/idaclang_tutorial>),
  so no impedance mismatch here.
- **Enums** (`Enum` DataTypes with name→value members).
- **Typedefs/pointers/arrays** as resolved DataType references.
- **Post-commit mutations**: the tail-padding hint pass
  (`GenerateGdt.java:251-310`) widens specific structs for the
  invisible-`RelocateMember` pattern. Any JSON dump must happen **after** this
  pass, or the JSON will disagree with the shipped `.gdt` for exactly the
  classes the hints exist for (`BaseExtraList`, `ExtraDataList`, per
  `tail_padding_hints.csv`).
- **Provenance per class**, via `coverage_baseline.json`: `expected` size from
  the mined `static_assert`, `actual` committed size, `status`
  (OK / NO_GROUND_TRUTH / MISMATCH / EMPTY / UNRESOLVED). 2,064 OK, 1,852
  NO_GROUND_TRUTH, 879 EMPTY, 47 MISMATCH, 27 UNRESOLVED as of this writing.

None of this requires IDA. The only IDA-specific step in this entire design
is the final `store_til()` call.

## Routes

### Route A (RECOMMENDED PRIMARY): idalib headless script, JSON in, `.til` out

A standalone Python script using **idalib** — IDA-as-a-library, shipped with
IDA Pro 9.0+ (also IDA Home 9.4+; OEM license needed only for SaaS/embedding,
not for this use — Hex-Rays idalib overview,
<https://docs.hex-rays.com/core/idalib/overview>). The `idapro` wheel ships
inside the IDA install (`<IDA>/idalib/python/idapro-*.whl`, per community
usage docs and Hex-Rays' own release notes,
<https://docs.hex-rays.com/release-notes/9_0>). It runs the full IDAPython API
in an ordinary Python process, no GUI, no RPC — scriptable in CI on the
Windows build box the same way `generate_gdt.sh` is scriptable here.

The script consumes the intermediate JSON (schema below) and builds types
**programmatically** via `ida_typeinf`:

- `tinfo_t.create_udt()` + `add_udm()` per member, `create_enum()` per enum.
  IDA 9.x removed `ida_struct`/`ida_enum` entirely; `ida_typeinf`'s UDT API is
  the only way (IDA 8.x→9.0 porting guide,
  <https://docs.hex-rays.com/developer-guide/idapython/idapython-porting-guide-ida-9#ida_struct>).
- **Member offsets are in BITS, not bytes** — multiply by 8. This is a known
  IDA 9.x gotcha documented in the porting guide and independently in
  third-party agent notes
  (<https://github.com/buzzer-re/Rikugan/blob/main/AGENTS.md>). Getting this
  wrong produces structs 8× too large with no error; the verification plan
  below exists partly to catch exactly this class of mistake.
- `tinfo_t.set_named_type(til, name)` to register each type into a fresh
  `til_t` from `ida_typeinf.new_til(name, desc)`, then `compact_til(til)` +
  `store_til(til, tildir, name)` + `free_til(til)`. This exact call sequence is
  the one in Hex-Rays' own shipped example `create_libssh2_til.py`
  (documented at <https://docs.hex-rays.com/developer/idapython/idapython-examples>
  and in the `ida_typeinf` API reference,
  <https://python.docs.hex-rays.com/ida_typeinf/index.html>).

Because offsets are set explicitly per member, IDA's C parser never gets a
vote on layout — MSVC-ABI correctness is inherited from our pipeline, not
re-derived. This is the key advantage over every other route.

**Trade-offs:**

- (+) Byte-exact control; zero new layout logic; reuses the verified pipeline
  output verbatim.
- (+) Fully headless and scriptable; no GUI session to babysit.
- (+) Written against documented, currently-shipped APIs with an official
  example for the exact `new_til → store_til` flow.
- (−) Requires IDA Pro 9.0+ specifically (idalib does not exist in 8.x). The
  Skyrim RE community skews to recent IDA, but not universally — mitigated by
  Route B, which is the same script with a different entry point.
- (−) **Unverified:** idalib's normal entry point is
  `idapro.open_database(path, ...)`, which wants an input file. Whether a TIL
  can be built with *no* database open, or whether we need to open a dummy
  file (e.g. an empty binary in binary-loader mode) first, is not stated in
  any doc found. First with-IDA step #1 answers this (below). Worst case: one
  dummy file, no analysis, cost ≈ zero.
- (−) The `tinfo_t` builder code must initially be written **blind** — no IDA
  here to even import-check it. Mitigated by keeping it small and mechanical,
  and by the JSON-level verification doing all the real correctness work
  before IDA ever runs (see Verification).

**Fallback within Route A:** instead of building `tinfo_t`s member-by-member,
render C declarations from the JSON and hand them to
`ida_typeinf.parse_decls(til, input, printer, hti_flags)` (documented in the
`ida_typeinf` reference; also what `create_libssh2_til.py` uses). Less code,
but now IDA's internal C parser decides member offsets from declaration order
and packing, so we must emit explicit padding fields — re-introducing a
second layout engine into the pipeline, which is precisely what Route A's
programmatic construction avoids. Keep as plan B if the `udm_t` API fights us.

### Route B: IDAPython script inside a running IDA GUI, JSON in

Same JSON, same `ida_typeinf` building code as Route A — only the entry point
differs (run from IDA's script runner / `-S` headless `idat` invocation
instead of the `idapro` wheel).

- (+) Works on IDA 8.4 (last version with the `ida_typeinf` UDT API fully in
  place) and even 7.x with porting — broader than Route A's 9.0+ floor.
- (+) Lets a human watch the Local Types window fill in and spot-check
  interactively during bring-up.
- (−) Not CI-friendly in GUI form; the `idat -S` headless form is fine but is
  then just a worse idalib (extra process, license seat held, database
  bookkeeping).
- (−) Duplicates Route A's core logic; the two must share one builder module
  or they will drift.

**Verdict:** not a separate implementation — Route A's script should be
written to run under both `idapro` and in-IDA IDAPython from the start (guard
the ~10 lines of entry-point code; keep the builder shared). Listed as a route
because it changes *who can run it*, not because it's different code.

### Route C: `tilib` from a generated C-header dump

`tilib` is Hex-Rays' standalone TIL builder: `tilib -c -hinput.h output.til`
(Hex-Rays TILIB docs,
<https://docs.hex-rays.com/9.0/user-guide/type-libraries/tilib>). Since IDA
9.1 it ships in the IDA install's `tools/` folder; before that it was a
registered-user download from the My Hex-Rays portal (Hex-Rays helper-tools
page, <https://docs.hex-rays.com/user-guide/helper-tools>).

The pipeline would gain a JSON → C header renderer (flattened structs with
explicit `unsigned char _pad_XX[N];` gap fillers, enums, typedefs — all
expressible in C), and `tilib` parses that.

- (+) Dead simple operationally: one binary, one command, works on any machine
  with any recent IDA install, no Python, no database.
- (+) The generated header is human-readable and diffable — a genuinely nice
  artifact in its own right (also usable as clang-cl layout-test input, see
  Verification).
- (−) **C only.** Per Hex-Rays' own docs: "TILIB support only C header files.
  C++ files (classes, templates, etc) are not supported." Irrelevant for us
  *because our JSON is already flattened C-shape* — but it means no
  `__cppobj`/vftable semantics, no C++ mangled symbol names, and enum classes
  degrade to plain enums.
- (−) Layout is decided by tilib's C parser from our padding fields — a second
  layout engine again. Any packing/`#pragma` mismatch produces silently wrong
  offsets. The explicit-offset JSON check (Verification) can't see inside this
  step; only `tilib -l` dumps can.
- (−) Another emitter to write and maintain (JSON → C), on top of the JSON
  emitter itself.

**Verdict:** viable fallback, and the JSON → C renderer is worth building
*anyway* for local clang-cl verification (it needs no IDA at all). But as a
`.til` producer it's strictly dominated by Route A: same input, less control.

### Route D (comparison only, NOT an implementation route): IDAClang direct

IDA 9.1+ ships `idaclang` in `tools/` — a command-line clang-based header→TIL
compiler that *does* handle C++: `idaclang -x c++ -target x86_64-pc-win32
foo.h` produces `foo.til` with mangled symbols and `/*VFT*/` vftable structs
(Hex-Rays IDAClang tutorial, cited above).

Tempting: point it at CommonLibSSE-NG directly. **Do not.** That path bypasses
all ~24 of our patches — template specialization inlining (patch 0003/0007),
redundant-vptr (0001), `std::` normalization (0005), EBO (0023), tail-padding
for runtime-relocated members (0019) — and there's no evidence idaclang would
even survive the MSVC STL + `ENABLE_SKYRIM_AE` macro setup without the stub
PCH we built. We would be starting the entire DESIGN.md investigation over
against a black-box frontend.

Where it *is* useful: as an **independent cross-check** on a handful of
already-correct classes. If idaclang's `TESForm` agrees with ours
field-for-field, that's a second compiler's opinion of the same headers for
free. Treat its output as a test oracle on a good day, never as ground truth
(it's clang, not MSVC — same caveat as our own clang-cl checks).

## Intermediate JSON format (the decoupling boundary)

One file per runtime, written by a new `--report-json <path>` flag on
`GenerateGdt`, dumped from the committed `FileDataTypeManager` **after** the
tail-padding pass (see inventory above). The JSON is the contract: the parse
side (Java, Ghidra, libclang — runs here) knows nothing about IDA; the emit
side (Python, `ida_typeinf` — needs IDA) knows nothing about C++.

Design rules:

- **Self-contained.** Every type the file references is either defined in the
  file or listed in `primitives`. No "look it up in IDA's stock TILs" —
  stock-TIL name resolution is version-dependent and unverifiable here.
- **Offsets in bytes, explicitly, per member.** The bits-vs-bytes conversion
  is the emitter's problem, in exactly one line of code.
- **Flattened.** Inheritance is already erased (bases are ordinary embedded
  fields); vtables are ordinary struct fields pointing at ordinary
  `<Class>_vtbl` struct types. The JSON describes C-shaped data only.
- **Provenance rides along** so a `.til` consumer (or a reviewer) can tell a
  static_assert-verified struct from a tail-padded heuristic one without
  leaving IDA.

### Schema

```json
{
  "format_version": 1,
  "generator": "GenerateGdt --report-json (type-importer)",
  "runtime": "ENABLE_SKYRIM_AE=1",
  "commonlib_commit": "<git sha of vendor/CommonLibSSE-NG>",
  "gdt_sha256": "<sha256 of the .gdt written in the same run>",
  "primitives": {
    "uint32_t": {"size": 4, "align": 4, "kind": "uint"},
    "uint64_t": {"size": 8, "align": 8, "kind": "uint"},
    "void*":    {"size": 8, "align": 8, "kind": "ptr"}
  },
  "types": [
    {
      "name": "TESForm",
      "kind": "struct",
      "size": 32,
      "align": 8,
      "provenance": {
        "baseline_status": "OK",
        "expected_size": 32,
        "tail_padded": false,
        "source_header": "RE/T/TESForm.h"
      },
      "members": [
        {"name": "vftable",    "offset": 0,  "type": {"kind": "ptr", "to": "TESForm_vtbl"}},
        {"name": "formID",     "offset": 8,  "type": {"kind": "ref", "name": "FormID"}},
        {"name": "inGameFormFlags", "offset": 12, "type": {"kind": "ref", "name": "std::enumeration<...>_flattened"}},
        {"name": "formFlags",  "offset": 16, "type": {"kind": "ref", "name": "uint32_t"}},
        {"name": "pad_1C",     "offset": 28, "type": {"kind": "array", "of": "uint8_t", "count": 4}, "synthetic_padding": true}
      ]
    },
    {
      "name": "TESForm_vtbl",
      "kind": "struct",
      "size": 296,
      "provenance": {"baseline_status": "NO_GROUND_TRUTH", "vtable_for": "TESForm"},
      "members": [
        {"name": "destructor", "offset": 0, "type": {"kind": "ptr", "to": "void"}, "comment": "virtual fn ptr; signature not recovered"}
      ]
    },
    {
      "name": "ExtraDataList",
      "kind": "struct",
      "size": 32,
      "provenance": {
        "baseline_status": "OK",
        "expected_size": null,
        "tail_padded": true,
        "tail_padding_note": "widened from 8 per tail_padding_hints.csv; heuristic lower bound, not asserted (DESIGN.md invisible-relocated-member pattern)"
      },
      "members": ["..."]
    },
    {
      "name": "FORM_ENUM_STRING",
      "kind": "enum",
      "size": 4,
      "underlying": "uint32_t",
      "members": [{"name": "kNone", "value": 0}]
    },
    {
      "name": "FormID",
      "kind": "typedef",
      "to": "uint32_t"
    }
  ],
  "unresolved": ["SomeTypeName", "..."]
}
```

Type references are exactly four shapes: `{"kind":"ref","name":N}`,
`{"kind":"ptr","to":N}`, `{"kind":"array","of":N,"count":C}`, and inline
primitive names from `primitives`. Union support (`"kind":"union"` with
members at overlapping offsets) is in the schema from day one even if v0.1's
emitter doesn't exercise it — GhidraClangPoweredParse handles unions and
dropping them from the JSON would silently lose them.

Explicitly NOT in the JSON: function prototypes (non-goal), Ghidra category
paths (Ghidra-ism; IDA TILs are flat by name), bitfield sub-offsets beyond
what Ghidra's component model already exposes (record `offset` in bytes plus
`bit_offset`/`bit_size` when nonzero — emitter may round to byte and warn,
since IDA UDT bitfields exist but are untestable here; flag as UNVERIFIED).

The member list above is illustrative, not a commitment about which padding
fields Ghidra materializes — the emitter dumps what the committed archive
actually contains, padding included, rather than re-deriving anything.

## Verification

### Without IDA (dev machine, now)

1. **JSON ≡ committed `.gdt`.** The `--report-json` emitter walks the same
   `FileDataTypeManager` the coverage CSV already walks
   (`GenerateGdt.java:184-189`). A checker script asserts: for every Composite
   in the archive, the JSON has a struct with identical name, `getLength()`,
   and per-component offset/name/size. This is a same-process, same-data
   round trip — if it fails, the emitter is buggy, full stop. No IDA
   involved, no IDA could help.
2. **JSON ≡ coverage baseline.** Project the JSON to `{name: size}` and run
   the existing `scripts/check_regression.py` semantics against
   `coverage_baseline.json`: every class that was `OK` must still be `OK` with
   the same size. Zero regressions tolerated — same gate the `.gdt` side uses.
3. **JSON → C header → clang-cl.** Build the Route C renderer (JSON → C with
   explicit padding fields) and compile it with the existing clang-cl + xwin
   setup, with `_Static_assert(sizeof(X) == N)` and
   `_Static_assert(offsetof(X, f) == O)` emitted for every type and member.
   This proves the JSON is *internally* layout-consistent under MSVC rules —
   i.e., that any correct C-shaped re-materialization of it (parse_decls,
   tilib, or a hand-written struct) will reproduce the offsets. It does NOT
   prove `tinfo_t.add_udm` does what we think; only IDA proves that.
4. **Schema validation.** A trivial JSON-Schema check in CI so a future
   pipeline change fails loudly instead of producing a subtly wrong `.til`
   months later.

After steps 1–3 pass, the JSON is as verified as the `.gdt` is. The residual
risk is entirely inside the ~200-line Python emitter: bits-vs-bytes, name
mangling of legal-IDA identifiers, `set_named_type` collision behavior. All
small, all enumerable, all caught by the first with-IDA run.

### With IDA (someone else's machine, in order)

1. **idalib smoke test.** Install the `idapro` wheel from
   `<IDA>/idalib/python/`, run `idapro.open_database()` on a dummy file (or
   determine no database is needed — open question above), call
   `new_til`/`store_til` on a 3-type hand-written JSON. Confirms the API
   surface matches the docs before 2,000+ types ride on it.
2. **Build the real `.til`** from the full JSON.
3. **`tilib -l` dump** (`tools/tilib` in 9.1+; portal download otherwise) and
   diff the reported struct sizes against `coverage_baseline.json`'s `actual`
   column. This is the first true end-to-end check and it needs no game
   binary.
4. **Load against the real binary.** Open the AE 1.6.1170 `SkyrimSE.exe`,
   `add_til()` the result, spot-check the known-landmark layouts from
   `DESIGN.md` (`TESObjectREFR` bases at 0x00/0x20/0x30/0x38, own members from
   0x40) and cross-check a few offsets against the Address Library, per
   `ADDRESS_LIBRARY_VALIDATION.md`'s existing methodology.
5. **Decompiler eyeball pass** on a few functions known to touch
   `TESObjectREFR` — the point of the whole exercise. If pseudocode field
   access looks sane, ship it.

## Work breakdown

**Now (no IDA required):**

- [ ] `GenerateGdt --report-json` emitter (walk committed
      `FileDataTypeManager` post-tail-padding; ~150 lines of Java beside
      `writeCoverageReport`).
- [ ] JSON schema file + validator script.
- [ ] JSON ≡ .gdt round-trip checker (Verification #1) and baseline projection
      check (Verification #2) — extend `check_regression.py` or a sibling.
- [ ] JSON → C header renderer + clang-cl static-assert harness
      (Verification #3). Doubles as Route C's front half.
- [ ] The Python `ida_typeinf` builder, written blind but structured for
      Routes A and B to share. Cannot even be import-checked here — treat as
      untested code with a deliberately tiny API surface, reviewed against the
      cited docs.
- [ ] Update the docs index (`README.md` / track docs) when the emitter
      lands — not in this doc's scope to write.

**Gated on IDA access (needs someone with a 9.x install):**

- [ ] idalib smoke test (with-IDA step 1) — resolves the database-required
      question and validates every API assumption in this doc.
- [ ] First real `.til` build + `tilib -l` diff against the baseline.
- [ ] In-IDA application + Address Library spot checks.
- [ ] (Optional) idaclang cross-check on ~10 known-good classes as a second
      opinion.
- [ ] (Optional, fallback only) finish Route C if Route A hits a wall.

## Licensing

Same rule as the `.gdt` (DESIGN.md): a `.til` generated from CommonLibSSE-NG
headers is treated as GPL-3.0 inherited from CommonLibSSE-NG, attributed to
the source commit hash (carried in the JSON as `commonlib_commit` so the
emitter can stamp it into the TIL description via `new_til(name, desc)`).
Tooling stays MIT. The intermediate JSON is derived data — same GPL-3.0
treatment as the archives.

## Unverified claims registry (everything here is cited doc, not tested)

1. `idapro` wheel location and `open_database` requirements (Hex-Rays docs +
   community READMEs; not run).
2. `add_udm` offset units are bits on IDA 9.x (porting guide + third-party
   notes; consistent across two independent sources, still not run).
3. `new_til`/`store_til` work with no IDB open / under idalib at all
   (documented for in-IDA use; idalib context not explicitly documented).
4. `tilib` ships in `tools/` for 9.1+ and handles our generated C (Hex-Rays
   docs; tilib has never executed on any machine we control).
5. `idaclang` C++ support and output shape (Hex-Rays tutorial; same caveat).
6. IDA 8.4's `ida_typeinf` UDT API is sufficient for Route B (porting guide
   implies it; not confirmed).

If with-IDA step 1 contradicts any of these, this doc gets a v0.2 corrections
section — same convention as DESIGN.md v0.1→v0.2.
