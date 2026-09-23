/**
 * 026b: the background watchdog — the alarm, the wiring, and the one-per-runtime rule.
 *
 * What is under test, and why it is in four parts. The probe batch measured that
 * a background window's page timers are throttled to about one tick a minute
 * (and in the frozen state stop entirely) while a Worker's own timers keep
 * running (026 P3). This batch turns that into product behaviour, and the
 * behaviour has four layers, each of which can fail on its own:
 *
 * 1. **The Worker's program** (`buildWatchdogSource`) — a clock, a silence
 *    counter, and one wake per check. Executed here for real, in-process, with a
 *    stand-in `self` and genuine timers: the program is a string, so nothing
 *    else can check it.
 * 2. **The page half** (`Watchdog`) — activity out, wakes in, and the honest
 *    failure when the host refuses a Worker at all.
 * 3. **The transport's reaction** (`Transport.wake`) — what a wake actually
 *    does, which differs by state: connect now, ping now, reconnect now, or
 *    nothing at all.
 * 4. **The wiring** (`index.ts`) — one alarm per editor runtime, never one per
 *    evaluation of the bundle (the editor re-evaluates it on every menu click),
 *    terminated with the connection, and reported in `About…`.
 *
 * Node has no `Worker` constructor, so every "the alarm runs" test injects one;
 * the tests that do not are the degradation tests, and they are the default
 * environment rather than a contrivance.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { createFacade } from '../dist/esm/facade.mjs';
import * as connector from '../dist/esm/index.mjs';
import { Transport } from '../dist/esm/transport.mjs';
import {
  Watchdog,
  buildWatchdogSource,
  WATCHDOG_ACTIVITY_TIMEOUT_MS,
  WATCHDOG_CHECK_INTERVAL_MS,
} from '../dist/esm/watchdog.mjs';

/** Poll until `predicate` holds; a fixed sleep guesses at someone else's clock. */
async function waitFor(predicate, timeout = 2000, interval = 5) {
  const deadline = Date.now() + timeout;
  for (;;) {
    if (await predicate()) return true;
    if (Date.now() > deadline) return false;
    await new Promise((resolve) => setTimeout(resolve, interval));
  }
}

// --------------------------------------------------------------------------
// 1. The Worker's own program
// --------------------------------------------------------------------------

/**
 * Run the Worker program in-process.
 *
 * The program is a string (it has to be: the extension ships as one bundle, so
 * there is no separate Worker file — 026b §五). `new Function('self', source)`
 * executes it with the real `setTimeout`/`setInterval`/`Date` from this realm
 * and a stand-in `self`, which is enough to observe the only thing it does:
 * post a wake when nobody has said anything for too long.
 */
function runWorkerProgram(source) {
  const posted = [];
  let onmessage = null;
  const self = {
    postMessage: (message) => posted.push(message),
    set onmessage(handler) {
      onmessage = handler;
    },
    get onmessage() {
      return onmessage;
    },
  };
  new Function('self', source)(self);
  return {
    posted,
    /** Put one message on the worker's own message queue. */
    send: (data) => onmessage?.({ data }),
    wakes: () => posted.filter((message) => message.type === 'wake').length,
  };
}

test('the watchdog program is a parseable classic script with its tunables baked in', () => {
  const source = buildWatchdogSource({ checkIntervalMs: 20, activityTimeoutMs: 40 });
  assert.doesNotThrow(() => new Function('self', source));
  assert.match(source, /CHECK_INTERVAL_MS = 20/);
  assert.match(source, /ACTIVITY_TIMEOUT_MS = 40/);
  // P2 measured that `eda` is invisible inside a Worker; forwarding editor calls
  // into one is forbidden outright (026b §五), so this is a source rule too.
  assert.equal(/\beda\b/.test(source), false, 'the worker must not reach for the editor API');
});

