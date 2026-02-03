"""Select entity for target media player override and playback mode."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import (
    DOMAIN,
    CONF_NAME,
    CONF_MEDIA_PLAYER,
    DEFAULT_NAME,
    DATA_TARGET_OVERRIDE,
    DATA_PLAYBACK_MODE,
    PLAYBACK_MODE_SEQUENTIAL,
    PLAYBACK_MODE_OPTIONS,
    PLAYBACK_MODE_LABELS,
)

_LOGGER = logging.getLogger(__name__)

USE_DEFAULT = "기본 대상(설정값 사용)"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up select entity."""
    async_add_entities([
        YTMusicTargetSelect(hass, entry),
        YTMusicPlaybackModeSelect(hass, entry),
    ], update_before_add=False)


class YTMusicTargetSelect(SelectEntity):
    """Select entity for choosing target media player."""

    _attr_has_entity_name = True
    _attr_name = "재생 대상"
    _attr_icon = "mdi:speaker-multiple"
    _attr_should_poll = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the select entity."""
        self.hass = hass
        self.entry = entry
        cfg = {**entry.data, **(entry.options or {})}
        self._org_name = cfg.get(CONF_NAME, DEFAULT_NAME)
        self._default_targets = cfg.get(CONF_MEDIA_PLAYER) or []
        self._attr_unique_id = f"{entry.entry_id}_target"
        self._attr_options = [USE_DEFAULT]
        self._attr_current_option = USE_DEFAULT
        # 기기 이름 → entity_id 매핑
        self._name_to_entity: dict[str, str] = {}
        self._entity_to_name: dict[str, str] = {}

    async def async_added_to_hass(self) -> None:
        """Called when entity is added to hass."""
        await super().async_added_to_hass()
        self._refresh_options()

    async def async_update(self) -> None:
        """Update the entity - refresh media player options."""
        self._refresh_options()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=self._org_name,
            manufacturer="Custom",
            model="YTMusic URL Player",
        )

    def _get_friendly_name(self, entity_id: str) -> str:
        """Get friendly name for an entity, fallback to entity_id."""
        state = self.hass.states.get(entity_id)
        if state and state.attributes:
            return state.attributes.get("friendly_name", entity_id)
        return entity_id

    def _media_player_options(self) -> list[str]:
        """Get media player friendly names and build mappings."""
        self._name_to_entity = {}
        self._entity_to_name = {}
        names = []

        for st in self.hass.states.async_all("media_player"):
            if st and st.entity_id:
                friendly_name = st.attributes.get("friendly_name", st.entity_id)
                # 중복 이름 처리: entity_id 추가
                if friendly_name in self._name_to_entity:
                    friendly_name = f"{friendly_name} ({st.entity_id})"
                self._name_to_entity[friendly_name] = st.entity_id
                self._entity_to_name[st.entity_id] = friendly_name
                names.append(friendly_name)

        names.sort()
        return names

    def _refresh_options(self) -> None:
        """Refresh the list of available options."""
        all_players = self._media_player_options()
        # Put USE_DEFAULT at top
        self._attr_options = [USE_DEFAULT] + all_players

        # 현재 선택이 유효한지 확인
        if self._attr_current_option != USE_DEFAULT:
            if self._attr_current_option not in self._attr_options:
                # entity_id로 저장되어 있던 경우 friendly_name으로 변환
                if self._attr_current_option in self._entity_to_name:
                    self._attr_current_option = self._entity_to_name[self._attr_current_option]
                else:
                    self._attr_current_option = USE_DEFAULT

    async def async_select_option(self, option: str) -> None:
        """Handle option selection."""
        self._refresh_options()
        if option not in self._attr_options:
            raise ValueError("Invalid option")

        self._attr_current_option = option
        store = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        if option == USE_DEFAULT:
            store[DATA_TARGET_OVERRIDE] = None
        else:
            # friendly_name을 entity_id로 변환하여 저장
            entity_id = self._name_to_entity.get(option, option)
            store[DATA_TARGET_OVERRIDE] = entity_id

        self.async_write_ha_state()


class YTMusicPlaybackModeSelect(SelectEntity):
    """Select entity for choosing playback mode."""

    _attr_has_entity_name = True
    _attr_name = "재생 모드"
    _attr_icon = "mdi:repeat"
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the select entity."""
        self.hass = hass
        self.entry = entry
        cfg = {**entry.data, **(entry.options or {})}
        self._org_name = cfg.get(CONF_NAME, DEFAULT_NAME)
        self._attr_unique_id = f"{entry.entry_id}_playback_mode"
        # 옵션은 한글 레이블로 표시
        self._attr_options = [PLAYBACK_MODE_LABELS[mode] for mode in PLAYBACK_MODE_OPTIONS]
        # 기본값: 순차반복
        self._attr_current_option = PLAYBACK_MODE_LABELS[PLAYBACK_MODE_SEQUENTIAL]
        # 레이블 ↔ 모드 매핑
        self._label_to_mode = {v: k for k, v in PLAYBACK_MODE_LABELS.items()}
        self._mode_to_label = PLAYBACK_MODE_LABELS

    async def async_added_to_hass(self) -> None:
        """Called when entity is added to hass."""
        await super().async_added_to_hass()
        # 저장소에서 현재 모드 읽어서 UI 동기화
        store = self.hass.data[DOMAIN][self.entry.entry_id]
        current_mode = store.get(DATA_PLAYBACK_MODE, PLAYBACK_MODE_SEQUENTIAL)
        self._attr_current_option = self._mode_to_label.get(current_mode, self._mode_to_label[PLAYBACK_MODE_SEQUENTIAL])
        _LOGGER.debug("[PlaybackMode] Initialized with mode: %s", current_mode)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=self._org_name,
            manufacturer="Custom",
            model="YTMusic URL Player",
        )

    async def async_select_option(self, option: str) -> None:
        """Handle option selection."""
        if option not in self._attr_options:
            raise ValueError("Invalid option")

        self._attr_current_option = option
        # 레이블을 모드 값으로 변환하여 저장
        mode = self._label_to_mode.get(option, PLAYBACK_MODE_SEQUENTIAL)
        # 직접 접근하여 실제 hass.data에 저장
        store = self.hass.data[DOMAIN][self.entry.entry_id]
        store[DATA_PLAYBACK_MODE] = mode
        _LOGGER.info("[PlaybackMode] Mode changed to: %s (%s)", option, mode)

        self.async_write_ha_state()
