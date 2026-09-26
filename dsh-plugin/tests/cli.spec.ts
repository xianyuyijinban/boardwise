import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('node:child_process', () => ({ spawn: vi.fn() }))

import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  BoardwiseCliError,
  STDOUT_HEAD_BYTES,
  STDOUT_LIMIT_BYTES,
  STDOUT_TAIL_BYTES,
  redactSecrets,
  resolveCli,
  runBoardwise,
} from '../src/cli.ts'
import { installSpawn, spawnedCommand, type FakeChild } from './fake-child.ts'

/** Temp directories made by one test, removed afterwards. */
const made: string[] = []

function tempDir(name = 'boardwise-cli-'): string {
  const dir = mkdtempSync(join(tmpdir(), name))
  made.push(dir)
  return dir
}

/** A temp directory holding empty files with the given names. */
function dirWith(...names: string[]): string {
  const dir = tempDir()
  for (const name of names) writeFileSync(join(dir, name), '')
  return dir
}

afterEach(() => {
  for (const dir of made.splice(0)) rmSync(dir, { recursive: true, force: true })
})

describe('resolveCli: BOARDWISE_EXE first', () => {
  it('uses BOARDWISE_EXE as the executable when it is a boardwise build', () => {
    const dir = dirWith('boardwise.exe')
    const exe = join(dir, 'boardwise.exe')
    expect(resolveCli({ BOARDWISE_EXE: exe }, 'win32')).toEqual({ command: exe, prefix: [], via: 'env' })
  })

  it('adds `-m boardwise.cli` when BOARDWISE_EXE is a Python interpreter', () => {
    const dir = dirWith('python.exe')
    const exe = join(dir, 'python.exe')
    expect(resolveCli({ BOARDWISE_EXE: exe }, 'win32')).toEqual({
      command: exe,
      prefix: ['-m', 'boardwise.cli'],
      via: 'env',
    })
  })

  it('refuses a BOARDWISE_EXE that does not exist instead of falling back to PATH', () => {
    const missing = join(tempDir(), 'boardwise.exe')
    const env = { BOARDWISE_EXE: missing, PATH: dirWith('python.exe') }
    expect(() => resolveCli(env, 'win32')).toThrow(BoardwiseCliError)
    expect(() => resolveCli(env, 'win32')).toThrow(/BOARDWISE_EXE is set to ".+boardwise\.exe", which is not an existing file/)
  })

  it('refuses a BOARDWISE_EXE that is a directory', () => {
    const dir = mkdtempSync(join(tmpdir(), 'boardwise-dir-'))
    made.push(dir)
    expect(() => resolveCli({ BOARDWISE_EXE: dir }, 'win32')).toThrow(/not an existing file/)
  })
})

describe('resolveCli: PATH lookups', () => {
  it('finds boardwise.exe on PATH before any interpreter', () => {
    const dir = dirWith('python.exe', 'boardwise.exe')
    expect(resolveCli({ PATH: dir }, 'win32')).toEqual({
      command: join(dir, 'boardwise.exe'),
      prefix: [],
      via: 'path',
    })
  })

  it('falls back to `python -m boardwise.cli` when PATH has an interpreter only', () => {
    const dir = dirWith('python.exe')
    expect(resolveCli({ PATH: dir }, 'win32')).toEqual({
      command: join(dir, 'python.exe'),
      prefix: ['-m', 'boardwise.cli'],
      via: 'python',
    })
  })

  it('walks PATH in order and skips empty entries', () => {
    const first = tempDir()
    const second = dirWith('boardwise.exe')
    const cli = resolveCli({ PATH: `${first};;${second}` }, 'win32')
    expect(cli.command).toBe(join(second, 'boardwise.exe'))
  })

  it('requires the POSIX launcher name (boardwise, not boardwise.exe)', () => {
    const dir = dirWith('boardwise.exe')
    expect(() => resolveCli({ PATH: dir }, 'linux')).toThrow(BoardwiseCliError)
  })

  // chmod only carries the write bit on Windows, so the execute bit itself can
  // only be observed on a POSIX host.
  it.skipIf(process.platform === 'win32')('accepts an executable file on POSIX', () => {
    const dir = dirWith('boardwise')
    const cli = join(dir, 'boardwise')
    chmodSync(cli, 0o755)
    expect(resolveCli({ PATH: dir }, 'linux')).toEqual({ command: cli, prefix: [], via: 'path' })
  })

  it('names the three ways out when nothing is found', () => {
    const empty = tempDir()
    const error = (() => {
      try {
        resolveCli({ PATH: empty }, 'win32')
        return null
      } catch (thrown) {
        return thrown as Error
      }
    })()
    expect(error).toBeInstanceOf(BoardwiseCliError)
    expect(error?.message).toMatch(/boardwise CLI not found/)
    expect(error?.message).toMatch(/PATH/)
    expect(error?.message).toMatch(/BOARDWISE_EXE/)
    expect(error?.message).toMatch(/\.venv\/Scripts\/python\.exe/)
  })
})

