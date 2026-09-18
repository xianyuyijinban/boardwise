/**
 * Wiring tests for the extension entry point — the gap that shipped twice.
 *
 * Until 0.2.0 nothing tested `index.ts`. Every transport test injects a fake
 * socket, so the one line in production that *obtains* the socket from the
 * editor was never executed by any test, and it was wrong for two releases
 * (`globalThis.eda` is `undefined` in the extension host — see
 * `docs/bridge.md` §3.2). The suite was green throughout, which is what made
 * it expensive.
 *
 * `index.ts` now takes its editor through an injectable facade
 * (`__setFacadeForTests`), so the whole production path can be driven here with
 * a stand-in host: activate → resolve config → generate a token → register a
 * socket → answer the daemon's banner with `hello`.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { createFacade } from '../dist/esm/facade.mjs';
import * as connector from '../dist/esm/index.mjs';

/** Mirrors the official `eda.sys_WebSocket` signature. */
class FakeSocket {
  constructor() {
    this.registered = [];
    this.sent = [];
    this.closed = [];
  }

  register(id, uri, onMessage, onConnected) {
    this.registered.push({ id, uri });
    this.onMessage = onMessage;
    this.onConnected = onConnected;
  }

  send(id, data) {
    this.sent.push({ id, frame: JSON.parse(data) });
  }

  close(id) {
    this.closed.push(id);
  }

  async deliver(frame) {
    await this.onMessage?.({ data: JSON.stringify(frame) });
  }

  frame(action) {
    return this.sent.find((entry) => entry.frame.action === action)?.frame;
  }
}

const EDITOR_VERSION = '3.2.149.88089769';

/** A stand-in editor host, shaped like the real one but wholly in-process. */
function fakeHost(stored = {}, random) {
  const socket = new FakeSocket();
  const logs = [];
  const toasts = [];
  const dialogs = [];
  const written = [];
  const host = {
    sys_WebSocket: socket,
    sys_Log: { add: (line) => logs.push(line) },
    sys_Message: { showToastMessage: (message) => toasts.push(message) },
    sys_Environment: { getEditorCurrentVersion: () => EDITOR_VERSION },
    // Only present when a test wants to prove the no-Web-Crypto path. Absent,
    // the facade reads the ambient realm — Node has Web Crypto, like a browser
    // and unlike the extension host that broke on 2026-09-13.
    ...(random ? { random } : {}),
    sys_Storage: {
      getExtensionUserConfig: (key) => stored[key],
      setExtensionUserConfig: async (key, value) => {
        // Really stores it. A write-only fake would make `rePair` look broken
        // (clear the token, read the old one straight back) and `activate`
        // look fine, which is the opposite of the real editor's behaviour.
        stored[key] = value;
        written.push([key, value]);
        return true;
      },
    },
    sys_Dialog: {
      showInformationMessage: (message, title) => dialogs.push({ message, title }),
    },
  };
  return { host, socket, logs, toasts, dialogs, written };
}

/** Install a facade for one test, and guarantee its timers are cleaned up. */
function withHost(t, stored, random) {
  const parts = fakeHost(stored, random);
  connector.__setFacadeForTests(createFacade(parts.host));
  t.after(() => {
    connector.deactivate();
    connector.__setFacadeForTests(undefined);
  });
  return parts;
}

const BANNER = {
  event: 'banner',
  data: { server: 'boardwise', protocol: '1.0', expect: 'hello' },
};

test('activate obtains the socket from the editor and registers it', async (t) => {
  const { socket } = withHost(t);

  await connector.activate();

  assert.equal(socket.registered.length, 1, 'the editor socket must be used');
  assert.equal(socket.registered[0].uri, 'ws://127.0.0.1:61190/eda');
  assert.match(socket.registered[0].id, /^boardwise-\d+$/);
});

test('the daemon banner is answered with a hello carrying a generated token', async (t) => {
  const { socket, written } = withHost(t);

  await connector.activate();
  await socket.deliver(BANNER);

  const hello = socket.frame('hello');
  assert.ok(hello, 'the banner must trigger hello');
  assert.equal(hello.params.role, 'connector');
  assert.equal(hello.params.client, `boardwise-connector/${EDITOR_VERSION}`);
  assert.match(hello.params.token, /^[0-9a-f]{64}$/, 'a fresh 32-byte secret');
  // Stored under one self-describing key, so a reload reuses it instead of
  // re-pairing the daemon — and so the source survives the reload with it. Not
  // a token key beside a source key: that pair is what half-wrote itself on a
  // real editor (2026-09-13).
  assert.deepEqual(written, [['token', `webcrypto:${hello.params.token}`]]);
});

