# Drawing with boardwise (`boardwise draw`, task 006 / 006b)

`boardwise draw` redraws a golden board — currently the CH340 USB-UART
schematic — on a **blank page of the open EasyEDA Pro project**, and diffs what
the editor actually understood against the golden netlist, pin by pin. Zero
differences is the definition of "drawn correctly"; since 006b the drawing also
has to be *readable*, which is why the layout is replayed rather than solved.

This page is the operator manual: what the flow does, what must be measured on
the machine before it can be trusted, and the step-by-step verification
checklist. Protocol details of the actions live in `docs/bridge.md` (the
catalogue is also rendered by `boardwise bridge --help`).

## The flow (006b: layout is data)

```
golden .epro2 ──build_schematic_model──▶ DesignModel   (connectivity, 005)
              └─collect_page_layout────▶ PageLayout    (the human's geometry)
              └─collect_symbol_bodies──▶ bodies        (measured drawn extents)
                    │
                    ▼ engines.replay (pure)
  sch.geometry ─▶ measured sheet frame  ─┐
                    │                    │
                    ▼                    ▼
                ActionPlan  (placements with rotation/mirror, wires, flags, labels)
                    │  self-check: 5 hard constraints + annotation lint
                    │  gate: print plan, human confirms (--yes skips)
                    ▼
   sch.doc.new ─ sch.place_component × N (rotation verbatim)
              ─ sch.doc.save ─ sch.netlist ─▶ core.verify (F2 PLACEMENT GATE)
                   │                              │
                   │                       unmappable part? ──▶ STOP (no wire)
                   ▼                              │
              sch.place_wire ─ sch.place_power (rails) / sch.place_netlabel (signals)
                    │
                    ▼ candidate model (the verified readback is reused)
   sch.netlist (preferred) ─▶ parse  ── otherwise ──▶ sch.geometry ─▶ parse
                    │
                    ▼ core.compare (005 + F4 identity maps)
        per-pin diff + `boardwise lint` table + `export.render` acceptance image
```

**The placement gate (revision 4).** The replay copies the golden's wire
endpoints on the assumption that the library resolves to *the same symbol*. In
round 4 it did not — a 0402 became a 0603, a 470 Ω part became a 1 kΩ one, and
USB1's pins were renumbered — and every replayed endpoint missed its pin, so
the whole page was 51 differences with no drawing error behind them. Since
0.3.8 the flow therefore reads the page back **after placement and before any
wire**, maps each part's pins to the golden's (by number, else by **name** —
`core/verify.py`), and:

* **refuses to draw** when a part cannot be mapped (fail fast: a broken page
  costs nothing but a refusal);
* **remaps the comparison** for a part whose numbering drifted with the library
  (`compare_models(..., pin_maps=...)`), so a renumbered part is compared
  pin-for-pin instead of reporting every pin as a difference;
* **continues unverified** when the netlist export returns nothing — *not
  knowing* is deliberately kept distinct from *knowing it is broken*.