test('the alarm fires only after the silence threshold, and repeats every check', async () => {
  const worker = runWorkerProgram(buildWatchdogSource({ checkIntervalMs: 10, activityTimeoutMs: 40 }));

  assert.equal(worker.posted[0].type, 'ready', 'it announces itself first');
  assert.equal(worker.wakes(), 0, 'nothing to report while the page is talking');
  await new Promise((resolve) => setTimeout(resolve, 25));
  assert.equal(worker.wakes(), 0, '25 ms of silence is not 40 ms');

  assert.ok(await waitFor(() => worker.wakes() > 0), 'the alarm must fire on its own');
  const first = worker.posted.find((message) => message.type === 'wake');
  assert.ok(first.silenceMs >= 40, `the wake must report a real silence: ${JSON.stringify(first)}`);

  // One per check, not one per silence: a frozen page swallows messages and has
  // to find one waiting the moment it runs again (026b §2.2).
  await waitFor(() => worker.wakes() >= 2);
  assert.ok(worker.wakes() >= 2, 'and it keeps firing until the page answers');

  worker.send({ type: 'activity' });
  const settled = worker.wakes();
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(worker.wakes(), settled, 'activity stops the alarm repeating');

  // Take the program's own clock down: this realm's interval would otherwise
  // keep the test process alive forever.
  worker.send({ type: 'stop' });
});

test('a stop message takes the worker\'s clock down with it', async () => {
  const worker = runWorkerProgram(buildWatchdogSource({ checkIntervalMs: 5, activityTimeoutMs: 10 }));
  worker.send({ type: 'stop' });
  assert.equal(worker.posted.at(-1).type, 'stopped');
  const settled = worker.posted.length;
  await new Promise((resolve) => setTimeout(resolve, 40));
  assert.equal(worker.posted.length, settled, 'a stopped worker says nothing more');
});

test('the shipped thresholds are the policy the docs state', () => {
  // 45 s is three heartbeat intervals (5 s) times three, and the observed
  // throttled period is ~60 s, so the alarm sits inside one throttled cycle.
  assert.equal(WATCHDOG_CHECK_INTERVAL_MS, 15_000);
  assert.equal(WATCHDOG_ACTIVITY_TIMEOUT_MS, 45_000);
  assert.match(buildWatchdogSource({
    checkIntervalMs: WATCHDOG_CHECK_INTERVAL_MS,
    activityTimeoutMs: WATCHDOG_ACTIVITY_TIMEOUT_MS,
  }), /ACTIVITY_TIMEOUT_MS = 45000/);
});

// --------------------------------------------------------------------------
// 2. The page half
// --------------------------------------------------------------------------

/** A stand-in Worker: records what the page sent it, and can be made to speak. */
class FakeWorker {
  static instances = [];
  static refuse = '';

  constructor(url) {
    this.url = url;
    this.posted = [];
    this.terminated = false;
    FakeWorker.instances.push(this);
    if (FakeWorker.refuse) throw new Error(FakeWorker.refuse);
  }

  postMessage(message) {
    this.posted.push(message);
  }

  terminate() {
    this.terminated = true;
  }

  /** Play a `wake` from the worker side. */
  wake(info = {}) {
    this.onmessage?.({ data: { type: 'wake', wakes: 1, silenceMs: 46_000, ...info } });
  }
}

function resetFakeWorker(refuse = '') {
  FakeWorker.instances = [];
  FakeWorker.refuse = refuse;
}

const sleepingOnWake = () => {};
const noLog = () => {};

function makeWatchdog(overrides = {}) {
  const wakes = [];
  const logs = [];
  const watchdog = new Watchdog({
    onWake: (info) => wakes.push(info),
    onLog: (message) => logs.push(message),
    createWorker: (url) => new FakeWorker(url),
    checkIntervalMs: 20,
    activityTimeoutMs: 40,
    ...overrides,
  });
  return { watchdog, wakes, logs };
}

test('a running alarm reports activity as fire-and-forget messages', () => {
  resetFakeWorker();
  const { watchdog, logs } = makeWatchdog();

  assert.equal(watchdog.start(), true);
  assert.equal(watchdog.isRunning(), true);
  const worker = FakeWorker.instances[0];
  assert.match(worker.url, /^blob:/, 'the Worker is built from an inline blob (one-file distribution)');

  watchdog.noteActivity();
  watchdog.noteActivity();
  assert.deepEqual(worker.posted.map((message) => message.type), ['activity', 'activity']);
  assert.equal(watchdog.status().activityPosts, 2);
  assert.equal(watchdog.status().state, 'running');
  assert.ok(logs.some((line) => /watchdog: running/.test(line)), logs.join('\n'));

  watchdog.stop();
});

