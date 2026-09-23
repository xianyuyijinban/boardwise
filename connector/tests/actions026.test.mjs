/**
 * 026 probe batch: `sys.worker_probe`, and the one assertion that is not negotiable.
 *
 * The action is temporary instrumentation, and the batch's own rule (026 §四) is
 * that **a failure must be reported as that failure**: no Worker, a CSP that
 * refuses `blob:` workers, a Worker that never answers. A probe that invents a
 * plausible `ready` payload when nothing answered would send the watchdog design
 * down a form that cannot work, and the whole point of probing before building is
 * to avoid exactly that. So the tests below pin both directions — the honest
 * failure, and the happy path reported verbatim from the Worker's own words.
 *
 * Node has no `Worker` (checked: `typeof Worker === 'undefined'`), which is
 * convenient: the *default* environment is the failure case, and the success case
 * injects a fake `Worker` class onto `globalThis` to play the part.
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

/** Run `fn` with `globalThis.Worker` replaced (or removed), then restore it. */
async function withWorker(fake, fn) {
  const had = Object.prototype.hasOwnProperty.call(globalThis, 'Worker');
  const previous = globalThis.Worker;
  if (fake === undefined) delete globalThis.Worker;
  else globalThis.Worker = fake;
  try {
    return await fn();
  } finally {
    if (had) globalThis.Worker = previous;
    else delete globalThis.Worker;
  }
}

/**
 * A stand-in Worker that plays a scripted role.
 *
 * `messages` is what it "says" on its own (the `ready` payload); every
 * `postMessage` from the page is answered with an `ack` and two ticks, which is
 * what the handler waits for before it terminates the worker.
 */
class FakeWorker {
  static instances = [];

  constructor(url, options) {
    this.url = url;
    this.options = options;
    this.terminated = false;
    this.received = [];
    FakeWorker.instances.push(this);
    if (FakeWorker.refuse) throw new Error(FakeWorker.refuse);
    if (!FakeWorker.silent) {
      setTimeout(() => this.onmessage?.({ data: FakeWorker.readyMessage }), 0);
    }
  }

  postMessage(data) {
    this.received.push(data);
    if (FakeWorker.silent) return;
    setTimeout(() => {
      this.onmessage?.({ data: { type: 'ack', echo: data, at: Date.now() } });
      this.onmessage?.({ data: { type: 'tick', ticks: 1, at: Date.now() } });
      this.onmessage?.({ data: { type: 'tick', ticks: 2, at: Date.now() + 200 } });
    }, 0);
  }

  terminate() {
    this.terminated = true;
  }
}

FakeWorker.readyMessage = {
  type: 'ready',
  at: Date.now(),
  probes: {
    self: 'object',
    window: 'undefined',
    eda: 'undefined',
    globalThisEda: 'undefined',
    globalThisKeys: ['self', 'postMessage', 'onmessage'],
    setInterval: 'function',
  },
};
FakeWorker.refuse = '';
FakeWorker.silent = false;

function resetFakeWorker() {
  FakeWorker.instances = [];
  FakeWorker.refuse = '';
  FakeWorker.silent = false;
}

test('the worker probe reports honestly when the runtime has no Worker', async (t) => {
  resetFakeWorker();
  t.after(resetFakeWorker);
  const { eda } = { eda: fakeEda() };
  const handlers = buildHandlers(eda);

  const report = await withWorker(undefined, () => handlers['sys.worker_probe']({ timeoutMs: 300 }));

  assert.equal(report.support.typeofWorker, 'undefined');
  assert.equal(report.blobUrl.ok, true, 'a blob URL is still creatable');
  assert.equal(report.construct.ok, false);
  assert.match(report.construct.error, /Worker is not a constructor|not defined|Worker/);
  assert.equal(report.messaging.delivered, false);
  assert.equal(report.messaging.ready, null, 'nothing may be invented for a worker that never ran');
  assert.equal(report.messaging.ack, null);
  assert.match(report.messaging.verdict, /no worker/);
  assert.equal(report.terminated, false);
});

