/**
 * WebSocket transport: connect to the daemon, handshake, reconnect forever.
 *
 * The socket belongs to the editor: `eda.sys_WebSocket.register(id, uri, onMessage,
 * onConnected, protocols)` opens an outbound connection and identifiers it with
 * an id *we* choose. Signatures taken from `@jlceda/pro-api-types@0.4.25`.
 *
 * Two consequences shape this file:
 *
 * - `register()` returns `void` and there is **no** onClose/onError callback,
 *   so death is detected by heartbeat timeout, not by an event.
 * - The API docs warn that re-registering the *same* id with different
 *   parameters is ignored while that id is still live. Reconnects therefore
 *   use a fresh id per attempt (`boardwise-1`, `boardwise-2`, …).
 *
 * Every `eda.*` call is wrapped: they all `throw Error` unless the user has
 * granted the extension's "external interaction" permission, and a thrown
 * error here must become a reconnect, never an unhandled rejection.
 */

import {
  ActionError,
  EVENT_BANNER,
  PROTOCOL_VERSION,
  ROLE_CONNECTOR,
  frameKind,
  isActionError,
  parseFrame,
  requestFrame,
  responseFrame,
  errorFrame,
  withContext,
  type Frame,
  type ResponseContext,
} from './protocol';

/** The slice of `eda.sys_WebSocket` we use. */
export interface EditorWebSocket {
  register(
    id: string,
    serviceUri: string,
    onMessage?: (event: { data: unknown }) => void | Promise<void>,
    onConnected?: () => void | Promise<void>,
    protocols?: string | string[],
  ): void;
  send(id: string, data: string): void;
  close(id: string, code?: number, reason?: string): void;
}

/**
 * `connecting`  — the socket is being opened.
 * `handshaking` — the socket is open and we are waiting for the daemon to
 *                 accept our `hello`. Kept distinct from `connecting` because
 *                 this is where every auth failure lands: a connector stuck
 *                 here has a token problem, a connector stuck in `connecting`
 *                 has a daemon problem.
 * `connected`   — handshake accepted; requests are being served.
 */
export type TransportState =
  | 'idle'
  | 'connecting'
  | 'handshaking'
  | 'connected'
  | 'reconnecting'
  | 'stopped';

/**
 * The editor window's own project, announced in `hello` (021 §2.3).
 *
 * Why it belongs in the handshake: `eda` is scoped to one editor *window*, so
 * the daemon can only ever see the project of the window whose connector holds
 * the bridge. Every window's connector announcing its own project — including
 * the ones the single-active guard turns away, which are exactly the other
 * windows — is what makes "which projects does the user have open?" answerable
 * at all (021 §实测记录 A1: three projects, three windows, one process).
 *
 * Both fields are optional, and are simply left out when the window cannot name
 * its project: the daemon records that absence rather than a guess, because
 * this is the field a caller would use to decide *where* it is working.
 */
export type HelloProjectIdentity = {
  /** The label the editor shows for the project, e.g. `/test`. */
  projectName?: string;
  projectUuid?: string;
};

/**
 * How long `hello` waits for that read, in ms.
 *
 * The daemon closes a socket that has not said `hello` within its own
 * `HELLO_TIMEOUT` (5 s), and `hello` is also what starts the heartbeat — so a
 * host call that never settles must not be able to hold the handshake open.
 * Past the deadline the frame goes out without the identity: a missing field is
 * honest, a hello nobody ever sends is a dead connection.
 */
const IDENTITY_DEADLINE_MS = 1500;

/**
 * How long a response waits for that context read, in ms.
 *
 * Same value and same reasoning as {@link IDENTITY_DEADLINE_MS}, for a harder
 * case: this deadline sits on *every* answer, so a host call that never settles
 * must cost a decoration, never the action. The read is two host calls and
 * normally answers in single-digit milliseconds; the deadline exists only for
 * the pathological case (a hung editor), and a response that arrives 1.5 s late
 * with no context is still the truth about what the action did.
 */
const RESPONSE_CONTEXT_DEADLINE_MS = 1500;

