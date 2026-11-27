# bdh-app-device-control

Black Diamond Hub app: the lodge Controls page (scenes, lights, blinds) via Home Assistant. Moved out of
[BlackDiamondHub](https://github.com/blackdiamondhub/BlackDiamondHub) and
installed into the hub through the `blackdiamondhub.plugins` entry point
(see [bdh-sdk](https://github.com/blackdiamondhub/bdh-sdk)).

Page: `/device_control/` (homepage tile "Controls").

Home Assistant scenes appear on the first tab and as homepage quick
actions. The **Scenes to show** setting (`scenes_filter`, comma-separated
friendly names) shows only some of them; in-process the old env names
`BDH_DEVICE_CONTROL_SCENES_FILTER`, `BDH_SCENES_FILTER` and `SCENE_FILTER`
still work.

## Container (hub API 2)

Since 2.0.0 the app runs in its own container:

- permissions: `ha.read` and `ha.call` for exactly the domains/services the
  Controls page uses (switch, light, cover, scene);
- `network: none` — Home Assistant is reached through the hub broker;
- `lifecycle: always`, so the homepage lights status stays live;
- `memory_mb: 96`.

Gemstone Lights moved to its own app (`bdh-app-gemstone`) in 2.1.0; the
Gemstone tab and its `gemstone_email` / `gemstone_password` settings are gone.

The Napoleon fireplace moved to its own app (`bdh-app-fireplace`) in 2.2.0;
the Fireplace tab, its `api/fireplace/...` endpoints, the fireplace homepage
status/shortcut and the `climate` / `number` / `select` / `media`
permissions are gone.

Settings to seed on the hub: `scenes_filter`. In the container it comes from the hub through
the broker; hub environment variables are not visible to the app.

## Assistant tools

The hub's assistant (voice/chat, bdh-sdk 0.46+ `tools` / `run_tool`) can use the scenes,
the Shades tab's blinds and the Lights tab's lights. Every tool is offered in every mode
(guest, dashboard and owner), the same as those tabs and the homepage scene shortcuts. The scene
tools only see the scenes the **Scenes to show** setting allows.

| Tool | Read-only | Params | Does |
| --- | --- | --- | --- |
| `list_scenes` | yes | none | "Scenes: Movie, Dinner." |
| `activate_scene` | no | `scene` (string; an enum of the current scene names when HA answers) | Turns the scene on: "The Movie scene is on." |
| `list_blinds` | yes | `blinds` (optional string, as below) | "Main Floor: Kitchen Left Window open, Kitchen Right Window 40% open." |
| `set_blinds` | no | `action` (`open`/`close`/`stop`/`position`), `position` (0 closed – 100 open, for `position`), `blinds` (string) | "Closing the Kitchen Left Window and Kitchen Right Window blinds." |
| `list_lights` | yes | `lights` (optional string, as below) | "2 of 47 on. Main Floor: Living Room Main Lights on at 40%, Kitchen Island Pendants on at 100%. The rest are off." / "All off." |
| `set_lights` | no | `action` (`on`/`off`/`brightness`), `brightness` (0–100 %, for `brightness` or with `on`; 0 is off), `lights` (string) | "The Living Room Main Lights are off.", "The Upper Floor lights are off.", "The Dining Room Chandelier is at 30%." |

`activate_scene` also accepts a name in any case, the `scene.` entity id, or a trailing
"scene"; an unknown name fails with a message listing the scenes. When Home Assistant is
down all tools are still offered and fail with "Home Assistant isn't answering right now".

`blinds` is free text (`device_control/blinds.py`): a blind's name, a room ("kitchen",
"living room"), a floor (the Shades tab groups, plus "downstairs", "upstairs", "main",
"deck", "outside"), "great room" (kitchen + living room), "all", or several joined by
commas/"and". Request and names are normalised the same way (case, plurals, and words
like "the", "blind(s)", "shade(s)", "window", "roller" dropped on both sides). A room that
spans floors ("master bedroom") fails with a question listing the options unless the
request says "all"; an unknown name fails listing the floors and blinds. Names that repeat
on two floors are prefixed with the floor ("Basement Master Bedroom Large Window"). The
deck's "All Deck Roller Shades" group cover is used instead of the single deck shades when
a request covers them all, and `list_blinds` lists the single shades instead.

`lights` (`device_control/lights.py`) works the same way (the matching is shared in
`device_control/matching.py`) over the Lights tab, including its exterior lights and the
lower-deck sconces switch. Light names repeat ("Main Lights", "Chandelier"), so each light is
named "<room> <name>" ("Living Room Main Lights", "Dining Room Chandelier") and a room name
("living room lights") targets every light in that room. Floors are the tab's groups plus
"upstairs", "downstairs", "outside" (not plain "main", which is a light name); "basement stairs"
is a room on one floor; "great room", "lounge", "game room" and "entry" are aliases; "light(s)",
"lamp", "bulb" are dropped on both sides. A name spread over floors ("stairs", "main lights",
"chandelier") fails with a question unless the request says "all" — except that turning it
**off** switches off the ones that are on when they are all on one floor ("turn that stairs
light off"). Brightness uses `brightness_pct`; lights that can't dim (on/off colour mode,
the switch) are just turned on and the reply says so. `list_lights` names every light for
up to 8 lights and otherwise only those that aren't off. The scene tools' descriptions steer
the model to `set_lights` for switching or dimming lights and rooms, and to scenes only for
a named mood.

CI's `image` job (from bdh-sdk's `app-ci.yml`) locks the dependencies
against the hub's app runtime, builds the app's image and smoke-tests it
the way the supervisor runs it.

## Development

CI (`.github/workflows/ci.yml`) uses the reusable `app-ci.yml` from
bdh-sdk. It builds the wheel, installs it next to the hub, then runs
`hub_smoke`, the app tests and the selenium tests.

To release, bump `version` in `pyproject.toml`. When that lands on
`main`, `release.yml` tags it and publishes the wheel, and the release
notes include the hashed line for the hub's `sites/<site>/apps.txt`.
