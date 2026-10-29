"""Playlist queue manager for continuous playback."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.const import (
    EVENT_CALL_SERVICE,
    STATE_IDLE,
    STATE_OFF,
    STATE_ON,
    STATE_PAUSED,
    STATE_PLAYING,
)
from homeassistant.helpers.area_registry import async_get as async_get_area_registry
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .const import (
    API_STREAM_PATH,
    DOMAIN,
    DATA_EXTRACTOR,
    DATA_PLAYBACK_MODE,
    PLAYBACK_MODE_SEQUENTIAL,
    PLAYBACK_MODE_ONCE,
    PLAYBACK_MODE_SHUFFLE,
    QUEUE_IDLE_GRACE_SECONDS,
    QUEUE_MAX_CONSECUTIVE_FAILURES,
    QUEUE_START_TIMEOUT_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

_STATE_BUFFERING = "buffering"
# A player in one of these states has the queued track in hand. Some players
# only ever report on/off.
_ACTIVE_STATES = frozenset({STATE_PLAYING, STATE_PAUSED, _STATE_BUFFERING, STATE_ON})
# A player in one of these states cannot be playing the queue.
_GONE_STATES = frozenset({STATE_OFF, "unavailable", "unknown"})
# media_player services that take the player away from the queue.
_TAKEOVER_SERVICES = frozenset({"media_stop", "turn_off", "play_media"})
# play_media enqueue values that keep the current playback (MediaPlayerEnqueue).
_KEEP_PLAYING_ENQUEUE = frozenset({"add", "next"})
# Every stream URL this integration sends contains this path.
OWN_STREAM_MARKER = f"/api/{DOMAIN}/{API_STREAM_PATH}/"


def _as_id_set(value: Any) -> set[str]:
    """Normalise an entity/device/area id target (str, comma list or list)."""
    if isinstance(value, str):
        return {part.strip() for part in value.split(",") if part.strip()}
    if isinstance(value, (list, tuple, set)):
        return {str(part).strip() for part in value if str(part).strip()}
    return set()


@dataclass
class PlaybackQueue:
    """Playback queue for a single media_player."""
    entity_id: str
    tracks: list[dict[str, Any]] = field(default_factory=list)
    original_tracks: list[dict[str, Any]] = field(default_factory=list)  # 원본 순서 저장
    current_index: int = 0
    is_active: bool = False
    unsubscribe: Callable | None = None
    current_mode: str = PLAYBACK_MODE_SEQUENTIAL  # 현재 적용된 모드
    # Increments with every play command, so events about an earlier track
    # are recognised and ignored.
    attempt: int = 0
    # Monotonic time the last play command returned; None while it runs.
    command_at: float | None = None
    cancel_watchdog: Callable | None = None
    # Tracks in a row whose play command failed or that never started.
    failures: int = 0


class QueueManager:
    """Manages playlist queues and continuous playback."""

    def __init__(self, hass: HomeAssistant, entry_id: str | None = None) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._queues: dict[str, PlaybackQueue] = {}
        self._play_callback: Callable | None = None
        self._lock = asyncio.Lock()
        # Keep strong references to fire-and-forget tasks; the event loop only
        # holds a weak reference, so untracked tasks may be garbage-collected
        # mid-flight (see asyncio.create_task docs).
        self._background_tasks: set[asyncio.Task] = set()
        self._unsub_service_calls: Callable | None = None
        self._clock: Callable[[], float] = time.monotonic

    def _spawn(self, coro) -> None:
        """Schedule a background task and retain a strong reference to it."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def set_entry_id(self, entry_id: str) -> None:
        """Set the entry_id for accessing playback mode."""
        self._entry_id = entry_id

    def set_play_callback(self, callback: Callable) -> None:
        """Set the callback function for playing a track."""
        self._play_callback = callback

    def _get_playback_mode(self) -> str:
        """Get current playback mode from hass.data."""
        if not self._entry_id:
            _LOGGER.warning("[Queue] No entry_id set, defaulting to SEQUENTIAL")
            return PLAYBACK_MODE_SEQUENTIAL

        domain_data = self.hass.data.get(DOMAIN)
        if not domain_data:
            _LOGGER.warning("[Queue] No domain data found")
            return PLAYBACK_MODE_SEQUENTIAL

        store = domain_data.get(self._entry_id)
        if not store:
            _LOGGER.warning("[Queue] No store found for entry_id=%s", self._entry_id)
            return PLAYBACK_MODE_SEQUENTIAL

        mode = store.get(DATA_PLAYBACK_MODE, PLAYBACK_MODE_SEQUENTIAL)
        _LOGGER.debug("[Queue] Retrieved playback mode: %s (entry_id=%s)", mode, self._entry_id)
        return mode

    async def start_playlist(
        self,
        entity_id: str,
        tracks: list[dict[str, Any]],
        start_index: int = 0,
    ) -> None:
        """Start a new playlist queue for the given entity."""
        async with self._lock:
            # Stop existing queue for this entity
            await self._stop_queue(entity_id)

            if not tracks:
                _LOGGER.warning("[Queue] No tracks provided for %s", entity_id)
                return

            # 재생 모드 확인
            playback_mode = self._get_playback_mode()
            _LOGGER.info("[Queue] Playback mode: %s", playback_mode)

            # 원본 트랙 저장
            original_tracks = list(tracks)
            play_tracks = list(tracks)

            # 랜덤재생 모드면 셔플
            if playback_mode == PLAYBACK_MODE_SHUFFLE:
                play_tracks = list(tracks)
                random.shuffle(play_tracks)
                start_index = 0  # 셔플 시 처음부터 재생
                _LOGGER.info("[Queue] Shuffled %d tracks", len(play_tracks))

            queue = PlaybackQueue(
                entity_id=entity_id,
                tracks=play_tracks,
                original_tracks=original_tracks,
                current_index=start_index,
                is_active=True,
                current_mode=playback_mode,
            )

            # Subscribe to state changes
            queue.unsubscribe = async_track_state_change_event(
                self.hass,
                [entity_id],
                self._on_state_change,
            )

            self._queues[entity_id] = queue
            self._ensure_service_listener()

            _LOGGER.info(
                "[Queue] Started playlist for %s: %d tracks, starting at %d, mode=%s",
                entity_id, len(play_tracks), start_index, playback_mode
            )

            # Play the first track
            await self._play_current(entity_id)

    async def stop_playlist(self, entity_id: str) -> None:
        """Stop the playlist queue for the given entity."""
        queue = self._queues.get(entity_id)
        if queue is not None:
            # Inactive at once: a play loop holding the lock gives up at its
            # next step instead of making the caller wait for every track.
            queue.is_active = False
            self._cancel_watchdog(queue)
        async with self._lock:
            await self._stop_queue(entity_id)

    def has_queue(self, entity_id: str) -> bool:
        """Return True when a playlist queue is active for the entity."""
        queue = self._queues.get(entity_id)
        return bool(queue and queue.is_active)

    async def _stop_queue(self, entity_id: str) -> None:
        """Internal: stop queue without lock."""
        queue = self._queues.pop(entity_id, None)
        if queue:
            queue.is_active = False
            self._cancel_watchdog(queue)
            if queue.unsubscribe:
                queue.unsubscribe()
            _LOGGER.info("[Queue] Stopped playlist for %s", entity_id)
        self._release_service_listener()

    @callback
    def _request_stop(self, entity_id: str, reason: str) -> None:
        """End a queue now; the cleanup runs under the lock afterwards."""
        queue = self._queues.get(entity_id)
        if queue is None or not queue.is_active:
            return
        _LOGGER.info("[Queue] Ending playlist for %s: %s", entity_id, reason)
        # Inactive at once, so no event or watchdog advances it meanwhile.
        queue.is_active = False
        self._cancel_watchdog(queue)
        self._spawn(self._stop_if_current(entity_id, queue))

    async def _stop_if_current(self, entity_id: str, queue: PlaybackQueue) -> None:
        async with self._lock:
            # A new playlist may have replaced this queue in the meantime.
            if self._queues.get(entity_id) is queue:
                await self._stop_queue(entity_id)

    def _just_commanded(self, queue: PlaybackQueue) -> bool:
        """True while a play command runs and shortly after it returned."""
        return (
            queue.command_at is None
            or self._clock() - queue.command_at < QUEUE_IDLE_GRACE_SECONDS
        )

    @callback
    def _on_state_change(self, event: Event) -> None:
        """Handle media_player state changes."""
        entity_id = event.data.get("entity_id")
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")

        if not new_state or entity_id not in self._queues:
            return

        queue = self._queues[entity_id]
        if not queue.is_active:
            return

        old_state_str = old_state.state if old_state else "unknown"
        new_state_str = new_state.state

        _LOGGER.debug(
            "[Queue] %s state: %s -> %s",
            entity_id, old_state_str, new_state_str
        )

        if new_state_str == STATE_OFF and old_state_str != STATE_OFF:
            if self._just_commanded(queue):
                # Usually the previous app closing; if the player stays off,
                # the start watchdog ends the queue.
                _LOGGER.debug("[Queue] %s switched off around a play command, ignored", entity_id)
                return
            self._request_stop(entity_id, "the player was turned off")
            return

        # Track finished: was playing, now idle
        if old_state_str == STATE_PLAYING and new_state_str == STATE_IDLE:
            if self._just_commanded(queue):
                # The content that played before our command stopped, or a
                # renderer gave up on the stream at once (the watchdog counts
                # that as a failure).
                _LOGGER.debug("[Queue] %s went idle right after a play command, ignored", entity_id)
                return
            _LOGGER.info("[Queue] Track finished on %s, playing next...", entity_id)
            queue.failures = 0  # this track played through
            self._spawn(self._play_next(entity_id, queue, queue.attempt))

    def _ensure_service_listener(self) -> None:
        if self._unsub_service_calls is None:
            self._unsub_service_calls = self.hass.bus.async_listen(
                EVENT_CALL_SERVICE, self._on_call_service
            )

    def _release_service_listener(self) -> None:
        if not self._queues and self._unsub_service_calls is not None:
            self._unsub_service_calls()
            self._unsub_service_calls = None

    def _is_current(
        self, entity_id: str, queue: PlaybackQueue | None, attempt: int | None
    ) -> bool:
        """Whether an event about (queue, attempt) still concerns the live track."""
        current = self._queues.get(entity_id)
        if queue is not None and current is not queue:
            return False  # the queue was replaced meanwhile
        if attempt is not None and (current is None or current.attempt != attempt):
            return False  # this track was already handled
        return True

    async def _play_next(
        self,
        entity_id: str,
        queue: PlaybackQueue | None = None,
        attempt: int | None = None,
    ) -> None:
        """Play the next track while holding the queue lock once.

        ``queue`` and ``attempt`` identify the play command the end event
        belongs to; events for an earlier track or queue are ignored.
        """
        async with self._lock:
            if not self._is_current(entity_id, queue, attempt):
                return
            if await self._advance_queue(entity_id):
                await self._play_current(entity_id)

    @callback
    def _on_call_service(self, event: Event) -> None:
        """End the queue when Home Assistant stops the player or plays other content on it."""
        data = event.data
        service = data.get("service")
        if data.get("domain") != "media_player" or service not in _TAKEOVER_SERVICES:
            return
        service_data = data.get("service_data") or {}
        if service == "play_media":
            enqueue = service_data.get("enqueue")
            if (
                # Announcements (tts.speak) and queued additions leave the
                # current track playing.
                service_data.get("announce")
                or enqueue is True
                or enqueue in _KEEP_PLAYING_ENQUEUE
                or OWN_STREAM_MARKER in str(service_data.get("media_content_id") or "")
            ):
                return
        for entity_id in self._targeted_queues(service_data):
            self._request_stop(entity_id, f"media_player.{service} was called")

    def _targeted_queues(self, service_data: dict[str, Any]) -> list[str]:
        """Queued players a service call addresses by entity, device, area, floor or label."""
        entity_target = service_data.get("entity_id")
        if isinstance(entity_target, str) and entity_target.strip().lower() == "all":
            return list(self._queues)
        entity_ids = _as_id_set(entity_target)
        device_ids = _as_id_set(service_data.get("device_id"))
        area_ids = _as_id_set(service_data.get("area_id"))
        floor_ids = _as_id_set(service_data.get("floor_id"))
        label_ids = _as_id_set(service_data.get("label_id"))
        targeted = [entity_id for entity_id in self._queues if entity_id in entity_ids]
        if device_ids or area_ids or floor_ids or label_ids:
            targeted += [
                entity_id
                for entity_id in self._queues
                if entity_id not in targeted
                and self._is_targeted(entity_id, device_ids, area_ids, floor_ids, label_ids)
            ]
        return targeted

    def _is_targeted(
        self,
        entity_id: str,
        device_ids: set[str],
        area_ids: set[str],
        floor_ids: set[str],
        label_ids: set[str],
    ) -> bool:
        """Resolve a device/area/floor/label target like Home Assistant does."""
        try:
            entry = async_get_entity_registry(self.hass).async_get(entity_id)
            if entry is None:
                return False
            device = (
                async_get_device_registry(self.hass).async_get(entry.device_id)
                if entry.device_id
                else None
            )
            if entry.device_id and entry.device_id in device_ids:
                return True
            # The entity's own area wins over its device's area.
            area_id = entry.area_id or (device.area_id if device else None)
            if area_id and area_id in area_ids:
                return True
            area = None
            if area_id and (floor_ids or label_ids):
                area = async_get_area_registry(self.hass).async_get_area(area_id)
            if floor_ids and area is not None and getattr(area, "floor_id", None) in floor_ids:
                return True
            if label_ids:
                labels = set(getattr(entry, "labels", ()) or ())
                if device is not None:
                    labels |= set(getattr(device, "labels", ()) or ())
                if area is not None:
                    labels |= set(getattr(area, "labels", ()) or ())
                if labels & label_ids:
                    return True
            return False
        except Exception as err:  # registry lookup must never break the bus
            _LOGGER.debug("[Queue] Could not resolve target of %s: %s", entity_id, err)
            return False

    async def _advance_queue(self, entity_id: str) -> bool:
        """Advance a queue; the caller must already hold the lock."""
        queue = self._queues.get(entity_id)
        if not queue or not queue.is_active:
            return False

        playback_mode = self._get_playback_mode()

        # 모드 변경 감지 및 트랙 리스트 재구성
        if playback_mode != queue.current_mode:
            _LOGGER.info(
                "[Queue] Mode changed: %s -> %s, restructuring playlist",
                queue.current_mode, playback_mode
            )
            current_track = queue.tracks[queue.current_index] if queue.current_index < len(queue.tracks) else None
            current_video_id = current_track.get("videoId") if current_track else None

            if playback_mode == PLAYBACK_MODE_SHUFFLE:
                # → 랜덤재생: 현재 트랙 제외하고 나머지 셔플
                remaining = [t for t in queue.original_tracks if t.get("videoId") != current_video_id]
                random.shuffle(remaining)
                # 현재 트랙을 맨 앞에 두고 나머지 셔플된 트랙 추가
                if current_track:
                    queue.tracks = [current_track] + remaining
                    queue.current_index = 0
                else:
                    queue.tracks = remaining
                    queue.current_index = 0
                _LOGGER.info("[Queue] Switched to shuffle: %d tracks", len(queue.tracks))

            elif playback_mode == PLAYBACK_MODE_SEQUENTIAL:
                # → 순차재생: 원본 순서로 복원, 현재 트랙 위치 찾기
                queue.tracks = list(queue.original_tracks)
                if current_video_id:
                    for i, t in enumerate(queue.tracks):
                        if t.get("videoId") == current_video_id:
                            queue.current_index = i
                            break
                _LOGGER.info("[Queue] Switched to sequential: index=%d", queue.current_index)

            # ONCE 모드는 리스트 변경 불필요 (다음 곡 끝나면 종료)
            queue.current_mode = playback_mode

        # 다음 트랙으로 이동
        queue.current_index += 1

        if queue.current_index >= len(queue.tracks):
            # 재생 모드에 따른 동작
            if playback_mode == PLAYBACK_MODE_ONCE:
                # 1회재생: 재생 종료
                _LOGGER.info("[Queue] Playlist finished for %s (mode=once)", entity_id)
                await self._stop_queue(entity_id)
                return False

            elif playback_mode == PLAYBACK_MODE_SHUFFLE:
                # 랜덤재생: 다시 셔플하고 처음부터
                _LOGGER.info("[Queue] Re-shuffling playlist for %s", entity_id)
                queue.tracks = list(queue.original_tracks)
                random.shuffle(queue.tracks)
                queue.current_index = 0

            else:  # PLAYBACK_MODE_SEQUENTIAL
                # 순차반복: 처음부터 다시
                _LOGGER.info("[Queue] Looping playlist for %s (mode=sequential)", entity_id)
                queue.current_index = 0

        return True

    async def _play_current(self, entity_id: str) -> None:
        """Bound playback attempts without reacquiring the queue lock."""
        queue = self._queues.get(entity_id)
        if not queue or not queue.is_active:
            return

        for _ in range(len(queue.tracks)):
            if not 0 <= queue.current_index < len(queue.tracks):
                _LOGGER.warning("[Queue] Index out of range for %s", entity_id)
                break

            track = queue.tracks[queue.current_index]
            video_id = track.get("videoId") or track.get("setVideoId")
            title = track.get("title", "Unknown")

            if not video_id:
                _LOGGER.warning(
                    "[Queue] Track %d/%d has no videoId, skipping: %s",
                    queue.current_index + 1, len(queue.tracks), title,
                )
            elif self._play_callback:
                _LOGGER.info(
                    "[Queue] Playing track %d/%d on %s: %s (%s)",
                    queue.current_index + 1, len(queue.tracks),
                    entity_id, title, video_id,
                )
                queue.attempt += 1
                queue.command_at = None
                self._cancel_watchdog(queue)
                failed = False
                try:
                    result = await self._play_callback(entity_id, video_id, track)
                except Exception as err:
                    _LOGGER.error("[Queue] Failed to play track: %s", err)
                    failed = True
                else:
                    if result is False:
                        _LOGGER.error(
                            "[Queue] Failed to play track %s on %s", video_id, entity_id
                        )
                        failed = True
                    elif not queue.is_active:
                        # Stopped while the play command ran.
                        return
                    else:
                        queue.command_at = self._clock()
                        self._arm_watchdog(queue)
                        next_idx = queue.current_index + 1
                        if next_idx < len(queue.tracks):
                            next_track = queue.tracks[next_idx]
                            next_video_id = next_track.get("videoId") or next_track.get("setVideoId")
                            if next_video_id:
                                self._spawn(self._prefetch_metadata(next_video_id))
                        return
                if failed and self._too_many_failures(queue):
                    await self._stop_queue(entity_id)
                    return
            else:
                return

            if not await self._advance_queue(entity_id):
                return

        _LOGGER.warning("[Queue] No playable tracks remain for %s", entity_id)
        await self._stop_queue(entity_id)

    @staticmethod
    def _too_many_failures(queue: PlaybackQueue) -> bool:
        """Count a track that did not play; True once too many failed in a row.

        Bounds the work (one stream extraction per track) on a player that
        rejects or never starts every track.
        """
        queue.failures += 1
        if queue.failures < QUEUE_MAX_CONSECUTIVE_FAILURES:
            return False
        _LOGGER.warning(
            "[Queue] %d tracks in a row did not play on %s, ending its playlist",
            queue.failures, queue.entity_id,
        )
        return True

    def _arm_watchdog(self, queue: PlaybackQueue) -> None:
        """Skip the track if the player has not started it in time."""
        self._cancel_watchdog(queue)
        entity_id, attempt = queue.entity_id, queue.attempt

        @callback
        def _expired(_now) -> None:
            queue.cancel_watchdog = None
            self._spawn(self._check_started(entity_id, queue, attempt))

        queue.cancel_watchdog = async_call_later(
            self.hass, QUEUE_START_TIMEOUT_SECONDS, _expired
        )

    @staticmethod
    def _cancel_watchdog(queue: PlaybackQueue) -> None:
        if queue.cancel_watchdog is not None:
            queue.cancel_watchdog()
            queue.cancel_watchdog = None

    async def _check_started(
        self, entity_id: str, queue: PlaybackQueue, attempt: int
    ) -> None:
        async with self._lock:
            if not self._is_current(entity_id, queue, attempt) or not queue.is_active:
                return
            state = self.hass.states.get(entity_id)
            state_str = state.state if state is not None else None
            if state_str in _ACTIVE_STATES:
                queue.failures = 0
                return
            if state_str is None or state_str in _GONE_STATES:
                # Off, unavailable or removed: playing on would only wake the
                # player later by itself.
                _LOGGER.warning(
                    "[Queue] %s is %s, ending its playlist", entity_id, state_str or "missing"
                )
                await self._stop_queue(entity_id)
                return
            _LOGGER.warning(
                "[Queue] Track %d/%d did not start on %s within %d s, skipping",
                queue.current_index + 1, len(queue.tracks), entity_id,
                QUEUE_START_TIMEOUT_SECONDS,
            )
            if self._too_many_failures(queue):
                await self._stop_queue(entity_id)
                return
            if await self._advance_queue(entity_id):
                await self._play_current(entity_id)

    async def _prefetch_metadata(self, video_id: str) -> None:
        """Pre-fetch next track metadata to warm cache."""
        try:
            # Access StreamExtractor from hass.data
            domain_data = self.hass.data.get(DOMAIN, {})
            for entry_id, store in domain_data.items():
                if isinstance(store, dict):
                    extractor = store.get(DATA_EXTRACTOR)
                    if extractor is not None:
                        _LOGGER.debug("[Queue] Pre-fetching metadata for next track: %s", video_id)
                        await extractor.async_get_metadata(video_id)
                        _LOGGER.info("[Queue] Pre-fetch completed for %s", video_id)
                        return
            _LOGGER.debug("[Queue] No extractor found for pre-fetching")
        except Exception as err:
            # Pre-fetch failure is non-critical, just log at debug level
            _LOGGER.debug("[Queue] Pre-fetch failed for %s: %s", video_id, err)

    def get_queue_info(self, entity_id: str) -> dict[str, Any] | None:
        """Get queue information for an entity."""
        queue = self._queues.get(entity_id)
        if not queue:
            return None

        return {
            "entity_id": entity_id,
            "total_tracks": len(queue.tracks),
            "current_index": queue.current_index,
            "is_active": queue.is_active,
            "current_track": queue.tracks[queue.current_index] if queue.tracks else None,
        }

    def clear_all(self) -> None:
        """Clear all queues."""
        for entity_id in list(self._queues.keys()):
            queue = self._queues.pop(entity_id, None)
            if queue:
                queue.is_active = False
                self._cancel_watchdog(queue)
                if queue.unsubscribe:
                    queue.unsubscribe()
        self._release_service_listener()
        # Cancel any in-flight play-next / prefetch tasks so they do not
        # outlive the config entry on unload or reload.
        for task in list(self._background_tasks):
            task.cancel()
        self._background_tasks.clear()
        _LOGGER.info("[Queue] Cleared all queues")