test('a wake reaches the caller, is counted, and is logged', () => {
  resetFakeWorker();
  const { watchdog, wakes, logs } = makeWatchdog();
  watchdog.start();

  FakeWorker.instances[0].wake({ wakes: 1, silenceMs: 51_234 });

  assert.deepEqual(wakes, [{ wakes: 1, silenceMs: 51_234 }]);
  assert.equal(watchdog.status().wakes, 1);
  assert.ok(typeof watchdog.status().lastWakeAt === 'number');
  assert.ok(logs.some((line) => /silent for 51234 ms/.test(line)), logs.join('\n'));

  watchdog.stop();
});

test('a wake handler that throws does not take the alarm down with it', () => {
  // The alarm is a safety net: a handler that throws must cost one wake, not the
  // mechanism that recovers the connection.
  resetFakeWorker();
  const logs = [];
  const watchdog = new Watchdog({
    onWake: () => {
      throw new Error('the transport exploded');
    },
    onLog: (message) => logs.push(message),
    createWorker: (url) => new FakeWorker(url),
  });
  watchdog.start();

  FakeWorker.instances[0].wake();
  assert.equal(watchdog.isRunning(), true);
  assert.ok(logs.some((line) => /the wake handler threw/.test(line)), logs.join('\n'));
  watchdog.stop();
});

test('a worker error is reported as unavailable rather than as a running alarm', () => {
  resetFakeWorker();
  const { watchdog } = makeWatchdog();
  watchdog.start();

  FakeWorker.instances[0].onerror?.({ message: 'the worker died' });

  assert.equal(watchdog.isRunning(), false);
  assert.equal(watchdog.status().state, 'unavailable');
  assert.match(String(watchdog.status().reason), /the worker died/);
});

test('stop() terminates the Worker and nothing is sent afterwards', () => {
  resetFakeWorker();
  const { watchdog } = makeWatchdog();
  watchdog.start();
  const worker = FakeWorker.instances[0];

  watchdog.stop();

  assert.equal(worker.terminated, true);
  assert.deepEqual(worker.posted.map((message) => message.type), ['stop'],
    'the stop request is the last thing it is told');
  assert.equal(worker.onmessage, null, 'and the page drops its own handler');

  const sent = worker.posted.length;
  watchdog.noteActivity(); // even a stray late call
  worker.wake(); // and a wake already in flight
  assert.equal(worker.posted.length, sent, 'nothing more is sent to it');
  assert.equal(watchdog.isRunning(), false);
  assert.equal(watchdog.status().state, 'stopped');
  // The dropped handler is what makes "a stopped transport sends nothing, ever"
  // true of the Worker too: an in-flight message cannot reach the caller.
  assert.equal(watchdog.status().wakes, 0);
});

test('a host with no Worker at all degrades to unavailable, with the reason', () => {
  resetFakeWorker();
  const logs = [];
  // No `createWorker` override: the default reads the ambient global, and Node
  // has no `Worker` — the same shape as an editor that refused the constructor.
  const watchdog = new Watchdog({ onWake: sleepingOnWake, onLog: (line) => logs.push(line) });

  assert.equal(watchdog.start(), false);
  assert.equal(watchdog.status().state, 'unavailable');
  assert.match(String(watchdog.status().reason), /no Worker constructor/);
  assert.ok(logs.some((line) => /watchdog: unavailable/.test(line)), logs.join('\n'));

  // Degraded, not broken: the page half stays callable and does nothing.
  watchdog.noteActivity();
  assert.equal(watchdog.status().activityPosts, 0, 'an unavailable alarm reports no activity');
  assert.equal(watchdog.isRunning(), false);
});

