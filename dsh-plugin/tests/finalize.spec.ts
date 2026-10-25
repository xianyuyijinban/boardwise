/**
 * 537D3a: the real `boardwise_review_finalize` tool, against a **real**
 * `dsh-session` Session and a **real** `SessionProjectionRegistry`.
 *
 * These tests never assert "some fake append was called": they read the event
 * back with `pluginRecordOf`, read the projection with `stateOf`, and check that
 * the record is ignorable and carries the complete post-change state. A fake
 * registry would let the production wiring rot.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@deepseek-ai/dsh-tools', () => ({ defineTool: (options: unknown) => options }))
vi.mock('node:child_process', () => ({ spawn: vi.fn() }))

import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { Context } from '@deepseek-ai/cordis'
import { Session, appendPluginRecord, pluginRecordOf } from '@deepseek-ai/dsh-session'
import { SessionProjectionRegistry } from '@deepseek-ai/dsh-session-projection'
import { apply } from '../src/index.ts'
import {
  REVIEW_FINALIZED_KEY,
  REVIEW_FINALIZED_RECORD,
  REVIEW_FINALIZE_TIMEOUT_MS,
  REVIEW_FINALIZE_TOOL,
  directoryKeyOf,
} from '../src/review-finalize.ts'
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
  execute: (
    args: Record<string, unknown>,
    exec: Record<string, unknown>,
  ) => Promise<Record<string, unknown>>
  timeoutMs?: number
}

/** The whole projection value, as the tool and the gate read it. */
interface ProjectionState {
  receipts: Record<string, {
    reviewDir: string
    receipt: Record<string, unknown>
    callId: string | null
  }>
}

const made: string[] = []
const saved = { BOARDWISE_EXE: process.env['BOARDWISE_EXE'], PATH: process.env['PATH'] }

function tempDir(prefix = 'boardwise-finalize-'): string {
  const dir = mkdtempSync(join(tmpdir(), prefix))
  made.push(dir)
  return dir
}

function writeJson(path: string, value: unknown): void {
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, 'utf8')
}

/** The value of `--flag` in a spawned command. */
function flagValue(argv: readonly string[], flag: string): string | undefined {
  const index = argv.indexOf(flag)
  return index === -1 ? undefined : argv[index + 1]
}

function newSession(id: string): InstanceType<typeof Session> {
  return Session.create(id as never)
}

/**
 * A real registry on a real cordis Context, plus the tools `apply` registers.
 * `projection: false` reproduces a mount that lacks the service.
 */
function harness(options: { projection?: boolean } = {}): {
  projections: InstanceType<typeof SessionProjectionRegistry>
  tools: Map<string, Tool>
} {
  const ctx = new Context()
  const projections = new SessionProjectionRegistry(ctx)
  const tools = new Map<string, Tool>()
  const pluginCtx: Record<string, unknown> = {
    tools: {
      register: (definition: unknown) => {
        const tool = definition as Tool
        tools.set(tool.name, tool)
        return () => {}
      },
    },
  }
  if (options.projection !== false) pluginCtx['sessionProjections'] = projections
  apply(pluginCtx as never)
  return { projections, tools }
}

function toolOf(tools: Map<string, Tool>): Tool {
  const found = tools.get(REVIEW_FINALIZE_TOOL)
  if (found === undefined) throw new Error(`no such tool: ${REVIEW_FINALIZE_TOOL}`)
  return found
}

/** The execution identity a real tool call carries. */
function execFor(
  session: unknown,
  controller = new AbortController(),
  callId = 'call-finalize-1',
): Record<string, unknown> {
  return { signal: controller.signal, agent: { session }, callId }
}

function stateOf(
  projections: InstanceType<typeof SessionProjectionRegistry>,
  session: unknown,
): ProjectionState {
  return projections.stateOf(session as never, REVIEW_FINALIZED_KEY) as ProjectionState
}

