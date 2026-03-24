"""
Image search tool — fetches kid-safe images.
Uses Unsplash when configured, otherwise Openverse.
"""

import logging
import os
import time

import httpx

log = logging.getLogger("kidschat.tools.search")

# You can swap this for Google Custom Search, Bing, Unsplash, etc.
# This uses the free Unsplash API as an example.
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")
OPENVERSE_API_URL = "https://api.openverse.org/v1/images/"
HTTP_HEADERS = {
    "User-Agent": "KidsChat/0.1 (local educational demo)",
}
CACHE_TTL_SECONDS = int(os.getenv("IMAGE_CACHE_TTL_SECONDS", "3600"))
_IMAGE_CACHE: dict[str, tuple[float, dict]] = {}
BLOCKED_TERMS = {
    "blood",
    "gore",
    "gun",
    "kill",
    "nude",
    "porn",
    "sex",
    "weapon",
}


async def search_images(args: dict) -> dict:
    """
    Search for kid-safe images.

    Args: {"query": "red panda"}
    Returns: {"images": [{"url": "...", "alt": "..."}]}
    """
    query = args.get("query", "")
    if not query:
        return {"images": [], "text": "I need to know what to search for!"}

    if _contains_blocked_term(query):
        return {
            "images": [],
            "text": "Let's choose a different kind of picture to look for.",
        }

    cache_key = query.strip().lower()
    cached = _get_cached_result(cache_key)
    if cached is not None:
        return cached

    # Safety filter: prepend kid-safe terms, avoid anything sketchy.
    safe_query = f"{query} for kids"

    # --- Option 1: Unsplash (free, high quality) ---
    if UNSPLASH_ACCESS_KEY:
        try:
            result = await _search_unsplash(safe_query)
            if result.get("images"):
                _store_cached_result(cache_key, result)
                return result
        except Exception as e:
            log.warning(f"Unsplash image search failed: {e}")

    # --- Option 2: Openverse (no API key) ---
    try:
        result = await _search_openverse(query)
        if result.get("images"):
            _store_cached_result(cache_key, result)
            return result
    except Exception as e:
        log.warning(f"Openverse image search failed: {e}")

    result = {
        "images": [],
        "text": f"I couldn't find a real picture of {query} right now.",
    }
    _store_cached_result(cache_key, result)
    return result


async def _search_unsplash(query: str) -> dict:
    """Search Unsplash for images."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.unsplash.com/search/photos",
            params={
                "query": query,
                "per_page": 3,
                "content_filter": "high",  # Safe content only
                "orientation": "landscape",
            },
            headers={
                "Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}",
                **HTTP_HEADERS,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

    images = []
    for result in data.get("results", [])[:3]:
        images.append({
            "url": result["urls"]["regular"],
            "alt": result.get("alt_description", query),
            "credit": result["user"]["name"],
        })

    return {"images": images}


async def _search_openverse(query: str) -> dict:
    """Search Openverse for real image thumbnails without an API key."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            OPENVERSE_API_URL,
            params={
                "q": query,
                "page_size": 3,
                "mature": "false",
                "license": "pdm,cc0",
                "excluded_source": "flickr,inaturalist,wikimedia",
            },
            headers=HTTP_HEADERS,
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

    return {"images": _extract_openverse_images(data, query)}


def _extract_openverse_images(data: dict, query: str) -> list[dict]:
    """Extract image thumbnail results from Openverse API data."""
    results = data.get("results", []) or []
    images = []

    for result in results:
        url = result.get("thumbnail") or result.get("url")
        if not url:
            continue

        title = (result.get("title") or query).strip()
        image = {
            "url": url,
            "alt": title.removeprefix("File:").replace("_", " "),
        }
        if result.get("detail_url"):
            image["page_url"] = result["detail_url"]
        elif result.get("foreign_landing_url"):
            image["page_url"] = result["foreign_landing_url"]

        images.append(image)
        if len(images) == 3:
            break

    return images


def _get_cached_result(cache_key: str) -> dict | None:
    """Return a recent cached search result, if available."""
    cached = _IMAGE_CACHE.get(cache_key)
    if not cached:
        return None

    cached_at, result = cached
    if time.monotonic() - cached_at > CACHE_TTL_SECONDS:
        _IMAGE_CACHE.pop(cache_key, None)
        return None

    return result


def _store_cached_result(cache_key: str, result: dict) -> None:
    """Store a search result in the in-memory cache."""
    _IMAGE_CACHE[cache_key] = (time.monotonic(), result)


def _contains_blocked_term(query: str) -> bool:
    lowered = query.lower()
    return any(term in lowered for term in BLOCKED_TERMS)
