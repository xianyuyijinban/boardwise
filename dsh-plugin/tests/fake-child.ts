/**
 * Fake `spawn` plumbing for the CLI tests. `node:child_process` is mocked in the
 * spec files, so `installSpawn` decides what every spawn call returns: a
 * {@link FakeChild} whose streams the test drives by hand.
 */
import { spawn, type ChildProcess } from 'node:child_process'
import { EventEmitter } from 'node:events'
import { vi, type Mock } from 'vitest'

/** Stand-in for a spawned child: the events the wrapper listens to, and `kill`. */
export class FakeChild extends EventEmitter {
  /** stdout, as a plain emitter — the wrapper only adds a `data` listener. */
  readonly stdout = new EventEmitter()
  /** stderr, same. */
  readonly stderr = new EventEmitter()
  /** Signals `kill` was called with, in order. */
  readonly kills: string[] = []

  /** Write to stdout. */
  out(chunk: string | Buffer): void {
    this.stdout.emit('data', Buffer.from(chunk))
  }

  /** Write to stderr. */
  err(chunk: string | Buffer): void {
    this.stderr.emit('data', Buffer.from(chunk))
  }

  /** End the run normally. */
  finish(code: number | null, signal: NodeJS.Signals | null = null): void {
    this.emit('close', code, signal)
  }

  /** Fail to start (ENOENT and friends). */
  failToStart(error: Error): void {
    this.emit('error', error)
  }

  /**
   * Behave like a killed process and end the run — a real child closes once the
   * signal lands, so the wrapper's promise must settle here too.
   */
  kill(signal?: NodeJS.Signals): boolean {
    this.kills.push(signal ?? 'SIGTERM')
    this.emit('close', null, signal ?? 'SIGTERM')
    return true
  }
}

/** What each spawned child does, once the wrapper has attached its listeners. */
export type ChildBehavior = (child: FakeChild, command: string, args: string[]) => void

/**
 * Make the mocked `spawn` hand out {@link FakeChild} instances (asynchronously
 * driven). A behavior that throws (typically a failed assertion about the
 * spawned arguments) ends the child at once, so the run fails fast instead of
 * waiting for the wrapper's deadline.
 */
export function installSpawn(behavior: ChildBehavior): Mock {
  const mock = vi.mocked(spawn) as unknown as Mock
  mock.mockReset()
  mock.mockImplementation((command: string, args?: readonly string[]) => {
    const child = new FakeChild()
    setImmediate(() => {
      try {
        behavior(child, command, [...(args ?? [])])
      } catch (error) {
        child.failToStart(error instanceof Error ? error : new Error(String(error)))
      }
    })
    return child as unknown as ChildProcess
  })
  return mock
}

/** The `[command, ...args]` of the nth (default: last) spawn call. */
export function spawnedCommand(mock: Mock, index = -1): string[] {
  const calls = mock.mock.calls as unknown as [string, readonly string[]][]
  const call = calls.at(index)
  if (call === undefined) throw new Error(`spawn was called ${calls.length} times`)
  return [call[0], ...call[1]]
}
