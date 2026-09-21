/**
 * 006b contract tests: the measured sheet bbox, the document render, and the
 * timeout-bounded net-label probe.
 *
 * All three exist because of a *measurement* rather than a preference:
 * the sheet's extent is not in its `getState_*` fields (so `Width`/`Height`
 * could only be trusted from the file); `getCurrentRenderedAreaImage` returns
 * cached frames on this host (so a viewport capture cannot be the acceptance
 * image); and `createNetLabel` is documented as hanging on 3.2.186 (so it has
 * to be bounded *and* self-reporting — the reference lesson is that a timed
 * out call may well have landed anyway, and a blind retry stacks duplicates).
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { createFacade } from '../dist/esm/facade.mjs';
import * as connector from '../dist/esm/index.mjs';

/**
 * Editor primitives expose `getState_*` on their **prototype** (that is how
 * `deepDump` finds them — it walks the prototype chain, not own properties),
 * so the fakes are class instances rather than object literals.
 */
class FakePrimitive {
  constructor(fields) {
    this.fields = fields;
  }
}
for (const name of ['PrimitiveId', 'ComponentType', 'X', 'Y', 'Key', 'Value']) {
  Object.defineProperty(FakePrimitive.prototype, `getState_${name}`, {
    value: function () {
      return this.fields[name];
    },
  });
}

function primitive(idOrFields, extra = {}) {
  const fields = typeof idOrFields === 'string' ? { PrimitiveId: idOrFields } : idOrFields;
  return new FakePrimitive({ ...fields, ...extra });
}

/** Minimal host: only the namespaces these three actions touch. */
function host(overrides = {}) {
  const state = { labelCalls: [] };
  const hostObject = {
    sys_WebSocket: {
      register(id, uri, onMessage) {
        hostObject.__onMessage = onMessage;
      },
      send(_id, data) {
        hostObject.__sent = hostObject.__sent ?? [];
        hostObject.__sent.push(JSON.parse(data));
      },
      close() {},
    },
    sys_Log: { add() {} },
    sys_Message: { showToastMessage() {} },
    sys_Environment: { getEditorCurrentVersion: () => '3.2.186' },
    sys_Storage: {
      getExtensionUserConfig: () => undefined,
      setExtensionUserConfig: async () => true,
    },
    sys_Dialog: { showInformationMessage() {} },

    sch_PrimitiveComponent: {
      getAll: async () => [
        primitive({ PrimitiveId: 'sheet-1', ComponentType: 'sheet', X: 0, Y: 0 }),
      ],
    },
    sch_PrimitiveWire: { getAll: async () => [] },
    sch_PrimitivePin: { getAll: async () => [] },
    sch_PrimitiveNetLabel: { getAll: async () => [] },

    sch_Primitive: {
      async getPrimitivesBBox(ids) {
        state.bboxCalls = state.bboxCalls ?? [];
        state.bboxCalls.push([...ids]);
        if (ids[0] === 'sheet-1') {
          return { minX: 0, minY: 0, maxX: 1170, maxY: 825 };
        }
        return undefined;
      },
    },

    sch_ManufactureData: {
      async getExportDocumentFile(fileName, fileType, typeParams, object) {
        state.exportCalls = state.exportCalls ?? [];
        state.exportCalls.push({ fileName, fileType, typeParams, object });
        // a 1x1 PNG
        const png = Buffer.from(
          '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c6300010000050001',
          'hex',
        );
        return {
          type: 'image/png',
          name: fileName,
          size: png.byteLength,
          async arrayBuffer() {
            return png.buffer.slice(png.byteOffset, png.byteOffset + png.byteLength);
          },
        };
      },
      // Still present on the real host (it answers NOT_IMPLEMENTED, it is not
      // absent) — kept so the sys.probe enumeration tests see it.
      getPngFile() {},
    },

    sch_SelectControl: {
      async doSelectPrimitives(ids) {
        state.selectedIds = [...ids];
        return true;
      },
    },

    sch_PrimitiveAttribute: {
      async createNetLabel(x, y, net) {
        state.labelCalls.push({ x, y, net });
        return primitive('label-1');
      },
      async getAll() {
        return (state.attributes ?? []).map((a) =>
          primitive(a.id, {
            getState_Key: () => a.key,
            getState_Value: () => a.value,
            getState_X: () => a.x,
            getState_Y: () => a.y,
          }),
        );
      },
    },

    dmt_Schematic: {
      async getCurrentSchematicPageInfo() {
        return { uuid: 'page-1' };
      },
    },

    __state: state,
  };
  for (const [key, value] of Object.entries(overrides)) {
    if (value === null) delete hostObject[key];
    else hostObject[key] = typeof value === 'function' ? value(hostObject) : value;
  }
  return hostObject;
}

