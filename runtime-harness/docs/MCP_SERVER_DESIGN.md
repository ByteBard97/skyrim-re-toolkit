# Runtime-Harness MCP Server — Design Doc (v0.1/v0.2 superseded by v0.3: integrate with `devbench`)

Status: pre-implementation, no code written. Grounded in real, committed
artifacts, not speculation: `tools/parse_layout_log.py` (existing, working)
and `examples/RuntimeHarness.log.excerpt` (a real, captured log from a live
Skyrim AE 1.6.1170 session, 2026-08-26). Every log-line format cited below is
copied verbatim from one of those two files, not invented.

## Goal

An MCP server that lets an LLM (or any MCP client) ask questions about
`RuntimeHarness.log` in natural terms — "what package is actor `000AAF99`
currently running", "did the layout validator find any mismatches on this
box", "when did the last savegame event fire, and what was in it" — instead
of grepping a growing text file by hand. This is the "live Skyrim MCP" this
backlog item was scoped around: nothing else in the ecosystem does this
(checked before writing this doc — Skyrim SKSE tooling has editors, mod
managers, and static-analysis helpers; nothing that fronts a *running
plugin's* log as a queryable interface).

## Non-goals (read this before assuming more than the log gives you)

- **Not a live RPC into the game process — a deliberate choice, not an
  unexamined limitation.** `RuntimeHarness` writes to a file (`spdlog` file
  sink) on the Windows box; it has no socket, pipe, or any other IPC surface
  today. "Live" in this design means *near-real-time log tailing while the
  game is running*, not a query that reaches into the process's actual
  memory at query time. Real in-process IPC into an SKSE plugin is proven
  feasible by prior art — **SkyLink AI**
  (github.com/jarvann/SkryimMCM, verified to exist) runs a named-pipe
  bridge (`\\.\pipe\SkyrimMCP`) from an SKSE/CommonLibSSE-NG plugin to an
  external MCP server, exposing 74 gameplay tools; **SkyrimNet** similarly
  runs an MCP server on a local port with 40+ tools including console
  commands on the game thread. Both are real, working systems for
  *gameplay-object* control (player stats, quests, NPCs, world state) —
  not this project's RE-internals target (AI scheduler decisions, Havok
  physics-step state, savegame serialization detail). Log-tailing is chosen
  here because it needs zero new C++/plugin work and keeps this design
  buildable/verifiable today against what `RuntimeHarness` already emits;
  a named-pipe query channel modeled on SkyLink's approach is a real,
  proven-feasible v0.2 direction if RE-internals users want true low-latency
  queries instead of log-tail freshness — not attempted here because it's a
  distinct, much larger feature requiring new plugin-side IPC code.
- **Not a control interface.** Read-only. The MCP server never writes to
  the game, the plugin, or the log file — there is no "spawn an NPC" or
  "force a save" tool. If that's ever wanted, it needs its own design and
  its own safety review; this doc doesn't open that door.
- **Not cross-platform in practice.** The log lives on the Windows build
  machine. The server can run there directly, or on the Linux dev box
  reading the file over the same SSH channel already used to drive that
  machine (see "Where this runs" below) — either way, a live game session
  is a Windows-box prerequisite this doc doesn't change.
