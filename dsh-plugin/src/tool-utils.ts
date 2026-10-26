/** Shared, mechanical checks for the line-owned boardwise tool registrations. */

import { existsSync } from 'node:fs'
import { mkdir, mkdtemp } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describeValue, text, type StructuredResult } from './transport.ts'

/** mkdtemp prefix for the plugin's own transport files (`--json` targets). */
const TRANSPORT_DIR_PREFIX = 'boardwise-dsh-'

/** Create the plugin's own temp directory for one `--json` transport file. */
export async function transportDir(tool: string): Promise<string> {
  try {
    return await mkdtemp(join(tmpdir(), TRANSPORT_DIR_PREFIX))
  } catch (error) {
    throw new Error(`${tool}: cannot create a private temp directory: ${(error as Error).message}`)
  }
}

/** A repeated flag's values: strings only, trimmed, empty entries ignored. */
export function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map(item => text(item)).filter(item => item !== '')
}

/** Transport check: one envelope field must be exactly the expected string. */
export function requireField(
  tool: string,
  value: StructuredResult,
  field: string,
  expected: string,
): void {
  const actual = value[field]
  if (actual !== expected) {
    throw new Error(
      `${tool}: the --json result has ${field} ${describeValue(actual)}, not ${JSON.stringify(expected)}; ` +
      'the file is not the answer this call asked for.',
    )
  }
}

/** Transport check: one envelope field must be an object. */
export function requireObjectField(tool: string, value: StructuredResult, field: string): void {
  const actual = value[field]
  if (actual === null || typeof actual !== 'object' || Array.isArray(actual)) {
    throw new Error(
      `${tool}: the --json result has no \`${field}\` object (read ${describeValue(actual)}); ` +
      'refusing to report an envelope without it.',
    )
  }
}

/** Transport check: one envelope field must be an array. */
export function requireArrayField(tool: string, value: StructuredResult, field: string): void {
  const actual = value[field]
  if (!Array.isArray(actual)) {
    throw new Error(
      `${tool}: the --json result has no \`${field}\` array (read ${describeValue(actual)}); ` +
      'refusing to report an envelope without it.',
    )
  }
}

/** Transport check: one envelope field must be present (any JSON value). */
export function requirePresentField(tool: string, value: StructuredResult, field: string): void {
  if (!(field in value)) {
    throw new Error(`${tool}: the --json result has no \`${field}\` field; refusing to report a partial envelope.`)
  }
}

/** Require a named input file without interpreting its contents in TypeScript. */
export function requireExistingInput(
  tool: string,
  field: string,
  value: string,
  description: string,
): string {
  if (value === '') throw new Error(`${tool}: ${field} is required (${description})`)
  if (!existsSync(value)) {
    throw new Error(
      `${tool}: ${field} not found: ${value} ` +
      "(paths are read as given, relative to the plugin's working directory)",
    )
  }
  return value
}

/** Refuse a path boardwise could only fail on, before anything is spawned. */
export function requireExistingFile(tool: string, file: string): string {
  return requireExistingInput(tool, 'file', file, 'a .epro2 / .enet export to read')
}

/**
 * Params are passed to the CLI verbatim; only the JSON syntax is checked here,
 * so a typo comes back as an argument error instead of a daemon round-trip.
 */
export function requireJsonObject(tool: string, params: string): string {
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

export async function ensureDirectory(tool: string, dir: string): Promise<void> {
  try {
    await mkdir(dir, { recursive: true })
  } catch (error) {
    throw new Error(`${tool}: cannot create directory ${dir}: ${(error as Error).message}`)
  }
}
