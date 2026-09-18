/**
 * Connector configuration and where the token comes from.
 *
 * An editor extension cannot read `~/.boardwise/token` — it has no way to learn
 * the OS home directory, and `sys_FileSystem` only exposes dialogs and the
 * extension's own folder. Asking the user to copy a 64-hex secret into a dialog
 * ("Set token…") was the worst part of v0, so as of 0.2.0 the connector
 * **generates its own random token** and the daemon trusts it on first use
 * (`docs/bridge.md` §3.4). Nobody types anything.
 *
 * Resolution order for the token:
 *
 * 1. `BOARDWISE_TOKEN` on `globalThis` — lets a wrapper inject it for testing.
 * 2. `token` in extension user config — generated on first activation, or
 *    cleared by "Re-pair on next connect".
 * 3. `?token=` on the configured URL — convenient for a one-off session.
 * 4. nothing — {@link ensureConnectorToken} generates one before we connect.
 *
 * Since 0.2.1 the generation itself is honest about its source: `random.ts`
 * reports whether it used Web Crypto or had to fall back to `Math.random`, and
 * that source is persisted beside the token so `About…` can still say so after a
 * reload. See `random.ts` and `docs/bridge.md` §9.
 */

import { generateToken, type RandomHost } from './random';

/**
 * Where the daemon listens by default.
 *
 * The `/eda` path is there to match the known-working `easyeda-agent`
 * connector, which dials `ws://127.0.0.1:<port>/eda`. Our daemon ignores the
 * path entirely (measured — see `docs/bridge.md` §12), so this is not
 * load-bearing; it is simply the spelling that has been observed to work on a
 * real editor, and matching it removes one variable when something does not
 * connect. The CLI dials the identical URL via `bridge.client.uri_for`.
 */
export const DEFAULT_URL = 'ws://127.0.0.1:61190/eda';

export const STORAGE_KEYS = {
  url: 'url',
  /**
   * The connector's secret, encoded as `"<source>:<64 hex>"` — **one key, one
   * write, on purpose**.
   *
   * 0.2.1 stored the token and its source as two keys written back to back, and
   * a real editor ended up holding `token.source` without `token` (measured
   * 2026-09-13, via `About…`: `storage: readable (token.source=webcrypto)`
   * beside `token: NONE`). Whatever the host does with two adjacent calls, no
   * later load can repair a half-written pair — so there is no longer a pair.
   * `rePair` clears this same single key, which is why it cannot leave residue.
   */
  token: 'token',
  autoConnect: 'autoConnect',
} as const;

/** `"webcrypto:<64 hex>"` / `"math:<64 hex>"`. */
const STORED_TOKEN = /^(webcrypto|math):([0-9a-f]{64})$/;

type TokenSource = 'webcrypto' | 'math';

/** Read a stored value as a token plus its provenance. */
function decodeStoredToken(raw: string): { token: string; source: TokenSource | '' } {
  const match = STORED_TOKEN.exec(raw);
  // A bare hex string is a 0.2.0–0.2.2 value, written before the source was
  // recorded; accept it rather than making the user re-pair.
  if (!match) return { token: raw, source: '' };
  return { token: match[2], source: match[1] as TokenSource };
}

function encodeStoredToken(token: string, source: TokenSource): string {
  return `${source}:${token}`;
}

/**
 * A display-only summary of a stored value. Never the value itself: `About…` and
 * the log panel are both user-visible and exportable.
 */
export function describeStoredToken(raw: unknown): string {
  if (raw === undefined || raw === null || raw === '') return 'unset';
  const text = String(raw);
  const match = STORED_TOKEN.exec(text);
  if (match) return `${match[1]}, ${match[2].length} characters`;
  return `legacy format, ${text.length} characters`;
}

export type StorageLike = {
  getExtensionUserConfig(key: string): unknown;
  setExtensionUserConfig(key: string, value: unknown): Promise<boolean>;
};

export type ResolvedConfig = {
  url: string;
  token: string;
  /**
   * Where the token came from. `generated` is the normal path since 0.2.0:
   * {@link ensureConnectorToken} invented it a moment ago and stored it.
   * `generated-weak` is the same thing via the `Math.random` fallback — a
   * connector that works, at a provenance the user is entitled to be told about.
   */
  tokenSource: 'global' | 'storage' | 'url' | 'generated' | 'generated-weak' | 'missing';
  /**
   * Diagnostics about the token's origin, safe to display (e.g.
   * `crypto=unavailable`). Present when we had to hunt for a source.
   */
  tokenNote?: string;
  autoConnect: boolean;
};

