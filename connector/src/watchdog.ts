/**
 * The watchdog alarm: a Worker whose only job is to notice that the page went
 * quiet (026b, form A).
 *
 * Why this exists at all. A background editor window is throttled by Chromium:
 * page timers fall to about one tick a minute, and in the frozen state measured
 * in the 7-hour incident they stop entirely (026 probe batch, P3). The
 * connector's liveness (heartbeat, reconnect backoff) runs on those very
 * timers, so a background window can sit on a dead socket for hours and only
 * recover when the user brings it to the front. P3 also measured the fix's
 * premise: a `blob:` Worker's own timers keep running while the page is
 * throttled (153/153 ticks in the same 153 s in which the page managed 20).
 *
 * So the alarm lives in the Worker and the *page* keeps it informed:
 *
 * - the page posts `{type:'activity'}` on every sign of life (heartbeat sent,
 *   frame received, connect attempt, handshake accepted);
 * - the Worker checks every {@link WATCHDOG_CHECK_INTERVAL_MS}; once the page
 *   has been silent for longer than {@link WATCHDOG_ACTIVITY_TIMEOUT_MS} it
 *   posts `{type:'wake'}` — and keeps posting one per check until activity
 *   resumes, because a single wake can be swallowed by a page that is still
 *   frozen. The messages queue, so the moment the page runs again it sees them;
 * - the page's reaction is `Transport.wake()` (`transport.ts`), which is what
 *   actually reconnects.
 *
 * The alarm never touches the socket and never touches the editor API. It is
 * deliberately the dumbest possible Worker: a clock, a silence counter and two
 * message types. That is also why nothing here reaches for `eda` — the Worker
 * scope cannot see it anyway (026 P2: `typeof eda` is `undefined` inside a
 * Worker), and the page side does not need it either.
 *
 * **Failure is reported, never hidden** (026 §四's one non-negotiable rule). A
 * host with no `Worker`, a CSP that refuses `blob:` workers, or a constructor
 * that throws leaves {@link Watchdog.state} at `unavailable` with the host's
 * own reason, and `About…` prints it. A watchdog that silently is not running
 * would be worse than none: the behaviour table in docs/bridge.md §7 would
 * describe a recovery that does not happen.
 *
 * One alarm per editor runtime, not per evaluation of the bundle — the same
 * rule the shared transport runtime follows (`transport.ts`,
 * {@link getOrCreateSharedRuntime}). `index.ts` owns the single instance; a
 * menu click's fresh evaluation reaches the published controller instead of
 * building a second alarm.
 */

/** How often the Worker checks how long the page has been silent, in ms. */
export const WATCHDOG_CHECK_INTERVAL_MS = 15_000;

/**
 * How long the page may be silent before the alarm fires, in ms.
 *
 * Three heartbeat intervals (5 s each) times three: the page normally reports
 * activity every 5 s, and the observed throttled period is about 60 s, so 45 s
 * is short enough to recover inside one throttled cycle and long enough that a
 * merely slow page never trips it.
 */
export const WATCHDOG_ACTIVITY_TIMEOUT_MS = 45_000;

/**
 * `idle`        — built, not started.
 * `running`     — the Worker is up and being fed activity.
 * `unavailable` — the host refused to give us a Worker; `reason` says what it
 *                 answered. The connector runs unchanged, without an alarm.
 * `stopped`     — terminated on purpose (`stop()`), and silent from then on.
 */
export type WatchdogState = 'idle' | 'running' | 'unavailable' | 'stopped';

/** What the page side needs of a Worker, so tests can inject one. */
export interface WatchdogWorkerLike {
  postMessage(message: unknown): void;
  terminate(): void;
  onmessage?: ((event: { data?: unknown }) => void) | null;
  onerror?: ((event: unknown) => void) | null;
}

export interface WatchdogOptions {
  /**
   * The alarm fired: the page has been silent past the timeout. Called once per
   * `wake` message received, on the page's own turn of the event loop.
   */
  onWake: (info: { wakes: number; silenceMs: number }) => void;
  /** Goes to the log panel like every other connector diagnostic. */
  onLog?: (message: string) => void;
  /**
   * Tunables. The defaults are the shipped policy
   * ({@link WATCHDOG_CHECK_INTERVAL_MS}, {@link WATCHDOG_ACTIVITY_TIMEOUT_MS});
   * the tests shrink them, and the values are baked into the Worker source, so
   * a test exercises the real scheduling path rather than a stand-in.
   */
  checkIntervalMs?: number;
  activityTimeoutMs?: number;
  /** Test seam: the Worker constructor. Defaults to the ambient one. */
  createWorker?: (url: string) => WatchdogWorkerLike;
  /** Test seam: `blob:` URL creation. Defaults to `Blob` + `URL`. */
  createObjectUrl?: (source: string) => string;
  /** Test seam: object URL cleanup. */
  revokeObjectUrl?: (url: string) => void;
}

