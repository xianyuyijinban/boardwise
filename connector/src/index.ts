/**
 * Extension entry point: wires the transport to the action handlers and
 * exposes the menu commands declared in `extension.json`.
 *
 * `registerFn` entries in the manifest are looked up by name on this module's
 * exports, so the command functions below must keep their exported names.
 *
 * Nothing here touches the editor API directly. Everything goes through the
 * `facade` from `facade.ts` — the single place allowed to reach for the host
 * global, and the reason the production wiring is now testable at all. Before
 * 0.2.0 this file was the one code path no test could reach, and it was
 * therefore the one that broke twice (see `tests/source-guard.test.mjs`).
 */

import {
  DEFAULT_URL,
  describeStoredToken,
  ensureConnectorToken,
  resolveConfig,
  STORAGE_KEYS,
  type ResolvedConfig,
} from './config';
import { createFacade, hasHost, type EditorFacade } from './facade';
import { describeRandom } from './random';
import { buildHandlers, currentProjectIdentity, currentResponseContext } from './actions';
import { ActionError } from './protocol';
import { Transport, type TransportState } from './transport';
import { VERSION, isVersionOlder } from './version';

let transport: Transport | undefined;
let facade: EditorFacade | undefined;

/**
 * When this module was evaluated.
 *
 * Shown in `About…` for one reason: if the editor evaluates the bundle twice, the
 * menu closures and the activation callback can end up in different instances,
 * and this timestamp is what makes that visible instead of baffling.
 */
const MODULE_LOADED_AT = new Date().toISOString();

/**
 * This extension instance's id, generated once per module evaluation (018 §A).
 *
 * What it is for: two editor windows each running a connector used to take
 * turns in the daemon's single "active connector" slot every few minutes, and a
 * write could then land in the project of the *other* window. The daemon now
 * refuses a second *live* instance, which means it has to be told when "the
 * same instance" reconnects and when a genuinely different one appears — the
 * two cases get opposite answers.
 *
 * So it is generated here, at module load, and **not** per connection: the
 * transport's reconnect loop (and a menu's `reconnect`) is the same editor
 * instance coming back, while a fresh editor process — or a reloaded extension
 * bundle — is a new one. Random rather than derived from the editor, because
 * the editor exposes nothing to derive it from; it is an identifier, not a
 * secret, and never goes into a message the user reads.
 */
const INSTANCE_ID = newInstanceId();

/** `inst-<HHMMSSmmm>-<8 random base36 chars>` — readable in an audit log. */
function newInstanceId(): string {
  const stamp = MODULE_LOADED_AT.slice(11, 23).replace(/[^0-9]/g, '');
  const random = Math.random().toString(36).slice(2, 10);
  return `inst-${stamp}-${random}`;
}

let status: {
  state: TransportState;
  detail?: string;
  lastError?: string;
  /** What the daemon said about this pairing, from the `hello` answer. */
  paired?: boolean;
  fingerprint?: string;
  /**
   * The oldest connector build the daemon accepts, from the `hello` answer.
   *
   * Only set when the daemon actually sent it: a daemon that predates the
   * field says nothing, and "nothing" must not be rendered as "you are up to
   * date" (018 §B3).
   */
  minConnectorVersion?: string;
  /** Set only when {@link VERSION} is *older* than `minConnectorVersion`. */
  connectorOutdated?: boolean;
} = { state: 'idle' };

/**
 * Whether the editor ever called us, and how it went.
 *
 * `About…` reports this first, because "there is no token" has two very
 * different causes that are otherwise indistinguishable from the outside:
 * nobody ever tried to make one, or the attempt failed. 0.2.1 shipped without
 * this and spent a round trip chasing the wrong one of the two.
 */
let activation: { at: string; outcome: 'running' | 'ok' | 'failed'; error?: string } | undefined;

/**
 * Whether a connection attempt has been started — by the module bootstrap,
 * `activate()`, or the self-arm. First caller wins; the second is a no-op.
 *
 * Without this, an editor that calls `activate()` after the bootstrap already
 * connected would open a second socket to the same daemon.
 */