function withEda(t, hostObject) {
  connector.__setFacadeForTests(createFacade(hostObject));
  t.after(() => {
    connector.deactivate();
    connector.__setFacadeForTests(undefined);
  });
}

async function waitFor(predicate, timeoutMs = 2000) {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() > deadline) return false;
    await new Promise((resolve) => setTimeout(resolve, 2));
  }
  return true;
}

async function call(hostObject, action, params = {}) {
  const id = `req-${Math.random().toString(36).slice(2, 8)}`;
  void hostObject.__onMessage({ data: JSON.stringify({ id, action, params }) });
  assert.ok(
    await waitFor(() => (hostObject.__sent ?? []).some((f) => f.id === id)),
    `no response frame for ${action}`,
  );
  return (hostObject.__sent ?? []).find((f) => f.id === id);
}

// --------------------------------------------------------------------------
// sch.geometry -> measured sheet bbox
// --------------------------------------------------------------------------

test('sch.geometry measures the sheet primitive bbox', async (t) => {
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sch.geometry', {});
  assert.equal(frame.ok, true);
  assert.deepEqual(frame.data.meta.sheets, ['sheet-1']);
  assert.equal(frame.data.meta.available.bboxes, true);
  assert.deepEqual(frame.data.bboxes['sheet-1'], {
    minX: 0, minY: 0, maxX: 1170, maxY: 825,
  });
});

test('sch.geometry measures extra ids on request', async (t) => {
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sch.geometry', { bboxIds: ['sheet-1', 'comp-9'] });
  assert.equal(frame.ok, true);
  assert.deepEqual(h.__state.bboxCalls.at(-1), ['comp-9']);
  assert.equal('comp-9' in frame.data.bboxes, false, 'an undefined box is simply absent');
});

test('sch.geometry says so when the host cannot measure boxes', async (t) => {
  const h = host({ sch_Primitive: null });
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sch.geometry', {});
  assert.equal(frame.ok, true);
  assert.equal(frame.data.meta.available.bboxes, false);
  assert.deepEqual(frame.data.bboxes, {});
});

// --------------------------------------------------------------------------
// export.render -> the acceptance image
// --------------------------------------------------------------------------

test('export.render returns the document render as base64', async (t) => {
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'export.render', {});
  assert.equal(frame.ok, true);
  assert.equal(frame.data.format, 'image/png');
  assert.equal(frame.data.encoding, 'base64');
  assert.equal(frame.data.scope, 'page');
  assert.match(frame.data.data, /^iVBOR/, 'PNG magic in base64');
  assert.ok(frame.data.bytes > 8);
});

test('export.render passes the REAL object literals, not the .d.ts ones', async (t) => {
  // The whole point of the 2026-09-18 port: the declared values
  // ('Current Schematic Page' et al.) hang the host's promise forever; the
  // literals below were read out of the shipped sch-main.js. If this test
  // ever fails, someone "fixed" the strings to match the type package.
  const h = host();
  withEda(t, h);
  await connector.activate();

  await call(h, 'export.render', {});
  await call(h, 'export.render', { scope: 'project' });
  await call(h, 'export.render', { scope: 'selection', ids: ['p1', 'p2'] });
  const objects = h.__state.exportCalls.map((c) => c.object);
  assert.deepEqual(objects, ['Current Page', 'Project', 'Current Page Selected Items']);
  const first = h.__state.exportCalls[0];
  assert.equal(first.fileType, 'PNG');
  assert.deepEqual(first.typeParams, { theme: 'Default', lineWidth: 'Default' });
  assert.equal(first.fileName, 'render.png', 'the default file name follows the format');
  assert.deepEqual(h.__state.selectedIds, ['p1', 'p2'], 'selection scope selects first');
});

