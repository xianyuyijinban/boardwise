/**
 * Transport tests against a fake `eda.sys_WebSocket`.
 *
 * The fake mirrors the official signatures (`register(id, uri, onMessage,
 * onConnected)`, `send(id, data)`, `close(id)`) so the tests exercise the same
 * call shapes the editor will see.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { ActionError, parseFrame, requestFrame } from '../dist/esm/protocol.mjs';
import { Transport } from '../dist/esm/transport.mjs';

class FakeSocket {
  constructor() {
    this.registered = [];
    this.sent = [];
    this.closed = [];
    this.onMessage = undefined;
    this.onConnected = undefined;
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

  /** Simulate the editor's connect callback. */
  connect() {
    this.onConnected?.();
  }

  /** Simulate a frame arriving from the daemon. */
  async deliver(frame) {
    await this.onMessage?.({ data: JSON.stringify(frame) });
  }

  lastFrame() {
    return this.sent[this.sent.length - 1]?.frame;
  }
}

function makeTransport(socket, overrides = {}) {
  const requests = [];
  const transport = new Transport({
    url: 'ws://127.0.0.1:61190/eda',
    token: 'tok',
    socket,
    minBackoffMs: 5,
    maxBackoffMs: 20,
    heartbeatMs: 10,
    heartbeatMissLimit: 2,
    onRequest: async (action, params) => {
      requests.push({ action, params });
      return { echoed: action };
    },
    ...overrides,
  });
  return { transport, requests };
}

/**
 * Poll until `predicate` holds, or the deadline passes.
 *
 * Preferred over `await sleep(n)`: Node clamps short timers to the platform's
 * timer granularity (~15.6 ms on Windows), so a nominal 30 ms of heartbeat
 * ticks can take twice that in practice. Polling keeps the suite fast on Linux
 * and correct on Windows, instead of tuning a sleep to the slowest platform.
 */
async function waitFor(predicate, timeoutMs = 1000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return true;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  return predicate();
}

test('registers with the daemon url and sends hello on connect', async () => {
  const socket = new FakeSocket();
  const { transport } = makeTransport(socket);
  await transport.start();

  assert.equal(socket.registered.length, 1);
  assert.equal(socket.registered[0].uri, 'ws://127.0.0.1:61190/eda');
  assert.equal(socket.sent.length, 0, 'no frame before the socket is connected');

  socket.connect();
  const hello = socket.lastFrame();
  assert.equal(hello.action, 'hello');
  assert.equal(hello.params.token, 'tok');
  assert.equal(hello.params.role, 'connector');
  assert.match(hello.params.protocol, /^\d+\.\d+$/);

  transport.stop();
});

test('a successful hello response marks the transport connected', async () => {
  const socket = new FakeSocket();
  const states = [];
  const { transport } = makeTransport(socket, {
    onStatus: (state) => states.push(state),
  });
  await transport.start();
  socket.connect();
  await socket.deliver({ id: 'hello', ok: true, data: { role: 'connector' } });

  assert.equal(transport.getState(), 'connected');
  assert.deepEqual(states, ['connecting', 'handshaking', 'connected']);

  transport.stop();
});

test('a rejected hello triggers a reconnect', async () => {
  const socket = new FakeSocket();
  const { transport } = makeTransport(socket);
  await transport.start();
  socket.connect();
  await socket.deliver({ id: 'hello', ok: false, error: { code: 'UNAUTHENTICATED', message: 'bad token' } });

  assert.equal(transport.getState(), 'reconnecting');
  assert.deepEqual(socket.closed, ['boardwise-1']);

  // The retry registers again, with a fresh id (the API ignores parameter
  // changes on a still-live id).
  assert.ok(await waitFor(() => socket.registered.length === 2), 'expected a retry');
  assert.equal(socket.registered[1].id, 'boardwise-2');

  transport.stop();
});