test('a refused worker constructor is reported with the host error, not smoothed over', async (t) => {
  resetFakeWorker();
  FakeWorker.refuse = 'Refused to create a worker (CSP)';
  t.after(resetFakeWorker);
  const handlers = buildHandlers(fakeEda());

  const report = await withWorker(FakeWorker, () => handlers['sys.worker_probe']({ timeoutMs: 300 }));

  assert.equal(report.construct.ok, false);
  assert.match(report.construct.error, /CSP/, 'the host words travel');
  assert.equal(report.messaging.delivered, false);
  assert.match(report.messaging.verdict, /constructor refused/);
  assert.match(report.messaging.verdict, /CSP/);
});

test('a worker that never answers is a timeout, not an empty success', async (t) => {
  resetFakeWorker();
  FakeWorker.silent = true;
  t.after(resetFakeWorker);
  const handlers = buildHandlers(fakeEda());

  const report = await withWorker(FakeWorker, () => handlers['sys.worker_probe']({ timeoutMs: 250 }));

  assert.equal(report.construct.ok, true, 'it was constructed — that is all that was observed');
  assert.equal(report.messaging.delivered, false);
  assert.equal(report.messaging.ready, null);
  assert.match(report.messaging.verdict, /no message within 250 ms/);
  assert.equal(report.terminated, true, 'a silent worker is still terminated');
});

test('a worker that answers is reported verbatim, with the round trip and ticks', async (t) => {
  resetFakeWorker();
  t.after(resetFakeWorker);
  const handlers = buildHandlers(fakeEda());

  const report = await withWorker(FakeWorker, () => handlers['sys.worker_probe']({ timeoutMs: 2_000 }));

  assert.equal(report.construct.ok, true);
  assert.equal(report.construct.options, 'classic');
  assert.equal(report.messaging.delivered, true);
  // P2's answer is the worker's own `typeof eda`, carried through unchanged.
  assert.equal(report.messaging.ready.eda, 'undefined');
  assert.equal(report.messaging.ready.window, 'undefined');
  assert.deepEqual(report.messaging.ready.globalThisKeys, ['self', 'postMessage', 'onmessage']);
  assert.ok(report.messaging.ack, 'the page→worker→page round trip happened');
  assert.equal(report.messaging.roundTripMs >= 0, true);
  assert.equal(report.messaging.ticks, 2);
  assert.equal(report.messaging.tickIntervalsMs.length, 1);
  assert.equal(report.messaging.verdict, 'worker-ready-and-round-tripped');
  assert.equal(report.terminated, true);
  assert.equal(FakeWorker.instances[0].terminated, true);
  assert.deepEqual(FakeWorker.instances[0].received[0].type, 'ping');
});

test('a worker that reports a visible eda is believed (that is form B\'s ticket)', async (t) => {
  resetFakeWorker();
  const original = FakeWorker.readyMessage;
  FakeWorker.readyMessage = {
    ...original,
    probes: { ...original.probes, eda: 'object', globalThisEda: 'object' },
  };
  t.after(() => {
    FakeWorker.readyMessage = original;
    resetFakeWorker();
  });
  const handlers = buildHandlers(fakeEda());

  const report = await withWorker(FakeWorker, () => handlers['sys.worker_probe']({ timeoutMs: 2_000 }));

  assert.equal(report.messaging.ready.eda, 'object');
  assert.equal(report.messaging.ready.globalThisEda, 'object');
});

