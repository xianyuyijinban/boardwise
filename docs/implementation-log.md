# Implementation log — the 0.3.9 → 0.3.14 machine-debugging arc

Merged record of what changed and why, including the root causes that cost
whole sessions. Written 2026-09-15 from the session notes; versions are
connector (`.eext`) versions — the Python side ships unversioned alongside.

## 0.3.9 — every member read guarded; the stack finally travels

*Symptom*: `sch.geometry` / `sch.readback` died with
`TypeError: Cannot read properties of undefined (reading 'prototype')`
while `sys.probe --checks`, the tab list and the top-level namespace scan kept
working. `document.current`'s `project` / `pcb` / `schematicPage` all read
`null` at once.

* What changed: `getState`, a new `readMember`, `geometryOf`, the probe's
  enumeration loop, `readback` and `snapshot`/`deepDump` all moved their
  property reads inside `try`; every failure is now *reported*
  (`meta.reasons` / `unreadable` / `problems`) instead of looking like an
  empty page. `blobLike()` replaced a bare `instanceof Blob`, which throws the
  same sentence when `Blob` is unbound.
* The instrument that mattered: `transport.ts` now puts the unexpected throw's
  `name` / `message` / **stack** into the `ActionError` `detail`, and the CLI
  prints it. Before this the stack was discarded, and the session was guesswork.

## 0.3.10 — the real root cause: a prototype read in a loop condition

0.3.9's stack arrived on the machine and pointed at
`walkPrototypeNames`'s `while` condition, column inside `Function.prototype`:

```js
while (current !== null && current !== undefined
  && current !== Object.prototype && current !== Function.prototype)
```

That property read sits outside every `try`. The host exposes `Function` as an
object whose `.prototype` access throws, so the loop condition killed the walk
before the per-level guards could run — which is why *every* caller of the
walker failed together and *nothing* that avoided the walker failed.

* Fix: the stop sentinels are read once, guarded, into `PROTOTYPE_STOPS`;
  the loop only does `includes`. A sentinel that cannot be read is dropped and
  the chain still terminates on `null`.
* `source-guard.test.mjs` now asserts the shipped bundle never contains
  `Function.prototype` (and that `PROTOTYPE_STOPS` is present, so the guard
  cannot pass against an empty file).

## 0.3.11 — the artifact can say which build it is

Two sideloads in a row looked successful while the editor kept executing the
previous bundle; the only symptom was a stack naming a line that had already
been fixed.

* `build.mjs` injects `__BOARDWISE_VERSION__` from `package.json` into both
  outputs; `src/version.ts` guards it with `typeof` so a build without the
  define answers `'unknown'` rather than throwing at load.
* `sys.probe` returns `connector: "<version>"` — **one CLI call settles which
  build is live**. `About…` leads with it too.
* Side finding, now a rule: a *successful* sideload resets the extension's
  storage, so the daemon's pairing fingerprint always changes. An unchanged
  fingerprint means the package was not replaced.

## 0.3.12 — the recon instruments

* `lib.symbol.get` (read-only): one library symbol, dumped whole — added
  because "we could not find pin geometry" had only ever been measured on the
  canvas path, and an absence nobody looked for is not an absence.
* Also carried the flag-rotation and derived-net-name fixes from the Python
  side (unversioned) on their first machine runs.

## 0.3.13 — `lib.device.get`, and the two-instance trap

* `lib.device.get` (read-only): `lib_Symbol.get` needs a *library* symbol
  uuid, and the only route to one is `lib_Device.get(...).association.symbol`.
  The netlist's `Symbol` property is project-local — measured: it answers
  `found: false` with and without the library uuid.
* Machine finding, now a rule: **the editor ran two extension instances at
  once** (manifest updated, long-lived evaluation stale), and they fought over
  the socket — the "connector disconnected" mid-draw that cost a whole run.
  Rule: delete the old extension *before* installing, and fully quit the
  editor process afterwards; clicking *Reconnect* only creates a second
  instance.

## 0.3.14 — the seventh path, and the dump that could not see plain properties

