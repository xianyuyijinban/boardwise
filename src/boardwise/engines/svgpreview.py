"""Offline SVG preview of a compiled plan (053 stage B: "岳不开编辑器即可看布局质量").

One function for the whole job — :func:`render_svg` — plus a writer that puts it
where a reviewer can open it. Pure standard library (string building and
``html.escape``): the point of the preview is that a compiled drawing can be
*looked at* without a browser engine, a plotting library or the editor, and a new
dependency would be the one thing this path cannot carry.

What the picture shows, and why each element is there:

* the **page and the keep-outs**, the same boxes the readability checker tests
  against, so "it fits" is visible rather than asserted;
* every **part** as its symbol's body box, with its pins and the reference/value
  text at the boxes the *compiler* computed — the font-metric boxes, drawn dashed,
  because a reviewer who sees only glyphs cannot tell whether a text was measured
  or estimated;
* every **wire**, **junction**, **label** and **flag**, with a label's anchor dot
  separate from its text (they are different facts in `LayoutPlan`). A flag's box
  is the one `drawcompiler` reserves — the glyph hanging away from the pin
  (`core.symbolprofile.flag_glyph_box`, 060) — so the two cannot disagree about
  which side of the anchor the flag occupies, which is how 054-059's upside-down
  flags stayed invisible;
* a caption with the plan's geometry digest, the compiler's notes and the raw soft
  metrics — never a score (052 sec.6), just the numbers the ranking used.

The transform is a pure map from canvas to SVG pixels: SVG's y grows down and the
canvas' grows up (010c measured), so ``Y = top - y``; no transform attribute is
used, so text renders the right way up.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Mapping, Sequence

from boardwise.core.layoutplan import LayoutPlan
from boardwise.core.symbolprofile import (
    Box,
    SymbolPose,
    SymbolProfile,
    flag_glyph_box,
)

__all__ = [
    "PREVIEW_FONT_SIZE",
    "PREVIEW_KIND",
    "PREVIEW_MARGIN",
    "render_svg",
    "write_preview",
]

#: Identifies the artefact, so a file on disk says what it is.
PREVIEW_KIND = "boardwise-plan-preview/1"

#: Canvas units of blank space around the drawing when no page is stated.
PREVIEW_MARGIN = 40.0

#: The caption's font size in SVG units (the drawing itself is 1:1).
PREVIEW_FONT_SIZE = 11.0

_COLOURS = {
    "background": "#ffffff",
    "page": "#f7f7f4",
    "grid": "#eeeeea",
    "border": "#cccccc",
    "body": "#e8e8e8",
    "bodyEdge": "#333333",
    "pin": "#888888",
    "wire": "#0b6b3a",
    "junction": "#0b6b3a",
    "label": "#1d4ed8",
    "flag": "#b45309",
    "text": "#444444",
    "textBox": "#e0a800",
    "keepout": "#cc3333",
    "frame": "#7c3aed",
    "caption": "#222222",
}


def render_svg(
    layout_plan: LayoutPlan,
    profiles: Mapping[str, SymbolProfile] | Sequence[SymbolProfile],
    *,
    page_box: Box | None = None,
    keepouts: Sequence[Box] = (),
    frames: Sequence[tuple[str, Box]] = (),
    title: str = "",
    scale: float = 1.0,
) -> str:
    """One compiled plan as an SVG document.

    ``profiles`` are the library entries the plan was drawn with — they are what
    turns a placed origin into a visible body, a pin and a glyph. ``page_box``
    states the sheet the drawing is meant for; when it is ``None`` the drawing's
    own bounding box (plus :data:`PREVIEW_MARGIN`) becomes the frame, which is
    the same convention the compiler uses for "no page was stated". ``frames`` are
    the named module frames of a *page* (056), drawn as outlines so a reviewer can
    see which group owns which part of the sheet; the parameter defaults to empty,
    and a single drawing's preview is byte-identical whether or not it is used.
    """
    if scale <= 0:
        raise ValueError(f"scale must be positive, got {scale!r}")
    book = _book(profiles)
    box = page_box if page_box is not None else _content_box(layout_plan, book)
    width = (box[2] - box[0]) * scale
    height = (box[3] - box[1]) * scale

    def x(value: float) -> float:
        return (value - box[0]) * scale

    def y(value: float) -> float:
        return (box[3] - value) * scale

    def rect(item: Box, **attributes: str) -> str:
        return (
            f'<rect x="{x(item[0]):.3f}" y="{y(item[3]):.3f}" '
            f'width="{(item[2] - item[0]) * scale:.3f}" '
            f'height="{(item[3] - item[1]) * scale:.3f}" '
            + " ".join(f'{key}="{value}"' for key, value in attributes.items())
            + "/>"
        )

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
        f'height="{height + 90:.0f}" viewBox="0 0 {width:.0f} {height + 90:.0f}" '
        f'font-family="DejaVu Sans, Consolas, monospace" '
        f'font-size="{PREVIEW_FONT_SIZE:g}">',
        f'<rect x="0" y="0" width="{width:.0f}" height="{height + 90:.0f}" '
        f'fill="{_COLOURS["background"]}"/>',
        rect(box, fill=_COLOURS["page"], stroke=_COLOURS["border"]),
    ]
    parts.extend(_grid(box, scale, x, y))
    for keep in keepouts:
        parts.append(rect(keep, fill="none", stroke=_COLOURS["keepout"],
                          **{"stroke-dasharray": "4 3"}))
    for name, frame in frames:
        parts.append(rect(frame, fill="none", stroke=_COLOURS["frame"],
                          **{"stroke-dasharray": "6 4", "stroke-width": "1.4"}))
        parts.append(
            f'<text x="{x(frame[0]) + 5:.3f}" y="{y(frame[3]) + 13:.3f}" '
            f'fill="{_COLOURS["frame"]}" font-size="12">{escape(str(name))}</text>'
        )

    for symbol in layout_plan.power_symbols:
        profile = book.get(symbol.symbol_ref)
        glyph = flag_glyph_box(
            profile, rotation=symbol.rotation, anchor=(symbol.x, symbol.y),
        ) if profile is not None else None
        if glyph is not None:
            parts.append(rect(glyph, fill="none", stroke=_COLOURS["flag"],
                              **{"stroke-width": "1.2"}))
        parts.append(
            f'<circle cx="{x(symbol.x):.3f}" cy="{y(symbol.y):.3f}" r="2.5" '
            f'fill="{_COLOURS["flag"]}"/>'
        )
        parts.append(
            f'<text x="{x(symbol.x) + 6:.3f}" y="{y(symbol.y) - 4:.3f}" '
            f'fill="{_COLOURS["flag"]}">{escape(symbol.net)}</text>'
        )

    for segment in layout_plan.segments:
        points = " ".join(
            f"{x(point[0]):.3f},{y(point[1]):.3f}" for point in segment.points
        )
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="{_COLOURS["wire"]}" '
            'stroke-width="1.8"/>'
        )
    for junction in layout_plan.junctions:
        parts.append(
            f'<circle cx="{x(junction.x):.3f}" cy="{y(junction.y):.3f}" r="3.2" '
            f'fill="{_COLOURS["junction"]}"/>'
        )

    for part in layout_plan.parts:
        profile = book.get(part.symbol_ref)
        pose = SymbolPose(rotation=int(part.rotation), mirror=part.mirror)
        origin = (part.x, part.y)
        body = _body_box(profile, pose, origin)
        if body is not None:
            parts.append(rect(body, fill=_COLOURS["body"], stroke=_COLOURS["bodyEdge"],
                              **{"stroke-width": "1.2"}))
        if profile is not None:
            for pin in profile.pins:
                tip = _transform(pin.tip, pose, origin)
                parts.append(
                    f'<circle cx="{x(tip[0]):.3f}" cy="{y(tip[1]):.3f}" r="2.2" '
                    f'fill="{_COLOURS["pin"]}"/>'
                )
                parts.append(
                    f'<text x="{x(tip[0]) + 4:.3f}" y="{y(tip[1]) - 3:.3f}" '
                    f'fill="{_COLOURS["pin"]}" font-size="9">'
                    f'{escape(str(pin.number))}</text>'
                )
        parts.append(
            f'<circle cx="{x(part.x):.3f}" cy="{y(part.y):.3f}" r="1.6" '
            f'fill="{_COLOURS["bodyEdge"]}"/>'
        )

    for text in layout_plan.texts:
        parts.append(rect(text.bbox, fill="none", stroke=_COLOURS["textBox"],
                          **{"stroke-dasharray": "2 2", "stroke-width": "0.8"}))
        centre_x = (text.bbox[0] + text.bbox[2]) / 2.0
        centre_y = (text.bbox[1] + text.bbox[3]) / 2.0
        parts.append(
            f'<text x="{x(centre_x):.3f}" y="{y(centre_y) + 3:.3f}" '
            f'fill="{_COLOURS["text"]}" text-anchor="middle">'
            f"{escape(text.text)}</text>"
        )
    for label in layout_plan.labels:
        parts.append(rect(label.bbox, fill="none", stroke=_COLOURS["label"],
                          **{"stroke-dasharray": "2 2", "stroke-width": "0.8"}))
        centre_x = (label.bbox[0] + label.bbox[2]) / 2.0
        centre_y = (label.bbox[1] + label.bbox[3]) / 2.0
        parts.append(
            f'<text x="{x(centre_x):.3f}" y="{y(centre_y) + 3:.3f}" '
            f'fill="{_COLOURS["label"]}" text-anchor="middle">'
            f"{escape(label.text)}</text>"
        )
        parts.append(
            f'<circle cx="{x(label.x):.3f}" cy="{y(label.y):.3f}" r="2.0" '
            f'fill="{_COLOURS["label"]}"/>'
        )

    parts.extend(_caption(layout_plan, title, box, scale, height))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def write_preview(
    path: str | Path,
    layout_plan: LayoutPlan,
    profiles: Mapping[str, SymbolProfile] | Sequence[SymbolProfile],
    **options: object,
) -> Path:
    """Render and write one preview; returns where it went."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        render_svg(layout_plan, profiles, **options),  # type: ignore[arg-type]
        encoding="utf-8",
    )
    return target


