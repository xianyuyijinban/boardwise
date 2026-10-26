/**
 * boardwise tools for DeepSeek Harness: line-owned registration only (540B7).
 * Every judgement stays in the Python CLI; TypeScript owns argv and file transport.
 */
import { registerDrawTools } from './draw-tools.js';
import { registerReviewDelivery } from './review-delivery.js';
import { registerReviewCheckup, registerReviewWorkflow } from './review-tools.js';
import { registerSharedTools } from './shared-tools.js';
/** Cordis plugin name; the row id in `cordis.patch.yml` is `tool-boardwise`. */
export const name = 'boardwise-dsh';
/** Tools plus the host-only finalize projection and delivery gate services. */
export const inject = ['tools', 'sessionProjections', 'fs', 'workingDirectory'];
/** Preserve the old eight-tool order, then append offline draw compile/lint. */
export function apply(ctx) {
    registerReviewCheckup(ctx);
    registerSharedTools(ctx);
    registerReviewWorkflow(ctx);
    registerDrawTools(ctx);
    registerReviewDelivery(ctx);
}
