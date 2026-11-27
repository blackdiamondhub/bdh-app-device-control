"""The Lights tab's lights, found by loose names for the assistant.

Light names repeat across rooms ("Main Lights", "Chandelier"), so each light
is labelled "<room> <name>" ("Living Room Main Lights") and a room ("living
room lights") targets every light in it. Matching is shared with the blinds
(:mod:`device_control.matching`).
"""
from .device_config import LIGHT_DEVICES
from .ha_client import call_service, get_entity_states
from .matching import Ambiguous, Catalog, NoMatch  # noqa: F401

# Words that never tell lights apart.
DEVICE_WORDS = frozenset({"light", "lamp", "lighting", "bulb", "fixture"})
# Other names for the floors (the LIGHT_DEVICES groups). Not plain "main":
# "main lights" is a light name, not the main floor.
FLOOR_ALIASES = {
    "Upper Floor": ("upper floor", "upstairs", "top floor", "upper level"),
    "Main Floor": ("main floor", "main level", "ground floor"),
    "Basement": ("basement", "downstairs", "lower floor", "lower level"),
    "Exterior": ("exterior", "outside", "outdoor", "outdoors"),
}
ROOM_ALIASES = {
    "great room": ("kitchen", "living room"),
    "lounge": ("living room",),
    "game room": ("game area",),
    "games room": ("game area",),
    "entry": ("front foyer",),
    "entrance": ("front foyer",),
}
#: A no-match message names every light only up to this many.
LIST_LIMIT = 20

CATALOG = Catalog("lights", LIGHT_DEVICES, device_words=DEVICE_WORDS, floor_aliases=FLOOR_ALIASES,
                  room_aliases=ROOM_ALIASES, list_limit=LIST_LIMIT)
# HA colour modes without brightness (any other mode dims).
_NO_DIM_MODES = {"onoff", "unknown"}


def lights():
    """Every light on the Lights tab as dicts in page order (``label`` is unique)."""
    return CATALOG.items()


def floors():
    return CATALOG.floors()


def resolve(text, *, strict=True):
    """The lights a request names, in page order; see :meth:`Catalog.resolve`."""
    return CATALOG.resolve(text, strict=strict)


def states(items):
    """entity_id -> HA state dict for ``items`` ({} when HA gave nothing)."""
    return get_entity_states([d["entity_id"] for d in items])


def is_on(state):
    return bool(state) and state.get("state") == "on"


def dimmable(light, state):
    """Whether ``light`` takes a brightness (assumed yes when HA doesn't say)."""
    if light["type"] != "light":
        return False
    modes = ((state or {}).get("attributes") or {}).get("supported_color_modes")
    return not modes or not set(modes) <= _NO_DIM_MODES


def percent(state):
    """Brightness 1-100 of a light that's on, or None."""
    value = ((state or {}).get("attributes") or {}).get("brightness")
    if not is_on(state) or not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return max(1, min(100, round(value / 2.55)))


def state_text(state):
    """"off", "on", "on at 40%", "unavailable", ... for an HA light/switch state dict."""
    if not state:
        return "unknown"
    pct = percent(state)
    if pct is not None:
        return f"on at {pct}%"
    return state.get("state", "unknown")


def switch(light, on, brightness=None):
    """Turn ``light`` on (at ``brightness`` percent, if given) or off; returns (ok, error)."""
    domain = "light" if light["type"] == "light" else "switch"
    extra = {"brightness_pct": int(brightness)} if on and brightness is not None and domain == "light" else None
    return call_service(domain, "turn_on" if on else "turn_off", light["entity_id"], extra_data=extra)