- **No new C++/plugin work.** This doc does not propose changing
  `RuntimeHarness` itself (no new log lines, no IPC additions) — v0.1 is a
  pure consumer of what the plugin already emits, verified against the two
  inspectors that are actually confirmed working
  (`AIProcessInspector`, `SavegameTracer`) plus `LayoutValidator`'s
  already-parsed LAYOUT/ADDR/LIVE lines. `HavokStepLogger` produces zero
  log lines as of this writing (README: "70+ minutes of real gameplay...
  ruled out timing"), so there is nothing for this server to surface from
  it yet — its tool surface is added when/if that inspector starts
  producing output, not designed blind now.

## What already exists (reuse, don't rebuild)

- **`tools/parse_layout_log.py`**: working regex parser for
  `LayoutValidator: LAYOUT/ADDR/LIVE` lines, already turning them into a
  JSON structure (`{"layout": {...}, "addr": {...}, "live": [...]}`) and
  already doing the three-way diff against
  `type-importer/coverage_baseline.json`. The MCP server **imports this
  module's `parse_log()` and `diff_against_baseline()` directly** — it does
  not reimplement layout parsing. (Requires lifting `parse_log` out of the
  script's `if __name__ == "__main__"` guard into an importable function,
  which it already is — no refactor needed, just an import.)
- **`examples/RuntimeHarness.log.excerpt`**: real captured output for the
  two working inspectors, used below to write the AIProcessInspector/
  SavegameTracer regexes this doc adds (parse_layout_log.py doesn't cover
  these two — it only handles LayoutValidator's own lines).

## Real log line formats (verbatim, from the two source files above)

```
[12:25:30.509] [info] RuntimeHarness v0-1-0-0 loading (runtime: Skyrim 1-6-1170-0)
[12:25:30.509] [info] AIProcessInspector: Actor::Update hook installed (Actor + Character vtables).
[12:25:30.509] [info] LayoutValidator: LAYOUT class=TESForm sizeof=0x20 off.formFlags=0x8 off.formID=0xC off.formType=0x0
[12:25:35.479] [info] kDataLoaded received -- game data is fully loaded.
[12:25:35.480] [info] LayoutValidator: ADDR vtable=TESForm[0] id=231469/187895 resolved=0x7FF6128F1000 rva=0x5B1000
[12:25:35.480] [info] LayoutValidator: LIVE TESForm(0x07) formID=00000007(raw=00000007,OK) formType=0x2B(raw=0x2B,OK)
[12:25:44.183] [info] SavegameTracer: BSSaveDataEvent 0x59499ef38 fired
[12:25:44.183] [info] SavegameTracer: saveGameList has 220 entries
[12:25:44.183] [info]   Save22_F3D415A1_1_XXXXXXXXXXXX_Tamriel_000157_20211213052538_10_1 -- player '' () at 'Skyrim', playtime
[12:25:49.368] [info] kPostLoadGame received -- a save finished loading.
[12:25:49.691] [info] actor 00106B85 -> package 0010C505 () [Package]
[12:25:49.691] [info] actor 000654FB -> package <none>
```

Two new line families this doc's parser must handle (not covered by
`parse_layout_log.py`):

**AIProcessInspector** — `actor <FORMID_HEX> -> package (<none>|<FORMID_HEX> (<NAME>) [<TYPE>])`.
Name field is frequently empty (`()`) in the real excerpt — not every
package resolves a friendly name. Note this line has **no distinguishing
prefix token** (unlike every other inspector's lines, which start with
`<InspectorName>:`) — it's disambiguated purely by matching `^actor
[0-9A-F]+ -> package`, which is a real, if mild, parsing fragility worth
flagging rather than hiding (see Risks).

**SavegameTracer** — three-line group: `BSSaveDataEvent <ptr> fired`,
`saveGameList has <N> entries`, then N indented lines of
`  <filename> -- player '<name>' (<race>) at '<location>', playtime <time>`
(playtime can be blank, as shown above, when the field wasn't populated at
capture time).

**Plugin lifecycle** (both inspectors' setup, and the messaging-interface
events every tool query needs for context — "is this data from before or
after the last save load"): `RuntimeHarness vX loading`, `<Name>: <hook
description> installed`, `Loaded.`, `kDataLoaded/kNewGame/kPreLoadGame/
kPostLoadGame received`.

## Intermediate data model (the decoupling boundary, same shape as TIL_EXPORT_DESIGN.md's JSON)

One in-memory structure per log file, rebuilt incrementally as new lines
arrive (see "Where this runs" for the tailing mechanism):

```python
{
  "lifecycle": {
    "plugin_version": "v0-1-0-0",
    "runtime": "Skyrim 1-6-1170-0",
    "hooks_installed": ["AIProcessInspector", "HavokStepLogger", "SavegameTracer"],
    "events": [{"time": "12:25:35.479", "event": "kDataLoaded"}, "..."],
  },
  "layout": { /* verbatim from parse_layout_log.parse_log()["layout"] */ },
  "addr":   { /* verbatim from parse_layout_log.parse_log()["addr"] */ },
  "live":   [ /* verbatim from parse_layout_log.parse_log()["live"] */ ],
  "ai_packages": {
    # keyed by actor form ID (hex string), most-recent-wins -- this is a
    # STATE PROJECTION of the log's append-only event stream, not the raw
    # events themselves (see "actor state" tool below for why both matter)
    "00106B85": {"package": "0010C505", "name": "", "type": "Package", "time": "12:25:49.691"},
  },
  "ai_package_history": [
    # raw, ordered event stream -- every transition, not just latest-per-actor
    {"time": "12:25:49.691", "actor": "00106B85", "package": "0010C505", "name": "", "type": "Package"},
  ],
  "savegame_events": [
    {
      "time": "12:25:44.183", "event_ptr": "0x59499ef38", "entry_count": 220,
      "entries_shown": [{"filename": "Save22_...", "player": "", "race": "", "location": "Skyrim", "playtime": None}],
    },
  ],
}
```

## MCP tool surface (v0.1)

Read-only, one tool per real question this data can actually answer:

- `get_lifecycle_status()` — plugin version, runtime, which hooks
  installed, most recent `kDataLoaded`/`kNewGame`/`kPreLoadGame`/
  `kPostLoadGame` event and its timestamp. The "is the log even fresh, and
  what state is the game in" tool every other query implicitly assumes an
  answer to.
- `get_actor_package(form_id)` — current (most recent) package for one
  actor from `ai_packages`, or `null` if never observed. This is the
  worked example from the backlog item's own framing ("query live
  inspector state").
- `get_actor_package_history(form_id, limit=20)` — the raw transition
  list for one actor from `ai_package_history`, most recent first. Answers
  "how has this NPC's package been changing", not just its current value.
- `list_recent_package_changes(since=None, limit=50)` — the tail of
  `ai_package_history` across ALL actors, optionally filtered to after a
  given timestamp. The "what's happening right now" tool.
- `get_layout(class_name)` — one class's `LayoutValidator` LAYOUT entry
  (sizeof + offsets + note), straight from `parse_layout_log.py`'s output.
- `diff_layout_vs_baseline(class_name=None)` — the three-way diff
  (`parse_layout_log.diff_against_baseline`) against
  `type-importer/coverage_baseline.json`, for one class or all of them.
  Reuses the existing tool's exit-code-1-on-mismatch logic as the "is
  there a real disagreement" signal.
- `get_latest_savegame_snapshot()` — the most recent `savegame_events`
  entry in full (entry count + the entries actually logged — note the real
  excerpt shows only 5 of 220 entries get logged per firing, an existing
  `SavegameTracer` limitation this tool surfaces rather than hides).
- `get_addr_resolution(name)` — one class's `ADDR` vtable/RTTI resolution
  entries (resolved address + RVA), for cross-checking against the Address
  Library by hand.

Every tool's response includes the **log file's own last-modified
timestamp** and a `stale_seconds` field (now minus that timestamp) — since
this is log-tailing, not a live process query, a client must always be able
to tell "this data is from 3 seconds ago" from "this data is from a session
that ended 6 hours ago" (see Risks — this is the single most important
honesty signal this server can emit, given the Non-goals section above).

## Where this runs

Two viable deployments, not mutually exclusive:

**A. On the Windows build machine, alongside the game.** Simplest data
path (local file read, no transfer lag), but ties the MCP server's
lifecycle to a box this project already treats as a scarce, gated resource.
Fine for the person actually at the keyboard there; not reachable from the
Linux-side workflow this project mostly runs.

**B. On the Linux dev box, reading the log over the existing SSH channel.**
Matches how every other Windows-box interaction in this project already
works ("Builds happen on a dedicated Windows machine driven over SSH" --
README, both root and runtime-harness). Concretely: `ssh <box> "tail -f -n
+1 'Documents/My Games/.../RuntimeHarness.log'"` piped into the same
parser, or a periodic `scp`/`rsync` poll if a persistent SSH tail proves
fragile. This is the recommended default — it needs no new access grant
beyond what driving builds already uses, and keeps the MCP server itself
off the gated resource.

Either way: **the server never touches the game or the box's input** (no
`SendInput`/`keybd_event` the way the earlier live-testing session did) --
purely a log reader, matching the read-only non-goal above.

