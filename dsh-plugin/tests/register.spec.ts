import { describe, expect, it, vi } from 'vitest'

vi.mock('@deepseek-ai/dsh-tools', () => ({ defineTool: (options: unknown) => options }))

import { apply, inject, name } from '../src/index.ts'

/** One parameter as this plugin declares it, flattened to the fields we pin. */
interface CapturedParameter {
  type: string
  required?: true
  description?: string
  enum?: readonly string[]
  items?: {
    type: string
    additionalProperties?: boolean
    properties?: Record<string, CapturedParameter>
  }
}

/** The shape `defineTool` would have validated, as this plugin declares it. */
interface CapturedTool {
  name: string
  description: string
  parameters: Record<string, CapturedParameter>
  output: {
    schema: { type: string; [key: string]: unknown }
    render: (args: unknown, value: unknown) => unknown
  }
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

/** The four tools that answer with one formatted text block. */
const TEXT_TOOLS = [
  'boardwise_checkup',
  'boardwise_arch',
  'boardwise_doctor',
  'boardwise_bridge',
] as const

/** The two tools that answer with a canonical JSON object (537D1b2 / 537D3a). */
const STRUCTURED_TOOLS = [
  'boardwise_review_read',
  'boardwise_triage_batch',
  'boardwise_review_finalize',
  'boardwise_draw_compile',
  'boardwise_draw_lint',
] as const

describe('boardwise-dsh: plugin registration contract', () => {
  it('exports the cordis plugin contract', () => {
    expect(name).toBe('boardwise-dsh')
    expect(inject).toContain('tools')
    // 537D3a: a finalize receipt has nowhere to be recorded without it.
    expect(inject).toContain('sessionProjections')
    // 537D3b: the present gate resolves and re-hashes through these services.
    expect(inject).toContain('fs')
    expect(inject).toContain('workingDirectory')
    expect(typeof apply).toBe('function')
  })

  it('keeps the eight old tools in order, then appends offline draw compile/lint', () => {
    expect([...registered().keys()]).toEqual([
      'boardwise_checkup',
      'boardwise_arch',
      'boardwise_doctor',
      'boardwise_bridge',
      'boardwise_review_read',
      'boardwise_review_evidence',
      'boardwise_triage_batch',
      'boardwise_review_finalize',
      'boardwise_draw_compile',
      'boardwise_draw_lint',
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

  it('renders one text block per call for the text tools only', () => {
    for (const name of TEXT_TOOLS) {
      const tool = registered().get(name) as CapturedTool
      expect(tool.output.schema.type).toBe('string')
      expect(tool.output.render({}, 'body')).toEqual([{ type: 'text', text: 'body' }])
    }
  })

  it('declares an object output for the structured tools', () => {
    for (const name of STRUCTURED_TOOLS) {
      const tool = registered().get(name) as CapturedTool
      expect(tool.output.schema.type).toBe('object')
      const value = { schema: 'x', payload: { answer: 42 } }
      expect(tool.output.render({}, value)).toEqual([
        { type: 'text', text: JSON.stringify(value, null, 2) },
      ])
    }
  })

  it('declares review_read over the six transport sections', () => {
    const tool = registered().get('boardwise_review_read') as CapturedTool
    expect(Object.keys(tool.parameters)).toEqual(['out', 'section'])
    expect(tool.parameters['out']?.required).toBe(true)
    expect(tool.parameters['section']?.required).toBe(true)
    expect(tool.parameters['section']?.enum).toEqual([
      'verdict',
      'findings',
      'crossView',
      'coverage',
      'artifacts',
      'netlist',
    ])
    // The read is cheap next to a live capture, but it still gets a budget.
    expect(tool.timeoutMs).toBe(120_000)
  })

  it('declares review_evidence with repeatable page/pcb and a ten-minute budget', () => {
    const tool = registered().get('boardwise_review_evidence') as CapturedTool
    expect(Object.keys(tool.parameters)).toEqual(['out', 'project', 'instance', 'page', 'pcb'])
    expect(tool.parameters['out']?.required).toBe(true)
    expect(tool.parameters['project']?.required).toBeUndefined()
    expect(tool.parameters['instance']?.required).toBeUndefined()
    expect(tool.parameters['page']?.type).toBe('array')
    expect(tool.parameters['pcb']?.type).toBe('array')
    // Evidence is still a formatted text result: exit 0/1/2/3 are collection
    // answers, so it is not one of the structured tools.
    expect(tool.output.schema.type).toBe('string')
    expect(tool.timeoutMs).toBe(600_000)
  })

  it('declares triage entries as exactly key/verdict/reason strings, with no TS verdict enum', () => {
    const tool = registered().get('boardwise_triage_batch') as CapturedTool
    expect(Object.keys(tool.parameters)).toEqual(['out', 'entries'])
    expect(tool.parameters['out']?.required).toBe(true)
    expect(tool.parameters['entries']?.required).toBe(true)
    expect(tool.parameters['entries']?.type).toBe('array')

    const item = tool.parameters['entries']?.items as NonNullable<CapturedParameter['items']>
    expect(item.type).toBe('object')
    expect(item.additionalProperties).toBe(false)
    expect(Object.keys(item.properties ?? {})).toEqual(['key', 'verdict', 'reason'])
    for (const field of ['key', 'verdict', 'reason'] as const) {
      expect(item.properties?.[field]?.type).toBe('string')
      expect(item.properties?.[field]?.required).toBe(true)
    }
    // needs-manual / admissibility / pending stay Python's judgement: the
    // plugin must not pin a TS enum here.
    expect(item.properties?.['verdict']?.enum).toBeUndefined()
    expect(tool.timeoutMs).toBe(120_000)
  })

  it('says the bridge tool is for read-only actions', () => {
    expect(registered().get('boardwise_bridge')?.description).toMatch(/read-only/)
  })

  it('declares review_finalize with only out, a two-minute budget and a delivery-not-board promise', () => {
    const tool = registered().get('boardwise_review_finalize') as CapturedTool
    expect(Object.keys(tool.parameters)).toEqual(['out'])
    expect(tool.parameters['out']?.required).toBe(true)
    expect(tool.parameters['out']?.type).toBe('string')
    expect(tool.timeoutMs).toBe(120_000)
    expect(tool.output.schema.type).toBe('object')
    // The receipt is a delivery statement; the board answer stays in the report.
    expect(tool.description).toMatch(/report\.conclusion/)
    expect(tool.description).toMatch(/not a board verdict/)
    expect(tool.description).toMatch(/plugin:boardwise-dsh\/review-finalized/)
  })

  it('declares only offline draw compile/lint, with no live-page or apply surface', () => {
    const tools = registered()
    const compile = tools.get('boardwise_draw_compile') as CapturedTool
    expect(Object.keys(compile.parameters)).toEqual([
      'circuit', 'presentation', 'profiles', 'pageBox', 'intent', 'out',
    ])
    for (const field of ['circuit', 'presentation', 'profiles']) {
      expect(compile.parameters[field]?.required).toBe(true)
    }
    expect(compile.timeoutMs).toBe(600_000)
    expect(compile.description).toMatch(/offline/)

    const lint = tools.get('boardwise_draw_lint') as CapturedTool
    expect(Object.keys(lint.parameters)).toEqual(['snapshot', 'render', 'bodies'])
    expect(lint.parameters['snapshot']?.required).toBe(true)
    expect(lint.parameters['render']?.required).toBe(true)
    expect(lint.parameters['page']).toBeUndefined()
    expect(lint.parameters['project']).toBeUndefined()
    expect(lint.parameters['instance']).toBeUndefined()
    expect(lint.timeoutMs).toBe(120_000)
    expect(lint.description).toMatch(/offline/)
    expect(tools.has('boardwise_draw_apply')).toBe(false)
  })
})
