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

/**
 * A dotted version string as numbers, or `null` when it is not one.
 *
 * Deliberately strict: `'unknown'` is a real value in this codebase
 * ({@link VERSION} answers it for a build with no define), and a comparison
 * that treated it as `0.0.0` would report every such build as outdated. An
 * unparsable side makes the comparison *unanswerable*, which is what the
 * caller has to hear (018 §B3: a missing `minConnectorVersion` must be silent,
 * not a warning).
 */
export function parseVersion(value: unknown): number[] | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim().replace(/^v/i, '');
  if (!/^\d+(?:\.\d+)*$/.test(trimmed)) return null;
  return trimmed.split('.').map((part) => Number(part));
}

/**
 * `-1` when `left` is older, `1` when newer, `0` when equal — `null` when
 * either side is not a version. Missing segments count as zero, so `0.4` and
 * `0.4.0` compare equal.
 */
export function compareVersions(left: unknown, right: unknown): number | null {
  const a = parseVersion(left);
  const b = parseVersion(right);
  if (!a || !b) return null;
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    const x = a[i] ?? 0;
    const y = b[i] ?? 0;
    if (x !== y) return x < y ? -1 : 1;
  }
  return 0;
}

/** Is `version` older than `minimum`? `null` when that cannot be decided. */
export function isVersionOlder(version: unknown, minimum: unknown): boolean | null {
  const order = compareVersions(version, minimum);
  return order === null ? null : order < 0;
}
