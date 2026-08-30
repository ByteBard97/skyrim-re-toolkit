# Function Signature / Symbol Application -- Problem Statement

Status: problem definition. The approach is now designed and externally
validated -- see `FUNCTION_SIGNATURE_DESIGN.md` for the actual plan.

## What we have today

The `type-importer` pipeline parses CommonLibSSE-NG headers and emits a
Ghidra `.gdt` archive containing **types only**: structs, classes, enums,
unions, with byte-accurate field offsets and sizes, vtable layout structs for
multi-inheritance hierarchies. This is verified three independent ways
(`static_assert`s, hand-derived offset math, real `clang-cl` compilation) and
is genuinely solid -- see `DESIGN.md`.

## What's still missing

Loading the `.gdt` into Ghidra and running **Apply Function Data Types**
against a real `SkyrimSE.exe` does not, by itself, retype any function in the
binary. The reason: Ghidra can only apply a type to a function it has already
identified *and* correctly matched to a C++ class + method. Two things this
project's pipeline does not currently produce:

1. **Address -> function identity.** Nothing in the current pipeline says
   "the function at RVA `0x1e1270` is `TESObjectREFR::Something(...)`."
   Ghidra's own RTTI-based class recovery can sometimes infer this from
   vtables it finds walking the binary, but that's opportunistic and
   incomplete, not something this project produces or verifies.
2. **Function prototypes.** Even where Ghidra correctly identifies "this is
   a method of class X," it doesn't know the parameter types, return type, or
   argument count unless something tells it -- which is exactly the
   information CommonLibSSE-NG's header declarations already carry (the
   parser already reads these headers for struct/class members; it doesn't
   currently extract function signatures from them).

Net effect: after following this project's own Quick Start exactly as
written, `SkyrimSE.exe` in Ghidra still shows
`FUN_1401e1270(longlong *param_1, undefined8 param_2)` for most functions --
same as before the `.gdt` import, just with better struct field names when a
function happens to dereference a known type. This gap was flagged directly
by a hostile review of the demo: *"Apply Function Data
Types on a stripped exe does nothing without symbols, did you even try
this?"* -- and the response chosen at the time was to add a `demo/`
walkthrough clarifying what actually changes on screen, not to close the gap.

## Why this project doesn't have it yet

Not a hard technical blocker. Three earlier project documents declared this
"out of scope" and treated that as settled project policy, which it was not
(the project author never declared it out of scope; that label came from
earlier review tooling, not from them):

- `TIL_EXPORT_DESIGN.md`: called it "`symbol-archive`'s problem" --
  `symbol-archive` never built it either; the work was punted between
  subprojects and landed nowhere.
- `README.md`: called RTTI-based class recovery "out of scope here."
- An internal track-planning doc called Address Library *RVA-level*
  cross-checks "out of scope per this project's ground rules (no acquiring
  Bethesda binaries)" -- but the project already validates generated `.gdt`s
  against a real `SkyrimSE.exe` locally elsewhere (this is exactly how the
  SkyObject/TypeDef bug and the demo screenshots got verified), so the
  binaries-acquisition rule doesn't actually forbid this the way it was
  cited to.

## The technical problem, stated plainly

Given:
- CommonLibSSE-NG headers (already parsed by `type-importer` for types,
  not yet mined for function declarations/signatures tied to `REL::ID`)
- meh321's public Address Library DB (already used for ID-level
  cross-checks, not yet used to resolve those IDs to real RVAs for symbol
  placement)
- A real, user-supplied `SkyrimSE.exe`/`Fallout4.exe` (not acquired or
  redistributed by this project -- supplied locally by whoever runs the
  tool, same posture as the BethesdaGhidraScripts pipeline and this
  project's own local PE-validation work)

Produce: a Ghidra headless-import step (or `.gdt`-adjacent artifact) that
creates named, correctly-typed `Function` objects at the right addresses in
the user's own binary -- not just types sitting unused in the Data Type
Manager.


