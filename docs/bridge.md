# boardwise bridge — protocol & operations

Status: v0, 2026-09-12, revised 2026-09-13. Scope: task 004 (read-mostly bridge), 004b
(message-driven handshake + log-panel diagnostics), the on-machine fix that followed
(`eda.sys_WebSocket` resolved from the extension's own scope, not `globalThis`), 004c
(connector 0.2.0 — automatic TOFU pairing, no typed secret, Origin evidence gathering), and
0.2.1/0.2.2 (the token's source is now detected, disclosed and fallen back on — **and a wrong
first diagnosis of why it was missing, withdrawn; see §10.14**), 0.2.3 (one atomic storage key;
a self-arm for an editor that never calls `activate()`), and 0.2.4 (**the 0.2.3 machine run
disproved the half-write theory and exposed the real About… bug — one box, two store views;
probes now observable; the menu click is the guaranteed arm** — §10.19, §10.20, §10.21), and
0.2.5 (004d revision: **the connect starts at module evaluation — the one window measured to
survive — timer probes deleted, the menu click demoted to a safety net**; §10.20).
Implementation: `src/boardwise/bridge/` (Python daemon + client), `connector/` (TypeScript
extension), `boardwise bridge` CLI.

## 1. What the bridge is for

Offline parsing (`boardwise review`) answers "is this design right?" from a file. The bridge
answers the two questions a file cannot:

- **What is open right now?** — which project / document / tab the user is looking at.
- **Can we point at it?** — a native screenshot of the live canvas, and markers drawn on the
  exact primitives a finding refers to.

Read-mostly through v0 (004–004d): the only thing that touched the design was `canvas.highlight`
— *indicator markers*, an overlay, not primitives. Task 006 (the draw flow) then added a
deliberate, gated set of schematic write actions (`sch.doc.new`, `sch.place_*`) that only the
explicit `boardwise draw` / `bridge call` entry points can drive; see [`docs/draw.md`](draw.md)
for the risk decisions behind them.

## 2. Topology

Three processes, one listening socket:

```
  EasyEDA Pro (one per open window)  ───────────────────────┐
  ┌──────────────────────────┐                              │ eda.* API (in-process)
  │ boardwise connector      │  TypeScript, dist/index.js   │
  │ (.eext, in the editor)   │  ← the only code with hands  │
  └────────────┬─────────────┘                              │
               │  outbound WebSocket (each window dials out) │
               │  ws://127.0.0.1:61190/eda                 │
  ┌────────────▼─────────────┐
  │ boardwise daemon         │  `boardwise bridge start`
  │ (Python, websockets)     │  auth · window hub · routing · audit
  └────────────┬─────────────┘
               │  same protocol, role="cli", short-lived
  ┌────────────▼─────────────┐
  │ boardwise CLI            │  status · call --project/--instance · screenshot
  └──────────────────────────┘
```

Every open EasyEDA window runs its own copy of the extension and dials the daemon itself, so a user
with three windows has three connector sockets. The daemon registers **all** of them (023, §3.5) and
routes each call to the window whose project the caller named.

Why the editor dials *out*: an extension cannot open a listening socket, and `eda.sys_WebSocket`
only offers outbound registration. So the daemon is the server and the editor is a client that
reconnects forever. This is the same shape `easyeda-agent` uses.

The connector is the only component that touches `eda.*`. The daemon never opens a file inside
the editor; it only forwards frames and relays answers.

## 3. Transport and framing

- WebSocket over `127.0.0.1`. One JSON object per **text** message. No binary frames.
- The daemon accepts **any request path** and ignores query strings — measured, not assumed:
  connecting to `/`, `/eda` and `/a/b?foo=1` all reach the same handler (see §12). Both sides
  dial `/eda` anyway, because that is the spelling observed working in `easyeda-agent`.
- Frame size cap: **32 MiB** (`MAX_FRAME_BYTES`). The `websockets` default of 1 MiB is smaller
  than a base64 screenshot, which is why it is raised.
- The daemon sets `ping_interval=None`: liveness is an application-level concern (§7), not a
  WebSocket-level one.

### 3.1 Envelope

Three kinds of frame share one envelope, told apart by which key is present:

| kind | key | direction | example |
|---|---|---|---|
| request | `action` | either → either | asks for something |
| response | `ok` | either → either | answers a request |
| event | `event` | daemon → client | unsolicited notification |

Precedence when classifying: **`ok` > `event` > `action`**, so a frame that somehow carries two
of them behaves predictably. Both sides classify it the same way (`frame_kind` in
`protocol.py`, `frameKind` in `connector/src/protocol.ts`) — if they disagreed, the banner
would be read as a request and answered with `BAD_REQUEST`.

Request — `params` is omitted when there is nothing to send, and `targetProject` / `targetInstance`
(023, §3.5) are omitted unless the caller is naming a window:

```json
{"id": "pcb.readback-9f2a1c04", "action": "pcb.readback", "params": {"includePrimitives": true}}
{"id": "doc.list-1a2b3c", "action": "doc.list", "targetProject": "test2"}
{"id": "doc.list-4d5e6f", "action": "doc.list", "targetInstance": "inst-101500123-aaaaaaaa"}
```

Success — `context` (023) is the answering window's live identity, a sibling of `data` rather than
part of it, and it is omitted when the window named nothing:

```json
{"id": "pcb.readback-9f2a1c04", "ok": true, "data": {"kind": "pcb", "componentCount": 17, "...": "..."},
 "context": {"projectName": "test2", "projectUuid": "uuid-…", "pageUuid": "page-…", "pageType": "pcb"}}
```

Failure — the same two optional fields may appear, so a refusal is attributable to the window it
came from (`WINDOW_UNSPECIFIED` and friends have no window, so they carry no `context`):

```json
{"id": "pcb.readback-9f2a1c04", "ok": false,
 "error": {"code": "NO_CONNECTOR", "message": "pcb.readback needs the editor: no connector is connected. ..."}}
```

Event — no `id`, because nothing correlates with it:

```json
{"event": "banner", "data": {"server": "boardwise", "protocol": "1.0", "expect": "hello"}}
```

Rules both sides implement:

1. `id` correlates. It is echoed unchanged; a late answer is matched by id, and an answer with
   an unknown id is dropped, not treated as an error.
2. `ok` decides success or failure; the key's presence is what makes a frame an answer.
   Both sides send requests and answers over the same socket.
3. An event is **never** answered. A client that replies to one is talking to itself.
4. `detail` is optional and free-form; `code` and `message` are always present on a failure.
5. Anything that is not a JSON object is rejected with `BAD_REQUEST` — including arrays, which
   parse as JSON objects in some languages and are never valid frames.
6. `requestFrame` omits empty `params` rather than sending `null`, so a request is exactly
   `{id, action}` when it has no arguments. This is the one byte-level detail both sides must
   agree on, and it has its own test on each side.

### 3.2 The banner, and why the daemon speaks first

**The daemon sends an event the instant a socket is accepted, before anything is asked of it.**

```json
{"event": "banner", "data": {"server": "boardwise", "protocol": "1.0", "expect": "hello"}}
```

The connector answers it with `hello`. Two *different* failures hid behind the one symptom ("the
editor never opens a TCP connection"). They are worth keeping apart, because their fixes are
unrelated — and because for a while the wrong one was believed to be the cause. **(a) is why the
socket never existed; (b) is a deadlock that (a) prevented us from ever reaching.**

**(a) The measured cause: `globalThis.eda` is `undefined` in the extension host.** The transport
built its socket handle as `this.options.socket ?? globalThis.eda?.sys_WebSocket`. Nothing passed
`options.socket`, so everything rested on that fallback — and the editor binds `eda` as a *context
global*, not a property of `globalThis`. Measured on the machine 2026-09-13 (probes in
`tools/probe1-surface.js`, `tools/probe2-register.js`): bare `eda` resolves, `globalThis.eda` is
`undefined`, and `globalThis.eda === eda` is **false**. So `socket` was `undefined`, `connect()`
took the `eda.sys_WebSocket is unavailable` branch, and `register` was *never called* — hence not
one TCP connection, ever. The same probes proved `register` does open a real socket when it is
reached from a scope where bare `eda` resolves. Fixed in 0.1.2 by passing the facade explicitly
and deleting the fallback: `eda.sys_WebSocket` is now the only source.

*(Generalisation, because this class of bug is cheap to reintroduce: a `??` fallback to a global
that happens to be unreachable is invisible. It does not throw, it does not warn — it just makes
the feature a no-op.)*

**(b) The connect callback is also unreliable — a real trap, but not the deadlock.** `hello` used
to be sent only from the editor's connect callback (the 4th argument of
`eda.sys_WebSocket.register`). It is not dependable, so the handshake must not hang off it. The
reference connector (`easyeda-agent`, which works in the same editor) passes an empty function
for that callback and tells liveness from **inbound frames**. Extracted from
`easyeda-agent-connector.eext` (`dist/index.js`), its registration is literally:

```js
eda.sys_WebSocket.register(
  wsId,
  `ws://127.0.0.1:${port}/eda`,
  async (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "handshake") { handshakeVerified = true; sendRegister(); ... }
    ...
  },
  () => { }        // <- the connect callback: deliberately empty
);
```

The handshake is driven entirely from the message handler; the callback is a no-op. Ours works
the same way, expressed in our envelope. This is what the banner is for: it makes the socket
speaking *first* a fact we can key on, rather than a callback we hope for.

**What task 004b actually delivered.** It did **not** fix the zero-TCP failure — 004b shipped
0.1.1 with (b) fixed and (a) still present, and the next hardware attempt still produced no
connection. What it delivered is the *visibility* that made (a) findable: diagnostics moved to
`eda.sys_Log` (§6), where the reason for each reconnect is readable inside the editor instead of
going to a `console.log` nobody can open. The hourly gap between "004b done" and "root cause
found" is the cost of a silent failure, and this section exists so that cost is not paid twice.

Consequences worth stating plainly:

- **Any inbound frame triggers `hello`**, not just the banner. Traffic is proof the socket is up
  end to end; a callback is an opinion. The trigger is idempotent, so the callback firing *and*
  the banner arriving still produce exactly one `hello` (a second one is a `PROTOCOL_VIOLATION`).
- **The heartbeat starts after `hello` goes out**, never on the callback.
- The callback is kept, demoted to advisory: a free early trigger when it works.

The banner carries no secret and no `id`. It arrives before authentication, so it may only state
what is already public about the daemon, and there is nothing for it to correlate with.

### 3.3 Handshake

Every connection — connector or CLI — must open with `hello` as its **first request**, i.e. the
first frame carrying an `action`. The banner does not count; it is an event, not a request.
The connector sends `hello` with the fixed id `"hello"`; the daemon answers with the same id.

```json
→ {"event": "banner", "data": {"server": "boardwise", "protocol": "1.0", "expect": "hello"}}
← {"id": "hello", "action": "hello",
   "params": {"token": "…64 hex…", "role": "connector",
              "protocol": "1.0", "client": "boardwise-connector/3.2.121",
              "connectorVersion": "0.4.1",
              "instanceId": "inst-112233445-9k2f0x1a"}}
→ {"id": "hello", "ok": true,
   "data": {"role": "connector", "protocol": "1.0", "serverTime": 1789000000.0,
            "paired": true, "fingerprint": "53cd3b41",
            "minConnectorVersion": "0.4.10",
            "windowsOnline": 2, "windowKey": "inst-112233445-9k2f0x1a"}}
```

`connectorVersion` is the connector's **own** build (`__BOARDWISE_VERSION__`,
baked in by `build.mjs`), not the editor's — the `client` field already names
the editor. Added in 004f so that every connection leaves "which build was
running?" in the audit log: twice a sideload that did not take looked
successful while the editor kept executing the previous bundle, and the only
symptom was a stack pointing at a line that had already been fixed. It is
**optional**: a connector that does not send it is accepted and recorded as
`connector=<version unknown>`.

`instanceId` names the **extension instance** (018 §A), not the build: it is
generated once when the bundle is evaluated (`connector/src/index.ts`) and is
stable across reconnects, so the daemon can tell "the same editor came back"
from "a second editor window appeared". Since **023** it is also the daemon's
**hub key**: every authenticated connector is registered rather than refused
(§3.5), and this id is how a call is routed to one of them. Two windows sharing
one id — the 3.2.175 double activation — are both kept, the second under a
suffixed key (`inst-…~2`), because a dropped connection is a window the user has
and the AI cannot see. The ack's `windowsOnline` says how many windows the
daemon holds after this one joined, and `windowKey` says what this connection is
called (`null` for a CLI connection). Also **optional**: without an
`instanceId` the daemon falls back to its connection-level uuid, which still
distinguishes live connections but not reconnects of the same one.

`minConnectorVersion` is the **ack's** half of that negotiation (018 §B3): the
oldest connector build the daemon will vouch for. The connector compares it
with its own `VERSION` on every accepted handshake and, when it is older, says
so in the editor's log panel **and** as a toast — never silently, because the
failure it prevents is a version skew that looks like a mysteriously broken
action. Three cases are deliberately *not* warnings:

- the field is **absent** — the daemon has not stated a minimum, so nothing is
  claimed in either direction (and a reading from an earlier daemon is
  discarded, so it cannot outlive the connection that produced it);
- the two values cannot be compared (a build whose `VERSION` is `unknown`),
  which is logged as an unanswerable comparison rather than reported as a
  verdict;
- the connector is **newer**, which is logged as satisfied.

**Status of the field.** The daemon side landed with 018 §A: the ack carries
`minConnectorVersion`, and its value is the daemon's own `MIN_CONNECTOR_VERSION`
constant, equal to the shipped connector version today — so nothing is refused
*now*, and the field exists for the day a protocol change makes an old bundle
dangerous. It is **announced, not enforced**: the daemon still answers an older
connector, which is why the connector's job here is to *say so* rather than to
stop working. (The refusal path for a version would have to run before the
token check, and a version comparison is not a reason to hang up on a connector
that still works.)

The daemon checks, **in this order**, and closes the socket on the first failure. The order is
load-bearing, not incidental — see §3.4 for why the version check precedes the secret:

| Check | Failure code |
|---|---|
| A frame arrived within `HELLO_TIMEOUT` (**5 s**) | `UNAUTHENTICATED` ("no hello within 5s") |
| `action == "hello"` | `PROTOCOL_VIOLATION` |
| `params` is an object | `BAD_REQUEST` |
| `role` is `connector` or `cli` | `BAD_REQUEST` |
| `token` is a non-empty string | `UNAUTHENTICATED` |
| `protocol` major version matches the daemon's | `VERSION_MISMATCH` |
| the secret matches, per role (`secrets.compare_digest`) | `UNAUTHENTICATED` |

Five seconds rather than ten, because the daemon speaks first: silence is now unambiguous — the
client was addressed and did not answer, so the fault is on its side. The reference daemon
allows 1.5 s; we are more generous only because a freshly started editor can be busy loading a
board.

Failures are answered with an error frame **before** the close, so the client can log a reason
instead of seeing a bare disconnect.

Two more rules:

- `hello` sent later in the session is a `PROTOCOL_VIOLATION` — it is a handshake, not a verb.
- **Every** connector that authenticates is **registered** in the daemon's window hub (023, §3.5).
  Until 2026-09-22 a second one was refused with `CONNECTOR_ALREADY_ACTIVE` — the fix for two windows
  taking turns in a single slot, where each write landed in whichever project the winning window had
  focused. Refusing was the wrong fix for the machine this runs on: a hardware engineer opens three
  or four windows as a matter of course. Contention is now answered by **routing** instead of by
  exclusion — the caller names the project it means, and a request that names none while several
  windows are online is refused (`WINDOW_UNSPECIFIED`) rather than sent to a plausible one. See §3.5
  for the routing rules and §5 for the codes.

The refusal code and the `connector_rejected` audit record it produced are **retired**: nothing
sends either any more, and both are kept only because connector builds in the field read the code.

### 3.4 Pairing: trust on first use

The CLI proves who it is with a secret it read off disk. A connector cannot: an editor extension
has no way to learn the OS home directory, so in v0 the user had to copy 64 hex characters out of
`~/.boardwise/token` and paste them into a dialog. As of 0.2.0 the connector **invents its own
secret** (32 random bytes, hex) and the daemon learns it the first time. Since 0.2.1 it also says
*which* source produced those bytes — Web Crypto, or the `Math.random` fallback it uses when Web
Crypto is unusable (see §9, and `connector/src/random.ts`):

```json
← {"id": "hello", "action": "hello",
   "params": {"token": "…64 hex, generated by the extension…", "role": "connector",
              "protocol": "1.0", "client": "boardwise-connector/0.2.1"}}
→ {"id": "hello", "ok": true,
   "data": {"role": "connector", "protocol": "1.0", "serverTime": …,
            "paired": true, "fingerprint": "53cd3b41"}}
```

| State of `~/.boardwise/connector-token` | What the daemon does |
|---|---|
| absent | **pairs**: writes the offered token, audits `pairing`, prints a loud line on the console |
| present, token matches | accepts |
| present, token differs, **a connector is attached** | `UNAUTHENTICATED` |
| present, token differs, **nothing is attached** | **re-pairs**: overwrites the record, audits `re-pairing`, announces the replacement (004f) |

The fourth row is the sideload self-heal. **Sideloading a connector build resets
the editor's extension storage**, so the new build generates a fresh token and
is then refused by a pairing it wrote itself on the previous run — an
`UNAUTHENTICATED` loop that used to need a manual `bridge revoke` every time.
With no connector attached the newcomer is displacing nobody, so it is accepted
and the replacement is announced *as a replacement*, with the fingerprint it
superseded. While a connector **is** attached the refusal stands: letting an
unknown token take over from a live peer is exactly what pairing exists to
prevent, and the error now says that instead of only quoting the revoke command.

Residual case, stated rather than hidden: **two connector instances alive at
once** (a sideload followed by *Reconnect* without a full editor restart leaves
the old bundle's socket up). Both are windows in the hub now (023, §3.5), so
both appear in `bridge status` — and if the new build wants to re-pair, it needs
either a real restart or the `Re-pair on next connect` menu item, because the
daemon will not pull the pairing out from under a live socket. If the two claim
one instance id, routing reports the ambiguity instead of picking one.

The console line is the whole safety mechanism, so it is fixed text:

```
boardwise bridge: paired new connector (fingerprint 53cd3b41); if this was not you, run: boardwise bridge revoke
```

`boardwise bridge revoke` deletes the file and audits `revoke`. The next connector re-pairs — a
reset, not a blocklist. That is deliberate: the command cannot tell "the connector I distrust"
from "the connector I just reinstalled", so it does the thing it can do honestly, which is make
the trust decision happen again where the user can watch.

Three properties that are easy to get wrong, and are not:

- **The connector token is a different file, and a different secret, from the CLI token.** Pairing
  a connector cannot weaken or leak the CLI credential, and a connector token never authenticates
  a `role: "cli"` caller (asserted in the suite).
- **An empty token never pairs.** Pairing is not a way in for a client with no random source of
  its own: the check happens before either branch, so `""` and `null` are refused and nothing is
  written. A hostile local process still has to invent a secret — it just does not have to be
  *our* secret anymore.
- **The version check precedes pairing.** Committing a pairing record for a connector we cannot
  talk to would lock out the working one that connects next, and the resulting
  `UNAUTHENTICATED` would name the wrong problem. A mismatched connector is refused and forgotten.
- **The token's provenance is recorded, never assumed.** 0.2.0 generated the secret and swallowed
  every failure, so when a real editor ended up with no token at all there was nothing to read
  (§10.14). 0.2.1/0.2.2 report the source (`webcrypto` / `math` / `none`) in the log panel, in
  `About…`, and beside the token in storage — so a weak token cannot hide behind a reload, and a
  missing one cannot hide behind silence. §9 says what the weaker source does and does not cost.

**Threat model.** The daemon is loopback-only, so what pairing resists is another *local process*
or a *web page* getting there first — not a process that can already read the user's home
directory, which has won regardless of anything this file says. Under that model, first-use trust
with a loud announcement and a one-command undo is the right strength: it removes the typed secret
without pretending to a guarantee the daemon cannot provide. The exposure window is the first
connection only, and it is visible in the console and in the audit log.

One rule changed with the hub (023): "a connector is attached" — the condition that blocks a
stranger's re-pairing — now means *any* live connector, not a single privileged one. The strength of
the rule is unchanged: an unknown token may only take over a pairing **nobody** is using, never one
a live window is connected with.

### 3.5 The window hub, and routing by project or instance (023)

The daemon keeps **every** authenticated connector. Each connection is a hub entry keyed by the
`instanceId` it claims, holding its socket and everything that window has said about itself; a
second, third or fourth EasyEDA window registers exactly like the first. Nothing is hidden: `ping`
returns one entry per window, `bridge status` prints one block each plus a `projects seen:` line, and
every `hello` / `disconnect` / forwarded call lands in the audit log with its `windowKey`.

**Context, kept fresh.** A window's identity is `{projectName, projectUuid, pageUuid, pageType}`.
It is announced in `hello` (021 §2.3) and then **refreshed by every action response** in a top-level
`context` object:

```json
← {"id": "doc.list-a1b2", "action": "doc.list", "params": {}}
→ {"id": "doc.list-a1b2", "ok": true, "data": {…},
   "context": {"projectName": "test2", "projectUuid": "uuid-…",
               "pageUuid": "page-…", "pageType": "sch"}}
