/**
 * 026b: `sys.connector_status` (promoted), and what is left of `sys.worker_probe`.
 *
 * Two actions, one theme: **a reading, never a guess.** `sys.connector_status`
 * answers whether this editor runtime ever evaluated the bundle and whether it
 * dispatched `activate()` — the two facts that make an inert extension
 * distinguishable from an absent one (issue #4), and which no daemon-side
 * surface can see. `sys.worker_probe` is down to the single P6 question — can a
 * native `WebSocket` reach the daemon from the page, and from a Worker? — and
 * its honour rules are the probe batch's, unchanged (026 §四): no Worker, a CSP
 * refusal, a socket that opened and said nothing are each reported as exactly
 * that.
 *
 * Everything here is offline. Node has no `Worker` (so the default environment
 * is itself the "no Worker" case), no daemon is contacted (`WebSocket` is
 * injected), and the Worker's own program is executed in-process with a stand-in
 * `self`, so the interpolated probe source is *run*, not merely parsed.
 *
 * The retired modes (`worker`, `pageTimer`, `workerTimer`, `hostTimer`,
 * `status`) are asserted to be gone rather than merely undocumented: a caller
 * still holding the old invocation must be told what replaced it.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { buildHandlers, nativeWsProbeWorkerSource } from '../dist/esm/actions.mjs';

function fakeEda(overrides = {}) {
  return {
    dmt_SelectControl: {
      getCurrentDocumentInfo: async () => ({ uuid: 'page-1', name: 'P1', documentType: 1, tabId: 't1' }),
    },
    ...overrides,
  };
}

const handlers = (eda = fakeEda()) => buildHandlers(eda);
const probe = async (params, eda) => handlers(eda)['sys.worker_probe'](params);
const status = async (eda) => handlers(eda)['sys.connector_status']({});

// --------------------------------------------------------------------------
// sys.connector_status — the promoted diagnostic
// --------------------------------------------------------------------------

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
      watchdog: { state: 'running', wakes: 2, activityPosts: 11, checkIntervalMs: 15000, activityTimeoutMs: 45000 },
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
    activityTimeoutMs: 45000,
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
  // detached call would answer about nothing. The probe calls it as a method.
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

// --------------------------------------------------------------------------
// sys.worker_probe — the retired modes
// --------------------------------------------------------------------------

for (const retired of ['worker', 'pageTimer', 'workerTimer', 'hostTimer', 'status']) {
  test(`the retired probe mode "${retired}" is refused, and named as retired`, async () => {
    await assert.rejects(
      () => probe({ mode: retired }),
      (error) => {
        assert.equal(error.code, 'BAD_REQUEST');
        assert.match(String(error.message), /nativeWs/);
        assert.match(String(error.message), /retired in 026b/);
        return true;
      },
    );
  });
}

// --------------------------------------------------------------------------
// P6 — the native WebSocket question, page half
// --------------------------------------------------------------------------

/** Run `fn` with `globalThis.WebSocket` replaced by a scripted fake. */
async function withWebSocket(fake, fn) {
  const had = Object.prototype.hasOwnProperty.call(globalThis, 'WebSocket');
  const previous = globalThis.WebSocket;
  globalThis.WebSocket = fake;
  try {
    return await fn();
  } finally {
    if (had) globalThis.WebSocket = previous;
    else delete globalThis.WebSocket;
  }
}

/**
 * A stand-in native WebSocket, scripted per test.
 *
 * `behaviour` is one of: `'opens-and-speaks'` (the daemon's banner), `'opens'`
 * (open and nothing else), `'errors'`, or `'throws'` (a CSP refusal, which is
 * what a blocked `connect-src` looks like).
 */
class FakeWebSocket {
  static behaviour = 'opens-and-speaks';
  static instances = [];

  constructor(url) {
    this.url = url;
    this.closed = [];
    FakeWebSocket.instances.push(this);
    if (FakeWebSocket.behaviour === 'throws') {
      throw new Error('Refused to connect: violates the document CSP');
    }
    setTimeout(() => {
      if (FakeWebSocket.behaviour === 'errors') {
        this.onerror?.({ message: 'connection refused' });
        return;
      }
      this.onopen?.({});
      if (FakeWebSocket.behaviour === 'opens-and-speaks') {
        this.onmessage?.({ data: JSON.stringify({ event: 'banner', data: { expect: 'hello' } }) });
      }
    }, 0);
  }

  close(code, reason) {
    this.closed.push([code, reason]);
    this.onclose?.({ code, reason });
  }
}

function resetFakeWebSocket(behaviour = 'opens-and-speaks') {
  FakeWebSocket.behaviour = behaviour;
  FakeWebSocket.instances = [];
}

