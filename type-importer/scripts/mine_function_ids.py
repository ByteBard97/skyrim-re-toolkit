#!/usr/bin/env python3
"""Mine function/data identities and their Address Library IDs from
CommonLibSSE-NG headers, resolve IDs to RVAs against a user-supplied meh321
Address Library .bin, and emit symbols.json for ApplySymbols.java.

This closes the "address -> function identity" gap described in
FUNCTION_SIGNATURE_PROBLEM.md: the .gdt already carries function signatures
(FunctionDefinitionDataTypes); this script says WHERE those functions live in
a specific game binary.

Patterns handled (all observed in vendor/CommonLibSSE-NG/include):
  1. Inline method bodies:
       bool Foo() { using func_t=...; REL::Relocation<func_t> func{ RELOCATION_ID(se, ae) }; ... }
     -> the enclosing Class::Method is a function at ID (se, ae).
  2. Class/namespace-scope statics:
       REL::Relocation<T**> singleton{ RELOCATION_ID(se, ae) };
     -> data label Class::singleton.
  3. RE/Offsets.h:  namespace RE::Offset::Actor { constexpr auto AddSpell = RELOCATION_ID(...); }
     -> function Actor::AddSpell (namespace path minus leading RE::Offset::).
  4. RE/Offsets_{RTTI,VTABLE,NiRTTI}.h:
       constexpr REL::VariantID RTTI_X(se, ae, vr) / VTABLE_X(...) / NiRTTI_X(...)
     -> data labels RTTI_X / VTABLE_X / NiRTTI_X.
  5. REL::ID(x) single-id form -> same id for both columns.

RELOCATION_ID(se, ae) expands to REL::RelocationID(se, ae) (PCH.h:724); both
take (se_id, ae_id). REL::VariantID(se, ae, vr) additionally carries a direct
VR offset (hex), NOT an ID.

Usage:
    python3 mine_function_ids.py <CommonLibSSE-NG>/include \
        --addrlib versionlib-1-6-1170-0.bin --format 2 --column ae \
        -o symbols.json

Independent implementation for the MIT skyrim-re-toolkit, informed by a
local reference run of the BethesdaGhidraScripts pipeline (alandtse fork,
commit 702c932); no code copied from it.
"""
import argparse
import glob
import json
import re
from pathlib import Path

from check_address_library_ids import parse_address_library

# ---------------------------------------------------------------------------
# ID-bearing constructs
# ---------------------------------------------------------------------------

# RELOCATION_ID(43956, 45348) / REL::RelocationID(...)  -> (se, ae), vr = 0
RELOC_ID_RE = re.compile(
    r'(?:RELOCATION_ID|REL::RelocationID)\(\s*(\d+)\s*,\s*(\d+)\s*\)')
# REL::VariantID(514633, 400793, 0x2f8a838) -> (se, ae, vr_offset)
VARIANT_ID_RE = re.compile(
    r'REL::VariantID\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(0[xX][0-9a-fA-F]+|\d+)\s*\)')
# REL::ID(12345) -> same id both columns
SINGLE_ID_RE = re.compile(r'REL::ID\(\s*(\d+)\s*\)')
# Declaration forms (Offsets_RTTI/VTABLE/NiRTTI.h):
#   constexpr REL::VariantID RTTI_X(se, ae, vr);  /  constexpr REL::ID X(id);
DECL_VARIANT_RE = re.compile(
    r'constexpr\s+REL::VariantID\s+(\w+)\(\s*(\d+)\s*,\s*(\d+)\s*,\s*'
    r'(0[xX][0-9a-fA-F]+|\d+)\s*\)')
DECL_ID_RE = re.compile(r'constexpr\s+REL::ID\s+(\w+)\(\s*(\d+)\s*\)')
# constexpr std::array<REL::VariantID, N> VTABLE_X{ REL::VariantID(...), ... }
# (multi-element = primary + secondary vtables; first element names the label)
ARRAY_VARIANT_RE = re.compile(
    r'constexpr\s+std::array\s*<\s*REL::VariantID\s*,\s*\d+\s*>\s+(\w+)\s*\{\s*$')

# constexpr auto X = ... / constexpr REL::VariantID X{...}
CONSTEXPR_NAME_RE = re.compile(
    r'constexpr\s+(?:auto|REL::\w+)\s+(\w+)\s*[={]\s*$')
# constexpr REL::VariantID X(  -- constructor-style, no '='
CONSTEXPR_CTOR_RE = re.compile(
    r'constexpr\s+(?:auto|REL::\w+)\s+(\w+)\s*$')
