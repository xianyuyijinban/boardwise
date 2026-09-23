"""boardwise command line interface."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from .engines.review import (
    BUILTIN_RULES,
    finding_refs,
    render_json,
    render_markdown,
    run_review,
    severity_counts,
)
from .engines.drc import (
    offline_section,
    pcb_section,
    schematic_section,
    summarise as drc_summarise,
)
from .engines.checkup import (
    PAGE_ATTRIBUTION_ARCHIVE,
    PAGE_ATTRIBUTION_PER_PAGE,
    PAGE_ATTRIBUTION_UNRESOLVED,
    modules_section,
    page_attribution_from_archive,
    render_report_markdown,
    summary_template,
    unknown_parts,
)
from .engines.generate import DEFAULT_NAMING_STRATEGY, NAMING_STRATEGIES
from .core.changeplan import (
    COMPONENT_VALUE_KIND,
    ChangePlan,
    ChangePlanError,
    PlanSource,
    component_value_plan,
    resolve_on_page,
    sha256_of,
)
from .core.geometry import ParseStats
from .parsers.enet import parse_enet
from .parsers.epro2_model import build_design_model
from .parsers.epru import EncryptedProjectError, build_board_geometry, load_epro2_source
from .rules.i18n import EMPTY_PCB_VIEW_HINT, finding_line, parse_drop_hint, summary_section

#: Input extensions the reviewer understands, and what each one is.
SUPPORTED_SUFFIXES: dict[str, str] = {
    ".enet": "schematic netlist export",
    ".epro2": "project backup (board + netlist, one file)",
}

#: Where `boardwise review --latest` looks when no directory is given
#: (task 018 §C.1): the three places an export actually lands for this user —
#: the browser's download folder, the desktop (where 立创's "导出" often saves),
#: and the editor's default project root. A directory that does not exist is
#: not an error: it is simply not scanned.
LATEST_DEFAULT_DIRS: tuple[str, ...] = ("~/Downloads", "~/Desktop", "E:/LC Project")

#: The suffix `--latest` recognises, matched case-insensitively (a copy of an
#: export can arrive as `.EPRO2`).
PROJECT_BACKUP_SUFFIX = ".epro2"

#: Printed (task 019 §1) when the pcb view of a `.epro2` reads nothing at all.
#: The most likely reason is that the export carries only a schematic, and the
#: default view cannot say that by itself: the run then reports "0 components,
#: 0 nets" as a fact and the reader concludes the export is empty. English,
#: like the rest of the console output. Fires on
#: :func:`_pcb_view_read_nothing` only — never on a board with content.
EMPTY_PCB_VIEW_NOTE = (
    "note: pcb view read nothing from this file — for a schematic review, "
    "re-run with --view schematic"
)

#: The tail every parse-drop note shares (task 020 §WI-1). The numbers are
#: written by :func:`_parse_drop_note`; the *consequence* is one sentence in
#: one place, because "coverage is incomplete" is the whole reason the note
#: exists — a reader who is told only the counts will take the report as
#: complete anyway.
PARSE_DROP_NOTE_TAIL = " — review coverage is incomplete"


def _parse_drop_note(pins_dropped: int, components_without_symbol: int) -> str:
    """The console note for a schematic parse that dropped things, or ``""``.

    English, like the rest of the console output, and printed only when a
    counter is non-zero — a zero is not evidence here (the pcb view never fills
    these counters at all, see :func:`_load_model`), so a note reading "0 pins
    dropped" would be a claim about a parse that did not happen. A zeroed item
    therefore contributes nothing instead of "0".

    The two facts are separate claims and stay separately worded: a dropped pin
    is a connection the reviewer never saw, a component without a symbol is a
    whole part whose pins are all missing. Both mean the same thing to the
    reader — the report under-covers this board — so both carry the same tail.
    """
    parts: list[str] = []
    if pins_dropped:
        parts.append(f"{pins_dropped} pin(s) dropped during parse (missing pin number)")
    if components_without_symbol:
        parts.append(f"{components_without_symbol} component(s) without a resolvable symbol")
    if not parts:
        return ""
    return "note: " + " and ".join(parts) + PARSE_DROP_NOTE_TAIL


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


class _VersionAction(argparse.Action):
    """``--version``, computed when it is asked for rather than at parse time.

    ``action="version"`` wants the text up front, which would make *every*
    command pay for two file reads (the bundle's size and its manifest) whether
    it prints them or not. This action resolves the text only when the flag is
    actually used. It exits 0 like the built-in one.
    """

    def __init__(self, option_strings, dest, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(option_strings, dest, nargs=0, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):  # type: ignore[no-untyped-def]
        print(_version_text())
        parser.exit()


def _version_text() -> str:
    """Two lines: this CLI, then the connector bundle it carries (028 §二.3).

    Both versions are *read*, never guessed. The CLI's comes from the package,
    the bundle's from the ``extension.json`` beside the bundle — the same
    manifest ``update-connector`` takes the pushed version from, so "what
    ``--version`` says" and "what a hot update would install" cannot disagree.

    A missing or unreadable manifest prints ``unknown`` **with the path it looked
    at**. A friend's bug report containing a path is worth more than a blank
    line, and inventing a version would be worse than both — the failure mode
    this whole package exists to avoid.
    """
    import json

    from . import __version__, resources

    first = f"boardwise {__version__} (CLI, running from {resources.describe_state()})"
    try:
        bundle = resources.connector_bundle()
        manifest = resources.connector_extension_json()
    except RuntimeError as exc:
        return f"{first}\nconnector bundle unknown ({exc})"
    try:
        version = str(json.loads(manifest.read_text(encoding="utf-8")).get("version") or "unknown")
    except (OSError, ValueError) as exc:
        return f"{first}\nconnector bundle unknown (cannot read {manifest}: {exc})"
    try:
        size = f", {bundle.stat().st_size} bytes"
    except OSError:
        size = " (the bundle file is missing)"
    return f"{first}\nconnector bundle {version} ({bundle}{size})"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="boardwise",
        description="AI harness for EasyEDA Pro: offline design review (stage 1).",
    )
    # Two versions on purpose (028 batch 3a): the CLI and the connector bundle
    # this build would push into the editor are versioned separately (0.1.0 vs
    # 0.4.19 today, a known and deliberate split), and a bug report needs both —
    # "which boardwise" and "which extension it installed" are different
    # questions, and the second one is the answer a friend cannot look up.
    parser.add_argument(
        "--version",
        action=_VersionAction,
        help="Print the CLI version and the embedded connector bundle version.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    review = sub.add_parser(
        "review", help="Review an EasyEDA .enet netlist or .epro2 backup offline."
    )
    review.add_argument(
        "file",
        nargs="?",
        help=(
            "Path to the .enet netlist or .epro2 project backup. Omit it when "
            "using --latest."
        ),
    )
    review.add_argument(
        "--latest",
        nargs="?",
        const="",
        default=None,
        metavar="DIR",
        help=(
            "Review the most recently modified .epro2 in DIR (one level of "
            "subdirectories included) instead of naming a file. Without DIR, "
            "the defaults are scanned: ~/Downloads, ~/Desktop, E:\\LC Project "
            "(only the ones that exist). Mutually exclusive with the file "
            "argument."
        ),
    )
    review.add_argument(
        "--json", dest="json_path", metavar="PATH", help="Write a JSON report."
    )
    review.add_argument(
        "--md", dest="md_path", metavar="PATH", help="Write a Markdown report."
    )
    review.add_argument(
        "--view",
        choices=("pcb", "schematic"),
        # Resolved in `_cmd_review`: `pcb` for a file (the historical default),
        # `schematic` for --live (a live model is a page model). A plain default
        # here would make `review --live` refuse its own sensible view.
        default=None,
        help=(
            "Which model of a .epro2 backup to review: pcb (the default for a "
            "file, the PCB netlist view) or schematic (the parsed schematic, the "
            "view the 011 review rules are written against — use it for "
            "schematic-only exports, where the pcb view is empty). With --live "
            "the default is schematic, because the live data path yields pages."
        ),
    )
    review.add_argument(
        "--live",
        action="store_true",
        help=(
            "Review the project open in the editor instead of a file (025 batch "
            "2): the same offline rules over a model loaded through checkup's "
            "tier ladder (project archive → per-page archives → netlist). "
            "Mutually exclusive with a file argument and with --latest. Exit 3 "
            "when the online state cannot be stated."
        ),
    )

    checkup = sub.add_parser(
        "checkup",
        help="One-command review: read the live project, report what tier it used.",
    )
    checkup.add_argument(
        "--file",
        metavar="PATH",
        default="",
        help=(
            "Offline fallback: an exported .epro2 to report on, with no editor "
            "and no daemon involved. Mutually exclusive with --project/--instance."
        ),
    )
    checkup.add_argument(
        "--project",
        default="",
        help=(
            "Which editor window to read, by project name or uuid (023). Needed "
            "only when several windows are connected and none can be named by "
            "the daemon's default."
        ),
    )
    checkup.add_argument(
        "--instance",
        default="",
        help=(
            "The same choice spelled as the window key `bridge status` prints — "
            "the way to reach one window when no project can be read yet."
        ),
    )
    checkup.add_argument(
        "--out",
        default="checkup",
        metavar="DIR",
        help=(
            "Directory for report.json (created if missing). Default: "
            "%(default)s."
        ),
    )
    checkup.add_argument(
        "--port", type=int, default=None, help="Daemon port (default 61190)."
    )

    review_eval = sub.add_parser(
        "review-eval",
        help="Measure review rules against oracle annotation sets (task 011a).",
        description=(
            "Run the built-in rules over each annotated board, pair findings "
            "with the oracle's defect/exception records, and print per-rule "
            "raw numerators and denominators. Holdout items are excluded "
            "unless --split holdout (or all) is given explicitly, so rule "
            "tuning cannot peek at them by accident."
        ),
    )
    review_eval.add_argument(
        "--annotations",
        nargs="+",
        required=True,
        metavar="PATH",
        help="Annotation-set JSON file(s) or glob patterns.",
    )
    review_eval.add_argument(
        "--split",
        choices=("dev", "holdout", "all"),
        default="dev",
        help="Which annotation split to measure (default: dev only).",
    )
    review_eval.add_argument(
        "--json",
        dest="json_path",
        metavar="PATH",
        help="Write the machine-readable report.",
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
        help="Version string to store (default: read from connector/extension.json).",
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
            "none can be named by a project. The read-back then waits for a "
            "window to come back announcing the stored version."
        ),
    )
    bridge.add_argument(
        "--port", type=int, default=None, help="Daemon port (default 61190)."
    )

    review_mark = sub.add_parser(
        "review-mark",
        help=(
            "Draw a `boardwise review` pass on the live schematic canvas "
            "(012v2 §八: markers + jump list)."
        ),
        description=(
            "Reads the findings `boardwise review --json` wrote (a path, `-` for "
            "stdin, or the JSON itself), resolves each finding's refs to positions "
            "on the focused page and draws indicator markers there. The marker API "
            "takes shapes, not text, so this command prints the finding table that "
            "numbers the markers: position k is `marker#k` on the canvas. "
            "`review-mark clear` removes the markers instead. Exit 0 all landed / "
            "1 partial (a ref not on the page, a finding with no ref, or a host "
            "that could not draw — each named) / 2 bad input or no daemon."
        ),
    )
    review_mark.add_argument(
        "findings",
        help=(
            "The `boardwise review --json` report: a path, `-` to read stdin, or "
            "the JSON text. The literal `clear` removes the markers instead."
        ),
    )
    review_mark.add_argument(
        "--page", default=None, metavar="UUID",
        help=(
            "Schematic page uuid the findings are about (from `doc.list`). Given, "
            "a different focused page is refused instead of marked."
        ),
    )
    review_mark.add_argument(
        "--focus", type=int, default=None, metavar="N",
        help="Zoom the canvas to the Nth finding (1-based, the report's order).",
    )
    review_mark.add_argument("--color", default="#FF0000", help="Marker colour (default #FF0000).")
    review_mark.add_argument(
        "--zoom", action="store_true", help="Zoom to all markers (ignored together with --focus)."
    )
    review_mark.add_argument(
        "--no-markers", action="store_true",
        help="Draw nothing: print the jump list (ref + coordinates) only.",
    )
    review_mark.add_argument(
        "--json", dest="json_path", metavar="PATH", help="Write the machine-readable result."
    )
    review_mark.add_argument(
        "--port", type=int, default=None, help="Daemon port (default 61190)."
    )

    edit = sub.add_parser(
        "edit",
        help=(
            "Review-to-local-edit (task 016): turn one review finding into an "
            "authorised, verified change of a single component's value."
        ),
        description=(
            "The M3 loop's middle: `edit plan` turns one finding into a "
            "ChangePlan (data, inspectable), `edit preview` re-checks it "
            "offline against the snapshot, `edit apply` executes it on the live "
            "canvas — one write, then a read-back, a save and a re-review. Only "
            "`param-value-mpn-match` findings are repairable in this slice; a "
            "plan for anything else is refused by name. Exit 0 applied (or "
            "already applied) / 2 the promised effect is not on the board (a "
            "refused write, a read-back that disagrees, a save the editor "
            "refused, a re-review that still reports the finding) / 3 the "
            "page's state cannot be stated (a timeout or a dropped connection; "
            "nothing is retried) / 4 a precondition of the plan no longer "
            "holds, or the snapshot is stale / 5 the plan or the input is "
            "unusable."
        ),
    )
    edit_sub = edit.add_subparsers(dest="edit_command", required=True)

    edit_plan = edit_sub.add_parser(
        "plan",
        help="Offline: read a finding and write the ChangePlan that would fix it.",
        description=(
            "Parse the snapshot, run one rule, take the VIOLATION finding for "
            "that designator and assemble the plan. Refuses (exit 5) when the "
            "rule is unknown, is not repairable, has no violation there, or the "
            "designator is ambiguous in the file — a plan that cannot be acted "
            "on is worse than no plan."
        ),
    )
    edit_plan.add_argument(
        "--file", required=True, help="The .epro2 / .enet snapshot the plan is built against."
    )
    edit_plan.add_argument(
        "--rule", required=True, help="Rule id whose finding the plan repairs (e.g. param-value-mpn-match)."
    )
    edit_plan.add_argument(
        "--designator", required=True, help="The component to change, e.g. U3."
    )
    edit_plan.add_argument(
        "--after", default=None,
        help="The value to write (default: the finding's own suggested value).",
    )
    edit_plan.add_argument(
        "-o", "--out", dest="out_path", default=None, metavar="PATH",
        help="Write the ChangePlan JSON here (default: print it to stdout).",
    )
    edit_plan.add_argument(
        "--json", dest="json_path", metavar="PATH", help="Write the machine-readable result."
    )
    edit_plan.add_argument(
        "--view", choices=("schematic", "pcb"), default="schematic",
        help=(
            "Which model of a .epro2 to parse (default: schematic — the view the "
            "011-family rules are written against; a schematic-only export's pcb "
            "view is empty)."
        ),
    )

    edit_preview = edit_sub.add_parser(
        "preview",
        help="Offline: check the plan against the snapshot and print the diff.",
        description=(
            "Re-read --file, compare its sha256 with the plan's, re-parse it and "
            "confirm the target is still there with the value the plan expects. "
            "Exit 4 for a stale snapshot or a target that moved; nothing is "
            "written, ever. --file is required: the plan carries the input's "
            "hash, not its path, so without the file there is nothing to check."
        ),
    )
    edit_preview.add_argument("plan", help="The ChangePlan JSON `edit plan` wrote.")
    edit_preview.add_argument(
        "--file", default=None, help="The snapshot the plan was built against."
    )
    edit_preview.add_argument(
        "--json", dest="json_path", metavar="PATH", help="Write the machine-readable result."
    )
    edit_preview.add_argument(
        "--view", choices=("schematic", "pcb"), default="schematic",
        help="Which model of a .epro2 to parse (default: schematic).",
    )

    edit_apply = edit_sub.add_parser(
        "apply",
        help="On the live canvas: re-check, write once, read back, save, re-review.",
        description=(
            "The four protections, in order: re-read the page and refuse a stale "
            "snapshot; write exactly one key on exactly one primitive; verify "
            "with the action's own read-back **and** an independent geometry "
            "read; and treat a timeout or a dropped connection as unknown — read "
            "the page back and never retry. Then `sch.doc.save` and a re-review "
            "against --file. A repeated run recognises the value is already "
            "there and writes nothing (exit 0, already_applied)."
        ),
    )
    edit_apply.add_argument("plan", help="The ChangePlan JSON `edit plan` wrote.")
    edit_apply.add_argument(
        "--file", default=None,
        help=(
            "The snapshot to re-review after the save. Without it the re-review "
            "is reported as unknown — it is never claimed."
        ),
    )
    edit_apply.add_argument(
        "--json", dest="json_path", metavar="PATH", help="Write the machine-readable result."
    )
    edit_apply.add_argument(
        "--view", choices=("schematic", "pcb"), default="schematic",
        help="Which model of a .epro2 to re-parse (default: schematic).",
    )
    edit_apply.add_argument(
        "--port", type=int, default=None, help="Daemon port (default 61190)."
    )

    # Spelled from the constant, never typed out again: the floor moves in one
    # place, or `--help` starts quoting a version doctor no longer asks for.
    floor_text = ".".join(str(part) for part in EDITOR_API_FLOOR)
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

    install_skill = sub.add_parser(
        "install-skill",
        help="Copy the bundled SKILL.md into the user-level Kimi Code skill directory.",
        description=(
            "Writes the SKILL.md this build carries to "
            "~/.kimi-code/skills/boardwise/SKILL.md (override the directory with "
            "BOARDWISE_SKILL_HOME). Idempotent: an identical file says 'already "
            "current' and is left alone. A *different* file is backed up to "
            "SKILL.md.bak-<date> first — never silently overwritten. --uninstall "
            "removes the installed copy, and the directory when it empties."
        ),
    )
    install_skill.add_argument(
        "--uninstall", action="store_true",
        help="Remove the installed copy instead of installing one.",
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
            "golden page (task 008a), and the spec first passes the product "
            "validation gates — a refused spec draws nothing (009-M0). "
            "Exit 0 equal / 1 differences or failures / 2 bad input / "
            "3 a write's outcome is unknown (a timeout or a dropped connection), "
            "which outranks 0 and 1 — the page's state cannot be stated."
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
    draw.add_argument(
        "--port-meta", default="blocklib/blocks.portmeta.json",
        help=(
            "Spec mode only: the port-metadata sidecar the pre-draw validation "
            "reads (default: %(default)s, same convention as `validate`). "
            "Without it the levels and power-tree gates answer \"cannot tell\", "
            "which refuses the draw."
        ),
    )
    draw.add_argument(
        "--library", default="",
        help=(
            "Spec mode only: curated part library a `part` reference in the "
            "spec can cite (default: none; a part citation without a library "
            "is undecidable, which refuses the draw)."
        ),
    )

    persist = sub.add_parser(
        "persistence",
        help=(
            "Snapshot the live page and compare it across a real close-and-reopen "
            "(read-only). Exit 0 identical / 1 different / 2 bad input / 3 undecidable."
        ),
        description=(
            "The third persistence state — saved_verified — is the only one that "
            "means the bytes reached the file, and no bridge action can establish "
            "it: doc.open moves the focused tab without reloading it from disk and "
            "there is no close-project action (M0-P0d audit). So the reopen is a "
            "human act, and this command turns its result into a verdict. Snapshot "
            "while the page is as drawn, close and reopen the project, then compare "
            "against the snapshot. Read-only on both legs, so it cannot change what "
            "it measures. See docs/persistence-baseline.md."
        ),
    )
    persist.add_argument(
        "--out", default=None,
        help="Write the snapshot (netlist + geometry) to this JSON file.",
    )
    persist.add_argument(
        "--baseline", default=None,
        help="A snapshot to compare the live page against; equal means saved_verified.",
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
            "Run a board spec through the validation gates of task 008c item 4 "
            "(sources, pin budget, levels, power tree; --benchmark adds the "
            "closed book). Exit 0 clean / 1 blocked / 2 bad input. An "
            "undecidable result blocks like a violation does; a skipped gate "
            "says so instead of passing."
        ),
    )
    validate.add_argument("--spec", required=True, help="Path to the board spec.")
    validate.add_argument(
        "--benchmark", action="store_true",
        help=(
            "Also run the closed-book gate: the generation benchmark's "
            "discipline (nothing may trace to the --target board, and every "
            "field must cite a declared input). Product validation leaves it "
            "out on purpose: a board being drawn owes sound electricity, not "
            "a bibliography."
        ),
    )
    validate.add_argument(
        "--target", action="append", default=[],
        metavar="NAME",
        help=(
            "Benchmark mode only: the board being generated — the one whose "
            "artifacts may not be consulted. Give every alias it has (the "
            "export AND the local project), or the closed-book gate stays "
            "undecidable; repeat the option for more than one."
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


def _load_model(
    path: Path, *, view: str = "pcb", parse_stats: ParseStats | None = None
) -> tuple[object, object | None]:
    """Return ``(DesignModel, BoardGeometry | None)`` for a supported input.

    ``view`` picks which model a ``.epro2`` backup yields: ``pcb`` (the
    default, the netlist view ``review`` has always used) or ``schematic``
    (the parsed schematic, which is what the 011-family rules are written
    against — a schematic-only export yields an empty pcb view, measured
    2026-09-19). ``BoardGeometry`` is only available for the pcb view of a
    ``.epro2``; both views come from one parse of the file. Raises
    :class:`EncryptedProjectError` for an unreadable backup and ``ValueError``
    for an unsupported extension.

    ``parse_stats`` (task 020 §WI-1) is an optional caller-owned
    :class:`boardwise.core.geometry.ParseStats` the schematic parse fills in.
    Only the schematic view writes it: the pcb view's model comes from the PCB
    document (:mod:`boardwise.parsers.epro2_model`), which never consults the
    SYMBOL documents the two drop counters are about — its counters would read
    0 by construction rather than by evidence, so it is left untouched and its
    reader must not treat a zero as a measurement.
    """
    suffix = path.suffix.lower()
    if suffix == ".enet":
        return parse_enet(path), None
    if suffix == ".epro2":
        source = load_epro2_source(path)
        if view == "schematic":
            from .parsers.schematic import build_schematic_model

            return build_schematic_model(path, parse_stats=parse_stats), None
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


def _safe_iterdir(directory: Path) -> list[Path]:
    """``directory``'s entries, sorted; an unreadable directory reads as empty.

    `--latest` is a convenience: a permission error on one subdirectory must
    not make the whole review fail, it just contributes no candidate.
    """
    try:
        return sorted(directory.iterdir())
    except OSError:
        return []


def _is_project_backup(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == PROJECT_BACKUP_SUFFIX


def _project_backups(directory: Path) -> list[Path]:
    """The `.epro2` files in *directory* and **one level** below it.

    One level, not a full walk: 立创 writes the export next to the project, and
    a recursive search would wander trees nobody exported into and then pick
    the wrong file with confidence.
    """
    found: list[Path] = []
    for entry in _safe_iterdir(directory):
        if entry.is_dir():
            found.extend(
                path for path in _safe_iterdir(entry) if _is_project_backup(path)
            )
        elif _is_project_backup(entry):
            found.append(entry)
    return found


def _newest_project_backup(directories: list[Path]) -> Path | None:
    """The most recently modified `.epro2` among *directories*, or ``None``.

    Ties are broken by path so that two files written inside the same
    nanosecond still give exactly one answer: the pick is a claim printed to
    the user and must be repeatable.
    """
    candidates: list[tuple[int, str, Path]] = []
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in _project_backups(directory):
            try:
                stamp = path.stat().st_mtime_ns
            except OSError:
                continue
            candidates.append((stamp, str(path), path))
    if not candidates:
        return None
    return max(candidates)[2]


def _latest_scan_dirs(spec: str) -> list[Path]:
    """The directories `--latest` scans: the one given, or the defaults that exist."""
    if spec:
        return [Path(spec).expanduser()]
    return [
        path
        for path in (Path(raw).expanduser() for raw in LATEST_DEFAULT_DIRS)
        if path.is_dir()
    ]


def _review_source(args: argparse.Namespace) -> str | None:
    """The file to review, spelled as it will be reported: the positional
    argument as given, or the path `--latest` picked.

    Prints the pick (path + mtime) before the review starts, because "最新" is
    only useful if it says which export it means — the user is the one who
    knows whether the newest export is the right one. Returns ``None`` after
    printing the reason when the input cannot be resolved (exit code 2, bad
    usage).
    """
    if args.latest is None:
        if not args.file:
            print(
                "boardwise review: give a file, or --latest [<目录>]",
                file=sys.stderr,
            )
            return None
        return args.file

    if args.file:
        print(
            "boardwise review: give either a file or --latest, not both "
            "(--latest picks the newest .epro2 itself)",
            file=sys.stderr,
        )
        return None

    directories = _latest_scan_dirs(args.latest)
    if not directories:
        print(
            "boardwise review --latest: 默认目录都不存在（"
            + "、".join(LATEST_DEFAULT_DIRS)
            + "）; give one: boardwise review --latest <目录>",
            file=sys.stderr,
        )
        return None
    missing = [path for path in directories if not path.is_dir()]
    if missing:
        print(
            "boardwise review --latest: "
            + "、".join(str(path) for path in missing)
            + " 不是一个目录",
            file=sys.stderr,
        )
        return None

    chosen = _newest_project_backup(directories)
    if chosen is None:
        print(
            "boardwise review --latest: 这些目录里没有 .epro2（已含一层子目录）："
            + "、".join(str(path) for path in directories),
            file=sys.stderr,
        )
        return None
    stamp = datetime.fromtimestamp(chosen.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    print(f"boardwise review --latest: 选中 {chosen}（最后修改 {stamp}）")
    return str(chosen)


def _finding_refs_for_summary(finding, designators: set[str]) -> list[str]:
    """A finding's designators, for the Chinese summary.

    Read the same way `review-mark` reads them (:func:`finding_refs`), plus the
    plan target when there is one — a repairable finding names the part it
    would change even if its prose does not (task 016's `target`).

    Then kept only if the board actually has that designator. The reader is an
    allow-list of *prefixes* (`RT`, `C`, `U`, …) applied to prose, so a part
    number sneaks through: on the injected value-mpn board the LED rule's
    evidence says "per U5 RT9013-33GB output", and `RT9013` reads as a preset
    designator. Naming a part the board does not contain would be worse than
    naming none (the Chinese line is the one a reader trusts fastest).
    """
    refs = [ref for ref in finding_refs(finding) if ref in designators]
    target = getattr(finding, "target", None)
    designator = getattr(target, "component_ref", "") if target is not None else ""
    if designator in designators and designator not in refs:
        refs.insert(0, designator)
    return refs


def _chinese_summary(
    findings: list,
    counts: dict[str, int],
    designators: set[str],
    *,
    empty_pcb_view: bool = False,
    parse_drop_hint: str = "",
) -> str:
    """The Chinese summary section for a set of findings (task 018 §C.3).

    One line per finding, in the report's own order (most severe first): rule
    name in Chinese, the designators it names, the numbers it already printed.

    ``empty_pcb_view`` (task 019 §2) adds the one sentence that explains an
    all-empty report — a reader who meets "共 0 条发现" and stops there would
    read a wrong view as a clean board. The wording lives in the i18n module
    with the rest of the Chinese; the trigger does not (it is
    :func:`_pcb_view_read_nothing`).

    ``parse_drop_hint`` (task 020 §WI-1) is the same idea one step further: the
    report's findings are found in a model that *lost* pins, so "共 N 条发现"
    is not the whole truth either. Empty string when nothing was dropped
    (``rules.i18n.parse_drop_hint`` builds it from the counters). Both hints can
    in principle be asked for at once, and they are two paragraphs then — each
    stays its own paragraph, which is what makes them read.
    """
    hints = [
        EMPTY_PCB_VIEW_HINT if empty_pcb_view else "",
        parse_drop_hint,
    ]
    return summary_section(
        [
            finding_line(
                severity=finding.severity,
                rule_id=finding.rule_id,
                message=finding.message,
                refs=_finding_refs_for_summary(finding, designators),
            )
            for finding in findings
        ],
        counts,
        hint="\n\n".join(paragraph for paragraph in hints if paragraph),
    )


def _with_chinese_summary(markdown: str, section: str) -> str:
    """Insert the Chinese summary (task 018 §C.3) into a rendered report.

    Right after the header block and **before the first finding section**, so
    the report still opens with `# boardwise review report` (byte for byte,
    tests/test_cli.py pins that) while the first thing the reader meets is
    Chinese. The English finding lines below it are untouched.
    """
    lines = markdown.split("\n")
    for index, line in enumerate(lines):
        if line.startswith("- Findings:"):
            insert_at = min(index + 2, len(lines))
            break
    else:  # a header shape this code does not recognise: leave it alone
        return markdown
    return "\n".join([*lines[:insert_at], *section.split("\n"), *lines[insert_at:]])


def _pcb_view_read_nothing(
    path: Path, view: str, model: object, board: object | None
) -> bool:
    """Was this a `.epro2` reviewed in the pcb view that read *nothing*?

    All three of task 019 §1's conditions in one place, because the hint is
    only allowed to fire on exactly this shape:

    * the input is a project backup (an `.enet` netlist has no view to pick, so
      an empty one means an empty netlist, not a wrong view);
    * ``view`` is ``pcb`` — the default, explicit or implicit, since the
      default is what quietly produced the shrug;
    * the model **and** the copper are empty: no components, no nets, no pads,
      no tracks, no vias. A board with copper but no netlist is not an empty
      read, and telling its reader to switch views would be a wrong hint —
      worse than silence.

    The wording is English or Chinese; the trigger is only ever this predicate.
    """
    if view != "pcb" or path.suffix.lower() != PROJECT_BACKUP_SUFFIX:
        return False
    if model.components or model.nets:
        return False
    # A board whose copper is there but whose netlist is empty is *not* an empty
    # read: pointing its reader at another view would send them somewhere worse.
    if board is not None and (board.pads or board.tracks or board.vias):
        return False
    return True


def _cmd_review(args: argparse.Namespace) -> int:
    live = bool(getattr(args, "live", False))
    live_notes: list[str] = []
    live_attempts: list[dict] = []
    parse_stats = ParseStats()

    if live:
        if args.file or args.latest is not None:
            print(
                "boardwise review --live: --live reads the editor, so a file "
                "argument / --latest would be a second, contradictory source "
                "(give one)",
                file=sys.stderr,
            )
            return 2
        # A live model is a *page* model: the live tiers read page archives (or a
        # netlist), and there is no live PCB-document model to review. Asking for
        # the pcb view explicitly is therefore refused rather than silently
        # answered with the schematic one.
        if args.view == "pcb":
            print(
                "boardwise review --live: the live data path yields the schematic "
                "view (pages + their library documents); --view pcb needs a PCB "
                "document export, which no action returns — review a file instead",
                file=sys.stderr,
            )
            return 2
        loaded = _load_model_online(
            args, notes=live_notes, attempts=live_attempts, parse_stats=parse_stats
        )
        if loaded is None:
            print(
                "boardwise review --live: 在线状态不可陈述 — no tier produced a model",
                file=sys.stderr,
            )
            for note in live_notes:
                print(f"  note: {note}", file=sys.stderr)
            return 3
        model, board, tier, source_meta, _attribution = loaded
        view = "schematic"
        source = f"live:{CHECKUP_TIERS[tier].split('（')[0]}"
        project = (source_meta.get("project") or {})
        label = project.get("friendlyName") or project.get("name")
        if label:
            source = f"live:/{label} (tier {tier})"
        path = None
    else:
        source = _review_source(args)
        if source is None:
            return 2
        path = Path(source)
        view = args.view or "pcb"
        # The parse reports what it dropped into this (task 020 §WI-1); the model
        # itself is unchanged, so `--json` and every rule's input are byte-for-byte
        # what they were. Only the schematic view fills it — see `_load_model`.
        try:
            model, board = _load_model(path, view=view, parse_stats=parse_stats)
        except EncryptedProjectError as exc:
            print(f"boardwise: {exc}", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(f"boardwise: {path}: {exc}", file=sys.stderr)
            return 2

    findings = run_review(model)
    counts = severity_counts(findings)
    # Computed once, read twice: the console line and the Chinese summary line
    # are two renderings of the same fact, and a change to the conditions must
    # not be able to make them disagree (task 019 §1, §2).
    empty_pcb_view = path is not None and _pcb_view_read_nothing(path, view, model, board)
    # Same rule for the drop counters: one pair of numbers, rendered once in
    # English for the console and once in Chinese for the summary.
    drop_note = _parse_drop_note(
        parse_stats.pins_dropped_no_number, parse_stats.components_without_symbol
    )

    print(
        f"boardwise review: {source} "
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
            "source": source,
            "components": len(model.components),
            "nets": len(model.nets),
        }
        summary = _chinese_summary(
            findings,
            counts,
            set(model.components),
            empty_pcb_view=empty_pcb_view,
            parse_drop_hint=parse_drop_hint(
                parse_stats.pins_dropped_no_number,
                parse_stats.components_without_symbol,
            ),
        )
        Path(args.md_path).write_text(
            _with_chinese_summary(render_markdown(findings, meta), summary),
            encoding="utf-8",
        )
        print(f"Markdown report written to {args.md_path}")

    # Last lines of the console output, after the report paths: a note is the
    # one thing a reader has to act on, so it must not be buried between the
    # census and a "written to" line. The two cannot fire together — the empty
    # view is a pcb-view reading and the counters are a schematic-parse one —
    # so neither has to concede being last.
    if empty_pcb_view:
        print(EMPTY_PCB_VIEW_NOTE)
    if drop_note:
        print(drop_note)

    return 1 if counts["ERROR"] else 0


# --------------------------------------------------------------------------
# checkup (025 batch 2): the data path, with an honest tier ladder
# --------------------------------------------------------------------------

#: Report schema id. Bumped when a field's *meaning* changes, not when one is added.
#:
#: `/2` since batch 3: `drc` and `findings` went from placeholders (`null` / `[]`,
#: listed in `pending`) to the sections themselves, and `summary` appeared. A
#: consumer written against `/1` — the two batch-2 reports in `outputs/` are that
#: shape — would read `drc.schematic: null` as "not checked yet"; the id is how it
#: can tell before it reads a batch-3 report wrong.
CHECKUP_SCHEMA = "boardwise.checkup/2"

#: What each tier actually read, spelled for the report's own header.
#:
#: The tier is the one field a reader must be able to trust, because it is what
#: separates "reviewed the whole project" from "reviewed one page" from
#: "reviewed connectivity only". A report that cannot say which of these it used
#: cannot be trusted to say what it reviewed (025 §2 阶段 A).
CHECKUP_TIERS: dict[str, str] = {
    "project-file": "整工程归档（sys.get_project_file → 临时 .epro2 → 离线管线）：满血",
    "per-page": "逐页归档合并（doc.open + sys.get_document_file × N）：跨页连通性不保证",
    "netlist": "在线网表 + 几何（sch.netlist / sch.geometry → candidate）：仅连通性",
    "file": "离线文件（--file）：不连编辑器",
}

#: The view the data path yields, and therefore the one `checkup` reports. The
#: 011-family rules are written against the schematic model, and the live tiers
#: produce exactly that (pages + the library documents they reference), so this
#: is not a default the caller should have to restate.
CHECKUP_VIEW = "schematic"


def _checkup_report(
    *,
    tier: str,
    source: dict,
    model: object,
    attempts: list[dict],
    notes: list[str],
    drc: dict,
    findings: list[dict],
    summary: dict,
    modules: list[dict],
    slots: dict,
) -> dict:
    """Assemble the report: what was read (batch 2), what was found (batch 3),
    what it means and what the model still has to do (batch 4).

    Every section is real by now. `pending` is kept as an **empty** object rather
    than removed: a consumer that learned to read it finds "nothing owed" instead
    of a missing key, and the next batch that owes something has a place to say
    so.
    """
    return {
        "schema": CHECKUP_SCHEMA,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": {
            "tier": tier,
            "tierLabel": CHECKUP_TIERS.get(tier, "(unknown tier)"),
            **source,
            "attempts": attempts,
            "notes": notes,
        },
        "model": {
            "view": CHECKUP_VIEW,
            "components": len(model.components),
            "nets": len(model.nets),
            "designators": sorted(model.components),
            "duplicateDesignators": sorted(model.duplicate_designators),
        },
        "summary": summary,
        "pending": {},
        "drc": drc,
        "modules": modules,
        "findings": findings,
        "ai_slots": slots,
    }


def _write_checkup_report(out_dir: Path, report: dict) -> Path:
    """Write ``report.json`` into ``out_dir`` (created if missing), and say where."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _write_checkup_markdown(out_dir: Path, report: dict) -> Path:
    """Write ``report.md`` beside ``report.json`` — the same content, for a human.

    Rendered from the *report dict*, never from the live objects: a second
    rendering path that read the model again could disagree with the JSON, and the
    JSON is the contract. The rendering itself lives in
    `engines/checkup.render_report_markdown`.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "report.md"
    path.write_text(render_report_markdown(report), encoding="utf-8")
    return path


def _merge_schematic_models(models: list, *, notes: list[str]) -> object:
    """Union per-page models into one.

    Why a merge at all: the per-page tier is what runs when the project-download
    gate is closed, and one page's model is not a project's. Components are keyed
    by designator (the model's own key), nets by name — so a net that appears on
    two pages keeps every pin it was seen with, and a designator that appears
    twice is recorded in ``duplicate_designators`` rather than silently winning.

    **What this cannot do is stated, not hidden**: two pages connected only by a
    net label are two pins with the same net name in the merged model, which is
    agreement by *name*, not a connectivity proof. That is why the caller labels
    the tier ``per-page`` instead of ``project-file``.
    """
    from .core.model import DesignModel, Net

    merged = DesignModel()
    for model in models:
        for designator, component in model.components.items():
            if designator in merged.components:
                if designator not in merged.duplicate_designators:
                    merged.duplicate_designators.append(designator)
                continue
            merged.components[designator] = component
        for name, net in model.nets.items():
            existing = merged.nets.get(name)
            if existing is None:
                merged.nets[name] = Net(name=name, pins=list(net.pins))
                continue
            for pin in net.pins:
                if pin not in existing.pins:
                    existing.pins.append(pin)
        for key, value in model.raw.items():
            merged.raw.setdefault(key, value)
    merged.duplicate_designators.sort()
    if len(models) > 1:
        notes.append(
            f"merged {len(models)} per-page models by designator/net name — cross-page "
            "connectivity is agreement by net name, not a traced connection"
        )
    return merged


def _archive_bytes(payload: object, label: str) -> bytes:
    """The base64 payload of an archive action as bytes, or a named failure."""
    import base64

    if not isinstance(payload, dict):
        raise ValueError(f"{label}: response is not an object")
    data = payload.get("data")
    if not isinstance(data, str) or not data:
        raise ValueError(f"{label}: response carries no base64 data")
    if payload.get("isZip") is False:
        raise ValueError(f"{label}: the host returned bytes that are not a ZIP archive")
    return base64.b64decode(data)


def _parse_archive(path: Path, *, parse_stats: ParseStats | None = None) -> tuple[object, object | None]:
    """Parse one downloaded archive through the *existing* offline pipeline."""
    return _load_model(path, view=CHECKUP_VIEW, parse_stats=parse_stats)


def _load_model_online(
    args: argparse.Namespace,
    *,
    notes: list[str],
    attempts: list[dict],
    parse_stats: ParseStats | None = None,
) -> tuple[object, object | None, str, dict, dict | None] | None:
    """The online branch of model loading: A1 → A1' → A3, first success wins.

    Returns ``(model, board, tier, source_meta, attribution)``, or ``None`` when
    the online state **cannot be stated** (daemon unreachable, no connector, or
    every tier refused) — which the caller turns into exit code 3, never into an
    empty model.

    The ladder, and why in this order:

    * **A1** `sys.get_project_file` — one archive, every page and library
      document: the only tier that is exactly what a human export would be.
    * **A1'** per page: `doc.open` + `sys.get_document_file` for each page, then
      merge. Same bytes per page as A1's, one page at a time; it exists because
      A1 is gated on 工程管理 > 下载工程 while the per-page read is gated on
      工程设计图 > 文件导出 — two different grants, so one can be closed while
      the other is open (025 batch 1 measured both open on this machine).
    * **A3** `sch.netlist` + `sch.geometry` → `core/candidate.py`: connectivity
      only, no values and no MPNs, but it needs no export permission at all.

    **A2 (`sys.getDocumentSource`) is deliberately absent.** Batch 1 measured it
    (`outputs/025_probe_p2_document_source.txt`): same record grammar as an
    `.epru`, but scoped to the *focused document* and missing the SYMBOL/DEVICE
    documents a page references — the model built from it lost the footprint and
    every net (P4: `0603`/2 nets → `''`/0 nets). A tier that silently reviews a
    wrong model is worse than one that admits it has no model.
    """
    import asyncio

    BridgeClient, BridgeError, port, token = _open_cli(args)
    route_kwargs: dict[str, str] = {}
    if getattr(args, "project", ""):
        route_kwargs["target_project"] = args.project.strip()
    if getattr(args, "instance", ""):
        route_kwargs["target_instance"] = args.instance.strip()

    async def run() -> tuple[object, object | None, str, dict, str] | None:
        try:
            client = await BridgeClient.open(
                _bridge_uri(port), token, "cli", client="boardwise-cli"
            )
        except (OSError, BridgeError) as exc:
            notes.append(f"daemon not reachable on 127.0.0.1:{port} ({exc})")
            return None
        try:
            return await _checkup_ladder(client, args, route_kwargs, notes, attempts, parse_stats)
        finally:
            await client.close()

    return asyncio.run(run())


async def _checkup_ladder(
    client,
    args: argparse.Namespace,
    route_kwargs: dict,
    notes: list[str],
    attempts: list[dict],
    parse_stats: ParseStats | None,
) -> tuple[object, object | None, str, dict, str] | None:
    """One pass down the tier ladder against an open client. See `_load_model_online`."""
    import hashlib
    import tempfile
    from pathlib import Path as _Path

    BridgeError = _bridge_modules()[2]

    async def call(action: str, params: dict):
        return await client.call(action, params, **route_kwargs)

    # --- the live editor's identity, read once for the report's `source` block.
    host_version = ""
    connector_version = ""
    try:
        probe = await call("sys.probe", {"namespaces": []})
        host_version = str(probe.get("version") or "")
        connector_version = str(probe.get("connector") or "")
    except BridgeError as exc:
        attempts.append({"tier": "identity", "ok": False, "code": exc.code, "message": exc.message})
    except Exception as exc:  # noqa: BLE001 — a missing connector is an answer, not a crash
        notes.append(f"sys.probe failed: {exc}")

    project: dict = {}
    active: dict = {}
    pages: list[str] = []
    page_titles: dict[str, str] = {}
    try:
        listing = await call("doc.list", {})
        for row in listing.get("projects", []) or []:
            if row.get("focused"):
                project = {"name": row.get("name"), "friendlyName": row.get("friendlyName"),
                           "projectUuid": row.get("projectUuid")}
        active = listing.get("active") or {}
        pages = [d.get("uuid") for d in listing.get("documents", []) or []
                 if d.get("type") == "page" and d.get("uuid")]
        page_titles = {d["uuid"]: str(d.get("name") or "")
                       for d in listing.get("documents", []) or []
                       if d.get("type") == "page" and d.get("uuid")}
    except BridgeError as exc:
        attempts.append({"tier": "identity", "ok": False, "code": exc.code, "message": exc.message})
        if exc.code in ("NO_CONNECTOR", "WINDOW_NOT_CONNECTED", "WINDOW_UNSPECIFIED",
                        "PROJECT_NOT_CONNECTED", "PROJECT_AMBIGUOUS"):
            notes.append(f"doc.list: {exc.code}: {exc.message}")
            return None
    except Exception as exc:  # noqa: BLE001
        notes.append(f"doc.list failed: {exc}")

    source_meta: dict = {
        "project": project or None,
        "pageUuid": active.get("uuid"),
        "pageType": active.get("type"),
        "hostVersion": host_version,
        "connectorVersion": connector_version,
        "file": None,
    }

    with tempfile.TemporaryDirectory(prefix="boardwise-checkup-") as tmp:
        tmpdir = _Path(tmp)

        # --- A1: the whole project in one archive.
        started = time.perf_counter()
        try:
            payload = await call("sys.get_project_file", {"fileType": "epro2"})
            blob = _archive_bytes(payload, "sys.get_project_file")
            archive = tmpdir / "project.epro2"
            archive.write_bytes(blob)
            model, board = _parse_archive(archive, parse_stats=parse_stats)
            attempts.append({
                "tier": "project-file", "ok": True,
                "ms": round((time.perf_counter() - started) * 1000, 1),
                "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
                "components": len(model.components), "nets": len(model.nets),
            })
            attribution = {
                "source": PAGE_ATTRIBUTION_ARCHIVE,
                "pages": page_attribution_from_archive(archive),
            }
            return model, board, "project-file", source_meta, attribution
        except BridgeError as exc:
            attempts.append({"tier": "project-file", "ok": False, "code": exc.code,
                             "message": exc.message,
                             "ms": round((time.perf_counter() - started) * 1000, 1)})
            notes.append(
                f"project-file tier refused: {exc.code}: {exc.message} — the declaration "
                "gates getProjectFile on 工程管理 > 下载工程; falling to per-page exports "
                "(a different gate: 工程设计图 > 文件导出)"
            )
        except (ValueError, EncryptedProjectError) as exc:
            attempts.append({"tier": "project-file", "ok": False, "error": str(exc)})
            notes.append(f"project-file tier unusable: {exc}")

        # --- A1': one archive per page, merged.
        if pages:
            started = time.perf_counter()
            models = []
            page_models: dict[str, object] = {}
            page_attempts = []
            reopened: list[str] = []
            try:
                for uuid in pages:
                    try:
                        await call("doc.open", {"uuid": uuid})
                        payload = await call("sys.get_document_file", {"fileType": "epro2"})
                        blob = _archive_bytes(payload, f"sys.get_document_file({uuid})")
                        archive = tmpdir / f"page-{uuid}.epro2"
                        archive.write_bytes(blob)
                        page_model, _ = _parse_archive(archive, parse_stats=parse_stats)
                        models.append(page_model)
                        page_models[uuid] = page_model
                        reopened.append(uuid)
                        page_attempts.append({
                            "pageUuid": uuid, "ok": True, "bytes": len(blob),
                            "components": len(page_model.components),
                        })
                    except (BridgeError, ValueError, EncryptedProjectError) as exc:
                        page_attempts.append({"pageUuid": uuid, "ok": False, "error": str(exc)})
            finally:
                # The ladder moved the editor's focus; put it back where it was, so a
                # read-only command does not leave the user's editor on a different page.
                if reopened and active.get("uuid"):
                    try:
                        await call("doc.open", {"uuid": active["uuid"]})
                    except Exception as exc:  # noqa: BLE001
                        notes.append(f"could not restore focus to {active['uuid']}: {exc}")
            if models:
                merged = _merge_schematic_models(models, notes=notes)
                attempts.append({
                    "tier": "per-page", "ok": True,
                    "ms": round((time.perf_counter() - started) * 1000, 1),
                    "pages": page_attempts,
                    "components": len(merged.components), "nets": len(merged.nets),
                })
                notes.append(
                    f"per-page tier: {len(models)}/{len(pages)} page archives parsed; focus restored"
                )
                attribution = {
                    "source": PAGE_ATTRIBUTION_PER_PAGE,
                    "pages": {
                        uuid: {
                            "uuid": uuid,
                            "title": page_titles.get(uuid, ""),
                            "components": sorted(page_models[uuid].components),
                        }
                        for uuid in reopened
                    },
                }
                return merged, None, "per-page", source_meta, attribution
            attempts.append({"tier": "per-page", "ok": False, "pages": page_attempts})
            notes.append("per-page tier produced no usable page archive")
        else:
            attempts.append({"tier": "per-page", "ok": False, "error": "no page uuid was listed"})
            notes.append("per-page tier skipped: doc.list listed no schematic page")

        # --- A3: connectivity only, no export permission needed.
        started = time.perf_counter()
        try:
            from .core.candidate import (
                GeometryError,
                NetlistFormatError,
                candidate_from_geometry,
                candidate_from_netlist,
            )

            model = None
            geometry_problem = ""
            try:
                netlist = await call("sch.netlist", {"type": "EasyEDA"})
                text = netlist.get("text") if isinstance(netlist, dict) else None
                if isinstance(text, str) and text.strip():
                    model = candidate_from_netlist(text, netlist.get("type", "EasyEDA"))
            except NetlistFormatError as exc:
                geometry_problem = f"netlist unusable ({exc})"
            except BridgeError as exc:
                geometry_problem = f"netlist refused ({exc.code}: {exc.message})"
            if model is None:
                try:
                    geometry = await call("sch.geometry", {})
                    model = candidate_from_geometry(geometry)
                except GeometryError as exc:
                    geometry_problem = (geometry_problem + "; " if geometry_problem else "") + str(exc)
                except BridgeError as exc:
                    geometry_problem = (
                        f"{geometry_problem}; geometry refused ({exc.code})"
                        if geometry_problem else f"geometry refused ({exc.code})"
                    )
            if model is None:
                attempts.append({"tier": "netlist", "ok": False, "error": geometry_problem})
                notes.append(f"netlist tier gave no model: {geometry_problem}")
                return None
            attempts.append({
                "tier": "netlist", "ok": True,
                "ms": round((time.perf_counter() - started) * 1000, 1),
                "components": len(model.components), "nets": len(model.nets),
                **({"note": geometry_problem} if geometry_problem else {}),
            })
            notes.append(
                "netlist tier: connectivity only — no values, no MPNs, no poses "
                "(core/candidate.py); the report header says so"
            )
            return model, None, "netlist", source_meta, None
        except Exception as exc:  # noqa: BLE001 — the last tier failing is still an answer
            attempts.append({"tier": "netlist", "ok": False, "error": str(exc)})
            notes.append(f"netlist tier failed: {exc}")
            return None


def _cmd_checkup(args: argparse.Namespace) -> int:
    """``boardwise checkup`` — one command, an honest tier ladder, an exit code.

    Exit codes follow ``review``'s vocabulary:

    * **0** a model was obtained and nothing is an ERROR;
    * **1** something is: an ERROR-severity finding from the offline rules, a
      `fatalError`/`error` count from the host's ERC, or a leaf from its PCB DRC
      (batch 3 made this reachable — the counts and the tree now reach the
      report instead of being marked pending);
    * **2** the input cannot be used (mutually exclusive arguments, an unreadable
      `--file`, an unsupported extension);
    * **3** the online state cannot be stated (no daemon, no connector, or every
      tier refused). Never an empty model dressed up as a clean board.

    A DRC that could **not** run is not an error and not a pass: it leaves the
    section at `{checked: false, reason}` and adds no counts, so exit 0 can never
    be read as "the editor's checks passed" when they never ran.
    """
    if args.file and (args.project or args.instance):
        print(
            "boardwise checkup: --file is the offline fallback and takes no "
            "--project/--instance (give one or the other)",
            file=sys.stderr,
        )
        return 2

    out_dir = Path(args.out)
    notes: list[str] = []
    attempts: list[dict] = []
    parse_stats = ParseStats()

    if args.file:
        path = Path(args.file)
        try:
            model, _board = _load_model(path, view=CHECKUP_VIEW, parse_stats=parse_stats)
        except EncryptedProjectError as exc:
            print(f"boardwise checkup: {exc}", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(f"boardwise checkup: {path}: {exc}", file=sys.stderr)
            return 2
        tier = "file"
        source = {
            "project": None, "pageUuid": None, "pageType": None,
            "hostVersion": "", "connectorVersion": "", "file": str(path),
        }
        attempts.append({"tier": "file", "ok": True, "path": str(path),
                         "components": len(model.components), "nets": len(model.nets)})
        # No editor, so no host DRC. Both sections say *that*, rather than
        # carrying zeroes a reader could mistake for a clean board.
        drc = {
            "schematic": offline_section(
                "离线路径（--file）不连编辑器，因此没有主机 ERC；这一段的空是「没查」，不是「零错误」"
            ),
            "pcb": offline_section(
                "离线路径（--file）不连编辑器，因此没有主机 PCB DRC；要它就给一个在线工程"
            ),
        }
        attribution = {
            "source": PAGE_ATTRIBUTION_ARCHIVE,
            "pages": page_attribution_from_archive(path),
        }
        canvas: list[dict] = []
        canvas_note = "离线路径（--file）不连编辑器，因此不出画布图；要图就给一个在线工程"
        print(f"boardwise checkup: {path} ({CHECKUP_TIERS['file']})")
    else:
        loaded = _load_model_online(args, notes=notes, attempts=attempts, parse_stats=parse_stats)
        if loaded is None:
            print(
                "boardwise checkup: 在线状态不可陈述 — no tier produced a model "
                "(see the attempts below); nothing was reported as reviewed",
                file=sys.stderr,
            )
            for attempt in attempts:
                print(f"  {attempt.get('tier')}: {attempt}", file=sys.stderr)
            for note in notes:
                print(f"  note: {note}", file=sys.stderr)
            return 3
        model, _board, tier, source, attribution = loaded
        project_name = (source.get("project") or {}).get("friendlyName") or (
            (source.get("project") or {}).get("name") or "(project unknown)"
        )
        print(f"boardwise checkup: {project_name} (tier {tier} — {CHECKUP_TIERS[tier]})")

        # --- 阶段 B: the editor's own DRC, read-only, focus restored.
        #
        # Its outcome is *not* appended to `source.attempts`: that array is the
        # tier ladder's record ("which model source answered"), and the DRC reads
        # are a different question — they live in the `drc` sections, which carry
        # their own `checked`/`reason`/`elapsedMs`.
        readings = _read_online_drc(args, notes=notes)
        drc = {
            "schematic": schematic_section(readings.get("schematic", [])),
            "pcb": pcb_section(readings.get("pcb"), documents_listed=readings.get("pcbDocuments", 0)),
        }
        notes.append(
            "DRC stage: read "
            f"{len(readings.get('schematic', []))} 页 ERC + "
            f"{readings.get('pcbDocuments', 0)} 块 PCB（userInterface=false，焦点已复位）"
        )

        # --- 阶段 D（只做原理图页）：each page rendered to a PNG in --out.
        canvas = _render_canvas_images(args, out_dir, notes=notes)
        canvas_note = "" if canvas else "没有页面可出图，或每一页的 render 都失败了（见 notes）" 

    findings = [_finding_payload(finding) for finding in run_review(model)]
    summary = drc_summarise(drc=drc, findings=findings)

    # --- 阶段 C 的分组 + AI 槽位（025 §2 阶段 C/E）。
    modules, module_facts = modules_section(
        model=model,
        findings=findings,
        attribution=(attribution or {}).get("pages"),
        attribution_source=(attribution or {}).get("source", PAGE_ATTRIBUTION_UNRESOLVED),
    )
    source.update({key: value for key, value in module_facts.items() if key != "notes"})
    notes.extend(module_facts.get("notes") or [])
    slots = {
        "unknown_parts": unknown_parts(model),
        "canvas_images": canvas,
        "canvas_images_note": canvas_note,
        "summary_template": summary_template(),
    }

    report = _checkup_report(
        tier=tier, source=source, model=model, attempts=attempts, notes=notes,
        drc=drc, findings=findings, summary=summary, modules=modules, slots=slots,
    )
    report_path = _write_checkup_report(out_dir, report)
    report_md_path = _write_checkup_markdown(out_dir, report)

    print(
        f"  model: {report['model']['components']} components, {report['model']['nets']} nets "
        f"(view {CHECKUP_VIEW})"
    )
    if report["model"]["designators"]:
        print(f"  designators: {', '.join(report['model']['designators'])}")
    print(f"  drc: {_drc_line('schematic', drc['schematic'])} | {_drc_line('pcb', drc['pcb'])}")
    print(
        f"  findings: {sum(1 for f in findings if f.get('severity') == 'ERROR')} ERROR, "
        f"{sum(1 for f in findings if f.get('severity') == 'WARN')} WARN, "
        f"{sum(1 for f in findings if f.get('severity') == 'INFO')} INFO (boardwise 规则引擎)"
    )
    print(f"  attempts: " + "; ".join(
        f"{a.get('tier')} {'ok' if a.get('ok') else 'failed'}"
        + (f" ({a.get('code')})" if a.get("code") else "")
        + (f" {a.get('ms')} ms" if a.get("ms") is not None else "")
        for a in attempts
    ))
    # 报告头部 ERROR 区：先说要紧的，再看清单。
    if summary["errors"]:
        print(f"  errors: {summary['errorCount']}"
              + ("（计数不完整：有主机答复不能枚举）" if summary["countsIncomplete"] else ""))
        for entry in summary["errors"]:
            print("    " + _summary_line(entry))
    else:
        print("  errors: none")
    for note in notes:
        print(f"  note: {note}")
    print(f"  modules: {len(modules)}（basis {source.get('moduleBasis')}，"
          f"pageAttribution {source.get('pageAttribution')}）")
    for module in modules:
        print(f"    {module['name']}: {len(module['components'])} 器件"
              + (f"，findings {module['findings']}" if module.get("findings") else "")
              + (f" — {module['note']}" if module.get("note") else ""))
    print(f"  ai_slots: unknown_parts {len(slots['unknown_parts'])}，"
          f"canvas_images {len(canvas)}" + (f"（{canvas_note}）" if canvas_note else "")
          + "，summary_template 已留槽")
    print(f"  report: {report_path}")
    print(f"  report.md: {report_md_path}")
    print("  pending: none（批 4 已把 modules / ai_slots / report.md / 画布图补齐）")
    if summary["warnings"]:
        # 末尾「提醒」段：warn 不决定退出码，但决定读者下一步看哪儿。
        print(f"  reminder: {summary['warnCount']} warning(s)")
        for entry in summary["warnings"]:
            print("    " + _summary_line(entry))
    exit_code = int(summary["exitCode"])
    print(
        f"  exit: {exit_code} "
        + ("(ERROR present — see the errors above)" if exit_code else
           "(a model was obtained and nothing is an ERROR)")
    )
    return exit_code


def _finding_payload(finding: object) -> dict:
    """One finding as the report carries it — **the same shape `review --json` uses**.

    Reusing `render_json`'s two derivations (`asdict` plus `finding_refs`) rather
    than re-spelling them here: `boardwise review`'s JSON output is a contract
    other tasks read (`review-mark` consumes it), and a second spelling would let
    the two drift into disagreeing about what a finding looks like. The engine
    itself is untouched — this is the report assembling what the rule wrote.
    """
    from dataclasses import asdict

    return {**asdict(finding), "refs": finding_refs(finding)}


def _drc_line(name: str, section: dict) -> str:
    """One console line per DRC section: what was read, or why nothing was."""
    if not section.get("checked"):
        return f"{name}: not checked — {section.get('reason')}"
    if name == "schematic":
        if section.get("countsKnown") is False:
            return f"schematic: passed={section.get('passed')} (主机未给计数)"
        parts = ", ".join(
            f"{kind} {section[kind]}" for kind in ("fatalError", "error", "warn") if kind in section
        )
        return (f"schematic: {parts or 'no counts'} "
                f"[{section.get('pagesChecked')}/{section.get('pageCount')} 页, {section.get('countsBasis')}]")
    if section.get("mode") == "boolean":
        return f"pcb: passed={section.get('passed')} (主机未给逐条)"
    totals = section.get("totals", {})
    return (f"pcb: {totals.get('leafs', 0)} leaf(s) in {len(section.get('groups', []))} group(s)"
            + ("（截断）" if section.get("truncated") else ""))


def _summary_line(entry: dict) -> str:
    """One line per summary entry — count plus the reference to check it at."""
    count = entry.get("count")
    number = "count unknown" if count is None else str(count)
    label = entry.get("ruleName") or entry.get("ruleId") or entry.get("kind") or entry.get("severity")
    net = f" net {entry['net']}" if entry.get("net") else ""
    detail = f" — {entry['detail']}" if entry.get("detail") else ""
    return f"[{entry.get('severity')}] {number}x {label}{net} ({entry.get('ref')}){detail}"


def _render_canvas_images(args: argparse.Namespace, out_dir: Path, *, notes: list[str]) -> list[dict]:
    """阶段 D: one PNG per **schematic page**, written into ``--out``.

    The canvas review is 岳's division of labour (025 §0): the model reads the
    picture and judges placement, legibility and net-name clarity — so the report's
    job is to *put the pictures where it can see them*, with no interpretation
    attached.

    Three disciplines, each one earned:

    * **schematic pages only.** PCB pages are explicitly out of scope for now
      ("PCB 先不动"), so the render walks the page list and nothing else.
    * **the focus is restored in a `finally`**, like the DRC stage — a read-only
      command must not leave the editor on another tab.
    * **a failure is an entry, not an exception.** A page whose render fails, or
      comes back as something other than a PNG (a multi-document zip is the known
      shape), is recorded with its reason and the rest still render; a report with
      no images and no explanation would read like a board with nothing to show.

    Relative file names go into the slot, because the slot's reader is looking at
    `report.json` inside `--out` and a machine-specific absolute path would be
    useless in a report that gets copied elsewhere.
    """
    import asyncio
    import hashlib

    BridgeClient, BridgeError, port, token = _open_cli(args)
    route_kwargs: dict[str, str] = {}
    if getattr(args, "project", ""):
        route_kwargs["target_project"] = args.project.strip()
    if getattr(args, "instance", ""):
        route_kwargs["target_instance"] = args.instance.strip()

    async def run() -> list[dict]:
        try:
            client = await BridgeClient.open(
                _bridge_uri(port), token, "cli", client="boardwise-cli"
            )
        except (OSError, BridgeError) as exc:
            notes.append(f"canvas stage: daemon not reachable ({exc})")
            return []
        focus: str | None = None
        rendered = False
        try:
            try:
                listing = await client.call("doc.list", {}, **route_kwargs)
            except BridgeError as exc:
                notes.append(f"canvas stage: doc.list {exc.code}: {exc.message}")
                return []
            focus = (listing.get("active") or {}).get("uuid")
            pages = [(d.get("uuid"), str(d.get("name") or "")) for d in listing.get("documents") or []
                     if d.get("type") == "page" and d.get("uuid")]
            out_dir.mkdir(parents=True, exist_ok=True)
            images: list[dict] = []
            for uuid, name in pages:
                entry: dict = {"page": name or uuid, "pageUuid": uuid}
                try:
                    await client.call("doc.open", {"uuid": uuid}, **route_kwargs)
                    rendered = True
                    payload = await client.call(
                        "export.render",
                        {"format": "png", "scope": "page", "fileName": f"canvas-{_file_stem(name or uuid)}.png"},
                        **route_kwargs,
                    )
                except BridgeError as exc:
                    entry["error"] = f"{exc.code}: {exc.message}"
                    images.append(entry)
                    continue
                if not isinstance(payload, dict) or not payload.get("data"):
                    entry["error"] = "render 没有回 base64 数据"
                elif payload.get("format") != "image/png":
                    # A zip here means the editor rendered several documents; writing
                    # it as `.png` would be a lie the report's reader cannot see.
                    entry["error"] = f"render 回的是 {payload.get('format')}，不是 PNG（不落盘）"
                else:
                    import base64

                    blob = base64.b64decode(payload["data"])
                    relative = f"canvas-{_file_stem(name or uuid)}.png"
                    (out_dir / relative).write_bytes(blob)
                    entry.update({
                        "file": relative,
                        "bytes": len(blob),
                        "sha256": hashlib.sha256(blob).hexdigest(),
                    })
                images.append(entry)
            return images
        finally:
            try:
                if rendered and focus:
                    await client.call("doc.open", {"uuid": focus}, **route_kwargs)
                    notes.append(f"canvas stage: 焦点已复位到 {focus}")
            except Exception as exc:  # noqa: BLE001 — a failed restore is a note
                notes.append(f"canvas stage: 焦点复位失败（{exc}）— 编辑器可能停在别处")
            finally:
                await client.close()

    return asyncio.run(run())


def _file_stem(name: str) -> str:
    """A file-name stem safe on every platform, from a page name."""
    stem = re.sub(r"[^A-Za-z0-9._\u4e00-\u9fff-]+", "_", str(name or "")).strip("_")
    return stem[:48] or "page"


def _read_online_drc(args: argparse.Namespace, *, notes: list[str]) -> dict:
    """阶段 B: ask the editor's own two DRCs, with the focus put back.

    Read-only by construction: `doc.open` moves the focused tab and `drc.check`
    only reads (with `userInterface` left at its `false` default, so the editor's
    bottom panel is not popped open on a machine nobody is watching). Every page
    is opened before its own `sch_Drc.check`, and the **focus is restored in a
    `finally`** — a review that left the user's editor on a different page would
    be a side effect nobody asked for.

    Why per page at all, when the counts do not vary by page: batch 3 measured
    that they do not (all four pages of the test project answer `warn 1`), and
    the section reports the per-page readings *and* the invariance. Calling per
    page is the only way to *know* that, and it costs ~27 ms each.

    Returns `{"schematic": [reading…], "pcb": reading|None, "pcbDocuments": n}`.
    A failure here never fails the command: it lands in the section as
    `checked: false` with its reason.
    """
    import asyncio

    BridgeClient, BridgeError, port, token = _open_cli(args)
    route_kwargs: dict[str, str] = {}
    if getattr(args, "project", ""):
        route_kwargs["target_project"] = args.project.strip()
    if getattr(args, "instance", ""):
        route_kwargs["target_instance"] = args.instance.strip()

    async def run() -> dict:
        try:
            client = await BridgeClient.open(
                _bridge_uri(port), token, "cli", client="boardwise-cli"
            )
        except (OSError, BridgeError) as exc:
            notes.append(f"DRC stage: daemon not reachable ({exc})")
            return {"schematic": [], "pcb": None, "pcbDocuments": 0, "unreachable": str(exc)}
        try:
            try:
                listing = await client.call("doc.list", {}, **route_kwargs)
            except BridgeError as exc:
                notes.append(f"DRC stage: doc.list {exc.code}: {exc.message}")
                return {"schematic": [], "pcb": None, "pcbDocuments": 0,
                        "error": {"code": exc.code, "message": exc.message}}
            documents = listing.get("documents") or []
            pages = [d.get("uuid") for d in documents if d.get("type") == "page" and d.get("uuid")]
            pcbs = [d.get("uuid") for d in documents if d.get("type") == "pcb" and d.get("uuid")]
            focus = (listing.get("active") or {}).get("uuid")

            async def open_document(uuid: str) -> dict | None:
                try:
                    await client.call("doc.open", {"uuid": uuid}, **route_kwargs)
                    return None
                except BridgeError as exc:
                    return {"code": exc.code, "message": exc.message}

            async def read_once(action: str, uuid: str) -> dict:
                failure = await open_document(uuid)
                if failure:
                    return {"documentUuid": uuid, "error": failure}
                try:
                    payload = await client.call(action, {}, **route_kwargs)
                except BridgeError as exc:
                    return {"documentUuid": uuid, "error": {"code": exc.code, "message": exc.message}}
                return {"documentUuid": uuid, "payload": payload}

            schematic: list[dict] = []
            for uuid in pages:
                reading = await read_once("sch.drc_check", uuid)
                schematic.append({"pageUuid": uuid, **reading})
            pcb_reading = await read_once("pcb.drc_check", pcbs[0]) if pcbs else None
            if len(pcbs) > 1:
                notes.append(
                    f"doc.list 列了 {len(pcbs)} 块 PCB，本段只读第一块 {pcbs[0]}"
                    "（多板工程要把 pcb.drc_check 逐块读，留待后续）"
                )
            return {"schematic": schematic, "pcb": pcb_reading, "pcbDocuments": len(pcbs)}
        finally:
            try:
                if (focus := locals().get("focus")) and pages:
                    await client.call("doc.open", {"uuid": focus}, **route_kwargs)
                    notes.append(f"DRC stage: 焦点已复位到 {focus}")
            except Exception as exc:  # noqa: BLE001 — a restore that fails is a note
                notes.append(f"DRC stage: 焦点复位失败（{exc}）— 编辑器可能停在别处")
            finally:
                await client.close()

    return asyncio.run(run())


def _cmd_review_eval(args: argparse.Namespace) -> int:
    """Measure rules against oracle annotations (task 011a).

    Exit codes: 0 measured (the harness is an instrument, not a gate — a bad
    precision is a finding about the rules, not a CLI failure), 2 bad input
    (unreadable annotation, missing board source). A record whose rule_hint
    names an unregistered rule is **not** an error: it is listed verbatim in
    the report's "no registered rule" column and enters no denominator
    (task 011c sec.3.0) — the oracle's ground truth must not be hostage to
    rule progress.
    """
    import json as _json

    from .core.annotations import AnnotationError, load_annotations
    from .engines.review_eval import (
        SPLIT_CHOICES,
        evaluate_annotations,
        load_board_model,
        render_text_report,
    )

    # Expand the annotation arguments (paths or globs), order-stable, deduped.
    paths: list[Path] = []
    for pattern in args.annotations:
        candidate = Path(pattern)
        if candidate.is_file():
            paths.append(candidate)
            continue
        matches = sorted(Path().glob(pattern))
        if not matches:
            print(f"boardwise review-eval: no annotation file for {pattern!r}", file=sys.stderr)
            return 2
        paths.extend(match for match in matches if match.is_file())
    seen: set[Path] = set()
    ordered = [p for p in paths if not (p in seen or seen.add(p))]  # type: ignore[func-returns-value]

    try:
        sets = [load_annotations(path) for path in ordered]
    except AnnotationError as exc:
        print(f"boardwise review-eval: {exc}", file=sys.stderr)
        return 2

    from .engines.review import BUILTIN_RULES

    if args.split not in SPLIT_CHOICES:
        print(f"boardwise review-eval: --split must be one of {SPLIT_CHOICES}", file=sys.stderr)
        return 2

    models: dict[str, object] = {}
    evaluations = []
    for aset in sets:
        try:
            model = models.get(aset.source)
            if model is None:
                model = load_board_model(aset.source)
                models[aset.source] = model
        except (FileNotFoundError, ValueError) as exc:
            print(f"boardwise review-eval: {exc}", file=sys.stderr)
            return 2
        evaluations.append(
            evaluate_annotations(
                aset, model, BUILTIN_RULES, split=args.split  # type: ignore[arg-type]
            )
        )

    print(
        render_text_report(
            evaluations,
            split=args.split,
            rule_ids=[rule.id for rule in BUILTIN_RULES],
        ).rstrip("\n")
    )
    if args.json_path:
        payload = {
            "split": args.split,
            "boards": [
                {
                    "board": evaluation.board,
                    "source": evaluation.source,
                    "reviewed": evaluation.reviewed,
                    "components": evaluation.component_count,
                    "nets": evaluation.net_count,
                    "findings": evaluation.severity_counts,
                    "queries_excluded": evaluation.queries,
                    "holdout_excluded": evaluation.excluded_holdout,
                    "cross_matches": evaluation.cross_matches,
                    "rules": [
                        {
                            "rule_id": metric.rule_id,
                            "defects_hinted": metric.defects_hinted,
                            "detected": metric.detected,
                            "missed": metric.missed,
                            "caught_by_other": metric.caught_by_other,
                            "exceptions_hinted": metric.exceptions_hinted,
                            "fp_on_exception": metric.fp_on_exception,
                            "fp_unexplained": metric.fp_unexplained,
                            "violations": metric.violations,
                            "precision": metric.precision,
                            "recall": metric.recall,
                            # High-priority (ERROR/WARN) findings: the
                            # determinate claims the graduation metric grades
                            # (011e sec.4.1).
                            "hp_findings": metric.hp_findings,
                            "hp_true_positives": metric.hp_tp,
                            "hp_false_positives_explained": metric.hp_fp_exception,
                            "hp_false_positives_unexplained": metric.hp_fp_unexplained,
                            "hp_precision": metric.hp_precision,
                            "outcomes": metric.outcome_counts,
                        }
                        for metric in evaluation.metrics
                    ],
                }
                for evaluation in evaluations
            ],
        }
        Path(args.json_path).write_text(
            _json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"JSON report written to {args.json_path}")
    return 0


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
    # `WebSocketException`, not just `OSError`: a port that belongs to some
    # *other* process accepts the TCP connection and then fails the WebSocket
    # handshake — `websockets` raises `InvalidMessage` ("did not receive a valid
    # HTTP response"), which is not an `OSError`, so it used to escape as a
    # traceback. From the user's seat the two are one fact: nothing that talks
    # like our daemon answered. Imported here rather than at module scope
    # because offline review must keep working with `websockets` uninstalled.
    from websockets.exceptions import WebSocketException

    _, daemon_module, _ = _bridge_modules()

    async def run() -> int:
        try:
            client = await BridgeClient.open(
                _bridge_uri(port), token, "cli", client="boardwise-cli"
            )
        except (OSError, WebSocketException, BridgeError) as exc:
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
        # Every online editor window, with its project and page (023). Rendered by
        # the daemon's ``status_lines`` rather than here, so the wording cannot
        # drift from the keys it reads; empty when there is nothing to say, so a
        # fresh daemon prints exactly what it did before. This is the list a
        # caller reads to pick the `--project` hint for `bridge call`.
        for line in daemon_module.status_lines(data):
            print(line)
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


class FabWriteError(Exception):
    """The fab bundle could not be written to disk."""


def _write_fab_bundle(payload: object, out_dir: Path) -> dict:
    """Write an ``export.fab`` payload into ``out_dir``; report what landed.

    Deliberately a **pure file operation**, separated from the socket call so
    the part that can destroy something is testable without a daemon. Three
    rules, each learned the hard way elsewhere:

    - **A file name is one path segment.** The name comes from the editor in one
      case (a host-named gerber archive), so a name like ``../../x`` would write
      outside the directory the user asked for; it is refused rather than
      sanitised, because a silent rename is a worse surprise than a failure.
    - **Every entry is decoded, then measured on disk.** ``written[].bytes`` is
      the size ``stat`` reports, and a disagreement with the connector's own
      ``bytes`` is reported instead of assumed away — a base64 bug would
      otherwise look like a successful export.
    - **The manifest is written last and enriched here**: ``outDir`` resolved and
      ``written`` filled in with the measured sizes, so a directory found later
      says where it went and what actually arrived.
    """
    import base64
    import json

    if not isinstance(payload, dict):
        raise FabWriteError(f"the connector returned {type(payload).__name__}, not a payload")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise FabWriteError(
            "the connector returned no files to write "
            f"(failed: {json.dumps(payload.get('failed'), ensure_ascii=False)})"
        )
    out_dir = Path(out_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FabWriteError(f"cannot create {out_dir}: {exc}") from exc

    written: list[dict] = []
    mismatched: list[str] = []
    for entry in files:
        if not isinstance(entry, dict):
            raise FabWriteError(f"a file entry is {type(entry).__name__}, not an object")
        name = str(entry.get("name") or "")
        if not name or name != Path(name).name or name in (".", ".."):
            raise FabWriteError(
                f"refusing to write {name!r}: a bundle file name must be a single "
                "path segment"
            )
        data = entry.get("data")
        if not isinstance(data, str) or not data:
            raise FabWriteError(f"{name}: the connector sent no data")
        try:
            blob = base64.b64decode(data, validate=True)
        except (ValueError, TypeError) as exc:
            raise FabWriteError(f"{name}: data is not base64 ({exc})") from exc
        target = out_dir / name
        try:
            target.write_bytes(blob)
            size = target.stat().st_size
        except OSError as exc:
            raise FabWriteError(f"cannot write {target}: {exc}") from exc
        declared = entry.get("bytes")
        if isinstance(declared, int) and declared != size:
            mismatched.append(name)
        written.append({
            "name": name,
            "role": entry.get("role"),
            "bytes": size,
            "declaredBytes": declared if isinstance(declared, int) else None,
        })

    manifest = payload.get("manifest")
    manifest = dict(manifest) if isinstance(manifest, dict) else {}
    manifest["outDir"] = str(out_dir)
    manifest["written"] = written
    if mismatched:
        manifest["byteCountMismatch"] = mismatched
    manifest_path = out_dir / "manifest.json"
    try:
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        raise FabWriteError(f"cannot write {manifest_path}: {exc}") from exc
    return {
        "outDir": str(out_dir),
        "written": written,
        "manifest": str(manifest_path),
        "mismatched": mismatched,
        "project": manifest.get("project"),
        "pcb": manifest.get("pcb"),
        "generatedAt": manifest.get("generatedAt"),
    }


def _cmd_bridge_export_fab(args: argparse.Namespace) -> int:
    """`bridge export-fab` — call `export.fab` and put the bundle on disk.

    Exit codes follow the rest of `boardwise bridge`: 2 when the daemon is not
    reachable, 1 when the action failed **or** when the bundle came back
    incomplete/broken, 0 only when every file and the manifest landed. A partial
    bundle is a failure here even though the files that did arrive are kept:
    a fab house cannot do anything with two of three files, and a caller reading
    the exit code must not have to parse the output to find that out.
    """
    import asyncio
    import json

    BridgeClient, BridgeError, port, token = _open_cli(args)
    params: dict = {"outDir": str(args.out), "vendor": args.vendor}
    if args.pcb:
        params["pcbUuid"] = args.pcb
    if args.bom_template:
        params["bomTemplate"] = args.bom_template
    if args.timeout_ms is not None:
        params["timeoutMs"] = args.timeout_ms
    if args.gerber:
        try:
            gerber = json.loads(args.gerber)
        except json.JSONDecodeError as exc:
            print(f"boardwise bridge export-fab: --gerber is not JSON ({exc})", file=sys.stderr)
            return 2
        if not isinstance(gerber, dict):
            print("boardwise bridge export-fab: --gerber must be a JSON object", file=sys.stderr)
            return 2
        params["gerber"] = gerber

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
            data = await client.call("export.fab", params)
        except BridgeError as exc:
            print(
                f"boardwise bridge export-fab: export.fab failed [{exc.code}] {exc.message}",
                file=sys.stderr,
            )
            return 1
        finally:
            await client.close()

        try:
            result = _write_fab_bundle(data, Path(args.out))
        except FabWriteError as exc:
            print(f"boardwise bridge export-fab: {exc}", file=sys.stderr)
            return 1

        failed = data.get("failed") if isinstance(data, dict) else None
        for item in failed or []:
            if isinstance(item, dict):
                print(
                    f"boardwise bridge export-fab: MISSING {item.get('role')}: {item.get('reason')}",
                    file=sys.stderr,
                )
        for entry in result["written"]:
            print(f"boardwise bridge export-fab: wrote {entry['name']} "
                  f"({entry['bytes']} B, {entry['role']})")
        print(
            f"boardwise bridge export-fab: {len(result['written'])} file(s) + manifest.json "
            f"in {result['outDir']}"
        )
        if result["mismatched"]:
            print(
                "boardwise bridge export-fab: byte counts disagree with the connector for "
                f"{', '.join(result['mismatched'])} — the files landed but the transfer is suspect",
                file=sys.stderr,
            )
            return 1
        if failed:
            return 1
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
    templates (008a): the spec first passes the product validation gates
    (009-M0 P0 — sources, pin budget, levels, power tree; a refused spec draws
    nothing), and ``--golden`` then turns on the double-check that the
    specification reproduces the golden's connectivity — both run *before* a
    single bridge call, because a draw that starts from an unverified
    specification just produces a page nobody can trust.
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
        from boardwise.core.parts import PartError, load_parts
        from boardwise.core.portmeta import PortMetaError, load_port_meta
        from boardwise.engines.assemble import assemble, assembly_lines
        from boardwise.engines.validate_spec import validate_spec

        # The product validation gates run before anything is assembled or
        # sent (009-M0 P0): a spec that fails them is refused with zero
        # writes — no assembly, no double check, and above all no bridge call.
        # The closed book deliberately stays out of this: it grades generation
        # benchmarks (`validate --benchmark`), not a board someone is drawing.
        # Nothing is cached — the report is bound to the file's current bytes
        # by the sha256 it prints, and every run re-reads them.
        port_meta = None
        if args.port_meta and Path(args.port_meta).is_file():
            try:
                port_meta = load_port_meta(args.port_meta)
            except PortMetaError as exc:
                print(f"boardwise draw: {exc}", file=sys.stderr)
                return 2
        try:
            spec = load_board_spec(args.spec, port_meta=port_meta)
        except BlockError as exc:
            print(f"boardwise draw: {args.spec}: {exc}", file=sys.stderr)
            return 2
        library = None
        if args.library:
            try:
                library = load_parts(args.library)
            except PartError as exc:
                print(f"boardwise draw: {args.library}: {exc}", file=sys.stderr)
                return 2
        validation = validate_spec(
            spec,
            library=library,
            # Declared inputs resolve beside the spec, same as its block
            # templates do; a new board has no other root to name.
            root=Path(args.spec).resolve().parent,
        )
        for line in validation.render():
            print(line)
        if not validation.ok:
            print(
                "boardwise draw: the spec failed validation; nothing was executed",
                file=sys.stderr,
            )
            return 2
        try:
            design = assemble(spec)
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

        code = _render_draw_result(result, args, assembly_report=assembly_report)
        _audit_draw_persistence(result, code)
        return code

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


def _cmd_persistence(args: argparse.Namespace) -> int:
    """Snapshot the live page, and compare it across a real close-and-reopen.

    Read-only on both legs (``sch.netlist`` + ``sch.geometry``), so measuring
    is not also changing. Exit 0 identical / 1 different / 2 bad input or an
    unreachable editor / 3 could not decide.

    Why this exists at all: `saved_verified` is the only persistence state that
    means the bytes reached the file, and **no bridge action can establish it**
    (M0-P0d audit E). The reopen is therefore a human act, and this command is
    what turns that act's result into an exit code instead of an eyeball.
    """
    import asyncio
    import json

    if not args.out and not args.baseline:
        print(
            "boardwise persistence: give --out <file> to snapshot, --baseline <file> "
            "to compare against one, or both",
            file=sys.stderr,
        )
        return 2

    BridgeClient, BridgeError, port, token = _open_cli(args)

    async def run() -> int:
        try:
            client = await BridgeClient.open(
                _bridge_uri(port), token, "cli", client="boardwise-cli"
            )
        except (OSError, BridgeError) as exc:
            print(
                f"boardwise persistence: daemon not reachable on 127.0.0.1:{port} ({exc})",
                file=sys.stderr,
            )
            return 2
        try:
            current = {
                "netlist": await client.call("sch.netlist", {"type": "EasyEDA"}),
                "geometry": await client.call("sch.geometry", {}),
            }
        except BridgeError as exc:
            print(f"boardwise persistence: {exc.code}: {exc.message}", file=sys.stderr)
            return 2
        finally:
            await client.close()

        if args.out:
            Path(args.out).write_text(
                json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"snapshot: {args.out}")
            print(
                "  next: close the project in the editor, reopen it, then re-run "
                f"with --baseline {args.out}"
            )
        if not args.baseline:
            return 0

        try:
            baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"boardwise persistence: {args.baseline}: {exc}", file=sys.stderr)
            return 2
        return _compare_persistence(baseline, current)

    return asyncio.run(run())


def _compare_persistence(baseline: dict, current: dict) -> int:
    """0 identical / 1 different / 3 could not decide.

    Two independent halves, because they fail independently: the **netlist**
    (connectivity, parsed by the same reader the diff uses) and a **primitive
    census** from the geometry dump. A missing half is *undecidable*, never a
    pass — "we could not look" and "it is identical" are the two answers this
    must never blur, which is also the reason the census is compared rather
    than the raw dumps: the dumps carry generated ids that change every render.
    """
    from boardwise.core.candidate import NetlistFormatError, candidate_from_netlist
    from boardwise.core.compare import compare_models
    from boardwise.engines.draw import geometry_fingerprint, fingerprint_total

    models: dict[str, object] = {}
    for side, snapshot in (("baseline", baseline), ("reopened", current)):
        netlist = snapshot.get("netlist") or {}
        text = netlist.get("text")
        if not isinstance(text, str) or not text.strip():
            print(
                f"boardwise persistence: {side} has no netlist text — cannot decide. "
                "The editor returns nothing for a never-saved project (measured "
                "2026-09-13), which is the shape a failed save leaves behind.",
                file=sys.stderr,
            )
            return 3
        try:
            models[side] = candidate_from_netlist(text, netlist.get("type", "EasyEDA"))
        except NetlistFormatError as exc:
            print(f"boardwise persistence: {side} netlist: {exc}", file=sys.stderr)
            return 3

    report = compare_models(models["baseline"], models["reopened"])
    if not report.is_empty:
        print("boardwise persistence: the reopened page is NOT what was drawn:")
        print(report.render())
        print("persistence: NOT saved_verified — the reopened content differs")
        return 1

    census = {
        side: geometry_fingerprint(snapshot.get("geometry"))
        for side, snapshot in (("baseline", baseline), ("reopened", current))
    }
    if not census["baseline"] or not census["reopened"]:
        print(
            "boardwise persistence: the primitive census came back empty on one "
            "side — cannot decide",
            file=sys.stderr,
        )
        return 3
    if census["baseline"] != census["reopened"]:
        print("boardwise persistence: the reopened page's primitives differ:")
        for name in sorted(set(census["baseline"]) | set(census["reopened"])):
            before = census["baseline"].get(name, 0)
            after = census["reopened"].get(name, 0)
            if before != after:
                print(f"  {name}: {before} -> {after}")
        print("persistence: NOT saved_verified")
        return 1

    reopened = models["reopened"]
    print(
        "boardwise persistence: the reopened page matches the snapshot "
        f"({len(reopened.components)} components, {len(reopened.nets)} nets, "
        f"{fingerprint_total(census['reopened'])} primitives)"
    )
    print("persistence: saved_verified — the content survived a close-and-reopen")
    _audit_persistence_verified(reopened, census["reopened"])
    return 0


def _audit_persistence_verified(model: object, census: dict) -> None:
    """The one record in the log that may say ``saved_verified`` outright.

    Written by the CLI, like ``bridge revoke``'s record, because the daemon
    cannot see across a reopen: it holds no connection while the editor is
    closed. Never raises — a log that can fail a check is worse than no line.
    """
    try:
        _, daemon_module, _ = _bridge_modules()
        from boardwise.engines.draw import fingerprint_total

        daemon_module.append_audit(
            None,
            action=daemon_module.AUDIT_PERSISTENCE_VERIFIED,
            role="cli",
            ok=True,
            persistence="saved_verified",
            components=len(model.components),
            nets=len(model.nets),
            primitives=fingerprint_total(census),
        )
    except (Exception, SystemExit):  # noqa: BLE001 — logging must not break a run
        pass


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


def _audit_draw_persistence(result: object, exit_code: int) -> None:
    """Put the persistence state in the audit log, not only on stdout.

    The daemon's own per-action records carry ``ok`` and nothing about
    persistence: an action can be ``ok: true`` while nothing was ever saved, and
    the save's payload never reaches the log because the daemon does not record
    action `data` (audit F, 2026-09-18). So "did this run persist anything?"
    has to be written by the process that knows the answer — the same way
    ``bridge revoke`` records its own outcome from the CLI.

    One field, one vocabulary: ``persistence`` carries the state name and
    nothing in this record says "saved" unless the state is ``saved_verified``.
    Never raises (and swallows the websockets-missing ``SystemExit``): a log
    that can fail a draw is worse than a missing line.
    """
    try:
        _, daemon_module, _ = _bridge_modules()
        daemon_module.append_audit(
            None,
            action=daemon_module.AUDIT_DRAW_PERSISTENCE,
            role="cli",
            ok=exit_code == 0,
            persistence=result.persistence,
            exitCode=exit_code,
            saveAccepted=result.save_ok,
            saveVerified=result.persistence == "saved_verified",
            # What is *known* to be on the page, and what cannot be stated. The
            # acknowledged count is the field that contradicts "nothing was
            # written" straight from the log, without needing the terminal
            # scrollback (M0-P0d follow-up, 2026-09-18).
            writesAcknowledged=len(result.acknowledged_writes),
            writesUnknown=[record.action for record in result.unknown_writes],
            timeouts=[record.action for record in result.timeouts],
        )
    except (Exception, SystemExit):  # noqa: BLE001 — logging must not break a draw
        pass


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

    # --- persistence: the facts about the write, and this run only has some.
    #
    # Silence here was the bug: with nothing printed, a reader takes "no
    # complaint" as "saved". The state is named, defined, and the audit log
    # gets the same answer so it survives the terminal (M0-P0d).
    from boardwise.engines.draw import PERSISTENCE_UNKNOWN, PERSISTENCE_WORDS

    persistence = result.persistence
    print(f"\npersistence: {persistence} — {PERSISTENCE_WORDS[persistence]}")
    if persistence == PERSISTENCE_UNKNOWN:
        # Say *which* writes are unaccounted for, and say what is known to be on
        # the page. "unknown" alone still leaves a reader unable to decide
        # whether redrawing is safe, and redrawing onto parts that are already
        # there is the damage this state exists to prevent.
        acknowledged = result.acknowledged_writes
        print(
            f"  {len(acknowledged)} write(s) were acknowledged before the run "
            "stopped — their content IS on the page:"
        )
        for record in acknowledged:
            print(f"    {record.action}: {record.summary}")
        print(
            f"  ! {len(result.unknown_writes)} write(s) never answered — do NOT "
            "assume they are absent, and do not redraw onto this page before "
            "looking at it:"
        )
        for record in result.unknown_writes:
            print(f"    {record.action}: {record.summary}")
    if persistence != "saved_verified":
        print(
            "  only a close-and-reopen that compares equal makes this "
            "saved_verified; see docs/persistence-baseline.md for the procedure"
        )

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
    if result.timeouts or persistence == PERSISTENCE_UNKNOWN:
        # A write the daemon gave up on, or one whose answer never arrived, may
        # still have landed — so whatever the diff says, this run's outcome is
        # "we cannot say". Exit 3 outranks both 0 and 1 for the same reason:
        # "the diff differed" is a claim about a page whose contents we are no
        # longer sure of. 3 is not 2 — 2 means nothing was executed, 3 means we
        # do not know what was (M0-P0d follow-up, 2026-09-18).
        print(
            "\nexit 3: a write's outcome is unknown (a call the daemon stopped "
            "waiting for, or one whose connection died) — the page's state "
            "cannot be stated, so this is not a pass"
        )
        exit_code = 3
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
    """Run the validation gates (task 008c, item 4; 009-M0 P0).

    Exit 0 when nothing blocks, 1 when a violation or an undecidable result
    does, 2 for bad input. Undecidable blocks because "we cannot tell" and "it
    is fine" must never look the same in a report somebody has to act on. The
    closed book runs only under ``--benchmark``: it grades generation runs,
    and a user validating a new board has no target to name.
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
        benchmark=args.benchmark,
    )
    if args.json:
        print(_json.dumps(report.as_json(), indent=2, ensure_ascii=False))
    else:
        for line in report.render():
            print(line)
        if args.benchmark and not args.target:
            print(
                "note: --benchmark without --target leaves the closed-book gate "
                "undecidable (this is not a pass). Name the board being "
                "generated — every alias of it.",
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


#: The verification phase's clock (task 020 §WI-2), read when the phase runs —
#: not baked into a default argument — so a test can shrink it to nothing.
#:
#: One read of the daemon's window table per second, for thirty seconds. In
#: practice the reloaded page re-pairs in a second or two, while a *closed* editor
#: never comes back: the budget is what keeps that case from hanging a script, and
#: thirty seconds is the point where "not back yet" stops being plausible.
#: Nothing here is on a write path — the write has already landed, this only reads.
UPDATE_VERIFY_INTERVAL_S = 1.0
UPDATE_VERIFY_BUDGET_S = 30.0
#: Settle time on top of the reply's own ``reloadInMs`` before the first read.
#: Waiting it out is what makes the first read *useful* (until the reload timer
#: fires, the table still lists the old socket), but it is no longer what keeps a
#: correct update from reading as a failure: that is `_reload_verdict`'s rule,
#: because the editor took five seconds to come back when this was measured and
#: any margin is a guess (025 batch 2's false FAILED was exactly that guess).
UPDATE_RELOAD_MARGIN_S = 0.5


def _connector_artifacts() -> tuple[Path, Path]:
    """``(bundle, extension.json)`` paths of the connector build this install ships.

    Resolved through :mod:`boardwise.resources`, so the answer is the in-repo
    build when boardwise runs from a checkout and the *embedded* copy when it
    runs from the frozen exe (028 batch 3a). Before that the two paths were
    computed here from ``Path(__file__).parents[2]``, which is right from a
    checkout and points into the PyInstaller extraction directory from an exe —
    the one resolution the single exe cannot get wrong, since it carries no repo.
    """
    from . import resources

    try:
        return resources.connector_bundle(), resources.connector_extension_json()
    except RuntimeError:
        # A frozen process that cannot name its own extraction directory. Return
        # the paths anyway: every caller reports them (that is how the friend
        # learns what is missing), and inventing a different answer here would
        # only hide the bootstrap problem.
        root = Path(__file__).resolve().parents[2]
        return (
            root / "connector" / "dist" / "index.js",
            root / "connector" / "extension.json",
        )


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

    **The command does not stop at "the daemon accepted the write"** (task 020
    §WI-2). That reply says the bytes were stored, not that they are running —
    it was a "fake success window": the old build keeps answering every action
    perfectly. So after the write the command waits, bounded, and reads the
    daemon's **window table** (:func:`_await_running_connector_version` →
    :func:`_reload_verdict`), which says per window which build each connection
    announces. Three outcomes, and the codes are 020's:

    * a window announces the stored version → ``verified: running connector is
      now X.Y.Z``, exit 0;
    * a connection that came back **after** the write announces a *different*
      build → the page reloaded onto the wrong build, exit 1;
    * nothing conclusive inside the budget → the state cannot be stated, exit 3,
      named on stderr.

    The middle one is the only way to reach exit 1, and that restriction is the
    fix this command needed (025 batch 2's carried-over todo): the window the
    write went to stays online under its old name until the editor tears the page
    down — **five seconds**, measured — and reading that lingering socket as "the
    write did not take effect" reported a successful update as FAILED. "Still
    here" is "not yet"; only "came back different" is evidence
    (:func:`_reload_verdict`).

    ``--no-verify`` restores the old behaviour (print "ok", return 0) for
    callers that would rather poll themselves.

    ``--instance`` (023) aims the write at **one** window. The read-back is the
    same either way, deliberately: the updated window reconnects under a new
    instance id, so it cannot be addressed by the old name, and a routed
    ``sys.probe`` in a multi-window session could be answered by *any* window —
    the table is the only read that keeps the facts per window.
    """
    import asyncio

    BridgeClient, BridgeError, port, token = _open_cli(args)
    instance = (args.instance or "").strip()

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
        # Which window this is aimed at, before anything is written: with several
        # windows open, "which one did that land in?" is the first thing a reader
        # of the log wants, and after the reload the window can no longer be asked.
        + (f" -> window {instance}" if instance else "")
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
        # **Who is online before the write** — the read-back's "already here" set.
        # It has to be taken first: after the write, "has this socket reloaded?"
        # can only be answered against what the table looked like before, because
        # a reload *replaces* the connection (a new instance id) while the old
        # socket lingers for as long as the editor takes to tear the page down
        # (see `_reload_verdict`). `None` = the table could not be read, and then
        # no mismatch can be claimed at all.
        online_before = _snapshot_identities(
            await _online_windows(BridgeClient, BridgeError, port, token)
        )
        try:
            # `--instance` routes the hot update itself; without it the call is
            # unhinted, exactly as it was before the flag existed.
            data = await client.call(
                "sys.self_update",
                params,
                **({"target_instance": instance} if instance else {}),
            )
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
        if args.no_verify:
            print(
                "  the editor page is reloading now; the new build should "
                "reconnect within seconds — verify with `boardwise bridge status` "
                "or the About… menu (version line)"
            )
            return 0

        expected = str(params["version"])
        running = await _await_running_connector_version(
            BridgeClient,
            BridgeError,
            port,
            token,
            reload_ms=data.get("reloadInMs") or 0,
            interval_s=UPDATE_VERIFY_INTERVAL_S,
            budget_s=UPDATE_VERIFY_BUDGET_S,
            margin_s=UPDATE_RELOAD_MARGIN_S,
            expected=expected,
            before=online_before,
        )
        if running is None:
            print(
                f"boardwise bridge update-connector: the connector did not come "
                f"back within {UPDATE_VERIFY_BUDGET_S:.0f}s — the state of the "
                f"write is UNKNOWN, not failed: the editor may be closed, or the "
                f"page may still be reloading. Re-check with `boardwise bridge "
                f"status` (or run doctor) before trusting either answer",
                file=sys.stderr,
            )
            return 3
        if running != expected:
            # The only way to reach this branch: a connection that was **not**
            # online before the write announced a different build. The old socket
            # being still there is no longer evidence of anything but "not yet"
            # (025 batch 2's false FAILED), so this is a real reload onto the
            # wrong build, and the reader is told which window it was aimed at.
            print(
                f"boardwise bridge update-connector: FAILED — the write stored "
                f"{expected} but a connector that (re)connected after the write "
                f"announces {running}: the page came back on a build other than "
                f"the one just stored"
                + (f" (the write was aimed at window {instance})" if instance else "")
                + ". The old socket being replaced is what makes this evidence "
                "rather than a reload still in flight; `boardwise bridge status` "
                "names every online window's version",
                file=sys.stderr,
            )
            return 1
        print(f"  verified: running connector is now {running}")
        return 0

    return asyncio.run(run())


async def _online_windows(BridgeClient, BridgeError, port: int, token: str) -> list[dict] | None:
    """The daemon's window table from ``ping``, or ``None`` if it cannot be read.

    ``ping`` is answered by the daemon itself, so this read needs no routing —
    which is the whole point: it works at the moment routing cannot, while the
    window an update was sent to has reloaded and its replacement has not
    arrived yet. ``None`` (daemon unreachable) and ``[]`` (no window connected)
    are kept apart because they are different facts, and the caller's deadline
    treats both as "nothing to read yet".
    """
    try:
        client = await BridgeClient.open(
            _bridge_uri(port), token, "cli", client="boardwise-cli"
        )
    except (OSError, BridgeError):
        return None
    try:
        data = await client.call("ping")
    except BridgeError:
        return None
    finally:
        await client.close()
    if not isinstance(data, dict):
        return None
    windows = data.get("windows")
    if not isinstance(windows, list):
        return []
    return [window for window in windows if isinstance(window, dict)]


def _text(value: object) -> str:
    """One wire field as a stripped string; ``None``/absent becomes ``""``."""
    return str(value).strip() if isinstance(value, str) else ""


#: What the reload read-back can conclude, and what the caller does with each.
#:
#: ``verified`` — a window is announcing the stored version; exit 0.
#: ``mismatch`` — a connection that came back *after* the write is announcing a
#: different build; exit 1. Only reachable with that "after" evidence, which is
#: what this pair of names is about.
RELOAD_VERIFIED = "verified"
RELOAD_MISMATCH = "mismatch"


def _window_names(window: dict) -> set[str]:
    """Every name one window answers to: its hub key and its claimed instance id."""
    names: set[str] = set()
    for key in ("windowKey", "instanceId"):
        text = _text(window.get(key))
        if text:
            names.add(text)
    return names


def _snapshot_identities(windows: list[dict] | None) -> frozenset[str] | None:
    """Who was online **before** the write, or ``None`` when that could not be read.

    The distinction matters in one direction only, and it is the whole point of
    this task: `None` disables the mismatch verdict, because "a connection came
    back on another build" is a claim *about a connection that was not there
    before* and cannot be made without knowing who was.
    """
    if windows is None:
        return None
    names: set[str] = set()
    for window in windows:
        names |= _window_names(window)
    return frozenset(names)


async def _reload_verdict(
    BridgeClient,
    BridgeError,
    port: int,
    token: str,
    *,
    expected: str,
    before: frozenset[str] | None,
) -> tuple[str, str] | None:
    """One read of the daemon's window table, as `(verdict, version)` or ``None``.

    The question is "did the stored build come back?", and the table answers it
    **per window**, which is what makes the distinction this function exists for
    possible:

    * some window announces ``expected`` → `(verified, version)`. The reloaded
      window reconnects under a **new instance id** (the connector mints one per
      page load), so it cannot be recognised as the window the write went to —
      and an unhinted routed read could be answered by *any* window in a
      multi-window session. Reading the table avoids both problems.
    * a window that was **not** online before the write announces something else
      → `(mismatch, version)`: the page did reload, and what came back is not
      what was stored. That is the evidence 020 §WI-2 wanted to surface.
    * only windows from the pre-write snapshot → ``None`` = "not back yet". A
      reload **destroys** the socket, so a window still online under its old name
      has not reloaded; it is not evidence that the write failed.

    Measured on the machine (2026-09-23, `outputs/025b_routed.txt`): the write
    lands and the reloaded connector says hello **five seconds** later, with the
    old socket answering the whole time. Before this rule existed, the first read
    inside that window was taken as a verdict and a successful update was
    reported as FAILED — the false alarm 025 batch 2 carried over.
    """
    windows = await _online_windows(BridgeClient, BridgeError, port, token)
    if windows is None:
        return None
    for window in windows:
        version = _text(window.get("connectorVersion"))
        if version and version == expected:
            return RELOAD_VERIFIED, version
    if before is None:
        # No snapshot: every window looks new, and claiming a mismatch here is
        # exactly the false FAILED this rule removes. Stay silent and let the
        # deadline answer "unknown".
        return None
    for window in windows:
        version = _text(window.get("connectorVersion"))
        if not version or (_window_names(window) & before):
            continue
        return RELOAD_MISMATCH, version
    return None


async def _await_running_connector_version(
    BridgeClient,
    BridgeError,
    port: int,
    token: str,
    *,
    reload_ms: float,
    interval_s: float,
    budget_s: float,
    margin_s: float,
    expected: str = "",
    before: frozenset[str] | None = None,
) -> str | None:
    """Wait for the reloaded connector and return the version it reports.

    The reload is on a timer — the ``sys.self_update`` reply carries it as
    ``reloadInMs`` (500 in practice) — and until it fires the **old** build is
    still attached and answers with the *old* version. So the first read waits out
    that window plus a margin; but the margin is a heuristic (the editor took 5 s
    to come back when this was measured), which is why the loop no longer treats
    "an old version came back" as a verdict at all: a still-attached socket is
    "not yet", and only a *reconnected* window can produce a mismatch
    (:func:`_reload_verdict`).

    After that it is one read per ``interval_s`` until ``budget_s`` runs out.
    ``None`` means the budget expired with nothing conclusive — "unknown", which
    is not the same claim as "failed".

    ``before`` is the set of windows that were online *before* the write
    (:func:`_snapshot_identities`); ``None`` means that snapshot could not be
    taken, and then this function can only ever answer verified-or-unknown.

    The three timings are **required** keyword arguments rather than defaults
    read from the module constants at import time: the caller
    (:func:`_cmd_bridge_update_connector`) looks them up when it runs, which is
    what lets a test shrink the clock to nothing and still exercise this exact
    function (defaults would freeze the 30 s production budget into the test).
    """
    import asyncio
    import time

    deadline = time.monotonic() + budget_s
    await asyncio.sleep(max(reload_ms, 0) / 1000.0 + margin_s)
    while True:
        verdict = await _reload_verdict(
            BridgeClient, BridgeError, port, token, expected=expected, before=before
        )
        if verdict is not None:
            return verdict[1]
        if time.monotonic() + interval_s >= deadline:
            return None
        await asyncio.sleep(interval_s)


def _cmd_bridge_call(args: argparse.Namespace) -> int:
    """Generic action probe (006): one call, the raw payload, exit 0/1/2.

    Also the scripting surface for `create` actions (006c): the daemon refuses
    those without an explicit confirmation, and this command is where a human
    gets asked. `--yes` is the escape hatch for scripts, and it is deliberately
    a flag rather than a prompt — a non-interactive caller should have to say
    so out loud.

    `--project` (023) is the window hint: with three or four editor windows open,
    "which project?" is the caller's to answer, and the daemon refuses a call
    that does not answer it rather than picking one. The hint travels **top
    level** on the request frame as ``targetProject`` and never inside `params`,
    so it cannot be mistaken for something the connector is being asked to do.

    `--instance` is the same hint spelled with the window's own instance id (the
    ``windowKey`` `bridge status` prints), for the case the project hint cannot
    cover at all: measured 2026-09-22, an editor that restarts has its windows
    greet the daemon before the editor API is ready, so every window's project
    reads as unknown and *no* `--project` value matches anything. The instance id
    is in the `hello` params, so it is always there. It rides the frame as the
    sibling top-level field ``targetInstance``; when both flags are given the
    daemon prefers the instance, and the caller is told which window answered by
    the response's own `context`.
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
    # Built once and reused by the confirmation retry: both sends have to name
    # the same window, or "yes" would retry the call against a *different*
    # window than the one the daemon refused to create a document in.
    project = (args.project or "").strip()
    instance = (args.instance or "").strip()
    route_kwargs: dict[str, str] = {}
    if project:
        route_kwargs["target_project"] = project
    if instance:
        route_kwargs["target_instance"] = instance

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
                data = await client.call(args.action, params, **route_kwargs)
            except BridgeError as exc:
                if (
                    exc.code == ErrorCodes.CONFIRMATION_REQUIRED
                    and params.get("confirm") is not True
                    and _ask(args.action, exc.message)
                ):
                    params["confirm"] = True
                    data = await client.call(args.action, params, **route_kwargs)
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


# --------------------------------------------------------------------------
# review-mark (012v2 §八: a review pass drawn back onto the page)
# --------------------------------------------------------------------------


class FindingsError(Exception):
    """The findings input could not be read or is not a review report."""


def _load_findings(source: str) -> tuple[list[dict], str]:
    """Read a findings list from a path, ``-`` (stdin) or the JSON itself.

    Returns ``(findings, label)``. Three input forms because all three are
    natural at a shell: the report file `boardwise review --json` wrote, a pipe
    from it, and a literal pasted from a conversation. The literal is only tried
    when the argument is *not* an existing path, so a file that happens to be
    named like JSON still wins.
    """
    import json

    label = source
    text: str
    if source == "-":
        label = "<stdin>"
        text = sys.stdin.read()
    elif Path(source).is_file():
        label = str(source)
        try:
            text = Path(source).read_text(encoding="utf-8")
        except OSError as exc:
            raise FindingsError(f"{source}: {exc}") from exc
    elif source.lstrip()[:1] in ("{", "["):
        text = source
    else:
        raise FindingsError(
            f"{source}: not a file, not `-`, and not JSON. Pass the report "
            "`boardwise review --json <path>` wrote, or `-` to read stdin."
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FindingsError(f"{label} is not JSON ({exc})") from exc

    if isinstance(payload, list):
        findings = payload
    elif isinstance(payload, dict) and isinstance(payload.get("findings"), list):
        findings = payload["findings"]
    elif isinstance(payload, dict) and ("rule_id" in payload or "ruleId" in payload):
        findings = [payload]
    else:
        raise FindingsError(
            f"{label} carries no findings: expected the `boardwise review --json` "
            "payload ({'summary': …, 'findings': […]}) or a bare list of findings"
        )
    if not all(isinstance(entry, dict) for entry in findings):
        raise FindingsError(f"{label}: every finding must be a JSON object")
    return findings, label


def marks_from_findings(findings: list[dict]) -> tuple[list[dict], list[dict]]:
    """``(marks, skipped)`` for :func:`boardwise.engines.review.render_json` output.

    A mark is what `review.mark` needs and nothing more: the ref, the rule id,
    the severity and the one-line message. One mark per **ref**, because a
    finding may name several parts (a decoupling violation names the IC *and*
    the capacitor) and each of them is somewhere on the page — the same
    rule-verdict may therefore light up twice, which is the honest picture.

    The refs come from the report's own ``refs`` field when it has one (written
    by `render_json` since 012v2 §八) and are otherwise read out of the evidence
    with :func:`boardwise.engines.review.finding_refs` — so an older report file
    still marks. A finding that names no ref at all is returned in `skipped`
    rather than dropped: "this finding cannot be pointed at" is information, and
    a silent gap in the count is not.
    """
    from .engines.review import finding_refs
    from .rules.base import Finding

    marks: list[dict] = []
    skipped: list[dict] = []
    for position, entry in enumerate(findings, 1):
        rule_id = str(entry.get("rule_id") or entry.get("ruleId") or "").strip()
        severity = str(entry.get("severity") or "").strip().upper()
        message = str(entry.get("message") or "").strip()
        evidence = entry.get("evidence")
        evidence = [str(item) for item in evidence] if isinstance(evidence, list) else []
        declared = entry.get("refs")
        if declared is None and entry.get("ref") is not None:
            declared = entry.get("ref")
        if isinstance(declared, str):
            declared = [declared]
        refs: list[str] = []
        if isinstance(declared, list):
            refs = [str(ref).strip() for ref in declared if str(ref).strip()]
        if not refs:
            refs = finding_refs(
                Finding(
                    rule_id=rule_id,
                    severity=severity or "INFO",
                    message=message,
                    level=str(entry.get("level") or ""),
                    evidence=evidence,
                )
            )
        if not refs:
            skipped.append(
                {
                    "finding": position,
                    "ruleId": rule_id,
                    "severity": severity,
                    "text": message,
                    "reason": "该发现没有点名任何位号",
                }
            )
            continue
        for ref in refs:
            marks.append(
                {
                    "ref": ref,
                    "ruleId": rule_id,
                    "severity": severity,
                    "text": message,
                    "finding": position,
                }
            )
    return marks, skipped


def _cmd_review_mark(args: argparse.Namespace) -> int:
    """Draw a review pass on the live canvas, or clear it (§八).

    Exit codes: 0 everything the report asked for is on the canvas (or the
    markers were cleared); 1 partial — a ref that is not on the page, a finding
    with no ref, or a host that could not draw, all named line by line; 2 the
    input or the daemon was unusable. Partial is exit 1 rather than 0 on
    purpose: "some of your review is on the canvas" is not the same claim as
    "your review is on the canvas".
    """
    import asyncio
    import json

    BridgeClient, BridgeError, port, token = _open_cli(args)

    marks: list[dict] = []
    skipped: list[dict] = []
    label = "clear"
    if args.findings != "clear":
        try:
            findings, label = _load_findings(args.findings)
            marks, skipped = marks_from_findings(findings)
        except FindingsError as exc:
            print(f"boardwise review-mark: {exc}", file=sys.stderr)
            return 2
        if not marks:
            print(
                f"boardwise review-mark: {label} 里没有可标记的位号"
                f"（{len(skipped)} 条发现没有点名位号）—— 没有调用编辑器",
                file=sys.stderr,
            )
            return 1

    params: dict = {
        "clear": args.findings == "clear",
        "markers": not args.no_markers,
        "color": args.color,
        "zoom": bool(args.zoom),
    }
    if args.findings != "clear":
        # `finding` stays CLI-side: the action's contract is position order, and
        # an unknown key in the marks would only invite a second source of truth.
        params["marks"] = [
            {key: mark[key] for key in ("ref", "ruleId", "severity", "text")} for mark in marks
        ]
    if args.page:
        params["pageUuid"] = args.page
    if args.focus is not None:
        params["focus"] = int(args.focus)

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
            data = await client.call("review.mark", params)
        except BridgeError as exc:
            print(
                f"boardwise review-mark: {params['clear'] and 'clear' or 'mark'} failed "
                f"[{exc.code}] {exc.message}",
                file=sys.stderr,
            )
            return 1
        finally:
            await client.close()
        return _render_review_mark(label, marks, skipped, data, args)

    return asyncio.run(run())


def _render_review_mark(
    label: str, marks: list[dict], skipped: list[dict], data: object,
    args: argparse.Namespace,
) -> int:
    """Print the finding ↔ marker table the marker API cannot draw, and decide the exit."""
    import json

    payload = data if isinstance(data, dict) else {}

    if payload.get("cleared") is not None and not marks:
        ok = bool(payload.get("cleared"))
        print(f"boardwise review-mark clear: {'已清除画布上的指示标记' if ok else '画布拒绝清除'}")
        if not ok:
            print(f"  {payload.get('note', '')}")
        if args.json_path:
            Path(args.json_path).write_text(
                json.dumps({"mode": "clear", "response": payload}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return 0 if ok else 1

    marked = {entry.get("position"): entry for entry in payload.get("marked", [])}
    unresolved = {entry.get("position"): entry for entry in payload.get("unresolved", [])}
    mode = str(payload.get("mode") or "markers")
    print(
        f"boardwise review-mark: {label} —— {len(marks)} 个位号"
        f"（{len(payload.get('marked', []))} 已打标，{len(payload.get('unresolved', []))} 未打标，"
        f"{len(skipped)} 条发现没有位号）"
    )
    for position, mark in enumerate(marks, 1):
        head = (
            f"  [{position}] {mark['severity']:<5} {mark['ruleId']:<22} {mark['ref']:<8}"
        )
        hit = marked.get(position)
        if hit:
            print(
                f"{head} marker#{hit.get('marker')} @ ({hit.get('x')}, {hit.get('y')})"
                f"  {mark['text']}"
            )
        else:
            reason = (unresolved.get(position) or {}).get("reason", "未打标")
            print(f"{head} 未打标：{reason}  {mark['text']}")
    for entry in skipped:
        print(
            f"  [~] {entry['severity']:<5} {entry['ruleId']:<22} "
            f"发现 #{entry['finding']}：{entry['reason']}"
        )
    if mode == "list":
        print(f"  降级为跳转清单（未在画布上打标）：{(payload.get('markers') or {}).get('reason', '')}")
    else:
        print(
            f"  画布标记：{(payload.get('markers') or {}).get('accepted', 0)}/"
            f"{(payload.get('markers') or {}).get('attempted', 0)}"
            f"（marker#k = 上面第 k 个 marker 编号）"
        )
    focused = payload.get("focused")
    if isinstance(focused, dict):
        print(
            f"  跳转到第 {focused.get('position')} 条 {focused.get('ref')}："
            f"{'已缩放' if focused.get('zoomed') else '未缩放 — ' + str(focused.get('reason', ''))}"
        )
    for note in payload.get("notes", []):
        print(f"  注：{note}")

    ok = mode == "markers" and not unresolved and not skipped
    print(
        "boardwise review-mark: 全部到位；清除用 `boardwise review-mark clear`"
        if ok
        else "boardwise review-mark: 部分到位（见上）；清除用 `boardwise review-mark clear`"
    )
    if args.json_path:
        Path(args.json_path).write_text(
            json.dumps(
                {
                    "source": label,
                    "marks": marks,
                    "skipped": skipped,
                    "mode": mode,
                    "complete": ok,
                    "response": payload,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0 if ok else 1


# --------------------------------------------------------------------------
# edit (016: review -> local edit — the M3 first slice, `component-value`)
# --------------------------------------------------------------------------


#: The rules whose findings this build can repair, mapped to the change kind a
#: plan for them must name. A rule *absent* from this table is answered rather
#: than ignored: a plan asked for such findings is refused by name, because
#: silence would read as "there is nothing to fix here".
REPAIRABLE_RULES: dict[str, str] = {"param-value-mpn-match": COMPONENT_VALUE_KIND}

#: The reverse map, derived so the two directions cannot drift apart: `preview`
#: and `apply` read a plan (which names no rule) and re-run the rule the plan's
#: change kind belongs to.
RULE_FOR_KIND: dict[str, str] = {
    kind: rule_id for rule_id, kind in REPAIRABLE_RULES.items()
}

#: The one component attribute this slice may write — a range guard with a
#: name, asserted in the apply path instead of promised in a comment (016 §四,
#: protection 2: only the target, only locally).
EDIT_WRITE_KEY = "Value"

#: Bridge error codes that mean "the write may still have landed". The rule is
#: draw.py's (`_call_write`, engines/draw.py:296-330): a timeout and a dropped
#: connection both leave the page's state unknown, so both are read back and
#: neither is retried. Pinned against `bridge.protocol.ErrorCodes` by the 016
#: tests rather than imported here, so this module stays importable without the
#: bridge's websockets dependency.
UNKNOWN_OUTCOME_CODES = frozenset({"TIMEOUT", "DISCONNECTED"})

#: Relative tolerance for "these two board values say the same thing". The rules
#: already judge declarations at 1e-3 (`rules/params`: nominal equality), and a
#: repair that disagreed with them would call a value changed that the rules
#: call equal. It lives here rather than in `core/changeplan.py` because it
#: needs the value parsers, and the layer rule is that `core` imports nothing
#: from the package (`tests/test_layer_rules.py`).
_VALUE_REL_TOL = 1e-3


def _edit_step(
    action: str, purpose: str, ok: bool, error: object | None = None,
    *, wrote: bool = False,
) -> dict:
    """One bridge call as a report row (draw.py's ``StepRecord``, as a dict)."""
    code = str(getattr(error, "code", "") or "") if error is not None else ""
    message = ""
    if error is not None:
        message = str(getattr(error, "message", "") or "") or str(error)
    return {
        "action": action,
        "purpose": purpose,
        "ok": ok,
        "wrote": wrote,
        "code": code,
        "message": message,
        "unknown": (not ok) and code in UNKNOWN_OUTCOME_CODES,
    }


def same_board_value(left: str, right: str) -> tuple[bool, str]:
    """Are these two board values the same value? ``(equal, how)``.

    String equality first, because that is what the editor stores and what the
    read-back compares; then the parsed quantity, because ``4.7k`` and
    ``4.7kΩ`` are the same resistor and treating a formatting difference as
    "somebody changed the board by hand" would refuse a plan that is still true.

    ``how`` is ``"identical"``, ``"same resistance"``, ``"same capacitance"`` or
    ``""`` for "not the same" — reported, so a reader can tell an exact match
    from a numeric one.
    """
    left, right = (left or "").strip(), (right or "").strip()
    if left == right:
        return True, "identical"
    from .rules.connectivity import parse_resistance_ohms
    from .rules.values import parse_capacitance_farads

    for parser, label in (
        (parse_resistance_ohms, "same resistance"),
        (parse_capacitance_farads, "same capacitance"),
    ):
        first, second = parser(left), parser(right)
        if first is None or second is None:
            continue
        if first == 0.0 and second == 0.0:
            return True, label
        high, low = max(first, second), min(first, second)
        if low > 0 and (high - low) <= _VALUE_REL_TOL * high:
            return True, label
    return False, ""


def _boardwise_designator(model, designator: str) -> str | None:
    """The model's own spelling of a designator, or None when it is not there.

    Exact match first (that is the file's spelling), case-insensitive second
    (a human typing ``u3`` means ``U3``). The model's spelling is returned so
    every later comparison in one run uses a single string.
    """
    if designator in model.components:
        return designator
    wanted = designator.strip().upper()
    for name in model.components:
        if name.upper() == wanted:
            return name
    return None


def _findings_naming(rule, model, designator: str) -> list:
    """The rule's findings that name this designator.

    Read through :func:`finding_refs` — the same reading ``review-mark`` marks
    the canvas with — so "which findings will this edit silence" is answered by
    the report's own definition of "names a designator", not by a second one.
    """
    wanted = designator.upper()
    return [
        finding
        for finding in rule.check(model)
        if wanted in {ref.upper() for ref in finding_refs(finding)}
    ]


def _snapshot_identity(path: Path) -> tuple[str, str, str, list[str]]:
    """``(projectUuid, pageUuid, hostVersion, notes)``, read from the snapshot.

    Three measured facts decide what is possible here, and each one is *said*
    rather than papered over:

    * a ``.epro2`` carries **no project uuid** — ``project2.json`` holds a
      title, an editor version and a few flags and nothing else (read by
      ``parsers/epru_stream.read_project_meta``), so ``projectUuid`` is empty
      and the plan records that the only authority on that id is ``doc.list``
      at apply time;
    * the **page uuid** comes from the ``SCH_PAGE`` document head, and only when
      the snapshot names exactly one such page: a multi-page backup has no
      single page for the plan to name, and picking one would be exactly the
      cross-page ambiguity §2.3 refuses to guess at;
    * an ``.enet`` export carries neither, so both stay empty.
    """
    notes: list[str] = []
    if path.suffix.lower() != ".epro2":
        notes.append(
            f"a {path.suffix or 'extension-less'} input carries no project or "
            "page metadata here, so projectUuid and pageUuid are empty and the "
            "page guard degrades to the focused page"
        )
        return "", "", "", notes

    from .parsers.epru_stream import iter_epru_records, load_epru_text

    try:
        text, meta = load_epru_text(path)
        pages = sorted({
            str((record.body or {}).get("uuid") or "")
            for record in iter_epru_records(text)
            if record.type == "DOCHEAD"
            and (record.body or {}).get("docType") == "SCH_PAGE"
        } - {""})
        host_version = str(meta.get("editorVersion") or "")
    except Exception as exc:  # noqa: BLE001 — metadata is a nice-to-have, not the plan
        notes.append(
            f"the snapshot's own metadata could not be read ({exc}); "
            "projectUuid and pageUuid are left empty"
        )
        return "", "", "", notes

    notes.append(
        "projectUuid is empty: a .epro2's metadata carries no project uuid "
        "(measured), so `edit apply` reports what doc.list calls the focused "
        "project and the plan does not pretend to know it"
    )
    if len(pages) == 1:
        return "", pages[0], host_version, notes
    if pages:
        notes.append(
            f"the snapshot holds {len(pages)} schematic pages, so no single "
            "pageUuid could be named; pageUuid is empty and the page guard "
            "degrades to the focused page"
        )
    else:
        notes.append(
            "the snapshot holds no SCH_PAGE document, so pageUuid is empty and "
            "the page guard degrades to the focused page"
        )
    return "", "", host_version, notes


def _cmd_edit_plan(args: argparse.Namespace) -> int:
    """``edit plan``: one finding -> one ChangePlan, entirely offline.

    Exit codes: 0 plan built; 2 the snapshot cannot be read; 5 the plan cannot
    be built from what was asked — an unknown rule id, a rule this build cannot
    repair, no violation for that designator, an ambiguous designator, or a
    before/after pair the plan's own validation would refuse. The last group is
    5 and not 2 on purpose: nothing is wrong with the input file, the *ask* is
    what cannot be turned into a plan.
    """
    import json

    path = Path(args.file)
    if not path.is_file():
        print(f"boardwise edit plan: {path}: not a file", file=sys.stderr)
        return 2
    try:
        model, _board = _load_model(path, view=args.view)
    except EncryptedProjectError as exc:
        print(f"boardwise edit plan: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — the CLI must not traceback
        print(f"boardwise edit plan: {path}: {exc}", file=sys.stderr)
        return 2

    rule = next((item for item in BUILTIN_RULES if item.id == args.rule), None)
    if rule is None:
        known = ", ".join(sorted(item.id for item in BUILTIN_RULES))
        print(
            f"boardwise edit plan: no rule with id {args.rule!r}\n"
            f"  known rule ids: {known}",
            file=sys.stderr,
        )
        return 5
    if rule.id not in REPAIRABLE_RULES:
        print(
            f"boardwise edit plan: rule {rule.id!r} is not repairable in this "
            "build（该规则不支持自动修改）— this slice executes "
            f"{', '.join(sorted(set(REPAIRABLE_RULES.values())))} only, and it "
            "needs a finding that carries a structured target",
            file=sys.stderr,
        )
        return 5

    designator = _boardwise_designator(model, args.designator)
    if designator is None:
        print(
            f"boardwise edit plan: {path}: no component with designator "
            f"{args.designator!r} in the {args.view} view",
            file=sys.stderr,
        )
        return 5
    if any(
        name.upper() == designator.upper()
        for name in model.duplicate_designators
    ):
        print(
            f"boardwise edit plan: 位号 {designator} 在源文件里出现了多次"
            "（duplicate designator）—— 跨页歧义，plan 拒绝生成，不猜是哪一块"
            "（§2.3）",
            file=sys.stderr,
        )
        return 5

    findings = rule.check(model)
    finding = next(
        (
            item
            for item in findings
            if item.target is not None
            and item.target.component_ref.upper() == designator.upper()
        ),
        None,
    )
    if finding is None:
        lines = [
            f"boardwise edit plan: no VIOLATION for {designator} under "
            f"{rule.id} — there is nothing to plan"
        ]
        for item in _findings_naming(rule, model, designator):
            lines.append(f"  [{item.severity}] {item.message}")
        if hasattr(rule, "outcomes"):
            for outcome in rule.outcomes(model):
                if outcome.subject == designator or outcome.subject.startswith(
                    f"{designator} "
                ):
                    lines.append(
                        f"  {outcome.state}: {outcome.subject} — {outcome.message}"
                    )
        print("\n".join(lines), file=sys.stderr)
        return 5

    before = finding.target.expected_before
    after = (args.after if args.after is not None else finding.target.suggested_after)
    after = (after or "").strip()
    if not before:
        print(
            f"boardwise edit plan: the finding for {designator} carries no "
            "current value, so the plan could not re-check itself before "
            "writing — nothing to build",
            file=sys.stderr,
        )
        return 5
    if not after:
        print(
            f"boardwise edit plan: no value to write for {designator} — pass "
            "--after, or use a rule whose finding carries a suggestion",
            file=sys.stderr,
        )
        return 5
    if after == before:
        print(
            f"boardwise edit plan: the value to write equals the current value "
            f"({before!r}) — a plan that changes nothing is refused (the same "
            "rule the plan's own validation applies)",
            file=sys.stderr,
        )
        return 5

    project_uuid, page_uuid, host_version, notes = _snapshot_identity(path)
    source = PlanSource(
        input_sha256=sha256_of(path),
        project_uuid=project_uuid,
        page_uuid=page_uuid,
        host_version=host_version,
        connector_version=_repo_connector_version(),
    )
    plan = component_value_plan(
        source, designator=designator, before=before, after=after
    )

    print(
        f"boardwise edit plan: {path} "
        f"({len(model.components)} components, {len(model.nets)} nets; "
        f"view {args.view})"
    )
    print(f"finding: [{finding.severity}] {finding.rule_id}: {finding.message}")
    print(
        f"plan: {designator}.{EDIT_WRITE_KEY} {before!r} -> {after!r} "
        f"({plan.change.kind})"
    )
    print(
        f"snapshot: sha256 {source.input_sha256}  "
        f"pageUuid {source.page_uuid or '(none)'}  "
        f"projectUuid {source.project_uuid or '(none)'}  "
        f"host {source.host_version or '(unknown)'}  "
        f"connector {source.connector_version or '(unknown)'}"
    )
    for note in notes:
        print(f"note: {note}")

    if args.out_path:
        plan.dump(args.out_path)
        print(f"plan written to {args.out_path}")
    else:
        print(json.dumps(plan.to_jsonable(), ensure_ascii=False, indent=2))

    if args.json_path:
        Path(args.json_path).write_text(
            json.dumps(
                {
                    "command": "plan",
                    "ok": True,
                    "file": str(path),
                    "view": args.view,
                    "rule": rule.id,
                    "designator": designator,
                    "before": before,
                    "after": after,
                    "sha256": source.input_sha256,
                    "planPath": args.out_path,
                    "plan": plan.to_jsonable(),
                    "components": len(model.components),
                    "nets": len(model.nets),
                    "notes": notes,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0


def _cmd_edit_preview(args: argparse.Namespace) -> int:
    """``edit preview``: check the plan against the snapshot and show the diff.

    Offline, read-only, and it cannot be talked out of the check: ``--file`` is
    required because the plan carries the snapshot's *hash* and not its path, so
    without the file protection 1 would have nothing to compare. Exit 0 fresh;
    4 a stale snapshot (sha256 differs) or a target that is gone or no longer
    holds the value the plan expects; 2 the snapshot cannot be read; 5 the plan
    or the arguments are unusable.
    """
    import json

    try:
        plan = ChangePlan.load(args.plan)
    except ChangePlanError as exc:
        print(f"boardwise edit preview: {exc}", file=sys.stderr)
        return 5
    if not args.file:
        print(
            "boardwise edit preview: --file is required — the plan carries the "
            "snapshot's sha256, not its path, so without the file there is "
            "nothing to check the snapshot against",
            file=sys.stderr,
        )
        return 5
    path = Path(args.file)
    if not path.is_file():
        print(f"boardwise edit preview: {path}: not a file", file=sys.stderr)
        return 2

    digest = sha256_of(path)
    if digest != plan.source.input_sha256:
        print(
            f"boardwise edit preview: 快照已失效 — {path} hashes {digest} but the "
            f"plan was built against {plan.source.input_sha256}; nothing was "
            "checked and nothing will be written — re-run `edit plan`",
            file=sys.stderr,
        )
        return 4

    try:
        model, _board = _load_model(path, view=args.view)
    except EncryptedProjectError as exc:
        print(f"boardwise edit preview: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — the CLI must not traceback
        print(f"boardwise edit preview: {path}: {exc}", file=sys.stderr)
        return 2

    designator = _boardwise_designator(model, plan.target.designator)
    if designator is None:
        print(
            f"boardwise edit preview: {path} no longer holds designator "
            f"{plan.target.designator} — 目标已不在快照里，前置条件失败",
            file=sys.stderr,
        )
        return 4
    component = model.components[designator]
    equal, how = same_board_value(component.value, plan.change.before)
    if not equal:
        print(
            f"boardwise edit preview: {designator}.{EDIT_WRITE_KEY} reads "
            f"{component.value!r} in the snapshot, but the plan expects "
            f"{plan.change.before!r} — 前置条件失败，快照里的值已经变了",
            file=sys.stderr,
        )
        return 4

    rule_id = RULE_FOR_KIND.get(plan.change.kind, "")
    rule = next((item for item in BUILTIN_RULES if item.id == rule_id), None)
    silenced = _findings_naming(rule, model, designator) if rule is not None else []

    print(f"boardwise edit preview: {args.plan}")
    print(
        f"plan: {plan.change.kind} {designator}.{EDIT_WRITE_KEY} "
        f"{plan.change.before!r} -> {plan.change.after!r}"
    )
    print(f"snapshot: {path} sha256 matches the plan's ({digest})")
    print(f"target: {designator} is still there, value still {component.value!r} ({how})")
    print(
        f"semantic diff: {designator}.{EDIT_WRITE_KEY}: "
        f"{component.value} → {plan.change.after}"
    )
    if rule is None:
        print(f"resolves: (the plan's kind {plan.change.kind!r} maps to no rule in this build)")
    else:
        print(f"resolves ({len(silenced)} finding(s) from {rule.id}):")
        for item in silenced:
            print(f"  [{item.severity}] {item.message}")
    print(
        "geometric diff: no geometric diff by construction — the change rewrites "
        "one key inside the component's otherProperty; no primitive is created, "
        "moved or deleted, so no coordinate can move"
    )

    if args.json_path:
        Path(args.json_path).write_text(
            json.dumps(
                {
                    "command": "preview",
                    "ok": True,
                    "file": str(path),
                    "view": args.view,
                    "planPath": args.plan,
                    "plan": plan.to_jsonable(),
                    "sha256": digest,
                    "snapshot": "fresh",
                    "designator": designator,
                    "observedValue": component.value,
                    "valueComparison": how,
                    "diff": {
                        "designator": designator,
                        "key": EDIT_WRITE_KEY,
                        "from": component.value,
                        "to": plan.change.after,
                    },
                    "resolves": [
                        {
                            "rule_id": item.rule_id,
                            "severity": item.severity,
                            "message": item.message,
                        }
                        for item in silenced
                    ],
                    "geometricDiff": (
                        "none by construction: one key inside the component's "
                        "otherProperty changes; no primitive is created, moved "
                        "or deleted"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0


def _active_document_uuid(listing: dict) -> str:
    """The focused document's uuid from a ``doc.list`` payload, ``""`` if none.

    ``active`` is ``null`` when nothing is focused, and the host's placeholder
    uuid ``"0"`` is normalised to null by the connector
    (``docs/bridge.md``) — the second half is checked here as well, because a
    placeholder taken for a page name would refuse a perfectly good plan.
    """
    active = listing.get("active")
    uuid = str(active.get("uuid") or "") if isinstance(active, dict) else str(active or "")
    return "" if uuid == "0" else uuid


def _focused_project_uuid(listing: dict) -> str:
    """The focused project's uuid from a ``doc.list`` payload, ``""`` if none."""
    for project in listing.get("projects") or []:
        if isinstance(project, dict) and project.get("focused"):
            return str(project.get("projectUuid") or "")
    return ""


def _identity_project_text(project: object) -> str:
    """One project of a ``sys.identity`` payload as ``name (uuid)``.

    Both halves are printed because either one alone can mislead: two projects
    can carry the same name, and a uuid names nothing to the operator.
    """
    if not isinstance(project, dict):
        return "(no project reported)"
    name = project.get("friendlyName") or project.get("name") or "(unnamed)"
    return f"{name} ({project.get('projectUuid') or '(no uuid)'})"


def _identity_document_text(document: object) -> str:
    """``sys.identity``'s active document as ``uuid (kind)``, or its absence."""
    if not isinstance(document, dict) or not document.get("uuid"):
        return "(no active document)"
    return f"{document['uuid']} ({document.get('type') or 'document'})"


def _identity_document_project_text(document: object) -> str:
    """The project the active document belongs to, named as far as it said.

    ``activeDocument.project`` is the read the connector preferred; when the
    host filled in only ``parentProjectUuid`` there is a uuid and no name, and
    that is printed as exactly that rather than as "no project".
    """
    if not isinstance(document, dict):
        return "(no active document)"
    if isinstance(document.get("project"), dict):
        return _identity_project_text(document["project"])
    uuid = str(document.get("projectUuid") or "")
    if uuid:
        return f"(unnamed) ({uuid})"
    return "(the document named no project)"


def _edit_post_review(
    path: str | None, started: float, rule_id: str, designator: str, view: str
) -> dict:
    """Step 7: re-read the snapshot from disk and re-run the rule (016 §3).

    Three answers, and only the one the evidence supports: ``resolved`` (the
    target's finding is gone), ``still_present`` (it is still there, with the
    new findings attached) or ``unknown`` — which is what an unchanged file
    gets, because "the save has not landed yet" and "the change was never saved"
    are different facts and neither can be claimed from an unchanged mtime.
    """
    result: dict = {
        "state": "unknown",
        "reason": "",
        "file": path or "",
        "startedAt": started,
        "findings": [],
        "outcomes": [],
    }
    if not path:
        result["reason"] = (
            "no --file was given, so the disk copy was not re-read; the "
            "re-review is not claimed"
        )
        return result
    snapshot = Path(path)
    try:
        stat = snapshot.stat()
    except OSError as exc:
        result["reason"] = f"{snapshot} could not be stat()ed ({exc})"
        return result
    result["mtime"] = stat.st_mtime
    # A file the editor's save never rewrote cannot be evidence about the
    # change: reading it would compare the old content against the new value
    # and call the edit un-resolved, which is a statement the file does not
    # support. This is the honest "unknown".
    if stat.st_mtime < started:
        result["reason"] = (
            f"{snapshot} was last written at {stat.st_mtime} which is before "
            f"this run started at {started} — 保存未落盘或落盘延迟, so the "
            "re-review is not claimed"
        )
        return result
    try:
        model, _board = _load_model(snapshot, view=view)
    except Exception as exc:  # noqa: BLE001 — the CLI must not traceback
        result["reason"] = f"{snapshot} could not be re-parsed ({exc})"
        return result
    rule = next((item for item in BUILTIN_RULES if item.id == rule_id), None)
    if rule is None:
        result["reason"] = f"the plan's kind maps to rule {rule_id!r}, which this build does not have"
        return result
    target = _boardwise_designator(model, designator)
    if target is None:
        result["state"] = "resolved"
        result["reason"] = (
            f"{designator} is not in the re-read snapshot at all — the component "
            "the finding was about is gone"
        )
        return result
    findings = _findings_naming(rule, model, target)
    result["findings"] = [
        {"rule_id": item.rule_id, "severity": item.severity, "message": item.message}
        for item in findings
    ]
    if hasattr(rule, "outcomes"):
        result["outcomes"] = [
            {"state": outcome.state, "subject": outcome.subject, "message": outcome.message}
            for outcome in rule.outcomes(model)
            if outcome.subject == target or outcome.subject.startswith(f"{target} ")
        ]
    result["value"] = model.components[target].value
    if findings:
        result["state"] = "still_present"
        result["reason"] = (
            f"{rule_id} still reports {len(findings)} finding(s) about {target} "
            f"after the save"
        )
    else:
        result["state"] = "resolved"
        result["reason"] = f"{rule_id} reports nothing about {target} after the save"
    return result


def _render_edit_apply(report: dict, args: argparse.Namespace) -> int:
    """Print the human summary, write ``--json``, and return the exit code."""
    import json

    code = int(report.get("exitCode") or 0)
    reason = report.get("reason") or ""
    print(
        f"boardwise edit apply: {report.get('designator')}.{EDIT_WRITE_KEY} "
        f"{report.get('before')!r} -> {report.get('after')!r}  "
        f"[{report.get('outcome')}{': ' + reason if reason else ''}]"
    )
    for step in report.get("steps") or []:
        mark = "ok" if step["ok"] else ("UNKNOWN" if step["unknown"] else "FAILED")
        line = f"  {mark:<7} {step['action']:<26} {step['purpose']}"
        if not step["ok"]:
            line += f" — [{step['code']}] {step['message']}"
        print(line)
    resolved = report.get("resolved") or {}
    if resolved:
        print(
            f"  target  {resolved.get('designator')} -> primitiveId "
            f"{resolved.get('primitiveId') or '(none)'}  "
            f"{EDIT_WRITE_KEY} {resolved.get('value')!r} "
            f"(read from {resolved.get('valueKey') or 'no Value key'})"
        )
    verification = report.get("verification") or {}
    if verification:
        print(
            f"  readback sch.geometry says {verification.get('observed')!r} "
            f"(wanted {verification.get('expected')!r}) — "
            f"{'matched' if verification.get('matched') else 'DID NOT MATCH'}"
            f"{' (' + verification['how'] + ')' if verification.get('how') else ''}"
        )
    if report.get("persistence"):
        print(f"  persistence: {report['persistence']}")
    post = report.get("postReview") or {}
    if post:
        print(f"  re-review: {post.get('state')} — {post.get('reason')}")
        for item in post.get("findings") or []:
            print(f"    [{item['severity']}] {item['rule_id']}: {item['message']}")
    for note in report.get("notes") or []:
        print(f"  note: {note}")
    if report.get("final"):
        print(f"boardwise edit apply: {report['final']}")

    if args.json_path:
        Path(args.json_path).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return code


async def _edit_apply_flow(
    client, bridge_error, plan, args: argparse.Namespace, started: float
) -> int:
    """The apply sequence of 016 §3, step by step, with every answer recorded.

    The order is the protection: nothing is written before the plan's
    preconditions have been re-read from the live page, and nothing is believed
    after the write until the page has been read back independently.
    """
    records: list[dict] = []
    notes: list[str] = []
    designator = plan.target.designator
    before, after = plan.change.before, plan.change.after
    page = plan.source.page_uuid
    report: dict = {
        "command": "apply",
        "ok": False,
        "outcome": "",
        "reason": "",
        "exitCode": 0,
        "planPath": str(args.plan),
        "plan": plan.to_jsonable(),
        "designator": designator,
        "before": before,
        "after": after,
        "page": {"uuid": page, "guard": "enforced" if page else "unavailable"},
        "identity": {},
        "projectUuid": "",
        "resolved": {},
        "write": {"action": "sch.set_component_attribute", "calls": 0, "key": EDIT_WRITE_KEY},
        "verification": {},
        "save": {},
        "persistence": "",
        "postReview": {},
        "steps": records,
        "notes": notes,
        "final": "",
    }

    def done(code: int, outcome: str, reason: str = "") -> int:
        report["exitCode"] = code
        report["outcome"] = outcome
        report["ok"] = code == 0
        if reason:
            report["reason"] = reason
        return _render_edit_apply(report, args)

    async def call(action, params, purpose, *, writes=False):
        try:
            data = await client.call(action, params)
        except bridge_error as exc:
            records.append(_edit_step(action, purpose, False, exc, wrote=writes))
            return None
        records.append(_edit_step(action, purpose, True, wrote=writes))
        return data

    # ---- 1. preconditions, re-read from the live page (protection 1) -----
    if page:
        listing = await call(
            "doc.list", {}, "confirm the focused page is the plan's page"
        )
        if isinstance(listing, dict):
            report["projectUuid"] = _focused_project_uuid(listing)
            focused = _active_document_uuid(listing)
            if focused and focused != page:
                notes.append(
                    f"the editor has {focused} focused and the plan targets "
                    f"{page}; nothing was read as the target and nothing was written"
                )
                return done(4, "refused", "page_mismatch")
            if not focused:
                notes.append(
                    "doc.list reports no focused document, so the page could not "
                    "be confirmed before the read; the write still carries "
                    "pageUuid, which the host enforces (`guardPage`, actions.ts)"
                )
        else:
            notes.append(
                "doc.list did not answer, so the focused page was not confirmed "
                "before the read; the write still carries pageUuid, which the "
                "host enforces (`guardPage`, actions.ts)"
            )
    else:
        notes.append(
            "pageUuid guard unavailable, focused page used — this plan carries "
            "no pageUuid, so `guardPage` returns early (measured, actions.ts) "
            "and nothing but the operator's attention says the focused page is "
            "the right one"
        )

    # ---- 1b. the editor's two layers of focus must agree (018 §B2) -------
    # `doc.list`'s focus and the active document are two different reads, and
    # they were measured disagreeing on the machine (2026-09-21): the write
    # lands on whatever document is in front, while the operator reads the
    # focused project. The plan's first precondition is "the page the editor has
    # focused is the plan's page", and a disagreement is exactly that
    # precondition being false — so it is checked before the plan is compared
    # against the page at all.
    identity = await call(
        "sys.identity", {}, "confirm the editor's two layers of focus agree"
    )
    if not isinstance(identity, dict):
        # No answer: an older connector, which does not know the action
        # (UNKNOWN_ACTION), or a call that failed. That is a check which could
        # not run, not a disagreement — the geometry guard below still stands,
        # and refusing here would break every 0.4.10 connector.
        last = records[-1]
        report["identity"] = {"consistent": None, "consistentBasis": "unavailable"}
        notes.append(
            f"sys.identity could not be asked ([{last['code']}] {last['message']}) "
            "— 身份核查不可用（老 connector 没有这个动作，或调用失败），"
            "降级到 geometry 守卫，本次不因其拒绝写入"
        )
    else:
        consistent = identity.get("consistent")
        basis = str(identity.get("consistentBasis") or "") or "unavailable"
        report["identity"] = {
            "consistent": consistent if isinstance(consistent, bool) else None,
            "consistentBasis": basis,
            "focusedProject": identity.get("focusedProject"),
            "activeDocument": identity.get("activeDocument"),
        }
        if consistent is False:
            document = identity.get("activeDocument")
            notes.append(
                "焦点不一致，请先切换工程再执行：doc.list 报的焦点工程是 "
                f"{_identity_project_text(identity.get('focusedProject'))}，"
                f"编辑区活动文档 {_identity_document_text(document)} 属于 "
                f"{_identity_document_project_text(document)}（判定依据 {basis}）"
                " —— ChangePlan 的第一条 precondition 是 \"the page the editor "
                "has focused is the plan's page\"，此时写入的落点与操作者预期"
                "不同，所以没有发出任何写动作"
            )
            return done(4, "refused", "focus_inconsistent")
        if consistent is not True:
            notes.append(
                "sys.identity could not decide whether the editor's two layers of "
                f"focus agree (consistent={consistent!r}, 判定依据 {basis}) — "
                "身份核查无法判定，降级到 geometry 守卫，本次不因其拒绝写入"
            )

    geometry = await call("sch.geometry", {}, "read the page before writing")
    if geometry is None:
        last = records[-1]
        if last["unknown"]:
            notes.append(
                "the page could not be read (a timeout or a dropped connection); "
                "nothing was written and nothing was retried"
            )
            return done(3, "unknown", "precondition_unreadable")
        notes.append(
            f"the page could not be read ([{last['code']}] {last['message']}); "
            "nothing was written"
        )
        return done(4, "refused", "precondition_unreadable")

    lookup = resolve_on_page(geometry, designator)
    if lookup.component is None:
        notes.append(
            f"{designator} is not on the focused page — the plan's precondition "
            "(`designator still resolves`) is broken, so nothing was written"
        )
        return done(4, "refused", "target_missing")
    if lookup.ambiguous:
        notes.append(
            f"{lookup.matching} primitives on the page carry the designator "
            f"{designator}; which of them the plan means cannot be decided, so "
            "nothing was written"
        )
        return done(4, "refused", "target_ambiguous")
    resolved = lookup.component
    report["resolved"] = {
        "designator": resolved.designator,
        "primitiveId": resolved.primitive_id,
        "value": resolved.value,
        "valueKey": resolved.value_key,
    }
    if not resolved.primitive_id:
        notes.append(
            f"the page reports no primitiveId for {designator}, so the write has "
            "no target; nothing was written"
        )
        return done(4, "refused", "target_without_id")
    if not resolved.value_key:
        # "the page states no Value" and "the page states a different Value" are
        # different facts, and only the first one means there is nothing to
        # compare the plan against.
        notes.append(
            f"the page states no {EDIT_WRITE_KEY} for {designator} (its primitive "
            "carries no Value key), so the plan's precondition cannot be checked "
            "against it; nothing was written"
        )
        return done(4, "refused", "target_without_value")

    # Step 4 first, so a repeated run is recognised before any staleness talk:
    # the value is already what the plan asks for -> nothing to write.
    already, how_already = same_board_value(resolved.value, after)
    if already:
        notes.append(
            f"{designator}.{EDIT_WRITE_KEY} already reads {resolved.value!r} "
            f"({how_already} with the plan's {after!r}) — nothing was written "
            "(idempotent: no repeat of an applied change)"
        )
        report["final"] = "already applied; the page was not touched"
        return done(0, "already_applied", "already_applied")

    holds, how_holds = same_board_value(resolved.value, before)
    if not holds:
        notes.append(
            f"the page says {designator}.{EDIT_WRITE_KEY} is {resolved.value!r} "
            f"but the plan expects {before!r} — 旧快照失效（值已被改动）, so "
            "nothing was written"
        )
        return done(4, "refused", "stale_before")

    # ---- 2. the one write (protection 2: one call, one key) --------------
    params = {
        "primitiveId": resolved.primitive_id,
        "key": EDIT_WRITE_KEY,
        "value": after,
    }
    if page:
        params["pageUuid"] = page
    write = await call(
        "sch.set_component_attribute", params,
        f"write {EDIT_WRITE_KEY}={after!r} on {designator}", writes=True,
    )
    report["write"]["calls"] = 1
    report["write"]["params"] = {
        "primitiveId": resolved.primitive_id,
        "key": EDIT_WRITE_KEY,
        "value": after,
        "pageUuid": page or "(omitted: the plan carries none)",
    }
    if write is None:
        last = records[-1]
        # Step 5: unknown means read the page back, never retry.
        readback = await call(
            "sch.geometry", {},
            "read the page back after the write's outcome went unknown",
        )
        observed, seen = "", "the page could not be read back"
        if isinstance(readback, dict):
            found = resolve_on_page(readback, designator)
            observed = found.component.value if found.component is not None else ""
            seen = (
                f"the page reports {designator}.{EDIT_WRITE_KEY} as {observed!r}"
                if found.component is not None
                else f"{designator} is not on the page now"
            )
        report["verification"] = {
            "action": "sch.geometry",
            "afterUnknownWrite": True,
            "observed": observed,
            "expected": after,
            "matched": same_board_value(observed, after)[0],
        }
        if last["unknown"]:
            notes.append(
                f"the write's outcome is UNKNOWN ([{last['code']}] "
                f"{last['message']}); {seen}. Nothing was retried — a timeout is "
                "not a cancellation and a dropped connection is not a failed "
                "write, so re-issuing it could double whatever did land"
            )
            return done(3, "unknown", "write_unknown")
        notes.append(
            f"the write was refused ([{last['code']}] {last['message']}); {seen}"
        )
        return done(2, "failed", "write_refused")

    data = write if isinstance(write, dict) else {}
    other_after = data.get("otherPropertyAfter")
    clobbered = data.get("clobberedOtherKeys") or []
    report["write"].update({
        "wrote": bool(data.get("wrote")),
        "applied": bool(data.get("applied")),
        "mergedKeys": data.get("mergedKeys") or [],
        "otherPropertyAfter": other_after if isinstance(other_after, dict) else None,
        "mismatched": data.get("mismatched") or [],
        "clobberedOtherKeys": clobbered,
        "readBackAfter": data.get("readBackAfter", ""),
        "readBackBefore": data.get("readBackBefore", ""),
        "writeError": data.get("writeError", ""),
    })
    if clobbered:
        notes.append(
            f"the action reports it clobbered other keys: {clobbered} — that is "
            "exactly what protection 2 exists to catch, and the merge into the "
            "existing otherProperty should have prevented it"
        )
    if not data.get("applied"):
        notes.append(
            "the action's own read-back does not confirm the write "
            f"(wrote={bool(data.get('wrote'))}, "
            f"mismatched={data.get('mismatched') or '[]'}, "
            f"readBackAfter={data.get('readBackAfter') or '(none)'}) — the "
            "independent read-back below is what decides"
        )

    # ---- 3. independent read-back (protection 3) ------------------------
    verify = await call(
        "sch.geometry", {}, "read the page back independently after the write"
    )
    if verify is None:
        last = records[-1]
        notes.append(
            f"the independent read-back failed ([{last['code']}] "
            f"{last['message']}) — the change may be on the page, but the page's "
            "state cannot be stated"
        )
        return done(3, "unknown", "readback_unavailable")
    found = resolve_on_page(verify, designator)
    observed = found.component.value if found.component is not None else ""
    matched, how = same_board_value(observed, after)
    report["verification"] = {
        "action": "sch.geometry",
        "designator": found.component.designator if found.component else designator,
        "primitiveId": found.component.primitive_id if found.component else "",
        "observed": observed,
        "expected": after,
        "valueKey": found.component.value_key if found.component else "",
        "matched": matched,
        "how": how,
    }
    if not matched:
        notes.append(
            f"the independent read-back says {designator}.{EDIT_WRITE_KEY} is "
            f"{observed!r}, not {after!r} — the change did not land as promised"
        )
        return done(2, "failed", "readback_mismatch")

    # ---- 6. save (protection: check the answer, do not discard it) -------
    saved = await call("sch.doc.save", {}, "persist the change", writes=True)
    if saved is None:
        last = records[-1]
        report["save"] = {"ok": False, "code": last["code"], "message": last["message"]}
        if last["unknown"]:
            report["persistence"] = "unknown"
            notes.append(
                "the save's outcome is unknown — the change is verified on the "
                "canvas, but whether it reached the file cannot be stated, and "
                "nothing was retried"
            )
            return done(3, "unknown", "save_unknown")
        report["persistence"] = "placed"
        notes.append(
            f"the editor refused the save ([{last['code']}] {last['message']}) — "
            "the change is on the canvas only; it is NOT persisted"
        )
        return done(2, "failed", "save_refused")
    report["save"] = {"ok": True, "answered": saved}
    report["persistence"] = "saved_unverified"
    notes.append(
        "persistence is capped at saved_unverified: this bridge has no "
        "close/reopen action (009d), so only a separate reopen can promote it "
        "to saved_verified"
    )

    # ---- 7. re-review against the snapshot on disk ----------------------
    report["postReview"] = _edit_post_review(
        args.file, started, RULE_FOR_KIND.get(plan.change.kind, ""), designator,
        args.view,
    )
    post_state = report["postReview"].get("state")
    if post_state == "still_present":
        report["final"] = (
            f"applied and verified, but the re-review still reports the finding "
            f"({designator})"
        )
        return done(2, "failed", "still_present")
    if post_state == "unknown":
        report["final"] = (
            "applied and verified; the re-review could not be taken (see above)"
        )
        return done(0, "applied", "post_review_unknown")
    report["final"] = f"applied, verified, saved and re-reviewed as {post_state}"
    return done(0, "applied")


def _cmd_edit_apply(args: argparse.Namespace) -> int:
    """``edit apply``: execute one plan against a running editor (016 §3).

    Exit codes: 0 the change is on the page and, when the re-review could be
    taken, resolves the finding (or was already there); 2 the promised effect is
    not there — the write was refused, the read-back disagreed, the editor
    refused the save, or the re-review still reports the finding; 3 the page's
    state cannot be stated (the daemon is unreachable, or a timeout / a dropped
    connection with a read-back and no retry); 4 a precondition of the plan is
    broken; 5 the plan or the input is unusable.
    """
    import asyncio
    import time

    try:
        plan = ChangePlan.load(args.plan)
    except ChangePlanError as exc:
        print(f"boardwise edit apply: {exc}", file=sys.stderr)
        return 5

    # Stamped before the first bridge call: step 7 compares the snapshot's
    # mtime against this, and a save that landed during the run must count.
    started = time.time()
    BridgeClient, BridgeError, port, token = _open_cli(args)

    async def run() -> int:
        try:
            client = await BridgeClient.open(
                _bridge_uri(port), token, "cli", client="boardwise-cli"
            )
        except (OSError, BridgeError) as exc:
            # 3, not 2: with no connection there is nothing the daemon could
            # have read back, so the page's state is *unstatable* — the same
            # claim the flow below makes when a read-back times out. 2 is
            # reserved for "the effect is not there", which is knowledge we do
            # not have here (task 018 §C.1, found on the 016 scenario 5 run).
            print(
                f"boardwise bridge: daemon not reachable on 127.0.0.1:{port} ({exc})",
                file=sys.stderr,
            )
            return 3
        try:
            return await _edit_apply_flow(client, BridgeError, plan, args, started)
        finally:
            await client.close()

    return asyncio.run(run())


EDIT_COMMANDS = {
    "plan": _cmd_edit_plan,
    "preview": _cmd_edit_preview,
    "apply": _cmd_edit_apply,
}


# --------------------------------------------------------------------------
# doctor (012v2 §九: is this installation able to do anything at all?)
# --------------------------------------------------------------------------


#: The five methods `doctor` spot-checks — one per capability the harness needs,
#: so a gap is named rather than discovered later by a failing action:
#: the page-identity read every write guard uses, the PCB's identity read (the
#: pcb guards), the component list every read and every ref resolution uses,
#: focus (`doc.open` / `export.fab`), and the marker API (`review.mark`).
#:
#: Five, and deliberately not more: `sys.probe` can verify any declared member
#: (`boardwise bridge call --action sys.probe`), and doctor is a health check,
#: not the probe report. Every name here must exist in the generated table
#: (`connector/src/api-names.ts`) — a test asserts that, so a typo cannot turn
#: into a permanent red line nobody can fix.
DOCTOR_PROBE_CHECKS: dict[str, tuple[str, ...]] = {
    "dmt_Schematic": ("getCurrentSchematicPageInfo",),
    "dmt_Pcb": ("getCurrentPcbInfo",),
    "sch_PrimitiveComponent": ("getAll",),
    "dmt_EditorControl": ("openDocument", "generateIndicatorMarkers"),
}

#: The oldest editor release this harness has evidence for. Not a promise that
#: everything from here up works — see the three boundaries below.
#:
#: It was 3.2.183, on the reading that `generateIndicatorMarkers`/`zoomToRegion`
#: and friends did not exist below that. **Disproved on 3.2.149.88089769**
#: (2026-09-23, measured on the machine): the eight members probed there all
#: answer `typeof === function` *with* their arity, `activate()` is dispatched
#: normally on a cold start (the "3.2.149 never dispatches it" reading of 024 did
#: not reproduce), and `sch_ManufactureData.getExportDocumentFile` really runs —
#: a 308 KB PNG came back. Hence 3.2.149.
#:
#: What it does *not* claim:
#:
#: 1. **Not "3.2.149 and up are all fine."** The measured points are exactly two
#:    hosts — 3.2.149.88089769 and 3.2.186 — and below 3.2.149 there is no
#:    evidence at all, which is why doctor keeps refusing those.
#: 2. **Behaviour is a separate question, measured separately**: `review.mark`
#:    really drawing, the checkup chain end to end, DRC on a real project. A host
#:    found crippled there gets a *behavioural* check in doctor rather than a
#:    version number — measure it, do not infer it from the release.
#: 3. **`typeof` proves a member exists, never that it works.** That is this
#:    repo's own lesson, not a caveat: `getPngFile` is declared from 3.2.183 and
#:    answers nothing at runtime on *both* measured hosts. Absence is evidence;
#:    presence is only a hint.
EDITOR_API_FLOOR = (3, 2, 149)

#: The one sentence every connector-dependent check repeats when nothing is
#: attached. Written once so the seven lines cannot drift into seven different
#: guesses about the same missing socket.
CONNECTOR_FIX = (
    "先让扩展连上：打开立创 EDA Pro，确认 boardwise 扩展已启用并在面板里可见"
    "（首页/原理图/PCB 菜单里有 boardwise，`About…` 应显示 connected），"
    "再重跑 `boardwise doctor`（若刚重启过编辑器，daemon 侧用 `boardwise bridge status` 复核）"
)

#: Only the first three fields of an editor version mean anything to the floor.
#: The fourth is a build suffix — `3.2.186.b52e3e87` on the machine this was
#: measured on, `3.2.149.88089769` in the issue — so comparing it would make two
#: readings of the same release disagree.
EDITOR_VERSION_DEPTH = 3

#: The manifest every Electron app carries at the top of its install tree. The
#: editor is no exception, and reading it needs no bridge, no daemon and no
#: running editor — which is the whole point of the offline pre-check (issue #3).
EDITOR_MANIFEST = Path("resources") / "app" / "package.json"

#: Directory names the desktop editor installs into, by the vendor's naming
#: habit (立创 EDA Pro / LCEDA Pro / EasyEDA Pro). Tried before the globs below,
#: so the ordinary machine costs a handful of `is_dir` calls.
EDITOR_INSTALL_DIR_NAMES = (
    "lceda-pro",
    "lceda",
    "LCEDA-Pro",
    "easyeda-pro",
    "EasyEDA Pro",
    "嘉立创EDA专业版",
    "嘉立创EDA",
)

#: One-level globs for the rest of that habit. One level only, and matched
#: case-insensitively on Windows: a recursive walk to find an editor would make
#: `doctor` — the command people run *because* something is broken — the slowest
#: thing in the tool.
EDITOR_INSTALL_GLOBS = ("*lceda*", "*easyeda*", "*嘉立创*")

#: Pins the offline search, `os.pathsep`-separated roots. Set, it *replaces* the
#: built-in locations: for an install somewhere unusual, and for tests, which
#: must not read whichever editor the developer happens to have installed.
EDITOR_INSTALL_ENV = "BOARDWISE_EDITOR_INSTALL"

#: `GetDriveTypeW`'s "fixed disk". Mapped shares and removable media are skipped
#: on purpose: globbing one of those is a hang, not a search.
_DRIVE_FIXED = 3


@dataclass
class EditorInstall:
    """An editor install tree found on disk, read without any bridge."""

    path: Path
    #: The version its manifest declares, `''` when the tree was there but the
    #: manifest could not be read (or said nothing usable).
    version: str = ""


@dataclass
class EditorInstallScan:
    """What the offline scan found, and the roots it looked under."""

    install: EditorInstall | None = None
    roots: tuple[Path, ...] = ()


def _fixed_drive_roots() -> list[Path]:
    """``D:\\``-style roots of this machine's fixed disks (Windows only)."""
    if os.name != "nt":
        return []
    try:
        import ctypes
        import string

        mask = ctypes.windll.kernel32.GetLogicalDrives()
        roots = []
        for index, letter in enumerate(string.ascii_uppercase):
            root = Path(f"{letter}:\\")
            if mask >> index & 1 and ctypes.windll.kernel32.GetDriveTypeW(str(root)) == _DRIVE_FIXED:
                roots.append(root)
        return roots
    except (ImportError, AttributeError, OSError):
        # ctypes ships with Python on Windows; should this ever fail, one try at
        # C: beats losing the scan entirely.
        fallback = Path("C:\\")
        return [fallback] if fallback.is_dir() else []


def _editor_search_roots() -> list[Path]:
    """Roots to look one level under, most likely first.

    The pinned list first (:data:`EDITOR_INSTALL_ENV`), then every fixed drive
    root — the machine this was measured on keeps the editor at ``D:\\lceda-pro``,
    which is only the naming habit one level under a drive — then the Windows
    install locations, where the installer puts it when the user takes the
    default.
    """
    pinned = [
        Path(part.strip())
        for part in os.environ.get(EDITOR_INSTALL_ENV, "").split(os.pathsep)
        if part.strip()
    ]
    if pinned:
        return pinned
    roots = _fixed_drive_roots()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots += [Path(local) / "Programs", Path(local)]
    for key in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        value = os.environ.get(key)
        if value:
            roots.append(Path(value))
    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def _editor_install_candidates(roots: Iterable[Path]) -> Iterator[Path]:
    """Directories worth reading a manifest from: named ones, then globbed ones."""
    seen: set[Path] = set()

    def fresh(candidate: Path) -> bool:
        if candidate in seen or not candidate.is_dir():
            return False
        seen.add(candidate)
        return True

    for root in roots:
        for name in EDITOR_INSTALL_DIR_NAMES:
            candidate = root / name
            if fresh(candidate):
                yield candidate
    for root in roots:
        for pattern in EDITOR_INSTALL_GLOBS:
            try:
                matches = sorted(root.glob(pattern))
            except OSError:
                continue
            for match in matches:
                if fresh(match):
                    yield match


def scan_editor_install(roots: Iterable[Path] | None = None) -> EditorInstallScan:
    """Find an editor install tree and read its version — offline.

    No daemon, no connected extension, no `sys.probe`: just the manifest the
    editor ships. That is what makes the answer available *before* the whole
    bridge path (daemon → extension → restart → pairing) that the version gate
    otherwise waits on, while upgrading the editor is the thing to do first
    (issue #3).

    ``install`` is ``None`` when no install tree was found at all, and carries an
    empty ``version`` when one was found but its manifest could not be read —
    doctor tells those two apart instead of guessing a verdict.
    """
    import json

    looked = tuple(roots) if roots is not None else tuple(_editor_search_roots())
    first_tree: Path | None = None
    for candidate in _editor_install_candidates(looked):
        if first_tree is None:
            first_tree = candidate
        try:
            payload = json.loads((candidate / EDITOR_MANIFEST).read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        version = payload.get("version") if isinstance(payload, dict) else None
        if str(version or "").strip():
            return EditorInstallScan(EditorInstall(candidate, str(version).strip()), looked)
    return EditorInstallScan(
        EditorInstall(first_tree, "") if first_tree is not None else None, looked
    )


@dataclass
class DoctorCheck:
    """One line of the doctor report, with its own fix."""

    name: str
    label: str
    ok: bool
    detail: str
    fix: str = ""
    #: True when the check could not be performed at all (its prerequisite is
    #: missing, or the fact it compares against is not on this machine). A skip
    #: is printed and never fails the run — claiming red for a comparison that
    #: was never made would be its own kind of wrong.
    skipped: bool = False


@dataclass
class DoctorProbe:
    """Everything doctor learned, before it judges any of it.

    A plain container so that :func:`run_doctor` is a *pure* function of what was
    read: every branch (no daemon, no connector, an old editor, a stale bundle)
    is testable without a socket, a daemon or an editor.
    """

    port: int
    #: This install's own version (`boardwise.__version__`).
    daemon_version: str = ""
    #: The build the running connector announces (`sys.probe` → `connector`).
    connector_version: str = ""
    #: The editor's own version (`sys.probe` → `version`).
    editor_version: str = ""
    #: The version the *installed* editor tree declares
    #: (`<安装目录>/resources/app/package.json`), read offline. Empty when no
    #: tree was found; see `offline_editor_path` to tell "not found" from
    #: "found but unreadable".
    offline_editor_version: str = ""
    #: The install tree that version came from.
    offline_editor_path: str = ""
    #: The roots the offline scan looked under — for its skip message, so the
    #: reader learns *where* doctor looked instead of just that it found nothing.
    offline_editor_roots: tuple[str, ...] = ()
    #: The in-repo connector version (`connector/extension.json`), '' when absent.
    local_connector_version: str = ""
    ping: dict | None = None
    ping_error: str = ""
    probe: dict | None = None
    probe_error: str = ""
    documents: dict | None = None
    documents_error: str = ""


def _version_tuple(text: str) -> tuple[int, ...]:
    """``"v3.2.186 (build 7)"`` → ``(3, 2, 186)``; ``""`` → ``()``.

    Tolerant on purpose: the editor's version string is the host's business, and
    a check that goes red because of a suffix would be a false alarm.
    """
    match = re.match(r"\s*v?(\d+(?:\.\d+)*)", text or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def _editor_version_key(text: str) -> tuple[int, ...]:
    """The comparable part of an editor version: its first three fields.

    ``"3.2.186.b52e3e87"`` → ``(3, 2, 186)``, the same key as the ``"3.2.186"``
    `sys.probe` reports for the running editor. Without this, the install tree
    (build suffix included) would read as a *different* release from the editor
    it belongs to, and the offline/online comparison would cry wolf on every
    healthy machine.
    """
    return _version_tuple(text)[:EDITOR_VERSION_DEPTH]


def _project_counts(documents: dict, focused_project: dict) -> tuple[int, int]:
    """``(页数, PCB 数)`` of the focused project, in ``doc.list``'s arithmetic.

    ``projects[].schematics`` is a *document list*, not a page count: it carries
    the container schematic node (``schematic1``) alongside the pages, so a
    four-page project reads as five — the real host said "5 页原理图" on a
    project whose ``schematicPages`` was 4 (measured 2026-09-21). ``doc.list``
    has already counted both facts from ``documents[]``; use those numbers
    rather than re-deriving a count from a list whose length means something
    else.

    The list lengths stay as the fallback whenever those two fields are not
    numbers — an older connector build, or a payload that arrived malformed.
    doctor never raises for a payload it does not understand.
    """
    schematics = focused_project.get("schematics") or []
    pcbs = focused_project.get("pcbs") or []
    pages = documents.get("schematicPages")
    boards = documents.get("pcbs")
    return (
        pages if isinstance(pages, int) else len(schematics),
        boards if isinstance(boards, int) else len(pcbs),
    )


def _editor_floor_label(*, offline: bool) -> str:
    """The label of one of the two version lines.

    They ask about two different editors — the tree on disk and the editor that
    is running — and those disagree on a machine that upgraded without
    restarting, so the two lines must not read as the same question asked twice.
    """
    floor_text = ".".join(str(part) for part in EDITOR_API_FLOOR)
    if offline:
        return f"编辑器安装版本 ≥ {floor_text}（离线读安装目录，不用扩展）"
    return f"编辑器版本 ≥ {floor_text}"


def run_doctor(p: DoctorProbe) -> list[DoctorCheck]:
    """Judge one :class:`DoctorProbe`. Pure: no socket, no daemon, no editor."""
    checks: list[DoctorCheck] = []
    floor_text = ".".join(str(part) for part in EDITOR_API_FLOOR)

    # Issue #3: the floor is the first thing to fix and was the last thing
    # decidable — it sat behind daemon → extension → .eext → restart → pairing.
    # The install tree answers it offline, so it is judged first and says what to
    # do before any of the six lines below can even be read.
    offline = _editor_version_key(p.offline_editor_version)
    running = _editor_version_key(p.editor_version)
    if not p.offline_editor_path and not p.offline_editor_version:
        checks.append(
            DoctorCheck(
                name="editor-install",
                label=_editor_floor_label(offline=True),
                ok=True,
                skipped=True,
                detail=(
                    "跳过：离线没找到编辑器安装（扫过 "
                    + ("、".join(p.offline_editor_roots) or "（没有可扫的位置）")
                    + "）—— 这一项不作结论，版本留给下面的『编辑器版本』，那项要扩展连上才读得到"
                ),
            )
        )
    elif not offline:
        checks.append(
            DoctorCheck(
                name="editor-install",
                label=_editor_floor_label(offline=True),
                ok=True,
                skipped=True,
                detail=(
                    f"跳过：找到了安装树 {p.offline_editor_path}，但读不出 "
                    f"{EDITOR_MANIFEST.as_posix()} 里的可用版本"
                    + (
                        "（清单里没有 version 字段）"
                        if not p.offline_editor_version
                        else f"（清单里写的是 {p.offline_editor_version}）"
                    )
                    + "—— 这一项不作结论"
                ),
            )
        )
    elif running and offline != running and max(offline, running) >= EDITOR_API_FLOOR:
        # Two install trees disagree, and the disagreement changes the verdict:
        # the one that passes the floor is not the one that fails it. The tree
        # found on disk may not be the editor anyone is using, so calling it red
        # would be the false alarm this project keeps sweeping up — report the
        # discrepancy and let the line below judge the editor that is running
        # (which is the one boardwise talks to).
        checks.append(
            DoctorCheck(
                name="editor-install",
                label=_editor_floor_label(offline=True),
                ok=True,
                skipped=True,
                detail=(
                    f"跳过：安装树 {p.offline_editor_path} 是 {p.offline_editor_version}，"
                    f"正在运行的编辑器报 {p.editor_version}——两处不是同一个安装，"
                    "本项不作结论（下面的『编辑器版本』以跑着的那个为准）"
                ),
            )
        )
    elif offline >= EDITOR_API_FLOOR:
        checks.append(
            DoctorCheck(
                name="editor-install",
                label=_editor_floor_label(offline=True),
                ok=True,
                detail=(
                    f"安装树 {p.offline_editor_path} 的包清单写着 {p.offline_editor_version}"
                    f"（离线读 {EDITOR_MANIFEST.as_posix()}，没有经过桥）"
                ),
            )
        )
    else:
        checks.append(
            DoctorCheck(
                name="editor-install",
                label=_editor_floor_label(offline=True),
                ok=False,
                detail=(
                    f"安装树 {p.offline_editor_path} 的包清单写着 {p.offline_editor_version}"
                    f"（离线读 {EDITOR_MANIFEST.as_posix()}，没有经过桥）"
                    + ("；正在运行的编辑器也是这个版本" if running == offline else "")
                ),
                fix=(
                    f"先升级编辑器到 ≥{floor_text}，其余检查项都排在它后面——"
                    "现在这一步就能做，不用管 daemon 和扩展。"
                    "到 https://pro.easyeda.com/ 下载最新桌面版（装到哪儿都行，doctor 会自己找到），"
                    "装完重启编辑器再重跑 `boardwise doctor`"
                ),
            )
        )

    reachable = p.ping is not None
    checks.append(
        DoctorCheck(
            name="daemon",
            # The daemon has no HTTP surface at all — it is a WebSocket server
            # and `ping` is its health answer, so that is what is checked.
            label="daemon 可达（ping，daemon 无 HTTP /health）",
            ok=reachable,
            detail=(
                f"127.0.0.1:{p.port} 的 daemon 已应答 ping"
                if reachable
                else f"连不上 127.0.0.1:{p.port}：{p.ping_error or '没有应答'}"
            ),
            fix="" if reachable else "运行 `boardwise bridge start`（前台运行，保持窗口开着）；端口不是 61190 时用 --port 指明",
        )
    )

    attached = bool((p.ping or {}).get("connector"))
    fingerprint = (p.ping or {}).get("pairedFingerprint")
    checks.append(
        DoctorCheck(
            name="connector",
            label="扩展已连接（WebSocket 已注册到 daemon）",
            ok=attached,
            detail=(
                f"daemon 上注册着一个 connector，配对指纹 {fingerprint}"
                if attached
                else (
                    "daemon 上没有 connector"
                    if reachable
                    else "未验证：daemon 都没连上"
                )
            ),
            fix="" if attached else CONNECTOR_FIX,
        )
    )

    missing = _probe_missing(p.probe)
    if p.probe is None:
        probe_ok = False
        probe_detail = f"未验证：sys.probe 没有答复（{p.probe_error or '扩展未连接'}）"
    else:
        probe_ok = not missing
        probe_detail = (
            f"5/5 关键方法都是 function（{_probe_names()}）"
            if probe_ok
            else f"缺失或不是方法：{', '.join(missing)}"
        )
    checks.append(
        DoctorCheck(
            name="methods",
            label="sys.probe 关键方法在位",
            ok=probe_ok,
            detail=probe_detail,
            fix=(
                ""
                if probe_ok
                else CONNECTOR_FIX
                if p.probe is None
                else "这台编辑器缺少 harness 依赖的接口——对照 `docs/getting-started.md` 的版本要求，"
                "或先用 `boardwise bridge call --action sys.probe --params '{\"checks\":true}'` 看全表"
            ),
        )
    )

    editor = _editor_version_key(p.editor_version)
    # What the install tree has to say about the editor that is *running*. The
    # running one stays the authority (it is the editor boardwise talks to), so
    # the tree is used only where it sharpens the answer:
    # - the tree clears the floor and the running editor does not → the upgrade
    #   happened and the process is still the old build (or the old install is
    #   the one being launched): red, and the fix is a restart, not a download;
    # - anything else they disagree on → a note. A second, stale install on disk
    #   is worth naming, but it is not a fault in the editor in use.
    outdated_running = bool(offline and editor and editor < EDITOR_API_FLOOR <= offline)
    other_tree = bool(offline and editor and editor != offline and not outdated_running)
    if not p.editor_version:
        editor_ok = False
        editor_detail = f"未验证：没有读到编辑器版本（{p.probe_error or '扩展未连接'}）"
    else:
        editor_ok = bool(editor) and editor >= EDITOR_API_FLOOR and not outdated_running
        if outdated_running:
            editor_detail = (
                f"编辑器 {p.editor_version}（低于 {floor_text}，而跑着的这个不是装着的那个）："
                f"安装树 {p.offline_editor_path} 里已经是 {p.offline_editor_version}——"
                "升级之后编辑器没重启，或者启动的仍是旧的安装目录"
            )
        else:
            editor_detail = (
                f"编辑器 {p.editor_version}"
                + (
                    ""
                    if editor_ok
                    else f"（低于 {floor_text}："
                    "这套 harness 依赖的画布接口只在这条线以上实测过——"
                    "低于它的版本没有证据，不是判定为坏的）"
                )
                + (
                    f"（安装树 {p.offline_editor_path} 里是 {p.offline_editor_version}，"
                    "不是正在跑的这个）"
                    if other_tree
                    else ""
                )
            )
    checks.append(
        DoctorCheck(
            name="editor-version",
            label=_editor_floor_label(offline=False),
            ok=editor_ok,
            detail=editor_detail,
            fix=(
                ""
                if editor_ok
                else CONNECTOR_FIX
                if not p.editor_version
                else (
                    "把编辑器完全关掉（含所有窗口）再启动一次，然后重跑 `boardwise doctor`："
                    "跑着的比装着的旧，说明升级前的旧进程还活着；"
                    "重启后如果仍是旧版本，看启动的是哪个安装目录"
                    "（`(Get-Process lceda-pro).Path`）"
                )
                if outdated_running
                else "升级立创 EDA Pro 到 "
                f"{floor_text} 以上（当前 {p.editor_version}）"
            ),
        )
    )

    reported = str((p.ping or {}).get("version") or "")
    if not reachable:
        daemon_version_ok = False
        daemon_version_detail = "未验证：daemon 没有答复"
    elif not reported:
        daemon_version_ok = False
        daemon_version_detail = (
            "运行的 daemon 没有报告自己的版本——它早于这一项检查：重启 daemon 再看"
        )
    else:
        daemon_version_ok = reported == p.daemon_version
        daemon_version_detail = (
            f"运行的 daemon {reported}，本机 boardwise {p.daemon_version}"
        )
    checks.append(
        DoctorCheck(
            name="daemon-version",
            label="daemon 版本与本机一致（新动作才不会『不认识』）",
            ok=daemon_version_ok,
            detail=daemon_version_detail,
            fix=(
                ""
                if daemon_version_ok
                else "重启 daemon（`boardwise bridge start`）：动作表是加载期常量，"
                "跑着旧版本的 daemon 会把新动作答成 UNKNOWN_ACTION"
            ),
        )
    )

    if not p.local_connector_version:
        checks.append(
            DoctorCheck(
                name="connector-version",
                label="运行中的 connector 版本与仓库一致",
                ok=True,
                skipped=True,
                detail="跳过比对：本机没有 connector/extension.json（不是仓库里的运行方式）",
            )
        )
    elif not p.connector_version:
        checks.append(
            DoctorCheck(
                name="connector-version",
                label="运行中的 connector 版本与仓库一致",
                ok=False,
                detail=f"未验证：没有读到运行中的 connector 版本（{p.probe_error or '扩展未连接'}）",
                fix=CONNECTOR_FIX,
            )
        )
    else:
        same = p.connector_version == p.local_connector_version
        checks.append(
            DoctorCheck(
                name="connector-version",
                label="运行中的 connector 版本与仓库一致",
                ok=same,
                detail=(
                    f"编辑器里跑的是 connector {p.connector_version}，仓库里是 {p.local_connector_version}"
                ),
                fix=""
                if same
                else "运行 `boardwise bridge update-connector`（把仓库里的 bundle 热更新进编辑器；"
                "编辑器里跑的可能是上一次的构建）",
            )
        )

    focused_project = None
    for entry in (p.documents or {}).get("projects") or []:
        if isinstance(entry, dict) and entry.get("focused"):
            focused_project = entry
            break
    if p.documents is None:
        project_ok = False
        project_detail = f"未验证：doc.list 没有答复（{p.documents_error or '扩展未连接'}）"
    elif focused_project is None:
        project_ok = False
        project_detail = "编辑器里没有一个焦点工程——没有打开任何工程"
    else:
        project_ok = True
        active = (p.documents or {}).get("active") or {}
        uuid = str(active.get("uuid") or "")
        if uuid and uuid != "0":
            active_text = f"{active.get('type', '?')} {uuid[:8]}…"
        else:
            # "No active document" reaches doctor in three shapes and they mean
            # the same thing: `active: null` alone (nothing is focused),
            # `active: null` with the host's raw reading kept in `notes` (what
            # connector 0.4.6 does with the placeholder `uuid: "0"`), and the
            # placeholder itself in `active` (a connector older than 0.4.6 still
            # loaded in the editor). The line stays green in all three — the
            # focused project is readable either way, which is what this check
            # is about.
            notes = " ".join(str(note) for note in (p.documents or {}).get("notes") or [])
            active_text = (
                "无（宿主报占位读数 uuid=0：没有焦点文档，多窗口下常见）"
                if uuid == "0" or 'uuid "0"' in notes
                else "无（编辑器里没有焦点文档）"
            )
        pages, boards = _project_counts(p.documents or {}, focused_project)
        project_detail = (
            f"焦点工程：{focused_project.get('friendlyName') or focused_project.get('name') or '(无名)'}"
            f"（{str(focused_project.get('projectUuid') or '')[:8]}…，"
            f"{pages} 页原理图 / "
            f"{boards} 个 PCB）；活动文档：{active_text}"
        )
    checks.append(
        DoctorCheck(
            name="project",
            label="当前工程焦点可读",
            ok=project_ok,
            detail=project_detail,
            fix=(
                ""
                if project_ok
                else CONNECTOR_FIX
                if p.documents is None
                else "在编辑器里打开（或切到）一个工程，再重跑 doctor："
                "所有真机动作都作用在焦点工程上"
            ),
        )
    )

    return checks


def _probe_names() -> str:
    return ", ".join(
        f"{namespace}.{member}"
        for namespace, members in DOCTOR_PROBE_CHECKS.items()
        for member in members
    )


def _probe_missing(payload: dict | None) -> list[str]:
    """Which of the spot-checked methods are not `function`, as ``ns.member``."""
    if not isinstance(payload, dict):
        return [f"{ns}.{member}" for ns, members in DOCTOR_PROBE_CHECKS.items() for member in members]
    checks = payload.get("checks")
    checks = checks if isinstance(checks, dict) else {}
    missing: list[str] = []
    for namespace, members in DOCTOR_PROBE_CHECKS.items():
        report = checks.get(namespace)
        status = report.get("status") if isinstance(report, dict) else None
        status = status if isinstance(status, dict) else {}
        for member in members:
            if status.get(member) != "function":
                missing.append(f"{namespace}.{member}={status.get(member, '未报告')}")
    return missing


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Report whether this installation can do anything, and how to fix it (§九).

    Exit 0 only when every check is green (a deliberate *skip* is not a failure);
    exit 1 otherwise, each line carrying its own fix. The whole point is the
    disconnected case — daemon down, extension not loaded, an old editor — so
    that case is the one built first: nothing here raises, and every check says
    what it could not verify instead of crashing. The one line that needs no
    socket is judged from the editor's install tree and printed first (issue #3):
    upgrading the editor is the first fix, so it must not wait on the six that
    follow it.
    """
    import asyncio
    import json

    BridgeClient, BridgeError, port, token = _open_cli(args)
    probe = DoctorProbe(
        port=port,
        daemon_version=_local_version(),
        local_connector_version=_repo_connector_version(),
    )
    # Read the install tree *before* touching the socket: this is the one thing
    # doctor can answer on a machine where nothing else is set up yet, and it is
    # the answer that has to come first (issue #3).
    scan = scan_editor_install()
    probe.offline_editor_roots = tuple(str(root) for root in scan.roots)
    if scan.install is not None:
        probe.offline_editor_path = str(scan.install.path)
        probe.offline_editor_version = scan.install.version

    async def run() -> int:
        try:
            client = await BridgeClient.open(
                _bridge_uri(port), token, "cli", client="boardwise-doctor"
            )
        except (OSError, BridgeError) as exc:
            probe.ping_error = str(exc)
            return _finish_doctor(run_doctor(probe), probe, args)
        try:
            try:
                probe.ping = await client.call("ping")
            except BridgeError as exc:
                probe.ping_error = f"[{exc.code}] {exc.message}"
            if isinstance(probe.ping, dict) and probe.ping.get("connector"):
                # The window hint, when one was given: every check below is a
                # connector-owned call, and with several windows online the
                # daemon answers WINDOW_UNSPECIFIED rather than guessing (§3.5).
                target = {
                    "target_project": args.project or None,
                    "target_instance": args.instance or None,
                }
                try:
                    probe.probe = await client.call(
                        "sys.probe",
                        {"checks": {ns: list(members) for ns, members in DOCTOR_PROBE_CHECKS.items()}},
                        **target,
                    )
                except BridgeError as exc:
                    probe.probe_error = f"[{exc.code}] {exc.message}"
                try:
                    probe.documents = await client.call("doc.list", **target)
                except BridgeError as exc:
                    probe.documents_error = f"[{exc.code}] {exc.message}"
        finally:
            await client.close()
        if isinstance(probe.probe, dict):
            probe.connector_version = str(probe.probe.get("connector") or "")
            probe.editor_version = str(probe.probe.get("version") or "")
        return _finish_doctor(run_doctor(probe), probe, args)

    return asyncio.run(run())


def _local_version() -> str:
    from . import __version__

    return str(__version__)


def _cmd_install_skill(args: argparse.Namespace) -> int:
    """Install (or remove) the user-level copy of SKILL.md (028 §三.2).

    Exit codes: 0 for every outcome the user asked for — installed, updated,
    already current, removed, and "there was nothing to remove" — because a
    second run of an idempotent command is a success, not a failure. 1 is
    reserved for a filesystem step that actually failed, whose message names the
    path and the OS reason.

    The source is the *bundled* SKILL.md (``resources.skill_md()``), not a path
    the caller passes: the whole point is that the exe carries the checklist it
    installs, so "install the skill" cannot mean "install whatever is on disk
    next to me".
    """
    from . import resources, skill_install

    if args.uninstall:
        try:
            outcome = skill_install.uninstall()
        except skill_install.SkillInstallError as exc:
            print(f"boardwise install-skill: {exc}", file=sys.stderr)
            return 1
        if outcome.outcome == "absent":
            print(f"boardwise install-skill: nothing to remove at {outcome.path}")
            return 0
        tail = " (and the now-empty directory)" if outcome.removed_directory else ""
        print(f"boardwise install-skill: removed {outcome.path}{tail}")
        return 0

    try:
        source = resources.skill_md()
    except RuntimeError as exc:
        print(f"boardwise install-skill: {exc}", file=sys.stderr)
        return 1
    try:
        outcome = skill_install.install(source)
    except skill_install.SkillInstallError as exc:
        print(f"boardwise install-skill: {exc}", file=sys.stderr)
        return 1

    if outcome.outcome == "current":
        print(f"boardwise install-skill: already current — {outcome.path} matches {source}")
        return 0
    print(
        f"boardwise install-skill: {outcome.outcome} {outcome.path} "
        f"({source.stat().st_size} bytes from {source})"
    )
    if outcome.backup is not None:
        print(
            f"  the file that was there is kept at {outcome.backup} "
            f"({outcome.previous_bytes} bytes)"
        )
    return 0


def _repo_connector_version() -> str:
    """The version in the in-repo ``connector/extension.json``, or ``''``.

    Read rather than imported: the comparison that matters is "what the editor
    is running" against "what this checkout would install", and a missing
    checkout is a legitimate installation (a wheel), not an error.
    """
    import json

    try:
        _bundle, manifest = _connector_artifacts()
        return str(json.loads(manifest.read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def _finish_doctor(checks: list[DoctorCheck], probe: DoctorProbe, args: argparse.Namespace) -> int:
    import json

    failed = [check for check in checks if not check.ok]
    for check in checks:
        mark = "SKIP" if check.skipped else ("PASS" if check.ok else "FAIL")
        print(f"  {mark:<4} {check.label}")
        print(f"         {check.detail}")
        if check.fix:
            print(f"         → {check.fix}")
    print(
        f"\nboardwise doctor: {len(checks) - len(failed)}/{len(checks)} 项通过"
        + ("" if not failed else f"，{len(failed)} 项需要处理（上面的 → 就是建议）")
    )
    if failed:
        print(f"  先修第一项：{failed[0].label}")
    if args.json_path:
        Path(args.json_path).write_text(
            json.dumps(
                {
                    "ok": not failed,
                    "port": probe.port,
                    "versions": {
                        "daemon": probe.daemon_version,
                        "daemonRunning": str((probe.ping or {}).get("version") or ""),
                        "connectorRunning": probe.connector_version,
                        "connectorRepo": probe.local_connector_version,
                        "editor": probe.editor_version,
                        "editorInstall": probe.offline_editor_version,
                        "editorInstallPath": probe.offline_editor_path,
                    },
                    "checks": [
                        {
                            "name": check.name,
                            "label": check.label,
                            "ok": check.ok,
                            "skipped": check.skipped,
                            "detail": check.detail,
                            "fix": check.fix,
                        }
                        for check in checks
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0 if not failed else 1


BRIDGE_COMMANDS = {
    "start": _cmd_bridge_start,
    "status": _cmd_bridge_status,
    "revoke": _cmd_bridge_revoke,
    "screenshot": _cmd_bridge_screenshot,
    "export-fab": _cmd_bridge_export_fab,
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
    if args.command == "checkup":
        return _cmd_checkup(args)
    if args.command == "review-eval":
        return _cmd_review_eval(args)
    if args.command == "review-mark":
        return _cmd_review_mark(args)
    if args.command == "edit":
        return EDIT_COMMANDS[args.edit_command](args)
    if args.command == "doctor":
        return _cmd_doctor(args)
    if args.command == "install-skill":
        return _cmd_install_skill(args)
    if args.command == "compare":
        return _cmd_compare(args)
    if args.command == "draw":
        return _cmd_draw(args)
    if args.command == "lint":
        return _cmd_lint(args)
    if args.command == "persistence":
        return _cmd_persistence(args)
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
