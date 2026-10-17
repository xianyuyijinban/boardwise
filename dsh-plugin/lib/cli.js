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
import { spawn } from 'node:child_process';
import { existsSync, statSync } from 'node:fs';
import { basename, join } from 'node:path';
/** stdout keeps this many bytes from the start of the stream. */
export const STDOUT_HEAD_BYTES = 16 * 1024;
/** …and this many from the end; the two halves are the ">32KB head+tail" cap. */
export const STDOUT_TAIL_BYTES = 16 * 1024;
/** The cap the two halves add up to (task 045 §2). */
export const STDOUT_LIMIT_BYTES = STDOUT_HEAD_BYTES + STDOUT_TAIL_BYTES;
/** stderr is diagnostic only, so it gets a smaller budget. */
export const STDERR_HEAD_BYTES = 4 * 1024;
export const STDERR_TAIL_BYTES = 4 * 1024;
/** The cap the two halves add up to. */
export const STDERR_LIMIT_BYTES = STDERR_HEAD_BYTES + STDERR_TAIL_BYTES;
/** mkdtemp prefix for the report directory this plugin creates. */
export const OUT_DIR_PREFIX = 'boardwise-dsh-';
/** Raised when the CLI cannot be found, or cannot be started once found. */
export class BoardwiseCliError extends Error {
    constructor(message) {
        super(message);
        this.name = 'BoardwiseCliError';
    }
}
/** The three ways out of "no CLI found", spelled for the model that has to fix it. */
const NOT_FOUND_HELP = 'boardwise CLI not found. Fix one of the three:\n' +
    '  1. install the boardwise executable and put it on PATH (`boardwise.exe`);\n' +
    '  2. set BOARDWISE_EXE to that executable, or to a Python interpreter that has boardwise installed ' +
    '(e.g. E:/boardwise/.venv/Scripts/python.exe);\n' +
    '  3. run this plugin from a boardwise checkout so its virtualenv interpreter can be used ' +
    '(<repo>/.venv/Scripts/python.exe).';
const WINDOWS_LAUNCHERS = ['boardwise.exe', 'boardwise.cmd', 'boardwise.bat', 'boardwise'];
const POSIX_LAUNCHERS = ['boardwise'];
const WINDOWS_PYTHONS = ['python.exe', 'python3.exe', 'py.exe'];
const POSIX_PYTHONS = ['python3', 'python', 'py'];
/** An interpreter name that needs `-m boardwise.cli` to become the CLI. */
const PYTHON_NAME = /^(python|python3|py)(\d+(\.\d+)*)?w?$/i;
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
export function resolveCli(env = process.env, platform = process.platform) {
    const configured = readEnv(env, 'BOARDWISE_EXE');
    if (configured !== '') {
        if (!isFile(configured)) {
            throw new BoardwiseCliError(`BOARDWISE_EXE is set to "${configured}", which is not an existing file. ` +
                'Unset it to fall back to PATH, or point it at the boardwise executable / a Python interpreter that has boardwise installed.');
        }
        return { command: configured, prefix: pythonPrefix(configured), via: 'env' };
    }
    const launcher = findOnPath(platform === 'win32' ? WINDOWS_LAUNCHERS : POSIX_LAUNCHERS, env, platform);
    if (launcher !== null)
        return { command: launcher, prefix: [], via: 'path' };
    const python = findOnPath(platform === 'win32' ? WINDOWS_PYTHONS : POSIX_PYTHONS, env, platform);
    if (python !== null)
        return { command: python, prefix: ['-m', 'boardwise.cli'], via: 'python' };
    throw new BoardwiseCliError(NOT_FOUND_HELP);
}
/**
 * Run the boardwise CLI once.
 *
 * @param run - arguments, deadline and cancellation signal.
 * @param cli - resolved invocation; resolved from the environment when omitted.
 * @returns exit code, stdout/stderr (truncated) and how the run ended.
 * @throws BoardwiseCliError when the child cannot be started (missing executable, EACCES).
 */
export async function runBoardwise(run, cli = resolveCli()) {
    const argv = [...cli.prefix, ...run.argv];
    const out = new BoundedCapture(STDOUT_HEAD_BYTES, STDOUT_TAIL_BYTES);
    const err = new BoundedCapture(STDERR_HEAD_BYTES, STDERR_TAIL_BYTES);
    const commandLine = formatCommandLine(cli.command, argv);
    let timedOut = false;
    let aborted = false;
    const finish = (code, signal) => ({
        cli,
        commandLine,
        code,
        signal,
        stdout: redactSecrets(out.text()),
        stderr: redactSecrets(err.text()),
        stdoutBytes: out.bytes,
        stderrBytes: err.bytes,
        // S4#2: which stream lost bytes is recorded per stream, not folded into one
        // flag. The folded `truncated` stays (it is the "anything was cut" reading a
        // caller may already use), but a formatter can no longer say "stdout
        // truncated" about a run whose *stderr* was the one cut.
        stdoutTruncated: out.truncated,
        stderrTruncated: err.truncated,
        truncated: out.truncated || err.truncated,
        timedOut,
        aborted,
    });
    // An already-aborted call never reaches the process table.
    if (run.signal?.aborted === true) {
        aborted = true;
        return finish(null, null);
    }
    const child = spawn(cli.command, argv, { windowsHide: true });
    let settled = false;
    let timer;
    const kill = () => {
        try {
            child.kill('SIGKILL');
        }
        catch {
            // Already gone: the close event tells the story.
        }
    };
    const onAbort = () => {
        aborted = true;
        kill();
    };
    return await new Promise((resolve, reject) => {
        const settle = (code, signal) => {
            if (settled)
                return;
            settled = true;
            if (timer !== undefined)
                clearTimeout(timer);
            run.signal?.removeEventListener('abort', onAbort);
            resolve(finish(code, signal));
        };
        timer = setTimeout(() => {
            timedOut = true;
            kill();
        }, run.timeoutMs);
        timer.unref?.();
        run.signal?.addEventListener('abort', onAbort, { once: true });
        child.stdout?.on('data', (chunk) => out.push(chunk));
        child.stderr?.on('data', (chunk) => err.push(chunk));
        child.on('error', (error) => {
            // The command was named and verified, yet the OS refused it.
            if (settled)
                return;
            settled = true;
            if (timer !== undefined)
                clearTimeout(timer);
            run.signal?.removeEventListener('abort', onAbort);
            reject(new BoardwiseCliError(`cannot run "${commandLine}": ${error.message}`));
        });
        child.on('close', (code, signal) => settle(code, signal));
    });
}
/**
 * Keep the first `headLimit` and last `tailLimit` bytes of a stream, and count
 * all of it — so a chatty run cannot fill the model's context.
 */
