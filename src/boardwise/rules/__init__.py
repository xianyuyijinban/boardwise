"""Built-in rules."""

from .base import Finding, Rule
from .connectivity import (
    CrystalLoadCaps,
    DecouplingPerIC,
    DuplicateDesignators,
    ShuntSenseLink,
)
from .decap import DecapRequiredCaps
from .facts import (
    DomainVsRange,
    LdoDropout,
    LibraryPinConsistency,
    NcAndMustConnect,
    SupplyOnKnownDomain,
    UsbCcPulldown,
)
from .params import (
    DividerOutput,
    LedCurrent,
    RcCutoff,
    ValueMpnMatch,
)

__all__ = [
    "Finding",
    "Rule",
    "CrystalLoadCaps",
    "DecouplingPerIC",
    "DuplicateDesignators",
    "ShuntSenseLink",
    "NcAndMustConnect",
    "LibraryPinConsistency",
    "SupplyOnKnownDomain",
    "DomainVsRange",
    "LdoDropout",
    "DecapRequiredCaps",
    "LedCurrent",
    "DividerOutput",
    "RcCutoff",
    "ValueMpnMatch",
    "UsbCcPulldown",
]
