from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs

@dataclass(frozen=True)
class ParsedUrl:
    raw: str
    kind: str  # video | playlist | album | unknown
    video_id: str | None = None
    list_id: str | None = None
    browse_id: str | None = None

def parse_url(raw_url: str) -> ParsedUrl:
    raw_url = (raw_url or "").strip()
    if not raw_url:
        return ParsedUrl(raw=raw_url, kind="unknown")

    # Allow users to paste without scheme
    if "://" not in raw_url and raw_url.startswith("music.youtube.com"):
        raw_url = "https://" + raw_url
    if "://" not in raw_url and raw_url.startswith("www.youtube.com"):
        raw_url = "https://" + raw_url
    if "://" not in raw_url and raw_url.startswith("youtu.be/"):
        raw_url = "https://" + raw_url

    parsed = urlparse(raw_url)
    qs = parse_qs(parsed.query)

    host = (parsed.netloc or "").lower()
    path = parsed.path or ""

    # youtu.be/<id>
    if host.endswith("youtu.be"):
        vid = path.strip("/").split("/")[0] if path.strip("/") else None
        return ParsedUrl(raw=raw_url, kind="video", video_id=vid)

    # /watch?v=... (&list=...)
    if path.startswith("/watch"):
        vid = (qs.get("v") or [None])[0]
        lst = (qs.get("list") or [None])[0]
        if lst and not vid:
            return ParsedUrl(raw=raw_url, kind="playlist", list_id=lst)
        if lst and vid:
            # user pasted a watch URL with list; treat as playlist (start track will be the first item)
            return ParsedUrl(raw=raw_url, kind="playlist", list_id=lst, video_id=vid)
        if vid:
            return ParsedUrl(raw=raw_url, kind="video", video_id=vid)

    # /playlist?list=...
    if path.startswith("/playlist"):
        lst = (qs.get("list") or [None])[0]
        return ParsedUrl(raw=raw_url, kind="playlist", list_id=lst)

    # /browse/<id>  (albums often MPREb..., playlists sometimes VL...)
    if path.startswith("/browse/"):
        bid = path.split("/browse/")[1].split("/")[0]
        if bid.startswith("VL") and len(bid) > 2:
            return ParsedUrl(raw=raw_url, kind="playlist", list_id=bid[2:], browse_id=bid)
        if bid.startswith("MPRE"):
            return ParsedUrl(raw=raw_url, kind="album", list_id=bid, browse_id=bid)
        return ParsedUrl(raw=raw_url, kind="unknown", browse_id=bid)

    # /podcast/<id> (YouTube Music podcast)
    # Podcast IDs can be:
    # - Short IDs (11 chars like video IDs): treat as video
    # - Longer IDs (like playlist IDs): treat as playlist
    if path.startswith("/podcast/"):
        podcast_id = path.split("/podcast/")[1].split("/")[0].split("?")[0]
        if podcast_id:
            # YouTube video IDs are typically 11 characters
            if len(podcast_id) == 11:
                return ParsedUrl(raw=raw_url, kind="video", video_id=podcast_id)
            else:
                # Longer ID - treat as playlist/browse ID
                return ParsedUrl(raw=raw_url, kind="playlist", list_id=podcast_id, browse_id=podcast_id)

    # /channel/<id> (channel page - try to extract video if in URL)
    if path.startswith("/channel/"):
        # Check for video in query params
        vid = (qs.get("v") or [None])[0]
        if vid:
            return ParsedUrl(raw=raw_url, kind="video", video_id=vid)

    # fallback: if has list=... anywhere
    lst = (qs.get("list") or [None])[0]
    vid = (qs.get("v") or [None])[0]
    if lst:
        return ParsedUrl(raw=raw_url, kind="playlist", list_id=lst, video_id=vid)
    if vid:
        return ParsedUrl(raw=raw_url, kind="video", video_id=vid)

    return ParsedUrl(raw=raw_url, kind="unknown")
