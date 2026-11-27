"""Assistant tools: Home Assistant scenes, the Shades tab's blinds and the Lights tab's lights.

They mirror the Scenes, Shades and Lights tabs and the homepage scene
shortcuts, which every mode (guest, dashboard, owner) can use.
"""
import logging

from bdh_sdk import ALL_MODES
from bdh_sdk.tools import MAX_ENUM, Tool, ToolError

from . import blinds, lights
from .ha_client import HA_ERRORS
from .matching import join as _join
from .scenes import activate_scene, get_scenes

logger = logging.getLogger(__name__)

LIST_SCENES = "list_scenes"
ACTIVATE_SCENE = "activate_scene"
LIST_BLINDS = "list_blinds"
SET_BLINDS = "set_blinds"
LIST_LIGHTS = "list_lights"
SET_LIGHTS = "set_lights"

HA_DOWN = "Home Assistant isn't answering right now, so I can't reach the scenes. Try again in a minute."
NO_SCENES = "There are no scenes set up."
BLINDS_DOWN = "Home Assistant isn't answering right now, so I can't reach the blinds. Try again in a minute."
NO_POSITION = "Say how far open to set them: 0 is closed, 100 fully open."
ACTIONS = ("open", "close", "stop", "position")
VERBS = {"open": "Opening", "close": "Closing", "stop": "Stopping", "position": "Setting"}
#: Past this many blinds a confirmation names the floors, not every blind.
MAX_NAMED = 4
LIGHTS_DOWN = "Home Assistant isn't answering right now, so I can't reach the lights. Try again in a minute."
NO_BRIGHTNESS = "Say how bright to make them: 1 to 100 percent, or 0 for off."
LIGHT_ACTIONS = ("on", "off", "brightness")
#: Up to this many lights list_lights names each one, on or off; past it only those not off.
MAX_LISTED = 8


def _scenes():
    try:
        return get_scenes()
    except HA_ERRORS as exc:
        logger.warning("Scenes fetch for the assistant failed: %s", exc)
        raise ToolError(HA_DOWN) from None


def _names(scenes):
    """Scene names in order, without duplicates."""
    return list(dict.fromkeys(s["name"] for s in scenes))


def _scene_param(scenes):
    param = {"type": "string",
             "description": "The scene's name, exactly as list_scenes gives it."}
    names = _names(scenes)
    if 0 < len(names) <= MAX_ENUM:
        param["enum"] = names
    return param


def _blinds_param(required):
    return {"type": "string",
            "description": "Which blinds, in the guest's words: a blind's name, a room (kitchen, living "
                           "room, office...), a floor (basement, main floor, upstairs, deck), 'all', or "
                           "several separated by commas. Map 'here' or 'this room' to the room this "
                           "screen is in; if it could mean different rooms, ask first."
                           + ("" if required else " Leave it out for every blind.")}


def _lights_param(required):
    return {"type": "string",
            "description": "Which lights, in the guest's words: a light's name (e.g. kitchen island "
                           "pendants, dining room chandelier), a room (living room, kitchen, stairs...), "
                           "a floor (upstairs, main floor, downstairs/basement, outside), 'all', or "
                           "several separated by commas. Map 'here' or 'this room' to the room this "
                           "screen is in; if it could mean different rooms, ask first."
                           + ("" if required else " Leave it out for every light.")}


