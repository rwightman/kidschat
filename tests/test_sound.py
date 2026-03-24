from __future__ import annotations

import asyncio

from tests.support import install_dependency_stubs

install_dependency_stubs()

from backend.tools import sound


def test_blocked_sound_terms_are_rejected():
    result = asyncio.run(sound.play_sound({"query": "murder scream"}))

    assert result["sounds"] == []
    assert "different sound" in result["text"]


def test_extract_openverse_sounds_prefers_direct_preview_urls_over_api_downloads():
    data = {
        "results": [
            {
                "title": "Bird chirp",
                "source": "jamendo",
                "url": "https://cdn.example.org/bird-original.wav",
            },
            {
                "title": "Cow moo",
                "source": "freesound",
                "url": "https://cdn.example.org/cow-preview.mp3",
                "filetype": "mp3",
                "creator": "Farmer Ada",
                "foreign_landing_url": "https://example.org/cow",
                "alt_files": [
                    {"filetype": "json", "url": "https://cdn.example.org/cow.json"},
                    {
                        "filetype": "wav",
                        "url": "https://freesound.org/apiv2/sounds/123/download/",
                    },
                ],
            },
        ]
    }

    sounds = sound._extract_openverse_sounds(data, "cow moo")

    assert sounds[0] == {
        "url": "https://cdn.example.org/cow-preview.mp3",
        "title": "Cow moo",
        "alt": "Cow moo",
        "autoplay": True,
        "credit": "Farmer Ada",
        "page_url": "https://example.org/cow",
    }
    assert sounds[1]["url"] == "https://cdn.example.org/bird-original.wav"


def test_pick_audio_url_falls_back_to_direct_alt_file_when_primary_url_missing():
    result = {
        "title": "Bird chirp",
        "alt_files": [
            {"filetype": "json", "url": "https://cdn.example.org/meta.json"},
            {"filetype": "ogg", "url": "https://cdn.example.org/bird.ogg"},
        ],
    }

    assert sound._pick_audio_url(result) == "https://cdn.example.org/bird.ogg"


def test_play_sound_uses_cache_for_repeat_queries(monkeypatch):
    sound._SOUND_CACHE.clear()
    calls = []

    async def fake_search_openverse_audio(query):
        calls.append(query)
        return {
            "sounds": [
                {"url": "https://cdn.example.org/cow.mp3", "title": "Cow moo"}
            ]
        }

    monkeypatch.setattr(sound, "_search_openverse_audio", fake_search_openverse_audio)

    first = asyncio.run(sound.play_sound({"query": "cow moo"}))
    second = asyncio.run(sound.play_sound({"query": "Cow Moo"}))

    assert first == second
    assert calls == ["cow moo"]


def test_play_sound_returns_text_when_no_sound_is_found(monkeypatch):
    sound._SOUND_CACHE.clear()

    async def fake_search_openverse_audio(query):
        return {"sounds": []}

    monkeypatch.setattr(sound, "_search_openverse_audio", fake_search_openverse_audio)

    result = asyncio.run(sound.play_sound({"query": "dinosaur roar"}))

    assert result["sounds"] == []
    assert "couldn't find a sound" in result["text"]
