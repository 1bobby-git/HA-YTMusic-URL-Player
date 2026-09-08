from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch


ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "ytmusic_url_player"


class QueueManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        package = types.ModuleType("queue_manager_test_package")
        package.__path__ = [str(ROOT)]
        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = object
        core.Event = object
        core.callback = lambda func: func
        constants = types.ModuleType("homeassistant.const")
        for name in ("IDLE", "PAUSED", "PLAYING"):
            setattr(constants, f"STATE_{name}", name.lower())
        event = types.ModuleType("homeassistant.helpers.event")
        self.unsubscribe = Mock()
        event.async_track_state_change_event = Mock(return_value=self.unsubscribe)
        self.modules = patch.dict(sys.modules, {
            package.__name__: package,
            "homeassistant.core": core,
            "homeassistant.const": constants,
            "homeassistant.helpers.event": event,
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)
        name = f"{package.__name__}.queue_manager"
        spec = importlib.util.spec_from_file_location(name, ROOT / "queue_manager.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        self.module = module
        self.hass = types.SimpleNamespace(data={module.DOMAIN: {"entry": {}}})
        self.manager = module.QueueManager(self.hass, "entry")
        self.play = AsyncMock()
        self.manager.set_play_callback(self.play)

    async def start(self, tracks) -> None:
        await asyncio.wait_for(
            self.manager.start_playlist("media_player.test", tracks), timeout=0.2
        )

    async def test_missing_video_id_skips_without_blocking_queue(self) -> None:
        await self.start([{"title": "Unavailable"}, {"videoId": "good"}])
        self.assertEqual("good", self.play.await_args.args[1])
        self.assertEqual(1, self.manager.get_queue_info("media_player.test")["current_index"])

    async def test_failed_playback_advances_to_next_track(self) -> None:
        self.play.side_effect = [RuntimeError("unavailable"), None]
        await self.start([{"videoId": "bad"}, {"videoId": "good"}])
        self.assertEqual(["bad", "good"], [call.args[1] for call in self.play.await_args_list])

    async def test_all_failures_stop_after_one_queue_pass(self) -> None:
        self.play.side_effect = RuntimeError("unavailable")
        await self.start([{"videoId": "bad1"}, {"videoId": "bad2"}])
        self.assertEqual(2, self.play.await_count)
        self.assertIsNone(self.manager.get_queue_info("media_player.test"))
        self.unsubscribe.assert_called_once()

    async def test_once_mode_stops_at_end_after_failure(self) -> None:
        self.hass.data[self.module.DOMAIN]["entry"][self.module.DATA_PLAYBACK_MODE] = self.module.PLAYBACK_MODE_ONCE
        self.play.side_effect = RuntimeError("unavailable")
        await self.start([{"videoId": "bad"}])
        self.assertEqual(1, self.play.await_count)
        self.assertIsNone(self.manager.get_queue_info("media_player.test"))

    async def test_track_end_failure_also_advances_without_blocking(self) -> None:
        await self.start([{"videoId": "first"}, {"videoId": "bad"}, {"videoId": "last"}])
        self.play.side_effect = [RuntimeError("unavailable"), None]
        await asyncio.wait_for(self.manager._play_next("media_player.test"), timeout=0.2)
        self.assertEqual("last", self.play.await_args.args[1])


if __name__ == "__main__":
    unittest.main()