export type TransportOptions = {
  url: string;
  token: string;
  client?: string;
  /**
   * The connector's own build version, announced in `hello`.
   *
   * Added 2026-09-16 (004f item 5) so that every connection leaves a trace of
   * *which build* connected. Twice a sideload that did not take was mistaken
   * for one that did, and the only symptom was a stack pointing at a line that
   * had already been fixed; `sys.probe` answers the question, but only when
   * someone thinks to ask. The daemon records this and marks old connectors
   * `(version unknown)` rather than refusing them.
   */
  connectorVersion?: string;
  /**
   * This extension instance's own id, announced in `hello` (018 §A/§B).
   *
   * The daemon keeps one *active connector instance* and refuses a second live
   * one, because two editor windows each running a connector used to swap the
   * active slot every few minutes and send writes into the wrong project. It
   * needs a value that survives reconnects and changes only when the editor
   * really restarts, which is what this is: `index.ts` generates it once per
   * module evaluation.
   *
   * Optional, like `connectorVersion`: a build that does not send it still
   * connects (the daemon falls back to its connection-level uuid).
   */
  instanceId?: string;
  /**
   * Reads the project this editor window has open, for `hello` (021 §2.3).
   *
   * Injected rather than imported: the reader lives in `actions.ts`, which this
   * file must not depend on (the dependency runs the other way, and reaching up
   * would be a cycle). Omitted entirely when absent — and also when it answers
   * nothing, throws, or never settles, because none of those is a reason to
   * lose the handshake.
   */
  projectIdentity?: () => Promise<HelloProjectIdentity | undefined>;
  /**
   * Deadline for {@link TransportOptions.projectIdentity}, in ms; default
   * {@link IDENTITY_DEADLINE_MS}. A tunable because the tests shrink it to keep
   * runs fast, like the others here.
   */
  projectIdentityTimeoutMs?: number;
  /**
   * Reads this window's live context, for every response frame (023 §协议字段约定 1).
   *
   * Injected for the same reason as {@link TransportOptions.projectIdentity}:
   * the reader lives in `actions.ts`, which this file must not depend on. It is
   * read **after** the action has run, so the answer describes the window as
   * the action left it — a `doc.open` is precisely the case where the context
   * before and after differ, and it is the after that a routing daemon needs.
   *
   * Optional, and answering `undefined` is a supported outcome: a transport
   * built without a reader puts exactly the frames it always did on the wire.
   */
  responseContext?: () => Promise<ResponseContext | undefined>;
  /** Deadline for {@link TransportOptions.responseContext}; see the constant. */
  responseContextTimeoutMs?: number;
  /** Called for every request frame; must return the data payload or throw. */
  onRequest: (action: string, params: Record<string, unknown>) => Promise<unknown>;
  onStatus?: (state: TransportState, detail?: string) => void;
  onLog?: (message: string) => void;
  /**
   * The `data` of the daemon's answer to `hello` — `{role, protocol,
   * serverTime, paired, fingerprint, minConnectorVersion}`. The fingerprint is
   * how the editor and the daemon can be seen to be talking about the same
   * pairing; `minConnectorVersion` is the oldest connector build the daemon
   * will vouch for, and is **absent** on daemons that predate the field.
   */
  onHelloResponse?: (data: Record<string, unknown>) => void;
  /**
   * The editor's socket facade. Required at runtime — see the note on the
   * `socket` getter below; optional only so tests can inject a fake.
   */
  socket?: EditorWebSocket;
  /**
   * The background alarm, told about every sign of life (026b).
   *
   * One direction only — the transport reports, it never drives the alarm.
   * `index.ts` owns the `Watchdog` and hands it in; the wake travels back
   * through {@link Transport.wake}, which is called by the owner, so this file
   * stays free of any knowledge of Workers.
   *
   * Every call is wrapped: the alarm is a safety net, and a safety net that can
   * break the liveness loop it guards is worse than none.
   */
  watchdog?: WatchdogLink;
  /** Tunables; the tests shrink these to keep runs fast. */
  minBackoffMs?: number;
  maxBackoffMs?: number;
  heartbeatMs?: number;
  /** Heartbeats with no answer before the socket is considered dead. */
  heartbeatMissLimit?: number;
};

/**
 * The slice of the watchdog the transport talks to (026b).
 *
 * Structural on purpose: `transport.ts` must not import `watchdog.ts`'s class,
 * so a test can hand it a counter and the dependency stays one method wide.
 */
export interface WatchdogLink {
  noteActivity(): void;
}

export class Transport {
  private socketId: string | undefined;
  private attempt = 0;
  private state: TransportState = 'idle';
  private backoffMs: number;
  private reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  private heartbeatTimer: ReturnType<typeof setInterval> | undefined;
  private missed = 0;
  private stopped = false;
  /** Has `hello` been sent for the current socket attempt? */
  private greeted = false;

  constructor(private readonly options: TransportOptions) {
    this.backoffMs = options.minBackoffMs ?? 1000;
  }

  getState(): TransportState {
    return this.state;
  }

  /**
   * The socket comes from the caller (`index.ts` passes `eda.sys_WebSocket`).
   * Do NOT "simplify" this to `globalThis.eda`: the editor's extension host
   * binds `eda` as a context global that is not reachable through `globalThis`
   * (measured on the real editor, 2026-09-13: bare `eda` resolves while
   * `globalThis.eda` is `undefined`). That one-line difference cost an entire
   * on-machine debugging session — every reconnect produced zero TCP.
   */
  private get socket(): EditorWebSocket | undefined {
    return this.options.socket;
  }

  private setState(state: TransportState, detail?: string) {
    this.state = state;
    this.options.onStatus?.(state, detail);
  }

  private log(message: string) {
    this.options.onLog?.(message);
  }