test('a constructor that throws (a CSP that blocks blob: workers) is the same honest failure', () => {
  resetFakeWorker('Refused to create a Worker: violates the document CSP');
  const { watchdog, logs } = makeWatchdog();

  assert.equal(watchdog.start(), false);
  assert.match(String(watchdog.status().reason), /violates the document CSP/);
  assert.ok(logs.some((line) => /runs without a background alarm/.test(line)), logs.join('\n'));
});

test('a blob URL that cannot be created is reported, not swallowed', () => {
  resetFakeWorker();
  const { watchdog } = makeWatchdog({
    createObjectUrl: () => {
      throw new Error('this host has no URL.createObjectURL');
    },
  });
  assert.equal(watchdog.start(), false);
  assert.match(String(watchdog.status().reason), /no URL.createObjectURL/);
});

test('the page half and the Worker program together: real silence, real wake', async (t) => {
  // The closest an offline suite gets to the machine: the Worker's *own* program
  // (real `setInterval`, real `Date`) is what the page half talks to, so this
  // test covers the two pieces as one mechanism rather than as two halves that
  // each pass on their own. Only the thread and the blob URL are stand-ins.
  const sources = [];
  const wakes = [];
  class RealtimeWorker {
    constructor(source) {
      this.program = runWorkerProgram(source);
      this.terminated = false;
      this.program.send({ type: 'activity' }); // the page has just started talking
      // Poll for what the program posts. It must keep polling through the gaps
      // (the first wake is a whole timeout away), and it must stop once the
      // worker is terminated and drained — this realm's timers are real, so a
      // chain that never ends keeps `node --test` alive.
      const forward = () => {
        const next = this.program.posted.shift();
        if (next) this.onmessage?.({ data: next });
        if (this.terminated && this.program.posted.length === 0) return;
        setTimeout(forward, 1);
      };
      setTimeout(forward, 1);
    }

    postMessage(message) {
      if (this.terminated) return;
      this.program.send(message);
    }

    terminate() {
      this.terminated = true;
      this.program.send({ type: 'stop' });
    }
  }

  const watchdog = new Watchdog({
    onWake: (info) => wakes.push(info),
    onLog: noLog,
    checkIntervalMs: 20,
    activityTimeoutMs: 400,
    createObjectUrl: (source) => {
      sources.push(source);
      return 'blob:boardwise-watchdog-test';
    },
    createWorker: () => new RealtimeWorker(sources.at(-1)),
  });
  t.after(() => watchdog.stop());

  assert.equal(watchdog.start(), true);
  assert.ok(await waitFor(() => wakes.length > 0, 2000), 'a silent page must be woken by the program itself');
  assert.ok(wakes[0].silenceMs >= 400, `the wake must carry the silence it measured: ${JSON.stringify(wakes[0])}`);

  // And the page answering resets the clock: the two windows below are well
  // inside the 400 ms threshold, so no *new* wake can be produced in either of
  // them — the first window is only there to absorb a wake that was already on
  // its way when the activity arrived.
  watchdog.noteActivity();
  await new Promise((resolve) => setTimeout(resolve, 150));
  const settled = wakes.length;
  await new Promise((resolve) => setTimeout(resolve, 150));
  assert.equal(wakes.length, settled, 'activity must silence the alarm');
});

// --------------------------------------------------------------------------
// 3. The transport's reaction to a wake
// --------------------------------------------------------------------------

class FakeSocket {
  constructor() {
    this.registered = [];
    this.sent = [];
    this.closed = [];
  }

  register(id, uri, onMessage, onConnected) {
    this.registered.push({ id, uri });
    this.onMessage = onMessage;
    this.onConnected = onConnected;
  }

  send(id, data) {
    this.sent.push({ id, frame: JSON.parse(data) });
  }

  close(id) {
    this.closed.push(id);
  }

  connect() {
    this.onConnected?.();
  }

  deliver(frame) {
    return this.onMessage?.({ data: JSON.stringify(frame) });
  }

  pings() {
    return this.sent.filter((entry) => entry.frame.action === 'ping');
  }
}

/** A socket whose first registrations are refused: a daemon that is not there yet. */
class FlakySocket extends FakeSocket {
  constructor() {
    super();
    this.refuse = true;
  }

