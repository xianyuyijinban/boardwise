# Block templates and the assembly engine (task 008a)

A page is not solved, it is **composed**: blocks are placed, each block replays
its own internal geometry, and the blocks are tied together by net *names* and
nothing else. That is 008's architectural bet (constitution items 1–2) and it
rests on one artifact — the block template — plus one engine that composes them.

This file documents both, states the coordinate contract once, and records what
008a does **not** claim.

## The shape of a page

```
board spec (blocklib/specs/*.json)
├── blocks[]      which template, where it goes, what it is for
├── connections[] one page net <- the ports that are on it
├── params{}      "<block id>.<parameter>" -> value
└── sheet{}       the page it targets (a fallback; the draw flow measures the
                  live page first)

        +  blocklib/blocks/*.json, one template per block

              ↓  engines/assemble.py::assemble()

DesignModel (the *spec netlist*)   +   PageLayout at the assembled positions
        +  file-space symbol offsets and measured symbol bodies

              ↓  engines/replay.py::build_replay_plan()  (unchanged, 006b)

ActionPlan -> the existing draw chain
```

Nothing in the assembly path invents geometry: `assemble` translates block
coordinates and renames nets, and `build_replay_plan` does the rest — including
`split_at_junctions` (R5) and the five hard constraints plus the annotation
lint. The self-check therefore runs on an assembled page with no new validator
and no new exception to R1–R5.

## The coordinate contract

**Every coordinate inside a block template is a block-local file coordinate**:
the golden page's file-space value minus `origin_file`. `origin_file` is kept so
a block can be put back exactly where it was cut from, which is what makes the
round-trip test possible.

* Placing a block is a plain addition: `page = local + instance.at`.
  (`at - origin_file` double-counts the cut offset. It is the bug the first
  assembler shipped: a correct netlist, geometry 240 units off the sheet.)
* `at` defaults to `origin_file`, so a spec that only wants "put it all back"
  says nothing.
* The file→canvas conversion still happens in exactly one place
  (`engines/replay.py`), which is why nothing in `core/blocks.py`,
  `engines/cut.py` or `engines/assemble.py` mentions the canvas. The 006c
  coordinate guards (`tests/test_coordinate_guards.py`) hold.

## Template fields

| Field | What it is |
|---|---|
| `name`, `description` | identity and prose for the report |
| `provenance` | `textbook` / `datasheet-extract` / `board-extract`, the source, the designators, a note |
| `origin_file`, `bbox_file` | the cut: where the block's zero is, and the boundary that was drawn (absolute file coordinates, provenance only) |
| `symbols` | symbol uuid → `offsets` / `body` / `pin_names`. Geometry travels with the block; positions do not |
| `components[]` | `ref`, `symbol`, `placement{x,y,rotation,mirror}`, `device{}`, `footprint`, `params{}`, `pins[]` |
| `interface[]` | `role`, `net`, `net_class` (`power`/`signal`/`gnd`), `position` (required iff the block has geometry), optional `direction`/`voltage`/`level` |
| `params[]` | `name`, `role`, `default`, `constraint`, `provenance` |
| `geometry` | `wires[]`, `flags[]`, `labels[]` — the block's internal copper and naming |

Two deliberate choices inside `components[]`:

* **`device{}` is an object, not four loose fields.** It mirrors
  `PlacementStep.resolution()`'s order (explicit uuid pair → lcsc → keyword) and
  carries `expect_footprint` and a `provenance` string, because a device binding
  is exactly the kind of thing that gets corrected on someone's authority (006b
  §G). A curated-library key (008b) will be one more field here; nothing else
  has to change.
* **`params{}` maps a component property to a parameter name**, rather than
  inlining a value. "Every number is a parameter" (constitution item 4) is only
  true if the number has one place to live, and that place is the board spec.

## Parameter constraints are executable

`params[].constraint` names a checker in `core/blocks.py::CONSTRAINTS`:
`free_text`, `resistor_value`, `capacitor_value`, `frequency`. Every value is
checked where it can enter — the template's `default` and the spec's
assignment — and **an unknown constraint name is an error**: a typo'd
constraint that validates nothing would leave the template claiming a check it
does not perform.

The cut tool infers a constraint from evidence and says which evidence:

| Evidence | Constraint |
|---|---|
| device title starts `Res`, or footprint matches `R####` | `resistor_value` |
| the value ends in a farad unit | `capacitor_value` |
| the value carries `Ω` / `ohm` | `resistor_value` |
| nothing conclusive | `free_text`, with a note |

`104` is a resistor's marking and a capacitor's marking at once, so with no
package evidence the tool refuses to guess. `tools/extract_block.py --constraint
REF=NAME` is the escape hatch, and it is explicit on purpose.

## One template, several instances (008c)

A spec may place the same template more than once, and then the page needs two
names for every part and every net the block carries. Both derivations are
deterministic code (`core/blocks.py`), because naming is never the model's:

* **designators** — instance *ordinal* 0 keeps the template's refs verbatim; the
  ordinal *n* instance adds `DESIGNATOR_STRIDE` (100) to the numeric part, so
  `R1` becomes `R101`. A ref that is not `letters + digits` is **refused** rather
  than mangled. The stride is a documented limit: a template whose refs span more
  than 100 of one prefix collides with its next instance, and
  `assemble._check_designators` rejects that instead of drawing two parts with
  one name.
* **nets** — the spec's `connections` stay authoritative (that is how two
  instances share `+5V`). A net the spec does **not** connect is scoped to its
  instance (`NET5` → `NET5#b2`), because a copy of a block carries the same net
  names — including its internal ones, which no connection can join since they
  are not interfaces. Without this, placing one template twice is reported as
  "two circuits would end up with the same page net name", which is true of two
  *different* blocks and false of a block and its copy.

Ordinal 0 is untouched in both derivations, so a spec that places one instance
per template produces exactly what 008a produced — `designator_map` for the
committed CH340 spec is the identity map, and `tests/test_designators.py` pins
that.

"The same block" is the **resolved template path**, not the template's name: two
files that happen to be called the same thing are two blocks.

## The BOM is an output (008c)

```bash
boardwise bom export --spec blocklib/specs/ch340g_usb_uart.json --out bom.csv
```

Nobody writes a BOM first — it falls out of the schematic — so nothing here takes
one as input. `engines/bom.py` derives it from the spec: each block component's
`device` binding resolved **by C-number** against the curated shelf (008b), plus
the parameter value the spec assigns, grouped by C-number and written as JLC's
five columns (`Comment,Designator,Footprint,LCSC,Qty`).

Three refusals, all of them open questions in the report rather than rows:

* a binding that resolves to nothing unique — **no nearest-match substitution**;
* a part with no binding at all (an abstract `Res_0603`) — named by designator,
  because a BOM that quietly omits a part is worse than no BOM;
