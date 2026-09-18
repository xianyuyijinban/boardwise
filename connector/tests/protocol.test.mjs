import assert from 'node:assert/strict';
import test from 'node:test';

import {
  ActionError,
  EVENT_BANNER,
  PROTOCOL_VERSION,
  errorFrame,
  frameKind,
  parseFrame,
  requestFrame,
  responseFrame,
} from '../dist/esm/protocol.mjs';

test('requestFrame carries action, params and an id', () => {
  const frame = parseFrame(JSON.stringify(requestFrame('pcb.readback', { includePrimitives: true }, 'x1')));
  assert.deepEqual(frame, {
    id: 'x1',
    action: 'pcb.readback',
    params: { includePrimitives: true },
  });
});

test('requestFrame omits empty params and still gets an id', () => {
  const frame = parseFrame(JSON.stringify(requestFrame('ping')));
  assert.equal(frame.action, 'ping');
  assert.equal(frame.params, undefined);
  assert.ok(frame.id);
});

test('response and error frames use the shared envelope', () => {
  assert.deepEqual(parseFrame(JSON.stringify(responseFrame('a', { pong: true }))), {
    id: 'a',
    ok: true,
    data: { pong: true },
  });

  const failure = parseFrame(
    JSON.stringify(errorFrame('a', new ActionError('NOT_IMPLEMENTED', 'nope', { path: 'x' }))),
  );
  assert.equal(failure.ok, false);
  assert.equal(failure.error.code, 'NOT_IMPLEMENTED');
  assert.equal(failure.error.message, 'nope');
  assert.deepEqual(failure.error.detail, { path: 'x' });
});

test('parseFrame rejects anything that is not a JSON object', () => {
  for (const raw of ['', 'nope', '[]', '42', 'null']) {
    assert.throws(() => parseFrame(raw), /BAD_REQUEST|JSON object|not JSON/);
  }
});

test('protocol version is a major.minor string', () => {
  assert.match(PROTOCOL_VERSION, /^\d+\.\d+$/);
});

test('frameKind tells the three kinds apart, strongest key first', () => {
  // Mirrors `frame_kind` in the Python daemon; the two must agree or the
  // banner is read as a request and answered with BAD_REQUEST.
  assert.equal(frameKind({ id: 'a', action: 'ping' }), 'request');
  assert.equal(frameKind({ id: 'a', ok: true, data: {} }), 'response');
  assert.equal(frameKind({ event: EVENT_BANNER }), 'event');

  assert.equal(frameKind({ ok: false, event: EVENT_BANNER }), 'response');
  assert.equal(frameKind({ event: EVENT_BANNER, action: 'ping' }), 'event');
});

test('a banner parses as an event carrying no secret', () => {
  const frame = parseFrame(
    JSON.stringify({ event: EVENT_BANNER, data: { server: 'boardwise', protocol: '1.0', expect: 'hello' } }),
  );
  assert.equal(frameKind(frame), 'event');
  assert.equal(frame.event, EVENT_BANNER);
  assert.equal(frame.data.expect, 'hello');
  assert.equal('id' in frame, false);
  assert.equal('token' in frame, false);
});
