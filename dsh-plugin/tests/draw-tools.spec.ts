import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@deepseek-ai/dsh-tools', () => ({ defineTool: (options: unknown) => options }))
vi.mock('node:child_process', () => ({ spawn: vi.fn() }))

import { existsSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apply } from '../src/index.ts'
import { installSpawn, spawnedCommand } from './fake-child.ts'

interface Tool {
  name: string
  execute: (args: Record<string, unknown>, exec: { signal: AbortSignal }) => Promise<unknown>
}

const exec = { signal: new AbortController().signal }
const saved = { BOARDWISE_EXE: process.env['BOARDWISE_EXE'], PATH: process.env['PATH'] }

function tempDir(prefix = 'boardwise-draw-tools-'): string {
  return mkdtempSync(join(tmpdir(), prefix))
}

function fixture(name: string, content = '{}\n'): string {
  const file = join(tempDir('boardwise-draw-fixture-'), name)
  writeFileSync(file, content, 'utf8')
  return file
}

function registered(): Map<string, Tool> {
  const tools = new Map<string, Tool>()
  apply({ tools: { register: (definition: unknown) => {
    const tool = definition as Tool
    tools.set(tool.name, tool)
    return () => {}
  } } } as never)
  return tools
}

async function callObject(name: string, args: Record<string, unknown>): Promise<Record<string, unknown>> {
  const tool = registered().get(name)
  if (tool === undefined) throw new Error(`no such tool: ${name}`)
  const value = await tool.execute(args, exec)
  expect(typeof value).toBe('object')
  expect(value).not.toBeNull()
  return value as Record<string, unknown>
}

function flagValue(argv: readonly string[], flag: string): string | undefined {
  const index = argv.indexOf(flag)
  return index === -1 ? undefined : argv[index + 1]
}

function writeJson(path: string, value: unknown): void {
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, 'utf8')
}

function restoreEnv(key: string, value: string | undefined): void {
  if (value === undefined) delete process.env[key]
  else process.env[key] = value
}

beforeEach(() => {
  const exe = join(tempDir('boardwise-bin-'), 'boardwise.exe')
  writeFileSync(exe, '')
  process.env['BOARDWISE_EXE'] = exe
})

afterEach(() => {
  restoreEnv('BOARDWISE_EXE', saved.BOARDWISE_EXE)
  restoreEnv('PATH', saved.PATH)
})

function compileInputs(): { circuit: string; presentation: string; profiles: string } {
  return {
    circuit: fixture('circuit.json'),
    presentation: fixture('presentation.json'),
    profiles: fixture('profiles.json'),
  }
}

function compilePayload(ok: boolean): Record<string, unknown> {
  return {
    command: 'compile',
    ok,
    candidates: ok ? [{ index: 0, key: 'candidate-0', metrics: { errors: 0 } }] : [],
    failures: ok ? [] : [{ category: 'circuit-invalid', detail: 'bad pin', action: 'fix it' }],
    failureRounds: [],
    rejected: [],
    notes: ['x'.repeat(40 * 1024)],
    previews: ok ? ['cand1.svg', 'cand1.layout.json'] : [],
  }
}

/** The page-compiler shape `draw compile --json` writes: `pages`, no `candidates`. */
function pageCompilePayload(ok: boolean): Record<string, unknown> {
  return {
    command: 'compile',
    document: 'page',
    ok,
    pages: ok
      ? [{
        index: 0,
        key: 'page-0',
        modules: [{ id: 'pwr' }, { id: 'sense' }],
        verdict: { ok: true },
      }]
      : [],
    failures: ok
      ? []
      : [{ category: 'module-refused', subject: 'pwr', detail: 'no legal drawing', action: 'widen the sheet' }],
    categories: ok ? {} : { 'module-refused': 1 },
    rejected: [],
    moduleFailureRounds: {},
    moduleLabelFallbacks: {},
    modules: { pwr: { ok }, sense: { ok } },
    notes: ['boardwise-pagecompiler/1: lattice 5 units'],
    previews: ok ? ['cand1.svg', 'cand1.page.json'] : [],
  }
}

