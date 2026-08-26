# Runtime-Harness MCP Server — Design Doc (v0.1 read-only + v0.2 control)

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
lifecycle to a box this project already treats as a scarce, gated resource
(BACKLOG.md: "Do NOT touch the Windows box unless... acting on the user's
direct word"). Fine for the person actually at the keyboard there; not
reachable from the Linux-side agent workflow this project mostly runs.

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
Geoff to physically press Continue at the main menu and be present at the
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
  actual need tonight was *test-harness* control: load a specific save,
  put the player near a target class instance, nothing about NPC behavior
  or quest state.
- **Attack surface.** A 40-70+ tool general console-command-passthrough
  surface is a much larger thing to reason about safely than "load this
  save" and "move the player here." Every unused tool in that surface is
  still something a client (or a bug) could invoke.
- **What IS adopted from them, deliberately:** SkyLink AI's plugin-side
  architecture (a thin named-pipe listener in the SKSE plugin, with the
  actual protocol logic in a separate external process) and SkyrimNet's
  core safety technique (mutate game state *on the game thread*, never via
  simulated input/`SendInput`). Both are proven-feasible prior art already
  cited in v0.1; this section reuses the pattern, not the tool count.

## Addendum: reviewing a user-supplied research report against the real headers

Geoff shared an external research report surveying MCP-in-Skyrim
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
  what's actually in the vendored headers (project rule) — so this
  doc does not adopt console-command execution as a mechanism until that
  API is confirmed present. The command set above already avoids needing
  it (direct API calls instead).
- **Native input injection via `BSInputDeviceManager` for main-menu
  navigation (e.g. selecting "Continue") — partially verified, capability
  NOT confirmed.** The class itself is real (`RE/B/BSInputDeviceManager.h`,
  vendored), but the only members present in this vendored version are
  `GetDeviceKeyMapping`/`GetDeviceMappedKeycode` — read-only key-mapping
  queries, no `SendEvent`/injection method of any kind. This is a real,
  unsolved need (tonight's actual friction was exactly this: a human
  pressing Continue at the main menu) but this doc does NOT claim a
  mechanism for it that isn't in the headers. `load_save`'s two API-level
  methods (`Load`/`LoadMostRecentSaveGame`) already solve the *save
  loading* half of tonight's friction without needing any menu navigation
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

## Architecture — no MCP code in the plugin at all

Researched, not assumed: there is no official C++ MCP SDK as of this
writing (the `modelcontextprotocol` org has an open, unresolved proposal
discussion for one — issue #603). A few unofficial community C++ libraries
exist (e.g. `hkr04/cpp-mcp`) but none are vetted or official, and pulling
one into `RuntimeHarness` would mean vetting a new third-party dependency
for a Windows SKSE plugin just to speak a protocol the plugin doesn't need
to speak directly.

**The split v0.1 already committed to solves this for free:** the plugin
exposes the smallest possible surface, and the actual MCP protocol layer
(JSON-RPC, tool registration) runs as a separate process on the Linux dev
box, using the official Python MCP SDK — the same server v0.1's read-only
log-tailing tools already run in. SkyLink AI itself follows exactly this
split (SKSE plugin + separate C# bridge process, not one binary that
speaks MCP). Concretely:

```
MCP client (editor/agent/chat tool)
      |  MCP protocol (JSON-RPC over stdio/SSE)
      v
Python MCP server (Linux dev box)     <- same process as v0.1's log-tailing tools
      |  new: write side, over the existing SSH channel to the Windows box
      v
Named-pipe client (small Python helper, or a raw pipe write over SSH-forwarded socket)
      |  Windows named pipe: \\.\pipe\RuntimeHarnessControl
      v
RuntimeHarness.dll (Windows box) -- named-pipe LISTENER thread (new, small, raw
  Win32 CreateNamedPipe/ConnectNamedPipe/ReadFile -- no third-party MCP
  library, no JSON parsing beyond a tiny fixed command format)
      |  SKSE::TaskInterface::AddTask(...) -- marshals onto the game's own
      |  main thread, the same technique SkyrimNet uses instead of SendInput
      v
Real CommonLibSSE-NG API calls (BGSSaveLoadManager::Load, TESObjectREFR::MoveTo, ...)
```

The pipe listener thread's only job is: read a small fixed-format command
off the pipe, validate it against the minimal command set below, and hand
the actual game-state mutation to `SKSE::TaskInterface::AddTask()` (real,
existing API — `SKSE/Interfaces.h:196`, already used implicitly by this
project's messaging-interface pattern in `main.cpp`) so it executes safely
on the main thread instead of racing the pipe's own worker thread. No
`SendInput`/`keybd_event` anywhere in this design — matching v0.1's
existing "the server never touches the game's input" principle, extended
from "never" to "only ever via the game's own thread-safe task queue."

## Command set — each one tied to a real friction point from tonight, not a wishlist

Every command below is backed by a real CommonLibSSE-NG API already
present in the vendored headers (checked, not invented) or explicitly
flagged as not yet confirmed.

- **`load_save(filename_or_index)`** — solves tonight's actual blocker
  (Geoff needing to press Continue by hand). Backed by
  `BGSSaveLoadManager::Load(const char* a_fileName)` (real,
  `RE/B/BGSSaveLoadManager.h:87`) or `LoadMostRecentSaveGame()` (same
  file, `:90`) for the common "just continue" case — both real, existing
  singleton methods (`BGSSaveLoadManager::GetSingleton()`), no console
  command needed. Response includes the same `kPreLoadGame`/
  `kPostLoadGame` lifecycle events v0.1's `get_lifecycle_status()` already
  tracks, so a client can poll load completion with a tool it already has.
- **`teleport_player_to(form_id)`** — solves "need to be near X to test
  a code path" (this session's own T3-3 work needed a real save load to
  reach `PlayerCharacter`/`ACTOR_RUNTIME_DATA` state; teleporting to a
  specific reference is the general form of that need). Backed by
  `TESObjectREFR::MoveTo(TESObjectREFR* a_target)` (real,
  `RE/T/TESObjectREFR.h:456`) called on `PlayerCharacter::GetSingleton()`
  with the target resolved from `TESForm::LookupByID(form_id)` — both
  real, existing APIs.
- **`get_control_status()`** — read-only, but listed here because it's
  part of the control channel: confirms the pipe listener is alive and
  reports whether the last command it ran succeeded, without needing a
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
- **No unauthenticated network exposure.** The named pipe is a local
  Windows IPC primitive (not a TCP socket) reachable only from the same
  box or over the existing SSH channel already used to drive it — no new
  network-facing listener is introduced.

## Verification plan

1. **Offline: command-format validation.** The pipe listener's fixed
   command parser gets the same "known input, known output" test
   discipline as v0.1's log parsers — malformed/oversized/unknown commands
   must be rejected before any `AddTask` call, testable without a running
   game (a unit test driving the parsing function directly).
2. **Compile-time: real API existence.** Every cited API
   (`BGSSaveLoadManager::Load`, `LoadMostRecentSaveGame`,
   `TESObjectREFR::MoveTo`, `SKSE::TaskInterface::AddTask`) needs to
   actually compile against the vendored CommonLibSSE-NG headers before
   any pipe-handling code is trusted — cheap, no Windows box required for
   this step alone (the type-importer sweep pipeline already parses these
   same headers).
3. **Gated (Windows box + live game session, same gate as
   `HavokStepLogger`/v0.1's own live items):** `load_save` against a real
   save file, confirm `kPostLoadGame` fires and the loaded save matches
   the requested one; `teleport_player_to` against a real, known form ID,
   confirm `PlayerCharacter`'s position actually changes (readable via the
   same `LayoutValidator`-style live field read this project already has
   working). This is real implementation work (T3-8, BACKLOG.md) — this
   doc is the design that work executes against, not a claim that any of
   it has run yet.