class BoundedCapture {
    headLimit;
    tailLimit;
    head = Buffer.alloc(0);
    tail = Buffer.alloc(0);
    total = 0;
    constructor(headLimit, tailLimit) {
        this.headLimit = headLimit;
        this.tailLimit = tailLimit;
    }
    push(chunk) {
        this.total += chunk.length;
        let rest = chunk;
        if (this.head.length < this.headLimit) {
            const take = Math.min(this.headLimit - this.head.length, rest.length);
            this.head = Buffer.concat([this.head, rest.subarray(0, take)]);
            rest = rest.subarray(take);
        }
        if (rest.length === 0)
            return;
        this.tail = Buffer.concat([this.tail, rest]);
        if (this.tail.length > this.tailLimit) {
            this.tail = this.tail.subarray(this.tail.length - this.tailLimit);
        }
    }
    /** Bytes seen in total. */
    get bytes() {
        return this.total;
    }
    /** True when bytes were dropped between the head and the tail. */
    get truncated() {
        return this.total > this.head.length + this.tail.length;
    }
    /** Bytes that did not fit, and so are gone from the returned text. */
    get dropped() {
        return this.total - this.head.length - this.tail.length;
    }
    /**
     * The kept text. Nothing dropped means the head and the tail are the whole
     * stream, so they are rejoined and decoded in one piece — a multi-byte
     * character split across the two halves (the CLI writes UTF-8, and its
     * reports are Chinese) then survives intact. Only a truncated stream decodes
     * the halves separately, which would turn a split character into U+FFFD on
     * both sides; those two artefacts are trimmed, and the gap is marked with the
     * number of bytes that did not fit.
     */
    text() {
        if (!this.truncated)
            return decodeUtf8(Buffer.concat([this.head, this.tail]));
        const head = decodeUtf8(this.head).replace(/\uFFFD+$/, '');
        const tail = decodeUtf8(this.tail).replace(/^\uFFFD+/, '');
        return `${head}\n...[${this.dropped} bytes dropped]...\n${tail}`;
    }
}
/** Lossy-but-readable UTF-8 decode; the CLI reconfigures its streams to UTF-8. */
function decodeUtf8(buffer) {
    return new TextDecoder('utf-8').decode(buffer);
}
const SECRET_ASSIGNMENT = /((?:token|secret|password|passwd|api[-_]?key|credential)s?["']?\s*[:=]\s*)(["']?)([^\s"',;&)\]}|]+)/gi;
const BEARER = /\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}/gi;
/**
 * Scrub anything token-shaped out of CLI output. The bridge's daemon token must
 * never appear in a log or a model-facing result (task 045 §2).
 *
 * @param text - raw stream text.
 * @returns the text with credential values replaced by `***`.
 */
export function redactSecrets(text) {
    return text.replace(SECRET_ASSIGNMENT, '$1$2***').replace(BEARER, '$1***');
}
/** The spawned command, quoted the way a shell would need it. */
export function formatCommandLine(command, argv) {
    return [command, ...argv].map(quoteArg).join(' ');
}
function quoteArg(value) {
    return /\s/.test(value) ? `"${value.replaceAll('"', '\\"')}"` : value;
}
/** `-m boardwise.cli` when the command is a Python interpreter, nothing otherwise. */
function pythonPrefix(command) {
    const stem = basename(command).replace(/\.(exe|cmd|bat|sh)$/i, '');
    return PYTHON_NAME.test(stem) ? ['-m', 'boardwise.cli'] : [];
}
/** First existing executable among `names`, walked over PATH in order. */
function findOnPath(names, env, platform) {
    const path = readEnv(env, 'PATH') || readEnv(env, 'Path');
    const separator = platform === 'win32' ? ';' : ':';
    for (const dir of path.split(separator)) {
        if (dir === '')
            continue;
        for (const name of names) {
            const candidate = join(dir, name);
            if (isExecutableFile(candidate, platform))
                return candidate;
        }
    }
    return null;
}
function isFile(path) {
    try {
        return statSync(path).isFile();
    }
    catch {
        return false;
    }
}
function isExecutableFile(path, platform) {
    if (!existsSync(path))
        return false;
    try {
        const stats = statSync(path);
        if (!stats.isFile())
            return false;
        // Windows has no execute bit: the extension carries that meaning instead.
        return platform === 'win32' || (stats.mode & 0o111) !== 0;
    }
    catch {
        return false;
    }
}
/** Trimmed value of one environment variable, `''` when unset. */
function readEnv(env, key) {
    return (env[key] ?? '').trim();
}