test('an already stored token is reused rather than regenerated', async (t) => {
  // A bare 64-hex value, i.e. exactly what 0.2.2 left behind: upgrading to
  // 0.2.3 must read it, not re-pair.
  const stored = { token: 'b'.repeat(64) };
  const { socket, written } = withHost(t, stored);

  await connector.activate();
  await socket.deliver(BANNER);

  assert.equal(socket.frame('hello').params.token, 'b'.repeat(64));
  assert.deepEqual(written, [], 'nothing needed generating');
});

test('the token is written under exactly one key, never a pair', async (t) => {
  // The regression guard for the measured partial write: 0.2.1 wrote `token`
  // then `token.source`, and a real editor kept the second without the first.
  const { socket, written } = withHost(t);

  await connector.activate();
  await socket.deliver(BANNER);

  assert.deepEqual(
    written.map(([key]) => key),
    ['token'],
    'a second key is a second chance to half-write',
  );
  assert.match(
    String(written[0][1]),
    /^(webcrypto|math):[0-9a-f]{64}$/,
    'the stored value must carry its own provenance',
  );
});

test('a host with no Web Crypto still connects, and says what it used', async (t) => {
  // The real editor on 2026-09-13: bare `crypto` did not resolve in the
  // extension realm, so 0.2.0 generated nothing and `About…` reported only
  // "cannot generate one" with no reason. It must fall back, work, and disclose.
  const { socket, logs, written, dialogs } = withHost(t, {}, { crypto: undefined });

  await connector.activate();
  await socket.deliver(BANNER);

  const hello = socket.frame('hello');
  assert.ok(hello, 'the connector must still reach the daemon');
  assert.match(hello.params.token, /^[0-9a-f]{64}$/);
  assert.deepEqual(written, [['token', `math:${hello.params.token}`]]);

  // Loud, in the log panel — a weak source is never silent.
  assert.ok(
    logs.some((line) => /Math\.random/.test(line) && /CSPRNG/.test(line)),
    `no warning in the log: ${JSON.stringify(logs)}`,
  );

  // And honest in About…, which still must not print the token.
  connector.about();
  const text = dialogs.at(-1).message;
  assert.match(text, /Math\.random/);
  assert.ok(!text.includes(hello.params.token), 'About… must not leak the token');
});

test('About… and the log panel explain a host with no random source at all', async (t) => {
  const { dialogs, logs } = withHost(t, {}, { crypto: undefined, mathRandom: undefined });

  await connector.activate();
  connector.about();

  // The log panel is the only window a user has in the editor, so the reason
  // has to be there, not just in About….
  assert.ok(
    logs.some((line) => /crypto=unavailable/.test(line)),
    `the log panel must name the reason: ${JSON.stringify(logs)}`,
  );

  const text = dialogs.at(-1).message;
  assert.match(text, /NONE/);
  assert.match(text, /crypto=unavailable/, 'say why, not merely that it failed');
});

test('About… says whether the editor ever called activate()', async (t) => {
  // Without this line, "no token" is ambiguous: nobody tried, or the try failed.
  // 0.2.1 could not tell those apart and spent a round trip on the wrong one.
  const { dialogs } = withHost(t);

  connector.about();
  assert.match(dialogs.at(-1).message, /activation: NEVER RAN/);
  // Also, when this copy of the module was evaluated — the tell for an editor
  // that loaded the bundle twice and now runs two of us.
  assert.match(dialogs.at(-1).message, /loaded: \d\d:\d\d:\d\d/);

  await connector.activate();
  connector.about();
  assert.match(dialogs.at(-1).message, /activation: \d\d:\d\d:\d\d ok/);
});

test('a self-arm connects even though the editor never called activate()', async (t) => {
  // The measured failure of 2026-09-13: menus worked (the editor reads the
  // `registerFn` exports) but `onStartupFinished` never fired on an extension
  // reload, so nothing ever connected and `About…` said `NEVER RAN`.
  const { socket, logs, dialogs } = withHost(t);

  await connector.__selfArmForTests();

  assert.equal(socket.registered.length, 1, 'the self-arm must open the socket itself');
  await socket.deliver(BANNER);
  assert.match(socket.frame('hello').params.token, /^[0-9a-f]{64}$/);

  // Loud, and honest: the editor still never activated, and we say so.
  assert.ok(
    logs.some((line) => /activate\(\) was not called/.test(line)),
    `the log must explain the workaround: ${JSON.stringify(logs)}`,
  );
  connector.about();
  const text = dialogs.at(-1).message;
  assert.match(text, /activation: NEVER RAN — self-connected at \d\d:\d\d:\d\d/);
});