# REL::Relocation<tmpl> name{ ...  (name may be "func" inside a method body)
RELOCATION_VAR_RE = re.compile(
    r'REL::Relocation\s*<([^;{}]*)>\s*(\w+)\s*\{\s*$')

NAMESPACE_OPEN_RE = re.compile(r'namespace\s+([\w:]+)\s*$')
CLASS_OPEN_RE = re.compile(r'\b(?:class|struct)\s+(\w+)(?:\s+final)?\s*(?::[^{}]*)?$')
METHOD_DECL_RE = re.compile(
    r'((?:\w+::)*~?\w+)\s*\([^;{}]*\)\s*'
    r'(?:const)?\s*(?:noexcept)?\s*(?:override)?\s*(?:final)?\s*$',
    re.S)

CONTROL_KEYWORDS = {'if', 'for', 'while', 'switch', 'catch'}
LABEL_PREFIXES = ('RTTI_', 'VTABLE_', 'NiRTTI_')


def _is_func_type(tmpl: str) -> bool:
    """Does a REL::Relocation<tmpl> instantiation hold a function pointer?
    func_t / decltype(&Class::Method) / raw 'ret (*)(args)' -> function;
    T** / T* (singletons and other data) -> data label."""
    return ('func_t' in tmpl or '(*' in tmpl or 'decltype(&' in tmpl
            or 'decltype (&' in tmpl)


def strip_comments_and_strings(text: str) -> str:
    """Remove // and /* */ comments and string/char literal contents,
    preserving newlines."""
    def repl(m):
        s = m.group(0)
        return '\n' * s.count('\n') if s.startswith(('//', '/*')) else '""'
    return re.sub(
        r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
        repl, text, flags=re.S)


def scan_file(path: Path, rel_src: str):
    raw = path.read_text(encoding='utf-8', errors='replace')
    text = strip_comments_and_strings(raw)

    stack = []   # (kind, name): kind in ns / class / method / block
    pending = []
    symbols = []
    i, n = 0, len(text)

    def qualified(extra=None):
        parts = [nm for k, nm in stack if k in ('ns', 'class') and nm]
        if extra:
            parts.append(extra)
        return '::'.join(parts)

    def enclosing_method():
        for k, nm in reversed(stack):
            if k == 'method':
                if '::' in nm:  # out-of-line definition: void Actor::Foo(...)
                    return nm
                cls = '::'.join(x for k2, x in stack if k2 == 'class')
                return f'{cls}::{nm}' if cls else nm
        return None

    def add_symbol(name, se, ae, vr, force_kind=None):
        if not name:
            return
        if name.startswith(LABEL_PREFIXES):
            kind = 'label'
        elif force_kind:
            kind = force_kind
        elif 'RE::Offset::' in name or enclosing_method():
            kind = 'func'
        else:
            kind = 'label'
        symbols.append(dict(name=name, kind=kind, se_id=se, ae_id=ae,
                            vr_offset=vr, src=rel_src))

    while i < n:
        c = text[i]

        if c == '{':
            chunk = ''.join(pending).strip()
            pending = []
            m = NAMESPACE_OPEN_RE.search(chunk)
            if m:
                stack.append(('ns', m.group(1)))
                i += 1
                continue
            m = CLASS_OPEN_RE.search(chunk)
            if m:
                stack.append(('class', m.group(1)))
                i += 1
                continue
            m = METHOD_DECL_RE.search(chunk)
            if m and m.group(1) not in CONTROL_KEYWORDS and '(' in chunk:
                stack.append(('method', m.group(1)))
            else:
                stack.append(('block', None))
            i += 1
            continue

        if c == '}':
            pending = []
            if stack:
                stack.pop()
            i += 1
            continue

        if c == ';':
            pending = []
            i += 1
            continue

        m = (RELOC_ID_RE.match(text, i)
             or VARIANT_ID_RE.match(text, i)
             or SINGLE_ID_RE.match(text, i)
             or DECL_VARIANT_RE.match(text, i)
             or DECL_ID_RE.match(text, i))
        if m:
            if m.re is SINGLE_ID_RE:
                se = ae = int(m.group(1))
                vr = 0
                decl_name = None
            elif m.re is VARIANT_ID_RE:
                se, ae, vr = int(m.group(1)), int(m.group(2)), int(m.group(3), 0)
                decl_name = None
            elif m.re is DECL_VARIANT_RE:
                decl_name = m.group(1)
                se, ae, vr = int(m.group(2)), int(m.group(3)), int(m.group(4), 0)
            elif m.re is DECL_ID_RE:
                decl_name = m.group(1)
                se = ae = int(m.group(2))
                vr = 0
            else:
                se, ae, vr = int(m.group(1)), int(m.group(2)), 0
                decl_name = None

            if decl_name:
                add_symbol(qualified(decl_name), se, ae, vr)
                i = m.end()
                pending = []
                continue
            line_start = text.rfind('\n', 0, i) + 1
            # declarations often span lines (`...{ \n RELOCATION_ID(...)`),
            # so look back beyond the current line
            prefix = text[max(0, line_start - 200):i]
            decl = None
            reloc_tmpl = None
            dm = CONSTEXPR_NAME_RE.search(prefix + ' ') or \
                CONSTEXPR_NAME_RE.search(prefix + '=') or \
                CONSTEXPR_CTOR_RE.search(prefix) or \
                ARRAY_VARIANT_RE.search(prefix)
            if dm:
                decl = dm.group(1)
            else:
                rm = RELOCATION_VAR_RE.search(prefix)
                if rm:
                    reloc_tmpl, decl = rm.group(1), rm.group(2)

            meth = enclosing_method()
            if reloc_tmpl is not None and not _is_func_type(reloc_tmpl):
                # REL::Relocation<T**> singleton{...}: the ID is a DATA
                # address (the singleton pointer), even when written inside
                # an inline GetSingleton() thunk. Name the variable.
                add_symbol(qualified(decl), se, ae, vr, force_kind='label')
            elif meth:
                # ID inside a function body with a function-pointer
                # relocation type belongs to that function, regardless of
                # any local `func` variable name.
                add_symbol(meth, se, ae, vr, force_kind='func')
            elif decl and decl != 'func':
                kind = 'func' if reloc_tmpl is not None else None
                add_symbol(qualified(decl), se, ae, vr, force_kind=kind)
            # else: class/namespace-scope `func` var with no derivable name
            i = m.end()
            pending = []
            continue

        pending.append(c)
        i += 1

    return symbols


