from bdh_sdk import PluginSpec, Setting, Tile
from bdh_sdk.plugins import LIFECYCLE_ALWAYS, NETWORK_NONE

spec = PluginSpec(
    id="device_control",
    app="device_control",
    urls="device_control.urls",
    status="device_control.homepage.status",
    shortcuts="device_control.homepage.shortcuts",
    run_shortcut="device_control.homepage.run_shortcut",
    # The assistant can list and activate scenes and list and move the blinds.
    tools="device_control.assistant.tools",
    run_tool="device_control.assistant.run_tool",
    tiles=(
        Tile(
            title="Controls",
            url_name="device_control",
            icon="device_control/hub/icon.svg",
            section="lodge",
            subtitle="Lights, shades, scenes & more",
            order=10,
        ),
    ),
    settings=(
        Setting(
            "scenes_filter",
            "Scenes to show",
            help="Comma-separated Home Assistant scene names for the Scenes tab "
                 "and homepage shortcuts. Empty shows every scene.",
        ),
    ),
    api_version=2,
    # Lights/switches/shades tabs and scenes.
    permissions=(
        "ha.read:switch.*",
        "ha.read:light.*",
        "ha.read:cover.*",
        "ha.read:scene.*",
        "ha.call:switch.turn_on",
        "ha.call:switch.turn_off",
        "ha.call:switch.toggle",
        "ha.call:light.turn_on",
        "ha.call:light.turn_off",
        "ha.call:light.toggle",
        "ha.call:cover.open_cover",
        "ha.call:cover.close_cover",
        "ha.call:cover.stop_cover",
        "ha.call:cover.set_cover_position",
        "ha.call:scene.turn_on",
    ),
    # Home Assistant is reached through the hub broker; nothing else is needed.
    network=NETWORK_NONE,
    # Keeps the homepage lights status live (on_demand would let it go
    # hours stale while the app sleeps).
    lifecycle=LIFECYCLE_ALWAYS,
    memory_mb=96,
)
