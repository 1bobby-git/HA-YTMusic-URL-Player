"""Playlist queue manager for continuous playback."""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Callable

from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.const import STATE_IDLE, STATE_PAUSED, STATE_PLAYING
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    DOMAIN,
    DATA_EXTRACTOR,
    DATA_PLAYBACK_MODE,
    PLAYBACK_MODE_SEQUENTIAL,
    PLAYBACK_MODE_ONCE,
    PLAYBACK_MODE_SHUFFLE,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class PlaybackQueue:
    """Playback queue for a single media_player."""
    entity_id: str
    tracks: list[dict[str, Any]] = field(default_factory=list)
    original_tracks: list[dict[str, Any]] = field(default_factory=list)  # 원본 순서 저장
    current_index: int = 0
    is_active: bool = False
    unsubscribe: Callable | None = None
    is_shuffled: bool = False  # 셔플 적용 여부


class QueueManager:
    """Manages playlist queues and continuous playback."""

    def __init__(self, hass: HomeAssistant, entry_id: str | None = None) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._queues: dict[str, PlaybackQueue] = {}
        self._play_callback: Callable | None = None
        self._lock = asyncio.Lock()

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
            is_shuffled = False

            # 랜덤재생 모드면 셔플
            if playback_mode == PLAYBACK_MODE_SHUFFLE:
                play_tracks = list(tracks)
                random.shuffle(play_tracks)
                is_shuffled = True
                start_index = 0  # 셔플 시 처음부터 재생
                _LOGGER.info("[Queue] Shuffled %d tracks", len(play_tracks))

            queue = PlaybackQueue(
                entity_id=entity_id,
                tracks=play_tracks,
                original_tracks=original_tracks,
                current_index=start_index,
                is_active=True,
                is_shuffled=is_shuffled,
            )

            # Subscribe to state changes
            queue.unsubscribe = async_track_state_change_event(
                self.hass,
                [entity_id],
                self._on_state_change,
            )

            self._queues[entity_id] = queue

            _LOGGER.info(
                "[Queue] Started playlist for %s: %d tracks, starting at %d, mode=%s",
                entity_id, len(play_tracks), start_index, playback_mode
            )

            # Play the first track
            await self._play_current(entity_id)

    async def stop_playlist(self, entity_id: str) -> None:
        """Stop the playlist queue for the given entity."""
        async with self._lock:
            await self._stop_queue(entity_id)

    async def _stop_queue(self, entity_id: str) -> None:
        """Internal: stop queue without lock."""
        queue = self._queues.pop(entity_id, None)
        if queue:
            queue.is_active = False
            if queue.unsubscribe:
                queue.unsubscribe()
            _LOGGER.info("[Queue] Stopped playlist for %s", entity_id)

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

        # Track finished: was playing, now idle
        if old_state_str == STATE_PLAYING and new_state_str == STATE_IDLE:
            _LOGGER.info("[Queue] Track finished on %s, playing next...", entity_id)
            asyncio.create_task(self._play_next(entity_id))

    async def _play_next(self, entity_id: str) -> None:
        """Play the next track in the queue."""
        async with self._lock:
            queue = self._queues.get(entity_id)
            if not queue or not queue.is_active:
                return

            queue.current_index += 1
            playback_mode = self._get_playback_mode()

            if queue.current_index >= len(queue.tracks):
                # 재생 모드에 따른 동작
                if playback_mode == PLAYBACK_MODE_ONCE:
                    # 1회재생: 재생 종료
                    _LOGGER.info("[Queue] Playlist finished for %s (mode=once)", entity_id)
                    await self._stop_queue(entity_id)
                    return

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

            await self._play_current(entity_id)

    async def _play_current(self, entity_id: str) -> None:
        """Play the current track in the queue."""
        queue = self._queues.get(entity_id)
        if not queue or not queue.is_active:
            return

        if queue.current_index >= len(queue.tracks):
            _LOGGER.warning("[Queue] Index out of range for %s", entity_id)
            return

        track = queue.tracks[queue.current_index]
        video_id = track.get("videoId") or track.get("setVideoId")
        title = track.get("title", "Unknown")

        _LOGGER.info(
            "[Queue] Playing track %d/%d on %s: %s (%s)",
            queue.current_index + 1, len(queue.tracks),
            entity_id, title, video_id
        )

        if self._play_callback and video_id:
            try:
                await self._play_callback(entity_id, video_id, track)

                # After current track starts playing, pre-fetch next track metadata
                next_idx = queue.current_index + 1
                if next_idx < len(queue.tracks):
                    next_track = queue.tracks[next_idx]
                    next_video_id = next_track.get("videoId") or next_track.get("setVideoId")
                    if next_video_id:
                        # Pre-fetch in background - don't await, just fire-and-forget
                        asyncio.create_task(self._prefetch_metadata(next_video_id))

            except Exception as e:
                _LOGGER.error("[Queue] Failed to play track: %s", e)
                # Try next track on error
                await self._play_next(entity_id)

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
            if queue and queue.unsubscribe:
                queue.unsubscribe()
        _LOGGER.info("[Queue] Cleared all queues")
