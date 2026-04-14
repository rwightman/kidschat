from __future__ import annotations

import asyncio

from tests.support import install_dependency_stubs

install_dependency_stubs()

from backend.tools import search


def test_blocked_terms_are_rejected():
    result = asyncio.run(search.search_images({"query": "toy gun"}))

    assert result["images"] == []
    assert "different kind of picture" in result["text"]


def test_search_prefers_openverse_results_without_unsplash(monkeypatch):
    search._IMAGE_CACHE.clear()

    async def fake_search_pexels(query):
        raise AssertionError("Pexels should not be queried without an API key")

    async def fake_search_openverse(query):
        assert query == "red panda"
        return {
            "images": [
                {"url": "https://cdn.example.org/red-panda.jpg", "alt": "Red panda"}
            ]
        }

    monkeypatch.setattr(search, "_search_pexels", fake_search_pexels)
    monkeypatch.setattr(search, "_search_openverse", fake_search_openverse)
    monkeypatch.setattr(search, "PEXELS_API_KEY", "")
    monkeypatch.setattr(search, "UNSPLASH_ACCESS_KEY", "")

    result = asyncio.run(search.search_images({"query": "red panda"}))

    assert result["images"] == [
        {"url": "https://cdn.example.org/red-panda.jpg", "alt": "Red panda"}
    ]


def test_openverse_results_extract_real_thumbnails():
    data = {
        "results": [
            {
                "title": "Rhinoceros",
                "thumbnail": "https://cdn.example.org/rhino-thumb.jpg",
                "detail_url": "https://openverse.org/image/123",
            },
            {
                "title": "No thumbnail here",
            },
        ]
    }

    images = search._extract_openverse_images(data, "rhinoceros")

    assert images == [
        {
            "url": "https://cdn.example.org/rhino-thumb.jpg",
            "alt": "Rhinoceros",
            "page_url": "https://openverse.org/image/123",
        }
    ]


def test_pexels_results_extract_large_images():
    data = {
        "photos": [
            {
                "alt": "Red panda in a tree",
                "photographer": "Ava Lens",
                "url": "https://www.pexels.com/photo/red-panda-123/",
                "src": {
                    "medium": "https://images.pexels.com/photos/123/medium.jpeg",
                    "large": "https://images.pexels.com/photos/123/large.jpeg",
                },
            }
        ]
    }

    images = search._extract_pexels_images(data, "red panda")

    assert images == [
        {
            "url": "https://images.pexels.com/photos/123/large.jpeg",
            "alt": "Red panda in a tree",
            "credit": "Ava Lens",
            "page_url": "https://www.pexels.com/photo/red-panda-123/",
        }
    ]


def test_search_returns_text_only_when_no_real_images_are_found(monkeypatch):
    search._IMAGE_CACHE.clear()

    async def fake_search_pexels(query):
        return {"images": []}

    async def fake_search_openverse(query):
        return {"images": []}

    monkeypatch.setattr(search, "_search_pexels", fake_search_pexels)
    monkeypatch.setattr(search, "_search_openverse", fake_search_openverse)
    monkeypatch.setattr(search, "PEXELS_API_KEY", "")
    monkeypatch.setattr(search, "UNSPLASH_ACCESS_KEY", "")

    result = asyncio.run(search.search_images({"query": "red panda"}))

    assert result["images"] == []
    assert "couldn't find a real picture" in result["text"]


def test_search_uses_cache_for_repeat_queries(monkeypatch):
    search._IMAGE_CACHE.clear()
    calls = []

    async def fake_search_pexels(query):
        raise AssertionError("Pexels should not be queried without an API key")

    async def fake_search_openverse(query):
        calls.append(query)
        return {
            "images": [
                {"url": "https://cdn.example.org/red-panda.jpg", "alt": "Red panda"}
            ]
        }

    monkeypatch.setattr(search, "_search_pexels", fake_search_pexels)
    monkeypatch.setattr(search, "_search_openverse", fake_search_openverse)
    monkeypatch.setattr(search, "PEXELS_API_KEY", "")
    monkeypatch.setattr(search, "UNSPLASH_ACCESS_KEY", "")

    first = asyncio.run(search.search_images({"query": "red panda"}))
    second = asyncio.run(search.search_images({"query": "Red Panda"}))

    assert first == second
    assert calls == ["red panda"]


def test_search_prefers_pexels_when_api_key_is_configured(monkeypatch):
    search._IMAGE_CACHE.clear()
    calls = []

    async def fake_search_pexels(query):
        calls.append(("pexels", query))
        return {
            "images": [
                {"url": "https://images.pexels.com/photos/123/cat.jpeg", "alt": "Cat"}
            ]
        }

    async def fake_search_unsplash(query):
        calls.append(("unsplash", query))
        return {
            "images": [
                {"url": "https://images.unsplash.com/cat.jpg", "alt": "Cat"}
            ]
        }

    async def fake_search_openverse(query):
        calls.append(("openverse", query))
        return {
            "images": [
                {"url": "https://cdn.example.org/cat.jpg", "alt": "Cat"}
            ]
        }

    monkeypatch.setattr(search, "PEXELS_API_KEY", "test-key")
    monkeypatch.setattr(search, "UNSPLASH_ACCESS_KEY", "test-unsplash")
    monkeypatch.setattr(search, "_search_pexels", fake_search_pexels)
    monkeypatch.setattr(search, "_search_unsplash", fake_search_unsplash)
    monkeypatch.setattr(search, "_search_openverse", fake_search_openverse)

    result = asyncio.run(search.search_images({"query": "cat"}))

    assert result["images"][0]["url"] == "https://images.pexels.com/photos/123/cat.jpeg"
    assert calls == [("pexels", "cat for kids")]
