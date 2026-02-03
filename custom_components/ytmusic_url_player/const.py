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
DATA_PLAYBACK_MODE: Final = "playback_mode"

# ----------------------------
# Playback Mode Constants
# ----------------------------
PLAYBACK_MODE_SEQUENTIAL: Final = "sequential"  # 순차반복
PLAYBACK_MODE_ONCE: Final = "once"              # 1회재생
PLAYBACK_MODE_SHUFFLE: Final = "shuffle"        # 랜덤재생

PLAYBACK_MODE_OPTIONS: Final = [
    PLAYBACK_MODE_SEQUENTIAL,
    PLAYBACK_MODE_ONCE,
    PLAYBACK_MODE_SHUFFLE,
]

PLAYBACK_MODE_LABELS: Final = {
    PLAYBACK_MODE_SEQUENTIAL: "순차반복",
    PLAYBACK_MODE_ONCE: "1회재생",
    PLAYBACK_MODE_SHUFFLE: "랜덤재생",
}

# ----------------------------
# Timing Constants (seconds)
# ----------------------------
STREAM_CACHE_TTL_SECONDS: Final = 600  # 10 minutes
CAST_CACHE_TTL_SECONDS: Final = 300    # 5 minutes
CAST_SCAN_INTERVAL_SECONDS: Final = 60

# ----------------------------
# API Endpoints
# ----------------------------
API_STREAM_PATH: Final = "stream"
API_M3U_PATH: Final = "m3u"
