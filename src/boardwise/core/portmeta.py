"""The port-metadata sidecar (task 008c, item 4).

What a port *is* electrically — the side of the rail it sits on, the voltage it
provides or asks for, the IO domain its signals speak — is a **declaration**,
not something the board's geometry says. The four CH340 blocks are cut out of a
golden page and ``tests/test_cut.py`` asserts the file is byte-for-byte what
re-running the cut produces; writing those declarations into the file would put
the two in conflict, and the way this project has settled that twice already
(006b golden overrides, 008b part corrections) is the same:

    the artifact stays reproducible from **sources + sidecar**.

So the metadata lives here, next to the blocks, and is folded in **at load
time** by whoever needs it — :func:`load_block_template`'s ``port_meta``
argument. Nothing else changes: a template read without the sidecar is the
template the board produced, and the three fields default to empty, which the
level and power-tree gates read as "cannot tell" and *not* as agreement.

The sidecar is merged into the parsed JSON **before** validation, so the class
rules (``direction`` only on power/ground, ``voltage`` only on power, ``level``
only on a signal) are enforced in exactly one place — the template reader —
with the sidecar named in the message.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PORT_META_KIND = "boardwise-block-port-metadata"
PORT_META_VERSION = 1

#: The three fields, kept here rather than written out three times.
PORT_META_FIELDS = ("direction", "voltage", "level")

_SECTION_KEYS = ("ports", "notes", "provenance")
_TOP_KEYS = ("kind", "version", "blocks", "notes")


class PortMetaError(ValueError):
    """The sidecar is malformed. Always names where."""


@dataclass
class TemplatePortMeta:
    """One block's declarations: per-port fields, notes, and where they came from."""

    name: str
    ports: dict[str, dict[str, str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    provenance: str = ""


@dataclass
class PortMeta:
    """The whole sidecar, keyed by template **name**."""

    blocks: dict[str, TemplatePortMeta] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    path: str = ""

    def for_template(self, name: str) -> TemplatePortMeta | None:
        return self.blocks.get(name)

    @property
    def is_empty(self) -> bool:
        return not self.blocks

    def merge(self, raw: dict[str, Any]) -> bool:
        """Fold this sidecar into a parsed template dict, in place.

        Returns whether anything was applied. Ports the template does not have,
        and fields that are already set in the file, are refused rather than
        silently winning: two sources for one fact is the thing this whole task
        book is trying to make impossible.
        """
        entry = self.for_template(str(raw.get("name") or ""))
        if entry is None:
            return False
        ports = raw.get("interface")
        if not isinstance(ports, list):
            raise PortMetaError(
                f"{self.path}: {entry.name}: the template has no interface to "
                "annotate"
            )
        by_role = {
            port.get("role"): port for port in ports if isinstance(port, dict)
        }
        for role, fields in entry.ports.items():
            port = by_role.get(role)
            if port is None:
                raise PortMetaError(
                    f"{self.path}: {entry.name} has no port {role!r}; it has "
                    f"{', '.join(sorted(str(r) for r in by_role)) or '(none)'}"
                )
            for key, value in fields.items():
                if key not in PORT_META_FIELDS:
                    raise PortMetaError(
                        f"{self.path}: {entry.name}.{role}.{key}: not one of "
                        f"{', '.join(PORT_META_FIELDS)}"
                    )
                if key in port and port[key]:
                    raise PortMetaError(
                        f"{self.path}: {entry.name}.{role}: {key} is already "
                        f"{port[key]!r} in the template file, so the sidecar would "
                        "be a second answer to one question"
                    )
                port[key] = value
        if entry.notes:
            raw.setdefault("notes", [])
            if not isinstance(raw["notes"], list):
                raise PortMetaError(f"{self.path}: {entry.name}: `notes` is not a list")
            raw["notes"].extend(
                f"{note} [{entry.provenance}]" if entry.provenance else note
                for note in entry.notes
            )
        return True


def port_meta_from_json(raw: Any, *, where: str = "<port-meta>") -> PortMeta:
    """Validate one parsed sidecar."""
    if not isinstance(raw, dict):
        raise PortMetaError(f"{where}: expected a JSON object")
    kind = raw.get("kind")
    if kind != PORT_META_KIND:
        raise PortMetaError(f"{where}.kind: expected {PORT_META_KIND!r}, got {kind!r}")
    if raw.get("version") != PORT_META_VERSION:
        raise PortMetaError(
            f"{where}.version: expected {PORT_META_VERSION}, got {raw.get('version')!r}"
        )
    unknown = sorted(set(raw) - set(_TOP_KEYS))
    if unknown:
        raise PortMetaError(
            f"{where}: unknown key(s) {', '.join(unknown)}; allowed: "
            f"{', '.join(_TOP_KEYS)}"
        )

    blocks: dict[str, TemplatePortMeta] = {}
    raw_blocks = raw.get("blocks") or {}
    if not isinstance(raw_blocks, dict):
        raise PortMetaError(f"{where}.blocks: expected an object keyed by template name")
    for name, body in raw_blocks.items():
        spot = f"{where}.blocks[{name}]"
        if not isinstance(body, dict):
            raise PortMetaError(f"{spot}: expected an object")
        unknown = sorted(set(body) - set(_SECTION_KEYS))
        if unknown:
            raise PortMetaError(
                f"{spot}: unknown key(s) {', '.join(unknown)}; allowed: "
                f"{', '.join(_SECTION_KEYS)}"
            )
        ports: dict[str, dict[str, str]] = {}
        raw_ports = body.get("ports") or {}
        if not isinstance(raw_ports, dict):
            raise PortMetaError(f"{spot}.ports: expected an object keyed by port role")
        for role, fields in raw_ports.items():
            if not isinstance(fields, dict):
                raise PortMetaError(f"{spot}.ports[{role}]: expected an object")
            for key, value in fields.items():
                if key not in PORT_META_FIELDS:
                    raise PortMetaError(
                        f"{spot}.ports[{role}].{key}: expected one of "
                        f"{', '.join(PORT_META_FIELDS)}, got {key!r}"
                    )
                if not isinstance(value, str) or not value.strip():
                    raise PortMetaError(
                        f"{spot}.ports[{role}].{key}: expected a non-empty string"
                    )
            ports[role] = dict(fields)
        if not ports:
            raise PortMetaError(f"{spot}.ports: nothing declared for any port")
        notes = body.get("notes") or []
        if not isinstance(notes, list) or not all(isinstance(n, str) for n in notes):
            raise PortMetaError(f"{spot}.notes: expected a list of strings")
        provenance = body.get("provenance") or ""
        if not isinstance(provenance, str):
            raise PortMetaError(f"{spot}.provenance: expected a string")
        blocks[name] = TemplatePortMeta(
            name=name, ports=ports, notes=list(notes), provenance=provenance
        )
    top_notes = raw.get("notes") or []
    if not isinstance(top_notes, list) or not all(isinstance(n, str) for n in top_notes):
        raise PortMetaError(f"{where}.notes: expected a list of strings")
    return PortMeta(blocks=blocks, notes=list(top_notes), path=where)


def load_port_meta(path: str | Path) -> PortMeta:
    """Read and validate the sidecar; missing file is an error, not silence."""
    file = Path(path)
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PortMetaError(f"{file}: cannot read: {exc}") from exc
    except ValueError as exc:
        raise PortMetaError(f"{file}: not JSON: {exc}") from exc
    meta = port_meta_from_json(raw, where=str(file))
    meta.path = str(file)
    return meta


__all__ = [
    "PORT_META_FIELDS",
    "PORT_META_KIND",
    "PORT_META_VERSION",
    "PortMeta",
    "PortMetaError",
    "TemplatePortMeta",
    "load_port_meta",
    "port_meta_from_json",
]