describe('boardwise_draw_compile: offline structured transport', () => {
  it('passes every argument and returns the complete JSON file, never stdout', async () => {
    const inputs = compileInputs()
    const intent = fixture('intent.json')
    const out = join(tempDir(), 'nested', 'compiled')
    const payload = compilePayload(true)
    let jsonPath = ''
    const mock = installSpawn((child, _command, args) => {
      jsonPath = flagValue(args, '--json') as string
      writeJson(jsonPath, payload)
      child.out('{not json ' + 'y'.repeat(40 * 1024))
      child.finish(0)
    })

    const value = await callObject('boardwise_draw_compile', {
      ...inputs,
      intent,
      out,
      pageBox: '0,0,1000,800',
    })

    expect(value).toEqual(payload)
    expect(existsSync(out)).toBe(true)
    expect(jsonPath.startsWith(tmpdir())).toBe(true)
    expect(jsonPath.startsWith(out)).toBe(false)
    expect(spawnedCommand(mock).slice(1)).toEqual([
      'draw', 'compile',
      '--circuit', inputs.circuit,
      '--presentation', inputs.presentation,
      '--profiles', inputs.profiles,
      '--out', out,
      '--json', jsonPath,
      '--page-box', '0,0,1000,800',
      '--intent', intent,
    ])
  })

  it('returns the compiler refusal JSON on its documented exit 5', async () => {
    const payload = compilePayload(false)
    const mock = installSpawn((child, _command, args) => {
      writeJson(flagValue(args, '--json') as string, payload)
      child.finish(5)
    })

    const value = await callObject('boardwise_draw_compile', compileInputs())

    expect(value).toEqual(payload)
    expect(value['ok']).toBe(false)
    expect(flagValue(spawnedCommand(mock), '--out')).toBeDefined()
  })

  it('does not mistake an unexpected exit for a readable compiler result', async () => {
    installSpawn((child, _command, args) => {
      writeJson(flagValue(args, '--json') as string, compilePayload(false))
      child.finish(2)
    })
    await expect(callObject('boardwise_draw_compile', compileInputs())).rejects.toThrow(/exit 2/)
  })

  it('refuses a missing spec before spawning anything', async () => {
    const inputs = compileInputs()
    const mock = installSpawn(child => child.finish(0))
    await expect(callObject('boardwise_draw_compile', {
      ...inputs,
      circuit: join(tempDir(), 'missing.json'),
    })).rejects.toThrow(/circuit not found/)
    expect(mock).not.toHaveBeenCalled()
  })

  it('returns a page compile whole, routed by document:"page" instead of candidates', async () => {
    const inputs = compileInputs()
    const payload = pageCompilePayload(true)
    const mock = installSpawn((child, _command, args) => {
      writeJson(flagValue(args, '--json') as string, payload)
      child.finish(0)
    })

    const value = await callObject('boardwise_draw_compile', {
      ...inputs,
      pageBox: '0,0,1169,826',
    })

    // The complete object comes back, `pages` and all; nothing is recomputed.
    expect(value).toEqual(payload)
    expect(value['pages']).toHaveLength(1)
    expect(value['candidates']).toBeUndefined()
    expect(flagValue(spawnedCommand(mock), '--page-box')).toBe('0,0,1169,826')
  })

  it('returns the page refusal JSON on exit 5 as well', async () => {
    const payload = pageCompilePayload(false)
    installSpawn((child, _command, args) => {
      writeJson(flagValue(args, '--json') as string, payload)
      child.finish(5)
    })

    const value = await callObject('boardwise_draw_compile', compileInputs())

    expect(value).toEqual(payload)
    expect(value['ok']).toBe(false)
    expect(value['pages']).toEqual([])
    expect(value['failures']).toHaveLength(1)
  })

  it('refuses a page envelope with no pages array, even on exit 0', async () => {
    const payload = pageCompilePayload(true)
    delete payload['pages']
    installSpawn((child, _command, args) => {
      writeJson(flagValue(args, '--json') as string, payload)
      child.finish(0)
    })
    await expect(callObject('boardwise_draw_compile', compileInputs()))
      .rejects.toThrow(/no .*pages.* array/)
  })

  it('still refuses a single-module envelope with no candidates array', async () => {
    const payload = compilePayload(true)
    delete payload['candidates']
    installSpawn((child, _command, args) => {
      writeJson(flagValue(args, '--json') as string, payload)
      child.finish(0)
    })
    await expect(callObject('boardwise_draw_compile', compileInputs()))
      .rejects.toThrow(/no .*candidates.* array/)
  })

  it('names the accepted exit, not exit 0, when a documented refusal writes no JSON', async () => {
    // `draw compile` exits 5 without a file when an input cannot be read, and
    // that exit is accepted by this tool; the missing-file report must say 5.
    installSpawn(child => child.finish(5))
    let message = ''
    try {
      await callObject('boardwise_draw_compile', compileInputs())
    } catch (error) {
      message = (error as Error).message
    }
    expect(message).toMatch(/exit 5 but the CLI did not write the JSON file/)
    expect(message).not.toMatch(/exit 0/)
  })
})

