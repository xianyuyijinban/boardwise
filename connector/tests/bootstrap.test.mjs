/**
 * 024 — the module-load bootstrap, and the runtime it hands to the next
 * evaluation of the bundle.
 *
 * Two host facts meet here, both measured rather than assumed:
 *
 * 1. 立创 EDA 3.2.149 never dispatches `activate()` for a user extension (the
 *    host's extension pass runs before the user info that gates it, then is
 *    skipped — upstream #219/#221). So the connect has to start at module
 *    scope, and `activate()` has to stay an idempotent second trigger.
 * 2. The editor evaluates the bundle more than once in one process (every menu
 *    click does). So "start at module scope" is only safe if the evaluations
 *    share one controller — otherwise each copy opens its own socket to the
 *    same daemon.
 *
 * The mechanism under test lives on the editor's own per-extension object
 * (`eda`), which is the one thing that outlives an evaluation: a versioned
 * record under `__boardwiseTransportRuntime`. These tests drive it three ways —
 * with a stand-in host (`createFacade`), with the *ambient* global bound before
 * a fresh evaluation of the bundle (the cold-start shape), and at the transport
 * level for the registry mechanics themselves.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { createFacade } from '../dist/esm/facade.mjs';
import * as connector from '../dist/esm/index.mjs';
import { SHARED_RUNTIME_KEY, SHARED_RUNTIME_MEMBERS, Transport, sharedRuntimeImplementation } from '../dist/esm/transport.mjs';
import { VERSION } from '../dist/esm/version.mjs';

/**
 * Every member `index.ts` reaches for on a record it adopts, in the order
 * `OwnedTransportRuntime` declares them — re-verify each against the source
 * before editing this list:
 *
 * - `start`, `reconnect`, `stop`, `about`, `getStatus` — `runtime().<member>()`
 *   in the menu export of the same name, plus `deactivate()`'s
 *   `shared.runtime.stop(true)`.
 * - `bootstrapFromModuleLoad` — `runtime().bootstrapFromModuleLoad()`: the module
 *   scope at the bottom of the file, and `__bootstrapForTests`.
 * - `selfArm` — `runtime().selfArm('test', …)`, the test seam.
 * - `noteEvaluation` — `published.noteEvaluation()`, called on the record at the
 *   moment `adoptPublishedRuntime` takes it over.
 *
 * `implementation` is deliberately absent: it is a string, and
 * `isReusableRuntime` compares it before looking at any of the above.
 */
const CALLED_MEMBERS = [
  'start',
  'bootstrapFromModuleLoad',
  'reconnect',
  'stop',
  'selfArm',
  'about',
  'getStatus',
  'noteEvaluation',
];

/**
 * A stand-in for a published record: every member above, each recording that it
 * ran, minus `missing` when one is named.
 */
function stubRecord(calls, missing) {
  const record = { implementation: sharedRuntimeImplementation(VERSION) };
  for (const member of CALLED_MEMBERS) {
    record[member] = () => {
      calls.push(member);
      return member === 'getStatus' ? { state: 'adopted-record' } : undefined;
    };
  }
  if (missing) delete record[missing];
  return record;
}

/** Mirrors the official `eda.sys_WebSocket` signature. */
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

  async deliver(frame) {
    await this.onMessage?.({ data: JSON.stringify(frame) });
    await new Promise((resolve) => setImmediate(resolve));
  }

  frame(action) {
    return this.sent.find((entry) => entry.frame.action === action)?.frame;
  }

  hellos() {
    return this.sent.filter((entry) => entry.frame.action === 'hello');
  }
}

/** A stand-in editor host, shaped like the real one but wholly in-process. */
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

/** Install a facade for one test, and guarantee its timers are cleaned up. */
function withHost(t, stored) {
  const parts = fakeHost(stored);
  connector.__setFacadeForTests(createFacade(parts.host));
  t.after(() => {
    connector.deactivate();
    connector.__setFacadeForTests(undefined);
  });
  return parts;
}

/** Poll until `predicate` holds; a fixed sleep guesses at someone else's clock. */
async function waitFor(predicate, timeout = 4000, interval = 10) {
  const deadline = Date.now() + timeout;
  for (;;) {
    if (await predicate()) return true;
    if (Date.now() > deadline) return false;
    await new Promise((resolve) => setTimeout(resolve, interval));
  }
}

/**
 * `HH:MM:SS` on this machine's clock — the form `About…` prints every time in.
 *
 * Local on purpose since 0.4.13 (before that the box printed UTC digits sliced
 * out of an ISO string, which reads eight hours early to a UTC+8 reader). The
 * expectation is derived the same way here rather than pinned to a zone, so the
 * suite passes wherever it runs — and a reversion to `.slice(11, 19)` fails on
 * any machine that is not at UTC+0.
 */
