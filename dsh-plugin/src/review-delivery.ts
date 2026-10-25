/**
 * 537D3b: the `present` delivery hard gate.
 *
 * A finalized review delivery is a directory whose content the CLI signed in
 * `finalize.json`: every tracked file (relative POSIX path, size, sha256) and
 * the complete receipt itself are recorded in the current Session's
 * `boardwiseReviewFinalized` projection by 537D3a. `finalize.json` on disk is
 * **not** an authorization: a model can write one by hand, copy one from
 * another directory, or leave the Session record from a delivery it has since
 * changed. So this gate reads only the projection and re-proves the content:
 *
 * 1. a `present` call is classified file by file. A `review-summary.md` in an
 *    ancestor directory marks a review directory, and a directory the current
 *    Session already finalized is recognized even after that marker is gone.
 *    The **nearest** such ancestor wins, so a nested delivery can never borrow
 *    its parent's (or a sibling's) receipt. Ordinary images, Office files and a
 *    `report.md` with no marker simply continue.
 * 2. the nearest review directory must have a **usable** receipt recorded for
 *    this exact Session and this exact directory. A receipt from another
 *    Session, a hand-written `finalize.json`, a delivery whose finalize has not
 *    completed yet, a malformed record, and an untracked file inside the
 *    directory are all denials.
 * 3. for a matched receipt **every** tracked file is recomputed — not only the
 *    one being presented. Each row must stay a relative POSIX path inside the
 *    directory, resolve through `ctx.fs`, be a regular file of exactly
 *    `bytes`, and hash to the recorded sha256 read in chunks of at most 1 MiB.
 *    Any change after finalize (including a tracked file nobody presented, and
 *    a deleted marker) invalidates the receipt and denies.
 *
 * Every failure — including an unexpected helper exception — is
 * `{kind: 'deny', reason}`; `next()` is never called on that path, and the
 * execution token is never echoed. All filesystem I/O goes through `ctx.fs`;
 * this module never reaches for `node:fs`.
 *
 * @module
 */

import { createHash } from 'node:crypto'
import { dirname, isAbsolute, join, relative, resolve } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import type { PreToolDecision, ToolExecution } from '@deepseek-ai/dsh-tools'
import type { Session } from '@deepseek-ai/dsh-session'
import {
  FINALIZE_RECEIPT_FILE,
  REVIEW_FINALIZED_KEY,
  directoryKeyOf,
  finalizeReceiptProblem,
  type FinalizeReceiptFile,
  type ReviewFinalizeReceipt,
} from './review-finalize.ts'

/** The one tool this gate inspects. Every other tool takes `next()` untouched. */
export const REVIEW_DELIVERY_TOOL = 'present'
/** The cordis event the listener is mounted on. */
export const REVIEW_DELIVERY_EVENT = 'tools/pre-execute'
/** The marker file whose parent directory is a review directory. */
export const REVIEW_DELIVERY_MARKER = 'review-summary.md'
/**
 * Hash chunks stay at or below 1 MiB (`readByteRange` bounds the transfer, not
 * the file), so a large delivery is read in several windows instead of one
 * unbounded buffer.
 */
export const REVIEW_DELIVERY_CHUNK_BYTES = 1_048_576

/**
 * The slice of `ctx.fs` this gate uses. Declared structurally so the plugin
 * needs no new peer dependency; a real `FileSystem` (local, sandboxed or
 * otherwise) satisfies it unchanged.
 */
export interface DeliveryTarget {
  readonly targetKey: string
  readonly displayPath: string
}

export interface DeliveryStat {
  readonly type: 'file' | 'directory' | 'other'
  readonly size?: number
}

export interface DeliveryFileSystem {
  resolve(path: string, opts?: { cwd?: string; signal?: AbortSignal }): Promise<DeliveryTarget>
  processPath(target: DeliveryTarget): string
  stat(target: DeliveryTarget, signal?: AbortSignal): Promise<DeliveryStat | undefined>
  contains(parent: DeliveryTarget, child: DeliveryTarget): boolean
  readByteRange(
    target: DeliveryTarget,
    range: { offset: number; length: number },
    signal?: AbortSignal,
  ): Promise<Uint8Array>
}

/** The slice of `ctx.workingDirectory` this gate uses. */
export interface DeliveryWorkingDirectory {
  get(session: Session): string
}

/** The slice of `ctx.sessionProjections` this gate uses. */
export interface DeliveryProjections {
  stateOf(session: Session, key: typeof REVIEW_FINALIZED_KEY): unknown
}

