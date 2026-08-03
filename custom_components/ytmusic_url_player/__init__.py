from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client

from .const import (
    DOMAIN,
    DATA_YTMUSIC,
    DATA_EXTRACTOR,
    DATA_TARGET_OVERRIDE,
    DATA_QUEUE_MANAGER,
    DATA_CAST_MANAGER,
    DATA_PLAYBACK_MODE,
    PLAYBACK_MODE_SEQUENTIAL,
)
from .ytmusic_client import YTMusicClient
from .streaming import StreamExtractor, YTMusicM3UView, YTMusicStreamView
from .service import async_register_services, async_unregister_services
from .queue_manager import QueueManager
from .cast_manager import CastManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.TEXT, Platform.SELECT]

_VIEWS_REGISTERED = False


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    global _VIEWS_REGISTERED

    hass.data.setdefault(DOMAIN, {})
    store = hass.data[DOMAIN].setdefault(entry.entry_id, {})

    config = {**entry.data, **(entry.options or {})}

    # ytmusicapi init
    client = YTMusicClient(hass, config)
    await client.async_init()
    store[DATA_YTMUSIC] = client

    # Target override (set by select entity)
    store.setdefault(DATA_TARGET_OVERRIDE, None)

    # Playback mode (set by select entity)
    store.setdefault(DATA_PLAYBACK_MODE, PLAYBACK_MODE_SEQUENTIAL)

    # Stream extractor + HTTP views
    session = aiohttp_client.async_get_clientsession(hass)
    extractor = StreamExtractor(hass, config, session)
    store[DATA_EXTRACTOR] = extractor

    # Queue manager for playlist continuous playback
    queue_manager = QueueManager(hass, entry_id=entry.entry_id)
    store[DATA_QUEUE_MANAGER] = queue_manager

    # Cast manager for pychromecast connection caching
    cast_manager = CastManager(hass)
    store[DATA_CAST_MANAGER] = cast_manager

    # Register HTTP views only once (reload-safe)
    if not _VIEWS_REGISTERED and not hass.data[DOMAIN].get("_views_registered"):
        hass.http.register_view(YTMusicStreamView(hass))
        hass.http.register_view(YTMusicM3UView(hass))
        hass.data[DOMAIN]["_views_registered"] = True
        _VIEWS_REGISTERED = True

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async_register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        domain_store = hass.data.get(DOMAIN, {})
        entry_store = domain_store.pop(entry.entry_id, None)
        if entry_store:
            client = entry_store.get(DATA_YTMUSIC)
            if client:
                await client.async_close()
            queue_manager = entry_store.get(DATA_QUEUE_MANAGER)
            if queue_manager:
                queue_manager.clear_all()
            cast_manager = entry_store.get(DATA_CAST_MANAGER)
            if cast_manager:
                cast_manager.clear_cache()

        # Unregister domain service when no config entries remain
        remaining = [
            k for k, v in domain_store.items()
            if isinstance(v, dict) and k not in {"_views_registered"}
        ]
        if not remaining:
            async_unregister_services(hass)

    return unload_ok
