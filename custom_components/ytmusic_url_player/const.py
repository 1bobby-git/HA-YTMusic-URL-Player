from typing import Final

DOMAIN: Final = "ytmusic_url_player"

# ----------------------------
# Configuration Keys
# ----------------------------
CONF_NAME: Final = "name"
CONF_MEDIA_PLAYER: Final = "media_player"
CONF_AUTH_FILE: Final = "auth_file"
CONF_AUTO_PLAY: Final = "auto_play"
CONF_PO_TOKEN: Final = "po_token"
CONF_VISITOR_DATA: Final = "visitor_data"

# ----------------------------
# Default Values
# ----------------------------
DEFAULT_NAME: Final = "YouTube Music URL Player"
DEFAULT_AUTO_PLAY: Final = True

# ----------------------------
# Internal Data Keys
# ----------------------------
DATA_YTMUSIC: Final = "ytmusic"
DATA_EXTRACTOR: Final = "extractor"
DATA_TARGET_OVERRIDE: Final = "target_override"
DATA_QUEUE_MANAGER: Final = "queue_manager"
DATA_CAST_MANAGER: Final = "cast_manager"

# ----------------------------
# Timing Constants (seconds)
# ----------------------------
STREAM_CACHE_TTL_SECONDS: Final = 600  # 10 minutes
CAST_CACHE_TTL_SECONDS: Final = 300    # 5 minutes
CAST_SCAN_INTERVAL_SECONDS: Final = 60

# ----------------------------
# Playback Strategies (internal use, auto-selected)
# ----------------------------
STRATEGY_CAST_NATIVE: Final = "cast_native"       # Cast 기기: YouTube 앱으로 재생
STRATEGY_DIRECT_STREAM: Final = "direct_stream"   # YouTube 스트림 URL 직접 전달
STRATEGY_PROXY_INTERNAL: Final = "proxy_internal" # HA 내부 프록시 (내부 네트워크)
STRATEGY_PROXY_EXTERNAL: Final = "proxy_external" # HA 외부 프록시 (외부 접근)

# ----------------------------
# Device Capabilities
# ----------------------------
CAPABILITY_CAST: Final = "cast"           # Google Cast 프로토콜 지원
CAPABILITY_HTTP_STREAM: Final = "http"    # HTTP 스트림 재생 지원
CAPABILITY_DLNA: Final = "dlna"           # DLNA/UPnP 지원
CAPABILITY_AIRPLAY: Final = "airplay"     # AirPlay 지원


# ----------------------------
# API Endpoints
# ----------------------------
API_STREAM_PATH: Final = "stream"
API_M3U_PATH: Final = "m3u"
