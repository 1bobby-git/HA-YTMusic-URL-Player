"""Playback service with playlist queue support - Simplified v1.6 style."""
from __future__ import annotations

import logging
from typing import Optional

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.network import get_url

from .const import (
    DOMAIN,
    CONF_MEDIA_PLAYER,
    DATA_TARGET_OVERRIDE,
    DATA_QUEUE_MANAGER,
    DATA_CAST_MANAGER,
    DATA_EXTRACTOR,
    DATA_YTMUSIC,
    API_STREAM_PATH,
)
from .url_parser import parse_url
from .queue_manager import QueueManager
from .cast_manager import CastManager

_LOGGER = logging.getLogger(__name__)

SERVICE_PLAY_URL = "play_url"


def _get_domain_data_item(hass: HomeAssistant, key: str):
    """Get item from the first available config entry in domain data."""
    domain_data = hass.data.get(DOMAIN, {})
    for entry_id, store in domain_data.items():
        if isinstance(store, dict):
            item = store.get(key)
            if item is not None:
                return item
    return None


def _get_extractor(hass: HomeAssistant):
    """Get StreamExtractor from domain data."""
    return _get_domain_data_item(hass, DATA_EXTRACTOR)


def _get_ytmusic_client(hass: HomeAssistant):
    """Get YTMusicClient from domain data."""
    return _get_domain_data_item(hass, DATA_YTMUSIC)


def _get_queue_manager(hass: HomeAssistant) -> QueueManager | None:
    """Get QueueManager from domain data."""
    return _get_domain_data_item(hass, DATA_QUEUE_MANAGER)


def _get_cast_manager(hass: HomeAssistant) -> CastManager | None:
    """Get CastManager from domain data."""
    return _get_domain_data_item(hass, DATA_CAST_MANAGER)


def _is_cast_device(hass: HomeAssistant, entity_id: str) -> bool:
    """Check if entity is a Google Cast device."""
    if entity_id.startswith("media_player."):
        state = hass.states.get(entity_id)
        if state:
            attrs = state.attributes
            if "app_id" in attrs or "app_name" in attrs:
                return True
            try:
                from homeassistant.helpers import entity_registry as er
                registry = er.async_get(hass)
                entry = registry.async_get(entity_id)
                if entry and entry.platform == "cast":
                    return True
            except Exception:
                pass
    return False


def _get_cast_friendly_name(hass: HomeAssistant, entity_id: str) -> str | None:
    """Get the friendly name of a Cast device."""
    state = hass.states.get(entity_id)
    if state:
        return state.attributes.get("friendly_name") or state.name
    return None


def _get_base_url(hass: HomeAssistant) -> str:
    """Get base URL for HA proxy - simple approach like v1.6."""
    # Try internal first (most common for local Cast devices)
    try:
        return get_url(hass, prefer_external=False)
    except Exception:
        pass
    # Fallback to external
    try:
        return get_url(hass, prefer_external=True)
    except Exception:
        pass
    # Last resort - use localhost (won't work for Cast but at least won't crash)
    return "http://localhost:8123"


