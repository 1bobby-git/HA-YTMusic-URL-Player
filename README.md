<!-- project-branding:start -->
<p align="center">
  <img src="media/readme-logo.svg" alt="YouTube Music URL Player 가로형 로고" width="480">
</p>
<p align="center">
  <a href="https://github.com/1bobby-git/HA-YTMusic-URL-Player/stargazers"><img src="https://img.shields.io/github/stars/1bobby-git/HA-YTMusic-URL-Player?style=flat-square&logo=github&label=Stars" alt="GitHub Stars"></a>
  <a href="https://github.com/1bobby-git/HA-YTMusic-URL-Player/releases"><img src="https://img.shields.io/github/v/release/1bobby-git/HA-YTMusic-URL-Player?style=flat-square&label=Release" alt="Latest Release"></a>
  <a href="https://github.com/1bobby-git/HA-YTMusic-URL-Player/blob/main/custom_components/ytmusic_url_player/manifest.json"><img src="https://img.shields.io/badge/Architecture-independent-0ea5e9?style=flat-square" alt="Architecture independent"></a>
  <a href="https://github.com/1bobby-git/HA-YTMusic-URL-Player/blob/main/LICENSE"><img src="https://img.shields.io/github/license/1bobby-git/HA-YTMusic-URL-Player?style=flat-square&label=License" alt="License"></a>
  <a href="https://github.com/1bobby-git/HA-YTMusic-URL-Player/commits/main"><img src="https://img.shields.io/github/last-commit/1bobby-git/HA-YTMusic-URL-Player?style=flat-square&label=Updated" alt="Last Commit"></a>
</p>
<!-- project-branding:end -->

# YouTube Music URL Player


> **Compatibility**: Home Assistant **2025.7+** 필요. 의존성 `pytubefix`(10.3.3 이상)가 aiohttp 3.12.13 이상을 요구하며, 이 버전은 Home Assistant 2025.7부터 들어 있습니다.
YouTube / YouTube Music URL을 Home Assistant 미디어 플레이어에서 재생하는 커스텀 통합입니다.

> 단일 트랙뿐 아니라 **플레이리스트/앨범 연속 재생**을 지원하며, Cast 기기에서는 **네이티브 YouTube 앱**을 통한 재생도 가능합니다.

---

## Features

- **단일 트랙 재생**
  - YouTube/YouTube Music URL을 입력하면 오디오 스트림 추출 후 재생
  - `yt-dlp` (기본) / `pytubefix` (폴백) 이중 추출 지원
- **플레이리스트/앨범 연속 재생**
  - 재생 목록의 트랙을 차례로 자동 재생 (QueueManager)
  - 재생 모드 선택: 순차반복(기본, 끝나면 처음부터), 1회재생(마지막 곡에서 종료), 랜덤재생(섞어서 반복)
  - 재생이 시작되지 않는 곡은 건너뜀
- **Cast 기기 네이티브 YouTube 재생**
  - 화면이 있는 Google Cast 기기는 YouTube 앱으로 재생 (YouTube Music URL은 YouTube Music 앱 먼저)
  - 화면 없는 Cast 스피커와 그 밖의 기기는 HA 프록시 스트림으로 재생
- **다중 재생 대상 지원**
  - Cast, DLNA, HTTP 스트림 등 다양한 미디어 플레이어 지원
  - 여러 기기에 동시 재생 가능