test('the page timer logs real intervals and reports the distribution', async (t) => {
  t.after(async () => {
    await buildHandlers(fakeEda())['sys.worker_probe']({ mode: 'pageTimer', op: 'stop' });
  });
  const handlers = buildHandlers(fakeEda());

  const started = await handlers['sys.worker_probe']({ mode: 'pageTimer', op: 'start', intervalMs: 50 });
  assert.equal(started.op, 'start');
  assert.equal(started.running, true);
  assert.equal(started.intervalMs, 50);
  await new Promise((resolve) => setTimeout(resolve, 260));

  const read = await handlers['sys.worker_probe']({ mode: 'pageTimer', op: 'read' });
  assert.ok(read.count >= 3, `expected a few ticks, got ${read.count}`);
  assert.equal(read.intervalsMs.length, read.count - 1);
  assert.ok(read.minMs >= 20, `min interval ${read.minMs} looks impossible`);
  assert.ok(read.maxMs >= read.minMs);
  assert.equal(typeof read.medianMs, 'number');
  // A frozen window shows up here, not in the mean.
  assert.deepEqual(Object.keys(read.gaps), ['over2s', 'over10s', 'over60s']);

  const stopped = await handlers['sys.worker_probe']({ mode: 'pageTimer', op: 'stop' });
  assert.equal(stopped.running, false);
  assert.equal(stopped.count, read.count, 'stopping keeps what was measured');
});

test('the page timer refuses an unknown op', async () => {
  const handlers = buildHandlers(fakeEda());
  await assert.rejects(
    () => handlers['sys.worker_probe']({ mode: 'pageTimer', op: 'dance' }),
    (error) => {
      assert.equal(error.code, 'BAD_REQUEST');
      assert.match(error.message, /start \| read \| stop/);
      return true;
    },
  );
});

test('the status mode reads the About box counters off the shared runtime', async () => {
  const published = {
    getStatus: () => ({
      state: 'connected',
      moduleBootstrapObserved: true,
      activateObserved: false,
      evaluations: 3,
      bootstrapAt: '2026-09-23T14:00:00.000Z',
    }),
  };
  const handlers = buildHandlers(fakeEda({ __boardwiseTransportRuntime: published }));

  const report = await handlers['sys.worker_probe']({ mode: 'status' });

  assert.equal(report.present, true);
  assert.equal(report.readStatus, true);
  assert.equal(report.moduleBootstrapObserved, true);
  assert.equal(report.activateObserved, false);
  assert.equal(report.evaluations, 3);
  assert.equal(report.status.state, 'connected');
});

test('the status mode says "not published" instead of inventing counters', async () => {
  const handlers = buildHandlers(fakeEda());

  const report = await handlers['sys.worker_probe']({ mode: 'status' });

  assert.equal(report.present, false);
  assert.equal(report.moduleBootstrapObserved, undefined, 'no fabricated false');
  assert.equal(report.evaluations, undefined);
  assert.match(String(report.note), /not on `eda`/);
});

test('a bad mode is a refusal, not a silent fallback to the worker probe', async () => {
  const handlers = buildHandlers(fakeEda());
  await assert.rejects(() => handlers['sys.worker_probe']({ mode: 'nonsense' }), (error) => {
    assert.equal(error.code, 'BAD_REQUEST');
    assert.match(error.message, /worker \| pageTimer \| workerTimer \| hostTimer \| status/);
    return true;
  });
});

test('a live worker timer is kept across calls and reports its own intervals', async (t) => {
  resetFakeWorker();
  t.after(resetFakeWorker);
  const handlers = buildHandlers(fakeEda());

  await withWorker(FakeWorker, async () => {
    const started = await handlers['sys.worker_probe']({
      mode: 'workerTimer', op: 'start', intervalMs: 50,
    });
    assert.equal(started.running, true, 'the worker is kept alive between calls');
    assert.equal(started.intervalMs, 50);
    assert.equal(FakeWorker.instances.length, 1);

    await new Promise((resolve) => setTimeout(resolve, 260));
    const read = await handlers['sys.worker_probe']({ mode: 'workerTimer', op: 'read' });
    // The fake answers one `start` with two ticks (it is not a real clock); what
    // matters here is that the worker stayed alive across calls and its timestamps
    // were carried through.
    assert.ok(read.count >= 2, `expected ticks, got ${read.count}`);
    assert.equal(read.intervalsMs.length, read.count - 1);
    assert.equal(read.running, true, 'still alive after a read');

    const stopped = await handlers['sys.worker_probe']({ mode: 'workerTimer', op: 'stop' });
    assert.equal(stopped.stopped, true);
    assert.equal(stopped.running, false);
    assert.equal(FakeWorker.instances[0].terminated, true);
    assert.equal(stopped.count, read.count, 'stopping keeps what was measured');
  });
});

