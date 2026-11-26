"""Assistant tools: list and activate Home Assistant scenes.

They mirror the Scenes tab and the homepage scene shortcuts, which every mode
(guest, dashboard, owner) can use.
"""
import logging

from bdh_sdk import ALL_MODES
from bdh_sdk.tools import MAX_ENUM, Tool, ToolError

from .ha_client import HA_ERRORS
from .scenes import activate_scene, get_scenes

logger = logging.getLogger(__name__)

LIST_SCENES = "list_scenes"
ACTIVATE_SCENE = "activate_scene"

HA_DOWN = "Home Assistant isn't answering right now, so I can't reach the scenes. Try again in a minute."
NO_SCENES = "There are no scenes set up."


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
    raise ToolError(f"Unknown tool {tool_id!r}")
