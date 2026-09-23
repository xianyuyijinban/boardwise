/**
 * 025 batch 1: the four new reads, against a fake `eda` built to the real API's
 * shape.
 *
 * What these tests are for: every one of the four actions talks to a host
 * method whose *declaration* and *behaviour* have disagreed on this machine
 * before (`sys_FileManager.getDocumentFile` is gated on a permission the
 * connector cannot read; `sch_Drc.check` promises a verbose array and answers
 * aggregate counts; `pcb_Drc.check` answers `undefined` when there is no PCB).
 * So the tests pin the three things a probe report can be wrong about:
 *
 * 1. **The call itself** — arguments in declaration order, and the defaults the
 *    editor's own UI uses (`userInterface: false`, or an unattended check would
 *    pop the bottom DRC panel on a machine nobody is watching).
 * 2. **Where the answer is kept** — the DRC tree and the count array cross the
 *    wire **verbatim**, because a mapping layer downstream has to read the shape
 *    the editor really produces, not the one this file guessed.
 * 3. **The failures, named** — a host `throw` and a host `undefined` are
 *    reported as themselves, with the focused document named, never flattened
 *    into "no findings".
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { buildHandlers } from '../dist/esm/actions.mjs';

/** A host `File` stand-in: only the three members the actions read. */
function fileLike(bytes, { name = 'ProPrj_test.epro2', type = 'application/zip' } = {}) {
  return {
    name,
    type,
    arrayBuffer: async () => new Uint8Array(bytes).buffer,
  };
}

/** Bytes that start with the ZIP magic, plus a little payload. */
const ZIP_BYTES = [0x50, 0x4b, 0x03, 0x04, 1, 2, 3, 4];

/** The focused-document read every one of the four actions consults. */
function focused(uuid = 'page-1', documentType = 1) {
  return { uuid, name: 'P1', documentType, tabId: 'tab-1' };
}

/**
 * A plausible `.epru`-shaped page: `header||body|` records, one per line.
 *
 * Long enough (≈1 kB) that the truncation path is exercised by a real length
 * rather than by a fixture that happens to be shorter than the budget.
 */
const SOURCE_TEXT = Array.from(
  { length: 20 },
  (_, i) => `{"type":"LINE","ticket":${i}}||{"id":["LINE",${i}],"x":${i}}|`,
).join('\n');

function fakeEda(overrides = {}) {
  const calls = { documentFile: [], documentSource: 0, schDrc: [], pcbDrc: [] };
  const eda = {
    dmt_SelectControl: {
      getCurrentDocumentInfo: async () => focused(),
    },
    sys_FileManager: {
      getDocumentFile: async (...args) => {
        calls.documentFile.push(args);
        return fileLike(ZIP_BYTES);
      },
      getDocumentSource: async () => {
        calls.documentSource += 1;
        return SOURCE_TEXT;
      },
    },
    sch_Drc: {
      check: async (...args) => {
        calls.schDrc.push(args);
        return [{ type: 'fatalError', count: 0 }, { type: 'error', count: 2 }, { type: 'warn', count: 3 }];
      },
    },
    pcb_Drc: {
      check: async (...args) => {
        calls.pcbDrc.push(args);
        return [
          {
            type: 'clearance',
            children: [
              { ruleName: 'Clearance', net: 'GND', pos: { x: 1, y: 2 }, explanation: 'too close', obj1: 'a', obj2: 'b', layer: 1 },
              { ruleName: 'Clearance', net: 'VCC', pos: { x: 3, y: 4 }, explanation: 'too close', obj1: 'c', obj2: 'd', layer: 2 },
            ],
          },
          { type: 'unrouted', children: [{ ruleName: 'Unrouted', net: 'SIG' }] },
        ];
      },
    },
    ...overrides,
  };
  return { eda, calls };
}

test('sys.get_document_file asks for epro2 by default and returns the bytes as base64', async () => {
  const { eda, calls } = fakeEda();
  const data = await buildHandlers(eda)['sys.get_document_file']({});

  // Declaration order: (fileName, password, fileType). An omitted optional is
  // passed as `undefined` rather than as '' — the host drops an argument it
  // dislikes without rejecting, so the shape of the call matters.
  assert.deepEqual(calls.documentFile, [[undefined, undefined, 'epro2']]);
  assert.equal(data.fileType, 'epro2');
  assert.equal(data.bytes, ZIP_BYTES.length);
  assert.equal(data.encoding, 'base64');
  assert.equal(data.name, 'ProPrj_test.epro2');
  assert.equal(data.isZip, true, 'the ZIP magic is reported, not assumed');
  assert.equal(data.note, undefined, 'a well-formed archive needs no note');
  // base64 of the four magic bytes: "UEsDBA..."
  assert.ok(data.data.startsWith('UEsD'), `unexpected base64 head: ${data.data}`);
});