test('the P6 probe reports the daemon banner verbatim when the page can connect', async () => {
  resetFakeWebSocket('opens-and-speaks');
  const report = await withWebSocket(FakeWebSocket, () => probe({ mode: 'nativeWs', timeoutMs: 2000 }));

  assert.equal(report.mode, 'nativeWs');
  assert.equal(report.url, 'ws://127.0.0.1:61190/eda');
  assert.equal(report.page.construct.ok, true);
  assert.equal(report.page.opened, true);
  assert.equal(report.page.messages, 1);
  assert.match(report.page.sample[0], /"event":"banner"/);
  assert.equal(report.page.verdict, 'opened, and the daemon spoke first');
  assert.deepEqual(FakeWebSocket.instances[0].closed, [[1000, 'boardwise probe done']]);
});

test('a socket that opens and says nothing is not reported as a connection', async () => {
  // "opened, silent" and "could not connect" are different readings, and a
  // probe that merged them would send the design down a route that does not
  // work — the same trap as P1's empty success.
  resetFakeWebSocket('opens');
  const report = await withWebSocket(FakeWebSocket, () =>
    probe({ mode: 'nativeWs', timeoutMs: 120 }));

  assert.equal(report.page.opened, true);
  assert.equal(report.page.messages, 0);
  assert.equal(report.page.verdict, 'opened, silent');
});

test('a constructor that throws is reported with the host\'s own refusal', async () => {
  resetFakeWebSocket('throws');
  const report = await withWebSocket(FakeWebSocket, () => probe({ mode: 'nativeWs', timeoutMs: 200 }));

  assert.equal(report.page.construct.ok, false);
  assert.match(String(report.page.construct.error), /violates the document CSP/);
  assert.equal(report.page.opened, false);
  assert.equal(report.page.verdict, 'the WebSocket constructor threw');
});

test('an error with no open is reported as never opened, with the events that arrived', async () => {
  resetFakeWebSocket('errors');
  const report = await withWebSocket(FakeWebSocket, () => probe({ mode: 'nativeWs', timeoutMs: 200 }));

  assert.equal(report.page.opened, false);
  assert.equal(report.page.verdict, 'never opened');
  assert.ok(report.page.events.some((event) => event.type === 'error'), JSON.stringify(report.page.events));
});

test('the page half never waits longer than the caller allowed', async () => {
  resetFakeWebSocket('opens'); // opens, never answers
  const started = Date.now();
  const report = await withWebSocket(FakeWebSocket, () =>
    probe({ mode: 'nativeWs', timeoutMs: 150 }));
  const elapsed = Date.now() - started;
  assert.ok(elapsed < 1500, `the probe must not hang: ${elapsed} ms`);
  assert.ok(report.page.elapsedMs >= 100, 'and it must actually have waited for the answer');
});

// --------------------------------------------------------------------------
// P6 — the Worker half
// --------------------------------------------------------------------------

test('the Worker half reports honestly when this host has no Worker at all', async () => {
  resetFakeWebSocket();
  const report = await withWebSocket(FakeWebSocket, () => probe({ mode: 'nativeWs', timeoutMs: 200 }));

  // Node's shape, and the shape of an editor that refused the constructor.
  assert.equal(report.worker.supported, false);
  assert.match(String(report.worker.error), /Worker is not a constructor|no Worker/);
  assert.match(String(report.worker.verdict), /unanswered by this host/);
  assert.match(String(report.verdict), /a Worker did not/);
});

test('the Worker half passes the Worker\'s own report through, unembellished', async () => {
  resetFakeWebSocket();
  class ReportingWorker {
    constructor(url) {
      this.url = url;
      this.posted = [];
      this.terminated = false;
      setTimeout(() => this.onmessage?.({
        data: {
          type: 'nativeWs',
          report: { construct: { ok: true }, opened: true, messages: 1, verdict: 'opened, and the daemon spoke first' },
        },
      }), 0);
    }

    postMessage(message) {
      this.posted.push(message);
    }

    terminate() {
      this.terminated = true;
    }
  }

  const had = Object.prototype.hasOwnProperty.call(globalThis, 'Worker');
  const previous = globalThis.Worker;
  globalThis.Worker = ReportingWorker;
  try {
    const report = await withWebSocket(FakeWebSocket, () =>
      probe({ mode: 'nativeWs', timeoutMs: 300 }));
    assert.equal(report.worker.supported, true);
    assert.equal(report.worker.verdict, 'opened, and the daemon spoke first');
    assert.match(String(report.verdict), /form B′ is at least possible/);
  } finally {
    if (had) globalThis.Worker = previous;
    else delete globalThis.Worker;
  }
});

