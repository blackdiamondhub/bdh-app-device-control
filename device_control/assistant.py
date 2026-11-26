"""Assistant tools: Home Assistant scenes and the Shades tab's blinds.

They mirror the Scenes and Shades tabs and the homepage scene shortcuts, which
every mode (guest, dashboard, owner) can use.
"""
import logging

from bdh_sdk import ALL_MODES
from bdh_sdk.tools import MAX_ENUM, Tool, ToolError

from . import blinds
from .ha_client import HA_ERRORS
from .scenes import activate_scene, get_scenes

logger = logging.getLogger(__name__)

LIST_SCENES = "list_scenes"
ACTIVATE_SCENE = "activate_scene"
LIST_BLINDS = "list_blinds"
SET_BLINDS = "set_blinds"

HA_DOWN = "Home Assistant isn't answering right now, so I can't reach the scenes. Try again in a minute."
NO_SCENES = "There are no scenes set up."
BLINDS_DOWN = "Home Assistant isn't answering right now, so I can't reach the blinds. Try again in a minute."
NO_POSITION = "Say how far open to set them: 0 is closed, 100 fully open."
ACTIONS = ("open", "close", "stop", "position")
VERBS = {"open": "Opening", "close": "Closing", "stop": "Stopping", "position": "Setting"}
#: Past this many blinds a confirmation names the floors, not every blind.
MAX_NAMED = 4


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
            description="Turn on one of the lodge's scenes, which sets the lights (and anything "
                        "else the scene covers) to a preset look, e.g. a movie or dinner scene. "
                        "Pick the scene whose name best matches what the guest asked for.",
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


def _join(parts):
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


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
    raise ToolError(f"Unknown tool {tool_id!r}")