  /**
   * Tell the background alarm that the page is alive (026b).
   *
   * Called from every sign of life the transport produces — a connect attempt,
   * any inbound frame, a heartbeat that went out, a completed handshake. It
   * carries no detail on purpose: what the alarm counts is silence, and the
   * *kind* of traffic is already in the log panel under its own name.
   *
   * Never allowed to throw into the caller: the alarm is an observer, and a
   * broken observer must not stop the heartbeat.
   */
  private noteActivity(): void {
    try {
      this.options.watchdog?.noteActivity();
    } catch {
      /* the alarm is not worth losing a connection over */
    }
  }

  /**
   * The alarm woke us: the page has been silent long enough that the throttled
   * timers are not to be trusted (026b §2.2).
   *
   * This is the whole point of the Worker. In the background a page's timers
   * fall to about one tick a minute — and in the frozen state measured over the
   * 7-hour incident they stop — so a heartbeat or backoff timer may not run for
   * hours. The wake message is *queued* by the Worker and delivered the moment
   * the page runs again, which is what turns "recovery when the user brings the
   * window to the front" into "recovery when the page unfreezes".
   *
   * Four cases, and the difference between them is what the transport knows:
   *
   * - `connected` with no outstanding heartbeat — nothing to do. The activity
   *   stamp above already stopped the alarm repeating.
   * - `connected` with **any** unanswered heartbeat — the socket is judged dead,
   *   now. Changed in 0.4.18 (026c), and the change is the whole point of it:
   *   the machine measurements of batch 2b showed a background window recovering
   *   in 135–152 s instead of the 90 s that batch was for, because a half-open
   *   socket was only *declared* dead after {@link heartbeatMissLimit} unanswered
   *   heartbeats — three throttled ticks, about three minutes. The old reaction
   *   here (send one more ping, then wait for the timer) could not shorten that:
   *   a ping into a dead socket proves nothing. The silence is what proves it. A
   *   live socket answers a ping within milliseconds, and that answer arrives as
   *   an inbound frame, which resets the miss counter and re-arms the alarm — so
   *   a page that has been quiet past the alarm's 45 s *and* has an unanswered
   *   heartbeat outstanding cannot be sitting on a live socket. Waiting for the
   *   third miss buys nothing and costs two more throttled cycles.
   * - `connecting`/`handshaking` with 45 s of silence behind it — the handshake
   *   is not coming (the daemon answers a banner immediately and allows 5 s for
   *   `hello`), so the attempt is replaced now rather than after the daemon's
   *   own close, which a half-open socket never delivers.
   * - `idle`/`reconnecting` — nothing on the wire; connect now, with the backoff
   *   ladder reset, because the silence was the page's and not the daemon's.
   */
  wake(source: string): void {
    if (this.stopped) return;
    this.noteActivity();

    if (this.state === 'connected') {
      if (this.missed === 0) {
        this.log(`watchdog wake (${source}): connected and answering — nothing to do`);
        return;
      }
      // One unanswered heartbeat is enough; see the case list above.
      this.reconnectNow(
        `watchdog wake (${source}): ${this.missed} unanswered heartbeat(s)`,
      );
      return;
    }

    if (this.state === 'connecting' || this.state === 'handshaking') {
      this.reconnectNow(`watchdog wake (${source}): the handshake has been silent for too long`);
      return;
    }

    this.log(`watchdog wake (${source}): nothing on the wire — connecting now, backoff reset`);
    this.backoffMs = this.options.minBackoffMs ?? 1000;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = undefined;
    }
    void this.connect();
  }

  /**
   * One heartbeat, sent by the timer that owns the cadence.
   *
   * `why` is what the log and any resulting reconnect reason are phrased
   * around, so "the timer got no answer" and "an alarm woke a silent page" stay
   * distinguishable in the log panel — the difference matters on the machine.
   * (The wake path used to come through here too until 0.4.18; it reconnects on
   * the first unanswered heartbeat now, so a ping from it would be pointless.)
   */
  private sendPing(why: string): void {
    this.missed += 1;
    try {
      this.raw(requestFrame('ping'));
    } catch {
      this.scheduleReconnect(`${why} send failed`);
    }
  }

  /**
   * Drop whatever is on the wire and reconnect **synchronously**, ladder reset.
   *
   * Two things this must not do, and both were measured:
   *
   * - It must not keep the ladder. A wake is evidence about the *page*, not
   *   about the daemon, so the backoff the previous failure climbed says nothing
   *   about now: a frozen window's recovery would otherwise wait through the
   *   1 s … 30 s it had accumulated against a daemon that never left.
   * - It must not go through a timer **at all**, not even `setTimeout(…, 0)`.
   *   A throttled page's timers are coalesced to about one tick a minute, and
   *   that applies to zero-delay ones too — so the "immediate" reconnect could
   *   be deferred by the rest of the throttled period. Measured on 3.2.186
   *   (026c): with `setTimeout(0)` the same experiment came back in 101 s and
   *   115 s on two runs out of three, and the deferral is what the extra ~50 s
   *   was. `connect()` registers synchronously, so calling it directly is
   *   immediate in the only sense that matters to a throttled page.
   */
  private reconnectNow(reason: string): void {
    this.backoffMs = this.options.minBackoffMs ?? 1000;
    if (!this.dropAttempt(reason)) return;
    // Logged like the ladder's path, with the one difference that matters to a
    // reader of the log panel: this one did not wait for anything.
    this.log(`reconnecting now, no timer: ${reason}`);
    void this.connect();
  }

  /**
   * Connect now. Never throws: a failure schedules a retry.
   *
   * Idempotent since 0.4.12 (024). `activate()` can now arrive *after* the
   * module-load bootstrap has already opened the socket, and a second
   * `start()` on a live attempt would register a second socket — the editor
   * keys connections by the id we choose, and we choose a fresh id per attempt,
   * so nothing would collapse the two. `connecting`, `handshaking` and
   * `connected` all mean "an attempt is already on the wire"; only `idle`,
   * `reconnecting` and `stopped` have nothing there.
   */
  async start(): Promise<void> {
    this.stopped = false;
    if (this.isLive()) return;
    if (this.reconnectTimer) {
      // An explicit start supersedes a scheduled retry, which would otherwise
      // register a second socket a moment later.
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = undefined;
    }
    await this.connect();
  }

  /** Is there already an attempt on the wire? See {@link start}. */
  private isLive(): boolean {
    return (
      this.state === 'connecting' || this.state === 'handshaking' || this.state === 'connected'
    );
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    if (this.socketId) {
      try {
        this.socket?.close(this.socketId);
      } catch {
        /* editor already gone */
      }
    }
    this.socketId = undefined;
    this.setState('stopped');
  }

  private clearTimers() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.reconnectTimer = undefined;
    this.heartbeatTimer = undefined;
  }

  private async connect(): Promise<void> {
    const socket = this.socket;
    // An attempt is a sign of life: the page is running, whatever the outcome.
    this.noteActivity();
    if (!socket) {
      this.scheduleReconnect('eda.sys_WebSocket is unavailable');
      return;
    }
    this.attempt += 1;
    const id = `boardwise-${this.attempt}`;
    this.greeted = false;
    this.setState('connecting');
    // Logged *before* the call: when registration is rejected outright there
    // is no other record of what we asked the editor to open.
    this.log(`register ${id} -> ${this.options.url}`);
    try {
      socket.register(
        id,
        this.options.url,
        (event) => void this.onMessage(event?.data),
        () => this.onConnected(),
      );
    } catch (error) {
      this.scheduleReconnect(`register failed: ${String(error)}`);
      return;
    }
    this.socketId = id;
  }

  /**
   * The editor's connect callback — advisory, never trusted.
   *
   * This is the bug that broke task 004b: `hello` used to be sent from here,
   * and on the real editor this callback never fires, so nothing was ever sent
   * in either direction. The reference connector (`easyeda-agent`) passes an
   * empty function for this argument and detects the connection purely from
   * inbound frames — see docs/bridge.md §7. Kept because it is a free early
   * trigger when it *does* fire; {@link onMessage} is the authoritative one.
   */
  private onConnected(): void {
    this.log('editor reports the socket connected (advisory)');
    this.ensureHello('onConnected');
  }

  /**
   * Send `hello`, once per socket attempt.
   *
   * Message-driven on purpose: the daemon sends a banner the moment the socket
   * opens, so *any* inbound frame proves the socket is up end to end — a fact,
   * unlike a callback that may never be invoked.
   *
   * Idempotent via {@link greeted}: the daemon answers a second `hello` with
   * `PROTOCOL_VIOLATION`, so repeated triggers must not produce a second frame.
   */
  private ensureHello(trigger: string): void {
    if (!this.socketId || this.greeted) return;
    this.greeted = true;
    this.missed = 0;
    this.backoffMs = this.options.minBackoffMs ?? 1000;
    this.setState('handshaking');
    const readProject = this.options.projectIdentity;
    if (!readProject) {
      // No reader configured: unchanged behaviour — the frame goes out here and
      // now, with no project fields at all.
      this.sendHello(trigger, {});
      return;
    }
    void this.sendHelloWithProject(trigger, readProject);
  }

  /**
   * Read this window's project, then send `hello` (021 §2.3).
   *
   * Deliberately on a deadline (see {@link IDENTITY_DEADLINE_MS}): the identity
   * is a decoration on the frame, never a precondition for it, and the daemon
   * closes a socket that stays silent past its own `HELLO_TIMEOUT`.
   */
  private async sendHelloWithProject(
    trigger: string,
    readProject: () => Promise<HelloProjectIdentity | undefined>,
  ): Promise<void> {
    const attempt = this.socketId;
    const project = await readProjectIdentity(
      readProject,
      this.options.projectIdentityTimeoutMs ?? IDENTITY_DEADLINE_MS,
    );
    // A reconnect may have begun while the read was pending. That attempt owns
    // the wire and greets on its own (`greeted` is per attempt), so this one
    // must not send anything to a socket that is no longer ours.
    if (this.stopped || !attempt || this.socketId !== attempt) return;
    this.sendHello(trigger, project);
  }

  private sendHello(trigger: string, project: HelloProjectIdentity): void {
    try {
      this.raw(
        requestFrame(
          'hello',
          {
            token: this.options.token,
            role: ROLE_CONNECTOR,
            protocol: PROTOCOL_VERSION,
            client: this.options.client ?? 'boardwise-connector',
            // Optional, and omitted when a build has no version baked in
            // (`VERSION` answers 'unknown' then, which is still a real value).
            ...(this.options.connectorVersion
              ? { connectorVersion: this.options.connectorVersion }
              : {}),
            // Which extension *instance* this is, so the daemon can tell two
            // editor windows apart instead of letting them take turns
            // (018 §A). Omitted when the caller has none.
            ...(this.options.instanceId ? { instanceId: this.options.instanceId } : {}),
            // Which project this window has open (021 §2.3), so the daemon can
            // list every window it has heard from — the refused ones included —
            // as a project. Omitted when this window cannot name one.
            ...project,
          },
          'hello',
        ),
      );
    } catch (error) {
      // Nothing went out, so the attempt is not greeted after all — otherwise
      // the retry would sit silently waiting for a hello it will never send.
      this.greeted = false;
      this.scheduleReconnect(`handshake send failed: ${String(error)}`);
      return;
    }
    this.log(`sent hello (triggered by ${trigger})`);
    // Heartbeat only starts once the handshake is on the wire: a heartbeat
    // before that would be measuring a connection we have not introduced
    // ourselves on.
    this.startHeartbeat();
  }

  private startHeartbeat(): void {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    const interval = this.options.heartbeatMs ?? 5000;
    const missLimit = this.options.heartbeatMissLimit ?? 3;
    this.heartbeatTimer = setInterval(() => {
      if (this.missed >= missLimit) {
        this.scheduleReconnect('heartbeat timed out');
        return;
      }
      this.sendPing('heartbeat');
      // A ping that went out is the page doing its job, whether or not an
      // answer comes back — the alarm measures the *page*, not the daemon.
      this.noteActivity();
    }, interval);
  }

  private async onMessage(raw: unknown): Promise<void> {
    if (typeof raw !== 'string') return;
    let frame: Frame;
    try {
      frame = parseFrame(raw);
    } catch (error) {
      this.log(`dropped unparsable frame: ${String(error)}`);
      return;
    }

    this.missed = 0; // any traffic proves the socket is alive
    this.noteActivity();

    // The handshake hangs off inbound traffic, not off the editor's connect
    // callback (see ensureHello). This line is the fix for task 004b.
    this.ensureHello(frame.event ? `daemon ${frame.event}` : 'inbound frame');

    const kind = frameKind(frame);

    // An event is unsolicited and is answered by nobody.
    if (kind === 'event') {
      this.onEvent(frame);
      return;
    }

    // A frame carrying `ok` is an answer to something we sent.
    if (kind === 'response') {
      if (frame.id === 'hello' || frame.action === 'hello') {
        if (frame.ok) {
          this.setState('connected');
          // The handshake is the strongest sign of life there is: the whole
          // path — socket, daemon, pairing — just answered (026b).
          this.noteActivity();
          this.options.onHelloResponse?.(
            (frame.data ?? {}) as Record<string, unknown>,
          );
        } else {
          this.scheduleReconnect(`daemon rejected handshake: ${frame.error?.code}`);
        }
      }
      return;
    }

    const action = frame.action;
    if (typeof action !== 'string' || action === '') {
      await this.reply(
        errorFrame(frame.id, new ActionError('BAD_REQUEST', 'request frame has no action')),
      );
      return;
    }
    try {
      const data = await this.options.onRequest(action, frame.params ?? {});
      // The context is read *here*, after the action: it has to describe the
      // window the action left behind, not the one it was sent to.
      await this.reply(responseFrame(frame.id, data));
    } catch (error) {
      if (isActionError(error)) {
        await this.reply(errorFrame(frame.id, error));
      } else {
        // An unexpected throw carries only a sentence ("TypeError: Cannot read
        // properties of undefined (reading 'prototype')"), which cost a whole
        // debug session on 2026-09-14: it says what the engine complained
        // about and nothing about where. The name and the top of the stack go
        // into `detail`, which the daemon and the CLI already print.
        const err = error as { name?: unknown; message?: unknown; stack?: unknown };
        await this.reply(errorFrame(frame.id, new ActionError('INTERNAL', String(error), {
          errorName: typeof err?.name === 'string' ? err.name : typeof error,
          errorMessage: typeof err?.message === 'string' ? err.message : null,
          stack: typeof err?.stack === 'string'
            ? err.stack.split('\n').slice(0, 6).join('\n')
            : null,
        })));
      }
    }
  }

  /**
   * Put one answer on the wire, carrying this window's live context (023).
   *
   * **The single point every response frame leaves the connector through** —
   * the success path, both failure paths and the malformed-request refusal all
   * end here — so "every answer says where it came from" is one line to read
   * instead of four to keep in step. A failed action still tells the daemon
   * which window refused it, which is exactly when a caller is most likely to
   * be guessing about the window.
   *
   * The context decorates the frame; it never gates one (see
   * {@link readResponseContext}).
   */
  private async reply(frame: Frame): Promise<void> {
    this.raw(withContext(frame, await this.readResponseContext()));
  }

  /**
   * This window's live context, or `undefined` when there is nothing to say.
   *
   * `undefined` rather than `{}`, and the difference is not cosmetic: a frame
   * that says nothing and a frame claiming an empty context are different
   * statements, and only the first is true of a build with no reader.
   */
  private async readResponseContext(): Promise<ResponseContext | undefined> {
    const read = this.options.responseContext;
    if (!read) return undefined;
    return readWithDeadline(
      read,
      this.options.responseContextTimeoutMs ?? RESPONSE_CONTEXT_DEADLINE_MS,
    );
  }

  /**
   * Handle an unsolicited notification from the daemon.
   *
   * Only the banner exists today, and it is logged rather than acted on: the
   * move it asks for (`expect: hello`) is already taken by `ensureHello`,
   * which fires for any inbound frame.
   */
  private onEvent(frame: Frame): void {
    if (frame.event === EVENT_BANNER) {
      const data = (frame.data ?? {}) as {
        server?: string;
        protocol?: string;
        expect?: string;
      };
      this.log(
        `daemon banner: ${data.server ?? 'unknown'} protocol ${data.protocol ?? '?'}` +
          ` expects ${data.expect ?? '?'}`,
      );
      return;
    }
    this.log(`ignored unknown event ${frame.event}`);
  }

  private raw(frame: Frame): void {
    if (!this.socket || !this.socketId) throw new Error('socket is not open');
    this.socket.send(this.socketId, JSON.stringify(frame));
  }

  /**
   * Drop the current attempt without scheduling anything.
   *
   * The teardown half of {@link scheduleReconnect}, split out in 026c: the wake
   * path has to be able to leave the wire clean *and* reconnect on the spot, and
   * it must not do the second half through a timer (see {@link reconnectNow}).
   * Returns false when there is nothing to do because the transport is stopped.
   */
  private dropAttempt(reason: string): boolean {
    if (this.stopped) return false;
    this.clearTimers();
    if (this.socketId) {
      try {
        this.socket?.close(this.socketId);
      } catch {
        /* already gone */
      }
    }
    this.socketId = undefined;
    this.setState('reconnecting', reason);
    return true;
  }

  /**
   * Drop the current attempt and try again after `delayMs` (default: the
   * current backoff step, which then doubles).
   *
   * This is the ladder's path — a failure the transport noticed on its own. The
   * watchdog's wake goes through {@link reconnectNow} instead, because a page
   * that is throttled cannot be trusted to run a timer on time.
   */
  private scheduleReconnect(reason: string, delayMs?: number): void {
    if (!this.dropAttempt(reason)) return;
    const delay = delayMs ?? this.backoffMs;
    this.log(`reconnecting in ${delay} ms: ${reason}`);
    this.reconnectTimer = setTimeout(() => void this.connect(), delay);
    this.backoffMs = Math.min(this.backoffMs * 2, this.options.maxBackoffMs ?? 30000);
  }
}

