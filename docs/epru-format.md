# `.epru` / `.epro2` format notes (reverse-engineered)

Reverse-engineering date: 2026-09-12.
Fixture: `tests/fixtures/llc_board.epro2` — an LLC full-bridge secondary-side
board, `editorVersion 3.2.121`, PCB document `editVersion 3.2.91`, 3.0 MB,
11,798 records.

There was **no official documentation** when these notes were written;
everything below was derived by reading the fixture. An official (MIT) type
reference has since been published and every inference was re-checked against
it — see [§12 Calibration against the official V3
documentation](#12-calibration-against-the-official-v3-documentation). Each
claim is tagged:

- **[confirmed]** — directly observable in the fixture, or a measurement that
  only has one plausible reading.
- **[inferred]** — a reasonable reading that has *not* been cross-checked
  against editor rendering or a second board. Treat as a hypothesis.

Corrections to previously recorded facts are listed in
[§9 Deviations from the earlier survey](#9-deviations-from-the-earlier-survey)
— read that section first if you already know the format, then read §12.

---

## 1. Container

`.epro2` is a ZIP archive. **[confirmed]**

| Entry | Size | Note |
|---|---|---|
| `IMAGE/` | 0 | directory entry |
| `project2.json` | 141 B | project metadata |
| `LLC全桥副边.epru` | 3,091,255 B | the record stream |

```json
{
  "title": "LLC全桥副边",
  "cbb_project": 0,
  "editorVersion": "3.2.121",
  "introduction": "",
  "description": "",
  "tags": "[]"
}
```

- **Match the `.epru` member by extension, never by name** — the entry name is
  mojibake'd Chinese. **[confirmed]**
- A backup can contain more than one `.epru`; the largest is the project
  stream. The parser picks the largest. **[inferred]** (only one on the fixture)
- `editorVersion` (project) and `editVersion` (per-document) differ on the
  fixture: 3.2.121 vs 3.2.91. Record both. **[confirmed]**

## 2. Record framing

One record per line: `{envelope-json}||{body-json}|` followed by `\n`.
**[confirmed]**

```jsonc
{"type":"LAYER","ticket":1,"id":"[\"LAYER\",1]"}||{"layerType":"TOP","layerName":"Top Layer", ...}|
```

- Envelope fields: `type`, `ticket` (monotonic edit counter), optional `id`
  (either an opaque element id **or** a JSON array serialised as a string, e.g.
  `"[\"LAYER\",1]"`), optional `firstTicket` (ticket of the record that created
  this object). **[confirmed]**
- **Empty body**: a record may carry no payload, written as `{envelope}|||`.
  There is nothing to read, so the parser counts and skips it. 558 of 11,798
  records are like this. **[confirmed]** — this was **not** in the earlier
  survey.
- **Last line has no terminator and no trailing newline.** The fixture ends
  mid-`BLOB`. Tolerate it. **[confirmed]**
- Ids that are JSON arrays are the format's way of expressing a composite key.
  Parse them with `json.loads`; they are *strings* in the envelope.
  **[confirmed]**

## 3. The stream is a concatenation of documents

Every document starts with a `DOCHEAD` record whose body carries `docType`.
The record stream is not one flat board — it is a library plus the design.
**[confirmed]**

| docType | Count |
|---|---|
| SYMBOL | 83 |
| FOOTPRINT | 81 |
| DEVICE | 81 |
| DOCHEAD (schema) | — |
| BOARD | 1 |
| SCH | 1 |
| SCH_PAGE | 1 (1,821 records) |
| **PCB** | **1 (1,419 records)** |
| CONFIG | 1 |
| FONT | 1 |
| BLOB | 1 |

```jsonc
{"type":"DOCHEAD","ticket":68375}||{"docType":"FOOTPRINT","client":"20ac4b53a32a3d96",
 "uuid":"a29b576e85021282","updateTime":1772353699198,"version":"943d6248e79077b28fa49707e182de5c",
 "editVersion":"3.2.91","user":{"uuid":"a29b576e85021282"}}
```

**Consequence:** everything "board" comes from the single `PCB` document.
`LAYER` (2,628 records), `PRIMITIVE` (622), `ATTR` (2,420) and friends are
repeated once per document, which is why the whole-file census is dominated by
library content. Anything that counts records for board-level purposes must
segment first.

## 4. Units and coordinate frame

**All coordinates and dimensions are in mils (1/1000 inch).** 1 mil = 0.0254 mm.
**[confirmed]** — five independent measurements agree:

| Field (fixture value) | mil | mm | Why it is decisive |
|---|---|---|---|
| `VIA.viaDiameter` = 39.37 | 39.37 | **1.000** | a standard 1 mm via |
| `VIA.holeDiameter` = 19.685 | 19.685 | **0.500** | 0.5 mm drill, half the via |
| outline 6102.3622 × 3149.6063 | — | **155.00 × 80.00** | a sane board size |
| C7 pad pitch 295.28 (2 × 147.64) | 295.28 | **7.50** | footprint is `CAP-TH_L12.5-W5.0-P7.50-D1.2` |
| C7 `hole.width` = 47.244 | 47.244 | **1.20** | that footprint's `D1.2` |
| `LINE.width` = 60 | 60 | 1.524 | plausible power trace |

**y increases upwards** (right-handed). **[inferred, but tightly constrained]**
The outline rectangle is `["R", -1.811, -3.189, 6102.3622, 3149.6063, 0, 150]`
and *every* copper coordinate on the board is negative in y — pads span
y = -3034 … -94, vias/tracks y = -3075 … -186. That only fits inside the
outline if the rectangle's height runs along **−y**, i.e. the board occupies
y = -3.19 … -3152.80. Under the alternative reading (height along +y) all
copper would sit off the board, which is impossible. A regression test asserts
that no element falls outside the outline.

Component rotation: `angle` is in degrees, positive **anti-clockwise** in that
right-handed frame. **[inferred]** — not verified against the editor, and the
fixture's angles (0 / 90 / 180 / 270 / -90) are symmetric enough that a
sign error would not show up in bounding boxes.

## 5. Layers

`LAYER` records inside the PCB document map `layerId` → name. Copper layers are
those with `layerType` in `{TOP, BOTTOM, SIGNAL}`. **[confirmed]** (the type
names are literal; the "copper" classification is **[inferred]** from the names).

| id | layerType | name |
|---|---|---|
| 1 | TOP | Top Layer |
| 2 | BOTTOM | Bottom Layer |
| 3 | TOP_SILK | Top Silkscreen Layer |
| 4 | BOT_SILK | Bottom Silkscreen Layer |
| 5 | TOP_SOLDER_MASK | Top Solder Mask Layer |
| 6 | BOT_SOLDER_MASK | Bottom Solder Mask Layer |
| 7 | TOP_PASTE_MASK | Top Paste Mask Layer |
| 8 | BOT_PASTE_MASK | Bottom Paste Mask Layer |
| 9–10 | *_ASSEMBLY | assembly layers |
| **11** | **OUTLINE** | **Board Outline Layer** |
| 12 | MULTI | Multi-Layer (through-hole pads live here) |
| 13 | DOCUMENT | Document Layer |
| 14 | MECHANICAL | Mechanical Layer |
| 15–46 | SIGNAL | Inner1 … Inner32 |
| 47–57 | HOLE / 3D_SHELL_* / DRILL_DRAWING / OTHER (Ratline) | … |
| 71–100 | CUSTOM | Custom1 … Custom30 |
| 361 | SUBSTRATE | Dielectric1 |

## 6. Records that carry board geometry

### 6.1 `COMPONENT` — a placed instance **[confirmed]**

```jsonc
{"type":"COMPONENT","ticket":67151,"id":"ef9d4d4060179ba4","firstTicket":58058}||
{"partitionId":"","groupId":0,"layerId":1,"x":5175.0035,"y":-170,"angle":180,
 "attrs":{"Unique ID":"gge2b62e3e2007d9e5c","Channel ID":"$1I145082",
          "Origin Footprint":"CAP-TH_L12.5-W5.0-P7.50-D1.2","Contributor":"LCSC",
          "spicePre":"C","nameAlias":"Capacitance"},"locked":false,"zIndex":-1}
```

`x`/`y` are the placement origin in board coordinates, `angle` the rotation.
The component carries **no pads** — see 6.3.

### 6.2 `ATTR` — attributes hanging off another object **[confirmed]**

```jsonc
{"type":"ATTR","ticket":67155,"id":"ef9d4d4060179ba4e12","firstTicket":58062}||
{"parentId":"ef9d4d4060179ba4","layerId":3,"x":5450.0035,"y":-135,
 "key":"Designator","value":"C7","keyVisible":false,"valueVisible":true,
 "fontFamily":"default","fontSize":45,"strokeWidth":6,"angle":360,...}
```

`parentId` links to the owning object. The keys that matter for review are
`Designator`, `Device` and `Footprint`:

| key | value | used for |
|---|---|---|
| `Designator` | `C7` | the human reference — the key of `DesignModel.components` |
| `Device` | `be59313648131898` | **uuid of a DEVICE document** — library metadata (§10) |
| `Footprint` | `ee8589d6ab3bfe1c` | **uuid of a FOOTPRINT document** — pad shapes |

**[confirmed]** — on the fixture: 47 `Designator`, 47 `Device`, 43
`Footprint` (the 4 without a footprint also have no pads). `Device` values
resolved **47/47** against the 81 DEVICE documents.

Note the two uuid-valued keys are easy to confuse with names: the PCB carries
*no* `Value` attribute at all on this fixture (value comes from the DEVICE
document, §10), and `COMPONENT.attrs["Origin Footprint"]` is the footprint
the part was **imported** with, which goes stale when the designer swaps it
(measured: C1 has `Origin Footprint` `CAP-TH_L7.9-W3.5-P7.50-D0.5-S2.4` but
sits on the FOOTPRINT titled `CAP-SMD_L8.0-W6.0-LS11.4`).

### 6.3 `PAD` — pad shape, in a FOOTPRINT document, footprint-local **[confirmed]**

Pads are **not** in the PCB document. They live in the FOOTPRINT library
document and are expressed relative to the footprint origin.

```jsonc
{"type":"PAD","ticket":25,"id":"e9"}||
{"groupId":0,"netName":"","layerId":12,"num":"1","centerX":-147.64,"centerY":0,
 "padAngle":0,"hole":{"holeType":"ROUND","width":47.244,"height":47.244},
 "defaultPad":{"padType":"ELLIPSE","width":70.866,"height":70.866},
 "specialPad":[],"padOffsetX":0,"padOffsetY":0,"relativeAngle":0,"plated":true,
 "padType":"NORMAL","topSolderExpansion":2,...}
```

- `layerId` 12 (MULTI) = through-hole; 1 = top-side SMD. **[inferred]**
- `hole` present ⇒ through-hole; absent ⇒ SMD. **[inferred]**
- `netName` is **empty here** even on the board — the net comes from `PAD_NET`
  (6.4). **[confirmed]**
- `padAngle` / `relativeAngle`: rotation of the pad shape and of the pad inside
  the component. The parser records `padAngle` but does not apply it to the
  position. **[inferred — unused]**

### 6.4 `PAD_NET` — pad ↔ net association **[confirmed]**

```jsonc
{"type":"PAD_NET","ticket":67152,"id":"[\"PAD_NET\",\"ef9d4d4060179ba4\",\"1\",\"e9\"]","firstTicket":58059}||
{"partitionId":"","padNet":"$1N144224","padLen":null,"attrsMap":{}}
```

The id is a **4-tuple**: `["PAD_NET", <component id>, <pin number>, <pad element id>]`.
So the association is: this pin of this placed instance of this footprint pad
sits on `padNet`. Indexing by `(component, pad id)` with a `(component, pin)`
fallback resolved all 47 components on the fixture.

The official `TPadNet` type puts the same triple **in the body** —
`componentId`, `padNum`, `padId`, all required — alongside `padNet`. The
fixture (editVersion 3.2.91) predates that and carries only `padNet`, so the
parser accepts either: body fields first, id tuple as fallback. **[confirmed —
both forms now supported]** The official type also requires `padLen` and
`propagationDelay` (3.4+); neither appears on the fixture.

Only **121 of 390** `PAD_NET` records carry a body (the rest are the empty-body
form from §2). 11 instantiated pads end up without a net — plausibly
mechanical / mounting holes. **[confirmed count, inferred reason]**

### 6.5 `VIA` **[confirmed]**

```jsonc
{"type":"VIA","ticket":66940,"id":"e81b6a6b48f31806"}||
{"partitionId":"","groupId":0,"netName":"CHS","ruleName":"","centerX":2560,"centerY":-2500,
 "holeDiameter":19.685,"viaDiameter":39.37,"viaType":"NORMAL",
 "topSolderExpansion":null,"bottomSolderExpansion":null,"locked":false,"unusedInnerLayers":[]}
```

Has a direct `netName`; no `layerId` (vias span the stack).

### 6.6 `LINE` — a straight track **[confirmed]**

```jsonc
{"type":"LINE","ticket":68006,"id":"07c8e25c3fa445ec"}||
{"partitionId":"","groupId":0,"netName":"CHG","layerId":1,"startX":2345,"startY":-2970,
 "endX":2265,"endY":-2970,"width":60,"locked":false,"zIndex":-1}
```

### 6.7 `POLY` — polygon; two very different roles **[confirmed]**

Board outline:

```jsonc
{"type":"POLY","ticket":65328,"id":"e0","firstTicket":1589}||
{"groupId":0,"netName":"","layerId":11,"width":10,
 "path":["R",-1.811,-3.189,6102.3622,3149.6063,0,150],
 "polyType":"BOARD_OUTLINE","locked":false,"zIndex":-1}
```

Ordinary polygon (105 of 106 in the PCB document):

```jsonc
{"type":"POLY","ticket":67534,"id":"707d9937a87845a5"}||
{"groupId":0,"netName":"","layerId":6,"width":118.1102,
 "path":[2193.7905,-2523.7905,"L",2279.998,-2609.998,2279.998,-2709.996],
 "polyType":"NORMAL",...}
```

- `polyType` is the discriminator: exactly one `BOARD_OUTLINE` per board.
  **[confirmed on this fixture]**
- The `NORMAL` polygons on this board mostly have an empty `netName` and sit on
  layers such as 6 (bottom solder mask), so they are **not all copper** — some
  are mask openings / keep-out style shapes. **[inferred]**
- `path` rectangle form: `["R", x, y, w, h, rotation, cornerRadius]`.
  **[inferred]** — the fixture cannot distinguish `(x, y, w, h)` from
  `(x1, y1, x2, y2)` because `x` ≈ 0; the height-along-−y part *is* forced by
  the copper coordinates (§4).

### 6.8 `FILL` — filled region, usually a real pour **[confirmed]**

```jsonc
{"type":"FILL","ticket":69814,"id":"de532d473516ee3b","firstTicket":66135}||
{"groupId":0,"netName":"CHS","layerId":1,"width":0.2,"fillStyle":"SOLID",
 "path":[[1545,-2770,"L",1270,-2770,1225,-2725,1225,-2625,1520,-2330, ... ,1545,-2770]],
 "isBridgingCopper":false,"networkList":[],"refs":[null]}
```

Note the path is **nested one level deeper** than `POLY`'s. `netName` is
populated, so this is the record type that actually carries pours with nets
(25 of them in the PCB document).

### 6.9 `POURED` — the result of pouring **[inferred]**

```jsonc
{"type":"POURED","ticket":58344,"id":"[\"POURED\",\"e294\"]","firstTicket":1612}||
{"pourFill":[{"strokeWidth":0,"fill":true,
  "path":[73.33,-93.9,"L",76.39,-96.96,73.31,-96.96,"ARC",0.1803,73.298,-96.96008,"L", ...]}]}
```

Only 4 on the fixture. Its id tuple names the element it was poured from; the
parser tries to borrow that element's net. The `ARC` command appears only here
and carries three numbers — `[sweep, x, y]`, where the first is an angle
(**[inferred]**: values like 45.0, 28.27, 50.80 are angles, not coordinates;
0.1803 is probably the same angle in radians). The parser drops the sweep and
keeps the point.

> **Coordinates warning (found the hard way).** `POURED.pourFill[].path` is
> **not in board coordinates**. Measured on the fixture: every point falls in
> a small local range (y = 22 … 78) while the board spans y = 208 … 790 in the
> same sign convention. Feeding those points into a bounding box silently
> corrupted every geometry query (248 of 481 points "outside the outline").
> The parser therefore keeps the record — it is real copper — but leaves its
> `points` empty. **[confirmed by measurement; reason inferred]** The official
> type confirms the field is `pourFill: TPourFill[]` and says nothing about
> the coordinate space.

### 6.10 `NET` — net metadata, not geometry **[confirmed]**

```jsonc
{"type":"NET","ticket":69974,"id":"[\"NET\",\"$1N144223\"]","firstTicket":57540}||
{"netType":null,"specialColor":null,"retLine":true,"differentialName":null,
 "isPositiveNet":false,"equalLengthGroupName":null}
```

73 in the PCB document, 47 of them empty-body. Net *names* on the PCB side are
a mix of schematic names (`DC-`, `DC+`, `CHS`, `DHS`, `CHG`, `CLG`, `DHG`,
`DLG`) and internal ids (`$1N144223`). **[confirmed]**

## 7. Records present but not consumed

Counted in `ParseStats.unconsumed_types` so it stays obvious what else the
format carries: `RULE` (242 whole-file), `RULE_SELECTOR`, `RULE_TEMPLATE`,
`PRIMITIVE`, `ELE_PLACEHOLDER`, `META`, `CANVAS`, `ACTIVE_LAYER`, `LAYER_PHYS`,
`PANELIZE`, `PREFERENCE`, `SILK_OPTS`, `DIMENSION`, `STRING`, `NET`, `GROUP`.

Two of them are worth a future task:

- **`RULE` / `RULE_SELECTOR`** — the design rules (`safeClearance`,
  `trackWidth`, …) with per-net selectors. This is the board's own rule set and
  is the natural input for a real DRC pass.
  ```jsonc
  {"type":"RULE","ticket":74,"id":"[\"RULE\",\"SAFE\",\"safeClearance\"]"}||{...}
  {"type":"RULE_SELECTOR","ticket":59675,"id":"[\"RULE_SELECTOR\",[\"NET\",\"VS2\"]]"}||{...}
  ```
- **`STRING` / `TEXT`** — silkscreen text (including Chinese: `全桥LLC副边输出`).

`BLOB` (1) is a base64 SVG (`data:image/svg+xml;base64,...`) and is the
truncated last line of the fixture.

## 8. Parser behaviour

`boardwise.parsers.epru`:

- One streaming pass: read the zip member → split lines → decode envelope and
  body → segment by `DOCHEAD` → keep only the PCB, FOOTPRINT and DEVICE
  documents → instantiate pads → build `BoardGeometry`. ~0.08 s for the 3 MB
  fixture, and ~0.09 s for geometry **and** netlist together.
- **One parse, two views.** `load_epro2_source()` returns an `Epro2Source`
  whose PCB document is walked **once** into a cached `PcbContext`.
  `build_board_geometry()` (copper) and `build_design_model()` (netlist) both
  read that context, so the two views cannot disagree and the stats are never
  double-counted.
- Unknown record types: counted in `stats.unknown_types`, never fatal.
- Records with an empty body: counted in `stats.empty_body_records`, skipped.
- Malformed lines (bad envelope, missing separator): counted in
  `stats.malformed_records`, skipped.
- No PCB document: returns an empty `BoardGeometry` rather than raising, so
  batch runs survive a schematic-only backup.
- `stats.records_by_type` is the **whole-file** census; `stats.pcb_records`
  and the element lists are PCB-document only. Do not compare them directly.

## 9. Deviations from the earlier survey

The notes in `docs/api-survey.md` and the task brief were right about the
container and the framing, but the following corrections matter:

1. **The record stream is 252 concatenated documents, not one board.**
   `PAD 281 / LINE 680 / POLY 1022 / FILL 444` are *whole-file* counts. Inside
   the single PCB document: `PAD 0`, `LINE 49`, `POLY 106`, `FILL 25`,
   `VIA 257`, `COMPONENT 47`. Counting the whole file would mix 81 footprint
   libraries and 83 symbol libraries into the board.
2. **Pads are not in the PCB document.** They live in FOOTPRINT documents in
   footprint-local coordinates and must be instantiated per placement using the
   component's `Footprint` attribute plus `x`/`y`/`angle`.
3. **Empty-body records exist** — 558 of them (`{envelope}|||`), including 269
   `PAD_NET` and 186 `LINE`. Only 121 of 390 `PAD_NET` records carry a net.
4. **11,798 records, not 11,799** — the last line has neither terminator nor
   trailing newline (a truncated `BLOB`). The earlier count included the
   trailing newline as a record.
5. **`PAD_NET`'s id is a 4-tuple**, not just "a pad↔net table":
   `["PAD_NET", component, pin, footprint-pad]`.
6. **y increases upwards**, and the outline rectangle's height runs along −y.
   All copper on this board has negative y.
7. `editVersion` is per document (PCB: 3.2.91) and differs from the project's
   `editorVersion` (3.2.121); both are worth recording.

---

## 10. Library metadata: the DEVICE join → `DesignModel`

`.epro2` has no netlist file, so the netlist is rebuilt from the placed board:
`parsers/epro2_model.py` turns the same `Epro2Source` into the same
`DesignModel` that `parsers/enet.py` produces, so every L1 rule runs on either
input unchanged.

The join is **placement → DEVICE document**:

```
PCB ATTR key="Device" (value = DEVICE uuid)
      └─> DEVICE document, META record
             ├─ title        -> Component.value fallback, props["DeviceTitle"]
             └─ attributes   -> Value / Supplier Part / Manufacturer / ...
```

The DEVICE `META` is the official `TMDevice` (`title`, `source`, `tags`,
`images`, `attributes`). Attribute keys are the **same strings** the `.enet`
export uses, which is what makes the two inputs interchangeable for rules.

Measured on the fixture (47 placed components):

| `Component` field | source | filled |
|---|---|---|
| `designator` | `ATTR key="Designator"` | 47 / 47 |
| `value` | DEVICE `Value`, else DEVICE `title` | 47 / 47 (only **10** have a real `Value`) |
| `footprint` | FOOTPRINT doc `title` behind `ATTR key="Footprint"` | 43 / 47 |
| `lcsc_part` | DEVICE `Supplier Part` | 44 / 47 |
| `manufacturer` | DEVICE `Manufacturer` | 44 / 47 |
| `mpn` | DEVICE `Manufacturer Part` | 44 / 47 |
| `datasheet` | DEVICE `Datasheet` | 36 / 47 |
| `props` | DEVICE attributes + instance `attrs` + `Device` / `DeviceTitle` / `Footprint` / `FootprintName` | all |
| `pins` | footprint pads (`num`) + `PAD_NET.padNet` | 117 pads → 118 pins |

Deliberately **left empty**, with the reason, not silently faked:

- **`Pin.name`** — pin *names* live in SYMBOL documents, which are dropped at
  parse time to keep memory proportional to useful data. Recovering them
  would need a second join (placement → DEVICE → `attributes["Symbol"]` →
  SYMBOL `PIN` records) and 83 more retained documents. `.enet` models *do*
  carry names; `.epro2` models do not.
- **`Component.role` / `Component.block`** — stage-2 intent metadata, still
  unpopulated everywhere.

Two conventions worth knowing before you trust a value string:

- **`value` is a display string, not a parsed quantity.** Only 10/47 devices
  define `Value`; the rest fall back to the DEVICE title, which is what the
  editor shows (`10k`, `472M 1KV`, `US5M`, `火线输出`). Rules that parse
  values (`shunt-sense-link`, `xtal-load-caps`) therefore behave differently
  on `.epro2` and `.enet` for parts that have no `Value`.
- **Unset attributes are the literal string `"null"`**, not missing and not
  empty (`Manufacturer: "null"` on several parts). The parser normalises
  `"null"`, `"None"`, `"-"` and `""` to `""`.

### What differs from an `.enet`-sourced model

Same `DesignModel`, same rules, but three structural differences decide why
the two paths can report different findings for the *same* board:

1. **Only placed parts exist.** `.enet` lists every schematic component;
   `.epro2` only what reached the PCB. Parts not converted to the board are
   invisible to every rule.
2. **No pin names.** Evidence strings and any future name-based rule degrade
   to pin numbers (§10 above).
3. **`value` is a display string.** On `.enet` it is the `Value` attribute
   (33/50 populated on the `board24v` fixture); on `.epro2` it is `Value`
   **or the DEVICE title** (10/47 real `Value`). Value-driven heuristics —
   `shunt-sense-link` parses ohms, `xtal-load-caps` looks for `MHz`/`kHz` —
   therefore see a different string for parts whose value lives only in the
   device name. Both directions are real: the fallback makes passives
   parseable (`R1` → `"10k"` → 10 000 Ω) and makes semiconductors
   un-parseable (`Q1` → `"B3M040065H"` → `None`), which is the correct answer
   in both cases.

Measured on the fixture: `boardwise review tests/fixtures/llc_board.epro2`
reports 47 components / 25 nets / 0 ERROR / 7 WARN, all `decoupling-per-ic`
on `U1`–`U7` (this board's supply nets are named `DC+` / `DC-`, and no
`C`-prefixed part sits on a `U` pin net).

Net names come straight from `PAD_NET.padNet`. There is **no** id → friendly
name lookup: the 73 `NET` records in the PCB document only carry display
options (`retLine`, `specialColor`), and the `$1N…` identifiers are EasyEDA's
own auto-names for nets the designer never labelled. 25 nets are actually
used by pads on this board. **[confirmed]**

## 11. Encrypted and unreadable backups

EasyEDA Pro's *save as (local)* dialog offers an optional **encryption**
checkbox. An encrypted export is not readable by any of this:

- `.epro2` (encrypted) — not a ZIP at all. Detected with
  `zipfile.is_zipfile()`.
- `.eprj2` (the SQLite *project* database) — a real SQLite file whose
  `project_history` blobs are **aes-128-gcm** encrypted: key =
  `project_history.key` (32 hex chars → 16 bytes), IV = the history uuid (hex
  → 16 bytes), plaintext gzipped, 16-byte auth tag appended. Reverse-engineered
  from the desktop client's `app.js`; out of scope for this parser.
- A ZIP whose entries carry the encryption bit (general purpose bit 0).

All three are reported as `EncryptedProjectError` with the same advice —
*"if the export was encrypted, re-export it with that option disabled"* —
instead of a `BadZipFile` / `JSONDecodeError` stack. The CLI prints it and
exits `2`.

## 12. Calibration against the official V3 documentation

Reference: <https://github.com/easyeda/easyeda-pro-format-skill> (MIT), cloned
to `.ref/easyeda-pro-format-skill` (commit `b2170ff`, 2026-09-09). It publishes
per-primitive field tables and JSON Schemas for SCH_PAGE / SYMBOL / PCB /
FOOTPRINT / DEVICE and more. Note it describes a **newer** format revision
than the fixture (`editVersion 3.2.91`): several fields it marks required do
not exist on the fixture.

| Claim (§) | Official status | Fixture evidence | Verdict |
|---|---|---|---|
| Framing `{envelope}\|\|{body}\|`, last line unterminated (§2) | `SKILL.md` lines 58, 229–234 show exactly this | matches | **confirmed** |
| Document stream segmented by `DOCHEAD.docType` (§3) | `documents/*.md` are per-document | 252 documents | **confirmed** |
| Units are mils (§4) | not stated directly | 5 independent measurements (§4 table) | **confirmed (measured)** |
| `y` increases upwards, rectangle height along −y (§4) | not stated | all copper negative in y, inside outline | **still inferred** |
| `COMPONENT.angle` in degrees (§6.1) | `TMPcbComponent.angle` = 旋转角度（角度制） | present as `angle` | **confirmed** — and the parser also accepts `rotation`, which the V3 name suggests for `ATTR` |
| `ATTR.key` / `value` / `parentId` (§6.2) | `TPcbAttr` has all three | matches | **confirmed** |
| `Device` attribute → DEVICE uuid (§6.2, §10) | not documented | 47/47 resolve | **confirmed (measured)** |
| Pad shapes live in FOOTPRINT docs (§6.3) | `FOOTPRINT.md` lists `PAD` | 0 PAD in the PCB doc | **confirmed** |
| `PAD_NET` triple in the body (§6.4) | `TPadNet`: `componentId` / `padNum` / `padId` | not on the fixture; id tuple instead | **both forms supported** |
| `PAD_NET.padLen` / `propagationDelay` | required in `TPadNet` | absent | official docs are **newer** than the fixture |
| `LINE` / `FILL` / `POLY` fields (§6.6–6.8) | `line.md` / `fill.md` / `poly.md` match | match | **confirmed** |
| `polyType` `BOARD_OUTLINE` (§6.7) | `poly.md` enum includes `BOARD_OUTLINE` | exactly one | **confirmed** |
| `POURED.pourFill` path is local, not board space (§6.9) | type says only `pourFill: TPourFill[]` | y = 22…78 vs board 208…790 | **confirmed (measured), reason still unexplained** |
| `DEVICE.META` = `TMDevice` (`title` + `attributes`) (§10) | `primitives/DEVICE/meta.md` | 81/81 DEVICE docs match | **confirmed** |

Net result: **nothing in the earlier notes was contradicted**, two inferences
became measurements (units, the `Device` join), one bug was found and fixed
(`POURED` polluting the bounding box), and the official docs turned out to
describe a newer revision than the fixture — so the parser keeps tolerating
the older shape rather than switching to the published one.
