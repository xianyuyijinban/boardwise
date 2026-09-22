/**
 * The live context on every response frame (023 §协议字段约定 1).
 *
 * Why it exists: three editor windows is normal for a hardware engineer, and
 * the daemon routes each call to one of them by project. The handshake names
 * the project of a window *once*; a user who then switches document has a
 * connection whose story is out of date, and every routing decision made on it
 * is about the wrong page. The answer the daemon is already waiting for is the
 * freshest thing on the wire, so the context rides on it.
 *
 * What is pinned here:
 *
 * - the four fields, at the frame's **top level** — an action's `data` shape is
 *   a contract with every caller and does not change;
 * - omitted, not blanked, when the window cannot say (unreadable, throwing,
 *   hung) — a missing field is a fact, a wrong one is a write in the wrong
 *   project;
 * - `pageType` in the daemon's vocabulary, `sch` / `pcb`, plus `null` for "a
 *   document is in front and it is neither";
 * - a frame with no reader configured is byte-for-byte what it always was.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { createFacade } from '../dist/esm/facade.mjs';
import { currentResponseContext } from '../dist/esm/actions.mjs';
import * as connector from '../dist/esm/index.mjs';
import { ActionError, withContext } from '../dist/esm/protocol.mjs';
import { Transport } from '../dist/esm/transport.mjs';

/** Mirrors the official `eda.sys_WebSocket` signature. */
class FakeSocket {
  constructor() {
    this.registered = [];
    this.sent = [];
    this.closed = [];
  }

  register(id, uri, onMessage, onConnected) {
    this.registered.push({ id, uri });
    this.onMessage = onMessage;
    this.onConnected = onConnected;
  }

  send(id, data) {
    this.sent.push({ id, frame: JSON.parse(data) });
  }

  close(id) {
    this.closed.push(id);
  }

  async deliver(frame) {
    await this.onMessage?.({ data: JSON.stringify(frame) });
  }

  /** The answer to one request id, if it has gone out yet. */
  answer(id) {
    return this.sent.find((entry) => entry.frame.id === id)?.frame;
  }
}

function makeTransport(socket, overrides = {}) {
  const transport = new Transport({
    url: 'ws://127.0.0.1:61190/eda',
    token: 'tok',
    socket,
    minBackoffMs: 5,
    maxBackoffMs: 20,
    heartbeatMs: 1000,
    heartbeatMissLimit: 2,
    onRequest: async (action) => ({ echoed: action }),
    ...overrides,
  });
  return { transport };
}

/** Poll until `predicate` holds, or the deadline passes. */
async function waitFor(predicate, timeoutMs = 1000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return true;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  return predicate();
}

/** Connect once, then deliver one request and wait for its answer. */
async function ask(socket, transport, id, frame = {}) {
  if (socket.registered.length === 0) {
    void transport.start();
    await socket.deliver({ event: 'banner', data: {} });
  }
  await socket.deliver({ id, action: 'doc.list', params: {}, ...frame });
  assert.ok(await waitFor(() => socket.answer(id)), `no answer to ${id}`);
  return socket.answer(id);
}

const FULL_CONTEXT = {
  projectName: '/test',
  projectUuid: 'ea80fff6',
  pageUuid: 'page-a1',
  pageType: 'sch',
};

test('a response frame carries the four context fields at its top level', async () => {
  const socket = new FakeSocket();
  const { transport } = makeTransport(socket, { responseContext: async () => FULL_CONTEXT });
  const answer = await ask(socket, transport, 'r1');

  assert.deepEqual(answer.context, FULL_CONTEXT);
  // The result shape is untouched: `context` is a sibling of `data`, never a
  // field inside it, because `data` is what every existing caller destructures.
  assert.deepEqual(answer.data, { echoed: 'doc.list' });
  assert.equal('context' in answer.data, false, 'the action result must not grow a context key');
  assert.deepEqual(Object.keys(answer).sort(), ['context', 'data', 'id', 'ok']);
  transport.stop();
});

test('the context is read per response, never carried over from the last one', async () => {
  // "Live" is the whole point: a value remembered from the previous answer
  // would describe the document the user has since switched away from — the
  // frozen-at-hello mistake, one response wide.
  const socket = new FakeSocket();
  const reads = [
    { ...FULL_CONTEXT },
    { projectName: '/test', projectUuid: 'ea80fff6', pageUuid: 'pcb-1', pageType: 'pcb' },
  ];
  let n = 0;
  const { transport } = makeTransport(socket, {
    responseContext: async () => reads[Math.min(n++, reads.length - 1)],
  });

  const first = await ask(socket, transport, 'r1');
  const second = await ask(socket, transport, 'r2');

  assert.equal(first.context.pageType, 'sch');
  assert.equal(second.context.pageType, 'pcb');
  assert.equal(second.context.pageUuid, 'pcb-1');
  assert.equal(n, 2, 'one read per response');
  transport.stop();
});