/** Everything `About…` and `sys.connector_status` may report about the alarm. */
export interface WatchdogStatus {
  state: WatchdogState;
  /** The host's own words, when the state is `unavailable`. */
  reason?: string;
  /** How many times the alarm fired in this editor runtime. */
  wakes: number;
  /** When the last wake arrived, ms since epoch. */
  lastWakeAt?: number;
  /** How many activity stamps the page has posted (a diagnostic, not a verdict). */
  activityPosts: number;
  checkIntervalMs: number;
  activityTimeoutMs: number;
}

function ambientCreateWorker(url: string): WatchdogWorkerLike {
  const Worker = (globalThis as { Worker?: unknown }).Worker;
  if (typeof Worker !== 'function') {
    throw new Error('this host has no Worker constructor');
  }
  return new (Worker as new (url: string) => WatchdogWorkerLike)(url);
}

function ambientCreateObjectUrl(source: string): string {
  const Blob = (globalThis as { Blob?: unknown }).Blob;
  const URL = (globalThis as { URL?: { createObjectURL?: (blob: unknown) => string } }).URL;
  if (typeof Blob !== 'function') throw new Error('this host has no Blob constructor');
  if (!URL || typeof URL.createObjectURL !== 'function') {
    throw new Error('this host has no URL.createObjectURL');
  }
  return String(URL.createObjectURL(new (Blob as new (parts: unknown[]) => unknown)([source])));
}

function ambientRevokeObjectUrl(url: string): void {
  const URL = (globalThis as { URL?: { revokeObjectURL?: (value: string) => void } }).URL;
  URL?.revokeObjectURL?.(url);
}

/**
 * The Worker's whole program, with its two tunables baked in.
 *
 * Written as source text because it has to be inline: the extension ships as a
 * single bundle (`dist/index.js`) that the editor loads into IndexedDB, so a
 * separate Worker file has nowhere to live (026b §五).
 *
 * Its own counters (`checks`, `wakes`) ride along on the wake and stopped
 * messages: the page keeps its own tally for `About…`, and the Worker's numbers
 * are what a future diagnostic would compare it against — a round trip the
 * connector does not need today, so there is no `status` message to maintain.
 */
export function buildWatchdogSource(options: { checkIntervalMs: number; activityTimeoutMs: number }): string {
  return `'use strict';
var CHECK_INTERVAL_MS = ${options.checkIntervalMs};
var ACTIVITY_TIMEOUT_MS = ${options.activityTimeoutMs};
var startedAt = Date.now();
var lastActivityAt = startedAt;
var checks = 0;
var wakes = 0;
function post(payload) {
  try { self.postMessage(payload); } catch (error) { /* the page is gone */ }
}
var timer = setInterval(function () {
  checks += 1;
  var silenceMs = Date.now() - lastActivityAt;
  if (silenceMs > ACTIVITY_TIMEOUT_MS) {
    wakes += 1;
    // One per check, not one per silence: a frozen page swallows messages and
    // must find one waiting the moment it runs again.
    post({ type: 'wake', wakes: wakes, checks: checks, silenceMs: silenceMs, at: Date.now() });
  }
}, CHECK_INTERVAL_MS);
self.onmessage = function (event) {
  var data = (event && event.data) ? event.data : {};
  if (data.type === 'activity') { lastActivityAt = Date.now(); return; }
  if (data.type === 'stop') {
    if (timer) { clearInterval(timer); timer = null; }
    post({ type: 'stopped', checks: checks, wakes: wakes, at: Date.now() });
  }
};
post({ type: 'ready', checkIntervalMs: CHECK_INTERVAL_MS, activityTimeoutMs: ACTIVITY_TIMEOUT_MS, at: startedAt });
`;
}

/**
 * The page half of the alarm. One per editor runtime; `index.ts` owns it.
 *
 * Every method is total: `noteActivity()` on an unavailable watchdog is a
 * no-op, `stop()` twice is a no-op, and nothing thrown here can reach the
 * transport. The alarm is a safety net, and a safety net that can break the
 * thing it protects is not one.
 */
export class Watchdog {
  private state: WatchdogState = 'idle';
  private reason = '';
  private worker: WatchdogWorkerLike | undefined;
  private url = '';
  private wakes = 0;
  private lastWakeAt: number | undefined;
  private activityPosts = 0;
  private readonly checkIntervalMs: number;
  private readonly activityTimeoutMs: number;

  constructor(private readonly options: WatchdogOptions) {
    this.checkIntervalMs = options.checkIntervalMs ?? WATCHDOG_CHECK_INTERVAL_MS;
    this.activityTimeoutMs = options.activityTimeoutMs ?? WATCHDOG_ACTIVITY_TIMEOUT_MS;
  }