let connectionAttempted = false;

/**
 * What the self-arm did, kept apart from {@link activation} on purpose.
 *
 * `activation` answers "did the editor call us", and the answer stays
 * `NEVER RAN` even when we connected anyway — that is the honest answer, and the
 * one that tells the user their editor's activation event did not fire. This
 * second record answers the follow-up: "so what did we do about it".
 */
let selfArm: { at: string; outcome: 'running' | 'ok' | 'failed'; error?: string } | undefined;

/**
 * What the fallback paths tried and what they found, in order.
 *
 * 0.2.3 shipped probes that returned silently when the editor global was not
 * reachable — and on the machine, something then swallowed them without a
 * trace: `About…` 13 s after load showed a bare `NEVER RAN` with no self-arm
 * record at all. A fallback that cannot say whether it ran is not observable,
 * which is the exact mistake 0.2.2 was made to fix. Every fallback outcome
 * lands here, and `About…` prints it when we never managed to arm.
 */
let armNotes: string[] = [];

/** The in-flight arm attempt, so a test (or a second caller) can await it. */
let armPromise: Promise<void> | undefined;

/**
 * How long the bootstrap waits between retries, in order.
 *
 * 004f item 3 (P0): "restart the editor and it does not connect, and neither
 * the About menu nor anything else recovers it — only another editor restart
 * does". Two defects in this file can produce exactly that, and both are
 * silent, so the first job of this list is to make the failure *observable*;
 * the second is to give `eda` a chance to appear.
 *
 * Why a timer is legitimate here when 0.2.3's 1s/4s probes were not: those
 * probes never ran because **the bundle was not loaded at startup at all**
 * (004d, fixed fact 2) — a timer that never gets scheduled proves nothing about
 * timers. What is measured is the opposite: a connection chain started during
 * module evaluation sustained a 48-minute reconnect loop, 274 audited connects,
 * on its own. The module-evaluation context is long-lived, and this is the only
 * context that is.
 *
 * Bounded on purpose: this is a startup nudge, not a reconnect policy. The
 * transport's own backoff loop takes over the moment a socket exists.
 */
const BOOTSTRAP_RETRY_DELAYS_MS = [250, 750, 1500, 3000, 5000, 8000, 10000];

let bootstrapRetries = 0;
let bootstrapTimer: ReturnType<typeof setTimeout> | undefined;

/** A rejected promise here is invisible in the editor, so always render it. */
function describeError(error: unknown): string {
  if (error && typeof error === 'object' && 'name' in error) {
    const name = String((error as { name: unknown }).name);
    const message = 'message' in error ? String((error as { message: unknown }).message) : '';
    return message ? `${name}: ${message}` : name;
  }
  return String(error);
}

/**
 * The facade, built on first use rather than at import time.
 *
 * Lazy on purpose: the host global is bound by the editor, and reading it
 * during module evaluation would be a bet that it is already there — the same
 * class of assumption that produced the zero-TCP bug. `activate()` is the
 * editor telling us it is ready.
 */
function host(): EditorFacade {
  if (!facade) facade = createFacade();
  return facade;
}

/**
 * Test seam: install a facade, or clear it.
 *
 * Exported so the wiring in this file can be driven with a stand-in host — the
 * gap that let `globalThis.eda` ship twice. Not referenced by `extension.json`
 * and not part of the editor's API.
 */
export function __setFacadeForTests(next: EditorFacade | undefined): void {
  facade = next;
  transport?.stop();
  transport = undefined;
  // Tests drive activation explicitly, so any background connect is a race
  // waiting to happen: it could fire between a test's `about()` and its
  // `activate()` and change what the box says. Reset the gate for good.
  armNotes = [];
  armPromise = undefined;
  connectionAttempted = false;
  if (next === undefined) {
    // Teardown only. A pending bootstrap retry belongs to the run that
    // scheduled it, so it is cancelled here — but installing a stand-in host
    // mid-run must NOT cancel it, because "the editor becomes reachable a
    // moment later" is exactly the case the retry exists for and the case the
    // test drives.
    if (bootstrapTimer) clearTimeout(bootstrapTimer);
    bootstrapTimer = undefined;
    bootstrapRetries = 0;
    // Clearing the stand-in returns the module to its pre-activation state, so
    // one test's activation cannot bleed into the next one's `About…` box.
    status = { state: 'idle' };
    activation = undefined;
    selfArm = undefined;
  }
}

