/**
 * The document-management actions (006c, work item 6).
 *
 * These four exist so the harness can *see* a project's documents instead of
 * acting on "whatever page is focused" — a mix-up between a golden and a test
 * page has already cost two rounds. What is pinned here is the part that has
 * bitten before: every one of them must confirm what happened by **asking the
 * editor**, not by trusting the call it just made.
 *
 * The fake project below models the parts of `dmt_*` the actions use, and can
 * be told to misbehave (accept a rename and store nothing, refuse to focus a
 * new PCB) so those paths are exercised rather than assumed.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { createFacade } from '../dist/esm/facade.mjs';
import * as connector from '../dist/esm/index.mjs';

const DOC_TYPE = { SCHEMATIC_PAGE: 1, PCB: 3 };

/**
 * A project with one schematic and two pages, plus one PCB.
 *
 * `rename` and `focus` switches let a test model a host that accepts a call
 * and does not do it — the shape that makes "read it back" load-bearing.
 */
function project({
  renameHonoured = true,
  pcbFocusable = true,
  enumerationFails = false,
  active = 'page-1',
} = {}) {
  const state = {
    schematics: [{ uuid: 'sch-1', name: 'Schematic1' }],
    pages: [
      { uuid: 'page-1', name: 'P1.Schematic1', parentSchematicUuid: 'sch-1' },
      { uuid: 'page-2', name: 'P2.Schematic1', parentSchematicUuid: 'sch-1' },
    ],
    pcbs: [{ uuid: 'pcb-1', name: 'PCB1' }],
    active,
    tabId: null,
    calls: [],
  };

  const find = (uuid) => {
    for (const list of [state.pages, state.pcbs, state.schematics]) {
      const hit = list.find((row) => row.uuid === uuid);
      if (hit) return hit;
    }
    return undefined;
  };

  const hostObject = {
    sys_WebSocket: {
      register(_id, _uri, onMessage) { hostObject.__onMessage = onMessage; },
      send(_id, data) {
        hostObject.__sent = hostObject.__sent ?? [];
        hostObject.__sent.push(JSON.parse(data));
      },
      close() {},
    },
    sys_Log: { add() {} },
    sys_Message: { showToastMessage() {} },
    sys_Environment: { getEditorCurrentVersion: () => '3.2.186' },
    sys_Storage: {
      getExtensionUserConfig: () => undefined,
      setExtensionUserConfig: async () => true,
    },
    sys_Dialog: { showInformationMessage() {} },

    dmt_Schematic: {
      async getAllSchematicsInfo() {
        state.calls.push('getAllSchematicsInfo');
        if (enumerationFails) throw new Error('enumeration blew up');
        return state.schematics;
      },
      async getAllSchematicPagesInfo() {
        state.calls.push('getAllSchematicPagesInfo');
        if (enumerationFails) throw new Error('enumeration blew up');
        return state.pages;
      },
      async getCurrentSchematicPageInfo() {
        state.calls.push('getCurrentSchematicPageInfo');
        return state.pages.find((row) => row.uuid === state.active);
      },
      async modifySchematicPageName(uuid, name) {
        state.calls.push(`modifySchematicPageName:${uuid}:${name}`);
        if (!renameHonoured) return true;      // accepted, stored nothing
        const page = state.pages.find((row) => row.uuid === uuid);
        if (!page) return false;
        page.name = name;
        return true;
      },
      async modifySchematicName(uuid, name) {
        state.calls.push(`modifySchematicName:${uuid}:${name}`);
        const schematic = state.schematics.find((row) => row.uuid === uuid);
        if (!schematic) return false;
        schematic.name = name;
        return true;
      },
    },

    dmt_Pcb: {
      async getAllPcbsInfo() {
        state.calls.push('getAllPcbsInfo');
        if (enumerationFails) throw new Error('enumeration blew up');
        return state.pcbs;
      },
      async getCurrentPcbInfo() {
        state.calls.push('getCurrentPcbInfo');
        return state.pcbs.find((row) => row.uuid === state.active);
      },
      async createPcb(boardName) {
        state.calls.push(`createPcb:${boardName ?? ''}`);
        const pcb = { uuid: 'pcb-2', name: boardName ?? 'PCB2' };
        state.pcbs.push(pcb);
        return pcb.uuid;
      },
      async modifyPcbName(uuid, name) {
        state.calls.push(`modifyPcbName:${uuid}:${name}`);
        const pcb = state.pcbs.find((row) => row.uuid === uuid);
        if (!pcb) return false;
        pcb.name = name;
        return true;
      },
    },

    dmt_SelectControl: {
      async getCurrentDocumentInfo() {
        state.calls.push('getCurrentDocumentInfo');
        const uuid = state.active;
        if (!uuid) return undefined;
        const isPcb = state.pcbs.some((row) => row.uuid === uuid);
        return {
          documentType: isPcb ? DOC_TYPE.PCB : DOC_TYPE.SCHEMATIC_PAGE,
          uuid,
          tabId: state.tabId ?? `tab-${uuid}`,
        };
      },
    },

    dmt_EditorControl: {
      async openDocument(uuid) {
        state.calls.push(`openDocument:${uuid}`);
        if (!find(uuid)) return undefined;
        if (uuid === 'pcb-2' && !pcbFocusable) {
          // Opens a tab but never takes focus — the case the action must refuse.
          state.tabId = 'tab-pcb-2';
          return 'tab-pcb-2';
        }
        state.active = uuid;
        state.tabId = `tab-${uuid}`;
        return state.tabId;
      },
      async activateDocument(tabId) {
        state.calls.push(`activateDocument:${tabId}`);
        return tabId === state.tabId;
      },
    },

    __state: state,
  };
  return hostObject;
}