  register(id, uri, onMessage, onConnected) {
    if (this.refuse) throw new Error('register refused');
    return super.register(id, uri, onMessage, onConnected);
  }
}

const BANNER = { event: 'banner', data: { server: 'boardwise', protocol: '1.0', expect: 'hello' } };

function makeTransport(socket, overrides = {}) {
  const activities = [];
  const logs = [];
  const transport = new Transport({
    url: 'ws://127.0.0.1:61190/eda',
    token: 'tok',
    socket,
    minBackoffMs: 5,
    maxBackoffMs: 20,
    heartbeatMs: 10,
    heartbeatMissLimit: 3,
    onRequest: async () => ({}),
    watchdog: { noteActivity: () => activities.push(Date.now()) },
    onLog: (message) => logs.push(message),
    ...overrides,
  });
  return { transport, activities, logs };
}

/**
 * A transport that is always stopped when the test ends.
 *
 * Registered as a cleanup rather than written at the bottom of the test body on
 * purpose: an assertion that fails first would otherwise leave the heartbeat
 * interval running, and a pending interval keeps `node --test` alive after every
 * test has reported — which is exactly how this suite hung once.
 */
function makeTransportWithCleanup(t, socket, overrides = {}) {
  const parts = makeTransport(socket, overrides);
  t.after(() => parts.transport.stop());
  return parts;
}

test('the transport reports activity on every sign of life it produces', async (t) => {
  const socket = new FakeSocket();
  const { transport, activities } = makeTransportWithCleanup(t, socket);

  await transport.start(); // a connect attempt
  const afterStart = activities.length;
  assert.ok(afterStart >= 1, 'the attempt itself is a sign of life');

  await socket.deliver(BANNER); // inbound traffic + the handshake going out
  assert.ok(activities.length > afterStart, 'inbound traffic is one too');

  await socket.deliver({ id: 'hello', ok: true, data: {} }); // handshake accepted
  const afterHello = activities.length;
  assert.ok(afterHello > afterStart);

  assert.ok(await waitFor(() => activities.length > afterHello), 'and the heartbeat keeps it fed');
});

test('a broken watchdog cannot break the connection', async (t) => {
  // The alarm is an observer. If it throws, liveness must be unaffected — that
  // is the whole reason every call into it is wrapped.
  const socket = new FakeSocket();
  const { transport } = makeTransportWithCleanup(t, socket, {
    watchdog: {
      noteActivity: () => {
        throw new Error('the alarm is broken');
      },
    },
  });

  await transport.start();
  await socket.deliver(BANNER);
  await socket.deliver({ id: 'hello', ok: true, data: {} });

  assert.equal(transport.getState(), 'connected', 'the handshake still completed');
});

test('a wake with nothing on the wire connects immediately, with the backoff reset', (t) => {
  const socket = new FakeSocket();
  const { transport, logs, activities } = makeTransportWithCleanup(t, socket);

  // Nothing started: the state is `idle` and no attempt exists.
  transport.wake('test');
  assert.equal(socket.registered.length, 1, 'a wake opens the socket without waiting');
  assert.ok(logs.some((line) => /backoff reset/.test(line)), logs.join('\n'));
  // The wake is a sign of life too: it must re-arm the alarm, or the alarm would
  // keep firing at a page that has just proved it is running.
  assert.ok(activities.length >= 1, 'the wake stamps activity before it acts');
});

test('a wake skips a pending backoff instead of waiting it out', async (t) => {
  const socket = new FlakySocket();
  // A ladder that would make the retry 5 s away — far longer than this test.
  const { transport } = makeTransportWithCleanup(t, socket, {
    minBackoffMs: 5000,
    maxBackoffMs: 60_000,
  });

  await transport.start();
  assert.equal(socket.registered.length, 0, 'the refused registration never reached the editor');
  assert.equal(transport.getState(), 'reconnecting', 'so a retry is scheduled, 5 s out');

  socket.refuse = false;
  transport.wake('test');

  // Synchronous: the wake must not wait for the ladder's timer to come round.
  assert.equal(
    socket.registered.length,
    1,
    'the wake connects now rather than after the 5 s the ladder wanted',
  );
});

