#!/usr/bin/env node
/**
 * Standalone smoke test for the built plugin (task 045, acceptance §2).
 *
 * It imports `lib/index.js` — the artifact `npm pack` ships — registers the four
 * tools against a fake Cordis Context, and executes them for real against the
 * local boardwise CLI. Read-only by construction: doctor's online checks and the
 * two offline reports, plus the error paths. No bridge action is ever called,
 * so nothing here can touch the design open in the editor.
 *
 *   node scripts/smoke.mjs            # BOARDWISE_EXE defaults to the repo venv
 *   BOARDWISE_EXE=<exe> node scripts/smoke.mjs
 */
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { apply, inject, name } from '../lib/index.js'

const repoRoot = fileURLToPath(new URL('../..', import.meta.url)).replace(/[\\/]$/, '')
const VENV_PYTHON = join(repoRoot, '.venv', 'Scripts', 'python.exe')
const FIXTURE = join(repoRoot, 'tests', 'fixtures', 'ch340_golden.epro2')

/** Point the plugin at the checkout's interpreter unless the caller chose one. */
if ((process.env['BOARDWISE_EXE'] ?? '') === '' && existsSync(VENV_PYTHON)) {
  process.env['BOARDWISE_EXE'] = VENV_PYTHON
}

/** What `apply` registered, keyed by tool name. */
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
const failures = []
const created = []

async function call(toolName, args) {
  const tool = tools.get(toolName)
  if (tool === undefined) throw new Error(`tool not registered: ${toolName}`)
  return await tool.execute(args, exec)
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

function exitOf(text) {
  return /: exit (\d+|none)/.exec(text)?.[1] ?? null
}

/** The stdout block of one tool result, for the log. */
function stdoutOf(text) {
  const start = text.indexOf('--- stdout ---')
  return start === -1 ? text : text.slice(start + '--- stdout ---'.length).trim()
}

function snippet(text, limit = 900) {
  const body = stdoutOf(text)
  return body.length <= limit ? body : `${body.slice(0, limit)}\n...(${body.length - limit} more chars)`
}

async function step(label, body) {
  try {
    const detail = await body()
    console.log(`PASS  ${label}`)
    if (detail) console.log(indent(detail))
  } catch (error) {
    failures.push(label)
    console.log(`FAIL  ${label}`)
    console.log(indent(error instanceof Error ? error.message : String(error)))
  }
}

function indent(text) {
  return text.split('\n').map(line => `        ${line}`).join('\n')
}

/** Run `body` with a temporarily replaced environment. */
async function withEnv(overrides, body) {
  const saved = new Map()
  for (const [key, value] of Object.entries(overrides)) {
    saved.set(key, process.env[key])
    if (value === undefined) delete process.env[key]
    else process.env[key] = value
  }
  try {
    return await body()
  } finally {
    for (const [key, value] of saved) {
      if (value === undefined) delete process.env[key]
      else process.env[key] = value
    }
  }
}

/** Run a call that must be refused, and return the message it was refused with. */
async function refusal(toolName, args, pattern) {
  let message = null
  try {
    await call(toolName, args)
  } catch (error) {
    message = error instanceof Error ? error.message : String(error)
  }
  assert(message !== null, `${toolName} was expected to refuse, but it ran`)
  assert(pattern.test(message), `${toolName} refused with an unexpected message: ${message}`)
  return message
}

console.log(`smoke: ${name} (inject: ${inject.join(', ')})`)
console.log(`smoke: BOARDWISE_EXE=${process.env['BOARDWISE_EXE'] ?? '(unset -> PATH lookup)'}`)
console.log(`smoke: fixture=${FIXTURE}`)
console.log('')

await step('boardwise_doctor — live daemon on 127.0.0.1:61190', async () => {
  const text = await call('boardwise_doctor', {})
  const exit = exitOf(text)
  assert(exit !== null, 'no exit code in the result')
  assert(/daemon/.test(text), 'the doctor report does not mention the daemon')
  assert(/PASS/.test(text), 'the doctor report has no PASS line, so nothing was actually checked')
  assert(/cli: /.test(text), 'the result does not name how the CLI was resolved')
  return `exit=${exit}\n${snippet(text)}`
})

await step('boardwise_arch — offline skeleton with counts', async () => {
  const text = await call('boardwise_arch', { file: FIXTURE })
  assert(exitOf(text) === '0', `expected exit 0, got exit ${exitOf(text)}: ${snippet(text)}`)
  assert(text.includes('架构骨架'), 'the skeleton heading is missing from stdout')
  assert(text.includes('TODO'), 'the skeleton has no TODO slot')
  assert(/轨/.test(text), 'the skeleton has no power rails section')
  return `exit=0\n${snippet(text, 600)}`
})

await step('boardwise_checkup --file — offline report files', async () => {
  const out = mkdtempSync(join(tmpdir(), 'boardwise-dsh-smoke-'))
  created.push(out)
  const text = await call('boardwise_checkup', { file: FIXTURE, out })
  assert(exitOf(text) === '0', `expected exit 0, got exit ${exitOf(text)}`)
  const report = join(out, 'report.json')
  const architecture = join(out, 'architecture.md')
  for (const path of [report, architecture]) {
    assert(existsSync(path), `${path} was not written`)
    assert(statSync(path).size > 0, `${path} is empty`)
    assert(text.includes(`${path} [present]`), `the result does not report ${path} as present`)
  }
  const parsed = JSON.parse(readFileSync(report, 'utf8'))
  assert(parsed.model?.components > 0, 'report.json carries no component count')
  assert(Array.isArray(parsed.findings), 'report.json carries no findings array')
  assert(parsed.architecture?.file === 'architecture.md', 'report.json does not point at architecture.md')
  return (
    `exit=0\nreport.json      ${statSync(report).size} bytes\narchitecture.md ${statSync(architecture).size} bytes\n` +
    `components=${parsed.model.components} findings=${parsed.findings.length}`
  )
})

await step('error path — file that is not there is refused before spawning', async () => {
  const message = await refusal('boardwise_checkup', { file: join(tmpdir(), 'boardwise-dsh-absent.epro2') }, /file not found/)
  return message
})

await step('error path — BOARDWISE_EXE pointing nowhere, no boardwise on PATH', async () => {
  const emptyPath = mkdtempSync(join(tmpdir(), 'boardwise-dsh-empty-'))
  created.push(emptyPath)
  const message = await withEnv(
    { BOARDWISE_EXE: join(tmpdir(), 'boardwise-dsh-absent', 'boardwise.exe'), PATH: emptyPath },
    () => refusal('boardwise_doctor', {}, /BOARDWISE_EXE is set to .*, which is not an existing file/),
  )
  return message
})

await step('error path — nothing on PATH names the CLI', async () => {
  const emptyPath = mkdtempSync(join(tmpdir(), 'boardwise-dsh-empty-'))
  created.push(emptyPath)
  const message = await withEnv(
    { BOARDWISE_EXE: undefined, PATH: emptyPath },
    () => refusal('boardwise_doctor', {}, /boardwise CLI not found[\s\S]*BOARDWISE_EXE/),
  )
  return message
})

for (const dir of created) rmSync(dir, { recursive: true, force: true })

console.log('')
if (failures.length > 0) {
  console.log(`smoke: ${failures.length} step(s) failed — ${failures.join('; ')}`)
  process.exitCode = 1
} else {
  console.log('smoke: all steps passed')
}
