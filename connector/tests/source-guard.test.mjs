/**
 * Source guards: rules about *shape* that only a source reader can enforce.
 *
 * Both rules exist because of the same failure. On 2026-09-13 an on-machine
 * session measured that the editor's extension host binds `eda` as a context
 * global rather than a property of `globalThis`, while *every* test passed —
 * because every test injects a fake socket and therefore never exercises the
 * one line in production that reaches for the editor.
 *
 * A guard is cheap, dumb, and impossible to satisfy "in spirit" while breaking
 * it in the code, which is exactly what was missing. Neither rule can be
 * replaced by a behavioural test: the behaviour depends on a host we do not
 * have in CI.
 */

import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const SRC = fileURLToPath(new URL('../src/', import.meta.url));

/** `globalThis.eda`, `(globalThis as ...).eda`, `globalThis['eda']` — all forbidden. */
const FORBIDDEN_GLOBAL = /globalThis[^\n;]*\beda\b/;

/**
 * The single module allowed to touch the host global. It is the seam: one
 * function reads `eda`, everything else takes the result as a parameter.
 */
const FACADE = 'facade.ts';

/** A property access on the host global: `eda.sys_WebSocket`, `eda?.sys_Log`. */
const CODE_EDA = /\beda\s*\??\./;

/**
 * The same rule, for the second host global that bit us.
 *
 * On 2026-09-13 the real editor reported `token: NONE — this editor cannot
 * generate one`, i.e. the bare `crypto` identifier did not resolve there either
 * — the same assumption, in a different module, again invisible to every test
 * (0.2.1, see `random.ts`). Confining the read to one file is what makes the
 * next occurrence a one-line change instead of a hardware session.
 *
 * Scope, stated honestly: like the `eda` rule this guards the *property access*
 * shape (`crypto.getRandomValues`), which is what host-reaching code actually
 * writes. A bare `const x = crypto;` elsewhere would slip through — as it does
 * for `eda`. Widen both together if that ever matters.
 */
const RANDOM = 'random.ts';

/** `globalThis.crypto`, `(globalThis as ...).crypto` — forbidden. */
const FORBIDDEN_CRYPTO_GLOBAL = /globalThis[^\n;]*\bcrypto\b/;

/** A property access on the ambient `crypto`: `crypto.getRandomValues`. */
const CODE_CRYPTO = /\bcrypto\s*\??\./;

const sources = () => readdirSync(SRC).filter((name) => name.endsWith('.ts'));
const read = (name) => readFileSync(new URL(`../src/${name}`, import.meta.url), 'utf8');

/**
 * Remove comments, so the places we *document* a trap cannot trip a guard.
 * Line-based: every comment in this codebase is line-oriented on purpose.
 */
function codeLines(text) {
  return text
    .split('\n')
    .map((line, index) => ({ line, number: index + 1 }))
    .filter(({ line }) => {
      const trimmed = line.trimStart();
      return !(
        trimmed.startsWith('//') ||
        trimmed.startsWith('*') ||
        trimmed.startsWith('/*')
      );
    });
}

