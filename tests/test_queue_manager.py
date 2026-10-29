from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch


ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "ytmusic_url_player"
ENTITY = "media_player.test"


class QueueManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        package = types.ModuleType("queue_manager_test_package")
        package.__path__ = [str(ROOT)]
        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = object
        core.Event = object
        core.callback = lambda func: func
        constants = types.ModuleType("homeassistant.const")
        for name in ("IDLE", "PAUSED", "PLAYING", "OFF"):
            setattr(constants, f"STATE_{name}", name.lower())
        constants.EVENT_CALL_SERVICE = "call_service"
        event = types.ModuleType("homeassistant.helpers.event")
        self.unsubscribe = Mock()
        event.async_track_state_change_event = Mock(return_value=self.unsubscribe)
        self.timers: list[types.SimpleNamespace] = []

        def _call_later(_hass, delay, action):
            handle = types.SimpleNamespace(delay=delay, action=action, cancelled=False)
            self.timers.append(handle)

            def _cancel() -> None:
                handle.cancelled = True

            return _cancel

        event.async_call_later = _call_later
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

        self.service_listeners: list = []
        self.unsubscribe_services = Mock()

        def _async_listen(event_type, listener):
            self.service_listeners.append((event_type, listener))
            return self.unsubscribe_services

        self.player_states: dict[str, types.SimpleNamespace] = {}
        self.hass = types.SimpleNamespace(
            data={module.DOMAIN: {"entry": {}}},
            bus=types.SimpleNamespace(async_listen=_async_listen),
            states=types.SimpleNamespace(get=self.player_states.get),
        )
        self.manager = module.QueueManager(self.hass, "entry")
        self.now = 1000.0
        self.manager._clock = lambda: self.now
        self.play = AsyncMock()
        self.manager.set_play_callback(self.play)

    async def start(self, tracks) -> None:
        await asyncio.wait_for(
            self.manager.start_playlist(ENTITY, tracks), timeout=0.2
        )

    async def settle(self) -> None:
        for _ in range(3):
            await asyncio.sleep(0)
        tasks = list(self.manager._background_tasks)
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=0.5)

    def player(self, old: str | None, new: str, entity_id: str = ENTITY) -> None:
        self.manager._on_state_change(types.SimpleNamespace(data={
            "entity_id": entity_id,
            "old_state": types.SimpleNamespace(state=old, attributes={}) if old else None,
            "new_state": types.SimpleNamespace(state=new, attributes={}),
        }))

    def service_call(self, service: str, **service_data) -> None:
        for _event_type, listener in list(self.service_listeners):
            listener(types.SimpleNamespace(data={
                "domain": "media_player",
                "service": service,
                "service_data": service_data,
            }))

    def played(self) -> list[str]:
        return [call.args[1] for call in self.play.await_args_list]

    async def test_missing_video_id_skips_without_blocking_queue(self) -> None:
        await self.start([{"title": "Unavailable"}, {"videoId": "good"}])
        self.assertEqual("good", self.play.await_args.args[1])
        self.assertEqual(1, self.manager.get_queue_info(ENTITY)["current_index"])

    async def test_failed_playback_advances_to_next_track(self) -> None:
        self.play.side_effect = [RuntimeError("unavailable"), None]
        await self.start([{"videoId": "bad"}, {"videoId": "good"}])
        self.assertEqual(["bad", "good"], self.played())

    async def test_all_failures_stop_after_one_queue_pass(self) -> None:
        self.play.side_effect = RuntimeError("unavailable")
        await self.start([{"videoId": "bad1"}, {"videoId": "bad2"}])
        self.assertEqual(2, self.play.await_count)
        self.assertIsNone(self.manager.get_queue_info(ENTITY))
        self.unsubscribe.assert_called_once()

    async def test_once_mode_stops_at_end_after_failure(self) -> None:
        self.hass.data[self.module.DOMAIN]["entry"][self.module.DATA_PLAYBACK_MODE] = self.module.PLAYBACK_MODE_ONCE
        self.play.side_effect = RuntimeError("unavailable")
        await self.start([{"videoId": "bad"}])
        self.assertEqual(1, self.play.await_count)
        self.assertIsNone(self.manager.get_queue_info(ENTITY))

    async def test_track_end_failure_also_advances_without_blocking(self) -> None:
        await self.start([{"videoId": "first"}, {"videoId": "bad"}, {"videoId": "last"}])
        self.play.side_effect = [RuntimeError("unavailable"), None]
        await asyncio.wait_for(self.manager._play_next(ENTITY), timeout=0.2)
        self.assertEqual("last", self.play.await_args.args[1])

    async def test_spawn_retains_task_reference_until_done(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def _worker() -> None:
            started.set()
            await release.wait()

        self.manager._spawn(_worker())
        await asyncio.wait_for(started.wait(), timeout=0.2)
        # A strong reference must be held while the task is in flight.
        self.assertEqual(1, len(self.manager._background_tasks))
        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        # The done callback must drop the reference once finished.
        self.assertEqual(0, len(self.manager._background_tasks))

    async def test_clear_all_cancels_pending_background_tasks(self) -> None:
        async def _worker() -> None:
            await asyncio.Event().wait()

        self.manager._spawn(_worker())
        task = next(iter(self.manager._background_tasks))
        self.manager.clear_all()
        self.assertEqual(0, len(self.manager._background_tasks))
        with self.assertRaises(asyncio.CancelledError):
            await task

    # --- 1.10.0: track end detection (Y2) ---

    async def test_idle_right_after_play_command_is_ignored(self) -> None:
        await self.start([{"videoId": "first"}, {"videoId": "second"}])

        self.now += 2  # the content that played before stops
        self.player("playing", "idle")
        await self.settle()
        self.assertEqual(["first"], self.played())

        self.now += 180  # the first track ends
        self.player("playing", "idle")
        await self.settle()
        self.assertEqual(["first", "second"], self.played())

    async def test_duplicate_end_events_advance_once(self) -> None:
        await self.start([{"videoId": "a"}, {"videoId": "b"}, {"videoId": "c"}])
        self.now += 180

        self.player("playing", "idle")
        self.player("playing", "idle")
        await self.settle()

        self.assertEqual(["a", "b"], self.played())

    # --- 1.10.0: failed playback (Y3) ---

    async def test_play_callback_false_skips_to_next_track(self) -> None:
        self.play.side_effect = [False, None]

        await self.start([{"videoId": "bad"}, {"videoId": "good"}])

        self.assertEqual(["bad", "good"], self.played())
        self.assertEqual(1, self.manager.get_queue_info(ENTITY)["current_index"])

    async def test_watchdog_skips_a_track_that_never_started(self) -> None:
        await self.start([{"videoId": "silent"}, {"videoId": "next"}])
        self.assertEqual(self.module.QUEUE_START_TIMEOUT_SECONDS, self.timers[0].delay)
        self.player_states[ENTITY] = types.SimpleNamespace(state="idle")

        self.timers[0].action(None)
        await self.settle()

        self.assertEqual(["silent", "next"], self.played())

    async def test_watchdog_leaves_a_playing_track_alone(self) -> None:
        await self.start([{"videoId": "playing"}, {"videoId": "next"}])
        self.player_states[ENTITY] = types.SimpleNamespace(state="playing")

        self.timers[0].action(None)
        await self.settle()

        self.assertEqual(["playing"], self.played())

    async def test_next_track_cancels_the_previous_watchdog(self) -> None:
        await self.start([{"videoId": "a"}, {"videoId": "b"}])
        self.now += 180
        self.player("playing", "idle")
        await self.settle()

        self.assertEqual(2, len(self.timers))
        self.assertTrue(self.timers[0].cancelled)
        self.assertFalse(self.timers[1].cancelled)

    # --- 1.10.0: ending the queue (Y1) ---

    async def test_player_turned_off_ends_queue(self) -> None:
        await self.start([{"videoId": "a"}, {"videoId": "b"}])
        self.now += 60

        self.player("playing", "off")
        await self.settle()

        self.assertIsNone(self.manager.get_queue_info(ENTITY))
        self.unsubscribe.assert_called_once()
        self.assertTrue(self.timers[0].cancelled)

    async def test_off_around_a_play_command_is_ignored(self) -> None:
        await self.start([{"videoId": "a"}, {"videoId": "b"}])
        self.now += 1

        self.player("playing", "off")
        await self.settle()

        self.assertIsNotNone(self.manager.get_queue_info(ENTITY))

    async def test_stop_service_call_for_the_player_ends_queue(self) -> None:
        await self.start([{"videoId": "a"}, {"videoId": "b"}])

        self.service_call("media_stop", entity_id=ENTITY)
        self.now += 180
        self.player("playing", "idle")
        await self.settle()

        self.assertEqual(["a"], self.played())
        self.assertIsNone(self.manager.get_queue_info(ENTITY))
        self.unsubscribe_services.assert_called_once()

    async def test_turn_off_for_all_players_ends_queue(self) -> None:
        await self.start([{"videoId": "a"}])

        self.service_call("turn_off", entity_id="all")
        await self.settle()

        self.assertIsNone(self.manager.get_queue_info(ENTITY))

    async def test_other_content_ends_queue_but_own_stream_does_not(self) -> None:
        await self.start([{"videoId": "a"}, {"videoId": "b"}])

        self.service_call(
            "play_media",
            entity_id=[ENTITY],
            media_content_id="http://ha.local/api/ytmusic_url_player/stream/b",
        )
        await self.settle()
        self.assertIsNotNone(self.manager.get_queue_info(ENTITY))

        self.service_call(
            "play_media", entity_id=ENTITY, media_content_id="https://radio.example/live.mp3"
        )
        await self.settle()
        self.assertIsNone(self.manager.get_queue_info(ENTITY))

    async def test_service_calls_for_other_players_or_volume_are_ignored(self) -> None:
        await self.start([{"videoId": "a"}])

        self.service_call("media_stop", entity_id="media_player.kitchen")
        self.service_call("volume_set", entity_id=ENTITY, volume_level=0.3)
        await self.settle()

        self.assertIsNotNone(self.manager.get_queue_info(ENTITY))

    async def test_new_playlist_replaces_queue_without_late_stop(self) -> None:
        await self.start([{"videoId": "old"}])
        self.service_call("media_stop", entity_id=ENTITY)
        await self.start([{"videoId": "new"}])
        await self.settle()

        info = self.manager.get_queue_info(ENTITY)
        self.assertIsNotNone(info)
        self.assertEqual("new", info["current_track"]["videoId"])

    async def test_clear_all_cancels_watchdog_and_service_listener(self) -> None:
        await self.start([{"videoId": "a"}])

        self.manager.clear_all()

        self.assertTrue(self.timers[0].cancelled)
        self.unsubscribe_services.assert_called_once()


if __name__ == "__main__":
    unittest.main()