test('export.render honours the format parameter', async (t) => {
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'export.render', { format: 'svg', fileName: 'page.svg' });
  assert.equal(frame.ok, true);
  const call_ = h.__state.exportCalls[0];
  assert.equal(call_.fileType, 'SVG');
  assert.equal(call_.fileName, 'page.svg');
});

test('export.render rejects a bad format before calling the host', async (t) => {
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'export.render', { format: 'bmp' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'BAD_REQUEST');
  assert.match(frame.error.message, /format/);
  assert.equal(h.__state.exportCalls, undefined, 'no host call on a rejected param');
});

test('export.render rejects a bad scope before calling the host', async (t) => {
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'export.render', { scope: 'everything' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'BAD_REQUEST');
  assert.match(frame.error.message, /scope/);
  assert.equal(h.__state.exportCalls, undefined);
});

test('export.render rejects scope=selection without ids', async (t) => {
  // Otherwise the editor renders whatever happens to be selected — an empty
  // image that reads as a successful render of nothing.
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'export.render', { scope: 'selection' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'BAD_REQUEST');
  assert.match(frame.error.message, /ids/);
  assert.equal(h.__state.exportCalls, undefined);
});

test('export.render rejects ids that are not a string[]', async (t) => {
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'export.render', { scope: 'selection', ids: [1, 2] });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'BAD_REQUEST');
  assert.equal(h.__state.exportCalls, undefined);
});

test('export.render reports an archive instead of pretending it is an image', async (t) => {
  const zip = Buffer.from('504b030414000000', 'hex');
  const h = host({
    sch_ManufactureData: {
      async getExportDocumentFile() {
        return {
          type: '',
          async arrayBuffer() {
            return zip.buffer.slice(zip.byteOffset, zip.byteOffset + zip.byteLength);
          },
        };
      },
    },
  });
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'export.render', { scope: 'project' });
  assert.equal(frame.ok, true);
  assert.equal(frame.data.format, 'zip');
  assert.match(frame.data.note, /archive/);
});

test('export.render is NOT_IMPLEMENTED when the host has no getExportDocumentFile', async (t) => {
  const h = host({ sch_ManufactureData: {} });
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'export.render', {});
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'NOT_IMPLEMENTED');
});

// --------------------------------------------------------------------------
// sch.place_netlabel -> bounded, self-reporting probe
// --------------------------------------------------------------------------

test('sch.place_netlabel reports success with its elapsed time', async (t) => {
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sch.place_netlabel', {
    x: 100, y: 200, net: 'RX', pageUuid: 'page-1',
  });
  assert.equal(frame.ok, true);
  assert.equal(frame.data.uuid, 'label-1');
  assert.equal(frame.data.outcome, 'ok');
  assert.equal(frame.data.landedAnyway, true);
  assert.equal(typeof frame.data.elapsedMs, 'number');
  assert.deepEqual(h.__state.labelCalls.at(-1), { x: 100, y: 200, net: 'RX' });
});

test('sch.place_netlabel bounds a hung host and reports it did not land', async (t) => {
  const h = host({
    sch_PrimitiveAttribute: {
      createNetLabel: () => new Promise(() => {}), // hangs forever, like #191
      async getAll() {
        return [];
      },
    },
  });
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sch.place_netlabel', {
    x: 10, y: 20, net: 'TX', pageUuid: 'page-1', timeoutMs: 250,
  });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'TIMEOUT');
  assert.equal(frame.error.detail.landedAnyway, false);
  assert.match(frame.error.message, /the call is unusable/);
  assert.ok(frame.error.detail.elapsedMs >= 200);
});

