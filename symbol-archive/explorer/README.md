# Type-layout explorer

A single self-contained HTML page for browsing the byte layout of every
Skyrim engine class in the archive: search a class, read its fields,
offsets, and sizes, and see whether the total size is confirmed
byte-for-byte against the header's own `static_assert`.

This is the public, searchable answer to *"what's at offset 0xB8 in
`Actor`?"* -- the question the community currently answers with a stale,
hand-maintained `types.h` shared privately. It needs no binary, no Ghidra,
and no server: open `index.html` in a browser (or host it on GitHub Pages).

`index.html` is generated and self-contained (data inlined); it is safe to
commit and to serve statically. It carries no game code or assets -- only
field names, offsets, and sizes derived from CommonLibSSE-NG (MIT).

## Regenerate

```bash
# 1. dump the archive to JSON (headless Ghidra; reuse any existing project)
analyzeHeadless <proj> <name> -process <anyprog> -noanalysis \
  -scriptPath ../tools \
  -postScript DumpGdtJson.java /path/to/CommonLibSSE_AE.gdt /tmp/types.json

# 2. mine the ground truth (record-qualified, patch 0011+)
python3 ../../type-importer/scripts/mine_static_asserts.py \
  ../../type-importer/vendor/CommonLibSSE-NG/include --json /tmp/ae_sizes.json

# 3. build the page (filters out stdlib/Windows-SDK noise, adds verification badges)
python3 build.py /tmp/types.json /tmp/ae_sizes.json --patchset 0001-0030
```

Note: the page's "verified" count is computed by name-matching the *dumped
archive* against the mined `static_assert`s, and reads slightly lower than the
coverage sweep's OK count for the same patchset -- the sweep also counts
typedef-of-template aliases (`BSString` etc.) and enum entries that the dump
renders as different kinds. The sweep numbers in the READMEs are authoritative;
this page is a browser, not the scoreboard.

## Files

- `template.html` -- the page (design + logic), with a `__DATA__` placeholder
- `build.py` -- cross-references ground truth, filters to game types, inlines
  the data into `template.html` → `index.html`
- `index.html` -- the generated, committed, self-contained result
- `../tools/DumpGdtJson.java` -- headless Ghidra script dumping a `.gdt` to JSON
