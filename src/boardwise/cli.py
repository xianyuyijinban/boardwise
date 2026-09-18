"""boardwise command line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .engines.review import (
    render_json,
    render_markdown,
    run_review,
    severity_counts,
)
from .engines.generate import DEFAULT_NAMING_STRATEGY, NAMING_STRATEGIES
from .parsers.enet import parse_enet
from .parsers.epro2_model import build_design_model
from .parsers.epru import EncryptedProjectError, build_board_geometry, load_epro2_source

#: Input extensions the reviewer understands, and what each one is.
SUPPORTED_SUFFIXES: dict[str, str] = {
    ".enet": "schematic netlist export",
    ".epro2": "project backup (board + netlist, one file)",
}


def _bridge_help_epilog() -> str:
    """Render the action catalogue for ``boardwise bridge --help``.

    The catalogue lives in one place (``bridge/protocol.py``) and is rendered
    here so the help text cannot drift from what the daemon actually routes.

    Imported lazily and defensively: the offline ``review`` path must keep
    working even if the bridge package is unavailable. ``protocol.py`` is
    stdlib-only, so this import never pulls in ``websockets``.
    """
    try:
        from .bridge.protocol import describe_actions

        return "actions:\n\n" + describe_actions()
    except Exception:  # pragma: no cover - defensive; bridge must never break review
        return "actions: (bridge package unavailable — see docs/bridge.md)"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="boardwise",
        description="AI harness for EasyEDA Pro: offline design review (stage 1).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    review = sub.add_parser(
        "review", help="Review an EasyEDA .enet netlist or .epro2 backup offline."
    )
    review.add_argument(
        "file", help="Path to the .enet netlist or .epro2 project backup."
    )
    review.add_argument(
        "--json", dest="json_path", metavar="PATH", help="Write a JSON report."
    )
    review.add_argument(
        "--md", dest="md_path", metavar="PATH", help="Write a Markdown report."
    )

    bridge = sub.add_parser(
        "bridge",
        help="Live channel to a running EasyEDA (daemon + editor extension).",
        description=(
            "Live channel to a running EasyEDA Pro: a loopback daemon plus an "
            "editor extension. Actions owned by 'daemon' are answered locally; "
            "'connector' actions are forwarded into the editor."
        ),
        epilog=_bridge_help_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    bridge_sub = bridge.add_subparsers(dest="bridge_command", required=True)
    bridge_sub.add_parser("start", help="Run the daemon in the foreground.")
    bridge_sub.add_parser("status", help="Report whether the daemon and connector are up.")
    bridge_sub.add_parser(
        "revoke",
        help="Forget the paired connector; the next one to connect is trusted instead.",
    )
    shot = bridge_sub.add_parser("screenshot", help="Export the current canvas as PNG.")
    shot.add_argument("out", help="Where to write the PNG.")
    shot.add_argument("--fit", action="store_true", help="Fit the board before capturing.")
    call = bridge_sub.add_parser(
        "call",
        help=(
            "Call one connector action directly (probes and diagnosis); "
            "--action NAME [--params JSON]."
        ),
    )
    call.add_argument("--action", required=True, help="Action name from the catalogue.")
    call.add_argument(
        "--params", default="{}", help="Action params as a JSON object literal."
    )
    call.add_argument(
        "--yes", action="store_true",
        help=(
            "Pre-confirm a `create` action (creates a new document). Without it, "
            "the daemon answers CONFIRMATION_REQUIRED and this command asks "
            "interactively instead."
        ),
    )
    mark = bridge_sub.add_parser("highlight", help="Mark primitives on the live canvas.")
    mark.add_argument("uuids", nargs="+", help="Primitive uuids to mark.")
    mark.add_argument("--color", default="#FF0000", help="Marker colour (default #FF0000).")
    mark.add_argument(
        "--clear", action="store_true", help="Clear previous markers instead of adding."
    )
    mark.add_argument(
        "--zoom", action="store_true", help="Zoom the canvas to the markers."
    )
    update = bridge_sub.add_parser(
        "update-connector",
        help=(
            "Hot-update the running connector to a freshly built bundle "
            "(sys.self_update): no uninstall, no re-import, no editor restart — "
            "the editor page reloads itself after the write."
        ),
    )
    update.add_argument(
        "--bundle", default=None,
        help="Path to the new bundle (default: connector/dist/index.js).",
    )
    update.add_argument(
        "--version", default=None, metavar="X.Y.Z",
        help="Version string to store (default: read from connector/extension.json).",
    )
    update.add_argument(
        "--yes", action="store_true",
        help="Skip the confirmation prompt (the editor page WILL reload).",
    )
    bridge.add_argument(
        "--port", type=int, default=None, help="Daemon port (default 61190)."
    )

    compare = sub.add_parser(
        "compare",
        help=(
            "Compare a candidate .epro2 against the golden board, per pin "
            "(task 005). With --spec the candidate side is the **spec netlist** "
            "assembled from block templates instead of a file (task 008a). "
            "Exit 0 equal / 1 differences / 2 bad input."
        ),
    )
    compare.add_argument(
        "candidate",
        nargs="?",
        default=None,
        help="Path to the candidate .epro2 project backup.",
    )
    compare.add_argument(
        "--spec",
        default=None,
        help=(
            "Path to a board spec (block templates + placement + connections). "
            "The candidate model is assembled from it offline, so the comparison "
            "answers 'does the specification reproduce the golden?' without an "
            "editor in the loop."
        ),
    )
    compare.add_argument(
        "--golden",
        default="tests/fixtures/ch340_golden.epro2",
        help="Path to the golden .epro2 (default: tests/fixtures/ch340_golden.epro2).",
    )
    compare.add_argument(
        "--overrides",
        default=None,
        help=(
            "Golden-corrections sidecar. Default: the file beside the golden "
            "fixture, `<stem>.overrides.json`."
        ),
    )
    compare.add_argument(
        "--json", action="store_true", help="Print the machine-readable report."
    )
    draw = sub.add_parser(
        "draw",
        help=(
            "Redraw a golden board on a blank schematic page through the "
            "bridge and diff the result per pin (task 006). With --spec the plan "
            "is assembled from block templates instead of replayed from the "
            "golden page (task 008a). "
            "Exit 0 equal / 1 differences or failures / 2 bad input."
        ),
    )
    draw.add_argument(
        "--from", dest="from_file", default=None,
        help="Path to the golden .epro2 whose connectivity is the design input.",
    )
    draw.add_argument(
        "--spec", default=None,
        help=(
            "Path to a board spec. The design is assembled from its block "
            "templates; --from is then only used for the double-check."
        ),
    )
    draw.add_argument(
        "--golden", default=None,
        help=(
            "With --spec: the .epro2 to double-check the spec netlist against "
            "**before** anything is created. A mismatch aborts the run."
        ),
    )
    draw.add_argument(
        "--yes", action="store_true",
        help="Skip the execution gate (print the plan and go).",
    )
    draw.add_argument(
        "--screenshot", default=None,
        help="Where to write the post-draw canvas screenshot (PNG path).",
    )
    draw.add_argument(
        "--overrides", default=None,
        help=(
            "Golden-corrections sidecar (JSON). Default: the file next to the "
            "golden fixture, `<stem>.overrides.json`. The fixture itself is "
            "evidence and is never edited; the sidecar carries the corrections "
            "and every hit is reported with its provenance."
        ),
    )
    draw.add_argument(
        "--render", default=None,
        help=(
            "Where to write the acceptance image — an `export.render` document "
            "render (PNG). A viewport screenshot is NOT evidence (cached frames)."
        ),
    )
    draw.add_argument(
        "--solver", action="store_true",
        help=(
            "Use the generic layout solver instead of replaying the golden "
            "page's own geometry (the default)."
        ),
    )
    draw.add_argument(
        "--naming", choices=NAMING_STRATEGIES, default=DEFAULT_NAMING_STRATEGY,
        help=(
            "How signal nets are named (default: %(default)s). "
            "wire: the wire carries the net name only; "
            "text: wire plus a decorative text label beside it (visible, not "
            "an electrical object — the report says so); "
            "label: the native net-label API (needs an EDA v4 host; dormant); "
            "none: no signal names at all. Rails always keep their flags."
        ),
    )

    lint = sub.add_parser(
        "lint",
        help=(
            "Offline layout lint of the plan (overlap / out-of-frame / through-part / "
            "floating or stacked names). No bridge, no editor. "
            "Exit 0 clean / 1 violations."
        ),
    )
    lint.add_argument(
        "--from", dest="from_file", default=None,
        help="Path to the golden .epro2 the plan is replayed from.",
    )
    lint.add_argument(
        "--spec", default=None,
        help="Path to a board spec: lint the plan assembled from its blocks instead.",
    )
    lint.add_argument(
        "--plan", choices=("replay", "solver"), default="replay",
        help="Which plan to lint (default: replay the golden geometry).",
    )
    lint.add_argument(
        "--naming", choices=NAMING_STRATEGIES, default=DEFAULT_NAMING_STRATEGY,
        help="Signal-naming policy to lint under (default: %(default)s).",
    )
    lint.add_argument(
        "--json", action="store_true", help="Print the machine-readable report.",
    )

    parts = sub.add_parser(
        "parts",
        help=(
            "The curated part library (task 008b): offline selection from "
            "blocklib/parts.json, with an explicit --online catalog compare."
        ),
    )
    parts_sub = parts.add_subparsers(dest="parts_command", required=True)
    pick = parts_sub.add_parser(
        "select",
        help=(
            "Rank parts for a query. Offline by default. An explicit resistance "
            "query (``10kΩ``) is gated: no exact candidate means exit code 1 and "
            "no fuzzy recommendation."
        ),
    )
    pick.add_argument("query", help="What is wanted, e.g. '10kΩ 0402' or 'CH340N'.")
    pick.add_argument(
        "--qty", type=int, default=100,
        help="Build quantity; decides the price tier and the stock requirement.",
    )
    pick.add_argument(
        "--library", default="blocklib/parts.json",
        help="Path to the curated library (default: %(default)s).",
    )
    pick.add_argument(
        "--online", action="store_true",
        help=(
            "Explicit opt-in: compare against the JLC SMT catalog (base + general "
            "merged). This touches the network; the connector never does."
        ),
    )
    pick.add_argument(
        "--limit", type=int, default=50, help="Catalog page size per query.",
    )
    pick.add_argument(
        "--resolve", action="store_true",
        help=(
            "Resolve the top pick's identity through the bridge by C-number "
            "(lib.device.search) — an exact key, never a fuzzy keyword."
        ),
    )
    pick.add_argument(
        "--write", action="store_true",
        help="With --resolve: add the resolved pick to the library on disk.",
    )
    pick.add_argument(
        "--json", action="store_true", help="Print the machine-readable result.",
    )

    bom = sub.add_parser(
        "bom",
        help=(
            "The bill of materials a board spec implies (task 008c): a BOM is an "
            "output of the design, so it is derived from the spec and the shelf."
        ),
    )
    bom_sub = bom.add_subparsers(dest="bom_command", required=True)
    export = bom_sub.add_parser(
        "export",
        help=(
            "Export the BOM as CSV (JLC's five columns) plus an open-question "
            "list. Exit 0 complete / 1 unresolved or conflicting / 2 bad input."
        ),
    )
    export.add_argument(
        "--spec", required=True, help="Path to the board spec whose BOM is wanted.",
    )
    export.add_argument(
        "--library", default="blocklib/parts.json",
        help="Path to the curated library (default: %(default)s).",
    )
    export.add_argument(
        "--out", default="",
        help="Write the CSV here (default: print the report only).",
    )
    export.add_argument(
        "--json", action="store_true", help="Print the machine-readable report.",
    )

    pintable = sub.add_parser(
        "pintable",
        help=(
            "The firmware pin table (task 008c): what the MCU is wired to, read "
            "from firmware and cross-checked against the CubeMX .ioc baseline."
        ),
    )
    pt_sub = pintable.add_subparsers(dest="pintable_command", required=True)
    check = pt_sub.add_parser(
        "check",
        help=(
            "Check a pin table: closed function vocabulary, one row per pin, "
            "and the two-way difference against a spec. Exit 0 clean / 1 defect "
            "/ 2 bad input. Open questions are printed but do not block."
        ),
    )
    check.add_argument("--table", required=True, help="Path to the pintable JSON.")
    check.add_argument(
        "--spec", default="",
        help="Board spec to compare nets against (gate 3).",
    )
    check.add_argument(
        "--block", default="",
        help="Block id of the MCU inside that spec (default: every block named 'mcu').",
    )
    check.add_argument(
        "--ioc", default="",
        help="CubeMX .ioc file to cross-check against. Disagreements are reported, "
             "never resolved.",
    )
    check.add_argument(
        "--json", action="store_true", help="Print the machine-readable report.",
    )

    validate = sub.add_parser(
        "validate",
        help=(
            "Run a board spec through the four gates of task 008c item 4 "
            "(closed book, pin budget, levels, power tree). Exit 0 clean / 1 "
            "blocked / 2 bad input. An undecidable result blocks like a "
            "violation does; a skipped gate says so instead of passing."
        ),
    )
    validate.add_argument("--spec", required=True, help="Path to the board spec.")
    validate.add_argument(
        "--target", action="append", default=[],
        metavar="NAME",
        help=(
            "The board being generated — the one whose artifacts may not be "
            "consulted. Give every alias it has (the export AND the local "
            "project), or the closed-book gate stays undecidable; repeat the "
            "option for more than one."
        ),
    )
    validate.add_argument(
        "--table", default="",
        help="Firmware pin table to check the MCU block against (gate 2).",
    )
    validate.add_argument(
        "--library", default="",
        help="Curated part library a `part` reference can cite (default: %(default)s).",
    )
    validate.add_argument(
        "--port-meta", default="blocklib/blocks.portmeta.json",
        help=(
            "Port-metadata sidecar saying what each port is electrically "
            "(default: %(default)s). Voltage, direction and IO level are "
            "declarations, so they live beside the blocks rather than inside "
            "them — `--recut` reproduces the block files byte for byte. Without "
            "it every gate that needs those fields answers \"cannot tell\"."
        ),
    )
    validate.add_argument(
        "--root", default=".",
        help="Directory declared input paths are read relative to (default: %(default)s).",
    )
    validate.add_argument(
        "--block", default="",
        help="Block id of the MCU (default: the one the pin table names, or one named 'mcu').",
    )
    validate.add_argument(
        "--mcu-component", default="",
        help="Designator of the MCU inside that block, when the block has more than one part.",
    )
    validate.add_argument(
        "--json", action="store_true", help="Print the machine-readable report.",
    )
    return parser


def _load_model(path: Path) -> tuple[object, object | None]:
    """Return ``(DesignModel, BoardGeometry | None)`` for a supported input.

    ``BoardGeometry`` is only available for ``.epro2``; both views come from
    one parse of the file. Raises :class:`EncryptedProjectError` for an
    unreadable backup and ``ValueError`` for an unsupported extension.
    """
    suffix = path.suffix.lower()
    if suffix == ".enet":
        return parse_enet(path), None
    if suffix == ".epro2":
        source = load_epro2_source(path)
        # One parse, two views: geometry and netlist stay consistent because
        # both read the same cached PCB context.
        return build_design_model(source), build_board_geometry(source)
    supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
    raise ValueError(f"unsupported input type {suffix or '(none)'}; expected {supported}")


def _cmd_compare(args: argparse.Namespace) -> int:
    """Golden-vs-candidate comparison (task 005): exit 0 equal / 1 differ / 2 bad input.

    With ``--spec`` the candidate side is the **spec netlist** assembled offline
    from block templates (task 008a work item 4): the judgement source becomes
    the specification rather than a candidate file, which is what lets the
    assembled design be checked against the golden before an editor is involved.
    The golden side gets its corrections sidecar applied first — the fixture is
    evidence and is never edited (006b §G.3).
    """
    from boardwise.core.compare import compare_models
    from boardwise.parsers.schematic import build_schematic_model

    if not args.spec and not args.candidate:
        print(
            "boardwise compare: give a candidate .epro2 or --spec <board spec>",
            file=sys.stderr,
        )
        return 2
    if args.spec and args.candidate:
        print(
            "boardwise compare: --spec and a candidate file are two different "
            "candidate sources; give one",
            file=sys.stderr,
        )
        return 2

    try:
        golden = build_schematic_model(args.golden)
    except Exception as exc:  # noqa: BLE001 — the CLI must not traceback
        print(f"boardwise compare: golden {args.golden}: {exc}", file=sys.stderr)
        return 2

    from boardwise.core.overrides import apply_overrides, load_overrides

    # The sidecar is applied **only when it is named**. `compare`'s contract
    # (task 005) is a raw file-against-file comparison, and silently correcting
    # the golden would change what an existing command means. `draw` defaults
    # to the sidecar beside the fixture because it always has; here the caller
    # says so, and `compare --spec ... --overrides <sidecar>` is how task 008a's
    # acceptance asks whether the specification reproduces the *corrected*
    # design.
    override_lines: list[str] = []
    if args.overrides:
        try:
            sidecar = load_overrides(args.overrides)
        except ValueError as exc:
            print(f"boardwise compare: {exc}", file=sys.stderr)
            return 2
        if sidecar.active:
            override_lines = apply_overrides(golden, sidecar)

    candidate_source = ""
    if args.spec:
        from boardwise.core.blocks import BlockError, load_board_spec
        from boardwise.engines.assemble import assemble

        try:
            design = assemble(load_board_spec(args.spec))
        except BlockError as exc:
            print(f"boardwise compare: {args.spec}: {exc}", file=sys.stderr)
            return 2
        candidate = design.model
        candidate_source = f"spec {args.spec}"
    else:
        try:
            candidate = build_schematic_model(args.candidate)
        except Exception as exc:  # noqa: BLE001
            print(f"boardwise compare: candidate {args.candidate}: {exc}", file=sys.stderr)
            return 2
        candidate_source = f"file {args.candidate}"

    report = compare_models(golden, candidate)
    if args.json:
        import json

        print(json.dumps(report.to_jsonable(), ensure_ascii=False, indent=2))
    else:
        print(
            f"boardwise compare: candidate {candidate_source} vs golden {args.golden} "
            f"({len(candidate.components)} components, {len(candidate.nets)} nets vs "
            f"{len(golden.components)}, {len(golden.nets)})"
        )
        for line in override_lines:
            print(f"  golden override: {line}")
        if report.is_empty:
            print("no differences — designs match")
        else:
            print(report.render())
    return 0 if report.is_empty else 1


def _cmd_review(args: argparse.Namespace) -> int:
    path = Path(args.file)
    try:
        model, board = _load_model(path)
    except EncryptedProjectError as exc:
        print(f"boardwise: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"boardwise: {path}: {exc}", file=sys.stderr)
        return 2

    findings = run_review(model)
    counts = severity_counts(findings)

    print(
        f"boardwise review: {args.file} "
        f"({len(model.components)} components, {len(model.nets)} nets)"
    )
    if board is not None:
        print(
            f"board: {len(board.pads)} pads, {len(board.tracks)} tracks, "
            f"{len(board.vias)} vias"
        )
    print(
        f"findings: {counts['ERROR']} ERROR, "
        f"{counts['WARN']} WARN, {counts['INFO']} INFO"
    )
    for finding in findings:
        print(f"[{finding.severity}] {finding.rule_id}: {finding.message}")

    if args.json_path:
        Path(args.json_path).write_text(render_json(findings), encoding="utf-8")
        print(f"JSON report written to {args.json_path}")
    if args.md_path:
        meta = {
            "source": str(args.file),
            "components": len(model.components),
            "nets": len(model.nets),
        }
        Path(args.md_path).write_text(
            render_markdown(findings, meta), encoding="utf-8"
        )
        print(f"Markdown report written to {args.md_path}")

    return 1 if counts["ERROR"] else 0


# --------------------------------------------------------------------------
# bridge (live channel to a running EasyEDA)
# --------------------------------------------------------------------------


def _bridge_modules():
    """Import the bridge lazily: offline review must work without websockets.

    Returns ``(client, daemon, BridgeError)`` — the two modules and the error
    type. Modules rather than a tuple of names: the daemon module keeps growing
    (tokens, pairing, audit) and positional unpacking made every addition a
    chance to silently shift an argument.
    """
    try:
        from .bridge import client as bridge_client
        from .bridge import daemon as bridge_daemon
        from .bridge.protocol import BridgeError
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on install
        raise SystemExit(
            f"boardwise bridge needs the 'websockets' package ({exc}). "
            "Install it with: pip install websockets"
        ) from exc
    return bridge_client, bridge_daemon, BridgeError


def _bridge_port(args: argparse.Namespace) -> int:
    if getattr(args, "port", None):
        return int(args.port)
    _, daemon, _ = _bridge_modules()
    return daemon.resolve_port()


def _open_cli(args: argparse.Namespace):
    """Return ``(BridgeClient, BridgeError, port, token)`` for an already-running daemon."""
    client, daemon, BridgeError = _bridge_modules()
    return client.BridgeClient, BridgeError, _bridge_port(args), daemon.ensure_token()


def _bridge_uri(port: int) -> str:
    """The daemon URL — spelled in exactly one place (``bridge.client.uri_for``).

    Imported here rather than at module scope so that ``boardwise review``
    still works on an install without ``websockets``.
    """
    from .bridge import client as bridge_client

    return bridge_client.uri_for(port=port)


def _cmd_bridge_start(args: argparse.Namespace) -> int:
    import asyncio

    _, daemon_module, _ = _bridge_modules()
    port = _bridge_port(args)
    daemon = daemon_module.BridgeDaemon(
        token=daemon_module.ensure_token(),
        # Pairing is announced here, on the console the operator is already
        # watching, rather than only landing in a JSONL file nobody tails.
        on_pairing=lambda notice: print("\n".join(notice.console_lines()), flush=True),
    )
    # flush=True throughout: this process then blocks forever, so anything left
    # in the buffer does not appear until it exits. Under a terminal that is
    # invisible; redirected to a file or a log collector it means the startup
    # banner and the pairing announcement never arrive at all — and the pairing
    # announcement is the one message that tells the user how to undo it.
    print(f"boardwise bridge: listening on 127.0.0.1:{port}", flush=True)
    print(f"  token file: {daemon_module.token_path()}", flush=True)
    print(f"  audit log:  {daemon_module.audit_dir()}", flush=True)
    print(f"  pairing:    {daemon_module.connector_token_path()}", flush=True)
    print("  waiting for the EasyEDA extension to connect (Ctrl-C to stop)", flush=True)

    async def run() -> None:
        async def on_ready(actual: int) -> None:
            if actual and actual != port:
                print(f"boardwise bridge: listening on 127.0.0.1:{actual}", flush=True)

        await daemon_module.serve_forever(daemon, port=port, on_ready=on_ready)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nboardwise bridge: stopped")
    return 0


def _cmd_bridge_status(args: argparse.Namespace) -> int:
    import asyncio

    BridgeClient, BridgeError, port, token = _open_cli(args)

    async def run() -> int:
        try:
            client = await BridgeClient.open(
                _bridge_uri(port), token, "cli", client="boardwise-cli"
            )
        except (OSError, BridgeError) as exc:
            print(f"boardwise bridge: daemon not reachable on 127.0.0.1:{port} ({exc})")
            return 2
        try:
            data = await client.call("ping")
        finally:
            await client.close()
        connected = bool(data.get("connector"))
        print(f"boardwise bridge: daemon up on 127.0.0.1:{port}")
        print(
            "  connector: connected"
            if connected
            else "  connector: not connected (is EasyEDA running with the extension?)"
        )
        # Fingerprint only. The daemon never puts the token on the wire, so
        # there is nothing else this line *could* print — which is the point.
        fingerprint = data.get("pairedFingerprint")
        print(
            f"  paired connector: {fingerprint}"
            if fingerprint
            else "  paired connector: none — the next connector to connect will be trusted"
        )
        return 0 if connected else 1

    return asyncio.run(run())


def _cmd_bridge_revoke(args: argparse.Namespace) -> int:
    """Forget the paired connector. The next one re-pairs by itself.

    Deliberately a local file operation, not an action sent to the daemon: the
    moment you most want to revoke is the moment you are least sure what is
    listening, and requiring a healthy daemon to withdraw trust would be
    backwards. The audit record is written by this process for the same reason.
    """
    _, daemon_module, _ = _bridge_modules()
    fingerprint = daemon_module.revoke_connector_token()
    daemon_module.append_audit(
        None,
        action=daemon_module.AUDIT_REVOKE,
        role="cli",
        ok=True,
        fingerprint=fingerprint,
    )
    if fingerprint:
        print(f"boardwise bridge: pairing revoked (was {fingerprint})")
    else:
        print("boardwise bridge: no connector was paired — nothing to revoke")
    print("  the next connector to connect will be trusted as the new one")
    return 0


def _cmd_bridge_screenshot(args: argparse.Namespace) -> int:
    import asyncio
    import base64

    BridgeClient, BridgeError, port, token = _open_cli(args)

    async def run() -> int:
        try:
            client = await BridgeClient.open(
                _bridge_uri(port), token, "cli", client="boardwise-cli"
            )
        except (OSError, BridgeError) as exc:
            print(
                f"boardwise bridge: daemon not reachable on 127.0.0.1:{port} ({exc})",
                file=sys.stderr,
            )
            return 2
        try:
            data = await client.call("export.screenshot", {"fit": bool(args.fit)})
        except BridgeError as exc:
            print(
                f"boardwise bridge: screenshot failed [{exc.code}] {exc.message}",
                file=sys.stderr,
            )
            return 1
        finally:
            await client.close()
        payload = data.get("data") if isinstance(data, dict) else None
        if not payload:
            print("boardwise bridge: connector returned no image", file=sys.stderr)
            return 1
        Path(args.out).write_bytes(base64.b64decode(payload))
        print(f"boardwise bridge: wrote {args.out}")
        return 0

    return asyncio.run(run())


def _cmd_bridge_highlight(args: argparse.Namespace) -> int:
    import asyncio

    BridgeClient, BridgeError, port, token = _open_cli(args)

    async def run() -> int:
        try:
            client = await BridgeClient.open(
                _bridge_uri(port), token, "cli", client="boardwise-cli"
            )
        except (OSError, BridgeError) as exc:
            print(
                f"boardwise bridge: daemon not reachable on 127.0.0.1:{port} ({exc})",
                file=sys.stderr,
            )
            return 2
        try:
            data = await client.call(
                "canvas.highlight",
                {
                    "uuids": list(args.uuids),
                    "color": args.color,
                    "clear": bool(args.clear),
                    "zoom": bool(args.zoom),
                },
            )
        except BridgeError as exc:
            print(
                f"boardwise bridge: highlight failed [{exc.code}] {exc.message}",
                file=sys.stderr,
            )
            return 1
        finally:
            await client.close()
        count = data.get("highlighted") if isinstance(data, dict) else None
        print(
            f"boardwise bridge: highlighted "
            f"{count if count is not None else len(args.uuids)} primitive(s)"
        )
        return 0

    return asyncio.run(run())


def _cmd_draw(args: argparse.Namespace) -> int:
    """Redraw the design through the bridge and diff it (task 006 / task 008a).

    Two design sources. ``--from <golden.epro2>`` replays the golden page's own
    layout (006b). ``--spec <board spec>`` **assembles** the design from block
    templates (008a): the spec is then the judgement source, and ``--golden``
    turns on the double-check that the specification reproduces the golden's
    connectivity — run *before* a single bridge call, because a draw that
    starts from an unverified specification just produces a page nobody can
    trust.
    """
    import asyncio

    from boardwise.engines.draw import DrawAborted, SelfCheckFailed, run_draw

    BridgeClient, BridgeError, port, token = _open_cli(args)

    if not args.spec and not args.from_file:
        print("boardwise draw: give --from <golden.epro2> or --spec <board spec>", file=sys.stderr)
        return 2
    if args.spec and args.from_file:
        print("boardwise draw: --from and --spec are two design sources; give one", file=sys.stderr)
        return 2
    if args.spec and args.solver:
        print(
            "boardwise draw: --solver places parts unrotated, so it cannot lay out "
            "block geometry that carries its own rotations; drop one of the two",
            file=sys.stderr,
        )
        return 2

    applied_overrides = None
    assembly_report: list[str] = []
    if args.spec:
        from boardwise.core.blocks import BlockError, load_board_spec
        from boardwise.engines.assemble import assemble, assembly_lines

        try:
            design = assemble(load_board_spec(args.spec))
        except BlockError as exc:
            print(f"boardwise draw: {args.spec}: {exc}", file=sys.stderr)
            return 2
        golden = design.model
        offsets = design.offsets
        symbol_defs = design.symbol_defs
        page_layout = design.page
        bodies = design.bodies
        assembly_report = assembly_lines(design)
        if not golden.components:
            print(f"boardwise draw: {args.spec} assembled no components", file=sys.stderr)
            return 2
        print(f"assembly from {args.spec}:")
        for line in assembly_report:
            print(line)
        if args.golden:
            code = _double_check_spec(golden, args.golden, args.spec)
            if code:
                return code
    else:
        from boardwise.parsers.schematic import build_pin_offsets, build_schematic_model

        try:
            golden = build_schematic_model(args.from_file)
        except Exception as exc:  # noqa: BLE001 — the CLI must not traceback
            print(f"boardwise draw: golden {args.from_file}: {exc}", file=sys.stderr)
            return 2
        try:
            offsets = build_pin_offsets(args.from_file)
        except Exception as exc:  # noqa: BLE001
            print(f"boardwise draw: pin offsets {args.from_file}: {exc}", file=sys.stderr)
            return 2
        from boardwise.parsers.schematic import collect_symbol_defs

        try:
            all_defs = collect_symbol_defs(args.from_file)
            symbol_defs = {
                des: all_defs[comp.uid]
                for des, comp in golden.components.items()
                if comp.uid in all_defs
            }
        except Exception as exc:  # noqa: BLE001
            print(f"boardwise draw: symbol defs {args.from_file}: {exc}", file=sys.stderr)
            return 2
        if not golden.components:
            print(
                f"boardwise draw: golden {args.from_file} has no components — "
                "is it a schematic project?",
                file=sys.stderr,
            )
            return 2

        # the golden page's own layout (task 006b) — absent means the solver runs
        page_layout, bodies = _golden_layout(args.from_file)

        # Golden corrections ride beside the fixture (§G.3): load the sidecar (if
        # any) so the plan places — and the diff compares against — the corrected
        # truth rather than a value everyone agrees is wrong. In --spec mode the
        # numbers come from the spec instead, and the sidecar is only used by the
        # golden-side double-check.
        from boardwise.core.overrides import load_overrides, sidecar_path_for

        overrides_path = Path(args.overrides) if args.overrides else sidecar_path_for(args.from_file)
        try:
            applied_overrides = load_overrides(overrides_path)
        except ValueError as exc:
            print(f"boardwise draw: {exc}", file=sys.stderr)
            return 2

    async def run() -> int:
        try:
            client = await BridgeClient.open(
                _bridge_uri(port), token, "cli", client="boardwise-cli"
            )
        except (OSError, BridgeError) as exc:
            print(
                f"boardwise draw: daemon not reachable on 127.0.0.1:{port} ({exc})",
                file=sys.stderr,
            )
            return 2
        try:
            result = await run_draw(
                client,
                golden,
                confirm=(lambda: True) if args.yes else _ask_confirm,
                offsets=offsets,
                symbol_defs=symbol_defs,
                page_layout=page_layout,
                bodies=bodies,
                prefer_replay=not args.solver,
                strategy=args.naming,
                overrides=applied_overrides,
            )
        except DrawAborted:
            print("boardwise draw: aborted at the gate; nothing was executed")
            return 2
        except SelfCheckFailed as exc:
            print(
                "boardwise draw: the plan failed its self-check; "
                "nothing was executed (see the report above)",
                file=sys.stderr,
            )
            _ = exc.violations
            return 2
        finally:
            await client.close()

        return _render_draw_result(result, args, assembly_report=assembly_report)

    return asyncio.run(run())


def _double_check_spec(design_model: object, golden_path: str, spec_path: str) -> int:
    """Does the spec netlist reproduce the golden's connectivity? 0 = yes.

    Task 008a work item 5's "双重核对": the assembled specification is compared
    against the golden **before** anything is drawn. This is a gate, not a
    report — a specification that does not reproduce the design it claims to
    describe has nothing worth drawing, and finding that out after the editor
    has been mutated costs a cleanup round.
    """
    from boardwise.core.compare import compare_models
    from boardwise.core.overrides import apply_overrides, load_overrides, sidecar_path_for
    from boardwise.parsers.schematic import build_schematic_model

    try:
        golden = build_schematic_model(golden_path)
    except Exception as exc:  # noqa: BLE001 — the CLI must not traceback
        print(f"boardwise draw: golden {golden_path}: {exc}", file=sys.stderr)
        return 2
    try:
        sidecar = load_overrides(sidecar_path_for(golden_path))
    except ValueError as exc:
        print(f"boardwise draw: {exc}", file=sys.stderr)
        return 2

    override_lines = apply_overrides(golden, sidecar) if sidecar.active else []
    report = compare_models(golden, design_model)
    print(f"double check: spec {spec_path} vs golden {golden_path}")
    for line in override_lines:
        print(f"  golden override: {line}")
    if report.is_empty:
        print(
            "  the specification reproduces the golden — net 0 / pin 0 / "
            "component 0 differences"
        )
        return 0
    print("  THE SPECIFICATION DOES NOT REPRODUCE THE GOLDEN; nothing will be executed:")
    for line in report.render().splitlines():
        print(f"  {line}")
    return 2


def _golden_layout(path: str):
    """The golden page's layout + measured symbol extents, or ``(None, None)``.

    Both are needed for the replay; either being unavailable is not an error —
    the draw flow then falls back to the generic solver and says so.
    """
    from boardwise.parsers.schematic import collect_page_layout, collect_symbol_bodies

    try:
        layout = collect_page_layout(path)
    except Exception as exc:  # noqa: BLE001 — fall back, do not traceback
        print(f"boardwise: golden layout {path}: {exc}", file=sys.stderr)
        layout = None
    try:
        bodies = collect_symbol_bodies(path)
    except Exception as exc:  # noqa: BLE001
        print(f"boardwise: symbol bodies {path}: {exc}", file=sys.stderr)
        bodies = None
    return layout, bodies


def _cmd_lint(args: argparse.Namespace) -> int:
    """Offline lint of the draw plan: no bridge, no editor (task 006b).

    With ``--spec`` the plan is *assembled from block templates* rather than
    replayed from the golden page, which is how task 008a's layout is checked
    without an editor in the loop (work item 3).
    """
    import json as _json

    from boardwise.engines import layout as layout_engine
    from boardwise.engines.generate import strip_dangling_nets
    from boardwise.engines.replay import (
        replay_or_solver,
        sheet_frame_from_bbox,
    )

    # `getattr` for the newer flags: tests drive these commands with a
    # hand-built Namespace, and a missing optional flag must read as absent
    # rather than as an AttributeError (the same tolerance `--naming` gets).
    spec_path = getattr(args, "spec", None)
    from_file = getattr(args, "from_file", None)
    if not spec_path and not from_file:
        print("boardwise lint: give --from <golden.epro2> or --spec <board spec>", file=sys.stderr)
        return 2
    if spec_path and from_file:
        print("boardwise lint: --from and --spec are two plan sources; give one", file=sys.stderr)
        return 2

    naming = getattr(args, "naming", None) or DEFAULT_NAMING_STRATEGY
    assembly_lines_out: list[str] = []

    if spec_path:
        from boardwise.core.blocks import BlockError, load_board_spec
        from boardwise.engines.assemble import assemble, assembly_lines

        try:
            design = assemble(load_board_spec(spec_path))
        except BlockError as exc:
            print(f"boardwise lint: {spec_path}: {exc}", file=sys.stderr)
            return 2
        model = strip_dangling_nets(design.model)
        if not model.components:
            print(f"boardwise lint: {spec_path} assembled no components", file=sys.stderr)
            return 2
        # The spec declares its page; a board without one gets the golden
        # fixture's own A4 numbers only if it says so — never a nominal guess.
        width = float(design.page.sheet_attrs.get("Width") or 0.0)
        height = float(design.page.sheet_attrs.get("Height") or 0.0)
        if width > 0 and height > 0:
            frame = sheet_frame_from_bbox(
                layout_engine.Rect(0.0, 0.0, width, height), provenance="spec-declared"
            )
        else:
            frame = None
        plan, source = replay_or_solver(
            model, design.page, frame, design.offsets,
            bodies=design.bodies, strategy=naming,
        )
        assembly_lines_out = assembly_lines(design)
    else:
        from boardwise.parsers.schematic import (
            build_pin_offsets,
            build_schematic_model,
            collect_page_layout,
        )

        try:
            golden = build_schematic_model(from_file)
            offsets = build_pin_offsets(from_file)
            page = collect_page_layout(from_file)
        except Exception as exc:  # noqa: BLE001 — the CLI must not traceback
            print(f"boardwise lint: {from_file}: {exc}", file=sys.stderr)
            return 2
        golden = strip_dangling_nets(golden)
        if not golden.components:
            print(
                f"boardwise lint: {from_file} has no components — is it a schematic project?",
                file=sys.stderr,
            )
            return 2

        if args.plan == "solver":
            plan, source = replay_or_solver(
                golden, None, None, offsets, prefer_replay=False, strategy=naming
            )
        else:
            # No editor here, so the frame comes from the golden page's *declared*
            # size (a measurement of the source, not a nominal guess); the draw
            # flow itself measures the live page instead.
            frame = sheet_frame_from_bbox(
                layout_engine.Rect(
                    0.0,
                    0.0,
                    float(page.sheet_attrs.get("Width") or 0.0),
                    float(page.sheet_attrs.get("Height") or 0.0),
                ),
                provenance="declared-size",
            )
            from boardwise.parsers.schematic import collect_symbol_bodies

            plan, source = replay_or_solver(
                golden, page, frame, offsets,
                bodies=collect_symbol_bodies(from_file),
                strategy=naming,
            )

    lines = layout_engine.lint_report(plan.violations)
    if args.json:
        print(
            _json.dumps(
                {
                    "source": source,
                    "naming": plan.naming_strategy,
                    "components": len(plan.placements),
                    "wires": len(plan.wires),
                    "net_names": len(plan.net_names),
                    "decorative_names": len(plan.decorative_names),
                    "nc_pins": len(plan.nc_pins),
                    "notes": plan.notes,
                    "violations": [
                        {"code": v.code, "subject": v.subject, "detail": v.detail}
                        for v in plan.violations
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        for line in assembly_lines_out:
            print(line)
        print(f"plan source: {source}")
        print(f"naming: {plan.naming_strategy}")
        if plan.decorative_names:
            print(
                f"  note: {len(plan.decorative_names)} signal name(s) are drawn as TEXT "
                "(decorative, not native net labels)"
            )
        print(plan.summary())
        for note in plan.notes:
            print(f"  note: {note}")
        for line in lines:
            print(line)
    return 1 if plan.violations else 0


def _ask_confirm() -> bool:
    try:
        return input("execute this plan? [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _render_draw_result(
    result: object, args: argparse.Namespace, assembly_report: list[str] | None = None
) -> int:
    """The acceptance report: what ran, what failed, what differs."""
    import base64

    if assembly_report:
        # The design source belongs at the top of the report: a reader has to
        # know whether this page was replayed from the golden or assembled from
        # a specification before reading a single difference line.
        print(f"design source: spec {args.spec}")
        for line in assembly_report:
            print(line)
    print(f"plan source: {result.plan_source or '(unknown)'}")
    if result.naming_strategy:
        line = f"naming: {result.naming_strategy}"
        decorative = result.plan.decorative_names
        if decorative:
            line += (
                f" — {len(decorative)} signal name(s) drawn as TEXT "
                "(decorative, NOT native net labels)"
            )
        elif not [s for s in result.plan.net_names if s.kind in ("text", "label", "port")]:
            line += " — no signal name primitive; names ride on the wires"
        print(line)
    if result.frame is not None:
        print(f"sheet frame: {result.frame.render()}")
    if result.candidate_source:
        print(f"candidate source: {result.candidate_source}")
    else:
        print("candidate source: (none — the diff did not run)")
    probe = result.netlist_probe
    if isinstance(probe, dict):
        # The netlist export is flaky on API-placed pages (measured); how it
        # answered belongs in the report, not in a footnote.
        if isinstance(probe.get("text"), str):
            print(f"netlist probe: {probe.get('source')} ({probe.get('size')} chars)")
        else:
            print(f"netlist probe: no text — keys={sorted(probe.keys())}")
    if result.netlist_census:
        # Only taken when the netlist export failed. This is what tells "a
        # primitive poisoned the exporter" apart from "our parser is wrong".
        rendered = ", ".join(f"{k}={v}" for k, v in sorted(result.netlist_census.items()))
        print(f"page census (netlist failed): {rendered}")
    placement = result.placement_report
    if placement is None:
        print("placement check: NOT RUN (no readback — the placements are unverified)")
    else:
        drifted = [c.designator for c in placement.drifted]
        print(
            f"placement check: {len(placement.checks)} parts, "
            f"{len(drifted)} drifted with the library version, "
            f"{len(placement.unmappable)} unmappable"
        )
        if drifted:
            print(
                "  ! pin numbering drifted with the library version — "
                "wire endpoints are replayed at the golden pin tips and the "
                "diff is compared by pin name for:"
            )
            print(f"    {', '.join(drifted)}")
        if placement.unmappable:
            print("  ✗ unmappable parts (the draw stops before any wire):")
            for check in placement.unmappable:
                print(f"    {check.designator}: {check.detail}")
        if placement.orphan_pins:
            print("  ! pins on the placed page that no golden pin addresses:")
            for des, pins in sorted(placement.orphan_pins.items()):
                print(f"    {des}: {', '.join(pins)}")
    failed = result.failures
    if failed:
        print(f"\nfailed actions ({len(failed)}):")
        for record in failed:
            print(f"  ✗ {record.action}: {record.summary}")
            if record.detail:
                print(f"      {record.detail}")
    if result.missing_pins:
        print(f"\npins the editor never exposed ({len(result.missing_pins)}):")
        for net, des, pin in result.missing_pins:
            print(f"  {des}.{pin} (net {net})")
    if result.enrichment_notes:
        print(f"\nlibrary enrichment ({len(result.enrichment_notes)}, not drawing errors):")
        for note in result.enrichment_notes:
            print(f"  · {note}")
    print(f"\nexecuted {len(result.records)} bridge actions, "
          f"{len(failed)} failed")

    report = result.comparison
    exit_code = 1
    if report is None:
        print("\ndiff: NOT RUN (no candidate model)")
    else:
        print(f"\ndiff vs golden ({result.candidate_source}):")
        if report.is_empty:
            print("no differences — designs match")
            exit_code = 0
        else:
            print(report.render())
    if result.render_b64 and args.render:
        Path(args.render).write_bytes(base64.b64decode(result.render_b64))
        print(f"\nrender (acceptance image): {args.render}")
    if result.render_b64 and not args.render:
        print("\nrender: produced but no --render path given; not written")
    if result.screenshot_b64 and args.screenshot:
        Path(args.screenshot).write_bytes(base64.b64decode(result.screenshot_b64))
        print(f"screenshot (diagnostic only): {args.screenshot}")
    return exit_code


def _render_parts_result(result: object, qty: int, query: str) -> None:
    """The human view: what was asked, what the gate said, what came back."""
    source = "jlcpcb.com (online)" if result.online else "blocklib/parts.json (offline)"
    print(f'boardwise parts select: query "{query}"  source={source}  qty={qty}')
    if result.gated:
        if result.resistance.ohms is None:
            print("resistance gate: the query names a resistance that is not one number — failing closed")
        else:
            print(f"resistance gate: {result.resistance.ohms} Ω, from the query")
    if result.unmapped_words:
        print(
            "  note: not in the footprint vocabulary table (no mapping applied): "
            + ", ".join(result.unmapped_words)
        )
    if not result.candidates:
        print("  no candidate")
        for note in result.notes:
            print(f"  note: {note}")
        return
    print(f"  {'#':>2} {'LCSC':<10} {'type':<7} {'key / MPN':<34} {'stock':>7}  evidence")
    for index, candidate in enumerate(result.candidates[:10], 1):
        if candidate.source == "jlcpcb.com":
            tag = "BASIC" if candidate.basic else "ext"
            label = f"{candidate.mpn or candidate.lcsc}"
            stock = str(candidate.stock)
        else:
            tag = {True: "BASIC", False: "ext", None: "?"}[candidate.basic]
            label = candidate.key
            stock = "-"
        evidence = ""
        if candidate.resistance:
            evidence = (
                f"R={candidate.resistance['ohms']}Ω ({candidate.resistance['raw']}"
                f" from {candidate.resistance['from']})"
            )
        print(
            f"  {index:>2} {candidate.lcsc:<10} {tag:<7} {label[:34]:<34} {stock:>7}  {evidence}"
        )
    for note in result.notes:
        print(f"  note: {note}")


def _entry_from_resolution(resolved: object, candidate: object) -> object:
    """The library entry a resolved online pick becomes.

    Provenance is ``catalog-select``, not ``board-extract``: nobody has built
    this part on a board yet, and the difference is exactly the kind of thing
    that must not be blurred. The footprint name comes from the library's own
    answer, which is why it is marked verified only when that answer arrived.
    """
    from boardwise.core.parts import PartEntry, PartProvenance

    return PartEntry(
        key=f"catalog.{resolved.lcsc.lower()}",
        mpn=candidate.mpn,
        lcsc=resolved.lcsc,
        manufacturer=candidate.brand,
        deviceUuid=resolved.deviceUuid,
        libraryUuid=resolved.libraryUuid,
        footprint_name=resolved.footprint_name,
        footprint_name_verified=True if resolved.footprint_name else None,
        params={"Description": candidate.description} if candidate.description else {},
        basic=candidate.basic,
        provenance=PartProvenance(
            kind="catalog-select",
            source="jlcpcb.com",
            designators=[],
            note=(
                f"selected online at qty {getattr(candidate, 'stock', 0)}-aware stock "
                f"{candidate.stock}, unit price {candidate.unit_price}; identity "
                f"resolved by lib.device.search on the exact C-number"
            ),
        ),
    )


def _cmd_bom_export(args: argparse.Namespace) -> int:
    """Export the BOM a spec implies (task 008c, item 1).

    Exit 0 when every placed component resolved to a shelf entry, 1 when the
    bill is incomplete or self-contradictory (the open questions are printed in
    either case — a partial BOM that does not say what is missing is the
    failure mode this command exists to avoid), 2 for bad input.
    """
    import json as _json

    from boardwise.core.blocks import BlockError, load_board_spec
    from boardwise.engines.bom import (
        BomError,
        assemble_for_bom,
        build_bom,
        load_library,
        write_csv,
    )

    try:
        spec = load_board_spec(args.spec)
    except BlockError as exc:
        print(f"boardwise bom export: {args.spec}: {exc}", file=sys.stderr)
        return 2
    try:
        library = load_library(args.library)
    except BomError as exc:
        print(f"boardwise bom export: {exc}", file=sys.stderr)
        return 2
    try:
        # The assembler is the same gate the draw chain runs: a spec that cannot
        # be composed has no trustworthy part list either.
        assemble_for_bom(spec)
    except BlockError as exc:
        print(f"boardwise bom export: {args.spec} cannot be assembled: {exc}",
              file=sys.stderr)
        return 2

    report = build_bom(spec, library)
    if args.json:
        print(_json.dumps(report.as_json(), indent=2, ensure_ascii=False))
    else:
        for line in report.render():
            print(line)
    if args.out:
        written = write_csv(report, args.out)
        print(f"written: {written} ({len(report.rows)} line(s))")
    return 0 if report.ok else 1


def _cmd_pintable_check(args: argparse.Namespace) -> int:
    """Check a firmware pin table (task 008c, item 2).

    Exit 0 when nothing blocks, 1 when a gate found a defect, 2 for bad
    input. Open questions are printed in every case and never block: a pin the
    schematic wires and the firmware has not used yet is a question for 岳翔宇,
    not a reason to stop.
    """
    import json as _json

    from boardwise.core.blocks import BlockError, load_board_spec
    from boardwise.core.pintable import (
        PinTableError,
        cross_check,
        load_ioc,
        load_pin_table,
    )
    from boardwise.engines.pintable_check import PinFinding, check_pin_table

    try:
        pin_table = load_pin_table(args.table)
    except PinTableError as exc:
        print(f"boardwise pintable check: {args.table}: {exc}", file=sys.stderr)
        return 2

    spec = None
    block_id = args.block
    if args.spec:
        try:
            spec = load_board_spec(args.spec)
        except BlockError as exc:
            print(f"boardwise pintable check: {args.spec}: {exc}", file=sys.stderr)
            return 2
        if not block_id:
            # Not guessed: the MCU block is the one whose name says so, and a
            # spec with zero or two such blocks is told to name it explicitly.
            named = [b.id for b in spec.blocks if b.id == "mcu"]
            if len(named) != 1:
                print(
                    f"boardwise pintable check: {args.spec} has "
                    f"{len(named)} block(s) named 'mcu'; say which one with "
                    "--block (it has "
                    f"{', '.join(b.id for b in spec.blocks)})",
                    file=sys.stderr,
                )
                return 2
            block_id = named[0]

    report = check_pin_table(pin_table, spec=spec, mcu_block_id=block_id)

    if args.ioc:
        try:
            project = load_ioc(args.ioc)
        except PinTableError as exc:
            print(f"boardwise pintable check: {args.ioc}: {exc}", file=sys.stderr)
            return 2
        for conflict in cross_check(pin_table, project):
            report.findings.append(
                PinFinding(
                    kind="open-question",
                    rule="ioc-cross-check",
                    message=conflict.detail,
                    evidence=[
                        f"{conflict.port_pin}: firmware={conflict.firmware!r} "
                        f"ioc={conflict.ioc!r}"
                    ],
                )
            )

    if args.json:
        print(_json.dumps(report.as_json(), indent=2, ensure_ascii=False))
    else:
        for line in report.render():
            print(line)
    return 0 if report.ok else 1


def _cmd_validate(args: argparse.Namespace) -> int:
    """Run the four gates (task 008c, item 4).

    Exit 0 when nothing blocks, 1 when a violation or an undecidable result
    does, 2 for bad input. Undecidable blocks because "we cannot tell" and "it
    is fine" must never look the same in a report somebody has to act on.
    """
    import json as _json

    from boardwise.core.blocks import BlockError, load_board_spec
    from boardwise.core.parts import PartError, load_parts
    from boardwise.core.pintable import PinTableError, load_pin_table
    from boardwise.core.portmeta import PortMetaError, load_port_meta
    from boardwise.engines.validate_spec import validate_spec

    port_meta = None
    if args.port_meta and Path(args.port_meta).is_file():
        try:
            port_meta = load_port_meta(args.port_meta)
        except PortMetaError as exc:
            print(f"boardwise validate: {exc}", file=sys.stderr)
            return 2

    try:
        spec = load_board_spec(args.spec, port_meta=port_meta)
    except BlockError as exc:
        print(f"boardwise validate: {args.spec}: {exc}", file=sys.stderr)
        return 2

    table = None
    if args.table:
        try:
            table = load_pin_table(args.table)
        except PinTableError as exc:
            print(f"boardwise validate: {args.table}: {exc}", file=sys.stderr)
            return 2

    library = None
    if args.library:
        try:
            library = load_parts(args.library)
        except PartError as exc:
            print(f"boardwise validate: {args.library}: {exc}", file=sys.stderr)
            return 2

    report = validate_spec(
        spec,
        table=table,
        library=library,
        target=args.target,
        root=args.root,
        mcu_block_id=args.block,
        mcu_component=args.mcu_component,
    )
    if args.json:
        print(_json.dumps(report.as_json(), indent=2, ensure_ascii=False))
    else:
        for line in report.render():
            print(line)
        if not args.target:
            print(
                "note: no --target was given, so the closed-book gate could not "
                "run (this is not a pass). Name the board being generated — "
                "every alias of it.",
                file=sys.stderr,
            )
    return 0 if report.ok else 1


def _cmd_parts_select(args: argparse.Namespace) -> int:
    """Part selection (task 008b, work item 3): exit 0 ok / 1 gated miss / 2 bad input."""
    import asyncio
    import json

    from boardwise.core.parts import PartError, load_parts
    from boardwise.engines.select import resolve_by_lcsc, select

    try:
        library = load_parts(args.library)
    except PartError as exc:
        print(f"boardwise parts select: {exc}", file=sys.stderr)
        return 2

    catalog = None
    if args.online:
        # The client is built with its default (network) fetcher only here, so
        # that importing the pipeline in a test never loads a network stack.
        from boardwise.engines.catalog import CatalogClient, CatalogError

        catalog = CatalogClient()
        try:
            result = select(args.query, library, qty=args.qty, online=True, client=catalog)
        except CatalogError as exc:
            print(f"boardwise parts select: {exc}", file=sys.stderr)
            return 2
    else:
        result = select(args.query, library, qty=args.qty, online=False)

    if args.json:
        print(json.dumps(result.as_json(), indent=2, ensure_ascii=False))
    else:
        _render_parts_result(result, args.qty, args.query)

    if args.resolve:
        if not result.candidates:
            print("boardwise parts select: nothing to resolve", file=sys.stderr)
            return result.exit_code
        pick = result.candidates[0]
        if not pick.lcsc:
            print("boardwise parts select: the top pick carries no C-number", file=sys.stderr)
            return 2

        BridgeClient, BridgeError, port, token = _open_cli(args)

        async def run() -> int:
            try:
                client = await BridgeClient.open(
                    _bridge_uri(port), token, "cli", client="boardwise-cli"
                )
            except (OSError, BridgeError) as exc:
                print(
                    f"boardwise parts select: daemon not reachable on "
                    f"127.0.0.1:{port} ({exc})",
                    file=sys.stderr,
                )
                return 2
            try:
                resolved = await resolve_by_lcsc(client, pick.lcsc)
            finally:
                await client.close()
            print(f"resolve {pick.lcsc}: {'ok' if resolved.resolved else 'refused'}")
            if resolved.resolved:
                print(
                    f"  deviceUuid={resolved.deviceUuid} libraryUuid={resolved.libraryUuid} "
                    f"footprint={resolved.footprint_name or '(not returned)'} "
                    f"via {resolved.matched_key} ({resolved.items_seen} item(s) seen)"
                )
            elif resolved.reason:
                print(f"  {resolved.reason}", file=sys.stderr)
            if args.write:
                if not resolved.resolved:
                    print(
                        "boardwise parts select: not writing an unresolved identity",
                        file=sys.stderr,
                    )
                    return 2
                from boardwise.core.parts import save_parts

                entry = _entry_from_resolution(resolved, pick)
                # The guard is by **C-number**, not by key: an entry harvested
                # from a board is the stronger claim (somebody built it), and
                # rewriting it from a catalog row would quietly downgrade
                # `board-extract` to `catalog-select`. One part is one entry.
                existing = library.by_lcsc().get(entry.lcsc)
                if existing is not None:
                    print(
                        f"  {existing.key} already curates {entry.lcsc} "
                        f"({existing.provenance.kind}); nothing written"
                    )
                    return 0
                library.parts.append(entry)
                library.parts.sort(key=lambda p: p.key)
                save_parts(library, args.library)
                print(f"  written: {args.library} now holds {len(library.parts)} entries")
            return 0 if resolved.resolved else 1

        return asyncio.run(run())

    return result.exit_code


def _connector_artifacts() -> tuple[Path, Path]:
    """``(bundle, extension.json)`` paths of the in-repo connector build.

    Resolved from this file's location (``src/boardwise/cli.py`` → repo root),
    so the defaults work from any working directory as long as the checkout is
    intact. This CLI is developed and run from the repo; an installed wheel
    without the ``connector/`` tree simply fails the existence check below.
    """
    root = Path(__file__).resolve().parents[2]
    return root / "connector" / "dist" / "index.js", root / "connector" / "extension.json"


def _update_connector_payload(
    bundle_path: Path, extension_json: Path, version: str | None
) -> tuple[dict[str, str], int]:
    """Build the ``sys.self_update`` params: ``({bundleB64, version}, byte_count)``.

    Pure file work, separated from the wire so the encoding and the defaults
    are unit-testable without a daemon. Raises :class:`ValueError` on anything
    unreadable — the caller renders it as exit 2.
    """
    try:
        bundle = bundle_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"bundle {bundle_path}: {exc}") from exc
    if not bundle:
        raise ValueError(f"bundle {bundle_path} is empty — run `npm run build` in connector/")
    if version is None:
        import json

        try:
            manifest = json.loads(extension_json.read_text(encoding="utf-8"))
            version = manifest["version"]
        except (OSError, ValueError, KeyError) as exc:
            raise ValueError(
                f"cannot read the version from {extension_json} ({exc}); pass --version"
            ) from exc
    import base64

    return {"bundleB64": base64.b64encode(bundle).decode("ascii"), "version": version}, len(bundle)


def _cmd_bridge_update_connector(args: argparse.Namespace) -> int:
    """Push a freshly built bundle into the running editor via ``sys.self_update``.

    The write lands in the editor's extension IndexedDB and the connector then
    reloads its own page — the whole point is skipping uninstall → import →
    restart. The confirmation exists because the reload discards unsaved
    editor state; `--yes` is the scripting escape hatch, same convention as
    `draw` and `bridge call`.
    """
    import asyncio

    BridgeClient, BridgeError, port, token = _open_cli(args)

    default_bundle, extension_json = _connector_artifacts()
    bundle_path = Path(args.bundle) if args.bundle else default_bundle
    try:
        params, byte_count = _update_connector_payload(
            bundle_path, extension_json, args.version
        )
    except ValueError as exc:
        print(f"boardwise bridge update-connector: {exc}", file=sys.stderr)
        return 2

    # The request has to fit in one daemon frame. The daemon caps inbound
    # frames at MAX_FRAME_BYTES (32 MiB); the bundle is ~0.1 MB as base64, so
    # this guard should never fire — it exists so that a future bundle growth
    # reports "raise the limit" instead of dying as a truncated socket.
    _, daemon_module, _ = _bridge_modules()
    frame_estimate = len(params["bundleB64"]) + 4096
    if frame_estimate > daemon_module.MAX_FRAME_BYTES:
        print(
            f"boardwise bridge update-connector: the base64 payload "
            f"({frame_estimate} bytes) exceeds the daemon's frame cap "
            f"({daemon_module.MAX_FRAME_BYTES}); raise MAX_FRAME_BYTES in "
            "src/boardwise/bridge/daemon.py first",
            file=sys.stderr,
        )
        return 2

    print(
        f"boardwise bridge update-connector: {bundle_path} "
        f"({byte_count} bytes, {len(params['bundleB64'])} as base64) "
        f"-> version {params['version']}"
    )
    if not args.yes:
        if not sys.stdin.isatty():
            print(
                "boardwise bridge update-connector: confirmation needed and "
                "stdin is not a terminal; re-run with --yes if intended",
                file=sys.stderr,
            )
            return 2
        print(
            "  the editor page will RELOAD right after the write — "
            "unsaved changes in the editor will be lost",
            file=sys.stderr,
        )
        try:
            answer = input("update the connector and reload the editor? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            print("", file=sys.stderr)
            return 2
        if answer.strip().lower() not in ("y", "yes"):
            print("boardwise bridge update-connector: aborted; nothing was sent")
            return 2

    async def run() -> int:
        try:
            client = await BridgeClient.open(
                _bridge_uri(port), token, "cli", client="boardwise-cli"
            )
        except (OSError, BridgeError) as exc:
            print(
                f"boardwise bridge: daemon not reachable on 127.0.0.1:{port} ({exc})",
                file=sys.stderr,
            )
            return 2
        try:
            data = await client.call("sys.self_update", params)
        except BridgeError as exc:
            print(
                f"boardwise bridge update-connector failed [{exc.code}] {exc.message}",
                file=sys.stderr,
            )
            return 1
        finally:
            await client.close()
        print(
            f"  ok: {data.get('oldVersion')} -> {data.get('newVersion')} "
            f"({data.get('bytes')} bytes written to {data.get('database')})"
        )
        print(
            "  the editor page is reloading now; the new build should "
            "reconnect within seconds — verify with `boardwise bridge status` "
            "or the About… menu (version line)"
        )
        return 0

    return asyncio.run(run())


def _cmd_bridge_call(args: argparse.Namespace) -> int:
    """Generic action probe (006): one call, the raw payload, exit 0/1/2.

    Also the scripting surface for `create` actions (006c): the daemon refuses
    those without an explicit confirmation, and this command is where a human
    gets asked. `--yes` is the escape hatch for scripts, and it is deliberately
    a flag rather than a prompt — a non-interactive caller should have to say
    so out loud.
    """
    import asyncio
    import json

    from .bridge.protocol import ErrorCodes

    BridgeClient, BridgeError, port, token = _open_cli(args)
    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as exc:
        print(f"boardwise bridge call: --params is not JSON ({exc})", file=sys.stderr)
        return 2
    if not isinstance(params, dict):
        print(
            "boardwise bridge call: --params must be a JSON object", file=sys.stderr
        )
        return 2
    if args.yes:
        params["confirm"] = True

    def _print_error(action: str, exc: "BridgeError") -> None:
        print(f"boardwise bridge call: {action} failed [{exc.code}] {exc.message}",
              file=sys.stderr)

    def _ask(action: str, message: str) -> bool:
        """Ask the human, but only when there is a human to ask.

        A piped stdin is not consent: returning False there means the caller
        learns it must pass --yes, instead of a prompt nobody sees silently
        defaulting to yes.
        """
        if not sys.stdin.isatty():
            print(
                f"boardwise bridge call: {action} needs confirmation and stdin is "
                "not a terminal; re-run with --yes if that is intended",
                file=sys.stderr,
            )
            return False
        print(f"\n{message}", file=sys.stderr)
        try:
            answer = input(f"call {action}? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("", file=sys.stderr)
            return False
        return answer in ("y", "yes")

    async def run() -> int:
        try:
            client = await BridgeClient.open(
                _bridge_uri(port), token, "cli", client="boardwise-cli"
            )
        except (OSError, BridgeError) as exc:
            print(
                f"boardwise bridge: daemon not reachable on 127.0.0.1:{port} ({exc})",
                file=sys.stderr,
            )
            return 2
        try:
            try:
                data = await client.call(args.action, params)
            except BridgeError as exc:
                if (
                    exc.code == ErrorCodes.CONFIRMATION_REQUIRED
                    and params.get("confirm") is not True
                    and _ask(args.action, exc.message)
                ):
                    params["confirm"] = True
                    data = await client.call(args.action, params)
                else:
                    raise
        except BridgeError as exc:
            _print_error(args.action, exc)
            # A connector-side unexpected throw arrives with the name and the
            # top of its stack in `detail` (transport.ts). Printing it is the
            # difference between "the read broke" and "the read broke *here*".
            if getattr(exc, "detail", None) is not None:
                detail = exc.detail
                if isinstance(detail, dict):
                    for key in ("errorName", "errorMessage", "stack"):
                        if detail.get(key):
                            print(f"    {key}: {detail[key]}", file=sys.stderr)
                else:
                    print(f"    detail: {detail}", file=sys.stderr)
            return 1
        finally:
            await client.close()
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    return asyncio.run(run())


BRIDGE_COMMANDS = {
    "start": _cmd_bridge_start,
    "status": _cmd_bridge_status,
    "revoke": _cmd_bridge_revoke,
    "screenshot": _cmd_bridge_screenshot,
    "call": _cmd_bridge_call,
    "highlight": _cmd_bridge_highlight,
    "update-connector": _cmd_bridge_update_connector,
}

PARTS_COMMANDS = {
    "select": _cmd_parts_select,
}

BOM_COMMANDS = {
    "export": _cmd_bom_export,
}

PINTABLE_COMMANDS = {
    "check": _cmd_pintable_check,
}


def main(argv: list[str] | None = None) -> int:
    # Windows pipes default stdio to the locale codepage (e.g. cp936), which
    # mangles any non-ASCII output (em-dashes, Chinese part names in evidence).
    # This CLI is UTF-8 end to end; reconfigure is best-effort for odd streams.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    if args.command == "review":
        return _cmd_review(args)
    if args.command == "compare":
        return _cmd_compare(args)
    if args.command == "draw":
        return _cmd_draw(args)
    if args.command == "lint":
        return _cmd_lint(args)
    if args.command == "parts":
        return PARTS_COMMANDS[args.parts_command](args)
    if args.command == "bom":
        return BOM_COMMANDS[args.bom_command](args)
    if args.command == "pintable":
        return PINTABLE_COMMANDS[args.pintable_command](args)
    if args.command == "validate":
        return _cmd_validate(args)
    if args.command == "bridge":
        return BRIDGE_COMMANDS[args.bridge_command](args)
    return 2  # unreachable: subparsers are required


if __name__ == "__main__":
    sys.exit(main())
