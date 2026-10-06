"""Where the files boardwise *ships* are found — from a checkout or from an exe.

Two states, one API (028 batch 3a):

* **running from a checkout** — this file lives at ``src/boardwise/resources.py``,
  so the repo root is two parents up and the resources are exactly the ones the
  developer just built (``connector/dist/index.js``, ``connector/extension.json``,
  ``.kimi-code/skills/boardwise/SKILL.md``, ``blocklib/parts.json``,
  ``blocklib/blocks.portmeta.json``).
* **running from a frozen PyInstaller exe** — the same files are unpacked under
  ``sys._MEIPASS/resources/`` by the spec's ``--add-data`` entries, so the exe
  carries its own connector bundle, its own SKILL.md, its own curated shelf and
  its own port-metadata sidecar, and needs neither a checkout nor a copy of the
  repo beside it.

Why this module exists at all: ``update-connector`` used to resolve its default
bundle with ``Path(__file__).resolve().parents[2]``. That is right from a
checkout and wrong from an exe, where it points at
``…\\_MEIxxxxxx\\connector\\dist\\index.js`` and fails the existence check — which
would have made the single exe useless for exactly the person the release is for
(a friend with neither Python nor the repo). The rule the two states share is
"resources live together, relative to one root"; only the root differs.

Nothing here reads file *contents*: a caller that needs bytes asks for the path
and does its own error handling, because "the resource is missing" is a
different message in every caller (`--version` says "unknown", `update-connector`
says "run npm run build", `install-skill` says which path it looked at).

The frozen layout mirrors the repo tree under ``resources/`` — the same relative
parts in both states (``connector/dist/index.js``,
``connector/extension.json``, ``.kimi-code/skills/boardwise/SKILL.md``,
``blocklib/parts.json``, ``blocklib/blocks.portmeta.json``), so the spec's
``--add-data`` lines and the two states' expectations cannot drift apart in the
way a per-resource special case would eventually drift.

Two resources have a *second* consumer shape: they are read as the default of a
path that used to be spelled relative to the working directory. A frozen process
has no working directory that means anything, so
``rules.facts.default_library_path`` resolves the shelf through
:func:`parts_library` and ``core.portmeta.default_port_meta_path`` resolves the
sidecar through :func:`portmeta_sidecar` — one answer each to "which shelf" and
"which sidecar", the same way the connector bundle has one answer for "which
bundle". Both keep the repo-relative spelling from a checkout, so only the frozen
answer changes.
"""

from __future__ import annotations

import sys
from pathlib import Path

#: Where the frozen bundle keeps everything it embeds. Named rather than inlined
#: because the spec and the tests both have to agree with it, and a silent
#: disagreement shows up as "resource missing" on a friend's machine.
FROZEN_SUBDIR = "resources"

#: The repo-relative homes of each resource, under the root.
_BUNDLE_PARTS = ("connector", "dist", "index.js")
_EXTENSION_PARTS = ("connector", "extension.json")
_SKILL_PARTS = (".kimi-code", "skills", "boardwise", "SKILL.md")
_PARTS_LIBRARY_PARTS = ("blocklib", "parts.json")
_PORT_META_PARTS = ("blocklib", "blocks.portmeta.json")
_DRC_RULESET_REFERENCE_PARTS = ("blocklib", "drc_ruleset_reference.json")


def is_frozen() -> bool:
    """Is this process a PyInstaller bundle?

    ``sys.frozen`` is set by PyInstaller's bootstrap before any user code runs;
    that attribute is the documented test. ``getattr`` rather than a direct read
    because this module has to import cleanly everywhere else (pytest, the
    editable install, a plain ``python -m boardwise.cli``).
    """
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """The directory the resource paths are built from, in whichever state.

    Raises :class:`RuntimeError` when a frozen process cannot say where its
    bundle was unpacked: that is a broken bootstrap, not a missing file, and
    guessing a path here would be worse than saying so.
    """
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if not meipass:
            raise RuntimeError(
                "this process is frozen (sys.frozen is set) but sys._MEIPASS is "
                "missing, so the bundled resources cannot be located"
            )
        return Path(str(meipass)) / FROZEN_SUBDIR
    # src/boardwise/resources.py -> src/boardwise -> src -> repo root.
    return Path(__file__).resolve().parents[2]


def describe_state() -> str:
    """``"a frozen exe"`` / ``"a checkout"`` — for ``--version`` and diagnostics."""
    return "a frozen exe" if is_frozen() else "a checkout"


def connector_bundle() -> Path:
    """The connector bundle (``connector/dist/index.js``) this install would push."""
    return resource_root().joinpath(*_BUNDLE_PARTS)


def connector_extension_json() -> Path:
    """The connector manifest (``connector/extension.json``) — the version source."""
    return resource_root().joinpath(*_EXTENSION_PARTS)


def skill_md() -> Path:
    """The SKILL.md this install would write into the user-level skill directory."""
    return resource_root().joinpath(*_SKILL_PARTS)


def parts_library() -> Path:
    """The curated shelf (``blocklib/parts.json``) this install judges parts against.

    Read-only by nature: frozen, this path lives inside PyInstaller's extraction
    directory, which is deleted when the process exits. Curating a shelf writes
    to a file on disk, so the writing subcommands deliberately keep the
    repo-relative spelling (``rules.facts.DEFAULT_LIBRARY_PATH``) instead of
    resolving through here — a write into the extraction directory would report
    success and vanish.
    """
    return resource_root().joinpath(*_PARTS_LIBRARY_PARTS)


def portmeta_sidecar() -> Path:
    """The port-metadata sidecar (``blocklib/blocks.portmeta.json``) — task 047.

    The `draw` and `validate` commands read it as the default of ``--port-meta``;
    spelled relative to the working directory it was simply *missing* for a
    frozen exe started anywhere else, and the level / power-tree gates then
    answered "cannot tell" and refused the spec (045b §七 measured that in a
    clean directory). Read-only: both consumers only load it (nothing writes a
    sidecar through the CLI), so resolving it through the bundle is safe in a
    way it would not be for the shelf.
    """
    return resource_root().joinpath(*_PORT_META_PARTS)


def drc_ruleset_reference() -> Path:
    """The PCB DRC rule-set reference table (``blocklib/drc_ruleset_reference.json``).

    123: the ruler `engines/drc.py::ruleset_section` compares a board's own DRC
    rule set against. Read-only like :func:`portmeta_sidecar`, and resolved the
    same way, so a frozen exe carries its own table and a checkout uses the one
    the developer just edited.

    **A caller must treat "the file is not there" as a reportable fact.** This
    table is what makes the meta-audit mean anything; without it the section has
    no comparison to run, and "nothing was compared" must not reach a reader as
    "everything matched". So callers report the absence, never swallow it.
    """
    return resource_root().joinpath(*_DRC_RULESET_REFERENCE_PARTS)
