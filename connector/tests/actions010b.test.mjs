/**
 * Task 010b: the editor's post-netlist lock window, and the bounded retry.
 *
 * Measured 2026-09-18 (host 3.2.186, pro-api 0.3.18, connector 0.4.4): for a
 * few seconds after a `sch.netlist` probe returns, `sch_PrimitiveWire.create`
 * throws `create failed!` in 1-3 ms while the same call with the same arguments
 * succeeds before the probe and again after the window closes. The draw flow
 * validates the page before it wires, so a 10-run block lost every wire and the
 * `place_wire` action answered `ok: false` with nothing to say about why.
 *
 * What these tests pin is the *shape* of the repair, at the boundary the daemon
 * sees — the same `ok` / `error.code` envelope the rest of the suite checks:
 *
 * - a rejection inside the window is retried until the wire lands, and the
 *   retry repeats the call verbatim;
 * - exhausting the budget is reported as `CONNECTOR_ERROR` carrying the attempt
 *   count and the elapsed time, and **no attempt starts at or after the
 *   budget** (the invariant that keeps a wire action inside the daemon's 30 s
 *   action timeout);
 * - only the pinned rejection is retried: a parameter error never reaches the
 *   host at all, and a foreign host failure keeps its own answer after exactly
 *   one attempt.
 *
 * The host here is deliberately tiny (only `sch_PrimitiveWire`, no page guard):
 * this file is about the retry, not about placement, so it drives one action.
 *
 * One test walks the budget on `node:test`'s mock timers — the real clock would
 * make it a 10 s test. Node prints an `ExperimentalWarning` for that API: it is
 * expected here, and the test that runs on the real clock covers the production
 * timers, so nothing depends on the mock beyond that one case.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { createFacade } from '../dist/esm/facade.mjs';
import * as connector from '../dist/esm/index.mjs';

/** Milliseconds the retry waits between attempts — mirrors the production constant. */
const RETRY_DELAY_MS = 500;
/** The production budget, restated so the invariant below is checkable. */
const RETRY_BUDGET_MS = 10_000;

/**
 * A host carrying just enough of the editor surface to place a wire.
 *
 * `failures` is how many leading `create` calls are rejected; `rejection` is
 * what they throw, so a test can plant a shape the connector must *not* retry.
 */
function edaHost({ failures = 0, rejection = () => new Error('create failed!') } = {}) {
  const calls = { wire: [] };
  let nextId = 1;

  const host = {
    sys_WebSocket: {
      register(_id, _uri, onMessage) {
        host.__onMessage = onMessage;
      },
      send(_id, data) {
        host.__sent = host.__sent ?? [];
        host.__sent.push(JSON.parse(data));
      },
      close() {},
    },
    sys_Log: { add() {} },

    sch_PrimitiveWire: {
      async create(points, net) {
        calls.wire.push({ points, net });
        if (calls.wire.length <= failures) throw rejection();
        return { getState_PrimitiveId: () => `wire-${nextId++}` };
      },
    },

    __calls: calls,
  };
  return host;
}

/** One connected session against a host, with the request/response plumbing. */
function withEda(t, host) {
  connector.__setFacadeForTests(createFacade(host));
  t.after(() => {
    connector.deactivate();
    connector.__setFacadeForTests(undefined);
  });
}

/** Wait for a predicate by polling — never a fixed sleep (Windows clamps timers). */
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
  void host.__onMessage({ data: JSON.stringify({ id, action, params }) });
  assert.ok(
    await waitFor(() => (host.__sent ?? []).some((f) => f.id === id)),
    `no response frame for ${action}`,
  );
  return (host.__sent ?? []).find((f) => f.id === id);
}

/** Let a handler's pending microtasks drain. `setImmediate` is not mocked. */
function flush() {
  return new Promise((resolve) => setImmediate(resolve));
}