```

The connector reads that context when it runs the action and **omits the keys it cannot read**: a
null, an empty string or an unknown key never overwrites a known value. That is what makes the
routing table follow 岳 switching project or document mid-session instead of freezing at the
handshake. `pageType` is the document domain (`sch` / `pcb`) and is the connector's vocabulary — the
daemon records what it is told and never translates it.

**Routing.** A caller names the window it wants, in one of two spellings:
`bridge call --project NAME_OR_UUID` (top-level `targetProject`) or `bridge call --instance
INSTANCE_ID` (top-level `targetInstance`). The daemon resolves the name to exactly one window, or
refuses:

| windows online | hint | result |
|---|---|---|
| ≥1 | `--instance`, matching a window's key or instance id | that window |
| ≥1 | `--instance`, matching none | `WINDOW_NOT_CONNECTED`; the message ends with the `projectName (instanceId)` of every online window |
| ≥1 | `--project`, matches exactly one window (by project **name** or **uuid**) | that window |
| ≥1 | `--project`, matches none | `PROJECT_NOT_CONNECTED`; the message ends with the same online-window list |
| ≥1 | `--project`, matches several | `PROJECT_AMBIGUOUS`; the message names the candidates — no "pick the newest" |
| ≥1 | both hints | the **instance** decides: it names one connection, a project name may be claimed by several |
| 1 | absent | that window — the pre-023 behaviour, byte for byte |
| ≥2 | absent | `WINDOW_UNSPECIFIED`; the message names the candidates |
| 0 | any | `NO_CONNECTOR` ("is EasyEDA running?") |

**Why the second spelling exists.** An instance id is the *window's own* name for itself and it
arrives in the `hello` params, so it is known from the first frame — while every project name is a
read the connector has to perform, and the editor can be up before its API is. Measured 2026-09-22
(023 follow-up): the editor restarts, three windows greet the daemon, and every context read comes
back null — each window is a row `(no project) (inst-…)` and **no** `--project` value matches
anything, including the window in front of the user. `--instance` is what still reaches a window
then; `bridge status` prints the key to use, and the two refusal messages above say so too. Keys
are matched, not guessed: when two live sockets claim one instance id the second is registered
under `inst-…~2`, and each of the two spellings reaches its own connection.

The answering window's live context comes back on the response frame — and on an error frame — as the
same top-level `context`, so a caller can see *which* window answered without a second call. The hint
itself never reaches `params`: it instructs the daemon about which window, it is not something the
connector is asked to do.

**Writes serialise per window.** Two writes into one editor queue (the editor is a single thread of
truth — two placements racing in one window is how a half-drawn page happens); writes into two
*different* windows run in parallel, which is the point of a hub; reads never take the lock at all.
Each forwarded call's audit record carries the `windowKey` it went to and that window's
`projectName`, because the window may be closed by the time anyone asks "which project did that write
land in?".

**What is retired.** 018's `CONNECTOR_ALREADY_ACTIVE` refusal, its `connector_rejected` audit record
and its Chinese console warning. The code stays in §5 — connector builds read it — but nothing sends
it. The console line was only ever necessary because the other windows were invisible everywhere
else.

**What is deferred.** Re-routing a retired window, deduplicating a double-activated window (it is
reported as `PROJECT_AMBIGUOUS` instead), and connector-pushed context changes — a response already
refreshes the context, which is enough until something wants live updates with no call in between.


## 4. Action catalogue

The catalogue is closed: an action not listed here is rejected with `UNKNOWN_ACTION` rather than
forwarded into the editor as an open-ended string. `owner` decides who executes it. `risk` decides
what may run unattended: `read` cannot change project content, `write` changes existing content,
and **`create`** produces a new document — the daemon refuses a `create` action unless
`params.confirm is True` (`CONFIRMATION_REQUIRED`), consuming the flag so it never reaches the
connector. `doc.delete_page` (012) is the one action that **removes** a document; it is classed
`write`, so the `create` gate above does not cover it — what guards it is the page-uuid check
(a uuid the project does not list is `NOT_FOUND`), not a confirmation flag.

Two tests keep this table honest: `connector/tests/contract-drift.test.mjs` asserts that
`ACTIONS`, the connector's handler registry and **this table** all list the same names
(both difference directions reported), and `tests/test_action_catalogue.py` checks the catalogue
against itself (unique names, the naming domain, valid `owner`/`risk`, every `create` action
declaring `confirm`).

| action | owner | risk | params | `data` on success | timeout |
|---|---|---|---|---|---|
| `hello` | daemon | read | daemon | `token`, `role`, `protocol`, `client` | `{role, protocol, serverTime}` | 30 s (`ACTION_TIMEOUT`) |
| `ping` | daemon | read | daemon | — | `{pong: true, version, connector: bool, pairedFingerprint: str\|null, windows: [obj]}` — `version` is the daemon's own build, so "the daemon answering me" and "the daemon my CLI was built from" can be told apart; `windows` (023, §3.5) is **one entry per online editor window** (oldest first), each with `windowKey`, `instanceId`, `instanceIdSource`, `connectorVersion`, `client`, `peer`, `connectedAt`, `lastSeen`, `routed` (calls it has answered), `projectName`, `projectUuid`, `pageUuid`, `pageType` — every optional field is `null`, never absent. `boardwise bridge status` renders it and adds nothing of its own; the pre-023 `activeInstance` / `recentRejections` keys are gone (no window is refused any more) | 30 s |
| `document.current` | connector | read | connector | — | `{project, pcb, schematicPage, active, type, typeSource, heuristic, tabs}` — `active` is the focused document, or **null** when none is focused (the host's placeholder uuid `"0"` is reported as `null` plus a `problems` line, as in `doc.list`); `typeSource`/`heuristic` say which read produced `type` (§10 item 5); when the host offers them, `active` also carries `projectUuid` / `libraryUuid` — the document's own `parentProjectUuid` / `parentLibraryUuid`, i.e. the channel that says which project the focused *document* belongs to, which is not always the project `doc.list` calls focused (`sys.identity`) | 30 s |
| `sys.identity` | connector | read | — | `{focusedProject, activeDocument, consistent, consistentBasis, pageUuid, readOnly, notes?}` — the editor's two identity layers side by side (018 §B): `focusedProject` is the project `doc.list` marks `focused` (`dmt_Project.getCurrentProjectInfo`), `activeDocument` is `getCurrentDocumentInfo`'s document plus the project it belongs to (`parentProjectUuid`, or the document's own per-kind info read when the host leaves that field empty). `consistent` compares the two project uuids and is **null** — never a hopeful `true` — when the comparison cannot be made, in which case `consistentBasis` says why (`no-active-document`, `unavailable`, or `focused-project-listing` when membership in the focused project's document list was the best available evidence). `pageUuid` is the active page's uuid. Read-only: nothing is opened, focused or written | 30 s |
| `sys.probe` | connector | read | connector | `checks`, `namespace`, `namespaces`, `functionsOnly`, `call` | `checks` mode: `{version, topLevel, checks: {NAME: {present, kind, checked, missing, status, arity, notes?}}}` — `status` is the member's `typeof` and `arity` its declared `fn.length` for the members that read back as functions; enumerate mode: `{version, topLevel, namespaces: {NAME: {present, ownNames, functions, data, errors?}}}` — **read-only** introspection of the live API surface; `call` mode (025): `{version, topLevel, call: {action, params, result}}` — runs one **allowlisted read-only** registered action and returns *that action's own* answer, which exists because the daemon's catalogue is a load-time constant (an action registered after the daemon started is unreachable via `bridge call --action` until it is restarted). The allowlist is closed and read-only so this channel can never bypass the daemon's `create` gate | 30 s |
| `sys.self_update` | connector | write | connector | `bundleB64`, `version` | `{ok, oldVersion, newVersion, bytes, database, reloadInMs}` — rewrites the connector's own bundle in IndexedDB and reloads the page (§8); **the permission grant is preserved** | 30 s |
| `sys.get_document_file` | connector | read | connector | `fileType`, `fileName`, `password`, `timeoutMs` | `{fileType, source, scope: 'document', encoding: 'base64', name, mime, bytes, data, isZip, note?}` — the open **document** as an `.epro`/`.epro2` archive (025): the online half of the offline pipeline, so the bytes go through `load_epru_text → build_schematic_model` unchanged. `scope` is reported because it was measured (2026-09-23): the archive holds the *focused page* plus the library documents it references, **not** the project. The declaration gates this call on **工程设计图 > 文件导出** and says a missing grant throws *every time*; the connector cannot read grants, so a refusal carries the host's own message plus the documented gate in `detail.gate`/`detail.permissions`, and `isZip` is reported rather than assumed (an `.epro2` whose first two bytes are not `PK` will not parse) | 30 s |
| `sys.get_project_file` | connector | read | connector | `fileType`, `fileName`, `password`, `timeoutMs` | `{fileType, source, scope: 'project', encoding: 'base64', name, mime, bytes, data, isZip, note?}` — the whole **project** in one archive (every page, every library document, the PCB), i.e. the tier-`project-file` payload `boardwise checkup` tries first. Gated on **工程管理 > 下载工程** — a *different* gate from `getDocumentFile`'s — so "the document export works" says nothing about this one; the same honest-refusal shape as above, with this call's own gate quoted | 30 s |
| `sys.get_document_source` | connector | read | connector | `maxChars` | `{source, chars, maxChars, truncated, data, headLines, tail?, note?}` — the focused document's own source text, **unjudged**: the declaration is one line (`Promise<string \| undefined>`, `@beta`) and says nothing about the format, so whether it equals the `.epru` record stream is a probe question (`outputs/025_probe_p2_document_source.txt`). Truncates to `maxChars` and echoes both ends — a stream is recognised by its first and last records, and a head without a tail cannot be told from a different format | 30 s |
| `sch.drc_check` | connector | read | connector | `strict`, `userInterface`, `includeVerboseError` | `{source, checked, mode: 'counts'\|'boolean'\|'unexpected', counts, entries?, total?, byType?, unparsed?, passed, elapsedMs, args, page, uiRequested, notes?, raw?}` — `sch_Drc.check(strict, false, true)`. (025 §0, measured) the host's verbose answer holds **aggregate counts only**; the per-item detail goes to the bottom panel and `SYS_PanelControl` has no read interface, so the array is returned **verbatim** under `counts` with `total`/`byType` summed from the entries' own fields and any entry lacking a numeric `count` counted in `unparsed` rather than folded in as zero. A boolean answer is mode `boolean`, never an empty result. Throws on a non-schematic page; the refusal names the focused document | 30 s |
| `pcb.drc_check` | connector | read | connector | `strict`, `userInterface`, `includeVerboseError`, `maxChars` | `{source, checked, available, mode: 'groups'\|'boolean'\|'unexpected', groups, counts: {groups, returnedGroups, errors, errorsSource, items, byLabel, jsonChars}, truncated, elapsedMs, args, page, uiRequested, reason?, notes?, raw?}` — `pcb_Drc.check(strict, false, true)`, the DRC that *does* carry item detail. **Measured 2026-09-23** (`outputs/025_probe_p4_pcb_drc.txt`): the tree is `group.list[].list[]`, every node states its own `count`, and a leaf carries `ruleName`/`errorType`/`explanation.str`/`obj1`/`obj2`/`globalIndex`/`parentId`. Groups come back **verbatim** for the Finding-mapping layer; whole groups are dropped (never cut in half) to stay inside `maxChars`. A non-PCB page is never reported as a clean board — the declaration promises `undefined`, the host actually **throws** `指定的主题消息在对应的画布内没有相关订阅`, and both become `checked: false` + a `reason` naming the focused document. An *empty* PCB is not a zero-finding board either: the test project's empty PCB answered one "Netlist Error / Import Changes" (schematic has parts, PCB does not) | 30 s |
| `sys.connector_status` | connector | read | connector | — | `{present, readStatus, status, moduleBootstrapObserved, activateObserved, evaluations}` — the About box's own read-out, for a caller who cannot open the box. `status` is the same `ConnectorStatus` the box renders (so the two can never disagree): the transport `state`, the daemon's `paired`/`fingerprint`/`minConnectorVersion`, the 024 lifecycle counters — **`moduleBootstrapObserved`** (was our bundle evaluated in this editor runtime at all?), **`activateObserved`** (did the host dispatch `activate()`?), **`evaluations`** (how many times the bundle was evaluated) — and, since 026b, **`watchdog`**: `{state: 'running'\|'unavailable'\|'not started'\|'stopped', reason?, wakes, activityPosts, checkIntervalMs, activityTimeoutMs}`. That last field is the one that answers "why did this window sit there for hours": `running` means a Worker alarm is watching the page, `unavailable(<reason>)` means the host refused one and the window recovers **only** when the user brings it to the front (§7). `present: false` means no evaluation has published its runtime record — an extension that is not loaded, which is a different failure from one that is loaded and inert. Read-only: it never starts, stops or reconnects anything | 30 s |
| `sch.readback` | connector | read | connector | `includePrimitives` | `{kind: 'sch', components, primitives, componentCount}` | 30 s |
| `pcb.readback` | connector | read | connector | `includePrimitives` | `{kind: 'pcb', components, primitives, componentCount}` | 30 s |
| `export.screenshot` | connector | read | connector | `fit` | `{format, encoding: 'base64', bytes, data}` — **diagnostic only**: cached frames | 60 s |
| `export.render` | connector | read | connector | `format`, `scope`, `ids`, `fileName`, `timeoutMs` | `{format: 'image/png'\|'image/svg+xml'\|'application/pdf'\|'zip', encoding, bytes, data, scope, note}` — the document render (`scope`: page\|selection\|project). `pageUuid` (0.4.22): which page the render is about — resolved as `pageUuid` ?? the **active document**, then **activated** via `dmt_EditorControl.openDocument` before the export (a page that was never activated hangs this host, on png and svg alike — §10.28); the answer carries `activatedPageUuid`, and a page that cannot be activated is an honest error with **no export attempted**. `timeoutMs` (0.4.20) clamps into 1..60 s and defaults to the 30 s constant; a call that runs out answers `TIMEOUT` whose leading hypothesis is **the page never having been activated**, with `params.pageUuid` as the way to be unambiguous (§10.28 — the earlier "PNG rasterisation stuck" / "format=svg will work" reading is withdrawn). Since **0.4.21** the action also retires the export's own progress toast ~400 ms after it answers, on **both** outcomes — on 3.2.149 the toast is left behind even by a *successful* export | 60 s |
| `canvas.highlight` | connector | read | connector | `uuids`, `color`, `clear` | `{highlighted, cleared, unresolved}` | 30 s |
| `sch.netlist` | connector | read | connector | `type` | `{type, source, size, text}` — the editor's own netlist | 60 s |
| `sch.geometry` | connector | read | connector | `bboxIds` | `{components, wires, pins, netlabels, bboxes, meta}` — raw `getState_*` dumps + **measured** sheet bbox | 60 s |
| `sch.doc.new` | connector | create | connector | `name` | `{schematicUuid, pageUuid}` | 60 s |
| `sch.place_component` | connector | write | connector | `lcsc` \| `deviceUuid`+`libraryUuid` \| `keyword`, `x`, `y`, `rotation`, `mirror`, `designator`, `pageUuid`, `timeoutMs` | `{uuid, device: {uuid, libraryUuid, name}, resolvedBy, elapsedMs}`; on a 30 s miss: `code: 'TIMEOUT'` with `{device, x, y, landedAnyway, landedCount, near}` | 60 s |
| `sch.place_wire` | connector | write | connector | `points` (`[[x,y],…]`), `net` | `{uuid, net, points}` | 60 s |
| `sch.place_netlabel` | connector | write | connector | `x`, `y`, `net`, `pageUuid`, `timeoutMs` | `{uuid, outcome, elapsedMs, landedAnyway}` — 8 s bounded, reads back what landed | 60 s |
| `sch.place_text` | connector | write | connector | `content`, `x`, `y`, `rotation`, `color`, `fontSize`, `pageUuid` | `{uuid, content, decorative: true}` — `sch_PrimitiveText`, **no connectivity** | 30 s |
| `sch.place_power` | connector | write | connector | `kind`, `net`, `x`, `y`, `rotation`, `mirror` | `{uuid}` | 60 s |
| `sch.place_netport` | connector | write | connector | `direction`, `net`, `x`, `y`, `rotation`, `mirror` | `{uuid}` | 60 s |
| `sch.delete_primitives` | connector | write | connector | `pageUuid`, `primitiveIds` | `{deleted, notFound, failed}` — per-id honest result; the id index covers component/wire/text/pin (attribute primitives cannot be addressed by id) | 60 s |
| `pcb.delete_primitives` | connector | write | connector | `pageUuid` (the PCB uuid), `primitiveIds` | `{deleted, notFound, failed}` — component/line/via/pad/pour, guarded against the focused PCB | 60 s |
| `sch.modify_primitive` | connector | write | connector | `pageUuid`, `primitiveId`, `x`/`y`/`rotation`/`mirror` (≥1) | `{before, after}` — pose only; a wire has no pose in the type package and is refused | 60 s |
| `pcb.modify_primitive` | connector | write | connector | `pageUuid`, `primitiveId`, `x`/`y`/`rotation` (≥1) | `{before, after}` — pose only, guarded against the focused PCB | 60 s |
| `sch.component_pins` | connector | read | `primitiveId` | `{primitiveId, returned, pins, note?, readErrors?}` — the placed component's pins **with geometry** (x/y/number/name/rotation/length) | 30 s |
| `lib.symbol.get` | connector | read | `uuid`, `libraryUuid` | `{uuid, libraryUuid, found, item, readErrors?}` — library symbol metadata; **no geometry** | 30 s |
| `lib.device.get` | connector | read | `uuid`, `libraryUuid` | `{uuid, libraryUuid, found, item, readErrors?}` — includes `association.symbol`/`.footprint` | 30 s |
| `lib.device.search` | connector | read | `keyword`, `limit` | `{keyword, returned, shown, items}` — each item carries `footprintName`/`footprintUuid`/`supplierId` | 30 s |
| `lib.footprint.get` | connector | read | `uuid`, `libraryUuid` | `{uuid, libraryUuid, found, name, item}` — footprint uuid → package name | 30 s |
| `sch.set_component_attribute` | connector | write | `primitiveId`, `attributes`, `key`, `value`, `pageUuid` | `{primitiveId, attributes, mergedKeys, applied, wrote, otherPropertyBefore, otherPropertyAfter, mismatched?, clobberedOtherKeys?}` — **one** `modify` per call, then a read-back; `applied` means the read-back matched | 30 s |
| `sch.doc.save` | connector | write | — | `{saved: true}` | 30 s |
| `doc.list` | connector | read | — | `{documents: [{uuid, name, type, active}], projects: [{projectUuid, name, focused, opened, schematics, pcbs, documents}], active, schematicPages, pcbs, count, notes?}` — every page and PCB in the focused project plus a multi-project view (012 §五: non-focused projects report `documents: "brief"`, no document tree — focus them to enumerate); `active` is **null** when no document is focused, including when the host answers with its placeholder uuid `"0"` — the raw reading is kept in `notes` | 30 s |
| `doc.focus` | connector | write | connector | `pageUuid` or `tabId` | `{activated, tabId, title, documentType}` — puts an already-open tab on top; refuses NOT_FOUND when nothing is open for that uuid | 30 s |
| `doc.delete_page` | connector | write | connector | `pageUuid` | `{deleted, pageUuid, name}` — removes a schematic page; NOT_FOUND for a uuid the project does not list | 30 s |
| `export.fab` | connector | read | connector | `pcbUuid`, `outDir`, `vendor`, `gerber`, `bom`, `bomTemplate`, `timeoutMs` | `{vendor, project, pcb, outDir, generatedAt, encoding: 'base64', files: [{role, name, mime, bytes, data}], manifest, failed, partial, note}` — Gerber + pick-and-place + BOM in one call with a manifest; preset `generic` (metric 4:5, drill table on, CSV P&P in mm, CSV BOM with every column — the 15 columns are sent as the two counting columns in `statistics` and the other 13 in `property`, disjoint lists whose union the host checks per column); a file the host refuses/empties/hangs on is reported per file in `failed`. `bom` is an override object limited to `filterOptions` — `[{property, includeValue}]` where a rule leaves a row **out** when the part matches `includeValue` (so the preset sends `'Add into BOM': 'no'`), and `null` means "send none, keep the host's own default rules". On disk the names are `fab_gerber.zip` / `fab_pick_and_place.csv` / `fab_bom.csv` | 240 s (`FAB_TIMEOUT`) |
| `lib.recommend` | connector | read | `query` \| `pageUuid`+`ref`, `topN`, `allLayers`, `timeoutMs`, `probes` | `{source, query, ref, component, target, layers: [{layer, api, called, args, hitCount, pagesFetched, reason?, error?}], returned, shown, candidates, 'stock/price', readOnly, placed}` — the ladder `searchByProperties({supplierId: <LCSC code>})` → `searchByProperties({value, footprintName})` → `search(keyword)`, 5 hits per page and 3 pages per rung; Basic parts first; **no stock/price**; never places. `timeoutMs` is the **per-page** deadline for one library search (default 20 s): a page that never settles is reported as that rung's `error` and the descent continues, instead of consuming the whole action. `probes` (≤10) replaces the ladder with raw `searchByProperties` calls: each entry `{properties, libraryUuid?, classification?, symbolType?, itemsOfPage?, page?}` is sent with **exactly** the arguments given (an argument the caller left out is not sent, so `arguments.length` is theirs) and reported as `{args, called, hitCount, pageSize, firstKeys, error?}`; the answer is then `{..., probes: […], probesOnly: true, layers: [], candidates: [], returned: 0, shown: 0}`. The `exact` rung's key is `supplierId` because that is the only properties key 3.2.186 indexes (§12) — `partNumber` / `partCode` are applied there and match nothing, so sending them would be a call that cannot return a hit | 90 s (`RECOMMEND_TIMEOUT`) |
| `review.mark` | connector | read | `pageUuid`, `marks` (`[{ref, ruleId, severity, text}]`), `clear`, `focus`, `color`, `zoom`, `markers` | `{mode: 'markers'\|'list', cleared, page: {components, designators, withoutPosition, active}, count, marked: [{position, marker, ref, designator, ruleId, severity, text, primitiveId, x, y}], unresolved: [{position, …, reason}], markers: {attempted, accepted, reason?}, focused?: {position, ref, zoomed, reason?}, readOnly, note, notes?}` — a review pass drawn on the focused schematic page: each finding's `ref` is resolved to its component's coordinates and marked with a rectangle. The marker API takes **shapes, not text**, so the rule id / severity / one-line summary come back in `marked` (`marked[k-1]` is marker k). `markers: false`, a missing `generateIndicatorMarkers` or a canvas that refuses it all degrade to `mode: 'list'` (the jump list, still carrying coordinates); a ref that is not on the page is reported per mark and the rest are still drawn; `focus: N` zooms to the Nth entry with `zoomToRegion`; `clear: true` removes the markers — it has **no page guard** (it clears whatever canvas is in front, which may belong to a different project; measured 2026-09-21), and with **no active document** it answers `cleared: true` with the note "no active canvas — nothing to remove" instead of reporting the host's refusal of a call that had nothing to act on | 30 s |
| `doc.open` | connector | read | `uuid` | `{uuid, tabId, opened, activated, document}` — switches the editor's active document, confirmed by asking the editor. On failure (`openDocument` answered no tab id) the error is a **diagnosis**, not a bare refusal (018 §B1): `CONNECTOR_ERROR` whose message names the focused project, the project the uuid belongs to (when a read can say so), whether the uuid is already open in a tab or listed among the open project's documents, and what to do (`switch the editor to project X first`, `use doc.focus`); `detail` carries the raw readings. A uuid no searchable project has says so, and says which projects could not be searched and why | 30 s |
| `pcb.doc.new` | connector | create | `boardName`, `confirm` | `{pcbUuid, focused}` — **gated**: without `confirm: true` the daemon answers `CONFIRMATION_REQUIRED` | 60 s |
| `doc.rename` | connector | write | `uuid`, `name`, `type` | `{uuid, name, type, renamed, confirmed, notes?}` — dispatches to the per-kind `modify*Name` call and verifies against the editor's listing | 30 s |

**`export.fab` does not write to `outDir`, by measurement rather than by choice.** The type package
declares `SYS_FileSystem.saveFile(fileData, fileName?)` — no destination argument; it goes through the
browser download / Electron save dialog, so it cannot honour a path. The action therefore returns the
three files as base64 (the same reliable path `export.render` uses) plus a `manifest{}`, and
`boardwise bridge export-fab --out DIR` is the caller that creates the directory and writes the four
files. `outDir` is still a required parameter: it is recorded in `manifest.json`, so a bundle on disk
says where it was meant to go. **Measured on 3.2.186 (2026-09-21)**: the Gerber export really is a zip
(16 entries, `testzip()` clean, magic sniffed rather than the extension trusted), all 15 BOM column
names come back verbatim in the header, and the **BOM's `filterOptions` are *exclusion* rules** — the
type package's `includeValue` is the value that leaves a row **out**, so its own example
(`'Add into BOM': 'yes'`) exports a header-only BOM for a 122-part board. The preset sends
`'Add into BOM': 'no'` (the host's own default rule) and the parts are there; the `bom` override exists
so this argument can be re-measured or replaced without a rebuild. The three names are not chosen the
same way either: gerber and P&P come back under the name they were handed, the BOM's is the host's own
`fileName + '.' + fileType` — which is why the preset carries the suffix for the first two and not for
the third.

**`review.mark` draws what the marker API can draw, and returns the rest.** The task asks for
marks carrying "rule id + severity + one sentence"; `generateIndicatorMarkers(markers, color,
lineWidth, zoom)` takes an array of *shapes* only — point, circle, line, arc, rectangle — and has
no place to put a string. So each mark becomes a rectangle around its component's coordinates and
the three text fields come back in `marked`, where `marked[k-1]` is marker `k` **in the order
drawn**. `boardwise review-mark` prints exactly that table, which is what makes the numbers on the
canvas mean something; per-severity colours are *not* implemented, because the colour belongs to
the call rather than to a marker, so they would cost one call per severity — a decision the oracle
has not made. Ref resolution reads the page through the same dump `sch.geometry` uses
(`getState_Designator` / `getState_X` / `getState_Y`), which keeps it one page read per pass
instead of one `locate` per ref. **The fallback is part of the contract, not an error path**: with
`markers: false`, with no `generateIndicatorMarkers` on the host, or with a canvas that answers
`false` (unsupported canvas / unknown tab), the response becomes `mode: 'list'` with the reason and
the coordinates — the jump list the task asks for. Structural things stay thrown: a `pageUuid` that
is not the focused page (`PAGE_MISMATCH`), a focused document that is not a schematic page, a page
whose components cannot be read at all, `focus` outside `marks`, and a `clear` on a host without
`removeIndicatorMarkers`. **`clear` deliberately has no page guard**: it removes the overlays on
whatever canvas is in front, which is what "clear the markers" means (measured 2026-09-21: it cleared a
canvas belonging to a project other than the one the caller had in mind). With **no** active document
the answer is `cleared: true` and the note "no active canvas — nothing to remove": the host answers
`false` for that call, but there was no canvas to act on, and calling it a refusal sends the caller
hunting an open document that does not exist. **The drawing path has run on a machine** — the host
accepts the rectangles (`accepted` 9/9 on the 毕设板 page) — while the *visibility* of the markers on
screen is only partly confirmed (one A/B sample showed box-shaped geometry, another showed none, with
the view moving under a human hand throughout); see `outputs/013_p2_findings.txt` §八.

**`ping` carries the daemon's own version.** `boardwise doctor` compares it with the version of the
install the CLI is running from, because "a daemon that is one checkout behind" is a failure mode
this project has already paid for twice: the action catalogue is a load-time constant, so a daemon
left running across a checkout answers every new action with `UNKNOWN_ACTION` while looking
perfectly healthy. The field is additive — a client that does not read it is unaffected — and a
daemon old enough not to send it is reported as *unknown* rather than silently equal (that is a
`FAIL` line in doctor, with "restart the daemon" as the fix).

**`lib.recommend`'s ref path is focus-guarded.** A designator is resolved in the *focused* page's
component list (`sch_PrimitiveComponent.getAll()`), and there is no cross-page lookup to use instead —
so a `pageUuid` that is not the focused page is refused with `PAGE_MISMATCH` rather than answered from
the wrong board. The rungs a hit made unnecessary are reported as `called: false` with the reason, so
"this rung found nothing" and "this rung never ran" never look alike. `searchByProperties` is
documented **ADD since EDA v4**: on a host without it the exact rung reports itself unavailable and
the keyword rung still answers — a degradation that is visible, not silent. Measured 2026-09-21 (013),
the declaration being *present* is not enough **by itself**, and it is also not the whole story: on
3.2.186 the method is callable and it **does** match — but only on the keys that host indexes, which
is why the exact rung sends `{supplierId}` rather than the declared `{partNumber, partCode}`. See
§12's row for the measured matrix.
To find out *why* on a live host without guessing, `probes` turns this action into a read-only
channel: the caller supplies up to ten raw argument lists, each goes to `searchByProperties` exactly
as written (an argument left out is not sent at all — the argument *count* is one of the things under
measurement), and the answer carries
`probes: [{args, called, hitCount, pageSize, firstKeys, error?}]` with `probesOnly: true`. Nothing
else changes: with no `probes`, the answer is the same answer it always was, field for field.

The 006 rows (everything from `sch.netlist` down) exist for the draw flow; their operator
documentation, machine-probe checklist and known host traps live in [`docs/draw.md`](draw.md).
Two of them carry measured warnings worth repeating here:

- **`sch.netlist` has no fallback inside the connector on purpose.** The deprecated
  `sch_Netlist.getNetlist()` has been measured *hanging* on EasyEDA 3.2.186, and a hung export
  would hold this action's slot until timeout. The export either answers or fails structured;
  the fallback to `sch.geometry` happens in the *draw flow*, where the timeout costs a report
  row instead of a wedged socket.
- **`export.render` is the acceptance image, `export.screenshot` is not.** The reference measured
  `getCurrentRenderedAreaImage` returning byte-identical images across different board states, and we
  reproduced that; the document render cannot come back as a cached frame. Since connector 0.4.2 the
  render runs through `sch_ManufactureData.getExportDocumentFile` (ported from the reference's
  `schematicExportImage`, live-verified on this host), so `format: png|svg|pdf` and
  `scope: page|selection|project` are all real — `scope: 'selection'` requires `ids` and drives
  `sch_SelectControl.doSelectPrimitives` first. **The `object` argument must be the literal strings
  `'Current Page' | 'Current Page Selected Items' | 'Project'`** — the values the type package declares
  make the host promise never settle (a stuck 1% toast), so the action races a 30 s deadline and its
  timeout error says to reload the document to clear the toast. A multi-page project may return a zip —
  the action says so (`format: 'zip'`) instead of handing the caller an archive named `.png`.
- **`sch.place_netlabel` is timeout-bounded and self-reporting** (006b): it races an 8 s deadline
  (`timeoutMs` overrides, clamped 200..30000 ms) and, on a miss, reads the attribute list back to
  report whether the label landed anyway — the reference lesson is that a timed-out write may have
  succeeded, and a blind retry stacks duplicates.
- **`sch.place_netlabel` is a known hang, and on 3.2.186 it cannot work at all** (measured
  2026-09-14): `createNetLabel` is documented *added in EDA v4*, so on the v3.2 line it never
  settles and nothing lands (`landedAnyway: false`). It stays for hosts that have v4. The 006b
  draw flow's `label` strategy is therefore dormant; the default `text` strategy names signal
  nets with `sch.place_text` (visible but decorative) and rails with `sch.place_power`;
  `sch.place_netport` remains only as the solver's last resort and is banned from the replay.
  Evidence: `tasks/006b-netlabel-finding.md`.
- **`sch.place_text` is the visible-name fallback, and it is decorative by construction.**
  `sch_PrimitiveText.create` draws a text primitive with no connectivity — the editor's netlister
  does not read it — so the action returns `decorative: true` and every report line that mentions
  it says so. The wire still carries the net (the `wire` strategy's mechanism), which the editor
  *does* honour; the text exists so a human can read the name.
- **`sch.place_component` can time out and still land** (measured 2026-09-14): the first library
  resolution on this host can exceed 30 s, after which the component *is* on the page. The action
  therefore races a deadline and then **reads the page back** (`componentsNear`, ±30 units) to
  report `landedAnyway` / `landedCount` / `near`, and its error text says "do NOT retry" when
  something landed. A blind retry is how the probe page got stacked resistors. The daemon's own
  deadline for this action is 60 s — deliberately longer, so the connector's readback answer
  arrives instead of the daemon's timeout.
- **`sys.probe` exists because a declared method and a live method are different things.**
  `sch_ManufactureData.getPngFile` is marked *added in v3.2.183*, the host reports 3.2.186, and
  the method answers `NOT_IMPLEMENTED` anyway. A `typeof` check can only say "one method is
  missing"; the probe enumerates the namespace's real members — walking from the object **itself**
  up the prototype chain (a class instance keeps its members on the prototype, `Object.keys`
  returns `[]`; a plain-object namespace keeps them as own properties, so starting at
  `getPrototypeOf` loses them). Each level is guarded on its own, because the host hands out
  exotic objects whose `getPrototypeOf` throws; those failures are reported in `errors` rather
  than swallowed.
- **`sys.probe` has two modes because enumeration is a measurement that can fail on the object it
  measures** (2026-09-14, on-machine). The first probe run died on *every* namespace with
  `Cannot read properties of undefined (reading 'prototype')` — the host's exotic objects throw
  from `getPrototypeOf`/`getOwnPropertyNames`, and `constructor` is unreachable. So the *stable*
  mode is `checks`: `{"checks": {"<ns>": ["methodA", …]}}` reads each name with a plain
  `typeof ns[name]`, and property access walks the prototype chain **as part of the language** —
  no enumeration call exists to throw. The candidate names come from the offline type package via
  `tools/api_names.py` (generated into `connector/src/api-names.ts`), which makes the check
  *complete* for the declared surface, not a sample. `checks: true` uses that generated table.
  The status vocabulary is deliberately the language's own — `function` / `object` / `undefined`
  — plus `threw: …` and `namespace-absent`, so "undeclared" and "the read itself failed" never
  collapse. Every member that reads back as a function also carries its **declared arity**
  (`fn.length`), which is how a "present, callable, matches nothing" method gets a shape to test
  (`lib_Device.searchByProperties` on 3.2.186 is the case that asked for it): a hint, not a
  verdict — a proxy or wrapper loses the real arity, so it is measured never judged on.
  A method the package marks `ADD since EDA v…` that reads back `undefined` gets a
  `notes` entry carrying the contradiction. Enumeration survives as the *predictive* mode: it can
  find a name nobody thought to check, which the type package cannot do.

Notes that matter operationally:

- **`hello`'s 30 s is the client's wait for an *answer*.** The daemon's wait for the *first
  inbound frame* is a different number — `HELLO_TIMEOUT`, 5 s (§3.3). They are unrelated, and
  confusing them makes the handshake look far more forgiving than it is.
- **`ping` never reaches the editor.** It is answered by the daemon and reports whether a
  connector is attached. This is what `boardwise bridge status` calls.
- **Only `role: "cli"` may originate editor actions.** A connector asking for `pcb.readback`
  gets `BAD_REQUEST` — the connector is the hands, not a caller, and this catches an accidental
  loop where the extension ends up talking to itself.
- **No connector attached** → `NO_CONNECTOR`, with a message naming the likely cause.
- **`export.screenshot` gets double the timeout** of everything else: the editor renders the
  canvas before replying, and a full-board render on a large design is slow. `fit: true` runs
  `zoomToAllPrimitives` first, which changes what the user sees — so it is opt-in
  (`--fit` on the CLI), never the default.
- **`canvas.highlight` resolves uuids to coordinates, then draws.** The official marker API
  (`dmt_EditorControl.generateIndicatorMarkers`) takes *shapes*, not ids, so each uuid is looked
  up through the primitive namespaces first. Uuids that cannot be resolved are reported in
  `unresolved` rather than silently skipped. Marker units are canvas units: mil on PCB, 0.01 inch
  on schematic — a marker drawn on the wrong document is a plausible failure, so `unresolved`
  being non-empty is the signal to check which tab is focused.
- **`clear: true` removes markers and ignores `uuids`.** It exists so a review pass can be
  reset without restarting the editor.

## 5. Error codes

| code | Meaning | Usually means |
|---|---|---|
| `UNAUTHENTICATED` | No `hello` in time, or the token is empty/wrong | A connector that is not the paired one — `boardwise bridge revoke` to forget the pairing (§3.4) |
| `PROTOCOL_VIOLATION` | `hello` not first, or `hello` sent twice | A hand-rolled client — or an extension bundle that reconnects without reloading the page |
| `VERSION_MISMATCH` | Protocol major differs | Daemon and connector from different checkouts |
| `BAD_REQUEST` | Malformed JSON, missing/invalid field, or wrong role for the action | A client bug — including a `targetProject` / `targetInstance` that is not a string (§3.5) |
| `UNKNOWN_ACTION` | Not in the catalogue | Typo, or an action that does not exist yet |
| `NOT_IMPLEMENTED` | Known to the connector, but this editor version lacks the API | Editor older than the connector expects |
| `NO_CONNECTOR` | The action needs the editor and none is attached | EasyEDA not running, extension disabled, or external interaction not granted |
| `CONNECTOR_ALREADY_ACTIVE` | **Retired (018 §A, removed by 023).** A second editor instance used to be refused while the first one's socket held the bridge | Nothing, today: the daemon sends this to nobody, because every authenticated window is registered (§3.5). It stays in the vocabulary because connector builds in the field read the code; the audit record `connector_rejected` is retired with it |
| `PROJECT_NOT_CONNECTED` | A `targetProject` hint that no connected window has open (023) | The project is not open, or its window has not announced it yet — a window that cannot read its project at all is listed as `(no project)` and reachable only by `--instance`. The message lists every online window as `projectName (instanceId)`: name one of them, or read it off `bridge status` |
| `PROJECT_AMBIGUOUS` | A `targetProject` hint that **more than one** connected window matches (023) | The same project open twice, or two sockets claiming one instance id (double activation). Nothing was forwarded; close the duplicate window or split the hint. Picking a window here is exactly the wrong-window write 018 measured |
| `WINDOW_UNSPECIFIED` | Several windows are connected and the request named none (023) | Add `--project NAME_OR_UUID` or `--instance INSTANCE_ID` (`bridge call …`). Not an error in the "broken" sense — it is the daemon refusing to guess which window was meant, and the message lists the candidates |
| `WINDOW_NOT_CONNECTED` | A `targetInstance` hint that no connected window answers to (023 follow-up) | The window is closed, or the id is from an earlier session (a reload gives the connector a new one). The message lists every online window as `projectName (instanceId)`; copy one out of it or out of `bridge status` |
| `CONFIRMATION_REQUIRED` | A `create` action (one that produces a new document) arrived without `confirm: true` | Expected on the first call — re-send with `confirm: true`, or let the CLI ask (§4, 006c). Nothing was forwarded, so nothing was created |
| `CONNECTOR_ERROR` | The connector raised, or refused (e.g. no image, canvas refused markers) | A document is not open/focused |
| `PAGE_MISMATCH` | The page (or PCB/board) the action was given is not the one the editor has focused | A call aimed at a tab that is not in front — the guard exists so a write cannot land on the wrong page. Focus it first (`doc.focus`, or `doc.open` if it is not open) and re-check with `doc.list` |
| `NOT_FOUND` | The uuid / primitive id / designator the action named does not exist: not in the project, not on the page, or with no open tab | A stale reference — the document was renamed or deleted, the primitive is gone, or the tab is closed. Re-read `doc.list` / `sch.geometry` and address what the editor actually reports |
| `TIMEOUT` | The connector did not answer within the action's timeout | Editor busy, modal dialog open, or a half-dead socket (§10) |
| `DISCONNECTED` | The socket died before an answer arrived — raised by the **client**, never by the daemon (once the socket is gone nobody is left to answer) | Daemon stopped or the editor closed mid-call. A write whose answer never came **may still have landed**: read the document back before retrying |
| `INTERNAL` | Anything else; `message` carries the text | A bug — read the audit log |

Codes are stable identifiers, not English prose: clients branch on `code`, humans read `message`.

## 6. Connector-side states

The transport reports six states. The split between `connecting` and `handshaking` is
intentional — it separates the two failure families:

| state | meaning | if it stays here |
|---|---|---|
| `idle` | not started, or auto-connect is off | — |
| `connecting` | opening the socket | the daemon is not running / wrong port |
| `handshaking` | socket open, waiting for `hello` to be accepted | **pairing problem** — the daemon is holding a different pairing (§3.4) |
| `connected` | accepted; serving requests | — |
| `reconnecting` | closed, waiting for the backoff timer | daemon went away |
| `stopped` | stopped from the menu | — |

The extension's **About…** menu item prints the state, the URL, where the token came from, the
pairing fingerprint the daemon reported, whether the background watchdog is running, and the last
error. It is the fastest way to see *why* nothing connects. The token's *value* is never shown —
not in About, not in the log panel, not on the daemon console, not in the audit log. Only its 8-hex
fingerprint ever leaves the daemon, which is why the fingerprint is the one thing the two sides can
compare.

The `watchdog:` line is one of four readings, and it is a fact about this editor rather than a
promise about behaviour (§7): `running (checks every 15000 ms, wakes after 30000 ms of page silence,
wakes so far: N)`, `unavailable(<the host's own refusal>)`, `not started (auto-connect is off)` or
`not started (no connection attempt yet)`. `unavailable` is the one to act on: that window will not
notice a dead socket while it is in the background, and only bringing it to the front recovers it.

## 7. Liveness and reconnect

`eda.sys_WebSocket.register(id, uri, onMessage, onConnected)` returns `void` and provides **no**
`onClose` or `onError` callback. Death cannot be observed, only *inferred* — and the one callback
it does offer fires **unreliably** (§3.2), so liveness is judged from traffic, never from it. Two
consequences:

1. **Heartbeat.** After a successful handshake the connector sends a `ping` request every 5 s
   (application level; the daemon does not do WebSocket-level pings). Three consecutive misses
   without an answer means the socket is dead, and a reconnect is scheduled. Because `ping` is
   answered by the daemon, an answer proves the whole path — socket, daemon, routing — is alive.
   Any incoming frame also clears the miss counter.
2. **A fresh id per attempt.** The API ignores parameter changes for an id that is still live, so
   each attempt registers a *new* id (`boardwise-1`, `boardwise-2`, …). Reusing one id would make
   the second attempt silently do nothing.

Backoff doubles from 1 s to a 30 s ceiling and resets on a successful connect. `stop()` clears
every timer and closes the socket and the watchdog Worker; a stopped transport sends nothing, ever
(asserted in the suite, with a wait long enough to be meaningful — and since 026b with the Worker's
own message count asserted alongside).

### 7.1 The background watchdog (026b)

Both of the mechanisms above are **page timers**, and a background editor window's page timers are
the problem. Measured on 3.2.186 (026 probe batch, `outputs/026_probe.md`): with the window pushed
out of the foreground, a 1 s page clock ticked **10 times in 242 s** (Chromium's intensive
throttling, ~1 tick a minute); the worst recorded case is the 7-hour incident (batch 2 of 025), where
a window in the frozen state never reconnected at all until the user brought it to the front. The
same probe batch measured the other half, and it is the premise of the fix: **a `blob:` Worker's own
timers are not throttled with the page** — in the same 153 s in which the page managed 20 ticks, the
Worker produced 153, maximum gap 1015 ms. A host-level timer (`eda.sys_Timer`) was measured too, and
is **not** an alternative: its callbacks are throttled exactly like the page's (P5).

So the connector ships one alarm in a Worker, and the page keeps it informed:

- the transport reports **activity** on every sign of life — heartbeat sent, any inbound frame, a
  connect attempt, a successful handshake;
- the Worker checks every **15 s**, and once the page has been silent for longer than **30 s** it
  posts `{type:'wake'}` — **one per check**, not one per silence, because a frozen page swallows
  messages and must find one waiting the moment it runs again;
- the page's reaction is `Transport.wake()`: `connected` with **nothing** outstanding → **probe the
  socket with a ping** (since 0.4.19 — the daemon's answer is the liveness evidence, and it arrives
  as an inbound frame, so nothing here waits for a page timer); `connected` with **any** unanswered
  heartbeat → the socket is judged dead and rebuilt now (since 0.4.18); `connecting`/`handshaking` →
  replace the attempt now; `idle`/`reconnecting` → connect now with the backoff ladder reset,
  because the silence was the page's and says nothing about the daemon.

| window state | page timers | without the watchdog | with the watchdog |
|---|---|---|---|
| foreground | normal | normal | unchanged (the alarm only ever adds a Worker) |
| background (throttled) | ~1 tick a minute | heartbeat drops to the same rate; a reconnect after a daemon restart waits for a throttled timer | the alarm probes the socket every 30–45 s and rebuilds it on the first unanswered answer: measured kill→hello **27–46 s** (§7.1's table) |
| frozen (the 7-hour state) | stop entirely | **never reconnects** until the window is brought to the front | the wake is already queued when the page unfreezes, and the reconnect happens then, without the backoff |
| page discarded | dead | nothing recovers | nothing recovers — the Worker's thread goes with the page |

**Honest boundary.** The throttled row is measured on the machine. The frozen row rests on the same
Worker-timer measurement plus the queued-message property, and **no controlled reproduction of the
frozen state exists** (the probe batch's item #2: the minimize APIs do not take effect on 3.2.186) —
so this table claims "the wake is waiting when the page runs again", not "a Worker survives a frozen
page". This document must never say the watchdog makes a window immune: it bounds the damage the
page's own throttling can do.

**The machine measurements, against the target (026b batch 2b and 026c, 3.2.186, 2026-09-23).** With
the window out of the foreground and its page ticking at ~1/minute (read off the daemon's audit as a
60 s `ping` spacing), killing and restarting the daemon brought the connector back **151 s** and
**135 s** on the first two runs — the brief was ≤90 s. The watchdog was running
(`sys.connector_status` → `state: running, wakes: 6, activityPosts: 186`) and it is what performed
those reconnections: the transport's own record is `watchdog wake (worker alarm after
59207 ms of page silence): 3 heartbeats unanswered`, the alarm's reconnect branch, not the heartbeat
timer's. What gated it was the miss limit in front of it: a half-open socket was only *declared* dead
after three unanswered heartbeats, and three throttled ticks are three minutes of silence — the
alarm's earlier wakes took the "…unanswered heartbeat(s) — pinging now" branch, and a ping into a
dead socket cannot prove anything.

**Both of those were fixed in 0.4.18 (026c), and this is what changed and what it bought.** One
unanswered heartbeat plus a wake now means dead (§10.22), and the wake's reconnect no longer goes
through `setTimeout(…, 0)` — a throttled page defers zero-delay timers along with everything else,
so "immediate" had a timer in it that could cost a whole tick. Five more machine runs (same method)
after those changes:

| run | connector | daemon took to listen | kill → hello | listening → hello | what the wake reported |
|---|---|---|---|---|---|
| A | 0.4.18, before the timer fix | 4.9 s | **62.8 s** | **57.9 s** | 51 104 ms of silence, 1 unanswered heartbeat |
| B | same | 54.3 s (slow start, unrelated) | 114.9 s | **60.6 s** | 51 103 ms, 1 unanswered heartbeat |
| C | same | 4.7 s | 101.3 s | 96.7 s | 51 108 ms, 1 unanswered heartbeat |
| D | 0.4.18, timer fixed | 4.6 s | 93.4 s | **88.8 s** | 48 488 ms, 1 unanswered heartbeat |
| E | same | 4.6 s | **74.6 s** | **70.0 s** | 48 476 ms, 1 unanswered heartbeat |

Read it in two parts, because one number would be a lie. **The connector's own share is the wake's
silence plus about a second — 48.5–51.1 s measured, against the 45–60 s the design predicts** — and
that is what the fix bought: the same measurement was 135–152 s before. The *total* from the kill
additionally contains the page's own throttled tick: a backgrounded page runs its timers about once
a minute, so where in that cycle the daemon died decides how long the page has left to notice, and
the total therefore lands anywhere in [connector's share, ~one tick + connector's share]. Five runs
spread exactly there (62.8 s … 114.9 s), which is why this section claims a *share*, not a total. Two
same-instant controls say the same thing: in run D the user's own window (never backgrounded by the
test, and not throttled) came back in **24 s**, while the throttled test window took 93 s.

**0.4.19 (026d) removed that residual term, and the same experiment now has no spread to explain
away.** The wake stopped being a page word for the page's own liveness and became a probe — and the
silence threshold went from 45 s to 30 s so the probe runs every 30–45 s in the steady state instead
of every 45–60 s. Where the old design waited for the page's throttled heartbeat timer to send the
ping that would discover the dead socket, this one never waits for a timer at all. Three runs, same
method, immediately after:

| run | connector | daemon took to listen | **kill → hello** | listening → hello | what the wake reported |
|---|---|---|---|---|---|
| F | 0.4.19 | 4.7 s | **39.6 s** | 34.9 s | 34 788 ms of silence, 1 unanswered heartbeat |
| G | 0.4.19 | 4.6 s | **27.1 s** | 22.5 s | 49 788 ms, 1 unanswered heartbeat |
| H | 0.4.19 | 4.7 s | **45.8 s** | 41.1 s | 34 773 ms, 1 unanswered heartbeat |

**3/3 under the 90 s brief, and the worst sample is roughly half of it** — where the same three-run
budget under 0.4.18 produced 93.4 s, 27.1 s and 45.8 s-shaped evidence only after the phase happened
to fall favourably. What remains is the design's own floor, not a scheduling accident: at worst the
page's last sign of life is 30–45 s before the first wake (the Worker compares strictly on a 15 s
grid), the probe's ping is unanswered, and the *next* check judges the socket dead — so the total is
bounded by that threshold plus one check, and the daemon's own startup. The two constants are now
the 15 s check and the 30 s silence threshold.

**One alarm per editor runtime.** The editor re-evaluates the bundle on every menu click, so the
Worker is owned by the shared runtime the transport already lives in (024): a later evaluation
adopts the published controller and never builds a second Worker, `stop()` terminates it with the
socket, and the singleton is asserted in `connector/tests/watchdog.test.mjs`. If the host refuses a
Worker (a CSP that blocks `blob:`, no constructor at all) the connector runs exactly as before —
with no alarm — and says so in the log panel and in `About…`; the failure is never silent.

The daemon is the passive side: it does not track per-connector liveness, and removing a window from
the hub depends on the handler loop exiting. So a *half-open* socket can leave `status` reporting
`connector: connected` while real actions time out — see §10.

## 8. Configuration reference

| What | Where | Default |
|---|---|---|
| Daemon host | `DEFAULT_HOST` | `127.0.0.1` (no public-interface code path exists) |
| Daemon port | `BOARDWISE_PORT`, `--port` | `61190` |
| Daemon state dir | `BOARDWISE_HOME` | `~/.boardwise` |
| CLI token file | `token_path()` | `~/.boardwise/token` |
| Paired connector token | `connector_token_path()` | `~/.boardwise/connector-token` (created on first pairing) |
| Audit log | `audit_dir()` | `~/.boardwise/audit/YYYY-MM-DD.jsonl` |
| Connector URL | extension user config `url` | `ws://127.0.0.1:61190/eda` |
| Connector token | extension user config `token` | **generated** on first activation; nothing to type |
| Connector auto-connect | extension user config `autoConnect` | on |

### The `bridge` subcommands

| Command | Exit | What it does |
|---|---|---|
| `bridge start` | 0 | Run the daemon. Prints the token path, the audit dir, the pairing path, and one loud line per first-time pairing. |
| `bridge status` | 0 / 1 / 2 | Daemon up + connector attached / daemon up, no connector / daemon unreachable. Prints the paired connector's fingerprint and — since 023 — **one block per online editor window**: its `windowKey`, connector build, project, page, peer, arrival, last-heard-from and how many calls it has answered, plus a `projects seen:` line naming every project with the key that reaches it (§3.5). That list is what a caller reads before `bridge call --project …`. Several windows connected is the normal case, not a warning |
| `bridge revoke` | 0 | Delete the pairing record and audit `revoke`. Needs no daemon: it is a local file operation, because the moment you want to withdraw trust is the moment you are least sure what is running. |
| `bridge screenshot <out>` | 0 / 1 / 2 | Native canvas capture; `--fit` zooms to the board first. |
| `bridge export-fab --out DIR` | 0 / 1 / 2 | The fab bundle: calls `export.fab` and writes Gerber + pick-and-place + BOM + `manifest.json` into DIR (created if missing). `--pcb`, `--vendor`, `--gerber` (JSON overrides), `--bom-template`, `--timeout-ms`. Exit 1 also for a **partial** bundle — the files that did arrive stay on disk, and the missing one is named on stderr. |
| `bridge highlight <uuid…>` | 0 / 1 / 2 | Draw markers; `--color`, `--zoom`, `--clear`. |
| `bridge call --action NAME [--params JSON] [--project NAME_OR_UUID] [--instance INSTANCE_ID] [--yes]` | 0 / 1 / 2 | Call one action and print its `data` as JSON. `--project` (023) routes the call to the editor window that has that project open, `--instance` (023 follow-up) to the window with that instance id (§3.5) — the latter is the only one that works while no window can read a project at all. Either is required as soon as more than one window is connected; without one a multi-window daemon answers `WINDOW_UNSPECIFIED` rather than guessing, and given both the instance decides. `--yes` pre-confirms a `create` action (006c); without it the daemon answers `CONFIRMATION_REQUIRED` and this command asks interactively. Exit 1 is a refused or failed action — the code and message are on stderr |
| `bridge update-connector [--instance INSTANCE_ID \| --all]` | 0 / 1 / 2 / 3 | Hot-update the running connector from `connector/dist/index.js` (§8); asks first, `--yes` skips. **Exit 0 only after the window that the write went to has reloaded and a connection that was not online before announces the stored version** (020 §WI-2, sharpened by 025 and again by 030 §二.2): 1 = a connection that came back *after* the write announces a different build (the reload landed on the wrong build), or a window's write was refused; 3 = nothing conclusive inside the 30 s budget (state unknown, not failed — the old socket lingering is "not yet", not a failure); 2 = bad input, no daemon, or an unaddressed call with several windows online. `--no-verify` skips the read-back and returns as soon as the daemon accepted the write. **Three modes** (030 §二.1): no addressing with one window online updates it, as before; no addressing with several windows online is **refused before anything is written**, with the window table and the two ways to name a window; `--instance` aims at one named window; `--all` updates every online window, writing per storage record and verifying each window on its own line (exit 0 only when all verified). The verification is per *window* because the reloaded window reconnects under a new instance id and cannot be probed by the old name — and because two windows of one editor **share** the IndexedDB record, so another window's answer is not evidence about this one (§10.27) |

Connector token resolution order: `globalThis.BOARDWISE_TOKEN` (injection for tests) →
extension user config → `?token=` on the configured URL → **generate one**. The last step is
what makes the flow zero-configuration: the concrete path is `ensureConnectorToken()`, which
writes the new token to extension storage before returning, so a reload reuses it instead of
re-pairing the daemon. A token passed in the URL is read and then **stripped** from the socket
URL, so it is not re-sent on every reconnect.

### The commands that are not `bridge` subcommands

`boardwise doctor`, `boardwise review-mark`, `boardwise checkup` and `boardwise arch` are
top-level because none of them is a *bridge* operation: doctor asks seven questions about the whole
installation, review-mark turns an offline report into canvas markers, checkup is the one-command
review that consumes the bridge end to end, and `arch` (044 M1) is the offline architecture-skeleton
generator (`boardwise arch <file> [--out PATH] [--library PATH]` — the same offline loader checkup's
`--file` uses, deterministic markdown, no bridge).

| Command | Exit | What it does |
|---|---|---|
| `boardwise doctor [--json PATH] [--port N]` | 0 / 1 | Seven checks in one run: the daemon answers `ping` (the daemon has **no HTTP surface at all** — no `/health`, it is a WebSocket server and `ping` is its health answer); the extension's socket is registered; five methods the harness depends on answer `typeof === function` (`sys.probe`); the running daemon's version matches this install; the connector build in the editor matches `connector/extension.json`; the editor is ≥ 3.2.149; the focused project is readable. Every line carries its own fix, and a check that *could not be made* says so instead of pretending. Exit 1 for anything not green — deliberately not 2, which `bridge status` uses for "daemon unreachable": to a colleague following `docs/getting-started.md`, "not ready yet" is one state with one next step |
| `boardwise review-mark <findings> [--page UUID] [--focus N] [--color C] [--zoom] [--no-markers] [--json PATH]` | 0 / 1 / 2 | Draw a `boardwise review --json` pass on the focused schematic page. `<findings>` is a path, `-` (stdin) or the JSON itself; the literal `clear` removes the markers instead. Prints the finding ↔ marker table (position *k* is `marker#k` on the canvas), the unresolved refs and any degradation to the jump list. Exit 1 is **partial**: a ref not on the page, a finding with no ref, or a host that could not draw |
| `boardwise checkup [--project NAME_OR_UUID] [--out DIR] [--file PATH] [--library PATH] [--aesthetics|--no-aesthetics]` | 0 / 1 / 2 / 3 | The whole review in one command (025): pulls the focused project down the three-tier ladder (`project-file` → `per-page` → `netlist`; `--file` is the offline fallback), runs the host's own checks (`sch.drc_check` + `pcb.drc_check`, `userInterface:false`, focus restored afterwards), runs the offline rule engine, groups components into modules (**warning-bearing modules first**, `source.modulesOrderedBy`), renders one `canvas-<page>.png` per schematic page (PCB pages are not rendered yet), and writes `report.json` (`schema: boardwise.checkup/4`) + `report.md` + `architecture.md` (the 044 M1 architecture skeleton: power tree / analog chains / control chains / buses / design-intent slots, every judgement a tool cannot make left as a `TODO`) into `--out`. Exit 1 means an ERROR was **found** (an ERC error/fatalError count, a PCB DRC leaf, or a rule's ERROR finding); exit 3 means the online state cannot be stated — never "the board is clean". A check that did not run is `{checked:false, reason}`, not zero counts. `/3` (039 批②) added three sections: `unreviewed_parts` (the datasheet gate — parts no rule can judge yet, with the three acquisition channels; `summary.mayClaimPassed` is false while it is non-empty and `summary.conclusion` says "DRC/连接性已审，N 颗器件缺手册未审"), `warning_triage` (one slot per warning the report knows about, `verdict`/`reason` left for the model), and `layout_review` (**absent** unless the aesthetics switch is on). `/4` (044 M1) added `architecture`: the count summary of `architecture.md` (per-board rails/chains/buses, the fixed slot vocabulary, `totals.todoSlots`) — **absent**, not empty, when the skeleton could not be generated. `ai_slots` still lists what is left for a model: `unknown_parts` (an alias of `unreviewed_parts`), `canvas_images`, `summary_template` |

### Self-updating the connector (`sys.self_update`, 0.4.3)

Swapping connector versions used to mean uninstall → import → restart the editor: the editor
evaluates an extension bundle exactly once at load, and dedups installs by uuid, so a version
bump alone silently fails the import. `boardwise bridge update-connector` skips all three. It
base64s the freshly built `connector/dist/index.js`, sends it as `sys.self_update`, and the
running connector — which executes inside the editor page and therefore shares its storage —
rewrites its own installation and reloads the page. The editor re-reads extensions from
IndexedDB on load, so the new code runs. The mechanism is ported from the reference
implementation's hot-reload script (live-verified there), minus its separate WS server and
console injection: the existing daemon channel carries the bundle.

The write targets two records (EasyEDA-internal layout):

- `extensionsObjectStorage`, key `<uuid>|dist/index.js` — `source` is replaced with a
  `File` built from the new bytes;
- `extensionsIndex`, key `<uuid>` — **only** `config.version` and `fileSize` are bumped.
  `isAllowExternalInteractions` (the permission grant) and `isEnable` are never touched:
  an update that reset the grant would wake up unable to call any `eda.*` API.

The response frame is sent **before** the reload is scheduled (a 500 ms timer), so the CLI
always learns the outcome before the page and socket go away. The connector knows its own
uuid because `build.mjs` bakes it in (`__BOARDWISE_UUID__`, same mechanism as the version).

**"The daemon accepted the write" is not "the new build is running" — so the CLI reads the
version back (020 §WI-2, sharpened in 025 batch 2's follow-up).** `newVersion` in the reply is an
*echo of the CLI's own input*; the old build goes on answering every action perfectly, which made a
failed update indistinguishable from a successful one. `boardwise bridge update-connector`
therefore waits out the reply's own `reloadInMs` (until that timer fires the old socket is still
in the daemon's table), then reads the daemon's **window table** — one read a second for at most
30 s — and decides on it *per window*:

- a window announcing the stored version → `verified: running connector is now X.Y.Z`, exit 0;
- a connection that was **not online before the write** announcing a *different* build → exit 1
  naming both: the page reloaded, and it came back on something other than what was just stored;
- nothing conclusive inside the budget → exit 3, because "unknown" is not "failed".

That middle rule is the one to remember, and it exists because of a measured false alarm: a reload
**replaces** the connection (the connector mints a new instance id per page load) while the old
socket lingers until the editor tears the page down — **five seconds**, measured on 2026-09-23.
Reading that lingering socket as "the write did not take effect" reported a successful update as
FAILED, which is precisely the "not back yet ≠ failed" distinction 020 set out to keep; the
"already here" snapshot is what makes the difference decidable. The comparison is against the
version the CLI just stored, i.e. the same `connector/extension.json` value `boardwise doctor`
compares against — a version-string drift between `extension.json` and `package.json` (the two
files the build reads) would surface here exactly as it does in doctor. `--no-verify` restores the old
"print ok and return 0" behaviour for callers that would rather poll themselves. `--instance INST`
aims the write at one named window; the read-back is the same either way, since the updated window
can no longer be addressed by its old name and a routed probe in a multi-window session could be
answered by any window.

**Warning: the IndexedDB database/store names are EasyEDA-internal structure (`User_<teamUuid>_v6`
today), not an official API — an editor upgrade may change them.** The action therefore
validates at runtime instead of assuming: it enumerates `indexedDB.databases()` and refuses
zero *or several* matches, checks both object stores exist, and checks both records exist
before writing anything. Every failure is an explicit error naming what was found — the
fallback is a manual uninstall + import of the `.eext`, and no failure path silently degrades.

The bundle travels as one WebSocket frame: the daemon's inbound cap is `MAX_FRAME_BYTES`
(32 MiB), and the ~164 kB bundle (0.4.6) is ~218 kB as base64, so it fits with two orders of
magnitude to spare; the CLI refuses early with a "raise the limit" message if that ever stops
being true.

**The reload takes the editor's focus with it, and the connector deliberately does not try to put
it back (decided 2026-09-21).** A reload is a page reload: the connector is re-evaluated from
scratch and the editor restores its own windows, so the focused project after the reload is not
necessarily the one that was focused before. Measured that day on a two-window editor (connector
0.4.5): the focus had moved from `/test` to `/test2` with nobody touching the editor. Restoring
the pre-reload document was considered and **not** implemented:

- `activateDocument` — the only "put this document in front" API — takes a **tab id** and switches
  the *tab layer only*; the schematic context does not follow it across projects (measured on this
  host). A restore would therefore be a half-truth: `doc.list`'s `active` could name the original
  page while the focused *project* — the thing every write action actually addresses — stayed
  wherever the reload left it. A drift the caller can see beats a restore that only looks complete.
- It would have to run *after* the editor has finished restoring its tabs, and there is no "editor
  ready" signal: the register callback does not fire reliably (§3.2 b), and the one context
  measured to survive a load is the module's own synchronous evaluation (§10 item 22). A restore
  would be a timed guess at boot — the shape of silent failure this document keeps recording.
- Tab ids are re-derived per load (`"<docUuid>@<hash>"`), and the document that was in front need
  not be open in the restored session at all, so the intent would have to be persisted across the
  reload and re-resolved against a tree that does not exist yet.

What an operator should do instead, after `boardwise bridge update-connector`: the command itself
now waits for the socket to come back and verifies the running version (020 §WI-2, exit 0 means
`verified: running connector is now X.Y.Z` — before that, this step was the manual `boardwise
bridge status` / `boardwise doctor` green the reader had to remember). What it does **not** do is
restore the focus, so the remaining manual step is to read
`boardwise bridge call --action doc.list` — it names the focused project and the active document —
and put the intended document back in front yourself: `doc.focus` for a tab that is already open,
`doc.open` for one that is not. Re-read `doc.list` before any write; skipping that check means
acting on a pre-reload reading in a changed editor.

**More than one editor window means more than one connector — and since 023 the daemon holds all of
them.** Measured 2026-09-21 (013 batch②, connector 0.4.9/0.4.10): the audit log recorded `hello`
frames reporting `0.4.9` and `0.4.10` on **different sockets inside the same minute**, while
`doc.list`'s focused project changed with the socket (`test` → `test2` → `毕设FOC驱动板`) and
nothing was done to the editor between reads. Each window keeps its own extension store (hence its
own build version) and its own focused project, and back then every window that (re)connected
replaced the daemon's connector connection — so *both* "which build answers" and "which project is
in front" belonged to whichever window registered last, and they flipped on the windows' own
schedule. Two consequences stand, and both are now answerable rather than mysterious:

**Both fixes in sequence.** 2026-09-22 (018 §A) stopped the flipping by refusing a second *live*
connector — whichever window arrived first and stayed connected answered, and `bridge status` named
it. 2026-09-23 (023 §3.5) replaced that with the hub: every window is registered and the caller says
which one it means (`--project`), so "which window is it this time?" is a parameter rather than a
property of connection order.

- **An R1-clean reading does not prove the build under test answered.** A window left on an older
  bundle answers `doc.list` perfectly. Check the *behaviour* you changed, not only the project name:
  in this batch an R1-clean `export-fab` came back with the **old** 17-column BOM from a window that
  still ran the previous 0.4.10, and the 15-column header is what identified the new one. Since 023
  each window's build is in `bridge status`, and every response frame's `context` names the window
  that answered — read it instead of inferring from the focused project.
- **`sys.self_update` (and `bridge update-connector`) updates whichever window the daemon routes to**
  — with several windows open, the one you name (`--project` by project, `--instance` by instance id),
  or the only one if there is just one. Hot updating one window and testing another is the way to get
  a clean answer; `sys.probe`'s `connector` version read in the same breath as the action says which
  build answered, and when two builds share a version string only a bump can tell them apart. Before
  023 the update landed on whichever window owned the socket, which is the same hazard with the window
  chosen for you. Since 030 the command will not even guess: with several windows online and no
  `--instance`/`--all` it refuses before writing (`--all` updates every window, each verified on its
  own line). Note what the read-back can and cannot say: the updated window reconnects under a **new**
  instance id, so the verification is "the window the write went to is gone from the table and a
  connection that was not online before announces the stored version" (exit 0), "a connection that
  came back announces another build" (exit 1), or neither inside the budget (exit 3) — never a claim
  about which connection is which, and never another window's answer standing in for this one's
  (§10.27).

### Audit log

One JSON object per line, best-effort (a logging failure never breaks a call):

```json
{"ts": 1789000000.1, "action": "pcb.readback", "role": "cli", "ok": true, "ms": 41.2, "windowKey": "inst-…", "projectName": "test2"}
{"ts": 1789000000.5, "action": "connect", "role": "-", "ok": true, "peer": "127.0.0.1:54048", "origin": null, "user_agent": "…"}
{"ts": 1789000001.3, "action": "pairing", "role": "connector", "ok": true, "client": "boardwise-connector/0.2.1", "peer": "127.0.0.1:54048", "fingerprint": "53cd3b41"}
{"ts": 1789000001.4, "action": "hello", "role": "connector", "ok": true, "connectorVersion": "0.4.10", "instanceId": "inst-…", "instanceIdSource": "hello", "windowKey": "inst-…", "tookOverFrom": null, "duplicateInstanceId": null, "projectName": "test2", "projectUuid": "uuid-…", "windowsOnline": 2}
{"ts": 1789000002.0, "action": "disconnect", "role": "connector", "ok": true, "actions": ["pcb.readback"], "windowKey": "inst-…", "projectName": "test2", "projectUuid": "uuid-…", "pageUuid": "page-…", "pageType": "sch", "routed": 7}
{"ts": 1789000003.0, "action": "revoke", "role": "cli", "ok": true, "fingerprint": "53cd3b41"}
```

`connect`, `disconnect`, `hello`, `pairing` and `revoke` are **lifecycle** records: they carry their
own fields and no `ms`. Everything else is a request and carries a duration, plus — since 023 —
`windowKey` and the window's `projectName` when it was routed to one: "which project did that write
land in?" has to be answerable from the call's own line, because the window may be closed by the time
anyone asks. A `hello` record carries the hub key and how many windows were online when it arrived;
a `disconnect` record carries the window's project and page **as last known**, which is where the
identity of a window that has since closed survives. A token — or any slice of one longer than the
8-hex fingerprint — must never appear in this file, and there is a test that greps for exactly that.

`connector_rejected` (018 §A) is **retired** (023). It used to record a second connector being turned
away, naming both sides; nothing is turned away any more, so nothing writes it. It is kept in this
list because a reader grepping old logs for it deserves to find out why it stopped.

## 9. Security posture

Stated plainly because it is the whole threat model:

- **Loopback only.** The daemon binds `127.0.0.1`. There is no code path that listens on a
  public interface and no option to make one.
- **Two secrets, one per role.** `~/.boardwise/token` is the CLI's, 32 random bytes as 64 hex
  characters, created on first `bridge start`, `chmod 0600` on POSIX. `~/.boardwise/connector-token`
  is the connector's, written by the daemon the first time a connector pairs (§3.4). They are
  separate files on purpose: pairing a connector can neither weaken nor leak the CLI credential,
  and neither token authenticates the other role. On Windows the `chmod` is a no-op and the files
  keep default ACLs — so on Windows the protection is the user profile's ACL, not that call.
- **The connector is not sandboxed.** Anything `eda.*` exposes, an authenticated caller can
  reach. The token is the only gate, which is why it is never logged, echoed in a status
  message, or included in an error `detail` — only its 8-hex fingerprint is.
- **The token is not a capability boundary against local processes.** Any process running as the
  same user can read these files. The threat model is "another program, or a web page, trying to
  get there first" — not "a program that already reads my home directory", which has won
  regardless. Pairing is sized to that: first-use trust, announced on the console, one command to
  undo.
- **The connector's token may come from a weaker source than Web Crypto.** 0.2.1 falls back to
  `Math.random` when Web Crypto is unusable, and *says so* — in the log panel, in `About…`, and in
  the provenance carried inside the stored value itself (`webcrypto:<hex>` / `math:<hex>`, one key
  since 0.2.3 — see §10.19). (The fallback was written after a real editor
  failed to produce a token at all. The first explanation for that — "no `crypto` here" — turned
  out to be wrong, §10.14; the fallback and its disclosure stand regardless, because a realm
  without Web Crypto is a real possibility this code should not be defeated by.) That is a genuine
  weakening (the bytes are not a CSPRNG's), but it does not move the boundary drawn directly
  above: the token's job is to make a later connection distinguishable from the paired one, an
  attacker who can read the file has won on either source, and one who cannot read it cannot
  observe this process's PRNG outputs. The `Origin` rule below is the control that actually
  addresses the web-page case. Anyone who wants stronger provenance can read `About…` and refuse a
  `Math.random` pairing — which is why the source is displayed rather than assumed.
- **What is *not* yet enforced: `Origin`.** The daemon records the `Origin` and `User-Agent` of
  every handshake (task 004c is evidence-gathering) and `check_origin()` currently allows
  everything. The rule — refuse `http(s)://` origins, allow a missing origin and the extension
  host's own — lands in 004d, once the measurements say what the editor actually sends. Do not
  describe this bridge as origin-checked until then.

## 10. Known limitations (v0)

Recorded rather than hidden, so a future session does not have to rediscover them:

1. **Half-open connectors look alive.** `status` reads the hub's socket states (`has_connector()`);
   if the editor dies without a clean TCP close, a window stays "online" until a forwarded action
   times out. Workaround: `boardwise bridge screenshot` — a real round trip — is the honest liveness
   check.
   **The background form of it is bounded since 0.4.17 (026b, §7.1), and only bounded.** A throttled
   window can hold a socket the daemon has already lost while its own page still believes it is
   connected; the Worker watchdog is what eventually drives it back — measured on 3.2.186, a daemon
   restart with the window out of the foreground gave a **151 s** reconnection (`hello` 17:41:17 for
   a daemon listening from 17:38:46), driven by the alarm, not by the page's heartbeats. The
   workaround above stays the honest check for a *foreground* window, and a window that is neither
   connected nor being woken is still indistinguishable from a dead one by `status` alone.
2. **Windows are registered, not deduplicated.** Every authenticated connector gets a hub row, so
   three or four windows is the normal case and the caller decides which one answers — `--project`
   by project, `--instance` by instance id (§3.5). What is
   still missing on purpose: a *retired* window is not re-routed to (the caller is told
   `PROJECT_NOT_CONNECTED` / `WINDOW_NOT_CONNECTED` and the window list), a window that connects
   twice under one instance id is
   reported as `PROJECT_AMBIGUOUS` rather than merged (the 3.2.175 double activation), and the
   connector does not push a context change on its own — a response refreshes it. Still one
   workstation's model, too: a second machine cannot share the bridge. **The daemon's own
   multi-project addressing was deliberately deferred** (004f): the per-project pairing table and
   `connectors.json` that task first specified were **withdrawn**, because the premise they were
   built on was measured to be false — see item 24. `--project` (023) is a *routing* hint against
   what each window reports, not a per-project pairing table.
3. **`canvas.highlight` cannot mark pads, tracks or vias by uuid.** `locate()` tries component
   namespaces first; other primitive kinds fall back to their namespace `get(uuid)` and start
   coordinates, so a track is marked at its start point, not along its length.
4. **Write actions exist, and since 012 they are no longer only what the draw flow needs**
   (superseded in 0.3.x — this entry used to read "none, by design"). `sch.place_*`,
   `sch.set_component_attribute` and `sch.doc.save` mutate the page; 012 added
   `sch.delete_primitives` / `pcb.delete_primitives`, `sch.modify_primitive` /
   `pcb.modify_primitive`, `doc.focus` and `doc.delete_page`. Delete makes the harness able to
   clean up after itself, but nothing drives it for you — these are reached through
   `boardwise bridge call`, so a run that leaves a page is still the operator's to clear. Still
   no DRC run.
5. ~~**`document.current` reports all three documents, not the focused tab.**~~ **Corrected
   2026-09-16 (004f item 4).** There *is* a focused-document getter —
   `dmt_SelectControl.getCurrentDocumentInfo` — and `document.current` now reads it, the same call
   `doc.list` uses, so the two cannot disagree. Before this, `type` was derived from the
   split-screen tab tree, whose objects carry **no `documentType` on this build**; the derivation
   therefore answered `unknown` for a schematic page in front while `doc.list` named the same page
   correctly. Consequences to rely on: `active` is the focused document and `typeSource` says
   which read produced `type`; when `heuristic` is `true` the answer came from a fallback and
   **must not be used as a criterion**. `tabs[]` is still returned, for display only.
6. **`sch.readback` / `pcb.readback` summarise primitives rather than returning them raw.**
   Editor objects are method-based (`getState_*()`), so the connector walks those getters, keeps
   scalars and reports counts for collections. A field the connector does not know about is
   still surfaced through the per-item `fields` bag, but nested structures are reduced to
   `{count}` or `{object: true}`.
7. **The editor's globals are not `globalThis`.** `eda` is bound as a context global in the
   extension host: bare `eda` resolves, `globalThis.eda` is `undefined` (§3.2 a). Anything the
   extension needs from the editor must be **passed in explicitly** by `index.ts`, never looked up
   off `globalThis`. The transport no longer has any global fallback, on purpose.
8. **The editor's connect callback cannot be trusted.** `eda.sys_WebSocket.register`'s 4th
   argument does not reliably fire — see §3.2 b. The transport treats it as advisory and drives
   `hello` from inbound frames. Consequence: **anything that needs to run "on connect" must be
   triggered by a frame, not a callback.** A future feature that assumes a working connect
   callback will silently never run.
9. ~~**An out-of-flow netlist export comes back empty.**~~ **Withdrawn 2026-09-16 — it was a
   probe bug, not a host behaviour.** The reading came from a shell-side probe that looked at the
   payload **without parsing the `text` field**, so a perfectly good export was reported as
   "0 components". `sch.netlist` returns the netlist as a JSON string under `data.text`; a
   consumer that reads `data` and stops sees an empty netlist no matter how healthy the editor
   is. The export is **not** anchored to a focused page, and there is no save-ordering problem —
   both explanations were built on the bad reading and are withdrawn with it.
   **Consequence for readers of this document:** the claims this entry used to carry about "which
   page is focused" were never measured. Go through `data.text`.
10. **A netlist export taken immediately after a write can be *stale*, and that IS real.**
   Measured repeatedly on 2026-09-15/16: the editor recomputes connectivity asynchronously after
   `sch.place_wire`, so an export issued right after the last create describes the page as it was
   **before** that wire. Reproduced on the golden board: the run reported `U1.16` unconnected
   while the same page, re-exported a moment later, had it in `VCC` — and a full membership
   comparison against the golden matched net for net. **A read that is merely early is
   indistinguishable from a broken board**, which is what made this expensive to find.
   `engines/draw.py::_settled_netlist` therefore saves and exports **until two consecutive reads
   agree** (up to four attempts), records how many attempts it took, and marks the verdict
   untrusted if it gave up — so "I do not know" and "I know" stay distinguishable in the report.
11. **`export.screenshot` gets 60 s because a render is slow — and that is a guess, not a
   measurement.** No render on a large board has been timed yet. If screenshots start timing out
   on real designs, this is the number to revisit first.
12. ~~**The socket wiring has no automated guard.**~~ **Closed in 0.2.0.** `index.ts` now takes
    its editor through an injectable facade (`src/facade.ts` — the only module allowed to touch
    the host global), `tests/wiring.test.mjs` drives the whole production path (activate → resolve
    config → generate a token → register a socket → answer the banner), and two source guards
    forbid both known shapes of the old bug. See §12.
13. **Pairing pairs whoever arrives first.** Between `bridge start` and the first connector, any
    local process or web page that reaches the port can claim the pairing — that is what
    first-use trust means. Mitigations, all of them visible: the announcement on the console, the
    `pairing` audit record with the client string and peer, `bridge status` showing the
    fingerprint, and `bridge revoke` to start over. What is *not* yet in place is the `Origin`
    rule that would close the web-page half of this (§9). Since 004f the same applies to a
    **re-pair** (§3.4): an unattached pairing may be re-taken, and that too is announced and
    audited as `re-pairing`, with the fingerprint it replaced.
14. **`revoke` cannot exclude one token.** It forgets the pairing, so *any* connector re-pairs
    next — including the one you just revoked. Distinguishing "the connector I distrust" from
    "the connector I reinstalled" is not possible from a token alone; the honest behaviour is to
    make the decision visible again rather than to pretend to a blocklist.
15. **The connector shows a fingerprint it did not compute.** `About…` reports the fingerprint
    the *daemon* sent in the `hello` answer, because a verified one would need SHA-256 in the
    extension and the editor's crypto surface is not guaranteed (see 14 — the first claim that it
    was *absent* did not survive measurement). It is enough for the user to compare the editor's
    line with `bridge status`, but it is not a proof of possession — do not present it as one.
16. **Why the token was missing: answered — activation never fired, and the store was half-written.**
    0.2.0 produced `token: NONE — this editor cannot generate one` with `state: idle`, and that was
    attributed to `crypto` being unreachable from an extension realm. **0.2.1 disproved that** — its
    own `About…` probes the realm and returned `crypto=ok`, i.e. `getRandomValues` is there and
    callable. The lesson is about the *inference*, not the API: "no token" was read as "generation
    failed", which it does not imply. The two causes are only distinguishable by asking whether
    `activate()` ever ran, and nothing recorded that before 0.2.2. Asking it on the machine produced
    `activation: NEVER RAN` — so it is the first cause, and 0.2.3 acts on it (§10.20). The same
    reading of `About…` turned up a second, independent defect: `storage: readable
    (token.source=webcrypto)` printed beside `token: NONE`, i.e. half a stored pair (§10.19). What
    0.2.1+ hold, and what these measurements were made with, is the defensive reading, the reported
    source, the `Math.random` fallback, the source guards, the probe, and the `activation:` /
    `storage:` lines.
17. **A `typeof` probe cannot tell a working function from one that throws.** The 0.2.1 diagnosis
    leaned partly on `describeRandomHost` reporting `crypto=ok`, which it derived from
    `typeof getRandomValues === 'function'`. A sandbox can expose a function that throws when
    called. As of 0.2.2 the description comes from *calling* it, so `crypto=ok` means "it worked".
18. **Nothing recorded whether the editor called `activate()`.** Menus work from a loaded module
    even when activation never ran, so the extension can look healthy while doing nothing at all.
    As of 0.2.2 `About…` reports `activation: NEVER RAN` / `<time> ok` / `<time> FAILED — <error>`,
    and a rejected `activate()` is logged *and* toasted instead of vanishing — an unhandled
    rejection in an extension host is otherwise completely invisible.
19. **A `false` return from `setExtensionUserConfig` used to be ignored.** The API returns a
    promise for a boolean and can resolve `false`; 0.2.x discarded it, so a refused write was
    indistinguishable from a good one until the next reload — when the token was simply gone and
    the connector silently re-paired. As of 0.2.2 it is reported through `tokenNote`.
20. **The token is generated by the connector, not issued by the daemon.** Consequence: a
    connector that cannot generate one cannot pair at all, even though the daemon could easily
    mint a secret. Daemon-issued pairing would need a handshake step beyond the current banner →
    `hello` shape, so it was left for a task that can change the protocol deliberately.
21. ~~**Two adjacent storage writes are not a transaction, and one of them can vanish.**~~
    **Downgraded in 0.2.4: the half-write was never proven, and the simpler explanation is that
    the observer was broken.** The original evidence was `About…` reading `storage: readable
    (token.source=webcrypto)` beside `token: NONE`. 0.2.3's own `About…` then reproduced the same
    contradiction in the *new* single-key format — `storage: readable (token=webcrypto, 64
    characters)` beside `token: NONE` — which cannot be a half-write, because there is only one
    key. The real cause is §10.21: `about()` resolved the config through `facade?.storage` while
    nothing had created the facade yet, so `token:` was computed with no store at all while
    `storage:` — evaluated later in the same function — read it fine. Two store views in one box.
    Lesson: **when two observations contradict, suspect the observer (two code paths) before the
    observed (the store).** What survives of 0.2.3: one key, `token`, holding
    `"<source>:<64 hex>"` — still the better shape (one write means nothing to half-write, and
    `rePair` clears exactly it), a bare 0.2.0–0.2.2 hex value is still read (as `legacy format`),
    and the upgrade forced no re-pair. But the editor storage's transactionality remains
    unmeasured — do not cite it as a known editor defect.
22. **The editor may never call `activate()`, and menus give no hint.** `activationEvents
    .onStartupFinished` fires at *editor* start; reloading the extension on its own does not
    re-trigger it. Menus keep working regardless — the editor evaluates the bundle to read the
    `registerFn` exports — so the extension looks installed and does nothing at all. That is the
    measured root cause of `token: NONE` (§10.14). 0.2.3 does not depend on the callback: at module
    load it arms two deferred checks (1 s and 4 s), and if `activate()` has still not run while an
    editor global is present, it connects anyway. Deliberately **loud** — it logs `activate() was
    not called; connecting anyway (self-arm)` and `About…` reports `NEVER RAN — self-connected at
    <time>`, so quiet coverage never hides a host behaving badly. The `NEVER RAN` still stands:
    that line answers "did the editor call us", which is a fact about the editor, not about us.
    `activate()` remains the primary path and wins the race — a shared one-shot guard means only
    one of the two ever opens a socket.
    **On the machine (0.2.3, 2026-09-13): the arm left no trace.** `About…` 13 s after load showed
    a bare `NEVER RAN` — no `self-connected`, no `FAILED` — while the store held a token some
    earlier module instance had written. So in that instance neither probe left a record, and
    0.2.3's probes were silent on the miss path — the exact blind spot 0.2.2 exists to prevent,
    rebuilt one version later. 0.2.4 closes it: every probe outcome is recorded
    (`self-arm <trigger>: editor global not reachable`, in the log panel and in `About…`), and the
    **menus are the guaranteed arm path** — `About…` arms after building its box, so one click is
    enough to connect even if the host discards idle timers. The arm stands down honestly when
    auto-connect is off (and releases its claim so a later arm can try again), and a manual
    `reconnect` claims the attempt so the self-arm can never pile a second socket on top.
    **Revised again in 0.2.5 (004d, measured under the new daemon): the arm is dead, long live the
    bootstrap.** The restart experiment settled it: full editor restart, zero clicks, 15 s — zero
    TCP; one About click — still zero TCP, confirming that menu-click contexts die before their
    async work runs, while one 0.2.x instance's module-load-initiated chain had sustained a
    48-minute reconnect loop (274 audited connects) on its own. Conclusion: **the only window the
    host reliably keeps alive is the module's synchronous evaluation**, so since 0.2.5 the connect
    starts exactly there (`bootstrapAtModuleLoad()` → `connectOnce()`, fire-and-forget), timer
    probes are deleted (they could only produce misleading logs), and the menu click is demoted to
    a redundant safety net (it re-evaluates the bundle, whose bootstrap has already claimed the
    attempt). Cross-evaluation idempotency: the claim gate within a copy, and the deterministic
    first socket id (`boardwise-1`) across copies — the editor sees a re-registration of the
    connection it already has, not a second one. `activate()` is downgraded to a supported trigger
    through the same gate; whether the host ever calls it is now a cleanliness question, not a
    correctness one.
    **Field result, 2026-09-23 (issue #4): on 3.2.149 the skipped activation is an upstream
    report, not a fact.** The 024 book read upstream #219/#221 (`hw()` sets
    `isExtensionsInitialized` before calling `Ig()`, which returns early until the user info
    exists) as a confirmed defect of 3.2.149 and built the module-scope bootstrap as the way
    around it. Measured instead on EasyEDA Pro **3.2.149.88089769** with connector **0.4.15
    registered in the extension library** (not sideloaded): a cold start **does** dispatch
    `activate()` — `activation: 10:25:01 ok`, `lifecycle: moduleBootstrapObserved=yes
    activateObserved=yes evaluations=3`, `state: connected`, paired — and closing and reopening
    the window behaves the same. So the item above keeps the meaning it always had: what it names
    is the **reload-without-restart** case, and that is the case the bootstrap exists for; on
    this host the bootstrap is **idempotent defence**, not a workaround for a defect reproduced
    here. One combination is still unmeasured and must not be cited as fact either way: a
    **sideloaded** build on 3.2.149 — the state the 024 observation was made in. A second symptom
    from the same run is not activation at all: with two windows open the daemon registered one,
    and the second appeared only after its page was reloaded — window freeze / lazy evaluation,
    the same cause as the 7-hour background-window freeze measured on 3.2.186
    (`tasks/025-review-flow-v2.md`), which is why multi-window work keeps 3.2.186 as its baseline.
    **026b (0.4.17, measured on 3.2.186, 2026-09-23): the background case now has a bound, and the
    number is honest.** The connector ships a Worker watchdog (§7.1), and this is what it actually
    did on the machine. A background window's page timers run at **~1 tick a minute** — read off the
    daemon's own audit as a 60 s `ping` spacing (17:42:18 → 17:43:18 → 17:44:18), the throttled
    regime §7.1 describes. Killing the daemon and restarting it while that window stayed out of the
    foreground, the connector returned **151 s later** (hello 17:41:17 for a daemon listening from
    17:38:46); the **≤90 s target was not met**. The watchdog was running and it is what performed
    that reconnection — the transport's own record says so in as many words:
    `lastError: watchdog wake (worker alarm after 59207 ms of page silence): 3 heartbeats
    unanswered` (the wake's reconnect branch, not the heartbeat timer's), with `watchdog: {state:
    running, wakes: 6, activityPosts: 186}` in `sys.connector_status`. What gated it is the miss
    limit: a half-open socket is only *declared* dead after three heartbeats go unanswered, and
    under a 60 s throttle that is three minutes of silence — the alarm's earlier wakes hit the
    "…unanswered heartbeat(s) — pinging now" branch, and a ping into a dead socket proves nothing.
    So: the watchdog bounds the loss to one throttled cycle *once the transport already agrees the
    socket is dead*, and no better. **Closed in 0.4.18 (026c):** a wake with *any* unanswered
    heartbeat now means dead outright, and the wake's reconnect no longer passes through
    `setTimeout(…)` — which a throttled page defers along with every other timer, so "immediate" used
    to contain up to a whole tick of delay. Five machine runs after the change gave 62.8 / 114.9 /
    101.3 / 93.4 / 74.6 s from the kill and 57.9 / 60.6 / 96.7 / 88.8 / 70.0 s from the moment the
    daemon could be reached, against 135–152 s before §7.1's numbers: the connector's own share of a
    recovery is now the wake's silence plus about a second (**48.5–51.1 s measured**), and the rest
    of the spread is the page's own ~1/minute tick — where in that cycle the daemon died is not
    something a connector can control, so the *total* is phase-dependent while the *share* is not.
    **Closed in 0.4.19 (026d):** that residual phase term came from the ping leaving on the page's
    throttled heartbeat timer, so the wake itself became the probe (ping now; the pong is the
    liveness evidence) and the silence threshold went 45 s → 30 s. Three runs with no other change:
    **kill → hello 39.6 / 27.1 / 45.8 s**, i.e. 3/3 inside the 90 s brief and roughly half of it in
    the worst case, with no spread that needs explaining. §7.1 carries the table.
    **Three more measurements from the same batch, because one number would have been a guess.**
    The same experiment was run three times (window out of the foreground, daemon killed and
    restarted): **151.5 s**, **135.5 s**, and a three-window run in which **all three** windows came
    back — the two backgrounded ones at **145.4 s / 145.5 s** and the third (untouched by the test,
    the user's own window) at 139.7 s. So the band is
    **135–152 s**, and every sample missed the 90 s target the same way (the miss limit, not the
    alarm, is the gate). The three-window run also measured a *second* long-standing symptom in its
    3.2.186 form: a freshly opened second window's connector **connected 3 s after launch but could
    not name its project** (`projectName` omitted, reachable only by `--instance`) until its page
    was evaluated again — after the daemon restart that same window came back as `project='test2'`.
    So on this host the second-window symptom is "online but anonymous", not "offline", which is a
    narrower failure than the 3.2.149 report and is why multi-window work should still name its
    target explicitly rather than trust a project hint.
23. **One box, two store views (0.2.3, fixed in 0.2.4).** `about()` resolved the config through
    `facade?.storage` — optional chaining, no facade created — while `storageLine()` used
    `host()`, which builds the facade on first use. Before anything else has run, the first read
    saw no store and the second saw it, so one box could say `token: NONE` beside `storage:
    readable (token=webcrypto, 64 characters)`. That contradiction is what §10.19's "half-write"
    was read from, and it was the wrong reading both times. 0.2.4 creates the facade before
    resolving anything, and a regression test installs a token and asserts the box reports it
    before any activation. Corollary worth keeping: **a diagnostic that reads the same thing twice
    through different paths is two diagnostics, and they can disagree.**
24. **`eda.sys_Storage` is shared by the editor, not scoped per project — and that was measured,
    not assumed.** Task 004f was originally specified as "one connector per project, so store a
    per-project pairing table and address actions by `--project`". DeepSeek's on-machine
    measurements overturned the premise: after a restart the connector connected with its
    **existing** token (`sys_Storage` had not been reset), and `revoke` did not disturb a live
    socket. The earlier "per-project isolation" reading came from a focused-page mix-up. So the
    per-project table, `connectors.json` and `AMBIGUOUS_TARGET` were **withdrawn before being
    built**. The single-connector model stood until **023** replaced it with the window hub (§3.5)
    — note what is *not* back: `--project` there is a routing hint matched against what each window
    reports about itself, not a per-project pairing record and not a second token store.
    What *does* reset the store is **sideloading a connector build** — and that, not project
    switching, is the only real cause of the `UNAUTHENTICATED` waves seen on 2026-09-14. §3.4
    turns that into a self-heal instead of a manual `bridge revoke`.
25. **The connector's startup path had a blind spot; it is now bounded and loud (004f item 3).**
    "Restart the editor and it does not connect, and nothing recovers it but another restart" has
    reproduced three times since 0.2.5. Two defects in `index.ts` can produce exactly that, and
    both were invisible: (a) `void bootstrapAtModuleLoad()` had **no `catch`**, so a rejection in
    the first connect attempt left the one-shot claim taken forever — `activate()`, the self-arm
    and `Reconnect` are all no-ops afterwards, with nothing in the log panel and nothing in
    `About…`; (b) when `eda` was not bound at module evaluation the bootstrap stood down for the
    life of that module instance. Since 0.4.1 the bootstrap catches, logs, **releases the claim**
    and retries on a bounded schedule (≈29 s total), recording every attempt. The retry is
    legitimate where 0.2.3's 1 s/4 s probes were not: those never ran because the bundle was not
    loaded at all, whereas a chain started at module evaluation is the one context measured to
    survive (004d: a 48-minute reconnect loop, 274 audited connects).
    **Acceptance passed 2026-09-16: 5/5 consecutive cold editor starts connected with zero
    clicks** (10–19 s each, one `hello ok` per start, and — the check that matters — **no
    `pairing`/`re-pairing` event in any of the five rounds**, so nothing was re-paired to get
    there). Reading "did it self-connect?" from `status: connected` alone is not enough: a single
    manual click looks the same. What distinguishes them is the audit shape — one socket
    dropping, exactly one `connect` arriving, and no pairing record.
26. **An ambient HTTP proxy breaks a loopback connect, and it looks like a dead daemon.**
    `websockets` 17 defaults `connect(..., proxy=True)`, which means "honour `HTTPS_PROXY` /
    `HTTP_PROXY` / `ALL_PROXY`" — and the daemon is on `127.0.0.1`, where a proxy can only be
    wrong. Measured 2026-09-16 with a proxy in the environment: `bridge status` dialled
    `ws://127.0.0.1:61190/eda`, the proxy answered `InvalidProxyStatus: proxy rejected
    connection: HTTP 502`, and the CLI reported "daemon not reachable" while the daemon was
    fine. `BridgeClient.open` now passes `proxy=None`; `tests/test_bridge_cli.py` pins it, and
    the rule generalises: a loopback destination never goes through a proxy.
27. **One editor profile, one extension record — and three consequences the multi-window
    operator has to know (030).** Measured on the machine 2026-09-24 (岳, updating with two windows
    open) and pinned by tests:
    - **Several windows share one IndexedDB record.** The connector bundle and its
      `config.version` live in `User_<teamUuid>_v6` (`connector/src/self-update.ts`), one record per
      editor profile, **not per window**. So `sys.self_update` in the second window reports
      `0.4.19 -> 0.4.19`: the record was already updated by the first. That is not an error and not
      a no-op either — the write is what schedules that page's `location.reload()`, so `--all`
      cannot skip it (§8) and says instead "N windows share this record, it changed once".
    - **A reload replaces the window's identity.** `INSTANCE_ID` is minted per module evaluation
      (`connector/src/index.ts`, `newInstanceId()`), so both the claimed instance id and the
      daemon's hub key change; the old id is dead the moment the page goes away. Anything written
      before the update ("update window `inst-…`") has to be re-read afterwards, and the
      verification can only bind "the window I wrote to" to "the new connection" through the
      table: its old identity **gone**, a connection that was not online before announcing the
      stored version. Reading "some window announces the stored version" was the pre-030 rule, and
      it let a *different* window of the same profile satisfy this one's `verified`.
    - **After a reload the window is anonymous until it answers something.** It greets the daemon
      before the editor API is ready, so the table has no `projectName` for it and `bridge status`
      prints it without a project. Measured 2026-09-24 on this machine, and the shape is worth
      knowing exactly: the reloaded window hello'd at **10:55:09**, `bridge call --project test`
      failed `PROJECT_NOT_CONNECTED` at **10:55:27** (the daemon had nothing to match the name
      against), **one** routed call by `--instance` at 10:55:38 refreshed its context — and
      `--project test` worked again from that moment on, with no further wait. So the escape hatch
      during the anonymous phase is the **instance id**, and project routing returns with the
      window's first answer; treat 岳's "~4 minutes" as the worst case he saw, not as a timer to
      wait out. This is **not** a display bug and not a sign the window was lost (§10.27).

28. **A hung export means the target page was never activated — and 031/032/033 are the three
    halves of that one symptom (issue #5).** The measurements, in the order they were made:
    - **The export hangs when the page has never been activated (033, the cause).** Controlled
      comparison on 岳's **3.2.149 + connector 0.4.21**, same window, same page, four minutes
      apart: 15:48:19 `export.render png page` with nothing opened first → TIMEOUT (30 s);
      15:50:00 `svg` the same way → **TIMEOUT too**; then `doc.open` the page (`activated: true`)
      → 15:54:02 `png` succeeded in **~2 s** (662229 bytes, magic checked). So the variable is
      *activation*, and it applies to png and svg alike. Two earlier readings are therefore
      **withdrawn**: "PNG hangs while SVG answers in the same second" rested on a single sample
      (2026-09-23 18:05:53's success came minutes after a checkup had opened that page — it was
      still warm), and "the host dislikes an argument" is the 2026-09-18 `.d.ts` trap, a real trap
      but not this symptom.
      One mechanism explains every historical observation: `boardwise checkup` never failed (its
      canvas stage opens every page before rendering it — that caller got it right by
      construction), and every bare `bridge call export.render` hung (nothing had focused the
      page). H1 ("it must be the active document") and H2 ("it must have been activated at least
      once") are not separated, and do not need to be: **since 0.4.22 the action activates the
      target page itself** — `scope=page` resolves `params.pageUuid` ?? the active document, calls
      `dmt_EditorControl.openDocument(uuid)`, and only then exports, reporting
      `activatedPageUuid`. An unresolvable active document, a throwing `openDocument`, or one that
      returns no tab id is an honest error and **no export is attempted** (with `doc.open`'s own
      diagnosis in `detail`). `scope=selection` / `scope=project` are untouched.
      **checkup is deliberately unchanged**: it opens each page itself, so it was never exposed to
      this. The 031 PNG→SVG fallback stays — it keeps a *timeout* from failing the whole canvas
      stage — but its premise is retracted: svg hangs the same way on an inactive page.
    - **The progress toast the export leaves behind (032).** Measured 2026-09-24: the render
      **succeeds** — `canvas-sch.png`, 664172 bytes on disk, no fallback, no error — and the editor
      still sits at 99% until a human closes the bar (another window: 326 KB, same shape). So the
      stuck toast is neither a timeout symptom nor a failure symptom: the ManufactureData pipeline
      opens a progress bar and never retires it, on both outcomes. **Since 0.4.21** `exportRender`
      wraps its export call in `try`/**`finally`** and schedules — 400 ms later, so the platform's
      own teardown is not raced — a best-effort `sys_LoadingAndProgressBar.destroyProgressBar()` +
      `destroyLoading()` (`@public`, idempotent, safe with no bar on screen; `typeof`-guarded and
      try/caught per call, so an older host or a refusing destroy cannot change the export's
      outcome). 岳 verified the disappearance on two independent samples — the 15:48 and 15:50
      timeouts above.
    - **A healthy connection cannot rule out a host fault.** Everything the bridge can read about
      itself (sockets, heartbeats, routing counters) describes the *channel*: a promise the host
      never settles produces the same "connected" picture as an idle editor. The only honest signal
      is the call's own timeout, which is why the action has one (and why 031's short leash exists).
    **Superseded guess:** the review-mark indicator markers were one early hypothesis for the
    trigger. The measured cause is page activation, and no batch since has needed the marker story.
    **Three steps, not one (034).** `openDocument(uuid)` opens a **tab**; `activateDocument(tabId)` is what brings the document to the front, and its argument is the **tab id**, not the uuid; `getCurrentDocumentInfo()` is the readback that confirms it (`matchesRequest`). 0.4.22 performed only the first — its 149 acceptance failed (a bare `export.render` still timed out twice with 0.4.22 running, and succeeded in 2 s right after a `doc.open`). Since **0.4.23** the export calls the `doc.open` handler itself (one implementation, so the two cannot drift) and refuses to export unless activation returned true **and** the readback matches; the answer carries `activatedPageUuid` + `activated: true`. H1/H2 is settled: **activate before every export**, not once per page load.

## 11. Relationship to `easyeda-agent` frames

The envelope is deliberately close to the frames reconnoitred from `easyeda-agent` (MIT) in
2026-08, so behaviour learned there transfers: `id` correlates, `ok` decides, `error.code` is
machine-readable. Two deliberate differences:

1. Results travel in `data`. `easyeda-agent` spreads them across `result` / `context` /
   `artifacts`; one field is easier to validate and to type on both sides.
2. The action catalogue is **declared**, not discovered at runtime. `ACTIONS` in `protocol.py`
   is the single source for the daemon's routing table, the CLI's `--help`, and the docs — so an
   action cannot exist in one place and be missing in another.

## 12. How the claims here were verified

| Claim | How |
|---|---|
| Envelope, routing, error codes, role guard, audit | `tests/test_bridge.py`, real WebSocket on `127.0.0.1:0` |
| CLI exit codes (`0`/`1`/`2`), token creation, audit trail | `tests/test_bridge_cli.py` — a real `bridge start` subprocess on a free port, no EasyEDA needed |
| Daemon ignores request path and query string | Probe: `/`, `/eda`, `/a/b?foo=1` all completed a `ping` handshake |
| Both sides classify a frame the same way | `frame_kind` / `frameKind` asserted against the same three shapes on each side (`tests/test_bridge.py`, `connector/tests/protocol.test.mjs`) |
| The daemon speaks first | `test_daemon_speaks_first_with_a_banner` — a raw socket receives `{"event":"banner",…}` before sending anything |
| The banner is an event and carries no secret | `test_banner_frame_is_an_event_and_carries_no_secret` — no `id`, no token, `frame_kind == "event"` |
| A banner *alone* triggers `hello` | `connector/tests/transport.test.mjs` — a banner is injected with **no** `socket.connect()` call, and `hello` must be sent |
| A banner is answered with `hello`, never with an error | `connector/tests/transport.test.mjs` — the reply is the `hello` request, not `BAD_REQUEST` |
| `hello` is sent exactly once per attempt | `connector/tests/transport.test.mjs` — both triggers (callback *and* banner) fire; one `hello` total |
| The heartbeat starts after `hello`, not on the callback | `connector/tests/transport.test.mjs` |
| Silence is hung up on and audited | `test_a_silent_connection_is_hung_up_and_audited` — `HELLO_TIMEOUT` monkeypatched to 0.5 s |
| Every socket end is audited, even a pre-hello drop | `test_raw_connection_and_disconnection_are_audited` — a bare socket that never says `hello` still yields a `connect` (with `peer`) and a `disconnect` record |
| `boardwise bridge --help` lists the real catalogue | `test_bridge_help_renders_the_action_catalogue` — renders `ACTIONS`, so help cannot drift from routing |
| The focused document is read from one call, by both actions (004f) | `connector/tests/actions.test.mjs` — with a schematic page in front and a tab tree carrying no `documentType`, `document.current` must name that page's uuid and `doc.list` must agree; a fallback is asserted to be marked `heuristic: true` |
| `hello` carries the connector's build, and an old one is not refused | `connector/tests/transport.test.mjs` (field present / absent in the frame) and `tests/test_bridge.py` — the audit record's `client` ends with `connector=0.4.1`, or with `(version unknown)` when the field is missing |
| An unattached pairing may be re-taken, an attached one may not (004f) | `tests/test_bridge.py` — `test_a_new_token_re_pairs_when_nothing_is_attached` (audited as `re-pairing`, with the fingerprint it replaced) and `test_a_live_connector_is_not_displaced_by_a_new_token` |
| A bootstrap that throws is loud, and does not hold the claim (004f) | `connector/tests/wiring.test.mjs` — an injected throwing `sys_Storage` must log `bootstrap FAILED: …` and a later `activate()` must still be able to connect; a stand-down retries once the host appears |
| `requestFrame` byte shape | Asserted on both sides (`tests/test_bridge.py`, `connector/tests/transport.test.mjs`) |
| `ActionError` survives a bundle boundary | `connector/tests/transport.test.mjs` — a foreign, structurally-valid error keeps its code instead of becoming `INTERNAL` |
| Reconnect after missed heartbeats | `connector/tests/transport.test.mjs`, polling for the condition rather than sleeping |
| `.eext` is a well-formed ZIP of the current build | `connector/tests/package.test.mjs` — parses the central directory and inflates every entry; CRC and size checked against the file on disk |
| `eda.sys_WebSocket` signature (no `onClose`) | `@jlceda/pro-api-types@0.4.25` type definitions — `register(...)` returns `void` |
| The connect callback is unreliable, and the reference works around it | Read from the extracted `easyeda-agent-connector.eext`: `register(id, \`ws://127.0.0.1:${port}/eda\`, onMessage, () => {})` — a deliberately **empty** 4th argument, with the handshake triggered by the inbound `{type:"handshake"}` frame inside `onMessage` |
| `eda.sys_Log.add` is the editor's log panel, and the reference uses it for diagnostics | Same source: its `diag()` helper is `eda.sys_Log.add(\`[easyeda-agent] ${msg}\`)`, called on every register/retry decision |
| The `.eext` layout | Unzipped the reference: root `extension.json` + `dist/index.js`, manifest using `entry: "./dist/index"`, `engines.eda: "~3.2.0"`, `activationEvents.onStartupFinished`, `headerMenus` — the same spellings ours uses |
| `globalThis.eda` is `undefined` in the extension host while bare `eda` resolves | **On the machine, 2026-09-13**, via the editor's own script console: `tools/probe1-surface.js` returns `edaType: 'object'` but `globalType: 'undefined'`, `same: false`; `tools/probe2-register.js` then called `eda.sys_WebSocket.register` from that scope and a real TCP connection reached the daemon (audit: `connect` from `127.0.0.1:54048` at 02:20:53, closed 3.4 s later by the probe) |
| A failed socket lookup was silent | Read from the 0.1.1 `.eext`: its `Transport` getter was `this.options.socket ?? globalThis.eda?.sys_WebSocket` while `buildTransport` passed no `socket` — so `socket` was always `undefined` and `connect()` returned into `scheduleReconnect('eda.sys_WebSocket is unavailable')` without ever calling `register`. 0.1.2 passes the socket explicitly; 0.2.0 removed the fallback entirely and made the wiring testable (§10.10, now closed) |
| Rectangle markers take `left/right/top/bottom`, not the line/arc fields | `@jlceda/pro-api-types` `IDMT_IndicatorMarkerShape`, confirmed on the machine: 0.1.2 sent `startX/startY/endX/endY`, the editor returned `true` and rendered **nothing**; 0.1.3 with the correct fields drew the box. Guard: `connector/tests/actions.test.mjs` asserts the exact key set |
| `canvas.highlight` end-to-end | **Human-confirmed 2026-09-13**: `boardwise bridge highlight <U1 primitiveId> --zoom` through our own daemon + 0.1.3 connector zoomed the canvas to U1 and drew the red rectangle; `--clear` removed it. Note: markers live on the interactive overlay, so exported screenshots are expected to be byte-identical with and without markers |
| `hello` from the editor reaches the daemon | **On the machine, 2026-09-13** (0.1.2/0.1.3): audit log shows `hello role=connector ok=true client="boardwise-connector/3.2.149.88089769"` followed by `ping` heartbeats |
| The first connector pairs, later ones must match | `test_first_connector_is_paired_and_remembered`, `test_a_paired_connector_pairs_only_once`, `test_hello_rejects_bad_token` — plus the CLI-level `test_a_connector_pairs_itself_and_then_only_that_token_is_accepted`, which pairs over a real socket against a real `bridge start` subprocess and then gets refused |
| An empty or missing token never pairs | `test_an_empty_token_never_pairs` (parametrised `""`/`null`) — refused, nothing written, no `pairing` record |
| A version-mismatched connector is never paired | `test_version_mismatch_never_pairs` — the version check runs before the record is written |
| The two roles keep two secrets | `test_pairing_a_connector_does_not_touch_the_cli_token` — the connector's token is refused as `cli`, the CLI's token is refused as `connector`, and `cli` still works |
| `revoke` forgets the pairing and the next connector re-pairs | `test_revoke_forgets_the_pairing_and_the_next_connector_re_pairs`, `test_revoke_without_a_pairing_is_a_no_op`, and `test_revoke_is_a_local_command_and_needs_no_daemon` (the CLI runs with nothing listening) |
| A token never reaches the audit log, the console or About… | `test_the_token_itself_never_reaches_the_audit_log` greps every audit line for the token *and* for its first 8 characters; `connector/tests/wiring.test.mjs` asserts the About box and log panel hold the fingerprint and not the token; the CLI test asserts `status` prints the fingerprint only |
| `connect` records `Origin` / `User-Agent`, absent → `null` | `test_connect_audit_records_origin_and_user_agent`, `test_a_missing_origin_is_recorded_as_null` |
| `check_origin` currently allows everything | `test_check_origin_allows_everything_for_now` — written as an assertion so 004d cannot inherit "always allow" without deleting it on purpose |
| The extension wires the editor's socket into the transport | `connector/tests/wiring.test.mjs` — with an injected facade: `activate()` registers the socket, a banner produces a `hello` carrying a generated 64-hex token, and the token is persisted |
| Every authenticated window is registered, none refused (023) | `test_every_window_that_authenticates_is_registered` (two windows, one shared token, both `ok`, both in `ping`), `test_two_live_sockets_claiming_one_instance_id_both_stay_visible` (the second under `inst-…~2`), and `test_the_refusal_machinery_is_gone_and_its_code_is_retired` (`refuse_if_held`, `RejectionNotice`, `active_instance`, `recent_rejections`, `on_rejection` all gone; no `connector_rejected` record is written) |
| A project hint reaches exactly the window that has it, and only it | `test_a_project_hint_routes_to_the_window_that_has_it` — by name *and* by uuid; each fake window records what it received, and the other receives nothing. `test_call_project_hint_reaches_that_window_from_the_cli` drives the same thing through a real `bridge call --project` subprocess against a real daemon |
| An instance hint reaches exactly the window that claimed it (023 follow-up) | `test_an_instance_hint_reaches_that_window_without_any_project` — two windows that can name **no** project (the restarted-editor state), where the project hint is refused and the instance hint still lands on one socket and not the other; `test_an_instance_hint_wins_over_a_project_hint`; `test_an_instance_hint_that_matches_no_window_lists_the_online_ones` (the message, verbatim); `test_an_instance_hint_names_one_of_two_connections_sharing_an_id` (the `~2` key is addressable); and `test_call_instance_hint_reaches_that_window_from_the_cli`, which drives the flag through a real CLI subprocess |
| Routing refuses rather than guesses | `test_a_hint_that_matches_no_window_lists_the_online_ones` (`PROJECT_NOT_CONNECTED`, exact message including `projectName (instanceId)` per window), `test_a_hint_that_matches_two_windows_is_ambiguous` (`PROJECT_AMBIGUOUS`, nothing forwarded), `test_several_windows_and_no_hint_are_refused_not_guessed` (`WINDOW_UNSPECIFIED`), `test_a_single_window_needs_no_hint` (the pre-023 path, unchanged) |
| A window's context is live, not frozen at the handshake | `test_a_response_context_moves_where_that_window_routes` — a window that answers while showing another project is found under the new name/uuid and **no longer** under the old one; `test_a_context_that_could_not_be_read_never_erases_what_is_known` (nulls, empty strings, unknown keys and non-objects change nothing) |
| Disconnect removes the window, and only that one | `test_ping_drops_a_window_as_soon_as_its_socket_closes` — the remaining window is still routable, the closed one's project becomes `PROJECT_NOT_CONNECTED`, and its `disconnect` record carries the project and page it was last known to have. `test_a_dead_socket_is_displaced_without_a_fuss` covers the reload (`tookOverFrom`, no duplicate) |
| Writes serialise per window; other windows run in parallel | `test_writes_to_one_window_serialise_while_other_windows_run_in_parallel` (wall-clock spans from a fake connector), `test_a_read_does_not_take_the_write_lock` |
| A response is accepted only from the window that was asked | `test_a_response_from_another_window_does_not_answer_the_call` |
| `bridge status` shows every window | `test_status_lines_render_the_window_table`, `test_status_lines_map_every_online_window_to_its_project`, `test_status_lines_say_nothing_about_projects_nobody_named`, and the CLI-level `test_status_lists_every_connected_window` / `test_status_maps_every_window_to_its_project` against a real daemon process |
| The whole production path runs in CI | Same file, via `__setFacadeForTests` — this is the gap that let `globalThis.eda` ship twice (§10.10) |
| Only one module touches the host `eda` global | `connector/tests/source-guard.test.mjs` — reads `src/*.ts`, ignores comments and string literals, and allows `eda.` only in `facade.ts`; a companion test fails if the facade stops referencing `eda` |
| `Set token…` is gone and the menus all resolve | `connector/tests/wiring.test.mjs` — parses `extension.json`, asserts every `registerFn` is exported and that `setToken` is not among them |
| Only one module touches the ambient `crypto` global | `connector/tests/source-guard.test.mjs` — the *same rule for the second host global*: `crypto.` is allowed only in `random.ts` and `globalThis.crypto` is forbidden everywhere, plus a companion test that fails if `random.ts` stops reading the global or stops reporting a source |
| A host without Web Crypto still connects, and says what it used | `connector/tests/random.test.mjs` (unit: absent / no `getRandomValues` / throwing / nothing usable at all) and `connector/tests/wiring.test.mjs` (end-to-end with an injected crypto-less host: the token is still 64 hex, `math:<hex>` is persisted, the log warns, `About…` names `Math.random` and still never prints the token) |
| `About…` explains *why* it has no token | `connector/tests/wiring.test.mjs` — a host with neither source reports `crypto=unavailable`, in the log panel and in the box |
| A `typeof` probe is not evidence a function works | `connector/tests/random.test.mjs` — the description is produced by *calling* `getRandomValues` (asserted with a call counter) and a function that throws is reported as `crypto=getRandomValues threw TypeError`, not `crypto=ok` |
| `About…` says whether `activate()` ever ran, and a failed one is never silent | `connector/tests/wiring.test.mjs` — `NEVER RAN` before activation, `<time> ok` after, and an injected throwing `sys_Storage` yields `activate FAILED: …` in the log panel, a toast, and `FAILED` plus the cause in the box |
| A refused token write is reported, not swallowed | `connector/tests/config.test.mjs` — `setExtensionUserConfig` resolving `false` still yields a usable token *and* a `tokenNote` saying it was refused |
| The token is stored under exactly one key, never a pair | `connector/tests/wiring.test.mjs` — the fake store records every key written and the assertion is `['token']`, so reintroducing a second key (the 0.2.1/0.2.2 partial-write bug, §10.19) fails the suite; `connector/tests/config.test.mjs` asserts the stored value is self-describing (`webcrypto:<hex>` / `math:<hex>`) |
| A 0.2.2 bare-hex token still pairs after the upgrade | `connector/tests/config.test.mjs` — `ensureConnectorToken` reads a plain 64-hex value and reuses it rather than regenerating, so upgrading does not force `bridge revoke` |
| `About…`'s `storage:` line summarises without disclosing | `connector/tests/config.test.mjs` — `describeStoredToken` over `unset` / `webcrypto:<hex>` / `math:<hex>` / legacy, asserting the summary never contains the value |
| The extension connects even when the editor never calls `activate()` | `connector/tests/wiring.test.mjs` — with an injected facade and **no** `activate()` call, the module bootstrap registers the socket and answers the banner; since 0.2.5 this is the primary path, started at module evaluation (the one window the host measurably keeps alive, §10.20) |
| Re-evaluating the bundle cannot open a second socket | `connector/tests/wiring.test.mjs` — the bootstrap run twice leaves exactly one registration (the claim gate); across copies the deterministic first socket id (`boardwise-1`) turns a re-registration into a no-op on the editor side |
| The self-arm and `activate()` cannot both open a socket | `connector/tests/wiring.test.mjs` — `activate()` then the self-arm leaves exactly one registration (the shared one-shot guard); the self-arm is a no-op with no editor present, which is the Node path |
| `About…`'s `token:` and `storage:` lines describe the same store | `connector/tests/wiring.test.mjs` — a token is installed and `about()` runs before anything else: the box reports `token: storage, 64 characters` and never `NONE` (the 0.2.3 regression, §10.21) |
| A menu click arms the connection | `connector/tests/wiring.test.mjs` — `about()` alone leaves exactly one registration; the in-flight arm is awaited through the test seam, not slept on |
| A missed self-arm probe is recorded, not swallowed | `connector/tests/wiring.test.mjs` — a probe told the editor is absent logs `self-arm …: editor global not reachable` and the box carries it (`self-arm: …`), so "probes ran and missed" is distinguishable from "nothing ran" |
| The arm stands down instead of claiming a connection it did not make | `connector/tests/wiring.test.mjs` — with auto-connect off the arm records `arm stood down`, never says `self-connected`, releases its claim, and a second arm after re-enabling connects |
| A manual connect claims the attempt | `connector/tests/wiring.test.mjs` — `reconnect()` followed by the self-arm leaves exactly one registration |
| ~~`crypto` is not reachable from an extension realm~~ | **Withdrawn.** This was 0.2.1's diagnosis of `token: NONE`, and 0.2.1's own `About…` disproved it by reporting `crypto=ok`. Recorded here rather than deleted: the error is instructive (§10.14). `tools/probe3-crypto.js` still measures a given editor, and as of 0.2.2 it reports *usability*, not mere presence |
| `export.fab` sends the preset's arguments, position for position | `connector/tests/actions012b.test.mjs` — the fake host records every call and the assertions are positional: `('fab_gerber.zip', false, 'mm', {4,5}, {drillTable: true, …}, undefined, undefined)`, P&P `('fab_pick_and_place.csv','csv','mm')`, and a BOM whose 15 `columns` are told to the host as **two disjoint lists** — the counting columns as `statistics` (2) and the attributes as `property` (13) — with the test asserting their union is exactly those 15 and that neither repeats the other. The BOM's `filterOptions` is one **exclusion** rule (`'Add into BOM': 'no'`), and the name it carries has no suffix because the host appends it |
| The BOM's columns go to the host as two disjoint lists, not as one list twice | **Measured on 3.2.186, 2026-09-21** (`outputs/013_p3_evidence/`, `outputs/013_fab_bishe3/`): the host builds its table from `statistics + property` and does not deduplicate, so a column named in both arrives twice — the preset's `No.`/`Quantity` in both places gave a **17-column header for a 15-column preset** (`序号`…`Number`, `数量`…`Quantity`). The two arguments are not interchangeable either: only `statistics` entries pass through `hne`, which rewrites `No.` into the `Number` column its BOM engine numbers, so dropping `statistics` makes the column check refuse the call and return **no file at all** (`api.js` `getBomFile`: `p.includes(m.property) … else return`). The counting columns therefore stay in `statistics` alone and `property` is derived as the columns minus those two; the header comes back with exactly 15 |
| The BOM's filter rule is an exclusion rule, and the names arrive with the right suffixes | **Measured on 3.2.186, 2026-09-21** (`outputs/013_p3_evidence/`): the host's own `api.js` maps `filterOptions` onto `filterRules` (`mne`/`gne`) and its BOM builder drops a row when the rule matches (`pro-sch` `attrsGroup2` → `verify`), so `includeValue: 'yes'` dropped all 122 parts (`outputs/013_fab_bishe/fab_bom.csv` = 152 B of header only) while `'no'` keeps them; the preset now sends `'no'`. `api.js` also names the files: gerber/P&P are `new File([data], <the name we sent>)` while the BOM is `fileName + '.' + fileType`, which is why only the first two carry suffixes and `fab_bom.csv` does not become `fab_bom.csv.csv` |
| The fab bundle lands as files, and a partial bundle is not a success | `tests/test_fab_export.py` — the writer decodes, writes and re-`stat`s every file, refuses a name that is not one path segment, reports a byte-count disagreement, and the CLI exits 1 for a partial bundle / 2 with no daemon |
| **`export.fab` and `lib.recommend` have run against EasyEDA (013, 2026-09-21)** | Their contracts are pinned (39 mock tests + 14 pytest cases). **`lib_Device.searchByProperties` on 3.2.186 is settled (013 F4, on-machine matrix `outputs/013_f4_probes_real.json`)**: the method is callable and it filters — but only on the keys that host actually indexes. `{supplierId:"C8678"}` returns exactly that one device (a bogus C-number returns none), `{partNumber:"SS34"}` / `{partCode:"C8678"}` / `{value:"SS34"}` are applied as filters and match nothing (they answer `[]`, not the unfiltered page), `{name:…}` / `{footprintName:…}` are ignored outright (they answer the library's default page of ten, same as `{}` and as an unknown key). Call shape is *not* the cause: the argument count (1 vs 6, with and without `libraryUuid`) changes nothing, and `lib_Device.search` reports the same arity (4) as `searchByProperties` while hitting every time. So the earlier "declaration present, runtime empty" reading was wrong — unlike `getPngFile` (declared v3.2.183, absent at runtime) and `createNetLabel` (**ADD since EDA v4**, never settles), this method works; **the key choice was wrong**. `lib.recommend`'s `exact` rung therefore sends `{supplierId: <LCSC code>}` (falls back to not-called when the part has no LCSC code), the `properties` rung is kept as declared and reports in `notes` that it cannot match on this host, and the keyword rung carries the rest. **`export.fab` is settled too** (013 batch②): the gerber is a real zip, the 15 BOM columns come back verbatim, the empty BOM was the filter rule (see the row above), and the file names now match `getting-started` — see `outputs/013_fab_bishe2/` and `outputs/012v2_s6_s7_offline.txt` |
| `review.mark` draws one rectangle per resolved ref, and returns the text the API cannot draw | `connector/tests/actions012c.test.mjs` — the fake host records the single marker call and the assertions are positional/exact: `left/right/top/bottom` around `getState_X/Y`, colour, line width 2, zoom flag; `marked[k-1]` is marker `k` and carries `ruleId`/`severity`/`text` |
| A review pass survives a host that cannot draw it | Same file — `markers: false`, a missing `generateIndicatorMarkers` and a `false` answer all yield `mode: 'list'` with the coordinates and a reason, while `PAGE_MISMATCH`, a non-schematic focused document, an unreadable page, `focus` out of range and `clear` without `removeIndicatorMarkers` stay thrown errors |
| `clear` with nothing open is already done, not refused | Same file — with the host answering its placeholder uuid for "nothing is focused", `clear: true` returns `cleared: true` and the note "no active canvas — nothing to remove" (with the raw reading appended) and never calls `removeIndicatorMarkers`; a canvas that is open and answers `false` still reports `cleared: false` |
| A findings report can be turned into marks without a rule change | `tests/test_review_mark_cli.py` — `render_json` gains per-finding `refs` (derived from evidence, allow-listed so `AMS1117`/`SS34`/`CH340G` are not mistaken for designators), the CLI reads a path / `-` / a JSON literal, and one mark per ref is sent in finding order |
| `boardwise doctor` diagnoses a disconnected installation instead of crashing on it | `tests/test_doctor.py` — `run_doctor` is pure, so no daemon, no connector, an old editor, a stale bundle and an unreadable project are all exercised as data; the CLI-level case (nothing listening) asserts exit 1 and one fix per failing line |
| The daemon reports its own version, so a stale daemon is diagnosable | `tests/test_bridge.py::test_daemon_owned_ping_reports_connector_state` asserts `ping.version == boardwise.__version__`; doctor compares it with the running install and fails with "restart the daemon" on a mismatch |
| **`review.mark` and `boardwise doctor` have run against EasyEDA (013 batch②, 2026-09-21)** | Their contracts are pinned (30 connector mock tests + 48 pytest cases). Machine facts so far: `generateIndicatorMarkers` **accepts** the rectangles (accepted 9/9 on the 毕设板 page) but whether they are *visible* is only partly confirmed — one A/B screenshot pair shows box-shaped geometry, another shows none, and the view moved under a human hand throughout (`outputs/013_p2_findings.txt` §八); `removeIndicatorMarkers` answered `true` once and `false` once in the same session, the `false` with no canvas focused (hence the口径 in the action table); `sys.probe` answers all five spot-checked methods, and `boardwise doctor` is 7/7 on the machine (`outputs/013_sys_probe_doctor.json`). See `outputs/012v2_s8_s9_offline.txt` |

Total: 1136 Python tests (~85 s) + 279 connector tests (~2 s). Everything except the `eda.*`
calls themselves is automated; §13 is what remains for a human with the editor open.

Five claims are **not** automated (four only reproducible by hand, one still open):

1. That the editor delivers the banner, so `hello` reaches the daemon — now **confirmed on the
   machine** (§12, 2026-09-13), but not reproducible in CI.
2. That `eda.sys_WebSocket` is reachable from the extension's scope — the *wiring* is tested now,
   and both known spellings of the old bug are forbidden by source guard, but "the editor really
   exposes it as we assume" can only be confirmed by connecting (and has been, §12).
3. **Whether the connector's token was ever *attempted* on the machine — settled.** 0.2.0/0.2.1
   showed `token: NONE` with `state: idle`; the first explanation ("no `crypto`") was disproved by
   0.2.1's own probe; the 0.2.2 `activation:` line then answered the remaining question with
   `NEVER RAN`. Kept in this list rather than deleted because the answer only arrived by asking
   the editor directly — the two candidate causes were indistinguishable from outside (§10.14).
4. **Whether the self-arm fires on the machine — settled by 0.2.5, accepted 2026-09-13 16:21.**
   The interim findings (0.2.3's traceless probes; 0.2.4's menu-click chain producing zero TCP)
   led to the module-bootstrap design, and the acceptance run closed it: full editor restart,
   zero clicks — audit shows `connect` (with `origin: "https://client"` and the editor's
   User-Agent, JLCEDAPro/3.2.186, Electron/41) → `pairing` (fingerprint `43b8e7a1`) → `hello
   ok=true`, then a steady 5-second heartbeat; `bridge status` says connected; `bridge screenshot`
   completed a real round trip. That audit line is also **004d's editor `Origin` sample** — the
   remaining sample (a deliberate browser-console connection) is what the whitelist still waits
   for. One nuance the run added: a menu click re-evaluates the bundle, and that fresh instance's
   `About…` shows `state: idle` because it cannot see the long-lived instance's connection —
   `bridge status` and the audit are the truth; and the re-evaluated bootstraps *did* reach TCP
   twice (same token, same id, harmless), so "menu contexts always die" is a tendency, not a law.
   (**Both symptoms closed in 0.4.13, without touching the fact underneath:** the box is now
   answered through the shared controller, so a menu click reports the owning runtime instead of
   its own empty copy, and it no longer arms a connection of its own — the observation that the
   editor re-evaluates the bundle per menu click is exactly what the shared runtime exists for.
   See §13 for the box's current shape.)
5. What `Origin` / `User-Agent` the editor's socket actually sends — **this is task 004c's
   outstanding deliverable**, and the reason `check_origin` still returns `true`. The two samples
   (one editor connection, one deliberate browser connection) belong in the run report; until
   they exist, no rule is written.

## 13. Manual verification checklist

Requirements: EasyEDA Pro (engine `~3.2.0`), Node 22+, Python 3.10+ with `websockets`.

**A. Build the connector**

```bash
cd connector
npm install
npm run build      # dist/index.js (IIFE, global edaEsbuildExportName) + dist/esm/*.mjs
npm run package    # -> connector/boardwise-connector-0.4.10.eext (~40 kB)
npm test           # 279 tests, ~2 s
npm run typecheck  # tsc --noEmit
```

`dist/index.js` is the artifact the editor loads; the `edaEsbuildExportName` global is what the
official scaffolding expects. `dist/esm/` is built only so the tests can import the real modules
without an editor, and is deliberately **not** in the `.eext`.

**B. Sideload the extension**

1. EasyEDA Pro → extension manager → install from a local `.eext`, or point it at the
   `connector/` folder (manifest: `extension.json`, uuid `a08393abee5cbeb92f33e6cf2bf4b6a0`,
   entry `./dist/index`).
   The layout is not a guess: the working reference (`easyeda-agent-connector.eext`, which
   installs in the same editor) is a ZIP whose root holds `extension.json`, with the bundle at
   `dist/index.js`, and whose manifest uses the same field spellings we do — `entry: "./dist/index"`,
   `engines.eda: "~3.2.0"`, `activationEvents.onStartupFinished`, `headerMenus`. Our archive
   carries exactly the two entries that matter (`extension.json`, `dist/index.js`) and is verified
   to be a well-formed ZIP matching the current build (`connector/tests/package.test.mjs`). If a
   future editor build rejects it, install from the folder instead — the archive carries nothing
   the folder does not.
2. **Grant the extension "external interaction" permission.** Every `eda.*` call throws until
   this is granted; without it the connector registers nothing and the daemon sees no connector
   at all. This is the single most common setup failure.

**C. Start the daemon**

```bash
boardwise bridge start
# boardwise bridge: listening on 127.0.0.1:61190
#   token file: C:\Users\<you>\.boardwise\token           <- the CLI's secret
#   audit log:  C:\Users\<you>\.boardwise\audit
#   pairing:    C:\Users\<you>\.boardwise\connector-token <- written on first connector connect
#   waiting for the EasyEDA extension to connect (Ctrl-C to stop)
```

**D. Let the connector pair itself** (once)

There is nothing to paste. On its first connection the connector presents a token it generated
for itself, and the daemon — which has no paired connector yet — accepts it and remembers it
(§3.4). The daemon prints a line naming the fingerprint:

```
boardwise bridge: paired new connector (fingerprint 3f9a1c7e); if this was not you, run: boardwise bridge revoke
```

`About…` should then read `state: connected` and show the same fingerprint. It also says **where
the token came from** — `storage`, or `Math.random — NOT a CSPRNG` if Web Crypto was unusable
(§9). The token value itself never appears in the log panel, the audit log or `status` — only the
8-hex fingerprint does.

**Read the box top to bottom**; each line localises a failure one step further along:

```text
boardwise connector 0.4.13
activation: 21:04:36 ok            <- did the editor call us, and how did that go
lifecycle: moduleBootstrapObserved=yes activateObserved=yes evaluations=3
bootstrap: the bundle was evaluated 3× in this editor runtime; activate() was dispatched at 21:04:36
loaded: 21:04:29                   <- when the evaluation that owns this box was loaded
state: connected
storage: readable (token=webcrypto, 64 characters)
url: ws://127.0.0.1:61190/eda
token: storage, 64 characters (never displayed)
pairing: paired with the daemon (fingerprint 3f9a1c7e)
connector version: ok (the daemon accepts >= 0.4.10)
auto-connect: on
```

The two 024 lines answer the question the rest of the box cannot: `lifecycle:` reports
the module-scope bootstrap and the activation callback as counters (plus how many times the
editor has evaluated this bundle), and `bootstrap:` says the same thing in one sentence — the
pair separates "the host never loaded us" from "it loaded us and never called `activate()`".
Since 0.4.13 the box is answered through the controller that **owns** the connection, so these
are the owning evaluation's numbers and `loaded:` stays put across menu clicks, even though the
editor re-evaluates the bundle on every click (§12:4). Every time in the box is your local
clock; before 0.4.13 all of them were UTC, which reads eight hours early in Beijing.
**`connector version:` appears only when the daemon stated a minimum** (018 §B3) — with no
minimum there is no verdict to print.

**Read `activation:` first** — it is the line that resolves the oldest confusion:

| `activation:` | Meaning |
|---|---|
| `NEVER RAN — self-connected at <time>` | The editor never called `activate()`, and the self-arm (§10.20) connected anyway. The extension works; the editor's activation event did not fire. Expected after reloading the extension without restarting the editor |
| `NEVER RAN — …` | The editor never called `activate()` and nothing armed either. The `self-arm:` line at the bottom of the box says what the deferred probes found. Menus still work, which is what makes this look like a healthy extension. **Open `About…` once — that connects — and do a full editor restart for the clean state** |
| `NEVER RAN — self-arm FAILED at <time>: <error>` | Both paths failed. The cause is in this line *and* in the log panel |
| `<time> FAILED — <error>` | Activation ran and threw. The cause is in this line *and* in the log panel. This is the case that used to be completely invisible |
| `<time> ok` / `<time> running` | Activation happened; whatever is wrong is further down (log panel, `storage:`, `token:`) |

`loaded:` is when the evaluation that **owns this box** was loaded — the controller holding the
connection, since 0.4.13 the box is answered through it even when a menu click re-evaluated the
bundle, so this line stays put across clicks in one editor session. A *newer* value means the
runtime was rebuilt (a new editor session, a re-import, or a record this build could not reuse),
which is worth ruling out before anything else is blamed. Every time in the box — here and in
`activation:`/`bootstrap:`/`self-arm:` — is the reader's **local** clock; before 0.4.13 it was UTC,
which read eight hours early in Beijing (a correct `loaded: 11:50:21` beside a daemon log at
19:50:21 was the round trip that fixed it).

Then `storage:` and `token:`. `storage: readable (token=unset)` means nothing is stored;
`(token=webcrypto, 64 characters)` means a token is there, with the provenance it was created with
— a *summary*, never the value. `token: NONE — this editor cannot generate one (crypto=…)` means
nothing produced random bytes *and* nothing was stored; the parenthetical is the live diagnosis of
the realm. `storage: read FAILED — …` means `eda.sys_Storage` rejected the read, which makes every
token question moot — that is the failure the type declarations warn about for non-extension
contexts. **The two lines must always agree** — 0.2.3 could show `token: NONE` beside a stored
token, because the two lines read the store through different paths (§10.21); if you ever see
that shape again on ≥ 0.2.4, it is a new bug and worth a report.

**Opening `About…` arms the connection.** If activation never ran and the deferred probes found
nothing, the menu click itself connects — menus are the one entry point measured to work without
activation. The box you are looking at is the honest pre-arm snapshot; open it a second time to
see the live state. The `self-arm:` line at the bottom records what the deferred probes tried
(`+1s: editor global not reachable`, …), so "probes ran and missed" is distinguishable from
"nothing ran" — the distinction 0.2.3 could not make (§10.20).

If it reads `token: NONE … (crypto=unavailable)`, run `tools/probe3-crypto.js` in the editor's
script console and report what it returns.
To forget the pairing (e.g. before hand-off, or to lock an intruder out), run
`boardwise bridge revoke`; the next connector to connect is trusted afresh. The editor-side
equivalent is **boardwise → Re-pair on next connect**, which drops the connector's own stored
token and offers a new one on the next connection — do both when you want a clean slate.

**Check the editor log panel here.** The extension writes `[boardwise] …` lines to the editor's
own log panel (`eda.sys_Log`) as well as to the devtools console. They name the URL it dials,
where the token came from, and the reason for every reconnect — so a failure is diagnosable
from inside the editor, without opening devtools.

Read the lines in order; each one localises the failure further along the chain than the last:

| Line | What it proves |
|---|---|
| `connect: url=… token=storage autoConnect=…` | the module evaluated and resolved its config — since 0.2.5 this is the bootstrap's line, not `activate()`'s (it names the token *source*, never the token value) |
| `activate FAILED: <error>` | activation ran and threw — the reason the state never leaves `idle`. Nothing logged this before 0.2.2, which is why a failure here used to be invisible |
| `generated a token with Math.random — crypto=unavailable` | the first run on this host: there was no usable Web Crypto, so the fallback produced the token (§9). A remark, not an error |
| `register boardwise-1 -> ws://127.0.0.1:61190/eda` | the socket facade **was** reachable and `register` ran |
| `sent hello (triggered by daemon banner)` | a frame came back from the daemon — the socket is up end to end |
| `paired with the daemon, fingerprint 3f9a1c7e` | the daemon accepted the token and reports the fingerprint both sides now agree on |
| state becomes `connected` | the transport is live and ready for actions |

If the panel is empty, the extension never reached `activate()` — check the permission in B.2.
If it stops after `activate`, the facade was not reachable: see the `is unavailable` row in F.

Because the daemon speaks first, `sent hello (triggered by …)` should name `daemon banner`. If it
instead says `onConnected`, the editor's connect callback fired this time — also fine, but the
banner path is the one to trust.

**E. Verify end to end**

```bash
boardwise bridge status
# boardwise bridge: daemon up on 127.0.0.1:61190
#   connector: connected            <- exit 0; "not connected" exits 1
#   windows: 1 connected            <- 023: one block per online editor window
#   window: inst-… (connector 0.4.10)  [project /test (uuid-…)]
#     peer: 127.0.0.1:54048  connected: 2026-09-23 17:10:02  last seen: …  routed: 4
#     page: sch page-…
#   projects seen: /test (inst-…)
#   paired connector: 3f9a1c7e      <- the fingerprint the connector's About box should match

boardwise bridge revoke           # forget the pairing; the next connector pairs afresh

boardwise bridge screenshot shot.png --fit     # -> wrote shot.png
boardwise bridge highlight <uuid> --color "#FF0000"   # marker appears on the canvas
boardwise bridge highlight --clear                    # markers removed
```

Open the PNG and confirm it shows the board you have open — that is the proof the whole chain
(dial-out socket, handshake, routing, `eda.*`) works.

**E2. Verify with three or four windows open (023)**

Open EasyEDA on three different projects (each window connects independently — check
`bridge status` lists three `window:` blocks with three different projects), then:

```bash
boardwise bridge call --action doc.list --project test2        # exit 0, and the answer is test2's
boardwise bridge call --action doc.list --project <uuid>       # the same window, by uuid
boardwise bridge call --action doc.list --instance <windowKey> # the same thing by instance id
boardwise bridge call --action doc.list                        # exit 1, WINDOW_UNSPECIFIED,
                                                               # listing all three windows
boardwise bridge call --action doc.list --project no-such-one  # exit 1, PROJECT_NOT_CONNECTED,
                                                               # listing all three windows
boardwise bridge call --action doc.list --instance no-such-id  # exit 1, WINDOW_NOT_CONNECTED,
                                                               # listing all three windows
boardwise bridge call --action sys.identity --project 反激辅助电源  # read-only, must name that project
```

Then switch the focused project inside one window and repeat `--project` for the **new** project: it
must route there without the window reconnecting (the context rides every response). For a write,
use `test` / `test2` only, and confirm the other windows' projects are untouched afterwards.

**E3. The restarted-editor case the instance hint exists for (023 follow-up)**

Restart EasyEDA with several projects open, then *immediately* run `bridge status`: the windows are
connected, but each may read as `[no project]` while the editor API is still coming up — the `hello`
arrives long before any project read can. In that state:

```bash
boardwise bridge call --action doc.list --project test2        # exit 1, PROJECT_NOT_CONNECTED —
                                                              # nothing to match against yet
boardwise bridge call --action doc.list --instance <windowKey> # exit 0: the instance id was in the
                                                              # hello, so it always routes
boardwise bridge update-connector --instance <windowKey> --yes # hot-update THAT window and read its
                                                              # version back from the hub
```

Then wait for the editor to finish loading and repeat `--project` for the same window: it routes
now, because the first response refreshed the context.

**F. When it does not work**

| Symptom | Look at |
|---|---|
| `status` says daemon not reachable, exit 2 | Is `bridge start` still running? Wrong `--port` / `BOARDWISE_PORT`? |
| `status` says connector not connected, exit 1 | Extension enabled? **External interaction granted?** → `About…` |
| Editor log panel shows no `[boardwise]` lines at all | Nothing ran — the extension is not enabled, or the permission in B.2 is missing. Note that with the self-arm (§10.20) the panel is written to even when `activate()` never fires, so "no lines at all" now means the bundle was never evaluated |
| `About…` says `NEVER RAN — self-connected at …` | Working as designed: the editor did not call `activate()`, and the self-arm covered it (§10.20). Nothing to fix, but it means the editor's activation event is not firing — a full restart is the clean state |
| `About…` says `NEVER RAN — self-arm FAILED at …` | Both lanes failed and the error is on the line; the log panel carries the same message |
| `About…` says `storage: readable (token=legacy format, …)` | A token written by 0.2.0–0.2.2, before provenance was recorded. Expected after the upgrade; it becomes `webcrypto`/`math` after the next re-pair (**Re-pair on next connect**) |
| `About…` says `storage: readable (token=unset)` and the token question never resolves | Nothing is stored, and the log panel says why (`refused to store`, or `storing the token threw`). The 0.2.3 shape — `token: NONE` beside a *stored* token — was a bug in the box, not the store (§10.21); on ≥ 0.2.4 the two lines cannot disagree |
| `About…` shows a `self-arm:` line with probe notes | The deferred probes ran and what each found is on the line (`+1s: editor global not reachable`, …). This is the answer 0.2.3 could not give: if the probes never left a note and nothing connected, the bundle was never evaluated; if they missed, the editor global was not bound when they fired — and opening `About…` connects anyway |
| `About…` says `token: NONE — this editor cannot generate one (…)` and the state never leaves `idle` | **Read `activation:` first.** If it says `NEVER RAN`, the editor never called `activate()`: do a full editor restart (menus keep working without activation, which is what makes this look healthy). If it says `FAILED — …`, the cause is right there. Only if it says `ok` does the parenthetical matter: nothing produced random bytes, so nothing was dialled — run `tools/probe3-crypto.js` and report what it returns |
| `About…` says `activation: <time> FAILED` | Activation threw and the log panel carries the same error. Before 0.2.2 this was silently swallowed |
| `About…` says `storage: read FAILED — …` | `eda.sys_Storage` rejected a read. The type declarations warn these methods throw outside a real extension context; every token question is downstream of this |
| `About…` says `Math.random — NOT a CSPRNG` | Working as designed: Web Crypto was unavailable and the fallback covered it (§9). Nothing to fix here — but the source is shown so you can decide |
| `About…` shows `handshaking` | The daemon refused the hello — the presented token does not match the paired one. `boardwise bridge revoke`, then reconnect |
| The connector loops `UNAUTHENTICATED` and nothing changed | A **stale daemon** is on the port: a long-running `bridge start` keeps the code it imported, so editing `src/` does not change what it enforces. A 0.2.0 daemon writes `origin` on every `connect` audit line — if today's `connect` lines have none, that daemon predates pairing and is still demanding the CLI token. Stop it, run `boardwise bridge start` again |
| `About…` fingerprint differs from `boardwise bridge status` | Something else paired first (or a stale pairing): `revoke` and reconnect, and check the audit log's `pairing` line |
| `About…` shows `connecting`, log names the URL | Daemon not listening on that port, or the URL was edited to a wrong path |
| Log repeats `eda.sys_WebSocket is unavailable` and never shows `register …` | The extension host never handed us the socket facade — this is §3.2 (a). Check that the code resolves the API from the extension's own scope (bare `eda`), **not** `globalThis.eda` |
| Log shows `register boardwise-N -> …` but no `sent hello` | `register` ran but nothing came back: the editor did not open the socket (permission, or the URL path) |
| Action returns `NO_CONNECTOR` | EasyEDA closed, or the extension stopped (menu → Reconnect) |
| Action returns `TIMEOUT` | Modal dialog / long render, or a half-open socket (§10) — try `screenshot` |
| Everything connects but reads look empty | Is the right document focused? `document.current` shows what the editor reports — `active: null` plus a note naming the host's uuid `"0"` means no document is focused (multi-window), so click the tab you meant and retry |