/**
 * Write one diagnostic line to both sinks.
 *
 * `console.log` is a black hole inside the editor — the log panel
 * (`eda.sys_Log`) is the only window the user can actually read, which is why
 * the reference connector writes there too. Task 004b is the reason this
 * exists: the handshake failed and every line explaining why went to a place
 * nobody could see.
 *
 * Never pass a token or any part of one: this text is shown in the UI and
 * exported by the log panel's own export function.
 */
function logLine(message: string): void {
  const line = `[boardwise] ${message}`;
  try {
    console.log(line);
  } catch {
    /* console may be unavailable */
  }
  facade?.log(line);
}

function config(): ResolvedConfig {
  return resolveConfig(facade?.storage);
}

/** Build a transport from the current config, wired to the editor. */
function buildTransport(current: ResolvedConfig): Transport {
  return new Transport({
    url: current.url,
    token: current.token,
    // Passed in explicitly. Do NOT move this lookup into the transport: bare
    // `eda` resolves in this context, `globalThis.eda` does not.
    socket: host().websocket,
    client: `boardwise-connector/${host().editorVersion() || 'unknown'}`,
    // Announced in `hello` so the daemon's audit log can answer "which build
    // was running?" after the fact — the question a sideload that silently did
    // not take leaves behind (004f item 5).
    connectorVersion: VERSION,
    // Told apart from the other editor windows (018 §A) — see INSTANCE_ID.
    instanceId: INSTANCE_ID,
    // Which project *this window* has open, read at handshake time (021 §2.3).
    // The daemon cannot ask: `eda` is window-scoped, so the only way it learns
    // about the other editor windows is each one saying so as it connects.
    projectIdentity: () => currentProjectIdentity(host().api as Record<string, any>),
    // Where this window is *now*, attached to every response frame (023). The
    // handshake's identity is the connection's starting point; this is what
    // keeps the daemon's routing current once the user switches document, so
    // the two readings come from the same two shared readers.
    responseContext: () => currentResponseContext(host().api as Record<string, any>),
    onRequest: async (action, params) => {
      const handlers = buildHandlers(host().api as Record<string, any>);
      const handler = handlers[action];
      if (!handler) {
        throw new ActionError('UNKNOWN_ACTION', `connector has no handler for ${action}`, {
          action,
          implemented: Object.keys(handlers),
        });
      }
      return await handler(params);
    },
    onStatus: (state, detail) => {
      status = { ...status, state, detail };
      if (state === 'connected') host().notify('boardwise: connected');
      if (state === 'reconnecting') status.lastError = detail;
    },
    onHelloResponse: (data) => {
      status = {
        ...status,
        paired: Boolean(data.paired),
        fingerprint: typeof data.fingerprint === 'string' ? data.fingerprint : undefined,
      };
      // The fingerprint goes in the log so the value the user reads in the
      // editor can be compared with `boardwise bridge status` on the daemon
      // side. It is derived from the token and cannot be turned back into it.
      logLine(
        status.fingerprint
          ? `paired with the daemon, fingerprint ${status.fingerprint}`
          : 'connected to the daemon, not paired yet',
      );
      checkMinimumVersion(data.minConnectorVersion);
    },
    onLog: (message) => logLine(message),
  });
}

/**
 * Compare this build against the daemon's `minConnectorVersion` (018 §B3).
 *
 * A toast rather than a refusal, because the daemon is still answering: the
 * minimum is a warning sign, not a gate. What it replaces is silence — a
 * version skew otherwise looks like an action that mysteriously misbehaves,
 * and the user has no way to learn that their extension is the old half.
 *
 * Nothing at all happens when the field is missing: a daemon that does not
 * state a minimum has not said this build is too old, and rendering its
 * absence as "up to date" (or as a warning) would be inventing a fact — the
 * rule the About box already follows for absent fields. The reading is
 * *cleared* in that case too, so a value seen on one daemon cannot outlive the
 * connection that produced it.
 */
