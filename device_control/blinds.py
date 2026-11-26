"""The Shades tab's blinds, found by loose names for the assistant.

A request names blinds, a room ("kitchen"), a floor ("upstairs") or all of
them, in the guest's words. Both the request and every blind/floor name go
through the same :func:`words`, so "the kitchen left blinds" matches
"Kitchen Left Window" and "Living Room Large Window Shade" matches
"living room large window" whichever side carries the "window"/"shade".
"""
import re

from .device_config import BLIND_DEVICES
from .ha_client import call_service, get_entity_states

# Words that never tell blinds apart (device words, articles, fillers).
FILLER = frozenset({
    "the", "a", "an", "and", "in", "on", "of", "at", "to", "for", "my", "our", "this", "that",
    "these", "those", "please", "blind", "shade", "window", "roller", "curtain", "drape",
    "cover", "screen", "one",
})
# Words meaning "every one of them" ("all the kitchen blinds", "the whole house").
QUANTIFIERS = frozenset({"all", "every", "everything", "both", "each", "entire", "whole",
                         "house", "lodge", "home", "everywhere"})
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
AGGREGATE_PREFIX = "All "


class NoMatch(LookupError):
    """Nothing matches a request; the message says what does exist."""


class Ambiguous(LookupError):
    """A request matches blinds in different rooms/floors; ask which."""


def _stem(word):
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def words(text):
    """The words that identify blinds in ``text``: lower case, singular, no fillers."""
    text = text.casefold().replace("'", "")
    raw = (_stem(w) for w in re.split(r"[^0-9a-z]+", text) if w)
    return tuple(w for w in raw if w not in FILLER)


def blinds():
    """Every blind on the Shades tab as dicts in page order.

    ``label`` is the name, prefixed with its floor when another floor has a
    blind of the same name, so labels are unique.
    """
    counts = {}
    for devices in BLIND_DEVICES.values():
        for dev in devices:
            counts[dev["name"]] = counts.get(dev["name"], 0) + 1
    out = []
    for floor, devices in BLIND_DEVICES.items():
        floor_words = set(words(floor))
        for alias in FLOOR_ALIASES.get(floor, ()):
            floor_words |= set(words(alias))
        for dev in devices:
            name = dev["name"]
            label = f"{floor} {name}" if counts[name] > 1 else name
            entity_words = words(dev["entity_id"].removeprefix("cover."))
            out.append({
                "entity_id": dev["entity_id"],
                "name": name,
                "label": label,
                "floor": floor,
                "aggregate": name.startswith(AGGREGATE_PREFIX),
                "exact": {_key(name), _key(label), _key(entity_words)},
                "all_words": (set(words(label)) | floor_words | set(entity_words)) - QUANTIFIERS,
            })
    return out


def floors():
    return list(BLIND_DEVICES)


def _key(text_or_words):
    found = words(text_or_words) if isinstance(text_or_words, str) else text_or_words
    return frozenset(w for w in found if w not in QUANTIFIERS)


def _floor_keys(floor):
    return {_key(floor), *(_key(alias) for alias in FLOOR_ALIASES.get(floor, ()))}


def _resolve_one(items, text, *, strict):
    """The blinds ``text`` names, or None when nothing matches."""
    found = words(text)
    key = frozenset(w for w in found if w not in QUANTIFIERS)
    every = len(key) < len(set(found))
    if not key:
        return list(items)
    exact = [b for b in items if key in b["exact"]]
    if len(exact) == 1:
        return exact
    for floor in floors():
        if key in _floor_keys(floor):
            return [b for b in items if b["floor"] == floor]
    for alias, rooms in ROOM_ALIASES.items():
        if key == _key(alias):
            out = []
            for room in rooms:
                out += _resolve_one(items, room, strict=False) or []
            return out or None
    matches = [b for b in items if key <= b["all_words"]]
    if not matches:
        return None
    spread = list(dict.fromkeys(b["floor"] for b in matches))
    if strict and len(spread) > 1 and not every:
        options = "; ".join(f"{floor}: " + ", ".join(b["label"] for b in matches if b["floor"] == floor)
                            for floor in spread)
        raise Ambiguous(f"{text.strip()!r} could mean blinds on more than one floor ({options}). "
                        "Ask which ones, or say all of them.")
    return matches


def _collapse(found):
    """Leave out blinds an "All ..." group blind already moves."""
    groups = {b["floor"] for b in found if b["aggregate"]}
    return [b for b in found if b["aggregate"] or b["floor"] not in groups]


def resolve(text, *, strict=True, listing=False):
    """The blinds a request names, in page order.

    ``text`` may list several targets ("kitchen, office" or "kitchen and
    office"). Raises :class:`NoMatch` or (when ``strict``) :class:`Ambiguous`.
    For ``listing`` the "All ..." group blinds are left out instead of their members.
    """
    items = blinds()
    found = _resolve_one(items, text, strict=strict)
    if found is None:
        parts = [p for p in re.split(r",|;|&|\+|/|\band\b|\bplus\b", text, flags=re.I) if p.strip()]
        if len(parts) < 2:
            raise NoMatch(no_match_message(text))
        found = []
        for part in parts:
            got = _resolve_one(items, part, strict=strict)
            if got is None:
                raise NoMatch(no_match_message(part))
            found += got
    ids = {b["entity_id"] for b in found}
    if listing:
        groups = {b["floor"] for b in found if b["aggregate"]}
        return [b for b in items if not b["aggregate"] and (b["entity_id"] in ids or b["floor"] in groups)]
    return _collapse([b for b in items if b["entity_id"] in ids])


def no_match_message(text):
    names = ", ".join(b["label"] for b in blinds())
    return (f"There are no blinds called {text.strip()!r}. The floors are {', '.join(floors())}; "
            f"the blinds are {names}.")


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
