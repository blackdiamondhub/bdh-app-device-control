"""
Tests for the device_control app.
"""

import json
import os
from unittest.mock import patch, MagicMock
from django.test import TestCase, RequestFactory, tag
from django.urls import NoReverseMatch, reverse
from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from .device_config import TABS, get_all_entity_ids
from .ha_client import get_entity_state, get_entity_states, call_service
from . import views

# The FILTERABLE_TABS set must stay in sync with the JS in the template.
FILTERABLE_TABS = {"lights", "shades"}


class DeviceConfigTests(TestCase):
    """Tests for device_config.py."""

    def test_tabs_not_empty(self):
        self.assertTrue(len(TABS) > 0)

    def test_each_tab_has_required_keys(self):
        for tab in TABS:
            self.assertIn("key", tab)
            self.assertIn("label", tab)
            self.assertIn("icon", tab)
            self.assertIn("devices", tab)

    def test_get_all_entity_ids_returns_set(self):
        ids = get_all_entity_ids()
        self.assertIsInstance(ids, set)
        self.assertTrue(len(ids) > 0)

    def test_all_entity_ids_have_dot(self):
        """Every entity_id should be in domain.object_id format."""
        for eid in get_all_entity_ids():
            self.assertIn(".", eid, f"Entity ID missing dot: {eid}")

    def test_no_duplicate_entity_ids_within_tab(self):
        """No tab should list the same entity_id twice."""
        for tab in TABS:
            seen = set()
            for _group, devices in tab["devices"].items():
                for dev in devices:
                    eid = dev["entity_id"]
                    self.assertNotIn(eid, seen, f"Duplicate {eid} in tab {tab['key']}")
                    seen.add(eid)


