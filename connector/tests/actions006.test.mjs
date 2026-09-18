/**
 * Contract tests for the 006 schematic actions (netlist / geometry / writes).
 *
 * Every new action is driven through the *production* dispatch path — a fake
 * host whose `sch_*` / `lib_*` namespaces record their calls — so the tests
 * pin the wire contract (request params in, `data` payload out) and the
 * failure shapes (`error.code` + `message`) at the same boundary the daemon
 * sees. That boundary is the one that broke 0.1.2, so it stays covered.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { createFacade } from '../dist/esm/facade.mjs';
import * as connector from '../dist/esm/index.mjs';

const BANNER = {
  event: 'banner',
  data: { server: 'boardwise', protocol: '1.0', expect: 'hello' },
};

/** An editor primitive stand-in: the getState_* surface the code consumes. */
function primitive(id, extra = {}) {
  return {
    getState_PrimitiveId: () => id,
    ...extra,
  };
}

/**
 * A host carrying fake library + schematic namespaces. Each namespace records
 * its calls so the assertions can check what the handler actually passed —
 * not merely that it returned something.
 */
function edaHost(stored = {}) {
  const calls = {
    wire: [], netFlag: [], netPort: [], netLabel: [], component: [],
    componentModify: [], lcsc: [], search: [], save: [],
  };
  let nextId = 1;

  const host = {
    sys_WebSocket: {
      register(id, uri, onMessage) {
        host.__onMessage = onMessage;
      },
      send(_id, data) {
        host.__sent = host.__sent ?? [];
        host.__sent.push(JSON.parse(data));
      },
      close() {},
    },
    sys_Log: { add() {} },
    sys_Message: { showToastMessage() {} },
    sys_Environment: { getEditorCurrentVersion: () => '3.2.186' },
    sys_Storage: {
      getExtensionUserConfig: (key) => stored[key],
      setExtensionUserConfig: async (key, value) => {
        stored[key] = value;
        return true;
      },
    },
    sys_Dialog: { showInformationMessage() {} },

    lib_Device: {
      async getByLcscIds(ids) {
        calls.lcsc.push([...ids]);
        return ids.map((id) => ({ uuid: `dev-${id}`, libraryUuid: 'lib-1', name: `Device ${id}` }));
      },
      async search(key) {
        calls.search.push(key);
        if (key === 'nothing matches this') return [];
        return [{ uuid: 'dev-kw', libraryUuid: 'lib-1', name: `Device for ${key}` }];
      },
      async get(uuid, libraryUuid) {
        if (uuid === 'dev-uuid') return { uuid, libraryUuid, name: 'Named device' };
        return undefined;
      },
    },

    sch_PrimitiveComponent: {
      getAll: async () => [],
      modifyCalls: [],
      async create(component, x, y, subPart, rotation, mirror, intoBom, intoPcb) {
        calls.component.push({ component, x, y, subPart, rotation, mirror, intoBom, intoPcb });
        return primitive(`comp-${nextId++}`);
      },
      async modify(primitiveId, property) {
        calls.componentModify.push({ primitiveId, property });
        return primitive(String(primitiveId));
      },
      async createNetFlag(kind, net, x, y, rotation, mirror) {
        calls.netFlag.push({ kind, net, x, y, rotation, mirror });
        return primitive(`flag-${nextId++}`);
      },
      async createNetPort(direction, net, x, y, rotation, mirror) {
        calls.netPort.push({ direction, net, x, y, rotation, mirror });
        return primitive(`port-${nextId++}`);
      },
    },

    sch_PrimitivePin: { getAll: async () => [] },
    sch_PrimitiveNetLabel: { getAll: async () => [] },

    sch_PrimitiveWire: {
      getAll: async () => [],
      async create(points, net) {
        calls.wire.push({ points, net });
        return primitive(`wire-${nextId++}`);
      },
    },

    sch_PrimitiveAttribute: {
      async createNetLabel(x, y, net) {
        calls.netLabel.push({ x, y, net });
        return primitive(`label-${nextId++}`);
      },
    },

    sch_ManufactureData: {
      async getNetlistFile(name, type) {
        return { text: async () => `netlist for ${type} via ${name}` };
      },
    },

    dmt_Schematic: {
      async getCurrentSchematicInfo() {
        // Plain-property shape, as measured on the real editor 2026-09-13 —
        // NOT a getState_* object.
        return { uuid: 'sch-1', name: 'Schematic1', parentProjectUuid: 'proj-1' };
      },
      async getCurrentSchematicPageInfo() {
        return { uuid: 'page-of-sch-1', parentSchematicUuid: 'sch-1' };
      },
      async createSchematicPage(schematicUuid) {
        return `page-of-${schematicUuid}`;
      },
    },

    dmt_EditorControl: {
      async openDocument(documentUuid) {
        host.__opened = host.__opened ?? [];
        host.__opened.push(documentUuid);
        return documentUuid;
      },
    },

    __calls: calls,
  };
  return host;
}

