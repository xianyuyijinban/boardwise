/**
 * `sys.self_update` tests (0.4.3): the connector rewrites its own bundle in
 * the editor's extension IndexedDB and reloads the page.
 *
 * The IndexedDB here is a hand-rolled fake — requests fire their handlers on
 * a microtask, exactly like the real API's "set the handler after the request
 * exists" shape. The assertions that matter:
 *
 * - the two `put`s are checked field by field, above all that
 *   `isAllowExternalInteractions` (the user's permission grant) is untouched;
 * - the reload fires only AFTER the response frame has been sent — the daemon
 *   must always learn the outcome before the page goes away;
 * - every schema anomaly (no DB, several DBs, missing store, missing record)
 *   is an explicit error, never a silent skip.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { createFacade } from '../dist/esm/facade.mjs';
import * as connector from '../dist/esm/index.mjs';
import { EXTENSION_UUID } from '../dist/esm/version.mjs';

const FILE_KEY = `${EXTENSION_UUID}|dist/index.js`;
const DB_NAME = 'User_team-7_v6';
const NEW_VERSION = '9.9.9-test';
const BUNDLE_BYTES = new TextEncoder().encode('console.log("boardwise 9.9.9-test");\n');
const BUNDLE_B64 = Buffer.from(BUNDLE_BYTES).toString('base64');

/** Minimal editor host: only what the transport wiring touches. */
function host() {
  const hostObject = {
    sys_WebSocket: {
      register(id, uri, onMessage) {
        hostObject.__onMessage = onMessage;
      },
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

// --------------------------------------------------------------------------
// fake IndexedDB
// --------------------------------------------------------------------------

/** A request whose handlers fire on a microtask, once assigned. */
function idbRequest(result, error) {
  const request = { result, error: error ?? null };
  queueMicrotask(() => {
    if (error) request.onerror?.();
    else request.onsuccess?.();
  });
  return request;
}

/**
 * A fake `IDBDatabase`. `records` is `{store: {key: record}}`; every `put` is
 * recorded into `puts` so the test asserts what was written, field by field,
 * instead of inferring it from the records it handed out.
 */
function fakeDb({ stores, records, puts }) {
  return {
    objectStoreNames: { contains: (name) => stores.includes(name) },
    transaction(store) {
      return {
        objectStore(name) {
          return {
            // Out-of-line keys: the real stores are keyed by an explicit key,
            // which is the `put(value, key)` spelling the handler must use.
            keyPath: null,
            get: (key) => idbRequest(records[name]?.[key]),
            put: (value, key) => {
              puts.push({ store: name, key, value });
              return idbRequest(true);
            },
          };
        },
      };
    },
    closed: false,
    close() {
      this.closed = true;
    },
  };
}

function healthyRecords() {
  return {
    extensionsObjectStorage: {
      [FILE_KEY]: { path: 'dist/index.js', source: 'the OLD bundle' },
    },
    extensionsIndex: {
      [EXTENSION_UUID]: {
        config: { name: 'boardwise-connector', version: '0.4.2' },
        isEnable: true,
        isAllowExternalInteractions: true,
        fileIndex: 'file-index-1',
        fileSize: 100,
      },
    },
  };
}

/**
 * Install the page globals the action resolves at call time, and restore them
 * afterwards. `setTimeout` intercepts only the reload timer (500 ms) and
 * delegates everything else — the harness's own `waitFor` depends on it.
 */
function withPageGlobals(t, { dbNames = [DB_NAME], db } = {}) {
  const page = { reloads: 0, timers: [], opened: null };
  const realSetTimeout = globalThis.setTimeout;
  globalThis.indexedDB = {
    databases: async () => dbNames.map((name) => ({ name })),
    open: (name) => {
      page.opened = name;
      return idbRequest(db);
    },
  };
  globalThis.location = {
    reload() {
      page.reloads += 1;
    },
  };
  globalThis.setTimeout = (fn, ms) => {
    if (ms === 500) {
      page.timers.push(fn);
      return 0;
    }
    return realSetTimeout(fn, ms);
  };
  t.after(() => {
    delete globalThis.indexedDB;
    delete globalThis.location;
    globalThis.setTimeout = realSetTimeout;
  });
  return page;
}

// --------------------------------------------------------------------------
// the write path
// --------------------------------------------------------------------------

test('sys.self_update rewrites both records, preserves the grant, reloads last', async (t) => {
  const puts = [];
  const db = fakeDb({
    stores: ['extensionsObjectStorage', 'extensionsIndex'],
    records: healthyRecords(),
    puts,
  });
  const page = withPageGlobals(t, { db });
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sys.self_update', {
    bundleB64: BUNDLE_B64,
    version: NEW_VERSION,
  });
  assert.equal(frame.ok, true, JSON.stringify(frame.error));
  assert.equal(frame.data.ok, true);
  assert.equal(frame.data.oldVersion, '0.4.2');
  assert.equal(frame.data.newVersion, NEW_VERSION);
  assert.equal(frame.data.bytes, BUNDLE_BYTES.length);
  assert.equal(frame.data.database, DB_NAME);
  assert.equal(page.opened, DB_NAME);

  // Two writes, in this order: the executable record, then the index record.
  assert.equal(puts.length, 2);
  const [filePut, indexPut] = puts;

  assert.equal(filePut.store, 'extensionsObjectStorage');
  assert.equal(filePut.key, FILE_KEY);
  assert.ok(filePut.value.source instanceof File, 'source must be a File');
  assert.equal(filePut.value.source.name, 'index.js');
  assert.equal(filePut.value.source.type, 'text/javascript');
  assert.equal(filePut.value.source.size, BUNDLE_BYTES.length);
  assert.equal(
    await filePut.value.source.text(),
    Buffer.from(BUNDLE_BYTES).toString('utf8'),
  );
  // Fields that were on the record stay on it.
  assert.equal(filePut.value.path, 'dist/index.js');

  assert.equal(indexPut.store, 'extensionsIndex');
  assert.equal(indexPut.key, EXTENSION_UUID);
  assert.equal(indexPut.value.config.version, NEW_VERSION);
  assert.equal(indexPut.value.fileSize, BUNDLE_BYTES.length);
  // The two things that must NEVER be touched: the permission grant and the
  // enable flag — plus the unrelated fields.
  assert.equal(indexPut.value.isAllowExternalInteractions, true);
  assert.equal(indexPut.value.isEnable, true);
  assert.equal(indexPut.value.fileIndex, 'file-index-1');
  assert.equal(indexPut.value.config.name, 'boardwise-connector');

  assert.equal(db.closed, true, 'the database handle is released');

  // The ordering contract: the response frame (asserted above — `call`
  // returns only after it arrived) precedes ANY reload.
  assert.equal(page.reloads, 0, 'reload fired before the response was sent');
  assert.equal(page.timers.length, 1, 'the reload is scheduled exactly once');
  page.timers[0]();
  assert.equal(page.reloads, 1);
});

// --------------------------------------------------------------------------
// parameter validation
// --------------------------------------------------------------------------

test('sys.self_update validates bundleB64', async (t) => {
  const h = host();
  withEda(t, h);
  await connector.activate();

  for (const params of [
    { version: NEW_VERSION },
    { bundleB64: 42, version: NEW_VERSION },
    { bundleB64: '', version: NEW_VERSION },
  ]) {
    const frame = await call(h, 'sys.self_update', params);
    assert.equal(frame.ok, false);
    assert.equal(frame.error.code, 'BAD_REQUEST', JSON.stringify(params));
    assert.match(frame.error.message, /bundleB64/);
  }
});

test('sys.self_update validates version', async (t) => {
  const h = host();
  withEda(t, h);
  await connector.activate();

  for (const params of [
    { bundleB64: BUNDLE_B64 },
    { bundleB64: BUNDLE_B64, version: 42 },
    { bundleB64: BUNDLE_B64, version: '' },
  ]) {
    const frame = await call(h, 'sys.self_update', params);
    assert.equal(frame.ok, false);
    assert.equal(frame.error.code, 'BAD_REQUEST', JSON.stringify(params));
    assert.match(frame.error.message, /version/);
  }
});

test('sys.self_update rejects undecodable base64', async (t) => {
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sys.self_update', {
    bundleB64: '!!!not-base64!!!',
    version: NEW_VERSION,
  });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'BAD_REQUEST');
  assert.match(frame.error.message, /base64/);
});

