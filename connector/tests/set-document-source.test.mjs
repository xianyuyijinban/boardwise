/**
 * R1-3: `sys.set_document_source` — the write half of the document-source channel.
 *
 * 178b filed the hole and 179 measured it: the bridge can read a document's
 * source (`sys.get_document_source`) but nothing can write one, so whether
 * `doc.rename`'s measured `NOT_SUPPORTED` is repairable through the source was
 * unmeasurable — `sys.probe`'s `call` mode is a read-only allowlist, so no
 * probe could reach a write. The R1-3 ruling (2026-10-12) added the write
 * instead. It is a recon instrument for **scratch pages**, and these tests pin
 * the properties that make it safe to hand to a machine:
 *
 * 1. **Never unguarded** — `uuid` is required *and* must be the active
 *    document (179's `DOC_NOT_ACTIVE` shape); a mismatch is refused before the
 *    host is called at all, because `setDocumentSource(source)` takes the text
 *    and nothing else (arity 1) and would otherwise rewrite whatever is in
 *    front.
 * 2. **Dangerous tier** — the catalogue entry is `risk="dangerous"` and
 *    declares `confirm`, which is what makes the daemon refuse it without
 *    `params.confirm is True`. The connector never sees the flag, and the
 *    action is deliberately absent from `sys.probe`'s read-only allowlist so no
 *    write can be routed around the gate.
 * 3. **The host's own answer travels** — anything but `true` is a failure
 *    naming what the host said (the declaration's `false` = malformed source),
 *    never a quiet `ok: false`.
 * 4. **"The host said yes" is not "the document holds it"** — a `true` is read
 *    back and the answer says whether the text came back identical; a
 *    difference is reported, not judged, because a host that accepts a document
 *    may re-serialise it.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { buildHandlers } from '../dist/esm/actions.mjs';

const ROOT = new URL('../../', import.meta.url);
const PROTOCOL = new URL('src/boardwise/bridge/protocol.py', ROOT);
const ACTIONS_TS = new URL('connector/src/actions.ts', ROOT);

const SOURCE_TEXT = '{"type":"DOCHEAD"}||{"uuid":"page-2","name":"P22"}|';
const REWRITTEN = SOURCE_TEXT.replace('P22', 'P22renamed');

/**
 * A project with two pages, `page-2` active, plus the source read/write pair.
 *
 * `write` is the knob: `true` (the host applies the text), `false` (the
 * declaration's "malformed source" answer), `'throw'`. `readBack` drives what
 * the follow-up `getDocumentSource()` returns: the same text, a re-serialised
 * one, `null` (the host gives nothing back), or `'missing'` when the host has
 * no read at all. `focusAfterWrite` moves the focus during the write — the user
 * clicking another tab while a whole document is replaced.
 */
function projectEda({
  active = 'page-2',
  write = true,
  readBack = REWRITTEN,
  focusAfterWrite = null,
} = {}) {
  let focused = active;
  const calls = { writes: [], reads: 0, focusReads: 0 };
  const eda = {
    dmt_SelectControl: {
      getCurrentDocumentInfo: async () => {
        calls.focusReads += 1;
        if (!focused) return undefined;
        return { uuid: focused, documentType: 1 };
      },
    },
    dmt_Schematic: {
      getAllSchematicsInfo: async () => [{ uuid: 'sch-1', name: 'Schematic1' }],
      getAllSchematicPagesInfo: async () => [
        { uuid: 'page-1', name: 'P1', parentSchematicUuid: 'sch-1' },
        { uuid: 'page-2', name: 'P22', parentSchematicUuid: 'sch-1' },
      ],
    },
    dmt_Pcb: { getAllPcbsInfo: async () => [] },
    sys_FileManager: {
      async setDocumentSource(...args) {
        calls.writes.push(args);
        if (write === 'throw') throw new Error('the source channel is not writable here');
        if (focusAfterWrite !== null) focused = focusAfterWrite;
        return write;
      },
    },
  };
  if (readBack !== 'missing') {
    eda.sys_FileManager.getDocumentSource = async () => {
      calls.reads += 1;
      return readBack;
    };
  }
  return { eda, calls };
}