function localClock(iso) {
  const at = new Date(iso);
  const pad = (value) => String(value).padStart(2, '0');
  return `${pad(at.getHours())}:${pad(at.getMinutes())}:${pad(at.getSeconds())}`;
}

/**
 * Bind the editor global so a *fresh evaluation* of the bundle sees it.
 *
 * `__setFacadeForTests` can only install a stand-in host in an instance that is
 * already evaluating, which is too late for the module scope — and the module
 * scope is exactly what 024 is about. On the machine the host binds `eda` the
 * same way it is done here (as a scope binding, not a `globalThis` property,
 * which is why the connector never reads it through `globalThis`), so this is
 * the cold-start shape rather than a contrivance.
 */
function bindAmbientHost(t, host) {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'eda');
  globalThis.eda = host;
  t.after(() => {
    if (previous) Object.defineProperty(globalThis, 'eda', previous);
    else delete globalThis.eda;
  });
}

/**
 * A second, independent evaluation of the same bundle.
 *
 * Node keys modules by URL, so a distinct query string is a distinct evaluation
 * — the closest thing to a menu click that a test process can produce. The
 * `transport.ts` chunk the two share is stateless, by design: everything that
 * must be shared is in the record under {@link SHARED_RUNTIME_KEY}.
 */
async function evaluateAgain(label) {
  return await import(`../dist/esm/index.mjs?${label}=${Date.now()}-${Math.random()}`);
}

// This bundle was evaluated before any host existed (the Node side of the 004f
// "the editor is late" case), so the import-time controller is local and
// unpublished. Clear it, so every test below drives the real publish path
// rather than reusing that leftovers-of-import one.
connector.__setFacadeForTests(undefined);

// --------------------------------------------------------------------------
// Transport: start() is idempotent
// --------------------------------------------------------------------------

test('Transport.start() does not re-register a live attempt', async () => {
  // The bug this pins: `activate()` arriving after the module-load bootstrap
  // used to open a *second* socket, because `start()` registered a fresh id
  // every time. Ids are ours to choose, so nothing would have collapsed the two
  // into one connection.
  const socket = new FakeSocket();
  const transport = new Transport({
    url: 'ws://127.0.0.1:61190/eda',
    token: 'tok',
    socket,
    minBackoffMs: 5,
    maxBackoffMs: 20,
    heartbeatMs: 60_000,
    onRequest: async () => ({}),
  });

  await transport.start();
  await transport.start();
  await transport.start();
  assert.equal(socket.registered.length, 1, 'three starts, one registration');

  // An explicit stop is a different statement: the next start must connect.
  transport.stop();
  await transport.start();
  assert.equal(socket.registered.length, 2, 'a stopped transport reconnects');
  assert.equal(socket.registered[1].id, 'boardwise-2', 'and still uses a fresh id');

  transport.stop();
});

// --------------------------------------------------------------------------
// The module scope alone is enough (the 3.2.149 cold start)
// --------------------------------------------------------------------------

test('a bundle evaluated with the editor bound connects without activate()', async (t) => {
  const parts = fakeHost();
  bindAmbientHost(t, parts.host);

  const fresh = await evaluateAgain('coldstart');
  t.after(() => {
    fresh.deactivate();
    fresh.__setFacadeForTests(undefined);
  });

  assert.ok(
    await waitFor(() => parts.socket.registered.length > 0),
    'the module scope must open the socket on its own',
  );
  assert.equal(parts.socket.registered.length, 1, 'exactly one socket');

  const status = fresh.getStatus();
  assert.equal(status.moduleBootstrapObserved, true, 'the bootstrap ran');
  assert.equal(status.activateObserved, false, 'and the editor never called activate()');
  assert.equal(status.state, 'connecting');

  // The discriminator the machine needs: the bundle was evaluated, the
  // lifecycle callback was not dispatched, and the connector is up anyway.
  fresh.about();
  const text = parts.dialogs.at(-1).message;
  assert.match(text, /lifecycle: moduleBootstrapObserved=yes activateObserved=no evaluations=1/);
  assert.match(text, /bootstrap: this is the first evaluation of the bundle/);
});

// --------------------------------------------------------------------------
// activate() early, late, or never
// --------------------------------------------------------------------------