// --------------------------------------------------------------------------
// schema anomalies: explicit errors, never a silent degrade
// --------------------------------------------------------------------------

test('sys.self_update reports a realm without IndexedDB', async (t) => {
  // No withPageGlobals: Node has no indexedDB of its own.
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sys.self_update', {
    bundleB64: BUNDLE_B64,
    version: NEW_VERSION,
  });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'NOT_IMPLEMENTED');
  assert.match(frame.error.message, /IndexedDB/);
});

test('sys.self_update refuses zero or several extension databases', async (t) => {
  const h = host();
  withEda(t, h);
  await connector.activate();

  withPageGlobals(t, { dbNames: ['UserSettings', 'OtherDB'] });
  const none = await call(h, 'sys.self_update', {
    bundleB64: BUNDLE_B64,
    version: NEW_VERSION,
  });
  assert.equal(none.ok, false);
  assert.equal(none.error.code, 'CONNECTOR_ERROR');
  assert.match(none.error.message, /no IndexedDB database matching/);
  assert.match(none.error.message, /UserSettings, OtherDB/, 'what WAS found is named');

  // Swap the enumeration mid-test; the globals are resolved per call.
  globalThis.indexedDB.databases = async () =>
    ['User_team-a_v6', 'User_team-b_v6'].map((name) => ({ name }));
  const several = await call(h, 'sys.self_update', {
    bundleB64: BUNDLE_B64,
    version: NEW_VERSION,
  });
  assert.equal(several.ok, false);
  assert.equal(several.error.code, 'CONNECTOR_ERROR');
  assert.match(several.error.message, /several IndexedDB databases/);
  assert.match(several.error.message, /refusing to guess/);
});

