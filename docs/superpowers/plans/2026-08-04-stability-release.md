# HA-YTMusic URL Player v1.9.2 Stability Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Goal
- v1.9.2에서 요구한 안정성 항목 4개를 기존 패턴 내에서 구현 가능한 상태로 정리한다.
- 구현, 회귀 검증, 버전 갱신, GitHub 릴리스까지 완료한다.

## Architecture
- 인증 초기화 및 임시 파일 수명주기: `custom_components/ytmusic_url_player/ytmusic_client.py`
- 자동 재생 토글 반영: `custom_components/ytmusic_url_player/text.py`
- 설정 반영 트리거: `custom_components/ytmusic_url_player/__init__.py`, `config_flow.py`
- playlist fallback 데이터 정규화: `custom_components/ytmusic_url_player/ytmusic_client.py`
- 검증: `tests/test_manifest.py`, `tests/test_playlist_ytdlp_fallback.py`
- CI: `.github/workflows/validate.yaml`

## Tech Stack
- Python 3.11
- Home Assistant integration APIs
- `ytmusicapi`, `pytubefix`, `yt_dlp`
- `unittest`, `unittest.mock`
- GitHub Actions + `gh` CLI

---

## Files
- `C:/Users/bobby/Documents/Codex/2026-08-04/1bobby-git-ha-ytmusic-url-player/work/repos/HA-YTMusic-URL-Player/custom_components/ytmusic_url_player/ytmusic_client.py`
- `C:/Users/bobby/Documents/Codex/2026-08-04/1bobby-git-ha-ytmusic-url-player/work/repos/HA-YTMusic-URL-Player/custom_components/ytmusic_url_player/text.py`
- `C:/Users/bobby/Documents/Codex/2026-08-04/1bobby-git-ha-ytmusic-url-player/work/repos/HA-YTMusic-URL-Player/custom_components/ytmusic_url_player/manifest.json`
- `C:/Users/bobby/Documents/Codex/2026-08-04/1bobby-git-ha-ytmusic-url-player/work/repos/HA-YTMusic-URL-Player/tests/test_manifest.py`
- `C:/Users/bobby/Documents/Codex/2026-08-04/1bobby-git-ha-ytmusic-url-player/work/repos/HA-YTMusic-URL-Player/tests/test_auth_tempfile_and_playlist_normalization.py`
- `C:/Users/bobby/Documents/Codex/2026-08-04/1bobby-git-ha-ytmusic-url-player/work/repos/HA-YTMusic-URL-Player/.github/workflows/validate.yaml`

## 최소 구현 코드

### Auth 임시 파일 정리

```python
import os

def _init():
    if not auth_input:
        return ytmusicapi.YTMusic()

    headers = _parse_devtools_headers(auth_input)
    if not headers:
        _LOGGER.warning("Could not parse auth headers (cookie not found), using anonymous mode")
        return ytmusicapi.YTMusic()

    auth_data = _build_auth_json(headers)
    temp_path = None
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(auth_data, f)
        temp_path = f.name

    try:
        return ytmusicapi.YTMusic(temp_path)
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
```

### auto_play runtime 반영

```python
def _resolve_auto_play(self) -> bool:
    cfg = {**self.entry.data, **(self.entry.options or {})}
    return bool(cfg.get(CONF_AUTO_PLAY, True))

async def async_set_value(self, value: str) -> None:
    self._auto_play = self._resolve_auto_play()
    self._attr_native_value = value or ""
    self.async_write_ha_state()
    if not self._auto_play:
        return
    ...
```

### playlist fallback 정규화 공통화

```python
def _coerce_tracks(raw_tracks):
    normalized = [_normalize_track(track) for track in (raw_tracks or [])]
    return [track for track in normalized if track is not None]

tracks = _coerce_tracks(data.get("tracks", []))
if tracks:
    return tracks
```

## 실제 unittest 코드