test('sch.place_netlabel reads back a label that landed after the timeout', async (t) => {
  // The reference lesson: a timed-out call may have created the marker
  // anyway, so a blind retry would stack duplicates.
  const h = host({
    sch_PrimitiveAttribute: {
      createNetLabel: () => new Promise(() => {}),
      async getAll() {
        return [
          primitive({ PrimitiveId: 'attr-1', Key: 'NET', Value: 'TX', X: 10, Y: 20 }),
        ];
      },
    },
  });
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sch.place_netlabel', {
    x: 10, y: 20, net: 'TX', pageUuid: 'page-1', timeoutMs: 250,
  });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'TIMEOUT');
  assert.equal(frame.error.detail.landedAnyway, true);
  assert.equal(frame.error.detail.matches, 1);
  assert.match(frame.error.message, /do NOT retry/);
});

test('sch.place_netlabel still refuses a stale focus', async (t) => {
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sch.place_netlabel', {
    x: 1, y: 2, net: 'RX', pageUuid: 'some-other-page',
  });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'PAGE_MISMATCH');
});

// --------------------------------------------------------------------------
// sys.probe -> the live API surface
// --------------------------------------------------------------------------

test('sys.probe reports the version and the real member names', async (t) => {
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sys.probe', { namespace: 'sch_ManufactureData' });
  assert.equal(frame.ok, true);
  assert.equal(frame.data.version, '3.2.186');
  assert.ok(Array.isArray(frame.data.topLevel));
  assert.ok(frame.data.topLevel.includes('sch_ManufactureData'));

  const ns = frame.data.namespaces.sch_ManufactureData;
  assert.equal(ns.present, true);
  assert.ok(ns.functions.includes('getPngFile'), 'getPngFile should be listed');
});

test('sys.probe walks the prototype chain, not own keys', async (t) => {
  // The trap: `Object.keys(ns)` on a class instance is `[]`, so a probe that
  // only reads own keys answers "no members" on a perfectly healthy namespace.
  class ManufactureData {
    getNetlistFile() {}
    getPngFile() {}
  }
  const h = host({ sch_ManufactureData: () => new ManufactureData() });
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sys.probe', { namespace: 'sch_ManufactureData' });
  assert.equal(frame.ok, true);
  const ns = frame.data.namespaces.sch_ManufactureData;
  assert.deepEqual(ns.functions, ['getNetlistFile', 'getPngFile']);
  assert.ok(ns.ownNames >= 2);
});

test('sys.probe reports a missing namespace as absent, not as an error', async (t) => {
  const h = host({ sch_ManufactureData: null });
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sys.probe', { namespace: 'sch_ManufactureData' });
  assert.equal(frame.ok, true);
  assert.equal(frame.data.namespaces.sch_ManufactureData.present, false);
  assert.deepEqual(frame.data.namespaces.sch_ManufactureData.functions, []);
});

test('sys.probe takes several namespaces at once', async (t) => {
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sys.probe', {
    namespaces: ['sch_ManufactureData', 'sys_Log', 'definitely_not_here'],
  });
  assert.equal(frame.ok, true);
  assert.equal(frame.data.namespaces.definitely_not_here.present, false);
  assert.equal(frame.data.namespaces.sys_Log.present, true);
  assert.ok(frame.data.namespaces.sys_Log.functions.includes('add'));
});

test('sys.probe survives a host object whose prototype access throws', async (t) => {
  // Measured 2026-09-14: the whole first probe run died with "reading
  // 'prototype'" because the host's exotic objects throw from
  // `getPrototypeOf`. One bad level must cost one report line, not the answer.
  const exotic = new Proxy(
    {},
    {
      getPrototypeOf() {
        throw new TypeError("Cannot read properties of undefined (reading 'prototype')");
      },
      getOwnPropertyDescriptor(target, prop) {
        if (prop === 'getNetlistFile') {
          return { value: () => {}, configurable: true, enumerable: true, writable: true };
        }
        return undefined;
      },
    },
  );
  const h = host({ sch_ManufactureData: exotic });
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sys.probe', {
    namespaces: ['sch_ManufactureData', 'sys_Log'],
  });
  assert.equal(frame.ok, true, 'a hostile namespace must not fail the whole call');

  const ns = frame.data.namespaces.sch_ManufactureData;
  assert.equal(ns.present, true);
  assert.ok(Array.isArray(ns.errors), 'the walk records why it stopped');
  assert.ok(
    ns.errors.some((line) => /getPrototypeOf/.test(line)),
    `expected a getPrototypeOf error, got ${JSON.stringify(ns.errors)}`,
  );
  // The other namespace in the same call is unaffected.
  assert.equal(frame.data.namespaces.sys_Log.present, true);
  assert.ok(frame.data.namespaces.sys_Log.functions.includes('add'));
});