test('sys.self_update names a missing object store', async (t) => {
  const puts = [];
  const db = fakeDb({ stores: ['extensionsIndex'], records: healthyRecords(), puts });
  withPageGlobals(t, { db });
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sys.self_update', {
    bundleB64: BUNDLE_B64,
    version: NEW_VERSION,
  });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'CONNECTOR_ERROR');
  assert.match(frame.error.message, /no object store extensionsObjectStorage/);
  assert.equal(puts.length, 0, 'nothing is written when the schema does not match');
});

test('sys.self_update names a missing file record', async (t) => {
  const puts = [];
  const records = healthyRecords();
  delete records.extensionsObjectStorage[FILE_KEY];
  const db = fakeDb({
    stores: ['extensionsObjectStorage', 'extensionsIndex'],
    records,
    puts,
  });
  withPageGlobals(t, { db });
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sys.self_update', {
    bundleB64: BUNDLE_B64,
    version: NEW_VERSION,
  });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'CONNECTOR_ERROR');
  assert.match(frame.error.message, /no file record/);
  assert.equal(puts.length, 0);
});

test('sys.self_update names a missing index record (and writes nothing)', async (t) => {
  const puts = [];
  const records = healthyRecords();
  delete records.extensionsIndex[EXTENSION_UUID];
  const db = fakeDb({
    stores: ['extensionsObjectStorage', 'extensionsIndex'],
    records,
    puts,
  });
  withPageGlobals(t, { db });
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sys.self_update', {
    bundleB64: BUNDLE_B64,
    version: NEW_VERSION,
  });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'CONNECTOR_ERROR');
  assert.match(frame.error.message, /no index record/);
  assert.equal(puts.length, 0, 'both records are read before anything is written');
});

test('sys.self_update refuses an index record with no config object', async (t) => {
  const puts = [];
  const records = healthyRecords();
  delete records.extensionsIndex[EXTENSION_UUID].config;
  const db = fakeDb({
    stores: ['extensionsObjectStorage', 'extensionsIndex'],
    records,
    puts,
  });
  withPageGlobals(t, { db });
  const h = host();
  withEda(t, h);
  await connector.activate();

  const frame = await call(h, 'sys.self_update', {
    bundleB64: BUNDLE_B64,
    version: NEW_VERSION,
  });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'CONNECTOR_ERROR');
  assert.match(frame.error.message, /no config object/);
  assert.equal(puts.length, 0, 'a schema anomaly is refused before any write');
});