function fromUrl(url: string): string {
  const match = /[?&]token=([^&]+)/.exec(url);
  return match ? decodeURIComponent(match[1]) : '';
}

export function resolveConfig(storage?: StorageLike): ResolvedConfig {
  const injected = (globalThis as { BOARDWISE_TOKEN?: string }).BOARDWISE_TOKEN;
  const storedUrl = String(storage?.getExtensionUserConfig(STORAGE_KEYS.url) ?? '');
  const url = storedUrl || DEFAULT_URL;

  const stored = decodeStoredToken(
    String(storage?.getExtensionUserConfig(STORAGE_KEYS.token) ?? ''),
  );
  const urlToken = fromUrl(url);

  let token = '';
  let tokenSource: ResolvedConfig['tokenSource'] = 'missing';
  if (injected) {
    token = injected;
    tokenSource = 'global';
  } else if (stored.token) {
    token = stored.token;
    // A token born of the weak fallback stays labelled that way for the rest of
    // its life, so `About…` never launders it into an anonymous `storage` token.
    tokenSource = stored.source === 'math' ? 'generated-weak' : 'storage';
  } else if (urlToken) {
    token = urlToken;
    tokenSource = 'url';
  }

  // The socket URL itself must not carry the token once it has been read.
  const cleanUrl = url.replace(/([?&])token=[^&]*&?/, '$1').replace(/[?&]$/, '');
  const autoConnect = storage?.getExtensionUserConfig(STORAGE_KEYS.autoConnect) !== false;

  return {
    url: cleanUrl || DEFAULT_URL,
    token,
    tokenSource,
    // Carry the provenance forward so `About…` can be honest after a reload,
    // not just at the moment of generation.
    ...(tokenSource === 'generated-weak'
      ? { tokenNote: 'the stored token was generated with Math.random (not a CSPRNG)' }
      : {}),
    autoConnect,
  };
}

export const DEFAULT_PORT = 61190;

/** Port from `BOARDWISE_PORT`, mirroring the daemon's own resolution. */
export function portFromEnvironment(): number {
  const raw = (globalThis as { BOARDWISE_PORT?: string | number }).BOARDWISE_PORT;
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_PORT;
}

/**
 * A fresh 32-byte secret as 64 hex characters — the same shape the daemon uses.
 *
 * A thin wrapper over {@link generateToken}, kept because its callers only want
 * the string. The *source* lives there because a caller that cannot say how it
 * got a token is precisely the mistake 0.2.1 exists to fix.
 */
export function randomToken(host?: RandomHost): string {
  return generateToken(host).token;
}

/**
 * The config, with a token guaranteed to exist.
 *
 * Called once per connect. Generates and persists a token the first time, so
 * the zero-configuration flow is: install the extension, restart the editor,
 * done. Writes to storage before returning, because a token that only lives in
 * this process would be regenerated on every reload — which would re-pair the
 * connector each restart and make the pairing record meaningless.
 */
export async function ensureConnectorToken(
  storage?: StorageLike,
  host?: RandomHost,
): Promise<ResolvedConfig> {
  const current = resolveConfig(storage);
  if (current.token) return current;

  const generated = generateToken(host);
  if (!generated.token) {
    // Nothing usable on this host. Return the *diagnosis*, not a bare failure:
    // the caller puts `tokenNote` in the log panel, so the user sees
    // `crypto=unavailable` instead of a connector that sits silently idle.
    return { ...current, tokenNote: generated.detail };
  }

  let note = generated.detail;
  try {
    // One key, one call. See STORAGE_KEYS.token for why this is not two.
    const wrote = await storage?.setExtensionUserConfig(
      STORAGE_KEYS.token,
      encodeStoredToken(generated.token, generated.source === 'math' ? 'math' : 'webcrypto'),
    );
    // The method returns a boolean and may resolve `false`. 0.2.x ignored it, so
    // a refused write was indistinguishable from a good one until the next
    // reload — when the token was simply gone. Say so instead.
    if (storage && wrote === false) {
      note = `${note}; the editor refused to store the token (setExtensionUserConfig returned false)`;
    }
  } catch {
    // Storage refused (quota, permissions). The token still works for this
    // session; it is the *next* restart that will re-pair. Not worth failing —
    // but it is worth reporting.
    note = `${note}; storing the token threw`;
  }
  return {
    ...current,
    token: generated.token,
    tokenSource: generated.source === 'math' ? 'generated-weak' : 'generated',
    tokenNote: note,
  };
}