test('the self-arm stands down when the editor did call activate()', async (t) => {
  const { socket } = withHost(t);

  await connector.activate();
  await connector.__selfArmForTests();

  assert.equal(socket.registered.length, 1, 'one socket, not two');
});

test('the self-arm is a no-op when there is no editor to reach', async (t) => {
  // The Node path: `eda` does not exist, so arming would only produce noise.
  connector.__setFacadeForTests(undefined);
  t.after(() => connector.__setFacadeForTests(undefined));

  await connector.__selfArmForTests();

  assert.equal(connector.getStatus().state, 'idle');
});

test('About… reports a stored token even before anything has run', async (t) => {
  // The 0.2.3 regression, measured on the machine: the box resolved the config
  // through a facade that did not exist yet, so `token:` said NONE while
  // `storage:` — evaluated later in the same function, through `host()` — showed
  // the very token. One box, two store views; the store was fine.
  const stored = { token: `webcrypto:${'e'.repeat(64)}` };
  const { dialogs } = withHost(t, stored);

  connector.about(); // no activate, no self-arm — the first thing that ever runs

  const text = dialogs.at(-1).message;
  assert.match(text, /token: storage, 64 characters/);
  assert.ok(!text.includes('NONE'), `the box contradicted its own storage line: ${text}`);
});

test('opening About… arms the connection when activation never ran', async (t) => {
  // The menus are the one entry point measured to work without activation, so a
  // menu click is the one arm trigger a timer-discard-happy host cannot swallow.
  const { socket } = withHost(t);

  connector.about();
  await connector.__selfArmForTests(); // the in-flight arm, not a new one

  assert.equal(socket.registered.length, 1, 'a menu click must be enough to connect');
});

test('a self-arm probe that finds no editor is recorded, not swallowed', async (t) => {
  // 0.2.3 returned silently from this branch, and on the machine the probes
  // then vanished without a trace — `About…` showed a bare NEVER RAN 13 s after
  // load with no way to tell "probes ran and missed" from "nothing ran".
  const { logs, dialogs } = withHost(t);

  await connector.__selfArmForTests({ hostPresent: false });

  assert.ok(
    logs.some((line) => /self-arm test: editor global not reachable/.test(line)),
    `the miss must reach the log panel: ${JSON.stringify(logs)}`,
  );
  connector.about();
  assert.match(
    dialogs.at(-1).message,
    /self-arm: test: editor global not reachable/,
    'the box must say what the fallback tried',
  );
});

test('the self-arm stands down instead of claiming a connection it did not make', async (t) => {
  const { dialogs, host, socket } = withHost(t, { autoConnect: false });

  await connector.__selfArmForTests();

  connector.about();
  const text = dialogs.at(-1).message;
  assert.match(text, /arm stood down: auto-connect is off/);
  assert.ok(!text.includes('self-connected'), `it must not claim success: ${text}`);

  // And the claim is released: re-enable auto-connect and arm again — this time
  // the socket opens.
  await host.sys_Storage.setExtensionUserConfig('autoConnect', true);
  await connector.__selfArmForTests();

  assert.equal(socket.registered.length, 1, 'the released claim lets the second arm connect');
});

test('a manual reconnect claims the attempt, so the self-arm never doubles the socket', async (t) => {
  const { socket } = withHost(t);

  await connector.reconnect();
  await connector.__selfArmForTests();

  assert.equal(socket.registered.length, 1, 'one manual connect, one registration');
});

test('a failing activation is logged and toasted, never silent', async (t) => {
  const parts = withHost(t);
  // The type declarations say these storage methods throw outside a real
  // extension context. If that happens here, activation must not vanish: an
  // unhandled rejection in the editor host is completely invisible.
  parts.host.sys_Storage.getExtensionUserConfig = () => {
    throw new Error('storage unavailable in this context');
  };

  await connector.activate();

  assert.match(
    parts.logs.join('\n'),
    /activate FAILED: Error: storage unavailable in this context/,
  );
  assert.ok(parts.toasts.length > 0, 'the user must be told, not just the log');

  // And About… still produces a box, naming the cause rather than hiding it.
  connector.about();
  const text = parts.dialogs.at(-1).message;
  assert.match(text, /activation: \d\d:\d\d:\d\d FAILED/);
  assert.match(text, /storage unavailable in this context/);
});

