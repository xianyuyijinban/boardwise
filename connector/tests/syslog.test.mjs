/**
 * 111b: `sys.log_read` — the sys_Log panel, read as text.
 *
 * Why the action exists: `sch.drc_check` returns **counts**, not findings.
 * 025 §0 measured it on the machine — `sch_Drc.check(…, includeVerboseError: true)`
 * answers `[{type, count}]` and the per-item ERC text goes to the bottom panel,
 * which no `eda.*` member reads. 岳's panel showed 22 warn lines of full text on
 * 2026-10-04. `SYS_Log.sort()` is the published surface for that panel, so this
 * is the candidate path back to the text. **These tests are all offline** — they
 * prove the filtering, the refusals and the honesty of the truncation, not that
 * the host's ERC lines land in sys_Log. That is a live question and is left to
 * the operator.
 *
 * What is pinned here, and why each one:
 *
 * 1. **The call shape** — `sort()` with *no argument* when no `types` was asked
 *    for (the declaration's default is "every type"), one bare value for one
 *    type, an array for several. The host drops an argument it dislikes rather
 *    than rejecting it, so a wrong-shaped call comes back as a plausible wrong
 *    answer rather than an error.
 * 2. **The filters, in order** — `since` is applied to the line's own
 *    `timestamp`, `types` to its own `type`, `pattern` as a case-insensitive
 *    substring. `total` stays the **pre-filter** count, so a caller can see how
 *    much the answer left out.
 * 3. **The refusals are refusals** — an absent `sys_Log` is `NOT_IMPLEMENTED`,
 *    a typo'd type is `BAD_REQUEST`, and a non-array answer is a `CONNECTOR_ERROR`
 *    rather than an empty log. An empty log and a log this build cannot read are
 *    different facts, and only the first one is benign.
 * 4. **`message` is verbatim** — no trimming, no re-casing, no wrapping. A log
 *    line is evidence and has to stay quotable back at an engineer.
 * 5. **Truncation is told, never hidden** — a line that does not fit is dropped
 *    whole, never sliced, and `truncated` is true whenever anything was left out.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { buildHandlers } from '../dist/esm/actions.mjs';

/** A plausible `ISYS_LogLine` set, oldest first, as the panel would hold them. */
const LINES = [
  { timestamp: 1_700_000_000_000, type: 'info', message: '项目已打开' },
  { timestamp: 1_700_000_001_000, type: 'warn', message: "Net 'VCC' has no driver" },
  { timestamp: 1_700_000_002_000, type: 'warn', message: "Net 'GND' has no driver" },
  { timestamp: 1_700_000_003_000, type: 'error', message: 'ERC: 引脚冲突 U1.3' },
  { timestamp: 1_700_000_004_000, type: 'info', message: 'DRC done' },
];

/** The calls `sys_Log.sort` was handed, so the argument shape is observable. */
function fakeEda(overrides = {}) {
  const calls = { sort: [], exported: 0, cleared: 0, found: 0 };
  const eda = {
    sys_Log: {
      sort: async (...args) => {
        calls.sort.push(args);
        return LINES.map((line) => ({ ...line }));
      },
      export: async () => {
        calls.exported += 1;
      },
      clear: () => {
        calls.cleared += 1;
      },
      find: async () => {
        calls.found += 1;
        return [];
      },
    },
    ...overrides,
  };
  return { eda, calls };
}

const read = (eda, params = {}) => buildHandlers(eda)['sys.log_read'](params);

test('sys.log_read is registered, and asks for every type with no argument at all', async () => {
  const { eda, calls } = fakeEda();
  const report = await read(eda);

  // The declaration's "types omitted = every type" is reached by passing *no*
  // argument. An explicit `[]` is not a documented spelling of the same thing.
  assert.deepEqual(calls.sort, [[]]);
  assert.equal(report.source, 'sys_Log.sort');
  assert.equal(report.total, LINES.length);
  assert.equal(report.count, LINES.length);
  assert.equal(report.truncated, false);
  assert.equal(report.types, undefined, 'no types asked for, none echoed');
  assert.ok(typeof report.elapsedMs === 'number');
});

test('sys.log_read never calls export or clear, and leaves the panel alone', async () => {
  // `export` opens the editor's save dialog and `clear` destroys the evidence
  // this action exists to recover. Both are one line away and neither is called.
  const { eda, calls } = fakeEda();
  await read(eda, { pattern: 'driver' });
  await read(eda, { types: 'warn' });
  assert.equal(calls.exported, 0);
  assert.equal(calls.cleared, 0);
  assert.equal(calls.found, 0, 'find() is unused: sort + the client filter covers it');
});

test('sys.log_read passes one type bare and several as an array', async () => {
  const one = fakeEda();
  await read(one.eda, { types: 'warn' });
  assert.deepEqual(one.calls.sort, [['warn']], 'a lone type is the declaration\'s own shape');

  const many = fakeEda();
  await read(many.eda, { types: ['warn', 'error'] });
  assert.deepEqual(many.calls.sort, [[['warn', 'error']]]);

  // A single-element *array* from a caller stays a single-element array: the
  // bare form is what a string becomes, and collapsing further would be a guess.
  const arrayOfOne = fakeEda();
  await read(arrayOfOne.eda, { types: ['error'] });
  assert.deepEqual(arrayOfOne.calls.sort, [[['error']]]);
});