function checkMinimumVersion(minimum: unknown): void {
  const wanted = typeof minimum === 'string' ? minimum.trim() : '';
  if (!wanted) {
    status = { ...status, minConnectorVersion: undefined, connectorOutdated: undefined };
    return;
  }
  status = { ...status, minConnectorVersion: wanted };
  const older = isVersionOlder(VERSION, wanted);
  if (older === null) {
    // One side is not a version — `'unknown'` from a bundle built without the
    // define, most likely. Recorded, never acted on: a comparison that cannot
    // be made is not a verdict, and guessing here is how "which build is
    // running" became a round trip twice already.
    logLine(
      `daemon asks for connector >= ${wanted}; this build reports ${VERSION}, `
        + 'so the two cannot be compared',
    );
    return;
  }
  if (!older) {
    status = { ...status, connectorOutdated: false };
    logLine(`connector ${VERSION} satisfies the daemon's minimum ${wanted}`);
    return;
  }
  status = { ...status, connectorOutdated: true };
  logLine(`connector ${VERSION} is older than the daemon's minimum ${wanted} — update the extension`);
  host().notify(
    `boardwise: connector ${VERSION} is older than the daemon's minimum ${wanted} — update the extension`,
  );
}

/** Resolve a config with a token in it, generating one on first use. */
async function connectableConfig(): Promise<ResolvedConfig> {
  const current = await ensureConnectorToken(host().storage, host().random);
  if (!current.token) {
    // 0.2.0 hit this and said only "the editor has no crypto.getRandomValues",
    // which was a guess dressed as a fact. The diagnosis now comes from
    // `random.ts`, so the log panel names what this host actually offered
    // (`crypto=unavailable`, `getRandomValues=undefined`, …).
    logLine(`cannot generate a token — ${current.tokenNote ?? 'no usable random source'}`);
    logLine(
      'the daemon refuses an empty token (docs/bridge.md §3.4), so pairing cannot proceed',
    );
    host().notify('boardwise: cannot create a connector token — see the log panel');
  } else if (current.tokenSource === 'generated-weak') {
    // Never silent. A weak token that works is still something the user is
    // entitled to know about, and it is the reason `About…` reports a source.
    logLine(
      `generated a token with Math.random — ${current.tokenNote ?? 'no Web Crypto'}; ` +
        'usable on loopback, but not a CSPRNG (docs/bridge.md §9)',
    );
  }
  return current;
}

/** Called by the editor when the extension activates. */
export async function activate(_status?: unknown, _arg?: unknown): Promise<void> {
  activation = { at: new Date().toISOString(), outcome: 'running' };
  try {
    await connectOnce();
    if (activation.outcome === 'running') activation.outcome = 'ok';
  } catch (error) {
    // An unhandled rejection inside an extension host is silent: no toast, no
    // log line, no state — just `state: idle` forever, which is exactly the
    // symptom that cost 0.2.1 a round trip. Never let it be silent again.
    activation = { at: activation.at, outcome: 'failed', error: describeError(error) };
    logLine(`activate FAILED: ${describeError(error)}`);
    host().notify('boardwise: activation failed — see the log panel');
  }
}

/**
 * One-shot claim on the single outbound connection.
 *
 * The module bootstrap, `activate()`, the self-arm and a manual `reconnect()`
 * all want to open the socket; whoever claims first wins and the rest become
 * no-ops. Without the claim, a late `activate()` after the bootstrap connected
 * would build a second transport and orphan the first.
 */
function claimConnectionAttempt(): boolean {
  if (connectionAttempted) return false;
  connectionAttempted = true;
  return true;
}

