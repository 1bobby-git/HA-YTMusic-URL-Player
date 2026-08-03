"""Config flow for YouTube Music URL Player."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
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


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Optional(
                CONF_NAME,
                default=defaults.get(CONF_NAME, DEFAULT_NAME),
            ): str,
            vol.Required(
                CONF_MEDIA_PLAYER,
                default=defaults.get(CONF_MEDIA_PLAYER, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player", multiple=True)
            ),
            vol.Optional(
                CONF_AUTH_FILE,
                default=defaults.get(CONF_AUTH_FILE, ""),
            ): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True, type=selector.TextSelectorType.TEXT)
            ),
            vol.Optional(
                CONF_AUTO_PLAY,
                default=bool(defaults.get(CONF_AUTO_PLAY, DEFAULT_AUTO_PLAY)),
            ): bool,
            vol.Optional(
                CONF_PO_TOKEN,
                default=defaults.get(CONF_PO_TOKEN, ""),
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Optional(
                CONF_VISITOR_DATA,
                default=defaults.get(CONF_VISITOR_DATA, ""),
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
        }
    )


class YTMusicUrlPlayerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for YouTube Music URL Player."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input.get(CONF_NAME, DEFAULT_NAME),
                data=user_input,
            )

        return self.async_show_form(step_id="user", data_schema=_schema())

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return YTMusicUrlPlayerOptionsFlow()


class YTMusicUrlPlayerOptionsFlow(config_entries.OptionsFlow):
    """Options flow using HA-provided self.config_entry."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            # Keep name/title in sync when changed via options
            name = user_input.get(CONF_NAME)
            data = {**self.config_entry.data}
            # Move mutable settings to options; keep identity fields in data.
            options = dict(user_input)
            if name:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    title=name,
                    data={**data, CONF_NAME: name},
                )
            return self.async_create_entry(title="", data=options)

        current = {**self.config_entry.data, **(self.config_entry.options or {})}
        return self.async_show_form(step_id="init", data_schema=_schema(current))
