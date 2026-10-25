import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@deepseek-ai/dsh-tools', () => ({ defineTool: (options: unknown) => options }))
vi.mock('node:child_process', () => ({ spawn: vi.fn() }))

import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { apply } from '../src/index.ts'
import { installSpawn, spawnedCommand } from './fake-child.ts'

/** One registered tool, as `defineTool` would pass it to the registry. */
interface Tool {
  name: string
  description: string
  parameters: Record<string, unknown>
  output: {
    schema: { type: string; [key: string]: unknown }
    render: (args: unknown, value: unknown) => unknown
  }
  execute: (args: Record<string, unknown>, exec: { signal: AbortSignal }) => Promise<unknown>
  timeoutMs?: number
}

const exec = { signal: new AbortController().signal }
const made: string[] = []
const saved = { BOARDWISE_EXE: process.env['BOARDWISE_EXE'], PATH: process.env['PATH'] }

/** A temp directory the test removes afterwards. */
function tempDir(prefix = 'boardwise-review-tools-'): string {
  const dir = mkdtempSync(join(tmpdir(), prefix))
  made.push(dir)
  return dir
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

function tool(name: string): Tool {
  const found = registered().get(name)
  if (found === undefined) throw new Error(`no such tool: ${name}`)
  return found
}

async function call(name: string, args: Record<string, unknown>): Promise<unknown> {
  return await tool(name).execute(args, exec)
}

async function callObject(name: string, args: Record<string, unknown>): Promise<Record<string, unknown>> {
  const value = await call(name, args)
  expect(typeof value).toBe('object')
  expect(value).not.toBeNull()
  return value as Record<string, unknown>
}

/** The value of `--flag` in a spawned command. */
function flagValue(argv: readonly string[], flag: string): string | undefined {
  const index = argv.indexOf(flag)
  return index === -1 ? undefined : argv[index + 1]
}

/** Every value of a repeated `--flag`. */
function flagValues(argv: readonly string[], flag: string): string[] {
  const values: string[] = []
  argv.forEach((token, index) => {
    if (token === flag) values.push(argv[index + 1] as string)
  })
  return values
}

function writeJson(path: string, value: unknown): void {
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, 'utf8')
}

function readJson(path: string): unknown {
  return JSON.parse(readFileSync(path, 'utf8'))
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
  for (const dir of made.splice(0)) rmSync(dir, { recursive: true, force: true })
  restoreEnv('BOARDWISE_EXE', saved.BOARDWISE_EXE)
  restoreEnv('PATH', saved.PATH)
})

