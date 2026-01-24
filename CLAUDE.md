# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a Home Assistant custom component (`ytmusic_url_player`) that enables playback of YouTube Music and YouTube URLs on media players. The integration supports:
- Single track playback
- Playlist/album continuous playback with automatic queue management
- Multiple media player targets (Cast devices, DLNA, HTTP streaming)
- YouTube Music API integration with authentication support

## Architecture

### Core Components

**Integration Entry Point** (`__init__.py`)
- Creates and manages core singleton instances per config entry
- Initializes: YTMusicClient, StreamExtractor, QueueManager, CastManager
- Registers HTTP views for streaming endpoints: `/api/ytmusic_url_player/stream/{video_id}` and `/api/ytmusic_url_player/m3u/{list_id}.m3u`
- Platforms: `text` (URL input entity), `select` (target override entity)

**URL Parsing** (`url_parser.py`)
- Parses YouTube/YouTube Music URLs to extract `video_id`, `list_id` (playlist), `browse_id` (album)
- Handles multiple URL formats: `watch?v=`, `youtu.be/`, `/playlist?list=`, `/browse/MPRE...`, mix playlists (`RD*`)

**YouTube Music Client** (`ytmusic_client.py`)
- Wraps `ytmusicapi` with Home Assistant async patterns
- Supports Chrome DevTools header authentication (parses multi-line Request Headers format)
- Playlist fetching with multiple fallback strategies:
  1. `get_album()` for MPRE* browseIds
  2. `get_album_browse_id()` + `get_album()` for OLAK5uy_* album playlists
  3. `get_playlist()` for standard playlists
  4. `get_watch_playlist()` for mixes and fallback
  5. `pytubefix.Playlist` as final fallback

**Stream Extraction** (`streaming.py`)
- Extracts direct audio stream URLs from YouTube using `pytubefix` (primary) or `yt-dlp` (fallback)
- `pytubefix` uses WEB client with auto po_token generation (recommended for bot detection bypass)
- Caches stream metadata (URL, title, author, thumbnail) for 10 minutes
- Implements HTTP proxy view (`YTMusicStreamView`) for media players that can't access YouTube URLs directly
- Supports range requests for seeking
- Also provides M3U playlist generation (`YTMusicM3UView`) for playlist URLs

**Queue Manager** (`queue_manager.py`)
- Manages continuous playlist playback by monitoring media_player state changes
- When track finishes (state: `playing` → `idle`), automatically plays next track
- Uses callback pattern: `QueueManager.set_play_callback()` → `_play_single_track()`
- One queue per entity_id, tracks progress with `PlaybackQueue` dataclass

**Cast Manager** (`cast_manager.py`)
- Caches `pychromecast` device connections (5-minute TTL) to avoid repeated discovery
- Scans for Cast devices with 60-second minimum interval
- Handles friendly name matching and connection reuse

**Service Handler** (`service.py`)
- Implements `ytmusic_url_player.play_url` service
- Target resolution priority: service parameter > select entity override > config default
- Playlist handling: uses QueueManager for continuous playback, falls back to single track on error
- Single track playback: builds HA proxy URL (`/api/ytmusic_url_player/stream/{video_id}`), calls `media_player.play_media` with `audio/mp4`

**Entities**
- `text.py`: Text input entity for URL pasting, auto-plays on value change if `auto_play` config is true
- `select.py`: Select entity for temporary target media player override (Korean UI: "재생 대상")

### Data Flow

**Single Track Playback:**
1. User calls service/sets text entity → `service.py:async_play_url()`
2. URL parsed → `url_parser.parse_url()`
3. Stream pre-cached → `StreamExtractor.async_get_metadata()` (pytubefix/yt-dlp)
4. Build HA proxy URL → `{base_url}/api/ytmusic_url_player/stream/{video_id}`
5. Call `media_player.play_media` with proxy URL and metadata
6. Media player requests stream → `YTMusicStreamView.get()` → `StreamExtractor.async_proxy()` → fetches from YouTube and proxies bytes

**Playlist Playback:**
1. URL with `list_id` → `YTMusicClient.async_get_playlist_video_ids()`
2. Returns list of tracks with `videoId`, `title`, `artists`, `thumbnails`, `duration`
3. `QueueManager.start_playlist()` → plays first track via callback
4. QueueManager subscribes to media_player state changes
5. On state `playing` → `idle`: automatically calls `_play_next()` → plays next track in queue

### Key Design Patterns

- **Singleton per config entry**: Core objects (client, extractor, managers) stored in `hass.data[DOMAIN][entry_id]`
- **Fallback cascade**: YouTube Music API → pytubfix → yt-dlp (for streams); get_album → get_playlist → get_watch_playlist → pytubefix (for playlists)
- **HA internal proxy**: Builds local network URLs (`prefer_external=False`) for Cast devices, proxies YouTube streams through HA HTTP server to bypass bot detection and handle authentication
- **Async executor pattern**: Blocking YouTube API calls run in `loop.run_in_executor(None, ...)`