test('sys.get_document_file passes fileName/password through and flags non-archive bytes', async () => {
  const { eda, calls } = fakeEda({
    sys_FileManager: {
      getDocumentFile: async (...args) => {
        calls.documentFile.push(args);
        return fileLike([0x7b, 0x22, 0x61], { name: 'not-a-zip.epro2', type: '' });
      },
    },
  });
  const data = await buildHandlers(eda)['sys.get_document_file']({
    fileName: 'boardwise.epro2',
    password: 'secret',
    fileType: 'epro',
  });

  assert.deepEqual(calls.documentFile, [['boardwise.epro2', 'secret', 'epro']]);
  assert.equal(data.isZip, false);
  assert.match(data.note, /not the ZIP magic/);
  assert.equal(data.mime, 'application/octet-stream', 'an empty host type falls back');
});

test('sys.get_document_file refuses an unknown fileType before calling the host', async () => {
  const { eda, calls } = fakeEda();
  const handler = buildHandlers(eda)['sys.get_document_file'];
  await assert.rejects(() => handler({ fileType: 'pdf' }), (error) => {
    assert.equal(error.code, 'BAD_REQUEST');
    assert.match(error.message, /epro2 or epro/);
    return true;
  });
  assert.deepEqual(calls.documentFile, [], 'nothing was forwarded to the editor');
});

test('sys.get_document_file reports a host refusal as a refusal, with the gates named', async () => {
  // The measured shape of the permission path: the declaration says a missing
  // grant throws *every time*, and the connector cannot read grants. So the
  // host's own words travel, and the possibility is named as a possibility.
  const { eda } = fakeEda({
    sys_FileManager: {
      getDocumentFile: async () => {
        throw new Error('no permission to export document');
      },
    },
  });
  await assert.rejects(() => buildHandlers(eda)['sys.get_document_file']({}), (error) => {
    assert.equal(error.code, 'CONNECTOR_ERROR');
    assert.match(error.message, /no permission to export document/);
    assert.match(error.message, /not knowable from here/);
    assert.equal(error.detail.thrown, true);
    assert.equal(error.detail.errorMessage, 'no permission to export document');
    assert.ok(error.detail.permissions.some((gate) => gate.includes('文件导出')));
    return true;
  });
});

test('sys.get_document_file treats a zero-byte file as a failure and names a missing method', async () => {
  const empty = fakeEda({
    sys_FileManager: { getDocumentFile: async () => fileLike([], { name: 'empty.epro2' }) },
  });
  await assert.rejects(() => buildHandlers(empty.eda)['sys.get_document_file']({}), (error) => {
    assert.equal(error.code, 'CONNECTOR_ERROR');
    assert.match(error.message, /zero-byte/);
    return true;
  });

  const gone = fakeEda({ sys_FileManager: {} });
  await assert.rejects(() => buildHandlers(gone.eda)['sys.get_document_file']({}), (error) => {
    assert.equal(error.code, 'NOT_IMPLEMENTED');
    assert.match(error.message, /sys_FileManager\.getDocumentFile/);
    return true;
  });
});

test('sys.get_document_source returns the text whole, and both ends when truncated', async () => {
  const { eda, calls } = fakeEda();
  const handler = buildHandlers(eda)['sys.get_document_source'];

  const whole = await handler({});
  assert.equal(calls.documentSource, 1);
  assert.equal(whole.truncated, false);
  assert.equal(whole.tail, undefined, 'no tail when nothing was cut');
  assert.equal(whole.chars, whole.data.length);
  assert.ok(whole.data.startsWith('{"type":"LINE"'));
  assert.equal(whole.headLines, 19, '19 separators, 20 records');

  const cut = await handler({ maxChars: 256 });
  assert.equal(cut.truncated, true);
  assert.equal(cut.data.length, 256);
  assert.equal(cut.chars, SOURCE_TEXT.length, 'the full length is still reported');
  assert.ok(cut.tail.endsWith('|'), 'the tail is the end of the stream');
  assert.match(cut.note, /truncated to the first 256/);
});

