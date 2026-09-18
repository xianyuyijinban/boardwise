# API & Format Survey — EasyEDA Pro

Recon date: 2026-09-12. Sources: `@jlceda/pro-api-types@0.4.25` (npm, published 2026-09-11)
and a real `.epro2` project backup (LLC full-bridge board, editorVersion 3.2.121).

## 1. Official `eda.*` API surface (from type definitions)

94 namespaces on the global `eda` object:

| Domain | Count | Namespaces |
|---|---|---|
| sch | 21 | sch_Document, sch_Drc, sch_Event, sch_ManufactureData, sch_Net, sch_Netlist, sch_Primitive(+Arc/Attribute/Bus/Circle/Component/Object/Pin/Polygon/Rectangle/Text/Wire), sch_SelectControl, sch_SimulationEngine, sch_Utils |
| pcb | 25 | pcb_Document, pcb_Drc, pcb_Event, pcb_Layer, pcb_ManufactureData, pcb_MathPolygon, pcb_Net, pcb_Primitive(+Arc/Attribute/Component/Dimension/Fill/Image/Line/Object/Pad/Polyline/Pour/Poured/Region/String/Via), pcb_RayTracerEngine, pcb_SelectControl |
| lib | 10 | lib_3DModel, lib_Cbb, lib_Classification, lib_Device, lib_Footprint, lib_LibrariesList, lib_PanelLibrary, lib_SelectControl, **lib_SimulationModel**, lib_Symbol |
| sys | 27 | sys_ClientUrl, sys_Dialog, sys_Environment, sys_FileManager, sys_FileSystem, sys_FontManager, sys_FormatConversion, sys_HeaderMenu, sys_I18N…, sys_WebSocket, sys_Window 等 |
| dmt | 11 | dmt_Board, dmt_EditorControl, dmt_Event, dmt_Folder, dmt_Panel, dmt_Pcb, dmt_Project, dmt_Schematic, dmt_SelectControl, dmt_Team, dmt_Workspace |

### Verdict: simulation

- `sch_SimulationEngine` exposes **only** `pushData(eventType, props)` — it feeds data into an
  already-running interactive simulation. There is **no programmatic "run sim → get waveforms" API**.
- `lib_SimulationModel` offers full CRUD for library simulation models, and its `modelType`
  literal is `'Ngspice'` — EasyEDA Pro's built-in simulator **is ngspice**, and the model
  library is API-accessible (upload/search/get).
- **Consequence for boardwise:** the external ngspice pipeline (schematic netlist → SPICE deck →
  external ngspice → waveform/spec comparison) is not a workaround, it is the only path. Being the
  same engine as the editor's, results can be cross-checked against in-editor simulation.
  The library model store may later serve as a model source for deck generation.

### Verdict: geometry & readback (for the future bridge)

Full primitive-level readback exists (`pcb_Primitive*.getAll`, pads/tracks/vias/pours with
geometry), plus helpers (`pcb_MathPolygon`, `sys_Math`, `pcb_RayTracerEngine`). DRC, netlist,
manufacture-data export all exposed. The bridge phase can rely on these; nothing here changes
the files-first plan.

## 2. `.epro2` project backup format (discovered, undocumented)

