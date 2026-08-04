from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "ytmusic_url_player"
    / "text.py"
)
MODULE_NAME = "custom_components.ytmusic_url_player.text_auto_play_test"


class _Entry:
    entry_id = "entry-1"

    def __init__(self) -> None:
        self.data = {"name": "Original", "auto_play": True}
        self.options = {}


class TextAutoPlayTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._saved_modules = {
            name: sys.modules.get(name)
            for name in (
                "homeassistant",
                "homeassistant.components",
                "homeassistant.components.text",
                "homeassistant.config_entries",
                "homeassistant.core",
                "homeassistant.helpers",
                "homeassistant.helpers.device_registry",
                "custom_components",
                "custom_components.ytmusic_url_player",
                "custom_components.ytmusic_url_player.const",
                "custom_components.ytmusic_url_player.service",
                MODULE_NAME,
            )
        }
        self.played_urls: list[str] = []

        homeassistant = types.ModuleType("homeassistant")
        components = types.ModuleType("homeassistant.components")
        text_component = types.ModuleType("homeassistant.components.text")

        class TextEntity:
            def async_write_ha_state(self) -> None:
                self.wrote_state = True

        text_component.TextEntity = TextEntity
        components.text = text_component

        config_entries = types.ModuleType("homeassistant.config_entries")
        config_entries.ConfigEntry = object
        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = object
        helpers = types.ModuleType("homeassistant.helpers")
        device_registry = types.ModuleType("homeassistant.helpers.device_registry")
        device_registry.DeviceInfo = dict
        helpers.device_registry = device_registry

        custom_components = types.ModuleType("custom_components")
        custom_components.__path__ = []
        integration_package = types.ModuleType("custom_components.ytmusic_url_player")
        integration_package.__path__ = []
        const = types.ModuleType("custom_components.ytmusic_url_player.const")
        const.DOMAIN = "ytmusic_url_player"
        const.CONF_NAME = "name"
        const.CONF_AUTO_PLAY = "auto_play"
        const.DEFAULT_NAME = "YouTube Music URL Player"

        test_case = self
        service = types.ModuleType("custom_components.ytmusic_url_player.service")

        async def async_play_url(_hass, _entry, url: str, _target) -> None:
            test_case.played_urls.append(url)

        service.async_play_url = async_play_url

        sys.modules.update(
            {
                "homeassistant": homeassistant,
                "homeassistant.components": components,
                "homeassistant.components.text": text_component,
                "homeassistant.config_entries": config_entries,
                "homeassistant.core": core,
                "homeassistant.helpers": helpers,
                "homeassistant.helpers.device_registry": device_registry,
                "custom_components": custom_components,
                "custom_components.ytmusic_url_player": integration_package,
                "custom_components.ytmusic_url_player.const": const,
                "custom_components.ytmusic_url_player.service": service,
            }
        )

        spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[MODULE_NAME] = module
        assert spec.loader is not None
        spec.loader.exec_module(module)
        self.entity_class = module.YTMusicUrlText

    def tearDown(self) -> None:
        for name, original in self._saved_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original

    async def test_auto_play_uses_current_options_without_recreating_entity(self) -> None:
        entry = _Entry()
        entity = self.entity_class(hass=object(), entry=entry)

        entry.options = {"auto_play": False}
        await entity.async_set_value("https://music.youtube.com/watch?v=off")

        entry.options = {"auto_play": True}
        await entity.async_set_value("https://music.youtube.com/watch?v=on")

        self.assertEqual(["https://music.youtube.com/watch?v=on"], self.played_urls)


if __name__ == "__main__":
    unittest.main()
