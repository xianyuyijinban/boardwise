# boardwise Architecture

Status: v0.3, 2026-09-16 — supersedes v0.2. The v0.3 sections (**Module rules**,
**Three coordinate spaces**, **Adding a bridge action**) are the project
constitution: they are enforced by tests, not by review alone (see each section
for the file that guards it).
Decision drivers: hardware review is *visual* and human-scale (a schematic is 1–5 pages,
a PCB one board — unlike thousand-line code diffs, every change can and must be inspected);
the product is born as a plugin/skill inside AI harnesses (Claude Code, Codex, VS Code),
not a standalone app (that waits until a user ecosystem exists).

## Design principles

1. **Checkability first** — every AI action yields three artifacts at each milestone:
   the result visible on the real EDA canvas, a semantic change list, and a review report.
   No black-box automation.
2. **Brain/bridge separation** — parsers, rules, engines and simulation run offline on files
   (CI-friendly, no editor needed). The bridge is only the senses and hands.
3. **Plugin form** — skill/CLI/MCP surfaces inside existing AI harnesses; the EDA canvas is
   the primary UI. No standalone frontend/backend until adoption justifies it.
4. **Rules are the taste** — one rule base with sources; the reviewer judges with it,
   the generator draws with it.

## Layers

```
agent surface (thin): skill / CLI (boardwise) / MCP later
engines (the brain, file-capable, editor-optional): review → generate → simulate
bridge (senses & hands): Python daemon (websockets) + TypeScript connector (.eext, official pro-api-types)
core: DesignModel (connectivity) + BoardGeometry (copper) + rule base
parsers: .enet, .epro2/.epru; later KiCad / Gerber for cross-EDA
render (narrow scope): report illustrations + CI/headless snapshots,
        benchmarked against native editor screenshots — never a replacement viewer
```

## Module rules (v0.3, 2026-09-16)

The layer diagram above is a picture; these are the rules. **A violation is a
PR rejection.** They are enforced on every test run by
`tests/test_layer_rules.py`, which parses the imports rather than the prose —
stating a rule nobody checks is how a constitution becomes decoration.

| Layer | May import | Must not |
|---|---|---|
| `core` | nothing inside the package | `parsers`, `rules`, `engines`, `bridge`, `render` |
| `parsers` | `core` | everything else |
| `rules` | `core` | everything else |
| `engines` | `core`, `parsers`, `rules` | `bridge`, `render` |
| `bridge` | itself | the brain — it is a transport, not a caller |
| `render` | `core` | everything else |
| `cli`, `boardwise/__init__` | anything | nothing (this is the assembly layer) |

Two consequences worth stating outright, because both have been violated:

1. **`core` is the bottom.** If `core` needs a helper that lives above it, the
   helper moves *down* or the need is a design error. `core/candidate.py` used
   to import `_transform_point` from `parsers.schematic` inside a function body
   to keep the arrow out of sight; `transform_point` now lives in
   `core/geometry.py` where both `parsers` and `engines` may use it.
2. **A private name (`_helper`) never crosses a layer.** Importing one means the
   boundary is being worked around. A helper two layers genuinely share is part
   of the lower layer's *interface* — publish it there (`field_of`,
   `as_float` in `core/candidate.py` are public for exactly this reason).

### The two layout engines, and the one place that chooses (006b, verified 006c)

`engines` holds two planners and they are **not** interchangeable:

* **golden replay** (`engines/replay.py`) — the default. Re-plays the geometry
  the golden page already contains. Layout is data.
* **generic solver** (`engines/generate.py` + `engines/layout.py`) — the
  fallback, used only when there is no golden layout to replay.

`replay.replay_or_solver(...)` is the **only** chooser. It returns
`(plan, source)` where `source` is `"golden replay"` or `"generic solver"`, the
report prints it, and a fallback is explained in `plan.notes` — a silently
different strategy is what makes a failure unreproducible. `draw.py` must go
through the chooser and never call either engine directly;
`tests/test_engine_boundary.py` holds both properties.

### Where an assembled page comes from (008a)

