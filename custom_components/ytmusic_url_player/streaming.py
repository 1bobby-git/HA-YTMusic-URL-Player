from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from aiohttp import web, ClientSession
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import get_url

from pytubefix import YouTube
from pytubefix.exceptions import BotDetection

# yt-dlp as fallback
try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False

from .const import (
    DOMAIN,
    CONF_PO_TOKEN,
    CONF_VISITOR_DATA,
    STREAM_CACHE_TTL_SECONDS,
    API_STREAM_PATH,
    API_M3U_PATH,
)
from .ytmusic_client import YTMusicClient

_LOGGER = logging.getLogger(__name__)


@dataclass
class VideoMetadata:
    """영상 메타데이터."""
    video_id: str
    title: str
    author: str
    thumbnail_url: str | None
    duration: int  # seconds
    stream_url: str
    mime_type: str

def build_stream_url(hass: HomeAssistant, video_id: str) -> str:
    base = get_url(hass, prefer_external=False)
    return f"{base}/api/{DOMAIN}/{API_STREAM_PATH}/{video_id}"

def build_m3u_url(hass: HomeAssistant, list_id: str, video_id: str | None = None) -> str:
    base = get_url(hass, prefer_external=False)
    if video_id:
        return f"{base}/api/{DOMAIN}/{API_M3U_PATH}/{list_id}.m3u?v={video_id}"
    return f"{base}/api/{DOMAIN}/{API_M3U_PATH}/{list_id}.m3u"