async function connectOnce(): Promise<void> {
  // `activate()` and the self-arm both route through here, and only one of them
  // should reach the editor's socket. See `claimConnectionAttempt`.
  if (!claimConnectionAttempt()) return;
  // Defensive: a manual reconnect may have left one behind. Two sockets to the
  // same daemon is never what anyone wants.
  transport?.stop();
  transport = undefined;
  facade = facade ?? createFacade();
  const current = config();
  // First line in the log panel: what this extension resolved. No token value,
  // only where it came from. Neutral verb on purpose — since 0.2.5 this runs
  // from the module bootstrap, not only from `activate()`.
  logLine(
    `connect: url=${current.url} token=${current.tokenSource}` +
      ` autoConnect=${current.autoConnect}`,
  );
  if (!current.autoConnect) {
    status = { state: 'idle', detail: 'auto-connect is off' };
    logLine('auto-connect is off; use the Reconnect menu item');
    return;
  }
  transport = buildTransport(await connectableConfig());
  await transport.start();
}

/** Called by the editor when the extension deactivates. */
export function deactivate(): void {
  transport?.stop();
  transport = undefined;
  status = { state: 'stopped' };
}

/** Menu: Reconnect */
export async function reconnect(): Promise<void> {
  // A manual connect is an attempt too: the self-arm must not pile a second
  // socket on top of this one afterwards.
  claimConnectionAttempt();
  transport?.stop();
  const current = await connectableConfig();
  transport = buildTransport(current);
  logLine(`manual reconnect to ${current.url} (token ${current.tokenSource})`);
  await transport.start();
  host().notify(`boardwise: reconnecting to ${current.url}`);
}

/** Menu: Stop */
export function stopConnection(): void {
  transport?.stop();
  status = { ...status, state: 'stopped', detail: 'stopped from the menu' };
  host().notify('boardwise: stopped');
}

/** Menu: Toggle auto-connect */
export async function toggleAutoConnect(): Promise<void> {
  const store = host().storage;
  const current = store?.getExtensionUserConfig(STORAGE_KEYS.autoConnect) !== false;
  await store?.setExtensionUserConfig(STORAGE_KEYS.autoConnect, !current);
  host().notify(`boardwise: auto-connect ${!current ? 'enabled' : 'disabled'}`);
}

/**
 * Menu: Re-pair on next connect
 *
 * Forgets this editor's token, then reconnects — which generates a fresh one
 * and offers it to the daemon. The daemon has to be willing to pair again
 * (`boardwise bridge revoke` on the host), otherwise it refuses: that is the
 * point of pairing, and pretending otherwise would be a lie in the UI.
 */
export async function rePair(): Promise<void> {
  transport?.stop();
  try {
    await host().storage?.setExtensionUserConfig(STORAGE_KEYS.token, '');
  } catch {
    /* storage refused; the reconnect below will re-pair with the old token */
  }
  logLine('re-pair: dropped the stored token; a new one will be offered');
  host().notify('boardwise: re-pairing — run "boardwise bridge revoke" on the daemon host first');
  await reconnect();
}

