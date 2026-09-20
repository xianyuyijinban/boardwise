# Triage — `ProPrj_毕设FOC驱动板_2026-09-17` (task 011e sec.3)

Board: `tests/fixtures/ProPrj_毕设FOC驱动板_2026-09-17.epro2`
Model: **121 components, 85 nets**. Findings: **30 ERROR / 17 WARN / 12 INFO**
(after 011e sec.1.1; before it, 11 of those were `param-rc-cutoff` numbers
sitting in the VIOLATION column).

**How to read this.** Nothing here is a claim about the design — it is the list
the rules produced, with the evidence behind each line, waiting for your
ruling. One line per *kind* where the whole kind resolves the same way (sec.3.2
asks for batch rulings); single items are listed one by one.

Each ruling is one of:

| ruling | meaning for the annotation set |
|---|---|
| `defect` | a real problem; it becomes a defect record with a rule hint |
| `exception` | the rule fires and it is **not** a problem; becomes an exception record (with the reason) |
| `observation` | worth recording, no verdict (e.g. "this block is a stub") |
| `backlog` | not a ruling at all: a **fact** the library cannot supply yet |

`reviewed_by` stays empty until every line is ruled; the harness keeps stamping
the report `DRAFT` until then. **As of 2026-09-19 every line is ruled except
B3**, which is the one holding the stamp.