/** Everything the listener needs; production `inject` guarantees all three. */
export interface ReviewDeliveryServices {
  readonly fs: DeliveryFileSystem
  readonly workingDirectory: DeliveryWorkingDirectory
  readonly sessionProjections: DeliveryProjections
}

/** The `tools/pre-execute` listener shape (the registry waterfall contract). */
export type ReviewDeliveryListener = (
  exec: ToolExecution,
  next: () => Promise<PreToolDecision>,
) => Promise<PreToolDecision>

/** One receipt the gate is willing to use, bound to the Session's directory. */
interface ReceiptEntry {
  readonly kind: 'ready'
  /** The projection map key (already case-folded by `directoryKeyOf`). */
  readonly key: string
  readonly reviewDir: string
  readonly canonicalKey: string
  readonly receipt: ReviewFinalizeReceipt
}

/** A record entry that exists but cannot authorize anything. */
interface BrokenEntry {
  readonly kind: 'broken'
  readonly key: string
  readonly problem: string
  readonly canonicalKey?: string
}

type IndexedEntry = ReceiptEntry | BrokenEntry

/** Both lookups are built once per `present` call. */
interface ReceiptIndex {
  readonly byKey: ReadonlyMap<string, IndexedEntry>
  readonly byCanonical: ReadonlyMap<string, IndexedEntry>
}

