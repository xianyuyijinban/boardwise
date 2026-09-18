/**
 * Contract drift guard (006c, work item 1).
 *
 * Adding a bridge action touches five places — the `ACTIONS` entry in
 * `protocol.py`, the handler in `actions.ts`, its registration in
 * `buildHandlers`, a test on each side, and the table in `docs/bridge.md` —
 * and until now **nothing compared the Python catalogue with the TypeScript
 * registry**. A one-sided addition was therefore a runtime `UNKNOWN_ACTION`
 * (or a daemon that never forwards to a handler that exists), discovered on
 * the machine instead of in CI.
 *
 * This reads both files as text and asserts the sets are equal. It found a
 * live instance on its first run: `sch.set_component_value`, the pre-0.3.18
 * name of `sch.set_component_attribute`, was still registered in the
 * connector months after the catalogue had renamed it. The daemon refuses any
 * action outside `ACTIONS`, so that handler was unreachable dead weight that
 * looked like a working action.
 *
 * Scope, stated honestly: `daemon`-owned actions (`hello`, `ping`) are
 * answered inside the daemon and have no connector handler by design, so they
 * are excluded from the comparison — the rule is about the catalogue↔connector
 * contract, not about the catalogue's entire contents.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

/** Repo root, resolved from this file — works from any working directory. */
const ROOT = new URL('../../', import.meta.url);
const PROTOCOL = new URL('src/boardwise/bridge/protocol.py', ROOT);
const ACTIONS_TS = new URL('connector/src/actions.ts', ROOT);
const BRIDGE_DOC = new URL('docs/bridge.md', ROOT);

const read = (url) => readFileSync(url, 'utf8').replace(/\r\n/g, '\n');

/** Every `Action(...)` block of the `ACTIONS` tuple, as text. */
function catalogueBlocks(source) {
  const start = source.indexOf('ACTIONS: tuple[Action, ...] = (');
  assert.ok(start >= 0, 'the ACTIONS tuple is gone — did protocol.py move?');
  const end = source.indexOf('\n)\n', start);
  assert.ok(end > start, 'could not find the end of the ACTIONS tuple');
  const body = source.slice(start, end);

  const blocks = [];
  let cursor = 0;
  for (;;) {
    const at = body.indexOf('    Action(', cursor);
    if (at < 0) break;
    // A block runs to the next top-level closer.
    const close = body.indexOf('\n    ),', at);
    assert.ok(close > at, `Action block at offset ${at} is unterminated`);
    blocks.push(body.slice(at, close));
    cursor = close;
  }
  return blocks;
}

/** `{name, owner}` for every catalogue entry. */
export function catalogueEntries(source) {
  return catalogueBlocks(source).map((block) => {
    const name = /\n\s*name="([^"]+)"/.exec(block);
    assert.ok(name, `an Action block has no name= field:\n${block}`);
    const owner = /\n\s*owner="([^"]+)"/.exec(block);
    return { name: name[1], owner: owner ? owner[1] : 'connector' };
  });
}

/** Keys of the `buildHandlers` registry. */
export function registryKeys(source) {
  const start = source.indexOf('export function buildHandlers');
  assert.ok(start >= 0, 'buildHandlers is gone — did actions.ts move?');
  const end = source.indexOf('\n  };', start);
  assert.ok(end > start, 'could not find the end of the handler registry');
  const body = source.slice(start, end);
  const keys = [];
  const pattern = /^\s*'([^']+)':\s*bind\(/gm;
  for (const match of body.matchAll(pattern)) keys.push(match[1]);
  return keys;
}

/** Action names in the `docs/bridge.md` §4 table's first column. */
export function documentedActions(source) {
  const start = source.indexOf('## 4. Action catalogue');
  assert.ok(start >= 0, 'the §4 action catalogue is gone from docs/bridge.md');
  const end = source.indexOf('## 5. Error codes', start);
  const body = source.slice(start, end > start ? end : undefined);
  const names = [];
  const pattern = /^\| `([a-z_][a-z_.]+)`/gm;
  for (const match of body.matchAll(pattern)) names.push(match[1]);
  return names;
}

