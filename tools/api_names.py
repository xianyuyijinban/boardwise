"""Extract a namespace's method names from the offline type package.

Why this exists
---------------
`sys.probe` used to answer "what does `sch_ManufactureData` expose?" by
*enumerating* the live object. On 2026-09-14 that crashed the whole probe run
on the real editor: the host hands out *exotic* objects whose
`getPrototypeOf`/`getOwnPropertyNames` throw, so enumeration is a measurement
that can fail on exactly the object you most want to measure.

The fix is to stop enumerating for the *expected* names. The type package
already declares them, and the declarations are pure text — reading them is
offline, complete, and cannot be broken by a hostile runtime object. This
script is that reader.

What it emits
-------------
For each requested namespace: the method names, plus the `ADD since EDA …`
line attached to each, plus the `@beta`/`@public` visibility markers. Those
annotations matter because the host's own answer is only meaningful against
them: a method declared `ADD since EDA v3.2.183` that answers `undefined` on a
3.2.186 host is a *rename or a removal*, not a version gap.

Usage
-----
    python tools/api_names.py sch_ManufactureData dmt_EditorControl
    python tools/api_names.py --json sch_ManufactureData > names.json

The output is deliberately stable and sorted — it is meant to be pasted into
`sys.probe`'s `checks` parameter and into `docs/api-survey.md`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TYPES = (
    Path(__file__).resolve().parents[1]
    / "connector"
    / "node_modules"
    / "@jlceda"
    / "pro-api-types"
    / "index.d.ts"
)

# `\tclass NAME {` — the package indents top-level declarations with one tab.
_CLASS_RE = re.compile(
    # `implements …` is optional in the source and present on the primitive
    # API classes (`class SCH_PrimitiveComponent implements ISCH_PrimitiveAPI`)
    # — without this clause the parser skipped every one of them, which is how
    # the F3 recon lost the seventh path until 2026-09-15.
    r"^\tclass\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+implements\s+[^{]+)?\s*\{"
)
# `public name(...)` or `public name?:` — a method or a data member.
_MEMBER_RE = re.compile(r"^\t\t(?:public\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(\??)\s*[:(]")
# `ADD since EDA v3.2.183 / EDA v4.1.23` (also seen as `添加于 EDA v…`).
_ADD_SINCE_RE = re.compile(r"ADD since\s+(EDA\s+v[0-9.]+)", re.IGNORECASE)
_BETA_RE = re.compile(r"@beta\b")
_INTERNAL_RE = re.compile(r"@internal\b")

# The `eda` class lists every namespace as `public NAME: TYPE;`.
_NS_DECL_RE = re.compile(r"^\t\tpublic\s+([a-z][A-Za-z0-9_]*)\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*;")


@dataclass
class Member:
    """One declared member of a namespace class."""

    name: str
    kind: str  # "method" | "property"
    since: str = ""
    beta: bool = False
    internal: bool = False

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"kind": self.kind}
        if self.since:
            out["since"] = self.since
        if self.beta:
            out["beta"] = True
        if self.internal:
            out["internal"] = True
        return out


@dataclass
class Namespace:
    """Everything the type package says about one namespace."""

    name: str
    type_name: str = ""
    members: dict[str, Member] = field(default_factory=dict)

    @property
    def methods(self) -> list[str]:
        return sorted(n for n, m in self.members.items() if m.kind == "method")

    def as_dict(self) -> dict[str, object]:
        return {
            "type": self.type_name,
            "methods": self.methods,
            "members": {n: m.as_dict() for n, m in sorted(self.members.items())},
        }


def _strip_comment(text: str) -> str:
    """Drop a trailing `// …` without touching `http://` inside strings.

    The declarations are machine-generated and terse, so a line-start check is
    enough; a full tokenizer would be more code than the problem deserves.
    """
    idx = text.find("//")
    return text[:idx] if idx >= 0 else text


def _is_comment(line: str) -> bool:
    """A line that is entirely inside a doc block / line comment.

    Comments must never reach the brace counter: these declarations embed
    `{@link https://…}` inside their prose, and `_strip_comment` (correctly)
    truncates at the `//`, leaving an orphan `{`. That orphan used to inflate
    the running depth by one *permanently*, so every class after it looked
    still-open and its members were folded into the wrong namespace — the
    symptom was `SYS_ClientUrl` reporting 544 members.
    """
    stripped = line.strip()
    return stripped.startswith("*") or stripped.startswith("/**") or stripped.startswith("/*")


def _brace_delta(line: str) -> int:
    """Net `{`-vs-`}` on one line, ignoring braces inside string literals.

    Needed because a class body must end at its own closing brace: without
    depth tracking the members of the *next* interface (or enum) get folded
    into the previous class — which is how this parser first reported
    `boardName`/`nets`/`wires` as `SCH_ManufactureData` methods. Those are
    members of `ISCH_WireInfo`, a completely different declaration.
    """
    if _is_comment(line):
        return 0
    depth = 0
    quote: str | None = None
    escaped = False
    for char in line:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in ("'", '"', "`"):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
    return depth


def parse_types(path: Path) -> tuple[dict[str, str], dict[str, Namespace]]:
    """Return (namespace -> class name, class name -> Namespace).

    A single forward pass: whenever a `class` line starts, subsequent
    indented members belong to it; the `public ns: TYPE;` block inside the
    `EDA` class supplies the namespace-to-type mapping. Doc comments are
    collected as we go so `ADD since` / `@beta` bind to the *next* member.
    """
    ns_to_type: dict[str, str] = {}
    classes: dict[str, Namespace] = {}
    current: Namespace | None = None
    body_depth = 0  # `{`-depth *relative to* the current class's opening brace
    base_depth = 0
    depth = 0
    doc: list[str] = []
    in_eda = False

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = _strip_comment(raw.rstrip())
        delta = _brace_delta(line)

        # Every declaration sits inside a single `declare global { … }` wrapper,
        # so the class body's *absolute* depth is never 1 — and inline object
        # types in signatures (`Promise<Array<{ a: string }>>`) push the
        # absolute number around. Only the depth *relative to the class's own
        # opening brace* is meaningful.
        if current is None:
            match = _CLASS_RE.match(line)
            if match:
                current = Namespace(name=match.group(1), type_name=match.group(1))
                classes[current.name] = current
                in_eda = current.name == "EDA"
                base_depth = depth
                body_depth = delta
                depth += delta
                doc.clear()
                continue
            depth += delta
            doc.clear()
            continue

        # A namespace alias line inside the `EDA` class body.
        if in_eda:
            match = _NS_DECL_RE.match(line)
            if match:
                ns_to_type[match.group(1)] = match.group(2)

        stripped = line.strip()
        if stripped.startswith("*") or stripped.startswith("/**"):
            doc.append(stripped)
        elif stripped and stripped != "*/":
            match = _MEMBER_RE.match(line)
            if match:
                name = match.group(1)
                kind = "property" if match.group(2) else "method"
                since = ""
                for entry in doc:
                    found = _ADD_SINCE_RE.search(entry)
                    if found:
                        since = found.group(1).replace("EDA ", "").strip()
                        break
                current.members[name] = Member(
                    name=name,
                    kind=kind,
                    since=since,
                    beta=any(_BETA_RE.search(e) for e in doc),
                    internal=any(_INTERNAL_RE.search(e) for e in doc),
                )
            doc.clear()

        depth += delta
        if depth <= base_depth:
            current = None
            in_eda = False
            doc.clear()

    return ns_to_type, classes


def resolve(ns_to_type: dict[str, str], classes: dict[str, Namespace], name: str) -> Namespace | None:
    """Look up a namespace by its `eda.*` name, falling back to a class name.

    Accepts both spellings so the tool works whether the caller thinks in
    `eda` terms (`sch_ManufactureData`) or type terms (`SCH_ManufactureData`).
    """
    if name in ns_to_type:
        cls = classes.get(ns_to_type[name])
        if cls is None:
            return Namespace(name=name, type_name=ns_to_type[name])
        return Namespace(name=name, type_name=cls.type_name, members=dict(cls.members))
    cls = classes.get(name)
    if cls is not None:
        return Namespace(name=name, type_name=cls.type_name, members=dict(cls.members))
    return None


# Why the roadmap cares about each namespace. Printed above its name list, so
# the generated file reads as a decision rather than a dump. A namespace with
# no note still gets its list — the note is commentary, not a gate.
NAMESPACE_NOTES: dict[str, str] = {
    "sch_ManufactureData": (
        "8.3 — the acceptance image. `getPngFile`/`getSvgFile` are declared\n"
        "  // `ADD since EDA v3.2.183`, yet the host (3.2.186) answers NOT_IMPLEMENTED\n"
        "  // for the render path; this is the check that separates a rename from an\n"
        "  // absence."
    ),
    "dmt_EditorControl": (
        "006c — `doc.open`: which tab is focused, and how to move focus. A page\n"
        "  // created by `sch.doc.new` anchors to the front tab, so this is the pair\n"
        "  // that makes \"draw into page X\" verifiable."
    ),
    "dmt_Schematic": (
        "006c — page creation. `createSchematic` returned empty on a blank project\n"
        "  // (measured), so `createSchematicPage` is the shape to verify."
    ),
    "dmt_Pcb": "The PCB half of the design model — the 001/002 readback line.",
    "sch_Document": (
        "`save` is the step that makes the netlist export reliable: an unsaved page\n"
        "  // has no netlist to hand back."
    ),
}


def emit_typescript(
    ns_to_type: dict[str, str], classes: dict[str, Namespace], namespaces: list[str]
) -> str:
    """Render the requested namespaces as a TypeScript module.

    This is how `connector/src/api-names.ts` is produced: the table is
    *generated from the type package*, never hand-typed, so it cannot drift
    without a regeneration showing the diff.
    """
    header = """/**
 * Candidate member names per namespace, read out of the offline type package.
 *
 * **Generated — do not edit by hand.** Regenerate with:
 *
 *     python tools/api_names.py --emit-ts connector/src/api-names.ts {names}
 *
 * Why a generated table instead of enumerating the live object: on
 * 2026-09-14 the on-machine probe died on *every* namespace with
 * "Cannot read properties of undefined (reading 'prototype')", because the
 * editor's extension host hands out *exotic* objects whose
 * `getOwnPropertyNames`/`getPrototypeOf` throw. Enumeration is therefore a
 * measurement that can fail on exactly the object under study.
 *
 * `typeof ns[name]` cannot fail that way: property access walks the prototype
 * chain as part of the language. So the stable path is
 *
 *     for each name the type package declares: typeof ns[name]
 *
 * and this module supplies "each name the type package declares" without
 * asking the running editor anything.
 *
 * A namespace missing here is not an error — the enumerate mode of
 * `sys.probe` still covers it. This table is the *complete declared surface*
 * for the namespaces the roadmap depends on.
 */

