"""Cast device manager with connection caching and native YouTube support."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import get_url

from .const import CAST_CACHE_TTL_SECONDS, CAST_SCAN_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)


@dataclass
class CastDevice:
    """Cached Cast device info."""
    name: str
    host: str
    port: int
    uuid: str
    cast: Any  # pychromecast.Chromecast
    last_used: float


class CastManager:
    """Manages Cast device connections with caching."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._devices: dict[str, CastDevice] = {}  # key: friendly_name
        self._lock = asyncio.Lock()
        self._last_scan: float = 0
        self._scan_interval = CAST_SCAN_INTERVAL_SECONDS

    def _get_cast_type(self, cast: Any) -> str | None:
        """Get the cast device type (audio, cast, etc.)."""
        if hasattr(cast, 'cast_type'):
            return cast.cast_type
        elif hasattr(cast, 'cast_info') and hasattr(cast.cast_info, 'cast_type'):
            return cast.cast_info.cast_type
        return None

    async def async_get_cast_type(self, friendly_name: str) -> str | None:
        """Get the cast device type by friendly name (async version)."""
        cast = await self._get_cast_device(friendly_name)
        if not cast:
            return None
        return self._get_cast_type(cast)

    async def async_play_youtube_native(
        self,
        friendly_name: str,
        video_id: str,
        playlist_id: str | None = None,
        is_music_url: bool = False,
    ) -> bool:
        """Play YouTube/YouTube Music natively on Cast device.

        For devices WITH screen:
          - is_music_url=True  → YouTube Music app
          - is_music_url=False → YouTube video app
        For devices WITHOUT screen (audio-only):
          - Returns False to trigger direct stream fallback

        This is the preferred method for Cast devices as it:
        - Bypasses bot detection completely
        - Uses the appropriate app based on URL source
        - Supports video on devices with screens
        """
        import pychromecast
        from pychromecast.controllers.youtube import YouTubeController

        loop = asyncio.get_running_loop()

        # Get or find Cast device
        cast = await self._get_cast_device(friendly_name)
        if not cast:
            _LOGGER.error("[CastMgr] Cast device not found: %s", friendly_name)
            return False

        def _play_native() -> bool:
            try:
                cast.wait(timeout=10)

                # Check if device is audio-only (no screen)
                cast_type = self._get_cast_type(cast)
                _LOGGER.debug("[CastMgr] Device type: %s, is_music_url: %s", cast_type, is_music_url)

                # Audio-only devices (Google Home, etc.) - skip YouTube controllers
                # YouTube/YouTubeMusic controllers often fail on audio-only devices
                # Return False to trigger direct stream fallback
                if cast_type == 'audio':
                    _LOGGER.info("[CastMgr] Audio-only device detected, skipping YouTube controller (use direct stream)")
                    return False

                # Devices with screen - choose app based on URL source
                if is_music_url:
                    # YouTube Music URL → Try YouTube Music app first
                    try:
                        from pychromecast.controllers.ytmusic import YouTubeMusicController
                        ytm = YouTubeMusicController()
                        cast.register_handler(ytm)

                        _LOGGER.info("[CastMgr] Playing via YouTube Music app: %s", video_id)
                        ytm.play_song(video_id)
                        time.sleep(2)

                        _LOGGER.info("[CastMgr] ✓ YouTube Music native playback started: %s", video_id)
                        return True
                    except ImportError:
                        _LOGGER.warning("[CastMgr] YouTubeMusicController not available, falling back to YouTube app")
                    except Exception as e:
                        _LOGGER.warning("[CastMgr] YouTube Music app failed: %s, trying YouTube app...", e)

                # YouTube URL or YouTube Music app failed → Use YouTube video app
                yt = YouTubeController()
                cast.register_handler(yt)

                _LOGGER.info("[CastMgr] Playing via YouTube app: %s", video_id)

                if playlist_id:
                    yt.play_video(video_id, playlist_id)
                else:
                    yt.play_video(video_id)

                time.sleep(2)

                _LOGGER.info("[CastMgr] ✓ YouTube native playback started: %s", video_id)
                return True
            except Exception as e:
                _LOGGER.warning("[CastMgr] YouTube native play failed: %s", e)
                return False

        try:
            return await loop.run_in_executor(None, _play_native)
        except Exception as e:
            _LOGGER.error("[CastMgr] YouTube native error: %s", e)
            return False

    async def async_play_youtube_playlist(
        self,
        friendly_name: str,
        playlist_id: str,
        video_id: str | None = None,
    ) -> bool:
        """Play YouTube playlist natively on Cast device.

        Note: YouTubeController.play_video() requires a video_id.
        If no video_id is provided, this method cannot start the playlist.
        """
        import pychromecast
        from pychromecast.controllers.youtube import YouTubeController

        loop = asyncio.get_running_loop()

        # YouTubeController requires video_id - can't play playlist without it
        if not video_id:
            _LOGGER.warning("[CastMgr] Cannot play playlist without video_id (YouTube limitation)")
            return False

        cast = await self._get_cast_device(friendly_name)
        if not cast:
            _LOGGER.error("[CastMgr] Cast device not found: %s", friendly_name)
            return False

        def _play_playlist() -> bool:
            try:
                cast.wait(timeout=10)

                yt = YouTubeController()
                cast.register_handler(yt)

                _LOGGER.info("[CastMgr] Playing YouTube playlist: %s (starting from %s)", playlist_id, video_id)

                # Start playlist from specific video
                yt.play_video(video_id, playlist_id)

                time.sleep(2)

                _LOGGER.info("[CastMgr] ✓ YouTube playlist started: %s", playlist_id)
                return True
            except Exception as e:
                _LOGGER.warning("[CastMgr] YouTube playlist play failed: %s", e)
                return False

        try:
            return await loop.run_in_executor(None, _play_playlist)
        except Exception as e:
            _LOGGER.error("[CastMgr] YouTube playlist error: %s", e)
            return False

    async def async_play_media_direct(
        self,
        friendly_name: str,
        stream_url: str,
        mime_type: str,
        title: str,
        thumb_url: str | None = None,
    ) -> bool:
        """Play media directly on Cast device using the stream URL (bypasses HA proxy).

        This method sends the YouTube stream URL directly to the Cast device,
        which avoids network issues with HA's internal URL.
        """
        import pychromecast

        loop = asyncio.get_running_loop()

        cast = await self._get_cast_device(friendly_name)
        if not cast:
            _LOGGER.error("[CastMgr] Cast device not found: %s", friendly_name)
            return False

        def _play_direct() -> bool:
            try:
                cast.wait(timeout=10)
                mc = cast.media_controller

                _LOGGER.info("[CastMgr] Playing direct stream: %s", title)
                mc.play_media(
                    stream_url,
                    mime_type,
                    title=title,
                    thumb=thumb_url,
                )
                mc.block_until_active(timeout=30)
                _LOGGER.info("[CastMgr] ✓ Direct stream playing: %s", title)
                return True
            except Exception as e:
                _LOGGER.warning("[CastMgr] Direct play failed: %s", e)
                return False

        try:
            return await loop.run_in_executor(None, _play_direct)
        except Exception as e:
            _LOGGER.error("[CastMgr] Direct play error: %s", e)
            return False

    async def async_play_media(
        self,
        friendly_name: str,
        video_id: str,
        title: str,
        thumb_url: str | None = None,
    ) -> bool:
        """Play media on a Cast device by friendly name (proxy method - fallback)."""
        import pychromecast

        loop = asyncio.get_running_loop()

        # Build URL candidates - internal first (Cast device is on local network)
        url_candidates = []
        try:
            internal = get_url(self.hass, prefer_external=False)
            url_candidates.append(internal)
            _LOGGER.info("[CastMgr] Internal URL: %s", internal)
        except Exception:
            pass
        try:
            external = get_url(self.hass, prefer_external=True)
            if external not in url_candidates:
                url_candidates.append(external)
                _LOGGER.info("[CastMgr] External URL: %s", external)
        except Exception:
            pass

        if not url_candidates:
            _LOGGER.error("[CastMgr] No URL candidates available")
            return False

        # Get or find Cast device
        cast = await self._get_cast_device(friendly_name)
        if not cast:
            _LOGGER.error("[CastMgr] Cast device not found: %s", friendly_name)
            return False

        # Try each URL
        for base_url in url_candidates:
            from .const import DOMAIN
            media_url = f"{base_url}/api/{DOMAIN}/stream/{video_id}"
            _LOGGER.info("[CastMgr] Trying URL: %s", media_url[:80])

            def _play() -> bool:
                try:
                    cast.wait(timeout=10)
                    mc = cast.media_controller
                    mc.play_media(
                        media_url,
                        "audio/mp4",
                        title=title,
                        thumb=thumb_url,
                    )
                    mc.block_until_active(timeout=30)
                    _LOGGER.info("[CastMgr] ✓ Playing: %s", title)
                    return True
                except Exception as e:
                    _LOGGER.warning("[CastMgr] Play failed: %s", e)
                    return False

            try:
                success = await loop.run_in_executor(None, _play)
                if success:
                    return True
            except Exception as e:
                _LOGGER.warning("[CastMgr] Failed with %s: %s", base_url, e)
                continue

        _LOGGER.error("[CastMgr] All URLs failed for %s", friendly_name)
        return False

    async def _get_cast_device(self, friendly_name: str) -> Any | None:
        """Get Cast device, using cache if available."""
        import pychromecast

        async with self._lock:
            now = time.time()

            # Check cache first
            cached = self._devices.get(friendly_name)
            if cached and (now - cached.last_used) < CAST_CACHE_TTL_SECONDS:
                _LOGGER.debug("[CastMgr] Using cached device: %s", friendly_name)
                cached.last_used = now
                return cached.cast

            # Need to scan for devices
            if (now - self._last_scan) < self._scan_interval and self._devices:
                # Recent scan, device might not exist
                _LOGGER.debug("[CastMgr] Recent scan, device not in cache")
                # Try to find by partial name match
                for name, device in self._devices.items():
                    if friendly_name in name or name in friendly_name:
                        device.last_used = now
                        return device.cast
                return None

            # Scan for Cast devices
            _LOGGER.info("[CastMgr] Scanning for Cast devices...")
            loop = asyncio.get_running_loop()

            def _scan():
                try:
                    chromecasts, browser = pychromecast.get_chromecasts(timeout=10)
                    pychromecast.discovery.stop_discovery(browser)
                    return chromecasts
                except Exception as e:
                    _LOGGER.error("[CastMgr] Scan failed: %s", e)
                    return []

            chromecasts = await loop.run_in_executor(None, _scan)
            self._last_scan = now

            _LOGGER.info("[CastMgr] Found %d Cast devices", len(chromecasts))

            # Update cache
            found_device = None
            for cc in chromecasts:
                # pychromecast 14.x uses cast_info for device details
                cast_info = cc.cast_info if hasattr(cc, 'cast_info') else cc
                host = getattr(cast_info, 'host', None) or getattr(cc, 'host', 'unknown')
                port = getattr(cast_info, 'port', None) or getattr(cc, 'port', 8009)
                uuid = str(getattr(cast_info, 'uuid', None) or getattr(cc, 'uuid', ''))
                name = getattr(cc, 'name', '') or getattr(cast_info, 'friendly_name', '')

                device = CastDevice(
                    name=name,
                    host=host,
                    port=port,
                    uuid=uuid,
                    cast=cc,
                    last_used=now,
                )
                self._devices[name] = device
                _LOGGER.debug("[CastMgr] Cached: %s (IP: %s)", name, host)

                # Check if this is the one we're looking for
                if friendly_name in name or name in friendly_name:
                    found_device = cc

            return found_device

    def clear_cache(self) -> None:
        """Clear all cached devices."""
        self._devices.clear()
        self._last_scan = 0
        _LOGGER.info("[CastMgr] Cache cleared")