test('a wire rejected inside the lock window lands on a retry', async (t) => {
  // Two rejections then success, on the **real** clock: this is the path the
  // draw flow takes, and it must work without any help from a fake clock.
  const host = edaHost({ failures: 2 });
  withEda(t, host);
  await connector.activate();

  const points = [[0, 0], [100, 0], [100, 200]];
  const startedAt = Date.now();
  const frame = await call(host, 'sch.place_wire', { points, net: 'GND' });
  const elapsedMs = Date.now() - startedAt;

  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.ok(String(frame.data.uuid).startsWith('wire-'));
  assert.equal(host.__calls.wire.length, 3, 'two rejections, then the call that landed');
  // The retry repeats the call verbatim — same flattened points, same net.
  assert.deepEqual(host.__calls.wire[1], host.__calls.wire[0]);
  assert.deepEqual(host.__calls.wire[2], host.__calls.wire[0]);
  assert.deepEqual(host.__calls.wire[2].points, [0, 0, 100, 0, 100, 200]);
  assert.equal(host.__calls.wire[2].net, 'GND');
  // Two waits of the production delay actually happened.
  assert.ok(
    elapsedMs >= 2 * RETRY_DELAY_MS - 50,
    `two retries should take about ${2 * RETRY_DELAY_MS} ms, measured ${elapsedMs} ms`,
  );
});

test('exhausting the budget reports the attempts, the time, and stops on time', async (t) => {
  const host = edaHost({ failures: Infinity });
  withEda(t, host);
  await connector.activate();

  // Virtual time for this one only: the loop must walk its whole budget
  // (~20 attempts), which on the real clock would be a 10 s test.
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'] });

  const id = 'req-exhausted';
  void host.__onMessage({
    data: JSON.stringify({
      id,
      action: 'sch.place_wire',
      params: { points: [[0, 0], [10, 0]] },
    }),
  });
  for (let i = 0; i < 40; i += 1) {
    t.mock.timers.tick(RETRY_DELAY_MS);
    await flush();
    if ((host.__sent ?? []).some((f) => f.id === id)) break;
  }
  const frame = (host.__sent ?? []).find((f) => f.id === id);
  assert.ok(frame, 'the exhausted retry must still answer the caller');

  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'CONNECTOR_ERROR');
  const parsed = /rejected create (\d+) time\(s\) over (\d+) ms/.exec(frame.error.message);
  assert.ok(parsed, `the message must carry the counts: ${frame.error.message}`);
  const attempts = Number(parsed[1]);
  const elapsedMs = Number(parsed[2]);

  assert.equal(
    attempts,
    host.__calls.wire.length,
    'the attempt count must be the calls actually made',
  );
  assert.ok(attempts > 2, `a bounded retry, not one try: ${attempts} attempt(s)`);
  assert.deepEqual(frame.error.detail, {
    attempts,
    elapsedMs,
    retryDelayMs: RETRY_DELAY_MS,
    budgetMs: RETRY_BUDGET_MS,
  });
  // The invariant: no attempt starts at or after the budget, so the action
  // cannot outlast the daemon's 30 s slot.
  assert.ok(
    elapsedMs + RETRY_DELAY_MS <= RETRY_BUDGET_MS,
    `every attempt must start inside the ${RETRY_BUDGET_MS} ms budget, last started at `
      + `${elapsedMs} ms`,
  );
  assert.match(frame.error.message, /create failed!/, 'the last rejection is quoted');
});

test('a parameter error is not retried — it never reaches the host', async (t) => {
  const host = edaHost({ failures: Infinity });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.place_wire', { points: [[0, 0]] });

  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'BAD_REQUEST');
  assert.equal(
    host.__calls.wire.length,
    0,
    'a malformed request must be refused before the host call, so there is nothing to retry',
  );
});

test('a foreign host failure keeps its own answer after exactly one attempt', async (t) => {
  // Only the pinned `create failed!` shape may be retried. Anything else is
  // thrown on the spot: waiting cannot fix it, and swallowing it into a
  // CONNECTOR_ERROR would hide the real cause behind a retry budget.
  const host = edaHost({
    failures: Infinity,
    rejection: () => new Error('no editor context'),
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.place_wire', { points: [[0, 0], [10, 0]] });

  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'INTERNAL');
  assert.match(frame.error.message, /no editor context/);
  assert.equal(host.__calls.wire.length, 1, 'exactly one attempt, no retry');
});