test('activate() after the bootstrap is a no-op: one socket, one handshake', async (t) => {
  const parts = withHost(t);

  await connector.__bootstrapForTests();
  assert.equal(parts.socket.registered.length, 1, 'the bootstrap connected');

  await connector.activate(); // the editor finally gets round to calling us
  assert.equal(parts.socket.registered.length, 1, 'a late activate() must not double up');

  await parts.socket.deliver({
    event: 'banner',
    data: { server: 'boardwise', protocol: '1.0', expect: 'hello' },
  });
  assert.equal(parts.socket.hellos().length, 1, 'one connection, one handshake');

  const status = connector.getStatus();
  assert.equal(status.moduleBootstrapObserved, true);
  assert.equal(status.activateObserved, true, 'the callback was recorded when it arrived');
});

test('activate() first, then the bootstrap: still one socket', async (t) => {
  const parts = withHost(t);

  await connector.activate();
  await connector.__bootstrapForTests(); // a re-evaluation, or the same evaluation re-run
  await connector.__bootstrapForTests();

  assert.equal(parts.socket.registered.length, 1, 'whichever path wins, there is one socket');
  const status = connector.getStatus();
  assert.equal(status.activateObserved, true);
  assert.equal(status.moduleBootstrapObserved, true);
});

test('the two counters reach the status read-out, and the About box', async (t) => {
  const parts = withHost(t);

  // The production sequence when the editor *does* dispatch activate(): the
  // module scope bootstraps, and the callback arrives afterwards.
  await connector.__bootstrapForTests();
  await connector.activate();
  connector.about();
  const text = parts.dialogs.at(-1).message;
  assert.match(text, /lifecycle: moduleBootstrapObserved=yes activateObserved=yes/);
  const status = connector.getStatus();
  assert.match(
    text,
    new RegExp(`bootstrap: the bundle was evaluated once, at ${localClock(status.bootstrapAt)}, and activate\\(\\) was dispatched`),
  );

  assert.equal(status.moduleBootstrapObserved, true);
  assert.equal(status.activateObserved, true);
  assert.equal(status.evaluations, 1, 'one evaluation, counted by the controller it created');
  assert.match(String(status.bootstrapAt), /^\d{4}-\d\d-\d\dT/);
  assert.match(String(status.activateAt), /^\d{4}-\d\d-\d\dT/);
});

// --------------------------------------------------------------------------
// The published record: reuse, retirement, and a host that refuses it
// --------------------------------------------------------------------------

test('a second evaluation of the bundle reuses the first controller', async (t) => {
  const parts = fakeHost();
  bindAmbientHost(t, parts.host);

  // Evaluation 1: this file's import, driven explicitly with the host there.
  connector.__setFacadeForTests(createFacade(parts.host));
  await connector.__bootstrapForTests();
  assert.equal(parts.socket.registered.length, 1);

  const published = parts.host[SHARED_RUNTIME_KEY];
  assert.ok(published, 'the controller must be published on the editor object');
  assert.equal(published.implementation, sharedRuntimeImplementation(VERSION));

  // Evaluation 2: a fresh copy of the bundle, whose module scope must find that
  // controller instead of building its own.
  const second = await evaluateAgain('evaluation');
  t.after(() => {
    second.deactivate();
    second.__setFacadeForTests(undefined);
    connector.deactivate();
    connector.__setFacadeForTests(undefined);
  });
  assert.equal(parts.socket.registered.length, 1, 'the second evaluation must not dial');

  const status = second.getStatus();
  assert.equal(status.evaluations, 2, 'counted as an evaluation, not as a second connection');
  assert.equal(status.state, 'connecting');
  assert.equal(parts.host[SHARED_RUNTIME_KEY], published, 'the same record, not a new one');

  // And it says so in the log panel, which is the only window a user has.
  assert.ok(
    parts.logs.some((line) => /reusing the controller published by/.test(line)),
    parts.logs.join('\n'),
  );
});