test('the catalogue and the connector registry list the same actions', () => {
  const catalogue = catalogueEntries(read(PROTOCOL));
  const connectorOwned = catalogue
    .filter((entry) => entry.owner === 'connector')
    .map((entry) => entry.name)
    .sort();
  const registry = registryKeys(read(ACTIONS_TS)).sort();

  // Sanity: both sides must be real, non-empty parses. A guard that compares
  // two empty sets passes forever while protecting nothing.
  assert.ok(catalogue.length > 10, `parsed only ${catalogue.length} catalogue entries`);
  assert.ok(registry.length > 10, `parsed only ${registry.length} registry keys`);
  assert.ok(
    catalogue.some((entry) => entry.owner === 'daemon'),
    'the daemon-owned actions disappeared — is the owner= parse still right?',
  );

  const inCatalogueOnly = connectorOwned.filter((name) => !registry.includes(name));
  const inRegistryOnly = registry.filter((name) => !connectorOwned.includes(name));

  assert.deepEqual(
    inCatalogueOnly,
    [],
    'in protocol.py but with no handler in actions.ts — the daemon will forward '
      + 'these and the connector will answer UNKNOWN_ACTION',
  );
  assert.deepEqual(
    inRegistryOnly,
    [],
    'registered in actions.ts but absent from ACTIONS — the daemon refuses these '
      + 'before they are ever forwarded, so the handler is unreachable dead code',
  );
  assert.deepEqual(registry, connectorOwned);
});

test('the documentation table lists exactly the catalogue', () => {
  // `docs/bridge.md` is the fifth touchpoint of adding an action, and the one
  // a reader trusts. Measured 2026-09-16: eleven actions were missing from it
  // (seven had been drifting for several rounds) — the table had stopped being
  // a description of the catalogue and become a partial memory of it.
  const catalogue = catalogueEntries(read(PROTOCOL)).map((entry) => entry.name).sort();
  const documented = documentedActions(read(BRIDGE_DOC)).sort();

  assert.ok(documented.length > 10, `parsed only ${documented.length} documented rows`);
  const undocumented = catalogue.filter((name) => !documented.includes(name));
  const invented = documented.filter((name) => !catalogue.includes(name));
  assert.deepEqual(
    undocumented,
    [],
    'in the catalogue but missing from the docs/bridge.md §4 table — a reader '
      + 'cannot discover these',
  );
  assert.deepEqual(
    invented,
    [],
    'documented in docs/bridge.md but absent from ACTIONS — the docs promise an '
      + 'action the daemon will refuse',
  );
  assert.deepEqual(documented, catalogue);
});

test('the guard actually fires when one side drifts', () => {
  // Positive control, in the spirit of source-guard.test.mjs: the comparison
  // above is only worth anything if removing an entry from either side turns
  // it red. This simulates both directions on real text.
  const catalogue = read(PROTOCOL);
  const registry = read(ACTIONS_TS);

  const droppedHandler = registry.replace(
    /^\s*'sch\.geometry':\s*bind\(schGeometry\),\n/m,
    '',
  );
  assert.notEqual(droppedHandler, registry, 'the simulation did not change the text');
  const afterDrop = registryKeys(droppedHandler).sort();
  const connectorOwned = catalogueEntries(catalogue)
    .filter((entry) => entry.owner === 'connector')
    .map((entry) => entry.name)
    .sort();
  assert.ok(
    connectorOwned.some((name) => !afterDrop.includes(name)),
    'dropping a handler did not produce a catalogue-only entry',
  );

  const droppedEntry = catalogue.replace(/\n\s*name="sch\.geometry",/, '\n        name="sch.geometryGONE",');
  assert.notEqual(droppedEntry, catalogue, 'the simulation did not change the text');
  const renamed = catalogueEntries(droppedEntry)
    .filter((entry) => entry.owner === 'connector')
    .map((entry) => entry.name);
  assert.ok(
    renamed.includes('sch.geometryGONE') && !renamed.includes('sch.geometry'),
    'renaming a catalogue entry was not picked up by the parser',
  );
  const stillRegistered = registryKeys(registry).sort();
  assert.ok(
    stillRegistered.includes('sch.geometry') && !renamed.includes('sch.geometry'),
    'renaming a catalogue entry did not produce a registry-only entry',
  );
});
