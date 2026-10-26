"""Small, dependency-free validator for the JSON Schema 2020-12 subset used by the
540C contracts.

The contracts declare ``https://json-schema.org/draft/2020-12/schema``, so the
subset that the contracts actually use is implemented with 2020-12 semantics
rather than a private dialect:

* ``$ref`` is an applicator: the referenced schema **and** the sibling keywords
  apply, ``$ref`` chains are followed, and a self/circular ``$ref`` raises instead
  of validating nothing.
* ``enum``/``const`` compare recursively, so ``true`` never equals ``1`` — not
  even inside an array or an object — while ``1`` and ``1.0`` are the same JSON
  number.
* ``integer`` accepts any finite JSON number with a zero fractional part
  (``1``, ``1.0``), never a boolean, never ``NaN``/``Infinity``.
* ``items`` applies only to the items *after* ``prefixItems``.
* Boolean schemas are supported: ``true`` accepts, ``false`` rejects.
* ``type`` is checked against the seven JSON type names in the pre-check, so an
  unknown name fails even when an earlier name in a ``type`` union already
  matched (``any()`` would otherwise short-circuit before seeing it).
* ``validate`` pre-checks the whole schema tree once, including ``$defs`` and
  ``properties`` the instance never reaches, so an unsupported keyword or a
  circular ``$ref`` cannot hide in an unused branch. That holds for an explicit
  ``root=`` argument as well: the entry point checks the given root *and* the
  schema it is about to apply, and no node is re-checked while walking.

Supported keywords: ``$ref``, ``type``, ``required``, ``properties``,
``additionalProperties``, ``items``, ``prefixItems``, ``enum``, ``const``,
``pattern``, ``minItems``, ``maxItems``, ``minLength``, ``minimum``.
``x-*`` annotations are documentation; every other keyword fails loudly.

JSON is read through :func:`loads_strict` / :func:`load_path`, which reject
``NaN``/``Infinity`` (and numbers that overflow to infinity): those are not JSON
numbers, and Python's default parser would otherwise accept a file the Rust side
refuses.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
from typing import Any, Iterator


class ContractValidationError(ValueError):
    """The instance or the schema subset is invalid."""


_META = {"$schema", "$id", "title", "description", "$defs"}
_SUPPORTED = {
    "$ref", "type", "required", "properties", "additionalProperties", "items",
    "prefixItems", "enum", "const", "pattern", "minItems", "maxItems",
    "minLength", "minimum",
}
#: The type vocabulary of the declared subset. A name outside it is a schema error
#: in the pre-check, whether or not an instance ever reaches that branch: `any()`
#: would otherwise short-circuit on an earlier match and never evaluate it.
_TYPES = frozenset({"object", "array", "string", "boolean", "integer", "number", "null"})


# ---------------------------------------------------------------------------
# JSON input: the one strict loader every entry point uses
# ---------------------------------------------------------------------------


def _reject_non_finite(token: str) -> Any:
    raise ContractValidationError(
        f"non-finite JSON number {token} is rejected: JSON numbers are finite, and "
        "NaN/Infinity would be accepted here while the Rust side refuses the file"
    )


def ensure_finite(value: Any) -> Any:
    """Reject ``NaN``/``Infinity`` anywhere inside an already-parsed JSON value.

    ``parse_constant`` catches the literal tokens; this catches ``1e999``, which
    ``json`` turns into ``inf`` through the ordinary float parser.
    """
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractValidationError(
            f"non-finite JSON number {value!r} is rejected: JSON numbers are finite"
        )
    if isinstance(value, dict):
        for item in value.values():
            ensure_finite(item)
    elif isinstance(value, list):
        for item in value:
            ensure_finite(item)
    return value


def loads_strict(text: str) -> Any:
    """``json.loads`` for contract JSON: no ``NaN``/``Infinity``, ever."""
    return ensure_finite(json.loads(text, parse_constant=_reject_non_finite))


def load_path(path: Path | str) -> Any:
    """Read a JSON file through the same strict loader."""
    return loads_strict(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Type / value equality
# ---------------------------------------------------------------------------


def _is_number(value: Any) -> bool:
    """A JSON number: never a boolean, never a non-finite float."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _is_integer(value: Any) -> bool:
    """2020-12 ``integer``: a finite number with a zero fractional part."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value) and value.is_integer()
    return False


def _type_matches(value: Any, expected: str) -> bool:
    if expected not in _TYPES:
        # The pre-check already refuses this name; reaching it here means a caller
        # skipped the pre-check, so it still fails loudly instead of matching False.
        raise ContractValidationError(f"unsupported JSON Schema type: {expected!r}")
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return _is_integer(value)
    if expected == "number":
        return _is_number(value)
    if expected == "null":
        return value is None
    raise ContractValidationError(f"unsupported JSON Schema type: {expected!r}")


def _json_equal(left: Any, right: Any) -> bool:
    """JSON value equality, recursive, with ``true`` and ``1`` kept apart.

    Containers are walked element by element: ``[1] == [True]`` and
    ``{"a": 1} == {"a": True}`` are false, because a boolean is not a number in
    JSON. Two numbers compare numerically, so ``1`` and ``1.0`` are equal, which
    is what 2020-12 says. Non-finite floats equal nothing.
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if _is_number(left) and _is_number(right):
        return left == right
    if isinstance(left, float) and not math.isfinite(left):
        return False
    if isinstance(right, float) and not math.isfinite(right):
        return False
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_equal(item_left, item_right)
            for item_left, item_right in zip(left, right)
        )
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _json_equal(left[key], right[key]) for key in left
        )
    return type(left) is type(right) and left == right