// --------------------------------------------------------------------------
// sys.probe checks mode -> named reads, immune to exotic host objects
// --------------------------------------------------------------------------

/**
 * The exact shape that killed the first on-machine probe (2026-09-14).
 *
 * Every namespace came back with "Cannot read properties of undefined
 * (reading 'prototype')" because the host's objects throw from
 * `getPrototypeOf`, and `constructor` is not reachable. Enumeration can
 * therefore fail on precisely the object being measured; a plain
 * `typeof ns[name]` read cannot.
 */
function hostThatBreaksEnumeration(members) {
  return new Proxy(
    {},
    {
      getPrototypeOf() {
        throw new TypeError("Cannot read properties of undefined (reading 'prototype')");
      },
      getOwnPropertyDescriptor(target, prop) {
        if (Object.prototype.hasOwnProperty.call(members, prop)) {
          return {
            value: members[prop],
            configurable: true,
            enumerable: true,
            writable: true,
          };
        }
        return undefined;
      },
      get(target, prop) {
        // `constructor` is deliberately unreachable, as on the real host.
        if (prop === 'constructor') {
          throw new TypeError("Cannot read properties of undefined (reading 'prototype')");
        }
        return members[prop];
      },
      has() {
        return false;
      },
      ownKeys() {
        throw new TypeError("Cannot read properties of undefined (reading 'prototype')");
      },
    },
  );
}

test('sys.probe checks mode answers on a host that breaks enumeration', async (t) => {
  // The regression this pins: enumerate mode cannot see this object at all,
  // but the *named* read still gives the true answer for every method.
  const namespace = hostThatBreaksEnumeration({
    getNetlistFile: async () => undefined,
    getPngFile: () => undefined,
    getSvgFile: undefined,
  });
  const h = host({ sch_ManufactureData: namespace });
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sys.probe', {
    checks: { sch_ManufactureData: ['getNetlistFile', 'getPngFile', 'getSvgFile', 'nope'] },
  });
  assert.equal(frame.ok, true, 'checks mode must not depend on enumeration');

  const ns = frame.data.checks.sch_ManufactureData;
  assert.equal(ns.present, true);
  assert.equal(ns.checked, 4);
  assert.equal(ns.missing, 2, 'getSvgFile undefined + nope absent');
  assert.equal(ns.status.getNetlistFile, 'function');
  assert.equal(ns.status.getPngFile, 'function');
  assert.equal(ns.status.getSvgFile, 'undefined');
  assert.equal(ns.status.nope, 'undefined');
});

test('sys.probe checks mode reaches methods on the prototype chain', async (t) => {
  // Property access walks the chain by construction — this is *why* the
  // checks path needs no enumeration to find an inherited method.
  class Grandparent {
    getNetlistFile() {}
  }
  class Parent extends Grandparent {
    getPngFile() {}
  }
  const h = host({ sch_ManufactureData: new Parent() });
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sys.probe', {
    checks: { sch_ManufactureData: ['getNetlistFile', 'getPngFile'] },
  });
  assert.equal(frame.data.checks.sch_ManufactureData.missing, 0);
  assert.equal(frame.data.checks.sch_ManufactureData.status.getNetlistFile, 'function');
});

