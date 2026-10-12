/**
 * 179: two actions that used to lie about what they had done.
 *
 * Both came out of the 178b probe against the live editor, and both are the
 * same failure in different clothes — the action answered *something* that
 * looked like an answer while the document it was asked about was never
 * touched:
 *
 * 1. `sys.get_document_source` took a `uuid` it never read. The host's
 *    `getDocumentSource()` takes **no arguments** (measured arity 0 on EDA
 *    3.2.186), so every call returned the *active* document's source. Asking
 *    for page A while page B was open returned B and said nothing.
 * 2. `doc.rename` returned `{renamed: false}` with exit 0 for a rename the host
 *    accepted, answered falsy for, and never applied — a caller reading the
 *    exit status saw a rename that never happened.
 *
 * The tests below pin the *contract*, not the host's current mood: a `uuid` the
 * host cannot read is refused and the host call is not made at all (so no wrong
 * document can reach the caller), and a rename that did not happen is an error
 * whose code names the fact that was observed — the host claimed success, the
 * host said no, the document left the listing, or the listing itself could not
 * be read (which is not the same fact, and is not reported as one).
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { buildHandlers } from '../dist/esm/actions.mjs';

const SOURCE_TEXT = '{"type":"DOCHEAD"}||{"uuid":"page-1"}|';

/** A host whose active document is `page-1`, with a source read that counts. */
function sourceEda({ active = { uuid: 'page-1', documentType: 1 }, source = SOURCE_TEXT } = {}) {
  const calls = { read: 0 };
  const eda = {
    dmt_SelectControl: { getCurrentDocumentInfo: async () => active },
    sys_FileManager: {
      getDocumentSource: async () => {
        calls.read += 1;
        return source;
      },
    },
  };
  return { eda, calls };
}

test('sys.get_document_source reads the active document when uuid is omitted', async () => {
  const { eda, calls } = sourceEda();
  const data = await buildHandlers(eda)['sys.get_document_source']({});
  assert.equal(calls.read, 1);
  assert.equal(data.data, SOURCE_TEXT);
});

test('sys.get_document_source reads the document it was named, and reads nothing else', async () => {
  const { eda, calls } = sourceEda();
  const data = await buildHandlers(eda)['sys.get_document_source']({ uuid: 'page-1' });
  assert.equal(calls.read, 1, 'the named document was the active one, so the read is the answer');
  assert.equal(data.data, SOURCE_TEXT);
});

test('sys.get_document_source refuses a uuid that is not the active document', async () => {
  // The 178b case: page-1 is active, the caller asked for page-2. Before this
  // guard the answer was page-1's source under page-2's name.
  const { eda, calls } = sourceEda();
  await assert.rejects(
    () => buildHandlers(eda)['sys.get_document_source']({ uuid: 'page-2' }),
    (error) => {
      assert.equal(error.code, 'DOC_NOT_ACTIVE');
      assert.match(error.message, /page-2/);
      assert.match(error.message, /page-1/);
      assert.match(error.message, /doc\.open/, 'the caller is told what would make it readable');
      assert.equal(error.detail.uuid, 'page-2');
      assert.equal(error.detail.activeUuid, 'page-1');
      assert.equal(error.detail.hostArity, 0, 'the reason is the host call taking no arguments');
      return true;
    },
  );
  assert.equal(calls.read, 0, 'the wrong document was never read');
});

test('sys.get_document_source refuses when no document is active at all', async () => {
  // `dmt_SelectControl` is gone, so "which document is active" cannot be
  // answered — and an unanswerable question is not a reason to hand back a
  // document the caller did not name.
  const { eda, calls } = sourceEda();
  delete eda.dmt_SelectControl;
  await assert.rejects(
    () => buildHandlers(eda)['sys.get_document_source']({ uuid: 'page-2' }),
    (error) => {
      assert.equal(error.code, 'DOC_NOT_ACTIVE');
      assert.equal(error.detail.activeUuid, null);
      return true;
    },
  );
  assert.equal(calls.read, 0);
});

test('sys.get_document_source keeps its maxChars band with a uuid in hand', async () => {
  const { eda } = sourceEda();
  const handler = buildHandlers(eda)['sys.get_document_source'];
  await assert.rejects(() => handler({ uuid: 'page-1', maxChars: 10 }), (error) => {
    assert.equal(error.code, 'BAD_REQUEST');
    return true;
  });
  const cut = await handler({ uuid: 'page-1', maxChars: 256 });
  assert.equal(cut.maxChars, 256);
  assert.equal(cut.data, SOURCE_TEXT);
});

// --------------------------------------------------------------------------
// doc.rename
// --------------------------------------------------------------------------

/**
 * What a host call returned, spelled as a string on purpose.
 *
 * `undefined` has to be *askable for*: as a plain option it would collide with
 * the destructuring default, and "the host said nothing" is exactly one of the
 * answers this file has to pin.
 */
const HOST_ANSWERS = { true: true, false: false, undefined: undefined, null: null };

/**
 * A project with one schematic, two pages and one PCB.
 *
 * The two knobs are the two ways a host can lie: `renameHonoured` (the rename
 * did/did not land) and `answer` (what the call returned) — because a host that
 * returns `true` and stores nothing and a host that returns `false` without
 * storing anything are different facts about the same editor.
 */
