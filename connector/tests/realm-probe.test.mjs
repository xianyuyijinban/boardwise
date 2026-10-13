/**
 * R4 stage 1: `sys.probe {realm: true}` — can the extension realm execute a string?
 *
 * The roadmap's stub-plus-payload hot update depends on it, and nothing had
 * measured it. The probe is the instrument for experiments 1–2; what it must
 * never be is a channel for running code someone else sent. Pinned here:
 *
 * 1. the realm facts and the three execution paths come back as rows, and in
 *    this (Node) realm all three run the constant and return the sentinel;
 * 2. `realm` is a switch: any value but `true` is refused, so a caller cannot
 *    smuggle code through it, and other params are never executed;
 * 3. a realm that forbids evaluation is a reading, not a crash: each path that
 *    throws is reported with its error.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { buildHandlers } from '../dist/esm/actions.mjs';

const probe = (params) => buildHandlers({})['sys.probe'](params);

test('realm mode reports the globals and runs the three constant probes', async () => {
  const data = await probe({ realm: true });
  assert.equal(typeof data.connector, 'string');
  const { kinds, execution, note } = data.realm;
  for (const name of ['eval', 'Function', 'fetch', 'WebSocket', 'crypto.subtle']) {
    assert.ok(name in kinds, name);
  }
  assert.equal(kinds.Function, 'function');
  assert.deepEqual(execution.indirectEval, { ok: true, value: '42' });
  assert.deepEqual(execution.newFunction, { ok: true, value: '42' });
  assert.deepEqual(execution.dynamicImportDataUrl, { ok: true, value: '42' });
  assert.match(note, /nothing from params is executed/);
});

test('realm is a switch, and nothing passed alongside it is executed', async () => {
  for (const realm of ['6 * 7', 1, { code: 'globalThis.__r4 = 1' }, false]) {
    await assert.rejects(() => probe({ realm }), (error) => {
      assert.equal(error.code, 'BAD_REQUEST');
      assert.match(error.message, /no code is accepted/);
      return true;
    });
  }
  delete globalThis.__r4;
  await probe({ realm: true, code: 'globalThis.__r4 = 1', source: 'globalThis.__r4 = 1' });
  assert.equal(globalThis.__r4, undefined, 'extra params are data, never code');
});

test('a realm that forbids evaluation answers with the errors, not a crash', async () => {
  const saved = { eval: globalThis.eval, Function: globalThis.Function };
  try {
    globalThis.eval = () => {
      throw new EvalError('Refused to evaluate a string as JavaScript (CSP)');
    };
    globalThis.Function = function Forbidden() {
      throw new EvalError('Function constructor is disabled');
    };
    const { execution, kinds } = (await probe({ realm: true })).realm;
    assert.equal(kinds.eval, 'function');
    assert.equal(execution.indirectEval.ok, false);
    assert.match(execution.indirectEval.error, /^EvalError: Refused to evaluate/);
    assert.equal(execution.newFunction.ok, false);
    assert.match(execution.newFunction.error, /Function constructor is disabled/);
    assert.equal(execution.dynamicImportDataUrl.ok, false, 'reached through the Function constructor, so it is blocked too');
  } finally {
    globalThis.eval = saved.eval;
    globalThis.Function = saved.Function;
  }
});

test('a path that runs but answers something else is not ok', async () => {
  const saved = globalThis.eval;
  try {
    globalThis.eval = () => 'tampered';
    const { execution } = (await probe({ realm: true })).realm;
    assert.deepEqual(execution.indirectEval, { ok: false, value: 'tampered' }, 'ok means the sentinel came back');
  } finally {
    globalThis.eval = saved;
  }
});
