/**
 * 123: `pcb.drc_ruleset` — the DRC rule set in force on the focused board.
 *
 * A PCB DRC result is a statement about a rule set: the same geometry passes
 * under one clearance and fails under another, so `pcb.drc_check`'s leaves are
 * half an answer on their own. This action reads the other half off `pcb_Drc`'s
 * read-side members.
 *
 * What is pinned here, and why each one:
 *
 * 1. **The call set** — the four read-side members, and nothing else. The
 *    namespace also carries `saveRuleConfiguration`,
 *    `overwriteCurrentRuleConfiguration`, `overwriteNetRules`,
 *    `createRuleConfiguration`, `deleteRuleConfiguration`,
 *    `renameRuleConfiguration`, `setAsDefault`, `startRealTimeDrc` /
 *    `stopRealTimeDrc` and a whole net-class / pad-pair / differential-pair
 *    family; every one of those is a write or an editor-state change, and a rule
 *    set is precisely the thing whose content decides what a DRC *means*, so the
 *    test's fake is built to fail loudly if one is ever reached.
 * 2. **The values cross verbatim** — sanitising is only allowed to remove what
 *    JSON cannot carry: functions, and cycles. A `Date` is rendered through the
 *    host's own `toJSON` rather than blanked, and a getter that throws is
 *    reported rather than silently turning into a missing key.
 * 3. **The focus discipline is `pcb.drc_check`'s** — a non-PCB focus is refused
 *    with `PAGE_MISMATCH` and the focused document named, and **no `doc.open` is
 *    issued**: opening the board is the caller's job (025's recorded boundary).
 * 4. **"Could not read" never reads as "there is nothing there"** — an absent
 *    member lands in `missing`, a throwing one in `unreadable`, and a board that
 *    answers none of them is an outright `CONNECTOR_ERROR`.
 *
 * These are all offline tests against a fake `eda`. What the host's rule set
 * actually contains is a live question, answered on the machine by
 * `outputs/123/` — not here.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { buildHandlers } from '../dist/esm/actions.mjs';

/**
 * Every write / editor-state member of `pcb_Drc`, kept as a tripwire: the fake
 * installs a spy for each, and any call to one fails the test by name.
 */
const FORBIDDEN_WRITES = [
  'saveRuleConfiguration',
  'overwriteCurrentRuleConfiguration',
  'overwriteNetRules',
  'overwriteNetByNetRules',
  'overwriteRegionRules',
  'createRuleConfiguration',
  'deleteRuleConfiguration',
  'renameRuleConfiguration',
  'setRuleConfigurationAsDefault',
  'setAsDefault',
  'startRealTimeDrc',
  'stopRealTimeDrc',
  'createNetClass',
  'deleteNetClass',
  'addNetToNetClass',
  'removeNetFromNetClass',
  'renameNetClass',
  'createPadPairGroup',
  'deletePadPairGroup',
  'addPadPairToPadPairGroup',
  'createDifferentialPair',
  'deleteDifferentialPair',
  'createEqualLengthNetGroup',
  'deleteEqualLengthNetGroup',
  'modifyPrimitive',
  'delete',
];

/** A rule set in the shape the four reads are expected to hand back. */
function ruleSet() {
  return {
    name: 'Default',
    clearance: { copperToCopper: 0.2, copperToHole: 0.25 },
    width: { min: 0.15, preferred: 0.25 },
    holeSize: { min: 0.2, max: 6.0 },
    layerPairs: [
      { layer1: 'TopLayer', layer2: 'BottomLayer', clearance: 0.2 },
    ],
    updatedAt: new Date(1_700_000_000_000),
  };
}

function fakeEda(overrides = {}) {
  const calls = { reads: [], writes: [] };
  const drc = {
    getCurrentRuleConfigurationName: async () => {
      calls.reads.push('getCurrentRuleConfigurationName');
      return '默认规则';
    },
    getCurrentRuleConfiguration: async () => {
      calls.reads.push('getCurrentRuleConfiguration');
      return ruleSet();
    },
    getDefaultRuleConfigurationName: async () => {
      calls.reads.push('getDefaultRuleConfigurationName');
      return '默认规则';
    },
    getRealTimeDrcStatus: async () => {
      calls.reads.push('getRealTimeDrcStatus');
      return false;
    },
    getAllRuleConfigurations: async () => {
      calls.reads.push('getAllRuleConfigurations');
      return ['默认规则', '高压规则'];
    },
  };
  for (const name of FORBIDDEN_WRITES) {
    drc[name] = async (...args) => {
      calls.writes.push([name, args]);
      throw new Error(`forbidden write reached the host: ${name}`);
    };
  }
  const eda = {
    dmt_SelectControl: {
      getCurrentDocumentInfo: async () => ({ uuid: '5dc38976c1fa45ce', name: 'PCB1', documentType: 3 }),
    },
    pcb_Drc: drc,
    ...overrides,
  };
  return { eda, calls };
}

