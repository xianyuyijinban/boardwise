/**
 * The one seam between this extension and the editor.
 *
 * **This is the only module in `src/` allowed to touch the host's `eda`
 * global**, and `tests/source-guard.test.mjs` enforces that by reading the
 * sources. The reason is not tidiness — it is that the composition root was the
 * one thing no test could see, and it broke twice in the same way.
 *
 * On 2026-09-13 an on-machine session measured the exact shape of the trap:
 * the extension host binds `eda` as a *context global*, so bare `eda` resolves
 * while `globalThis.eda` is `undefined`. The transport used to reach for the
 * socket through `globalThis`, got `undefined` every time, and therefore never
 * called `register` — zero TCP connections, with a healthy daemon, and every
 * test green because every test injects a fake socket.
 *
 * So the global is read in exactly one function ({@link createFacade}), the
 * result is passed down explicitly, and {@link createFacade} accepts an
 * explicit host so tests can drive the whole production path with a stand-in.
 */

import { ambientRandomHost, type RandomHost } from './random';
import type { StorageLike } from './config';
import type { EditorWebSocket } from './transport';

/** The editor's API surface. Deliberately `any`: see `actions.ts` for why. */
declare const eda: any;

export type EditorFacade = {
  /** The raw API, handed to the action handlers (`actions.ts`). */
  readonly api: unknown;
  /** `eda.sys_WebSocket` — the outbound socket the editor owns. */
  readonly websocket: EditorWebSocket | undefined;
  /** `eda.sys_Storage` — where the connector's own token lives. */
  readonly storage: StorageLike | undefined;
  /**
   * Where random bytes come from. Part of the host surface on purpose: the
   * extension realm is *not* a browser realm (bare `crypto` did not resolve
   * there on 2026-09-13), so the source has to be observable and injectable
   * rather than assumed. See `random.ts`.
   */
  readonly random: RandomHost;
  /** One line into the editor's log panel. Never pass anything secret. */
  log(line: string): void;
  /** Best-effort toast. */
  notify(message: string): void;
  /** Modal info box, falling back to a toast. Used by `About…`. */
  alert(message: string, title: string): void;
  /** The host editor's version, for the `client` field of `hello`. */
  editorVersion(): string;
};

/**
 * Read the host global, or `undefined` when there is no editor.
 *
 * The `try` is load-bearing: in a plain Node process (the test suite) `eda` is
 * not a declared variable anywhere, so evaluating the bare identifier throws a
 * `ReferenceError`. That is catchable — and catching it is what lets every
 * test import this module without an editor present.
 */
function hostGlobal(): any {
  try {
    return eda;
  } catch {
    return undefined;
  }
}

/**
 * Is the editor global bound *right now*? Deliberately does not cache.
 *
 * For the self-arm check in `index.ts`: an editor that loads an extension for its
 * menus without ever calling `activate()` leaves us with nothing to do, and
 * waiting forever for a callback the host may not send is not a design. This
 * asks the question without creating a facade, so a "no editor yet" answer does
 * not get cached and shadow a later, real one.
 */
export function hasHost(): boolean {
  return Boolean(hostGlobal());
}

/**
 * The host object itself, as somewhere to hang cross-evaluation state (024).
 *
 * Read *without* creating a facade on purpose: the caller is the shared-runtime
 * registry, which runs during module evaluation — before anything has decided
 * that the editor is ready — and a facade created here would also answer
 * `hasHost()` differently for everyone else.
 *
 * What it is for: the editor hands every evaluation of our bundle the same
 * per-extension `eda` object, which is the only place that survives a
 * re-evaluation (`globalThis` is not reachable from the extension host, see the
 * module docstring). `undefined` when there is no editor to publish to.
 */
export function hostObject(): Record<string, unknown> | undefined {
  const api = hostGlobal();
  return api && typeof api === 'object' ? (api as Record<string, unknown>) : undefined;
}

export function createFacade(host?: unknown): EditorFacade {
  const api = (host ?? hostGlobal()) as any;

  return {
    api,
    websocket: api?.sys_WebSocket,
    storage: api?.sys_Storage,
    // A stand-in host may bring its own random surface (the wiring tests do, to
    // prove the no-Web-Crypto path); otherwise read the ambient realm.
    random: (api?.random as RandomHost | undefined) ?? ambientRandomHost(),

    log(line: string): void {
      try {
        api?.sys_Log?.add?.(line);
      } catch {
        // The log panel is a convenience. It must never break the transport.
      }
    },

    notify(message: string): void {
      try {
        api?.sys_Message?.showToastMessage?.(message);
      } catch {
        // No toast available; the About… box still reports the state.
      }
    },

    alert(message: string, title: string): void {
      try {
        api?.sys_Dialog?.showInformationMessage?.(message, title);
      } catch {
        // Fall back to the toast, which is at least visible.
        this.notify(message);
      }
    },

    editorVersion(): string {
      try {
        return String(api?.sys_Environment?.getEditorCurrentVersion?.(true) ?? '');
      } catch {
        return '';
      }
    },
  };
}