/** A complete, structurally valid CLI receipt; `overrides` may replace any field. */
function receipt(
  overrides: Record<string, unknown> = {},
  files?: readonly unknown[],
): Record<string, unknown> {
  return {
    schema: 'boardwise.review-finalize/1',
    ok: true,
    scope: 'delivery-content',
    boardConclusionAuthority: 'report.conclusion',
    files: files ?? [
      { path: 'report.json', bytes: 12, sha256: 'a'.repeat(64) },
      { path: 'sections/plan.md', bytes: 0, sha256: 'b'.repeat(64) },
    ],
    ...overrides,
  }
}

/**
 * Serve one receipt from the fake CLI: write `<out>/finalize.json`, print
 * `stdout`, then exit with `code` (`write: false` reproduces a missing file).
 */
function serveReceipt(
  value: unknown,
  options: { code?: number; stdout?: string; write?: boolean } = {},
): ReturnType<typeof installSpawn> {
  return installSpawn((child, _command, args) => {
    if (options.write !== false) {
      writeJson(join(flagValue(args, '--out') as string, 'finalize.json'), value)
    }
    child.out(options.stdout ?? '')
    child.finish(options.code ?? 0)
  })
}

beforeEach(() => {
  const exe = join(tempDir('boardwise-bin-'), 'boardwise.exe')
  writeFileSync(exe, '')
  process.env['BOARDWISE_EXE'] = exe
})

afterEach(() => {
  for (const dir of made.splice(0)) rmSync(dir, { recursive: true, force: true })
  if (saved.BOARDWISE_EXE === undefined) delete process.env['BOARDWISE_EXE']
  else process.env['BOARDWISE_EXE'] = saved.BOARDWISE_EXE
  if (saved.PATH === undefined) delete process.env['PATH']
  else process.env['PATH'] = saved.PATH
  vi.useRealTimers()
})