test('request frames are dispatched to onRequest and answered', async () => {
  const socket = new FakeSocket();
  const { transport, requests } = makeTransport(socket);
  await transport.start();
  socket.connect();

  await socket.deliver({ id: 'r1', action: 'pcb.readback', params: { includePrimitives: true } });

  assert.deepEqual(requests, [{ action: 'pcb.readback', params: { includePrimitives: true } }]);
  const answer = socket.lastFrame();
  assert.equal(answer.id, 'r1');
  assert.equal(answer.ok, true);
  assert.deepEqual(answer.data, { echoed: 'pcb.readback' });

  transport.stop();
});

test('handler failures become structured error frames', async () => {
  const socket = new FakeSocket();
  const { transport } = makeTransport(socket, {
    onRequest: async () => {
      throw new ActionError('NOT_IMPLEMENTED', 'no such action');
    },
  });
  await transport.start();
  socket.connect();
  await socket.deliver({ id: 'r2', action: 'board.explode' });

  const answer = socket.lastFrame();
  assert.equal(answer.ok, false);
  assert.equal(answer.error.code, 'NOT_IMPLEMENTED');

  transport.stop();
});

test('a request without an action is refused, not dispatched', async () => {
  const socket = new FakeSocket();
  const { transport, requests } = makeTransport(socket);
  await transport.start();
  socket.connect();
  await socket.deliver({ id: 'r3' });

  assert.equal(requests.length, 0);
  assert.equal(socket.lastFrame().error.code, 'BAD_REQUEST');

  transport.stop();
});

test('heartbeat misses force a reconnect', async () => {
  const socket = new FakeSocket();
  const { transport } = makeTransport(socket);
  await transport.start();
  socket.connect();

  const before = socket.registered.length;
  assert.ok(
    await waitFor(() => socket.registered.length > before),
    'expected a re-registration after missed heartbeats',
  );
  // The reconnect must come from *missed heartbeats*, not from anything else:
  // the miss limit is 2, so at least two pings went unanswered first.
  const pings = socket.sent.filter((entry) => entry.frame.action === 'ping');
  assert.ok(pings.length >= 2, `expected >=2 pings before the reconnect, saw ${pings.length}`);
  assert.equal(
    transport.getState() === 'reconnecting' || transport.getState() === 'connecting',
    true,
  );

  transport.stop();
});

test('a banner alone triggers hello, with no editor callback at all', async () => {
  // The task 004b fix. The editor's connect callback does not fire on the real
  // editor, so sending hello from it meant nothing was ever sent. The
  // handshake now hangs off inbound traffic, which is a fact rather than a
  // callback's opinion.
  const socket = new FakeSocket();
  const { transport } = makeTransport(socket);
  await transport.start();
  assert.equal(socket.registered.length, 1);
  assert.equal(socket.sent.length, 0, 'nothing goes out before something comes in');

  // Deliberately never call socket.connect().
  await socket.deliver({
    event: 'banner',
    data: { server: 'boardwise', protocol: '1.0', expect: 'hello' },
  });

  assert.equal(socket.lastFrame().action, 'hello');
  assert.equal(transport.getState(), 'handshaking');
  transport.stop();
});

test('the banner is never answered with an error frame', async () => {
  // Regression guard: an event carries no `action`, so the request path used
  // to reply BAD_REQUEST to it — which the daemon would then read as a
  // protocol violation during its own handshake.
  const socket = new FakeSocket();
  const { transport } = makeTransport(socket);
  await transport.start();
  await socket.deliver({ event: 'banner', data: {} });

  const replies = socket.sent
    .map((entry) => entry.frame)
    .filter((frame) => 'ok' in frame);
  assert.deepEqual(replies, [], 'an event must not be answered');
  transport.stop();
});

test('hello is sent once even when both triggers fire', async () => {
  // The daemon rejects a second hello with PROTOCOL_VIOLATION, so the
  // idempotence is a contract, not tidiness.
  const socket = new FakeSocket();
  const { transport } = makeTransport(socket);
  await transport.start();
  socket.connect(); // advisory trigger
  await socket.deliver({ event: 'banner', data: {} }); // primary trigger
  await socket.deliver({ event: 'banner', data: {} });

  const hellos = socket.sent.filter((entry) => entry.frame.action === 'hello');
  assert.equal(hellos.length, 1, 'a second hello would be a PROTOCOL_VIOLATION');
  transport.stop();
});

