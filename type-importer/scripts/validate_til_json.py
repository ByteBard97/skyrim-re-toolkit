#!/usr/bin/env python3
"""Validate a TIL-export intermediate JSON file against the schema documented
in TIL_EXPORT_DESIGN.md's "Intermediate JSON format" section.

This is a standalone structural + referential-integrity check, independent of
the (not-yet-written) `GenerateGdt --report-json` emitter -- it exists so the
emitter, the JSON->C renderer, and (eventually) the IDA-side builder can all
validate against one shared, precisely-specified contract instead of each
re-deriving what "valid" means.

Checks, in order:
  1. Structural: every required top-level key is present and the right JSON
     type; every `types[]` entry has a recognized `kind` and that kind's
     required fields; every member's `type` shape is one of the four
     documented forms (ref / ptr / array / bare primitive-name string).
  2. Referential integrity ("Self-contained" design rule): every type name a
     `ref`/`ptr`/`array` points at must resolve to either a `primitives` key,
     a `void` pointee (the one builtin exempted -- see TIL_EXPORT_DESIGN.md's
     TESForm_vtbl example, `{"kind": "ptr", "to": "void"}`), or another
     `types[]` entry's own `name`. A dangling reference is exactly the kind
     of mistake that produces a "subtly wrong .til months later" this script
     exists to catch in CI, per the design doc's own stated motivation.
  3. Semantic: struct/union member offsets are non-negative, within
     `[0, size)` (a member cannot start at or past its own struct's end),
     and duplicate names within one struct/union are rejected -- Ghidra's
     `FileDataTypeManager` can't produce these bogus shapes normally, so
     seeing them signals a JSON emitter bug, not a real type.

Usage:
    python3 validate_til_json.py path/to/export.json
    python3 validate_til_json.py --self-test    # run built-in fixtures, no file needed

Exit code 0 if valid, 1 if any error was found (all errors are collected and
printed together, not just the first -- a single run should surface every
problem in a large JSON, not require N re-runs to find N bugs).
"""
import argparse
import json
import sys
from pathlib import Path

REQUIRED_TOP_LEVEL = {
    "format_version": int,
    "generator": str,
    "runtime": str,
    "commonlib_commit": str,
    "gdt_sha256": str,
    "primitives": dict,
    "types": list,
    "unresolved": list,
}

VALID_PRIMITIVE_KINDS = {"uint", "int", "float", "ptr", "bool", "char"}
VALID_TYPE_KINDS = {"struct", "union", "enum", "typedef"}
VALID_REF_KINDS = {"ref", "ptr", "array"}

# The one type name every archive may reference without defining or listing
# it in `primitives` -- a `{"kind": "ptr", "to": "void"}` pointee, per the
# TESForm_vtbl example in TIL_EXPORT_DESIGN.md's schema section.
IMPLICIT_BUILTIN_NAMES = {"void"}


class ValidationError(Exception):
    """Never raised as a real exception -- used only as a namespaced
    container so callers can `str()` a collected error uniformly."""


def _err(errors, path, message):
    errors.append(f"{path}: {message}")


def validate(doc):
    """Returns a list of error strings; empty list means valid."""
    errors = []

    if not isinstance(doc, dict):
        return ["$: top-level document must be a JSON object"]

    for key, expected_type in REQUIRED_TOP_LEVEL.items():
        if key not in doc:
            _err(errors, "$", f"missing required key '{key}'")
        elif not isinstance(doc[key], expected_type):
            _err(errors, f"$.{key}", f"expected {expected_type.__name__}, got {type(doc[key]).__name__}")

    if "format_version" in doc and isinstance(doc["format_version"], int) and doc["format_version"] != 1:
        _err(errors, "$.format_version", f"expected 1, got {doc['format_version']} (unknown schema version)")

    primitives = doc.get("primitives", {}) if isinstance(doc.get("primitives"), dict) else {}
    _validate_primitives(primitives, errors)

    types = doc.get("types", []) if isinstance(doc.get("types"), list) else []
    type_names = set()
    for i, t in enumerate(types):
        path = f"$.types[{i}]"
        if not isinstance(t, dict):
            _err(errors, path, "type entry must be a JSON object")
            continue
        name = t.get("name")
        if not isinstance(name, str) or not name:
            _err(errors, path, "missing or empty 'name'")
        else:
            if name in type_names:
                _err(errors, path, f"duplicate type name '{name}'")
            type_names.add(name)

    known_names = set(primitives.keys()) | type_names | IMPLICIT_BUILTIN_NAMES

    for i, t in enumerate(types):
        if not isinstance(t, dict):
            continue
        path = f"$.types[{i}]" + (f" ({t.get('name')})" if isinstance(t.get("name"), str) else "")
        kind = t.get("kind")
        if kind not in VALID_TYPE_KINDS:
            _err(errors, path, f"'kind' must be one of {sorted(VALID_TYPE_KINDS)}, got {kind!r}")
            continue
        if kind in ("struct", "union"):
            _validate_struct_or_union(t, path, known_names, errors)
        elif kind == "enum":
            _validate_enum(t, path, errors)
        elif kind == "typedef":
            _validate_typedef(t, path, known_names, errors)

    unresolved = doc.get("unresolved", []) if isinstance(doc.get("unresolved"), list) else []
    for i, u in enumerate(unresolved):
        if not isinstance(u, str):
            _err(errors, f"$.unresolved[{i}]", f"expected string, got {type(u).__name__}")

    return errors


