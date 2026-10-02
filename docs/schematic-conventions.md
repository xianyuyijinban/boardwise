# Schematic readability conventions

Source: xianyuyijinban's exemplar review (2026-09-14), exemplar = `0CD5010P_高速风机_T01A`
(single-page power + control board). These rules are the generator's constitution and the
rubric for the draw acceptance gate ("xianyuyijinban亲验判可读"). They bind **generated** layouts
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
(xianyuyijinban's standing rule). Power/ground use flags as usual.

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
| **drawing compiler (053+)** | R6–R10 are compile-time hard constraints — a candidate that breaks one is rejected, not scored down; the independent readability gate (`engines/readability.py`) re-checks survivors |
| layout lint | checkable subset today: overlap / off-frame / through-body / orphan naming; block-aware checks (wire stays inside block bbox; label at block boundary) are queued behind 006c |
| gate 3 (human) | full rubric R1–R4, judged by xianyuyijinban on the render |

## Non-goals

Block frames/captions are **not** synthesized onto golden replays that lack them (the CH340
golden has none — replay stays verbatim). Frame synthesis is a generator feature, not a
replay patch. **Block assembly (008a) deliberately does not synthesize them either**: its
R1 conformance is the whitespace moat the spec's placement creates, and a caption primitive
would need its own lint surface. Recorded here so the omission is a decision, not an
oversight.

## Compiler-era rulings (060–074, ruled by xianyuyijinban on live renders 2026-09-28/29)

These bind the **drawing compiler** (`engines/drawcompiler.py` / `engines/pagecompiler.py`)
and are enforced as hard constraints at compile time — a candidate that breaks one is
rejected, not scored down. The reference renders live in `outputs/069_ldo_example/`
(the hand-drawn P22 exemplar) and `evidence/074/` (P23 v5/v6).

R11–R12 are the power-entry rulings, added by 088b (ruled by xianyuyijinban 2026-10-02 on
the landed 088 sample drawing); R6–R10 stand unchanged.

### R6 — A capacitor hangs on its owning pin's physical side

The decoupling rule "caps touch their IC's power pins" (R4) is pinned to the *pin*, not
the device's bounding side. When the symbol offers a same-role pin on the opposite face
(measured: pin tips whose dot product across the body centre is strictly negative), the
output capacitor hangs on that opposite pin. On the single-sided AMS1117 symbol this put
the input cap left on the VIN side and the output cap right on the duplicate VOUT pin —
ruled correct against the hand-drawn exemplar (065).

### R7 — Far same-role pins join by name, never by a wire

Two pins of the same role on *opposite faces* of a body are "far apart": they are **not**
bridged with a physical wire. Each gets a short stub carrying a same-named flag
(power/ground) or net label (other nets); the net merges by name. Same-side same-role
pins still wire directly (069①; the electrical obligation from 060② is unchanged — every
same-role pin is connected, only the *form* changed).

### R8 — Every power net carries at least one power flag

A rail named only by wire text is a **defect** (069③). The compiler runs a closing pass
that adds the flag; a wire whose net has a flag then carries **no name of its own**
(069⑨ — the flag *is* the name; hand-drawn pages show empty `Net` fields on such wires).
Flag placement hugs the device: a power-pin stub prefers a 50-unit lead, backing off
30/10/0 when occupied, 60 at most (069②), and the whole flag box (glyph + text + margin)
stays clear of foreign wires (069⑧).

### R9 — Flags are always vertical

Flag rotation is ∈ {0°, 180°}; 90°/270° are forbidden (069④). The two glyph families have
opposite natural poses in the library (measured 064: `Ground-GND` bar below the connect
point, `Power-VCC` bar above), so the rotation offset is per-family — ground glyphs +180,
rail glyphs +0 — from one shared table; compass and glyph box can never drift to opposite
sides again.

### R10 — A flag lead never crosses a foreign conductor

A flag lead, a far-pin stub, or a rail-flag jog crossing **another net's** wire or pin is
a hard defect (074) — crossing without a junction dot reads as a short to the human eye
even when the netlist keeps two islands. Shared endpoints, T-taps and collinear overlap
are *not* crossings, and no fake junction may be planted to dodge the rule. A violating
candidate is rejected and the anchor ladder re-seats the flag; ordinary signal routing
crossings stay a soft metric. Exhausted ladders report `layout-unsat` with the conductor
named — the compiler never silently ships a crossing.

### R11 — A power inlet's return rail carries exactly one ground outlet symbol

The bottom rail of a power-entry drawing is a solid conductor (088, part of the same ruling)
**and** carries exactly **one** ground outlet symbol: hung off the rail's far end — the
member pin away from the inlet, read from `sidePreferences.input`, so the symbol mirrors
with the drawing — and standing vertical (`rot ∈ {0°, 180°}`, R9). Two marks read as two
returns (岳 2026-10-02, on the landed sample: 「真实体现得很乱」), and none leaves the
group's ground as a bare conductor that says nothing about where it leaves. **Unconditional**:
the grammar states the promise (`gnd-outlet`) on every bind and the compiler places the
symbol — the case does not have to declare modules (088b's first cut gated it that way and
the main agent's review took the gate away: 岳's own sample declares no modules either, and
「加一个接地符号」 has no such premise). 069③'s page-level flag pass is untouched, so a page
still expresses a ground shared across modules with flags at the module boundary
(`pagecompiler` port kinds unchanged).

### R12 — Bleeder parts (TVS/diodes) sit nearest the inlet, and the order is declared

A branch that clamps a spike belongs nearest the inlet (岳 2026-10-02: 要及时把电压尖峰泄
下去). Which branch that is cannot come from the drawing law: a TVS, a bulk capacitor and
the inlet are the same shape between the same two nets, and 053 §6 forbids a grammar
reading a designator prefix, a value or a package name. So the **presentation** states the
order — `PresentationSpec.modules[].branchOrder`, listed from the inlet end outwards — and
the grammar only carries it out and refuses a statement that is not about its own branches.
The model writing the presentation is the one that can tell (it reads `SMCJ28CA` as a TVS);
the grammar never guesses. Absent = designator order (088's drawing, byte-identical); a
partial list keeps its stated prefix, the rest follow in designator order, and the
completion is written into the binding evidence so nothing is silently re-ordered.