test('sys.log_read refuses a type the ESYS_LogType enum does not have, before calling the host', async () => {
  const { eda, calls } = fakeEda();
  await assert.rejects(() => read(eda, { types: 'warning' }), (error) => {
    assert.equal(error.code, 'BAD_REQUEST');
    assert.match(error.message, /fatalError/);
    return true;
  });
  await assert.rejects(() => read(eda, { types: ['info', 'oops'] }), (error) => {
    assert.equal(error.code, 'BAD_REQUEST');
    return true;
  });
  await assert.rejects(() => read(eda, { types: [] }), (error) => {
    assert.equal(error.code, 'BAD_REQUEST');
    assert.match(error.message, /omit it to read every type/);
    return true;
  });
  assert.deepEqual(calls.sort, [], 'nothing was forwarded — the host would drop it silently');
});

test('sys.log_read filters by since on the line own timestamp, inclusive', async () => {
  const { eda, calls } = fakeEda();
  const report = await read(eda, { since: 1_700_000_002_000 });

  assert.deepEqual(calls.sort, [[]], 'since is ours, not the host\'s argument');
  assert.equal(report.total, LINES.length, 'total is the pre-filter count');
  assert.equal(report.count, 3);
  assert.equal(report.since, 1_700_000_002_000);
  assert.deepEqual(
    report.lines.map((line) => line.timestamp),
    [1_700_000_002_000, 1_700_000_003_000, 1_700_000_004_000],
    'the boundary line is kept: the filter is `>=`',
  );
});

test('sys.log_read filters types and pattern together, case-insensitively', async () => {
  const { eda } = fakeEda();
  const report = await read(eda, { types: 'warn', pattern: 'HAS NO' });

  assert.equal(report.total, LINES.length);
  assert.equal(report.count, 2);
  assert.deepEqual(report.types, ['warn']);
  assert.deepEqual(
    report.lines.map((line) => line.message),
    ["Net 'VCC' has no driver", "Net 'GND' has no driver"],
  );
  // The pattern is echoed in the form it was matched in, so a reader can see
  // what the answer was filtered by without re-deriving the case.
  assert.equal(report.pattern, 'has no');
});

test('sys.log_read keeps every message verbatim, including the awkward ones', async () => {
  const awkward = [
    { timestamp: 1, type: 'warn', message: '  前后都有空格  ' },
    { timestamp: 2, type: 'warn', message: "line\twith\ttabs" },
    { timestamp: 3, type: 'warn', message: 'multi\nline message' },
    { timestamp: 4, type: 'warn', message: '' },
    { timestamp: 5, type: 'warn', message: '{braces} [brackets] "quotes"' },
  ];
  const { eda } = fakeEda({
    sys_Log: { sort: async () => awkward.map((line) => ({ ...line })) },
  });
  const report = await read(eda, { types: 'warn' });

  assert.deepEqual(
    report.lines.map((line) => line.message),
    awkward.map((line) => line.message),
    'no trimming, no re-casing, no re-wrapping, empty strings included',
  );
});

test('sys.log_read reports a missing sys_Log as NOT_IMPLEMENTED, not an empty log', async () => {
  // An older editor build has no `sys_Log`. That is an absent *channel*, and an
  // absent channel must never be reported as "the log is empty" — which is the
  // answer that would let a review conclude there was nothing to find.
  const { eda } = fakeEda({ sys_Log: {} });
  await assert.rejects(() => read(eda), (error) => {
    assert.equal(error.code, 'NOT_IMPLEMENTED');
    assert.match(error.message, /sys_Log\.sort\(\) is not available/);
    assert.equal(error.detail.path, 'sys_Log.sort');
    return true;
  });

  const bare = fakeEda({ sys_Log: undefined });
  await assert.rejects(() => read(bare.eda), (error) => {
    assert.equal(error.code, 'NOT_IMPLEMENTED');
    return true;
  });
});

test('sys.log_read reports a host refusal as a refusal, with its own words', async () => {
  const { eda } = fakeEda({
    sys_Log: {
      sort: async () => {
        throw new Error('log panel is not ready');
      },
    },
  });
  await assert.rejects(() => read(eda), (error) => {
    assert.equal(error.code, 'CONNECTOR_ERROR');
    assert.match(error.message, /log panel is not ready/);
    assert.match(error.message, /refusal of that text/);
    assert.equal(error.detail.thrown, true);
    assert.equal(error.detail.errorMessage, 'log panel is not ready');
    return true;
  });
});

test('sys.log_read never turns a non-array answer into an empty log', async () => {
  // `undefined` from a host that is not the shape the declaration promises is
  // the one answer that must not be read as "nothing was logged".
  for (const [label, value] of [['undefined', undefined], ['null', null], ['boolean', true]]) {
    const { eda } = fakeEda({ sys_Log: { sort: async () => value } });
    await assert.rejects(() => read(eda), (error) => {
      assert.equal(error.code, 'CONNECTOR_ERROR', label);
      assert.match(error.message, /instead of the declared array/);
      assert.match(error.message, /an empty log/);
      return true;
    });
  }
});

