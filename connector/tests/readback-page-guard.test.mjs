/**
 * 527B B4: `pcb.readback` / `sch.readback` must refuse a page the window does
 * not have in front, instead of reading the other namespace and dying.
 *
 * The defect, measured on the machine by the user (2026-09): with a schematic
 * page in front, `pcb.readback` called the PCB component namespace anyway; the
 * host answered `null` (or a list with null holes) and the reader turned that
 * into `TypeError: Cannot read properties of null (reading 'map')`. The same
 * defect surfaced as `pcb.geometry` returning `bboxes: 0`, because its id list
 * comes from this readback.
 *
 * What is pinned here:
 *
 * 1. **A precise mismatch is refused, in both directions.** The reading that
 *    counts as precise is `activeDocument`'s direct getter
 *    (`dmt_SelectControl.getCurrentDocumentInfo`) — the same string
 *    `document.current` reports as `typeSource`. The refusal names what was
 *    asked for, what is actually open, and how to fix it, and *nothing is
 *    read*: no invented list, no silent empty one.
 * 2. **The matching page still reads.** The guard must not cost the ordinary
 *    path anything.
 * 3. **A heuristic focus is not a refusal.** When only the per-kind fallbacks
 *    answer, the connector cannot tell "a PCB is open" from "a PCB exists", so
 *    the read proceeds exactly as before — and the null holes the host leaves
 *    behind are *reported* (`unreadable`) rather than dropped, which is what
 *    keeps a wrong page from looking like an empty board.
 *
 * All offline, against a fake `eda`; nothing here touches an editor.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { buildHandlers } from '../dist/esm/actions.mjs';

/** `EDMT_EditorDocumentType` values, as the type package declares them. */
const DOC_TYPE = { SCHEMATIC_PAGE: 1, PCB: 3 };

/** An editor object whose `getState_*` getters sit on the prototype. */
function primitive(state) {
  const proto = {};
  for (const [key, value] of Object.entries(state)) {
    proto[`getState_${key}`] = () => value;
  }
  return Object.create(proto);
}

const PCB_COMPONENT = () => primitive({
  PrimitiveId: 'c1', Designator: 'U1', Name: 'CH340C',
  Footprint: 'SOP-16', Supplier: 'LCSC', SupplierId: 'C84681',
  Manufacturer: 'WCH', X: 100, Y: 200, Rotation: 90, Layer: 1,
});

const SCH_COMPONENT = () => primitive({ PrimitiveId: 's1', Designator: 'R1', Net: 'TX', X: 10, Y: 20 });

/**
 * A window with one schematic page and one PCB, and a settable focus.
 *
 * `focus: 'none'` removes `dmt_SelectControl` altogether — the shape that
 * leaves only the per-kind fallbacks, i.e. the heuristic case.
 */
function fakeWindow({ focus = 'pcb', pcbItems, schItems } = {}) {
  const calls = { pcbGetAll: 0, schGetAll: 0 };
  const activeUuid = focus === 'pcb' ? 'pcb-1' : 'page-1';
  const activeType = focus === 'pcb' ? DOC_TYPE.PCB : DOC_TYPE.SCHEMATIC_PAGE;

  const eda = {
    dmt_Schematic: {
      getCurrentSchematicPageInfo: async () => ({ uuid: 'page-1', name: 'P1.Schematic1' }),
    },
    dmt_Pcb: {
      getCurrentPcbInfo: async () => ({ uuid: 'pcb-1', name: 'PCB1' }),
    },
    dmt_EditorControl: {
      getSplitScreenTree: async () => ({
        id: 'root',
        tabs: [
          { tabId: 't1', title: 'P1.Schematic1' },
          { tabId: 't2', title: 'PCB1' },
        ],
        children: [],
      }),
    },
    pcb_PrimitiveComponent: {
      async getAll() {
        calls.pcbGetAll += 1;
        return pcbItems === undefined ? [PCB_COMPONENT()] : pcbItems;
      },
    },
    sch_PrimitiveComponent: {
      async getAll() {
        calls.schGetAll += 1;
        return schItems === undefined ? [SCH_COMPONENT()] : schItems;
      },
    },
  };
  if (focus !== 'none') {
    eda.dmt_SelectControl = {
      getCurrentDocumentInfo: async () => ({
        uuid: activeUuid, name: activeUuid, documentType: activeType, tabId: 't1',
      }),
    };
  }
  return { eda, calls };
}

const call = (eda, action, params = {}) => buildHandlers(eda)[action](params);