## Verification (no game session required for most of this)

1. **Regex correctness against the real excerpt.** Every new AIProcessInspector/
   SavegameTracer regex is tested against
   `examples/RuntimeHarness.log.excerpt` verbatim (committed, real data) --
   if a pattern doesn't match every line in that file, it's wrong before
   any MCP wiring is even written. `parse_layout_log.py`'s own LAYOUT/ADDR/
   LIVE regexes are already covered by its existing tests against
   `tools/sample_logs/`.
2. **Tool-response shape tests against the same excerpt**, offline (no
   MCP client, no game): feed the excerpt through the full parser +
   state-projection pipeline and assert each tool function's output
   matches hand-computed expected values (e.g. `get_actor_package("00106B85")`
   must return package `0010C505` after the excerpt's own last transition
   for that actor). This is the same "known input, known output" discipline
   `parse_layout_log.py`'s sample-log tests already use.
3. **`stale_seconds` correctness** with a synthetic old file
   (`touch -d "6 hours ago"`) -- confirms the honesty signal actually fires
   before it's ever needed against a real stale session.
4. **With a live game session** (gated, needs the Windows box + an actual
   play session, same gate as `HavokStepLogger`'s own live verification):
   confirm the tailing mechanism (route B) actually keeps up with a
   growing log in real time, and that `get_lifecycle_status()` correctly
   reflects a `kPostLoadGame` that happens *during* the MCP server's own
   runtime, not just one baked into a static excerpt.

## Work breakdown

**Now (no game/IDA access required):**

- [ ] Lift `parse_layout_log.parse_log`/`diff_against_baseline` into an
      importable state (already true — just document the import contract).
- [ ] New parser module (`runtime-harness/tools/mcp_server/log_state.py`
      or similar) implementing the AIProcessInspector/SavegameTracer/
      lifecycle regexes above, tested against
      `examples/RuntimeHarness.log.excerpt`.
- [ ] State-projection layer (`ai_packages` latest-wins view +
      `ai_package_history` raw stream) over the parsed event list.
- [ ] MCP server wiring (Python MCP SDK) exposing the 7 tools above as
      thin wrappers over the parser + state layer.
- [ ] Offline tool-response tests against the committed excerpt (item 2 above).
- [ ] `stale_seconds` synthetic-old-file test (item 3 above).

**Gated (needs the Windows box + a live game session, same gate as
`HavokStepLogger`'s own live-verification item):**

- [ ] Confirm the SSH-tail deployment (route B) actually tracks a live,
      growing log without dropping lines under real gameplay load.
- [ ] End-to-end: MCP client asks `get_actor_package` for an NPC mid-session,
      confirm the answer updates as the game runs.

## Risks / honest caveats

- **AIProcessInspector's line format has no inspector-name prefix** (every
  other line starts with `<Name>:`; this one is bare `actor X -> package
  Y`) — a plugin log-format change that happens to start a line with
  `actor ` and use a similar shape could false-match. Low risk in practice
  (SKSE plugin log conventions are fairly stable, and this project owns
  the only producer of this log), but worth a code comment pointing back
  here so nobody "fixes" the regex to be looser without noticing why it's
  narrow.
- **`SavegameTracer` only logs 5 of N saveGameList entries per firing**
  (confirmed in the real excerpt: 220 entries, 5 shown) — `entries_shown`
  in the data model is named that way specifically so no tool response
  implies it has the full list when it doesn't.
- **This entire design is unverified against a live, currently-running
  game** — everything except the last two "Gated" work-breakdown items is
  checkable against the committed static excerpt alone, which is real data
  but a snapshot, not a stream. Route B's tailing behavior under real
  conditions is the one genuinely open question, flagged as gated rather
  than assumed to work.

---

# v0.2 — Control interface (XT-7)

Status: pre-implementation, no code written. This section supersedes v0.1's
"Not a control interface" non-goal for a narrow, explicitly-scoped reason:
**real session friction, not a feature wishlist.** Tonight's work needed
a human to physically press Continue at the main menu and be present at the
Windows box for anything past that — a load-a-save action that has nothing
to do with reverse-engineering and everything to do with this box being
remote. v0.2 exists to remove that specific friction, not to build a
general gameplay-automation surface.

## Why not adopt SkyLink AI / SkyrimNet wholesale

Both are real, working, popular (SkyrimNet: MCP on :8889, 44+ tools
including console commands on the game thread; SkyLink AI: named-pipe
bridge, 74 tools) — checked, not assumed (see v0.1's non-goals section,
which already cites both). Not adopted here because:

- **Scope mismatch.** Both target *gameplay*-object control for AI-NPC
  systems (dialogue, quests, world state as game content). This project's
  actual need during the live test session was *test-harness* control: load a specific save,
  put the player near a target class instance, nothing about NPC behavior
  or quest state.
- **Attack surface.** A 40-70+ tool general console-command-passthrough
  surface is a much larger thing to reason about safely than "load this
  save" and "move the player here." Every unused tool in that surface is
  still something a client (or a bug) could invoke.
- **What IS adopted from them, deliberately:** SkyrimNet's core safety
  technique (mutate game state *on the game thread*, never via simulated
  input/`SendInput`) — real, proven-feasible prior art already cited in
  v0.1, reused here regardless of process architecture. (An earlier
  version of this bullet also credited SkyLink AI's separate-process
  split as adopted; the "Architecture" section below now runs everything
  in-process instead, per the project's firm no-separate-process
  requirement — see that section's own superseded note for why.)

## Addendum: reviewing an external research report against the real headers

An external research report surveying MCP-in-Skyrim was shared
architecture options. Per this project's standing discipline (verify
against the real vendored headers before writing anything into this doc
as fact), each claim was checked rather than transcribed:

- **Transport: WebSocket as an alternative to the named pipe above.**
  Verified real via the GitHub API (not just trusting the report):
  [`andreyvelsk/SkyrimWebSocket`](https://github.com/andreyvelsk/SkyrimWebSocket)
  (a real SKSE plugin, C++, exposing `ws://127.0.0.1:8765`) is itself built
  from [`SkyrimScripting/SKSE_Template_WebSockets`](https://github.com/SkyrimScripting/SKSE_Template_WebSockets)
  (a real, reusable GitHub template repo, `is_template: true`, C++,
  confirmed via `gh api`). This is worth evaluating as a starting point
  instead of hand-writing `CreateNamedPipe`/`ConnectNamedPipe` from
  scratch for T3-8's implementation — a WebSocket on localhost is not
  meaningfully less safe than a named pipe here (still local-only, no
  external exposure) and a maintained template lowers the amount of new
  low-level Win32 code this project has to own and get right. **Not
  switched to in this doc** — the protocol/framing choice doesn't change
  anything else in this design (command set, task-interface marshaling,
  scope boundary all apply identically either way), so it's left as an
  explicit implementation-time decision for whoever picks up T3-8, not
  re-litigated here.
- **`ConsoleUtil`/`ExecuteCommand` as a console-command execution path —
  NOT verified, do not cite as fact.** Grepped the entire vendored
  `CommonLibSSE-NG/include` tree for `ConsoleUtil` and `ExecuteCommand`:
  zero matches. This class/method may exist in a different CommonLibSSE-NG
  version or fork than what's vendored here, but this project only trusts
  what's actually in the vendored headers — so this
  doc does not adopt console-command execution as a mechanism until that
  API is confirmed present. The command set above already avoids needing
  it (direct API calls instead).
- **Native input injection via `BSInputDeviceManager` for main-menu
  navigation (e.g. selecting "Continue") — partially verified, capability
  NOT confirmed.** The class itself is real (`RE/B/BSInputDeviceManager.h`,
  vendored), but the only members present in this vendored version are
  `GetDeviceKeyMapping`/`GetDeviceMappedKeycode` — read-only key-mapping
  queries, no `SendEvent`/injection method of any kind. This is a real,
  unsolved need (the live session's actual friction was exactly this: a human
  pressing Continue at the main menu) but this doc does NOT claim a
  mechanism for it that isn't in the headers. `load_save`'s two API-level
  methods (`Load`/`LoadMostRecentSaveGame`) already solve the *save
  loading* half of that friction without needing any menu navigation
  at all — this gap is narrower than it first sounds. True main-menu UI
  automation (if ever needed) is left as an open question for a future
  pass, not guessed at here.
- **DirectX 11 swap-chain hooking for screenshot capture — real and
  technically sound, explicitly OUT of this pass's scope, flagged as a
  possible v0.3 direction only.** `IDXGISwapChain::Present` detouring
  (PolyHook2/MinHook) plus a GPU-to-CPU staging texture readback is a
  legitimate, working technique elsewhere, but it's rendering-pipeline
  hooking and GPU memory extraction — a materially larger, higher-risk
  feature than "load a save and move the player," and outside this pass's
  explicit "minimal, RE-testing-focused" mandate. Not designed here at
  all; noted only so it doesn't get silently folded into v0.2's scope by
  a future reader of the source report.

## Architecture — SUPERSEDED, see revision below

The section originally here proposed a two-process split (thin plugin-side
pipe listener + a separate Python MCP process on the Linux box). That
framing was wrong: a separate MCP server process is firmly out — a hard
project requirement, stated twice. The real constraint was mischaracterized
as "in-process vs. separate process" when it's actually "stdio vs. network
transport" — stdio genuinely can't work embedded in Skyrim (stdout isn't a
clean pipe once the engine/loader are writing to the console too, so a
JSON-RPC stream over it would get corrupted), but HTTP/SSE or WebSocket
transport works fine embedded, with no process boundary required at all.
See the revised architecture immediately below, which replaces this
section. Kept here (not deleted) so the reasoning that got corrected is on
record, same as `patches/0007-*.md`'s own superseded-by convention.

## Architecture (revised) — embedded, single process, no separate MCP server

**`RuntimeHarness.dll` runs the entire MCP protocol server itself**, in a
background thread, using an embedded C++ MCP library rather than talking
to a process on the Linux box:

```
MCP client (editor/agent/chat tool)
      |  MCP protocol over HTTP/SSE or WebSocket (NOT stdio -- see above)
      v
RuntimeHarness.dll (Windows box), background std::thread
      |  hkr04/cpp-mcp (verified real: github.com/hkr04/cpp-mcp, C++, 318
      |  stars, not archived, "Lightweight C++ MCP SDK", HTTP/SSE
      |  transport + tool-registration API per its own description --
      |  this SUPERSEDES the earlier "no third-party MCP library" call,
      |  which was reasoned correctly off the WRONG architecture)
      v
Thread-safe request queue: mutex + condition_variable guarded FIFO,
  std::packaged_task/std::future per request-response pair -- the ONLY
  thing shared between the MCP thread and the main thread. The MCP
  thread never touches RE::* directly, ever.
      v
SKSE::TaskInterface::AddTask(...) (real, verified: `const TaskInterface*
  SKSE::GetTaskInterface() noexcept` in `SKSE/API.h:24`, `void AddTask(TaskFn)
  const` in `SKSE/Interfaces.h:196` -- already how this project's other
  main-thread work happens, e.g. this project's own messaging-interface
  pattern in `main.cpp`) drains the queue safely on the main thread,
  once per tick/frame.
      v
Real CommonLibSSE-NG API calls (BGSSaveLoadManager::Load, TESObjectREFR::MoveTo, ...)
```

No `SendInput`/`keybd_event` anywhere in this design, same as the
superseded version — matching v0.1's "the server never touches the game's
input" principle, extended to "only ever via the game's own thread-safe
task queue."

**Trade-off, stated explicitly rather than silently accepted:** embedding
the full MCP protocol layer in-process means a bug in that layer (a
malformed request, a parsing crash, a threading bug in the queue) can
crash Skyrim itself — unlike the superseded two-process design, where a
bug in the protocol layer would take down a Python process on the Linux
box, not the game. This is a real cost of the no-separate-process
requirement, not a hidden one. Mitigated, not
eliminated, by: the MCP thread never calling `RE::*` directly (all game
mutation happens through the queued/main-thread path, so a protocol-layer
bug can't corrupt game state directly, only crash the plugin's own
thread) and keeping the command surface itself minimal (see below) so
there's less protocol-adjacent code to get wrong in the first place.

**On the earlier WebSocket-transport research-report note above:** this
revision makes that finding directly load-bearing rather than a mere
alternative — `SkyrimScripting/SKSE_Template_WebSockets` (verified real)
is now a concretely relevant reference for the embedded HTTP/SSE-or-
WebSocket server thread this architecture needs, not just a named-pipe
alternative for a separate-process design that no longer exists.

## Command set — each one tied to a real friction point from live testing, not a wishlist

Every command below is backed by a real CommonLibSSE-NG API already
present in the vendored headers (checked, not invented) or explicitly
flagged as not yet confirmed.

- **`load_save(filename_or_index)`** — solves the live session's actual blocker
  (a human needing to press Continue by hand). Backed by
  `BGSSaveLoadManager::Load(const char* a_fileName)` (real,
  `RE/B/BGSSaveLoadManager.h:87`) or `LoadMostRecentSaveGame()` (same
  file, `:90`) for the common "just continue" case — both real, existing
  singleton methods (`BGSSaveLoadManager::GetSingleton()`), no console
  command needed. Response includes the same `kPreLoadGame`/
  `kPostLoadGame` lifecycle events v0.1's `get_lifecycle_status()` already
  tracks, so a client can poll load completion with a tool it already has.
- **`teleport_player_to(form_id)`** — solves "need to be near X to test
  a code path" (this pass's own T3-3 work needed a real save load to
  reach `PlayerCharacter`/`ACTOR_RUNTIME_DATA` state; teleporting to a
  specific reference is the general form of that need). Backed by
  `TESObjectREFR::MoveTo(TESObjectREFR* a_target)` (real,
  `RE/T/TESObjectREFR.h:456`) called on `PlayerCharacter::GetSingleton()`
  with the target resolved from `TESForm::LookupByID(form_id)` — both
  real, existing APIs.
- **`get_control_status()`** — read-only, but listed here because it's
  part of the control channel: confirms the embedded MCP server thread is
  alive and reports whether the last command it ran succeeded, without
  needing a
  round-trip through the game log. The "did that actually work" tool this
  channel needs that v0.1's log-tailing tools structurally can't provide
  (a command's own success isn't necessarily logged).

**Explicitly NOT designed in this pass (the "maybe" items from XT-7's own
backlog framing, deferred honestly rather than guessed):**

- **Force time-of-day / weather.** `Calendar` (`RE/C/Calendar.h`) exists
  and models the game clock, but its value storage is backed by
  `TESGlobal` records this doc has not yet traced to a confirmed, safe
  setter API (unlike `BGSSaveLoadManager`/`TESObjectREFR` above, where the
  exact method signature is already in hand). Real need, not designed
  blind — needs one more header-reading pass before it gets its own
  command, not before this design is useful without it.

**Explicit scope boundary — what this deliberately will not do:**

- **No general console-command passthrough.** No `run_console_command(str)`
  tool, ever, in this design. Every command is a named, fixed-signature
  function tied to a real API call this doc cites by file and line — the
  attack surface is exactly as large as the command list above, not
  "anything the console can do."
- **No arbitrary scripting.** No Papyrus invocation, no code injection, no
  general "run this" primitive of any kind.
- **No NPC/quest/dialogue control.** That's SkyrimNet/SkyLink's actual
  target; explicitly out of scope here (see "Why not adopt" above).
- **No unauthenticated exposure beyond localhost.** Unlike the superseded
  named-pipe design, the revised embedded HTTP/SSE-or-WebSocket server IS
  a real network listener, not a local-only IPC primitive — this needs to
  bind to `127.0.0.1` only (never `0.0.0.0`) and, since the box is reached
  over the existing SSH channel for everything else this project already
  does, an MCP client on the Linux dev box should reach it through an SSH
  local-port-forward rather than the port being exposed on the box's LAN
  interface. This is a real, slightly larger exposure than the superseded
  design had (a bound TCP port vs. a named pipe with no network presence
  at all) and is written down here as part of the honest trade-off this
  revision accepts, not glossed over.

## Verification plan

1. **Offline: command-format validation.** The embedded MCP server's
   request-to-command mapping gets the same "known input, known output"
   test discipline as v0.1's log parsers — malformed/oversized/unknown
   requests must be rejected before any `AddTask` call, testable without
   a running game (a unit test driving the parsing/validation function
   directly).
2. **Compile-time: real API existence.** Every cited API
   (`BGSSaveLoadManager::Load`, `LoadMostRecentSaveGame`,
   `TESObjectREFR::MoveTo`, `SKSE::TaskInterface::AddTask`) needs to
   actually compile against the vendored CommonLibSSE-NG headers before
   any of this is trusted — cheap, no Windows box required for this step
   alone (the type-importer sweep pipeline already parses these same
   headers).
3. **Gated (Windows box + live game session, same gate as
   `HavokStepLogger`/v0.1's own live items):** `load_save` against a real
   save file, confirm `kPostLoadGame` fires and the loaded save matches
   the requested one; `teleport_player_to` against a real, known form ID,
   confirm `PlayerCharacter`'s position actually changes (readable via the
   same `LayoutValidator`-style live field read this project already has
   working). This is real implementation work (tracked as T3-8) — this
   doc is the design that work executes against, not a claim that any of
   it has run yet.

---

# v0.3 — SUPERSEDES v0.1 (read-only) and v0.2 (control): integrate with `alandtse/devbench` instead of building either from scratch

**This is the "don't reverse-engineer/reinvent what the community already
produced" principle** — the same one this repo's own root `README.md`
states as its Architecture design principle for `type-importer` (package
CommonLibSSE-NG's community RE knowledge instead of deriving offsets by
hand) — applied to tooling infrastructure instead of type data. Verified
before writing a word of this section, not taken on description alone:
fetched `alandtse/devbench`'s actual `README.md` via `gh api` (real repo,
not fabricated — C++, GPL-3.0, 10 stars, pushed 2 days before this was
written, so actively maintained, not abandoned).

