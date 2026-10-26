#!/usr/bin/env node
/**
 * Offline-only acceptance for the two 540B7 draw tools, against the real CLI.
 * No doctor/bridge call, no editor contact, no apply, and no artifact deletion.
 */
import { existsSync, mkdtempSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { apply } from '../lib/index.js'

const repoRoot = fileURLToPath(new URL('../..', import.meta.url)).replace(/[\\/]$/, '')
const venvPython = join(repoRoot, '.venv', 'Scripts', 'python.exe')
if ((process.env['BOARDWISE_EXE'] ?? '') === '' && existsSync(venvPython)) {
  process.env['BOARDWISE_EXE'] = venvPython
}

const tools = new Map()
apply({
  tools: {
    register: definition => {
      tools.set(definition.name, definition)
      return () => {}
    },
  },
})
const exec = { signal: new AbortController().signal }

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function call(name, args) {
  const tool = tools.get(name)
  assert(tool !== undefined, `tool not registered: ${name}`)
  return await tool.execute(args, exec)
}

const fixtureRoot = join(repoRoot, 'tests', 'fixtures', 'drawapply')
const out = mkdtempSync(join(tmpdir(), 'boardwise-draw-smoke-'))
const compiled = await call('boardwise_draw_compile', {
  circuit: join(fixtureRoot, 'divider.circuit.json'),
  presentation: join(fixtureRoot, 'divider.presentation.json'),
  profiles: join(fixtureRoot, 'library.json'),
  pageBox: '0,-1000,1200,0',
  out,
})
assert(compiled.command === 'compile', 'compile returned the wrong command envelope')
assert(compiled.ok === true, `offline divider compile was refused: ${JSON.stringify(compiled.failures)}`)
assert(Array.isArray(compiled.candidates) && compiled.candidates.length > 0, 'compile returned no candidates')
assert(Array.isArray(compiled.previews) && compiled.previews.length > 0, 'compile returned no previews')
for (const path of compiled.previews) {
  assert(existsSync(path) && statSync(path).size > 0, `preview is missing or empty: ${path}`)
}

// `draw compile` has a second payload shape: a page presentation is compiled by
// the page compiler and answers `document: "page"` + `pages` (no `candidates`).
// The scene below is the 057 page scene (`tests/test_057_draw_page_cli.py`'s
// `page_circuit` / `page_presentation`), written into this run's own temp dir —
// no test fixture or repo file is written or edited by this smoke.
const part = (id, symbolRef, value, lcsc) => ({ id, symbolRef, value, lcsc, provenance: 'verified_recipe' })
const net = (id, cls, members) => ({ id, class: cls, members, provenance: 'verified_recipe' })
const pageReport = join(out, 'page')
const pageCircuit = join(out, 'page.circuit.json')
const pagePresentation = join(out, 'page.presentation.json')
writeFileSync(pageCircuit, `${JSON.stringify({
  parts: [
    part('U1', 'AMS1117-3.3', 'AMS1117-3.3', 'C6186'),
    part('C1', 'C0402', '10uF', 'C15525'),
    part('C2', 'C0402', '22uF', 'C45783'),
    part('R1', 'R0402', '10k', 'C25744'),
    part('R2', 'R0402', '10k', 'C25744'),
  ],
  nets: [
    net('VIN', 'power', ['U1.3', 'C1.1', 'R1.1']),
    net('3V3', 'power', ['U1.2', 'C2.1']),
    net('TAP', 'signal', ['R1.2', 'R2.1']),
    net('GND', 'gnd', ['U1.1', 'C1.2', 'C2.2', 'R2.2']),
  ],
}, null, 2)}\n`, 'utf8')
writeFileSync(pagePresentation, `${JSON.stringify({
  modules: [
    { id: 'pwr', parts: ['U1', 'C1', 'C2'], role: 'regulator', grammarRef: 'ldo' },
    { id: 'sense', parts: ['R1', 'R2'], role: 'divider', grammarRef: 'voltage-divider' },
  ],
  flow: [['pwr', 'sense']],
  portRoles: { VIN: 'input', '3V3': 'output' },
  directWiringObligations: [{ nets: ['VIN', '3V3'], note: 'the regulator rails are wired' }],
}, null, 2)}\n`, 'utf8')

const page = await call('boardwise_draw_compile', {
  circuit: pageCircuit,
  presentation: pagePresentation,
  profiles: join(fixtureRoot, 'library.json'),
  pageBox: '0,0,1169,826',
  out: pageReport,
})
assert(page.command === 'compile', 'page compile returned the wrong command envelope')
assert(page.document === 'page', 'a two-module presentation must be compiled by the page compiler')
assert(page.ok === true, `offline page compile was refused: ${JSON.stringify(page.failures)}`)
assert(Array.isArray(page.pages) && page.pages.length > 0, 'page compile returned no pages')
assert(page.candidates === undefined, 'page compile must not be read for candidates')
assert(page.pages[0].modules.length === 2, 'the page candidate must carry both modules')
assert(Array.isArray(page.previews) && page.previews.length > 0, 'page compile returned no previews')
for (const path of page.previews) {
  assert(existsSync(path) && statSync(path).size > 0, `page preview is missing or empty: ${path}`)
}

const snapshot = join(out, 'lint-snapshot.json')
const render = join(out, 'lint-render.svg')
writeFileSync(snapshot, `${JSON.stringify({
  components: [{
    primitiveId: 'sheet1',
    state: {
      PrimitiveType: 'Component',
      ComponentType: 'sheet',
      PrimitiveId: 'sheet1',
    },
  }],
  wires: [],
  pins: [],
  netlabels: [],
  bboxes: { sheet1: { minX: 0, minY: 0, maxX: 1170, maxY: 825 } },
  meta: { sheets: ['sheet1'] },
}, null, 2)}\n`, 'utf8')
writeFileSync(render, '<svg></svg>\n', 'utf8')
const lint = await call('boardwise_draw_lint', { snapshot, render })
assert(lint.source === 'replay', 'lint did not use the offline replay source')
assert(lint.exitCode === 0, `empty synthetic page returned exit ${lint.exitCode}`)
assert(Array.isArray(lint.findings), 'lint findings is not an array')
assert(lint.counts && typeof lint.counts === 'object', 'lint counts is not an object')
assert(lint.textReadable === false, 'an empty SVG must disclose unreadable text geometry')

console.log(`PASS boardwise_draw_compile: ${compiled.candidates.length} candidate(s), ${compiled.previews.length} artifact(s)`)
console.log(`PASS boardwise_draw_compile (page): ${page.pages.length} page(s), ${page.previews.length} artifact(s)`)
console.log(`PASS boardwise_draw_lint: source=replay, exitCode=${lint.exitCode}, textReadable=${lint.textReadable}`)
console.log(`artifacts retained: ${out}`)
