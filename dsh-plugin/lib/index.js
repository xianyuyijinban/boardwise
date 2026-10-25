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
import { defineTool } from '@deepseek-ai/dsh-tools';
import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { OUT_DIR_PREFIX } from './cli.js';
import { registerReviewDelivery } from './review-delivery.js';
import { registerReviewFinalize } from './review-finalize.js';
import { STRUCTURED_OUTPUT, TEXT_OUTPUT, describeValue, executeCli, requireOut, runStructuredCli, text, } from './transport.js';
/** Cordis plugin name; the row id in `cordis.patch.yml` is `tool-boardwise`. */
export const name = 'boardwise-dsh';
/**
 * This plugin contributes tools, one host-only Session projection (537D3a) and
 * the `present` delivery gate (537D3b). All four services are required:
 * `sessionProjections` gives a finalize receipt somewhere to be recorded and
 * the gate somewhere to read it; `fs` and `workingDirectory` let that gate
 * resolve and re-hash a delivery through the harness rather than `node:fs`.
 * The plugin must not load without them rather than pretend.
 */
export const inject = ['tools', 'sessionProjections', 'fs', 'workingDirectory'];
const CHECKUP_TIMEOUT_MS = 600_000;
const ARCH_TIMEOUT_MS = 120_000;
const DOCTOR_TIMEOUT_MS = 60_000;
const BRIDGE_TIMEOUT_MS = 120_000;
const REVIEW_READ_TIMEOUT_MS = 120_000;
const REVIEW_EVIDENCE_TIMEOUT_MS = 600_000;
const TRIAGE_BATCH_TIMEOUT_MS = 120_000;
/** 537D1a: the transport envelope `review-read --json` writes, in full, to a file. */
const REVIEW_READ_SCHEMA = 'boardwise.review-read/1';
/** The six sections the Python projection serves; the enum is the transport list. */
const REVIEW_READ_SECTIONS = [
    'verdict',
    'findings',
    'crossView',
    'coverage',
    'artifacts',
    'netlist',
];
/** 537D1b1: the strict input object Python validates as a whole, and its result. */
const TRIAGE_BATCH_SCHEMA = 'boardwise.triage-batch/1';
const TRIAGE_BATCH_RESULT_SCHEMA = 'boardwise.triage-batch-result/1';
/** mkdtemp prefix for the plugin's own transport files (`--json` targets). */
const TRANSPORT_DIR_PREFIX = 'boardwise-dsh-';
export function apply(ctx) {
    ctx.tools.register(defineTool({
        name: 'boardwise_checkup',
        description: 'Review one EasyEDA Pro design with boardwise and read the report that comes back. ' +
            'Designs are named exactly once: file= runs fully offline on an exported .epro2/.enet backup ' +
            '(no editor, no daemon), while project= or instance= reads the project open in the editor ' +
            'through the local bridge daemon — the live path only reads, it never edits. ' +
            'boardwise writes report.json, report.md, architecture.md and design-intent.md into `out` (a fresh temp ' +
            'directory when omitted) and this tool returns those paths, the CLI stdout and its exit code: 0 = a model was read and ' +
            'nothing is an ERROR, 1 = an ERROR was found, 2 = the input cannot be used, 3 = nothing may be stated ' +
            '(the online state cannot be read — usually several editor windows are connected, so name one with ' +
            'project=/instance= — or the report\'s completion.verdict is `incomplete`, i.e. the review did not see the ' +
            'whole board: an empty model, parts with no datasheet, no architecture skeleton, missing coverage). ' +
            'Exit 3 is never a pass; read completion.verdict for which of the two it is. ' +
            'A timeout longer than 10 minutes means the plugin gave up on it.',
        parameters: {
            file: {
                type: 'string',
                description: 'Path to an exported .epro2 / .enet backup to review offline. Exclusive with project/instance.',
            },
            project: {
                type: 'string',
                description: 'Editor window to read live, by project name or uuid. Needed when several windows are connected ' +
                    'and the focus is ambiguous.',
            },
            instance: {
                type: 'string',
                description: 'The same choice spelled as the window key `bridge status` prints — for a window that cannot name ' +
                    'a project yet. Exclusive with file.',
            },
            out: {
                type: 'string',
                description: `Directory for report.json / report.md / architecture.md / design-intent.md (created if missing). ` +
                    `Default: a fresh temp directory with the prefix "${OUT_DIR_PREFIX}".`,
            },
        },
        output: TEXT_OUTPUT,
        execute: async (args, exec) => {
            const tool = 'boardwise_checkup';
            const file = text(args.file);
            const project = text(args.project);
            const instance = text(args.instance);
            const named = [file, project, instance].filter(value => value !== '').length;
            if (named !== 1) {
                throw new Error(`${tool}: name exactly one design — file (an exported .epro2/.enet, offline) or project/instance ` +
                    `(the project open in the editor). Got ${named} of the three; boardwise never guesses which window to read.`);
            }
            if (file !== '')
                requireExistingFile(tool, file);
            const outDir = text(args.out) !== '' ? text(args.out) : await mkdtemp(join(tmpdir(), OUT_DIR_PREFIX));
            await ensureDirectory(tool, outDir);
            const argv = ['checkup'];
            if (file !== '')
                argv.push('--file', file);
            else if (project !== '')
                argv.push('--project', project);
            else
                argv.push('--instance', instance);
            argv.push('--out', outDir);
            return await executeCli(tool, argv, CHECKUP_TIMEOUT_MS, exec, [
                { label: 'report.json', path: join(outDir, 'report.json') },
                { label: 'report.md', path: join(outDir, 'report.md') },
                { label: 'architecture.md', path: join(outDir, 'architecture.md') },
                // Generated and overwritten every run — the answer sheet, by contrast, is
                // `design-intent.md`: created once, then read-only (053 §2.2).
                { label: 'design-intent.md', path: join(outDir, 'design-intent.md') },
            ]);
        },
        timeoutMs: CHECKUP_TIMEOUT_MS,
    }));
    ctx.tools.register(defineTool({
        name: 'boardwise_arch',
        description: 'Generate the architecture skeleton boardwise builds for one exported .epro2/.enet (task 044): power tree, ' +
            'analog chains, control chains, buses and design-intent slots, with every judgement a tool cannot make left ' +
            'as a TODO slot for the engineer to fill. Offline and deterministic — the same model yields byte-identical ' +
            'markdown. The skeleton is **generated and overwritten**; the answers belong in the paired `design-intent.md` ' +
            'beside `out` (created once as an all-TODO template, then read-only, 053 §2.2) and are merged back into the ' +
            'report`s architecture section. ' +
            'Without `out` the markdown comes back on stdout (long; it may be truncated); with `out` it is written to that ' +
            'file and the path is returned. Exit 0 = generated, 2 = the input cannot be used.',
        parameters: {
            file: {
                type: 'string',
                required: true,
                description: 'The .epro2 / .enet export to read (read-only).',
            },
            out: {
                type: 'string',
                description: 'Write the markdown here instead of stdout (parent directories are created).',
            },
        },
        output: TEXT_OUTPUT,
        execute: async (args, exec) => {
            const tool = 'boardwise_arch';
            const file = requireExistingFile(tool, text(args.file));
            const out = text(args.out);
            const argv = ['arch', file];
            const artifacts = [];
            if (out !== '') {
                await ensureDirectory(tool, dirname(out));
                argv.push('--out', out);
                artifacts.push({ label: 'architecture', path: out });
                // The CLI keeps the pair: the skeleton at `out`, the engineer's answers
                // in `design-intent.md` beside it.
                artifacts.push({ label: 'design-intent', path: join(dirname(out), 'design-intent.md') });
            }
            return await executeCli(tool, argv, ARCH_TIMEOUT_MS, exec, artifacts);
        },
        timeoutMs: ARCH_TIMEOUT_MS,
    }));
    ctx.tools.register(defineTool({
        name: 'boardwise_doctor',
        description: 'Diagnose the local boardwise installation in one run: the daemon answers ping, the editor extension is ' +
            'connected, the five methods the harness depends on exist, the running daemon and connector versions match ' +
            'this install, the editor is new enough, and the focused project can be read. ' +
            'project= / instance= name which editor window the online checks ask: as soon as several windows are ' +
            'connected the daemon refuses to guess, and those checks answer "not verified" instead of inventing an answer. ' +
            'Green exits 0; anything else exits 1 with one suggested fix per failing line. Read-only.',
        parameters: {
            project: {
                type: 'string',
                description: 'Editor window to ask, by project name or uuid.',
            },
            instance: {
                type: 'string',
                description: 'The same choice by window key (`bridge status` prints them); decides when both are given.',
            },
        },
        output: TEXT_OUTPUT,
        execute: async (args, exec) => {
            const tool = 'boardwise_doctor';
            const argv = ['doctor'];
            if (text(args.project) !== '')
                argv.push('--project', text(args.project));
            if (text(args.instance) !== '')
                argv.push('--instance', text(args.instance));
            return await executeCli(tool, argv, DOCTOR_TIMEOUT_MS, exec);
        },
        timeoutMs: DOCTOR_TIMEOUT_MS,
    }));
    ctx.tools.register(defineTool({
        name: 'boardwise_bridge',
        description: 'Escape hatch: call one action of the boardwise connector catalogue directly on the live editor, for probes ' +
            'and diagnosis that no higher-level tool covers (e.g. sys.probe, sys.identity, doc.list, sch.readback, ' +
            'export.render). `action` is the catalogue name and `params` a JSON object literal; project= / instance= route ' +
            'the call to one editor window when several are connected (without them the daemon answers WINDOW_UNSPECIFIED ' +
            'rather than guessing). Every call is made with `--read-only`, so the CLI refuses — before contacting the ' +
            'editor — any action whose catalogue risk is not `read` (doc.focus and every other write, create or dangerous ' +
            'tier, and unknown names). Designs are changed with the boardwise CLI under its own identity discipline, never ' +
            'through this tool. Daemon tokens are never printed.',
        parameters: {
            action: {
                type: 'string',
                required: true,
                description: 'Action name from the connector catalogue, e.g. "sys.probe" or "doc.list".',
            },
            params: {
                type: 'string',
                required: true,
                description: 'Action params as a JSON object literal, e.g. "{}" for no params. Passed to the CLI verbatim.',
            },
            project: {
                type: 'string',
                description: 'Route the call to the editor window with this project name or uuid.',
            },
            instance: {
                type: 'string',
                description: 'The same choice by window key; decides when both project= and instance= are given.',
            },
        },
        output: TEXT_OUTPUT,
        execute: async (args, exec) => {
            const tool = 'boardwise_bridge';
            const action = text(args.action);
            if (action === '')
                throw new Error(`${tool}: action is required (a name from the connector catalogue)`);
            const params = requireJsonObject(tool, text(args.params));
            // `--read-only` is the 537A hard gate: the CLI refuses a non-read action
            // (write / create / dangerous / unknown) before it reaches for the daemon
            // or the editor. It is pinned in argv on every call, not left to the
            // prompt: the tool's own promise must be enforced by the command it runs.
            const argv = ['bridge', 'call', '--read-only', '--action', action, '--params', params];
            if (text(args.project) !== '')
                argv.push('--project', text(args.project));
            if (text(args.instance) !== '')
                argv.push('--instance', text(args.instance));
            return await executeCli(tool, argv, BRIDGE_TIMEOUT_MS, exec);
        },
        timeoutMs: BRIDGE_TIMEOUT_MS,
    }));
    ctx.tools.register(defineTool({
        name: 'boardwise_review_read',
        description: 'Read one section of an existing boardwise `checkup` report as structured JSON — the one supported ' +
            'answer to "what does the report say", instead of hand-written JSON parsing. `section` is one of ' +
            'verdict (report.conclusion, the only board-level answer), findings (findings + the triage ledger), ' +
            'crossView, coverage, artifacts (every cited file with exists/bytes/sha256 status) or netlist ' +
            '(the live capture\'s own netlist, only when its identity and liveSchematic are proven). ' +
            'The CLI writes the whole envelope `{schema: "boardwise.review-read/1", section, report: {path, schema}, ' +
            'payload}` to a private temp file via `--json`, and this tool returns that parsed object and renders it as ' +
            'complete pretty JSON. There is no `ok` field: a successful read is not a passed board, and the verdict ' +
            'stays `payload.conclusion`. Exit 0 = projected; 2 = unusable input/output path; 3 = no report.json. ' +
            'A non-zero exit, a missing/unreadable file or a wrong schema/section is an error — never a partial or ' +
            'stdout-derived answer (dsh truncates stdout at 32 KiB).',
        parameters: {
            out: {
                type: 'string',
                required: true,
                description: 'The `checkup --out` directory holding report.json. Read-only; nothing is written there.',
            },
            section: {
                type: 'string',
                required: true,
                enum: REVIEW_READ_SECTIONS,
                description: 'Which question to answer: verdict / findings / crossView / coverage / artifacts / netlist.',
            },
        },
        output: STRUCTURED_OUTPUT,
        execute: async (args, exec) => {
            const tool = 'boardwise_review_read';
            const out = requireOut(tool, text(args.out));
            const section = text(args.section);
            const target = join(await transportDir(tool), 'review-read.json');
            const argv = ['review-read', '--out', out, '--section', section, '--json', target];
            const envelope = await runStructuredCli(tool, argv, REVIEW_READ_TIMEOUT_MS, exec, target);
            requireField(tool, envelope, 'schema', REVIEW_READ_SCHEMA);
            requireField(tool, envelope, 'section', section);
            requireObjectField(tool, envelope, 'report');
            requirePresentField(tool, envelope, 'payload');
            return envelope;
        },
        timeoutMs: REVIEW_READ_TIMEOUT_MS,
    }));
    ctx.tools.register(defineTool({
        name: 'boardwise_review_evidence',
        description: 'Collect the live schematic/PCB evidence for an existing boardwise `checkup` report through the local ' +
            'bridge, merge it into that report\'s evidence ledger, and return the CLI\'s formatted result. Read-only: ' +
            'it opens documents, proves focus, reads back/netlists/geometries/renders, and restores the original focus; ' +
            'it never writes the design. `--out` is the existing `checkup --out` directory (report.json is required), ' +
            'project=/instance= choose the editor window, and page=/pcb= may be repeated to collect an explicit subset ' +
            '(an explicit subset is disclosed as missing coverage, never ok). Files written: report.json, report.md, ' +
            'board-report.md and live-evidence.json. Exit codes describe this collection, not the board: 0 = collector ok, ' +
            'identity verified, focus restored; 1 = some direct evidence failed/missing, an explicit subset, identity ' +
            'unverified or focus not restored; 2 = unusable input/merge; 3 = nothing may be stated (no report.json, no ' +
            'daemon, doc.list failed). The board conclusion still comes from report.json via boardwise_review_read.',
        parameters: {
            out: {
                type: 'string',
                required: true,
                description: 'The existing `checkup --out` directory holding report.json (the capture is merged into it).',
            },
            project: {
                type: 'string',
                description: 'Which editor window to read, by project name or uuid.',
            },
            instance: {
                type: 'string',
                description: 'The same choice spelled as the window key `bridge status` prints.',
            },
            page: {
                type: 'array',
                items: { type: 'string' },
                description: 'Collect only this schematic page (repeat for several). Default: every document doc.list reports.',
            },
            pcb: {
                type: 'array',
                items: { type: 'string' },
                description: 'Collect only this PCB document (repeat for several). Default: all.',
            },
        },
        output: TEXT_OUTPUT,
        execute: async (args, exec) => {
            const tool = 'boardwise_review_evidence';
            const out = requireOut(tool, text(args.out));
            const argv = ['review-evidence', '--out', out];
            if (text(args.project) !== '')
                argv.push('--project', text(args.project));
            if (text(args.instance) !== '')
                argv.push('--instance', text(args.instance));
            for (const page of stringList(args.page))
                argv.push('--page', page);
            for (const pcb of stringList(args.pcb))
                argv.push('--pcb', pcb);
            return await executeCli(tool, argv, REVIEW_EVIDENCE_TIMEOUT_MS, exec, [
                { label: 'report.json', path: join(out, 'report.json') },
                { label: 'report.md', path: join(out, 'report.md') },
                { label: 'board-report.md', path: join(out, 'board-report.md') },
                { label: 'live-evidence.json', path: join(out, 'live-evidence.json') },
            ]);
        },
        timeoutMs: REVIEW_EVIDENCE_TIMEOUT_MS,
    }));
    ctx.tools.register(defineTool({
        name: 'boardwise_triage_batch',
        description: 'Apply a whole batch of warning verdicts to an existing `checkup` report in one atomic step. Each entry is ' +
            'exactly {key, verdict, reason}; the plugin writes the versioned batch ' +
            '`{schema: "boardwise.triage-batch/1", entries}` to its own temp file and passes it to ' +
            '`boardwise triage-batch --input ... --json ...`. Python validates the **whole** batch before the first ' +
            'writer: an unknown key, an empty reason, a word outside the vocabulary, a three-word verdict on a slot with ' +
            'no per-item text, or the same key twice refuses everything with exit 2 and leaves every file byte-identical. ' +
            'The plugin makes none of those judgements itself — needs-manual, admissibility and pending counts are ' +
            'Python\'s, and verdict is deliberately not an enum here. On exit 0 the parsed ' +
            '`boardwise.triage-batch-result/1` object is returned and rendered as complete pretty JSON; exit 0 means the ' +
            'batch was applied, not that the board passed (the report\'s own gate is quoted, never re-decided). ' +
            'Exit 2 = unusable input or output path; 3 = no report.json to triage. An invalid batch or preflight ' +
            'failure writes nothing; a later JSON-output I/O failure can leave the report/sidecar already written and ' +
            'follows the CLI\'s own disclosure.',
        parameters: {
            out: {
                type: 'string',
                required: true,
                description: 'The `checkup --out` directory holding report.json (the verdicts are written into that report).',
            },
            entries: {
                type: 'array',
                required: true,
                items: {
                    type: 'object',
                    additionalProperties: false,
                    properties: {
                        key: { type: 'string', required: true, description: 'The warning slot key from the report.' },
                        verdict: {
                            type: 'string',
                            required: true,
                            description: 'The judgement word, exactly as the Python side spells it (including needs-manual). ' +
                                'Not an enum here: admissibility is decided by the CLI.',
                        },
                        reason: {
                            type: 'string',
                            required: true,
                            description: 'Why that verdict. Written verbatim to the batch; Python trims and validates it.',
                        },
                    },
                },
                description: 'The batch rows. Empty is not refused here — the CLI decides and exits 2.',
            },
        },
        output: STRUCTURED_OUTPUT,
        execute: async (args, exec) => {
            const tool = 'boardwise_triage_batch';
            const out = requireOut(tool, text(args.out));
            const dir = await transportDir(tool);
            const inputPath = join(dir, 'triage-batch.json');
            const resultPath = join(dir, 'triage-batch-result.json');
            // UTF-8 and the entries as given: Python owns trimming, validation and
            // the atomic whole-batch refusal. Nothing is pre-judged here.
            const batch = { schema: TRIAGE_BATCH_SCHEMA, entries: args.entries };
            try {
                await writeFile(inputPath, `${JSON.stringify(batch, null, 2)}\n`, 'utf8');
            }
            catch (error) {
                throw new Error(`${tool}: cannot write the batch input ${inputPath}: ${error.message}`);
            }
            const argv = ['triage-batch', '--out', out, '--input', inputPath, '--json', resultPath];
            const result = await runStructuredCli(tool, argv, TRIAGE_BATCH_TIMEOUT_MS, exec, resultPath);
            requireField(tool, result, 'schema', TRIAGE_BATCH_RESULT_SCHEMA);
            const applied = result['applied'];
            if (!Array.isArray(applied)) {
                throw new Error(`${tool}: the --json result has no \`applied\` array (read ${describeValue(applied)}); ` +
                    'refusing to report a batch that cannot name what it applied.');
            }
            return result;
        },
        timeoutMs: TRIAGE_BATCH_TIMEOUT_MS,
    }));
    // 537D3a: the eighth tool, appended after triage_batch. It also registers the
    // host-only `boardwiseReviewFinalized` Session projection this tool writes to
    // and the delivery gate (537D3b) reads.
    registerReviewFinalize(ctx);
    // 537D3b: mount the `present` gate on the root context. It stays optional for
    // the older light fake contexts (no `fs` / `workingDirectory`), while the
    // plugin's production `inject` above guarantees every service it needs.
    registerReviewDelivery(ctx);
}
/** Create the plugin's own temp directory for one `--json` transport file. */
async function transportDir(tool) {
    try {
        return await mkdtemp(join(tmpdir(), TRANSPORT_DIR_PREFIX));
    }
    catch (error) {
        throw new Error(`${tool}: cannot create a private temp directory: ${error.message}`);
    }
}
/** A repeated flag's values: strings only, trimmed, empty entries ignored. */
function stringList(value) {
    if (!Array.isArray(value))
        return [];
    return value.map(item => text(item)).filter(item => item !== '');
}
/** Transport check: one envelope field must be exactly the expected string. */
function requireField(tool, value, field, expected) {
    const actual = value[field];
    if (actual !== expected) {
        throw new Error(`${tool}: the --json result has ${field} ${describeValue(actual)}, not ${JSON.stringify(expected)}; ` +
            'the file is not the answer this call asked for.');
    }
}
/** Transport check: one envelope field must be an object. */
function requireObjectField(tool, value, field) {
    const actual = value[field];
    if (actual === null || typeof actual !== 'object' || Array.isArray(actual)) {
        throw new Error(`${tool}: the --json result has no \`${field}\` object (read ${describeValue(actual)}); ` +
            'refusing to report an envelope without it.');
    }
}
/** Transport check: one envelope field must be present (any JSON value). */
function requirePresentField(tool, value, field) {
    if (!(field in value)) {
        throw new Error(`${tool}: the --json result has no \`${field}\` field; refusing to report a partial envelope.`);
    }
}
/** Refuse a path boardwise could only fail on, before anything is spawned. */
function requireExistingFile(tool, file) {
    if (file === '')
        throw new Error(`${tool}: file is required (a .epro2 / .enet export to read)`);
    if (!existsSync(file)) {
        throw new Error(`${tool}: file not found: ${file} (paths are read as given, relative to the plugin's working directory)`);
    }
    return file;
}
/**
 * Params are passed to the CLI verbatim; only the JSON syntax is checked here,
 * so a typo comes back as an argument error instead of a daemon round-trip.
 */
function requireJsonObject(tool, params) {
    if (params === '')
        throw new Error(`${tool}: params is required — a JSON object literal, e.g. "{}"`);
    let parsed;
    try {
        parsed = JSON.parse(params);
    }
    catch (error) {
        throw new Error(`${tool}: params is not valid JSON (${error.message}); expected an object literal, e.g. "{}"`);
    }
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error(`${tool}: params must be a JSON object literal, e.g. "{}" or {"project":"test"}`);
    }
    return params;
}
async function ensureDirectory(tool, dir) {
    try {
        await mkdir(dir, { recursive: true });
    }
    catch (error) {
        throw new Error(`${tool}: cannot create directory ${dir}: ${error.message}`);
    }
}