test('sys.get_document_source refuses a maxChars outside its band and reports undefined honestly', async () => {
  const { eda } = fakeEda();
  const handler = buildHandlers(eda)['sys.get_document_source'];
  await assert.rejects(() => handler({ maxChars: 10 }), (error) => {
    assert.equal(error.code, 'BAD_REQUEST');
    assert.match(error.message, /between 256 and 4000000/);
    return true;
  });

  // `undefined` is documented (no document open / the read failed) and must not
  // become an empty string: an equivalence check would happily compare one.
  const missing = fakeEda({ sys_FileManager: { getDocumentSource: async () => undefined } });
  await assert.rejects(() => buildHandlers(missing.eda)['sys.get_document_source']({}), (error) => {
    assert.equal(error.code, 'CONNECTOR_ERROR');
    assert.match(error.message, /returned undefined/);
    assert.equal(error.detail.kind, 'undefined');
    return true;
  });
});

test('sch.drc_check returns the count array verbatim with the UI off by default', async () => {
  const { eda, calls } = fakeEda();
  const data = await buildHandlers(eda)['sch.drc_check']({});

  assert.deepEqual(calls.schDrc, [[true, false, true]], 'strict, no UI, verbose');
  assert.deepEqual(data.counts, [
    { type: 'fatalError', count: 0 },
    { type: 'error', count: 2 },
    { type: 'warn', count: 3 },
  ], 'the host array is passed through unchanged');
  assert.equal(data.mode, 'counts');
  assert.equal(data.total, 5);
  assert.deepEqual(data.byType, { fatalError: 0, error: 2, warn: 3 });
  assert.equal(data.passed, false);
  assert.equal(data.uiRequested, false);
  assert.equal(typeof data.elapsedMs, 'number');
});

test('sch.drc_check honours explicit arguments and refuses to fold an unparsable entry into zero', async () => {
  const { eda, calls } = fakeEda({
    sch_Drc: {
      check: async (...args) => {
        calls.schDrc.push(args);
        return [{ type: 'warn', count: 1 }, { type: 'error' }];
      },
    },
  });
  const data = await buildHandlers(eda)['sch.drc_check']({
    strict: false,
    userInterface: true,
    includeVerboseError: false,
  });

  assert.deepEqual(calls.schDrc, [[false, true, false]]);
  assert.equal(data.total, 1, 'an entry with no numeric count adds nothing');
  assert.equal(data.unparsed, 1);
  assert.equal(data.passed, false, 'one warning is not zero findings');
});

test('sch.drc_check reports a boolean answer as a boolean, not as an empty result', async () => {
  const { eda } = fakeEda({ sch_Drc: { check: async () => true } });
  const data = await buildHandlers(eda)['sch.drc_check']({});

  assert.equal(data.mode, 'boolean');
  assert.equal(data.counts, null);
  assert.equal(data.passed, true);
  assert.match(data.note, /does not hand back per-kind counts/);
});

test('sch.drc_check names the focused document when the host throws', async () => {
  // The measured failure on this host: the call is only meaningful on a
  // schematic page, and a refusal has to say which page it was looking at.
  const { eda } = fakeEda({
    dmt_SelectControl: { getCurrentDocumentInfo: async () => focused('pcb-1', 3) },
    sch_Drc: {
      check: async () => {
        throw new Error('not a schematic page');
      },
    },
  });
  await assert.rejects(() => buildHandlers(eda)['sch.drc_check']({}), (error) => {
    assert.equal(error.code, 'CONNECTOR_ERROR');
    assert.match(error.message, /not a schematic page/);
    assert.match(error.message, /pcb-1 \(pcb\)/);
    assert.equal(error.detail.focused.uuid, 'pcb-1');
    assert.equal(error.detail.thrown, true);
    assert.deepEqual(error.detail.args, { strict: true, userInterface: false, includeVerboseError: true });
    return true;
  });
});

