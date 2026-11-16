# bdh-app-device-control

Black Diamond Hub app: the lodge Controls page (scenes, lights, blinds, fireplaces, Gemstone Lights) via Home Assistant. Moved out of
[BlackDiamondHub](https://github.com/blackdiamondlodge/BlackDiamondHub) and
installed into the hub through the `blackdiamondhub.plugins` entry point
(see [bdh-sdk](https://github.com/blackdiamondlodge/bdh-sdk)).

Page: `/device_control/` (homepage tile "Controls").

Home Assistant scenes appear on the first tab and as homepage quick
actions. The **Scenes to show** setting (`scenes_filter`, comma-separated
friendly names) shows only some of them; in-process the old env names
`BDH_DEVICE_CONTROL_SCENES_FILTER`, `BDH_SCENES_FILTER` and `SCENE_FILTER`
still work.

## Container (hub API 2)

Since 2.0.0 the app runs in its own container:

- permissions: `ha.read` and `ha.call` for exactly the domains/services the
  Controls page uses (switch, light, cover, scene, climate, number, select),
  plus `media` (the fireplace card's JS comes from HA's static files);
- `network: outbound` — Gemstone Lights is a cloud service (AWS Cognito +
  AppSync, HTTPS/WSS on 443). Its traffic goes through the supervisor's
  egress proxy: the app hands pygemstone an aiohttp session with
  `trust_env=True` so `HTTPS_PROXY` is honoured (boto3 honours it already);
- `lifecycle: always` (the Gemstone client keeps a background event loop);
- `memory_mb: 128`.

Settings to seed on the hub: `scenes_filter`, `gemstone_email` and the
secret `gemstone_password` (vault; previously `GEMSTONE_EMAIL` /
`GEMSTONE_PASSWORD` env). In the container these come from the hub through
the broker; hub environment variables are not visible to the app.

The Fireplace tab reads HA's device/entity registry over the websocket API,
which needs the broker's `ha.ws` grant. A manifest can't request `ha.ws`
yet, so until the hub grants it the Fireplace tab shows an error and the
fireplace homepage status/shortcut are hidden; everything else works.

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
