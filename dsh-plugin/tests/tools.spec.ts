import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@deepseek-ai/dsh-tools', () => ({ defineTool: (options: unknown) => options }))
vi.mock('node:child_process', () => ({ spawn: vi.fn() }))

import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apply } from '../src/index.ts'
import { installSpawn, spawnedCommand } from './fake-child.ts'

/** One tool call, as the registry would make it. */
interface Tool {
  name: string
  execute: (args: Record<string, unknown>, exec: { signal: AbortSignal }) => Promise<string>
}

const exec = { signal: new AbortController().signal }
const made: string[] = []
const saved = { BOARDWISE_EXE: process.env['BOARDWISE_EXE'], PATH: process.env['PATH'] }

/** A temp directory the test removes afterwards. */
function tempDir(prefix = 'boardwise-tools-'): string {
  const dir = mkdtempSync(join(tmpdir(), prefix))
  made.push(dir)
  return dir
}

/** A real, existing file — the pre-flight check only asks whether it is there. */
function fixture(name = 'x.epro2'): string {
  const file = join(tempDir('boardwise-fixture-'), name)
  writeFileSync(file, '')
  return file
}

/** Collect the tools `apply` registers, as `defineTool` would pass them on. */
function registered(): Map<string, Tool> {
  const tools = new Map<string, Tool>()
  apply({ tools: { register: (definition: unknown) => {
    const tool = definition as Tool
    tools.set(tool.name, tool)
    return () => {}
  } } } as never)
  return tools
}

/** Call one tool by name, failing loudly when the name is wrong. */
async function call(name: string, args: Record<string, unknown>): Promise<string> {
  const tool = registered().get(name)
  if (tool === undefined) throw new Error(`no such tool: ${name}`)
  return await tool.execute(args, exec)
}

/** The value of `--flag` in a spawned command. */
function flagValue(argv: readonly string[], flag: string): string | undefined {
  const index = argv.indexOf(flag)
  return index === -1 ? undefined : argv[index + 1]
}

/** Restore one environment variable, unsetting it when it was not there. */
function restoreEnv(key: string, value: string | undefined): void {
  if (value === undefined) delete process.env[key]
  else process.env[key] = value
}

beforeEach(() => {
  // A resolvable CLI, so the tests never depend on this machine's PATH.
  const exe = join(tempDir('boardwise-bin-'), 'boardwise.exe')
  writeFileSync(exe, '')
  process.env['BOARDWISE_EXE'] = exe
})

afterEach(() => {
  for (const dir of made.splice(0)) rmSync(dir, { recursive: true, force: true })
  restoreEnv('BOARDWISE_EXE', saved.BOARDWISE_EXE)
  restoreEnv('PATH', saved.PATH)
})

