/**
 * `sch.set_component_attribute` — the two defects §J.1 measured, pinned.
 *
 * Both are properties of the *host*, not preferences:
 *
 * 1. `modify`'s `otherProperty` replaces the whole map instead of merging, so
 *    a per-key write loop silently keeps only its last key (measured
 *    2026-09-15 on C1: `Value` was wiped by the `Supplier Footprint` write
 *    that followed it).
 * 2. `modify`'s return value is not evidence — the action must read the
 *    property map back and define `applied` as "read-back equals target",
 *    or a silent no-op looks like success.
 *
 * The fakes below model exactly those two behaviours, so a regression in
 * either direction fails here rather than on the bench.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { createFacade } from '../dist/esm/facade.mjs';
import * as connector from '../dist/esm/index.mjs';

/** A component holding an `otherProperty` map, mutated the way the host does. */
class FakeComponent {
  constructor(map = {}) {
    this.map = { ...map };
    this.writes = 0;
  }
}

/**
 * `modify` replaces the whole map (the measured behaviour of 3.2.186).
 * `honour` false models a host that accepts the call and stores nothing.
 */
function host({ initial = {}, honour = true } = {}) {
  const components = new Map([['c1', new FakeComponent(initial)]]);
  const hostObject = {
    sys_WebSocket: {
      register(_id, _uri, onMessage) { hostObject.__onMessage = onMessage; },
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
      async modify(primitiveId, property) {
        const component = components.get(primitiveId);
        if (!component) return undefined;
        component.writes += 1;
        if (!honour) return component;           // accepted, stored nothing
        component.map = { ...(property.otherProperty ?? {}) };  // REPLACE
        return component;
      },
      async get(primitiveId) {
        const component = components.get(primitiveId);
        if (!component) return undefined;
        return {
          getState_OtherProperty() { return { ...component.map }; },
        };
      },
    },
    __components: components,
  };
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

test('two consecutive writes with different keys do not erase each other', async (t) => {
  // This is the §J.1 regression: on the bench the Value write came back empty
  // because the Supplier Footprint write after it replaced the whole map.
  const h = host();
  withEda(t, h);
  await connector.activate();
  await connector.activate();

  const first = await call(h, 'sch.set_component_attribute', {
    primitiveId: 'c1', key: 'Value', value: '100nF',
  });
  assert.equal(first.ok, true);
  assert.equal(first.data.applied, true);

  const second = await call(h, 'sch.set_component_attribute', {
    primitiveId: 'c1', key: 'Supplier Footprint', value: '0603',
  });
  assert.equal(second.ok, true);
  assert.equal(second.data.applied, true);

  const finalMap = h.__components.get('c1').map;
  assert.equal(finalMap.Value, '100nF', 'the earlier key must survive');
  assert.equal(finalMap['Supplier Footprint'], '0603');
});

test('the draw form writes every key in one call', async (t) => {
  const h = host();
  withEda(t, h);
  await connector.activate();
  await connector.activate();

  const frame = await call(h, 'sch.set_component_attribute', {
    primitiveId: 'c1',
    attributes: { Value: '5.1K', 'Supplier Footprint': '0402' },
  });
  assert.equal(frame.ok, true);
  assert.deepEqual(frame.data.attributes, {
    Value: '5.1K', 'Supplier Footprint': '0402',
  });
  assert.equal(h.__components.get('c1').writes, 1, 'one modify call, not two');
  assert.deepEqual(h.__components.get('c1').map, {
    Value: '5.1K', 'Supplier Footprint': '0402',
  });
});

test('applied is the read-back, not the call succeeding', async (t) => {
  // A host that accepts the write and stores nothing must not report success.
  const h = host({ honour: false });
  withEda(t, h);
  await connector.activate();
  await connector.activate();

  const frame = await call(h, 'sch.set_component_attribute', {
    primitiveId: 'c1', attributes: { Value: '100nF' },
  });
  assert.equal(frame.ok, true, 'the call itself did not throw');
  assert.equal(frame.data.wrote, true, 'the host returned an object');
  assert.equal(frame.data.applied, false, 'but nothing was stored');
  assert.equal(frame.data.mismatched.length, 1);
});

test('existing keys the caller did not touch are preserved and reported', async (t) => {
  const h = host({ initial: { Manufacturer: 'UNI-ROYAL', Value: '' } });
  withEda(t, h);
  await connector.activate();
  await connector.activate();

  const frame = await call(h, 'sch.set_component_attribute', {
    primitiveId: 'c1', attributes: { Value: '5.1K' },
  });
  assert.equal(frame.data.applied, true);
  const stored = h.__components.get('c1').map;
  assert.equal(stored.Manufacturer, 'UNI-ROYAL', 'merge, not replace');
  assert.deepEqual(frame.data.otherPropertyBefore, { Manufacturer: 'UNI-ROYAL', Value: '' });
  assert.equal(frame.data.otherPropertyAfter.Value, '5.1K');
});
