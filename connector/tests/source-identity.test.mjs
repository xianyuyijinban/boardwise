/**
 * R1-2: `sys.get_document_source` names the document it read.
 *
 * 179 made a `uuid` that is not the active document a refusal. That closed the
 * "asked for A, got B" hole for callers who name a document — but a caller who
 * omits `uuid` (the host call takes no arguments, so "read whatever is active"
 * is the action's natural use) still got a source with no name on it, and no
 * way to check it was the document it meant.
 *
 * Pinned here, offline against a fake `eda`:
 *
 * 1. **Every answer carries `uuid` / `name` / `type`**, with or without a
 *    `uuid` in the request, spelled as `doc.list` spells them — the name comes
 *    from the same listing `doc.list` builds, so the two cannot disagree.
 * 2. **Nothing that was already there moves**: `source` is still the host call
 *    path, the text, length and truncation fields are unchanged.
 * 3. **A source that may belong to two documents is not named**: the focus is
 *    read again after the host call, and if it moved, all three fields are
 *    `null` with a `notes` line saying why.
 * 4. **"Unknown" is never filled in with a guess**: no active document gives
 *    nulls and a note; a document missing from the listing keeps its uuid and
 *    type with `name: null` and a note.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { buildHandlers } from '../dist/esm/actions.mjs';

const SOURCE_TEXT = '{"type":"DOCHEAD"}||{"uuid":"page-2"}|';

/**
 * A project with one schematic, two pages and a PCB; `page-2` is active.
 *
 * `focusAfterRead` moves the focus *during* the host read (the user clicking
 * another tab while the source streams back) — the one race this action can
 * see and must not paper over.
 */
function projectEda({ active = 'page-2', documentType = 1, focusAfterRead = null, listed = true } = {}) {
  let focused = active;
  const calls = { read: 0, focusReads: 0 };
  const pages = [
    { uuid: 'page-1', name: 'P1', parentSchematicUuid: 'sch-1' },
    { uuid: 'page-2', name: 'P22 电源', parentSchematicUuid: 'sch-1' },
  ];
  const eda = {
    dmt_SelectControl: {
      getCurrentDocumentInfo: async () => {
        calls.focusReads += 1;
        if (!focused) return undefined;
        return { uuid: focused, documentType: focused.startsWith('pcb') ? 3 : documentType };
      },
    },
    dmt_Schematic: {
      getAllSchematicsInfo: async () => [{ uuid: 'sch-1', name: 'Schematic1' }],
      getAllSchematicPagesInfo: async () => (listed ? pages : pages.filter((p) => p.uuid !== active)),
    },
    dmt_Pcb: { getAllPcbsInfo: async () => [{ uuid: 'pcb-1', name: 'PCB1' }] },
    sys_FileManager: {
      getDocumentSource: async () => {
        calls.read += 1;
        if (focusAfterRead !== null) focused = focusAfterRead;
        return SOURCE_TEXT;
      },
    },
  };
  return { eda, calls };
}

const read = (eda, params = {}) => buildHandlers(eda)['sys.get_document_source'](params);

test('a read without a uuid names the active document, as doc.list names it', async () => {
  const { eda, calls } = projectEda();
  const data = await read(eda);
  assert.equal(calls.read, 1);
  assert.equal(data.uuid, 'page-2');
  assert.equal(data.name, 'P22 电源');
  assert.equal(data.type, 'page');
  assert.equal(data.notes, undefined, 'a clean read carries no notes');

  const listing = await buildHandlers(eda)['doc.list']({});
  const row = listing.documents.find((doc) => doc.uuid === data.uuid);
  assert.deepEqual({ uuid: row.uuid, name: row.name, type: row.type }, {
    uuid: data.uuid, name: data.name, type: data.type,
  }, 'the source read and doc.list spell the same document the same way');
});

test('a read with the active uuid answers the same identity', async () => {
  const { eda } = projectEda();
  const data = await read(eda, { uuid: 'page-2' });
  assert.deepEqual([data.uuid, data.name, data.type], ['page-2', 'P22 电源', 'page']);
});

test('a PCB in front is named as a pcb', async () => {
  const { eda } = projectEda({ active: 'pcb-1' });
  const data = await read(eda);
  assert.deepEqual([data.uuid, data.name, data.type], ['pcb-1', 'PCB1', 'pcb']);
});

test('the fields that were already there are unchanged', async () => {
  const { eda } = projectEda();
  const data = await read(eda);
  assert.equal(data.source, 'sys_FileManager.getDocumentSource', '`source` is still the host call');
  assert.equal(data.data, SOURCE_TEXT);
  assert.equal(data.chars, SOURCE_TEXT.length);
  assert.equal(data.truncated, false);
  assert.equal(data.maxChars, 65536);
  assert.equal(data.headLines, 0);
});

test('a focus that moved during the read leaves the source unnamed, and says why', async () => {
  const { eda, calls } = projectEda({ focusAfterRead: 'page-1' });
  const data = await read(eda);
  assert.equal(data.data, SOURCE_TEXT, 'the text is still handed back — it is the identity that is withheld');
  assert.deepEqual([data.uuid, data.name, data.type], [null, null, null]);
  assert.equal(data.notes.length, 1);
  assert.match(data.notes[0], /changed during the read \(page-2 before, page-1 after\)/);
  assert.equal(calls.focusReads, 2, 'the focus is read once before and once after the host call');
});

test('no active document gives nulls and a note, never a guessed name', async () => {
  const { eda } = projectEda({ active: null });
  const data = await read(eda);
  assert.deepEqual([data.uuid, data.name, data.type], [null, null, null]);
  assert.ok(data.notes.some((note) => /no active document could be read/.test(note)), data.notes);
});

test('a document the listing does not hold keeps its uuid and type, without a name', async () => {
  const { eda } = projectEda({ listed: false });
  const data = await read(eda);
  assert.equal(data.uuid, 'page-2');
  assert.equal(data.type, 'page');
  assert.equal(data.name, null);
  assert.ok(data.notes.some((note) => /page-2 is not in the open project's document listing/.test(note)), data.notes);
});

test('a refused uuid still refuses before the host is read (179 contract unchanged)', async () => {
  const { eda, calls } = projectEda();
  await assert.rejects(() => read(eda, { uuid: 'page-1' }), (error) => {
    assert.equal(error.code, 'DOC_NOT_ACTIVE');
    assert.equal(error.detail.activeUuid, 'page-2');
    return true;
  });
  assert.equal(calls.read, 0);
});