/** Menu: About… — also the quickest way to see why nothing connects. */
export function about(): void {
  // Create the facade BEFORE resolving the config. 0.2.3 resolved the config
  // through `facade?.storage` while nothing had created the facade yet, so
  // `token:` said NONE while `storage:` — evaluated later, through `host()` —
  // showed the very token. One box, two store views; on the machine that
  // contradiction was read as a half-written store (§10.19) when the observer
  // was the bug. The two lines must always describe the same store.
  const h = host();
  let current: ResolvedConfig;
  try {
    current = resolveConfig(h.storage);
  } catch (error) {
    // This box is the only diagnostic the user has. It must never be the thing
    // that fails — a throwing `sys_Storage` would otherwise hide everything.
    current = {
      url: DEFAULT_URL,
      token: '',
      tokenSource: 'missing',
      tokenNote: `reading the config threw: ${describeError(error)}`,
      autoConnect: true,
    };
  }

  const pairing = status.fingerprint
    ? `paired with the daemon (fingerprint ${status.fingerprint})`
    : status.paired === false
      ? 'REFUSED — the daemon holds a different pairing; run "boardwise bridge revoke"'
      : 'not connected yet';
  const lines = [
    // First thing in the box: *which build is this*? On 2026-09-14 a sideload
    // that did not take was indistinguishable from one that did, and the only
    // symptom was a stack pointing at a line that had already been fixed.
    `boardwise connector ${VERSION}`,
    // Second, because "no token" is ambiguous without it: never tried vs. failed.
    `activation: ${activationLine()}`,
    `loaded: ${MODULE_LOADED_AT.slice(11, 19)}`,
    `state: ${status.state}${status.detail ? ` (${status.detail})` : ''}`,
    `storage: ${storageLine()}`,
    `url: ${current.url}`,
    // The token itself is never shown, here or anywhere else.
    `token: ${tokenLine(current)}`,
    `pairing: ${pairing}`,
    // Only when the daemon actually stated a minimum (018 §B3): an absent
    // field means "no minimum", and a line about it would read as a verdict.
    ...(status.minConnectorVersion
      ? [
          status.connectorOutdated
            ? `upgrade needed: the daemon accepts connector >= ${status.minConnectorVersion}, this build is ${VERSION}`
            : `connector version: ok (the daemon accepts >= ${status.minConnectorVersion})`,
        ]
      : []),
    `auto-connect: ${current.autoConnect ? 'on' : 'off'}`,
  ];
  if (status.lastError) lines.push(`last error: ${status.lastError}`);
  // Shown only while we are *not* connected: a note that explains a failure is
  // noise once the connection is up — the bootstrap may have knocked a few
  // times before `eda` appeared, and that history is not the answer to "why am
  // I not connected".
  if (armNotes.length > 0 && !selfArm && status.state !== 'connected') {
    lines.push(`self-arm: ${armNotes.join('; ')}`);
  }
  host().alert(lines.join('\n'), 'About boardwise');
  // Redundant safety net, kept on purpose (004d): the primary path is the
  // module bootstrap, which every evaluation — including this one — already
  // ran, so this is a no-op unless that bootstrap skipped for lack of an editor
  // global and one became reachable since. Fired AFTER the box is built, so
  // what the user reads is the honest pre-arm snapshot.
  void selfArmNow('About menu');
}

/**
 * Did the editor call `activate()`?
 *
 * Menus keep working even when activation never ran — the module is loaded for
 * them either way — so the extension looks healthy while doing nothing at all.
 * `activationEvents.onStartupFinished` fires at *editor* start; reloading the
 * extension on its own may not re-trigger it.
 */
function activationLine(): string {
  if (!activation) {
    // The editor never called us. If the self-arm picked it up, say so — the
    // user should know their editor's activation event did not fire, and that
    // the extension is nonetheless working.
    if (selfArm) {
      const armed = selfArm.at.slice(11, 19);
      if (selfArm.outcome === 'failed') {
        return `NEVER RAN — self-arm FAILED at ${armed}: ${selfArm.error}`;
      }
      if (selfArm.outcome === 'running') return `NEVER RAN — self-arm running since ${armed}`;
      return `NEVER RAN — self-connected at ${armed}`;
    }
    // Nothing armed and nothing attempted. If the probes tried and missed, say
    // so — that is the difference between "the editor forgot us" and "our own
    // fallback could not see the editor either", and 0.2.3 could not tell them
    // apart, which is why this line exists.
    if (armNotes.length > 0) {
      return `NEVER RAN — the editor has not called activate(); self-arm: ${armNotes.join('; ')}`;
    }
    return 'NEVER RAN — the editor has not called activate() since load; try a full editor restart';
  }
  const time = activation.at.slice(11, 19);
  if (activation.outcome === 'failed') return `${time} FAILED — ${activation.error}`;
  return `${time} ${activation.outcome}`;
}