describe('runBoardwise: spawning and reporting', () => {
  const cli = { command: 'C:/tools/boardwise.exe', prefix: [] as string[], via: 'env' as const }

  it('passes the exit code and stdout through unchanged', async () => {
    installSpawn(child => {
      child.out('findings: 0 ERROR, 1 WARN\n')
      child.finish(2)
    })
    const result = await runBoardwise({ argv: ['checkup', '--file', 'x.epro2'], timeoutMs: 5_000 }, cli)
    expect(result.code).toBe(2)
    expect(result.stdout).toBe('findings: 0 ERROR, 1 WARN\n')
    expect(result.stderr).toBe('')
    expect(result.timedOut).toBe(false)
    expect(result.aborted).toBe(false)
    expect(result.truncated).toBe(false)
  })

  it('spawns the resolved prefix followed by argv', async () => {
    const mock = installSpawn(child => child.finish(0))
    const python = { command: 'C:/venv/Scripts/python.exe', prefix: ['-m', 'boardwise.cli'], via: 'python' as const }
    await runBoardwise({ argv: ['doctor'], timeoutMs: 5_000 }, python)
    expect(spawnedCommand(mock)).toEqual([
      'C:/venv/Scripts/python.exe',
      '-m',
      'boardwise.cli',
      'doctor',
    ])
  })

  it('caps stdout at 16KB head + 16KB tail (32KB), per the tool contract', () => {
    expect(STDOUT_HEAD_BYTES).toBe(16 * 1024)
    expect(STDOUT_TAIL_BYTES).toBe(16 * 1024)
    expect(STDOUT_LIMIT_BYTES).toBe(32 * 1024)
  })

  it('keeps head and tail and marks the dropped bytes past 32KB', async () => {
    const head = 'H'.repeat(20 * 1024)
    const middle = 'M'.repeat(5 * 1024)
    const tail = 'T'.repeat(20 * 1024)
    installSpawn(child => {
      child.out(head)
      child.out(middle)
      child.out(tail)
      child.finish(0)
    })
    const result = await runBoardwise({ argv: ['arch', 'x.epro2'], timeoutMs: 5_000 }, cli)
    expect(result.stdoutBytes).toBe(45 * 1024)
    expect(result.truncated).toBe(true)
    expect(result.stdout.startsWith('H'.repeat(16 * 1024))).toBe(true)
    expect(result.stdout.endsWith('T'.repeat(16 * 1024))).toBe(true)
    // 45KB in, 32KB kept: 13312 bytes are gone, and the marker says so.
    expect(result.stdout).toContain('...[13312 bytes dropped]...')
    expect(result.stdout).not.toContain('M')
  })

  it('does not truncate at exactly the limit', async () => {
    installSpawn(child => {
      child.out('x'.repeat(32 * 1024))
      child.finish(0)
    })
    const result = await runBoardwise({ argv: ['arch', 'x.epro2'], timeoutMs: 5_000 }, cli)
    expect(result.truncated).toBe(false)
    expect(result.stdout).toHaveLength(32 * 1024)
  })

  it('decodes a multi-byte character that straddles the head/tail split', async () => {
    // One byte short of the head limit, then a 3-byte character, then a byte:
    // the split lands inside the character, and nothing is dropped after all.
    const buffer = Buffer.concat([
      Buffer.from('a'.repeat(STDOUT_HEAD_BYTES - 1)),
      Buffer.from('中'),
      Buffer.from('b'),
    ])
    installSpawn(child => {
      child.out(buffer)
      child.finish(0)
    })
    const result = await runBoardwise({ argv: ['arch', 'x.epro2'], timeoutMs: 5_000 }, cli)
    expect(result.truncated).toBe(false)
    expect(result.stdout).toBe(`${'a'.repeat(STDOUT_HEAD_BYTES - 1)}中b`)
  })

  it('kills the child when the deadline passes and reports the timeout', async () => {
    let spawned: FakeChild | undefined
    installSpawn(child => {
      spawned = child
      // Never closes on its own: only the wrapper's kill ends it.
    })
    const result = await runBoardwise({ argv: ['doctor'], timeoutMs: 10 }, cli)
    expect(result.timedOut).toBe(true)
    expect(result.code).toBeNull()
    expect(spawned?.kills).toEqual(['SIGKILL'])
  })

  it('kills the child and reports cancellation when the caller aborts', async () => {
    let spawned: FakeChild | undefined
    installSpawn(child => {
      spawned = child
    })
    const controller = new AbortController()
    const pending = runBoardwise({ argv: ['doctor'], timeoutMs: 60_000, signal: controller.signal }, cli)
    setImmediate(() => controller.abort())
    const result = await pending
    expect(result.aborted).toBe(true)
    expect(spawned?.kills).toEqual(['SIGKILL'])
  })

  it('never spawns an already-aborted call', async () => {
    const mock = installSpawn(child => child.finish(0))
    const controller = new AbortController()
    controller.abort()
    const result = await runBoardwise({ argv: ['doctor'], timeoutMs: 60_000, signal: controller.signal }, cli)
    expect(result.aborted).toBe(true)
    expect(mock).not.toHaveBeenCalled()
  })

  it('reports a child that cannot be started as a CLI error', async () => {
    installSpawn(child => child.failToStart(new Error('spawn ENOENT')))
    await expect(runBoardwise({ argv: ['doctor'], timeoutMs: 5_000 }, cli)).rejects.toThrow(
      /cannot run "C:\/tools\/boardwise\.exe doctor": spawn ENOENT/,
    )
  })
})

describe('stream hygiene', () => {
  it('redacts token-shaped values from stdout and stderr', async () => {
    const cli = { command: 'boardwise', prefix: [] as string[], via: 'path' as const }
    installSpawn(child => {
      child.out('token=abc123def456\n{"apiKey": "sk-live-999"}\nAuthorization: Bearer eyJhbGciOi.jwt.payload\n')
      child.err('secret: hunter2\n')
      child.finish(0)
    })
    const result = await runBoardwise({ argv: ['bridge', 'status'], timeoutMs: 5_000 }, cli)
    expect(result.stdout).not.toContain('abc123def456')
    expect(result.stdout).not.toContain('sk-live-999')
    expect(result.stdout).not.toContain('eyJhbGciOi')
    expect(result.stdout).toContain('Bearer ***')
    expect(result.stderr).toContain('secret: ***')
  })

  it('redactSecrets leaves ordinary output alone', () => {
    const text = 'boardwise doctor: 4/8 项通过\n  paired connector: b8b4a348\n'
    expect(redactSecrets(text)).toBe(text)
  })
})