class HaClientTests(TestCase):
    """Tests for ha_client.py (mocked HTTP)."""

    def setUp(self):
        # The hub's provider reads HA from Settings (none in the test DB);
        # point bdh_sdk.ha at a fixed instance so the mocked HTTP path runs.
        from bdh_sdk import ha as sdk_ha

        class _Provider:
            def connection(self, instance=None):
                return ("http://ha.test:8123", "token")

            def instances(self):
                return [{"id": "ha", "name": "HA", "site": "", "default": True}]

        previous = sdk_ha._provider
        sdk_ha.set_provider(_Provider())
        self.addCleanup(sdk_ha.set_provider, previous)

    @patch("device_control.ha_client.requests.get")
    def test_get_entity_state_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "entity_id": "switch.test",
            "state": "on",
            "attributes": {"friendly_name": "Test"},
        }
        mock_get.return_value = mock_resp

        result = get_entity_state("switch.test")
        self.assertIsNotNone(result)
        self.assertEqual(result["state"], "on")

    @patch("device_control.ha_client.requests.get")
    def test_get_entity_state_failure(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        result = get_entity_state("switch.nonexistent")
        self.assertIsNone(result)

    @patch("device_control.ha_client.requests.get")
    def test_get_entity_states_filters(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"entity_id": "switch.a", "state": "on", "attributes": {}},
            {"entity_id": "switch.b", "state": "off", "attributes": {}},
            {"entity_id": "switch.c", "state": "on", "attributes": {}},
        ]
        mock_get.return_value = mock_resp

        result = get_entity_states(["switch.a", "switch.c"])
        self.assertEqual(len(result), 2)
        self.assertIn("switch.a", result)
        self.assertIn("switch.c", result)
        self.assertNotIn("switch.b", result)

    @patch("device_control.ha_client.requests.post")
    def test_call_service_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        success, error = call_service("switch", "turn_on", "switch.test")
        self.assertTrue(success)
        self.assertIsNone(error)

    @patch("device_control.ha_client.requests.post")
    def test_call_service_failure(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_post.return_value = mock_resp

        success, error = call_service("switch", "turn_on", "switch.test")
        self.assertFalse(success)
        self.assertIn("500", error)


class ViewTests(TestCase):
    """Tests for device_control views."""

    def test_main_page_renders(self):
        resp = self.client.get(reverse("device_control"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Controls")
        self.assertContains(resp, "dc-tab")

    def test_filter_bar_visible_on_initial_load(self):
        """The filter bar must not be hidden when the first tab is filterable."""
        first_tab_key = TABS[0]["key"]
        resp = self.client.get(reverse("device_control"))
        content = resp.content.decode()

        if first_tab_key in FILTERABLE_TABS:
            # Filter bar should NOT have the 'hidden' class
            self.assertNotIn(
                'dc-filter-bar hidden',
                content,
                "Filter bar is hidden on initial load but the first tab "
                f"('{first_tab_key}') is filterable — it should be visible.",
            )
        else:
            # Filter bar SHOULD have the 'hidden' class
            self.assertIn('dc-filter-bar hidden', content)

    def test_main_page_has_all_tabs(self):
        resp = self.client.get(reverse("device_control"))
        for tab in TABS:
            self.assertContains(resp, tab["label"])

    @patch("device_control.views.get_entity_states")
    def test_states_endpoint(self, mock_states):
        mock_states.return_value = {
            "switch.living_room_tv_socket_1": {
                "state": "on",
                "attributes": {"friendly_name": "Living Room TV Socket 1"},
            }
        }
        resp = self.client.get(reverse("device_control_states"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("switch.living_room_tv_socket_1", data)
        self.assertEqual(data["switch.living_room_tv_socket_1"]["state"], "on")

    def test_action_requires_post(self):
        resp = self.client.get(reverse("device_control_action"))
        self.assertEqual(resp.status_code, 405)

    @patch("device_control.views.call_service")
    def test_action_toggle_switch(self, mock_call):
        mock_call.return_value = (True, None)
        resp = self.client.post(
            reverse("device_control_action"),
            data='{"entity_id": "switch.living_room_tv_socket_1", "action": "on", "type": "switch"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        mock_call.assert_called_once_with("switch", "turn_on", "switch.living_room_tv_socket_1", extra_data=None)

    def test_action_rejects_unknown_entity(self):
        resp = self.client.post(
            reverse("device_control_action"),
            data='{"entity_id": "switch.evil_entity", "action": "on", "type": "switch"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_action_rejects_bad_json(self):
        resp = self.client.post(
            reverse("device_control_action"),
            data="not json",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_action_rejects_unknown_type(self):
        resp = self.client.post(
            reverse("device_control_action"),
            data='{"entity_id": "switch.living_room_tv_socket_1", "action": "on", "type": "thermostat"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    @patch("device_control.views.call_service")
    def test_action_cover_open(self, mock_call):
        mock_call.return_value = (True, None)
        resp = self.client.post(
            reverse("device_control_action"),
            data='{"entity_id": "cover.kitchen_left_window", "action": "open", "type": "cover"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        mock_call.assert_called_once_with("cover", "open_cover", "cover.kitchen_left_window", extra_data=None)

    @patch("device_control.views.call_service")
    def test_action_ha_error_returns_502(self, mock_call):
        mock_call.return_value = (False, "HA timeout")
        resp = self.client.post(
            reverse("device_control_action"),
            data='{"entity_id": "switch.living_room_tv_socket_1", "action": "off", "type": "switch"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 502)
        data = resp.json()
        self.assertFalse(data["ok"])


class FireplaceRemovedTests(TestCase):
    """The fireplace moved to its own app (bdh-app-fireplace); Controls must
    not show, route or serve it."""

    def test_no_fireplace_tab_panel_assets_or_routes(self):
        self.assertNotIn("fireplace", [t["key"] for t in TABS])
        content = self.client.get(reverse("device_control")).content.decode()
        for needle in ('id="panel-fireplace"', "switchTab('fireplace'", "fireplace.js",
                       "fireplace.css", "fpCard", "fitFireplace", "data-card-url"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, content)
        for name in ("device_control_fireplace_states", "device_control_fireplace_action",
                     "device_control_fireplace_card"):
            with self.subTest(name=name), self.assertRaises(NoReverseMatch):
                reverse(name)
        for path in ("api/fireplace/states/", "api/fireplace/action/", "api/fireplace/card.js"):
            with self.subTest(path=path):
                url = reverse("device_control") + path
                self.assertEqual(self.client.get(url).status_code, 404)


class GemstoneRemovedTests(TestCase):
    """Gemstone Lights moved to its own app; Controls must not show or route it."""

    def test_no_gemstone_tab_panel_assets_or_routes(self):
        self.assertNotIn("gemstone", [t["key"] for t in TABS])
        content = self.client.get(reverse("device_control")).content.decode().lower()
        self.assertNotIn("gemstone", content)
        for name in ("device_control_gemstone_states", "device_control_gemstone_action"):
            with self.subTest(name=name), self.assertRaises(NoReverseMatch):
                reverse(name)


@tag('selenium')
class DeviceControlShadesSliderTest(StaticLiveServerTestCase):
    """Ensure shade cards render a position slider that fits within the card."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from selenium import webdriver
        from tests.selenium_helpers import get_chrome_options
        cls.browser = webdriver.Chrome(options=get_chrome_options())
        cls.browser.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {
            'width': 1920,
            'height': 1080,
            'deviceScaleFactor': 1,
            'mobile': False,
        })

    @classmethod
    def tearDownClass(cls):
        cls.browser.quit()
        super().tearDownClass()

    def test_shade_slider_visible(self):
        """Each shade card must contain a visible position slider."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        self.browser.get(self.live_server_url + reverse("device_control"))

        # Click the Shades tab
        WebDriverWait(self.browser, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "dc-tab"))
        )
        for tab_btn in self.browser.find_elements(By.CLASS_NAME, "dc-tab"):
            if "Shades" in tab_btn.text:
                tab_btn.click()
                break

        # Wait for shade cards to appear
        WebDriverWait(self.browser, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".dc-cover-slider"))
        )

        # Check every shade card's slider
        cards = self.browser.find_elements(By.CSS_SELECTOR, "[data-type='cover']")
        self.assertTrue(len(cards) > 0, "No shade cards found")

        for card in cards:
            card_rect = card.rect
            card_right = card_rect['x'] + card_rect['width']

            sliders = card.find_elements(By.CSS_SELECTOR, ".dc-cover-slider")
            self.assertEqual(len(sliders), 1,
                             f"Expected 1 slider in card, found {len(sliders)}")

            slider = sliders[0]
            slider_rect = slider.rect
            slider_right = slider_rect['x'] + slider_rect['width']

            # Slider must not extend beyond the card
            self.assertLessEqual(
                slider_right, card_right + 1,
                f"Slider right edge ({slider_right}px) extends "
                f"beyond card right edge ({card_right}px)"
            )

            # Slider must have positive visible dimensions
            self.assertGreater(
                slider_rect['width'], 0,
                "Slider has zero width — not visible"
            )
            self.assertGreater(
                slider_rect['height'], 0,
                "Slider has zero height — not visible"
            )


class ScenesTests(TestCase):
    STATES = [
        {"entity_id": "scene.movie", "state": "x",
         "attributes": {"friendly_name": "Movie", "icon": "mdi:movie"}},
        {"entity_id": "scene.party", "state": "x",
         "attributes": {"friendly_name": "Party", "icon": "mdi:nope"}},
        {"entity_id": "light.a", "state": "on", "attributes": {"friendly_name": "A"}},
    ]

    def test_get_scenes_maps_icons_and_skips_other_entities(self):
        from device_control.scenes import DEFAULT_ICON, get_scenes
        self.assertEqual(get_scenes(self.STATES), [
            {"id": "scene.movie", "name": "Movie", "icon": "fa-solid fa-film"},
            {"id": "scene.party", "name": "Party", "icon": DEFAULT_ICON},
        ])

    def test_filter_reads_new_and_legacy_names(self):
        from device_control.scenes import get_scenes
        for var in ("BDH_DEVICE_CONTROL_SCENES_FILTER", "BDH_SCENES_FILTER", "SCENE_FILTER"):
            with self.subTest(var=var), patch.dict(os.environ, {var: " party ,other"}):
                self.assertEqual([s["id"] for s in get_scenes(self.STATES)], ["scene.party"])

    @patch("device_control.scenes.get_all_states")
    def test_scenes_api_lists_scenes(self, mock_states):
        mock_states.return_value = self.STATES
        resp = self.client.get(reverse("device_control_scenes"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([s["name"] for s in resp.json()["scenes"]], ["Movie", "Party"])

    @patch("device_control.scenes.get_all_states", side_effect=views.HAError("down"))
    def test_scenes_api_reports_ha_errors(self, _):
        resp = self.client.get(reverse("device_control_scenes"))
        self.assertEqual(resp.status_code, 502)

    @patch("device_control.scenes.call_service", return_value=(True, None))
    @patch("device_control.scenes.get_all_states")
    def test_activate_only_known_scenes(self, mock_states, mock_call):
        mock_states.return_value = self.STATES
        url = reverse("device_control_scene_action")
        for scene_id in ("scene.unknown", "light.a"):
            resp = self.client.post(url, json.dumps({"scene_id": scene_id}),
                                    content_type="application/json")
            self.assertEqual(resp.status_code, 400)
        mock_call.assert_not_called()
        resp = self.client.post(url, json.dumps({"scene_id": "scene.movie"}),
                                content_type="application/json")
        self.assertEqual(resp.json(), {"ok": True})
        mock_call.assert_called_once_with("scene", "turn_on", "scene.movie")

    def test_scenes_is_the_first_tab(self):
        self.assertEqual(TABS[0]["key"], "scenes")


class HomepageHookTests(TestCase):
    STATES = [
        {"entity_id": "climate.living", "state": "heat"},
        {"entity_id": "climate.bedroom", "state": "off"},
        {"entity_id": "climate.nest", "state": "heat"},
        {"entity_id": "light.a", "state": "on", "attributes": {}},
        {"entity_id": "light.b", "state": "on", "attributes": {}},
        {"entity_id": "light.c", "state": "off", "attributes": {}},
        {"entity_id": "light.group", "state": "on", "attributes": {"entity_id": ["light.a"]}},
        {"entity_id": "light.office_ap_led", "state": "on", "attributes": {}},
        {"entity_id": "switch.d", "state": "on", "attributes": {}},
    ]
    TABS = [{"devices": {"Room": [
        {"entity_id": "light.a", "type": "light"},
        {"entity_id": "light.b", "type": "light"},
        {"entity_id": "light.c", "type": "light"},
        {"entity_id": "switch.d", "type": "switch"},
    ]}}]

    def setUp(self):
        patcher = patch("device_control.homepage.get_all_states", return_value=self.STATES)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch("device_control.homepage.TABS", self.TABS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_status_counts_configured_lights_only(self):
        from device_control.homepage import status
        result = status()
        self.assertEqual(result.text, "2 lights on")
        self.assertEqual(result.level, "on")

    def test_status_when_all_lights_are_off(self):
        # A lit (Napoleon) fireplace climate entity no longer counts as "on".
        from device_control.homepage import status
        states = [{"entity_id": "climate.living", "state": "heat"},
                  {"entity_id": "light.a", "state": "off", "attributes": {}}]
        with patch("device_control.homepage.get_all_states", return_value=states):
            result = status()
        self.assertEqual(result.text, "All lights off")
        self.assertEqual(result.level, "info")

    def test_one_light_is_singular(self):
        from device_control.homepage import status
        states = [{"entity_id": "light.a", "state": "on", "attributes": {}}]
        with patch("device_control.homepage.get_all_states", return_value=states):
            self.assertEqual(status().text, "1 light on")

    def test_shortcuts_are_scenes_only(self):
        from device_control.homepage import shortcuts
        self.assertEqual(shortcuts(), [])
        states = ScenesTests.STATES + self.STATES
        with patch("device_control.homepage.get_all_states", return_value=states):
            items = shortcuts()
        self.assertEqual([(s.id, s.title) for s in items], [
            ("scene-movie", "Movie"), ("scene-party", "Party")])

    def test_fireplaces_off_shortcut_is_gone(self):
        from device_control.homepage import run_shortcut
        with self.assertRaises(ValueError):
            run_shortcut("fireplaces_off")

    @patch("device_control.scenes.call_service", return_value=(True, None))
    @patch("device_control.scenes.get_all_states", return_value=ScenesTests.STATES)
    def test_scene_shortcut_activates_only_known_scenes(self, _, mock_call):
        from device_control.homepage import run_shortcut
        self.assertIsNone(run_shortcut("scene-movie"))
        mock_call.assert_called_once_with("scene", "turn_on", "scene.movie")
        with self.assertRaises(ValueError):
            run_shortcut("scene-unknown")


class ManifestTests(TestCase):
    def test_hub_api_2_manifest(self):
        from device_control.plugin import spec
        m = spec.manifest()
        self.assertEqual(m["api_version"], 2)
        self.assertEqual((m["network"], m["lifecycle"], m["memory_mb"]), ("none", "always", 96))
        perms = m["permissions"]
        self.assertIn("ha.call:cover.set_cover_position", perms)
        self.assertIn("ha.call:scene.turn_on", perms)
        # The fireplace's grants went with it to bdh-app-fireplace.
        self.assertNotIn("media", perms)
        self.assertFalse([p for p in perms if p.split(":", 1)[-1].split(".", 1)[0]
                          in ("climate", "number", "select")])
        self.assertFalse([p for p in perms if p.endswith(":*") or p == "ha.read:*"])

    def test_only_the_scenes_setting(self):
        from device_control.plugin import spec
        self.assertEqual([s.key for s in spec.settings], ["scenes_filter"])


class HubFrameLayoutTests(TestCase):
    """The app renders inside the hub's iframe, below the hub navbar, so its
    CSS must not reserve space for that navbar (e.g. sticky ``top: 62px``,
    which left the tab bar floating over the scrolled controls)."""

    def test_no_hub_navbar_offsets(self):
        import pathlib
        import re
        root = pathlib.Path(__file__).resolve().parent
        pattern = re.compile(r"top\s*:\s*6[0-9]px|100vh\s*-\s*6[0-9]px")
        hits = []
        for path in list(root.glob("templates/**/*.html")) + list(root.glob("static/**/*.css")):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    hits.append(f"{path.relative_to(root)}:{n}: {line.strip()}")
        self.assertEqual(hits, [])


class BrokerTests(TestCase):
    """In its container the app reaches HA and its secrets through the hub broker."""

    STATES = [
        {"entity_id": "light.a", "state": "on", "attributes": {}},
        {"entity_id": "climate.living", "state": "heat", "attributes": {}},
        {"entity_id": "scene.movie", "state": "x", "attributes": {"friendly_name": "Movie"}},
    ]

    def setUp(self):
        from bdh_sdk.testing import FakeBroker

        self.broker = FakeBroker(
            grants=("settings.get", "secrets.get", "ha.get_all_states", "ha.get_entity_states",
                    "ha.call_service"),
            install=True, app_id="device_control")
        self.broker.start()
        self.addCleanup(self.broker.stop)
        self.broker.on("ha.get_all_states", lambda p: self.STATES)
        self.broker.on("ha.call_service", lambda p: [True, None])
        patcher = patch("device_control.homepage.TABS",
                        [{"devices": {"Room": [{"entity_id": "light.a", "type": "light"}]}}])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_action_calls_service_through_broker(self):
        eid = "switch.living_room_tv_socket_1"
        resp = self.client.post(reverse("device_control_action"),
                                data=json.dumps({"entity_id": eid, "action": "on", "type": "switch"}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        (call,) = self.broker.ops("ha.call_service")
        self.assertEqual(call["entity_id"], eid)

    def test_refused_call_is_a_502_not_a_crash(self):
        self.broker.grants = ["settings.get", "secrets.get", "ha.get_all_states"]
        eid = "switch.living_room_tv_socket_1"
        resp = self.client.post(reverse("device_control_action"),
                                data=json.dumps({"entity_id": eid, "action": "on", "type": "switch"}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 502)

    def test_status_never_mentions_fireplaces(self):
        # Even with Napoleon climate entities in HA (and ha.registry granted),
        # the homepage status is lights-only and the registry is never read.
        self.broker.grants.append("ha.registry")
        self.broker.registry = {
            "entities": [{"entity_id": "climate.living", "device_id": "d1", "platform": "napoleon",
                          "translation_key": None, "disabled_by": None}],
            "devices": [{"id": "d1", "name": "Living", "name_by_user": None}],
            "unit_system": {"temperature": "°C"},
        }
        from device_control.homepage import shortcuts, status
        result = status()
        self.assertEqual(result.text, "1 light on")
        self.assertNotIn("fireplace", result.text.lower())
        self.assertEqual([s.id for s in shortcuts()], ["scene-movie"])
        self.assertFalse(self.broker.ops("ha.registry"))


class AssistantToolTests(TestCase):
    """The assistant's scene tools, run the way the hub runs them (FakeBroker sessions)."""

    STATES = ScenesTests.STATES

    def setUp(self):
        from bdh_sdk import Stay
        from bdh_sdk.testing import FakeBroker

        self.broker = FakeBroker(grants=("settings.get", "ha.get_all_states", "ha.call_service", "tools.*"),
                                 install=True, app_id="device_control")
        self.broker.start()
        self.addCleanup(self.broker.stop)
        self.states = list(self.STATES)
        self.broker.on("ha.get_all_states", lambda p: self.states)
        self.service_result = [True, None]
        self.broker.on("ha.call_service", lambda p: self.service_result)
        self.broker.stay = Stay(guest="Smith")  # a voice session during a stay is in guest mode

    def session(self, mode="guest"):
        """Offer the app's tools for ``mode`` the way the hub does and open a session."""
        from bdh_sdk import tools as sdk_tools
        from device_control import assistant

        self.broker.assistant_tools.clear()
        for tool in assistant.tools(mode=mode):
            self.broker.add_tool(tool, lambda args, t=tool.id: assistant.run_tool(t, args, mode=mode))
        return sdk_tools.open_session()

    def call(self, name, args=None):
        from bdh_sdk import tools as sdk_tools
        return sdk_tools.call_tool(self.session(), name, args)

    def test_every_mode_gets_the_tools_with_the_scene_names(self):
        from bdh_sdk import ALL_MODES
        from device_control import assistant
        for mode in sorted(ALL_MODES):
            with self.subTest(mode=mode):
                tools = {t.id: t for t in assistant.tools(mode=mode)}
                self.assertEqual(list(tools), ["list_scenes", "activate_scene", "list_blinds", "set_blinds", "list_lights", "set_lights"])
                self.assertEqual(tools["list_scenes"].modes, ALL_MODES)
                self.assertTrue(tools["list_scenes"].readonly)
                self.assertEqual(tools["activate_scene"].modes, ALL_MODES)
                self.assertFalse(tools["activate_scene"].readonly)
                self.assertEqual(tools["activate_scene"].params["properties"]["scene"]["enum"],
                                 ["Movie", "Party"])

    def test_guest_session_lists_the_tools(self):
        from bdh_sdk import tools as sdk_tools
        listed = sdk_tools.list_tools(self.session())
        self.assertEqual([t["name"] for t in listed], ["activate_scene", "list_blinds", "list_lights", "list_scenes", "set_blinds", "set_lights"])

    def test_list_scenes(self):
        self.assertEqual(self.call("list_scenes"), {"ok": True, "result": "Scenes: Movie, Party."})

    def test_list_scenes_honours_the_filter(self):
        with patch("device_control.scenes.scene_filter", return_value=["party"]):
            self.assertEqual(self.call("list_scenes")["result"], "Scenes: Party.")
            from device_control import assistant
            activate = assistant.tools()[1]
            self.assertEqual(activate.params["properties"]["scene"]["enum"], ["Party"])

    def test_activate_scene(self):
        self.assertEqual(self.call("activate_scene", {"scene": "Movie"}),
                         {"ok": True, "result": "The Movie scene is on."})
        (call,) = self.broker.ops("ha.call_service")
        self.assertEqual((call["domain"], call["service"], call["entity_id"]), ("scene", "turn_on", "scene.movie"))

    def test_bad_arguments_never_reach_home_assistant(self):
        for args in ({}, {"scene": "Disco"}, {"scene": 3}, {"scene": "Movie", "room": "den"}):
            with self.subTest(args=args):
                answer = self.call("activate_scene", args)
                self.assertFalse(answer["ok"])
                self.assertIn("invalid arguments", answer["error"])
        self.assertEqual(self.broker.ops("ha.call_service"), [])

    def test_names_match_loosely_and_unknown_ones_list_the_scenes(self):
        from bdh_sdk.tools import ToolError
        from device_control.assistant import run_tool
        self.assertEqual(run_tool("activate_scene", {"scene": "  movie  scene"}), "The Movie scene is on.")
        self.assertEqual(run_tool("activate_scene", {"scene": "scene.party"}), "The Party scene is on.")
        with self.assertRaisesRegex(ToolError, "no scene called 'Disco'.*Movie, Party"):
            run_tool("activate_scene", {"scene": "Disco"})
        with self.assertRaises(ToolError):
            run_tool("nope", {})

    def test_failed_scene_is_reported(self):
        self.service_result = [False, "boom"]
        answer = self.call("activate_scene", {"scene": "Party"})
        self.assertEqual(answer, {"ok": False, "error": "The Party scene didn't start: Home Assistant reported a problem."})

    def test_no_scenes(self):
        self.states = [s for s in self.states if not s["entity_id"].startswith("scene.")]
        from device_control import assistant
        activate = assistant.tools()[1]
        self.assertNotIn("enum", activate.params["properties"]["scene"])
        self.assertEqual(self.call("list_scenes")["result"], assistant.NO_SCENES)
        self.assertEqual(self.call("activate_scene", {"scene": "Movie"})["error"], assistant.NO_SCENES)

    def test_home_assistant_down(self):
        from device_control import assistant
        patcher = patch("device_control.scenes.get_all_states", side_effect=views.HAError("down"))
        patcher.start()
        self.addCleanup(patcher.stop)
        tools = assistant.tools()
        self.assertEqual([t.id for t in tools], ["list_scenes", "activate_scene", "list_blinds", "set_blinds", "list_lights", "set_lights"])
        self.assertNotIn("enum", tools[1].params["properties"]["scene"])
        self.assertEqual(self.call("list_scenes"), {"ok": False, "error": assistant.HA_DOWN})
        self.assertEqual(self.call("activate_scene", {"scene": "Movie"}), {"ok": False, "error": assistant.HA_DOWN})

    def test_hooks_serialise(self):
        from bdh_sdk import hooks
        from device_control.plugin import spec
        listed = hooks.run(spec, "tools", mode="guest")
        self.assertEqual([t["id"] for t in listed], ["list_scenes", "activate_scene", "list_blinds", "set_blinds", "list_lights", "set_lights"])
        self.assertEqual(listed[1]["modes"], ["dashboard", "guest", "owner"])
        self.assertEqual(listed[3]["modes"], ["dashboard", "guest", "owner"])
        self.assertEqual(hooks.run(spec, "run_tool", tool_id="list_scenes", args={}, mode="guest"),
                         "Scenes: Movie, Party.")


class AssistantBlindToolTests(TestCase):
    """The assistant's blind tools: loose names, rooms, floors, positions, HA down."""

    def setUp(self):
        from bdh_sdk import Stay
        from bdh_sdk.testing import FakeBroker

        self.broker = FakeBroker(grants=("settings.get", "ha.get_all_states", "ha.get_entity_states",
                                         "ha.call_service", "tools.*"),
                                 install=True, app_id="device_control")
        self.broker.start()
        self.addCleanup(self.broker.stop)
        self.broker.stay = Stay(guest="Smith")
        self.broker.on("ha.get_all_states", lambda p: [])
        self.states = {
            "cover.kitchen_left_window": {"state": "open", "attributes": {"current_position": 100}},
            "cover.kitchen_right_window": {"state": "open", "attributes": {"current_position": 40}},
            "cover.living_room_large_window_shade": {"state": "closing", "attributes": {"current_position": 70}},
            "cover.living_room_small_window": {"state": "closed", "attributes": {"current_position": 0}},
            "cover.office_large_window_shades": {"state": "closed", "attributes": {}},
        }
        self.broker.on("ha.get_entity_states",
                       lambda p: {eid: dict(self.states[eid], entity_id=eid)
                                  for eid in p["entity_ids"] if eid in self.states})
        self.failing = set()
        self.broker.on("ha.call_service",
                       lambda p: [False, "boom"] if p["entity_id"] in self.failing else [True, None])

    def call(self, name, args=None, mode="guest"):
        from bdh_sdk import tools as sdk_tools
        from device_control import assistant

        self.broker.assistant_tools.clear()
        for tool in assistant.tools(mode=mode):
            self.broker.add_tool(tool, lambda a, t=tool.id: assistant.run_tool(t, a, mode=mode))
        return sdk_tools.call_tool(sdk_tools.open_session(), name, args)

    def moved(self):
        return [(c["service"], c["entity_id"], c.get("extra_data"))
                for c in self.broker.ops("ha.call_service")]

    def test_every_mode_gets_the_blind_tools(self):
        from bdh_sdk import ALL_MODES
        from device_control import assistant
        for mode in sorted(ALL_MODES):
            with self.subTest(mode=mode):
                tools = {t.id: t for t in assistant.tools(mode=mode)}
                self.assertEqual(tools["list_blinds"].modes, ALL_MODES)
                self.assertTrue(tools["list_blinds"].readonly)
                self.assertEqual(tools["set_blinds"].modes, ALL_MODES)
                self.assertFalse(tools["set_blinds"].readonly)
                self.assertEqual(tools["set_blinds"].params["required"], ["action", "blinds"])

    def test_every_blind_matches_its_own_name_with_or_without_device_words(self):
        # Regression (fireplace bug class): normalise both sides, so a suffix like
        # "Window"/"Shade" on the request or on the name never stops a match.
        from device_control import blinds
        for b in blinds.blinds():
            base = b["label"]
            for word in (" Window", " Shades", " Shade", " Roller Shade"):
                base = base.removesuffix(word)
            for text in (b["label"], f"the {b['label']} blinds", b["label"].lower(), base,
                         f"{base} shade", f"{base} window blinds", f"  the  {base.upper()}  "):
                with self.subTest(text=text):
                    self.assertEqual([x["entity_id"] for x in blinds.resolve(text)], [b["entity_id"]])

    def test_suffix_on_either_side(self):
        self.assertEqual(self.call("set_blinds", {"action": "close", "blinds": "living room large window shade"}),
                         {"ok": True, "result": "Closing the Living Room Large Window blind."})
        self.assertEqual(self.call("set_blinds", {"action": "open", "blinds": "Office Large blinds"})["result"],
                         "Opening the Office Large Window blind.")
        self.assertEqual(self.moved(), [("close_cover", "cover.living_room_large_window_shade", None),
                                        ("open_cover", "cover.office_large_window_shades", None)])

    def test_a_room_moves_its_blinds(self):
        self.assertEqual(self.call("set_blinds", {"action": "close", "blinds": "all the kitchen blinds"})["result"],
                         "Closing the Kitchen Left Window and Kitchen Right Window blinds.")
        self.assertEqual([e for _, e, _ in self.moved()],
                         ["cover.kitchen_left_window", "cover.kitchen_right_window"])

    def test_several_targets_in_one_call(self):
        result = self.call("set_blinds", {"action": "open", "blinds": "office small, kitchen left and the bbq deck"})
        self.assertEqual(result["result"],
                         "Opening the Kitchen Left Window, Office Small Window and BBQ Deck Roller Shade.")
        self.assertEqual([e for _, e, _ in self.moved()],
                         ["cover.kitchen_left_window", "cover.office_small_window", "cover.bbq_deck_roller_shade"])

    def test_position(self):
        result = self.call("set_blinds", {"action": "position", "position": 50, "blinds": "living room"})
        self.assertEqual(result["result"],
                         "Setting the Living Room Large Window and Living Room Small Window blinds to 50% open.")
        self.assertEqual(self.moved(), [
            ("set_cover_position", "cover.living_room_large_window_shade", {"position": 50}),
            ("set_cover_position", "cover.living_room_small_window", {"position": 50}),
        ])
        from device_control.assistant import NO_POSITION
        self.assertEqual(self.call("set_blinds", {"action": "position", "blinds": "kitchen"}),
                         {"ok": False, "error": NO_POSITION})
        self.assertFalse(self.call("set_blinds", {"action": "position", "position": 101, "blinds": "kitchen"})["ok"])
        self.assertEqual(len(self.moved()), 2)

    def test_floors_and_everything(self):
        self.assertEqual(self.call("set_blinds", {"action": "close", "blinds": "upstairs"})["result"],
                         "Closing 6 blinds on the Upper Floor.")
        self.broker.calls.clear()
        self.assertEqual(self.call("set_blinds", {"action": "stop", "blinds": "all"})["result"],
                         "Stopping all the blinds.")
        moved = [e for _, e, _ in self.moved()]
        # The deck's group cover moves the deck shades, so they aren't called one by one.
        self.assertIn("cover.all_deck_roller_shades", moved)
        self.assertNotIn("cover.left_deck_roller_shade", moved)
        self.assertEqual(len(moved), 18)
        self.broker.calls.clear()
        self.assertEqual(self.call("set_blinds", {"action": "close", "blinds": "deck"})["result"],
                         "Closing all the Deck Roller Shades.")

    def test_ambiguous_room_asks_and_moves_nothing(self):
        answer = self.call("set_blinds", {"action": "close", "blinds": "master bedroom"})
        self.assertFalse(answer["ok"])
        self.assertIn("more than one floor", answer["error"])
        self.assertIn("Basement", answer["error"])
        self.assertIn("Upper Floor", answer["error"])
        self.assertEqual(self.moved(), [])
        self.assertTrue(self.call("set_blinds", {"action": "close", "blinds": "upstairs master bedroom"})["ok"])
        self.assertEqual(len(self.moved()), 6)

    def test_unknown_name_lists_floors_and_blinds(self):
        answer = self.call("set_blinds", {"action": "open", "blinds": "garage door"})
        self.assertFalse(answer["ok"])
        self.assertIn("no blinds called 'garage door'", answer["error"])
        self.assertIn("Main Floor", answer["error"])
        self.assertIn("Kitchen Left Window", answer["error"])
        answer = self.call("set_blinds", {"action": "open", "blinds": "kitchen and garage"})
        self.assertIn("no blinds called 'garage'", answer["error"])
        self.assertEqual(self.moved(), [])

    def test_list_blinds(self):
        result = self.call("list_blinds", {"blinds": "great room"})["result"]
        self.assertEqual(result, "Main Floor: Kitchen Left Window open, Kitchen Right Window 40% open, "
                                 "Living Room Large Window closing, Living Room Small Window closed.")
        full = self.call("list_blinds")["result"]
        self.assertTrue(full.startswith("Basement: Game Area Small Window unknown"))
        self.assertIn("Office Large Window closed", full)
        self.assertIn("Deck / Exterior: BBQ Deck Roller Shade unknown", full)
        self.assertNotIn("All Deck", full)
        self.states["cover.kitchen_left_window"] = {"state": "closed", "attributes": {"current_position": 0}}
        self.states["cover.kitchen_right_window"] = {"state": "closed", "attributes": {}}
        self.assertEqual(self.call("list_blinds", {"blinds": "kitchen"})["result"],
                         "All closed. Main Floor: Kitchen Left Window closed, Kitchen Right Window closed.")

    def test_partial_failure_is_reported(self):
        self.failing = {"cover.kitchen_right_window"}
        self.assertEqual(self.call("set_blinds", {"action": "open", "blinds": "kitchen"})["result"],
                         "Opening the Kitchen Left Window blind. The Kitchen Right Window blind didn't respond.")
        self.failing = {"cover.kitchen_left_window", "cover.kitchen_right_window"}
        self.assertEqual(self.call("set_blinds", {"action": "open", "blinds": "kitchen"}),
                         {"ok": False, "error": "Home Assistant couldn't move the Kitchen Left Window and "
                                                "Kitchen Right Window blinds."})

    def test_home_assistant_down(self):
        from device_control import assistant
        self.broker.grants = ["settings.get", "tools.*"]  # every HA call is refused
        self.assertEqual([t.id for t in assistant.tools()][2:4], ["list_blinds", "set_blinds"])
        self.assertEqual(self.call("list_blinds"), {"ok": False, "error": assistant.BLINDS_DOWN})
        self.assertEqual(self.call("set_blinds", {"action": "close", "blinds": "kitchen"}),
                         {"ok": False, "error": assistant.BLINDS_DOWN})
        self.broker.grants = ["settings.get", "ha.get_entity_states", "tools.*"]
        self.states = {}  # HA answers with nothing
        self.assertEqual(self.call("list_blinds"), {"ok": False, "error": assistant.BLINDS_DOWN})


class AssistantLightToolTests(TestCase):
    """The assistant's light tools: rooms, generic names, floors, brightness, ambiguity, HA down."""

    def setUp(self):
        from bdh_sdk import Stay
        from bdh_sdk.testing import FakeBroker
        from device_control import lights

        self.broker = FakeBroker(grants=("settings.get", "ha.get_all_states", "ha.get_entity_states",
                                         "ha.call_service", "tools.*"),
                                 install=True, app_id="device_control")
        self.broker.start()
        self.addCleanup(self.broker.stop)
        self.broker.stay = Stay(guest="Smith")
        self.broker.on("ha.get_all_states", lambda p: [])
        dims = {"supported_color_modes": ["brightness"]}
        self.states = {d["entity_id"]: {"state": "off", "attributes": dict(dims)} for d in lights.lights()}
        self.states["light.hot_tub_light"]["attributes"] = {"supported_color_modes": ["onoff"]}
        self.states["switch.exterior_lower_deck_sconces"]["attributes"] = {}
        self.broker.on("ha.get_entity_states",
                       lambda p: {eid: dict(self.states[eid], entity_id=eid)
                                  for eid in p["entity_ids"] if eid in self.states})
        self.failing = set()
        self.broker.on("ha.call_service",
                       lambda p: [False, "boom"] if p["entity_id"] in self.failing else [True, None])

    def turn_on(self, *entity_ids, brightness=255):
        for eid in entity_ids:
            self.states[eid] = {"state": "on", "attributes": {"brightness": brightness,
                                                              "supported_color_modes": ["brightness"]}}

    def call(self, name, args=None, mode="guest"):
        from bdh_sdk import tools as sdk_tools
        from device_control import assistant

        self.broker.assistant_tools.clear()
        for tool in assistant.tools(mode=mode):
            self.broker.add_tool(tool, lambda a, t=tool.id: assistant.run_tool(t, a, mode=mode))
        return sdk_tools.call_tool(sdk_tools.open_session(), name, args)

    def switched(self):
        return [(c["domain"], c["service"], c["entity_id"], c.get("extra_data"))
                for c in self.broker.ops("ha.call_service")]

    def test_every_mode_gets_the_light_tools(self):
        from bdh_sdk import ALL_MODES
        from device_control import assistant
        for mode in sorted(ALL_MODES):
            with self.subTest(mode=mode):
                tools = {t.id: t for t in assistant.tools(mode=mode)}
                self.assertEqual(tools["list_lights"].modes, ALL_MODES)
                self.assertTrue(tools["list_lights"].readonly)
                self.assertEqual(tools["set_lights"].modes, ALL_MODES)
                self.assertFalse(tools["set_lights"].readonly)
                self.assertEqual(tools["set_lights"].params["required"], ["action", "lights"])
                self.assertIn("set_lights", tools["activate_scene"].description)

    def test_every_light_matches_its_own_name_with_or_without_device_words(self):
        # Regression (fireplace bug class): normalise both sides, so "lights"/"lamp"
        # on the request or on the name never stops a match.
        from device_control import lights
        labels = [d["label"] for d in lights.lights()]
        self.assertEqual(len(labels), len(set(labels)))
        for d in lights.lights():
            base = d["label"]
            for word in (" Lights", " Light", " Lamp"):
                base = base.removesuffix(word)
            for text in (d["label"], f"the {d['label']} lights", d["label"].lower(), base,
                         f"{base} light", f"{base} lamp", f"  the  {base.upper()}  "):
                with self.subTest(text=text):
                    self.assertEqual([x["entity_id"] for x in lights.resolve(text)], [d["entity_id"]])

    def test_a_room_switches_all_its_lights(self):
        self.assertEqual(self.call("set_lights", {"action": "off", "lights": "living room lights"}),
                         {"ok": True, "result": "The Living Room Main Lights are off."})
        self.assertEqual(self.call("set_lights", {"action": "off", "lights": "the kitchen lights"})["result"],
                         "The Kitchen lights are off.")
        self.assertEqual(self.switched(), [
            ("light", "turn_off", "light.living_room_main_lights", None),
            ("light", "turn_off", "light.kitchen_main_lights", None),
            ("light", "turn_off", "light.kitchen_island_pendants", None),
            ("light", "turn_off", "light.kitchen_shelf_lights", None),
        ])

    def test_generic_names_need_a_room(self):
        self.assertEqual(self.call("set_lights", {"action": "on", "lights": "kitchen island pendants"})["result"],
                         "The Kitchen Island Pendants are on.")
        self.assertEqual(self.call("set_lights", {"action": "on", "lights": "office main light"})["result"],
                         "The Office Main Lights are on.")
        answer = self.call("set_lights", {"action": "on", "lights": "main lights"})
        self.assertFalse(answer["ok"])
        self.assertIn("more than one floor", answer["error"])
        self.assertIn("Living Room Main Lights", answer["error"])
        self.assertEqual([e for _, _, e, _ in self.switched()],
                         ["light.kitchen_island_pendants", "light.office_main_lights"])

    def test_floors_and_everything(self):
        self.assertEqual(self.call("set_lights", {"action": "off", "lights": "all the lights upstairs"})["result"],
                         "The Upper Floor lights are off.")
        self.assertEqual(len(self.switched()), 10)
        self.broker.calls.clear()
        self.assertEqual(self.call("set_lights", {"action": "off", "lights": "all"})["result"],
                         "All the lights are off.")
        switched = self.switched()
        self.assertEqual(len(switched), 47)
        self.assertIn(("switch", "turn_off", "switch.exterior_lower_deck_sconces", None), switched)
        self.broker.calls.clear()
        self.assertEqual(self.call("set_lights", {"action": "on", "lights": "basement stairs"})["result"],
                         "The Basement Stairs lights are on.")
        self.assertEqual([e for _, _, e, _ in self.switched()],
                         ["light.stairs_downstairs_sconce_lights", "light.stairs_lower_step_lights"])

    def test_brightness(self):
        self.assertEqual(self.call("set_lights", {"action": "brightness", "brightness": 30,
                                                  "lights": "dining room chandelier"})["result"],
                         "The Dining Room Chandelier is at 30%.")
        self.assertEqual(self.call("set_lights", {"action": "on", "brightness": 50,
                                                  "lights": "hot tub and deck"})["result"],
                         "The Deck lights are at 50%. The Hot Tub Light can't dim, so it is just on.")
        self.assertEqual(self.call("set_lights", {"action": "brightness", "brightness": 0,
                                                  "lights": "office floor lamp"})["result"],
                         "The Office Floor Lamp is off.")
        self.assertEqual(self.switched(), [
            ("light", "turn_on", "light.dining_room_chandelier", {"brightness_pct": 30}),
            ("light", "turn_on", "light.exterior_deck_ceiling_lights", {"brightness_pct": 50}),
            ("light", "turn_on", "light.exterior_deck_sconce_lights", {"brightness_pct": 50}),
            ("light", "turn_on", "light.hot_tub_light", None),
            ("light", "turn_off", "light.office_table_lamp", None),
        ])
        from device_control.assistant import NO_BRIGHTNESS
        self.assertEqual(self.call("set_lights", {"action": "brightness", "lights": "kitchen"}),
                         {"ok": False, "error": NO_BRIGHTNESS})
        self.assertFalse(self.call("set_lights", {"action": "brightness", "brightness": 101, "lights": "kitchen"})["ok"])
        self.assertEqual(len(self.switched()), 5)

    def test_ambiguous_room_asks_and_switches_nothing(self):
        answer = self.call("set_lights", {"action": "on", "lights": "stairs light"})
        self.assertFalse(answer["ok"])
        for floor in ("Upper Floor", "Main Floor", "Basement"):
            self.assertIn(floor, answer["error"])
        self.turn_on("light.stairs_upper_step_lights", "light.stairs_lower_step_lights")
        self.assertIn("more than one floor", self.call("set_lights", {"action": "off", "lights": "stairs"})["error"])
        self.assertEqual(self.switched(), [])
        self.assertEqual(self.call("set_lights", {"action": "off", "lights": "all the stairs lights"})["result"],
                         "The Stairs lights are off.")
        self.assertEqual(len(self.switched()), 5)

    def test_turning_off_an_ambiguous_light_picks_the_one_that_is_on(self):
        # "There's another light on the stairs. Can you turn that one off?"
        self.turn_on("light.stairs_screen_accent_lights")
        self.assertEqual(self.call("set_lights", {"action": "off", "lights": "the stairs light"})["result"],
                         "The Stairs Screen Accent is off.")
        self.assertEqual(self.switched(), [("light", "turn_off", "light.stairs_screen_accent_lights", None)])

    def test_unknown_name_lists_floors_and_rooms(self):
        answer = self.call("set_lights", {"action": "off", "lights": "garage"})
        self.assertFalse(answer["ok"])
        self.assertIn("no lights called 'garage'", answer["error"])
        self.assertIn("Main Floor", answer["error"])
        self.assertIn("Living Room", answer["error"])
        self.assertIn("no lights called 'garage'",
                      self.call("set_lights", {"action": "off", "lights": "kitchen and garage"})["error"])
        self.assertEqual(self.switched(), [])

    def test_list_lights(self):
        self.assertEqual(self.call("list_lights")["result"], "All off.")
        self.turn_on("light.living_room_main_lights", brightness=102)
        self.turn_on("light.master_bedroom_chandelier")
        self.assertEqual(self.call("list_lights")["result"],
                         "2 of 47 on. Upper Floor: Master Bedroom Chandelier on at 100%. "
                         "Main Floor: Living Room Main Lights on at 40%. The rest are off.")
        self.assertEqual(self.call("list_lights", {"lights": "living room"})["result"],
                         "Living Room Main Lights: on at 40%.")
        self.assertEqual(self.call("list_lights", {"lights": "kitchen"})["result"],
                         "All off.")
        self.turn_on("light.kitchen_island_pendants")
        self.assertEqual(self.call("list_lights", {"lights": "kitchen"})["result"],
                         "Main Floor: Kitchen Main Lights off, Kitchen Island Pendants on at 100%, "
                         "Kitchen Shelf Lights off.")
        self.assertEqual(self.switched(), [])

    def test_partial_failure_is_reported(self):
        self.failing = {"light.kitchen_shelf_lights"}
        self.assertEqual(self.call("set_lights", {"action": "off", "lights": "kitchen"})["result"],
                         "The Kitchen Main Lights and Kitchen Island Pendants are off. "
                         "The Kitchen Shelf Lights didn't respond.")
        self.failing = {"light.living_room_main_lights"}
        self.assertEqual(self.call("set_lights", {"action": "off", "lights": "living room"}),
                         {"ok": False, "error": "Home Assistant couldn't switch the Living Room Main Lights."})

    def test_home_assistant_down(self):
        from device_control import assistant
        self.broker.grants = ["settings.get", "tools.*"]  # every HA call is refused
        self.assertEqual([t.id for t in assistant.tools()][4:], ["list_lights", "set_lights"])
        self.assertEqual(self.call("list_lights"), {"ok": False, "error": assistant.LIGHTS_DOWN})
        self.assertEqual(self.call("set_lights", {"action": "off", "lights": "kitchen"}),
                         {"ok": False, "error": assistant.LIGHTS_DOWN})
        self.broker.grants = ["settings.get", "ha.get_entity_states", "tools.*"]
        self.states = {}  # HA answers with nothing
        self.assertEqual(self.call("list_lights"), {"ok": False, "error": assistant.LIGHTS_DOWN})