test('an error frame carries the context too — a refusal says which window refused', async () => {
  const socket = new FakeSocket();
  const { transport } = makeTransport(socket, {
    responseContext: async () => FULL_CONTEXT,
    onRequest: async () => {
      throw new ActionError('PAGE_MISMATCH', 'the focused page is not the one asked for');
    },
  });
  const answer = await ask(socket, transport, 'r2');

  assert.equal(answer.ok, false);
  assert.equal(answer.error.code, 'PAGE_MISMATCH', 'the structured error is unchanged');
  assert.equal(answer.context.projectName, '/test');
  transport.stop();
});

test('a request with no action is refused with the context attached', async () => {
  // The third response path (the frame is neither a success nor a handler
  // failure). It goes through the same single choke point, so it cannot be the
  // one answer that forgets where it came from.
  const socket = new FakeSocket();
  const { transport } = makeTransport(socket, { responseContext: async () => FULL_CONTEXT });
  const answer = await ask(socket, transport, 'r3', { action: undefined });

  assert.equal(answer.error.code, 'BAD_REQUEST');
  assert.deepEqual(answer.context, FULL_CONTEXT);
  transport.stop();
});

test('a context that cannot be read is omitted, never blanked or guessed', async () => {
  // Three ways a window can have nothing to say, all real: no reader answered
  // (`{}`), no project could be named (`undefined`), the read threw (the
  // editor host hands out Proxies whose `get` trap throws — measured
  // 2026-09-14). None may become `null`, `''` or the string `"undefined"`: a
  // blank field reads on the daemon side like a project that happens to be
  // named that, and this is the field a write is routed by.
  const cases = [
    ['answers an empty object', async () => ({})],
    ['answers nothing', async () => undefined],
    ['throws', async () => {
      throw new Error('getCurrentProjectInfo blew up');
    }],
  ];
  for (const [label, responseContext] of cases) {
    const socket = new FakeSocket();
    const { transport } = makeTransport(socket, { responseContext });
    const answer = await ask(socket, transport, 'r4');

    assert.equal('context' in answer, false, `${label}: the key must be absent, not empty`);
    assert.deepEqual(Object.keys(answer).sort(), ['data', 'id', 'ok'], label);
    assert.deepEqual(answer.data, { echoed: 'doc.list' }, `${label}: the answer still stands`);
    transport.stop();
  }
});

test('a context read that never settles costs the decoration, not the answer', async () => {
  // The deadline is why this test can exist: an action has already been
  // carried out by the time the context is read, so an answer that never went
  // out would be far worse than one with no context on it.
  const socket = new FakeSocket();
  const { transport } = makeTransport(socket, {
    responseContext: () => new Promise(() => {}),
    responseContextTimeoutMs: 20,
  });
  const started = Date.now();
  const answer = await ask(socket, transport, 'r5');

  assert.equal('context' in answer, false);
  assert.deepEqual(answer.data, { echoed: 'doc.list' });
  assert.ok(Date.now() - started < 1000, 'the deadline must release the response');
  transport.stop();
});

test('a frame from a transport with no reader is byte-for-byte what it always was', async () => {
  // Older wiring, or a build that can read nothing: the field must not appear
  // at all. `context: {}` is a different claim on the daemon side — it says
  // this connector speaks 023 and has nothing to report.
  const socket = new FakeSocket();
  const { transport } = makeTransport(socket);
  const answer = await ask(socket, transport, 'r6');

  assert.deepEqual(Object.keys(answer).sort(), ['data', 'id', 'ok']);
  transport.stop();
});

