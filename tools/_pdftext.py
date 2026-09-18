"""One-off: pull readable text out of a text-layer PDF.

The project's own code may only use the standard library plus `websockets`, and
reading a datasheet happens *before* any of that matters — this is a lab tool
for a human (and an agent) to read a page, not part of the pipeline. It handles
the common `Tj`/`TJ` text operators and ignores everything else.
"""

from __future__ import annotations

import re
import sys
import zlib
from pathlib import Path


def _streams(raw: bytes) -> list[bytes]:
    out: list[bytes] = []
    for match in re.finditer(rb"stream\r?\n", raw):
        start = match.end()
        end = raw.find(b"endstream", start)
        if end < 0:
            continue
        blob = raw[start:end]
        try:
            out.append(zlib.decompress(blob))
        except zlib.error:
            out.append(blob)
    return out


_STRING = re.compile(rb"\((?:\\.|[^\\()])*\)")


def _decode_literal(token: bytes) -> str:
    body = token[1:-1]
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i : i + 1]
        if ch == b"\\":
            nxt = body[i + 1 : i + 2]
            mapping = {b"n": "\n", b"r": "\r", b"t": "\t", b"(": "(", b")": ")", b"\\": "\\"}
            out.append(mapping.get(nxt, nxt.decode("latin-1")))
            i += 2
            continue
        out.append(ch.decode("latin-1"))
        i += 1
    return "".join(out)


def text_of(path: Path) -> str:
    raw = path.read_bytes()
    lines: list[str] = []
    for stream in _streams(raw):
        # A text object per `BT ... ET`; within it every show operator appends.
        for block in re.findall(rb"BT(.*?)ET", stream, flags=re.DOTALL):
            chunk: list[str] = []
            for token in _STRING.finditer(block):
                chunk.append(_decode_literal(token.group(0)))
            if chunk:
                lines.append(" ".join(chunk))
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: _pdftext.py FILE.pdf [> out.txt]", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    for name in argv[1:]:
        path = Path(name)
        print(f"===== {path.name} =====")
        print(text_of(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
