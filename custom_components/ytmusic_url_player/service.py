"""Playback service with playlist queue support."""
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
    # Method 1: Check if entity is from cast integration
    if entity_id.startswith("media_player."):
        state = hass.states.get(entity_id)
        if state:
            # Check for cast-specific attributes
            attrs = state.attributes
            # Cast devices have app_id, app_name attributes
            if "app_id" in attrs or "app_name" in attrs:
                return True
            # Check entity registry for platform
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
    """Get the friendly name of a Cast device for pychromecast."""
    state = hass.states.get(entity_id)
    if state:
        return state.attributes.get("friendly_name") or state.name
    return None


async def _play_single_track(
    hass: HomeAssistant,
    entity_id: str,
    video_id: str,
    track_info: dict,
) -> bool:
    """Play a single track on the media_player.

    This is the callback used by QueueManager for playlist playback.
    For Cast devices: Uses native YouTube playback
    For other devices: Uses HA proxy URL
    """
    _LOGGER.info("[Track] Playing %s on %s", video_id, entity_id)

    # Check if this is a Cast device - use native YouTube playback
    if _is_cast_device(hass, entity_id):
        cast_manager = _get_cast_manager(hass)
        friendly_name = _get_cast_friendly_name(hass, entity_id)

        if cast_manager and friendly_name:
            try:
                success = await cast_manager.async_play_youtube_native(
                    friendly_name, video_id
                )
                if success:
                    _LOGGER.info("[Track] ✓ Native YouTube playback: %s", video_id)
                    return True
                else:
                    _LOGGER.warning("[Track] Native YouTube failed, trying proxy fallback...")
            except Exception as e:
                _LOGGER.warning("[Track] Native YouTube error: %s, trying proxy fallback...", e)

    # Fallback: Extract stream and play directly or via proxy
    _LOGGER.info("[Track] Using fallback for: %s", entity_id)

    extractor = _get_extractor(hass)
    title = None
    thumb_url = None
    mime_type = "audio/mp4"
    stream_url = None

    if extractor:
        try:
            metadata = await extractor.async_get_metadata(video_id)
            _LOGGER.info("[Track] Extracted stream for: %s (mime: %s)", metadata.title, metadata.mime_type)
            title = metadata.title
            thumb_url = metadata.thumbnail_url
            mime_type = metadata.mime_type or "audio/mp4"
            stream_url = metadata.stream_url
        except Exception as e:
            _LOGGER.warning("[Track] Failed to extract stream: %s", e)

    # Use track_info for metadata if not from extractor
    if not title:
        track_title = track_info.get("title", "")
        artists = track_info.get("artists", [])
        artist_name = artists[0].get("name", "") if artists else ""
        title = f"{artist_name} - {track_title}".strip(" -") if artist_name else track_title

    if not thumb_url:
        thumbnails = track_info.get("thumbnails", [])
        thumb_url = thumbnails[-1].get("url") if thumbnails else None

    # For Cast devices, try direct stream first (bypasses HA proxy network issues)
    if _is_cast_device(hass, entity_id) and stream_url:
        cast_manager = _get_cast_manager(hass)
        friendly_name = _get_cast_friendly_name(hass, entity_id)

        if cast_manager and friendly_name:
            try:
                _LOGGER.info("[Track] Trying direct stream to Cast device...")
                success = await cast_manager.async_play_media_direct(
                    friendly_name,
                    stream_url,
                    mime_type,
                    title or video_id,
                    thumb_url,
                )
                if success:
                    _LOGGER.info("[Track] ✓ Direct stream success: %s", title or video_id)
                    return True
                else:
                    _LOGGER.warning("[Track] Direct stream failed, trying HA proxy...")
            except Exception as e:
                _LOGGER.warning("[Track] Direct stream error: %s, trying HA proxy...", e)

    # Fallback: Use HA proxy URL
    try:
        base_url = get_url(hass, prefer_external=False)
    except Exception:
        try:
            base_url = get_url(hass, prefer_external=True)
        except Exception as e:
            _LOGGER.error("[Track] Cannot get base URL: %s", e)
            return False

    media_url = f"{base_url}/api/{DOMAIN}/{API_STREAM_PATH}/{video_id}"
    _LOGGER.info("[Track] Media URL: %s", media_url)

    # Build service data
    service_data = {
        "entity_id": entity_id,
        "media_content_type": mime_type,
        "media_content_id": media_url,
    }

    # Add metadata if available
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
        _LOGGER.info("[Track] ✓ Success: %s", title or video_id)
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
) -> bool:
    """Play a video on a media_player device.

    For Cast devices: Try native YouTube casting first (bypasses bot detection)
    For other devices: Use HA proxy URL approach
    """
    _LOGGER.info("[Play] Starting playback: %s on %s", video_id, entity_id)

    # Check if this is a Cast device - try native YouTube playback first
    if _is_cast_device(hass, entity_id):
        _LOGGER.info("[Play] Detected Cast device, trying native YouTube playback")
        cast_manager = _get_cast_manager(hass)
        friendly_name = _get_cast_friendly_name(hass, entity_id)

        if cast_manager and friendly_name:
            try:
                if playlist_id:
                    success = await cast_manager.async_play_youtube_native(
                        friendly_name, video_id, playlist_id
                    )
                else:
                    success = await cast_manager.async_play_youtube_native(
                        friendly_name, video_id
                    )

                if success:
                    _LOGGER.info("[Play] ✓ Native YouTube playback started: %s", video_id)
                    return True
                else:
                    _LOGGER.warning("[Play] Native YouTube playback failed, trying proxy fallback...")
            except Exception as e:
                _LOGGER.warning("[Play] Native YouTube error: %s, trying proxy fallback...", e)

    # Fallback: Extract stream and play directly or via proxy
    _LOGGER.info("[Play] Using fallback for: %s", entity_id)

    # Get extractor to extract stream
    extractor = _get_extractor(hass)
    mime_type = "audio/mp4"
    stream_url = None

    if extractor:
        try:
            metadata = await extractor.async_get_metadata(video_id)
            _LOGGER.info("[Play] Extracted stream for: %s (mime: %s)", metadata.title, metadata.mime_type)
            if not title:
                title = metadata.title
            if not thumb_url:
                thumb_url = metadata.thumbnail_url
            mime_type = metadata.mime_type or "audio/mp4"
            stream_url = metadata.stream_url
        except Exception as e:
            _LOGGER.warning("[Play] Failed to extract stream: %s", e)

    # For Cast devices, try direct stream first (bypasses HA proxy network issues)
    if _is_cast_device(hass, entity_id) and stream_url:
        cast_manager = _get_cast_manager(hass)
        friendly_name = _get_cast_friendly_name(hass, entity_id)

        if cast_manager and friendly_name:
            try:
                _LOGGER.info("[Play] Trying direct stream to Cast device...")
                success = await cast_manager.async_play_media_direct(
                    friendly_name,
                    stream_url,
                    mime_type,
                    title or video_id,
                    thumb_url,
                )
                if success:
                    _LOGGER.info("[Play] ✓ Direct stream success: %s", title or video_id)
                    return True
                else:
                    _LOGGER.warning("[Play] Direct stream failed, trying HA proxy...")
            except Exception as e:
                _LOGGER.warning("[Play] Direct stream error: %s, trying HA proxy...", e)

    # Fallback: Use HA proxy URL
    try:
        base_url = get_url(hass, prefer_external=False)
    except Exception:
        try:
            base_url = get_url(hass, prefer_external=True)
        except Exception as e:
            _LOGGER.error("[Play] Cannot get base URL: %s", e)
            return False

    media_url = f"{base_url}/api/{DOMAIN}/{API_STREAM_PATH}/{video_id}"
    _LOGGER.info("[Play] Media URL: %s", media_url)

    # Build service data
    service_data = {
        "entity_id": entity_id,
        "media_content_type": mime_type,
        "media_content_id": media_url,
    }

    # Add metadata if available
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
        _LOGGER.info("[Play] ✓ Success: %s", title or video_id)
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
    _LOGGER.info("[Service] play_url called")
    _LOGGER.info("[Service] URL: %s", url)
    _LOGGER.info("[Service] Target: %s", target_media_player)

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
        _LOGGER.error("[Service] No target media_player configured")
        raise ValueError("No target media_player configured")

    _LOGGER.info("[Service] Targets: %s", targets)

    # Parse URL
    parsed = parse_url(url)
    if not parsed.video_id and not parsed.list_id:
        _LOGGER.error("[Service] Could not parse URL: %s", url)
        raise ValueError(f"Could not parse URL: {url}")

    _LOGGER.info("[Service] Parsed: video=%s, list=%s", parsed.video_id, parsed.list_id)

    # Get clients
    client = _get_ytmusic_client(hass)
    queue_manager = _get_queue_manager(hass)
    cast_manager = _get_cast_manager(hass)

    # Check if all targets are Cast devices - try native YouTube playback first
    all_cast = all(_is_cast_device(hass, t) for t in targets)

    if all_cast and cast_manager and parsed.video_id:
        # Native YouTube requires video_id
        _LOGGER.info("[Service] All targets are Cast devices, trying native YouTube playback")

        native_success = []
        native_failed = []

        for target in targets:
            friendly_name = _get_cast_friendly_name(hass, target)
            if not friendly_name:
                native_failed.append(target)
                continue

            try:
                if parsed.list_id:
                    # Native YouTube playlist playback (requires video_id)
                    _LOGGER.info("[Service] Playing YouTube playlist natively: %s", parsed.list_id)
                    success = await cast_manager.async_play_youtube_native(
                        friendly_name, parsed.video_id, parsed.list_id
                    )
                else:
                    # Native YouTube single video
                    success = await cast_manager.async_play_youtube_native(
                        friendly_name, parsed.video_id
                    )

                if success:
                    native_success.append(target)
                    _LOGGER.info("[Service] ✓ Native YouTube started on %s", target)
                else:
                    native_failed.append(target)
                    _LOGGER.info("[Service] Native YouTube failed on %s (no YouTube app?)", target)
            except Exception as e:
                native_failed.append(target)
                _LOGGER.warning("[Service] Native YouTube failed on %s: %s", target, e)

        if native_success:
            _LOGGER.info("[Service] ✓ Native YouTube playback on %d/%d devices", len(native_success), len(targets))

            # If some devices failed, try proxy fallback for those
            if native_failed:
                _LOGGER.info("[Service] Trying proxy fallback for %d devices without YouTube app...", len(native_failed))
                targets = native_failed  # Continue with failed devices only
            else:
                return  # All succeeded

        if not native_success:
            _LOGGER.warning("[Service] Native YouTube failed on all devices, trying proxy fallback...")

    # Handle playlist with QueueManager for continuous playback (non-Cast or fallback)
    if parsed.list_id and queue_manager and client:
        _LOGGER.info("[Service] Playlist detected, using QueueManager for continuous playback")

        try:
            # Get playlist tracks
            tracks = await client.async_get_playlist_video_ids(parsed.list_id, parsed.video_id)

            if tracks:
                # Find start index if video_id is specified
                start_index = 0
                if parsed.video_id:
                    for i, track in enumerate(tracks):
                        if track.get("videoId") == parsed.video_id:
                            start_index = i
                            break

                _LOGGER.info("[Service] Playlist loaded: %d tracks, starting at %d",
                            len(tracks), start_index)

                # Set up callback for queue manager
                async def play_callback(entity_id: str, video_id: str, track_info: dict):
                    return await _play_single_track(hass, entity_id, video_id, track_info)

                queue_manager.set_play_callback(play_callback)

                # Start playlist on first target (queue manager handles one entity at a time)
                success_count = 0
                for target in targets:
                    try:
                        await queue_manager.start_playlist(
                            entity_id=target,
                            tracks=tracks,
                            start_index=start_index,
                        )
                        success_count += 1
                    except Exception as e:
                        _LOGGER.error("[Service] Failed to start playlist on %s: %s", target, e)

                if success_count > 0:
                    _LOGGER.info("[Service] ✓ Playlist started on %d devices", success_count)
                    return

                _LOGGER.warning("[Service] Playlist start failed, falling back to single track")
            else:
                _LOGGER.warning("[Service] Empty playlist, falling back to single track")

        except Exception as e:
            _LOGGER.error("[Service] Failed to load playlist: %s", e)
            # Fall through to single track playback

    # Single track playback (or playlist fallback)
    video_id = parsed.video_id

    if not video_id and parsed.list_id:
        # Playlist URL without video_id - get first track
        if client:
            try:
                _LOGGER.info("[Service] Getting first track from playlist: %s", parsed.list_id)
                tracks = await client.async_get_playlist_video_ids(parsed.list_id, None)
                if tracks and len(tracks) > 0:
                    video_id = tracks[0].get("videoId")
                    _LOGGER.info("[Service] First track: %s", video_id)
            except Exception as e:
                _LOGGER.error("[Service] Failed to get playlist: %s", e)

    if not video_id:
        _LOGGER.error("[Service] No video_id available")
        raise ValueError("No video_id available from URL")

    # Play on each target
    success_count = 0
    for target in targets:
        try:
            if await _play_on_device(hass, target, video_id):
                success_count += 1
        except Exception as e:
            _LOGGER.exception("[Service] Error playing on %s: %s", target, e)

    _LOGGER.info("[Service] Completed: %d/%d devices succeeded", success_count, len(targets))

    if success_count == 0:
        raise RuntimeError(f"Playback failed on all {len(targets)} devices")


def _entity_or_entities(value):
    if value is None:
        return None
    if isinstance(value, str):
        return cv.entity_id(value)
    if isinstance(value, list):
        return [cv.entity_id(v) for v in value]
    raise vol.Invalid("media_player must be an entity_id or a list of entity_ids")


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
            _LOGGER.error("[Service] No config entry found")
            raise RuntimeError("No config entry found for ytmusic_url_player")

        entry = entries[0]
        await async_play_url(hass, entry, url, target)

    hass.services.async_register(DOMAIN, SERVICE_PLAY_URL, _handle, schema=SERVICE_SCHEMA)
