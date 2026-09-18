# Component-diff inventory — draw acceptance 2026-09-14

Every `[component]` row from the clean-run acceptance report
(`draw_accept.txt`, 25 rows on 17 placed parts), itemised as 岳翔宇 asked:
device / field / both sides / root cause / what would actually close it.

**"导出怪癖" is not an exemption.** Each row below states the mechanism and
the concrete fix; whether a row is *excusable* under §J is a call only the
task book's §J text can make — that text is not in this repo, so no row here
claims a §J clause on its own.

## Cross-check performed first

Before classifying, the placed parts were identified by `DeviceName` /
`Supplier Part` in the editor's own netlist, against the golden's
expectation. **All 17 devices are the intended ones**:

| Part | Placed `DeviceName` | `Supplier Part` | Verdict |
|---|---|---|---|
| U1 | CH340G | C14267 | matches golden |
| U3 | FRC0805J471 TS | C2907329 | device matches golden's DEVICE META title |
| U5 | RT9013-33GB | C47773 | matches (SOT-23-5 LDO) |
| C1 | CC0603KRX7R9BB104 | C14663 | 100nF 0603 — matches |
| C3 | CC0402JRNPO9BN300 | C107004 | 30pF 0402 — matches |
| C25 | CC0402JRNPO9BN300 | C107004 | 30pF 0402 — matches |
| C6 | CC0603KRX7R9BB104 | C14663 | 100nF 0603 — matches |
| C7 | CC0603KRX7R9BB103 | C100042 | 10nF 0603 — matches |
| H1 | PZ254V-11-03P | C2937625 | 2.54 mm header — matches |
| LED1 | GL0603UG01 | C51933293 | 0603 LED — matches |
| USB1 | TYPE-C 16PIN 2MD(073) | C2765186 | **identical** to golden `device_name` |
| X1 | X322512MSB4SI | C9002 | 3225 package — matches |
| R24 | TCH35P5K10JE | C2641839 | 5.1 K — **package unconfirmed** (open question) |
| R27 | TCH35P5K10JE | C2641839 | 5.1 K — **package unconfirmed** (open question) |

So the placement resolution (F1) is right; what differs is *which field the
two sides read*.

## Group A — footprint: golden name vs candidate uuid (20 rows)

`golden='0603' candidate='ae4da87b67db9979'` shape, on C1, C3, C25, C4, C5,
C6, C7, C9, H1, LED1, R24, R27, U1, U3, U5, USB1, X1.

* **Golden side**: the schematic's `Supplier Footprint` attribute — a
  human-readable package name (`0603`, `SOP-16`, …).
* **Candidate side**: the netlist export's `Footprint` property, which on this
  host is a **footprint document uuid**, not a name. `Supplier Footprint` is
  empty in this export, so the candidate builder falls back to `Footprint`
  and a uuid reaches the diff.
* **Same device on both sides** (table above), so for 18 of the 20 rows this
  is a *representation* difference, not a wrong part.
* **Close it by translating, not by exempting**: `lib_Footprint.get(uuid)`
  (same shape as `lib_Device.get`, which the recon actions already exercise)
  would turn the uuid back into a footprint name so both sides compare like
  for like. That is a real work item, not a waiver.
* **Two rows are a genuine open question**: R24/R27 — golden says `Res_0402`
  / `0402`, the resolved device is `TCH35P5K10JE`, whose package is not
  decodable from its name. Until someone confirms that part is 0402, these
  two are *unresolved*, not explained.

## Group B — value: golden has one, candidate empty (8 rows)

C1 `100nF`, C25 `30pF`, C3 `30pF`, C6 `100nF`, C7 `10nF`, R24 `5.1K`,
R27 `5.1K`, U3 `1kΩ` — candidate `''`.

* **Mechanism**: the draw flow never sets `Value`. Placement by LCSC fills
  `DeviceName` / `Supplier Part` but leaves the schematic `Value` attribute
  empty, and the netlist exports that emptiness.
* **Close it by writing the attribute**: `sch_PrimitiveComponent.modify`
  exists; after placing, set `Value` from the golden model. That is a real
  fix and would clear all eight rows.
* **One row is a data question, not a tool gap**: U3 — golden `Value=1kΩ`,
  but the *library device itself* is `FRC0805J471 TS` (EIA code 471 = 470 Ω).
  The golden's 1 kΩ is a stale local override sitting on the instance
  (documented in `parsers/schematic.py`'s `resolve_component_identity`).
  Writing it back would put a wrong value on the board. **This row needs a
  human decision on which side is true**, and it is the one place where the
  golden is known-bad.

## Summary

| Group | Rows | Nature | Action that closes it |
|---|---|---|---|
| A footprint name vs uuid | 20 | representation (+2 unresolved R24/R27 package) | resolve uuid → footprint name |
| B value empty | 8 | attribute never written (1 of them: golden data wrong) | write `Value` after placement; decide U3 |

§J mapping is deliberately left blank: the task book's §J is not in this
repository, so claiming a clause here would be inventing it.
