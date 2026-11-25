from bdh_sdk import ALL_MODES, INFO, ON, Shortcut, Status

from .device_config import TABS
from .ha_client import get_all_states
from .scenes import activate_scene, get_scenes

SCENE_PREFIX = "scene-"


def _configured_lights():
    return {
        dev["entity_id"]
        for tab in TABS
        for devices in tab["devices"].values()
        for dev in devices
        if dev.get("type") == "light"
    }


def _lights_on(states):
    # Only lights shown in the app count, so AP LEDs and appliance lights
    # don't inflate the number.
    lights = _configured_lights()
    return sum(
        1 for s in states
        if s.get("entity_id") in lights and s.get("state") == "on"
    )


def status():
    lights = _lights_on(get_all_states())
    text = f"{lights} light{'s' if lights != 1 else ''} on" if lights else "All lights off"
    return Status(text, ON if lights else INFO)


def shortcuts():
    return [
        Shortcut(
            id=SCENE_PREFIX + scene["id"].removeprefix("scene."),
            title=scene["name"],
            icon=scene["icon"],
            order=10,
            modes=ALL_MODES,
        )
        for scene in get_scenes(get_all_states())
    ]


def run_shortcut(shortcut_id):
    if not shortcut_id.startswith(SCENE_PREFIX):
        raise ValueError(shortcut_id)
    scene_id = "scene." + shortcut_id.removeprefix(SCENE_PREFIX)
    if scene_id not in {s["id"] for s in get_scenes()}:
        raise ValueError(shortcut_id)
    activate_scene(scene_id)
    return None