- `.epro2` is a **ZIP** containing `project2.json` (title/tags metadata) and one `*.epru`
  per project (entry name may be mojibake'd Chinese — match by extension).
- `.epru` is a line format: `{envelope-json}||{body-json}` terminated by `|\n`.
  The envelope carries `type`, `ticket`, `id`; the body carries the record payload.
- Record census on the fixture (11,799 records): PAD 281, PAD_NET 390, VIA 257, LINE 680,
  POLY 1022, FILL 444, NET 89, COMPONENT 98, PIN 265, WIRE 32, TEXT 63, RULE 242,
  LAYER 2628, LAYER_PHYS 135, plus DOCHEAD/ATTR/META/CANVAS/PANELIZE…

**This is full semantic geometry — per-pad net association (PAD_NET), tracks, vias, pours,
design rules — obtainable offline with no editor running.** It replaces Gerber as the primary
geometry input for EasyEDA boards. Gerber/drill parsing stays on the roadmap only for the
cross-EDA (KiCad/AD exports) phase.

### Risks & policy

- Format drift between editor versions (`editVersion` is recorded per document — parser must
  record it and stay tolerant: unknown record types are skipped-and-counted, never fatal).
- Writing/injecting this format is out of scope for the review engine (read-only).
- **Encryption**: the local save/export dialog offers *optional* password encryption
  (official prodocs). Default is off — plaintext ZIP+JSON (verified on fixture: no encrypted
  flag bits, plaintext records). Parser must detect encrypted/non-ZIP input early and fail
  with a clear "re-export without encryption" message.

### Official documentation discovered (2026-09-12, supersedes "undocumented" above)

- `github.com/easyeda/easyeda-pro-format-skill` (MIT) — **official V3 format docs packaged as
  an agent skill**: 13 document domains (incl. SCH_PAGE, PCB, FOOTPRINT, SIMULATION, rules),
  per-primitive field definitions, JSON Schemas, examples, and a `validate.js` checker.
  Confirms the reverse-engineered line format (`{type,id,ticket}||{data}`, DOCHEAD+CANVAS head).
- `github.com/easyeda/easyeda-pro-file-format-v2` — official V2 spec (legacy; V3 moved to
  key-value log records, V2 import/export still supported).
- **Consequences**: (1) parser assumptions must be cross-checked against the official schemas —
  all "guessed" semantics in `docs/epru-format.md` should be promoted to confirmed or corrected;
  (2) the generation phase gains an official, validated foundation — bulk board creation can be
  produced offline as format-valid `.epro2` and opened via the editor's own restore path,
  shrinking the bridge's scope further to interactive/incremental operations only;
  (3) the SIMULATION document domain is documented there — evaluate when the sim phase starts.

## 3. Declared surface of the namespaces the roadmap depends on

Source: `@jlceda/pro-api-types` text, extracted by `tools/api_names.py` (offline, complete —
no editor required). The generated table lives at `connector/src/api-names.ts`, and
`tests/test_api_names.py` fails if the two drift.

The extraction is deliberate rather than a convenience: on 2026-09-14 the on-machine probe
died on *every* namespace with `Cannot read properties of undefined (reading 'prototype')`,
because the editor's extension host hands out *exotic* objects whose
`getOwnPropertyNames`/`getPrototypeOf` throw. Enumerating the live object is a measurement that
can fail on exactly the object under measurement; `typeof ns[name]` cannot, because property
access walks the prototype chain as part of the language. So `sys.probe` grew a `checks` mode
that verifies a *named* list, and this table is the source of those names.

| Namespace | Type | Methods | Notable |
|---|---|---|---|
| `sch_ManufactureData` | `SCH_ManufactureData` | 13 | `getPngFile` / `getSvgFile` both `ADD since EDA v3.2.183` and both `@beta` — yet the 3.2.186 host answers nothing (see §4) |
| `dmt_EditorControl` | `DMT_EditorControl` | 20 | `openDocument` / `closeDocument` / `getSplitScreenTree` / `getTabsBySplitScreenId` — the tab-focus primitives 006c needs |
| `dmt_Schematic` | `DMT_Schematic` | 17 | `createSchematicPage` (thin) vs `createSchematic` (returned empty on a blank project, measured) |
| `dmt_Pcb` | `DMT_Pcb` | 7 | `getCurrentPcbInfo`, `getPcbInfo` |
| `sch_Document` | `SCH_Document` | 9 | `save` — the step that makes `sch.netlist` reliable |

Reproduce:

```bash
python tools/api_names.py sch_ManufactureData dmt_EditorControl    # table
python tools/api_names.py --methods-only dmt_Schematic             # paste-ready names
python tools/api_names.py --json dmt_Pcb                           # machine-readable
python tools/api_names.py --emit-ts connector/src/api-names.ts \
    sch_ManufactureData dmt_EditorControl dmt_Schematic dmt_Pcb sch_Document
```

## 4. Implications for the roadmap

1. Review engine inputs, priority order: `.enet` (done) → **`.epro2` geometry (next)** →
   Gerber/IPC-D-356 (cross-EDA phase).
2. Bridge phase contract confirmed: TypeScript connector against `@jlceda/pro-api-types`
   (Apache-2.0), apply + readback only.
3. Simulation phase: external ngspice; evaluate `lib_SimulationModel` as model source when
   the deck generator lands.