/** The nearest review directory found for one presented path. */
interface ReviewLocation {
  readonly rootPath: string
  readonly rootTarget: DeliveryTarget
  readonly entry: IndexedEntry | null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/** One path key: the CLI's `normcase` recipe, reused from 537D3a. */
function foldPath(path: string): string {
  return directoryKeyOf(path)
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function deny(reason: string): PreToolDecision {
  return { kind: 'deny', reason }
}

/**
 * Mount the gate on the root context.
 *
 * Registration is optional while the services are incomplete: the older
 * registration tests mount `apply` on a light fake context that only has
 * `tools`. In production `inject` names `tools`, `sessionProjections`, `fs` and
 * `workingDirectory`, so the listener is always present there. A partial mount
 * gets no gate rather than a gate that cannot resolve paths or receipts.
 */
export function registerReviewDelivery(ctx: Context): (() => boolean) | undefined {
  const candidate = ctx as unknown as {
    fs?: DeliveryFileSystem
    workingDirectory?: DeliveryWorkingDirectory
    sessionProjections?: DeliveryProjections
  }
  if (
    candidate.fs === undefined ||
    candidate.workingDirectory === undefined ||
    candidate.sessionProjections === undefined
  ) {
    return undefined
  }
  const listener = createReviewDeliveryGate({
    fs: candidate.fs,
    workingDirectory: candidate.workingDirectory,
    sessionProjections: candidate.sessionProjections,
  })
  return ctx.on(REVIEW_DELIVERY_EVENT, listener)
}

/**
 * Build the listener itself. The main agent's independent integration can use
 * this directly with any `FileSystem`/`workingDirectory`/projection pair; the
 * plugin's own `apply` reaches it through {@link registerReviewDelivery} and
 * `ctx.on('tools/pre-execute', …)`.
 */
export function createReviewDeliveryGate(services: ReviewDeliveryServices): ReviewDeliveryListener {
  return async (exec, next) => {
    // The gate is for delivery, nothing else: no resolution, no reads.
    if (exec.name !== REVIEW_DELIVERY_TOOL) return next()

    const paths = presentedPaths(exec.arguments)
    // Not a shape this gate can classify: present itself owns that refusal.
    if (paths === null || paths.length === 0) return next()

    const session = exec.agent?.session
    // present refuses a call without an agent Session; there is no receipt to
    // compare against either, so let that tool report its own precondition.
    if (session === undefined) return next()

    let cwd: string
    try {
      cwd = services.workingDirectory.get(session)
    } catch (error) {
      return deny(`review delivery: the working directory is unavailable (${errorMessage(error)}).`)
    }
    if (!isAbsolute(cwd)) {
      return deny(`review delivery: the working directory ${JSON.stringify(cwd)} is not absolute.`)
    }

    try {
      return await decide(services, session, cwd, paths, exec.signal, next)
    } catch (error) {
      // Fail closed, including helper exceptions. `exec.token` is deliberately
      // never interpolated here (or anywhere else in this module).
      return deny(
        `review delivery: the delivery could not be verified (${errorMessage(error)}); refusing to present it.`,
      )
    }
  }
}

/** The `files[].path` strings of a `present` call, or `null` for a shape present owns. */
function presentedPaths(args: unknown): string[] | null {
  if (!isRecord(args)) return null
  const files = args['files']
  if (!Array.isArray(files)) return null
  const paths: string[] = []
  for (const file of files) {
    if (!isRecord(file)) return null
    const path = file['path']
    if (typeof path !== 'string' || path.trim() === '') return null
    paths.push(path)
  }
  return paths
}

async function decide(
  services: ReviewDeliveryServices,
  session: Session,
  cwd: string,
  paths: readonly string[],
  signal: AbortSignal | undefined,
  next: () => Promise<PreToolDecision>,
): Promise<PreToolDecision> {
  const state = services.sessionProjections.stateOf(session, REVIEW_FINALIZED_KEY)
  const index = await buildReceiptIndex(services, state, signal)
  const verified = new Map<string, string | null>()

  for (const path of paths) {
    const fileTarget = await services.fs.resolve(path, { cwd, signal })
    // Classify on the spelling the caller used (available from `displayPath`)
    // so a link *inside* a review directory is still examined as one; fall back
    // to the canonical process path for a backend whose display path is relative.
    const spelled = isAbsolute(fileTarget.displayPath) ? fileTarget.displayPath : services.fs.processPath(fileTarget)
    if (!isAbsolute(spelled)) {
      return deny(`review delivery: ${JSON.stringify(path)} did not resolve to an absolute path.`)
    }

    const found = await findReviewDirectory(services, index, spelled, cwd, signal)
    if (found === null) continue

    if (found.entry === null) {
      return deny(
        `review delivery: ${JSON.stringify(path)} is inside the review directory ` +
          `${JSON.stringify(found.rootPath)}, which the current Session has not finalized. ` +
          'A marker, a hand-written finalize.json or another Session\'s receipt is not authorization; ' +
          'run boardwise_review_finalize on that directory first.',
      )
    }
    if (found.entry.kind === 'broken') {
      return deny(
        `review delivery: ${JSON.stringify(path)} is inside a review directory whose Session receipt is not ` +
          `usable (${found.entry.problem}); refusing to present it.`,
      )
    }

    const entry = found.entry
    const relativePath = reviewRelativePath(services, found.rootTarget, fileTarget)
    if (relativePath === null) {
      return deny(
        `review delivery: ${JSON.stringify(path)} resolves outside the review directory ` +
          `${JSON.stringify(found.rootPath)} (a path escape); refusing to present it.`,
      )
    }
    if (!receiptTracks(entry.receipt, relativePath)) {
      return deny(
        `review delivery: ${JSON.stringify(relativePath)} in ${JSON.stringify(found.rootPath)} is not ` +
          'tracked by the finalized receipt (untracked); refusing to present it.',
      )
    }

    // Every tracked file, not just this one: a delivery changes when any of its
    // signed content changes, including a file nobody is presenting right now.
    let problem = verified.get(entry.key)
    if (problem === undefined) {
      problem = await verifyReceiptFiles(services, entry, found.rootTarget, signal)
      verified.set(entry.key, problem)
    }
    if (problem !== null) {
      return deny(
        `review delivery: the receipt for ${JSON.stringify(found.rootPath)} no longer matches its files: ` +
          `${problem} Refusing to present anything from that directory.`,
      )
    }
  }

  return next()
}

/**
 * Find the **nearest** ancestor of `filePath` that is a review directory: a
 * directory whose Session receipt this gate knows, or one carrying the marker.
 */
async function findReviewDirectory(
  services: ReviewDeliveryServices,
  index: ReceiptIndex,
  filePath: string,
  cwd: string,
  signal: AbortSignal | undefined,
): Promise<ReviewLocation | null> {
  let dir = dirname(filePath)
  for (;;) {
    let entry = index.byKey.get(foldPath(resolve(dir)))
    if (entry === undefined && index.byCanonical.size > 0) {
      const dirTarget = await services.fs.resolve(dir, { cwd, signal })
      entry = index.byCanonical.get(foldPath(services.fs.processPath(dirTarget)))
    }

    const marker = entry === undefined ? await hasMarker(services.fs, dir, cwd, signal) : false
    if (entry !== undefined || marker) {
      const rootTarget = await services.fs.resolve(dir, { cwd, signal })
      return { rootPath: dir, rootTarget, entry: entry ?? null }
    }

    const parent = dirname(dir)
    if (parent === dir) return null
    dir = parent
  }
}

/** Is there a regular `review-summary.md` directly inside `dir`? */
async function hasMarker(
  fs: DeliveryFileSystem,
  dir: string,
  cwd: string,
  signal: AbortSignal | undefined,
): Promise<boolean> {
  const target = await fs.resolve(join(dir, REVIEW_DELIVERY_MARKER), { cwd, signal })
  const info = await fs.stat(target, signal)
  return info !== undefined && info.type === 'file'
}

/** The presented file's path relative to the review root, POSIX-shaped. */
function reviewRelativePath(
  services: ReviewDeliveryServices,
  rootTarget: DeliveryTarget,
  fileTarget: DeliveryTarget,
): string | null {
  if (!services.fs.contains(rootTarget, fileTarget)) return null
  const rootPath = services.fs.processPath(rootTarget)
  const filePath = services.fs.processPath(fileTarget)
  const rel = relative(rootPath, filePath)
  if (rel === '' || rel === '..' || rel.startsWith(`..${'/'}`) || rel.startsWith('..\\')) return null
  if (isAbsolute(rel)) return null
  return rel.replaceAll('\\', '/')
}

/** Does the receipt sign exactly this relative POSIX path? */
function receiptTracks(receipt: ReviewFinalizeReceipt, relativePath: string): boolean {
  const needle = foldPath(relativePath)
  return receipt.files.some(row => foldPath(row.path) === needle)
}

/**
 * Recompute every tracked file of one receipt. Returns `null` when all match,
 * or one sentence naming the first relative path that does not.
 */
async function verifyReceiptFiles(
  services: ReviewDeliveryServices,
  entry: ReceiptEntry,
  rootTarget: DeliveryTarget,
  signal: AbortSignal | undefined,
): Promise<string | null> {
  const rootPath = services.fs.processPath(rootTarget)
  for (const row of entry.receipt.files) {
    const label = row.path
    let target: DeliveryTarget
    try {
      // Build the path from the receipt's own POSIX segments against the
      // canonical root: no absolute path, no `..`, no backslash reaches here
      // (537D3a's receipt check already refused them).
      target = await services.fs.resolve(join(rootPath, ...label.split('/')), { signal })
    } catch (error) {
      return `${problemFile(label)} could not be resolved (${errorMessage(error)}).`
    }
    if (!services.fs.contains(rootTarget, target)) {
      return `${problemFile(label)} resolves outside the review directory.`
    }

    let info: DeliveryStat | undefined
    try {
      info = await services.fs.stat(target, signal)
    } catch (error) {
      return `${problemFile(label)} could not be inspected (${errorMessage(error)}).`
    }
    if (info === undefined) return `${problemFile(label)} is missing.`
    if (info.type !== 'file') return `${problemFile(label)} is not a regular file (${info.type}).`
    if (info.size !== row.bytes) {
      return `${problemFile(label)} is ${describeSize(info.size)} but the receipt says ${row.bytes} bytes.`
    }

    const digest = createHash('sha256')
    let offset = 0
    try {
      while (offset < row.bytes) {
        const length = Math.min(REVIEW_DELIVERY_CHUNK_BYTES, row.bytes - offset)
        const chunk = await services.fs.readByteRange(target, { offset, length }, signal)
        if (chunk.byteLength === 0) {
          return `${problemFile(label)} ended at ${offset} of ${row.bytes} bytes.`
        }
        if (chunk.byteLength > length) {
          return `${problemFile(label)} returned ${chunk.byteLength} bytes for a ${length}-byte window.`
        }
        digest.update(chunk)
        offset += chunk.byteLength
      }
    } catch (error) {
      return `${problemFile(label)} could not be read (${errorMessage(error)}).`
    }

    // Re-prove the size after the read too: a file that grew while it was being
    // hashed must not pass on a prefix.
    let after: DeliveryStat | undefined
    try {
      after = await services.fs.stat(target, signal)
    } catch (error) {
      return `${problemFile(label)} could not be re-inspected (${errorMessage(error)}).`
    }
    if (after === undefined || after.type !== 'file' || after.size !== row.bytes) {
      return `${problemFile(label)} changed while it was being verified.`
    }

    const actual = digest.digest('hex')
    if (actual !== row.sha256) {
      return `${problemFile(label)} has sha256 ${actual}, but the receipt says ${row.sha256}.`
    }
  }
  return null
}

function problemFile(label: string): string {
  return `tracked file ${JSON.stringify(label)}`
}

function describeSize(size: number | undefined): string {
  return size === undefined ? 'of unknown size' : `${size} bytes`
}

/** Read the projection's whole state; a missing state means "no receipts". */
function receiptsOf(state: unknown): Record<string, unknown> | null {
  if (!isRecord(state)) return null
  const receipts = state['receipts']
  return isRecord(receipts) ? receipts : null
}

/**
 * Validate and index every record entry once. Shape errors are kept as
 * `broken` entries keyed by their own map key **and** by the canonical
 * directory they name, so a directory with a bad record is denied rather than
 * silently treated as unfinalized.
 */
async function buildReceiptIndex(
  services: ReviewDeliveryServices,
  state: unknown,
  signal: AbortSignal | undefined,
): Promise<ReceiptIndex> {
  const byKey = new Map<string, IndexedEntry>()
  const byCanonical = new Map<string, IndexedEntry>()
  const receipts = receiptsOf(state)
  if (receipts === null) return { byKey, byCanonical }

  for (const [rawKey, value] of Object.entries(receipts)) {
    const key = foldPath(rawKey)
    const problem = recordProblem(rawKey, value)
    const reviewDir = reviewDirOf(value)

    let canonicalKey: string | undefined
    if (reviewDir !== null) {
      try {
        const target = await services.fs.resolve(reviewDir, { signal })
        canonicalKey = foldPath(services.fs.processPath(target))
      } catch {
        // A directory that cannot be resolved can only be matched by its key.
      }
    }

    if (problem !== null) {
      const broken: BrokenEntry = { kind: 'broken', key, problem, ...(canonicalKey === undefined ? {} : { canonicalKey }) }
      byKey.set(key, broken)
      if (canonicalKey !== undefined) byCanonical.set(canonicalKey, broken)
      continue
    }

    const receipt = (value as { receipt: ReviewFinalizeReceipt }).receipt
    const ready: ReceiptEntry = {
      kind: 'ready',
      key,
      reviewDir: reviewDir as string,
      canonicalKey: canonicalKey as string,
      receipt,
    }
    byKey.set(key, ready)
    if (canonicalKey !== undefined && !byCanonical.has(canonicalKey)) byCanonical.set(canonicalKey, ready)
  }
  return { byKey, byCanonical }
}

/** The `reviewDir` field when it is a non-empty absolute string, else `null`. */
function reviewDirOf(value: unknown): string | null {
  if (!isRecord(value)) return null
  const reviewDir = value['reviewDir']
  return typeof reviewDir === 'string' && reviewDir !== '' && isAbsolute(reviewDir) ? reviewDir : null
}

/**
 * The record-entry self-consistency check: the map key and `reviewDir` must
 * agree, and the receipt itself must pass 537D3a's one receipt recipe. The
 * receipt never signs `finalize.json`, and never the same path twice.
 */
function recordProblem(rawKey: string, value: unknown): string | null {
  if (!isRecord(value)) return `the entry is not an object (${typeof value})`
  const reviewDir = value['reviewDir']
  if (typeof reviewDir !== 'string' || reviewDir === '' || !isAbsolute(reviewDir)) {
    return '`reviewDir` is not a non-empty absolute path'
  }
  const callId = value['callId']
  if (callId !== null && typeof callId !== 'string') {
    return '`callId` is neither a string nor null'
  }
  const expectedKey = directoryKeyOf(resolve(reviewDir))
  if (foldPath(rawKey) !== foldPath(expectedKey)) {
    return `the map key is ${JSON.stringify(rawKey)}, but reviewDir gives ${JSON.stringify(expectedKey)}`
  }

  const receipt = value['receipt']
  const receiptProblem = finalizeReceiptProblem(receipt)
  if (receiptProblem !== null) return `the receipt is not usable: ${receiptProblem}`

  const rows = (receipt as ReviewFinalizeReceipt).files
  const seen = new Set<string>()
  for (const row of rows as readonly FinalizeReceiptFile[]) {
    const folded = foldPath(row.path)
    if (folded === foldPath(FINALIZE_RECEIPT_FILE)) {
      return 'the receipt signs finalize.json, which a receipt can never track'
    }
    if (seen.has(folded)) return `the receipt lists ${JSON.stringify(row.path)} twice`
    seen.add(folded)
  }
  return null
}