def tools(mode=None):
    try:
        scenes = get_scenes()
    except HA_ERRORS:
        # Still offer the tools; running them says Home Assistant is down.
        scenes = []
    return [
        Tool(
            id=LIST_SCENES,
            title="List scenes",
            description="List the lodge's lighting scenes (Home Assistant scenes) by name. "
                        "Use it to answer which scenes or moods there are.",
            modes=ALL_MODES,
            readonly=True,
        ),
        Tool(
            id=ACTIVATE_SCENE,
            title="Activate scene",
            description="Turn on a named lighting scene (a preset look such as movie or dinner); pick "
                        "the scene whose name best matches. Not for switching, dimming or turning off "
                        "particular lights or rooms (use set_lights), and never to turn lights off "
                        "unless the guest asked for that scene.",
            params={"type": "object", "properties": {"scene": _scene_param(scenes)},
                    "required": ["scene"]},
            modes=ALL_MODES,
        ),
        Tool(
            id=LIST_BLINDS,
            title="List blinds",
            description="List the lodge's blinds and shades by floor with whether each is open, "
                        "closed, partly open (percent) or moving. Use it to answer whether blinds "
                        "are open and to learn their names.",
            params={"type": "object", "properties": {"blinds": _blinds_param(False)}},
            modes=ALL_MODES,
            readonly=True,
        ),
        Tool(
            id=SET_BLINDS,
            title="Move blinds",
            description="Open, close or stop blinds and shades, or set how far open they are "
                        "(position, 0 closed to 100 fully open; halfway is 50). Works on one blind, "
                        "several, a room, a floor or all of them.",
            params={"type": "object", "properties": {
                "action": {"type": "string", "enum": list(ACTIONS),
                           "description": "open, close, stop, or position to set how far open"},
                "position": {"type": "integer", "minimum": 0, "maximum": 100,
                             "description": "Percent open for action position: 0 closed, 100 fully open"},
                "blinds": _blinds_param(True),
            }, "required": ["action", "blinds"]},
            modes=ALL_MODES,
        ),
        Tool(
            id=LIST_LIGHTS,
            title="List lights",
            description="List the lodge's lights by floor: on (with brightness %) or off. Use it to "
                        "answer which lights are on and to learn light names; with many lights it "
                        "names only those that are on, so filter by room or floor to hear them all.",
            params={"type": "object", "properties": {"lights": _lights_param(False)}},
            modes=ALL_MODES,
            readonly=True,
        ),
        Tool(
            id=SET_LIGHTS,
            title="Switch lights",
            description="Turn lights on or off or dim them to a percent: one light, several, a room "
                        "('living room lights'), a floor or all. Use this, not activate_scene, "
                        "whenever the guest asks to switch or dim lights; scenes are only for a "
                        "named mood such as movie or dinner.",
            params={"type": "object", "properties": {
                "action": {"type": "string", "enum": list(LIGHT_ACTIONS),
                           "description": "on, off, or brightness to dim/brighten to a percentage"},
                "brightness": {"type": "integer", "minimum": 0, "maximum": 100,
                               "description": "Percent brightness for action brightness (or on): "
                                              "1 dimmest, 100 full; 0 is off"},
                "lights": _lights_param(True),
            }, "required": ["action", "lights"]},
            modes=ALL_MODES,
        ),
    ]


def _find(scenes, wanted):
    key = " ".join(wanted.split()).casefold()
    if key.endswith(" scene"):
        key = key.removesuffix(" scene")
    for scene in scenes:
        names = {scene["name"].casefold(), scene["id"].casefold(),
                 scene["id"].removeprefix("scene.").casefold()}
        if key in names:
            return scene
    return None


def _targets(text, **kwargs):
    try:
        return blinds.resolve(text, **kwargs)
    except (blinds.NoMatch, blinds.Ambiguous) as exc:
        raise ToolError(str(exc)) from None


def _named(items):
    """"the Kitchen Left Window and Kitchen Right Window blinds", "all the Deck Roller Shades"."""
    parts = [f"all the {b['name'].removeprefix(blinds.AGGREGATE_PREFIX)}" for b in items if b["aggregate"]]
    labels = [b["label"] for b in items if not b["aggregate"]]
    if labels:
        noun = "" if labels[-1].casefold().endswith(("shade", "shades", "blind", "blinds")) else (
            " blinds" if len(labels) > 1 else " blind")
        parts.insert(0, "the " + _join(labels) + noun)
    return _join(parts)


def _phrase(items):
    """How a confirmation names ``items``."""
    everything = blinds.resolve("all")
    if {b["entity_id"] for b in items} == {b["entity_id"] for b in everything}:
        return "all the blinds"
    if len(items) <= MAX_NAMED:
        return _named(items)
    floors = list(dict.fromkeys(b["floor"] for b in items))
    return f"{len(items)} blinds on the {_join(floors)}"


