# Security Policy

## Supported Versions

보안 수정은 최신 릴리스에만 제공합니다. HACS에서 최신 버전으로 업데이트한 뒤 문제가 계속되는지 확인해 주세요.

| Version | Supported |
| ------- | --------- |
| 최신 릴리스 (1.10.x) | 지원 |
| 그 이전 | 지원하지 않음 |

## Reporting a Vulnerability

공개 이슈에 취약점 세부 내용을 올리지 말고, GitHub 저장소의 **Security → Report a vulnerability**(비공개 보고)로 알려 주세요. 재현 방법, 영향받는 버전, Home Assistant 버전을 함께 적어 주시면 확인이 빠릅니다.

보고에 YouTube 쿠키·`auth_file` 내용·`po_token`·Home Assistant 토큰 같은 비밀 값은 넣지 마세요.

## 노출 범위

이 통합은 미디어 플레이어가 쓰는 스트림 엔드포인트(`/api/ytmusic_url_player/stream/<videoId>`)를 인증 없이 열어 둡니다. 1.10.0부터 인증 없는 요청은 이 통합이 재생한 곡만 받고, M3U 엔드포인트는 Home Assistant 인증이 필요합니다. 옵션 `allow_unauthenticated_streams`를 켜면 이 제한이 풀립니다.
