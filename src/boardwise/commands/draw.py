"""Draw CLI parser registration and runtime dispatch (540B4).

Only command-surface assembly lives here; drawing decisions remain in the engines.
This module never imports :mod:`boardwise.cli`. The assembly layer supplies the
historical handler registry at call time, so existing monkeypatches keep their
observable behavior and the command module cannot become a second implementation.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from typing import Any

from ..engines.generate import DEFAULT_NAMING_STRATEGY, NAMING_STRATEGIES

#: Where `draw islands propose` writes when no `--out` is given.  A directory of
#: its own rather than beside `outputs/054_drawcompile`: a proposal is not a
#: drawing, and the two must not be mistaken for each other in a directory listing.
DEFAULT_ISLANDS_OUT = "outputs/530e_islands"
EDIT_DIRECTIONS = ("value", "mpn")


def register_draw_parser(sub: Any, *, force_help: str) -> None:
    """Register the legacy draw flow and its seven subcommands, in old order."""
    from ..core.portmeta import default_port_meta_path

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
            "auto: name a signal net only when it is long or cross-page — "
            "everything else is read off its wires (a net label is an "
            "electrical net port in EasyEDA, so naming everything buries "
            "connections); "
            "wire: the wire carries the net name only; "
            "text: wire plus a decorative text label beside every signal net "
            "(visible, not an electrical object — the report says so); "
            "label: the native net-label API (needs an EDA v4 host; dormant); "
            "none: no signal names at all. Rails always keep their flags."
        ),
    )
    draw.add_argument(
        "--port-meta", default=default_port_meta_path(),
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
    # ---- 054 stage C1: the compiled drawing's three commands ----------------
    #
    # The group sits *beside* the 006 flow rather than replacing it: the legacy
    # invocation carries no positional (`draw --spec X`), so an optional
    # subparsers group leaves it untouched, and `draw compile|plan|apply` are the
    # compiled-drawing path (053's `LayoutPlan`, landed through a ChangePlan).
    draw_sub = draw.add_subparsers(dest="draw_command", required=False)

    draw_compile = draw_sub.add_parser(
        "compile",
        help=(
            "Offline: compile two specs into legal drawings, rank them, and write "
            "the previews (053 stage B, task 054)."
        ),
        description=(
            "The compiler that turns a CircuitSpec + PresentationSpec + a symbol "
            "library into the legal drawings that survived its hard gate, best "
            "first — at most eight, and one or two is a normal success. It prints "
            "the ranking "
            "(the layers are compared, never summed), the four refusal categories "
            "with the action that would fix each one, and writes one SVG preview "
            "and one LayoutPlan JSON per candidate. Nothing here touches the "
            "editor. Exit 0 at least one candidate / 5 the compiler refused or an "
            "input could not be read."
        ),
    )
    draw_compile.add_argument(
        "--circuit", required=True, metavar="PATH", help="The CircuitSpec JSON.",
    )
    draw_compile.add_argument(
        "--presentation", required=True, metavar="PATH",
        help="The PresentationSpec JSON (the grammar to draw the circuit in).",
    )
    draw_compile.add_argument(
        "--profiles", required=True, metavar="PATH",
        help=(
            "The symbol library: `{\"profiles\": [SymbolProfile, …]}`, a bare list, "
            "or a symbolRef -> SymbolProfile mapping. Every symbol the circuit "
            "cites must be in it, with the geometry the layout is drawn against."
        ),
    )
    draw_compile.add_argument(
        "--page-box", default=None, metavar="X0,Y0,X1,Y1",
        help=(
            "The sheet the drawing must fit in, in canvas units. Given, the "
            "drawing is anchored at that page's own top-left corner, so the "
            "plan's coordinates are canvas coordinates a landing can use."
        ),
    )
    draw_compile.add_argument(
        "--out", dest="out_path", default=None, metavar="DIR",
        help="Where the previews go (default: outputs/054_drawcompile).",
    )
    draw_compile.add_argument(
        "--json", dest="json_path", metavar="PATH", help="Write the machine-readable result."
    )
    draw_compile.add_argument(
        "--intent", default="", metavar="PATH",
        help=(
            "The DesignIntent contract the grammar reads (095 A4 / 090 A1) — today "
            "the branch order of a `power-entry` drawing and the core of an "
            "`ic-periphery` one: a `decisions[]` entry that says which branch "
            "clamps the rail places it nearest the inlet, and a `blocks[]` entry "
            "whose parts name exactly one multi-pin part of the drawing says which "
            "part it is arranged around, so the fact is stated once for the review "
            "and the drawing alike. Explicit "
            "path only: this command compiles before anything names a project, so "
            "the user-level default (`~/.boardwise/design-intent/<uuid>.json`) has "
            "no uuid to be found from. `PresentationSpec.modules[].branchOrder` "
            "still outranks it, and the two disagreeing is a refusal naming both."
        ),
    )

    draw_plan = draw_sub.add_parser(
        "plan",
        help="Offline (or page-bound): one candidate -> the ChangePlan a human authorises.",
        description=(
            "Turn candidate N of a compiled drawing into a `draw-module` "
            "ChangePlan: every part with its recipe, its library symbol and its "
            "pose, every wire, every rail flag, the netlist the finished page must "
            "show, and the guards (both spec digests, the layout digest, the "
            "library geometry table, the page and its primitive census). With "
            "--page (or --project) the designators come from the page *and* the "
            "project export (036b), the census is recorded and the project's "
            "findings become the baseline. Exit 0 planned / 5 refused / 3 the "
            "daemon is unreachable for the live legs."
        ),
    )
    draw_plan.add_argument(
        "--circuit", required=True, metavar="PATH", help="The CircuitSpec JSON.",
    )
    draw_plan.add_argument(
        "--presentation", required=True, metavar="PATH", help="The PresentationSpec JSON.",
    )
    draw_plan.add_argument(
        "--profiles", required=True, metavar="PATH", help="The symbol library JSON.",
    )
    draw_plan.add_argument(
        "--candidate", type=int, default=0, metavar="N",
        help="Which compiled candidate to land (default: 0, the ranked leader).",
    )
    draw_plan.add_argument(
        "--lcsc", action="append", default=None, metavar="R1=C25744",
        help=(
            "The LCSC number of a part the circuit spec does not carry one for. "
            "Repeatable. Without it (and without the spec's own `lcsc`) the plan "
            "is refused naming the parts: a compiled drawing places library "
            "devices, and an unverified part is never placed silently."
        ),
    )
    draw_plan.add_argument(
        "--value", action="append", default=None, metavar="R2=4k7",
        help=(
            "The value of a part the circuit spec states none for. Repeatable. "
            "The value is what the read-back and the reviewer compare."
        ),
    )
    draw_plan.add_argument(
        "--page-box", default=None, metavar="X0,Y0,X1,Y1",
        help="The sheet to draw into (see `draw compile --page-box`).",
    )
    draw_plan.add_argument(
        "--keep-names", action="store_true",
        help=(
            "Land every part under its spec id instead of a freshly allocated "
            "number (121c: the engineer's `C10` stays `C10`, not a renumbered "
            "`C3`). Checked, not forced — a spec id already in the page/project "
            "pool refuses the plan by name, because the host would rename it "
            "mid-run (036b)."
        ),
    )
    draw_plan.add_argument(
        "--page", default=None, metavar="UUID",
        help=(
            "Bind the plan to a page: its census, its designator pool (with the "
            "project export's) and its findings are read live and recorded."
        ),
    )
    draw_plan.add_argument(
        "-o", "--out", dest="out_path", default=None, metavar="PATH",
        help="Write the ChangePlan JSON here (default: print it to stdout).",
    )
    draw_plan.add_argument(
        "--json", dest="json_path", metavar="PATH", help="Write the machine-readable result."
    )
    draw_plan.add_argument(
        "--intent", default="", metavar="PATH",
        help=(
            "The DesignIntent contract the grammar reads (095 A4) — see "
            "`draw compile --intent`. It travels into the compilation (the layout "
            "this plan lands was drawn with it) and, since 094, into the findings "
            "baseline the plan records for a bound page."
        ),
    )

    draw_apply = draw_sub.add_parser(
        "apply",
        help="On the live page: guard, land the drawing, read it back, save, render.",
        description=(
            "Land one `draw-module` plan: the guards first (both spec digests, the "
            "layout digest, the library geometry table, the page's identity and its "
            "primitive census) with nothing written if any of them fails; then the "
            "plan's own postconditions read on the page (satisfied = "
            "already_applied, zero writes); then the parts, a pin read-back against "
            "the plan's expected offsets *before* any wire, the wires and the rail "
            "flags; then both verification legs (the editor's own netlist and the "
            "canvas), the range on a fresh export and the findings' one-way rule "
            "graded by severity (an ERROR always stops the save, a WARN unless "
            "--force, an INFO never); "
            "then the save and the render. Exit 0 applied (or already applied) / 2 "
            "the promised effect is not there / 3 the state cannot be stated or the "
            "read-back disagrees / 4 a guard refused / 5 the plan is unusable."
        ),
    )
    draw_apply.add_argument("plan", help="The ChangePlan JSON `draw plan` wrote.")
    draw_apply.add_argument(
        "--page", default=None, metavar="UUID",
        help=(
            "The page to land on, when the plan is not bound to one. Required for a "
            "repeat run (`already_applied`) unless the plan carries its page."
        ),
    )
    draw_apply.add_argument(
        "--new-page", action="store_true",
        help=(
            "Create a page for this drawing (`sch.doc.new`, a `create` action), when "
            "the plan is not bound to one and `--page` is not given. Refused (exit 5) "
            "when either is — a run cannot both land on a settled page and create one, "
            "and the flag is never ignored. The host ignores the name (pit 24), so the "
            "page's uuid is the identity and it is confirmed against the listing "
            "afterwards."
        ),
    )
    draw_apply.add_argument(
        "--page-name", default=None, metavar="NAME",
        help=(
            "The name handed to `sch.doc.new` (cosmetic: the host ignores it). Read "
            "only where a page is created; a run that creates none says so."
        ),
    )
    draw_apply.add_argument(
        "--expect-census", default=None, metavar="SHA256",
        help=(
            "The page census this run must find before it writes — the digest a "
            "previous run's report quoted. This is 054's C5 guard for a plan built "
            "offline: a page somebody changed by hand then refuses (exit 4, zero "
            "writes) instead of being drawn over."
        ),
    )
    for flag, text in (
        ("--circuit", "The CircuitSpec JSON to re-digest for the stale guard."),
        ("--presentation", "The PresentationSpec JSON to re-digest for the stale guard."),
        ("--profiles", "The symbol library, for the library-geometry guard (C6)."),
        ("--layout", "The LayoutPlan JSON to re-digest for the layout guard."),
    ):
        draw_apply.add_argument(flag, default=None, metavar="PATH", help=text)
    draw_apply.add_argument(
        "--keep-names", action="store_true",
        help=(
            "A page document only: keep every part's spec id as its designator "
            "when the plan is built at apply time (see `draw plan --keep-names`). "
            "A `draw-module` plan already carries the designators it was built "
            "with, so this flag does nothing on that route."
        ),
    )
    draw_apply.add_argument(
        "--render", default=None, metavar="PATH",
        help=(
            "Where to write the acceptance image — an `export.render` document render "
            "(PNG). A viewport screenshot is NOT evidence (cached frames)."
        ),
    )
    draw_apply.add_argument(
        "--out", dest="out_path", default=None, metavar="DIR",
        help="Where the render goes when --render is not given (default: outputs/054_apply).",
    )
    draw_apply.add_argument(
        "--json", dest="json_path", metavar="PATH", help="Write the machine-readable result."
    )
    draw_apply.add_argument("--force", action="store_true", help=force_help)
    draw_apply.add_argument(
        "--page-box", default=None, metavar="X0,Y0,X1,Y1",
        help=(
            "The sheet the drawing is landing on, in canvas units — the override "
            "for a page whose own attributes could not be read back (533: the "
            "landing reads them off the live page first and only falls back to "
            "this). An island-page plan is refused without one of the two."
        ),
    )
    draw_apply.add_argument(
        "--project", default=None, metavar="NAME_OR_UUID",
        help="Which editor window to write to (023 routing hint; the daemon will not guess).",
    )
    draw_apply.add_argument(
        "--instance", default=None, metavar="INSTANCE_ID",
        help="The same choice by window key, for a window that cannot name a project.",
    )
    draw_apply.add_argument(
        "--port", type=int, default=None, help="Daemon port (default: 61190).",
    )
    draw_plan.add_argument(
        "--project", default=None, metavar="NAME_OR_UUID",
        help="Which editor window to read the page, pool and findings from.",
    )
    draw_plan.add_argument(
        "--instance", default=None, metavar="INSTANCE_ID",
        help="The same choice by window key.",
    )
    draw_plan.add_argument(
        "--port", type=int, default=None, help="Daemon port (default: 61190).",
    )

    # ---- 057 sec.5: the explicit clean-up ---------------------------------
    draw_discard = draw_sub.add_parser(
        "discard",
        help="On the live page: delete exactly one plan's drawing, identity-checked.",
        description=(
            "Take one landed drawing back off its page (057 G5): the plan's own "
            "primitives and nothing else. Every part is identified by designator, "
            "position and value before anything is deleted, every flag by net and "
            "point, every wire by net and by all of its points lying on the plan's "
            "wiring — one mismatch refuses the whole batch (exit 4, nothing "
            "deleted). Lines go first, then flags, then parts; the page is read back "
            "and everything outside the plan must be unchanged. A second run finds "
            "nothing and says so (exit 0). A page document is accepted with "
            "--circuit/--presentation/--profiles (its parts are then found by "
            "position). Exit 0 discarded or nothing to discard / 2 a delete refused "
            "or the read-back disagrees / 3 state unknown (never retried) / 4 "
            "identity mismatch or guard refused / 5 unusable input."
        ),
    )
    draw_discard.add_argument(
        "plan", help="The draw-module plan that was applied, or the page document.",
    )
    draw_discard.add_argument(
        "--page", default=None, metavar="UUID",
        help="The page the drawing is on (required when the plan is not bound to one).",
    )
    for flag, text in (
        ("--circuit", "Page document only: the CircuitSpec (values and recipes)."),
        ("--presentation", "Page document only: the PresentationSpec."),
        ("--profiles", "Page document only: the symbol library."),
    ):
        draw_discard.add_argument(flag, default=None, metavar="PATH", help=text)
    draw_discard.add_argument(
        "--save", action="store_true",
        help="Save the page after a verified clean-up (default: leave it unsaved).",
    )
    draw_discard.add_argument(
        "--json", dest="json_path", metavar="PATH", help="Write the machine-readable result."
    )
    draw_discard.add_argument(
        "--project", default=None, metavar="NAME_OR_UUID",
        help="Which editor window to clean (023 routing hint; the daemon will not guess).",
    )
    draw_discard.add_argument(
        "--instance", default=None, metavar="INSTANCE_ID",
        help="The same choice by window key.",
    )
    draw_discard.add_argument(
        "--port", type=int, default=None, help="Daemon port (default: 61190).",
    )

    # ---- 111: the page lint (read-only; live snapshot or a captured dump) --
    draw_lint = draw_sub.add_parser(
        "lint",
        help=(
            "Read-only readability lint of one page: nine geometric predicates "
            "(text-on-wire, text-on-text, text-on-part, wire-through-part, "
            "duplicate-annotation, crossings, label-wire-clearance, flag "
            "orientation, board fill), findings by severity (task 111)."
        ),
        description=(
            "The machine gate for the defects 110's re-review caught by eye: "
            "a wire printed through a label, a value stacked on a part, a pin "
            "crossed mid-span — all purely geometric, all judgeable from one "
            "read-only page snapshot. The snapshot is the page's `sch.geometry` "
            "plus the editor's own SVG render of the same page (the render is "
            "where the text geometry lives: the host exposes no text-extent "
            "read, so every text box is estimated from the render's anchors "
            "and marked `estimate` in the findings). Default reads the live "
            "page (`--page` focuses it first, exactly like `draw apply`'s "
            "guard); `--snapshot` + `--render` replay a captured pair with no "
            "daemon at all. Exit 0 no ERROR (INFO/WARN reported) / 1 ERROR "
            "findings / 2 bad input / 3 the page's state cannot be stated."
        ),
    )
    draw_lint.add_argument(
        "--page", default=None, metavar="UUID",
        help=(
            "The page to lint (default: the focused page). Reads only: "
            "doc.open + sch.geometry + export.render format=svg — no page "
            "content is written. `doc.open` does move the editor's tab, so the "
            "focus is re-read to confirm it really moved (a page that would not "
            "open is refused, exit 3) and put back where it was before the run."
        ),
    )
    draw_lint.add_argument(
        "--snapshot", default=None, metavar="PATH",
        help=(
            "A captured `sch.geometry` dump to lint instead of the live page "
            "(offline replay; with --render there is no daemon contact)."
        ),
    )
    draw_lint.add_argument(
        "--render", default=None, metavar="PATH",
        help=(
            "The captured SVG render of the same page (the text-geometry "
            "sidecar for --snapshot; without it the text predicates answer "
            "'unreadable' and only wire/flag geometry is judged)."
        ),
    )
    draw_lint.add_argument(
        "--bodies", default=None, metavar="PATH",
        help=(
            "Per-part measured body boxes (JSON: primitiveId → [minX, minY, "
            "maxX, maxY], from `sch.geometry --params {\"bboxIds\":[id]}`). "
            "Without them L3/L4's body half answers 'unreadable' — the host "
            "gives no body extent in the page dump."
        ),
    )
    draw_lint.add_argument(
        "--json", dest="json_path", metavar="PATH",
        help="Write the machine-readable findings report here.",
    )
    draw_lint.add_argument(
        "--project", default=None, metavar="NAME_OR_UUID",
        help="Which editor window to read (023 routing hint; the daemon will not guess).",
    )
    draw_lint.add_argument(
        "--instance", default=None, metavar="INSTANCE_ID",
        help="The same choice by window key.",
    )
    draw_lint.add_argument(
        "--port", type=int, default=None, help="Daemon port (default: 61190).",
    )

    # ---- 109 A4: the intent proposer (offline, no editor) ------------------
    draw_propose = draw_sub.add_parser(
        "propose",
        help=(
            "Offline: one DesignIntent contract -> one PresentationSpec draft "
            "(module list + flow + roles, 109)."
        ),
        description=(
            "The proposer (109 A4): it reads the contract **once** and writes down a "
            "whole draft of the presentation — the module list from `blocks[]` "
            "(id/parts/kind), the flow from the nets the blocks share, the branch "
            "order from the contract's own clamping claims — instead of making every "
            "grammar read the contract one clause at a time. The draft goes through "
            "the **same** closed schema as a hand-written spec (`PresentationSpec`), "
            "so the compiler still judges it: the proposer writes, it does not decide "
            "correctness. Nothing is guessed silently — an unmapped kind, a core two "
            "sources disagree about and a flow direction no role table entry decides "
            "are left empty and **named** in the report (R3). Exit 0 a draft with at "
            "least one module / 2 an input could not be read / 5 nothing could be "
            "proposed."
        ),
    )
    draw_propose.add_argument(
        "--intent", required=True, metavar="PATH",
        help=(
            "The DesignIntent contract to turn into a draft (090 A1: "
            "`design-intent-channel.md` §二). Explicit path only, exactly as `draw "
            "compile --intent` takes it: this command runs before anything names a "
            "project, so the user-level default (`<home>/design-intent/<uuid>.json`) "
            "has no uuid to be found from (095 §8③'s recorded limit)."
        ),
    )
    draw_propose.add_argument(
        "--circuit", default="", metavar="PATH",
        help=(
            "The CircuitSpec the draft is proposed against. The netlist decides the "
            "three facts a document cannot: which groups share a net (the flow's "
            "adjacency), which part is a group's core (pin counts) and which parts "
            "hang between the rails (the branch order). Without it those three stay "
            "empty and **the report says so** — they are never guessed."
        ),
    )
    draw_propose.add_argument(
        "-o", "--out", dest="out_path", default=None, metavar="PATH",
        help="Write the draft here (default: print it to stdout).",
    )
    draw_propose.add_argument(
        "--json", dest="json_path", metavar="PATH",
        help=(
            "Write the machine-readable proposal report: the two declared tables, "
            "one row per module with its notes, the flow edges and its undetermined "
            "candidates, what was read out of every contract element, and the list of "
            "everything that was not."
        ),
    )

    draw_islands = draw_sub.add_parser(
        "islands",
        help=(
            "Offline: propose the islands a spec has not declared, and write a "
            "judged proposal into it (530E)."
        ),
        description=(
            "The mixed-island path (`evidence/523/DESIGN.md` §5, 岳 2026-10-20: "
            "声明优先 + 未声明部分自动聚类 + AI 语义判断). `propose` reads a "
            "presentation spec — including one whose `islands[]` names only *some* "
            "of its parts, which `PresentationSpec` itself refuses to load — clusters "
            "the parts no island names (锚=≥3 脚器件, 挂共网或 <40, 离所有锚 >120 "
            "自成岛) and writes one work order per cluster; `apply` reads that "
            "document back with a `judgement[]` filled in, runs §5.5's six gates and "
            "writes the partition into `islands[]`. Nothing here reaches the editor, "
            "and `draw compile` never runs either half: it reads the `islands[]` "
            "that `apply` wrote and nothing else."
        ),
    )
    islands_sub = draw_islands.add_subparsers(dest="islands_command", required=True)

    islands_propose = islands_sub.add_parser(
        "propose",
        help="A presentation spec -> a proposal document (one work order per cluster).",
        description=(
            "Read the spec and the circuit, cluster every part no `islands[]` entry "
            "names, and write `<out>/islands-proposal.json`: the declared islands "
            "copied verbatim, then one work order per cluster holding only facts "
            "(library symbol, value, pin count), the cluster's own nets and "
            "classes, which nets cross to which neighbour, and the evidence the "
            "clustering acted on — **no coordinates**, because the question is "
            "semantic. Identical inputs give a byte-identical file. Exit 0 written "
            "(including the case where the declaration is already complete, which "
            "gives an empty proposal) / 2 an input could not be read / 5 the "
            "document states no parts at all."
        ),
    )
    islands_propose.add_argument(
        "--circuit", required=True, metavar="PATH",
        help="The CircuitSpec JSON: the netlist decides which parts share a net.",
    )
    islands_propose.add_argument(
        "--presentation", required=True, metavar="PATH",
        help=(
            "The PresentationSpec JSON. Read **leniently** here: the modules decide "
            "which parts this document has, and `islands[]` decides which of them "
            "are already placed. A document where some part sits in no island is "
            "exactly the input this command exists for, and `parse_islands`' "
            "\"every part in exactly one block\" invariant is not touched."
        ),
    )
    islands_propose.add_argument(
        "--profiles", required=True, metavar="PATH",
        help="The symbol library JSON (`draw compile --profiles`).",
    )
    islands_propose.add_argument(
        "--intent", default="", metavar="PATH",
        help=(
            "The DesignIntent the proposal is proposed against, if there is one. Its "
            "`blocks[]` ids are listed in the document so a judgement can see what "
            "would be updated rather than added."
        ),
    )
    islands_propose.add_argument(
        "-o", "--out", dest="out_path", default=None, metavar="PATH",
        help=(
            "Where the proposal goes (default: "
            f"{DEFAULT_ISLANDS_OUT}/islands-proposal.json)."
        ),
    )
    islands_propose.add_argument(
        "--json", dest="json_path", metavar="PATH",
        help="Write the machine-readable run report (the same facts, as a report).",
    )
    islands_propose.add_argument(
        "--print", dest="print_document", action="store_true",
        help="Print the proposal document to stdout as well as writing it.",
    )

    islands_apply = islands_sub.add_parser(
        "apply",
        help="A judged proposal -> the spec's `islands[]` and the intent's `blocks[]`.",
        description=(
            "Read the proposal back through §5.5's six gates — the id one, the "
            "verdict one, 件守恒 (the only judgement that refuses the whole "
            "document), the role vocabulary, the reason that must cite a name the "
            "work order printed, and the rule that nothing crosses a declared "
            "island — then write the declared islands **verbatim** plus the judged "
            "partition into `islands[]`, and one `blocks[]` entry per written "
            "cluster with `provenance = ai_asserted` into the design intent (which "
            "turns the whole intent document into a draft, on purpose). A judgement "
            "that fails a gate falls back to the geometric cluster it was given, "
            "never to a guess (§5.6). Exit 0 written / 2 an input could not be read "
            "/ 5 the judgement broke 件守恒 and nothing was written."
        ),
    )
    islands_apply.add_argument(
        "--proposal", required=True, metavar="PATH",
        help="The proposal document `draw islands propose` wrote, with `judgement[]`.",
    )
    islands_apply.add_argument(
        "--presentation", required=True, metavar="PATH",
        help=(
            "The PresentationSpec the proposal was made from. Its declared islands "
            "are copied into the output verbatim; by default the file is "
            "**rewritten** in the normal form (see --out-spec)."
        ),
    )
    islands_apply.add_argument(
        "--out-spec", dest="out_spec", default=None, metavar="PATH",
        help=(
            "Write the updated presentation spec here instead of rewriting "
            "`--presentation`. The document is written through "
            "`PresentationSpec`, so it comes out in the normal form (key order and "
            "formatting are the writer's, not the input file's)."
        ),
    )
    islands_apply.add_argument(
        "--intent", default="", metavar="PATH",
        help=(
            "The DesignIntent to merge the judgements into. Without it no intent is "
            "written, and the judgements live only in the proposal document — which "
            "is where they are read from next time anyway."
        ),
    )
    islands_apply.add_argument(
        "--out-intent", dest="out_intent", default=None, metavar="PATH",
        help="Write the updated intent here instead of rewriting `--intent`.",
    )
    islands_apply.add_argument(
        "--json", dest="json_path", metavar="PATH",
        help="Write the machine-readable apply report (one row per judgement).",
    )


def register_edit_parser(sub: Any, *, force_help: str) -> None:
    """Register edit plan/preview/apply without owning their handlers."""
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
            "canvas — one write, then a read-back, a save and a re-review. "
            "`--file` repairs one component's value (`param-value-mpn-match`, "
            "whose finding records a contradiction rather than a repair, so the "
            "direction is stated with it); the other kinds are reached by "
            "`--report` / `--insert` / `--move`, and a rule outside that table "
            "is refused by name. Exit 0 applied (or "
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
            "rule is unknown, is not repairable, has no violation there, the "
            "designator is ambiguous in the file, or the finding records a "
            "contradiction without a repair direction and the operator has "
            "stated none (--after / --direction, 052 §2.1) — a plan that "
            "cannot be acted on is worse than no plan."
        ),
    )
    edit_plan.add_argument(
        "--file", default=None,
        help=(
            "The .epro2 / .enet snapshot the plan is built against. Required by the "
            "`--file` and `--report` ways in (it is the snapshot's sha256 the plan "
            "carries); `--insert` builds from the live page and records the live "
            "export's own sha256 instead, so it refuses this flag rather than "
            "quietly ignoring it."
        ),
    )
    edit_plan.add_argument(
        "--rule", default=None,
        help=(
            "Rule id whose finding the plan repairs (e.g. param-value-mpn-match). "
            "Required except with `--insert`, which has no rule to name (036)."
        ),
    )
    edit_plan.add_argument(
        "--designator", default=None,
        help=(
            "The component to change, e.g. U3. Required except with `--insert "
            "divider`, which anchors on a net (036)."
        ),
    )
    edit_plan.add_argument(
        "--after", default=None,
        help=(
            "The value to write. Required for `param-value-mpn-match` unless the "
            "finding carries a suggestion of its own, which since 052 §2.1 it "
            "does not: that finding records a contradiction whose two repairs are "
            "fixing Value to the MPN's decoded value or swapping in a part that "
            "matches the design value, and the direction is the operator's to "
            "state (--after names the value of the first)."
        ),
    )
    edit_plan.add_argument(
        "--direction", choices=EDIT_DIRECTIONS, default=None,
        help=(
            "Which field the repair writes (052 §2.1), for the --file path "
            "only: `value` repairs the board's Value field and still needs "
            "--after <value>; `mpn` would repair the MPN/LCSC field, whose change "
            "kind this build does not have, so it is refused and says so. Neither "
            "flag leaves the direction unstated, and a plan is not built then — "
            "the MPN-decoded value is a candidate, not the answer (048)."
        ),
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
    # ---- 029-a: the same command, the other way in -----------------------
    edit_plan.add_argument(
        "--report", default=None, metavar="PATH",
        help=(
            "Build the plan from a checkup report.json instead of re-running the "
            "rule: the finding there carries the anchor, the supply pin, the net "
            "and the recipe (`decap-required-caps` findings only). Needs --lcsc "
            "and a live editor (the landing spot and the designator pool come "
            "from `sch.geometry`) — `edit plan --help`, §029-a."
        ),
    )
    edit_plan.add_argument(
        "--pin", default=None, metavar="NUMBER",
        help=(
            "Which pin's finding to repair (035 四轮). A report can carry several "
            "findings for one designator under one rule — the NC pin and the "
            "must_connect pin of the same part, one decap row per supply pin — and "
            "the selector will not pick one for you: with more than one match it "
            "refuses and names the pins. Required then, optional otherwise; when "
            "given it must match exactly one finding."
        ),
    )
    edit_plan.add_argument(
        "--lcsc", default=None, metavar="Cxxxxx",
        help=(
            "The orderable part number of the part to add (§二.2: an LCSC number "
            "from the facts shelf, or this). Without one the plan is refused: an "
            "unverified recipe is not something to place silently."
        ),
    )
    # ---- 036: the third way in — an explicit request, with no rule at all ----
    edit_plan.add_argument(
        "--insert", default=None, metavar="TEMPLATE",        help=(
            "Insert a whole sub-circuit instead of repairing a finding (036): "
            "`rc-lowpass` (series R with a shunt C to ground — it removes the wire "
            "that joins the anchor pin to its net, so it needs --pin) or `divider` "
            "(two resistors from a net to ground with the tap in the middle — it "
            "creates only, so it needs --net). Both need their values and LCSC "
            "numbers explicitly: there is no rule and no recipe lookup here, and an "
            "unverified part is never placed silently."
        ),
    )
    edit_plan.add_argument(
        "--net", default=None, metavar="NAME",
        help=(
            "For `--insert divider`: the net the divider taps (its own wire vertex "
            "is the anchor). Refused when it has no geometry on the page — a "
            "divider hanging off nothing is not a divider."
        ),
    )
    # ---- 037: the fourth way in — the caller names a group and a delta ------
    edit_plan.add_argument(
        "--move", action="store_true",
        help=(
            "Move a block of parts locally (037): `--designators R7,C9 --dx 100 --dy 0`. "
            "The delta must be a whole number of 5-unit grid steps, the group must be "
            "parts (not a sheet frame), and every wire attached to the group is taken off "
            "and drawn again — the host moves a part without dragging its wires "
            "(measured, `outputs/037_probe.txt`). Refuses anything it cannot move without "
            "guessing: a label or flag on a boundary wire, a T through a group pin, a "
            "target area that is occupied, an unknown or duplicated designator."
        ),
    )
    edit_plan.add_argument(
        "--designators", default=None, metavar="R7,C9",
        help="For `--move`: the parts to move together, comma-separated (≥1).",
    )
    edit_plan.add_argument(
        "--dx", default=None, metavar="UNITS",
        help="For `--move`: the horizontal delta, in canvas units (a multiple of 5).",
    )
    edit_plan.add_argument(
        "--dy", default=None, metavar="UNITS",
        help="For `--move`: the vertical delta, in canvas units (a multiple of 5).",
    )
    for flag, text in (
        ("--r", "For `--insert rc-lowpass`: the series resistor's value (e.g. 1k)."),
        ("--r-lcsc", "For `--insert rc-lowpass`: the series resistor's LCSC number."),
        ("--c", "For `--insert rc-lowpass`: the shunt capacitor's value (e.g. 1n)."),
        ("--c-lcsc", "For `--insert rc-lowpass`: the shunt capacitor's LCSC number."),
        ("--r1", "For `--insert divider`: the upper resistor's value."),
        ("--r1-lcsc", "For `--insert divider`: the upper resistor's LCSC number."),
        ("--r2", "For `--insert divider`: the lower resistor's value."),
        ("--r2-lcsc", "For `--insert divider`: the lower resistor's LCSC number."),
    ):
        edit_plan.add_argument(flag, default=None, metavar="VALUE", help=text)
    edit_plan.add_argument(
        "--project", default=None, metavar="NAME_OR_UUID",
        help="Which editor window to read the geometry from (023 routing hint).",
    )
    edit_plan.add_argument(
        "--instance", default=None, metavar="INSTANCE_ID",
        help="The same choice by window key, for a window that cannot name a project.",
    )
    edit_plan.add_argument(
        "--port", type=int, default=None, help="Daemon port (default 61190).",
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
    edit_preview.add_argument(
        "--project", default=None, metavar="NAME_OR_UUID",
        help="Which editor window to read from (023 routing hint; add-component plans only).",
    )
    edit_preview.add_argument(
        "--instance", default=None, metavar="INSTANCE_ID",
        help="The same choice by window key.",
    )
    edit_preview.add_argument(
        "--port", type=int, default=None, help="Daemon port (default 61190).",
    )

    edit_apply = edit_sub.add_parser(
        "apply",
        help="On the live canvas: re-check, write once, read back, save, re-review.",
        description=(
            "The four protections, in order: re-read the page and refuse a stale "
            "snapshot; write exactly one key on exactly one primitive; verify "
            "with the action's own read-back **and** an independent geometry "
            "read; and treat a timeout or a dropped connection as unknown — read "
            "the page back and never retry. Then `sch.doc.save` and a re-review: "
            "for `add-component` the live project is re-exported and the rule re-run "
            "(029-d §②), for `component-value` the snapshot `--file` is re-read. A "
            "repeated run recognises the work is already done and writes nothing "
            "(exit 0, already_applied)."
        ),
    )
    edit_apply.add_argument("plan", help="The ChangePlan JSON `edit plan` wrote.")
    edit_apply.add_argument(
        "--file", default=None,
        help=(
            "The snapshot to re-review after the save (`component-value`: the file "
            "the editor rewrites; an `add-component` apply re-exports the live "
            "project instead and falls back to this when that cannot answer). "
            "Without it the re-review is reported as unknown — never claimed."
        ),
    )
    edit_apply.add_argument(
        "--json", dest="json_path", metavar="PATH", help="Write the machine-readable result."
    )
    edit_apply.add_argument("--force", action="store_true", help=force_help)
    edit_apply.add_argument(
        "--view", choices=("schematic", "pcb"), default="schematic",
        help="Which model of a .epro2 to re-parse (default: schematic).",
    )
    edit_apply.add_argument(
        "--port", type=int, default=None, help="Daemon port (default 61190)."
    )
    edit_apply.add_argument(
        "--project", default=None, metavar="NAME_OR_UUID",
        help=(
            "Which editor window to write to (023 routing hint). Needed whenever "
            "several windows are online: the daemon refuses to guess."
        ),
    )
    edit_apply.add_argument(
        "--instance", default=None, metavar="INSTANCE_ID",
        help="The same choice by window key, for a window that cannot name a project.",
    )

def register_layout_lint_parser(sub: Any) -> None:
    """Register the offline layout-lint command (not draw lint)."""
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

def register_validate_parser(sub: Any) -> None:
    """Register the draw-domain board-spec validation command."""
    from ..core.portmeta import default_port_meta_path

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
        "--port-meta", default=default_port_meta_path(),
        help=(
            "Port-metadata sidecar saying what each port is electrically "
            "(default: %(default)s). Voltage, direction and IO level are "
            "declarations, so they live beside the blocks rather than inside "
            "them — `--recut` reproduces the block files byte for byte. Without "
            "it every gate that needs those fields answers \"cannot tell\"."
        ),
    )
    validate.add_argument(
        "--root", default=None,
        help="Directory declared input paths are read relative to (default: the "
        "directory the spec itself lives in).",
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

def register_pintable_parser(sub: Any) -> None:
    """Register the draw-domain firmware pin-table check."""
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

def dispatch_draw(
    args: argparse.Namespace,
    handlers: Mapping[str, Callable[[argparse.Namespace], int]],
    legacy_handler: Callable[[argparse.Namespace], int],
) -> int:
    """Resolve the old handler registry at call time; never bind a second copy."""
    command = getattr(args, "draw_command", None)
    if command:
        return handlers[command](args)
    return legacy_handler(args)



def dispatch_edit(
    args: argparse.Namespace,
    handlers: Mapping[str, Callable[[argparse.Namespace], int]],
) -> int:
    """Resolve edit plan/preview/apply through the historical live registry."""
    return handlers[args.edit_command](args)


def dispatch_draw_utility(
    args: argparse.Namespace,
    handler: Callable[[argparse.Namespace], int],
) -> int:
    """Resolve a direct draw-domain handler at call time (lint / validate)."""
    return handler(args)



def dispatch_pintable(
    args: argparse.Namespace,
    handlers: Mapping[str, Callable[[argparse.Namespace], int]],
) -> int:
    """Resolve the pin-table check through its historical live registry."""
    return handlers[args.pintable_command](args)
