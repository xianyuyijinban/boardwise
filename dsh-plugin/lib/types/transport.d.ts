/**
 * The transport half of the boardwise tools: how a CLI run is turned into a
 * model-facing answer, and how a structured answer is read back from a **file**
 * instead of from stdout.
 *
 * Task 045 §1 keeps every judgement in the Python CLI; this module only owns the
 * mechanics two tool families share (537D3a moved it out of `index.ts` so the
 * delivery gate can reuse it without duplicating the truncation and exit-code
 * discipline):
 *
 * - {@link executeCli} formats a text answer whose exit code is itself a result;
 * - {@link runStructuredCli} refuses stdout outright — dsh truncates it at
 *   32 KiB — and reads the whole `--json` / receipt file only after exit 0.
 */
import { type CliResult } from './cli.ts';
import type { InferValue } from '@deepseek-ai/dsh-tools';
/** The part of an execution this module uses: caller cancellation. */
export interface Cancellable {
    readonly signal?: AbortSignal | undefined;
}
/** One file the CLI was supposed to write. */
export interface ArtifactNote {
    readonly label: string;
    readonly path: string;
}
/** The output contract every text tool shares: one text block. */
export declare const TEXT_OUTPUT: {
    schema: {
        type: 'string';
    };
    render: (_args: unknown, value: string) => {
        type: 'text';
        text: string;
    }[];
};
/**
 * 537D1b2: the output contract of a structured read — a canonical JSON object,
 * rendered as the whole pretty-printed document. `render` never sees a byte
 * cap: the value was parsed from a CLI file, not from stdout.
 */
export declare const STRUCTURED_OUTPUT: {
    schema: {
        type: 'object';
        additionalProperties: boolean;
    };
    render: (_args: unknown, value: unknown) => {
        type: 'text';
        text: string;
    }[];
};
/** The object shape {@link STRUCTURED_OUTPUT} declares, inferred from the schema. */
export type StructuredResult = InferValue<(typeof STRUCTURED_OUTPUT)['schema']>;
/**
 * Run the CLI and format the outcome for the model.
 *
 * A non-zero exit is a **result**, not a failure (checkup and doctor report
 * through it). Only two things throw: a run that was killed before it answered
 * (deadline or cancellation), and a child the OS refused to start.
 */
export declare function executeCli(tool: string, argv: readonly string[], timeoutMs: number, exec: Cancellable, artifacts?: readonly ArtifactNote[]): Promise<string>;
/**
 * 537D1b2: run a CLI command whose answer is a **file**, and read the whole file.
 *
 * dsh truncates stdout at 32 KiB, so a structured answer can never come from
 * there: `--json PATH` (or a receipt the CLI signs in `--out`) is read in full,
 * and only a successful run plus a complete, parsed object is an answer. A
 * non-zero exit is loud and carries {@link formatOutcome}; a missing file,
 * broken JSON or non-object root is equally loud — there is no stale, partial
 * or stdout fallback path.
 */
export declare function runStructuredCli(tool: string, argv: readonly string[], timeoutMs: number, exec: Cancellable, jsonPath: string): Promise<StructuredResult>;
/** A short, log-safe name for an unexpected JSON value. */
export declare function describeValue(value: unknown): string;
/** A required `out` directory, refused before anything is spawned. */
export declare function requireOut(tool: string, out: string): string;
/** A parameter that arrived as a non-empty, trimmed string, else `''`. */
export declare function text(value: unknown): string;
export declare function formatOutcome(tool: string, result: CliResult, artifacts: readonly {
    label: string;
    path: string;
    exists: boolean;
}[]): string;
