# Contributing

Thanks for considering it.

## Short version

- We're not looking for novel RE research. We're looking for **reliable
  engineering** on top of what the community (CommonLibSSE-NG, meh321's
  Address Library, SKSE) has already reverse-engineered. See the README's
  "What's in here" section for where help is most useful right now
  (`type-importer`, `symbol-archive`, `runtime-harness`).
- **Ground rules are binding, not suggestions**: no console exploits, no
  distributing DRM-circumvention tools or cracked binaries, no redistribution
  of game binaries/PDBs/copyrighted assets. (Locally unpacking your own
  legally-purchased executable's SteamStub wrapper for static analysis —
  the same interoperability use case as debugging or disassembling your own
  binary — is standard RE practice and is what `demo/README.md` walks
  through; this rule targets distribution and piracy tooling, not that.)
  Every type or offset must be derivable from public community sources
  (CommonLibSSE-NG, the Address Library, RTTI), not from acquiring or dumping
  Bethesda's own build artifacts.
- **Platform split matters**: `type-importer` and `symbol-archive` are
  Linux-native (Ghidra, libclang, and GitHub Actions `ubuntu-latest` all
  work fine); `runtime-harness` is Windows + MSVC only, no exceptions —
  SKSE plugins are Windows DLLs built against Skyrim's PE ABI and cannot
  be built or tested on Linux/Proton.
- **Don't invent offsets, struct layouts, or version numbers.** Pull them
  from CommonLibSSE-NG or the Address Library, or open an issue if the
  source isn't available to you.
- **Don't commit generated type archives** (`.gdt`/`.til`) or built
  binaries — see `.gitignore`. These are CI-published artifacts (GitHub
  Releases), not source.
- Licensing: the toolkit code is MIT (see `LICENSE`). Generated `.gdt`/`.til`
  archives are derived from [CommonLibSSE-NG](https://github.com/CharmedBaryon/CommonLibSSE-NG)
  headers, which are themselves MIT-licensed — keep the attribution intact.
  The vendored parser extension (`GhidraClangPoweredParse`) is Apache-2.0;
  patches to it under `type-importer/patches/` stay Apache-2.0-compatible.

## Before opening a PR

- If you're touching `type-importer`'s parser (patches under
  `type-importer/patches/`), follow the existing methodology: root-cause with
  a minimal reproduction before writing a fix, verify with a full sweep
  (`type-importer/scripts/generate_gdt.sh` + `coverage_report.py` +
  `check_regression.py`) against `type-importer/coverage_baseline.json`, and
  write up the patch following the numbering/format already established in
  `type-importer/patches/*.md`. Zero regressions required — a fix that
  unmasks a pre-existing bug is fine, but document it; never merge a
  net-negative patch.
- Keep subproject READMEs (`type-importer/README.md`,
  `symbol-archive/README.md`, `runtime-harness/README.md`) consistent with
  the root README's status table and roadmap if your change affects status.

## Questions / bug reports

Use [GitHub Issues](https://github.com/ByteBard97/skyrim-re-toolkit/issues)
(templates provided) or
[Discussions](https://github.com/ByteBard97/skyrim-re-toolkit/discussions)
for open-ended questions.
