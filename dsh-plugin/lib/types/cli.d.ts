/**
 * Finding the local boardwise CLI, and the spawn wrapper around it.
 *
 * Task 045 §1: this plugin is a thin adapter. Everything that judges a design —
 * the parser, the rule engine, the report — stays in the Python CLI. This file
 * only resolves which CLI to run, runs it, and bounds what comes back: a
 * deadline, head+tail truncation of stdout, exit-code passthrough, and a scrub
 * of anything token-shaped (the daemon token must never reach a log or a
 * model).
 */
/** stdout keeps this many bytes from the start of the stream. */
export declare const STDOUT_HEAD_BYTES: number;
/** …and this many from the end; the two halves are the ">32KB head+tail" cap. */
export declare const STDOUT_TAIL_BYTES: number;
/** The cap the two halves add up to (task 045 §2). */
export declare const STDOUT_LIMIT_BYTES: number;
/** stderr is diagnostic only, so it gets a smaller budget. */
export declare const STDERR_HEAD_BYTES: number;
export declare const STDERR_TAIL_BYTES: number;
/** The cap the two halves add up to. */
export declare const STDERR_LIMIT_BYTES: number;
/** mkdtemp prefix for the report directory this plugin creates. */
export declare const OUT_DIR_PREFIX = "boardwise-dsh-";
/** How the CLI was located. */
export type CliSource = 'env' | 'path' | 'python';
/** One resolved invocation: the executable plus the arguments that name the CLI itself. */
export interface BoardwiseCli {
    /** Executable to spawn. */
    readonly command: string;
    /** Arguments that select the CLI (`-m boardwise.cli` for the Python fallback). */
    readonly prefix: readonly string[];
    /** Which of the three lookups won. */
    readonly via: CliSource;
}
/** Raised when the CLI cannot be found, or cannot be started once found. */
export declare class BoardwiseCliError extends Error {
    constructor(message: string);
}
/**
 * `BOARDWISE_EXE` → PATH `boardwise` → PATH `python`/`py` with `-m boardwise.cli`.
 *
 * A `BOARDWISE_EXE` that points nowhere is an error rather than a silent fall
 * through: a wrong path must be loud, never quietly replaced by a different
 * boardwise (that is the R3 discipline in the reverse direction).
 *
 * @param env - environment to read (defaults to `process.env`).
 * @param platform - platform whose launcher names and PATH separator apply.
 * @returns the resolved command, its CLI-selecting prefix, and how it was found.
 */
export declare function resolveCli(env?: NodeJS.ProcessEnv, platform?: NodeJS.Platform): BoardwiseCli;
/** One CLI call: the arguments after the prefix, a deadline, and the caller's cancellation. */
export interface BoardwiseRun {
    /** Arguments after the resolved prefix, e.g. `['checkup', '--file', 'x.epro2']`. */
    readonly argv: readonly string[];
    /** Deadline in milliseconds; the child is killed when it passes. */
    readonly timeoutMs: number;
    /** Caller cancellation (dsh enforces `timeoutMs` through this signal). */
    readonly signal?: AbortSignal | undefined;
}
/** What one finished CLI call looks like. */
export interface CliResult {
    readonly cli: BoardwiseCli;
    /** The command as it was spawned, for the model to see. */
    readonly commandLine: string;
    /** Process exit code, or `null` when the child was killed before exiting. */
    readonly code: number | null;
    /** Termination signal, when the child died from one. */
    readonly signal: NodeJS.Signals | null;
    /** stdout, head+tail truncated at {@link STDOUT_LIMIT_BYTES}. */
    readonly stdout: string;
    /** stderr, truncated the same way with a smaller budget. */
    readonly stderr: string;
    /** stdout bytes produced in total, before truncation. */
    readonly stdoutBytes: number;
    /** stderr bytes produced in total, before truncation. */
    readonly stderrBytes: number;
    /** Whether **stdout** lost bytes between head and tail. */
    readonly stdoutTruncated: boolean;
    /** Whether **stderr** lost bytes between head and tail. */
    readonly stderrTruncated: boolean;
    /** Whether either stream lost bytes between head and tail. */
    readonly truncated: boolean;
    /** True when the deadline passed and the child was killed. */
    readonly timedOut: boolean;
    /** True when the caller's signal aborted the call. */
    readonly aborted: boolean;
}
/**
 * Run the boardwise CLI once.
 *
 * @param run - arguments, deadline and cancellation signal.
 * @param cli - resolved invocation; resolved from the environment when omitted.
 * @returns exit code, stdout/stderr (truncated) and how the run ended.
 * @throws BoardwiseCliError when the child cannot be started (missing executable, EACCES).
 */
export declare function runBoardwise(run: BoardwiseRun, cli?: BoardwiseCli): Promise<CliResult>;
/**
 * Scrub anything token-shaped out of CLI output. The bridge's daemon token must
 * never appear in a log or a model-facing result (task 045 §2).
 *
 * @param text - raw stream text.
 * @returns the text with credential values replaced by `***`.
 */
export declare function redactSecrets(text: string): string;
/** The spawned command, quoted the way a shell would need it. */
export declare function formatCommandLine(command: string, argv: readonly string[]): string;