test('the About box from a second evaluation reports the owner, not its own empty copy', async (t) => {
  // 0.4.12 shipped `about()` calling `runAbout()` directly, so the box was built
  // from the *clicking* evaluation's module state. The editor re-evaluates the
  // bundle for every menu click, and that copy has never run the bootstrap and
  // has never seen a frame — so the box read `no/no/0`, `state: idle`,
  // `pairing: not connected yet` and "the module-scope bootstrap never ran in
  // this editor runtime" while the daemon was connected and pinging (measured on
  // 3.2.186, 2026-09-21). This is also the gap in this suite: the test above
  // builds a real second evaluation and never calls `second.about()`.
  const parts = fakeHost();
  bindAmbientHost(t, parts.host);

  // Evaluation 1: this file's import, fully connected and paired — the state the
  // user is in when they open the menu.
  connector.__setFacadeForTests(createFacade(parts.host));
  await connector.__bootstrapForTests();
  await parts.socket.deliver({
    event: 'banner',
    data: { server: 'boardwise', protocol: '1.0', expect: 'hello' },
  });
  await parts.socket.deliver({
    id: 'hello',
    ok: true,
    data: { role: 'connector', protocol: '1.0', paired: true, fingerprint: 'ab12cd34' },
  });
  const owner = connector.getStatus();
  assert.equal(owner.state, 'connected', 'the owner owns a live connection');
  assert.equal(owner.fingerprint, 'ab12cd34');

  // Evaluation 2: what a menu click is — a fresh copy of the bundle.
  const second = await evaluateAgain('about-owner');
  t.after(() => {
    second.deactivate();
    second.__setFacadeForTests(undefined);
    connector.deactivate();
    connector.__setFacadeForTests(undefined);
  });

  // The click must describe the controller that owns the connection...
  second.about();
  const text = parts.dialogs.at(-1).message;
  assert.match(text, /lifecycle: moduleBootstrapObserved=yes activateObserved=no evaluations=2/);
  assert.match(text, /^state: connected$/m);
  assert.match(text, /^pairing: paired with the daemon \(fingerprint ab12cd34\)$/m);
  assert.equal(
    /never ran in this editor runtime|the host had not loaded the extension/.test(text),
    false,
    `the box must not deny the bootstrap that connected it:\n${text}`,
  );

  // ...and must not disturb it. The clicking copy has a claim gate and an arm of
  // its own (`connectionAttempted`, `selfArm` are per evaluation), so 0.4.12's
  // About click registered the socket a second time — `docs/bridge.md` §12.
  assert.equal(parts.socket.registered.length, 1, 'the click must not open a second socket');
  assert.equal(connector.getStatus().state, 'connected', 'the owner is untouched');
});

test('a controller published by another build is stopped before this one takes over', async (t) => {
  const parts = withHost(t);
  const calls = [];
  // What an older build leaves behind: the same key, a signature this build
  // cannot use, and a live socket of its own.
  parts.host[SHARED_RUNTIME_KEY] = {
    implementation: '0.4.0:cross-eval-v1',
    start: () => calls.push('start'),
    stop: (quiet) => calls.push(`stop(${String(quiet)})`),
    bootstrapFromModuleLoad: () => calls.push('bootstrap'),
    getStatus: () => ({}),
  };

  await connector.activate();

  assert.deepEqual(calls, ['stop(undefined)'], 'the stale controller is stopped, best-effort');
  assert.equal(parts.socket.registered.length, 1, 'this build owns the socket');
  assert.equal(
    parts.host[SHARED_RUNTIME_KEY].implementation,
    sharedRuntimeImplementation(VERSION),
    'and it replaces the record',
  );
  assert.ok(
    parts.logs.some((line) => /retired the controller published by 0\.4\.0:cross-eval-v1/.test(line)),
    parts.logs.join('\n'),
  );
});

test('the validated member list covers every member the connector calls', () => {
  // The list in `transport.ts` is the record's whole interface minus the
  // `implementation` string. This is the assertion that keeps it that way when
  // `index.ts` starts reaching for one more member: a name the connector calls
  // but does not validate fails at the call site, not here.
  assert.deepEqual(
    [...SHARED_RUNTIME_MEMBERS].sort(),
    [...CALLED_MEMBERS].sort(),
    'every member the connector calls on an adopted record must be validated',
  );
});

test('a published record missing any member this build calls is retired, not adopted', async (t) => {
  // Why the member check is in `transport.ts` rather than a `typeof` guard at
  // each call site (0.4.13): the signature matches, so the version gate cannot
  // see such a record, and every name in the list is one a later evaluation
  // *calls*. Adopting it moves the failure to that call site — and not always
  // loudly: `noteEvaluation` is called inside `runtime()`, whose throw
  // `activate()` catches on purpose so an editor-host rejection cannot become an
  // unhandled rejection. The extension would then look inert rather than broken.
  const parts = withHost(t);

  let registrations = 0;
  for (const missing of CALLED_MEMBERS) {
    const calls = [];
    // A clean evaluation per case: this module keeps the controller it adopted,
    // and a leftover one answers before the host object is read at all.
    connector.__setFacadeForTests(undefined);
    connector.__setFacadeForTests(createFacade(parts.host));
    const stub = stubRecord(calls, missing);
    parts.host[SHARED_RUNTIME_KEY] = stub;

    await connector.activate();

    assert.equal(
      calls.includes('stop'),
      missing !== 'stop',
      `retired, best-effort — a record with no \`stop\` cannot be (${missing} missing)`,
    );
    assert.notEqual(parts.host[SHARED_RUNTIME_KEY], stub, `replaced (${missing} missing)`);
    for (const member of CALLED_MEMBERS) {
      assert.equal(
        typeof parts.host[SHARED_RUNTIME_KEY][member],
        'function',
        `the replacement carries ${member} (${missing} missing)`,
      );
    }
    registrations += 1;
    assert.equal(parts.socket.registered.length, registrations, `one socket (${missing} missing)`);
  }
});

