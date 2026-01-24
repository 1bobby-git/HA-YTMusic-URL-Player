"""Config flow for YouTube Music URL Player."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_NAME,
    CONF_MEDIA_PLAYER,
    CONF_AUTH_FILE,
    CONF_AUTO_PLAY,
    CONF_PO_TOKEN,
    CONF_VISITOR_DATA,
    DEFAULT_NAME,
    DEFAULT_AUTO_PLAY,
)


class YTMusicUrlPlayerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for YouTube Music URL Player."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is not None:
            return self.async_create_entry(
                title=user_input.get(CONF_NAME, DEFAULT_NAME),
                data=user_input,
            )

        schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_MEDIA_PLAYER): selector.selector(
                    {"entity": {"domain": "media_player", "multiple": True}}
                ),
                vol.Optional(CONF_AUTH_FILE, default=""): selector.selector(
                    {"text": {"multiline": True, "type": "text"}}
                ),
                vol.Optional(CONF_AUTO_PLAY, default=DEFAULT_AUTO_PLAY): bool,
                vol.Optional(CONF_PO_TOKEN, default=""): selector.selector(
                    {"text": {"type": "text"}}
                ),
                vol.Optional(CONF_VISITOR_DATA, default=""): selector.selector(
                    {"text": {"type": "text"}}
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)
