/**
 * boardwise tools for DeepSeek Harness: line-owned registration only (540B7).
 * Every judgement stays in the Python CLI; TypeScript owns argv and file transport.
 */
import type { Context } from '@deepseek-ai/cordis';
/** Cordis plugin name; the row id in `cordis.patch.yml` is `tool-boardwise`. */
export declare const name = "boardwise-dsh";
/** Tools plus the host-only finalize projection and delivery gate services. */
export declare const inject: string[];
/** Preserve the old eight-tool order, then append offline draw compile/lint. */
export declare function apply(ctx: Context): void;
