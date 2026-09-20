# Triage — `board24v` (task 011e sec.3)

Board: `tests/fixtures/board24v.enet`
Model: **50 components, 42 nets**. Findings: **0 ERROR / 15 WARN / 27 INFO**
(after 011e sec.1.1; before it, all 27 of the INFO lines were sitting in the
VIOLATION column).

**Caveat that shapes everything below: this fixture is a netlist export
(`.enet`), not a project backup.** Consequences, both measured:

* `conn-duplicate-designators` can never fire here — duplicate detection lives
  in the schematic parser (`parsers/schematic.py`), which walks `SCH_PAGE`
  boundaries that a flat netlist does not have. It reports 0 on this board and
  that 0 says nothing about the board.
* There are no page-level or annotation facts to check either, so this board
  exercises the **facts** rules and almost nothing else.

That makes it a good *facts* holdout board and a poor general one; worth knowing
before it is assigned a split.

Rulings and their meaning are the same as in the graduation board's triage file
(`defect` / `exception` / `observation` / `backlog`). `reviewed_by` stays empty
until every line is ruled.

---

## A. Batch rulings

### A1. `param-value-mpn-match` — 15 × WARN, and **all three kinds look like the decoder, not the board**

> `C115: board value 0.00033 F contradicts its MPN ('PA50V330M10x15' decodes to
> 3.3e-11 F) -- BOM and schematic disagree`

| kind | refs | board value | MPN | "decoded" | what the code actually is |
|---|---|---|---|---|---|
| A1a | `C115` `C116` `C47` `C50` `C51` `C52` | 330 µF | `PA50V330M10x15` | 3.3e-11 F | an **aluminium-electrolytic part number**: `330M` = 330 µF ±20 %, `50V`, `10×15 mm`. Not EIA at all. |
| A1b | `C53` `C54` `C55` `C56` `C57` `C58` | 10 µF | `HGC1206R5106K500NSPJ` | 5e-11 F | the decoder read `500` out of `K500N`, which is the **500 V rating**; the capacitance code is `106` = 10 µF, and it agrees with the board. |
| A1c | `R39` `R40` `R43` | 0.001 Ω | `RE2512F3R001` | 0 Ω | the decoder read `001` as "00 × 10^1"; the part uses the **four-character R notation** `R001` = 0.001 Ω (a current-sense shunt), which is exactly the board value. |

In all three the board is right and the decode is wrong: A1b and A1c are
*agreements* being misread as contradictions.

Suggested ruling: [ ] `exception` × 15, with the note naming the decoder gap.
[ ] `defect` — only if the oracle judges the MPN/value pair suspect anyway.

**Rule-side consequence (M2, not this task):** `rules/values.py::mpn_value_code`
needs (a) the four-character R-notation, (b) to ignore voltage/ dielectric
tokens, and (c) a plausible-range guard so a "0 Ω" or "50 pF" decode of a
power part is rejected rather than reported. Under 011e sec.6 nothing is
retuned here to move a number; this is recorded for the next rule batch.

### A2. `param-rc-cutoff` — 27 × INFO, **no ruling needed**

These are measurements, not defects (011e sec.1.1 moved them out of VIOLATION).
Grouped, they say one thing:

* `R34` / `R36` / `R37` (10 Ω) in series with the `VM` rail against six 330 µF
  bulk capacitors → **fc ≈ 48 Hz**; the same three resistors against the small
  ceramics on the same net run up to **fc ≈ 1.6 MHz**.

The 10 Ω parts are evidently rail damping/filtering, and the numbers are what a
10 Ω/330 µF bank should produce. Suggested: [ ] `observation` (record once:
"the VM rail's damping network reads fc 48 Hz–1.6 MHz across the capacitor
bank") — [ ] nothing.

---

## B. Single items

### B1. `conn-nc-and-must-connect` — UNKNOWN × 3

`U18` (`DRV8350SRTVR`), `U19` / `U21` (`HX PZ2.54-2x6P TP`): the library has no
`nc_pins` / `must_connect` records. Not a finding — **backlog**.

### B2. `decoupling-per-ic` / `xtal-load-caps` / `shunt-sense-link` — silent

All three L1 heuristics report nothing on this board. No ruling required; noted
because it means this fixture gives no signal on the L1 family.

### B3. `conn-usb-cc-pulldown` — silent

No connector on this board carries a `pull_required` identity, so the rule has
nothing to say. No ruling required.

---

## C. Facts backlog (this *is* the M2 priority list)

| rule | missing fact | parts affected |
|---|---|---|
| `conn-nc-and-must-connect` | `nc_pins` / `must_connect` | `U18` `U19` `U21` |
| `pwr-supply-on-known-domain` | `supply_pins` | `U18` `U19` `U21` |
| `pwr-domain-vs-range` | `v_operating` / `v_abs_max` | `U18` `U19` `U21` |
| `decap-required-caps` | `required_caps` | `U18` `U19` `U21` |
| `path-ldo-dropout` | `category` + `ldo` | `U18` `U19` `U21` |
| `param-value-mpn-match` | a decodable EIA code in the MPN | 8 (`C4` `C48` `R33` `R34` `R35` `R36` `R37` `R38`) |
| `conn-library-pins` | a library resolver (the bridge) | all identified parts |

Three parts close five rules at once — the smallest useful 011b batch of the
two boards. `DRV8350SRTVR` also appears on the graduation board as `U2`, so one
datasheet would serve both.

---

## D. Honest limitations

* **No `defect` candidates on this board.** Every WARN it produced is
  attributable to the decoder (A1) or to a heuristic (none here), and the rest
  is backlog. If the oracle agrees, this board becomes an **exception-heavy
  holdout board**: useful precisely because a rule that starts over-firing on it
  would show up as precision loss rather than as a missed defect.
* `.enet` has no pages ⇒ no CONN-1 signal, as above.