class StreamExtractor:
    def __init__(self, hass: HomeAssistant, config: dict[str, Any], session: ClientSession) -> None:
        self.hass = hass
        self._config = config
        self._session = session
        self._cache: dict[str, dict[str, Any]] = {}
        # po_token for bot detection bypass
        self._po_token = config.get(CONF_PO_TOKEN, "").strip() or None
        self._visitor_data = config.get(CONF_VISITOR_DATA, "").strip() or None
        if self._po_token:
            _LOGGER.info("[Stream] po_token configured (length=%d)", len(self._po_token))

    async def async_get_audio(self, video_id: str) -> tuple[str, str, dict[str, str]]:
        """오디오 스트림 URL만 반환 (기존 호환성 유지)."""
        metadata = await self.async_get_metadata(video_id)
        return metadata.stream_url, metadata.mime_type, {"User-Agent": "Mozilla/5.0"}

    async def async_get_metadata(self, video_id: str) -> VideoMetadata:
        """영상의 전체 메타데이터 반환 (썸네일, 제목 등 포함)."""
        _LOGGER.debug("[Stream] Getting metadata for video_id=%s", video_id)

        now = time.time()
        cached = self._cache.get(video_id)
        if cached and cached.get("expires", 0) > now:
            _LOGGER.debug("[Stream] Using cached metadata for %s", video_id)
            return cached["metadata"]

        loop = asyncio.get_running_loop()
        po_token = self._po_token
        visitor_data = self._visitor_data

        def _extract_pytubefix():
            """Try extraction with pytubefix using multiple client strategies."""
            _LOGGER.debug("[Stream] Trying pytubefix...")
            url = f"https://www.youtube.com/watch?v={video_id}"

            # Try multiple clients in order of reliability
            # IOS and ANDROID clients often bypass bot detection better
            clients_to_try = ['IOS', 'ANDROID', 'WEB', 'MWEB', 'TV_EMBED']

            last_error = None
            yt = None

            for client in clients_to_try:
                try:
                    _LOGGER.debug("[Stream] Trying %s client...", client)
                    yt = YouTube(url, client=client)
                    # Try to access title to verify it works
                    _ = yt.title
                    _LOGGER.debug("[Stream] %s client succeeded", client)
                    break
                except Exception as e:
                    _LOGGER.debug("[Stream] %s client failed: %s", client, e)
                    last_error = e
                    yt = None
                    continue

            if yt is None:
                # Last resort: try without specifying client
                try:
                    _LOGGER.debug("[Stream] Trying default client...")
                    yt = YouTube(url)
                    _ = yt.title
                except Exception as e:
                    _LOGGER.debug("[Stream] Default client failed: %s", e)
                    raise last_error or e

            _LOGGER.debug("[Stream] Video title: %s", yt.title)

            stream = (
                yt.streams.filter(only_audio=True)
                .order_by("abr")
                .desc()
                .first()
            )
            if not stream:
                raise RuntimeError("No audio stream found")

            _LOGGER.debug("[Stream] Found audio stream: %s, bitrate=%s",
                         stream.mime_type, stream.abr)

            _LOGGER.info("[Stream] ✓ pytubefix: '%s' by %s", yt.title, yt.author)

            return VideoMetadata(
                video_id=video_id,
                title=yt.title or "Unknown",
                author=yt.author or "Unknown",
                thumbnail_url=yt.thumbnail_url,
                duration=yt.length or 0,
                stream_url=stream.url,
                mime_type=stream.mime_type or "audio/mp4",
            )

        def _extract_ytdlp():
            """Fallback extraction with yt-dlp."""
            if not YT_DLP_AVAILABLE:
                raise RuntimeError("yt-dlp not available")

            _LOGGER.info("[Stream] Trying yt-dlp fallback...")

            ydl_opts = {
                'format': 'bestaudio/best',
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'nocheckcertificate': True,
                # Use mobile user agent to avoid some bot detection
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
                },
            }

            url = f"https://www.youtube.com/watch?v={video_id}"

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if not info:
                raise RuntimeError("yt-dlp returned no info")

            # Find best audio format
            formats = info.get('formats', [])
            audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']

            if not audio_formats:
                # Fallback to any format with audio
                audio_formats = [f for f in formats if f.get('acodec') != 'none']

            if not audio_formats:
                # Last resort: use the URL directly if available
                direct_url = info.get('url')
                if direct_url:
                    _LOGGER.info("[Stream] ✓ yt-dlp (direct): '%s'", info.get('title', 'Unknown'))
                    return VideoMetadata(
                        video_id=video_id,
                        title=info.get('title', 'Unknown'),
                        author=info.get('uploader', info.get('channel', 'Unknown')),
                        thumbnail_url=info.get('thumbnail'),
                        duration=info.get('duration', 0),
                        stream_url=direct_url,
                        mime_type='audio/mp4',
                    )
                raise RuntimeError("No audio format found")

            # Sort by audio bitrate and pick best
            audio_formats.sort(key=lambda x: x.get('abr') or 0, reverse=True)
            best_audio = audio_formats[0]

            stream_url = best_audio.get('url')
            if not stream_url:
                raise RuntimeError("No stream URL in format")

            title = info.get('title', 'Unknown')
            author = info.get('uploader', info.get('channel', 'Unknown'))
            thumbnail = info.get('thumbnail')
            duration = info.get('duration', 0)
            mime_type = best_audio.get('ext', 'mp4')
            if mime_type == 'm4a':
                mime_type = 'audio/mp4'
            elif mime_type == 'webm':
                mime_type = 'audio/webm'
            else:
                mime_type = f'audio/{mime_type}'

            _LOGGER.info("[Stream] ✓ yt-dlp: '%s' by %s", title, author)

            return VideoMetadata(
                video_id=video_id,
                title=title,
                author=author,
                thumbnail_url=thumbnail,
                duration=duration,
                stream_url=stream_url,
                mime_type=mime_type,
            )

        def _extract():
            """Try pytubefix first, fallback to yt-dlp on bot detection."""
            try:
                return _extract_pytubefix()
            except BotDetection as err:
                _LOGGER.warning("[Stream] pytubefix bot detection for %s, trying yt-dlp...", video_id)
                return _extract_ytdlp()
            except Exception as err:
                # Check if error message contains bot detection hint
                if "bot" in str(err).lower() or "BotDetection" in str(type(err).__name__):
                    _LOGGER.warning("[Stream] Possible bot detection for %s, trying yt-dlp...", video_id)
                    return _extract_ytdlp()
                raise

        try:
            metadata = await loop.run_in_executor(None, _extract)
        except Exception as err:
            _LOGGER.error("[Stream] ✗ Failed to extract metadata for %s: %s", video_id, err)
            raise

        self._cache[video_id] = {
            "metadata": metadata,
            "expires": now + STREAM_CACHE_TTL_SECONDS,
        }
        return metadata

    def _invalidate_cache(self, video_id: str) -> None:
        """Invalidate cached stream URL for a video."""
        if video_id in self._cache:
            del self._cache[video_id]
            _LOGGER.info("[Stream] Cache invalidated for %s", video_id)

    async def async_proxy(self, request: web.Request, video_id: str) -> web.StreamResponse:
        _LOGGER.info("[Proxy] Proxy request for video_id=%s from %s", video_id, request.remote)

        # Retry logic for 403 errors (expired/blocked stream URLs)
        max_retries = 2
        for attempt in range(max_retries):
            try:
                audio_url, mime, base_headers = await self.async_get_audio(video_id)
                _LOGGER.info("[Proxy] Got audio URL (length=%d), mime=%s", len(audio_url), mime)
            except Exception as err:
                _LOGGER.error("[Proxy] ✗ Failed to get audio URL for %s: %s", video_id, err)
                return web.Response(status=500, text=f"Stream extraction failed: {err}")

            req_headers = dict(base_headers)
            range_header = request.headers.get("Range")
            if range_header:
                req_headers["Range"] = range_header
                _LOGGER.debug("[Proxy] Range request: %s", range_header)

            _LOGGER.info("[Proxy] Fetching audio stream from YouTube (attempt %d/%d)...", attempt + 1, max_retries)

            try:
                async with self._session.get(audio_url, headers=req_headers, timeout=30) as resp:
                    _LOGGER.info("[Proxy] YouTube response: status=%d, content-length=%s",
                                 resp.status, resp.headers.get("Content-Length", "unknown"))

                    if resp.status == 403:
                        # Stream URL expired or blocked - invalidate cache and retry
                        if attempt < max_retries - 1:
                            _LOGGER.warning("[Proxy] YouTube returned 403, invalidating cache and retrying...")
                            self._invalidate_cache(video_id)
                            continue
                        else:
                            _LOGGER.error("[Proxy] ✗ YouTube returned 403 after %d attempts", max_retries)
                            return web.Response(status=403, text="YouTube stream blocked after retries")

                    if resp.status >= 400:
                        _LOGGER.error("[Proxy] ✗ YouTube returned error status: %d", resp.status)
                        return web.Response(status=resp.status, text=f"YouTube returned {resp.status}")

                    # Success - stream the response
                    stream_resp = web.StreamResponse(status=resp.status)
                    ct = resp.headers.get("Content-Type") or mime
                    stream_resp.content_type = ct.split(";")[0]

                    # Add CORS headers for Cast devices
                    stream_resp.headers["Access-Control-Allow-Origin"] = "*"
                    stream_resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"

                    for h in ("Content-Length", "Accept-Ranges", "Content-Range"):
                        if h in resp.headers:
                            stream_resp.headers[h] = resp.headers[h]
                    await stream_resp.prepare(request)

                    bytes_sent = 0
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        await stream_resp.write(chunk)
                        bytes_sent += len(chunk)

                    await stream_resp.write_eof()
                    _LOGGER.info("[Proxy] ✓ Streamed %d bytes for %s", bytes_sent, video_id)
                    return stream_resp

            except Exception as err:
                _LOGGER.error("[Proxy] ✗ Stream failed for %s: %s", video_id, err)
                if attempt < max_retries - 1:
                    _LOGGER.warning("[Proxy] Retrying after error...")
                    self._invalidate_cache(video_id)
                    continue
                return web.Response(status=500, text=f"Stream failed: {err}")

        # Should not reach here, but just in case
        return web.Response(status=500, text="Proxy failed after retries")