function renameEda({ renameHonoured = true, answer = 'true', vanish = false, listingBreaks = false } = {}) {
  const state = {
    schematics: [{ uuid: 'sch-1', name: 'Schematic1' }],
    pages: [
      { uuid: 'page-1', name: 'P1', parentSchematicUuid: 'sch-1' },
      { uuid: 'page-2', name: 'P2', parentSchematicUuid: 'sch-1' },
    ],
    pcbs: [{ uuid: 'pcb-1', name: 'PCB1' }],
    calls: [],
    listingReads: 0,
  };
  const eda = {
    dmt_Schematic: {
      getAllSchematicsInfo: async () => state.schematics,
      getAllSchematicPagesInfo: async () => {
        state.listingReads += 1;
        // The kind resolution reads the listing first; `listingBreaks` models a
        // host that answers that one and fails the *confirmation* read, which is
        // the case whose error message must not claim the document vanished.
        if (listingBreaks && state.listingReads > 1) throw new Error('listing blew up');
        return state.pages;
      },
      modifySchematicPageName: async (uuid, name) => {
        state.calls.push(`modifySchematicPageName:${uuid}:${name}`);
        if (vanish) {
          state.pages = state.pages.filter((row) => row.uuid !== uuid);
          return true;
        }
        if (renameHonoured) {
          const page = state.pages.find((row) => row.uuid === uuid);
          if (page) page.name = name;
        }
        return HOST_ANSWERS[answer];
      },
    },
    dmt_Pcb: { getAllPcbsInfo: async () => state.pcbs, modifyPcbName: async () => true },
  };
  return { eda, state };
}

test('doc.rename confirms a rename against the editor listing, not the call', async () => {
  const { eda, state } = renameEda();
  const data = await buildHandlers(eda)['doc.rename']({ uuid: 'page-1', name: 'First' });
  assert.equal(data.type, 'page');
  assert.equal(data.renamed, true);
  assert.equal(data.confirmed, true);
  assert.ok(state.calls.includes('modifySchematicPageName:page-1:First'));
});

test('doc.rename reports NOT_SUPPORTED when the host answers false and nothing changed', async () => {
  // The measured 178b shape: the declaration's own (uuid, name), arity 2, the
  // call present and answering `false` — and the name is exactly what it was.
  const { eda } = renameEda({ renameHonoured: false, answer: 'false' });
  await assert.rejects(
    () => buildHandlers(eda)['doc.rename']({ uuid: 'page-1', name: 'SCRATCH_179' }),
    (error) => {
      assert.equal(error.code, 'NOT_SUPPORTED');
      assert.match(error.message, /modifySchematicPageName/);
      assert.match(error.message, /still names it P1/);
      assert.equal(error.detail.hostAnswer, 'false');
      assert.equal(error.detail.actualName, 'P1');
      return true;
    },
  );
});

test('doc.rename reports NOT_SUPPORTED when the host answers undefined', async () => {
  const { eda } = renameEda({ renameHonoured: false, answer: 'undefined' });
  await assert.rejects(
    () => buildHandlers(eda)['doc.rename']({ uuid: 'page-1', name: 'X' }),
    (error) => {
      assert.equal(error.code, 'NOT_SUPPORTED');
      assert.equal(error.detail.hostAnswer, 'undefined');
      return true;
    },
  );
});

test('doc.rename keeps CONNECTOR_ERROR for a host that claims success and stores nothing', async () => {
  const { eda } = renameEda({ renameHonoured: false, answer: 'true' });
  await assert.rejects(
    () => buildHandlers(eda)['doc.rename']({ uuid: 'page-1', name: 'X' }),
    (error) => {
      assert.equal(error.code, 'CONNECTOR_ERROR');
      assert.match(error.message, /claimed success but the page is still named P1/);
      return true;
    },
  );
});

test('doc.rename believes the listing when the host under-reports its own work', async () => {
  // The reverse lie: the name did change and the call said `false`. The
  // verified fact wins, and `renamed` still reports what the host claimed, so
  // the two are never merged into one hopeful answer.
  const { eda } = renameEda({ renameHonoured: true, answer: 'false' });
  const data = await buildHandlers(eda)['doc.rename']({ uuid: 'page-1', name: 'First' });
  assert.equal(data.confirmed, true);
  assert.equal(data.renamed, false);
});

test('doc.rename refuses to confirm a document that left the listing', async () => {
  const { eda } = renameEda({ vanish: true });
  await assert.rejects(
    () => buildHandlers(eda)['doc.rename']({ uuid: 'page-1', name: 'X' }),
    (error) => {
      assert.equal(error.code, 'CONNECTOR_ERROR');
      assert.match(error.message, /no longer/);
      assert.equal(error.detail.actualName, null);
      return true;
    },
  );
});

test('doc.rename names a failed listing read as one, never as "the document is gone"', async () => {
  // "cannot confirm" is one answer to two different facts, and the message has
  // to carry the one that happened: a host that could not be read must not be
  // reported as a project that no longer holds the document.
  const { eda } = renameEda({ listingBreaks: true, renameHonoured: false, answer: 'true' });
  await assert.rejects(
    () => buildHandlers(eda)['doc.rename']({ uuid: 'page-1', name: 'X' }),
    (error) => {
      assert.equal(error.code, 'CONNECTOR_ERROR');
      assert.match(error.message, /listing could not be read/);
      assert.match(error.message, /listing blew up/);
      assert.doesNotMatch(error.message, /no longer holds/);
      return true;
    },
  );
});