test('a wake on a healthy connection does nothing but stamp activity', async (t) => {
  const socket = new FakeSocket();
  const { transport, logs, activities } = makeTransportWithCleanup(t, socket);
  await transport.start();
  await socket.deliver(BANNER);
  await socket.deliver({ id: 'hello', ok: true, data: {} });

  const pings = socket.pings().length;
  const registered = socket.registered.length;
  const seen = activities.length;
  transport.wake('test');

  assert.equal(transport.getState(), 'connected', 'nothing was torn down');
  assert.equal(socket.registered.length, registered, 'and nothing was re-registered');
  assert.equal(socket.pings().length, pings, 'no extra ping: the heartbeat is not overdue');
  assert.equal(activities.length, seen + 1, 'but the alarm is told the page is alive');
  assert.ok(logs.some((line) => /connected and answering/.test(line)), logs.join('\n'));
});

test('a wake with an outstanding heartbeat sends one at once', async (t) => {
  // A heartbeat that has gone out and not been answered: the socket may be
  // half-open, and the throttled timer that would have noticed is the thing the
  // alarm exists to bypass. The miss limit is set high so the heartbeat timer
  // itself cannot reconnect during the test — the branch under test is the
  // middle one (0 < missed < limit).
  const socket = new FakeSocket();
  const { transport, logs } = makeTransportWithCleanup(t, socket, {
    heartbeatMs: 20,
    heartbeatMissLimit: 50,
  });
  await transport.start();
  await socket.deliver(BANNER);
  await socket.deliver({ id: 'hello', ok: true, data: {} });

  assert.ok(await waitFor(() => socket.pings().length >= 1), 'an unanswered heartbeat had to go first');
  const pings = socket.pings().length;
  transport.wake('test');

  assert.ok(logs.some((line) => /watchdog wake \(test\): \d+ unanswered heartbeat\(s\) — pinging now/.test(line)),
    `the decision must be readable in the log: ${logs.join('\n')}`);
  assert.ok(
    await waitFor(() => socket.pings().length > pings),
    'and a heartbeat must actually go out',
  );
  assert.notEqual(transport.getState(), 'reconnecting', 'this branch pings; it does not rebuild');
});

test('a wake past the miss limit rebuilds the socket instead of waiting for the timer', async (t) => {
  // The 7-hour shape: the daemon went away, the page never noticed, and on this
  // side the only recovery would have been a page timer that is not running.
  const socket = new FakeSocket();
  const { transport } = makeTransportWithCleanup(t, socket, { heartbeatMs: 5, heartbeatMissLimit: 2 });
  await transport.start();
  await socket.deliver(BANNER);
  await socket.deliver({ id: 'hello', ok: true, data: {} });

  // Let the (unanswered) heartbeats accumulate past the limit without the
  // transport noticing — a throttled page.
  await waitFor(() => socket.pings().length >= 2, 1000, 2);
  const registered = socket.registered.length;
  transport.wake('test');

  assert.ok(
    await waitFor(() => socket.registered.length > registered),
    'the wake must replace the socket, not just ping it',
  );
});

// --------------------------------------------------------------------------
// 4. The wiring: one alarm per editor runtime
// --------------------------------------------------------------------------

const RE_A = [{ event: 'banner', data: { server: 'boardwise', protocol: '1.0', expect: 'hello' } }];

function fakeHost(stored = {}) {
  const socket = new FakeSocket();
  const logs = [];
  const toasts = [];
  const dialogs = [];
  const host = {
    sys_WebSocket: socket,
    sys_Log: { add: (line) => logs.push(line) },
    sys_Message: { showToastMessage: (message) => toasts.push(message) },
    sys_Environment: { getEditorCurrentVersion: () => '3.2.149.88089769' },
    sys_Storage: {
      getExtensionUserConfig: (key) => stored[key],
      setExtensionUserConfig: async (key, value) => {
        stored[key] = value;
        return true;
      },
    },
    sys_Dialog: {
      showInformationMessage: (message, title) => dialogs.push({ message, title }),
    },
  };
  return { host, socket, logs, toasts, dialogs };
}

