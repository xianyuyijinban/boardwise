/**
 * `sys.connector_status` — the promoted diagnostics action (026b), and the one
 * thing it is for: telling an *inert* extension from an *absent* one.
 *
 * The action answers the question no daemon-side surface can. On 立创 EDA
 * 3.2.149 the host may evaluate our bundle and never dispatch `activate()`
 * (upstream #219/#221), and from outside that looks exactly like a connector
 * that is not running at all — no socket, no log, nothing to ask. These are the
 * readings that separate "the host never evaluated our bundle" from "the host
 * evaluated it and never called us": `moduleBootstrapObserved`,
 * `activateObserved`, `evaluations`, plus the background watchdog's state
 * (`running` / `unavailable(<reason>)` / `not started`), which is the difference
 * between a window that recovers by itself in the background and one that waits
 * for the user to bring it to the front.
 *
 * Its honour rules are the probe batch's, kept after the probe itself was
 * deleted (0.4.18 / 026c): **a reading, never a guess.** No published runtime
 * record answers `present: false` — never an empty success and never invented
 * counters; a member read that throws is reported as a failed read, because on
 * this host a member read is a trap invocation that can throw.
 *
 * Everything here is offline: the record is stood up by hand, so the tests pin
 * what the action reports for each shape a real record can be in.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { buildHandlers } from '../dist/esm/actions.mjs';

function fakeEda(overrides = {}) {
  return {
    dmt_SelectControl: {
      getCurrentDocumentInfo: async () => ({ uuid: 'page-1', name: 'P1', documentType: 1, tabId: 't1' }),
    },
    ...overrides,
  };
}

const status = (eda = fakeEda()) => buildHandlers(eda)['sys.connector_status']({});

test('sys.connector_status reports present:false when no evaluation published a runtime', async () => {
  // The honest absence: no record under `__boardwiseTransportRuntime` means this
  // editor has no evaluation of our bundle, which is a *different* failure from
  // a bundle that loaded and never activated (026b §2.4).
  const report = await status(fakeEda());
  assert.equal(report.present, false);
  assert.equal(report.observed, 'undefined');
  assert.match(String(report.note), /no evaluation published one/);
});

test('sys.connector_status reports present:false, not a crash, when the member read throws', async () => {
  // Host objects are Proxies whose `get` trap throws on this editor. A
  // diagnostic that dies on its own subject is worse than useless.
  const eda = {};
  Object.defineProperty(eda, '__boardwiseTransportRuntime', {
    get() {
      throw new Error('proxy get trap refused');
    },
  });
  const report = await status(eda);
  assert.equal(report.present, false);
  assert.match(String(report.error), /proxy get trap refused/);
});

test('sys.connector_status reports present:false when the record is not an object', async () => {
  const report = await status(fakeEda({ __boardwiseTransportRuntime: 'not a record' }));
  assert.equal(report.present, false);
  assert.equal(report.observed, 'string');
});

test('sys.connector_status says readStatus:false when the record has no getStatus', async () => {
  const report = await status(fakeEda({ __boardwiseTransportRuntime: { implementation: 'x' } }));
  assert.equal(report.present, true);
  assert.equal(report.readStatus, false);
  assert.match(String(report.error), /getStatus is undefined/);
});

test('sys.connector_status lifts the three lifecycle counters out of the status read-out', async () => {
  // Spelled out beside the full status because these three are the whole
  // question of issue #4, and a caller should not have to know where they live.
  const published = {
    getStatus: () => ({
      state: 'connected',
      moduleBootstrapObserved: true,
      activateObserved: false,
      evaluations: 3,
      fingerprint: '53cd3b41',
      watchdog: { state: 'running', wakes: 2, activityPosts: 11, checkIntervalMs: 15000, activityTimeoutMs: 30000 },
    }),
  };
  const report = await status(fakeEda({ __boardwiseTransportRuntime: published }));

  assert.equal(report.present, true);
  assert.equal(report.readStatus, true);
  assert.equal(report.moduleBootstrapObserved, true);
  assert.equal(report.activateObserved, false);
  assert.equal(report.evaluations, 3);
  assert.deepEqual(report.status.watchdog, {
    state: 'running',
    wakes: 2,
    activityPosts: 11,
    checkIntervalMs: 15000,
    activityTimeoutMs: 30000,
  });
});

test('sys.connector_status reports a throwing getStatus instead of pretending it read one', async () => {
  const published = {
    getStatus: () => {
      throw new Error('the controller was released');
    },
  };
  const report = await status(fakeEda({ __boardwiseTransportRuntime: published }));
  assert.equal(report.present, true);
  assert.equal(report.readStatus, false);
  assert.match(String(report.error), /the controller was released/);
});

test('the record is called through its own object, never detached from it', async () => {
  // `getStatus` closes over the publishing evaluation's module state, so a
  // detached call would answer about nothing. The action calls it as a method.
  let sawThis = null;
  const published = {
    marker: 'the record',
    getStatus() {
      sawThis = this;
      return { state: 'connected' };
    },
  };
  await status(fakeEda({ __boardwiseTransportRuntime: published }));
  assert.equal(sawThis, published);
});

test('the retired probe action is gone, and the registry says so', async () => {
  // 0.4.18 (026c): `sys.worker_probe` was deleted once its last question (P6)
  // had been answered on the machine. A handler that quietly remained would be
  // unreachable dead weight — the daemon refuses the name before it is ever
  // forwarded — so the registry is asserted directly, and the catalogue and docs
  // tables are held in step with it by `contract-drift.test.mjs`.
  const handlers = buildHandlers(fakeEda());
  assert.equal('sys.worker_probe' in handlers, false, 'the probe action must be gone');
  assert.equal('sys.connector_status' in handlers, true, 'and its promoted replacement must remain');
});