test('sys.probe checks mode reports a throwing read as its own outcome', async (t) => {
  // "undeclared" and "the read itself failed" must never collapse into one.
  const namespace = new Proxy(
    {},
    {
      getPrototypeOf() {
        return null;
      },
      get(_target, prop) {
        if (prop === 'explodes') throw new Error('host said no');
        return undefined;
      },
    },
  );
  const h = host({ sch_ManufactureData: namespace });
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sys.probe', {
    checks: { sch_ManufactureData: ['explodes', 'absent'] },
  });
  const ns = frame.data.checks.sch_ManufactureData;
  assert.match(ns.status.explodes, /^threw: host said no$/);
  assert.equal(ns.status.absent, 'undefined');
  assert.equal(ns.missing, 2, 'a throwing read still counts as not-answered');
});

test('sys.probe checks mode reports an absent namespace as namespace-absent', async (t) => {
  const h = host({ sch_ManufactureData: null });
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sys.probe', {
    checks: { sch_ManufactureData: ['getPngFile'] },
  });
  const ns = frame.data.checks.sch_ManufactureData;
  assert.equal(ns.present, false);
  assert.equal(ns.status.getPngFile, 'namespace-absent');
});

test('sys.probe checks mode reports the declared arity of every function member', async (t) => {
  // F4 (2026-09-21): `lib_Device.searchByProperties` reads back `function` on
  // the 3.2.186 host and answers nothing, so "is the live member the
  // six-argument method the type package declares, or a two-argument namesake?"
  // is a question `typeof` cannot answer on its own — the same name exists on
  // three classes with arities 6 / 2 / 2. `arity` is that answer, reported
  // beside the typeof it belongs to and never judged on (a wrapper loses it).
  const h = host({
    sch_ManufactureData: {
      getExportDocumentFile(fileName, fileType, typeParams, object) {},
      getSvgFile() {},
      version: '3.2.186',
      getPngFile: undefined,
    },
  });
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sys.probe', {
    checks: {
      sch_ManufactureData: [
        'getExportDocumentFile', 'getSvgFile', 'version', 'getPngFile', 'nope',
      ],
    },
  });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  const ns = frame.data.checks.sch_ManufactureData;
  assert.equal(ns.arity.getExportDocumentFile, 4);
  assert.equal(ns.arity.getSvgFile, 0, 'a zero-argument method is reported, not omitted');
  assert.equal(ns.status.getExportDocumentFile, 'function');
  // Only the functions carry an entry: "no arity" is how a data field, an
  // undefined member and a name the namespace never had stay distinguishable
  // from a method that declares nothing.
  assert.deepEqual(ns.arity, { getExportDocumentFile: 4, getSvgFile: 0 });
  assert.equal(ns.status.version, 'string');
  assert.equal(ns.arity.version, undefined);
  assert.equal(ns.arity.getPngFile, undefined);
  assert.equal(ns.arity.nope, undefined);
});

test('sys.probe checks mode notes a declared ADD-since method that is missing', async (t) => {
  // `getPngFile` is declared `ADD since EDA v3.2.183`; the host claims 3.2.186
  // and answers nothing. The report must carry the contradiction, not leave
  // the reader to cross-reference the type package.
  const h = host({ sch_ManufactureData: { getNetlistFile() {} } });
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sys.probe', {
    checks: { sch_ManufactureData: ['getNetlistFile', 'getPngFile'] },
  });
  const ns = frame.data.checks.sch_ManufactureData;
  assert.equal(ns.status.getPngFile, 'undefined');
  assert.match(ns.notes.getPngFile, /ADD since v3\.2\.183/);
  assert.equal(ns.notes.getNetlistFile, undefined, 'only the missing one is noted');
});

test('sys.probe checks mode takes the offline table when asked for defaults', async (t) => {
  // `checks: true` means "the names the type package declares". The table is
  // generated from `@jlceda/pro-api-types` by `tools/api_names.py`, so this
  // test also fails if the generated file is emptied or the names drift.
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sys.probe', { checks: true });
  assert.equal(frame.ok, true);
  const namespaces = Object.keys(frame.data.checks).sort();
  assert.deepEqual(namespaces, [
    'dmt_EditorControl',
    'dmt_Pcb',
    'dmt_Schematic',
    'sch_Document',
    'sch_ManufactureData',
    // 006b-F3 recon: the seventh path to a placed pin's geometry, plus the
    // real net-flag API (`createNetFlag`) the decorative-text fallback stands
    // in for.
    'sch_PrimitiveComponent',
    'sch_PrimitivePin',
  ]);
  // The five namespaces must not be empty shells.
  for (const name of namespaces) {
    assert.ok(frame.data.checks[name].checked > 0, `${name} checked nothing`);
  }
});