test('pcb.drc_check returns the host tree verbatim and counts what it describes', async () => {
  const { eda, calls } = fakeEda();
  const data = await buildHandlers(eda)['pcb.drc_check']({});

  assert.deepEqual(calls.pcbDrc, [[true, false, true]]);
  assert.equal(data.checked, true);
  assert.equal(data.available, true);
  assert.equal(data.mode, 'groups');
  assert.equal(data.groups.length, 2);
  // Verbatim: the leaf keeps the fields the editor put there, so the batch-3
  // mapping layer reads the real shape (ruleName/net/pos/explanation/obj1/obj2/layer).
  assert.deepEqual(data.groups[0].children[0], {
    ruleName: 'Clearance', net: 'GND', pos: { x: 1, y: 2 }, explanation: 'too close',
    obj1: 'a', obj2: 'b', layer: 1,
  });
  assert.equal(data.counts.groups, 2);
  assert.equal(data.counts.returnedGroups, 2);
  assert.equal(data.counts.items, 3);
  assert.equal(data.counts.byLabel.Clearance, 2);
  assert.equal(data.truncated, false);
});

test('pcb.drc_check reads the tree the host really sends (measured 2026-09-23)', async () => {
  // Recorded verbatim from `pcb_Drc.check(true,false,true)` on the test project's
  // empty PCB (`outputs/025_probe_p4_pcb_drc.txt`): group -> list -> sub-group ->
  // list -> leaf, every node stating its own `count`, and the leaf carrying
  // `objs: ['err0']` *and* `title: [...]` arrays of its own. A tally that follows
  // every array-valued field reports 0 items next to a group whose count says 1.
  const measured = [
    {
      name: 'Netlist Error',
      list: [
        {
          name: 'Netlist Error',
          list: [
            {
              visible: true,
              errorType: 'Netlist Error',
              errorObjType: 'Netlist Error',
              ruleName: 'Import Changes',
              ruleTypeName: 'Import Changes',
              obj1: { typeName: 'Schematic Netlist', suffix: '' },
              obj2: { typeName: 'PCB Netlist', suffix: '' },
              objs: ['err0'],
              explanation: {
                str: 'PCB and schematic netlist does not match.',
                param: {},
              },
              globalIndex: 'err0',
              parentId: 'DRCTab|_|Errors|_|Netlist Error|_|Netlist Error',
            },
          ],
          count: 1,
          title: ['Netlist Error', '(1)'],
          visible: true,
        },
      ],
      visible: true,
      count: 1,
      title: ['Netlist Error', '(1)'],
    },
  ];
  const { eda } = fakeEda({ pcb_Drc: { check: async () => measured } });
  const data = await buildHandlers(eda)['pcb.drc_check']({});

  assert.equal(data.counts.errors, 1, 'the group states its own count; that is the total');
  assert.equal(data.counts.errorsSource, 'group-count');
  assert.equal(data.counts.items, 1, 'the walk agrees with the host, not with zero');
  assert.deepEqual(data.counts.byLabel, { 'Import Changes': 1 });
  // Verbatim: the mapping layer must be able to read `explanation.str`,
  // `globalIndex` and `parentId`, which only the real shape carries.
  assert.deepEqual(data.groups, measured);
  assert.equal(data.groups[0].list[0].list[0].explanation.str, 'PCB and schematic netlist does not match.');
});

test('pcb.drc_check reports the host throw a non-PCB page really produces', async () => {
  // Measured 2026-09-23: on a *schematic* page the host does **not** answer the
  // declared `undefined` — it throws a message-bus error, because the check
  // publishes to the PCB canvas topic and nothing there subscribes. The message
  // already begins with its own error name, so the report must not say it twice.
  const { eda } = fakeEda({
    dmt_SelectControl: { getCurrentDocumentInfo: async () => focused('page-1', 1) },
    pcb_Drc: {
      check: async () => {
        throw new Error('Error: 指定的主题消息在对应的画布内没有相关订阅');
      },
    },
  });
  await assert.rejects(() => buildHandlers(eda)['pcb.drc_check']({}), (error) => {
    assert.equal(error.code, 'CONNECTOR_ERROR');
    assert.match(error.message, /指定的主题消息在对应的画布内没有相关订阅/);
    assert.ok(!error.message.includes('Error: Error:'), `name said twice: ${error.message}`);
    assert.match(error.message, /page-1 \(page\)/);
    assert.equal(error.detail.thrown, true);
    return true;
  });
});

