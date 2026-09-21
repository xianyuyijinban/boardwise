"""Wire protocol for the boardwise bridge (daemon <-> connector / CLI).

One WebSocket server speaks to two kinds of client, distinguished at
handshake by ``params.role``:

- ``connector`` — the TypeScript extension running inside EasyEDA Pro. It owns
  the ``eda.*`` API, so every *editor* action is forwarded to it. At most one
  connector is tracked at a time.
- ``cli``       — short-lived command line calls. They ask the daemon to
  forward an action and wait for the answer.

Framing is one JSON object per WebSocket text message. Nothing here touches
the network — this module only defines, builds and validates frames, which
keeps the contract testable without a socket.

There are three kinds of frame, told apart by which key is present:

======================  ==========================  =========================
kind                    key                         meaning
======================  ==========================  =========================
request                 ``action``                  asks for something
response                ``ok``                      answers a request
event                   ``event``                   unsolicited notification
======================  ==========================  =========================

``ok`` wins over ``event`` wins over ``action`` when reading, so a frame is
classified by the strongest key it carries.

Envelope (request)::

    {"id": "…", "action": "pcb.readback", "params": {…}}

Envelope (response)::

    {"id": "…", "ok": true,  "data": {…}}
    {"id": "…", "ok": false, "error": {"code": "…", "message": "…"}}

Envelope (event) — no ``id``, because nothing correlates with it::

    {"event": "banner", "data": {…}}

The shape is deliberately close to the ``easyeda-agent`` frames reconnoitred
in 2026-08 (see ``docs/bridge.md``), so behaviour learned on that connector
transfers: ``id`` correlates, ``ok`` decides, ``error.code`` is machine
readable. Three differences: we put results in ``data`` instead of
``result``/``context``/``artifacts``, every action is explicitly declared in
:data:`ACTIONS` rather than discovered at runtime, and the liveness signal
travels *daemon to connector* as an event (:func:`banner_frame`) instead of
being inferred from a connect callback the editor does not reliably call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

__all__ = [
    "PROTOCOL_VERSION",
    "ROLE_CONNECTOR",
    "ROLE_CLI",
    "ROLES",
    "EVENT_BANNER",
    "Action",
    "ACTIONS",
    "ACTION_NAMES",
    "HELLO_TIMEOUT",
    "BridgeError",
    "ErrorCodes",
    "new_id",
    "banner_frame",
    "request_frame",
    "response_frame",
    "error_frame",
    "decode_frame",
    "frame_kind",
    "describe_actions",
]

#: Bumped whenever the envelope or an action's params/result contract changes.
#: A connector whose ``hello`` reports a different major version is rejected
#: with ``ErrorCodes.VERSION_MISMATCH`` rather than silently mis-speaking.
PROTOCOL_VERSION = "1.0"

ROLE_CONNECTOR = "connector"
ROLE_CLI = "cli"
ROLES: tuple[str, ...] = (ROLE_CONNECTOR, ROLE_CLI)

#: Seconds a fresh connection has to present a valid ``hello`` before the
#: daemon hangs up.
#:
#: Five seconds, not ten: the daemon speaks first (:func:`banner_frame`), so
#: silence is unambiguous — either the client never opened a socket, or it got
#: the banner and failed to answer. Nothing is gained by waiting longer, and a
#: short hang-up keeps the audit log honest instead of full of dead sockets.
#:
#: Reference point: the ``easyeda-agent`` daemon allows 1.5 s. We are more
#: generous only because a freshly started editor can be busy loading a board.
HELLO_TIMEOUT = 5.0

#: Seconds the daemon waits for the connector to answer a forwarded action.
ACTION_TIMEOUT = 30.0

#: Seconds the daemon waits for a screenshot: the editor renders the canvas
#: before replying, which is slower than a plain readback.
SCREENSHOT_TIMEOUT = 60.0

#: Seconds the daemon waits for a component placement. The editor resolves the
#: library on the *first* placement of a session, which on the measured host
#: outran the old 30 s default — and the placement landed anyway. The daemon
#: budget has to sit above the connector's own 30 s deadline so the connector's
#: readback ("did it land?") is what answers, not a daemon-side hang-up.
PLACEMENT_TIMEOUT = 60.0

#: Seconds the daemon waits for a primitive delete batch. Measured 2026-09-21
#: (012): the editor re-solves the page per primitive at ~3.7 s each, so a
#: 17-part cleanup needs ~63 s and blew through the 30 s default mid-batch.
#: 150 s covers ~40 primitives — the largest single cleanup worth doing in
#: one call; beyond that the caller should split on purpose, not by accident.
DELETE_TIMEOUT = 150.0

#: Seconds the daemon waits for a fab bundle. Three manufacture exports run in
#: one call (Gerber / pick-and-place / BOM) and each can take tens of seconds on
#: a real board, so the connector bounds **each file** at 60 s and this budget
#: sits above 3 of those deadlines: a connector that hangs on one file still
#: answers, per-file, inside the daemon's patience.
FAB_TIMEOUT = 240.0

#: Seconds the daemon waits for a part recommendation. Up to 3 rungs × 3 pages
#: of library search, each of which is a round trip to the editor's own library
#: backend — 30 s is the default for *one* read and this is up to nine.
RECOMMEND_TIMEOUT = 90.0

#: Name of the event the daemon sends the instant a socket opens.
EVENT_BANNER = "banner"


@dataclass(frozen=True)
class Action:
    """One entry of the typed action catalogue."""

    name: str
    summary: str
    #: What the call can do to the project — the field a reviewer reads before
    #: letting anything run unattended. No default: every entry must state it,
    #: because a forgotten risk is a silently ungated action.
    #:
    #: * ``read`` — cannot change project content. Reads, probes, exports, and
    #:   view-only annotations (``canvas.highlight``) live here; so does
    #:   ``doc.open``, which changes the editor's active document but not a
    #:   single byte of what the project contains.
    #: * ``write`` — changes existing content in place (place, wire, attribute
    #:   writes, rename, save).
    #: * ``create`` — produces a **new document**. The daemon refuses these
    #:   unless ``params.confirm is True`` (``CONFIRMATION_REQUIRED``).
    risk: str
    #: Who may originate this action. ``connector`` actions are executed by
    #: the extension; ``daemon`` actions are answered by the daemon itself.
    owner: str = "connector"
    params: tuple[str, ...] = ()
    #: Docs only — what a successful ``data`` payload looks like.
    returns: str = ""
    params_schema: str = ""


#: Every action the bridge knows about. ``--help`` renders this table, and the
#: daemon refuses anything not listed (``ErrorCodes.UNKNOWN_ACTION``) instead
#: of forwarding an open-ended string into the editor.
ACTIONS: tuple[Action, ...] = (
    Action(
        name="hello",
        summary="Handshake. Must be the first frame on every connection.",
        owner="daemon",
        params=("token", "role", "protocol", "client"),
        returns="{ok: true, data: {role, protocol, serverTime}}",
        risk="read",
    ),
    Action(
        name="ping",
        summary="Liveness check; answered by the daemon, not forwarded.",
        owner="daemon",
        returns="{ok: true, data: {pong: true, connector: bool}}",
        risk="read",
    ),
    Action(
        name="document.current",
        summary="Which project / document / document type is open in the editor.",
        params=(),
        returns="{project: {…}, document: {…}, type: 'sch'|'pcb'|…}",
        risk="read",
    ),
    Action(
        name="sys.probe",
        summary=(
            "READ-ONLY introspection of the editor's live API surface: the "
            "editor version, the namespaces bound on `eda`, and what each "
            "requested namespace actually exposes. Exists because the type "
            "package declaring a method and the running editor exposing it "
            "are different statements. Two modes: `checks` verifies named "
            "members with a plain `typeof ns[name]` read (immune to the "
            "exotic host objects that abort enumeration), and enumeration "
            "finds members nobody predicted."
        ),
        params=("checks", "namespace", "namespaces", "functionsOnly"),
        returns=(
            "checks mode: {version, topLevel, checks: {NAME: {present, kind, "
            "checked, missing, status: {member: 'function'|'object'|"
            "'undefined'|'threw: …'|'namespace-absent'}, arity: {member: "
            "fn.length for the members that are functions}, notes?}}}; "
            "enumerate mode: {version, topLevel, namespaces: {NAME: {present, "
            "functions, data, errors?}}}"
        ),
        risk="read",
    ),
    Action(
        name="sys.self_update",
        summary=(
            "Replace this connector's bundle in the editor's extension "
            "IndexedDB (User_<teamUuid>_v6, store names are EasyEDA-internal) "
            "and reload the page, so a new build takes effect WITHOUT "
            "uninstall/import/restart. The response is sent before the reload "
            "fires. Only `config.version` and `fileSize` are touched in the "
            "index record — the external-interaction grant is preserved. Every "
            "step validates; any failure is an explicit error (fall back to a "
            "manual reinstall), never a silent degrade."
        ),
        params=("bundleB64", "version"),
        returns="{ok, oldVersion, newVersion, bytes, database, reloadInMs}",
        params_schema=(
            "bundleB64: the new dist/index.js, base64-encoded (required); "
            "version: the new version string to store (required)"
        ),
        risk="write",
    ),
    Action(
        name="sch.readback",
        summary="Schematic components and a primitive subset, for a netlist view.",
        params=("includePrimitives",),
        returns="{components: [...], primitives: [...]}",
        risk="read",
    ),
    Action(
        name="pcb.readback",
        summary="PCB components and a primitive subset (pads / tracks / vias).",
        params=("includePrimitives",),
        returns="{components: [...], primitives: [...]}",
        risk="read",
    ),
    Action(
        name="export.screenshot",
        summary="Native editor image export of the current canvas, as base64 PNG.",
        params=("fit",),
        returns="{format: 'png', encoding: 'base64', data: '…'}",
        risk="read",
    ),
    Action(
        name="export.render",
        summary=(
            "Render the *document* to an image file (base64) via "
            "sch_ManufactureData.getExportDocumentFile — the acceptance image. "
            "A viewport capture (export.screenshot) can return cached frames on "
            "this host, so it is never evidence. Scope can be the current page, "
            "a selection of primitives, or the whole project; a multi-page "
            "project may come back as a zip and the `format` field says which."
        ),
        params=("format", "scope", "ids", "fileName"),
        returns=(
            "{format: 'image/png'|'image/svg+xml'|'application/pdf'|'zip', "
            "encoding: 'base64', bytes, data, scope, note}"
        ),
        params_schema=(
            "format: png|svg|pdf (default png); scope: page|selection|project "
            "(default page); ids: primitive ids, required when scope=selection; "
            "fileName: optional, default render.<ext>"
        ),
        risk="read",
    ),
    Action(
        name="canvas.highlight",
        summary="Mark primitives on the live canvas by uuid (review annotations).",
        params=("uuids", "color", "clear", "zoom"),
        returns="{highlighted: n, cleared: bool}",
        risk="read",
    ),
    # --- 006: schematic candidate-model reads -------------------------------
    Action(
        name="sch.component_pins",
        summary=(
            "Recon (read-only): the placed pins of one component, with geometry. "
            "The seventh path to a pin the six-path table had missed — "
            "sch_PrimitiveComponent.getAllPinsByPrimitiveId returns "
            "器件引脚图元 (x/y/pinNumber/pinName/rotation/pinLength) for a PLACED "
            "component, @beta with no ADD-since-v4 marker. Decides whether F3 "
            "(drifted-part endpoint snapping) is implementable."
        ),
        params=("primitiveId",),
        returns="{primitiveId, returned, pins, note?, readErrors?}",
        params_schema="primitiveId: the placed component's primitive id (required)",
        risk="read",
    ),
    Action(
        name="lib.device.get",
        summary=(
            "Recon (read-only): one library device, dumped whole. Its "
            "association.symbol is the *library* symbol uuid that lib.symbol.get "
            "needs — the netlist's Symbol property is project-local and answers "
            "found:false there."
        ),
        params=("uuid", "libraryUuid"),
        returns="{uuid, libraryUuid, found, item, readErrors?}",
        params_schema="uuid: library device uuid (required); libraryUuid: optional",
        risk="read",
    ),
    Action(
        name="lib.device.search",
        summary=(
            "Read-only: library device keyword candidates, each dumped. A search "
            "item carries association.footprint.uuid, so pairing it with "
            "lib.footprint.get answers 'which hit is really 0402?' by measurement."
        ),
        params=("keyword", "limit"),
        returns="{keyword, returned, shown, items}",
        params_schema="keyword: search text; limit: max items to dump (default 8)",
        risk="read",
    ),
    Action(
        name="lib.footprint.get",
        summary=(
            "Read-only: one library footprint, dumped whole. Turns the netlist's "
            "footprint uuid back into the package name both sides can compare, "
            "and verifies a replacement part really is the package it claims."
        ),
        params=("uuid", "libraryUuid"),
        returns="{uuid, libraryUuid, found, name, item}",
        params_schema="uuid: library footprint uuid (required); libraryUuid: optional",
        risk="read",
    ),
    Action(
        name="sch.set_component_attribute",
        summary=(
            "Write schematic attributes on a placed component in ONE call, then "
            "read them back. modify()'s otherProperty REPLACES the whole map "
            "(measured: writing Value then Supplier Footprint kept only the "
            "second), so callers send attributes{} and the action merges first. "
            "`applied` means the read-back equals the target, never 'modify "
            "returned an object'."
        ),
        params=("primitiveId", "attributes", "key", "value", "pageUuid"),
        returns=(
            "{primitiveId, attributes, mergedKeys, applied, wrote, "
            "otherPropertyBefore, otherPropertyAfter, mismatched?, "
            "clobberedOtherKeys?, readBackBefore?, readBackAfter?}"
        ),
        params_schema=(
            "primitiveId: placed component id; attributes: {name: value} written "
            "in one call (preferred); key/value: single-pair shorthand; pageUuid"
        ),
        risk="write",
    ),
    Action(
        name="lib.symbol.get",
        summary=(
            "Recon (read-only): one library symbol, dumped whole. Answers whether "
            "the *library* path exposes pin geometry — the canvas path is measured "
            "dead (sch_PrimitivePin.getAll() empty, Symbol state {}, netlist has no "
            "coordinates), but nobody had looked here."
        ),
        params=("uuid", "libraryUuid"),
        returns="{uuid, libraryUuid, found, item, readErrors?}",
        params_schema="uuid: library symbol uuid (required); libraryUuid: optional",
        risk="read",
    ),
    Action(
        name="sch.netlist",
        summary=(
            "The editor's own netlist export (sch_ManufactureData.getNetlistFile) "
            "— the ground-truth connectivity for draw verification."
        ),
        params=("type",),
        returns="{type, source, size, text}",
        params_schema="type: ESYS_NetlistType value ('EasyEDA' | 'Protel2' | 'JLCEDA' | 'PADS' | …), default 'EasyEDA'",
        risk="read",
    ),
    Action(
        name="sch.geometry",
        summary=(
            "Full geometry of the open schematic page (wires with polylines, "
            "pins, net labels, components) — the readback fallback when the "
            "netlist export is unusable."
        ),
        params=("bboxIds",),
        returns=(
            "{components: [...], wires: [...], pins: [...], netlabels: [...], "
            "bboxes: {primitiveId: {minX,minY,maxX,maxY}}, meta: {...}}"
        ),
        params_schema="bboxIds: optional array of primitive ids to measure as well",
        risk="read",
    ),
    # --- 006: schematic write actions ---------------------------------------
    Action(
        name="sch.doc.new",
        summary="Create a blank schematic page in the current project.",
        params=("name", "confirm"),
        returns="{schematicUuid, pageUuid, focused}",
        risk="create",
    ),
    Action(
        name="sch.doc.save",
        summary=(
            "Save the project — required before the netlist export, which "
            "returns nothing for a never-saved project (measured)."
        ),
        params=(),
        returns="{saved: true}",
        risk="write",
    ),
    Action(
        name="sch.place_component",
        summary=(
            "Place a library device (resolved by LCSC part number, library "
            "uuid pair, or keyword search) on the current schematic page. "
            "Timeout-bounded and self-reporting: the first placement of a "
            "session can outrun its deadline and land anyway, so a miss reads "
            "the page back and says whether a part appeared."
        ),
        params=(
            "lcsc", "deviceUuid", "libraryUuid", "keyword", "x", "y",
            "rotation", "mirror", "designator", "pageUuid", "timeoutMs",
        ),
        returns="{uuid, device: {uuid, libraryUuid, name}, resolvedBy, elapsedMs}",
        params_schema="timeoutMs: override the 30 s placement deadline (200..60000, clamped)",
        risk="write",
    ),
    Action(
        name="sch.place_wire",
        summary="Place a wire polyline, optionally naming its net.",
        params=("points", "net"),
        returns="{uuid}",
        params_schema="points: [[x, y], …] (2+ points); net: optional net name carried by the wire",
        risk="write",
    ),
    Action(
        name="sch.place_netlabel",
        summary=(
            "Place a net label. Timeout-bounded and self-reporting: the call "
            "races an 8 s deadline and, when the host hangs (measured on "
            "3.2.186, reference issue #191), reads back whether the label "
            "landed anyway before failing — never retry blind."
        ),
        params=("x", "y", "net", "pageUuid", "timeoutMs"),
        returns="{uuid, outcome: 'ok', elapsedMs, landedAnyway}",
        params_schema=(
            "pageUuid: refuse to write unless the focused page matches; "
            "timeoutMs: override the 8 s deadline (200..30000, clamped)"
        ),
        risk="write",
    ),
    Action(
        name="sch.place_text",
        summary=(
            "Place a free text primitive next to a wire — the *decorative* "
            "signal-name fallback. `createNetLabel` (the only real net-label "
            "API) is documented 'ADD since EDA v4' and can never settle on the "
            "v3.2 host, so a signal name is drawn as text: visible to a reader, "
            "but NOT an electrical object. The response says `decorative: true`."
        ),
        params=("x", "y", "content", "rotation", "color", "fontSize", "pageUuid"),
        returns="{uuid, content, decorative: true}",
        risk="write",
    ),
    Action(
        name="sch.place_power",
        summary=(
            "Place a power / ground net flag (a real library component placed "
            "by the editor, named with the given net)."
        ),
        params=("kind", "net", "x", "y", "rotation", "mirror"),
        returns="{uuid}",
        params_schema="kind: 'Power' | 'Ground' | 'AnalogGround' | 'ProtectGround'",
        risk="write",
    ),
    Action(
        name="sch.place_netport",
        summary=(
            "Place a net port (IN / OUT / BI) carrying a net name. The solver's "
            "LAST resort only: 岳翔宇's rule bans I/O ports for signal naming — "
            "the draw flow names signals with label actions and never emits one."
        ),
        params=("direction", "net", "x", "y", "rotation", "mirror"),
        returns="{uuid}",
        params_schema="direction: 'IN' | 'OUT' | 'BI'",
        risk="write",
    ),
    # --- 012: delete / move / rotate by id (the AI's basic edit verbs) -------
    Action(
        name="sch.delete_primitives",
        summary=(
            "Delete schematic primitives by id. The page's id index is built "
            "first (component / wire / text / pin — the classes the type "
            "package lets address by id; attribute primitives cannot be), so "
            "an id the page never held is reported, not guessed at. Honest "
            "partial result: deleted / notFound / failed."
        ),
        params=("pageUuid", "primitiveIds"),
        returns="{deleted: [id], notFound: [id], failed: [{id, reason}]}",
        params_schema="pageUuid: the guarded page; primitiveIds: list of primitive ids",
        risk="write",
    ),
    Action(
        name="pcb.delete_primitives",
        summary=(
            "Delete PCB primitives by id — component / line / via / pad / "
            "pour, guarded against the focused PCB. Honest partial result, "
            "same shape as sch.delete_primitives."
        ),
        params=("pageUuid", "primitiveIds"),
        returns="{deleted: [id], notFound: [id], failed: [{id, reason}]}",
        params_schema="pageUuid: the guarded PCB uuid; primitiveIds: list of primitive ids",
        risk="write",
    ),
    Action(
        name="sch.modify_primitive",
        summary=(
            "Move / rotate / mirror one schematic primitive by id — pose only. "
            "The class comes from the page's id index; the pose keys are "
            "filtered through what that class's modify actually accepts "
            "(a wire has no pose in the type package and is refused). "
            "Returns the before/after pose for verification."
        ),
        params=("pageUuid", "primitiveId", "x", "y", "rotation", "mirror"),
        returns="{before: {x, y, rotation, mirror}, after: {…}}",
        params_schema="at least one of x / y / rotation / mirror",
        risk="write",
    ),
    Action(
        name="pcb.modify_primitive",
        summary=(
            "Move / rotate one PCB primitive by id — pose only, same contract "
            "as sch.modify_primitive against the focused PCB."
        ),
        params=("pageUuid", "primitiveId", "x", "y", "rotation", "mirror"),
        returns="{before: {x, y, rotation, mirror}, after: {…}}",
        params_schema="at least one of x / y / rotation / mirror",
        risk="write",
    ),
    # --- 012 §五: multi-project awareness ------------------------------------
    Action(
        name="doc.focus",
        summary=(
            "Put an already-open document on top: resolve a tab id from a "
            "page uuid (or take a full tabId) in the split-screen tree and "
            "activate it. Refuses (NOT_FOUND) when nothing is open for that "
            "uuid — doc.open is the one that opens tabs."
        ),
        params=("pageUuid", "tabId"),
        returns="{activated, tabId, title, documentType}",
        params_schema="pageUuid or tabId, one required",
        risk="write",
    ),
    Action(
        name="doc.delete_page",
        summary=(
            "Delete a schematic page by uuid — the cleanup half of the "
            "scratch-page flow. The uuid must be one the project lists "
            "(NOT_FOUND otherwise); the host refuses to delete a schematic's "
            "last page."
        ),
        params=("pageUuid",),
        returns="{deleted, pageUuid, name}",
        params_schema="pageUuid: the page to delete",
        risk="write",
    ),
    # --- 012 §六/§七: the fab bundle and part recommendations ----------------
    Action(
        name="export.fab",
        summary=(
            "The focused PCB's fab bundle in one call (012 §六): Gerber (zip) + "
            "pick-and-place + BOM, plus a manifest carrying the file list, the "
            "parameters used, the project/pcb identity and the timestamp. The "
            "connector CANNOT write to a path — no declared API takes a directory "
            "(SYS_FileSystem.saveFile(fileData, fileName?) has none) — so the three "
            "files come back as base64 and the caller writes them into `outDir`; "
            "`boardwise bridge export-fab` is that caller. Vendor presets: `generic` "
            "only, until a 捷配 sample BOM arrives. A file the host refuses, returns "
            "empty or hangs on is reported per file in `failed` (`partial: true`) "
            "while the others still come back. Measured on 3.2.186 (2026-09-21): the "
            "15 BOM column names come back verbatim — the two counting columns reach "
            "the host as `statistics` and the other 13 as `property`, two disjoint "
            "lists whose union it checks per column, because naming a column in both "
            "is what doubled the header (17 columns for a 15-column preset) and "
            "dropping `statistics` makes it return no BOM file at all; the BOM's "
            "`filterOptions` are "
            "*exclusion* rules — `includeValue` is the value that leaves a row out, "
            "not the one it keeps — and the host names the BOM file itself "
            "(`fileName + '.' + fileType`) while gerber/P&P echo the name they are "
            "handed."
        ),
        params=("pcbUuid", "outDir", "vendor", "gerber", "bom", "bomTemplate", "timeoutMs"),
        returns=(
            "{vendor, project, pcb, outDir, generatedAt, encoding: 'base64', "
            "files: [{role, name, mime, bytes, data}], manifest, failed, partial, note}"
        ),
        params_schema=(
            "pcbUuid: the board to export — default is the focused PCB, and a pcbUuid "
            "that is not the focused one is PAGE_MISMATCH (the manufacture APIs export "
            "the board in front); outDir: the directory the CALLER writes into "
            "(required; recorded in the manifest); vendor: 'generic' (default); gerber: "
            "override object limited to fileName/colorSilkscreen/unit/digitalFormat/"
            "other/layers/objects; bom: override object limited to filterOptions — "
            "`[{property, includeValue}]` where the rule leaves a row **out** when the "
            "part's property matches `includeValue` (so the preset sends 'Add into "
            "BOM': 'no'), and `null` means 'send none — keep the host's own default "
            "rules'; bomTemplate: a saved BOM template name; timeoutMs: "
            "per-file deadline (200..600000, default 60000)"
        ),
        risk="read",
    ),
    Action(
        name="lib.recommend",
        summary=(
            "READ-ONLY part recommendations for a placed part or a bare query "
            "(012 §七). The search descends: the LCSC code as `supplierId` (the one "
            "properties key 3.2.186 indexes, measured 2026-09-21) → "
            "searchByProperties(value + footprintName) → search(keyword); "
            "each rung reports its own hit count (5 per page, 3 pages max) and the "
            "rungs a hit made unnecessary are reported as not called. JLCPCB Basic "
            "parts sort first. No stock and no price — the type package's search item "
            "carries neither — so the answer labels them `stock/price: 以商城实时为准`. "
            "`probes` (≤10) replaces the descent with raw `searchByProperties` calls — a "
            "read-only channel for measuring that method on a live host, see "
            "`params_schema`. Nothing is placed: placement stays the oracle's decision."
        ),
        params=("query", "pageUuid", "ref", "topN", "allLayers", "timeoutMs", "probes"),
        returns=(
            "{source, query, ref, component, target, layers: [{layer, api, called, args, "
            "hitCount, pagesFetched, reason?, error?}], returned, shown, candidates: "
            "[{name, lcsc, mpn, footprintName, partClass, datasheet, deviceUuid, "
            "libraryUuid, symbolUuid, footprintUuid, layer}], 'stock/price', readOnly, placed}; "
            "with probes: {source: 'probes', probes: [{args, called, hitCount, pageSize, "
            "firstKeys, error?}], probesOnly: true, layers: [], candidates: [], returned: 0, "
            "shown: 0, …}"
        ),
        params_schema=(
            "query: free text (an MPN, a value, or a C-number) — or pageUuid+ref for a "
            "part already on the page (the ref path is focus-guarded: the designator is "
            "resolved in the focused page's component list); a bare MPN reaches the "
            "keyword rung only: the exact rung is the LCSC code under `supplierId`, "
            "because that is the one properties key 3.2.186 indexes (measured "
            "2026-09-21); topN: how many candidates "
            "(1..20, default 5); allLayers: run every rung instead of stopping at the "
            "first that hits; timeoutMs: per-page deadline for one library search "
            "(200..120000, default 20000) — a hung page is reported as that rung's "
            "error and the descent continues; probes: at most 10 raw "
            "{properties, libraryUuid?, classification?, symbolType?, itemsOfPage?, page?} "
            "entries — each is one `lib_Device.searchByProperties` call sent with exactly "
            "the arguments given (an argument left out is not sent, so `arguments.length` "
            "is the caller's), the ladder is not walked at all, and each entry is reported "
            "as {args, called, hitCount, pageSize, firstKeys, error?} with "
            "`probesOnly: true` in the answer"
        ),
        risk="read",
    ),
    # --- 012 §八: a review pass drawn back onto the canvas -------------------
    Action(
        name="review.mark",
        summary=(
            "Draw a `boardwise review` pass on the focused schematic page as "
            "indicator markers, and jump to one finding (012 §八). The marker API "
            "takes SHAPES, not text, so each mark's ref is resolved to its "
            "component's coordinates first (the same component dump `sch.geometry` "
            "returns) and the rule id / severity / one-line summary travel in the "
            "result instead: `marked[k-1]` is marker k. View-only: markers are an "
            "overlay, no primitive is created, moved or modified."
        ),
        params=("pageUuid", "marks", "clear", "focus", "color", "zoom", "markers"),
        returns=(
            "{mode: 'markers'|'list', cleared, page: {components, designators, "
            "withoutPosition, active}, count, marked: [{position, marker, ref, "
            "designator, ruleId, severity, text, primitiveId, x, y}], unresolved: "
            "[{position, ref, ruleId, severity, text, reason}], markers: {attempted, "
            "accepted, reason?}, focused?: {position, ref, zoomed, reason?}, readOnly, "
            "note, notes?}"
        ),
        params_schema=(
            "pageUuid: optional — the schematic page the findings are about; a "
            "different focused page is PAGE_MISMATCH (without it, the page is not "
            "verified and the result says so); marks: [{ref, ruleId, severity, text}] "
            "in the caller's own finding order (position k is the k-th entry, which is "
            "what `focus` counts) — a ref that is not on the page is reported in "
            "`unresolved` while the rest are still marked; clear: true calls "
            "removeIndicatorMarkers instead (and ignores marks) — it has **no page "
            "guard** (it clears whatever canvas is in front, which may belong to "
            "another project), and with no active document it answers cleared: true "
            "with the note 'no active canvas — nothing to remove' instead of "
            "reporting the host's refusal of a call that had nothing to act on; "
            "focus: 1-based "
            "position to zoom to, via zoomToRegion; color: '#RRGGBB' or "
            "{r,g,b,alpha}; zoom: zoom the canvas to all markers (ignored when focus "
            "is given); markers: false returns the jump list (ref + coordinates) "
            "without drawing — the explicit form of the degradation that also "
            "happens when generateIndicatorMarkers is missing or refuses"
        ),
        risk="read",
    ),
    # --- 006c: document management (probe / open / create / rename) ----------
    Action(
        name="doc.list",
        summary=(
            "READ-ONLY: every document in the open project — schematic pages and "
            "PCBs — with uuid / name / type / which one is active. The harness has "
            "been acting on 'whatever page is focused'; this makes the project's "
            "document set something a caller can see instead of assume, and is "
            "how a uuid for doc.open / doc.rename is obtained."
        ),
        params=(),
        returns=(
            "{documents: [{uuid, name, type, active}], active: {uuid, type, tabId}, "
            "schematicPages, pcbs, count, notes?}"
        ),
        risk="read",
    ),
    Action(
        name="doc.open",
        summary=(
            "Open a document by uuid and put the input focus in it, so subsequent "
            "actions operate on the page the caller chose rather than on whichever "
            "tab happened to be in front. Changes the editor's active document, "
            "never the project's content."
        ),
        params=("uuid",),
        returns="{uuid, tabId, opened, activated, document: {uuid, name, type, active}}",
        params_schema="uuid: schematic page / schematic / PCB uuid (from doc.list)",
        risk="read",
    ),
    Action(
        name="pcb.doc.new",
        summary=(
            "CREATE a PCB in the current project (mirrors sch.doc.new). Produces a "
            "new document, so the daemon refuses it without params.confirm: true "
            "(CONFIRMATION_REQUIRED)."
        ),
        params=("boardName", "confirm"),
        returns="{pcbUuid, focused}",
        params_schema="boardName: optional parent board name; confirm: must be true",
        risk="create",
    ),
    Action(
        name="doc.rename",
        summary=(
            "Rename a schematic page, a schematic, or a PCB by uuid. The editor "
            "exposes three separate calls (modifySchematicPageName / "
            "modifySchematicName / modifyPcbName) and the action dispatches on the "
            "requested type — a rename is a write to existing content, not a new "
            "document."
        ),
        params=("uuid", "name", "type"),
        returns="{uuid, name, type, renamed, document?}",
        params_schema=(
            "uuid: document uuid; name: the new name; type: 'page'|'schematic'|'pcb' "
            "(optional — resolved through doc.list when omitted)"
        ),
        risk="write",
    ),
)

ACTION_NAMES: frozenset[str] = frozenset(action.name for action in ACTIONS)
_ACTIONS_BY_NAME: dict[str, Action] = {action.name: action for action in ACTIONS}


class ErrorCodes:
    """Machine-readable error codes carried in ``error.code``."""

    #: No ``hello``, a bad or missing token.
    UNAUTHENTICATED = "UNAUTHENTICATED"
    #: First frame was not ``hello``, or ``hello`` arrived twice.
    PROTOCOL_VIOLATION = "PROTOCOL_VIOLATION"
    #: Connector and daemon disagree on the protocol major version.
    VERSION_MISMATCH = "VERSION_MISMATCH"
    #: Malformed JSON, or a frame missing a required field.
    BAD_REQUEST = "BAD_REQUEST"
    #: Action is not in :data:`ACTIONS`.
    UNKNOWN_ACTION = "UNKNOWN_ACTION"
    #: Action is known but this side does not implement it yet.
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    #: A ``create`` action arrived without ``params.confirm is True``. Raised by
    #: the daemon, before anything is forwarded, so the editor never sees it.
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    #: The action needs the editor but no connector is connected.
    NO_CONNECTOR = "NO_CONNECTOR"
    #: The connector raised / returned an error.
    CONNECTOR_ERROR = "CONNECTOR_ERROR"
    #: The connector did not answer in time.
    TIMEOUT = "TIMEOUT"
    #: The daemon connection died before an answer arrived. Raised by the
    #: **client**, never by the daemon: once the socket is gone nobody is left to
    #: answer. It exists as its own code because "the transport died" and "the
    #: action failed" are not the same fact — a write whose answer never came may
    #: still have landed in the editor, and a caller that cannot tell them apart
    #: will report a half-drawn page as untouched (M0-P0d follow-up, 2026-09-18).
    DISCONNECTED = "DISCONNECTED"
    #: Anything else; ``error.message`` carries the text.
    INTERNAL = "INTERNAL"


class BridgeError(Exception):
    """An error that carries a wire-level code."""

    def __init__(self, code: str, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def as_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail is not None:
            error["detail"] = self.detail
        return error


# --------------------------------------------------------------------------
# frame building / parsing
# --------------------------------------------------------------------------

_id_counter = 0


def new_id(prefix: str = "req") -> str:
    """Return a short unique correlation id.

    Monotonic counter plus a random suffix: unique within a process and
    unguessable enough that a stray late response cannot be mistaken for the
    current one.
    """
    global _id_counter
    _id_counter += 1
    return f"{prefix}-{_id_counter:06d}-{_random_suffix()}"


def _random_suffix() -> str:
    import secrets

    return secrets.token_hex(3)


def request_frame(action: str, params: dict[str, Any] | None = None, *, id: str | None = None) -> str:
    """Serialise a request frame."""
    frame: dict[str, Any] = {"id": id or new_id(), "action": action}
    if params:
        frame["params"] = params
    return json.dumps(frame, ensure_ascii=False)


def response_frame(id: str, data: Any = None) -> str:
    """Serialise a successful response frame."""
    return json.dumps({"id": id, "ok": True, "data": data}, ensure_ascii=False)


def error_frame(id: str | None, error: BridgeError | dict[str, Any]) -> str:
    """Serialise a failed response frame."""
    payload = error.as_dict() if isinstance(error, BridgeError) else error
    frame: dict[str, Any] = {"id": id, "ok": False, "error": payload}
    return json.dumps(frame, ensure_ascii=False)


def banner_frame() -> str:
    """Serialise the event the daemon sends the moment a socket opens.

    This is the fix for the handshake deadlock found on real hardware (task
    004b). The connector used to send ``hello`` from the editor's *connect
    callback*, and when that callback did not fire the connector stayed silent
    while the daemon waited — nothing was ever sent in either direction.
    Sending a frame from the daemon first makes the handshake **message
    driven**: any inbound frame proves the socket is up end to end, and the
    connector answers it with ``hello``.

    Carries no secret: it arrives before authentication, so it may only say
    what is already public about the daemon. ``expect`` states the next move
    explicitly rather than leaving the client to infer it.
    """
    return json.dumps(
        {
            "event": EVENT_BANNER,
            "data": {
                "server": "boardwise",
                "protocol": PROTOCOL_VERSION,
                "expect": "hello",
            },
        },
        ensure_ascii=False,
    )


def decode_frame(raw: str | bytes) -> dict[str, Any]:
    """Parse one frame, raising :class:`BridgeError` on anything unusable.

    Validated here: JSON parses, the top level is an object, ``action`` is a
    non-empty string on requests. ``id`` is *not* required — the caller may
    still need to answer "I could not even read your id".
    """
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BridgeError(ErrorCodes.BAD_REQUEST, "frame is not UTF-8") from exc
    try:
        frame = json.loads(raw)
    except ValueError as exc:
        raise BridgeError(ErrorCodes.BAD_REQUEST, f"frame is not JSON: {exc}") from exc
    if not isinstance(frame, dict):
        raise BridgeError(ErrorCodes.BAD_REQUEST, "frame must be a JSON object")
    if "action" in frame and not (isinstance(frame["action"], str) and frame["action"]):
        raise BridgeError(ErrorCodes.BAD_REQUEST, "frame.action must be a non-empty string")
    return frame


def frame_kind(frame: dict[str, Any]) -> str:
    """Classify a decoded frame: ``"response"`` | ``"event"`` | ``"request"``.

    A frame is classified by the strongest key it carries, so a frame that
    somehow holds two of them behaves predictably instead of ambiguously. Both
    clients use this to step over the banner while waiting for an answer, and
    the tests use it to say what they expect on the wire.
    """
    if "ok" in frame:
        return "response"
    if "event" in frame:
        return "event"
    return "request"


def describe_actions(actions: Iterable[Action] = ACTIONS) -> str:
    """Render the action catalogue for ``--help`` / docs."""
    lines = [f"{'action':22} {'owner':10} {'risk':7} {'params':28} summary"]
    for action in actions:
        params = ",".join(action.params) or "-"
        lines.append(
            f"{action.name:22} {action.owner:10} {action.risk:7} {params:28} {action.summary}"
        )
    return "\n".join(lines)


def action_spec(name: str) -> Action | None:
    return _ACTIONS_BY_NAME.get(name)


def timeout_for(action: str) -> float:
    """Per-action timeout: image work and placements render; the rest just reads."""
    # Image work is slow: a canvas capture and a document render both wait on
    # the editor's renderer, so they get the longer budget.
    if action in ("export.screenshot", "export.render"):
        return SCREENSHOT_TIMEOUT
    # A placement resolves the library on first use; the connector bounds the
    # call itself (30 s default) and reads back on a miss, so the daemon's
    # budget must outlast that readback for its answer to reach the caller.
    if action == "sch.place_component":
        return PLACEMENT_TIMEOUT
    # 012 measured 2026-09-21: a schematic delete costs ~3.7 s per primitive
    # (the editor re-solves the page each time), so the 17-part cleanup ran
    # past the 30 s default and the CLI hung up mid-batch. The action is
    # per-id honest and resumable, but a caller that has to split its own
    # batches to fit a timeout is a caller working around the daemon. 150 s
    # covers ~40 primitives, the largest sane single cleanup.
    if action in ("sch.delete_primitives", "pcb.delete_primitives"):
        return DELETE_TIMEOUT
    # Three manufacture exports in one call, each bounded at 60 s by the
    # connector — the daemon has to outlast all three so a per-file miss
    # ("gerber timed out, BOM still landed") reaches the caller as an answer.
    if action == "export.fab":
        return FAB_TIMEOUT
    # Up to nine library searches (3 rungs × 3 pages) behind one action.
    if action == "lib.recommend":
        return RECOMMEND_TIMEOUT
    return ACTION_TIMEOUT


@dataclass
class Connection:
    """Bookkeeping the daemon keeps for one socket. Not wire-visible."""

    role: str = ""
    client: str = ""
    protocol: str = ""
    #: The connector's own build version, announced in `hello`. Empty for a CLI
    #: connection and for a connector built before 0.4.1 — see
    #: :func:`boardwise.bridge.daemon.client_with_version`, which renders that
    #: absence as "(version unknown)" instead of hiding it.
    connector_version: str = ""
    authenticated: bool = False
    #: Frames received after handshake, for the audit log.
    seen_actions: list[str] = field(default_factory=list)