**Ruling record (oracle Yue Xiangyu, 2026-09-19).** A1 → `defect` ×30 (the
oracle's words for the cause: 当时疏忽，没在意). A2a+A2b → `exception` ×10
(three because the decoder over-reaches on part numbers that are not EIA-coded,
seven because the decode is right and the positions do not care). B1 → `defect`,
B2/B4/B5 → `observation`/`observation`/`backlog`, B3 → pending. All of it is
landed in `reviewsets/ProPrj_毕设FOC驱动板_2026-09-17.json` — the per-line blocks
below carry the reasoning.

---

## A. Batch rulings (one decision covers the whole kind)

### A1. `conn-duplicate-designators` — 30 × ERROR

> `U1 is used by more than one placed part; the model kept only the last placement`

Refs (30): `U1 U2 U14 U15 U16 C1 C2 C3 C4 C5 C6 C7 C8 C9 C10 C11 C12 C13 R1 R2
R3 R4 R5 R6 R8 R18 SCREW1 SCREW2 SCREW3 SCREW4`

Evidence: `parsers/schematic.py::build_schematic_model` merges every `SCH_PAGE`
into one model keyed by designator; each collision is recorded in
`model.duplicate_designators`. The 30 refs are the collisions, not 30 separate
defects in the drawing.

Suggested ruling — **one of**:

- [x] `defect` × 30 — the board genuinely numbers two different parts the same.
      (Likely: R-class and C-class refs repeating across subsheets, plus the
      four mounting screws.)
- [ ] `exception` × 30 — the duplicates are page-local and intentional, and the
      model's "last placement wins" is the accepted reading.
- [ ] split — e.g. `SCREW1..4` are mounting hardware, not circuit parts:
      `exception` for those, `defect` for the rest.

If `exception`, please give the reason in one sentence per group — the record's
note has to explain *why* the rule's firing is acceptable.

### A2. `param-value-mpn-match` — 10 × WARN

Refs and the contradiction each one reports:

| ref | board value | MPN | MPN decodes to |
|---|---|---|---|
| `R43` | 0.01 Ω | `JER2512F3R005` | 0 Ω |
| `U14` | 1000 Ω | `FRC0805J471 TS` | 470 Ω |
| `U10` | 1000 Ω | `FRC0805J471 TS` | 470 Ω |
| `C115` `C116` | 0.00033 F (330 µF) | `PA50V330M10x15` | 3.3e-11 F |
| `C28` `C29` `C36` `C42` `C44` | 2.2 µF / 10 nF | `CC0805KRX7R9BB104` | 1e-07 F (100 nF) |

Two sub-kinds, because they resolve differently:

- **A2a — `R43`, and the `PA50V330M10x15` group.** An aluminium-electrolytic
  part number is not an EIA code at all: `330M` is being read as "33 × 10^0 pF"
  and `3R005` as "3.005 Ω rounded to 0". Here the *decoder* is over-reaching,
  not the board.
  Suggested ruling: [x] `exception` for these refs (rule limitation, named
  in the note) — [ ] `defect`.
- **A2b — `U14`, `U10`, and the `CC0805KRX7R9BB104` group.** `471` → 470 Ω and
  `104` → 100 nF are *correct* EIA decodes of a 0805 part; a 1000 Ω part and a
  2.2 µF part genuinely contradict them.
  Suggested ruling: [ ] `defect` — [x] `exception`.

Note: `U10`/`U14` carry the same MPN/value pair as the CH340G board's `U3`,
where the oracle already ruled **the value is right and the MPN is wrong**
(2026-09-19). If that ruling generalises, A2b is `defect` and the fix is a BOM
correction.

### A3. `conn-nc-and-must-connect` / `pwr-*` / `path-ldo-dropout` /
`decap-required-caps` / `param-divider-output` — UNKNOWN, not defects

These are **not** rulings about the board. They are the harness saying "the
library cannot answer this yet", and the missing fact is named per part. They
belong to the facts backlog (§C), and they stay UNKNOWN — no record — until
011b-style facts land. **No tick required.**

---

## B. Single items

### B1. `decap-required-caps` — 1 × WARN

> `U11 pin5: the grounded capacitor on 'NET2' is only 100nF (< required 1uF)`

Evidence: `U11` is identified on the shelf and its facts demand ≥1 µF on pin 5;
the largest established capacitor on `NET2` is 100 nF.
Suggested ruling: [x] `defect` — [ ] `exception` (the 100 nF *is* the intended
part and the datasheet figure is a recommendation).

**Ruling (oracle Yue Xiangyu, 2026-09-19): `defect`.** The reading is right and
what is missing is the fault: NET2 carries 100 nF + 10 nF where the datasheet
asks for ≥1 µF of output bulk, and the oracle confirmed the project's own
convention for bulk decoupling rather than accepting the datasheet figure as a
recommendation. Landed as one defect record (`U11`, `decap-required-caps`,
WARN, holdout).

### B2. `decoupling-per-ic` (L1 heuristic) — 5 × WARN

> `U1 / U8 / USB1 / U7 / U6: none of its pin nets contains a capacitor.`

Evidence: L1 matches designator prefixes only — it cannot tell a supply pin from
a signal pin, and any `C*` part counts as a capacitor. `USB1` is a connector.
Suggested ruling: [x] `observation` (heuristic limitation, record it once) —
[ ] `defect` for named refs — [ ] `exception`.

**Ruling (oracle Yue Xiangyu, 2026-09-19): `observation`.** Recorded once, not
as five item records: the heuristic limitation is the finding, and the rule is on
M2's retirement list. Consequence kept in view: with no item records these five
WARN findings stay in the harness's *unexplained* column, which is the same
column as "the oracle has not looked". The precision number is the same either
way (an exception record counts against it too) — what changes is only which
column reports it, and the record below says so out loud.

### B3. `xtal-load-caps` (L1 heuristic) — 1 × WARN

> `X1: no grounded capacitor found on net(s) OSC-IN, OSC-OUT.`

Suggested ruling: [ ] `defect` — [ ] `exception` (e.g. the load caps are inside
the crystal's own package, or the oscillator is driven externally).

**Ruling: PENDING.** The oracle's instruction is to land whatever Kimi's
confirmation says (2026-09-19); until it arrives this line is the only one
unruled, and it is what holds the `DRAFT` stamp and the empty `reviewed_by` on
the board's annotation set.

### B4. `shunt-sense-link` (L1 heuristic) — 1 × INFO

> `R43 (10mΩ): no IC pins found on its terminal nets IA / PGND.`

Evidence: the check is connectivity-only; a sense link running through a filter
network is invisible to it.
Suggested ruling: [x] `observation` — [ ] `exception`.

**Ruling (oracle Yue Xiangyu, 2026-09-19): `observation`.** The
connectivity-only check is correct about what it can see; the sense link runs
through the RC filter network it cannot walk. No verdict about the board. INFO
findings sit outside the high-priority precision denominator, so this one does
not move the graduation number.

### B5. `conn-usb-cc-pulldown` — UNKNOWN × 2

> `USB1 pin4: a readable value on USB1` / `USB1 pin10: a readable value on USB1`

The **pull-downs are present and correct** on the CH340G board (R24/R27, 5.1 k
per ST AN5225 Table 6). Here the connector's own pins are on nets, but no
resistor value is readable for them — a facts/parse gap, not a finding.
Suggested ruling: [x] `backlog` (facts) — [ ] `observation`.

**Ruling (oracle Yue Xiangyu, 2026-09-19): `backlog`.** The pull-downs are
present and correct in the design; what is missing is a readable value on
USB1's own pins, so the rule stays UNKNOWN. UNKNOWN produces no finding at all,
so this enters no precision denominator — it joins section C's queue.

---

## C. Facts backlog (this *is* the M2 priority list)

| rule | missing fact | parts affected |
|---|---|---|
| `pwr-supply-on-known-domain` | `supply_pins` | 15 (U1 U2 U3 U4 U5 U6 U7 U8 U9 U10 U12 U13 U14 U15 U16) |
| `pwr-domain-vs-range` | `v_operating` / `v_abs_max` | the same 15 |
| `decap-required-caps` | `required_caps` | the same 15 |
| `path-ldo-dropout` | `category` + `ldo` | the same 15 |
| `conn-nc-and-must-connect` | `nc_pins` / `must_connect` | the same 15 |
| `param-value-mpn-match` | a decodable EIA code in the MPN | 32 (C5 C6 C7 C8 C11 C15 C16 C17 C20 C21 C22 C23 C28…C33 C36 C38 C40 C42 C44 C45 R5 R7 R9 R10 R13 R14 R15 R16 R18 R20 R22 R23 R24 R27 R32) |
| `conn-library-pins` | a library resolver (the bridge) | all identified parts |
| `param-divider-output` | an input-range fact for `U7 pin5` | 1 |

**The 15 ICs above are the natural 011b batch** — they are the board's actual
silicon (`TLE5012BE1000`, `DRV8350SRTVR`, `CH340N`, `SN65HVD230DR`,
`REF2033AIDDCR`, `LM5164DDAR`, `TLP2981-30DBVR`, `TLV9062IDR`, connectors) and
one datasheet each closes five rules at once.

---

## D. What this board teaches the graduation set

30 duplicates in one board is the single strongest signal M1 has produced, and
it is a **parser-level** finding (`DesignModel.duplicate_designators`), not a
rule-level one. If the oracle rules A1 `defect`, this board becomes the
CONN-1 holdout board for 011e sec.2's "at least one real board in holdout".