/** Blank out string literals: `'eda.sys_WebSocket is unavailable'` is a message, not a reference. */
function withoutLiterals(line) {
  return line
    .replace(/'(?:[^'\\]|\\.)*'/g, "''")
    .replace(/"(?:[^"\\]|\\.)*"/g, '""')
    .replace(/`(?:[^`\\]|\\.)*`/g, '``');
}

test('src never resolves eda via globalThis', () => {
  const files = sources();
  assert.ok(files.length > 0, 'no sources found — is this test in the right place?');
  for (const name of files) {
    for (const { line, number } of codeLines(read(name))) {
      assert.equal(
        FORBIDDEN_GLOBAL.test(line),
        false,
        `${name}:${number} reaches for eda through globalThis: ${line.trim()}`,
      );
    }
  }
});

test('only the facade touches the host eda global', () => {
  const files = sources();
  assert.ok(files.length > 0, 'no sources found — is this test in the right place?');

  for (const name of files) {
    if (name === FACADE) continue;
    for (const { line, number } of codeLines(read(name))) {
      assert.equal(
        CODE_EDA.test(withoutLiterals(line)),
        false,
        `${name}:${number} uses the host eda global directly. ` +
          `Pass it through the ${FACADE} instead (see its module docstring): ${line.trim()}`,
      );
    }
  }
});

test('the facade exemption is not a hole', () => {
  // If the facade stopped touching `eda`, the exemption above would silently
  // start protecting nothing — and the next `eda.` elsewhere would be the only
  // reference in the program, unguarded and unexplained.
  const source = read(FACADE);
  assert.ok(
    /\bdeclare const eda\b/.test(source),
    `${FACADE} no longer declares the host global — either the seam moved ` +
      '(update FACADE) or this exemption is hiding something',
  );
  assert.ok(
    source.includes('return eda;'),
    `${FACADE} no longer reads the host global; the single reference should be ` +
      'one obvious `return eda;` inside a try/catch',
  );
});

test('src never resolves crypto via globalThis', () => {
  const files = sources();
  assert.ok(files.length > 0, 'no sources found — is this test in the right place?');
  for (const name of files) {
    for (const { line, number } of codeLines(read(name))) {
      assert.equal(
        FORBIDDEN_CRYPTO_GLOBAL.test(line),
        false,
        `${name}:${number} reaches for crypto through globalThis: ${line.trim()}`,
      );
    }
  }
});

test('only random.ts touches the ambient crypto global', () => {
  const files = sources();
  for (const name of files) {
    if (name === RANDOM) continue;
    for (const { line, number } of codeLines(read(name))) {
      assert.equal(
        CODE_CRYPTO.test(withoutLiterals(line)),
        false,
        `${name}:${number} reads the ambient crypto directly. ` +
          `Use ${RANDOM} (see its module docstring), which reports the source ` +
          `instead of hiding it: ${line.trim()}`,
      );
    }
  }
});

test('the random exemption is not a hole', () => {
  // Same reasoning as the facade: if this file stopped reading the global, the
  // exemption would protect nothing while the guard still looked green.
  const source = read(RANDOM);
  assert.ok(
    source.includes('return crypto;'),
    `${RANDOM} no longer reads the ambient global; the single reference should ` +
      'be one obvious `return crypto;` inside a try/catch',
  );
  assert.ok(
    /describeRandomHost/.test(source) && /source: /.test(source),
    `${RANDOM} must keep reporting which source produced the token — the point ` +
      'of 0.2.1 was to stop generating silently',
  );
});

test('the guards actually fire on the original bug shapes', () => {
  // The exact getter line that caused the outage — if the regex stops
  // matching this, the guard is dead weight and must be fixed, not weakened.
  const originalBug = 'return this.options.socket ?? (globalThis as { eda?: unknown }).eda;';
  assert.ok(FORBIDDEN_GLOBAL.test(originalBug));
  assert.ok(FORBIDDEN_GLOBAL.test('const api = globalThis.eda;'));
  assert.ok(FORBIDDEN_GLOBAL.test("const api = globalThis['eda'];"));

  assert.ok(CODE_EDA.test('socket: eda.sys_WebSocket,'));
  assert.ok(CODE_EDA.test('api?.sys_Log?.add?.(line)'.replace('api', 'eda')));
  assert.ok(CODE_EDA.test('const ctl = eda.dmt_EditorControl;'));

  // Sanity: the allowed patterns must keep passing.
  assert.equal(FORBIDDEN_GLOBAL.test('const token = globalThis.BOARDWISE_TOKEN;'), false);
  assert.equal(FORBIDDEN_GLOBAL.test('declare const eda: any;'), false);
  assert.equal(CODE_EDA.test("throw new Error('eda.sys_WebSocket is unavailable')"), true);
  assert.equal(
    CODE_EDA.test(withoutLiterals("throw new Error('eda.sys_WebSocket is unavailable')")),
    false,
    'a message that names eda is not a reference to it',
  );
  assert.equal(CODE_EDA.test(withoutLiterals('  socket: host().websocket,')), false);
});

test('the crypto guards fire on the shapes that bit us', () => {
  // What 0.2.0 shipped, verbatim.
  assert.ok(CODE_CRYPTO.test('crypto.getRandomValues(bytes);'));
  assert.ok(CODE_CRYPTO.test('const rng = crypto?.getRandomValues;'));

  // The spelling that looks right and is the whole reason for the rule.
  assert.ok(FORBIDDEN_CRYPTO_GLOBAL.test('const c = globalThis.crypto;'));
  assert.ok(FORBIDDEN_CRYPTO_GLOBAL.test('(globalThis as { crypto?: unknown }).crypto'));

  // Sanity: the allowed patterns must keep passing.
  assert.equal(FORBIDDEN_CRYPTO_GLOBAL.test('const api = globalThis.eda;'), false);
  assert.equal(CODE_CRYPTO.test(withoutLiterals("return 'crypto=unavailable';")), false);
  assert.equal(CODE_CRYPTO.test(withoutLiterals('  describeRandomHost(cryptoGlobal)')), false);
  assert.equal(CODE_CRYPTO.test('pickCrypto(host)'), false, 'capitalised names are local helpers');
});

/** The bundle the editor actually loads. */
const BUNDLE = fileURLToPath(new URL('../dist/index.js', import.meta.url));

test('a prototype read is never taken bare (the walk that killed every read action)', () => {
  // 2026-09-14, on the machine: `sch.geometry`, `sch.readback`, the three
  // `document.current` info boxes and the probe's enumeration ALL failed with
  // `TypeError: Cannot read properties of undefined (reading 'prototype')`.
  // The stack — captured in the error's `detail`, the instrument added in the
  // same round — pointed at the *loop condition* of `walkPrototypeNames`:
  // `current !== Function.prototype` is a property read sitting outside every
  // `try`, and this host's `Function` is an exotic object whose `.prototype`
  // access throws. The per-level guards inside the loop never got to run.
  //
  // No behavioural test can catch this one: it needs a host CI does not have.
  // So the shipped bundle is read, and the bare read is forbidden outright.
  const bundle = readFileSync(BUNDLE, 'utf8');
  assert.equal(
    bundle.includes('Function.prototype'),
    false,
    'Function.prototype must be read once and guarded (PROTOTYPE_STOPS), never inline',
  );
  // Sanity: the guard is looking at real code, not at an empty file.
  assert.ok(bundle.includes('PROTOTYPE_STOPS'), 'the guarded stop list must be in the bundle');
});

test('the artifact carries its own version (so "did the sideload take?" is answerable)', () => {
  // 2026-09-14: two sideloads in a row looked successful while the editor kept
  // executing the previous bundle, and the only symptom was a stack naming a
  // line that had already been fixed — a round trip spent on a question the
  // artifact can answer itself. `build.mjs` bakes in `package.json`'s version
  // and `sys.probe` reports it, so a single CLI call settles which build is
  // actually live.
  const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
  const bundle = readFileSync(BUNDLE, 'utf8');
  assert.ok(
    bundle.includes(`"${pkg.version}"`),
    `the bundle must carry its own version (${pkg.version}) — is the build.mjs define missing?`,
  );
  assert.ok(
    bundle.includes('connector: VERSION'),
    'sys.probe must report the connector version',
  );
});