/** One connected session against a host, with the banner already answered. */
function withEda(t, host) {
  connector.__setFacadeForTests(createFacade(host));
  t.after(() => {
    connector.deactivate();
    connector.__setFacadeForTests(undefined);
  });
}

/**
 * Wait for a predicate by polling. Never a fixed sleep: Node clamps short
 * timers (≈15 ms on Windows), so a "give it 5 ms" assertion is a flake.
 */
async function waitFor(predicate, timeoutMs = 2000) {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() > deadline) return false;
    await new Promise((resolve) => setTimeout(resolve, 2));
  }
  return true;
}

async function call(host, action, params = {}) {
  const id = `req-${Math.random().toString(36).slice(2, 8)}`;
  // The connector's register callback wraps onMessage in `void`, so the
  // dispatch is not awaitable from here — poll for the answer frame instead.
  void host.__onMessage({ data: JSON.stringify({ id, action, params }) });
  assert.ok(
    await waitFor(() => (host.__sent ?? []).some((f) => f.id === id)),
    `no response frame for ${action}`,
  );
  return (host.__sent ?? []).find((f) => f.id === id);
}

test('sch.netlist returns the editor netlist and names its source', async (t) => {
  const host = edaHost();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.netlist', {});
  assert.equal(frame.ok, true);
  assert.equal(frame.data.type, 'EasyEDA');
  assert.equal(frame.data.source, 'getNetlistFile');
  assert.match(frame.data.text, /netlist for EasyEDA/);
});

test('sch.netlist validates the requested type but accepts any known one', async (t) => {
  const host = edaHost();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.netlist', { type: 'Protel2' });
  assert.equal(frame.ok, true);
  assert.equal(frame.data.type, 'Protel2');
});

test('sch.doc.new creates a page inside the current schematic and focuses it', async (t) => {
  const host = edaHost();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.doc.new', { name: 'draw' });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.schematicUuid, 'sch-1');
  assert.equal(frame.data.pageUuid, 'page-of-sch-1');
  assert.equal(frame.data.focused, true);
  assert.deepEqual(host.__opened, ['page-of-sch-1'], 'the new page must be opened');
});

test('write actions refuse to place when the focused page is not the target', async (t) => {
  const host = edaHost();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.place_component', {
    lcsc: 'C14663', x: 0, y: 0, designator: 'C1',
    pageUuid: 'some-other-page',
  });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'PAGE_MISMATCH');
  assert.match(frame.error.message, /refusing to place/);
});

test('sch.place_component resolves by LCSC, places, and names the designator', async (t) => {
  const host = edaHost();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.place_component', {
    lcsc: 'C14663',
    x: 100,
    y: -50,
    rotation: 90,
    designator: 'C1',
  });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.resolvedBy, 'lcsc');
  assert.equal(frame.data.device.uuid, 'dev-C14663');
  assert.ok(frame.data.uuid.startsWith('comp-'));

  const placed = host.__calls.component[0];
  assert.equal(placed.component.uuid, 'dev-C14663');
  assert.equal(placed.component.libraryUuid, 'lib-1');
  assert.equal(placed.x, 100);
  assert.equal(placed.y, -50);
  assert.equal(placed.rotation, 90);
  assert.equal(placed.intoBom, true, 'a real part belongs in the BOM');
  assert.equal(placed.intoPcb, true, 'a real part goes to PCB');
  // The designator goes through `modify(primitiveId, …)` — the measured path
  // that actually works (`setState_Designator`+`done()` silently did nothing).
  assert.deepEqual(host.__calls.componentModify[0], {
    primitiveId: frame.data.uuid,
    property: { designator: 'C1' },
  });
});