```python
from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "ytmusic_url_player"
    / "ytmusic_client.py"
)
MODULE_NAME = "custom_components.ytmusic_url_player.ytmusic_client_test"


class FakeYTMusic:
    def __init__(self, fail_init: bool = False):
        self.fail_init = fail_init
        self.init_path = None

    def __call__(self, path=None):
        self.init_path = path
        if self.fail_init:
            raise RuntimeError("init failed")
        return self

    def get_album(self, list_id):
        return {"tracks": [{"setVideoId": "ALBUM01", "title": 1, "artists": [{"name": "X"}], "thumbnails": []}]}

    def get_playlist(self, list_id, limit=None):
        if list_id.startswith("RD") or list_id.startswith("PL"):
            raise RuntimeError("playlist path skipped")
        return {"tracks": [{"videoId": "PL01", "title": 2, "artists": []}]}

    def get_watch_playlist(self, videoId: str | None = None, playlistId: str | None = None, limit: int | None = None):
        return {"tracks": [{"id": "WATCH01", "title": 3, "artists": []}]}


class YTMusicPlaylistStabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.saved_modules = {name: sys.modules.get(name) for name in (
            "homeassistant",
            "homeassistant.core",
            "ytmusicapi",
            "pytubefix",
            "yt_dlp",
            "custom_components",
            "custom_components.ytmusic_url_player",
            "custom_components.ytmusic_url_player.const",
        )}

        homeassistant = types.ModuleType("homeassistant")
        homeassistant_core = types.ModuleType("homeassistant.core")
        homeassistant_core.HomeAssistant = object
        homeassistant.core = homeassistant_core

        ytmusicapi = types.ModuleType("ytmusicapi")
        pytubefix = types.ModuleType("pytubefix")
        yt_dlp = types.ModuleType("yt_dlp")

        class FakePlaylist:
            def __init__(self, _url: str):
                self.video_urls = ["https://www.youtube.com/watch?v=PBT1"]
        pytubefix.Playlist = FakePlaylist

        class FakeYoutubeDL:
            def __init__(self, options):
                self.options = options
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return None
            def extract_info(self, _url, download=False):
                return {
                    "entries": [
                        {"id": "YTD01", "title": 4, "uploader": "U", "thumbnail": "https://x"},
                    ]
                }
        yt_dlp.YoutubeDL = FakeYoutubeDL

        custom_components = types.ModuleType("custom_components")
        custom_components.__path__ = []
        integration_package = types.ModuleType("custom_components.ytmusic_url_player")
        integration_package.__path__ = []
        const = types.ModuleType("custom_components.ytmusic_url_player.const")
        const.CONF_AUTH_FILE = "auth_file"

        for name, mod in {
            "homeassistant": homeassistant,
            "homeassistant.core": homeassistant_core,
            "ytmusicapi": ytmusicapi,
            "pytubefix": pytubefix,
            "yt_dlp": yt_dlp,
            "custom_components": custom_components,
            "custom_components.ytmusic_url_player": integration_package,
            "custom_components.ytmusic_url_player.const": const,
        }.items():
            sys.modules[name] = mod

        spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[MODULE_NAME] = module
        assert spec.loader is not None
        spec.loader.exec_module(module)
        self.client_module = module
        self.client_cls = module.YTMusicClient

    def tearDown(self) -> None:
        for name, old in self.saved_modules.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old
        sys.modules.pop(MODULE_NAME, None)

    async def test_tempfile_is_deleted_on_init_success(self) -> None:
        fake = FakeYTMusic()
        sys.modules["ytmusicapi"].YTMusic = Mock(side_effect=fake.__call__)
        client = self.client_cls(object(), {"auth_file": "cookie\nabc=1\nx-goog-authuser\n0\n"})
        await client.async_init()
        self.assertEqual(fake.init_path is not None, True)
        self.assertFalse(os.path.exists(fake.init_path))

    async def test_tempfile_is_deleted_on_init_failure(self) -> None:
        fake = FakeYTMusic(fail_init=True)
        sys.modules["ytmusicapi"].YTMusic = Mock(side_effect=fake.__call__)
        client = self.client_cls(object(), {"auth_file": "cookie\nabc=1\nx-goog-authuser\n0\n"})
        with self.assertRaises(RuntimeError):
            await client.async_init()
        self.assertEqual(fake.init_path is not None, True)
        self.assertFalse(os.path.exists(fake.init_path))

    async def test_playlist_fallback_tracks_normalized(self) -> None:
        fake = FakeYTMusic()
        sys.modules["ytmusicapi"].YTMusic = Mock(return_value=fake)
        client = self.client_cls(object(), {})
        await client.async_init()

        tracks = await client.async_get_playlist_video_ids("MPRE000")
        self.assertEqual([t["videoId"] for t in tracks], ["ALBUM01"])

        tracks_watch = await client.async_get_playlist_video_ids("RDTEST", seed_video_id="seed")
        self.assertEqual([t["videoId"] for t in tracks_watch], ["WATCH01"])

        tracks_pytube = await client.async_get_playlist_video_ids("PLABC")
        self.assertEqual([t["videoId"] for t in tracks_pytube], ["PBT1"])

        tracks_ydl = await client.async_get_playlist_video_ids("RDPL")
        self.assertEqual([t["videoId"] for t in tracks_ydl], ["YTD01"])

class ManifestVersionTests(unittest.TestCase):
    def test_manifest_version_is_1_9_2(self) -> None:
        manifest_path = Path(__file__).parents[1] / "custom_components" / "ytmusic_url_player" / "manifest.json"
        manifest = manifest_path.read_text(encoding="utf-8")
        self.assertIn("\"version\": \"1.9.2\"", manifest)
```

## Red/Green commands and exact results

Red command:
- `python -m unittest tests.test_manifest`
- 기대 결과: `AssertionError: '1.9.1' != '1.9.2'`

Green command:
- `python -m unittest discover -s tests -v`
- 기대 결과: `Ran 5 tests in 0.0xxs` 그리고 `OK`

## CI
- `python -m unittest discover -s tests -v`
- `.github/workflows/validate.yaml`의 `unit-tests`, `validate-hacs`, `validate-hassfest`

## non-force tag/release/gh verification
- `git tag v1.9.2`
- `git tag --list | Select-String "v1.9.2"`
- `gh release list --limit 10`
- `gh release view v1.9.2 --json name,tagName,tagCommitish,isDraft,isPrerelease`
- `gh release create v1.9.2` 는 문서 단계에서 실행하지 않고 계획 항목으로 유지

## 2~5분 체크리스트
- 2분: 설계 문서/실행 문서 일치 점검
- 3분: 4개 요구사항 항목에 구현 코드 블록 추가 완료
- 4분: Red/Green/CI/gh 검증 항목 정합성 재검토
- 5분: Placeholder 스캔 결과와 경로 오탈자 점검 완료

## Selective Lore commits
Intent: scope-stable v1.9.2 stability release prep with auth temp cleanup and fallback normalization

Constraint: release scope only, no new dependencies
Rejected: API surface refactor for stream extraction
Confidence: medium
Scope-risk: narrow
Directive: keep runtime entity behavior unchanged except auto_play resolution timing
Tested: Red/Green command targets prepared in execution plan
Not-tested: actual runtime HA integration smoke on real devices
***
