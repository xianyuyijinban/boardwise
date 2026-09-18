"""Core data model for boardwise.

``model`` is the schematic view (``.enet``), ``geometry`` the physical view
(``.epro2``). They share :func:`is_ground_net` so a rule can ask the same
question of a netlist net and of a copper net.
"""

from .geometry import (
    BBox,
    BoardGeometry,
    BoardOutline,
    ComponentPlacement,
    LayerInfo,
    MIL_TO_MM,
    NetGeometry,
    PadGeometry,
    ParseStats,
    Point,
    PourShape,
    TrackSegment,
    ViaGeometry,
    mil_to_mm,
)
from .model import (
    GROUND_NET_PREFIXES,
    Component,
    DesignModel,
    Net,
    Pin,
    is_ground_net,
)

__all__ = [
    # geometry
    "MIL_TO_MM",
    "BBox",
    "BoardGeometry",
    "BoardOutline",
    "ComponentPlacement",
    "LayerInfo",
    "NetGeometry",
    "PadGeometry",
    "ParseStats",
    "Point",
    "PourShape",
    "TrackSegment",
    "ViaGeometry",
    "mil_to_mm",
    # netlist model
    "GROUND_NET_PREFIXES",
    "Component",
    "DesignModel",
    "Net",
    "Pin",
    "is_ground_net",
]