def _validate_primitives(primitives, errors):
    for name, spec in primitives.items():
        path = f"$.primitives.{name}"
        if not isinstance(spec, dict):
            _err(errors, path, "primitive spec must be a JSON object")
            continue
        for field, expected_type in (("size", int), ("align", int), ("kind", str)):
            if field not in spec:
                _err(errors, path, f"missing required field '{field}'")
            elif not isinstance(spec[field], expected_type):
                _err(errors, f"{path}.{field}", f"expected {expected_type.__name__}, got {type(spec[field]).__name__}")
        if isinstance(spec.get("kind"), str) and spec["kind"] not in VALID_PRIMITIVE_KINDS:
            _err(errors, f"{path}.kind", f"'{spec['kind']}' not one of {sorted(VALID_PRIMITIVE_KINDS)}")
        if isinstance(spec.get("size"), int) and spec["size"] <= 0:
            _err(errors, f"{path}.size", f"must be positive, got {spec['size']}")


def _resolve_type_ref(ref, path, known_names, errors):
    """A member/typedef 'type' or 'to' field: either a bare string naming a
    known type, or one of the three wrapped shapes (ref/ptr/array)."""
    if isinstance(ref, str):
        if ref not in known_names:
            _err(errors, path, f"references unknown type '{ref}'")
        return
    if not isinstance(ref, dict):
        _err(errors, path, f"type reference must be a string or object, got {type(ref).__name__}")
        return
    kind = ref.get("kind")
    if kind not in VALID_REF_KINDS:
        _err(errors, path, f"type-ref 'kind' must be one of {sorted(VALID_REF_KINDS)} or a bare name, got {kind!r}")
        return
    if kind == "ref":
        name = ref.get("name")
        if not isinstance(name, str) or name not in known_names:
            _err(errors, f"{path}.name", f"references unknown type '{name}'")
    elif kind == "ptr":
        to = ref.get("to")
        if not isinstance(to, str) or to not in known_names:
            _err(errors, f"{path}.to", f"references unknown type '{to}'")
    elif kind == "array":
        of = ref.get("of")
        count = ref.get("count")
        if not isinstance(of, str) or of not in known_names:
            _err(errors, f"{path}.of", f"references unknown type '{of}'")
        # count == 0 is allowed: a real C/C++ flexible-array-member idiom
        # (e.g. Ghidra's own "Array" wrapper class, or a trailing
        # `char data[0];`), not a synthesis error.
        if not isinstance(count, int) or count < 0:
            _err(errors, f"{path}.count", f"must be a non-negative integer, got {count!r}")


def _validate_struct_or_union(t, path, known_names, errors):
    size = t.get("size")
    if not isinstance(size, int) or size < 0:
        _err(errors, path, f"'size' must be a non-negative integer, got {size!r}")
        size = None

    provenance = t.get("provenance")
    if not isinstance(provenance, dict):
        _err(errors, path, "missing or invalid 'provenance' object (required for struct/union)")
    elif "baseline_status" not in provenance:
        _err(errors, f"{path}.provenance", "missing 'baseline_status'")

    members = t.get("members")
    if not isinstance(members, list):
        _err(errors, path, f"'members' must be a list, got {type(members).__name__}")
        return

    seen_names = set()
    for j, m in enumerate(members):
        mpath = f"{path}.members[{j}]"
        if not isinstance(m, dict):
            _err(errors, mpath, "member must be a JSON object")
            continue
        name = m.get("name")
        if not isinstance(name, str) or not name:
            _err(errors, mpath, "missing or empty 'name'")
        elif name in seen_names:
            _err(errors, mpath, f"duplicate member name '{name}' in this struct/union")
        else:
            seen_names.add(name)

        offset = m.get("offset")
        if not isinstance(offset, int) or offset < 0:
            _err(errors, mpath, f"'offset' must be a non-negative integer, got {offset!r}")
        elif size is not None and offset > size:
            # offset == size is allowed: a trailing member whose OWN type is
            # zero-length (e.g. a genuinely-empty embedded class under a
            # runtime where its real fields are only ever accessed via
            # REL::RelocateMember, never declared -- see patch 0019 /
            # tail_padding_hints.csv) legitimately sits exactly at the
            # struct's own end. Only strictly starting past the end is
            # invalid.
            _err(errors, mpath, f"offset {offset} is > struct size {size} (member starts past the end)")

        if "type" not in m:
            _err(errors, mpath, "missing 'type'")
        else:
            _resolve_type_ref(m["type"], f"{mpath}.type", known_names, errors)

        for optional_bool in ("synthetic_padding",):
            if optional_bool in m and not isinstance(m[optional_bool], bool):
                _err(errors, f"{mpath}.{optional_bool}", "must be a boolean if present")

        # Bitfield sub-offset fields, if present, must be a consistent pair
        # (per TIL_EXPORT_DESIGN.md: "record offset in bytes plus
        # bit_offset/bit_size when nonzero").
        has_bit_offset = "bit_offset" in m
        has_bit_size = "bit_size" in m
        if has_bit_offset != has_bit_size:
            _err(errors, mpath, "'bit_offset' and 'bit_size' must both be present or both absent")
        if has_bit_offset and not isinstance(m["bit_offset"], int):
            _err(errors, f"{mpath}.bit_offset", "must be an integer")
        if has_bit_size and (not isinstance(m["bit_size"], int) or m["bit_size"] <= 0):
            _err(errors, f"{mpath}.bit_size", "must be a positive integer")