## What devbench already is

A standalone SKSE plugin — already built, already working, per its own
docs — that runs an in-process server on `127.0.0.1` exposing a
`ToolRegistry` over **both** MCP (`/mcp`, JSON-RPC/streamable-HTTP) and
plain REST (`/api/tool/<name>`) from one shared registry. Directly
relevant to everything v0.1/v0.2 above set out to build:

| What v0.1/v0.2 designed | What devbench already ships |
|---|---|
| Read-only log-tailing with `stale_seconds` honesty (v0.1) — because `RuntimeHarness` only writes a file | `inspect` tool: **synchronous, live** state reads (`scene`, `player`, `inventory`, `quests`, `effects`, `refs`, `mods`, `vm`) run on the main thread and return the real value *now*, not a log-tail snapshot from N seconds ago. Strictly better ground truth than what v0.1 could ever offer without new plugin IPC work. |
| `load_save`/`get_control_status` (v0.2) — new C++, `BGSSaveLoadManager::Load` marshaled through a hand-built pipe/WebSocket server | `game action='loadLast'` / `action='load'` — already built, already exposed. **This is the exact friction point from live testing** (a human needing to press Continue), already solved, zero new code required on our side. |
| `teleport_player_to` (v0.2) — new C++, `TESObjectREFR::MoveTo` | `console` tool (`player.moveto`/`coc`/`setpos` etc., with real output capture via the marker-fence technique) already covers this, and more generally than one hand-picked API call would. |
| An embedded MCP protocol server, threading model, request queue, transport choice (the entire "Architecture (revised)" section above) | Already built and running: `ToolRegistry` + `McpAdapter`/`RestAdapter` over one `httplib` server, `MainThread::RunAndWait` for the exact same "marshal to main thread, return synchronously" pattern this doc's own revision converged on independently. Confirms that pattern was the right one to converge on — but it doesn't need re-implementing. |
| Guessed-sleep session automation ("wait for the main menu to settle") | `scenario` tool with `waitFor` steps keyed on real Skyrim lifecycle events (`waitFor lifecycle:postLoadGame`) instead of a fixed delay — exactly the class of problem the Continue-press friction belongs to, solved generally. |