`engines/assemble.py` composes a page out of block templates and a board spec.
It is **not** a third layout engine: it produces a `DesignModel` and a
`PageLayout` in file coordinates and hands them to the same replay planner, so
an assembled page is validated by the same five hard constraints, the same
annotation lint and the same R5 junction split as a golden replay. What 008a
adds is a *source* of geometry (a block library) and a *composition rule*
(translate the block, name the nets); the plan-building path is untouched.
`docs/blocks.md` is the format and pipeline reference.

## Three coordinate spaces (v0.3, 2026-09-16)

Three spaces coexist and only two of them are ours to convert between. Getting
this wrong produced two separate off-by-sign bugs in 006b, so the rules are
stated as constraints rather than as a convention.

| Space | Units | y axis | Who sees it |
|---|---|---|---|
| **file** | mil (`.epru` stores what it stores) | up, and the sign convention is recorded per record type as measured | parsers |
| **canvas** | page units, 1:1 with file | **down** (`canvas_y = -file_y`) | engines, the editor |
| **mm** | millimetres | — | human-facing reports only |

Rules:

1. **Conversion happens in exactly two places**: at a parser's boundary (file →
   canvas, as the parser hands its result over) and in
   `engines/generate.py::canvas_pin_offsets` (the sanctioned entry point for pin
   geometry). Anywhere else is a bug, not a shortcut.
2. **`engines` never speaks mil.** `mil_to_mm`, `25.4` and `39.37` are forbidden
   in `src/boardwise/engines/**`; the conversion lives in
   `core/geometry.py` (`MIL_TO_MM`, `mil_to_mm`) and is called at the boundary.
3. **`parsers` never speaks canvas.** Identifiers containing `canvas` are
   forbidden in `src/boardwise/parsers/**`. (The *words* are fine in comments,
   docstrings and `.epru` record-type names — `"CANVAS"` is a record type, not a
   coordinate claim.)
4. **A name carries its space.** A variable or parameter holding canvas
   coordinates ends in `_canvas`, and one holding file coordinates ends in
   `_file`. Where the two meet, the suffix is what makes a reader able to check
   the arithmetic instead of trusting it — `canvas_pin_offsets` and
   `part_positions_canvas` exist for this reason alone.
5. **mm is for output.** It may appear in a report string and nowhere else; a
   rule that computes in mm and compares against mil has to convert twice and
   will eventually not.

Rules 2 and 3 are enforced by `tests/test_coordinate_guards.py` (a source scan
via `tokenize`, so comments and format vocabulary do not trip it).

## Adding a bridge action (v0.3, 2026-09-16)

An action touches **five** places. Missing one used to be a runtime surprise —
usually `UNKNOWN_ACTION` on the machine, sometimes a handler nobody could ever
reach — because the Python catalogue and the TypeScript registry were never
compared. Do all five, in this order:

1. **`src/boardwise/bridge/protocol.py`** — an `ACTIONS` entry: `name`
   (`domain.verb`, lowercase; a third segment only inside a declared family such
   as `lib.<entity>.<verb>`), `summary`, `risk`, `owner`, `params`, `returns`.
2. **`connector/src/actions.ts`** — the handler.
3. **`connector/src/actions.ts`** — its registration in `buildHandlers`.
4. **Tests on both sides** — `tests/` for the daemon/protocol side,
   `connector/tests/` for the handler.
5. **`docs/bridge.md`** — the action table.

`risk` is not decoration. `read` cannot change project content, `write` changes
existing content, and **`create`** produces a new document — and only `create`
is gated: the daemon refuses it unless `params.confirm is True`
(`ErrorCodes.CONFIRMATION_REQUIRED`), consuming the flag so it never reaches the
connector. Creating a document is the one thing that must be asked for first.

Then, if the action table changed, **restart the daemon** (`ACTIONS` is read
once at load) and re-install the extension. Getting this order wrong costs a
whole round trip; it has happened three times.

Two guards make the five steps checkable rather than remembered:

* `connector/tests/contract-drift.test.mjs` — the catalogue's connector-owned
  names and the registry's keys must be **set-equal**, both difference
  directions reported. It found a live drift on its first run: a handler
  registered under a name the catalogue had already renamed, unreachable and
  invisible.
