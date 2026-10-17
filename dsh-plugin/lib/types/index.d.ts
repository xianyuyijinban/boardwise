/**
 * boardwise tools for the DeepSeek Harness (task 045).
 *
 * Four thin tools over the local boardwise CLI: checkup / arch / doctor run the
 * review harness itself, bridge is the escape hatch into the connector's action
 * catalogue. No review logic lives here — arguments are passed through, stdout
 * and the exit code come back, and the report files the CLI wrote are named for
 * the model (task 045 §1: "any idea of recomputing this in TS is refused").
 */
import type { Context } from '@deepseek-ai/cordis';
/** Cordis plugin name; the row id in `cordis.patch.yml` is `tool-boardwise`. */
export declare const name = "boardwise-dsh";
/** This plugin only contributes tools. */
export declare const inject: string[];
export declare function apply(ctx: Context): void;
