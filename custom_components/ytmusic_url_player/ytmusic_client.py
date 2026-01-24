from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from typing import Any, Optional

from homeassistant.core import HomeAssistant

import ytmusicapi
from pytubefix import Playlist as PytubePlaylist

# yt-dlp as fallback for playlists
try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False

from .const import CONF_AUTH_FILE

_LOGGER = logging.getLogger(__name__)


def _parse_devtools_headers(raw_text: str) -> dict[str, str] | None:
    """
    Parse Chrome DevTools 'Request Headers' format.

    Chrome DevTools format (key and value on alternating lines):
    ```
    accept
    */*
    cookie
    VISITOR_INFO1_LIVE=xxx; SID=xxx; ...
    x-goog-authuser
    0
    ```
    """
    headers = {}
    lines = [line.strip() for line in raw_text.strip().split("\n") if line.strip()]

    # Skip lines that look like section headers or decoded content
    skip_markers = ["decoded:", "message ", "repeated ", "//"]

    i = 0
    while i < len(lines) - 1:
        key = lines[i].lower()

        # Skip if this looks like decoded content or comments
        if any(marker in key for marker in skip_markers):
            i += 1
            continue

        # Skip if key contains spaces (likely a value, not a key)
        # Headers keys don't have spaces (e.g., "content-type", "x-goog-authuser")
        if " " in key and not key.startswith("sec-"):
            i += 1
            continue

        value = lines[i + 1]

        # Skip if value looks like a header key (no spaces, short, lowercase)
        # Real values usually have special chars, spaces, or are longer
        if len(value) < 3 and value.isalpha():
            i += 1
            continue

        headers[key] = value
        i += 2

    # Validate: must have cookie
    if "cookie" in headers:
        _LOGGER.debug("Parsed %d headers from DevTools format", len(headers))
        return headers

    return None


def _build_auth_json(headers: dict[str, str]) -> dict[str, str]:
    """Build ytmusicapi-compatible auth dict from parsed headers."""
    auth = {
        "origin": "https://music.youtube.com",
        "x-origin": "https://music.youtube.com",
    }

    # Required
    if "cookie" in headers:
        auth["cookie"] = headers["cookie"]

    # Optional but useful for authenticated requests
    for key in ["x-goog-authuser", "authorization"]:
        if key in headers:
            auth[key] = headers[key]

    return auth

