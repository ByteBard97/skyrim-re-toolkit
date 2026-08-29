---
name: Bug report
about: Something in the parser output, CI build, or runtime-harness plugin is wrong
title: ""
labels: bug
assignees: ""
---

**Which subproject?** `type-importer` / `symbol-archive` / `runtime-harness`

**What happened**
A clear description of the bug. If it's a layout/size mismatch, name the
exact class (e.g. `RE::TESObjectREFR`) and, if you have it, the expected vs.
actual size or offset.

**How to reproduce**
Exact command(s) run, or the exact `.gdt`/`.til` release/artifact used.

**Runtime/version**
Which Skyrim runtime this concerns (SE 1.5.97 / AE 1.6.1170 / AE 1.7.99 /
VR 1.4.15 / GOG 1.6.1179), if relevant.

**Expected behavior**
What you expected instead, and -- if you have it -- the community source
(CommonLibSSE-NG header, Address Library entry, a real disassembly) that
supports the expected value. Project rule: offsets and layouts are never
invented, only derived from public community sources -- citing one speeds up
triage a lot.

**Environment**
OS, Ghidra/IDA version, JDK version if building `type-importer` locally.
