"""Build ``packaging/out/boardwise.exe`` — the single-file friend build (028 §二.2).

The ordering matters and is the reason this is a script rather than a
``pyinstaller packaging/boardwise.spec`` line in a README:

1. **``npm run build`` in ``connector/``** — the exe embeds
   ``connector/dist/index.js``, and the whole point of embedding it is that the
   exe can hot-update the editor from what it carries. Building the exe around a
   stale bundle would ship a friend an extension older than the one the release
   notes describe, with no way to tell from the outside.
2. **The version cross-check** — the connector's ``package.json`` and
   ``extension.json`` must agree, because ``--version`` reports the manifest's
   number while the release notes (3c) quote the bundle's hash.
3. **PyInstaller**, then a report: where the exe is, how big it is, its sha256,
   and the sha256 of the bundle that went into it. All four go into the release
   notes.
4. **The artifact gate** (193 §B.3): ``tools/check_repo_hygiene.py --assets``
   over the exe that was just built — raw bytes plus every zlib stream inside
   it. A hit stops the build here, which is the last moment before the exe
   becomes a release attachment.

Usage: ``.venv/Scripts/python.exe packaging/build_exe.py [--skip-npm]``
Exits non-zero if any step fails; prints one line per step so a build log is
readable on its own.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGING = REPO / "packaging"
OUT = PACKAGING / "out"
WORK = PACKAGING / "build"
EXE = OUT / "boardwise.exe"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(argv: list[str], cwd: Path) -> None:
    print(f"$ {' '.join(argv)}   (in {cwd})", flush=True)
    completed = subprocess.run(argv, cwd=cwd, shell=(sys.platform == "win32"))
    if completed.returncode != 0:
        raise SystemExit(f"boardwise build_exe: {argv[0]} failed ({completed.returncode})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-npm", action="store_true",
        help="Skip `npm run build` (only when the caller just ran it).",
    )
    args = parser.parse_args()

    if not args.skip_npm:
        run(["npm", "run", "build"], REPO / "connector")

    bundle = REPO / "connector" / "dist" / "index.js"
    manifest = json.loads((REPO / "connector" / "extension.json").read_text(encoding="utf-8"))
    package = json.loads((REPO / "connector" / "package.json").read_text(encoding="utf-8"))
    if manifest["version"] != package["version"]:
        raise SystemExit(
            "boardwise build_exe: connector/package.json says "
            f"{package['version']} but extension.json says {manifest['version']} — "
            "the exe would report one version and carry a bundle labelled the other"
        )
    print(f"connector bundle {manifest['version']}  sha256 {sha256(bundle)}  {bundle.stat().st_size} bytes")

    # A clean build directory: PyInstaller reuses build/ artefacts, and a stale
    # one is how "it worked before I changed the spec" happens.
    if WORK.exists():
        shutil.rmtree(WORK)
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.time()
    run(
        [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath", str(OUT),
            "--workpath", str(WORK),
            str(PACKAGING / "boardwise.spec"),
        ],
        REPO,
    )
    if not EXE.is_file():
        raise SystemExit(f"boardwise build_exe: PyInstaller reported success but {EXE} is missing")
    print(
        f"\nboardwise.exe  {EXE}\n"
        f"  size     {EXE.stat().st_size} bytes ({EXE.stat().st_size / 1024 / 1024:.1f} MiB)\n"
        f"  sha256   {sha256(EXE)}\n"
        f"  bundle   {manifest['version']} sha256 {sha256(bundle)}\n"
        f"  build    {time.time() - started:.1f} s"
    )

    # The artifact gate (193 §B.3). Everything above is about reproducing the
    # exe; this is about not publishing it. The source gates ran before the
    # build, against a working tree that is not what PyInstaller read — and the
    # bytes it did read are zlib-compressed inside the exe, so a plain scan of
    # the file would not see them either. `--assets` decompresses the streams.
    # A missing word list (any clone, any CI) prints one line and passes; a hit
    # exits non-zero and this build stops before the exe can be attached to a
    # release.
    print(f"\n$ {sys.executable} tools/check_repo_hygiene.py --assets {EXE.name}", flush=True)
    gate = subprocess.run(
        [sys.executable, str(REPO / "tools" / "check_repo_hygiene.py"), "--assets", str(EXE)],
        cwd=REPO,
    )
    if gate.returncode != 0:
        raise SystemExit(
            "boardwise build_exe: 发布件闸拦下了这个 exe（敏感词表命中，见上方输出）——"
            "不要发布它。命中报告只印条目号，词在 .sensitive-words 里。"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
