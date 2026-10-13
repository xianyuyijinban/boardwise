/**
 * R1-1: `pcb.place_component` — a library device's footprint onto the focused PCB.
 *
 * The gap: the bridge could read a board and move or delete what was on it, but
 * never put anything there, so the empty test board had nothing for a live
 * check (172's measured silk width) to measure. The host call is
 * `pcb_PrimitiveComponent.create(component, layer, x, y, rotation,
 * primitiveLock)`, declared `@beta`; whether the calibrated host implements it
 * is a live reading (`outputs/R1/`), not something this file can know.
 *
 * What is pinned here, all offline against a fake `eda`:
 *
 * 1. **Never unguarded** — `pageUuid` is required, and a board that is not the
 *    focused one is a `PAGE_MISMATCH`; in both cases `create` is never reached.
 * 2. **The call shape** — the bare `{libraryUuid, uuid}` pair, the numeric
 *    layer (top 1 / bottom 2), the rounded coordinates, the rotation and
 *    `primitiveLock: false`, in the declaration's argument order.
 * 3. **The same resolver as the schematic placement** — LCSC / uuid pair /
 *    keyword resolve exactly as `sch.place_component` resolves them, and a
 *    request naming none of them is refused under this action's own name.
 * 4. **A miss is read back by diffing the board's component ids**, not by
 *    proximity: a timeout that landed says `landedAnyway: true` with the new
 *    id, a refusal that left nothing says `false`, a part that was already
 *    sitting on the requested point does not count as a landing, and a board
 *    that cannot be enumerated says `null` (unknown) — never "nothing landed".
 * 5. **The answer is checkable** — `requested` (what was asked), `placed` (what
 *    the returned primitive reports, `null` per field the host did not say)
 *    and `appeared` (the board diff) travel side by side.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { buildHandlers } from '../dist/esm/actions.mjs';

const PCB = 'pcb-1';
const DEVICE = { uuid: 'dev-0603', libraryUuid: 'lib-sys', name: '0603WAF1002T5E' };

/** A placed component as the host hands it back: `getState_*` getters only. */
function component(id, { x, y, rotation = 0, layer = 1, designator = 'R1' }) {
  return {
    getState_PrimitiveId: () => id,
    getState_X: () => x,
    getState_Y: () => y,
    getState_Rotation: () => rotation,
    getState_Layer: () => layer,
    getState_Designator: () => designator,
  };
}

/**
 * A host with one focused board and a device library.
 *
 * `create` is the knob: `'land'` stores the part and returns it, `'empty'`
 * answers `undefined` and stores nothing, `'throw'` rejects, `'hang-land'`
 * stores the part but never settles (the 006b shape: timed out *and* landed).
 * `board` seeds components already on the board; `enumerable: false` makes
 * `getAllPrimitiveId` unavailable.
 */
function fakeEda({ create = 'land', focused = PCB, board = [], enumerable = true } = {}) {
  const calls = { create: [], lcsc: [], search: [], get: [] };
  const onBoard = new Map(board.map((part) => [part.id, part]));
  let next = 1;
  const pcbComponent = {
    async create(...args) {
      calls.create.push(args);
      const id = `cmp-new-${next++}`;
      const [, layer, x, y, rotation] = args;
      if (create === 'empty') return undefined;
      if (create === 'throw') throw new Error('library device has no footprint');
      onBoard.set(id, { id, x, y });
      const placed = component(id, { x, y, rotation, layer, designator: 'U?' });
      if (create === 'hang-land') return new Promise(() => {});
      return placed;
    },
  };
  if (enumerable) {
    pcbComponent.getAllPrimitiveId = async () => [...onBoard.keys()];
  }
  const eda = {
    dmt_Pcb: { getCurrentPcbInfo: async () => (focused ? { uuid: focused } : undefined) },
    lib_Device: {
      async getByLcscIds(ids) {
        calls.lcsc.push(ids);
        return ids[0] === 'C25804' ? [DEVICE] : [];
      },
      async search(keyword) {
        calls.search.push(keyword);
        return keyword === '0603 10k' ? [DEVICE] : [];
      },
      async get(uuid, libraryUuid) {
        calls.get.push([uuid, libraryUuid]);
        if (uuid !== DEVICE.uuid) return undefined;
        return {
          getState_Uuid: () => DEVICE.uuid,
          getState_LibraryUuid: () => DEVICE.libraryUuid,
          getState_Name: () => DEVICE.name,
        };
      },
    },
    pcb_PrimitiveComponent: pcbComponent,
  };
  return { eda, calls, onBoard };
}

