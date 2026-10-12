/**
 * 174: `pcb.geometry` — the **measured** rendered box of PCB primitives.
 *
 * The action exists because 172 could not finish its sentence without it: a
 * board's silk designator width is not in the `.epru` file (a font size and a
 * character count are), so 「这条丝印压上焊盘了吗」 can only be answered by
 * measuring the canvas. `eda.pcb_Primitive.getPrimitivesBBox` is the API that
 * reports where a primitive actually is — easyeda-agent's `pcbSilkAlign`
 * measures every designator ATTR with exactly this call — and 172's wiring had
 * to borrow the **schematic** twin (`sch.geometry`) for the job. This test
 * file pins the PCB action that replaces that borrow.
 *
 * What is pinned, and why each one:
 *
 * 1. **The call shape** — one `getPrimitivesBBox(id list)` call per id, with the
 *    id passed as an array. Measured on the reference connector: the host
 *    answers the **union** box of the list it is given, so batching ids would
 *    silently give every id the same box.
 * 2. **Read-only** — `pcb_Primitive` carries `create` / `modify` / `delete` and
 *    a whole `pcb_Primitive*` family of writing namespaces; the fake installs a
 *    loud tripwire on every one of them. A measuring action that draws is the
 *    one failure this action cannot afford.
 * 3. **"The host has no box" and "this host cannot measure" are different
 *    readings** — the first lands in `meta.unreadable` naming the id, the second
 *    sets `meta.available.bboxes = false` with a reason. A single empty `bboxes`
 *    table would be read by 172's caller as "measured, nothing there", which is
 *    exactly the kind of number-that-looks-like-a-reading 172 removed.
 * 4. **A half-filled box never becomes geometry** — a host that answers
 *    `{minX: 1}` (or `{minX: undefined, …}` for an unknown id, the schematic
 *    twin's measured behaviour) is reported as unreadable rather than recorded
 *    as a box whose `maxX` is `undefined`.
 *
 * All offline, against a fake `eda`. What the host's real boxes are is a live
 * question answered in `outputs/174/evidence.md`, not here.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { buildHandlers } from '../dist/esm/actions.mjs';

/** Writing / drawing members of the `pcb_Primitive*` namespaces, as a tripwire. */
const FORBIDDEN_CALLS = ['create', 'modify', 'delete', 'setState', 'createBatch'];

function fakeEda(overrides = {}) {
  const calls = { bbox: [], forbidden: [] };
  const primitive = {
    async getPrimitivesBBox(ids) {
      calls.bbox.push([...ids]);
      const id = ids[0];
      if (id === 'attr-1') return { minX: 10, minY: 20, maxX: 40, maxY: 60 };
      if (id === 'attr-2') return { minX: -5, minY: -6, maxX: 7, maxY: 8 };
      if (id === 'attr-junk') return { minX: 1, minY: 2 };   // no maxX/maxY
      if (id === 'attr-throws') throw new Error('canvas not ready');
      return undefined;                                       // the host knows no such id
    },
  };
  for (const name of FORBIDDEN_CALLS) {
    primitive[name] = async (...args) => {
      calls.forbidden.push([name, args]);
      throw new Error(`forbidden write reached the host: pcb_Primitive.${name}`);
    };
  }
  const eda = { pcb_Primitive: primitive, ...overrides };
  return { eda, calls };
}

const call = (eda, params = {}) => buildHandlers(eda)['pcb.geometry'](params);

test('pcb.geometry measures one id per call and keys the boxes by that id', async () => {
  const { eda, calls } = fakeEda();
  const report = await call(eda, { bboxIds: ['attr-1', 'attr-2'] });

  assert.deepEqual(calls.bbox, [['attr-1'], ['attr-2']], 'the ids are measured one at a time');
  assert.deepEqual(report.bboxes, {
    'attr-1': { minX: 10, minY: 20, maxX: 40, maxY: 60 },
    'attr-2': { minX: -5, minY: -6, maxX: 7, maxY: 8 },
  });
  assert.deepEqual(report.meta.available, { bboxes: true });
  assert.equal(report.meta.requested, 2);
  assert.equal(report.meta.measured, 2);
  assert.deepEqual(report.meta.unreadable, undefined, 'nothing to report about');
});

