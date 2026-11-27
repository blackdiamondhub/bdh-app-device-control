"""The Shades tab's blinds, found by loose names for the assistant.

Matching is shared with the lights (:mod:`device_control.matching`): both the
request and every blind/floor name are normalised the same way, so "the
kitchen left blinds" matches "Kitchen Left Window" and "Living Room Large
Window Shade" matches "living room large window" whichever side carries the
"window"/"shade".
"""
from .device_config import BLIND_DEVICES
from .ha_client import call_service, get_entity_states
from .matching import AGGREGATE_PREFIX, QUANTIFIERS, Ambiguous, Catalog, NoMatch  # noqa: F401

# Words that never tell blinds apart.
DEVICE_WORDS = frozenset({"blind", "shade", "window", "roller", "curtain", "drape", "cover", "screen"})
# Other names for the floors (the BLIND_DEVICES groups).
FLOOR_ALIASES = {
    "Basement": ("basement", "downstairs", "lower floor", "lower level"),
    "Main Floor": ("main floor", "main level", "ground floor", "main"),
    "Upper Floor": ("upper floor", "upstairs", "top floor", "upper level"),
    "Deck / Exterior": ("deck", "exterior", "outside", "outdoor", "patio"),
}
# Rooms with no blind of their own name: "great room" is the open kitchen/living room.
ROOM_ALIASES = {
    "great room": ("kitchen", "living room"),
    "lounge": ("living room",),
}

CATALOG = Catalog("blinds", BLIND_DEVICES, device_words=DEVICE_WORDS,
                  floor_aliases=FLOOR_ALIASES, room_aliases=ROOM_ALIASES)


def words(text):
    """The words that identify blinds in ``text``: lower case, singular, no fillers."""
    return CATALOG.words(text)


def blinds():
    """Every blind on the Shades tab as dicts in page order (``label`` is unique)."""
    return CATALOG.items()


def floors():
    return CATALOG.floors()


def resolve(text, *, strict=True, listing=False):
    """The blinds a request names, in page order; see :meth:`Catalog.resolve`."""
    return CATALOG.resolve(text, strict=strict, listing=listing)


def no_match_message(text):
    return CATALOG.no_match_message(text)


def states(items):
    """entity_id -> HA state dict for ``items`` ({} when HA gave nothing)."""
    return get_entity_states([b["entity_id"] for b in items])


def state_text(state):
    """"open", "closed", "40% open", "opening", ... for an HA cover state dict."""
    if not state:
        return "unknown"
    value = state.get("state", "unknown")
    pos = (state.get("attributes") or {}).get("current_position")
    if value in ("open", "closed") and isinstance(pos, (int, float)) and not isinstance(pos, bool):
        if pos <= 0:
            return "closed"
        if pos >= 100:
            return "open"
        return f"{int(pos)}% open"
    return value


SERVICES = {
    "open": "open_cover",
    "close": "close_cover",
    "stop": "stop_cover",
    "position": "set_cover_position",
}


def move(blind, action, position=None):
    """Call the cover service for ``action``; returns (ok, error)."""
    extra = {"position": int(position)} if action == "position" else None
    return call_service("cover", SERVICES[action], blind["entity_id"], extra_data=extra)