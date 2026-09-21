/**
 * Contract tests for the 012 delete / modify actions.
 *
 * Same boundary as every other action test: the *production* dispatch path
 * against a fake host, so the wire contract and the failure shapes are pinned
 * where the daemon sees them. The host here exposes the primitive classes the
 * delete/modify dispatch walks (each recording its calls), the two document
 * guards, and nothing else — anything the handler reaches beyond that fails
 * the test, which is exactly what keeps the enumeration honest.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { createFacade } from '../dist/esm/facade.mjs';
import * as connector from '../dist/esm/index.mjs';

const BANNER = {
  event: 'banner',
  data: { server: 'boardwise', protocol: '1.0', expect: 'hello' },
};

const SCH_PAGE = 'page-1';
const PCB_UUID = 'pcb-1';

/** A primitive stand-in with a pose: both getState_* and plain properties. */
function withPose(id, pose = {}) {
  const { x = 10, y = 20, rotation = 0, mirror = false } = pose;
  return {
    getState_X: () => x,
    getState_Y: () => y,
    getState_Rotation: () => rotation,
    getState_Mirror: () => mirror,
    x,
    y,
    rotation,
    mirror,
  };
}

function keyed(ids, poseOf = () => ({})) {
  const deleted = [];
  const modified = [];
  const ns = {
    async getAllPrimitiveId() {
      return [...ids];
    },
    async get(id) {
      return ids.includes(id) ? withPose(id, poseOf(id)) : undefined;
    },
    async delete(id) {
      deleted.push(id);
      return true;
    },
    async modify(id, property) {
      modified.push({ id, property });
      const base = poseOf(id);
      return withPose(id, { ...base, ...property });
    },
    __deleted: deleted,
    __modified: modified,
  };
  return ns;
}

/**
 * A host with the schematic + PCB primitive classes the dispatch walks.
 * `without` drops a namespace entirely (the API-missing structural case).
 */
function host012({ without = [], poseById = {} } = {}) {
  const classes = {
    sch_PrimitiveComponent: keyed(['c1', 'c2'], (id) => poseById[id] ?? {}),
    sch_PrimitiveWire: keyed(['w1']),
    sch_PrimitiveText: keyed(['t1']),
    sch_PrimitivePin: keyed(['p1']),
    pcb_PrimitiveComponent: keyed(['pc1'], (id) => poseById[id] ?? {}),
    pcb_PrimitiveLine: keyed(['pl1']),
    pcb_PrimitiveVia: keyed(['pv1']),
    pcb_PrimitivePad: keyed(['pp1']),
    pcb_PrimitivePour: keyed(['po1']),
  };
  for (const name of without) delete classes[name];

  const host = {
    sys_WebSocket: {
      register(id, uri, onMessage) {
        host.__onMessage = onMessage;
      },
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
    dmt_Schematic: {
      async getCurrentSchematicPageInfo() {
        return { uuid: SCH_PAGE };
      },
      async getAllSchematicsInfo() {
        return [{ uuid: 'sch-9', name: 'schematic1' }];
      },
      async getAllSchematicPagesInfo() {
        return [{ uuid: SCH_PAGE, name: 'P1', parentSchematicUuid: 'sch-9' }];
      },
    },
    dmt_Pcb: {
      async getCurrentPcbInfo() {
        return { uuid: PCB_UUID };
      },
      async getAllPcbsInfo() {
        return [{ uuid: 'pcb-9', name: 'PCB1' }];
      },
    },
    dmt_Project: {
      async getCurrentProjectInfo() {
        return {
          uuid: 'proj-1',
          name: 'proj-1-name',
          friendlyName: 'Proj One',
          data: [
            { itemType: 'Schematic', uuid: 'sch-9', name: 'schematic1' },
            { itemType: 'PCB', uuid: 'pcb-9', name: 'PCB1' },
          ],
        };
      },
      async getAllProjectsUuid() {
        return ['proj-1', 'proj-2'];
      },
      async getProjectInfo(uuid) {
        return { uuid, friendlyName: 'Proj Two', teamUuid: 'team-1' };
      },
    },
    dmt_EditorControl: {
      async getSplitScreenTree() {
        return {
          id: 'split-1',
          tabs: [
            { title: 'P1', tabId: `${SCH_PAGE}@hash1`, documentType: 'schematic_page' },
            { title: 'PCB1', tabId: 'other-doc@hash2', documentType: 'pcb' },
          ],
        };
      },
      async activateDocument(tabId) {
        host.__activated = tabId;
        return true;
      },
    },
    ...classes,
  };
  return host;
}

function withEda(t, host) {
  connector.__setFacadeForTests(createFacade(host));
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

async function call(host, action, params = {}) {
  const id = `req-${Math.random().toString(36).slice(2, 8)}`;
  void host.__onMessage({ data: JSON.stringify({ id, action, params }) });
  assert.ok(
    await waitFor(() => (host.__sent ?? []).some((f) => f.id === id)),
    `no response frame for ${action}`,
  );
  return (host.__sent ?? []).find((f) => f.id === id);
}

test('delete dispatches mixed ids to their own classes and reports them deleted', async (t) => {
  const host = host012();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.delete_primitives', {
    pageUuid: SCH_PAGE,
    primitiveIds: ['c1', 'w1', 't1'],
  });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.deepEqual(frame.data.deleted, ['c1', 'w1', 't1']);
  assert.deepEqual(frame.data.notFound, []);
  assert.deepEqual(frame.data.failed, []);
  assert.deepEqual(host.sch_PrimitiveComponent.__deleted, ['c1']);
  assert.deepEqual(host.sch_PrimitiveWire.__deleted, ['w1']);
  assert.deepEqual(host.sch_PrimitiveText.__deleted, ['t1']);
});

