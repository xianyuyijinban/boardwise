import { describe, expect, it, vi } from 'vitest'

vi.mock('@deepseek-ai/dsh-tools', () => ({ defineTool: (options: unknown) => options }))

import { apply, inject, name } from '../src/index.ts'

/** The shape `defineTool` would have validated, as this plugin declares it. */
interface CapturedTool {
  name: string
  description: string
  parameters: Record<string, { type: string; required?: true; description?: string }>
  output: { schema: { type: string }; render: (args: unknown, value: unknown) => unknown }
  timeoutMs?: number
}

/** Run `apply` against a fake registry and collect what was registered. */
function registered(): Map<string, CapturedTool> {
  const tools = new Map<string, CapturedTool>()
  const ctx = {
    tools: {
      register: (definition: unknown) => {
        const tool = definition as CapturedTool
        tools.set(tool.name, tool)
        return () => {}
      },
    },
  }
  apply(ctx as never)
  return tools
}

describe('boardwise-dsh: plugin registration contract', () => {
  it('exports the cordis plugin contract', () => {
    expect(name).toBe('boardwise-dsh')
    expect(inject).toContain('tools')
    expect(typeof apply).toBe('function')
  })

  it('registers exactly the four boardwise tools', () => {
    expect([...registered().keys()]).toEqual([
      'boardwise_checkup',
      'boardwise_arch',
      'boardwise_doctor',
      'boardwise_bridge',
    ])
  })

  it('declares the checkup surface', () => {
    const tool = registered().get('boardwise_checkup') as CapturedTool
    expect(Object.keys(tool.parameters)).toEqual(['file', 'project', 'instance', 'out'])
    expect(tool.timeoutMs).toBe(600_000)
    expect(tool.description).toMatch(/offline/)
  })

  it('requires file on arch and action/params on bridge', () => {
    const tools = registered()
    expect(tools.get('boardwise_arch')?.parameters['file']?.required).toBe(true)
    expect(tools.get('boardwise_arch')?.timeoutMs).toBe(120_000)
    expect(tools.get('boardwise_bridge')?.parameters['action']?.required).toBe(true)
    expect(tools.get('boardwise_bridge')?.parameters['params']?.required).toBe(true)
    expect(tools.get('boardwise_bridge')?.timeoutMs).toBe(120_000)
  })

  it('gives doctor only the two routing hints, with no required parameter', () => {
    const tool = registered().get('boardwise_doctor') as CapturedTool
    expect(Object.keys(tool.parameters)).toEqual(['project', 'instance'])
    expect(tool.timeoutMs).toBe(60_000)
  })

  it('renders one text block per call', () => {
    for (const tool of registered().values()) {
      expect(tool.output.schema.type).toBe('string')
      expect(tool.output.render({}, 'body')).toEqual([{ type: 'text', text: 'body' }])
    }
  })

  it('says the bridge tool is for read-only actions', () => {
    expect(registered().get('boardwise_bridge')?.description).toMatch(/read-only/)
  })
})
