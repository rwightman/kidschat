"""
Sound tool — finds kid-friendly sound clips to play in the chat UI.
"""

from __future__ import annotations

import logging
import os
import time
from urllib.parse import urlparse

import httpx

log = logging.getLogger("kidschat.tools.sound")

FREESOUND_SEARCH_API_URL = "https://freesound.org/apiv2/search/"
OPENVERSE_AUDIO_API_URL = "https://api.openverse.org/v1/audio/"
HTTP_HEADERS = {
    "User-Agent": "KidsChat/0.1 (local educational demo)",
}
SOUND_CACHE_TTL_SECONDS = int(os.getenv("SOUND_CACHE_TTL_SECONDS", "3600"))
FREESOUND_API_KEY = os.getenv("FREESOUND_API_KEY", "").strip()
_SOUND_CACHE: dict[str, tuple[float, dict]] = {}
PLAYABLE_AUDIO_FILETYPES = {"mp3", "ogg", "wav", "m4a", "aac", "webm"}
BLOCKED_TERMS = {
    "blood",
    "gore",
    "kill",
    "murder",
    "porn",
    "sex",
    "suicide",
}


async def play_sound(args: dict) -> dict:
    """
    Search for a short sound clip and return the best match.

    Args: {"query": "cow moo"}
    Returns: {"sounds": [{"url": "...", "title": "..."}], "text": "..."}
    """
    query = (args.get("query") or "").strip()
    if not query:
        return {"sounds": [], "text": "I need to know what sound to look for first."}

    if _contains_blocked_term(query):
        return {
            "sounds": [],
            "text": "Let's pick a different sound to play.",
        }

    cache_key = query.lower()
    cached = _get_cached_result(cache_key)
    if cached is not None:
        return cached

    if FREESOUND_API_KEY:
        try:
            result = await _search_freesound_audio(query)
            if result.get("sounds"):
                _store_cached_result(cache_key, result)
                return result
        except Exception as e:
            log.warning(f"Freesound audio search failed: {e}")

    try:
        result = await _search_openverse_audio(query)
        if result.get("sounds"):
            _store_cached_result(cache_key, result)
            return result
    except Exception as e:
        log.warning(f"Openverse audio search failed: {e}")

    result = {
        "sounds": [],
        "text": f"I couldn't find a sound for {query} right now.",
    }
    _store_cached_result(cache_key, result)
    return result


async def _search_freesound_audio(query: str) -> dict:
    """Search Freesound for short preview clips using token auth."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            FREESOUND_SEARCH_API_URL,
            params={
                "query": query,
                "page_size": 6,
                "fields": "id,name,previews,username,url,license,duration",
                "filter": "duration:[0 TO 20]",
            },
            headers={
                **HTTP_HEADERS,
                "Authorization": f"Token {FREESOUND_API_KEY}",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

    return {"sounds": _extract_freesound_sounds(data, query)}


async def _search_openverse_audio(query: str) -> dict:
    """Search Openverse for short playable audio clips."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            OPENVERSE_AUDIO_API_URL,
            params={
                "q": query,
                "page_size": 6,
                "mature": "false",
                "license": "pdm,cc0",
            },
            headers=HTTP_HEADERS,
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

    return {"sounds": _extract_openverse_sounds(data, query)}


def _extract_freesound_sounds(data: dict, query: str) -> list[dict]:
    """Extract browser-playable sound previews from Freesound results."""
    results = data.get("results", []) or []
    sounds = []

    for result in results:
        previews = result.get("previews") or {}
        url = (
            _clean_url(previews.get("preview-hq-mp3"))
            or _clean_url(previews.get("preview-hq-ogg"))
            or _clean_url(previews.get("preview-lq-mp3"))
            or _clean_url(previews.get("preview-lq-ogg"))
        )
        if not url:
            continue

        title = (result.get("name") or query).strip() or query
        sound = {
            "url": url,
            "title": title,
            "alt": title,
            "autoplay": True,
            "credit": result.get("username", "Freesound"),
        }
        page_url = _clean_url(result.get("url"))
        if page_url:
            sound["page_url"] = page_url

        sounds.append(sound)
        if len(sounds) == 3:
            break

    return sounds


def _extract_openverse_sounds(data: dict, query: str) -> list[dict]:
    """Extract short, playable audio clips from Openverse results."""
    results = data.get("results", []) or []
    sounds = []

    # Prefer Freesound-style effects when available.
    ordered_results = sorted(
        results,
        key=lambda item: 0 if "freesound" in str(item.get("source", "")).lower() else 1,
    )

    for result in ordered_results:
        url = _pick_audio_url(result)
        if not url:
            continue

        title = (result.get("title") or query).strip() or query
        sound = {
            "url": url,
            "title": title,
            "alt": title,
            "autoplay": True,
        }
        if result.get("creator"):
            sound["credit"] = result["creator"]
        if result.get("foreign_landing_url"):
            sound["page_url"] = result["foreign_landing_url"]
        elif result.get("detail_url"):
            sound["page_url"] = result["detail_url"]

        sounds.append(sound)
        if len(sounds) == 3:
            break

    return sounds


def _pick_audio_url(result: dict) -> str | None:
    """Choose a playable audio URL from an Openverse audio result."""
    primary_url = _clean_url(result.get("url"))
    if primary_url and _looks_like_playable_audio_url(
        primary_url, result.get("filetype")
    ):
        return primary_url

    alt_files = result.get("alt_files") or []
    for file_info in alt_files:
        candidate_url = _clean_url(file_info.get("url"))
        if not candidate_url or _is_known_non_browser_audio_url(candidate_url):
            continue
        if _looks_like_playable_audio_url(candidate_url, file_info.get("filetype")):
            return candidate_url

    return None


def _clean_url(value: object) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    return text or None


def _looks_like_playable_audio_url(url: str, filetype: object) -> bool:
    normalized_filetype = str(filetype or "").lower()
    if normalized_filetype in PLAYABLE_AUDIO_FILETYPES:
        return True

    path = urlparse(url).path.lower()
    return any(path.endswith(f".{ext}") for ext in PLAYABLE_AUDIO_FILETYPES)


def _is_known_non_browser_audio_url(url: str) -> bool:
    lowered = url.lower()
    return "freesound.org/apiv2/" in lowered or lowered.rstrip("/").endswith("/download")


def _contains_blocked_term(query: str) -> bool:
    lowered = query.lower()
    return any(term in lowered for term in BLOCKED_TERMS)


def _get_cached_result(cache_key: str) -> dict | None:
    cached = _SOUND_CACHE.get(cache_key)
    if not cached:
        return None

    cached_at, result = cached
    if time.monotonic() - cached_at > SOUND_CACHE_TTL_SECONDS:
        _SOUND_CACHE.pop(cache_key, None)
        return None

    return result


def _store_cached_result(cache_key: str, result: dict) -> None:
    _SOUND_CACHE[cache_key] = (time.monotonic(), result)
