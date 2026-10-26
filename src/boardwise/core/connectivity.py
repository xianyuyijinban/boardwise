"""Shared, side-effect-free pin connectivity readings (540B2).

These are the electrical facts used by both the review rules and the pin-repair
readback: which net a pin occupies, which *other* pins share it, and whether a
pin is connected.  A single-member auto net is not a connection; a single-member
net somebody named is one.  Rule outcomes, findings and repair policy stay in
their owning layers.

**The net is read off the component the caller holds** — :func:`component_net`,
one implementation.  That is the 035 round-2 ruling A reading: a caller passes a
component object *because* that object is the board state it is judging, so a
copy handed in from a second view of the project (or a stale one) must answer
about its own pins, not about whatever the model happens to map the designator
to.  :func:`pin_net` is the same reading for a caller that only has a designator
and a model: it looks the component up and then delegates here, so the two can
never disagree about what "the pin sits on this net" means.  (540B fix: the
first cut of the move made the model lookup authoritative *inside*
:func:`nc_violation` / :func:`pin_company`, which answered 「touches no net」 for
a component object the model did not hold — a declared-NC false pass.)
"""

from __future__ import annotations

from .model import Component, DesignModel
from .netdomains import is_auto_net

__all__ = ["component_net", "pin_net", "pin_company", "nc_violation", "pin_dangles"]


def component_net(comp: Component, pin: str) -> str | None:
    """Return the net a pin sits on, read off the component object itself."""
    for item in comp.pins:
        if item.number == pin:
            return item.net
    return None


def pin_net(model: DesignModel, designator: str, pin: str) -> str | None:
    """Return the net name a pin sits on in a parsed model, or ``None``.

    The model lookup, and nothing else: the answer is :func:`component_net` of
    the component the model holds for ``designator``.
    """
    component = model.components.get(designator)
    if component is None:
        return None
    return component_net(component, pin)


def pin_company(model: DesignModel, comp: Component, pin: str) -> list[tuple[str, str]]:
    """Return every *other* pin sharing this pin's net, in model order."""
    node = (model.nets or {}).get(component_net(comp, pin) or "")
    if node is None:
        return []
    return [
        (str(name), str(number))
        for name, number in node.pins
        if not (str(name) == comp.designator and str(number) == str(pin))
    ]


def nc_violation(model: DesignModel, comp: Component, pin: str) -> tuple[bool, str]:
    """Return whether a declared-NC pin is connected, plus the shared evidence.

    Sharing a net with another pin is connected.  Sitting alone on a named net
    is also connected because naming is intent; sitting alone on an editor-auto
    net is the shape of touching nothing and is not connected.
    """
    net = component_net(comp, pin)
    company = pin_company(model, comp, pin)
    if company:
        mates = ", ".join(f"{name}.{number}" for name, number in sorted(company))
        return True, f"sits on net {net!r} with {mates}"
    if net and not is_auto_net(net):
        return True, f"sits alone on the named net {net!r}"
    return False, f"touches no net" + (f" (alone on {net!r})" if net else "")


def pin_dangles(model: DesignModel, comp: Component, pin: str) -> tuple[bool, str]:
    """Return ``not nc_violation`` with the *same* evidence string."""
    connected, how = nc_violation(model, comp, pin)
    return (not connected), how
