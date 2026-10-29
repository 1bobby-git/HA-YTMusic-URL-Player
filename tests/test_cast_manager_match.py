"""Cast device lookup by name and Cast UUID (1.10.0, Y7)."""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
import uuid as uuidlib
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "ytmusic_url_player"
PACKAGE = "cast_manager_test_package"
TV_UUID = "a1b2c3d4-0000-1111-2222-333344445555"
SPEAKER_UUID = "99999999-0000-1111-2222-333344445555"


class _FakeCast:
    def __init__(self, name: str, uuid: str, cast_type: str) -> None:
        self.name = name
        self.cast_type = cast_type
        self.cast_info = types.SimpleNamespace(
            host="192.0.2.10", port=8009, uuid=uuidlib.UUID(uuid),
            friendly_name=name, cast_type=cast_type,
        )


TV = _FakeCast("Living Room TV", TV_UUID, "cast")
SPEAKER = _FakeCast("Kitchen speaker", SPEAKER_UUID, "audio")


class CastManagerMatchTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(ROOT)]
        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = object
        self.scan_order: list[_FakeCast] = []
        pychromecast = types.ModuleType("pychromecast")
        discovery = types.ModuleType("pychromecast.discovery")
        discovery.stop_discovery = lambda _browser: None
        pychromecast.discovery = discovery
        pychromecast.get_chromecasts = lambda timeout=10: (list(self.scan_order), object())
        self.modules = patch.dict(sys.modules, {
            PACKAGE: package,
            "homeassistant.core": core,
            "pychromecast": pychromecast,
            "pychromecast.discovery": discovery,
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)
        name = f"{PACKAGE}.cast_manager"
        spec = importlib.util.spec_from_file_location(name, ROOT / "cast_manager.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        self.module = module
        self.manager = module.CastManager(hass=object())

    def add(self, name: str):
        device = self.module.CastDevice(
            name=name, host="192.0.2.1", port=8009, uuid=name, cast=object(), last_used=0.0
        )
        self.manager._devices[name] = device
        return device

    def test_exact_name_wins_over_longer_names(self) -> None:
        room = self.add("거실")
        tv = self.add("거실 TV")

        self.assertIs(room, self.manager._match_device("거실"))
        self.assertIs(tv, self.manager._match_device("거실 TV"))

    def test_exact_match_ignores_case(self) -> None:
        device = self.add("Living Room")

        self.assertIs(device, self.manager._match_device("living room"))

    def test_unique_partial_match_is_still_used(self) -> None:
        self.add("거실")
        tv = self.add("거실 TV")

        self.assertIs(tv, self.manager._match_device("TV"))

    def test_ambiguous_partial_match_returns_nothing(self) -> None:
        self.add("거실 스피커")
        self.add("거실 TV")

        self.assertIsNone(self.manager._match_device("거실"))

    def test_device_without_name_never_matches(self) -> None:
        self.add("")

        self.assertIsNone(self.manager._match_device("주방"))

    def test_cast_uuid_wins_over_names(self) -> None:
        self.add("거실 스피커")
        tv = self.add("거실 TV")
        tv.uuid = "A1B2C3D4-0000-1111-2222-333344445555"

        self.assertIs(
            tv, self.manager._match_device("거실", "a1b2c3d4-0000-1111-2222-333344445555")
        )
        self.assertIsNone(self.manager._match_device("거실", "ffffffff-0000-0000-0000-000000000000"))

    async def test_lookup_right_after_a_scan_finds_the_requested_device(self) -> None:
        cases = [
            ("TV by UUID, speaker scanned last", [TV, SPEAKER], "Living Room TV", TV_UUID, "cast"),
            ("speaker by UUID, TV scanned last", [SPEAKER, TV], "Kitchen speaker", SPEAKER_UUID, "audio"),
            ("renamed TV by UUID", [TV, SPEAKER], "TV", TV_UUID, "cast"),
            ("no UUID, exact name", [SPEAKER, TV], "Kitchen speaker", None, "audio"),
        ]
        for label, order, name, cast_uuid, expected in cases:
            with self.subTest(label):
                self.scan_order[:] = order
                manager = self.module.CastManager(hass=object())  # fresh, as after start-up

                self.assertEqual(expected, await manager.async_get_cast_type(name, uuid=cast_uuid))
                self.assertEqual(expected, await manager.async_get_cast_type(name, uuid=cast_uuid))


if __name__ == "__main__":
    unittest.main()