test('the heartbeat starts after hello, not on the editor callback', async () => {
  // A transport that only ever sees a banner must still keep itself alive.
  const socket = new FakeSocket();
  const { transport } = makeTransport(socket);
  await transport.start();
  await socket.deliver({ event: 'banner', data: {} });

  assert.ok(
    await waitFor(() => socket.sent.some((entry) => entry.frame.action === 'ping')),
    'expected heartbeats once the handshake is on the wire',
  );
  transport.stop();
});

test('stop() clears timers and closes the socket', async () => {
  const socket = new FakeSocket();
  const { transport } = makeTransport(socket);
  await transport.start();
  socket.connect();
  transport.stop();

  assert.equal(transport.getState(), 'stopped');
  assert.deepEqual(socket.closed, ['boardwise-1']);
  const sentAfterStop = socket.sent.length;
  // Long enough to cover several heartbeat intervals even at Windows timer
  // granularity — otherwise "nothing was sent" is trivially but meaninglessly true.
  await new Promise((resolve) => setTimeout(resolve, 200));
  assert.equal(socket.sent.length, sentAfterStop, 'nothing is sent after stop()');
});

test('an injected requestFrame shape matches what the daemon parses', () => {
  // Guards the one thing both sides must agree on byte-for-byte.
  const frame = requestFrame('ping', undefined, 'zz');
  assert.deepEqual(Object.keys(frame).sort(), ['action', 'id']);
  assert.deepEqual(parseFrame(JSON.stringify(frame)), { id: 'zz', action: 'ping' });
});

test('an ActionError-shaped error keeps its code across a bundle boundary', async () => {
  // `instanceof` fails when two copies of protocol.ts are loaded — the test
  // build, or an editor still holding an older extension instance. A foreign
  // but well-formed error must still reach the daemon with its real code
  // rather than being flattened to INTERNAL.
  const socket = new FakeSocket();
  const { transport } = makeTransport(socket, {
    onRequest: async () => {
      const foreign = new Error('no such action');
      foreign.name = 'ActionError';
      foreign.code = 'NOT_IMPLEMENTED';
      throw foreign;
    },
  });
  await transport.start();
  socket.connect();
  await socket.deliver({ id: 'r4', action: 'board.explode' });

  assert.equal(socket.lastFrame().error.code, 'NOT_IMPLEMENTED');
  transport.stop();
});

test('hello announces the connector build, and omits it when there is none', async () => {
  // 004f item 5: every connection should say which build made it, so a
  // sideload that did not take is answerable from the audit log afterwards.
  const socket = new FakeSocket();
  const { transport } = makeTransport(socket, { connectorVersion: '0.4.1' });
  await transport.start();
  socket.connect();

  assert.equal(socket.lastFrame().params.connectorVersion, '0.4.1');
  transport.stop();

  // An older build says nothing at all, and must not be padded with a guess —
  // the daemon records that absence as "(version unknown)".
  const bare = new FakeSocket();
  const { transport: older } = makeTransport(bare);
  await older.start();
  bare.connect();

  assert.equal('connectorVersion' in bare.lastFrame().params, false);
  older.stop();
});


test('hello announces the instance id, and omits it when there is none', async () => {
  // 018 §A: the daemon refuses a second *live* connector instance, so it has to
  // be told which instance is coming back. The value is the extension's, not
  // the connection's — `index.ts` generates it once per module evaluation — so
  // the transport only carries what it is handed.
  const socket = new FakeSocket();
  const { transport } = makeTransport(socket, { instanceId: 'inst-112233445-ab12cd34' });
  await transport.start();
  socket.connect();

  assert.equal(socket.lastFrame().params.instanceId, 'inst-112233445-ab12cd34');
  transport.stop();

  // A build that does not have one still connects: the daemon falls back to its
  // connection-level uuid, which is weaker but not a guess.
  const bare = new FakeSocket();
  const { transport: anonymous } = makeTransport(bare);
  await anonymous.start();
  bare.connect();

  assert.equal('instanceId' in bare.lastFrame().params, false);
  anonymous.stop();
});