/** Install a stand-in editor for one test, and guarantee the Worker is cleaned up. */
function withHost(t, stored = {}) {
  const parts = fakeHost(stored);
  connector.__setFacadeForTests(createFacade(parts.host));
  t.after(() => {
    connector.deactivate();
    connector.__setFacadeForTests(undefined);
  });
  return parts;
}

/** Install a fake Worker on the ambient global for one test. */
function withFakeWorker(t, refuse = '') {
  resetFakeWorker(refuse);
  const had = Object.prototype.hasOwnProperty.call(globalThis, 'Worker');
  const previous = globalThis.Worker;
  globalThis.Worker = FakeWorker;
  t.after(() => {
    if (had) globalThis.Worker = previous;
    else delete globalThis.Worker;
  });
}

test('connecting starts exactly one alarm, and it is fed while the page lives', async (t) => {
  withFakeWorker(t);
  const parts = withHost(t);

  await connector.activate();

  assert.equal(FakeWorker.instances.length, 1, 'one connection, one alarm');
  const worker = FakeWorker.instances[0];
  assert.ok(
    await waitFor(() => worker.posted.some((message) => message.type === 'activity')),
    'the transport must keep the alarm fed, not just start it',
  );
  assert.equal(worker.terminated, false);

  const status = connector.getStatus();
  assert.equal(status.watchdog.state, 'running');
  assert.ok(status.watchdog.checkIntervalMs > 0);
});

test('a manual reconnect replaces the socket, never the alarm', async (t) => {
  // The mutation this bites: dropping the singleton guard in `ensureWatchdog`,
  // which would start a second thread for every connect and terminate neither.
  withFakeWorker(t);
  const parts = withHost(t);

  await connector.activate();
  await connector.reconnect();
  await connector.reconnect();

  assert.equal(FakeWorker.instances.length, 1, 'one alarm per editor runtime, whatever reconnects');
  assert.equal(FakeWorker.instances[0].terminated, false, 'and the live one is still the live one');
});

test('a fresh evaluation of the bundle adopts the runtime and builds no second alarm', async (t) => {
  // What a menu click is: the editor evaluates the bundle again. Everything that
  // must be shared travels through the published record (024), and the Worker is
  // part of that — one thread, not one per click.
  resetFakeWorker();
  const had = Object.prototype.hasOwnProperty.call(globalThis, 'Worker');
  const previous = globalThis.Worker;
  globalThis.Worker = FakeWorker;
  const parts = fakeHost();
  const previousEda = Object.getOwnPropertyDescriptor(globalThis, 'eda');
  globalThis.eda = parts.host;
  t.after(() => {
    if (had) globalThis.Worker = previous;
    else delete globalThis.Worker;
    if (previousEda) Object.defineProperty(globalThis, 'eda', previousEda);
    else delete globalThis.eda;
  });

  const first = await import(`../dist/esm/index.mjs?watchdog-a=${Date.now()}-${Math.random()}`);
  assert.ok(await waitFor(() => parts.socket.registered.length > 0), 'the first evaluation connects');
  const second = await import(`../dist/esm/index.mjs?watchdog-b=${Date.now()}-${Math.random()}`);
  parts.socket.connect();
  await parts.socket.deliver(RE_A[0]);
  // A menu click, then a reconnect from the *new* evaluation: both must reach
  // the controller that owns the socket, and its alarm.
  await second.reconnect();
  await waitFor(() => false, 50);

  assert.equal(FakeWorker.instances.length, 1, 'the second evaluation must not build an alarm of its own');
  assert.equal(second.getStatus().watchdog.state, 'running', 'and it still reports the live one');
  t.after(() => {
    second.deactivate();
    first.deactivate();
    second.__setFacadeForTests(undefined);
  });
});