- **HA 프록시 스트리밍**
  - YouTube 스트림을 HA를 통해 프록시하여 호환성 향상
  - Range 요청 지원으로 탐색(Seek) 가능
  - 인증 없는 스트림 요청은 이 통합이 재생한 곡만 받습니다 ([스트림 접근](#스트림-접근))
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
| `po_token`, `visitor_data` | 둘 다 입력하면 pytubefix 폴백 추출에서 봇 감지 우회에 사용 (기본 추출기 yt-dlp는 사용하지 않음) |
| `allow_unauthenticated_streams` | 인증 없는 스트림·M3U 요청을 모두 허용하는 이전 방식 (기본 꺼짐, 권장하지 않음) |

---

## Entities

통합을 추가하면 아래 엔티티들이 생성됩니다.

| 엔티티 | 설명 |
|--------|------|
| `text.*` URL | URL 입력 엔티티 (값 변경 시 자동 재생) |
| `select.*` 재생 대상 | 재생 대상 오버라이드 선택 |
| `select.*` 재생 모드 | 순차반복 / 1회재생 / 랜덤재생 |

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
| `media_player` | X | 재생 대상 (미지정 시 재생 대상 선택값, 없으면 기본값 사용) |

### `ytmusic_url_player.stop`

재생 목록 연속 재생을 끝내고 대상마다 `media_player.media_stop`으로 재생을 멈춥니다(정지를 지원하지 않고 일시정지만 되는 기기는 `media_pause`).

```yaml
service: ytmusic_url_player.stop
data:
  media_player: media_player.living_room_speaker  # 선택사항
```

| 파라미터 | 필수 | 설명 |
|----------|------|------|
| `media_player` | X | 대상 (미지정 시 `play_url`과 같은 규칙) |

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
2. 같은 기기에서 재생 중인 재생 목록이 있으면 끝냄
3. 화면이 있는 Cast 기기: YouTube 앱으로 재생, 실패하면 4로
4. 그 밖의 기기: HA 프록시 URL로 재생 (스트림은 yt-dlp → pytubefix 순으로 추출)

### 플레이리스트
1. URL 입력 → 플레이리스트 트랙 목록 조회
2. QueueManager가 첫 번째 트랙 재생
3. 트랙 종료 감지 (playing → idle) 시 다음 트랙 자동 재생. 재생 명령 직후 10초 안의 idle은 이전 콘텐츠가 멈춘 것으로 보고 무시합니다.
4. 재생 명령 후 90초가 지나도 기기가 재생 중(playing·paused·buffering·on)이 아니면 그 곡을 건너뜁니다. 그때 기기가 꺼짐·사용 불가·알 수 없음 상태이면 재생 목록을 끝냅니다.
5. 재생 명령 실패나 시작 안 됨이 3곡 연속이면 재생 목록을 끝냅니다(곡이 끝까지 재생되거나 90초 시점에 재생 중이면 다시 0부터 셉니다). 길이가 10초 미만으로 알려진 곡은 유예 시간 안에 끝나도 다음 곡으로 넘어가고, 실패로 세지 않습니다.
6. 마지막 곡 다음: 순차반복·랜덤재생은 처음부터 다시, 1회재생은 종료

### 재생 목록이 끝나는 경우
- `ytmusic_url_player.stop` 호출
- 같은 기기로 다른 URL(단일 곡 또는 다른 재생 목록) 재생
- Home Assistant에서 그 기기로 `media_player.media_stop`·`turn_off`를 호출하거나, 다른 콘텐츠를 `media_player.play_media`로 재생 (`entity_id`·기기·영역·층·라벨 대상, `all` 포함. 숨긴 엔티티는 Home Assistant처럼 기기·영역·층·라벨 대상에서 제외)
- 기기가 꺼짐(`off`)
- 위 4·5의 경우

TTS 안내(`tts.speak` 등 `announce` 재생)와 `enqueue: add`/`next`로 추가하는 `play_media`는 재생 목록을 끝내지 않습니다.

> 기기 자체(음성 명령·기기 앱)에서 정지하면 곡이 정상적으로 끝난 것과 구분할 수 없어 다음 곡이 재생될 수 있습니다. 이때는 Home Assistant에서 정지하거나 `ytmusic_url_player.stop`을 사용하세요.

---

## 스트림 접근

미디어 플레이어는 Home Assistant 로그인 정보 없이 `/api/ytmusic_url_player/stream/<videoId>`를 가져갑니다. 이 주소가 인터넷에 노출돼도 아무 영상이나 프록시하지 않도록 다음처럼 제한합니다.

- 인증 없는 스트림 요청: 이 통합이 재생 명령을 보낸 곡과 M3U에 넣은 곡만 24시간 동안 허용 (최대 10000개, Home Assistant 재시작이나 옵션 저장 때 초기화)
- Home Assistant 인증 요청(토큰·서명 URL): 항상 허용. Cast·Sonos·DLNA 등 Home Assistant 기본 미디어 플레이어 통합은 이 주소에 서명을 붙여 기기로 보내므로 그대로 동작합니다.
- `/api/ytmusic_url_player/m3u/<listId>.m3u`: 사용자 YouTube 쿠키로 비공개 목록(예: `LM`)까지 읽으므로 Home Assistant 인증 필요. Home Assistant는 쿼리가 붙은 주소에 서명하지 않으므로, 믹스용 `?v=` 주소는 외부 플레이어에서 쓰려면 아래 옵션이 필요합니다.

Home Assistant 밖(VLC, 스크립트, 저장해 둔 주소)에서 스트림·M3U 주소를 직접 쓰던 경우 1.10.0부터 403/401이 납니다. 이전처럼 인증 없이 모두 허용하려면 옵션 `allow_unauthenticated_streams`를 켭니다(권장하지 않음).

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

- `ytmusicapi>=1.9.1` - YouTube Music API
- `yt-dlp>=2026.7.4` - 스트림 추출 (기본)
- `pytubefix>=10.3.0` - 스트림 추출 (폴백)
- `pychromecast>=14.0.0` - Cast 기기 통신

---

## License

MIT License

## 통합 업데이트 1.9.4

- 동일 영상의 동시 캐시 미스에서 성공한 추출 결과 재사용; 영상별 잠금은 유휴 시 자동 제거
- 메타데이터 캐시를 128개로 제한하고 시스템 시각 변경의 TTL 영향 제거
- 긴 재생을 중단시키는 전체 30초 제한 대신 연결/수신 정체 30초 제한
- 이미 전송을 시작한 스트림에서 오류가 나면 새 응답·추출을 반복하지 않음
- 추출기 선택·재생목록·서비스·엔티티·인증 정책 및 라이브러리 버전은 변경하지 않음

변경 내용, 검증 범위 및 롤백 방법: [최적화 문서](docs/OPTIMIZATION_2026-09-06.md). 펌웨어·브리지 앱은 변경하지 않으며, 운영 HA 설치·실기기 검증은 별도입니다.

## 통합 업데이트 1.9.5

- 재생 불가 또는 ID가 없는 곡을 건너뛸 때 재생 큐가 잠금 대기로 멈추는 문제를 수정했습니다.
- 연속 재생 실패 시 시도 횟수를 큐 길이로 제한하고 대기열을 정리합니다.

실제 Home Assistant 설치 및 기기 검증은 별도입니다.

## 통합 업데이트 1.9.6

- 인증이 없는 스트림/M3U 엔드포인트에서 videoId·listId·시드 값을 허용 문자 집합으로 검증해 잘못된 요청을 네트워크 호출 전에 400으로 거부합니다.
- 연속 재생의 다음 곡 재생·메타데이터 선반입 작업에 강한 참조를 유지해 이벤트 루프가 작업을 중간에 회수하지 못하도록 하고, 언로드 시 미완료 작업을 취소합니다.

실제 Home Assistant 설치 및 기기 검증은 별도입니다.

## 통합 업데이트 1.10.0

- 재생 목록을 끝낼 수 있습니다: `ytmusic_url_player.stop` 서비스를 추가했고, 같은 기기로 다른 URL을 재생하거나 Home Assistant에서 정지·끄기·다른 콘텐츠 재생을 하면 큐가 끝납니다. 기기가 꺼져도 끝납니다. TTS 안내는 재생 목록을 끝내지 않습니다.
- 새 재생 목록을 시작할 때 이전 콘텐츠가 멈추며 첫 곡을 건너뛰던 문제를 고쳤습니다.
- 재생 명령이 실패한 곡과 90초 안에 재생이 시작되지 않은 곡은 건너뛰고(전에는 큐가 멈춰 있었음), 3곡 연속 실패하거나 기기가 꺼짐·사용 불가이면 재생 목록을 끝냅니다.
- **호환성 주의**: 인증 없는 스트림 요청은 이 통합이 재생한 곡만 받고, M3U는 Home Assistant 인증이 필요합니다. Home Assistant 밖에서 이 주소를 직접 쓰던 경우 `allow_unauthenticated_streams` 옵션으로 이전 방식을 켤 수 있습니다.
- yt-dlp가 YouTube TLS 인증서를 검증합니다. `po_token`·`visitor_data`를 pytubefix 폴백 추출에 사용합니다.
- Cast 기기 이름이 겹칠 때(예: `거실`과 `거실 TV`) Cast UUID로 먼저 찾고, 다음으로 정확히 같은 이름을 고릅니다.
- README·설정 화면 문구를 실제 동작에 맞췄고, 한국어 옵션 화면 번역을 추가했습니다.
- 최소 Home Assistant 버전 표기를 2025.7.0으로 정정했습니다. 의존성이 그 이전 버전에는 설치되지 않습니다(1.9.x도 같음).
- 도메인·엔티티·기존 설정 키·`play_url` 인자·스트림 URL 형식·재생 모드는 바꾸지 않았습니다.

실제 Home Assistant 설치 및 기기 검증은 별도입니다.