const place = (eda, params) => buildHandlers(eda)['pcb.place_component'](params);

async function refusal(promise) {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  assert.fail('expected the placement to be refused');
}

test('pcb.place_component refuses to write without a pageUuid, before touching the host', async () => {
  const { eda, calls } = fakeEda();
  for (const params of [{ lcsc: 'C25804', x: 0, y: 0 }, { pageUuid: '  ', lcsc: 'C25804', x: 0, y: 0 }]) {
    const error = await refusal(place(eda, params));
    assert.equal(error.code, 'BAD_REQUEST');
    assert.match(error.message, /pageUuid/);
  }
  assert.deepEqual(calls.create, []);
  assert.deepEqual(calls.lcsc, [], 'the library is not even asked');
});

test('pcb.place_component refuses a board that is not the focused one', async () => {
  const { eda, calls } = fakeEda({ focused: 'pcb-other' });
  const error = await refusal(place(eda, { pageUuid: PCB, lcsc: 'C25804', x: 0, y: 0 }));
  assert.equal(error.code, 'PAGE_MISMATCH');
  assert.equal(error.detail.expected, PCB);
  assert.equal(error.detail.actual, 'pcb-other');
  assert.deepEqual(calls.create, []);
});

test('pcb.place_component places the resolved device with the declared argument order', async () => {
  const { eda, calls } = fakeEda();
  const data = await place(eda, { pageUuid: PCB, lcsc: 'C25804', x: 1000.004, y: -250, rotation: 90 });

  assert.equal(calls.create.length, 1);
  assert.deepEqual(calls.create[0], [
    { libraryUuid: DEVICE.libraryUuid, uuid: DEVICE.uuid },
    1,
    1000,
    -250,
    90,
    false,
  ], 'component ref, layer, x, y, rotation, primitiveLock');
  assert.equal(data.uuid, 'cmp-new-1');
  assert.deepEqual(data.device, DEVICE);
  assert.equal(data.resolvedBy, 'lcsc');
  assert.deepEqual(data.requested, { x: 1000, y: -250, rotation: 90, layer: 'top' });
  assert.deepEqual(data.placed, { x: 1000, y: -250, rotation: 90, layer: 1, designator: 'U?' });
  assert.deepEqual(data.appeared, ['cmp-new-1'], 'exactly one new component on the board');
  assert.equal(typeof data.elapsedMs, 'number');
});

test('pcb.place_component puts a part on the bottom side and rejects any other side', async () => {
  const { eda, calls } = fakeEda();
  const data = await place(eda, { pageUuid: PCB, lcsc: 'C25804', x: 0, y: 0, layer: ' Bottom ' });
  assert.equal(calls.create[0][1], 2);
  assert.equal(data.requested.layer, 'bottom');

  for (const layer of ['inner1', 3, '']) {
    const error = await refusal(place(eda, { pageUuid: PCB, lcsc: 'C25804', x: 0, y: 0, layer }));
    assert.equal(error.code, 'BAD_REQUEST');
    assert.match(error.message, /'top' or 'bottom'/);
  }
  assert.equal(calls.create.length, 1, 'a refused side never reaches the host');
});

test('pcb.place_component rejects coordinates and rotations that are not numbers', async () => {
  const { eda, calls } = fakeEda();
  for (const params of [{ x: 'left', y: 0 }, { x: 0, y: 'up', rotation: 0 }, { x: 0, y: 0, rotation: 'ninety' }]) {
    const error = await refusal(place(eda, { pageUuid: PCB, lcsc: 'C25804', ...params }));
    assert.equal(error.code, 'BAD_REQUEST', JSON.stringify(params));
  }
  assert.deepEqual(calls.create, []);
});

test('pcb.place_component walks the schematic placement\'s resolution ladder', async () => {
  const { eda, calls } = fakeEda();
  const byUuid = await place(eda, {
    pageUuid: PCB, deviceUuid: DEVICE.uuid, libraryUuid: DEVICE.libraryUuid, x: 0, y: 0,
  });
  assert.equal(byUuid.resolvedBy, 'uuid');
  assert.deepEqual(calls.get, [[DEVICE.uuid, DEVICE.libraryUuid]]);

  const byKeyword = await place(eda, { pageUuid: PCB, keyword: '0603 10k', x: 0, y: 0 });
  assert.equal(byKeyword.resolvedBy, 'keyword');
  assert.deepEqual(byKeyword.device, DEVICE);

  const none = await refusal(place(eda, { pageUuid: PCB, x: 0, y: 0 }));
  assert.equal(none.code, 'BAD_REQUEST');
  assert.match(none.message, /^pcb\.place_component needs one of lcsc/);

  const miss = await refusal(place(eda, { pageUuid: PCB, lcsc: 'C0000', x: 0, y: 0 }));
  assert.equal(miss.code, 'CONNECTOR_ERROR');
  assert.match(miss.message, /C0000 matched no library device/);
  assert.equal(calls.create.length, 2, 'only the two resolved requests were placed');
});

