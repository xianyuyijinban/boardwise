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
import { readFile, stat } from 'node:fs/promises';
import { STDERR_HEAD_BYTES, STDERR_TAIL_BYTES, STDOUT_HEAD_BYTES, STDOUT_TAIL_BYTES, runBoardwise, } from './cli.js';
/** How much of a killed run's stdout rides along in the error. */
const FAILURE_TAIL_CHARS = 2000;
/** The output contract every text tool shares: one text block. */
export const TEXT_OUTPUT = {
    schema: { type: 'string' },
    render: (_args, value) => [{ type: 'text', text: value }],
};
/**
 * 537D1b2: the output contract of a structured read — a canonical JSON object,
 * rendered as the whole pretty-printed document. `render` never sees a byte
 * cap: the value was parsed from a CLI file, not from stdout.
 */
export const STRUCTURED_OUTPUT = {
    schema: { type: 'object', additionalProperties: true },
    render: (_args, value) => [
        { type: 'text', text: JSON.stringify(value, null, 2) },
    ],
};
/**
 * Run the CLI and format the outcome for the model.
 *
 * A non-zero exit is a **result**, not a failure (checkup and doctor report
 * through it). Only two things throw: a run that was killed before it answered
 * (deadline or cancellation), and a child the OS refused to start.
 */
export async function executeCli(tool, argv, timeoutMs, exec, artifacts = []) {
    const result = await runBoardwise({ argv, timeoutMs, signal: exec.signal });
    if (result.timedOut || result.aborted) {
        const how = result.timedOut ? `did not finish within ${timeoutMs}ms` : 'was cancelled';
        throw new Error(`${tool}: the boardwise CLI ${how} and was killed, so its output is incomplete. ` +
            `command: ${result.commandLine}. Last stdout: ${tailOf(result.stdout) || '(none)'}`);
    }
    const notes = await Promise.all(artifacts.map(async (artifact) => ({
        ...artifact,
        exists: await isFile(artifact.path),
    })));
    return formatOutcome(tool, result, notes);
}
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
export async function runStructuredCli(tool, argv, timeoutMs, exec, jsonPath) {
    const result = await runBoardwise({ argv, timeoutMs, signal: exec.signal });
    if (result.timedOut || result.aborted) {
        const how = result.timedOut ? `did not finish within ${timeoutMs}ms` : 'was cancelled';
        throw new Error(`${tool}: the boardwise CLI ${how} and was killed, so no structured result exists. ` +
            `command: ${result.commandLine}. Last stdout: ${tailOf(result.stdout) || '(none)'}`);
    }
    if (result.code !== 0) {
        const code = result.code === null ? 'none (killed)' : String(result.code);
        throw new Error(`${tool}: the boardwise CLI did not succeed (exit ${code}); no structured result may be read from a ` +
            'failed run, so no stale or partial JSON is returned.\n' +
            formatOutcome(tool, result, []));
    }
    let raw;
    try {
        raw = await readFile(jsonPath, 'utf8');
    }
    catch (error) {
        throw new Error(`${tool}: exit 0 but the CLI did not write the JSON file it was told to write (${jsonPath}): ` +
            `${error.message}. The truncated stdout is not a fallback.\n` +
            formatOutcome(tool, result, []));
    }
    return parseJsonObject(tool, jsonPath, raw);
}
/** Parse a complete JSON document whose root must be an object. */
function parseJsonObject(tool, jsonPath, raw) {
    let parsed;
    try {
        parsed = JSON.parse(raw);
    }
    catch (error) {
        throw new Error(`${tool}: the --json file ${jsonPath} is not valid JSON (${error.message}); ` +
            'refusing to return a half-written result.');
    }
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error(`${tool}: the --json file ${jsonPath} must contain a JSON object, got ${describeValue(parsed)}; ` +
            'refusing to return a non-object result.');
    }
    return parsed;
}
/** A short, log-safe name for an unexpected JSON value. */
export function describeValue(value) {
    if (value === undefined)
        return 'undefined';
    const encoded = JSON.stringify(value);
    return encoded === undefined ? String(value) : encoded;
}
/** A required `out` directory, refused before anything is spawned. */
export function requireOut(tool, out) {
    if (out === '') {
        throw new Error(`${tool}: out is required (the checkup --out directory holding report.json)`);
    }
    return out;
}
/** A parameter that arrived as a non-empty, trimmed string, else `''`. */
export function text(value) {
    return typeof value === 'string' ? value.trim() : '';
}
export function formatOutcome(tool, result, artifacts) {
    const lines = [
        `${tool}: exit ${result.code === null ? 'none (killed)' : result.code} (cli: ${result.cli.via})`,
        `command: ${result.commandLine}`,
    ];
    if (artifacts.length > 0) {
        lines.push('artifacts:');
        for (const artifact of artifacts) {
            lines.push(`  ${artifact.label}: ${artifact.path} [${artifact.exists ? 'present' : 'MISSING'}]`);
        }
    }
    lines.push('--- stdout ---', result.stdout.trimEnd() || '(empty)');
    if (result.stdoutTruncated) {
        lines.push(`(stdout truncated: ${result.stdoutBytes} bytes total, head ${STDOUT_HEAD_BYTES} + tail ${STDOUT_TAIL_BYTES} kept)`);
    }
    if (result.stderr.trim() !== '')
        lines.push('--- stderr ---', result.stderr.trimEnd());
    // S4#2: the marker names the stream it belongs to. It used to be written for
    // `stdout || stderr`, so a run whose stderr was the stream that got cut was
    // reported as "stdout truncated" — and a reader looking for what was dropped
    // would go to the wrong block, or conclude stdout had lost bytes it still had.
    if (result.stderrTruncated) {
        lines.push(`(stderr truncated: ${result.stderrBytes} bytes total, head ${STDERR_HEAD_BYTES} + tail ${STDERR_TAIL_BYTES} kept)`);
    }
    const hint = pythonHint(result);
    if (hint !== null)
        lines.push(`hint: ${hint}`);
    return lines.join('\n');
}
/**
 * The Python fallback can land on an interpreter that has no boardwise
 * installed; without this line the raw ModuleNotFoundError is the only clue.
 */
function pythonHint(result) {
    if (result.cli.via !== 'python' || result.code === 0)
        return null;
    if (!/No module named ['"]?boardwise/i.test(result.stderr))
        return null;
    return (`the interpreter found on PATH (${result.cli.command}) has no boardwise installed: ` +
        'set BOARDWISE_EXE to one that has it, e.g. <boardwise repo>/.venv/Scripts/python.exe');
}
/** Last {@link FAILURE_TAIL_CHARS} characters of a partial run. */
function tailOf(value) {
    const trimmed = value.trim();
    return trimmed.length <= FAILURE_TAIL_CHARS ? trimmed : `...${trimmed.slice(-FAILURE_TAIL_CHARS)}`;
}
async function isFile(path) {
    try {
        return (await stat(path)).isFile();
    }
    catch {
        return false;
    }
}