describe('boardwise_review_read: structured read through --json', () => {
  const big = 'p'.repeat(50 * 1024)
  const envelope = {
    schema: 'boardwise.review-read/1',
    section: 'findings',
    report: { path: 'C:/tmp/review/report.json', schema: 'boardwise.checkup-report/1' },
    payload: {
      findings: [{ rule: 'lonely-pin', severity: 'WARN' }],
      warningsPendingTriage: 1,
      big,
    },
  }

  it('passes --out/--section/--json and returns the complete file, not stdout', async () => {
    const out = tempDir('boardwise-out-')
    let jsonPath = ''
    const mock = installSpawn((child, _command, args) => {
      jsonPath = flagValue(args, '--json') as string
      writeJson(jsonPath, envelope)
      // The whole point: stdout is over the 32 KiB cap and is not JSON at all.
      // An implementation that parses stdout — or falls back to it — cannot
      // return this envelope.
      child.out('{not json ' + 'x'.repeat(40 * 1024))
      child.finish(0)
    })

    const value = await callObject('boardwise_review_read', { out, section: 'findings' })

    expect(value).toEqual(envelope)
    expect((value['payload'] as Record<string, unknown>)['big']).toHaveLength(big.length)
    const argv = spawnedCommand(mock)
    expect(argv.slice(1)).toEqual(['review-read', '--out', out, '--section', 'findings', '--json', jsonPath])
    expect(jsonPath.startsWith(tmpdir())).toBe(true)
    expect(dirname(jsonPath).startsWith(join(tmpdir(), 'boardwise-dsh-'))).toBe(true)
    expect(jsonPath.startsWith(out)).toBe(false)

    // The render is the whole canonical object, pretty-printed — no 32 KiB cap.
    expect(tool('boardwise_review_read').output.render({}, value)).toEqual([
      { type: 'text', text: JSON.stringify(envelope, null, 2) },
    ])
  })

  it('throws a formatOutcome error on a non-zero exit even when the file is complete', async () => {
    const out = tempDir('boardwise-out-')
    installSpawn((child, _command, args) => {
      writeJson(flagValue(args, '--json') as string, envelope)
      child.out('boardwise review-read: report.json 不存在\n')
      child.err('trace: broken\n')
      child.finish(3)
    })

    await expect(call('boardwise_review_read', { out, section: 'findings' })).rejects.toThrow(
      /boardwise_review_read: exit 3[\s\S]*command: [\s\S]*trace: broken/,
    )
  })

  it('refuses the stdout fallback when exit 0 wrote no JSON file', async () => {
    const out = tempDir('boardwise-out-')
    installSpawn(child => {
      // A complete, parseable envelope on stdout: an implementation that falls
      // back to stdout would happily return it. It must not.
      child.out(JSON.stringify(envelope))
      child.finish(0)
    })

    await expect(call('boardwise_review_read', { out, section: 'findings' })).rejects.toThrow(
      /did not write|no JSON file|missing/i,
    )
  })

  it('throws on a JSON file that is not parseable', async () => {
    const out = tempDir('boardwise-out-')
    installSpawn((child, _command, args) => {
      writeFileSync(flagValue(args, '--json') as string, '{oops', 'utf8')
      child.finish(0)
    })
    await expect(call('boardwise_review_read', { out, section: 'findings' })).rejects.toThrow(/JSON/i)
  })

  it('throws when the JSON root is not an object', async () => {
    const out = tempDir('boardwise-out-')
    installSpawn((child, _command, args) => {
      writeJson(flagValue(args, '--json') as string, [envelope])
      child.finish(0)
    })
    await expect(call('boardwise_review_read', { out, section: 'findings' })).rejects.toThrow(/object/i)
  })

  it('throws when the envelope schema is not review-read/1', async () => {
    const out = tempDir('boardwise-out-')
    installSpawn((child, _command, args) => {
      writeJson(flagValue(args, '--json') as string, { ...envelope, schema: 'boardwise.review-read/0' })
      child.finish(0)
    })
    await expect(call('boardwise_review_read', { out, section: 'findings' })).rejects.toThrow(/schema/i)
  })

  it('throws when the section is not the one asked for', async () => {
    const out = tempDir('boardwise-out-')
    installSpawn((child, _command, args) => {
      writeJson(flagValue(args, '--json') as string, { ...envelope, section: 'verdict' })
      child.finish(0)
    })
    await expect(call('boardwise_review_read', { out, section: 'findings' })).rejects.toThrow(/section/i)
  })

  it('throws when report or payload is absent', async () => {
    const out = tempDir('boardwise-out-')
    for (const missing of ['report', 'payload'] as const) {
      installSpawn((child, _command, args) => {
        const body = { ...envelope } as Record<string, unknown>
        delete body[missing]
        writeJson(flagValue(args, '--json') as string, body)
        child.finish(0)
      })
      await expect(call('boardwise_review_read', { out, section: 'findings' })).rejects.toThrow(
        new RegExp(missing),
      )
    }
  })

  it('treats a cancelled run as an error even when the file already exists', async () => {
    const out = tempDir('boardwise-out-')
    installSpawn((child, _command, args) => {
      writeJson(flagValue(args, '--json') as string, envelope)
      // Never closes; cancellation ends it.
    })
    const controller = new AbortController()
    const pending = tool('boardwise_review_read').execute({ out, section: 'findings' }, { signal: controller.signal })
    await new Promise(resolve => setTimeout(resolve, 25))
    controller.abort()
    await expect(pending).rejects.toThrow(/was cancelled/)
  })
})

