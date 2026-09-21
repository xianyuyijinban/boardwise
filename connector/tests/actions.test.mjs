/**
 * Handler tests against a fake `eda`, built to the real API's *shape*:
 * `getState_*()` methods live on the prototype (not as own properties),
 * because the handlers discover fields by walking the prototype chain.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { buildHandlers } from '../dist/esm/actions.mjs';

/** Make an object whose getState_* methods sit on the prototype, like the API. */
function primitive(state) {
  const proto = {};
  for (const [key, value] of Object.entries(state)) {
    proto[`getState_${key}`] = () => value;
  }
  return Object.create(proto);
}

function fakeEda(overrides = {}) {
  const calls = { markers: [], removed: 0, zoomed: 0 };
  const pcbComponent = primitive({
    PrimitiveId: 'c1', Designator: 'U1', Name: 'CH340C',
    Footprint: 'SOP-16', Supplier: 'LCSC', SupplierId: 'C84681',
    Manufacturer: 'WCH', X: 100, Y: 200, Rotation: 90, Layer: 1,
  });
  const schComponent = primitive({ PrimitiveId: 's1', Designator: 'R1', Net: 'TX', X: 10, Y: 20 });
  const eda = {
    dmt_Project: {
      getCurrentProjectInfo: async () => primitive({ FriendlyName: 'CH340G', Uuid: 'p1' }),
    },
    dmt_Pcb: {
      getCurrentPcbInfo: async () => primitive({ Name: 'PCB1', Uuid: 'pcb1' }),
    },
    dmt_Schematic: {
      getCurrentSchematicPageInfo: async () => primitive({ Name: 'Sheet1', Uuid: 'sch1' }),
    },
    // The direct "which document is in front" getter, added in 004f. It is what
    // `document.current` and `doc.list` both read now: the split-screen tab
    // tree carries no reliable `documentType` on this host.
    dmt_SelectControl: {
      getCurrentDocumentInfo: async () => ({
        uuid: 'pcb1', name: 'PCB1', documentType: 3, tabId: 't2',
      }),
    },
    dmt_EditorControl: {
      getSplitScreenTree: async () => ({
        id: 'root',
        tabs: [
          { tabId: 't1', title: 'Sheet1', documentType: 1 },
          { tabId: 't2', title: 'PCB1', documentType: 3 },
        ],
        children: [],
      }),
      getCurrentRenderedAreaImage: async () =>
        new Blob([new Uint8Array([137, 80, 78, 71])], { type: 'image/png' }),
      zoomToAllPrimitives: async () => {
        calls.zoomed += 1;
        return true;
      },
      generateIndicatorMarkers: async (...args) => {
        calls.markers.push(args);
        return true;
      },
      removeIndicatorMarkers: async () => {
        calls.removed += 1;
        return true;
      },
    },
    // `getAll` is the readback path; `get` is what canvas.highlight uses to
    // turn a uuid into coordinates. Both are part of the real API.
    pcb_PrimitiveComponent: {
      getAll: async () => [pcbComponent],
      get: async (uuid) => (uuid === 'c1' ? pcbComponent : undefined),
    },
    sch_PrimitiveComponent: {
      getAll: async () => [schComponent],
      get: async (uuid) => (uuid === 's1' ? schComponent : undefined),
    },
    pcb_PrimitiveVia: {
      getAll: async () => [primitive({ PrimitiveId: 'v1', X: 5, Y: 6 })],
    },
    ...overrides,
  };
  return { eda, calls };
}

test('document.current reports the project, both documents and the tabs', async () => {
  const { eda } = fakeEda();
  const data = await buildHandlers(eda)['document.current']({});

  assert.equal(data.project.FriendlyName, 'CH340G');
  assert.equal(data.pcb.Name, 'PCB1');
  assert.equal(data.schematicPage.Name, 'Sheet1');
  assert.equal(data.type, 'pcb', 'a pcb tab is open');
  assert.equal(data.tabs.length, 2);
  // `type` now comes from the focused document, not from the tab tree, and
  // says so — so a reader can tell a measurement from a guess.
  assert.equal(data.typeSource, 'dmt_SelectControl.getCurrentDocumentInfo');
  assert.equal(data.heuristic, false);
  assert.equal(data.active.uuid, 'pcb1');
});