const read = (eda, params = {}) => buildHandlers(eda)['pcb.drc_ruleset'](params);

test('pcb.drc_ruleset is registered and reads exactly the four read-side members', async () => {
  const { eda, calls } = fakeEda();
  const report = await read(eda);

  assert.deepEqual(
    calls.reads,
    [
      'getCurrentRuleConfigurationName',
      'getCurrentRuleConfiguration',
      'getDefaultRuleConfigurationName',
      'getRealTimeDrcStatus',
    ],
    'the read order is the answer\'s own key order, so a caller reading the JSON can follow it',
  );
  assert.equal(report.source, 'pcb_Drc');
  assert.equal(report.readOnly, true);
  assert.deepEqual(report.page, { uuid: '5dc38976c1fa45ce', type: 'pcb' });
  assert.equal(report.ruleset.currentName, '默认规则');
  assert.equal(report.ruleset.defaultName, '默认规则');
  assert.equal(report.ruleset.realTimeDrcStatus, false);
  assert.equal(report.ruleset.current.clearance.copperToCopper, 0.2);
  assert.ok(typeof report.elapsedMs === 'number');
  // Every read is accounted for in `reads`, so a member that stayed silent is
  // visible without diffing two objects by hand.
  assert.deepEqual(
    report.reads.map((entry) => [entry.key, entry.read]),
    [
      ['currentName', true],
      ['current', true],
      ['defaultName', true],
      ['realTimeDrcStatus', true],
    ],
  );
  assert.ok(report.reads.every((entry) => entry.path.startsWith('pcb_Drc.')));
});

test('pcb.drc_ruleset asks for the whole catalogue only when told, and all:true includes it', async () => {
  const off = fakeEda();
  const without = await read(off.eda);
  assert.ok(!off.calls.reads.includes('getAllRuleConfigurations'), 'the default is about this board');
  assert.equal(without.ruleset.allConfigurations, undefined);

  const on = fakeEda();
  const withAll = await read(on.eda, { all: true });
  assert.ok(on.calls.reads.includes('getAllRuleConfigurations'));
  assert.deepEqual(withAll.ruleset.allConfigurations, ['默认规则', '高压规则']);
  assert.equal(withAll.missing.length, 0);
});

test('pcb.drc_ruleset refuses a non-PCB focus with PAGE_MISMATCH and names the document', async () => {
  // 025's recorded boundary: the action does not open a board, because a rule
  // set read from the wrong tab would be indistinguishable from "no rules".
  const { eda, calls } = fakeEda({
    dmt_SelectControl: {
      getCurrentDocumentInfo: async () => ({ uuid: 'b4298962367251c8', name: 'P1', documentType: 1 }),
    },
  });
  await assert.rejects(() => read(eda), (error) => {
    assert.equal(error.code, 'PAGE_MISMATCH');
    assert.match(error.message, /b4298962367251c8 \(page\)/);
    assert.match(error.message, /doc\.open/);
    assert.equal(error.detail.expected, 'pcb');
    return true;
  });
  assert.deepEqual(calls.reads, [], 'no host read happened, so no write could either');
});

test('pcb.drc_ruleset refuses when no document is focused, and says which answer that is', async () => {
  const { eda, calls } = fakeEda({
    dmt_SelectControl: {
      getCurrentDocumentInfo: async () => ({ uuid: '0', name: '', documentType: -1 }),
    },
  });
  await assert.rejects(() => read(eda), (error) => {
    assert.equal(error.code, 'PAGE_MISMATCH');
    assert.match(error.message, /not a PCB/);
    return true;
  });
  assert.deepEqual(calls.reads, []);
});

test('pcb.drc_ruleset never reaches a write, and the fake fails loudly if one is', async () => {
  const { eda, calls } = fakeEda();
  await read(eda, { all: true });
  assert.deepEqual(calls.writes, [], 'only the read-side members are on the list');
});

