/**
 * 537D3a: the real `boardwise review finalize` tool and the Session receipt it
 * produces.
 *
 * The Python command validates a **delivery** (the recomputed report, the filled
 * summary and every cited artifact agree) and signs a deterministic
 * `finalize.json` receipt bound to the content hashes. This module adds the two
 * things a file cannot promise:
 *
 * 1. the receipt is read back **whole from the file** — never from dsh's
 *    truncated stdout — and its transport envelope is checked before anything is
 *    believed;
 * 2. the receipt is recorded in the **current Session** as an ignorable
 *    `plugin:boardwise-dsh/review-finalized` record whose payload is the complete
 *    post-change projection state. A later delivery gate (537D3b) reads that
 *    projection instead of a file the model could write by hand.
 *
 * What this module deliberately does not do: recompute the verdict, the pending
 * triage count or the cross-view candidates, and never turn `ok: true` into a
 * board-level pass. `report.conclusion` stays the only board-level authority.
 *
 * @module
 */
import { defineTool } from '@deepseek-ai/dsh-tools';
import { appendPluginRecord, pluginRecordOf } from '@deepseek-ai/dsh-session';
import { isAbsolute, join, resolve } from 'node:path';
import { z } from 'zod';
import { STRUCTURED_OUTPUT, describeValue, requireOut, runStructuredCli, text, } from './transport.js';
/** The tool name (the eighth boardwise tool). */
export const REVIEW_FINALIZE_TOOL = 'boardwise_review_finalize';
/** The CLI's delivery receipt inside `--out`. */
export const FINALIZE_RECEIPT_FILE = 'finalize.json';
/** The frozen transport envelope of that receipt. */
export const REVIEW_FINALIZE_SCHEMA = 'boardwise.review-finalize/1';
/** What the receipt signs: the content of this delivery, not the board. */
export const REVIEW_FINALIZE_SCOPE = 'delivery-content';
/** Where the board-level answer lives — in report.json, never in this receipt. */
export const REVIEW_FINALIZE_AUTHORITY = 'report.conclusion';
/** `boardwise review finalize` gets the same budget as the other review tools. */
export const REVIEW_FINALIZE_TIMEOUT_MS = 120_000;
/**
 * The plugin record type this tool appends. `plugin:` namespaces it away from
 * the released `SessionEventMap`, and `appendPluginRecord` marks it
 * `ignorable`, so a reader that does not know the type skips it instead of
 * refusing the session.
 */
export const REVIEW_FINALIZED_RECORD = 'plugin:boardwise-dsh/review-finalized';
/** The host-only projection this plugin registers for that record. */
export const REVIEW_FINALIZED_KEY = 'boardwiseReviewFinalized';
/** Bumped only when the serialized projection state or its fold changes. */
export const REVIEW_FINALIZED_STATE_VERSION = 1;
/** A sha256 as Python writes it: exactly 64 lowercase hex digits. */
const SHA256_LOWER = /^[0-9a-f]{64}$/;
/**
 * The receipt's own transport contract, shared by the file check and the
 * projection's record check — one definition, so a receipt this tool recorded
 * can never be rejected by its own projection (or vice versa).
 *
 * 537D3b exports the same judgement for the `present` delivery gate: a receipt
 * is usable only when its envelope, scope, authority and every file row are the
 * frozen shapes the CLI signs. There is exactly one recipe.
 */