* one C-number carrying two different values — the row appears with an empty
  `Comment`, because the export will not pick one of the two numbers (#202).

The designators in the file are the **page** designators, so a board that places
one block twice gets one line listing both instances' refs. The export runs the
assembler first: a spec that cannot be composed has no trustworthy part list.

## Cutting a block out of a board

```bash
python tools/extract_block.py --golden tests/fixtures/ch340_golden.epro2 \
    --overrides tests/fixtures/ch340_golden.overrides.json \
    --name ch340_usb_input --designators USB1,R24,R27,C4 \
    --bbox 40,-240,230,-40 --out blocklib/blocks/ch340_usb_input.json
```

Everything the cut needs is recorded **inside** the template, so a committed
block can be re-derived from the board it names and the two compared:

```bash
python tools/extract_block.py --recut blocklib/blocks/*.json \
    --golden tests/fixtures/ch340_golden.epro2 \
    --overrides tests/fixtures/ch340_golden.overrides.json
```

`tests/test_cut.py` asserts the committed JSON and the re-cut JSON are equal
byte for byte. That is what turns "this template is a faithful extract of board
X, region Y" from a comment into a checkable claim.

Three refusals are the tool's actual design:

* a part the boundary does not contain → error (widen it or leave the part out);
* **a wire run that leaves the boundary → error.** Half a run cannot be assigned
  to a block without either dragging a stub into whatever ends up next door or
  losing copper the connectivity pass already counted, so the tool says which
  run and where it leaves instead of picking one;
* **a port is never invented.** A port is a label or flag inside the box that
  names a net with at least one member *outside* the block. A net that crosses
  the boundary carrying no anchor of its own gets **no port** and a note — "what
  is on the boundary is what gets written; the rest is a human's to fill in".

For the CH340 golden the four boundaries partition the page exactly: 45 wire
runs, no run inside two blocks, none outside every block
(`test_the_cut_partitions_the_page_without_losing_copper`).

## Assembling

```bash
boardwise compare --spec blocklib/specs/ch340g_usb_uart.json \
    --golden tests/fixtures/ch340_golden.epro2 \
    --overrides tests/fixtures/ch340_golden.overrides.json   # offline double check
boardwise lint --spec blocklib/specs/ch340g_usb_uart.json    # offline plan + lint
boardwise draw --spec blocklib/specs/ch340g_usb_uart.json \
    --golden tests/fixtures/ch340_golden.epro2 --render out.png   # assemble and draw
```

`draw --spec` runs two offline gates **before** it opens the bridge (in that
order, which is the order that keeps a wrong specification from mutating a
project): the assembly report, then the double check that the spec netlist
reproduces the golden. A mismatch aborts the run.

### Nets: the connection is authoritative

A block's own geometry carries net names, and the spec's `connections` decide
the *page* name of each one. A connection that names a net differently from the
block's local name renames every wire, flag, label and pin of that net inside
that block; a connection whose name already matches is a no-op. The CH340 blocks
were cut from the golden, so all seven connections are no-ops by name — but the
mechanism is what makes a `datasheet-extract` block (whose local names would be
its own) usable next to it.

Three refusals guard the merge:

* two blocks claiming the same **designator** → error. Refs are used verbatim;
  per-instance designator allocation is 008c's job, and silently renumbering
  would break the diff against a golden.
* two circuits ending up with the same **page net name** without a connection
  joining them → error, with both sides named. This is the mistake that would
  quietly turn two nets into one.
* a **power/ground port with no flag** at its position → error, **but only on a
  block that carries geometry** (2026-09-17 ruling; see the next section). A
  template with wires or flags replays the anchors its cut saw, so a missing one
  is a defect in the template. A geometry-less block has no measured anchor to
  be missing — its anchors are synthesised.

## Anchors: two paths, chosen by whether the block carries geometry

A port's `position` is where its **name** is drawn, and where that anchor comes
from depends on the block (2026-09-17 ruling, 岳翔宇):

* **A block with geometry** (a `board-extract`) has anchors its cut actually
  saw. Its flags and labels are translated onto the page, `position` is
  **required** and must be one of them, and a rail port with nothing there is an
  error — a measurement with a hole in it is a defect in the template.
* **A block with no geometry** (`datasheet-extract`, `textbook`) has no measured
  anchor at all, so `position` is **forbidden** and the assembler **synthesises**
  one per pin endpoint. Writing `[0, 0]` there is not "no position" — it is the
  claim that the anchor sits at the block origin, which is false unless something
  is drawn there. The loader refuses it.

The synthesis is deterministic, so the same input assembles byte-identically:

| rule | value |
|---|---|
| endpoints | `placement + symbol offsets`, rotated by `core.geometry.transform_point` (the one rotation convention in the project) |
| rail stub | one routing cell, `engines.layout.GRID` = 5.0, **outward**: `+y` for power, `-y` for ground (`+y` is up in file space) |
| rail flag | at the stub's far end, `kind` = `Power`/`Ground`, **`symbol_uuid` empty** |
| signal name | a net label **at** the endpoint, no stub |
| port anchor | the port doubles as its own endpoint's anchor: power takes the net's topmost endpoint, ground the bottommost, a signal the leftmost — ties broken by smallest x, resp. smallest y |
| collision | an anchor inside another part's body is **noted, not refused**: the author's layout is signed, and readability is a real-host question |

Nothing is invented about a flag *glyph*: `sch.place_power` takes no symbol uuid
and the editor resolves it from `kind` + `net`, while an empty `symbol_uuid`
degrades gracefully in the replay (it only feeds the annotation-box prediction).
Both halves are pinned by `tools/_probe_flag_anchor.py`.

**Why the anchors exist at all.** A geometry-less block's components sit where
its author placed them — a signed layout, not a solved one — and it has no
wires, so without this pass its pins are electrically real but visually
anonymous: a reader would see three parts and no idea which net is which.
Connectivity travels as names, and names need anchors.

## What 008a does and does not claim

The CH340 templates are **board-extracts** — source 3 of the three the
architecture lists. So what this validates is the **assembly mechanism**:

* the cut is faithful (re-cut reproduces the committed JSON);
* cut + assemble at the original origins reproduces the golden page's parts,
  wires, flags and labels exactly, and its netlist exactly;
* the assembled page, on a grid of the spec's own choosing, lints to 0
  violations and still reproduces the golden's connectivity.

It does **not** validate template authoring quality — whether a `textbook` or
`datasheet-extract` block is a good block. That is 008c/008d. It also does not
solve:

* **per-instance designators.** One instance per block, refs verbatim — **closed
  by 008c**; see "One template, several instances" above.
* **block captions and frames.** R1 is satisfied here by whitespace moats; the
  golden page has no captions either, and synthesising them is a generator
  feature with its own lint surface. Deliberately not in 008a.
* **a generic placer.** Where the blocks go is the spec's decision, chosen by
  hand and checked by the existing lint.

Non-goals are listed rather than implied because a reader who assumes otherwise
will read the acceptance numbers as more than they are.

## Files

| Path | Role |
|---|---|
| `src/boardwise/core/blocks.py` | the schema, the loaders, the constraint registry, the designator and net derivations |
| `src/boardwise/engines/cut.py` | board → block template |
| `src/boardwise/engines/assemble.py` | templates + spec → design |
| `src/boardwise/engines/bom.py` | spec + shelf → the bill of materials (008c) |
| `tools/extract_block.py` | the cutting CLI (single cut and `--recut`) |
| `blocklib/blocks/*.json` | the block library (committed; regenerable) |
| `blocklib/specs/*.json` | a board: blocks, placement, connections, numbers |
| `tests/test_blocks.py` | schema + constraints |
| `tests/test_cut.py` | cut round trip and the three refusals |
| `tests/test_assemble.py` | round trip, moved layout, negative cases |
| `tests/test_spec_cli.py` | the `--spec` CLI surface |
| `tests/test_designators.py` | the per-instance designator rule |
| `tests/test_bom.py` | the BOM export and its three refusals |