async def _play_single_track(
    hass: HomeAssistant,
    entity_id: str,
    video_id: str,
    track_info: dict,
    is_music_url: bool = False,
) -> bool:
    """Play a single track on the media_player - v1.6 style (simple).

    Uses HA's media_player.play_media for all devices.
    Native YouTube is only attempted for Cast devices WITH screen.
    """
    _LOGGER.info("[Track] Playing %s on %s", video_id, entity_id)

    # For Cast devices WITH screen, try native YouTube first (better UX)
    if _is_cast_device(hass, entity_id):
        cast_manager = _get_cast_manager(hass)
        friendly_name = _get_cast_friendly_name(hass, entity_id)

        if cast_manager and friendly_name:
            cast_type = await cast_manager.async_get_cast_type(friendly_name)
            _LOGGER.debug("[Track] Cast device type: %s", cast_type)

            # Only try native YouTube for devices with screen (cast type)
            if cast_type and cast_type != 'audio':
                try:
                    success = await cast_manager.async_play_youtube_native(
                        friendly_name, video_id, None, is_music_url
                    )
                    if success:
                        _LOGGER.info("[Track] ✓ Native YouTube: %s", video_id)
                        return True
                except Exception as e:
                    _LOGGER.debug("[Track] Native YouTube failed: %s", e)

    # Standard approach: Extract metadata and use HA proxy (v1.6 style)
    extractor = _get_extractor(hass)
    title = None
    thumb_url = None
    mime_type = "audio/mp4"

    if extractor:
        try:
            metadata = await extractor.async_get_metadata(video_id)
            title = metadata.title
            thumb_url = metadata.thumbnail_url
            mime_type = metadata.mime_type or "audio/mp4"
            _LOGGER.info("[Track] Metadata: %s", title)
        except Exception as e:
            _LOGGER.warning("[Track] Metadata extraction failed: %s", e)

    # Use track_info as fallback for metadata
    if not title:
        track_title = track_info.get("title", "")
        artists = track_info.get("artists", [])
        artist_name = artists[0].get("name", "") if artists else ""
        title = f"{artist_name} - {track_title}".strip(" -") if artist_name else track_title

    if not thumb_url:
        thumbnails = track_info.get("thumbnails", [])
        thumb_url = thumbnails[-1].get("url") if thumbnails else None

    # Build HA proxy URL (v1.6 style - simple)
    base_url = _get_base_url(hass)
    media_url = f"{base_url}/api/{DOMAIN}/{API_STREAM_PATH}/{video_id}"
    _LOGGER.info("[Track] Proxy URL: %s", media_url[:80])

    # Call media_player.play_media (v1.6 style)
    service_data = {
        "entity_id": entity_id,
        "media_content_type": mime_type,
        "media_content_id": media_url,
    }

    if title or thumb_url:
        service_data["extra"] = {}
        if title:
            service_data["extra"]["title"] = title
        if thumb_url:
            service_data["extra"]["thumb"] = thumb_url

    try:
        await hass.services.async_call(
            "media_player", "play_media",
            service_data,
            blocking=True,
        )
        _LOGGER.info("[Track] ✓ Playing: %s", title or video_id)
        return True
    except Exception as err:
        _LOGGER.error("[Track] ✗ Failed: %s", err)
        return False


async def _play_on_device(
    hass: HomeAssistant,
    entity_id: str,
    video_id: str,
    title: str | None = None,
    thumb_url: str | None = None,
    playlist_id: str | None = None,
    is_music_url: bool = False,
) -> bool:
    """Play a video on a media_player device - v1.6 style (simple).

    Uses HA's media_player.play_media for all devices.
    Native YouTube is only attempted for Cast devices WITH screen.
    """
    _LOGGER.info("[Play] Starting: %s on %s", video_id, entity_id)

    # For Cast devices WITH screen, try native YouTube first
    if _is_cast_device(hass, entity_id):
        cast_manager = _get_cast_manager(hass)
        friendly_name = _get_cast_friendly_name(hass, entity_id)

        if cast_manager and friendly_name:
            cast_type = await cast_manager.async_get_cast_type(friendly_name)
            _LOGGER.debug("[Play] Cast device type: %s", cast_type)

            # Only try native YouTube for devices with screen
            if cast_type and cast_type != 'audio':
                try:
                    success = await cast_manager.async_play_youtube_native(
                        friendly_name, video_id, playlist_id, is_music_url
                    )
                    if success:
                        _LOGGER.info("[Play] ✓ Native YouTube: %s", video_id)
                        return True
                except Exception as e:
                    _LOGGER.debug("[Play] Native YouTube failed: %s", e)

    # Standard approach: Extract metadata and use HA proxy (v1.6 style)
    extractor = _get_extractor(hass)
    mime_type = "audio/mp4"

    if extractor:
        try:
            metadata = await extractor.async_get_metadata(video_id)
            if not title:
                title = metadata.title
            if not thumb_url:
                thumb_url = metadata.thumbnail_url
            mime_type = metadata.mime_type or "audio/mp4"
            _LOGGER.info("[Play] Metadata: %s", title)
        except Exception as e:
            _LOGGER.warning("[Play] Metadata extraction failed: %s", e)

    # Build HA proxy URL (v1.6 style - simple)
    base_url = _get_base_url(hass)
    media_url = f"{base_url}/api/{DOMAIN}/{API_STREAM_PATH}/{video_id}"
    _LOGGER.info("[Play] Proxy URL: %s", media_url[:80])

    # Call media_player.play_media (v1.6 style)
    service_data = {
        "entity_id": entity_id,
        "media_content_type": mime_type,
        "media_content_id": media_url,
    }

    if title or thumb_url:
        service_data["extra"] = {}
        if title:
            service_data["extra"]["title"] = title
        if thumb_url:
            service_data["extra"]["thumb"] = thumb_url

    _LOGGER.info("[Play] Calling media_player.play_media")

    try:
        await hass.services.async_call(
            "media_player", "play_media",
            service_data,
            blocking=True,
        )
        _LOGGER.info("[Play] ✓ Playing: %s", title or video_id)
        return True
    except Exception as err:
        _LOGGER.error("[Play] ✗ Failed: %s", err)
        return False


