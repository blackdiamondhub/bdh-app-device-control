"""Loose names for the assistant's device tools (the Shades and Lights tabs).

A request names devices, a room ("kitchen"), a floor ("upstairs") or all of
them, in the guest's words. Both the request and every device/room/floor name
go through the same :meth:`Catalog.words`, so "the kitchen left blinds"
matches "Kitchen Left Window" and "living room lights" matches the Living
Room's "Main Lights" whichever side carries the device word.
"""
import re
from collections import Counter

# Words that never tell devices apart; each catalog adds its device words.
COMMON_FILLER = frozenset({
    "the", "a", "an", "and", "in", "on", "of", "at", "to", "for", "my", "our", "this", "that",
    "these", "those", "please", "one",
})
# Words meaning "every one of them" ("all the kitchen blinds", "the whole house").
QUANTIFIERS = frozenset({"all", "every", "everything", "both", "each", "entire", "whole",
                         "house", "lodge", "home", "everywhere"})
AGGREGATE_PREFIX = "All "
_SPLIT = re.compile(r",|;|&|\+|/|\band\b|\bplus\b", re.I)


class NoMatch(LookupError):
    """Nothing matches a request; the message says what does exist."""


class Ambiguous(LookupError):
    """A request matches devices on different floors; ask which.

    ``matches`` are the devices it could mean.
    """

    def __init__(self, message, matches=()):
        super().__init__(message)
        self.matches = list(matches)


def _stem(word):
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def join(parts):
    """"a", "a and b", "a, b and c"."""
    parts = list(parts)
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


class Catalog:
    """The devices of one Controls tab (``groups``: floor -> device dicts).

    ``noun`` is the plural the messages use ("blinds"). Devices with a
    ``room`` are labelled "<room> <name>" (unless the name already says the
    room) and can be targeted by room. A label that repeats on another floor
    is prefixed with its floor, so labels are unique. ``list_limit`` caps how
    many devices a no-match message names (None: always all of them).
    """

    def __init__(self, noun, groups, *, device_words, floor_aliases, room_aliases=None, list_limit=None):
        self.noun = noun
        self.groups = groups
        self.filler = COMMON_FILLER | frozenset(device_words)
        self.floor_aliases = floor_aliases
        self.room_aliases = room_aliases or {}
        self.list_limit = list_limit

    def words(self, text):
        """The words that identify devices in ``text``: lower case, singular, no fillers."""
        text = text.casefold().replace("'", "")
        raw = (_stem(w) for w in re.split(r"[^0-9a-z]+", text) if w)
        return tuple(w for w in raw if w not in self.filler)

    def key(self, text_or_words):
        found = self.words(text_or_words) if isinstance(text_or_words, str) else text_or_words
        return frozenset(w for w in found if w not in QUANTIFIERS)

    def floors(self):
        return list(self.groups)

    def rooms(self):
        return list(dict.fromkeys(d["room"] for devices in self.groups.values()
                                  for d in devices if d.get("room")))

    def _floor_keys(self, floor):
        return {self.key(floor), *(self.key(alias) for alias in self.floor_aliases.get(floor, ()))}

    def items(self):
        """Every device as dicts in page order."""
        base = []
        for floor, devices in self.groups.items():
            for dev in devices:
                label, room = dev["name"], dev.get("room")
                if room and not set(self.words(room)) <= set(self.words(label)):
                    label = f"{room} {label}"
                base.append((floor, dev, label))
        counts = Counter(label for _, _, label in base)
        out = []
        for floor, dev, label in base:
            if counts[label] > 1:
                label = f"{floor} {label}"
            floor_words = set(self.words(floor))
            for alias in self.floor_aliases.get(floor, ()):
                floor_words |= set(self.words(alias))
            entity_words = self.words(dev["entity_id"].split(".", 1)[-1])
            name = dev["name"]
            out.append({
                "entity_id": dev["entity_id"],
                "name": name,
                "label": label,
                "floor": floor,
                "room": dev.get("room"),
                "type": dev.get("type"),
                "aggregate": name.startswith(AGGREGATE_PREFIX),
                "exact": {self.key(name), self.key(label), self.key(entity_words)},
                "all_words": (set(self.words(label)) | floor_words | set(entity_words)) - QUANTIFIERS,
            })
        return out

    def _ambiguous(self, text, matches, spread):
        options = "; ".join(f"{floor}: " + ", ".join(d["label"] for d in matches if d["floor"] == floor)
                            for floor in spread)
        return Ambiguous(f"{text.strip()!r} could mean {self.noun} on more than one floor ({options}). "
                         "Ask which ones, or say all of them.", matches)

    def _resolve_one(self, items, text, *, strict):
        """The devices ``text`` names, or None when nothing matches."""
        found = self.words(text)
        key = frozenset(w for w in found if w not in QUANTIFIERS)
        every = len(key) < len(set(found))
        if not key:
            return list(items)
        exact = [d for d in items if key in d["exact"]]
        if len(exact) == 1:
            return exact
        for floor in self.floors():
            if key in self._floor_keys(floor):
                return [d for d in items if d["floor"] == floor]
        matches = None
        for room in self.rooms():
            room_key = self.key(room)
            if key == room_key:
                matches = [d for d in items if d["room"] == room]
                break
            # "basement stairs": a room on one floor.
            floor = next((f for f in self.floors() if room_key < key and key - room_key in self._floor_keys(f)),
                         None)
            if floor is not None:
                matches = [d for d in items if d["room"] == room and d["floor"] == floor] or None
                if matches:
                    break
        if matches is None:
            for alias, rooms in self.room_aliases.items():
                if key == self.key(alias):
                    out = []
                    for room in rooms:
                        out += self._resolve_one(items, room, strict=False) or []
                    return out or None
            matches = [d for d in items if key <= d["all_words"]]
        if not matches:
            return None
        spread = list(dict.fromkeys(d["floor"] for d in matches))
        if strict and len(spread) > 1 and not every:
            raise self._ambiguous(text, matches, spread)
        return matches

    def resolve(self, text, *, strict=True, listing=False):
        """The devices a request names, in page order.

        ``text`` may list several targets ("kitchen, office" or "kitchen and
        office"). Raises :class:`NoMatch` or (when ``strict``) :class:`Ambiguous`.
        "All ..." group devices stand in for their floor's devices; for
        ``listing`` they are left out instead of their members.
        """
        items = self.items()
        found = self._resolve_one(items, text, strict=strict)
        if found is None:
            parts = [p for p in _SPLIT.split(text) if p.strip()]
            if len(parts) < 2:
                raise NoMatch(self.no_match_message(text))
            found = []
            for part in parts:
                got = self._resolve_one(items, part, strict=strict)
                if got is None:
                    raise NoMatch(self.no_match_message(part))
                found += got
        ids = {d["entity_id"] for d in found}
        groups = {d["floor"] for d in found if d["aggregate"]}
        if listing:
            return [d for d in items if not d["aggregate"] and (d["entity_id"] in ids or d["floor"] in groups)]
        return [d for d in items if d["entity_id"] in ids and (d["aggregate"] or d["floor"] not in groups)]

    def no_match_message(self, text):
        text = f"There are no {self.noun} called {text.strip()!r}. The floors are {', '.join(self.floors())}"
        rooms = self.rooms()
        if rooms:
            text += f"; the rooms are {', '.join(rooms)}"
        items = self.items()
        if self.list_limit is None or len(items) <= self.list_limit:
            text += f"; the {self.noun} are {', '.join(d['label'] for d in items)}"
        return text + "."
