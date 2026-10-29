"""Cast device lookup by name (1.10.0, Y7)."""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "ytmusic_url_player"
PACKAGE = "cast_manager_test_package"


class CastManagerMatchTest(unittest.TestCase):
    def setUp(self) -> None:
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(ROOT)]
        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = object
        self.modules = patch.dict(sys.modules, {
            PACKAGE: package,
            "homeassistant.core": core,
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


if __name__ == "__main__":
    unittest.main()