* `tests/test_action_catalogue.py` — the catalogue against itself: unique names,
  the naming domain, valid `owner`/`risk`, no duplicate `params`, and every
  `create` action declaring the `confirm` parameter its own gate demands.

## The model-freedom boundary (v0.3, 2026-09-14)

Origin: 岳翔宇's critique — "exemplary prose constraints don't work on models weaker than
the frontier". Agreed. Therefore: **skills and convention docs are specs for code, never
runtime instructions to a model.** The constraint mechanism that works on any model is
*removal of freedom*: deterministic code decides, hard gates reject, the model never holds
a geometric decision at runtime.

| Decisions | Owner at runtime |
|---|---|
| component coordinates, rotation, wire routes, net naming, page geometry | deterministic code only (replay / solver / lint). No model inference, ever |
| connectivity & layout acceptance | hard gates (`compare` per-pin diff, layout lint). A failed gate means zero bridge calls or a rejected artifact — not a model apology |
| strategy choice (replay vs solver, naming mode), which golden to replay from | model may choose; every choice is gated by the same checks |
| authoring/changing harness code | model writes; tests + independent re-verification + 岳翔宇's sign-off gate it |
| novel circuit with no golden source | model proposes structure; placement still compiled rules (block packing, topology templates) — the conventions doc is the *spec for that code*, not a prompt |

Rule for every new feature: state explicitly which decisions remain with the model.
The default answer is "none at runtime". If a feature needs model judgment on the canvas,
the design is wrong — push the decision down into code or gate it.

## Phases

- **P0 Review, file-flow** (underway): .enet connectivity (done), .epro2 geometry (done),
  one-file review (task 002), L2 geometry rules incl. Kelvin sense (task 003).
- **P1 Bridge v0, read-mostly** (task 004): handshake/health, document state readback,
  native screenshot export, on-canvas highlight/markers for findings.
  *Scope discipline: build only what the next engine consumes. No "just-in-case" coverage
  of the 94 official namespaces.*
- **P2 In-editor review UX**: findings annotated on the live canvas; review the open document
  without manual export.
- **P3 Generator**: write actions + milestone gates (canvas + change list + report per gate).
  Bulk offline `.epro2` generation (official format skill + validate.js) as the
  creation path; bridge for incremental/interactive edits.
- **P4 Simulation pipeline**: netlist → ngspice deck → run → spec check (external ngspice;
  editor has no run-and-return API, verified 2026-09-12).
- **P5 Standalone app**: only after a user ecosystem forms.

## Decisions log

- 2026-09-17  **Input understanding starts (008c).** Two pieces of the generator
  stopped being hand-waved. A page may place **one template several times**, and
  both things that then need two names are derived by code: designators (ordinal
  0 verbatim, ordinal *n* offset by a documented stride, an unparseable ref
  refused) and the nets a spec does not connect (scoped to their instance, since
  a copy of a block carries its twin's names — including the internal ones no
  connection can join). Ordinal 0 is untouched, so the 008a spec still assembles
  to the same bytes. And the BOM became an **output**: derived from the spec's
  bindings resolved by C-number against the curated shelf, with three refusals —
  no nearest-match substitution, no silently omitted part, and no picking one of
  two values for one C-number. `docs/blocks.md`.
