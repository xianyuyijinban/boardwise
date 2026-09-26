/**
 * boardwise tools for the DeepSeek Harness (task 045).
 *
 * Four thin tools over the local boardwise CLI: checkup / arch / doctor run the
 * review harness itself, bridge is the escape hatch into the connector's action
 * catalogue. No review logic lives here — arguments are passed through, stdout
 * and the exit code come back, and the report files the CLI wrote are named for
 * the model (task 045 §1: "any idea of recomputing this in TS is refused").
 */

import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { existsSync } from 'node:fs'
import { mkdir, mkdtemp, stat } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import {
  OUT_DIR_PREFIX,
  STDOUT_HEAD_BYTES,
  STDOUT_TAIL_BYTES,
  runBoardwise,
  type CliResult,
} from './cli.ts'

/** Cordis plugin name; the row id in `cordis.patch.yml` is `tool-boardwise`. */
export const name = 'boardwise-dsh'
/** This plugin only contributes tools. */
export const inject = ['tools']

const CHECKUP_TIMEOUT_MS = 600_000
const ARCH_TIMEOUT_MS = 120_000
const DOCTOR_TIMEOUT_MS = 60_000
const BRIDGE_TIMEOUT_MS = 120_000

/** How much of a killed run's stdout rides along in the error. */
const FAILURE_TAIL_CHARS = 2000

/** The part of an execution this plugin uses: caller cancellation. */
interface Cancellable {
  readonly signal?: AbortSignal | undefined
}

/** One file the CLI was supposed to write. */
interface ArtifactNote {
  readonly label: string
  readonly path: string
}

/** The output contract every tool here shares: one text block. */
const TEXT_OUTPUT = {
  schema: { type: 'string' as const },
  render: (_args: unknown, value: string) => [{ type: 'text' as const, text: value }],
}