## What this project still owns, and what changes

`RuntimeHarness`'s actual value — `AIProcessInspector`, `LayoutValidator`,
`SavegameTracer`, and (once its open root cause is fixed) `HavokStepLogger`
— **does not go away or get replaced.** Those are this project's real
reverse-engineering work: hooks into engine subsystems nothing else
exposes. What changes is *how their data reaches an MCP client*: instead
of writing to a log file for a separate reader to tail (v0.1) or building
a competing embedded MCP server (v0.2's revision), `RuntimeHarness`
becomes a **devbench tool provider** via its C ABI.

```
RuntimeHarness.dll (this project's real RE hooks, unchanged)
      |  kPostLoad: DevBenchAPI::GetDevBenchInterface001() -- returns
      |  null gracefully if devbench isn't installed (soft dependency,
      |  RuntimeHarness keeps working standalone via its log file either way)
      v
dvb->RegisterTool("runtimeharness.ai_package", schema, handler, ctx)
dvb->RegisterToolExtension("inspect", "runtimeharness.layout_diff", schema, handler, ctx)
      |  handler runs on devbench's server thread; anything touching
      |  RE::* still marshals through SKSE::TaskInterface, same as every
      |  design in this doc has always required
      v
devbench.dll's ToolRegistry -- reachable over /mcp AND /api/tool/<name>,
  alongside devbench's own built-in `game`/`console`/`inspect`/`scenario`
  tools, on ONE port, to ONE MCP client connection
```

**Integration cost, concretely:** `include/DevBenchAPI.h` + `DevBenchAPI.cpp`
are MIT-licensed and meant to be dropped directly into a consumer plugin
(no vcpkg required for the simplest path — "copy the two API files
directly... no vcpkg involved," per devbench's own README) or pulled via a
vcpkg overlay port. `RuntimeHarness` already builds via CMake; devbench
itself builds via xmake, but that's irrelevant to us — we never build
devbench, we link two small MIT files and devbench.dll is a separate,
independently-installed SKSE plugin at runtime, the same way any two SKSE
mods coexist in one `Data/SKSE/Plugins/` folder.

**Licensing, matching this project's existing posture:**
devbench the plugin is GPL-3.0; we never link against or redistribute its
GPL-3.0 code. The integration surface we'd actually consume
(`DevBenchAPI.h`/`.cpp`) is separately, deliberately MIT-licensed by
devbench's own author specifically so consumers avoid that entanglement —
the same license-boundary discipline this project already applies to
CommonLibSSE-NG-derived `.gdt` archives (MIT, attribution kept) vs. the
toolkit's own code (MIT), just running the other direction here (we
consume an MIT surface in front of someone else's GPL-3.0 plugin, rather
than us being the GPL-3.0-derived side).

## What v0.1/v0.2 above are still good for

Not deleted, same convention as `patches/0007-*.md`'s superseded-by note
and this doc's own earlier "Architecture — SUPERSEDED" section: v0.1's
real log-line regexes (AIProcessInspector/SavegameTracer parsing) and
v0.2's verified real-API citations (`BGSSaveLoadManager::Load`,
`TESObjectREFR::MoveTo`, `SKSE::TaskInterface::AddTask`) are directly
reusable as the *handler bodies* registered with devbench's `RegisterTool`
— the API research wasn't wasted, only the "build our own transport/
protocol/threading layer to deliver it" plan was superseded. `parse_layout_log.py`
also stays useful standalone for offline analysis of committed log files
(`examples/RuntimeHarness.log.excerpt`, sample logs) regardless of what
serves live queries.

