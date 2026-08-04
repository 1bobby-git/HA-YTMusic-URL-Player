# HA-YTMusic URL Player v1.9.2 Stability Release Design

## Agentic Workers
- Architecture: 파일 단위 변경점 점검, 런타임 동작 영향 최소화
- Test Engineering: unittest 작성, 실패 케이스 기반 회귀 방지
- Verification: CI/manifest/릴리스 파이프라인, 비강제 태깅/릴리스 체크
- Release: 버전 1.9.2 릴리스 기준선 문서화

## 목표
- 구현 범위를 안정성 보강으로 제한하고 코드 체인지의 실패 영역을 고정한다.
- 요청 4개 변경점(요약):
  1) `NamedTemporaryFile(delete=False)` 기반 auth 파일 해제 로직을 생성/실패 양쪽 모두 `finally`에서 제거
  2) `auto_play` 옵션 변경이 기존 `update_listener` 기반 reload/update 패턴으로 runtime 엔티티에 반영되도록 보강
  3) `get_playlist` 하위의 album/watch/pytubefix/yt-dlp fallback 트랙을 `_normalize_track`로 통일
  4) 릴리스 범위 명시(`v1.9.2`) 및 CI/manifest/검증 체인 정렬

## 현재 증거 (실제 소스)
- 인증 파일 생성/해제 소스: `custom_components/ytmusic_url_player/ytmusic_client.py`
  - `async_init()`에서 `tempfile.NamedTemporaryFile(..., delete=False)` 사용
  - 현재 `json.dump(auth_data)` 후 return 시 `YTMusic(temp_path)`로 전달하고 삭제 없음
- `auto_play` 소스: `custom_components/ytmusic_url_player/text.py`
  - `__init__` 시 `cfg`를 캐시해 `_auto_play` 설정
  - 옵션 변경 반영이 현재 `async_set_value` 호출 시점에 즉시 조회되지 않음
- `options` 소스: `custom_components/ytmusic_url_player/__init__.py`
  - `entry.async_on_unload(entry.add_update_listener(_async_update_listener))`
  - `_async_update_listener`는 `hass.config_entries.async_reload(entry.entry_id)` 수행
- Playlist fallback 소스: `custom_components/ytmusic_url_player/ytmusic_client.py`
  - `_normalize_track`는 `get_playlist` 루트에만 적용
  - `PL`, `watch`, `pytubefix`, `yt_dlp` 경로는 정규화 없이 직접 반환
- 버전 소스:
  - `custom_components/ytmusic_url_player/manifest.json` 현재 `1.9.1`
- 테스트 소스:
  - `tests/test_manifest.py`에서 manifest 버전 기대값이 `1.9.1`로 고정
  - `tests/test_playlist_ytdlp_fallback.py`는 `yt_dlp` 옵션/헤더 동작과 fallback 성공 id 추출만 검증
- CI 소스: `.github/workflows/validate.yaml` (unit-tests, HACS, hassfest)

## 설계 상세

### 1) `YTMusicClient` 인증 임시파일 생명주기 정리
- 구현 방침:
  - `NamedTemporaryFile(delete=False)`로 생성한 `temp_path`는 `async_init()` 내부에서 항상 추적
  - `_init()` 내부 `try/finally`에서 생성 여부와 경로를 체크하여 `os.unlink(temp_path)` 실행
  - 성공/실패/예외 경로 모두 동일하게 정리되도록 보장
- 최소 구현 코드(요약):

```python
import os

def _init():
    if not auth_input:
        _LOGGER.info("No auth provided, using anonymous mode")
        return ytmusicapi.YTMusic()

    headers = _parse_devtools_headers(auth_input)
    if headers:
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
    _LOGGER.warning("Could not parse auth headers (cookie not found), using anonymous mode")
    return ytmusicapi.YTMusic()
```

### 2) `auto_play` 옵션 변경의 runtime 반영
- 구현 방침:
  - 기존 `entry.async_update_entry` + `_async_update_listener(async_reload)` 패턴은 유지
  - `YTMusicUrlText`는 옵션 변경 반영 시 캐시된 `_auto_play`만 신뢰하지 않고 현재 설정을 재조회
  - 변경 지점 1개만 유지: `_refresh_auto_play()` 추가 및 `async_set_value` 진입부에서 항상 호출
- 최소 구현 코드(요약):

```python
def _current_auto_play(self) -> bool:
    cfg = {**self.entry.data, **(self.entry.options or {})}
    return bool(cfg.get(CONF_AUTO_PLAY, True))

async def async_set_value(self, value: str) -> None:
    self._auto_play = self._current_auto_play()
    if not self._auto_play:
        return
    ...
```

### 3) playlist fallback 전체 트랙 정규화 통일
- 구현 방침:
  - `tracks`를 `get_playlist` 또는 각 fallback마다 반환 직전에 반드시 `_normalize_track` 통과
  - `_normalize_track`를 각 fallback의 마지막 `tracks` 생성부 공통 출력점으로 구성
  - 현재 `videoId`, `title`, `artists`, `thumbnails`, `duration_seconds` 구조 유지
- 최소 구현 코드(요약):

```python
def _coerce_tracks(raw_tracks):
    normalized = [_normalize_track(t) for t in (raw_tracks or [])]
    return [t for t in normalized if t is not None]

# PL fallback
tracks = _coerce_tracks(tracks)
if tracks:
    return tracks

# get_album
tracks = _coerce_tracks(data.get("tracks"))
if tracks:
    return tracks

# watch / get_watch_playlist
tracks = _coerce_tracks(data.get("tracks"))
if tracks:
    return tracks

# pytubefix
tracks = _coerce_tracks(tracks)
if tracks:
    return tracks

# yt-dlp
tracks = _coerce_tracks(tracks)
if tracks:
    return tracks
```

### 4) 릴리스 바운더리
- 최소 변경 파일 세트:
  - `custom_components/ytmusic_url_player/ytmusic_client.py`
  - `custom_components/ytmusic_url_player/text.py`
  - `tests/test_manifest.py`
  - `custom_components/ytmusic_url_player/manifest.json`
  - 추가 단위테스트 파일 1개(예: `tests/test_auth_tempfile_and_track_normalization.py`)

## 테스트 설계
- unittest 항목:
  1) `test_auth_tempfile_always_deleted_on_success`
  2) `test_auth_tempfile_always_deleted_on_failure`
  3) `test_auto_play_uses_current_option`
  4) `test_playlist_fallbacks_use_normalize_track_for_all_sources`
  5) `test_manifest_version_bumped_to_1.9.2`

## 정확한 실패/성공 커맨드 시나리오(문서화)
- Red: 실패를 재현해야 하는 기존 테스트 입력
  - 실패 입력(예): 인증 데이터 파싱 성공 시 `NamedTemporaryFile` 경로가 삭제되지 않음
  - 기존 `YTMusicClient.async_init()`는 삭제를 보장하지 않기 때문에 파일 잔존 가능성 점검
- Green: 정규화 적용 후 동일 케이스 통과
  - `_coerce_tracks`가 비정상 트랙을 걸러 `videoId` 누락 항목을 제거
  - 옵션 변경 시 `auto_play` 즉시 반영 동작

## 완성 기준
- `v1.9.2` 변경이 기존 동작을 깨지 않으면서도 누수/오동기 반영을 제거
- 텍스트 엔티티와 플레이리스트 fallback가 동일한 트랙 스키마를 사용
- manifest/test/CI 기준치가 동기화됨