test('pcb.drc_ruleset carries the values verbatim, including a Date as the instant it is', async () => {
  const { eda } = fakeEda();
  const report = await read(eda);

  const current = report.ruleset.current;
  assert.equal(current.name, 'Default');
  assert.deepEqual(current.width, { min: 0.15, preferred: 0.25 });
  // A Date through the host's own serialiser, not `{}` and not a raw object.
  assert.equal(current.updatedAt, '2023-11-14T22:13:20.000Z');
  assert.equal(typeof current.updatedAt, 'string');
  // `realTimeDrcStatus: false` must survive as a falsy value rather than being
  // dropped by a truthiness filter — "no" and "not asked" are different.
  assert.equal(report.ruleset.realTimeDrcStatus, false);
});

test('pcb.drc_ruleset strips the functions that make an editor object graph cyclic, and counts them', async () => {
  const cyclic = ruleSet();
  cyclic.owner = { name: 'board', backToRoot: cyclic };
  cyclic.read = () => 'a method, not a rule value';
  const { eda } = fakeEda({
    pcb_Drc: {
      getCurrentRuleConfigurationName: async () => '默认规则',
      getCurrentRuleConfiguration: async () => cyclic,
      getDefaultRuleConfigurationName: async () => '默认规则',
      getRealTimeDrcStatus: async () => false,
    },
  });
  const report = await read(eda);

  const current = report.ruleset.current;
  assert.equal(current.clearance.copperToCopper, 0.2, 'the rule values are untouched');
  assert.equal(current.read, undefined, 'a method is not a rule value');
  assert.equal(current.owner.name, 'board');
  // The cycle is cut where it would re-enter, not by dropping the branch: a
  // reader must be able to see that something was there.
  assert.equal(current.owner.backToRoot, '(cycle)');
  assert.ok(
    report.notes.some((note) => /sanitised out/.test(note)),
    `expected the cuts to be named, got ${JSON.stringify(report.notes)}`,
  );
});

test('pcb.drc_ruleset reports an absent member as absent, never as an empty value', async () => {
  // An older editor build has one reader fewer. That is an absent *channel*, and
  // the difference from "this board has no default rule set" is the difference
  // between a degraded reading and a wrong one.
  const { eda } = fakeEda({
    pcb_Drc: {
      getCurrentRuleConfigurationName: async () => '默认规则',
      getCurrentRuleConfiguration: async () => ruleSet(),
      getDefaultRuleConfigurationName: async () => '默认规则',
    },
  });
  const report = await read(eda);

  assert.equal(report.ruleset.realTimeDrcStatus, undefined, 'nothing invented for the missing reader');
  assert.deepEqual(report.missing, ['pcb_Drc.getRealTimeDrcStatus']);
  assert.equal(report.reads.find((entry) => entry.key === 'realTimeDrcStatus').read, false);
  assert.ok(report.notes.some((note) => /has no pcb_Drc\.getRealTimeDrcStatus/.test(note)));
  // The reads that did answer are still a real answer.
  assert.equal(report.ruleset.current.width.min, 0.15);
});

test('pcb.drc_ruleset keeps one throwing read from swallowing the other three', async () => {
  const { eda } = fakeEda({
    pcb_Drc: {
      getCurrentRuleConfigurationName: async () => '默认规则',
      getCurrentRuleConfiguration: async () => {
        throw new Error('规则集正在被另一个操作修改');
      },
      getDefaultRuleConfigurationName: async () => '默认规则',
      getRealTimeDrcStatus: async () => true,
    },
  });
  const report = await read(eda);

  assert.equal(report.ruleset.current, undefined);
  assert.equal(report.ruleset.currentName, '默认规则');
  assert.equal(report.ruleset.realTimeDrcStatus, true);
  assert.deepEqual(report.unreadable.length, 1);
  assert.match(report.unreadable[0], /current: .*规则集正在被另一个操作修改/);
});

test('pcb.drc_ruleset records a read that answered undefined as null, with its key present', async () => {
  // Measured live 2026-10-06 on test/PCB1 (connector 0.4.29): the host resolves
  // `getDefaultRuleConfigurationName()` to nothing, because this board's rule set
  // is not the factory default. Omitting the key would make that identical to
  // "this build has no such member", and those need different decisions.
  const { eda } = fakeEda({
    pcb_Drc: {
      getCurrentRuleConfigurationName: async () => 'JLCPCB Capability(Two Layers Board)',
      getCurrentRuleConfiguration: async () => ruleSet(),
      getDefaultRuleConfigurationName: async () => undefined,
      getRealTimeDrcStatus: async () => false,
    },
  });
  const report = await read(eda);

  assert.ok('defaultName' in report.ruleset, 'the key is present — the read happened');
  assert.equal(report.ruleset.defaultName, null, 'and it says the host named nothing');
  assert.deepEqual(report.missing, [], 'nothing was missing; the member answered nothing');
  assert.equal(report.reads.find((entry) => entry.key === 'defaultName').read, true);
});