function withEda(t, hostObject) {
  connector.__setFacadeForTests(createFacade(hostObject));
  t.after(() => {
    connector.deactivate();
    connector.__setFacadeForTests(undefined);
  });
}

async function waitFor(predicate, timeoutMs = 2000) {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() > deadline) return false;
    await new Promise((resolve) => setTimeout(resolve, 2));
  }
  return true;
}

async function call(hostObject, action, params = {}) {
  const id = `req-${Math.random().toString(36).slice(2, 8)}`;
  void hostObject.__onMessage({ data: JSON.stringify({ id, action, params }) });
  assert.ok(
    await waitFor(() => (hostObject.__sent ?? []).some((f) => f.id === id)),
    `no response frame for ${action}`,
  );
  return (hostObject.__sent ?? []).find((f) => f.id === id);
}

async function ready(t, hostObject) {
  withEda(t, hostObject);
  await connector.activate();
  await connector.activate();
}

// --------------------------------------------------------------------------
// doc.list
// --------------------------------------------------------------------------

test('doc.list shows every document kind and marks the active one', async (t) => {
  const h = project({ active: 'page-2' });
  await ready(t, h);

  const frame = await call(h, 'doc.list');
  assert.equal(frame.ok, true);
  const rows = frame.data.documents;
  assert.deepEqual(
    rows.map((row) => [row.uuid, row.type, row.active]).sort(),
    [
      ['page-1', 'page', false],
      ['page-2', 'page', true],
      ['pcb-1', 'pcb', false],
      ['sch-1', 'schematic', false],
    ].sort(),
  );
  assert.equal(frame.data.schematicPages, 2);
  assert.equal(frame.data.pcbs, 1);
  assert.equal(frame.data.count, 4);
  assert.equal(frame.data.active.uuid, 'page-2');
  assert.equal(frame.data.active.type, 'page');
  // Pages carry their schematic so a caller can tell two "P1" apart.
  const page = rows.find((row) => row.uuid === 'page-1');
  assert.equal(page.parentUuid, 'sch-1');
  assert.equal(page.parentName, 'Schematic1');
});

test('doc.list names a failed enumeration instead of looking empty', async (t) => {
  // "Nothing is open" and "the read broke" must not look the same: that
  // conflation is what made a real project look empty on 2026-09-14.
  const h = project({ enumerationFails: true });
  await ready(t, h);

  const frame = await call(h, 'doc.list');
  assert.equal(frame.ok, true, 'one broken read is not a failed action');
  assert.equal(frame.data.count, 0);
  assert.ok(frame.data.notes.length >= 3, `expected a note per read: ${frame.data.notes}`);
  assert.ok(frame.data.notes.every((note) => /blew up/.test(note)));
});

test('doc.list reports no active document without inventing one', async (t) => {
  const h = project({ active: null });
  await ready(t, h);

  const frame = await call(h, 'doc.list');
  assert.equal(frame.data.active, null);
  assert.ok(frame.data.documents.every((row) => row.active === false));
});

// --------------------------------------------------------------------------
// doc.open
// --------------------------------------------------------------------------

test('doc.open focuses the page and confirms it by asking the editor', async (t) => {
  const h = project({ active: 'page-1' });
  await ready(t, h);

  const frame = await call(h, 'doc.open', { uuid: 'page-2' });
  assert.equal(frame.ok, true);
  assert.equal(frame.data.uuid, 'page-2');
  assert.equal(frame.data.opened, true);
  assert.equal(frame.data.activated, true);
  assert.equal(frame.data.document.uuid, 'page-2');
  assert.equal(frame.data.document.matchesRequest, true);
  assert.equal(h.__state.active, 'page-2');
});

test('doc.open requires a uuid — it will not fall back to "whatever is open"', async (t) => {
  const h = project();
  await ready(t, h);

  const frame = await call(h, 'doc.open', {});
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'BAD_REQUEST');
  assert.match(frame.error.message, /doc\.list/);
});