- 2026-09-16  **The curated part library (008b).** 008c will pick parts, so it
  needs a shelf that does not depend on a model's judgement: `blocklib/parts.json`
  holds verified identities (MPN + LCSC C-number + library device/footprint uuids
  + the library's footprint name + parameters verbatim), each with the
  provenance of the boards it was harvested from. Two policies are code rather
  than advice: the **value gate** (#202 — an explicit `Ω` query must match a
  *named field* numerically, SI prefixes are case-sensitive, an ambiguous or
  unreadable expression fails closed, and no exact candidate means exit code 1),
  and the **footprint vocabulary table**, which is the only mapping allowed
  between a size word (`0402`) and a library name (`R0402`). The online JLC SMT
  comparison is an explicit `--online`, lives Python-side (the webview cannot
  make cross-origin fetches) and sits behind a fetcher seam so tests never touch
  a network. Harvesting reads a **local project** (`.eprj2`) — which required
  correcting 004's finding that a local project carries no library metadata: the
  attributes live in its `attributes` table, which is empty only for a
  project saved as an edit log. `docs/parts.md`.
- 2026-09-16  **A loopback connection must not go through a proxy.** `websockets`
  17 defaults `proxy=True`, i.e. "use `HTTPS_PROXY`/`HTTP_PROXY`/`ALL_PROXY`",
  and `engines/…` dial `ws://127.0.0.1:61190`. Measured with a proxy in the
  environment: the connect went to the proxy and came back
  `InvalidProxyStatus: HTTP 502` — indistinguishable from "the daemon is down"
  while the daemon was fine. `BridgeClient.open` now passes `proxy=None`.
- 2026-09-16  **Block templates and the assembly engine (008a).** A page is
  composed, not solved: `blocklib/blocks/*.json` carry a block's parts, symbol
  geometry, internal wires, parameters and ports; a board spec says which
  blocks, where, with which numbers and how their ports are wired. The engine
  (`engines/assemble.py`) translates coordinates and renames nets and hands the
  result to the *existing* replay planner — no new validator, no new exception
  to R1–R5, and the file→canvas conversion stays in one place. Three things are
  refused rather than papered over: a wire that leaves a cut boundary, two
  circuits that would share a page net name, and a rail port with no flag to
  name it. The block library for the CH340 board is a **board-extract** (source
  3 of the three the architecture lists), so 008a validates the assembly
  mechanism and explicitly not template authoring quality — that is 008c/d.
  `docs/blocks.md`.
- 2026-09-16  **Architecture guardrails (006c).** Three growth axes get guards
  instead of good intentions: (1) the action contract is now compared between
  the Python catalogue and the TypeScript registry on every run; (2) the module
  rules and the three coordinate spaces are stated *and* enforced by
  `tests/test_layer_rules.py` / `tests/test_coordinate_guards.py`; (3) adding an
  action has a five-step checklist. Writing the rules found two live violations
  — `core` importing a private helper from `parsers`, and a connector handler
  registered under a name the catalogue no longer had — which is the argument
  for executable rules over prose ones. Creating a document is now the one
  gated action (`CONFIRMATION_REQUIRED`), enforced at the daemon so the
  connector stays a plain executor.
- 2026-09-16  **Document management is a first-class capability** (`doc.list`,
  `doc.open`, `pcb.doc.new`, `doc.rename`). Until now every action addressed
  "the focused page", and a golden/test page mix-up cost two rounds. Documents
  are now enumerable and switchable by uuid. Deliberately **not** added:
  anything that deletes a document.

- 2026-09-14  Model-freedom boundary codified (岳翔宇: prose constraints fail on non-frontier
  models): geometry/naming/verification are deterministic code with hard gates; models only
  pick strategies and write gated code. Convention docs (e.g. `schematic-conventions.md`)
  are code specs, not prompts.
- 2026-09-12  Bridge moved before generator; renderer descoped (fidelity burden argued by
  岳翔宇: a worse-than-editor renderer is a burden, not a help; canvas is the review UI).
- 2026-09-12  Bridge v0 is read-mostly: review drives it, not authoring.
- 2026-09-12  Daemon in Python (imports engines directly, no second toolchain); connector in
  TypeScript (forced by official extension API). `websockets` becomes the first runtime dep.
- 2026-09-12  File-flow review remains the CI/headless path and the cross-EDA future.
- 2026-09-12  `.eprj2` discovery (岳翔宇 + DeepSeek recon): the editor's LOCAL project
  database (SQLite) is decryptable and contains full document history in .epru record
  form (aes-128-gcm, key stored in the same DB, IV = history uuid, gzip plaintext;
  empty body = deletion; final state = merged history chain). Consequence: live
  read-only review of the *working* project with no manual export. To be productionized
  as an optional parser (task 006) AFTER the CH340 slice; undocumented internals —
  tolerant parsing and read-only access only.
- 2026-09-12  First validation target set by 岳翔宇: a CH340 USB-UART board, redrawn
  end-to-end by the AI from a blank schematic, validated by netlist diff against his
  existing board (golden reference). Power-domain rules (task 003) postponed until the
  plain system-board slice works.