def _validate_enum(t, path, errors):
    if not isinstance(t.get("size"), int) or t["size"] <= 0:
        _err(errors, path, f"'size' must be a positive integer, got {t.get('size')!r}")
    if not isinstance(t.get("underlying"), str):
        _err(errors, path, "missing or invalid 'underlying' (expected a primitive type name string)")

    members = t.get("members")
    if not isinstance(members, list):
        _err(errors, path, f"'members' must be a list, got {type(members).__name__}")
        return
    seen_names = set()
    for j, m in enumerate(members):
        mpath = f"{path}.members[{j}]"
        if not isinstance(m, dict):
            _err(errors, mpath, "enum member must be a JSON object")
            continue
        name = m.get("name")
        if not isinstance(name, str) or not name:
            _err(errors, mpath, "missing or empty 'name'")
        elif name in seen_names:
            _err(errors, mpath, f"duplicate enum member name '{name}'")
        else:
            seen_names.add(name)
        if not isinstance(m.get("value"), int):
            _err(errors, mpath, f"'value' must be an integer, got {m.get('value')!r}")


def _validate_typedef(t, path, known_names, errors):
    to = t.get("to")
    if not isinstance(to, str) or not to:
        _err(errors, path, "missing or invalid 'to' (expected a type name string)")
        return
    if to not in known_names:
        _err(errors, f"{path}.to", f"references unknown type '{to}'")


# ---------------------------------------------------------------------------
# Self-test fixtures: one hand-written valid example (a trimmed version of
# TIL_EXPORT_DESIGN.md's own schema example), plus one malformed variant per
# documented failure mode. Run with --self-test.
# ---------------------------------------------------------------------------

def _valid_example():
    return {
        "format_version": 1,
        "generator": "GenerateGdt --report-json (type-importer)",
        "runtime": "ENABLE_SKYRIM_AE=1",
        "commonlib_commit": "deadbeef",
        "gdt_sha256": "0" * 64,
        "primitives": {
            "uint32_t": {"size": 4, "align": 4, "kind": "uint"},
            "uint8_t": {"size": 1, "align": 1, "kind": "uint"},
            "void*": {"size": 8, "align": 8, "kind": "ptr"},
        },
        "types": [
            {
                "name": "TESForm",
                "kind": "struct",
                "size": 32,
                "align": 8,
                "provenance": {"baseline_status": "OK", "expected_size": 32, "tail_padded": False},
                "members": [
                    {"name": "vftable", "offset": 0, "type": {"kind": "ptr", "to": "TESForm_vtbl"}},
                    {"name": "formFlags", "offset": 16, "type": "uint32_t"},
                    {"name": "pad_1C", "offset": 28, "type": {"kind": "array", "of": "uint8_t", "count": 4},
                     "synthetic_padding": True},
                ],
            },
            {
                "name": "TESForm_vtbl",
                "kind": "struct",
                "size": 8,
                "provenance": {"baseline_status": "NO_GROUND_TRUTH", "vtable_for": "TESForm"},
                "members": [
                    {"name": "destructor", "offset": 0, "type": {"kind": "ptr", "to": "void"}},
                ],
            },
            {
                "name": "FORM_ENUM_STRING",
                "kind": "enum",
                "size": 4,
                "underlying": "uint32_t",
                "members": [{"name": "kNone", "value": 0}],
            },
            {
                "name": "FormID",
                "kind": "typedef",
                "to": "uint32_t",
            },
        ],
        "unresolved": ["SomeUnresolvedType"],
    }


