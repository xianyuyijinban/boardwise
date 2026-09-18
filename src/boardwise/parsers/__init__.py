"""Input parsers (``.enet`` netlist and ``.epro2`` project backup).

Two layers, deliberately separated (006c, work item 4):

* :mod:`~boardwise.parsers.epru_stream` — the ``.epru`` **framing**: archive
  reading, line-record decoding, ``DOCHEAD`` document splitting. Public names
  only; :func:`load_epru_text` is the entry point. It knows nothing about pads,
  tracks or netlists.
* :mod:`~boardwise.parsers.epru` (copper) and
  :mod:`~boardwise.parsers.epro2_model` (connectivity) — the two *views* over
  that stream.

The split exists because the schematic parser used to reach into the copper
builder for a private ``_load_epru_text`` just to read a text file.
"""

from .enet import parse_enet
from .epro2_model import build_design_model
from .epru import (
    EncryptedProjectError,
    build_board_geometry,
    load_epro2_source,
    parse_epro2,
    parse_epru_text,
)
from .epru_stream import (
    ParseStats,
    iter_epru_records,
    load_epru_text,
    read_project_meta,
    split_documents,
)

__all__ = [
    "EncryptedProjectError",
    "ParseStats",
    "build_board_geometry",
    "build_design_model",
    "iter_epru_records",
    # the framing layer, exported so callers stop reaching into epru.py for it
    "load_epru_text",
    "load_epro2_source",
    "parse_enet",
    "parse_epro2",
    "parse_epru_text",
    "read_project_meta",
    "split_documents",
]