test('pcb.geometry deduplicates the ids it was given, keeping the caller\'s order', async () => {
  const { eda, calls } = fakeEda();
  const report = await call(eda, { bboxIds: ['attr-2', 'attr-1', 'attr-2', ''] });
  assert.deepEqual(calls.bbox, [['attr-2'], ['attr-1']], 'an empty id is not a primitive');
  assert.deepEqual(Object.keys(report.bboxes), ['attr-2', 'attr-1']);
  assert.equal(report.meta.requested, 2);
});

test('pcb.geometry names the ids the host had no box for, instead of dropping them', async () => {
  const { eda } = fakeEda();
  const report = await call(eda, { bboxIds: ['attr-1', 'attr-nowhere', 'attr-throws'] });

  assert.deepEqual(Object.keys(report.bboxes), ['attr-1'], 'the readable box is still the answer');
  assert.equal(report.meta.measured, 1);
  assert.equal(report.meta.requested, 3);
  assert.equal(report.meta.available.bboxes, true, 'the call is available; one id had no box');
  assert.equal(report.meta.unreadable.length, 2);
  assert.match(report.meta.unreadable[0], /^attr-nowhere: the host returned no box/);
  assert.match(report.meta.unreadable[1], /^attr-throws: the measuring call threw: canvas not ready/);
});

test('pcb.geometry records a half-filled box as unreadable, never as geometry', async () => {
  const { eda } = fakeEda();
  const report = await call(eda, { bboxIds: ['attr-junk'] });
  assert.deepEqual(report.bboxes, {}, 'a box missing maxX/maxY is not a box');
  assert.equal(report.meta.unreadable.length, 1);
  assert.match(report.meta.unreadable[0], /no finite minX\/minY\/maxX\/maxY/);
});

test('pcb.geometry says the host cannot measure, and why, when the API is absent', async () => {
  for (const host of [{}, { pcb_Primitive: {} }, { pcb_Primitive: { getPrimitivesBBox: 'not a function' } }]) {
    const report = await call(host, { bboxIds: ['attr-1'] });
    assert.deepEqual(report.bboxes, {});
    assert.deepEqual(report.meta.available, { bboxes: false }, JSON.stringify(host));
    assert.match(report.meta.reasons.bboxes, /pcb_Primitive\.getPrimitivesBBox/);
    assert.equal(report.meta.requested, 1, 'the request is still recorded as asked');
  }
});

test('pcb.geometry with no bboxIds answers an empty table without calling the host', async () => {
  const { eda, calls } = fakeEda();
  const report = await call(eda);
  assert.deepEqual(calls.bbox, []);
  assert.deepEqual(report.bboxes, {});
  assert.deepEqual(report.meta.available, { bboxes: true });
  assert.equal(report.meta.requested, 0);
});

test('pcb.geometry never reaches a writing member of the namespace', async () => {
  const { eda, calls } = fakeEda();
  await call(eda, { bboxIds: ['attr-1', 'attr-2', 'attr-junk', 'attr-throws'] });
  assert.deepEqual(calls.forbidden, [], 'only getPrimitivesBBox is on the list');
});

test('a hostile host object that throws on member reads is reported, not crashed through', async () => {
  // The host hands out exotic objects (026-era lesson): a property read is a
  // trap invocation and may throw. The answer must be "cannot measure", with
  // the reason, rather than an INTERNAL from the transport.
  const eda = {
    get pcb_Primitive() {
      throw new Error('exotic proxy');
    },
  };
  const report = await call(eda, { bboxIds: ['attr-1'] });
  assert.deepEqual(report.bboxes, {});
  assert.deepEqual(report.meta.available, { bboxes: false });
});

test('the catalogue, the handler registry and the docs table all list pcb.geometry', async () => {
  // The five touchpoints of adding an action, asserted here so this file fails
  // on its own rather than only in the repo-wide contract-drift guard.
  const { readFileSync } = await import('node:fs');
  const root = new URL('../../', import.meta.url);
  const text = (url) => readFileSync(new URL(url, root), 'utf8').replace(/\r\n/g, '\n');

  const protocol = text('src/boardwise/bridge/protocol.py');
  const actions = text('connector/src/actions.ts');
  const docs = text('docs/bridge.md');

  assert.match(protocol, /\n\s*name="pcb\.geometry",/);
  assert.match(protocol, /name="pcb\.geometry",[\s\S]{0,1500}?risk="read",/);
  assert.match(actions, /^\s*'pcb\.geometry': bind\(pcbGeometry\),/m);
  assert.match(docs, /^\| `pcb\.geometry` \| connector \| read \| connector \|/m);
});
