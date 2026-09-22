/**
 * Version comparison, for the connector/daemon minimum-version negotiation
 * (018 §B3).
 *
 * The point of these tests is the *third* answer. A comparison that cannot be
 * made must not come back as `false` ("not older"), because that is exactly the
 * shape that reports an old connector as fine — and a bundle built without the
 * `__BOARDWISE_VERSION__` define reports the string `unknown`, which is a real
 * value in this codebase, not a missing one.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { compareVersions, isVersionOlder, parseVersion } from '../dist/esm/version.mjs';

test('a dotted version parses into numbers, and anything else does not', () => {
  assert.deepEqual(parseVersion('0.4.10'), [0, 4, 10]);
  assert.deepEqual(parseVersion(' 1.2 '), [1, 2]);
  assert.deepEqual(parseVersion('v3.2.186'), [3, 2, 186]);

  for (const bad of ['unknown', '', '1.2.3-rc1', '1..2', 'x.y', 42, null, undefined]) {
    assert.equal(parseVersion(bad), null, `${JSON.stringify(bad)} is not a version`);
  }
});

test('versions compare segment by segment, missing segments as zero', () => {
  assert.equal(compareVersions('0.4.10', '0.4.9'), 1, '10 beats 9 — not a string sort');
  assert.equal(compareVersions('0.4.9', '0.4.10'), -1);
  assert.equal(compareVersions('0.4.0', '0.4'), 0);
  assert.equal(compareVersions('1.0.0', '0.9.9'), 1);
  assert.equal(compareVersions('0.4.10', '0.4.10'), 0);
});

test('an unparsable side makes the comparison unanswerable, never false', () => {
  // `null` is the whole contract: the caller must distinguish "this build is
  // old" from "this build cannot say what it is".
  assert.equal(compareVersions('unknown', '0.4.10'), null);
  assert.equal(compareVersions('0.4.10', 'unknown'), null);
  assert.equal(isVersionOlder('unknown', '0.4.10'), null);
  assert.equal(isVersionOlder('0.4.10', ''), null);
});

test('isVersionOlder answers only what it can defend', () => {
  assert.equal(isVersionOlder('0.4.9', '0.4.10'), true);
  assert.equal(isVersionOlder('0.4.10', '0.4.10'), false, 'equal is not older');
  assert.equal(isVersionOlder('0.5.0', '0.4.10'), false);
  assert.equal(isVersionOlder('0.4', '0.4.0'), false);
});