test('snapshot survives an exotic primitive instead of losing every field', async (t) => {
  // `snapshot` walks the prototype chain too, so it had the same hole: one
  // throwing level used to abort the readback for a whole component.
  const exoticPrimitive = new Proxy(
    {
      getState_Designator() {
        return 'R1';
      },
      getState_X() {
        return 12;
      },
    },
    {
      getPrototypeOf() {
        throw new TypeError('nope');
      },
      getOwnPropertyDescriptor(target, prop) {
        return Object.getOwnPropertyDescriptor(target, prop);
      },
      ownKeys(target) {
        return Reflect.ownKeys(target);
      },
    },
  );
  const h = host({
    sch_PrimitiveComponent: { getAll: async () => [exoticPrimitive] },
  });
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sch.readback', {});
  assert.equal(frame.ok, true);
  assert.equal(frame.data.componentCount, 1);
});

test('a member read that THROWS must not kill the read action (measured host shape)', async (t) => {
  // 2026-09-14 on the real machine: the host's objects are Proxies whose `get`
  // trap throws `Cannot read properties of undefined (reading 'prototype')`.
  // `getState` performed `obj['getState_' + name]` OUTSIDE its try, and
  // `obj?.[key]` only guards null/undefined — so `sch.geometry`, `sch.readback`
  // and every `document.current` info box failed, while paths that never went
  // through `getState` (the probe's `checks`, the tab list) kept working.
  // A guarded read is the fix; the failure must also be REPORTED, because a
  // silently empty dump is indistinguishable from an empty page.
  const EXOTIC = "Cannot read properties of undefined (reading 'prototype')";
  const throwing = new Proxy(
    {},
    {
      ownKeys() {
        return ['getState_Designator'];
      },
      getOwnPropertyDescriptor() {
        return { value: () => 'R1', configurable: true, enumerable: true, writable: true };
      },
      getPrototypeOf() {
        throw new TypeError(EXOTIC);
      },
      get() {
        // every member read traps, exactly as measured
        throw new TypeError(EXOTIC);
      },
    },
  );
  const h = host({ sch_PrimitiveComponent: { getAll: async () => [throwing] } });
  withEda(t, h);
  await connector.activate();

  const rb = await call(h, 'sch.readback', {});
  assert.equal(rb.ok, true, 'the action must survive a throwing member read');
  assert.ok(rb.data.unreadable >= 1, 'the failure must be reported, not swallowed');
  assert.match(String(rb.data.reason), /prototype/);

  const geo = await call(h, 'sch.geometry', {});
  assert.equal(geo.ok, true, 'sch.geometry must survive it too');
  assert.ok(geo.data.meta.reasons, 'and must name the namespace whose read broke');
  assert.match(String(geo.data.meta.reasons.components), /prototype/);
});

// --------------------------------------------------------------------------
// sch.place_component -> timeout-hardened (revision 3)
// --------------------------------------------------------------------------

/** A host with just enough library + component surface to place one part. */
function placeHost({ create, getAll }) {
  const state = { created: 0 };
  const h = host({});
  h.lib_Device = {
    async getByLcscIds(ids) {
      return ids.map((id) => ({ uuid: `dev-${id}`, libraryUuid: 'lib-1', name: `Device ${id}` }));
    },
  };
  h.sch_PrimitiveComponent = {
    async create() {
      state.created += 1;
      return create();
    },
    async modify(id) {
      return primitive(String(id));
    },
    getAll: getAll ?? (async () => []),
  };
  h.__place = state;
  return h;
}