const write = (eda, params) => buildHandlers(eda)['sys.set_document_source'](params);
const valid = { source: REWRITTEN, uuid: 'page-2' };

async function refusal(promise) {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  assert.fail('expected the write to be refused');
}

// --------------------------------------------------------------------------
// the guard — the host is never called with an unaddressed whole document
// --------------------------------------------------------------------------

test('sys.set_document_source refuses a missing or empty source, before touching the host', async () => {
  const { eda, calls } = projectEda();
  for (const params of [
    { uuid: 'page-2' },
    { source: '', uuid: 'page-2' },
    { source: 42, uuid: 'page-2' },
  ]) {
    const error = await refusal(write(eda, params));
    assert.equal(error.code, 'BAD_REQUEST');
    assert.match(error.message, /params\.source/);
  }
  assert.deepEqual(calls.writes, []);
});

test('sys.set_document_source refuses without a uuid — the write is never unguarded', async () => {
  const { eda, calls } = projectEda();
  for (const params of [{ source: REWRITTEN }, { source: REWRITTEN, uuid: '  ' }]) {
    const error = await refusal(write(eda, params));
    assert.equal(error.code, 'BAD_REQUEST');
    assert.match(error.message, /params\.uuid/);
  }
  assert.deepEqual(calls.writes, []);
});

test('a uuid that is not the active document is DOC_NOT_ACTIVE, host untouched', async () => {
  const { eda, calls } = projectEda();
  const error = await refusal(write(eda, { source: REWRITTEN, uuid: 'page-1' }));
  assert.equal(error.code, 'DOC_NOT_ACTIVE');
  assert.equal(error.detail.uuid, 'page-1');
  assert.equal(error.detail.activeUuid, 'page-2');
  assert.match(error.message, /page-1/);
  assert.deepEqual(calls.writes, [], 'a refused uuid must never reach setDocumentSource');
});

test('no active document at all is a refusal too, not a write to whatever is in front', async () => {
  const { eda, calls } = projectEda({ active: null });
  const error = await refusal(write(eda, valid));
  assert.equal(error.code, 'DOC_NOT_ACTIVE');
  assert.equal(error.detail.activeUuid, null);
  assert.deepEqual(calls.writes, []);
});

// --------------------------------------------------------------------------
// the write itself
// --------------------------------------------------------------------------

test('the host is called with the text and nothing else, and a true is read back', async () => {
  const { eda, calls } = projectEda();
  const data = await write(eda, valid);
  assert.deepEqual(calls.writes, [[REWRITTEN]], 'setDocumentSource(source) — declared arity 1');
  assert.equal(calls.reads, 1, 'the write is verified by reading the document back');
  assert.equal(data.source, 'sys_FileManager.setDocumentSource');
  assert.equal(data.uuid, 'page-2');
  assert.equal(data.type, 'page');
  assert.equal(data.chars, REWRITTEN.length);
  assert.equal(data.hostAnswer, true);
  assert.equal(data.readBack, 'identical');
  assert.equal(data.readBackChars, REWRITTEN.length);
  assert.equal(data.notes, undefined, 'a clean write carries no notes');
});

test('a host that answers false is a failure naming its own answer, never ok: false', async () => {
  const { eda, calls } = projectEda({ write: false });
  const error = await refusal(write(eda, valid));
  assert.equal(error.code, 'CONNECTOR_ERROR');
  assert.match(error.message, /answered false/);
  assert.match(error.message, /malformed/);
  assert.equal(error.detail.hostAnswer, 'false');
  assert.equal(calls.reads, 0, 'a refused write is not read back — there is nothing to verify');
});

test('a host without the write call says so by name', async () => {
  const { eda } = projectEda();
  delete eda.sys_FileManager.setDocumentSource;
  const error = await refusal(write(eda, valid));
  assert.equal(error.code, 'NOT_IMPLEMENTED');
  assert.match(error.message, /sys_FileManager\.setDocumentSource/);
});