describe('boardwise_review_evidence: live capture stays a text result', () => {
  it('repeats --page/--pcb, routes the window and reports exit 1 with artifacts', async () => {
    const out = tempDir('boardwise-evidence-')
    const mock = installSpawn((child, _command, args) => {
      const dir = flagValue(args, '--out') as string
      writeFileSync(join(dir, 'report.json'), '{}')
      writeFileSync(join(dir, 'live-evidence.json'), '{}')
      child.out('channels: liveSchematic ok, livePcb failed\n')
      child.finish(1)
    })

    const text = (await call('boardwise_review_evidence', {
      out,
      project: 'test',
      page: ['page-1', 'page-2'],
      pcb: ['pcb-1', 'pcb-2'],
    })) as string

    const argv = spawnedCommand(mock)
    expect(argv.slice(1)).toEqual([
      'review-evidence',
      '--out',
      out,
      '--project',
      'test',
      '--page',
      'page-1',
      '--page',
      'page-2',
      '--pcb',
      'pcb-1',
      '--pcb',
      'pcb-2',
    ])
    expect(flagValues(argv, '--page')).toEqual(['page-1', 'page-2'])
    expect(flagValues(argv, '--pcb')).toEqual(['pcb-1', 'pcb-2'])
    // Exit 1 is this collection's answer, not a throw: the text comes back.
    expect(text).toContain('boardwise_review_evidence: exit 1')
    expect(text).toContain(`report.json: ${join(out, 'report.json')} [present]`)
    expect(text).toContain(`live-evidence.json: ${join(out, 'live-evidence.json')} [present]`)
    expect(text).toContain(`report.md: ${join(out, 'report.md')} [MISSING]`)
    expect(text).toContain('board-report.md:')
    expect(text).toContain('livePcb failed')
  })

  it('spells the window choice as --instance and keeps exit 3 textual', async () => {
    const out = tempDir('boardwise-evidence-')
    const mock = installSpawn(child => {
      child.err('boardwise review-evidence: 连不上 daemon\n')
      child.finish(3)
    })

    const text = (await call('boardwise_review_evidence', { out, instance: 'inst-015813234-aw2317s0' })) as string

    expect(spawnedCommand(mock).slice(1)).toEqual([
      'review-evidence',
      '--out',
      out,
      '--instance',
      'inst-015813234-aw2317s0',
    ])
    expect(text).toContain('boardwise_review_evidence: exit 3')
    expect(text).toContain('连不上 daemon')
    expect(text).toContain('[MISSING]')
  })

  it('gives the live collection the ten-minute budget', () => {
    expect(tool('boardwise_review_evidence').timeoutMs).toBe(600_000)
  })

  it('requires out', async () => {
    const mock = installSpawn(child => child.finish(0))
    await expect(call('boardwise_review_evidence', {})).rejects.toThrow(/out is required/)
    expect(mock).not.toHaveBeenCalled()
  })
})

