"""Review CLI parser registration and runtime dispatch (540B5).

Only command-surface assembly lives here; review judgements stay in their engines
and historical handlers. This module never imports :mod:`boardwise.cli`. The
assembly layer supplies handlers or their live registries at call time, preserving
existing monkeypatch targets without creating a second review implementation.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from typing import Any

from ..engines.checkup import (
    TRIAGE_UNJUDGEABLE,
    TRIAGE_VERDICT_CHOICES,
    TRIAGE_VERDICTS,
)
from ..engines.reviewread import REVIEW_READ_SECTIONS


def register_review_parser(sub: Any) -> None:
    """Register the historical `review` command surface."""
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
        # Resolved in `_cmd_review`: `schematic` for a file (017's ruling: the
        # schematic is the design's truth) and `schematic` for --live (a live
        # model is a page model). A plain default here would make
        # `review --live` refuse its own sensible view.
        default=None,
        help=(
            "Which model of a .epro2 backup to review: schematic (the parsed "
            "schematic — **the default**, and the view the 011 review rules are "
            "written against) or pcb (the PCB netlist view, for board-level "
            "content: pads, tracks, vias). The schematic is the default because "
            "the pcb view reads the PCB document's own copy of the design, which "
            "goes stale whenever the schematic changed and the board was not "
            "re-synced — a review of such a file reports parts of a design that "
            "is no longer there (017). With --live the view is always schematic: "
            "the live data path yields pages."
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
            "when the online state cannot be stated, and also when the model it "
            "did obtain is empty (0 components and 0 nets) — a live reading with "
            "nothing in it is not a pass either, and checkup answers 3 for it."
        ),
    )
    review.add_argument(
        "--out",
        dest="out",
        metavar="DIR",
        default="",
        help=(
            "**Only for `review finalize`** (537D2a2). The review directory to "
            "validate: `boardwise review finalize --out DIR` recomputes "
            "`report.json` in memory, verifies the artifacts it cites, folds the "
            "triage sidecar back in and checks the filled `review-summary.md` — "
            "and re-syncs `report.json` / `report.md` / `board-report.md` only "
            "when the delivery validates. On success it also re-renders the "
            "summary's environment/evidence machine sections from the recomputed "
            "report; the human content around them is never touched. It then "
            "signs `finalize.json`, a deterministic CLI delivery receipt "
            "(`scope: delivery-content`) of the final files and cited evidence — "
            "not a board pass, and a DSH Session still needs D3. A plain file "
            "review ignores this flag."
        ),
    )


def register_checkup_parser(sub: Any) -> None:
    """Register the historical `checkup` command surface."""
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
    checkup.add_argument(
        "--library",
        default=None,
        help=(
            "The curated shelf the facts-driven sections read (default: "
            "blocklib/parts.json). `未审器件` uses it to say which facts a part "
            "is missing, and whether the LCSC channel has a datasheet link."
        ),
    )
    checkup.add_argument(
        "--intent",
        default="",
        metavar="PATH",
        help=(
            "The DesignIntent contract to read (090 A1) — what the board is *for*: "
            "rail voltages/currents, each chain's polarity and closure, the blocks "
            "and the decisions behind them. Default: "
            "~/.boardwise/design-intent/<projectUuid>.json when that file exists. "
            "checkup only **reads** it (regeneration is `boardwise arch --intent`), "
            "and the report's `intent` section names every slot it still owes."
        ),
    )
    aesthetics = checkup.add_mutually_exclusive_group()
    aesthetics.add_argument(
        "--aesthetics",
        dest="aesthetics",
        action="store_true",
        default=None,
        help=(
            "Turn the layout aesthetics section on for this run only (five axes, "
            "1-5 + evidence each). Overrides `config`'s review.aesthetics; the "
            "section is absent when the switch is off."
        ),
    )
    aesthetics.add_argument(
        "--no-aesthetics",
        dest="aesthetics",
        action="store_false",
        help="Turn it off for this run only, whatever the configuration says.",
    )


def register_need_datasheet_parser(sub: Any) -> None:
    """Register the historical `need-datasheet` command surface."""
    need_datasheet = sub.add_parser(
        "need-datasheet",
        help=(
            "Mark a device/pin the review cannot explain yet, so the report stops "
            "short of a pass (058 ⓪: ask for the datasheet before judging it)."
        ),
        description=(
            "The ⓪ 先问再判 step's input (issue #8). Records what the reviewer "
            "cannot establish from the drawing and the material at hand — a pin "
            "whose function is unknown, a whole device whose behaviour has to be "
            "read out of its datasheet — and merges it into the `needs_datasheet` "
            "section of an existing `checkup` report. The report's gate is then "
            "recomputed: `completion.verdict` becomes `incomplete`, "
            "`summary.conclusion` says how many pins are waiting, and `report.md` "
            "is re-rendered with the section that forbids claiming a pass while "
            "it is non-empty. Idempotent per `(part, pin)`: marking again updates "
            "the reason instead of adding a row. Purely offline — no editor, no "
            "daemon. Exit 0 applied / 2 bad input / 3 no report.json to mark up."
        ),
    )
    need_datasheet.add_argument(
        "--out",
        default="checkup",
        metavar="DIR",
        help=(
            "The `checkup --out` directory holding report.json (and the sidecar "
            "needs-datasheet.json). Default: %(default)s."
        ),
    )
    need_datasheet.add_argument(
        "--part",
        default="",
        metavar="REF",
        help=(
            "The designator whose function is not established (e.g. U7). "
            "Required unless --merge is used."
        ),
    )
    need_datasheet.add_argument(
        "--pins",
        action="append",
        default=None,
        metavar="P1,P2",
        help=(
            "Pin names (or numbers) that cannot be explained; repeatable, and each "
            "value may be a comma/space list. **Merge semantics** (516 B2): a later "
            "call for the same designator takes the **union** of its pins and the "
            "ones already recorded — it does not replace them. Omit it for 'the "
            "whole device'. Use --replace-pins to overwrite instead."
        ),
    )
    need_datasheet.add_argument(
        "--replace-pins",
        action="store_true",
        help=(
            "Drop the designator's existing pin marks before merging --pins, i.e. "
            "**overwrite** rather than union (516 B2). Without it the default is "
            "merge, so two calls accumulate pins."
        ),
    )
    need_datasheet.add_argument(
        "--merge",
        default="",
        metavar="SIDECAR.json",
        help=(
            "Batch-merge every mark from another `needs-datasheet.json` (516 A3) — "
            "one command instead of one per designator. `--part`/`--reason` are not "
            "needed with it, and a mark for a designator the report does not carry "
            "is reported as unmatched. Combines with --part if both are given."
        ),
    )
    need_datasheet.add_argument(
        "--reason",
        default="",
        help=(
            "Why it cannot be judged — what the datasheet would have to say. "
            "Required with --part: it is the only pointer to what to ask for."
        ),
    )
    need_datasheet.add_argument(
        "--json",
        dest="json_path",
        nargs="?",
        const="-",
        metavar="PATH",
        help=(
            "Write the merged result (the marked entries, the recomputed "
            "`completion`, the conclusion) as JSON. `-` prints it instead."
        ),
    )


def register_triage_parser(sub: Any) -> None:
    """Register the historical `triage` command surface."""
    triage = sub.add_parser(
        "triage",
        help=(
            "Record the verdict for one warning of an existing `checkup` report "
            "(有益/有害/无害 + reason, or needs-manual where the source gave no "
            "per-item text), so a re-run cannot drop it (issue #12)."
        ),
        description=(
            "xianyuyijinban's step ② as an action: one warning, one verdict, one "
            "reason. Writes the verdict into `warning_triage[]` of an existing "
            "`checkup` report **and** into the sidecar `warning-triage.json` beside "
            "it — which is what makes the judgement survive the next `checkup` "
            "(issue #12: the slots were the only AI channel with no way back in). "
            "The report's gate is recomputed on the spot: "
            "`completion.warningsPendingTriage` drops, `report.md` is re-rendered "
            "with the verdict in the table. Idempotent per `key`: a second run for "
            "the same key updates it rather than adding a row. **537B: a slot whose "
            "`text` is empty (the host's ERC totals, no per-item text) cannot be "
            "closed with the three words** — `有益/有害/无害` answer 「这条警告说的是"
            "什么」 and need the warning's own text, so the command refuses by name "
            "and writes nothing; `needs-manual` is the verdict for those, it takes "
            "the same `--reason`, and the row stays in `warningsPendingTriage` "
            "(counted apart as `warningsNeedsManual`). Purely offline — no "
            "editor, no daemon. Exit 0 applied / 2 bad input (including a key the "
            "report does not carry, or a three-word verdict on a text-less slot) / "
            "3 no report.json to triage."
        ),
    )
    triage.add_argument(
        "--out",
        required=True,
        metavar="DIR",
        help=(
            "The `checkup --out` directory holding report.json (and the sidecar "
            "warning-triage.json). Required: the verdict is written into that "
            "report, so guessing the directory would write it into the wrong one."
        ),
    )
    triage.add_argument(
        "--key",
        required=True,
        metavar="KEY",
        help=(
            "The `warning_triage[].key` of the warning being judged (e.g. "
            "`boardwise-rule:xtal-load-caps:Y1`). Unknown keys are refused by name."
        ),
    )
    triage.add_argument(
        "--verdict",
        required=True,
        choices=list(TRIAGE_VERDICT_CHOICES),
        metavar="VERDICT",
        help=(
            "One of: " + " / ".join(TRIAGE_VERDICTS) + " — or `" + TRIAGE_UNJUDGEABLE
            + "` for a slot with no per-item text (a host-ERC count): the three words "
            "need the warning's own text, `" + TRIAGE_UNJUDGEABLE + "` says a human must "
            "look, and the row stays in `completion.warningsPendingTriage`."
        ),
    )
    triage.add_argument(
        "--reason",
        required=True,
        help=(
            "Why that verdict — what makes the warning harmless or harmful. "
            "Required: it is the only pointer to what the judgement rested on."
        ),
    )
    triage.add_argument(
        "--json-path",
        "--json",
        dest="json_path",
        nargs="?",
        const="-",
        metavar="PATH",
        help=(
            "Write the merged result (the slots, the recomputed `completion`, the "
            "conclusion) as JSON. `-` prints it instead."
        ),
    )


def register_triage_batch_parser(sub: Any) -> None:
    """Register the historical `triage-batch` command surface."""
    triage_batch = sub.add_parser(
        "triage-batch",
        help=(
            "Apply a whole batch of warning verdicts to an existing `checkup` "
            "report in one atomic step (537D1b1): every row is checked and applied "
            "in memory first, so one bad row writes nothing at all."
        ),
        description=(
            "The batch form of `boardwise triage`: one JSON file of "
            "`{key, verdict, reason}` rows is validated **as a whole**, merged into "
            "`warning_triage[]` of an existing `checkup` report and into the sidecar "
            "`warning-triage.json` beside it, and only then written — `report.json`, "
            "the sidecar, `report.md` and `board-report.md` are rewritten once, "
            "after every row has passed. An unknown key, an empty reason, a word "
            "outside the vocabulary (`有益` / `有害` / `无害` / `needs-manual`), a "
            "three-word verdict on a slot with no per-item text, or the same key "
            "twice in the input refuses the whole batch with exit 2 and leaves every "
            "file byte-identical. A key the **report** carries twice is a different "
            "matter: every matching slot is updated and the count is disclosed as "
            "`duplicateReportKeys`. Exit 0 means the batch was applied, **not** that "
            "the board passed — the report's own gate is quoted, never re-decided. "
            "Purely offline: no editor, no daemon. `review-summary.md` is never "
            "written. Exit 0 applied / 2 unusable input or output path / 3 no "
            "report.json to triage."
        ),
    )
    triage_batch.add_argument(
        "--out",
        required=True,
        metavar="DIR",
        help=(
            "The `checkup --out` directory holding report.json (and the sidecar "
            "warning-triage.json). Required, like `boardwise triage`: the verdicts "
            "are written into that report."
        ),
    )
    triage_batch.add_argument(
        "--input",
        required=True,
        metavar="BATCH.json",
        help=(
            'The batch as a strict object: {"schema": "boardwise.triage-batch/1", '
            '"entries": [{"key": "…", "verdict": "…", "reason": "…"}]}. Entries must '
            "be non-empty, each key may appear once, and every key must exist in "
            "the report."
        ),
    )
    triage_batch.add_argument(
        "--json-path",
        "--json",
        dest="json_path",
        nargs="?",
        const="-",
        metavar="PATH",
        help=(
            "Write the batch result (per-row matched/added/updated, the slots, the "
            "recomputed `completion`, the conclusion) as JSON. `-` prints it "
            "instead; with no `--json` the human summary is printed and stdout "
            "carries no JSON. Protected report files are refused by name."
        ),
    )


def register_review_evidence_parser(sub: Any) -> None:
    """Register the historical `review-evidence` command surface."""
    review_evidence = sub.add_parser(
        "review-evidence",
        help=(
            "Collect the live schematic/PCB evidence for an existing `checkup` "
            "report and merge it into that report's evidence ledger (537C3b2)."
        ),
        description=(
            "The 537C fix for a review that read the live schematic, failed to "
            "read the live PCB and produced no PCB image — with none of it "
            "disclosed. This command opens the editor through the bridge, runs "
            "`engines.liveevidence.collect_live_evidence` once (doc.list identity, "
            "then per-document doc.open → document.current focus proof → "
            "readback/netlist/geometry/render, focus restored in `finally`), "
            "writes the whole capture to `<out>/live-evidence.json` with its "
            "bytes/sha256, and merges it into `<out>/report.json`'s `evidence` "
            "section through `merge_live_capture` (four live channels replaced, "
            "archive/datasheets untouched, identity/focus disclosures added). "
            "`report.json`, `report.md` and `board-report.md` are then re-written "
            "from that one report reading. It **never** rewrites "
            "`review-summary.md`: what a human wrote there is not this command's "
            "to replace. The board-level conclusion (`completion`, `summary`, "
            "`conclusion`) is not changed — collecting evidence is not judging "
            "the board. Paths: --project/--instance choose the editor window "
            "(023), --page/--pcb may be repeated to collect an explicit subset "
            "(an explicit subset is disclosed as `missing` coverage, never `ok`). "
            "Purely read-only actions; no design write. Exit codes describe "
            "**this collection**: 0 = the collector returned ok, the identity was "
            "verified against the report (`source.project.projectUuid`) and the "
            "original focus was restored (a channel with nothing to read, e.g. no "
            "PCB document, is `not-applicable` and does not block) · 1 = the "
            "collector returned but some direct evidence failed/missing, the "
            "selection was an explicit subset, the identity was not verified "
            "(including a report with no project uuid) or the focus was not "
            "restored · 2 = unusable input (no/broken report, an evidence section "
            "of another schema, a merge that refuses the capture, a report that "
            "cannot be written) · 3 = nothing may be stated (no `report.json`, the "
            "daemon cannot be reached, or `doc.list` itself failed — the capture "
            "and its failure disclosure still land). 0 is not a board pass: the "
            "board conclusion stays `report.json`'s `conclusion`."
        ),
    )
    review_evidence.add_argument(
        "--out",
        required=True,
        metavar="DIR",
        help=(
            "The `checkup --out` directory holding report.json. Required: the "
            "capture is merged into that report, so guessing the directory would "
            "write the evidence into the wrong one."
        ),
    )
    review_evidence.add_argument(
        "--project",
        default="",
        help=(
            "Which editor window to read, by project name or uuid (023). Needed "
            "only when several windows are connected and none can be named by "
            "the daemon's default."
        ),
    )
    review_evidence.add_argument(
        "--instance",
        default="",
        help=(
            "The same choice spelled as the window key `bridge status` prints — "
            "the way to reach one window when no project can be read yet."
        ),
    )
    review_evidence.add_argument(
        "--port", type=int, default=None, help="Daemon port (default 61190)."
    )
    review_evidence.add_argument(
        "--page",
        action="append",
        default=None,
        metavar="UUID",
        help=(
            "Collect only this schematic page (repeat for several). Default: every "
            "document `doc.list` reports. An explicit subset is recorded as "
            "`missing` coverage, never `ok` — the pages left out were not read."
        ),
    )
    review_evidence.add_argument(
        "--pcb",
        action="append",
        default=None,
        metavar="UUID",
        help="Collect only this PCB document (repeat for several). Default: all.",
    )


def register_review_read_parser(sub: Any) -> None:
    """Register the historical `review-read` command surface."""
    review_read = sub.add_parser(
        "review-read",
        help=(
            "Read one existing `checkup` report as structured JSON — one of the "
            "questions a review asks (537D1a)."
        ),
        description=(
            "The 537D fix for the review's worst habit: every question about a "
            "report was answered by a hand-written one-off JSON parser, and a "
            "missing key read as 「零问题」. This command is the one structured "
            "read, and it projects — it never re-gates, renders or writes the "
            "report. `--section` is one of: "
            + " / ".join(REVIEW_READ_SECTIONS)
            + ". `verdict` is `report.conclusion` and nothing else (a report "
            "without it is `status: \"missing\"`; `summary.conclusion` is a "
            "sentence and is never promoted to a verdict). `findings` carries the "
            "findings list and the triage ledger with `warningsPendingTriage` / "
            "`warningsNeedsManual` counted through checkup's own predicates — a "
            "`needs-manual` row stays pending. `crossView` copies every board's "
            "`crossView` verbatim (`checked: false`, `suspected` and the candidate "
            "mappings included) and says `missing` when there is none. `coverage` "
            "copies the environment/evidence ledgers and names every absent "
            "section in `missingSections` instead of guessing it. `netlist` "
            "projects the live capture's own parsed netlist (components, nets, "
            "pin names) in sorted order, and answers `missing` with a reason "
            "when the capture did not verify, the live schematic is not `ok`, or "
            "no netlist artifact was cited; a cited netlist that fails its "
            "bytes/sha256/UTF-8/parse proof is exit 2. `artifacts` lists every "
            "file the report's machine fields cite (canvas images, channel "
            "artifacts, the live capture's own files, then the five standard "
            "outputs) with `path`/`exists`/`bytesOnDisk`/`bytesMatch`/"
            "`sha256Matches`/`error` per row, `missingOutputs` for absent "
            "standard outputs, and a final `status` of ok / missing / "
            "unavailable; a citation outside `--out` is refused before it is "
            "read. "
            "The envelope is `{schema: \"boardwise.review-read/1\", section, "
            "report: {path, schema}, payload}` — no `ok` field, because a "
            "successful read is not a passed board. The same input bytes produce "
            "the same output bytes. Exit codes describe **this read**: 0 projected "
            "· 2 unusable input (no report object, broken JSON, a projection that "
            "refuses the report, an output that cannot be written) · 3 no "
            "`report.json` to read. `--json PATH` may create a new file but never "
            "overwrites the report or the products beside it (`report.json`, "
            "`report.md`, `board-report.md`, `review-summary.md`, "
            "`live-evidence.json`): naming one of those is exit 2 with every byte "
            "unchanged."
        ),
    )
    review_read.add_argument(
        "--out",
        required=True,
        metavar="DIR",
        help=(
            "The `checkup --out` directory holding report.json. Required: guessing "
            "the directory would answer about a different review."
        ),
    )
    review_read.add_argument(
        "--section",
        required=True,
        choices=list(REVIEW_READ_SECTIONS),
        metavar="SECTION",
        help=(
            "Which question to answer: " + " / ".join(REVIEW_READ_SECTIONS)
            + ". `verdict` is the board-level answer (`report.conclusion`); "
            "`findings` the findings + triage ledger; `crossView` the per-board "
            "cross-view sections; `coverage` the environment/evidence ledger and "
            "what the report does not carry; `artifacts` every cited file with "
            "its on-disk verification; `netlist` the live capture's parsed "
            "netlist (or why there is none)."
        ),
    )
    review_read.add_argument(
        "--json",
        dest="json_path",
        nargs="?",
        const="-",
        metavar="PATH",
        help=(
            "Write the envelope as UTF-8 pretty JSON (stable bytes) instead of "
            "printing it. `-` (and a bare `--json`) prints it, which is exactly "
            "the default. A path inside `--out` naming one of the five protected "
            "inputs is refused before anything is written."
        ),
    )


def register_review_eval_parser(sub: Any) -> None:
    """Register the historical `review-eval` command surface."""
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


def register_review_mark_parser(sub: Any) -> None:
    """Register the historical `review-mark` command surface."""
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


def register_parts_parser(sub: Any) -> None:
    """Register the historical `parts` command surface."""
    parts = sub.add_parser(
        "parts",
        help=(
            "The curated part library (task 008b): offline selection from "
            "blocklib/parts.json, with an explicit --online catalog compare."
        ),
    )
    parts_sub = parts.add_subparsers(dest="parts_command", required=True)
    parts_missing = parts_sub.add_parser(
        "missing",
        help="Offline: which U-prefix parts of a project the facts shelf cannot judge yet.",
        description=(
            "Read an .epro2 / .eprj3 project offline and list every U-prefix part with "
            "the fact keys the shelf is missing for it (and its category state). Exit 0 "
            "always — this is a report, not a failure: 0 means every part is judgeable, "
            "and a non-empty list is still exit 0 because 'the shelf has work to do' is "
            "information, not an error. Exit 2 is reserved for an input that cannot be "
            "read. --json is the machine shape the AI consumes."
        ),
    )
    parts_missing.add_argument(
        "--file", required=True, help="The .epro2 / .eprj3 project to read (read-only)."
    )
    parts_missing.add_argument(
        "--library", default=None, help="The shelf to judge against (default blocklib/parts.json)."
    )
    parts_missing.add_argument(
        "--json", dest="json_path", metavar="PATH", help="Write the machine-readable report."
    )
    parts_show = parts_sub.add_parser(
        "show",
        help="Dump one shelf entry: identity, facts, every provenance line, gate state.",
        description=(
            "Human-readable dump of one entry, looked up by MPN or key (exact first, then "
            "case-insensitive). Not found → exit 2 with up to five substring candidates, "
            "because 'no such part' without 'did you mean' is a dead end."
        ),
    )
    parts_show.add_argument("query", help="MPN or key, e.g. CH340N or ic.rt9013_33gb.")
    parts_show.add_argument(
        "--library", default=None, help="The shelf to read (default blocklib/parts.json)."
    )
    parts_show.add_argument(
        "--json", dest="json_path", metavar="PATH", help="Write the entry as JSON."
    )
    parts_list = parts_sub.add_parser(
        "list",
        help="One line per shelf entry, each labelled with the shelf it came from (191B).",
        description=(
            "The shelf as a list: key, MPN, C-number, value, category and the **source** of "
            "the row. On a frozen exe the review reads the user's shelf *and* the copy the "
            "exe carries, merged by identity (the user's entry wins for the same part), so "
            "an entry an upgrade brought into the bundle is visible without the user "
            "re-curating anything — and every row says which of the three it is: `user` "
            "(only the user's shelf has it), `builtin` (only the exe's copy has it) or "
            "`user-overrides-builtin` (both have the part and the user's entry won). From a "
            "checkout, or with an explicit `--library`, there is one shelf and every row "
            "reads `-` instead of a label that would invent a second one. Exit 0 read / 2 "
            "the shelf cannot be read."
        ),
    )
    parts_list.add_argument(
        "--library", default=None,
        help="The shelf to list (default: the shelf this install reads).",
    )
    parts_list.add_argument(
        "--category", default="", metavar="词",
        help="Only entries whose category contains this text（如 ic / resistor）。",
    )
    parts_list.add_argument(
        "--query", default="", metavar="文本",
        help="Only entries whose key / MPN / C-number / value contains this text（大小写不敏感）。",
    )
    parts_list.add_argument(
        "--limit", type=int, default=0, metavar="N",
        help="At most N rows (default 0 = all).",
    )
    parts_list.add_argument(
        "--json", action="store_true", help="Print the machine-readable list.",
    )
    parts_add = parts_sub.add_parser(
        "add",
        help=(
            "Append a candidate entry, or write facts into the shelf "
            "(--facts/--fact; --verified closes the gate)."
        ),
        description=(
            "Two jobs in one flow. Identity only (`boardwise parts add <MPN> "
            "--lcsc C1234`): append a candidate entry — no category, no facts, "
            "facts_trust candidate, provenance.kind manual-curation. With facts "
            "(`--facts <file.json>` / repeated `--fact KEY=JSON`): write those "
            "facts onto the entry — the one already on the shelf when the "
            "identity exists (that is the candidate `parts fetch` left behind), "
            "otherwise a new one — and `--verified` is the engineer's explicit "
            "declaration that they were checked, which is what makes them drive "
            "rules. Without `--verified` the facts are a candidate's claim and "
            "drive nothing. `--verified` is never implied. A duplicate insisted "
            "on without facts is refused (exit 2) and points at `parts show`. "
            "The file is edited at the JSON-document level so existing entries "
            "keep their exact bytes, backed up to a .tmp sibling first, and "
            "re-parsed with the real validator before the write is called done. "
            "`--resolve` (187c) fills the two uuids the verified gate demands "
            "from the online bridge — one command from a datasheet to a landed "
            "entry."
        ),
    )
    parts_add.add_argument("mpn", help="The manufacturer part number to add.")
    parts_add.add_argument("--lcsc", required=True, help="Its LCSC C-code (e.g. C2977777).")
    parts_add.add_argument(
        "--key", default=None, help="Shelf key (default: derived from the MPN)."
    )
    parts_add.add_argument(
        "--facts", default=None, metavar="FILE",
        help=(
            "A JSON file holding the facts object (keys from the fact "
            "vocabulary). `parts fetch`'s <stem>.candidate.json is accepted as "
            "it stands. Every fact is validated by the same loader the shelf "
            "uses, page-cited provenance included."
        ),
    )
    parts_add.add_argument(
        "--fact", action="append", default=None, metavar="KEY=JSON",
        help=(
            "One fact record, repeatable: --fact 'nc_pins={\"pins\":[\"2\"],"
            "\"provenance\":\"file:ds.pdf p.3\"}'. The value is JSON because "
            "every fact kind is a record, not a scalar."
        ),
    )
    parts_add.add_argument(
        "--verified", action="store_true",
        help=(
            "Declare the facts checked: writes the entry with facts a rule may "
            "act on (needs facts, and the schema's uuid pair — see the note it "
            "prints). Never implied, and never the default."
        ),
    )
    parts_add.add_argument(
        "--force", action="store_true",
        help=(
            "Replace facts an entry already carries (only meaningful with "
            "--facts/--fact). Without it, an entry whose facts drive rules is "
            "never overwritten."
        ),
    )
    parts_add.add_argument(
        "--category", default="", help="Shelf category (vocabulary-checked), e.g. ic.ldo."
    )
    parts_add.add_argument(
        "--device-uuid", default="", help="Bridge device uuid (required with --verified)."
    )
    parts_add.add_argument(
        "--library-uuid", default="", help="Bridge library uuid (required with --verified)."
    )
    parts_add.add_argument(
        "--resolve", action="store_true",
        help=(
            "Fill --device-uuid/--library-uuid from the online bridge (187c): "
            "lib.device.search on the C-number, then on the MPN. Offline is a "
            "refusal, never an invented uuid; an explicitly given uuid wins."
        ),
    )
    parts_add.add_argument(
        "--library", default=None, help="The shelf to append to (default blocklib/parts.json)."
    )
    parts_add.add_argument(
        "--json", dest="json_path", metavar="PATH", help="Write the machine-readable result."
    )
    parts_accept = parts_sub.add_parser(
        "accept-unknown",
        help=(
            "工程师明示接受一颗器件的未知（写进设计意图合同）—— "
            "该件不再让 completion.verdict 停在 incomplete，但报告一直写着这个数。"
        ),
        description=(
            "191A: the datasheet gate's second exit. A part the shelf cannot judge "
            "stops the review (`unreviewed_parts` → `verdict: incomplete`); the other "
            "way out is to **state that it need not be judged**. The acceptance is "
            "written into the DesignIntent contract "
            "(`acceptedUnknown[]`: part / reason / who / when / board), which is the "
            "file `checkup` already reads — so the next run moves that part out of "
            "`unreviewed_parts` into the report's `accepted_unknown[]`, stops being "
            "`incomplete` because of it, and still says 「另有 N 颗工程师接受未审」 in "
            "the quotable conclusion. `--reason` is mandatory (an acceptance with no "
            "reason would be a silent pass); `--revoke` takes one back. A contract "
            "entry whose part the drawing no longer has is kept and marked `stale` "
            "rather than deleted. Exit 0 written / 2 unusable input, a missing "
            "`--reason`, or a `--revoke` with nothing to revoke."
        ),
    )
    parts_accept.add_argument("part", help="MPN 或位号（checkup 的未审清单用这两个键认件）。")
    parts_accept.add_argument(
        "--reason", default="", metavar="TEXT",
        help=(
            "这颗的哪些未知被接受、为什么。接受时**必填**（撤销不需要）：没有理由的接受"
            "就是静默变绿，本通道不准。"
        ),
    )
    parts_accept.add_argument(
        "--board", default="", metavar="名",
        help="只在这个板上接受（多板工程用；单板工程可省，省了就是全板）。",
    )
    parts_accept.add_argument(
        "--revoke", action="store_true",
        help="撤销接受：从合同里删掉这条记录。合同里没有它 → exit 2（目标缺失就停，不算已撤销）。",
    )
    parts_accept.add_argument(
        "--file", default="", metavar="PATH",
        help=(
            "工程（.epro2 / .eprj3 目录）——只读：用它解析合同默认路径"
            "（和 checkup 同一份），并核对令牌是否真在这块板上。"
        ),
    )
    parts_accept.add_argument(
        "--intent", default="", metavar="PATH",
        help="显式指定合同路径（优先于 --file 推出的默认路径）。",
    )
    parts_accept.add_argument(
        "--who", default="", help="谁接受的（默认取本机用户名，纯审计字段）。"
    )
    parts_accept.add_argument(
        "--library", default=None, help="解析默认合同路径时用的货架（默认 blocklib/parts.json）。"
    )
    parts_accept.add_argument(
        "--json", dest="json_path", metavar="PATH",
        help="Write the machine-readable result（`-` = stdout）。",
    )
    parts_fetch = parts_sub.add_parser(
        "fetch",
        help="Get a datasheet and turn it into a candidate entry (facts_verified: false).",
        description=(
            "Two channels, in the order xianyuyijinban named them. `--file <local PDF>` is the "
            "engineer handing one over; without it, the shelf entry's own LCSC "
            "links (datasheetPdfUrl first, then the product page) are downloaded "
            "into .tmp_datasheets/ (gitignored). Either way the PDF's text is "
            "dumped beside it page by page, a narrow extractor proposes "
            "supply_pins / required_caps / nc_pins records that quote their own "
            "line and page, and the entry is written with facts_verified: false — "
            "a candidate drives no rule until a human vouches for it. The third "
            "channel (the vendor's own site) is the AI's, via WebSearch; this "
            "command prints the queries to start from when it cannot get a PDF. "
            "Exit 0 fetched / 2 nothing to fetch or the input is unusable."
        ),
    )
    parts_fetch.add_argument("query", help="MPN, shelf key or C-number of the part.")
    parts_fetch.add_argument(
        "--file", dest="pdf_file", default=None,
        help="A local PDF the engineer provided (skips the download entirely).",
    )
    parts_fetch.add_argument(
        "--library", default=None, help="The shelf to write into (default blocklib/parts.json)."
    )
    parts_fetch.add_argument(
        "--out", default=".tmp_datasheets",
        help="Where the PDF and its text dump go (default: %(default)s, gitignored).",
    )
    parts_fetch.add_argument(
        "--force", action="store_true",
        help=(
            "Replace facts an entry already carries (and re-close the gate). "
            "Without it, an entry whose facts drive rules is never overwritten."
        ),
    )
    parts_fetch.add_argument(
        "--json", dest="json_path", metavar="PATH", help="Write the machine-readable result."
    )
    parts_hunt = parts_sub.add_parser(
        "hunt",
        help="Address every part of a board at once, and hand back the search work order.",
        description=(
            "The batch half of `parts fetch` (520). Every component of a board is classified "
            "into one of three channels — a valid 立创 C-number (asked about via the product "
            "detail API, which sends the C-number and nothing else), an MPN only (needs a "
            "search engine), or no identity at all (the engineer's own job). Whatever comes "
            "back as a PDF is checked for the PDF magic before the extractor sees it: a "
            "landing page or a 404 is `download-failed`, never a text dump that reads as "
            "'the datasheet says nothing'. Four artefacts land in --out: "
            "hunt-report.json (every part and its outcome), hunt-plan.json (the parts that "
            "need a search, as {designator, mpn, query} only), hunt-report.md (the one-page "
            "read) and hunt-audit.jsonl (one line per outbound call — the evidence that only "
            "a C-number or an MPN left the machine). `--apply answers.json` is the second "
            "stage: hand-found URLs come back in and go through the same download / extract "
            "/ land path. Nothing here verifies anything: entries land with "
            "facts_verified: false, so 喂 PDF ≠ 清闸 still holds. Exit 0 report written / "
            "2 the input or an answers file cannot be read."
        ),
    )
    parts_hunt.add_argument(
        "--file", required=True, help="The .epro2 / .eprj3 project to address (read-only)."
    )
    parts_hunt.add_argument(
        "--out", required=True, help="Where the four artefacts and the candidate sidecars go."
    )
    parts_hunt.add_argument(
        "--offline", action="store_true",
        help=(
            "Classification and work order only: not a single outbound call (an injected "
            "fetcher that raises goes unused). CI and confidential boards use this."
        ),
    )
    parts_hunt.add_argument(
        "--shelf", default=None, metavar="PATH",
        help=(
            "Write the extracted facts into this parts.json as candidates. Without it only "
            "the sidecars under --out are written — a batch run does not quietly edit a shelf."
        ),
    )
    parts_hunt.add_argument(
        "--cache", default=None, metavar="DIR",
        help="Cross-board PDF cache (default: <boardwise home>/datasheets).",
    )
    parts_hunt.add_argument(
        "--no-cache", action="store_true",
        help=(
            "Do not reuse PDFs across runs: the store moves inside --out, so this run's "
            "downloads travel with its report and the next run starts from nothing."
        ),
    )
    parts_hunt.add_argument(
        "--limit", type=int, default=0, metavar="N",
        help="Only the first N parts, for a batched run (default 0 = all).",
    )
    parts_hunt.add_argument(
        "--apply", default=None, metavar="PATH",
        help=(
            "Stage two: a JSON list of {designator|lcsc|mpn, url} to replay through the same "
            "download/extract/land path. A designator the board does not have becomes an "
            "`unknown-designator` row and the rest are processed normally."
        ),
    )
    parts_hunt.add_argument(
        "--apply-facts", default=None, metavar="PATH", dest="apply_facts",
        help=(
            "Stage three: a JSON list of {designator|lcsc|mpn, facts, quotes} — what an "
            "AI or an engineer read out of the cached <C-number>.txt. Every quote must "
            "appear VERBATIM on the page it cites (whitespace runs folded) or the claim "
            "is `facts-rejected` and nothing of it lands. Accepted claims still land as "
            "candidates (facts_verified: false): the gate checks the evidence, not the "
            "reading. Needs no network — the dump is already on disk."
        ),
    )
    parts_classify = parts_sub.add_parser(
        "classify",
        help=(
            "Give an entry its `category` — with evidence (machine tier) or by "
            "hand (human tier)."
        ),
        description=(
            "523/527D: the first-class route to a shelf entry's `category`. "
            "`parts hunt --apply-facts` can write facts that drive calculations, "
            "but until this command existed nothing could set the class those "
            "facts are judged against — `rules.facts._category_state` answers "
            "UNKNOWN for an entry with no category whatever else is on it — so "
            "the only way was editing blocklib/parts.json by hand. The word must "
            "come from the shelf's own table (`core.parts.CATEGORY_VOCABULARY`); "
            "anything else is exit 2 with the legal families listed, because the "
            "table is extended by decision and never by typo. "
            "`--from` + `--page` + `--quote` **together** are the evidence: the "
            "quote goes through 521's gate (at least "
            "10 characters / 3 words, whole-word, verbatim on the page it cites, "
            "checked against a document on disk — no network), and the entry is "
            "written `category_trust: machine_verified`. A category is a "
            "**conclusion**, so 522's dividing line applies: the machine tier "
            "unlocks the calculation rules and no connectivity / safety rule. "
            "With no evidence at all the class is written as the **human** tier "
            "(`verified`, the default — no key in the file) and the output says "
            "so. Only the entry's class keys move: `category`, `category_trust`, "
            "and — with evidence — `category_provenance` (527D2), which keeps "
            "the three flags on the shelf so the citation survives the terminal "
            "(a re-sign without evidence takes it back off): every "
            "other byte of the shelf is preserved, the file is backed up to a "
            ".tmp sibling and re-parsed with the real validator. Exit 0 written "
            "/ 2 a word outside the table, an entry the shelf does not have (this "
            "command never creates one), or evidence that does not hold."
        ),
    )
    parts_classify.add_argument(
        "entry", help="MPN、货架 key 或 C 号码，例如 CH340N / ic.rt9013_33gb / C2977777。",
    )
    parts_classify.add_argument(
        "category", help="分类词，必须落在货架词表里（如 ic.ldo、resistor、module）。",
    )
    parts_classify.add_argument(
        "--from", dest="source", default="", metavar="URL|file:路径",
        help=(
            "分类这条结论的出处：http(s) URL，或 `file:<本地 PDF / 页 dump>`"
            "（522/524 的保密口径：不收裸路径）。与 --page/--quote 三条齐全才算带证据。"
        ),
    )
    parts_classify.add_argument(
        "--page", type=int, default=0, metavar="N",
        help="引文所在页码（1 开始）。要和 --from/--quote 一起给。",
    )
    parts_classify.add_argument(
        "--quote", default="", metavar="文本",
        help=(
            "证据原句，走 521 的引文闸：≥10 字符、≥3 个词、两端词边界、"
            "且逐字出现在 --page 那一页上（空白折叠是唯一的放宽）。"
        ),
    )
    parts_classify.add_argument(
        "--cache", default=None, metavar="DIR",
        help=(
            "http(s) --from 的引文对着这个资料缓存核（默认 <boardwise home>/datasheets，"
            "即 parts fetch / parts hunt 留下的 <C码>/<C码>.pages.json）。"
        ),
    )
    parts_classify.add_argument(
        "--library", default=None, help="要改的货架（默认 blocklib/parts.json）。",
    )
    parts_classify.add_argument(
        "--json", dest="json_path", metavar="PATH", help="Write the machine-readable result.",
    )
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
        "--library", default=None,
        help=(
            "Path to the curated library (default: the shelf this install "
            "reads — `blocklib/parts.json` from a checkout, the copy the exe "
            "carries when frozen)."
        ),
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


def register_bom_parser(sub: Any) -> None:
    """Register the historical `bom` command surface."""
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
        "--library", default=None,
        help=(
            "Path to the curated library (default: the shelf this install "
            "reads — `blocklib/parts.json` from a checkout, the copy the exe "
            "carries when frozen)."
        ),
    )
    export.add_argument(
        "--out", default="",
        help="Write the CSV here (default: print the report only).",
    )
    export.add_argument(
        "--json", action="store_true", help="Print the machine-readable report.",
    )


def dispatch_review(
    args: argparse.Namespace,
    handler: Callable[[argparse.Namespace], int],
) -> int:
    """Resolve one direct review-domain handler at call time."""
    return handler(args)


def dispatch_parts(
    args: argparse.Namespace,
    handlers: Mapping[str, Callable[[argparse.Namespace], int]],
) -> int:
    """Resolve the parts subcommand through its historical live registry."""
    return handlers[args.parts_command](args)


def dispatch_bom(
    args: argparse.Namespace,
    handlers: Mapping[str, Callable[[argparse.Namespace], int]],
) -> int:
    """Resolve the BOM subcommand through its historical live registry."""
    return handlers[args.bom_command](args)