test('document.current names the focused schematic page even when tabs say nothing', async () => {
  // The bug this pins, measured 2026-09-15: with a schematic page in front,
  // `document.current` reported `type: "unknown"` because `type` was derived
  // from the split-screen tab tree, whose objects carry no `documentType` on
  // this build — while `doc.list`, reading `getCurrentDocumentInfo`, named the
  // same page correctly. The fix is that both read the same call, so the two
  // actions cannot disagree about which document is in front.
  const { eda } = fakeEda({
    dmt_SelectControl: {
      getCurrentDocumentInfo: async () => ({
        uuid: 'sch1', name: 'Sheet1', documentType: 1, tabId: 't1',
      }),
    },
    // A tab tree of the shape the real host hands back: no documentType at all.
    dmt_EditorControl: {
      getSplitScreenTree: async () => ({
        id: 'root',
        tabs: [{ tabId: 't1', title: 'Sheet1' }, { tabId: 't2', title: 'PCB1' }],
        children: [],
      }),
    },
  });
  const data = await buildHandlers(eda)['document.current']({});

  assert.equal(data.active.uuid, 'sch1', 'the focused page, not a tab guess');
  assert.equal(data.active.type, 'page');
  assert.equal(data.type, 'sch');
  assert.equal(data.typeSource, 'dmt_SelectControl.getCurrentDocumentInfo');
  assert.equal(data.heuristic, false);
  // The tab tree is still reported, but only as display: it must not be the
  // thing `type` was derived from.
  assert.equal(data.tabs.length, 2);
  assert.equal(data.tabs[0].documentType, null);
});

test('document.current marks a tab-tree-derived type as a heuristic', async () => {
  // When the direct getter is unavailable the tab tree is all we have — and
  // the answer must say so, because "unknown" from a guess and "unknown" from
  // the editor look identical otherwise.
  const { eda } = fakeEda({ dmt_SelectControl: undefined });
  const data = await buildHandlers(eda)['document.current']({});

  assert.equal(data.heuristic, true, 'a fallback must never pose as a measurement');
  assert.equal(data.typeSource, 'dmt_Schematic.getCurrentSchematicPageInfo');
  assert.ok(
    (data.problems ?? []).some((p) => p.includes('getCurrentDocumentInfo')),
    'the failed direct read is named, not swallowed',
  );
});

test('a getState-shaped project box keeps its fields and gains doc.list\'s spelling', async () => {
  // The *other* project shape: this fake answers through `getState_*` on the
  // prototype, the way `document.current`'s pcb and schematic-page boxes do on
  // the real build. Adding the identity `doc.list` reports must not cost a
  // field a caller was already reading (measured 2026-09-21: on the real host
  // it was the other way round — plain properties, an empty box).
  const { eda } = fakeEda();
  const data = await buildHandlers(eda)['document.current']({});

  assert.equal(data.project.FriendlyName, 'CH340G');
  assert.equal(data.project.Uuid, 'p1');
  assert.equal(data.project.projectUuid, 'p1');
  assert.equal(data.project.friendlyName, 'CH340G');
});

test('pcb.readback summarises components using the getState contract', async () => {
  const { eda } = fakeEda();
  const data = await buildHandlers(eda)['pcb.readback']({});

  assert.equal(data.componentCount, 1);
  const [component] = data.components;
  assert.equal(component.designator, 'U1');
  assert.equal(component.name, 'CH340C');
  assert.equal(component.footprint, 'SOP-16');
  assert.equal(component.supplierId, 'C84681');
  assert.equal(component.layer, 1);
  assert.equal(component.primitiveId, 'c1');
});

test('sch.readback exposes the net of each component', async () => {
  const { eda } = fakeEda();
  const data = await buildHandlers(eda)['sch.readback']({});
  assert.equal(data.kind, 'sch');
  assert.equal(data.components[0].net, 'TX');
});

test('primitives are only read when asked for, and list what was unavailable', async () => {
  const { eda } = fakeEda();
  const without = await buildHandlers(eda)['pcb.readback']({});
  assert.deepEqual(without.primitives, []);

  const withIt = await buildHandlers(eda)['pcb.readback']({ includePrimitives: true });
  const meta = withIt.primitives[0].__meta;
  assert.ok(withIt.primitives.length > 1, 'at least one primitive namespace returned data');
  assert.ok(meta.unavailable.includes('pcb_PrimitivePad'), 'missing namespaces are reported');
});