## Configuration

**Config Flow** (`config_flow.py`)
- `CONF_NAME`: Integration instance name (default: "YouTube Music URL Player")
- `CONF_MEDIA_PLAYER`: Default target media player entity IDs (can be multiple)
- `CONF_AUTH_FILE`: Chrome DevTools Request Headers (multi-line text) for authenticated YouTube Music access
- `CONF_AUTO_PLAY`: Enable auto-play when text entity value changes (default: True)
- `CONF_PO_TOKEN`, `CONF_VISITOR_DATA`: Optional tokens for bot detection bypass (legacy, now auto-handled by pytubefix WEB client)

**Constants** (`const.py`)
- `DOMAIN = "ytmusic_url_player"`
- Internal data keys: `DATA_YTMUSIC`, `DATA_EXTRACTOR`, `DATA_QUEUE_MANAGER`, `DATA_CAST_MANAGER`, `DATA_TARGET_OVERRIDE`
- Playback strategies (internal): `STRATEGY_CAST_NATIVE`, `STRATEGY_DIRECT_STREAM`, `STRATEGY_PROXY_INTERNAL`, `STRATEGY_PROXY_EXTERNAL`

## Development

### Testing Changes

Since this is a Home Assistant custom component, testing requires a running Home Assistant instance:

1. Copy the `custom_components/ytmusic_url_player` folder to your HA config directory's `custom_components/` folder
2. Restart Home Assistant
3. Add integration via UI: Configuration → Integrations → Add Integration → "YouTube Music URL Player"
4. Test service calls via Developer Tools → Services:
   ```yaml
   service: ytmusic_url_player.play_url
   data:
     url: "https://music.youtube.com/watch?v=VIDEO_ID"
     media_player: media_player.your_device
   ```
5. Check logs: Configuration → Logs, filter for `ytmusic_url_player`

### Common Development Workflows

**Adding new URL format support:**
- Modify `url_parser.py:parse_url()` to detect and extract IDs
- Update `ParsedUrl.kind` if needed
- Test with various URL formats

**Changing stream extraction logic:**
- Modify `streaming.py:StreamExtractor.async_get_metadata()`
- Update `_extract_pytubefix()` for pytubefix changes
- Update `_extract_ytdlp()` for yt-dlp changes
- Be careful with bot detection: pytubefix WEB client now auto-generates po_token

**Modifying playlist fetching:**
- Update `ytmusic_client.py:async_get_playlist_video_ids()`
- Follow existing fallback pattern: try method, log result, fall through on error
- Ensure returned tracks have: `videoId`, `title`, `artists` (list of dicts with `name`), `thumbnails`, `duration`

**Adding new entity platforms:**
- Add platform to `PLATFORMS` list in `__init__.py`
- Create entity file following Home Assistant patterns (see `text.py`, `select.py`)

### Code Patterns to Follow

**Logging:**
```python
_LOGGER.info("[Component] Major event")  # Success, important state changes
_LOGGER.debug("[Component] Detail")      # Verbose debugging
_LOGGER.warning("[Component] Fallback")  # Non-fatal issues
_LOGGER.error("[Component] ✗ Failed")    # Fatal errors
_LOGGER.info("[Component] ✓ Success")    # Successful operations
```

**Async Executor for Blocking Calls:**
```python
loop = asyncio.get_running_loop()
result = await loop.run_in_executor(None, blocking_function)
```

**Accessing Integration Data:**
```python
domain_data = hass.data.get(DOMAIN, {})
for entry_id, store in domain_data.items():
    if isinstance(store, dict):
        client = store.get(DATA_YTMUSIC)
```

### Dependencies

See `manifest.json`:
- `ytmusicapi==1.9.1`: YouTube Music API client
- `pytubefix>=10.3.0`: YouTube stream extraction (primary)
- `yt-dlp>=2024.1.0`: YouTube stream extraction (fallback)
- `pychromecast>=14.0.0`: Cast device communication

### Troubleshooting

**Bot detection errors from YouTube:**
- pytubefix 8.12+ handles this automatically with WEB client
- Fallback to yt-dlp happens automatically
- User can provide `po_token` + `visitor_data` in config if needed

**Playlist not loading:**
- Check logs for which method succeeded/failed
- Different playlist types use different APIs: albums (MPRE*, OLAK5uy_*), playlists, mixes (RD*)
- Final fallback uses pytubefix.Playlist which works for most public playlists

**Stream playback fails:**
- Check if HA proxy URL is accessible from media player's network
- Verify base URL in logs (`get_url(hass, prefer_external=False)`)
- Ensure no firewall blocking port 8123
- Check if stream extraction succeeded (cached metadata in logs)

**Queue not advancing:**
- QueueManager tracks state changes: `playing` → `idle` triggers next track
- Some media players don't report `idle` state correctly
- Check entity state transitions in HA Developer Tools → States