export function apply(ctx: Context): void {
  ctx.tools.register(defineTool({
    name: 'boardwise_checkup',
    description:
      'Review one EasyEDA Pro design with boardwise and read the report that comes back. ' +
      'Designs are named exactly once: file= runs fully offline on an exported .epro2/.enet backup ' +
      '(no editor, no daemon), while project= or instance= reads the project open in the editor ' +
      'through the local bridge daemon — the live path only reads, it never edits. ' +
      'boardwise writes report.json, report.md and architecture.md into `out` (a fresh temp directory when ' +
      'omitted) and this tool returns those paths, the CLI stdout and its exit code: 0 = a model was read and ' +
      'nothing is an ERROR, 2 = the input cannot be used, 3 = the online state cannot be stated ' +
      '(usually several editor windows are connected, so name one with project=/instance=). ' +
      'A timeout longer than 10 minutes means the plugin gave up on it.',
    parameters: {
      file: {
        type: 'string',
        description:
          'Path to an exported .epro2 / .enet backup to review offline. Exclusive with project/instance.',
      },
      project: {
        type: 'string',
        description:
          'Editor window to read live, by project name or uuid. Needed when several windows are connected ' +
          'and the focus is ambiguous.',
      },
      instance: {
        type: 'string',
        description:
          'The same choice spelled as the window key `bridge status` prints — for a window that cannot name ' +
          'a project yet. Exclusive with file.',
      },
      out: {
        type: 'string',
        description:
          `Directory for report.json / report.md / architecture.md (created if missing). ` +
          `Default: a fresh temp directory with the prefix "${OUT_DIR_PREFIX}".`,
      },
    },
    output: TEXT_OUTPUT,
    execute: async (args, exec) => {
      const tool = 'boardwise_checkup'
      const file = text(args.file)
      const project = text(args.project)
      const instance = text(args.instance)
      const named = [file, project, instance].filter(value => value !== '').length
      if (named !== 1) {
        throw new Error(
          `${tool}: name exactly one design — file (an exported .epro2/.enet, offline) or project/instance ` +
          `(the project open in the editor). Got ${named} of the three; boardwise never guesses which window to read.`,
        )
      }
      if (file !== '') requireExistingFile(tool, file)

      const outDir = text(args.out) !== '' ? text(args.out) : await mkdtemp(join(tmpdir(), OUT_DIR_PREFIX))
      await ensureDirectory(tool, outDir)

      const argv = ['checkup']
      if (file !== '') argv.push('--file', file)
      else if (project !== '') argv.push('--project', project)
      else argv.push('--instance', instance)
      argv.push('--out', outDir)

      return await executeCli(tool, argv, CHECKUP_TIMEOUT_MS, exec, [
        { label: 'report.json', path: join(outDir, 'report.json') },
        { label: 'report.md', path: join(outDir, 'report.md') },
        { label: 'architecture.md', path: join(outDir, 'architecture.md') },
      ])
    },
    timeoutMs: CHECKUP_TIMEOUT_MS,
  }))

  ctx.tools.register(defineTool({
    name: 'boardwise_arch',
    description:
      'Generate the architecture skeleton boardwise builds for one exported .epro2/.enet (task 044): power tree, ' +
      'analog chains, control chains, buses and design-intent slots, with every judgement a tool cannot make left ' +
      'as a TODO slot for the engineer to fill. Offline and deterministic — the same model yields byte-identical ' +
      'markdown, so the artifact can be diffed and kept as the living record of designed intent. ' +
      'Without `out` the markdown comes back on stdout (long; it may be truncated); with `out` it is written to that ' +
      'file and the path is returned. Exit 0 = generated, 2 = the input cannot be used.',
    parameters: {
      file: {
        type: 'string',
        required: true,
        description: 'The .epro2 / .enet export to read (read-only).',
      },
      out: {
        type: 'string',
        description: 'Write the markdown here instead of stdout (parent directories are created).',
      },
    },
    output: TEXT_OUTPUT,
    execute: async (args, exec) => {
      const tool = 'boardwise_arch'
      const file = requireExistingFile(tool, text(args.file))
      const out = text(args.out)

      const argv = ['arch', file]
      const artifacts: ArtifactNote[] = []
      if (out !== '') {
        await ensureDirectory(tool, dirname(out))
        argv.push('--out', out)
        artifacts.push({ label: 'architecture', path: out })
      }
      return await executeCli(tool, argv, ARCH_TIMEOUT_MS, exec, artifacts)
    },
    timeoutMs: ARCH_TIMEOUT_MS,
  }))

  ctx.tools.register(defineTool({
    name: 'boardwise_doctor',
    description:
      'Diagnose the local boardwise installation in one run: the daemon answers ping, the editor extension is ' +
      'connected, the five methods the harness depends on exist, the running daemon and connector versions match ' +
      'this install, the editor is new enough, and the focused project can be read. ' +
      'project= / instance= name which editor window the online checks ask: as soon as several windows are ' +
      'connected the daemon refuses to guess, and those checks answer "not verified" instead of inventing an answer. ' +
      'Green exits 0; anything else exits 1 with one suggested fix per failing line. Read-only.',
    parameters: {
      project: {
        type: 'string',
        description: 'Editor window to ask, by project name or uuid.',
      },
      instance: {
        type: 'string',
        description: 'The same choice by window key (`bridge status` prints them); decides when both are given.',
      },
    },
    output: TEXT_OUTPUT,
    execute: async (args, exec) => {
      const tool = 'boardwise_doctor'
      const argv = ['doctor']
      if (text(args.project) !== '') argv.push('--project', text(args.project))
      if (text(args.instance) !== '') argv.push('--instance', text(args.instance))
      return await executeCli(tool, argv, DOCTOR_TIMEOUT_MS, exec)
    },
    timeoutMs: DOCTOR_TIMEOUT_MS,
  }))

  ctx.tools.register(defineTool({
    name: 'boardwise_bridge',
    description:
      'Escape hatch: call one action of the boardwise connector catalogue directly on the live editor, for probes ' +
      'and diagnosis that no higher-level tool covers (e.g. sys.probe, sys.identity, doc.list, sch.readback, ' +
      'export.render). `action` is the catalogue name and `params` a JSON object literal; project= / instance= route ' +
      'the call to one editor window when several are connected (without them the daemon answers WINDOW_UNSPECIFIED ' +
      'rather than guessing). Use read-only actions: write actions change the design the user has open, and those ' +
      'belong in the boardwise CLI under its own identity discipline, not behind a model tool. ' +
      'Daemon tokens are never printed.',
    parameters: {
      action: {
        type: 'string',
        required: true,
        description: 'Action name from the connector catalogue, e.g. "sys.probe" or "doc.list".',
      },
      params: {
        type: 'string',
        required: true,
        description: 'Action params as a JSON object literal, e.g. "{}" for no params. Passed to the CLI verbatim.',
      },
      project: {
        type: 'string',
        description: 'Route the call to the editor window with this project name or uuid.',
      },
      instance: {
        type: 'string',
        description: 'The same choice by window key; decides when both project= and instance= are given.',
      },
    },
    output: TEXT_OUTPUT,
    execute: async (args, exec) => {
      const tool = 'boardwise_bridge'
      const action = text(args.action)
      if (action === '') throw new Error(`${tool}: action is required (a name from the connector catalogue)`)
      const params = requireJsonObject(tool, text(args.params))

      const argv = ['bridge', 'call', '--action', action, '--params', params]
      if (text(args.project) !== '') argv.push('--project', text(args.project))
      if (text(args.instance) !== '') argv.push('--instance', text(args.instance))
      return await executeCli(tool, argv, BRIDGE_TIMEOUT_MS, exec)
    },
    timeoutMs: BRIDGE_TIMEOUT_MS,
  }))
}

