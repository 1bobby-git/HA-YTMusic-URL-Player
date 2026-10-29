"""play_url / stop service behaviour around playlist queues (1.10.0)."""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock


ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "ytmusic_url_player"
PACKAGE = "service_queue_test_package"


class _Entry:
    entry_id = "entry-1"

    def __init__(self, media_player=None) -> None:
        self.data = {"media_player": media_player or ["media_player.default"]}
        self.options = {}


class ServiceQueueControlTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        names = (
            "voluptuous",
            "homeassistant",
            "homeassistant.config_entries",
            "homeassistant.core",
            "homeassistant.helpers",
            "homeassistant.helpers.config_validation",
            "homeassistant.helpers.network",
            PACKAGE,
            f"{PACKAGE}.queue_manager",
            f"{PACKAGE}.cast_manager",
            f"{PACKAGE}.service",
        )
        self._saved = {name: sys.modules.get(name) for name in names}

        vol = types.ModuleType("voluptuous")

        class Invalid(Exception):
            pass

        vol.Invalid = Invalid
        vol.Schema = lambda schema: (lambda value: value)
        vol.Required = lambda key, **_kwargs: key
        vol.Optional = lambda key, **_kwargs: key

        homeassistant = types.ModuleType("homeassistant")
        config_entries = types.ModuleType("homeassistant.config_entries")
        config_entries.ConfigEntry = object
        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = object
        core.ServiceCall = object
        helpers = types.ModuleType("homeassistant.helpers")
        cv = types.ModuleType("homeassistant.helpers.config_validation")
        cv.string = str
        cv.entity_id = str
        network = types.ModuleType("homeassistant.helpers.network")
        network.get_url = lambda _hass, prefer_external=False: "http://ha.local"
        helpers.config_validation = cv
        helpers.network = network

        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(ROOT)]
        queue_manager = types.ModuleType(f"{PACKAGE}.queue_manager")
        queue_manager.QueueManager = object
        cast_manager = types.ModuleType(f"{PACKAGE}.cast_manager")
        cast_manager.CastManager = object

        sys.modules.update({
            "voluptuous": vol,
            "homeassistant": homeassistant,
            "homeassistant.config_entries": config_entries,
            "homeassistant.core": core,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.config_validation": cv,
            "homeassistant.helpers.network": network,
            PACKAGE: package,
            f"{PACKAGE}.queue_manager": queue_manager,
            f"{PACKAGE}.cast_manager": cast_manager,
        })

        name = f"{PACKAGE}.service"
        spec = importlib.util.spec_from_file_location(name, ROOT / "service.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        self.module = module

        self.queue_manager = types.SimpleNamespace(
            stop_playlist=AsyncMock(),
            start_playlist=AsyncMock(),
            set_play_callback=Mock(),
        )

        async def _no_metadata(_video_id):
            raise RuntimeError("offline test")

        self.extractor = types.SimpleNamespace(
            async_get_metadata=_no_metadata,
            grant_stream=Mock(),
        )
        self.registered: dict[str, object] = {}
        self.hass = types.SimpleNamespace(
            data={
                module.DOMAIN: {
                    "entry-1": {
                        module.DATA_QUEUE_MANAGER: self.queue_manager,
                        module.DATA_EXTRACTOR: self.extractor,
                    }
                }
            },
            states=types.SimpleNamespace(get=lambda _entity_id: None),
            services=types.SimpleNamespace(
                async_call=AsyncMock(),
                has_service=lambda domain, service: (domain, service) in self.registered,
                async_register=lambda domain, service, handler, schema=None: self.registered.__setitem__(
                    (domain, service), handler
                ),
                async_remove=lambda domain, service: self.registered.pop((domain, service), None),
            ),
        )

    def tearDown(self) -> None:
        for name, original in self._saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original

    def calls(self) -> list[tuple]:
        return [call.args[:3] for call in self.hass.services.async_call.await_args_list]

    async def test_single_track_ends_running_playlist_and_grants_stream(self) -> None:
        await self.module.async_play_url(
            self.hass, _Entry(), "https://youtu.be/abcdefghijk", "media_player.living"
        )

        self.queue_manager.stop_playlist.assert_awaited_once_with("media_player.living")
        self.extractor.grant_stream.assert_called_once_with("abcdefghijk")
        domain, service, data = self.calls()[0]
        self.assertEqual(("media_player", "play_media"), (domain, service))
        self.assertEqual(
            "http://ha.local/api/ytmusic_url_player/stream/abcdefghijk",
            data["media_content_id"],
        )

    async def test_stop_ends_queue_and_stops_default_targets(self) -> None:
        await self.module.async_stop(self.hass, _Entry(["media_player.a", "media_player.b"]))

        self.assertEqual(
            ["media_player.a", "media_player.b"],
            [call.args[0] for call in self.queue_manager.stop_playlist.await_args_list],
        )
        self.assertEqual(
            [("media_player", "media_stop", {"entity_id": ["media_player.a", "media_player.b"]})],
            self.calls(),
        )

    async def test_stop_uses_select_override_like_play_url(self) -> None:
        self.hass.data[self.module.DOMAIN]["entry-1"][self.module.DATA_TARGET_OVERRIDE] = (
            "media_player.override"
        )

        await self.module.async_stop(self.hass, _Entry())

        self.queue_manager.stop_playlist.assert_awaited_once_with("media_player.override")

    async def test_stop_tolerates_players_that_cannot_stop(self) -> None:
        self.hass.services.async_call.side_effect = RuntimeError("not supported")

        await self.module.async_stop(self.hass, _Entry(), "media_player.a")

        self.queue_manager.stop_playlist.assert_awaited_once_with("media_player.a")

    async def test_register_and_unregister_both_services(self) -> None:
        self.module.async_register_services(self.hass)
        self.assertEqual(
            {("ytmusic_url_player", "play_url"), ("ytmusic_url_player", "stop")},
            set(self.registered),
        )

        self.module.async_unregister_services(self.hass)
        self.assertEqual({}, self.registered)


if __name__ == "__main__":
    unittest.main()
