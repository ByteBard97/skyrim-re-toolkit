# Contributing

Thanks for considering it. This project's design principle, ground rules, and
working conventions are documented in the project notes — read that
first; it's the actual source of truth (kept up to date as the project's
internal engineering guide, not written as marketing copy).

## Short version

- We're not looking for novel RE research. We're looking for **reliable
  engineering** on top of what the community (CommonLibSSE-NG, meh321's
  Address Library, SKSE) has already reverse-engineered. See the README's
  "What's in here" section for where help is most useful right now
  (`type-importer`, `symbol-archive`, `runtime-harness`).
- **Ground rules are binding, not suggestions**: no console exploits, no DRM
  circumvention, no redistribution of game binaries/PDBs/copyrighted assets.
  Every type or offset must be derivable from public community sources, not
  from acquiring or dumping Bethesda's own build artifacts. See the project notes'
  "Ground rules" section for the full list.
- **Platform split matters**: `type-importer` and `symbol-archive` are
  Linux-native (Ghidra, libclang, CastXML, GitHub Actions `ubuntu-latest` all
  work fine); `runtime-harness` is Windows + MSVC only, no exceptions — see
  the project notes' "Platform constraints" section before assuming a change can
  be tested on Linux.
- **Don't invent offsets, struct layouts, or version numbers.** Pull them
  from CommonLibSSE-NG or the Address Library, or open an issue if the
  source isn't available to you.
- **Don't commit generated type archives** (`.gdt`/`.til`) or built
  binaries — see `.gitignore`. These are CI-published artifacts (GitHub
  Releases), not source.
- Licensing: the toolkit code itself is MIT (see `LICENSE`), but generated
  `.gdt`/`.til` archives are derived from CommonLibSSE-NG headers and
  inherit its GPL-3.0 (+ modding exception) license. Don't relicense
  generated archives.

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