test('delete reports ids the page never held as notFound, keeps the rest', async (t) => {
  const host = host012();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.delete_primitives', {
    pageUuid: SCH_PAGE,
    primitiveIds: ['c1', 'ghost', 'w1'],
  });
  assert.equal(frame.ok, true);
  assert.deepEqual(frame.data.deleted, ['c1', 'w1']);
  assert.deepEqual(frame.data.notFound, ['ghost']);
});

test('delete reports a host refusal per id instead of throwing', async (t) => {
  const host = host012();
  host.sch_PrimitiveComponent.delete = async (id) =>
    id === 'c-stuck' ? false : true;
  host.sch_PrimitiveComponent.getAllPrimitiveId = async () => ['c-stuck', 'c-ok'];
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.delete_primitives', {
    pageUuid: SCH_PAGE,
    primitiveIds: ['c-stuck', 'c-ok'],
  });
  assert.equal(frame.ok, true);
  assert.deepEqual(frame.data.deleted, ['c-ok']);
  assert.deepEqual(frame.data.failed, [
    { id: 'c-stuck', reason: 'delete returned false' },
  ]);
});

test('delete with an empty list is a successful no-op', async (t) => {
  const host = host012();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.delete_primitives', {
    pageUuid: SCH_PAGE,
    primitiveIds: [],
  });
  assert.equal(frame.ok, true);
  assert.deepEqual(frame.data, { deleted: [], notFound: [], failed: [] });
  // And the enumeration never ran — nothing to delete, nothing to index.
  assert.deepEqual(host.sch_PrimitiveComponent.__deleted, []);
});

test('delete refuses a page mismatch before touching anything', async (t) => {
  const host = host012();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.delete_primitives', {
    pageUuid: 'some-other-page',
    primitiveIds: ['c1'],
  });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'PAGE_MISMATCH');
  assert.deepEqual(host.sch_PrimitiveComponent.__deleted, []);
});

test('delete fails structurally when a dispatch class is missing', async (t) => {
  const host = host012({ without: ['sch_PrimitiveText'] });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.delete_primitives', {
    pageUuid: SCH_PAGE,
    primitiveIds: ['c1'],
  });
  assert.equal(frame.ok, false);
  // The structural code: a half-built index would dress "the API is gone"
  // up as "the id was wrong", so the missing class fails the whole action.
  assert.equal(frame.error.code, 'NOT_IMPLEMENTED');
  assert.match(frame.error.message, /sch_PrimitiveText/);
});