""".format(names=" ".join(namespaces))

    lines = ["export const PROBE_CHECKS: Record<string, string[]> = {"]
    for ns in namespaces:
        parsed = resolve(ns_to_type, classes, ns)
        note = NAMESPACE_NOTES.get(ns)
        if note:
            lines.append(f"  // {note}")
        else:
            lines.append(f"  // {parsed.type_name if parsed else '(not declared)'}")
        lines.append(f"  {ns}: [")
        for method in (parsed.methods if parsed else []):
            lines.append(f"    '{method}',")
        lines.append("  ],")
    lines.append("};")

    additions = [
        (ns, name, member.since)
        for ns in namespaces
        for name, member in sorted((resolve(ns_to_type, classes, ns) or Namespace(ns)).members.items())
        if member.since
    ]
    lines.append("")
    lines.append("/**")
    lines.append(" * Methods the type package marks `ADD since EDA v…` — the ones where an")
    lines.append(" * `undefined` answer is evidence rather than a surprise.") 
    lines.append(" */")
    lines.append("export const ADDED_SINCE: Record<string, Record<string, string>> = {")
    for ns in namespaces:
        entries = [(name, since) for n, name, since in additions if n == ns]
        if not entries:
            continue
        lines.append(f"  {ns}: {{")
        for name, since in entries:
            lines.append(f"    {name}: '{since}',")
        lines.append("  },")
    lines.append("};")
    lines.append("")
    return header + "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("namespaces", nargs="+", help="e.g. sch_ManufactureData dmt_Pcb")
    parser.add_argument("--types", type=Path, default=DEFAULT_TYPES, help="path to index.d.ts")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument(
        "--methods-only",
        action="store_true",
        help="print just the names, one per line — paste-ready for sys.probe checks",
    )
    parser.add_argument(
        "--emit-ts",
        type=Path,
        metavar="PATH",
        help="write a TypeScript module of PROBE_CHECKS (writes to PATH, or '-' for stdout)",
    )
    args = parser.parse_args(argv)

    if not args.types.exists():
        print(f"type package not found: {args.types}", file=sys.stderr)
        print("run `cd connector && npm install` first", file=sys.stderr)
        return 2

    ns_to_type, classes = parse_types(args.types)

    if args.emit_ts:
        text = emit_typescript(ns_to_type, classes, args.namespaces)
        if str(args.emit_ts) == "-":
            sys.stdout.write(text)
        else:
            args.emit_ts.write_text(text, encoding="utf-8")
            print(f"wrote {args.emit_ts} ({len(text)} bytes)")
        return 0

    if args.methods_only:
        for requested in args.namespaces:
            ns = resolve(ns_to_type, classes, requested)
            for method in (ns.methods if ns else []):
                print(method)
        return 0

    resolved: dict[str, Namespace | None] = {
        requested: resolve(ns_to_type, classes, requested) for requested in args.namespaces
    }

    if args.json:
        payload = {
            ns: (parsed.as_dict() if parsed else {"present": False})
            for ns, parsed in resolved.items()
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    missing = [ns for ns, parsed in resolved.items() if parsed is None]
    for ns, parsed in resolved.items():
        print(f"== {ns} ==")
        if parsed is None:
            print("  (not declared in the type package)")
            continue
        print(f"  type: {parsed.type_name}")
        methods = parsed.methods
        print(f"  methods ({len(methods)}):")
        for name in methods:
            member = parsed.members[name]
            marks = []
            if member.beta:
                marks.append("beta")
            if member.internal:
                marks.append("internal")
            if member.since:
                marks.append(f"ADD since {member.since}")
            suffix = f"   [{', '.join(marks)}]" if marks else ""
            print(f"    {name}{suffix}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
