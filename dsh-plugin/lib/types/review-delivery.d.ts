/**
 * 537D3b: the `present` delivery hard gate.
 *
 * A finalized review delivery is a directory whose content the CLI signed in
 * `finalize.json`: every tracked file (relative POSIX path, size, sha256) and
 * the complete receipt itself are recorded in the current Session's
 * `boardwiseReviewFinalized` projection by 537D3a. `finalize.json` on disk is
 * **not** an authorization: a model can write one by hand, copy one from
 * another directory, or leave the Session record from a delivery it has since
 * changed. So this gate reads only the projection and re-proves the content:
 *
 * 1. a `present` call is classified file by file. A `review-summary.md` in an
 *    ancestor directory marks a review directory, and a directory the current
 *    Session already finalized is recognized even after that marker is gone.
 *    The **nearest** such ancestor wins, so a nested delivery can never borrow
 *    its parent's (or a sibling's) receipt. Ordinary images, Office files and a
 *    `report.md` with no marker simply continue.
 * 2. the nearest review directory must have a **usable** receipt recorded for
 *    this exact Session and this exact directory. A receipt from another
 *    Session, a hand-written `finalize.json`, a delivery whose finalize has not
 *    completed yet, a malformed record, and an untracked file inside the
 *    directory are all denials.
 * 3. for a matched receipt **every** tracked file is recomputed — not only the
 *    one being presented. Each row must stay a relative POSIX path inside the
 *    directory, resolve through `ctx.fs`, be a regular file of exactly
 *    `bytes`, and hash to the recorded sha256 read in chunks of at most 1 MiB.
 *    Any change after finalize (including a tracked file nobody presented, and
 *    a deleted marker) invalidates the receipt and denies.
 *
 * Every failure — including an unexpected helper exception — is
 * `{kind: 'deny', reason}`; `next()` is never called on that path, and the
 * execution token is never echoed. All filesystem I/O goes through `ctx.fs`;
 * this module never reaches for `node:fs`.
 *
 * @module
 */
import type { Context } from '@deepseek-ai/cordis';
import type { PreToolDecision, ToolExecution } from '@deepseek-ai/dsh-tools';
import type { Session } from '@deepseek-ai/dsh-session';
import { REVIEW_FINALIZED_KEY } from './review-finalize.ts';
/** The one tool this gate inspects. Every other tool takes `next()` untouched. */
export declare const REVIEW_DELIVERY_TOOL = "present";
/** The cordis event the listener is mounted on. */
export declare const REVIEW_DELIVERY_EVENT = "tools/pre-execute";
/** The marker file whose parent directory is a review directory. */
export declare const REVIEW_DELIVERY_MARKER = "review-summary.md";
/**
 * Hash chunks stay at or below 1 MiB (`readByteRange` bounds the transfer, not
 * the file), so a large delivery is read in several windows instead of one
 * unbounded buffer.
 */
export declare const REVIEW_DELIVERY_CHUNK_BYTES = 1048576;
/**
 * The slice of `ctx.fs` this gate uses. Declared structurally so the plugin
 * needs no new peer dependency; a real `FileSystem` (local, sandboxed or
 * otherwise) satisfies it unchanged.
 */
export interface DeliveryTarget {
    readonly targetKey: string;
    readonly displayPath: string;
}
export interface DeliveryStat {
    readonly type: 'file' | 'directory' | 'other';
    readonly size?: number;
}
export interface DeliveryFileSystem {
    resolve(path: string, opts?: {
        cwd?: string;
        signal?: AbortSignal;
    }): Promise<DeliveryTarget>;
    processPath(target: DeliveryTarget): string;
    stat(target: DeliveryTarget, signal?: AbortSignal): Promise<DeliveryStat | undefined>;
    contains(parent: DeliveryTarget, child: DeliveryTarget): boolean;
    readByteRange(target: DeliveryTarget, range: {
        offset: number;
        length: number;
    }, signal?: AbortSignal): Promise<Uint8Array>;
}
/** The slice of `ctx.workingDirectory` this gate uses. */
export interface DeliveryWorkingDirectory {
    get(session: Session): string;
}
/** The slice of `ctx.sessionProjections` this gate uses. */
export interface DeliveryProjections {
    stateOf(session: Session, key: typeof REVIEW_FINALIZED_KEY): unknown;
}
/** Everything the listener needs; production `inject` guarantees all three. */
export interface ReviewDeliveryServices {
    readonly fs: DeliveryFileSystem;
    readonly workingDirectory: DeliveryWorkingDirectory;
    readonly sessionProjections: DeliveryProjections;
}
/** The `tools/pre-execute` listener shape (the registry waterfall contract). */
export type ReviewDeliveryListener = (exec: ToolExecution, next: () => Promise<PreToolDecision>) => Promise<PreToolDecision>;
/**
 * Mount the gate on the root context.
 *
 * Registration is optional while the services are incomplete: the older
 * registration tests mount `apply` on a light fake context that only has
 * `tools`. In production `inject` names `tools`, `sessionProjections`, `fs` and
 * `workingDirectory`, so the listener is always present there. A partial mount
 * gets no gate rather than a gate that cannot resolve paths or receipts.
 */
export declare function registerReviewDelivery(ctx: Context): (() => boolean) | undefined;
/**
 * Build the listener itself. The main agent's independent integration can use
 * this directly with any `FileSystem`/`workingDirectory`/projection pair; the
 * plugin's own `apply` reaches it through {@link registerReviewDelivery} and
 * `ctx.on('tools/pre-execute', …)`.
 */
export declare function createReviewDeliveryGate(services: ReviewDeliveryServices): ReviewDeliveryListener;
