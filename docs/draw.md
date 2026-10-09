# Drawing with boardwise (`boardwise draw`)

Two flows share this command family:

- **The drawing compiler (053–074, the main line).** You state circuit intent —
  a `CircuitSpec` (what the circuit is) plus a `PresentationSpec` (how a human
  should read it) — and `draw compile` turns it into ranked `LayoutPlan`s
  offline, behind an independent readability gate; `draw plan` / `draw apply`
  land one into the open editor, and `draw discard` takes it back off.
  Grammars today: voltage divider, RC low-pass, LDO; several modules compose
  onto one page. See **The compiled page** below and `docs/architecture.md`;
  the drawing rules it enforces are `docs/schematic-conventions.md` R6–R10.
- **The golden replay (006/006b, this document's original flow).** Redraws a
  golden board — currently the CH340 USB-UART schematic — on a **blank page of
  the open EasyEDA Pro project**, and diffs what the editor actually
  understood against the golden netlist, pin by pin. Zero differences is the
  definition of "drawn correctly"; since 006b the drawing also has to be
  *readable*, which is why the layout is replayed rather than solved.

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

xianyuyijinban's rule: **signal nets are named with net labels; I/O ports are banned**
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

## Naming strategies (006b revision 3; default changed by 134, 2026-10-08)

xianyuyijinban's rule is fixed: **signal nets are named with a visible label, never an
I/O port**; power and ground keep their flags. What varies is *how* the visible
name is realised, and — since 134 — *whether* one is placed at all.

**Why this stopped being a cosmetic choice.** In EasyEDA Pro a net label is
equivalent to a network port: drawing one **creates an electrical connection**.
So labelling every signal net was not "a bit busy", it was burying implicit
connections all over the page *and* masking routing mistakes. An engineer's
complaint that the AI-drawn flyback came back as a screenful of network
identifiers smeared over parts and wires is precisely this.

| Strategy | Wire carries the net? | Signal name primitive | Status |
|---|---|---|---|
| `wire` | yes (`WireStep.net`) | none | **verified** — measured 2026-09-14: the editor's netlister honours the wire's own net attribute (3 resistors + a wire tagged `PROBE_WIRE_NET` → `R1.2/R2.2/R3.1 → PROBE_WIRE_NET` in `getNetlistFile`) |
| `auto` | yes (`WireStep.net`) | only on long or cross-page nets | **default** (134) — see below |
| `text` | yes | `sch.place_text` (`sch_PrimitiveText`), one per signal net | was the 006b default; visible but decorative, and every report line says so |
| `label` | yes | `sch.place_netlabel` (`createNetLabel`) | **dormant** — documented *v4*, never settles on 3.2.186; kept behind its timeout |
| `none` | no | none | for a bare-connectivity run |

### `auto`: a name only where a name is the only way to read the net

A signal net is named on either of two grounds (岳裁 2026-10-08，长距离/跨页才打):

1. **long distance** — its routed wire runs past `LONG_NET_LABEL_UNITS`
   (1500 canvas units ≈ 38 mm at 1 unit = 1 mil). The threshold answers *how
   far can a reader follow a net*, not how tidy the page looks: past roughly a
   third of an A4 landscape sheet a net has to be traced, and tracing is what a
   name saves. It is a **house rule pending confirmation of the exact number** —
   one named constant in `engines/generate.py`, so moving it moves the policy
   for every page at once. Measured on the CH340G golden board the longest
   signal net runs 1395 units, i.e. *just under* the threshold, so that page
   now carries rail flags only.
2. **cross page** — the net's members sit on more than one sheet
   (`DesignModel.unproven_nets`; an empty page tuple counts too, because it
   means "seen twice, page ids unavailable" — issue #19).

Everything else is read off its wires, as a schematic is meant to be read. The
**wire still carries the net name** under `auto`: the ruling removes the visible
decoration, never the electrical name (measured 2026-09-14 — the editor's own
netlister reads the wire's net attribute).

### Where a placed label is allowed to land

Every label that *is* placed goes through `layout.clear_label_point`, which
walks the on-wire candidates of *that* net — never off it, because a name off
its wire is a floating marker rather than a name — and scores each by the
clearance its predicted text box has from every foreign component box, every
foreign wire, and every name already placed. When nothing along the route
clears the bar, the plan records that in `notes` instead of dropping a label
somewhere it reads as a smudge: a nameless net is legible, an unreadable one is
worse than either.

`boardwise draw --naming <strategy>` and `boardwise lint --naming <strategy>`
select it; an unknown value falls back to the default **and the fallback is
reported**, never silent. The gate printout and the acceptance report both name
the strategy, and any strategy that draws a text name carries an explicit
"(decorative, NOT native net labels)" disclaimer.

The golden replay lints clean (**0 violations**) under all five strategies. That
is a deliberate invariant, not a coincidence: the human's wire ends where the
human's label sits, so the validator's legal terminals include the golden
page's flag / label anchors regardless of whether the current strategy draws a
name there. Deriving them from the plan's naming steps alone made the two
strategies that draw no name report ten phantom `ENDPOINT_NOT_TERMINAL` rows.
On the replay path `auto` decides **whether** a golden label is drawn; the
human's own anchor still decides **where**, because a replay that moved the
human's labels would not be a replay.

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
| `WIRE_TOO_CLOSE` | two nets' wires running **alongside** each other closer than `WIRE_CLEARANCE` (136) |
| `SEPARATION_GIVEN_UP` | a net that only routed after the retry dropped the router's wire-separation preference (136) |
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

# 3b. the decorative text fallback (the `text` strategy uses this; the `auto`
#     default only places one when a net is long or cross-page)
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
3. **xianyuyijinban reads the `export.render` image** and judges it readable — the
   human gate the solver failed. The viewport screenshot is not evidence.

Verification steps:

1. Stop anything on 61190 that is not the current daemon (`netstat -ano |
   grep 61190`), then `boardwise bridge start`.
2. Sideload connector **0.4.2**, restart the editor, open the **test** project,
   `boardwise bridge status` must say `connector: connected`.
3. `boardwise lint --from tests/fixtures/ch340_golden.epro2` → `0 violations`.
   (Offline, no editor — do this first.) Repeat for
   `--naming auto|wire|text|label|none`: all five must be 0, because the
   human's geometry does not depend on our naming policy.
   **Task 008a adds the assembled path**, also offline:
   `boardwise lint --spec blocklib/specs/ch340g_usb_uart.json` → 0 violations,
   and `boardwise compare --spec blocklib/specs/ch340g_usb_uart.json --golden
   tests/fixtures/ch340_golden.epro2 --overrides
   tests/fixtures/ch340_golden.overrides.json` → `no differences`.
4. Create a fresh page **after asking xianyuyijinban** (new rule: never create a page
   unprompted), then `boardwise draw --from tests/fixtures/ch340_golden.epro2
   --render out.png` (default `auto` strategy — signal nets are named only
   when long or cross-page) — or, for the 008a acceptance,
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
| `saved_verified` | a close-and-reopen in which the snapshot's content is all still present (content added afterwards is reported as extras, not failed) | the content reached the file |

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
  into `BridgeError(DISCONNECTED)` by the layer that owns the transport:
  `bridge/client.py` when the daemon connection dies, and `bridge/daemon.py`
  when the editor's window closes while the call is already on the wire (#43 —
  reporting that second case as `CONNECTOR_ERROR` is what used to make an
  in-flight write read as `not_placed`).

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

## The compiled page (057: `draw compile|plan|apply` on a page, `draw discard`)

054 landed one compiled module; 056 compiled several modules into one page
offline; 057 lands that page. There is **no new landing command and no new
flag** — the three `draw` commands take a page on the same flags:

| input | `draw compile` | `draw plan` | `draw apply` |
|---|---|---|---|
| a presentation with ≥2 modules, a `flow`, a module `grammarRef` or a page lock | page compiler; `candN.page.json` + framed `candN.svg`; `--page-box` required | the chosen page's `plan` field → the same `draw-module` plan; `<plan>.page.json` written beside it | — |
| a page document (`kind=boardwise-page-layout-plan`) | — | — | as `--layout` (digests its `plan`), or as the positional (needs `--circuit/--presentation/--profiles` and `--page`/`--new-page`; the plan is built at apply time) |

**A non-empty page** (`draw plan --page`): every primitive already on the page
(part, wire segment, flag, net label — parts and labels at their `bboxIds`-measured
extent, anything unmeasured at an assumed ±50 box the notes name) becomes a
keep-out, and the arrangement moves off them as a rigid body
(`PageCompileBudget.relocate_around_keepouts`; nothing is squeezed). A page the
census fills is `presentation-poor`, the keep-out named by what it is ("existing
R5 c-17"). After the landing, **every primitive that was on the page before is
compared field by field** (designator, value, LCSC, net, origin, pose; a wire's
point list; a label's net, text and pose) — one changed item is exit 2 and no save
(`range.outOfScope`). This applies to every `draw apply`, single module or page.
The C5 digest behind all of this counts every section a `sch.geometry` dump is
contracted to carry (`components`/`wires`/`pins`/`netlabels`) plus the parts the
designator set deliberately drops (`R5?`): a kind the census does not count is a
change no guard can see.

**Page locks**: a `userLocks[]` entry with `"scope": "page"` (x, y only — the pose
is the module's) pins the part to that page point in every candidate: the
module's origin is `P − L(generation)`. A lock point off the page, two locks in
one module that disagree, a locked frame off the page / on a keep-out / on
another locked frame are `presentation-poor` naming the lock(s). A module lock
and a page lock may sit on the same part.

**Shared nets (G4)**: a net that spans modules is named at each end (label or
flag); this host cannot place a net label, so a label whose point no planned wire
reaches becomes a 10-unit **named stub** (declared in the plan's downgrades) —
otherwise the pin sits on an unnamed net and the two modules' same-named nets
never merge in the editor's project-wide netlist. The apply report's
`verification.nets` lists every net's live name(s), `crossModule` and `oneNet`;
findings may only shrink, judged by identity (`rule|severity|designator|pins|named
nets`), never by count.

**`draw discard <plan.json|page.json>`** takes one landed drawing back off its
page, and only that: a part is the plan's by designator + position + value (the
LCSC number for a pre-055 plan), a flag by net + point, a wire by net and *every*
point lying on the plan's own wiring (a primitive the host merged with somebody
else's wire, pit 32, is never deleted). One mismatch refuses the whole batch
(exit 4, nothing deleted). Lines go first, then flags, then parts (≤30 ids per
call, a split is reported); the page is read back — targets gone, everything else
unchanged. A second run answers `nothing_to_discard` (exit 0). `--save` saves; a
timeout is read back and never retried (exit 3). A page document is discarded
with `--circuit/--presentation/--profiles`, its parts found by position, prefix
and value.

Offline evidence: `tools/057_scenarios.py` (writes `outputs/057_offline/`); the
real-machine steps for E1–E7 are `tools/057_live_runbook.md`.

## Flag and naming rules on compiled pages (060–074)

After 057 landed pages, xianyuyijinban ruled five drawing conventions on the
live renders; they are compile-time hard constraints, written up as R6–R10 in
`docs/schematic-conventions.md`. The visible consequences on any compiled page:

- capacitors hang on their owning pin's physical side (input cap by the input
  pin, output cap by the output pin — even when the symbol duplicates the pin
  on the far face);
- same-role pins on opposite faces of a body join **by name** (a short stub
  with a flag or label each), never by a wire across the part;
- every power net carries at least one flag, flags are always vertical
  (0°/180°), and a wire on a flagged net carries no text name of its own;
- a flag lead never crosses a foreign net's conductor — the compiler rejects
  such a candidate outright and reports `layout-unsat` rather than shipping a
  crossing.

The apply report's `verification.nets` and the readability evidence are what
prove these held; the renders under `evidence/074/` show the before/after.


## 落图 SOP（自 SKILL.md §3.3 迁入，2026-10-06 减重 124）

053 阶段 B 的编译器离线算出**画法**（`LayoutPlan`：器件+姿态+折线+旗标+文字 bbox，
`engines/drawcompiler.py`），054 把一张画法落进编辑器的一页。三条命令：

```bash
boardwise draw compile --circuit C.json --presentation P.json --profiles LIB.json \
    --page-box 0,0,1170,825 --out outputs/054_x/previews      # 离线：ranked 表 + 四分类 + SVG
boardwise draw plan    --circuit … --presentation … --profiles … --page-box … \
    --page <uuid> --project test --lcsc R1=C25744 --out plan.json   # 一候选 → ChangePlan
boardwise draw apply   plan.json --project test \
    --circuit … --presentation … --profiles … --layout <cand1.layout.json> \
    --render render.png --json apply.json                     # 真机：守卫 → 落图 → 回读 → 保存 → 出图
```

同族另外两条，别漏：**`boardwise draw lint --page …` 是落图之后的机器闸**（只读：九条几何
谓词——压线/重叠/出界/同名导线段等，111 起；真机快照或 `--snapshot` 捕获件都吃。
P1 的 48E/20W/21I 验收基线就是它量的——**画完一页先过它再交付**）；
**`boardwise draw propose`**（109 A4，纯离线）把一份 DesignIntent 合同提成
PresentationSpec 草稿（模块清单 + flow + 角色），是「意图 → 画法」这条链的入口，
compile/plan 的 `--intent PATH` 消费同一份合同（见下）。

**支路顺序的三个来源（095 A4 起）**：`power-entry` 画法里「哪条支路贴入口」按
`PresentationSpec.modules[].branchOrder` > **DesignIntent 合同** > 位号序 读；后两者都
没说话时与 088/088b 逐字节一致。合同侧读 `decisions[subject=<支路>]` 的 prose 或
`blocks[].kind`（写明 `tvs`/`clamp`·`钳位`/`泄放` 才算），原文 + 出处 + provenance 进
绑定 evidence，`ai_asserted` 照走但标注草稿。**声明与合同不一致 → `circuit-invalid` 拒绝、
两个来源的原文并列**（谁错人裁，不会自动二选一）。`draw compile` / `draw plan` 用
`--intent PATH` 把合同交给编译（`dc.compile(..., intent=…)`）；**只认显式路径**——编译发生在
读工程之前，用户级默认落点 `<home>/design-intent/<projectUuid>.json` 那时还没有 uuid；
页级（057）路径本批不读合同，给了 `--intent` 会明说没读。

**落图前必须先有"实测符号库"**（本批最关键的一条工序，C1/C2 都是这么过的）：
编辑器**不提供**库符号几何的读接口（`lib.symbol.get` 明说 no geometry），所以
`--profiles` 的那份库要**先在真机上量**——在临时页上放一颗真器件（`sch.place_component
--params '{"lcsc":"C25744","x":400,"y":300}'`），读 `sch.component_pins`（引脚偏移 + PinLength）
和 `sch.geometry --params '{"bboxIds":[<id>]}'`（实测外框 = body），删掉这颗探针件，
再把量到的数字写成 `SymbolProfile`（`source` 里写清量法与出处）。
实测：C25744（0402 10k）引脚 ±20、body ±10.5×±4.5；C1525（0402 100n）引脚 ±20、body ±10.5×±8.5。
拿**竖排 ±50** 这类没量过的 profile 去落图，引脚回读必然点名不符（C6 现场）。

**apply 的执行序**（`_draw_apply_flow`）：① 页（`--page` 或 `--new-page`；plan 未绑页又没给页 → exit 5；
**plan 已绑页或已给 `--page` 时再给 `--new-page` → 显式拒 exit 5**，绝不静默落在绑定页上——143d）
→ ② 守卫（双 spec 摘要 + 布局摘要 + 库几何表 + 页身份；**显式** `--expect-census` 也在这关）
→ ③ 探针（plan 自己的 postconditions，双证齐全 = `already_applied` exit 0 零写入）
→ ④ 页既不是 plan 成品也不是 plan 基线 → `canvas_changed` exit 4 零写入
→ ⑤ 位号池（页面 ∪ 工程导出）→ ⑥ 放件 → ⑦ **写 Value**（055 起：plan 用 `valueKey` 逐件
声明，无 key/无值**不写不报**；`sch.set_component_attribute` 既有通道零新增）
→ ⑧ **引脚回读**（容差半格，同一把 geometry 读同时做值回读；引脚不符、值写不进/回读不符
**都在拉线前**停住 exit 3）→ ⑨ 走线（`net` 承载网名）→ ⑩ 旗标（`place_power`）→ ⑪ 双证回读
（活网表按**本 plan 自己的引脚**判分区；页面外同名同网只报 `sharedWithOutsidePins`）
→ ⑫ 范围（无删除 → 导出新鲜）+ findings 分级拦（ERROR 必拦 / WARN 需 `--force` / INFO 只报告）
→ ⑬ 保存（`saved_unverified`，要 `saved_verified` 得走 `boardwise persistence` 的关闭重开）
→ ⑭ `export.render` 出图（`already_applied` 也出图：图是证据不是写）
→ ⑮ **旗标朝向核对**（坑 42 的手法、坑 43 的事实）：出图时一并要 `format=svg`，解
`c_partid="netflag"` 组逐颗读"连接点 → 字形往哪边伸"，与 plan 里每颗旗标的 `rotation`
对表；GND 与 PWR-* 两家自然姿态相反，离线预览画的是统一约定盒、看不出这个差
（照抄姿势与判据见 `outputs/064_railflag/`）。

退出码：**0** 落图并被双证确认（或 already_applied 零写入）/ **2** 承诺的效果不在（写被拒、
保存被拒、range/旗标数不对、findings 仍被拦：ERROR 有、或 WARN 有而未给 `--force`）/ **3** 页状态不可陈述或回读不符（超时、拔 daemon、
引脚/值回读不符、postconditions 不满足——**在拉线前**停）/ **4** 守卫拒绝（摘要 stale、库几何变了、
页不是 plan 的、画布被动过、位号被占、半成品件在页上）/ **5** plan 或输入不可用。

幂等与 stale：`draw apply` 同 plan 再跑 → `already_applied` 零写入（C4）；手工动过画布再跑 →
exit 4 零写入（C5）；库几何不符 → exit 4 零写入（C6，写前那条腿用 `--profiles` 的库文档，
编辑器侧那条腿只能靠放完后的引脚回读，所以它是 exit 3 且件已放）。

**LDO（C3）现场有两条真机事实，照坑 33/34 走**：真机 AMS1117 符号的 VIN/VOUT/GND 全在**同一侧**
（外加一颗重复 VOUT），`ldo` 文法的默认"in 左 out 右"**无合法姿态**——要么按坑 33 用
`sidePreferences`（这是一个**说明**"下面那条输出支路"，不是"输出在下方"），要么换一颗符号；
另有坑 34：本仓库 facts 要求 AMS1117 输出 ≥22µF（053 场景值 055 起已同步为 22µF），拿 100n
输出落图 `decap-required-caps` 会涨 finding、`draw apply` 按 036 规矩**拒绝保存**（图落好了、没落盘）。

**057：一页多模块（页文档）与 `draw discard`——不加命令、不加旗标，同三条命令**：

- **什么算"页"**：PresentationSpec 有 ≥2 个 `modules[]`、或写了 `flow`、或某模块自带 `grammarRef`、
  或有页级锁（`pagecompiler.wants_page`）→ 走页级编译；恰一个模块（054 夹具那种）走原单模块路径，输出一字不变。
  页级 `draw compile` **必须给 `--page-box`**，产物是 `candN.page.json`（`kind=boardwise-page-layout-plan`）+
  带模块虚线框的 `candN.svg`。
- **`draw plan`（页）**：页级编译后把选中候选的 `plan` 字段交给同一个 `module_plan`，产出的仍是
  `draw-module` plan（layoutSha256 = 页文档 `plan` 的几何哈希），旁边写 `<plan>.page.json`。带 `--page`
  时读页面 census，**每个既有图元（件/线/旗标/网标，件与网标用 `bboxIds` 实测外框，没量到的用原点 ±50 假定框
  并在 notes 里点名）转 keepout**，模块组整体平移避开；
  未编号器件（编辑器自己的 `R5?`）没有位号可点名，只进 census 计数、不进组件集；
  全被占 → `presentation-poor` 点名"existing R5 …"。页文档里的跨模块标签在本机放不了（坑 9），**没有线
  到达的标签点会补一段 10 单位具名短线**（downgrades 里写明），否则两边同名网在工程级网表里合不起来。
- **`draw apply`**：`--layout` 可给页文档；位置参数也可直接给页文档（需 `--circuit/--presentation/--profiles`
  + `--page`/`--new-page`），运行时现建 plan 再走原流程；页文档的"过期守卫" = 它的模块框对页面现状的
  keepout 规则（压到既有图元 → exit 4 零写入）；要"页面任何变动都拒"用 `draw plan --page` 产的 plan
  （census 摘要精确）或 `--expect-census`。**所有落图**新增范围外逐项对比：落图前已在页上的每个图元
  （位号/值/LCSC/网/坐标/姿态/线点；网标另比 网名/文字/坐标/角度）必须原样，改了一件 → exit 2 不保存（`range.outOfScope`）。
  报告 `verification.nets` 逐网列出编辑器网表回读名，跨模块网标 `crossModule`、`oneNet`（G4）。
  findings 按身份分级拦（`rule|severity|位号|脚|命名网` 的**第二段**就是严重度）：ERROR 必拦、
  WARN 需 `--force`、INFO 只报告（#55 裁决 B）；仍不按计数。
- **页级锁**：`userLocks[]` 加 `"scope": "page"`（不写 rotation；位姿归模块）→ 该件在每个候选都落在
  页坐标 P（origin = P − 模块内坐标，逐代次不同是对的）；锁点出页 / 两把锁矛盾 / 锁住的框出页、压
  keepout、与另一锁住的框冲突 → `presentation-poor` 点名锁。模块锁（默认 scope）与页锁可同件共存。
- **`draw discard <plan.json|page.json>`**：只删该 plan 自己画的东西。件按**位号 + 坐标 + 值**（无 valueKey
  的旧 plan 用 LCSC）核身份，旗标按网 + 点，线要求**每个点都在 plan 的线上**（被宿主并进别人线的 primitive
  不删，坑 32）；**任何一件不符整批拒删**（exit 4，零删除）。先线、再旗标、后件（每相每次 ≤30 id，分批
  会写进报告）；删后回读：目标全无 + 范围外逐项不变。第二遍 = `nothing_to_discard` exit 0。`--save` 才保存；
  超时/断连先回读、不重试（exit 3）。页文档需 `--circuit/--presentation/--profiles`，按坐标 + 前缀 + 值找件。
- **已知缺口（057 离线实测，`tools/057_scenarios.py`）**：CH340G 核心/晶振/USB 侧**没有文法**（只有
  divider/RC/LDO），页级编译对这三组报 `facts-missing`；金样板上的 RT9013（VIN/GND/EN 同在左侧）在 `ldo`
  文法下 48 种 sidePreferences **全部无合法姿态**——坑 33 的"改输入侧"对它无效。真机 E1–E7 的操作清单见
  `tools/057_live_runbook.md`。
- **074：旗引线不得穿越别网导体**（岳裁「必须改」，命令面一字未增）。069 落下的 pin2 3V3 旗引线
  「横 50 + 竖拐 25」的**竖拐**子线段与 5V0 横轨在 (60,740) 垂直交叉、无 junction 圆点——电气双岛正确，
  但第一眼读成「旗挂在 5V0 轨上」。尺子：候选引线的**每个子线段**与别网导体（`router.edges` +
  已落件引脚）做**严格内部**相交——共享端点、T 型衔接（端点落线 = 有意的 junction）、共线重叠都**不算**；
  只硬化**旗引线/stub 段**（069① 远脚 stub、`_rail_flag` 沿轨段、竖拐 jog），**普通信号布线穿越不硬化**
  （crossings 仍是软指标）。硬拒后按既有梯子升级（距离档 → 逃逸方向 → 三折/两段引线 → 向无轨方向垂挂）；
  梯子穷尽 → `layout-unsat`，报**哪段穿哪条导体 + 交叉点 + 建议动作**，**不许静默产出穿越图、不许假
  junction**（安全阀：`layout-unsat` 是契约内的合法答复，不是 bug）。