class YTMusicClient:
    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        self.hass = hass
        self._config = config
        self._yt: Optional[ytmusicapi.YTMusic] = None

    @property
    def yt(self) -> ytmusicapi.YTMusic:
        if not self._yt:
            raise RuntimeError("YTMusic client not initialized")
        return self._yt

    async def async_init(self) -> None:
        auth_input = (self._config.get(CONF_AUTH_FILE) or "").strip()
        loop = asyncio.get_running_loop()

        def _init():
            if not auth_input:
                _LOGGER.info("No auth provided, using anonymous mode")
                return ytmusicapi.YTMusic()

            # Parse Chrome DevTools Request Headers format
            headers = _parse_devtools_headers(auth_input)
            if headers:
                auth_data = _build_auth_json(headers)
                _LOGGER.info("Parsed Chrome DevTools headers, found %d auth fields", len(auth_data))
                # Write to temp file for ytmusicapi
                with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                    json.dump(auth_data, f)
                    temp_path = f.name
                return ytmusicapi.YTMusic(temp_path)

            _LOGGER.warning("Could not parse auth headers (cookie not found), using anonymous mode")
            return ytmusicapi.YTMusic()

        self._yt = await loop.run_in_executor(None, _init)

    async def async_close(self) -> None:
        self._yt = None

    async def async_get_playlist_video_ids(self, list_id: str, seed_video_id: str | None = None) -> list[dict[str, Any]]:
        """Return a list of track dicts with at least videoId + title + artists."""
        _LOGGER.info("[Playlist] Fetching playlist: list_id=%s, seed_video=%s", list_id, seed_video_id)
        loop = asyncio.get_running_loop()

        def _fetch():
            # Album browseIds often start with MPRE...
            if list_id.startswith("MPRE"):
                _LOGGER.debug("[Playlist] Trying get_album (MPRE prefix)")
                try:
                    data = self.yt.get_album(list_id)
                    tracks = data.get("tracks", []) or []
                    _LOGGER.info("[Playlist] ✓ get_album succeeded: %d tracks", len(tracks))
                    return tracks
                except Exception as e:
                    _LOGGER.warning("[Playlist] get_album failed for %s: %s", list_id, e)

            # OLAK5uy_ is a YouTube Music album playlist ID
            # These often fail with get_playlist, so try get_album_browse_id first
            if list_id.startswith("OLAK5uy_"):
                _LOGGER.debug("[Playlist] OLAK5uy_ detected, trying album lookup")
                try:
                    # Get album browse ID from playlist ID
                    browse_id = self.yt.get_album_browse_id(list_id)
                    if browse_id:
                        _LOGGER.debug("[Playlist] Got album browse_id: %s", browse_id)
                        data = self.yt.get_album(browse_id)
                        tracks = data.get("tracks", []) or []
                        if tracks:
                            _LOGGER.info("[Playlist] ✓ get_album (from OLAK5uy_) succeeded: %d tracks", len(tracks))
                            return tracks
                except Exception as e:
                    _LOGGER.warning("[Playlist] Album lookup failed for %s: %s", list_id, e)

            # Try get_playlist (works for most playlists)
            _LOGGER.debug("[Playlist] Trying get_playlist")
            try:
                data = self.yt.get_playlist(list_id, limit=None)
                tracks = data.get("tracks", []) or []
                if tracks:
                    _LOGGER.info("[Playlist] ✓ get_playlist succeeded: %d tracks", len(tracks))
                    return tracks
                _LOGGER.debug("[Playlist] get_playlist returned empty tracks")
            except Exception as e:
                _LOGGER.warning("[Playlist] get_playlist failed for %s: %s", list_id, e)

            # Fallback: watch playlist (e.g., RD* mixes, or when playlist fails)
            if seed_video_id:
                _LOGGER.debug("[Playlist] Trying get_watch_playlist with seed video")
                try:
                    data = self.yt.get_watch_playlist(videoId=seed_video_id, playlistId=list_id, limit=200)
                    tracks = data.get("tracks", []) or []
                    if tracks:
                        _LOGGER.info("[Playlist] ✓ get_watch_playlist succeeded: %d tracks", len(tracks))
                        return tracks
                except Exception as e:
                    _LOGGER.warning("[Playlist] get_watch_playlist failed for %s: %s", list_id, e)

                # Last resort: try with just the seed video
                _LOGGER.debug("[Playlist] Trying get_watch_playlist (video only)")
                try:
                    data = self.yt.get_watch_playlist(videoId=seed_video_id, limit=200)
                    tracks = data.get("tracks", []) or []
                    if tracks:
                        _LOGGER.info("[Playlist] ✓ get_watch_playlist (video only) succeeded: %d tracks", len(tracks))
                        return tracks
                except Exception as e:
                    _LOGGER.warning("[Playlist] get_watch_playlist (video only) failed: %s", e)

            # Fallback: use pytubefix Playlist - only get video IDs to avoid bot detection
            _LOGGER.info("[Playlist] Trying pytubefix fallback for: %s", list_id)
            try:
                pl_url = f"https://www.youtube.com/playlist?list={list_id}"
                pl = PytubePlaylist(pl_url)
                tracks = []

                # Only get video URLs/IDs - don't fetch individual video metadata
                # This is much faster and avoids triggering bot detection
                video_urls = list(pl.video_urls)
                _LOGGER.debug("[Playlist] pytubefix found %d video URLs", len(video_urls))

                for idx, url in enumerate(video_urls):
                    try:
                        # Extract video ID from URL
                        if "v=" in url:
                            vid = url.split("v=")[1].split("&")[0]
                        elif "youtu.be/" in url:
                            vid = url.split("youtu.be/")[1].split("?")[0]
                        else:
                            continue

                        # Add track with minimal info - metadata will be fetched on playback
                        tracks.append({
                            "videoId": vid,
                            "title": f"Track {idx + 1}",
                            "artists": [],
                            "thumbnails": [],
                        })
                    except Exception as ve:
                        _LOGGER.debug("[Playlist] Failed to parse video URL: %s", ve)
                        continue

                if tracks:
                    _LOGGER.info("[Playlist] ✓ pytubefix fallback succeeded: %d tracks", len(tracks))
                    return tracks
                _LOGGER.warning("[Playlist] pytubefix returned empty playlist")
            except Exception as e:
                _LOGGER.warning("[Playlist] pytubefix fallback failed for %s: %s", list_id, e)

            # Final fallback: use yt-dlp for playlist extraction
            if YT_DLP_AVAILABLE:
                _LOGGER.info("[Playlist] Trying yt-dlp fallback for: %s", list_id)
                try:
                    ydl_opts = {
                        'extract_flat': True,  # Don't download, just get info
                        'quiet': True,
                        'no_warnings': True,
                        'http_headers': {
                            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15',
                        },
                    }
                    pl_url = f"https://www.youtube.com/playlist?list={list_id}"

                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(pl_url, download=False)

                    if info and info.get('entries'):
                        tracks = []
                        for entry in info['entries']:
                            if entry and entry.get('id'):
                                tracks.append({
                                    "videoId": entry.get('id'),
                                    "title": entry.get('title', 'Unknown'),
                                    "artists": [{"name": entry.get('uploader', entry.get('channel', 'Unknown'))}],
                                    "duration_seconds": entry.get('duration', 0),
                                    "thumbnails": [{"url": entry.get('thumbnail')}] if entry.get('thumbnail') else [],
                                })
                        if tracks:
                            _LOGGER.info("[Playlist] ✓ yt-dlp fallback succeeded: %d tracks", len(tracks))
                            return tracks
                except Exception as e:
                    _LOGGER.warning("[Playlist] yt-dlp fallback failed for %s: %s", list_id, e)

            _LOGGER.error("[Playlist] ✗ All methods failed for list_id=%s", list_id)
            return []

        return await loop.run_in_executor(None, _fetch)