test('only the daemon\'s two words survive, and an explicit null is kept', () => {
  // The wire is where the vocabulary is enforced, whatever a reader hands
  // over. `pageType: null` is the one null that is a reading — "a document is
  // in front and it is neither a schematic page nor a PCB" — and it is kept;
  // the daemon's merge treats it as no news rather than as a value.
  const frame = { id: 'r7', ok: true, data: {} };

  assert.deepEqual(
    withContext(frame, { projectName: '/test', pageUuid: 'p1', pageType: 'pcb' }),
    { id: 'r7', ok: true, data: {}, context: { projectName: '/test', pageUuid: 'p1', pageType: 'pcb' } },
  );
  assert.deepEqual(
    withContext(frame, { pageUuid: 'p1', pageType: null }).context,
    { pageUuid: 'p1', pageType: null },
  );
  // Fields that are not readings are dropped: an empty string is not a name,
  // a third word is not a page type, and `undefined` is not a value.
  assert.deepEqual(
    withContext(frame, { projectName: '', projectUuid: undefined, pageUuid: '', pageType: 'schematic' }),
    frame,
    'nothing usable — the frame is returned untouched',
  );
  assert.equal(withContext(frame, undefined), frame);
  assert.deepEqual(frame, { id: 'r7', ok: true, data: {} }, 'the input frame is never mutated');
});

// --------------------------------------------------------------------------
// the production reader: `actions.currentResponseContext`
// --------------------------------------------------------------------------

const DOC_TYPE = { SCHEMATIC_PAGE: 1, PCB: 3 };

/**
 * The host pieces the two shared reads use.
 *
 * `active` is the uuid of the document in front; `documentType` is the
 * host's own enum, which is what the real editor answers with.
 */
function fakeEda({ active = 'page-a1', documentType, omitSelectControl = false } = {}) {
  const eda = {
    dmt_Project: {
      getCurrentProjectInfo: async () => ({
        uuid: 'ea80fff642fa86cd', name: 'test', friendlyName: '/test',
      }),
    },
  };
  if (!omitSelectControl) {
    eda.dmt_SelectControl = {
      getCurrentDocumentInfo: async () =>
        active === null ? undefined : { uuid: active, tabId: `tab-${active}`, documentType },
    };
  }
  return eda;
}

test('the reader reports the project and the page, in the daemon\'s vocabulary', async () => {
  const schematic = await currentResponseContext(
    fakeEda({ active: 'page-a1', documentType: DOC_TYPE.SCHEMATIC_PAGE }),
  );
  assert.deepEqual(schematic, {
    projectName: '/test',
    projectUuid: 'ea80fff642fa86cd',
    pageUuid: 'page-a1',
    pageType: 'sch',
  });

  const pcb = await currentResponseContext(
    fakeEda({ active: 'pcb-1', documentType: DOC_TYPE.PCB }),
  );
  assert.equal(pcb.pageType, 'pcb', 'the second word the daemon routes by');
  assert.equal(pcb.pageUuid, 'pcb-1');
});

test('a window with nothing in front omits the page keys, and keeps the project', async () => {
  const eda = fakeEda({ active: null });
  const context = await currentResponseContext(eda);

  assert.deepEqual(context, { projectName: '/test', projectUuid: 'ea80fff642fa86cd' });
  assert.equal('pageUuid' in context, false);
  assert.equal('pageType' in context, false);
});

test('the host\'s "nothing is focused" placeholder is not reported as a page', async () => {
  // Measured 2026-09-21: with several windows open and none focused,
  // `getCurrentDocumentInfo` still answers — with `uuid: "0"`, which no
  // document anywhere has. Reporting that would quietly defeat exactly the
  // check the daemon is doing with this field.
  const eda = fakeEda({ active: '0', documentType: DOC_TYPE.SCHEMATIC_PAGE });
  const context = await currentResponseContext(eda);

  assert.equal('pageUuid' in context, false);
  assert.equal('pageType' in context, false);
});

test('a per-kind fallback still names the page type', async () => {
  // A host without the direct read: `doc.list` and `document.current` use the
  // per-kind getters next, and the context must say the same thing they do.
  const eda = fakeEda({ omitSelectControl: true });
  eda.dmt_Schematic = { getCurrentSchematicPageInfo: async () => ({ uuid: 'page-a1' }) };
  const context = await currentResponseContext(eda);

  assert.equal(context.pageUuid, 'page-a1');
  assert.equal(context.pageType, 'sch', 'the fallback is a schematic page, and says so');
});

test('a document of another kind is reported as null, not as a missing page', async () => {
  // A symbol editor or the home tab: a document *is* in front and it is
  // neither of the two the daemon routes by. `null` says that; omitting the
  // key would say "this window cannot see its own canvas", which is a
  // different and untrue statement.
  const eda = fakeEda({ active: 'sym-1', documentType: 2 }); // SYMBOL_COMPONENT
  const context = await currentResponseContext(eda);

  assert.equal(context.pageUuid, 'sym-1');
  assert.equal(context.pageType, null);
});

