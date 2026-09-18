# Schematic readability conventions

Source: 岳翔宇's exemplar review (2026-09-14), exemplar = `0CD5010P_高速风机_T01A`
(single-page power + control board). These rules are the generator's constitution and the
rubric for the draw acceptance gate ("岳翔宇亲验判可读"). They bind **generated** layouts
(the solver and any future AI-authored page); golden replay inherits them for free because
the golden pages are human-drawn.

## R1 — Block partitioning is mandatory

A page is divided into **functional blocks**, each visually delimited (frame or clear
whitespace moat) and captioned with the block's function (`输入端口`, `12V供电电源`,
`5010P QFN40`, `发热丝控制电路`, `过流检测`, …). No block may sprawl across another's
region. Block inventory follows the circuit's function, not component count.

Exemplar block layout: power entry top-left → 12V rail → 5V rail → power stage right;
MCU center; interfaces (NTC / programming / keys / lamp) left and bottom; sensing
(zero-cross / over-current / over-temp / current-amps) bottom rows.

## R2 — Between blocks: net labels, never ports

Inter-block connectivity is named with **net labels** (in our pipeline: wire-carried net
name + TEXT presentation, see `docs/draw.md` — native `createNetLabel` is v4-locked,
measured 2026-09-14). I/O ports (`sch.place_netport`) are forbidden in generated pages
(岳翔宇's standing rule). Power/ground use flags as usual.

## R3 — Inside a block: wires for simple topology, labels for complex

- Simple sub-circuits (divider, RC filter, connector + pull-up): direct wires, short and
  Manhattan.
- Complex or wide-fanout signals *within* a block may also use net labels to avoid
  wire spaghetti (exemplar: the MCU pin fan-out uses labels even though the MCU sits
  one block away).

## R4 — Follow the canonical circuit topology

Placement must make the circuit **recognizable at a glance** to an engineer:

- A divider looks like a divider (vertical series pair, tap node mid-wire).
- A bridge / power stage keeps its H/LLC shape; gate drivers adjacent to their switches.
- Current-sense amps drawn as the classic op-amp triangle with feedback network wrapped
  around it (exemplar: U相/U相/母线电流放大 blocks).
- Decoupling caps physically touch their IC's power pins.
- Signal flow reads left→right or top→bottom within a block.

## R5 — Every run touching a junction must END there

Not a style rule: a measured property of the editor (2026-09-15).

`sch_PrimitiveWire.create` **merges polylines that share an endpoint into one
primitive** and repeats the junction point. If a run's endpoint lands on another
run's *interior*, the merged polyline can come back with a pin tip sitting in
its middle — and the netlist then reports that pin as **unconnected**. That is
exactly how U1.16 dropped out of VCC while every coordinate matched the golden:
the branch stub ended on the main run's middle vertex.

So the wire builder applies a junction rule at planning time
(`engines/replay.py::split_at_junctions`, run again after F3 snapping because a
stub is a new run):

1. an endpoint of one run lying inside another run's segment is inserted as a
   vertex there;
2. every run is then split at any vertex where another run ends, so all
   touching segments share an endpoint.

The editor's own representation of a junction is a connection point that every
touching segment terminates at; matching it is what makes connectivity survive
the merge. Verified on the live page: re-sending the pin's segment as an
endpoint run put U1.16 back into VCC.

## How the pipeline consumes these rules

| Stage | Use |
|---|---|
| golden replay (006b default) | inherits R1–R4 from the human page; lint only verifies |
| **block assembly (008a)** | inherits R1–R4 from the blocks it is composed of; the spec's block placement decides the whitespace moats, and the same lint verifies |
| solver fallback | must satisfy R1 (blocks from `Component.block` metadata) and R3; R4 via per-topology placement templates (future) |
| layout lint | checkable subset today: overlap / off-frame / through-body / orphan naming; block-aware checks (wire stays inside block bbox; label at block boundary) are queued behind 006c |
| gate 3 (human) | full rubric R1–R4, judged by 岳翔宇 on the render |

## Non-goals

Block frames/captions are **not** synthesized onto golden replays that lack them (the CH340
golden has none — replay stays verbatim). Frame synthesis is a generator feature, not a
replay patch. **Block assembly (008a) deliberately does not synthesize them either**: its
R1 conformance is the whitespace moat the spec's placement creates, and a caption primitive
would need its own lint surface. Recorded here so the omission is a decision, not an
oversight.