* Type-package audit turned up a path the F3 six-path table had missed:
  `SCH_PrimitiveComponent.getAllPinsByPrimitiveId(primitiveId)` and
  `ISCH_PrimitiveComponent.getAllPins()` return "器件引脚图元" — x/y/pinNumber/
  pinName/rotation/pinLength for the pins of a **placed** component. Both
  `@beta`, **no** "ADD since v4" marker, so 3.2.186 may have them.
  `createNetFlag(...)` (the real power/ground flag API, same `@beta`) is
  in the same class.
* New read-only `sch.component_pins` action wraps `getAllPinsByPrimitiveId`.
* `deepDump` falls back to the object's own keys when the `getState_*` walk
  yields nothing: `lib_Device.get` had answered `found: true, item: {}` on a
  device the editor had just placed, because `ILIB_DeviceItem` carries its
  data as plain properties rather than accessors.
* Generator bug fixed: `_CLASS_RE` required the class name to be followed
  directly by `{`, so every `implements`-carrying class — including both
  primitive namespaces — was silently skipped, and the probe table had no
  idea they existed.
* Probe table gained `sch_PrimitiveComponent` / `sch_PrimitivePin`; the
  anti-drift test's namespace list gained them too.

## Python-side (unversioned) — shipped with the 0.3.12–0.3.14 draws

* **`_editor_rotation`** — the file's instance rotation is clockwise in y-up
  space, the editor's `rotation` parameter turns the symbol the other way.
  Signature: every two-pin passive replayed at 90/270 came back with its pins
  exchanged while 0/180 were correct — the exact shape of a sign flip
  (negating leaves 0 and 180 alone, swaps 90 with 270). Applied at the single
  place the two conventions meet; the replay's own geometry keeps the golden
  angle. **The same correction had to be applied to `sch.place_power` a round
  later**: the seven flag symbols all keep their pin at (0, 0), so the
  netlist stayed clean and only the *visual* direction was wrong — which is
  why it hid behind a passing diff.
* **`candidate.scope`** — the netlist export is project-scoped, not
  page-scoped; leftover pages from earlier runs put 51 designators in one
  export. It is a hard stop, because a polluted candidate makes the whole
  verdict meaningless.
* **`_reconcile_derived_names`** — the editor names an unnamed cluster
  `$11N…` where the golden parser says `NET1..N`; renamed only on *exact*
  membership, so it cannot hide a real difference.
* **Hybrid pin mapping** — the library renamed twelve of USB1's pins to pad
  names and kept `13`/`14`, so neither "all by number" nor "all by name" can
  match it. Matching is now number-first for the surviving numbers and
  case-insensitive by name for the rest (`DN2` vs `Dn2`).

## Where the acceptance stands

17/17 placed, 1 drifted, 0 unmappable, 98 actions with the single expected
`export.render` failure. By membership, **every** connectivity difference
traces to USB1's swapped library symbol; the other sixteen parts are correct.
See `docs/component-diff-inventory.md` for the 25 component rows.

## Outcome — gate 3 passes (2026-09-15)

`total: 25 (component 25, net 0, pin 0)` — connectivity now matches the golden
exactly; the 25 remaining rows are the component-representation gaps
itemised in `docs/component-diff-inventory.md`.

* 修复 1 (GND flags): zero net differences — every GND member present. The
  root cause was `place_power` not going through the rotation correction.
* 修复 2 (USB1, real F3): zero pin differences — USB1 fully connected, via
  the seventh path (`getAllPinsByPrimitiveId`) and a **stub** strategy: the
  golden run is kept verbatim and gains one straight segment from the golden
  tip to the placed pin. Two earlier attempts that *re-routed* the wire both
  merged D+/D- into +5V, because inside a pin field a dozen pins 10 units
  apart any re-route crosses a neighbour — keeping the golden run and adding
  a stub is what held.

## 0.3.19 — the two defects the 0.3.18 acceptance run exposed

### J.1 — `modify`'s `otherProperty` replaces the whole map

Measured on C1 with a single-component probe, not inferred:

1. after the run, `sch.geometry` state showed
   `OtherProperty = {"Supplier Footprint": "0603", "Value": "", …}` — the footprint
   had landed, the value had not;
2. a probe writing only `Value=100nF` read back `Value="100nF"` with
   **`Supplier Footprint` blanked to `""`**.