/** Can we read the store the token lives in? The type docs warn these throw. */
function storageLine(): string {
  const store = host().storage;
  if (!store) return 'unavailable — the editor exposed no eda.sys_Storage';
  try {
    // Summarised, never shown: this value is the secret.
    const raw = store.getExtensionUserConfig(STORAGE_KEYS.token);
    return `readable (token=${describeStoredToken(raw)})`;
  } catch (error) {
    return `read FAILED — ${describeError(error)}`;
  }
}

function tokenLine(current: ResolvedConfig): string {
  if (current.tokenSource === 'missing') {
    // Say *why*: the whole reason 0.2.1 exists is that this line used to be
    // unexplained. Prefer the diagnosis from the last generation attempt; if
    // About… was opened before any attempt, ask the facade's host directly —
    // not the ambient realm, which is the stand-in during tests.
    const why = current.tokenNote ?? describeRandom(host().random);
    return `NONE — this editor cannot generate one (${why})`;
  }
  if (current.tokenSource === 'generated-weak') {
    return `Math.random — NOT a CSPRNG — ${current.token.length} characters (never displayed)`;
  }
  return `${current.tokenSource}, ${current.token.length} characters (never displayed)`;
}

/**
 * The menu safety net: connect from a menu click if nothing else has.
 *
 * Since 0.2.5 the primary path is the module bootstrap, which every evaluation
 * runs — including the evaluation a menu click triggers — so this is expected
 * to be a no-op. It exists for the one case the bootstrap cannot cover: the
 * editor global was not bound at evaluation time (the bootstrap logs that and
 * stands down), and a menu click proves the editor is here after all.
 *
 * Deliberately loud. This is a workaround for host behaviour we do not control,
 * and quiet coverage would hide the underlying problem: the log panel names it,
 * and `About…` reports `self-connected` beside the `NEVER RAN`.
 */
function selfArmNow(trigger: string, hostPresent?: boolean): Promise<void> | undefined {
  if (activation) return undefined; // the editor did call us; nothing to arm
  if (selfArm) return undefined; // already armed, successfully or not
  // "Is there an editor?" defaults to a live check — the facade counts (a test
  // installed one, or something already used it), else the ambient global. Not
  // cached on purpose: the answer may change between probes.
  const present = hostPresent ?? (Boolean(facade) || hasHost());
  if (!present) {
    // 0.2.3 returned silently here, and on the machine the probes then
    // vanished without a trace. Never again: every miss is recorded and shown.
    const note = `${trigger}: editor global not reachable`;
    armNotes.push(note);
    logLine(`self-arm ${note}`);
    return undefined;
  }
  selfArm = { at: new Date().toISOString(), outcome: 'running' };
  logLine(`activate() was not called; connecting anyway (self-arm via ${trigger})`);
  armPromise = connectOnce()
    .then(() => {
      if (transport) {
        if (selfArm?.outcome === 'running') selfArm = { at: selfArm.at, outcome: 'ok' };
        return;
      }
      // The arm ran but opened no socket — `auto-connect is off` is the only
      // way `connectOnce` returns without one. `About…` must not claim a
      // connection that was never made, and the claim must be released so a
      // later menu click can arm again after the setting changes.
      armNotes.push('arm stood down: auto-connect is off');
      selfArm = undefined;
      connectionAttempted = false;
    })
    .catch((error) => {
      // Same reasoning as in `activate()`: a rejection inside the extension host
      // is completely invisible unless something renders it.
      selfArm = {
        at: selfArm?.at ?? new Date().toISOString(),
        outcome: 'failed',
        error: describeError(error),
      };
      logLine(`self-arm connect FAILED: ${describeError(error)}`);
      host().notify('boardwise: activation failed — see the log panel');
    });
  return armPromise;
}