test('pcb.readback refuses a wrong page: schematic in front, PCB asked for', async () => {
  const { eda, calls } = fakeWindow({ focus: 'sch' });

  await assert.rejects(
    () => call(eda, 'pcb.readback'),
    (error) => {
      assert.equal(error.name, 'ActionError');
      assert.equal(error.code, 'PAGE_MISMATCH');
      // The message names all three things: what was asked for, what is
      // actually in front, and what to do about it.
      assert.match(error.message, /pcb\.readback/);
      assert.match(error.message, /schematic page/);
      assert.match(error.message, /page-1/);
      assert.match(error.message, /doc\.(focus|open)/);
      assert.deepEqual(error.detail.active, { uuid: 'page-1', type: 'page' });
      assert.equal(error.detail.kind, 'pcb');
      return true;
    },
  );
  assert.equal(calls.pcbGetAll, 0, 'a refused read must not touch the host namespace');
});

test('sch.readback refuses the mirror case: PCB in front, schematic asked for', async () => {
  const { eda, calls } = fakeWindow({ focus: 'pcb' });

  await assert.rejects(
    () => call(eda, 'sch.readback'),
    (error) => {
      assert.equal(error.code, 'PAGE_MISMATCH');
      assert.match(error.message, /sch\.readback/);
      assert.match(error.message, /PCB \(pcb-1\)/);
      assert.match(error.message, /schematic page/);
      assert.equal(error.detail.active.type, 'pcb');
      return true;
    },
  );
  assert.equal(calls.schGetAll, 0, 'the schematic namespace is left alone too');
});

test('a read of the page that IS in front goes through, both ways', async () => {
  const pcb = fakeWindow({ focus: 'pcb' });
  const pcbData = await call(pcb.eda, 'pcb.readback');
  assert.equal(pcbData.componentCount, 1);
  assert.equal(pcbData.components[0].designator, 'U1');
  assert.equal(pcb.calls.pcbGetAll, 1);

  const sch = fakeWindow({ focus: 'sch' });
  const schData = await call(sch.eda, 'sch.readback');
  assert.equal(schData.componentCount, 1);
  assert.equal(schData.components[0].net, 'TX');
  assert.equal(sch.calls.schGetAll, 1);
});

test('an unknown focus is not a refusal — the read proceeds on the heuristic', async () => {
  // No `dmt_SelectControl` at all: only the per-kind fallbacks answer, and a
  // fallback cannot say which page is *in front*, so it must not veto a read.
  const { eda, calls } = fakeWindow({ focus: 'none' });

  const data = await call(eda, 'pcb.readback');
  assert.equal(data.kind, 'pcb');
  assert.equal(data.componentCount, 1);
  assert.equal(calls.pcbGetAll, 1, 'the heuristic path still reads');
});

test('a null hole in getAll is counted as unreadable, never dropped', async () => {
  // The measured host shape behind B4: a list whose entries are partly null.
  const { eda } = fakeWindow({ focus: 'pcb', pcbItems: [null, PCB_COMPONENT()] });

  const data = await call(eda, 'pcb.readback');
  assert.equal(data.componentCount, 1, 'the one real component still comes out');
  assert.equal(data.components[0].designator, 'U1');
  assert.equal(data.unreadable, 1, 'the null entry is reported, not silently swallowed');
  assert.match(String(data.reason), /null/);
});

test('getAll answering a bare null is reported, not turned into a crash', async () => {
  const { eda } = fakeWindow({ focus: 'pcb', pcbItems: null });

  const data = await call(eda, 'pcb.readback');
  assert.equal(data.componentCount, 0);
  assert.equal(data.components.length, 0, 'nothing is invented for an empty list');
  // 527B F7: the first version asserted the two lines above and nothing else,
  // which the *pre-change* code also passed. The counting bug this guards is
  // "holes that vanished become a number": an empty answer is zero holes, so the
  // key must be absent, not `unreadable: 1`.
  assert.equal('unreadable' in data, false, 'no holes means no unreadable count');
});

/**
 * An info object in the shape the host's per-kind getters use: `getState_*()` on
 * the prototype, no own enumerable keys at all. `plainGet` sees nothing here,
 * which is exactly the shape 527B F1 was about.
 */
function stateOnly(state) {
  const proto = {};
  for (const [key, value] of Object.entries(state)) {
    proto[`getState_${key}`] = () => value;
  }
  return Object.create(proto);
}

