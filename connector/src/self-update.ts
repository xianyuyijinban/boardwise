/**
 * `sys.self_update` — hot-update the connector inside the running editor.
 *
 * The pain this removes: EasyEDA evaluates an extension bundle exactly once,
 * at load, and dedups installs by uuid — so swapping versions used to mean
 * uninstall → import → restart the editor (a version bump alone silently fails
 * the import).
 *
 * The working path, ported from the reference
 * (`easyeda-agent_RE/extension/scripts/hot-reload-inject.js`, live-verified):
 * installed extensions live in the editor page's IndexedDB — the desktop
 * client is a Chromium webview — so overwriting the bundle record and bumping
 * the stored version, then reloading the page, makes the editor run the new
 * code. No extra WS server and no console injection: this connector already
 * runs in the editor page and already has the daemon channel, so the bundle
 * arrives as an action payload.
 *
 * The layout being written (EasyEDA-internal, measured `_v6` today):
 *
 * - database `User_<teamUuid>_v6`, found by *enumerating*
 *   `indexedDB.databases()` — the connector cannot know the team uuid, and
 *   zero or several matches are both reported, never guessed;
 * - store `extensionsObjectStorage`, key `<uuid>|dist/index.js`, whose
 *   `source` field is a `File` — the extension's only executable;
 * - store `extensionsIndex`, key `<uuid>`, carrying `config` (the parsed
 *   `extension.json`), `isEnable`, `isAllowExternalInteractions`, `fileIndex`,
 *   `fileSize`.
 *
 * **Only `config.version` and `fileSize` are touched in the index record** —
 * `isAllowExternalInteractions` is the user's grant and must survive the
 * update, or the new build wakes up unable to call any `eda.*` API.
 *
 * Every step validates and fails loudly: the schema is not an official API
 * and an editor upgrade may change it. A failure means "fall back to a
 * manual uninstall + import", and the error says so — never a silent degrade.
 *
 * Ordering guarantee: the handler resolves *before* the reload is scheduled,
 * and the transport sends the response frame synchronously on resolution, so
 * the daemon always learns the outcome before the page goes away.
 *
 * `params.reload: false` (528A, `boardwise bridge update-connector
 * --no-reload`) is the one opt-out: the record is written and the page is left
 * alone, so a caller with unsaved editor state can stage a build without losing
 * it. Nothing runs until EasyEDA re-evaluates the extension — opening the
 * boardwise menu once does that (measured 2026-10-17, R4 experiment ④) — and
 * the reply says so by carrying `reloadInMs: 0`. Anything else — including an
 * absent field — keeps the original write-then-reload behaviour unchanged.
 */

import { ActionError } from './protocol';
import { EXTENSION_UUID } from './version';

/** The bundle lands under this path inside the extension's records. */
const BUNDLE_PATH = 'dist/index.js';
const DB_NAME_PATTERN = /^User_.+_v6$/;
const FILE_STORE = 'extensionsObjectStorage';
const INDEX_STORE = 'extensionsIndex';
const RELOAD_DELAY_MS = 500;

const FALLBACK_HINT = 'fall back to a manual uninstall + import of the .eext';

/** The slice of the host this action needs, resolved at call time. */
export type SelfUpdateDeps = {
  indexedDB: IDBFactory;
  location: { reload(): void };
  File: new (parts: BlobPart[], name: string, options?: FilePropertyBag) => File;
  setTimeout: (fn: () => void, ms: number) => unknown;
};

/**
 * Read the ambient globals **at call time**, never at module load.
 *
 * Standard Web APIs (`indexedDB`, `location`, `File`) are ordinary global
 * properties in the editor's realm — unlike the injected `eda`, which is why
 * `globalThis` is safe here while `globalThis.eda` is not. Resolving per call
 * keeps tests able to substitute fakes without a module seam.
 *
 * `needsReload` is the caller's reading of `params.reload` and it is there for
 * one reason (528A): `location.reload()` is only *used* when a reload is
 * actually going to be scheduled, so a `reload: false` request must not be
 * refused for a realm that lacks it — that would reject "please do not touch my
 * page" because the page cannot be touched. The other three globals are needed
 * either way: the write is the same write.
 */
