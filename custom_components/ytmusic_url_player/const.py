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
CONF_ALLOW_UNAUTHENTICATED: Final = "allow_unauthenticated_streams"

# ----------------------------
# Default Values
# ----------------------------
DEFAULT_NAME: Final = "YouTube Music URL Player"
DEFAULT_AUTO_PLAY: Final = True
DEFAULT_ALLOW_UNAUTHENTICATED: Final = False

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
# A playing -> idle change this soon after a play command is the previous
# content stopping, not the new track ending.
QUEUE_IDLE_GRACE_SECONDS: Final = 10
# Skip a queued track the player has not started this long after the command.
QUEUE_START_TIMEOUT_SECONDS: Final = 90
# End the queue after this many tracks in a row failed to play or start.
QUEUE_MAX_CONSECUTIVE_FAILURES: Final = 3
# Unauthenticated stream requests are allowed for tracks this integration
# played or listed, for this long.
STREAM_GRANT_TTL_SECONDS: Final = 24 * 3600
# Large enough for a full M3U of a big library (playlists hold up to 5000).
STREAM_GRANT_MAX_ENTRIES: Final = 10000

# media_player supported_features bits (MediaPlayerEntityFeature)
MEDIA_PLAYER_FEATURE_PAUSE: Final = 1
MEDIA_PLAYER_FEATURE_STOP: Final = 4096

# ----------------------------
# API Endpoints
# ----------------------------
API_STREAM_PATH: Final = "stream"
API_M3U_PATH: Final = "m3u"
