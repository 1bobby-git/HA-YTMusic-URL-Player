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
MODULE_NAME = "custom_components.ytmusic_url_player.ytmusic_client_test"


class _EmptyPlaylist:
    def __init__(self, _url: str) -> None:
        self.video_urls: list[str] = []


class _FailingYTMusic:
    def get_playlist(self, _list_id: str, limit=None):
        raise KeyError("playlist response has no contents")


class PlaylistYtDlpFallbackTest(unittest.IsolatedAsyncioTestCase):
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
        self.captured_options: dict = {}

        homeassistant = types.ModuleType("homeassistant")
        homeassistant_core = types.ModuleType("homeassistant.core")
        homeassistant_core.HomeAssistant = object
        homeassistant.core = homeassistant_core

        ytmusicapi = types.ModuleType("ytmusicapi")
        ytmusicapi.YTMusic = object

        pytubefix = types.ModuleType("pytubefix")
        pytubefix.Playlist = _EmptyPlaylist

        test_case = self

        class FakeYoutubeDL:
            def __init__(self, options: dict) -> None:
                test_case.captured_options = options

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback) -> None:
                return None

            def extract_info(self, _url: str, download: bool = False):
                user_agent = self.captured_user_agent
                if "iPhone" in user_agent:
                    raise RuntimeError("Unable to recognize tab page")
                return {
                    "entries": [
                        {
                            "id": "bjjs-14horc",
                            "title": "Track 1",
                            "channel": "Artist 1",
                        }
                    ]
                }

            @property
            def captured_user_agent(self) -> str:
                return test_case.captured_options.get("http_headers", {}).get(
                    "User-Agent", ""
                )

        yt_dlp = types.ModuleType("yt_dlp")
        yt_dlp.YoutubeDL = FakeYoutubeDL

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
                "ytmusicapi": ytmusicapi,
                "pytubefix": pytubefix,
                "yt_dlp": yt_dlp,
                "custom_components": custom_components,
                "custom_components.ytmusic_url_player": integration_package,
                "custom_components.ytmusic_url_player.const": const,
            }
        )

        spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[MODULE_NAME] = module
        assert spec.loader is not None
        spec.loader.exec_module(module)
        self.client_class = module.YTMusicClient

    def tearDown(self) -> None:
        for name, original in self._saved_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original

    async def test_yt_dlp_playlist_fallback_uses_supported_default_headers(self) -> None:
        client = self.client_class(hass=object(), config={})
        client._yt = _FailingYTMusic()

        tracks = await client.async_get_playlist_video_ids(
            "RDCLAK5uy_mtQ5lds7IYeZ3TsZurHJX2w0CLMJ3w8Y4"
        )

        self.assertEqual(["bjjs-14horc"], [track["videoId"] for track in tracks])
        self.assertNotIn("http_headers", self.captured_options)

    async def test_pl_playlist_yt_dlp_fallback_uses_supported_default_headers(self) -> None:
        client = self.client_class(hass=object(), config={})
        client._yt = _FailingYTMusic()

        tracks = await client.async_get_playlist_video_ids("PL-test-playlist")

        self.assertEqual(["bjjs-14horc"], [track["videoId"] for track in tracks])
        self.assertNotIn("http_headers", self.captured_options)


if __name__ == "__main__":
    unittest.main()