async def async_play_url(
    hass: HomeAssistant,
    entry: ConfigEntry,
    url: str,
    target_media_player: Optional[str | list[str]] = None,
) -> None:
    """Main entry point for URL playback."""
    _LOGGER.info("=" * 60)
    _LOGGER.info("[Service] play_url: %s", url)

    cfg = {**entry.data, **(entry.options or {})}
    configured = cfg.get(CONF_MEDIA_PLAYER)

    # Determine target(s)
    targets = []
    if target_media_player:
        if isinstance(target_media_player, str):
            targets = [target_media_player]
        else:
            targets = list(target_media_player)

    if not targets:
        store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        override = store.get(DATA_TARGET_OVERRIDE)
        if override:
            targets = [override] if isinstance(override, str) else list(override)

    if not targets:
        if configured:
            targets = [configured] if isinstance(configured, str) else list(configured)

    if not targets:
        _LOGGER.error("[Service] No target media_player")
        raise ValueError("No target media_player configured")

    _LOGGER.info("[Service] Targets: %s", targets)

    # Parse URL
    parsed = parse_url(url)
    if not parsed.video_id and not parsed.list_id:
        _LOGGER.error("[Service] Invalid URL: %s", url)
        raise ValueError(f"Could not parse URL: {url}")

    _LOGGER.info("[Service] Parsed: video=%s, list=%s, is_music=%s",
                 parsed.video_id, parsed.list_id, parsed.is_music_url)

    # Get clients
    client = _get_ytmusic_client(hass)
    queue_manager = _get_queue_manager(hass)

    # Handle playlist with QueueManager
    if parsed.list_id and queue_manager and client:
        _LOGGER.info("[Service] Playlist mode")

        try:
            tracks = await client.async_get_playlist_video_ids(parsed.list_id, parsed.video_id)

            if tracks:
                start_index = 0
                if parsed.video_id:
                    for i, track in enumerate(tracks):
                        if track.get("videoId") == parsed.video_id:
                            start_index = i
                            break

                _LOGGER.info("[Service] %d tracks, starting at %d", len(tracks), start_index)

                # Callback with is_music_url captured
                is_music = parsed.is_music_url
                async def play_callback(entity_id: str, video_id: str, track_info: dict):
                    return await _play_single_track(hass, entity_id, video_id, track_info, is_music)

                queue_manager.set_play_callback(play_callback)

                for target in targets:
                    try:
                        await queue_manager.start_playlist(
                            entity_id=target,
                            tracks=tracks,
                            start_index=start_index,
                        )
                    except Exception as e:
                        _LOGGER.error("[Service] Playlist start failed on %s: %s", target, e)

                return

        except Exception as e:
            _LOGGER.error("[Service] Playlist load failed: %s", e)

    # Single track playback
    video_id = parsed.video_id

    if not video_id and parsed.list_id and client:
        try:
            tracks = await client.async_get_playlist_video_ids(parsed.list_id, None)
            if tracks:
                video_id = tracks[0].get("videoId")
        except Exception as e:
            _LOGGER.error("[Service] Failed to get first track: %s", e)

    if not video_id:
        raise ValueError("No video_id available")

    # Play on each target
    success_count = 0
    for target in targets:
        try:
            if await _play_on_device(hass, target, video_id, is_music_url=parsed.is_music_url):
                success_count += 1
        except Exception as e:
            _LOGGER.exception("[Service] Error on %s: %s", target, e)

    _LOGGER.info("[Service] Done: %d/%d succeeded", success_count, len(targets))

    if success_count == 0:
        raise RuntimeError(f"Playback failed on all {len(targets)} devices")


def _entity_or_entities(value):
    if value is None:
        return None
    if isinstance(value, str):
        return cv.entity_id(value)
    if isinstance(value, list):
        return [cv.entity_id(v) for v in value]
    raise vol.Invalid("media_player must be an entity_id or a list")


SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("url"): cv.string,
        vol.Optional(CONF_MEDIA_PLAYER): _entity_or_entities,
    }
)


def async_register_services(hass: HomeAssistant) -> None:
    """Register the play_url service."""
    if hass.services.has_service(DOMAIN, SERVICE_PLAY_URL):
        return

    async def _handle(call: ServiceCall) -> None:
        url = call.data["url"]
        target = call.data.get(CONF_MEDIA_PLAYER)

        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            raise RuntimeError("No config entry found")

        entry = entries[0]
        await async_play_url(hass, entry, url, target)

    hass.services.async_register(DOMAIN, SERVICE_PLAY_URL, _handle, schema=SERVICE_SCHEMA)
