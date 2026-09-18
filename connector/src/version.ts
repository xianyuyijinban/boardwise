/**
 * The build's own version, injected by the bundler.
 *
 * Why this exists: on 2026-09-14 "which build is the editor actually running?"
 * was unanswerable from the machine. Two sideloads in a row looked successful
 * while the editor kept executing the previous bundle, and the only symptom was
 * a stack trace pointing at a line that had already been fixed — a whole round
 * trip spent on a question the artifact could answer itself.
 *
 * `build.mjs` defines `__BOARDWISE_VERSION__` from `package.json`, so a bundle
 * always carries the version it was built from. Written as a `typeof` test so
 * that a build *without* the define answers `'unknown'` instead of throwing a
 * `ReferenceError` at module load — the same "never let the diagnostic be the
 * thing that fails" rule the log panel follows.
 */

declare const __BOARDWISE_VERSION__: string;

export const VERSION: string =
  typeof __BOARDWISE_VERSION__ === 'string' ? __BOARDWISE_VERSION__ : 'unknown';

/**
 * The extension's own uuid, injected the same way from `extension.json`.
 *
 * `sys.self_update` needs it to address the connector's records in the
 * editor's IndexedDB (`<uuid>|dist/index.js`); a bundle built without the
 * define answers `''`, which the action reports as an explicit error rather
 * than writing to a record keyed `'|dist/index.js'`.
 */
declare const __BOARDWISE_UUID__: string;

export const EXTENSION_UUID: string =
  typeof __BOARDWISE_UUID__ === 'string' ? __BOARDWISE_UUID__ : '';