test('a host without the PCB create call says so by name', async () => {
  const { eda } = fakeEda();
  delete eda.pcb_PrimitiveComponent.create;
  const error = await refusal(place(eda, { pageUuid: PCB, lcsc: 'C25804', x: 0, y: 0 }));
  assert.equal(error.code, 'NOT_IMPLEMENTED');
  assert.match(error.message, /pcb_PrimitiveComponent\.create/);
});

test('a placement that timed out but landed says so, with the new id, and says do not retry', async () => {
  const { eda, onBoard } = fakeEda({ create: 'hang-land' });
  const error = await refusal(place(eda, { pageUuid: PCB, lcsc: 'C25804', x: 0, y: 0, timeoutMs: 200 }));
  assert.equal(error.code, 'TIMEOUT');
  assert.match(error.message, /did not settle within 200 ms/);
  assert.match(error.message, /DID appear.*do NOT retry/);
  assert.equal(error.detail.landedAnyway, true);
  assert.deepEqual(error.detail.appeared, ['cmp-new-1']);
  assert.ok(onBoard.has('cmp-new-1'));
});

test('a host that answers nothing is not a timeout, and nothing landed', async () => {
  const { eda } = fakeEda({ create: 'empty' });
  const error = await refusal(place(eda, { pageUuid: PCB, lcsc: 'C25804', x: 0, y: 0 }));
  assert.equal(error.code, 'CONNECTOR_ERROR');
  assert.match(error.message, /answered undefined/);
  assert.match(error.message, /nothing landed/);
  assert.equal(error.detail.landedAnyway, false);
  assert.deepEqual(error.detail.appeared, []);
});

test('a host that throws is reported with its reason and the board diff', async () => {
  const { eda } = fakeEda({ create: 'throw' });
  const error = await refusal(place(eda, { pageUuid: PCB, lcsc: 'C25804', x: 0, y: 0 }));
  assert.equal(error.code, 'CONNECTOR_ERROR');
  assert.match(error.message, /threw: library device has no footprint/);
  assert.equal(error.detail.landedAnyway, false);
});

test('a part already sitting on the requested point is not read as a landing', async () => {
  // Proximity — the schematic action's test — would answer "landed" here.
  const { eda } = fakeEda({ create: 'empty', board: [{ id: 'cmp-old', x: 0, y: 0 }] });
  const error = await refusal(place(eda, { pageUuid: PCB, lcsc: 'C25804', x: 0, y: 0 }));
  assert.equal(error.detail.landedAnyway, false);
  assert.deepEqual(error.detail.appeared, []);
});

test('a board that cannot be enumerated makes the readback unknown, never "nothing landed"', async () => {
  const { eda } = fakeEda({ create: 'empty', enumerable: false });
  const error = await refusal(place(eda, { pageUuid: PCB, lcsc: 'C25804', x: 0, y: 0 }));
  assert.equal(error.detail.landedAnyway, null);
  assert.equal(error.detail.appeared, null);
  assert.match(error.message, /UNKNOWN/);
  assert.doesNotMatch(error.message, /nothing landed/);

  // On success the placement still answers; only the diff is unknown.
  const ok = fakeEda({ enumerable: false });
  const data = await place(ok.eda, { pageUuid: PCB, lcsc: 'C25804', x: 0, y: 0 });
  assert.equal(data.uuid, 'cmp-new-1');
  assert.equal(data.appeared, null);
});

test('a returned primitive that hides its getters yields nulls, not a failed placement', async () => {
  const { eda } = fakeEda();
  eda.pcb_PrimitiveComponent.create = async () => ({ getState_PrimitiveId: () => 'cmp-bare' });
  const data = await place(eda, { pageUuid: PCB, lcsc: 'C25804', x: 5, y: 6 });
  assert.equal(data.uuid, 'cmp-bare');
  assert.deepEqual(data.placed, { x: null, y: null, rotation: null, layer: null, designator: null });
  assert.deepEqual(data.requested, { x: 5, y: 6, rotation: 0, layer: 'top' });
});