def _list_blinds(args):
    items = _targets(args.get("blinds") or "all", strict=False, listing=True)
    try:
        states = blinds.states(items)
    except HA_ERRORS as exc:
        logger.warning("Blind states for the assistant failed: %s", exc)
        raise ToolError(BLINDS_DOWN) from None
    if not states:
        raise ToolError(BLINDS_DOWN)
    texts = {b["entity_id"]: blinds.state_text(states.get(b["entity_id"])) for b in items}
    lines = []
    for floor in dict.fromkeys(b["floor"] for b in items):
        lines.append(f"{floor}: " + ", ".join(f"{b['label']} {texts[b['entity_id']]}"
                                             for b in items if b["floor"] == floor) + ".")
    kinds = set(texts.values())
    if len(items) > 1 and len(kinds) == 1:
        lines.insert(0, f"All {next(iter(kinds))}.")
    return " ".join(lines)


def _set_blinds(args):
    action = args["action"]
    position = args.get("position")
    if action == "position" and position is None:
        raise ToolError(NO_POSITION)
    items = _targets(args["blinds"])
    failed = []
    for b in items:
        try:
            ok, err = blinds.move(b, action, position)
        except HA_ERRORS as exc:
            logger.warning("Blind %s %s failed: %s", b["entity_id"], action, exc)
            raise ToolError(BLINDS_DOWN) from None
        if not ok:
            logger.warning("Blind %s %s failed: %s", b["entity_id"], action, err)
            failed.append(b)
    if len(failed) == len(items):
        raise ToolError(f"Home Assistant couldn't move {_named(items)}.")
    moved = [b for b in items if b not in failed]
    where = f" to {position}% open" if action == "position" else ""
    text = f"{VERBS[action]} {_phrase(moved)}{where}."
    if failed:
        text += f" {_named(failed)[:1].upper()}{_named(failed)[1:]} didn't respond."
    return text


def _cap(text):
    return text[:1].upper() + text[1:]


def _plural(label):
    last = label.split()[-1].casefold()
    return last.endswith("s") and not last.endswith("ss")


def _light_names(items):
    """"the Kitchen Island Pendants and Office Floor Lamp", and whether that's plural."""
    labels = [d["label"] for d in items]
    return "the " + _join(labels), len(labels) > 1 or _plural(labels[0])


def _light_phrase(items):
    """How a confirmation names ``items`` (whole floors and rooms by name), and whether it's plural."""
    every = lights.lights()
    ids = {d["entity_id"] for d in items}
    if ids == {d["entity_id"] for d in every}:
        return "all the lights", True
    groups, rest = [], list(items)
    for floor in lights.floors():
        members = {d["entity_id"] for d in every if d["floor"] == floor}
        if members and members <= ids:
            groups.append(floor)
            rest = [d for d in rest if d["floor"] != floor]
    for room in dict.fromkeys(d["room"] for d in rest):
        members = [d for d in every if d["room"] == room]
        if len(members) > 1 and all(m["entity_id"] in ids for m in members):
            groups.append(room)
            rest = [d for d in rest if d["room"] != room]
            continue
        for floor in dict.fromkeys(m["floor"] for m in members):
            part = [m for m in members if m["floor"] == floor]
            if len(part) > 1 and all(m["entity_id"] in ids for m in part):
                groups.append(f"{floor} {room}")
                rest = [d for d in rest if not (d["room"] == room and d["floor"] == floor)]
    if len(groups) + len(rest) > MAX_NAMED:
        floors = list(dict.fromkeys(d["floor"] for d in items))
        return f"{len(items)} lights on the {_join(floors)}", True
    parts = ["the " + _join(groups) + " lights"] if groups else []
    if rest:
        named, plural = _light_names(rest)
        parts.append(named)
    return _join(parts), bool(groups) or plural


def _light_states(items):
    try:
        states = lights.states(items)
    except HA_ERRORS as exc:
        logger.warning("Light states for the assistant failed: %s", exc)
        raise ToolError(LIGHTS_DOWN) from None
    if not states:
        raise ToolError(LIGHTS_DOWN)
    return states


