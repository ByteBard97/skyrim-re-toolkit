# type-importer

**Parses CommonLibSSE-NG C++ headers into Ghidra type archives (`.gdt`).**

See the [root README's type-importer section](../README.md#1-type-importer)
for current status, accuracy numbers, and the Quick Start.

## Where to look for what

- **[`DESIGN.md`](DESIGN.md)** -- the full investigation log: architecture
  decisions (why libclang over CastXML/PDB import), root-causes for every
  parser limitation found, verification methodology, open questions.
- **[`COVERAGE_SWEEP_PLAN.md`](COVERAGE_SWEEP_PLAN.md)** -- the coverage-sweep
  history: every accepted patch, what it fixed, before/after numbers, and the
  currently-deferred investigations with written reasons.
- **[`patches/`](patches/)** -- one `.patch` + `.md` writeup per accepted fix
  to the vendored `GhidraClangPoweredParse` parser, in order.
- **[`ADDRESS_LIBRARY_VALIDATION.md`](ADDRESS_LIBRARY_VALIDATION.md)** -- how
  generated Address Library IDs are cross-checked against real community
  databases.
- **[`RUNTIME_SE_1_5_97.md`](RUNTIME_SE_1_5_97.md)**,
  **[`RUNTIME_VR_1_4_15.md`](RUNTIME_VR_1_4_15.md)** -- per-runtime layout
  validation writeups.
- **[`scripts/`](scripts/)** -- `generate_gdt.sh` (the real entry point),
  `coverage_report.py` / `check_regression.py` (the CI regression gate),
  header-mining and layout-dump tooling.
- **[`tools/`](tools/)** -- `GenerateGdt.java`, the actual CLI invoked by
  `generate_gdt.sh`.
- **[`stubs/`](stubs/)** -- minimal headers so the real CommonLibSSE-NG parses
  without pulling in a full SKSE build.
- **[`vendor/`](vendor/)** -- `CommonLibSSE-NG` and `GhidraClangPoweredParse`,
  vendored as git submodules.

## Contributing

See the root [`CONTRIBUTING.md`](../CONTRIBUTING.md) for the patch
methodology (minimal repro, root-cause, full-sweep verification, written
regression accounting) -- every accepted patch in `patches/` follows it.
