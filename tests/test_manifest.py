from __future__ import annotations

import json
import unittest
from pathlib import Path


MANIFEST_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "ytmusic_url_player"
    / "manifest.json"
)


class ManifestTest(unittest.TestCase):
    def test_release_refreshes_playlist_extractor_dependencies(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

        self.assertEqual("1.9.3", manifest["version"])
        self.assertEqual(["http"], manifest["dependencies"])
        self.assertIn("pytubefix>=10.3.0", manifest["requirements"])
        self.assertIn("yt-dlp>=2026.7.4", manifest["requirements"])

    def test_config_descriptions_do_not_embed_urls(self) -> None:
        integration_dir = MANIFEST_PATH.parent
        translation_paths = [
            integration_dir / "strings.json",
            *sorted((integration_dir / "translations").glob("*.json")),
        ]

        for path in translation_paths:
            with self.subTest(path=path.name):
                document = json.loads(path.read_text(encoding="utf-8"))
                description = document["config"]["step"]["user"]["description"]
                self.assertNotRegex(description, r"https?://")


if __name__ == "__main__":
    unittest.main()