test('pcb delete guards the focused PCB the same way', async (t) => {
  const host = host012();
  withEda(t, host);
  await connector.activate();

  const bad = await call(host, 'pcb.delete_primitives', {
    pageUuid: 'not-the-pcb',
    primitiveIds: ['pc1'],
  });
  assert.equal(bad.ok, false);
  assert.equal(bad.error.code, 'PAGE_MISMATCH');

  const good = await call(host, 'pcb.delete_primitives', {
    pageUuid: PCB_UUID,
    primitiveIds: ['pc1', 'pl1'],
  });
  assert.equal(good.ok, true);
  assert.deepEqual(good.data.deleted, ['pc1', 'pl1']);
});

test('modify moves a component and returns the before/after pose', async (t) => {
  const host = host012({ poseById: { c1: { x: 10, y: 20, rotation: 0 } } });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.modify_primitive', {
    pageUuid: SCH_PAGE,
    primitiveId: 'c1',
    x: 100,
    y: 200,
    rotation: 90,
  });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.before.x, 10);
  assert.equal(frame.data.before.y, 20);
  assert.equal(frame.data.before.rotation, 0);
  assert.equal(frame.data.after.x, 100);
  assert.equal(frame.data.after.y, 200);
  assert.equal(frame.data.after.rotation, 90);
  assert.deepEqual(host.sch_PrimitiveComponent.__modified, [
    { id: 'c1', property: { x: 100, y: 200, rotation: 90 } },
  ]);
});

test('modify filters mirror through the class pose (a text has none)', async (t) => {
  const host = host012();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.modify_primitive', {
    pageUuid: SCH_PAGE,
    primitiveId: 't1',
    x: 5,
    mirror: true,
  });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'BAD_REQUEST');
  assert.match(frame.error.message, /no mirror/);
});

test('modify refuses a class with no pose semantics (a wire)', async (t) => {
  const host = host012();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.modify_primitive', {
    pageUuid: SCH_PAGE,
    primitiveId: 'w1',
    x: 1,
  });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'BAD_REQUEST');
  assert.match(frame.error.message, /no pose semantics/);
  assert.deepEqual(host.sch_PrimitiveWire.__modified, []);
});

test('modify needs an id it can find and at least one pose field', async (t) => {
  const host = host012();
  withEda(t, host);
  await connector.activate();

  const ghost = await call(host, 'sch.modify_primitive', {
    pageUuid: SCH_PAGE,
    primitiveId: 'nope',
    x: 1,
  });
  assert.equal(ghost.ok, false);
  assert.equal(ghost.error.code, 'NOT_FOUND');

  const empty = await call(host, 'sch.modify_primitive', {
    pageUuid: SCH_PAGE,
    primitiveId: 'c1',
  });
  assert.equal(empty.ok, false);
  assert.equal(empty.error.code, 'BAD_REQUEST');

  const missing = await call(host, 'sch.modify_primitive', {
    pageUuid: SCH_PAGE,
    x: 1,
  });
  assert.equal(missing.ok, false);
  assert.equal(missing.error.code, 'BAD_REQUEST');
});

test('modify refuses a page mismatch before touching anything', async (t) => {
  const host = host012();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'sch.modify_primitive', {
    pageUuid: 'some-other-page',
    primitiveId: 'c1',
    x: 1,
  });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'PAGE_MISMATCH');
  assert.deepEqual(host.sch_PrimitiveComponent.__modified, []);

  const pcb = await call(host, 'pcb.modify_primitive', {
    pageUuid: 'not-the-pcb',
    primitiveId: 'pc1',
    x: 1,
  });
  assert.equal(pcb.ok, false);
  assert.equal(pcb.error.code, 'PAGE_MISMATCH');
  assert.deepEqual(host.pcb_PrimitiveComponent.__modified, []);
});