So each `modify(primitiveId, {otherProperty: {key: value}})` call replaces the map,
and the draw's key-by-key loop kept only its last key. That is the whole of the 8
"Value empty" rows, and it was invisible because nothing read the write back.

* `sch.set_component_attribute` now takes `attributes: {…}`, reads the current map,
  merges, writes **once**, re-reads `getState_OtherProperty()`, and defines
  `applied` as "the read-back equals the target, key by key". It also reports
  `otherPropertyBefore/After`, `mismatched` and any `clobberedOtherKeys`.
* The draw flow checks `applied` and records `verify.attributes` as a **failure**
  when it is false — a caller that ignores the flag is how a silent no-op becomes
  a green report.
* `connector/tests/set-attribute.test.mjs` pins both behaviours against a fake
  host that models whole-map replacement, including "two consecutive writes with
  different keys do not erase each other" (§J.4).

### J.2 — the library-resolved name was replacing the diff operand

`draw.py` wrote the library footprint name (`C0603`) over the candidate's
`Supplier Footprint` (`0603`). §I had approved the name for `expect_footprint`
verification and side-by-side reporting only; using it as the operand makes a
mismatch **constructive** — it survives any improvement to the write. Removed:
the operand stays the netlist's `Supplier Footprint`, and the two vocabularies are
printed together (`label=… library=…`) for the reader.

### J.3 — an out-of-flow netlist export comes back empty

Documented in `docs/bridge.md` §10 item 9 rather than worked around. It is **not**
a save-timing problem: the draw already issues `sch.doc.save` immediately before
exporting. The export is coupled to something the draw flow holds. The
operational consequence is the important part — **a shell-side `sch.netlist` is
not evidence about the project**, so a cleanliness pre-check that trusts it can
report "0 components" on a page that is far from empty.

### The daemon trap, third occurrence

0.3.18's first run produced 20 consecutive `UNKNOWN_ACTION` responses because the
daemon was started before the new actions were registered and the action catalogue
is a load-time constant. Order of operations, now fixed: **register the action →
restart the daemon → install the extension → restart the editor**. Any step out of
order costs a whole cycle, and this is the third time it has.

## Acceptance — the closing run (2026-09-15/16)

```
GATE: components: 17  nets named: 27  wires: 57  NC pins: 12  naming: text  violations: 0
placement check: 17 parts, 1 drifted with the library version, 0 unmappable
executed 163 bridge actions, 1 failed   (export.render — NOT_IMPLEMENTED on this build)
diff vs golden (netlist export):
no differences — designs match
```

