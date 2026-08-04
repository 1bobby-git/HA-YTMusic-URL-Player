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

    def get_album(self, _browse_id: str):
        raise KeyError("album response has no contents")

    def get_watch_playlist(self, *args, **kwargs):
        raise KeyError("watch playlist response has no contents")


class _AlbumYTMusic(_FailingYTMusic):
    def get_album(self, _browse_id: str):
        return {
            "tracks": [
                {"id": "album-id", "title": "7"},
                {"title": "missing id"},
            ]
        }


class _AlbumBrowseYTMusic(_FailingYTMusic):
    def get_album_browse_id(self, _list_id: str):
        return "MPRE-browse-id"

    def get_album(self, _browse_id: str):
        return {
            "tracks": [
                {"setVideoId": "browse-set-id", "title": "Browse Track"},
                {"videoId": "", "title": "missing id"},
            ]
        }


class _WatchPlaylistYTMusic(_FailingYTMusic):
    def get_watch_playlist(self, *args, **kwargs):
        return {
            "tracks": [
                {"id": "watch-id", "title": "Watch Track", "artists": [{"name": "A"}]},
                "not a track",
            ]
        }


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
        self.extract_entries = [
            {
                "id": "bjjs-14horc",
                "title": "Track 1",
                "channel": "Artist 1",
            }
        ]

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
                    "entries": test_case.extract_entries
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
        self.module = module
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

    async def test_album_tracks_are_normalized_and_invalid_tracks_skipped(self) -> None:
        client = self.client_class(hass=object(), config={})
        client._yt = _AlbumYTMusic()

        tracks = await client.async_get_playlist_video_ids("MPRE-test-album")

        self.assertEqual(
            [
                {
                    "videoId": "album-id",
                    "title": "Track 7",
                    "artists": [],
                    "thumbnails": [],
                    "duration_seconds": None,
                }
            ],
            tracks,
        )

    async def test_album_browse_tracks_are_normalized_and_invalid_tracks_skipped(self) -> None:
        client = self.client_class(hass=object(), config={})
        client._yt = _AlbumBrowseYTMusic()

        tracks = await client.async_get_playlist_video_ids("OLAK5uy_test_album")

        self.assertEqual(
            [
                {
                    "videoId": "browse-set-id",
                    "title": "Browse Track",
                    "artists": [],
                    "thumbnails": [],
                    "duration_seconds": None,
                }
            ],
            tracks,
        )

    async def test_watch_playlist_tracks_are_normalized_and_invalid_tracks_skipped(self) -> None:
        client = self.client_class(hass=object(), config={})
        client._yt = _WatchPlaylistYTMusic()

        tracks = await client.async_get_playlist_video_ids("RD-test", seed_video_id="seed")

        self.assertEqual(
            [
                {
                    "videoId": "watch-id",
                    "title": "Watch Track",
                    "artists": [{"name": "A"}],
                    "thumbnails": [],
                    "duration_seconds": None,
                }
            ],
            tracks,
        )

    async def test_pytubefix_fallback_tracks_have_required_structure(self) -> None:
        class FakePlaylist:
            def __init__(self, _url: str) -> None:
                self.video_urls = [
                    "https://www.youtube.com/watch?v=pytube-id&list=test",
                    "https://youtu.be/pytube-short",
                    "https://www.youtube.com/playlist?list=invalid",
                ]

        self.module.PytubePlaylist = FakePlaylist
        client = self.client_class(hass=object(), config={})
        client._yt = _FailingYTMusic()

        tracks = await client.async_get_playlist_video_ids("fallback-list")

        self.assertEqual(
            [
                {
                    "videoId": "pytube-id",
                    "title": "Track 1",
                    "artists": [],
                    "thumbnails": [],
                    "duration_seconds": None,
                },
                {
                    "videoId": "pytube-short",
                    "title": "Track 2",
                    "artists": [],
                    "thumbnails": [],
                    "duration_seconds": None,
                },
            ],
            tracks,
        )

    async def test_yt_dlp_fallback_tracks_are_normalized_and_invalid_tracks_skipped(self) -> None:
        self.extract_entries = [
            {"id": "yt-dlp-id", "title": "3", "uploader": "Artist"},
            {"title": "missing id"},
        ]
        client = self.client_class(hass=object(), config={})
        client._yt = _FailingYTMusic()

        tracks = await client.async_get_playlist_video_ids("fallback-list")

        self.assertEqual(
            [
                {
                    "videoId": "yt-dlp-id",
                    "title": "Track 3",
                    "artists": [{"name": "Artist"}],
                    "thumbnails": [],
                    "duration_seconds": None,
                }
            ],
            tracks,
        )


if __name__ == "__main__":
    unittest.main()
