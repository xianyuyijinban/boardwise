/**
 * Build script.
 *
 * Two outputs, on purpose:
 *
 * - `dist/index.js` — the sideloadable artifact. EasyEDA reads a global
 *   variable produced by esbuild's `--format=iife --global-name=…`; the name
 *   `edaEsbuildExportName` matches what the official scaffolding and the
 *   `easyeda-agent` extension (MIT) both produce, so the editor finds our
 *   `activate` / menu functions where it expects them.
 * - `dist/esm/*.js` — the same sources as plain ESM, so `node --test` can
 *   exercise the real modules without an editor.
 */

import { build } from 'esbuild';
import { rm } from 'node:fs/promises';
import { readFileSync } from 'node:fs';

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'));
const manifest = JSON.parse(readFileSync(new URL('./extension.json', import.meta.url), 'utf8'));

const shared = {
  bundle: true,
  target: 'es2020',
  logLevel: 'info',
  // The artifact must be able to name itself. "Did the sideload take?" was
  // unanswerable from the editor on 2026-09-14 — two loads looked successful
  // while the previous bundle kept running — so the version is baked in here
  // and reported by `sys.probe` and the About panel. The uuid joins it for
  // `sys.self_update`, which addresses the extension's IndexedDB records by
  // `<uuid>|dist/index.js` and must never guess it.
  define: {
    __BOARDWISE_VERSION__: JSON.stringify(pkg.version),
    __BOARDWISE_UUID__: JSON.stringify(manifest.uuid),
  },
};

await rm('dist', { recursive: true, force: true });

// 1. The extension artifact.
await build({
  ...shared,
  entryPoints: ['src/index.ts'],
  outfile: 'dist/index.js',
  format: 'iife',
  globalName: 'edaEsbuildExportName',
  platform: 'neutral',
});

// 2. ESM copies for the unit tests.
//
// `splitting` matters: without it every entry point inlines its own copy of
// `protocol.ts`, and `instanceof ActionError` then fails across module
// boundaries — the test build would not behave like the shipped bundle. With
// splitting, esbuild hoists the shared modules into one chunk that all entries
// import, so the tests exercise the same single-copy topology the editor sees.
await build({
  ...shared,
  entryPoints: [
    'src/index.ts',
    'src/actions.ts',
    'src/config.ts',
    'src/facade.ts',
    'src/protocol.ts',
    'src/random.ts',
    'src/self-update.ts',
    'src/transport.ts',
    'src/version.ts',
  ],
  outdir: 'dist/esm',
  format: 'esm',
  splitting: true,
  platform: 'node',
  outExtension: { '.js': '.mjs' },
  logLevel: 'warning',
});

console.log('boardwise connector: built dist/index.js and dist/esm/*.mjs');
