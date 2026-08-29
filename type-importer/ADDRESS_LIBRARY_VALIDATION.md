# Address Library ID cross-check

The one piece of "v0.2 -- other runtimes" not covered by the layout-only
sweeps in `RUNTIME_SE_1_5_97.md`/`RUNTIME_VR_1_4_15.md`: confirming
CommonLibSSE-NG's declared `REL::VariantID(se_id, ae_id, vr_offset)`
entries are real, resolvable entries in an actual community Address
Library database, not typos or stale placeholders.

## What this checks (and what it doesn't)

`REL::VariantID`'s `se_id`/`ae_id` fields are meh321 Address Library ID
numbers, looked up against a real per-version `.bin` database **at
runtime**, to resolve an actual RVA in a live process -- this is
completely separate machinery from `type-importer`'s own struct-layout
output (`sizeof`/field-offset correctness, what the coverage sweeps
check). This cross-check validates that CommonLibSSE-NG's own hardcoded
ID numbers are genuine and exist in a real database; it says nothing
about the `.gdt`/struct-layout work and doesn't touch it.

## Method

`scripts/check_address_library_ids.py` is a from-scratch Python port of
the real Address Library binary format, written directly from
CommonLibSSE-NG's own `REL/ID.h` (`header_t::read`,
`IDDatabase::unpack_file`) -- same header + delta-encoded `(type_byte,
id, offset)` record format, no external dependencies. Verified against
two real fixture files already vendored in the submodule for its own
unit tests (`vendor/CommonLibSSE-NG/tests/REL/`):

- `version-1-5-97-0.bin` -- real SE 1.5.97 Address Library, format 1
  (778,674 entries)
- `versionlib-1-6-353-0.bin` -- real AE 1.6.353 Address Library, format 2
  (415,925 entries)

Mined every `REL::VariantID(...)` call across all of
`vendor/CommonLibSSE-NG/include` (8,814 call sites; `0` is
CommonLibSSE-NG's own "not applicable to this runtime" sentinel,
excluded from the check) and checked each unique `se_id`/`ae_id` for
existence in the corresponding real database.

## Result

| Column | Unique IDs checked | Found in real DB | Missing |
|---|---|---|---|
| `se_id` (vs. real SE 1.5.97) | 8,379 | 8,379 (100.00%) | 0 |
| `ae_id` (vs. real AE 1.6.353) | 8,702 | 8,702 (100.00%) | 0 |

Every single non-sentinel ID CommonLibSSE-NG declares resolves to a real
entry in the corresponding real Address Library database. No typos, no
stale/placeholder IDs found.

## Caveats

- The AE fixture is 1.6.353, not 1.6.1170/1.7.99 (no 1.6.1170/1.7.99
  `.bin` fixture is vendored in this repo). Per meh321's own ID
  numbering scheme, IDs are stable across AE point releases (only the
  RVA each ID maps to changes between builds) -- an ID existing in the
  1.6.353 database is strong evidence it's a real, valid ID for AE in
  general, but this doesn't confirm the *offset* is correct for
  1.6.1170/1.7.99 specifically, since offsets do shift between AE
  point releases with recompiles.
- This checks ID *existence*, not that the resulting RVA points at the
  intended symbol (that would need a real disassembled binary and
  RTTI/signature matching to confirm -- out of scope here, and outside
  what this repo's ground rules permit acquiring).
- VR uses direct offsets (`vr_offset`), not an ID lookup -- nothing to
  cross-check there against an ID database (see `REL::VariantID`'s own
  runtime dispatch in `REL/ID.h`: `Runtime::VR` returns `_vrOffset`
  directly, no `IDDatabase` lookup).