describe('boardwise_triage_batch: one atomic batch, judged by Python', () => {
  const entries = [
    { key: 'w1', verdict: 'needs-manual', reason: '  需要人工复核 μF  ' },
    { key: 'w2', verdict: '无害', reason: '测试点，未接任何负载\n第二行保持原样' },
  ]
  const result = {
    schema: 'boardwise.triage-batch-result/1',
    applied: [
      { key: 'w1', verdict: 'needs-manual', reason: entries[0]!.reason, matched: 1, added: 1, updated: 0 },
      { key: 'w2', verdict: '无害', reason: entries[1]!.reason, matched: 1, added: 1, updated: 0 },
    ],
    added: 2,
    updated: 0,
    duplicateReportKeys: [],
    warning_triage: [{ key: 'w1', verdict: 'needs-manual' }],
    completion: { verdict: 'complete-with-open-items', warningsPendingTriage: 1, warningsNeedsManual: 1 },
    conclusionSection: { verdict: 'pass-with-notes' },
    conclusion: '通过，但有一条待人工复核',
    report: 'C:/tmp/review/report.json',
    sidecar: 'C:/tmp/review/warning-triage.json',
    reportMd: 'C:/tmp/review/report.md',
    boardReport: 'C:/tmp/review/board-report.md',
  }

  it('writes the versioned input verbatim and returns the full --json result', async () => {
    const out = tempDir('boardwise-triage-')
    let inputPath = ''
    let resultPath = ''
    let inputText = ''
    const mock = installSpawn((child, _command, args) => {
      inputPath = flagValue(args, '--input') as string
      resultPath = flagValue(args, '--json') as string
      inputText = readFileSync(inputPath, 'utf8')
      writeJson(resultPath, result)
      // Deliberately a *different*, truncated-looking answer on stdout. The
      // result must come from the file, never from this.
      child.out(`${JSON.stringify({ schema: 'boardwise.triage-batch-result/1', applied: [] })}` + 'y'.repeat(40 * 1024))
      child.finish(0)
    })

    const value = await callObject('boardwise_triage_batch', { out, entries })

    expect(value).toEqual(result)
    expect('ok' in value).toBe(false)
    // needs-manual and the pending count are Python's, not rewritten here.
    expect((value['applied'] as Array<Record<string, unknown>>)[0]!['verdict']).toBe('needs-manual')
    expect((value['completion'] as Record<string, unknown>)['warningsPendingTriage']).toBe(1)
    expect(inputPath.startsWith(tmpdir())).toBe(true)
    expect(resultPath.startsWith(tmpdir())).toBe(true)
    expect(inputPath).not.toBe(resultPath)
    const argv = spawnedCommand(mock)
    expect(argv.slice(1)).toEqual(['triage-batch', '--out', out, '--input', inputPath, '--json', resultPath])
    expect(JSON.parse(inputText)).toEqual({ schema: 'boardwise.triage-batch/1', entries })
    // UTF-8, reason untouched — Python is the one that trims and validates.
    expect(inputText).toContain('  需要人工复核 μF  ')
    expect(inputText).toContain('测试点，未接任何负载\\n第二行保持原样')

    expect(tool('boardwise_triage_batch').output.render({}, value)).toEqual([
      { type: 'text', text: JSON.stringify(result, null, 2) },
    ])
  })

  it('lets an empty batch reach the CLI instead of refusing it in TS', async () => {
    const out = tempDir('boardwise-triage-')
    const mock = installSpawn((child, _command, args) => {
      const batch = readJson(flagValue(args, '--input') as string) as Record<string, unknown>
      expect(batch).toEqual({ schema: 'boardwise.triage-batch/1', entries: [] })
      child.err('boardwise triage-batch: entries 必须非空\n')
      child.finish(2)
    })

    // No local "entries must not be empty" error: the CLI's exit 2 is the answer.
    await expect(call('boardwise_triage_batch', { out, entries: [] })).rejects.toThrow(/exit 2/)
    expect(mock).toHaveBeenCalledTimes(1)
  })

  it('throws a formatOutcome error on a non-zero exit even when the file is complete', async () => {
    const out = tempDir('boardwise-triage-')
    installSpawn((child, _command, args) => {
      writeJson(flagValue(args, '--json') as string, result)
      child.err('boardwise triage-batch: 第 1 行：报告里没有 key = w1 的槽位\n')
      child.finish(2)
    })
    await expect(call('boardwise_triage_batch', { out, entries })).rejects.toThrow(
      /boardwise_triage_batch: exit 2[\s\S]*没有 key/,
    )
  })

  it('refuses the stdout fallback when exit 0 wrote no result file', async () => {
    const out = tempDir('boardwise-triage-')
    installSpawn(child => {
      child.out(JSON.stringify(result))
      child.finish(0)
    })
    await expect(call('boardwise_triage_batch', { out, entries })).rejects.toThrow(
      /did not write|no JSON file|missing/i,
    )
  })

  it('throws on a result schema that is not triage-batch-result/1', async () => {
    const out = tempDir('boardwise-triage-')
    installSpawn((child, _command, args) => {
      writeJson(flagValue(args, '--json') as string, { ...result, schema: 'boardwise.triage-batch-result/0' })
      child.finish(0)
    })
    await expect(call('boardwise_triage_batch', { out, entries })).rejects.toThrow(/schema/i)
  })

  it('throws when applied is absent or not an array', async () => {
    const out = tempDir('boardwise-triage-')
    for (const bad of [{ ...result, applied: undefined }, { ...result, applied: {} }]) {
      installSpawn((child, _command, args) => {
        writeJson(flagValue(args, '--json') as string, bad)
        child.finish(0)
      })
      await expect(call('boardwise_triage_batch', { out, entries })).rejects.toThrow(/applied/i)
    }
  })
})