test('doc.open rejects a uuid the project does not have', async (t) => {
  const h = project();
  await ready(t, h);

  const frame = await call(h, 'doc.open', { uuid: 'page-does-not-exist' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'CONNECTOR_ERROR');
  assert.match(frame.error.message, /no tab id/);
});

test('doc.open passes the tab id to activateDocument, not the document uuid', async (t) => {
  // `openDocument` returns a *tab id* and `activateDocument` takes one; using
  // the document uuid there is the mistake this asserts against.
  const h = project();
  await ready(t, h);

  await call(h, 'doc.open', { uuid: 'sch-1' });
  const activate = h.__state.calls.find((entry) => entry.startsWith('activateDocument:'));
  assert.equal(activate, 'activateDocument:tab-sch-1');
  assert.equal(
    h.__state.calls.some((entry) => entry.startsWith('activateDocument:sch-1')),
    false,
  );
});

// --------------------------------------------------------------------------
// pcb.doc.new
// --------------------------------------------------------------------------

test('pcb.doc.new creates, opens and verifies the new board', async (t) => {
  const h = project();
  await ready(t, h);

  const frame = await call(h, 'pcb.doc.new', { boardName: 'Board1' });
  assert.equal(frame.ok, true);
  assert.equal(frame.data.pcbUuid, 'pcb-2');
  assert.equal(frame.data.focused, true);
  assert.ok(h.__state.calls.includes('createPcb:Board1'));
  assert.equal(h.__state.active, 'pcb-2', 'the new board is what later actions address');
});

test('pcb.doc.new refuses when the new board cannot be focused', async (t) => {
  // Every placement action addresses the focused document, so a silent failure
  // here would mean editing whatever was open instead.
  const h = project({ pcbFocusable: false });
  await ready(t, h);

  const frame = await call(h, 'pcb.doc.new', {});
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'CONNECTOR_ERROR');
  assert.match(frame.error.message, /refusing to edit the wrong document/);
});

// --------------------------------------------------------------------------
// doc.rename
// --------------------------------------------------------------------------

test('doc.rename renames a page and confirms it against the editor listing', async (t) => {
  const h = project();
  await ready(t, h);

  const frame = await call(h, 'doc.rename', { uuid: 'page-2', name: 'P2.Renamed' });
  assert.equal(frame.ok, true);
  assert.equal(frame.data.type, 'page');
  assert.equal(frame.data.renamed, true);
  assert.equal(frame.data.confirmed, true);
  assert.ok(h.__state.calls.includes('modifySchematicPageName:page-2:P2.Renamed'));
});

test('doc.rename works out the kind itself when type is omitted', async (t) => {
  const h = project();
  await ready(t, h);

  const asPcb = await call(h, 'doc.rename', { uuid: 'pcb-1', name: 'Main' });
  assert.equal(asPcb.data.type, 'pcb');
  const asSchematic = await call(h, 'doc.rename', { uuid: 'sch-1', name: 'Sheet' });
  assert.equal(asSchematic.data.type, 'schematic');
  const asPage = await call(h, 'doc.rename', { uuid: 'page-1', name: 'First' });
  assert.equal(asPage.data.type, 'page');
});

test('doc.rename dispatches on the kind it was told', async (t) => {
  const h = project();
  await ready(t, h);

  const frame = await call(h, 'doc.rename', { uuid: 'sch-1', name: 'X', type: 'schematic' });
  assert.equal(frame.data.type, 'schematic');
  assert.ok(h.__state.calls.includes('modifySchematicName:sch-1:X'));
});

test('doc.rename rejects an unknown kind rather than guessing one', async (t) => {
  const h = project();
  await ready(t, h);

  const frame = await call(h, 'doc.rename', { uuid: 'page-1', name: 'X', type: 'board' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'BAD_REQUEST');
  assert.match(frame.error.message, /page\/schematic\/pcb/);
});

test('doc.rename refuses a uuid that is not in the project', async (t) => {
  const h = project();
  await ready(t, h);

  const frame = await call(h, 'doc.rename', { uuid: 'nope', name: 'X' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'BAD_REQUEST');
  assert.match(frame.error.message, /doc\.list/);
});

test('doc.rename fails loudly when the editor claims success and stored nothing', async (t) => {
  // "modify returned true" and "the document is called that now" are different
  // statements; only the second one is what the caller asked for.
  const h = project({ renameHonoured: false });
  await ready(t, h);

  const frame = await call(h, 'doc.rename', { uuid: 'page-1', name: 'New' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'CONNECTOR_ERROR');
  assert.match(frame.error.message, /still named P1\.Schematic1/);
});

test('doc.rename needs a non-empty name', async (t) => {
  const h = project();
  await ready(t, h);

  for (const name of ['', '   ']) {
    const frame = await call(h, 'doc.rename', { uuid: 'page-1', name });
    assert.equal(frame.ok, false);
    assert.equal(frame.error.code, 'BAD_REQUEST');
  }
});