**component 0 / net 0 / pin 0**, with the three golden overrides printed at the
gate together with their provenance (R24/R27 → a real 0402 `0402WGF5101TCE` /
C25905, U3 → 2.2kΩ 0805 `0805W8F2201T5E` / C17520 — both chosen by
`lib.device.search` reading `footprintName`, not by a keyword's first hit).

### The last two defects, and why one of them was a false alarm

**R5 — junctions must be split (a real geometric defect).** The golden's VCC net
has a branch stub ending on the *middle vertex* of the run that leaves U1.16.
`sch_PrimitiveWire.create` merges polylines that share an endpoint into one
primitive, and the merged polyline came back with the pin tip buried
mid-polyline. Handing over the same geometry as segments that all **end** at the
junction fixed it — verified on the live page before changing any code.
`engines/replay.py::split_at_junctions` does that at planning time (and again
after F3 snapping, because a stub is a new run); `docs/schematic-conventions.md`
records it as **R5**. 45 runs became 57, and U1.16's own segment became
`[(310,716),(320,716)]` — a pin tip on an endpoint.

**The stale export (a measurement defect).** Even after R5 the run still
reported U1.16 unconnected — but the *page* was already correct: re-exporting
the same page moments later put U1.16 in VCC, and the full membership comparison
matched the golden net for net. The editor recomputes connectivity
asynchronously after wires land, so the export taken right after the last
`place_wire` describes the page as it was **before** that wire. A first read
that is simply early is indistinguishable from a broken board unless the harness
insists on a settled read.

`_settled_netlist()` now saves and exports until **two consecutive reads agree**
(up to four attempts), records how many attempts it took, and marks the verdict
as untrusted if it gave up. The verdict therefore rests on a read the harness
has reason to trust — and the difference between "I do not know" and "I know"
stays visible in the report.


## 0.4.0 — architecture guardrails (006c, 2026-09-16)

Baseline 291 / 142 / `tsc` clean → **368 / 161 / `tsc` clean**. New action face, so
the connector version moved to 0.4.0.

### The guards, and the two things writing them found

Three rules were stated and made executable in the same round, which turned out to
be the point: **both guards found live violations the moment they ran**.

1. **Contract drift.** `connector/tests/contract-drift.test.mjs` compares the
   `ACTIONS` catalogue with the `buildHandlers` registry (and, added here, the
   `docs/bridge.md` §4 table). Its first run found `sch.set_component_value` still
   registered in the connector under a name the catalogue had renamed in 0.3.18 —
   unreachable, because the daemon refuses anything outside `ACTIONS`, and
   invisible, because nothing compared the two lists. The table in `bridge.md` had
   drifted further: **eleven** actions were missing, seven of them for several
   rounds.
2. **The module rules.** `tests/test_layer_rules.py` encodes the layering. Drafting
   the section discovered that `core/candidate.py` was importing `_transform_point`
   — a private name — from `parsers/schematic.py` *inside a function body*, which
   both inverted the dependency arrow and hid it from a casual read.
   `transform_point` now lives in `core/geometry.py`. It returns a **tuple**, not
   `Point`: the result is used as a dict key against tuples, and the dataclass
   compares unequal to them, so "tidying" it into `Point` would have been a silent
   correctness bug in the middle of a refactor. Two more private names crossed the
   same boundary the other way (`engines/draw.py` taking `_field`/`_as_float` from
   `core/candidate.py`); both are now public in `core`, because a helper two layers
   share is part of the lower layer's interface.
3. **Coordinate spaces.** `tests/test_coordinate_guards.py` scans via `tokenize`,
   so only identifiers and numeric literals count — comments and docstrings must
   stay free, since `epru.py` legitimately lists `"CANVAS"` as an `.epru` **record
   type** and the parsers have to be able to *describe* the conversion they perform
   at their boundary.

### The framing layer, extracted

`parsers/epru_stream.py` (14 public names) now owns the `.epru` record stream: ZIP
reading, `||`-record decoding, `DOCHEAD` document splitting. The schematic parser
used to import a **private** `_load_epru_text` from the PCB copper builder just to
read a text file; it now imports `load_epru_text` from the framing module, and
`epru.py` keeps only pad/track/via geometry.

One deliberate deviation from the task's wording: **`ParseStats` is re-exported, not
moved.** It is defined in `core/geometry.py` and `BoardGeometry` carries one, so
relocating it into `parsers` would force `core` to import `parsers` — the exact
inversion this round fixed. The judgement standard was met regardless: *the
existing tests pass with zero modifications.*

### Creating a document is now the one gated action

`ACTIONS` entries gained a `risk` field with **no default**, so a new action cannot
be silently ungated: `read` / `write` / `create`, and only `create` is refused
without `confirm: true`. The check sits on the **daemon**, keyed on `risk` — not on
whether the entry lists `confirm` among its params, because that version fails
*open*: an entry that forgot to declare the parameter would never be refused. The
flag is consumed at the gate, so the connector has no concept of confirmation and
cannot be talked into creating something the daemon declined.

`doc.list` / `doc.open` / `pcb.doc.new` / `doc.rename` exist because every action
until now addressed "whatever page is focused" — a mix-up that cost two rounds. All
four were built on real `@public`/`@beta` entry points found by recon:
`openDocument` takes a document uuid and returns a **tab id** (which is what
`activateDocument` wants — a different type, easy to conflate),
`createPcb` mirrors `createSchematic`, and renaming dispatches to the three
per-kind `modify*Name` calls. Nothing was emulated, and **no delete API is used**.

### Verification

Both guards were deliberately broken and observed red before being restored:
removing the `sch.geometry` registration produced `actual: 0: 'sch.geometry'` from
the drift guard; injecting `mil_to_mm` + `25.4` into `engines/layout.py` produced
`layout.py:1134 uses 'mil_to_mm'` and `layout.py:1135 carries the conversion factor
25.4`; injecting `canvas_y` into `parsers/epru_stream.py` produced
`epru_stream.py:291 defines 'canvas_y'`.

### Withdrawal — `docs/bridge.md` §10, and the reading it was built on

The §10 item claiming "an out-of-flow netlist export comes back empty, because the
export follows the focused page" is **withdrawn**. 岳翔宇 traced it to his probe
parsing the payload **without reading `data.text`** — the netlist arrives as a JSON
string under `text`, so a consumer that reads `data` and stops sees an empty
netlist on a perfectly healthy editor. "Focused page" and "save ordering" were both
inferred from that bad reading.

What survives is the part that was measured behaviourally and reproducibly: **an
export taken immediately after a write can be stale**, because the editor recomputes
connectivity asynchronously. `_settled_netlist` (save+export until two consecutive
reads agree) is the fix and stays.


## 0.4.1 — the bridge-hardening round (004f, 2026-09-16)

Baseline 368 / 161 / `tsc` clean → **372 / 167 / `tsc` clean**. No new actions, so the
action catalogue is untouched; the daemon nevertheless has to be restarted, because
pairing and the handshake live in its Python.

### Withdrawn: "one connector per project"

Task 004f was specified as a per-project pairing table with `--project` addressing. The
premise was measured to be false first — `sys_Storage` is shared by the editor, not scoped
per project — so the table, `connectors.json` and `AMBIGUOUS_TARGET` were dropped **before
being built**, and the single-connector model stands (documented as `bridge.md` §10.24).
The thing that actually resets extension storage is **sideloading a build**, and that — not
project switching — is the only real cause of the `UNAUTHENTICATED` waves.

### Re-pairing, keyed on "is anyone attached"

An unattached pairing may now be re-taken: the record is overwritten, the audit says
`re-pairing` with the fingerprint it replaced, and the console announces it as a
*replacement* rather than a first pairing. Attached still means attached — displacing a live
peer is what pairing exists to prevent. Five existing tests asserted the old semantics (they
closed the paired connector and then expected a stranger to be refused); all five are
directly related and now keep the connector attached, or wait for `daemon.connector` to
actually become `None`. That wait matters: `await ws.close()` does not synchronously clear
the daemon's view, and a fixed sleep would be a guess about someone else's event loop.

### The bootstrap blind spot

"Restart the editor and it does not connect; only another restart helps." Two defects in
`index.ts` produce exactly that, and both were silent:

1. `void bootstrapAtModuleLoad()` had **no `.catch`**. `connectOnce()` is async, and by the
   time it can reject it has already taken the one-shot claim — so `activate()`, the self-arm
   and Reconnect are no-ops for the rest of the editor's life, with nothing in the log panel.
   Restarting looks like the fix because restarting is the only thing that re-runs the
   bootstrap.
2. When `eda` was not bound at module evaluation the bootstrap stood down permanently.

Both now log, release the claim, and retry on a bounded schedule (~29 s). The retry deserves
a word, because 0.2.3's 1 s/4 s probes are usually quoted as proof that "the host discards
timers": those probes never ran **because the bundle was not loaded at all**, which is 004d's
own fixed fact 2 — a timer that is never scheduled proves nothing. The one measured survivor
is a chain started during module evaluation (48 minutes, 274 audited connects), which is
exactly where these retries live. The five-cold-start acceptance is still open.

### One reader per fact

`document.current` derived its `type` from the split-screen tab tree, whose objects carry no
`documentType` on this build — so a schematic page in front was reported `unknown` while
`doc.list`, reading `getCurrentDocumentInfo`, named it correctly. Both now call one shared
`activeDocument()`, and the response says which read answered (`typeSource`) and whether it
was a fallback (`heuristic`). Two readers of the same fact with different answers is worse
than one wrong reader, because the disagreement itself is invisible.

### Which build was that?

`hello` now carries `connectorVersion`; the daemon records it in the audit's `client` line
(`… connector=0.4.1`) and, for older connectors that do not send it, as `(version unknown)`
— never refusing them. Twice a sideload that did not take looked successful while the editor
kept running the previous bundle; the handshake is the one moment every build passes through.