# ------------------------------------------------------------------- drawing


def _grid(box: Box, scale: float, x, y) -> list[str]:
    """A faint every-50-units grid, so a reader can measure by eye."""
    out: list[str] = []
    step = 50.0
    start = step * int(box[0] // step)
    while start <= box[2]:
        if start >= box[0]:
            out.append(
                f'<line x1="{x(start):.3f}" y1="{y(box[3]):.3f}" '
                f'x2="{x(start):.3f}" y2="{y(box[1]):.3f}" '
                f'stroke="{_COLOURS["grid"]}" stroke-width="0.6"/>'
            )
        start += step
    start = step * int(box[1] // step)
    while start <= box[3]:
        if start >= box[1]:
            out.append(
                f'<line x1="{x(box[0]):.3f}" y1="{y(start):.3f}" '
                f'x2="{x(box[2]):.3f}" y2="{y(start):.3f}" '
                f'stroke="{_COLOURS["grid"]}" stroke-width="0.6"/>'
            )
        start += step
    del scale
    return out


def _caption(
    plan: LayoutPlan, title: str, box: Box, scale: float, height: float
) -> list[str]:
    """The strip under the drawing: what this is, and the raw numbers."""
    metrics = ", ".join(
        f"{key}={value:g}" for key, value in sorted(plan.evidence.soft_metrics.items())
    ) or "soft metrics: not measured"
    lines = [
        title or "boardwise compiled plan (offline preview)",
        f"{PREVIEW_KIND}  geometry {plan.geometry_sha256()[:12]}  "
        f"size {box[2] - box[0]:g} x {box[3] - box[1]:g} units  scale {scale:g}",
        f"verdict {plan.evidence.verdict}  checker {plan.evidence.checker or 'not run'}",
        f"soft metrics: {metrics}",
        *[note[:150] for note in plan.notes[:4]],
    ]
    out: list[str] = []
    for index, line in enumerate(lines):
        out.append(
            f'<text x="8" y="{height + 16 + index * 15:.3f}" '
            f'fill="{_COLOURS["caption"]}">{escape(line)}</text>'
        )
    return out


# ------------------------------------------------------------------ geometry


def _book(
    profiles: Mapping[str, SymbolProfile] | Sequence[SymbolProfile],
) -> dict[str, SymbolProfile]:
    if isinstance(profiles, Mapping):
        return {str(key): value for key, value in profiles.items()}
    return {profile.symbol_ref: profile for profile in profiles}


def _transform(
    local: tuple[float, float], pose: SymbolPose, origin: tuple[float, float]
) -> tuple[float, float]:
    """The same rigid transform the compiler and the checker use.

    Imported from `core.geometry` rather than re-derived: a preview drawn with its
    own convention would show a *different* drawing from the one the checker
    measured, which is the one thing a preview must not do.
    """
    from boardwise.core.geometry import transform_point

    return transform_point(
        local[0], local[1], rotation=pose.rotation, mirror=pose.mirror,
        ox=origin[0], oy=origin[1],
    )


def _body_box(
    profile: SymbolProfile | None, pose: SymbolPose, origin: tuple[float, float]
) -> Box | None:
    if profile is None or profile.body is None:
        return None
    x0, y0, x1, y1 = profile.body
    corners = [
        _transform(corner, pose, origin)
        for corner in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    ]
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def _content_box(
    plan: LayoutPlan, book: Mapping[str, SymbolProfile]
) -> Box:
    """The drawing's own extent, used as the frame when no page is stated."""
    boxes: list[Box] = []
    for part in plan.parts:
        profile = book.get(part.symbol_ref)
        body = _body_box(
            profile, SymbolPose(int(part.rotation), part.mirror), (part.x, part.y)
        )
        if body is not None:
            boxes.append(body)
        if profile is not None:
            for pin in profile.pins:
                tip = _transform(
                    pin.tip, SymbolPose(int(part.rotation), part.mirror),
                    (part.x, part.y),
                )
                boxes.append((tip[0], tip[1], tip[0], tip[1]))
    for symbol in plan.power_symbols:
        boxes.append((symbol.x, symbol.y, symbol.x, symbol.y))
    for text in plan.texts:
        boxes.append(text.bbox)
    for label in plan.labels:
        boxes.append(label.bbox)
    for segment in plan.segments:
        for point in segment.points:
            boxes.append((point[0], point[1], point[0], point[1]))
    if not boxes:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(box[0] for box in boxes) - PREVIEW_MARGIN,
        min(box[1] for box in boxes) - PREVIEW_MARGIN,
        max(box[2] for box in boxes) + PREVIEW_MARGIN,
        max(box[3] for box in boxes) + PREVIEW_MARGIN,
    )


@dataclass(frozen=True)
class PreviewNote:
    """What one preview file says, for a caller that lists them."""

    path: str
    geometry: str
    verdict: str