export function finalizeReceiptProblem(value) {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) {
        return `the receipt root must be a JSON object, got ${describeValue(value)}`;
    }
    const receipt = value;
    const envelope = [
        ['schema', REVIEW_FINALIZE_SCHEMA],
        ['ok', true],
        ['scope', REVIEW_FINALIZE_SCOPE],
        ['boardConclusionAuthority', REVIEW_FINALIZE_AUTHORITY],
    ];
    for (const [field, expected] of envelope) {
        if (receipt[field] !== expected) {
            return `\`${field}\` is ${describeValue(receipt[field])}, not ${describeValue(expected)}`;
        }
    }
    const files = receipt['files'];
    if (!Array.isArray(files)) {
        return `\`files\` must be an array, got ${describeValue(files)}`;
    }
    for (const [index, row] of files.entries()) {
        if (row === null || typeof row !== 'object' || Array.isArray(row)) {
            return `files[${index}] must be an object, got ${describeValue(row)}`;
        }
        const file = row;
        if (typeof file['path'] !== 'string' || !isRelativeReceiptPath(file['path'])) {
            return (`files[${index}].path is ${describeValue(file['path'])}, not a relative POSIX path ` +
                'inside the review directory');
        }
        if (!Number.isSafeInteger(file['bytes']) || file['bytes'] < 0) {
            return `files[${index}].bytes is ${describeValue(file['bytes'])}, not a non-negative integer`;
        }
        if (typeof file['sha256'] !== 'string' || !SHA256_LOWER.test(file['sha256'])) {
            return `files[${index}].sha256 is ${describeValue(file['sha256'])}, not 64 lowercase hex digits`;
        }
    }
    return null;
}
/**
 * A receipt path is relative to `--out` and POSIX-shaped: no absolute path, no
 * drive letter, no `..` escape, no backslash (the CLI writes `as_posix()`).
 */
function isRelativeReceiptPath(path) {
    if (path === '' || isAbsolute(path))
        return false;
    if (path.includes('\\') || /^[A-Za-z]:/.test(path))
        return false;
    return path.split('/').every(segment => segment !== '' && segment !== '.' && segment !== '..');
}
/**
 * The directory key: the absolute, normalized `--out`, case-folded on Windows.
 *
 * Python's receipt containment check folds with `os.path.normcase`; the same
 * recipe keeps `E:\Review` and `e:\review` one key on this host, so finalizing
 * the same directory again replaces its receipt instead of accumulating twins.
 * The entry keeps the caller's absolute spelling for the delivery gate.
 */
export function directoryKeyOf(reviewDir) {
    return process.platform === 'win32' ? reviewDir.toLowerCase() : reviewDir;
}
const receiptSchema = z.custom(value => finalizeReceiptProblem(value) === null, { message: 'not a complete `boardwise.review-finalize/1` delivery receipt' });
const projectionStateSchema = z.object({
    receipts: z.record(z.string(), z.object({
        reviewDir: z.string().min(1),
        receipt: receiptSchema,
        callId: z.string().nullable(),
    })),
});
/**
 * Register the Session projection and the eighth tool.
 *
 * The projection registration is optional so a lightweight fake `Context` (the
 * older registration tests) still mounts the tool; **executing** the tool
 * without a projection service is a loud failure, never a quiet "the file was
 * fine, so this counts". In production `inject` names `sessionProjections`, so
 * the plugin is not loaded without it.
 */
