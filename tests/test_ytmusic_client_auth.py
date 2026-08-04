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
    / "ytmusic_client.py"
)
MODULE_NAME = "custom_components.ytmusic_url_player.ytmusic_client_auth_test"


AUTH_HEADERS = """
cookie
VISITOR_INFO1_LIVE=test; SID=test
x-goog-authuser
0
"""


class YTMusicClientAuthTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._saved_modules = {
            name: sys.modules.get(name)
            for name in (
                "homeassistant",
                "homeassistant.core",
                "ytmusicapi",
                "pytubefix",
                "yt_dlp",
                "custom_components",
                "custom_components.ytmusic_url_player",
                "custom_components.ytmusic_url_player.const",
                MODULE_NAME,
            )
        }

        homeassistant = types.ModuleType("homeassistant")
        homeassistant_core = types.ModuleType("homeassistant.core")
        homeassistant_core.HomeAssistant = object
        homeassistant.core = homeassistant_core

        pytubefix = types.ModuleType("pytubefix")
        pytubefix.Playlist = object

        yt_dlp = types.ModuleType("yt_dlp")
        yt_dlp.YoutubeDL = object

        custom_components = types.ModuleType("custom_components")
        custom_components.__path__ = []
        integration_package = types.ModuleType("custom_components.ytmusic_url_player")
        integration_package.__path__ = []
        const = types.ModuleType("custom_components.ytmusic_url_player.const")
        const.CONF_AUTH_FILE = "auth_file"

        sys.modules.update(
            {
                "homeassistant": homeassistant,
                "homeassistant.core": homeassistant_core,
                "pytubefix": pytubefix,
                "yt_dlp": yt_dlp,
                "custom_components": custom_components,
                "custom_components.ytmusic_url_player": integration_package,
                "custom_components.ytmusic_url_player.const": const,
            }
        )

    def tearDown(self) -> None:
        for name, original in self._saved_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original

    def _load_client_class(self, ytmusic_cls: type):
        ytmusicapi = types.ModuleType("ytmusicapi")
        ytmusicapi.YTMusic = ytmusic_cls
        sys.modules["ytmusicapi"] = ytmusicapi

        spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[MODULE_NAME] = module
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module.YTMusicClient

    async def test_auth_temp_file_is_removed_after_constructor_success(self) -> None:
        captured_path = ""

        class FakeYTMusic:
            def __init__(self, auth_path: str | None = None) -> None:
                nonlocal captured_path
                captured_path = auth_path or ""
                self.exists_during_init = Path(captured_path).exists()

        client_class = self._load_client_class(FakeYTMusic)
        client = client_class(hass=object(), config={"auth_file": AUTH_HEADERS})

        await client.async_init()

        self.assertTrue(client.yt.exists_during_init)
        self.assertFalse(Path(captured_path).exists())

    async def test_auth_temp_file_is_removed_after_constructor_failure(self) -> None:
        captured_path = ""

        class FailingYTMusic:
            def __init__(self, auth_path: str | None = None) -> None:
                nonlocal captured_path
                captured_path = auth_path or ""
                self.exists_during_init = Path(captured_path).exists()
                raise RuntimeError("constructor failed")

        client_class = self._load_client_class(FailingYTMusic)
        client = client_class(hass=object(), config={"auth_file": AUTH_HEADERS})

        with self.assertRaises(RuntimeError):
            await client.async_init()

        self.assertFalse(Path(captured_path).exists())


if __name__ == "__main__":
    unittest.main()