/**
 * Run the CLI and format the outcome for the model.
 *
 * A non-zero exit is a **result**, not a failure (checkup and doctor report
 * through it). Only two things throw: a run that was killed before it answered
 * (deadline or cancellation), and a child the OS refused to start.
 */
async function executeCli(
  tool: string,
  argv: readonly string[],
  timeoutMs: number,
  exec: Cancellable,
  artifacts: readonly ArtifactNote[] = [],
): Promise<string> {
  const result = await runBoardwise({ argv, timeoutMs, signal: exec.signal })
  if (result.timedOut || result.aborted) {
    const how = result.timedOut ? `did not finish within ${timeoutMs}ms` : 'was cancelled'
    throw new Error(
      `${tool}: the boardwise CLI ${how} and was killed, so its output is incomplete. ` +
      `command: ${result.commandLine}. Last stdout: ${tailOf(result.stdout) || '(none)'}`,
    )
  }
  const notes = await Promise.all(artifacts.map(async artifact => ({
    ...artifact,
    exists: await isFile(artifact.path),
  })))
  return formatOutcome(tool, result, notes)
}

function formatOutcome(
  tool: string,
  result: CliResult,
  artifacts: readonly { label: string; path: string; exists: boolean }[],
): string {
  const lines = [
    `${tool}: exit ${result.code === null ? 'none (killed)' : result.code} (cli: ${result.cli.via})`,
    `command: ${result.commandLine}`,
  ]
  if (artifacts.length > 0) {
    lines.push('artifacts:')
    for (const artifact of artifacts) {
      lines.push(`  ${artifact.label}: ${artifact.path} [${artifact.exists ? 'present' : 'MISSING'}]`)
    }
  }
  lines.push('--- stdout ---', result.stdout.trimEnd() || '(empty)')
  if (result.truncated) {
    lines.push(
      `(stdout truncated: ${result.stdoutBytes} bytes total, head ${STDOUT_HEAD_BYTES} + tail ${STDOUT_TAIL_BYTES} kept)`,
    )
  }
  if (result.stderr.trim() !== '') lines.push('--- stderr ---', result.stderr.trimEnd())
  const hint = pythonHint(result)
  if (hint !== null) lines.push(`hint: ${hint}`)
  return lines.join('\n')
}

/**
 * The Python fallback can land on an interpreter that has no boardwise
 * installed; without this line the raw ModuleNotFoundError is the only clue.
 */
function pythonHint(result: CliResult): string | null {
  if (result.cli.via !== 'python' || result.code === 0) return null
  if (!/No module named ['"]?boardwise/i.test(result.stderr)) return null
  return (
    `the interpreter found on PATH (${result.cli.command}) has no boardwise installed: ` +
    'set BOARDWISE_EXE to one that has it, e.g. <boardwise repo>/.venv/Scripts/python.exe'
  )
}

/** Last {@link FAILURE_TAIL_CHARS} characters of a partial run. */
function tailOf(value: string): string {
  const trimmed = value.trim()
  return trimmed.length <= FAILURE_TAIL_CHARS ? trimmed : `...${trimmed.slice(-FAILURE_TAIL_CHARS)}`
}

/** A parameter that arrived as a non-empty, trimmed string, else `''`. */
function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

/** Refuse a path boardwise could only fail on, before anything is spawned. */
function requireExistingFile(tool: string, file: string): string {
  if (file === '') throw new Error(`${tool}: file is required (a .epro2 / .enet export to read)`)
  if (!existsSync(file)) {
    throw new Error(`${tool}: file not found: ${file} (paths are read as given, relative to the plugin's working directory)`)
  }
  return file
}

/**
 * Params are passed to the CLI verbatim; only the JSON syntax is checked here,
 * so a typo comes back as an argument error instead of a daemon round-trip.
 */
function requireJsonObject(tool: string, params: string): string {
  if (params === '') throw new Error(`${tool}: params is required — a JSON object literal, e.g. "{}"`)
  let parsed: unknown
  try {
    parsed = JSON.parse(params)
  } catch (error) {
    throw new Error(`${tool}: params is not valid JSON (${(error as Error).message}); expected an object literal, e.g. "{}"`)
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`${tool}: params must be a JSON object literal, e.g. "{}" or {"project":"test"}`)
  }
  return params
}

async function ensureDirectory(tool: string, dir: string): Promise<void> {
  try {
    await mkdir(dir, { recursive: true })
  } catch (error) {
    throw new Error(`${tool}: cannot create directory ${dir}: ${(error as Error).message}`)
  }
}

async function isFile(path: string): Promise<boolean> {
  try {
    return (await stat(path)).isFile()
  } catch {
    return false
  }
}