  /**
   * Build the Worker. Returns whether the alarm is running.
   *
   * Never throws: a refusal is recorded as `unavailable` with the host's own
   * message, which is the state `About…` prints and the tests assert on.
   */
  start(): boolean {
    if (this.state === 'running') return true;
    const source = buildWatchdogSource({
      checkIntervalMs: this.checkIntervalMs,
      activityTimeoutMs: this.activityTimeoutMs,
    });
    try {
      const createWorker = this.options.createWorker ?? ambientCreateWorker;
      const createObjectUrl = this.options.createObjectUrl ?? ambientCreateObjectUrl;
      this.url = createObjectUrl(source);
      this.worker = createWorker(this.url);
    } catch (error) {
      this.fail(error);
      return false;
    }

    this.worker.onmessage = (event) => this.onMessage(event?.data);
    this.worker.onerror = (event) => {
      // Not fatal: a Worker that errored stops checking, and the honest answer
      // is that this runtime has no alarm any more.
      this.fail((event as { message?: unknown })?.message ?? 'the watchdog Worker errored');
    };
    this.state = 'running';
    this.reason = '';
    this.options.onLog?.(
      `watchdog: running (a Worker checks every ${this.checkIntervalMs} ms, `
        + `waking after ${this.activityTimeoutMs} ms of page silence)`,
    );
    return true;
  }

  /** The page is alive. Fire-and-forget: never awaited, never throws. */
  noteActivity(): void {
    if (this.state !== 'running' || !this.worker) return;
    this.activityPosts += 1;
    try {
      this.worker.postMessage({ type: 'activity', at: Date.now() });
    } catch (error) {
      this.fail(error);
    }
  }

  /**
   * Terminate the alarm.
   *
   * Both halves matter: `terminate()` stops the Worker's thread, and dropping
   * the handlers is what makes "a stopped transport sends nothing" true of the
   * Worker too — a message already in flight cannot be answered by a handler
   * that is gone.
   */
  stop(): void {
    const worker = this.worker;
    this.worker = undefined;
    if (worker) {
      worker.onmessage = null;
      worker.onerror = null;
      try {
        worker.postMessage({ type: 'stop' });
      } catch {
        /* on its way out anyway */
      }
      try {
        worker.terminate();
      } catch {
        /* the host may already have collected it */
      }
    }
    if (this.url) {
      try {
        (this.options.revokeObjectUrl ?? ambientRevokeObjectUrl)(this.url);
      } catch {
        /* nothing to do about a URL that will not revoke */
      }
    }
    this.url = '';
    this.state = 'stopped';
  }

  isRunning(): boolean {
    return this.state === 'running' && this.worker !== undefined;
  }

  status(): WatchdogStatus {
    return {
      state: this.state,
      ...(this.reason ? { reason: this.reason } : {}),
      wakes: this.wakes,
      ...(this.lastWakeAt === undefined ? {} : { lastWakeAt: this.lastWakeAt }),
      activityPosts: this.activityPosts,
      checkIntervalMs: this.checkIntervalMs,
      activityTimeoutMs: this.activityTimeoutMs,
    };
  }

  private onMessage(data: unknown): void {
    if (this.state !== 'running') return;
    const payload = (data ?? {}) as { type?: unknown; wakes?: unknown; silenceMs?: unknown };
    if (payload.type !== 'wake') return;
    this.wakes += 1;
    this.lastWakeAt = Date.now();
    const info = {
      wakes: typeof payload.wakes === 'number' ? payload.wakes : this.wakes,
      silenceMs: typeof payload.silenceMs === 'number' ? payload.silenceMs : 0,
    };
    this.options.onLog?.(
      `watchdog: the page has been silent for ${info.silenceMs} ms — waking it (#${info.wakes})`,
    );
    try {
      this.options.onWake(info);
    } catch (error) {
      // A wake handler that throws must not take the alarm down with it: the
      // next check is what recovers the connection.
      this.options.onLog?.(`watchdog: the wake handler threw: ${String(error)}`);
    }
  }

  /** Record the host's refusal, in its own words, and stop pretending. */
  private fail(error: unknown): void {
    const worker = this.worker;
    this.worker = undefined;
    if (worker) {
      worker.onmessage = null;
      worker.onerror = null;
      try {
        worker.terminate();
      } catch {
        /* nothing to do */
      }
    }
    if (this.url) {
      try {
        (this.options.revokeObjectUrl ?? ambientRevokeObjectUrl)(this.url);
      } catch {
        /* nothing to do */
      }
      this.url = '';
    }
    this.reason = error instanceof Error ? error.message : String(error);
    this.state = 'unavailable';
    this.options.onLog?.(
      `watchdog: unavailable (${this.reason}) — the connector runs without a background alarm`,
    );
  }
}
