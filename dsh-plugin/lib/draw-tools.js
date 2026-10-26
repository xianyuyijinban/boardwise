/** Offline draw tools (540B7): Python judges, TypeScript transports JSON files. */
import { defineTool } from '@deepseek-ai/dsh-tools';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { OUT_DIR_PREFIX } from './cli.js';
import { STRUCTURED_OUTPUT, describeValue, runStructuredCli, text, } from './transport.js';
import { ensureDirectory, requireArrayField, requireExistingInput, requireField, requireObjectField, requirePresentField, transportDir, } from './tool-utils.js';
const DRAW_COMPILE_TIMEOUT_MS = 600_000;
const DRAW_LINT_TIMEOUT_MS = 120_000;
/** Append the two offline tools after the historical eight; no apply surface. */
export function registerDrawTools(ctx) {
    ctx.tools.register(defineTool({
        name: 'boardwise_draw_compile',
        description: 'Compile one CircuitSpec + PresentationSpec + symbol profile library entirely offline through ' +
            '`boardwise draw compile`. No editor, daemon, live page or apply route is contacted. The CLI writes the ' +
            'result to a private JSON file and this tool returns that whole object unchanged: a single-module ' +
            'presentation answers `candidates` + `failureRounds`, while a page presentation (the CLI marks it ' +
            '`document: "page"`) answers `pages` + `moduleFailureRounds`; both carry `failures`, `categories`, ' +
            '`rejected`, `notes` and the `previews` artifact paths. `ok` and every verdict are Python\'s, never ' +
            'recomputed in TypeScript. Exit 0 (at least one candidate) and exit 5 (a documented compiler refusal) are ' +
            'both transported **when the CLI wrote the JSON file**; a run whose input could not be read exits 5 without ' +
            'writing one, and that is an error — as is an unreadable transport or an unexpected exit. A partial or ' +
            'stdout-derived answer is never returned.',
        parameters: {
            circuit: {
                type: 'string',
                required: true,
                description: 'The CircuitSpec JSON to read (read-only).',
            },
            presentation: {
                type: 'string',
                required: true,
                description: 'The PresentationSpec JSON to read (read-only).',
            },
            profiles: {
                type: 'string',
                required: true,
                description: 'The symbol profile library JSON to read (read-only).',
            },
            pageBox: {
                type: 'string',
                description: 'Optional canvas box X0,Y0,X1,Y1, passed to --page-box without interpretation in TS. ' +
                    'The CLI itself requires one when the presentation describes a page.',
            },
            intent: {
                type: 'string',
                description: 'Optional DesignIntent JSON passed to --intent (read-only).',
            },
            out: {
                type: 'string',
                description: 'Directory for candidate SVG/LayoutPlan artifacts (created if missing). Default: a fresh temp directory.',
            },
        },
        output: STRUCTURED_OUTPUT,
        execute: async (args, exec) => {
            const tool = 'boardwise_draw_compile';
            const circuit = requireExistingInput(tool, 'circuit', text(args.circuit), 'the CircuitSpec JSON');
            const presentation = requireExistingInput(tool, 'presentation', text(args.presentation), 'the PresentationSpec JSON');
            const profiles = requireExistingInput(tool, 'profiles', text(args.profiles), 'the symbol profile JSON');
            const intent = text(args.intent);
            if (intent !== '')
                requireExistingInput(tool, 'intent', intent, 'the DesignIntent JSON');
            const requestedOut = text(args.out);
            const outDir = requestedOut !== '' ? requestedOut : await mkdtemp(join(tmpdir(), OUT_DIR_PREFIX));
            await ensureDirectory(tool, outDir);
            const target = join(await transportDir(tool), 'draw-compile.json');
            const argv = [
                'draw', 'compile',
                '--circuit', circuit,
                '--presentation', presentation,
                '--profiles', profiles,
                '--out', outDir,
                '--json', target,
            ];
            const pageBox = text(args.pageBox);
            if (pageBox !== '')
                argv.push('--page-box', pageBox);
            if (intent !== '')
                argv.push('--intent', intent);
            const result = await runStructuredCli(tool, argv, DRAW_COMPILE_TIMEOUT_MS, exec, target, [0, 5]);
            requireField(tool, result, 'command', 'compile');
            requireBooleanField(tool, result, 'ok');
            // `draw compile` has two payload shapes and Python names which one this is:
            // a page presentation is compiled by the page compiler and answers `pages`
            // (+ `moduleFailureRounds`), a single-module one answers `candidates`
            // (+ `failureRounds`). This is a transport route, not a verdict: `ok` stays
            // exactly as Python wrote it, and the complete object is returned either way.
            if (result['document'] === 'page') {
                requireArrayField(tool, result, 'pages');
            }
            else {
                requireArrayField(tool, result, 'candidates');
            }
            requireArrayField(tool, result, 'failures');
            requireArrayField(tool, result, 'previews');
            return result;
        },
        timeoutMs: DRAW_COMPILE_TIMEOUT_MS,
    }));
    ctx.tools.register(defineTool({
        name: 'boardwise_draw_lint',
        description: 'Replay one captured schematic page offline through `boardwise draw lint --snapshot ... --render ...`. ' +
            'Both inputs are required; bodies= optionally supplies measured part boxes. There is deliberately no page=, ' +
            'project=, instance= or apply parameter, so this tool cannot focus or modify a live design. Python writes ' +
            'the complete findings/counts/thresholds/notes object to a private JSON file and this tool returns it whole. ' +
            'Exit 0 (no ERROR) and exit 1 (ERROR findings) are both lint results and return that JSON; exit 2 is an ' +
            'input/transport error. The tool never derives a finding, severity, verdict or pass from the JSON in TS.',
        parameters: {
            snapshot: {
                type: 'string',
                required: true,
                description: 'Captured sch.geometry JSON to replay offline (read-only).',
            },
            render: {
                type: 'string',
                required: true,
                description: 'The matching captured SVG render used for text geometry (read-only).',
            },
            bodies: {
                type: 'string',
                description: 'Optional measured body boxes JSON passed to --bodies (read-only).',
            },
        },
        output: STRUCTURED_OUTPUT,
        execute: async (args, exec) => {
            const tool = 'boardwise_draw_lint';
            const snapshot = requireExistingInput(tool, 'snapshot', text(args.snapshot), 'the captured geometry JSON');
            const render = requireExistingInput(tool, 'render', text(args.render), 'the captured SVG render');
            const bodies = text(args.bodies);
            if (bodies !== '')
                requireExistingInput(tool, 'bodies', bodies, 'the measured body-box JSON');
            const target = join(await transportDir(tool), 'draw-lint.json');
            const argv = ['draw', 'lint', '--snapshot', snapshot, '--render', render];
            if (bodies !== '')
                argv.push('--bodies', bodies);
            argv.push('--json', target);
            const result = await runStructuredCli(tool, argv, DRAW_LINT_TIMEOUT_MS, exec, target, [0, 1]);
            requireField(tool, result, 'source', 'replay');
            requirePresentField(tool, result, 'page');
            requireArrayField(tool, result, 'findings');
            requireObjectField(tool, result, 'counts');
            requirePresentField(tool, result, 'exitCode');
            requireBooleanField(tool, result, 'textReadable');
            requireArrayField(tool, result, 'notes');
            requireObjectField(tool, result, 'thresholds');
            return result;
        },
        timeoutMs: DRAW_LINT_TIMEOUT_MS,
    }));
}
/** Transport shape only; whether the boolean is true remains Python's answer. */
function requireBooleanField(tool, value, field) {
    const actual = value[field];
    if (typeof actual !== 'boolean') {
        throw new Error(`${tool}: the --json result has \`${field}\` ${describeValue(actual)}, not a boolean; ` +
            'refusing to report a malformed envelope.');
    }
}
