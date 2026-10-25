/**
 * 537D3b: the `present` delivery hard gate, exercised through the listener
 * `apply` actually mounts.
 *
 * These tests never call the decision helper directly: every case builds a real
 * cordis `Context`, registers the plugin on it, captures the
 * `tools/pre-execute` listener from `ctx.on`, and drives it with a real
 * `dsh-session` Session and a real `SessionProjectionRegistry`. The Session
 * record fixture is appended with `appendPluginRecord` and read back through
 * `stateOf`, which proves the projection really is 537D3a's
 * `plugin:boardwise-dsh/review-finalized` type.
 *
 * The filesystem adapter is a small `ctx.fs` over real temporary files: it
 * supports byte windows, counts every call, and can fail `stat` / `read` on
 * demand. The gate therefore never touches `node:fs` in these tests either.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@deepseek-ai/dsh-tools', () => ({ defineTool: (options: unknown) => options }))

import { createHash } from 'node:crypto'
import {
  closeSync,
  mkdirSync,
  mkdtempSync,
  openSync,
  readFileSync,
  readSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path'
import { Context } from '@deepseek-ai/cordis'
import { Session, appendPluginRecord } from '@deepseek-ai/dsh-session'
import { SessionProjectionRegistry } from '@deepseek-ai/dsh-session-projection'
import { apply } from '../src/index.ts'
import {
  REVIEW_FINALIZE_AUTHORITY,
  REVIEW_FINALIZE_SCHEMA,
  REVIEW_FINALIZE_SCOPE,
  REVIEW_FINALIZED_KEY,
  REVIEW_FINALIZED_RECORD,
  directoryKeyOf,
  type ReviewFinalizeReceipt,
} from '../src/review-finalize.ts'
import {
  REVIEW_DELIVERY_CHUNK_BYTES,
  REVIEW_DELIVERY_EVENT,
  type DeliveryFileSystem,
  type DeliveryStat,
  type DeliveryTarget,
} from '../src/review-delivery.ts'

/* ------------------------------------------------------------------ fixtures */

const made: string[] = []

function tempDir(prefix = 'boardwise-delivery-'): string {
  const dir = mkdtempSync(join(tmpdir(), prefix))
  made.push(dir)
  return dir
}

/** The five files the CLI would sign for a minimal complete delivery. */
const DELIVERY_FILES: Readonly<Record<string, string>> = {
  'report.json': '{"conclusion":"pass-with-notes"}\n',
  'report.md': '# report\n',
  'board-report.md': '# board report\n',
  'review-summary.md': '# review summary\n',
  'empty.txt': '',
}

interface MadeDelivery {
  dir: string
  receipt: ReviewFinalizeReceipt
  names: readonly string[]
}

/** Write a delivery directory and sign a receipt from its real bytes. */
function makeDelivery(extra: Readonly<Record<string, string>> = {}): MadeDelivery {
  const dir = tempDir()
  const files = { ...DELIVERY_FILES, ...extra }
  for (const [name, content] of Object.entries(files)) {
    const path = join(dir, ...name.split('/'))
    mkdirSync(dirname(path), { recursive: true })
    writeFileSync(path, content, 'utf8')
  }
  return { dir, receipt: receiptFor(dir, Object.keys(files)), names: Object.keys(files) }
}

/** The receipt rows for the named files, computed from disk right now. */
function receiptFor(dir: string, names: readonly string[]): ReviewFinalizeReceipt {
  const files = names
    .map(path => {
      const bytes = readFileSync(join(dir, ...path.split('/')))
      return {
        path,
        bytes: bytes.byteLength,
        sha256: createHash('sha256').update(bytes).digest('hex'),
      }
    })
    .sort((left, right) => left.path.localeCompare(right.path))
  return {
    schema: REVIEW_FINALIZE_SCHEMA,
    ok: true,
    scope: REVIEW_FINALIZE_SCOPE,
    boardConclusionAuthority: REVIEW_FINALIZE_AUTHORITY,
    files,
  }
}

/* --------------------------------------------------------------- ctx.fs seam */

type Fault = (path: string) => Error | undefined

/** A real-file `ctx.fs`: lexical resolve, stat, containment and byte windows. */
class TempFs implements DeliveryFileSystem {
  readonly resolves: string[] = []
  readonly stats: string[] = []
  readonly reads: { path: string; offset: number; length: number }[] = []
  statFault: Fault | undefined
  readFault: Fault | undefined