/**
 * The primary connect path: run once, synchronously, at module evaluation.
 *
 * 004d measured the host's lifecycle rules the hard way (2026-09-13, new daemon,
 * no stale-code confound):
 *
 * - a connection chain initiated during the module's synchronous evaluation
 *   **survives** — one 0.2.x instance's chain sustained a 48-minute reconnect
 *   loop on its own (274 audited connects);
 * - chains initiated *later* do not: the `+1s`/`+4s` self-arm timers never left
 *   a trace, and a menu click's `void selfArmNow()` chain produced zero TCP —
 *   each menu click re-evaluates the bundle (`loaded:` changes every time) and
 *   that context dies before its async work runs.
 *
 * So the connect starts here, in the only window measured to work, instead of
 * waiting for `activate()` (which the host may never call) or a timer (which
 * the host may discard). `activate()` remains a supported trigger via the same
 * gate; whatever gets there first wins.
 *
 * Re-evaluations are the reason for the claim gate: every menu click evaluates
 * this module again, and each copy would happily open its own socket. Within
 * one copy the gate is enough; across copies the deterministic first socket id
 * (`boardwise-1`) means the editor sees a re-registration of the connection it
 * already has, not a second one. Node (the test suite) has no editor, so the
 * guard keeps import side-effect-free there.
 */
function bootstrapAtModuleLoad(): Promise<void> | undefined {
  if (!facade && !hasHost()) {
    // No editor bound at evaluation time. Say so in the log panel — the one
    // sink that outlives this module instance — rather than vanishing, and
    // knock again: an extension bundle can be evaluated before the host has
    // bound its global, and until 004f that meant standing down for good.
    const note = 'at module load: editor global not bound; connect not attempted';
    armNotes.push(note);
    logLine(`bootstrap ${note}`);
    scheduleBootstrapRetry('editor global not bound');
    return undefined;
  }
  // The `catch` is the fix for the blind spot, not a nicety. `connectOnce()`
  // had already taken the one-shot claim by the time it can reject, so without
  // this an early throw left `activate()`, the self-arm and Reconnect all
  // no-ops for the rest of the editor's life, with nothing in the log panel and
  // nothing in `About…`: a dead extension that looks untouched.
  return connectOnce().catch((error) => {
    connectionAttempted = false; // a failed attempt must not block the next one
    const reason = describeError(error);
    armNotes.push(`bootstrap attempt failed: ${reason}`);
    logLine(`bootstrap FAILED: ${reason}`);
    scheduleBootstrapRetry(reason);
  });
}

/**
 * One more bootstrap try, after {@link BOOTSTRAP_RETRY_DELAYS_MS}.
 *
 * Always records what it did. A fallback that cannot say whether it ran is the
 * mistake 0.2.2 was made to fix, and "the editor restarted and nothing
 * happened" is unanswerable without these lines.
 */
function scheduleBootstrapRetry(reason: string): void {
  if (bootstrapRetries >= BOOTSTRAP_RETRY_DELAYS_MS.length) {
    const note = `bootstrap gave up after ${bootstrapRetries} retry/retries: ${reason}`;
    armNotes.push(note);
    logLine(`bootstrap ${note}`);
    return;
  }
  const delay = BOOTSTRAP_RETRY_DELAYS_MS[bootstrapRetries];
  bootstrapRetries += 1;
  logLine(`bootstrap retry ${bootstrapRetries} in ${delay} ms: ${reason}`);
  bootstrapTimer = setTimeout(() => {
    bootstrapTimer = undefined;
    if (!facade && !hasHost()) {
      scheduleBootstrapRetry('editor global still not bound');
      return;
    }
    void connectOnce().catch((error) => {
      connectionAttempted = false;
      scheduleBootstrapRetry(describeError(error));
    });
  }, delay);
}

// The connect starts here, at evaluation — not in `activate()`, which the host
// may never call, and not in a timer, which the host may discard.
void bootstrapAtModuleLoad();

/** Test seam: run the module-load bootstrap now (Node has no editor at import). */
export function __bootstrapForTests(): Promise<void> {
  return bootstrapAtModuleLoad() ?? armPromise ?? Promise.resolve();
}

/** Test seam: run the menu safety-net arm now, instead of from a menu click. */
export function __selfArmForTests(options?: { hostPresent?: boolean }): Promise<void> {
  return selfArmNow('test', options?.hostPresent) ?? armPromise ?? Promise.resolve();
}

/** Exposed for the manual checklist / smoke test: current connection state. */
export function getStatus(): typeof status {
  return status;
}