test('a record carrying every validated member is adopted, and its counters are the ones used', async (t) => {
  // The other direction, so that a longer list cannot pass by refusing
  // everything: a complete record keeps its place on the editor object — no
  // retirement, no second controller — and it answers the status read-out.
  const parts = withHost(t);
  const calls = [];
  const stub = stubRecord(calls, undefined);
  parts.host[SHARED_RUNTIME_KEY] = stub;

  await connector.activate();

  assert.deepEqual(calls, ['noteEvaluation', 'start'], 'adopted and counted, then started');
  assert.equal(parts.host[SHARED_RUNTIME_KEY], stub, 'the same record, never replaced');
  assert.equal(
    connector.getStatus().state,
    'adopted-record',
    'the status read-out is the adopted record\'s, not this evaluation\'s',
  );
});

test('a stale controller that throws while stopping still gets replaced', async (t) => {
  const parts = withHost(t);
  parts.host[SHARED_RUNTIME_KEY] = {
    implementation: '0.2.0:cross-eval-v1',
    start: () => {},
    stop: () => {
      throw new Error('this controller cannot stop');
    },
    bootstrapFromModuleLoad: () => {},
    getStatus: () => ({}),
  };

  await connector.activate();

  assert.equal(parts.socket.registered.length, 1, 'an old controller throwing is not our problem');
  assert.equal(
    parts.host[SHARED_RUNTIME_KEY].implementation,
    sharedRuntimeImplementation(VERSION),
  );
});

test('a host that refuses the hand-off still connects, and says so', async (t) => {
  const parts = withHost(t);
  Object.freeze(parts.host); // a sealed/frozen extension object is a real shape

  await connector.__bootstrapForTests();

  assert.equal(parts.socket.registered.length, 1, 'the controller works unpublished');
  assert.equal(parts.host[SHARED_RUNTIME_KEY], undefined, 'nothing could be published');
  assert.ok(
    parts.logs.some((line) => /the editor object is not reachable yet/.test(line)),
    `the failed hand-off must be visible: ${parts.logs.join('\n')}`,
  );
});

test('the bootstrap tries once more on the next macrotask', async (t) => {
  // The reason for the second try: a sandbox may bind its globals only when the
  // current task ends, so "no editor at module scope" is not final until the
  // next macrotask has been given its chance.
  const parts = fakeHost();
  connector.__setFacadeForTests(undefined);
  t.after(() => {
    connector.deactivate();
    connector.__setFacadeForTests(undefined);
  });

  await connector.__bootstrapForTests(); // stands down: no host, no ambient `eda`
  assert.equal(parts.socket.registered.length, 0, 'nothing to connect to yet');

  connector.__setFacadeForTests(createFacade(parts.host)); // the editor appears, same task
  assert.ok(
    await waitFor(() => parts.socket.registered.length > 0),
    'the next-macrotask attempt must find the editor',
  );
  assert.ok(
    parts.logs.some((line) => /next-macrotask attempt: the editor is reachable/.test(line)),
    parts.logs.join('\n'),
  );

  // The retry ladder is still armed from the stand-down. When it fires it must
  // be a no-op, not a second socket — the attempt is one-shot.
  await new Promise((resolve) => setTimeout(resolve, 400));
  assert.equal(parts.socket.registered.length, 1, 'the ladder retry must not double up');
});

test('deactivate() releases the record, so the next load owns its own controller', async (t) => {
  const parts = fakeHost();
  connector.__setFacadeForTests(createFacade(parts.host));
  t.after(() => connector.__setFacadeForTests(undefined));

  await connector.__bootstrapForTests();
  const published = parts.host[SHARED_RUNTIME_KEY];
  assert.ok(published);

  connector.deactivate();

  assert.equal(parts.host[SHARED_RUNTIME_KEY], undefined, 'the stopped controller is un-published');
  assert.ok(
    parts.socket.closed.includes('boardwise-1'),
    `the socket must be closed, not left open: ${JSON.stringify(parts.socket.closed)}`,
  );
});