test('sch.place_component reports a timed-out placement that did NOT land', async (t) => {
  const h = placeHost({
    // hangs forever — the measured first-placement-of-a-session case
    create: () => new Promise(() => {}),
    getAll: async () => [],
  });
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sch.place_component', {
    lcsc: 'C14663', x: 100, y: 200, designator: 'R9', timeoutMs: 250,
  });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'TIMEOUT');
  assert.equal(frame.error.detail.landedAnyway, false);
  assert.equal(frame.error.detail.landedCount, 0);
  assert.match(frame.error.message, /nothing appeared/);
  assert.equal(h.__place.created, 1, 'exactly one create attempt — the harness must not retry');
});

test('sch.place_component reports a timed-out placement that DID land', async (t) => {
  // The measured trap: library resolution outran the deadline and the part
  // landed anyway; a blind retry would stack two parts on one spot.
  const h = placeHost({
    create: () => new Promise(() => {}),
    getAll: async () => [
      primitive({ PrimitiveId: 'comp-x', Designator: 'R9', X: 100, Y: 200 }),
    ],
  });
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sch.place_component', {
    lcsc: 'C14663', x: 100, y: 200, designator: 'R9', timeoutMs: 250,
  });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'TIMEOUT');
  assert.equal(frame.error.detail.landedAnyway, true);
  assert.equal(frame.error.detail.landedCount, 1);
  assert.match(frame.error.message, /do NOT retry/);
});

test('sch.place_component ignores a part far from the requested point', async (t) => {
  // The readback must answer "did MY placement land", not "is anything here".
  const h = placeHost({
    create: () => new Promise(() => {}),
    getAll: async () => [
      primitive({ PrimitiveId: 'comp-far', Designator: 'R1', X: 900, Y: 900 }),
    ],
  });
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sch.place_component', {
    lcsc: 'C14663', x: 100, y: 200, designator: 'R9', timeoutMs: 250,
  });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.detail.landedAnyway, false);
  assert.match(frame.error.message, /nothing appeared/);
});

test('sch.place_component reports its elapsed time on success', async (t) => {
  const h = placeHost({ create: async () => primitive('comp-1'), getAll: async () => [] });
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sch.place_component', {
    lcsc: 'C14663', x: 10, y: 20, designator: 'C1',
  });
  assert.equal(frame.ok, true);
  assert.equal(frame.data.uuid, 'comp-1');
  assert.equal(typeof frame.data.elapsedMs, 'number');
});

// --------------------------------------------------------------------------
// sch.place_text -> decorative net names (revision 3 naming strategy)
// --------------------------------------------------------------------------

test('sch.place_text places a text primitive and marks it decorative', async (t) => {
  const h = host({});
  const calls = [];
  h.sch_PrimitiveText = {
    async create(...args) {
      calls.push(args);
      return primitive('text-1');
    },
  };
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sch.place_text', {
    x: 120, y: 240, content: 'RX', pageUuid: 'page-1',
  });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.uuid, 'text-1');
  assert.equal(frame.data.content, 'RX');
  assert.equal(frame.data.decorative, true, 'a text primitive carries no connectivity');
  assert.deepEqual(calls[0].slice(0, 3), [120, 240, 'RX']);
});

test('sch.place_text needs content and honours the page guard', async (t) => {
  const h = host({ sch_PrimitiveText: { async create() { return primitive('text-1'); } } });
  withEda(t, h);
  await connector.activate();

  const empty = await call(h, 'sch.place_text', { x: 1, y: 2, content: '', pageUuid: 'page-1' });
  assert.equal(empty.ok, false);
  assert.equal(empty.error.code, 'BAD_REQUEST');

  const stale = await call(h, 'sch.place_text', {
    x: 1, y: 2, content: 'RX', pageUuid: 'nope',
  });
  assert.equal(stale.ok, false);
  assert.equal(stale.error.code, 'PAGE_MISMATCH');
});

test('sch.place_text is NOT_IMPLEMENTED when the host has no text namespace', async (t) => {
  const h = host({});
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sch.place_text', {
    x: 1, y: 2, content: 'RX', pageUuid: 'page-1',
  });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'NOT_IMPLEMENTED');
});
