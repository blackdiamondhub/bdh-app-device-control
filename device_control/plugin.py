from bdh_sdk import PluginSpec, Setting, Tile
from bdh_sdk.plugins import LIFECYCLE_ALWAYS, NETWORK_OUTBOUND, SECRET

spec = PluginSpec(
    id="device_control",
    app="device_control",
    urls="device_control.urls",
    status="device_control.homepage.status",
    shortcuts="device_control.homepage.shortcuts",
    run_shortcut="device_control.homepage.run_shortcut",
    tiles=(
        Tile(
            title="Controls",
            url_name="device_control",
            icon="device_control/hub/icon.svg",
            section="lodge",
            subtitle="Lights, shades, fireplaces & more",
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
        Setting("gemstone_email", "Gemstone Lights email",
                help="Gemstone Lights cloud account for the Gemstone tab."),
        Setting("gemstone_password", "Gemstone Lights password", type=SECRET),
    ),
    api_version=2,
    # Lights/switches/shades tabs, scenes, and the Napoleon fireplace card
    # (climate + its switch/light/number/select entities).
    permissions=(
        "ha.read:switch.*",
        "ha.read:light.*",
        "ha.read:cover.*",
        "ha.read:scene.*",
        "ha.read:climate.*",
        "ha.read:number.*",
        "ha.read:select.*",
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
        "ha.call:climate.set_hvac_mode",
        "ha.call:climate.set_preset_mode",
        "ha.call:climate.set_temperature",
        "ha.call:climate.turn_off",
        "ha.call:number.set_value",
        "ha.call:select.select_option",
        # The fireplace card's JS is served from HA's /napoleon_static/.
        "media",
    ),
    # Gemstone Lights is a cloud service (AWS, HTTPS only); HA goes via the hub.
    network=NETWORK_OUTBOUND,
    # The Gemstone client keeps a logged-in session on a background loop thread.
    lifecycle=LIFECYCLE_ALWAYS,
    # aiohttp + boto3 (Cognito login) on top of Django.
    memory_mb=128,
)
