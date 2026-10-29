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
        for name in ("IDLE", "PAUSED", "PLAYING", "OFF", "ON"):
            setattr(constants, f"STATE_{name}", name.lower())
        constants.EVENT_CALL_SERVICE = "call_service"
        self.entity_entries: dict[str, types.SimpleNamespace] = {}
        self.device_entries: dict[str, types.SimpleNamespace] = {}
        self.area_entries: dict[str, types.SimpleNamespace] = {}
        entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
        entity_registry.async_get = lambda _hass: types.SimpleNamespace(
            async_get=self.entity_entries.get
        )
        device_registry = types.ModuleType("homeassistant.helpers.device_registry")
        device_registry.async_get = lambda _hass: types.SimpleNamespace(
            async_get=self.device_entries.get
        )
        area_registry = types.ModuleType("homeassistant.helpers.area_registry")
        area_registry.async_get = lambda _hass: types.SimpleNamespace(
            async_get_area=self.area_entries.get
        )
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
            "homeassistant.helpers.entity_registry": entity_registry,
            "homeassistant.helpers.device_registry": device_registry,
            "homeassistant.helpers.area_registry": area_registry,
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

    # --- 1.10.0 review fixes ---

    async def test_announcements_and_enqueue_keep_the_playlist(self) -> None:
        await self.start([{"videoId": "a"}, {"videoId": "b"}])

        self.service_call(
            "play_media", entity_id=ENTITY, media_content_id="media-source://tts/x", announce=True
        )
        self.service_call("play_media", entity_id=ENTITY, media_content_id="x", enqueue="add")
        self.service_call("play_media", entity_id=ENTITY, media_content_id="x", enqueue="next")
        await self.settle()

        self.assertTrue(self.manager.has_queue(ENTITY))

        self.service_call("play_media", entity_id=ENTITY, media_content_id="x", enqueue="replace")
        await self.settle()
        self.assertFalse(self.manager.has_queue(ENTITY))

    async def test_stop_by_area_or_device_ends_queue(self) -> None:
        self.entity_entries[ENTITY] = types.SimpleNamespace(device_id="dev1", area_id=None)
        self.device_entries["dev1"] = types.SimpleNamespace(area_id="living_room")
        await self.start([{"videoId": "a"}])

        self.service_call("media_stop", area_id="kitchen")
        await self.settle()
        self.assertTrue(self.manager.has_queue(ENTITY))

        self.service_call("media_stop", area_id=["living_room"])
        await self.settle()
        self.assertFalse(self.manager.has_queue(ENTITY))

        await self.start([{"videoId": "a"}])
        self.service_call("turn_off", device_id="dev1")
        await self.settle()
        self.assertFalse(self.manager.has_queue(ENTITY))

    async def test_stop_by_floor_or_label_ends_queue(self) -> None:
        self.entity_entries[ENTITY] = types.SimpleNamespace(
            device_id="dev1", area_id=None, labels={"music"}
        )
        self.device_entries["dev1"] = types.SimpleNamespace(area_id="living_room", labels=set())
        self.area_entries["living_room"] = types.SimpleNamespace(floor_id="ground", labels={"downstairs"})

        for target in (
            {"floor_id": "ground"},
            {"label_id": "music"},
            {"label_id": ["downstairs"]},
        ):
            with self.subTest(target=target):
                await self.start([{"videoId": "a"}])
                self.service_call("media_stop", floor_id="upstairs")
                self.service_call("media_stop", label_id="kids")
                await self.settle()
                self.assertTrue(self.manager.has_queue(ENTITY))

                self.service_call("media_stop", **target)
                await self.settle()
                self.assertFalse(self.manager.has_queue(ENTITY))

    async def test_renderer_that_fails_at_once_still_hits_the_failure_bound(self) -> None:
        await self.start([{"videoId": f"t{i}"} for i in range(10)])
        self.player_states[ENTITY] = types.SimpleNamespace(state="idle")

        for _ in range(3):
            # Reports playing for a moment, then gives up on the stream.
            self.player("idle", "playing")
            self.player("playing", "idle")
            await self.settle()
            self.timers[-1].action(None)
            await self.settle()

        self.assertEqual(["t0", "t1", "t2"], self.played())
        self.assertFalse(self.manager.has_queue(ENTITY))

    async def test_watchdog_ends_queue_when_player_is_gone(self) -> None:
        for state in ("off", "unavailable", "unknown", None):
            with self.subTest(state=state):
                self.play.reset_mock()
                self.timers.clear()
                await self.start([{"videoId": "a"}, {"videoId": "b"}])
                if state is None:
                    self.player_states.pop(ENTITY, None)
                else:
                    self.player_states[ENTITY] = types.SimpleNamespace(state=state)

                self.timers[0].action(None)
                await self.settle()

                self.assertEqual(["a"], self.played())
                self.assertFalse(self.manager.has_queue(ENTITY))

    async def test_watchdog_leaves_an_on_only_player_alone(self) -> None:
        await self.start([{"videoId": "a"}, {"videoId": "b"}])
        self.player_states[ENTITY] = types.SimpleNamespace(state="on")

        self.timers[0].action(None)
        await self.settle()

        self.assertEqual(["a"], self.played())
        self.assertTrue(self.manager.has_queue(ENTITY))

    async def test_queue_ends_after_three_failures_in_a_row(self) -> None:
        self.play.side_effect = RuntimeError("rejected")
        tracks = [{"videoId": f"t{i}"} for i in range(30)]

        await self.start(tracks)

        self.assertEqual(3, self.play.await_count)
        self.assertFalse(self.manager.has_queue(ENTITY))

    async def test_tracks_that_never_start_end_the_queue_after_three(self) -> None:
        await self.start([{"videoId": f"t{i}"} for i in range(10)])
        self.player_states[ENTITY] = types.SimpleNamespace(state="idle")

        for _ in range(3):
            self.timers[-1].action(None)
            await self.settle()

        self.assertEqual(["t0", "t1", "t2"], self.played())
        self.assertFalse(self.manager.has_queue(ENTITY))

    async def test_failure_count_survives_playing_and_resets_when_a_track_plays_through(self) -> None:
        self.play.side_effect = [RuntimeError("x"), RuntimeError("x"), None, None, None]
        await self.start([{"videoId": f"t{i}"} for i in range(6)])
        self.player("idle", "playing")
        self.assertEqual(2, self.manager._queues[ENTITY].failures)
        self.now += 180

        self.player("playing", "idle")  # the track played through
        await self.settle()

        self.assertTrue(self.manager.has_queue(ENTITY))
        self.assertEqual(0, self.manager._queues[ENTITY].failures)

    async def test_watchdog_finding_the_track_active_resets_the_failure_count(self) -> None:
        self.play.side_effect = [RuntimeError("x"), RuntimeError("x"), None]
        await self.start([{"videoId": f"t{i}"} for i in range(6)])
        self.assertEqual(2, self.manager._queues[ENTITY].failures)
        self.player_states[ENTITY] = types.SimpleNamespace(state="playing")

        self.timers[-1].action(None)
        await self.settle()

        self.assertEqual(0, self.manager._queues[ENTITY].failures)

    async def test_short_track_ending_inside_the_grace_window_plays_the_next(self) -> None:
        await self.start([
            {"videoId": "intro", "duration_seconds": 6},
            {"videoId": "song", "duration_seconds": 200},
        ])

        self.now += 1  # the previous content stops: still ignored
        self.player("playing", "idle")
        await self.settle()
        self.assertEqual(["intro"], self.played())

        self.now += 5  # the 6 s intro ends
        self.player("playing", "idle")
        await self.settle()
        self.assertEqual(["intro", "song"], self.played())

    async def test_short_tracks_missed_by_the_player_do_not_end_the_playlist(self) -> None:
        await self.start([{"videoId": f"s{i}", "duration_seconds": 5} for i in range(5)])
        self.player_states[ENTITY] = types.SimpleNamespace(state="idle")

        for _ in range(4):
            self.timers[-1].action(None)
            await self.settle()

        self.assertEqual(["s0", "s1", "s2", "s3", "s4"], self.played())
        self.assertTrue(self.manager.has_queue(ENTITY))

    async def test_hidden_player_is_not_reached_by_area_targets(self) -> None:
        self.entity_entries[ENTITY] = types.SimpleNamespace(
            device_id=None, area_id="living_room", labels=set(), hidden_by="user"
        )
        await self.start([{"videoId": "a"}])

        self.service_call("media_stop", area_id="living_room")
        await self.settle()
        self.assertTrue(self.manager.has_queue(ENTITY))

        self.service_call("media_stop", entity_id=ENTITY)
        await self.settle()
        self.assertFalse(self.manager.has_queue(ENTITY))

    async def test_end_event_of_a_replaced_queue_is_ignored(self) -> None:
        await self.start([{"videoId": "old"}])
        old_queue = self.manager._queues[ENTITY]
        old_attempt = old_queue.attempt
        await self.start([{"videoId": "new1"}, {"videoId": "new2"}])

        await self.manager._play_next(ENTITY, old_queue, old_attempt)

        self.assertEqual(["old", "new1"], self.played())
        self.assertEqual(0, self.manager.get_queue_info(ENTITY)["current_index"])

    async def test_stop_playlist_deactivates_before_waiting_for_the_lock(self) -> None:
        await self.start([{"videoId": "a"}, {"videoId": "b"}])
        queue = self.manager._queues[ENTITY]
        await self.manager._lock.acquire()

        stopping = asyncio.create_task(self.manager.stop_playlist(ENTITY))
        await asyncio.sleep(0)

        self.assertFalse(queue.is_active)
        self.assertTrue(self.timers[0].cancelled)
        self.manager._lock.release()
        await asyncio.wait_for(stopping, timeout=0.2)
        self.assertIsNone(self.manager.get_queue_info(ENTITY))


if __name__ == "__main__":
    unittest.main()
