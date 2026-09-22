/**
 * `sys.identity` and `doc.open`'s failure diagnosis (018 §B1/§B2).
 *
 * Both exist because of one measured failure: the editor has two layers of
 * focus, and on 2026-09-21 they disagreed. `doc.list` reported the focused
 * project as `/test` while the document in the canvas belonged to
 * `ROBOT ctrl FOC`, and `doc.open` — scoped to the project the editor has open
 * — refused a uuid that plainly existed, with a message that gave the caller
 * nothing to act on.
 *
 * The host below models both projects, and can be told to leave out each
 * channel the diagnosis might use (`parentProjectUuid`, the per-kind info
 * reads, the whole `dmt_Project` namespace) so the *fallbacks* are exercised
 * rather than assumed. The two editor layers are the point: `focused` is what
 * `dmt_Project.getCurrentProjectInfo` answers, `active` is what
 * `dmt_SelectControl.getCurrentDocumentInfo` answers.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { createFacade } from '../dist/esm/facade.mjs';
import * as connector from '../dist/esm/index.mjs';

/** Two open projects, each with one schematic (two pages) and one PCB. */
const PROJECTS = {
  'proj-test': {
    name: '/test',
    friendlyName: 'test',
    schematics: [{ uuid: 'sch-test', name: 'Sheet1' }],
    pages: [
      { uuid: 'page-a1', name: 'P1.Sheet1', parentSchematicUuid: 'sch-test' },
      { uuid: 'page-a2', name: 'P2.Sheet1', parentSchematicUuid: 'sch-test' },
    ],
    pcbs: [{ uuid: 'pcb-test', name: 'PCB1' }],
  },
  'proj-robot': {
    name: '/ROBOT ctrl FOC',
    friendlyName: 'ROBOT ctrl FOC',
    schematics: [{ uuid: 'sch-robot', name: 'FOC' }],
    pages: [{ uuid: 'page-b1', name: 'P1.FOC', parentSchematicUuid: 'sch-robot' }],
    pcbs: [{ uuid: 'pcb-robot', name: 'FOC PCB' }],
  },
};

/** uuid -> { projectUuid, type, row } for every document of both projects. */
function documentIndex() {
  const index = new Map();
  for (const [projectUuid, project] of Object.entries(PROJECTS)) {
    for (const row of project.schematics) index.set(row.uuid, { projectUuid, type: 'schematic', row });
    for (const row of project.pages) index.set(row.uuid, { projectUuid, type: 'page', row });
    for (const row of project.pcbs) index.set(row.uuid, { projectUuid, type: 'pcb', row });
  }
  return index;
}

const INDEX = documentIndex();

const DOC_TYPE = { SCHEMATIC_PAGE: 1, PCB: 3 };

/**
 * A two-project editor host.
 *
 * `active` is the uuid in the canvas, `focused` is the project
 * `getCurrentProjectInfo` names — they may disagree, which is the whole subject
 * of this file. `without` drops namespace members (e.g. `'dmt_Project'` or
 * `'dmt_Pcb.getPcbInfo'`) to model a host build that does not have them.
 */