function ambientDeps(needsReload: boolean): SelfUpdateDeps {
  const g = globalThis as Record<string, unknown>;
  if (typeof g.indexedDB !== 'object' || g.indexedDB === null) {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      `this realm exposes no IndexedDB — the self-update path is impossible here; ${FALLBACK_HINT}`,
    );
  }
  if (typeof (g.indexedDB as IDBFactory).databases !== 'function') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      `indexedDB.databases() is missing, so the extensions database cannot be found without guessing a name; ${FALLBACK_HINT}`,
    );
  }
  const location = g.location as { reload?: unknown } | undefined;
  if (needsReload && (!location || typeof location.reload !== 'function')) {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      'this realm has no location.reload() — without it the new bundle would be written but never run',
    );
  }
  if (typeof g.File !== 'function') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      'this realm has no File constructor — the IndexedDB record holds File objects, nothing else will do',
    );
  }
  return {
    indexedDB: g.indexedDB as IDBFactory,
    // Only ever called when `needsReload`, which is the case that just proved
    // it exists; the cast is what keeps that proof and the type in one place.
    location: (location ?? {}) as { reload(): void },
    File: g.File as SelfUpdateDeps['File'],
    setTimeout: (fn, ms) => (g.setTimeout as SelfUpdateDeps['setTimeout'])(fn, ms),
  };
}

function requestToPromise<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('IndexedDB request failed'));
  });
}

function openDatabase(idb: IDBFactory, name: string): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = idb.open(name);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () =>
      reject(request.error ?? new Error(`opening IndexedDB ${name} failed`));
  });
}

function idbError(store: string, error: unknown): ActionError {
  return new ActionError(
    'CONNECTOR_ERROR',
    `IndexedDB ${store} write/read failed: ${String((error as Error)?.message ?? error)} — ${FALLBACK_HINT}`,
  );
}

async function storeGet(db: IDBDatabase, store: string, key: string): Promise<unknown> {
  try {
    return await requestToPromise(
      db.transaction(store, 'readonly').objectStore(store).get(key),
    );
  } catch (error) {
    throw idbError(store, error);
  }
}

/**
 * Put with or without an explicit key, depending on the store's keyPath —
 * the spellings differ and passing a key to an in-line-key store throws.
 */
async function storePut(db: IDBDatabase, store: string, value: unknown, key: string): Promise<void> {
  try {
    const objectStore = db.transaction(store, 'readwrite').objectStore(store);
    const request =
      objectStore.keyPath == null ? objectStore.put(value as any, key) : objectStore.put(value as any);
    await requestToPromise(request);
  } catch (error) {
    throw idbError(store, error);
  }
}

/**
 * The handler itself. The `eda` parameter is unused — this action talks to
 * the *page's* storage, not the editor API — but the signature matches every
 * other handler so `buildHandlers` can bind it uniformly. `deps` defaults to
 * the ambient globals at call time; tests inject fakes.
 */