test('sys.log_read truncates at limit and says so, with total to measure the loss', async () => {
  const { eda } = fakeEda();
  const report = await read(eda, { limit: 2 });

  assert.equal(report.total, 5, 'total is what the host had');
  assert.equal(report.count, 2);
  assert.equal(report.truncated, true);
  assert.ok(
    report.notes.some((note) => /3 matching line\(s\) were left out by limit=2/.test(note)),
    `expected the loss to be named, got ${JSON.stringify(report.notes)}`,
  );
});

test('sys.log_read truncates at maxChars by dropping whole lines, never slicing one', async () => {
  const fat = [
    { timestamp: 1, type: 'warn', message: 'x'.repeat(400) },
    { timestamp: 2, type: 'warn', message: 'y'.repeat(400) },
    { timestamp: 3, type: 'warn', message: 'z'.repeat(400) },
  ];
  const { eda } = fakeEda({ sys_Log: { sort: async () => fat.map((line) => ({ ...line })) } });
  const report = await read(eda, { maxChars: 500 });

  assert.equal(report.total, 3);
  assert.ok(report.count < 3, 'something had to go');
  assert.equal(report.truncated, true);
  // A half-sentence in a log read is indistinguishable from a different line.
  for (const line of report.lines) {
    assert.match(line.message, /^(x+|y+|z+)$/, 'a line was cut in half');
  }
  assert.ok(report.notes.some((note) => /maxChars=500/.test(note)));
});

test('sys.log_read returns an oversized first line whole and admits it', async () => {
  // The opposite failure: refusing to return anything would be a second way of
  // losing the text. Return it, and say the answer is over budget.
  const { eda } = fakeEda({
    sys_Log: { sort: async () => [{ timestamp: 1, type: 'error', message: 'q'.repeat(3000) }] },
  });
  const report = await read(eda, { maxChars: 100 });

  assert.equal(report.count, 1);
  assert.equal(report.lines[0].message.length, 3000);
  assert.equal(report.truncated, false, 'nothing was left out — the answer is just big');
  assert.ok(report.notes.some((note) => /first line alone exceeds maxChars/.test(note)));
});

test('sys.log_read says an empty log is an empty log', async () => {
  const { eda } = fakeEda({ sys_Log: { sort: async () => [] } });
  const report = await read(eda);

  assert.deepEqual(report.lines, []);
  assert.equal(report.count, 0);
  assert.equal(report.total, 0);
  assert.equal(report.truncated, false, 'an empty log is not a truncation');
  assert.ok(report.notes.some((note) => /an empty log, reported as an empty log/.test(note)));
});

test('sys.log_read refuses a non-finite since, a non-string pattern and an out-of-range limit', async () => {
  const { eda, calls } = fakeEda();
  for (const params of [
    { since: 'yesterday' },
    { pattern: 42 },
    { limit: 0 },
    { limit: 5001 },
    { limit: 1.5 },
    { maxChars: 0 },
    { maxChars: 4_000_001 },
  ]) {
    await assert.rejects(() => read(eda, params), (error) => {
      assert.equal(error.code, 'BAD_REQUEST', JSON.stringify(params));
      return true;
    });
  }
  assert.deepEqual(calls.sort, [], 'a refused parameter never reaches the editor');
});

test('sys.log_read says when a line carried no timestamp and since left it out', async () => {
  // The declaration promises `timestamp: number` on every line, but a host that
  // breaks its own promise must not have the affected lines vanish silently —
  // "nothing that old is in the log" is exactly the wrong reading.
  const { eda } = fakeEda({
    sys_Log: {
      sort: async () => [
        { timestamp: 1_700_000_009_000, type: 'warn', message: 'recent' },
        { type: 'warn', message: 'no timestamp at all' },
      ],
    },
  });
  const report = await read(eda, { since: 1_700_000_000_000 });

  assert.equal(report.total, 2);
  assert.equal(report.count, 1);
  assert.ok(
    report.notes.some((note) => /no numeric timestamp/.test(note)),
    `expected the loss to be named, got ${JSON.stringify(report.notes)}`,
  );

  // Without `since` the same line comes through untouched — the filter is the
  // only thing that could drop it.
  const all = await read(fakeEda({
    sys_Log: { sort: async () => [{ type: 'warn', message: 'no timestamp at all' }] },
  }).eda);
  assert.equal(all.count, 1);
});

test('sys.log_read accepts the documented parameter extremes', async () => {
  const { eda } = fakeEda();
  const atMax = await read(eda, { limit: 5000, maxChars: 4_000_000, since: 0 });
  assert.equal(atMax.count, LINES.length);
  const atMin = await read(eda, { limit: 1, maxChars: 1 });
  assert.equal(atMin.count, 1, 'maxChars=1 keeps the first line whole');
});