test('doc.list carries the multi-project view alongside the legacy fields', async (t) => {
  const host = host012();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'doc.list', {});
  assert.equal(frame.ok, true, JSON.stringify(frame));
  const projects = frame.data.projects;
  assert.equal(projects.length, 2);
  const focused = projects.find((p) => p.focused);
  assert.equal(focused.projectUuid, 'proj-1');
  assert.equal(focused.opened, 'yes');
  assert.equal(focused.documents, 'full');
  assert.deepEqual(focused.schematics, [
    { uuid: 'sch-9', name: 'schematic1', type: 'schematic' },
    { uuid: SCH_PAGE, name: 'P1', type: 'page' },
  ]);
  assert.deepEqual(focused.pcbs, [
    { uuid: 'pcb-9', name: 'PCB1', type: 'pcb' },
  ]);
  const other = projects.find((p) => !p.focused);
  assert.equal(other.projectUuid, 'proj-2');
  assert.equal(other.name, 'Proj Two');
  assert.equal(other.opened, 'unknown');
  assert.equal(other.documents, 'brief');
  // Legacy fields untouched.
  assert.ok(Array.isArray(frame.data.documents));
  assert.equal(frame.data.count, frame.data.documents.length);
});

test('document.current names the current project the way doc.list does', async (t) => {
  // Measured 2026-09-21 (editor 3.2.186): `dmt_Project.getCurrentProjectInfo`
  // answers with plain readonly properties, and this box was built with
  // `snapshot()` — which walks `getState_*` prototype members only — so
  // `document.current` reported `project: {}` for the very project `doc.list`
  // named (`/test`, `test`, `ea80fff6…`). The fake host answers in that shape
  // (see `host012`), so both readers are held against one object here.
  const host = host012();
  withEda(t, host);
  await connector.activate();

  const current = await call(host, 'document.current', {});
  const list = await call(host, 'doc.list', {});
  const [focused] = list.data.projects.filter((project) => project.focused);

  assert.equal(current.ok, true, JSON.stringify(current));
  assert.notDeepEqual(current.data.project, {}, 'an empty project box hides an open project');
  assert.equal(current.data.project.projectUuid, focused.projectUuid);
  assert.equal(current.data.project.name, focused.name);
  assert.equal(current.data.project.friendlyName, focused.friendlyName);
});

test('doc.focus activates a tab resolved by page-uuid prefix', async (t) => {
  const host = host012();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'doc.focus', { pageUuid: SCH_PAGE });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.activated, true);
  assert.equal(frame.data.tabId, `${SCH_PAGE}@hash1`);
  assert.equal(frame.data.title, 'P1');
  assert.equal(host.__activated, `${SCH_PAGE}@hash1`);
});

test('doc.focus refuses a document that has no open tab', async (t) => {
  const host = host012();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'doc.focus', { pageUuid: 'never-opened' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'NOT_FOUND');
  assert.equal(host.__activated, undefined);
});

test('doc.delete_page removes a listed page and refuses an unknown uuid', async (t) => {
  const host = host012();
  host.dmt_Schematic.deleteSchematicPage = async (uuid) => {
    host.__deletedPage = uuid;
    return true;
  };
  withEda(t, host);
  await connector.activate();

  const ok = await call(host, 'doc.delete_page', { pageUuid: SCH_PAGE });
  assert.equal(ok.ok, true, JSON.stringify(ok));
  assert.equal(ok.data.deleted, true);
  assert.equal(host.__deletedPage, SCH_PAGE);

  const ghost = await call(host, 'doc.delete_page', { pageUuid: 'not-a-page' });
  assert.equal(ghost.ok, false);
  assert.equal(ghost.error.code, 'NOT_FOUND');

  const missing = await call(host, 'doc.delete_page', {});
  assert.equal(missing.ok, false);
  assert.equal(missing.error.code, 'BAD_REQUEST');
});

test('pcb modify moves a pad with rotation and reads the pcb guard', async (t) => {
  const host = host012({ poseById: { pp1: { x: 0, y: 0, rotation: 0 } } });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'pcb.modify_primitive', {
    pageUuid: PCB_UUID,
    primitiveId: 'pp1',
    x: 30,
    rotation: 45,
  });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.after.x, 30);
  assert.equal(frame.data.after.rotation, 45);
  assert.deepEqual(host.pcb_PrimitivePad.__modified, [
    { id: 'pp1', property: { x: 30, rotation: 45 } },
  ]);
});
