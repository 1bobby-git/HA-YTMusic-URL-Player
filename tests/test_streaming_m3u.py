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
    / "streaming.py"
)
MODULE_NAME = "custom_components.ytmusic_url_player.streaming_m3u_test"


class _Client:
    async def async_get_playlist_video_ids(self, _list_id: str, _seed_video_id=None):
        return [
            {
                "videoId": "duration-id",
                "title": "Timed Track",
                "artists": [{"name": "Artist"}],
                "duration": "3:45",
                "duration_seconds": 225,
            }
        ]


class _Request:
    query: dict[str, str] = {}


class StreamingM3UTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._saved_modules = {
            name: sys.modules.get(name)
            for name in (
                "homeassistant",
                "homeassistant.components",
                "homeassistant.components.http",
                "homeassistant.core",
                "homeassistant.helpers",
                "homeassistant.helpers.network",
                "pytubefix",
                "pytubefix.exceptions",
                "yt_dlp",
                "custom_components",
                "custom_components.ytmusic_url_player",
                "custom_components.ytmusic_url_player.const",
                "custom_components.ytmusic_url_player.ytmusic_client",
                MODULE_NAME,
            )
        }

        homeassistant = types.ModuleType("homeassistant")
        components = types.ModuleType("homeassistant.components")
        http = types.ModuleType("homeassistant.components.http")
        http.HomeAssistantView = object
        components.http = http
        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = object
        helpers = types.ModuleType("homeassistant.helpers")
        network = types.ModuleType("homeassistant.helpers.network")
        network.get_url = lambda _hass, prefer_external=False: "http://ha.local"
        helpers.network = network

        pytubefix = types.ModuleType("pytubefix")
        pytubefix.YouTube = object
        pytubefix_exceptions = types.ModuleType("pytubefix.exceptions")
        pytubefix_exceptions.BotDetection = Exception
        yt_dlp = types.ModuleType("yt_dlp")
        yt_dlp.YoutubeDL = object

        custom_components = types.ModuleType("custom_components")
        custom_components.__path__ = []
        integration_package = types.ModuleType("custom_components.ytmusic_url_player")
        integration_package.__path__ = []
        const = types.ModuleType("custom_components.ytmusic_url_player.const")
        const.DOMAIN = "ytmusic_url_player"
        const.CONF_PO_TOKEN = "po_token"
        const.CONF_VISITOR_DATA = "visitor_data"
        const.STREAM_CACHE_TTL_SECONDS = 600
        const.API_STREAM_PATH = "stream"
        const.API_M3U_PATH = "m3u"
        ytmusic_client = types.ModuleType("custom_components.ytmusic_url_player.ytmusic_client")
        ytmusic_client.YTMusicClient = object

        sys.modules.update(
            {
                "homeassistant": homeassistant,
                "homeassistant.components": components,
                "homeassistant.components.http": http,
                "homeassistant.core": core,
                "homeassistant.helpers": helpers,
                "homeassistant.helpers.network": network,
                "pytubefix": pytubefix,
                "pytubefix.exceptions": pytubefix_exceptions,
                "yt_dlp": yt_dlp,
                "custom_components": custom_components,
                "custom_components.ytmusic_url_player": integration_package,
                "custom_components.ytmusic_url_player.const": const,
                "custom_components.ytmusic_url_player.ytmusic_client": ytmusic_client,
            }
        )

        spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[MODULE_NAME] = module
        assert spec.loader is not None
        spec.loader.exec_module(module)
        self.view_class = module.YTMusicM3UView

    def tearDown(self) -> None:
        for name, original in self._saved_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original

    async def test_m3u_extinf_uses_colon_duration_seconds(self) -> None:
        hass = types.SimpleNamespace(
            data={"ytmusic_url_player": {"entry": {"ytmusic": _Client()}}}
        )
        response = await self.view_class(hass).get(_Request(), "playlist-id")

        self.assertIn("#EXTINF:225,Artist - Timed Track", response.text)


if __name__ == "__main__":
    unittest.main()
