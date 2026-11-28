"""The Deck tab's heaters and the Fans tab's exhaust fans, for the assistant.

Both are plain on/off switches. Matching is shared with the blinds and lights
(:mod:`device_control.matching`): "deck heater", "patio heaters" and "outdoor
heaters" find the Deck Heaters; "powder room fan" finds that exhaust fan and
"bathroom fan" (several floors) asks which.

Devices flagged ``auto_off`` (the deck heaters) that a guest or dashboard
session turns on go off again after the ``heater_auto_off_minutes`` setting.
The deadline is kept in the app's state, so a restart doesn't lose it, and
:mod:`device_control.worker` turns the device off when it is due.
"""
import datetime as dt
import logging

from bdh_sdk.settings import app_setting
from bdh_sdk.storage import app_state

from .device_config import DECK_DEVICES, FAN_DEVICES
from .ha_client import HA_ERRORS, call_service, get_entity_states
from .matching import Ambiguous, Catalog, NoMatch  # noqa: F401

logger = logging.getLogger(__name__)

APP = "device_control"
AUTO_OFF_SETTING = "heater_auto_off_minutes"
DEFAULT_AUTO_OFF_MINUTES = 120
#: app_state key: entity_id -> ISO time it goes off.
AUTO_OFF_KEY = "auto_off"

GROUPS = {**DECK_DEVICES, **FAN_DEVICES}
# Words that never tell these devices apart. Not "heater"/"fan": they tell the two kinds apart.
DEVICE_WORDS = frozenset({"exhaust", "switch", "device", "power"})
FLOOR_ALIASES = {
    "Deck": ("deck", "patio", "outdoor", "outdoors", "outside", "exterior", "terrace"),
    "Upper Floor": ("upper floor", "upstairs", "top floor", "upper level"),
    "Main Floor": ("main floor", "main level", "ground floor"),
    "Basement": ("basement", "downstairs", "lower floor", "lower level"),
}
ROOM_ALIASES = {
    "heat": ("deck heaters",),
    "heating": ("deck heaters",),
    "deck heat": ("deck heaters",),
    "patio heat": ("deck heaters",),
    "outdoor heat": ("deck heaters",),
    "outside heat": ("deck heaters",),
    "heat lamp": ("deck heaters",),
}

CATALOG = Catalog("heaters or fans", GROUPS, device_words=DEVICE_WORDS,
                  floor_aliases=FLOOR_ALIASES, room_aliases=ROOM_ALIASES)
AUTO_OFF_IDS = frozenset(d["entity_id"] for devices in GROUPS.values() for d in devices if d.get("auto_off"))


def devices():
    """Every heater and fan as dicts in page order (``label`` is unique)."""
    return CATALOG.items()


def resolve(text, *, strict=True):
    return CATALOG.resolve(text, strict=strict)


def states(items):
    return get_entity_states([d["entity_id"] for d in items])


def is_on(state):
    return bool(state) and state.get("state") == "on"


def switch(device, on):
    """Turn ``device`` on or off; returns (ok, error)."""
    domain = device["entity_id"].split(".", 1)[0]
    return call_service(domain, "turn_on" if on else "turn_off", device["entity_id"])


# ---------------------------------------------------------------- auto-off

def auto_off_minutes():
    """Minutes a guest-on heater stays on; 0 means it isn't turned off."""
    try:
        value = int(app_setting(APP, AUTO_OFF_SETTING, DEFAULT_AUTO_OFF_MINUTES, cast=int))
    except (TypeError, ValueError):
        return DEFAULT_AUTO_OFF_MINUTES
    return max(0, value)


def _now(now=None):
    from django.utils import timezone

    return timezone.localtime(now or timezone.now())


def pending():
    """entity_id -> aware datetime it goes off."""
    raw = app_state(APP).get(AUTO_OFF_KEY) or {}
    return {eid: dt.datetime.fromisoformat(at) for eid, at in raw.items()}


def _save(due):
    if due:
        app_state(APP).set(AUTO_OFF_KEY, {eid: at.isoformat() for eid, at in due.items()})
    else:
        app_state(APP).delete(AUTO_OFF_KEY)


def schedule_off(entity_id, now=None):
    """Turn ``entity_id`` off after the setting's minutes; returns when, or None (no auto-off)."""
    minutes = auto_off_minutes()
    if not minutes:
        cancel_off(entity_id)
        return None
    at = _now(now) + dt.timedelta(minutes=minutes)
    due = pending()
    due[entity_id] = at
    _save(due)
    return at


def cancel_off(entity_id):
    due = pending()
    if due.pop(entity_id, None) is not None:
        _save(due)


def enforce_auto_off(now=None):
    """Turn off what's due; returns the entity ids turned off. Failures are retried next time."""
    due = pending()
    if not due:
        return []
    now = _now(now)
    done = []
    for eid, at in list(due.items()):
        if at > now:
            continue
        domain = eid.split(".", 1)[0]
        try:
            ok, err = call_service(domain, "turn_off", eid)
        except HA_ERRORS as exc:
            ok, err = False, exc
        if not ok:
            logger.warning("Auto-off of %s failed (%s); will retry", eid, err)
            continue
        logger.info("Auto-off: turned %s off", eid)
        due.pop(eid)
        done.append(eid)
    if done:
        _save(due)
    return done


def clock(value):
    """"9 PM", "9:40 PM" in local time."""
    value = _now(value)
    hour = value.hour % 12 or 12
    ampm = "AM" if value.hour < 12 else "PM"
    return f"{hour} {ampm}" if value.minute == 0 else f"{hour}:{value.minute:02d} {ampm}"
