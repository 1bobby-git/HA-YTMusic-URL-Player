from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "ytmusic_url_player"
    / "streaming.py"
)
MODULE_NAME = "custom_components.ytmusic_url_player.streaming_m3u_test"
VIDEO_ID = "abcdefghijk"


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


class _Request(dict):
    """aiohttp requests are mappings; Home Assistant stores the auth result in them."""

    def __init__(self, *, authenticated: bool = False, query=None) -> None:
        super().__init__()
        if authenticated:
            self["ha_authenticated"] = True
        self.query = query or {}
        self.remote = "192.0.2.10"


class StreamingM3UTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._saved_modules = {
            name: sys.modules.get(name)
            for name in (
                "aiohttp",
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

        aiohttp = types.ModuleType("aiohttp")

        class Response:
            def __init__(
                self,
                *,
                status: int = 200,
                text: str | None = None,
                content_type: str | None = None,
            ) -> None:
                self.status = status
                self.text = text
                self.content_type = content_type

        aiohttp.web = types.SimpleNamespace(
            Response=Response,
            Request=object,
            StreamResponse=object,
        )
        aiohttp.ClientSession = object
        aiohttp.ClientTimeout = types.SimpleNamespace

        homeassistant = types.ModuleType("homeassistant")
        components = types.ModuleType("homeassistant.components")
        http = types.ModuleType("homeassistant.components.http")
        http.HomeAssistantView = object
        http.KEY_AUTHENTICATED = "ha_authenticated"
        components.http = http
        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = object
        helpers = types.ModuleType("homeassistant.helpers")
        network = types.ModuleType("homeassistant.helpers.network")
        network.get_url = lambda _hass, prefer_external=False: "http://ha.local"
        helpers.network = network

        test_case = self
        self.youtube_calls: list[dict] = []
        self.ytdlp_options: dict = {}

        class FakeStream:
            url = "https://audio.example/stream"
            mime_type = "audio/mp4"
            abr = "128kbps"

        class FakeStreams:
            def filter(self, **_kwargs):
                return self

            def order_by(self, _key):
                return self

            def desc(self):
                return self

            def first(self):
                return FakeStream()

        class FakeYouTube:
            def __init__(self, _url: str, **kwargs) -> None:
                test_case.youtube_calls.append(kwargs)
                self.title = "Title"
                self.author = "Author"
                self.thumbnail_url = None
                self.length = 200
                self.streams = FakeStreams()

        class FakeYoutubeDL:
            def __init__(self, options: dict) -> None:
                test_case.ytdlp_options = options

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def extract_info(self, *_args, **_kwargs):
                raise RuntimeError("blocked in test")

        pytubefix = types.ModuleType("pytubefix")
        pytubefix.YouTube = FakeYouTube
        pytubefix_exceptions = types.ModuleType("pytubefix.exceptions")
        pytubefix_exceptions.BotDetection = Exception
        yt_dlp = types.ModuleType("yt_dlp")
        yt_dlp.YoutubeDL = FakeYoutubeDL

        custom_components = types.ModuleType("custom_components")
        custom_components.__path__ = []
        integration_package = types.ModuleType("custom_components.ytmusic_url_player")
        integration_package.__path__ = []
        const = types.ModuleType("custom_components.ytmusic_url_player.const")
        const.DOMAIN = "ytmusic_url_player"
        const.CONF_PO_TOKEN = "po_token"
        const.CONF_VISITOR_DATA = "visitor_data"
        const.CONF_ALLOW_UNAUTHENTICATED = "allow_unauthenticated_streams"
        const.DEFAULT_ALLOW_UNAUTHENTICATED = False
        const.STREAM_CACHE_TTL_SECONDS = 600
        const.STREAM_GRANT_TTL_SECONDS = 24 * 3600
        const.STREAM_GRANT_MAX_ENTRIES = 1000
        const.API_STREAM_PATH = "stream"
        const.API_M3U_PATH = "m3u"
        ytmusic_client = types.ModuleType("custom_components.ytmusic_url_player.ytmusic_client")
        ytmusic_client.YTMusicClient = object

        sys.modules.update(
            {
                "aiohttp": aiohttp,
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
        self.module = module
        self.view_class = module.YTMusicM3UView
        self.stream_view_class = module.YTMusicStreamView

    def tearDown(self) -> None:
        for name, original in self._saved_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original

    def make_extractor(self, **config):
        extractor = self.module.StreamExtractor(object(), config, None)
        extractor.async_proxy = AsyncMock(return_value="streamed")
        return extractor

    @staticmethod
    def hass_with(**store):
        return types.SimpleNamespace(data={"ytmusic_url_player": {"entry": store}})

    async def test_m3u_extinf_uses_colon_duration_seconds(self) -> None:
        hass = self.hass_with(ytmusic=_Client())
        response = await self.view_class(hass).get(_Request(authenticated=True), "playlist-id")

        self.assertIn("#EXTINF:225,Artist - Timed Track", response.text)

    async def test_m3u_rejects_malformed_list_id(self) -> None:
        hass = self.hass_with(ytmusic=_Client())
        request = types.SimpleNamespace(query={}, remote="127.0.0.1")
        response = await self.view_class(hass).get(request, "../../secret")

        self.assertEqual(400, response.status)

    async def test_m3u_rejects_malformed_seed_video_id(self) -> None:
        hass = self.hass_with(ytmusic=_Client())
        request = types.SimpleNamespace(query={"v": "bad id!"}, remote="127.0.0.1")
        response = await self.view_class(hass).get(request, "valid-list")

        self.assertEqual(400, response.status)

    async def test_stream_view_rejects_malformed_video_id(self) -> None:
        hass = types.SimpleNamespace(data={"ytmusic_url_player": {}})
        request = types.SimpleNamespace(remote="127.0.0.1")
        response = await self.stream_view_class(hass).get(request, "a/b")

        self.assertEqual(400, response.status)

    # --- 1.10.0: who may fetch streams and playlists (Y4) ---

    async def test_stream_refuses_unauthenticated_request_for_unplayed_track(self) -> None:
        extractor = self.make_extractor()
        response = await self.stream_view_class(self.hass_with(extractor=extractor)).get(
            _Request(), VIDEO_ID
        )

        self.assertEqual(403, response.status)
        extractor.async_proxy.assert_not_awaited()

    async def test_stream_serves_tracks_this_integration_played(self) -> None:
        extractor = self.make_extractor()
        extractor.grant_stream(VIDEO_ID)

        response = await self.stream_view_class(self.hass_with(extractor=extractor)).get(
            _Request(), VIDEO_ID
        )

        self.assertEqual("streamed", response)

    async def test_stream_serves_authenticated_requests(self) -> None:
        extractor = self.make_extractor()

        response = await self.stream_view_class(self.hass_with(extractor=extractor)).get(
            _Request(authenticated=True), VIDEO_ID
        )

        self.assertEqual("streamed", response)

    async def test_legacy_option_serves_any_track_without_auth(self) -> None:
        extractor = self.make_extractor(allow_unauthenticated_streams=True)

        response = await self.stream_view_class(self.hass_with(extractor=extractor)).get(
            _Request(), VIDEO_ID
        )

        self.assertEqual("streamed", response)

    def test_stream_grant_expires_and_is_bounded(self) -> None:
        extractor = self.make_extractor()
        ttl = self.module.STREAM_GRANT_TTL_SECONDS
        with patch.object(self.module.time, "monotonic", return_value=0.0):
            extractor.grant_stream(VIDEO_ID)
        with patch.object(self.module.time, "monotonic", return_value=ttl - 1):
            self.assertTrue(extractor.stream_open_without_auth(VIDEO_ID))
        with patch.object(self.module.time, "monotonic", return_value=ttl + 1):
            self.assertFalse(extractor.stream_open_without_auth(VIDEO_ID))

        limit = self.module.STREAM_GRANT_MAX_ENTRIES
        for index in range(limit + 5):
            extractor.grant_stream(f"v{index}")
        self.assertEqual(limit, len(extractor._stream_grants))
        self.assertFalse(extractor.stream_open_without_auth("v0"))
        self.assertTrue(extractor.stream_open_without_auth(f"v{limit + 4}"))

    async def test_m3u_requires_authentication(self) -> None:
        hass = self.hass_with(ytmusic=_Client(), extractor=self.make_extractor())

        response = await self.view_class(hass).get(_Request(), "LM")

        self.assertEqual(401, response.status)

    async def test_m3u_lets_players_fetch_the_listed_tracks(self) -> None:
        extractor = self.make_extractor()
        hass = self.hass_with(ytmusic=_Client(), extractor=extractor)

        response = await self.view_class(hass).get(_Request(authenticated=True), "playlist-id")

        self.assertIn("http://ha.local/api/ytmusic_url_player/stream/duration-id", response.text)
        self.assertTrue(extractor.stream_open_without_auth("duration-id"))

    async def test_m3u_legacy_option_allows_unauthenticated(self) -> None:
        hass = self.hass_with(
            ytmusic=_Client(),
            extractor=self.make_extractor(allow_unauthenticated_streams=True),
        )

        response = await self.view_class(hass).get(_Request(), "playlist-id")

        self.assertIn("#EXTM3U", response.text)

    # --- 1.10.0: extraction settings (Y5, Y6) ---

    async def test_ytdlp_verifies_certificates_and_pytubefix_uses_po_token(self) -> None:
        extractor = self.module.StreamExtractor(
            object(), {"po_token": " TOKEN ", "visitor_data": "VISITOR"}, None
        )

        metadata = await extractor.async_get_metadata(VIDEO_ID)

        self.assertNotIn("nocheckcertificate", self.ytdlp_options)
        first = self.youtube_calls[0]
        self.assertEqual("WEB", first["client"])
        self.assertTrue(first["use_po_token"])
        self.assertEqual(("VISITOR", "TOKEN"), first["po_token_verifier"]())
        self.assertEqual(1, len(self.youtube_calls))
        self.assertEqual("https://audio.example/stream", metadata.stream_url)

    async def test_pytubefix_without_po_token_keeps_client_order(self) -> None:
        extractor = self.module.StreamExtractor(object(), {"po_token": "only-token"}, None)

        await extractor.async_get_metadata(VIDEO_ID)

        self.assertEqual({"client": "IOS"}, self.youtube_calls[0])


if __name__ == "__main__":
    unittest.main()
