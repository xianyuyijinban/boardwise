/**
 * boardwise tools for the DeepSeek Harness (task 045).
 *
 * Eight thin tools over the local boardwise CLI: checkup / arch / doctor run the
 * review harness itself, bridge is the escape hatch into the connector's action
 * catalogue, review_read projects one report section to canonical JSON,
 * review_evidence collects live schematic/PCB evidence, triage_batch applies
 * warning verdicts atomically, and review_finalize (537D3a) validates one
 * delivery and records its receipt in the current Session. No review logic lives
 * here — arguments are passed through, stdout / exit codes / the CLI's `--json`
 * files come back, and the report files the CLI wrote are named for the model
 * (task 045 §1: "any idea of recomputing this in TS is refused").
 */
import type { Context } from '@deepseek-ai/cordis';
/** Cordis plugin name; the row id in `cordis.patch.yml` is `tool-boardwise`. */
export declare const name = "boardwise-dsh";
/**
 * This plugin contributes tools, one host-only Session projection (537D3a) and
 * the `present` delivery gate (537D3b). All four services are required:
 * `sessionProjections` gives a finalize receipt somewhere to be recorded and
 * the gate somewhere to read it; `fs` and `workingDirectory` let that gate
 * resolve and re-hash a delivery through the harness rather than `node:fs`.
 * The plugin must not load without them rather than pretend.
 */
export declare const inject: string[];
export declare function apply(ctx: Context): void;