test('pcb.drc_ruleset refuses to report a ruleset when not one of the reads answered', async () => {
  // The failure this guards is the reassuring one: an empty `current` would read
  // as "this board checks nothing", which is a claim, not a reading.
  const { eda } = fakeEda({
    pcb_Drc: {
      getCurrentRuleConfigurationName: async () => {
        throw new Error('canvas not ready');
      },
      getCurrentRuleConfiguration: async () => {
        throw new Error('canvas not ready');
      },
      getDefaultRuleConfigurationName: async () => {
        throw new Error('canvas not ready');
      },
      getRealTimeDrcStatus: async () => {
        throw new Error('canvas not ready');
      },
    },
  });
  await assert.rejects(() => read(eda), (error) => {
    assert.equal(error.code, 'CONNECTOR_ERROR');
    assert.match(error.message, /not a board with no rules/);
    assert.match(error.message, /5dc38976c1fa45ce \(pcb\)/);
    assert.match(error.detail.attempts.current.message, /canvas not ready/);
    return true;
  });
});

test('pcb.drc_ruleset refuses a maxChars outside its documented range, before reading', async () => {
  const { eda, calls } = fakeEda();
  for (const maxChars of [999, 4_000_001, 'lots', null]) {
    if (maxChars === null) continue;
    await assert.rejects(() => read(eda, { maxChars }), (error) => {
      assert.equal(error.code, 'BAD_REQUEST', JSON.stringify(maxChars));
      return true;
    });
  }
  assert.deepEqual(calls.reads, [], 'a refused parameter never reaches the editor');
});

test('pcb.drc_ruleset admits the documented parameter extremes', async () => {
  const atMax = await read(fakeEda().eda, { maxChars: 4_000_000 });
  assert.equal(atMax.ruleset.current.width.min, 0.15);
  const atMin = await read(fakeEda().eda, { maxChars: 1000 });
  assert.ok(atMin.jsonChars > 0);
});

test('pcb.drc_ruleset says so when the answer is over the character budget', async () => {
  const fat = ruleSet();
  fat.layerPairs = Array.from({ length: 400 }, (_, i) => ({
    layer1: `TopLayer-${i}`,
    layer2: `BottomLayer-${i}`,
    clearance: 0.2,
    note: 'x'.repeat(40),
  }));
  const { eda } = fakeEda({
    pcb_Drc: {
      getCurrentRuleConfigurationName: async () => '默认规则',
      getCurrentRuleConfiguration: async () => fat,
      getDefaultRuleConfigurationName: async () => '默认规则',
      getRealTimeDrcStatus: async () => false,
    },
  });
  const report = await read(eda, { maxChars: 1000 });

  assert.ok(report.jsonChars > 1000, 'the reading is whole even when it is over budget');
  assert.equal(
    report.ruleset.current.layerPairs.length,
    400,
    'a half rule set is not a rule set: the values are not clipped, only the budget is reported',
  );
  assert.ok(report.notes.some((note) => /maxChars=1000/.test(note)));
});

test('the catalogue, the handler registry and the docs table all list pcb.drc_ruleset', async () => {
  // The five touchpoints of adding an action, asserted here so this file fails
  // on its own if one of them drifts rather than only in CI's guard test.
  const { readFileSync } = await import('node:fs');
  const root = new URL('../../', import.meta.url);
  const text = (url) => readFileSync(new URL(url, root), 'utf8').replace(/\r\n/g, '\n');

  const protocol = text('src/boardwise/bridge/protocol.py');
  const actions = text('connector/src/actions.ts');
  const docs = text('docs/bridge.md');

  assert.match(protocol, /\n\s*name="pcb\.drc_ruleset",/);
  assert.match(protocol, /name="pcb\.drc_ruleset",[\s\S]{0,4000}?risk="read",/);
  assert.match(actions, /^\s*'pcb\.drc_ruleset': bind\(pcbDrcRuleset\),/m);
  assert.match(actions, /^\s*'pcb\.drc_ruleset': pcbDrcRuleset,/m);
  assert.match(docs, /^\| `pcb\.drc_ruleset` \| connector \| read \| connector \|/m);
});