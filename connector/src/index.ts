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
import { createFacade, hasHost, hostObject, type EditorFacade } from './facade';
import { describeRandom } from './random';
import { buildHandlers, currentProjectIdentity, currentResponseContext } from './actions';
import { ActionError } from './protocol';
import {
  Transport,
  getOrCreateSharedRuntime,
  publishSharedRuntimeIfEmpty,
  readSharedRuntime,
  releaseSharedRuntime,
  sharedRuntimeImplementation,
  type TransportState,
} from './transport';
import { VERSION, isVersionOlder } from './version';
import { Watchdog, type WatchdogStatus } from './watchdog';

let transport: Transport | undefined;
let facade: EditorFacade | undefined;

/**
 * The background alarm, one per editor runtime (026b, form A).
 *
 * Owned here because this file owns the connection, and for the same reason the
 * transport is shared through a published record: the editor re-evaluates the
 * bundle on every menu click, so "one Worker per evaluation" would leak a
 * thread per click. A later evaluation reaches the runtime that published this
 * object and never calls this module's own {@link ensureWatchdog} at all — the
 * singleton is a consequence of the shared runtime, not a second guard beside
 * it (`tests/watchdog.test.mjs`, "a fresh evaluation of the bundle adopts the
 * runtime and builds no second alarm", drives exactly that: a fresh evaluation
 * plus a reconnect, and one Worker constructed in total).
 *
 * `undefined` until the first connection attempt: with auto-connect off there
 * is nothing for an alarm to watch, and a Worker started then would only be
 * something else to explain in `About…`.
 */
let watchdog: Watchdog | undefined;

/**
 * When this module was evaluated.
 *
 * Shown in `About…` as `loaded:` — the evaluation that *answers* the box, which
 * since 0.4.13 is the one holding the connection (`about()` goes through
 * `runtime()`). So two boxes in one editor session agree, and a newer value means
 * the runtime was rebuilt rather than that the editor re-evaluated the bundle:
 * that re-evaluation happens on every menu click and is the reason the shared
 * runtime exists at all, while `evaluations` in the same box is what counts it.
 *
 * ISO/UTC deliberately, and not for display: {@link newInstanceId} slices the
 * digits of {@link INSTANCE_ID} out of it and the daemon's audit log reads them,
 * so that format is a contract. What the user reads goes through
 * {@link localClock}.
 */
const MODULE_LOADED_AT = new Date().toISOString();

/**
 * `HH:MM:SS` on the reader's own clock — the form every time in `About…` takes.
 *
 * Local, rather than the UTC digits this box used to slice out of an ISO string:
 * the box is read next to the editor's clock, the daemon's audit log and
 * `boardwise bridge status`, and all three are local. On 2026-09-21 a UTC
 * reading eight hours behind the wall clock is exactly what made a *correct*
 * `loaded: 11:50:21` (19:50:21 in Beijing; the same instant the daemon logged
 * the instance) look like it had come from an earlier editor session.
 *
 * An unparsable stamp answers `'unknown'`, the rule the rest of this box follows
 * for a field that is not there — and the reason the callers below may pass
 * `''` for an unset one.
 */
