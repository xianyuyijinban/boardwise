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
  type Frame,
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
  /** Tunables; the tests shrink these to keep runs fast. */
  minBackoffMs?: number;
  maxBackoffMs?: number;
  heartbeatMs?: number;
  /** Heartbeats with no answer before the socket is considered dead. */
  heartbeatMissLimit?: number;
};

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

  /** Connect now. Never throws: a failure schedules a retry. */
  async start(): Promise<void> {
    this.stopped = false;
    await this.connect();
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
      this.missed += 1;
      try {
        this.raw(requestFrame('ping'));
      } catch {
        this.scheduleReconnect('heartbeat send failed');
      }
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
      this.raw(errorFrame(frame.id, new ActionError('BAD_REQUEST', 'request frame has no action')));
      return;
    }
    try {
      const data = await this.options.onRequest(action, frame.params ?? {});
      this.raw(responseFrame(frame.id, data));
    } catch (error) {
      if (isActionError(error)) {
        this.raw(errorFrame(frame.id, error));
      } else {
        // An unexpected throw carries only a sentence ("TypeError: Cannot read
        // properties of undefined (reading 'prototype')"), which cost a whole
        // debug session on 2026-09-14: it says what the engine complained
        // about and nothing about where. The name and the top of the stack go
        // into `detail`, which the daemon and the CLI already print.
        const err = error as { name?: unknown; message?: unknown; stack?: unknown };
        this.raw(errorFrame(frame.id, new ActionError('INTERNAL', String(error), {
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

  private scheduleReconnect(reason: string): void {
    if (this.stopped) return;
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
    this.log(`reconnecting in ${this.backoffMs} ms: ${reason}`);
    this.reconnectTimer = setTimeout(() => void this.connect(), this.backoffMs);
    this.backoffMs = Math.min(this.backoffMs * 2, this.options.maxBackoffMs ?? 30000);
  }
}