test('a host that throws on every read answers {} rather than failing the action', async () => {
  // The editor host hands out exotic objects whose property reads throw. This
  // reader is on the response path of every action, so "never throws" is the
  // only acceptable contract.
  const hostile = {
    get dmt_Project() {
      throw new Error('get trap');
    },
    get dmt_SelectControl() {
      throw new Error('get trap');
    },
    get dmt_Schematic() {
      throw new Error('get trap');
    },
    get dmt_Pcb() {
      throw new Error('get trap');
    },
  };

  assert.deepEqual(await currentResponseContext(hostile), {});
});

// --------------------------------------------------------------------------
// the production path, end to end
// --------------------------------------------------------------------------

/** A stand-in editor host, shaped like the real one but wholly in-process. */
function fakeHost() {
  const socket = new FakeSocket();
  const state = { active: 'page-a1' };
  const host = {
    sys_WebSocket: socket,
    sys_Log: { add() {} },
    sys_Message: { showToastMessage() {} },
    sys_Environment: { getEditorCurrentVersion: () => '3.2.186' },
    sys_Storage: {
      getExtensionUserConfig: () => undefined,
      setExtensionUserConfig: async () => true,
    },
    sys_Dialog: { showInformationMessage() {} },

    dmt_Project: {
      getCurrentProjectInfo: async () => ({
        uuid: 'ea80fff642fa86cd', name: 'test', friendlyName: '/test',
      }),
      // `doc.list` asks these two of every host, focused project or not.
      getAllProjectsUuid: async () => ['ea80fff642fa86cd'],
      getProjectInfo: async (uuid) => ({ uuid, name: 'test', friendlyName: '/test' }),
    },
    dmt_SelectControl: {
      getCurrentDocumentInfo: async () => {
        if (state.active === null) return undefined;
        const pcb = state.active === 'pcb-1';
        return {
          uuid: state.active,
          tabId: `tab-${state.active}`,
          documentType: pcb ? DOC_TYPE.PCB : DOC_TYPE.SCHEMATIC_PAGE,
        };
      },
    },
    dmt_Schematic: {
      getAllSchematicsInfo: async () => [{ uuid: 'sch-1', name: 'Schematic1' }],
      getAllSchematicPagesInfo: async () => [
        { uuid: 'page-a1', name: 'P1.Schematic1', parentSchematicUuid: 'sch-1' },
      ],
      getCurrentSchematicPageInfo: async () =>
        state.active === 'page-a1' ? { uuid: 'page-a1' } : undefined,
    },
    dmt_Pcb: {
      getAllPcbsInfo: async () => [{ uuid: 'pcb-1', name: 'PCB1' }],
      getCurrentPcbInfo: async () => (state.active === 'pcb-1' ? { uuid: 'pcb-1' } : undefined),
    },
    dmt_EditorControl: { getSplitScreenTree: async () => ({ tabs: [], children: [] }) },
  };
  return { host, socket, state };
}

const BANNER = {
  event: 'banner',
  data: { server: 'boardwise', protocol: '1.0', expect: 'hello' },
};

test('the wired connector attaches the host\'s live context to a real action response', async (t) => {
  // The production path: `index.ts` hands the transport a reader built on
  // `actions.currentResponseContext`, and the value has to survive the whole
  // chain (facade → handler → frame) unchanged. A unit test on the reader
  // alone would not notice a wiring line that was never added.
  const { host, socket, state } = fakeHost();
  connector.__setFacadeForTests(createFacade(host));
  t.after(() => {
    connector.deactivate();
    connector.__setFacadeForTests(undefined);
  });

  await connector.activate();
  await socket.deliver(BANNER);
  await socket.deliver({ id: 'r1', action: 'doc.list', params: {} });
  assert.ok(await waitFor(() => socket.answer('r1')), 'the action must be answered');
  assert.deepEqual(socket.answer('r1').context, {
    projectName: '/test',
    projectUuid: 'ea80fff642fa86cd',
    pageUuid: 'page-a1',
    pageType: 'sch',
  });

  // The user clicks the PCB tab. The next answer must say so — this is the
  // whole reason the context is per response rather than per connection.
  state.active = 'pcb-1';
  await socket.deliver({ id: 'r2', action: 'doc.list', params: {} });
  assert.ok(await waitFor(() => socket.answer('r2')), 'the second action must be answered');
  assert.equal(socket.answer('r2').context.pageType, 'pcb');
  assert.equal(socket.answer('r2').context.pageUuid, 'pcb-1');
  // ...and the action's own result is still the action's own result.
  assert.ok(socket.answer('r2').data.documents.some((row) => row.uuid === 'pcb-1'));
  assert.equal('context' in socket.answer('r2').data, false);
});