## Verification plan (v0.3)

1. **Confirm devbench's C-ABI header matches this doc's description**
   before writing any registration code — this section is grounded in
   devbench's own `README.md` (fetched real, not paraphrased from a
   secondary source), not yet in a direct read of `include/DevBenchAPI.h`
   itself. That header read is the first real step of implementation, not
   assumed done by this doc.
2. **Soft-dependency behavior**: `RuntimeHarness` must build and run
   identically with devbench absent (verifies `GetDevBenchInterface001()`
   returning null is handled as a no-op, not a crash) — testable on a
   build with devbench simply not installed in `Data/SKSE/Plugins/`.
3. **Gated (Windows box + live game session):** install devbench
   alongside `RuntimeHarness`, confirm `runtimeharness.*` tools appear in
   `tools/list` alongside devbench's built-ins, confirm one registered
   tool (e.g. `AIProcessInspector`'s current-package data) returns live,
   correct data via a real MCP call — and separately, confirm
   `game action='loadLast'` alone (no `RuntimeHarness` code involved)
   actually solves the original friction end-to-end.

## Work breakdown (v0.3, replaces v0.2's T3-8 scope)

- [ ] Read `include/DevBenchAPI.h` + `cmake/ports/devbench-api/README.md`
      directly (not just this doc's README-derived summary) before
      writing integration code.
- [ ] Drop `DevBenchAPI.h`/`.cpp` into `RuntimeHarness`, wire the
      `kPostLoad` null-checked registration call.
- [ ] Register a first real tool wrapping existing, already-working data
      — `AIProcessInspector`'s current package-per-actor state is the
      natural first choice (already a clean in-memory map, no new hook
      needed, immediately useful, low risk).
- [ ] Verify per the plan above.
- [ ] Once proven, register `LayoutValidator`'s live diff and
      `SavegameTracer`'s save-list data the same way.
- [ ] Update the T3-8 task entry and this doc's status line to drop
      the "blocked/ready" framing tied to the superseded pipe/WebSocket
      plan.