function localClock(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return 'unknown';
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${pad(at.getHours())}:${pad(at.getMinutes())}:${pad(at.getSeconds())}`;
}

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

// ─── The published controller (024) ───────────────────────────────────

/**
 * Which path asked for the connection.
 *
 * `bootstrap` is the module scope ({@link runBootstrap}); `activate` is the
 * editor's lifecycle callback. Recorded rather than merely logged: on 立创 EDA
 * 3.2.149 `activate` may never arrive, and the counters below are how that is
 * told apart — on the machine, after a restart — from "the bundle was never
 * evaluated at all".
 */
type TransportStartSource = 'activate' | 'bootstrap';

/**
 * What one evaluation of this bundle publishes for the next one to reuse.
 *
 * The members close over the *publishing* evaluation's module state, which is
 * the whole point: the editor re-evaluates the bundle for every menu click, and
 * a copy with its own state would open its own socket. Through this record a
 * later evaluation reaches the controller that owns the connection and the real
 * history, instead of a fresh copy of all three.
 *
 * The record lives on the editor's own per-extension object (`eda`), the one
 * thing that outlives an evaluation — see the registry in `transport.ts` for
 * the mechanics and the version signature that makes it safe.
 */
interface OwnedTransportRuntime {
  readonly implementation: string;
  start(source: TransportStartSource): Promise<void>;
  bootstrapFromModuleLoad(): Promise<void>;
  reconnect(): Promise<void>;
  stop(quiet?: boolean): void;
  selfArm(trigger: string, hostPresent?: boolean): Promise<void> | undefined;
  about(): void;
  getStatus(): ConnectorStatus;
  noteEvaluation(): void;
}

/** This evaluation's view of the shared runtime, and who created it. */
let shared: { runtime: OwnedTransportRuntime; created: boolean; published: boolean } | undefined;

/**
 * Did the module-load bootstrap run in this editor runtime? (024)
 *
 * Reported next to {@link activateObserved}. The pair exists because the
 * failure mode is otherwise invisible: "the host evaluated the bundle but never
 * dispatched `activate()`" is the case the bootstrap rescues, while "the host
 * never evaluated the bundle" cannot be rescued from inside the editor at all —
 * and on 3.2.149 the two look identical from the outside (no menu, no daemon
 * connection, nothing in the log).
 */
let moduleBootstrapObserved = false;
let moduleBootstrapObservedAt: string | undefined;

/** Did the editor dispatch `activate()`? The counter that names the 3.2.149 defect. */
let activateObserved = false;
let activateObservedAt: string | undefined;

/** How many times the editor has evaluated this bundle in this editor runtime. */
let evaluations = 0;

/**
 * The bootstrap's once-per-editor-runtime latch.
 *
 * Per runtime, not per evaluation: `connectOnce` is one-shot anyway, but the
 * latch is what stops a re-evaluation from re-running the bootstrap's own
 * logging and scheduling.
 */
let bootstrappedFromModuleLoad = false;

/** Where the controller is published: the stand-in host in the tests, else `eda`. */
function sharedRuntimeHost(): Record<string, unknown> | undefined {
  // The installed facade comes first on purpose: in the tests the host is a
  // stand-in the ambient global knows nothing about, while in production the
  // facade's `api` *is* `eda`.
  const api = facade?.api ?? hostObject();
  return api && typeof api === 'object' ? (api as Record<string, unknown>) : undefined;
}

/**
 * The controller for this editor runtime: the published one, or a new one.
 *
 * Called from module scope (the bootstrap) and from every exported entry point,
 * so a menu click's evaluation of the bundle reaches the controller that owns
 * the socket instead of building a second one.
 *
 * A *published* record of this build wins over everything, including a
 * controller of ours that was built before the editor's object was reachable
 * (004f's late `eda`): the published one is the one the other evaluations will
 * use, so it has to be the one we use too.
 */
function runtime(): OwnedTransportRuntime {
  const host = sharedRuntimeHost();
  const implementation = sharedRuntimeImplementation(VERSION);
  const published = readSharedRuntime<OwnedTransportRuntime>(host, implementation);
  if (published) {
    if (shared?.runtime === published) {
      // The registry was read late: what is published is what we published.
      shared.published = true;
    } else {
      adoptPublishedRuntime(published);
    }
    return published;
  }
  if (shared) return shared.runtime;
  const lookup = getOrCreateSharedRuntime<OwnedTransportRuntime>(host, implementation, createRuntime);
  shared = { runtime: lookup.runtime, created: lookup.created, published: lookup.published };
  if (lookup.created) {
    // Creating a controller *is* this evaluation, so this is where it is
    // counted. Every later evaluation of the same bundle reaches this record
    // through `adoptPublishedRuntime` and counts itself there; that is what
    // makes "the bundle was evaluated N times in this editor runtime" true
    // rather than a guess.
    evaluations += 1;
  }
  if (!lookup.published) {
    // Honest, and not fatal: the controller works, the hand-off does not.
    logLine(
      'shared runtime: the editor object is not reachable yet — this evaluation owns its controller',
    );
  }
  if (lookup.retired) {
    logLine(`shared runtime: retired the controller published by ${lookup.retired}`);
  }
  return lookup.runtime;
}

/**
 * Take over the controller another evaluation published, retiring ours.
 *
 * Ours never reached the host, but it may already own a socket (it was built
 * while the editor's global was still unbound). Two controllers connected to one
 * daemon is precisely what this mechanism exists to prevent, so the local one is
 * stopped — best-effort, because a controller that cannot stop is still the
 * wrong one to keep.
 */
function adoptPublishedRuntime(published: OwnedTransportRuntime): void {
  const previous = shared?.runtime;
  logLine(`shared runtime: reusing the controller published by ${published.implementation}`);
  if (previous && previous !== published) {
    try {
      previous.stop(true);
    } catch {
      /* best-effort: it is on its way out either way */
    }
  }
  shared = { runtime: published, created: false, published: true };
  // The owner counts evaluations, so a reused record has to be told: this
  // evaluation of the bundle is not the one that created the controller.
  published.noteEvaluation();
}

/**
 * Publish a controller that was built before the editor's object was reachable.
 *
 * The bundle can be evaluated while the host has not bound `eda` yet (measured
 * in 004f). The controller then owns everything but is unpublished — exactly
 * the state a second evaluation cannot see. Publishing it once the host appears
 * is best-effort and never overwrites: something already under the key is
 * another evaluation's controller, and this one then stays local. Both
 * outcomes are logged, so the log panel never has to be guessed at.
 */
function republishSharedRuntime(): void {
  if (!shared || shared.published) return;
  const host = sharedRuntimeHost();
  if (!host) return;
  if (publishSharedRuntimeIfEmpty(host, shared.runtime)) {
    shared.published = true;
    logLine('shared runtime: published now that the editor object is reachable');
  } else {
    logLine('shared runtime: another controller owns the editor object; this one stays local');
  }
}

/** The record this evaluation publishes. Every member closes over this file's state. */
function createRuntime(): OwnedTransportRuntime {
  return {
    implementation: sharedRuntimeImplementation(VERSION),
    start: runStart,
    bootstrapFromModuleLoad: runBootstrap,
    reconnect: runReconnect,
    stop: runStop,
    selfArm: runSelfArm,
    about: runAbout,
    getStatus: readStatus,
    noteEvaluation: () => {
      evaluations += 1;
    },
  };
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
 * What {@link getStatus} answers: the connection state plus the 024 lifecycle
 * counters.
 *
 * The counters ride along on the existing status read-out rather than in a new
 * channel, because that read-out is what every diagnostic surface already uses
 * (`About…` through this module, and the tests). On the machine they are the
 * difference between the two failures described at {@link moduleBootstrapObserved}.
 */
export type ConnectorStatus = typeof status & {
  moduleBootstrapObserved: boolean;
  activateObserved: boolean;
  evaluations: number;
  /** When the bootstrap ran, ISO; absent when it never did. */
  bootstrapAt?: string;
  /** When `activate()` was dispatched, ISO; absent when it never was. */
  activateAt?: string;
  /**
   * What the background alarm is doing (026b), or absent when none was ever
   * built (auto-connect off, or no connection attempt yet).
   *
   * Reported as a reading, never as a promise: `state: 'unavailable'` means
   * this editor refused a Worker, and the connector then has **no** background
   * alarm — which is exactly what `sys.connector_status` exists to say out
   * loud, since the observable difference on the machine is hours of silence.
   */
  watchdog?: WatchdogStatus;
};

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
/** The next-macrotask half of the bootstrap pair; see {@link scheduleNextMacrotaskAttempt}. */
let nextMacrotaskTimer: ReturnType<typeof setTimeout> | undefined;

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
  if (next === undefined && shared) {
    // Teardown: retire the controller this module published. Released *before*
    // the facade is cleared, because the host object it was published on is the
    // one the installed facade points at.
    releaseSharedRuntime(sharedRuntimeHost(), shared.runtime);
    shared = undefined;
  }
  facade = next;
  transport?.stop();
  transport = undefined;
  // The alarm belongs to the run that built it (026b). A Worker left ticking
  // between tests would be a leaked thread *and* a wake arriving in the next
  // test's transport — the same reason the transport is stopped right above.
  watchdog?.stop();
  watchdog = undefined;
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
    if (nextMacrotaskTimer) clearTimeout(nextMacrotaskTimer);
    nextMacrotaskTimer = undefined;
    bootstrapRetries = 0;
    // Clearing the stand-in returns the module to its pre-activation state, so
    // one test's activation cannot bleed into the next one's `About…` box. The
    // 024 lifecycle counters are part of that state: they describe *this*
    // editor runtime, and the next test has a new one.
    status = { state: 'idle' };
    activation = undefined;
    selfArm = undefined;
    moduleBootstrapObserved = false;
    moduleBootstrapObservedAt = undefined;
    activateObserved = false;
    activateObservedAt = undefined;
    evaluations = 0;
    bootstrappedFromModuleLoad = false;
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
  // The facade is created here when the editor is reachable, rather than only
  // from `connectOnce()`: the bootstrap's own lines (which evaluation ran, which
  // controller it found) happen *before* the first connect, and they are exactly
  // the lines that answer "did the host load the bundle at all?" — a question
  // nobody can answer from `console.log` in the editor. No new bet on the host:
  // `hasHost()` already asks the same question one line earlier in the caller.
  if (!facade && hasHost()) facade = createFacade();
  facade?.log(line);
}

function config(): ResolvedConfig {
  return resolveConfig(facade?.storage);
}

/**
 * The alarm for this runtime: the existing one, or a new one (026b §2.1).
 *
 * The `if (watchdog) return watchdog` line is the whole singleton: a manual
 * reconnect, a second connect path, or a re-run of the bootstrap all land here
 * and reuse the Worker that is already ticking. Deleting that line is the leak
 * `tests/watchdog.test.mjs` bites on — "a manual reconnect replaces the socket,
 * never the alarm" and "a fresh evaluation of the bundle adopts the runtime and
 * builds no second alarm" — because every connect would then start another
 * thread that nothing ever terminates.
 *
 * A watchdog that could not be built is kept, not retried: the host's refusal
 * (no `Worker`, a CSP that blocks `blob:`) is a fact about this editor, and
 * `About…` reports it rather than pretending the connector is watched. The
 * connector itself is unaffected — this is a safety net, not a requirement.
 */
function ensureWatchdog(): Watchdog {
  if (watchdog) return watchdog;
  const created = new Watchdog({
    // The transport is looked up at wake time, never captured: a manual
    // reconnect replaces it, and a wake must reach whatever owns the wire now.
    onWake: (info) => {
      transport?.wake(`worker alarm after ${info.silenceMs} ms of page silence`);
    },
    onLog: (message) => logLine(message),
  });
  watchdog = created;
  created.start();
  return created;
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
    // The alarm is told about every sign of life by the transport itself
    // (`noteActivity` at the heartbeat, on inbound traffic, on a connect
    // attempt and on the handshake). One method wide, and read at call time so
    // a watchdog replaced by a later evaluation is reached, not a stale one.
    watchdog: { noteActivity: () => watchdog?.noteActivity() },
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

/**
 * Called by the editor when the extension activates.
 *
 * One of the two start paths since 024 — and on 立创 EDA 3.2.149 not the one
 * that matters, because that host never dispatches this callback for a
 * user-installed extension (the extension pass runs before the user info it is
 * gated on, then is skipped; upstream #219/#221). It stays a supported trigger:
 * whatever gets here first wins, and a late `activate()` finds the connection
 * already made instead of opening a second one.
 */
export async function activate(_status?: unknown, _arg?: unknown): Promise<void> {
  try {
    await runtime().start('activate');
  } catch {
    // Recorded, logged and toasted inside `runStart`; the catch is here so an
    // editor-host rejection never becomes an unhandled rejection, which is
    // completely invisible in an extension host.
  }
}

/**
 * Start the connection, recording which path asked and how it went.
 *
 * The single body behind both paths, so the difference between them is one
 * parameter instead of two code paths that drift: `activate()` claims the
 * one-shot attempt through {@link connectOnce}, and so does the module
 * bootstrap, so a host that dispatches `activate()` long after evaluating the
 * bundle gets the idempotent no-op it needs.
 *
 * Rejects on failure as well as recording it, because the caller's reaction
 * differs: `activate()` has nothing left to do, while the bootstrap schedules
 * the retry that is the whole difference between a dead extension and one that
 * connects when the editor settles.
 */
async function runStart(source: TransportStartSource): Promise<void> {
  if (source === 'activate') {
    // The counters are set before the attempt, not after: "the editor called
    // us" and "the attempt worked" are different facts, and on the machine only
    // the first one tells the 3.2.149 defect apart from a broken connect.
    activateObserved = true;
    activateObservedAt = new Date().toISOString();
    activation = { at: activateObservedAt, outcome: 'running' };
  }
  try {
    await connectOnce();
    if (source === 'activate' && activation?.outcome === 'running') {
      activation = { at: activation.at, outcome: 'ok' };
    }
  } catch (error) {
    if (source === 'activate') {
      // An unhandled rejection inside an extension host is silent: no toast, no
      // log line, no state — just `state: idle` forever, which is exactly the
      // symptom that cost 0.2.1 a round trip. Never let it be silent again.
      activation = {
        at: activation?.at ?? new Date().toISOString(),
        outcome: 'failed',
        error: describeError(error),
      };
      logLine(`activate FAILED: ${describeError(error)}`);
      host().notify('boardwise: activation failed — see the log panel');
    }
    throw error;
  }
}

/**
 * One-shot claim on the single outbound connection.
 *
 * The module bootstrap, `activate()`, the self-arm and a manual `reconnect()`
 * all want to open the socket; whoever claims first wins and the rest become
 * no-ops. Without the claim, a late `activate()` after the bootstrap connected
 * would build a second transport and orphan the first.
 *
 * Since 024 this is the *second* line of defence: the shared runtime means a
 * re-evaluated bundle reaches the controller that already holds the connection
 * instead of owning a claim of its own. This one still matters, because a host
 * that dispatches `activate()` and then a menu click can arrive through two
 * evaluations that both treat the attempt as theirs.
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
  // Reaching this point means the editor is demonstrably here. If the controller
  // was built before the host bound its global (004f), this is the moment it
  // becomes visible to later evaluations — see `republishSharedRuntime`.
  republishSharedRuntime();
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
  // The alarm comes up with the connection, never before it: with auto-connect
  // off there is no socket for it to watch, and `About…` would then have to
  // explain a running Worker that watches nothing (026b §2.2).
  ensureWatchdog();
  transport = buildTransport(await connectableConfig());
  await transport.start();
}

/**
 * Called by the editor when the extension deactivates.
 *
 * Stops the controller *and* un-publishes it (024), so a subsequent extension
 * load installs its own controller instead of inheriting a stopped one.
 */
export function deactivate(): void {
  if (!shared) {
    // Nothing was ever published by this evaluation: stop what it owns
    // locally. A deactivation must leave the module inert either way.
    transport?.stop();
    transport = undefined;
    status = { state: 'stopped' };
    return;
  }
  shared.runtime.stop(true);
  releaseSharedRuntime(sharedRuntimeHost(), shared.runtime);
  shared = undefined;
}

/** Menu: Reconnect */
export async function reconnect(): Promise<void> {
  await runtime().reconnect();
}

/** Menu: Stop */
export function stopConnection(): void {
  runtime().stop();
}

/** The body behind Reconnect: a fresh socket, claimed so nothing doubles it. */
async function runReconnect(): Promise<void> {
  // A manual connect is an attempt too: the self-arm must not pile a second
  // socket on top of this one afterwards.
  claimConnectionAttempt();
  transport?.stop();
  const current = await connectableConfig();
  // The same alarm, not a second one: a manual reconnect replaces the socket,
  // never the Worker (026b §2.1).
  ensureWatchdog();
  transport = buildTransport(current);
  logLine(`manual reconnect to ${current.url} (token ${current.tokenSource})`);
  await transport.start();
  host().notify(`boardwise: reconnecting to ${current.url}`);
}

/**
 * The body behind Stop, and behind deactivation.
 *
 * `quiet` is for deactivation: the editor is taking the extension away, so a
 * toast telling the user their bridge stopped is noise they cannot act on.
 *
 * The alarm goes with the connection (026b §2.1): a Worker left ticking after
 * `stop()` would keep waking a transport that is not there, and "a stopped
 * transport sends nothing, ever" (docs/bridge.md §7) has to stay true of the
 * thread too — so it is terminated, and the next connect builds a fresh one.
 */
function runStop(quiet = false): void {
  transport?.stop();
  transport = undefined;
  watchdog?.stop();
  watchdog = undefined;
  status = {
    ...status,
    state: 'stopped',
    detail: quiet ? 'deactivated' : 'stopped from the menu',
  };
  if (!quiet) host().notify('boardwise: stopped');
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
  // Through the controller, like every other entry point — and that is not a
  // style point. Called directly (as 0.4.12 did) this body runs in the
  // *clicking* evaluation, whose counters have never been written: the box then
  // reports `no/no/0`, `state: idle`, `pairing: not connected yet` and
  // "the module-scope bootstrap never ran in this editor runtime" for a runtime
  // that is connected and answering pings.
  runtime().about();
}

/**
 * The body behind About…, run by the controller that owns the connection (024).
 *
 * Not the clicking evaluation's copy of it: the box is a report on *this editor
 * runtime* — when it was loaded, which path started it, whether the editor ever
 * dispatched `activate()` — and only the owning evaluation has that history.
 *
 * Reached through `runtime().about()` — from {@link about} above, and from the
 * published record's own copy of this function when a later evaluation of the
 * bundle renders the box. Before 0.4.13 the export called this directly instead,
 * so the box was built from whatever evaluation the editor dispatched the click
 * into (see `tests/bootstrap.test.mjs`, "reports the owner, not its own empty
 * copy").
 */
function runAbout(): void {
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
    // Third (024): the same question asked as two counters, because on 立创 EDA
    // 3.2.149 "the editor never called us" and "the editor never even loaded us"
    // are different failures with different answers, and only these tell them
    // apart from inside the editor.
    `lifecycle: moduleBootstrapObserved=${moduleBootstrapObserved ? 'yes' : 'no'}` +
      ` activateObserved=${activateObserved ? 'yes' : 'no'} evaluations=${evaluations}`,
    `bootstrap: ${bootstrapLine()}`,
    `loaded: ${localClock(MODULE_LOADED_AT)}`,
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
    // What keeps this window recoverable while it is in the background (026b).
    // Next to `state:` on purpose: this is the line that explains *why* a
    // background window's state can lag, and the only place a user can see
    // that this editor refused a Worker.
    `watchdog: ${watchdogLine()}`,
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
  void runSelfArm('About menu');
}

/**
 * What the module-load bootstrap did, in one sentence (024).
 *
 * This is the line that decides the next step on the real machine. "The bundle
 * was evaluated and `activate()` was not dispatched" means the bootstrap is
 * doing its job and the only thing missing is the editor's callback. "The
 * bundle was never evaluated before this click" means the host did not load it
 * at all — nothing inside the extension can fix that, and the answer is
 * re-importing at every start or a newer editor.
 */
function bootstrapLine(): string {
  if (!moduleBootstrapObserved) {
    return 'the module-scope bootstrap never ran in this editor runtime';
  }
  const observedAt = localClock(moduleBootstrapObservedAt ?? '');
  if (evaluations <= 1) {
    // The editor re-evaluates the bundle for every menu click (measured on the
    // real editor, see this file's history), so `evaluations=1` reported from a
    // menu item means the startup evaluation never happened and this click is
    // the editor loading us for the first time.
    if (activateObserved) {
      return `the bundle was evaluated once, at ${observedAt}, and activate() was dispatched`;
    }
    return (
      `this is the first evaluation of the bundle in this editor runtime (at ${observedAt}); ` +
      'the host had not loaded the extension before this point'
    );
  }
  if (!activateObserved) {
    return (
      `the bundle was evaluated ${evaluations}× in this editor runtime and activate() was never ` +
      `dispatched — the connection starts from the module load (first seen at ${observedAt})`
    );
  }
  const activatedAt = localClock(activateObservedAt ?? '');
  return (
    `the bundle was evaluated ${evaluations}× in this editor runtime; activate() was dispatched ` +
    `at ${activatedAt}`
  );
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
      const armed = localClock(selfArm.at);
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
  const time = localClock(activation.at);
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
 * Whether a background alarm is watching this window (026b), in the words a
 * user reads.
 *
 * Deliberately narrow, and deliberately *not* a claim about what the alarm
 * achieves: P3 measured that a Worker's clock survives page throttling, but no
 * controlled reproduction of the frozen state exists (026b §一), so the box
 * says who is running — `running` or the host's own refusal — and nothing else.
 * "immunity" is a word this line must never contain.
 */
function watchdogLine(): string {
  if (!watchdog) {
    if (status.state === 'idle' && status.detail === 'auto-connect is off') {
      return 'not started (auto-connect is off)';
    }
    // A stopped connection had an alarm and it was terminated with the socket
    // (`runStop`) — saying "no connection attempt yet" there would be false.
    if (status.state === 'stopped') return 'stopped (the alarm goes with the connection)';
    return 'not started (no connection attempt yet)';
  }
  const report = watchdog.status();
  if (report.state === 'unavailable') {
    return `unavailable(${report.reason ?? 'the host gave no reason'})`;
  }
  if (report.state === 'running') {
    return `running (checks every ${report.checkIntervalMs} ms, wakes after `
      + `${report.activityTimeoutMs} ms of page silence, wakes so far: ${report.wakes})`;
  }
  return report.state;
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
function runSelfArm(trigger: string, hostPresent?: boolean): Promise<void> | undefined {
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
 * The module-load bootstrap: start the connection without `activate()` (024).
 *
 * ★ This is the primary path, not a fallback, and the reason is a host defect
 * rather than a preference. On 立创 EDA 3.2.149 the host initialises its
 * extension registry *before* the user info that gates it, so the pass that
 * would dispatch a user extension's `activate()` never runs for that launch —
 * the extension works when imported and never again after a restart. Upstream
 * reports the same finding (#219/#221/#222) and answers it the same way: start
 * from the module scope, which the host does execute, and let `activate()`
 * remain an idempotent second trigger.
 *
 * The older measurement from 004d points the same way: a connection chain
 * started during the module's synchronous evaluation **survives** (one ran a
 * 48-minute reconnect loop on its own, 274 audited connects), while chains
 * started later — timers, menu clicks — do not.
 *
 * Once per *editor runtime*: a re-evaluation finds the bootstrap already done
 * and stands down, which is what keeps the log panel plot readable and the
 * second-evaluation no-op. The latch is armed only when an attempt actually
 * started — a bootstrap that stood down for lack of an editor must stay
 * re-runnable, because that is the whole "the host bound `eda` a moment later"
 * case the ladder below exists for.
 */
async function runBootstrap(): Promise<void> {
  if (bootstrappedFromModuleLoad) return;
  moduleBootstrapObserved = true;
  moduleBootstrapObservedAt = new Date().toISOString();
  logLine(
    `module evaluated (evaluation ${evaluations} of this bundle in this editor runtime); ` +
      'starting the connector without waiting for activate()',
  );
  // The pair upstream uses: try now, and once more on the next macrotask,
  // because a sandbox may only bind its globals when the current task ends.
  // Both land on `runStart('bootstrap')`, whose claim gate makes the second a
  // no-op whenever the first one got anywhere.
  const immediate = bootstrapAttempt('at module load');
  if (immediate) bootstrappedFromModuleLoad = true;
  scheduleNextMacrotaskAttempt();
  await immediate;
}

/**
 * One bootstrap connect attempt, with the failure record and the retry (004f).
 *
 * The `catch` is the fix for that blind spot, not a nicety: `connectOnce()` has
 * already taken the one-shot claim by the time it can reject, so without this an
 * early throw left `activate()`, the self-arm and Reconnect all no-ops for the
 * rest of the editor's life, with nothing in the log panel and nothing in
 * `About…`: a dead extension that looks untouched.
 */
function bootstrapAttempt(trigger: string): Promise<void> | undefined {
  if (!facade && !hasHost()) {
    // No editor bound at evaluation time. Say so in the log panel — the one
    // sink that outlives this module instance — rather than vanishing, and
    // knock again: an extension bundle can be evaluated before the host has
    // bound its global, and until 004f that meant standing down for good.
    const note = `${trigger}: editor global not bound; connect not attempted`;
    armNotes.push(note);
    logLine(`bootstrap ${note}`);
    scheduleBootstrapRetry(note);
    return undefined;
  }
  return runStart('bootstrap').catch((error) => {
    connectionAttempted = false; // a failed attempt must not block the next one
    const reason = describeError(error);
    armNotes.push(`bootstrap attempt failed: ${reason}`);
    logLine(`bootstrap FAILED: ${reason}`);
    scheduleBootstrapRetry(reason);
  });
}

/**
 * The second half of the bootstrap pair: one more look, on the next macrotask.
 *
 * Not a retry policy — `scheduleBootstrapRetry` owns that, with its own ladder —
 * but the "the sandbox was not ready for the first attempt" case, which is only
 * a macrotask away. Cheap when the first attempt worked: the claim gate ends it
 * in one line.
 */
function scheduleNextMacrotaskAttempt(): void {
  nextMacrotaskTimer = setTimeout(() => {
    nextMacrotaskTimer = undefined;
    if (connectionAttempted || activation || selfArm) return; // an attempt owns it
    if (!facade && !hasHost()) {
      logLine('bootstrap next-macrotask attempt: the editor global is still not bound');
      return;
    }
    logLine('bootstrap next-macrotask attempt: the editor is reachable after the module load');
    void bootstrapAttempt('next macrotask');
  }, 0);
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
    void bootstrapAttempt('bootstrap retry');
  }, delay);
}

// The connect starts here, at evaluation — not in `activate()`, which the host
// may never call, and not in a timer, which the host may discard. Everything
// below this line happens on every evaluation, and `runtime()` is what makes
// the second evaluation share the first one's controller instead of building a
// second one — including its count of how many evaluations there have been.
void runtime().bootstrapFromModuleLoad();

/** Test seam: run the module-load bootstrap now (Node has no editor at import). */
export function __bootstrapForTests(): Promise<void> {
  return runtime().bootstrapFromModuleLoad();
}

/** Test seam: run the menu safety-net arm now, instead of from a menu click. */
export function __selfArmForTests(options?: { hostPresent?: boolean }): Promise<void> {
  return runtime().selfArm('test', options?.hostPresent) ?? armPromise ?? Promise.resolve();
}

/**
 * The status read-out: connection state plus the 024 lifecycle counters.
 *
 * Read through the runtime so a menu-click evaluation reports the state of the
 * controller that owns the connection — which is the only state that means
 * anything — rather than its own, freshly initialised copy.
 */
export function getStatus(): ConnectorStatus {
  return runtime().getStatus();
}

function readStatus(): ConnectorStatus {
  return {
    ...status,
    moduleBootstrapObserved,
    activateObserved,
    evaluations,
    ...(moduleBootstrapObservedAt ? { bootstrapAt: moduleBootstrapObservedAt } : {}),
    ...(activateObservedAt ? { activateAt: activateObservedAt } : {}),
    // Read at call time, and only when there is an alarm: "no watchdog key" and
    // "a watchdog that is not running" are different statements, and the
    // diagnostics that read this (`sys.connector_status`, `About…`) must be
    // able to tell them apart (026b §2.3).
    ...(watchdog ? { watchdog: watchdog.status() } : {}),
  };
}