  async resolve(path: string, opts?: { cwd?: string; signal?: AbortSignal }): Promise<DeliveryTarget> {
    opts?.signal?.throwIfAborted()
    const cwd = opts?.cwd ?? process.cwd()
    const absolute = isAbsolute(path) ? path : resolve(cwd, path)
    this.resolves.push(absolute)
    return { targetKey: absolute, displayPath: absolute }
  }

  processPath(target: DeliveryTarget): string {
    return target.targetKey
  }

  contains(parent: DeliveryTarget, child: DeliveryTarget): boolean {
    const rel = relative(parent.targetKey, child.targetKey)
    return rel === '' || (rel !== '..' && !rel.startsWith(`..${sep}`) && !isAbsolute(rel))
  }

  async stat(target: DeliveryTarget, signal?: AbortSignal): Promise<DeliveryStat | undefined> {
    signal?.throwIfAborted()
    this.stats.push(target.targetKey)
    const fault = this.statFault?.(target.targetKey)
    if (fault !== undefined) throw fault
    try {
      const info = statSync(target.targetKey)
      return {
        type: info.isFile() ? 'file' : info.isDirectory() ? 'directory' : 'other',
        size: info.size,
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return undefined
      throw error
    }
  }

  async readByteRange(
    target: DeliveryTarget,
    range: { offset: number; length: number },
    signal?: AbortSignal,
  ): Promise<Uint8Array> {
    signal?.throwIfAborted()
    this.reads.push({ path: target.targetKey, offset: range.offset, length: range.length })
    const fault = this.readFault?.(target.targetKey)
    if (fault !== undefined) throw fault
    const fd = openSync(target.targetKey, 'r')
    try {
      const buffer = Buffer.alloc(range.length)
      const count = readSync(fd, buffer, 0, range.length, range.offset)
      return new Uint8Array(buffer.subarray(0, count))
    } finally {
      closeSync(fd)
    }
  }

  /** Every read window for one path, in call order. */
  windowsFor(path: string): { offset: number; length: number }[] {
    return this.reads.filter(read => read.path === path).map(({ offset, length }) => ({ offset, length }))
  }
}

/* ------------------------------------------------------------ plugin harness */

type Decision = { kind: 'allow' } | { kind: 'deny'; reason: string }

type Listener = (exec: Exec, next: () => Promise<Decision>) => Promise<Decision>

interface Exec {
  name: string
  arguments: unknown
  agent?: { session: InstanceType<typeof Session> }
  signal: AbortSignal
  callId: string
  token: symbol
}

interface Harness {
  projections: InstanceType<typeof SessionProjectionRegistry>
  fs: TempFs
  listeners: Map<string, Listener>
  session: (id: string) => InstanceType<typeof Session>
  useSession: (session: InstanceType<typeof Session>, cwd: string) => void
  present: (
    session: InstanceType<typeof Session>,
    files: readonly (string | { path: string })[],
    options?: { name?: string; args?: unknown; signal?: AbortSignal },
  ) => Promise<{ decision: Decision; nextCalls: number }>
}

/** Register the real plugin on a real proxy context and capture its listener. */
function harness(): Harness {
  const cordis = new Context()
  const projections = new SessionProjectionRegistry(cordis)
  const fs = new TempFs()
  const listeners = new Map<string, Listener>()
  const cwds = new WeakMap<object, string>()
  const fallback = tempDir('boardwise-workspace-')

  const pluginCtx = {
    tools: { register: () => () => {} },
    sessionProjections: projections,
    fs,
    workingDirectory: {
      get: (session: object) => cwds.get(session) ?? fallback,
    },
    on: (event: string, listener: Listener) => {
      listeners.set(event, listener)
      return () => true
    },
  }
  apply(pluginCtx as never)

  const listener = listeners.get(REVIEW_DELIVERY_EVENT)
  if (listener === undefined) throw new Error(`apply did not register ${REVIEW_DELIVERY_EVENT}`)

  const useSession = (session: InstanceType<typeof Session>, cwd: string): void => {
    cwds.set(session, cwd)
  }

  return {
    projections,
    fs,
    listeners,
    session: id => Session.create(id as never),
    useSession,
    present: async (session, files, options = {}) => {
      const next = vi.fn(async (): Promise<Decision> => ({ kind: 'allow' }))
      const exec: Exec = {
        name: options.name ?? 'present',
        arguments:
          options.args ??
          ({
            files: files.map(file => (typeof file === 'string' ? { path: file } : file)),
          } as unknown),
        agent: { session },
        signal: options.signal ?? new AbortController().signal,
        callId: 'call-present-1',
        // A recognisable secret: no denial reason may echo it.
        token: Symbol('delivery-gate-secret-token'),
      }
      const decision = await listener(exec, next)
      return { decision, nextCalls: next.mock.calls.length }
    },
  }
}

interface ReceiptFixture {
  dir: string
  receipt: ReviewFinalizeReceipt
  keyOverride?: string
}

/**
 * Append 537D3a's record — the **complete** post-change receipt map — and prove
 * the real projection serves it. Several directories go in one record because
 * a whole-value record replaces the state rather than adding to it.
 */
function appendReceipts(
  h: Harness,
  session: InstanceType<typeof Session>,
  fixtures: readonly ReceiptFixture[],
  options: { projected?: boolean } = {},
): string[] {
  const receipts: Record<string, unknown> = {}
  const keys = fixtures.map(fixture => {
    const key = fixture.keyOverride ?? directoryKeyOf(resolve(fixture.dir))
    receipts[key] = { reviewDir: resolve(fixture.dir), receipt: fixture.receipt, callId: 'call-finalize-1' }
    return key
  })
  appendPluginRecord(session, REVIEW_FINALIZED_RECORD, { receipts } as never)
  // The type literal and the real registry are both part of the fixture: this
  // is exactly the D3a record the gate is documented to read.
  expect(REVIEW_FINALIZED_RECORD).toBe('plugin:boardwise-dsh/review-finalized')
  const state = h.projections.stateOf(session, REVIEW_FINALIZED_KEY) as
    | { receipts: Record<string, unknown> }
    | undefined
  for (const [index, key] of keys.entries()) {
    if (options.projected === false) {
      // The projection refused this record (a path escape is not a receipt), so
      // the Session must hold no entry for it.
      expect(state?.receipts[key], `fixture ${index}`).toBeUndefined()
    } else {
      expect(state?.receipts[key], `fixture ${index}`).toBeDefined()
    }
  }
  return keys
}

/** The single-directory form of {@link appendReceipts}. */
function appendReceipt(
  h: Harness,
  session: InstanceType<typeof Session>,
  dir: string,
  receipt: ReviewFinalizeReceipt,
  keyOverride?: string,
  options: { projected?: boolean } = {},
): string {
  return appendReceipts(h, session, [{ dir, receipt, ...(keyOverride === undefined ? {} : { keyOverride }) }], options)[0] as string
}

function expectDenied(result: { decision: Decision; nextCalls: number }, pattern: RegExp): void {
  expect(result.decision.kind).toBe('deny')
  expect(result.nextCalls).toBe(0)
  if (result.decision.kind === 'deny') {
    expect(result.decision.reason).toMatch(pattern)
    expect(result.decision.reason).not.toContain('delivery-gate-secret-token')
  }
}

function expectAllowed(result: { decision: Decision; nextCalls: number }): void {
  expect(result.decision).toEqual({ kind: 'allow' })
  expect(result.nextCalls).toBe(1)
}

afterEach(() => {
  for (const dir of made.splice(0)) rmSync(dir, { recursive: true, force: true })
})

/* -------------------------------------------------------------------- tests */

describe('present delivery gate: ordinary files are untouched', () => {
  it('lets images, Office files and a report.md with no review marker through', async () => {
    const h = harness()
    const session = h.session('session-delivery-ordinary')
    const workspace = tempDir('boardwise-workspace-')
    h.useSession(session, workspace)
    const photo = join(workspace, 'photo.png')
    const deck = join(workspace, 'deck.pptx')
    const report = join(workspace, 'report.md')
    writeFileSync(photo, 'png')
    writeFileSync(deck, 'pptx')
    writeFileSync(report, '# a plain report, not a delivery\n')

    expectAllowed(await h.present(session, [photo, deck, report]))
    // No receipt was involved, so nothing was hashed.
    expect(h.fs.reads).toEqual([])
  })

  it('leaves every non-present tool alone, without touching the filesystem', async () => {
    const h = harness()
    const session = h.session('session-delivery-other-tool')
    const result = await h.present(session, [join(tempDir(), 'x.epro2')], {
      name: 'boardwise_checkup',
      args: { file: 'x.epro2' },
    })
    expectAllowed(result)
    expect(h.fs.resolves).toEqual([])
    expect(h.fs.stats).toEqual([])
    expect(h.fs.reads).toEqual([])
  })

  it('leaves a shape present itself rejects to present', async () => {
    const h = harness()
    const session = h.session('session-delivery-shape')
    expectAllowed(await h.present(session, [], { args: { files: 'not-an-array' } }))
    expectAllowed(await h.present(session, [], { args: { files: [{ path: 7 }] } }))
    expectAllowed(await h.present(session, [], { args: { files: [{ path: '  ' }] } }))
    expect(h.fs.reads).toEqual([])
  })
})

describe('present delivery gate: only the current Session receipt authorizes', () => {
  it('denies a marker directory with no record, even beside a hand-written finalize.json', async () => {
    const delivery = makeDelivery()
    const h = harness()
    const session = h.session('session-delivery-no-record')
    h.useSession(session, delivery.dir)
    // A perfectly shaped receipt on disk, written by hand: never authorization.
    writeFileSync(
      join(delivery.dir, 'finalize.json'),
      `${JSON.stringify(delivery.receipt, null, 2)}\n`,
      'utf8',
    )

    expectDenied(await h.present(session, ['report.json']), /not finalized|authorization/i)
    expect(h.fs.reads.every(read => !read.path.endsWith('finalize.json'))).toBe(true)
  })

  it('denies a parallel present that runs before finalize completed', async () => {
    const delivery = makeDelivery()
    const h = harness()
    const session = h.session('session-delivery-parallel')
    h.useSession(session, delivery.dir)
    // finalize is in flight: the marker exists, the Session record does not yet.
    expectDenied(await h.present(session, ['board-report.md']), /not finalized/i)
  })

  it('keeps one Session receipt invisible to another Session', async () => {
    const delivery = makeDelivery()
    const h = harness()
    const owner = h.session('session-delivery-owner')
    const intruder = h.session('session-delivery-intruder')
    h.useSession(owner, delivery.dir)
    h.useSession(intruder, delivery.dir)
    appendReceipt(h, owner, delivery.dir, delivery.receipt)

    expectDenied(await h.present(intruder, ['report.json']), /not finalized/i)
    expectAllowed(await h.present(owner, ['report.json']))
  })

  it('denies an untracked file and the receipt itself inside a finalized directory', async () => {
    const delivery = makeDelivery()
    const h = harness()
    const session = h.session('session-delivery-untracked')
    h.useSession(session, delivery.dir)
    appendReceipt(h, session, delivery.dir, delivery.receipt)
    writeFileSync(join(delivery.dir, 'notes.txt'), 'not signed\n')
    writeFileSync(join(delivery.dir, 'finalize.json'), '{}\n')

    expectDenied(await h.present(session, ['notes.txt']), /untracked/i)
    expectDenied(await h.present(session, ['finalize.json']), /untracked|not tracked/i)
    expect(h.fs.reads).toEqual([])
  })

  it('denies a record entry whose key and reviewDir disagree', async () => {
    const delivery = makeDelivery()
    const h = harness()
    const session = h.session('session-delivery-bad-entry')
    h.useSession(session, delivery.dir)
    // A record the projection schema accepts (arbitrary map key), but which a
    // self-consistent delivery can never produce.
    appendReceipt(h, session, delivery.dir, delivery.receipt, 'some-other-directory-key')

    expectDenied(await h.present(session, ['report.json']), /not usable|map key/i)
    expect(h.fs.reads).toEqual([])
  })

  it('denies a receipt that signs finalize.json itself', async () => {
    const delivery = makeDelivery()
    const h = harness()
    const session = h.session('session-delivery-signs-itself')
    h.useSession(session, delivery.dir)
    const receipt: ReviewFinalizeReceipt = {
      ...delivery.receipt,
      files: [
        ...delivery.receipt.files,
        { path: 'finalize.json', bytes: 2, sha256: 'a'.repeat(64) },
      ],
    }
    appendReceipt(h, session, delivery.dir, receipt)

    expectDenied(await h.present(session, ['report.json']), /not usable|finalize\.json/i)
  })
})

describe('present delivery gate: a matched receipt must still match its files', () => {
  it('allows a delivery only when every tracked file matches, including a zero-byte file', async () => {
    const delivery = makeDelivery()
    const h = harness()
    const session = h.session('session-delivery-good')
    h.useSession(session, delivery.dir)
    appendReceipt(h, session, delivery.dir, delivery.receipt)

    expectAllowed(await h.present(session, ['report.json', 'review-summary.md']))

    // The presented pair is verified, and so is every other tracked file.
    const readPaths = new Set(h.fs.reads.map(read => read.path))
    for (const name of ['report.json', 'report.md', 'board-report.md', 'review-summary.md']) {
      expect(readPaths.has(join(delivery.dir, name)), `missing hash read for ${name}`).toBe(true)
    }
    // A zero-byte file hashes without any read window.
    expect(readPaths.has(join(delivery.dir, 'empty.txt'))).toBe(false)
  })

  it('denies when the presented file changed after finalize', async () => {
    const delivery = makeDelivery()
    const h = harness()
    const session = h.session('session-delivery-presented-changed')
    h.useSession(session, delivery.dir)
    appendReceipt(h, session, delivery.dir, delivery.receipt)
    writeFileSync(join(delivery.dir, 'report.json'), '{"conclusion":"pass"}\n')

    expectDenied(await h.present(session, ['report.json']), /report\.json/i)
  })

  it('denies a same-size rewrite of the presented file: only the recomputed sha256 can catch it', async () => {
    // The *presented* file, not "another tracked file": `report.json` is exactly
    // what this call hands to present. `pass-with-notes` → `fail-with-notes`
    // keeps both words 15 bytes, so the size checks before and after the read
    // all pass and the recomputed digest is the one gate left standing.
    const delivery = makeDelivery()
    const h = harness()
    const session = h.session('session-delivery-presented-same-size')
    h.useSession(session, delivery.dir)
    appendReceipt(h, session, delivery.dir, delivery.receipt)

    const rewritten = '{"conclusion":"fail-with-notes"}\n'
    const signed = delivery.receipt.files.find(row => row.path === 'report.json')
    expect(signed, 'report.json must be tracked by the receipt').toBeDefined()
    // A receipt row whose byte count still matches is what makes this a
    // same-size rewrite rather than the plain length change above.
    expect(Buffer.byteLength(rewritten, 'utf8')).toBe(signed?.bytes)
    writeFileSync(join(delivery.dir, 'report.json'), rewritten)

    expectDenied(await h.present(session, ['report.json']), /report\.json.*sha256/i)
  })

  it('denies when a tracked file that is not presented changed after finalize', async () => {
    const delivery = makeDelivery()
    const h = harness()
    const session = h.session('session-delivery-other-changed')
    h.useSession(session, delivery.dir)
    appendReceipt(h, session, delivery.dir, delivery.receipt)
    writeFileSync(join(delivery.dir, 'report.md'), '# rewritten by a later checkup\n')

    expectDenied(await h.present(session, ['report.json']), /report\.md/i)
  })

  it('denies a same-size rewrite: only the recomputed sha256 can catch it', async () => {
    const delivery = makeDelivery()
    const h = harness()
    const session = h.session('session-delivery-same-size')
    h.useSession(session, delivery.dir)
    appendReceipt(h, session, delivery.dir, delivery.receipt)
    // Same byte count as `# report\n`, different content: size alone passes.
    writeFileSync(join(delivery.dir, 'report.md'), '# REPORT\n')

    expectDenied(await h.present(session, ['report.json']), /report\.md.*sha256/i)
  })

  it('does not bypass a deleted marker: the Session root is recognized, then the hash set fails', async () => {
    const delivery = makeDelivery()
    const h = harness()
    const session = h.session('session-delivery-marker-gone')
    h.useSession(session, delivery.dir)
    appendReceipt(h, session, delivery.dir, delivery.receipt)
    rmSync(join(delivery.dir, 'review-summary.md'))

    expectDenied(await h.present(session, ['report.json']), /review-summary\.md/i)
  })

  it('denies a missing tracked file and a failed stat/read with the relative path named', async () => {
    const delivery = makeDelivery()
    const h = harness()
    const session = h.session('session-delivery-missing')
    h.useSession(session, delivery.dir)
    appendReceipt(h, session, delivery.dir, delivery.receipt)
    rmSync(join(delivery.dir, 'board-report.md'))

    expectDenied(await h.present(session, ['report.json']), /board-report\.md.*missing/i)

    const delivery2 = makeDelivery()
    const h2 = harness()
    const session2 = h2.session('session-delivery-stat-fault')
    h2.useSession(session2, delivery2.dir)
    appendReceipt(h2, session2, delivery2.dir, delivery2.receipt)
    h2.fs.statFault = path => (path.endsWith('report.md') ? new Error('stat exploded') : undefined)

    expectDenied(await h2.present(session2, ['report.json']), /report\.md.*(inspected|stat exploded)/i)

    const delivery3 = makeDelivery()
    const h3 = harness()
    const session3 = h3.session('session-delivery-read-fault')
    h3.useSession(session3, delivery3.dir)
    appendReceipt(h3, session3, delivery3.dir, delivery3.receipt)
    h3.fs.readFault = path => (path.endsWith('report.json') ? new Error('read exploded') : undefined)

    expectDenied(await h3.present(session3, ['report.json']), /report\.json.*(read|read exploded)/i)
  })

  it('refuses a receipt path escape before reading any content', async () => {
    const delivery = makeDelivery()
    const h = harness()
    const session = h.session('session-delivery-escape')
    h.useSession(session, delivery.dir)
    const escaped: ReviewFinalizeReceipt = {
      ...delivery.receipt,
      files: [
        { path: '../outside.txt', bytes: 1, sha256: 'a'.repeat(64) },
        ...delivery.receipt.files,
      ],
    }
    // 537D3a's projection refuses this record outright, so the Session holds no
    // usable receipt: the gate denies a marker directory and reads nothing.
    appendReceipt(h, session, delivery.dir, escaped, undefined, { projected: false })

    expectDenied(await h.present(session, ['report.json']), /not finalized|not usable/i)
    expect(h.fs.reads).toEqual([])
  })

  it('hashes a tracked file larger than 1 MiB in bounded chunks', async () => {
    const big = 'A'.repeat(REVIEW_DELIVERY_CHUNK_BYTES * 2 + 1234)
    const delivery = makeDelivery({ 'big.bin': big })
    const h = harness()
    const session = h.session('session-delivery-big')
    h.useSession(session, delivery.dir)
    appendReceipt(h, session, delivery.dir, delivery.receipt)

    expectAllowed(await h.present(session, ['big.bin']))

    const windows = h.fs.windowsFor(join(delivery.dir, 'big.bin'))
    expect(windows).toHaveLength(3)
    expect(windows.map(window => window.length)).toEqual([
      REVIEW_DELIVERY_CHUNK_BYTES,
      REVIEW_DELIVERY_CHUNK_BYTES,
      1234,
    ])
    expect(windows[0]?.offset).toBe(0)
    expect(windows[1]?.offset).toBe(REVIEW_DELIVERY_CHUNK_BYTES)
    for (const window of windows) expect(window.length).toBeLessThanOrEqual(REVIEW_DELIVERY_CHUNK_BYTES)
  })
})

describe('present delivery gate: nested directories never borrow a receipt', () => {
  it('denies a nested marker directory that has no receipt of its own', async () => {
    const parent = makeDelivery()
    const h = harness()
    const session = h.session('session-delivery-nested')
    h.useSession(session, parent.dir)
    appendReceipt(h, session, parent.dir, parent.receipt)

    const nested = join(parent.dir, 'appendix')
    mkdirSync(nested)
    writeFileSync(join(nested, 'review-summary.md'), '# appendix summary\n')
    writeFileSync(join(nested, 'report.json'), '{}\n')

    // The nearest root is the nested marker directory; the parent receipt is not
    // allowed to authorize it. The parent's own file still passes.
    expectDenied(await h.present(session, ['appendix/report.json']), /not finalized/i)
    expectAllowed(await h.present(session, ['report.json']))
  })

  it('keeps sibling deliveries independent', async () => {
    const left = makeDelivery()
    const right = makeDelivery()
    const h = harness()
    const session = h.session('session-delivery-siblings')
    h.useSession(session, left.dir)
    appendReceipts(h, session, [
      { dir: left.dir, receipt: left.receipt },
      { dir: right.dir, receipt: right.receipt },
    ])

    writeFileSync(join(right.dir, 'report.md'), '# right changed\n')

    // Changing right cannot invalidate left.
    expectAllowed(await h.present(session, ['report.json']))
    expectDenied(await h.present(session, [join(right.dir, 'report.json')]), /right|report\.md/i)
  })
})

describe('present delivery gate: registration contract', () => {
  it('mounts the listener only when fs, workingDirectory and the projection registry exist', () => {
    const minimal: string[] = []
    apply({
      tools: { register: () => () => {} },
      on: (event: string) => {
        minimal.push(event)
        return () => true
      },
    } as never)
    // The light fake context of the older tests still mounts the tools, but no
    // gate is invented without the services it needs.
    expect(minimal).not.toContain(REVIEW_DELIVERY_EVENT)

    const h = harness()
    expect(h.listeners.has(REVIEW_DELIVERY_EVENT)).toBe(true)
  })
})