test('sch.place_component falls back to keyword search and reports it', async (t) => {
  const host = edaHost();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.place_component', { keyword: 'CH340G', x: 0, y: 0 });
  assert.equal(frame.ok, true);
  assert.equal(frame.data.resolvedBy, 'keyword');
  assert.deepEqual(host.__calls.search, ['CH340G']);
});

test('sch.place_component fails structurally when nothing matches', async (t) => {
  const host = edaHost();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.place_component', { keyword: 'nothing matches this', x: 0, y: 0 });
  assert.equal(frame.ok, false);
  assert.match(frame.error.message, /matched no library device/);

  const noArgs = await call(host, 'sch.place_component', { x: 0, y: 0 });
  assert.equal(noArgs.ok, false);
  assert.match(noArgs.error.message, /needs one of/);
});

test('sch.place_wire passes points through and reports the uuid', async (t) => {
  const host = edaHost();
  withEda(t, host);
  await connector.activate();

  const points = [[0, 0], [100, 0], [100, 200]];
  const frame = await call(host, 'sch.place_wire', { points, net: 'GND' });
  assert.equal(frame.ok, true);
  assert.ok(frame.data.uuid.startsWith('wire-'));
  // The editor rejects pair arrays at runtime ("create failed!", measured
  // 2026-09-13) — the handler must flatten before the call.
  assert.deepEqual(host.__calls.wire[0].points, [0, 0, 100, 0, 100, 200]);
  assert.equal(host.__calls.wire[0].net, 'GND');

  const bad = await call(host, 'sch.place_wire', { points: [[0, 0]] });
  assert.equal(bad.ok, false);
  assert.equal(bad.error.code, 'BAD_REQUEST');
});

test('sch.place_netlabel and sch.place_power pass their geometry through', async (t) => {
  const host = edaHost();
  withEda(t, host);
  await connector.activate();

  const label = await call(host, 'sch.place_netlabel', { x: 10, y: 20, net: 'V3' });
  assert.equal(label.ok, true);
  assert.deepEqual(host.__calls.netLabel[0], { x: 10, y: 20, net: 'V3' });

  const flag = await call(host, 'sch.place_power', { kind: 'Ground', net: 'GND', x: 5, y: 6 });
  assert.equal(flag.ok, true, JSON.stringify(flag));
  assert.deepEqual(host.__calls.netFlag[0], {
    kind: 'Ground', net: 'GND', x: 5, y: 6, rotation: 0, mirror: false,
  });

  const badKind = await call(host, 'sch.place_power', { kind: 'Sparkle', net: 'GND', x: 0, y: 0 });
  assert.equal(badKind.ok, false);
  assert.equal(badKind.error.code, 'BAD_REQUEST');
});

test('sch.place_netport passes direction and net through', async (t) => {
  const host = edaHost();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.place_netport', {
    direction: 'BI', net: 'RX', x: 30, y: 40,
  });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.deepEqual(host.__calls.netPort[0], {
    direction: 'BI', net: 'RX', x: 30, y: 40, rotation: 0, mirror: false,
  });

  const bad = await call(host, 'sch.place_netport', { direction: 'SIDEWAYS', net: 'RX', x: 0, y: 0 });
  assert.equal(bad.ok, false);
  assert.equal(bad.error.code, 'BAD_REQUEST');
});

test('sch.geometry dumps every namespace with uuids preserved', async (t) => {
  const host = edaHost();
  withEda(t, host);
  await connector.activate();
  // Seed one wire through the real handler so the dump has content.
  await call(host, 'sch.place_wire', { points: [[0, 0], [10, 0]] });

  const frame = await call(host, 'sch.geometry', {});
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(
    frame.data.meta.available.components, true, JSON.stringify(frame.data.meta),
  );
  assert.equal(frame.data.meta.available.wires, true);
  assert.equal(frame.data.meta.available.pins, true);
});