test('a worker timer that cannot start says so instead of reporting a running one', async (t) => {
  resetFakeWorker();
  t.after(resetFakeWorker);
  const handlers = buildHandlers(fakeEda());

  const report = await withWorker(undefined, () =>
    handlers['sys.worker_probe']({ mode: 'workerTimer', op: 'start', intervalMs: 50 }));

  assert.equal(report.running, false);
  assert.match(String(report.error), /Worker|constructor|not defined/);
  assert.equal(report.count, 0, 'no ticks may be invented for a worker that never ran');
});

test('the host timer mode reports the API surface it found and refuses honestly', async () => {
  const handlers = buildHandlers(fakeEda());  // no sys_Timer on this fake

  const report = await handlers['sys.worker_probe']({ mode: 'hostTimer', op: 'start' });

  assert.equal(report.running, false);
  assert.match(String(report.error), /sys_Timer is not an object/);
  assert.equal(report.facts.setIntervalTimer, 'namespace-absent');
  assert.equal(report.count, 0, 'no ticks may be invented for a timer that was never set');
});

test('the host timer mode times the host callbacks and carries their arguments', async (t) => {
  const calls = [];
  const timerNs = {
    setIntervalTimer: (id, timeout, callFn, ...args) => {
      calls.push({ id, timeout, args });
      const handle = setInterval(() => callFn(...args), 40);
      timerNs.handles.set(id, handle);
      return true;
    },
    clearIntervalTimer: (id) => {
      clearInterval(timerNs.handles.get(id));
      timerNs.handles.delete(id);
      return true;
    },
    handles: new Map(),
  };
  t.after(() => {
    for (const handle of timerNs.handles.values()) clearInterval(handle);
  });
  const handlers = buildHandlers(fakeEda({ sys_Timer: timerNs }));

  const started = await handlers['sys.worker_probe']({
    mode: 'hostTimer', op: 'start', intervalMs: 50, id: 'unit-probe',
  });
  assert.equal(started.running, true);
  assert.equal(started.setterReturned, true);
  assert.equal(started.timerId, 'unit-probe');
  assert.equal(started.facts.setIntervalTimer, 'function/3', 'declared arity is reported');

  await new Promise((resolve) => setTimeout(resolve, 200));
  const read = await handlers['sys.worker_probe']({ mode: 'hostTimer', op: 'read' });
  assert.ok(read.count >= 2, `expected host callbacks, got ${read.count}`);
  assert.equal(read.intervalsMs.length, read.count - 1);
  assert.deepEqual(read.callbackArgs, ['probe-arg', 42], 'the ...args pass-through is measured');
  assert.deepEqual(calls[0].args, ['probe-arg', 42], 'the extra args reach the host setter');

  const stopped = await handlers['sys.worker_probe']({ mode: 'hostTimer', op: 'stop' });
  assert.equal(stopped.cleared, true);
  assert.equal(timerNs.handles.size, 0);
});

test('a host timer the host refuses to set is reported as not running', async () => {
  const handlers = buildHandlers(fakeEda({
    sys_Timer: { setIntervalTimer: () => false, clearIntervalTimer: () => true },
  }));

  const report = await handlers['sys.worker_probe']({ mode: 'hostTimer', op: 'start' });

  assert.equal(report.running, false);
  assert.equal(report.setterReturned, false);
  assert.match(String(report.error), /answered false/);
});
