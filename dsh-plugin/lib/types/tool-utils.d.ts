/** Shared, mechanical checks for the line-owned boardwise tool registrations. */
import { type StructuredResult } from './transport.ts';
/** Create the plugin's own temp directory for one `--json` transport file. */
export declare function transportDir(tool: string): Promise<string>;
/** A repeated flag's values: strings only, trimmed, empty entries ignored. */
export declare function stringList(value: unknown): string[];
/** Transport check: one envelope field must be exactly the expected string. */
export declare function requireField(tool: string, value: StructuredResult, field: string, expected: string): void;
/** Transport check: one envelope field must be an object. */
export declare function requireObjectField(tool: string, value: StructuredResult, field: string): void;
/** Transport check: one envelope field must be an array. */
export declare function requireArrayField(tool: string, value: StructuredResult, field: string): void;
/** Transport check: one envelope field must be present (any JSON value). */
export declare function requirePresentField(tool: string, value: StructuredResult, field: string): void;
/** Require a named input file without interpreting its contents in TypeScript. */
export declare function requireExistingInput(tool: string, field: string, value: string, description: string): string;
/** Refuse a path boardwise could only fail on, before anything is spawned. */
export declare function requireExistingFile(tool: string, file: string): string;
/**
 * Params are passed to the CLI verbatim; only the JSON syntax is checked here,
 * so a typo comes back as an argument error instead of a daemon round-trip.
 */
export declare function requireJsonObject(tool: string, params: string): string;
export declare function ensureDirectory(tool: string, dir: string): Promise<void>;