export async function sysSelfUpdate(
  params: Record<string, unknown>,
  _eda?: unknown,
  deps?: SelfUpdateDeps,
): Promise<Record<string, unknown>> {
  if (!EXTENSION_UUID) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      'this bundle does not know its own extension uuid (the build define is missing), so it cannot address its IndexedDB records',
    );
  }
  const bundleB64 = params.bundleB64;
  if (typeof bundleB64 !== 'string' || !bundleB64) {
    throw new ActionError(
      'BAD_REQUEST',
      'sys.self_update needs params.bundleB64: the new dist/index.js, base64-encoded',
    );
  }
  const version = params.version;
  if (typeof version !== 'string' || !version) {
    throw new ActionError(
      'BAD_REQUEST',
      'sys.self_update needs params.version: the version string to store in the index record',
    );
  }

  let bytes: Uint8Array<ArrayBuffer>;
  try {
    const binary = atob(bundleB64);
    bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
  } catch {
    throw new ActionError('BAD_REQUEST', 'params.bundleB64 is not valid base64');
  }

  // Resolved after validation on purpose: a malformed call is BAD_REQUEST on
  // every host, even one whose realm has no IndexedDB at all. `params.reload`
  // is read the same way it is read below — exact identity, not truthiness —
  // because that is the value `needsReload` has to describe: `reload: false`
  // is the only spelling that skips the reload, and therefore the only one that
  // may skip the `location.reload` requirement (`ambientDeps`, 528A).
  const reload = params.reload !== false;
  const host = deps ?? ambientDeps(reload);

  // Find the extensions database by enumerating, never by guessing the team
  // uuid. Zero matches means the schema changed (or no user data exists yet);
  // several means the name alone cannot disambiguate. Both are reported.
  const databases = await host.indexedDB.databases();
  const matches = databases
    .map((info) => info.name ?? '')
    .filter((name) => DB_NAME_PATTERN.test(name));
  if (matches.length === 0) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `no IndexedDB database matching ${DB_NAME_PATTERN} (found: ${
        databases.map((info) => info.name ?? '?').join(', ') || 'none'
      }) — the editor's storage schema may have changed; ${FALLBACK_HINT}`,
    );
  }
  if (matches.length > 1) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `several IndexedDB databases match ${DB_NAME_PATTERN}: ${matches.join(', ')} — ` +
        `refusing to guess; ${FALLBACK_HINT}`,
    );
  }
  const database = matches[0];

  const db = await openDatabase(host.indexedDB, database).catch((error: unknown) => {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `could not open IndexedDB ${database}: ${String((error as Error)?.message ?? error)} — ${FALLBACK_HINT}`,
    );
  });
  try {
    for (const store of [FILE_STORE, INDEX_STORE]) {
      if (!db.objectStoreNames.contains(store)) {
        throw new ActionError(
          'CONNECTOR_ERROR',
          `IndexedDB ${database} has no object store ${store} — the editor's storage schema has changed; ${FALLBACK_HINT}`,
        );
      }
    }

    // Read BOTH records before writing anything: a missing index record must
    // not leave a half-updated install behind (new bundle, stale version).
    const fileKey = `${EXTENSION_UUID}|${BUNDLE_PATH}`;
    const fileRecord = (await storeGet(db, FILE_STORE, fileKey)) as Record<string, unknown> | undefined;
    if (!fileRecord || typeof fileRecord !== 'object') {
      throw new ActionError(
        'CONNECTOR_ERROR',
        `no file record ${fileKey} in ${database} — is this connector installed under uuid ${EXTENSION_UUID}?`,
        { fileKey, database },
      );
    }
    const indexRecord = (await storeGet(db, INDEX_STORE, EXTENSION_UUID)) as
      | Record<string, any>
      | undefined;
    if (!indexRecord || typeof indexRecord !== 'object') {
      throw new ActionError(
        'CONNECTOR_ERROR',
        `no index record for uuid ${EXTENSION_UUID} in ${database}`,
        { uuid: EXTENSION_UUID, database },
      );
    }
    if (!indexRecord.config || typeof indexRecord.config !== 'object') {
      throw new ActionError(
        'CONNECTOR_ERROR',
        `the index record for ${EXTENSION_UUID} has no config object — the editor's storage schema has changed; ${FALLBACK_HINT}`,
      );
    }

    // The executable record: `source` becomes a File of the new bundle.
    fileRecord.source = new host.File([bytes], 'index.js', {
      type: 'text/javascript',
    });
    await storePut(db, FILE_STORE, fileRecord, fileKey);

    // The index record: bump ONLY config.version and fileSize. The
    // permission grant (isAllowExternalInteractions) and isEnable are the
    // user's settings — an update that resets them would strand the new
    // build without the very API access this channel runs on.
    const oldVersion =
      typeof indexRecord.config.version === 'string' ? indexRecord.config.version : null;
    indexRecord.config.version = version;
    if (typeof indexRecord.fileSize === 'number') indexRecord.fileSize = bytes.length;
    await storePut(db, INDEX_STORE, indexRecord, EXTENSION_UUID);

    // The response frame is sent the moment this handler resolves; the reload
    // is scheduled behind a delay so the answer always reaches the daemon
    // before the page (and this socket) goes away.
    //
    // `reload: false` (528A) is the one case that schedules nothing: the write
    // is the whole request, and the reply's `reloadInMs: 0` is how the caller
    // learns not to wait for a page that is not coming back. Exact identity,
    // not truthiness — a caller that sends `reload: "false"` is asking for
    // something this action does not define, and the safe reading of an
    // unrecognised value is the documented behaviour (reload), not silence.
    // `reload` is computed above, before `ambientDeps`: a host with no
    // `location.reload` can still take a write that will not need it.
    if (reload) {
      host.setTimeout(() => host.location.reload(), RELOAD_DELAY_MS);
    }

    return {
      ok: true,
      oldVersion,
      newVersion: version,
      bytes: bytes.length,
      database,
      reloadInMs: reload ? RELOAD_DELAY_MS : 0,
    };
  } finally {
    db.close();
  }
}