/**
 * Keep only the fields the `hello` frame is entitled to carry.
 *
 * The reader is a callback a build supplies, so this is where "a field we could
 * not read" is turned into "no field" — never into `null`, `undefined` or the
 * string `"undefined"`, all of which would read on the daemon side like a
 * project that happens to be named that.
 */
function identityFields(identity: HelloProjectIdentity | undefined): HelloProjectIdentity {
  const name = identity?.projectName;
  const uuid = identity?.projectUuid;
  return {
    ...(typeof name === 'string' && name ? { projectName: name } : {}),
    ...(typeof uuid === 'string' && uuid ? { projectUuid: uuid } : {}),
  };
}

/**
 * The injected project read, with a deadline, and with "nothing" as its one
 * failure mode.
 *
 * Never rejects and never hangs. A reader that throws and a reader that never
 * settles both answer `{}` — both are real on the editor host (measured
 * 2026-09-14: host objects are Proxies whose `get` trap throws), and a caller
 * whose read failed still has a socket to open and a daemon waiting for it.
 */
async function readProjectIdentity(
  read: () => Promise<HelloProjectIdentity | undefined>,
  ms: number,
): Promise<HelloProjectIdentity> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const deadline = new Promise<undefined>((resolve) => {
      timer = setTimeout(() => resolve(undefined), ms);
    });
    // `Promise.race` subscribes to both promises, so a reader that rejects
    // *after* the deadline won is still a handled rejection.
    const value = await Promise.race([Promise.resolve(read()), deadline]);
    return identityFields(value);
  } catch {
    return {};
  } finally {
    clearTimeout(timer);
  }
}