test('a write that threw carries the host\'s words and the gate the declaration names', async () => {
  const { eda } = projectEda({ write: 'throw' });
  const error = await refusal(write(eda, valid));
  assert.equal(error.code, 'CONNECTOR_ERROR');
  assert.match(error.message, /threw.*the source channel is not writable here/);
  assert.equal(error.detail.gate, null, 'the declaration attaches no permission gate to this call');
});

// --------------------------------------------------------------------------
// the read-back is a reading, not a verdict
// --------------------------------------------------------------------------

test('a re-serialised source is reported as a difference, not as a failed write', async () => {
  const { eda } = projectEda({ readBack: SOURCE_TEXT });
  const data = await write(eda, valid);
  assert.equal(data.readBack, 'differs');
  assert.equal(data.readBackChars, SOURCE_TEXT.length);
  assert.equal(data.hostAnswer, true, 'the host did accept the write; the difference is what was measured');
});

test('a host that will not read the text back leaves the effect unverified, not failed', async () => {
  const { eda } = projectEda({ readBack: null });
  const data = await write(eda, valid);
  assert.equal(data.readBack, 'unreadable');
  assert.equal(data.readBackChars, null);

  const missing = projectEda({ readBack: 'missing' }).eda;
  const dataMissing = await write(missing, valid);
  assert.equal(dataMissing.readBack, 'unreadable');
  assert.equal(dataMissing.hostAnswer, true);
});

test('a focus that moved during the write is named, because the text may have gone elsewhere', async () => {
  const { eda, calls } = projectEda({ focusAfterWrite: 'page-1' });
  const data = await write(eda, valid);
  assert.equal(calls.writes.length, 1);
  assert.ok(data.notes.some((note) => /active document changed while the write ran/.test(note)), data.notes);
  assert.equal(data.readBack, 'identical', 'the text landed on a document; which one is the open question');
});

// --------------------------------------------------------------------------
// the declaration the gate is keyed on
// --------------------------------------------------------------------------

/** The text block of one `Action(...)` entry of the Python catalogue. */
function catalogueBlock(name) {
  const source = readFileSync(PROTOCOL, 'utf8').replace(/\r\n/g, '\n');
  const start = source.indexOf(`name="${name}"`);
  assert.ok(start >= 0, `${name} is not in the ACTIONS catalogue`);
  const open = source.lastIndexOf('    Action(', start);
  const close = source.indexOf('\n    ),', start);
  assert.ok(open >= 0 && close > start, `${name}'s Action block could not be delimited`);
  return source.slice(open, close);
}

test('the dangerous tier requires confirm, and this action is in it', () => {
  // The gate lives on the daemon and is keyed on `risk`, not on the params
  // list (016) — so the declaration is the load-bearing part on this side: a
  // `dangerous` entry the daemon refuses must declare `confirm`, or the refusal
  // could never be lifted and the action would be permanently dead.
  const block = catalogueBlock('sys.set_document_source');
  assert.match(block, /\n\s*risk="dangerous"/, 'sys.set_document_source must be in the dangerous tier');
  assert.match(block, /\n\s*params=\([^)]*"confirm"/, 'a dangerous action must declare confirm');
});

test('the write is not on sys.probe\'s read-only allowlist', () => {
  // That allowlist exists so a probe cannot route around the daemon's
  // confirmation gate (a write registered there would be reachable with no
  // `confirm` at all). Its own docstring says it is a closed list of reads.
  const source = readFileSync(ACTIONS_TS, 'utf8').replace(/\r\n/g, '\n');
  const start = source.indexOf('const PROBE_CALL_ACTIONS');
  const end = source.indexOf('\n};', start);
  assert.ok(start >= 0 && end > start, 'PROBE_CALL_ACTIONS could not be delimited');
  assert.doesNotMatch(source.slice(start, end), /set_document_source/);
});

test('the handler is registered, so the daemon does not answer UNKNOWN_ACTION', () => {
  const handlers = buildHandlers(projectEda().eda);
  assert.equal(typeof handlers['sys.set_document_source'], 'function');
});