function host018({
  active = 'page-a1',
  focused = 'proj-test',
  activeProjectField = true,
  crossProjectReads = true,
  enumerationFails = [],
  without = [],
  tabs = [],
  pcbsExotic = false,
} = {}) {
  const calls = [];
  const projectInfo = (uuid) => {
    const project = PROJECTS[uuid];
    if (!project) return undefined;
    return { uuid, name: project.name, friendlyName: project.friendlyName };
  };
  /** The per-kind reads that answer for a uuid outside the focused project. */
  const readable = (uuid) => {
    const hit = INDEX.get(uuid);
    if (!hit) return null;
    if (!crossProjectReads && hit.projectUuid !== focused) return null;
    return hit;
  };

  const host = {
    sys_WebSocket: {
      register(_id, _uri, onMessage) { host.__onMessage = onMessage; },
      send(_id, data) {
        host.__sent = host.__sent ?? [];
        host.__sent.push(JSON.parse(data));
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

    dmt_Project: {
      async getCurrentProjectInfo() {
        calls.push('dmt_Project.getCurrentProjectInfo');
        return projectInfo(focused);
      },
      async getAllProjectsUuid() {
        calls.push('dmt_Project.getAllProjectsUuid');
        return Object.keys(PROJECTS);
      },
      async getProjectInfo(uuid) {
        calls.push(`dmt_Project.getProjectInfo:${uuid}`);
        return projectInfo(uuid);
      },
    },

    dmt_Schematic: {
      async getAllSchematicsInfo() {
        calls.push('dmt_Schematic.getAllSchematicsInfo');
        if (enumerationFails.includes('dmt_Schematic.getAllSchematicsInfo')) {
          throw new Error('schematics enumeration blew up');
        }
        return PROJECTS[focused].schematics;
      },
      async getAllSchematicPagesInfo() {
        calls.push('dmt_Schematic.getAllSchematicPagesInfo');
        if (enumerationFails.includes('dmt_Schematic.getAllSchematicPagesInfo')) {
          throw new Error('pages enumeration blew up');
        }
        return PROJECTS[focused].pages;
      },
      async getSchematicInfo(uuid) {
        calls.push(`dmt_Schematic.getSchematicInfo:${uuid}`);
        const hit = readable(uuid);
        if (!hit || hit.type !== 'schematic') return undefined;
        return { ...hit.row, parentProjectUuid: hit.projectUuid };
      },
      async getSchematicPageInfo(uuid) {
        calls.push(`dmt_Schematic.getSchematicPageInfo:${uuid}`);
        const hit = readable(uuid);
        if (!hit || hit.type !== 'page') return undefined;
        return hit.row;
      },
    },

    dmt_Pcb: {
      async getAllPcbsInfo() {
        calls.push('dmt_Pcb.getAllPcbsInfo');
        if (enumerationFails.includes('dmt_Pcb.getAllPcbsInfo')) {
          throw new Error('pcb enumeration blew up');
        }
        if (pcbsExotic) {
          // An exotic host object: `Object.keys` is the read that throws on the
          // real editor's proxies (measured 2026-09-14).
          return [new Proxy({}, { ownKeys() { throw new TypeError('exotic host object'); } })];
        }
        return PROJECTS[focused].pcbs;
      },
      async getPcbInfo(uuid) {
        calls.push(`dmt_Pcb.getPcbInfo:${uuid}`);
        const hit = readable(uuid);
        if (!hit || hit.type !== 'pcb') return undefined;
        return { ...hit.row, parentProjectUuid: hit.projectUuid };
      },
    },

    dmt_SelectControl: {
      async getCurrentDocumentInfo() {
        calls.push('dmt_SelectControl.getCurrentDocumentInfo');
        if (!active) return undefined;
        const hit = INDEX.get(active);
        return {
          documentType: hit?.type === 'pcb' ? DOC_TYPE.PCB : DOC_TYPE.SCHEMATIC_PAGE,
          uuid: active,
          tabId: `tab-${active}`,
          ...(activeProjectField && hit ? { parentProjectUuid: hit.projectUuid } : {}),
        };
      },
    },

    dmt_EditorControl: {
      async openDocument(uuid) {
        calls.push(`openDocument:${uuid}`);
        // The measured refusal: a uuid of a project the editor does not have
        // open yields no tab, and so does a uuid that is not a document at all.
        return undefined;
      },
      async activateDocument(tabId) {
        calls.push(`activateDocument:${tabId}`);
        return false;
      },
      async getSplitScreenTree() {
        calls.push('dmt_EditorControl.getSplitScreenTree');
        return { tabs, children: [] };
      },
    },

    __calls: calls,
  };

  for (const path of without) {
    const parts = path.split('.');
    if (parts.length === 1) {
      delete host[path];
    } else {
      delete host[parts[0]][parts.slice(1).join('.')];
    }
  }
  return host;
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
// sys.identity
// --------------------------------------------------------------------------

test('sys.identity agrees when the active document belongs to the focused project', async (t) => {
  const h = host018({ active: 'page-a1', focused: 'proj-test' });
  await ready(t, h);

  const frame = await call(h, 'sys.identity');
  assert.equal(frame.ok, true);
  assert.equal(frame.data.focusedProject.projectUuid, 'proj-test');
  assert.equal(frame.data.focusedProject.name, '/test');
  assert.equal(frame.data.activeDocument.uuid, 'page-a1');
  assert.equal(frame.data.activeDocument.type, 'page');
  assert.equal(frame.data.activeDocument.project.projectUuid, 'proj-test');
  assert.equal(frame.data.activeDocument.project.name, '/test');
  assert.equal(frame.data.consistent, true);
  assert.equal(frame.data.consistentBasis, 'project-uuid');
  assert.equal(frame.data.pageUuid, 'page-a1');
  assert.equal(frame.data.readOnly, true);
});

test('sys.identity reports the disagreement instead of picking a winner', async (t) => {
  // The measured shape: `doc.list` names the focused project, the canvas holds
  // a document of another one. Both are reported, with the ids that let a
  // caller decide — and the owner is named from the open-project index, because
  // a uuid on its own is not something a human can switch to.
  const h = host018({ active: 'pcb-robot', focused: 'proj-test' });
  await ready(t, h);

  const frame = await call(h, 'sys.identity');
  assert.equal(frame.data.focusedProject.projectUuid, 'proj-test');
  assert.equal(frame.data.activeDocument.uuid, 'pcb-robot');
  assert.equal(frame.data.activeDocument.type, 'pcb');
  assert.equal(frame.data.activeDocument.project.projectUuid, 'proj-robot');
  assert.equal(frame.data.activeDocument.project.name, '/ROBOT ctrl FOC');
  assert.equal(frame.data.consistent, false);
  assert.equal(frame.data.consistentBasis, 'project-uuid');
  assert.equal(frame.data.pageUuid, 'pcb-robot');
});

test('sys.identity reports an unanswerable comparison as null, never as true', async (t) => {
  // "The check passed" and "the check could not run" must not look alike when
  // the caller is deciding whether it is safe to write.
  const h = host018({ without: ['dmt_Project'] });
  await ready(t, h);

  const frame = await call(h, 'sys.identity');
  assert.equal(frame.ok, true, 'a missing namespace is reported, not thrown');
  assert.equal(frame.data.focusedProject, null);
  assert.equal(frame.data.consistent, null);
  assert.equal(frame.data.consistentBasis, 'unavailable');
  // The active document's own channel still works, so that half is reported.
  assert.equal(frame.data.activeDocument.project.projectUuid, 'proj-test');
  assert.ok(
    (frame.data.notes ?? []).some((note) => note.includes('dmt_Project.getCurrentProjectInfo')),
    `the reason must be readable: ${JSON.stringify(frame.data.notes)}`,
  );
});

test('sys.identity falls back to the document\'s own read when the host leaves parentProjectUuid empty', async (t) => {
  const h = host018({ active: 'pcb-robot', focused: 'proj-test', activeProjectField: false });
  await ready(t, h);

  const frame = await call(h, 'sys.identity');
  assert.equal(frame.data.activeDocument.project.projectUuid, 'proj-robot');
  assert.equal(frame.data.activeDocument.project.name, '/ROBOT ctrl FOC');
  assert.equal(frame.data.consistent, false);
  assert.equal(frame.data.consistentBasis, 'project-uuid');
  assert.ok(
    h.__calls.includes('dmt_Pcb.getPcbInfo:pcb-robot'),
    `the per-kind read must be the fallback: ${h.__calls.join(', ')}`,
  );
});

test('sys.identity falls back to the focused project\'s listing when no project uuid can be had', async (t) => {
  // The weakest basis, and the only one left when the host offers neither
  // channel: membership in the document list `doc.list` shows.
  const h = host018({
    active: 'page-a2',
    activeProjectField: false,
    without: [
      'dmt_Pcb.getPcbInfo',
      'dmt_Schematic.getSchematicInfo',
      'dmt_Schematic.getSchematicPageInfo',
    ],
  });

  await ready(t, h);
  const frame = await call(h, 'sys.identity');
  assert.equal(frame.data.consistent, true);
  assert.equal(frame.data.consistentBasis, 'focused-project-listing');
  assert.equal(frame.data.focusedProject.projectUuid, 'proj-test');
});

test('sys.identity reports the listing basis as a disagreement for a foreign document', async (t) => {
  // Same host and same limited channels, with the active document in the
  // *other* project: it is not in the focused project's listing, so the two
  // layers disagree — which is the useful answer, and the one the incident
  // needed.
  const h = host018({
    active: 'page-b1',
    activeProjectField: false,
    without: [
      'dmt_Pcb.getPcbInfo',
      'dmt_Schematic.getSchematicInfo',
      'dmt_Schematic.getSchematicPageInfo',
    ],
  });

  await ready(t, h);
  const frame = await call(h, 'sys.identity');
  assert.equal(frame.data.consistent, false);
  assert.equal(frame.data.consistentBasis, 'focused-project-listing');
  assert.equal(frame.data.activeDocument.uuid, 'page-b1');
  assert.equal(frame.data.activeDocument.project, null, 'no read could name its project');
});

test('sys.identity refuses to answer from an incomplete listing', async (t) => {
  // A partial enumeration would report "not in this project" for a document
  // that simply was not listed — the conflation that made a real project look
  // empty on 2026-09-14.
  const h = host018({
    active: 'page-a1',
    activeProjectField: false,
    without: [
      'dmt_Pcb.getPcbInfo',
      'dmt_Schematic.getSchematicInfo',
      'dmt_Schematic.getSchematicPageInfo',
    ],
    enumerationFails: ['dmt_Schematic.getAllSchematicPagesInfo'],
  });

  await ready(t, h);
  const frame = await call(h, 'sys.identity');
  assert.equal(frame.data.consistent, null);
  assert.equal(frame.data.consistentBasis, 'unavailable');
  assert.ok(
    (frame.data.notes ?? []).some((note) => note.includes('enumeration blew up')),
    `the failed read must be named: ${JSON.stringify(frame.data.notes)}`,
  );
  assert.ok(
    (frame.data.notes ?? []).some((note) => note.includes('cannot be compared')),
    `and the missing comparison must be named: ${JSON.stringify(frame.data.notes)}`,
  );
});

test('sys.identity says so when nothing is focused', async (t) => {
  const h = host018({ active: null });
  await ready(t, h);

  const frame = await call(h, 'sys.identity');
  assert.equal(frame.data.activeDocument, null);
  assert.equal(frame.data.pageUuid, null);
  assert.equal(frame.data.consistent, null);
  assert.equal(frame.data.consistentBasis, 'no-active-document');
  assert.equal(frame.data.focusedProject.projectUuid, 'proj-test');
});

test('sys.identity changes nothing: it ignores its parameters and opens no tab', async (t) => {
  const h = host018({ active: 'page-a1' });
  await ready(t, h);
  h.__calls.length = 0;

  const frame = await call(h, 'sys.identity', { uuid: 'pcb-robot', confirm: true, write: true });
  assert.equal(frame.ok, true);
  assert.equal(frame.data.readOnly, true);
  assert.equal(
    h.__calls.some((entry) => entry.startsWith('openDocument') || entry.startsWith('activateDocument')),
    false,
    `a read must not open or focus anything: ${h.__calls.join(', ')}`,
  );
});

// --------------------------------------------------------------------------
// doc.open — the failure diagnosis
// --------------------------------------------------------------------------

test('doc.open says what it could search when the uuid is nowhere', async (t) => {
  const h = host018({ active: 'page-a1', focused: 'proj-test' });
  await ready(t, h);

  const frame = await call(h, 'doc.open', { uuid: 'page-ghost' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'CONNECTOR_ERROR', 'the code stays CONNECTOR_ERROR');
  assert.match(frame.error.message, /no tab id/);
  // The focused project is named, and the searchable set is stated honestly.
  assert.match(frame.error.message, /"\/test" \(proj-test\)/);
  assert.match(frame.error.message, /none of them is this uuid/);
  assert.match(frame.error.message, /cannot be searched/);
  assert.match(frame.error.message, /ROBOT ctrl FOC/);
  assert.match(frame.error.message, /doc\.list/);
  // The active document (and the project it belongs to) rides along, so the
  // caller can see both layers rather than only the one that is in doubt.
  assert.match(frame.error.message, /the active document is page-a1 \(project "\/test" \(proj-test\)\)/);

  const detail = frame.error.detail;
  assert.equal(detail.uuid, 'page-ghost');
  assert.equal(detail.focusedProject.projectUuid, 'proj-test');
  assert.equal(detail.uuidBelongsTo, null);
  assert.equal(detail.inFocusedProjectListing, false);
  assert.equal(detail.listingCount, 4);
});

test('doc.open does not claim a uuid is absent everywhere when only one project could be searched', async (t) => {
  // The honest limit, and the reason this branch names the projects it could
  // not search: `getProjectInfo` is a brief read with no document tree, so
  // "not in the open project" is all the connector can defend.
  const h = host018({ active: 'page-a1', focused: 'proj-test', crossProjectReads: false });
  await ready(t, h);

  const frame = await call(h, 'doc.open', { uuid: 'page-b1' });
  assert.equal(frame.error.code, 'CONNECTOR_ERROR');
  assert.equal(frame.error.detail.uuidBelongsTo, null, 'the owner channel really could not answer');
  assert.match(frame.error.message, /none of them is this uuid/);
  assert.match(frame.error.message, /cannot be searched/, 'the limit must be stated');
  assert.match(frame.error.message, /ROBOT ctrl FOC/, 'and the unsearched project named');
  assert.doesNotMatch(frame.error.message, /belongs to project/, 'no owner may be invented');
});

test('doc.open names the owning project and tells the caller to switch', async (t) => {
  // The measured incident, inverted: the uuid exists, in a project the editor
  // does not have open. Before this, the caller read "returned no tab id — the
  // uuid may not exist in this project" and had nothing to do next.
  const h = host018({ active: 'page-a1', focused: 'proj-test' });
  await ready(t, h);

  const frame = await call(h, 'doc.open', { uuid: 'page-b1' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'CONNECTOR_ERROR');
  assert.match(frame.error.message, /belongs to project "\/ROBOT ctrl FOC" \(proj-robot\)/);
  assert.match(frame.error.message, /not the project the editor has open/);
  assert.match(frame.error.message, /focused project: "\/test" \(proj-test\)/);
  assert.match(frame.error.message, /switch the editor to that project first/);
  // Both layers named: the focused project, and the document that is actually
  // in front with the project it belongs to.
  assert.match(frame.error.message, /the active document is page-a1 \(project "\/test" \(proj-test\)\)/);

  assert.equal(frame.error.detail.uuidBelongsTo.projectUuid, 'proj-robot');
  assert.equal(frame.error.detail.uuidBelongsTo.name, '/ROBOT ctrl FOC');
  // A page uuid is resolved through its schematic, and `source` names the reads
  // that produced the answer rather than the call that started it.
  assert.match(frame.error.detail.uuidBelongsTo.source, /getSchematicPageInfo → dmt_Schematic\.getSchematicInfo/);
  assert.equal(frame.error.detail.focusedProject.projectUuid, 'proj-test');
});

test('doc.open says "already open" and points at doc.focus when a tab has it', async (t) => {
  const h = host018({
    active: 'page-a1',
    focused: 'proj-test',
    // A tab id is `"<documentUuid>@<hash>"` (measured 006c), which is what the
    // prefix test matches on.
    tabs: [{ tabId: 'page-a2@9f1c', title: 'P2.Sheet1' }],
    // Neither owner channel answers here, so the tab is what is left to say.
    without: [
      'dmt_Pcb.getPcbInfo',
      'dmt_Schematic.getSchematicInfo',
      'dmt_Schematic.getSchematicPageInfo',
    ],
    activeProjectField: false,
  });

  await ready(t, h);
  const frame = await call(h, 'doc.open', { uuid: 'page-a2' });

  assert.equal(frame.ok, false);
  assert.match(frame.error.message, /already-open tab \("P2\.Sheet1"\)/);
  assert.match(frame.error.message, /doc\.focus/);
  assert.equal(frame.error.detail.openTabs.length, 1);
});

test('doc.open keeps the original failure when its own diagnosis breaks', async (t) => {
  // The diagnosis runs inside an error path, so it must never be able to
  // replace a clear error with a second, unrelated one. An exotic host object
  // (`Object.keys` throws — measured 2026-09-14) is enough to break it.
  const h = host018({ active: 'page-a1', focused: 'proj-test', pcbsExotic: true });
  await ready(t, h);

  const frame = await call(h, 'doc.open', { uuid: 'page-b1' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'CONNECTOR_ERROR');
  assert.match(frame.error.message, /returned no tab id/);
  assert.equal(frame.error.detail.uuid, 'page-b1');
  assert.equal(frame.error.detail.diagnosisError, true);
});

test('doc.open still opens what the editor will open, diagnosis or not', async (t) => {
  // Control: the failing path must not have grown a way to break the success
  // path. `openDocument` answers a tab id here, so the action reports it.
  const h = host018({ active: 'page-a1', focused: 'proj-test' });
  h.dmt_EditorControl.openDocument = async (uuid) => {
    h.__calls.push(`openDocument:${uuid}`);
    return 'tab-page-a2';
  };
  h.dmt_EditorControl.activateDocument = async (tabId) => {
    h.__calls.push(`activateDocument:${tabId}`);
    return true;
  };
  await ready(t, h);

  const frame = await call(h, 'doc.open', { uuid: 'page-a2' });
  assert.equal(frame.ok, true);
  assert.equal(frame.data.tabId, 'tab-page-a2');
  assert.equal(frame.data.activated, true);
  assert.equal(frame.data.opened, true);
  assert.equal(frame.data.document.matchesRequest, false, 'the mock never switches the active document');
});