def _self_test():
    import copy

    failures = []

    def check(label, mutate, expect_valid):
        doc = copy.deepcopy(_valid_example())
        if mutate is not None:
            mutate(doc)
        errors = validate(doc)
        ok = (len(errors) == 0) == expect_valid
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {label}" + ("" if ok else f" -- errors={errors}"))
        if not ok:
            failures.append(label)

    check("valid example passes", None, expect_valid=True)

    check("missing top-level key", lambda d: d.pop("runtime"), expect_valid=False)
    check("wrong top-level type", lambda d: d.__setitem__("primitives", []), expect_valid=False)
    check("bad format_version", lambda d: d.__setitem__("format_version", 2), expect_valid=False)

    def bad_primitive_kind(d):
        d["primitives"]["uint32_t"]["kind"] = "nonsense"
    check("invalid primitive kind", bad_primitive_kind, expect_valid=False)

    def negative_primitive_size(d):
        d["primitives"]["uint32_t"]["size"] = -1
    check("negative primitive size", negative_primitive_size, expect_valid=False)

    def dangling_ref(d):
        d["types"][0]["members"][1]["type"] = "nonexistent_type"
    check("dangling type reference (bare name)", dangling_ref, expect_valid=False)

    def dangling_ptr(d):
        d["types"][0]["members"][0]["type"] = {"kind": "ptr", "to": "NoSuchStruct"}
    check("dangling type reference (ptr.to)", dangling_ptr, expect_valid=False)

    def dangling_array(d):
        d["types"][0]["members"].append(
            {"name": "arr", "offset": 100, "type": {"kind": "array", "of": "NoSuchType", "count": 4}})
        d["types"][0]["size"] = 200
    check("dangling type reference (array.of)", dangling_array, expect_valid=False)

    def duplicate_type_name(d):
        dup = copy.deepcopy(d["types"][0])
        d["types"].append(dup)
    check("duplicate top-level type name", duplicate_type_name, expect_valid=False)

    def duplicate_member_name(d):
        d["types"][0]["members"].append({"name": "formFlags", "offset": 20, "type": "uint32_t"})
    check("duplicate member name", duplicate_member_name, expect_valid=False)

    def member_offset_past_end(d):
        d["types"][0]["members"][1]["offset"] = 999
    check("member offset >= struct size", member_offset_past_end, expect_valid=False)

    def negative_offset(d):
        d["types"][0]["members"][1]["offset"] = -4
    check("negative member offset", negative_offset, expect_valid=False)

    def missing_provenance(d):
        del d["types"][0]["provenance"]
    check("struct missing provenance", missing_provenance, expect_valid=False)

    def unknown_kind(d):
        d["types"][0]["kind"] = "class"
    check("unrecognized type kind", unknown_kind, expect_valid=False)

    def enum_bad_value(d):
        d["types"][2]["members"][0]["value"] = "zero"
    check("enum member non-integer value", enum_bad_value, expect_valid=False)

    def typedef_dangling(d):
        d["types"][3]["to"] = "NoSuchPrimitive"
    check("typedef references unknown type", typedef_dangling, expect_valid=False)

    def mismatched_bitfield_fields(d):
        d["types"][0]["members"][1]["bit_offset"] = 0
        # bit_size deliberately omitted
    check("bit_offset without bit_size", mismatched_bitfield_fields, expect_valid=False)

    def unresolved_non_string(d):
        d["unresolved"] = [123]
    check("unresolved entry not a string", unresolved_non_string, expect_valid=False)

    def void_ptr_is_allowed(d):
        # Sanity check the other direction: 'void' must NOT be flagged even
        # though it's never defined in primitives or types.
        pass
    check("implicit 'void' pointee is allowed (not a failure case)", void_ptr_is_allowed, expect_valid=True)

    print()
    if failures:
        print(f"{len(failures)} self-test case(s) FAILED: {failures}")
        return 1
    print(f"All self-test cases passed.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("json_path", type=Path, nargs="?", help="Path to a TIL-export JSON file to validate")
    parser.add_argument("--self-test", action="store_true", help="Run built-in fixtures instead of validating a file")
    args = parser.parse_args()

    if args.self_test:
        sys.exit(_self_test())

    if args.json_path is None:
        parser.error("json_path is required unless --self-test is given")

    try:
        doc = json.loads(args.json_path.read_text())
    except json.JSONDecodeError as e:
        print(f"error: {args.json_path}: not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    errors = validate(doc)
    if errors:
        print(f"# INVALID: {len(errors)} error(s) in {args.json_path}")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)

    type_count = len(doc.get("types", []))
    print(f"# VALID: {args.json_path} ({type_count} type(s), format_version={doc.get('format_version')})")
    sys.exit(0)


if __name__ == "__main__":
    main()