**Honest limit.** There is no API that returns a *placed* symbol's pin
geometry (`sch_PrimitivePin.getAll()` is empty on a schematic page, a
component's `Symbol` state is an empty object, `lib_Symbol.get` is metadata
only, and the geometry dump's `pins` is empty). Endpoints are therefore still
replayed at the **golden** pin tip: exactly right when a redraw kept the pad
positions (only the numbering moved), and caught by the gate when the mapping
cannot be built at all. See `tasks/006b-schematic-readability.md` §I-3.

**The decision that fixed 006.** The 006 solver's output was judged
"completely unusable" (wires crossing parts, no zoning, off the frame). The
answer was not a better solver: the golden `.epro2` already holds a human's
placement — every COMPONENT's `x/y/rotation/mirror`, every WIRE's segments,
every visible net-label anchor — so the default plan **copies it** onto the new
page, inheriting zoning, orientation and spacing. The generic solver in
`engines/layout.py` stays as the fallback for boards with no reference
geometry, and `boardwise draw --solver` forces it.

## Coordinate contract (rewritten by task 010c, 2026-09-18)

| Space | Convention |
|---|---|
| editor canvas | **y up**, x right — measured by a two-marker test, GUI-confirmed |
| `.epru` page as stored | **y down** — measured: `stored_y = -canvas_y` on 35 of 42 parts |
| our file space = canvas | **y up**, x right |

**One negation, at one boundary.** The parser negates the stored y as it hands its
result over (`parsers/schematic.py::_page_y` / `_page_box`); everything past that
point — replay, layout, the candidate builders, the plan — is canvas space and
negates nothing. The earlier revision of this table had the canvas and the file
labels the wrong way round, which is what made hand-authored geometry come out
vertically mirrored while the golden replay stayed self-consistent (two
negations cancelling). `engines/generate.py::canvas_pin_offsets` survives as the
named checkpoint for that boundary and is now an identity.

Pin offsets rotate **counter-clockwise** — the file's own convention, restored in
`core/geometry.py::transform_point` — and then mirror across the vertical axis;
the instance origin is added last. Note that the *editor API* turns clockwise, so
`engines/draw.py::_editor_rotation` negates the angle when it hands it over: the
file's angle and the API's angle are opposite, and the two ends of that pair must
be changed together (010c's appendix B moved one and broke the golden). The page
offset is snapped to a 5-unit lattice so pin tips keep the grid the wire endpoints
share.

A replay is therefore byte-exact apart from one integer page translation — and
the self-check proves it: a replayed part's rotated pin tip must land on a
replayed wire (`test_replay.py::test_every_replayed_pin_tip_lands_on_its_own_wire`).

## The sheet frame is measured, never assumed

- **Frame**: the focused page's sheet primitive bbox, via `getPrimitivesBBox`
  (the sheet's `getState_*` fields carry an anchor, not an extent, so
  `Width`/`Height` would have to be *trusted* from the file — they are used only
  as a provenance-tagged fallback, and when neither is available the replay
  **refuses** instead of inventing an A4).
- **Title block**: carved from that bbox by the A-series-landscape ratio the
  reference implementation also uses (0.6 x 0.24, bottom-right), cross-checked
  against a rendered page. It is a *keep-out*, and it is deliberately
  conservative (larger than the real block).
- **Offset**: centred in the drawable area, then shifted left/above the title
  block if centring would land on it, then clamped inside the frame. Every
  deviation is a `note` in the gate output — a silent clamp is a lie about what
  the picture will look like.

## Names: labels for signals, flags for rails

岳翔宇's rule: **signal nets are named with net labels; I/O ports are banned**
(`sch.place_netport` stays in the catalogue for the solver's last resort, but
the replay never emits one). Power/ground rails keep the standard flag drawing.

`sch.place_netlabel` is **timeout-bounded and self-reporting**:

- the call races an 8 s deadline (`timeoutMs` may shorten it, 200..30000 ms);
- when it does not settle, the handler **reads the attribute list back** before
  failing, and says in the error whether a `NET` attribute for that name
  appeared anyway. The reference lesson: a timed-out call may well have created
  the marker, and a blind retry stacks duplicates;
- the result or the error always carries `elapsedMs` and `landedAnyway`.

**Measured 2026-09-14 on 3.2.186.b52e3e87** (see
`tasks/006b-netlabel-finding.md`): the call hung for 6963 ms against a 6000 ms
bound and **nothing landed** (`landedAnyway: false`, `matches: 0`). The cause is
in the type package, not the host: `createNetLabel` is documented **"ADD since
EDA v4"** and this host is the v3.2 line — so it is not flaky here, it is a call
that can never settle. The timeout is what turns that into a reportable failure
instead of a dead action slot.

The type package has **no path for a *connectivity-bearing* signal-net name**:
`createNetFlag` accepts only `Power / Ground / AnalogGround / ProtectGround`, and
`sch_PrimitiveNetLabel` is not a namespace on this host. The only visible form
the package offers is `sch_PrimitiveText` — a decoration with no connectivity.

## Naming strategies (006b revision 3)

岳翔宇's rule is fixed: **signal nets are named with a visible label, never an
I/O port**; power and ground keep their flags. What varies is *how* the visible
name is realised, so the generator carries a switch (default `text`):

| Strategy | Wire carries the net? | Signal name primitive | Status |
|---|---|---|---|
| `wire` | yes (`WireStep.net`) | none | **verified** — measured 2026-09-14: the editor's netlister honours the wire's own net attribute (3 resistors + a wire tagged `PROBE_WIRE_NET` → `R1.2/R2.2/R3.1 → PROBE_WIRE_NET` in `getNetlistFile`) |
| `text` | yes | `sch.place_text` (`sch_PrimitiveText`) | **default** — visible, but decorative; every report line says so |
| `label` | yes | `sch.place_netlabel` (`createNetLabel`) | **dormant** — documented *v4*, never settles on 3.2.186; kept behind its timeout |
| `none` | no | none | for a bare-connectivity run |

`boardwise draw --naming <strategy>` and `boardwise lint --naming <strategy>`
select it; an unknown value falls back to the default **and the fallback is
reported**, never silent. The gate printout and the acceptance report both name
the strategy, and the `text` strategy carries an explicit
"(decorative, NOT native net labels)" disclaimer.

The golden replay lints clean (**0 violations**) under all four strategies. That
is a deliberate invariant, not a coincidence: the human's wire ends where the
human's label sits, so the validator's legal terminals include the golden
page's flag / label anchors regardless of whether the current strategy draws a
name there. Deriving them from the plan's naming steps alone made the two
strategies that draw no name report ten phantom `ENDPOINT_NOT_TERMINAL` rows.

## Two design sources (008a added the second)

| Source | Flag | The design comes from | The diff answers |
|---|---|---|---|
| golden replay | `--from <golden.epro2>` | the golden page's own layout (006b) | "did we draw what the golden has?" |
| **assembly** | `--spec <board spec>` | block templates + a spec (`docs/blocks.md`) | "did we draw what the **specification** says?" |

With `--spec` the spec first passes the **product validation gates**
(009-M0 P0, `docs/validate_spec.md`: sources, levels, power tree, and pin
budget when a table is given) before anything is assembled — a refused spec
draws nothing, the bridge is never opened, and the report's `spec sha256:`
prefix binds the verdict to the exact bytes that were checked (nothing is
cached; an edited spec is re-judged on the next run).

With `--spec`, `--golden` turns on the **double check** that runs before a
single bridge call: `compare` the assembled spec netlist against the golden
(fixture plus its correction sidecar). A mismatch aborts the run, so a wrong
specification cannot mutate a project. `boardwise lint --spec …` and
`boardwise compare --spec …` are the same two checks without an editor.

`compare` applies a corrections sidecar **only when `--overrides` names one**
(its task-005 contract is a raw file-against-file comparison); `draw` keeps
defaulting to the sidecar beside the fixture, as it always has.

## The acceptance image is a document render

`export.render` calls `sch_ManufactureData.getExportDocumentFile(fileName,
fileType, typeParams, object)` — a *document* render. `export.screenshot`
(`getCurrentRenderedAreaImage`) returns **cached frames** on this host (the
reference measured two byte-identical captures across different board states),
so it stays available as a diagnostic of the viewport and is never evidence.
`format: png|svg|pdf` (default png) selects the render type — svg is the
vector, zoomable option — and `scope: page|selection|project` (default page)
selects what is rendered; `scope: 'selection'` requires `ids` and selects the
primitives first. A multi-page project can come back as a zip; the action
reports `format: 'zip'` rather than saving an archive with a `.png` name.

**Ported 2026-09-18** from the reference's live-verified `schematicExportImage`
(reference issue #166). Before that, this action targeted `getPngFile`, which
answers `NOT_IMPLEMENTED` on this host even though the package marks it *added
in v3.2.183* and the host reports 3.2.186. One trap the type package cannot
warn about: the `object` argument must be the literal strings `'Current
Page' | 'Current Page Selected Items' | 'Project'` — the values the `.d.ts`
declares make the host promise never settle (a stuck 1% toast), which is why
the connector races the call against a 30 s deadline and its timeout error
says to reload the document to clear the toast.

## Offline lint (self-produced detail)

`boardwise lint --from <golden.epro2> [--plan replay|solver] [--json]` runs the
whole plan — layout, routing, naming — with **no bridge and no editor**, and
prints one row per violation plus a tally:

| Code | Meaning |
|---|---|
| `BOX_OVERLAP` | two parts' measured drawn extents intersect |
| `OUT_OF_SHEET` | a part's box leaves the measured frame |
| `PLACEMENT_ON_TITLE_BLOCK` | a part's box enters the title block |
| `WIRE_THROUGH_BOX` | a wire's interior crosses a part's box |
| `NON_MANHATTAN` | a diagonal segment |
| `WIRE_OUT_OF_SHEET` / `WIRE_ON_TITLE_BLOCK` | a wire endpoint outside / on the block |
| `ENDPOINT_NOT_TERMINAL` | a wire end that is neither a pin tip, a junction, an annotated end, nor a short overhang |
| `CROSS_NET_SHORT` | one net's endpoint lands on another net's wire (the editor junction-dots it) |
| `LABEL_FLOATS` | a flag / label not on any of its own wires |
| `LABEL_ON_COMPONENT` | an annotation box overlaps a foreign part |
| `LABEL_OVERLAP` | two annotation boxes intersect |
| `LABEL_ON_TITLE_BLOCK` | an annotation inside the title block |

`boardwise draw` runs the same lint as part of its self-check and **refuses to
execute** when anything fails — the whole point is that the burden of proof
moved from the reviewer's eyes to the generator.

Parts are bounded by their **measured drawn geometry** (`collect_symbol_bodies`:
the symbol's `RECT`/`POLY`/`CIRCLE` records), not by their pin extents. This is
not cosmetic: with a pin-extent box inflated by 20 units, the human's own
decoupling capacitors register as 19 overlapping pairs, and the wires reaching
their IC register as 25 crossings. With the drawn extent and zero pad, the
human's board lints clean — which is the calibration that makes the lint
trustworthy at all.

## Machine probe (006b additions)

Prerequisites: connector **0.4.2** sideloaded, daemon restarted (the action
catalogue grew — a stale daemon answers `UNKNOWN_ACTION`), editor open on the
project to draw into.

```bash
# 0a. what does the editor's API actually expose? (read-only, always first)
#     NAMED reads — immune to the exotic host objects that killed the first
#     enumeration run with "reading 'prototype'". `checks: true` verifies the
#     type package's declared surface for the namespaces the roadmap uses; the
#     table is generated by tools/api_names.py into connector/src/api-names.ts.
PYTHONPATH=src python -m boardwise.cli bridge call --action sys.probe \
    --params '{"checks": true}'
#   -> checks: {<ns>: {present, checked, missing, status: {member: typeof},
#                      arity: {member: fn.length for the functions}, notes?}}
#   `status` uses the language's own vocabulary — function / object / undefined —
#   plus `threw: …` and `namespace-absent`, so "undeclared" and "the read itself
#   failed" stay distinguishable. `arity` is the declared `fn.length`, reported
#   for the members that are functions — a hint, not a verdict (a wrapper loses
#   the real arity). A method the package marks `ADD since EDA v…` that reads
#   back `undefined` gets a `notes` entry carrying the contradiction.
#   Exit is 0 whether or not names are missing — an answer is the product.
#   Looking for: getExportDocumentFile on sch_ManufactureData (the render path
#   since 0.4.2), and the page/tab switch on dmt_EditorControl / dmt_Schematic.

# 0b. enumerate when you need a name nobody predicted (predictive, but it can
#     fail on a hostile object; one bad level costs one `errors` line, not the call)
PYTHONPATH=src python -m boardwise.cli bridge call --action sys.probe \
    --params '{"namespaces":["sch_ManufactureData","dmt_EditorControl","dmt_Schematic"]}'
#   -> namespaces: {<ns>: {present, ownNames, functions, data, errors?}}

# 1. the measured frame (sheet bbox + which namespaces exist)
PYTHONPATH=src python -m boardwise.cli bridge call --action sch.geometry > frame.json

# 2. does the wire's own net name stick? (this is the `wire` strategy's basis)
PYTHONPATH=src python -m boardwise.cli bridge call --action sch.doc.new
PYTHONPATH=src python -m boardwise.cli bridge call --action sch.place_wire \
    --params '{"points": [[0, 100], [200, 100]], "net": "PROBE_NET"}'
PYTHONPATH=src python -m boardwise.cli bridge call --action sch.geometry

# 3. the net-label probe: bounded, and it reads back what landed
PYTHONPATH=src python -m boardwise.cli bridge call --action sch.place_netlabel \
    --params '{"x": 200, "y": 100, "net": "PROBE_NET", "timeoutMs": 8000}'
#   outcome ok / elapsedMs / landedAnyway       -> the label path works
#   TIMEOUT + landedAnyway true                 -> it landed; the API just never answers
#   TIMEOUT + landedAnyway false                -> no label path on this host

# 3b. the decorative text fallback (the default `text` strategy uses this)
PYTHONPATH=src python -m boardwise.cli bridge call --action sch.place_text \
    --params '{"content": "PROBE_NET", "x": 200, "y": 80}'

# 3c. placement: a first library resolution can exceed 30 s and STILL land.
#     The action reads the page back and says so — never retry on TIMEOUT.
PYTHONPATH=src python -m boardwise.cli bridge call --action sch.place_component \
    --params '{"lcsc": "C14267", "x": 300, "y": 300, "designator": "U9"}'
#   ok                     -> {uuid, device, resolvedBy, elapsedMs}
#   TIMEOUT landedAnyway   -> true: it is on the page, do NOT resend
#                            false: nothing appeared; `near` lists what is close by

# 4. the acceptance render (format png|svg|pdf, scope page|selection|project;
#    selection needs ids; svg is the zoomable option for the readability gate)
PYTHONPATH=src python -m boardwise.cli bridge call --action export.render
PYTHONPATH=src python -m boardwise.cli bridge call --action export.render \
    --params '{"format": "svg", "scope": "page"}'
```

## Acceptance (three gates, all three required)

1. **`compare` per-pin: 0 differences** — the existing 005 referee, printed by
   the draw report (`no differences — designs match`).
2. **Self-produced lint: 0 violations** — printed before and after the run;
   `boardwise lint` reproduces it offline.
3. **岳翔宇 reads the `export.render` image** and judges it readable — the
   human gate the solver failed. The viewport screenshot is not evidence.

Verification steps:

1. Stop anything on 61190 that is not the current daemon (`netstat -ano |
   grep 61190`), then `boardwise bridge start`.
2. Sideload connector **0.4.2**, restart the editor, open the **test** project,
   `boardwise bridge status` must say `connector: connected`.
3. `boardwise lint --from tests/fixtures/ch340_golden.epro2` → `0 violations`.
   (Offline, no editor — do this first.) Repeat for `--naming wire|label|none`:
   all four must be 0, because the human's geometry does not depend on our
   naming policy.
   **Task 008a adds the assembled path**, also offline:
   `boardwise lint --spec blocklib/specs/ch340g_usb_uart.json` → 0 violations,
   and `boardwise compare --spec blocklib/specs/ch340g_usb_uart.json --golden
   tests/fixtures/ch340_golden.epro2 --overrides
   tests/fixtures/ch340_golden.overrides.json` → `no differences`.
4. Create a fresh page **after asking 岳翔宇** (new rule: never create a page
   unprompted), then `boardwise draw --from tests/fixtures/ch340_golden.epro2
   --render out.png` (default `text` strategy) — or, for the 008a acceptance,
   `boardwise draw --spec blocklib/specs/ch340g_usb_uart.json --golden
   tests/fixtures/ch340_golden.epro2 --render out.png`. Do **not** draw into
   P1 — the
   probes above left primitives on it. Read the gate output: plan source
   `golden replay`, the measured frame, the offset note, 17 placements with
   their rotations, the naming line, 45 wires.
   In `--spec` mode the report opens with the assembly (each block, where it
   went, every port and connection) and with the double check's verdict.
   If the netlist export fails and the flow falls back to geometry, the report
   prints a **page census** (`page census (netlist failed): <type>=<n>, …`) —
   that is what tells "a net-port poisoned the exporter" apart from "our parser
   is wrong". Report the census; do not guess.
5. The report prints the candidate source, the **placement check** line, failed
   actions, then the per-pin diff. Read the placement check first:

   ```
   placement check: 17 parts, 0 drifted with the library version, 0 unmappable
   ```

   `0 unmappable` is the pass mark — anything else means the flow **stopped
   before drawing a single wire** and printed why (`✗ unmappable parts …`).
   A non-zero **drifted** count is not a failure: it means the library redrew
   those symbols, the diff is being compared by pin name, and the wire
   endpoints stay at the golden pin tips (see the honest limit above).
   If the netlist export failed and the flow fell back to geometry, the report
   prints a **page census** (`page census (netlist failed): <type>=<n>, …`) —
   that is what tells "a net-port poisoned the exporter" apart from "our parser
   is wrong". Report the census; do not guess.
6. The diff below it: **0 differences** is the pass mark.
7. Open `out.png` and read it as a schematic: zoning inherited from the golden,
   wires orthogonal, every rail flagged, every signal name on its wire. The
   `text` strategy's names are decorative — if the readability gate rejects
   disguised text, flip to `--naming wire` and re-run: zero rework, the wire
   already carries the net.

## Persistence: the facts about a write (M0-P0d, extended 2026-09-18)

"The write API said ok", "the editor's page is right" and "the file kept it" are
different facts. The report names which one it established, and prints the state
with its qualifier attached:

| state | established by | meaning |
|---|---|---|
| `not_placed` | zero write attempts acknowledged | the page was never touched |
| `unknown` | the run stopped with writes acknowledged or unanswered | what is on the page **cannot be stated** |
| `placed` | the netlist compare | written, and the editor's own readback agrees. **Not saved** |
| `saved_unverified` | a `sch.doc.save` that answered ok | the editor accepted a save; nothing checked the disk |
| `saved_verified` | a close-and-reopen that compares equal | the content reached the file |

`unknown` is not a weaker rung on the ladder — it is the statement that the
ladder cannot be climbed. It exists because of a measured defect: killing the
daemon mid-draw left **five parts on the page** while the report said "nothing
was written". A reader who believed that would redraw onto a page that already
had them, ending with two sets of parts on one sheet. So the one state that
asserts an *absence* requires positive evidence of the absence: zero write
attempts acknowledged **and** zero unanswered.

Two properties are structural, not oversights:

* **`draw` tops out at `saved_unverified`.** `saved_verified` needs a reopen, and
  the bridge cannot perform one: `doc.open` is a `read` that moves the focused tab
  without reloading it from disk, and there is no close-project action in the
  catalogue. The report therefore says "NOT verified on disk" out loud rather than
  borrowing the word "saved" for a state it never reached.
* **A failed write is not "nothing happened", in either of its two shapes.** A
  **timeout** means the daemon stopped waiting without telling the editor to
  cancel; a **disconnect** means the answer never arrived because the connection
  died in flight. Both leave the outcome unknown, so every write the flow issues
  goes through a timeout-aware wrapper: on either failure it reads the page back
  (`sch.geometry`), reports what it saw — or that it **could not look**, which is
  not the same as "it is empty" — and never re-issues the call, because a retry
  after a write that landed is a duplicate part. Transport deaths are normalised
  into `BridgeError(DISCONNECTED)` by `bridge/client.py`, the one layer that knows
  about `websockets`.

The exit code for an unknown outcome is **3** ("cannot say"), distinct from 2
("nothing was executed"), and it **outranks both 0 and 1**: "the diff happened to
match" and "the diff differed" are claims about a page whose contents we are no
longer sure of.

The third state is reachable only through a human step, and
`boardwise persistence` turns that step's result into an exit code —
see `docs/persistence-baseline.md` for the four-scenario checklist.

## Known limits (006b scope)

- The replay reproduces the golden's *drawing*, so it inherits the golden's own
  quirks (a 4-unit overhang past one VCC junction, unlabelled local nets). The
  lint's tolerances are documented next to the codes; nothing is silently
  "fixed" away, because a replay that edits the source is no longer evidence.
- The title block is a ratio-derived keep-out, not a measured rectangle: the
  API exposes no title-block bbox. It is conservative, and a violation inside it
  is reported with that provenance.
- Annotation marker boxes are predictions (flag glyph = measured symbol body +
  a text band; labels = 6 units per character). The reference implementation's
  rule applies: generation and checking must use the same ruler, which they do.
- Rotation is replayed verbatim; a host that applies `rotation` differently from
  the file would show up immediately as a per-pin diff (and as a failed pin-tip
  invariant in the self-check).
- No PCB anything (task 007). The generic solver remains for boards without
  reference geometry, and is still "legal but ugly" by design.