describe('boardwise_review_finalize: the receipt comes from the file and lands in the Session', () => {
  it('reads a >32 KiB receipt whole while stdout is over the cap and not JSON, then records the complete state', async () => {
    const big = 'w'.repeat(64 * 1024)
    const value = receipt({ big, review: { conclusion: 'pass-with-notes' } })
    const { projections, tools } = harness()
    const session = newSession('session-finalize-big')
    const out = tempDir()
    const mock = serveReceipt(value, { stdout: `{not json ${'x'.repeat(48 * 1024)}` })

    const result = await toolOf(tools).execute({ out }, execFor(session))

    // The answer is the complete file, not the truncated/non-JSON stdout.
    expect(result['receipt']).toEqual(value)
    expect((result['receipt'] as Record<string, unknown>)['big']).toHaveLength(big.length)
    expect(result['reviewDir']).toBe(resolve(out))
    expect(result['out']).toBe(out)
    expect(spawnedCommand(mock).slice(1)).toEqual(['review', 'finalize', '--out', out])

    // The Session carries an ignorable plugin record with the whole state.
    const seq = (result['sessionRecord'] as { seq: number }).seq
    const log = (session as unknown as { log: readonly unknown[] }).log
    const event = log[seq] as { ignorable?: true; type: string } | undefined
    expect(event).toBeDefined()
    expect(event?.ignorable).toBe(true)
    const record = pluginRecordOf(event as never)
    expect(record?.type).toBe(REVIEW_FINALIZED_RECORD)
    expect(record?.seq).toBe(seq)

    const key = directoryKeyOf(resolve(out))
    expect(result['directoryKey']).toBe(key)
    const expectedEntry = {
      reviewDir: resolve(out),
      receipt: JSON.parse(readFileSync(join(out, 'finalize.json'), 'utf8')),
      callId: 'call-finalize-1',
    }
    expect(record?.data).toEqual({ receipts: { [key]: expectedEntry } })
    // …and the real projection serves the same value.
    expect(stateOf(projections, session)).toEqual({ receipts: { [key]: expectedEntry } })
    expect(toolOf(tools).output.render({}, result)).toEqual([
      { type: 'text', text: JSON.stringify(result, null, 2) },
    ])
  })

  it('records nothing on a non-zero exit even when a complete receipt already exists', async () => {
    const { projections, tools } = harness()
    const session = newSession('session-finalize-nonzero')
    const out = tempDir()
    serveReceipt(receipt(), { code: 2, stdout: 'boardwise review finalize: 内容不一致\n' })

    await expect(toolOf(tools).execute({ out }, execFor(session))).rejects.toThrow(/exit 2/)
    expect(session.seq).toBe(0)
    expect(stateOf(projections, session).receipts).toEqual({})
  })

  it('records nothing when exit 0 wrote no receipt, and never falls back to stdout', async () => {
    const { projections, tools } = harness()
    const session = newSession('session-finalize-missing')
    const out = tempDir()
    // A complete receipt on stdout: an implementation that parsed stdout would
    // happily accept it. It must not.
    serveReceipt(receipt(), { write: false, stdout: JSON.stringify(receipt()) })

    await expect(toolOf(tools).execute({ out }, execFor(session))).rejects.toThrow(
      /did not write|no JSON file|missing/i,
    )
    expect(session.seq).toBe(0)
    expect(stateOf(projections, session).receipts).toEqual({})
  })

  it('records nothing when the receipt file is not JSON or not an object', async () => {
    const { projections, tools } = harness()
    const session = newSession('session-finalize-broken')
    const out = tempDir()

    installSpawn((child, _command, args) => {
      writeFileSync(join(flagValue(args, '--out') as string, 'finalize.json'), '{oops', 'utf8')
      child.finish(0)
    })
    await expect(toolOf(tools).execute({ out }, execFor(session))).rejects.toThrow(/JSON/i)

    serveReceipt([receipt()])
    await expect(toolOf(tools).execute({ out }, execFor(session))).rejects.toThrow(/object/i)

    expect(session.seq).toBe(0)
    expect(stateOf(projections, session).receipts).toEqual({})
  })

  it('rejects every transport violation and records nothing', async () => {
    const row = (overrides: Record<string, unknown>): Record<string, unknown> => ({
      path: 'report.json',
      bytes: 1,
      sha256: 'a'.repeat(64),
      ...overrides,
    })
    const cases: readonly [string, unknown][] = [
      ['wrong schema', receipt({ schema: 'boardwise.review-finalize/0' })],
      ['ok not true', receipt({ ok: false })],
      ['ok missing', receipt({ ok: undefined })],
      ['wrong scope', receipt({ scope: 'board' })],
      ['wrong authority', receipt({ boardConclusionAuthority: 'review-summary.md' })],
      ['files missing', receipt({ files: undefined })],
      ['files not an array', receipt({ files: {} })],
      ['absolute path', receipt({}, [row({ path: 'C:/tmp/report.json' })])],
      ['drive-relative path', receipt({}, [row({ path: 'C:report.json' })])],
      ['parent escape', receipt({}, [row({ path: '../report.json' })])],
      ['nested escape', receipt({}, [row({ path: 'sections/../../report.json' })])],
      ['empty segment', receipt({}, [row({ path: 'a//b.md' })])],
      ['backslash path', receipt({}, [row({ path: 'sections\\plan.md' })])],
      ['empty path', receipt({}, [row({ path: '' })])],
      ['path not a string', receipt({}, [row({ path: 7 })])],
      ['negative bytes', receipt({}, [row({ bytes: -1 })])],
      ['fractional bytes', receipt({}, [row({ bytes: 1.5 })])],
      ['bytes not a number', receipt({}, [row({ bytes: '1' })])],
      ['uppercase sha', receipt({}, [row({ sha256: 'A'.repeat(64) })])],
      ['short sha', receipt({}, [row({ sha256: 'a'.repeat(63) })])],
      ['non-hex sha', receipt({}, [row({ sha256: 'g'.repeat(64) })])],
      ['file row not an object', receipt({}, ['report.json'])],
    ]

    for (const [label, value] of cases) {
      const { projections, tools } = harness()
      const session = newSession(`session-finalize-bad-${label.replaceAll(/\W+/g, '-')}`)
      const out = tempDir()
      serveReceipt(value)
      await expect(
        toolOf(tools).execute({ out }, execFor(session)),
        `case: ${label}`,
      ).rejects.toThrow(/receipt|files|schema|ok|scope|authority/i)
      expect(session.seq, `case: ${label}`).toBe(0)
      expect(stateOf(projections, session).receipts, `case: ${label}`).toEqual({})
    }
  })

  it('does not read a hand-written receipt: no tool call, no record', () => {
    const { projections } = harness()
    const session = newSession('session-finalize-handwritten')
    const out = tempDir()
    writeJson(join(out, 'finalize.json'), receipt())

    // The file is there and valid; the Session knows nothing about it, which is
    // exactly why the delivery gate reads the projection and not the file.
    expect(session.seq).toBe(0)
    expect(stateOf(projections, session).receipts).toEqual({})
  })

  it('keeps different directories and replaces the receipt of the same directory', async () => {
    const { projections, tools } = harness()
    const session = newSession('session-finalize-dirs')
    const outA = tempDir()
    const outB = tempDir()
    const receiptA = receipt({ which: 'A' })
    const receiptB = receipt({ which: 'B' })
    const receiptA2 = receipt({ which: 'A2' })

    installSpawn((child, _command, args) => {
      const out = flagValue(args, '--out') as string
      writeJson(join(out, 'finalize.json'), out === outA ? receiptA : receiptB)
      child.finish(0)
    })
    await toolOf(tools).execute({ out: outA }, execFor(session))
    await toolOf(tools).execute({ out: outB }, execFor(session))

    const keyA = directoryKeyOf(resolve(outA))
    const keyB = directoryKeyOf(resolve(outB))
    let state = stateOf(projections, session)
    expect(Object.keys(state.receipts).sort()).toEqual([keyA, keyB].sort())
    expect(state.receipts[keyA]?.receipt).toEqual(receiptA)
    expect(state.receipts[keyB]?.receipt).toEqual(receiptB)

    // The second record carried the complete state, so replaying only it still
    // names both directories (a delta would have dropped A here).
    const secondSeq = 1
    const second = pluginRecordOf(
      (session as unknown as { log: readonly unknown[] }).log[secondSeq] as never,
    )
    expect(Object.keys((second?.data as ProjectionState).receipts).sort()).toEqual([keyA, keyB].sort())

    serveReceipt(receiptA2)
    await toolOf(tools).execute({ out: outA }, execFor(session))
    state = stateOf(projections, session)
    expect(Object.keys(state.receipts).sort()).toEqual([keyA, keyB].sort())
    expect(state.receipts[keyA]?.receipt).toEqual(receiptA2)
    expect(state.receipts[keyB]?.receipt).toEqual(receiptB)
    // A replacement is a new whole-value record, not a rewrite of history.
    expect(session.seq).toBe(3)
  })

  it('keeps the records of one Session invisible to another Session', async () => {
    const { projections, tools } = harness()
    const sessionA = newSession('session-finalize-a')
    const sessionB = newSession('session-finalize-b')
    const out = tempDir()
    serveReceipt(receipt())

    await toolOf(tools).execute({ out }, execFor(sessionA))

    expect(Object.keys(stateOf(projections, sessionA).receipts)).toHaveLength(1)
    expect(stateOf(projections, sessionB).receipts).toEqual({})
    expect(sessionB.seq).toBe(0)
  })

  it('returns the same projection state for unrelated events and fails closed on a corrupt record', () => {
    const { projections } = harness()
    const session = newSession('session-finalize-events')
    const before = stateOf(projections, session)

    // Someone else's plugin record: not ours, same state reference.
    appendPluginRecord(session, 'plugin:other-plugin/notes' as never, { note: 'hi' } as never)
    expect(stateOf(projections, session)).toBe(before)

    // Our type, but not a state this projection can read: keep the old value and
    // do not throw. A corrupt record must never grant delivery qualification.
    appendPluginRecord(
      session,
      REVIEW_FINALIZED_RECORD as never,
      { receipts: { '/review': { reviewDir: '', receipt: {}, callId: null } } } as never,
    )
    expect(stateOf(projections, session)).toBe(before)
    expect(stateOf(projections, session).receipts).toEqual({})
  })

  it('fails loudly, before spawning, when the projection service is missing', async () => {
    const { tools } = harness({ projection: false })
    const session = newSession('session-finalize-no-projection')
    const out = tempDir()
    const mock = installSpawn(child => child.finish(0))

    await expect(toolOf(tools).execute({ out }, execFor(session))).rejects.toThrow(
      /session-projection service/,
    )
    expect(mock).not.toHaveBeenCalled()
    expect(session.seq).toBe(0)
  })

  it('fails loudly, before spawning, when the call has no current Session', async () => {
    const { tools } = harness()
    const out = tempDir()
    const mock = installSpawn(child => child.finish(0))

    await expect(
      toolOf(tools).execute({ out }, { signal: new AbortController().signal, callId: 'c-1' }),
    ).rejects.toThrow(/no current Session/)
    expect(mock).not.toHaveBeenCalled()
  })

  it('requires out and never spawns without it', async () => {
    const { tools } = harness()
    const session = newSession('session-finalize-no-out')
    const mock = installSpawn(child => child.finish(0))

    await expect(toolOf(tools).execute({}, execFor(session))).rejects.toThrow(/out is required/)
    expect(mock).not.toHaveBeenCalled()
    expect(session.seq).toBe(0)
  })

  it('treats cancellation as an error and records nothing', async () => {
    const { projections, tools } = harness()
    const session = newSession('session-finalize-abort')
    const out = tempDir()
    installSpawn(() => {
      // Never closes; the caller's cancellation ends it.
    })
    const controller = new AbortController()
    const pending = toolOf(tools).execute({ out }, execFor(session, controller))
    await new Promise(resolve => setTimeout(resolve, 25))
    controller.abort()

    await expect(pending).rejects.toThrow(/was cancelled/)
    expect(session.seq).toBe(0)
    expect(stateOf(projections, session).receipts).toEqual({})
  })

  it('treats a timeout as an error and records nothing', async () => {
    const { projections, tools } = harness()
    const session = newSession('session-finalize-timeout')
    const out = tempDir()
    installSpawn(() => {
      // Never closes; the deadline kills it.
    })

    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const pending = toolOf(tools).execute({ out }, execFor(session))
    const assertion = expect(pending).rejects.toThrow(
      new RegExp(`did not finish within ${REVIEW_FINALIZE_TIMEOUT_MS}ms`),
    )
    await vi.advanceTimersByTimeAsync(REVIEW_FINALIZE_TIMEOUT_MS)
    await assertion

    vi.useRealTimers()
    expect(session.seq).toBe(0)
    expect(stateOf(projections, session).receipts).toEqual({})
  })
})

describe('review-finalize directory keys', () => {
  it.skipIf(process.platform !== 'win32')('folds a Windows path case-insensitively', () => {
    const upper = resolve('E:/Boardwise/Reviews/537')
    const lower = resolve('e:/boardwise/reviews/537')
    expect(upper).not.toBe(lower)
    expect(directoryKeyOf(upper)).toBe(directoryKeyOf(lower))
  })

  it('keeps distinct directories distinct', () => {
    expect(directoryKeyOf(resolve('a'))).not.toBe(directoryKeyOf(resolve('b')))
  })
})