test('About… reports whether the token store is readable, never the token', async (t) => {
  const { dialogs, socket } = withHost(t);

  connector.about();
  assert.match(dialogs.at(-1).message, /storage: readable \(token=unset\)/);

  // The first `about()` armed the connection (void); await that in-flight
  // attempt rather than hoping its microtask chain has drained — `activate()`
  // below is a no-op (the arm claimed the attempt) and resolves immediately.
  await connector.__selfArmForTests();
  await connector.activate();
  await socket.deliver(BANNER);
  const token = socket.frame('hello').params.token;

  connector.about();
  const text = dialogs.at(-1).message;
  // Summarised, so the user can tell "stored, and how it was made" from
  // "nothing there" — which is the difference the partial write hid.
  assert.match(text, /storage: readable \(token=webcrypto, 64 characters\)/);
  assert.ok(!text.includes(token), 'About… must never print the token');
});

test('the pairing fingerprint from the daemon is surfaced, never the token', async (t) => {
  const { socket, logs, dialogs } = withHost(t);

  await connector.activate();
  await socket.deliver(BANNER);
  const token = socket.frame('hello').params.token;

  await socket.deliver({
    id: 'hello',
    ok: true,
    data: { role: 'connector', protocol: '1.0', paired: true, fingerprint: '53cd3b41' },
  });

  assert.equal(connector.getStatus().state, 'connected');
  assert.equal(connector.getStatus().fingerprint, '53cd3b41');
  assert.ok(logs.some((line) => line.includes('fingerprint 53cd3b41')), logs.join('\n'));

  connector.about();
  const about = dialogs.at(-1).message;
  assert.ok(about.includes('53cd3b41'), about);
  assert.ok(about.includes('connected'), about);
  // The whole point: the user can read this box and the log panel freely.
  assert.ok(!about.includes(token), 'the About box must never show the token');
  assert.ok(!logs.join('\n').includes(token), 'nor may the log panel');
});

test('a refused hello is reported instead of looking connected', async (t) => {
  const { socket, logs, dialogs } = withHost(t);

  await connector.activate();
  await socket.deliver(BANNER);
  await socket.deliver({
    id: 'hello',
    ok: false,
    error: { code: 'UNAUTHENTICATED', message: 'not the paired connector' },
  });

  assert.equal(connector.getStatus().state, 'reconnecting');
  assert.ok(
    logs.some((line) => line.includes('UNAUTHENTICATED')),
    `the reason must be readable in the log panel: ${logs.join('\n')}`,
  );

  connector.about();
  assert.ok(dialogs.at(-1).message.includes('reconnecting'));
});

test('rePair drops the stored token so the next connect offers a new one', async (t) => {
  const { socket, written, logs } = withHost(t, { token: 'c'.repeat(64) });

  await connector.activate();
  assert.equal(socket.frame('hello'), undefined, 'nothing sent before the banner');

  await connector.rePair();
  await socket.deliver(BANNER);

  assert.ok(
    written.some(([key, value]) => key === 'token' && value === ''),
    'the old token must be cleared',
  );
  const offered = socket.frame('hello').params.token;
  assert.match(offered, /^[0-9a-f]{64}$/);
  assert.notEqual(offered, 'c'.repeat(64), 'a different token is offered');
  assert.ok(logs.some((line) => line.includes('re-pair')), logs.join('\n'));
});

test('auto-connect off means no socket is opened', async (t) => {
  const { socket, logs } = withHost(t, { autoConnect: false });

  await connector.activate();

  assert.deepEqual(socket.registered, []);
  assert.ok(logs.some((line) => line.includes('auto-connect is off')));
});

test('the module bootstrap connects when an editor is present, and only once', async (t) => {
  // 004d's measured host rules: a chain initiated during the module's
  // synchronous evaluation survives (one ran a 48-minute reconnect loop on its
  // own); timers and menu-click async chains do not. So the connect starts at
  // evaluation — this is the primary path, not a fallback.
  const { socket } = withHost(t);

  await connector.__bootstrapForTests();
  await connector.__bootstrapForTests(); // a re-evaluation must not double up

  assert.equal(socket.registered.length, 1, 'one bootstrap, one socket');
  await socket.deliver(BANNER);
  assert.match(socket.frame('hello').params.token, /^[0-9a-f]{64}$/);
});

test('the bootstrap stands down when no editor is bound at evaluation time', async (t) => {
  // The Node shape, and the host shape if `eda` binds after evaluation. It must
  // record that it skipped rather than connect to nothing.
  connector.__setFacadeForTests(undefined);
  t.after(() => connector.__setFacadeForTests(undefined));

  await connector.__bootstrapForTests();

  assert.equal(connector.getStatus().state, 'idle', 'nothing was dialled');
});