test('export.screenshot returns base64 PNG and can fit the view first', async () => {
  const { eda, calls } = fakeEda();
  const data = await buildHandlers(eda)['export.screenshot']({ fit: true });

  assert.equal(data.encoding, 'base64');
  assert.equal(data.format, 'image/png');
  assert.equal(data.bytes, 4);
  assert.equal(Buffer.from(data.data, 'base64').toString('hex'), '89504e47');
  assert.equal(calls.zoomed, 1);
});

test('export.screenshot reports a missing API instead of failing silently', async () => {
  const { eda } = fakeEda({
    dmt_EditorControl: { getSplitScreenTree: async () => ({ tabs: [] }) },
  });
  await assert.rejects(
    () => buildHandlers(eda)['export.screenshot']({}),
    (error) => error.code === 'NOT_IMPLEMENTED',
  );
});

test('export.screenshot surfaces an empty canvas', async () => {
  const { eda } = fakeEda({
    dmt_EditorControl: {
      getCurrentRenderedAreaImage: async () => undefined,
      getSplitScreenTree: async () => ({ tabs: [] }),
    },
  });
  await assert.rejects(
    () => buildHandlers(eda)['export.screenshot']({}),
    (error) => error.code === 'CONNECTOR_ERROR' && /no image/.test(error.message),
  );
});

test('canvas.highlight resolves component uuids to marker shapes', async () => {
  const { eda, calls } = fakeEda();
  const data = await buildHandlers(eda)['canvas.highlight']({
    uuids: ['c1', 's1', 'ghost'],
    color: '#00FF00',
  });

  assert.equal(data.highlighted, 2);
  assert.deepEqual(data.unresolved, ['ghost']);
  const [markers, color, lineWidth, zoom] = calls.markers[0];
  assert.equal(markers.length, 2);
  assert.equal(markers[0].type, 'rectangle');
  // Regression guard: rectangles take left/right/top/bottom — the line/arc
  // fields (startX/...) are silently accepted but render nothing on a real
  // editor. c1 sits at (100, 200), marker size is 60.
  assert.deepEqual(Object.keys(markers[0]).sort(), ['bottom', 'left', 'right', 'top', 'type']);
  assert.deepEqual(
    [markers[0].left, markers[0].right, markers[0].top, markers[0].bottom],
    [40, 160, 260, 140],
  );
  assert.deepEqual(color, { r: 0, g: 255, b: 0, alpha: 255 });
  assert.equal(lineWidth, 2);
  assert.equal(zoom, false, 'zoom defaults to false');
});

test('canvas.highlight passes params.zoom through to the editor', async () => {
  const { eda, calls } = fakeEda();
  await buildHandlers(eda)['canvas.highlight']({ uuids: ['c1'], zoom: true });

  assert.equal(calls.markers[0][3], true);
});

test('canvas.highlight with clear removes markers instead of adding', async () => {
  const { eda, calls } = fakeEda();
  const data = await buildHandlers(eda)['canvas.highlight']({ uuids: ['c1'], clear: true });

  assert.equal(data.cleared, true);
  assert.equal(calls.removed, 1);
  assert.equal(calls.markers.length, 0);
});

test('canvas.highlight requires uuids and falls back to the default colour', async () => {
  const { eda, calls } = fakeEda();
  await assert.rejects(
    () => buildHandlers(eda)['canvas.highlight']({}),
    (error) => error.code === 'BAD_REQUEST',
  );

  await buildHandlers(eda)['canvas.highlight']({ uuids: ['c1'], color: 'not-a-colour' });
  assert.deepEqual(calls.markers[0][1], { r: 255, g: 0, b: 0, alpha: 255 });
});

test('a missing editor namespace becomes NOT_IMPLEMENTED, not a crash', async () => {
  const eda = {};
  await assert.rejects(
    () => buildHandlers(eda)['canvas.highlight']({ uuids: ['c1'] }),
    (error) => error.code === 'NOT_IMPLEMENTED',
  );
});
