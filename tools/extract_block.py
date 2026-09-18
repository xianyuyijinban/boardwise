"""Cut block templates out of a golden EasyEDA page (task 008a, work item 2).

Two modes, both of them mechanical:

    # cut one block out of a board
    python tools/extract_block.py --golden tests/fixtures/ch340_golden.epro2 \
        --overrides tests/fixtures/ch340_golden.overrides.json \
        --name ch340_usb_input --description "USB-C input, CC pull-downs, VBUS decoupling" \
        --designators USB1,R24,R27,C4 --bbox 40,-240,230,-40 \
        --out blocklib/blocks/ch340_usb_input.json

    # re-derive committed templates from the board they name (deterministic;
    # this is what the round-trip test asserts)
    python tools/extract_block.py --recut blocklib/blocks/*.json \
        --golden tests/fixtures/ch340_golden.epro2 \
        --overrides tests/fixtures/ch340_golden.overrides.json

The tool exists so that "this template is a faithful extract of board X,
region Y" is reproducible rather than asserted. It never edits the golden —
corrections come from the sidecar and are folded in with their provenance.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from boardwise.core.blocks import BlockError  # noqa: E402
from boardwise.core.overrides import load_overrides  # noqa: E402
from boardwise.engines.cut import (  # noqa: E402
    CutError,
    extract_block,
    recut,
    write_block,
)


def _parse_bbox(text: str) -> tuple[float, float, float, float]:
    parts = [chunk.strip() for chunk in text.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("--bbox is x0,y0,x1,y1")
    try:
        x0, y0, x1, y1 = (float(chunk) for chunk in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--bbox is not four numbers: {text!r}") from exc
    if x0 > x1 or y0 > y1:
        raise argparse.ArgumentTypeError("--bbox must be (min x, min y, max x, max y)")
    return (x0, y0, x1, y1)


def _parse_designators(text: str) -> list[str]:
    return [chunk.strip() for chunk in text.split(",") if chunk.strip()]


def _parse_constraint(text: str) -> tuple[str, str]:
    ref, _, name = text.partition("=")
    if not ref or not name:
        raise argparse.ArgumentTypeError("--constraint is REF=constraint_name")
    return (ref.strip(), name.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="extract_block",
        description="Cut block templates (task 008a, work item 2).",
    )
    parser.add_argument("--golden", required=True, help="The .epro2 to cut from.")
    parser.add_argument(
        "--overrides",
        default=None,
        help=(
            "Golden-corrections sidecar (JSON). The fixture is evidence and is "
            "never edited; corrections are folded into the template's device "
            "bindings and parameter defaults with their provenance."
        ),
    )
    parser.add_argument(
        "--recut",
        nargs="+",
        metavar="TEMPLATE",
        help=(
            "Re-derive these committed templates from the golden file they name "
            "and overwrite them. Deterministic; no other arguments needed."
        ),
    )
    parser.add_argument("--name", help="Block name (single-cut mode).")
    parser.add_argument("--description", default="", help="One line of prose.")
    parser.add_argument(
        "--designators",
        type=_parse_designators,
        help="Comma-separated parts the block owns, e.g. USB1,R24,R27,C4.",
    )
    parser.add_argument(
        "--bbox",
        type=_parse_bbox,
        help="The designer's boundary, absolute file coordinates: x0,y0,x1,y1.",
    )
    parser.add_argument("--note", default="", help="Free-text provenance note.")
    parser.add_argument(
        "--constraint",
        action="append",
        type=_parse_constraint,
        default=[],
        metavar="REF=NAME",
        help=(
            "Force a parameter's constraint instead of the inferred one "
            "(repeatable), for values the inference refuses to classify."
        ),
    )
    parser.add_argument("--out", help="Where to write the template (single-cut mode).")
    return parser


def _cli(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    overrides = load_overrides(args.overrides) if args.overrides else None

    if args.recut:
        failures = 0
        for path in args.recut:
            try:
                from boardwise.core.blocks import load_block_template

                template = load_block_template(path)
                outcome = recut(args.golden, template, overrides=overrides)
                written = write_block(outcome, path)
            except (CutError, BlockError) as exc:
                print(f"extract_block: {path}: {exc}", file=sys.stderr)
                failures += 1
                continue
            print(f"= {template.name} -> {written}")
            for line in outcome.report:
                print(f"    {line}")
            for note in outcome.template.notes:
                print(f"    note: {note}")
        return 1 if failures else 0

    missing = [
        flag
        for flag, value in (("--name", args.name), ("--designators", args.designators), ("--bbox", args.bbox))
        if not value
    ]
    if missing:
        print(
            "extract_block: single-cut mode needs " + ", ".join(missing),
            file=sys.stderr,
        )
        return 2
    constraints = dict(args.constraint)
    try:
        outcome = extract_block(
            args.golden,
            name=args.name,
            description=args.description,
            designators=args.designators,
            bbox=args.bbox,
            note=args.note,
            overrides=overrides,
            constraints=constraints,
        )
    except (CutError, BlockError) as exc:
        print(f"extract_block: {exc}", file=sys.stderr)
        return 1
    for line in outcome.report:
        print(line)
    for note in outcome.template.notes:
        print(f"note: {note}")
    if args.out:
        print(f"written: {write_block(outcome, args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
