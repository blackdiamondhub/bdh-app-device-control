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

The hub's assistant (voice/chat, bdh-sdk 0.46+ `tools` / `run_tool`) can use the scenes.
Both tools are offered in every mode (guest, dashboard and owner), the same as the
homepage scene shortcuts, and only see the scenes the **Scenes to show** setting allows.

| Tool | Read-only | Params | Does |
| --- | --- | --- | --- |
| `list_scenes` | yes | none | "Scenes: Movie, Dinner." |
| `activate_scene` | no | `scene` (string; an enum of the current scene names when HA answers) | Turns the scene on: "The Movie scene is on." |

`activate_scene` also accepts a name in any case, the `scene.` entity id, or a trailing
"scene"; an unknown name fails with a message listing the scenes. When Home Assistant is
down both tools are still offered and fail with "Home Assistant isn't answering right now".
Lights and blinds aren't tools yet.

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
