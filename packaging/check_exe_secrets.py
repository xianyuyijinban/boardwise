#!/usr/bin/env python3
"""The zlib streams inside a PyInstaller one-file exe, as readable bytes.

A release artifact is the one place a leak can hide from every source-level
gate: ``tools/check_repo_hygiene.py`` reads the index and the working tree, and
the exe is built *after* both were clean, from whatever the build machine had on
disk at that moment (193 §B.3 — the 186 round shipped two docstrings into a
commit precisely because the gate only ever looked at source files).

A one-file PyInstaller build is not one opaque blob. It is a small C loader, an
archive with a table of contents, and then **each embedded file as its own zlib
stream** (the TOC is streamed too). So the bytes that matter are not visible with
a plain ``grep``, and the honest scan is: find every zlib stream, decompress it,
and read the text inside.

:func:`iter_zlib_streams` does exactly that, in one pass:

* a candidate is an offset where the two bytes are a **valid zlib header**
  (``78 01`` / ``78 5e`` / ``78 9c`` / ``78 da`` — the four compression-level
  spellings PyInstaller emits, and the ``78`` makes ``(b0 << 8 | b1) % 31 == 0``
  hold). Roughly four offsets in 65 thousand qualify, so the scan stays linear
  rather than trying every byte;
* ``decompressobj().decompress(data[offset:])`` decodes the stream and stops at
  its end, leaving the rest in ``unused_data`` — so a 20 MB exe is walked in
  stream-sized steps, not by re-decompressing its tail at every candidate;
* the scan resumes **after** the bytes that stream consumed, which is what keeps
  a decompressed payload from being re-scanned as if it were still compressed;
* **a stream counts only when the decompressor reached its end** (``eof``,
  S3#3): zlib reports no error for a stream that was simply cut off, and a
  truncated one used to be accepted like a complete one — then "resumed" at EOF,
  because a stream that never ended has no ``unused_data``. One accidental
  header followed by garbage (an offset inside the loader or the TOC) therefore
  swallowed the whole rest of the file, and every real stream after it went
  unseen. A candidate that does not reach ``eof`` is treated as what it is —
  two bytes of coincidence — and the scan steps past it by exactly those two
  bytes (no real stream can start at offset+1: its first byte would have to be
  ``78``, and the header check already fixed byte 1 of the candidate).

Only top-level streams are returned: a stream nested inside a decompressed
payload is reported as part of its parent's text, which is what a leak scan
wants — the bytes are in the parent's output either way.
"""

from __future__ import annotations

import sys
import zlib

#: The zlib header's first byte is always 0x78 and the second is one of these
#: (compression level 1/5/9 × the default dictionary); ``(0x78 << 8 | b1) % 31``
#: is 0 for all four, which is zlib's own header check.
_ZLIB_HEADERS = (b"\x78\x01", b"\x78\x5e", b"\x78\x9c", b"\x78\xda")

#: Below this, a "stream" is a coincidence rather than a payload worth reporting.
_MIN_STREAM_BYTES = 16


def is_exe_name(name: str) -> bool:
    """Whether a path names a Windows executable (the artifact whose streams count)."""
    return name.lower().endswith((".exe", ".dll", ".pyd"))


def iter_zlib_streams(data: bytes, min_bytes: int = _MIN_STREAM_BYTES):
    """Yield every zlib stream's decompressed bytes in ``data``, in file order.

    ``min_bytes`` drops the streams too small to be a payload while keeping
    every one that could hold a name.

    A candidate is yielded only when ``decompressor.eof`` is true — see the
    module docstring (S3#3): a truncated stream decodes without error and
    consumes everything after it, so accepting one hides every real stream
    behind it. Rejected candidates cost two bytes, not one: a genuine stream
    cannot begin at an offset whose two bytes are already a valid header.
    """
    index = 0
    size = len(data)
    while index < size - 1:
        if data[index : index + 2] in _ZLIB_HEADERS:
            stream = None
            complete = False
            try:
                decompressor = zlib.decompressobj()
                stream = decompressor.decompress(data[index:])
                complete = decompressor.eof
            except zlib.error:
                stream = None
            if complete and stream is not None and len(stream) >= min_bytes:
                yield stream
                consumed = size - index - len(decompressor.unused_data)
                index += max(consumed, 2)
                continue
            index += 2
            continue
        index += 1


def scan_text(data: bytes) -> str:
    """The readable text inside a payload, for the word gate to search.

    ``errors="replace"`` rather than a refusal: a stream that will not decode is
    still where a name typed into a docstring ends up, and the surrounding ASCII
    of a ``.pyc``'s marshalled strings survives the decode. A false hit is a
    five-second look; a miss is a release.
    """
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "replace")
    return data.decode("utf-8", "replace")


def main(argv: list[str]) -> int:
    """Report the streams in the given files — a probe, not a gate.

    Prints counts and sizes only; the words belong to
    ``tools/check_repo_hygiene.py --assets``, which is the gate that reads them.
    """
    total = 0
    for name in argv[1:]:
        try:
            data = sys.stdin.buffer.read() if name == "-" else open(name, "rb").read()  # noqa: SIM115
        except OSError as exc:
            print(f"check_exe_secrets: cannot read {name}: {exc}", file=sys.stderr)
            return 2
        streams = list(iter_zlib_streams(data))
        whole = sum(len(stream) for stream in streams)
        print(f"{name}: {len(data)} bytes, {len(streams)} zlib stream(s), {whole} bytes decompressed")
        total += len(streams)
    print(f"total zlib streams: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
