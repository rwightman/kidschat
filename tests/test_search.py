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

    async def fake_search_openverse(query):
        assert query == "red panda"
        return {
            "images": [
                {"url": "https://cdn.example.org/red-panda.jpg", "alt": "Red panda"}
            ]
        }

    monkeypatch.setattr(search, "_search_openverse", fake_search_openverse)
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


def test_search_returns_text_only_when_no_real_images_are_found(monkeypatch):
    search._IMAGE_CACHE.clear()

    async def fake_search_openverse(query):
        return {"images": []}

    monkeypatch.setattr(search, "_search_openverse", fake_search_openverse)
    monkeypatch.setattr(search, "UNSPLASH_ACCESS_KEY", "")

    result = asyncio.run(search.search_images({"query": "red panda"}))

    assert result["images"] == []
    assert "couldn't find a real picture" in result["text"]


def test_search_uses_cache_for_repeat_queries(monkeypatch):
    search._IMAGE_CACHE.clear()
    calls = []

    async def fake_search_openverse(query):
        calls.append(query)
        return {
            "images": [
                {"url": "https://cdn.example.org/red-panda.jpg", "alt": "Red panda"}
            ]
        }

    monkeypatch.setattr(search, "_search_openverse", fake_search_openverse)
    monkeypatch.setattr(search, "UNSPLASH_ACCESS_KEY", "")

    first = asyncio.run(search.search_images({"query": "red panda"}))
    second = asyncio.run(search.search_images({"query": "Red Panda"}))

    assert first == second
    assert calls == ["red panda"]