# ---------------------------------------------------------------------------
# $ref resolution
# ---------------------------------------------------------------------------


def _lookup_ref(reference: str, root: Any) -> Any:
    if not isinstance(reference, str):
        raise ContractValidationError(f"$ref must be a string, got {reference!r}")
    if reference == "#":
        return root
    if not reference.startswith("#/"):
        raise ContractValidationError(f"only local $ref is supported: {reference!r}")
    target: Any = root
    for token in reference[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(target, dict) or token not in target:
            raise ContractValidationError(f"unresolvable $ref: {reference!r}")
        target = target[token]
    if not isinstance(target, (dict, bool)):
        raise ContractValidationError(f"$ref does not name a schema: {reference!r}")
    return target


def _circular(reference: str, chain: tuple[str, ...], path: str) -> ContractValidationError:
    cycle = " -> ".join([*chain[chain.index(reference):], reference])
    return ContractValidationError(
        f"circular $ref at {path}: {cycle}; a self-referential $ref would "
        "validate nothing, so it is refused rather than passed"
    )


def _check_reference_chain(reference: Any, root: Any, path: str) -> None:
    """Follow a ``$ref`` chain without an instance and refuse a cycle."""
    chain: tuple[str, ...] = ()
    current = reference
    while True:
        if not isinstance(current, str):
            raise ContractValidationError(
                f"invalid schema at {path}: $ref must be a string, got {current!r}"
            )
        if current in chain:
            raise _circular(current, chain, path)
        chain = (*chain, current)
        target = _lookup_ref(current, root)
        if isinstance(target, bool) or "$ref" not in target:
            return
        current = target["$ref"]


# ---------------------------------------------------------------------------
# Whole-schema pre-check (F13: no lazy keyword check)
# ---------------------------------------------------------------------------


def _child_schemas(schema: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    """Every position in this node that holds a subschema (never ``enum`` data)."""
    for name in ("$defs", "properties"):
        mapping = schema.get(name)
        if mapping is not None:
            for key, child in mapping.items():
                yield f"{name}/{key}", child
    for name in ("additionalProperties", "items"):
        child = schema.get(name)
        if child is not None:
            yield name, child
    prefix = schema.get("prefixItems")
    if prefix is not None:
        for index, child in enumerate(prefix):
            yield f"prefixItems/{index}", child


def _invalid(path: str, detail: str) -> ContractValidationError:
    return ContractValidationError(f"invalid schema at {path}: {detail}")


def _check_structure(schema: dict[str, Any], path: str) -> None:
    """Refuse a keyword whose value cannot mean what this validator would do with it."""
    for name in ("$defs", "properties"):
        if name in schema and not isinstance(schema[name], dict):
            raise _invalid(path, f"{name} must be an object, got {type(schema[name]).__name__}")
    for name in ("additionalProperties", "items"):
        if name in schema and not isinstance(schema[name], (dict, bool)):
            raise _invalid(
                path,
                f"{name} must be a schema object or a boolean, got "
                f"{type(schema[name]).__name__}",
            )
    if "prefixItems" in schema and not isinstance(schema["prefixItems"], list):
        raise _invalid(path, "prefixItems must be an array of schemas")
    if "type" in schema:
        expected = schema["type"]
        if isinstance(expected, str):
            names = [expected]
        elif isinstance(expected, list) and expected and all(
            isinstance(item, str) for item in expected
        ):
            names = expected
        else:
            raise _invalid(path, f"type must be a string or a non-empty array of strings, got {expected!r}")
        # The whole vocabulary is checked here, not where an instance meets it:
        # `any()` stops at the first matching branch, so a later unknown name would
        # never be reported while the instance happens to match an earlier one.
        unknown = sorted({name for name in names if name not in _TYPES})
        if unknown:
            raise _invalid(
                path,
                f"unsupported JSON Schema type(s) {unknown}; the subset implements "
                f"{sorted(_TYPES)}",
            )
    if "required" in schema:
        required = schema["required"]
        if not isinstance(required, list) or not all(isinstance(key, str) for key in required):
            raise _invalid(path, "required must be an array of strings")
    if "enum" in schema and not isinstance(schema["enum"], list):
        # 2020-12 only says the array *SHOULD* have an element; an empty enum is a
        # well-defined "nothing matches", so it is not turned into a schema error.
        raise _invalid(path, "enum must be an array")
    if "pattern" in schema:
        if not isinstance(schema["pattern"], str):
            raise _invalid(path, "pattern must be a string")
        try:
            re.compile(schema["pattern"])
        except re.error as error:
            raise _invalid(path, f"pattern is not a regular expression: {error}") from error
    for name in ("minItems", "maxItems", "minLength"):
        if name in schema:
            value = schema[name]
            # 2020-12: "a non-negative integer"; `2.0` is that integer, `True` is not.
            if not _is_integer(value) or value < 0:
                raise _invalid(path, f"{name} must be a non-negative integer, got {value!r}")
    if "minimum" in schema and not _is_number(schema["minimum"]):
        raise _invalid(path, f"minimum must be a finite number, got {schema['minimum']!r}")


def _check_node(schema: Any, root: Any, path: str, active: set[int]) -> None:
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        raise _invalid(path, f"a schema must be an object or a boolean, got {type(schema).__name__}")
    identity = id(schema)
    if identity in active:
        raise _invalid(path, "the schema tree contains itself (a Python object cycle)")
    active.add(identity)
    try:
        unsupported = {
            key for key in schema
            if key not in _SUPPORTED and key not in _META and not key.startswith("x-")
        }
        if unsupported:
            raise ContractValidationError(
                f"unsupported schema keyword(s) at {path}: {sorted(unsupported)}"
            )
        _check_structure(schema, path)
        if "$ref" in schema:
            _check_reference_chain(schema["$ref"], root, path)
        for name, child in _child_schemas(schema):
            _check_node(child, root, f"{path}/{name}", active)
    finally:
        active.discard(identity)


def check_schema(schema: Any) -> None:
    """Pre-check the entire schema tree, whether or not an instance reaches it.

    Walks every ``$defs``/``properties``/``items``/``prefixItems``/
    ``additionalProperties`` position, refuses any keyword this validator does not
    implement, and refuses a ``$ref`` that is unresolvable or circular. Raises
    :class:`ContractValidationError`; returns ``None`` when the whole tree is in
    the supported subset.
    """
    _check_node(schema, schema, "$", set())


def _check_tree(schema: Any, root: Any) -> None:
    """Pre-check one schema node tree with ``root`` as the ``$ref`` resolution base."""
    _check_node(schema, root, "$", set())


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate(
    instance: Any, schema: Any, path: str, root: Any, ref_chain: tuple[str, ...]
) -> list[str]:
    if isinstance(schema, bool):
        return [] if schema else [
            f"{path}: rejected by a false schema: no value is allowed here"
        ]
    if not isinstance(schema, dict):
        raise _invalid(path, f"a schema must be an object or a boolean, got {type(schema).__name__}")
    reference = schema.get("$ref")
    if reference is not None:
        if reference in ref_chain:
            raise _circular(reference, ref_chain, path)
        errors = _validate(
            instance, _lookup_ref(reference, root), path, root, (*ref_chain, reference)
        )
        # 2020-12: $ref is an applicator, not a replacement — siblings still apply.
        siblings = {name: value for name, value in schema.items() if name != "$ref"}
        if siblings:
            errors = errors + _validate(instance, siblings, path, root, ref_chain)
        return errors
    errors: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        types = [expected] if isinstance(expected, str) else expected
        if not any(_type_matches(instance, item) for item in types):
            return [f"{path}: expected {expected}, got {type(instance).__name__}"]
    if "const" in schema and not _json_equal(instance, schema["const"]):
        errors.append(f"{path}: expected const {schema['const']!r}, got {instance!r}")
    if "enum" in schema and not any(_json_equal(instance, item) for item in schema["enum"]):
        errors.append(f"{path}: {instance!r} is not in enum {schema['enum']!r}")
    if isinstance(instance, str):
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            errors.append(f"{path}: {instance!r} does not match {schema['pattern']!r}")
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: shorter than minLength {schema['minLength']}")
    if _is_number(instance):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} is below minimum {schema['minimum']}")
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: expected at least {schema['minItems']} items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: expected at most {schema['maxItems']} items")
        prefix = schema.get("prefixItems", [])
        for index, subschema in enumerate(prefix):
            if index < len(instance):
                errors.extend(_validate(instance[index], subschema, f"{path}[{index}]", root, ()))
        if "items" in schema:
            # 2020-12: `items` applies only to the tail after `prefixItems`.
            for index in range(len(prefix), len(instance)):
                errors.extend(
                    _validate(instance[index], schema["items"], f"{path}[{index}]", root, ())
                )
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: required key {key!r} is missing")
        properties = schema.get("properties", {})
        for key, subschema in properties.items():
            if key in instance:
                errors.extend(_validate(instance[key], subschema, f"{path}.{key}", root, ()))
        additional = schema.get("additionalProperties", True)
        extra = sorted(set(instance) - set(properties))
        if additional is False:
            for key in extra:
                errors.append(f"{path}: additional property {key!r} is not allowed")
        elif additional is not True:
            for key in extra:
                errors.extend(_validate(instance[key], additional, f"{path}.{key}", root, ()))
    return errors


def validate(
    instance: Any, schema: Any, path: str = "$", root: Any = None
) -> list[str]:
    """Return every validation error; never silently ignore an unsupported keyword.

    Whatever the caller passes as ``root``, the entry point pre-checks the whole
    tree exactly once — the given root *and* the schema about to be applied (they
    are usually the same object). An unknown keyword, an unknown ``type`` name or a
    circular ``$ref`` therefore fails even when the instance never reaches it, and
    :func:`_validate` never re-checks a node it visits.
    """
    if root is None:
        root = schema
    _check_tree(root, root)
    if schema is not root:
        _check_tree(schema, root)
    return _validate(instance, schema, path, root, ())


def assert_valid(instance: Any, schema: Any) -> None:
    errors = validate(instance, schema)
    if errors:
        raise ContractValidationError("\n".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instance", help="JSON instance to validate")
    parser.add_argument("schema", help="JSON Schema using the supported subset")
    args = parser.parse_args()
    instance = load_path(args.instance)
    schema = load_path(args.schema)
    errors = validate(instance, schema)
    if errors:
        print("\n".join(errors))
        return 1
    print(f"valid: {args.instance} against {args.schema}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