describe('boardwise_checkup: argument assembly', () => {
  it('passes --file and a fresh temp --out, then reports the artifacts it wrote', async () => {
    const file = fixture('ch340_golden.epro2')
    let outExisted = false
    const mock = installSpawn((child, _command, args) => {
      const out = flagValue(args, '--out') as string
      outExisted = existsSync(out)
      for (const name of ['report.json', 'report.md', 'architecture.md']) writeFileSync(join(out, name), '{}')
      child.out('findings: 0 ERROR, 1 WARN\n')
      child.finish(0)
    })

    const text = await call('boardwise_checkup', { file })

    const argv = spawnedCommand(mock)
    expect(argv.slice(1, 3)).toEqual(['checkup', '--file'])
    expect(argv[3]).toBe(file)
    const out = flagValue(argv, '--out') as string
    expect(out.startsWith(join(tmpdir(), 'boardwise-dsh-'))).toBe(true)
    expect(outExisted).toBe(true)
    expect(text).toContain('boardwise_checkup: exit 0')
    expect(text).toContain(`report.json: ${join(out, 'report.json')} [present]`)
    expect(text).toContain(`architecture.md: ${join(out, 'architecture.md')} [present]`)
    expect(text).toContain('findings: 0 ERROR, 1 WARN')
  })

  it('uses the given --out and creates it', async () => {
    const file = fixture()
    const out = join(tempDir(), 'nested', 'reports')
    const mock = installSpawn(child => {
      writeFileSync(join(out, 'report.json'), '{}')
      child.finish(0)
    })

    const text = await call('boardwise_checkup', { file, out })

    expect(flagValue(spawnedCommand(mock), '--out')).toBe(out)
    expect(existsSync(out)).toBe(true)
    expect(text).toContain(`report.json: ${join(out, 'report.json')} [present]`)
  })

  it('routes the live path by --project and reports artifacts that are not there', async () => {
    const mock = installSpawn(child => {
      child.out('model: 17 components\n')
      child.finish(3)
    })

    const text = await call('boardwise_checkup', { project: 'test' })

    const argv = spawnedCommand(mock)
    expect(argv.slice(1, 3)).toEqual(['checkup', '--project'])
    expect(argv[3]).toBe('test')
    expect(text).toContain('boardwise_checkup: exit 3')
    expect(text).toContain('report.json:')
    expect(text).toContain('[MISSING]')
  })

  it('spells the same choice as --instance when that is what was given', async () => {
    const mock = installSpawn(child => child.finish(3))
    await call('boardwise_checkup', { instance: 'inst-015813234-aw2317s0' })
    const argv = spawnedCommand(mock)
    expect(argv.slice(1, 3)).toEqual(['checkup', '--instance'])
    expect(argv[3]).toBe('inst-015813234-aw2317s0')
  })

  it('refuses to guess when no design is named', async () => {
    const mock = installSpawn(child => child.finish(0))
    await expect(call('boardwise_checkup', {})).rejects.toThrow(/name exactly one design/)
    expect(mock).not.toHaveBeenCalled()
  })

  it('refuses two designs at once', async () => {
    const mock = installSpawn(child => child.finish(0))
    await expect(call('boardwise_checkup', { file: fixture(), project: 'test' })).rejects.toThrow(
      /name exactly one design/,
    )
    expect(mock).not.toHaveBeenCalled()
  })

  it('refuses a file that is not there, before spawning anything', async () => {
    const mock = installSpawn(child => child.finish(0))
    await expect(call('boardwise_checkup', { file: join(tempDir(), 'nope.epro2') })).rejects.toThrow(
      /file not found/,
    )
    expect(mock).not.toHaveBeenCalled()
  })
})

describe('boardwise_arch: argument assembly', () => {
  it('passes the file through and lets the markdown come back on stdout', async () => {
    const file = fixture()
    const mock = installSpawn(child => {
      child.out('## 1. power tree\n- +5V: TODO\n')
      child.finish(0)
    })

    const text = await call('boardwise_arch', { file })

    expect(spawnedCommand(mock)).toEqual([process.env['BOARDWISE_EXE'] as string, 'arch', file])
    expect(text).toContain('boardwise_arch: exit 0')
    expect(text).toContain('TODO')
  })

  it('writes to --out when asked and reports the file', async () => {
    const file = fixture()
    const out = join(tempDir(), 'arch.md')
    const mock = installSpawn(child => {
      writeFileSync(out, '# arch')
      child.out(`architecture: ${out}\n`)
      child.finish(0)
    })

    const text = await call('boardwise_arch', { file, out })

    expect(spawnedCommand(mock)).toEqual([process.env['BOARDWISE_EXE'] as string, 'arch', file, '--out', out])
    expect(text).toContain(`architecture: ${out} [present]`)
  })

  it('requires the file argument', async () => {
    await expect(call('boardwise_arch', {})).rejects.toThrow(/file is required/)
  })
})

describe('boardwise_doctor: argument assembly', () => {
  it('passes both routing hints through when given', async () => {
    const mock = installSpawn(child => {
      child.out('  PASS daemon reachable (ping)\n')
      child.finish(1)
    })

    const text = await call('boardwise_doctor', { project: 'test', instance: 'inst-1' })

    expect(spawnedCommand(mock)).toEqual([
      process.env['BOARDWISE_EXE'] as string,
      'doctor',
      '--project',
      'test',
      '--instance',
      'inst-1',
    ])
    expect(text).toContain('boardwise_doctor: exit 1')
  })

  it('adds no flag when nothing is named', async () => {
    const mock = installSpawn(child => child.finish(0))
    await call('boardwise_doctor', {})
    expect(spawnedCommand(mock)).toEqual([process.env['BOARDWISE_EXE'] as string, 'doctor'])
  })
})