test('the menu items in the manifest all exist as exports', async () => {
  // `registerFn` is looked up by name on this module, so a rename in
  // extension.json without a matching export is a dead menu item at runtime —
  // and nothing else would notice, because the editor just does nothing.
  const { readFileSync } = await import('node:fs');
  const manifest = JSON.parse(
    readFileSync(new URL('../extension.json', import.meta.url), 'utf8'),
  );
  const names = new Set(
    Object.values(manifest.headerMenus)
      .flat()
      .flatMap((menu) => menu.menuItems.map((item) => item.registerFn)),
  );
  assert.ok(names.size > 0, 'the manifest declares no menu items?');
  for (const name of names) {
    assert.equal(
      typeof connector[name],
      'function',
      `extension.json registers "${name}" but index.ts does not export it`,
    );
  }
  // The removed dialog flow must not come back through the manifest.
  assert.ok(!names.has('setToken'), 'Set token… was replaced by automatic pairing');
  assert.ok(names.has('rePair'));
});

test('no editor at all is survivable', async (t) => {
  // Node has no `eda`. `activate()` still has to report rather than throw —
  // otherwise an editor that binds its globals late produces a blank failure.
  connector.__setFacadeForTests(createFacade({}));
  t.after(() => connector.__setFacadeForTests(undefined));

  await connector.activate();

  assert.equal(connector.getStatus().state, 'reconnecting');
  assert.ok(String(connector.getStatus().lastError).includes('unavailable'));
});

// --------------------------------------------------------------------------
// 004f item 3 — the bootstrap blind spot (P0)
// --------------------------------------------------------------------------

/** Poll until `predicate` holds; a fixed sleep guesses at someone else's clock. */
async function waitFor(predicate, timeout = 4000, interval = 20) {
  const deadline = Date.now() + timeout;
  for (;;) {
    if (await predicate()) return true;
    if (Date.now() > deadline) return false;
    await new Promise((resolve) => setTimeout(resolve, interval));
  }
}

test('a bootstrap that throws is logged instead of dying in silence', async (t) => {
  // The blind spot this pins: `void bootstrapAtModuleLoad()` had no `catch`,
  // so a rejection inside the very first connect attempt left the extension
  // dead for the rest of the editor's life — `activate()`, the self-arm and
  // Reconnect are all no-ops once the claim is taken, and nothing anywhere said
  // why. On the machine that looks exactly like "only restarting the editor
  // helps", because restarting is the one thing that re-runs the bootstrap.
  const parts = withHost(t);
  parts.host.sys_Storage.getExtensionUserConfig = () => {
    throw new Error('storage unavailable in this context');
  };

  await connector.__bootstrapForTests();

  assert.match(
    parts.logs.join('\n'),
    /bootstrap FAILED: Error: storage unavailable in this context/,
    'the failure reaches the log panel — the one sink the user can read',
  );
  assert.match(
    parts.logs.join('\n'),
    /bootstrap retry 1 in 250 ms/,
    'and it does not stop there silently',
  );
});

test('a failed bootstrap releases the claim, so the next attempt can connect', async (t) => {
  const parts = withHost(t);
  const readable = parts.host.sys_Storage.getExtensionUserConfig;
  parts.host.sys_Storage.getExtensionUserConfig = () => {
    throw new Error('not ready yet');
  };

  await connector.__bootstrapForTests();
  assert.equal(parts.socket.registered.length, 0, 'the first attempt failed');

  // The editor settles. Until 004f the claim stayed taken forever, so this
  // second attempt was a no-op and the extension never recovered.
  parts.host.sys_Storage.getExtensionUserConfig = readable;
  await connector.activate();
  assert.equal(parts.socket.registered.length, 1, 'the claim was released');
});

test('the bootstrap retries instead of standing down when the editor is late', async (t) => {
  // The other half: at module evaluation `eda` may not be bound yet. The old
  // code recorded the stand-down and then waited forever for `activate()`,
  // which this host does not reliably call.
  const parts = fakeHost();
  connector.__setFacadeForTests(undefined);
  t.after(() => {
    connector.deactivate();
    connector.__setFacadeForTests(undefined);
  });

  // No facade, and Node has no ambient `eda`: the bootstrap stands down — and
  // schedules a retry rather than treating the answer as final.
  await connector.__bootstrapForTests();
  assert.equal(parts.socket.registered.length, 0, 'nothing to connect to yet');

  // The host binds its global a moment later; the retry must find it.
  connector.__setFacadeForTests(createFacade(parts.host));
  assert.ok(
    await waitFor(() => parts.socket.registered.length > 0),
    'the startup nudge connects once the editor is reachable',
  );
});