class YTMusicStreamView(HomeAssistantView):
    url = f"/api/{DOMAIN}/{API_STREAM_PATH}/{{video_id}}"
    name = f"api:{DOMAIN}:{API_STREAM_PATH}"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    def _get_extractor(self) -> StreamExtractor | None:
        """Get StreamExtractor from the first available config entry."""
        domain_data = self.hass.data.get(DOMAIN, {})
        for entry_id, store in domain_data.items():
            if isinstance(store, dict):
                extractor = store.get("extractor")
                if extractor is not None:
                    return extractor
        return None

    async def get(self, request: web.Request, video_id: str) -> web.StreamResponse:
        extractor = self._get_extractor()
        if extractor is None:
            _LOGGER.error("No StreamExtractor available")
            return web.Response(status=500, text="Stream extractor not available")

        try:
            return await extractor.async_proxy(request, video_id)
        except Exception as err:
            _LOGGER.exception("Stream failed for %s: %s", video_id, err)
            return web.Response(status=500, text="Stream failed")

class YTMusicM3UView(HomeAssistantView):
    url = f"/api/{DOMAIN}/{API_M3U_PATH}/{{list_id}}.m3u"
    name = f"api:{DOMAIN}:{API_M3U_PATH}"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    def _get_client(self) -> YTMusicClient | None:
        """Get YTMusicClient from the first available config entry."""
        domain_data = self.hass.data.get(DOMAIN, {})
        for entry_id, store in domain_data.items():
            if isinstance(store, dict):
                client = store.get("ytmusic")
                if client is not None:
                    return client
        return None

    async def get(self, request: web.Request, list_id: str) -> web.Response:
        seed_video_id = request.query.get("v")

        client = self._get_client()
        if client is None:
            _LOGGER.error("No YTMusic client available")
            return web.Response(status=500, text="YTMusic client not available")

        try:
            tracks = await client.async_get_playlist_video_ids(list_id, seed_video_id)
        except Exception as err:
            _LOGGER.exception("Failed to build playlist for %s: %s", list_id, err)
            return web.Response(status=500, text="Failed to build playlist")

        base = get_url(self.hass, prefer_external=False)

        lines = ["#EXTM3U"]
        for t in tracks:
            vid = t.get("videoId") or t.get("setVideoId")
            if not vid:
                continue
            title = t.get("title") or "YouTube Music"
            artists = t.get("artists") or []
            artist_name = ""
            if isinstance(artists, list) and artists:
                artist_name = artists[0].get("name") or ""
            label = f"{artist_name} - {title}".strip(" -")

            # 트랙 길이 (초 단위, 없으면 -1)
            duration = -1
            duration_str = t.get("duration")
            if duration_str:
                # "3:45" 형식을 초로 변환
                try:
                    parts = duration_str.split(":")
                    if len(parts) == 2:
                        duration = int(parts[0]) * 60 + int(parts[1])
                    elif len(parts) == 3:
                        duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                except (ValueError, IndexError):
                    pass
            elif t.get("duration_seconds"):
                duration = int(t.get("duration_seconds"))

            lines.append(f"#EXTINF:{duration},{label}")

            # 썸네일 URL (ytmusicapi 응답에 thumbnails 배열이 있음)
            thumbnails = t.get("thumbnails") or t.get("thumbnail") or []
            if isinstance(thumbnails, list) and thumbnails:
                # 가장 큰 썸네일 선택
                thumb_url = thumbnails[-1].get("url") if thumbnails else None
                if thumb_url:
                    lines.append(f"#EXTIMG:{thumb_url}")

            lines.append(f"{base}/api/{DOMAIN}/{API_STREAM_PATH}/{vid}")

        body = "\n".join(lines) + "\n"
        return web.Response(text=body, content_type="audio/x-mpegurl")
