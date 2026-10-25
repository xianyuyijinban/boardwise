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
import type { Context } from '@deepseek-ai/cordis';
/** The tool name (the eighth boardwise tool). */
export declare const REVIEW_FINALIZE_TOOL = "boardwise_review_finalize";
/** The CLI's delivery receipt inside `--out`. */
export declare const FINALIZE_RECEIPT_FILE = "finalize.json";
/** The frozen transport envelope of that receipt. */
export declare const REVIEW_FINALIZE_SCHEMA = "boardwise.review-finalize/1";
/** What the receipt signs: the content of this delivery, not the board. */
export declare const REVIEW_FINALIZE_SCOPE = "delivery-content";
/** Where the board-level answer lives — in report.json, never in this receipt. */
export declare const REVIEW_FINALIZE_AUTHORITY = "report.conclusion";
/** `boardwise review finalize` gets the same budget as the other review tools. */
export declare const REVIEW_FINALIZE_TIMEOUT_MS = 120000;
/**
 * The plugin record type this tool appends. `plugin:` namespaces it away from
 * the released `SessionEventMap`, and `appendPluginRecord` marks it
 * `ignorable`, so a reader that does not know the type skips it instead of
 * refusing the session.
 */
export declare const REVIEW_FINALIZED_RECORD = "plugin:boardwise-dsh/review-finalized";
/** The host-only projection this plugin registers for that record. */
export declare const REVIEW_FINALIZED_KEY = "boardwiseReviewFinalized";
/** Bumped only when the serialized projection state or its fold changes. */
export declare const REVIEW_FINALIZED_STATE_VERSION = 1;
/** One content-bound file row of the CLI receipt — always relative to `--out`. */
export interface FinalizeReceiptFile {
    readonly path: string;
    readonly bytes: number;
    readonly sha256: string;
}
/** The complete `finalize.json` payload the CLI signs after a successful run. */
export interface ReviewFinalizeReceipt {
    readonly schema: string;
    readonly ok: true;
    readonly scope: string;
    readonly boardConclusionAuthority: string;
    readonly files: readonly FinalizeReceiptFile[];
    /** The CLI may add fields; they are carried through untouched. */
    readonly [key: string]: unknown;
}
/** One finalized review directory, as the Session remembers it. */
export interface ReviewFinalizedEntry {
    /** The absolute review directory (`--out`), kept for the delivery gate. */
    readonly reviewDir: string;
    /** The complete receipt, exactly as the CLI wrote it. */
    readonly receipt: ReviewFinalizeReceipt;
    /** The tool call that produced it, for audit. */
    readonly callId: string | null;
}
/**
 * The **complete** projection state: every finalized directory this Session has
 * seen. Records carry this whole value, never a delta (whole-value event rule),
 * so a receiver never has to reconstruct state from a partial log.
 */
export interface BoardwiseReviewFinalizedState {
    readonly receipts: Readonly<Record<string, ReviewFinalizedEntry>>;
}
declare module '@deepseek-ai/dsh-session/types' {
    interface PluginRecordMap {
        /** 537D3a: one complete post-change review-finalized projection state. */
        'plugin:boardwise-dsh/review-finalized': BoardwiseReviewFinalizedState;
    }
}
declare module '@deepseek-ai/dsh-session-projection/types' {
    interface SessionProjectionStateMap {
        /** 537D3a: host-only; read by the delivery gate, never sent to a client. */
        boardwiseReviewFinalized: BoardwiseReviewFinalizedState;
    }
}
/**
 * The receipt's own transport contract, shared by the file check and the
 * projection's record check — one definition, so a receipt this tool recorded
 * can never be rejected by its own projection (or vice versa).
 *
 * 537D3b exports the same judgement for the `present` delivery gate: a receipt
 * is usable only when its envelope, scope, authority and every file row are the
 * frozen shapes the CLI signs. There is exactly one recipe.
 */
export declare function finalizeReceiptProblem(value: unknown): string | null;
/**
 * The directory key: the absolute, normalized `--out`, case-folded on Windows.
 *
 * Python's receipt containment check folds with `os.path.normcase`; the same
 * recipe keeps `E:\Review` and `e:\review` one key on this host, so finalizing
 * the same directory again replaces its receipt instead of accumulating twins.
 * The entry keeps the caller's absolute spelling for the delivery gate.
 */
export declare function directoryKeyOf(reviewDir: string): string;
/** The structured answer of one successful finalize. */
export interface ReviewFinalizeResult {
    /** `--out` exactly as the caller spelled it. */
    readonly out: string;
    /** The absolute review directory the receipt belongs to. */
    readonly reviewDir: string;
    /** The projection key this directory's receipt is stored under. */
    readonly directoryKey: string;
    /** The complete `finalize.json` payload. */
    readonly receipt: ReviewFinalizeReceipt;
    /** Where the receipt was recorded in this Session. */
    readonly sessionRecord: {
        readonly type: typeof REVIEW_FINALIZED_RECORD;
        readonly seq: number;
    };
}
/**
 * Register the Session projection and the eighth tool.
 *
 * The projection registration is optional so a lightweight fake `Context` (the
 * older registration tests) still mounts the tool; **executing** the tool
 * without a projection service is a loud failure, never a quiet "the file was
 * fine, so this counts". In production `inject` names `sessionProjections`, so
 * the plugin is not loaded without it.
 */
export declare function registerReviewFinalize(ctx: Context): void;
