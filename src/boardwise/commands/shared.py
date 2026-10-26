"""Shared CLI parser registration and runtime dispatch (540B6).

Only command-surface assembly lives here. Transport, public-contract and model
judgements stay in their existing modules and handlers. Assembly supplies every
handler and the two parser callbacks at call time; this module never imports cli.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from typing import Any


def register_bridge_parser(sub: Any, *, help_epilog: Callable[[], str]) -> None:
    """Register bridge using the assembly-owned live help renderer."""
    bridge = sub.add_parser(
        "bridge",
        help="Live channel to a running EasyEDA (daemon + editor extension).",
        description=(
            "Live channel to a running EasyEDA Pro: a loopback daemon plus an "
            "editor extension. Actions owned by 'daemon' are answered locally; "
            "'connector' actions are forwarded into the editor."
        ),
        epilog=help_epilog(),
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
    fab = bridge_sub.add_parser(
        "export-fab",
        help=(
            "Export the fab bundle (Gerber + pick-and-place + BOM + manifest.json) "
            "into a directory. 012v2 §六."
        ),
        description=(
            "Calls `export.fab` and writes what comes back into a directory: the "
            "three fab files plus a manifest.json recording what they are, where "
            "they were meant to go and what was verified. The connector cannot "
            "write to a path itself — the declared SYS_FileSystem.saveFile takes no "
            "directory — so the bytes arrive as base64 and this command is the "
            "writer. Exit 0 only when the whole bundle landed."
        ),
    )
    fab.add_argument("--out", required=True, help="Directory to write into (created if missing).")
    fab.add_argument("--pcb", default=None, help="PCB uuid to export (default: the focused board).")
    fab.add_argument("--vendor", default="generic", help="Vendor preset (default: generic).")
    fab.add_argument(
        "--gerber", default=None,
        help=(
            "JSON object of gerber overrides: fileName, colorSilkscreen, unit, "
            "digitalFormat, other, layers, objects."
        ),
    )
    fab.add_argument("--bom-template", default=None, help="Saved BOM template name.")
    fab.add_argument(
        "--timeout-ms", type=int, default=None,
        help="Per-file deadline for the editor's export (200..600000, default 60000).",
    )
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
        "--read-only", action="store_true",
        help=(
            "Refuse any action whose catalogue risk is not `read`, before the "
            "daemon is contacted or started: write, create, dangerous and "
            "unknown names all fail without forwarding anything. The DSH "
            "boardwise_bridge tool always sets it."
        ),
    )
    call.add_argument(
        "--project", default=None, metavar="NAME_OR_UUID",
        help=(
            "Route the call to the editor window that has this project open, "
            "named by project name or uuid. Required as soon as more than one "
            "window is connected: without it the daemon answers "
            "WINDOW_UNSPECIFIED and lists the windows rather than guessing."
        ),
    )
    call.add_argument(
        "--instance", default=None, metavar="INSTANCE_ID",
        help=(
            "Route the call to one editor window by the instance id it "
            "announced (the windowKey `bridge status` prints). The exact form of "
            "`--project` for a window that cannot be named by a project — e.g. "
            "right after the editor restarted and no window can read one yet. "
            "Given together with --project, the instance decides."
        ),
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
        help=(
            "Version string to store in the record (default: read from "
            "connector/package.json). It is a **label**, not the version a "
            "connector announces: what a connector announces is the string baked "
            "into its bundle at build time (`build.mjs` inlines package.json's "
            "version), so a value that differs from connector/package.json is "
            "refused (exit 2, nothing written) — the read-back could never verify "
            "it. Blank (or an empty `\"$VAR\"`) counts as not given. To tell two "
            "builds apart, bump connector/package.json **and** connector/"
            "extension.json, rebuild, and point `--bundle` at that build."
        ),
    )
    update.add_argument(
        "--yes", action="store_true",
        help="Skip the confirmation prompt (the editor page WILL reload).",
    )
    update.add_argument(
        "--no-verify", action="store_true",
        help=(
            "Return as soon as the daemon accepted the write, without waiting "
            "for the reloaded connector to report its version (the pre-020 "
            "behaviour: exit 0 even if the old build is still answering)."
        ),
    )
    update.add_argument(
        "--instance", default=None, metavar="INSTANCE_ID",
        help=(
            "Update one named editor window (the windowKey `bridge status` "
            "prints) instead of whichever window the daemon would route to. The "
            "only way to hot-update a window while several are connected and "
            "none can be named by a project. The read-back then waits for the "
            "window to come back announcing the stored version."
        ),
    )
    update.add_argument(
        "--all", action="store_true",
        help=(
            "Update **every** online editor window (030): the bundle is written "
            "per storage record and each window is reloaded and verified on its "
            "own line. Windows of one editor profile share an IndexedDB record, "
            "so the record changes once however many windows write into it, and "
            "every window still reloads (the write and the reload are one action; "
            "`--no-reload` is the frame-level opt-out from the reload half); with "
            "`--no-reload` **each online window needs its own menu click** — the "
            "host re-evaluates an extension per window, so writing the shared "
            "record does not wake the windows you did not click in (R4 measured). "
            "Every window's unsaved state is lost — including windows you did not "
            "name."
        ),
    )
    update.add_argument(
        "--no-reload", action="store_true",
        help=(
            "Write the bundle into the editor's extension storage and stop there: "
            "**no reload is dispatched**, so nothing is activated and no unsaved "
            "editor state is lost. The stored build takes over when EasyEDA next "
            "re-evaluates the extension — click the boardwise menu once per window "
            "(528A). Exit 0 means 'written', and explicitly not 'running'; there is "
            "no window-table read-back to wait for. **The running build must be "
            "528A or later for this to hold**: a build older than 528A does not "
            "know `reload: false` and reloads the page anyway — the command detects "
            "that from the reply's `reloadInMs` and says so (its exit code stays 0, "
            "the write did land). The first `--no-reload` against an old editor is "
            "therefore not reload-free: update once by the default route first. "
            "Without this flag the write still schedules the reload, exactly as it "
            "did before."
        ),
    )
    bridge.add_argument(
        "--port", type=int, default=None, help="Daemon port (default 61190)."
    )


def register_doctor_parser(
    sub: Any, *, editor_api_floor: tuple[int, ...]
) -> None:
    """Register doctor with the assembly-owned editor floor."""
    # Spelled from the constant, never typed out again: the floor moves in one
    # place, or `--help` starts quoting a version doctor no longer asks for.
    floor_text = ".".join(str(part) for part in editor_api_floor)
    doctor = sub.add_parser(
        "doctor",
        help="Check that this installation can do anything (daemon · extension · versions · project).",
        description=(
            "Seven checks in one run: the daemon answers ping (there is no HTTP "
            "/health — the daemon is a WebSocket server), the extension's "
            "WebSocket is registered, five methods the harness depends on answer "
            "`typeof === function` (sys.probe), the running daemon version matches "
            "this install, the connector build in the editor matches the repo, the "
            f"editor is ≥ {floor_text}, and the focused project is readable. Green exits "
            "0; anything else exits 1 with one fix per failing line. Built for the "
            "unplugged case: no daemon, no extension and an old editor are all "
            "reported, never crashed on."
        ),
    )
    doctor.add_argument(
        "--json", dest="json_path", metavar="PATH", help="Write the machine-readable report."
    )
    doctor.add_argument(
        "--port", type=int, default=None, help="Daemon port (default 61190)."
    )
    # Same two hints `bridge call` takes, and for the same reason (023 §3.5):
    # with several editor windows connected the daemon refuses to guess which one
    # a call is about, so four of doctor's checks can only answer "not verified"
    # unless it can name a window. Measured 2026-09-23 with three windows open:
    # doctor read 4/8 purely because it had no way to say which window to ask.
    doctor.add_argument(
        "--project", default=None, metavar="NAME_OR_UUID",
        help="Which editor window the online checks should ask (023 routing hint).",
    )
    doctor.add_argument(
        "--instance", default=None, metavar="INSTANCE_ID",
        help="The same choice by window key, for a window that cannot name a project.",
    )


def register_compare_parser(sub: Any) -> None:
    """Register the historical `compare` command surface."""
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


def register_persistence_parser(sub: Any) -> None:
    """Register the historical `persistence` command surface."""
    persist = sub.add_parser(
        "persistence",
        help=(
            "Snapshot the live page and compare it across a real close-and-reopen "
            "(read-only). Exit 0 the snapshot's content survived / 1 it is missing "
            "or changed / 2 bad input / 3 undecidable."
        ),
        description=(
            "The third persistence state — saved_verified — is the only one that "
            "means the bytes reached the file, and no bridge action can establish "
            "it: doc.open moves the focused tab without reloading it from disk and "
            "there is no close-project action (M0-P0d audit). So the reopen is a "
            "human act, and this command turns its result into a verdict. Snapshot "
            "while the page is as drawn, close and reopen the project, then compare "
            "against the snapshot. Read-only on both legs, so it cannot change what "
            "it measures. The comparison asks whether the snapshot's content is "
            "still there — content added after the snapshot is listed as extras and "
            "does not fail it. See docs/persistence-baseline.md."
        ),
    )
    persist.add_argument(
        "--out", default=None,
        help="Write the snapshot (netlist + geometry) to this JSON file.",
    )
    persist.add_argument(
        "--baseline", default=None,
        help=(
            "A snapshot to compare the live page against; all of its content still "
            "present means saved_verified (extras are reported, not failed)."
        ),
    )


def register_arch_parser(sub: Any) -> None:
    """Register the historical `arch` command surface."""
    arch = sub.add_parser(
        "arch",
        help=(
            "Offline: the architecture skeleton for an export (task 044 M1) — "
            "power tree / analog chains / control chains / buses / intent slots, "
            "every judgement a tool cannot make left as a TODO slot."
        ),
        description=(
            "Generate the architecture skeleton an AI must walk and fill (task 044). "
            "It is a skeleton and nothing more: the tool lists the chains it can see "
            "in the netlist, writes one block of fixed-key slots per chain, and "
            "leaves every question it cannot answer (a rail's source, a chain's "
            "polarity / reference / gain, any design-intent number) as `TODO`. "
            "Deterministic: the same model produces byte-identical markdown, so the "
            "artifact can be diffed and kept as a living document. Offline: no "
            "editor, no daemon, no network. A multi-board project is walked per "
            "board (checkup's own rule) and prints one section block per board. "
            "Exit 0 generated / 2 the input cannot be used."
        ),
    )
    arch.add_argument("file", help="The .epro2 / .enet export to read (read-only).")
    arch.add_argument(
        "--out", default=None,
        help="Write the markdown here instead of stdout (created if missing).",
    )
    arch.add_argument(
        "--library", default=None,
        help=(
            "The curated shelf, for the two pieces of evidence it adds: the "
            "`ic.mcu` classification and its regulators' output voltages "
            "(default blocklib/parts.json)."
        ),
    )
    arch.add_argument(
        "--intent", default="", metavar="PATH",
        help=(
            "Read (or create) the DesignIntent contract at PATH and **regenerate** "
            "it against this drawing (090 A1): the slots the project now owes are "
            "added as TODO entries, every answer already in the file is preserved "
            "byte for byte, an object that disappeared is marked `stale` and never "
            "deleted. Also writes the human view `design-intent.md` beside --out. "
            "Without this flag nothing is written outside --out."
        ),
    )


def register_intent_parser(sub: Any) -> None:
    """Register the historical `intent` command surface."""
    intent = sub.add_parser(
        "intent",
        help=(
            "The DesignIntent contract's rails: `intent audit` lists the power nets "
            "whose voltage only the engineer knows (issue #65), `intent set-rail` "
            "writes one answer into the contract with provenance user_stated."
        ),
        description=(
            "Issue #65's two halves, mechanical so the reviewer's question is not "
            "reinvented 每 run. `intent audit --file <export>` enumerates every "
            "power net (VCC/VDD/VBAT/VREF-class names, or a net carrying a supply "
            "pin whose own name is one of those spellings — a bare `OUT`/`IN` is a "
            "port label, not a rail) "
            "whose voltage no source prices — the name, the contract and the "
            "architecture enumeration are all checked first — and marks the ones "
            "that are already answered, so an engineer is asked **once** and never "
            "again. `intent set-rail <net> --voltage <值>` writes that answer at "
            "requirements.rails[net=<网名>].voltage with provenance `user_stated`, "
            "through the same designintent module `arch --intent` uses, touching no "
            "other key. Both are offline and read-only except set-rail, which edits "
            "the one contract file and nothing else. Exit 0 ok / 2 input unusable."
        ),
    )
    intent_sub = intent.add_subparsers(dest="intent_command", required=True)
    intent_audit = intent_sub.add_parser(
        "audit",
        help="List the power nets whose voltage nobody has stated — the ask list.",
        description=(
            "One row per unanswered power net: the evidence that put it on the list "
            "(a rail-spelled net name, or a supply pin — one whose own name is such "
            "a spelling — sitting on it), the exact contract "
            "key to write, and a `settled` line for the ones already priced. The "
            "settled half is the point of the command: a rail the contract already "
            "carries, a rail whose own name says 5 V, and a ground net come back "
            "with WHERE the answer came from, so no run asks for it again. "
            "--json writes the same two lists as a machine-readable report."
        ),
    )
    intent_audit.add_argument(
        "--file", required=True, help="The .epro2 / .eprj3 project to read (read-only)."
    )
    intent_audit.add_argument(
        "--intent",
        default="",
        metavar="PATH",
        help=(
            "The DesignIntent contract to read for existing answers (default: "
            "~/.boardwise/design-intent/<projectUuid>.json when that file exists, "
            "same resolution `checkup --intent` uses). Without a contract every "
            "unpriced rail is a question."
        ),
    )
    intent_audit.add_argument(
        "--library",
        default=None,
        help=(
            "The curated shelf, for the one settled reason that needs it (a "
            "regulator's declared or MPN-decoded output; default "
            "blocklib/parts.json)."
        ),
    )
    intent_audit.add_argument(
        "--json", dest="json_path", metavar="PATH", help="Write the report as JSON."
    )
    intent_set = intent_sub.add_parser(
        "set-rail",
        help="Write one rail's voltage into the contract as user_stated.",
        description=(
            "The clerk half of issue #65: the engineer answered, this records it "
            "once. It sets requirements.rails[net=<网名>].voltage and the entry's "
            "provenance to `user_stated`, creates the entry when the contract has "
            "none, and touches no other key, entry or line order. A value this "
            "build cannot read as volts is refused by name (exit 2) rather than "
            "stored — the slot is priced by arithmetic, so an unreadable string "
            "would leave the rail asking forever. A stale entry is still the "
            "engineer's answer: re-stating it is how a moved rail keeps its value."
        ),
    )
    intent_set.add_argument("net", help="The net to price, e.g. VCC.")
    intent_set.add_argument(
        "--voltage", required=True, help="What it is, e.g. 3.3V / 3V3 / +5V / -12V."
    )
    intent_set.add_argument(
        "--file",
        dest="contract",
        required=True,
        metavar="PATH",
        help=(
            "The DesignIntent contract to update (JSON is the source). Created if "
            "it does not exist — this command is where an engineer's first answer "
            "lands, so a missing file is the normal first run, not an error."
        ),
    )
    intent_set.add_argument(
        "--json",
        dest="json_path",
        metavar="PATH",
        help="Write what changed (net, voltage, provenance, the new digest).",
    )


def register_config_parser(sub: Any) -> None:
    """Register the historical `config` command surface."""
    settings = sub.add_parser(
        "config",
        help=(
            "User-level settings in ~/.boardwise/config.json (039 批②). "
            "`config get <key>` / `config set <key> <value>` / `config show`. "
            "Exit 0 ok / 2 bad key, bad value or unreadable file."
        ),
    )
    settings_sub = settings.add_subparsers(dest="config_command", required=True)
    settings_get = settings_sub.add_parser(
        "get",
        help="Print one setting's resolved value (the file's, else the default).",
        description=(
            "The resolved value, one line on stdout so a shell can read it, and "
            "with --json the value plus where it came from ('file' or 'default')."
        ),
    )
    settings_get.add_argument("key", help="The dotted key, e.g. review.aesthetics.")
    settings_get.add_argument(
        "--json", action="store_true", help="Print {key, value, source, path}."
    )
    settings_set = settings_sub.add_parser(
        "set",
        help="Write one setting (a switch takes on/off).",
        description=(
            "Read-modify-write of the whole settings file, written atomically "
            "beside it. An unknown key is refused: the table of settings is "
            "extended by decision, not by typo."
        ),
    )
    settings_set.add_argument("key", help="The dotted key, e.g. review.aesthetics.")
    settings_set.add_argument("value", help="on / off (also true/false/1/0/yes/no).")
    settings_show = settings_sub.add_parser(
        "show",
        help="Every known setting with its value, source and meaning.",
    )
    settings_show.add_argument(
        "--json", action="store_true", help="Print the whole resolved table."
    )


def dispatch_shared(
    args: argparse.Namespace,
    handler: Callable[[argparse.Namespace], int],
) -> int:
    """Resolve one direct shared-domain handler at call time."""
    return handler(args)


def dispatch_bridge(
    args: argparse.Namespace,
    handlers: Mapping[str, Callable[[argparse.Namespace], int]],
) -> int:
    """Resolve a bridge subcommand through its historical live registry."""
    return handlers[args.bridge_command](args)


def dispatch_config(
    args: argparse.Namespace,
    handlers: Mapping[str, Callable[[argparse.Namespace], int]],
) -> int:
    """Resolve a config subcommand through its historical live registry."""
    return handlers[args.config_command](args)


def dispatch_intent(
    args: argparse.Namespace,
    handlers: Mapping[str, Callable[[argparse.Namespace], int]],
) -> int:
    """Resolve an intent subcommand through its historical live registry."""
    return handlers[args.intent_command](args)