def _list_lights(args):
    try:
        items = lights.resolve(args.get("lights") or "all", strict=False)
    except lights.NoMatch as exc:
        raise ToolError(str(exc)) from None
    states = _light_states(items)
    texts = {d["entity_id"]: lights.state_text(states.get(d["entity_id"])) for d in items}
    if len(items) == 1:
        return f"{items[0]['label']}: {texts[items[0]['entity_id']]}."
    if all(t == "off" for t in texts.values()):
        return "All off."
    shown = items if len(items) <= MAX_LISTED else [d for d in items if texts[d["entity_id"]] != "off"]
    lines = [f"{floor}: " + ", ".join(f"{d['label']} {texts[d['entity_id']]}"
                                       for d in shown if d["floor"] == floor) + "."
             for floor in dict.fromkeys(d["floor"] for d in shown)]
    lit = sum(1 for d in items if lights.is_on(states.get(d["entity_id"])))
    if lit == len(items):
        lines.insert(0, "All on.")
    elif len(shown) < len(items):
        lines.insert(0, f"{lit} of {len(items)} on.")
        lines.append("The rest are off.")
    return " ".join(lines)


def _set_lights(args):
    action, level = args["action"], args.get("brightness")
    if action == "brightness" and level is None:
        raise ToolError(NO_BRIGHTNESS)
    on = action != "off" and level != 0
    if not on:
        level = None
    try:
        items = lights.resolve(args["lights"])
    except lights.NoMatch as exc:
        raise ToolError(str(exc)) from None
    except lights.Ambiguous as exc:
        # Turning off is unambiguous when only one floor's matches are on.
        if on:
            raise ToolError(str(exc)) from None
        states = _light_states(exc.matches)
        lit = [d for d in exc.matches if lights.is_on(states.get(d["entity_id"]))]
        if not lit:
            return "They're already off."
        if len({d["floor"] for d in lit}) > 1:
            raise ToolError(str(exc)) from None
        items = lit
    states = _light_states(items) if level is not None else {}
    failed, plain = [], []
    for d in items:
        dim = level is not None and lights.dimmable(d, states.get(d["entity_id"]))
        try:
            ok, err = lights.switch(d, on, level if dim else None)
        except HA_ERRORS as exc:
            logger.warning("Light %s %s failed: %s", d["entity_id"], action, exc)
            raise ToolError(LIGHTS_DOWN) from None
        if not ok:
            logger.warning("Light %s %s failed: %s", d["entity_id"], action, err)
            failed.append(d)
        elif level is not None and not dim:
            plain.append(d)
    if len(failed) == len(items):
        raise ToolError(f"Home Assistant couldn't switch {_light_phrase(items)[0]}.")
    done = [d for d in items if d not in failed]
    dimmed = [d for d in done if d not in plain]
    if dimmed:
        subject, plural = _light_phrase(dimmed)
        state = f"at {level}%" if level is not None else ("on" if on else "off")
        text = f"{_cap(subject)} {'are' if plural else 'is'} {state}."
        if plain:
            named, plural = _light_names(plain)
            text += f" {_cap(named)} can't dim, so {'they are' if plural else 'it is'} just on."
    else:
        named, plural = _light_names(plain)
        text = f"{_cap(named)} {'are' if plural else 'is'} on; {'they' if plural else 'it'} can't dim."
    if failed:
        named, plural = _light_names(failed)
        text += f" {_cap(named)} didn't respond."
    return text


def run_tool(tool_id, args, mode=None):
    if tool_id == LIST_SCENES:
        names = _names(_scenes())
        if not names:
            return NO_SCENES
        return "Scenes: " + ", ".join(names) + "."
    if tool_id == ACTIVATE_SCENE:
        scenes = _scenes()
        if not scenes:
            raise ToolError(NO_SCENES)
        scene = _find(scenes, args["scene"])
        if scene is None:
            raise ToolError(f"There's no scene called {args['scene']!r}. "
                            f"The scenes are: {', '.join(_names(scenes))}.")
        try:
            activate_scene(scene["id"])
        except (*HA_ERRORS, RuntimeError) as exc:
            logger.warning("Scene %s failed: %s", scene["id"], exc)
            raise ToolError(f"The {scene['name']} scene didn't start: Home Assistant reported a problem.") from None
        return f"The {scene['name']} scene is on."
    if tool_id == LIST_BLINDS:
        return _list_blinds(args)
    if tool_id == SET_BLINDS:
        return _set_blinds(args)
    if tool_id == LIST_LIGHTS:
        return _list_lights(args)
    if tool_id == SET_LIGHTS:
        return _set_lights(args)
    raise ToolError(f"Unknown tool {tool_id!r}")