test('pcb.drc_check drops whole groups to fit maxChars and says how many', async () => {
  const { eda } = fakeEda({
    pcb_Drc: {
      check: async () => [
        {
          type: 'clearance',
          children: [{ ruleName: 'Clearance', net: 'GND', explanation: 'x'.repeat(900) }],
        },
        {
          type: 'unrouted',
          children: [{ ruleName: 'Unrouted', net: 'SIG', explanation: 'y'.repeat(100) }],
        },
      ],
    },
  });
  // A budget that fits the first group plus its brackets (988 + 2), but not the
  // second (186 more).
  const data = await buildHandlers(eda)['pcb.drc_check']({ maxChars: 1000 });
  assert.equal(data.truncated, true);
  assert.equal(data.counts.groups, 2, 'the counts describe the whole answer');
  assert.equal(data.counts.returnedGroups, 1);
  assert.equal(data.counts.items, 2, 'the counts describe the whole answer, like `groups`');
  assert.match(data.notes.join(' '), /were dropped to keep the answer inside maxChars/);
});

test('pcb.drc_check never reports "no PCB to check" as a clean board', async () => {
  const { eda } = fakeEda({ pcb_Drc: { check: async () => undefined } });
  const data = await buildHandlers(eda)['pcb.drc_check']({});

  assert.equal(data.checked, false);
  assert.equal(data.available, false);
  assert.equal(data.groups, null);
  assert.equal(data.counts, null);
  assert.match(data.reason, /No check ran: this is not a board with zero errors/);
  assert.match(data.reason, /page-1 \(page\)/);
  assert.equal(data.passed, undefined, 'a check that did not run has no verdict');
});

test('pcb.drc_check reports a host throw with the focused document named', async () => {
  const { eda } = fakeEda({
    pcb_Drc: {
      check: async () => {
        throw new Error('nope');
      },
    },
  });
  await assert.rejects(() => buildHandlers(eda)['pcb.drc_check']({}), (error) => {
    assert.equal(error.code, 'CONNECTOR_ERROR');
    assert.match(error.message, /pcb_Drc\.check threw Error: nope/);
    assert.equal(error.detail.thrown, true);
    return true;
  });
});

test('sys.probe call mode dispatches exactly the allowlisted read-only actions', async () => {
  const { eda, calls } = fakeEda();
  const handlers = buildHandlers(eda);

  const frame = await handlers['sys.probe']({
    call: { action: 'sys.get_document_file', params: { fileType: 'epro2' } },
  });
  assert.equal(frame.call.action, 'sys.get_document_file');
  assert.equal(frame.call.result.isZip, true);
  assert.deepEqual(calls.documentFile, [[undefined, undefined, 'epro2']]);
  assert.equal(frame.call.result.bytes, ZIP_BYTES.length);

  // The channel's whole point: it runs the *registered* handler. If the two ever
  // drift, the probe would measure something other than what it claims.
  for (const name of ['sys.get_document_file', 'sys.get_document_source', 'sch.drc_check', 'pcb.drc_check']) {
    assert.ok(name in handlers, `${name} is not registered`);
  }

  // Closed list, and read-only: a write or create action must not be reachable
  // through here, because the daemon's confirmation gate is on the daemon's side
  // and this channel bypasses the daemon's catalogue, not its rules.
  await assert.rejects(
    () => handlers['sys.probe']({ call: { action: 'pcb.doc.new', params: {} } }),
    (error) => {
      assert.equal(error.code, 'BAD_REQUEST');
      assert.match(error.message, /only dispatches/);
      assert.match(error.message, /create gate/);
      return true;
    },
  );
  await assert.rejects(() => handlers['sys.probe']({ call: { action: 'nope' } }), (error) => {
    assert.equal(error.code, 'BAD_REQUEST');
    return true;
  });
  await assert.rejects(() => handlers['sys.probe']({ call: 'sys.get_document_file' }), (error) => {
    assert.equal(error.code, 'BAD_REQUEST');
    assert.match(error.message, /must be an object/);
    return true;
  });
});

test('sys.probe call mode propagates the called action error, code and all', async () => {
  const { eda } = fakeEda({
    sys_FileManager: {
      getDocumentFile: async () => {
        throw new Error('no permission');
      },
    },
  });
  await assert.rejects(
    () => buildHandlers(eda)['sys.probe']({ call: { action: 'sys.get_document_file' } }),
    (error) => {
      assert.equal(error.code, 'CONNECTOR_ERROR', 'the caller sees the refusal, not a wrapper');
      assert.equal(error.detail.thrown, true);
      return true;
    },
  );
});