function lintPayload(exitCode: number): Record<string, unknown> {
  return {
    page: 'captured.json',
    source: 'replay',
    findings: exitCode === 0 ? [] : [{ predicate: 'L1', severity: 'ERROR', message: 'overlap' }],
    counts: { ERROR: exitCode, WARN: 0, INFO: 0 },
    exitCode,
    textReadable: true,
    notes: [],
    thresholds: { L1_TEXT_WIRE_PENETRATION: 0.1 },
  }
}

describe('boardwise_draw_lint: offline replay only', () => {
  it('returns the full lint JSON on exit 1 and exposes no live-page argv', async () => {
    const snapshot = fixture('snapshot.json')
    const render = fixture('render.svg', '<svg/>\n')
    const bodies = fixture('bodies.json')
    const payload = lintPayload(1)
    let jsonPath = ''
    const mock = installSpawn((child, _command, args) => {
      jsonPath = flagValue(args, '--json') as string
      writeJson(jsonPath, payload)
      child.out('not the answer')
      child.finish(1)
    })

    const value = await callObject('boardwise_draw_lint', { snapshot, render, bodies })

    expect(value).toEqual(payload)
    const argv = spawnedCommand(mock)
    expect(argv.slice(1)).toEqual([
      'draw', 'lint', '--snapshot', snapshot, '--render', render,
      '--bodies', bodies, '--json', jsonPath,
    ])
    for (const liveFlag of ['--page', '--project', '--instance', '--port']) {
      expect(argv).not.toContain(liveFlag)
    }
  })

  it('returns a clean replay result on exit 0', async () => {
    const payload = lintPayload(0)
    installSpawn((child, _command, args) => {
      writeJson(flagValue(args, '--json') as string, payload)
      child.finish(0)
    })
    const value = await callObject('boardwise_draw_lint', {
      snapshot: fixture('snapshot.json'), render: fixture('render.svg', '<svg/>\n'),
    })
    expect(value).toEqual(payload)
  })

  it('keeps exit 2 as an error even when a JSON file exists', async () => {
    installSpawn((child, _command, args) => {
      writeJson(flagValue(args, '--json') as string, lintPayload(0))
      child.finish(2)
    })
    await expect(callObject('boardwise_draw_lint', {
      snapshot: fixture('snapshot.json'), render: fixture('render.svg', '<svg/>\n'),
    })).rejects.toThrow(/exit 2/)
  })

  it('refuses a live-source envelope instead of presenting it as offline replay', async () => {
    installSpawn((child, _command, args) => {
      writeJson(flagValue(args, '--json') as string, { ...lintPayload(0), source: 'live' })
      child.finish(0)
    })
    await expect(callObject('boardwise_draw_lint', {
      snapshot: fixture('snapshot.json'), render: fixture('render.svg', '<svg/>\n'),
    })).rejects.toThrow(/source/)
  })
})
