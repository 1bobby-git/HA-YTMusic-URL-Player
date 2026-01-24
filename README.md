# YouTube Music URL Player

YouTube / YouTube Music URL을 Home Assistant 미디어 플레이어에서 재생하는 커스텀 통합입니다.

> 단일 트랙뿐 아니라 **플레이리스트/앨범 연속 재생**을 지원하며, Cast 기기에서는 **네이티브 YouTube 앱**을 통한 재생도 가능합니다.

---

## Features

- **단일 트랙 재생**
  - YouTube/YouTube Music URL을 입력하면 오디오 스트림 추출 후 재생
  - `pytubefix` (기본) / `yt-dlp` (폴백) 이중 추출 지원
- **플레이리스트/앨범 연속 재생**
  - 재생 목록의 모든 트랙을 순서대로 자동 재생
  - 트랙 종료 시 자동으로 다음 트랙 재생 (QueueManager)
- **Cast 기기 네이티브 YouTube 재생**
  - Google Cast 기기에서 YouTube 앱을 통한 네이티브 재생
  - 봇 감지 우회 및 고품질 재생 지원
- **다중 재생 대상 지원**
  - Cast, DLNA, HTTP 스트림 등 다양한 미디어 플레이어 지원
  - 여러 기기에 동시 재생 가능
- **HA 프록시 스트리밍**
  - YouTube 스트림을 HA를 통해 프록시하여 호환성 향상
  - Range 요청 지원으로 탐색(Seek) 가능
- **인증 지원**
  - Chrome DevTools Request Headers를 통한 YouTube Music 인증
  - 비공개 플레이리스트/라이브러리 접근 가능

---

## Install (HACS)

[![Open your Home Assistant instance and show the HACS repository.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=1bobby-git&repository=HA-YTMusic-URL-Player&category=integration)

1. HACS → Integrations → 우측 상단 ⋮ → Custom repositories
2. Repository: `https://github.com/1bobby-git/HA-YTMusic-URL-Player`
3. Category: Integration
4. 설치 후 Home Assistant 재시작

---

## Setup

[![Open your Home Assistant instance and start setting up the integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=ytmusic_url_player)

1. 설정 → 기기 및 서비스 → 통합 추가 → **YouTube Music URL Player**
2. 기본 미디어 플레이어 선택
3. (선택) 인증 정보 입력 (Chrome DevTools Request Headers)
4. 완료

---

## Options

| 옵션 | 설명 |
|------|------|
| `name` | 통합 인스턴스 이름 |
| `media_player` | 기본 재생 대상 미디어 플레이어 |
| `auth_file` | Chrome DevTools Request Headers (인증용) |
| `auto_play` | 텍스트 엔티티 값 변경 시 자동 재생 |

---

## Entities

통합을 추가하면 아래 엔티티들이 생성됩니다.

| 엔티티 | 설명 |
|--------|------|
| `text.ytmusic_url_player_*` | URL 입력 엔티티 (값 변경 시 자동 재생) |
| `select.ytmusic_url_player_*_target` | 재생 대상 오버라이드 선택 |

---

## Service

### `ytmusic_url_player.play_url`

URL을 재생합니다.

```yaml
service: ytmusic_url_player.play_url
data:
  url: "https://music.youtube.com/watch?v=VIDEO_ID"
  media_player: media_player.living_room_speaker  # 선택사항
```

| 파라미터 | 필수 | 설명 |
|----------|------|------|
| `url` | O | YouTube/YouTube Music URL |
| `media_player` | X | 재생 대상 (미지정 시 기본값 사용) |

---

## Supported URL Formats

- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://music.youtube.com/watch?v=VIDEO_ID`
- `https://www.youtube.com/playlist?list=PLAYLIST_ID`
- `https://music.youtube.com/playlist?list=PLAYLIST_ID`
- `https://music.youtube.com/browse/MPRE...` (앨범)
- Mix 플레이리스트 (`RD*`)

---

## Playback Flow

### 단일 트랙
1. URL 입력 → 파싱
2. 스트림 추출 (pytubefix → yt-dlp 폴백)
3. Cast 기기: 네이티브 YouTube → 직접 스트림 → HA 프록시 순서로 시도
4. 기타 기기: HA 프록시 URL로 재생

### 플레이리스트
1. URL 입력 → 플레이리스트 트랙 목록 조회
2. QueueManager가 첫 번째 트랙 재생
3. 트랙 종료 감지 (playing → idle) 시 다음 트랙 자동 재생
4. 마지막 트랙까지 순차 재생

---

## Debug (Logs)

`configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.ytmusic_url_player: debug
```

---

## Dependencies

- `ytmusicapi==1.9.1` - YouTube Music API
- `pytubefix>=10.3.0` - 스트림 추출 (기본)
- `yt-dlp>=2024.1.0` - 스트림 추출 (폴백)
- `pychromecast>=14.0.0` - Cast 기기 통신

---

## License

MIT License