test('a Worker that never answers is a timeout, not an empty success', async () => {
  resetFakeWebSocket();
  class SilentWorker {
    constructor() {
      this.terminated = false;
    }

    postMessage() {}

    terminate() {
      this.terminated = true;
    }
  }

  const had = Object.prototype.hasOwnProperty.call(globalThis, 'Worker');
  const previous = globalThis.Worker;
  globalThis.Worker = SilentWorker;
  try {
    const report = await withWebSocket(FakeWebSocket, () => probe({ mode: 'nativeWs', timeoutMs: 120 }));
    assert.equal(report.worker.timedOut, true);
    assert.match(String(report.worker.error), /no answer from the Worker/);
  } finally {
    if (had) globalThis.Worker = previous;
    else delete globalThis.Worker;
  }
});

test('the Worker half terminates its Worker and revokes its blob URL either way', async () => {
  resetFakeWebSocket();
  const revoked = [];
  const realRevoke = URL.revokeObjectURL;
  URL.revokeObjectURL = (url) => revoked.push(url);
  let worker = null;
  class CapturingWorker {
    constructor(url) {
      this.url = url;
      this.terminated = false;
      worker = this;
    }

    postMessage() {}

    terminate() {
      this.terminated = true;
    }
  }

  const had = Object.prototype.hasOwnProperty.call(globalThis, 'Worker');
  const previous = globalThis.Worker;
  globalThis.Worker = CapturingWorker;
  try {
    await withWebSocket(FakeWebSocket, () => probe({ mode: 'nativeWs', timeoutMs: 100 }));
    assert.equal(worker.terminated, true, 'a probe that leaks a thread is a bug of its own');
    assert.equal(revoked.length, 1, 'and its blob URL is its own leak to clean up');
  } finally {
    URL.revokeObjectURL = realRevoke;
    if (had) globalThis.Worker = previous;
    else delete globalThis.Worker;
  }
});

test('the Worker program is the page\'s own probe code, and it parses', async () => {
  // The one real risk of interpolating a function into a string: a change that
  // breaks the worker copy while the page half keeps working. Reading the text
  // is the only way to see it from here.
  const source = nativeWsProbeWorkerSource();
  assert.doesNotThrow(() => new Function('self', source), 'the worker source must parse');
  assert.match(source, /function nativeWebSocketProbe/, 'the page\'s own function, interpolated');
  assert.match(source, /new WebSocket\(url\)/, 'the worker makes its own socket');
  // No `eda` in the worker: P2 measured it is `undefined` there, and forwarding
  // editor calls into a Worker is forbidden by 026b §五.
  assert.equal(/\beda\b/.test(source), false, 'the worker must not reach for the editor API');
});

test('the Worker program actually opens a socket and reports it, end to end', async () => {
  // Not a parse check: the interpolated program is executed with the real
  // `setTimeout`/`Date` and a stand-in `self`, driving the same fake WebSocket
  // the page half used. This is the closest an offline suite gets to "a Worker
  // ran the probe".
  resetFakeWebSocket('opens-and-speaks');
  const posted = [];
  let onmessage = null;
  const fakeSelf = {
    postMessage: (message) => posted.push(message),
    set onmessage(handler) {
      onmessage = handler;
    },
    get onmessage() {
      return onmessage;
    },
  };

  await withWebSocket(FakeWebSocket, async () => {
    new Function('self', nativeWsProbeWorkerSource())(fakeSelf);
    assert.equal(typeof onmessage, 'function', 'the program installs its own message handler');
    onmessage({ data: { type: 'probe', url: 'ws://127.0.0.1:61190/eda', timeoutMs: 1000 } });
    const deadline = Date.now() + 2000;
    while (posted.length === 0 && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
  });

  assert.equal(posted.length, 1, `the worker must answer once: ${JSON.stringify(posted)}`);
  assert.equal(posted[0].type, 'nativeWs');
  assert.equal(posted[0].report.opened, true);
  assert.equal(posted[0].report.messages, 1);
  assert.equal(posted[0].report.verdict, 'opened, and the daemon spoke first');
  assert.equal(FakeWebSocket.instances.length, 1, 'one socket, opened inside the worker program');
});

test('the worker copy is the page\'s probe, not a second implementation', async () => {
  // The page half and the worker half must not drift into two similar
  // implementations: the interpolation is the guarantee. Both strings below
  // come from inside `nativeWebSocketProbe`'s own body, and the end-to-end test
  // above is the behaviour that follows from it.
  const source = nativeWsProbeWorkerSource();
  assert.match(source, /boardwise probe done/);
  assert.match(source, /opened, and the daemon spoke first/);
  assert.equal(source.includes('makeSocket(url)'), true, 'the socket comes in as a parameter');
});