test('the guard still fires when the host answers through getState_ getters', async () => {
  // F1: `activeDocument` read `documentType` off own keys only, while it read the
  // uuid in both shapes — so on a getState-shaped answer the type was `unknown`,
  // the guard skipped, and the read went through with `source` still saying
  // "precise". Nothing about the message or the code differs; what differs is
  // that the refusal happens at all.
  const { eda, calls } = fakeWindow({ focus: 'sch' });
  eda.dmt_SelectControl = {
    getCurrentDocumentInfo: async () => stateOnly({
      Uuid: 'page-1', DocumentType: DOC_TYPE.SCHEMATIC_PAGE, TabId: 't1',
    }),
  };

  await assert.rejects(
    () => call(eda, 'pcb.readback'),
    (error) => {
      assert.equal(error.code, 'PAGE_MISMATCH');
      assert.equal(error.detail.active.type, 'page');
      return true;
    },
  );
  assert.equal(calls.pcbGetAll, 0);
});

test('a PCB preview / simulation page is named, so the mirror refusals fire', async () => {
  // F2: `PCB_2D_PREVIEW (12)`, `PCB_3D_PREVIEW (15)` and the two simulation
  // schematic page types (8, 9) are the same two kinds opened another way. Left
  // as `unknown` they made the guard skip — a focused PCB preview let
  // `sch.readback` read the schematic namespace.
  const preview = fakeWindow({ focus: 'pcb' });
  preview.eda.dmt_SelectControl = {
    getCurrentDocumentInfo: async () => ({
      uuid: 'pcb-1', name: 'PCB1', documentType: 12, tabId: 't2',
    }),
  };
  await assert.rejects(
    () => call(preview.eda, 'sch.readback'),
    (error) => error.code === 'PAGE_MISMATCH',
  );
  assert.equal(preview.calls.schGetAll, 0);

  const sim = fakeWindow({ focus: 'sch' });
  sim.eda.dmt_SelectControl = {
    getCurrentDocumentInfo: async () => ({
      uuid: 'page-1', name: 'SIM', documentType: 9, tabId: 't1',
    }),
  };
  await assert.rejects(
    () => call(sim.eda, 'pcb.readback'),
    (error) => error.code === 'PAGE_MISMATCH',
  );
  assert.equal(sim.calls.pcbGetAll, 0);
});

test('a direct reading with an unnameable type says the guard did not run', async () => {
  // F1/F3: "direct but unnamed" is the one combination where nothing can be
  // refused. It must not look like a checked read, so it is named in the return
  // body — which the pre-change code dropped on the floor.
  const { eda } = fakeWindow({ focus: 'pcb' });
  eda.dmt_SelectControl = {
    getCurrentDocumentInfo: async () => ({ uuid: 'pcb-1', name: 'PCB1', tabId: 't2' }),
  };

  const data = await call(eda, 'pcb.readback');
  assert.equal(data.componentCount, 1, 'the read itself still happens');
  assert.ok(Array.isArray(data.problems) && data.problems.length > 0);
  assert.match(String(data.problems[0]), /type could not be read/);
  assert.match(String(data.problems[0]), /not checked/);
});

test('getAll throwing rejects instead of reporting an empty board', async () => {
  const { eda } = fakeWindow({ focus: 'pcb' });
  eda.pcb_PrimitiveComponent = {
    getAll: async () => { throw new Error('host said no'); },
  };

  // A non-`ActionError` propagates raw (the transport stamps the frame with
  // `CONNECTOR_ERROR` + the throw's name — `transport.ts`), so what is pinned
  // here is the thing that matters: the call **fails loudly** rather than
  // answering `componentCount: 0`, which would read as "this board has no
  // components".
  await assert.rejects(
    () => call(eda, 'pcb.readback'),
    (error) => {
      assert.match(String(error?.message ?? error), /host said no/);
      return true;
    },
  );
});

test('includePrimitives counts its null holes instead of inventing rows', async () => {
  // F4: the component path was fixed and this one was not, so the same defect
  // survived behind a flag — a null hole became `{primitiveId: '', fields: {}}`,
  // a phantom primitive that `__meta.returned` counted as real.
  const { eda } = fakeWindow({ focus: 'pcb' });
  eda.pcb_PrimitivePad = { getAll: async () => [null, primitive({ PrimitiveId: 'p1' })] };

  const data = await call(eda, 'pcb.readback', { includePrimitives: true });
  const meta = data.primitives[0].__meta;
  assert.equal(meta.returned, 1, 'only the real primitive is a row');
  assert.equal(meta.nullEntries, 1, 'the hole is counted');
  const rows = data.primitives.slice(1).filter((row) => row.namespace === 'pcb_PrimitivePad');
  assert.deepEqual(rows.map((row) => row.primitiveId), ['p1']);
});