def normalize_name(name: str) -> str:
    """RE::Offset::Actor::AddSpell -> Actor::AddSpell ; strip leading RE::."""
    for prefix in ('RE::Offset::', 'RE::'):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('include_dir', type=Path, nargs='+',
                    help='one or more roots to scan (e.g. include/ and src/)')
    ap.add_argument('--addrlib', type=Path, help='meh321 .bin for the target exe version')
    ap.add_argument('--format', type=int, choices=[1, 2],
                    help='1 = version.bin (SE/VR), 2 = versionlib.bin (AE)')
    ap.add_argument('--column', choices=['se', 'ae'], default='ae')
    ap.add_argument('-o', '--out', type=Path, default=Path('symbols.json'))
    args = ap.parse_args()

    if args.addrlib and args.format is None:
        ap.error('--addrlib requires --format')

    id_to_rva = {}
    if args.addrlib:
        id_to_rva = parse_address_library(args.addrlib, args.format)

    symbols = {}
    files = []
    for root in args.include_dir:
        files.extend((root, Path(f))
                     for f in sorted(glob.glob(str(root / '**' / '*.h'), recursive=True)
                                     + glob.glob(str(root / '**' / '*.cpp'), recursive=True)))
    for root, path in files:
        rel = str(path.relative_to(root))
        for sym in scan_file(path, rel):
            sym['name'] = normalize_name(sym['name'])
            if not sym['name'] or sym['name'].endswith('::'):
                continue
            key = (sym['name'], sym['kind'])
            symbols.setdefault(key, sym)  # first hit wins; deterministic order

    out = []
    unresolved = 0
    for sym in symbols.values():
        entry = {'n': sym['name'], 't': sym['kind'], 'src': sym['src']}
        id_ = sym['se_id'] if args.column == 'se' else sym['ae_id']
        entry['id'] = id_
        if id_to_rva:
            if id_ and id_ in id_to_rva:
                entry['rva'] = id_to_rva[id_]
            else:
                unresolved += 1
                continue  # no address for this target -> not placeable
        out.append(entry)

    out.sort(key=lambda e: e['n'])
    doc = {'version': 1, 'target': args.column, 'symbols': out}
    args.out.write_text(json.dumps(doc, indent=1))

    funcs = sum(1 for e in out if e['t'] == 'func')
    print(f'scanned {len(files)} headers')
    print(f'symbols: {len(out)} ({funcs} funcs, {len(out) - funcs} labels)')
    if id_to_rva:
        print(f'resolved against {args.addrlib.name} ({len(id_to_rva)} entries); '
              f'dropped {unresolved} with no {args.column} address')
    print(f'wrote {args.out}')


if __name__ == '__main__':
    main()