export function registerReviewFinalize(ctx) {
    const projections = ctx.sessionProjections;
    if (projections !== undefined) {
        projections.register({
            key: REVIEW_FINALIZED_KEY,
            stateVersion: REVIEW_FINALIZED_STATE_VERSION,
            stateSchema: projectionStateSchema,
            init: () => ({ receipts: {} }),
            apply: (state, event) => {
                const record = pluginRecordOf(event);
                if (record === undefined || record.type !== REVIEW_FINALIZED_RECORD) {
                    // Not ours: the same reference keeps every other unit's work untouched.
                    return state;
                }
                const parsed = projectionStateSchema.safeParse(record.data);
                // Fail closed: a record we cannot read grants no delivery qualification
                // and must not take the projection (or the session) down with it.
                if (!parsed.success)
                    return state;
                return parsed.data;
            },
        });
    }
    ctx.tools.register(defineTool({
        name: REVIEW_FINALIZE_TOOL,
        description: 'Finalize one delivered boardwise review: runs `boardwise review finalize --out DIR`, which recomputes the ' +
            'report and the summary, proves every cited artifact still matches, and only then signs the deterministic ' +
            '`finalize.json` receipt (`boardwise.review-finalize/1`, scope=delivery-content). ' +
            'Exit 0 means **this delivery** is consistent — it is not a board verdict: the board-level answer stays ' +
            '`report.conclusion` inside report.json, and this tool never recomputes the verdict, the pending triage ' +
            'count or the cross-view candidates. ' +
            'On success the receipt is read back **whole from the file** (never from stdout, which dsh truncates) and ' +
            'its envelope and every file row (relative path, bytes, sha256) are checked; the complete receipt is then ' +
            'recorded in the **current Session** as an ignorable `plugin:boardwise-dsh/review-finalized` record, so a ' +
            'later delivery gate reads the Session instead of a hand-written file. The result carries `reviewDir`, the ' +
            'checked `receipt` and the record `seq`. ' +
            'A non-zero exit, a timeout or cancellation, a missing/invalid `finalize.json`, or a call with no current ' +
            'Session records nothing and is an error. Exit codes: 0 = delivery consistent; 1 = content disagreement; ' +
            '2 = unusable input; 3 = no report.json to finalize.',
        parameters: {
            out: {
                type: 'string',
                required: true,
                description: 'The `checkup --out` review directory to finalize. The CLI writes `finalize.json` there; ' +
                    'this tool reads it in full and records it in the current Session.',
            },
        },
        output: STRUCTURED_OUTPUT,
        execute: async (args, exec) => {
            const tool = REVIEW_FINALIZE_TOOL;
            const out = requireOut(tool, text(args.out));
            if (projections === undefined) {
                throw new Error(`${tool}: no session-projection service is available, so the receipt could not be recorded in this ` +
                    'Session. The plugin declares `sessionProjections` in its inject list; a mount without it cannot ' +
                    'promise a Session receipt, and a file-only answer is not accepted as success.');
            }
            const session = exec.agent?.session;
            if (session === undefined) {
                throw new Error(`${tool}: this call has no current Session (\`exec.agent.session\` is absent), and a finalize receipt ` +
                    'only counts when it is recorded in the Session that delivered it. Nothing was recorded.');
            }
            const reviewDir = resolve(out);
            const directoryKey = directoryKeyOf(reviewDir);
            // argv is the one place this command is spelled; the CLI owns every
            // judgement behind it. `--out` is passed as the caller gave it.
            const argv = ['review', 'finalize', '--out', out];
            const receiptPath = join(reviewDir, FINALIZE_RECEIPT_FILE);
            const parsed = await runStructuredCli(tool, argv, REVIEW_FINALIZE_TIMEOUT_MS, exec, receiptPath);
            const problem = finalizeReceiptProblem(parsed);
            if (problem !== null) {
                throw new Error(`${tool}: exit 0 but ${receiptPath} is not a usable delivery receipt: ${problem}. ` +
                    'Nothing was recorded in the Session.');
            }
            const receipt = parsed;
            const rawCallId = exec.callId;
            const entry = {
                reviewDir,
                receipt,
                callId: typeof rawCallId === 'string' && rawCallId !== '' ? rawCallId : null,
            };
            // stateOf → spread → append: deliberately synchronous. An `await` here
            // could interleave with another finalize and drop its directory.
            const current = projections.stateOf(session, REVIEW_FINALIZED_KEY);
            if (current === undefined) {
                throw new Error(`${tool}: the session-projection registry does not serve \`${REVIEW_FINALIZED_KEY}\`, so the receipt ` +
                    'has nowhere to be recorded. Nothing was recorded.');
            }
            const receipts = {
                ...current.receipts,
                [directoryKey]: entry,
            };
            const seq = appendPluginRecord(session, REVIEW_FINALIZED_RECORD, { receipts });
            const result = {
                out,
                reviewDir,
                directoryKey,
                receipt,
                sessionRecord: { type: REVIEW_FINALIZED_RECORD, seq },
            };
            // The shared object output schema infers as `Record<string, never>` (it
            // declares `additionalProperties` without properties), so the typed result
            // is handed back through the transport type it is rendered as.
            return result;
        },
        timeoutMs: REVIEW_FINALIZE_TIMEOUT_MS,
    }));
}