test('stop() takes the Worker with it, and a later connect builds a fresh one', async (t) => {
  // "A stopped transport sends nothing, ever" (docs/bridge.md §7) has to be true
  // of the thread as well: an alarm left ticking would keep waking a transport
  // that is not there.
  withFakeWorker(t);
  const parts = withHost(t);

  await connector.activate();
  const first = FakeWorker.instances[0];

  connector.stopConnection();

  assert.equal(first.terminated, true, 'stopped means the Worker is gone');
  assert.equal(
    Object.prototype.hasOwnProperty.call(connector.getStatus(), 'watchdog'),
    false,
    'and nothing is left to report as running',
  );

  await connector.reconnect();
  assert.equal(FakeWorker.instances.length, 2, 'a reconnect after a stop is a new alarm');
  assert.equal(FakeWorker.instances[1].terminated, false);
});

test('a host that refuses a Worker still connects, and About… says so', async (t) => {
  // The honest degradation (026b §2.3): no alarm, no silence about it.
  withFakeWorker(t, 'Refused to create a Worker: violates the document CSP');
  const parts = withHost(t);

  await connector.activate();

  assert.equal(parts.socket.registered.length, 1, 'the connection is unaffected');
  const status = connector.getStatus();
  assert.equal(status.watchdog.state, 'unavailable');
  assert.match(String(status.watchdog.reason), /violates the document CSP/);
  assert.ok(
    parts.logs.some((line) => /watchdog: unavailable/.test(line)),
    `the log panel must say it: ${parts.logs.join('\n')}`,
  );

  connector.about();
  const box = parts.dialogs.at(-1).message;
  assert.match(box, /watchdog: unavailable\(Refused to create a Worker: violates the document CSP\)/);
});

test('About… reports the alarm without claiming it makes the window immune', async (t) => {
  withFakeWorker(t);
  const parts = withHost(t);

  await connector.activate();
  FakeWorker.instances[0].wake({ wakes: 1, silenceMs: 47_000 });
  connector.about();

  const box = parts.dialogs.at(-1).message;
  assert.match(box, /watchdog: running \(checks every 15000 ms, wakes after 45000 ms of page silence, wakes so far: 1\)/);
  for (const word of ['immune', 'immunity', 'always', 'never fails']) {
    assert.equal(box.includes(word), false, `the box must not promise "${word}"`);
  }
});

test('About… says why there is no alarm when auto-connect is off', async (t) => {
  withFakeWorker(t);
  const parts = withHost(t, { autoConnect: false });

  await connector.activate();

  assert.equal(FakeWorker.instances.length, 0, 'nothing to watch, nothing started');
  connector.about();
  assert.match(parts.dialogs.at(-1).message, /watchdog: not started \(auto-connect is off\)/);
});

test('About… reports a stopped alarm as stopped, not as never started', async (t) => {
  // After the menu's Stop the alarm is gone with the socket, and "no connection
  // attempt yet" would be a plainly false reading of a runtime that has been
  // connected and stopped.
  withFakeWorker(t);
  const parts = withHost(t);

  await connector.activate();
  connector.stopConnection();
  connector.about();

  assert.match(parts.dialogs.at(-1).message, /watchdog: stopped \(the alarm goes with the connection\)/);
});

test('a wake actually drives the connection: the alarm and the transport are wired together', async (t) => {
  // The end-to-end of the mechanism: the Worker speaks, the page acts. Without
  // the wiring in `ensureWatchdog` the alarm is a thread that reports into
  // nothing, which is the shape a "fake alarm" mutation produces.
  //
  // Driven from `connecting` on purpose: the wake's own reaction is asserted
  // case by case in part 3 above (a healthy connection does nothing), and this
  // test is about the one thing only the wiring can show — that a message from
  // the Worker reaches the transport at all. No wall-clock waits are needed for
  // that, so the test cannot go flaky on a slow machine.
  withFakeWorker(t);
  const parts = withHost(t);

  await connector.activate();
  assert.equal(parts.socket.registered.length, 1);
  assert.equal(connector.getStatus().state, 'connecting', 'nothing has answered yet');

  FakeWorker.instances[0].wake({ wakes: 1, silenceMs: 46_000 });

  assert.ok(
    await waitFor(() => parts.socket.registered.length > 1),
    'the wake must reach the transport and replace the silent attempt',
  );
  assert.equal(connector.getStatus().watchdog.wakes, 1, 'and the alarm counted it');
});
