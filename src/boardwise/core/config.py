"""The user-level settings: ``%USERPROFILE%\\.boardwise\\config.json`` (039 批②).

boardwise's first user-level setting lives here, and the shape is deliberately
small: a **table** of known keys with a default and a type, a file that holds the
ones the user changed, and a resolved view that applies the defaults. The table is
the contract — `set` refuses an unknown key ("the table is extended by decision,
not by typo", the same rule the part library's category vocabulary follows), and a
key that is absent from the file is simply not overridden.

Two spellings of the same setting are read, one is written:

* flat, dotted — ``{"review.aesthetics": true}`` — what `config set` writes;
* nested — ``{"review": {"aesthetics": true}}`` — accepted because a human who
  opens the file by hand will reasonably try it.

`BOARDWISE_HOME` overrides the directory, matching the daemon's own convention
(`bridge/daemon.py`), so a test — or a second profile — never has to touch the
real one.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The file name under the boardwise home.
CONFIG_FILE = "config.json"

#: The settings table. One entry per key: what it means, its default, and how a
#: text value is parsed. `kind` is checked on write, so a file cannot carry a
#: string where a switch belongs and be silently trusted.
_TRUE = frozenset({"on", "true", "1", "yes", "y", "开", "是"})
_FALSE = frozenset({"off", "false", "0", "no", "n", "关", "否"})


class ConfigError(ValueError):
    """The configuration cannot be read, or the key/value is not one it knows."""


@dataclass(frozen=True)
class Setting:
    """One known key."""

    key: str
    default: Any
    kind: type
    label: str
    help: str


SETTINGS: dict[str, Setting] = {
    "review.aesthetics": Setting(
        key="review.aesthetics",
        default=False,
        kind=bool,
        label="布局审美评分",
        help=(
            "打开后 checkup 报告加 layout_review 节（拓扑可辨 / 流向明确 / 文字可读 / "
            "分组合理 / 网络标识规范 五轴各 1–5 分 + 一句证据）。初装默认关：它要求驱动模型"
            "具备视觉能力，且会多看几张画布图。单次覆盖用 `checkup --aesthetics` / "
            "`--no-aesthetics`。"
        ),
    ),
}


def boardwise_home() -> Path:
    """The boardwise home directory (``BOARDWISE_HOME`` wins, else ``~/.boardwise``)."""
    override = os.environ.get("BOARDWISE_HOME")
    return Path(override) if override else Path.home() / ".boardwise"


def config_path(home: Path | None = None) -> Path:
    """The settings file's path (it may not exist — that is the default state)."""
    return (home or boardwise_home()) / CONFIG_FILE


def parse_value(key: str, raw: str) -> Any:
    """A command-line text value → the typed value for ``key``.

    Only the types the table declares: a switch takes the words people actually
    type (`on`/`off`, and their Chinese equivalents), and anything else is an
    error rather than a truthy string.
    """
    setting = SETTINGS.get(key)
    if setting is None:
        raise ConfigError(
            f"unknown setting {key!r}; known keys: {', '.join(sorted(SETTINGS))}"
        )
    if setting.kind is bool:
        text = str(raw).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise ConfigError(
            f"{key}: expected on/off (got {raw!r}); the values are on, off, true, "
            "false, 1, 0, yes, no"
        )
    raise ConfigError(f"{key}: unsupported kind {setting.kind.__name__}")


def read_config(home: Path | None = None) -> dict[str, Any]:
    """The raw file contents, or ``{}`` when there is no file.

    A malformed file is an error, never silently empty: a settings file the tool
    cannot read is a settings file the user believes is in force.
    """
    path = config_path(home)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read: {exc}") from exc
    except ValueError as exc:
        raise ConfigError(f"{path}: not JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a JSON object of settings")
    return raw


def _lookup(raw: dict[str, Any], key: str) -> tuple[bool, Any]:
    """``(found, value)`` for one key, flat spelling first then nested."""
    if key in raw:
        return True, raw[key]
    node: Any = raw
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def source_of(key: str, *, home: Path | None = None) -> str:
    """``"file"`` when the settings file names this key, else ``"default"``.

    Public because the CLI reports it: "the value is off" and "the value is off
    because nobody chose it" are different answers for the user, and the raw
    lookup is an implementation detail a caller must not reach into.
    """
    if key not in SETTINGS:
        raise ConfigError(
            f"unknown setting {key!r}; known keys: {', '.join(sorted(SETTINGS))}"
        )
    found, _ = _lookup(read_config(home), key)
    return "file" if found else "default"


def get_setting(key: str, *, home: Path | None = None) -> Any:
    """The resolved value: the file's if it names the key, else the default."""
    setting = SETTINGS.get(key)
    if setting is None:
        raise ConfigError(
            f"unknown setting {key!r}; known keys: {', '.join(sorted(SETTINGS))}"
        )
    found, value = _lookup(read_config(home), key)
    if not found:
        return setting.default
    if setting.kind is bool:
        if isinstance(value, bool):
            return value
        # A hand-edited string is accepted through the same parser the CLI uses,
        # and a value that is neither is reported rather than coerced.
        if isinstance(value, str):
            return parse_value(key, value)
        raise ConfigError(
            f"{config_path(home)}: {key} must be true or false, got {value!r}"
        )
    return value


def resolved_settings(*, home: Path | None = None) -> dict[str, dict[str, Any]]:
    """Every known key with its value and where that value came from."""
    raw = read_config(home)
    out: dict[str, dict[str, Any]] = {}
    for key, setting in SETTINGS.items():
        found, _ = _lookup(raw, key)
        out[key] = {
            "value": get_setting(key, home=home),
            "source": "file" if found else "default",
            "default": setting.default,
            "label": setting.label,
            "kind": setting.kind.__name__,
            "help": setting.help,
        }
    return out


def set_setting(key: str, value: Any, *, home: Path | None = None) -> Path:
    """Write one key, atomically, and return the file's path.

    Read-modify-write over the whole document (a settings file is small and a
    partial write would lose somebody else's key), with a `.tmp` sibling plus
    `os.replace` so an interrupted write cannot leave a half file where the
    settings used to be.
    """
    setting = SETTINGS.get(key)
    if setting is None:
        raise ConfigError(
            f"unknown setting {key!r}; known keys: {', '.join(sorted(SETTINGS))}"
        )
    if setting.kind is bool and not isinstance(value, bool):
        raise ConfigError(f"{key}: expected true or false, got {value!r}")
    raw = read_config(home)
    raw = {k: v for k, v in raw.items() if k != key}  # flat wins; no stale duplicate
    raw[key] = value
    path = config_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)
    return path


def aesthetics_enabled(override: bool | None, *, home: Path | None = None) -> tuple[bool, str]:
    """``(enabled, source)`` for `review.aesthetics`.

    ``override`` is the command line's single-run choice (`--aesthetics` /
    `--no-aesthetics`); ``None`` means "the user did not say", and then the
    configuration decides. The override always wins — that is what makes the
    switch testable without touching a file the user owns.
    """
    if override is not None:
        return bool(override), "cli"
    return bool(get_setting("review.aesthetics", home=home)), "config"