describe('boardwise_bridge: argument assembly', () => {
  it('passes action, params and the window hint through verbatim', async () => {
    const mock = installSpawn(child => {
      child.out('{"ok":true}')
      child.finish(0)
    })

    const text = await call('boardwise_bridge', {
      action: 'doc.list',
      params: '{"page":"sch"}',
      project: 'test',
    })

    expect(spawnedCommand(mock)).toEqual([
      process.env['BOARDWISE_EXE'] as string,
      'bridge',
      'call',
      '--action',
      'doc.list',
      '--params',
      '{"page":"sch"}',
      '--project',
      'test',
    ])
    expect(text).toContain('{"ok":true}')
  })

  it('refuses params that are not a JSON object', async () => {
    const mock = installSpawn(child => child.finish(0))
    await expect(call('boardwise_bridge', { action: 'sys.probe', params: '{oops}' })).rejects.toThrow(
      /params is not valid JSON/,
    )
    await expect(call('boardwise_bridge', { action: 'sys.probe', params: '[1,2]' })).rejects.toThrow(
      /params must be a JSON object/,
    )
    await expect(call('boardwise_bridge', { action: 'sys.probe' })).rejects.toThrow(/params is required/)
    expect(mock).not.toHaveBeenCalled()
  })
})

describe('failure surfaces', () => {
  it('refuses before spawning when no CLI can be found', async () => {
    delete process.env['BOARDWISE_EXE']
    process.env['PATH'] = tempDir('boardwise-empty-')
    await expect(call('boardwise_doctor', {})).rejects.toThrow(/boardwise CLI not found[\s\S]*BOARDWISE_EXE/)
  })

  it('hints at BOARDWISE_EXE when a PATH interpreter lacks boardwise', async () => {
    delete process.env['BOARDWISE_EXE']
    const bin = tempDir('boardwise-py-')
    writeFileSync(join(bin, 'python.exe'), '')
    process.env['PATH'] = bin
    installSpawn(child => {
      child.err("ModuleNotFoundError: No module named 'boardwise'\n")
      child.finish(1)
    })

    const text = await call('boardwise_doctor', {})

    expect(text).toContain('boardwise_doctor: exit 1 (cli: python)')
    expect(text).toContain('hint: the interpreter found on PATH')
  })

  it('turns a killed run into an error instead of a partial answer', async () => {
    installSpawn(child => {
      child.out('starting review...\n')
      // Never closes: the caller's cancellation ends it instead.
    })
    const controller = new AbortController()
    const tool = registered().get('boardwise_doctor') as Tool
    const pending = tool.execute({}, { signal: controller.signal })
    await new Promise(resolve => setTimeout(resolve, 25))
    controller.abort()

    await expect(pending).rejects.toThrow(/was cancelled and was killed[\s\S]*starting review/)
  })

  it('reports a child the OS refused to start', async () => {
    installSpawn(child => child.failToStart(new Error('spawn EACCES')))
    await expect(call('boardwise_doctor', {})).rejects.toThrow(/cannot run .*boardwise\.exe doctor.*EACCES/)
  })
})

describe('output hygiene', () => {
  it('never prints a token-shaped value', async () => {
    installSpawn(child => {
      child.out('daemon token=deadbeefcafe\n')
      child.finish(0)
    })
    const text = await call('boardwise_doctor', {})
    expect(text).not.toContain('deadbeefcafe')
    expect(text).toContain('token=***')
  })

  it('marks a truncated report instead of silently cutting it', async () => {
    installSpawn(child => {
      child.out('x'.repeat(64 * 1024))
      child.finish(0)
    })
    const text = await call('boardwise_arch', { file: fixture() })
    expect(text).toContain('stdout truncated: 65536 bytes total')
    expect(text).toContain('bytes dropped')
  })
})