/**
 * The injected context read, on a deadline, with "nothing" as its one failure
 * mode.
 *
 * The same shape as {@link readProjectIdentity} on purpose: a reader that
 * throws and one that never settles both answer `undefined`, because both are
 * real on the editor host and neither is a reason to lose the answer to an
 * action that has already been carried out. Keeping only the fields that are
 * readings is `withContext`'s job, at the frame.
 */
async function readWithDeadline(
  read: () => Promise<ResponseContext | undefined>,
  ms: number,
): Promise<ResponseContext | undefined> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const deadline = new Promise<undefined>((resolve) => {
      timer = setTimeout(() => resolve(undefined), ms);
    });
    // `Promise.race` subscribes to both promises, so a reader that rejects
    // *after* the deadline won is still a handled rejection.
    return await Promise.race([Promise.resolve(read()), deadline]);
  } catch {
    return undefined;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * ─── Cross-evaluation runtime registry (024) ─────────────────────────────
 *
 * 立创 EDA 3.2.149 never dispatches `activate()` for a user extension: the host
 * initialises its extension registry before the user info the gate depends on
 * exists, then skips the pass (upstream issues #219/#221). The connector's
 * answer is to start from the module load — which raises the next problem. The
 * editor evaluates the bundle more than once in the same process (every menu
 * click does), so without something shared, each evaluation would build its own
 * controller: a second socket to the same daemon, a second reconnect loop, and
 * its own idea of what is connected.
 *
 * So the first evaluation publishes its controller on the editor's own
 * per-extension object (`eda`) under {@link SHARED_RUNTIME_KEY}, and a later
 * evaluation of the same build reuses it. {@link sharedRuntimeImplementation}
 * is the signature that makes "the same build" checkable: `cross-eval-v1` names
 * the *shape* of the record, the connector version names the build. A record
 * that is not an exact signature match is a different build (or an older
 * connector that never published one) — its `stop` is called, best-effort, and
 * this evaluation publishes in its place.
 *
 * This module owns the *mechanics* only — publish, look up, retire. What the
 * controller does is the caller's business, which is also why the host object
 * is a parameter: `facade.ts` is the only module allowed to touch `eda`, and a
 * stand-in host is what makes the mechanism testable in Node at all.
 */

/** Where the published controller lives. Chosen for the editor's own object. */
export const SHARED_RUNTIME_KEY = '__boardwiseTransportRuntime';

/**
 * The record's shape, appended to the connector version.
 *
 * Bump it when the members below change meaning: two builds that disagree about
 * the shape must not hand each other their controllers, and the version alone
 * would not catch a change to what the members *are*.
 */
export const SHARED_RUNTIME_EPOCH = 'cross-eval-v1';

/** `<version>:cross-eval-v1` — the whole point of the check. */
export function sharedRuntimeImplementation(version: string): string {
  return `${version}:${SHARED_RUNTIME_EPOCH}`;
}

/**
 * Every member a published record must carry to be usable by another evaluation.
 *
 * Validated by reading, not by trusting the key: the object on the host belongs
 * to the editor, and anything could be sitting under it.
 *
 * **The whole record — `keyof OwnedTransportRuntime` (`index.ts`) minus the
 * `implementation` string, which is compared separately — rather than one name
 * per defect.** The list used to grow the way the failures arrived, which is how
 * `about` came to be the one member of five that a caller reached for without
 * being checked: listed were the members a test had already gone red on. A
 * record missing a member the caller then uses fails at the call site instead,
 * and that failure is not always loud — an adopted record with no
 * `noteEvaluation` throws inside `runtime()`, which `activate()` catches on
 * purpose, so the extension looks inert rather than broken (measured: that is
 * exactly what dropping a name from this list does, see the loop in
 * `tests/bootstrap.test.mjs`). The price of the whole list is one comparison per
 * member on a read that happens a handful of times per editor session; the price
 * of a partial one is a silently half-working controller. The test walks it in
 * both directions — a record missing any single member is retired, a record
 * carrying all of them is adopted.
 */
export const SHARED_RUNTIME_MEMBERS = [
  'start',
  'bootstrapFromModuleLoad',
  'reconnect',
  'stop',
  'selfArm',
  'about',
  'getStatus',
  'noteEvaluation',
] as const;

export interface SharedRuntimeLookup<T> {
  /** The controller to use: ours, or the one already published. */
  runtime: T;
  /** True when this lookup created it (i.e. this evaluation ran the bootstrap). */
  created: boolean;
  /** True when {@link SHARED_RUNTIME_KEY} now holds that controller. */
  published: boolean;
  /** The signature of the record this evaluation replaced, when there was one. */
  retired?: string;
}

function isReusableRuntime(value: unknown, implementation: string): boolean {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Record<string, unknown>;
  if (candidate.implementation !== implementation) return false;
  return SHARED_RUNTIME_MEMBERS.every((member) => typeof candidate[member] === 'function');
}

/**
 * Publish a controller on the host, or report that the host would not take it.
 *
 * Both writes are attempted because the two ways this fails are real and
 * different: a frozen or sealed object refuses `defineProperty`, a `Proxy` host
 * may refuse assignment instead. A host that takes neither still runs the
 * controller — this evaluation just has no way to hand it to the next one, and
 * the caller says so in the log panel rather than pretending otherwise.
 */
function publishSharedRuntime(host: Record<string, unknown>, runtime: unknown): boolean {
  try {
    Object.defineProperty(host, SHARED_RUNTIME_KEY, {
      configurable: true,
      enumerable: false,
      value: runtime,
      writable: true,
    });
    return true;
  } catch {
    /* frozen, sealed, or a refusing proxy — try the plain write */
  }
  try {
    host[SHARED_RUNTIME_KEY] = runtime;
    return true;
  } catch {
    return false;
  }
}

/**
 * The published controller, when the host carries one this build can use.
 *
 * The read-only half of {@link getOrCreateSharedRuntime}: what it answers is
 * either the controller that owns this editor runtime or nothing, and the
 * caller decides what to do with "nothing" (publish its own, or keep the one it
 * already built before the host was reachable).
 */
export function readSharedRuntime<T extends { implementation: string }>(
  host: Record<string, unknown> | undefined,
  implementation: string,
): T | undefined {
  if (!host) return undefined;
  const existing = host[SHARED_RUNTIME_KEY];
  return isReusableRuntime(existing, implementation) ? (existing as T) : undefined;
}

/**
 * Publish a controller built before the host was reachable, without overwriting.
 *
 * The narrow case this covers: the bundle was evaluated before the editor bound
 * `eda`, so there was nothing to publish to. When the host appears later, the
 * controller that already owns everything should become visible to later
 * evaluations — but only if nothing is under the key yet. Anything that *is*
 * there belongs to another evaluation, and two controllers overwriting each
 * other is worse than one staying local.
 */
export function publishSharedRuntimeIfEmpty(
  host: Record<string, unknown> | undefined,
  runtime: unknown,
): boolean {
  if (!host) return false;
  if (host[SHARED_RUNTIME_KEY] !== undefined) return false;
  return publishSharedRuntime(host, runtime);
}

/**
 * The controller that owns this editor runtime: the published one, or a new one.
 *
 * `create` runs only when there is nothing to reuse, so a re-evaluation never
 * builds a second controller and never reaches for a second socket.
 */
export function getOrCreateSharedRuntime<T extends { implementation: string }>(
  host: Record<string, unknown> | undefined,
  implementation: string,
  create: () => T,
): SharedRuntimeLookup<T> {
  if (!host) {
    // No editor to publish to — the Node case, and the case of a host that
    // binds its global a macrotask late. This evaluation owns its controller,
    // unchanged from before this mechanism existed.
    return { runtime: create(), created: true, published: false };
  }

  const existing = host[SHARED_RUNTIME_KEY];
  if (isReusableRuntime(existing, implementation)) {
    return { runtime: existing as T, created: false, published: false };
  }

  // Something else is there: a different build, or a record from a connector
  // that predates this mechanism. Retire it before publishing, so its socket
  // and its reconnect timer do not outlive the build that made them. Best
  // effort by design — an old build's `stop` throwing must not stop us.
  let retired: string | undefined;
  if (existing && typeof existing === 'object') {
    const stale = existing as { implementation?: unknown; stop?: unknown };
    retired = typeof stale.implementation === 'string' ? stale.implementation : 'unknown build';
    if (typeof stale.stop === 'function') {
      try {
        (stale.stop as () => void).call(existing);
      } catch {
        /* a stale controller that cannot stop is still stale */
      }
    }
  }

  const runtime = create();
  const published = publishSharedRuntime(host, runtime);
  return { runtime, created: true, published, ...(retired ? { retired } : {}) };
}

/**
 * Forget the published controller, when it is still the one we published.
 *
 * Called on deactivation: the next extension load must be free to install its
 * own controller rather than inherit a stopped one.
 */
export function releaseSharedRuntime(host: Record<string, unknown> | undefined, runtime: unknown): void {
  if (!host || host[SHARED_RUNTIME_KEY] !== runtime) return;
  try {
    delete host[SHARED_RUNTIME_KEY];
  } catch {
    try {
      host[SHARED_RUNTIME_KEY] = undefined;
    } catch {
      /* the stopped controller stays on the host, inert */
    }
  }
}
