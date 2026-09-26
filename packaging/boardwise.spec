# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the single-file ``boardwise.exe`` (028 batch 3a).

What the friend gets: one file, no Python, no repo. Everything the CLI needs at
runtime that is *not* code travels with it as *data* — and the layout under
``resources/`` mirrors the repo tree exactly, which is what
``boardwise/resources.py`` resolves in the frozen state. The two must agree; if
this file's ``datas`` entries change, that module's ``_*_PARTS`` change with
them, and `tests/test_resources.py` is what says so.

Three deliberate choices:

* **onefile, console.** One file because "download two files" is the whole
  promise; console because the daemon is a visible window the user can Ctrl-C —
  on a friend's machine that visibility is a feature, not a leak (028 §一).
* **No UPX, no signature.** UPX rewrites the binary's sections and some endpoint
  protections read that as malware; signing needs a certificate nobody has. The
  Release notes say SmartScreen will ask once, and that is the honest answer.
* **``packaging/out/`` for the artifact**, never the repo-root ``dist/``, which
  belongs to the connector's build and is where ``update-connector`` reads from.

Build it with ``python packaging/build_exe.py`` (that script runs
``npm run build`` first, so the embedded bundle is the one the manifest names).
"""

import sys
from pathlib import Path

# `SPECPATH` is set by PyInstaller to the directory holding this spec
# (`<repo>/packaging`). The name check rather than `parents[N]` because the two
# PyInstaller versions in the wild disagree about whether that variable is the
# spec's directory or the spec's file path — and a wrong `parents[N]` here does
# not fail loudly, it points the resource paths at `E:\` and the missing-resource
# guard below blames the wrong thing.
_SPEC_DIR = Path(SPECPATH).resolve()  # noqa: F821 - injected by PyInstaller
REPO = _SPEC_DIR.parent if _SPEC_DIR.name == "packaging" else _SPEC_DIR

#: The resources the CLI resolves at runtime, mirrored into the bundle under
#: `resources/` with the same relative paths (`boardwise/resources.py`).
DATAS = [
    (REPO / "connector" / "dist" / "index.js", "resources/connector/dist"),
    (REPO / "connector" / "extension.json", "resources/connector"),
    (
        REPO / ".kimi-code" / "skills" / "boardwise" / "SKILL.md",
        "resources/.kimi-code/skills/boardwise",
    ),
    # The curated shelf, and deliberately *only* that one file out of
    # `blocklib/`. `blocklib/sources/` is 22 MB of project containers kept as
    # read-only review input — carrying them inside a downloadable exe is what
    # the hygiene guard's red line is about; `parts.corrections.json` is a
    # curation sidecar read by `tools/`, never by the CLI's load path. Without
    # parts.json a frozen process read a *missing* file as an empty shelf, and
    # every facts-driven rule went quiet without saying so.
    (REPO / "blocklib" / "parts.json", "resources/blocklib"),
]

for _source, _target in DATAS:
    if not _source.is_file():  # a build that cannot work should stop here
        raise SystemExit(f"boardwise.spec: missing resource {_source} (target {_target})")

analysis = Analysis(  # noqa: F821 - injected by PyInstaller
    [str(REPO / "packaging" / "entry.py")],
    pathex=[str(REPO / "src")],
    binaries=[],
    datas=DATAS,
    # The daemon imports `websockets.asyncio.server` / `websockets.asyncio.client`
    # at module level, so the analysis finds them; these names are listed because
    # they are the ones a `hiddenimports`-less build has failed on before, and an
    # explicit list costs nothing when it is redundant. `boardwise.bridge.daemon`
    # and `boardwise.bridge.client` import `websockets` lazily inside functions,
    # which is exactly the shape static analysis can miss.
    hiddenimports=[
        "websockets",
        "websockets.asyncio",
        "websockets.asyncio.server",
        "websockets.asyncio.client",
        "boardwise.bridge.daemon",
        "boardwise.bridge.client",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "pyinstaller"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)  # noqa: F821 - injected by PyInstaller

exe = EXE(  # noqa: F821 - injected by PyInstaller
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="boardwise",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

if sys.platform == "win32":
    # Onefile: everything above ends up appended to this single binary.
    pass
