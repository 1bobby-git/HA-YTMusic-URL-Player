from __future__ import annotations

import logging

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, CONF_NAME, CONF_AUTO_PLAY, DEFAULT_NAME
from .service import async_play_url

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    async_add_entities([YTMusicUrlText(hass, entry)], update_before_add=False)

class YTMusicUrlText(TextEntity):
    _attr_has_entity_name = True
    _attr_name = "URL"
    _attr_icon = "mdi:youtube-music"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        cfg = {**entry.data, **(entry.options or {})}
        self._org_name = cfg.get(CONF_NAME, DEFAULT_NAME)
        self._auto_play = bool(cfg.get(CONF_AUTO_PLAY, True))
        self._attr_unique_id = f"{entry.entry_id}_url"
        self._attr_native_value = ""

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=self._org_name,
            manufacturer="Custom",
            model="URL Helper",
        )

    async def async_set_value(self, value: str) -> None:
        self._attr_native_value = value or ""
        self.async_write_ha_state()

        if not self._auto_play:
            return

        url = (value or "").strip()
        if not url:
            return

        try:
            # Let service logic decide targets (service override > select override > config default)
            await async_play_url(self.hass, self.entry, url, None)
        except Exception as err:
            _LOGGER.exception("Auto-play failed: %s", err)
